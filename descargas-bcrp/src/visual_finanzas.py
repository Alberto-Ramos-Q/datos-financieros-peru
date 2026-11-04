"""Genera `outputs/finanzas_publicas.html`: tablero de las finanzas públicas del Perú.

Lee los paneles de `data/processed/` (correr antes `descargar_series.py` y `construir_tablas.py`),
la población por departamento de `config/insumo_inei_departamentos.csv` (copia de `../descargas-inei`,
que se refresca sola si ese proyecto está al lado) y los límites departamentales de `data/raw/geo/`
(`descargar_geo.py`; el mapa lo arma `mapa_departamental.py`). Arma los datos que usa la página y los inyecta en la plantilla
`src/plantillas/finanzas.html`. El HTML resultante es autocontenido.

Cálculos propios (todos con cifras oficiales del BCRP):
- Flujos acumulados en 12 meses como % del PBI. El denominador es el PBI nominal de 12 meses
  implícito en la serie oficial del resultado económico en 12 meses (% del PBI, PN39524FM):
  PBI12 = resultado económico acumulado en 12 meses / (porcentaje oficial / 100). Así los cocientes
  usan el mismo PBI que el BCRP, también en los meses que aún no tienen PBI trimestral. Se controla
  contra la suma de 4 trimestres del PBI nominal en los cierres de trimestre.
- Variaciones reales: sobre las series del BCRP en soles de diciembre de 2021.
- Inversión pública acumulada en el año y valores por departamento y por habitante.

Uso:
    python visual_finanzas.py
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mapa_departamental import build_geo  # noqa: E402  (mismo mapa que el tablero del PBI)
from visual_reservas import artifact_version  # noqa: E402

PROJECT_DIR = Path(__file__).resolve().parents[1]
PROCESSED = PROJECT_DIR / "data" / "processed"
INEI = PROJECT_DIR.parent / "descargas-inei" / "data" / "processed"
DEP_INPUT = PROJECT_DIR / "config" / "insumo_inei_departamentos.csv"   # copia que viaja con el proyecto
DEP_INPUT_COLS = ["anio", "ubigeo_dpto", "departamento", "ambito", "precios", "poblacion", "fuente_poblacion"]
TEMPLATE = PROJECT_DIR / "src" / "plantillas" / "finanzas.html"
OUT = PROJECT_DIR / "outputs" / "finanzas_publicas.html"
OUT_ARTIFACT = PROJECT_DIR / "outputs" / "finanzas_publicas_artifact.html"
PLACEHOLDER = "/*__DATA__*/null"
START = "2003-01"
WARNINGS: list[str] = []


def warn(msg: str) -> None:
    WARNINGS.append(msg)
    print("  AVISO:", msg)


def load_panel(freq: str) -> pd.DataFrame:
    df = pd.read_csv(PROCESSED / f"bcrp_panel_{freq}.csv", parse_dates=["fecha"], encoding="utf-8-sig")
    return df.set_index("fecha").sort_index()


def num(v, nd: int = 4):
    """Valor JSON seguro: None para vacíos e infinitos. Por defecto 4 decimales, para que la página redondee una sola
    vez (con 2 decimales, 3.4495 → 3.45 → «3.5%» en pantalla)."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if not np.isfinite(f) else round(f, nd)


def arr(s: pd.Series, index, nd: int = 4) -> list:
    return [num(v, nd) for v in s.reindex(index)]


def month_key(ts) -> str:
    return f"{ts.year:04d}-{ts.month:02d}"


def quarter_key(ts) -> str:
    return f"{ts.year:04d}-T{(ts.month - 1) // 3 + 1}"


def roll12(s: pd.Series) -> pd.Series:
    """Suma de 12 meses; solo donde están los 12 meses."""
    return s.rolling(12, min_periods=12).sum()


# ---------------------------------------------------------------------------------------------
# PBI nominal de 12 meses (denominador de los cocientes mensuales)
# ---------------------------------------------------------------------------------------------
def pbi12(m: pd.DataFrame, q: pd.DataFrame) -> pd.Series:
    re12 = roll12(m["resultado_economico_spnf"])
    pct = m["spnf_res_econ_12m_pct_pbi"]
    implied = re12 / (pct / 100)
    # Donde el resultado es casi cero, el cociente es inestable: se descarta y se interpola.
    implied[(pct.abs() < 0.3) | (re12.abs() < 500)] = np.nan
    # Control: suma de 4 trimestres del PBI nominal, asignada al último mes de cada trimestre.
    pq = q["pbi_nominal_trim"].dropna().rolling(4, min_periods=4).sum().dropna()
    pq.index = pq.index + pd.offsets.MonthBegin(2)
    both = pd.concat([implied, pq], axis=1, keys=["imp", "q"]).dropna()
    if len(both):
        dev = (both.imp / both.q - 1).abs() * 100
        print(f"  PBI 12 meses implícito vs 4 trimestres: desvío medio {dev.mean():.2f}%, máx. {dev.max():.2f}% "
              f"({len(both)} cierres de trimestre; último {month_key(both.index.max())})")
        if dev.tail(8).max() > 1.5:
            warn("el PBI implícito se aleja más de 1.5% de la suma trimestral en los últimos 2 años")
    # Relleno: en los huecos, interpolación log-lineal entre valores conocidos (implícitos o trimestrales).
    base = implied.combine_first(pq.reindex(implied.index))
    filled = np.exp(np.log(base).interpolate(limit_area="inside"))
    return filled


def share(flow: pd.Series, den: pd.Series) -> pd.Series:
    return roll12(flow) / den * 100


def real_yoy12(s: pd.Series) -> pd.Series:
    """Variación real de la suma de 12 meses frente a la de 12 meses antes (%)."""
    r = roll12(s)
    return (r / r.shift(12) - 1) * 100


