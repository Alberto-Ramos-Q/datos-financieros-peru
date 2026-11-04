"""Genera `outputs/mercado_ssff.html`: tablero público de la estructura del mercado de crédito
(concentración y alcance) del sistema financiero peruano.

Lee de `data/processed/` (correr antes `leer_boletin.py` y `leer_sf2103.py`):
- `boletin/ranking-creditos-depositos-patrimonio`: créditos directos, depósitos totales y patrimonio
  por entidad y mes (B-2332, B-3243, C-1205, C-2205, C-4217). Con ellos se calculan la participación de
  cada entidad, el índice de Herfindahl-Hirschman (HHI), la participación de las 4 mayores (C4) y el
  número de entidades, por subsistema y para el sistema (los 5 subsistemas; en depósitos, los 4 que
  captan).
- `boletin/deudores-tipo-credito`: número de deudores por entidad y tipo de crédito, y el total
  consolidado de cada subsistema (fila TOTAL: un deudor con créditos en dos entidades del subsistema
  cuenta una vez). Nunca se suman deudores entre entidades.
  Deudores de UNA entidad repetidos de otro mes (2026-11-03, `errores_origen.debtor_entity_errors`: CMAC Sullana
  2024-06, C-1231 con la nota «La información de CMAC Sullana corresponde al 31/05/2024»): la serie de la entidad queda
  sin deudores ese mes (`drop_debtor_source_errors(d, entities=True)`); los totales de subsistema y la suma de
  deudores de las entidades frente al SF-2103 usan las cifras publicadas (la SBS las suma). La página recibe
  `deuEntErr` y da el motivo en la ficha, el ranking, los gráficos y la tabla de la entidad.
- `boletin/creditos-tipo-situacion`: saldo de créditos directos por tipo (para el saldo por deudor). Solo se usan
  los totales por subsistema, así que no se enmascara nada (las cifras repetidas están en el total que publica la SBS).
- `boletin/depositantes-tipo-deposito` (2026-11-04): número de depositantes por entidad, tipo de depósito y tipo de
  persona (B-2373, B-3232, C-1250, C-2255). A diferencia de los deudores, la fila TOTAL de cada subsistema es la suma
  de sus entidades: quien tiene depósitos en dos entidades cuenta dos veces. Las entidad-mes que repiten las cifras de
  otro mes (`source_repeat_mask`) quedan sin dato en la serie de la entidad; el total del subsistema es el publicado.
- `boletin/depositos-escala-montos`: monto y número de depositantes del total de cada tipo de depósito y de persona,
  solo por subsistema; da el depósito promedio por depositante (monto ÷ número del mismo cuadro).
- `sf2103_deudores.parquet`: deudores únicos del sistema (SF-2103, trimestral desde 2019-12).
- `config/insumo_poblacion_adulta.csv`: población de 18 años a más (INEI, al 30 de junio). Se refresca sola desde
  `../descargas-inei/data/processed/poblacion_adulta.parquet` (solo lectura) cuando ese proyecto está al lado.
- `config/entidades/eventos_mercado.csv`: fusiones, absorciones, conversiones, ingresos y salidas
  (`src/eventos_mercado.py`).

Series de entidad y cifras repetidas de otro mes (`errores_origen.RANKING_REPEATS`): el ranking ya viene sin esas
entidad-mes (`drop_ranking_repeats`); los deudores, sin las de `debtor_entity_errors` (arriba). Las demás entidad-mes
de la lista traen deudores propios. `rkErr` lleva también la clave de la entidad y el mes repetido, para que la tabla
y la ficha de la entidad muestren su último dato válido con su mes y el motivo (regla «sin huecos»).

Genera además `outputs/mercado_ssff_artifact.html`, la versión para publicar como Artifact.

Uso:
    python visual_mercado.py
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
from visual_mora import (ENTIDADES, PROJECT_DIR, SUBSYSTEMS, artifact_version, load_stocks,  # noqa: E402
                         month_key, month_range, read_table)
from errores_origen import (DEBTOR_ENTITY_GAPS, DEBTOR_SOURCE_ERRORS, DEBTOR_TOTAL_ERRORS,  # noqa: E402
                            DEPOSIT_SCALE_ERRORS, DEPOSITOR_FIELD_ERRORS, DEPOSITOR_SOURCE_ERRORS, RANKING_REPEATS,
                            debtor_entity_errors, drop_debtor_source_errors, drop_ranking_repeats,
                            ranking_affected_months, ranking_blank_months, repeat_footnote, source_repeat_mask,
                            source_repeats)

BOLETIN = PROJECT_DIR / "data" / "processed" / "boletin"
SF2103 = PROJECT_DIR / "data" / "processed" / "sf2103_deudores.parquet"
DEPOSITORS = BOLETIN / "depositantes-tipo-deposito.parquet"
DEPOSIT_SCALE = BOLETIN / "depositos-escala-montos.parquet"
POPULATION_SOURCE = PROJECT_DIR.parent / "descargas-inei" / "data" / "processed" / "poblacion_adulta.parquet"
POPULATION = PROJECT_DIR / "config" / "insumo_poblacion_adulta.csv"   # copia que viaja con el proyecto
POPULATION_COLS = ["anio", "poblacion_total", "poblacion_18_mas", "tipo_cifra", "base_censal", "fuente", "cuadro_fuente"]
EVENTS = PROJECT_DIR / "config" / "entidades" / "eventos_mercado.csv"
TEMPLATE = PROJECT_DIR / "src" / "plantillas" / "mercado.html"
OUT = PROJECT_DIR / "outputs" / "mercado_ssff.html"
OUT_ARTIFACT = PROJECT_DIR / "outputs" / "mercado_ssff_artifact.html"
PLACEHOLDER = "/*__DATA__*/null"
# Comparación internacional (2026-11-03): salidas de src/internacional/construir_<pais>.py.
INTL_DIR = PROJECT_DIR / "data" / "processed" / "internacional"
INTL_COUNTRIES = [("PER", "Perú", "peru"), ("CHL", "Chile", "chile"), ("COL", "Colombia", "colombia"),
                  ("BRA", "Brasil", "brasil")]
# Una sola base contable por país en el tablero (decisión del usuario, 2026-11-03: Chile entra «consolidado»).
# Chile trae además colocaciones individuales 2022-2025, que quedan en el CSV y en docs/internacional/chile.md.
# Brasil: con y sin estatales son un cálculo propio del segmento bancario b1+b2 con el IF.data (conglomerado
# prudencial, 2015-2025, agregado el 2026-11-04). El RC4 oficial del SFN (`oficial_con_estatales`) existe desde
# 2019 con la misma base; 2015-2018 trae solo RC5 con otro perímetro (`base = no_especificada`) y no se empalma.
INTL_BASE = {"CHL": "consolidado", "BRA": "conglomerado_prudencial"}

KEY = ["periodo", "subsistema", "id_entidad"]
SUB_KEYS = [s for s, _, _ in SUBSYSTEMS]
DEPOSIT_TAKERS = ["banca-multiple", "empresas-financieras", "cajas-municipales", "cajas-rurales"]
# Variables del ranking: clave corta → variable del cuadro.
RANK_VARS = {"cr": "creditos_directos", "dep": "depositos_totales", "pat": "patrimonio"}
# Subsistemas que tienen que estar para que el sistema tenga dato (las EC no captan depósitos).
NEEDS = {"cr": SUB_KEYS, "pat": SUB_KEYS, "dep": DEPOSIT_TAKERS}
# Tipos de crédito de los cuadros de deudores (mismo orden que el tablero de mora).
DEBTOR_TYPES = ["total", "corporativos", "grandes_empresas", "medianas_empresas", "pequenas_empresas",
                "microempresas", "consumo", "hipotecarios"]
# Depositantes (2026-11-04): tipos de depósito del cuadro (las cajas no tienen «vista») y grupos de persona.
# Los tipos de persona son excluyentes, así que «all» es la suma de los tres; los tipos de depósito no (una persona con
# ahorro y CTS cuenta una vez en «total»).
DEPOSIT_TYPES = ["total", "ahorro", "plazo", "cts", "vista"]
PERSON_GROUPS = {"all": ["personas_naturales", "pj_sin_fines_lucro", "pj_otras"], "pn": ["personas_naturales"],
                 "pj": ["pj_sin_fines_lucro", "pj_otras"]}
DEPOSITOR_TEMA = "depositantes-tipo-deposito"
# Desde 2024-10 cambia la tipificación de los créditos a empresas (Res. SBS 2368-2023).
BUSINESS_RECLASS = 202410
# Errores de origen en los cuadros de deudores y en el ranking: en `errores_origen.py` (común a todos los scripts).
# Ranking: las entidad-mes en que la SBS repite las cifras de un mes anterior se quitan (`drop_ranking_repeats`); si
# la entidad pesa en su subsistema, ese subsistema-mes (y el sistema) queda sin concentración (`ranking_blank_months`).
# Fuentes de eventos que se muestran: solo sitios oficiales. Los demás enlaces del CSV (prensa, bases privadas,
# empresas, informes de clasificadoras) no salen en el tablero.
OFFICIAL_DOMAINS = ("sbs.gob.pe", "elperuano.pe", "gob.pe", "congreso.gob.pe")
# Enlaces del CSV que llevan a otra resolución (auditoría de textos del 2026-11-03): no se muestran.
MISMATCHED_LINKS = ("NL/2325762-1", "NL/2038327-1", "NL/1958339-1", "NL/2542604-1", "NL/2326960-1",
                    "resolucion-no-3775-2017")
# Referencias del HHI: Lineamientos para la calificación y análisis de las operaciones de concentración
# empresarial del INDECOPI (Res. 103-2022/CLC-INDECOPI, El Peruano 30-01-2023), § 2.3.1.2, pp. 42-43: menor
# probabilidad de riesgo para la competencia con IHH < 1 500, o entre 1 500 y 2 500 con aumento < 200, o > 2 500
# con aumento < 100. Son referencias para evaluar fusiones en un mercado relevante, no límites legales; el
# INDECOPI no usa las etiquetas «no / moderadamente / altamente concentrado» (son de las guías de EE. UU. de 2010).
# Detalle y otras autoridades: docs/mercado_metodologia.md. Solo se dibujan en créditos y depósitos (el patrimonio
# no es un mercado).
HHI_REFS = {"cuts": [1500, 2500], "vars": ["cr", "dep"],
            "labels": ["Por debajo de 1,500", "Entre 1,500 y 2,500", "Por encima de 2,500"],
            "lines": ["1,500 (INDECOPI)", "2,500 (INDECOPI)"]}
# Control: participación de los «4 bancos grandes» (BCP, BBVA, Scotiabank, Interbank) en créditos y depósitos de
# las empresas de operaciones múltiples (los 5 subsistemas), SBS, SF-2103 (dic-2019 p. 8; demás, p. 9, tabla
# «Estructura por Grupo»). Comparable con el C4 del sistema cuando esos 4 son los 4 mayores.
SBS_BIG4 = {201912: (72.8, 73.6), 202212: (73.0, 74.2), 202312: (72.1, 73.3), 202412: (72.6, 74.5),
            202512: (72.1, 74.7), 202606: (72.4, 75.0)}
# Referencia oficial de inclusión: SBS, «Perú: Reporte de Indicadores de Inclusión Financiera» (CIIF-0001) de
# jun-2026, p. 7: «Número de deudores / población adulta (%)», solo personas naturales (incluye mancomunados),
# adultos de 18 años a más, sistema financiero con Banco de la Nación y Agrobanco. Valores de junio de cada año.
SBS_CIIF = {202106: 29.48, 202206: 31.10, 202306: 32.63, 202406: 32.86, 202506: 34.98, 202606: 39.59}
# Rankings que el lector rechaza (cifras inválidas en todas las celdas): ese subsistema-mes y el sistema quedan sin dato.
RANKING_INVALID = {(201011, "cajas-rurales"): "el ranking de las cajas rurales de ese mes trae −999,999.99 en todas las celdas"}


# ---------------------------------------------------------------- lectura
def load_international() -> dict | None:
    """CR4, CR5 e IHH anuales (diciembre) de la banca por país y variante, de `data/processed/internacional`.

    Solo entran los países cuyo archivo existe; las variantes son `con_estatales`, `sin_estatales` y, en Brasil, además
    `oficial_con_estatales` (cifra publicada por el BCB para el SFN). Ver docs/internacional/ y el README.
    """
    num = lambda x, d=1: None if pd.isna(x) else round(float(x), d)
    countries, rows = [], []
    for code, name, stem in INTL_COUNTRIES:
        path = INTL_DIR / f"{stem}_concentracion.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path)
        df = df[df["variable"].isin(["creditos", "depositos"])]
        if df["base"].nunique() > 1:
            keep = INTL_BASE.get(code) or df["base"].value_counts().idxmax()
            df = df[df["base"] == keep]
        dup = df.duplicated(["anio", "variable", "variante"])
        if dup.any():
            raise ValueError(f"{path.name}: filas duplicadas por año, variable y variante")
        if df.empty:
            continue
        countries.append({"k": code, "l": name, "variants": sorted(df["variante"].unique()),
                          "base": {t: "/".join(sorted(g["base"].dropna().astype(str).unique()))
                                   for t, g in df.groupby("variante")}})
        for r in df.itertuples(index=False):
            rows.append({"p": code, "y": int(r.anio), "v": r.variable, "t": r.variante,
                         "n": None if pd.isna(r.n) else int(r.n), "cr4": num(r.cr4), "cr5": num(r.cr5),
                         "ihh": num(r.ihh, 0), "pe": num(r.peso_estatal)})
    return {"countries": countries, "rows": rows} if countries else None


def load_ranking() -> pd.DataFrame:
    """Montos del ranking por entidad y mes (miles de S/), columnas cr, dep, pat.
    Se descartan las filas sin ningún monto positivo (entidades que la SBS sigue listando en cero) y las
    entidad-mes que repiten las cifras de un mes anterior (`RANKING_REPEATS`)."""
    d = read_table(BOLETIN / "ranking-creditos-depositos-patrimonio.parquet",
                   filters=[("variable", "in", list(RANK_VARS.values()))])
    d = drop_ranking_repeats(d[~d["es_total"]])
    w = d.pivot_table(index=KEY, columns="variable", values="valor", aggfunc="first")
    w = w.rename(columns={v: k for k, v in RANK_VARS.items()})
    keep = (w[list(RANK_VARS)].fillna(0) > 0).any(axis=1)
    return w[keep].reset_index()


def load_published_shares() -> pd.DataFrame:
    """Participaciones publicadas. Sin los subsistema-mes con una entidad repetida: la SBS las calculó con la
    cifra vieja de esa entidad, que el tablero quita."""
    d = read_table(BOLETIN / "ranking-creditos-depositos-patrimonio.parquet",
                   filters=[("variable", "in", [f"participacion_{v}" for v in RANK_VARS.values()])])
    d = d[~d["es_total"]]
    d = d[~pd.Series(list(zip(d["periodo"], d["subsistema"])), index=d.index).isin(ranking_affected_months())]
    return d.pivot_table(index=KEY, columns="variable", values="valor", aggfunc="first")


def load_debtors() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(entidades: deudores totales por entidad y mes, sin las entidad-mes con deudores repetidos de otro mes;
    subsistemas: total consolidado por tipo; entidades con las cifras publicadas, para sumarlas como la SBS)."""
    d = drop_debtor_source_errors(read_table(BOLETIN / "deudores-tipo-credito.parquet"))
    ent_all = d[~d["es_total"] & (d["apertura"] == "total")].groupby(KEY)["valor"].sum().rename("deu").reset_index()
    bad = pd.Series(list(zip(ent_all["periodo"], ent_all["subsistema"], ent_all["id_entidad"])),
                    index=ent_all.index).isin(debtor_entity_errors() | set(DEBTOR_ENTITY_GAPS))
    print(f"  Deudores por entidad: {int(bad.sum())} entidad-mes sin dato por repetir otro mes "
          f"(errores_origen.debtor_entity_errors); totales de subsistema sin cambio")
    sub = d[d["es_total"]].pivot_table(index=["periodo", "subsistema"], columns="apertura", values="valor",
                                       aggfunc="first")
    # Entidad que falta en algunas columnas (errores_origen.DEBTOR_ENTITY_GAPS): el total del subsistema tampoco la
    # incluye, así que esas columnas del subsistema quedan sin dato ese mes.
    for (per, s, _), (cols, _why) in DEBTOR_ENTITY_GAPS.items():
        if (per, s) in sub.index:
            sub.loc[(per, s), [c for c in cols if c in sub.columns]] = np.nan
    return ent_all[~bad].reset_index(drop=True), sub, ent_all


