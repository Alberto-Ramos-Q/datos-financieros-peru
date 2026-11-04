"""Pobreza monetaria, gasto e ingreso real por ámbito y departamento, ENAHO 2004-2025.

Calcula desde la Sumaria de cada año, con la metodología del INEI replicada y validada en
src/validar_cifras_oficiales.py (cuyas funciones se importan, sin modificarlo):
- Peso de personas facpob07 = round(factor07 * mieperho, 1) (redondeo de Stata al entero).
- Diseño: strata(estrato), psu(conglome); linealización de Taylor, PSU con reemplazo.
  Pobreza y totales de población: dominio «subpop» (Cuadros III.1, III.4). Gasto e ingreso:
  varianza sobre la submuestra del dominio (`svy ... if`, Cuadros I.1, I.15).
- Gasto real = Σ de los 8 grupos de la Sumaria, cada uno / (12·mieperho·ld·i0k); ingreso real =
  inghog1d / (12·mieperho·ld·i00). Soles de 2025 a precios de Lima Metropolitana.
  i0k de data/processed/deflactores/deflactor_temporal.parquet; ld de la Sumaria (2012+) o
  construido con dominioA y deflactor_espacial.parquet (2004-2011).
- Ámbitos: nacional; área; región natural; dominios del INEI (dominio2); ámbito geográfico
  (Lima Met. y Callao, resto urbano, rural); los 8 dominios muestrales; 25 departamentos
  (ubigeo[:2], 15 = Lima completo, 07 = Callao); y las 26 unidades del Cuadro III.1 del INEI
  (Lima Metropolitana = 43 distritos de la provincia de Lima, «Lima 2/» = resto del departamento,
  Callao aparte); y la apertura de los informes con datos hasta 2012 (24 unidades: «Lima»
  incluye al Callao), como ámbito «departamento_inei_24» con id 15C (los otros 23 son los mismos
  de «departamento»).
- Grupos de departamentos con pobreza estadísticamente semejante (Cuadros 4.2 y 4.4): IC del
  grupo oficial (2016-2025, config/grupos_departamentos_oficial_2016_2025.csv) y una
  reproducción algorítmica para todos los años (partición óptima del ranking, ver
  group_departments()).

Salidas (data/processed/pobreza/):
    pobreza_ambitos.parquet / .csv          formato largo (anio × ámbito × indicador)
    pobreza_departamentos.parquet / .csv    ancho, departamentos, listo para el mapa
    grupos_departamentos.parquet / .csv     grupos de pobreza (oficiales y calculados)

Uso (desde la raíz de descargas-enaho):
    python src/pobreza_departamental.py            # 2004-2025
    python src/pobreza_departamental.py 2016 2025  # solo esos años (sobrescribe las salidas)
Validación contra el INEI: python src/validar_pobreza_departamental.py
Informe: docs/validacion_pobreza_departamental.md
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))  # módulos hermanos de src/
from construir_deflactores import build_dominio_a  # noqa: E402
from validar_cifras_oficiales import (  # noqa: E402
    BASE_YEAR, EXPENDITURE_GROUPS, Z_95, load_price_coefficients, load_spatial_deflator,
    survey_ratio)

ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = ROOT / "data" / "processed"
OUT_DIR = PROCESSED_DIR / "pobreza"
OFFICIAL_GROUPS_FILE = ROOT / "config" / "grupos_departamentos_oficial_2016_2025.csv"

YEARS = list(range(2004, 2026))
CV_REFERENTIAL = 15.0  # CV > 15 % = cifra referencial [POB p.232, nota del Cuadro III.1: «mayor al
                       # 15%»; p.73: «menores o iguales al 15%» = precisión adecuada]
MAX_GROUPS = 5         # número de grupos de partida (el INEI publica casi siempre 5)
SE_FLOOR = 0.05        # EE mínimo (pp) al ponderar unidades con 0 % de pobres en la muestra

COLUMNS = ["conglome", "ubigeo", "dominio", "estrato", "mieperho", "factor07",
           "gashog2d", "inghog1d", "linea", "linpe", "pobreza"]

DEPARTMENTS = {
    "01": "Amazonas", "02": "Áncash", "03": "Apurímac", "04": "Arequipa", "05": "Ayacucho",
    "06": "Cajamarca", "07": "Prov. Const. del Callao", "08": "Cusco", "09": "Huancavelica",
    "10": "Huánuco", "11": "Ica", "12": "Junín", "13": "La Libertad", "14": "Lambayeque",
    "15": "Lima", "16": "Loreto", "17": "Madre de Dios", "18": "Moquegua", "19": "Pasco",
    "20": "Piura", "21": "Puno", "22": "San Martín", "23": "Tacna", "24": "Tumbes",
    "25": "Ucayali",
}
LIMA_CALLAO_ID, LIMA_CALLAO_NAME = "15C", "Lima (incluye Prov. Const. del Callao)"
LIMA_UNITS = {"15LM": "Lima Metropolitana (43 distritos)",
              "15LP": "Lima Provincias (Región Lima)"}
SAMPLE_DOMAINS = {1: "Costa Norte", 2: "Costa Centro", 3: "Costa Sur", 4: "Sierra Norte",
                  5: "Sierra Centro", 6: "Sierra Sur", 7: "Selva", 8: "Lima Metropolitana"}

# indicador -> (columna y, denominador, escala, unidad, tipo de estimador)
INDICATORS = {
    "pobreza_total": ("pobre_total", "one", 100.0, "%", "ratio_subpop"),
    "pobreza_extrema": ("pobre_extremo", "one", 100.0, "%", "ratio_subpop"),
    "gasto_real_pc": ("gasto_real_pc", "one", 1.0, "S/ 2025 Lima Met. mes", "ratio_subset"),
    "ingreso_real_pc": ("ingreso_real_pc", "one", 1.0, "S/ 2025 Lima Met. mes", "ratio_subset"),
    "gasto_nominal_pc": ("gasto_nominal_pc", "one", 1.0, "S/ corrientes mes", "ratio_subset"),
    "poblacion": ("one", None, 1.0, "personas", "total"),
    "poblacion_pobre_total": ("pobre_total", None, 1.0, "personas", "total"),
    "poblacion_pobre_extrema": ("pobre_extremo", None, 1.0, "personas", "total"),
}


# --------------------------------------------------------------------------------------------
# Insumos
# --------------------------------------------------------------------------------------------
def load_year(year: int, coefficients: pd.DataFrame, ld_table: pd.Series) -> pd.DataFrame:
    """Sumaria del año con las variables derivadas del INEI (válida para 2004-2025).

    Trampas de 2004-2015 resueltas aquí (ver docs/validacion_pobreza_departamental.md §5):
    - `ld` no existe en 2004-2011: se construye con dominioA (rutina INEI) y el deflactor espacial.
    - Tipos float32/int8 en 2004-2007 (p. ej. mieperho int8 en 2006: 12*mieperho desborda):
      todo se pasa a float64 antes de operar.
    - Grupos de gasto con nulos en 2004-2006: se rellenan con 0 (`recode ... (.=0)` del INEI).
    - Lima Metropolitana (dominio 8) con estrato rural (un conglomerado de Pachacámac en 2007 y
      2011): se trata como urbana, como la rutina INEI (`replace area=1 if dominio==8`).
    """
    path = PROCESSED_DIR / str(year) / f"sumaria-{year}.parquet"
    available = set(pq.read_schema(path).names)
    group_cols = [c for cols in EXPENDITURE_GROUPS.values() for c in cols if c in available]
    cols = COLUMNS + (["ld"] if "ld" in available else []) + group_cols
    df = pd.read_parquet(path, columns=cols)
    for cols_k in EXPENDITURE_GROUPS.values():
        for col in cols_k:
            if col not in df.columns:  # sg27/sig28 (2004-2022), gru52hd2 (2017+)
                df[col] = 0.0
    num_cols = [c for c in df.columns if c not in ("conglome", "ubigeo")]
    df[num_cols] = df[num_cols].astype("float64")
    df[group_cols] = df[group_cols].fillna(0.0)

    df["dpto"] = df["ubigeo"].str[:2]
    df["provincia"] = df["ubigeo"].str[:4]
    df["lima_met"] = df["dominio"] == 8
    df["urbana"] = (df["estrato"] <= 5) | df["lima_met"]
    df["region"] = np.select(
        [df["dominio"].isin([1, 2, 3, 8]), df["dominio"].isin([4, 5, 6])],
        ["costa", "sierra"], "selva")
    # round(x, 1) de Stata = redondeo al entero, mitades hacia arriba
    df["facpob07"] = np.floor(df["factor07"] * df["mieperho"] + 0.5)

    ld_built = build_dominio_a(df).map(ld_table)
    if "ld" not in df.columns:
        df["ld"] = ld_built
    elif (df["ld"] - ld_built).abs().max() > 1e-9:
        raise ValueError(f"{year}: ld de la Sumaria distinto del deflactor espacial")

    coef = coefficients[coefficients["anio"] == year].set_index("dpto")
    df["dpto_ipc"] = df["dpto"].astype(int).replace({7: 15})  # Callao usa el IPC de Lima
    df = df.join(coef[[f"i0{k}" for k in range(9)]], on="dpto_ipc")
    if df[[f"i0{k}" for k in range(9)]].isna().any().any():
        raise ValueError(f"{year}: faltan coeficientes IPC para algún departamento")

    monthly_people = 12.0 * df["mieperho"]
    df["gasto_nominal_pc"] = df["gashog2d"] / monthly_people
    df["gasto_real_pc"] = 0.0
    for k, cols_k in EXPENDITURE_GROUPS.items():
        df["gasto_real_pc"] += df[cols_k].sum(axis=1) / (monthly_people * df["ld"] * df[f"i0{k}"])
    df["ingreso_real_pc"] = df["inghog1d"] / (monthly_people * df["ld"] * df["i00"])
    df["pobre_total"] = df["pobreza"].isin([1, 2]).astype(float)
    df["pobre_extremo"] = (df["pobreza"] == 1).astype(float)
    df["one"] = 1.0
    return df


# --------------------------------------------------------------------------------------------
# Ámbitos
# --------------------------------------------------------------------------------------------
def domain_masks(df: pd.DataFrame) -> list[tuple[str, str, str, pd.Series]]:
    """(ambito_tipo, ambito_id, ambito, máscara) de cada ámbito calculado."""
    urb, lima = df["urbana"], df["lima_met"]
    out = [("nacional", "PE", "Nacional", pd.Series(True, index=df.index)),
           ("area", "urbana", "Urbana", urb),
           ("area", "rural", "Rural", ~urb)]
    for reg in ("costa", "sierra", "selva"):
        out.append(("region_natural", reg, reg.capitalize(), df["region"] == reg))
    for reg in ("costa", "sierra", "selva"):  # dominio2 del INEI: costa sin Lima Met.
        mask = (df["region"] == reg) & ~lima
        out.append(("dominio_inei", f"{reg}_urbana", f"{reg.capitalize()} urbana", mask & urb))
        out.append(("dominio_inei", f"{reg}_rural", f"{reg.capitalize()} rural", mask & ~urb))
    out.append(("dominio_inei", "lima_metropolitana_callao",
                "Lima Metropolitana y Prov. Const. del Callao", lima))
    out += [("ambito_geografico", "lima_metropolitana_callao",
             "Lima Metropolitana y Prov. Const. del Callao", lima),
            ("ambito_geografico", "resto_urbano", "Resto urbano", urb & ~lima),
            ("ambito_geografico", "rural", "Rural", ~urb)]
    for code, name in SAMPLE_DOMAINS.items():
        out.append(("dominio_muestral", str(code), name, df["dominio"] == code))
    for code, name in DEPARTMENTS.items():
        out.append(("departamento", code, name, df["dpto"] == code))
    for code, name in inei_units().items():
        out.append(("departamento_inei", code, name, inei_unit_mask(df, code)))
    # Apertura antigua (informes con datos hasta 2012): «Lima» incluye al Callao, 24 unidades
    out.append(("departamento_inei_24", LIMA_CALLAO_ID, LIMA_CALLAO_NAME,
                df["dpto"].isin(["07", "15"])))
    return out


def inei_units() -> dict[str, str]:
    """Las 26 unidades del Cuadro III.1 del INEI (departamentos con Lima abierto en dos)."""
    units = {c: n for c, n in DEPARTMENTS.items() if c != "15"}
    units.update(LIMA_UNITS)
    return dict(sorted(units.items()))


def inei_unit_mask(df: pd.DataFrame, code: str) -> pd.Series:
    if code == "15LM":  # «Incluye los 43 distritos de la provincia de Lima» [POB p.232, nota 1/]
        return df["provincia"] == "1501"
    if code == "15LP":  # «Lima 2/»: provincias Barranca … Yauyos = resto del departamento 15
        return (df["dpto"] == "15") & (df["provincia"] != "1501")
    return df["dpto"] == code


# --------------------------------------------------------------------------------------------
# Estimación
# --------------------------------------------------------------------------------------------
def design_variance(z: pd.Series, strata: pd.Series, psu: pd.Series) -> float:
    """Varianza de un total linealizado z: Σ_h n_h/(n_h-1) Σ_c (z_hc - z̄_h)² (= survey_ratio)."""
    psu_totals = z.groupby([strata, psu]).sum()
    grouped = psu_totals.groupby(level=0)
    n_h = grouped.transform("size")
    dev = (psu_totals - grouped.transform("mean")) ** 2 * n_h / (n_h - 1)
    return float(dev[n_h > 1].sum())


def survey_total(y: pd.Series, weight: pd.Series, strata: pd.Series, psu: pd.Series,
                 domain: pd.Series) -> tuple[float, float]:
    """Total ponderado Σw·y en un dominio («subpop») y su error estándar."""
    z = weight * y * domain.astype(float)
    return float(z.sum()), float(np.sqrt(design_variance(z, strata, psu)))


def linearized_ratio(y: pd.Series, weight: pd.Series, domain: pd.Series) -> tuple[float, pd.Series]:
    """Razón R = Σw·y/Σw en el dominio y su variable linealizada z (para contrastes)."""
    d = domain.astype(float)
    total_x = (weight * d).sum()
    ratio = (weight * y * d).sum() / total_x
    return float(ratio), weight * d * (y - ratio) / total_x


def estimate_year(df: pd.DataFrame, year: int) -> pd.DataFrame:
    """Todas las estimaciones del año en formato largo."""
    args = dict(weight=df["facpob07"], strata=df["estrato"], psu=df["conglome"])
    rows = []
    for ambito_tipo, ambito_id, ambito, mask in domain_masks(df):
        n = int(mask.sum())
        for indicator, (ycol, xcol, scale, unit, kind) in INDICATORS.items():
            if n == 0:
                est = se = np.nan
            elif kind == "total":
                est, se = survey_total(df[ycol], domain=mask, **args)
            else:
                est, se = survey_ratio(df[ycol], df[xcol], domain=mask,
                                       subset=(kind == "ratio_subset"), **args)
            est, se = est * scale, se * scale
            rows.append(dict(anio=year, ambito_tipo=ambito_tipo, ambito_id=ambito_id,
                             ambito=ambito, indicador=indicator, unidad=unit, valor=est, ee=se,
                             ic_inf=est - Z_95 * se, ic_sup=est + Z_95 * se,
                             cv=100 * se / est if est else np.nan, n_hogares=n,
                             metodo_ee={"ratio_subpop": "subpop", "total": "subpop",
                                        "ratio_subset": "submuestra"}[kind]))
    out = pd.DataFrame(rows)
    out["referencial"] = out["cv"] > CV_REFERENTIAL
    return out


# --------------------------------------------------------------------------------------------
# Grupos de departamentos estadísticamente semejantes
# --------------------------------------------------------------------------------------------
def pairwise_t(df: pd.DataFrame, ycol: str, codes: list[str]) -> tuple[pd.Series, pd.DataFrame]:
    """Estimación (%) por unidad INEI y matriz de estadísticos t de las diferencias.

    La varianza de R_a − R_b se calcula con el diseño completo (z_a − z_b), así incluye la
    covarianza que generan los estratos compartidos entre departamentos. Dos unidades sin
    varianza (p. ej. 0 % de pobres extremos en la muestra) tienen t = 0 si son iguales.
    """
    est, z = {}, {}
    for code in codes:
        est[code], z[code] = linearized_ratio(df[ycol], df["facpob07"], inei_unit_mask(df, code))
    t = pd.DataFrame(0.0, index=codes, columns=codes)
    for i, a in enumerate(codes):
        for b in codes[i + 1:]:
            se = np.sqrt(design_variance(z[a] - z[b], df["estrato"], df["conglome"]))
            diff = est[a] - est[b]
            t.loc[a, b] = t.loc[b, a] = diff / se if se > 0 else (0.0 if diff == 0 else np.inf)
    return pd.Series(est) * 100, t


def optimal_partition(values: np.ndarray, weights: np.ndarray, k: int) -> list[tuple[int, int]]:
    """Partición óptima de una lista ordenada en k tramos contiguos (Fisher/Jenks).

    Minimiza Σ_g Σ_{i∈g} w_i (p_i − p̄_g)², con p̄_g la media ponderada del tramo; programación
    dinámica exacta. Devuelve los tramos como pares (inicio, fin) de índices.
    """
    n = len(values)

    def cost(i: int, j: int) -> float:
        w, v = weights[i:j], values[i:j]
        return float((w * (v - (w * v).sum() / w.sum()) ** 2).sum())

    best = np.full((k + 1, n + 1), np.inf)
    back = np.zeros((k + 1, n + 1), dtype=int)
    best[0, 0] = 0.0
    for g in range(1, k + 1):
        for j in range(g, n + 1):
            for i in range(g - 1, j):
                candidate = best[g - 1, i] + cost(i, j)
                if candidate < best[g, j]:
                    best[g, j], back[g, j] = candidate, i
    cuts, j = [], n
    for g in range(k, 0, -1):
        cuts.append((back[g, j], j))
        j = back[g, j]
    return cuts[::-1]


def group_departments(df: pd.DataFrame, ycol: str, estimates: pd.DataFrame,
                      max_groups: int = MAX_GROUPS) -> pd.Series:
    """Grupos de departamentos con pobreza estadísticamente semejante (reproducción propia).

    El INEI dice que aplica pruebas t y de Kolmogorov-Smirnov y obtiene «cinco grupos» [POB p.74,
    p.80], pero no publica la regla. Lo que sí muestran sus Cuadros 4.2 y 4.4 (2016-2025) es que:
    (i) los grupos son tramos contiguos del ranking de departamentos; (ii) casi siempre son 5
    (6 en 2016 y 4 en 2018-2020 para la extrema); (iii) los IC 95 % de los grupos no se solapan;
    (iv) dentro de un grupo puede haber pares con diferencia significativa (no es un criterio
    «todos contra todos»). Regla aquí: partición óptima del ranking en k tramos ponderando cada
    unidad por 1/EE² (los departamentos imprecisos pesan menos), empezando con k = 5 y bajando k
    hasta que los IC de los grupos (calculados con el diseño) no se solapen. Coincidencia con los
    grupos oficiales: ver docs/validacion_pobreza_departamental.md §4.3.
    """
    order = estimates.sort_values("valor", ascending=False)
    values = order["valor"].to_numpy()
    weights = 1.0 / np.maximum(order["ee"].to_numpy(), SE_FLOOR) ** 2
    args = dict(weight=df["facpob07"], strata=df["estrato"], psu=df["conglome"])
    for k in range(max_groups, 1, -1):
        cuts = optimal_partition(values, weights, k)
        intervals = []
        for i, j in cuts:
            mask = pd.concat([inei_unit_mask(df, c) for c in order.index[i:j]], axis=1).any(axis=1)
            r, se = survey_ratio(df[ycol], df["one"], domain=mask, **args)
            intervals.append((r - Z_95 * se, r + Z_95 * se))
        if all(intervals[g][0] > intervals[g + 1][1] for g in range(k - 1)):
            break
    return pd.Series({code: g + 1 for g, (i, j) in enumerate(cuts) for code in order.index[i:j]})


def load_official_groups() -> pd.DataFrame:
    if not OFFICIAL_GROUPS_FILE.exists():
        return pd.DataFrame()
    return pd.read_csv(OFFICIAL_GROUPS_FILE, dtype={"ambito_ids": str})


def groups_year(df: pd.DataFrame, year: int, official: pd.DataFrame) -> pd.DataFrame:
    """Grupos calculados (todos los años) y oficiales (2016-2025), con el IC del grupo.

    El IC del grupo es el de la pobreza del conjunto de sus departamentos (dominio «subpop»): así
    se reproducen los «límites inferior y superior de cada grupo robusto» de los Cuadros 4.2/4.4.
    """
    codes = list(inei_units())
    args = dict(weight=df["facpob07"], strata=df["estrato"], psu=df["conglome"])
    rows = []
    for indicator, ycol in (("pobreza_total", "pobre_total"),
                            ("pobreza_extrema", "pobre_extremo")):
        est, t = pairwise_t(df, ycol, codes)
        se = pd.Series({c: survey_ratio(df[ycol], df["one"], domain=inei_unit_mask(df, c),
                                        **args)[1] * 100 for c in codes})
        partitions = {"calculado": group_departments(df, ycol, pd.DataFrame({"valor": est, "ee": se}))}
        off = official[(official["indicador"] == indicator) & (official["anio"] == year)] \
            if len(official) else official
        if len(off):
            partitions["oficial"] = pd.Series(
                {c: int(g) for g, ids in zip(off["grupo"], off["ambito_ids"])
                 for c in ids.split(";")})
        for source, membership in partitions.items():
            for group, members in membership.groupby(membership).groups.items():
                members = list(members)
                mask = pd.concat([inei_unit_mask(df, c) for c in members], axis=1).any(axis=1)
                r, se = survey_ratio(df[ycol], df["one"], domain=mask, **args)
                tmax = max((abs(t.loc[a, b]) for i, a in enumerate(members)
                            for b in members[i + 1:]), default=0.0)
                rows.append(dict(
                    anio=year, indicador=indicator, fuente_grupo=source, grupo=int(group),
                    ambito_ids=";".join(sorted(members)),
                    departamentos="; ".join(inei_units()[c] for c in sorted(members)),
                    n_unidades=len(members), valor=100 * r, ic_inf=100 * (r - Z_95 * se),
                    ic_sup=100 * (r + Z_95 * se), min_unidad=est[members].min(),
                    max_unidad=est[members].max(), t_max_interno=tmax))
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------------
# Salidas
# --------------------------------------------------------------------------------------------
def department_table(long: pd.DataFrame, groups: pd.DataFrame) -> pd.DataFrame:
    """Tabla ancha de departamentos para el mapa: una fila por año × unidad."""
    dep = long[long["ambito_tipo"].isin(["departamento", "departamento_inei",
                                         "departamento_inei_24"])].copy()
    dep = dep.drop_duplicates(["anio", "ambito_id", "indicador"])
    wide = dep.pivot_table(index=["anio", "ambito_id", "ambito", "n_hogares"],
                           columns="indicador", values="valor").reset_index()
    wide.columns.name = None
    for indicator in ("pobreza_total", "pobreza_extrema"):
        sub = dep[dep["indicador"] == indicator].set_index(["anio", "ambito_id"])
        for stat in ("ic_inf", "ic_sup", "cv"):
            wide[f"{indicator}_{stat}"] = sub[stat].reindex(
                pd.MultiIndex.from_frame(wide[["anio", "ambito_id"]])).values
        wide[f"{indicator}_referencial"] = wide[f"{indicator}_cv"] > CV_REFERENTIAL
    wide["ubigeo_dpto"] = wide["ambito_id"].str[:2]
    wide["en_mapa_25"] = wide["ambito_id"].isin(DEPARTMENTS)
    wide["en_cuadro_inei_26"] = wide["ambito_id"].isin(inei_units())
    # 24 unidades de los informes con datos hasta 2012: 23 departamentos + Lima con Callao
    wide["en_cuadro_inei_24"] = wide["ambito_id"].isin(
        [c for c in DEPARTMENTS if c not in ("07", "15")] + [LIMA_CALLAO_ID])
    for indicator in ("pobreza_total", "pobreza_extrema"):
        for source in ("oficial", "calculado"):
            g = groups[(groups["indicador"] == indicator) & (groups["fuente_grupo"] == source)]
            lookup = {(y, c): grp for y, ids, grp in zip(g["anio"], g["ambito_ids"], g["grupo"])
                      for c in ids.split(";")}
            wide[f"grupo_{indicator}_{source}"] = [
                lookup.get((y, c), pd.NA) for y, c in zip(wide["anio"], wide["ambito_id"])]
            wide[f"grupo_{indicator}_{source}"] = wide[f"grupo_{indicator}_{source}"].astype("Int64")
    first = ["anio", "ubigeo_dpto", "ambito_id", "ambito", "en_mapa_25", "en_cuadro_inei_26",
             "en_cuadro_inei_24",
             "n_hogares"]
    ordered = first + [
        "pobreza_total", "pobreza_total_ic_inf", "pobreza_total_ic_sup", "pobreza_total_cv",
        "pobreza_total_referencial", "pobreza_extrema", "pobreza_extrema_ic_inf",
        "pobreza_extrema_ic_sup", "pobreza_extrema_cv", "pobreza_extrema_referencial",
        "gasto_real_pc", "ingreso_real_pc", "gasto_nominal_pc", "poblacion",
        "poblacion_pobre_total", "poblacion_pobre_extrema",
        "grupo_pobreza_total_oficial", "grupo_pobreza_total_calculado",
        "grupo_pobreza_extrema_oficial", "grupo_pobreza_extrema_calculado"]
    return wide[ordered].sort_values(["anio", "ambito_id"]).reset_index(drop=True)


def write(df: pd.DataFrame, stem: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_DIR / f"{stem}.parquet", index=False)
    df.to_csv(OUT_DIR / f"{stem}.csv", index=False, encoding="utf-8")
    print(f"[ok] {(OUT_DIR / stem).relative_to(ROOT).as_posix()}.parquet/.csv  "
          f"{len(df):,} filas × {df.shape[1]} cols")


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    years = list(range(int(argv[0]), int(argv[1]) + 1)) if len(argv) == 2 else YEARS
    coefficients = load_price_coefficients()
    if int(coefficients["anio"].max()) < max(years):
        raise ValueError("deflactor_temporal no cubre todos los años: correr construir_deflactores.py")
    ld_table = load_spatial_deflator()
    official_groups = load_official_groups()
    long_parts, group_parts = [], []
    for year in years:
        df = load_year(year, coefficients, ld_table)
        est = estimate_year(df, year)
        grp = groups_year(df, year, official_groups)
        long_parts.append(est)
        group_parts.append(grp)
        nat = est[(est["ambito_tipo"] == "nacional")].set_index("indicador")["valor"]
        print(f"{year}: {len(df):>6,} hogares  pobreza {nat['pobreza_total']:5.2f} %  "
              f"extrema {nat['pobreza_extrema']:5.2f} %  gasto real S/ {nat['gasto_real_pc']:6.1f}  "
              f"ingreso real S/ {nat['ingreso_real_pc']:6.1f}  "
              f"grupos calculados {grp[grp.fuente_grupo == 'calculado'].groupby('indicador').size().to_dict()}")
    long = pd.concat(long_parts, ignore_index=True)
    long["anio"] = long["anio"].astype("int16")
    long["n_hogares"] = long["n_hogares"].astype("int32")
    groups = pd.concat(group_parts, ignore_index=True)
    write(long, "pobreza_ambitos")
    write(department_table(long, groups), "pobreza_departamentos")
    write(groups, "grupos_departamentos")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
