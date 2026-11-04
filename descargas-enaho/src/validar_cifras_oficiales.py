"""Valida la base local de la ENAHO (Parquet) contra las cifras oficiales del INEI, 2016-2025.

Fuente oficial: INEI, «Perú: Evolución de la pobreza monetaria 2016-2025. Informe técnico»
(docs/enaho/2025/7_Informe_tecnico_de_pobreza/07_Informe_tecnico_de_Pobreza_Monetaria_2025.pdf).
Las cifras oficiales están transcritas abajo como constantes; cada una indica cuadro/gráfico y
página del PDF (la que muestra el visor; coincide con la página impresa en este informe).

Metodología replicada (rutinas Stata del INEI en docs/enaho/2025/1_Rutinas-medicion-pobreza/):
- Base: sumaria-<año>.parquet (un registro por hogar; ya contiene solo RESULT 1-2).
- Peso de personas: facpob07 = round(factor07 * mieperho).
- Pobreza: pobreza in {1, 2} (total) y pobreza == 1 (extrema). Equivale a
  gpcm = gashog2d / (12 * mieperho) frente a linea / linpe.
- Área: urbana si estrato <= 5; rural si estrato 6-8. Región: costa = dominio 1-3 u 8;
  sierra = 4-6; selva = 7. Lima Metropolitana = dominio 8.
- Gasto nominal per cápita mensual = gashog2d / (12 * mieperho).
- Gasto real (soles constantes 2025, precios de Lima Metropolitana) = suma de los 8 grupos de la
  Sumaria, cada uno / (12 * mieperho * ld * i0k), con i0k = IPC del grupo k promedio del año en el
  departamento / IPC promedio 2025 del mismo departamento (ipc-BASE-2009nh.dta).
- Ingreso real = inghog1d / (12 * mieperho * ld * i00); «ingreso nominal» del Cuadro I.19 =
  inghog1d / (12 * mieperho * i00) (sin deflactor espacial).
- Errores estándar: linealización de Taylor para razones, estrato = estrato, PSU = conglome,
  PSU con reemplazo (equivale a svyset [w=facpob07], psu(conglome) strata(estrato)). Pobreza:
  dominio «subpop»; gasto/ingreso: varianza sobre la submuestra del dominio (`svy ... if`).
Informe de resultados: docs/validacion_cifras_oficiales.md.

Uso (desde la raíz de descargas-enaho):
    python src/validar_cifras_oficiales.py            # todos los años disponibles
    python src/validar_cifras_oficiales.py 2016 2025  # solo esos años
Los años sin sumaria-<año>.parquet se reportan como PENDIENTE (vuelve a correrlo más tarde).
No escribe archivos: solo imprime.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))  # módulos hermanos de src/
from construir_deflactores import SPATIAL_FILE, TEMPORAL_FILE  # noqa: E402
from construir_deflactores import build_dominio_a as _dominio_a  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = ROOT / "data" / "processed"

YEARS = list(range(2016, 2026))
BASE_YEAR = 2025
Z_95 = 1.96  # Stata usa t(gl = PSU - estratos) ~ 1.9604 con > 5 000 PSU

# Grupos de gasto de la Sumaria 8G tal como los arma el INEI (sintaxis_vulnerabilidad_2025.do,
# variables gpcrplg*; i0k = IPC del grupo k).
EXPENDITURE_GROUPS = {
    1: ["gru11hd", "gru12hd1", "gru12hd2", "gru13hd1", "gru13hd2", "gru13hd3",
        "g05hd", "g05hd1", "g05hd2", "g05hd3", "g05hd4", "g05hd5", "g05hd6", "ig06hd",
        "sg23", "sig24", "gru14hd", "gru14hd1", "gru14hd2", "gru14hd3", "gru14hd4",
        "gru14hd5", "sg25", "sig26", "sg27", "sig28"],
    2: ["gru21hd", "gru22hd1", "gru22hd2", "gru23hd1", "gru23hd2", "gru23hd3", "gru24hd"],
    3: ["gru31hd", "gru32hd1", "gru32hd2", "gru33hd1", "gru33hd2", "gru33hd3", "gru34hd"],
    4: ["gru41hd", "gru42hd1", "gru42hd2", "gru43hd1", "gru43hd2", "gru43hd3", "gru44hd",
        "sg421", "sg42d1", "sg423", "sg42d3"],
    5: ["gru51hd", "gru52hd1", "gru52hd2", "gru53hd1", "gru53hd2", "gru53hd3", "gru54hd"],
    6: ["gru61hd", "gru62hd1", "gru62hd2", "gru63hd1", "gru63hd2", "gru63hd3", "gru64hd",
        "g07hd", "ig08hd", "sg422", "sg42d2"],
    7: ["gru71hd", "gru72hd1", "gru72hd2", "gru73hd1", "gru73hd2", "gru73hd3", "gru74hd",
        "sg42", "sg42d"],
    8: ["gru81hd", "gru82hd1", "gru82hd2", "gru83hd1", "gru83hd2", "gru83hd3", "gru84hd"],
}
BASE_COLUMNS = ["conglome", "ubigeo", "dominio", "estrato", "mieperho", "factor07",
                "gashog2d", "inghog1d", "ld", "linea", "linpe", "pobreza"]

AREAS = ["nacional", "urbana", "rural", "lima_metropolitana", "resto_urbano",
         "costa", "sierra", "selva", "costa_urbana", "costa_rural", "sierra_urbana",
         "sierra_rural", "selva_urbana", "selva_rural"]

# --------------------------------------------------------------------------------------------
# Cifras oficiales (orden 2016, 2017, ..., 2025). Página = página del PDF del informe técnico.
# --------------------------------------------------------------------------------------------
OFFICIAL_SERIES = {
    "pobreza_total": {
        "fuente": "Cuadro 4.1 p.72; Cuadro III.1 p.231 (resto urbano)", "unidad": "%", "tol": 0.1,
        "valores": {
            "nacional": [20.7, 21.7, 20.5, 20.2, 30.1, 25.9, 27.5, 29.0, 27.6, 25.7],
            "urbana": [13.9, 15.1, 14.4, 14.6, 26.0, 22.3, 24.1, 26.4, 24.8, 23.4],
            "rural": [43.8, 44.4, 42.1, 40.8, 45.7, 39.7, 41.1, 39.8, 39.3, 35.5],
            "lima_metropolitana": [11.0, 13.3, 13.1, 14.2, 27.5, 24.9, 27.3, 28.7, 28.2, 27.3],
            "resto_urbano": [15.9, 16.4, 15.3, 14.8, 25.0, 20.6, 21.9, 24.8, 22.4, 20.7],
            "costa": [12.8, 14.4, 13.5, 13.8, 25.9, 22.1, 24.3, 26.4, 25.2, 23.7],
            "sierra": [31.7, 31.6, 30.4, 29.3, 37.4, 32.5, 32.4, 32.8, 30.9, 28.6],
            "selva": [27.4, 28.6, 26.5, 25.8, 31.0, 26.4, 30.2, 31.6, 30.0, 27.3],
            "costa_urbana": [13.7, 15.0, 12.7, 12.3, 22.9, 17.9, 19.4, 22.9, 20.7, 18.2],
            "costa_rural": [28.9, 24.6, 25.1, 21.1, 30.4, 21.5, 26.6, 26.0, 24.5, 23.8],
            "sierra_urbana": [16.9, 16.3, 16.7, 16.1, 27.0, 23.3, 23.5, 25.2, 22.6, 21.4],
            "sierra_rural": [47.8, 48.7, 46.1, 45.2, 50.4, 44.3, 44.1, 43.1, 42.5, 38.8],
            "selva_urbana": [19.6, 20.5, 19.3, 19.0, 26.3, 21.6, 25.4, 29.1, 26.7, 25.7],
            "selva_rural": [39.3, 41.4, 38.3, 37.3, 39.2, 35.0, 39.2, 36.3, 36.7, 30.7],
        },
    },
    "pobreza_extrema": {
        "fuente": "Cuadro 4.3 p.80; Cuadro III.4 p.235 (Lima Met., resto urbano)", "unidad": "%",
        "tol": 0.1,
        "valores": {
            "nacional": [3.8, 3.8, 2.8, 2.9, 5.1, 4.1, 5.0, 5.7, 5.5, 4.7],
            "urbana": [0.9, 1.2, 0.8, 1.0, 2.9, 2.1, 2.6, 3.2, 3.1, 3.1],
            "rural": [13.2, 12.8, 10.0, 9.8, 13.7, 12.1, 14.6, 16.2, 15.5, 11.4],
            "lima_metropolitana": [0.2, 0.7, 0.2, 0.4, 2.9, 2.0, 2.9, 3.2, 3.3, 3.6],
            "resto_urbano": [1.5, 1.5, 1.2, 1.3, 2.9, 2.1, 2.4, 3.2, 3.0, 2.8],
            "costa": [0.5, 0.8, 0.4, 0.6, 2.3, 1.6, 2.3, 2.7, 2.6, 2.8],
            "sierra": [8.3, 8.0, 6.3, 6.5, 9.9, 8.1, 8.9, 10.4, 9.9, 7.6],
            "selva": [6.5, 6.2, 4.6, 3.9, 6.0, 5.8, 7.7, 8.0, 7.9, 6.1],
        },
    },
    "gasto_real_pc": {
        "fuente": "Cuadro 2.1 p.28; Cuadro I.1 p.175 (resto urbano)", "unidad": "S/", "tol": 1.0,
        "valores": {
            "nacional": [974, 972, 988, 999, 840, 892, 898, 892, 903, 920],
            "urbana": [1102, 1097, 1112, 1117, 922, 972, 979, 967, 977, 991],
            "rural": [546, 539, 550, 567, 528, 577, 575, 584, 589, 615],
            "lima_metropolitana": [1214, 1211, 1214, 1210, 969, 1008, 1003, 1000, 1001, 1014],
            "resto_urbano": [1023, 1017, 1039, 1052, 889, 947, 962, 944, 960, 974],
            "costa": [1136, 1134, 1146, 1152, 946, 997, 997, 989, 996, 1009],
            "sierra": [788, 780, 800, 820, 711, 760, 788, 783, 800, 820],
            "selva": [741, 748, 766, 770, 689, 743, 725, 722, 733, 761],
            "costa_urbana": [1074, 1068, 1091, 1110, 941, 1007, 1013, 998, 1013, 1027],
            "costa_rural": [672, 691, 711, 741, 660, 751, 740, 731, 741, 734],
            "sierra_urbana": [1017, 1006, 1025, 1042, 867, 916, 957, 937, 958, 969],
            "sierra_rural": [539, 527, 541, 556, 518, 562, 569, 575, 581, 609],
            "selva_urbana": [895, 906, 931, 923, 802, 859, 838, 819, 830, 851],
            "selva_rural": [506, 499, 496, 513, 493, 537, 516, 537, 542, 577],
        },
    },
    "gasto_nominal_pc": {
        "fuente": "Cuadro I.8 p.190", "unidad": "S/", "tol": 1.0,
        "valores": {
            "nacional": [631, 649, 672, 694, 594, 663, 726, 761, 783, 809],
            "urbana": [727, 746, 769, 790, 664, 736, 805, 839, 861, 885],
            "rural": [308, 313, 325, 343, 326, 375, 410, 444, 455, 480],
        },
    },
    "ingreso_real_pc": {
        "fuente": "Cuadro 2.5 p.43; Cuadro I.15 p.205", "unidad": "S/", "tol": 1.0,
        "valores": {
            "nacional": [1295, 1276, 1304, 1321, 1047, 1182, 1199, 1186, 1213, 1252],
            "urbana": [1498, 1472, 1489, 1495, 1159, 1296, 1319, 1300, 1328, 1362],
            "rural": [617, 599, 646, 684, 622, 736, 717, 719, 727, 776],
            "costa": [1548, 1524, 1539, 1544, 1183, 1329, 1338, 1328, 1349, 1377],
            "sierra": [1004, 979, 1033, 1071, 888, 1009, 1044, 1033, 1063, 1109],
            "selva": [931, 937, 952, 959, 834, 953, 952, 924, 966, 1036],
        },
    },
    "ingreso_sin_ld_pc": {
        "fuente": "Cuadro I.19 p.217 (titulado «nominal»; en realidad a precios 2025 sin ld)",
        "unidad": "S/", "tol": 1.0,
        "valores": {
            "nacional": [1153, 1135, 1159, 1172, 924, 1041, 1056, 1047, 1070, 1104],
            "urbana": [1352, 1328, 1343, 1346, 1039, 1161, 1180, 1165, 1189, 1219],
            "rural": [484, 469, 505, 534, 486, 575, 560, 562, 568, 606],
        },
    },
    "vestido_real_pc": {
        "fuente": "Cuadro 2.4 p.34 / I.4 p.183 (Prendas de vestir y calzado)", "unidad": "S/",
        "tol": 1.0,
        "valores": {"nacional": [36, 36, 37, 39, 24, 26, 28, 29, 30, 30]},
    },
    "vestido_pct_gasto": {
        "fuente": "Cuadro I.5 p.185 (estructura del gasto real)", "unidad": "%", "tol": 0.1,
        "valores": {"nacional": [3.7, 3.7, 3.7, 3.9, 2.8, 2.9, 3.1, 3.2, 3.3, 3.3]},
    },
}

# Intervalo de confianza 95 % de la pobreza total nacional, todos los años (Gráfico 4.1, p.68).
OFFICIAL_CI_NATIONAL_POVERTY = {
    "fuente": "Gráfico 4.1 p.68",
    "inferior": [19.9, 20.9, 19.7, 19.3, 29.0, 24.8, 26.5, 28.0, 26.6, 24.6],
    "superior": [21.6, 22.5, 21.3, 21.1, 31.3, 26.9, 28.5, 30.0, 28.6, 26.7],
}

# Precisión publicada solo para 2025: (indicador, ámbito) -> (IC inf, IC sup, CV %, fuente).
OFFICIAL_PRECISION_2025 = {
    ("pobreza_total", "nacional"): (24.6, 26.7, 2.0, "Cuadro III.1 p.231"),
    ("pobreza_total", "urbana"): (22.2, 24.6, 2.6, "Cuadro III.1 p.231"),
    ("pobreza_total", "rural"): (33.8, 37.1, 2.3, "Cuadro III.1 p.231"),
    ("pobreza_total", "lima_metropolitana"): (24.9, 29.7, 4.4, "Cuadro III.1 p.231"),
    ("pobreza_total", "resto_urbano"): (19.5, 21.9, 2.9, "Cuadro III.1 p.231"),
    ("pobreza_total", "costa"): (22.2, 25.3, 3.3, "Cuadro III.1 p.231"),
    ("pobreza_total", "sierra"): (27.0, 30.2, 2.8, "Cuadro III.1 p.231"),
    ("pobreza_total", "selva"): (25.2, 29.5, 4.1, "Cuadro III.1 p.231"),
    ("pobreza_total", "costa_urbana"): (16.7, 19.6, 4.1, "Cuadro III.1 p.231"),
    ("pobreza_total", "costa_rural"): (19.8, 27.8, 8.6, "Cuadro III.1 p.231"),
    ("pobreza_total", "sierra_urbana"): (19.2, 23.6, 5.2, "Cuadro III.1 p.231"),
    ("pobreza_total", "sierra_rural"): (36.8, 40.9, 2.6, "Cuadro III.1 p.231"),
    ("pobreza_total", "selva_urbana"): (22.8, 28.5, 5.7, "Cuadro III.1 p.231"),
    ("pobreza_total", "selva_rural"): (27.5, 34.0, 5.4, "Cuadro III.1 p.231"),
    ("pobreza_extrema", "nacional"): (4.2, 5.1, 5.2, "Cuadro III.4 p.235"),
    ("pobreza_extrema", "urbana"): (2.6, 3.6, 8.4, "Cuadro III.4 p.235"),
    ("pobreza_extrema", "rural"): (10.2, 12.6, 5.3, "Cuadro III.4 p.235"),
    ("pobreza_extrema", "lima_metropolitana"): (2.6, 4.6, 14.0, "Cuadro III.4 p.235"),
    ("gasto_real_pc", "nacional"): (None, None, 0.7, "Cuadro I.1 p.175"),
    ("gasto_real_pc", "urbana"): (None, None, 0.9, "Cuadro I.1 p.175"),
    ("gasto_real_pc", "rural"): (None, None, 1.0, "Cuadro I.1 p.175"),
    ("gasto_real_pc", "lima_metropolitana"): (None, None, 1.7, "Cuadro I.1 p.175"),
    ("gasto_real_pc", "resto_urbano"): (None, None, 0.8, "Cuadro I.1 p.175"),
    ("gasto_real_pc", "costa"): (None, None, 1.1, "Cuadro I.1 p.175"),
    ("gasto_real_pc", "sierra"): (None, None, 1.1, "Cuadro I.1 p.175"),
    ("gasto_real_pc", "selva"): (None, None, 1.3, "Cuadro I.1 p.175"),
    ("gasto_real_pc", "costa_urbana"): (None, None, 1.0, "Cuadro I.1 p.175"),
    ("gasto_real_pc", "costa_rural"): (None, None, 2.6, "Cuadro I.1 p.175"),
    ("gasto_real_pc", "sierra_urbana"): (None, None, 1.6, "Cuadro I.1 p.175"),
    ("gasto_real_pc", "sierra_rural"): (None, None, 1.2, "Cuadro I.1 p.175"),
    ("gasto_real_pc", "selva_urbana"): (None, None, 1.7, "Cuadro I.1 p.175"),
    ("gasto_real_pc", "selva_rural"): (None, None, 2.0, "Cuadro I.1 p.175"),
    ("gasto_nominal_pc", "nacional"): (None, None, 0.8, "Cuadro I.8 p.190"),
    ("gasto_nominal_pc", "urbana"): (None, None, 0.9, "Cuadro I.8 p.190"),
    ("gasto_nominal_pc", "rural"): (None, None, 1.0, "Cuadro I.8 p.190"),
    ("ingreso_real_pc", "nacional"): (None, None, 0.9, "Cuadro I.15 p.205"),
    ("ingreso_real_pc", "urbana"): (None, None, 1.1, "Cuadro I.15 p.205"),
    ("ingreso_real_pc", "rural"): (None, None, 1.2, "Cuadro I.15 p.205"),
    ("ingreso_real_pc", "costa"): (None, None, 1.4, "Cuadro I.15 p.205"),
    ("ingreso_real_pc", "sierra"): (None, None, 1.5, "Cuadro I.15 p.205"),
    ("ingreso_real_pc", "selva"): (None, None, 1.7, "Cuadro I.15 p.205"),
    ("vestido_real_pc", "nacional"): (None, None, 1.3, "Cuadro I.4 p.183"),
}
# Los anexos de gasto/ingreso (I.1, I.4, I.8, I.15) solo se reproducen en región natural si la
# varianza se calcula sobre la submuestra (Stata `svy: mean ... if`); los de pobreza (III.1,
# III.4), con dominio «subpop» (todas las PSU). En ámbitos alineados con estratos da lo mismo.
SUBSET_VARIANCE_INDICATORS = {"gasto_real_pc", "gasto_nominal_pc", "ingreso_real_pc",
                              "ingreso_sin_ld_pc", "vestido_real_pc"}
TOL_CI = 0.1   # puntos porcentuales en los límites del IC
TOL_CV = 0.1   # puntos de CV (el INEI publica el CV con 1 decimal)


# --------------------------------------------------------------------------------------------
# Insumos
# --------------------------------------------------------------------------------------------
def load_price_coefficients() -> pd.DataFrame:
    """Coeficiente deflactor i00..i08 por (año, departamento) = IPC promedio del año / IPC 2025.

    Lee data/processed/deflactores/deflactor_temporal.parquet (construir_deflactores.py, que
    replica 02_Programa-actualización_de_la_pobreza-2025.do, líneas 17-69). Así esta validación
    prueba la misma tabla que usan los demás proyectos.
    """
    temporal = pd.read_parquet(TEMPORAL_FILE)
    if int(temporal["anio_base"].iloc[0]) != BASE_YEAR:
        raise ValueError(f"deflactor_temporal con base {temporal['anio_base'].iloc[0]}, "
                         f"se espera {BASE_YEAR}: correr construir_deflactores.py")
    coefficients = temporal[["anio", "dpto"] + [f"def_i0{k}" for k in range(9)]].copy()
    coefficients["dpto"] = coefficients["dpto"].astype(int)
    return coefficients.rename(columns={f"def_i0{k}": f"i0{k}" for k in range(9)})


def load_spatial_deflator() -> pd.Series:
    """Deflactor espacial ld por dominioA (17 valores; Lima Metropolitana = 1)."""
    ld = pd.read_parquet(SPATIAL_FILE)
    return ld.set_index("dominio_a")["ld"]


def sumaria_path(year: int) -> Path:
    return PROCESSED_DIR / str(year) / f"sumaria-{year}.parquet"


def load_sumaria(year: int, coefficients: pd.DataFrame) -> pd.DataFrame:
    """Lee la Sumaria 8G del año y agrega las variables derivadas que usa el INEI."""
    path = sumaria_path(year)
    available = set(pq.read_schema(path).names)
    group_cols = [c for cols in EXPENDITURE_GROUPS.values() for c in cols if c in available]
    df = pd.read_parquet(path, columns=BASE_COLUMNS + group_cols)
    for cols in EXPENDITURE_GROUPS.values():
        for col in cols:
            if col not in df.columns:  # p. ej. sg27/sig28 (2016) o gru52hd2 (2017+) no existen
                df[col] = 0.0
    num_cols = [c for c in df.columns if c not in ("conglome", "ubigeo")]
    df[num_cols] = df[num_cols].astype(float)
    df[group_cols] = df[group_cols].fillna(0.0)

    df["dpto"] = df["ubigeo"].str[:2].astype(int).replace({7: 15})  # Callao usa el IPC de Lima
    df["urbana"] = df["estrato"] <= 5
    df["facpob07"] = (df["factor07"] * df["mieperho"]).round()
    df["region"] = np.select(
        [df["dominio"].isin([1, 2, 3, 8]), df["dominio"].isin([4, 5, 6])],
        ["costa", "sierra"], "selva")
    df["dominio_a"] = build_dominio_a(df)

    coef_year = coefficients[coefficients["anio"] == year].set_index("dpto")
    df = df.join(coef_year[[f"i0{k}" for k in range(9)]], on="dpto")

    monthly_people = 12.0 * df["mieperho"]
    df["gasto_nominal_pc"] = df["gashog2d"] / monthly_people
    df["gasto_real_pc"] = 0.0
    for k, cols in EXPENDITURE_GROUPS.items():
        group_real = df[cols].sum(axis=1) / (monthly_people * df["ld"] * df[f"i0{k}"])
        df[f"grupo{k}_real_pc"] = group_real
        df["gasto_real_pc"] += group_real
    df["gasto_real_i00_pc"] = df["gashog2d"] / (monthly_people * df["ld"] * df["i00"])
    df["vestido_real_pc"] = df["grupo2_real_pc"]
    df["ingreso_real_pc"] = df["inghog1d"] / (monthly_people * df["ld"] * df["i00"])
    df["ingreso_sin_ld_pc"] = df["inghog1d"] / (monthly_people * df["i00"])
    df["pobre_total"] = df["pobreza"].isin([1, 2]).astype(float)
    df["pobre_extremo"] = (df["pobreza"] == 1).astype(float)
    return df


def build_dominio_a(df: pd.DataFrame) -> pd.Series:
    """dominioA de las rutinas INEI (17 dominios x área); ver construir_deflactores.py."""
    return _dominio_a(df)


def area_masks(df: pd.DataFrame) -> dict[str, pd.Series]:
    """Máscaras booleanas de cada ámbito publicado por el INEI."""
    urb, lima = df["urbana"], df["dominio"] == 8
    masks = {
        "nacional": pd.Series(True, index=df.index),
        "urbana": urb,
        "rural": ~urb,
        "lima_metropolitana": lima,
        "resto_urbano": urb & ~lima,
    }
    for region in ("costa", "sierra", "selva"):
        reg = df["region"] == region
        masks[region] = reg
        if region == "costa":  # Cuadros 2.1/4.1: costa urbana/rural excluyen Lima Met.
            reg = reg & ~lima
        masks[f"{region}_urbana"] = reg & urb
        masks[f"{region}_rural"] = reg & ~urb
    return masks


# --------------------------------------------------------------------------------------------
# Estimación con diseño complejo
# --------------------------------------------------------------------------------------------
def survey_ratio(y: pd.Series, x: pd.Series, weight: pd.Series, strata: pd.Series,
                 psu: pd.Series, domain: pd.Series, subset: bool = False) -> tuple[float, float]:
    """Razón ponderada R = Σw·y / Σw·x en un dominio y su error estándar (Taylor).

    subset=False (por defecto, «subpop»): no filtra la base; fuera del dominio y = x = 0, así se
    conservan todas las PSU. subset=True replica `svy: mean ... if dominio` de Stata: descarta las
    PSU fuera del dominio antes de calcular la varianza.
    Varianza con reemplazo entre PSU dentro de cada estrato: Σ_h n_h/(n_h-1) Σ_c (z_hc - z̄_h)².
    """
    if subset:
        keep = domain.astype(bool)
        y, x, weight, strata, psu = (s[keep] for s in (y, x, weight, strata, psu))
        domain = domain[keep]
    d = domain.astype(float)
    wy, wx = weight * y * d, weight * x * d
    total_x = wx.sum()
    ratio = wy.sum() / total_x
    z = (wy - ratio * wx) / total_x
    psu_totals = z.groupby([strata, psu]).sum()
    grouped = psu_totals.groupby(level=0)
    n_h = grouped.transform("size")
    dev = (psu_totals - grouped.transform("mean")) ** 2 * n_h / (n_h - 1)
    variance = dev[n_h > 1].sum()
    return float(ratio), float(np.sqrt(variance))


def estimate_year(df: pd.DataFrame) -> dict[tuple[str, str], tuple[float, float, float]]:
    """Calcula (estimación, EE subpop, EE subset) para cada indicador y ámbito publicado."""
    masks = area_masks(df)
    one = pd.Series(1.0, index=df.index)
    args = dict(weight=df["facpob07"], strata=df["estrato"], psu=df["conglome"])
    results: dict[tuple[str, str], tuple[float, float, float]] = {}
    per_capita = {
        "pobreza_total": ("pobre_total", one, 100.0),
        "pobreza_extrema": ("pobre_extremo", one, 100.0),
        "gasto_real_pc": ("gasto_real_pc", one, 1.0),
        "gasto_nominal_pc": ("gasto_nominal_pc", one, 1.0),
        "ingreso_real_pc": ("ingreso_real_pc", one, 1.0),
        "ingreso_sin_ld_pc": ("ingreso_sin_ld_pc", one, 1.0),
        "vestido_real_pc": ("vestido_real_pc", one, 1.0),
        "vestido_pct_gasto": ("vestido_real_pc", df["gasto_real_pc"], 100.0),
        "gasto_real_i00_pc": ("gasto_real_i00_pc", one, 1.0),
    }
    for indicator, (ycol, x, scale) in per_capita.items():
        areas = OFFICIAL_SERIES.get(indicator, OFFICIAL_SERIES["gasto_real_pc"])["valores"]
        for area in areas:
            est, se_dom = survey_ratio(df[ycol], x, domain=masks[area], **args)
            _, se_sub = survey_ratio(df[ycol], x, domain=masks[area], subset=True, **args)
            results[(indicator, area)] = (est * scale, se_dom * scale, se_sub * scale)
    return results


# --------------------------------------------------------------------------------------------
# Diagnósticos de la base
# --------------------------------------------------------------------------------------------
def diagnose(df: pd.DataFrame, ld_table: pd.Series) -> list[str]:
    """Chequeos de consistencia de la Sumaria del año (no comparan contra el INEI)."""
    gpcm = df["gashog2d"] / (12 * df["mieperho"])
    recomputed = np.where(gpcm < df["linpe"], 1, np.where(gpcm < df["linea"], 2, 3))
    group_sum = sum(df[cols].sum(axis=1) for cols in EXPENDITURE_GROUPS.values())
    ld_diff = (df["ld"] - df["dominio_a"].map(ld_table)).abs().max()
    psu_multi = (df.groupby("conglome")["estrato"].nunique() > 1).sum()
    return [
        f"hogares={len(df):,}  personas expandidas={df['facpob07'].sum():,.0f}  "
        f"PSU={df['conglome'].nunique():,}",
        f"pobreza != recalculada con gashog2d/(12*mieperho) vs linpe/linea: "
        f"{int((recomputed != df['pobreza']).sum())} hogares",
        f"|Σ 8 grupos - gashog2d| máx = {np.abs(group_sum - df['gashog2d']).max():.4f} soles/año",
        f"|ld Sumaria - despacial_ldnew(dominioA)| máx = {ld_diff:.6f}",
        f"conglomerados en más de un estrato: {psu_multi}",
        f"hogares con mieperho<=0 o gashog2d<=0: "
        f"{int(((df['mieperho'] <= 0) | (df['gashog2d'] <= 0)).sum())}",
    ]


# --------------------------------------------------------------------------------------------
# Comparación y salida
# --------------------------------------------------------------------------------------------
def fmt(value: float | None, decimals: int) -> str:
    return "—" if value is None or pd.isna(value) else f"{value:,.{decimals}f}"


def compare_year(year: int, results: dict) -> list[dict]:
    """Filas de comparación oficial vs calculado para un año."""
    idx = YEARS.index(year)
    rows = []
    for indicator, spec in OFFICIAL_SERIES.items():
        decimals = 1 if spec["unidad"] == "%" else 0
        for area, values in spec["valores"].items():
            official = values[idx]
            est = results[(indicator, area)][0]
            diff = est - official
            rows.append(dict(anio=year, indicador=indicator, ambito=area, tipo="valor",
                             oficial=official, calculado=est, dif=diff,
                             ok=abs(diff) <= spec["tol"] + 1e-9, dec=decimals,
                             fuente=spec["fuente"]))
    lo, hi = (OFFICIAL_CI_NATIONAL_POVERTY[k][idx] for k in ("inferior", "superior"))
    est, se, _ = results[("pobreza_total", "nacional")]
    for label, official, calc in (("IC95 inf", lo, est - Z_95 * se),
                                  ("IC95 sup", hi, est + Z_95 * se)):
        rows.append(dict(anio=year, indicador="pobreza_total", ambito="nacional", tipo=label,
                         oficial=official, calculado=calc, dif=calc - official,
                         ok=abs(calc - official) <= TOL_CI + 1e-9, dec=1,
                         fuente=OFFICIAL_CI_NATIONAL_POVERTY["fuente"]))
    if year == BASE_YEAR:
        for (indicator, area), (lo, hi, cv, source) in OFFICIAL_PRECISION_2025.items():
            est, se_dom, se_sub = results[(indicator, area)]
            se = se_sub if indicator in SUBSET_VARIANCE_INDICATORS else se_dom
            checks = [("CV %", cv, 100 * se / est, TOL_CV)]
            if lo is not None and area != "nacional":  # el nacional ya se comparó arriba
                checks += [("IC95 inf", lo, est - Z_95 * se, TOL_CI),
                           ("IC95 sup", hi, est + Z_95 * se, TOL_CI)]
            for label, official, calc, tol in checks:
                rows.append(dict(anio=year, indicador=indicator, ambito=area, tipo=label,
                                 oficial=official, calculado=calc, dif=calc - official,
                                 ok=abs(calc - official) <= tol + 1e-9, dec=1, fuente=source))
    return rows


def print_rows(rows: list[dict]) -> None:
    header = (f"{'indicador':<18} {'ámbito':<19} {'tipo':<8} {'oficial':>9} {'calculado':>10} "
              f"{'dif':>7}  {'OK':<5} fuente")
    print(header)
    print("-" * len(header))
    for r in rows:
        dec = r["dec"]
        calc_dec = 2 if dec == 1 else 1
        print(f"{r['indicador']:<18} {r['ambito']:<19} {r['tipo']:<8} "
              f"{fmt(r['oficial'], dec):>9} {fmt(r['calculado'], calc_dec):>10} "
              f"{r['dif']:>+7.2f}  {'OK' if r['ok'] else 'FALLA':<5} {r['fuente']}")


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):  # consola Windows (cp1252) y python -E
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    years = [int(a) for a in argv] if argv else YEARS
    coefficients = load_price_coefficients()
    ld_table = load_spatial_deflator()
    all_rows, pending = [], []
    for year in years:
        print(f"\n{'=' * 100}\nENAHO {year}\n{'=' * 100}")
        if not sumaria_path(year).exists():
            print(f"PENDIENTE: no existe {sumaria_path(year).relative_to(ROOT)} "
                  "(conversión a Parquet en curso). Vuelve a correr el script más tarde.")
            pending.append(year)
            continue
        df = load_sumaria(year, coefficients)
        for line in diagnose(df, ld_table):
            print(f"  · {line}")
        results = estimate_year(df)
        est_g = results[("gasto_real_pc", "nacional")][0]
        est_i00 = results[("gasto_real_i00_pc", "nacional")][0]
        rur_g = results[("gasto_real_pc", "rural")][0]
        rur_i00 = results[("gasto_real_i00_pc", "rural")][0]
        print(f"  · gasto real con IPC por grupo (método INEI) vs con i00 único: "
              f"nacional {est_g:.1f} vs {est_i00:.1f}; rural {rur_g:.1f} vs {rur_i00:.1f}")
        rows = compare_year(year, results)
        print()
        print_rows(rows)
        all_rows.extend(rows)

    print(f"\n{'=' * 100}\nRESUMEN\n{'=' * 100}")
    if all_rows:
        summary = pd.DataFrame(all_rows)
        summary["grupo"] = np.where(summary["tipo"] == "valor", "valor", "precisión")
        table = (summary.groupby(["anio", "grupo"])["ok"]
                 .agg(comparaciones="size", ok="sum").reset_index())
        table["fallas"] = table["comparaciones"] - table["ok"]
        print(table.to_string(index=False))
        failures = summary[~summary["ok"]]
        if len(failures):
            print("\nComparaciones fuera de tolerancia:")
            print_rows(failures.to_dict("records"))
        else:
            print("\nTodas las comparaciones están dentro de tolerancia.")
    if pending:
        print(f"\nAños PENDIENTES (sin Parquet de Sumaria): {', '.join(map(str, pending))}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
