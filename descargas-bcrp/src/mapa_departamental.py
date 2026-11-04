"""Mapa departamental del Perú para los tableros del BCRP (PBI y finanzas públicas).

Lee los límites departamentales de `data/raw/geo/peru_departamental_simple.geojson`, que baja
`descargar_geo.py` (repositorio público juaneladio/peru-geojson, licencia MPL 2.0), los proyecta y
simplifica, y devuelve los trazos SVG por código de departamento (FIRST_IDDP).

Antes vivía en `visual_pbi.py`; se separó el 2026-11-04 para que `visual_finanzas.py` no dependa de
ese script. El resultado es idéntico.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Callable

PROJECT_DIR = Path(__file__).resolve().parents[1]
GEO = PROJECT_DIR / "data" / "raw" / "geo" / "peru_departamental_simple.geojson"


def simplify(points: list[tuple[float, float]], tol: float) -> list[tuple[float, float]]:
    """Douglas-Peucker sobre un anillo ya proyectado (en píxeles)."""
    if len(points) < 4:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        (x1, y1), (x2, y2) = points[a], points[b]
        dx, dy = x2 - x1, y2 - y1
        norm = math.hypot(dx, dy)
        best, bi = -1.0, -1
        for i in range(a + 1, b):
            x0, y0 = points[i]
            # En un anillo cerrado el primer y el último punto coinciden: distancia al punto.
            d = (abs(dy * x0 - dx * y0 + x2 * y1 - y2 * x1) / norm if norm > 1e-9
                 else math.hypot(x0 - x1, y0 - y1))
            if d > best:
                best, bi = d, i
        if best > tol:
            keep[bi] = True
            stack += [(a, bi), (bi, b)]
    return [p for p, k in zip(points, keep) if k]


def build_geo(warn: Callable[[str], None] = print) -> dict | None:
    if not GEO.exists():
        warn("sin límites departamentales (correr descargar_geo.py); se omite el mapa")
        return None
    g = json.loads(GEO.read_text(encoding="utf-8"))
    rings = []
    for f in g["features"]:
        geom = f["geometry"]
        polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
        rings.append((f["properties"]["FIRST_IDDP"], [poly[0] for poly in polys]))
    lons = [x for _, ps in rings for ring in ps for x, _ in ring]
    lats = [y for _, ps in rings for ring in ps for _, y in ring]
    lat0 = math.radians((min(lats) + max(lats)) / 2)
    width = 420.0
    sx = width / ((max(lons) - min(lons)) * math.cos(lat0))
    height = (max(lats) - min(lats)) * sx
    proj = lambda lon, lat: ((lon - min(lons)) * math.cos(lat0) * sx, (max(lats) - lat) * sx)  # noqa: E731
    paths = {}
    for code, polys in rings:
        d = ""
        for ring in polys:
            pts = simplify([proj(x, y) for x, y in ring], 0.35)
            if len(pts) < 4:
                continue
            d += "M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + "Z"
        paths[code] = d
    return {"w": width, "h": round(height, 1), "paths": paths}
