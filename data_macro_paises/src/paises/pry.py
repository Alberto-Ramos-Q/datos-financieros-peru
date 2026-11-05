"""Paraguay (PRY): descarga y procesa series macro de fuentes oficiales.

Fuentes:
- BCP  (Banco Central del Paraguay, www.bcp.gov.py): IPC, IMAEP, cuentas nacionales,
  tasas, agregados, crédito, tipo de cambio, reservas, comercio exterior, balanza de pagos,
  remesas, salario mínimo (anexo del ISS).
- INE  (Instituto Nacional de Estadística, www.ine.gov.py): desempleo (EPHC trimestral).
- MEF  (Ministerio de Economía y Finanzas, www.mef.gov.py): resultado fiscal y deuda pública.

Dos pasos separados (ver `src/comun.py`):
1. Descargar: entra a la página oficial de cada cuadro, localiza el enlace del Excel por
   su nombre (los enlaces del BCP cambian con cada actualización: llevan fecha y un UUID)
   y guarda el archivo tal cual en `data/raw/PRY/<fuente>/` con un nombre estable.
2. Procesar: lee SOLO `data/raw/PRY/` y escribe `data/interim/PRY_observaciones.parquet`.

Trampa principal: www.bcp.gov.py está detrás de Cloudflare, que rechaza (403 "Just a moment")
a `requests` por su huella TLS aunque el User-Agent sea de navegador. `curl` sí pasa, de forma
intermitente. Por eso, solo para ese host, las descargas se hacen con `curl` (secuencial, con
pausa y reintentos), envuelto en `CurlClient`. `comun.Client` no ofrece esta vía.

Uso:
    python src/paises/pry.py                       # descarga + procesa todas las activas
    python src/paises/pry.py --solo-procesar       # solo reprocesa data/raw/PRY
    python src/paises/pry.py --serie ipc_indice tasa_politica
    python src/paises/pry.py --pausa 2
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import logging
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, unquote_plus, urljoin

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import comun  # noqa: E402

ISO3 = "PRY"
log = logging.getLogger("data_macro_paises")

BCP = "https://www.bcp.gov.py/web/institucional/"
CURL_HOSTS = {"www.bcp.gov.py"}

MONTHS = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8,
          "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12}
# Marcadores de "sin dato" que aparecen en los cuadros oficiales.
NO_DATA = {"", "-", "--", "s/d", "s/m", "nd", "n.d.", "...", "na", "(p)", "*"}


# --------------------------------------------------------------------------------------
# Descarga
# --------------------------------------------------------------------------------------
class CurlClient:
    """Cliente secuencial que usa `curl` (para hosts con Cloudflare que bloquea `requests`).

    Misma interfaz mínima que `comun.Client`: get()/post() devuelven un objeto con
    `.content`, `.text`, `.status_code` y `.url`. Reintenta mientras Cloudflare responda
    con el desafío "Just a moment" (403); la cookie de sesión se guarda en un archivo
    temporal (fuera del proyecto).
    """

    @dataclass
    class Response:
        content: bytes
        status_code: int
        url: str

        @property
        def text(self) -> str:
            return self.content.decode("utf-8", errors="replace")

    def __init__(self, pause: float = 1.0, retries: int = 6):
        self.curl = shutil.which("curl") or shutil.which("curl.exe")
        if not self.curl:
            raise RuntimeError("No se encontró `curl` en el PATH (necesario para www.bcp.gov.py)")
        self.pause = pause
        self.retries = retries
        self.tmp = Path(tempfile.mkdtemp(prefix="pry_curl_"))
        self.cookies = self.tmp / "cookies.txt"

    def get(self, url: str, timeout: int = 180) -> "CurlClient.Response":
        return self._run(url, [], timeout)

    def post(self, url: str, data: dict, timeout: int = 180) -> "CurlClient.Response":
        args = []
        for k, v in data.items():
            args += ["--data-urlencode", f"{k}={v}"]
        return self._run(url, args, timeout)

    def _run(self, url: str, extra: list[str], timeout: int) -> "CurlClient.Response":
        out = self.tmp / "body.bin"
        last = None
        for attempt in range(1, self.retries + 1):
            time.sleep(self.pause)
            cmd = [self.curl, "-sS", "-L", "--max-time", str(timeout),
                   "-A", comun.USER_AGENT, "-H", "Accept-Language: es-ES,es;q=0.9",
                   "-c", str(self.cookies), "-b", str(self.cookies),
                   "-o", str(out), "-w", "%{http_code}", *extra, url]
            p = subprocess.run(cmd, capture_output=True, text=True)
            code = int(p.stdout.strip() or 0) if p.stdout.strip().isdigit() else 0
            body = out.read_bytes() if out.exists() else b""
            challenge = b"Just a moment" in body[:20000]
            if p.returncode == 0 and code == 200 and not challenge:
                return CurlClient.Response(body, code, url)
            last = f"curl rc={p.returncode} http={code}{' (desafío Cloudflare)' if challenge else ''} {p.stderr.strip()[:200]}"
            wait = 3 * attempt
            log.warning("Intento %d falló (%s); reintento en %d s", attempt, last, wait)
            time.sleep(wait)
        raise RuntimeError(f"No se pudo descargar {url}: {last}")


@dataclass
class RawFile:
    """Un archivo oficial: de qué página sale y cómo se reconoce su enlace."""
    key: str                      # nombre estable en data/raw/PRY/<fuente>/
    fuente: str
    page: str                     # página oficial donde está el enlace
    pattern: str                  # regex sobre el href decodificado (nombre del archivo)
    note: str = ""


RAW_FILES: dict[str, RawFile] = {f.key: f for f in [
    RawFile("bcp_ipc_desde_1950.xlsx", "BCP", BCP + "indice-precios-al-consumidor-ipc",
            r"/IPC_desde_1950[^/]*\.xlsx/"),
    RawFile("bcp_anexo_ipc.xlsx", "BCP", BCP + "indice-precios-al-consumidor-ipc",
            r"/AE_IPC\.xlsx/"),
    RawFile("bcp_imaep.xlsx", "BCP",
            BCP + "indicador-mensual-de-actividad-economica-del-paraguay-imaep-",
            r"/Indicador Mensual de la Actividad Econ[^/]*\.xlsx/"),
    RawFile("bcp_cnt.xlsx", "BCP", BCP + "cuentas-nacionales-trimestrales-cnt-",
            r"/Serie_final_CNT[^/]*\.xlsx/"),
    RawFile("bcp_pib_anual_desde_1950.xlsx", "BCP", BCP + "serie-historica-del-pib-base-2014",
            r"/PIB total, PIB per c.pita desde 1950\.xlsx/"),
    RawFile("bcp_lrm_tpm_tib.xlsx", "BCP", BCP + "instrumentos-de-regulaci%C3%B3n-monetaria",
            r"/Resumen Hist.rico Mensual LRM\.xlsx/"),
    RawFile("bcp_indicadores_financieros.xlsx", "BCP",
            BCP + "anexo-estadistico-indicadores-financieros", r"/Ind\. Financieros[^/]*\.xlsx/"),
    RawFile("bcp_creditos_depositos.xlsx", "BCP", BCP + "creditos-y-depositos",
            r"/Cr.ditos y Dep.sitos\.xlsx/"),
    RawFile("bcp_agregados_monetarios.xlsx", "BCP", BCP + "agregados-monetarios",
            r"/Agregados Monetarios\.xlsx/"),
    RawFile("bcp_tipo_cambio_nominal.xlsx", "BCP", BCP + "tipo-de-cambio-nominal-tcn-",
            r"/Tipo de cambio nominal[^/]*\.xlsx/"),
    RawFile("bcp_tipo_cambio_real.xlsx", "BCP", BCP + "tipo-de-cambio-real",
            r"/Tipo de cambio real[^/]*\.xlsx/"),
    RawFile("bcp_reservas_internacionales.xlsx", "BCP", BCP + "reservas-internacionales",
            r"/Reservas Internacionales[^/]*\.xlsx/"),
    RawFile("bcp_comercio_exterior_cuadros.xlsx", "BCP", BCP + "comercio-externo-comex-mensual",
            r"/Cuadros de Comercio Exterior[^/]*\.xlsx/"),
    RawFile("bcp_balanza_pagos.xlsx", "BCP",
            BCP + "balanza-de-pagos-y-posicion-de-inversion-internacional",
            r"/Balanza de pagos[^/]*\.xlsx/"),
    RawFile("bcp_remesas_familiares.xlsx", "BCP", BCP + "remesas-familiares",
            r"/Remesas familiares\.xlsx/"),
    RawFile("bcp_anexo_iss.xlsx", "BCP", BCP + "%C3%ADndice-de-sueldos-y-salarios-iss-",
            r"/AE_ISS\.xlsx/"),
    RawFile("bcp_meta_inflacion.xlsx", "BCP", BCP + "meta-de-inflacion",
            r"/Meta de inflaci.n\.xlsx/"),
    RawFile("ine_ephc_tasas.xlsx", "INE", "https://www.ine.gov.py/publicacion/3/empleo",
            r"/\d+/1\. ?Tasas\.xlsx$"),
    RawFile("mef_situfin_anual.xlsx", "MEF", "https://www.mef.gov.py/es/situfin",
            r"ADMINISTRACI.N CENTRAL[^/]*serie anual\.xlsx$"),
    RawFile("mef_estadisticas_deuda.xlsx", "MEF",
            "https://www.mef.gov.py/es/dependencias/viceministerio-de-economia-y-planificacion/deuda-publica",
            r"/Estadisticas_Deuda_Publica[^/]*\.xlsx$"),
]}
# Cotización referencial diaria del BCP (USD): una planilla por año, POST al formulario.
COTIZ_URL = "https://www.bcp.gov.py/webapps/web/cotizacion/monedas-historica"
COTIZ_FUENTE = "BCP"
COTIZ_KEY = "bcp_cotizacion_usd_{year}.html"


def page_links(page_html: str, base: str) -> list[str]:
    """Hrefs absolutos de una página (sin decodificar)."""
    hrefs = re.findall(r"""href=["']([^"']+)["']""", page_html)
    return [urljoin(base, html.unescape(h)) for h in hrefs]


def find_link(page_html: str, base: str, pattern: str) -> str:
    """Primer enlace cuyo href decodificado (unquote_plus) calza con el patrón."""
    rx = re.compile(pattern, re.I)
    for href in page_links(page_html, base):
        if rx.search(unquote_plus(href)):
            return href
    raise LookupError(f"No se encontró enlace {pattern!r} en {base}")


class Downloader:
    def __init__(self, pause: float):
        self.curl = CurlClient(pause=pause)
        self.http = comun.Client(pause=pause)
        self.pages: dict[str, str] = {}

    def client_for(self, url: str):
        host = re.sub(r"^https?://([^/]+).*$", r"\1", url)
        return self.curl if host in CURL_HOSTS else self.http

    def get(self, url: str):
        return self.client_for(url).get(url)

    def page(self, url: str) -> str:
        if url not in self.pages:
            self.pages[url] = self.get(url).text
        return self.pages[url]

    def fetch(self, rf: RawFile) -> str:
        link = find_link(self.page(rf.page), rf.page, rf.pattern)
        r = self.get(link)
        if r.content[:2] != b"PK":   # todos los .xlsx son zip
            raise ValueError(f"{rf.key}: la respuesta no es un .xlsx ({r.content[:80]!r})")
        action = comun.save_raw(ISO3, rf.fuente, rf.key, r.content, link)
        log.info("  %-38s %-11s %s", rf.key, action, unquote_plus(link.split("?")[0])[-90:])
        return action

    def fetch_cotizaciones(self, years: list[int] | None = None) -> None:
        form = self.page(COTIZ_URL)
        available = sorted(int(y) for y in re.findall(r"<option\s*>(\d{4})</option>", form))
        if not available:
            raise LookupError("No se encontraron años en el formulario de cotizaciones del BCP")
        for year in (years or available):
            # El botón PLANILLA hace POST a .../xls: devuelve una tabla HTML (no un .xls real).
            r = self.curl.post(COTIZ_URL + "/xls", {"anho": year, "moneda": "USD"})
            if b"PLANILLA DE COTIZACIONES" not in r.content.upper() and b"<table" not in r.content:
                raise ValueError(f"Cotizaciones {year}: respuesta inesperada")
            key = COTIZ_KEY.format(year=year)
            action = comun.save_raw(ISO3, COTIZ_FUENTE, key, r.content,
                                    f"{COTIZ_URL}/xls?anho={year}&moneda=USD (POST)")
            log.info("  %-38s %s", key, action)


# --------------------------------------------------------------------------------------
# Utilidades de parseo
# --------------------------------------------------------------------------------------
def norm(text) -> str:
    """Texto en minúsculas, sin tildes ni espacios repetidos."""
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return ""
    t = unicodedata.normalize("NFKD", str(text))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.replace("\n", " ").split()).lower()


class Discards:
    """Registro de valores no numéricos descartados (no se imputan)."""

    def __init__(self):
        self.items: dict[str, list] = {}

    def add(self, serie: str, periodo, valor) -> None:
        self.items.setdefault(serie, []).append((periodo, valor))

    def report(self) -> None:
        for serie, items in self.items.items():
            ejemplos = ", ".join(f"{p}={v!r}" for p, v in items[:4])
            log.info("  %s: %d valores sin dato descartados (p. ej. %s)", serie, len(items), ejemplos)


DISCARDS = Discards()


def to_float(v, serie: str = "", periodo=None):
    """Número o None. Los marcadores de sin dato se descartan y quedan en el log."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    s = str(v).strip()
    if norm(s) in NO_DATA:
        if s and serie:
            DISCARDS.add(serie, periodo, s)
        return None
    s2 = s.replace("\xa0", "").replace(" ", "")
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+(,\d+)?", s2) or re.fullmatch(r"-?\d+,\d+", s2):
        s2 = s2.replace(".", "").replace(",", ".")      # formato 6.486,59
    try:
        return float(s2)
    except ValueError:
        if serie:
            DISCARDS.add(serie, periodo, s)
        return None


