"""Ecuador: series del Banco Central del Ecuador (BCE).

Ecuador está dolarizado desde 2000: no hay tasa de política monetaria ni tipo de
cambio propio (los indicadores comunes tasa_politica, tc_usd_* no aplican).

Fuentes (todas oficiales y sin clave):
- `bce_bcedata`: API REST pública de BCEData (portal de series del BCE, publica los
  cuadros de la Información Estadística Mensual con toda su historia):
      /wp-json/bcedata/v1/bundle/<grupo>   series, frecuencias, unidades y rango
      /wp-json/bcedata/v1/grid?id_grupo=&frecuencia=&unidad=&desde=&hasta=
  Se guarda la respuesta de `grid` por (grupo, frecuencia, unidad).
  codigo_fuente = 'g<grupo>|<frecuencia>|<unidad>|<id_serie>'; con ' + ' entre dos
  códigos se suman (deuda externa + interna en % del PIB).
- `bce_cnt`: Excel del Boletín de Cuentas Nacionales Trimestrales vigente (tou_*.xlsx).
- `bce_imaec`: Excel del IMAEc (índice mensual de actividad) vigente.
- `bce_iem`: cuadro 4.2.1 (IPC) de la Información Estadística Mensual vigente.
Los Excel cambian de nombre cada mes: se busca el enlace vigente y se guarda con
nombre estable en data/raw.

Uso:
    python ecu.py                      # descargar + procesar
    python ecu.py --solo-procesar      # solo rehacer data/interim desde data/raw
    python ecu.py --serie ipc_indice desempleo
"""
from __future__ import annotations

import argparse
import ast
import base64
import datetime as dt
import json
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import comun  # noqa: E402