def load_balances_by_type() -> pd.DataFrame:
    """Saldo de créditos directos por subsistema, mes y tipo (miles de S/). `load_stocks` ya trae el
    «total» y los subtotales (empresariales, consumo revolvente / no revolvente): no se vuelven a sumar."""
    s = load_stocks()
    return s.groupby(["periodo", "subsistema", "tipo"])["tot"].sum().unstack("tipo")


def load_depositors(months: list[int]) -> tuple[dict, dict, list, list[str]]:
    """Depositantes: (por subsistema y «sistema» = suma de los 4: {a, V: {n_<tipo>_<grupo>, a_<tipo>_<grupo>}};
    por entidad: {«subsistema/entidad»: {a, V: {pn, pj}}}; entidad-mes repetidas; líneas de control).

    n_: número de depositantes publicado (fila TOTAL = suma de las entidades). a_: depósito promedio por depositante en
    soles, monto ÷ número de la escala de montos (mismo cuadro). En el «sistema» un campo tiene dato solo si los cuatro
    subsistemas lo tienen ese mes (vista: solo banca y financieras, así que el sistema no lo tiene)."""
    d = read_table(DEPOSITORS)
    d = d[d["variable"] == "numero_depositantes"].copy()
    # Cuadro equivocado (errores_origen.DEPOSITOR_SOURCE_ERRORS): ese subsistema-mes queda sin dato.
    wrong = pd.Series(list(zip(d["periodo"], d["subsistema"])), index=d.index).isin(set(DEPOSITOR_SOURCE_ERRORS))
    d = d[~wrong]
    frac = d[(d["valor"] - d["valor"].round()).abs() > 1e-6]
    if len(frac):
        print("  AVISO: depositantes con decimales (¿otro cuadro?): "
              + ", ".join(f"{s} {p}" for p, s in sorted(set(zip(frac["periodo"], frac["subsistema"])))))
    d[["tdep", "tper"]] = d["apertura"].str.split("|", n=1, expand=True)
    # Celda imposible (errores_origen.DEPOSITOR_FIELD_ERRORS): sin dato en la entidad y en el total del subsistema.
    for (per, s, eid, ap) in DEPOSITOR_FIELD_ERRORS:
        hit = (d["periodo"] == per) & (d["subsistema"] == s) & (d["apertura"] == ap) & ((d["id_entidad"] == eid) | d["es_total"])
        d.loc[hit, "valor"] = np.nan
    tot = d[d["es_total"]].pivot_table(index=["periodo", "subsistema"], columns="apertura", values="valor", aggfunc="first")
    x = read_table(DEPOSIT_SCALE)
    x = x[x["es_total"] & x["apertura"].str.endswith("|total")].copy()
    x["ap"] = x["apertura"].str.rsplit("|", n=1).str[0]
    xm = x[x["variable"] == "depositos"].pivot_table(index=["periodo", "subsistema"], columns="ap", values="valor", aggfunc="first")
    xn = x[x["variable"] == "numero_depositantes"].pivot_table(index=["periodo", "subsistema"], columns="ap", values="valor",
                                                                aggfunc="first")
    assert set(x.loc[x["variable"] == "depositos", "unidad"]) == {"miles_soles"}, "unidad inesperada en la escala de montos"
    # Escala con el perímetro de otro mes (DEPOSIT_SCALE_ERRORS) y celda imposible (DEPOSITOR_FIELD_ERRORS): sin promedio.
    for w in (xm, xn):
        for key in DEPOSIT_SCALE_ERRORS:
            if key in w.index:
                w.loc[key, :] = np.nan
        for (per, s, _eid, ap) in DEPOSITOR_FIELD_ERRORS:
            if (per, s) in w.index:
                w.loc[(per, s), [c for c in (ap, ap.split("|")[0] + "|total") if c in w.columns]] = np.nan

    def grab(w, sub, cols):
        if sub not in w.index.get_level_values("subsistema") or not all(c in w for c in cols):
            return None
        return w.xs(sub, level="subsistema")[cols].sum(axis=1, min_count=len(cols))

    n_parts, m_parts, k_parts = {}, {}, {}
    for sub in DEPOSIT_TAKERS:
        for t in DEPOSIT_TYPES:
            for p, people in PERSON_GROUPS.items():
                n = grab(tot, sub, [f"{t}|{q}" for q in people])
                if n is not None:
                    n_parts[(sub, f"n_{t}_{p}")] = n
                sc = [f"{t}|total"] if p == "all" else [f"{t}|{q}" for q in people]
                m, k = grab(xm, sub, sc), grab(xn, sub, sc)
                if m is not None and k is not None:
                    m_parts[(sub, f"{t}_{p}")], k_parts[(sub, f"{t}_{p}")] = m, k
    out = {}
    for sub in DEPOSIT_TAKERS + ["sistema"]:
        g = pd.DataFrame(index=months)
        for t in DEPOSIT_TYPES:
            for p in PERSON_GROUPS:
                f = f"{t}_{p}"
                if sub == "sistema":
                    ns = [n_parts.get((s, "n_" + f)) for s in DEPOSIT_TAKERS]
                    ms = [m_parts.get((s, f)) for s in DEPOSIT_TAKERS]
                    ks = [k_parts.get((s, f)) for s in DEPOSIT_TAKERS]
                    n = None if any(v is None for v in ns) else pd.concat(ns, axis=1).reindex(months).sum(axis=1, min_count=4)
                    m = None if any(v is None for v in ms) else pd.concat(ms, axis=1).reindex(months).sum(axis=1, min_count=4)
                    k = None if any(v is None for v in ks) else pd.concat(ks, axis=1).reindex(months).sum(axis=1, min_count=4)
                else:
                    n, m, k = n_parts.get((sub, "n_" + f)), m_parts.get((sub, f)), k_parts.get((sub, f))
                if n is not None:
                    g["n_" + f] = n.reindex(months)
                if m is not None and k is not None:
                    g["a_" + f] = (m * 1000 / k.where(k > 0)).reindex(months)
        out[sub] = series(g.dropna(how="all"), months, list(g.columns))

    # Entidades: solo «total» de depósitos, por grupo de persona; sin las entidad-mes que repiten otro mes.
    e = d[~d["es_total"] & d["id_entidad"].notna() & (d["tdep"] == "total")]
    bad = source_repeat_mask(e, DEPOSITOR_TEMA)
    w = e[~bad].pivot_table(index=KEY, columns="tper", values="valor", aggfunc="first")
    w["pn"] = w["personas_naturales"]
    w["pj"] = w[PERSON_GROUPS["pj"]].sum(axis=1, min_count=2)
    ent = {}
    for (sub, eid), g in w.reset_index().groupby(["subsistema", "id_entidad"]):
        g = g.set_index("periodo").sort_index()
        if not (g[["pn", "pj"]].fillna(0) > 0).any().any():
            continue
        ent[f"{sub}/{eid}"] = series(g, months, ["pn", "pj"])
    rep = []
    for k, r in sorted(source_repeats(DEPOSITOR_TEMA).items()):
        if k[0] >= int(months[0]):
            note = repeat_footnote(r)
            rep.append([month_key(k[0]), f"{k[1]}/{k[2]}", month_key(r["same_as"]),
                        "nota al pie del cuadro: " + note if note else "sin nota al pie"])

    # Controles: suma de entidades (con las cifras publicadas) vs. fila TOTAL; número de la escala vs. este cuadro.
    lines = []
    s_ent = d[~d["es_total"]].groupby(["periodo", "subsistema", "apertura"])["valor"].sum()
    s_tot = d[d["es_total"]].groupby(["periodo", "subsistema", "apertura"])["valor"].sum(min_count=1)
    gap = (s_ent - s_tot).dropna().abs()
    lines.append(f"Depositantes, suma de entidades vs. TOTAL publicado: {len(gap)} subsistema-mes-apertura, "
                 f"{int((gap > 0.5).sum())} distintos")
    xr = []
    for (sub, f), k in k_parts.items():
        n = n_parts.get((sub, "n_" + f))
        if n is not None:
            xr.append((k / n.reindex(k.index) - 1).dropna().abs())
    xr = pd.concat(xr)
    lines.append(f"Depositantes, escala de montos vs. cuadro de depositantes: {len(xr)} subsistema-mes-campo, "
                 f"{int((xr > 0.001).sum())} con diferencia > 0,1 % (el promedio usa el número de la escala)")
    lines.append(f"Depositantes por entidad: {int(bad.sum())} filas sin dato por repetir otro mes ({len(rep)} entidad-mes), "
                 f"{len(ent)} series de entidad; {int(wrong.sum())} filas sin dato por cuadro equivocado "
                 f"({len(DEPOSITOR_SOURCE_ERRORS)} subsistema-mes)")
    for ln in lines:
        print("  " + ln)
    return out, ent, rep, lines


