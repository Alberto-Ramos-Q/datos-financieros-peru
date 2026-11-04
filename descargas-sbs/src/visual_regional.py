"""Genera `outputs/creditos_regional.html`: tablero público del crédito por departamento.

Lee `data/processed/boletin/creditos-departamento.parquet` (correr antes `leer_boletin.py`): los
cuadros «Estructura de los Créditos Directos por Departamento» (B-2349, B-3228, C-1223, C-2223 y
C-4219), que dan el % del crédito directo de cada entidad por departamento y su TOTAL en miles de
soles. El monto por departamento es `creditos_directos_calculado` (% × TOTAL / 100).

- Agregados (cada subsistema y el sistema = los 5 subsistemas) = suma de entidades por departamento.
  Se controla contra la fila TOTAL que publica la SBS (la diferencia tiene que ser 0 salvo la
  imputación de abajo).
- «Sucursales en el Exterior» (solo banca: BCP toda la serie; Interbank y Scotiabank al inicio) no
  entra al total del Perú: el mapa y los totales nacionales son la suma de los 24 departamentos y el
  Callao. El exterior se informa aparte.
- Mibanco 2023-10 sale con «-» en toda la fila (ni % ni TOTAL) y el total de banca no lo incluye.
  Se imputa: créditos directos del ranking de ese mes (`panel_entidad_mes.parquet`) repartidos con
  el promedio de su estructura por departamento de 2023-09 y 2023-11. Va marcado en los datos (`imp`).
- Cifras repetidas de otro mes (2026-11-03, `errores_origen.RANKING_REPEATS`): en 9 entidad-mes la SBS repite en
  este cuadro la distribución del mes anterior (CMAC Pisco 2014-01 → 04, CRAC Señor de Luren 2015-05, CRAC Chavín /
  Raíz 2016-03 y 04, Financiera TFC 2019-11, CMAC Sullana 2024-06; las nueve con la nota «La información de ...
  corresponde al ...»). La serie de la ENTIDAD (`ent`: T y D) queda sin dato ese mes (`source_repeat_mask(d,
  "creditos-departamento")`); los agregados por subsistema y sistema, y el control contra la fila TOTAL, siguen con
  las cifras publicadas (la SBS las suma en su total). La página recibe la lista en `rep` ([mes, «subsistema/entidad»,
  mes repetido, «fila», motivo, acción]): la ficha, el mapa y las tablas de la entidad muestran el último dato válido
  con su mes y el motivo; la entidad no entra en «Quién presta» ese mes (con nota); y el IHH y el número de
  entidades del subsistema y del sistema quedan sin dato ese mes si la entidad pesa (acción «blank_month», mismo
  criterio que el tablero de concentración), con el último dato válido en las fichas y tablas; con Pisco
  («drop_entity», 0,4 % de las CMAC) se calculan sin ella.
- Crecimiento anual: nominal (el cuadro no separa monedas, así que no se puede aislar el tipo de
  cambio).
- Por habitante y sobre el VAB (no es el PBI: el INEI no reparte impuestos ni derechos de importación
  por departamento): insumo `config/insumos_departamentales.csv` (población al 30 de junio y VAB a
  precios corrientes del INEI, con su URL de origen), que se arma con `--insumos` desde el proyecto
  hermano `../descargas-inei` (solo lectura). En el cuadro del INEI la fila «Lima» incluye al Callao;
  el insumo usa Lima = Provincia de Lima + Región Lima (comprobado: los 25 suman el VAB del país).
- Mapa: `config/geo/departamentos_svg.json`, límites departamentales del INEI (2007) publicados en
  el repositorio juaneladio/peru-geojson (licencia MPL-2.0), simplificados sin romper los bordes
  compartidos (Douglas–Peucker por arco) y proyectados (equirrectangular con el coseno de la latitud
  media). Se arma con `--geo` (descarga el GeoJSON a `config/geo/` si no está).

Genera además `outputs/creditos_regional_artifact.html`, la versión para publicar como Artifact de
claude.ai (sin <html>/<head>/<body>).

Uso:
    python visual_regional.py              # tablero (arma los insumos que falten)
    python visual_regional.py --insumos    # rehace config/insumos_departamentales.csv
    python visual_regional.py --geo        # vuelve a bajar y simplificar la geometría
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from visual_mora import SUBSYSTEMS, artifact_version, month_key, month_range, read_table
from errores_origen import repeat_footnote, source_repeat_mask, source_repeats

TEMA = "creditos-departamento"

PROJECT_DIR = Path(__file__).resolve().parents[1]
BOLETIN = PROJECT_DIR / "data" / "processed" / "boletin"
PANEL = PROJECT_DIR / "data" / "processed" / "panel_entidad_mes.parquet"
ENTIDADES = PROJECT_DIR / "config" / "entidades" / "entidad.csv"
INPUTS = PROJECT_DIR / "config" / "insumos_departamentales.csv"
GEO_DIR = PROJECT_DIR / "config" / "geo"
GEO_SRC = GEO_DIR / "peru_departamental_simple.geojson"
GEO_OUT = GEO_DIR / "departamentos_svg.json"
INEI_DIR = PROJECT_DIR.parent / "descargas-inei" / "data" / "processed"
TEMPLATE = PROJECT_DIR / "src" / "plantillas" / "regional.html"
OUT = PROJECT_DIR / "outputs" / "creditos_regional.html"
OUT_ARTIFACT = PROJECT_DIR / "outputs" / "creditos_regional_artifact.html"
PLACEHOLDER = "/*__DATA__*/null"

GEO_URL = "https://raw.githubusercontent.com/juaneladio/peru-geojson/master/peru_departamental_simple.geojson"
GEO_REPO = "https://github.com/juaneladio/peru-geojson"
POP_URL = "https://www.inei.gob.pe/media/MenuRecursivo/indices_tematicos/proy_03_4.xlsx"
VAB_URL = "https://www.inei.gob.pe/media/MenuRecursivo/indices_tematicos/pbi_peru_17.xlsx"

# Ubigeo del INEI → clave del lector del boletín y nombre con tildes.
DEPARTMENTS = [
    ("01", "amazonas", "Amazonas"), ("02", "ancash", "Áncash"), ("03", "apurimac", "Apurímac"),
    ("04", "arequipa", "Arequipa"), ("05", "ayacucho", "Ayacucho"), ("06", "cajamarca", "Cajamarca"),
    ("07", "callao", "Callao"), ("08", "cusco", "Cusco"), ("09", "huancavelica", "Huancavelica"),
    ("10", "huanuco", "Huánuco"), ("11", "ica", "Ica"), ("12", "junin", "Junín"),
    ("13", "la_libertad", "La Libertad"), ("14", "lambayeque", "Lambayeque"), ("15", "lima", "Lima"),
    ("16", "loreto", "Loreto"), ("17", "madre_de_dios", "Madre de Dios"), ("18", "moquegua", "Moquegua"),
    ("19", "pasco", "Pasco"), ("20", "piura", "Piura"), ("21", "puno", "Puno"),
    ("22", "san_martin", "San Martín"), ("23", "tacna", "Tacna"), ("24", "tumbes", "Tumbes"),
    ("25", "ucayali", "Ucayali"),
]
DEPT_KEYS = [k for _, k, _ in DEPARTMENTS]
EXTERIOR = "exterior"
IMPUTE = [("banca-multiple", "mibanco", 202310, (202309, 202311))]
FIRST_YEAR = 2010  # primer año de la historia del boletín (2010-07); antes 2015

# Geometría: tolerancia de Douglas–Peucker en unidades del mapa (ancho = 1000).
MAP_W = 1000.0
SIMPLIFY_TOL = 0.6


def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower().strip()
    return s.replace(" ", "_")


# ---------------------------------------------------------------- geometría
def download_geo() -> None:
    import requests
    resp = requests.get(GEO_URL, timeout=60)
    resp.raise_for_status()
    feats = json.loads(resp.content.decode("utf-8"))["features"]
    if len(feats) != 25:
        raise ValueError(f"se esperaban 25 departamentos y llegaron {len(feats)}")
    GEO_DIR.mkdir(parents=True, exist_ok=True)
    GEO_SRC.write_bytes(resp.content)
    print(f"  Bajado {GEO_SRC.name} ({len(resp.content) / 1024:.0f} KB, sha256 "
          f"{hashlib.sha256(resp.content).hexdigest()[:12]}...)")


def _dp(pts: list[tuple[float, float]], tol: float) -> list[tuple[float, float]]:
    """Douglas–Peucker iterativo; conserva los extremos."""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        (x1, y1), (x2, y2) = pts[a], pts[b]
        dx, dy = x2 - x1, y2 - y1
        norm = math.hypot(dx, dy)
        best, idx = -1.0, -1
        for i in range(a + 1, b):
            x0, y0 = pts[i]
            d = abs(dy * x0 - dx * y0 + x2 * y1 - y2 * x1) / norm if norm else math.hypot(x0 - x1, y0 - y1)
            if d > best:
                best, idx = d, i
        if best > tol:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(pts, keep) if k]


def build_geo() -> dict:
    """Proyecta y simplifica los límites. La simplificación es por arco (tramo de borde entre dos
    nudos donde cambia el vecino), igual en los dos departamentos que lo comparten: no abre huecos."""
    g = json.loads(GEO_SRC.read_text(encoding="utf-8"))
    rings: list[tuple[str, int, list[tuple[float, float]]]] = []   # (depto, n.º de anillo en el depto, puntos)
    lon_all, lat_all = [], []
    by_code = {u: k for u, k, _ in DEPARTMENTS}
    for f in g["features"]:
        dep = by_code[f["properties"]["FIRST_IDDP"]]
        geo = f["geometry"]
        polys = geo["coordinates"] if geo["type"] == "MultiPolygon" else [geo["coordinates"]]
        n = 0
        for poly in polys:
            for ring in poly:
                pts = [(round(x, 6), round(y, 6)) for x, y in ring]
                if pts[0] == pts[-1]:
                    pts = pts[:-1]
                rings.append((dep, n, pts))
                n += 1
                lon_all += [p[0] for p in pts]
                lat_all += [p[1] for p in pts]
    lon0, lon1, lat0, lat1 = min(lon_all), max(lon_all), min(lat_all), max(lat_all)
    cosm = math.cos(math.radians((lat0 + lat1) / 2))
    k = MAP_W / ((lon1 - lon0) * cosm)
    proj = lambda p: ((p[0] - lon0) * cosm * k, (lat1 - p[1]) * k)   # noqa: E731

    owners: dict[tuple, set] = defaultdict(set)
    for r, (_, _, pts) in enumerate(rings):
        for p in pts:
            owners[p].add(r)
    cache: dict[tuple, list] = {}
    n_in = n_out = 0
    paths: dict[str, list[str]] = defaultdict(list)
    for r, (dep, _, pts) in enumerate(rings):
        n = len(pts)
        junction = [len(owners[pts[i]]) > 2 or owners[pts[i]] != owners[pts[i - 1]]
                    or owners[pts[i]] != owners[pts[(i + 1) % n]] for i in range(n)]
        cuts = [i for i in range(n) if junction[i]]
        if len(cuts) < 2:   # anillo sin vecinos (costa completa, isla, enclave): dos cortes fijos
            cuts = [0, n // 2]
        out: list[tuple[float, float]] = []
        for j, a in enumerate(cuts):
            b = cuts[(j + 1) % len(cuts)]
            arc = [pts[i % n] for i in range(a, (b if b > a else b + n) + 1)]
            key = tuple(arc)
            rev = tuple(reversed(arc))
            if key in cache:
                simp = cache[key]
            elif rev in cache:
                simp = list(reversed(cache[rev]))
            else:
                simp = _dp([proj(p) for p in arc], SIMPLIFY_TOL)
                cache[key] = simp
            out += simp[:-1]
        n_in += n
        n_out += len(out)
        d = "M" + "L".join(f"{x:.1f} {y:.1f}" for x, y in out) + "Z"
        paths[dep].append(d)
    height = (lat1 - lat0) * k
    # Recuadro de Lima y Callao: zona alrededor del Callao, en unidades del mapa.
    callao = [proj(p) for dep, _, pts in rings if dep == "callao" for p in pts]
    cx = (min(p[0] for p in callao) + max(p[0] for p in callao)) / 2
    cy = (min(p[1] for p in callao) + max(p[1] for p in callao)) / 2
    out = {
        "w": MAP_W, "h": round(height, 1),
        "paths": {d: "".join(v) for d, v in paths.items()},
        "focus": [round(cx, 1), round(cy, 1)],
        "meta": {
            "fuente": "INEI, límites departamentales (2007), vía el repositorio juaneladio/peru-geojson",
            "url": GEO_URL, "repositorio": GEO_REPO, "licencia": "MPL-2.0 (Mozilla Public License 2.0)",
            "proyeccion": f"equirrectangular, x = (lon − {lon0:.4f}) × cos({(lat0 + lat1) / 2:.3f}°), "
                          f"y = ({lat1:.4f} − lat); escala {k:.3f} unidades por grado",
            "simplificacion": f"Douglas–Peucker por arco compartido, tolerancia {SIMPLIFY_TOL} unidades "
                              f"(ancho {MAP_W:.0f}); {n_in} → {n_out} vértices",
            "generado": dt.date.today().isoformat(),
        },
    }
    GEO_OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  Geometría: {n_in} -> {n_out} vértices; escrito {GEO_OUT.relative_to(PROJECT_DIR)}")
    return out


def load_geo(force: bool) -> dict:
    if force or not GEO_SRC.exists():
        download_geo()
    if force or not GEO_OUT.exists():
        return build_geo()
    return json.loads(GEO_OUT.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- insumos externos
def build_inputs() -> pd.DataFrame:
    """Población al 30 de junio y VAB a precios corrientes por departamento (INEI), desde las tablas
    procesadas de `../descargas-inei`. Se guarda en `config/` con la URL de cada cuadro de origen."""
    pop = pd.read_parquet(INEI_DIR / "poblacion_departamental.parquet")
    pop = pop[(pop["ambito"] == "departamento") & (pop["anio"] >= FIRST_YEAR)]
    vab = pd.read_parquet(INEI_DIR / "pbi_departamental.parquet")
    vab = vab[(vab["ambito"] == "departamento") & vab["es_total"] & (vab["precios"] == "corrientes")
              & (vab["anio"] >= FIRST_YEAR)]
    code = {u: k for u, k, _ in DEPARTMENTS}
    p = pop.assign(departamento=pop["ubigeo_dpto"].map(code))[["anio", "ubigeo_dpto", "departamento", "poblacion", "tipo_cifra"]]
    v = vab.assign(departamento=vab["ubigeo_dpto"].map(code))[["anio", "departamento", "valor", "estado_cifra"]]
    v = v.rename(columns={"valor": "vab_corrientes_miles", "estado_cifra": "estado_vab"})
    out = p.merge(v, on=["anio", "departamento"], how="left").rename(columns={"ubigeo_dpto": "ubigeo", "tipo_cifra": "tipo_poblacion"})
    if out["departamento"].isna().any() or out.groupby("anio").size().ne(25).any():
        raise ValueError("insumos: no están los 25 departamentos en todos los años")
    out["url_poblacion"] = POP_URL
    out["url_vab"] = VAB_URL
    out = out.sort_values(["anio", "ubigeo"])
    out.to_csv(INPUTS, index=False, encoding="utf-8")
    print(f"  Insumos: {out['anio'].min()}–{out['anio'].max()}, escrito {INPUTS.relative_to(PROJECT_DIR)}")
    return out


def load_inputs(force: bool) -> pd.DataFrame:
    if force or not INPUTS.exists():
        return build_inputs()
    return pd.read_csv(INPUTS, dtype={"ubigeo": str})


# ---------------------------------------------------------------- crédito por departamento
def load_amounts() -> tuple[pd.DataFrame, pd.DataFrame, list[dict]]:
    """Monto por (periodo, subsistema, entidad, departamento) en miles de S/ (incluye «exterior») y
    la fila TOTAL publicada por subsistema (para el control)."""
    d = read_table(BOLETIN / "creditos-departamento.parquet")
    calc = d[d["variable"] == "creditos_directos_calculado"]
    ent = calc[~calc["es_total"]].rename(columns={"apertura": "dep"})
    ent = ent.groupby(["periodo", "subsistema", "id_entidad", "dep"], as_index=False)["valor"].sum()
    pub = d[(d["variable"] == "creditos_directos") & d["es_total"]].groupby(["periodo", "subsistema"])["valor"].sum()

    panel = read_table(PANEL, columns=["periodo", "subsistema", "id_entidad", "creditos_directos"])
    imputed = []
    for sub, eid, per, (pa, pb) in IMPUTE:
        have = ent[(ent["periodo"] == per) & (ent["subsistema"] == sub) & (ent["id_entidad"] == eid)]["valor"].sum()
        if have > 0:
            continue   # la SBS corrigió el cuadro: no hace falta imputar
        tot = panel[(panel["periodo"] == per) & (panel["subsistema"] == sub) & (panel["id_entidad"] == eid)]["creditos_directos"]
        if tot.empty or not tot.iloc[0] > 0:
            print(f"  AVISO: no se pudo imputar {eid} {per}: sin dato en el ranking")
            continue
        nb = ent[(ent["subsistema"] == sub) & (ent["id_entidad"] == eid) & ent["periodo"].isin([pa, pb])]
        sh = nb.pivot_table(index="dep", columns="periodo", values="valor", aggfunc="sum").fillna(0.0)
        sh = (sh / sh.sum()).mean(axis=1)
        rows = pd.DataFrame({"periodo": per, "subsistema": sub, "id_entidad": eid, "dep": sh.index,
                             "valor": sh.values * float(tot.iloc[0])})
        ent = ent[~((ent["periodo"] == per) & (ent["subsistema"] == sub) & (ent["id_entidad"] == eid))]
        ent = pd.concat([ent, rows], ignore_index=True)
        imputed.append({"k": f"{sub}/{eid}", "m": month_key(per), "tot": round(float(tot.iloc[0]))})
        print(f"  Imputado {eid} {per}: S/ {float(tot.iloc[0]) / 1e3:,.0f} mill. (ranking) con la estructura promedio de {pa} y {pb}")
    return ent, pub, imputed


def repeat_list(ent: pd.DataFrame, masked: pd.Series) -> list[list]:
    """Para la página: [mes, «subsistema/entidad», mes repetido, «fila», motivo, acción] de cada entidad-mes enmascarada.
    La acción («blank_month» o «drop_entity», de `RANKING_REPEATS`) dice si el IHH del subsistema y del sistema queda
    sin dato ese mes (la entidad pesa) o se calcula sin ella (Pisco, 0,4 % de las CMAC)."""
    present = set(map(tuple, ent.loc[masked, ["periodo", "subsistema", "id_entidad"]].drop_duplicates().values.tolist()))
    out = []
    for k, r in sorted(source_repeats(TEMA).items()):
        if k not in present:
            continue
        note = repeat_footnote(r)
        out.append([month_key(k[0]), f"{k[1]}/{k[2]}", month_key(r["same_as"]), "fila",
                    "nota al pie del cuadro: " + note if note else "sin nota al pie", r["action"]])
    return out


def check_totals(ent: pd.DataFrame, pub: pd.Series, imputed: list[dict]) -> None:
    """Suma de entidades (con exterior) vs. fila TOTAL publicada por subsistema y mes."""
    s = ent.groupby(["periodo", "subsistema"])["valor"].sum()
    gap = (s - pub).dropna()
    imp = {(int(x["m"].replace("-", "")), x["k"].split("/")[0]): x["tot"] for x in imputed}
    bad = []
    for (per, sub), g in gap.items():
        expected = imp.get((per, sub), 0.0)
        if abs(g - expected) > max(1.0, 1e-6 * pub[(per, sub)]):
            bad.append((per, sub, g))
    print(f"  Control: suma de entidades vs. TOTAL publicado en {len(gap)} subsistema-mes; "
          f"{len(bad)} con diferencia (fuera de la imputación)")
    for b in bad[:10]:
        print("    ", b)


def build_data(force_inputs: bool, force_geo: bool) -> dict:
    geo = load_geo(force_geo)
    inputs = load_inputs(force_inputs)
    ent, pub, imputed = load_amounts()
    check_totals(ent, pub, imputed)
    months = month_range(int(ent["periodo"].min()), int(ent["periodo"].max()))
    pos = {m: i for i, m in enumerate(months)}
    N = len(months)

    def arr(series: pd.Series) -> list:
        out = [None] * N
        for m, v in series.items():
            out[pos[m]] = int(round(float(v)))
        return out

    # Agregados por ámbito: {dep: [N]}; departamentos sin entidades ese mes = 0.
    agg: dict[str, dict] = {}
    ext: dict[str, list] = {}
    # El sistema llega hasta el último mes que publicaron los cinco subsistemas (si uno se atrasa, la suma
    # de los demás no es el sistema).
    sys_end = int(ent.groupby("subsistema")["periodo"].max().min())
    for scope, mask in [("sistema", slice(None))] + [(k, ent["subsistema"] == k) for k, _, _ in SUBSYSTEMS]:
        g = ent[mask] if scope != "sistema" else ent[ent["periodo"] <= sys_end]
        piv = g.groupby(["dep", "periodo"])["valor"].sum().unstack("periodo").reindex(columns=months)
        present = g.groupby("periodo")["valor"].sum().reindex(months)
        block = {}
        for dep in DEPT_KEYS:
            row = piv.loc[dep] if dep in piv.index else pd.Series(np.nan, index=months)
            row = row.where(present.notna(), np.nan).fillna(0.0).where(present.notna())
            block[dep] = [None if pd.isna(v) else int(round(float(v))) for v in row]
        agg[scope] = block
        er = piv.loc[EXTERIOR] if EXTERIOR in piv.index else pd.Series(0.0, index=months)
        ext[scope] = [int(round(float(v))) if pd.notna(v) else 0 for v in er]

    # Entidades: {n, s, a, T (total con exterior), D: {dep: [a, ...]}}; solo departamentos con saldo. Sin las
    # entidad-mes en que la SBS repite la distribución de otro mes (los agregados de arriba sí las incluyen).
    masked = source_repeat_mask(ent, TEMA)
    print(f"  Cifras repetidas de otro mes (errores_origen.RANKING_REPEATS): {int(masked.sum())} filas de entidad sin dato "
          f"en {ent[masked].groupby(['periodo', 'id_entidad']).ngroups} entidad-mes; agregados sin cambio")
    rep = repeat_list(ent, masked)
    ent = ent[~masked]
    names = pd.read_csv(ENTIDADES, dtype=str).set_index("id_entidad")["nombre_actual"]
    panel = read_table(PANEL, columns=["periodo", "subsistema", "id_entidad", "nombre_entidad"])
    last_name = panel.sort_values("periodo").groupby(["subsistema", "id_entidad"])["nombre_entidad"].last()
    entities, emap = [], {}
    for (sub, eid), g in ent.groupby(["subsistema", "id_entidad"]):
        tot = g.groupby("periodo")["valor"].sum()
        tot = tot[tot > 0]
        if tot.empty:
            continue
        a, b = pos[tot.index.min()], pos[tot.index.max()]
        T = [None] * (b - a + 1)
        for m, v in tot.items():
            T[pos[m] - a] = int(round(float(v)))
        D = {}
        piv = g.pivot_table(index="dep", columns="periodo", values="valor", aggfunc="sum")
        for dep, row in piv.iterrows():
            if not (row.fillna(0) > 0.5).any():
                continue
            vals = [None] * (b - a + 1)
            for m, v in row.items():
                if pd.notna(v) and m in tot.index:
                    vals[pos[m] - a] = int(round(float(v)))
            # Dentro del rango de la entidad, sin fila = 0 (la entidad no tenía créditos ahí).
            vals = [0 if v is None and T[j] is not None else v for j, v in enumerate(vals)]
            D[dep] = vals
        k = f"{sub}/{eid}"
        emap[k] = {"n": last_name.get((sub, eid)) or names.get(eid, eid), "s": sub, "a": a, "T": T, "D": D}
        entities.append(k)
    by_id: dict[str, list[str]] = {}
    for k in entities:
        by_id.setdefault(k.split("/", 1)[1], []).append(k)
    for ks in by_id.values():
        if len(ks) > 1:
            for k in ks:
                emap[k]["o"] = [x for x in ks if x != k]

    # Entidades con sucursales en el exterior (para el texto de metodología).
    ex = ent[(ent["dep"] == EXTERIOR) & (ent["valor"] > 0)].groupby("id_entidad")["periodo"].agg(["min", "max"])
    ext_info = [{"k": f"banca-multiple/{i}", "n": emap.get(f"banca-multiple/{i}", {}).get("n", i),
                 "desde": month_key(int(r["min"])), "hasta": month_key(int(r["max"]))} for i, r in ex.iterrows()]

    years = sorted(inputs["anio"].unique().tolist())
    pop = {dep: [int(v) for v in inputs[inputs["departamento"] == dep].sort_values("anio")["poblacion"]] for dep in DEPT_KEYS}
    vy = inputs.dropna(subset=["vab_corrientes_miles"])
    vab_years = sorted(vy["anio"].unique().tolist())
    vab = {dep: [int(round(v)) for v in vy[vy["departamento"] == dep].sort_values("anio")["vab_corrientes_miles"]] for dep in DEPT_KEYS}
    vab_state = vy.groupby("anio")["estado_vab"].first().to_dict()

    return {
        "months": [month_key(m) for m in months],
        "depts": [{"k": k, "l": l, "u": u} for u, k, l in DEPARTMENTS],
        "subs": [{"k": k, "l": l, "s": s} for k, l, s in SUBSYSTEMS],
        "agg": agg,
        "ext": ext,
        "ent": emap,
        "entities": entities,
        "extInfo": ext_info,
        "imp": imputed,
        # Entidad-mes con las cifras de otro mes (errores_origen.RANKING_REPEATS): sin dato en la serie de la entidad.
        "rep": rep,
        "pop": {"y0": years[0], "v": pop},
        "vab": {"y0": vab_years[0], "v": vab, "estado": {str(k): v for k, v in vab_state.items()}},
        "geo": {"w": geo["w"], "h": geo["h"], "paths": geo["paths"], "focus": geo["focus"]},
        "hasta": month_key(months[-1]),
        # Último mes con los cinco subsistemas (= último mes del sistema) y último mes de cada ámbito: la
        # página abre en `allHasta` y, si un ámbito no tiene el mes elegido, muestra su último mes.
        "allHasta": month_key(sys_end),
        "scopeHasta": {sc: month_key(months[max(k for k, v in enumerate(b["lima"]) if v is not None)])
                       for sc, b in agg.items()},
        "generado": dt.date.today().isoformat(),
    }


def summary(data: dict) -> None:
    """Cifras del último mes para revisar a ojo."""
    s = data["agg"]["sistema"]
    i = max(k for k in range(len(data["months"])) if s["lima"][k] is not None)  # último mes del sistema
    tot = sum(s[d][i] for d in DEPT_KEYS)
    lc = s["lima"][i] + s["callao"][i]
    print(f"  {data['months'][i]}: sistema S/ {tot / 1e6:,.1f} mil mill. sin exterior; Lima y Callao {100 * lc / tot:.1f}%")
    top = sorted(DEPT_KEYS, key=lambda d: -s[d][i])[:5]
    print("  Top 5:", ", ".join(f"{d} {s[d][i] / 1e6:,.1f}" for d in top))
    gr = {d: 100 * (s[d][i] / s[d][i - 12] - 1) for d in DEPT_KEYS if s[d][i - 12]}
    print("  Crecen más:", ", ".join(f"{d} {v:+.1f}%" for d, v in sorted(gr.items(), key=lambda x: -x[1])[:5]))
    cj = {d: 100 * (data["agg"]["cajas-municipales"][d][i] + data["agg"]["cajas-rurales"][d][i]) / s[d][i] for d in DEPT_KEYS}
    print("  Peso de cajas:", ", ".join(f"{d} {v:.1f}%" for d, v in sorted(cj.items(), key=lambda x: -x[1])[:6]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--insumos", action="store_true", help="rehace config/insumos_departamentales.csv")
    ap.add_argument("--geo", action="store_true", help="vuelve a bajar y simplificar la geometría")
    args = ap.parse_args()
    print("Armando datos de crédito por departamento...")
    data = build_data(args.insumos, args.geo)
    summary(data)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    template = TEMPLATE.read_text(encoding="utf-8")
    if PLACEHOLDER not in template:
        print(f"ERROR: la plantilla no tiene el marcador {PLACEHOLDER}")
        return 1
    html = template.replace(PLACEHOLDER, payload)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    OUT_ARTIFACT.write_text(artifact_version(html), encoding="utf-8")
    print(f"  Último mes con los 5 subsistemas: {data['allHasta']}; por ámbito: "
          + ", ".join(f"{k} {v}" for k, v in data["scopeHasta"].items()))
    print(f"  {data['months'][0]} a {data['hasta']}, {len(data['entities'])} series de entidad, "
          f"datos {len(payload) / 1e6:.2f} MB, página {len(html.encode('utf-8')) / 1e6:.2f} MB")
    print(f"  Escrito {OUT.relative_to(PROJECT_DIR)} y {OUT_ARTIFACT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
