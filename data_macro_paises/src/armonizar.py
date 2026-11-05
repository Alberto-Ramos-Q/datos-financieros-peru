"""Capa comparable: transforma las series oficiales en indicadores homogéneos entre países.

Lee `data/processed/macro_observaciones.parquet` (salida de consolidar.py) y aplica las
transformaciones recomendadas en `docs/comparabilidad/` para obtener indicadores con la misma
definición, unidad y base en todos los países:

- variaciones a/a desde el nivel ORIGINAL (no desde el desestacionalizado);
- índices rebasados a un año común (BASE_YEAR = 100), lo que también elimina el factor 4 de los
  PBI trimestrales a tasa anual (ARG, MEX) y las diferencias de moneda y de año base;
- conversión a USD (flujos con el tipo de cambio promedio y saldos con el de fin de periodo;
  España cotiza en USD por EUR y se invierte);
- tasas en TEA, punto medio del rango del FOMC, MRO del BCE antes de 2008-09, EONIA empalmado;
- desempleo a trimestre calendario (trimestres móviles re-fechados, meses sueltos promediados);
- salario mínimo mensual (MEX por día ×30,4; ESP en 14 pagas ×14/12) y en USD;
- crédito a tipo de cambio constante y en términos reales;
- ratios sobre el PBI (cuenta corriente, crédito, dinero, reservas, apertura);
- desviación de la inflación respecto de la meta (config/comparable/metas_inflacion.csv);
- variables de régimen y quiebres (config/comparable/regimenes.csv) y cortes de muestra
  (config/comparable/cortes_muestra.csv).

Cada par país × indicador lleva su método, sus insumos, la cobertura y el grado de
comparabilidad de la fuente (docs/comparabilidad/matriz_comparabilidad.csv).

Salidas en `data/processed/comparable/`:
    comparable_observaciones.parquet / .csv   largo: pais, indicador, frecuencia, fecha, valor, regimen
    comparable_series.csv                     una fila por país × indicador: método, insumos, cobertura, grados, uso
    comparable_catalogo.csv                   definición de cada indicador comparable
    comparable_cobertura.csv                  indicador × país: uso y rango de fechas
    comparable_panel_<frecuencia>.csv         panel país × fecha (excluye lo 'no_comparable')
    comparable_validacion.csv                 pruebas de consistencia

Uso:
    python armonizar.py
"""
from __future__ import annotations

import datetime as dt
import fnmatch
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.tseries.offsets import BDay

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun  # noqa: E402

PROCESSED_DIR = comun.PROJECT_DIR / "data" / "processed"
OUT_DIR = PROCESSED_DIR / "comparable"
COMP_CONFIG = comun.CONFIG_DIR / "comparable"
MATRIX_CSV = comun.PROJECT_DIR / "docs" / "comparabilidad" / "matriz_comparabilidad.csv"

BASE_YEAR = 2019
# Países cuya moneda es el dólar (o cuyas series ya vienen en USD): no se convierten.
USD_COUNTRIES = {"ECU", "PAN", "USA"}
# Publican el tipo de cambio del día t con las operaciones de t−1 (dólar observado, TRM).
TC_LAGGED = {"CHL", "COL"}

log = comun.log