def ytd_real(s: pd.Series) -> dict:
    """Variación real acumulada en el año: enero hasta el último mes frente al mismo periodo del año anterior."""
    s = s.dropna()
    last = s.index.max()
    cur = s[(s.index.year == last.year) & (s.index.month <= last.month)].sum()
    prev = s[(s.index.year == last.year - 1) & (s.index.month <= last.month)].sum()
    return {"v": num((cur / prev - 1) * 100, 1), "m": month_key(last)}


# ---------------------------------------------------------------------------------------------
# Mensual
# ---------------------------------------------------------------------------------------------
def build_monthly(m: pd.DataFrame, q: pd.DataFrame):
    den = pbi12(m, q)
    last = m["resultado_economico_spnf"].dropna().index.max()
    months = pd.date_range(START + "-01", last, freq="MS")
    S = {
        "re12": arr(m["spnf_res_econ_12m_pct_pbi"], months),
        "rp12": arr(share(m["resultado_primario_spnf"], den), months),
        "int12": arr(share(m["spnf_intereses"], den), months),
        "ing12": arr(share(m["ingresos_corrientes_gg"], den), months),
        "trib12": arr(share(m["ingresos_tributarios_gg"], den), months),
        "gnf12": arr(share(m["spnf_gnf"], den), months),
        "corr12": arr(share(m["spnf_gnf_corriente"], den), months),
        "cap12": arr(share(m["spnf_gnf_capital"], den), months),
        "fbk12": arr(share(m["spnf_gnf_capital_fbk"], den), months),
        # Variación real de 12 meses (sumas móviles en soles de dic-2021)
        "ing_r": arr(real_yoy12(m["ing_gg_total_ingresos_corrientes_real"]), months, 1),
        "trib_r": arr(real_yoy12(m["ing_gg_trib_real"]), months, 1),
        "ir_r": arr(real_yoy12(m["ing_gg_trib_gn_ir_real"]), months, 1),
        "igv_r": arr(real_yoy12(m["ing_gg_trib_gn_igv_real"]), months, 1),
        "gnf_r": arr(real_yoy12(m["gnf_gg_gnf_total_real"]), months, 1),
        "corr_r": arr(real_yoy12(m["gnf_gg_corr_real"]), months, 1),
        "fbk_r": arr(real_yoy12(m["gnf_gg_capital_fbk_real"]), months, 1),
    }
    # Control: el resultado primario propio + intereses ≈ resultado económico oficial (en % del PBI).
    re_own = share(m["resultado_economico_spnf"], den)
    gap = (re_own - m["spnf_res_econ_12m_pct_pbi"]).abs().dropna()
    print(f"  control: resultado económico propio vs oficial (12 m, % PBI): dif. máx. {gap.max():.3f} pp")
    if gap.max() > 0.05:
        warn("el resultado económico calculado no reproduce la serie oficial (> 0.05 pp)")
    return months, S, den


# ---------------------------------------------------------------------------------------------
# Composición anual (oficial, % del PBI) + últimos 12 meses (propio)
# ---------------------------------------------------------------------------------------------
TAX_KEYS = [  # (clave, etiqueta, serie anual % PBI, serie mensual millones)
    ("igv", "IGV", "ing_gg_trib_igv_pct_pbi_anual", "ing_gg_trib_gn_igv"),
    ("ir", "Impuesto a la renta", "ing_gg_trib_ir_pct_pbi_anual", "ing_gg_trib_gn_ir"),
    ("isc", "ISC", "ing_gg_trib_isc_pct_pbi_anual", "ing_gg_trib_gn_isc"),
    ("imp", "Aranceles", "ing_gg_trib_importaciones_pct_pbi_anual", "ing_gg_trib_gn_importaciones"),
    ("otr", "Otros tributos", "ing_gg_trib_otros_trib_pct_pbi_anual", "ing_gg_trib_gn_otros_trib"),
    ("dev", "Devoluciones", "ing_gg_trib_documentos_valorados_pct_pbi_anual", "ing_gg_trib_gn_devoluciones"),
]
SPEND_KEYS = [
    ("rem", "Remuneraciones", "gasto_gg_corr_remuneraciones_pct_pbi_anual", "gnf_gg_corr_remuneraciones"),
    ("bys", "Bienes y servicios", "gasto_gg_corr_bys_pct_pbi_anual", "gnf_gg_corr_bys"),
    ("tra", "Transferencias", "gasto_gg_corr_transferencias_pct_pbi_anual", "gnf_gg_corr_transferencias"),
    ("fbk", "Inversión pública", "gasto_gg_capital_fbk_pct_pbi_anual", "gnf_gg_capital_fbk"),
    ("ocap", "Otros gastos de capital", "gasto_gg_capital_otros_pct_pbi_anual", "gnf_gg_capital_otros"),
]


