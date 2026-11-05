"""Uruguay (URY): descarga y procesa series macro de fuentes oficiales.

Fuentes (todas públicas, sin clave):
- Banco Central del Uruguay (BCU): planillas Excel del sitio (cuentas nacionales, agregados
  monetarios, reservas, comercio exterior, balanza de pagos, tasas y créditos de la SSF,
  encuesta de expectativas), exportación Excel de las listas del sitio (IMAE, Tasa 1 día) y el
  web service SOAP de cotizaciones (`cotizaciones.bcu.gub.uy`).
- Instituto Nacional de Estadística (INE, `www5.ine.gub.uy`): IPC, IPC subyacente, ECH
  (desempleo), Unidad Indexada, Índice Medio de Salarios, Salario Mínimo Nacional.
- Ministerio de Economía y Finanzas (MEF): planilla "Economic Indicators" de la Unidad de
  Gestión de Deuda y planilla mensual de resultados del sector público.

Dos pasos separados:
1. Descargar: guarda cada archivo tal cual con `comun.save_raw` en `data/raw/URY/<fuente>/`.
2. Procesar: lee SOLO `data/raw/URY/` y escribe `data/interim/URY_observaciones.parquet`.

Uso:
    python src/paises/ury.py                          # descarga + procesa (todas las activas)
    python src/paises/ury.py --solo-procesar          # solo reconstruye el parquet desde data/raw
    python src/paises/ury.py --serie ipc_indice tc_usd_diario   # descarga solo esas series
    python src/paises/ury.py --pausa 2                # segundos entre peticiones (mínimo 1)

`--serie` limita la DESCARGA; el procesamiento siempre reconstruye el parquet con todas las
series activas.

`codigo_fuente` en config/series/URY.csv:  `<archivo>|<hoja>|<etiqueta>[|<subetiqueta>][#transf+...]`
- `<archivo>` es el nombre del archivo en data/raw/URY (ver SOURCES: de ahí sale la URL).
- `<hoja>`: nombre de la hoja; varias separadas por ';'; '*' = todas.
- `<etiqueta>`: texto de la fila (cuadros "anchos", con periodos en columnas) o de la columna
  (cuadros "largos", con periodos en filas). Se busca por texto, sin depender de la posición.
- Dos selectores unidos por ' - ' restan una serie de otra (balanza comercial).
Transformaciones: las mismas de bra.py (desde, esc, neg, fin_mes, prom_mes, suma_trim,
suma_anual=n, dic, var12m, acum12m) más `ffill_mes` (escalonada por fechas de vigencia →
mensual hasta el mes en curso).

Trampas resueltas aquí (detalle en docs/fuentes/URY.md):
- www.bcu.gub.uy, cotizaciones.bcu.gub.uy y www5.ine.gub.uy no envían el certificado
  intermedio: se completa la cadena descargando los intermedios por AIA (sin desactivar la
  verificación TLS).
- Las listas del sitio del BCU se cargan por JavaScript; se usa la exportación Excel del
  handler `BCUListasHandler.ashx`, que genera un archivo distinto en cada descarga: solo se
  guarda si cambió el contenido.
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import logging
import re
import socket
import ssl
import sys
import tempfile
import time
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote, urljoin

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import comun  # noqa: E402

ISO3 = "URY"
BCU = "https://www.bcu.gub.uy/"
INE = "https://www5.ine.gub.uy/documents/"
BCU_LIST_HANDLER = BCU + "_layouts/15/BCU.Portal2016/BCUListasHandler.ashx"
BCU_WS = "https://cotizaciones.bcu.gub.uy/wscotizaciones/servlet/awsbcucotizaciones"
MEF_RESULTS_PAGE = ("https://www.gub.uy/ministerio-economia-finanzas/datos-y-estadisticas/"
                    "estadisticas/informacion-resultados-del-sector-publico")
TLS_HOSTS = ("www.bcu.gub.uy", "cotizaciones.bcu.gub.uy", "www5.ine.gub.uy")
WS_FIRST_YEAR = 2000          # el web service no tiene cotizaciones anteriores
WS_CURRENCY = 2225            # DLS. USA BILLETE

# archivo raw → (carpeta, tipo de descarga, url o parámetros)
SOURCES: dict[str, tuple[str, str, object]] = {
    "Actividades_K.xlsx": ("bcu", "get", BCU + "Estadisticas-e-Indicadores/Cuentas Nacionales/1. Actividades_K.xlsx"),
    "Actividades_C.xlsx": ("bcu", "get", BCU + "Estadisticas-e-Indicadores/Cuentas Nacionales/2. Actividades_C.xlsx"),
    "Desestacionalizado.xlsx": ("bcu", "get", BCU + "Estadisticas-e-Indicadores/Cuentas Nacionales/5. Desestacionalizado.xlsx"),
    "imae.xlsx": ("bcu", "lista", {"siteUrl": BCU + "Estadisticas-e-Indicadores/", "listName": "IMAE"}),
    "tasa_1_dia.xlsx": ("bcu", "lista", {"siteUrl": BCU + "Politica-Economica-y-Mercados/", "listName": "Tasa 1 Día"}),
    "tasas.xls": ("bcu", "get", BCU + "Servicios-Financieros-SSF/Series IF/tasas.xls"),
    "Creditos.xlsx": ("bcu", "get", BCU + "Servicios-Financieros-SSF/Series IF/Creditos.xlsx"),
    "pmam03d.xls": ("bcu", "get", BCU + "Estadisticas-e-Indicadores/Principales-Agregados-Monetarios/pmam03d.xls"),
    # La carpeta se llama así en el sitio del BCU (le faltan las letras con tilde).
    "IEES05I2.xlsx": ("bcu", "get", BCU + "Politica-Economica-y-Mercados/Expectativas para la inflacin y la economa/IEES05I2.xlsx"),
    "reservas.xls": ("bcu", "get", BCU + "Estadisticas-e-Indicadores/MonedayCredito/Activos-de-Reserva/reservas.xls"),
    "exp_ciiu_val.xls": ("bcu", "get", BCU + "Estadisticas-e-Indicadores/ComercioExterior_ICB/exp_ciiu_val.xls"),
    "imp_gce_val.xls": ("bcu", "get", BCU + "Estadisticas-e-Indicadores/ComercioExterior_ICB/imp_gce_val.xls"),
    "dse_bp_m6_arm_scn.xlsx": ("bcu", "get", BCU + "Estadisticas-e-Indicadores/Balanza de Pagos/dse_bp_m6_arm_scn.xlsx"),
    "cotizaciones_2225": ("bcu_cotizaciones", "ws", WS_CURRENCY),
    "ipc_general_base2022.xlsx": ("ine", "get", INE + "Estadísticaseconómicas/SERIES Y OTROS/IPC/Base Octubre 2022=100/IPC gral y variaciones_base 2022.xlsx"),
    "ipc_subyacente.xlsx": ("ine", "get", INE + "Estadísticaseconómicas/SERIES Y OTROS/IPC/Base Octubre 2022=100/IPC_Cuadro_inflación subyacente.xlsx"),
    "ECH0013.xlsx": ("ine", "get", INE + "DemografíayEESS/SERIES Y OTROS/ECH/Series históricas/Actividad, empleo y desempleo/ECH0013.xlsx"),
    "unidad_indexada.xls": ("ine", "get", INE + "Estadísticaseconómicas/SERIES Y OTROS/UI/Unidad Indexada.xls"),
    "IMSN_M_B08.xls": ("ine", "get", INE + "Estadísticaseconómicas/SERIES Y OTROS/IMS/Base Julio 2008=100/IMSN M B08.xls"),
    "salario_minimo_nacional.xls": ("ine", "get", INE + "Estadísticaseconómicas/SERIES Y OTROS/IMS/Salario Mínimo Nacional.xls"),
    "economic-indicators-web.xlsx": ("mef", "get", "https://deuda.mef.gub.uy/innovaportal/file/6473/1/economic-indicators-web.xlsx"),
    "resultados_sector_publico.xlsx": ("mef", "enlace", (MEF_RESULTS_PAGE, r"""href=['"]([^'"]*Resultados[^'"]*\.xlsx)['"]""")),
}