ISO3 = "ECU"
BCE = "https://contenido.bce.fin.ec"
BCEDATA_API = f"{BCE}/wp-json/bcedata/v1"
# Archivo estable en data/raw -> (página, patrón del enlace, cómo elegir el vigente).
EXCEL_SOURCES = {
    "bce_cnt": ("/boletin-de-cuentas-nacionales-trimestrales/",
                r"/documentos/informacioneconomica/cuentasnacionales/trimestrales/tou_(\d+)_\d{6}\.xlsx"),
    "bce_imaec": ("/imaec-cuadros-de-resultados/",
                  r"/documentos/PublicacionesNotas/Catalogo/IMAEc/IMAEc_(\d{6})\.xlsx"),
}
IEM_PAGE = "/iem-publicaciones/"
IEM_INDEX = r"/documentos/PublicacionesNotas/Catalogo/IEMensual/Indices/m(\d{4})\d{6}\.html?"
IEM_FILE = "/documentos/PublicacionesNotas/Catalogo/IEMensual/m{num}/{archivo}"
MONTHS = {m: i + 1 for i, m in enumerate(
    ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"])}
MONTHS["set"] = 9
ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4}

log = comun.log


# ---------------------------------------------------------------- utilidades
def norm(text) -> str:
    return " ".join(str(text).split()).lower()


def to_float(values: pd.Series, name: str) -> pd.Series:
    """Convierte a número; los no numéricos se descartan (no se imputan) y se registran."""
    num = pd.to_numeric(values, errors="coerce")
    bad = values[num.isna() & values.notna() & (values.astype(str).str.strip() != "")]
    if len(bad):
        log.warning("%s: %d valores no numéricos descartados, p. ej. %s",
                    name, len(bad), bad.head(3).tolist())
    return num


def apply_scale(serie: pd.Series, ops: list[str]) -> pd.Series:
    for op in ops:
        if re.fullmatch(r"x[\d.]+", op):
            serie = serie * float(op[1:])
        else:
            raise ValueError(f"Transformación desconocida: {op}")
    return serie


# ---------------------------------------------------------------- BCEData
def bcedata_parts(codigo: str) -> list[tuple[int, str, str, str]]:
    """'g4|Anual|Porcentaje del PIB|735 + g21|...' -> [(4, 'Anual', 'Porcentaje del PIB', '735'), ...]"""
    out = []
    for part in codigo.split(" + "):
        g, freq, unidad, id_serie = [p.strip() for p in part.split("|")]
        out.append((int(g.lstrip("g")), freq, unidad, id_serie))
    return out


def grid_filename(grupo: int, freq: str, unidad: str) -> str:
    slug = re.sub(r"[^0-9A-Za-zÁÉÍÓÚáéíóúÑñ]+", "_", unidad).strip("_")
    return f"g{grupo}_{freq}_{slug}.json"


def serie_id(token: str) -> str:
    """El token de BCEData es base64 de '<id_serie>:<hash>'."""
    return base64.b64decode(token + "=" * (-len(token) % 4)).decode("utf-8", "replace").split(":")[0]


def parse_bcedata_period(label, freq: str) -> pd.Timestamp:
    label = str(label).strip()
    if freq == "Mensual":                       # 'Ene 2000'
        mes, anio = label.split()
        return pd.Timestamp(int(anio), MONTHS[mes[:3].lower()], 1)
    if freq == "Trimestral":                    # '2012-I'
        anio, q = label.split("-")
        return pd.Timestamp(int(anio), 3 * ROMAN[q] - 2, 1)
    if freq == "Anual":                         # '2012'
        return pd.Timestamp(int(label), 1, 1)
    raise ValueError(f"Frecuencia BCEData no soportada: {freq}")


def bcedata_one(grupo: int, freq: str, unidad: str, id_serie: str, name: str) -> tuple[pd.Series, str]:
    path = comun.raw_path(ISO3, "bce_bcedata", grid_filename(grupo, freq, unidad))
    grid = json.loads(path.read_bytes().decode("utf-8"))
    row = next((r for r in grid.get("rows", []) if r.get("tipo") == "Series" and r.get("token")
                and serie_id(r["token"]) == id_serie), None)
    if row is None:
        raise ValueError(f"{path.name}: no está la serie {id_serie}")
    values = row.get("values") or {}
    if isinstance(values, str):
        # La API a veces devuelve el diccionario como texto (repr de Python).
        values = ast.literal_eval(re.sub(r"\bnan\b", "None", values))
    s = pd.Series({parse_bcedata_period(k, freq): v for k, v in values.items()})
    return to_float(s, name).dropna().sort_index(), row.get("ruta", "")


def bcedata_series(s: dict) -> pd.Series:
    parts = []
    for grupo, freq, unidad, id_serie in bcedata_parts(s["codigo_fuente"]):
        serie, ruta = bcedata_one(grupo, freq, unidad, id_serie, s["nombre_corto"])
        log.debug("%s: g%s %s -> %s", s["nombre_corto"], grupo, id_serie, ruta)
        parts.append(serie)
    if len(parts) == 1:
        return parts[0]
    both = pd.concat(parts, axis=1, join="inner")
    log.info("%s: suma de %d series en %d periodos comunes", s["nombre_corto"], len(parts), len(both))
    return both.sum(axis=1)


# ---------------------------------------------------------------- Excel BCE
def find_row(raw: pd.DataFrame, col: int, text: str) -> int:
    return next(i for i, v in raw[col].items() if isinstance(v, str) and norm(v) == text.lower())


def wide_sheet(raw: pd.DataFrame, header_text: str, column: str, parse_date, name: str) -> pd.Series:
    """Hojas del IMAEc y de CNT: una fila de encabezado (col 0 = header_text) y debajo
    una fila por periodo; la columna se localiza por su título."""
    hdr = find_row(raw, 0, header_text)
    col = next(c for c, v in raw.iloc[hdr].items() if isinstance(v, str) and norm(v) == column.lower())
    recs = {}
    for i in range(hdr + 1, len(raw)):
        fecha = parse_date(raw.iat[i, 0])
        if fecha is not None:
            recs[fecha] = raw.iat[i, col]
    serie = to_float(pd.Series(recs, dtype=object), name).dropna().sort_index()
    if serie.index.duplicated().any():
        raise ValueError(f"{name}: periodos repetidos")
    return serie


def parse_imaec_date(v) -> pd.Timestamp | None:     # '2018.ene'
    m = re.fullmatch(r"(\d{4})\.([a-zA-Z]{3})\w*", str(v).strip())
    return pd.Timestamp(int(m[1]), MONTHS[m[2].lower()], 1) if m else None


def parse_cnt_date(v) -> pd.Timestamp | None:       # '2000.I'
    m = re.fullmatch(r"(\d{4})\.(I|II|III|IV)", str(v).strip())
    return pd.Timestamp(int(m[1]), 3 * ROMAN[m[2]] - 2, 1) if m else None


def excel_series(s: dict) -> pd.Series:
    archivo, hoja, columna, *ops = s["codigo_fuente"].split("|")
    raw = pd.read_excel(comun.raw_path(ISO3, s["fuente"], archivo), sheet_name=hoja, header=None)
    if s["fuente"] == "bce_imaec":
        serie = wide_sheet(raw, "Fecha", columna, parse_imaec_date, s["nombre_corto"])
    else:
        serie = wide_sheet(raw, "Variables", columna, parse_cnt_date, s["nombre_corto"])
    return apply_scale(serie, ops)


def iem_series(s: dict) -> pd.Series:
    """Cuadro IEM 4.2.1: encabezado con grupos ('TOTAL', divisiones) y debajo
    'Índice' / 'Variación porcentual'. Filas mensuales: col 0 = año (solo en enero),
    col 1 = nombre del mes. Arriba hay secciones de promedio anual y a diciembre."""
    archivo, grupo, medida = s["codigo_fuente"].split("|")
    raw = pd.read_excel(comun.raw_path(ISO3, "bce_iem", archivo), sheet_name=0, header=None)
    # La celda del grupo trae también la ponderación: ' TOTAL  Ponderación: 100.0%'.
    g = grupo.lower()
    hdr, gcol = next((i, c) for i in range(min(30, len(raw))) for c in range(raw.shape[1])
                     if isinstance(raw.iat[i, c], str)
                     and (norm(raw.iat[i, c]) == g or norm(raw.iat[i, c]).startswith(g + " ")))
    col = next(c for c in range(gcol, raw.shape[1])
               if isinstance(raw.iat[hdr + 1, c], str) and norm(raw.iat[hdr + 1, c]) == medida.lower())
    meses = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
             "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11,
             "diciembre": 12}
    recs, year = {}, None
    for i in range(hdr + 2, len(raw)):
        y, m = raw.iat[i, 0], raw.iat[i, 1]
        if isinstance(m, str) and norm(m) in meses:
            if pd.notna(y):
                year = int(y)
            if year is None:
                raise ValueError(f"{archivo}: mes sin año en la fila {i}")
            recs[pd.Timestamp(year, meses[norm(m)], 1)] = raw.iat[i, col]
    serie = to_float(pd.Series(recs, dtype=object), s["nombre_corto"]).dropna().sort_index()
    if (serie.index.to_series().diff().dropna() > pd.Timedelta(days=31)).any():
        raise ValueError(f"{archivo}: huecos en la serie mensual (¿años mal asignados?)")
    return serie