# ---------------------------------------------------------------------------------------
# Catálogo de indicadores comparables
#   base: indicador común cuyo grado (docs/comparabilidad) hereda; tipo: nivel | variacion
# ---------------------------------------------------------------------------------------
CATALOG = [
    # actividad
    ("pbi_real_indice", "actividad", "trimestral", f"índice {BASE_YEAR}=100", "pbi_real_trim", "nivel",
     "PBI real sin desestacionalizar, rebasado (elimina moneda, año base y anualización)"),
    ("pbi_real_var_a", "actividad", "trimestral", "%", "pbi_real_var12m_trim", "variacion",
     "PBI real, variación % a/a calculada desde el nivel original"),
    ("pbi_desest_indice", "actividad", "trimestral", f"índice {BASE_YEAR}=100", "pbi_desest_trim", "nivel",
     "PBI real desestacionalizado, rebasado"),
    ("pbi_desest_var_t", "actividad", "trimestral", "%", "pbi_desest_trim", "variacion",
     "PBI real desestacionalizado, variación % t/t SIN anualizar"),
    ("actividad_mensual_indice", "actividad", "mensual", f"índice {BASE_YEAR}=100", "actividad_mensual_indice", "nivel",
     "Indicador mensual de actividad, rebasado (ver cobertura: conciliado / proxy / producción industrial)"),
    ("actividad_mensual_var_a", "actividad", "mensual", "%", "actividad_mensual_var12m", "variacion",
     "Indicador mensual de actividad, variación % a/a calculada desde el índice original"),
    ("pbi_nominal_usd", "actividad", "anual", "millones USD", "pbi_nominal_anual", "nivel",
     "PBI nominal anual en USD (tipo de cambio promedio del año)"),
    # precios
    ("ipc_indice", "precios", "mensual", f"índice {BASE_YEAR}=100", "ipc_indice", "nivel",
     "IPC rebasado"),
    ("inflacion_mensual", "precios", "mensual", "%", "inflacion_mensual", "variacion",
     "Inflación mensual publicada (serie original en todos los países)"),
    ("inflacion_12m", "precios", "mensual", "%", "inflacion_12m", "variacion",
     "Inflación 12m publicada: índice oficial de la meta (PER Lima, PRY Asunción)"),
    ("inflacion_12m_nacional", "precios", "mensual", "%", "inflacion_12m", "variacion",
     "Inflación 12m con cobertura nacional (PER: IPC nacional del INEI; excluye PRY)"),
    ("inflacion_subyacente_12m", "precios", "mensual", "%", "inflacion_subyacente_12m", "variacion",
     "Subyacente oficial de cada país (definiciones distintas; BOL: núcleo del BCB)"),
    ("inflacion_sae_12m", "precios", "mensual", "%", "inflacion_subyacente_12m", "variacion",
     "Inflación sin alimentos y energía, solo donde existe esa definición oficial"),
    ("expectativa_inflacion_12m", "precios", "mensual", "%", "expectativa_inflacion_12m", "variacion",
     "Expectativa de inflación a 12 meses de la encuesta oficial"),
    ("meta_inflacion", "precios", "mensual", "%", "inflacion_12m", "variacion",
     "Centro de la meta de inflación vigente (o punto medio del rango)"),
    ("meta_inflacion_inferior", "precios", "mensual", "%", "inflacion_12m", "variacion", "Límite inferior de la meta"),
    ("meta_inflacion_superior", "precios", "mensual", "%", "inflacion_12m", "variacion", "Límite superior de la meta"),
    ("desvio_meta_pp", "precios", "mensual", "pp", "inflacion_12m", "variacion",
     "Inflación 12m menos el centro de la meta"),
    ("fuera_de_rango_meta", "precios", "mensual", "0/1", "inflacion_12m", "variacion",
     "1 si la inflación 12m está fuera del rango de la meta"),
    # monetario
    ("tasa_politica_tea", "monetario", "mensual", "% TEA", "tasa_politica", "nivel",
     "Tasa de política fin de mes en TEA (FOMC punto medio; BCE MRO hasta 2008-09 y DFR después)"),
    ("tasa_interbancaria_tea", "monetario", "mensual", "% TEA", "tasa_interbancaria", "nivel",
     "Tasa interbancaria/overnight en TEA (ESP: €STR con EONIA empalmado)"),
    ("tasa_real_exante", "monetario", "mensual", "%", "expectativa_inflacion_12m", "nivel",
     "Tasa de política real ex-ante: (1+i)/(1+πᵉ)−1"),
    ("diferencial_fed_pp", "monetario", "mensual", "pp", "tasa_politica", "nivel",
     "Tasa de política (TEA) menos la de la Fed (TEA)"),
    ("tasa_activa_promedio", "monetario", "mensual", "% anual", "tasa_activa_promedio", "nivel",
     "Tasa activa publicada (conceptos distintos: solo dinámica dentro del país)"),
    ("tasa_pasiva_promedio", "monetario", "mensual", "% anual", "tasa_pasiva_promedio", "nivel",
     "Tasa pasiva publicada (conceptos distintos: solo dinámica dentro del país)"),
    ("credito_privado_usd", "monetario", "mensual", "millones USD", "credito_privado", "nivel",
     "Crédito al sector privado, saldo en USD (tipo de cambio de fin de mes)"),
    ("credito_var_a", "monetario", "mensual", "%", "credito_privado", "variacion",
     "Crédito, variación % a/a nominal a tipo de cambio constante cuando hay componente en ME"),
    ("credito_real_var_a", "monetario", "mensual", "%", "credito_privado", "variacion",
     "Crédito, variación % a/a real (deflactado con el IPC), a tipo de cambio constante cuando aplica"),
    ("credito_pct_pbi", "monetario", "anual", "% PBI", "credito_privado", "nivel",
     "Crédito al sector privado de diciembre sobre el PBI nominal del año"),
    ("dinero_amplio_var_a", "monetario", "mensual", "%", "m2", "variacion",
     "Dinero amplio (M3 si M2 es estrecho), variación % a/a"),
    ("dinero_amplio_pct_pbi", "monetario", "anual", "% PBI", "m2", "nivel",
     "Dinero amplio de diciembre sobre el PBI nominal"),
    # externo
    ("tc_ml_por_usd", "externo", "mensual", "moneda local por USD", "tc_usd_promedio", "nivel",
     "Tipo de cambio promedio del mes, moneda local por USD (ESP: EUR por USD; BOL: medio compra/venta)"),
    ("tc_ml_por_usd_fin", "externo", "mensual", "moneda local por USD", "tc_usd_diario", "nivel",
     "Tipo de cambio de fin de mes (último día hábil; CHL y COL re-fechados a t−1)"),
    ("depreciacion_var_a", "externo", "mensual", "%", "tc_usd_promedio", "variacion",
     "Depreciación a/a de la moneda local (+ = depreciación)"),
    ("volatilidad_tc", "externo", "mensual", "% anualizada", "tc_usd_diario", "variacion",
     "Desvío estándar de los retornos logarítmicos diarios del mes ×√252"),
    ("reservas_usd", "externo", "mensual", "millones USD", "reservas_internacionales", "nivel",
     "Reservas internacionales publicadas en USD (brutas o netas según el país; USA trimestral)"),
    ("reservas_brutas_usd", "externo", "mensual", "millones USD", "reservas_internacionales", "nivel",
     "Reservas internacionales BRUTAS en USD (solo donde existe la serie bruta)"),
    ("reservas_meses_importacion", "externo", "mensual", "meses", "reservas_internacionales", "nivel",
     "Reservas (brutas si existen) / promedio mensual de importaciones de los últimos 12 meses"),
    ("reservas_pct_pbi", "externo", "anual", "% PBI", "reservas_internacionales", "nivel",
     "Reservas de fin de año sobre el PBI en USD"),
    ("exportaciones_usd", "externo", "mensual", "millones USD", "exportaciones", "nivel",
     "Exportaciones de bienes (aduana) en USD"),
    ("importaciones_usd", "externo", "mensual", "millones USD", "importaciones", "nivel",
     "Importaciones de bienes (aduana) en USD (FOB o CIF según el país)"),
    ("balanza_comercial_usd", "externo", "mensual", "millones USD", "balanza_comercial", "nivel",
     "Exportaciones − importaciones (aduana)"),
    ("exportaciones_var_a_12m", "externo", "mensual", "%", "exportaciones", "variacion",
     "Variación % a/a de las exportaciones acumuladas en 12 meses"),
    ("importaciones_var_a_12m", "externo", "mensual", "%", "importaciones", "variacion",
     "Variación % a/a de las importaciones acumuladas en 12 meses"),
    ("exportaciones_bienes_trim_usd", "externo", "trimestral", "millones USD", "exportaciones", "nivel",
     "Exportaciones de bienes del trimestre: balanza de pagos si existe (incluye zonas francas), si no aduana"),
    ("importaciones_bienes_trim_usd", "externo", "trimestral", "millones USD", "importaciones", "nivel",
     "Importaciones de bienes del trimestre: balanza de pagos FOB si existe, si no aduana"),
    ("balanza_bienes_trim_usd", "externo", "trimestral", "millones USD", "balanza_comercial", "nivel",
     "Exportaciones − importaciones de bienes del trimestre"),
    ("apertura_comercial_pct_pbi", "externo", "anual", "% PBI", "exportaciones", "nivel",
     "(Exportaciones + importaciones de bienes) / PBI en USD"),
    ("cuenta_corriente_usd", "externo", "trimestral", "millones USD", "cuenta_corriente", "nivel",
     "Saldo en cuenta corriente del trimestre en USD"),
    ("cuenta_corriente_pct_pbi", "externo", "anual", "% PBI", "cuenta_corriente", "nivel",
     "Cuenta corriente del año (suma de 4 trimestres) / PBI en USD"),
    # fiscal
    ("resultado_fiscal_pct_pbi", "fiscal", "anual", "% PBI", "resultado_fiscal_pct_pbi", "nivel",
     "Resultado fiscal global anual (+ superávit); ver cobertura institucional"),
    ("resultado_fiscal_var_pp", "fiscal", "anual", "pp", "resultado_fiscal_pct_pbi", "variacion",
     "Cambio anual del resultado fiscal en pp del PBI"),
    ("deuda_publica_pct_pbi", "fiscal", "anual", "% PBI", "deuda_publica_pct_pbi", "nivel",
     "Deuda pública de fin de año; ver cobertura (bruta/neta, institucional)"),
    ("deuda_publica_var_pp", "fiscal", "anual", "pp", "deuda_publica_pct_pbi", "variacion",
     "Cambio anual de la deuda pública en pp del PBI"),
    # laboral
    ("desempleo_trim", "laboral", "trimestral", "%", "desempleo", "nivel",
     "Tasa de desempleo del trimestre calendario, sin desestacionalizar"),
    ("desempleo_anual", "laboral", "anual", "%", "desempleo", "nivel",
     "Tasa de desempleo promedio del año"),
    ("desempleo_var_a_pp", "laboral", "trimestral", "pp", "desempleo", "variacion",
     "Cambio a/a de la tasa de desempleo trimestral, en pp"),
    ("salario_minimo_mensual_ml", "laboral", "mensual", "moneda local por mes", "salario_minimo", "nivel",
     "Salario mínimo mensual (MEX diario ×30,4; ESP 14 pagas ×14/12)"),
    ("salario_minimo_usd", "laboral", "mensual", "USD por mes", "salario_minimo", "nivel",
     "Salario mínimo mensual en USD (tipo de cambio promedio del mes)"),
    ("salario_minimo_real_indice", "laboral", "mensual", f"índice {BASE_YEAR}=100", "salario_minimo", "variacion",
     "Salario mínimo real (deflactado con el IPC), rebasado"),
    ("salario_minimo_real_var_a", "laboral", "mensual", "%", "salario_minimo", "variacion",
     "Salario mínimo real, variación % a/a"),
]
CATALOG_DF = pd.DataFrame(CATALOG, columns=["indicador", "bloque", "frecuencia", "unidad",
                                            "base_comun", "tipo", "descripcion"])
UNITS = dict(zip(CATALOG_DF.indicador, CATALOG_DF.unidad))
USO = {"A": "comparable", "B": "comparable_con_ajuste", "C": "solo_tendencias",
       "D": "no_comparable", "NA": "sin_grado", "": "sin_grado"}


# ---------------------------------------------------------------------------------------
# Datos de entrada
# ---------------------------------------------------------------------------------------
class Store:
    """Acceso a las series de `macro_observaciones` por (país, nombre_corto)."""

    def __init__(self, obs: pd.DataFrame):
        obs = obs.sort_values("fecha")
        self.series: dict[tuple[str, str], pd.Series] = {}
        self.units: dict[tuple[str, str], str] = {}
        for (p, n), g in obs.groupby(["pais", "nombre_corto"]):
            s = g.set_index("fecha")["valor"].astype(float)
            self.series[(p, n)] = s[~s.index.duplicated(keep="last")]
            self.units[(p, n)] = str(g["unidad"].iloc[0])
        self.common = {(r.pais, r.indicador_comun): r.nombre_corto
                       for r in obs[["pais", "nombre_corto", "indicador_comun"]].drop_duplicates().itertuples()
                       if r.indicador_comun}
        self.paises = sorted(obs["pais"].unique())

    def get(self, pais: str, nombre: str | None) -> pd.Series | None:
        if nombre is None:
            return None
        s = self.series.get((pais, nombre))
        return None if s is None or s.empty else s.copy()

    def com(self, pais: str, indicador: str) -> pd.Series | None:
        return self.get(pais, self.common.get((pais, indicador)))

    def com_name(self, pais: str, indicador: str) -> str | None:
        return self.common.get((pais, indicador))

    def unit(self, pais: str, nombre: str | None) -> str:
        return self.units.get((pais, nombre), "")