def build_annual(m: pd.DataFrame, a: pd.DataFrame, den: pd.Series, last_m) -> dict:
    years = a.index.year
    A = {"P": [str(y) for y in years]}
    for k, col in [("re", "spnf_res_econ_pct_pbi_anual"), ("rp", "spnf_res_prim_pct_pbi_anual"),
                   ("int", "spnf_intereses_pct_pbi_anual"), ("inv", "spnf_inversion_publica_pct_pbi_anual"),
                   ("trib", "ing_gg_trib_pct_pbi_anual"), ("ing", "ing_gg_total_pct_pbi_anual"),
                   ("gnf", "gasto_gg_gnf_total_pct_pbi_anual"), ("gcorr", "gasto_gg_corr_pct_pbi_anual"),
                   ("deuda", "deuda_total_pct_pbi_anual"), ("dneta", "deuda_neta_deuda_neta_pct_pbi_anual")]:
        A[k] = arr(a[col], a.index) if col in a else None
        if col not in a:
            warn(f"falta la serie anual {col}")
    for keys, tot in [(TAX_KEYS, "ing_gg_trib_pct_pbi_anual"), (SPEND_KEYS, "gasto_gg_gnf_total_pct_pbi_anual")]:
        for k, _, col, _ in keys:
            A["c_" + k] = arr(a[col], a.index)
        parts = sum(a[col].fillna(0) for _, _, col, _ in keys)
        ok = a[tot].notna() & a[[c for _, _, c, _ in keys]].notna().any(axis=1)
        dif = (parts[ok] - a[tot][ok]).abs()
        print(f"  control anual: partes vs total ({tot}): dif. máx. {dif.max():.2f} pp en {dif.idxmax().year}")
    # Últimos 12 meses (propio): mismas partes con los flujos mensuales, en el último mes en que existen el
    # denominador y todos los componentes (si una serie llega atrasada, se retrocede un mes en vez de fallar).
    cols = [mc for keys in (TAX_KEYS, SPEND_KEYS) for *_, mc in keys] + ["ing_gg_trib_gl", "ing_gg_trib", "gnf_gg_gnf_total"]
    okm = den.dropna().index
    for c in cols:
        okm = okm.intersection(roll12(m[c]).dropna().index)
    if len(okm) and okm.max() < last_m:
        warn(f"últimos 12 meses por tipo: se usa {month_key(okm.max())} (alguna serie no llega a {month_key(last_m)})")
    if len(okm):
        last_m = min(last_m, okm.max())
    lt = {"m": month_key(last_m)}
    for keys in (TAX_KEYS, SPEND_KEYS):
        for k, _, _, mcol in keys:
            flow = m[mcol]
            if k == "otr":   # en las series anuales, «otros» incluye los tributos municipales
                flow = flow + m["ing_gg_trib_gl"]
            lt["c_" + k] = num(share(flow, den).get(last_m))
    lt["trib"] = num(share(m["ing_gg_trib"], den).get(last_m))
    lt["gnf"] = num(share(m["gnf_gg_gnf_total"], den).get(last_m))
    for keys, tot in [(TAX_KEYS, "trib"), (SPEND_KEYS, "gnf")]:
        parts = [lt["c_" + k] for k, *_ in keys]
        if None in parts or lt[tot] is None:
            warn(f"control últimos 12 meses ({tot}): faltan datos")
            continue
        print(f"  control últimos 12 meses: partes vs total ({tot}): dif. {abs(sum(parts) - lt[tot]):.3f} pp")
    A["last12"] = lt
    return A


def build_ingresos_comp(m: pd.DataFrame, last_m) -> dict:
    """Ingresos corrientes del gobierno general en los últimos 12 meses (S/ millones)."""
    items = [("Impuesto a la renta: empresas", "ing_gg_trib_gn_ir_pj"), ("Impuesto a la renta: personas", "ing_gg_trib_gn_ir_pn"),
             ("Impuesto a la renta: regularización", "ing_gg_trib_gn_ir_regularizacion"),
             ("IGV interno", "ing_gg_trib_gn_igv_interno"), ("IGV a las importaciones", "ing_gg_trib_gn_igv_importaciones"),
             ("ISC", "ing_gg_trib_gn_isc"), ("Aranceles", "ing_gg_trib_gn_importaciones"),
             ("Otros tributos", "ing_gg_trib_gn_otros_trib"), ("Tributos municipales", "ing_gg_trib_gl"),
             ("Devoluciones", "ing_gg_trib_gn_devoluciones"),
             ("Contribuciones sociales", "ing_gg_contribuciones_sociales"), ("Canon y regalías", "ing_gg_canon_y_regalias"),
             ("Recursos propios y transferencias", "ing_gg_rec_propios_transf"), ("Otros no tributarios", "ing_gg_otros"),
             ("No tributarios regionales y locales", None)]
    out = []
    for lab, col in items:
        if col is None:
            v = roll12(m["ing_gg_no_trib_gr"]).get(last_m, np.nan) + roll12(m["ing_gg_no_trib_gl"]).get(last_m, np.nan)
        else:
            v = roll12(m[col]).get(last_m, np.nan)
        out.append({"label": lab, "v": num(v, 0), "trib": col is not None and col.startswith("ing_gg_trib")})
    tot = roll12(m["ing_gg_total_ingresos_corrientes"]).get(last_m)
    s = sum(o["v"] or 0 for o in out)
    print(f"  control: composición de ingresos suma {s:,.0f} vs total {tot:,.0f} (dif. {s - tot:,.0f})")
    return {"m": month_key(last_m), "items": out, "total": num(tot, 0)}


def build_inv_ytd(m: pd.DataFrame) -> dict:
    """Inversión pública (formación bruta de capital) del gobierno general por nivel, enero al último
    mes de cada año, en millones de soles de diciembre de 2021."""
    cols = {"gn": "gnf_gg_capital_fbk_gn_real", "gr": "gnf_gg_capital_fbk_gr_real", "gl": "gnf_gg_capital_fbk_gl_real"}
    d = m[list(cols.values())].dropna(how="all")
    last = d.dropna().index.max()
    sub = d[d.index.month <= last.month]
    g = sub.groupby(sub.index.year).sum(min_count=1)
    g = g[g.index >= d.dropna().index.min().year]
    out = {"m": month_key(last), "P": [str(y) for y in g.index]}
    for k, c in cols.items():
        out[k] = [num(v, 0) for v in g[c]]
    tot = g.sum(axis=1)
    out["var"] = num((tot.iloc[-1] / tot.iloc[-2] - 1) * 100, 1)
    return out


