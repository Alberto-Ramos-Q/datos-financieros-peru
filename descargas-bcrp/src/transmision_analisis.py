"""Análisis del traspaso de la tasa de referencia del BCRP a las tasas de mercado.

Módulo de cálculo para el tablero «Transmisión de la política monetaria en el Perú»
(`visual_transmision.py` lo importa). No escribe archivos: `build_transmission(m, d)` devuelve un
dict serializable a JSON (sin NaN; `None` donde no hay dato) con:

- `ciclos`: ciclos de alzas y recortes de la tasa de referencia desde 2003-09;
- `tasas`: catálogo de las tasas analizadas;
- `traspaso_ciclo`: cambio de cada tasa en cada ciclo y su ratio frente al de la referencia;
- `ecm`: traspaso de largo plazo, impacto y velocidad (modelo de corrección de errores, ARDL);
- `respuesta`: traspaso acumulado a 0-24 meses (multiplicadores dinámicos) con bandas al 95 %;
- `metodo`: textos breves en español para las notas del tablero;
- `controles`: pruebas de coherencia y robustez, en texto.

La metodología y los resultados están en `docs/transmision/metodologia_traspaso.md`.

Uso directo (imprime un resumen):
    python transmision_analisis.py
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

# statsmodels se importa dentro de las funciones que lo usan (`_fit`, `ecm_for_series`), para que
# `find_cycles` y `cycle_passthrough` se puedan importar sin él.

# ---------------------------------------------------------------------------------------------
# Parámetros (cambiarlos obliga a actualizar docs/transmision/metodologia_traspaso.md)
# ---------------------------------------------------------------------------------------------
REF = "tasa_referencia"
REF_DAILY = "tasa_referencia_diario"
REF_START = pd.Timestamp("2003-09-01")       # inicio del régimen de tasa de referencia
COVID_CYCLE_START = pd.Timestamp("2020-03-01")  # única excepción a la regla de ciclos
LAG_AFTER_CYCLE = 6                          # meses tras el último cambio para medir el traspaso
SMALL_DREF = 1.0                             # |Δ referencia| < 1 pp: el ratio no se publica
LONG_PAUSE = 12                              # pausa larga dentro de un ciclo (solo para la nota)
SAMPLE_START = pd.Timestamp("2010-08-01")    # tasas por tipo de crédito empiezan aquí
COVID_FROM, COVID_TO = pd.Timestamp("2020-03-01"), pd.Timestamp("2021-12-01")
PRE_TO = pd.Timestamp("2020-02-01")
POST_FROM = pd.Timestamp("2022-01-01")
PYME_BREAK = pd.Timestamp("2025-03-01")      # salto de 38,9 % a 58,2 % (feb → mar-2025)
SBS_MICRO_BREAK = pd.Timestamp("2025-01-01") # SBS microempresa: 46,3 % → 65,2 % (dic-2024 → ene-2025)
BREAKS = {"pyme": PYME_BREAK, "sbs_micro": SBS_MICRO_BREAK}
CAP_FROM = pd.Timestamp("2021-05-01")        # tasa máxima (Ley 31143)
MAX_LAG = 5                                  # rezagos máximos de Δy y de Δx (además de Δx_t)
HORIZON = 24
LONG_HORIZON = 120                           # para m50 / m90 cuando el ajuste es lento
N_SIM = 2000
SEED = 20261102
LP_CONTROLS = 3                              # rezagos de control en las proyecciones locales

# Valores críticos asintóticos de la prueba de límites (Pesaran, Shin y Smith, 2001),
# caso III (constante sin restricción, sin tendencia), k = 1 regresor.
PSS_F_5 = (4.94, 5.73)     # I(0), I(1) al 5 %
PSS_T_5 = (-2.86, -3.22)
POST_SHIFT_FROM = POST_FROM                  # variante: escalón desde 2022 (cambio de margen)

# Umbrales de robustez del ECM (fijados antes de mirar resultados).
MAX_SUBSAMPLE_GAP = 0.40   # |β pre-COVID − β post-COVID|
MIN_SUBSAMPLE_N = 40       # observaciones mínimas de cada submuestra
MAX_COVID_GAP = 0.30       # |β con escalón − β excluyendo los meses COVID|
BETA_RANGE = (0.0, 1.5)
PATH_FLOOR = -0.25         # el multiplicador a 0-24 meses no baja de aquí
PATH_OVERSHOOT = (1.5, 0.25)  # ... ni sube por encima de 1,5·|β| + 0,25

# Catálogo: (nombre_corto, etiqueta, grupo, moneda, en ECM, marca especial)
SERIES = [
    ("tasa_interbancaria_mn", "Interbancaria", "mercado", "MN", True, None),
    ("tasa_cd_bcrp_hasta3m", "CD BCRP hasta 3 meses", "mercado", "MN", False, "cd"),
    ("tasa_cd_bcrp_4a6m", "CD BCRP 4 a 6 meses", "mercado", "MN", False, "cd"),
    ("tasa_cd_bcrp_7m_1a", "CD BCRP 7 meses a 1 año", "mercado", "MN", False, "cd"),
    ("tasa_cd_bcrp_1a_2a", "CD BCRP 1 a 2 años", "mercado", "MN", False, "cd"),
    ("tasa_preferencial_corp_mn", "Preferencial corporativa 90 días", "activa", "MN", True, None),
    ("tasa_bancos_corporativo_hasta360_mn", "Corporativo hasta 360 días", "activa", "MN", True, None),
    ("tasa_bancos_grandes_empresas_hasta360_mn", "Grandes empresas hasta 360 días", "activa", "MN", True, None),
    ("tasa_bancos_medianas_empresas_hasta360_mn", "Medianas empresas hasta 360 días", "activa", "MN", True, None),
    ("tasa_bancos_pyme_hasta360_mn", "Pequeña y microempresa hasta 360 días", "activa", "MN", True, "pyme"),
    ("tasa_bancos_consumo_prest_hasta360_mn", "Consumo, préstamos hasta 360 días", "activa", "MN", True, "consumo"),
    ("tasa_bancos_hipotecario_mn", "Hipotecario", "activa", "MN", True, None),
    ("ftamn", "FTAMN (activa promedio de 30 días)", "activa", "MN", True, "composicion"),
    ("tasa_pasiva_ahorro_mn", "Ahorro", "pasiva", "MN", True, None),
    ("tasa_pasiva_plazo_hasta30d_mn", "Plazo hasta 30 días", "pasiva", "MN", True, None),
    ("tasa_pasiva_plazo_31a180d_mn", "Plazo de 31 a 180 días", "pasiva", "MN", True, None),
    ("tasa_pasiva_plazo_181a360d_mn", "Plazo de 181 a 360 días", "pasiva", "MN", True, None),
    ("tasa_pasiva_plazo_mas360d_mn", "Plazo a más de 360 días", "pasiva", "MN", True, None),
    ("ftipmn", "FTIPMN (pasiva promedio de 30 días)", "pasiva", "MN", True, None),
    ("bono_soberano_10a_soles", "Bono soberano a 10 años", "bonos", "MN", True, None),
    ("tasa_interbancaria_me", "Interbancaria", "mercado", "ME", False, "me"),
    ("tasa_preferencial_corp_me", "Preferencial corporativa 90 días", "activa", "ME", False, "me"),
    ("tasa_bancos_corporativo_hasta360_me", "Corporativo hasta 360 días", "activa", "ME", False, "me"),
    ("ftamex", "FTAMEX (activa promedio de 30 días)", "activa", "ME", False, "me"),
    ("ftipmex", "FTIPMEX (pasiva promedio de 30 días)", "pasiva", "ME", False, "me"),
]
# Tasas de operaciones nuevas de la SBS (banca múltiple, columna «Promedio», MN), opcionales.
PROJECT_DIR = Path(__file__).resolve().parents[1]
SBS_RATES = PROJECT_DIR.parent / "descargas-sbs" / "data" / "processed" / "tasas_activas.parquet"
SBS_SUBSYSTEM = "banca-multiple"
SBS_SERIES = [
    ("sbs_corporativo", "Corporativo (SBS, operaciones nuevas)", "activa", "MN", True, "sbs"),
    ("sbs_grandes", "Grandes empresas (SBS, operaciones nuevas)", "activa", "MN", True, "sbs"),
    ("sbs_medianas", "Medianas empresas (SBS, operaciones nuevas)", "activa", "MN", True, "sbs"),
    ("sbs_pequenas", "Pequeñas empresas (SBS, operaciones nuevas)", "activa", "MN", True, "sbs_pequenas"),
    ("sbs_micro", "Microempresas (SBS, operaciones nuevas)", "activa", "MN", True, "sbs_micro"),
    ("sbs_consumo", "Consumo (SBS, operaciones nuevas)", "activa", "MN", True, "sbs_consumo"),
    ("sbs_hipotecario", "Hipotecario (SBS, operaciones nuevas)", "activa", "MN", True, "sbs"),
]
RISK_FLAGS = ("pyme", "consumo", "sbs_micro", "sbs_consumo")   # sin ratio y sin traspaso publicado
CAP_FLAGS = ("pyme", "consumo", "sbs_pequenas", "sbs_micro", "sbs_consumo")

# Tramos de bonos del Tesoro (0 = sin dato): se limpian si se usan; hoy no entran al análisis.
TREASURY_TRANCHES = ["tasa_bonos_tesoro_hasta5a", "tasa_bonos_tesoro_5a10a",
                     "tasa_bonos_tesoro_10a15a", "tasa_bonos_tesoro_15a20a",
                     "tasa_bonos_tesoro_mas20a"]

# Tasas que, aunque se estiman, no se publican como traspaso (ok = False por diseño).
_MES_TXT = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "set", "oct", "nov", "dic"]


def _mes0(ts) -> str:
    return f"{_MES_TXT[ts.month - 1]} {ts.year}"


CAP_NOTE = (f"Desde {_mes0(CAP_FROM)} rige además una tasa máxima para consumo y MYPE; este "
            "tablero no mide su efecto.")
_RISK_TXT = "depende sobre todo del riesgo y de los costos operativos"
FORCED_NOT_OK = {
    "pyme": (f"No se publica como traspaso: esta tasa {_RISK_TXT} y tiene un salto de serie en "
             f"{_mes0(PYME_BREAK)} (posible quiebre, controlado con un escalón). " + CAP_NOTE),
    "consumo": f"No se publica como traspaso: esta tasa {_RISK_TXT}. " + CAP_NOTE,
    "sbs_micro": (f"No se publica como traspaso: la tasa de microempresa {_RISK_TXT} y salta en "
                  f"{_mes0(SBS_MICRO_BREAK)} (posible quiebre de serie, controlado con un "
                  "escalón). " + CAP_NOTE),
    "sbs_consumo": f"No se publica como traspaso: la tasa de consumo {_RISK_TXT}. " + CAP_NOTE,
    "composicion": ("No se publica como traspaso: es un promedio de todos los tipos de crédito y "
                    "lo mueve también el peso de cada tipo. Usar las tasas por tipo."),
}


# ---------------------------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------------------------
def _r(v, nd: int = 3):
    """Redondea a `nd` decimales; NaN, inf o None → None."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, nd) if np.isfinite(f) else None


