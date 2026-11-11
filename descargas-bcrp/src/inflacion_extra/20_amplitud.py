"""Amplitud de la inflación: qué parte de los rubros del IPC sube más de 3 %, entre 1 % y 3 % o menos de 1 %.

Usa los 13 rubros de la clasificación sectorial del mapa de calor (nivel 2 de `HEAT_ROWS`): subyacente bienes (4),
subyacente servicios (5) y no subyacente (4). Juntos forman una partición del IPC: no se mezclan con sus padres
(bienes, servicios, subyacente) ni con la clasificación de transables, cuyos rubros repiten series.
Variación de 12 meses de cada rubro = composición de sus variaciones mensuales (igual que el mapa de calor).

Si el módulo de contribuciones (`10_contribuciones`, KEY `contrib`) entrega ponderaciones por rubro, calcula
además la versión ponderada (% de la canasta en cada tramo). Si no, solo la versión por número de rubros.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

KEY = "amplitud"
FLOOR = "2002-01-01"   # mismo inicio que el mapa de calor y los paneles pequeños
LO, HI = 1.0, 3.0      # tramos fijos (los del mapa de calor): < 1 %, 1 % a 3 %, > 3 %


def _num(v, nd=1):
    return None if v is None or pd.isna(v) else round(float(v), nd)


def _mk(ts) -> str:
    return f"{ts.year:04d}-{ts.month:02d}"


def _compose_12m(monthly: pd.Series) -> pd.Series:
    f = 1 + monthly / 100
    return (f.rolling(12, min_periods=12).apply(np.prod, raw=True) - 1) * 100


def _rubros(ctx) -> list[tuple[str, str, str]]:
    import visual_inflacion as vi   # ya está en sys.path (src/)
    m = ctx["m"]
    return [(k, lab, col) for k, lab, lv, col, kind in vi.HEAT_ROWS
            if lv == 2 and kind == "m" and col in m.columns and not m[col].dropna().empty]


def _weights(contrib, keys: list[str], months: pd.DatetimeIndex) -> pd.DataFrame | None:
    """Ponderaciones por rubro y mes desde la salida de `contrib`, si las trae para estos rubros.
    Formas aceptadas: {'pesos'|'weights'|'w': {clave: peso}} (fijas), o una lista de tramos
    [{'desde': 'YYYY-MM', 'hasta': 'YYYY-MM'|None, 'pesos': {clave: peso}}] (cambian con la base del IPC)."""
    if not isinstance(contrib, dict):
        return None
    # Forma de 10_contribuciones: {'rubros': [{'k', 'w', ...}], 'start12': 'YYYY-MM', ...}. Los pesos son los oficiales
    # de la base dic-2021; solo valen para variaciones de 12 meses que caen enteras en esa base (desde 'start12').
    if isinstance(contrib.get("rubros"), list) and all(isinstance(r, dict) and "k" in r and "w" in r for r in contrib["rubros"]):
        pes = {r["k"]: r["w"] for r in contrib["rubros"]}
        cand = [{"desde": (contrib.get("start12") or contrib.get("start")) + "-01" if (contrib.get("start12") or contrib.get("start")) else None,
                 "hasta": None, "pesos": pes}]
        return _weights({"pesos": cand}, keys, months)
    cand = None
    for name in ("pesos_heat", "pesos", "weights", "w", "ponderaciones"):
        if name in contrib:
            cand = contrib[name]
            break
    if cand is None:
        return None
    W = pd.DataFrame(np.nan, index=months, columns=keys)
    tramos = cand if isinstance(cand, list) else [{"desde": None, "hasta": None, "pesos": cand}]
    for t in tramos:
        if not isinstance(t, dict):
            return None
        p = t.get("pesos") or t.get("w") or t.get("weights")
        if not isinstance(p, dict):
            return None
        a = pd.Timestamp(t["desde"]) if t.get("desde") else months.min()
        b = pd.Timestamp(t["hasta"]) if t.get("hasta") else months.max()
        sel = (months >= a) & (months <= b)
        for k in keys:
            if k in p and p[k] is not None:
                W.loc[sel, k] = float(p[k])
    # Solo sirve si cubre todos los rubros en algún tramo.
    full = W.notna().all(axis=1)
    if not full.any():
        return None
    return W.where(full, np.nan)


def build(ctx) -> dict | None:
    m, months = ctx["m"], ctx["months"]
    rub = _rubros(ctx)
    if len(rub) < 10:
        ctx["warn"](f"amplitud: solo {len(rub)} rubros sectoriales disponibles; se omite")
        return None
    keys = [k for k, _, _ in rub]
    V = pd.DataFrame({k: _compose_12m(m[col]) for k, _, col in rub}).reindex(months)
    ok = V.notna().all(axis=1) & (V.index >= pd.Timestamp(FLOOR))
    hi = (V > HI).where(ok)
    lo = (V < LO).where(ok)
    mid = ((V >= LO) & (V <= HI)).where(ok)
    n = len(keys)
    out = {
        "n": n, "lo_t": LO, "hi_t": HI,
        "rubros": [{"k": k, "label": lab} for k, lab, _ in rub],
        "hi": [None if not o else _num(100 * h.sum() / n, 6) for o, (_, h) in zip(ok, hi.iterrows())],
        "mid": [None if not o else _num(100 * x.sum() / n, 6) for o, (_, x) in zip(ok, mid.iterrows())],
        "lo": [None if not o else _num(100 * x.sum() / n, 6) for o, (_, x) in zip(ok, lo.iterrows())],
    }
    last = V[ok].index.max()
    out["last_m"] = _mk(last)
    out["first_m"] = _mk(V[ok].index.min())
    out["cur"] = sorted([{"k": k, "label": lab, "v": _num(V.at[last, k], 4)} for k, lab, _ in rub],
                        key=lambda r: -(r["v"] if r["v"] is not None else -1e9))
    # Referencias para el texto: promedio desde 2002 y promedio en los meses con inflación total cerca del centro de la
    # meta (entre 1.5 % y 2.5 %), como compara el BCRP en su Reporte de Inflación con su propio índice de 188 rubros.
    share_hi = pd.Series(out["hi"], index=months, dtype="float")
    t12 = m["ipc_var12m"].reindex(months)
    out["avg_hi"] = _num(share_hi.mean(), 6)
    # Promedio de toda la muestra en años completos (2002 al último diciembre con dato).
    full = share_hi.dropna()
    last_dec = full.index[full.index.month == 12].max()
    out["avg_all"] = _num(full.loc[:last_dec].mean(), 6)
    out["avg_all_from"], out["avg_all_to"] = int(full.index.min().year), int(last_dec.year)
    near = share_hi[(t12 >= 1.5) & (t12 <= 2.5)].dropna()
    out["avg_hi_near"] = _num(near.mean(), 6) if len(near) >= 24 else None
    out["n_near"] = int(len(near))
    out["max_hi"] = _num(share_hi.max(), 0)
    out["max_hi_m"] = _mk(share_hi.idxmax())
    # Hace 12 meses, para comparar.
    prev = last - pd.DateOffset(years=1)
    out["hi_yago"] = _num(share_hi.get(prev), 6)

    W = _weights(ctx.get("extra", {}).get("contrib"), keys, months)
    if W is not None:
        okw = ok & W.notna().all(axis=1)
        tot = W.sum(axis=1)
        out["w_hi"] = [_num(100 * (W.loc[t] * (V.loc[t] > HI)).sum() / tot[t], 6) if okw[t] else None for t in months]
        out["w_mid"] = [_num(100 * (W.loc[t] * ((V.loc[t] >= LO) & (V.loc[t] <= HI))).sum() / tot[t], 6) if okw[t] else None for t in months]
        out["w_lo"] = [_num(100 * (W.loc[t] * (V.loc[t] < LO)).sum() / tot[t], 6) if okw[t] else None for t in months]
        out["w_first_m"] = _mk(W[okw].index.min())
        out["w_src"] = "ponderaciones oficiales del IPC base dic-2021, BCRP"
        for r in out["cur"]:
            r["w"] = _num(W.at[last, r["k"]], 2) if okw[last] else None
    else:
        ctx["warn"]("amplitud: sin ponderaciones por rubro de la extensión de contribuciones; solo versión por número de rubros")
    return out
