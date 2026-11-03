"""Genera `outputs/transmision_bcrp.html`: tablero de la transmisión de la política monetaria en el Perú.

Lee los paneles mensual y diario de `data/processed/` (correr antes `construir_tablas.py`), las tasas de
operaciones nuevas de la SBS (`../descargas-sbs`), la capa comparable de `../data_macro_paises` (tasas de
política de la región y de la Fed) y, si existe, el módulo de análisis `transmision_analisis.py` (ciclos,
traspaso por ciclo, modelo de corrección de errores y multiplicadores). Arma los datos que usa la página y
los inyecta en la plantilla `src/plantillas/transmision.html`. El HTML resultante es autocontenido (sin
librerías externas) y se abre con doble clic. Genera además `outputs/transmision_bcrp_artifact.html`, la
versión para publicar como Artifact de claude.ai (sin <html>/<head>/<body>).

Si falta una serie (o el módulo de análisis), el bloque que la usa se omite con un aviso en consola en vez
de fallar. Al generar imprime controles: interbancaria dentro del corredor, identidades de los saldos de
inyección y esterilización, último mes por bloque, posibles quiebres de serie y número de series.

Uso:
    python visual_transmision.py
"""
from __future__ import annotations

import datetime as dt
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from visual_reservas import artifact_version, month_key, num  # noqa: E402

PROJECT_DIR = Path(__file__).resolve().parents[1]
PROCESSED = PROJECT_DIR / "data" / "processed"
SERIES_CSV = PROJECT_DIR / "config" / "series.csv"
TEMPLATE = PROJECT_DIR / "src" / "plantillas" / "transmision.html"
OUT = PROJECT_DIR / "outputs" / "transmision_bcrp.html"
OUT_ARTIFACT = PROJECT_DIR / "outputs" / "transmision_bcrp_artifact.html"
PLACEHOLDER = "/*__DATA__*/null"
COMPARABLE = PROJECT_DIR.parent / "data_macro_paises" / "data" / "processed" / "comparable"
SBS_TASAS = PROJECT_DIR.parent / "descargas-sbs" / "data" / "processed" / "tasas_activas.parquet"

START = pd.Timestamp("2003-09-01")   # inicio de la tasa de referencia
DAILY_YEARS = 3                      # ventana de las series diarias que se incrustan
LIVE_MONTHS = 3                      # una serie sigue «viva» si su último dato está a 3 meses o menos del final
PEAK_FROM = "2021-01"                # región: máximo de la tasa de política desde este mes hasta el último dato

WARNINGS: list[str] = []


def warn(msg: str) -> None:
    WARNINGS.append(msg)
    print(f"  AVISO: {msg}")


# ---------------------------------------------------------------------------------------------
# Series mensuales que usa la página. Clave corta (la que lee el JS) -> columna del panel.
# ---------------------------------------------------------------------------------------------
MONTHLY = {
    # Corredor y mercado interbancario
    "ref": "tasa_referencia", "on": "tasa_depositos_overnight_mn", "vent": "tasa_creditos_regulacion_monetaria_mn",
    "ib": "tasa_interbancaria_mn", "ibme": "tasa_interbancaria_me", "exp": "expectativa_inflacion_12m",
    "tc": "tc_interbancario_prom",
    # CD del BCRP
    "cd3": "tasa_cd_bcrp_hasta3m", "cd6": "tasa_cd_bcrp_4a6m", "cd12": "tasa_cd_bcrp_7m_1a",
    "cd24": "tasa_cd_bcrp_1a_2a",
    # Activas MN de los bancos (BCRP, por modalidad)
    "pref": "tasa_preferencial_corp_mn", "corp": "tasa_bancos_corporativo_hasta360_mn",
    "gde": "tasa_bancos_grandes_empresas_hasta360_mn", "med": "tasa_bancos_medianas_empresas_hasta360_mn",
    "pym": "tasa_bancos_pyme_hasta360_mn", "cons": "tasa_bancos_consumo_prest_hasta360_mn",
    "hip": "tasa_bancos_hipotecario_mn", "ftamn": "ftamn", "tamn": "tamn",
    "estc": "tasa_bancos_estructura_constante_mn",
    # Activas ME
    "corpme": "tasa_bancos_corporativo_hasta360_me", "hipme": "tasa_bancos_hipotecario_me",
    # Pasivas MN
    "aho": "tasa_pasiva_ahorro_mn", "cc": "tasa_pasiva_cuenta_corriente_mn", "p30": "tasa_pasiva_plazo_hasta30d_mn",
    "p180": "tasa_pasiva_plazo_31a180d_mn", "p360": "tasa_pasiva_plazo_181a360d_mn",
    "p360m": "tasa_pasiva_plazo_mas360d_mn", "ftipmn": "ftipmn",
    # Bonos
    "b10": "bono_soberano_10a_soles", "b10usd": "bono_soberano_10a_usd",
    # Dolarización, crédito y encaje
    "dolc": "dolarizacion_credito", "doll": "dolarizacion_liquidez",
    "crmn": "credito_privado_mn_var12m", "crme": "credito_privado_me_var12m",
    "crtc": "credito_privado_tc_constante_var12m",
    "cremp": "credito_empresas_mn_var12m", "crcon": "credito_consumo_mn_var12m", "crhip": "credito_hipotecario_mn_var12m",
    "enxmn": "encaje_exigible_mn_pct", "enfmn": "encaje_efectivo_mn_pct",
    "enxme": "encaje_exigible_me_pct", "enfme": "encaje_efectivo_me_pct",
}
# Tramos de los bonos del Tesoro: el 0 es «sin dato» (meses sin colocación), no una tasa.
TRAMOS = {"t5": "tasa_bonos_tesoro_hasta5a", "t510": "tasa_bonos_tesoro_5a10a",
          "t1015": "tasa_bonos_tesoro_10a15a", "t1520": "tasa_bonos_tesoro_15a20a", "t20": "tasa_bonos_tesoro_mas20a"}
