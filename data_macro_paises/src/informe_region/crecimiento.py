"""Bloque «Crecimiento y ciclo económico» del informe «El Perú frente a la región».

Lee solo la capa comparable (`data/processed/comparable/`) y respeta:
- la columna `uso` de `comparable_series.csv` (lo `no_comparable` nunca entra; lo
  `solo_tendencias` no entra en comparaciones de nivel ni en el ciclo mensual);
- las marcas de `regimen` por observación (se excluye la intervención del INDEC en promedios y
  correlaciones; 2020-2021 se trata aparte);
- los cortes de `config/comparable/cortes_muestra.csv` (se aplican por si alguno toca este bloque).

No imputa huecos: si un país no tiene el último trimestre, se muestra su último dato con su fecha.

Uso:
    python src/informe_region/crecimiento.py
"""
from __future__ import annotations

import fnmatch
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

# --- Constantes del bloque ------------------------------------------------------------------
FOCUS = "PER"
COUNTRIES = ["PER", "CHL", "COL", "MEX", "BRA", "ARG", "ECU", "URY", "PRY", "BOL", "PAN", "ESP", "USA"]
NAMES = {
    "PER": "Perú", "CHL": "Chile", "COL": "Colombia", "MEX": "México", "BRA": "Brasil",
    "ARG": "Argentina", "ECU": "Ecuador", "URY": "Uruguay", "PRY": "Paraguay", "BOL": "Bolivia",
    "PAN": "Panamá", "ESP": "España", "USA": "Estados Unidos",
}
# Núcleo con metas de inflación y tipo de cambio flotante (docs de comparabilidad)
CORE = ["PER", "CHL", "COL", "MEX", "BRA", "URY"]
# Regla común del informe: medianas y puestos solo con América Latina; ESP y USA son referencia
REFERENCE = ["ESP", "USA"]
REGION = [c for c in COUNTRIES if c not in REFERENCE]

COMPARABLE_USES = {"comparable", "comparable_con_ajuste"}
CYCLE_USES = COMPARABLE_USES | {"solo_tendencias"}

PRE_WINDOW = ("2015-01-01", "2019-12-31")      # promedio prepandemia
POST_START = "2022-01-01"                      # promedio pospandemia: 2022-T1 al último
PANDEMIC = ("2020-01-01", "2021-12-31")        # fuera de la correlación principal
CORR_START = "2010-01-01"                      # inicio de la muestra de sincronización
LEVEL_CHART_START = "2018-10-01"               # primer promedio de 4T con datos de Panamá
MIN_PRE_QUARTERS = 8                           # al menos 2 años para el promedio prepandemia
MIN_CORR_OBS = 12
MONTHLY_WINDOW = 36                            # meses del gráfico de ciclo mensual
EXCLUDED_REGIMES = ("intervencion_indec",)     # marcas que invalidan la observación

FUENTE_TRIM = ("Cuentas nacionales trimestrales de los bancos centrales e institutos de "
               "estadística de cada país. Variaciones e índices calculados sobre las series oficiales.")
FUENTE_MENS = ("Indicadores mensuales de actividad de los bancos centrales e institutos de "
               "estadística de cada país. Variaciones calculadas sobre el índice original.")

MONTHS_ES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "set", "oct", "nov", "dic"]


# --- Utilidades -----------------------------------------------------------------------------
def _read_retry(reader, path: Path, attempts: int = 6, wait: float = 20.0, **kw):
    """Lee un archivo reintentando si está a medio escribir por otra corrida."""
    last = None
    for i in range(attempts):
        try:
            return reader(path, **kw)
        except Exception as exc:  # noqa: BLE001
            last = exc
            if i < attempts - 1:
                time.sleep(wait)
    raise RuntimeError(f"No se pudo leer {path.name}: {last}")


def qlabel(ts) -> str:
    ts = pd.Timestamp(ts)
    return f"{ts.year}-T{(ts.month - 1) // 3 + 1}"


def mlabel(ts) -> str:
    ts = pd.Timestamp(ts)
    return f"{MONTHS_ES[ts.month - 1]}-{ts.year}"