MONTHS = {m: i + 1 for i, m in enumerate(
    ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "set", "oct", "nov", "dic"])}
MONTHS["sep"] = 9
MONTHS_FULL = {m: i + 1 for i, m in enumerate(
    ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "setiembre",
     "octubre", "noviembre", "diciembre"])}
MONTHS_FULL["septiembre"] = 9
ROMAN_Q = {"I": 1, "II": 2, "III": 3, "IV": 4}

log = logging.getLogger("data_macro_paises.ury")


# --------------------------------------------------------------------------- TLS

def ca_bundle() -> str:
    """certifi + certificados intermedios que los servidores uruguayos no envían.

    Se descargan por AIA (caIssuers del certificado del servidor) y se agregan al almacén de
    certifi. No se agregan raíces: la cadena se sigue validando contra las raíces de certifi.
    """
    import certifi
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding
    from cryptography.x509.oid import AuthorityInformationAccessOID

    pems = []
    for host in TLS_HOSTS:
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE  # solo para leer el certificado
            with socket.create_connection((host, 443), timeout=30) as s, \
                    ctx.wrap_socket(s, server_hostname=host) as ss:
                cert = x509.load_der_x509_certificate(ss.getpeercert(binary_form=True))
            for _ in range(3):
                try:
                    aia = cert.extensions.get_extension_for_class(x509.AuthorityInformationAccess).value
                except x509.ExtensionNotFound:
                    break
                urls = [d.access_location.value for d in aia
                        if d.access_method == AuthorityInformationAccessOID.CA_ISSUERS]
                if not urls:
                    break
                data = requests.get(urls[0], timeout=60).content
                try:
                    cert = x509.load_der_x509_certificate(data)
                except ValueError:
                    try:
                        cert = x509.load_pem_x509_certificate(data)
                    except ValueError:
                        break
                if cert.issuer == cert.subject:      # raíz: no se agrega
                    break
                pems.append(cert.public_bytes(Encoding.PEM).decode())
        except (OSError, requests.RequestException) as e:
            log.warning("No se pudo completar la cadena TLS de %s: %s", host, e)
    path = Path(tempfile.gettempdir()) / "data_macro_paises_ury_ca.pem"
    path.write_text(Path(certifi.where()).read_text(encoding="utf-8") + "\n" + "\n".join(pems),
                    encoding="utf-8")
    return str(path)