class Output:
    def __init__(self):
        self.parts: list[pd.DataFrame] = []
        self.meta: list[dict] = []

    def add(self, pais: str, indicador: str, s: pd.Series | None, metodo: str, insumos: str,
            frecuencia: str | None = None, cobertura: str = "", grado: tuple[str, str] | None = None):
        if s is None:
            return
        s = s.replace([np.inf, -np.inf], np.nan).dropna()
        if s.empty:
            return
        freq = frecuencia or CATALOG_DF.set_index("indicador").at[indicador, "frecuencia"]
        self.parts.append(pd.DataFrame({"pais": pais, "indicador": indicador, "frecuencia": freq,
                                        "fecha": pd.to_datetime(s.index), "valor": s.values}))
        self.meta.append({"pais": pais, "indicador": indicador, "frecuencia": freq, "metodo": metodo,
                          "insumos": insumos, "cobertura": cobertura,
                          "grado_override": "/".join(grado) if grado else ""})


# ---------------------------------------------------------------------------------------
# Transformaciones básicas
# ---------------------------------------------------------------------------------------
def lag_years(s: pd.Series, years: int = 1) -> pd.Series:
    lagged = s.copy()
    lagged.index = lagged.index + pd.DateOffset(years=years)
    return lagged.reindex(s.index)


def yoy(s: pd.Series) -> pd.Series:
    """Variación % respecto del mismo periodo del año anterior (robusta a huecos)."""
    return ((s / lag_years(s)) - 1) * 100


def diff_yoy(s: pd.Series) -> pd.Series:
    return s - lag_years(s)


def rebase(s: pd.Series | None, n_expected: int) -> pd.Series | None:
    if s is None:
        return None
    base = s[s.index.year == BASE_YEAR]
    if len(base) < n_expected:
        return None
    return s / base.mean() * 100


def monthly_full(s: pd.Series) -> pd.Series:
    return s.reindex(pd.date_range(s.index.min(), s.index.max(), freq="MS"))


def roll12_sum(s: pd.Series) -> pd.Series:
    return monthly_full(s).rolling(12, min_periods=12).sum().dropna()


def aggregate(s: pd.Series, period: str, how: str, min_n: int) -> pd.Series:
    """Agrega a trimestre ('Q') o año ('Y'), exigiendo min_n observaciones; fecha = inicio."""
    if s is None or s.empty:
        return pd.Series(dtype=float)
    g = s.groupby(s.index.to_period(period))
    agg = getattr(g, how)()
    agg = agg[g.count() >= min_n]
    agg.index = agg.index.to_timestamp(how="start")
    return agg


def last_of_period(s: pd.Series, months: tuple[int, ...]) -> pd.Series:
    """Toma los meses indicados (p. ej. 12 = diciembre) y re-fecha al inicio del periodo."""
    sel = s[s.index.month.isin(months)].copy()
    if months == (12,):
        sel.index = pd.to_datetime([dt.date(d.year, 1, 1) for d in sel.index])
    else:
        sel.index = sel.index.to_period("Q").to_timestamp(how="start")
    return sel


def tea_act360(r: pd.Series) -> pd.Series:
    """Tasa nominal anual act/360 con capitalización diaria → TEA."""
    return ((1 + r / 100 / 360) ** 365 - 1) * 100


def tea_tna365(r: pd.Series, days: int) -> pd.Series:
    """TNA (base 365) a plazo `days` → TEA."""
    return ((1 + r / 100 * days / 365) ** (365 / days) - 1) * 100


# ---------------------------------------------------------------------------------------
# Tipo de cambio y conversión a USD
# ---------------------------------------------------------------------------------------
class FX:
    def __init__(self, st: Store, today: dt.date):
        self.st = st
        self.current_month = pd.Timestamp(today.year, today.month, 1)
        self._prom: dict[str, pd.Series | None] = {}
        self._daily: dict[str, pd.Series | None] = {}

    def prom_m(self, p: str) -> pd.Series | None:
        """Moneda local por USD, promedio del mes."""
        if p in self._prom:
            return self._prom[p]
        s = None if p in USD_COUNTRIES else self.st.com(p, "tc_usd_promedio")
        if s is not None and p == "BOL":
            venta = self.st.get(p, "tc_usd_venta_promedio")
            if venta is not None:
                s = ((s + venta.reindex(s.index)) / 2).fillna(s)
        if s is not None and p == "ESP":
            s = 1 / s                       # USD por EUR → EUR por USD
        self._prom[p] = s
        return s

    def daily(self, p: str) -> pd.Series | None:
        if p in self._daily:
            return self._daily[p]
        s = None if p in USD_COUNTRIES else self.st.com(p, "tc_usd_diario")
        if s is not None:
            if p == "BOL":
                venta = self.st.get(p, "tc_usd_venta_diario")
                if venta is not None:
                    s = ((s + venta.reindex(s.index)) / 2).fillna(s)
            s = s[s.index.dayofweek < 5]    # fines de semana con valor repetido (COL, BOL)
            if p in TC_LAGGED:
                s.index = s.index - BDay(1)
            if p == "ESP":
                s = 1 / s
            s = s[~s.index.duplicated(keep="last")].sort_index()
        self._daily[p] = s
        return s

    def fin_m(self, p: str) -> pd.Series | None:
        """Moneda local por USD, último día hábil del mes (mes en curso excluido)."""
        d = self.daily(p)
        if d is None:
            return self.prom_m(p)
        m = d.groupby(d.index.to_period("M")).last()
        m.index = m.index.to_timestamp(how="start")
        return m[m.index < self.current_month]

    def to_usd(self, p: str, s: pd.Series, unidad: str, kind: str, freq: str) -> pd.Series | None:
        """Convierte una serie en moneda local (o EUR) a USD. kind: flujo | saldo."""
        if p in USD_COUNTRIES or "USD" in unidad or "US$" in unidad:
            return s
        if kind == "flujo":
            tc = self.prom_m(p)
            if tc is None:
                return None
            if freq == "trimestral":
                tc = aggregate(tc, "Q", "mean", 3)
            elif freq == "anual":
                tc = aggregate(tc, "Y", "mean", 12)
        else:
            tc = self.fin_m(p)
            if tc is None:
                return None
            if freq == "trimestral":
                tc = last_of_period(tc, (3, 6, 9, 12))
            elif freq == "anual":
                tc = last_of_period(tc, (12,))
        return (s / tc.reindex(s.index)).dropna()


def cobertura_table() -> dict[tuple[str, str], str]:
    df = pd.read_csv(COMP_CONFIG / "cobertura.csv", dtype=str, encoding="utf-8-sig", keep_default_na=False)
    return {(r.grupo, r.pais): r.cobertura + (f" ({r.nota})" if r.nota else "") for r in df.itertuples()}


