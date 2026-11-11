"""Extensión `contrib`: contribución de cada rubro a la inflación (puntos porcentuales).

Usa las ponderaciones oficiales del IPC de Lima Metropolitana base Dic.2021 = 100 para la
clasificación sectorial del BCRP (subyacente / no subyacente), guardadas en
`config/ponderaciones_ipc.csv` (fuente: BCRP, Nota Semanal, cuadro 63). Ver
`docs/inflacion_extra/contribuciones_fuentes.md`.

Cálculo (Laspeyres, como el IPC del INEI desde enero de 2022):
  - Índice de cada rubro en base dic-2021 = 100, encadenando su var% mensual desde ene-2022.
  - Índice agregado = suma ponderada de los índices de los 13 rubros / suma de pesos.
  - Contribución a la variación de h meses del rubro i en t:
        c_i = w_i × I_i,t−h / (Σ w × I)_t−h × var%_h,i
    con h = 12 (12 meses) o h = 1 (mes). La suma de las c_i es la variación del agregado.
  - Control: esa suma se compara con la inflación publicada (12 meses y mensual).
Antes de 2022 el IPC tenía otra base (2009) y otras ponderaciones: no se calcula. La
contribución a 12 meses existe desde dic-2022 (el primer mes cuya comparación cae entera en la
base 2021); la mensual, desde ene-2022.
"""
from __future__ import annotations

import pandas as pd

KEY = "contrib"

BASE = pd.Timestamp("2021-12-01")    # base del IPC: dic-2021 = 100
FIRST = pd.Timestamp("2022-01-01")   # primer mes con las ponderaciones base 2021

# Rubros de la clasificación sectorial (partición del IPC): (clave, columna, grupo de presentación).
# Las claves son las del mapa de calor de visual_inflacion.py.
RUBROS = [
    ("h_sba", "ipc_sub_bienes_alimentos_var_mensual", "sb"),
    ("h_sbt", "ipc_sub_bienes_textiles_var_mensual", "sb"),
    ("h_sbe", "ipc_sub_bienes_electrodomesticos_var_mensual", "sb"),
    ("h_sbr", "ipc_sub_bienes_resto_industriales_var_mensual", "sb"),
    ("h_ssc", "ipc_sub_serv_comidas_fuera_var_mensual", "ss"),
    ("h_sse", "ipc_sub_serv_educacion_var_mensual", "ss"),
    ("h_sss", "ipc_sub_serv_salud_var_mensual", "ss"),
    ("h_ssa", "ipc_sub_serv_alquileres_var_mensual", "ss"),
    ("h_ssr", "ipc_sub_serv_resto_var_mensual", "ss"),
    ("h_na", "ipc_nosub_alimentos_var_mensual", "na"),
    ("h_nc", "ipc_nosub_combustibles_var_mensual", "nc"),
    ("h_nt", "ipc_nosub_transportes_var_mensual", "nt"),
    ("h_np", "ipc_nosub_servicios_publicos_var_mensual", "np"),
]
# Etiquetas cortas para la página (la del CSV es la oficial, más larga).
SHORT = {
    "h_sba": "Alimentos y bebidas (subyacente)", "h_sbt": "Textiles y calzado", "h_sbe": "Electrodomésticos",
    "h_sbr": "Otros productos industriales", "h_ssc": "Comidas fuera del hogar", "h_sse": "Educación",
    "h_sss": "Salud", "h_ssa": "Alquileres", "h_ssr": "Otros servicios",
    "h_na": "Alimentos volátiles y básicos", "h_nc": "Combustibles", "h_nt": "Transportes",
    "h_np": "Servicios públicos",
}
# Nombres abreviados fijos para pantallas angostas u otros gráficos (sin perder el sentido).
ABBR = {
    "h_sba": "Alim. y bebidas (subyac.)", "h_sbt": "Textiles y calzado", "h_sbe": "Electrodomésticos",
    "h_sbr": "Otros prod. industriales", "h_ssc": "Comidas fuera del hogar", "h_sse": "Educación",
    "h_sss": "Salud", "h_ssa": "Alquileres", "h_ssr": "Otros servicios",
    "h_na": "Alim. volátiles y básicos", "h_nc": "Combustibles", "h_nt": "Transportes",
    "h_np": "Servicios públicos",
}
# Color de cada grupo (claro, oscuro). Referencia común del tablero: la plantilla los publica como --ctb-<grupo>.
# Paleta del tablero (s1–s4) más un violeta claro y un gris; separación validada (daltonismo y visión normal).
GROUP_COLORS = {
    "ss": ("#001e6b", "#9fb2e6"), "sb": ("#1c7ce5", "#2482eb"), "na": ("#25624f", "#4abba1"),
    "nt": ("#9a8bc0", "#7d6aa8"), "nc": ("#722f9a", "#cb91f4"), "np": ("#868a93", "#8a8f9c"),
}
# Grupos del gráfico en el tiempo, en el orden de apilado (de abajo hacia arriba).
GROUPS = [
    ("ss", "Servicios subyacentes"),
    ("sb", "Bienes subyacentes"),
    ("na", "Alimentos volátiles y básicos"),
    ("nt", "Transportes"),
    ("nc", "Combustibles"),
    ("np", "Servicios públicos"),
]
# Controles: agregado publicado (var% mensual) que debe reproducirse con sus rubros.
CHECKS = [
    ("Subyacente: bienes", "ipc_sub_bienes_var_mensual", ["h_sba", "h_sbt", "h_sbe", "h_sbr"]),
    ("Subyacente: servicios", "ipc_sub_servicios_var_mensual", ["h_ssc", "h_sse", "h_sss", "h_ssa", "h_ssr"]),
    ("Subyacente", "ipc_subyacente_var_mensual", [k for k, _, g in RUBROS if g in ("sb", "ss")]),
]


