"""Bolivia (BOL): descarga y procesa series macro de fuentes oficiales.

Fuentes:
- BCB  (Banco Central de Bolivia, www.bcb.gob.bo): tipo de cambio oficial, comercio exterior,
  balanza de pagos, reservas, agregados monetarios, crédito, inflación subyacente/núcleo,
  tasas del sistema financiero, estadísticas semanales (tasa de reporto, bolivianización).
- INE  (Instituto Nacional de Estadística, www.ine.gob.bo): IPC, PIB trimestral y anual
  (año de referencia 2017), IGAE, empleo urbano (ECE) y salario mínimo nacional.
- MEFP (Ministerio de Economía y Finanzas Públicas, www.economiayfinanzas.gob.bo):
  operaciones consolidadas del sector público no financiero.

Dos pasos separados (ver `src/comun.py`):
1. Descargar: entra a la página oficial de cada cuadro, localiza el enlace por el nombre del
   archivo o por el título del cuadro (el INE publica en una nube Nextcloud con enlaces
   `nube.ine.gob.bo/index.php/s/<token>/download` que cambian al actualizar) y guarda el
   archivo tal cual en `data/raw/BOL/<fuente>/` con un nombre estable.
2. Procesar: lee SOLO `data/raw/BOL/` y escribe `data/interim/BOL_observaciones.parquet`.

Trampas:
- www.economiayfinanzas.gob.bo no envía el certificado intermedio (Sectigo DV R36): falla la
  verificación TLS. Se arma un bundle = certifi + el intermedio descargado de la URL AIA del
  propio certificado (crt.sectigo.com) y se pasa a `comun.Client(verify=bundle)`. Solo si eso
  falla se usa verify=False para ese host (queda en el log).
- Régimen cambiario: hasta el 26/06/2026 el tipo de cambio oficial fue fijo (6,86 compra /
  6,96 venta). Desde el 29/06/2026 el BCB fija un TCO único (RD 88/2026 y RD 142/2026) que
  el BCB publica en la columna "Compra"; la columna "Venta" se discontinúa.

Uso:
    python src/paises/bol.py                       # descarga + procesa todas las activas
    python src/paises/bol.py --solo-procesar       # solo reprocesa data/raw/BOL
    python src/paises/bol.py --serie ipc_indice tc_usd_diario
    python src/paises/bol.py --pausa 2
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import logging
import re
import ssl
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urljoin

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import comun  # noqa: E402

ISO3 = "BOL"
log = logging.getLogger("data_macro_paises")

BCB = "https://www.bcb.gob.bo/"
INE = "https://www.ine.gob.bo/"
MEFP = "https://www.economiayfinanzas.gob.bo/"
MEFP_HOST = "economiayfinanzas.gob.bo"   # con y sin www
# Intermedio que el servidor del MEFP no envía (URL AIA de su certificado).
MEFP_INTERMEDIATE = "http://crt.sectigo.com/SectigoPublicServerAuthenticationCADVR36.crt"

MONTHS = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8,
          "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12}
NO_DATA = {"", "-", "--", "s/d", "nd", "n.d.", "...", "na", "(p)", "*"}


# --------------------------------------------------------------------------------------
# Descarga
# --------------------------------------------------------------------------------------
@dataclass
class RawFile:
    key: str          # nombre estable en data/raw/BOL/<fuente>/ ('{year}' si hay uno por año)
    fuente: str
    page: str         # página oficial donde está el enlace
    href: str = ""    # regex sobre el href decodificado
    text: str = ""    # o regex sobre el texto del enlace (títulos de cuadros del INE)
    per_year: bool = False   # un archivo por año: el regex de href captura el año


RAW_FILES: dict[str, RawFile] = {f.key: f for f in [
    RawFile("bcb_tipo_cambio_oficial.xlsx", "BCB", BCB + "?q=content/sector-externo-0",
            href=r"/Tipo de Cambio Oficial ?\.xlsx$"),
    RawFile("bcb_balanza_comercial.xlsx", "BCB", BCB + "?q=content/sector-externo-0",
            href=r"/Balanza Comercial\.xlsx$"),
    RawFile("bcb_exportaciones.xlsx", "BCB", BCB + "?q=content/sector-externo-0",
            href=r"Comercio Internacional de Bienes/Exportaciones\.xlsx$"),
    RawFile("bcb_bop_series.xlsx", "BCB", BCB + "?q=content/sector-externo-0",
            href=r"/\d\. ?Serie_BOP_[^/]*\.xlsx$"),
    RawFile("bcb_rin.xlsx", "BCB", BCB + "?q=content/sector-externo-0",
            href=r"/Reservas_Internacionales_Netas_del_Banco_Central_de_Bolivia_por_componentes\.xlsx$"),
    RawFile("bcb_remesas.xlsx", "BCB", BCB + "?q=content/sector-externo-0",
            href=r"/Remesas de trabajadores recibidas segun pais de origen\.xlsx$"),
    RawFile("bcb_agregados_monetarios.xlsx", "BCB", BCB + "?q=content/sector-monetario",
            href=r"/7\. Agregados Monetarios\.xlsx$"),
    RawFile("bcb_balance_sistema_financiero.xlsx", "BCB", BCB + "?q=content/sector-monetario",
            href=r"/Balances Consolidados/1\. Sistema Financiero\.xlsx$"),
    RawFile("bcb_inflacion_subyacente.xlsx", "BCB", BCB + "?q=content/sector-precios",
            href=r"/Inflacion subyacente\.xlsx$"),
    RawFile("bcb_inflacion_nucleo.xlsx", "BCB", BCB + "?q=content/sector-precios",
            href=r"/Inflacion nucleo\.xlsx$"),
    RawFile("bcb_estadisticas_semanales.xlsx", "BCB", BCB + "?q=estad-sticas-semanales",
            href=r"/Semanal ?\d+_ ?\d{4}[^/]*\.xlsx$"),
    RawFile("bcb_tasas_activas_sf_{year}.xlsx", "BCB",
            BCB + "?q=tasas-de-inter-s-activas&field_tipo_de_tasa_activa_value=asf",
            href=r"/30 ?AC ?M ?((?:19|20)\d{2})[^/]*\.xlsx$", per_year=True),
    RawFile("bcb_tasas_pasivas_dpf_{year}.xlsx", "BCB",
            BCB + "?q=tasas-de-inter-s-pasivas&field_tipo_de_tasa_pasiva_value=pa",
            href=r"/28 ?PA ?M ?((?:19|20)\d{2})[^/]*\.xlsx$", per_year=True),
    RawFile("ine_ipc_serie_empalmada.xlsx", "INE", INE + "index.php/serie-historica-empalmada/",
            text=r"^Índice General, Variación Mensual, Acumulada y a 12 Meses$"),
    RawFile("ine_pib_trim_volumen.xlsx", "INE", INE + "referencia2017/pib_trimestral.html",
            text=r"^BOLIVIA: MEDIDAS DE VOLUMEN ENCADENADAS DEL PRODUCTO INTERNO BRUTO POR GRUPOS DE ACTIVIDAD"),
    RawFile("ine_pib_trim_variacion.xlsx", "INE", INE + "referencia2017/pib_trimestral.html",
            text=r"^BOLIVIA: VARIACIÓN DE LAS MEDIDAS DE VOLUMEN ENCADENADAS DEL PRODUCTO INTERNO BRUTO POR GRUPOS"),
    RawFile("ine_pib_anual_corrientes.xlsx", "INE", INE + "referencia2017/pib_anual.html",
            text=r"^2\.1\.1 BOLIVIA: PRODUCTO INTERNO BRUTO POR EL ENFOQUE DE LA PRODUCCIÓN"),
    RawFile("ine_igae_indice.xlsx", "INE",
            INE + "index.php/estadisticas-economicas/indice-global-de-actividad-economica-igae/",
            text=r"INDICE GLOBAL DE LA ACTIVIDAD ECONÓMICA, POR MES"),
    RawFile("ine_igae_variacion.xlsx", "INE",
            INE + "index.php/estadisticas-economicas/indice-global-de-actividad-economica-igae/",
            text=r"VARIACIÓN A SIMILAR PERIODO DEL IGAE, POR MES"),
    RawFile("ine_empleo_urbano_mensual.xlsx", "INE",
            INE + "index.php/estadisticas-sociales/bolivia-area-urbana-principales-indicadores-de-empleo-por-mes-segun-sexo/",
            href=r"^https://(?:nube|nimbus)\.ine\.gob\.bo/index\.php/s/\w+/download$"),
    RawFile("ine_salario_minimo.xlsx", "INE",
            INE + "index.php/estadisticas-economicas/salario-minimo-nacional-cuadros-estadisticos/",
            href=r"^https://(?:nube|nimbus)\.ine\.gob\.bo/index\.php/s/\w+/download$"),
    RawFile("mefp_spnf_{year}.xlsx", "MEFP", MEFP + "index.php/ejecucion-sector-publico-no-financiero",
            href=r"/SPNFGOBEMP((?:19|20)\d{2})[^/]*\.xlsx$", per_year=True),
]}


def links(page_html: str, base: str) -> list[tuple[str, str]]:
    """(href absoluto, texto del enlace) de una página."""
    out = []
    for m in re.finditer(r"""<a\s[^>]*href=["']([^"']+)["'][^>]*>(.*?)</a>""", page_html, re.S | re.I):
        href = urljoin(base, html.unescape(m.group(1)).strip())
        text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", m.group(2))).split())
        out.append((href, text))
    return out


def mefp_bundle(client: comun.Client) -> str | bool:
    """Bundle CA = certifi + intermedio Sectigo que el servidor del MEFP omite."""
    try:
        import certifi
        der = client.get(MEFP_INTERMEDIATE).content
        pem = ssl.DER_cert_to_PEM_cert(der)
        path = Path(tempfile.mkdtemp(prefix="bol_ca_")) / "bundle.pem"
        path.write_text(Path(certifi.where()).read_text(encoding="utf-8") + "\n" + pem, encoding="utf-8")
        return str(path)
    except Exception as e:      # último recurso, solo para este host
        log.warning("No se pudo armar el bundle TLS del MEFP (%s): se usa verify=False", e)
        return False


class Downloader:
    def __init__(self, pause: float):
        self.http = comun.Client(pause=pause)
        self.mefp = comun.Client(pause=pause, verify=mefp_bundle(self.http))
        self.pages: dict[str, str] = {}

    def client_for(self, url: str) -> comun.Client:
        return self.mefp if url.split("/")[2].endswith(MEFP_HOST) else self.http

    def get(self, url: str):
        return self.client_for(url).get(url)

    def page(self, url: str) -> str:
        if url not in self.pages:
            content = self.get(url).content
            # Varias páginas (p. ej. referencia2017 del INE) son UTF-8 sin charset en la
            # cabecera: requests las decodificaría como latin-1 y los títulos no calzarían.
            try:
                self.pages[url] = content.decode("utf-8")
            except UnicodeDecodeError:
                self.pages[url] = content.decode("latin-1")
        return self.pages[url]

    def targets(self, rf: RawFile) -> list[tuple[str, str]]:
        """[(clave raw, url)] del archivo (o de todos los años si es por año)."""
        found = []
        for href, text in links(self.page(rf.page), rf.page):
            target = unquote(href)
            if rf.href:
                m = re.search(rf.href, target, re.I)
                if not m:
                    continue
                key = rf.key.format(year=m.group(1)) if rf.per_year else rf.key
            elif re.search(norm(rf.text), norm(text)):
                key = rf.key
            else:
                continue
            if key not in {k for k, _ in found}:
                found.append((key, href))
            if not rf.per_year:
                break
        if not found:
            raise LookupError(f"No se encontró el enlace de {rf.key} en {rf.page}")
        return found

    def fetch(self, rf: RawFile) -> None:
        for key, url in self.targets(rf):
            r = self.get(url)
            if r.content[:2] != b"PK":
                raise ValueError(f"{key}: la respuesta no es un .xlsx ({r.content[:60]!r})")
            action = comun.save_raw(ISO3, rf.fuente, key, r.content, url)
            log.info("  %-40s %-11s %s", key, action, unquote(url)[-80:])


# --------------------------------------------------------------------------------------
# Utilidades de parseo
# --------------------------------------------------------------------------------------
def norm(text) -> str:
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return ""
    t = unicodedata.normalize("NFKD", str(text))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.replace("\n", " ").split()).lower()


DISCARDED: dict[str, list] = {}


def to_float(v, serie: str = "", periodo=None):
    """Número o None; los marcadores de sin dato se descartan (no se imputan) y se registran."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    s = str(v).strip()
    try:
        return float(s.replace(",", "")) if re.fullmatch(r"-?[\d,]*\.?\d+", s) else float(s)
    except ValueError:
        if s and serie and norm(s) not in ("",):
            DISCARDED.setdefault(serie, []).append((periodo, s))
        return None


