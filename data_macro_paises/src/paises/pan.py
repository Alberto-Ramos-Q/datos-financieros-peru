"""Panamá: descarga y procesa series del INEC, la Superintendencia de Bancos y el MEF.

Panamá no tiene banco central y está dolarizado (balboa = USD 1:1): no hay tasa de
política, tipo de cambio, reservas internacionales ni M2 oficiales (ver docs/fuentes/PAN.md).

Fuentes oficiales (todas por descarga de archivos publicados, sin API ni token):
- INEC (Contraloría General): www.inec.gob.pa. Los nombres de archivo llevan una marca de
  tiempo que cambia en cada publicación, así que la URL se busca en la página de la
  publicación (por texto del enlace) y el archivo se guarda con un nombre estable.
    · IMAE (avance de cifras, ID_CIFRAS=49): cuadro .xlsx y serie .csv
    · IPC base 2024 (avance, ID_CIFRAS=10): Anexo 4
    · PIB trimestral y anual (publicaciones, subcategorías 73 y 26)
    · Encuesta de Mercado Laboral, Cuadro 2 histórico (subcategoría 38)
    · Principales Indicadores Económicos Mensuales (PIEM), una página por año: comercio
      exterior y Canal de Panamá
    · Balanza de pagos, Cuadro 1 MBP5 de cada publicación trimestral (subcategoría 24)
- Superintendencia de Bancos (SBP): tasa interbancaria de referencia, tasas de crédito
  y depósito, saldos de crédito local por sector (reporte RE0034A).
- MEF: balance fiscal del sector público no financiero (archivos de cierre de año).

Los archivos históricos (publicaciones viejas que ya no cambian) se bajan una sola vez;
`--rehacer-historico` los vuelve a bajar.

Uso:
    python pan.py                      # descarga + procesa
    python pan.py --solo-procesar      # solo reconstruye el parquet desde data/raw/PAN
    python pan.py --serie ipc_indice exportaciones
    python pan.py --pausa 2
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import io
import logging
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import urljoin

import openpyxl
import pandas as pd
import requests
import xlrd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import comun  # noqa: E402

ISO3 = "PAN"
log = logging.getLogger("data_macro_paises")

INEC = "https://www.inec.gob.pa"
INEC_AVANCE = INEC + "/avance/Default2.aspx?ID_CATEGORIA={cat}&ID_CIFRAS={cifras}&ID_IDIOMA=1"
INEC_AVANCE_CAT = INEC + "/avance/Default.aspx?ID_CATEGORIA={cat}&ID_IDIOMA=1"
INEC_PUBS = INEC + "/publicaciones/Default2.aspx?ID_CATEGORIA={cat}&ID_SUBCATEGORIA={sub}"
INEC_PUB = INEC + "/publicaciones/Default3.aspx?ID_PUBLICACION={pub}&ID_CATEGORIA={cat}&ID_SUBCATEGORIA={sub}"
SBP = "https://www.superbancos.gob.pa"
SBP_RE0034A = (SBP + "/documentos/financiera_y_estadistica/reportes_estadisticos/{y}/{m:02d}/"
               "cartera_sectorial/RE-CREDITO-en-RE0034A.xlsx")
SBP_FIRST_YEAR = 2019          # primer año con reporte RE0034A en la ruta actual (2018/12 → 404)
MEF_BF = "https://www.mef.gob.pa/documentos/balance-fiscal/"

MONTHS = {m: i + 1 for i, m in enumerate(
    ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
     "septiembre", "octubre", "noviembre", "diciembre"])}
MONTHS["setiembre"] = 9
MON3 = {k[:3]: v for k, v in MONTHS.items()}
QUARTERS = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "primer": 1, "segundo": 2, "tercer": 3,
            "cuarto": 4}
NO_DATA = {"", "..", "...", "-", "—", "n.a.", "n.d.", "nd", "…", "*"}


# --------------------------------------------------------------------------- utilidades

def norm(text) -> str:
    """Minúsculas, sin tildes y con espacios simples (para buscar por texto)."""
    s = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return " ".join(s.lower().split())


def to_float(x) -> float | None:
    """Número o None si es marcador de 'sin dato'. Lanza ValueError si es otra cosa."""
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip().replace(",", "")
    if norm(s) in NO_DATA:
        return None
    return float(s)


def year_of(label) -> int | None:
    """2024, 2024.0, '2024 (P)', '2021 (octubre)', '2019-18' → año (el primero)."""
    if isinstance(label, (int, float)) and 1900 < label < 2100:
        return int(label)
    m = re.match(r"^\s*((?:19|20)\d{2})\b", str(label or ""))
    return int(m.group(1)) if m else None


def label_of(r: list) -> object:
    """Rótulo de la fila: primera celda no vacía entre las dos primeras columnas
    (varios cuadros tienen una columna A vacía o celdas combinadas corridas)."""
    return next((c for c in r[:2] if c not in (None, "")), None)


def month_of(label) -> int | None:
    return MONTHS.get(norm(label)) if label is not None else None


def read_book(path: Path) -> dict[str, list[list]]:
    """{hoja: filas} para .xls (xlrd) o .xlsx (openpyxl), valores ya calculados."""
    if path.suffix.lower() == ".xls":
        wb = xlrd.open_workbook(str(path))
        return {sh.name: [sh.row_values(i) for i in range(sh.nrows)] for sh in wb.sheets()}
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    out = {ws.title: [list(r) for r in ws.iter_rows(values_only=True)] for ws in wb.worksheets}
    wb.close()
    return out


def find_sheet(book: dict[str, list[list]], *needles: str, head: int = 15) -> list[list]:
    """Primera hoja cuyas primeras filas contienen TODOS los textos buscados."""
    for name, rows in book.items():
        text = norm(" ".join(str(c) for r in rows[:head] for c in r if c not in (None, "")))
        if all(norm(n) in text for n in needles):
            return rows
    raise ValueError(f"no se encontró una hoja con {needles}")


def find_col(rows: list[list], needle: str, start: int = 0, stop: int | None = None,
             nth: int = 0) -> tuple[int, int]:
    """(fila, columna) de la n-ésima celda que contiene el texto."""
    hits = 0
    for i, r in enumerate(rows[start:stop], start):
        for j, c in enumerate(r):
            if c not in (None, "") and norm(needle) in norm(c):
                if hits == nth:
                    return i, j
                hits += 1
    raise ValueError(f"no se encontró la columna {needle!r}")


def page_links(client: comun.Client, url: str) -> list[tuple[str, str]]:
    """[(url absoluta, texto del enlace)] de una página, en orden de aparición."""
    s = client.get(url).content.decode("utf-8", "replace")
    out = []
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', s, re.S):
        href = html.unescape(m.group(1)).strip()
        text = " ".join(re.sub(r"<[^>]+>", " ", html.unescape(m.group(2))).split())
        out.append((urljoin(url, href), text))
    return out


def pick(links: list[tuple[str, str]], pattern: str) -> str:
    for u, _ in links:
        if re.search(pattern, u.split("/")[-1].split("?")[0], re.I):
            return u
    raise RuntimeError(f"no hay enlace que cumpla {pattern!r}")


def fetch(client: comun.Client, fuente: str, filename: str, url: str) -> str:
    r = client.get(url)
    if len(r.content) < 200 or r.content[:15].lstrip().lower().startswith((b"<!doctype", b"<html")):
        raise RuntimeError(f"{url} no devolvió un archivo de datos")
    action = comun.save_raw(ISO3, fuente, filename, r.content, url)
    log.info("  %-12s %-45s %8d B  [%s]", fuente, filename, len(r.content), action)
    return action


# --------------------------------------------------------------------------- descarga INEC

def inec_avance_year_pages(client: comun.Client) -> dict[int, str]:
    """{año: url} de las páginas 'Principales Indicadores Económicos Mensuales - AAAA'."""
    out = {}
    for u, t in page_links(client, INEC_AVANCE_CAT.format(cat=1)):
        m = re.search(r"Principales Indicadores Econ.micos Mensuales\s*-\s*(\d{4})", t, re.I)
        if m and "ID_CIFRAS" in u:
            out[int(m.group(1))] = u
    return out


def inec_publications(client: comun.Client, cat: int, sub: int) -> list[str]:
    s = client.get(INEC_PUBS.format(cat=cat, sub=sub)).content.decode("utf-8", "replace")
    return list(dict.fromkeys(re.findall(r"Default3\.aspx\?ID_PUBLICACION=(\d+)", s)))


def download_inec(client: comun.Client, redo_history: bool) -> int:
    errors = 0

    def step(desc, fn):
        nonlocal errors
        try:
            fn()
        except (requests.RequestException, RuntimeError, ValueError) as e:
            log.error("INEC %s: %s", desc, e)
            errors += 1

    log.info("INEC")
    # IMAE: cuadro (variaciones) y serie larga en CSV.
    def imae():
        links = page_links(client, INEC_AVANCE.format(cat=1, cifras=49))
        fetch(client, "inec", "imae_cuadro.xlsx", pick(links, r"Cuadro_IMAE.*\.xlsx$"))
        fetch(client, "inec", "imae_serie.csv", pick(links, r"IMAE.*\.csv$"))
    step("IMAE", imae)

    # IPC base 2024: Anexo 4 (índice y variaciones mensual / interanual).
    def ipc():
        links = page_links(client, INEC_AVANCE.format(cat=2, cifras=10))
        fetch(client, "inec", "ipc_anexo4.xlsx", pick(links, r"Anexo\s*4\.xlsx$"))
    step("IPC", ipc)

    # Publicaciones: se toma la más reciente.
    def latest_pub(cat, sub, pattern, filename):
        pub = inec_publications(client, cat, sub)[0]
        links = page_links(client, INEC_PUB.format(pub=pub, cat=cat, sub=sub))
        fetch(client, "inec", filename, pick(links, pattern))
    step("PIB trimestral", lambda: latest_pub(4, 73, r"\.xlsx$", "pib_trimestral.xlsx"))
    step("PIB anual", lambda: latest_pub(4, 26, r"\.xlsx$", "pib_anual.xlsx"))
    step("EML", lambda: latest_pub(5, 38, r"Cuadro\s*2\.xlsx$", "eml_cuadro2.xlsx"))

    # PIEM: una página por año; cada archivo trae el año y el anterior (meses publicados).
    def piem():
        pages = inec_avance_year_pages(client)
        if not pages:
            raise RuntimeError("no se encontraron páginas PIEM")
        recent = sorted(pages)[-2:]
        for year in sorted(pages):
            names = {k: f"piem_{year}_{k}.xls" for k in PIEM_FILES}
            if year not in recent and not redo_history and all(
                    comun.raw_path(ISO3, "inec", n).exists() for n in names.values()):
                continue
            links = page_links(client, pages[year])
            for key, pattern in PIEM_FILES.items():
                try:
                    fetch(client, "inec", names[key], pick(links, pattern))
                except RuntimeError as e:
                    log.warning("  PIEM %d %s: %s", year, key, e)
    step("PIEM", piem)

    # Balanza de pagos: Cuadro 1 (MBP5) de cada publicación; las viejas se bajan una vez.
    def bop():
        pubs = inec_publications(client, 4, 24)
        misses = 0
        for k, pub in enumerate(pubs):
            fn = f"bp_{pub}_cuadro1_mbp5.xlsx"
            if k > 0 and not redo_history and comun.raw_path(ISO3, "inec", fn).exists():
                continue
            links = page_links(client, INEC_PUB.format(pub=pub, cat=4, sub=24))
            try:
                url = pick(links, r"Cuadro\s*1\.?\s*Componentes\s+Normalizados(\s*-\s*MBP5)?\.xlsx$")
            except RuntimeError:
                # Publicaciones anuales intercaladas ('341-01.xlsx') o viejas (antes de 2014,
                # otro formato): se omiten. Tras 4 seguidas sin cuadro se deja de buscar.
                misses += 1
                log.info("  BP %s: sin 'Cuadro 1. Componentes Normalizados' (.xlsx); se omite", pub)
                if misses >= 4:
                    break
                continue
            misses = 0
            fetch(client, "inec", fn, url)
    step("Balanza de pagos", bop)
    return errors


PIEM_FILES = {"valor_fob": r"_valor_fob\.xls$", "valor_cif": r"_valor_cif\.xls$",
              "transporte_acp": r"_transporte_acp\.xls$"}


# --------------------------------------------------------------------------- descarga SBP y MEF

def download_sbp(client: comun.Client, redo_history: bool) -> int:
    errors = 0
    log.info("SBP")
    try:
        home = page_links(client, SBP + "/")
        fetch(client, "sbp", "tasa_interbancaria.xlsx", pick(home, r"^tasas\.xlsx$"))
        links = page_links(client, SBP + "/estadisticas-financieras/tasas-interes")
        fetch(client, "sbp", "tasas_creditos.xlsx", pick(links, r"^Tasas_Creditos\.xlsx$"))
        fetch(client, "sbp", "tasas_depositos.xlsx", pick(links, r"^Tasas_Depositos\.xlsx$"))
    except (requests.RequestException, RuntimeError) as e:
        log.error("SBP tasas: %s", e)
        errors += 1
    # Crédito local por sector: el reporte del último mes + el de diciembre de cada año.
    try:
        links = page_links(client, SBP + "/estadisticas-financieras/cartera-credito")
        url = pick(links, r"RE-CREDITO-en-RE0034A\.xlsx$")
        m = re.search(r"/(\d{4})/(\d{2})/", url)
        last_y, last_m = int(m.group(1)), int(m.group(2))
        fetch(client, "sbp", f"re0034a_{last_y}{last_m:02d}.xlsx", url)
        probe = comun.Client(pause=client.pause, retries=1)
        for y in range(SBP_FIRST_YEAR, last_y):
            fn = f"re0034a_{y}12.xlsx"
            if comun.raw_path(ISO3, "sbp", fn).exists() and not redo_history and y < last_y - 1:
                continue
            try:
                fetch(probe, "sbp", fn, SBP_RE0034A.format(y=y, m=12))
            except requests.HTTPError as e:
                log.warning("  SBP RE0034A %d-12 no disponible (%s)", y, e)
    except (requests.RequestException, RuntimeError, AttributeError) as e:
        log.error("SBP crédito: %s", e)
        errors += 1
    return errors


def download_mef(client: comun.Client) -> int:
    log.info("MEF")
    try:
        links = page_links(client, MEF_BF)
        urls = [u for u, _ in links if re.search(r"\.xlsx$", u.split("?")[0], re.I)
                and not re.search(r"ingl|english|fiscal-balance|[-_]EN[-_.]", u.split("/")[-1], re.I)]
        if not urls:
            raise RuntimeError("no hay archivos de balance fiscal en español")
        for u in dict.fromkeys(urls):
            fetch(client, "mef", "balance_fiscal__" + u.split("/")[-1].split("?")[0], u)
        return 0
    except (requests.RequestException, RuntimeError) as e:
        log.error("MEF: %s", e)
        return 1


# --------------------------------------------------------------------------- parsers INEC

def parse_year_month_block(rows: list[list], value_col: int, start: int,
                           stop_text: str = "variacion") -> dict[pd.Timestamp, float | None]:
    """Filas tipo PIEM: una fila con el año (o '2026 (P)') seguida de filas con meses.

    Se detiene en el primer bloque de variaciones. Los años sin meses debajo (totales
    acumulados) se ignoran porque las filas de meses siempre siguen a su año.
    """
    out, year = {}, None
    for r in rows[start:]:
        label = r[0] if r else None
        if label is not None and stop_text in norm(label):
            break
        y = year_of(label)
        if y:
            year = y
            continue
        mth = month_of(label)
        if mth and year:
            out[pd.Timestamp(year, mth, 1)] = to_float(r[value_col]) if value_col < len(r) else None
    return out


def piem_series(prefix: str, key: str, title: str, col_text: str, nth: int = 0) -> pd.Series:
    """Une los archivos PIEM de todos los años; el archivo más nuevo manda (revisiones)."""
    files = sorted(comun.raw_path(ISO3, "inec", "x").parent.glob(f"{prefix}_*_{key}.xls"),
                   key=lambda p: int(p.name.split("_")[1]))
    if not files:
        raise FileNotFoundError(f"{prefix}_*_{key}.xls")
    data: dict[pd.Timestamp, float] = {}
    for f in files:                                   # de viejo a nuevo: el nuevo sobrescribe
        rows = find_sheet(read_book(f), title)
        hdr, col = find_col(rows, col_text, nth=nth)
        per, _ = find_col(rows, "periodo")
        block = parse_year_month_block(rows, col, max(hdr, per) + 1)
        for k, v in block.items():
            if v is not None:
                data[k] = v
        log.info("  %s: %d meses (%s → %s)", f.name, sum(v is not None for v in block.values()),
                 min(block).date() if block else "-", max(block).date() if block else "-")
    return pd.Series(data).sort_index()


def imae_csv(column: str) -> pd.Series:
    path = comun.raw_path(ISO3, "inec", "imae_serie.csv")
    rows = list(csv.reader(io.StringIO(path.read_bytes().decode("latin-1"))))
    col = [norm(c) for c in rows[0]].index(norm(column))
    out = {}
    for r in rows[1:]:
        if not r or not r[0].strip():
            continue
        m = re.match(r"([a-z]{3})\w*[-/ ](\d{2,4})$", norm(r[0]))
        if not m:
            log.warning("  IMAE csv: fecha no reconocida %r", r[0])
            continue
        y = int(m.group(2))
        y = y + 2000 if y < 100 else y
        try:
            v = to_float(r[col])
        except ValueError:
            log.warning("  IMAE csv %s: valor no numérico %r descartado", r[0], r[col])
            continue
        if v is not None:
            out[pd.Timestamp(y, MON3[m.group(1)], 1)] = v
    return pd.Series(out).sort_index()


def imae_var12m() -> pd.Series:
    rows = find_sheet(read_book(comun.raw_path(ISO3, "inec", "imae_cuadro.xlsx")),
                      "indice mensual de la actividad economica")
    hdr, col = find_col(rows, "interanual")           # la 1.ª es la de la serie original
    out, year = {}, None
    for r in rows[hdr + 1:]:
        y = year_of(r[0]) if r and r[0] is not None else None
        if y:
            year = y
        mth = next((month_of(c) for c in r[:2] if month_of(c)), None)
        if mth and year:
            v = to_float(r[col])
            if v is not None:
                out[pd.Timestamp(year, mth, 1)] = v
    return pd.Series(out).sort_index()


def ipc_anexo4(col_text: str) -> pd.Series:
    rows = find_sheet(read_book(comun.raw_path(ISO3, "inec", "ipc_anexo4.xlsx")),
                      "indice de precios al consumidor nacional urbano")
    if col_text == "indice":
        hdr, col = find_col(rows, "indice de precios", start=6)
    else:
        hdr, col = find_col(rows, col_text, start=6)
    out, year = {}, None
    for r in rows[hdr + 1:]:
        y = year_of(r[0])
        if y:
            year = y                               # fila de año = promedio anual: se omite
            continue
        mth = month_of(r[0])
        if mth and year:
            v = to_float(r[col]) if col < len(r) else None
            if v is not None:
                out[pd.Timestamp(year, mth, 1)] = v
    s = pd.Series(out).sort_index()
    if col_text == "indice" and not s.empty and not 50 < s.iloc[-1] < 200:
        raise ValueError(f"IPC base 2024 fuera de rango: {s.iloc[-1]}")
    return s


def pib_trimestral(cuadro: str, title: str) -> pd.Series:
    book = read_book(comun.raw_path(ISO3, "inec", "pib_trimestral.xlsx"))
    rows = None
    for name, rr in book.items():
        top = [norm(c) for r in rr[:3] for c in r if c not in (None, "")]
        if f"cuadro {cuadro}" in top and norm(title) in " ".join(
                norm(c) for r in rr[:8] for c in r if c not in (None, "")):
            rows = rr
            break
    if rows is None:
        raise ValueError(f"PIB trimestral: no está el Cuadro {cuadro}")
    hdr, _ = find_col(rows, "trimestre")
    col = None
    for r in rows[max(hdr - 2, 0):hdr + 1]:
        for j, c in enumerate(r):
            if c is not None and (norm(c).startswith("pib") or "producto interno bruto" in norm(c)):
                col = j
    if col is None:
        raise ValueError("PIB trimestral: no se encontró la columna del PIB")
    out, year = {}, None
    for r in rows[hdr + 1:]:
        if r[0] is None:
            continue
        if norm(r[0]).startswith("nota"):
            break
        y = year_of(r[0])
        if y:
            year = y
            continue
        q = QUARTERS.get(norm(r[0]))
        if q and year:
            v = to_float(r[col])
            if v is not None:
                out[pd.Timestamp(year, 3 * q - 2, 1)] = v
    return pd.Series(out).sort_index()


def pib_anual_nominal() -> pd.Series:
    # El índice ('Contenido') repite los títulos: se exige también el rótulo de la columna.
    rows = find_sheet(read_book(comun.raw_path(ISO3, "inec", "pib_anual.xlsx")),
                      "principales indicadores macroeconomicos", "pib a precios corrientes")
    hdr, col = find_col(rows, "pib a precios corrientes")
    out = {}
    for r in rows[hdr + 1:]:
        y = year_of(r[0])
        if y:
            v = to_float(r[col])
            if v is not None:
                out[pd.Timestamp(y, 1, 1)] = v
    return pd.Series(out).sort_index()


def eml_desempleo() -> pd.Series:
    rows = find_sheet(read_book(comun.raw_path(ISO3, "inec", "eml_cuadro2.xlsx")),
                      "condicion en la actividad")
    hdr, col = find_col(rows, "porcentaje de la poblacion activa")
    out = {}
    for r in rows[hdr + 1:]:
        lab = label_of(r)
        y = year_of(lab)
        if y:
            v = to_float(r[col])
            if v is not None:
                out[pd.Timestamp(y, 1, 1)] = v
                if "(" in str(lab):
                    log.info("  EML %s: nota en el rótulo del año: %r", y, lab)
    return pd.Series(out).sort_index()


def bop_series(label_regex: str, sub_regex: str | None = None) -> pd.Series:
    """Une los Cuadro 1 (MBP5) de todas las publicaciones; la publicación más nueva manda.

    Con `sub_regex` se toma la subfila ('crédito' / 'débito') que va debajo de la partida.
    """
    folder = comun.raw_path(ISO3, "inec", "x").parent
    files = sorted(folder.glob("bp_*_cuadro1_mbp5.xlsx"), key=lambda p: int(p.name.split("_")[1]))
    if not files:
        raise FileNotFoundError("bp_*_cuadro1_mbp5.xlsx")
    data: dict[pd.Timestamp, float] = {}
    for f in files:                                   # de viejo a nuevo
        try:
            block = parse_bop(f, label_regex, sub_regex)
        except ValueError as e:
            # Publicaciones 2012-2014: otro diseño (solo ene-sep y rótulos 'Primero/Tercero');
            # quedarían años sin el 4.º trimestre, así que no se usan (la serie arranca en 2015).
            log.info("  %s: formato no reconocido (%s); se omite", f.name, e)
            continue
        data.update({k: v for k, v in block.items() if v is not None})
    return pd.Series(data).sort_index()


def bop_goods_debit() -> pd.Series:
    """Bienes, débito (importaciones FOB de balanza de pagos). El Cuadro 1 publica los débitos
    con signo negativo: se cambia el signo para expresarlos como importaciones positivas."""
    s = bop_series(r"^a\.\s*bienes$", r"^debito$")
    if (s > 0).any():
        raise ValueError(f"débitos de bienes con signo positivo en {list(s[s > 0].index[:3])}: "
                         "revisar el signo del Cuadro 1")
    return -s


def parse_bop(path: Path, label_regex: str,
              sub_regex: str | None = None) -> dict[pd.Timestamp, float | None]:
    rows = find_sheet(read_book(path), "componentes normalizados")
    # Fila de años ('2024 (P)', '2025 (P)'...) y la de trimestres ('Primer', 'Segundo'...).
    yrow = next((i for i, r in enumerate(rows[:25]) if sum(1 for c in r[2:] if year_of(c)) >= 2), None)
    if yrow is None:
        raise ValueError("sin fila de años")
    qrow = next((i for i in range(yrow + 1, min(yrow + 4, len(rows)))
                 if sum(1 for c in rows[i] if norm(c or "") in QUARTERS) >= 2), None)
    if qrow is None:
        raise ValueError("sin fila de trimestres")
    years, cur = {}, None
    for j, c in enumerate(rows[yrow]):
        if j >= 2 and year_of(c):
            cur = year_of(c)
        years[j] = cur
    cols = {}
    for j, c in enumerate(rows[qrow]):
        q = QUARTERS.get(norm(c or ""))
        # 'Primer semestre' tiene el mismo texto 'Primer' en la fila siguiente: se descarta.
        below = norm(rows[qrow + 1][j]) if qrow + 1 < len(rows) and j < len(rows[qrow + 1]) and rows[qrow + 1][j] else ""
        if q and years.get(j) and "semestre" not in below:
            cols[j] = pd.Timestamp(years[j], 3 * q - 2, 1)
    if not cols:
        raise ValueError("sin columnas trimestrales")
    def row_label(r: list) -> str:
        # El n.º de línea a veces viene como texto ('1'): el rótulo es la 1.ª celda con letras.
        return norm(next((c for c in r[:3] if isinstance(c, str) and re.search(r"[A-Za-z]", c)), ""))

    for i, r in enumerate(rows[qrow + 1:], qrow + 1):
        if re.search(label_regex, row_label(r)):
            if sub_regex is None:
                return {d: to_float(r[j]) if j < len(r) else None for j, d in cols.items()}
            # Subfila de la partida: solo se miran las filas inmediatas (vacías, 'crédito',
            # 'débito'); si aparece otra partida, la subfila no existe en esta publicación.
            for s in rows[i + 1:i + 5]:
                lab = row_label(s)
                if re.search(sub_regex, lab):
                    return {d: to_float(s[j]) if j < len(s) else None for j, d in cols.items()}
                if lab not in ("", "credito", "debito"):
                    break
            raise ValueError(f"sin subfila {sub_regex!r} bajo {label_regex!r}")
    raise ValueError(f"sin fila {label_regex!r}")


def canal(col_text: str) -> pd.Series:
    return piem_series("piem", "transporte_acp", "autoridad del canal de panama", col_text)


# --------------------------------------------------------------------------- parsers SBP / MEF

def sbp_interbank_monthly() -> pd.Series:
    rows = find_sheet(read_book(comun.raw_path(ISO3, "sbp", "tasa_interbancaria.xlsx")),
                      "tasa de referencia interbancaria", "hasta 1 semana")
    hdr, col = find_col(rows, "1 semana", start=5)
    _, ycol = find_col(rows, "ano", start=hdr, stop=hdr + 1)
    _, mcol = find_col(rows, "mes", start=hdr, stop=hdr + 1)
    vals, zeros, bad = {}, 0, 0
    for r in rows[hdr + 1:]:
        y = year_of(r[ycol]) if ycol < len(r) else None
        mth = month_of(r[mcol]) if mcol < len(r) else None
        if not (y and mth):
            continue
        try:
            v = to_float(r[col])
        except ValueError:
            bad += 1
            log.warning("  SBP interbancaria %s %s: valor no numérico %r descartado", y, r[mcol], r[col])
            continue
        if v is None:
            continue
        if v == 0:                       # 0 = semana sin operaciones en ese plazo (sin dato)
            zeros += 1
            continue
        vals.setdefault(pd.Timestamp(y, mth, 1), []).append(v)
    log.info("  SBP interbancaria 1 semana: %d semanas en 0 (sin operaciones) descartadas", zeros)
    return pd.Series({k: sum(v) / len(v) for k, v in vals.items()}).sort_index()


def sbp_rate(filename: str, sheet_title: str, col_text: str) -> pd.Series:
    book = read_book(comun.raw_path(ISO3, "sbp", filename))
    rows = book.get(sheet_title) or find_sheet(book, sheet_title)
    frow, _ = find_col(rows, "fecha")
    hdr, col = find_col(rows, col_text, start=frow, stop=frow + 1)
    out, nd = {}, 0
    for r in rows[hdr + 1:]:
        d = r[0]
        if not isinstance(d, (dt.datetime, dt.date)):
            continue
        v = to_float(r[col]) if col < len(r) else None
        if v is None:
            nd += 1
            continue
        out[pd.Timestamp(d.year, d.month, 1)] = v
    if nd:
        log.info("  SBP %s %s: %d meses N.D. descartados", filename, col_text, nd)
    return pd.Series(out).sort_index()


def sbp_credit_private() -> pd.Series:
    folder = comun.raw_path(ISO3, "sbp", "x").parent
    files = sorted(folder.glob("re0034a_*.xlsx"), key=lambda p: p.stem.split("_")[1])
    if not files:
        raise FileNotFoundError("re0034a_*.xlsx")
    data, zeros = {}, 0
    for f in files:                                  # de viejo a nuevo
        rows = find_sheet(read_book(f), "saldos de creditos locales")
        mrow = next(i for i, r in enumerate(rows[:20])
                    if sum(1 for c in r if month_of(c)) >= 6)
        yrow = mrow - 1
        years, cur = {}, None
        for j, c in enumerate(rows[yrow]):
            cur = year_of(c) or cur
            years[j] = cur
        target = next(r for r in rows[mrow + 1:] if r and norm(r[0] or "") == "sector privado")
        block = {}
        for j, c in enumerate(rows[mrow]):
            mth = month_of(c)
            if mth and years.get(j) and j < len(target):
                v = to_float(target[j])
                if v is None or v == 0:          # meses aún no publicados vienen en 0
                    zeros += v == 0
                    continue
                block[pd.Timestamp(years[j], mth, 1)] = v
        # Trampa: el título dice 'En Millones de Balboas', pero desde 2025-26 los valores
        # vienen en balboas. Se detecta por magnitud (el crédito privado es ~50-70 mil millones).
        scale = 1e-6 if max(block.values()) > 1e7 else 1.0
        data.update({k: v * scale for k, v in block.items()})
        log.info("  %s: %d meses%s", f.name, len(block), " (en balboas → millones)" if scale != 1 else "")
    log.info("  SBP crédito: %d celdas en 0 (meses futuros) descartadas", zeros)
    return pd.Series(data).sort_index()


def mef_file_balance(f: Path) -> dict[pd.Timestamp, float]:
    """{año: balance total SPNF % PIB} si el archivo es de cierre (diciembre vs diciembre)."""
    try:
        rows = find_sheet(read_book(f), "sector publico no financiero")
    except ValueError:
        return {}
    prow, _ = find_col(rows, "detalle")
    months = [norm(c) for c in rows[prow - 1] if c is not None and norm(c)]
    yrs = [(j, year_of(c)) for j, c in enumerate(rows[prow]) if year_of(c)]
    if len(yrs) < 2 or months[:2] != ["diciembre", "diciembre"]:
        return {}                                     # no es cierre de año
    brow, _ = find_col(rows, "balance total")
    pct = rows[brow + 1]
    if "pib" not in norm(next((c for c in pct if isinstance(c, str)), "")):
        raise ValueError("no hay fila '% del PIB' bajo 'Balance Total'")
    gdp_row, _ = find_col(rows, "pib nominal")
    out = {}
    for j, y in yrs[:2]:
        frac = to_float(pct[j])
        bal, gdp = to_float(rows[brow][j]), to_float(rows[gdp_row][j])
        if frac is None:
            continue
        # Validación interna: % publicado vs balance / PIB del mismo cuadro.
        if bal and gdp and abs(100 * frac - 100 * bal / gdp) > 0.15:
            log.warning("  MEF %s %d: %% PIB publicado %.2f vs calculado %.2f",
                        f.name, y, 100 * frac, 100 * bal / gdp)
        out[pd.Timestamp(y, 1, 1)] = 100 * frac       # la celda es una fracción (formato %)
    return out


def mef_fiscal_balance() -> pd.Series:
    """Balance total del SPNF en % del PIB, de los archivos de cierre (diciembre vs diciembre)."""
    folder = comun.raw_path(ISO3, "mef", "x").parent
    files = sorted(folder.glob("balance_fiscal__*.xlsx"))
    found = []                                        # (año más reciente del archivo, {fecha: valor})
    for f in files:
        try:
            block = mef_file_balance(f)
        except ValueError as e:
            log.warning("  MEF %s: %s (se omite)", f.name, e)
            continue
        if block:
            found.append((max(block).year, block))
            log.info("  %s: cierre %s", f.name, sorted(d.year for d in block))
    data = {}
    for _, block in sorted(found, key=lambda t: t[0]):   # el cierre más nuevo manda (revisiones)
        data.update(block)
    if not data:
        raise ValueError("ningún archivo del MEF es de cierre de año")
    return pd.Series(data).sort_index()


# --------------------------------------------------------------------------- registro de series

BUILDERS = {
    "pbi_real_trim": lambda: pib_trimestral("1", "medidas de volumen encadenadas"),
    "pbi_real_var12m_trim": lambda: pib_trimestral("1.a", "medidas de volumen encadenadas"),
    "pbi_nominal_trim": lambda: pib_trimestral("5", "trimestral corriente"),
    "actividad_mensual_indice": lambda: imae_csv("serie original"),
    "imae_tendencia_ciclo": lambda: imae_csv("tendencia ciclo"),
    "actividad_mensual_var12m": imae_var12m,
    "pbi_nominal_anual": pib_anual_nominal,
    "ipc_indice": lambda: ipc_anexo4("indice"),
    "inflacion_mensual": lambda: ipc_anexo4("mensual"),
    "inflacion_12m": lambda: ipc_anexo4("interanual"),
    "tasa_interbancaria": sbp_interbank_monthly,
    "credito_privado": sbp_credit_private,
    "exportaciones": lambda: piem_series("piem", "valor_fob", "valor fob de las exportaciones", "total") / 1e3,
    "importaciones": lambda: piem_series("piem", "valor_cif", "valor cif de las importaciones", "total") / 1e3,
    "balanza_comercial": lambda: bop_series(r"^a\.\s*bienes$"),
    "cuenta_corriente": lambda: bop_series(r"^i\.\s*cuenta corriente$"),
    # Bienes de balanza de pagos (incluyen la Zona Libre de Colón y las zonas francas).
    "exportaciones_bienes_bp": lambda: bop_series(r"^a\.\s*bienes$", r"^credito$"),
    "importaciones_bienes_bp": bop_goods_debit,
    "resultado_fiscal_pct_pbi": mef_fiscal_balance,
    "desempleo": eml_desempleo,
    # 'Tránsito de naves' (hasta 2024) o 'Tránsito de buques' (desde 2025): la 1.ª es la del TOTAL.
    "canal_transitos": lambda: canal("transito de"),
    "canal_ingresos_peaje": lambda: canal("ingresos por peaje") / 1e3,   # 'peaje' o 'peajes' según el año
    "tasa_prestamo_personal": lambda: sbp_rate("tasas_creditos.xlsx", "CONSUMO", "prestamo personal"),
    "tasa_credito_comercio_mayor": lambda: sbp_rate("tasas_creditos.xlsx", "COMERCIO", "al por mayor"),
    "tasa_dpf_1_anio": lambda: sbp_rate("tasas_depositos.xlsx", "DEPOSITOS A PLAZO FIJO", "1 ano"),
    "tasa_ahorro": lambda: sbp_rate("tasas_depositos.xlsx", "AHORRO CORRIENTE", "ahorro"),
}


def process(rows: list[dict]) -> int:
    frames, errors = [], 0
    for row in rows:
        name = row["nombre_corto"]
        try:
            if name not in BUILDERS:
                raise ValueError("sin parser en pan.py (BUILDERS)")
            s = BUILDERS[name]().dropna()
        except (FileNotFoundError, ValueError, RuntimeError, KeyError, StopIteration) as e:
            log.error("%s: no se pudo procesar (%s)", name, e)
            errors += 1
            continue
        if s.empty:
            log.error("%s: sin observaciones", name)
            errors += 1
            continue
        df = pd.DataFrame({"fecha": comun.period_start(pd.Series(s.index), row["frecuencia"]),
                           "valor": s.values})
        for col in ("fuente", "codigo_fuente", "nombre_corto", "frecuencia", "unidad"):
            df[col] = row[col]
        df["indicador_comun"] = row["indicador_comun"]
        df["pais"] = ISO3
        frames.append(df)
    if not frames:
        return errors + 1
    comun.write_interim(ISO3, pd.concat(frames, ignore_index=True))
    return errors


# --------------------------------------------------------------------------- CLI

SOURCE_OF = {"inec": download_inec, "sbp": download_sbp, "mef": download_mef}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--solo-procesar", action="store_true",
                    help="no descarga; reconstruye el parquet desde data/raw/PAN")
    ap.add_argument("--serie", nargs="+", metavar="NOMBRE_CORTO",
                    help="descargar solo las fuentes de estas series (el parquet se rehace con todas)")
    ap.add_argument("--pausa", type=float, default=1.0, help="segundos entre peticiones (mín. 1)")
    ap.add_argument("--rehacer-historico", action="store_true",
                    help="volver a bajar también las publicaciones históricas ya guardadas")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):          # consola cp1252 vs '→' del log de comun
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    comun.setup_logging(ISO3)

    rows = comun.load_series(ISO3)
    errors = 0
    if not args.solo_procesar:
        wanted = rows
        if args.serie:
            wanted = [r for r in rows if r["nombre_corto"] in args.serie]
            missing = set(args.serie) - {r["nombre_corto"] for r in wanted}
            if missing:
                log.warning("No están activas en config/series/PAN.csv: %s", ", ".join(sorted(missing)))
        client = comun.Client(pause=max(args.pausa, 1.0))
        for fuente in dict.fromkeys(r["fuente"] for r in wanted):
            fn = SOURCE_OF[fuente]
            errors += fn(client) if fuente == "mef" else fn(client, args.rehacer_historico)
    errors += process(rows)
    log.info("Fin PAN: %d errores", errors)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
