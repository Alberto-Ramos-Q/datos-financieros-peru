"""Genera `outputs/solvencia_ssff.html`: tablero público de solvencia y capital del sistema financiero.

Lee cuatro tablas largas de `data/processed/boletin/` (correr antes `leer_boletin.py`):
- `ratio-capital-global`: ratio de capital global (RCG), patrimonio efectivo (PE, publicado hasta
  2023-05), activos y contingentes ponderados por riesgo (APR, publicados desde 2021-04, total y por
  riesgo de crédito, mercado y operacional), requerimientos de PE por tipo de riesgo y, desde 2023-06,
  los ratios de capital ordinario de nivel 1 (CET1) y de PE de nivel 1, por entidad y mes.
- `estructura-patrimonio-efectivo`: PE total (desde 2023-06 es la única fuente del PE) y sus niveles.
  Banca y financieras publican los niveles en miles de S/; cajas municipales, cajas rurales y empresas
  de créditos, en % del total (aquí se pasan a miles: % × total / 100).
- `estados-financieros`: pasivo total, capital social y reservas (apalancamiento agregado).
- `indicadores-financieros`: apalancamiento publicado por entidad (pasivo / (capital social + reservas)).
y `data/processed/panel_entidad_mes.parquet` para la mora, el ROE y el activo de cada entidad
(eje horizontal de la dispersión).

Reglas de cálculo:
- APR antes de 2021-04 (la SBS no lo publicaba) = PE × 100 / RCG de cada entidad. Por tipo de riesgo,
  = requerimiento × 10, reescalado para que sume el APR total (de 2011-07 a 2021-03 el límite global era
  10%; de 2010-07 a 2011-06 era 9,8% y el factor legal 10,2, pero al reescalar solo cuenta la proporción
  entre requerimientos; la identidad reproduce el RCG con error mediano de 0,002 pp).
- PE desde 2023-06 = total del cuadro de estructura del PE; si falta, RCG × APR / 100.
- CET1 y PE de nivel 1 en miles = ratio publicado × APR / 100.
- Agregados (subsistema y sistema) = suma de entidades y luego el cociente: Σ PE / Σ APR, nunca el
  promedio de los ratios. El sistema (los 5 subsistemas) solo tiene dato en los meses en que los cinco
  publicaron el cuadro (cajas y empresas de créditos salen un mes después).
- Mínimo legal (límite global, art. 199 de la Ley General) por mes en `LIMITS`, con los requerimientos
  mínimos de CET1 y de PE de nivel 1 del régimen de adecuación (Res. SBS 274-2024).

Genera además `outputs/solvencia_ssff_artifact.html`, la versión para publicar como Artifact de
claude.ai (sin <html>/<head>/<body>).

Uso:
    python visual_solvencia.py
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from visual_mora import (ENTIDADES, PROJECT_DIR, SUBSYSTEMS, artifact_version, read_table,  # noqa: E402
                         month_key, month_range)

BOLETIN = PROJECT_DIR / "data" / "processed" / "boletin"
PANEL = PROJECT_DIR / "data" / "processed" / "panel_entidad_mes.parquet"
TEMPLATE = PROJECT_DIR / "src" / "plantillas" / "solvencia.html"
OUT = PROJECT_DIR / "outputs" / "solvencia_ssff.html"
OUT_ARTIFACT = PROJECT_DIR / "outputs" / "solvencia_ssff_artifact.html"
PLACEHOLDER = "/*__DATA__*/null"

FIRST_APR = 202104      # primer mes con APR publicado
FIRST_CALC_PE = 202306  # desde aquí la SBS no publica el PE en el cuadro del RCG

# (desde AAAAMM, límite global %, CET1 mínimo %, PE de nivel 1 mínimo %). Fuentes:
# - Ley 26702, vigésima cuarta disposición transitoria (incorporada por el art. 2 del
#   D. Leg. 1028, vigente desde 2009-07): adecuación gradual del límite global, 9,5% a julio de 2009,
#   9,8% a julio de 2010 (riesgo de mercado y operacional × 10,2) y 10% a julio de 2011 (× 10). Los
#   datos empiezan en 2010-07; el cuadro lo confirma (requerimiento total / APR = 9,8% hasta 2011-06).
# - Ley 26702 art. 199 (texto del D. Leg. 1028): límite global 10% desde 2011-07.
# - Res. SBS 2115-2009, art. 3 (texto sustituido por la Res. SBS 3127-2012): el APR por riesgo operacional
#   se multiplica por un factor de ajuste de 0,40 hasta 2011-06, 0,50, 0,60 y 0,80 cada julio y 1 desde
#   2014-07. El requerimiento operacional publicado ya lo incluye (total / APR = límite), así que no se
#   corrige aquí; solo explica los saltos de julio en el APR operacional.
# - D.U. 037-2021 (El Peruano 15-04-2021): límite global 8% hasta el 31-03-2022.
# - D.U. 003-2022 (El Peruano 26-03-2022): 8% hasta agosto de 2022 y 8,5% desde setiembre de 2022
#   (vigente hasta el 31-03-2023).
# - D. Leg. 1531 (arts. 184, 199, 199-A, 199-B y 218 vigentes desde 2023-01): CET1 ≥ 4,5%,
#   PE de nivel 1 ≥ 6%, límite global ≥ 10%.
# - Res. SBS 3952-2022, art. 3 (vigente 2023-01): adecuación hasta 10% en 2024-03; sustituido por la
#   Res. SBS 2192-2023 (vigente 2023-06-30; 10% en 2024-09) y luego por la Res. SBS 274-2024 (del
#   24-01-2024; 10% en 2025-03). Cada cambio llegó antes del escalón siguiente, así que la tabla final
#   es la que rigió mes a mes; lo confirma requerimiento por riesgo de crédito / APR de crédito.
# - APR de mercado y operacional = 10 × requerimiento en todos los meses, aun con límite transitorio < 10%.
LIMITS = [
    (201007, 9.8, None, None),
    (201107, 10.0, None, None),
    (202104, 8.0, None, None),
    (202209, 8.5, None, None),
    (202301, 8.5, 3.825, 5.10),
    (202304, 9.0, 4.05, 5.40),
    (202409, 9.5, 4.275, 5.70),
    (202503, 10.0, 4.50, 6.00),
]

# Campos por ámbito (todos los montos en miles de S/):
# pe, apr; ac/am/ao = APR por riesgo de crédito/mercado/operacional; c1/t1 = CET1 y PE de nivel 1
# (ratio × APR); n1/n2/n3 = niveles del PE hasta 2023-05; ce/at = CET1 y capital adicional de nivel 1
# del cuadro de estructura (desde 2023-06; n2 sigue); pas/csr = pasivo y capital social + reservas.
# Solo entidades: rcg y lev publicados, mora (%), roe (%), act (activo total, miles de S/).
AMOUNTS = ["pe", "apr", "ac", "am", "ao", "c1", "t1", "n1", "n2", "n3", "ce", "at", "pas", "csr"]
ENTITY_ONLY = ["rcg", "lev", "mora", "roe", "act"]
KEY = ["periodo", "subsistema", "id_entidad"]


def wide(df: pd.DataFrame, value: str = "valor") -> pd.DataFrame:
    """Tabla larga → una columna por variable|apertura, por (periodo, subsistema, entidad)."""
    d = df[~df["es_total"]].copy()
    d["k"] = d["variable"] + "|" + d["apertura"].fillna("")
    return d.pivot_table(index=KEY, columns="k", values=value, aggfunc="first")


def load_capital() -> pd.DataFrame:
    """RCG, PE, APR (total y por riesgo), CET1 y PE de nivel 1 por entidad y mes."""
    w = wide(read_table(BOLETIN / "ratio-capital-global.parquet"))
    out = pd.DataFrame(index=w.index)
    out["rcg"] = w["ratio_capital_global|"]
    pe_pub = w["patrimonio_efectivo|"]
    apr_pub = w["activos_ponderados_riesgo|total"]
    out["apr"] = apr_pub.where(apr_pub.notna(), pe_pub * 100 / out["rcg"])
    for col, risk in (("ac", "riesgo_credito"), ("am", "riesgo_mercado"), ("ao", "riesgo_operacional")):
        pub = w[f"activos_ponderados_riesgo|{risk}"]
        out[col] = pub.where(pub.notna(), 10 * w[f"requerimiento_patrimonio_efectivo|{risk}"])
    # Antes de 2021-04 el APR por riesgo se reconstruye con los requerimientos; se reescala para que
    # sume el APR total (diferencias de redondeo).
    per = out.index.get_level_values("periodo")
    old = per < FIRST_APR
    parts = out.loc[old, ["ac", "am", "ao"]]
    out.loc[old, ["ac", "am", "ao"]] = parts.mul(out.loc[old, "apr"] / parts.sum(axis=1), axis=0)
    out["pe_pub"] = pe_pub
    out["c1"] = w["ratio_capital_ordinario_nivel1|"] * out["apr"] / 100
    out["t1"] = w["ratio_patrimonio_efectivo_nivel1|"] * out["apr"] / 100
    return out


def load_structure() -> pd.DataFrame:
    """Niveles del PE en miles de S/ y PE total del cuadro de estructura."""
    s = read_table(BOLETIN / "estructura-patrimonio-efectivo.parquet")
    s = s[~s["es_total"]]
    # CRAC 2015-07 y 2015-09 repiten una fila idéntica: se queda la primera.
    tot = s[(s["variable"] == "patrimonio_efectivo") & (s["apertura"] == "total")].groupby(KEY)["valor"].first()
    names = {"nivel1": "n1", "nivel2": "n2", "nivel3": "n3", "capital_ordinario_nivel1": "ce",
             "capital_adicional_nivel1": "at"}
    amt = s[(s["variable"] == "patrimonio_efectivo") & (s["apertura"] != "total")]
    amt = amt.pivot_table(index=KEY, columns="apertura", values="valor", aggfunc="first").rename(columns=names)
    # Cajas y empresas de créditos: componentes en % del total. Si los % no suman 100 (error de
    # origen, p. ej. CMAC Ica, Paita y Piura en 2026-06/07) se reparten en proporción.
    sh = s[s["variable"] == "participacion_patrimonio_efectivo"]
    sh = sh.pivot_table(index=KEY, columns="apertura", values="valor", aggfunc="first").rename(columns=names)
    ssum = sh.sum(axis=1, min_count=1)
    bad = (ssum - 100).abs() > 0.5
    if bad.any():
        print(f"  AVISO: {int(bad.sum())} entidad-mes con % de la estructura del PE que no suman 100 (se reescalan)")
    sh = sh.div(ssum, axis=0).mul(tot.reindex(sh.index), axis=0)
    lv = pd.concat([amt, sh])
    lv = lv.groupby(level=[0, 1, 2]).first()
    lv["pe_est"] = tot.reindex(lv.index)
    missing = tot.index.difference(lv.index)
    if len(missing):
        lv = pd.concat([lv, pd.DataFrame({"pe_est": tot.reindex(missing)})])
    return lv


def load_leverage() -> pd.DataFrame:
    """Pasivo total y capital social + reservas (miles de S/) y el apalancamiento publicado."""
    e = read_table(BOLETIN / "estados-financieros.parquet",
                        filters=[("variable", "in", ["total_pasivo", "patrimonio_capital_social", "patrimonio_reservas"])])
    e = e[(~e["es_total"]) & (e["apertura"] == "total")]
    e = e.pivot_table(index=KEY, columns="variable", values="valor", aggfunc="first")
    out = pd.DataFrame({"pas": e["total_pasivo"],
                        "csr": e["patrimonio_capital_social"].fillna(0) + e["patrimonio_reservas"].fillna(0)})
    ind = read_table(BOLETIN / "indicadores-financieros.parquet")
    ind = ind[(~ind["es_total"]) & (ind["variable"] == "pasivo_total_capital_social_reservas")]
    out["lev"] = ind.groupby(KEY)["valor"].first()
    return out


def build_frame() -> pd.DataFrame:
    cap = load_capital()
    st = load_structure()
    lev = load_leverage()
    f = cap.join(st, how="outer").join(lev, how="left")
    per = f.index.get_level_values("periodo")
    # PE: publicado hasta 2023-05; desde 2023-06, el total del cuadro de estructura (o RCG × APR).
    calc = f["rcg"] * f["apr"] / 100
    f["pe"] = np.where(per < FIRST_CALC_PE, f["pe_pub"], f["pe_est"].where(f["pe_est"].notna(), calc))
    # Sin RCG no hay solvencia: se dejan solo los meses con cuadro de capital.
    f = f[f["rcg"].notna() | f["apr"].notna()]
    # Para los agregados, PE y APR tienen que venir juntos.
    both = f["pe"].notna() & f["apr"].notna()
    f.loc[~both, ["pe", "apr"]] = np.nan
    # Si un nivel no viene en el mes, la estructura queda vacía (no 0).
    panel = read_table(PANEL, columns=KEY + ["morosidad", "roe", "activo_total"])
    panel = panel[panel["id_entidad"] != "_total"].set_index(KEY)
    f = f.join(panel.rename(columns={"morosidad": "mora", "activo_total": "act"}), how="left")
    return f.reset_index()


def series(g: pd.DataFrame, months: list[int], fields: list[str], decimals: dict) -> dict:
    """{a: índice del primer mes, V: {campo: [valores]}} para un ámbito; None si no hay dato."""
    pos = {m: i for i, m in enumerate(months)}
    g = g.set_index("periodo").sort_index()
    present = [m for m in g.index if m in pos]
    if not present:
        return {"a": 0, "V": {}}
    a, b = pos[present[0]], pos[present[-1]]
    V = {}
    for col in fields:
        if col not in g:
            continue
        v = g[col].reindex(months[a:b + 1])
        if v.notna().sum() == 0:
            continue
        d = decimals.get(col, 0)
        V[col] = [None if pd.isna(x) else (int(round(float(x))) if d == 0 else round(float(x), d)) for x in v]
    return {"a": a, "V": V}


def aggregate(df: pd.DataFrame) -> pd.DataFrame:
    """Suma de entidades por mes; un campo queda vacío si ninguna entidad lo tiene."""
    return df.groupby("periodo")[AMOUNTS].sum(min_count=1).reset_index()


def check_totals(full: pd.DataFrame) -> None:
    """Control: el RCG agregado (Σ PE / Σ APR) frente al RCG del total que publica la SBS."""
    d = read_table(BOLETIN / "ratio-capital-global.parquet")
    pub = d[d["es_total"] & (d["variable"] == "ratio_capital_global")].set_index(["periodo", "subsistema"])["valor"]
    agg = full.groupby(["periodo", "subsistema"])[["pe", "apr"]].sum(min_count=1)
    calc = 100 * agg["pe"] / agg["apr"]
    gap = (calc - pub).dropna().abs()
    big = gap[gap > 0.05]
    print(f"  Control RCG agregado vs. total publicado: {len(gap)} subsistema-mes, mediana {gap.median():.3f} pp, "
          f"{len(big)} con diferencia > 0,05 pp")
    for (p, s), v in big.sort_values(ascending=False).head(8).items():
        print(f"    {p} {s}: calculado {calc[(p, s)]:.2f} vs publicado {pub[(p, s)]:.2f}")


def build_data() -> dict:
    full = build_frame()
    check_totals(full)
    months = month_range(int(full["periodo"].min()), int(full["periodo"].max()))
    dec = {"rcg": 2, "lev": 2, "mora": 2, "roe": 2}

    names = pd.read_csv(ENTIDADES, dtype=str).set_index("id_entidad")["nombre_actual"]
    panel = read_table(PANEL, columns=["periodo", "subsistema", "id_entidad", "nombre_entidad"])
    last_name = panel.sort_values("periodo").groupby(["subsistema", "id_entidad"])["nombre_entidad"].last()

    scopes: dict[str, dict] = {}
    subs_present = {}
    for sub, label, _ in SUBSYSTEMS:
        g = aggregate(full[full["subsistema"] == sub])
        subs_present[sub] = g.set_index("periodo")
        scopes[sub] = {"n": label, "s": sub, **series(g, months, AMOUNTS, dec)}
    # Sistema: un campo tiene dato en un mes solo si los cinco subsistemas lo tienen.
    sysg = pd.concat(subs_present.values()).groupby(level=0)[AMOUNTS]
    total = sysg.sum(min_count=1)
    count = sysg.count()
    total = total.where(count >= len(SUBSYSTEMS))
    scopes["sistema"] = {"n": "Sistema financiero", "s": None, **series(total.reset_index(), months, AMOUNTS, dec)}

    entities = []
    for (sub, ent), g in full.groupby(["subsistema", "id_entidad"]):
        block = series(g, months, AMOUNTS + ENTITY_ONLY, dec)
        if "rcg" not in block["V"]:
            continue
        k = f"{sub}/{ent}"
        scopes[k] = {"n": last_name.get((sub, ent)) or names.get(ent, ent), "s": sub, **block}
        entities.append(k)
    by_id: dict[str, list[str]] = {}
    for k in entities:
        by_id.setdefault(k.split("/", 1)[1], []).append(k)
    for ks in by_id.values():
        if len(ks) > 1:
            for k in ks:
                scopes[k]["o"] = [x for x in ks if x != k]

    def limit_at(m: int, j: int):
        val = None
        for row in LIMITS:
            if m >= row[0]:
                val = row[j]
        return val

    sys_months = [m for m, v in zip(months, total["pe"].reindex(months)) if not pd.isna(v)]
    return {
        "months": [month_key(m) for m in months],
        "lg": [limit_at(m, 1) for m in months],
        "c1min": [limit_at(m, 2) for m in months],
        "t1min": [limit_at(m, 3) for m in months],
        "aprFrom": month_key(FIRST_APR),
        "peCalcFrom": month_key(FIRST_CALC_PE),
        "subs": [{"k": k, "l": l, "s": s} for k, l, s in SUBSYSTEMS],
        "scopes": scopes,
        "entities": entities,
        "hasta": month_key(months[-1]),
        "sysHasta": month_key(sys_months[-1]),
        "generado": dt.date.today().isoformat(),
    }


def summary(data: dict) -> None:
    """Cifras del último mes con sistema completo, para revisar a ojo."""
    i = data["months"].index(data["sysHasta"])
    lg = data["lg"][i]
    print(f"  Último mes con los 5 subsistemas: {data['sysHasta']} (límite global {lg}%)")
    for k in ["sistema"] + [s["k"] for s in data["subs"]]:
        s = data["scopes"][k]
        j = i - s["a"]
        pe, apr = s["V"]["pe"][j], s["V"]["apr"][j]
        c1 = s["V"].get("c1", [None] * (j + 1))[j]
        print(f"    {s['n']:<22} RCG {100 * pe / apr:6.2f}%  CET1 {100 * c1 / apr if c1 else float('nan'):6.2f}%  "
              f"colchón S/ {(pe - lg * apr / 100) / 1e6:6.1f} mil mill.")
    low = []
    for k in data["entities"]:
        s = data["scopes"][k]
        j = i - s["a"]
        r = s["V"]["rcg"]
        if 0 <= j < len(r) and r[j] is not None and r[j] < lg + 2.5:
            low.append((r[j], s["n"], s["s"]))
    print(f"  Entidades con RCG < límite + 2,5 pp en {data['sysHasta']}:")
    for v, n, sub in sorted(low):
        print(f"    {v:6.2f}%  {n} ({sub})")


def main() -> int:
    print("Armando datos de solvencia...")
    data = build_data()
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
    print(f"  {data['months'][0]} a {data['hasta']}, {len(data['entities'])} series de entidad, datos {len(payload) / 1e6:.1f} MB")
    print(f"  Escrito {OUT.relative_to(PROJECT_DIR)} y {OUT_ARTIFACT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