def month_of(label) -> int | None:
    t = re.sub(r"\(.*?\)", "", norm(label)).strip(" .*")
    return MONTHS.get(t[:3]) if t[:3] in MONTHS and t.isalpha() else None


def year_of(label) -> int | None:
    if isinstance(label, (int, float)) and not pd.isna(label) and 1900 <= label <= 2100:
        return int(label)
    m = re.match(r"^\s*((?:19|20)\d{2})(?:\.0)?\s*(?:\(p\)|\*|\(\d\))?\s*$", str(label), re.I)
    return int(m.group(1)) if m else None


def is_date(v) -> bool:
    return isinstance(v, (dt.datetime, pd.Timestamp))


def raw(key: str, fuente: str) -> Path:
    p = comun.raw_path(ISO3, fuente, key)
    if not p.exists():
        raise FileNotFoundError(f"Falta {p} (¿no se descargó?)")
    return p


def read_sheet(key: str, fuente: str, sheet) -> pd.DataFrame:
    path = raw(key, fuente)
    if isinstance(sheet, str) and sheet.startswith("re:"):
        names = pd.ExcelFile(path).sheet_names
        sheet = next(n for n in names if re.search(sheet[3:], n, re.I))
    return pd.read_excel(path, sheet_name=sheet, header=None)