def month_of(label) -> int | None:
    """'Ene', 'SEPT', 'Setiembre', 'Julio' -> número de mes."""
    t = norm(label).rstrip(".*").strip()
    t = re.sub(r"\(.*\)$", "", t).strip()
    return MONTHS.get(t[:3]) if t and t[:3] in MONTHS and t.isalpha() else None


def year_of(label) -> int | None:
    """'2025 1/', '2026*', 2014.0, '2019 (p)' -> año; None si no es un año."""
    if isinstance(label, (int, float)) and not pd.isna(label) and 1900 <= label <= 2100:
        return int(label)
    m = re.match(r"^\s*((?:19|20)\d{2})(?:\s*(?:\*|\(p\)|1/|\d/))*\s*\*?\s*$", str(label))
    return int(m.group(1)) if m else None


def parse_mon_yy(label) -> pd.Timestamp | None:
    """'may-26 *', 'SET-11', 'ene-20', 'dic-23*' -> primer día del mes."""
    if isinstance(label, (dt.datetime, pd.Timestamp)):
        return pd.Timestamp(label)
    m = re.match(r"^\s*([A-Za-z]{3,4})[-/ ](\d{2}|\d{4})\b", str(label))
    if not m or month_of(m.group(1)) is None:
        return None
    y = int(m.group(2))
    y = y + 2000 if y < 100 else y
    return pd.Timestamp(y, month_of(m.group(1)), 1)


