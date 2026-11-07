"""Bloque «fortaleza externa y fiscal» del informe «El Perú frente a la región».

Lee solo la capa comparable (data/processed/comparable/) y respeta:
- la columna `uso` de comparable_series.csv;
- las marcas de régimen de cada observación (config/comparable/regimenes.csv);
- los cortes de muestra (config/comparable/cortes_muestra.csv).

Qué entra (según la revisión de comparabilidad):
- cuenta corriente en % del PBI (países MBP6);
- reservas en meses de importación (países con moneda propia; brutas frente a netas);
- depreciación y volatilidad del tipo de cambio de las monedas flotantes;
- fiscal y deuda: entre países SOLO cambios en pp; niveles solo del Perú frente a su historia.

Regla común del informe (medianas y puestos):
- solo países de América Latina; la mediana es la de los OTROS países (sin el Perú);
- se compara el mismo periodo: el último del Perú, en los países que lo tienen;
- España y EE. UU. se muestran como referencia, sin entrar en medianas ni puestos.

Uso: python src/informe_region/externo.py  → data/processed/informe_region/externo.json
"""
from __future__ import annotations

import json
import math
import sys
import time
from fnmatch import fnmatch
from pathlib import Path

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------------------
# Constantes
# --------------------------------------------------------------------------------------
COUNTRY_NAMES = {
    "PER": "Perú", "CHL": "Chile", "COL": "Colombia", "MEX": "México", "BRA": "Brasil",
    "ARG": "Argentina", "ECU": "Ecuador", "URY": "Uruguay", "PRY": "Paraguay",
    "BOL": "Bolivia", "PAN": "Panamá", "ESP": "España", "USA": "Estados Unidos",
}
LATAM = ["PER", "CHL", "COL", "MEX", "BRA", "ARG", "ECU", "URY", "PRY", "BOL", "PAN"]
# Monedas flotantes válidas para depreciación y volatilidad (revisión de comparabilidad)
FLOATERS = ["PER", "BRA", "CHL", "COL", "MEX", "PRY", "URY"]
# Sin moneda o política cambiaria propia: tipo de cambio y reservas no aplican
NO_OWN_CURRENCY = {"ECU": "dolarizado", "PAN": "dolarizado", "ESP": "zona del euro"}
# Emisor de la moneda de reserva: reservas en meses de importación no miden holgura
RESERVE_ISSUER = {"USA"}
USABLE = {"comparable", "comparable_con_ajuste"}
TRENDS_OK = USABLE | {"solo_tendencias"}          # para cambios dentro de cada país
FX_REGIMES_OUT = ("cepo_cambiario", "tc_fijo", "tc_oficial_unico")
FISCAL_BASE_YEAR = 2019                           # prepandemia
PER_FISCAL_FROM = 2015                            # historia propia del Perú en niveles
HIST_START = "2010-01-01"
FX_HIST_START = "2019-01-01"

MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "setiembre", "octubre", "noviembre", "diciembre"]
MON_ABBR = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "set", "oct", "nov", "dic"]
ORD_HIGH = {1: "el más alto", 2: "el segundo más alto", 3: "el tercero más alto",
            4: "el cuarto más alto", 5: "el quinto más alto"}
ORD_LOW = {1: "la más baja", 2: "la segunda más baja", 3: "la tercera más baja",
           4: "la cuarta más baja", 5: "la quinta más baja"}

SRC_BP = ("Bancos centrales de cada país (balanza de pagos) e institutos de estadística "
          "(PBI nominal); conversión a USD con el tipo de cambio oficial.")
SRC_RES = ("Bancos centrales de cada país (reservas internacionales) y estadísticas de comercio "
           "exterior. RIN del Perú: BCRP, Nota Informativa 062-2006.")
SRC_FX = "Bancos centrales de cada país (tipo de cambio oficial de referencia)."
SRC_FIS = ("Ministerios de economía y hacienda, bancos centrales e institutos de estadística "
           "de cada país.")
SRC_FIS_PER = "BCRP y Ministerio de Economía y Finanzas del Perú."

# Coberturas institucionales legibles (columna `cobertura` de la capa comparable)
COVERAGE_BASE = {
    "spnf": "Sector público no financiero",
    "spn_no_financiero": "Sector público nacional no financiero, sin provincias",
    "spc_con_bc": "Sector público consolidado, con banco central",
    "gobierno_central": "Gobierno central",
    "gobierno_nacional_central": "Gobierno nacional central",
    "gobierno_general": "Gobierno general",
    "sector_publico_amplio": "Sector público amplio",
    "administracion_central": "Administración central",
    "gobierno_federal": "Gobierno federal",
    "gobierno_federal_en_manos_del_publico": "Gobierno federal, deuda en manos del público",
    "sector_publico_total": "Sector público total",
    "sector_publico": "Sector público",
}
COVERAGE_FLAGS = [("no consolidada", "no consolidada"), ("año fiscal", "año fiscal"),
                  ("base caja", "base caja"), ("SHRFSP", "SHRFSP"), ("RFSP", "RFSP")]


# --------------------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------------------
def _retry(fn, *args, tries: int = 8, wait: float = 20.0, **kw):
    """Reintenta lecturas: la actualización puede estar reescribiendo los archivos."""
    last = None
    for _ in range(tries):
        try:
            return fn(*args, **kw)
        except Exception as exc:  # archivo a medio escribir o bloqueado
            last = exc
            time.sleep(wait)
    raise last


def name(iso: str) -> str:
    return COUNTRY_NAMES.get(iso, iso)