def find_cell(df: pd.DataFrame, pattern: str, rows=None, cols=None) -> tuple[int, int]:
    rx = re.compile(pattern)
    for r in (range(df.shape[0]) if rows is None else rows):
        for c in (range(df.shape[1]) if cols is None else cols):
            t = norm(df.iat[r, c])
            if t and rx.search(t):
                return r, c
    raise LookupError(f"No se encontró {pattern!r}")


def ffill_row(df: pd.DataFrame, r: int) -> list[str]:
    out, last = [], ""
    for v in df.iloc[r]:
        last = norm(v) or last
        out.append(last)
    return out


def series_from(dates, values, serie: str, scale: float = 1.0) -> pd.DataFrame:
    recs = []
    for d, v in zip(dates, values):
        if d is None or pd.isna(d):
            continue
        x = to_float(v, serie, pd.Timestamp(d).date())
        if x is not None:
            recs.append((pd.Timestamp(d), x * scale))
    return pd.DataFrame(recs, columns=["fecha", "valor"])


def dated_column(key: str, fuente: str, sheet, header: str, scale: float = 1.0,
                 date_col: int | None = None) -> Callable[[str], pd.DataFrame]:
    """Cuadro con una columna de fechas y la serie bajo un encabezado (regex normalizado)."""
    def parse(serie: str) -> pd.DataFrame:
        df = read_sheet(key, fuente, sheet)
        rh, col = find_cell(df, header)
        dc = date_col
        if dc is None:
            dc = max(range(df.shape[1]), key=lambda c: sum(is_date(v) for v in df.iloc[rh:, c]))
        sub = df.iloc[rh + 1:]
        dates = [pd.Timestamp(v) if is_date(v) else None for v in sub[dc]]
        return series_from(dates, sub[col].tolist(), serie, scale)
    return parse