LIQ_COLS = ["op_bcrp_sistema_financiero_saldo", "repo_valores_saldo", "repo_monedas_saldo", "repo_cartera_saldo",
            "repo_cartera_garantia_estatal_saldo", "valores_bcrp_saldo", "cd_bcrp_saldo", "cdr_bcrp_saldo",
            "cdv_bcrp_saldo", "depositos_intermediarios_bcrp_saldo", "depositos_overnight_bcrp_saldo",
            "depositos_intermediarios_otros_bcrp_saldo"]
CORR_COLS = ["tasa_interbancaria_mn", "tasa_depositos_overnight_mn", "tasa_creditos_regulacion_monetaria_mn"]

# Una sola regla para las tasas sin traspaso publicado (dependen sobre todo del riesgo y de los costos operativos,
# o de la composición) y para las tasas del BCRP por modalidad que van como contraste. El JS lee estas listas.
RISK_NC = ["tasa_bancos_pyme_hasta360_mn", "tasa_bancos_consumo_prest_hasta360_mn", "ftamn",
           "sbs_pequenas", "sbs_micro", "sbs_consumo"]
CONTRAST_NC = ["tasa_bancos_corporativo_hasta360_mn", "tasa_bancos_grandes_empresas_hasta360_mn",
               "tasa_bancos_medianas_empresas_hasta360_mn", "tasa_bancos_hipotecario_mn"]

# Bloques (para el pie, el control del último mes y los códigos de BCRPData).
BLOCKS = [
    ("Tasa de referencia y corredor", ["tasa_referencia", "tasa_depositos_overnight_mn",
                                       "tasa_creditos_regulacion_monetaria_mn", "tasa_referencia_diario"]),
    ("Interbancaria", ["tasa_interbancaria_mn", "tasa_interbancaria_me", "tasa_interbancaria_mn_diario"]),
    ("Expectativa de inflación a 12 meses", ["expectativa_inflacion_12m"]),
    ("Tipo de cambio", ["tc_interbancario_prom"]),
    ("Tasas de los CD BCRP", ["tasa_cd_bcrp_hasta3m", "tasa_cd_bcrp_4a6m", "tasa_cd_bcrp_7m_1a", "tasa_cd_bcrp_1a_2a"]),
    ("Tasas activas de los bancos en soles", ["tasa_preferencial_corp_mn", "tasa_bancos_corporativo_hasta360_mn",
        "tasa_bancos_grandes_empresas_hasta360_mn", "tasa_bancos_medianas_empresas_hasta360_mn",
        "tasa_bancos_pyme_hasta360_mn", "tasa_bancos_consumo_prest_hasta360_mn", "tasa_bancos_hipotecario_mn",
        "ftamn", "tamn", "tasa_bancos_estructura_constante_mn"]),
    ("Tasas activas en dólares", ["tasa_bancos_corporativo_hasta360_me", "tasa_bancos_hipotecario_me"]),
    ("Tasas pasivas en soles", ["tasa_pasiva_ahorro_mn", "tasa_pasiva_cuenta_corriente_mn",
        "tasa_pasiva_plazo_hasta30d_mn", "tasa_pasiva_plazo_31a180d_mn", "tasa_pasiva_plazo_181a360d_mn",
        "tasa_pasiva_plazo_mas360d_mn", "ftipmn"]),
    ("Bonos soberanos y del Tesoro", ["bono_soberano_10a_soles", "bono_soberano_10a_usd", "bono_soberano_10a_soles_diario",
        "tasa_bonos_tesoro_hasta5a", "tasa_bonos_tesoro_5a10a", "tasa_bonos_tesoro_10a15a",
        "tasa_bonos_tesoro_15a20a", "tasa_bonos_tesoro_mas20a", "ust_10a_diario"]),
    ("Dolarización y crédito", ["dolarizacion_credito", "dolarizacion_liquidez", "credito_privado_mn_var12m",
        "credito_privado_me_var12m", "credito_privado_tc_constante_var12m", "credito_empresas_mn_var12m",
        "credito_consumo_mn_var12m", "credito_hipotecario_mn_var12m"]),
    ("Encaje", ["encaje_exigible_mn_pct", "encaje_efectivo_mn_pct", "encaje_exigible_me_pct", "encaje_efectivo_me_pct"]),
    ("Saldos de las operaciones monetarias", LIQ_COLS),
]

# Tasa neutral estimada por el BCRP (con su historia). Cambiar cuando un Reporte de Inflación publique otra.
NEUTRAL_RATE = {
    "real": 2.0, "lo": 1.0, "hi": 2.6, "nominal": 4.0, "m": "2026-06",
    "fuente": "BCRP, Reporte de Inflación de junio de 2026, Recuadro 4: mediana de ocho estimaciones con datos hasta 2025",
    "historia": [
        {"m": "2019-11", "real": 1.5, "fuente": "Reporte de Inflación de diciembre de 2019, Recuadro 5"},
        {"m": "2023-09", "real": 2.1, "fuente": "Reporte de Inflación de setiembre de 2023, según el de junio de 2026"},
    ],
}
# Meta de inflación del BCRP (para la expectativa frente al rango meta).
INFLATION_TARGETS = [
    {"desde": "2002-01", "hasta": "2007-01", "lo": 1.5, "hi": 3.5},
    {"desde": "2007-02", "hasta": None, "lo": 1.0, "hi": 3.0},
]