def num(x: float, dec: int = 1, sign: bool = False) -> str:
    """Número en formato español (coma decimal, signo menos tipográfico)."""
    s = f"{abs(x):.{dec}f}".replace(".", ",")
    if x < 0 and float(s.replace(",", ".")) != 0:
        return "−" + s
    return ("+" + s) if sign and float(s.replace(",", ".")) != 0 else s


def month_text(d: pd.Timestamp) -> str:
    return f"{MONTHS[d.month - 1]} de {d.year}"


def mon_abbr(d) -> str:
    d = pd.Timestamp(d)
    return f"{MON_ABBR[d.month - 1]}-{d.year}"


def iso(d: pd.Timestamp) -> str:
    return pd.Timestamp(d).strftime("%Y-%m-%d")


def names_list(isos) -> str:
    n = [name(p) for p in isos]
    return n[0] if len(n) == 1 else ", ".join(n[:-1]) + " y " + n[-1]


def coverage_label(raw) -> str:
    if not isinstance(raw, str) or not raw.strip():
        return "—"
    code, _, rest = raw.partition("(")
    code = code.strip()
    kind = ""
    for suf, lab in (("_bruta", "bruta"), ("_neta", "neta")):
        if code.endswith(suf):
            code, kind = code[: -len(suf)], lab
    parts = [COVERAGE_BASE.get(code, code.replace("_", " ").capitalize())]
    if kind:
        parts.append(f"deuda {kind}")
    for key, lab in COVERAGE_FLAGS:
        if key in rest and lab not in parts:
            parts.append(lab)
            if key == "SHRFSP":
                break  # evita repetir RFSP dentro de SHRFSP
    return ", ".join(parts)


def _clean(o):
    """NaN/inf → None y tipos numpy → nativos, para JSON."""
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if (math.isnan(f) or math.isinf(f)) else f
    if isinstance(o, np.integer):
        return int(o)
    return o


# --------------------------------------------------------------------------------------
# Carga de la capa comparable
# --------------------------------------------------------------------------------------
INDICATORS = ["cuenta_corriente_pct_pbi", "cuenta_corriente_usd", "reservas_meses_importacion",
              "depreciacion_var_a", "volatilidad_tc", "resultado_fiscal_pct_pbi",
              "resultado_fiscal_var_pp", "deuda_publica_pct_pbi", "deuda_publica_var_pp"]


class Layer:
    def __init__(self, comparable_dir: Path):
        comparable_dir = Path(comparable_dir)
        obs = _retry(pd.read_parquet, comparable_dir / "comparable_observaciones.parquet")
        obs = obs[obs["indicador"].isin(INDICATORS)].copy()
        obs["fecha"] = pd.to_datetime(obs["fecha"])
        obs["regimen"] = obs["regimen"].fillna("")
        obs = obs.dropna(subset=["valor"])
        self.series = _retry(pd.read_csv, comparable_dir / "comparable_series.csv",
                             encoding="utf-8-sig")
        cfg = comparable_dir.parents[2] / "config" / "comparable"
        self.regimes = (_retry(pd.read_csv, cfg / "regimenes.csv", encoding="utf-8-sig")
                        if (cfg / "regimenes.csv").exists() else pd.DataFrame())
        cuts = (_retry(pd.read_csv, cfg / "cortes_muestra.csv", encoding="utf-8-sig")
                if (cfg / "cortes_muestra.csv").exists() else pd.DataFrame())
        self.obs = self._apply_cuts(obs, cuts)

    @staticmethod
    def _apply_cuts(obs: pd.DataFrame, cuts: pd.DataFrame) -> pd.DataFrame:
        """Cortes de muestra: 'mantener' conserva solo [desde, hasta]; 'excluir' lo quita."""
        if cuts.empty:
            return obs
        drop = pd.Series(False, index=obs.index)
        for r in cuts.itertuples():
            pats = [p.strip() for p in str(r.indicadores).split(",")]
            m = obs["indicador"].map(lambda i: any(fnmatch(i, p) for p in pats))
            if str(r.pais) != "*":
                m &= obs["pais"] == r.pais
            d0 = pd.to_datetime(r.desde) if pd.notna(r.desde) else pd.Timestamp.min
            d1 = pd.to_datetime(r.hasta) if pd.notna(r.hasta) else pd.Timestamp.max
            inside = obs["fecha"].between(d0, d1)
            drop |= m & (~inside if r.tipo == "mantener" else inside)
        return obs[~drop]

    def uso(self, ind: str) -> dict:
        s = self.series[self.series["indicador"] == ind]
        return dict(zip(s["pais"], s["uso"]))

    def coverage(self, ind: str) -> dict:
        s = self.series[self.series["indicador"] == ind]
        return dict(zip(s["pais"], s["cobertura"]))

    def get(self, ind: str, countries=None, usos=USABLE, drop_regimes=()) -> pd.DataFrame:
        u = self.uso(ind)
        ok = [p for p, v in u.items() if v in usos and (countries is None or p in countries)]
        df = self.obs[(self.obs["indicador"] == ind) & self.obs["pais"].isin(ok)]
        for reg in drop_regimes:
            df = df[~df["regimen"].str.contains(reg, regex=False)]
        return df.sort_values(["pais", "fecha"])


def at_ref_or_last(df: pd.DataFrame, ref: pd.Timestamp) -> pd.DataFrame:
    """Valor de cada país en el periodo de referencia (el del Perú); si no lo tiene, su último
    valor publicado (que luego no entra en medianas ni puestos)."""
    rows = []
    for p, d in df.sort_values("fecha").groupby("pais"):
        hit = d[d["fecha"] == ref]
        rows.append((hit if not hit.empty else d.tail(1)).iloc[-1])
    return pd.DataFrame(rows).set_index("pais") if rows else pd.DataFrame()