def read_sheet(key: str, fuente: str, sheet) -> pd.DataFrame:
    path = comun.raw_path(ISO3, fuente, key)
    if not path.exists():
        raise FileNotFoundError(f"Falta {path} (¿no se descargó?)")
    return pd.read_excel(path, sheet_name=sheet, header=None)


def find_cell(df: pd.DataFrame, pattern: str, rows=None, cols=None, exact=False) -> tuple[int, int]:
    """(fila, col) de la primera celda cuyo texto normalizado calza con `pattern`."""
    rows = range(df.shape[0]) if rows is None else rows
    cols = range(df.shape[1]) if cols is None else cols
    rx = re.compile(pattern)
    for r in rows:
        for c in cols:
            t = norm(df.iat[r, c])
            if t and ((exact and t == pattern) or (not exact and rx.search(t))):
                return r, c
    raise LookupError(f"No se encontró {pattern!r}")


def ffill_row(df: pd.DataFrame, r: int) -> list[str]:
    """Fila de encabezado con las celdas combinadas rellenadas hacia la derecha."""
    out, last = [], ""
    for v in df.iloc[r]:
        t = norm(v)
        last = t or last
        out.append(last)
    return out


def series_from(dates, values, serie: str) -> pd.DataFrame:
    recs = []
    for d, v in zip(dates, values):
        if d is None or pd.isna(d):
            continue
        x = to_float(v, serie, d.date() if hasattr(d, "date") else d)
        if x is not None:
            recs.append((pd.Timestamp(d), x))
    return pd.DataFrame(recs, columns=["fecha", "valor"])


def check_unique(df: pd.DataFrame, serie: str) -> pd.DataFrame:
    dup = df.duplicated("fecha", keep=False)
    if dup.any():
        raise ValueError(f"{serie}: periodos repetidos {df[dup].fecha.dt.date.unique()[:5]}")
    return df.sort_values("fecha").reset_index(drop=True)