# ---------------------------------------------------------------------------------------
# Constructores por bloque
# ---------------------------------------------------------------------------------------
def build_actividad(st: Store, fx: FX, out: Output, cob: dict) -> None:
    for p in st.paises:
        lvl = st.com(p, "pbi_real_trim")
        if lvl is not None:
            out.add(p, "pbi_real_indice", rebase(lvl, 4),
                    f"rebase {BASE_YEAR}=100 del nivel original", "pbi_real_trim")
            g = yoy(lvl).dropna()
            metodo = "a/a desde el nivel original"
            pub = st.com(p, "pbi_real_var12m_trim")
            if pub is not None and not g.empty and pub.index.min() < g.index.min():
                metodo += f"; antes de {g.index.min():%Y-%m} se usa la variación publicada"
                g = pd.concat([pub[pub.index < g.index.min()], g])
            out.add(p, "pbi_real_var_a", g, metodo, "pbi_real_trim, pbi_real_var12m_trim")

        d, src = st.com(p, "pbi_desest_trim"), "pbi_desest_trim"
        if d is not None:
            q = ((d / d.shift(1)) - 1) * 100
            q = q[(d.index.to_series().diff().dt.days.between(80, 100)).values]
            out.add(p, "pbi_desest_indice", rebase(d, 4), f"rebase {BASE_YEAR}=100", src)
            out.add(p, "pbi_desest_var_t", q, "t/t sin anualizar desde el nivel", src)
        elif p == "PER" and st.get(p, "pbi_desest_var_trim") is not None:
            v = st.get(p, "pbi_desest_var_trim")
            q = ((1 + v / 100) ** 0.25 - 1) * 100
            chained = 100 * (1 + q / 100).cumprod()
            out.add(p, "pbi_desest_indice", rebase(chained, 4),
                    "nivel encadenado desde la variación t/t anualizada (PN37939AQ)", "pbi_desest_var_trim",
                    grado=("B", "A"))
            out.add(p, "pbi_desest_var_t", q, "t/t anualizada convertida a t/t: (1+g)^(1/4)−1",
                    "pbi_desest_var_trim", grado=("B", "A"))

        m = st.com(p, "actividad_mensual_indice")
        if m is not None:
            c = cob.get(("actividad_mensual", p), "")
            out.add(p, "actividad_mensual_indice", rebase(m, 12), f"rebase {BASE_YEAR}=100",
                    "actividad_mensual_indice", cobertura=c)
            out.add(p, "actividad_mensual_var_a", yoy(m), "a/a desde el índice original",
                    "actividad_mensual_indice", cobertura=c)

        n = st.com(p, "pbi_nominal_anual")
        if n is not None:
            u = fx.to_usd(p, n, st.unit(p, "pbi_nominal_anual"), "flujo", "anual")
            out.add(p, "pbi_nominal_usd", u, "PBI nominal / tipo de cambio promedio anual",
                    "pbi_nominal_anual, tc_usd_promedio")


def load_targets() -> pd.DataFrame | None:
    path = COMP_CONFIG / "metas_inflacion.csv"
    if not path.exists():
        log.warning("Falta %s: no se calculan metas ni desvíos", path.name)
        return None
    return pd.read_csv(path, dtype=str, encoding="utf-8-sig", keep_default_na=False)


def targets_monthly(tg: pd.DataFrame, pais: str, until: pd.Timestamp) -> pd.DataFrame:
    rows = []
    for r in tg[tg.pais == pais].itertuples():
        if r.tipo == "sin_meta" or not r.desde:
            continue
        lo = pd.to_numeric(r.rango_inferior, errors="coerce")
        hi = pd.to_numeric(r.rango_superior, errors="coerce")
        ce = pd.to_numeric(r.meta_centro, errors="coerce")
        if pd.isna(ce) and not (pd.isna(lo) or pd.isna(hi)):
            ce = (lo + hi) / 2
        start = pd.Timestamp(r.desde).to_period("M").to_timestamp()
        end = pd.Timestamp(r.hasta).to_period("M").to_timestamp() if r.hasta else until
        for d in pd.date_range(start, end, freq="MS"):
            rows.append({"fecha": d, "centro": ce, "inferior": lo, "superior": hi,
                         "coincide": r.coincide_con_repositorio})
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).drop_duplicates("fecha", keep="last").set_index("fecha").sort_index()


SAE_NOTES = {
    "ESP": "INE: general sin alimentos, bebidas, tabaco ni productos energéticos (no existe uno sin solo alimentos y energía)",
    "BRA": "BCB: núcleo IPCA EX-FE, acumulado 12 meses",
    "CHL": "IPC SAE del INE; 12m calculada desde el índice base 2023",
    "COL": "DANE: total menos energéticos y alimentos",
    "PRY": "BCP: IPC sin alimentos, combustibles ni servicios tarifados",
}


def build_precios(st: Store, fx: FX, out: Output, cob: dict, today: dt.date) -> None:
    tg = load_targets()
    for p in st.paises:
        c = cob.get(("ipc", p), "")
        ipc = st.com(p, "ipc_indice")
        out.add(p, "ipc_indice", rebase(ipc, 12), f"rebase {BASE_YEAR}=100", "ipc_indice", cobertura=c)
        out.add(p, "inflacion_mensual", st.com(p, "inflacion_mensual"), "publicada", "inflacion_mensual",
                cobertura=c)
        inf12 = st.com(p, "inflacion_12m")
        out.add(p, "inflacion_12m", inf12, "publicada", "inflacion_12m", cobertura=c)

        if p == "PER" and st.get(p, "inflacion_nacional_12m") is not None:
            out.add(p, "inflacion_12m_nacional", st.get(p, "inflacion_nacional_12m"),
                    "IPC nacional del INEI", "inflacion_nacional_12m", cobertura="nacional",
                    grado=("A", "A"))
        elif c.startswith(("nacional", "urbano")):
            out.add(p, "inflacion_12m_nacional", inf12, "publicada (cobertura nacional)", "inflacion_12m",
                    cobertura=c)

        if p == "BOL" and st.get(p, "inflacion_nucleo_12m") is not None:
            out.add(p, "inflacion_subyacente_12m", st.get(p, "inflacion_nucleo_12m"),
                    "núcleo del BCB (la subyacente del INE casi no filtra)", "inflacion_nucleo_12m")
        else:
            out.add(p, "inflacion_subyacente_12m", st.com(p, "inflacion_subyacente_12m"), "publicada",
                    "inflacion_subyacente_12m")
        if p in ("USA", "PER"):    # su subyacente común ya es "sin alimentos y energía"
            out.add(p, "inflacion_sae_12m", st.com(p, "inflacion_subyacente_12m"),
                    "subyacente oficial = sin alimentos y energía", "inflacion_subyacente_12m", grado=("B", "B"))
        elif st.get(p, "inflacion_sae_12m") is not None:
            out.add(p, "inflacion_sae_12m", st.get(p, "inflacion_sae_12m"),
                    "serie oficial sin alimentos y energía", "inflacion_sae_12m", grado=("B", "B"),
                    cobertura=SAE_NOTES.get(p, ""))

        out.add(p, "expectativa_inflacion_12m", st.com(p, "expectativa_inflacion_12m"), "publicada",
                "expectativa_inflacion_12m")

        if tg is not None and inf12 is not None:
            t = targets_monthly(tg, p, pd.Timestamp(today.year, today.month, 1))
            if t.empty:
                continue
            note = "meta sobre el mismo índice" if (t.coincide == "si").all() else \
                "ATENCIÓN: la meta se define sobre otro índice (ver metas_inflacion.csv)"
            out.add(p, "meta_inflacion", t.centro, note, "metas_inflacion.csv")
            out.add(p, "meta_inflacion_inferior", t.inferior, note, "metas_inflacion.csv")
            out.add(p, "meta_inflacion_superior", t.superior, note, "metas_inflacion.csv")
            j = pd.concat([inf12.rename("inf"), t], axis=1, join="inner")
            out.add(p, "desvio_meta_pp", j.inf - j.centro, note, "inflacion_12m, metas_inflacion.csv")
            # Metas de tipo "techo" solo tienen límite superior.
            band = j.dropna(subset=["superior"]).copy()
            band["inferior"] = band["inferior"].fillna(-np.inf)
            out.add(p, "fuera_de_rango_meta",
                    ((band.inf < band.inferior) | (band.inf > band.superior)).astype(float),
                    note, "inflacion_12m, metas_inflacion.csv")


def policy_rate_tea(st: Store, p: str) -> tuple[pd.Series | None, str]:
    s = st.com(p, "tasa_politica")
    if s is None:
        return None, ""
    if p == "USA":
        rng = s.index >= pd.Timestamp("2008-12-01")
        s = s.where(~rng, s - 0.125)
        return tea_act360(s), "límite superior del FOMC − 0,125 (punto medio) desde 2008-12; TEA act/360"
    if p == "ESP":
        mro = st.get(p, "tasa_bce_mro")
        metodo = "facilidad de depósito del BCE; TEA act/360"
        if mro is not None:
            cut = pd.Timestamp("2008-09-01")
            s = pd.concat([mro[mro.index <= cut], s[s.index > cut]]).sort_index()
            s = s[~s.index.duplicated(keep="last")]
            metodo = "MRO del BCE hasta 2008-09 y facilidad de depósito después; TEA act/360"
        return tea_act360(s), metodo
    if p in ("CHL", "MEX"):
        return tea_act360(s), "TEA act/360"
    if p == "ARG":
        return s, "sin convertir: TNA de un instrumento que cambió en el tiempo"
    return s, "publicada (ya en TEA)"