# Razón oficial de las decisiones de cada ciclo (Notas Informativas del Programa Monetario del BCRP).
# Clave 'YYYY-MM' = mes de la decisión citada. Una causa se muestra en el ciclo cuyo periodo contiene ese mes.
# Solo afirmaciones verificadas en la nota citada; sin entrada, la página da las cifras sin explicar el porqué.
CYCLE_CAUSES = {
    "2003-11": {"t": "la inflación proyectada para diciembre de 2003 estaba en el límite inferior de la meta",
                "f": "Nota Informativa del Programa Monetario de noviembre de 2003"},
    "2004-08": {"t": "choques de oferta en alimentos y combustibles habían llevado la inflación transitoriamente por encima del límite superior de la meta",
                "f": "Nota Informativa del Programa Monetario de agosto de 2004"},
    "2005-12": {"t": "para contribuir a reducir la volatilidad cambiaria y encarecer los movimientos especulativos",
                "f": "Notas Informativas del Programa Monetario de diciembre de 2005 y mayo de 2006"},
    "2007-07": {"t": "primero, de forma preventiva, ante el robusto crecimiento de la demanda interna; después, para evitar que el alza de los precios internacionales de alimentos y combustibles pasara a las expectativas de inflación; en 2008 también subió los encajes",
                "f": "Notas Informativas del Programa Monetario de julio de 2007, marzo de 2008 y setiembre de 2008"},
    "2009-02": {"t": "tras inyectar liquidez y bajar encajes desde setiembre de 2008, por las menores presiones inflacionarias, el menor crecimiento mundial y la caída de los precios internacionales de alimentos y combustibles; la inflación y sus expectativas bajaban",
                "f": "Notas Informativas del Programa Monetario de enero, febrero y agosto de 2009"},
    "2010-05": {"t": "para retirar de forma preventiva el estímulo ante el claro crecimiento de la producción, sin presiones inflacionarias; la última alza (mayo de 2011) buscó limitar el efecto del alza internacional de alimentos y combustibles en las expectativas",
                "f": "Notas Informativas del Programa Monetario de mayo de 2010 y mayo de 2011"},
    "2013-11": {"t": "la economía crecía por debajo de su potencial",
                "f": "Notas Informativas del Programa Monetario de noviembre de 2013 y enero de 2015"},
    "2015-09": {"t": "las expectativas de inflación llegaron al tope del rango meta y luego lo superaron, por el alza de algunos alimentos y la depreciación del sol",
                "f": "Notas Informativas del Programa Monetario de setiembre de 2015 y febrero de 2016"},
    "2017-05": {"t": "se revertían los choques de oferta y la actividad crecía por debajo de su potencial",
                "f": "Notas Informativas del Programa Monetario de mayo de 2017 y marzo de 2018"},
    "2019-08": {"t": "para ampliar el estímulo, con una inflación proyectada alrededor de 2% y riesgo de una demanda interna más débil",
                "f": "Notas Informativas del Programa Monetario de agosto y noviembre de 2019"},
    "2020-03": {"t": "la pandemia afectaba la actividad con un choque de oferta y una caída de la demanda",
                "f": "Notas Informativas del Programa Monetario del 19 de marzo y del 9 de abril de 2020"},
    "2021-08": {"t": "la inflación superó el rango meta por el alza de los precios internacionales de alimentos y combustibles y del tipo de cambio; luego esa alza se acentuó por conflictos internacionales, y las expectativas de inflación también superaron el rango",
                "f": "Notas Informativas del Programa Monetario de agosto de 2021, octubre de 2022 y enero de 2023"},
    "2023-09": {"t": "la inflación bajaba desde inicios de año y las expectativas se acercaban al rango meta; en noviembre de 2024 la nota indica que la tasa de interés real se acerca al nivel estimado como neutral, y en setiembre de 2025, que la tasa se ubica muy cerca de ese nivel",
                "f": "Notas Informativas del Programa Monetario de setiembre de 2023, noviembre de 2024 y setiembre de 2025"},
}

# Países de la comparación regional (capa comparable de data_macro_paises).
REGION = [("PER", "Perú"), ("CHL", "Chile"), ("COL", "Colombia"), ("MEX", "México"), ("BRA", "Brasil"),
          ("USA", "Estados Unidos")]
REGION_SOURCES = {
    "PER": "BCRP", "CHL": "Banco Central de Chile (TPM; expectativas: Encuesta de Expectativas Económicas)",
    "COL": "Banco de la República (tasa de política; expectativas: Encuesta mensual de expectativas de analistas económicos)",
    "MEX": "Banco de México (tasa objetivo; expectativas: Encuesta sobre las Expectativas de los Especialistas en Economía del Sector Privado)",
    "BRA": "Banco Central do Brasil (Meta Selic; expectativas: encuesta Focus)",
    "USA": "Reserva Federal (rango objetivo de los fondos federales, punto medio)",
}
USO_OK = {"comparable", "comparable_con_ajuste"}

# Tasas de las operaciones nuevas de la SBS (banca múltiple, fila «Promedio», operaciones de los últimos 30 días
# útiles, en soles). La clave es la misma que usa el módulo de análisis: sbs_<tipo>.
SBS_TIPOS = ["corporativo", "grandes", "medianas", "pequenas", "micro", "consumo", "hipotecario"]
JUMP_PP = 10.0            # salto mensual que se marca como posible quiebre de serie
JUMP_FROM = "2021-01"     # antes, los saltos de 2020 se deben a Reactiva Perú y a la pandemia


# ---------------------------------------------------------------------------------------------
def load_panel(freq: str) -> pd.DataFrame:
    df = pd.read_csv(PROCESSED / f"bcrp_panel_{freq}.csv", parse_dates=["fecha"], encoding="utf-8-sig")
    df = df.set_index("fecha").sort_index()
    if freq == "mensual":
        df.index = df.index.to_period("M").to_timestamp()
        df = df[~df.index.duplicated(keep="last")]
    return df