# --------------------------------------------------------------------------------------
# Parsers por cuadro
# --------------------------------------------------------------------------------------
def p_ipc_1950(column: str) -> Callable[[str], pd.DataFrame]:
    """IPC empalmado desde 1950 (BCP). Años en filas; desde 1964 cada año trae sus meses.

    Antes de 1964 solo hay promedios anuales: se omiten (la serie es mensual).
    `column`: 'indice' | 'mensual' | 'interanual'.
    """
    def parse(serie: str) -> pd.DataFrame:
        df = read_sheet("bcp_ipc_desde_1950.xlsx", "BCP", 0)
        r0, _ = find_cell(df, r"^ano/mes$")
        head = [f"{a} {b}".strip() for a, b in zip(ffill_row(df, r0), [norm(v) for v in df.iloc[r0 + 1]])]
        wanted = {"indice": r"indice general", "mensual": r"variaciones mensual",
                  "interanual": r"variaciones interanual"}[column]
        col = next(i for i, h in enumerate(head) if re.search(wanted, h))
        year, dates, vals = None, [], []
        for r in range(r0 + 2, df.shape[0]):
            lab = df.iat[r, 0]
            y = year_of(lab)
            if y is not None:
                year = y
                continue
            m = month_of(lab)
            if m is None:
                if norm(lab):
                    log.debug("%s: fila ignorada %r", serie, lab)
                continue
            if year is None:
                raise ValueError(f"{serie}: mes sin año en fila {r}")
            dates.append(pd.Timestamp(year, m, 1))
            vals.append(df.iat[r, col])
        return series_from(dates, vals, serie)
    return parse


def p_anexo_ipc(sheet: str, category: str, measure: str) -> Callable[[str], pd.DataFrame]:
    """Cuadros del anexo del IPC (AE_IPC.xlsx): encabezado de 2-3 filas con celdas combinadas.

    `category` = texto exacto (normalizado) del grupo, p. ej. 'subyacente' (distinto de
    'subyacente (x1)'); `measure` = 'mensual' | 'interanual' (tercera fila del encabezado).
    """
    def parse(serie: str) -> pd.DataFrame:
        df = read_sheet("bcp_anexo_ipc.xlsx", "BCP", sheet)
        r0, _ = find_cell(df, r"^ano$", cols=[0])
        cats = ffill_row(df, r0)
        col = next((c for c in range(1, df.shape[1])
                    if cats[c] == category and norm(df.iat[r0 + 2, c]) == measure), None)
        if col is None:
            raise LookupError(f"{serie}: no se encontró {category}/{measure} en {sheet}")
        dates = [pd.Timestamp(v) if isinstance(v, (dt.datetime, pd.Timestamp)) else None
                 for v in df.iloc[r0 + 1:, 0]]
        return series_from(dates, df.iloc[r0 + 1:, col].tolist(), serie)
    return parse


def p_anexo_ipc_var(sheet: str, label: str, measure: str) -> Callable[[str], pd.DataFrame]:
    """Cuadros del anexo del IPC con el índice en una columna y sus variaciones a la derecha
    (CUADRO 5): fila 'Año' con los rótulos ('IPC sin Alim, Comb, Serv. Tarif', 'Variación%'
    en celdas combinadas) y debajo 'Mens.' / 'Acum.' / 'Inter.'. Se toma la primera columna
    de `measure` a la derecha del rótulo; las fechas están en la primera columna."""
    def parse(serie: str) -> pd.DataFrame:
        df = read_sheet("bcp_anexo_ipc.xlsx", "BCP", sheet)
        r0, _ = find_cell(df, r"^ano$", cols=[0])
        _, lc = find_cell(df, "^" + re.escape(norm(label)) + "$", rows=[r0])
        col = next((c for c in range(lc + 1, df.shape[1]) if norm(df.iat[r0 + 1, c]) == measure), None)
        if col is None:
            raise LookupError(f"{serie}: no se encontró {label}/{measure} en {sheet}")
        nxt = next((c for c in range(lc + 1, df.shape[1]) if norm(df.iat[r0, c]) not in ("", "variacion%")), df.shape[1])
        if col >= nxt:
            raise LookupError(f"{serie}: la columna {measure} no pertenece a {label}")
        dates = [pd.Timestamp(v) if isinstance(v, (dt.datetime, pd.Timestamp)) else None
                 for v in df.iloc[r0 + 2:, 0]]
        return series_from(dates, df.iloc[r0 + 2:, col].tolist(), serie)
    return parse


def p_imaep(label: str) -> Callable[[str], pd.DataFrame]:
    def parse(serie: str) -> pd.DataFrame:
        df = read_sheet("bcp_imaep.xlsx", "BCP", "IMAEP")
        r0, col = find_cell(df, "^" + re.escape(norm(label)) + "$")
        dcol = next(c for c in range(df.shape[1])
                    if isinstance(df.iat[r0 + 1, c], (dt.datetime, pd.Timestamp)))
        sub = df.iloc[r0 + 1:]
        dates = [pd.Timestamp(v) if isinstance(v, (dt.datetime, pd.Timestamp)) else None for v in sub[dcol]]
        return series_from(dates, sub[col].tolist(), serie)
    return parse


def yoy(parser: Callable[[str], pd.DataFrame]) -> Callable[[str], pd.DataFrame]:
    """Variación % interanual calculada desde un índice mensual oficial.

    Solo cuando el BCP no publica la variación en el mismo cuadro; se calcula solo si el
    mes de un año antes existe (no se imputa nada)."""
    def parse(serie: str) -> pd.DataFrame:
        base = parser(serie + "(índice)").set_index("fecha").valor
        prev = base.reindex(base.index - pd.DateOffset(months=12)).values
        out = pd.DataFrame({"fecha": base.index, "valor": (base.values / prev - 1) * 100})
        return out.dropna().reset_index(drop=True)
    return parse