def interbank_tea(st: Store, p: str) -> tuple[pd.Series | None, str]:
    s = st.com(p, "tasa_interbancaria")
    if p == "ESP":
        eonia = st.get(p, "eonia")
        if eonia is not None:
            first = s.index.min() if s is not None else pd.Timestamp.max
            pre = eonia[eonia.index < first] - 0.085
            s = pd.concat([pre, s]) if s is not None else pre
            return tea_act360(s.sort_index()), "€STR; antes de 2019-10, EONIA − 8,5 pb (equivalencia del BCE); TEA act/360"
        return (tea_act360(s), "€STR; TEA act/360") if s is not None else (None, "")
    if s is None:
        return None, ""
    if p in ("USA", "CHL", "MEX"):
        return tea_act360(s), "TEA act/360"
    if p == "ARG":
        return tea_tna365(s, 1), "TNA a 1 día → TEA"
    return s, "publicada"


def constant_fx_credit(st: Store, fx: FX, p: str, cred: pd.Series) -> tuple[pd.Series, str]:
    """Crédito con el componente en ME valuado a un tipo de cambio fijo (promedio de BASE_YEAR)."""
    tc = fx.fin_m(p)
    if p in USD_COUNTRIES or tc is None:
        return cred, "saldo publicado"
    tc_base = tc[tc.index.year == BASE_YEAR].mean()
    mn, me = st.get(p, "credito_privado_mn"), st.get(p, "credito_privado_me_usd")
    if mn is not None and me is not None:
        j = pd.concat([mn.rename("mn"), me.rename("me")], axis=1, join="inner").dropna()
        return j.mn + j.me * tc_base, f"MN + ME(USD) × TC promedio {BASE_YEAR}"
    for name, is_mn_share in (("dolarizacion_credito", False), ("dolarizacion_credito_privado", False),
                              ("bolivianizacion_credito", True)):
        ratio = st.get(p, name)
        if ratio is not None:
            share_me = (100 - ratio) / 100 if is_mn_share else ratio / 100
            j = pd.concat([cred.rename("c"), share_me.rename("d"), tc.rename("tc")], axis=1, join="inner").dropna()
            me_lc = j.c * j.d
            return (j.c - me_lc) + me_lc / j.tc * tc_base, \
                f"saldo × (1 − {name}) + parte en ME a TC promedio {BASE_YEAR}"
    return cred, "saldo publicado (sin desglose MN/ME)"


def build_monetario(st: Store, fx: FX, out: Output, cob: dict) -> None:
    fed, _ = policy_rate_tea(st, "USA")
    for p in st.paises:
        i, metodo = policy_rate_tea(st, p)
        out.add(p, "tasa_politica_tea", i, metodo, "tasa_politica")
        ib, metodo_ib = interbank_tea(st, p)
        out.add(p, "tasa_interbancaria_tea", ib, metodo_ib, "tasa_interbancaria")
        pe = st.com(p, "expectativa_inflacion_12m")
        if i is not None and pe is not None:
            j = pd.concat([i.rename("i"), pe.rename("pe")], axis=1, join="inner")
            out.add(p, "tasa_real_exante", ((1 + j.i / 100) / (1 + j.pe / 100) - 1) * 100,
                    "(1+i)/(1+πᵉ)−1 con i en TEA", "tasa_politica, expectativa_inflacion_12m")
        if i is not None and fed is not None and p != "USA":
            j = pd.concat([i.rename("i"), fed.rename("f")], axis=1, join="inner")
            out.add(p, "diferencial_fed_pp", j.i - j.f, "tasa de política (TEA) − Fed (TEA, punto medio)",
                    "tasa_politica, USA tasa_politica")
        out.add(p, "tasa_activa_promedio", st.com(p, "tasa_activa_promedio"), "publicada", "tasa_activa_promedio")
        out.add(p, "tasa_pasiva_promedio", st.com(p, "tasa_pasiva_promedio"), "publicada", "tasa_pasiva_promedio")

        cred = st.com(p, "credito_privado")
        if cred is not None:
            c = cob.get(("credito", p), "")
            # Saldo a tipo de cambio CORRIENTE: con desglose MN/ME se reconstruye (PER publica el
            # total a un TC constante de 3,36); sin desglose se usa el total publicado.
            mn, me, tc = st.get(p, "credito_privado_mn"), st.get(p, "credito_privado_me_usd"), fx.fin_m(p)
            if mn is not None and me is not None and tc is not None:
                j = pd.concat([mn.rename("mn"), me.rename("me"), tc.rename("tc")], axis=1, join="inner").dropna()
                cred_usd, cred_cur = j.mn / j.tc + j.me, j.mn + j.me * j.tc
                metodo_lvl, ins_lvl = "MN / TC fin de mes + ME (USD)", "credito_privado_mn, credito_privado_me_usd"
            else:
                cred_usd = fx.to_usd(p, cred, st.unit(p, "credito_privado"), "saldo", "mensual")
                cred_cur, metodo_lvl, ins_lvl = cred, "saldo / tipo de cambio de fin de mes", "credito_privado"
            out.add(p, "credito_privado_usd", cred_usd, metodo_lvl, ins_lvl, cobertura=c)
            ctc, metodo_c = constant_fx_credit(st, fx, p, cred)
            out.add(p, "credito_var_a", yoy(ctc), f"a/a de: {metodo_c}", "credito_privado", cobertura=c)
            ipc = st.com(p, "ipc_indice")
            if ipc is not None:
                real = ((1 + yoy(ctc) / 100) / (1 + yoy(ipc).reindex(ctc.index) / 100) - 1) * 100
                out.add(p, "credito_real_var_a", real, f"a/a real con el IPC de: {metodo_c}",
                        "credito_privado, ipc_indice", cobertura=c)
            gdp = st.com(p, "pbi_nominal_anual")
            if gdp is not None:
                dec = last_of_period(cred_cur, (12,))
                out.add(p, "credito_pct_pbi", dec / gdp.reindex(dec.index) * 100,
                        "saldo de diciembre a TC corriente / PBI nominal del año", f"{ins_lvl}, pbi_nominal_anual",
                        cobertura=c)

        m3 = st.get(p, "m3_amplio")
        money, src = (m3, "m3_amplio") if m3 is not None else (st.com(p, "m2"), "m2")
        if money is not None:
            c = cob.get(("dinero", p), "")
            grado = ("B", "B") if src == "m3_amplio" else None
            if src == "m3_amplio":
                c = "amplio (M3, incluye moneda extranjera)"
            out.add(p, "dinero_amplio_var_a", yoy(money), f"a/a de {src}", src, cobertura=c, grado=grado)
            gdp = st.com(p, "pbi_nominal_anual")
            if gdp is not None:
                dec = last_of_period(money, (12,))
                out.add(p, "dinero_amplio_pct_pbi", dec / gdp.reindex(dec.index) * 100,
                        f"{src} de diciembre / PBI nominal", f"{src}, pbi_nominal_anual", cobertura=c, grado=grado)


def imports_usd(st: Store, fx: FX, p: str) -> pd.Series | None:
    s = st.com(p, "importaciones")
    return None if s is None else fx.to_usd(p, s, st.unit(p, "importaciones"), "flujo", "mensual")


