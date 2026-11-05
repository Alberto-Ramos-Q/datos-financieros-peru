"""Descargador de series macro de Argentina (BCRA, INDEC, Ministerio de Economía).

Fuentes (todas oficiales y sin clave):
- `bcra`: API de Estadísticas Monetarias **v4.0** del BCRA
  (`https://api.bcra.gob.ar/estadisticas/v4.0/Monetarias/{id}`). La v3 responde
  410 "deprecado" desde 2026. Máximo 3000 registros por consulta.
- `indec`: archivo CSV del IPC de INDEC (`serie_ipc_divisiones.csv`), más actual que
  la API de series (que publica el IPC con un mes de rezago).
- `datos_gob_ar`: API de Series de Tiempo del Estado argentino
  (`apis.datos.gob.ar/series`), para series de INDEC (cuentas nacionales, comercio,
  EPH) y del Ministerio de Economía (Hacienda, Trabajo). El organismo originador de
  cada serie se anota en `notas`.
- `mecon_finanzas`: Excel trimestral de deuda pública de la Secretaría de Finanzas.

Uso:
    python arg.py                       # descarga y procesa todas las series activas
    python arg.py --solo-procesar       # solo reconstruye el parquet desde data/raw/ARG
    python arg.py --serie tasa_politica m2 --pausa 2

Convenciones de `codigo_fuente` en `config/series/ARG.csv`:
- bcra: id de variable de la API v4 (p. ej. `5`).
- indec: `<Codigo>|<Region>|<columna>` del CSV del IPC (p. ej. `0|Nacional|v_i_a_IPC`).
- datos_gob_ar: id de la serie; `id@modo` pide un `representation_mode` de la API
  (p. ej. `@percent_change_a_year_ago`); `idA/idB` es el cociente A/B×100.
- mecon_finanzas: `<hoja>|<rótulo de la fila>`.
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import logging
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import comun  # noqa: E402

ISO3 = "ARG"
BCRA_URL = "https://api.bcra.gob.ar/estadisticas/v4.0/Monetarias"
BCRA_PAGE = 3000                 # límite máximo de la API v4
BCRA_WINDOW_YEARS = 5            # ventanas fijas para series diarias (< 3000 registros)
INDEC_IPC_URL = "https://www.indec.gob.ar/ftp/cuadros/economia/serie_ipc_divisiones.csv"
SERIES_API_URL = "https://apis.datos.gob.ar/series/api/series/"
SERIES_API_PAGE = 1000           # límite máximo de la API de series
FINANZAS_PAGE = "https://www.argentina.gob.ar/economia/finanzas/datos-trimestrales-de-la-deuda"

log = logging.getLogger("data_macro_paises")

# Conversión a la unidad del indicador común.
FACTOR = {
    ("bcra", "1618"): 1 / 1000,       # M2: miles de ARS → millones
    ("bcra", "1606"): 1 / 1000,       # base monetaria: miles de ARS → millones
    ("bcra", "1623"): 1 / 1000,       # M3 total (MN + ME): miles de ARS → millones
    ("datos_gob_ar", "143.3_ICE_SERVIA_2004_A_25"): 100,   # fracción → %
    ("datos_gob_ar", "45.2_ECTDT_0_T_33"): 100,            # fracción → %
    ("mecon_finanzas", "*"): 100,                          # ratios en fracción → %
}

# Series diarias que se guardan como mensuales: "last" = fin de periodo, "mean" = promedio.
DAILY_TO_MONTHLY = {
    "tasa_politica": "last",
    "credito_privado": "last",
    "tasa_interbancaria": "mean",
    "tasa_pasiva_promedio": "mean",
    "tc_usd_promedio": "mean",
    "tasa_badlar": "mean",
    "credito_privado_mn": "last",
    "credito_privado_me_usd": "last",
}

# Recortes documentados (ver docs/fuentes/ARG.md).
MIN_DATE = {
    # El SMVM anterior a 1992 está en signos monetarios ya extinguidos ($ ley 18.188,
    # $a, australes): mezclarlos con pesos rompe la serie. Se conserva desde el peso actual.
    "salario_minimo": "1992-01-01",
}
NO_FUTURE = {"salario_minimo"}   # la API publica aumentos ya decretados a futuro
# Agregados del BCRA reexpresados en pesos actuales (13 ceros quitados desde 1970):
# antes de ~1965 el saldo redondeado en miles de ARS da 0. Ese 0 no es un dato.
ZERO_AS_MISSING = {"m2", "base_monetaria", "m3_amplio"}


# ---------------------------------------------------------------------------
# Descarga
# ---------------------------------------------------------------------------

def bcra_catalog(client: comun.Client) -> dict[str, dict]:
    """Catálogo de variables de la API v4 (se guarda en raw para trazabilidad)."""
    rows = []
    for offset in (0, 1000, 2000):
        url = f"{BCRA_URL}?offset={offset}&limit=1000"
        r = client.get(url)
        comun.save_raw(ISO3, "bcra", f"catalogo_{offset:04d}.json", r.content, url)
        page = r.json().get("results", [])
        rows += page
        if len(page) < 1000:
            break
    return {str(x["idVariable"]): x for x in rows}


def bcra_windows(first: str, periodicity: str, today: dt.date) -> list[tuple[str, str, str]]:
    """Ventanas (etiqueta, desde, hasta). Las mensuales van en una sola consulta; las
    diarias en bloques fijos de 5 años, para que los bloques viejos no cambien de bytes
    en cada corrida (la API ordena de más reciente a más antiguo)."""
    if periodicity != "D":
        return [("completa", "1900-01-01", today.isoformat())]
    y0 = int(first[:4]) // BCRA_WINDOW_YEARS * BCRA_WINDOW_YEARS
    out = []
    for y in range(y0, today.year + 1, BCRA_WINDOW_YEARS):
        end = min(dt.date(y + BCRA_WINDOW_YEARS - 1, 12, 31), today)
        out.append((f"{y}-{y + BCRA_WINDOW_YEARS - 1}", f"{y}-01-01", end.isoformat()))
    return out


def download_bcra(client: comun.Client, var_ids: set[str], today: dt.date) -> int:
    catalog = bcra_catalog(client)
    errors = 0
    for vid in sorted(var_ids, key=int):
        meta = catalog.get(vid)
        if not meta:
            log.error("bcra %s: no figura en el catálogo de la API v4", vid)
            errors += 1
            continue
        for label, desde, hasta in bcra_windows(meta["primerFechaInformada"], meta["periodicidad"], today):
            offset, n_total = 0, None
            while True:
                url = (f"{BCRA_URL}/{vid}?desde={desde}&hasta={hasta}"
                       f"&limit={BCRA_PAGE}&offset={offset}")
                r = client.get(url)
                payload = r.json()
                n_total = payload["metadata"]["resultset"]["count"]
                suffix = f"_p{offset // BCRA_PAGE}" if offset else ""
                action = comun.save_raw(ISO3, "bcra", f"{vid}__{label}{suffix}.json", r.content, url)
                log.info("bcra %-5s %-10s n=%5d  [%s]", vid, label + suffix, n_total, action)
                offset += BCRA_PAGE
                if offset >= n_total:
                    break
    return errors


def download_indec(client: comun.Client) -> int:
    r = client.get(INDEC_IPC_URL)
    action = comun.save_raw(ISO3, "indec", "serie_ipc_divisiones.csv", r.content, INDEC_IPC_URL)
    log.info("indec serie_ipc_divisiones.csv  [%s]", action)
    return 0


def series_api_file(sid: str, mode: str | None) -> str:
    return f"{sid}__{mode}.json" if mode else f"{sid}.json"


def download_series_api(client: comun.Client, items: set[tuple[str, str | None]]) -> int:
    errors = 0
    for sid, mode in sorted(items, key=lambda x: (x[0], x[1] or "")):
        params = {"ids": sid, "limit": SERIES_API_PAGE, "format": "json", "metadata": "full"}
        if mode:
            params["representation_mode"] = mode
        r = client.get(SERIES_API_URL, params=params)
        payload = r.json()
        count = payload.get("count", 0)
        if count > SERIES_API_PAGE:      # ninguna serie actual lo supera; se avisa por si cambia
            log.error("datos_gob_ar %s: %d filas > %d; falta paginar con start", sid, count, SERIES_API_PAGE)
            errors += 1
        action = comun.save_raw(ISO3, "datos_gob_ar", series_api_file(sid, mode), r.content, r.url)
        log.info("datos_gob_ar %-36s n=%4d  [%s]", sid + (f"@{mode}" if mode else ""), count, action)
    return errors


def download_finanzas(client: comun.Client) -> int:
    """El Excel cambia de nombre cada trimestre: se toma el primer enlace de la página
    (el más reciente) y se guarda con nombre fijo; save_raw versiona los cambios."""
    page = client.get(FINANZAS_PAGE).text
    links = re.findall(r'href="([^"]*deuda_publica_[^"]+\.xlsx)"', page)
    if not links:
        log.error("mecon_finanzas: no se encontró el Excel de deuda en %s", FINANZAS_PAGE)
        return 1
    url = links[0]
    r = client.get(url)
    action = comun.save_raw(ISO3, "mecon_finanzas", "deuda_publica.xlsx", r.content, url)
    log.info("mecon_finanzas %s → deuda_publica.xlsx  [%s]", url.rsplit("/", 1)[-1], action)
    return 0


def download(series: list[dict], pause: float) -> int:
    client = comun.Client(pause=pause)
    today = dt.date.today()
    bcra, api, errors = set(), set(), 0
    sources = {s["fuente"] for s in series}
    for s in series:
        if s["fuente"] == "bcra":
            bcra.add(s["codigo_fuente"])
        elif s["fuente"] == "datos_gob_ar":
            for part in s["codigo_fuente"].split("/"):
                sid, _, mode = part.partition("@")
                api.add((sid, mode or None))
    steps = [("indec", lambda: download_indec(client)),
             ("bcra", lambda: download_bcra(client, bcra, today)),
             ("datos_gob_ar", lambda: download_series_api(client, api)),
             ("mecon_finanzas", lambda: download_finanzas(client))]
    for fuente, step in steps:
        if fuente not in sources:
            continue
        try:
            errors += step()
        except Exception as e:  # noqa: BLE001
            log.error("%s: %s", fuente, e)
            errors += 1
    return errors


# ---------------------------------------------------------------------------
# Procesamiento (solo lee data/raw/ARG)
# ---------------------------------------------------------------------------

def read_bcra(vid: str) -> pd.Series:
    files = sorted(comun.raw_path(ISO3, "bcra", "x").parent.glob(f"{vid}__*.json"))
    if not files:
        raise FileNotFoundError(f"no hay archivos crudos de la variable {vid}")
    obs = {}
    for f in files:
        for res in json.loads(f.read_bytes().decode("utf-8")).get("results", []):
            for d in res.get("detalle", []):
                obs[d["fecha"]] = d["valor"]
    s = pd.Series(obs, dtype="object")
    s.index = pd.to_datetime(s.index)
    return s.sort_index()


def read_indec_ipc(code: str) -> pd.Series:
    codigo, region, column = code.split("|")
    path = comun.raw_path(ISO3, "indec", "serie_ipc_divisiones.csv")
    # INDEC publica en latin-1, separado por ';', con coma decimal y "NA" como faltante.
    df = pd.read_csv(path, sep=";", encoding="latin-1", dtype=str, keep_default_na=False)
    df = df[(df["Codigo"].str.strip() == codigo) & (df["Region"].str.strip() == region)]
    if df.empty:
        raise ValueError(f"INDEC IPC: no hay filas para {codigo}/{region}")
    s = pd.Series(df[column].str.strip().str.replace(",", ".", regex=False).values,
                  index=pd.to_datetime(df["Periodo"].str.strip(), format="%Y%m"))
    return s.sort_index()


def read_series_api(sid: str, mode: str | None) -> pd.Series:
    path = comun.raw_path(ISO3, "datos_gob_ar", series_api_file(sid, mode))
    payload = json.loads(path.read_bytes().decode("utf-8"))
    s = pd.Series({row[0]: row[1] for row in payload["data"]}, dtype="object")
    s.index = pd.to_datetime(s.index)
    return s.sort_index()


def read_finanzas(code: str) -> pd.Series:
    sheet, label = code.split("|", 1)
    path = comun.raw_path(ISO3, "mecon_finanzas", "deuda_publica.xlsx")
    df = pd.read_excel(path, sheet_name=sheet, header=None)
    header_row = df.index[df.astype(str).apply(lambda r: r.str.strip().eq("INDICADORES").any(), axis=1)][0]
    years = df.loc[header_row]
    rows = df.index[df.astype(str).apply(lambda r: r.str.strip().eq(label).any(), axis=1)]
    if rows.empty:
        raise ValueError(f"{sheet}: no se encontró la fila '{label}'")
    row = df.loc[rows[0]]
    obs = {}
    for col, head in years.items():
        # Solo columnas anuales ("2005", "2005 (1)"); las trimestrales ("1er. Trim. 2026") se omiten.
        m = re.fullmatch(r"(\d{4})(?:\s*\(\d\))?", str(head).strip().replace(".0", ""))
        if m:
            obs[f"{m.group(1)}-01-01"] = row[col]
    s = pd.Series(obs, dtype="object")
    s.index = pd.to_datetime(s.index)
    return s


def raw_values(s: dict) -> pd.Series:
    fuente, code = s["fuente"], s["codigo_fuente"]
    if fuente == "bcra":
        return read_bcra(code)
    if fuente == "indec":
        return read_indec_ipc(code)
    if fuente == "mecon_finanzas":
        return read_finanzas(code)
    if fuente == "datos_gob_ar":
        parts = []
        for part in code.split("/"):
            sid, _, mode = part.partition("@")
            v = pd.to_numeric(read_series_api(sid, mode or None), errors="coerce")
            if mode:                       # los modos de variación vienen como fracción
                v = v * 100
            parts.append(v)
        if len(parts) == 2:               # cociente A/B en %
            a, b = parts
            return (a / b * 100).dropna()
        return parts[0]
    raise ValueError(f"fuente desconocida: {fuente}")


def factor_for(fuente: str, code: str) -> float:
    return FACTOR.get((fuente, code), FACTOR.get((fuente, "*"), 1))


def build_series(s: dict) -> pd.DataFrame:
    name, freq = s["nombre_corto"], s["frecuencia"]
    raw = raw_values(s)
    values = pd.to_numeric(raw, errors="coerce")
    bad = raw.notna() & values.isna() & ~raw.astype(str).str.strip().isin(["", "NA", "nan", "None"])
    if bad.any():
        log.warning("%s: %d valores no numéricos descartados (p. ej. %r)", name, bad.sum(), raw[bad].iloc[0])
    n_na = int((raw.notna() & values.isna()).sum() - bad.sum())
    if n_na:
        log.info("%s: %d marcadores de 'sin dato' (NA/vacío) descartados", name, n_na)
    values = values.dropna() * factor_for(s["fuente"], s["codigo_fuente"])

    if name in ZERO_AS_MISSING:
        zeros = int((values == 0).sum())
        values = values[values != 0]
        if zeros:
            log.info("%s: %d ceros por redondeo de la reexpresión descartados", name, zeros)
    if name in MIN_DATE:
        dropped = (values.index < MIN_DATE[name]).sum()
        values = values[values.index >= MIN_DATE[name]]
        log.info("%s: %d observaciones anteriores a %s excluidas (ver notas)", name, dropped, MIN_DATE[name])
    if name in NO_FUTURE:
        limit = pd.Timestamp(dt.date.today()).to_period("M").to_timestamp()
        dropped = (values.index > limit).sum()
        values = values[values.index <= limit]
        if dropped:
            log.info("%s: %d valores futuros (ya decretados) excluidos", name, dropped)

    agg = DAILY_TO_MONTHLY.get(name)
    if agg:
        # El mes en curso está incompleto: su promedio o "fin de mes" no es el dato del mes.
        current = pd.Timestamp(dt.date.today()).to_period("M")
        values = values[values.index.to_period("M") < current]
        values = values.groupby(values.index.to_period("M")).agg(agg)
        values.index = values.index.to_timestamp()

    df = pd.DataFrame({"pais": ISO3,
                       "fecha": comun.period_start(pd.Series(values.index), freq).values,
                       "valor": values.values})
    for col in ("fuente", "codigo_fuente", "nombre_corto", "indicador_comun", "frecuencia", "unidad"):
        df[col] = s[col]
    return df


def process(series: list[dict]) -> int:
    frames, errors = [], 0
    for s in series:
        try:
            frames.append(build_series(s))
        except Exception as e:  # noqa: BLE001
            log.error("%s: %s", s["nombre_corto"], e)
            errors += 1
    if not frames:
        log.error("No hay series para procesar")
        return errors + 1
    comun.write_interim(ISO3, pd.concat(frames, ignore_index=True))
    return errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--solo-procesar", action="store_true", help="no descarga; solo procesa data/raw/ARG")
    ap.add_argument("--serie", nargs="+", help="nombre_corto a descargar (el parquet se rehace con todas)")
    ap.add_argument("--pausa", type=float, default=1.0, help="segundos entre peticiones (mín. 1)")
    args = ap.parse_args(argv)
    # La consola de Windows usa cp1252 y comun.py loguea "→": sin esto, logging falla.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    comun.setup_logging(ISO3)

    series = comun.load_series(ISO3)
    errors = 0
    if not args.solo_procesar:
        target = series
        if args.serie:
            target = [s for s in series if s["nombre_corto"] in set(args.serie)]
            unknown = set(args.serie) - {s["nombre_corto"] for s in target}
            if unknown:
                log.warning("No están activas en config/series/ARG.csv: %s", ", ".join(sorted(unknown)))
        log.info("Descargando %d serie(s) de BCRA / INDEC / datos.gob.ar / Finanzas", len(target))
        errors += download(target, max(args.pausa, 1.0))
    errors += process(series)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