def span(a, b) -> str:
    """«2015-2019» si son años completos; si no, «2017-T1 a 2019-T4»."""
    a, b = pd.Timestamp(a), pd.Timestamp(b)
    if a.month == 1 and b.month == 10:
        return f"{a.year}-{b.year}" if a.year != b.year else str(a.year)
    return f"{qlabel(a)} a {qlabel(b)}"


def r_critical(n: int, alpha: float = 0.05) -> float:
    """Correlación mínima (en valor absoluto) distinta de cero al nivel alpha, bilateral."""
    try:
        from scipy.stats import t as student_t
        tc = float(student_t.ppf(1 - alpha / 2, n - 2))
    except ImportError:  # aproximación normal si no hay scipy
        tc = 1.959964
    return tc / math.sqrt(n - 2 + tc * tc)


def iso(ts) -> str:
    return pd.Timestamp(ts).strftime("%Y-%m-%d")


def num(x: float, dec: int = 1, sign: bool = False) -> str:
    """Número con coma decimal (convención en español)."""
    s = f"{x:+.{dec}f}" if sign else f"{x:.{dec}f}"
    return s.replace("-", "−").replace(".", ",")


def rnd(x, dec: int = 2):
    if x is None or (isinstance(x, float) and not math.isfinite(x)) or pd.isna(x):
        return None
    return round(float(x), dec)