def get_col(m: pd.DataFrame, col: str, what: str) -> pd.Series | None:
    if col not in m.columns or m[col].dropna().empty:
        warn(f"falta la columna {col} ({what}); se omite")
        return None
    return m[col]


def series_list(s: pd.Series | None, months: pd.DatetimeIndex, nd: int = 2) -> list | None:
    if s is None:
        return None
    s = s.reindex(months)
    return [num(v, nd) for v in s.values]


def clean(o):
    """Convierte numpy/NaN a tipos JSON (NaN -> None)."""
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if (math.isnan(float(o)) or math.isinf(float(o))) else round(float(o), 4)
    if isinstance(o, pd.Timestamp):
        return o.strftime("%Y-%m")
    if isinstance(o, dt.date):
        return o.isoformat()
    return o


def _import_analysis():
    import transmision_analisis as ta  # noqa: PLC0415
    return ta


# ---------------------------------------------------------------------------------------------
# Ciclos: siempre con la regla del módulo de análisis (`find_cycles`), también como respaldo.
# ---------------------------------------------------------------------------------------------
def detect_cycles(ref: pd.Series) -> list[dict]:
    try:
        ta = _import_analysis()
        cyc = ta.find_cycles(ref)
        return [{k: v for k, v in c.items() if not k.startswith("_")} for c in cyc]
    except Exception as exc:  # noqa: BLE001
        warn(f"no se pudieron detectar los ciclos con la regla del análisis ({type(exc).__name__}: {exc}); se omiten")
        return []


def load_analysis(m: pd.DataFrame, d: pd.DataFrame) -> dict | None:
    try:
        ta = _import_analysis()
        res = ta.build_transmission(m, d)
    except Exception as exc:  # módulo ausente o con error
        warn(f"no se pudo cargar el análisis de traspaso ({type(exc).__name__}: {exc}); se omiten esos bloques")
        return None
    if not isinstance(res, dict):
        warn("el análisis de traspaso no devolvió un diccionario; se omiten esos bloques")
        return None
    for key in ["ciclos", "tasas", "traspaso_ciclo", "ecm", "respuesta", "metodo"]:
        if key not in res:
            warn(f"el análisis de traspaso no trae '{key}'")
    ctrl = res.get("controles") or []
    print(f"  controles del análisis ({len(ctrl)}):")
    for c in ctrl:
        if str(c).startswith("Aviso"):
            warn("análisis: " + str(c))
        else:
            print("    " + str(c)[:220])
    res = {k: v for k, v in res.items() if k != "controles"}
    # Solo viajan al HTML las filas de traspaso de las tasas en soles (las demás no se muestran).
    mn = {t["k"] for t in res.get("tasas", []) if t.get("mon") == "MN"}
    res["traspaso_ciclo"] = [r for r in res.get("traspaso_ciclo", []) if r.get("k") in mn]
    return clean(res)


def analysis_params() -> dict:
    """Parámetros del método que el texto público cita (se toman del módulo si está)."""
    out = {"lag": 6, "long_pause": 12}
    try:
        ta = _import_analysis()
        out["lag"] = int(getattr(ta, "LAG_AFTER_CYCLE", 6))
        out["long_pause"] = int(getattr(ta, "LONG_PAUSE", 12))
    except Exception:  # noqa: BLE001
        pass
    return out


# ---------------------------------------------------------------------------------------------
def build_codes(used_cols: set[str]) -> list[dict]:
    """Códigos de BCRPData por bloque, para el pie."""
    cat = pd.read_csv(SERIES_CSV, encoding="utf-8-sig")
    code = dict(zip(cat.nombre_corto, cat.codigo))
    out = []
    for name, cols in BLOCKS:
        cs = [code[c] for c in cols if c in code and c in used_cols]
        if cs:
            out.append({"b": name, "c": cs})
    return out


def build_daily(d: pd.DataFrame, m: pd.DataFrame) -> dict | None:
    need = ["tasa_referencia_diario", "tasa_interbancaria_mn_diario"]
    if any(c not in d.columns for c in need):
        warn("faltan la tasa de referencia o la interbancaria diarias; se omite la vista diaria")
        return None
    if any(c not in m.columns for c in CORR_COLS[1:]) or "tasa_referencia" not in m.columns:
        warn("falta el corredor mensual; se omite la vista diaria")
        return None
    df = d[need].dropna(how="all")
    both = df.dropna()
    if both.empty:
        warn("la referencia y la interbancaria diarias no tienen días en común; se omite la vista diaria")
        return None
    last = both.index.max()
    df = df.loc[last - pd.DateOffset(years=DAILY_YEARS):last]
    ref = df["tasa_referencia_diario"].ffill()
    per = df.index.to_period("M").to_timestamp()
    spread_on = pd.Series((m["tasa_depositos_overnight_mn"] - m["tasa_referencia"]).reindex(per).values).ffill().values
    spread_ve = pd.Series((m["tasa_creditos_regulacion_monetaria_mn"] - m["tasa_referencia"]).reindex(per).values).ffill().values
    on = ref.values + spread_on
    ve = ref.values + spread_ve
    ib = df["tasa_interbancaria_mn_diario"].values
    ok = ~np.isnan(ib) & ~np.isnan(on) & ~np.isnan(ve)
    inside = ((ib[ok] >= on[ok] - 1e-9) & (ib[ok] <= ve[ok] + 1e-9)).sum()
    print(f"  control corredor diario (últimos {DAILY_YEARS} años): interbancaria dentro en {inside} de {ok.sum()} días")
    near = (np.abs(ib[ok] - ref.values[ok]) <= 0.05 + 1e-9).mean() * 100 if ok.any() else None
    return {"f": [t.strftime("%Y-%m-%d") for t in df.index], "ref": [num(v, 2) for v in ref.values],
            "ib": [num(v, 2) for v in ib], "on": [num(v, 2) for v in on], "ve": [num(v, 2) for v in ve],
            "near": num(near, 0), "inside": int(inside), "n": int(ok.sum()), "years": DAILY_YEARS}