# ---------------------------------------------------------------------------------------------
# Deuda (trimestral)
# ---------------------------------------------------------------------------------------------
def build_debt(q: pd.DataFrame) -> dict:
    cols = {"bruta": "deuda_publica_pct_pbi", "neta": "deuda_deuda_neta_del_sector_publico_no_financiero_pct_pbi",
            "ext": "deuda_externa_pct_pbi", "int": "deuda_interna_pct_pbi"}
    d = q[list(cols.values())].dropna(how="all")
    out = {"P": [quarter_key(t) for t in d.index]}
    for k, c in cols.items():
        out[k] = arr(d[c], d.index)
    # Participación de no residentes en los bonos (en %; cociente de saldos en millones).
    for k, tot, nr in [("nr_sob", "deuda_bonos_soberanos_mill", "deuda_bonos_soberanos_no_residentes_mill"),
                       ("nr_glob", "deuda_bonos_globales_mill", "deuda_bonos_globales_no_residentes_mill")]:
        if tot in q and nr in q:
            out[k] = arr(q[nr] / q[tot] * 100, d.index, 1)
        else:
            warn(f"faltan {tot} o {nr}")
            out[k] = None
    dif = (q["deuda_externa_pct_pbi"] + q["deuda_interna_pct_pbi"] - q["deuda_publica_pct_pbi"]).abs().dropna()
    print(f"  control deuda: externa + interna vs total (% PBI): dif. máx. {dif.max():.3f} pp")
    return out


# ---------------------------------------------------------------------------------------------
# Departamentos
# ---------------------------------------------------------------------------------------------
def slug(t: str) -> str:
    t = unicodedata.normalize("NFKD", t.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]+", "_", t).strip("_")


REG_PREFIX = {"ri": "recaud_internos", "igv": "recaud_igv", "ir": "recaud_ir",
              "ign": "inv_gn", "igr": "inv_gr", "igl": "inv_gl", "ggr": "gnf_gr", "ggl": "gnf_gl"}


def build_regions(m: pd.DataFrame) -> dict | None:
    pc = inei_departments()
    if pc is None:
        warn("sin población departamental (config/insumo_inei_departamentos.csv); se omite la pestaña de regiones")
        return None
    pop = (pc[(pc.precios == "corrientes") & pc.ambito.isin(["departamento", "nacional"])]
           .pivot_table(index="anio", columns="ubigeo_dpto", values="poblacion"))
    names = (pc[pc.ambito.isin(["departamento"])].drop_duplicates("ubigeo_dpto")
             .set_index("ubigeo_dpto")["departamento"].to_dict())
    by_slug = {slug(n): c for c, n in names.items()}
    last_i = m[[c for c in m.columns if c.startswith("inv_gr_")]].dropna(how="all").index.max()
    last_r = m[[c for c in m.columns if c.startswith("recaud_internos_")]].dropna(how="all").index.max()
    last = min(last_i, last_r)   # último mes común: el año parcial suma los mismos meses en todos los indicadores
    if last_i != last_r:
        warn(f"regiones: inversión a {month_key(last_i)} y recaudación a {month_key(last_r)}; se corta en {month_key(last)}")
    m = m[m.index <= last]
    years = list(range(2008, last.year + 1))
    # Sumas anuales; el año en curso, de enero al último mes con datos.
    units = {c: {"code": c, "name": n} for c, n in sorted(names.items())}
    nat = {"code": "00", "name": "Perú"}
    official: dict[str, pd.Series] = {}
    # Partes de Lima que el BCRP publica por separado y se suman en el departamento de Lima (15).
    lima_parts = {"municipalidad_metropolitana_de_lima", "lima_metropolitana", "lima_provincias"}
    unmatched = set()
    for key, pre in REG_PREFIX.items():
        cols = [c for c in m.columns if c.startswith(pre + "_")]
        sub = m[cols]
        # Sumas anuales; el año en curso, de enero al último mes común (ver arriba). min_count=1: un año con algún
        # mes faltante se suma igual (el BCRP publica estas series sin huecos; si aparecieran, revisar).
        g = sub.groupby(sub.index.year).sum(min_count=1).reindex(years)
        acc: dict[str, pd.Series] = {}
        for c in cols:
            dep = c[len(pre) + 1:]
            if dep == "total":
                official[key] = g[c]
                continue
            code = "15" if dep in lima_parts else by_slug.get(dep)
            if code is None:
                unmatched.add(c)
                continue
            acc[code] = g[c] if code not in acc else acc[code].add(g[c], fill_value=0)
        for code, s in acc.items():
            units[code][key] = [num(v, 1) for v in s]
        # Perú = suma de los departamentos (el total del BCRP tiene errores de origen; ver README).
        nat[key] = [num(v, 1) for v in pd.concat(acc.values(), axis=1).sum(axis=1, min_count=1)]
    if unmatched:
        warn("columnas departamentales sin ubigeo: " + ", ".join(sorted(unmatched)))
    for u in list(units.values()) + [nat]:
        code = "00" if u is nat else u["code"]
        p = pop[code].reindex(years).ffill()   # años sin proyección: última población disponible
        u["pob"] = [num(v, 0) for v in p]
    # Control: suma de departamentos vs total publicado por el BCRP.
    for key, tot in official.items():
        d = (pd.Series(nat[key], index=years, dtype=float) - tot).abs()
        bad = d[d > 1]
        print(f"  control regiones {key}: suma de departamentos vs total del BCRP: {len(bad)} año(s) con dif. > 1 millón"
              + (f"; máx. {bad.max():,.1f} en {bad.idxmax()} (total BCRP {tot[bad.idxmax()]:,.1f})" if len(bad) else ""))
    pop_last = int(pop.index.max())
    return {"years": years, "partial": {"y": last.year, "m": month_key(last)} if last.month < 12 else None,
            "recaud_m": month_key(last_r), "pop_last": pop_last,
            "units": list(units.values()), "nat": nat}


