"""Pestaña «Lo último» del tablero de inflación: resumen automático del último dato publicado.

Todos los textos se arman aquí, desde los datos, con frases condicionales (sube/baja por N.º mes,
dentro/fuera del rango meta, «la más alta desde ...»). No hay adjetivos fijos ni causas: las causas
solo se escriben en la pestaña «Episodio actual» y en `SHOCK_CAUSES` (con fuente oficial).

Salida (`D.extra.ultimo`): `m` (mes del IPC), `tiles` (tarjetas), `groups` (bloques de frases),
`rubros` (los que más subieron/bajaron o más aportaron), `band`, `exp_m`, `ref_m`.

Prueba de los textos con casos sintéticos (inflación bajando, dentro del rango, negativa, cambios de tasa...):
    python src/inflacion_extra/90_lo_ultimo.py --probar
Fuentes de las definiciones: docs/inflacion_extra/lo_ultimo_fuentes.md
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

KEY = "ultimo"

MES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "set", "oct", "nov", "dic"]
MES_LARGO = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "setiembre",
             "octubre", "noviembre", "diciembre"]
ORD_M = {2: "segundo", 3: "tercer", 4: "cuarto", 5: "quinto", 6: "sexto", 7: "séptimo", 8: "octavo",
         9: "noveno", 10: "décimo"}
ORD_F = {2: "segunda", 3: "tercera", 4: "cuarta", 5: "quinta", 6: "sexta", 7: "séptima", 8: "octava",
         9: "novena", 10: "décima"}

# Para «la más alta/baja desde ...»: solo se dice si el registro anterior es de hace al menos este número de meses.
RECORD_MIN_GAP = 12
# Para «para un mes de octubre, la más alta desde ...»: mínimo de años hacia atrás.
SAME_MONTH_MIN_YEARS = 3
# Rubros que se listan arriba y abajo.
TOP_N = 3

# Rubros del mapa de calor (solo hojas, nivel 2: nunca se mezclan padres e hijos) y su grupo.
RUBRO_GROUP = {"h_sb": "Subyacente · bienes", "h_ss": "Subyacente · servicios", "h_n": "No subyacente"}


# ------------------------------------------------------------------------------------------------
# Formato
# ------------------------------------------------------------------------------------------------
def fx(v: float, d: int = 2) -> str:
    r = round(float(v), d)
    if r == 0:
        r = 0.0
    return ("−" if r < 0 else "") + f"{abs(r):.{d}f}"


def pct(v: float, d: int = 2) -> str:
    return fx(v, d) + "%"


def signed(v: float, d: int = 2, unit: str = "%") -> str:
    r = round(float(v), d)
    return ("+" if r > 0 else "") + fx(r, d) + unit


def mlong(ts: pd.Timestamp) -> str:
    return f"{MES_LARGO[ts.month - 1]} de {ts.year}"


def mshort(ts: pd.Timestamp) -> str:
    return f"{MES[ts.month - 1]}-{ts.year}"


def mlabel(ts: pd.Timestamp) -> str:
    return f"{MES[ts.month - 1]} {ts.year}"


def mkey(ts: pd.Timestamp) -> str:
    return f"{ts.year:04d}-{ts.month:02d}"


def months(n: int) -> str:
    return "1 mes" if n == 1 else f"{n} meses"


def lower_first(s: str) -> str:
    return s[:1].lower() + s[1:]


def join_es(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " y " + items[-1]


def months_between(a: pd.Timestamp, b: pd.Timestamp) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


# ------------------------------------------------------------------------------------------------
# Análisis de series (todas con índice mensual, valores redondeados a 2 decimales como se publican)
# ------------------------------------------------------------------------------------------------
def clean(s: pd.Series | None) -> pd.Series | None:
    if s is None:
        return None
    # Valores publicados, a 2 decimales: los cambios de las tarjetas, las distancias al rango y las comparaciones
    # se calculan con lo que se muestra (4.64 − 4.51 = 0.13), igual que las tarjetas del Tablero.
    s = s.dropna().round(2)
    return s if not s.empty else None


def run(s: pd.Series) -> tuple[int, int]:
    """Dirección del último cambio (+1, −1, 0) y cuántos meses seguidos se repite esa dirección."""
    d = np.sign(s.diff().round(2).dropna().values)
    if len(d) == 0:
        return 0, 0
    last, n = d[-1], 0
    for x in d[::-1]:
        if x != last:
            break
        n += 1
    return int(last), n


def dir_clause(s: pd.Series) -> str:
    """«sube por tercer mes seguido (4.51% en setiembre de 2026)», «baja frente a ...», «igual que en ...»."""
    if len(s) < 2:
        return ""
    d, n = run(s)
    prev_ts, prev = s.index[-2], s.iloc[-2]
    ref = f"{pct(prev)} en {mlong(prev_ts)}"
    verb = "sube" if d > 0 else "baja"
    if d == 0:
        return f"se mantiene igual que en {mlong(prev_ts)}"
    if n == 1:
        return f"{verb} frente a {mlong(prev_ts)} ({pct(prev)})"
    if n in ORD_M:
        return f"{verb} por {ORD_M[n]} mes seguido ({ref})"
    return f"acumula {n} meses seguidos {'al alza' if d > 0 else 'a la baja'} ({ref})"


def record(s: pd.Series, min_gap: int = RECORD_MIN_GAP) -> dict | None:
    """Si el último valor subió (bajó) frente al mes anterior: último mes con un valor igual o mayor
    (igual o menor). Devuelve None si no hay cambio o si ese mes es muy reciente para mencionarlo."""
    if len(s) < 2:
        return None
    s = s.round(2)
    ts, v, prev = s.index[-1], s.iloc[-1], s.iloc[-2]
    if v == prev:
        return None
    hi = v > prev
    earlier = s.iloc[:-1]
    hit = earlier[earlier >= v] if hi else earlier[earlier <= v]
    if hit.empty:
        return {"hi": hi, "m": None, "start": s.index[0]}
    j = hit.index[-1]
    if months_between(j, ts) < min_gap:
        return None
    return {"hi": hi, "m": j, "v": hit.iloc[-1]}


def same_month_record(s: pd.Series, min_years: int = SAME_MONTH_MIN_YEARS) -> dict | None:
    """Comparación con el mismo mes de años anteriores (la variación mensual tiene estacionalidad)."""
    s = s.round(2)
    ts, v = s.index[-1], s.iloc[-1]
    same = s[(s.index.month == ts.month) & (s.index < ts)]
    if len(same) < min_years:
        return None
    # Dirección: frente al mismo mes del año anterior (un promedio histórico lo distorsiona la hiperinflación).
    if same.iloc[-1] == v:
        return None
    hi = v > same.iloc[-1]
    hit = same[same >= v] if hi else same[same <= v]
    if hit.empty:
        return {"hi": hi, "m": None, "start": same.index[0]}
    j = hit.index[-1]
    if ts.year - j.year < min_years:
        return None
    return {"hi": hi, "m": j, "v": hit.iloc[-1]}


# Regla única del tablero para el rango: valor publicado (2 decimales) frente al límite, estricto. Fuera por
# 0.10 pp o menos = «ligeramente por encima/por debajo».
SLIGHT = 0.10


def band_state(v: float, band: dict) -> int:
    v = round(float(v), 2)
    return 1 if v > band["hi"] else (-1 if v < band["lo"] else 0)


def gap(v: float, band: dict) -> float:
    """Distancia al límite que se cruzó (0 si está dentro), en pp, con el valor publicado."""
    v = round(float(v), 2)
    return round(v - band["hi"], 2) if v > band["hi"] else (round(band["lo"] - v, 2) if v < band["lo"] else 0.0)


def is_slight(v: float, band: dict) -> bool:
    return band_state(v, band) != 0 and gap(v, band) <= SLIGHT + 1e-9


def streaks(s: pd.Series, band: dict, since: pd.Timestamp) -> dict:
    """Racha actual dentro/por encima/por debajo del rango (desde que rige la meta vigente) y la racha anterior."""
    t = s[s.index >= since]
    st = [band_state(v, band) for v in t.values]
    cur, n = st[-1], 0
    for x in st[::-1]:
        if x != cur:
            break
        n += 1
    # to_start: la racha llega al primer mes evaluado; covers: ese mes es el inicio de la meta vigente.
    out = {"state": cur, "n": n, "from": t.index[len(t) - n], "to_start": n == len(t),
           "covers": t.index[0] <= since, "prev": None}
    rest = st[: len(t) - n]
    if rest:
        p, k = rest[-1], 0
        for x in rest[::-1]:
            if x != p:
                break
            k += 1
        out["prev"] = {"state": p, "n": k, "to_start": k == len(rest)}
    return out


def band_txt(band: dict) -> str:
    return f"{fx(band['lo'], 0)}% a {fx(band['hi'], 0)}%"


def ref_clause(v: float, band: dict) -> str:
    """Para medidas que no son la meta (tendencia, expectativa): sin decir «rango meta»."""
    st, g = band_state(v, band), gap(v, band)
    lo, hi = fx(band["lo"], 0), fx(band["hi"], 0)
    tail = "(que se aplica a la inflación total)"
    if st > 0:
        how = f"ligeramente por encima de {hi}% ({fx(g)} pp)" if is_slight(v, band) else f"{fx(g)} pp por encima de {hi}%"
        return f"{how}, el límite superior del rango {tail}"
    if st < 0:
        how = f"ligeramente por debajo de {lo}% ({fx(g)} pp)" if is_slight(v, band) else f"{fx(g)} pp por debajo de {lo}%"
        return f"{how}, el límite inferior del rango {tail}"
    return f"entre {lo}% y {hi}%, el rango {tail}"


def chip_of(v: float, band: dict, kind: str) -> dict:
    """kind 'meta' (solo la inflación total) o 'ref' (marca «Sobre 3%» / «Entre 1% y 3%» / «Bajo 1%»)."""
    return {"kind": kind, "st": band_state(v, band), "slight": is_slight(v, band)}


STATE_WORD = {1: "por encima del", 0: "dentro del", -1: "por debajo del"}


def meta_sentence(s: pd.Series, band: dict, since: pd.Timestamp) -> str:
    st = streaks(s, band, since)
    v, cur, n = s.iloc[-1], st["state"], st["n"]
    rng = f"rango meta del BCRP ({band_txt(band)})"
    if cur != 0:
        side, lim = ("sobre", "superior") if cur > 0 else ("bajo", "inferior")
        if is_slight(v, band):
            where = f"está ligeramente {'por encima' if cur > 0 else 'por debajo'}: {fx(gap(v, band))} pp {side} el límite {lim}"
        else:
            where = f"está {fx(gap(v, band))} pp {side} el límite {lim}"
    else:
        dc = round(v - band["c"], 2)
        where = (f"está en el centro de la meta ({fx(band['c'], 0)}%)" if dc == 0 else
                 f"está {fx(abs(dc))} pp {'por encima' if dc > 0 else 'por debajo'} del centro de la meta ({fx(band['c'], 0)}%)")
    prev = st["prev"]
    if n == 1 and prev is not None:
        pn = (f"al menos {months(prev['n'])}" if prev["to_start"] else months(prev["n"]))
        pw = {1: "por encima", 0: "dentro", -1: "por debajo"}[prev["state"]]
        if cur == 0:
            return f"Vuelve al {rng} tras {pn} {pw}; {where}."
        if prev["state"] == 0:
            verb = "Supera el" if cur > 0 else "Cae por debajo del"
            return f"{verb} {rng} tras {pn} dentro de él; {where}."
        return f"Pasa de estar {pw} del {rng} a estar {'por encima' if cur > 0 else 'por debajo'}; {where}."
    if n == 1:
        return f"Está {STATE_WORD[cur]} {rng}; {where}."
    since_txt = f"desde {mlong(st['from'])}"
    if st["to_start"]:
        since_txt += (", cuando empezó a regir la meta actual" if st["covers"] else ", primer mes con datos")
    return f"Lleva {n} meses seguidos {STATE_WORD[cur]} {rng}, {since_txt}; {where}."


def rec_sentence(r: dict | None, noun: str, fem: bool = True) -> str:
    if r is None:
        return ""
    adj = ("más alta" if fem else "más alto") if r["hi"] else ("más baja" if fem else "más bajo")
    if r["m"] is None:
        return f"Es {'la' if fem else 'el'} {noun} {adj} de la serie, que empieza en {mlong(r['start'])}."
    return f"Es {'la' if fem else 'el'} {noun} {adj} desde {mlong(r['m'])} ({pct(r['v'])})."


def delta_txt(s: pd.Series, unit: str = "pp") -> str:
    if len(s) < 2:
        return ""
    d = round(s.iloc[-1] - s.iloc[-2], 2)
    p = mlabel(s.index[-2])
    return ("= sin cambio" if d == 0 else ("▲ " if d > 0 else "▼ ") + fx(abs(d)) + " " + unit) + " vs " + p


def at_year_ago(s: pd.Series) -> tuple[pd.Timestamp, float] | None:
    ts = s.index[-1] - pd.DateOffset(years=1)
    return (ts, s.loc[ts]) if ts in s.index else None


# ------------------------------------------------------------------------------------------------
# Bloques
# ------------------------------------------------------------------------------------------------
def block_dato(tot12: pd.Series, totm: pd.Series | None, band: dict, since: pd.Timestamp) -> list[str]:
    ts, v = tot12.index[-1], tot12.iloc[-1]
    out = []
    first = f"En {mlong(ts)}, la inflación de 12 meses del IPC de Lima Metropolitana fue {pct(v)}"
    dc = dir_clause(tot12)
    first += (f" y {dc}" if dc else "") + "."
    ya = at_year_ago(tot12)
    if ya is not None:
        first += f" Hace un año, en {mlong(ya[0])}, era {pct(ya[1])}."
    out.append(first)
    if v < 0:
        out.append(f"Es una variación negativa: los precios son {fx(abs(v))}% más bajos que en {mlong(ts - pd.DateOffset(years=1))}.")
    elif v == 0:
        out.append(f"Los precios están, en promedio, al mismo nivel que en {mlong(ts - pd.DateOffset(years=1))}.")
    r = rec_sentence(record(tot12), "tasa")
    if r:
        out.append(r)
    out.append(meta_sentence(tot12, band, since))
    if totm is not None and totm.index[-1] == ts:
        vm = totm.iloc[-1]
        verb = f"subió {pct(vm)}" if vm > 0 else (f"bajó {pct(abs(vm))}" if vm < 0 else "no varió (0.00%)")
        s = f"En el mes, el IPC {verb}"
        ref = []
        if len(totm) > 1:
            ref.append(f"{pct(totm.iloc[-2])} en {mlong(totm.index[-2])}")
        ya = at_year_ago(totm)
        if ya is not None:
            ref.append(f"{pct(ya[1])} en {mlong(ya[0])}")
        s += (" (" + "; ".join(ref) + ")" if ref else "") + "."
        out.append(s)
        r = record(totm)
        if r is not None:
            out.append(rec_sentence(r, "variación mensual"))
        else:
            sm = same_month_record(totm)
            if sm is not None:
                adj = "más alta" if sm["hi"] else "más baja"
                name = MES_LARGO[ts.month - 1]
                if sm["m"] is None:
                    out.append(f"Es la variación {adj} para un mes de {name} en toda la serie, que empieza en {sm['start'].year}.")
                else:
                    out.append(f"Para un mes de {name}, es la variación {adj} desde {mlong(sm['m'])} ({pct(sm['v'])}).")
    return out


def block_tendencia(tot12: pd.Series, trends: dict[str, pd.Series], band: dict) -> list[str]:
    ts = tot12.index[-1]
    out, dirs, vals = [], [], []
    names = {"sae12": "La inflación sin alimentos y energía", "sub12": "La inflación subyacente"}
    for k, s in trends.items():
        if s is None or s.index[-1] != ts:
            continue
        v = s.iloc[-1]
        dc = dir_clause(s)
        out.append(f"{names[k]} fue {pct(v)} en 12 meses" + (f": {dc}" if dc else "") + f"; está {ref_clause(v, band)}.")
        dirs.append(run(s)[0])
        vals.append(v)
    if len(dirs) == 2:
        if dirs[0] == dirs[1]:
            out.append({1: "Las dos medidas de tendencia suben en el mes.", -1: "Las dos medidas de tendencia bajan en el mes.",
                        0: "Las dos medidas de tendencia no cambian en el mes."}[dirs[0]])
        elif 0 in dirs:
            out.append("Una medida de tendencia cambia en el mes y la otra no.")
        else:
            out.append("Las dos medidas de tendencia se mueven en sentidos opuestos en el mes.")
        v = tot12.iloc[-1]
        if v > max(vals):
            out.append(f"La inflación total ({pct(v)}) está por encima de ambas.")
        elif v < min(vals):
            out.append(f"La inflación total ({pct(v)}) está por debajo de ambas.")
        elif min(vals) < v < max(vals):
            out.append(f"La inflación total ({pct(v)}) está entre ambas.")
    if out:
        out.append("La meta del BCRP se aplica a la inflación total; para estas medidas, 1% y 3% son solo una referencia.")
    return out


def rubros_from_contrib(contrib, ts: pd.Timestamp) -> list[dict] | None:
    """Adapta la salida de la extensión de contribuciones (forma no fija): busca filas con etiqueta y aporte
    en puntos del mes `ts`. Devuelve None si no la reconoce."""
    if not isinstance(contrib, dict):
        return None
    key = mkey(ts)
    # Forma de 10_contribuciones.py: start = 'AAAA-MM' (primer mes), hasta = último mes, rubros = [{k, label, cm, vm}]
    # con cm = aporte mensual en pp y vm = var% mensual, alineados desde `start`.
    if isinstance(contrib.get("rubros"), list) and contrib.get("start"):
        if contrib.get("hasta") != key:
            return None
        i = months_between(pd.Timestamp(contrib["start"] + "-01"), ts)
        rows = []
        for r in contrib["rubros"]:
            cm, vm = r.get("cm") or [], r.get("vm") or []
            if i < 0 or i >= len(cm) or cm[i] is None:
                return None
            rows.append({"label": str(r.get("label")), "g": group_of(str(r.get("k", ""))), "v": float(cm[i]),
                         "var": round(float(vm[i]), 2) if i < len(vm) and vm[i] is not None else None})
        return rows or None
    cand = None
    for name in ("ultimo", "last", "latest", "mes", "rows"):
        if isinstance(contrib.get(name), (list, dict)):
            cand = contrib[name]
            break
    if isinstance(cand, dict):
        if cand.get("m") not in (None, key):
            return None
        cand = cand.get("rows") or cand.get("items")
    if not isinstance(cand, list):
        return None
    rows = []
    for r in cand:
        if not isinstance(r, dict):
            continue
        lab = r.get("label") or r.get("rubro") or r.get("nombre")
        val = next((r[k] for k in ("contrib", "aporte", "c", "pp") if r.get(k) is not None), None)
        if lab is None or val is None:
            continue
        if r.get("m") not in (None, key):
            continue
        rows.append({"label": str(lab), "g": r.get("g") or r.get("grupo") or "", "v": float(val),
                     "var": r.get("var") if r.get("var") is not None else r.get("v_m")})
    return rows or None


def block_rubros(rubros: dict[str, tuple[str, str, pd.Series]], ts: pd.Timestamp, contrib=None) -> tuple[list[str], dict | None]:
    rows = rubros_from_contrib(contrib, ts) if contrib is not None else None
    mode = "contrib" if rows else "var"
    if rows is None:
        rows = []
        for k, (lab, grp, s) in rubros.items():
            if s is not None and ts in s.index and not pd.isna(s.loc[ts]):
                rows.append({"label": lab, "g": grp, "v": round(float(s.loc[ts]), 2)})
    if len(rows) < 2 * TOP_N:
        return [], None
    rows.sort(key=lambda r: r["v"], reverse=True)
    top, bot = rows[:TOP_N], rows[::-1][:TOP_N]
    unit = " pp" if mode == "contrib" else "%"

    def head(group: list[dict], up: bool) -> str:
        """Encabezado según los signos reales (nunca «más bajaron» si todos subieron, etc.)."""
        pos, neg = all(r["v"] > 0 for r in group), all(r["v"] < 0 for r in group)
        if mode == "contrib":
            if up:
                return "Más aportaron" if pos else "Mayor aporte"
            return "Más restaron" if neg else "Menor aporte"
        if up:
            return "Más subieron" if pos else ("Menos bajaron" if neg else "Mayor variación")
        return "Más bajaron" if neg else ("Menos subieron" if pos else "Menor variación")

    PROSE = {"Más aportaron": "los que más aportaron fueron", "Mayor aporte": "los de mayor aporte fueron",
             "Más restaron": "los que más restaron", "Menor aporte": "los de menor aporte",
             "Más subieron": "los que más subieron fueron", "Mayor variación": "los de mayor variación fueron",
             "Más bajaron": "los que más bajaron", "Menos bajaron": "los que menos bajaron fueron", "Menos subieron": "los que menos subieron",
             "Menor variación": "los de menor variación"}

    def item(r):
        extra = f"; precio {signed(r['var'])}" if mode == "contrib" and r.get("var") is not None else ""
        return f"{lower_first(r['label'])} ({signed(r['v'], 2, unit)}{extra})"

    h_top, h_bot = head(top, True), head(bot, False)
    lists = (f"{PROSE[h_top]} {join_es([item(r) for r in top])}; {PROSE[h_bot]}, {join_es([item(r) for r in bot])}")
    if mode == "contrib":
        txt = f"Por su aporte a la inflación del mes (en puntos porcentuales, con las ponderaciones de la canasta), {lists}."
    else:
        txt = (f"Entre los rubros del IPC de Lima, por su variación de precio en el mes, {lists}. "
               "Son variaciones, no aportes: no consideran el peso de cada rubro en la canasta.")
    return [txt], {"mode": mode, "m": mkey(ts), "top": top, "bot": bot, "h_top": h_top, "h_bot": h_bot}


def block_politica(exp: pd.Series | None, ref: pd.Series | None, band: dict) -> list[str]:
    out = []
    if exp is not None:
        v, ts = exp.iloc[-1], exp.index[-1]
        dc = dir_clause(exp)
        out.append(f"La expectativa de inflación a 12 meses (encuesta del BCRP a analistas económicos y al sistema "
                   f"financiero) fue {pct(v)} en {mlong(ts)}" + (f": {dc}" if dc else "") + f"; está {ref_clause(v, band)}.")
    if ref is not None:
        v, ts = ref.iloc[-1], ref.index[-1]
        chg = ref[ref.diff().round(2) != 0].iloc[1:] if len(ref) > 1 else ref.iloc[0:0]
        if len(ref) > 1 and ref.iloc[-1] != ref.iloc[-2]:
            prev = ref.iloc[-2]
            up = v > prev
            s = f"En {mlong(ts)}, el BCRP {'subió' if up else 'bajó'} su tasa de referencia de {pct(prev)} a {pct(v)}."
            # Cambios seguidos (meses consecutivos) en la misma dirección.
            d = np.sign(ref.diff().round(2).values[1:])
            n = 0
            for x in d[::-1]:
                if x != np.sign(v - prev):
                    break
                n += 1
            if n >= 2:
                s += f" Es la {ORD_F.get(n, f'{n}.ª')} {'alza' if up else 'baja'} en meses consecutivos."
            elif len(chg) > 1:
                pts = chg.index[-2]
                pup = chg.iloc[-2] > ref.loc[:pts].iloc[-2]
                s += f" El cambio anterior fue en {mlong(pts)} ({'un alza' if pup else 'una baja'})."
            out.append(s)
        elif len(chg):
            cts = chg.index[-1]
            before = ref.loc[:cts].iloc[-2]
            out.append(f"La tasa de referencia del BCRP se mantiene en {pct(v)} desde {mlong(cts)}, cuando "
                       f"{'subió' if v > before else 'bajó'} desde {pct(before)}; último dato: {mlong(ts)}.")
        else:
            out.append(f"La tasa de referencia del BCRP está en {pct(v)} en {mlong(ts)}, sin cambios en toda la serie.")
    return out


def block_nacional(nac12: pd.Series | None, nacm: pd.Series | None, tot12: pd.Series) -> list[str]:
    if nac12 is None:
        return []
    ts, v = nac12.index[-1], nac12.iloc[-1]
    s = f"Con el IPC nacional del INEI, la inflación de 12 meses fue {pct(v)} en {mlong(ts)}"
    if nacm is not None and nacm.index[-1] == ts:
        s += f" ({pct(nacm.iloc[-1])} en el mes)"
    if ts in tot12.index:
        lima = tot12.loc[ts]
        rel = "igual a" if v == lima else ("por debajo de" if v < lima else "por encima de")
        s += f", {rel} la de Lima Metropolitana ({pct(lima)})"
    return [s + "."]


def proy_from_extra(proy, year: int) -> dict | None:
    """Adapta la salida de la extensión de proyecciones (forma no fija): proyección vigente del BCRP para
    la inflación de diciembre del año `year`, con la fecha del Reporte de Inflación que la publicó."""
    if not isinstance(proy, dict):
        return None
    # Forma de 30_proyecciones.py: ris = [{id: 'RI-AAAA-MM', f: fecha de publicación}], pts = [i_ri, año, proyección, ...].
    if isinstance(proy.get("ris"), list) and isinstance(proy.get("pts"), list):
        ris = proy["ris"]
        cand = sorted((pt for pt in proy["pts"] if int(pt[1]) == year and pt[2] is not None), key=lambda pt: pt[0])
        if not cand:
            return None

        def name(i):
            rid = str(ris[i]["id"])
            return f"Reporte de Inflación de {MES_LARGO[int(rid[8:10]) - 1]} de {rid[3:7]}"

        last = cand[-1]
        out = {"v": float(last[2]), "year": year, "src": name(last[0]), "f": ris[last[0]].get("f")}
        if len(cand) > 1:
            out["prev"] = {"v": float(cand[-2][2]), "src": name(cand[-2][0])}
        return out
    cur = proy.get("vigente") or proy.get("current") or proy.get("ultima") or proy.get("latest")
    if isinstance(cur, dict):
        anio = cur.get("anio") or cur.get("year") or cur.get("y")
        val = cur.get("v") if cur.get("v") is not None else cur.get("valor")
        src = cur.get("reporte") or cur.get("fuente") or cur.get("src") or cur.get("ri")
        if val is not None and (anio is None or int(anio) == year):
            return {"v": float(val), "src": src, "year": year}
        for k in ("anios", "years", "values"):
            if isinstance(cur.get(k), dict) and str(year) in cur[k]:
                return {"v": float(cur[k][str(year)]), "src": src, "year": year}
    return None


def block_proy(p: dict | None, tot12: pd.Series) -> list[str]:
    """Da la proyección (1 decimal, como la publica el RI) y el último dato con sus fechas; no los resta: son
    de meses distintos (la proyección es para diciembre y se hizo con datos anteriores)."""
    if p is None:
        return []
    v, pv, ts, year = tot12.iloc[-1], p["v"], tot12.index[-1], p["year"]
    src = ""
    if p.get("src"):
        f = p.get("f")
        src = f" ({p['src']}"
        if f:
            pub = pd.Timestamp(f)
            src += (f", publicado el {pub.day} de {MES_LARGO[pub.month - 1]} de {pub.year}, con datos de inflación "
                    f"hasta {mlong(pub - pd.DateOffset(months=1))}")
        src += ")"
    if ts.month == 12 and ts.year == year:
        return [f"La proyección del BCRP para la inflación de diciembre de {year} era {pct(pv, 1)}{src}; "
                f"el resultado fue {pct(v)}."]
    s = f"La proyección vigente del BCRP para la inflación de 12 meses de diciembre de {year} es {pct(pv, 1)}{src}."
    pr = p.get("prev")
    if pr is not None:
        s += (f" En el reporte anterior ({pr['src']}) era la misma." if round(pv - pr["v"], 1) == 0 else
              f" En el reporte anterior ({pr['src']}) era {pct(pr['v'], 1)}.")
    s += f" El último dato, de {mlong(ts)}, es {pct(v)}; la proyección se refiere a diciembre, no a ese mes."
    return [s]


# ------------------------------------------------------------------------------------------------
# Tarjetas
# ------------------------------------------------------------------------------------------------
def tile(lab: str, s: pd.Series, sub: str = "", chip: dict | None = None, hero: bool = False, extra: str = "") -> dict:
    return {"lab": lab, "v": round(float(s.iloc[-1]), 2), "m": mkey(s.index[-1]), "sub": sub,
            "chip": chip, "hero": hero, "extra": extra}


def build_core(ser: dict, targets: list[dict], rubros: dict, contrib=None, proy=None) -> dict | None:
    tot12 = clean(ser.get("tot12"))
    if tot12 is None or len(tot12) < 13:
        return None
    totm, sae12, sub12 = clean(ser.get("totm")), clean(ser.get("sae12")), clean(ser.get("sub12"))
    exp, ref = clean(ser.get("exp")), clean(ser.get("ref"))
    nac12, nacm = clean(ser.get("nac12")), clean(ser.get("nacm"))
    cur = targets[-1]
    band = {"lo": cur["lo"], "hi": cur["hi"], "c": cur["c"] if cur.get("c") is not None else (cur["lo"] + cur["hi"]) / 2}
    since = pd.Timestamp(cur["desde"]).to_period("M").to_timestamp()
    ts = tot12.index[-1]

    groups = []
    groups.append({"id": "dato", "h": "El dato del mes", "p": block_dato(tot12, totm, band, since)})
    t = block_tendencia(tot12, {"sae12": sae12, "sub12": sub12}, band)
    if t:
        groups.append({"id": "tend", "h": "Medidas de tendencia", "p": t})
    r_txt, r_data = block_rubros(rubros, ts, contrib)
    if r_txt:
        groups.append({"id": "rub", "h": "Rubros", "p": r_txt})
    p = block_proy(proy_from_extra(proy, ts.year), tot12) if proy is not None else []
    if p:
        groups.append({"id": "proy", "h": "Frente a la proyección del BCRP", "p": p})
    pol = block_politica(exp, ref, band)
    if pol:
        groups.append({"id": "pol", "h": "Expectativas y tasa de referencia", "p": pol})
    nac = block_nacional(nac12, nacm, tot12)
    if nac:
        groups.append({"id": "nac", "h": "Inflación nacional", "p": nac})

    st = streaks(tot12, band, since)
    if st["n"] == 1:
        hero_extra = f"Primer mes {STATE_WORD[st['state']]} rango meta"
    else:
        hero_extra = (f"{st['n']} meses seguidos {STATE_WORD[st['state']]} rango meta"
                      f"{' (desde que rige la meta actual)' if st['to_start'] and st['covers'] else ''}")
    ya = at_year_ago(tot12)
    tiles = [tile("Inflación de 12 meses · IPC de Lima", tot12,
                  delta_txt(tot12) + (f" · {pct(ya[1])} en {mlabel(ya[0])}" if ya else ""), chip=chip_of(tot12.iloc[-1], band, "meta"), hero=True,
                  extra=hero_extra)]
    if totm is not None:
        ya = at_year_ago(totm)
        tiles.append(tile("Inflación del mes", totm, f"{pct(totm.iloc[-2])} en {mlabel(totm.index[-2])}" +
                          (f" · {pct(ya[1])} en {mlabel(ya[0])}" if ya else "")))
    if sae12 is not None:
        tiles.append(tile("Sin alimentos y energía (12 meses)", sae12, delta_txt(sae12), chip=chip_of(sae12.iloc[-1], band, "ref")))
    if sub12 is not None:
        tiles.append(tile("Subyacente (12 meses)", sub12, delta_txt(sub12), chip=chip_of(sub12.iloc[-1], band, "ref")))
    if exp is not None:
        tiles.append(tile("Expectativa de inflación a 12 meses", exp, delta_txt(exp) + " · encuesta del BCRP", chip=chip_of(exp.iloc[-1], band, "ref")))
    if ref is not None:
        chg = ref[ref.diff().round(2) != 0].iloc[1:]
        if len(ref) > 1 and ref.iloc[-1] != ref.iloc[-2]:
            sub = delta_txt(ref)
        elif len(chg):
            sub = f"sin cambio desde {mlabel(chg.index[-1])}"
        else:
            sub = "sin cambios en la serie"
        tiles.append(tile("Tasa de referencia del BCRP", ref, sub))
    if nac12 is not None:
        tiles.append(tile("Inflación nacional, 12 meses (INEI)", nac12, delta_txt(nac12),
                          extra="La meta del BCRP se mide con el IPC de Lima, no con el nacional."))
    pr = proy_from_extra(proy, ts.year) if proy is not None else None
    if pr is not None and not (ts.month == 12):
        # Va como línea extra de la tarjeta principal (no como tarjeta suelta).
        src = str(pr.get("src") or "Reporte de Inflación")
        tiles[0]["extra2"] = f"Proyección del BCRP para dic {pr['year']}: {pct(pr['v'], 1)} ({src.replace('Reporte de Inflación de ', 'Reporte de Inflación, ')})"

    return {"m": mkey(ts), "band": band, "tiles": tiles, "groups": groups, "rubros": r_data,
            "exp_m": mkey(exp.index[-1]) if exp is not None else None,
            "ref_m": mkey(ref.index[-1]) if ref is not None else None}


def heat_leaves() -> list[tuple[str, str, str]]:
    """(clave, etiqueta, columna) de las hojas del mapa de calor, desde visual_inflacion.HEAT_ROWS."""
    src = Path(__file__).resolve().parents[1]
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    import visual_inflacion as vi  # noqa: E402  (solo constantes; su main no corre al importar)
    return [(k, lab, col) for k, lab, lv, col, kind in vi.HEAT_ROWS if lv == 2 and kind == "m"]


def group_of(key: str) -> str:
    for p, g in RUBRO_GROUP.items():
        if key.startswith(p):
            return g
    return ""


def build(ctx: dict) -> dict | None:
    m, months_idx, S = ctx["m"], ctx["months"], ctx["S"]

    def col(c):
        return m[c] if c in m.columns else None

    def from_S(k):
        v = S.get(k)
        return pd.Series(v, index=months_idx, dtype=float) if v is not None else None

    ser = {"tot12": col("ipc_var12m"), "totm": col("ipc_var_mensual"), "sae12": col("ipc_sin_alim_energia_var12m"),
           "sub12": col("ipc_subyacente_var12m"), "exp": col("expectativa_inflacion_12m"), "ref": col("tasa_referencia"),
           "nac12": from_S("nac12"), "nacm": from_S("nacm")}
    rubros = {}
    for k, lab, c in heat_leaves():
        if c in m.columns:
            rubros[k] = (lab, group_of(k), m[c])
    extra = ctx.get("extra") or {}
    out = build_core(ser, ctx["targets"], rubros, extra.get("contrib"), extra.get("proy"))
    if out is not None:
        out["has_contrib"] = "contrib" in extra
        out["has_proy"] = "proy" in extra
    return out


# ------------------------------------------------------------------------------------------------
# Prueba con casos sintéticos
# ------------------------------------------------------------------------------------------------
BAD = [r"\bnan\b", r"None", r"−0\.00", r"\b1 meses\b", r"  ", r" \.", r"\.\.", r",,", r"\binf\b", r"\(\)", r" ;", r"; \."]


def check_text(txt: str) -> list[str]:
    errs = [f"patrón «{p}»" for p in BAD if re.search(p, txt)]
    if not txt.endswith("."):
        errs.append("no termina en punto")
    if txt[:1] != txt[:1].upper():
        errs.append("no empieza con mayúscula")
    return errs


def _probar() -> int:
    idx = pd.date_range("2019-01-01", "2026-10-01", freq="MS")
    n = len(idx)
    targets = [{"desde": "2007-02-01", "hasta": None, "c": 2.0, "lo": 1.0, "hi": 3.0}]

    def S(vals):
        vals = list(vals)
        return pd.Series(vals, index=idx[-len(vals):], dtype=float)

    def base(last12: list[float], lastm: list[float], **kw):
        pre = [2.0] * (n - len(last12))
        ser = {"tot12": S(pre + last12), "totm": S([0.2] * (n - len(lastm)) + lastm),
               "sae12": S([2.0] * (n - 3) + kw.get("sae", [2.1, 2.2, 2.3])),
               "sub12": S([2.0] * (n - 3) + kw.get("sub", [2.3, 2.2, 2.1])),
               "exp": S([2.5] * (n - 4) + kw.get("exp", [2.4, 2.4, 2.3])),
               "ref": S(kw.get("ref", [4.25] * n)),
               "nac12": S([2.0] * (n - 1) + [last12[-1] - 0.3]) if kw.get("nac", True) else None,
               "nacm": S([0.2] * n) if kw.get("nac", True) else None}
        return ser

    def rub(vals):
        keys = ["h_sba", "h_sbt", "h_sbe", "h_sbr", "h_ssc", "h_sse", "h_sss", "h_ssa", "h_ssr", "h_na", "h_nc"]
        return {k: (f"Rubro {k}", group_of(k), S([0.1] * (n - 1) + [v])) for k, v in zip(keys, vals)}

    mixed = [0.5, -0.2, 0.1, 0.3, 0.4, 1.2, 0.0, 0.2, -1.1, 2.4, -0.4]
    cases = {
        "1 sube y sale del rango por encima": (base([2.6, 2.8, 3.4], [0.3, 0.4, 0.7]), rub(mixed)),
        "2 baja por cuarto mes y vuelve al rango": (base([4.0] * 20 + [3.8, 3.5, 3.2, 2.9], [0.1, 0.0, -0.1, 0.05]), rub(mixed)),
        "3 dentro del rango, sin cambio": (base([2.4, 2.4], [0.2, 0.2]), rub([0.1 * i for i in range(1, 12)])),
        "4 inflación negativa y mes negativo": (base([0.4, 0.1, -0.3, -0.6], [-0.2, -0.1, -0.3, -0.4],
                                                     sae=[0.9, 0.8, 0.7], sub=[0.8, 0.8, 0.8], exp=[1.2, 1.0, 0.9]),
                                                rub([-0.1 * i for i in range(1, 12)])),
        "5 recorte de tasa (tres seguidos)": (base([2.5, 2.3, 2.1], [0.1, 0.1, 0.1], ref=[5.0] * (n - 3) + [4.75, 4.5, 4.25]), rub(mixed)),
        "6 alza de tasa aislada": (base([3.5, 3.7, 3.9], [0.4, 0.4, 0.4], ref=[4.0] * (n - 12) + [3.75] * 11 + [4.0]), rub(mixed)),
        "7 récord de toda la serie y sin nacional": (base(list(np.linspace(2, 9, 30)), [0.3, 0.9], nac=False), rub(mixed)),
        "8 por debajo del rango, larga racha, tasa constante": (base([0.6] * 30, [0.05, 0.05], ref=[3.0] * n), rub(mixed)),
        "9 de por debajo a por encima": (base([0.8, 3.3], [0.1, 2.0]), rub(mixed)),
    }
    contrib = {"ultimo": {"m": "2026-10", "rows": [{"label": f"Rubro {i}", "contrib": c} for i, c in
                                                     enumerate([0.12, 0.08, 0.05, 0.01, -0.01, -0.03, 0.0])]}}
    proy = {"vigente": {"anio": 2026, "v": 2.6, "reporte": "Reporte de Inflación de setiembre de 2026"}}
    cases["10 con contribuciones y proyección"] = (base([2.5, 2.7, 2.9], [0.2, 0.3, 0.3]), rub(mixed), contrib, proy)
    proy2 = {"ris": [{"id": "RI-2026-06", "f": "2026-06-19"}, {"id": "RI-2026-09", "f": "2026-09-18"}],
             "pts": [[0, 2026, 3.8, None, None], [1, 2026, 4.2, None, None], [1, 2027, 2.0, None, None]]}
    keys13 = ["h_sba", "h_sbt", "h_sbe", "h_sbr", "h_ssc", "h_sse", "h_sss", "h_ssa", "h_ssr", "h_na", "h_nc", "h_nt", "h_np"]
    cm_last = [0.02, -0.01, 0.0, 0.01, 0.05, 0.0, 0.01, 0.02, 0.06, 0.25, 0.04, 0.02, -0.03]
    contrib2 = {"start": "2026-09", "hasta": "2026-10",
                "rubros": [{"k": k, "label": f"Rubro {k}", "cm": [0.0, c], "vm": [0.0, c * 10]} for k, c in zip(keys13, cm_last)]}
    cases["12 contribuciones con formato de 10_contribuciones"] = (base([2.5, 2.7, 2.9], [0.2, 0.3, 0.3]), rub(mixed), contrib2)
    cases["13 ligeramente por encima (3.04) y expectativa 3.01"] = (base([2.95, 3.04], [0.2, 0.2], exp=[2.98, 2.99, 3.01]), rub(mixed))
    cases["14 ligeramente por encima en el borde (3.10)"] = (base([3.04, 3.10], [0.2, 0.2], exp=[3.0, 3.0, 3.0]), rub(mixed))
    cases["15 por encima (3.11)"] = (base([3.0, 3.11], [0.2, 0.2]), rub(mixed))
    cases["11 proyección con formato de 30_proyecciones"] = (base([4.4, 4.6, 4.2], [0.1, 0.2, -0.1]), rub(mixed), None, proy2)

    fails = 0
    for name, c in cases.items():
        ser, rubros = c[0], c[1]
        res = build_core(ser, targets, rubros, *(c[2:] if len(c) > 2 else ()))
        print(f"\n=== {name}")
        for g in res["groups"]:
            for p in g["p"]:
                errs = check_text(p)
                fails += bool(errs)
                print(f"  [{g['h']}] {p}" + (f"   <<< {', '.join(errs)}" if errs else ""))
        for t in res["tiles"]:
            print(f"  · {t['lab']}: {t['v']} ({t['m']}) {t['sub']} {t['extra']}")
    # Controles puntuales de lógica.
    exp_checks = [
        ("1 sube y sale del rango por encima", "Supera el rango meta"),
        ("2 baja por cuarto mes y vuelve al rango", "baja por cuarto mes seguido"),
        ("2 baja por cuarto mes y vuelve al rango", "Vuelve al rango meta del BCRP (1% a 3%) tras 23 meses por encima"),
        ("3 dentro del rango, sin cambio", "igual que en setiembre de 2026"),
        ("4 inflación negativa y mes negativo", "Es una variación negativa"),
        ("4 inflación negativa y mes negativo", "el IPC bajó 0.40%"),
        ("5 recorte de tasa (tres seguidos)", "Es la tercera baja en meses consecutivos"),
        ("6 alza de tasa aislada", "El cambio anterior fue en noviembre de 2025 (una baja)"),
        ("7 récord de toda la serie y sin nacional", "de la serie, que empieza en"),
        ("8 por debajo del rango, larga racha, tasa constante", "Lleva 30 meses seguidos por debajo"),
        ("9 de por debajo a por encima", "Pasa de estar por debajo del rango meta"),
        ("10 con contribuciones y proyección", "Por su aporte a la inflación del mes"),
        ("10 con contribuciones y proyección", "La proyección vigente del BCRP para la inflación de 12 meses de diciembre de 2026 es 2.6%"),
        ("11 proyección con formato de 30_proyecciones", "diciembre de 2026 es 4.2% (Reporte de Inflación de setiembre de 2026, publicado el 18 de setiembre de 2026, con datos de inflación hasta agosto de 2026). En el reporte anterior (Reporte de Inflación de junio de 2026) era 3.8%. El último dato, de octubre de 2026, es 4.20%; la proyección se refiere a diciembre, no a ese mes."),
        ("13 ligeramente por encima (3.04) y expectativa 3.01", "Supera el rango meta del BCRP (1% a 3%) tras al menos 93 meses dentro de él; está ligeramente por encima: 0.04 pp sobre el límite superior."),
        ("13 ligeramente por encima (3.04) y expectativa 3.01", "fue 3.01% en octubre de 2026: sube por tercer mes seguido (2.99% en setiembre de 2026); está ligeramente por encima de 3% (0.01 pp), el límite superior del rango (que se aplica a la inflación total)."),
        ("14 ligeramente por encima en el borde (3.10)", "está ligeramente por encima: 0.10 pp sobre el límite superior"),
        ("14 ligeramente por encima en el borde (3.10)", "está entre 1% y 3%, el rango (que se aplica a la inflación total)."),
        ("15 por encima (3.11)", "está 0.11 pp sobre el límite superior."),
        ("15 por encima (3.11)", "Supera el rango meta del BCRP (1% a 3%) tras al menos 93 meses dentro de él"),
        ("12 contribuciones con formato de 10_contribuciones", "los que más aportaron fueron rubro h_na (+0.25 pp; precio +2.50%)"),
        ("12 contribuciones con formato de 10_contribuciones", "los de menor aporte, rubro h_np (−0.03 pp; precio −0.30%)"),
    ]
    for name, frag in exp_checks:
        c = cases[name]
        res = build_core(c[0], targets, c[1], *(c[2:] if len(c) > 2 else ()))
        allp = " ".join(p for g in res["groups"] for p in g["p"])
        ok = frag in allp
        fails += not ok
        print(f"  {'OK ' if ok else 'FALLA'} {name}: «{frag}»")
    print(f"\n{'Sin problemas' if not fails else f'{fails} problema(s)'} en {len(cases)} casos.")
    return 1 if fails else 0


if __name__ == "__main__":
    if "--probar" in sys.argv:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.exit(_probar())
    print("Uso: python src/inflacion_extra/90_lo_ultimo.py --probar  (el módulo lo corre visual_inflacion.py)")