# --------------------------------------------------------------------------------------
# Parsers por cuadro
# --------------------------------------------------------------------------------------
def p_ine_ipc(sheet_id: str) -> Callable[[str], pd.DataFrame]:
    """IPC empalmado del INE (1937-): años en columnas y meses en filas."""
    def parse(serie: str) -> pd.DataFrame:
        df = read_sheet("ine_ipc_serie_empalmada.xlsx", "INE", "re:" + re.escape(sheet_id))
        rh, _ = find_cell(df, r"^mes$", cols=[0])
        years = [year_of(v) for v in df.iloc[rh]]
        dates, vals = [], []
        for r in range(rh + 1, df.shape[0]):
            m = month_of(df.iat[r, 0])
            if m is None:
                continue
            for c, y in enumerate(years):
                if y:
                    dates.append(pd.Timestamp(y, m, 1))
                    vals.append(df.iat[r, c])
        return series_from(dates, vals, serie)
    return parse


def p_pib_trim(key: str) -> Callable[[str], pd.DataFrame]:
    """PIB trimestral del INE (referencia 2017): años sobre trimestres I-IV en columnas."""
    def parse(serie: str) -> pd.DataFrame:
        df = read_sheet(key, "INE", 0)
        rh, _ = find_cell(df, r"^actividad economica$")
        row, _ = find_cell(df, r"^producto interno bruto", rows=range(rh + 1, df.shape[0]))
        year, dates = None, []
        for c in range(df.shape[1]):
            year = year_of(df.iat[rh, c]) or year
            q = {"i": 1, "ii": 2, "iii": 3, "iv": 4}.get(norm(df.iat[rh + 1, c]))
            dates.append(pd.Timestamp(year, 3 * q - 2, 1) if (year and q) else None)
        return series_from(dates, df.iloc[row].tolist(), serie)
    return parse