# ---------------------------------------------------------------------------------------------
# v2: ejecución presupuestal del MEF (Consulta Amigable)
# ---------------------------------------------------------------------------------------------
MEF_RAW = PROJECT_DIR / "data" / "raw" / "mef_ejecucion"
MEF_NUM = ["pia", "pim", "certificacion", "compromiso_anual", "atencion_compromiso_mensual", "devengado", "girado"]


def read_mef(year: int, tipo: str, vista: str) -> pd.DataFrame | None:
    p = MEF_RAW / str(year) / f"{tipo}__{vista}.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p, dtype=str, encoding="utf-8").fillna("")
    for c in MEF_NUM:
        df[c] = pd.to_numeric(df[c].str.replace(",", ""), errors="coerce") / 1e6   # millones de soles
    df["avance_pct"] = pd.to_numeric(df["avance_pct"], errors="coerce")
    return df


LOWER = {"de", "del", "y", "e", "la", "las", "los", "el", "en", "a", "con", "para"}


# La Consulta Amigable escribe sin tildes; se reponen en las palabras que aparecen en los sectores.
TILDES = {"identificacion": "identificación", "educacion": "educación", "produccion": "producción",
          "construccion": "construcción", "promocion": "promoción", "inclusion": "inclusión", "economia": "economía",
          "republica": "república", "energia": "energía", "defensoria": "defensoría", "contraloria": "contraloría",
          "publico": "público", "publica": "pública", "comunicaciones": "comunicaciones", "informacion": "información",
          "elecciones": "elecciones", "organizacion": "organización", "nacion": "nación", "proteccion": "protección"}


SECTOR_OFICIAL = {"Presidencia Consejo Ministros": "Presidencia del Consejo de Ministros",
                  "Vivienda Construcción y Saneamiento": "Vivienda, Construcción y Saneamiento",
                  "Agrario y de Riego": "Desarrollo Agrario y Riego", "Ambiental": "Ambiente",
                  "Contraloría General": "Contraloría General de la República",
                  "Registro Nacional de Identificación y Estado Civil": "Reniec"}


def nice_title(t: str) -> str:
    words = [TILDES.get(w, w) for w in t.strip().lower().split()]
    out = " ".join(w if (i and w in LOWER) else w[:1].upper() + w[1:] for i, w in enumerate(words))
    return SECTOR_OFICIAL.get(out, out)


def inei_departments() -> pd.DataFrame | None:
    """Población al 30 de junio y nombre de cada departamento (INEI), a precios corrientes. Lee la copia de
    `config/insumo_inei_departamentos.csv`; si `../descargas-inei` está al lado, antes la refresca desde
    `pbi_departamental_per_capita.parquet` (solo lectura)."""
    src = INEI / "pbi_departamental_per_capita.parquet"
    if src.exists():
        pc = pd.read_parquet(src, columns=DEP_INPUT_COLS)
        pc = pc[(pc.precios == "corrientes") & pc.ambito.isin(["departamento", "nacional"])]
        new = pc.to_csv(index=False, lineterminator="\n")
        if not DEP_INPUT.exists() or DEP_INPUT.read_text(encoding="utf-8") != new:
            DEP_INPUT.write_text(new, encoding="utf-8")
    if not DEP_INPUT.exists():
        return None
    return pd.read_csv(DEP_INPUT, dtype={"ubigeo_dpto": str, "poblacion": "Int64"})


def dep_names() -> dict:
    """Nombres de departamento del INEI (con tildes) por código de ubigeo."""
    pc = inei_departments()
    if pc is None:
        return {}
    return pc[pc.ambito == "departamento"].drop_duplicates("ubigeo_dpto").set_index("ubigeo_dpto")["departamento"].to_dict()


DEP_NAMES = dep_names()


