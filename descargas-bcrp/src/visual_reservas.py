"""Genera `outputs/reservas_bcrp.html`: tablero de reservas internacionales e intervención
cambiaria del BCRP.

Lee los paneles de `data/processed/` (correr antes `construir_tablas.py`), arma los datos que
usa la página y los inyecta en la plantilla `src/plantillas/reservas.html`. El HTML resultante
es autocontenido (sin librerías externas) y se abre con doble clic.

Uso:
    python visual_reservas.py
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parents[1]
PROCESSED = PROJECT_DIR / "data" / "processed"
TEMPLATE = PROJECT_DIR / "src" / "plantillas" / "reservas.html"
PORTFOLIO_CSV = PROJECT_DIR / "config" / "portafolio_memoria.csv"
OUT = PROJECT_DIR / "outputs" / "reservas_bcrp.html"
OUT_ARTIFACT = PROJECT_DIR / "outputs" / "reservas_bcrp_artifact.html"
PLACEHOLDER = "/*__DATA__*/null"


def load_panel(freq: str) -> pd.DataFrame:
    df = pd.read_csv(PROCESSED / f"bcrp_panel_{freq}.csv", parse_dates=["fecha"],
                     encoding="utf-8-sig")
    return df.set_index("fecha").sort_index()


def num(v, nd: int = 1):
    return None if pd.isna(v) else round(float(v), nd)


def month_key(ts) -> str:
    return f"{ts.year:04d}-{ts.month:02d}"


def build_ownership(d: pd.DataFrame) -> list[dict]:
    """RIN por dueño: último dato diario de cada mes (y el último disponible del mes en curso)."""
    own = d[["rin_diario", "posicion_cambio_diario", "dep_sist_financiero_bcrp_diario",
             "dep_sector_publico_bcrp_diario"]].dropna()
    own.columns = ["rin", "propias", "bancos", "publico"]
    # Sector público + residuo (otras obligaciones): así las tres capas suman la RIN exacta.
    own["publico"] = own.rin - own.propias - own.bancos
    last = own.groupby(own.index.to_period("M")).tail(1)
    # Entre jun y ago-2021 hay días sueltos con residuo negativo; en los cierres de mes no debe haberlos.
    if (last.publico <= 0).any():
        raise ValueError("La capa 'sector público y otros' sale negativa en algún cierre de mes")
    return [{"m": month_key(ts), "f": ts.strftime("%Y-%m-%d"), "rin": num(r.rin, 0),
             "propias": num(r.propias, 0), "bancos": num(r.bancos, 0),
             "publico": num(r.publico, 0)} for ts, r in last.iterrows()]


def build_monthly(m: pd.DataFrame, d: pd.DataFrame) -> tuple[list[dict], str]:
    """Compras netas spot, swaps y TC por mes. El mes en curso se completa con datos diarios."""
    net_m = m["rin_var_compras_netas_mesa"].dropna()
    net_d = d["compras_netas_bcrp_diario"].dropna()
    net_dm = net_d.groupby(net_d.index.to_period("M").to_timestamp()).sum()

    overlap = net_m.index.intersection(net_dm.index)
    gap = (net_m[overlap] - net_dm[overlap]).abs().max()
    print(f"  compras netas: diferencia máx. mensual vs. suma diaria = {gap:.1f} (US$ MM)")

    # Mensual oficial donde existe; suma diaria antes de 1998 y para el mes en curso (parcial).
    net = net_m.combine_first(net_dm)
    partial = [ts for ts in net.index if ts > net_m.index.max()]

    tc_d = d["tc_interbancario_venta_diario"].dropna()
    tc = m["tc_interbancario_prom"].dropna().copy()
    for ts, v in tc_d.groupby(tc_d.index.to_period("M").to_timestamp()).mean().items():
        if ts > tc.index.max():
            tc.loc[ts] = v
    swap = m["bcrp_swap_venta_neto"].dropna()

    months = pd.date_range(min(net.index.min(), tc.index.min()), max(net.index.max(),
                           tc.index.max()), freq="MS")
    rows = [{"m": month_key(ts), "net": num(net.get(ts), 0), "swap": num(swap.get(ts), 0),
             "tc": num(tc.get(ts), 3), "p": 1 if ts in partial else 0} for ts in months]
    last_daily = net_d.index.max().strftime("%Y-%m-%d")
    return rows, last_daily


def build_annual(m: pd.DataFrame, d: pd.DataFrame) -> list[dict]:
    g = m[["rin_var_compras_mesa", "rin_var_ventas_mesa"]].dropna()
    last_month = g.index.max()
    yearly = g.groupby(g.index.year).sum()
    # Meses posteriores al último mensual: la serie diaria es neta, se asigna por signo diario.
    net_d = d["compras_netas_bcrp_diario"].dropna()
    extra = net_d[net_d.index >= last_month + pd.offsets.MonthBegin(1)]
    for ts, v in extra.items():
        if ts.year not in yearly.index:
            yearly.loc[ts.year] = 0.0
        col = "rin_var_compras_mesa" if v > 0 else "rin_var_ventas_mesa"
        yearly.loc[ts.year, col] += abs(v)
    this_year = net_d.index.max().year
    return [{"y": int(y), "compras": num(r.rin_var_compras_mesa, 0),
             "ventas": num(r.rin_var_ventas_mesa, 0), "p": 1 if y == this_year else 0}
            for y, r in yearly.iterrows()]


def build_composition(m: pd.DataFrame) -> dict:
    cols = {"liquidez_intl_valores": "Valores (bonos)",
            "liquidez_intl_depositos": "Depósitos en el exterior",
            "liquidez_intl_oro_plata": "Oro y plata",
            "liquidez_intl_fmi_bis_flar": "Aportes a FMI, BIS y FLAR",
            "liquidez_intl_otros": "Otros"}
    sub = m[list(cols) + ["liquidez_intl_total", "rin_activos_brutos", "rin_obligaciones_cp",
                          "rin"]].dropna()
    ts, r = sub.index.max(), sub.iloc[-1]
    hist = [{"m": month_key(t), **{c.removeprefix("liquidez_intl_"): num(row[c], 0) for c in cols},
             "total": num(row.liquidez_intl_total, 0)} for t, row in sub.iterrows()]
    items = [{"k": c.removeprefix("liquidez_intl_"), "label": lab, "v": num(r[c], 0)}
             for c, lab in cols.items()]
    items.sort(key=lambda it: -it["v"])
    return {"m": month_key(ts), "items": items, "total": num(r.liquidez_intl_total, 0),
            "brutas": num(r.rin_activos_brutos, 0), "oblig": num(r.rin_obligaciones_cp, 0),
            "rin": num(r.rin, 0), "hist": hist}


def build_portfolio() -> dict:
    """Moneda, calificación, plazo y duración del portafolio: no están en BCRPData; se copian a
    mano de la Memoria del BCRP en config/portafolio_memoria.csv (con cuadro y página)."""
    df = pd.read_csv(PORTFOLIO_CSV, encoding="utf-8").sort_values(["dimension", "orden"])
    if df.groupby("corte").ngroups != 1:
        raise ValueError("portafolio_memoria.csv mezcla fechas de corte")
    for dim, g in df[df.unidad == "%"].groupby("dimension"):
        if abs(g.valor.sum() - 100) > 1:
            raise ValueError(f"portafolio_memoria.csv: '{dim}' no suma 100% ({g.valor.sum()})")
    out = {"corte": df.corte.iloc[0], "fuente": df.fuente.iloc[0]}
    for dim, g in df.groupby("dimension"):
        out[dim] = [{"label": r.categoria, "v": float(r.valor)} for r in g.itertuples()]
    return out


def quarter_label(ts) -> str:
    return f"T{(ts.month - 1) // 3 + 1} {ts.year}"


def build_edu(m: pd.DataFrame, q: pd.DataFrame) -> dict:
    """Indicadores de suficiencia y datos de contexto para la pestaña educativa."""
    # RIN / deuda externa de corto plazo (Greenspan-Guidotti), al cierre del último trimestre.
    std = q["deuda_externa_cp"].dropna()
    q_end = std.index.max() + pd.offsets.MonthBegin(2)   # 'fecha' trimestral = primer mes
    rin_q, pos_q = m.loc[q_end, "rin"], m.loc[q_end, "posicion_cambio"]
    # Meses de importaciones: RIN / promedio mensual de los últimos 12 meses.
    imp = m["importaciones"].dropna()
    imp_ts, imp_avg = imp.index.max(), imp.iloc[-12:].mean()
    # RIN / liquidez total (dinero amplio, convertido a US$ al TC de fin de mes).
    liq = m[["liquidez_total", "tc_interbancario_fin", "rin", "posicion_cambio"]].dropna()
    liq_ts, lr = liq.index.max(), liq.iloc[-1]
    liq_usd = lr.liquidez_total / lr.tc_interbancario_fin
    # Reservas como % del PBI (serie del BCRP), trimestral.
    pct = q["reservas_pct_pbi"].dropna()
    # Dolarización: último dato y máximo histórico.
    dc, dl = m["dolarizacion_credito"].dropna(), m["dolarizacion_liquidez"].dropna()
    # Oro: valor de "oro y plata" entre la valuación contable por onza (la plata es marginal).
    g = m[["liquidez_intl_oro_plata", "oro_valuacion_contable"]].dropna()
    g_ts, gr = g.index.max(), g.iloc[-1]
    onzas = gr.liquidez_intl_oro_plata * 1e6 / gr.oro_valuacion_contable
    return {
        "std": num(std.iloc[-1], 0), "std_q": quarter_label(std.index.max()),
        "rin_std": round(rin_q / std.iloc[-1], 1), "pos_std": round(pos_q / std.iloc[-1], 1),
        "imp_avg": num(imp_avg, 0), "imp_m": month_key(imp_ts),
        "rin_imp": round(m.loc[imp_ts, "rin"] / imp_avg, 1),
        "pos_imp": round(m.loc[imp_ts, "posicion_cambio"] / imp_avg, 1),
        "liq_usd": num(liq_usd, 0), "liq_m": month_key(liq_ts),
        "rin_liq": round(100 * lr.rin / liq_usd, 1), "pos_liq": round(100 * lr.posicion_cambio / liq_usd, 1),
        "pct_pbi": [{"q": quarter_label(ts), "v": num(v, 1)} for ts, v in pct.items()],
        "dol_cred": num(dc.iloc[-1], 1), "dol_liq": num(dl.iloc[-1], 1), "dol_m": month_key(dc.index.max()),
        "dol_cred_max": num(dc.max(), 1), "dol_cred_max_m": month_key(dc.idxmax()),
        "oro_moz": round(onzas / 1e6, 2), "oro_t": round(onzas / 32150.7466, 1),
        "oro_precio": num(gr.oro_valuacion_contable, 0), "oro_m": month_key(g_ts),
    }


def build_kpis(d: pd.DataFrame, own: list[dict]) -> dict:
    rin = d["rin_diario"].dropna()
    rin_prev = rin[rin.index.year < rin.index.max().year].iloc[-1]
    net_d = d["compras_netas_bcrp_diario"].dropna()
    ytd = net_d[net_d.index.year == net_d.index.max().year]
    tc = d["tc_interbancario_venta_diario"].dropna()
    return {"rin": num(rin.iloc[-1], 0), "rin_f": rin.index.max().strftime("%Y-%m-%d"),
            "rin_var_anio": num(rin.iloc[-1] - rin_prev, 0),
            "rin_prev_f": rin[rin.index.year < rin.index.max().year].index.max().strftime("%Y-%m-%d"),
            "propias": own[-1]["propias"], "propias_f": own[-1]["f"],
            "propias_pct": round(100 * own[-1]["propias"] / own[-1]["rin"], 1),
            "compras_ytd": num(ytd[ytd > 0].sum(), 0), "ventas_ytd": num(-ytd[ytd < 0].sum(), 0),
            "dias_compra": int((ytd > 0).sum()), "dias_venta": int((ytd < 0).sum()),
            "ytd_anio": int(net_d.index.max().year), "ytd_f": net_d.index.max().strftime("%Y-%m-%d"),
            "tc": num(tc.iloc[-1], 3), "tc_f": tc.index.max().strftime("%Y-%m-%d")}


def main() -> int:
    m, d, q = load_panel("mensual"), load_panel("diaria"), load_panel("trimestral")
    own = build_ownership(d)
    monthly, last_daily = build_monthly(m, d)
    data = {"generado": dt.date.today().isoformat(), "hasta": last_daily,
            "kpi": build_kpis(d, own), "own": own, "mon": monthly,
            "anual": build_annual(m, d), "comp": build_composition(m), "edu": build_edu(m, q),
            "port": build_portfolio()}

    html = TEMPLATE.read_text(encoding="utf-8")
    if PLACEHOLDER not in html:
        raise ValueError(f"La plantilla no tiene el marcador {PLACEHOLDER}")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html.replace(PLACEHOLDER, payload), encoding="utf-8")
    print(f"  {OUT.relative_to(PROJECT_DIR)}  ({OUT.stat().st_size / 1024:.0f} KB; "
          f"{len(own)} meses RIN, {len(monthly)} meses intervención)")

    OUT_ARTIFACT.write_text(artifact_version(OUT.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"  {OUT_ARTIFACT.relative_to(PROJECT_DIR)}  (versión para publicar en claude.ai)")
    return 0


def artifact_version(html: str) -> str:
    """Versión para publicar como Artifact de claude.ai: la plataforma pone su propio
    <html>/<head>/<body>, así que se dejan solo <title>, <style> y el contenido del body."""
    head = re.search(r"<head>(.*?)</head>", html, re.S).group(1)
    body = re.search(r"<body>(.*?)</body>", html, re.S).group(1)
    head = re.sub(r"\s*<meta (charset|name=\"viewport\")[^>]*>", "", head)
    head = head.replace("</title>",
                        '</title>\n<meta name="claude:viewport-fit-sides" content="cover">', 1)
    return head.strip() + "\n" + body.strip() + "\n"


if __name__ == "__main__":
    sys.exit(main())