def quarter_date(label) -> pd.Timestamp | None:
    m = re.match(r"^\s*((?:19|20)\d{2})\s*Q([1-4])", str(label))
    return pd.Timestamp(int(m.group(1)), 3 * int(m.group(2)) - 2, 1) if m else None


def p_cnt(section: str, measure: str) -> Callable[[str], pd.DataFrame]:
    """CNT, hoja 'PIB Oferta': secciones (niveles / var. interanual / acumulada) × actividad × medida."""
    def parse(serie: str) -> pd.DataFrame:
        df = read_sheet("bcp_cnt.xlsx", "BCP", "PIB Oferta")
        rs, _ = find_cell(df, r"variacion interanual")
        sec, act = ffill_row(df, rs), ffill_row(df, rs + 1)
        meas = [norm(v) for v in df.iloc[rs + 2]]
        col = next(c for c in range(df.shape[1])
                   if section in sec[c] and act[c] == "producto interno bruto" and meas[c] == measure)
        dates = [quarter_date(v) for v in df[0]]
        return series_from(dates, df[col].tolist(), serie)
    return parse


def p_pib_anual(serie: str) -> pd.DataFrame:
    df = read_sheet("bcp_pib_anual_desde_1950.xlsx", "BCP", 0)
    r0, _ = find_cell(df, r"^ano$", cols=[0])
    top, sub = ffill_row(df, r0), [norm(v) for v in df.iloc[r0 + 1]]
    col = next(c for c in range(df.shape[1]) if "millones de guaranies" in top[c] and "corrientes" in sub[c])
    dates = [pd.Timestamp(year_of(v), 1, 1) if year_of(v) else None for v in df[0]]
    return series_from(dates, df[col].tolist(), serie)


def p_lrm(label: str) -> Callable[[str], pd.DataFrame]:
    """Resumen histórico mensual de LRM: incluye la TPM (fin de mes) y la TIB (promedio)."""
    def parse(serie: str) -> pd.DataFrame:
        df = read_sheet("bcp_lrm_tpm_tib.xlsx", "BCP", 0)
        _, col = find_cell(df, label)
        dates = [pd.Timestamp(v) if isinstance(v, (dt.datetime, pd.Timestamp)) else None for v in df[0]]
        return series_from(dates, df[col].tolist(), serie)
    return parse


def p_ind_financieros(operacion: str) -> Callable[[str], pd.DataFrame]:
    """Cuadro 1.1 (tasas nominales, bancos, promedio mensual ponderado por saldos): meses en columnas."""
    def parse(serie: str) -> pd.DataFrame:
        df = read_sheet("bcp_indicadores_financieros.xlsx", "BCP", "1.1")
        rh, _ = find_cell(df, r"^moneda$", cols=[0])
        row = next(r for r in range(rh + 1, df.shape[0])
                   if norm(df.iat[r, 0]) == "mn" and norm(df.iat[r, 1]) == operacion
                   and norm(df.iat[r, 2]) == "total")
        dates = [parse_mon_yy(v) for v in df.iloc[rh]]
        return series_from(dates[3:], df.iloc[row, 3:].tolist(), serie)
    return parse


def p_creditos(top: str, sub: str) -> Callable[[str], pd.DataFrame]:
    def parse(serie: str) -> pd.DataFrame:
        df = read_sheet("bcp_creditos_depositos.xlsx", "BCP", "Créditos-Priv-ByF")
        rh, _ = find_cell(df, r"^ano$", cols=[0])
        t, s = ffill_row(df, rh), [norm(v) for v in df.iloc[rh + 1]]
        col = next(c for c in range(df.shape[1]) if t[c] == top and s[c].startswith(sub))
        dates = [parse_mon_yy(v) for v in df[0]]
        dates = [d if (d is not None and i > rh + 1) else None for i, d in enumerate(dates)]
        return series_from(dates, df[col].tolist(), serie)
    return parse


def p_simple_dated(key: str, sheet, header: str, exact=True, date_col=None) -> Callable[[str], pd.DataFrame]:
    """Cuadros con una columna de fechas (datetime) y encabezados en una fila."""
    def parse(serie: str) -> pd.DataFrame:
        df = read_sheet(key, "BCP", sheet)
        rh, col = find_cell(df, norm(header) if exact else header, exact=exact)
        dc = date_col
        if dc is None:
            dc = next(c for c in range(df.shape[1])
                      if sum(isinstance(v, (dt.datetime, pd.Timestamp)) for v in df.iloc[rh:, c]) > 5)
        dates = [pd.Timestamp(v) if isinstance(v, (dt.datetime, pd.Timestamp)) else None
                 for v in df.iloc[rh + 1:, dc]]
        return series_from(dates, df.iloc[rh + 1:, col].tolist(), serie)
    return parse


def p_meta_inflacion(serie: str) -> pd.DataFrame:
    df = read_sheet("bcp_meta_inflacion.xlsx", "BCP", 0)
    rh, col = find_cell(df, r"^objetivo")
    dates = [parse_mon_yy(v) for v in df.iloc[rh + 1:, 0]]
    return series_from(dates, df.iloc[rh + 1:, col].tolist(), serie)