def load_sf2103() -> pd.DataFrame:
    sf = pd.read_parquet(SF2103)
    return sf.pivot_table(index="periodo", columns="grupo", values="deudores", aggfunc="first")


def load_population() -> pd.DataFrame | None:
    """Población de 18 años a más por año (INEI, al 30 de junio). None si aún no existe el insumo."""
    if POPULATION_SOURCE.exists():   # refrescar la copia de config/ desde descargas-inei
        new = pd.read_parquet(POPULATION_SOURCE, columns=POPULATION_COLS).to_csv(index=False, lineterminator="\n")
        if not POPULATION.exists() or POPULATION.read_text(encoding="utf-8") != new:
            POPULATION.write_text(new, encoding="utf-8")
    if not POPULATION.exists():
        print(f"  AVISO: falta {POPULATION.name} (población adulta); el tablero sale sin deudores por adulto")
        return None
    return pd.read_csv(POPULATION)


def join_resolutions(text: str) -> str:
    """«Res. SBS 03341-2024 y Res. SBS 03376-2024 y Res. SBS 3370-2024» → «Res. SBS 3341-2024, 3376-2024 y 3370-2024»:
    sin ceros a la izquierda en el número, sin repetir y con el prefijo una sola vez cuando todas lo comparten."""
    parts = [re.sub(r"(?<![\d-])0+(\d)", r"\1", x.strip()) for x in text.split(" y ") if x.strip()]
    parts = list(dict.fromkeys(parts))
    m = [re.fullmatch(r"(Res\. SBS(?: N\.° ?)?)\s*(\d+-\d{4})", x) for x in parts]
    if len(parts) > 1 and all(m) and len({x.group(1).strip() for x in m}) == 1:
        nums = [x.group(2) for x in m]
        return m[0].group(1).strip() + " " + ", ".join(nums[:-1]) + " y " + nums[-1]
    return " y ".join(parts)