# ---------------------------------------------------------------- descarga
def latest_link(client: comun.Client, page: str, pattern: str) -> tuple[str, str]:
    html = client.get(BCE + page).text
    found = [(m.group(0), m.group(1)) for m in re.finditer(pattern, html)]
    if not found:
        raise ValueError(f"no se encontró ningún enlace {pattern} en {BCE + page}")
    return max(found, key=lambda x: int(x[1]))   # el de mayor número/fecha


def download(series: list[dict], client: comun.Client) -> None:
    done: set[str] = set()
    iem_num: str | None = None

    def save(fuente: str, filename: str, url: str, content: bytes) -> None:
        action = comun.save_raw(ISO3, fuente, filename, content, url)
        log.info("%-12s %-45s [%s]", fuente, filename, action)
        done.add(f"{fuente}/{filename}")

    bundles: dict[int, dict] = {}
    for s in series:
        fuente, codigo = s["fuente"], s["codigo_fuente"]
        try:
            if fuente == "bce_bcedata":
                for grupo, freq, unidad, _ in bcedata_parts(codigo):
                    fn = grid_filename(grupo, freq, unidad)
                    if f"{fuente}/{fn}" in done:
                        continue
                    if grupo not in bundles:
                        bundles[grupo] = client.get(f"{BCEDATA_API}/bundle/{grupo}").json()
                    b = bundles[grupo]
                    if unidad not in b["unidades"].get(freq, []):
                        raise ValueError(f"g{grupo}: la unidad '{unidad}' ({freq}) ya no existe; "
                                         f"hay {b['unidades'].get(freq)}")
                    rng = b["range_by_freq"][freq]
                    params = {"id_grupo": grupo, "frecuencia": freq, "unidad": unidad,
                              "desde": rng["minYm"], "hasta": rng["maxYm"]}
                    r = client.get(f"{BCEDATA_API}/grid", params=params, timeout=300)
                    if not r.json().get("rows"):
                        raise ValueError(f"g{grupo} {freq} {unidad}: respuesta sin filas")
                    save(fuente, fn, r.url, r.content)
            elif fuente in EXCEL_SOURCES:
                fn = codigo.split("|")[0]
                if f"{fuente}/{fn}" in done:
                    continue
                link, _ = latest_link(client, *EXCEL_SOURCES[fuente])
                r = client.get(BCE + link)
                if not r.content.startswith(b"PK"):
                    raise ValueError(f"{link} no es un .xlsx")
                log.info("%s: archivo vigente %s", fuente, link.rsplit("/", 1)[-1])
                save(fuente, fn, BCE + link, r.content)
            elif fuente == "bce_iem":
                fn = codigo.split("|")[0]
                if f"{fuente}/{fn}" in done:
                    continue
                if iem_num is None:
                    _, iem_num = latest_link(client, IEM_PAGE, IEM_INDEX)
                    log.info("IEM vigente: m%s", iem_num)
                url = BCE + IEM_FILE.format(num=iem_num, archivo=fn)
                r = client.get(url)
                if not r.content.startswith(b"PK"):
                    raise ValueError(f"{url} no es un .xlsx")
                save(fuente, fn, url, r.content)
            else:
                raise ValueError(f"fuente desconocida: {fuente}")
        except Exception as e:  # noqa: BLE001
            log.error("%s (%s): %s", s["nombre_corto"], codigo, e)


