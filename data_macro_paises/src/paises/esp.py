"""Descargador de series macroeconómicas de España (solo fuentes oficiales).

Fuentes (ver docs/fuentes/ESP.md):
    bde   Banco de España: servicio web de estadísticas (API JSON, sin clave).
          Tipos de interés (incluidos los del BCE), crédito, M2, tipo de cambio,
          reservas, comercio exterior, balanza de pagos, AAPP, SMI.
    ine   Instituto Nacional de Estadística: API JSON Tempus (sin clave).
          Contabilidad nacional trimestral, IPC, IPI y EPA.

Dos pasos:
    1. descargar: guarda cada respuesta tal cual en data/raw/ESP/<fuente>/.
    2. procesar: lee SOLO data/raw/ESP/ y escribe data/interim/ESP_observaciones.parquet.

Uso:
    python esp.py                              # descarga todo y procesa
    python esp.py --serie ipc_indice m2        # descarga solo esas series (procesa todas)
    python esp.py --solo-procesar              # no usa la red
    python esp.py --pausa 2                    # segundos entre peticiones

`codigo_fuente` admite un sufijo de transformación tras «|», aplicado al procesar:
    x<f>      multiplica por f (p. ej. x0.001: miles de euros → millones)
    sumanual  serie trimestral → anual sumando los 4 trimestres (solo años completos)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import unicodedata
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import comun  # noqa: E402

ISO3 = "ESP"
log = comun.log

BDE_URL = "https://app.bde.es/bierest/resources/srdatosapp/listaSeries"
INE_URL = "https://servicios.ine.es/wstempus/js/ES/DATOS_SERIE/{code}"
# Sin parámetros la API del INE devuelve solo el último dato: se pide un rango amplio.
INE_DATE_RANGE = "19000101:21001231"
# FK_Periodo del INE: 1-12 meses, 19-22 trimestres, 28 año.
INE_QUARTERS = {19: 1, 20: 4, 21: 7, 22: 10}


# =======================================================================================
# Utilidades
# =======================================================================================
def split_code(codigo: str) -> tuple[str, str]:
    base, _, op = codigo.partition("|")
    return base.strip(), op.strip()


def safe_name(code: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", code)


def norm(text: str) -> str:
    """Para comparar títulos: sin tildes, mayúsculas ni puntuación."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def save(fuente: str, filename: str, content: bytes, url: str) -> None:
    action = comun.save_raw(ISO3, fuente, filename, content, url)
    log.info("  %-4s %-62s %9d bytes  [%s]", fuente, filename, len(content), action)


# =======================================================================================
# Paso 1: descarga
# =======================================================================================
def bde_get(client: comun.Client, code: str, rango: str):
    # Los códigos llevan caracteres especiales (#, %, $): requests los codifica en `params`.
    r = client.get(BDE_URL, params={"idioma": "es", "series": code, "rango": rango})
    payload = r.json()
    if not isinstance(payload, list) or not payload:
        raise RuntimeError(f"BdE {code}: respuesta inesperada {str(payload)[:200]}")
    return r, payload[0]


def download_bde(client: comun.Client, code: str, frecuencia: str) -> None:
    if frecuencia != "diaria":
        r, _ = bde_get(client, code, "MAX")
        save("bde", safe_name(code) + ".json", r.content, r.url)
        return
    # Diarias: la API admite como máximo 36 meses o un año concreto, así que se piden
    # año por año desde el inicio de la serie. Solo cambian los archivos de los años recientes.
    r, meta = bde_get(client, code, str(dt.date.today().year))
    first_year = int(meta["fechaInicio"][:4])
    save("bde", f"{safe_name(code)}_{dt.date.today().year}.json", r.content, r.url)
    for year in range(dt.date.today().year - 1, first_year - 1, -1):
        r, _ = bde_get(client, code, str(year))
        save("bde", f"{safe_name(code)}_{year}.json", r.content, r.url)


