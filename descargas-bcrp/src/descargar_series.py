"""Descargador de series estadísticas del BCRP (BCRPData, API pública).

Recorre las series de `config/series.csv`, descarga la historia completa de cada
una y guarda la respuesta de la API tal cual en `data/raw/<frecuencia>/CODIGO.json`.
Si el BCRP revisó datos ya publicados (p. ej. el PBI), la versión anterior se
conserva en la carpeta de historial antes de reemplazarla.

Uso:
    python descargar_series.py                     # corrida normal (todas las activas)
    python descargar_series.py --serie PN01770AM   # solo una o varias series
    python descargar_series.py --catalogo          # además, actualiza docs/catalogo_bcrp.csv
    python descargar_series.py --dry-run           # solo informa, no escribe

Las descargas son secuenciales y con pausa: el sitio del BCRP está detrás de
Imperva, igual que la SBS.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import logging
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import requests

PROJECT_DIR = Path(__file__).resolve().parents[1]
SERIES_CSV = PROJECT_DIR / "config" / "series.csv"
CATALOG_CSV = PROJECT_DIR / "docs" / "catalogo_bcrp.csv"
DEFAULT_DEST = PROJECT_DIR / "data" / "raw"
# Historial, manifest y logs van FUERA de data/raw: Folder.Files de Power BI es
# recursivo y leería las versiones anteriores como si fueran datos vigentes.
DEFAULT_CONTROL = PROJECT_DIR / "data" / "_control"

API_URL = "https://estadisticas.bcrp.gob.pe/estadisticas/series/api"
CATALOG_URL = "https://estadisticas.bcrp.gob.pe/estadisticas/series/metadata"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
# Columnas del catálogo del BCRP, en su orden original, con nombres sin tildes.
CATALOG_FIELDS = ["codigo", "categoria", "grupo", "nombre", "descripcion", "metodologia",
                  "unidad", "escala", "geografia", "fuente", "frecuencia", "fecha_creacion",
                  "grupo_publicacion", "area", "fecha_actualizacion", "fecha_inicio",
                  "fecha_fin", "memo"]

MANIFEST_FIELDS = ["frecuencia", "archivo", "url", "n_obs", "desde", "hasta",
                   "obs_revisadas", "sha256", "descargado_en", "accion"]

log = logging.getLogger("descargador_bcrp")


@dataclass
class Series:
    codigo: str
    frecuencia: str
    tema: str
    nombre_corto: str
    titulo_bcrp: str


def date_range(frecuencia: str, today: dt.date) -> tuple[str, str]:
    """Rango de la consulta: toda la historia hasta el periodo actual.

    La API rellena con 'n.d.' los periodos sin dato, así que no se pide más allá
    de hoy: en las diarias, pedir hasta 2100 genera 70 años de filas vacías.
    """
    if frecuencia == "mensual":
        return "1900-1", f"{today.year}-{today.month}"
    if frecuencia == "trimestral":
        return "1900-1", f"{today.year}-{(today.month - 1) // 3 + 1}"
    if frecuencia == "anual":
        return "1900", str(today.year)
    if frecuencia == "diaria":
        # Las diarias usan años de 2 dígitos ('02.Ene.97'): no pedir antes de 1990.
        return "1990-01-01", today.isoformat()
    raise ValueError(f"Frecuencia desconocida: {frecuencia}")


def observations(payload: dict) -> dict[str, str]:
    """{etiqueta de periodo: valor} sin los 'n.d.' (periodos sin dato)."""
    out = {}
    for p in payload.get("periods", []):
        v = p["values"][0] if p.get("values") else None
        if v not in (None, "", "n.d."):
            out[p["name"]] = v
    return out


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def norm(text: str) -> str:
    return " ".join(text.split()).lower()


class BcrpClient:
    """Cliente HTTP secuencial con pausa y reintentos."""

    def __init__(self, pause: float, retries: int = 4):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.pause = pause
        self.retries = retries

    def get(self, url: str, timeout: int = 120) -> requests.Response:
        for attempt in range(1, self.retries + 1):
            time.sleep(self.pause)
            try:
                r = self.session.get(url, timeout=timeout)
                r.raise_for_status()
                return r
            except requests.RequestException as e:
                if attempt == self.retries:
                    raise
                wait = 5 * attempt
                log.warning("Intento %d falló (%s); reintento en %d s", attempt, e, wait)
                time.sleep(wait)
        raise RuntimeError("inalcanzable")


def load_series(only: set[str] | None) -> list[Series]:
    with SERIES_CSV.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    series = [Series(r["codigo"], r["frecuencia"], r["tema"], r["nombre_corto"], r["titulo_bcrp"])
              for r in rows if r["activo"].strip() == "1"]
    if only:
        series = [s for s in series if s.codigo in only]
        missing = only - {s.codigo for s in series}
        if missing:
            log.warning("No están activas en config/series.csv: %s", ", ".join(sorted(missing)))
    return series


def append_manifest(control: Path, row: dict) -> None:
    path = control / "manifest.csv"
    new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


def update_catalog(client: BcrpClient, dry_run: bool) -> None:
    """Descarga el catálogo completo de BCRPData (~17 mil series) a docs/."""
    r = client.get(CATALOG_URL, timeout=300)
    # El BCRP lo publica en latin-1 y separado por ';', con un ';' final en cada fila.
    reader = csv.reader(io.StringIO(r.content.decode("latin-1")), delimiter=";")
    next(reader)
    rows = [row[:len(CATALOG_FIELDS)] for row in reader if row]
    log.info("Catálogo: %d series", len(rows))
    if dry_run:
        return
    CATALOG_CSV.parent.mkdir(parents=True, exist_ok=True)
    with CATALOG_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(CATALOG_FIELDS)
        w.writerows(rows)


def process_series(client: BcrpClient, s: Series, dest: Path, control: Path,
                   today: dt.date, dry_run: bool) -> str:
    ini, fin = date_range(s.frecuencia, today)
    url = f"{API_URL}/{s.codigo}/json/{ini}/{fin}/esp"
    r = client.get(url)
    try:
        payload = json.loads(r.content.decode("utf-8"))
    except ValueError:
        log.error("%s: la API no devolvió JSON (¿código dado de baja?): %r",
                  s.codigo, r.text[:200])
        return "error"

    # La API devuelve el nombre real de la serie: si el BCRP renombra o reutiliza
    # un código, se avisa en vez de dejar pasar datos con el rótulo viejo.
    api_name = payload["config"]["series"][0]["name"]
    if norm(api_name) != norm(s.titulo_bcrp):
        log.warning("%s: el nombre cambió\n    config: %s\n    API:    %s",
                    s.codigo, s.titulo_bcrp, api_name)

    new_obs = observations(payload)
    if not new_obs:
        log.error("%s: sin observaciones en %s", s.codigo, url)
        return "error"

    path = dest / s.frecuencia / f"{s.codigo}.json"
    revised = 0
    if not path.exists():
        action = "nuevo"
    else:
        old_obs = observations(json.loads(path.read_bytes().decode("utf-8")))
        revised = sum(1 for k, v in old_obs.items() if new_obs.get(k) != v)
        if revised:
            action = "revisado"          # cambió o desapareció algún dato ya publicado
        elif new_obs.keys() != old_obs.keys():
            action = "ampliado"          # solo periodos nuevos
        else:
            action = "sin_cambios"

    periods = list(new_obs)
    log.info("%-10s %-11s %-36s n=%5d  %s → %s  [%s%s]", s.codigo, s.frecuencia,
             s.nombre_corto, len(new_obs), periods[0], periods[-1], action,
             f": {revised} obs" if revised else "")
    if dry_run or action == "sin_cambios":
        return action

    if action == "revisado":
        hist = control / "historial" / s.frecuencia
        hist.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, hist / f"{s.codigo}__{today:%Y%m%d}.json")

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(r.content)
    tmp.replace(path)
    append_manifest(control, {
        "frecuencia": s.frecuencia, "archivo": path.name, "url": url,
        "n_obs": len(new_obs), "desde": periods[0], "hasta": periods[-1],
        "obs_revisadas": revised, "sha256": sha256_bytes(r.content),
        "descargado_en": dt.datetime.now().isoformat(timespec="seconds"), "accion": action,
    })
    return action


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--serie", nargs="+", help="códigos a procesar (por defecto, todas las activas)")
    ap.add_argument("--catalogo", action="store_true", help="actualizar docs/catalogo_bcrp.csv")
    ap.add_argument("--dry-run", action="store_true", help="no escribe nada")
    ap.add_argument("--pausa", type=float, default=1.0, help="segundos entre peticiones")
    ap.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    ap.add_argument("--control", type=Path, default=DEFAULT_CONTROL)
    args = ap.parse_args(argv)

    (args.control / "logs").mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    # La consola de Windows (cp1252) no puede imprimir «→» y el logging lanza un error por línea.
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler(args.control / "logs" / f"{stamp}.log", encoding="utf-8")])

    client = BcrpClient(args.pausa)
    if args.catalogo:
        update_catalog(client, args.dry_run)

    today = dt.date.today()
    series = load_series(set(args.serie) if args.serie else None)
    log.info("Series a procesar: %d%s", len(series), " (dry-run)" if args.dry_run else "")
    counts: dict[str, int] = {}
    for s in series:
        try:
            action = process_series(client, s, args.dest, args.control, today, args.dry_run)
        except requests.RequestException as e:
            log.error("%s: %s", s.codigo, e)
            action = "error"
        counts[action] = counts.get(action, 0) + 1

    log.info("Resumen: %s", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return 1 if counts.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