def build_externo(st: Store, fx: FX, out: Output, cob: dict) -> None:
    for p in st.paises:
        tc = fx.prom_m(p)
        if tc is not None:
            metodo = {"ESP": "1 / (USD por EUR)", "BOL": "medio compra/venta"}.get(p, "publicado")
            out.add(p, "tc_ml_por_usd", tc, metodo, "tc_usd_promedio")
            out.add(p, "depreciacion_var_a", yoy(tc), "a/a del promedio mensual", "tc_usd_promedio")
        d = fx.daily(p)
        if d is not None:
            out.add(p, "tc_ml_por_usd_fin", fx.fin_m(p),
                    "último día hábil" + ("; re-fechado a t−1" if p in TC_LAGGED else ""), "tc_usd_diario")
            r = np.log(d).diff().dropna()
            g = r.groupby(r.index.to_period("M"))
            vol = (g.std() * np.sqrt(252) * 100)[g.count() >= 10]
            vol.index = vol.index.to_timestamp(how="start")
            out.add(p, "volatilidad_tc", vol[vol.index < fx.current_month],
                    "desvío de retornos log diarios × √252 (≥10 días)", "tc_usd_diario")

        # reservas
        res = st.com(p, "reservas_internacionales")
        res_freq = "trimestral" if p == "USA" else "mensual"
        c = cob.get(("reservas", p), "")
        res_usd = None
        if res is not None:
            res_usd = fx.to_usd(p, res, st.unit(p, "reservas_internacionales"), "saldo", res_freq)
            out.add(p, "reservas_usd", res_usd, "publicadas; EUR→USD a fin de mes" if p == "ESP" else "publicadas",
                    "reservas_internacionales", frecuencia=res_freq, cobertura=c)
        brutas = st.get(p, "reservas_brutas")
        ref, ref_freq, ref_name = res_usd, res_freq, "reservas publicadas"
        if brutas is not None:
            brutas = fx.to_usd(p, brutas, st.unit(p, "reservas_brutas"), "saldo", "mensual")
            out.add(p, "reservas_brutas_usd", brutas, "serie bruta oficial", "reservas_brutas",
                    cobertura="bruta", grado=("A", "A"))
            ref, ref_freq, ref_name = brutas, "mensual", "reservas brutas"
        elif res_usd is not None and c.startswith("bruta"):
            out.add(p, "reservas_brutas_usd", res_usd, "la serie publicada ya es bruta",
                    "reservas_internacionales", frecuencia=res_freq, cobertura=c)
            ref_name = "reservas brutas"
        imp = imports_usd(st, fx, p)
        if ref is not None and imp is not None:
            avg = roll12_sum(imp) / 12
            # USA publica reservas trimestrales fechadas al inicio del trimestre: comparar con el
            # promedio de importaciones al cierre del trimestre.
            end = ref.index + pd.DateOffset(months=2) if ref_freq == "trimestral" else ref.index
            ratio = pd.Series(ref.values / avg.reindex(end).values, index=ref.index)
            out.add(p, "reservas_meses_importacion", ratio,
                    f"{ref_name} / importaciones promedio de 12 meses", "reservas, importaciones",
                    frecuencia=ref_freq, cobertura="bruta" if ref_name == "reservas brutas" else c)
        gdp_usd = None
        gdp = st.com(p, "pbi_nominal_anual")
        if gdp is not None:
            gdp_usd = fx.to_usd(p, gdp, st.unit(p, "pbi_nominal_anual"), "flujo", "anual")
        if ref is not None and gdp_usd is not None:
            if ref_freq == "trimestral":
                q4 = ref[ref.index.month == 10]
                dec = pd.Series(q4.values, index=pd.to_datetime([dt.date(x.year, 1, 1) for x in q4.index]))
            else:
                dec = last_of_period(ref, (12,))
            out.add(p, "reservas_pct_pbi", dec / gdp_usd.reindex(dec.index) * 100,
                    f"{ref_name} de fin de año / PBI en USD", "reservas, pbi_nominal_anual",
                    cobertura="bruta" if ref_name == "reservas brutas" else c)

        # comercio (aduana, mensual)
        exp = st.com(p, "exportaciones")
        exp_usd = None if exp is None else fx.to_usd(p, exp, st.unit(p, "exportaciones"), "flujo", "mensual")
        ci = cob.get(("importaciones", p), "")
        conv = "; EUR→USD con TC promedio" if p == "ESP" else ""
        out.add(p, "exportaciones_usd", exp_usd, "aduana" + conv, "exportaciones")
        out.add(p, "importaciones_usd", imp, "aduana" + conv, "importaciones", cobertura=ci)
        if exp_usd is not None and imp is not None:
            j = pd.concat([exp_usd.rename("x"), imp.rename("m")], axis=1, join="inner")
            out.add(p, "balanza_comercial_usd", j.x - j.m, "X − M (aduana)", "exportaciones, importaciones",
                    cobertura=ci)
            out.add(p, "exportaciones_var_a_12m", yoy(roll12_sum(exp_usd)), "a/a de la suma de 12 meses",
                    "exportaciones")
            out.add(p, "importaciones_var_a_12m", yoy(roll12_sum(imp)), "a/a de la suma de 12 meses",
                    "importaciones", cobertura=ci)

        # bienes trimestrales: balanza de pagos si existe, si no aduana
        trim = {}
        for flow, aduana in (("exportaciones", exp_usd), ("importaciones", imp)):
            bp = st.get(p, f"{flow}_bienes_bp")
            if bp is not None:
                unit = st.unit(p, f"{flow}_bienes_bp")
                months = bp.index.month
                if len(bp) > 1 and not set(months).issubset({1, 4, 7, 10}):
                    bp = aggregate(bp, "Q", "sum", 3)      # mensual → trimestral
                bp_usd = fx.to_usd(p, bp, unit, "flujo", "trimestral")
                trim[flow] = (bp_usd, "balanza de pagos (FOB, incluye zonas francas)", f"{flow}_bienes_bp")
            elif aduana is not None:
                trim[flow] = (aggregate(aduana, "Q", "sum", 3), "suma trimestral de aduana", flow)
        for flow, ind in (("exportaciones", "exportaciones_bienes_trim_usd"),
                          ("importaciones", "importaciones_bienes_trim_usd")):
            if flow in trim:
                s, metodo, src = trim[flow]
                grado = ("A", "A") if src.endswith("_bp") else None
                out.add(p, ind, s, metodo, src, cobertura="" if src.endswith("_bp") else ci, grado=grado)
        if len(trim) == 2:
            j = pd.concat([trim["exportaciones"][0].rename("x"), trim["importaciones"][0].rename("m")],
                          axis=1, join="inner")
            both_bp = trim["exportaciones"][2].endswith("_bp") and trim["importaciones"][2].endswith("_bp")
            out.add(p, "balanza_bienes_trim_usd", j.x - j.m,
                    "X − M " + ("(balanza de pagos)" if both_bp else "(aduana o mixto)"),
                    f"{trim['exportaciones'][2]}, {trim['importaciones'][2]}",
                    grado=("A", "A") if both_bp else None)
            if gdp_usd is not None:
                a = aggregate(j.x + j.m, "Y", "sum", 4)
                out.add(p, "apertura_comercial_pct_pbi", a / gdp_usd.reindex(a.index) * 100,
                        "(X + M de bienes del año) / PBI en USD",
                        f"{trim['exportaciones'][2]}, {trim['importaciones'][2]}, pbi_nominal_anual",
                        grado=("B", "B") if both_bp else None)

        ca = st.com(p, "cuenta_corriente")
        if ca is not None:
            ca_usd = fx.to_usd(p, ca, st.unit(p, "cuenta_corriente"), "flujo", "trimestral")
            out.add(p, "cuenta_corriente_usd", ca_usd, "publicada" + ("; EUR→USD con TC promedio trimestral"
                                                                      if p == "ESP" else ""), "cuenta_corriente")
            if gdp_usd is not None and ca_usd is not None:
                a = aggregate(ca_usd, "Y", "sum", 4)
                out.add(p, "cuenta_corriente_pct_pbi", a / gdp_usd.reindex(a.index) * 100,
                        "suma de 4 trimestres / PBI en USD", "cuenta_corriente, pbi_nominal_anual")


def annual_from(s: pd.Series | None, unit_freq_quarterly: bool) -> pd.Series | None:
    """Fiscal trimestral (suma móvil o saldo): el T4 es el dato anual."""
    if s is None:
        return None
    if unit_freq_quarterly or not set(s.index.month).issubset({1}):
        q4 = s[s.index.month == 10]
        return pd.Series(q4.values, index=pd.to_datetime([dt.date(d.year, 1, 1) for d in q4.index]))
    return s


