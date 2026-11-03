"""Genera `outputs/inflacion_bcrp.html`: tablero de inflación del Perú.

Lee el panel mensual de `data/processed/` (correr antes `construir_tablas.py`) y la comparación
nacional/regional de `inflacion_comparada.py`, arma los datos que usa la página y los inyecta en
la plantilla `src/plantillas/inflacion.html`. El HTML resultante es autocontenido (sin librerías
externas) y se abre con doble clic. Genera además `outputs/inflacion_bcrp_artifact.html`, la
versión para publicar como Artifact de claude.ai (sin <html>/<head>/<body>).

Si falta alguna serie en el panel (p. ej. porque aún no se descargó), el bloque que la usa se
omite con un aviso en consola en vez de fallar.

Uso:
    python visual_inflacion.py
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from visual_reservas import artifact_version, month_key, num  # noqa: E402

PROJECT_DIR = Path(__file__).resolve().parents[1]
PROCESSED = PROJECT_DIR / "data" / "processed"
TEMPLATE = PROJECT_DIR / "src" / "plantillas" / "inflacion.html"
OUT = PROJECT_DIR / "outputs" / "inflacion_bcrp.html"
OUT_ARTIFACT = PROJECT_DIR / "outputs" / "inflacion_bcrp_artifact.html"
PLACEHOLDER = "/*__DATA__*/null"

# Meta vigente si no se puede leer la tabla de metas (BCRP: 2% ±1 desde feb-2007; 2.5% ±1 en 2002-2007).
FALLBACK_TARGETS = [
    {"desde": "2002-01-01", "hasta": "2007-01-31", "c": 2.5, "lo": 1.5, "hi": 3.5},
    {"desde": "2007-02-01", "hasta": None, "c": 2.0, "lo": 1.0, "hi": 3.0},
]

WARNINGS: list[str] = []


def warn(msg: str) -> None:
    WARNINGS.append(msg)
    print(f"  AVISO: {msg}")


# ---------------------------------------------------------------------------------------------
# Series que usa la página. Clave corta (la que lee el JS) -> columna del panel.
# 'c12' = var% 12 meses compuesta desde la var% mensual.
# ---------------------------------------------------------------------------------------------
DIRECT = {
    "tot12": "ipc_var12m", "totm": "ipc_var_mensual", "sae12": "ipc_sin_alim_energia_var12m",
    "sub12": "ipc_subyacente_var12m", "exp": "expectativa_inflacion_12m", "ref": "tasa_referencia",
    "tra12": "ipc_transables_var12m", "ntr12": "ipc_no_transables_var12m", "ipm12": "ipm_var12m",
    "saem": "ipc_sin_alim_energia_var_mensual", "subm": "ipc_subyacente_var_mensual",
    "ae12": "ipc_alim_energia_var12m", "nsub12": "ipc_no_subyacente_var12m",
    "imp12": "ipc_importado_var12m", "ab12": "ipc_alim_bebidas_var12m",
    "vtc12": "ipc_vinculados_tc_var12m", "nvtc12": "ipc_no_vinculados_tc_var12m",
    "d3m": "ipc_desest_var3m_anualizada", "sae3m": "ipc_sae_desest_var3m_anualizada",
}

# Mapa de calor: (clave, etiqueta, nivel, columna, tipo). tipo 'd' = ya es var% 12m; 'm' = mensual.
# Clasificación principal: la sectorial (subyacente / no subyacente). De la de transables solo se
# muestra el corte agregado, porque varios de sus rubros son la misma serie que los sectoriales
# (educación, alquileres, textiles, electrodomésticos, comidas fuera, salud, combustibles...).
# Nivel 0 = agregado, 1 = subgrupo (padre de sus rubros), 2 = rubro. Los padres no se suman con
# sus hijos: la página los distingue visualmente.
HEAT_ROWS = [
    ("tot12", "IPC total", 0, "ipc_var12m", "d"),
    ("sub12", "Subyacente", 0, "ipc_subyacente_var12m", "d"),
    ("h_sb", "Bienes", 1, "ipc_sub_bienes_var_mensual", "m"),
    ("h_sba", "Alimentos y bebidas (resto)", 2, "ipc_sub_bienes_alimentos_var_mensual", "m"),
    ("h_sbt", "Textiles y calzado", 2, "ipc_sub_bienes_textiles_var_mensual", "m"),
    ("h_sbe", "Electrodomésticos", 2, "ipc_sub_bienes_electrodomesticos_var_mensual", "m"),
    ("h_sbr", "Otros productos industriales", 2, "ipc_sub_bienes_resto_industriales_var_mensual", "m"),
    ("h_ss", "Servicios", 1, "ipc_sub_servicios_var_mensual", "m"),
    ("h_ssc", "Comidas fuera del hogar", 2, "ipc_sub_serv_comidas_fuera_var_mensual", "m"),
    ("h_sse", "Educación", 2, "ipc_sub_serv_educacion_var_mensual", "m"),
    ("h_sss", "Salud", 2, "ipc_sub_serv_salud_var_mensual", "m"),
    ("h_ssa", "Alquileres", 2, "ipc_sub_serv_alquileres_var_mensual", "m"),
    ("h_ssr", "Otros servicios", 2, "ipc_sub_serv_resto_var_mensual", "m"),
    ("nsub12", "No subyacente", 0, "ipc_no_subyacente_var12m", "d"),
    ("h_na", "Alimentos volátiles y básicos", 2, "ipc_nosub_alimentos_var_mensual", "m"),
    ("h_nc", "Combustibles", 2, "ipc_nosub_combustibles_var_mensual", "m"),
    ("h_nt", "Transportes", 2, "ipc_nosub_transportes_var_mensual", "m"),
    ("h_np", "Servicios públicos", 2, "ipc_nosub_servicios_publicos_var_mensual", "m"),
    ("tra12", "Transables", 0, "ipc_transables_var12m", "d"),
    ("ntr12", "No transables", 0, "ipc_no_transables_var12m", "d"),
]
# Grupos del mapa de calor (se separan con un espacio): fila inicial de cada grupo.
HEAT_GROUPS = {"tot12": "", "sub12": "Clasificación sectorial", "tra12": "Transables y no transables"}

# Causa documentada de un choque mensual (clave 'YYYY-MM'). Solo se escribe una causa si una fuente
# oficial la respalda; si no, la página da las cifras sin explicar el porqué.
SHOCK_CAUSES = {
    # BCRP, Notas de Estudios N.° 26-2026 (Inflación: marzo 2026).
    "2026-03": "la rotura del gasoducto de TGP, que provocó escasez de gas natural vehicular y GLP, y el mayor precio del petróleo",
}

# Paneles pequeños: otras medidas de la inflación (clave, etiqueta, descripción breve).
SMALL = [
    ("sae12", "Sin alimentos y energía", "Excluye alimentos y bebidas (también las comidas fuera del hogar), combustibles y electricidad. Es la medida de tendencia que destaca el BCRP."),
    ("ae12", "Alimentos y energía", "Lo que excluye la anterior: la parte más volátil de la canasta."),
    ("sub12", "Subyacente", "Excluye los alimentos más volátiles, pan, arroz, fideos, aceites, combustibles, transportes y servicios públicos."),
    ("nsub12", "No subyacente", "Lo que excluye la subyacente: esos alimentos, combustibles, transportes y servicios públicos."),
    ("tra12", "Transables", "Bienes que se comercian con el exterior: siguen los precios internacionales y el dólar."),
    ("ntr12", "No transables", "Sobre todo servicios (alquileres, educación, salud, comidas fuera del hogar), además de algunos alimentos frescos."),
    ("imp12", "Importado", "Rubros importados: el canal más directo del tipo de cambio y del petróleo."),
    ("vtc12", "Vinculados al dólar y a cotizaciones", "Rubros que el BCRP considera ligados al tipo de cambio, a los precios mayoristas o a cotizaciones internacionales."),
    ("nvtc12", "No vinculados", "El resto de la canasta."),
    ("ab12", "Alimentos y bebidas", "El grupo de mayor peso en la canasta del IPC de Lima (incluye las comidas fuera del hogar)."),
    ("ipm12", "Precios al por mayor", "Índice del INEI, nacional: precios de bienes que venden productores e importadores al por mayor. No es parte de la canasta del consumidor."),
]


def load_panel() -> pd.DataFrame:
    df = pd.read_csv(PROCESSED / "bcrp_panel_mensual.csv", parse_dates=["fecha"], encoding="utf-8-sig")
    return df.set_index("fecha").sort_index()


def compose_12m(monthly: pd.Series) -> pd.Series:
    """Var% 12 meses desde la var% mensual: (prod(1 + m/100) de los últimos 12 meses - 1) * 100."""
    factor = 1 + monthly / 100
    return (factor.rolling(12, min_periods=12).apply(np.prod, raw=True) - 1) * 100


def get_col(m: pd.DataFrame, col: str, what: str) -> pd.Series | None:
    if col not in m.columns or m[col].dropna().empty:
        warn(f"falta la columna {col} ({what}); se omite")
        return None
    return m[col]


def load_comparada() -> dict | None:
    try:
        import inflacion_comparada as ic
        d = ic.load_inflacion_comparada()
        d["_high"] = set(getattr(ic, "HIGH_INFLATION_COUNTRIES", {"ARG"}))
        d["_src_nac"] = getattr(ic, "SOURCE_NATIONAL", "INEI, IPC nacional")
        return d
    except Exception as exc:  # módulo ausente o datos no disponibles
        warn(f"no se pudo cargar la comparación nacional/regional ({type(exc).__name__}: {exc}); se omite")
        return None


def build_targets(comp: dict | None) -> list[dict]:
    """Tramos de la meta de inflación del Perú (BCRP)."""
    if comp is not None and "metas" in comp:
        mt = comp["metas"]
        per = mt[mt.pais == "PER"].sort_values("desde")
        if not per.empty:
            out = []
            for r in per.itertuples():
                out.append({"desde": pd.Timestamp(r.desde).strftime("%Y-%m-%d"),
                            "hasta": None if pd.isna(r.hasta) else pd.Timestamp(r.hasta).strftime("%Y-%m-%d"),
                            "c": num(r.meta_centro, 2), "lo": num(r.rango_inferior, 2),
                            "hi": num(r.rango_superior, 2), "tipo": str(r.tipo)})
            return out
    warn("sin tabla de metas: se usa la meta del BCRP desde 2002 (2.5% ±1 y 2% ±1 desde feb-2007)")
    return [dict(t, tipo="puntual_con_rango") for t in FALLBACK_TARGETS]


def band_for_months(months: pd.DatetimeIndex, targets: list[dict]) -> tuple[list, list, list]:
    lo, hi, c = [None] * len(months), [None] * len(months), [None] * len(months)
    for t in targets:
        a = pd.Timestamp(t["desde"]).to_period("M").to_timestamp()
        b = pd.Timestamp(t["hasta"]) if t["hasta"] else months.max()
        for i, ts in enumerate(months):
            if a <= ts <= b:
                lo[i], hi[i] = t["lo"], t["hi"]
                c[i] = t["c"] if t["c"] is not None else None
    return lo, hi, c


def series_list(s: pd.Series | None, months: pd.DatetimeIndex, nd: int = 2) -> list | None:
    if s is None:
        return None
    s = s.reindex(months)
    return [num(v, nd) for v in s.values]


def build_heat(m: pd.DataFrame, months: pd.DatetimeIndex, S: dict) -> list[dict]:
    """Filas del mapa de calor; los valores van a S (var% 12m) y S['<clave>_m'] (var% mensual)."""
    keep = []
    for key, label, level, col, kind in HEAT_ROWS:
        if S.get(key) is None:
            s = get_col(m, col, f"mapa de calor, {label}")
            if s is None:
                continue
            if kind == "m":
                S[key] = series_list(compose_12m(s), months)
                S[key + "_m"] = series_list(s, months)
            else:
                S[key] = series_list(s, months)
        keep.append({"k": key, "label": label, "lv": level, "g": HEAT_GROUPS.get(key)})
    if sum(1 for r in keep if r["lv"] == 2) < 3:
        warn("mapa de calor: sin desglose por rubros todavía; se omite")
        return []
    return keep


def build_shock(m: pd.DataFrame) -> dict | None:
    """Mes con la mayor inflación mensual de los últimos 12 meses y qué rubros la explican.
    Sirve para anotar el gráfico y explicar por qué divergen subyacente y sin alimentos y energía."""
    full = m["ipc_var_mensual"].dropna()
    s = full.iloc[-12:]
    ts = s.idxmax()
    out = {"m": month_key(ts), "ipc": num(s.max(), 2), "cause": SHOCK_CAUSES.get(month_key(ts))}
    # Último mes anterior con un alza mensual igual o mayor (para decir "la mayor desde ...").
    prev = full[(full.index < ts) & (full >= s.max())]
    out["record_since"] = month_key(prev.index.max()) if not prev.empty else None
    for key, col in [("comb", "ipc_nosub_combustibles_var_mensual"), ("trans", "ipc_nosub_transportes_var_mensual"),
                     ("alim", "ipc_nosub_alimentos_var_mensual")]:
        if col in m.columns and not pd.isna(m.at[ts, col]):
            out[key] = num(m.at[ts, col], 1)
            out[key + "12"] = num(compose_12m(m[col]).dropna().iloc[-1], 1)
    # Solo se anota si el choque es inusual: más de 1 pp en el mes.
    return out if out["ipc"] > 1 and "comb" in out else None


def check_composition(m: pd.DataFrame) -> None:
    """Control: la 12m compuesta desde la mensual debe reproducir la 12m publicada."""
    for mcol, dcol in [("ipc_var_mensual", "ipc_var12m"), ("ipc_subyacente_var_mensual", "ipc_subyacente_var12m"),
                       ("ipc_sin_alim_energia_var_mensual", "ipc_sin_alim_energia_var12m")]:
        if mcol in m.columns and dcol in m.columns:
            diff = (compose_12m(m[mcol]) - m[dcol]).loc["2002":].abs().max()
            print(f"  control composición {mcol} -> 12m: diferencia máx. desde 2002 = {diff:.3f} pp")


def build_region(comp: dict | None, months: pd.DatetimeIndex) -> dict | None:
    if comp is None or "paises" not in comp:
        return None
    p = comp["paises"].copy()
    p["fecha"] = pd.to_datetime(p["fecha"]).dt.to_period("M").dt.to_timestamp()
    high = comp.get("_high", set())
    metas = comp.get("metas")
    countries = []
    for iso, g in p.groupby("pais", sort=False):
        g = g.dropna(subset=["inflacion_12m"]).sort_values("fecha")
        if g.empty:
            continue
        s = g.set_index("fecha")["inflacion_12m"]
        meta = None
        if metas is not None:
            cur = metas[(metas.pais == iso) & metas.hasta.isna()]
            if not cur.empty:
                r = cur.sort_values("desde").iloc[-1]
                meta = {"c": num(r.meta_centro, 2), "lo": num(r.rango_inferior, 2),
                        "hi": num(r.rango_superior, 2)}
        cob = str(g["cobertura"].iloc[0]) if "cobertura" in g else ""
        countries.append({
            "iso": iso, "name": str(g["pais_nombre"].iloc[0]), "cob": cob,
            "start": month_key(s.index.min()), "v": [num(v, 2) for v in s.reindex(
                pd.date_range(s.index.min(), s.index.max(), freq="MS")).values],
            "last": num(s.iloc[-1], 2), "last_m": month_key(s.index.max()),
            "high": iso in high, "meta": meta,
            "max": num(s.max(), 1), "max_m": month_key(s.idxmax()),
        })
    if not countries:
        return None
    return {"countries": countries,
            "fuentes": {k: str(v) for k, v in (comp.get("fuentes") or {}).items()}}


def build_national(comp: dict | None, months: pd.DatetimeIndex, S: dict) -> str | None:
    if comp is None or "nacional" not in comp:
        return None
    n = comp["nacional"].copy()
    n["fecha"] = pd.to_datetime(n["fecha"]).dt.to_period("M").dt.to_timestamp()
    n = n.set_index("fecha").sort_index()
    if n["ipc_nacional_var12m"].dropna().empty:
        warn("IPC nacional sin variación de 12 meses; se omite Lima vs. nacional")
        return None
    S["nac12"] = series_list(n["ipc_nacional_var12m"], months)
    S["nacm"] = series_list(n["ipc_nacional_var_mensual"], months)
    return str(comp.get("_src_nac", "INEI"))


def last_two(s: pd.Series) -> tuple[pd.Timestamp, float, float | None]:
    s = s.dropna()
    return s.index[-1], s.iloc[-1], (s.iloc[-2] if len(s) > 1 else None)


def build_kpis(m: pd.DataFrame, real: pd.Series | None) -> dict:
    k = {}
    for key, col in [("tot12", "ipc_var12m"), ("totm", "ipc_var_mensual"),
                     ("sae12", "ipc_sin_alim_energia_var12m"), ("sub12", "ipc_subyacente_var12m"),
                     ("exp", "expectativa_inflacion_12m"), ("ref", "tasa_referencia")]:
        if col not in m.columns or m[col].dropna().empty:
            warn(f"indicador {key}: falta {col}")
            continue
        ts, v, prev = last_two(m[col])
        k[key] = {"v": num(v, 2), "prev": num(prev, 2), "m": month_key(ts)}
    if "totm" in k:
        s = m["ipc_var_mensual"].dropna()
        ts = s.index[-1]
        same = ts - pd.DateOffset(years=1)
        k["totm"]["yago"] = num(s.get(same), 2)
    if real is not None and not real.dropna().empty:
        ts, v, prev = last_two(real)
        k["real"] = {"v": num(v, 2), "prev": num(prev, 2), "m": month_key(ts)}
        # Tasa real con la tasa de referencia más reciente (si es de un mes posterior a la expectativa).
        if "ref" in k and k["ref"]["m"] > k["real"]["m"]:
            k["real"]["ref_now"] = num(k["ref"]["v"] - m["expectativa_inflacion_12m"].dropna().iloc[-1], 2)
    return k


def decade_table(m: pd.DataFrame) -> list[dict]:
    """Inflación promedio anual (geométrica) por década, desde la var% mensual."""
    s = m["ipc_var_mensual"].dropna()
    out = []
    for dec in range(1950, s.index.max().year + 1, 10):
        sub = s[(s.index.year >= dec) & (s.index.year < dec + 10)]
        if len(sub) < 12:
            continue
        g = (np.prod(1 + sub / 100) ** (12 / len(sub)) - 1) * 100
        out.append({"d": f"{dec}s", "from": month_key(sub.index.min()), "to": month_key(sub.index.max()),
                    "v": num(g, 1), "max": num(m["ipc_var12m"].loc[sub.index].max(), 1)})
    return out


def build_edu(m: pd.DataFrame, targets: list[dict]) -> dict:
    t12 = m["ipc_var12m"].dropna()
    imax = t12.idxmax()
    since02 = t12.loc["2002":]
    cur = targets[-1]
    since_t = t12.loc[pd.Timestamp(cur["desde"]):]
    inside = ((since_t >= cur["lo"]) & (since_t <= cur["hi"])).mean() * 100
    # Racha actual: meses consecutivos dentro / por encima / por debajo del rango vigente.
    state = np.where(since_t > cur["hi"], 1, np.where(since_t < cur["lo"], -1, 0))
    streak = 1
    for i in range(len(state) - 2, -1, -1):
        if state[i] != state[-1]:
            break
        streak += 1
    m02 = m["ipc_var_mensual"].loc["2002":].dropna()
    avg02 = (np.prod(1 + m02 / 100) ** (12 / len(m02)) - 1) * 100
    idx = m["ipc_indice"].dropna()
    base = pd.Timestamp("2001-12-01")
    pp = 100 * idx.iloc[-1] / idx.loc[base] if base in idx.index else None
    pmax02 = since_t.idxmax()  # inflación más alta desde que rige la meta vigente
    # Última vez dentro del rango antes de la racha actual.
    return {
        "max12": num(t12.max(), 0), "max12_m": month_key(imax),
        "avg02": num(avg02, 1), "max02": num(since_t.max(), 2), "max02_m": month_key(pmax02),
        "inside_pct": num(inside, 0), "inside_from": month_key(since_t.index.min()),
        "streak": int(streak), "streak_state": int(state[-1]),
        "pp_base": "2001-12", "pp_val": num(pp, 0), "pp_m": month_key(idx.index[-1]),
        "decades": decade_table(m),
        "sae_start": month_key(m["ipc_sin_alim_energia_var12m"].dropna().index.min()),
    }


def main() -> int:
    m = load_panel()
    comp = load_comparada()
    targets = build_targets(comp)

    t12 = m["ipc_var12m"].dropna()
    months = pd.date_range(t12.index.min(), t12.index.max(), freq="MS")
    print(f"  meses: {month_key(months[0])} a {month_key(months[-1])} ({len(months)})")

    S: dict[str, list | None] = {}
    for key, col in DIRECT.items():
        s = get_col(m, col, key)
        if s is not None:
            S[key] = series_list(s, months)
    # Tasa real ex ante = tasa de referencia - expectativa de inflación a 12 meses.
    real = None
    if "ref" in S and "exp" in S:
        real = (m["tasa_referencia"] - m["expectativa_inflacion_12m"]).dropna()
        S["real"] = series_list(real, months)
    check_composition(m)

    S["band_lo"], S["band_hi"], S["band_c"] = band_for_months(months, targets)
    heat = build_heat(m, months, S)
    shock = build_shock(m)
    src_nac = build_national(comp, months, S)
    region = build_region(comp, months)
    small = [{"k": k, "label": lab, "desc": desc} for k, lab, desc in SMALL if S.get(k) is not None]
    for k, lab, _ in SMALL:
        if S.get(k) is None:
            warn(f"panel pequeño '{lab}' omitido (sin datos)")

    # Recorta series sin ningún dato.
    S = {k: v for k, v in S.items() if v is not None and any(x is not None for x in v)}
    if "d3m" not in S and "sae3m" not in S:
        warn("sin series desestacionalizadas (var. 3 meses anualizada): se omite el gráfico de tendencia")

    data = {
        "generado": dt.date.today().isoformat(), "start": month_key(months[0]), "hasta": month_key(months[-1]),
        "S": S, "targets": targets, "kpi": build_kpis(m, real), "heat": heat, "small": small, "shock": shock,
        "region": region, "src_nac": src_nac, "edu": build_edu(m, targets),
    }

    html = TEMPLATE.read_text(encoding="utf-8")
    if PLACEHOLDER not in html:
        raise ValueError(f"La plantilla no tiene el marcador {PLACEHOLDER}")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html.replace(PLACEHOLDER, payload), encoding="utf-8")
    print(f"  {OUT.relative_to(PROJECT_DIR)}  ({OUT.stat().st_size / 1024:.0f} KB; {len(S)} series, "
          f"mapa de calor: {len(heat)} filas; región: {'sí' if region else 'omitida'}; "
          f"nacional: {'sí' if src_nac else 'omitido'})")
    OUT_ARTIFACT.write_text(artifact_version(OUT.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"  {OUT_ARTIFACT.relative_to(PROJECT_DIR)}  (versión para publicar en claude.ai)")
    if WARNINGS:
        print(f"  {len(WARNINGS)} aviso(s): bloques omitidos o con datos parciales (ver arriba)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
