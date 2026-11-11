"""Poder adquisitivo: variación real de 12 meses de la remuneración mínima vital (RMV), la masa salarial del sector
formal y el ingreso mensual de Lima Metropolitana, deflactados con el IPC de Lima (`ipc_indice`).

- RMV (MTPE vía BCRP, S/ nominales): real 12m = (RMV_t / RMV_t−12) / (IPC_t / IPC_t−12) − 1.
- Masa salarial formal (SUNAT vía BCRP, millones de S/ nominales, desde 2015): igual, con el IPC del mes. Así la presenta
  el BCRP en su Reporte de Inflación («masa salarial formal ... en términos reales, var. % interanual»); con este cálculo se
  reproducen sus cifras de ene-2025 a abr-2026 con diferencias de 0.1 pp como máximo.
- Ingreso mensual de Lima (INEI, EPEN, S/ nominales): cada dato es un trimestre móvil que termina en ese mes, así que se
  deflacta con el promedio del IPC de esos mismos tres meses.
Cada serie con su último mes publicado; no se extrapola.
"""
from __future__ import annotations

import pandas as pd

KEY = "poder"

# Reajustes de la RMV fijados por decreto supremo que la serie del BCRP todavía puede no recoger. Solo se usan si son
# posteriores al último mes de la serie: el texto los menciona sin imputarlos (misma regla que data_macro_paises).
# Verificado en fuente primaria: RMV S/ 1,230 desde el 1-oct-2026 (DS 015-2026-TR), igual que el tablero regional.
RMV_DECRETOS = [
    {"m": "2026-10", "v": 1230, "norma": "DS 015-2026-TR"},
]


def _num(v, nd=2):
    return None if v is None or pd.isna(v) else round(float(v), nd)


def _mk(ts) -> str:
    return f"{ts.year:04d}-{ts.month:02d}"


def build(ctx) -> dict | None:
    m, months, warn = ctx["m"], ctx["months"], ctx["warn"]
    if "ipc_indice" not in m.columns:
        warn("poder adquisitivo: falta ipc_indice; se omite")
        return None
    p = m["ipc_indice"]
    p3 = p.rolling(3, min_periods=3).mean()
    out: dict = {}
    for key, col, defl, nd in [("rmv", "rmv", p, 0), ("masa", "masa_salarial_formal", p, 1), ("ing", "ingreso_mensual_lima", p3, 1)]:
        if col not in m.columns or m[col].dropna().empty:
            warn(f"poder adquisitivo: falta {col}; se omite su panel")
            continue
        s = m[col].dropna()
        nom12 = (s / s.shift(12) - 1) * 100
        real12 = ((s / s.shift(12)) / (defl / defl.shift(12)) - 1) * 100
        real12 = real12.reindex(s.index)
        last = s.index[-1]
        out[key] = [_num(x, nd) for x in s.reindex(months).values]
        out[key + "_r12"] = [_num(x, 6) for x in real12.reindex(months).values]
        out[key + "_n12"] = [_num(x, 6) for x in nom12.reindex(months).values]
        r = real12.dropna()
        out[key + "_last"] = {"m": _mk(last), "v": _num(s.iloc[-1], nd), "n12": _num(nom12.iloc[-1], 6),
                              "r12": _num(r.iloc[-1], 6) if not r.empty else None,
                              "r12_m": _mk(r.index[-1]) if not r.empty else None,
                              "first": _mk(s.index[0])}
        # Promedio de la variación real desde que hay datos comparables (o desde 2002).
        rr = r.loc["2002":]
        out[key + "_avg"] = _num(rr.mean(), 6) if len(rr) >= 24 else None
        out[key + "_neg_share"] = _num(100 * (rr < 0).mean(), 0) if len(rr) >= 24 else None
    if "rmv" in out:
        s = m["rmv"].dropna()
        changes = s[s.diff().fillna(0) != 0]
        if not changes.empty:
            ch = changes.index[-1]
            last = s.index[-1]
            # Poder de compra perdido desde el último aumento (RMV nominal fija): IPC del último aumento / IPC del último dato.
            out["rmv_change"] = {"m": _mk(ch), "v": _num(s[ch], 0), "prev": _num(s[s.index < ch].iloc[-1], 0),
                                 "nom_pct": _num((s[ch] / s[s.index < ch].iloc[-1] - 1) * 100, 6),
                                 "loss": _num((p[ch] / p[last] - 1) * 100, 6) if pd.notna(p.get(last)) else None,
                                 "ipc_since": _num((p[last] / p[ch] - 1) * 100, 6) if pd.notna(p.get(last)) else None,
                                 "to": _mk(last)}
        # Reajuste por decreto posterior al último dato de la serie (el más reciente).
        nuevos = [d for d in RMV_DECRETOS if d["m"] > _mk(s.index[-1])]
        if nuevos:
            d = max(nuevos, key=lambda x: x["m"])
            out["rmv_norma"] = {"m": d["m"], "v": d["v"], "norma": d["norma"],
                                "nom_pct": _num((d["v"] / s.iloc[-1] - 1) * 100, 6)}
    if not any(k in out for k in ("rmv", "masa", "ing")):
        return None
    return out
