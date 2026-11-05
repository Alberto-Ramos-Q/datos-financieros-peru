"""Descargador de series macroeconómicas de Estados Unidos (solo fuentes oficiales).

Fuentes (ver docs/fuentes/USA.md):
    fed       Federal Reserve Board: Data Download Program (H.15, H.10, H.8, H.6, G.17)
              y la tabla de decisiones del FOMC (Open Market Operations).
    bls       Bureau of Labor Statistics: API pública v1 (sin clave; IPC y empleo).
    bea       Bureau of Economic Analysis: archivos planos de NIPA (PBI) y tablas
              interactivas ITA/IIP (cuenta corriente, reservas).
    census    Census Bureau: historia del FT-900 (comercio de bienes, base BoP).
    omb       Office of Management and Budget: Historical Tables 1.2 y 7.1 (fiscal).
    nyfed     Federal Reserve Bank of New York: Survey of Consumer Expectations.
    treasury  U.S. Treasury, Fiscal Data API: Debt to the Penny.

Dos pasos:
    1. descargar: guarda cada respuesta tal cual en data/raw/USA/<fuente>/.
    2. procesar: lee SOLO data/raw/USA/ y escribe data/interim/USA_observaciones.parquet.

Uso:
    python usa.py                          # descarga todo y procesa
    python usa.py --serie tasa_politica m2 # descarga solo esas series (procesa todas)
    python usa.py --solo-procesar          # no usa la red
    python usa.py --pausa 2                # segundos entre peticiones
    python usa.py --serie desempleo_nsa --bls-desde 1948   # BLS solo desde el bloque 1943-1952

`codigo_fuente` admite un sufijo de transformación tras «|», aplicado al procesar:
    var1m   variación % respecto al mes anterior
    var12m  variación % respecto al mismo mes del año anterior
    x<f>    multiplica por f (p. ej. x1000: miles de millones → millones)

BLS: sin clave se usa la API v1 (10 años por petición, 25 peticiones por día y por IP;
una corrida completa hace 12). Si existe la variable de entorno BLS_API_KEY se usa la v2.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import html
import io
import json
import os
import re
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import comun  # noqa: E402

ISO3 = "USA"
log = comun.log

# --- Federal Reserve Board -------------------------------------------------------------
DDP_URL = "https://www.federalreserve.gov/datadownload/Output.aspx"
FOMC_PAGES = {
    "openmarket.htm": "https://www.federalreserve.gov/monetarypolicy/openmarket.htm",
    "openmarket_archive.htm": "https://www.federalreserve.gov/monetarypolicy/openmarket_archive.htm",
}

# --- BLS -------------------------------------------------------------------------------
BLS_V1_URL = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
BLS_V2_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
BLS_FIRST_YEAR = 1913      # inicio del IPC; los bloques de 10 años son fijos (1913-1922, ...)
BLS_CHUNK_YEARS = 10       # límite de la API v1

# --- BEA -------------------------------------------------------------------------------
BEA_FLAT_URL = "https://apps.bea.gov/national/Release/TXT/{name}"
BEA_FLAT = {"trimestral": "NipaDataQ.txt", "anual": "NipaDataA.txt"}
BEA_ITABLE_URL = "https://apps.bea.gov/iTable/core/data/app/GetSteps"
# Tablas interactivas de transacciones internacionales (appid 62). Se pide la tabla
# completa (todas las líneas y años) y se elige la línea por número y rótulo.
BEA_ITABLES = {
    "ITA T1.1 L30": {"product": "1", "table": "1", "freq": "1", "line": "30",
                     "label": "Balance on current account", "file": "ita_t1_1_qsa.json"},
    "IIP T1.1 L11": {"product": "5", "table": "143", "freq": "1", "line": "11",
                     "label": "Reserve assets", "file": "iip_t1_1_qnsa.json"},
}

# --- Census ----------------------------------------------------------------------------
CENSUS_URL = "https://www.census.gov/foreign-trade/statistics/historical/exhibit_history.xlsx"
# Columnas de la hoja exhibit_history: Periodo | Balance (Total, Goods, Services) |
# Exports (Total, Goods, Services) | Imports (Total, Goods, Services)
CENSUS_COLS = {
    "FT900 exhibit_history: Balance Total": 1, "FT900 exhibit_history: Balance Goods": 2,
    "FT900 exhibit_history: Exports Goods": 5, "FT900 exhibit_history: Imports Goods": 8,
}
MONTHS_EN = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"])}

# --- OMB -------------------------------------------------------------------------------
OMB_PAGE = "https://www.whitehouse.gov/omb/information-resources/budget/historical-tables/"
OMB_TABLES = {   # codigo_fuente → (archivo, columna con el % del PBI)
    "hist01z2: Total Surplus or Deficit (-)": ("hist01z2", 4),
    "hist07z1: Gross Federal Debt % GDP": ("hist07z1", 6),
    "hist07z1: Debt Held by the Public % GDP": ("hist07z1", 8),
}
# Rótulos que deben aparecer en la cabecera (filas 1-3) de la columna, para detectar si OMB
# reordena las columnas de la tabla 7.1 (bloque «As Percentages of GDP»).
OMB_HEADER_CHECK = {
    "hist07z1: Debt Held by the Public % GDP": ("percentages of gdp", "held by the public", "total"),
}

# --- NY Fed y Tesoro -------------------------------------------------------------------
NYFED_URL = ("https://www.newyorkfed.org/medialibrary/interactives/sce/sce/downloads/"
             "data/frbny-sce-data.xlsx")
TREASURY_URL = ("https://api.fiscaldata.treasury.gov/services/api/fiscal_service/"
                "v2/accounting/od/debt_to_penny")


# =======================================================================================
# Utilidades
# =======================================================================================
def split_code(codigo: str) -> tuple[str, str]:
    """'CUUR0000SA0|var12m' → ('CUUR0000SA0', 'var12m')."""
    base, _, op = codigo.partition("|")
    return base.strip(), op.strip()


def safe_name(code: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", code)


def save(fuente: str, filename: str, content: bytes, url: str) -> None:
    action = comun.save_raw(ISO3, fuente, filename, content, url)
    log.info("  %-10s %-45s %9d bytes  [%s]", fuente, filename, len(content), action)


def raw_file(fuente: str, filename: str) -> Path:
    return comun.raw_path(ISO3, fuente, filename)


def to_float(value) -> float | None:
    """Número o None (marcadores de 'sin dato': ND, -, (D), ..., vacío)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return None if pd.isna(value) else float(value)
    text = str(value).strip().replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