def build_ejecucion() -> dict | None:
    if not MEF_RAW.exists():
        warn("sin datos de ejecución del MEF (correr descargar_ejecucion_mef.py); se omite la pestaña")
        return None
    required = [f"{t}__{v}.csv" for t in ("todo", "proyectos")
                for v in ["nivel", "nivel_E__mes", "nivel_M__mes", "nivel_R__mes", "nivel_E__sector",
                          "nivel_R__departamento", "nivel_M__departamento", "departamento"]]
    complete = lambda y: all((MEF_RAW / str(y) / f).exists() and (MEF_RAW / str(y) / f).stat().st_size > 200 for f in required)  # noqa: E731
    years = sorted(int(p.name) for p in MEF_RAW.iterdir() if p.is_dir() and p.name.isdigit() and complete(int(p.name)))
    if not years:
        warn("ejecución del MEF incompleta; se omite la pestaña de presupuesto")
        return None
    man_path = PROJECT_DIR / "data" / "_control" / "manifest_mef_ejecucion.csv"
    if not man_path.exists():
        warn("sin manifest de la descarga del MEF; se omite la pestaña de presupuesto")
        return None
    man = pd.read_csv(man_path, encoding="utf-8")

    def corte_de(y):
        """Fecha de corte del año y: la más antigua entre las últimas descargas de cada vista necesaria
        (así no se mezclan vistas de fechas distintas)."""
        mm = man[(man.anio == y) & man.vista.isin([v for v in ["nivel", "nivel_E__mes", "nivel_M__mes", "nivel_R__mes"]])]
        if mm.empty:
            return None
        return pd.to_datetime(mm.groupby(["tipo", "vista"]).descargado_en.max()).min().date()

    cur = years[-1]
    corte = corte_de(cur)
    if corte is None:
        warn(f"manifest sin descargas de {cur}; se omite la pestaña de presupuesto")
        return None
    last_full = corte.month - 1 if corte.year == cur else 12    # último mes completo
    if last_full == 0:   # enero: el año nuevo aún no tiene un mes completo; se muestra el año anterior cerrado
        warn(f"{cur} aún sin un mes completo; se muestra {cur - 1}")
        years = [y for y in years if y < cur]
        cur = years[-1]
        corte = corte_de(cur) or corte
        last_full = 12
    # Años cerrados bajados antes de terminar: su curva quedaría cortada y contaminaría el promedio.
    stale = [y for y in years if y < cur and (corte_de(y) or dt.date.max) < dt.date(y + 1, 1, 15)]
    if stale:
        warn(f"años cerrados bajados antes de su cierre (correr el descargador con --refrescar): {stale}")
    out = {"years": years, "cur": cur, "corte": corte.isoformat(), "mes_completo": last_full, "tipos": {}}
    for tipo in ["todo", "proyectos"]:
        T = {"nivel": {}, "curvas": {}}
        for y in years:
            nv = read_mef(y, tipo, "nivel")
            if nv is None:
                continue
            nv = nv.set_index("codigo")
            row = {lv: {"pim": num(nv.at[lv, "pim"], 1), "dev": num(nv.at[lv, "devengado"], 1),
                        "av": num(nv.at[lv, "avance_pct"], 1)} for lv in ["E", "M", "R"] if lv in nv.index}
            tot_pim, tot_dev = nv["pim"].sum(), nv["devengado"].sum()
            row["T"] = {"pim": num(tot_pim, 1), "dev": num(tot_dev, 1), "av": num(tot_dev / tot_pim * 100, 1)}
            T["nivel"][str(y)] = row
            # Curva de avance acumulado: devengado acumulado al cierre de cada mes / PIM del año.
            curves, cum_tot = {}, None
            for lv in ["E", "M", "R"]:
                ms = read_mef(y, tipo, f"nivel_{lv}__mes")
                if ms is None or lv not in nv.index:
                    continue
                ms["mes"] = ms["codigo"].astype(int)
                dev = ms.set_index("mes")["devengado"].reindex(range(1, 13)).fillna(0).cumsum()
                if y == cur:
                    dev[dev.index > last_full] = np.nan
                curves[lv] = [num(v / nv.at[lv, "pim"] * 100, 4) for v in dev]
                cum_tot = dev if cum_tot is None else cum_tot + dev
            if cum_tot is not None:
                curves["T"] = [num(v / tot_pim * 100, 4) for v in cum_tot]
            T["curvas"][str(y)] = curves
        # Detalle del año en curso
        def listing(vista):
            df = read_mef(cur, tipo, vista)
            if df is None:
                return None
            dep = "departamento" in vista
            if dep:
                df = df[pd.to_numeric(df.codigo, errors="coerce").between(1, 25)]
            return [{"code": r.codigo, "name": (DEP_NAMES.get(r.codigo) if dep else None) or nice_title(r.nombre),
                     "pim": num(r.pim, 1), "dev": num(r.devengado, 1), "av": num(r.avance_pct, 1)} for r in df.itertuples()]
        T["sector"] = listing("nivel_E__sector")
        T["gr"] = listing("nivel_R__departamento")
        T["gl"] = listing("nivel_M__departamento")
        T["dep"] = listing("departamento")
        out["tipos"][tipo] = T
    # Gobiernos regionales: avance de la inversión al cierre del último mes completo, este año y el anterior.
    gr_same = {}
    for y in (cur, cur - 1):
        base = read_mef(y, "proyectos", "nivel_R__departamento")
        if base is None:
            continue
        for r in base.itertuples():
            ms = read_mef(y, "proyectos", f"nivel_R__dep_{r.codigo}__mes")
            if ms is None or not r.pim:
                continue
            ms["mes"] = ms["codigo"].astype(int)
            acc = ms.loc[ms.mes <= last_full, "devengado"].sum()
            gr_same.setdefault(r.codigo, {})[str(y)] = num(acc / r.pim * 100, 1)
    out["gr_mismo_mes"] = gr_same
    # Control: la suma de los niveles reproduce el devengado total por departamento.
    for tipo in ["todo", "proyectos"]:
        d = read_mef(cur, tipo, "departamento")
        n = read_mef(cur, tipo, "nivel")
        if d is not None and n is not None:
            print(f"  control MEF {cur} {tipo}: devengado por departamento {d.devengado.sum():,.0f} vs por nivel "
                  f"{n.devengado.sum():,.0f} millones")
    print(f"  ejecución MEF: años {years[0]}–{cur}, corte {corte}, último mes completo {last_full}")
    return out


# ---------------------------------------------------------------------------------------------
# v2: reglas fiscales y proyecciones del MMM
# ---------------------------------------------------------------------------------------------
MMM_DIR = PROJECT_DIR / "data" / "raw" / "proyecciones" / "MEF_MMM"
def mmm_files(n: int = 2) -> dict:
    """Los n MMM más recientes con cuadros estadísticos en Excel y el formato actual (hoja C-07 con «Resultado»)."""
    found = []
    for f in MMM_DIR.glob("*.xlsx"):
        mt = re.search(r"mmm[-_](\d{4})[-_](\d{4})", f.name, re.I)
        if mt:
            found.append((int(mt.group(1)), int(mt.group(2)), f.name))
    found.sort()
    out = {}
    for y0, y1, name in reversed(found):
        import openpyxl
        if "C-07" in openpyxl.load_workbook(MMM_DIR / name, read_only=True).sheetnames:
            out[f"MMM {y0}-{y1}"] = name
        if len(out) == n:
            break
    return dict(reversed(list(out.items())))