def build_fiscal(st: Store, fx: FX, out: Output, cob: dict) -> None:
    for p in st.paises:
        c = cob.get(("fiscal", p), "")
        rfsp = st.get(p, "rfsp_pct_pbi")
        if rfsp is not None:
            # La serie ya viene con el signo de la fuente: negativo = déficit (requerimiento).
            res, metodo, src = rfsp, "RFSP (requerimientos financieros del sector público; − = déficit)", "rfsp_pct_pbi"
            c = "sector_publico_amplio (RFSP)"
        else:
            raw = st.com(p, "resultado_fiscal_pct_pbi")
            res = annual_from(raw, False) if raw is not None else None
            metodo = "T4 de la suma móvil de 4 trimestres" if raw is not None and \
                not set(raw.index.month).issubset({1}) else "publicado / calculado (ver docs/fuentes)"
            src = "resultado_fiscal_pct_pbi"
        out.add(p, "resultado_fiscal_pct_pbi", res, metodo, src, cobertura=c)
        if res is not None:
            out.add(p, "resultado_fiscal_var_pp", res - res.shift(1).where(
                res.index.to_series().diff().dt.days.between(360, 370).values), "diferencia anual", src, cobertura=c)

        c = cob.get(("deuda", p), "")
        debt, metodo, src = None, "", ""
        if st.get(p, "shrfsp_pct_pbi") is not None:
            debt, metodo, src = st.get(p, "shrfsp_pct_pbi"), "SHRFSP (saldo histórico de los RFSP)", "shrfsp_pct_pbi"
            c = "sector_publico_amplio_neta (SHRFSP)"
        elif p == "USA" and st.get(p, "deuda_publico_pct_pbi") is not None:
            debt, metodo, src = st.get(p, "deuda_publico_pct_pbi"), "deuda federal en manos del público", \
                "deuda_publico_pct_pbi"
            c = "gobierno_federal_en_manos_del_publico (año fiscal)"
        elif p == "PRY" and st.get(p, "deuda_publica_usd") is not None:
            gdp = st.com(p, "pbi_nominal_anual")
            gdp_usd = fx.to_usd(p, gdp, st.unit(p, "pbi_nominal_anual"), "flujo", "anual") if gdp is not None else None
            usd = annual_from(st.get(p, "deuda_publica_usd"), False)
            if gdp_usd is not None:
                debt = usd / gdp_usd.reindex(usd.index) * 100
                metodo, src = "deuda en USD / PBI del BCP en USD (evita el cambio de denominador del MEF)", \
                    "deuda_publica_usd, pbi_nominal_anual"
        if debt is None:
            raw = st.com(p, "deuda_publica_pct_pbi")
            debt = annual_from(raw, False) if raw is not None else None
            metodo = "T4 del saldo trimestral" if raw is not None and not set(raw.index.month).issubset({1}) \
                else "publicada"
            src = "deuda_publica_pct_pbi"
        out.add(p, "deuda_publica_pct_pbi", debt, metodo, src, cobertura=c)
        if debt is not None:
            out.add(p, "deuda_publica_var_pp", debt - debt.shift(1).where(
                debt.index.to_series().diff().dt.days.between(360, 370).values), "diferencia anual", src, cobertura=c)


UNEMPLOYMENT_TYPE = {"BRA": "movil", "CHL": "movil", "PER": "movil", "ARG": "trimestral",
                     "ESP": "trimestral", "PRY": "trimestral", "PAN": "anual", "ECU": "irregular"}


def build_laboral(st: Store, fx: FX, out: Output, cob: dict) -> None:
    for p in st.paises:
        c = cob.get(("desempleo", p), "")
        u, src = st.com(p, "desempleo"), "desempleo"
        if p == "USA" and st.get(p, "desempleo_nsa") is not None:
            u, src = st.get(p, "desempleo_nsa"), "desempleo_nsa"
        if u is not None:
            kind = UNEMPLOYMENT_TYPE.get(p, "mensual")
            if kind == "movil":
                q, metodo = last_of_period(u, (3, 6, 9, 12)), "trimestre móvil de mar/jun/sep/dic = trimestre calendario"
            elif kind == "trimestral":
                q, metodo = u, "trimestral publicada"
            elif kind == "irregular":
                q, metodo = aggregate(u, "Q", "mean", 1), "promedio de los datos del trimestre (≥1)"
            elif kind == "mensual":
                q, metodo = aggregate(u, "Q", "mean", 3), "promedio de los 3 meses"
            else:
                q, metodo = None, ""
            if p == "USA" and src == "desempleo":
                metodo += " (serie DESESTACIONALIZADA: falta desempleo_nsa)"
            if q is not None:
                out.add(p, "desempleo_trim", q, metodo, src, cobertura=c)
                out.add(p, "desempleo_var_a_pp", diff_yoy(q), "diferencia a/a en pp", src, cobertura=c)
                out.add(p, "desempleo_anual", aggregate(q, "Y", "mean", 4), "promedio de 4 trimestres", src,
                        cobertura=c)
            else:
                out.add(p, "desempleo_anual", u, "anual publicada", src, cobertura=c)

        sm = st.com(p, "salario_minimo")
        if sm is not None:
            unit = st.unit(p, "salario_minimo").lower()
            factor, metodo = 1.0, "mensual publicado"
            if "día" in unit or "dia" in unit:
                factor, metodo = 30.4, "diario × 30,4"
            elif p == "ESP":
                factor, metodo = 14 / 12, "mensual en 14 pagas × 14/12"
            smm = sm * factor
            out.add(p, "salario_minimo_mensual_ml", smm, metodo, "salario_minimo")
            out.add(p, "salario_minimo_usd", fx.to_usd(p, smm, st.unit(p, "salario_minimo"), "flujo", "mensual"),
                    metodo + "; / TC promedio del mes", "salario_minimo, tc_usd_promedio")
            ipc = st.com(p, "ipc_indice")
            if ipc is not None:
                real = (smm / ipc.reindex(smm.index)).dropna()
                out.add(p, "salario_minimo_real_indice", rebase(real, 12), f"salario / IPC, {BASE_YEAR}=100",
                        "salario_minimo, ipc_indice")
                out.add(p, "salario_minimo_real_var_a", yoy(real), "a/a real", "salario_minimo, ipc_indice")


# ---------------------------------------------------------------------------------------
# Post-proceso: cortes, regímenes, grados
# ---------------------------------------------------------------------------------------
def matches(indicador: str, patterns: str) -> bool:
    pats = [x.strip() for x in str(patterns).split(",") if x.strip()]
    return any(fnmatch.fnmatch(indicador, pat) for pat in pats)


def apply_cuts(obs: pd.DataFrame) -> pd.DataFrame:
    cuts = pd.read_csv(COMP_CONFIG / "cortes_muestra.csv", dtype=str, encoding="utf-8-sig", keep_default_na=False)
    keep = pd.Series(True, index=obs.index)
    for r in cuts.itertuples():
        sel = (obs.pais == r.pais) & obs.indicador.map(lambda x: matches(x, r.indicadores))
        d0 = pd.Timestamp(r.desde) if r.desde else pd.Timestamp.min
        d1 = pd.Timestamp(r.hasta) if r.hasta else pd.Timestamp.max
        inside = obs.fecha.between(d0, d1)
        if r.tipo == "mantener":
            keep &= ~(sel & ~inside)
        else:
            keep &= ~(sel & inside)
    log.info("Cortes de muestra: %d observaciones descartadas", (~keep).sum())
    return obs[keep]


def apply_regimes(obs: pd.DataFrame) -> pd.Series:
    reg = pd.read_csv(COMP_CONFIG / "regimenes.csv", dtype=str, encoding="utf-8-sig", keep_default_na=False)
    flags = pd.Series("", index=obs.index)
    for r in reg.itertuples():
        sel = (obs.pais == r.pais) if r.pais != "*" else pd.Series(True, index=obs.index)
        sel &= obs.indicador.map(lambda x: matches(x, r.indicadores))
        d0 = pd.Timestamp(r.desde) if r.desde else pd.Timestamp.min
        d1 = pd.Timestamp(r.hasta) if r.hasta else pd.Timestamp.max
        sel &= obs.fecha.between(d0, d1)
        flags[sel] = np.where(flags[sel] == "", r.etiqueta, flags[sel] + ";" + r.etiqueta)
    return flags


def grades() -> dict[tuple[str, str], tuple[str, str]]:
    m = pd.read_csv(MATRIX_CSV, dtype=str, encoding="utf-8-sig", keep_default_na=False)
    return {(r.indicador_comun, r.pais): (r.grado_niveles, r.grado_variaciones) for r in m.itertuples()}