def p_year_month_block(key: str, sheet: str, header: str, scale: float = 1.0,
                       drop_all_zero_cols: list[str] | None = None) -> Callable[[str], pd.DataFrame]:
    """Cuadros con un año en una fila seguido de sus meses ('Ene'...'Dic').

    Las filas de año (totales anuales) se omiten. En el año en curso los meses futuros
    vienen en 0: se descartan las filas en que todas las columnas `drop_all_zero_cols`
    valen 0 o están vacías (no son datos).
    """
    def parse(serie: str) -> pd.DataFrame:
        df = read_sheet(key, "BCP", sheet)
        rh, col = find_cell(df, "^" + re.escape(norm(header)) + "$")
        guard = [find_cell(df, "^" + re.escape(norm(h)) + "$", rows=[rh])[1]
                 for h in (drop_all_zero_cols or [header])]
        year, dates, vals = None, [], []
        for r in range(rh + 1, df.shape[0]):
            lab = df.iat[r, 0]
            y = year_of(lab)
            if y is not None:
                year = y
                continue
            m = month_of(lab)
            if m is None:
                if norm(lab).startswith(("var", "fuente", "nota", "total", "partic", "incid")):
                    year = None
                continue
            if year is None:
                continue
            g = [to_float(df.iat[r, c]) for c in guard]
            if all(v in (None, 0.0) for v in g):
                continue
            v = to_float(df.iat[r, col], serie, f"{year}-{m:02d}")
            if v is not None:
                dates.append(pd.Timestamp(year, m, 1))
                vals.append(v * scale)
        return pd.DataFrame({"fecha": dates, "valor": vals})
    return parse


def p_bop(label: str) -> Callable[[str], pd.DataFrame]:
    """Balanza de pagos MBP6, Cuadro N° 1: años (con '*') sobre trimestres I-IV y 'Total'."""
    def parse(serie: str) -> pd.DataFrame:
        df = read_sheet("bcp_balanza_pagos.xlsx", "BCP", "Cuadro N° 1")
        row, _ = find_cell(df, "^" + re.escape(norm(label)), cols=range(0, 4))
        ry = next(r for r in range(row - 1, 0, -1)
                  if sum(year_of(v) is not None for v in df.iloc[r]) >= 5)
        year, dates = None, []
        for c in range(df.shape[1]):
            y = year_of(str(df.iat[ry, c]).replace("*", "")) if pd.notna(df.iat[ry, c]) else None
            year = y or year
            q = norm(df.iat[ry + 1, c]).replace("*", "").strip()
            qn = {"i": 1, "ii": 2, "iii": 3, "iv": 4}.get(q)
            dates.append(pd.Timestamp(year, 3 * qn - 2, 1) if (year and qn) else None)
        return series_from(dates, df.iloc[row].tolist(), serie)
    return parse


def p_reservas(serie: str) -> pd.DataFrame:
    df = read_sheet("bcp_reservas_internacionales.xlsx", "BCP", "CUADRO 56a")
    rh, col = find_cell(df, r"^saldo$")
    _, dc = find_cell(df, r"^ano$", rows=[rh])
    sub = df.iloc[rh + 1:]
    # Las fechas son el día del último dato del mes (p. ej. 2026-09-25): se normaliza al mes.
    dates = [pd.Timestamp(v).to_period("M").start_time if isinstance(v, (dt.datetime, pd.Timestamp)) else None
             for v in sub[dc]]
    return series_from(dates, sub[col].tolist(), serie)


def p_salario_minimo(serie: str) -> pd.DataFrame:
    """Salario mínimo legal (anexo del ISS): fila anual (promedio) y, si hubo ajuste en el año,
    filas de subperiodo 'Enero/Junio', 'Julio/Diciembre'... Se expande a meses: cada mes toma
    el valor vigente en su subperiodo; si el año no tiene subperiodos, el valor anual rige todo
    el año. El año en curso llega solo hasta el último mes del último subperiodo publicado."""
    df = read_sheet("bcp_anexo_iss.xlsx", "BCP", "CUADRO 1")
    rh, col = find_cell(df, r"^salario minimo legal")
    years: dict[int, dict] = {}
    year = None
    for r in range(rh + 2, df.shape[0]):
        lab = df.iat[r, 0]
        y = year_of(lab)
        if y is not None:
            year = y
            years[year] = {"anual": to_float(df.iat[r, col], serie, year), "sub": []}
            continue
        m = re.match(r"^\s*([A-Za-zé]+)\s*/\s*([A-Za-zé]+)\s*$", str(lab))
        if m and year is not None and month_of(m.group(1)) and month_of(m.group(2)):
            years[year]["sub"].append((month_of(m.group(1)), month_of(m.group(2)),
                                       to_float(df.iat[r, col], serie, f"{year} {lab}")))
    recs = []
    for y, d in years.items():
        spans = d["sub"] or [(1, 12, d["anual"])]
        for m1, m2, v in spans:
            if v is None:
                continue
            for mth in range(m1, m2 + 1):
                recs.append((pd.Timestamp(y, mth, 1), v))
    return pd.DataFrame(recs, columns=["fecha", "valor"])


def p_cotizaciones(serie: str) -> pd.DataFrame:
    """Planillas anuales HTML (día × mes) de la cotización referencial del BCP para el USD."""
    folder = comun.RAW_DIR / ISO3 / COTIZ_FUENTE
    files = sorted(folder.glob("bcp_cotizacion_usd_*.html"))
    if not files:
        raise FileNotFoundError(f"No hay planillas de cotización en {folder}")
    recs = []
    for f in files:
        year = int(re.search(r"(\d{4})", f.stem).group(1))
        text = f.read_bytes().decode("utf-8", errors="replace")
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.S | re.I):
            cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip()
                     for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)]
            if len(cells) != 13 or not cells[0].isdigit():
                continue
            day = int(cells[0])
            for mth, raw in enumerate(cells[1:], start=1):
                if norm(raw) in ("nd", ""):
                    continue      # sin cotización ese día (feriado / fin de semana): no se imputa
                try:
                    fecha = pd.Timestamp(year, mth, day)
                except ValueError:
                    continue      # 30 de febrero, etc.
                v = to_float(raw, serie, fecha.date())
                if v is not None:
                    recs.append((fecha, v))
    return pd.DataFrame(recs, columns=["fecha", "valor"])