def lag_text(vals: pd.DataFrame, lag: list) -> str:
    """'2024 en Bolivia y Paraguay', agrupando por año."""
    by = {}
    for p in lag:
        by.setdefault(vals.loc[p, "fecha"].year, []).append(p)
    return "; ".join(f"{y} en {names_list(ps)}" for y, ps in sorted(by.items()))


def order_peru_first(isos) -> list:
    rest = sorted([p for p in isos if p != "PER"], key=lambda p: name(p))
    return (["PER"] if "PER" in isos else []) + rest


def bar_series(last: pd.DataFrame, order) -> list:
    return [{"pais": p, "nombre": name(p),
             "puntos": [[iso(last.loc[p, "fecha"]), float(last.loc[p, "valor"])]]}
            for p in order if p in last.index]


def line_series(df: pd.DataFrame, order, start: str, end=None) -> list:
    out = []
    for p in order:
        d = df[(df["pais"] == p) & (df["fecha"] >= start)]
        if end is not None:
            d = d[d["fecha"] <= end]
        if d.empty:
            continue
        out.append({"pais": p, "nombre": name(p),
                    "puntos": [[iso(f), float(v)] for f, v in zip(d["fecha"], d["valor"])]})
    return out


def peers_same_period(vals: pd.DataFrame, ref: pd.Timestamp, exclude=()) -> list:
    """Otros países de América Latina con dato en el mismo periodo del Perú."""
    return [p for p in vals.index
            if p in LATAM and p != "PER" and p not in exclude and vals.loc[p, "fecha"] == ref]


def rank_of_peru(vals: pd.Series, peers: list, ascending: bool) -> int:
    s = vals.loc[["PER"] + peers].sort_values(ascending=ascending)
    return list(s.index).index("PER") + 1