def check_corridor(m: pd.DataFrame) -> None:
    miss = [c for c in CORR_COLS if c not in m.columns]
    if miss:
        warn(f"faltan {', '.join(miss)}; se omite el control del corredor")
        return
    c = m[CORR_COLS].loc[START:].dropna()
    ins = (c.iloc[:, 0] >= c.iloc[:, 1] - 1e-9) & (c.iloc[:, 0] <= c.iloc[:, 2] + 1e-9)
    out = [month_key(t) for t in c.index[~ins]]
    print(f"  control corredor mensual: interbancaria dentro en {int(ins.sum())} de {len(c)} meses desde {month_key(START)}; "
          f"fuera: {', '.join(out) if out else 'ninguno'}")


def build_liquidity(m: pd.DataFrame, months: pd.DatetimeIndex, S: dict) -> dict | None:
    """Saldos de inyección (positivos) y esterilización (negativos), en millones de S/.
    Los componentes suman exactamente el total publicado: el residuo va como «otros»."""
    miss = [c for c in LIQ_COLS if c not in m.columns]
    if miss:
        warn(f"faltan saldos de operaciones monetarias ({', '.join(miss)}); se omite el gráfico de liquidez")
        return None
    x = m[LIQ_COLS].reindex(months)
    f0 = lambda c: x[c].fillna(0)  # noqa: E731 (antes de que exista un instrumento, su saldo es 0)
    repos = f0("repo_valores_saldo") + f0("repo_monedas_saldo") + f0("repo_cartera_saldo") + f0("repo_cartera_garantia_estatal_saldo")
    res_iny = x["op_bcrp_sistema_financiero_saldo"] - repos
    val3 = f0("cd_bcrp_saldo") + f0("cdr_bcrp_saldo") + f0("cdv_bcrp_saldo")
    res_val = x["valores_bcrp_saldo"] - val3
    res_dep = x["depositos_intermediarios_bcrp_saldo"] - f0("depositos_overnight_bcrp_saldo") - f0("depositos_intermediarios_otros_bcrp_saldo")
    print(f"  control inyección = repos de valores + monedas + cartera + garantía estatal: dif. máx. {res_iny.abs().max():,.1f} millones")
    if res_iny.abs().max() > 1:
        warn(f"la inyección total no es igual a la suma de los repos (dif. máx. {res_iny.abs().max():,.0f} millones); "
             "la diferencia va como «otras operaciones de inyección»")
    print(f"  control valores del BCRP = CD + CDR + CDV: dif. máx. {res_val.abs().max():,.1f} millones "
          f"({int((res_val.abs() > 1).sum())} meses con diferencia; va como «otros valores»)")
    print(f"  control depósitos de intermediarios = overnight + otros: dif. máx. {res_dep.abs().max():,.1f} millones")
    S["l_rval"] = series_list(x["repo_valores_saldo"], months, 0)
    S["l_rmon"] = series_list(x["repo_monedas_saldo"], months, 0)
    S["l_rcar"] = series_list(x["repo_cartera_saldo"], months, 0)
    S["l_rgar"] = series_list(x["repo_cartera_garantia_estatal_saldo"], months, 0)
    S["l_iotr"] = series_list(res_iny.where(res_iny.abs() > 1), months, 0)
    S["l_cd"] = series_list(-x["cd_bcrp_saldo"], months, 0)
    S["l_cdr"] = series_list(-x["cdr_bcrp_saldo"], months, 0)
    S["l_cdv"] = series_list(-x["cdv_bcrp_saldo"], months, 0)
    S["l_votr"] = series_list(-res_val.where(res_val.abs() > 1), months, 0)
    S["l_don"] = series_list(-x["depositos_overnight_bcrp_saldo"], months, 0)
    S["l_dotr"] = series_list(-x["depositos_intermediarios_otros_bcrp_saldo"], months, 0)
    S["l_iny"] = series_list(x["op_bcrp_sistema_financiero_saldo"], months, 0)
    S["l_est"] = series_list(-(x["valores_bcrp_saldo"] + x["depositos_intermediarios_bcrp_saldo"]), months, 0)
    iny = x["op_bcrp_sistema_financiero_saldo"].dropna()
    est = (x["valores_bcrp_saldo"] + x["depositos_intermediarios_bcrp_saldo"]).dropna()
    gar = x["repo_cartera_garantia_estatal_saldo"].dropna()
    cd = x["cd_bcrp_saldo"].dropna()
    out = {
        "last": month_key(iny.index.max()), "iny_max": num(iny.max(), 0), "iny_max_m": month_key(iny.idxmax()),
        "est_max": num(est.max(), 0), "est_max_m": month_key(est.idxmax()),
        "cd_max": num(cd.max(), 0), "cd_max_m": month_key(cd.idxmax()),
        "otros_val": [month_key(t) for t in res_val.index[res_val.abs() > 1]],
        "otros_iny": bool(res_iny.abs().max() > 1),
    }
    if (gar > 0).any():
        g = gar[gar > 0]
        out.update({"gar_max": num(g.max(), 0), "gar_max_m": month_key(g.idxmax()),
                    "gar_first": month_key(g.index.min()), "gar_last": month_key(g.index.max())})
    eps = []
    for a, b, lab in [("2008-09", "2009-12", "crisis financiera internacional"), ("2013-01", "2016-12", "desdolarización"),
                      ("2020-03", "2021-12", "pandemia")]:
        w = iny.loc[a:b]
        if not w.empty:
            eps.append({"lab": lab, "m": month_key(w.idxmax()), "v": num(w.max(), 0)})
    out["eps"] = eps
    return out