def p_ine_desempleo(serie: str) -> pd.DataFrame:
    """EPHC trimestral: 'Total país' > 'Tasa de Desocupados'; años y trimestres en columnas."""
    df = read_sheet("ine_ephc_tasas.xlsx", "INE", 0)
    ry, _ = find_cell(df, r"^ano (19|20)\d{2}")
    rt, _ = find_cell(df, r"^total pais")
    row, _ = find_cell(df, r"^tasa de desocupados", rows=range(rt, df.shape[0]))
    year, dates = None, []
    for c in range(df.shape[1]):
        m = re.match(r"^ano ((?:19|20)\d{2})", norm(df.iat[ry, c]))
        year = int(m.group(1)) if m else year
        q = re.match(r"^\s*([1-4])", norm(df.iat[ry + 1, c]))
        dates.append(pd.Timestamp(year, 3 * int(q.group(1)) - 2, 1) if (year and q) else None)
    return series_from(dates, df.iloc[row].tolist(), serie)


def p_mef_fiscal(serie: str) -> pd.DataFrame:
    df = read_sheet("mef_situfin_anual.xlsx", "MEF", "% PIB")
    ry = next(r for r in range(df.shape[0]) if sum(year_of(v) is not None for v in df.iloc[r]) >= 5)
    row, _ = find_cell(df, r"^prestamo neto / endeudamiento neto", cols=[0])
    dates = [pd.Timestamp(year_of(v), 1, 1) if year_of(v) else None for v in df.iloc[ry]]
    return series_from(dates, df.iloc[row].tolist(), serie)


def p_mef_deuda(serie: str, measure: str = "pct_pib") -> pd.DataFrame:
    """Saldo de la deuda del Sector Público Total, fin de año.

    `measure`: 'pct_pib' (fila '% PIB') o 'usd' (la fila del rótulo, en millones de USD).
    El encabezado mezcla años (hasta 2019 y luego en la posición de diciembre: 2020-2022),
    meses como fecha y textos 'dic-23*'. Se toman solo los cierres de año: columnas con
    año o con 'dic-AA'."""
    df = read_sheet("mef_estadisticas_deuda.xlsx", "MEF", "1. Saldo")
    rs, _ = find_cell(df, r"^deuda sector publico total")
    if measure == "usd":
        find_cell(df, r"^\(en millones de usd\)$", rows=range(0, rs))   # verifica la unidad
        row = rs
    else:
        row, _ = find_cell(df, r"^% pib$", rows=range(rs, rs + 3))
    rh = next(r for r in range(rs - 1, -1, -1) if sum(year_of(v) is not None for v in df.iloc[r]) >= 5)
    dates = []
    for v in df.iloc[rh]:
        y = year_of(v)
        if y is None:
            m = re.match(r"^\s*dic-(\d{2})", str(v), re.I)
            y = 2000 + int(m.group(1)) if m else None
        dates.append(pd.Timestamp(y, 1, 1) if y else None)
    return series_from(dates, df.iloc[row].tolist(), serie)


# nombre_corto -> (archivos raw que necesita, parser). El CSV de config documenta cada serie.
PARSERS: dict[str, tuple[list[str], Callable[[str], pd.DataFrame]]] = {
    "pbi_real_trim": (["bcp_cnt.xlsx"], p_cnt("millones de guaranies", "real")),
    "pbi_real_var12m_trim": (["bcp_cnt.xlsx"], p_cnt("variacion interanual", "real")),
    "actividad_mensual_indice": (["bcp_imaep.xlsx"], p_imaep("IMAEP Serie Original")),
    "actividad_mensual_var12m": (["bcp_imaep.xlsx"], yoy(p_imaep("IMAEP Serie Original"))),
    "pbi_nominal_anual": (["bcp_pib_anual_desde_1950.xlsx"], p_pib_anual),
    "ipc_indice": (["bcp_ipc_desde_1950.xlsx"], p_ipc_1950("indice")),
    "inflacion_mensual": (["bcp_ipc_desde_1950.xlsx"], p_ipc_1950("mensual")),
    "inflacion_12m": (["bcp_ipc_desde_1950.xlsx"], p_ipc_1950("interanual")),
    "inflacion_subyacente_12m": (["bcp_anexo_ipc.xlsx"], p_anexo_ipc("CUADRO 7", "subyacente", "interanual")),
    "tasa_politica": (["bcp_lrm_tpm_tib.xlsx"], p_lrm(r"^tasa de politica monetaria$")),
    "tasa_interbancaria": (["bcp_lrm_tpm_tib.xlsx"], p_lrm(r"^tasa interbancaria \(tib\)")),
    "tasa_activa_promedio": (["bcp_indicadores_financieros.xlsx"], p_ind_financieros("tasa activa")),
    "tasa_pasiva_promedio": (["bcp_indicadores_financieros.xlsx"], p_ind_financieros("tasa pasiva")),
    "credito_privado": (["bcp_creditos_depositos.xlsx"], p_creditos("total de saldos", "en millones de guaranies")),
    "m2": (["bcp_agregados_monetarios.xlsx"], p_simple_dated("bcp_agregados_monetarios.xlsx", "Datos", "M2")),
    "tc_usd_promedio": (["bcp_tipo_cambio_nominal.xlsx"], p_simple_dated("bcp_tipo_cambio_nominal.xlsx", 0, "USD 1/")),
    "tc_usd_diario": ([COTIZ_KEY], p_cotizaciones),
    "reservas_internacionales": (["bcp_reservas_internacionales.xlsx"], p_reservas),
    "exportaciones": (["bcp_comercio_exterior_cuadros.xlsx"], p_year_month_block(
        "bcp_comercio_exterior_cuadros.xlsx", "43", "Exportaciones totales", 1 / 1000,
        ["Exportaciones totales", "Importaciones totales"])),
    "importaciones": (["bcp_comercio_exterior_cuadros.xlsx"], p_year_month_block(
        "bcp_comercio_exterior_cuadros.xlsx", "43", "Importaciones totales", 1 / 1000,
        ["Exportaciones totales", "Importaciones totales"])),
    "balanza_comercial": (["bcp_comercio_exterior_cuadros.xlsx"], p_year_month_block(
        "bcp_comercio_exterior_cuadros.xlsx", "43", "Saldo", 1 / 1000,
        ["Exportaciones totales", "Importaciones totales"])),
    "cuenta_corriente": (["bcp_balanza_pagos.xlsx"], p_bop("I.- Cuenta corriente")),
    "resultado_fiscal_pct_pbi": (["mef_situfin_anual.xlsx"], p_mef_fiscal),
    "deuda_publica_pct_pbi": (["mef_estadisticas_deuda.xlsx"], p_mef_deuda),
    "desempleo": (["ine_ephc_tasas.xlsx"], p_ine_desempleo),
    "salario_minimo": (["bcp_anexo_iss.xlsx"], p_salario_minimo),
    # Series adicionales
    "imaep_sin_agro_binacionales": (["bcp_imaep.xlsx"], p_imaep("IMAEP sin Agri. ni Bin. Serie Original")),
    "inflacion_subyacente_x1_12m": (["bcp_anexo_ipc.xlsx"], p_anexo_ipc("CUADRO 7", "subyacente (x1)", "interanual")),
    "meta_inflacion": (["bcp_meta_inflacion.xlsx"], p_meta_inflacion),
    "dolarizacion_credito_privado": (["bcp_creditos_depositos.xlsx"], p_creditos("moneda extranjera", "part. %")),
    "remesas_familiares": (["bcp_remesas_familiares.xlsx"], p_year_month_block(
        "bcp_remesas_familiares.xlsx", 0, "Total", 1 / 1000)),
    "exportaciones_soja_grano": (["bcp_comercio_exterior_cuadros.xlsx"], p_year_month_block(
        "bcp_comercio_exterior_cuadros.xlsx", "44a", "Granos de soja", 1 / 1000,
        ["Fibras de algodón", "Granos de soja", "Aceites de soja", "Harina de soja", "Trigo"])),
    "tcr_multilateral": (["bcp_tipo_cambio_real.xlsx"], p_simple_dated("bcp_tipo_cambio_real.xlsx", "Hoja1", "TCR")),
    # Capa comparable
    "m3_amplio": (["bcp_agregados_monetarios.xlsx"], p_simple_dated("bcp_agregados_monetarios.xlsx", "Datos", "M3")),
    "deuda_publica_usd": (["mef_estadisticas_deuda.xlsx"], lambda serie: p_mef_deuda(serie, "usd")),
    "inflacion_sae_12m": (["bcp_anexo_ipc.xlsx"], p_anexo_ipc_var(
        "CUADRO 5", "IPC sin Alim, Comb, Serv. Tarif", "inter.")),
}


