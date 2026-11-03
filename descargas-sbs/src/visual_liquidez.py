"""Genera `outputs/liquidez_ssff.html`: tablero público de liquidez y fondeo del sistema financiero.

Lee siete tablas largas de `data/processed/boletin/` (correr antes `leer_boletin.py`):
- `ratios-liquidez`: activos líquidos y pasivos de corto plazo en MN (miles de S/) y en ME (miles
  de US$) por entidad y mes; de ahí salen los ratios de liquidez (Anexo 15-C).
- `ratio-cobertura-liquidez`: ratio de cobertura de liquidez (RCL) publicado, total, MN y ME.
  Trimestral desde 2024-03: el dato va en el mes de cierre del trimestre y sale ~3 meses después.
  Es el promedio simple de los ratios diarios del trimestre, así que NO se agrega (no hay RCL del
  sistema): se muestra el publicado por entidad y por subsistema.
- `ratio-financiacion-neta-estable`: financiación estable disponible y requerida (miles de S/),
  mensual desde 2025-12. RFNE = disponible / requerida (reproduce el publicado en todas las filas).
- `estados-financieros`: balance (columnas locales, sin sucursales en el exterior): depósitos del
  público por tipo, depósitos del sistema financiero y organismos internacionales, adeudos,
  valores en circulación, otros pasivos y patrimonio, con su parte en ME (dolarización).
- `ranking-creditos-depositos-patrimonio`: créditos directos (numerador de créditos / depósitos).
- `depositantes-tipo-deposito`: número de depositantes por entidad (total de depósitos, suma de
  personas naturales, jurídicas sin fines de lucro y otras jurídicas).
- `depositos-escala-montos`: depósitos y depositantes por tramo de saldo, solo por subsistema.
  Los tramos son múltiplos de la cobertura del Fondo de Seguro de Depósitos (FSD); la cobertura
  en soles de cada cuadro se lee del límite «de X a más» (= 100 veces la cobertura) del Excel
  original en `data/raw/` (solo lectura), porque la tabla procesada guarda solo el múltiplo.
- `adeudos-obligaciones-financieras`: estructura de los adeudos por origen y plazo (en %).

Reglas de cálculo:
- Depósitos totales = vista + ahorro + plazo (con CTS y depósitos restringidos) del público +
  depósitos del sistema financiero y organismos internacionales. Es la definición del ranking de
  depósitos de la SBS (la reproduce en el 99,8 % de las entidades-mes).
- Agregados (subsistema y sistema) = suma de entidades y luego el cociente (Σ activos líquidos /
  Σ pasivos de corto plazo), nunca el promedio de ratios. En liquidez, depósitos y depositantes el
  sistema son los cuatro subsistemas que captan depósitos (las empresas de créditos no captan); en
  el fondeo y los adeudos, los cinco. Un campo del sistema solo tiene dato si todos sus
  subsistemas lo tienen ese mes.
- Depósitos cubiertos por el FSD (estimación propia, solo por subsistema): en «Depósitos totales»,
  personas naturales y jurídicas sin fines de lucro, Σ monto de los tramos hasta 1 vez la cobertura
  + número de depositantes de los tramos mayores × cobertura; más lo mismo con los depósitos a la
  vista de las otras personas jurídicas (`FSD_COVERED`).
- Los controles contra los totales publicados se imprimen al correr el script.
- Mes por defecto (`allHasta`): último mes con todos los campos del resumen en el sistema. Si un ámbito
  no tiene un mes porque algún subsistema aún no lo publica, la plantilla muestra su último mes con dato
  y lo marca (no se rellena la serie).

Historia desde 2010-07 (visual_mora.START_PERIOD): las financieras publican ratios de liquidez y escala
de montos desde 2010-10 y la estructura de adeudos desde 2015-09; el balance hasta 2012-12 sigue el Manual
de Contabilidad anterior (ver BALANCE_VARS).

Genera además `outputs/liquidez_ssff_artifact.html`, la versión para publicar como Artifact de
claude.ai (sin <html>/<head>/<body>).

Uso:
    python visual_liquidez.py
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from visual_mora import (ENTIDADES, PROJECT_DIR, START_PERIOD, SUBSYSTEMS, artifact_version, read_table,  # noqa: E402
                         month_key, month_range)

BOLETIN = PROJECT_DIR / "data" / "processed" / "boletin"
RAW = PROJECT_DIR / "data" / "raw" / "boletin"
PANEL = PROJECT_DIR / "data" / "processed" / "panel_entidad_mes.parquet"
TEMPLATE = PROJECT_DIR / "src" / "plantillas" / "liquidez.html"
OUT = PROJECT_DIR / "outputs" / "liquidez_ssff.html"
OUT_ARTIFACT = PROJECT_DIR / "outputs" / "liquidez_ssff_artifact.html"
PLACEHOLDER = "/*__DATA__*/null"

KEY = ["periodo", "subsistema", "id_entidad"]
DEPOSIT_TAKERS = ["banca-multiple", "empresas-financieras", "cajas-municipales", "cajas-rurales"]
MONTH_CODE = {"en": 1, "fe": 2, "ma": 3, "ab": 4, "my": 5, "jn": 6, "jl": 7, "ag": 8,
              "se": 9, "oc": 10, "no": 11, "di": 12}
# Mínimos regulatorios (desde AAAAMM, %). Fuentes:
# - Ratios de liquidez 2010-07 → 2013-09: Normas para la Gestión de Tesorería (Res. SBS 472-2001), que
#   la Res. SBS 9075-2012 (05-12-2012) derogó desde el 01-10-2013 (Artículo Quinto, fin del plazo de
#   adecuación). Mínimo 8% en MN y 20% en ME según el Glosario SBS de abril de 2011 («Las instituciones
#   financieras deben mantener un ratio mínimo de 8% en MN y de 20% en ME. No aplicable a Edpymes»;
#   copia de web.archive.org del 2013-07-16). El texto de la 472-2001 no se consiguió en línea.
# - Ratios de liquidez desde 2013-10: Res. SBS 9075-2012, art. 30 a) y b), y Res. SBS 4221-2023 (vigente desde
#   2024-01), art. 45.1 a) y b): RLMN ≥ 8% y RLME ≥ 20%; suben a 10% y 25% si la concentración de los
#   20 principales depositantes del mes anterior supera 25% (dato que la SBS no publica por entidad:
#   el tablero muestra el mínimo general). Se miden con el promedio mensual de saldos diarios (45.4).
# - RCL total ≥ 100% (RCL MN ≥ 80%, RCL ME ≥ 100%): Res. SBS 4221-2023, art. 45.1 d); cumplimiento
#   diario. El RCL publicado empieza en 2024-03, todo bajo esa norma.
# - RFNE ≥ 100% con gradualidad: 80% desde dic-2024, 90% desde dic-2025, 100% desde dic-2026
#   (Res. SBS 4221-2023, art. 45.1 e) y Segunda Disposición Complementaria Transitoria).
# No aplican a las empresas de créditos (art. 45.2, desde el texto original; la Res. SBS 00874-2026 sustituyó
# el 45.2 para quitar a Agrobanco de las excepciones y mantuvo la de las empresas de créditos).
# Res. SBS 9075-2012, art. 30 (verificado en la v6.0): RLMN ≥ 8% y RLME ≥ 20% (10% y 25% con concentración).
LIMITS = {
    "lmn": [(201007, 8.0)],
    "lme": [(201007, 20.0)],
    "rcl": [(202401, 100.0)],
    "rfne": [(202412, 80.0), (202512, 90.0), (202612, 100.0)],
}
# Control de la estimación de depósitos cubiertos: depósitos asegurados que publica el FSD
# (millones de S/, % de los depósitos totales de sus miembros) en sus memorias anuales, sección
# «Depósitos asegurados por el FSD»: Memoria 2011 a 2015 (p. 9 del PDF; 2013, p. 10) y Memoria 2025 (p. 19).
# Dic-2014: % revisado de la Memoria 2015 (36,4 %; la Memoria 2014 daba 34,5 %; el monto, S/ 68.522 mill., es el de
# la Memoria 2014). La Memoria 2010 da el monto por moneda (S/ 24,243 mill. y US$ 6,029 mill.), sin total en soles: no entra.
FSD_PUBLISHED = {201112: (48_055, 34.3), 201212: (54_887, 34.8), 201312: (63_081, 33.2), 201412: (68_522, 36.4),
                 201512: (75_147, 32.6), 202412: (165_706, 39.9), 202512: (180_480, 41.4)}
# Grupos de tramos de la escala de montos, en múltiplos de la cobertura del FSD: (desde, hasta].
SCALE_GROUPS = [(0, 1), (1, 10), (10, 100), (100, np.inf)]

# Campos por ámbito. Montos en miles de S/ salvo almE/pcmE (miles de US$).
#   Liquidez: alN, pcN (MN); alE, pcE (ME).
#   RCL (%, publicado; solo meses de cierre de trimestre): rcl, rcN, rcE.
#   RFNE: fed, fer (financiación estable disponible y requerida).
#   Balance: dv, da, dp, dc (vista, ahorro, plazo con restringidos y sin CTS, CTS del público),
#     dsf (depósitos del sistema financiero y org. internacionales), dme (depósitos totales en ME),
#     ad (adeudos), va (valores en circulación), ot (otros pasivos), pat (patrimonio), pas (pasivo).
#   cr: créditos directos (ranking). nd: depositantes.
#   Adeudos por origen y plazo: apc, apl, aec, ael (país/exterior × corto/largo).
#   Escala (solo subsistemas y sistema): m0..m3 y n0..n3 (monto y depositantes por grupo de
#     tramos), cub (depósitos cubiertos, estimación), fsd (cobertura en soles; no se suma).
LIQ = ["alN", "pcN", "alE", "pcE"]
RCL = ["rcl", "rcN", "rcE"]
NSF = ["fed", "fer"]
BAL_DEP = ["dv", "da", "dp", "dc", "dsf", "dme"]
BAL_ALL = ["ad", "va", "ot", "pat", "pas"]
ADE = ["apc", "apl", "aec", "ael"]
SCALE = [f"m{i}" for i in range(4)] + [f"n{i}" for i in range(4)] + ["cub"]
AMOUNTS = LIQ + NSF + BAL_DEP + BAL_ALL + ["cr", "nd"] + ADE
# Qué subsistemas tienen que estar para que el sistema tenga dato en cada campo.
NEEDS_ALL5 = set(BAL_ALL + ADE + ["cr"])
DEC = {"rcl": 1, "rcN": 1, "rcE": 1}


def wide(df: pd.DataFrame, cols: list[str] = ("variable", "apertura")) -> pd.DataFrame:
    d = df[~df["es_total"]].copy()
    d["k"] = d[list(cols)].fillna("").astype(str).agg("|".join, axis=1)
    return d.pivot_table(index=KEY, columns="k", values="valor", aggfunc="first")


def published_totals(df: pd.DataFrame) -> pd.DataFrame:
    d = df[df["es_total"]].copy()
    d["k"] = d["variable"] + "|" + d["apertura"].fillna("")
    return d.pivot_table(index=["periodo", "subsistema"], columns="k", values="valor", aggfunc="first")


# ---------------------------------------------------------------- lectura
def load_liquidity() -> pd.DataFrame:
    w = wide(read_table(BOLETIN / "ratios-liquidez.parquet"))
    return pd.DataFrame({"alN": w["activos_liquidos|mn"], "pcN": w["pasivos_corto_plazo|mn"],
                         "alE": w["activos_liquidos|me"], "pcE": w["pasivos_corto_plazo|me"],
                         "rN": w["ratio_liquidez|mn"], "rE": w["ratio_liquidez|me"]})


def load_lcr() -> tuple[pd.DataFrame, pd.DataFrame]:
    d = read_table(BOLETIN / "ratio-cobertura-liquidez.parquet",
                        filters=[("variable", "==", "ratio_cobertura_liquidez")])
    names = {"total": "rcl", "mn": "rcN", "me": "rcE"}
    ent = d[~d["es_total"]].pivot_table(index=KEY, columns="apertura", values="valor", aggfunc="first").rename(columns=names)
    tot = d[d["es_total"]].pivot_table(index=["periodo", "subsistema"], columns="apertura", values="valor",
                                       aggfunc="first").rename(columns=names)
    return ent, tot


def load_nsfr() -> tuple[pd.DataFrame, pd.DataFrame]:
    d = read_table(BOLETIN / "ratio-financiacion-neta-estable.parquet")
    d = d[d["variable"].isin(["resumen_total_financiacion_estable_disponible",
                              "resumen_total_financiacion_estable_requerida", "ratio_financiacion_neta_estable"])]
    names = {"resumen_total_financiacion_estable_disponible": "fed",
             "resumen_total_financiacion_estable_requerida": "fer", "ratio_financiacion_neta_estable": "rfne"}
    ent = d[~d["es_total"]].pivot_table(index=KEY, columns="variable", values="valor", aggfunc="first").rename(columns=names)
    tot = d[d["es_total"]].pivot_table(index=["periodo", "subsistema"], columns="variable", values="valor",
                                       aggfunc="first").rename(columns=names)
    return ent, tot


BALANCE_VARS = [
    "obligaciones_publico_depositos_vista", "obligaciones_publico_depositos_ahorro",
    "obligaciones_publico_depositos_plazo", "obligaciones_publico_depositos_plazo_cts",
    "obligaciones_publico_depositos_restringidos", "obligaciones_publico_otras_obligaciones",
    "depositos_sistema_financiero", "fondos_interbancarios_pasivo", "adeudos",
    "obligaciones_circulacion_no_subordinadas", "obligaciones_circulacion_subordinadas",
    "cuentas_por_pagar", "intereses_por_pagar", "provisiones_pasivo", "otros_pasivos",
    "total_pasivo", "patrimonio", "total_pasivo_patrimonio",
    # Manual de Contabilidad anterior (hasta 2012-12): en lugar de `provisiones_pasivo` el balance trae
    # «Provisiones por créditos contingentes» (va a otros pasivos; con ella las capas cuadran en 100 %).
    "provisiones_creditos_contingentes",
]


def balance_items(w: pd.DataFrame, cur: str, deposits: pd.Series) -> pd.DataFrame:
    """Partidas del fondeo desde el balance (columnas `variable|moneda`)."""
    g = lambda v: w.get(f"{v}|{cur}", pd.Series(0.0, index=w.index)).fillna(0.0)  # noqa: E731
    out = pd.DataFrame(index=w.index)
    out["dv"] = g("obligaciones_publico_depositos_vista")
    out["da"] = g("obligaciones_publico_depositos_ahorro")
    out["dc"] = g("obligaciones_publico_depositos_plazo_cts")
    out["dp"] = g("obligaciones_publico_depositos_plazo") - out["dc"] + g("obligaciones_publico_depositos_restringidos")
    out["dsf"] = g("depositos_sistema_financiero")
    out["ad"] = g("adeudos")
    out["va"] = g("obligaciones_circulacion_no_subordinadas") + g("obligaciones_circulacion_subordinadas")
    out["ot"] = (g("obligaciones_publico_otras_obligaciones") + g("fondos_interbancarios_pasivo") + g("cuentas_por_pagar")
                 + g("intereses_por_pagar") + g("provisiones_pasivo") + g("provisiones_creditos_contingentes")
                 + g("otros_pasivos"))
    out["pat"] = g("patrimonio")
    out["pas"] = g("total_pasivo")
    # Empresas de créditos: no captan depósitos; sus depósitos restringidos (cifras mínimas) van a otros pasivos.
    nodep = ~deposits
    out.loc[nodep, "ot"] += out.loc[nodep, ["dv", "da", "dp", "dc", "dsf"]].sum(axis=1)
    out.loc[nodep, ["dv", "da", "dp", "dc", "dsf"]] = np.nan
    return out


def load_balance() -> tuple[pd.DataFrame, pd.DataFrame]:
    e = read_table(BOLETIN / "estados-financieros.parquet", filters=[("variable", "in", BALANCE_VARS)])
    e = e[e["apertura"].isin(["total", "me"])]
    w = wide(e)
    deposits = pd.Series(w.index.get_level_values("subsistema").isin(DEPOSIT_TAKERS), index=w.index)
    tot = balance_items(w, "total", deposits)
    me = balance_items(w, "me", deposits)
    tot["dme"] = me[["dv", "da", "dp", "dc", "dsf"]].sum(axis=1, min_count=1)
    # Identidad: las capas suman pasivo + patrimonio.
    tpp = w["total_pasivo_patrimonio|total"]
    layers = tot[["dv", "da", "dp", "dc", "dsf", "ad", "va", "ot", "pat"]].sum(axis=1)
    gap = (layers - tpp).abs()
    print(f"  Control balance: capas del fondeo = pasivo + patrimonio en {int((gap < 2).sum())} de {gap.notna().sum()} entidad-mes")
    pub = published_totals(e)
    return tot, pub


def load_credit() -> pd.Series:
    r = read_table(BOLETIN / "ranking-creditos-depositos-patrimonio.parquet",
                        filters=[("variable", "in", ["creditos_directos", "depositos_totales"])])
    r = r[~r["es_total"]].pivot_table(index=KEY, columns="variable", values="valor", aggfunc="first")
    return r


def load_depositors() -> tuple[pd.Series, pd.Series]:
    d = read_table(BOLETIN / "depositantes-tipo-deposito.parquet")
    d = d[d["apertura"].str.startswith("total|")]
    ent = d[~d["es_total"]].groupby(KEY)["valor"].sum(min_count=1)
    tot = d[d["es_total"]].groupby(["periodo", "subsistema"])["valor"].sum(min_count=1)
    return ent, tot


def load_debt_structure() -> pd.DataFrame:
    """Adeudos por origen (país / exterior) y plazo (corto / largo), en miles = % × total / 100."""
    d = read_table(BOLETIN / "adeudos-obligaciones-financieras.parquet")
    w = wide(d)
    total = w["adeudos_obligaciones_financieras|total|total"]
    out = pd.DataFrame(index=w.index)
    for col, ap in (("apc", "pais|corto_plazo"), ("apl", "pais|largo_plazo"),
                    ("aec", "exterior|corto_plazo"), ("ael", "exterior|largo_plazo")):
        out[col] = w.get(f"participacion_adeudos|{ap}", pd.Series(np.nan, index=w.index))
    s = out.sum(axis=1, min_count=1)
    # Entidades sin adeudos publican 0 en todo; los % de una entidad pueden no sumar 100 (error de origen).
    out = out.div(s.where(s > 0), axis=0).mul(total, axis=0)
    return out


def fsd_coverage_from_raw() -> pd.Series:
    """Cobertura del FSD (S/) que usa cada cuadro de escala de montos: límite «de X a más» / 100."""
    rows = {}
    for sub in DEPOSIT_TAKERS:
        for f in sorted((RAW / sub / "depositos-escala-montos").glob("*.XLS")):
            m = re.search(r"-([a-z]{2})(\d{4})\.XLS$", f.name, re.I)
            if not m:
                continue
            per = int(m.group(2)) * 100 + MONTH_CODE[m.group(1).lower()]
            if per < START_PERIOD:  # primer mes del tablero (visual_mora.START_PERIOD)
                continue
            g = pd.read_excel(f, header=None, sheet_name=0)
            lows = []
            for i in range(len(g)):
                cells = [v for v in g.iloc[i].tolist() if pd.notna(v)]
                txt = " ".join(str(v) for v in cells).lower()
                if txt.startswith("de") and re.search(r"a\s+m[aá]s", txt):
                    nums = [v for v in g.iloc[i].tolist()[:4] if isinstance(v, (int, float)) and pd.notna(v)]
                    if nums:
                        lows.append(float(nums[0]))
            if lows:
                rows[(per, sub)] = max(lows) / 100
    s = pd.Series(rows, name="fsd")
    s.index.names = ["periodo", "subsistema"]
    return s


def _bounds(tramo: str) -> tuple[float, float]:
    t = tramo.replace("fsd", "")
    if t.startswith("hasta_"):
        return 0.0, float(t[6:])
    a, b = t.split("_a_")
    return float(a), (np.inf if b == "mas" else float(b))


def load_scale(cover: pd.Series) -> pd.DataFrame:
    """Escala de montos por subsistema: monto y depositantes por grupo de tramos y depósitos cubiertos."""
    d = read_table(BOLETIN / "depositos-escala-montos.parquet")
    parts = d["apertura"].str.split("|", expand=True)
    d = d.assign(tipo=parts[0], dep=parts[1], tramo=parts[2])
    d = d[d["tramo"] != "total"]
    lo_hi = d["tramo"].map(_bounds)
    d["lo"], d["hi"] = lo_hi.str[0], lo_hi.str[1]
    idx = ["periodo", "subsistema"]
    out = pd.DataFrame(index=d[idx].drop_duplicates().set_index(idx).index).sort_index()
    tot = d[(d["tipo"] == "total") & (d["dep"] == "total")]
    for j, (a, b) in enumerate(SCALE_GROUPS):
        sel = tot[(tot["lo"] >= a) & (tot["hi"] <= b)]
        out[f"m{j}"] = sel[sel["variable"] == "depositos"].groupby(idx)["valor"].sum()
        out[f"n{j}"] = sel[sel["variable"] == "numero_depositantes"].groupby(idx)["valor"].sum()
    # Un tramo sin cifra (p. ej. cajas rurales sin depositantes de más de 100 veces la cobertura) es 0.
    out[[f"{c}{j}" for c in "mn" for j in range(4)]] = out[[f"{c}{j}" for c in "mn" for j in range(4)]].fillna(0.0)
    out["fsd"] = cover.reindex(out.index)

    def covered(rows: pd.DataFrame) -> pd.Series:
        """Σ monto de tramos ≤ 1 cobertura + depositantes de tramos mayores × cobertura (miles de S/)."""
        small = rows[(rows["hi"] <= 1) & (rows["variable"] == "depositos")].groupby(idx)["valor"].sum()
        big = rows[(rows["lo"] >= 1) & (rows["variable"] == "numero_depositantes")].groupby(idx)["valor"].sum()
        return small.reindex(out.index).fillna(0) + big.reindex(out.index).fillna(0) * out["fsd"] / 1000

    eligible = d[(d["tipo"] == "total") & d["dep"].isin(["personas_naturales", "pj_sin_fines_lucro"])]
    vista_pj = d[(d["tipo"] == "vista") & (d["dep"] == "pj_otras")]
    out["cub"] = covered(eligible) + covered(vista_pj)
    out.loc[out["fsd"].isna(), "cub"] = np.nan
    # Control: los tramos de «Depósitos totales» suman el total del bloque.
    blk = d[(d["tipo"] == "total") & (d["dep"] == "total") & (d["variable"] == "depositos")].groupby(idx)["valor"].sum()
    out["mt"] = blk
    return out


# ---------------------------------------------------------------- armado
def build_frame() -> tuple[pd.DataFrame, dict]:
    liq = load_liquidity()
    lcr_e, lcr_t = load_lcr()
    nsf_e, nsf_t = load_nsfr()
    bal, bal_pub = load_balance()
    cred = load_credit()
    nd_e, nd_t = load_depositors()
    ade = load_debt_structure()
    f = bal.join(liq, how="outer").join(lcr_e, how="left").join(nsf_e, how="left")
    f = f.join(cred.rename(columns={"creditos_directos": "cr", "depositos_totales": "dtr"}), how="left")
    f = f.join(nd_e.rename("nd"), how="left").join(ade, how="left")
    pub = {"lcr": lcr_t, "nsfr": nsf_t, "bal": bal_pub, "nd": nd_t}
    return f.reset_index(), pub


def checks(full: pd.DataFrame, pub: dict, scale: pd.DataFrame) -> list[str]:
    """Controles de los agregados propios contra los totales publicados; devuelve las líneas impresas."""
    lines = []
    agg = full.groupby(["periodo", "subsistema"]).sum(min_count=1, numeric_only=True)
    liq_pub = published_totals(read_table(BOLETIN / "ratios-liquidez.parquet"))
    for cur, a, p in (("MN", "alN", "pcN"), ("ME", "alE", "pcE")):
        calc = 100 * agg[a] / agg[p]
        gap = (calc - liq_pub[f"ratio_liquidez|{cur.lower()}"]).dropna().abs()
        lines.append(f"Ratio de liquidez {cur} agregado vs. total publicado: {len(gap)} subsistema-mes, "
                     f"máx. {gap.max():.3f} pp, {int((gap > 0.01).sum())} con diferencia > 0,01 pp")
    # RCL: la fórmula de la Res. SBS 4221-2023 (art. 25) aplicada a los promedios del trimestre. No es
    # exacta porque el publicado es el promedio de los ratios diarios: se informa la brecha.
    r = read_table(BOLETIN / "ratio-cobertura-liquidez.parquet")
    r = r[r["variable"].str.startswith("resumen_total") | (r["variable"] == "ratio_cobertura_liquidez")]
    r = r.assign(k=r["variable"] + "|" + r["apertura"]).pivot_table(
        index=["periodo", "subsistema", r["id_entidad"].fillna("_total")], columns="k", values="valor", aggfunc="first")
    for cur in ("mn", "me", "total"):
        A, E, S = (r[f"resumen_total_{v}|{cur}|ajustado"] for v in ("alac", "flujos_entrantes", "flujos_salientes"))
        calc = 100 * (A + np.minimum(E, 0.75 * S)) / S
        g = (calc - r[f"ratio_cobertura_liquidez|{cur}"]).dropna().abs()
        lines.append(f"RCL {cur.upper()} con la fórmula del art. 25 sobre promedios vs. publicado: {len(g)} filas, "
                     f"mediana {g.median():.2f} pp, {(g < 2).mean():.0%} a menos de 2 pp")
    gap = (agg["fed"] / agg["fer"] - pub["nsfr"]["rfne"]).dropna().abs()
    lines.append(f"RFNE agregado vs. publicado: {len(gap)} subsistema-mes, máx. {gap.max():.5f} veces")
    b = pub["bal"]
    dep_pub = (b["obligaciones_publico_depositos_vista|total"].fillna(0) + b["obligaciones_publico_depositos_ahorro|total"].fillna(0)
               + b["obligaciones_publico_depositos_plazo|total"].fillna(0) + b["obligaciones_publico_depositos_restringidos|total"].fillna(0)
               + b["depositos_sistema_financiero|total"].fillna(0))
    dep_calc = agg[["dv", "da", "dp", "dc", "dsf"]].sum(axis=1, min_count=1)
    for name, calc, p in (("Depósitos totales (balance)", dep_calc, dep_pub),
                          ("Adeudos (balance)", agg["ad"], b["adeudos|total"]),
                          ("Pasivo + patrimonio", agg[["dv", "da", "dp", "dc", "dsf", "ad", "va", "ot", "pat"]].sum(axis=1, min_count=1),
                           b["total_pasivo_patrimonio|total"])):
        r = (calc / p - 1).replace([np.inf, -np.inf], np.nan).dropna().abs()
        r = r[p.reindex(r.index) > 0]
        worst = r.sort_values().tail(3)
        lines.append(f"{name} suma de entidades vs. columna TOTAL: {len(r)} subsistema-mes, "
                     f"{int((r > 1e-4).sum())} con diferencia > 0,01 %"
                     + (" (mayores: " + ", ".join(f"{s} {p_} {v:.3%}" for (p_, s), v in worst[worst > 1e-4].items()) + ")"
                        if (worst > 1e-4).any() else ""))
    nd_gap = (agg["nd"] - pub["nd"]).dropna().abs()
    lines.append(f"Depositantes suma de entidades vs. TOTAL publicado: {len(nd_gap)} subsistema-mes, {int((nd_gap > 0.5).sum())} distintos")
    # Créditos / depósitos: con el ranking de créditos y los depósitos del balance; la SBS publica
    # depósitos / créditos solo para cajas (indicadores financieros).
    ind = read_table(BOLETIN / "indicadores-financieros.parquet",
                          filters=[("variable", "in", ["depositos_creditos_directos", "adeudos_pasivo_total"])])
    ind = ind[ind["es_total"]].pivot_table(index=["periodo", "subsistema"], columns="variable", values="valor")
    dc = (100 * dep_calc / agg["cr"] - ind["depositos_creditos_directos"]).dropna().abs()
    lines.append(f"Depósitos / créditos (cajas) vs. indicador publicado: {len(dc)} subsistema-mes, mediana {dc.median():.2f} pp, "
                 f"máx. {dc.max():.2f} pp")
    ap = (100 * agg["ad"] / agg["pas"] - ind["adeudos_pasivo_total"]).dropna().abs()
    lines.append(f"Adeudos / pasivo (cajas y EC) vs. indicador publicado: {len(ap)} subsistema-mes, mediana {ap.median():.2f} pp, "
                 f"máx. {ap.max():.2f} pp")
    sg = (scale[[f"m{i}" for i in range(4)]].sum(axis=1) / scale["mt"] - 1).dropna().abs()
    lines.append(f"Escala de montos: grupos de tramos vs. total del bloque: {len(sg)} subsistema-mes, máx. {sg.max():.2e}")
    tot = scale.groupby(level="periodo")[["cub", "mt"]].sum(min_count=1)
    for per, (mill, share) in FSD_PUBLISHED.items():
        if per in tot.index:
            c, t = tot.loc[per, "cub"], tot.loc[per, "mt"]
            lines.append(f"Depósitos cubiertos {month_key(per)}: estimación S/ {c / 1e3:,.0f} millones ({100 * c / t:.1f}%) vs. "
                         f"FSD S/ {mill:,} millones ({share}%)")
    miss = scale["fsd"].isna().sum()
    lines.append(f"Cobertura del FSD leída del Excel: {scale['fsd'].notna().sum()} subsistema-mes ({miss} sin dato)")
    for ln in lines:
        print("  " + ln)
    return lines


def series(g: pd.DataFrame, months: list[int], fields: list[str]) -> dict:
    """{a: índice del primer mes, V: {campo: [valores]}} para un ámbito."""
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
        d = DEC.get(col, 2 if col in ("rN", "rE") else 0)
        V[col] = [None if pd.isna(x) else (int(round(float(x))) if d == 0 else round(float(x), d)) for x in v]
    return {"a": a, "V": V}


def build_data() -> dict:
    full, pub = build_frame()
    cover = fsd_coverage_from_raw()
    scale = load_scale(cover)
    control = checks(full, pub, scale)
    months = month_range(int(full["periodo"].min()), int(full["periodo"].max()))

    names = pd.read_csv(ENTIDADES, dtype=str).set_index("id_entidad")["nombre_actual"]
    panel = read_table(PANEL, columns=["periodo", "subsistema", "id_entidad", "nombre_entidad"])
    last_name = panel.sort_values("periodo").groupby(["subsistema", "id_entidad"])["nombre_entidad"].last()

    scopes: dict[str, dict] = {}
    per_sub = {}
    scale_fields = SCALE + ["fsd"]
    for sub, label, _ in SUBSYSTEMS:
        g = full[full["subsistema"] == sub].groupby("periodo")[AMOUNTS].sum(min_count=1)
        # RCL y RFNE del subsistema: el publicado (el RCL no se puede agregar).
        if sub in DEPOSIT_TAKERS:
            g = g.join(pub["lcr"].xs(sub, level="subsistema"), how="left")
            if sub in scale.index.get_level_values("subsistema"):
                g = g.join(scale.xs(sub, level="subsistema")[scale_fields], how="left")
        per_sub[sub] = g
        scopes[sub] = {"n": label, "s": sub, **series(g.reset_index(), months, AMOUNTS + RCL + scale_fields)}
    # Sistema: suma de subsistemas; cada campo exige los cinco (fondeo) o los cuatro que captan depósitos.
    stack = pd.concat({s: g for s, g in per_sub.items()}, names=["subsistema", "periodo"])
    sysf = {}
    for col in AMOUNTS + SCALE:
        if col not in stack:
            continue
        need = [s for s, _, _ in SUBSYSTEMS] if col in NEEDS_ALL5 else DEPOSIT_TAKERS
        x = stack[col].unstack("subsistema").reindex(columns=need)
        sysf[col] = x.sum(axis=1, min_count=1).where(x.notna().all(axis=1))
    sysdf = pd.DataFrame(sysf).reset_index()
    scopes["sistema"] = {"n": "Sistema financiero", "s": None, **series(sysdf, months, AMOUNTS + SCALE)}
    # Mes por defecto del tablero: último mes en que el sistema tiene todos los campos del resumen
    # (liquidez, depósitos, créditos, adeudos y pasivo). Cada subsistema publica a su ritmo; el selector
    # sigue llegando al último mes publicado por alguno.
    kpi_fields = LIQ + BAL_DEP + ["cr", "ad", "pas"]
    all_last = int(sysdf.set_index("periodo")[kpi_fields].dropna().index.max())

    entities = []
    for (sub, ent), g in full.groupby(["subsistema", "id_entidad"]):
        block = series(g, months, AMOUNTS + RCL + ["rN", "rE"])
        if not block["V"]:
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

    # Ejemplo numérico del RCL para «Cómo leer los datos»: banca múltiple en MN, último trimestre.
    rcl_raw = read_table(BOLETIN / "ratio-cobertura-liquidez.parquet")
    rcl_raw = rcl_raw[rcl_raw["es_total"] & (rcl_raw["subsistema"] == "banca-multiple")]
    q = int(rcl_raw["periodo"].max())
    rq = rcl_raw[rcl_raw["periodo"] == q].set_index(["variable", "apertura"])["valor"]
    example_lcr = {"m": month_key(q), "A": round(float(rq[("resumen_total_alac", "mn|ajustado")])),
                   "E": round(float(rq[("resumen_total_flujos_entrantes", "mn|ajustado")])),
                   "S": round(float(rq[("resumen_total_flujos_salientes", "mn|ajustado")])),
                   "R": round(float(rq[("ratio_cobertura_liquidez", "mn")]), 1)}
    lcr_months = sorted(pub["lcr"].index.get_level_values("periodo").unique())
    nsfr_months = sorted(pub["nsfr"].index.get_level_values("periodo").unique())
    return {
        "months": [month_key(m) for m in months],
        "subs": [{"k": k, "l": l, "s": s} for k, l, s in SUBSYSTEMS],
        "dep": DEPOSIT_TAKERS,
        "scopes": scopes,
        "entities": entities,
        "lcrFrom": month_key(lcr_months[0]), "lcrTo": month_key(lcr_months[-1]),
        "nsfrFrom": month_key(nsfr_months[0]), "nsfrTo": month_key(nsfr_months[-1]),
        "lim": {k: [[month_key(m), v] for m, v in rows] for k, rows in LIMITS.items()},
        "exLcr": example_lcr,
        "hasta": month_key(months[-1]),
        "allHasta": month_key(all_last),
        "generado": dt.date.today().isoformat(),
        "_control": control,
    }


def summary(data: dict) -> None:
    """Cifras del último mes, para revisar a ojo."""
    M = data["months"]
    i = len(M) - 1

    def v(sc, f, j=i):
        s = data["scopes"][sc]
        a = s["V"].get(f)
        k = j - s["a"]
        return a[k] if a and 0 <= k < len(a) else None

    print(f"  Último mes: {M[i]}; el sistema tiene todo el resumen hasta {data['allHasta']} (mes por defecto)")
    for k in ["sistema"] + [s["k"] for s in data["subs"]]:
        n = data["scopes"][k]["n"]
        aln, pcn, ale, pce = (v(k, f) for f in LIQ)
        dep = sum(x or 0 for x in (v(k, f) for f in ["dv", "da", "dp", "dc", "dsf"])) or None
        tpp = sum(x or 0 for x in (v(k, f) for f in ["dv", "da", "dp", "dc", "dsf", "ad", "va", "ot", "pat"]))
        cr, dme, ad = v(k, "cr"), v(k, "dme"), v(k, "ad")
        fmt = lambda x, d=1: "   —  " if x is None else f"{x:6.{d}f}"  # noqa: E731
        print(f"    {n:<22} liq MN {fmt(aln and 100 * aln / pcn)}%  ME {fmt(ale and 100 * ale / pce)}%  "
              f"cré/dep {fmt(100 * cr / dep if cr and dep else None)}%  dolar. {fmt(100 * dme / dep if dme is not None and dep else None)}%  "
              f"dep/fondeo {fmt(dep and 100 * dep / tpp)}%  adeudos/fondeo {fmt(100 * ad / tpp if ad is not None else None)}%  "
              f"depósitos S/ {fmt(dep and dep / 1e6)} mil mill.")


def main() -> int:
    print("Armando datos de liquidez y fondeo...")
    data = build_data()
    summary(data)
    data.pop("_control")
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
