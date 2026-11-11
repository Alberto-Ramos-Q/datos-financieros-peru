"""Pestaña «Episodio actual» del tablero de inflación (KEY `episodio`).

El contenido curado (títulos, causas, respuesta de política, fuentes, episodios con que se compara) está en
`config/episodio_actual.json`, separado del código: cambiar de episodio es editar ese archivo (ver su clave
`_como_reemplazar`). Aquí solo se calculan las cifras desde el panel del BCRP (`ctx["m"]`):

- `ep`: el episodio actual (racha más reciente de inflación de 12 meses fuera del rango meta): inicio, meses,
  nivel y pico, mayor alza mensual, «la más alta desde ...».
- `align`: el episodio actual y los anteriores de `comparar`, alineados por meses desde que salieron del rango
  (inflación de 12 meses, cambio de la tasa de referencia y expectativas).
- `rubros`: variación acumulada de cada rubro desde el inicio del episodio (o contribuciones, si la extensión
  `contrib` las dejó en `ctx["extra"]["contrib"]` en un formato reconocible).
- `pol`: tasa de referencia y expectativas, al inicio y al último dato.

Fuentes de cada afirmación curada: docs/inflacion_extra/episodio_fuentes.md
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

KEY = "episodio"

# Meses antes de la salida del rango que se muestran en los gráficos alineados.
LEAD = 6
# Meses que se muestran después del fin del episodio más largo (para ver la vuelta al rango).
TAIL = 3
# Tope del eje de meses alineados.
MAX_SPAN = 48

# Rubros por defecto (clasificación sectorial del BCRP; solo hojas, para no mezclar totales con sus partes).
DEFAULT_RUBROS = [
    ("ipc_nosub_combustibles_var_mensual", "Combustibles", "nc"),
    ("ipc_nosub_transportes_var_mensual", "Transportes", "nt"),
    ("ipc_nosub_alimentos_var_mensual", "Alimentos volátiles y básicos", "na"),
    ("ipc_nosub_servicios_publicos_var_mensual", "Servicios públicos", "np"),
    ("ipc_sub_bienes_alimentos_var_mensual", "Alimentos y bebidas (subyacente)", "sb"),
    ("ipc_sub_bienes_textiles_var_mensual", "Textiles y calzado", "sb"),
    ("ipc_sub_bienes_electrodomesticos_var_mensual", "Electrodomésticos", "sb"),
    ("ipc_sub_bienes_resto_industriales_var_mensual", "Otros productos industriales", "sb"),
    ("ipc_sub_serv_comidas_fuera_var_mensual", "Comidas fuera del hogar", "ss"),
    ("ipc_sub_serv_educacion_var_mensual", "Educación", "ss"),
    ("ipc_sub_serv_salud_var_mensual", "Salud", "ss"),
    ("ipc_sub_serv_alquileres_var_mensual", "Alquileres", "ss"),
    ("ipc_sub_serv_resto_var_mensual", "Otros servicios", "ss"),
]
# Grupos (mismos ids, nombres y colores que la sección de contribuciones del Tablero, extensión `contrib`).
GROUPS = [("ss", "Servicios subyacentes"), ("sb", "Bienes subyacentes"), ("na", "Alimentos volátiles y básicos"),
          ("nt", "Transportes"), ("nc", "Combustibles"), ("np", "Servicios públicos")]


def mk(ts: pd.Timestamp) -> str:
    return pd.Timestamp(ts).strftime("%Y-%m")


def rnd(v, nd: int = 2):
    return None if v is None or pd.isna(v) else round(float(v), nd)


def band_at(targets: list[dict], ts: pd.Timestamp) -> tuple[float, float]:
    for t in reversed(targets):
        a = pd.Timestamp(t["desde"]).to_period("M").to_timestamp()
        b = pd.Timestamp(t["hasta"]) if t.get("hasta") else pd.Timestamp.max
        if a <= ts <= b:
            return t["lo"], t["hi"]
    return targets[-1]["lo"], targets[-1]["hi"]


def find_runs(t12: pd.Series, targets: list[dict]) -> list[dict]:
    """Rachas de meses consecutivos fuera del rango meta (por encima: +1; por debajo: -1), desde 2006, cuando la
    meta empezó a evaluarse cada mes con la variación de 12 meses."""
    s = t12.loc["2006-01":].dropna()
    runs, cur = [], None
    for ts, v in s.items():
        lo, hi = band_at(targets, ts)
        v2 = round(float(v), 2)   # regla única del tablero: valor publicado (2 decimales) frente al límite, estricto
        st = 1 if v2 > hi else (-1 if v2 < lo else 0)
        if cur and (st != cur["side"]):
            runs.append(cur)
            cur = None
        if st != 0 and cur is None:
            cur = {"side": st, "start": ts, "end": ts}
        elif st != 0:
            cur["end"] = ts
    if cur:
        runs.append(cur)
    last = s.index.max()
    for r in runs:
        seg = s.loc[r["start"]:r["end"]]
        r["n"] = len(seg)
        r["ongoing"] = r["end"] == last
        pk = seg.idxmax() if r["side"] > 0 else seg.idxmin()
        r["peak"], r["peak_m"] = float(seg.loc[pk]), pk
    return runs


def accumulated(monthly: pd.Series, a: pd.Timestamp, b: pd.Timestamp) -> float | None:
    seg = monthly.loc[a:b].dropna()
    if len(seg) < len(pd.date_range(a, b, freq="MS")):
        return None
    return (np.prod(1 + seg / 100) - 1) * 100


def compose_12m(monthly: pd.Series) -> pd.Series:
    return ((1 + monthly / 100).rolling(12, min_periods=12).apply(np.prod, raw=True) - 1) * 100


def aligned(series: pd.Series | None, start: pd.Timestamp, k0: int, k1: int, nd: int = 2, base: float | None = None):
    """Valores de la serie desde k0 hasta k1 meses respecto de `start` (en k = 0 sale del rango)."""
    if series is None:
        return None
    out = []
    for k in range(k0, k1 + 1):
        ts = start + pd.DateOffset(months=k)
        v = series.get(ts)
        if v is None or pd.isna(v):
            out.append(None)
        else:
            out.append(rnd(v - base if base is not None else v, nd))
    return out


def contrib_from_extra(contrib, a: str, b: str) -> list[dict] | None:
    """Aporte exacto de cada rubro a la inflación acumulada del episodio, con las ponderaciones oficiales que deja la
    extensión `contrib` (10_contribuciones.py): por rubro `w` (peso) e `i` (índice dic-2021 = 100), y `agg` (índice
    agregado) y `w_sum` (suma de pesos). Desde el mes previo al inicio (a0) hasta el último dato (b):
        aporte_i = w_i × (I_i,b − I_i,a0) / (agg_a0 × suma de pesos) × 100
    La suma de los aportes es la variación acumulada del agregado. Si el formato no se reconoce o el periodo cae fuera
    de la base 2021 del IPC, devuelve None y la página usa las variaciones."""
    try:
        rows, start, agg, wsum = contrib.get("rubros"), contrib.get("start"), contrib.get("agg"), contrib.get("w_sum")
        if not rows or not start or not agg or not wsum:
            return None
        base = pd.Timestamp(start + "-01")
        pos = lambda m: (pd.Timestamp(m + "-01").year - base.year) * 12 + pd.Timestamp(m + "-01").month - base.month  # noqa: E731
        ia, ib = pos(a) - 1, pos(b)
        if ia < 0 or ib >= len(agg) or agg[ia] is None:
            return None
        out = []
        for r in rows:
            idx, w = r.get("i"), r.get("w")
            if not isinstance(idx, list) or w is None or ib >= len(idx) or idx[ia] is None or idx[ib] is None:
                return None
            out.append({"label": str(r["label"]), "g": r.get("g"), "c": rnd(w * (idx[ib] - idx[ia]) / (agg[ia] * wsum) * 100, 2),
                        "acc": rnd((idx[ib] / idx[ia] - 1) * 100, 2), "w": w})
        return out
    except Exception:  # noqa: BLE001
        return None


def build(ctx: dict) -> dict | None:
    m: pd.DataFrame = ctx["m"]
    warn = ctx["warn"]
    targets = ctx["targets"]
    cfg_path = Path(ctx["project_dir"]) / "config" / "episodio_actual.json"
    if not cfg_path.exists():
        warn("episodio: falta config/episodio_actual.json; se omite la pestaña")
        return None
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

    t12 = m["ipc_var12m"].dropna()
    totm = m["ipc_var_mensual"].dropna()
    last = t12.index.max()
    runs = find_runs(t12, targets)
    print("  episodio: episodios detectados fuera del rango (6+ meses): " +
          ", ".join(f"{mk(r['start'])} a {mk(r['end'])} ({r['n']} m)" for r in runs if r["n"] >= 6))

    # Episodio actual.
    if cfg.get("inicio", "auto") == "auto":
        if not runs:
            warn("episodio: no hay rachas fuera del rango meta; se omite la pestaña")
            return None
        cur = runs[-1]
    else:
        ts = pd.Timestamp(cfg["inicio"] + "-01")
        cur = next((r for r in runs if r["start"] == ts), None)
        if cur is None:
            warn(f"episodio: el inicio {cfg['inicio']} de la config no coincide con ninguna racha fuera del rango")
            return None
    if cfg.get("inicio_esperado") and cfg["inicio_esperado"] != mk(cur["start"]):
        warn(f"episodio: según los datos el episodio empieza en {mk(cur['start'])}, no en {cfg['inicio_esperado']} "
             "(inicio_esperado de la config): revisar los textos")
    if cfg.get("redactado_con_dato") and cfg["redactado_con_dato"] < mk(last):
        warn(f"episodio: los textos se redactaron con el dato de {cfg['redactado_con_dato']} y el panel llega a "
             f"{mk(last)}: revisar config/episodio_actual.json")
    if not cur["ongoing"]:
        warn(f"episodio: el episodio {mk(cur['start'])} terminó en {mk(cur['end'])}: actualizar los textos")

    a, b = cur["start"], last
    seg_m = totm.loc[a:b]
    mx = seg_m.idxmax()
    prev = totm[(totm.index < mx) & (totm >= totm.loc[mx])]
    lvl_prev = t12[(t12.index < a) & (t12 >= t12.loc[last])] if cur["side"] > 0 else t12[(t12.index < a) & (t12 <= t12.loc[last])]
    lo, hi = band_at(targets, last)
    ep = {
        "start": mk(a), "end": mk(cur["end"]), "ongoing": bool(cur["ongoing"]), "side": cur["side"], "n": cur["n"],
        "start_v": rnd(t12.loc[a]), "prev_m": mk(a - pd.DateOffset(months=1)),
        "prev_v": rnd(t12.get(a - pd.DateOffset(months=1))),
        "last_m": mk(last), "last_v": rnd(t12.loc[last]), "peak_v": rnd(cur["peak"]), "peak_m": mk(cur["peak_m"]),
        "totm_last": rnd(totm.loc[last]), "totm_max": rnd(totm.loc[mx]), "totm_max_m": mk(mx),
        "totm_record_since": mk(prev.index.max()) if not prev.empty else None,
        "level_since": mk(lvl_prev.index.max()) if not lvl_prev.empty else None,
        "acc": rnd(accumulated(totm, a, b)), "lo": lo, "hi": hi,
    }
    if "ipc_sin_alim_energia_var12m" in m:
        sae = m["ipc_sin_alim_energia_var12m"].dropna()
        ep["sae_last"], ep["sae_m"] = rnd(sae.iloc[-1]), mk(sae.index[-1])

    # Episodios alineados.
    comp = []
    for c in cfg.get("comparar", []):
        ts = pd.Timestamp(c["inicio"] + "-01")
        r = next((r for r in runs if r["start"] == ts), None)
        if r is None:
            warn(f"episodio: no se encontró un episodio fuera del rango que empiece en {c['inicio']}; se omite")
            continue
        if r is cur:
            continue
        comp.append((c, r))
    span = min(MAX_SPAN, max([r["n"] for _, r in comp] + [cur["n"]]) + TAIL)
    ctx_now = cfg.get("contexto_actual") or {}
    ref = m["tasa_referencia"] if "tasa_referencia" in m else None
    exp = m["expectativa_inflacion_12m"] if "expectativa_inflacion_12m" in m else None
    real = (ref - exp).dropna() if ref is not None and exp is not None else None   # tasa real ex ante
    eps = []
    for c, r, now in [({"etiqueta": "Episodio actual", **ctx_now}, cur, True)] + [(cc, rr, False) for cc, rr in comp]:
        s, label = r["start"], c["etiqueta"]
        ref0 = ref.get(s - pd.DateOffset(months=1)) if ref is not None else None
        e = {
            "label": label, "now": now, "start": mk(s), "end": mk(r["end"]), "n": r["n"], "ongoing": bool(r["ongoing"]),
            "peak": rnd(r["peak"]), "peak_m": mk(r["peak_m"]), "peak_k": int((r["peak_m"].year - s.year) * 12 + r["peak_m"].month - s.month),
            "t12": aligned(t12, s, -LEAD, span),
            "ref": aligned(ref, s, -LEAD, span), "ref0": rnd(ref0), "exp": aligned(exp, s, -LEAD, span),
            "real": aligned(real, s, -LEAD, span) if real is not None else None,
            "contexto": c.get("contexto"), "fuentes": c.get("fuentes", []),
        }
        eps.append(e)
    align = {"k0": -LEAD, "k1": span, "eps": eps}

    # Rubros: variación acumulada en el episodio (a..b) y variación de 12 meses al último dato.
    rub_cfg = cfg.get("rubros") or DEFAULT_RUBROS
    rubros = []
    for col, label, g in rub_cfg:
        if col not in m or m[col].dropna().empty:
            warn(f"episodio: falta el rubro {col}; se omite")
            continue
        s = m[col].dropna()
        bb = min(b, s.index.max())
        acc = accumulated(s, a, bb)
        if acc is None:
            continue
        rubros.append({"label": label, "g": g, "acc": rnd(acc, 2), "v12": rnd(compose_12m(s).loc[bb], 2),
                       "m": mk(bb)})
    rubros.sort(key=lambda r: -r["acc"])
    ref_rows = {"ipc": rnd(accumulated(totm, a, b), 2)}
    if "ipc_sin_alim_energia_var_mensual" in m:
        ref_rows["sae"] = rnd(accumulated(m["ipc_sin_alim_energia_var_mensual"], a, b), 2)
    contrib = contrib_from_extra((ctx.get("extra") or {}).get("contrib") or {}, mk(a), mk(b))
    if contrib is None and (ctx.get("extra") or {}).get("contrib"):
        warn("episodio: la extensión contrib existe pero su formato no se reconoce; se usan variaciones")
    if contrib:
        tot = sum(r["c"] for r in contrib)
        print(f"  episodio: aportes por rubro (ponderaciones oficiales) suman {tot:.2f} pp; IPC acumulado {ep['acc']:.2f}%")
        if ep["acc"] is not None and abs(tot - ep["acc"]) > 0.1:
            warn(f"episodio: los aportes suman {tot:.2f} pp y el IPC acumulado es {ep['acc']:.2f}%: se usan variaciones")
            contrib = None

    # Política: tasa de referencia y expectativas.
    pol = {}
    if ref is not None:
        rs = ref.dropna()
        pol.update(ref_now=rnd(rs.iloc[-1]), ref_m=mk(rs.index[-1]), ref_start=rnd(ref.get(a - pd.DateOffset(months=1))),
                   ref_changes=int((rs.loc[a:].diff().fillna(0) != 0).sum()))
        unchanged = rs[rs != rs.iloc[-1]]
        pol["ref_since"] = mk(unchanged.index.max() + pd.DateOffset(months=1)) if not unchanged.empty else None
    if exp is not None:
        es = exp.dropna()
        pol.update(exp_now=rnd(es.iloc[-1]), exp_m=mk(es.index[-1]), exp_start=rnd(exp.get(a - pd.DateOffset(months=1))))
        # Regla única del tablero: valor publicado (2 decimales) frente al límite, estricto; a 0.10 pp o menos del
        # límite se dice «ligeramente» por encima/por debajo.
        es2 = es.round(2)
        v2 = float(es2.iloc[-1])
        pol["exp_state"] = 1 if v2 > hi else (0 if v2 >= lo else -1)
        pol["exp_gap"] = rnd(v2 - hi if v2 > hi else (lo - v2 if v2 < lo else 0))
        above = es[es2 > hi]
        pol["exp_above_since"] = None
        if not above.empty and above.index.max() == es.index.max():
            k = es.index.max()
            while k - pd.DateOffset(months=1) in above.index:
                k -= pd.DateOffset(months=1)
            pol["exp_above_since"] = mk(k)

    if real is not None:
        a0 = a - pd.DateOffset(months=1)
        pol.update(real_start=rnd(real.get(a0)), real_start_m=mk(a0), real_now=rnd(real.iloc[-1]), real_m=mk(real.index[-1]))

    # Amplitud con 13 grupos (extensión `amplitud`), para dejar dicho que es otra medida que la del BCRP (188 rubros).
    amp = None
    xa = (ctx.get("extra") or {}).get("amplitud") or {}
    try:
        hi_s = [v for v in xa.get("hi", []) if v is not None]
        if hi_s and xa.get("last_m"):
            amp = {"v": rnd(hi_s[-1], 0), "m": xa["last_m"], "n": xa.get("n")}
    except Exception:  # noqa: BLE001
        amp = None

    out_cfg = {k: cfg.get(k) for k in ("id", "titulo", "bajada", "causas", "politica", "fuentes",
                                       "redactado_con_dato", "redactado_el")}
    return {"cfg": out_cfg, "ep": ep, "groups": [{"id": g, "label": lab} for g, lab in GROUPS], "align": align, "rubros": rubros, "rub_ref": ref_rows,
            "contrib": contrib, "pol": pol, "amp": amp}
