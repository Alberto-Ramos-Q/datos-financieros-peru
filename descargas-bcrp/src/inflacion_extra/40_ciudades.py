"""Extensión «ciudades» del tablero de inflación: inflación por ciudades del IPC nacional del INEI.

Lee `data/processed/inei_ipc_ciudades.csv`, que arma `src/descargar_ipc_ciudades.py` desde los informes
mensuales de precios del INEI (cuadro «Variación porcentual del IPC Nacional y de Principales Ciudades»).
Devuelve, para cada mes, la variación mensual, acumulada y de 12 meses de las 26 ciudades y del promedio
nacional, más el mapa departamental (geometría de `mapa_departamental.py`) con la ubicación de cada ciudad.

Controles (se imprimen en consola y, si fallan, van como aviso):
  - el promedio nacional del cuadro frente al IPC nacional de `../data_macro_paises` (ctx["comp"]);
  - Lima Metropolitana del cuadro frente al IPC de Lima de BCRPData (ctx["m"]);
  - cada ciudad cae dentro de su departamento en el mapa.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pandas as pd

KEY = "ciudades"

# Ciudad -> código de departamento (FIRST_IDDP del GeoJSON) y ubicación aproximada (lat, lon) de la
# ciudad, solo para dibujar el punto en el mapa (no es una cifra del tablero).
CITY_GEO = {
    "Abancay": ("03", -13.636, -72.881), "Arequipa": ("04", -16.399, -71.537),
    "Ayacucho": ("05", -13.160, -74.226), "Cajamarca": ("06", -7.164, -78.500),
    "Cerro de Pasco": ("19", -10.683, -76.256), "Chachapoyas": ("01", -6.231, -77.869),
    "Chiclayo": ("14", -6.771, -79.841), "Chimbote": ("02", -9.075, -78.594),
    "Cusco": ("08", -13.532, -71.967), "Huancavelica": ("09", -12.787, -74.973),
    "Huancayo": ("12", -12.065, -75.205), "Huánuco": ("10", -9.930, -76.242),
    "Huaraz": ("02", -9.527, -77.528), "Ica": ("11", -14.068, -75.729),
    "Iquitos": ("16", -3.749, -73.254), "Lima Metropolitana": ("15", -12.046, -77.043),
    "Moquegua": ("18", -17.194, -70.935), "Moyobamba": ("22", -6.034, -76.972),
    "Piura": ("20", -5.194, -80.632), "Pucallpa": ("25", -8.379, -74.554),
    "Puerto Maldonado": ("17", -12.593, -69.189), "Puno": ("21", -15.840, -70.022),
    "Tacna": ("23", -18.006, -70.246), "Tarapoto": ("22", -6.482, -76.373),
    "Trujillo": ("13", -8.112, -79.029), "Tumbes": ("24", -3.567, -80.451),
}
NATIONAL = "Nacional"
LIMA = "Lima Metropolitana"
TOL = 0.015   # pp: las cifras del INEI vienen redondeadas a 2 decimales


def num(v, nd: int = 2):
    return None if v is None or pd.isna(v) else round(float(v), nd)


def mkey(ts) -> str:
    return pd.Timestamp(ts).strftime("%Y-%m")


def point_in_ring(x: float, y: float, ring: list) -> bool:
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def build_map(project_dir: Path, warn) -> dict | None:
    """Trazos departamentales (los mismos del tablero del PBI) y puntos de las ciudades con la misma proyección."""
    sys.path.insert(0, str(project_dir / "src"))
    try:
        import mapa_departamental as md
    except Exception as e:  # noqa: BLE001
        warn(f"ciudades: no se pudo importar mapa_departamental ({e}); se omite el mapa")
        return None
    geo = md.build_geo(warn)
    if geo is None:
        return None
    g = json.loads(md.GEO.read_text(encoding="utf-8"))
    polys_by_dep: dict[str, list] = {}
    for f in g["features"]:
        geom = f["geometry"]
        polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
        polys_by_dep[f["properties"]["FIRST_IDDP"]] = [p[0] for p in polys]
    lons = [x for ps in polys_by_dep.values() for r in ps for x, _ in r]
    lats = [y for ps in polys_by_dep.values() for r in ps for _, y in r]
    # Misma proyección que mapa_departamental.build_geo.
    lat0 = math.radians((min(lats) + max(lats)) / 2)
    sx = geo["w"] / ((max(lons) - min(lons)) * math.cos(lat0))
    proj = lambda lon, lat: ((lon - min(lons)) * math.cos(lat0) * sx, (max(lats) - lat) * sx)  # noqa: E731
    pts = {}
    outside = []
    for city, (dep, lat, lon) in CITY_GEO.items():
        x, y = proj(lon, lat)
        pts[city] = [round(x, 1), round(y, 1)]
        if not any(point_in_ring(lon, lat, [tuple(p) for p in ring]) for ring in polys_by_dep.get(dep, [])):
            outside.append(city)
    if outside:
        warn("ciudades: puntos fuera de su departamento en el mapa: " + ", ".join(outside))
    # Lima Metropolitana incluye el Callao: ambos departamentos se dibujan como zona del dato de Lima.
    return {"w": geo["w"], "h": geo["h"], "paths": geo["paths"], "pts": pts}


def validate(df: pd.DataFrame, ctx: dict) -> dict:
    """Compara el promedio nacional y Lima del cuadro con las series que ya usa el tablero."""
    out = {}
    warn = ctx["warn"]
    nat = df[df.ciudad == NATIONAL].set_index("fecha")
    comp = ctx.get("comp")
    if comp is not None and "nacional" in comp:
        n = comp["nacional"].copy()
        n["fecha"] = pd.to_datetime(n["fecha"]).dt.to_period("M").dt.to_timestamp()
        n = n.set_index("fecha")
        j = nat.join(n[["ipc_nacional_var_mensual", "ipc_nacional_var12m"]], how="inner")
        d12 = (j.var_12m - j.ipc_nacional_var12m).abs()
        dm = (j.var_mensual - j.ipc_nacional_var_mensual).abs()
        out["nac"] = {"n": int(d12.notna().sum()), "max12": num(d12.max(), 3), "maxm": num(dm.max(), 3),
                      "desde": mkey(j.index.min()), "hasta": mkey(j.index.max())}
        print(f"  ciudades: nacional del cuadro vs IPC nacional de data_macro_paises: {out['nac']['n']} meses, "
              f"dif. máx. 12m {out['nac']['max12']} pp, mensual {out['nac']['maxm']} pp")
        bad = j[(d12 > TOL) | (dm > TOL)]
        if not bad.empty:
            warn(f"ciudades: el nacional del cuadro difiere del IPC nacional en {len(bad)} meses "
                 f"(p. ej. {mkey(bad.index[0])})")
    m = ctx.get("m")
    if m is not None and "ipc_var12m" in m.columns:
        lima = df[df.ciudad == LIMA].set_index("fecha")
        j = lima.join(m[["ipc_var12m", "ipc_var_mensual"]], how="inner")
        d12 = (j.var_12m - j.ipc_var12m).abs()
        dm = (j.var_mensual - j.ipc_var_mensual).abs()
        out["lima"] = {"n": int(d12.notna().sum()), "max12": num(d12.max(), 3), "maxm": num(dm.max(), 3)}
        print(f"  ciudades: Lima del cuadro vs IPC de Lima de BCRPData: {out['lima']['n']} meses, "
              f"dif. máx. 12m {out['lima']['max12']} pp, mensual {out['lima']['maxm']} pp")
        bad = j[(d12 > TOL) | (dm > TOL)]
        if not bad.empty:
            warn(f"ciudades: Lima del cuadro difiere del IPC de Lima del BCRP en {len(bad)} meses "
                 f"(p. ej. {mkey(bad.index[0])})")
    return out


def build(ctx: dict) -> dict | None:
    project_dir = Path(ctx["project_dir"])
    warn = ctx["warn"]
    path = project_dir / "data" / "processed" / "inei_ipc_ciudades.csv"
    if not path.exists():
        warn("ciudades: falta data/processed/inei_ipc_ciudades.csv (correr src/descargar_ipc_ciudades.py)")
        return None
    df = pd.read_csv(path, parse_dates=["fecha"], encoding="utf-8-sig")
    cities = [c for c in CITY_GEO if c in set(df.ciudad)]
    if len(cities) < len(CITY_GEO) or NATIONAL not in set(df.ciudad):
        warn(f"ciudades: el cuadro tiene {len(cities)} de {len(CITY_GEO)} ciudades")
    names = [NATIONAL] + cities
    months = pd.date_range(df.fecha.min(), df.fecha.max(), freq="MS")
    full = df.set_index(["fecha", "ciudad"]).sort_index()
    have = set(df.fecha)
    missing = [mkey(t) for t in months if t not in have]
    if missing:
        warn(f"ciudades: meses sin cuadro: {', '.join(missing)} (se muestran vacíos en la tabla)")

    def col(name: str, c: str) -> list:
        s = full[c].xs(name, level="ciudad").reindex(months) if name in set(df.ciudad) else pd.Series(index=months)
        return [num(v) for v in s.values]

    data = {
        "names": names,
        "months": [mkey(t) for t in months],
        "v12": {n: col(n, "var_12m") for n in names},
        "vm": {n: col(n, "var_mensual") for n in names},
        "va": {n: col(n, "var_acumulada") for n in names},
        "last": mkey(df.fecha.max()),
        "map": build_map(project_dir, warn),
        "check": validate(df, ctx),
        "fuente": "INEI, Informe de Precios (Informe técnico «Variación de los Indicadores de Precios de la "
                  "Economía»), cuadro «Variación porcentual del Índice de Precios al Consumidor Nacional y de "
                  "Principales Ciudades».",
        "url": "https://www.inei.gob.pe/biblioteca-virtual/boletines/informe-de-precios/1/",
        "last_url": str(df.loc[df.fecha == df.fecha.max(), "url"].iloc[0]),
    }
    # Primer mes con variación de 12 meses en todas las ciudades y en el nacional (el nacional, desde 2013).
    ok = [i for i, _ in enumerate(months) if all(data["v12"][n][i] is not None for n in names)]
    data["first12"] = data["months"][ok[0]] if ok else None
    print(f"  ciudades: {len(cities)} ciudades, {data['months'][0]} a {data['last']}"
          f"{'' if data['map'] else ' (sin mapa)'}")
    return data