# =======================================================================================
# Paso 1: descarga
# =======================================================================================
def download_fed_ddp(client: comun.Client, code: str) -> None:
    """Una serie del Data Download Program. El parámetro `series` del DDP es el md5 del
    «Unique Identifier» (p. ej. md5('H15/H15/RIFSPFF_N.M'))."""
    rel = code.split("/")[0]
    params = {"rel": rel, "series": hashlib.md5(code.encode()).hexdigest(), "lastobs": "",
              "from": "", "to": "", "filetype": "csv", "label": "include",
              "layout": "seriescolumn", "type": "package"}
    # El DDP a veces responde 200 con cuerpo vacío (parece un límite de frecuencia):
    # se reintenta con espera creciente.
    for attempt in range(1, 5):
        r = client.get(DDP_URL, params=params)
        if f'"Unique Identifier: ","{code}"'.encode() in r.content:
            save("fed", safe_name(code) + ".csv", r.content, r.url)
            return
        log.warning("DDP %s: respuesta sin la serie (intento %d, %d bytes); espero %d s",
                    code, attempt, len(r.content), 10 * attempt)
        time.sleep(10 * attempt)
    raise RuntimeError(f"DDP no devolvió {code}")


def download_fomc(client: comun.Client) -> None:
    for name, url in FOMC_PAGES.items():
        r = client.get(url)
        if b"Level (%)" not in r.content:
            raise RuntimeError(f"{url}: no se encontró la tabla de decisiones del FOMC")
        save("fed", name, r.content, url)


