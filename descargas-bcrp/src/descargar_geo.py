"""Descarga los límites departamentales del Perú (GeoJSON) para el mapa del tablero del PBI.

Fuente: repositorio público juaneladio/peru-geojson (GitHub), versión simplificada de los límites
departamentales (25 unidades: 24 departamentos más la Provincia Constitucional del Callao). No es
una fuente oficial: sirve solo para dibujar el mapa; las cifras vienen del INEI.

Guarda el archivo tal cual en `data/raw/geo/` y registra url, bytes y sha256 en
`data/_control/manifest_geo.csv`. Si el archivo ya existe y no cambió, no hace nada.

Uso:
    python descargar_geo.py
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

import requests

PROJECT_DIR = Path(__file__).resolve().parents[1]
URL = "https://raw.githubusercontent.com/juaneladio/peru-geojson/master/peru_departamental_simple.geojson"
DEST = PROJECT_DIR / "data" / "raw" / "geo" / "peru_departamental_simple.geojson"
MANIFEST = PROJECT_DIR / "data" / "_control" / "manifest_geo.csv"


def main() -> int:
    resp = requests.get(URL, timeout=60)
    resp.raise_for_status()
    content = resp.content
    # Control mínimo: tiene que ser un FeatureCollection con 25 polígonos.
    features = json.loads(content.decode("utf-8"))["features"]
    if len(features) != 25:
        raise ValueError(f"se esperaban 25 departamentos y llegaron {len(features)}")
    sha = hashlib.sha256(content).hexdigest()
    old = hashlib.sha256(DEST.read_bytes()).hexdigest() if DEST.exists() else None
    action = "sin_cambios" if old == sha else ("actualizado" if old else "nuevo")
    if action != "sin_cambios":
        DEST.parent.mkdir(parents=True, exist_ok=True)
        DEST.write_bytes(content)
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    new_file = not MANIFEST.exists()
    with MANIFEST.open("a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if new_file:
            w.writerow(["url", "archivo", "bytes", "sha256", "descargado_en", "accion"])
        w.writerow([URL, DEST.relative_to(PROJECT_DIR).as_posix(), len(content), sha,
                    dt.datetime.now().isoformat(timespec="seconds"), action])
    print(f"  {DEST.relative_to(PROJECT_DIR)}: {action} ({len(content) / 1024:.0f} KB, {len(features)} departamentos)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