def join_es(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " y " + items[-1]


def _clean_nan(obj):
    """NaN/inf → None para que el JSON sea válido."""
    if isinstance(obj, dict):
        return {k: _clean_nan(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean_nan(v) for v in obj]
    if isinstance(obj, (float, np.floating)):
        return None if not math.isfinite(float(obj)) else float(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    return obj


# --- Carga y filtros ------------------------------------------------------------------------
def _project_dir(comparable_dir: Path) -> Path:
    # data/processed/comparable → raíz del proyecto
    return comparable_dir.resolve().parents[2]


def _apply_cuts(obs: pd.DataFrame, comparable_dir: Path) -> pd.DataFrame:
    path = _project_dir(comparable_dir) / "config" / "comparable" / "cortes_muestra.csv"
    if not path.exists():
        return obs
    cuts = pd.read_csv(path, encoding="utf-8-sig", dtype=str).fillna("")
    keep = pd.Series(True, index=obs.index)
    for _, c in cuts.iterrows():
        pats = [p.strip() for p in c["indicadores"].split(",") if p.strip()]
        m = obs["indicador"].apply(lambda s: any(fnmatch.fnmatch(s, p) for p in pats))
        if c["pais"] not in ("", "*"):
            m &= obs["pais"] == c["pais"]
        if not m.any():
            continue
        desde = pd.Timestamp(c["desde"]) if c["desde"] else pd.Timestamp.min
        hasta = pd.Timestamp(c["hasta"]) if c["hasta"] else pd.Timestamp.max
        inside = obs["fecha"].between(desde, hasta)
        if c["tipo"] == "mantener":
            keep &= ~(m & ~inside)
        elif c["tipo"] == "excluir":
            keep &= ~(m & inside)
    return obs[keep]


def load(comparable_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    comparable_dir = Path(comparable_dir)
    obs = _read_retry(pd.read_parquet, comparable_dir / "comparable_observaciones.parquet")
    series = _read_retry(pd.read_csv, comparable_dir / "comparable_series.csv")
    inds = ["pbi_real_var_a", "pbi_real_indice", "pbi_desest_indice", "actividad_mensual_var_a"]
    obs = obs[obs["indicador"].isin(inds) & obs["pais"].isin(COUNTRIES)].copy()
    obs["fecha"] = pd.to_datetime(obs["fecha"])
    obs["regimen"] = obs["regimen"].fillna("").astype(str)
    obs = obs.dropna(subset=["valor"])
    obs = _apply_cuts(obs, comparable_dir)
    return obs, series


def _uso(series: pd.DataFrame, ind: str) -> dict[str, str]:
    s = series[series["indicador"] == ind]
    return dict(zip(s["pais"], s["uso"]))


def _flagged(reg: pd.Series) -> pd.Series:
    return reg.apply(lambda r: any(x in r.split(";") for x in EXCLUDED_REGIMES))


def _wide(obs: pd.DataFrame, ind: str, countries: list[str], drop_flagged: bool) -> pd.DataFrame:
    d = obs[(obs["indicador"] == ind) & obs["pais"].isin(countries)]
    if drop_flagged:
        d = d[~_flagged(d["regimen"])]
    w = d.pivot_table(index="fecha", columns="pais", values="valor", aggfunc="first").sort_index()
    return w.reindex(columns=[c for c in countries if c in w.columns])


def _series_points(s: pd.Series, dec: int = 2) -> list:
    s = s.dropna()
    return [[iso(k), rnd(v, dec)] for k, v in s.items()]


def _ordered(countries) -> list[str]:
    return [c for c in COUNTRIES if c in set(countries)]


# --- Cálculos -------------------------------------------------------------------------------
def build(comparable_dir: Path) -> dict:
    obs, series = load(Path(comparable_dir))

    uso_g = _uso(series, "pbi_real_var_a")
    uso_l = _uso(series, "pbi_real_indice")
    uso_m = _uso(series, "actividad_mensual_var_a")
    cobertura_m = dict(zip(series.loc[series.indicador == "actividad_mensual_var_a", "pais"],
                           series.loc[series.indicador == "actividad_mensual_var_a", "cobertura"]))

    g_countries = _ordered([c for c, u in uso_g.items() if u in COMPARABLE_USES])
    l_countries = _ordered([c for c, u in uso_l.items() if u in COMPARABLE_USES])
    m_countries = _ordered([c for c, u in uso_m.items() if u in COMPARABLE_USES])
    m_excluded = _ordered([c for c, u in uso_m.items() if u not in COMPARABLE_USES])

    growth = _wide(obs, "pbi_real_var_a", g_countries, drop_flagged=False)
    growth_clean = _wide(obs, "pbi_real_var_a", g_countries, drop_flagged=True)
    level = _wide(obs, "pbi_real_indice", l_countries, drop_flagged=False)
    monthly = _wide(obs, "actividad_mensual_var_a", m_countries, drop_flagged=False)
    desest = _wide(obs, "pbi_desest_indice", COUNTRIES, drop_flagged=False)

    # 1) Trimestre de referencia = último del Perú. Todos los países se comparan en ese mismo
    #    trimestre; si un país no lo publicó, se usa su último dato anterior, con su fecha.
    last = {c: (growth[c].dropna().index[-1], growth[c].dropna().iloc[-1])
            for c in growth.columns if growth[c].notna().any()}
    ref_q = last[FOCUS][0]
    at_ref = {}
    for c in growth.columns:
        s = growth[c].dropna()
        s = s[s.index <= ref_q]
        if len(s):
            at_ref[c] = (s.index[-1], s.iloc[-1])
    behind = {c: d for c, (d, _) in at_ref.items() if d < ref_q}
    ahead = {c: last[c] for c in last if last[c][0] > ref_q}

    # 2) Promedios de crecimiento a/a: 2015-2019 y 2022-T1 al trimestre de referencia
    #    (sin trimestres intervenidos)
    pre, post = {}, {}
    for c in growth_clean.columns:
        s = growth_clean[c].dropna()
        p = s[(s.index >= PRE_WINDOW[0]) & (s.index <= PRE_WINDOW[1])]
        if len(p) >= MIN_PRE_QUARTERS:
            pre[c] = (p.mean(), p.index[0], p.index[-1], len(p))
        q = s[(s.index >= POST_START) & (s.index <= ref_q)]
        if len(q):
            post[c] = (q.mean(), q.index[0], q.index[-1], len(q))

    # 3) Nivel: promedio móvil de 4 trimestres del índice 2019=100 (quita la estacionalidad;
    #    en 2019-T4 vale 100 por construcción). Solo con 4 trimestres consecutivos.
    lvl4 = pd.DataFrame(index=level.index)
    for c in level.columns:
        s = level[c].dropna()
        full = s.asfreq("QS")
        lvl4[c] = full.rolling(4, min_periods=4).mean().reindex(level.index)
    ref_l = lvl4[FOCUS].dropna().index[-1]
    lvl_ref = {}
    for c in lvl4.columns:
        s = lvl4[c].dropna()
        s = s[s.index <= ref_l]
        if len(s):
            lvl_ref[c] = (s.index[-1], s.iloc[-1])

    # 4) Sincronización: correlación del crecimiento a/a del Perú con cada país, hasta el
    #    trimestre de referencia. Umbral de significancia al 5 % (bilateral) con el n de cada par.
    sync = {}
    base = growth_clean[FOCUS]
    for c in growth_clean.columns:
        if c == FOCUS:
            continue
        pair = pd.concat([base, growth_clean[c]], axis=1, keys=["a", "b"]).dropna()
        pair = pair[(pair.index >= CORR_START) & (pair.index <= ref_q)]
        no_pand = pair[(pair.index < PANDEMIC[0]) | (pair.index > PANDEMIC[1])]
        if len(no_pand) < MIN_CORR_OBS:
            continue
        r, n = no_pand["a"].corr(no_pand["b"]), len(no_pand)
        crit = r_critical(n)
        sync[c] = {
            "r": r, "n": n, "crit": crit, "sig": abs(r) >= crit,
            "desde": no_pand.index[0], "hasta": no_pand.index[-1],
            "r_all": pair["a"].corr(pair["b"]), "n_all": len(pair),
        }

    # 5) Ciclo mensual (solo indicadores conciliados con el PBI)
    m_last = {c: (monthly[c].dropna().index[-1], monthly[c].dropna().iloc[-1])
              for c in monthly.columns if monthly[c].notna().any()}
    m_end = max(d for d, _ in m_last.values())
    m_start = (m_end - pd.DateOffset(months=MONTHLY_WINDOW - 1)).normalize()

    # 6) Ecuador: brecha entre su a/a oficial (sobre la desestacionalizada) y la a/a original
    ecu_gap = None
    if "ECU" in growth.columns and "ECU" in desest.columns:
        sa = desest["ECU"].dropna().asfreq("QS")
        gap = ((sa / sa.shift(4) - 1) * 100 - growth["ECU"]).abs().dropna()
        if len(gap):
            ecu_gap = (gap.max(), gap.idxmax())

    # --- Comparación regional (regla común: solo América Latina, sin el Perú, mismo trimestre)
    per_q, per_g = last[FOCUS]
    others_ref = {c: v for c, (d, v) in at_ref.items()
                  if c in REGION and c != FOCUS and d == ref_q}
    n_others = len(others_ref)
    median_others = float(np.median(list(others_ref.values()))) if others_ref else float("nan")
    rank = 1 + sum(v > per_g for v in others_ref.values())
    n_rank = n_others + 1
    per_post = post.get(FOCUS)
    per_pre = pre.get(FOCUS)
    per_lvl = lvl_ref[FOCUS][1]

    # --- KPIs (valores sin redondear; el formato lo aplica la plantilla) ---------------------
    kpis = [
        {"lab": "Crecimiento del PBI real", "val": float(per_g), "fmt": "pct1", "unit": "%",
         "sub": f"Perú, a/a, {qlabel(per_q)}", "fecha": iso(per_q)},
        {"lab": "Mediana de la región", "val": median_others, "fmt": "pct1", "unit": "%",
         "sub": f"los otros {n_others} países de la región, {qlabel(ref_q)}", "fecha": iso(ref_q)},
        {"lab": "Puesto del Perú en la región", "val": float(rank), "fmt": "num0",
         "unit": f"de {n_rank}", "sub": f"crecimiento a/a, {qlabel(ref_q)}", "fecha": iso(ref_q)},
    ]
    if per_post:
        kpis.append({"lab": "Crecimiento promedio desde 2022", "val": float(per_post[0]),
                     "fmt": "pct1", "unit": "%",
                     "sub": f"Perú, {qlabel(per_post[1])} a {qlabel(per_post[2])}",
                     "fecha": iso(per_post[2])})
    if per_post and per_pre:
        kpis.append({"lab": "Frente a 2015-2019", "val": float(per_post[0] - per_pre[0]),
                     "fmt": "pp1", "unit": "pp",
                     "sub": f"Perú, promedio {qlabel(per_post[1])} a {qlabel(per_post[2])} "
                            f"menos promedio {span(per_pre[1], per_pre[2])}",
                     "fecha": iso(per_post[2])})
    kpis.append({"lab": "Nivel del PBI real", "val": float(per_lvl), "fmt": "num1",
                 "unit": "2019=100", "sub": f"Perú, promedio de 4 trimestres a {qlabel(ref_l)}",
                 "fecha": iso(ref_l)})
    if FOCUS in m_last:
        d, v = m_last[FOCUS]
        kpis.append({"lab": "Actividad mensual", "val": float(v), "fmt": "pct1", "unit": "%",
                     "sub": f"Perú, PBI mensual a/a, {mlabel(d)}", "fecha": iso(d)})

    # --- Gráficos ----------------------------------------------------------------------------
    def label(c: str) -> str:
        return f"{NAMES[c]} (referencia)" if c in REFERENCE else NAMES[c]

    def bar_series(values: dict) -> list:
        """Región ordenada de mayor a menor; España y EE. UU. al final, como referencia."""
        reg = sorted(((c, d, v) for c, (d, v) in values.items() if c not in REFERENCE),
                     key=lambda t: -t[2])
        ref = [(c, *values[c]) for c in REFERENCE if c in values]
        return [{"pais": c, "nombre": label(c), "puntos": [[iso(d), rnd(v, 3)]]}
                for c, d, v in reg + ref]

    notes_q = []
    if behind:
        notes_q.append("; ".join(f"{NAMES[c]}: último dato publicado {qlabel(d)}"
                                 for c, d in behind.items()) + ".")
    if ahead:
        notes_q.append(f"{join_es([NAMES[c] for c in ahead])} ya "
                       f"{'publicó' if len(ahead) == 1 else 'publicaron'} "
                       f"{qlabel(max(d for d, _ in ahead.values()))}; para comparar el mismo "
                       f"periodo se usa {qlabel(ref_q)}.")
    ref_note = (f"España y Estados Unidos se muestran como referencia y no entran en la mediana "
                f"ni en el puesto, que se calculan con los {n_rank} países de América Latina.")

    sig_txt = join_es([NAMES[c] for c, v in sorted(sync.items(), key=lambda kv: -kv[1]["r"])
                       if v["sig"]])
    graficos = [
        {
            "id": "crec_ultimo",
            "titulo": f"Crecimiento del PBI real en {qlabel(ref_q)}",
            "subtitulo": f"Variación % a/a; {qlabel(ref_q)}, último trimestre publicado por el Perú",
            "tipo": "barras_h", "unidad": "%",
            "series": bar_series(at_ref),
            "nota": " ".join(["Variación calculada desde el nivel original (sin desestacionalizar) "
                              "en todos los países.", ref_note] + notes_q),
            "fuente": FUENTE_TRIM,
        },
        {
            "id": "crec_pospandemia",
            "titulo": "Crecimiento promedio desde 2022",
            "subtitulo": f"Promedio de las variaciones % a/a trimestrales, 2022-T1 a {qlabel(ref_q)}",
            "tipo": "barras_h", "unidad": "%",
            "series": bar_series({c: (v[2], v[0]) for c, v in post.items()}),
            "nota": " ".join([f"Todos los países se cortan en {qlabel(ref_q)}.", ref_note]
                             + (notes_q[:1] if behind else [])
                             + ["La comparación con 2015-2019 está en la tabla del bloque."]),
            "fuente": FUENTE_TRIM,
        },
        {
            "id": "nivel_2019",
            "titulo": "Nivel del PBI real frente a 2019",
            "subtitulo": "Índice 2019=100, promedio móvil de 4 trimestres",
            "tipo": "lineas", "unidad": "índice 2019=100",
            "series": [{"pais": c, "nombre": NAMES[c],
                        "puntos": _series_points(lvl4.loc[lvl4.index >= LEVEL_CHART_START, c], 3)}
                       for c in lvl4.columns],
            "nota": "El promedio de 4 trimestres elimina la estacionalidad de la serie original y "
                    "vale 100 en 2019-T4. Muestra trayectorias, no el tamaño de cada economía.",
            "fuente": FUENTE_TRIM,
        },
        {
            "id": "crec_nucleo",
            "titulo": "Crecimiento del PBI real: Perú y economías con metas de inflación",
            "subtitulo": "Variación % a/a trimestral desde 2022-T1",
            "tipo": "lineas", "unidad": "%",
            "series": [{"pais": c, "nombre": NAMES[c],
                        "puntos": _series_points(growth.loc[growth.index >= POST_START, c], 3)}
                       for c in CORE if c in growth.columns],
            "nota": "Países con metas de inflación y tipo de cambio flotante.",
            "fuente": FUENTE_TRIM,
        },
        {
            "id": "ciclo_mensual",
            "titulo": "Ciclo mensual de la actividad",
            "subtitulo": f"Variación % a/a del indicador mensual de actividad, "
                         f"{mlabel(m_start)} a {mlabel(m_end)}",
            "tipo": "lineas", "unidad": "%",
            "series": [{"pais": c, "nombre": NAMES[c],
                        "puntos": _series_points(monthly.loc[monthly.index >= m_start, c], 3)}
                       for c in monthly.columns],
            "nota": f"Solo los {len(m_countries)} países cuyo indicador mensual concilia con su PBI."
                    + "".join(f" {NAMES[c]}: último dato {mlabel(d)}." for c, (d, _) in m_last.items()
                              if d != m_end),
            "fuente": FUENTE_MENS,
        },
        {
            "id": "sincronizacion",
            "titulo": "Sincronización del ciclo del Perú con cada país",
            "subtitulo": f"Correlación del crecimiento % a/a trimestral, sin 2020-2021, hasta {qlabel(ref_q)}",
            "tipo": "barras_h", "unidad": "coeficiente de correlación",
            "series": [{"pais": c, "nombre": NAMES[c], "puntos": [[iso(v["hasta"]), rnd(v["r"], 3)]]}
                       for c, v in sorted(sync.items(), key=lambda kv: -kv[1]["r"])],
            "nota": f"Muestra desde {qlabel(CORR_START)} o desde el inicio de la serie del país, sin "
                    "2020-2021 ni trimestres con estadísticas intervenidas. Distintas de cero al 5 %: "
                    f"{sig_txt or 'ninguna'}; las demás no se distinguen de cero. El umbral de cada "
                    "par y el número de trimestres están en la tabla.",
            "fuente": FUENTE_TRIM,
        },
    ]

    # --- Tablas ------------------------------------------------------------------------------
    period = span
    first_g = {c: growth_clean[c].dropna().index[0] for c in growth_clean.columns
               if growth_clean[c].notna().any()}

    filas = []
    for c in COUNTRIES:
        if c not in at_ref:
            continue
        d, v = at_ref[c]
        pr, po, lv = pre.get(c), post.get(c), lvl_ref.get(c)
        filas.append([
            label(c), qlabel(d), rnd(v, 1),
            rnd(pr[0], 1) if pr else None,
            period(pr[1], pr[2]) if pr else f"serie desde {qlabel(first_g[c])}",
            rnd(po[0], 1) if po else None,
            rnd(po[0] - pr[0], 1) if (pr and po) else None,
            rnd(lv[1], 1) if lv else None,
        ])
    tablas = [
        {
            "id": "tabla_crecimiento",
            "titulo": "Crecimiento del PBI real por país",
            "columnas": ["País", "Trimestre", "Var. % a/a", "Promedio 2015-2019 (%)",
                         "Periodo del promedio", f"Promedio 2022-T1 a {qlabel(ref_q)} (%)",
                         "Diferencia (pp)", "Nivel 2019=100 (prom. 4T)"],
            "filas": filas,
            "nota": " ".join([
                f"Todos los países se comparan en {qlabel(ref_q)}, el último trimestre publicado "
                "por el Perú.", *notes_q,
                "Promedios de las variaciones a/a trimestrales. Cuando la serie oficial empieza "
                "después de 2015, o hay trimestres con estadísticas intervenidas, el promedio "
                "2015-2019 cubre solo el periodo indicado. La diferencia se calcula antes de "
                "redondear."]),
        },
        {
            "id": "tabla_sincronizacion",
            "titulo": "Correlación del crecimiento a/a del Perú con cada país",
            "columnas": ["País", "Correlación sin 2020-2021", "Umbral al 5 %",
                         "Distinta de cero al 5 %", "Trimestres", "Muestra",
                         "Correlación con 2020-2021", "Trimestres (con 2020-2021)"],
            "filas": [[NAMES[c], rnd(v["r"], 2), rnd(v["crit"], 2), "Sí" if v["sig"] else "No",
                       v["n"], period(v["desde"], v["hasta"]), rnd(v["r_all"], 2), v["n_all"]]
                      for c, v in sorted(sync.items(), key=lambda kv: -kv[1]["r"])],
            "nota": "El umbral es el valor absoluto mínimo de la correlación para distinguirla de "
                    "cero al 5 % con el número de trimestres de cada par. Supone observaciones "
                    "independientes; como las variaciones a/a de trimestres vecinos se superponen, "
                    "es un umbral mínimo y los coeficientes cercanos a él deben leerse con cautela. "
                    "La columna con 2020-2021 es solo referencia: el choque común de la pandemia "
                    "eleva todas las correlaciones.",
        },
    ]

    # --- Resumen (todas las cifras salen de los datos) ---------------------------------------
    resumen = [
        f"En {qlabel(per_q)} el PBI real del Perú creció {num(per_g)} % a/a, frente a una mediana "
        f"de {num(median_others)} % en los otros {n_others} países de la región "
        f"(puesto {rank} de {n_rank})."
    ]
    if per_post and per_pre:
        post_reg = [v[0] for c, v in post.items()
                    if c in REGION and c != FOCUS and v[2] == ref_q]
        resumen.append(
            f"Entre {qlabel(per_post[1])} y {qlabel(per_post[2])} el crecimiento a/a promedio del "
            f"Perú fue {num(per_post[0])} %, frente a {num(per_pre[0])} % en "
            f"{span(per_pre[1], per_pre[2])}; la mediana de los otros {len(post_reg)} países de la "
            f"región en el periodo reciente fue {num(float(np.median(post_reg)))} %."
        )
    others_lvl = {c: v for c, (d, v) in lvl_ref.items()
                  if c in REGION and c != FOCUS and d == ref_l}
    above = sum(v > per_lvl for v in others_lvl.values())
    resumen.append(
        f"Con el promedio de 4 trimestres a {qlabel(ref_l)}, el PBI real del Perú está "
        f"{num(per_lvl - 100)} % por encima de 2019; {above} de los otros {len(others_lvl)} "
        f"países de la región muestran un crecimiento acumulado mayor desde 2019 en el mismo "
        f"trimestre."
    )
    if sync:
        ranked = sorted(sync.items(), key=lambda kv: -kv[1]["r"])
        pos = [f"{NAMES[c]} ({num(v['r'], 2)})" for c, v in ranked if v["sig"] and v["r"] > 0]
        neg = [f"{NAMES[c]} ({num(v['r'], 2)})" for c, v in ranked if v["sig"] and v["r"] < 0]
        nul = [NAMES[c] for c, v in ranked if not v["sig"]]
        parts = []
        if pos:
            parts.append(f"es positiva y distinta de cero al 5 % con {join_es(pos)}")
        if neg:
            parts.append(f"es negativa con {join_es(neg)}")
        txt = (f"Sin 2020-2021 y hasta {qlabel(ref_q)}, la correlación del crecimiento a/a del Perú "
               + "; ".join(parts))
        if nul:
            txt += f"; no muestra relación con {join_es(nul)}"
        resumen.append(txt + ".")

    # --- Advertencias ------------------------------------------------------------------------
    ecu_txt = ""
    if ecu_gap is not None:
        ecu_txt = (f" En Ecuador la diferencia con la cifra oficial llega a {num(ecu_gap[0])} pp "
                   f"({qlabel(ecu_gap[1])}).")
    advertencias = [
        "Medianas y puestos usan solo los países de América Latina, sin el Perú y en el mismo "
        "trimestre; España y Estados Unidos se muestran como referencia.",
        "Ecuador y España difunden como cifra titular la variación a/a sobre la serie "
        "desestacionalizada, y Estados Unidos la variación trimestral anualizada de la serie "
        "desestacionalizada. Aquí todas las variaciones a/a se calculan desde el nivel original, "
        "como en los demás países, por lo que pueden diferir de la cifra difundida." + ecu_txt,
        "Argentina, México, Paraguay, Perú y Uruguay miden el PBI real a precios de un año base "
        "fijo, algunos lejano (2004 en Argentina, 2007 en Perú); no conviene leer diferencias de "
        "crecimiento de pocas décimas como diferencias reales.",
        "Las cifras recientes son preliminares en todos los países, el Perú incluido; las "
        "revisiones suelen ser mayores en Argentina, Bolivia, Paraguay, Panamá y Estados Unidos.",
        "Se excluyen de promedios y correlaciones los trimestres de Argentina de 2007 a 2015, "
        "con estadísticas del INDEC intervenidas.",
        "El índice 2019=100 compara trayectorias, no tamaños: no sirve para ordenar economías por "
        "nivel de producto.",
    ]
    if behind or ahead:
        advertencias.append(
            f"El bloque compara {qlabel(ref_q)}, el último trimestre publicado por el Perú. "
            + " ".join(notes_q)
            + (" Se muestra el último dato publicado de cada país con su fecha." if behind else "")
        )
    short = [(c, v) for c, v in pre.items() if pd.Timestamp(v[1]) > pd.Timestamp(PRE_WINDOW[0])]
    no_pre = [c for c in g_countries if c not in pre]
    if short or no_pre:
        txt = "Las series oficiales vigentes son cortas en algunos países: el promedio 2015-2019 cubre "
        txt += "; ".join(f"{span(v[1], v[2])} en {NAMES[c]}" for c, v in short)
        if no_pre:
            txt += ("; " if short else "") + "no se calcula en " + join_es(
                [f"{NAMES[c]} (serie desde {qlabel(first_g[c])})" for c in no_pre])
        advertencias.append(txt + ".")
    if m_excluded:
        prod_ind = [c for c in m_excluded if "produccion_industrial" in str(cobertura_m.get(c, ""))]
        proxy = [c for c in m_excluded if c not in prod_ind]
        txt = "El ciclo mensual incluye solo indicadores conciliados con el PBI. "
        if prod_ind:
            txt += (f"{join_es([NAMES[c] for c in prod_ind])} no publican un indicador mensual "
                    "de toda la economía. ")
        if proxy:
            txt += (f"Los indicadores de {join_es([NAMES[c] for c in proxy])} no concilian con su "
                    "PBI y quedan fuera.")
        advertencias.append(txt.strip())
    if "ECU" in m_countries:
        advertencias.append(
            "En Ecuador la variación mensual oficial se calcula sobre la serie desestacionalizada; "
            "aquí se usa la del índice original."
        )
    short_corr = [c for c, v in sync.items() if v["desde"] > pd.Timestamp(CORR_START)]
    txt = "La correlación mide cuánto se mueven juntos los ciclos, no causalidad."
    if short_corr:
        ns = [sync[c]["n"] for c in short_corr]
        txt += (f" En {join_es([NAMES[c] for c in _ordered(short_corr)])} la muestra es más corta "
                f"({min(ns)} a {max(ns)} trimestres) y el coeficiente es menos estable.")
    advertencias.append(txt)

    return {
        "id": "crecimiento",
        "titulo": "Crecimiento y ciclo económico",
        "resumen": resumen,
        "kpis": kpis,
        "graficos": graficos,
        "tablas": tablas,
        "advertencias": advertencias,
    }


# --- Ejecución directa ----------------------------------------------------------------------
if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    project = Path(__file__).resolve().parents[2]
    comparable = project / "data" / "processed" / "comparable"
    out_dir = project / "data" / "processed" / "informe_region"
    out_dir.mkdir(parents=True, exist_ok=True)

    block = _clean_nan(build(comparable))
    out = out_dir / "crecimiento.json"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(block, fh, ensure_ascii=False, indent=1, allow_nan=False)

    # Controles
    g = next(x for x in block["graficos"] if x["id"] == "crec_ultimo")
    print(f"Salida: {out}")
    print(f"Países con crecimiento a/a: {len(g['series'])}")
    for s in g["series"]:
        d, v = s["puntos"][0]
        print(f"  {s['pais']}  {qlabel(d)}  {v:+.2f} %")
    m = next(x for x in block["graficos"] if x["id"] == "ciclo_mensual")
    print(f"Países en ciclo mensual: {len(m['series'])} -> "
          + ", ".join(f"{s['pais']} {s['puntos'][-1][0][:7]}" for s in m["series"]))
    print(f"KPIs: {len(block['kpis'])} | gráficos: {len(block['graficos'])} | "
          f"tablas: {len(block['tablas'])} | advertencias: {len(block['advertencias'])}")
    print("Resumen:")
    for r in block["resumen"]:
        print("  -", r)