def _ym(ts) -> str:
    return f"{ts.year:04d}-{ts.month:02d}"


_MES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "set", "oct", "nov", "dic"]


def _mes(ts) -> str:
    """Mes para textos: «set 2026»."""
    return f"{_MES[ts.month - 1]} {ts.year}"


def _f(v: float, nd: int = 2, sign: bool = False) -> str:
    """Número para textos: punto decimal y signo «−»; sin «−0.00»; NaN o None → «—»."""
    if v is None or not np.isfinite(float(v)):
        return "—"
    v = float(v)
    if abs(v) < 0.5 * 10 ** -nd:
        v = 0.0
    txt = f"{v:+.{nd}f}" if sign else f"{v:.{nd}f}"
    return txt.replace("-", "−")


def _span(rows) -> str:
    """Periodo de una muestra para textos: «feb 2011 a set 2026»."""
    if rows is None or len(rows) == 0:
        return "—"
    return f"{_mes(rows.min())} a {_mes(rows.max())}"


def _err(exc: Exception) -> str:
    """Excepción en una línea corta, para `controles`."""
    msg = (str(exc).splitlines() or [""])[0][:160]
    return f"{type(exc).__name__}: {msg}"


def _meses(n: int) -> str:
    return f"{n} mes" if n == 1 else f"{n} meses"


def _months_between(a: pd.Timestamp, b: pd.Timestamp) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def _add_months(ts: pd.Timestamp, n: int) -> pd.Timestamp:
    return ts + pd.DateOffset(months=n)


def _clean_panel(m: pd.DataFrame) -> pd.DataFrame:
    """Copia del panel con índice mensual (inicio de mes) y los 0 de los tramos del Tesoro como NaN."""
    m = m.copy()
    m.index = pd.to_datetime(m.index).to_period("M").to_timestamp()
    m = m.sort_index()
    for c in TREASURY_TRANCHES:
        if c in m.columns:
            m[c] = m[c].where(m[c] > 0)
    return m


def _value_at(s: pd.Series, ts: pd.Timestamp, lookback: int = 0):
    """Valor de `s` en `ts` o, si falta, el último dato de los `lookback` meses previos.

    Devuelve (valor, mes usado) o (None, None).
    """
    for k in range(lookback + 1):
        t = _add_months(ts, -k)
        if t in s.index and pd.notna(s.loc[t]):
            return float(s.loc[t]), t
    return None, None


def load_sbs_rates(path: Path | None = None, notes: list[str] | None = None) -> pd.DataFrame | None:
    """Tasas activas de operaciones nuevas de la SBS: banca múltiple, columna «Promedio», MN.

    Lee `descargas-sbs/data/processed/tasas_activas.parquet` (solo lectura). Devuelve un panel
    mensual (inicio de mes) con columnas `sbs_<tipo>`, o None si el archivo no existe o no se puede
    leer. Si hay más de un promedio por mes y tipo, los promedia. Los avisos van a `notes`.
    """
    notes = [] if notes is None else notes
    path = SBS_RATES if path is None else Path(path)
    if not path.exists():
        notes.append("Aviso: tasas de operaciones nuevas de la SBS: no se encontró la tabla; se omiten.")
        return None
    try:
        t = pd.read_parquet(path, columns=["periodo", "subsistema", "es_promedio", "tipo_credito",
                                           "subproducto", "tasa", "moneda"])
        for c in ("subsistema", "tipo_credito", "subproducto", "moneda"):
            t[c] = t[c].astype(str)
        t = t[(t["subsistema"] == SBS_SUBSYSTEM) & t["es_promedio"].astype(bool)
              & (t["subproducto"] == "total") & (t["moneda"] == "MN")]
        if t.empty:
            notes.append("Aviso: tasas de operaciones nuevas de la SBS: el filtro no deja filas; se omiten.")
            return None
        n_dup = int(t.duplicated(["periodo", "tipo_credito"], keep=False).sum())
        if n_dup:
            notes.append(f"Aviso: tasas de la SBS: {n_dup} filas con más de un promedio por mes y "
                         "tipo; se promedian.")
        w = t.pivot_table(index="periodo", columns="tipo_credito", values="tasa", aggfunc="mean")
        w.index = pd.to_datetime(pd.Index(w.index).astype(int).astype(str), format="%Y%m")
        w.columns = [f"sbs_{c}" for c in w.columns]
    except Exception as exc:  # noqa: BLE001 - la fuente es opcional
        notes.append(f"Aviso: no se pudieron leer las tasas de la SBS ({_err(exc)}); se omiten.")
        return None
    keep = [k for k, *_ in SBS_SERIES if k in w.columns]
    if not keep:
        notes.append("Aviso: la tabla de la SBS no trae los tipos esperados; se omite.")
        return None
    return w[keep].astype(float).sort_index()


def _largest_jump(s: pd.Series):
    """Mayor cambio mensual absoluto fuera de la ventana COVID: (mes, antes, después, Δ)."""
    s = s.dropna()
    dlt = s.diff()
    dlt = dlt[(dlt.index < COVID_FROM) | (dlt.index > COVID_TO)].dropna()
    t = dlt.abs().idxmax()
    return t, float(s.loc[_add_months(t, -1)]), float(s.loc[t]), float(dlt.loc[t])