def download_ine(client: comun.Client, code: str) -> None:
    url = INE_URL.format(code=code)
    r = client.get(url, params={"date": INE_DATE_RANGE})
    payload = r.json()
    if not isinstance(payload, dict) or not payload.get("Data"):
        raise RuntimeError(f"INE {code}: respuesta sin datos {r.text[:200]}")
    save("ine", f"{code}.json", r.content, r.url)


def download(series: list[dict], pause: float) -> int:
    client = comun.Client(pause=pause)
    errors = 0
    done: set[str] = set()
    for s in series:
        code, _ = split_code(s["codigo_fuente"])
        if (s["fuente"], code) in done:
            continue
        done.add((s["fuente"], code))
        try:
            if s["fuente"] == "bde":
                download_bde(client, code, s["frecuencia"])
            elif s["fuente"] == "ine":
                download_ine(client, code)
            else:
                raise ValueError(f"fuente desconocida: {s['fuente']}")
        except Exception as e:  # noqa: BLE001 — se registra y se sigue con la siguiente serie
            errors += 1
            log.error("%s (%s): %s", s["nombre_corto"], code, e)
    return errors


# =======================================================================================
# Paso 2: procesamiento (solo lee data/raw/ESP)
# =======================================================================================
def check_title(s: dict, official: str | None) -> None:
    """Avisa si el organismo cambió el nombre de la serie (código reutilizado o renombrado)."""
    if official and norm(official) != norm(s["titulo_fuente"]):
        log.warning("%s: el título no coincide\n    config: %s\n    fuente: %s",
                    s["nombre_corto"], s["titulo_fuente"], official)


def read_bde(s: dict, code: str, dropped: list) -> pd.DataFrame:
    folder = comun.raw_path(ISO3, "bde", "x").parent
    if s["frecuencia"] == "diaria":
        paths = sorted(folder.glob(f"{safe_name(code)}_[12][0-9][0-9][0-9].json"))
    else:
        paths = [folder / f"{safe_name(code)}.json"]
    if not paths or not paths[0].exists():
        raise FileNotFoundError(paths[0] if paths else folder / safe_name(code))
    recs, official = [], None
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))[0]
        info = {i["titulo"]: i["descripcion"] for i in payload.get("informacion") or []}
        official = info.get("Nombre") or official
        # En las diarias, la petición de un año trae también el 31-dic del año anterior:
        # cada archivo aporta solo las fechas de su propio año.
        year = path.stem.rsplit("_", 1)[1] if s["frecuencia"] == "diaria" else None
        # Las fechas vienen como '2026-09-01T08:15:00Z' (día 1 del periodo; la hora no
        # significa nada) y en orden descendente.
        for fecha, valor in zip(payload["fechas"], payload["valores"]):
            if year and fecha[:4] != year:
                continue
            if not isinstance(valor, (int, float)) or isinstance(valor, bool):
                dropped.append((s["nombre_corto"], fecha[:10], valor))
                continue
            recs.append((fecha[:10], float(valor)))
    check_title(s, official)
    return pd.DataFrame(recs, columns=["fecha", "valor"])


def read_ine(s: dict, code: str, dropped: list) -> pd.DataFrame:
    payload = json.loads(comun.raw_path(ISO3, "ine", f"{code}.json").read_text(encoding="utf-8"))
    check_title(s, payload.get("Nombre"))
    recs = []
    for d in payload["Data"]:
        # 'Fecha' falta en algunos registros antiguos: el periodo sale de Anyo + FK_Periodo.
        year, per = int(d["Anyo"]), int(d["FK_Periodo"])
        if 1 <= per <= 12:
            fecha = dt.date(year, per, 1)
        elif per in INE_QUARTERS:
            fecha = dt.date(year, INE_QUARTERS[per], 1)
        elif per == 28:
            fecha = dt.date(year, 1, 1)
        else:
            raise ValueError(f"{code}: FK_Periodo desconocido {per}")
        valor = d.get("Valor")
        if d.get("Secreto") or not isinstance(valor, (int, float)) or isinstance(valor, bool):
            dropped.append((s["nombre_corto"], fecha.isoformat(), valor))
            continue
        recs.append((fecha, float(valor)))
    return pd.DataFrame(recs, columns=["fecha", "valor"])