# ---------------------------------------------------------------- proceso
def process(series: list[dict]) -> None:
    readers = {"bce_bcedata": bcedata_series, "bce_cnt": excel_series,
               "bce_imaec": excel_series, "bce_iem": iem_series}
    frames = []
    for s in series:
        try:
            serie = readers[s["fuente"]](s)
        except FileNotFoundError as e:
            log.warning("%s: falta el archivo crudo (%s)", s["nombre_corto"], e)
            continue
        except Exception as e:  # noqa: BLE001
            log.error("%s: no se pudo procesar: %s", s["nombre_corto"], e)
            continue
        if serie.empty:
            log.error("%s: sin observaciones", s["nombre_corto"])
            continue
        df = pd.DataFrame({"fecha": comun.period_start(pd.Series(serie.index), s["frecuencia"]),
                           "valor": serie.values})
        if df.fecha.duplicated().any():
            raise ValueError(f"{s['nombre_corto']}: periodos repetidos tras normalizar fechas")
        for col in ("fuente", "codigo_fuente", "nombre_corto", "indicador_comun", "frecuencia", "unidad"):
            df[col] = s[col]
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    out["pais"] = ISO3
    comun.write_interim(ISO3, out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--solo-procesar", action="store_true", help="no descarga; solo data/raw -> interim")
    ap.add_argument("--serie", nargs="+", help="nombre_corto de las series a descargar")
    ap.add_argument("--pausa", type=float, default=1.0, help="segundos entre peticiones (>= 1)")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # el log usa '→' y tildes

    comun.setup_logging(ISO3)
    series = comun.load_series(ISO3)
    if not args.solo_procesar:
        todo = [s for s in series if not args.serie or s["nombre_corto"] in args.serie]
        download(todo, comun.Client(pause=max(args.pausa, 1.0)))
    process(series)
    return 0


if __name__ == "__main__":
    sys.exit(main())