# ---------------------------------------------------------------------------------------
# Validación
# ---------------------------------------------------------------------------------------
def validate(st: Store, obs: pd.DataFrame) -> pd.DataFrame:
    checks = []

    def add(nombre, pais, ok, detalle):
        checks.append({"prueba": nombre, "pais": pais, "resultado": "ok" if ok else "REVISAR", "detalle": detalle})

    def get(p, ind):
        s = obs[(obs.pais == p) & (obs.indicador == ind)].set_index("fecha").valor
        return s if not s.empty else None

    for p in st.paises:
        # inflación 12m calculada desde el índice vs publicada
        ipc, inf = st.com(p, "ipc_indice"), st.com(p, "inflacion_12m")
        if ipc is not None and inf is not None:
            dif = (yoy(ipc) - inf).dropna()
            dif = dif[dif.index >= pd.Timestamp("2000-01-01")]
            if len(dif):
                add("inflacion_12m_desde_indice", p, dif.abs().max() < 0.15,
                    f"máx |dif| desde 2000 = {dif.abs().max():.3f} pp (n={len(dif)})")
        # PBI a/a calculado vs publicado
        calc, pub = get(p, "pbi_real_var_a"), st.com(p, "pbi_real_var12m_trim")
        if calc is not None and pub is not None:
            dif = (calc - pub).dropna()
            if len(dif):
                add("pbi_var_a_vs_publicada", p, dif.abs().mean() < 0.3 or p in ("ECU", "ESP", "USA"),
                    f"media |dif| = {dif.abs().mean():.2f} pp (ECU/ESP/USA publican sobre la desestacionalizada)")
        # balanza = X − M
        x, m, b = get(p, "exportaciones_usd"), get(p, "importaciones_usd"), st.com(p, "balanza_comercial")
        # PAN: su balanza común es la de balanza de pagos (con la Zona Libre de Colón), no X − M.
        if x is not None and m is not None and b is not None and p not in ("ESP", "PAN"):
            dif = ((x - m) - b).dropna()
            if len(dif):
                add("balanza_igual_x_menos_m", p, dif.abs().max() < 2,
                    f"máx |dif| = {dif.abs().max():.1f} millones USD")
        # rangos plausibles del último dato
        for ind, lo, hi in (("salario_minimo_usd", 80, 3000), ("reservas_meses_importacion", 0.3, 40),
                            ("tasa_real_exante", -30, 40), ("desempleo_trim", 0, 40),
                            ("credito_pct_pbi", 3, 300), ("dinero_amplio_pct_pbi", 5, 200),
                            ("cuenta_corriente_pct_pbi", -25, 25), ("apertura_comercial_pct_pbi", 5, 250),
                            ("tc_ml_por_usd", 0, 1e5)):
            s = get(p, ind)
            if s is not None:
                v = s.iloc[-1]
                add(f"rango_{ind}", p, lo <= v <= hi, f"último ({s.index[-1]:%Y-%m}) = {v:.2f}; rango [{lo}, {hi}]")
    # cuenta corriente % PBI frente a cifras oficiales citadas en docs/comparabilidad/externo.md
    for p, year, official in (("CHL", 2025, -1.2), ("COL", 2025, -2.4), ("PER", 2025, 3.5)):
        s = get(p, "cuenta_corriente_pct_pbi")
        if s is not None and pd.Timestamp(year, 1, 1) in s.index:
            v = s[pd.Timestamp(year, 1, 1)]
            add("cuenta_corriente_pct_pbi_vs_oficial", p, abs(v - official) < 0.2,
                f"{year}: {v:.2f} vs oficial {official}")
    # España: EUR por USD en rango (incluye el euro sintético desde 1979; máximo en 1985 ≈ 1,49)
    s = get("ESP", "tc_ml_por_usd")
    if s is not None:
        add("esp_eur_por_usd", "ESP", s.between(0.6, 1.6).all(), f"rango {s.min():.3f}–{s.max():.3f}")
    # USA: el punto medio del FOMC
    s = get("USA", "tasa_politica_tea")
    if s is not None and pd.Timestamp("2015-06-01") in s.index:
        add("usa_punto_medio_2015_06", "USA", abs(s[pd.Timestamp("2015-06-01")] - 0.125) < 0.01,
            f"2015-06 = {s[pd.Timestamp('2015-06-01')]:.3f} (esperado 0,125)")
    return pd.DataFrame(checks)


# ---------------------------------------------------------------------------------------
def main() -> int:
    comun.setup_logging("COMPARABLE")
    today = dt.date.today()
    obs_in = pd.read_parquet(PROCESSED_DIR / "macro_observaciones.parquet")
    obs_in["indicador_comun"] = obs_in["indicador_comun"].fillna("")
    st = Store(obs_in)
    fx = FX(st, today)
    cob = cobertura_table()
    out = Output()
    for builder in (build_actividad, build_monetario, build_externo, build_fiscal, build_laboral):
        builder(st, fx, out, cob)
    build_precios(st, fx, out, cob, today)

    obs = pd.concat(out.parts, ignore_index=True)
    obs = apply_cuts(obs)
    obs["regimen"] = apply_regimes(obs)
    obs = obs.sort_values(["indicador", "pais", "fecha"]).reset_index(drop=True)

    meta = pd.DataFrame(out.meta).drop_duplicates(["pais", "indicador"], keep="last")
    cover = obs.groupby(["pais", "indicador"]).fecha.agg(n_obs="count", desde="min", hasta="max").reset_index()
    meta = meta.merge(cover, on=["pais", "indicador"], how="inner")
    meta = meta.merge(CATALOG_DF[["indicador", "bloque", "unidad", "base_comun", "tipo"]], on="indicador")
    g = grades()
    gn, gv = [], []
    for r in meta.itertuples():
        if r.grado_override:
            a, b = r.grado_override.split("/")
        else:
            a, b = g.get((r.base_comun, r.pais), ("", ""))
        gn.append(a)
        gv.append(b)
    meta["grado_niveles"], meta["grado_variaciones"] = gn, gv
    meta["uso"] = [USO.get(a if t == "nivel" else b, "sin_grado")
                   for a, b, t in zip(meta.grado_niveles, meta.grado_variaciones, meta.tipo)]
    meta = meta[["bloque", "indicador", "pais", "frecuencia", "unidad", "n_obs", "desde", "hasta", "uso",
                 "grado_niveles", "grado_variaciones", "cobertura", "metodo", "insumos"]]
    meta = meta.sort_values(["bloque", "indicador", "pais"])

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    obs.to_parquet(OUT_DIR / "comparable_observaciones.parquet", index=False)
    obs.to_csv(OUT_DIR / "comparable_observaciones.csv", index=False, encoding="utf-8-sig")
    meta.to_csv(OUT_DIR / "comparable_series.csv", index=False, encoding="utf-8-sig")
    CATALOG_DF.to_csv(OUT_DIR / "comparable_catalogo.csv", index=False, encoding="utf-8-sig")

    cell = meta.assign(texto=meta.uso + ": " + meta.desde.dt.strftime("%Y-%m") + " → " +
                       meta.hasta.dt.strftime("%Y-%m"))
    (cell.pivot(index="indicador", columns="pais", values="texto")
     .reindex(CATALOG_DF.indicador).fillna("")
     .to_csv(OUT_DIR / "comparable_cobertura.csv", encoding="utf-8-sig"))

    usable = meta[meta.uso != "no_comparable"][["pais", "indicador"]]
    panel_obs = obs.merge(usable, on=["pais", "indicador"])
    for freq in comun.FREQUENCIES:
        sub = panel_obs[panel_obs.frecuencia == freq]
        if sub.empty:
            continue
        cols = [c for c in CATALOG_DF.indicador if c in set(sub.indicador)]
        panel = sub.pivot_table(index=["pais", "fecha"], columns="indicador", values="valor",
                                aggfunc="first")[cols].sort_index()
        panel.to_csv(OUT_DIR / f"comparable_panel_{freq}.csv", encoding="utf-8-sig")

    val = validate(st, obs)
    val.to_csv(OUT_DIR / "comparable_validacion.csv", index=False, encoding="utf-8-sig")

    log.info("Capa comparable: %s observaciones · %d indicadores · %d pares país×indicador",
             f"{len(obs):,}", obs.indicador.nunique(), len(meta))
    log.info("Uso: %s", meta.uso.value_counts().to_dict())
    bad = val[val.resultado != "ok"]
    log.info("Validación: %d pruebas, %d para revisar", len(val), len(bad))
    for r in bad.itertuples():
        log.warning("  REVISAR %-38s %s  %s", r.prueba, r.pais, r.detalle)
    return 0


if __name__ == "__main__":
    sys.exit(main())
