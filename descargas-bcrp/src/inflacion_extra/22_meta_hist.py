"""Cumplimiento de la meta de inflación: por año desde 2002, % de meses con la inflación de 12 meses dentro del rango
meta vigente en cada mes (2.5 % ± 1 hasta enero de 2007; 1 % a 3 % desde febrero de 2007, según `ctx["targets"]`),
y rachas fuera del rango (por encima o por debajo): inicio, fin, duración y valor extremo. Incluye la racha vigente,
que puede ser dentro, por encima o por debajo del rango.

Entre 2002 y 2005 la meta se evaluaba solo con la inflación de diciembre; el cálculo mensual de esos años es de referencia
(la página lo aclara y marca además si diciembre quedó dentro).
"""
from __future__ import annotations

import pandas as pd

KEY = "meta_hist"
START = pd.Timestamp("2002-01-01")
DEC_ONLY_UNTIL = 2005   # hasta 2005 la meta se evaluaba solo con la inflación de diciembre (BCRP, RI ene-2006)


def _num(v, nd=2):
    return None if v is None or pd.isna(v) else round(float(v), nd)


def _mk(ts) -> str:
    return f"{ts.year:04d}-{ts.month:02d}"


def _band(months: pd.DatetimeIndex, targets: list[dict]) -> pd.DataFrame:
    b = pd.DataFrame(index=months, columns=["lo", "hi", "c"], dtype="float")
    for t in targets:
        a = pd.Timestamp(t["desde"]).to_period("M").to_timestamp()
        z = pd.Timestamp(t["hasta"]) if t.get("hasta") else months.max()
        sel = (months >= a) & (months <= z)
        b.loc[sel, "lo"], b.loc[sel, "hi"] = t["lo"], t["hi"]
        b.loc[sel, "c"] = t.get("c")
    return b