def build_bonds(m: pd.DataFrame, d: pd.DataFrame, months: pd.DatetimeIndex, S: dict) -> dict:
    info = {"bad": []}
    for k, col in TRAMOS.items():
        s = get_col(m, col, "tramo de bonos del Tesoro")
        if s is None:
            continue
        s = s.where(s > 0)
        for t, v in s[s > 30].items():
            info["bad"].append({"k": k, "m": month_key(t), "v": num(v, 2)})
        S[k] = series_list(s.where(s <= 30), months)
    if "ust_10a_diario" in d.columns and not d["ust_10a_diario"].dropna().empty:
        u = d["ust_10a_diario"].dropna()
        grp = u.index.to_period("M").to_timestamp()
        um = u.groupby(grp).mean()
        cnt = u.groupby(grp).size().loc[:months[-1]]
        S["ust10"] = series_list(um, months)
        info["ust_last_d"] = u.loc[:months[-1] + pd.offsets.MonthEnd(0)].index.max().strftime("%Y-%m-%d")
        info["ust_last_m"] = month_key(cnt.index[-1])
        info["ust_last_n"] = int(cnt.iloc[-1])
    else:
        warn("falta el bono del Tesoro de EE. UU. a 10 años (diario); se omite el diferencial")
    return info


def last_info(s: pd.Series | None) -> dict | None:
    if s is None:
        return None
    s = s.dropna()
    if s.empty:
        return None
    return {"v": num(s.iloc[-1], 2), "m": month_key(s.index[-1])}


def build_kpis(m: pd.DataFrame, d: pd.DataFrame, cycles: list[dict], real: pd.Series | None) -> dict:
    """Indicadores del último dato y su cambio desde el mes previo al inicio del ciclo vigente.
    `m` puede traer columnas extra (sbs_<tipo>) agregadas por main()."""
    k: dict = {}
    cur = cycles[-1] if cycles else None
    antes_m = (pd.Timestamp(cur["inicio"] + "-01") - pd.DateOffset(months=1)) if cur else None

    def at(s, ts):
        return num(s.get(ts, np.nan), 2) if ts is not None else None

    r = m["tasa_referencia"].dropna()
    ch = r.diff()
    mv = ch[ch.abs() > 1e-9]
    k["ref"] = {"v": num(r.iloc[-1], 2), "m": month_key(r.index[-1]),
                "last_move": num(mv.iloc[-1], 2) if not mv.empty else None,
                "last_move_m": month_key(mv.index[-1]) if not mv.empty else None}
    prev = [c for c in cycles[:-1] if c["tipo"] != (cur["tipo"] if cur else None)]
    if prev:
        p = prev[-1]
        k["ref"]["peak"] = {"v": p["ref_fin"], "m": p["fin"], "tipo": p["tipo"], "inicio": p["inicio"]}
    if cur:
        k["cycle"] = {"tipo": cur["tipo"], "inicio": cur["inicio"], "antes": month_key(antes_m), "fin": cur["fin"]}
    tiles = [
        ("sbs_corp", "sbs_corporativo"), ("sbs_cons", "sbs_consumo"),
        ("pref", "tasa_preferencial_corp_mn"), ("corp", "tasa_bancos_corporativo_hasta360_mn"),
        ("p30", "tasa_pasiva_plazo_hasta30d_mn"), ("ftipmn", "ftipmn"), ("b10", "bono_soberano_10a_soles"),
        ("dolc", "dolarizacion_credito"), ("cons", "tasa_bancos_consumo_prest_hasta360_mn"),
        ("crmn", "credito_privado_mn_var12m"), ("ib", "tasa_interbancaria_mn"), ("exp", "expectativa_inflacion_12m"),
    ]
    for key, col in tiles:
        if col not in m.columns or m[col].dropna().empty:
            warn(f"indicador {key}: falta {col}")
            continue
        li = last_info(m[col])
        li["antes"] = at(m[col], antes_m)
        k[key] = li
    if real is not None and not real.dropna().empty:
        li = last_info(real)
        li["antes"] = num(real.get(antes_m, np.nan), 2)
        if k["ref"]["m"] > li["m"] and "exp" in k:
            li["ref_now"] = num(k["ref"]["v"] - k["exp"]["v"], 2)
        k["real"] = li
    for key, col in [("ib_d", "tasa_interbancaria_mn_diario"), ("b10_d", "bono_soberano_10a_soles_diario"),
                     ("ref_d", "tasa_referencia_diario")]:
        if col in d.columns and not d[col].dropna().empty:
            s = d[col].dropna()
            k[key] = {"v": num(s.iloc[-1], 2), "f": s.index[-1].strftime("%Y-%m-%d")}
    # Diferencial interbancaria − referencia medido el mismo día.
    if "ib_d" in k and "tasa_referencia_diario" in d.columns:
        rs = d["tasa_referencia_diario"].ffill()
        k["ib_d"]["ref"] = num(rs.get(pd.Timestamp(k["ib_d"]["f"]), np.nan), 2)
    return k