# --------------------------------------------------------------------------- descarga

def split_code(codigo_fuente: str) -> tuple[list[list[str]], list[str]]:
    """'a.xls|H|X - b.xls|H|Y#esc=0.001' → ([['a.xls','H','X'], ['b.xls','H','Y']], ['esc=0.001'])."""
    base, _, transf = codigo_fuente.partition("#")
    selectors = [[p.strip() for p in part.split("|")] for part in base.split(" - ")]
    return selectors, [t.strip() for t in transf.split("+") if t.strip()]


def files_for(row: dict) -> list[str]:
    selectors, _ = split_code(row["codigo_fuente"])
    return [sel[0] for sel in selectors]


def file_kind(content: bytes) -> str:
    if content[:4] == b"PK\x03\x04":
        return "xlsx"
    if content[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return "xls"
    return "otro"


def encode_url(url: str) -> str:
    return quote(url, safe=":/=,&?%")


def download(series: list[dict], client: comun.Client, today: dt.date) -> int:
    files = []
    for row in series:
        for f in files_for(row):
            if f not in files:
                files.append(f)
    log.info("Descarga: %d archivos para %d series", len(files), len(series))
    errors = 0
    for name in files:
        if name not in SOURCES:
            log.error("  %s: no está en SOURCES", name)
            errors += 1
            continue
        folder, kind, spec = SOURCES[name]
        try:
            if kind == "ws":
                errors += download_ws(client, folder, name, int(spec), today)
                continue
            if kind == "get":
                url = encode_url(str(spec))
                content = client.get(url).content
            elif kind == "lista":
                url, content = download_list(client, dict(spec))
            elif kind == "enlace":
                page, pattern = spec
                html = client.get(page).text
                m = re.search(pattern, html)
                if not m:
                    raise ValueError(f"no se encontró el enlace al Excel en {page}")
                url = encode_url(urljoin(page, m.group(1)))
                content = client.get(url).content
            else:
                raise ValueError(f"tipo de descarga desconocido: {kind}")
            if file_kind(content) == "otro":
                raise ValueError(f"no es un Excel: {content[:120]!r}")
            if kind == "lista" and same_excel_content(folder, name, content):
                log.info("  %-50s sin_cambios (mismo contenido; el Excel exportado cambia en cada descarga)",
                         f"{folder}/{name}")
                continue
            action = comun.save_raw(ISO3, folder, name, content, url)
            log.info("  %-50s %s", f"{folder}/{name}", action)
        except (requests.RequestException, ValueError) as e:
            errors += 1
            log.error("  %s/%s: %s", folder, name, e)
    return errors


def download_list(client: comun.Client, params: dict) -> tuple[str, bytes]:
    """Exportación Excel de una lista del sitio del BCU (lo mismo que el botón 'Excel')."""
    data = {"action": "export", "siteUrl": params["siteUrl"], "listName": params["listName"],
            "viewName": "Todos", "viewAvanzada": "", "filters": "[]", "search": "",
            "order[0][column]": 0, "order[0][dir]": "asc", "title": params["listName"],
            "userSort": "false"}
    r = client.post(BCU_LIST_HANDLER, data=data)
    url = f"{BCU_LIST_HANDLER}?action=export&listName={quote(params['listName'])}"
    return url, r.content


def same_excel_content(folder: str, name: str, content: bytes) -> bool:
    path = comun.raw_path(ISO3, folder, name)
    if not path.exists():
        return False
    try:
        old = pd.read_excel(path, sheet_name=None, header=None)
        new = pd.read_excel(io.BytesIO(content), sheet_name=None, header=None)
    except ValueError:
        return False
    return old.keys() == new.keys() and all(old[k].equals(new[k]) for k in old)


WS_BODY = """<?xml version="1.0" encoding="utf-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:cot="Cotiza">
<soapenv:Header/><soapenv:Body><cot:wsbcucotizaciones.Execute><cot:Entrada>
<cot:Moneda><cot:item>{moneda}</cot:item></cot:Moneda><cot:FechaDesde>{desde}</cot:FechaDesde>
<cot:FechaHasta>{hasta}</cot:FechaHasta><cot:Grupo>0</cot:Grupo>
</cot:Entrada></cot:wsbcucotizaciones.Execute></soapenv:Body></soapenv:Envelope>"""


def download_ws(client: comun.Client, folder: str, name: str, currency: int, today: dt.date) -> int:
    """Web service de cotizaciones: un año por consulta (rechaza rangos mayores). Los años
    cerrados no se revisan: solo se vuelven a pedir el año en curso, el anterior y los que
    falten en data/raw."""
    errors = 0
    for year in range(WS_FIRST_YEAR, today.year + 1):
        fname = f"{name}_{year}.xml"
        if comun.raw_path(ISO3, folder, fname).exists() and year < today.year - 1:
            continue
        body = WS_BODY.format(moneda=currency, desde=f"{year}-01-01",
                              hasta=min(dt.date(year, 12, 31), today).isoformat())
        try:
            r = client.post(BCU_WS, data=body.encode("utf-8"),
                            headers={"Content-Type": "text/xml; charset=utf-8",
                                     "SOAPAction": "Cotizaction/AWSBCUCOTIZACIONES.Execute"})
            status = re.search(rb"<status>(\d)</status>", r.content)
            if not status or status.group(1) != b"1":
                msg = re.search(rb"<mensaje>([^<]*)</mensaje>", r.content)
                raise ValueError(f"el web service respondió error: {msg.group(1)[:100] if msg else r.content[:100]!r}")
            action = comun.save_raw(ISO3, folder, fname, r.content, f"{BCU_WS} (SOAP, moneda {currency}, {year})")
            log.info("  %-50s %s", f"{folder}/{fname}", action)
        except (requests.RequestException, ValueError) as e:
            errors += 1
            log.error("  %s/%s: %s", folder, fname, e)
    return errors


# --------------------------------------------------------------------------- utilidades de lectura

def norm(x) -> str:
    """Texto normalizado para comparar etiquetas: sin tildes, minúsculas, espacios simples."""
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return ""
    s = unicodedata.normalize("NFKD", str(x))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


def to_float(v) -> float:
    """Número desde celdas de Excel: admite '6,00%', '1.234,5'. Lo demás → NaN."""
    if isinstance(v, bool):
        return float("nan")
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("%", "").replace("\xa0", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return float("nan")


def to_date(v) -> pd.Timestamp | None:
    """Fechas de las celdas: datetime, 'Set-05' (mes abreviado y año de 2 dígitos),
    'dd/mm/aaaa' o 'dd-mm-aaaa'. Números y textos no reconocidos → None."""
    if isinstance(v, (dt.datetime, dt.date, pd.Timestamp)):
        return pd.Timestamp(v)
    if not isinstance(v, str):
        return None
    s = norm(v)
    m = re.fullmatch(r"([a-z]{3})[a-z]*[-/ .](\d{2}|\d{4})", s)
    if m and m.group(1) in MONTHS:
        y = int(m.group(2))
        y = y + (2000 if y < 50 else 1900) if y < 100 else y
        return pd.Timestamp(y, MONTHS[m.group(1)], 1)
    m = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", s)
    if m:
        return pd.Timestamp(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    return None


def numbers(values: list, label: str) -> pd.Series:
    """Convierte a número y deja constancia de los descartes ('n/d', '-', '..', textos)."""
    raw = pd.Series(values, dtype=object)
    num = raw.map(to_float)
    bad = raw[num.isna() & raw.notna() & (raw.astype(str).str.strip() != "")]
    if len(bad):
        log.info("    %s: %d valores no numéricos descartados %s", label, len(bad),
                 sorted({str(v) for v in bad})[:5])
    return num


def read_sheets(path: Path, sheets: str) -> dict[str, pd.DataFrame]:
    book = pd.read_excel(path, sheet_name=None, header=None)
    if sheets == "*":
        return book
    out = {}
    for s in sheets.split(";"):
        match = [k for k in book if norm(k) == norm(s)]
        if not match:
            raise ValueError(f"{path.name}: no existe la hoja '{s}' (hay {list(book)})")
        out[match[0]] = book[match[0]]
    return out


def find_header_row(df: pd.DataFrame, label: str, max_rows: int = 40) -> tuple[int, int]:
    """Primera celda (fila, col) cuyo texto normalizado empieza con `label`."""
    target = norm(label)
    for r in range(min(max_rows, len(df))):
        for c, v in enumerate(df.iloc[r].tolist()):
            if norm(v).startswith(target) and target:
                return r, c
    raise ValueError(f"no se encontró el encabezado '{label}'")


def find_col(df: pd.DataFrame, rows: list[int], label: str, min_col: int = 0,
             max_col: int | None = None) -> int:
    """Columna cuyo encabezado (en alguna de `rows`) coincide con `label`: primero igualdad
    exacta normalizada, si no, 'empieza con' (debe ser única)."""
    target = norm(label)
    exact, prefix = [], []
    for r in rows:
        if r < 0 or r >= len(df):
            continue
        for c, v in enumerate(df.iloc[r].tolist()):
            if c < min_col or (max_col is not None and c >= max_col):
                continue
            n = norm(v)
            if n == target:
                exact.append(c)
            elif n.startswith(target) or (len(target) > 8 and target in n):
                prefix.append(c)
    if exact:
        return min(exact)
    if prefix:
        return min(prefix)
    raise ValueError(f"no se encontró la columna '{label}'")


# --------------------------------------------------------------------------- parsers

def parse_long(df: pd.DataFrame, sel: list[str], label: str) -> pd.DataFrame:
    """Cuadro 'largo': periodos en filas. sel = [archivo, hoja, columna, (subcolumna)].
    La columna de fechas es la del encabezado 'Fecha', 'Mes', 'Mes y año'... (la primera fila
    de encabezado que se encuentre)."""
    header_labels = ["fecha encuesta", "fecha de vigencia", "mes y ano", "fecha", "mes"]
    hr = hc = None
    for h in header_labels:
        try:
            hr, hc = find_header_row(df, h)
            break
        except ValueError:
            continue
    if hr is None:
        raise ValueError(f"{label}: no se encontró la columna de fechas")
    vc = find_col(df, [hr - 2, hr - 1, hr], sel[2], min_col=hc + 1)
    if len(sel) > 4:      # bloque > columna > subcolumna: 'MONEDA NACIONAL' → 'SECTOR PRIVADO' → 'Total'
        vc = find_col(df, [hr - 2, hr - 1, hr], sel[3], min_col=vc)
        vc = find_col(df, [hr + 1, hr + 2], sel[4], min_col=vc, max_col=vc + 6)
    elif len(sel) > 3:    # subcolumna: p. ej. 'SECTOR PRIVADO' → 'Total', o pregunta → 'Mediana'
        vc = find_col(df, [hr + 1, hr + 2], sel[3], min_col=vc, max_col=vc + 6)
    body = df.iloc[hr + 1:]
    dates = body.iloc[:, hc].map(lambda v: parse_vigencia(v) if "vigencia" in norm(df.iat[hr, hc]) else to_date(v))
    keep = dates.notna()
    out = pd.DataFrame({"fecha": dates[keep].values,
                        "valor": numbers(body.iloc[:, vc][keep].tolist(), label).values})
    return out.dropna(subset=["valor"])


def parse_vigencia(v) -> pd.Timestamp | None:
    """'1° de Diciembre/1969' → 1969-12-01 (Salario Mínimo Nacional)."""
    m = re.search(r"de ([a-z]+)\s*/\s*(\d{4})", norm(v))
    if m and m.group(1) in MONTHS_FULL:
        return pd.Timestamp(int(m.group(2)), MONTHS_FULL[m.group(1)], 1)
    return None


def parse_year_month_cols(df: pd.DataFrame, sel: list[str], label: str) -> pd.DataFrame:
    """IPC subyacente del INE: columnas 'Año' y 'Mes' (número) y bloques índice + variaciones."""
    hr, yc = find_header_row(df, "Año")
    mc = find_col(df, [hr], "Mes", min_col=yc + 1)
    ic = find_col(df, [hr], sel[2], min_col=mc + 1)
    vc = find_col(df, [hr], sel[3], min_col=ic + 1, max_col=ic + 5)
    body = df.iloc[hr + 1:]
    years = pd.to_numeric(body.iloc[:, yc], errors="coerce")
    months = pd.to_numeric(body.iloc[:, mc], errors="coerce")
    keep = years.notna() & months.notna()
    fechas = pd.to_datetime(dict(year=years[keep].astype(int), month=months[keep].astype(int), day=1))
    out = pd.DataFrame({"fecha": fechas.values,
                        "valor": numbers(body.iloc[:, vc][keep].tolist(), label).values})
    return out.dropna(subset=["valor"])


def period_quarter_roman(v) -> pd.Timestamp | None:
    m = re.fullmatch(r"(i|ii|iii|iv) (\d{4})\*?", norm(v))
    if m:
        return pd.Timestamp(int(m.group(2)), ROMAN_Q[m.group(1).upper()] * 3 - 2, 1)
    return None


def period_quarter_dot(v) -> pd.Timestamp | None:
    m = re.fullmatch(r"(\d{4})\*?\.(i|ii|iii|iv)", norm(v))
    if m:
        return pd.Timestamp(int(m.group(1)), ROMAN_Q[m.group(2).upper()] * 3 - 2, 1)
    return None


def period_datetime(v) -> pd.Timestamp | None:
    return pd.Timestamp(v) if isinstance(v, (dt.datetime, pd.Timestamp)) else None


def parse_wide(df: pd.DataFrame, sel: list[str], label: str) -> pd.DataFrame:
    """Cuadro 'ancho': periodos en columnas, conceptos en filas. Se elige la fila de
    encabezado con más periodos reconocibles y la fila cuyo rótulo contiene la etiqueta y
    tiene datos (debe ser única)."""
    best = None
    for parser in (period_quarter_roman, period_quarter_dot, period_datetime):
        for r in range(min(40, len(df))):
            cols = {c: parser(v) for c, v in enumerate(df.iloc[r].tolist())}
            cols = {c: p for c, p in cols.items() if p is not None}
            if len(cols) >= 3 and (best is None or len(cols) > len(best[1])):
                best = (r, cols)
    if best is None:
        raise ValueError(f"{label}: no se encontró la fila de periodos")
    hr, period_cols = best
    first_period_col = min(period_cols)
    if " > " in sel[2]:
        return parse_wide_nested(df, sel, label, hr, period_cols)
    target = norm(sel[2])
    candidates = []
    for r in range(hr + 1, len(df)):
        row = df.iloc[r].tolist()
        text = " ".join(norm(v) for v in row[:first_period_col] if isinstance(v, str))
        if target and target in text:
            vals = numbers([row[c] for c in period_cols], label)
            if vals.notna().any():
                candidates.append((r, vals))
    if not candidates:
        raise ValueError(f"{label}: no se encontró la fila '{sel[2]}' con datos")
    if len(candidates) > 1:
        raise ValueError(f"{label}: la etiqueta '{sel[2]}' es ambigua (filas {[c[0] for c in candidates]})")
    _, vals = candidates[0]
    out = pd.DataFrame({"fecha": list(period_cols.values()), "valor": vals.values})
    return out.dropna(subset=["valor"])


def parse_wide_nested(df: pd.DataFrame, sel: list[str], label: str, hr: int,
                      period_cols: dict) -> pd.DataFrame:
    """'Padre > Hijo' en un cuadro ancho: la primera fila que contiene el rótulo padre y,
    debajo, la primera fila cuyo rótulo es exactamente el hijo (p. ej. '1.A.a Bienes > Crédito'
    en la balanza de pagos, donde 'Crédito' se repite en cada sección)."""
    parent, child = (norm(x) for x in sel[2].split(" > ", 1))
    first_period_col = min(period_cols)

    def text(r: int) -> str:
        return " ".join(norm(v) for v in df.iloc[r].tolist()[:first_period_col] if isinstance(v, str))

    pr = next((r for r in range(hr + 1, len(df)) if parent in text(r)), None)
    if pr is None:
        raise ValueError(f"{label}: no se encontró la fila '{parent}'")
    cr = next((r for r in range(pr + 1, len(df)) if text(r) == child), None)
    if cr is None:
        raise ValueError(f"{label}: no se encontró la fila '{child}' debajo de '{parent}'")
    row = df.iloc[cr].tolist()
    vals = numbers([row[c] for c in period_cols], label)
    out = pd.DataFrame({"fecha": list(period_cols.values()), "valor": vals.values})
    return out.dropna(subset=["valor"])


def parse_ech(df: pd.DataFrame, sel: list[str], label: str) -> pd.DataFrame:
    """Cuadros de la ECH del INE: bloques por año ('2006'), filas de meses ('Enero (2)'),
    trimestres ('Enero - Marzo/06') y total anual. Solo se toman los meses."""
    hr, _ = find_header_row(df, "Año, Trimestre y Mes")
    vc = find_col(df, [hr], sel[2])
    year, rows = None, []
    for r in range(hr + 1, len(df)):
        lab, val = df.iat[r, 0], df.iat[r, vc]
        n = norm(lab)
        y = re.fullmatch(r"(\d{4})(\.0)?(\s*\(\d+\))*", n)      # '2015 (5)', '2017 (7) (8)'
        if y:
            year = int(y.group(1))
            continue
        m = re.match(r"([a-z]+)\b", n)
        if year and m and m.group(1) in MONTHS_FULL and "-" not in n:
            rows.append((pd.Timestamp(year, MONTHS_FULL[m.group(1)], 1), val))
    out = pd.DataFrame(rows, columns=["fecha", "valor"])
    out["valor"] = numbers(out.valor.tolist(), label).values
    return out.dropna(subset=["valor"])


def parse_mef_indicators(df: pd.DataFrame, sel: list[str], label: str) -> pd.DataFrame:
    """Planilla 'Economic Indicators' del MEF: años en columnas, sección + concepto en filas y
    una columna 'As of:' con el último periodo (p. ej. 2026M06). La columna del año en curso es
    un acumulado móvil, no un año calendario: solo se toman años cerrados."""
    section, item = norm(sel[2]), norm(sel[3])
    labels = [" ".join(norm(v) for v in df.iloc[r].tolist() if isinstance(v, str)) for r in range(len(df))]
    sec = [r for r in range(len(df)) if norm(next((v for v in df.iloc[r].tolist() if isinstance(v, str)), "")) == section]
    if len(sec) != 1:
        raise ValueError(f"{label}: sección '{sel[2]}' no encontrada o ambigua ({sec})")
    sr = sec[0]
    ir = next((r for r in range(sr + 1, len(df)) if labels[r].startswith(item)), None)
    if ir is None:
        raise ValueError(f"{label}: concepto '{sel[3]}' no encontrado tras la sección")
    year_row = next(r for r in range(sr, -1, -1)
                    if sum(1 for v in df.iloc[r].tolist() if re.fullmatch(r"(19|20)\d{2}(\.0)?", norm(v))) >= 5)
    years = {c: int(float(norm(v))) for c, v in enumerate(df.iloc[year_row].tolist())
             if re.fullmatch(r"(19|20)\d{2}(\.0)?", norm(v))}
    asof_col = next(c for r in range(year_row, sr + 1) for c, v in enumerate(df.iloc[r].tolist())
                    if norm(v).startswith("as of"))
    m = re.fullmatch(r"(\d{4})(?:(m)(\d{1,2})|(q)(\d))?", norm(df.iat[ir, asof_col]))
    if not m:
        raise ValueError(f"{label}: 'As of' no reconocido: {df.iat[ir, asof_col]!r}")
    asof_year = int(m.group(1))
    closed = m.group(2) is None and m.group(4) is None or (m.group(3) == "12") or (m.group(5) == "4")
    rows = []
    for c, y in years.items():
        if y < asof_year or (y == asof_year and closed):
            rows.append((pd.Timestamp(y, 1, 1), df.iat[ir, c]))
        elif y == asof_year:
            log.info("    %s: se descarta %d (dato a %s, no es año cerrado)", label, y, df.iat[ir, asof_col])
    out = pd.DataFrame(rows, columns=["fecha", "valor"])
    out["valor"] = numbers(out.valor.tolist(), label).values
    return out.dropna(subset=["valor"])


def parse_ws(folder: Path, name: str, field: str, label: str) -> pd.DataFrame:
    files = sorted(folder.glob(f"{name}_*.xml"))
    if not files:
        raise FileNotFoundError(f"no hay archivos {name}_*.xml")
    rows = []
    for f in files:
        root = ET.fromstring(f.read_bytes())
        for dato in root.iter():
            if dato.tag.endswith("datoscotizaciones.dato"):
                vals = {child.tag.split("}")[-1]: child.text for child in dato}
                rows.append((pd.Timestamp(vals["Fecha"]), vals.get(field)))
    out = pd.DataFrame(rows, columns=["fecha", "valor"]).drop_duplicates("fecha")
    out["valor"] = numbers(out.valor.tolist(), label).values
    return out.dropna(subset=["valor"])


LONG_FILES = {"imae.xlsx", "tasa_1_dia.xlsx", "tasas.xls", "Creditos.xlsx", "IEES05I2.xlsx",
              "reservas.xls", "ipc_general_base2022.xlsx", "unidad_indexada.xls",
              "IMSN_M_B08.xls", "salario_minimo_nacional.xls"}


def load_selector(sel: list[str], label: str) -> pd.DataFrame:
    fname = sel[0]
    folder = comun.RAW_DIR / ISO3 / SOURCES[fname][0]
    if SOURCES[fname][1] == "ws":
        return parse_ws(folder, fname, sel[1], label)
    path = folder / fname
    if not path.exists():
        raise FileNotFoundError(f"falta {path.relative_to(comun.PROJECT_DIR)}")
    frames = []
    for sheet, df in read_sheets(path, sel[1]).items():
        if fname in LONG_FILES:
            part = parse_long(df, sel, label)
        elif fname == "ipc_subyacente.xlsx":
            part = parse_year_month_cols(df, sel, label)
        elif fname == "ECH0013.xlsx":
            part = parse_ech(df, sel, label)
        elif fname == "economic-indicators-web.xlsx":
            part = parse_mef_indicators(df, sel, label)
        else:
            if sel[1] == "*":     # todas las hojas: las que no tienen la fila se ignoran
                try:
                    part = parse_wide(df, sel, f"{label}[{sheet}]")
                except ValueError as e:
                    log.info("    %s: hoja '%s' sin la serie (%s)", label, sheet, e)
                    continue
            else:
                part = parse_wide(df, sel, f"{label}[{sheet}]")
        frames.append(part)
    if not frames:
        raise ValueError(f"{label}: ninguna hoja de {fname} tiene la serie")
    out = pd.concat(frames, ignore_index=True).sort_values("fecha")
    return out


# --------------------------------------------------------------------------- transformaciones

def apply_transforms(df: pd.DataFrame, transforms: list[str], label: str, today: dt.date) -> pd.DataFrame:
    """Mismas transformaciones que bra.py, más `ffill_mes`."""
    df = df.sort_values("fecha").reset_index(drop=True)
    for t in transforms:
        name, _, arg = t.partition("=")
        if name == "desde":
            df = df[df.fecha >= pd.Timestamp(arg)]
        elif name == "esc":
            df = df.assign(valor=df.valor * float(arg))
        elif name == "neg":
            df = df.assign(valor=-df.valor)
        elif name in ("fin_mes", "prom_mes"):
            per = df.fecha.dt.to_period("M")
            agg = df.groupby(per).valor.last() if name == "fin_mes" else df.groupby(per).valor.mean()
            agg = agg[agg.index < pd.Period(today, "M")]      # solo meses cerrados
            df = pd.DataFrame({"fecha": agg.index.to_timestamp(), "valor": agg.values})
        elif name == "suma_trim":
            g = df.groupby(df.fecha.dt.to_period("Q")).valor.agg(["sum", "count"])
            g = g[g["count"] == 3]
            df = pd.DataFrame({"fecha": g.index.to_timestamp(), "valor": g["sum"].values})
        elif name == "suma_anual":
            g = df.groupby(df.fecha.dt.to_period("Y")).valor.agg(["sum", "count"])
            g = g[g["count"] == int(arg)]
            df = pd.DataFrame({"fecha": g.index.to_timestamp(), "valor": g["sum"].values})
        elif name == "dic":
            df = df[df.fecha.dt.month == 12]
            df = df.assign(fecha=df.fecha.dt.to_period("Y").dt.start_time)
        elif name == "var12m":
            prev = df.assign(fecha=df.fecha + pd.DateOffset(years=1))
            m = df.merge(prev, on="fecha", suffixes=("", "_prev"))
            df = pd.DataFrame({"fecha": m.fecha, "valor": (m.valor / m.valor_prev - 1) * 100})
        elif name == "acum12m":
            s = df.set_index(df.fecha.dt.to_period("M")).valor
            s = s.reindex(pd.period_range(s.index.min(), s.index.max(), freq="M"))
            factor = (1 + s / 100).rolling(12, min_periods=12).apply(lambda x: x.prod(), raw=True)
            out = ((factor - 1) * 100).dropna()
            df = pd.DataFrame({"fecha": out.index.to_timestamp(), "valor": out.values})
        elif name == "ffill_mes":
            s = df.set_index(df.fecha.dt.to_period("M")).valor
            s = s[~s.index.duplicated(keep="last")]
            s = s.reindex(pd.period_range(s.index.min(), pd.Period(today, "M"), freq="M")).ffill()
            df = pd.DataFrame({"fecha": s.index.to_timestamp(), "valor": s.values})
        else:
            raise ValueError(f"{label}: transformación desconocida '{t}'")
    return df.reset_index(drop=True)


# --------------------------------------------------------------------------- procesamiento

def process(series: list[dict], today: dt.date) -> int:
    frames, errors = [], 0
    for row in series:
        name = row["nombre_corto"]
        selectors, transforms = split_code(row["codigo_fuente"])
        try:
            parts = [load_selector(sel, name) for sel in selectors]
        except (FileNotFoundError, ValueError, KeyError, StopIteration) as e:
            errors += 1
            log.error("  %s: no se pudo leer (%s)", name, e)
            continue
        if len(parts) == 1:
            df = parts[0]
        else:                                          # 'a - b' (balanza comercial)
            a = parts[0].assign(fecha=parts[0].fecha.dt.to_period("M"))
            b = parts[1].assign(fecha=parts[1].fecha.dt.to_period("M"))
            m = a.merge(b, on="fecha", suffixes=("_a", "_b"))
            df = pd.DataFrame({"fecha": m.fecha.dt.to_timestamp(), "valor": m.valor_a - m.valor_b})
        future = df.fecha > pd.Timestamp(today)
        if future.any():
            log.info("    %s: %d obs. con fecha futura descartadas (hasta %s)", name,
                     int(future.sum()), df.fecha[future].max().date())
            df = df[~future]
        df = apply_transforms(df, transforms, name, today)
        df["fecha"] = comun.period_start(df["fecha"], row["frecuencia"])
        df = df.dropna(subset=["valor"])
        if df.empty:
            errors += 1
            log.error("  %s: sin observaciones tras procesar", name)
            continue
        dup = df.duplicated("fecha")
        if dup.any():
            errors += 1
            log.error("  %s: %d periodos repetidos tras normalizar fechas, p. ej. %s", name,
                      dup.sum(), df[dup].fecha.head(3).dt.date.tolist())
            continue
        for col in ("fuente", "codigo_fuente", "nombre_corto", "indicador_comun", "frecuencia",
                    "unidad"):
            df[col] = row[col]
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    out["pais"] = ISO3
    comun.write_interim(ISO3, out)
    return errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--solo-procesar", action="store_true", help="no descarga; solo procesa data/raw")
    ap.add_argument("--serie", nargs="+", metavar="NOMBRE_CORTO", help="descargar solo estas series")
    ap.add_argument("--pausa", type=float, default=1.0, help="segundos entre peticiones (mínimo 1)")
    args = ap.parse_args(argv)

    # La consola de Windows (cp1252) no puede mostrar '→', que comun.py usa en el log.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    comun.setup_logging(ISO3)
    today = dt.date.today()
    series = comun.load_series(ISO3)
    errors = 0
    if not args.solo_procesar:
        selected = series
        if args.serie:
            wanted = set(args.serie)
            selected = [s for s in series if s["nombre_corto"] in wanted]
            missing = wanted - {s["nombre_corto"] for s in selected}
            if missing:
                log.warning("No están activas en config/series/URY.csv: %s", ", ".join(sorted(missing)))
        client = comun.Client(pause=max(args.pausa, 1.0), verify=ca_bundle())
        errors += download(selected, client, today)
    errors += process(series, today)
    log.info("Fin%s", f" con {errors} errores" if errors else " sin errores")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
