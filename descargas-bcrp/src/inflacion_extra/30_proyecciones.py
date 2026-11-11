"""Extensión del tablero de inflación: proyecciones de inflación del BCRP frente a lo ocurrido.

Lee `config/proyecciones_inflacion.csv` (lo arma `src/extraer_proyecciones_inflacion.py` desde los Reportes de
Inflación) y la inflación de 12 meses de diciembre del panel (`ipc_var12m`, IPC de Lima, la medida de la meta).

Salida (`D.extra.proy`):
  ris    lista de RI: id, fecha de publicación (f), etiqueta de mes (m)
  pts    [índice del RI, año objetivo, proyección, mínimo, máximo] (rango solo en 2015-2017)
  real   {año: inflación de 12 meses de diciembre}
  now    último dato del año en curso (si diciembre aún no se publica)
  err    por año cerrado: proyección del RI de diciembre del año anterior y del RI de mitad de año, con su desvío
  stats  desvío medio (sesgo) y desvío absoluto medio por momento de la proyección
  top    años de mayor sorpresa (por el desvío de la proyección de diciembre del año anterior)
  causes causa documentada en un RI (solo si hay fuente oficial; ver docs/inflacion_extra/proyecciones_fuentes.md)

Desvío = inflación observada − proyección (positivo: la inflación terminó por encima de lo proyectado).
"""
from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

KEY = "proy"
MES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "set", "oct", "nov", "dic"]

# Años del choque global de alimentos y energía (RI dic-2021 y dic-2022, Resumen viii): se muestra también el
# desvío medio sin ellos, para no leer como sesgo sistemático lo que fue un choque.
SHOCK_YEARS = (2021, 2022)

# Causa de la sorpresa según el propio BCRP (solo con fuente oficial; ver proyecciones_fuentes.md).
CAUSES = {
    2021: {"t": "Según el BCRP, entre agosto y noviembre de 2021 la inflación subió por el mayor precio de los alimentos "
                "con alto contenido importado y de los combustibles, y por la depreciación del sol",
           "src": "RI de diciembre de 2021, Resumen, párrafo viii"},
    2022: {"t": "En diciembre de 2022, el BCRP proyectaba para 2023 la reversión del efecto de factores transitorios sobre "
                "la inflación: los precios internacionales de alimentos y energía",
           "src": "RI de diciembre de 2022, Resumen, párrafo viii"},
}


def _r(v, nd=2):
    return None if v is None or pd.isna(v) else round(float(v), nd)


def build(ctx: dict) -> dict | None:
    path = Path(ctx["project_dir"]) / "config" / "proyecciones_inflacion.csv"
    if not path.exists():
        ctx["warn"]("proyecciones: falta config/proyecciones_inflacion.csv (correr src/extraer_proyecciones_inflacion.py)")
        return None
    with path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return None
    m = ctx["m"]
    if "ipc_var12m" not in m.columns:
        ctx["warn"]("proyecciones: falta ipc_var12m en el panel")
        return None
    t12 = m["ipc_var12m"].dropna()

    # Lista de RI ordenada por fecha.
    ri_ids = sorted({r["ri"] for r in rows}, key=lambda x: (x[3:7], x[8:10]))
    date_of = {r["ri"]: r["fecha_publicacion"] for r in rows}
    url_of = {r["ri"]: r["url"] for r in rows}
    ris = [{"id": i, "f": date_of[i], "m": MES[int(i[8:10]) - 1] + " " + i[3:7], "url": url_of[i]} for i in ri_ids]
    pos = {i: k for k, i in enumerate(ri_ids)}
    pts = []
    for r in rows:
        lo, hi = float(r["proyeccion_min"]), float(r["proyeccion_max"])
        pts.append([pos[r["ri"]], int(r["anio_objetivo"]), _r(float(r["proyeccion"])),
                    _r(lo) if lo != hi else None, _r(hi) if lo != hi else None])
    pts.sort(key=lambda p: (p[1], p[0]))
    years = sorted({p[1] for p in pts})

    # Observado: inflación de 12 meses de diciembre de cada año.
    real = {}
    for y in years:
        ts = pd.Timestamp(y, 12, 1)
        if ts in t12.index:
            real[y] = _r(t12.loc[ts])
    last_ts = t12.index.max()
    now = None
    if last_ts.month != 12 and last_ts.year in years:
        now = {"y": int(last_ts.year), "m": last_ts.strftime("%Y-%m"), "v": _r(t12.iloc[-1])}

    # Errores por año cerrado.
    def pick(y, cond):
        cand = [p for p in pts if p[1] == y and cond(ri_ids[p[0]])]
        return max(cand, key=lambda p: p[0]) if cand else None   # el último RI que cumple

    err = []
    for y in years:
        if y not in real:
            continue
        start = f"{y}-01-01"
        dic = pick(y, lambda i: date_of[i] < start)                                   # último RI antes del año
        mid = pick(y, lambda i: i[3:7] == str(y) and i[8:10] in ("05", "06"))         # RI de mayo o junio del año
        rec = {"y": y, "real": real[y]}
        for k, p in (("dic", dic), ("mid", mid)):
            if p:
                rec[k] = {"ri": p[0], "p": p[2], "lo": p[3], "hi": p[4], "e": _r(real[y] - p[2])}
        err.append(rec)

    def summary(k, skip=()):
        # Mismos años para ambos momentos (los que tienen las dos proyecciones), para que sean comparables.
        es = [(r["y"], r[k]["e"]) for r in err if "dic" in r and "mid" in r and r["y"] not in skip]
        if not es:
            return None
        e = pd.Series([v for _, v in es])
        return {"n": len(es), "from": es[0][0], "to": es[-1][0], "bias": _r(e.mean()), "mae": _r(e.abs().mean()),
                "k1": int((e.abs() <= 1).sum()), "med": _r(e.abs().median())}

    stats = {"dic": summary("dic"), "mid": summary("mid")}
    # Sin los años del choque global de alimentos y energía (solo si están en la muestra).
    skip = tuple(y for y in SHOCK_YEARS if any(r["y"] == y and "dic" in r for r in err))
    if skip:
        stats["dic_ex"] = summary("dic", skip)
        stats["ex_years"] = list(skip)
    top = sorted([r for r in err if "dic" in r], key=lambda r: -abs(r["dic"]["e"]))[:2]
    top = [{"y": r["y"], "e": r["dic"]["e"], "p": r["dic"]["p"], "ri": r["dic"]["ri"], "real": r["real"]}
           for r in top if abs(r["dic"]["e"]) >= 1]

    cur_y = now["y"] if now else None
    print(f"    proyecciones: {len(ris)} RI ({ris[0]['m']} a {ris[-1]['m']}), {len(pts)} cifras, "
          f"años {years[0]}-{years[-1]}, cerrados con dato: {len(err)}; "
          f"desvío absoluto medio (RI dic. previo) = {stats['dic']['mae'] if stats['dic'] else '—'} pp")
    return {
        "ris": ris, "pts": pts, "real": {str(k): v for k, v in real.items()}, "now": now, "cur": cur_y,
        "err": err, "stats": stats, "top": top,
        "causes": {str(k): v for k, v in CAUSES.items()},
        "last_range": max((ri_ids[p[0]] for p in pts if p[3] is not None), default=None),
    }