def mmm_table(path: Path, sheet: str, labels: dict[str, str], pct_next: bool) -> dict:
    """Lee un cuadro del MMM: fila de años y filas cuyo rótulo contiene cada texto de `labels`.
    Si pct_next, el valor en % del PBI está en la fila siguiente («% del PBI»)."""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    rows = [list(r) for r in wb[sheet].iter_rows(values_only=True)]
    years = None
    out = {}
    for i, r in enumerate(rows):
        vals = [c for c in r if c is not None]
        if years is None and sum(isinstance(c, int) and 2015 <= c <= 2040 for c in vals) >= 4:
            years = [(j, c) for j, c in enumerate(r) if isinstance(c, int) and 2015 <= c <= 2040]
            continue
        if years is None:
            continue
        text = " ".join(str(c) for c in r if isinstance(c, str))
        for key, lab in labels.items():
            if key in out or lab.lower() not in text.lower():
                continue
            if pct_next and i + 1 >= len(rows):
                continue
            src = rows[i + 1] if pct_next else r
            if pct_next and "% del pbi" not in " ".join(str(c) for c in src if isinstance(c, str)).lower():
                continue
            out[key] = {str(y): num(src[j], 4) for j, y in years if isinstance(src[j], (int, float))}
    return out


def build_reglas(a: pd.DataFrame, debt: dict) -> dict:
    rules = pd.read_csv(PROJECT_DIR / "config" / "reglas_fiscales.csv", encoding="utf-8")
    mmm = {}
    for name, fname in mmm_files().items():
        p = MMM_DIR / fname
        if not p.exists():
            warn(f"falta {fname}")
            continue
        t = mmm_table(p, "C-07", {"re": "Resultado económico", "ing": "Ingresos del gobierno general",
                                  "gnf": "Gastos no financieros del gobierno general"}, pct_next=True)
        t.update(mmm_table(p, "C-19", {"deuda": "Deuda pública total"}, pct_next=False))
        mmm[name] = t
    obs = {"re": {str(t.year): num(v, 4) for t, v in a["spnf_res_econ_pct_pbi_anual"].dropna().items()},
           "deuda": {str(t.year): num(v, 4) for t, v in a["deuda_total_pct_pbi_anual"].dropna().items()}}
    # Control: el MMM reproduce el último año observado.
    for name, t in mmm.items():
        for k in ("re", "deuda"):
            common = sorted(set(t.get(k, {})) & set(obs[k]))
            if common:
                y = common[-1]
                print(f"  control {name} {k} {y}: MMM {t[k][y]} vs BCRP {obs[k][y]}")
    return {"rules": [{"regla": r.regla, "y": int(r.anio), "v": float(r.valor_pct_pbi), "fuente": r.fuente}
                      for r in rules.itertuples()], "mmm": mmm, "obs": obs}


# ---------------------------------------------------------------------------------------------
# v2: indicadores de riesgo de la deuda (MEF, archivo bajado a mano)
# ---------------------------------------------------------------------------------------------
MEF_MANUAL = PROJECT_DIR / "data" / "manual" / "mef"
MES_ES = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8, "set": 9, "sep": 9,
          "oct": 10, "nov": 11, "dic": 12}


def build_deuda_mef() -> dict | None:
    import openpyxl
    def fecha(f):
        mt = re.search(r"_(\d{1,2})_(\d{4})", f.name)
        return (int(mt.group(2)), int(mt.group(1))) if mt else (0, 0)
    files = sorted(MEF_MANUAL.glob("Indicadores_Deuda_Publica_*.xlsx"), key=fecha)
    if not files:
        warn("sin indicadores de deuda del MEF (data/manual/mef)")
        return None
    wb = openpyxl.load_workbook(files[-1], read_only=True, data_only=True)
    series = {}
    for sheet, key in [("Soles", "soles"), ("TasaFija", "fija"), ("VidaMedia", "vida"), ("Duracion", "dur")]:
        s = {}
        for r in wb[sheet].iter_rows(values_only=True):
            r = [c for c in (r or ()) if c is not None]   # los datos no empiezan en la columna A
            if len(r) < 4:
                continue
            d = r[0]
            if isinstance(d, (dt.datetime, dt.date)):
                y, mth = d.year, d.month
            elif isinstance(d, str) and re.match(r"^[a-z]{3}\.?-\d{2}$", d.strip().lower()):
                ab, yy = d.strip().lower().replace(".", "").split("-")
                y, mth = 2000 + int(yy), MES_ES[ab]
            else:
                continue
            v = r[3]
            if isinstance(v, (int, float)):
                s[f"{y}-T{(mth - 1) // 3 + 1}"] = v
        series[key] = s
    P = sorted(set().union(*[set(s) for s in series.values()]))
    out = {"P": P, "archivo": files[-1].name, **{k: [num(s.get(p), 4) for p in P] for k, s in series.items()}}
    print(f"  deuda MEF ({files[-1].name}): {P[0]} a {P[-1]}; en soles {out['soles'][-1]} %, tasa fija {out['fija'][-1]} %")
    return out


# ---------------------------------------------------------------------------------------------
# v3: el Perú frente a la región (FMI, gobierno general)
# ---------------------------------------------------------------------------------------------
FMI_RAW = PROJECT_DIR / "data" / "raw" / "fmi"
FMI_IND = {"res": "GGXCNL_NGDP", "prim": "GGXONLB_G01_GDP_PT", "deuda": "GGXWDG_NGDP",
           "dneta": "GGXWDN_G01_GDP_PT", "ing": "GGR_G01_GDP_PT", "gasto": "G_X_G01_GDP_PT"}
# Vecinos y pares de la región, más España y EE. UU. como referencia (editar aquí para cambiar la comparación).
FMI_PAISES = {"PER": "Perú", "CHL": "Chile", "COL": "Colombia", "MEX": "México", "BRA": "Brasil", "ECU": "Ecuador",
              "BOL": "Bolivia", "PRY": "Paraguay", "URY": "Uruguay", "ARG": "Argentina", "PAN": "Panamá",
              "ESP": "España", "USA": "Estados Unidos"}
FMI_REGION = ["CHL", "COL", "MEX", "BRA", "ECU", "BOL", "PRY", "URY", "ARG", "PAN"]   # para la mediana regional