def transform(df: pd.DataFrame, op: str) -> pd.DataFrame:
    if not op:
        return df
    if op.startswith("x"):
        return df.assign(valor=df["valor"] * float(op[1:]))
    if op == "sumanual":
        # Trimestral → anual sumando los 4 trimestres; los años incompletos se descartan.
        fecha = pd.to_datetime(df["fecha"])
        g = df.assign(anio=fecha.dt.year).groupby("anio")["valor"].agg(["sum", "count"])
        incomplete = g.index[g["count"] != 4].tolist()
        if incomplete:
            log.info("  sumanual: años incompletos descartados %s", incomplete)
        g = g[g["count"] == 4]
        return pd.DataFrame({"fecha": pd.to_datetime([f"{y}-01-01" for y in g.index]),
                             "valor": g["sum"].to_numpy()})
    raise ValueError(f"Transformación no soportada: {op}")


def process() -> Path:
    series = comun.load_series(ISO3)
    dropped: list[tuple] = []
    frames = []
    for s in series:
        code, op = split_code(s["codigo_fuente"])
        reader = {"bde": read_bde, "ine": read_ine}[s["fuente"]]
        try:
            df = reader(s, code, dropped)
        except FileNotFoundError as e:
            log.error("%s: falta el archivo crudo (%s); ¿se descargó?", s["nombre_corto"], e)
            continue
        if df.empty:
            log.error("%s: sin observaciones", s["nombre_corto"])
            continue
        df = transform(df, op)
        df["fecha"] = comun.period_start(df["fecha"], s["frecuencia"])
        dup = df.duplicated("fecha")
        if dup.any():
            raise ValueError(f"{s['nombre_corto']}: {dup.sum()} periodos repetidos tras normalizar fechas")
        for col in ("fuente", "codigo_fuente", "nombre_corto", "indicador_comun",
                    "frecuencia", "unidad"):
            df[col] = s[col]
        df["pais"] = ISO3
        frames.append(df)
    # Valores nulos o no numéricos: no se imputan, se descartan y se dejan en el log.
    by_series: dict[str, list] = {}
    for name, fecha, valor in dropped:
        by_series.setdefault(name, []).append(f"{fecha}={valor!r}")
    for name, items in by_series.items():
        log.info("  descartados (sin dato) %s: %d, p. ej. %s", name, len(items), ", ".join(items[:4]))
    return comun.write_interim(ISO3, pd.concat(frames, ignore_index=True))


def main(argv: list[str] | None = None) -> int:
    # La consola de Windows (cp1252) no puede imprimir algunos caracteres del log de
    # comun.write_interim y de esta ayuda ('→'): se reemplazan en pantalla; el archivo de log queda en UTF-8.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--solo-procesar", action="store_true",
                    help="no descarga: solo procesa lo que ya está en data/raw/ESP")
    ap.add_argument("--serie", nargs="+", metavar="NOMBRE_CORTO",
                    help="descargar solo estas series (el procesamiento siempre es completo)")
    ap.add_argument("--pausa", type=float, default=1.0, help="segundos entre peticiones (≥ 1)")
    args = ap.parse_args(argv)

    comun.setup_logging(ISO3)
    errors = 0
    if not args.solo_procesar:
        series = comun.load_series(ISO3)
        if args.serie:
            wanted = set(args.serie)
            missing = wanted - {s["nombre_corto"] for s in series}
            if missing:
                log.warning("No están activas en config/series/ESP.csv: %s", ", ".join(sorted(missing)))
            series = [s for s in series if s["nombre_corto"] in wanted]
        log.info("Descargando %d series de ESP", len(series))
        errors = download(series, max(args.pausa, 1.0))
    log.info("Procesando data/raw/ESP")
    process()
    if errors:
        log.error("Terminó con %d errores de descarga (ver arriba)", errors)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