def p_pib_anual(serie: str) -> pd.DataFrame:
    df = read_sheet("ine_pib_anual_corrientes.xlsx", "INE", 0)
    rh, _ = find_cell(df, r"^concepto$")
    row, _ = find_cell(df, r"^producto interno bruto", rows=range(rh + 1, df.shape[0]))
    dates = [pd.Timestamp(year_of(v), 1, 1) if year_of(v) else None for v in df.iloc[rh]]
    return series_from(dates, df.iloc[row].tolist(), serie)


def p_igae(key: str) -> Callable[[str], pd.DataFrame]:
    """IGAE (1990=100): años en una fila (con 0 o vacío en las celdas repetidas) y meses debajo."""
    def parse(serie: str) -> pd.DataFrame:
        df = read_sheet(key, "INE", 0)
        rh, _ = find_cell(df, r"^actividad economica$", cols=[0])
        row, _ = find_cell(df, r"^indice general$", cols=[0])
        year, dates = None, []
        for c in range(df.shape[1]):
            y = year_of(str(df.iat[rh, c]).replace("(p)", "")) if pd.notna(df.iat[rh, c]) else None
            year = y if (y and y > 1900) else year
            m = month_of(df.iat[rh + 1, c])
            dates.append(pd.Timestamp(year, m, 1) if (year and m) else None)
        return series_from(dates, df.iloc[row].tolist(), serie)
    return parse


def p_ine_empleo(serie: str) -> pd.DataFrame:
    df = read_sheet("ine_empleo_urbano_mensual.xlsx", "INE", 0)
    rh, _ = find_cell(df, r"^indicadores de empleo$", cols=[0])
    row, _ = find_cell(df, r"^tasa de desocupacion", cols=[0])
    year, dates = None, []
    for c in range(df.shape[1]):
        year = year_of(df.iat[rh, c]) or year
        m = month_of(df.iat[rh + 1, c])
        dates.append(pd.Timestamp(year, m, 1) if (year and m) else None)
    return series_from(dates, df.iloc[row].tolist(), serie)


def p_salario_minimo(serie: str) -> pd.DataFrame:
    """Salario mínimo nacional por gestión (INE), expandido a meses.

    Nota del cuadro: desde 2007 la vigencia es desde el 1 de enero de cada gestión. Antes de
    2007 rige desde el mes de promulgación (los meses previos mantienen el valor anterior).
    Si una gestión aparece dos veces y la segunda se promulgó en el último trimestre, esa
    fila corresponde a la gestión siguiente (nota (3): DS 5503 de dic-2025 'vigente para la
    gestión 2026'). Se expande hasta diciembre de cada gestión, sin pasar del mes en curso.
    """
    df = read_sheet("ine_salario_minimo.xlsx", "INE", 0)
    rh, cy = find_cell(df, r"^ano$")
    _, cv = find_cell(df, r"^salario minimo nacional", rows=[rh])
    _, cf = find_cell(df, r"^fecha de promulgacion", rows=[rh])
    by_year: dict[int, tuple[pd.Timestamp, float]] = {}
    for r in range(rh + 1, df.shape[0]):
        y = year_of(df.iat[r, cy])
        v = to_float(df.iat[r, cv], serie, y)
        if y is None or v is None:
            continue
        prom = pd.Timestamp(df.iat[r, cf]) if is_date(df.iat[r, cf]) else pd.Timestamp(y, 1, 1)
        if y in by_year and prom.month >= 10 and prom.year == y:
            y += 1
        if y in by_year:
            raise ValueError(f"{serie}: gestión {y} repetida en el cuadro")
        by_year[y] = (prom, v)
    today = pd.Timestamp(dt.date.today()).to_period("M").start_time
    recs, last = [], None
    for y in sorted(by_year):
        prom, v = by_year[y]
        start = 1 if y >= 2007 else (prom.month if prom.year == y else 1)
        for m in range(1, 13):
            fecha = pd.Timestamp(y, m, 1)
            if fecha > today:
                break
            val = v if m >= start else last
            if val is not None:
                recs.append((fecha, val))
        last = v
    return pd.DataFrame(recs, columns=["fecha", "valor"])