# ---------------------------------------------------------------------------------------------
# 1. Ciclos
# ---------------------------------------------------------------------------------------------
def find_cycles(ref: pd.Series) -> list[dict]:
    """Ciclos de la tasa de referencia (no necesita statsmodels).

    Firma: `find_cycles(ref: pd.Series) -> list[dict]`.
    - `ref`: tasa de referencia mensual (fin de mes), con índice de fechas; se normaliza a inicio
      de mes y se usa desde `REF_START`.
    - Devuelve una lista ordenada de ciclos con las claves públicas `id`, `tipo` («alza» o
      «recorte»), `inicio` y `fin` («AAAA-MM», primer y último mes con cambio), `ref_antes` (nivel
      del mes previo al inicio), `ref_fin`, `d_ref` (pp), `n_mov` y `en_curso` (solo el último), más
      auxiliares internos que empiezan con «_» (`_start`, `_end`, `_max_pause`, `_since_last`);
      quítelos antes de serializar.

    Regla: un ciclo es una secuencia de cambios del mismo signo; lo corta un cambio de signo
    contrario; las pausas no lo cortan. Única excepción: el recorte de emergencia de
    `COVID_CYCLE_START` (mar-2020) abre un ciclo propio aunque siga a recortes previos.
    """
    ref = ref.dropna().astype(float)
    ref.index = pd.to_datetime(ref.index).to_period("M").to_timestamp()
    ref = ref[~ref.index.duplicated(keep="last")].sort_index()
    ref = ref[ref.index >= REF_START]
    chg = ref.diff()
    moves = chg[(chg.abs() > 1e-9)].dropna()
    cycles: list[dict] = []
    cur = None
    for ts, dv in moves.items():
        sign = 1 if dv > 0 else -1
        new = (cur is None or sign != cur["sign"] or ts == COVID_CYCLE_START)
        if new:
            if cur is not None:
                cycles.append(cur)
            cur = {"sign": sign, "start": ts, "end": ts, "moves": [ts]}
        else:
            cur["end"] = ts
            cur["moves"].append(ts)
    if cur is not None:
        cycles.append(cur)

    last_month = ref.index.max()
    out = []
    for i, c in enumerate(cycles):
        before = float(ref.loc[:_add_months(c["start"], -1)].iloc[-1])
        end_level = float(ref.loc[c["end"]])
        y0, y1 = c["start"].year, c["end"].year
        tipo = "alza" if c["sign"] > 0 else "recorte"
        cid = f"{tipo}-{y0}" if y0 == y1 else f"{tipo}-{y0}-{y1}"
        gaps = [_months_between(a, b) - 1 for a, b in zip(c["moves"][:-1], c["moves"][1:])]
        out.append({
            "id": cid, "tipo": tipo, "inicio": _ym(c["start"]), "fin": _ym(c["end"]),
            "ref_antes": _r(before, 2), "ref_fin": _r(end_level, 2),
            "d_ref": _r(end_level - before, 2), "n_mov": len(c["moves"]),
            "en_curso": i == len(cycles) - 1,
            # auxiliares internos (se quitan antes de devolver)
            "_start": c["start"], "_end": c["end"], "_max_pause": max(gaps) if gaps else 0,
            "_since_last": _months_between(c["end"], last_month),
        })
    ids = [c["id"] for c in out]
    if len(set(ids)) != len(ids):
        raise ValueError("Identificadores de ciclo repetidos")
    return out


# ---------------------------------------------------------------------------------------------
# 2. Traspaso por ciclo
# ---------------------------------------------------------------------------------------------
def cycle_passthrough(m: pd.DataFrame, cycles: list[dict], series=None) -> list[dict]:
    """Cambio de cada tasa entre el mes previo al ciclo y el fin del ciclo + 6 meses.

    El mes de medición se acota al mes previo al siguiente ciclo y al último dato de la tasa.
    Si la serie empieza dentro del ciclo, el ciclo es «parcial»: se mide desde el primer dato y
    el ratio se calcula frente al cambio de la referencia desde ese mismo mes. Para las tasas de
    la SBS se omiten los ciclos anteriores a la serie.
    """
    series = SERIES if series is None else series
    ref = m[REF]
    rows = []
    for i, c in enumerate(cycles):
        start, end = c["_start"], c["_end"]
        prev = _add_months(start, -1)
        target = _add_months(end, LAG_AFTER_CYCLE)
        if i + 1 < len(cycles):
            target = min(target, _add_months(cycles[i + 1]["_start"], -1))
        d_ref = c["d_ref"]
        for k, label, grupo, mon, _, flag in series:
            if k not in m.columns:
                continue
            s = m[k]
            look = 2 if flag == "cd" else 0
            first = s.dropna().index.min()
            last = s.dropna().index.max()
            if k.startswith("sbs_") and (pd.isna(first) or first > end):
                continue
            meas = min(target, last) if pd.notna(last) else target
            a, a_t = _value_at(s, prev, look)
            partial = False
            cyc_dref = d_ref
            if a is None and pd.notna(first) and prev < first <= end:
                a, a_t = float(s.loc[first]), first
                partial = True
                cyc_dref = float(ref.loc[c["_end"]]) - float(ref.loc[first])
            b, b_t = (None, None)
            if pd.notna(last) and meas >= start:
                b, b_t = _value_at(s, meas, look)
                if b_t is not None and b_t < start:
                    b, b_t = None, None
            notes = []
            d = ratio = None
            if partial and b is not None:
                notes.append(f"Ciclo parcial: la serie empieza en {_mes(first)}; se mide desde ahí, "
                             f"frente a un cambio de la referencia de {_f(cyc_dref, sign=True)} pp.")
            if a is None or b is None:
                if pd.notna(first) and first <= prev and b is None and pd.notna(last) and last < start:
                    notes.append(f"Sin datos suficientes después del ciclo para medirlo (último "
                                 f"dato: {_mes(last)}).")
                elif flag == "cd":
                    notes.append("Sin colocación de CD en ese plazo cerca de esas fechas.")
                elif pd.isna(first):
                    notes.append("Sin datos de esta serie.")
                elif first > end:
                    notes.append(f"La serie empieza después de este ciclo (primer dato: "
                                 f"{_mes(first)}).")
                elif b is None and pd.notna(last) and last < start:
                    notes.append(f"Sin datos suficientes después del ciclo para medirlo (último "
                                 f"dato: {_mes(last)}).")
                elif a is None:
                    notes.append(f"Sin dato en {_mes(prev)}, el mes previo al ciclo.")
                else:
                    notes.append(f"Sin dato en {_mes(meas)}, el mes de medición.")
            else:
                d = b - a
                if abs(cyc_dref) < SMALL_DREF:
                    notes.append(f"La referencia cambió solo {_f(abs(cyc_dref))} pp: el ratio no "
                                 "se interpreta.")
                else:
                    ratio = d / cyc_dref
                if flag == "cd" and (a_t != prev or b_t != meas):
                    notes.append("Sin colocación de CD en ese plazo en el mes exacto: se usa el "
                                 "último mes con colocación (hasta 2 meses antes).")
                if c["_start"] == COVID_CYCLE_START and grupo == "activa":
                    notes.append("2020: los créditos con garantía estatal (Reactiva Perú) bajaron "
                                 "las tasas de forma excepcional; no es traspaso normal.")
                if flag in RISK_FLAGS:
                    notes.append("Esta tasa depende sobre todo del riesgo y de los costos "
                                 "operativos, no de la referencia: no se calcula el ratio.")
                    ratio = None
                if flag == "sbs_pequenas":
                    notes.append("En pequeñas empresas pesan más el riesgo y los costos que en "
                                 "las grandes: leer el ratio con cautela.")
                if flag in BREAKS and a_t < BREAKS[flag] <= b_t:
                    brk = BREAKS[flag]
                    notes.append(f"Incluye el salto de la serie entre {_mes(_add_months(brk, -1))} "
                                 f"y {_mes(brk)} (posible quiebre de serie).")
                if flag in CAP_FLAGS and b_t >= CAP_FROM:
                    notes.append(CAP_NOTE)
                if grupo == "bonos":
                    notes.append("El bono a 10 años depende también de las tasas externas y del "
                                 "riesgo país.")
                if flag == "composicion":
                    notes.append("Promedio de todos los tipos de crédito: lo mueve el peso de "
                                 "cada tipo, no solo el traspaso. Sin ratio.")
                    ratio = None
                if flag == "me":
                    notes.append("Tasa en dólares: responde sobre todo a la tasa de la Fed, no a "
                                 "la referencia del BCRP.")
                if c["_max_pause"] >= LONG_PAUSE:
                    notes.append(f"Ciclo con pausas de hasta {c['_max_pause']} meses: el cambio "
                                 "recoge también otros factores.")
                if c["en_curso"] and b_t == last and meas < target:
                    notes.append("Medido con el último dato disponible.")
            rows.append({
                "ciclo": c["id"], "k": k, "antes": _r(a, 2), "fin": _r(b, 2),
                "d": _r(d, 2), "ratio": _r(ratio, 2),
                "medido_en": _ym(b_t) if b_t is not None else _ym(meas),
                "rezago": _months_between(end, b_t if b_t is not None else meas),
                "nota": " ".join(notes) if notes else None,
            })
    return rows