def load_events(rk: pd.DataFrame) -> list[dict]:
    """Un registro por evento; los que tocan dos subsistemas (una fila por subsistema en el CSV) se juntan
    en `ss`, con primero el subsistema donde figura la entidad (`id_entidad`) ese mes o el siguiente."""
    if not EVENTS.exists():
        print(f"  AVISO: falta {EVENTS}; el tablero sale sin eventos")
        return []
    e = pd.read_csv(EVENTS, dtype=str).fillna("")
    where = rk.groupby(["periodo", "id_entidad"])["subsistema"].first()
    out = []
    for (per, eid, rel, tipo, lab), g in e.groupby(["periodo", "id_entidad", "id_entidad_relacionada", "tipo", "etiqueta_corta"], sort=False):
        ss = list(dict.fromkeys(g["subsistema"]))
        per = int(per)
        home = next((where.get((m, eid)) for m in month_range(per, per + 1 if per % 100 < 12 else per + 89)
                     if where.get((m, eid)) in ss), None)
        if home:
            ss = [home] + [x for x in ss if x != home]
        r = g.iloc[0]
        parts = [x.strip() for x in r["fuente"].replace(" | ", " ; ").split(" ; ") if x.strip()]
        keep = [x for x in parts if not x.startswith("http") or
                (any(dm in x.split("/")[2] for dm in OFFICIAL_DOMAINS) and "extranet.sbs.gob.pe/iece" not in x
                 and not any(b in x for b in MISMATCHED_LINKS))]
        res = " y ".join(x.strip() for x in r["resolucion"].split(";") if x.strip())
        out.append({"m": month_key(per), "s": ss[0], "ss": ss, "id": eid, "rel": rel, "t": tipo,
                    "l": lab.replace(" Del Centro", " del Centro"), "res": res, "src": " ; ".join(keep), "c": r["confianza"]})
    # Dos filas del CSV para un mismo hecho (misma entidad y mes): se juntan, con la etiqueta de la absorción o fusión.
    merged: dict = {}
    for ev in out:
        k = (ev["m"], ev["id"])
        if k not in merged:
            merged[k] = ev
            continue
        a = merged[k]
        a["ss"] = list(dict.fromkeys(a["ss"] + ev["ss"]))
        if ev["t"] in ("absorcion", "fusion") and a["t"] not in ("absorcion", "fusion"):
            for f in ("t", "l", "rel"):
                a[f] = ev[f]
        a["res"] = " y ".join(dict.fromkeys(x for x in (a["res"] + " y " + ev["res"]).split(" y ") if x))
        a["src"] = " ; ".join(dict.fromkeys(x for x in (a["src"] + " ; " + ev["src"]).split(" ; ") if x))
    out = sorted(merged.values(), key=lambda x: (x["m"], x["s"]))
    for ev in out:
        ev["res"] = join_resolutions(ev["res"])
    print(f"  Eventos: {len(out)} ({len(e)} filas del CSV)")
    return out