def p_bop(manual: str) -> Callable[[str], pd.DataFrame]:
    """Serie de balanza de pagos del BCB: fechas fin de trimestre; MBP5 (1996-2013) y MBP6 (2014-)."""
    def parse(serie: str) -> pd.DataFrame:
        df = read_sheet("bcb_bop_series.xlsx", "BCB", r"re:-\s*" + manual + r"\s+Manual")
        rh, col = find_cell(df, r"^cuenta corriente$")
        dates = [pd.Timestamp(v) if is_date(v) else None for v in df.iloc[rh + 1:, 0]]
        return series_from(dates, df.iloc[rh + 1:, col].tolist(), serie)
    return parse


def p_semanal(block: str, label: str) -> Callable[[str], pd.DataFrame]:
    """Estadísticas semanales del BCB: las primeras columnas son cierres de mes (1987-…),
    luego vienen 'Semana n' y días del mes en curso (se ignoran)."""
    def parse(serie: str) -> pd.DataFrame:
        df = read_sheet("bcb_estadisticas_semanales.xlsx", "BCB", 0)
        rb, _ = find_cell(df, block)
        row, _ = find_cell(df, label, rows=range(rb + 1, min(rb + 8, df.shape[0])))
        rd = next(r for r in range(df.shape[0]) if sum(is_date(v) for v in df.iloc[r]) > 50)
        dates = []
        for v in df.iloc[rd]:
            if isinstance(v, str) and norm(v).startswith("semana"):
                break
            dates.append(pd.Timestamp(v) if is_date(v) else None)
        return series_from(dates, df.iloc[row, :len(dates)].tolist(), serie)
    return parse


def p_tasas_sf(prefix: str, sheet: str) -> Callable[[str], pd.DataFrame]:
    """Tasas efectivas del sistema financiero (BCB), un archivo por año.

    Cada mes es una fila 'Ene 2026' con el total del sistema y debajo una fila por tipo de
    entidad. Solo los archivos recientes traen el total en la fila del mes: en los antiguos la
    fila del mes viene vacía y no se calcula ningún promedio (quedan fuera)."""
    def parse(serie: str) -> pd.DataFrame:
        folder = comun.RAW_DIR / ISO3 / "BCB"
        files = sorted(folder.glob(prefix + "_*.xlsx"))
        if not files:
            raise FileNotFoundError(f"No hay archivos {prefix}_*.xlsx en {folder}")
        recs = []
        for f in files:
            df = read_sheet(f.name, "BCB", sheet)
            rh, col = find_cell(df, r"^total efect")
            for r in range(rh + 1, df.shape[0]):
                m = re.match(r"^\s*([A-Za-z]{3})\w*\.?\s+((?:19|20)\d{2})\s*$", str(df.iat[r, 0]))
                if not m or month_of(m.group(1)) is None:
                    continue
                v = to_float(df.iat[r, col], serie, f"{m.group(2)}-{m.group(1)}")
                if v is not None and v != 0:
                    recs.append((pd.Timestamp(int(m.group(2)), month_of(m.group(1)), 1), v))
        return pd.DataFrame(recs, columns=["fecha", "valor"])
    return parse


def spnf_global() -> pd.DataFrame:
    """Sup (def) global anual del SPNF (MEFP), millones de Bs; solo gestiones completas (DICIEMBRE)."""
    folder = comun.RAW_DIR / ISO3 / "MEFP"
    recs = []
    for f in sorted(folder.glob("mefp_spnf_*.xlsx")):
        df = read_sheet(f.name, "MEFP", r"re:^SPNF")   # SPNF, SPNF_BCB, SPNF_Web...
        r_title, _ = find_cell(df, r"^(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|"
                                   r"octubre|noviembre|diciembre)\s+(19|20)\d{2}", rows=range(0, 6))
        title = norm(df.iat[r_title, 0])
        if not title.startswith("diciembre"):
            log.info("  %s: gestión incompleta (%s), se omite", f.name, title)
            continue
        year = int(re.search(r"((?:19|20)\d{2})", title).group(1))
        rh, ct = find_cell(df, r"^total$")
        row, _ = find_cell(df, r"^sup \(def\) global", cols=[0])
        recs.append((pd.Timestamp(year, 1, 1), to_float(df.iat[row, ct], "resultado_global_spnf", year)))
    return pd.DataFrame(recs, columns=["fecha", "valor"]).dropna()


def p_spnf_global(serie: str) -> pd.DataFrame:
    return spnf_global()