# ---------------------------------------------------------------------------------------------
# 3. ECM / ARDL
# ---------------------------------------------------------------------------------------------
def _design(y: pd.Series, x: pd.Series, p: int, q: int, dummies: dict[str, pd.Series]):
    """Matriz del ECM condicional (ARDL en forma de corrección de errores).

    Δy_t = c + a·y_{t-1} + b·x_{t-1} + Σ_{i=1..p} φ_i Δy_{t-i} + Σ_{j=0..q} ψ_j Δx_{t-j} + dummies
    """
    dy, dx = y.diff(), x.diff()
    cols = {"const": pd.Series(1.0, index=y.index), "y_l1": y.shift(1), "x_l1": x.shift(1)}
    for i in range(1, p + 1):
        cols[f"dy_l{i}"] = dy.shift(i)
    for j in range(0, q + 1):
        cols[f"dx_l{j}"] = dx.shift(j)
    for name, s in dummies.items():
        cols[name] = s
    X = pd.DataFrame(cols)
    return dy.rename("dy"), X


def _complete_rows(y: pd.Series, x: pd.Series, flag: str | None, rows: pd.Index) -> pd.Index:
    """Meses de `rows` con dato en todos los regresores del modelo más grande (p = q = MAX_LAG)."""
    dy, X = _design(y, x, MAX_LAG, MAX_LAG, _dummies(y.index, flag, "step"))
    ok = dy.loc[rows].notna() & X.loc[rows].notna().all(axis=1)
    return rows[ok.to_numpy()]


MIN_ECM_N = 60   # meses mínimos con todos los datos para estimar el modelo


def _covid_step(index) -> pd.Series:
    return pd.Series(((index >= COVID_FROM) & (index <= COVID_TO)).astype(float), index=index)


def _dummies(index, flag: str | None, covid: str) -> dict[str, pd.Series]:
    """Dummies según el tratamiento de la COVID ('step', 'impulse', 'none') y la serie."""
    dm: dict[str, pd.Series] = {}
    if covid == "step":
        dm["covid"] = _covid_step(index)
    elif covid == "impulse":
        for t in pd.date_range(COVID_FROM, COVID_TO, freq="MS"):
            dm[f"imp_{_ym(t)}"] = pd.Series((index == t).astype(float), index=index)
    if covid == "step_post":
        dm["covid"] = _covid_step(index)
        dm["post"] = pd.Series((index >= POST_SHIFT_FROM).astype(float), index=index)
    if flag in BREAKS:
        brk = BREAKS[flag]
        dm["break_step"] = pd.Series((index >= brk).astype(float), index=index)
        dm["break_imp"] = pd.Series((index == brk).astype(float), index=index)
    return dm


def _nw_lags(n: int) -> int:
    return int(np.floor(4 * (n / 100.0) ** (2.0 / 9.0)))


def _fit(dy: pd.Series, X: pd.DataFrame, rows: pd.Index):
    import statsmodels.api as sm
    yy, XX = dy.loc[rows], X.loc[rows]
    keep = [c for c in XX.columns if c == "const" or XX[c].abs().sum() > 0]
    XX = XX[keep]
    ols = sm.OLS(yy.values, XX.values).fit()
    hac = sm.OLS(yy.values, XX.values).fit(cov_type="HAC",
                                           cov_kwds={"maxlags": _nw_lags(len(yy))})
    return ols, hac, list(XX.columns)


def _long_run(params: np.ndarray, cov: np.ndarray, names: list[str]):
    ia, ib = names.index("y_l1"), names.index("x_l1")
    a, b = params[ia], params[ib]
    theta = -b / a
    g = np.zeros(len(params))
    g[ia], g[ib] = b / a ** 2, -1.0 / a
    se = float(np.sqrt(g @ cov @ g))
    return float(theta), se


def _multipliers(P: np.ndarray, names: list[str], p: int, q: int, horizon: int) -> np.ndarray:
    """Respuesta acumulada de y a un alza permanente de 1 pp de x en t = 0.

    `P` tiene forma (n_draws, n_params). Devuelve (n_draws, horizon + 1).
    """
    n = P.shape[0]
    a = P[:, names.index("y_l1")]
    b = P[:, names.index("x_l1")]
    phi = np.column_stack([P[:, names.index(f"dy_l{i}")] for i in range(1, p + 1)]) if p else np.zeros((n, 0))
    psi = np.column_stack([P[:, names.index(f"dx_l{j}")] for j in range(0, q + 1)])
    y_hist = np.zeros((n, horizon + 1))
    dy_hist = np.zeros((n, horizon + 1))
    for t in range(horizon + 1):
        y_prev = y_hist[:, t - 1] if t > 0 else np.zeros(n)
        x_prev = 1.0 if t > 0 else 0.0
        val = a * y_prev + b * x_prev
        for i in range(1, p + 1):
            if t - i >= 0:
                val = val + phi[:, i - 1] * dy_hist[:, t - i]
        if t <= q:
            val = val + psi[:, t]          # Δx_{t-j} = 1 solo cuando j = t
        dy_hist[:, t] = val
        y_hist[:, t] = y_prev + val
    return y_hist


def _first_reach(path: np.ndarray, target: float) -> int | None:
    if not np.isfinite(target) or target <= 0:
        return None
    idx = np.where(path >= target)[0]
    return int(idx[0]) if idx.size else None


def _estimate(y, x, flag, rows, p, q, covid):
    dm = _dummies(y.index, flag, covid)
    dy, X = _design(y, x, p, q, dm)
    ols, hac, names = _fit(dy, X, rows)
    theta, se = _long_run(hac.params, hac.cov_params(), names)
    return {"ols": ols, "hac": hac, "names": names, "theta": theta, "se": se, "n": len(rows),
            "start": rows.min()}