# --------------------------------------------------------------------------------------
# Construcción del bloque
# --------------------------------------------------------------------------------------
def build(comparable_dir: Path) -> dict:
    L = Layer(Path(comparable_dir))
    resumen, kpis, graficos, tablas, adv = [], [], [], [], []

    # ================= Cuenta corriente (% del PBI, anual) =================
    cc_all = L.get("cuenta_corriente_pct_pbi")
    cc_uso = L.uso("cuenta_corriente_pct_pbi")
    cc_ref = cc_all.loc[cc_all["pais"] == "PER", "fecha"].max()
    cc_vals = at_ref_or_last(cc_all, cc_ref)
    cc_peers = peers_same_period(cc_vals, cc_ref)
    cc_med = float(cc_vals.loc[cc_peers, "valor"].median())
    cc_rank = rank_of_peru(cc_vals["valor"], cc_peers, ascending=False)
    cc_lag = [p for p in cc_vals.index if cc_vals.loc[p, "fecha"] != cc_ref]
    cc_out = [p for p, v in cc_uso.items() if v not in USABLE]
    # ¿hay cuenta corriente en USD del año de referencia en los rezagados? (falta el PBI)
    ccu = L.get("cuenta_corriente_usd")
    lag_usd_full = [p for p in cc_lag
                    if (ccu[(ccu["pais"] == p) & (ccu["fecha"].dt.year == cc_ref.year)].shape[0] == 4)]

    nota_cc = ("Saldo anual (suma de cuatro trimestres) entre el PBI nominal en USD. Positivo = "
               f"superávit. Mediana y puesto: países de América Latina con dato de {cc_ref.year}; "
               "España y Estados Unidos solo como referencia.")
    if cc_lag:
        nota_cc += (" Último año publicado: " + lag_text(cc_vals, cc_lag)
                    + "; se muestra ese valor, fuera de la mediana y del puesto.")
    if "PAN" in cc_out:
        nota_cc += (" Panamá queda fuera: sus revisiones son grandes (por ejemplo, el saldo de "
                    "2023-T3 pasó de −5 855 a −990 millones de USD) y compila la balanza de pagos "
                    "con el manual anterior (MBP5).")
    graficos.append({
        "id": "cc_pct_pbi_ultimo", "titulo": "Cuenta corriente",
        "subtitulo": f"% del PBI, {cc_ref.year} o último año publicado",
        "tipo": "barras_h", "unidad": "% del PBI",
        "series": bar_series(cc_vals, list(cc_vals.sort_values("valor", ascending=False).index)),
        "nota": nota_cc, "fuente": SRC_BP})

    cc_hist_order = [p for p in FLOATERS if p in cc_vals.index]
    graficos.append({
        "id": "cc_pct_pbi_historia", "titulo": "Cuenta corriente desde 2010",
        "subtitulo": "% del PBI, países con tipo de cambio flotante",
        "tipo": "lineas", "unidad": "% del PBI",
        "series": line_series(cc_all, cc_hist_order, HIST_START),
        "nota": "Saldo anual entre el PBI nominal en USD. Positivo = superávit.",
        "fuente": SRC_BP})

    # ================= Reservas en meses de importación =================
    res_cands = [p for p in L.uso("reservas_meses_importacion")
                 if p not in NO_OWN_CURRENCY and p not in RESERVE_ISSUER]
    res = L.get("reservas_meses_importacion", countries=res_cands)
    res_ref = res.loc[res["pais"] == "PER", "fecha"].max()
    res_vals = at_ref_or_last(res, res_ref)
    # países con régimen cambiario marcado en el dato usado: en la tabla, no en mediana ni gráfico
    res_marked = [p for p in res_vals.index
                  if any(r in str(res_vals.loc[p, "regimen"]) for r in FX_REGIMES_OUT)]
    res_peers = peers_same_period(res_vals, res_ref, exclude=res_marked)
    res_med = float(res_vals.loc[res_peers, "valor"].median())
    res_cov = L.coverage("reservas_meses_importacion")
    res_uso = L.uso("reservas_meses_importacion")
    res_dropped_uso = [p for p in res_cands if res_uso.get(p) not in USABLE]
    netas = [p for p in res_vals.index if str(res_cov.get(p, "")).startswith("neta")]
    shown = [p for p in res_vals.index if p not in res_marked]
    brutas = [p for p in shown if p not in netas]
    res_lag = [p for p in shown if res_vals.loc[p, "fecha"] != res_ref]
    nota_res = ("Reservas de fin de mes entre el promedio mensual de importaciones de los últimos "
                f"12 meses, en {month_text(res_ref)} (mes del último dato del Perú). Brutas en "
                + names_list(order_peru_first(brutas)) + "; netas (RIN) en "
                + names_list(order_peru_first([p for p in netas if p in shown]))
                + ". La RIN del Perú incluye los encajes en dólares de la banca y los depósitos "
                "del sector público en el BCRP (Nota Informativa 062-2006); la posición de cambio "
                "del BCRP, que excluye esos pasivos, es menor. Sirve para seguir la tendencia de "
                "cada país, no como ranking de holgura.")
    if res_lag:
        nota_res += (" Último mes publicado en " + "; ".join(
            f"{name(p)}: {mon_abbr(res_vals.loc[p, 'fecha'])}" for p in res_lag) + ".")
    graficos.append({
        "id": "reservas_meses_ultimo", "titulo": "Reservas internacionales",
        "subtitulo": f"Meses de importación de bienes, {month_text(res_ref)}",
        "tipo": "barras", "unidad": "meses",
        "series": bar_series(res_vals, order_peru_first(shown)),
        "nota": nota_res, "fuente": SRC_RES})
    res_hist_order = [p for p in FLOATERS if p in res_vals.index]
    graficos.append({
        "id": "reservas_meses_historia", "titulo": "Reservas en meses de importación desde 2010",
        "subtitulo": "Meses de importación de bienes, países con tipo de cambio flotante",
        "tipo": "lineas", "unidad": "meses",
        "series": line_series(res, res_hist_order, HIST_START),
        "nota": ("Las variaciones incluyen efectos de valoración (oro y otras monedas) y no son "
                 "flujos de intervención cambiaria."),
        "fuente": SRC_RES})

    # ================= Tipo de cambio: depreciación y volatilidad =================
    # Regla única: todo se alinea en el último mes con depreciación del Perú (promedio mensual).
    fx_c = [p for p in FLOATERS if p not in NO_OWN_CURRENCY]
    dep = L.get("depreciacion_var_a", countries=fx_c, drop_regimes=FX_REGIMES_OUT)
    vol = L.get("volatilidad_tc", countries=fx_c, drop_regimes=FX_REGIMES_OUT)
    fx_ref = dep.loc[dep["pais"] == "PER", "fecha"].max()
    dep_vals = at_ref_or_last(dep[dep["fecha"] <= fx_ref], fx_ref)
    fx_order = order_peru_first(list(dep_vals.index))
    graficos.append({
        "id": "depreciacion_historia", "titulo": "Depreciación frente al dólar",
        "subtitulo": "Variación % a/a del tipo de cambio promedio del mes (+ = depreciación)",
        "tipo": "lineas", "unidad": "%",
        "series": line_series(dep, fx_order, FX_HIST_START, end=fx_ref),
        "nota": ("Moneda local por dólar, promedio mensual. Valores negativos = apreciación de la "
                 f"moneda local. Todas las series se cortan en {mon_abbr(fx_ref)}, último mes "
                 "publicado para el Perú, para comparar el mismo periodo."),
        "fuente": SRC_FX})

    win0 = fx_ref - pd.DateOffset(months=11)

    def vol_window(d: pd.DataFrame):
        w = d[(d["fecha"] >= win0) & (d["fecha"] <= fx_ref)]
        return float(w["valor"].mean()) if len(w) >= 10 else np.nan

    vol12, vol_ref = {}, {}
    for p, d in vol.groupby("pais"):
        vol12[p] = vol_window(d)
        r = d[(d["fecha"] >= "2015-01-01") & (d["fecha"] <= "2019-12-01")]
        vol_ref[p] = float(r["valor"].mean()) if len(r) >= 24 else np.nan
    vol_vals = pd.DataFrame({"fecha": fx_ref, "valor": pd.Series(vol12)}).dropna()
    vol_peers = [p for p in vol_vals.index if p != "PER" and p in LATAM]
    vol_rank = rank_of_peru(vol_vals["valor"], vol_peers, ascending=True)
    vol_med = float(vol_vals.loc[vol_peers, "valor"].median())
    # contraste: puesto del Perú si se incluyera Argentina (sin tramos de cepo)
    arg_vol = L.obs[(L.obs["indicador"] == "volatilidad_tc") & (L.obs["pais"] == "ARG")]
    arg_vol = arg_vol[~arg_vol["regimen"].str.contains("cepo_cambiario", regex=False)]
    arg_v = vol_window(arg_vol)
    rank_with_arg = (rank_of_peru(pd.concat([vol_vals["valor"], pd.Series({"ARG": arg_v})]),
                                  vol_peers + ["ARG"], ascending=True)
                     if pd.notna(arg_v) else None)
    graficos.append({
        "id": "volatilidad_12m", "titulo": "Volatilidad del tipo de cambio",
        "subtitulo": f"% anualizado, promedio de los 12 meses a {mon_abbr(fx_ref)}",
        "tipo": "barras", "unidad": "% anualizado",
        "series": bar_series(vol_vals, list(vol_vals.sort_values("valor").index)),
        "nota": ("Desviación estándar de las variaciones logarítmicas diarias de cada mes × √252, "
                 f"promediada de {mon_abbr(win0)} a {mon_abbr(fx_ref)} (último mes con "
                 "depreciación publicada para el Perú) en todos los países. Sin fines de semana; "
                 "Chile y Colombia refechados al día de la operación."),
        "fuente": SRC_FX})

    # ================= Fiscal =================
    def fiscal_changes(level_ind: str, var_ind: str):
        lev = L.get(level_ind, usos=TRENDS_OK)
        var = L.get(var_ind, usos=TRENDS_OK)
        out = {}
        for p, d in lev.groupby("pais"):
            d = d.set_index(d["fecha"].dt.year)
            last_y = int(d.index.max())
            base = d["valor"].get(FISCAL_BASE_YEAR, np.nan)
            v = var[var["pais"] == p]
            v_last = v.iloc[-1] if not v.empty else None
            out[p] = {
                "last_year": last_y, "fecha": d.loc[last_y, "fecha"],
                "last": float(d.loc[last_y, "valor"]), "base": base,
                "chg_base": (float(d.loc[last_y, "valor"] - base)
                             if pd.notna(base) and last_y > FISCAL_BASE_YEAR else np.nan),
                "chg_1y": float(v_last["valor"]) if v_last is not None else np.nan,
                "levels": d["valor"],
            }
        return out

    fis = fiscal_changes("resultado_fiscal_pct_pbi", "resultado_fiscal_var_pp")
    debt = fiscal_changes("deuda_publica_pct_pbi", "deuda_publica_var_pp")
    fis_cov = L.coverage("resultado_fiscal_pct_pbi")
    debt_cov = L.coverage("deuda_publica_pct_pbi")

    def change_bars(d: dict) -> list:
        order = order_peru_first([p for p, v in d.items() if pd.notna(v["chg_base"])])
        return [{"pais": p, "nombre": name(p),
                 "puntos": [[iso(d[p]["fecha"]), d[p]["chg_base"]]]} for p in order]

    nota_fis_common = ("Cambio dentro de cada país; las coberturas institucionales difieren "
                       "(gobierno central, sector público no financiero, gobierno general o sector "
                       "público consolidado), por lo que los niveles no se comparan ni se ordenan.")
    graficos.append({
        "id": "resultado_fiscal_cambio", "titulo": f"Resultado fiscal: cambio desde {FISCAL_BASE_YEAR}",
        "subtitulo": f"pp del PBI, último año frente a {FISCAL_BASE_YEAR} (+ = menor déficit o mayor superávit)",
        "tipo": "barras", "unidad": "pp del PBI", "series": change_bars(fis),
        "nota": nota_fis_common + " En Estados Unidos, año fiscal de octubre a setiembre.",
        "fuente": SRC_FIS})
    graficos.append({
        "id": "deuda_publica_cambio", "titulo": f"Deuda pública: cambio desde {FISCAL_BASE_YEAR}",
        "subtitulo": f"pp del PBI, último año frente a {FISCAL_BASE_YEAR} (+ = más deuda)",
        "tipo": "barras", "unidad": "pp del PBI", "series": change_bars(debt),
        "nota": nota_fis_common + (" México mide deuda neta; Argentina y Ecuador, deuda no "
                                   "consolidada; Estados Unidos, deuda federal en manos del público."),
        "fuente": SRC_FIS})

    # ================= Tablas =================
    ext_countries = order_peru_first(sorted(set(cc_vals.index) | set(res_vals.index)))
    rows = []
    for p in ext_countries:
        cc = cc_vals.loc[p] if p in cc_vals.index else None
        rs = res_vals.loc[p] if p in res_vals.index else None
        dp = dep_vals.loc[p] if p in dep_vals.index else None
        vl = vol12.get(p, np.nan)
        concept = None
        if rs is not None:
            concept = "neta (RIN)" if p in netas else "bruta"
            if p in res_marked:
                concept += "; transición cambiaria, fuera de la mediana"
        rows.append([
            name(p),
            round(float(cc["valor"]), 1) if cc is not None else None,
            str(cc["fecha"].year) if cc is not None else None,
            round(float(rs["valor"]), 1) if rs is not None else None,
            mon_abbr(rs["fecha"]) if rs is not None else None,
            concept,
            round(float(dp["valor"]), 1) if dp is not None else None,
            mon_abbr(dp["fecha"]) if dp is not None else None,
            round(vl, 1) if pd.notna(vl) else None,
            round(vol_ref[p], 1) if pd.notna(vl) and pd.notna(vol_ref.get(p)) else None,
        ])
    tablas.append({
        "id": "tabla_externo", "titulo": "Indicadores externos por país",
        "columnas": ["País", "Cuenta corriente (% PBI)", "Año", "Reservas (meses de importación)",
                     "Mes", "Reservas: concepto", "Depreciación a/a (%)", "Mes",
                     f"Volatilidad 12 meses a {mon_abbr(fx_ref)} (% anual.)",
                     "Volatilidad promedio 2015-2019"],
        "filas": rows,
        "nota": ("Vacío = no aplica: Ecuador y Panamá están dolarizados y España usa el euro; "
                 "Estados Unidos emite la moneda de reserva, así que sus reservas no miden holgura. "
                 "Argentina y Bolivia quedan fuera del análisis cambiario por sus regímenes. "
                 "Cada cifra lleva su periodo; no se rellenan huecos.")})

    fis_rows = []
    for p in order_peru_first(sorted(set(fis) | set(debt))):
        f, d = fis.get(p), debt.get(p)
        fis_rows.append([
            name(p),
            coverage_label(fis_cov.get(p)) if f else None,
            round(f["chg_base"], 1) if f and pd.notna(f["chg_base"]) else None,
            round(f["chg_1y"], 1) if f and pd.notna(f["chg_1y"]) else None,
            f["last_year"] if f else None,
            coverage_label(debt_cov.get(p)) if d else None,
            round(d["chg_base"], 1) if d and pd.notna(d["chg_base"]) else None,
            round(d["chg_1y"], 1) if d and pd.notna(d["chg_1y"]) else None,
            d["last_year"] if d else None,
        ])
    tablas.append({
        "id": "tabla_fiscal_cambios", "titulo": "Fiscal y deuda: cambios dentro de cada país",
        "columnas": ["País", "Resultado fiscal: cobertura", f"Cambio desde {FISCAL_BASE_YEAR} (pp)",
                     "Cambio último año (pp)", "Último año", "Deuda: cobertura",
                     f"Cambio desde {FISCAL_BASE_YEAR} (pp)", "Cambio último año (pp)", "Último año"],
        "filas": fis_rows,
        "nota": ("Solo cambios en puntos porcentuales del PBI. Resultado: + = mejora (menor déficit "
                 "o mayor superávit). Deuda: + = aumento. No se muestran niveles porque las "
                 "coberturas institucionales no son homogéneas entre países. Bolivia y Panamá no "
                 "publican una serie de deuda descargable.")})

    # Niveles del Perú frente a su propia historia (permitido dentro del país)
    if "PER" in fis and "PER" in debt:
        fl, dl = fis["PER"]["levels"], debt["PER"]["levels"]
        last_y = max(fis["PER"]["last_year"], debt["PER"]["last_year"])
        per_rows = [[y, round(float(fl[y]), 1) if y in fl.index else None,
                     round(float(dl[y]), 1) if y in dl.index else None]
                    for y in range(PER_FISCAL_FROM, last_y + 1)]
        f_avg = fl.loc[PER_FISCAL_FROM:FISCAL_BASE_YEAR].mean()
        d_avg = dl.loc[PER_FISCAL_FROM:FISCAL_BASE_YEAR].mean()
        per_rows.append([f"Promedio {PER_FISCAL_FROM}-{FISCAL_BASE_YEAR}",
                         round(float(f_avg), 1), round(float(d_avg), 1)])
        tablas.append({
            "id": "tabla_peru_fiscal_niveles",
            "titulo": f"Perú: resultado fiscal y deuda pública, {PER_FISCAL_FROM}-{last_y}",
            "columnas": ["Año", "Resultado económico del SPNF (% PBI)",
                         "Deuda bruta del SPNF (% PBI)"],
            "filas": per_rows,
            "nota": ("Niveles solo del Perú, para compararlo con su propia historia; no se "
                     "comparan con otros países porque las coberturas difieren. Resultado: "
                     "negativo = déficit. Sector público no financiero (SPNF). "
                     f"Fuente: {SRC_FIS_PER}")})

    # ================= KPIs del Perú =================
    if "PER" in cc_vals.index:
        r = cc_vals.loc["PER"]
        kpis.append({"lab": "Cuenta corriente", "val": float(r["valor"]), "fmt": "pct1",
                     "unit": "% del PBI",
                     "sub": (f"{r['fecha'].year}; mediana de los otros {len(cc_peers)} países de "
                             f"la región: {num(cc_med)} %"),
                     "fecha": iso(r["fecha"])})
    if "PER" in res_vals.index:
        r = res_vals.loc["PER"]
        kpis.append({"lab": "Reservas internacionales netas", "val": float(r["valor"]),
                     "fmt": "num1", "unit": "meses de importación",
                     "sub": (f"{month_text(r['fecha']).capitalize()}; mediana de los otros "
                             f"{len(res_peers)} países de la región con moneda propia: {num(res_med)}"),
                     "fecha": iso(r["fecha"])})
    if "PER" in dep_vals.index:
        r = dep_vals.loc["PER"]
        d = float(r["valor"])
        sol = (1 / (1 + d / 100) - 1) * 100
        kpis.append({"lab": "Tipo de cambio: variación a/a", "val": d,
                     "fmt": "pct1", "unit": "%",
                     "sub": (f"{month_text(r['fecha']).capitalize()}; el sol se "
                             f"{'apreció' if sol > 0 else 'depreció'} {num(abs(sol))} %"),
                     "fecha": iso(r["fecha"])})
    if "PER" in vol_vals.index:
        kpis.append({"lab": "Volatilidad cambiaria", "val": float(vol_vals.loc["PER", "valor"]),
                     "fmt": "pct1", "unit": "% anualizado",
                     "sub": (f"Promedio de 12 meses a {month_text(fx_ref)}; mediana de las otras "
                             f"{len(vol_peers)} monedas flotantes: {num(vol_med)} %"),
                     "fecha": iso(fx_ref)})
    if "PER" in fis and pd.notna(fis["PER"]["chg_base"]):
        f = fis["PER"]
        kpis.append({"lab": "Resultado fiscal: cambio", "val": f["chg_base"], "fmt": "pp1",
                     "unit": "pp del PBI",
                     "sub": (f"{f['last_year']} frente a {FISCAL_BASE_YEAR}; SPNF: "
                             f"{num(f['last'])} % del PBI en {f['last_year']}"),
                     "fecha": iso(f["fecha"])})
    if "PER" in debt and pd.notna(debt["PER"]["chg_base"]):
        d = debt["PER"]
        kpis.append({"lab": "Deuda pública: cambio", "val": d["chg_base"], "fmt": "pp1",
                     "unit": "pp del PBI",
                     "sub": (f"{d['last_year']} frente a {FISCAL_BASE_YEAR}; deuda bruta del SPNF: "
                             f"{num(d['last'])} % del PBI en {d['last_year']}"),
                     "fecha": iso(d["fecha"])})

    # ================= Resumen (generado con los datos) =================
    if "PER" in cc_vals.index:
        r = cc_vals.loc["PER"]
        word = "superávit" if r["valor"] >= 0 else "déficit"
        txt = (f"En {cc_ref.year} el Perú registró un {word} en cuenta corriente de "
               f"{num(abs(r['valor']))} % del PBI")
        if cc_rank in ORD_HIGH:
            txt += f", {ORD_HIGH[cc_rank]} entre {len(cc_peers) + 1} países de la región con dato de ese año"
            if cc_rank > 1:
                top = cc_vals.loc[cc_peers, "valor"].idxmax()
                txt += f" después de {name(top)} ({num(cc_vals.loc[top, 'valor'])} %)"
        txt += f"; la mediana de los otros {len(cc_peers)} países fue {num(cc_med)} %."
        resumen.append(txt)
    if "PER" in res_vals.index:
        r = res_vals.loc["PER"]
        rel = "por encima de" if r["valor"] > res_med else "por debajo de"
        resumen.append(
            f"Las reservas internacionales netas del Perú equivalían a {num(r['valor'])} meses de "
            f"importación en {month_text(r['fecha'])}, {rel} la mediana de los otros "
            f"{len(res_peers)} países de la región con moneda propia ({num(res_med)} meses); la "
            "comparación es referencial porque la RIN peruana incluye los encajes en dólares de "
            "la banca y los depósitos del sector público.")
    if "PER" in dep_vals.index and "PER" in vol_vals.index:
        d = float(dep_vals.loc["PER", "valor"])
        sol = (1 / (1 + d / 100) - 1) * 100
        tc_move = "bajó" if d < 0 else "subió"
        sol_move = "se apreció" if sol > 0 else "se depreció"
        v_txt = ORD_LOW.get(vol_rank, f"la {vol_rank}.ª más baja")
        resumen.append(
            f"En {month_text(fx_ref)} el tipo de cambio {tc_move} {num(abs(d))} % a/a (el sol "
            f"{sol_move} {num(abs(sol))} %), y su volatilidad promedio de los 12 meses previos "
            f"({num(float(vol_vals.loc['PER', 'valor']))} % anualizado) fue {v_txt} entre "
            f"{len(vol_peers) + 1} monedas flotantes de la región.")
    if "PER" in fis and "PER" in debt and pd.notna(fis["PER"]["chg_base"]) and pd.notna(debt["PER"]["chg_base"]):
        f, d = fis["PER"], debt["PER"]
        fv, dv = f["chg_base"], d["chg_base"]
        bal = (f"un déficit de {num(abs(f['last']))} % del PBI" if f["last"] < 0
               else f"un superávit de {num(f['last'])} % del PBI")
        f_txt = (f"{num(abs(fv))} pp del PBI {'peor' if fv < 0 else 'mejor'} que en "
                 f"{FISCAL_BASE_YEAR} ({num(f['base'])} %)")
        d_txt = (f"la deuda bruta llegó a {num(d['last'])} % del PBI, {num(abs(dv))} pp "
                 f"{'por encima' if dv >= 0 else 'por debajo'} de {FISCAL_BASE_YEAR}")
        yrs = (str(f["last_year"]) if f["last_year"] == d["last_year"]
               else f"{f['last_year']} (resultado) y {d['last_year']} (deuda)")
        resumen.append(
            f"En lo fiscal, el sector público no financiero del Perú cerró {yrs} con {bal}, "
            f"{f_txt}, y {d_txt}; entre países solo se comparan cambios, no niveles, por "
            "diferencias de cobertura institucional.")

    # ================= Advertencias =================
    adv.append("Medianas y puestos: solo países de América Latina, sin el Perú y en el mismo "
               "periodo que el último dato del Perú. España y Estados Unidos se muestran como "
               "referencia, fuera de medianas y puestos.")
    adv.append("Ecuador y Panamá están dolarizados y España usa el euro: el tipo de cambio y las "
               "reservas no miden una política cambiaria propia, por lo que quedan fuera de esos "
               "indicadores. Sí entran en cuenta corriente (Ecuador y España) y en fiscal.")
    adv.append("Reservas: se mezclan reservas brutas (" + names_list(order_peru_first(brutas))
               + ") y netas (" + names_list(order_peru_first([p for p in netas if p in shown]))
               + "). La RIN del Perú incluye los encajes en dólares de la banca y los depósitos del "
               "sector público en el BCRP (Nota Informativa 062-2006); la posición de cambio del "
               "BCRP, que los excluye, es menor. Uruguay también incluye encajes en dólares. "
               "Sirven para seguir la tendencia de cada país, no para ordenar la holgura entre "
               "países.")
    if res_marked:
        adv.append("Reservas de " + names_list(res_marked) + ": quedan en la tabla con su marca, "
                   "pero fuera de la mediana y del gráfico: Bolivia está en transición cambiaria y sus "
                   "reservas son sobre todo oro.")
    if res_dropped_uso:
        adv.append("Reservas de " + names_list(res_dropped_uso) + ": fuera de la comparación; las "
                   "brutas incluyen el swap con China, encajes en dólares y repos, que no son de "
                   "libre disponibilidad. Estados Unidos tampoco entra: emite la moneda de "
                   "reserva, así que sus reservas no miden holgura.")
    # regímenes cambiarios, descritos desde la configuración
    reg_txt = []
    if not L.regimes.empty:
        rg = L.regimes
        arg = rg[(rg["pais"] == "ARG") & (rg["etiqueta"] == "cepo_cambiario")]
        bol = rg[(rg["pais"] == "BOL") & (rg["etiqueta"].isin(["tc_fijo", "tc_oficial_unico"]))]
        if not arg.empty:
            tramos = "; ".join(f"{mon_abbr(a)} a {mon_abbr(b)}"
                               for a, b in zip(arg["desde"], arg["hasta"]))
            reg_txt.append(
                f"Argentina queda fuera por el cepo cambiario ({tramos}). Desde el 14-abr-2025 se "
                "liberó el acceso de las personas humanas (Com. «A» 8226), pero las empresas "
                "mantienen restricciones, y en 2026 cambió la metodología del tipo de referencia.")
        if not bol.empty:
            fijo = bol[bol["etiqueta"] == "tc_fijo"]
            nuevo = bol[bol["etiqueta"] == "tc_oficial_unico"]
            t = "Bolivia queda fuera: tuvo tipo de cambio fijo"
            if not fijo.empty and pd.notna(fijo["hasta"].iloc[0]):
                t += f" hasta {mon_abbr(fijo['hasta'].iloc[0])}"
            if not nuevo.empty:
                d0 = pd.Timestamp(nuevo["desde"].iloc[0])
                t += (f". Desde el {d0.day}-{MON_ABBR[d0.month - 1]}-{d0.year}, el BCB (Bolivia) "
                      "calcula el tipo oficial a partir de operaciones de mercado (RD 88/2026), "
                      "pero la variación a/a todavía cruza el tramo fijo")
            reg_txt.append(t + ".")
    if reg_txt:
        txt = ("Depreciación y volatilidad solo para las monedas flotantes ("
               + names_list(sorted(fx_c, key=name)) + "). " + " ".join(reg_txt))
        if rank_with_arg is not None:
            same = rank_with_arg == vol_rank
            txt += (f" Si se incluyera Argentina ({num(arg_v)} % anualizado en los 12 meses a "
                    f"{mon_abbr(fx_ref)}), el Perú "
                    + (f"seguiría siendo {ORD_LOW.get(vol_rank, str(vol_rank))} en volatilidad."
                       if same else
                       f"pasaría a ser {ORD_LOW.get(rank_with_arg, str(rank_with_arg))} en volatilidad."))
        adv.append(txt)
    if "PAN" in cc_out:
        adv.append("Cuenta corriente: Panamá queda fuera porque sus revisiones son grandes (el "
                   "saldo de 2023-T3 pasó de −5 855 a −990 millones de USD) y compila la balanza "
                   "de pagos con el manual anterior (MBP5). España se convierte de euros a dólares.")
    if cc_lag:
        t = ("Cuenta corriente. Último año publicado: " + lag_text(cc_vals, cc_lag)
             + "; se muestra ese valor, fuera de la mediana y del puesto.")
        if lag_usd_full:
            t += (f" En {names_list(lag_usd_full)} ya hay cuenta corriente de {cc_ref.year} en "
                  f"dólares, pero no PBI nominal anual de {cc_ref.year} para el cociente.")
        adv.append(t)
    adv.append("Fiscal y deuda: las coberturas institucionales no son homogéneas (gobierno central, "
               "sector público no financiero, gobierno general o sector público con banco "
               "central; México con deuda neta; Argentina y Ecuador sin consolidar; Estados Unidos "
               "en año fiscal). Por eso entre países solo se muestran cambios en pp y no se "
               "ordenan países por nivel de déficit o deuda; los niveles del Perú se comparan "
               "solo con su propia historia.")
    adv.append("La deuda argentina es muy sensible a la valoración cambiaria (salto en 2023 por la "
               "devaluación de diciembre); su cambio desde 2019 debe leerse con cautela.")

    return _clean({
        "id": "externo",
        "titulo": "Fortaleza externa y fiscal",
        "resumen": resumen, "kpis": kpis, "graficos": graficos, "tablas": tablas,
        "advertencias": adv,
    })