def p_spnf_pct_pib(serie: str) -> pd.DataFrame:
    """Resultado global del SPNF en % del PIB: CALCULADO = MEFP (Bs) / PIB nominal INE (Bs)."""
    res = spnf_global().set_index("fecha").valor
    pib = p_pib_anual(serie + "(pib)").set_index("fecha").valor
    out = (res / pib * 100).dropna()
    return out.rename("valor").rename_axis("fecha").reset_index()


PARSERS: dict[str, tuple[list[str], Callable[[str], pd.DataFrame]]] = {
    "pbi_real_trim": (["ine_pib_trim_volumen.xlsx"], p_pib_trim("ine_pib_trim_volumen.xlsx")),
    "pbi_real_var12m_trim": (["ine_pib_trim_variacion.xlsx"], p_pib_trim("ine_pib_trim_variacion.xlsx")),
    "actividad_mensual_indice": (["ine_igae_indice.xlsx"], p_igae("ine_igae_indice.xlsx")),
    "actividad_mensual_var12m": (["ine_igae_variacion.xlsx"], p_igae("ine_igae_variacion.xlsx")),
    "pbi_nominal_anual": (["ine_pib_anual_corrientes.xlsx"], p_pib_anual),
    "ipc_indice": (["ine_ipc_serie_empalmada.xlsx"], p_ine_ipc("1.1")),
    "inflacion_mensual": (["ine_ipc_serie_empalmada.xlsx"], p_ine_ipc("1.2")),
    "inflacion_12m": (["ine_ipc_serie_empalmada.xlsx"], p_ine_ipc("1.4")),
    "inflacion_subyacente_12m": (["bcb_inflacion_subyacente.xlsx"], dated_column(
        "bcb_inflacion_subyacente.xlsx", "BCB", 0, r"^a 12 meses$")),
    "tasa_activa_promedio": (["bcb_tasas_activas_sf_{year}.xlsx"], p_tasas_sf("bcb_tasas_activas_sf", r"re:MN$")),
    "tasa_pasiva_promedio": (["bcb_tasas_pasivas_dpf_{year}.xlsx"], p_tasas_sf("bcb_tasas_pasivas_dpf", r"re:MN$")),
    "credito_privado": (["bcb_balance_sistema_financiero.xlsx"], None),   # se completa abajo
    "m2": (["bcb_agregados_monetarios.xlsx"], dated_column(
        "bcb_agregados_monetarios.xlsx", "BCB", 0, r"^m2$", 1 / 1000)),
    "tc_usd_promedio": (["bcb_tipo_cambio_oficial.xlsx"], dated_column(
        "bcb_tipo_cambio_oficial.xlsx", "BCB", "re:mensual", r"^compra$")),
    "tc_usd_diario": (["bcb_tipo_cambio_oficial.xlsx"], dated_column(
        "bcb_tipo_cambio_oficial.xlsx", "BCB", "re:diaria", r"^compra$")),
    "reservas_internacionales": (["bcb_rin.xlsx"], dated_column(
        "bcb_rin.xlsx", "BCB", "re:mens", r"^reservas internacionales netas de obligaciones")),
    "exportaciones": (["bcb_balanza_comercial.xlsx"], dated_column(
        "bcb_balanza_comercial.xlsx", "BCB", "Mensual", r"^exportacion valor fob")),
    "importaciones": (["bcb_balanza_comercial.xlsx"], dated_column(
        "bcb_balanza_comercial.xlsx", "BCB", "Mensual", r"^importacion valor fob")),
    "balanza_comercial": (["bcb_balanza_comercial.xlsx"], dated_column(
        "bcb_balanza_comercial.xlsx", "BCB", "Mensual", r"^balanza comercial x-m")),
    "cuenta_corriente": (["bcb_bop_series.xlsx"], p_bop("VI")),
    "resultado_fiscal_pct_pbi": (["mefp_spnf_{year}.xlsx", "ine_pib_anual_corrientes.xlsx"], p_spnf_pct_pib),
    "desempleo": (["ine_empleo_urbano_mensual.xlsx"], p_ine_empleo),
    "salario_minimo": (["ine_salario_minimo.xlsx"], p_salario_minimo),
    # Series adicionales
    "inflacion_nucleo_12m": (["bcb_inflacion_nucleo.xlsx"], dated_column(
        "bcb_inflacion_nucleo.xlsx", "BCB", 0, r"^a 12 meses$")),
    "tasa_reporto_mn": (["bcb_estadisticas_semanales.xlsx"], p_semanal(
        r"^tasas premio de reporto", r"^moneda nacional")),
    "bolivianizacion_credito": (["bcb_estadisticas_semanales.xlsx"], p_semanal(
        r"^credito del sistema financiero al sector privado", r"^bolivianizacion")),
    "tc_usd_venta_promedio": (["bcb_tipo_cambio_oficial.xlsx"], dated_column(
        "bcb_tipo_cambio_oficial.xlsx", "BCB", "re:mensual", r"^venta")),
    "remesas_recibidas": (["bcb_remesas.xlsx"], dated_column(
        "bcb_remesas.xlsx", "BCB", "re:^mensual", r"^total$")),
    "exportaciones_gas_natural": (["bcb_exportaciones.xlsx"], dated_column(
        "bcb_exportaciones.xlsx", "BCB", "Mensual", r"^gas natural$")),
    "cuenta_corriente_mbp5": (["bcb_bop_series.xlsx"], p_bop("V")),
    "resultado_global_spnf": (["mefp_spnf_{year}.xlsx"], p_spnf_global),
    # Capa comparable: agregado amplio, reservas brutas y tipo de cambio de venta diario
    "m3_amplio": (["bcb_agregados_monetarios.xlsx"], dated_column(
        "bcb_agregados_monetarios.xlsx", "BCB", 0, r"^m'3$", 1 / 1000)),
    "reservas_brutas": (["bcb_rin.xlsx"], dated_column(
        "bcb_rin.xlsx", "BCB", "re:mens", r"^reservas brutas$")),
    "tc_usd_venta_diario": (["bcb_tipo_cambio_oficial.xlsx"], dated_column(
        "bcb_tipo_cambio_oficial.xlsx", "BCB", "re:diaria", r"^venta")),
}