def ecm_for_series(m: pd.DataFrame, k: str, flag: str | None) -> dict:
    """Estima el ECM principal y sus variantes de robustez para una tasa.

    Usa solo los meses con todos los datos del modelo más grande (`_complete_rows`). Lanza
    ValueError si quedan menos de `MIN_ECM_N` meses.
    """
    from statsmodels.stats.diagnostic import breaks_cusumolsresid
    from statsmodels.tsa.stattools import coint
    y = m[k].astype(float)
    x = m[REF].astype(float)
    last_y = y.dropna().index.max()
    first = _add_months(max(SAMPLE_START, y.dropna().index.min()), MAX_LAG + 1)
    rows = y.index[(y.index >= first) & (y.index <= last_y)]
    n_gaps = len(rows)
    rows = _complete_rows(y, x, flag, rows)
    n_gaps -= len(rows)
    if len(rows) < MIN_ECM_N:
        raise ValueError(f"muestra insuficiente ({len(rows)} meses con todos los datos)")
    # Elegir rezagos por BIC en una muestra común.
    best = None
    for p in range(0, MAX_LAG + 1):
        for q in range(0, MAX_LAG + 1):
            dm = _dummies(y.index, flag, "step")
            dy, X = _design(y, x, p, q, dm)
            ols, _, _ = _fit(dy, X, rows)
            if best is None or ols.bic < best[0] - 1e-12:
                best = (ols.bic, p, q)
    _, p, q = best
    main = _estimate(y, x, flag, rows, p, q, "step")
    names = main["names"]
    hac, ols = main["hac"], main["ols"]
    a = float(hac.params[names.index("y_l1")])
    # Prueba de límites (F sobre a = b = 0 y t de a; errores clásicos, como en PSS).
    R = np.zeros((2, len(names)))
    R[0, names.index("y_l1")] = 1
    R[1, names.index("x_l1")] = 1
    f_pss = float(np.squeeze(ols.f_test(R).fvalue))
    t_pss = float(ols.tvalues[names.index("y_l1")])
    # Engle-Granger sobre niveles en la misma muestra (complementaria; no admite dummies).
    lev = pd.concat([y, x], axis=1).loc[rows].dropna()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        eg_p = float(coint(lev.iloc[:, 0], lev.iloc[:, 1], trend="c")[1])
    # CUSUM de residuos OLS (Ploberger y Krämer).
    cus_p = float(breaks_cusumolsresid(ols.resid, ddof=len(names))[1])
    # Variantes.
    var = {}
    var["impulse"] = _estimate(y, x, flag, rows, p, q, "impulse")
    var["none"] = _estimate(y, x, flag, rows, p, q, "none")
    pre_rows = rows[rows <= PRE_TO]
    post_rows = rows[rows >= POST_FROM]
    for key, rr in (("pre", pre_rows), ("post", post_rows)):
        if len(rr) >= MIN_SUBSAMPLE_N:
            var[key] = _estimate(y, x, flag, rr, p, q, "none")
        else:
            var[key] = {"theta": np.nan, "se": np.nan, "n": len(rr),
                        "start": rr.min() if len(rr) else None}
    pre_lab, post_lab = _span(pre_rows), _span(post_rows)
    var["shift"] = _estimate(y, x, flag, rows, p, q, "step_post")
    first_valid = y.dropna().index.min()
    if first_valid < SAMPLE_START:
        lrows = y.index[(y.index >= _add_months(max(first_valid, REF_START), MAX_LAG + 1))
                        & (y.index <= last_y)]
        lrows = _complete_rows(y, x, flag, lrows)
        if len(lrows) >= MIN_ECM_N:
            var["long"] = _estimate(y, x, flag, lrows, p, q, "step")
    # Multiplicadores y bandas por simulación paramétrica (normal con la covarianza HAC).
    P0 = hac.params[None, :]
    path_long = _multipliers(P0, names, p, q, LONG_HORIZON)[0]
    rng = np.random.default_rng(SEED)
    draws = rng.multivariate_normal(hac.params, hac.cov_params(), size=N_SIM, method="svd")
    sims = _multipliers(draws, names, p, q, HORIZON)
    lo_band = np.percentile(sims, 2.5, axis=0)
    hi_band = np.percentile(sims, 97.5, axis=0)
    theta, se = main["theta"], main["se"]
    m50 = _first_reach(path_long, 0.5 * theta)
    m90 = _first_reach(path_long, 0.9 * theta)
    # Proyecciones locales (robustez).
    lp = local_projection(m, k)
    b24, s24, _ = lp[24]
    e24 = float(path_long[24])
    lp_same = None if b24 is None else bool(
        abs(b24 - e24) <= 0.25 or (b24 - 1.96 * s24 <= e24 <= b24 + 1.96 * s24))
    # Criterios de aceptación (prueba de límites completa: F y t sobre el umbral I(1) al 5 %).
    fails = []
    bounds_txt = (f"prueba de límites: F = {_f(f_pss)}, t = {_f(t_pss)}; umbrales I(1) al 5 %: "
                  f"{_f(PSS_F_5[1])} y {_f(PSS_T_5[1])}")
    if f_pss > PSS_F_5[1] and t_pss < PSS_T_5[1]:
        pass
    elif f_pss < PSS_F_5[0] or t_pss > PSS_T_5[0]:
        fails.append(f"sin relación de largo plazo ({bounds_txt})")
    else:
        fails.append(f"relación de largo plazo no concluyente ({bounds_txt})")
    if not (-2 < a < 0):
        fails.append(f"coeficiente de ajuste fuera de rango ({_f(a)})")
    if cus_p < 0.05:
        fails.append(f"la prueba CUSUM rechaza la estabilidad (p = {_f(cus_p, 3)})")
    gap_sub = abs(var["pre"]["theta"] - var["post"]["theta"])
    if min(len(pre_rows), len(post_rows)) < MIN_SUBSAMPLE_N:
        fails.append(f"submuestras demasiado cortas para probar estabilidad ({len(pre_rows)} y "
                     f"{len(post_rows)} meses)")
    elif not gap_sub <= MAX_SUBSAMPLE_GAP:
        fails.append(f"el traspaso cambia entre submuestras ({_f(var['pre']['theta'])} de "
                     f"{pre_lab} y {_f(var['post']['theta'])} de {post_lab})")
    gap_cov = abs(var["impulse"]["theta"] - theta)
    if not gap_cov <= MAX_COVID_GAP:
        fails.append(f"depende de cómo se traten {_mes(COVID_FROM)} a {_mes(COVID_TO)} "
                     f"({_f(theta)} con escalón y {_f(var['impulse']['theta'])} excluyendo esos "
                     "meses)")
    p_min, p_max = float(path_long[: HORIZON + 1].min()), float(path_long[: HORIZON + 1].max())
    if p_min < PATH_FLOOR or p_max > PATH_OVERSHOOT[0] * abs(theta) + PATH_OVERSHOOT[1]:
        fails.append(f"trayectoria poco creíble a 0-24 meses (va de {_f(p_min)} a {_f(p_max)})")
    if not (BETA_RANGE[0] <= theta <= BETA_RANGE[1]):
        fails.append(f"traspaso de largo plazo fuera de rango plausible ({_f(theta)})")
    ok = not fails
    note_parts = []
    if flag in FORCED_NOT_OK:
        ok = False
        note_parts.append(FORCED_NOT_OK[flag])
    if fails:
        note_parts.append("No pasa las pruebas: " + "; ".join(fails) + ".")
    if ok and m90 is not None and m90 > HORIZON:
        note_parts.append(f"Ajuste lento: el 90 % del traspaso llega a los {m90} meses.")
    if theta > 0 and m90 is None:
        note_parts.append(f"El modelo no alcanza el 90 % del traspaso de largo plazo en "
                          f"{LONG_HORIZON} meses.")
    if ok and lp_same is False:
        note_parts.append(f"Las proyecciones locales dan un traspaso acumulado de {_f(b24)} a 24 "
                          f"meses, frente a {_f(e24)} de este modelo; las submuestras dan "
                          f"{_f(var['pre']['theta'])} ({pre_lab}) y {_f(var['post']['theta'])} "
                          f"({post_lab}). Tomar el valor con cautela.")
    lo_ci, hi_ci = theta - 1.96 * se, theta + 1.96 * se
    sub = [var["pre"]["theta"], var["post"]["theta"]]
    if ok and lp_same is not False and all(np.isfinite(sub)):
        side = ("por encima" if min(sub) > hi_ci else "por debajo" if max(sub) < lo_ci else None)
        if side:
            note_parts.append(f"Las dos submuestras dan {_f(sub[0])} ({pre_lab}) y {_f(sub[1])} "
                              f"({post_lab}), ambas {side} del intervalo del modelo conjunto: el "
                              "margen sobre la referencia cambió entre periodos y el valor conjunto "
                              "puede estar sesgado. Los ratios por ciclo son la referencia.")
    if n_gaps:
        note_parts.append(f"Se excluyen {_meses(n_gaps)} sin todos los datos del modelo.")
    return {
        "k": k, "p": p, "q": q, "theta": theta, "se": se, "a": a,
        "impact": float(hac.params[names.index("dx_l0")]),
        "m50": m50, "m90": m90, "rows": rows, "n": len(rows),
        "f_pss": f_pss, "t_pss": t_pss, "eg_p": eg_p, "cusum_p": cus_p,
        "variants": {kk: (vv["theta"], vv["se"], vv["n"], vv["start"]) for kk, vv in var.items()},
        "path": path_long[: HORIZON + 1], "lo": lo_band, "hi": hi_band,
        "ok": ok, "fails": fails, "nota": " ".join(note_parts) if note_parts else None,
        "lp": lp, "lp_same": lp_same, "pre_lab": pre_lab, "post_lab": post_lab,
    }