def download_bls(client: comun.Client, codes: list[str], from_year: int | None = None) -> None:
    """IPC y empleo por bloques fijos de 10 años con todas las series BLS juntas.

    `from_year` salta los bloques que terminan antes de ese año (para ahorrar cuota cuando
    se agrega una serie que empieza tarde, p. ej. 1948): esos archivos quedan como estaban.
    """
    key = os.environ.get("BLS_API_KEY", "").strip()
    url = BLS_V2_URL if key else BLS_V1_URL
    starts = [s for s in range(BLS_FIRST_YEAR, dt.date.today().year + 1, BLS_CHUNK_YEARS)
              if from_year is None or s + BLS_CHUNK_YEARS - 1 >= from_year]
    if not key:
        log.info("  BLS: API v1 sin clave (límite 25 peticiones/día; esta corrida usa %d)",
                 len(starts))
    for start in starts:
        end = start + BLS_CHUNK_YEARS - 1
        body = {"seriesid": codes, "startyear": str(start),
                "endyear": str(min(end, dt.date.today().year))}
        if key:
            body["registrationkey"] = key
        r = client.post(url, json=body)
        payload = r.json()
        if payload.get("status") != "REQUEST_SUCCEEDED":
            raise RuntimeError(f"BLS {start}-{end}: {payload.get('status')} {payload.get('message')}")
        # La clave nunca se guarda: el archivo crudo es la respuesta, no la petición.
        save("bls", f"bls_{start}_{end}.json", r.content, url)


def download_bea_flat(client: comun.Client, freqs: set[str]) -> None:
    """Archivos planos de NIPA (~35 MB el trimestral). Se guardan comprimidos con gzip
    (sin pérdida, mtime=0 para que el sha256 no cambie si el contenido no cambia)."""
    for freq in sorted(freqs):
        name = BEA_FLAT[freq]
        url = BEA_FLAT_URL.format(name=name)
        r = client.get(url, timeout=600)
        if not r.content.startswith(b"%SeriesCode"):
            raise RuntimeError(f"{url}: formato inesperado")
        save("bea", name + ".gz", gzip.compress(r.content, compresslevel=9, mtime=0), url)


def download_bea_itable(client: comun.Client, code: str) -> None:
    t = BEA_ITABLES[code]
    body = {"appid": 62, "steps": [1, 2, 6],
            "data": [["Product", t["product"]], ["TableList", t["table"]],
                     ["Filter_#1", "0"],            # todos los años
                     ["Filter_#2", t["freq"]],      # 1 = trimestral (SA en ITA, NSA en IIP)
                     ["Filter_#3", "0"],            # todas las líneas
                     ["Filter_#4", "0"], ["Filter_#5", "0"]]}
    r = client.post(BEA_ITABLE_URL, json=body, timeout=300)
    payload = r.json()
    if not any(s.get("Number") == 6 for s in payload.get("Steps", [])):
        raise RuntimeError(f"BEA iTable {code}: la respuesta no trae la tabla")
    save("bea", t["file"], r.content, BEA_ITABLE_URL + " " + json.dumps(body))


def download_omb(client: comun.Client, names: set[str]) -> None:
    """La URL de cada tabla cambia con cada presupuesto: se busca en la página índice."""
    page = client.get(OMB_PAGE).text
    for name in sorted(names):
        links = re.findall(rf'href="([^"]*/{name}_fy\d{{4}}\.xlsx)"', page)
        if not links:
            raise RuntimeError(f"OMB: no se encontró el enlace a {name}")
        url = links[0]
        r = client.get(url)
        save("omb", f"{name}.xlsx", r.content, url)


def download_treasury(client: comun.Client) -> None:
    page, pages = 1, 1
    while page <= pages:
        params = {"fields": "record_date,tot_pub_debt_out_amt", "sort": "record_date",
                  "page[size]": "10000", "page[number]": str(page)}
        r = client.get(TREASURY_URL, params=params)
        pages = r.json()["meta"]["total-pages"]
        save("treasury", f"debt_to_penny_p{page}.json", r.content, r.url)
        page += 1


