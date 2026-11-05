"""México: descarga y procesa series de Banxico (SIE) e INEGI (API, solo con token).

Fuentes oficiales:
- Banco de México, Sistema de Información Económica (SIE). Se usa la exportación
  CSV pública de la consulta de series (`consultarDirectorioInternetAction.do?
  accion=consultarSeries`), que NO pide token. El SIE también publica, con la misma
  clave, las series de INEGI (PIB, IGAE, INPC, balanza comercial) y de SHCP (finanzas
  públicas): se toman de ahí.
- INEGI, API de indicadores (BIE). Pide token gratuito: solo se usa si existe la
  variable de entorno INEGI_TOKEN (hoy solo para desempleo, que está inactiva).
- SHCP, datos abiertos (RFSP y SHRFSP) publicados en la Plataforma Nacional de Datos
  Abiertos (CKAN de www.datos.gob.mx). Se consulta la API `datastore_search` filtrada por
  `clave_concepto`: el CSV directo (repodatos.atdt.gob.mx) responde 403 desde esta red y
  los portales de SHCP no responden.

Configuración en `config/series/MEX.csv`. Formato de `codigo_fuente` (SIE):
    SR17575              la serie tal cual (niveles)
    SR17575:var_anual    la misma serie exportada por el SIE como tasa de crecimiento anual
    SG14/SR17645         cociente calculado (ver DERIVED) a partir de dos series
y de SHCP (fuente `shcp_datos`):
    <dataset CKAN>|<clave_concepto>/SR17645   concepto de SHCP entre el PIB nominal anual del SIE

Uso:
    python mex.py                         # descarga + procesa todas las activas
    python mex.py --solo-procesar         # solo reconstruye el parquet desde data/raw/MEX
    python mex.py --serie tasa_politica m2
    python mex.py --pausa 2

Cada serie es una petición (descargas secuenciales con pausa ≥ 1 s). La respuesta se
guarda tal cual en `data/raw/MEX/banxico_sie/<CLAVE>[__var_anual].csv`.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import os
import sys
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import comun  # noqa: E402

ISO3 = "MEX"
log = logging.getLogger("data_macro_paises")

SIE_URL = ("https://www.banxico.org.mx/SieInternet/consultarDirectorioInternetAction.do"
           "?accion=consultarSeries")
# Tipo de información de la exportación del SIE: 4,1 = niveles; 4,4 = tasa de crecimiento anual.
SIE_TIPOS = {"": "4,1", "var_anual": "4,4"}
SIE_NO_DATA = {"N/E", ""}          # N/E = "no existe" (fines de semana, meses sin dato)
SIE_FREQ = {"Diaria": "diaria", "Mensual": "mensual", "Trimestral": "trimestral",
            "Anual": "anual"}

INEGI_URL = ("https://www.inegi.org.mx/app/api/indicadores/desarrolladores/jsonxml/INDICATOR/"
             "{codigo}/es/00/false/BIE/2.0/{token}?type=json")

# SHCP vía la API CKAN de la Plataforma Nacional de Datos Abiertos.
SHCP_API = "https://www.datos.gob.mx/api/3/action/"
SHCP_MONTHS = {m: i + 1 for i, m in enumerate(
    ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
     "septiembre", "octubre", "noviembre", "diciembre"])}
SHCP_MONTHS["setiembre"] = 9

# Escala: la fuente viene en miles → se publica en millones (indicador común en millones).
SCALE = {"credito_privado": 1e-3, "m2": 1e-3, "exportaciones": 1e-3,
         "importaciones": 1e-3, "balanza_comercial": 1e-3}
# Series diarias que se publican mensuales: método de agregación.
DAILY_TO_MONTHLY = {"tasa_politica": "last"}


# --------------------------------------------------------------------------- descarga

def sie_components(codigo: str) -> list[tuple[str, str]]:
    """'SG14/SR17645' → [('SG14',''), ('SR17645','')]; 'SR17575:var_anual' → [('SR17575','var_anual')]."""
    out = []
    for part in codigo.split("/"):
        clave, _, tipo = part.strip().partition(":")
        if tipo not in SIE_TIPOS:
            raise ValueError(f"Tipo SIE desconocido en {codigo!r}: {tipo!r}")
        out.append((clave, tipo))
    return out


def sie_filename(clave: str, tipo: str) -> str:
    return f"{clave}__{tipo}.csv" if tipo else f"{clave}.csv"


def download_sie(client: comun.Client, clave: str, tipo: str) -> str:
    data = [("idCuadro", "CF102"), ("sector", "6"), ("version", "3"), ("locale", "es"),
            ("series", clave), ("anoInicial", ""), ("anoFinal", ""),   # vacío = toda la historia
            ("tipoInformacion", SIE_TIPOS[tipo]), ("formatoHorizontal", "false"),
            ("metadatosWeb", "true"), ("formatoCSV.x", "10"), ("formatoCSV.y", "10")]
    r = client.post(SIE_URL, data=data)
    if not r.headers.get("Content-Type", "").startswith("text/csv"):
        raise RuntimeError(f"El SIE no devolvió CSV para {clave} ({r.headers.get('Content-Type')})")
    meta, obs = parse_sie(r.content)            # valida antes de guardar
    if meta["clave"] != clave:
        raise RuntimeError(f"El SIE devolvió {meta['clave']} en vez de {clave}")
    # Trampa: el CSV trae la línea 'Fecha de consulta: <hora>', así que nunca es idéntico
    # byte a byte. Si solo cambia esa línea no se guarda (si no, save_raw versionaría la
    # serie en cada corrida y llenaría el historial).
    path = comun.raw_path(ISO3, "banxico_sie", sie_filename(clave, tipo))
    if path.exists() and strip_query_date(path.read_bytes()) == strip_query_date(r.content):
        action = "sin_cambios"
    else:
        action = comun.save_raw(ISO3, "banxico_sie", sie_filename(clave, tipo), r.content,
                                f"{SIE_URL} [POST series={clave} tipoInformacion={SIE_TIPOS[tipo]}]")
    log.info("%-10s %-10s %-10s n=%5d  %s → %s  [%s]", clave, tipo or "niveles",
             meta["periodicidad"], len(obs), obs[0][0] if obs else "-",
             obs[-1][0] if obs else "-", action)
    return action


def strip_query_date(content: bytes) -> bytes:
    return b"\n".join(l for l in content.splitlines() if not l.startswith(b'"Fecha de consulta'))


def download_inegi(client: comun.Client, codigo: str) -> str:
    token = os.environ.get("INEGI_TOKEN", "").strip()
    if not token:
        raise RuntimeError("falta la variable de entorno INEGI_TOKEN")
    url = INEGI_URL.format(codigo=codigo, token=token)
    r = client.get(url)
    json.loads(r.content.decode("utf-8"))      # valida que sea JSON
    # La URL guardada en el manifest NO lleva el token.
    return comun.save_raw(ISO3, "inegi_bie", f"{codigo}.json", r.content,
                          INEGI_URL.format(codigo=codigo, token="<INEGI_TOKEN>"))


def shcp_components(codigo: str) -> tuple[str, str, str]:
    """'dataset|RF000000SPFC/SR17645' → ('dataset', 'RF000000SPFC', 'SR17645')."""
    left, _, gdp = codigo.partition("/")
    dataset, _, concepto = left.partition("|")
    if not (dataset and concepto and gdp):
        raise ValueError(f"codigo_fuente SHCP mal formado: {codigo!r}")
    return dataset, concepto, gdp


def download_shcp(client: comun.Client, dataset: str, concepto: str) -> str:
    """Registros de un concepto de SHCP desde el datastore CKAN de datos.gob.mx."""
    meta = client.get(SHCP_API + "package_show", params={"id": dataset}).json()
    if not meta.get("success"):
        raise RuntimeError(f"datos.gob.mx: no existe el conjunto {dataset}")
    res = [r for r in meta["result"]["resources"] if r.get("datastore_active")]
    if len(res) != 1:
        raise RuntimeError(f"{dataset}: se esperaba 1 recurso con datastore y hay {len(res)}")
    params = {"resource_id": res[0]["id"], "filters": json.dumps({"clave_concepto": concepto}),
              "limit": 32000, "sort": "_id"}
    r = client.get(SHCP_API + "datastore_search", params=params)
    payload = r.json()
    result = payload.get("result") or {}
    recs = result.get("records") or []
    if not payload.get("success") or not recs:
        raise RuntimeError(f"{dataset}/{concepto}: respuesta sin registros")
    if result.get("total") != len(recs):
        raise RuntimeError(f"{dataset}/{concepto}: respuesta paginada ({len(recs)} de {result.get('total')})")
    action = comun.save_raw(ISO3, "shcp_datos", f"{concepto}.json", r.content, r.url)
    log.info("%-12s %-10s n=%5d  [%s]", concepto, "SHCP", len(recs), action)
    return action


def download(rows: list[dict], pause: float) -> int:
    client = comun.Client(pause=pause)
    errors, done = 0, set()
    for row in rows:
        try:
            if row["fuente"] == "shcp_datos":
                dataset, concepto, gdp = shcp_components(row["codigo_fuente"])
                download_shcp(client, dataset, concepto)
                if (gdp, "") not in done:
                    download_sie(client, gdp, "")
                    done.add((gdp, ""))
            elif row["fuente"] == "banxico_sie":
                for clave, tipo in sie_components(row["codigo_fuente"]):
                    if (clave, tipo) in done:
                        continue
                    download_sie(client, clave, tipo)
                    done.add((clave, tipo))
            elif row["fuente"] == "inegi_bie":
                log.info("%s: INEGI (token) → %s", row["nombre_corto"],
                         download_inegi(client, row["codigo_fuente"]))
            else:
                raise ValueError(f"fuente desconocida {row['fuente']}")
        except (requests.RequestException, RuntimeError, ValueError) as e:
            log.error("%s (%s): %s", row["nombre_corto"], row["codigo_fuente"], e)
            errors += 1
    return errors


# --------------------------------------------------------------------------- lectura

def parse_sie(content: bytes) -> tuple[dict, list[tuple[str, str]]]:
    """CSV de exportación del SIE → (metadatos, [(fecha dd/mm/aaaa, valor texto)]).

    El archivo trae un encabezado de metadatos ('Título', 'Periodo disponible',
    'Periodicidad', 'Unidad'...) y luego la fila 'Fecha,<CLAVE>' con los datos.
    Viene en ISO-8859-1.
    """
    rows = list(csv.reader(io.StringIO(content.decode("latin-1"))))
    meta, start = {}, None
    for i, r in enumerate(rows):
        if not r:
            continue
        key = r[0].strip()
        if key in ("Título", "Periodo disponible", "Periodicidad", "Cifra", "Unidad", "Base"):
            meta[key] = r[1].strip() if len(r) > 1 else ""
        if key == "Fecha":
            meta["clave"] = r[1].strip()
            start = i + 1
            break
    if start is None or "Periodicidad" not in meta:
        raise RuntimeError("CSV del SIE sin encabezado reconocible")
    meta["periodicidad"] = meta["Periodicidad"]
    obs = [(r[0].strip(), r[1].strip()) for r in rows[start:] if len(r) >= 2 and r[0].strip()]
    return meta, obs


def read_sie(clave: str, tipo: str) -> tuple[dict, pd.Series]:
    """Serie (fecha → valor float) leída SOLO de data/raw. Descarta 'N/E' y no numéricos."""
    path = comun.raw_path(ISO3, "banxico_sie", sie_filename(clave, tipo))
    if not path.exists():
        raise FileNotFoundError(path)
    meta, obs = parse_sie(path.read_bytes())
    dates, values, no_data, bad = [], [], 0, []
    for fecha, txt in obs:
        if txt in SIE_NO_DATA:
            no_data += 1
            continue
        try:
            v = float(txt.replace(",", ""))
        except ValueError:
            bad.append((fecha, txt))
            continue
        dates.append(pd.to_datetime(fecha, format="%d/%m/%Y"))
        values.append(v)
    if no_data:
        log.info("  %s%s: %d periodos con N/E descartados", clave, f":{tipo}" if tipo else "", no_data)
    for fecha, txt in bad:
        log.warning("  %s %s: valor no numérico %r descartado (no se imputa)", clave, fecha, txt)
    return meta, pd.Series(values, index=pd.DatetimeIndex(dates), dtype=float).sort_index()


def read_inegi(codigo: str) -> pd.Series:
    path = comun.raw_path(ISO3, "inegi_bie", f"{codigo}.json")
    if not path.exists():
        raise FileNotFoundError(path)
    payload = json.loads(path.read_bytes().decode("utf-8"))
    dates, values = [], []
    for o in payload["Series"][0]["OBSERVATIONS"]:
        txt = (o.get("OBS_VALUE") or "").strip()
        try:
            v = float(txt)
        except ValueError:
            log.warning("  INEGI %s %s: valor %r descartado", codigo, o.get("TIME_PERIOD"), txt)
            continue
        anio, _, per = o["TIME_PERIOD"].partition("/")
        dates.append(pd.Timestamp(int(anio), int(per or 1), 1))
        values.append(v)
    return pd.Series(values, index=pd.DatetimeIndex(dates), dtype=float).sort_index()


def read_shcp(concepto: str) -> tuple[str, pd.Series]:
    """(nombre del concepto, serie mensual en miles de pesos) leída SOLO de data/raw."""
    path = comun.raw_path(ISO3, "shcp_datos", f"{concepto}.json")
    if not path.exists():
        raise FileNotFoundError(path)
    recs = json.loads(path.read_bytes().decode("utf-8"))["result"]["records"]
    names = {r["nombre"] for r in recs}
    units = {r["unidad_medida"] for r in recs}
    if len(names) != 1 or units != {"Miles de Pesos"}:
        raise ValueError(f"SHCP {concepto}: nombres {names} o unidades {units} inesperados")
    dates, values = [], []
    for r in recs:
        dates.append(pd.Timestamp(int(r["ciclo"]), SHCP_MONTHS[r["mes"].strip().lower()], 1))
        values.append(float(r["monto"]))
    s = pd.Series(values, index=pd.DatetimeIndex(dates), dtype=float).sort_index()
    if s.index.duplicated().any():
        raise ValueError(f"SHCP {concepto}: meses repetidos")
    return names.pop(), s


def shcp_ratio(row: dict) -> pd.Series:
    """RFSP: suma enero-diciembre de los flujos mensuales (solo años con 12 meses).
    SHRFSP: saldo de diciembre. Ambos en miles de pesos → millones, / PIB nominal anual × 100."""
    _, concepto, gdp = shcp_components(row["codigo_fuente"])
    nombre, s = read_shcp(concepto)
    if " ".join(nombre.split()).lower() not in " ".join(row["titulo_fuente"].split()).lower():
        log.warning("%s: el nombre del concepto SHCP cambió\n    config: %s\n    SHCP:   %s",
                    row["nombre_corto"], row["titulo_fuente"], nombre)
    if row["nombre_corto"] == "rfsp_pct_pbi":
        g = s.groupby(s.index.year)
        num = g.sum()[g.count() == 12]
        num.index = pd.to_datetime([f"{y}-01-01" for y in num.index])
    elif row["nombre_corto"] == "shrfsp_pct_pbi":
        num = december_value(s)
    else:
        raise ValueError(f"{row['nombre_corto']}: concepto SHCP sin regla de cálculo")
    pib = annual_from_annualized_quarters(read_sie(gdp, "")[1])
    both = pd.concat([num * 1e-3, pib], axis=1, keys=["num", "pib"]).dropna()
    return 100 * both["num"] / both["pib"]


# --------------------------------------------------------------------------- transformaciones

def annual_from_annualized_quarters(q: pd.Series) -> pd.Series:
    """PIB anual = promedio de los 4 trimestres (niveles a tasa anual). Solo años completos."""
    g = q.groupby(q.index.year)
    full = g.count() == 4
    out = g.mean()[full]
    out.index = pd.to_datetime([f"{y}-01-01" for y in out.index])
    return out


def december_value(m: pd.Series) -> pd.Series:
    d = m[m.index.month == 12]
    d.index = pd.to_datetime([f"{y}-01-01" for y in d.index.year])
    return d


def ratio_to_gdp(numer: pd.Series, gdp_q: pd.Series, numer_factor: float) -> pd.Series:
    gdp = annual_from_annualized_quarters(gdp_q)
    num = december_value(numer) * numer_factor
    both = pd.concat([num, gdp], axis=1, keys=["num", "pib"]).dropna()
    return 100 * both["num"] / both["pib"]


def build_series(row: dict) -> pd.Series:
    name, freq = row["nombre_corto"], row["frecuencia"]
    if row["fuente"] == "inegi_bie":
        return read_inegi(row["codigo_fuente"])
    if row["fuente"] == "shcp_datos":
        return shcp_ratio(row)

    comps = sie_components(row["codigo_fuente"])
    if name == "resultado_fiscal_pct_pbi":                     # SG14 / SR17645
        (_, num), (_, gdp) = read_sie(*comps[0]), read_sie(*comps[1])
        return ratio_to_gdp(num, gdp, 1.0)                     # millones / millones
    if name == "deuda_publica_pct_pbi":                        # SG193 / SR17645
        (_, num), (_, gdp) = read_sie(*comps[0]), read_sie(*comps[1])
        return ratio_to_gdp(num, gdp, 1e3)                     # miles de millones → millones
    if len(comps) != 1:
        raise ValueError(f"{name}: código compuesto sin regla de cálculo")

    meta, s = read_sie(*comps[0])
    src_freq = SIE_FREQ.get(meta["periodicidad"])
    # El nombre puede cambiar si Banxico reutiliza o renombra la clave: avisar.
    titulo = meta.get("Título", "")
    if comps[0][1] == "" and " ".join(titulo.split()) != " ".join(row["titulo_fuente"].split()):
        log.warning("%s: el título del SIE cambió\n    config: %s\n    SIE:    %s",
                    name, row["titulo_fuente"], titulo)

    if name == "pbi_nominal_anual":
        return annual_from_annualized_quarters(s)
    if name in DAILY_TO_MONTHLY:
        if src_freq != "diaria":
            raise ValueError(f"{name}: se esperaba serie diaria y el SIE dice {meta['periodicidad']}")
        how = DAILY_TO_MONTHLY[name]
        s = s.groupby(s.index.to_period("M")).agg(how)
        s.index = s.index.to_timestamp()
        return s
    if src_freq != freq:
        raise ValueError(f"{name}: frecuencia en config {freq} ≠ SIE {meta['periodicidad']}")
    return s * SCALE.get(name, 1.0)


def process(rows: list[dict]) -> int:
    frames, errors = [], 0
    for row in rows:
        try:
            s = build_series(row).dropna()
        except (FileNotFoundError, ValueError, RuntimeError, KeyError) as e:
            log.error("%s: no se pudo procesar (%s)", row["nombre_corto"], e)
            errors += 1
            continue
        if s.empty:
            log.error("%s: sin observaciones", row["nombre_corto"])
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
        log.error("Nada que escribir")
        return errors + 1
    comun.write_interim(ISO3, pd.concat(frames, ignore_index=True))
    return errors


# --------------------------------------------------------------------------- CLI

def select_rows(only: list[str] | None) -> list[dict]:
    if not only:
        return comun.load_series(ISO3)
    # Por nombre se puede pedir también una serie inactiva (p. ej. desempleo con token).
    rows = [r for r in comun.load_series(ISO3, only_active=False) if r["nombre_corto"] in only]
    missing = set(only) - {r["nombre_corto"] for r in rows}
    if missing:
        log.warning("No están en config/series/MEX.csv: %s", ", ".join(sorted(missing)))
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--solo-procesar", action="store_true",
                    help="no descarga; reconstruye el parquet desde data/raw/MEX")
    ap.add_argument("--serie", nargs="+", metavar="NOMBRE_CORTO",
                    help="descargar solo estas series (el procesamiento usa siempre todas las activas)")
    ap.add_argument("--pausa", type=float, default=1.0, help="segundos entre peticiones (mín. 1)")
    args = ap.parse_args(argv)
    # La consola de Windows usa cp1252 y comun.write_interim registra '→': forzar UTF-8.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    comun.setup_logging(ISO3)

    errors = 0
    if not args.solo_procesar:
        rows = select_rows(args.serie)
        log.info("Descarga MEX: %d series", len(rows))
        errors += download(rows, max(args.pausa, 1.0))
    # El parquet se reconstruye siempre con todas las activas (más las pedidas por nombre).
    rows = comun.load_series(ISO3)
    if args.serie:
        names = {r["nombre_corto"] for r in rows}
        rows += [r for r in select_rows(args.serie) if r["nombre_corto"] not in names]
    errors += process(rows)
    log.info("Fin MEX: %d errores", errors)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