# ---------------------------------------------------------------------------------------------
# 3b. Proyecciones locales (Jordà), como robustez
# ---------------------------------------------------------------------------------------------
def local_projection(m: pd.DataFrame, k: str, horizons=(6, 12, 24)) -> dict:
    """Traspaso acumulado por proyecciones locales con variable instrumental.

    Para cada horizonte h: (y_{t+h} − y_{t−1}) = β_h (x_{t+h} − x_{t−1}) + controles, con Δx_t
    como instrumento. β_h es el cambio acumulado de la tasa por cada punto que se acumuló en la
    referencia hasta h. Se excluyen las observaciones cuya ventana [t − 1 − LP_CONTROLS, t + h]
    (base y controles incluidos) toca la ventana COVID.
    """
    y = m[k].astype(float)
    x = m[REF].astype(float)
    dy, dx = y.diff(), x.diff()
    out = {}
    for h in horizons:
        df = pd.DataFrame({
            "dep": y.shift(-h) - y.shift(1),
            "endo": x.shift(-h) - x.shift(1),
            "z": dx,
        })
        for L in range(1, LP_CONTROLS + 1):
            df[f"dx_l{L}"] = dx.shift(L)
            df[f"dy_l{L}"] = dy.shift(L)
        idx = df.index
        t_end = idx + pd.DateOffset(months=h)
        t_base = idx - pd.DateOffset(months=1 + LP_CONTROLS)
        overlap = (t_end >= COVID_FROM) & (t_base <= COVID_TO)
        start = max(SAMPLE_START, y.dropna().index.min())
        df = df[(idx >= _add_months(start, LP_CONTROLS + 1)) & ~overlap].dropna()
        if len(df) < 40:
            out[h] = (None, None, len(df))
            continue
        W = np.column_stack([np.ones(len(df))] + [df[c].values for c in df.columns
                                                  if c.startswith(("dx_l", "dy_l"))])
        X = np.column_stack([df["endo"].values, W])
        Z = np.column_stack([df["z"].values, W])
        yv = df["dep"].values
        ZX = Z.T @ X
        beta = np.linalg.solve(ZX, Z.T @ yv)
        u = yv - X @ beta
        g = Z * u[:, None]
        L = h + 1
        S = g.T @ g
        for lag in range(1, L + 1):
            w = 1 - lag / (L + 1)
            G = g[lag:].T @ g[:-lag]
            S += w * (G + G.T)
        inv = np.linalg.inv(ZX)
        V = inv @ S @ inv.T
        out[h] = (float(beta[0]), float(np.sqrt(V[0, 0])), len(df))
    return out


# ---------------------------------------------------------------------------------------------
# 4. Textos de método
# ---------------------------------------------------------------------------------------------
def _method_texts(cycles, info: dict, sources_txt: str | None = None) -> dict:
    """Textos de `metodo`. `info` trae los meses reales de cada muestra (ver build_transmission)."""
    last = cycles[-1]
    since = last["_since_last"]
    curso = ""
    if last["en_curso"]:
        span = (_mes(last["_start"]) if last["_start"] == last["_end"]
                else f"{_mes(last['_start'])} a {_mes(last['_end'])}")
        curso = (f"El último ciclo ({span}) sigue abierto porque no ha habido un cambio de signo "
                 "contrario")
        curso += (f"; la tasa lleva {_meses(since)} sin cambios (hasta {_mes(info['ref_last'])})."
                  if since > 0 else ".")
    sbs_ecm = (f" Las tasas de operaciones nuevas de la SBS se estiman desde "
               f"{_mes(info['sbs_ecm_first'])}, con una muestra más corta."
               if info.get("sbs_ecm_first") is not None else "")
    ecm_from = (f"desde {_mes(info['bcrp_ecm_first'])}" if info.get("bcrp_ecm_first") is not None
                else "")
    sbs_range = (f"; tasas de operaciones nuevas de la SBS de {_mes(info['sbs_first'])} a "
                 f"{_mes(info['sbs_last'])}" if info.get("sbs_first") is not None else "")
    types_txt = ""
    if info.get("types_first") is not None and info.get("bcrp_ecm_first") is not None:
        types_txt = (f" Las tasas por tipo de crédito del BCRP, la preferencial, la FTAMN y la "
                     f"FTIPMN existen desde {_mes(info['types_first'])}; por los rezagos, el modelo "
                     f"las usa desde {_mes(info['bcrp_ecm_first'])}")
        types_txt += (f" (las de la SBS, desde {_mes(info['sbs_ecm_first'])})."
                      if info.get("sbs_ecm_first") is not None else ".")
    brk = f"{_mes(PYME_BREAK)} en el BCRP"
    if info.get("sbs_first") is not None:
        brk += f" y {_mes(SBS_MICRO_BREAK)} en la microempresa de la SBS"
    return {
        "ciclos": (
            "Un ciclo es una secuencia de cambios de la tasa de referencia en la misma dirección. "
            "Termina cuando el BCRP mueve la tasa en sentido contrario; las pausas no lo cortan. "
            f"Única excepción: el recorte de emergencia de {_mes(COVID_CYCLE_START)}, por la "
            "pandemia, abre un ciclo propio aunque siga a recortes previos. Se usa la tasa de fin "
            f"de mes desde {_mes(info['ref_first'])}, cuando empezó el régimen de tasa de "
            "referencia. " + curso).strip(),
        "traspaso_ciclo": (
            f"Es la medida principal del tablero. Para cada ciclo se compara cada tasa en el mes "
            f"previo al primer cambio con su valor {LAG_AFTER_CYCLE} meses después del último "
            f"cambio (o antes, si empieza otro ciclo o si no hay datos más recientes). El ratio "
            f"divide ese cambio entre el de la referencia: 1 significa que la tasa se movió lo "
            f"mismo. Es un cociente de cambios, no un efecto: incluye también lo que pasó con el "
            f"riesgo, las tasas externas y la competencia en el mismo periodo. No se calcula el "
            f"ratio cuando la referencia cambió menos de {SMALL_DREF:.0f} punto, cuando no hay "
            "datos para el ciclo, ni para consumo, microempresa y la FTAMN, que dependen sobre "
            "todo del riesgo, de los costos o del peso de cada tipo de crédito. La tasa de "
            f"pequeña y microempresa tiene además un salto de serie ({brk}). En 2020 las tasas "
            "a empresas cayeron también por los créditos con garantía estatal (Reactiva Perú). "
            "Las tasas en dólares siguen sobre todo a la Fed y se muestran solo como contraste."),
        "ecm": (
            "Prueba de robustez de los ratios por ciclo. El traspaso de largo plazo es una "
            "asociación estimada: cuánto se mueve cada tasa, una vez completado el ajuste, por "
            "cada punto que cambia la referencia, en un modelo de corrección de errores mensual "
            "de una sola ecuación (cada mes la tasa corrige parte de su distancia al equilibrio). "
            "El modelo toma la referencia como dada; no mide un efecto causal. Usa datos "
            f"{ecm_from} y errores robustos (Newey-West). Los meses de {_mes(COVID_FROM)} a "
            f"{_mes(COVID_TO)} se controlan con una variable que permite un nivel distinto en la "
            "pandemia, porque Reactiva Perú y los repos con garantía estatal bajaron las tasas "
            "fuera de lo normal. Se marca como no confiable la tasa que no muestra una relación "
            "de largo plazo (o cuya prueba es no concluyente), cambia entre antes y después de la "
            "pandemia, depende de cómo se trate la pandemia o tiene una trayectoria poco creíble "
            "en los primeros 24 meses. Consumo, microempresa y la FTAMN se estiman pero no se "
            "publican como traspaso: dependen sobre todo del riesgo, de los costos o del peso de "
            "cada tipo de crédito. Las tasas en dólares y los CD del BCRP (con meses sin "
            "colocación) no entran." + sbs_ecm),
        "respuesta": (
            "Multiplicadores dinámicos del modelo de corrección de errores: cuánto se movería "
            "cada tasa, mes a mes, si la referencia subiera 1 punto de forma permanente. El modelo "
            "supone que la referencia no responde a las demás tasas, así que no es la respuesta a "
            f"un choque de política identificado. La banda es el intervalo del 95 % ({N_SIM} "
            "simulaciones de los coeficientes). Solo se muestran las tasas que pasaron las "
            "pruebas."),
        "muestra": (
            f"Tasa de referencia mensual de {_mes(info['ref_first'])} a {_mes(info['ref_last'])}; "
            f"tasas del BCRP hasta {_mes(info['bcrp_last'])}" + sbs_range + "." + types_txt +
            " Se excluyen la TAMN y la TIPMN (promedios de saldos, con efecto composición) y los "
            "tramos de bonos del Tesoro (meses sin colocación). Fuentes: BCRPData y SBS; cálculos "
            "propios."),
        "fuentes_tasas": sources_txt or (
            "Las tasas por tipo de crédito son las que publica el BCRP en BCRPData (fuente: SBS). "
            "No se pudieron leer las tasas de operaciones nuevas de la SBS."),
    }