def build_fmi(a: pd.DataFrame) -> dict | None:
    meta_p = FMI_RAW / "indicadores.json"
    if not meta_p.exists():
        warn("sin datos del FMI (correr descargar_fmi.py); se omite la pestaña regional")
        return None
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    ymax = 2000
    for code in FMI_IND.values():
        p = FMI_RAW / f"{code}.json"
        if p.exists():
            v = json.loads(p.read_text(encoding="utf-8"))["values"][code]
            ymax = max([ymax] + [int(y) for iso in FMI_PAISES for y in v.get(iso, {})])
    years = list(range(2000, ymax + 1))
    src = (meta["indicadores"].get(FMI_IND["res"]) or {}).get("source") or ""
    ed = re.search(r"(January|April|July|October)\s+(\d{4})", src)
    first_proj = int(ed.group(2)) if ed else int(meta["descargado_en"][:4])   # en el WEO, el año de la edición ya es proyección
    out = {"years": [str(y) for y in years], "first_proj": first_proj, "paises": [{"iso": k, "name": v} for k, v in FMI_PAISES.items()],
           "region": FMI_REGION, "m": {}, "mediana": {}, "fuentes": {},
           "descargado": meta["descargado_en"][:10]}
    for key, code in FMI_IND.items():
        p = FMI_RAW / f"{code}.json"
        if not p.exists():
            warn(f"falta {code}")
            continue
        vals = json.loads(p.read_text(encoding="utf-8"))["values"][code]
        out["m"][key] = {iso: [num(vals.get(iso, {}).get(str(y))) for y in years] for iso in FMI_PAISES}
        med = []
        for j in range(len(years)):
            xs = [out["m"][key][iso][j] for iso in FMI_REGION if out["m"][key][iso][j] is not None]
            med.append(num(float(np.median(xs))) if len(xs) >= 6 else None)
        out["mediana"][key] = med
        info = meta["indicadores"].get(code) or {}
        out["fuentes"][key] = {"source": info.get("source"), "modificado": (info.get("last-modified") or "")[:10]}
    # Control: el Perú en el FMI frente al BCRP (2025).
    bcrp = {"res": a["spnf_res_econ_pct_pbi_anual"], "deuda": a["deuda_total_pct_pbi_anual"]}
    out["control"] = {}
    for key, s in bcrp.items():
        s = s.dropna()
        y = str(s.index.max().year)
        f = out["m"].get(key, {}).get("PER", [None] * len(years))[years.index(int(y))]
        out["control"][key] = {"y": y, "fmi": f, "bcrp": num(s.iloc[-1], 4)}
        print(f"  control FMI vs BCRP, Perú {key} {y}: FMI {f} vs BCRP {num(s.iloc[-1], 4)}")
    return out


# ---------------------------------------------------------------------------------------------
def last_two_years(s: pd.Series, ts):
    s = s.dropna()
    prev = ts - pd.DateOffset(years=1)
    return num(s.get(ts), 4), num(s.get(prev), 4)


def build_kpis(m, q, S, months, D_debt) -> dict:
    re = pd.Series(S["re12"], index=months).dropna()
    ts = re.index.max()
    trib = pd.Series(S["trib12"], index=months).dropna()
    k = {"re": {"v": re.iloc[-1], "prev": re.get(ts - pd.DateOffset(years=1)), "m": month_key(ts)},
         "trib": {"v": trib.iloc[-1], "prev": trib.get(trib.index.max() - pd.DateOffset(years=1)), "m": month_key(trib.index.max())},
         "ing": ytd_real(m["ing_gg_total_ingresos_corrientes_real"]),
         "gnf": ytd_real(m["gnf_gg_gnf_total_real"]),
         "fbk": ytd_real(m["gnf_gg_capital_fbk_real"])}
    br = [(p, v) for p, v in zip(D_debt["P"], D_debt["bruta"]) if v is not None]
    ne = [(p, v) for p, v in zip(D_debt["P"], D_debt["neta"]) if v is not None]
    k["deuda"] = {"v": br[-1][1], "q": br[-1][0], "prev": br[-5][1] if len(br) > 4 else None,
                  "neta": ne[-1][1], "neta_q": ne[-1][0]}
    return k


def main() -> int:
    m, q, a = load_panel("mensual"), load_panel("trimestral"), load_panel("anual")
    months, S, den = build_monthly(m, q)
    last_m = months[-1]
    print(f"  meses: {month_key(months[0])} a {month_key(last_m)}")
    debt = build_debt(q)
    data = {
        "generado": dt.date.today().isoformat(), "start": month_key(months[0]), "n": len(months),
        "hasta": month_key(last_m), "S": S,
        "A": build_annual(m, a, den, last_m), "comp": build_ingresos_comp(m, last_m),
        "inv": build_inv_ytd(m), "debt": debt, "kpi": build_kpis(m, q, S, months, debt),
        "regions": build_regions(m), "geo": build_geo(warn),
        "ejec": build_ejecucion(), "reglas": build_reglas(a, debt), "deuda_mef": build_deuda_mef(),
        "fmi": build_fmi(a),
    }
    html = TEMPLATE.read_text(encoding="utf-8")
    if PLACEHOLDER not in html:
        raise ValueError(f"La plantilla no tiene el marcador {PLACEHOLDER}")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("</", "<\\/")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html.replace(PLACEHOLDER, payload), encoding="utf-8")
    print(f"  {OUT.relative_to(PROJECT_DIR)}  ({OUT.stat().st_size / 1024:.0f} KB; datos {len(payload) / 1024:.0f} KB)")
    OUT_ARTIFACT.write_text(artifact_version(OUT.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"  {OUT_ARTIFACT.relative_to(PROJECT_DIR)}  (versión para publicar en claude.ai)")
    if WARNINGS:
        print(f"  {len(WARNINGS)} aviso(s) (ver arriba)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