def p_credito(serie: str) -> pd.DataFrame:
    """Balance consolidado del sistema financiero (activo): financiamiento al sector privado, total."""
    df = read_sheet("bcb_balance_sistema_financiero.xlsx", "BCB", "re:^activo$")
    rs, _ = find_cell(df, r"^financiamiento al sector privado")
    top = ffill_row(df, rs)
    col = next(c for c in range(df.shape[1])
               if top[c].startswith("financiamiento al sector privado")
               and any(norm(df.iat[r, c]) == "total" for r in range(rs + 1, rs + 4)))
    dates = [pd.Timestamp(v) if is_date(v) else None for v in df.iloc[rs + 1:, 0]]
    return series_from(dates, df.iloc[rs + 1:, col].tolist(), serie, 1 / 1000)


PARSERS["credito_privado"] = (["bcb_balance_sistema_financiero.xlsx"], p_credito)


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
    keys: list[str] = []
    for r in rows:
        for k in PARSERS[r["nombre_corto"]][0]:
            if k not in keys:
                keys.append(k)
    dl = Downloader(pause)
    errors = 0
    log.info("Descargando %d archivos/grupos oficiales", len(keys))
    for k in keys:
        try:
            dl.fetch(RAW_FILES[k])
        except Exception as e:
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
        dup = df.duplicated("fecha", keep=False)
        if dup.any():
            errors += 1
            log.error("  %s: periodos repetidos %s", name, df[dup].fecha.dt.date.unique()[:5])
            continue
        df["pais"] = ISO3
        for col in ("fuente", "codigo_fuente", "nombre_corto", "indicador_comun", "frecuencia", "unidad"):
            df[col] = r[col]
        frames.append(df.sort_values("fecha"))
    for serie, items in DISCARDED.items():
        log.info("  %s: %d valores sin dato descartados (p. ej. %s)", serie, len(items),
                 ", ".join(f"{p}={v!r}" for p, v in items[:4]))
    if frames:
        comun.write_interim(ISO3, pd.concat(frames, ignore_index=True))
    return errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--solo-procesar", action="store_true", help="no descarga; procesa data/raw/BOL")
    ap.add_argument("--serie", nargs="+", help="nombre_corto a descargar (por defecto, todas las activas)")
    ap.add_argument("--pausa", type=float, default=1.0, help="segundos entre peticiones (mín. 1)")
    args = ap.parse_args(argv)
    comun.setup_logging(ISO3)

    rows = selected_series(args.serie)
    log.info("%s: %d series activas%s", ISO3, len(rows), " (solo procesar)" if args.solo_procesar else "")
    errors = 0
    if not args.solo_procesar:
        errors += download(rows, max(1.0, args.pausa))
    if args.serie:
        # Con --serie se reprocesan TODAS las activas para no dejar el parquet incompleto.
        rows = selected_series(None)
    errors += process(rows)
    log.info("Fin: %d errores", errors)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