# --------------------------------------------------------------------------------------
# Orquestación
# --------------------------------------------------------------------------------------
def selected_series(only: list[str] | None) -> list[dict]:
    rows = comun.load_series(ISO3)
    if only:
        missing = set(only) - {r["nombre_corto"] for r in rows}
        if missing:
            log.warning("No están activas en config/series/%s.csv: %s", ISO3, ", ".join(sorted(missing)))
        rows = [r for r in rows if r["nombre_corto"] in only]
    unknown = [r["nombre_corto"] for r in rows if r["nombre_corto"] not in PARSERS]
    if unknown:
        raise KeyError(f"Series sin parser en {Path(__file__).name}: {unknown}")
    return rows


def download(rows: list[dict], pause: float) -> int:
    keys = []
    for r in rows:
        for k in PARSERS[r["nombre_corto"]][0]:
            if k not in keys:
                keys.append(k)
    dl = Downloader(pause)
    errors = 0
    log.info("Descargando %d archivos oficiales", len(keys))
    for k in keys:
        try:
            if k == COTIZ_KEY:
                dl.fetch_cotizaciones()
            else:
                dl.fetch(RAW_FILES[k])
        except Exception as e:      # se sigue con el resto; el error queda en el log
            errors += 1
            log.error("  %s: %s", k, e)
    return errors


def process(rows: list[dict]) -> int:
    frames, errors = [], 0
    for r in rows:
        name = r["nombre_corto"]
        try:
            df = PARSERS[name][1](name)
        except Exception as e:
            errors += 1
            log.error("  %s: %s", name, e)
            continue
        if df.empty:
            errors += 1
            log.error("  %s: sin observaciones", name)
            continue
        df["fecha"] = comun.period_start(df["fecha"], r["frecuencia"])
        df = check_unique(df, name)
        df["pais"] = ISO3
        for col in ("fuente", "codigo_fuente", "nombre_corto", "indicador_comun", "frecuencia", "unidad"):
            df[col] = r[col]
        frames.append(df)
    DISCARDS.report()
    if frames:
        comun.write_interim(ISO3, pd.concat(frames, ignore_index=True))
    return errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--solo-procesar", action="store_true", help="no descarga; procesa data/raw/PRY")
    ap.add_argument("--serie", nargs="+", help="nombre_corto a procesar (por defecto, todas las activas)")
    ap.add_argument("--pausa", type=float, default=1.0, help="segundos entre peticiones (mín. 1)")
    args = ap.parse_args(argv)
    comun.setup_logging(ISO3)
    pause = max(1.0, args.pausa)

    rows = selected_series(args.serie)
    log.info("%s: %d series activas%s", ISO3, len(rows), " (solo procesar)" if args.solo_procesar else "")
    errors = 0
    if not args.solo_procesar:
        errors += download(rows, pause)
    if args.serie:
        # Con --serie se reprocesan TODAS las activas para no dejar el parquet incompleto.
        rows = selected_series(None)
    errors += process(rows)
    log.info("Fin: %d errores", errors)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