# ---------------------------------------------------------------------------------------------
# Interfaz principal
# ---------------------------------------------------------------------------------------------
def build_transmission(m: pd.DataFrame, d: pd.DataFrame | None = None) -> dict:
    """Calcula ciclos, traspaso por ciclo, ECM, respuestas y controles.

    `m`: panel mensual (índice de fecha, inicio de mes; columnas = nombre_corto).
    `d`: panel diario (opcional; se usa para verificar la tasa de referencia de fin de mes).
    """
    m = _clean_panel(m)
    if REF not in m.columns:
        raise KeyError(f"Falta {REF} en el panel mensual")
    controls: list[str] = []
    series = list(SERIES)
    sbs = load_sbs_rates(notes=controls)
    if sbs is not None:
        if sbs.index.max() > m.index.max():
            controls.append(f"Tasas de la SBS: llegan a {_mes(sbs.index.max())}, después del último "
                            f"mes del panel ({_mes(m.index.max())}); esos meses no se usan.")
        m = m.join(sbs, how="left")
        series += [x for x in SBS_SERIES if x[0] in sbs.columns]
        controls.append(f"Tasas de operaciones nuevas de la SBS (banca múltiple, columna «Promedio», "
                        f"MN): {sbs.shape[1]} tipos, de {_mes(sbs.index.min())} a "
                        f"{_mes(sbs.index.max())}, {int(sbs.notna().all(axis=1).sum())} meses "
                        "completos.")
    ref = m[REF]

    # --- Ciclos
    cycles = find_cycles(ref)
    total = sum(c["d_ref"] for c in cycles)
    r0 = float(ref.loc[_add_months(REF_START, 0)])
    rN = float(ref.dropna().iloc[-1])
    if abs(r0 + total - rN) > 1e-6:
        raise ValueError("Los cambios por ciclo no suman el cambio total de la referencia")
    n_moves = int((ref.dropna().diff().abs() > 1e-9).sum())
    controls.append(f"Ciclos: {len(cycles)}, con {n_moves} cambios de la referencia desde "
                    f"{_mes(ref.dropna().index.min())}. "
                    f"La suma de los cambios por ciclo ({_f(total, sign=True)} pp) cuadra con el "
                    f"paso de {_f(r0)} % a {_f(rN)} %.")
    if d is not None and REF_DAILY in d.columns:
        dd = d[REF_DAILY].dropna()
        dd.index = pd.to_datetime(dd.index)
        eom = dd.groupby(dd.index.to_period("M")).last()
        eom.index = eom.index.to_timestamp()
        comp = pd.concat([eom, ref], axis=1, join="inner").dropna()
        n_diff = int((comp.iloc[:, 0] - comp.iloc[:, 1]).abs().gt(1e-9).sum())
        dchg = dd.diff()
        dchg = dchg[dchg.abs() > 1e-9]
        per_month = dchg.groupby(dchg.index.to_period("M")).size()
        multi = int((per_month > 1).sum())
        controls.append(f"Referencia diaria frente a mensual: el último dato del mes coincide en "
                        f"{len(comp) - n_diff} de {len(comp)} meses; hay {len(dchg)} cambios "
                        f"diarios y {multi} meses con más de un cambio, así que la serie mensual "
                        "no pierde movimientos.")

    # --- Catálogo de tasas
    tasas = []
    for k, label, grupo, mon, _, _ in series:
        if k not in m.columns or m[k].dropna().empty:
            controls.append(f"Aviso: falta la serie {k}; se omite.")
            continue
        s = m[k].dropna()
        tasas.append({"k": k, "label": label, "grupo": grupo, "mon": mon,
                      "desde": _ym(s.index.min()), "hasta": _ym(s.index.max())})
    present = {t["k"] for t in tasas}
    name = {t["k"]: f"{t['label']} ({t['mon']})" for t in tasas}

    # --- Traspaso por ciclo
    tc = [r for r in cycle_passthrough(m, cycles, series) if r["k"] in present]

    # Control del quiebre de pequeña y microempresa.
    jump = m["tasa_bancos_pyme_hasta360_mn"].diff() if "tasa_bancos_pyme_hasta360_mn" in present else None
    if jump is not None and PYME_BREAK in jump.index and pd.notna(jump.loc[PYME_BREAK]):
        j = float(jump.loc[PYME_BREAK])
        others = float(jump.drop(PYME_BREAK).abs().max())
        controls.append(f"Pequeña y microempresa hasta 360 días: salto de {_f(j, sign=True)} pp en "
                        f"{_mes(PYME_BREAK)}; el mayor cambio mensual en el resto de la serie es de "
                        f"{_f(others)} pp. Se trata como posible quiebre de serie: escalón en el "
                        "modelo y sin ratio en el ciclo afectado. BCRPData no documenta la causa.")

    jumps = []
    for k in ("tasa_bancos_pyme_hasta360_mn", "sbs_micro", "sbs_pequenas"):
        if k in present:
            t, v0, v1, dv = _largest_jump(m[k])
            jumps.append(f"{name[k]}: {_f(v0)} % ({_mes(_add_months(t, -1))}) → {_f(v1)} % "
                         f"({_mes(t)}), {_f(dv, sign=True)} pp")
    if len(jumps) > 1:
        controls.append(f"Mayor cambio mensual fuera de {_mes(COVID_FROM)} a {_mes(COVID_TO)}, "
                        "por fuente: " + "; ".join(jumps)
                        + ". El salto de la microempresa está en las dos fuentes, pero no en el "
                        "mismo mes; la tasa de pequeñas empresas de la SBS no salta. No se "
                        "atribuye causa.")

    sources_txt = None
    pairs = [("tasa_bancos_corporativo_hasta360_mn", "sbs_corporativo"),
             ("tasa_bancos_grandes_empresas_hasta360_mn", "sbs_grandes"),
             ("tasa_bancos_medianas_empresas_hasta360_mn", "sbs_medianas"),
             ("tasa_bancos_hipotecario_mn", "sbs_hipotecario")]
    if all(a in present and b in present for a, b in pairs):
        corr = {b: float(m[[a, b]].dropna().corr().iloc[0, 1]) for a, b in pairs}
        both = m[[a for a, _ in pairs] + [b for _, b in pairs]].dropna(how="any")
        controls.append(f"Correlación entre la tasa del BCRP y la de operaciones nuevas de la SBS, "
                        f"mismo tipo, de {_mes(both.index.min())} a {_mes(both.index.max())}: "
                        + "; ".join(f"{name[b].split(' (')[0]} {_f(v)}" for b, v in corr.items())
                        + ".")
        # Ventana para el hipotecario: desde el mes previo al penúltimo ciclo (el último ciclo
        # completo de alzas o recortes y el actual).
        win = _add_months(cycles[-2]["_start"], -1) if len(cycles) >= 2 else both.index.min()
        hb = m["tasa_bancos_hipotecario_mn"][m.index >= win].dropna()
        hs = m["sbs_hipotecario"][m.index >= win].dropna()
        s_min_t = hs.loc[:hs.idxmax()].idxmin()
        firm = [corr["sbs_corporativo"], corr["sbs_grandes"]]
        sources_txt = (
            "Hay dos fuentes de tasas activas por tipo de crédito. Las de la SBS son de operaciones "
            "nuevas: el promedio de los préstamos en soles que la banca múltiple otorgó en los "
            "últimos 30 días útiles al cierre del mes. Las del BCRP por tipo de crédito y por "
            "modalidad (BCRPData, con fuente SBS) no traen su metodología en el catálogo de "
            "BCRPData. En los créditos a empresas de hasta 360 días ambas se mueven casi igual: "
            f"la correlación es de {_f(min(firm))} a {_f(max(firm))} en corporativo y grandes "
            f"empresas, y de {_f(corr['sbs_medianas'])} en medianas. La diferencia aparece en el "
            f"hipotecario: desde {_mes(win)} la tasa del BCRP queda entre {_f(hb.min(), 1)} % y "
            f"{_f(hb.max(), 1)} %, mientras la de la SBS sube de {_f(hs.loc[s_min_t], 1)} % "
            f"({_mes(s_min_t)}) a {_f(hs.max(), 1)} % ({_mes(hs.idxmax())}) y baja a "
            f"{_f(hs.iloc[-1], 1)} % ({_mes(hs.index[-1])}); entre ambas la correlación es de "
            f"{_f(corr['sbs_hipotecario'])}. Una posible explicación, no verificada: si las del "
            "BCRP fueran promedios sobre saldos, el saldo de los créditos de corto plazo se "
            "renueva en pocos meses y sigue a las operaciones nuevas, mientras el de los créditos "
            "de vivienda, de largo plazo, no. Para el crédito hipotecario conviene leer la tasa de "
            f"la SBS. Las tasas de la SBS empiezan en {_mes(m['sbs_hipotecario'].dropna().index.min())}.")

    # --- ECM y proyecciones locales (una tasa que falla no tumba las demás)
    ecm_rows, resp_series, agree = [], [], []
    ecm_first = {"bcrp": None, "sbs": None}
    for k, label, grupo, mon, in_ecm, flag in series:
        if not in_ecm or k not in present:
            continue
        try:
            r = ecm_for_series(m, k, flag)
        except Exception as exc:  # noqa: BLE001
            s_k = m[k].dropna()
            controls.append(f"Aviso: no se pudo estimar el modelo de {name[k]} "
                            f"({_err(exc)}); se marca como no confiable.")
            ecm_rows.append({
                "k": k, "beta": None, "lo": None, "hi": None, "impacto": None,
                "m50": None, "m90": None, "desde": _ym(s_k.index.min()),
                "hasta": _ym(s_k.index.max()), "n": 0, "ok": False,
                "nota": "No se pudo estimar el modelo con los datos disponibles.",
            })
            continue
        src = "sbs" if k.startswith("sbs_") else "bcrp"
        if ecm_first[src] is None or r["rows"].min() < ecm_first[src]:
            ecm_first[src] = r["rows"].min()
        ecm_rows.append({
            "k": k, "beta": _r(r["theta"]), "lo": _r(r["theta"] - 1.96 * r["se"]),
            "hi": _r(r["theta"] + 1.96 * r["se"]), "impacto": _r(r["impact"]),
            "m50": r["m50"], "m90": r["m90"],
            "desde": _ym(r["rows"].min()), "hasta": _ym(r["rows"].max()), "n": int(r["n"]),
            "ok": bool(r["ok"]), "nota": r["nota"],
        })
        if r["ok"]:
            resp_series.append({"k": k, "v": [_r(v) for v in r["path"]],
                                "lo": [_r(v) for v in r["lo"]], "hi": [_r(v) for v in r["hi"]]})
        v = r["variants"]
        extra = ""
        if "long" in v:
            extra = f"; muestra larga desde {_mes(v['long'][3])}: {_f(v['long'][0])} (n = {v['long'][2]})"
        controls.append(
            f"Modelo, {name[k]} ({_span(r['rows'])}, n = {r['n']}): rezagos Δy {r['p']} y Δx "
            f"{r['q']} (BIC); β = {_f(r['theta'])} (ee {_f(r['se'])}); ajuste {_f(r['a'])} por mes; "
            f"prueba de límites F = {_f(r['f_pss'])}, t = {_f(r['t_pss'])}; Engle-Granger p = "
            f"{_f(r['eg_p'], 3)}; CUSUM p = {_f(r['cusum_p'], 3)}. β excluyendo {_mes(COVID_FROM)} "
            f"a {_mes(COVID_TO)}: {_f(v['impulse'][0])}; sin control: {_f(v['none'][0])}; con "
            f"escalón desde {_mes(POST_SHIFT_FROM)}: {_f(v['shift'][0])}; {r['pre_lab']}: "
            f"{_f(v['pre'][0])}; {r['post_lab']}: {_f(v['post'][0])}{extra}. "
            f"{'Pasa' if r['ok'] else 'No pasa'}.")
        lp = r["lp"]
        b12, s12, _ = lp[12]
        b24, s24, n24 = lp[24]
        if b24 is None:
            controls.append(f"Proyecciones locales, {name[k]}: muestra insuficiente.")
            continue
        if r["ok"]:
            agree.append(bool(r["lp_same"]))
        controls.append(
            f"Proyecciones locales, {name[k]}: traspaso acumulado de {_f(b12)} a 12 meses "
            f"(ee {_f(s12)}) y de {_f(b24)} a 24 meses (ee {_f(s24)}, n = {n24}); el modelo da "
            f"{_f(float(r['path'][12]))} y {_f(float(r['path'][24]))}: "
            f"{'cuentan la misma historia' if r['lp_same'] else 'difieren'}.")
    if agree:
        controls.append(f"Proyecciones locales frente al modelo, en las tasas que pasan las "
                        f"pruebas: coinciden en {sum(agree)} de {len(agree)}.")

    bcrp_keys = [k for k in present if not k.startswith("sbs_")]
    sbs_keys = [k for k in present if k.startswith("sbs_")]
    types_k = "tasa_bancos_corporativo_hasta360_mn"
    info = {
        "ref_first": ref.dropna().index.min(), "ref_last": ref.dropna().index.max(),
        "bcrp_last": max(m[k].dropna().index.max() for k in bcrp_keys),
        "sbs_first": min(m[k].dropna().index.min() for k in sbs_keys) if sbs_keys else None,
        "sbs_last": max(m[k].dropna().index.max() for k in sbs_keys) if sbs_keys else None,
        "types_first": m[types_k].dropna().index.min() if types_k in present else None,
        "bcrp_ecm_first": ecm_first["bcrp"], "sbs_ecm_first": ecm_first["sbs"],
    }
    metodo = _method_texts(cycles, info, sources_txt)

    for c in cycles:
        for kk in [k for k in c if k.startswith("_")]:
            c.pop(kk)

    return {
        "ciclos": cycles,
        "tasas": tasas,
        "traspaso_ciclo": tc,
        "ecm": ecm_rows,
        "respuesta": {"h": list(range(HORIZON + 1)), "series": resp_series},
        "metodo": metodo,
        "controles": controls,
    }