def build_region(months: pd.DatetimeIndex, S: dict) -> dict | None:
    try:
        panel = pd.read_csv(COMPARABLE / "comparable_panel_mensual.csv", encoding="utf-8-sig",
                            usecols=["pais", "fecha", "tasa_politica_tea", "tasa_real_exante"], parse_dates=["fecha"])
        ser = pd.read_csv(COMPARABLE / "comparable_series.csv", encoding="utf-8-sig")
    except Exception as exc:  # noqa: BLE001
        warn(f"no se pudo leer la capa comparable de países ({type(exc).__name__}: {exc}); se omite la región y la Fed")
        return None
    uso = {(r.pais, r.indicador): str(r.uso) for r in ser.itertuples()}
    panel["fecha"] = panel["fecha"].dt.to_period("M").dt.to_timestamp()
    out = []
    for iso, name in REGION:
        g = panel[panel.pais == iso].set_index("fecha").sort_index()
        g = g[~g.index.duplicated(keep="last")]
        if g.empty or g["tasa_politica_tea"].dropna().empty:
            warn(f"región: sin tasa de política de {name}")
            continue
        pol, rl = g["tasa_politica_tea"], g["tasa_real_exante"]
        pl = pol.dropna()
        c = {"iso": iso, "name": name, "pol": series_list(pol, months), "uso_pol": uso.get((iso, "tasa_politica_tea"), ""),
             "pol_last": last_info(pol), "fuente": REGION_SOURCES.get(iso, "")}
        if not rl.dropna().empty:
            c["real"] = series_list(rl, months)
            c["real_last"] = last_info(rl)
            c["uso_real"] = uso.get((iso, "tasa_real_exante"), "")
        w = pl.loc[PEAK_FROM:]
        if not w.empty:
            top = w[w == w.max()]
            c["peak"] = {"v": num(w.max(), 2), "a": month_key(top.index.min()), "b": month_key(top.index.max())}
            c["d_peak"] = num(pl.iloc[-1] - w.max(), 2)
            low = w[w == w.min()]
            c["low"] = {"v": num(w.min(), 2), "a": month_key(low.index.min()), "b": month_key(low.index.max())}
        t12 = pl.index[-1] - pd.DateOffset(months=12)
        if t12 in pl.index:
            c["d12"] = num(pl.iloc[-1] - pl[t12], 2)
            c["v12"] = {"v": num(pl[t12], 2), "m": month_key(t12)}
        out.append(c)
        if iso == "USA":
            S["fed"] = series_list(pol, months)
    if not out:
        return None
    return {"countries": out, "peak_from": PEAK_FROM}


def load_sbs(months: pd.DatetimeIndex, S: dict) -> dict | None:
    """Tasas activas de las operaciones nuevas de la banca múltiple (SBS), por tipo de crédito."""
    try:
        t = pd.read_parquet(SBS_TASAS)
        x = t[(t.subsistema == "banca-multiple") & (t.es_promedio) & (t.subproducto == "total") & (t.moneda == "MN")]
        if x.empty:
            warn("las tasas de la SBS no traen la fila «Promedio» de la banca múltiple; se omiten")
            return None
        if x.duplicated(["periodo", "tipo_credito"]).any():
            warn("SBS: más de un promedio por mes y tipo de crédito; se promedian")
        x = x.assign(fecha=pd.to_datetime(x.periodo.astype(int).astype(str), format="%Y%m"))
        p = x.pivot_table(index="fecha", columns="tipo_credito", values="tasa", observed=True).sort_index()
    except Exception as exc:  # noqa: BLE001
        warn(f"no se pudieron leer las tasas de operaciones nuevas de la SBS ({type(exc).__name__}: {exc}); "
             "la cadena usa solo las tasas del BCRP")
        return None
    out = {}
    for tipo in SBS_TIPOS:
        if tipo not in p.columns or p[tipo].dropna().empty:
            warn(f"SBS: falta la tasa de {tipo}")
            continue
        S[f"sbs_{tipo}"] = series_list(p[tipo], months)
        out[tipo] = month_key(p[tipo].dropna().index.max())
    if not out:
        return None
    print(f"  tasas de operaciones nuevas (SBS, banca múltiple): {len(out)} tipos, "
          f"{month_key(p.index.min())} a {max(out.values())}")
    return {"desde": month_key(p.index.min()), "hasta": max(out.values()), "frame": p}


def build_breaks(m: pd.DataFrame, sbs: dict | None) -> dict:
    """Saltos de JUMP_PP o más en un mes (desde JUMP_FROM): posibles quiebres de serie, sin causa documentada."""
    cand = {"pym": m.get("tasa_bancos_pyme_hasta360_mn"), "cons": m.get("tasa_bancos_consumo_prest_hasta360_mn")}
    if sbs:
        for tipo in SBS_TIPOS:
            if tipo in sbs["frame"].columns:
                cand[f"sbs_{tipo}"] = sbs["frame"][tipo]
    out = {}
    for k, s in cand.items():
        if s is None:
            continue
        s = s.dropna()
        dd = s.diff().loc[JUMP_FROM:]
        js = [{"m": month_key(t), "a": num(s.shift(1)[t], 1), "b": num(s[t], 1)} for t in dd.index[dd.abs() >= JUMP_PP]]
        if js:
            out[k] = js
            print(f"  posible quiebre de serie en {k}: " + ", ".join(f"{j['m']} ({j['a']} → {j['b']})" for j in js))
    return out


def build_targets(months: pd.DatetimeIndex, S: dict) -> None:
    lo, hi = [None] * len(months), [None] * len(months)
    for t in INFLATION_TARGETS:
        a = pd.Timestamp(t["desde"] + "-01")
        b = pd.Timestamp(t["hasta"] + "-01") if t["hasta"] else months.max()
        for i, ts in enumerate(months):
            if a <= ts <= b:
                lo[i], hi[i] = t["lo"], t["hi"]
    S["meta_lo"], S["meta_hi"] = lo, hi