def short_name(n: str) -> str:
    """Nombre corto, con el estilo de los cuadros (p. ej. «Caja Rural de Ahorro y Crédito X S.A.A.» → «CRAC X»)."""
    n = n.replace("Caja Rural de Ahorro y Crédito ", "CRAC ")
    for suf in (" S.A.A.", " S.A."):
        if n.endswith(suf):
            n = n[: -len(suf)]
    return n


# ---------------------------------------------------------------- cálculos
def concentration(v: pd.Series) -> dict:
    """HHI (0-10 000), C4 (%), número de entidades con monto positivo y la mayor, para un vector de
    montos por entidad. Los montos negativos (patrimonio negativo) cuentan como cero."""
    v = v.clip(lower=0)
    v = v[v > 0]
    if v.empty:
        return {}
    s = 100 * v / v.sum()
    top = s.sort_values(ascending=False)
    return {"hhi": float((s ** 2).sum()), "c4": float(top.iloc[:4].sum()), "n": int(len(s)),
            "t1": float(top.iloc[0]), "t1id": top.index[0], "tot": float(v.sum())}


def build_concentration(rk: pd.DataFrame, months: list[int]) -> tuple[dict, dict]:
    """Series de concentración por ámbito (sistema y subsistemas) y el último mes de cada variable en el
    sistema (todos los subsistemas que hacen falta). Los subsistema-mes de `ranking_blank_months` (una entidad
    con peso repite las cifras de otro mes) quedan sin dato, y el sistema también si le hace falta ese subsistema."""
    blank = ranking_blank_months()
    out: dict[str, dict] = {}
    sys_last = {}
    pos = {m: i for i, m in enumerate(months)}
    present = {var: rk[rk[var].fillna(0) > 0].groupby("periodo")["subsistema"].agg(set) for var in RANK_VARS}
    for scope in ["sistema"] + SUB_KEYS:
        V: dict[str, list] = {}
        for var in RANK_VARS:
            if scope == "sistema":
                x = rk
                ok = present[var].apply(lambda s, need=NEEDS[var]: set(need) <= s)
                valid = set(ok[ok].index) - {p for p, s in blank if s in NEEDS[var]}
                if valid:
                    sys_last[var] = max(valid)
            else:
                x = rk[rk["subsistema"] == scope]
                valid = set(x["periodo"]) - {p for p, s in blank if s == scope}
            rows = {m: concentration(g.set_index(g["subsistema"] + "/" + g["id_entidad"])[var].dropna())
                    for m, g in x.groupby("periodo") if m in valid}
            for f in ("hhi", "c4", "n", "t1", "t1id", "tot"):
                arr = [None] * len(months)
                for m, r in rows.items():
                    if r:
                        val = r[f]
                        arr[pos[m]] = (round(val, 3) if f in ("hhi",) else round(val, 4) if f in ("c4", "t1")
                                       else int(round(val)) if f in ("tot", "n") else val)
                V[f"{f}_{var}"] = arr
        a = next((i for i in range(len(months)) if any(V[k][i] is not None for k in V)), 0)
        out[scope] = {"a": a, "V": {k: v[a:] for k, v in V.items() if any(x is not None for x in v)}}
    return out, sys_last