# ---------------------------------------------------------------------------------------------
# Ejecución directa: resumen legible
# ---------------------------------------------------------------------------------------------
def _load(freq: str) -> pd.DataFrame:
    path = PROJECT_DIR / "data" / "processed" / f"bcrp_panel_{freq}.csv"
    df = pd.read_csv(path, parse_dates=["fecha"], encoding="utf-8-sig")
    return df.set_index("fecha").sort_index()


def main() -> int:
    import time
    sys.stdout.reconfigure(encoding="utf-8")
    t0 = time.perf_counter()
    m, d = _load("mensual"), _load("diaria")
    out = build_transmission(m, d)
    txt = json.dumps(out, ensure_ascii=False, allow_nan=False)
    elapsed = time.perf_counter() - t0
    labels = {t["k"]: f"{t['label']} ({t['mon']})" for t in out["tasas"]}
    print("== Ciclos")
    for c in out["ciclos"]:
        print(f"  {c['id']:22s} {c['inicio']} → {c['fin']}  {c['ref_antes']:.2f} → "
              f"{c['ref_fin']:.2f} ({c['d_ref']:+.2f} pp, {c['n_mov']} mov.)"
              f"{'  EN CURSO' if c['en_curso'] else ''}")
    print("\n== ECM (traspaso de largo plazo)")
    for e in out["ecm"]:
        print(f"  {labels[e['k']]:48s} β={_f(e['beta']):>6s} [{_f(e['lo']):>5s}, {_f(e['hi']):>5s}] "
              f"imp={_f(e['impacto']):>5s} m50={e['m50']} m90={e['m90']} ok={e['ok']}")
    for cid in [out["ciclos"][-2]["id"], out["ciclos"][-1]["id"]]:
        print(f"\n== Traspaso en el ciclo {cid}")
        for r in out["traspaso_ciclo"]:
            if r["ciclo"] == cid and r["d"] is not None:
                rat = "  —" if r["ratio"] is None else f"{r['ratio']:5.2f}"
                print(f"  {labels[r['k']]:48s} {r['antes']:6.2f} → {r['fin']:6.2f} "
                      f"({r['d']:+6.2f}) ratio {rat}  [{r['medido_en']}]")
    print("\n== Controles")
    for c in out["controles"]:
        print("  - " + c)
    print(f"\nJSON: {len(txt):,} caracteres; {elapsed:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