def build(ctx) -> dict | None:
    m, targets = ctx["m"], ctx["targets"]
    t12 = m["ipc_var12m"].dropna()
    t12 = t12[t12.index >= START]
    if t12.empty:
        return None
    b = _band(t12.index, targets)
    ok = b["lo"].notna() & b["hi"].notna()
    t12, b = t12[ok], b[ok]
    state = pd.Series(0, index=t12.index)
    state[t12 > b["hi"]] = 1
    state[t12 < b["lo"]] = -1

    # Régimen vigente: meta actual (2 % ± 1 desde feb-2007) con evaluación continua. Las estadísticas y los récords de
    # rachas se cuentan desde ahí; 2002 a ene-2007 (meta de 2.5 % ± 1; hasta 2005 evaluada solo en diciembre) va aparte,
    # como referencia.
    cur_t = targets[-1]
    reg0 = pd.Timestamp(cur_t["desde"]).to_period("M").to_timestamp()

    years = []
    for y, s in state.groupby(state.index.year):
        v = t12[s.index]
        dec = pd.Timestamp(f"{y}-12-01")
        sr = s[s.index >= reg0]
        ref = sr.empty
        ss = s if ref else sr          # el año del cambio de meta cuenta solo los meses del régimen vigente
        vv = t12[ss.index]
        years.append({
            "y": int(y), "n": int(len(ss)), "in": int((ss == 0).sum()), "up": int((ss == 1).sum()), "dn": int((ss == -1).sum()),
            "pct": _num(100 * (ss == 0).mean(), 0), "avg": _num(vv.mean(), 2), "max": _num(vv.max(), 2), "min": _num(vv.min(), 2),
            "dec": _num(t12.get(dec), 2), "dec_state": int(state[dec]) if dec in state.index else None,
            "rng": [[_num(lo, 1), _num(hi, 1)] for lo, hi in dict.fromkeys(zip(b["lo"][ss.index], b["hi"][ss.index]))],
            "dec_only": bool(y <= DEC_ONLY_UNTIL), "ref": bool(ref), "from_m": _mk(ss.index[0]), "to_m": _mk(ss.index[-1]),
            "partial": bool(len(ss) < 12),
        })

    def runs_of(st_ser: pd.Series, ref: bool) -> list[dict]:
        out, start, vals = [], 0, st_ser.values
        for i in range(1, len(vals) + 1):
            if i == len(vals) or vals[i] != vals[start]:
                idx = st_ser.index[start:i]
                v = t12[idx]
                st = int(vals[start])
                ext_ts = v.idxmax() if st >= 0 else v.idxmin()
                lim = b["hi"][idx] if st > 0 else b["lo"][idx]
                dev = (v - lim).abs() if st != 0 else v * 0      # distancia al límite que se cruzó, en pp
                out.append({"st": st, "from": _mk(idx[0]), "to": _mk(idx[-1]), "n": int(len(idx)),
                            "ext": _num(v[ext_ts], 2), "ext_m": _mk(ext_ts), "ref": ref,
                            "dev_max": _num(dev.max(), 6), "dev_avg": _num(dev.mean(), 6),
                            "open": bool(not ref and idx[-1] == state.index[-1])})
                start = i
        return out

    runs = runs_of(state[state.index >= reg0], False)
    runs_ref = runs_of(state[state.index < reg0], True)
    out_runs = [r for r in runs if r["st"] != 0]
    cur = runs[-1]
    longest = {}
    for st in (1, -1):
        rr = [r for r in out_runs if r["st"] == st]
        if rr:
            longest[str(st)] = max(rr, key=lambda r: r["n"])
    # Puesto de la racha vigente entre las del mismo lado (1 = la más larga), desde el inicio del régimen.
    same = [r for r in runs if r["st"] == cur["st"]]
    cur_rank = 1 + sum(1 for r in same if r["n"] > cur["n"])
    since = state[state.index >= reg0]
    # Distancia media al límite en los meses fuera del rango (desde reg0), y rachas que nunca pasaron de 0.3 pp.
    ts = t12[since.index]
    dev_up = (ts - b["hi"][since.index])[since == 1]
    dev_dn = (b["lo"][since.index] - ts)[since == -1]
    devs = pd.concat([dev_up, dev_dn])
    small_up = sum(1 for r in out_runs if r["st"] == 1 and r["dev_max"] < 0.3)
    small_dn = sum(1 for r in out_runs if r["st"] == -1 and r["dev_max"] < 0.3)
    in_runs = [r for r in runs if r["st"] == 0]
    return {
        "years": years, "runs": out_runs, "runs_ref": [r for r in runs_ref if r["st"] != 0], "cur": cur, "longest": longest,
        "cur_rank": int(cur_rank), "cur_of": len(same), "reg_m": _mk(reg0),
        "longest_in": max(in_runs, key=lambda r: r["n"]) if in_runs else None,
        "last_m": _mk(t12.index[-1]), "last_v": _num(t12.iloc[-1], 2),
        "pct_since": _num(100 * (since == 0).mean(), 0), "since_m": _mk(since.index[0]),
        "up_since": _num(100 * (since == 1).mean(), 0), "dn_since": _num(100 * (since == -1).mean(), 0),
        "n_runs_up": sum(1 for r in out_runs if r["st"] == 1), "n_runs_dn": sum(1 for r in out_runs if r["st"] == -1),
        "cur_lo": cur_t["lo"], "cur_hi": cur_t["hi"],
        "dev_avg": _num(devs.mean(), 6) if len(devs) else None, "dev_avg_up": _num(dev_up.mean(), 6) if len(dev_up) else None,
        "small_up": small_up, "small_dn": small_dn, "last_dev": _num(float((ts - b["hi"][since.index]).iloc[-1]) if since.iloc[-1] == 1
                                                                   else float((b["lo"][since.index] - ts).iloc[-1]) if since.iloc[-1] == -1 else 0.0, 6),
    }