# --------------------------------------------------------------------------------------
if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    comp = root / "data" / "processed" / "comparable"
    out_dir = root / "data" / "processed" / "informe_region"
    out_dir.mkdir(parents=True, exist_ok=True)
    block = build(comp)
    text = json.dumps(block, ensure_ascii=False, indent=1, allow_nan=False)
    (out_dir / "externo.json").write_text(text, encoding="utf-8")

    # Controles
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(f"externo.json: {len(text):,} bytes")
    print("RESUMEN:")
    for s in block["resumen"]:
        print("  -", s)
    print("KPIs:")
    for k in block["kpis"]:
        print(f"  - {k['lab']}: {k['val']:.2f} {k['unit']} ({k['fecha']}) | {k['sub']}")
    print("GRÁFICOS:")
    for g in block["graficos"]:
        n = sum(len(s["puntos"]) for s in g["series"])
        print(f"  - {g['id']} [{g['tipo']}]: {len(g['series'])} series, {n} puntos, "
              f"países={[s['pais'] for s in g['series']]}")
        assert all(s["pais"] in COUNTRY_NAMES for s in g["series"])
        if g["tipo"] in ("barras", "barras_h"):
            assert all(len(s["puntos"]) == 1 for s in g["series"]), g["id"]
    for g in block["graficos"]:
        if g["id"] in {"depreciacion_historia", "volatilidad_12m"}:
            assert not {s["pais"] for s in g["series"]} & {"ARG", "BOL", "ECU", "PAN", "ESP", "USA"}
        if g["id"].startswith("reservas"):
            assert not {s["pais"] for s in g["series"]} & {"ECU", "PAN", "ESP", "USA"}
    bad = [w for w in ("aún no", "desvío", "re-fechad", "–", ".py", "agente") if w in text]
    assert not bad, bad
    print("TABLAS:", [(t["id"], len(t["filas"])) for t in block["tablas"]])
    print("ADVERTENCIAS:", len(block["advertencias"]))
    for a in block["advertencias"]:
        print("  -", a)