def series(g: pd.DataFrame, months: list[int], fields: list[str], dec: dict | None = None) -> dict:
    """{a: índice del primer mes, V: {campo: [valores]}} para un ámbito (g indexado por periodo)."""
    dec = dec or {}
    pos = {m: i for i, m in enumerate(months)}
    present = [m for m in g.index if m in pos]
    if not present:
        return {"a": 0, "V": {}}
    a, b = pos[min(present)], pos[max(present)]
    V = {}
    for col in fields:
        if col not in g:
            continue
        v = g[col].reindex(months[a:b + 1])
        if v.notna().sum() == 0:
            continue
        d = dec.get(col, 0)
        V[col] = [None if pd.isna(x) else (int(round(float(x))) if d == 0 else round(float(x), d)) for x in v]
    return {"a": a, "V": V}


def checks(rk: pd.DataFrame, conc: dict, months: list[int], deu_sub: pd.DataFrame, sf: pd.DataFrame,
           bal: pd.DataFrame) -> list[str]:
    """Controles contra lo publicado; devuelve las líneas impresas."""
    lines = []
    pub = load_published_shares()
    x = rk.set_index(KEY)
    for var, name in RANK_VARS.items():
        v = x[var].clip(lower=0)
        share = 100 * v / v.groupby(level=["periodo", "subsistema"]).transform("sum")
        p = pub.get(f"participacion_{name}")
        if p is None:
            continue
        gap = (share - p.reindex(share.index)).dropna().abs()
        big = gap[gap > 0.05]
        lines.append(f"Participación en {name} calculada vs. publicada: {len(gap)} entidad-mes, mediana {gap.median():.4f} pp, "
                     f"máx. {gap.max():.2f} pp, {len(big)} con diferencia > 0,05 pp"
                     + (" (mayores: " + ", ".join(f"{s} {e} {p_}: {g:.2f}" for (p_, s, e), g in big.sort_values().tail(3).items()) + ")"
                        if len(big) else ""))
    # Créditos del ranking vs. saldo de créditos por tipo y situación (suma de entidades).
    # Sin los subsistema-mes con una entidad repetida (el ranking ya no la trae y el otro cuadro sí, o con otra cifra).
    rc = x["cr"].groupby(level=["periodo", "subsistema"]).sum()
    rc = rc[~rc.index.isin(list(ranking_affected_months()))]
    tc = bal["total"]
    r = (rc / tc - 1).dropna().abs()
    lines.append(f"Créditos directos del ranking vs. créditos por tipo y situación: {len(r)} subsistema-mes "
                 f"(sin los {len(ranking_affected_months())} con una entidad repetida), mediana {r.median():.4%}, "
                 f"{int((r > 0.001).sum())} con diferencia > 0,1 %"
                 + (" (mayores: " + ", ".join(f"{s} {p_} {g:.2%}" for (p_, s), g in r.sort_values().tail(3).items()) + ")" if (r > 0.001).any() else ""))
    # Deudores: total del subsistema del boletín vs. SF-2103.
    gaps = []
    for per in sf.index:
        for s in SUB_KEYS:
            if (per, s) in deu_sub.index and s in sf.columns and pd.notna(sf.loc[per, s]):
                gaps.append(abs(deu_sub.loc[(per, s), "total"] - sf.loc[per, s]))
    gaps = pd.Series(gaps)
    lines.append(f"Deudores por subsistema, boletín vs. SF-2103: {len(gaps)} subsistema-trimestre, {int((gaps > 0).sum())} distintos")
    tot = deu_sub["total"].unstack("subsistema")
    for per in (201912, 202103):
        if per in sf.index and per in tot.index:
            lines.append(f"Duplicación entre subsistemas {month_key(per)}: {tot.loc[per, SUB_KEYS].sum() / sf.loc[per, 'operaciones-multiples']:.3f} "
                         f"(README: {'1,370' if per == 201912 else '1,302'})")
    cs = conc["sistema"]
    for per, (c_pub, d_pub) in SBS_BIG4.items():
        if per in months:
            i = months.index(per) - cs["a"]
            c, d = cs["V"]["c4_cr"][i], cs["V"]["c4_dep"][i]
            lines.append(f"C4 del sistema {month_key(per)} vs. «4 bancos grandes» del SF-2103: créditos {c:.1f}% vs. {c_pub}%, "
                         f"depósitos {d:.1f}% vs. {d_pub}%")
    for ln in lines:
        print("  " + ln)
    return lines