def build_edu(m: pd.DataFrame) -> dict:
    """Cifras de la pestaña «Aprende» que salen de los datos."""
    out = {}
    r = m["tasa_referencia"].dropna()
    out["ref_first"] = {"v": num(r.iloc[0], 2), "m": month_key(r.index[0])}
    hi = r[r == r.max()]
    out["ref_max"] = {"v": num(r.max(), 2), "a": month_key(hi.index.min()), "b": month_key(hi.index.max())}
    lo = r[r == r.min()]
    out["ref_min"] = {"v": num(r.min(), 2), "a": month_key(lo.index.min()), "b": month_key(lo.index.max())}
    out["n_moves"] = int((r.diff().abs() > 1e-9).sum())
    for key, col in [("dolc", "dolarizacion_credito"), ("doll", "dolarizacion_liquidez")]:
        if col in m.columns:
            s = m[col].dropna()
            base = pd.Timestamp("2000-12-01")
            if base in s.index:
                out[key] = {"v0": num(s[base], 1), "m0": "2000-12", "v": num(s.iloc[-1], 1), "m": month_key(s.index[-1])}
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    m = load_panel("mensual")
    d = load_panel("diaria")
    if "tasa_referencia" not in m.columns:
        raise ValueError("Falta la tasa de referencia en el panel mensual: no se puede generar el tablero")

    used = [c for c in MONTHLY.values() if c in m.columns] + [c for c in TRAMOS.values() if c in m.columns]
    last = max(m[c].dropna().index.max() for c in used if not m[c].dropna().empty)
    months = pd.date_range(START, last, freq="MS")
    print(f"  meses: {month_key(months[0])} a {month_key(months[-1])} ({len(months)})")

    S: dict[str, list | None] = {}
    for key, col in MONTHLY.items():
        s = get_col(m, col, key)
        if s is not None:
            S[key] = series_list(s, months, 3 if key == "tc" else 2)
    real = None
    if "ref" in S and "exp" in S:
        real = (m["tasa_referencia"] - m["expectativa_inflacion_12m"]).dropna()
        S["real"] = series_list(real, months)
    if "corp" in S and "p30" in S:
        S["mrgc"] = series_list(m["tasa_bancos_corporativo_hasta360_mn"] - m["tasa_pasiva_plazo_hasta30d_mn"], months)
    build_targets(months, S)
    check_corridor(m)

    analysis = load_analysis(m, d)
    if analysis and analysis.get("ciclos"):
        cycles = analysis["ciclos"]
        print(f"  ciclos: {len(cycles)} (del módulo de análisis)")
    else:
        cycles = clean(detect_cycles(m["tasa_referencia"]))
        print(f"  ciclos: {len(cycles)} (regla del módulo de análisis, sin el resto del análisis)")

    sbs = load_sbs(months, S)
    liq = build_liquidity(m, months, S)
    bonds = build_bonds(m, d, months, S)
    if "b10" in S and "ust10" in S:
        u = d["ust_10a_diario"].dropna()
        um = u.groupby(u.index.to_period("M").to_timestamp()).mean()
        S["sp10"] = series_list(m["bono_soberano_10a_soles"] - um, months)
    daily = build_daily(d, m)
    region = build_region(months, S)
    mk = m.copy()
    if sbs:
        for tipo in SBS_TIPOS:
            if tipo in sbs["frame"].columns:
                mk[f"sbs_{tipo}"] = sbs["frame"][tipo].reindex(mk.index)
    kpi = build_kpis(mk, d, cycles, real)

    S = {k: v for k, v in S.items() if v is not None and any(x is not None for x in v)}

    used_cols = set(used) | set(d.columns) | set(LIQ_COLS)
    print("  último dato por bloque:")
    for name, cols in BLOCKS:
        ls = []
        for c in cols:
            src = m if c in m.columns else d if c in d.columns else None
            if src is not None and not src[c].dropna().empty:
                ls.append(src[c].dropna().index.max())
        if ls:
            print(f"    {name}: {max(ls).strftime('%Y-%m-%d') if any(t.day > 1 for t in ls) else month_key(max(ls))}")
        else:
            warn(f"bloque sin datos: {name}")
    if sbs:
        print(f"    Tasas de operaciones nuevas (SBS): {sbs['hasta']}")

    params = analysis_params()
    params.update({"daily_years": DAILY_YEARS, "jump_pp": JUMP_PP, "jump_from": JUMP_FROM, "live": LIVE_MONTHS,
                   "peak_from": PEAK_FROM, "risk": [], "contrast": CONTRAST_NC})
    nc = {**{col: key for key, col in MONTHLY.items() if key in S}, **{k: k for k in S if k.startswith("sbs_")}}
    params["risk"] = sorted({nc.get(c, c) for c in RISK_NC})
    data = {
        "generado": dt.date.today().isoformat(), "start": month_key(months[0]), "hasta": month_key(months[-1]),
        "S": S, "cycles": cycles, "kpi": kpi, "daily": daily, "liq": liq, "bonds": bonds, "region": region,
        "A": analysis, "neutral": NEUTRAL_RATE, "causes": CYCLE_CAUSES, "codes": build_codes(used_cols),
        "edu": build_edu(m), "breaks": build_breaks(m, sbs), "params": params,
        "sbs": {"desde": sbs["desde"], "hasta": sbs["hasta"]} if sbs else None,
        "nc": nc,  # nombre_corto del panel -> clave corta de S (el módulo de análisis usa nombre_corto)
    }
    data = clean(data)

    html = TEMPLATE.read_text(encoding="utf-8")
    if PLACEHOLDER not in html:
        raise ValueError(f"La plantilla no tiene el marcador {PLACEHOLDER}")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html.replace(PLACEHOLDER, payload), encoding="utf-8")
    print(f"  {OUT.relative_to(PROJECT_DIR)}  ({OUT.stat().st_size / 1024:.0f} KB; JSON {len(payload) / 1024:.0f} KB; "
          f"{len(S)} series mensuales; diaria: {len(daily['f']) if daily else 0} días; "
          f"región: {len(region['countries']) if region else 0} países; análisis: {'sí' if analysis else 'omitido'})")
    OUT_ARTIFACT.write_text(artifact_version(OUT.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"  {OUT_ARTIFACT.relative_to(PROJECT_DIR)}  (versión para publicar en claude.ai)")
    if WARNINGS:
        print(f"  {len(WARNINGS)} aviso(s): bloques omitidos o con datos parciales (ver arriba)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
