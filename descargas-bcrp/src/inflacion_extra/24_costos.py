"""Transmisión de costos: petróleo WTI y tipo de cambio (costos de importar) frente a los precios al por mayor (IPM),
los rubros importados y los vinculados al tipo de cambio del IPC. Cada serie va en su propio panel, con un solo eje;
la página alinea los paneles en el tiempo. Aquí solo se arman el WTI y el tipo de cambio (nivel y var% 12 meses);
IPM, importado y vinculados ya están en `S` (ipm12, imp12, vtc12) y la página los toma de ahí.

No atribuye causas a meses concretos: solo describe co-movimientos y da el último dato de cada serie con su mes.
"""
from __future__ import annotations

import pandas as pd

KEY = "costos"


def _num(v, nd=2):
    return None if v is None or pd.isna(v) else round(float(v), nd)


def _mk(ts) -> str:
    return f"{ts.year:04d}-{ts.month:02d}"


def _series(m, col, months, warn, what):
    if col not in m.columns or m[col].dropna().empty:
        warn(f"costos: falta la serie {col} ({what}); se omite su panel")
        return None
    return m[col]


def build(ctx) -> dict | None:
    m, months, S, warn = ctx["m"], ctx["months"], ctx["S"], ctx["warn"]
    out: dict = {}
    for key, col, nd, what in [("wti", "petroleo_wti", 2, "petróleo WTI, US$ por barril"),
                               ("tc", "tc_interbancario_prom", 3, "tipo de cambio interbancario promedio, S/ por US$")]:
        s = _series(m, col, months, warn, what)
        if s is None:
            continue
        s = s.dropna()
        v12 = (s / s.shift(12) - 1) * 100
        v12 = v12.where(s.shift(12).notna())
        out[key] = [_num(x, nd) for x in s.reindex(months).values]
        out[key + "12"] = [_num(x, 6) for x in v12.reindex(months).values]
        last = s.index[-1]
        out[key + "_last"] = {"m": _mk(last), "v": _num(s.iloc[-1], nd), "v12": _num(v12.iloc[-1], 6)}
    for key in ("ipm12", "imp12", "vtc12"):
        if S.get(key) is None:
            warn(f"costos: falta {key} en S; se omite su panel")
    if "wti" not in out and "tc" not in out:
        return None
    return out