def build_data() -> dict:
    rk = load_ranking()
    last = int(rk["periodo"].max())
    months = month_range(int(rk["periodo"].min()), last)
    conc, sys_last = build_concentration(rk, months)
    deu_ent, deu_sub, deu_ent_all = load_debtors()
    bal = load_balances_by_type()
    sf = load_sf2103()
    control = checks(rk, conc, months, deu_sub, sf, bal)
    dpt, dpt_ent, dpt_rep, dpt_lines = load_depositors(months)
    control += dpt_lines

    names = pd.read_csv(ENTIDADES, dtype=str).set_index("id_entidad")["nombre_actual"]
    panel = read_table(PROJECT_DIR / "data" / "processed" / "panel_entidad_mes.parquet",
                       columns=["periodo", "subsistema", "id_entidad", "nombre_entidad"])
    last_name = panel.sort_values("periodo").groupby(["subsistema", "id_entidad"])["nombre_entidad"].last()
    panel_name = panel.drop_duplicates(["periodo", "subsistema", "id_entidad"]).set_index(
        ["periodo", "subsistema", "id_entidad"])["nombre_entidad"]

    # Entidades: montos del ranking y deudores.
    ent = rk.merge(deu_ent, on=KEY, how="outer")
    entities, scopes = [], {}
    for (sub, eid), g in ent.groupby(["subsistema", "id_entidad"]):
        block = series(g.set_index("periodo").sort_index(), months, ["cr", "dep", "pat", "deu"])
        if not block["V"]:
            continue
        k = f"{sub}/{eid}"
        scopes[k] = {"n": short_name(last_name.get((sub, eid)) or names.get(eid, eid)), "s": sub, "id": eid, **block}
        entities.append(k)
    by_id: dict[str, list[str]] = {}
    for k in entities:
        by_id.setdefault(scopes[k]["id"], []).append(k)
    for ks in by_id.values():
        if len(ks) > 1:
            for k in ks:
                scopes[k]["o"] = [x for x in ks if x != k]
    # Nombre de la mayor entidad de cada ámbito (t1id → nombre vigente).
    for sc in conc.values():
        for f, arr in list(sc["V"].items()):
            if f.startswith("t1id_"):
                sc["V"][f] = [None if v is None else scopes.get(v, {}).get("n", names.get(v.split("/", 1)[1], v)) for v in arr]

    # Deudores y saldos por subsistema y tipo.
    deu = {}
    for sub in SUB_KEYS:
        g = pd.DataFrame(index=sorted(set(deu_sub.index.get_level_values("periodo"))))
        if sub in deu_sub.index.get_level_values("subsistema"):
            d = deu_sub.xs(sub, level="subsistema")
            for t in DEBTOR_TYPES:
                if t in d:
                    g["n_" + t] = d[t]
        if sub in bal.index.get_level_values("subsistema"):
            b = bal.xs(sub, level="subsistema")
            g = g.join(b[[t for t in DEBTOR_TYPES if t in b]].add_prefix("s_"), how="outer")
        deu[sub] = series(g.dropna(how="all"), months, list(g.columns), {c: 2 for c in g.columns if c.startswith("s_")})
    # SF-2103 (trimestral): deudores únicos del sistema y de cada subsistema. La duplicación entre
    # subsistemas se calcula con las filas del propio SF-2103 (coinciden con el boletín salvo EC 2022-03,
    # error de origen del Excel C-4226, que repite las cifras de abril).
    # Suma de los deudores de todas las entidades (cada deudor cuenta una vez por entidad en que tiene crédito):
    # solo meses con los cinco subsistemas.
    # Con las cifras publicadas de cada entidad (también la repetida de CMAC Sullana 2024-06, que la SBS suma).
    ent_sum = deu_ent_all.groupby(["periodo", "subsistema"])["deu"].sum().unstack("subsistema")
    ent_sum = ent_sum.reindex(columns=SUB_KEYS).sum(axis=1, min_count=1).where(ent_sum.reindex(columns=SUB_KEYS).notna().all(axis=1))
    sf_rows = []
    for per, r in sf.sort_index().iterrows():
        sf_rows.append({"m": month_key(int(per)), "eom": int(r["operaciones-multiples"]), "sf": int(r["sistema-financiero"]),
                        "be": None if pd.isna(r.get("banca-estatal")) else int(r["banca-estatal"]),
                        "subs": {s: int(r[s]) for s in SUB_KEYS if s in r and pd.notna(r[s])},
                        "ent": None if pd.isna(ent_sum.get(per)) else int(ent_sum.get(per))})

    pop = load_population()
    pop_rows = None
    if pop is not None:
        pop_rows = [[int(r.anio), int(r.poblacion_18_mas)] for r in pop.sort_values("anio").itertuples(index=False)]

    # Entidades que repiten en el ranking las cifras de otro mes: [mes, subsistema, nombre de ese mes, acción,
    # «subsistema/entidad», mes repetido].
    rk_err = []
    for r in sorted(RANKING_REPEATS, key=lambda r: (r["periodo"], r["subsistema"])):
        nm = panel_name.get((r["periodo"], r["subsistema"], r["id_entidad"])) or last_name.get((r["subsistema"], r["id_entidad"]))
        rk_err.append([month_key(r["periodo"]), r["subsistema"], short_name(nm or names.get(r["id_entidad"], r["id_entidad"])),
                       r["action"], f"{r['subsistema']}/{r['id_entidad']}", month_key(r["same_as"])])
    # Entidades cuyos deudores repiten los de otro mes: [mes, «subsistema/entidad», mes repetido, motivo].
    deu_ent_err = []
    for k, r in sorted(source_repeats("deudores-tipo-credito").items()):
        if k in debtor_entity_errors() and k[0] >= int(months[0]):
            note = repeat_footnote(r)
            deu_ent_err.append([month_key(k[0]), f"{k[1]}/{k[2]}", month_key(r["same_as"]),
                                "nota al pie del cuadro: " + note if note else "sin nota al pie"])
    # Entidad que falta en el cuadro (DEBTOR_ENTITY_GAPS): sin mes repetido; el motivo va completo.
    for (per, s, eid), (_cols, why) in sorted(DEBTOR_ENTITY_GAPS.items()):
        deu_ent_err.append([month_key(per), f"{s}/{eid}", None, why])

    all_last = sys_last.get("cr", last)
    return {
        "months": [month_key(m) for m in months],
        "subs": [{"k": k, "l": l, "s": s} for k, l, s in SUBSYSTEMS],
        "dep": DEPOSIT_TAKERS,
        "conc": conc,
        "scopes": scopes,
        "entities": entities,
        "deu": deu,
        "sf": sf_rows,
        "pop": pop_rows,
        "events": load_events(rk),
        "refs": HHI_REFS,
        "big4": [[month_key(k), c, d] for k, (c, d) in SBS_BIG4.items()],
        "ciif": [[month_key(k), v] for k, v in SBS_CIIF.items()],
        "reclass": month_key(BUSINESS_RECLASS),
        "deuErr": [[month_key(m), sub] for m, sub in sorted(DEBTOR_SOURCE_ERRORS)],
        "deuTotErr": [[month_key(m), sub] for m, sub in sorted(DEBTOR_TOTAL_ERRORS)],
        "rkErr": rk_err,
        "deuEntErr": deu_ent_err,
        "dpt": dpt,
        "dptEnt": {k: ({**v, "n": short_name(last_name.get(tuple(k.split("/", 1))) or names.get(k.split("/", 1)[1], k))}
                       if k not in scopes else v) for k, v in dpt_ent.items()},
        "dptErr": dpt_rep,
        "dptSubErr": [[month_key(m), s, why] for (m, s), why in sorted(DEPOSITOR_SOURCE_ERRORS.items())],
        # Otras notas de depositantes: [mes, subsistema, vista ('n', 'a' o 'na'), tipos de depósito, grupos, motivo].
        "dptNotes": [[month_key(m), s, "a", [], [], why] for (m, s), why in sorted(DEPOSIT_SCALE_ERRORS.items())]
        + [[month_key(m), s, "na", [ap.split("|")[0]], ["pj", "all"], why]
           for (m, s, _e, ap), why in sorted(DEPOSITOR_FIELD_ERRORS.items())],
        "deuGap": [[month_key(m), s, cols, why] for (m, s, _e), (cols, why) in sorted(DEBTOR_ENTITY_GAPS.items())],
        "rkBad": [[month_key(m), s, why] for (m, s), why in sorted(RANKING_INVALID.items())],
        "sysLast": {k: month_key(v) for k, v in sys_last.items()},
        "hasta": month_key(last),
        "allHasta": month_key(all_last),
        "intl": load_international(),
        "generado": dt.date.today().isoformat(),
        "_control": control,
    }