def download(series: list[dict], pause: float, bls_from: int | None = None) -> int:
    client = comun.Client(pause=pause)
    errors = 0
    by_source: dict[str, list[dict]] = {}
    for s in series:
        by_source.setdefault(s["fuente"], []).append(s)

    def run(label: str, fn, *args) -> None:
        nonlocal errors
        try:
            fn(*args)
        except Exception as e:  # noqa: BLE001 — se registra y se sigue con la siguiente fuente
            errors += 1
            log.error("%s: %s", label, e)

    for s in by_source.get("fed", []):
        code, _ = split_code(s["codigo_fuente"])
        if code == "fomc_target_upper":
            run("FOMC", download_fomc, client)
        else:
            run(code, download_fed_ddp, client, code)

    if "bls" in by_source:
        # Siempre todas las series BLS activas: los archivos por bloque las contienen a todas.
        all_bls = sorted({split_code(s["codigo_fuente"])[0]
                          for s in comun.load_series(ISO3) if s["fuente"] == "bls"})
        run("BLS", download_bls, client, all_bls, bls_from)

    bea = by_source.get("bea", [])
    flat_freqs = {s["frecuencia"] for s in bea if split_code(s["codigo_fuente"])[0] not in BEA_ITABLES}
    if flat_freqs:
        run("BEA NIPA", download_bea_flat, client, flat_freqs)
    for code in sorted({split_code(s["codigo_fuente"])[0] for s in bea} & set(BEA_ITABLES)):
        run(code, download_bea_itable, client, code)

    if "census" in by_source:
        run("Census", lambda: save("census", "exhibit_history.xlsx",
                                   client.get(CENSUS_URL).content, CENSUS_URL))
    if "omb" in by_source:
        names = {OMB_TABLES[split_code(s["codigo_fuente"])[0]][0] for s in by_source["omb"]}
        run("OMB", download_omb, client, names)
    if "nyfed" in by_source:
        run("NY Fed", lambda: save("nyfed", "frbny-sce-data.xlsx",
                                   client.get(NYFED_URL).content, NYFED_URL))
    if "treasury" in by_source:
        run("Treasury", download_treasury, client)
    return errors


# =======================================================================================
# Paso 2: procesamiento (solo lee data/raw/USA)
# =======================================================================================
class Dropped:
    """Lleva la cuenta de valores no numéricos descartados (no se imputan)."""

    def __init__(self) -> None:
        self.items: dict[str, list[str]] = {}

    def add(self, code: str, period: str, value) -> None:
        self.items.setdefault(code, []).append(f"{period}={value!r}")

    def report(self) -> None:
        for code, items in self.items.items():
            log.info("  descartados (sin dato) %s: %d, p. ej. %s", code, len(items),
                     ", ".join(items[:4]))


def frame(records: list[tuple], code: str) -> pd.DataFrame:
    df = pd.DataFrame(records, columns=["fecha", "valor"])
    if df.empty:
        raise ValueError(f"{code}: sin observaciones")
    df["fecha"] = pd.to_datetime(df["fecha"])
    return df


def read_fed_ddp(code: str, dropped: Dropped) -> pd.DataFrame:
    path = raw_file("fed", safe_name(code) + ".csv")
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith('"Time Period"')) + 1
    recs = []
    for ln in lines[start:]:
        if not ln.strip():
            continue
        period, value = ln.split(",", 1)
        v = to_float(value)
        if v is None:
            dropped.add(code, period, value)
            continue
        recs.append((period, v))      # 'AAAA-MM' o 'AAAA-MM-DD'
    return frame(recs, code)


