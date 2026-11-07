"""Perú: series del BCRP (BCRPData, API pública sin clave) y del INEI.

Misma lógica que el proyecto hermano `descargas-bcrp` (que tiene 118 series y el
catálogo completo), reducida a los indicadores comunes y algunas series propias.

Fuente `inei`: el IPC a nivel nacional no está en BCRPData (solo el de Lima). Se toma
del Excel del INEI enlazado en su página de índices de precios; el nombre del archivo
cambia cada mes (`..._nivel_nacional_set26.xlsx`), así que se busca el enlace vigente
y se guarda con nombre estable. `codigo_fuente` = `archivo|hoja|columna`.

Uso:
    python per.py                      # descargar + procesar
    python per.py --solo-procesar      # solo rehacer data/interim desde data/raw
    python per.py --serie ipc_indice tasa_politica
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import comun  # noqa: E402

ISO3 = "PER"
FUENTE = "bcrp"
API_URL = "https://estadisticas.bcrp.gob.pe/estadisticas/series/api"
MONTHS = {m: i + 1 for i, m in enumerate(
    ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"])}
MONTHS["set"] = 9  # el BCRP a veces escribe «Set.» por setiembre

INEI_BASE = "https://www.inei.gob.pe"
INEI_PAGE = INEI_BASE + "/estadisticas/indice-tematico/price-indexes/"
# Archivo estable en data/raw/PER/inei -> patrón del enlace vigente en INEI_PAGE.
# Desde nov-2026 el INEI agrega a veces un sufijo de versión («..._oct26_1.xlsx»): se acepta `_N` opcional.
INEI_FILES = {
    "n02_ipc_nacional.xlsx":
        r"/media/MenuRecursivo/indices_tematicos/n02_indice-precios_al_consumidor-nivel_nacional_[a-z]+\d{2}(?:_\d+)?\.xlsx",
}

log = comun.log


def date_range(frecuencia: str, today: dt.date) -> tuple[str, str]:
    """Toda la historia hasta hoy. Sin fechas la API devuelve solo 5 años, y
    rellena con 'n.d.' hasta la fecha pedida: no pedir más allá de hoy."""
    if frecuencia == "mensual":
        return "1900-1", f"{today.year}-{today.month}"
    if frecuencia == "trimestral":
        return "1900-1", f"{today.year}-{(today.month - 1) // 3 + 1}"
    if frecuencia == "anual":
        return "1900", str(today.year)
    # Las diarias usan años de 2 dígitos ('02.Ene.97'): no pedir antes de 1990.
    return "1990-01-01", today.isoformat()


def full_year(yy: str, today: dt.date) -> int:
    if len(yy) == 4:
        return int(yy)
    y = int(yy)
    return 2000 + y if y <= today.year % 100 else 1900 + y


def parse_period(label: str, frecuencia: str, today: dt.date) -> dt.date:
    if frecuencia == "mensual":            # 'Ene.1994'
        mes, anio = label.split(".")
        return dt.date(full_year(anio, today), MONTHS[mes[:3].lower()], 1)
    if frecuencia == "trimestral":         # 'T1.80'
        trim, anio = label.split(".")
        return dt.date(full_year(anio, today), 3 * int(trim[1]) - 2, 1)
    if frecuencia == "anual":              # '1922'
        return dt.date(int(label), 1, 1)
    dia, mes, anio = label.split(".")      # '02.Ene.97'
    return dt.date(full_year(anio, today), MONTHS[mes[:3].lower()], int(dia))


def download_inei(series: list[dict], client: comun.Client) -> None:
    files = {s["codigo_fuente"].split("|")[0] for s in series}
    if not files:
        return
    try:
        html = client.get(INEI_PAGE).text
    except Exception as e:  # noqa: BLE001
        log.error("INEI: no se pudo leer %s: %s", INEI_PAGE, e)
        return
    for fn in sorted(files):
        try:
            links = re.findall(INEI_FILES[fn], html)
            if not links:
                raise ValueError(f"no se encontró el enlace a {fn} en {INEI_PAGE}")
            url = INEI_BASE + links[0]
            r = client.get(url)
            if not r.content.startswith(b"PK"):
                raise ValueError(f"{url} no es un .xlsx")
            pd.read_excel(io.BytesIO(r.content), sheet_name=None, header=None)  # valida
        except Exception as e:  # noqa: BLE001
            log.error("INEI %s: %s", fn, e)
            continue
        action = comun.save_raw(ISO3, "inei", fn, r.content, url)
        log.info("inei       %-30s %s [%s]", fn, links[0].rsplit("/", 1)[-1], action)


def inei_series(s: dict, today: dt.date) -> pd.DataFrame:
    """Cuadro del INEI: fila 'Año | Mes | Índice | Mensual | Acumulada | Anual'; el año
    solo aparece en enero (se rellena hacia abajo) y '-' es dato no disponible."""
    archivo, hoja, columna = s["codigo_fuente"].split("|")
    raw = pd.read_excel(comun.raw_path(ISO3, "inei", archivo), sheet_name=hoja, header=None)
    titulo = " ".join(str(v) for v in raw.iloc[:3, 0] if isinstance(v, str))
    if "nivel nacional" not in titulo.lower():
        raise ValueError(f"{archivo}/{hoja}: el título no es el del IPC nacional ({titulo!r})")
    hdr = next(i for i, v in raw[0].items() if str(v).strip().lower() == "año")
    col = next(c for c, v in raw.iloc[hdr].items() if str(v).strip().lower() == columna.lower())
    body = raw.iloc[hdr + 1:]
    years = pd.to_numeric(body[0], errors="coerce").ffill()
    recs = []
    for i, mes in body[1].items():
        if not isinstance(mes, str) or mes.strip()[:3].lower() not in MONTHS or pd.isna(years[i]):
            continue
        v = pd.to_numeric(body.at[i, col], errors="coerce")
        if pd.isna(v):
            continue
        recs.append({"fecha": dt.date(int(years[i]), MONTHS[mes.strip()[:3].lower()], 1), "valor": float(v)})
    df = pd.DataFrame(recs)
    if df.fecha.duplicated().any():
        raise ValueError(f"{s['nombre_corto']}: meses repetidos en {archivo}/{hoja}")
    gaps = pd.to_datetime(df.fecha).diff().dropna() > pd.Timedelta(days=31)
    if gaps.any():
        raise ValueError(f"{s['nombre_corto']}: huecos en la serie mensual")
    return df


def download(series: list[dict], client: comun.Client, today: dt.date) -> None:
    download_inei([s for s in series if s["fuente"] == "inei"], client)
    for s in series:
        if s["fuente"] != FUENTE:
            continue
        ini, fin = date_range(s["frecuencia"], today)
        url = f"{API_URL}/{s['codigo_fuente']}/json/{ini}/{fin}/esp"
        try:
            r = client.get(url)
            json.loads(r.content.decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            log.error("%s: %s", s["codigo_fuente"], e)
            continue
        action = comun.save_raw(ISO3, FUENTE, f"{s['codigo_fuente']}.json", r.content, url)
        log.info("%-10s %-30s [%s]", s["codigo_fuente"], s["nombre_corto"], action)


def process(series: list[dict], today: dt.date) -> None:
    frames = []
    for s in series:
        if s["fuente"] == "inei":
            try:
                df = inei_series(s, today)
            except FileNotFoundError as e:
                log.warning("falta %s", e)
                continue
            for col in ("fuente", "codigo_fuente", "nombre_corto", "indicador_comun", "frecuencia", "unidad"):
                df[col] = s[col]
            frames.append(df)
            continue
        path = comun.raw_path(ISO3, FUENTE, f"{s['codigo_fuente']}.json")
        if not path.exists():
            log.warning("falta %s", path.name)
            continue
        payload = json.loads(path.read_bytes().decode("utf-8"))
        api_name = payload["config"]["series"][0]["name"]
        if " ".join(api_name.split()).lower() != " ".join(s["titulo_fuente"].split()).lower():
            log.warning("%s: el nombre cambió\n    config: %s\n    API:    %s",
                        s["codigo_fuente"], s["titulo_fuente"], api_name)
        recs = []
        for p in payload["periods"]:
            v = p["values"][0] if p.get("values") else None
            if v in (None, "", "n.d."):
                continue
            try:
                value = float(v)
            except ValueError:
                log.warning("%s %s: valor no numérico %r (queda como faltante)",
                            s["codigo_fuente"], p["name"], v)
                continue
            recs.append({"fecha": parse_period(p["name"], s["frecuencia"], today), "valor": value})
        df = pd.DataFrame(recs)
        for col in ("fuente", "codigo_fuente", "nombre_corto", "indicador_comun", "frecuencia", "unidad"):
            df[col] = s[col]
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    out["pais"] = ISO3
    comun.write_interim(ISO3, out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--solo-procesar", action="store_true")
    ap.add_argument("--serie", nargs="+", help="nombre_corto de las series a descargar")
    ap.add_argument("--pausa", type=float, default=1.0)
    args = ap.parse_args(argv)

    comun.setup_logging(ISO3)
    today = dt.date.today()
    series = comun.load_series(ISO3)
    if not args.solo_procesar:
        todo = [s for s in series if not args.serie or s["nombre_corto"] in args.serie]
        download(todo, comun.Client(pause=args.pausa), today)
    process(series, today)
    return 0


if __name__ == "__main__":
    sys.exit(main())
