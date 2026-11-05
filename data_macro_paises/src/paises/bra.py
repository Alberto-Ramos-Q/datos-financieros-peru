"""Brasil (BRA): descarga y procesa series macro de fuentes oficiales.

Fuentes (todas públicas, sin clave):
- Banco Central do Brasil, SGS: `api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados?formato=json`.
  Las series DIARIAS exigen `dataInicial`/`dataFinal` con una ventana máxima de 10 años:
  se piden en ventanas fijas de 10 años (nombres de archivo estables).
- IBGE, SIDRA: `apisidra.ibge.gov.br/values/t/{tabla}/n1/all/v/{variable}/p/all[/c{clas}/{cat}]`.
- Banco Central do Brasil, Focus/Expectativas (API Olinda, OData).

Dos pasos separados:
1. Descargar: guarda cada respuesta tal cual con `comun.save_raw` en `data/raw/BRA/<fuente>/`.
2. Procesar: lee SOLO `data/raw/BRA/` y escribe `data/interim/BRA_observaciones.parquet`.

Uso:
    python src/paises/bra.py                          # descarga + procesa (todas las activas)
    python src/paises/bra.py --solo-procesar          # solo reconstruye el parquet desde data/raw
    python src/paises/bra.py --serie ipc_indice tc_usd_diario   # descarga solo esas series
    python src/paises/bra.py --pausa 2                # segundos entre peticiones (mínimo 1)

`--serie` limita la DESCARGA; el procesamiento siempre reconstruye el parquet con todas las
series activas (si no, el parquet quedaría incompleto).

`codigo_fuente` en config/series/BRA.csv:  `<código>[#<transf>+<transf>...]`
- BCB-SGS:    código SGS (`433`).
- IBGE-SIDRA: `<tabla>/v<variable>[/c<clasificación>=<categoría>]` (`1620/v583/c11255=90707`).
- BCB-Focus:  `<recurso>/<Indicador>/Suavizada=<S|N>/baseCalculo=<0|1>/<campo>`.
Transformaciones (se aplican en el orden escrito; ver `apply_transforms`):
    desde=AAAA-MM-DD  descarta observaciones anteriores (cambio de moneda, Plan Real)
    esc=<factor>      multiplica por un factor (cambio de escala, p. ej. miles → millones)
    neg               cambia el signo (NFSP → resultado)
    fin_mes           último dato de cada mes (de diaria a mensual); solo meses cerrados
    prom_mes          promedio del mes (de diaria a mensual); solo meses cerrados
    suma_trim         suma de 3 meses; solo trimestres completos
    suma_anual=<n>    suma de n periodos del año (4 trimestres o 12 meses); solo años completos
    dic               valor de diciembre como dato anual
    var12m            variación % contra el mismo periodo del año anterior
    acum12m           variación % compuesta de los últimos 12 meses (de variaciones mensuales %)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
import time
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import comun  # noqa: E402

ISO3 = "BRA"
SGS_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados?formato=json"
SIDRA_URL = "https://apisidra.ibge.gov.br/values/t/{table}/n1/all/v/{var}/p/all{cls}"
OLINDA_URL = "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/{resource}"
RAW_FOLDER = {"BCB-SGS": "bcb_sgs", "IBGE-SIDRA": "ibge_sidra", "BCB-Focus": "bcb_focus"}

# Series SGS diarias y su primer año con datos. La API rechaza ventanas de más de 10 años y
# devuelve 404 si la ventana no tiene datos, así que las ventanas empiezan en ese año.
DAILY_SGS_FIRST_YEAR = {"1": 1984, "432": 1999}
DAILY_WINDOW_YEARS = 10

log = logging.getLogger("data_macro_paises.bra")


# --------------------------------------------------------------------------- configuración

def split_code(codigo_fuente: str) -> tuple[str, list[str]]:
    """'5727#dic+neg' → ('5727', ['dic', 'neg'])."""
    base, _, transf = codigo_fuente.partition("#")
    return base.strip(), [t.strip() for t in transf.split("+") if t.strip()]


def raw_requests(row: dict, today: dt.date) -> list[tuple[str, str, str]]:
    """Lista de (carpeta, archivo, url) que necesita la serie. Varias series pueden compartir
    archivo (p. ej. 432 diaria y 432#fin_mes): se descarga una sola vez."""
    fuente = row["fuente"]
    base, _ = split_code(row["codigo_fuente"])
    folder = RAW_FOLDER[fuente]
    if fuente == "BCB-SGS":
        if base not in DAILY_SGS_FIRST_YEAR:
            return [(folder, f"sgs_{base}.json", SGS_URL.format(code=base))]
        out = []
        for y0 in range(DAILY_SGS_FIRST_YEAR[base], today.year + 1, DAILY_WINDOW_YEARS):
            y1 = y0 + DAILY_WINDOW_YEARS - 1
            url = (SGS_URL.format(code=base)
                   + f"&dataInicial=01/01/{y0}&dataFinal=31/12/{y1}")
            out.append((folder, f"sgs_{base}_{y0}-{y1}.json", url))
        return out
    if fuente == "IBGE-SIDRA":
        table, var, cls = parse_sidra_code(base)
        cls_url = f"/c{cls[0]}/{cls[1]}" if cls else ""
        name = f"sidra_{table}_v{var}" + (f"_c{cls[0]}-{cls[1]}" if cls else "") + ".json"
        return [(folder, name, SIDRA_URL.format(table=table, var=var, cls=cls_url))]
    if fuente == "BCB-Focus":
        resource, indicador, suav, base_calc, _field = base.split("/")
        flt = (f"Indicador eq '{indicador}' and Suavizada eq '{suav.split('=')[1]}' "
               f"and baseCalculo eq {base_calc.split('=')[1]}")
        url = (OLINDA_URL.format(resource=resource) + "?$format=json&$top=100000&$orderby=Data"
               + "&$filter=" + quote(flt))
        name = f"focus_{resource}_{indicador}_{suav.replace('=', '')}_{base_calc.replace('=', '')}.json"
        return [(folder, name.lower(), url)]
    raise ValueError(f"Fuente desconocida: {fuente}")


def parse_sidra_code(base: str) -> tuple[str, str, tuple[str, str] | None]:
    parts = base.split("/")
    table, var = parts[0], parts[1].lstrip("v")
    cls = None
    if len(parts) > 2:
        c, _, cat = parts[2].lstrip("c").partition("=")
        cls = (c, cat)
    return table, var, cls


# --------------------------------------------------------------------------- descarga

def download(series: list[dict], client: comun.Client, today: dt.date) -> int:
    """Descarga secuencial. Devuelve el número de errores."""
    pending: dict[tuple[str, str], str] = {}
    for row in series:
        for folder, name, url in raw_requests(row, today):
            pending.setdefault((folder, name), url)
    log.info("Descarga: %d archivos para %d series", len(pending), len(series))
    errors = 0
    for (folder, name), url in pending.items():
        try:
            content = get_valid(client, url, name)
            action = comun.save_raw(ISO3, folder, name, content, url)
            log.info("  %-60s %s", f"{folder}/{name}", action)
        except (requests.RequestException, ValueError) as e:
            errors += 1
            log.error("  %s/%s: %s", folder, name, e)
    return errors


def get_valid(client: comun.Client, url: str, name: str, attempts: int = 4) -> bytes:
    """GET con reintentos también cuando la respuesta no es válida: el gateway del BCB a veces
    corta a los 30 s y devuelve una página HTML de error con estado 200 (consultas diarias
    largas con la caché fría). Al reintentar suele responder en menos de 1 s."""
    for attempt in range(1, attempts + 1):
        r = client.get(url)
        try:
            check_payload(r.content, name)
            return r.content
        except ValueError as e:
            if attempt == attempts:
                raise
            wait = 10 * attempt
            log.warning("  %s: respuesta no válida (%s); reintento en %d s", name, str(e)[:80], wait)
            time.sleep(wait)
    raise RuntimeError("inalcanzable")


def check_payload(content: bytes, name: str) -> None:
    """Rechaza respuestas que no son datos (errores en JSON o páginas HTML) antes de guardarlas."""
    try:
        payload = json.loads(content.decode("utf-8"))
    except ValueError:
        raise ValueError(f"la respuesta no es JSON: {content[:150]!r}")
    if isinstance(payload, dict) and ("erro" in payload or "error" in payload):
        raise ValueError(f"la API devolvió un error: {str(payload)[:200]}")
    if isinstance(payload, list) and not payload:
        raise ValueError("respuesta vacía")


# --------------------------------------------------------------------------- lectura de raw

def read_raw(path: Path) -> object:
    return json.loads(path.read_bytes().decode("utf-8"))


def to_number(values: pd.Series, label: str) -> pd.Series:
    """Convierte a número; los marcadores de 'sin dato' ('...', '-', 'X', vacío, None) se
    descartan (no se imputan) y se deja constancia en el log."""
    num = pd.to_numeric(values, errors="coerce")
    bad = values[num.isna()]
    if len(bad):
        sample = sorted({str(v) for v in bad})[:5]
        log.info("    %s: %d valores no numéricos descartados %s", label, len(bad), sample)
    return num


def load_sgs(base: str, today: dt.date) -> pd.DataFrame:
    folder = comun.RAW_DIR / ISO3 / RAW_FOLDER["BCB-SGS"]
    if base in DAILY_SGS_FIRST_YEAR:
        files = sorted(folder.glob(f"sgs_{base}_*.json"))
    else:
        files = [folder / f"sgs_{base}.json"]
    files = [f for f in files if f.exists()]
    if not files:
        raise FileNotFoundError(f"no hay archivos raw para SGS {base}")
    rows = []
    for f in files:
        rows.extend(read_raw(f))
    df = pd.DataFrame(rows)
    df["fecha"] = pd.to_datetime(df["data"], format="%d/%m/%Y")
    df["valor"] = to_number(df["valor"], f"SGS {base}")
    df = df.dropna(subset=["valor"]).drop_duplicates("fecha").sort_values("fecha")
    return df[["fecha", "valor"]]


def load_sidra(base: str) -> pd.DataFrame:
    table, var, cls = parse_sidra_code(base)
    name = f"sidra_{table}_v{var}" + (f"_c{cls[0]}-{cls[1]}" if cls else "") + ".json"
    payload = read_raw(comun.RAW_DIR / ISO3 / RAW_FOLDER["IBGE-SIDRA"] / name)
    header, rows = payload[0], payload[1:]
    # La dimensión de periodo es la que se llama "Mês"/"Trimestre"/"Trimestre Móvel"...
    per_key = next(k for k, v in header.items() if k.endswith("C") and
                   any(w in v for w in ("Mês", "Trimestre", "Ano")))
    label_key = per_key[:-1] + "N"
    df = pd.DataFrame(rows)
    codes, labels = df[per_key].astype(str), df[label_key].astype(str).str.lower()
    year = codes.str[:4].astype(int)
    sub = codes.str[4:].astype(int)
    # '1º trimestre 1996' → código 199601 = trimestre 1. Los trimestres MÓVILES de la PNAD
    # ('jan-fev-mar 2012', código 201203) usan el último mes del trimestre.
    quarterly = labels.str.contains("trimestre") & ~labels.str.contains("-")
    month = sub.where(~quarterly, sub * 3 - 2)
    df["fecha"] = pd.to_datetime(dict(year=year, month=month, day=1))
    df["valor"] = to_number(df["V"], f"SIDRA {base}")
    return df.dropna(subset=["valor"]).sort_values("fecha")[["fecha", "valor"]]


def load_focus(base: str) -> pd.DataFrame:
    resource, indicador, suav, base_calc, field = base.split("/")
    name = f"focus_{resource}_{indicador}_{suav.replace('=', '')}_{base_calc.replace('=', '')}.json"
    payload = read_raw(comun.RAW_DIR / ISO3 / RAW_FOLDER["BCB-Focus"] / name.lower())
    df = pd.DataFrame(payload["value"])
    df["fecha"] = pd.to_datetime(df["Data"])
    df["valor"] = to_number(df[field], f"Focus {indicador}")
    return df.dropna(subset=["valor"]).sort_values("fecha")[["fecha", "valor"]]


# --------------------------------------------------------------------------- transformaciones

def apply_transforms(df: pd.DataFrame, transforms: list[str], label: str, today: dt.date) -> pd.DataFrame:
    """Aplica las transformaciones de `codigo_fuente` en orden (ver docstring del módulo)."""
    df = df.sort_values("fecha").reset_index(drop=True)
    for t in transforms:
        name, _, arg = t.partition("=")
        if name == "desde":
            n0 = len(df)
            df = df[df.fecha >= pd.Timestamp(arg)]
            log.info("    %s: %d obs. anteriores a %s descartadas (moneda no comparable)",
                     label, n0 - len(df), arg)
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
            per = df.fecha.dt.to_period("Q")
            g = df.groupby(per).valor.agg(["sum", "count"])
            g = g[g["count"] == 3]
            df = pd.DataFrame({"fecha": g.index.to_timestamp(), "valor": g["sum"].values})
        elif name == "suma_anual":
            per = df.fecha.dt.to_period("Y")
            g = df.groupby(per).valor.agg(["sum", "count"])
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
        else:
            raise ValueError(f"{label}: transformación desconocida '{t}'")
    return df.reset_index(drop=True)


# --------------------------------------------------------------------------- procesamiento

def process(series: list[dict], today: dt.date) -> int:
    frames, errors = [], 0
    for row in series:
        name = row["nombre_corto"]
        base, transforms = split_code(row["codigo_fuente"])
        try:
            if row["fuente"] == "BCB-SGS":
                df = load_sgs(base, today)
            elif row["fuente"] == "IBGE-SIDRA":
                df = load_sidra(base)
            elif row["fuente"] == "BCB-Focus":
                df = load_focus(base)
            else:
                raise ValueError(f"fuente desconocida {row['fuente']}")
        except (FileNotFoundError, KeyError, ValueError) as e:
            errors += 1
            log.error("  %s: no se pudo leer el raw (%s)", name, e)
            continue
        # Fechas futuras (Meta Selic hasta la próxima reunión, salario mínimo ya decretado):
        # no son observaciones, se descartan antes de agregar.
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
            raise ValueError(f"{name}: {dup.sum()} periodos repetidos tras normalizar fechas")
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
                log.warning("No están activas en config/series/BRA.csv: %s", ", ".join(sorted(missing)))
        client = comun.Client(pause=max(args.pausa, 1.0))
        errors += download(selected, client, today)
    errors += process(series, today)
    log.info("Fin%s", f" con {errors} errores" if errors else " sin errores")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