def summary(data: dict) -> None:
    """Cifras para revisar a ojo: HHI y C4 de créditos en diciembre de algunos años y el último mes."""
    M = data["months"]

    def v(sc, f, m):
        s = data["conc"][sc]
        i = M.index(m) - s["a"]
        a = s["V"].get(f)
        return a[i] if a and 0 <= i < len(a) else None

    marks = [m for m in M if m.endswith("-12") and int(m[:4]) % 5 == 0] + [data["allHasta"]]
    print("  HHI de créditos directos (C4 entre paréntesis):")
    for sc in ["sistema"] + SUB_KEYS:
        cells = []
        for m in marks:
            h, c = v(sc, "hhi_cr", m), v(sc, "c4_cr", m)
            cells.append(f"{m}: {h:7.0f} ({c:4.1f}%)" if h is not None else f"{m}:      —        ")
        print(f"    {sc:<22} " + "  ".join(cells))
    s = data["sf"][-1]
    print(f"  Deudores únicos {s['m']}: EOM {s['eom']:,} · sistema financiero {s['sf']:,}")


def main() -> int:
    print("Armando datos de la estructura del mercado de crédito...")
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
    print(f"  {data['months'][0]} a {data['hasta']} (sistema completo hasta {data['allHasta']}), "
          f"{len(data['entities'])} series de entidad, {len(data['events'])} eventos, datos {len(payload) / 1e6:.2f} MB")
    print(f"  Escrito {OUT.relative_to(PROJECT_DIR)} y {OUT_ARTIFACT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