def _r(v, nd=3):
    return None if v is None or pd.isna(v) else round(float(v), nd)


def build(ctx: dict) -> dict | None:
    m: pd.DataFrame = ctx["m"]
    warn = ctx["warn"]
    path = ctx["project_dir"] / "config" / "ponderaciones_ipc.csv"
    if not path.exists():
        warn("contribuciones: falta config/ponderaciones_ipc.csv")
        return None
    pw = pd.read_csv(path, encoding="utf-8").set_index("rubro")

    cols = {k: c for k, c, _ in RUBROS}
    missing = [c for c in cols.values() if c not in m.columns or c not in pw.index]
    if missing:
        warn(f"contribuciones: faltan series o ponderaciones de {missing}; se omite")
        return None
    for col in ("ipc_var_mensual", "ipc_var12m"):
        if col not in m.columns:
            warn(f"contribuciones: falta {col}; se omite")
            return None

    w = pd.Series({k: float(pw.at[c, "peso"]) for k, c in cols.items()})
    var_m = pd.DataFrame({k: m[c] for k, c in cols.items()}).loc[FIRST:]
    # Último mes con todos los rubros y la inflación publicada.
    ok = var_m.notna().all(axis=1) & m["ipc_var_mensual"].reindex(var_m.index).notna()
    if not ok.any():
        warn("contribuciones: sin datos desde 2022")
        return None
    last = ok[ok].index.max()
    var_m = var_m.loc[:last]
    if var_m.isna().any().any():
        warn("contribuciones: hay meses sin dato en algún rubro desde 2022; se omite")
        return None

    # Índices base dic-2021 = 100 (encadenando la var% mensual) y agregado ponderado.
    idx = 100 * (1 + var_m / 100).cumprod()
    idx.loc[BASE] = 100.0
    idx = idx.sort_index()
    agg = (idx * w).sum(axis=1) / w.sum()

    def contrib(h: int) -> pd.DataFrame:
        c = idx.diff(h).mul(w, axis=1).div(w.sum()).div(agg.shift(h), axis=0) * 100
        return c.loc[FIRST:]

    c12, cm = contrib(12), contrib(1)
    months = pd.date_range(FIRST, last, freq="MS")
    s12 = c12.sum(axis=1, min_count=len(w)).reindex(months)
    sm = cm.sum(axis=1, min_count=len(w)).reindex(months)
    pub12 = m["ipc_var12m"].reindex(months)
    pubm = m["ipc_var_mensual"].reindex(months)
    e12, em = (s12 - pub12).dropna(), (sm - pubm).dropna()

    # Variación de 12 meses de cada rubro (desde los índices) y peso efectivo (peso actualizado por precios).
    v12 = (idx / idx.shift(12) - 1) * 100
    weff12 = idx.shift(12).mul(w, axis=1).div(agg.shift(12), axis=0) / w.sum() * 100

    checks = []
    for label, col, keys in CHECKS:
        if col not in m.columns:
            continue
        sub = (idx[keys] * w[keys]).sum(axis=1) / w[keys].sum()
        d = ((sub / sub.shift(1) - 1) * 100 - m[col].reindex(sub.index)).loc[FIRST:].abs()
        checks.append({"label": label, "w": _r(w[keys].sum(), 1), "pub_w": _r(pw.at[col, "peso"], 1) if col in pw.index else None,
                       "err": _r(d.max(), 6)})

    key = lambda ts: ts.strftime("%Y-%m")  # noqa: E731
    val = {
        "w_sum": _r(w.sum(), 1),
        "err12": _r(e12.abs().max(), 6), "err12_m": key(e12.abs().idxmax()), "err12_from": key(e12.index.min()),
        "errm": _r(em.abs().max(), 6), "errm_m": key(em.abs().idxmax()), "errm_from": key(em.index.min()),
        "checks": checks,
    }
    print(f"  contribuciones: suma de rubros vs inflación publicada, error máx. 12 m = {val['err12']:.4f} pp "
          f"({val['err12_m']}), mensual = {val['errm']:.4f} pp ({val['errm_m']}); pesos suman {val['w_sum']}")
    for ch in checks:
        print(f"    control {ch['label']}: var% mensual reconstruida vs publicada, error máx. {ch['err']:.4f} pp")

    # 6 decimales: la página redondea una sola vez al mostrar (evita dobles redondeos como 24.154 -> 24.15 -> 24.1).
    def lst(s: pd.Series, nd=6):
        return [_r(v, nd) for v in s.reindex(months).values]

    rubros = []
    for k, col, g in RUBROS:
        rubros.append({
            "k": k, "label": SHORT[k], "corto": ABBR[k], "label_of": str(pw.at[col, "etiqueta"]), "g": g, "w": _r(w[k], 1),
            "c12": lst(c12[k]), "cm": lst(cm[k]), "v12": lst(v12[k]), "vm": lst(var_m[k]),
            "we12": lst(weff12[k]),
            # Para otras extensiones: alias de `cm` y del grupo, e índice del rubro (dic-2021 = 100) para calcular
            # contribuciones acumuladas exactas: w × (I_b − I_a) / (agg_a × suma de pesos) × 100.
            "c_m": lst(cm[k]), "grupo": dict(GROUPS)[g], "i": lst(idx[k]),
        })
    src = pw.loc[cols["h_sba"]]
    return {
        "start": key(FIRST), "start12": key(e12.index.min()), "hasta": key(last), "base": key(BASE),
        "groups": [{"id": g, "label": lab, "color": GROUP_COLORS[g][0], "color_dark": GROUP_COLORS[g][1],
                    "css": f"--ctb-{g}"} for g, lab in GROUPS],
        # Mapa estable rubro -> nombres, grupo y color (referencia común para otras extensiones). Claves = las del
        # mapa de calor (h_*); `col` = nombre_corto de la serie mensual en config/series.csv.
        "map": {k: {"label": SHORT[k], "corto": ABBR[k], "col": c, "g": g, "grupo": dict(GROUPS)[g],
                    "color": GROUP_COLORS[g][0], "color_dark": GROUP_COLORS[g][1], "css": f"var(--ctb-{g})",
                    "w": _r(w[k], 1)} for k, c, g in RUBROS},
        "rubros": rubros,
        "tot12": lst(pub12), "totm": lst(pubm), "sum12": lst(s12), "summ": lst(sm),
        "agg": lst(agg), "w_sum": _r(w.sum(), 1),
        "val": val,
        "src": {"url": str(src["url"]), "cuadro": str(src["pagina_cuadro"])},
    }