def read_fomc(dropped: Dropped) -> pd.DataFrame:
    """Decisiones del FOMC → límite superior vigente a fin de cada mes.

    Las fechas de la tabla son las de entrada en vigor (p. ej. el recorte decidido el
    31-jul-2019 figura como 1-ago). El nivel es un rango ('4.25-4.50') o, hasta 2008,
    un objetivo puntual ('5.25'). Se toma el límite superior.
    """
    changes = []
    for name in FOMC_PAGES:
        text = raw_file("fed", name).read_text(encoding="utf-8", errors="replace")
        year = None
        for y, row in re.findall(r"<h4>\s*(\d{4})\s*</h4>|<tr[^>]*>(.*?)</tr>", text, re.S):
            if y:
                year = int(y)
                continue
            cells = [" ".join(html.unescape(re.sub(r"<[^>]+>", " ", c)).split())
                     for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
            if len(cells) != 4 or year is None:
                continue
            date_txt = re.sub(r"[^A-Za-z0-9 ]", "", cells[0]).strip()   # quita el '*' de notas
            upper = to_float(cells[3].split("-")[-1])
            try:
                when = dt.datetime.strptime(f"{date_txt} {year}", "%B %d %Y").date()
            except ValueError:
                dropped.add("fomc_target_upper", f"{year} {cells[0]}", cells[3])
                continue
            if upper is None:
                dropped.add("fomc_target_upper", str(when), cells[3])
                continue
            changes.append((pd.Timestamp(when), upper))
    if not changes:
        raise ValueError("FOMC: no se encontraron decisiones")
    steps = pd.Series(dict(changes)).sort_index()
    # Último nivel vigente en cada fin de mes, desde el mes del primer cambio hasta hoy.
    months = pd.period_range(steps.index.min(), pd.Timestamp.today(), freq="M")
    month_ends = months.to_timestamp(how="end").normalize()
    values = steps.reindex(steps.index.union(month_ends)).ffill().loc[month_ends]
    return pd.DataFrame({"fecha": months.to_timestamp(), "valor": values.to_numpy()})


_bls_cache: dict[str, list[tuple]] | None = None


def read_bls(code: str, dropped: Dropped) -> pd.DataFrame:
    global _bls_cache
    if _bls_cache is None:
        _bls_cache = {}
        for path in sorted(raw_file("bls", "x").parent.glob("bls_*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            for s in payload["Results"]["series"]:
                recs = _bls_cache.setdefault(s["seriesID"], [])
                for d in s["data"]:
                    if not re.fullmatch(r"M(0[1-9]|1[0-2])", d["period"]):
                        continue          # M13 = promedio anual
                    period = f"{d['year']}-{d['period'][1:]}"
                    v = to_float(d["value"])
                    if v is None:         # p. ej. '-' en oct-2025 (cierre del gobierno)
                        dropped.add(s["seriesID"], period, d["value"])
                        continue
                    recs.append((period, v))
    if code not in _bls_cache:
        raise ValueError(f"{code}: no está en los archivos de BLS (¿falta descargar?)")
    return frame(_bls_cache[code], code).drop_duplicates("fecha", keep="last")


_bea_flat_cache: dict[str, pd.DataFrame] = {}


def read_bea_flat(code: str, frecuencia: str, dropped: Dropped) -> pd.DataFrame:
    name = BEA_FLAT[frecuencia]
    if name not in _bea_flat_cache:
        raw = gzip.decompress(raw_file("bea", name + ".gz").read_bytes())
        _bea_flat_cache[name] = pd.read_csv(io.BytesIO(raw), dtype=str)
    df = _bea_flat_cache[name]
    sub = df[df["%SeriesCode"] == code]
    recs = []
    for period, value in zip(sub["Period"], sub["Value"]):
        v = to_float(value)
        if v is None:
            dropped.add(code, period, value)
            continue
        if frecuencia == "trimestral":               # '1947Q1'
            year, q = period.split("Q")
            fecha = dt.date(int(year), 3 * int(q) - 2, 1)
        else:                                       # '1929'
            fecha = dt.date(int(period), 1, 1)
        recs.append((fecha, v))
    return frame(recs, code)


def read_bea_itable(code: str, dropped: Dropped) -> pd.DataFrame:
    t = BEA_ITABLES[code]
    payload = json.loads(raw_file("bea", t["file"]).read_text(encoding="utf-8"))
    step = next(s for s in payload["Steps"] if s["Number"] == 6)
    prompt = next(p for p in step["Prompts"] if p["UIControl"] == "Table")
    table = json.loads(json.loads(prompt["PromtData"])["Table"])
    cells: dict[tuple[int, int], str] = {}
    for c in table["TD"]:
        clean = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", c["Cell_Value"]))
                         .replace(" ", " ").replace("�", " ").split())
        cells[(int(c["Row_ID"]), int(c["Column_ID"]))] = clean
    n_rows, n_cols = int(table["Number_Of_Rows"]), int(table["Number_Of_Columns"])
    n_head = int(table["Number_Of_Header_Rows"])
    # Fila del rótulo: columna 1 = número de línea, columna 2 = descripción.
    row = next((r for r in range(n_head + 1, n_rows + n_head + 1)
                if cells.get((r, 1)) == t["line"]), None)
    if row is None or not cells.get((row, 2), "").startswith(t["label"]):
        raise ValueError(f"{code}: la línea {t['line']} ya no es «{t['label']}» "
                         f"(encontrado: {cells.get((row, 2)) if row else None})")
    recs = []
    for col in range(3, n_cols + 1):
        year, quarter = cells.get((n_head - 1, col), ""), cells.get((n_head, col), "")
        m = re.match(r"(\d{4})", year)
        q = re.match(r"Q([1-4])", quarter)
        if not (m and q):
            continue
        value = cells.get((row, col))
        v = to_float(value)
        if v is None:
            dropped.add(code, f"{m.group(1)}Q{q.group(1)}", value)
            continue
        recs.append((dt.date(int(m.group(1)), 3 * int(q.group(1)) - 2, 1), v))
    return frame(recs, code)


def read_census(code: str, dropped: Dropped) -> pd.DataFrame:
    df = pd.read_excel(raw_file("census", "exhibit_history.xlsx"), header=None)
    col = CENSUS_COLS[code]
    year, recs = None, []
    for label, value in zip(df[0], df[col]):
        label = str(label).strip()
        if re.fullmatch(r"\d{4}", label):
            year = int(label)
            continue
        month = MONTHS_EN.get(label.lower())
        if month is None or year is None:
            continue                        # 'Jan. - Dec.', títulos y notas
        v = to_float(value)
        if v is None:                       # meses futuros del año en curso (vacíos)
            if not pd.isna(value):
                dropped.add(code, f"{year}-{month:02d}", value)
            continue
        recs.append((dt.date(year, month, 1), v))
    return frame(recs, code)


def read_omb(code: str, dropped: Dropped) -> pd.DataFrame:
    name, col = OMB_TABLES[code]
    df = pd.read_excel(raw_file("omb", f"{name}.xlsx"), header=None)
    if code in OMB_HEADER_CHECK:
        # La fila 1 tiene el bloque en celda combinada (solo en la 1.ª columna): se arrastra.
        block = df.iloc[1, :col + 1].ffill().iloc[-1]
        header = " ".join(str(x) for x in (block, df.iloc[2, col], df.iloc[3, col])
                          if not pd.isna(x)).lower()
        header = " ".join(header.split())
        if not all(t in header for t in OMB_HEADER_CHECK[code]):
            raise ValueError(f"{code}: la columna {col} de {name} ya no es la esperada ({header!r})")
    recs = []
    for label, value in zip(df[0], df[col]):
        label = str(label).strip()
        if not re.fullmatch(r"\d{4}", label):
            continue          # títulos, 'TQ' (trimestre de transición de 1976), estimaciones, notas
        v = to_float(value)
        if v is None:
            dropped.add(code, label, value)
            continue
        recs.append((dt.date(int(label), 1, 1), v))
    return frame(recs, code)


def read_nyfed(code: str, dropped: Dropped) -> pd.DataFrame:
    column = code.split(":", 1)[1].strip()
    df = pd.read_excel(raw_file("nyfed", "frbny-sce-data.xlsx"),
                       sheet_name="Inflation expectations", header=None)
    header_row = next(i for i in range(10) if column in [str(x).strip() for x in df.iloc[i]])
    col = [str(x).strip() for x in df.iloc[header_row]].index(column)
    recs = []
    for period, value in zip(df.iloc[header_row + 1:, 0], df.iloc[header_row + 1:, col]):
        if not re.fullmatch(r"\d{6}", str(period).strip()):
            continue
        v = to_float(value)
        if v is None:
            dropped.add(code, period, value)
            continue
        p = str(period).strip()
        recs.append((dt.date(int(p[:4]), int(p[4:]), 1), v))
    return frame(recs, code)


def read_treasury(code: str, dropped: Dropped) -> pd.DataFrame:
    field = code.split(":", 1)[1].strip()
    recs = []
    for path in sorted(raw_file("treasury", "x").parent.glob("debt_to_penny_p*.json")):
        for d in json.loads(path.read_text(encoding="utf-8"))["data"]:
            v = to_float(d[field])
            if v is None:
                dropped.add(code, d["record_date"], d[field])
                continue
            recs.append((d["record_date"], v))
    return frame(recs, code).drop_duplicates("fecha", keep="last")


def read_base(s: dict, code: str, dropped: Dropped) -> pd.DataFrame:
    fuente = s["fuente"]
    if fuente == "fed":
        return read_fomc(dropped) if code == "fomc_target_upper" else read_fed_ddp(code, dropped)
    if fuente == "bls":
        return read_bls(code, dropped)
    if fuente == "bea":
        if code in BEA_ITABLES:
            return read_bea_itable(code, dropped)
        return read_bea_flat(code, s["frecuencia"], dropped)
    if fuente == "census":
        return read_census(code, dropped)
    if fuente == "omb":
        return read_omb(code, dropped)
    if fuente == "nyfed":
        return read_nyfed(code, dropped)
    if fuente == "treasury":
        return read_treasury(code, dropped)
    raise ValueError(f"Fuente desconocida: {fuente}")


def transform(df: pd.DataFrame, op: str, frecuencia: str) -> pd.DataFrame:
    """Aplica el sufijo de `codigo_fuente`. Las variaciones exigen periodos contiguos:
    si falta un mes (p. ej. oct-2025 en el IPC) la variación queda vacía, no se imputa."""
    if not op:
        return df
    if op.startswith("x"):
        return df.assign(valor=df["valor"] * float(op[1:]))
    if op in ("var1m", "var12m") and frecuencia == "mensual":
        lag = 1 if op == "var1m" else 12
        s = df.set_index(df["fecha"].dt.to_period("M"))["valor"].sort_index()
        s = s.reindex(pd.period_range(s.index.min(), s.index.max(), freq="M"))
        out = (s / s.shift(lag) - 1) * 100
        out = out.dropna()
        return pd.DataFrame({"fecha": out.index.to_timestamp(), "valor": out.to_numpy()})
    raise ValueError(f"Transformación no soportada: {op} ({frecuencia})")


def process() -> Path:
    series = comun.load_series(ISO3)
    dropped = Dropped()
    frames = []
    for s in series:
        code, op = split_code(s["codigo_fuente"])
        try:
            df = transform(read_base(s, code, dropped), op, s["frecuencia"])
        except FileNotFoundError as e:
            log.error("%s: falta el archivo crudo (%s); ¿se descargó?", s["nombre_corto"], e)
            continue
        df["fecha"] = comun.period_start(df["fecha"], s["frecuencia"])
        dup = df.duplicated("fecha")
        if dup.any():
            raise ValueError(f"{s['nombre_corto']}: {dup.sum()} periodos repetidos tras normalizar fechas")
        for col in ("fuente", "codigo_fuente", "nombre_corto", "indicador_comun",
                    "frecuencia", "unidad"):
            df[col] = s[col]
        df["pais"] = ISO3
        frames.append(df)
    dropped.report()
    return comun.write_interim(ISO3, pd.concat(frames, ignore_index=True))


def main(argv: list[str] | None = None) -> int:
    # La consola de Windows (cp1252) no puede imprimir algunos caracteres del log de
    # comun.write_interim y de esta ayuda ('→'): se reemplazan en pantalla; el archivo de log queda en UTF-8.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--solo-procesar", action="store_true",
                    help="no descarga: solo procesa lo que ya está en data/raw/USA")
    ap.add_argument("--serie", nargs="+", metavar="NOMBRE_CORTO",
                    help="descargar solo estas series (el procesamiento siempre es completo)")
    ap.add_argument("--pausa", type=float, default=1.0, help="segundos entre peticiones (≥ 1)")
    ap.add_argument("--bls-desde", type=int, metavar="AAAA",
                    help="BLS: pedir solo los bloques de 10 años que llegan a ese año o después "
                         "(ahorra cuota de la API v1; los bloques anteriores no se tocan)")
    args = ap.parse_args(argv)

    comun.setup_logging(ISO3)
    errors = 0
    if not args.solo_procesar:
        series = comun.load_series(ISO3)
        if args.serie:
            wanted = set(args.serie)
            missing = wanted - {s["nombre_corto"] for s in series}
            if missing:
                log.warning("No están activas en config/series/USA.csv: %s", ", ".join(sorted(missing)))
            series = [s for s in series if s["nombre_corto"] in wanted]
        log.info("Descargando %d series de USA", len(series))
        errors = download(series, max(args.pausa, 1.0), args.bls_desde)
    log.info("Procesando data/raw/USA")
    process()
    if errors:
        log.error("Terminó con %d errores de descarga (ver arriba)", errors)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
