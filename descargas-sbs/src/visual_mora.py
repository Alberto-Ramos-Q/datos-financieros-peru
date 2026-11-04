"""Genera `outputs/mora_ssff.html`: tablero público de colocaciones y morosidad del sistema financiero.

Lee cuatro tablas largas de `data/processed/boletin/` (correr antes `leer_boletin.py`):
- `creditos-tipo-situacion`: saldo de créditos directos por tipo de crédito y situación
  (vigentes, refinanciados y reestructurados, atrasados), por entidad y mes.
- `castigos-tipo-credito`: flujo de castigos por tipo de crédito (mensual desde 2016-01; antes,
  trimestral: flujo del trimestre en los cuadros de marzo, junio, setiembre y diciembre, desde 2010-09).
- `creditos-tipo-modalidad-moneda`: créditos en moneda extranjera (miles de US$) por tipo; de ahí
  salen la dolarización y el tipo de cambio implícito de cada mes ((total − MN) / ME, único por mes).
- `deudores-tipo-credito`: número de deudores por tipo de crédito (entidades y total consolidado
  de cada subsistema).
y `data/processed/sf2103_deudores.parquet` para los deudores únicos del sistema (trimestral).

Con esos saldos se calculan en la página el saldo de colocaciones, su crecimiento anual a tipo de
cambio constante, la dolarización, la mora (atrasados / directos), la cartera de alto riesgo
((atrasados + refinanciados + reestructurados) / directos) y la mora ajustada por castigos
((atrasados + castigos 12 m) / (directos + castigos 12 m)), para el sistema (los 5 subsistemas),
cada subsistema y cada entidad. Los agregados son la suma de las entidades (coincide con el total
que publica la SBS salvo errores de origen; ver `_control/<tema>_validacion.csv`). Los deudores no
se suman: un deudor con créditos en dos entidades se cuenta una vez en el total del subsistema.

Deudores con errores de origen (desde el 2026-11-03): algunos Excel de deudores de la SBS repiten las
cifras de otro mes (el mes entero, o solo la columna del total). `load_debtors` los quita con
`errores_origen.drop_debtor_source_errors` (lista y detalle en `errores_origen.py`), así que esos
subsistema-mes no tienen deudores ni saldo por deudor en los datos. La página no deja huecos: en los
KPI, el ranking, la ficha y las tablas muestra el último dato válido con su mes y el motivo («la SBS
repitió las cifras de abr-2016»), con `deuErr` / `deuTotErr` del JSON. Los deudores únicos del
sistema (SF-2103) no están afectados. Desde el 2026-11-03 `load_debtors` quita también los deudores de
una sola entidad repetidos (`entities=True`: CMAC Sullana 2024-06, que repite mayo).

Cifras repetidas de otro mes (2026-11-03, `errores_origen.RANKING_REPEATS`): en 9 entidad-mes la SBS repite
el mes anterior en casi todos los cuadros (CMAC Pisco 2014-01 → 04, CRAC Señor de Luren 2015-05, CRAC Chavín /
Raíz 2016-03 y 04, Financiera TFC 2019-11, CMAC Sullana 2024-06). `mask_repeats` deja vacías esas cifras en la
serie de la entidad, por cuadro de origen (`COL_TEMA`: saldos, castigos, moneda y deudores; los deudores de
Pisco, Luren, Raíz y TFC son propios y se quedan), y los castigos de 12 meses de los 11 meses siguientes (su
ventana suma el flujo repetido; solo pesa en Raíz). Los agregados (subsistema y sistema) se arman antes y siguen
sumando lo publicado, como los totales de la SBS. La página recibe la lista en `rep`: la ficha y la tabla de la
entidad muestran el último dato válido con su mes y el motivo, el ranking y la dispersión la omiten con una nota
(también cuando falta el crecimiento anual o la mora ajustada porque su cuenta usa un mes repetido) y el tooltip
del hueco del gráfico dice «sin dato: en jun-2024 la SBS repitió las cifras de may-2024 …».

Genera además `outputs/mora_ssff_artifact.html`, la versión para publicar como Artifact de
claude.ai (sin <html>/<head>/<body>).

Uso:
    python visual_mora.py
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from errores_origen import (DEBTOR_SOURCE_ERRORS, DEBTOR_TOTAL_ERRORS, drop_debtor_source_errors,  # noqa: E402
                            repeat_footnote, repeats_tema, source_repeat_mask, source_repeats)

PROJECT_DIR = Path(__file__).resolve().parents[1]
BOLETIN = PROJECT_DIR / "data" / "processed" / "boletin"
# Primer mes de los tableros públicos: toda lectura de una tabla del boletín o del panel pasa por
# `read_table`, que descarta lo anterior. Desde el 2026-10-28 es 2010-07 (antes 2015-01), el primer mes
# de la historia extendida. Las copias privadas siguen en 2015-01: fijan PRIVATE_START_PERIOD en
# `visual_mora.START_PERIOD` al importar (read_table lee el global del módulo en cada llamada).
START_PERIOD = 201007
PRIVATE_START_PERIOD = 201501


def read_table(path, **kwargs) -> pd.DataFrame:
    """`pd.read_parquet` de una tabla procesada (boletín o panel) desde START_PERIOD."""
    filters = list(kwargs.pop("filters", None) or []) + [("periodo", ">=", START_PERIOD)]
    return pd.read_parquet(path, filters=filters, **kwargs)

ENTIDADES = PROJECT_DIR / "config" / "entidades" / "entidad.csv"
TEMPLATE = PROJECT_DIR / "src" / "plantillas" / "mora.html"
OUT = PROJECT_DIR / "outputs" / "mora_ssff.html"
OUT_ARTIFACT = PROJECT_DIR / "outputs" / "mora_ssff_artifact.html"
PLACEHOLDER = "/*__DATA__*/null"

SUBSYSTEMS = [
    ("banca-multiple", "Banca múltiple", "Banca"),
    ("empresas-financieras", "Empresas financieras", "Financieras"),
    ("cajas-municipales", "Cajas municipales", "CMAC"),
    ("cajas-rurales", "Cajas rurales", "CRAC"),
    ("empresas-credito", "Empresas de créditos", "EC"),
]

BUSINESS = ["corporativos", "grandes_empresas", "medianas_empresas", "pequenas_empresas", "microempresas"]
# (clave, etiqueta, nivel). Nivel 1 = subtipo de la fila anterior de nivel 0.
TYPES = [
    ("total", "Total", 0),
    ("empresariales", "Empresariales", 0),
    ("corporativos", "Corporativos", 1),
    ("grandes_empresas", "Grandes empresas", 1),
    ("medianas_empresas", "Medianas empresas", 1),
    ("pequenas_empresas", "Pequeñas empresas", 1),
    ("microempresas", "Microempresas", 1),
    ("consumo", "Consumo", 0),
    ("consumo_revolvente", "Consumo revolvente", 1),
    ("consumo_no_revolvente", "Consumo no revolvente", 1),
    ("hipotecarios", "Hipotecarios", 0),
]
# Solo banca y financieras separan el consumo en revolvente y no revolvente.
SPLIT_CONSUMO = {"banca-multiple", "empresas-financieras"}
FIRST_MONTHLY_WRITEOFF = 201601   # antes, castigos trimestrales
# Primer mes del primer trimestre de castigos publicado (el cuadro de 2010-09 trae julio-setiembre).
FIRST_WRITEOFF_QUARTER = 201007
# Los tipos de crédito a empresas se separan desde 2010-10: antes, una sola columna «empresariales».
FIRST_BUSINESS_SPLIT = 201010


def writeoff_start() -> int:
    """Primer mes de la suma de castigos: el primer mes de trimestre (ene, abr, jul u oct) desde
    START_PERIOD y desde el primer trimestre publicado."""
    return next(m for m in month_range(max(START_PERIOD, FIRST_WRITEOFF_QUARTER), 210012) if m % 100 % 3 == 1)


def adj_months(last: int) -> list[int]:
    """Meses con castigos de 12 meses completos. Mientras la ventana incluya castigos trimestrales
    solo cuadra en los cierres de trimestre (marzo, junio, setiembre y diciembre); desde que hay 12
    meses mensuales (2016-12), todos."""
    first = month_range(writeoff_start(), 210012)[11]
    monthly = month_range(FIRST_MONTHLY_WRITEOFF, 210012)[11]
    return [m for m in month_range(first, last) if m >= monthly or m % 100 % 3 == 0]


def month_key(p: int) -> str:
    return f"{p // 100}-{p % 100:02d}"


def month_range(a: int, b: int) -> list[int]:
    out, y, m = [], a // 100, a % 100
    while y * 100 + m <= b:
        out.append(y * 100 + m)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def load_stocks() -> pd.DataFrame:
    """Saldos por (periodo, subsistema, entidad, tipo) con columnas tot, atr, ref (miles de S/)."""
    d = read_table(BOLETIN / "creditos-tipo-situacion.parquet")
    d = d[~d["es_total"]].copy()
    d[["tipo", "sit"]] = d["apertura"].str.split("|", expand=True)
    key = ["periodo", "subsistema", "id_entidad"]
    w = d[d["tipo"] != "total"].pivot_table(index=key + ["tipo"], columns="sit", values="valor", aggfunc="sum")
    w = w.rename(columns={"atrasados": "atr", "refinanciados_reestructurados": "ref", "vigentes": "vig"}).fillna(0.0)
    w["tot"] = w["vig"] + w["ref"] + w["atr"]
    w = w[["tot", "atr", "ref"]].reset_index()

    def add(name: str, members: list[str], mask=None) -> pd.DataFrame:
        sub = w[w["tipo"].isin(members)]
        if mask is not None:
            sub = sub[mask(sub)]
        g = sub.groupby(key, as_index=False)[["tot", "atr", "ref"]].sum()
        g["tipo"] = name
        return g

    split = lambda x: x["subsistema"].isin(SPLIT_CONSUMO)   # noqa: E731
    parts = [
        w,
        add("consumo", ["consumo_revolvente", "consumo_no_revolvente"], split),
        add("empresariales", BUSINESS),
        add("total", [t for t in w["tipo"].unique()]),
    ]
    out = pd.concat(parts, ignore_index=True)

    # Control: el total armado desde los tipos debe cuadrar con la columna TOTAL publicada.
    pub = d[d["apertura"] == "total|total"].set_index(key)["valor"]
    chk = out[out["tipo"] == "total"].set_index(key)["tot"]
    gap = (chk / pub - 1).abs().dropna()
    if (gap > 1e-3).any():
        print(f"  AVISO: {int((gap > 1e-3).sum())} entidad-mes donde la suma de tipos difiere del TOTAL publicado")
    return out


def load_writeoffs(stocks: pd.DataFrame) -> pd.DataFrame:
    """Castigos de los últimos 12 meses por (periodo, subsistema, entidad, tipo), en los meses de
    `adj_months`. Los tipos de crédito a empresas, desde la primera ventana sin la columna agregada
    «empresariales» (2011-09 con la historia desde 2010-07)."""
    c = read_table(BOLETIN / "castigos-tipo-credito.parquet")
    c = c[(~c["es_total"]) & c["variable"].isin(["castigos_flujo_mensual", "castigos_flujo_trimestral"])]
    c = c.rename(columns={"apertura": "tipo"})
    key = ["periodo", "subsistema", "id_entidad"]
    # Una entidad que cambia de subsistema puede salir en los dos cuadros el mismo mes (Santander
    # Consumer en 2025-04): se queda la fila del subsistema donde están sus créditos ese mes.
    where = stocks.loc[stocks["tipo"] == "total", key].drop_duplicates()
    c = c.merge(where, on=key, how="inner")
    c = c.groupby(key + ["tipo"], as_index=False)["valor"].sum()
    emp = c[c["tipo"].isin(BUSINESS)].groupby(key, as_index=False)["valor"].sum().assign(tipo="empresariales")
    c = pd.concat([c, emp], ignore_index=True)

    # Rejilla completa de meses por entidad (sin castigo publicado = 0) y suma móvil de 12 meses. El
    # flujo trimestral queda en el mes de cierre del trimestre: la suma de 12 meses solo vale en los
    # cierres de trimestre hasta que la ventana es toda mensual (`adj_months`).
    last = int(stocks["periodo"].max())
    valid = adj_months(last)
    months = month_range(writeoff_start(), last)
    flows = c.pivot_table(index=["subsistema", "id_entidad", "tipo"], columns="periodo", values="valor", aggfunc="sum")
    flows = flows.reindex(columns=months).fillna(0.0)
    roll = flows.T.rolling(12, min_periods=12).sum().T
    roll = roll.loc[:, valid]
    out = roll.stack().rename("cas").reset_index()
    first_split = month_range(FIRST_BUSINESS_SPLIT, 210012)[11]
    return out[~(out["tipo"].isin(BUSINESS) & (out["periodo"] < first_split))]


def load_currency() -> tuple[pd.DataFrame, pd.Series]:
    """Créditos en moneda extranjera (miles de US$) por (periodo, subsistema, entidad, tipo) y el
    tipo de cambio implícito de cada mes. El cuadro no separa el consumo revolvente / no revolvente."""
    d = read_table(BOLETIN / "creditos-tipo-modalidad-moneda.parquet")
    d = d[~d["es_total"]].copy()
    d[["tipo", "modalidad", "mon"]] = d["apertura"].str.split("|", expand=True)
    d = d[d["modalidad"] == "total"]
    key = ["periodo", "subsistema", "id_entidad"]
    w = d.pivot_table(index=key + ["tipo"], columns="mon", values="valor", aggfunc="sum").reset_index()
    # La SBS expresa el total en soles con un solo tipo de cambio por mes: se toma la mediana por
    # entidad-tipo con saldo en ME relevante (la dispersión es < 1e-5).
    big = w[w["me"] > 100]
    tc = ((big["total"] - big["mn"]) / big["me"]).groupby(big["periodo"]).median()
    w = w[w["tipo"] != "total"].rename(columns={"me": "meu"})[key + ["tipo", "meu"]]
    emp = w[w["tipo"].isin(BUSINESS)].groupby(key, as_index=False)["meu"].sum().assign(tipo="empresariales")
    tot = w.groupby(key, as_index=False)["meu"].sum().assign(tipo="total")
    return pd.concat([w, emp, tot], ignore_index=True), tc


def load_debtors() -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    """Número de deudores: por entidad y tipo, total consolidado de cada subsistema por tipo
    (fila TOTAL publicada, no la suma) y deudores únicos del sistema (SF-2103, trimestral, solo total).
    No hay deudores de «empresariales» (un deudor puede tener varios tipos) ni del consumo revolvente.
    Sin los errores de origen de `errores_origen.py` (meses y totales que repiten las cifras de otro
    mes): esos subsistema-mes quedan sin dato aquí y en todo lo que se calcula con ellos (saldo por
    deudor). Desde el 2026-11-03 también las entidad-mes cuyos deudores repiten otro mes (`entities=True`: CMAC
    Sullana 2024-06; el total del subsistema no cambia). También lo usa `indicadores_datos.py`."""
    d = drop_debtor_source_errors(read_table(BOLETIN / "deudores-tipo-credito.parquet"), entities=True)
    d = d.rename(columns={"apertura": "tipo", "valor": "deu"})
    ent = d[~d["es_total"]].groupby(["periodo", "subsistema", "id_entidad", "tipo"], as_index=False)["deu"].sum()
    sub = d[d["es_total"]].groupby(["periodo", "subsistema", "tipo"], as_index=False)["deu"].sum()
    sf = pd.read_parquet(PROJECT_DIR / "data" / "processed" / "sf2103_deudores.parquet")
    sysd = sf[sf["grupo"] == "operaciones-multiples"].set_index("periodo")["deudores"]
    return ent, sub, sysd


def debtor_error_notes() -> tuple[list, list]:
    """Para la página: (deuErr, deuTotErr). deuErr = [[mes, subsistema, mes repetido]] de los meses enteros
    repetidos; deuTotErr = [[mes, subsistema, alcance, mes repetido]] de los totales repetidos (alcance «sub»:
    solo el total del subsistema; «all»: también el total de cada entidad). El mes repetido se busca en los
    datos (el total del subsistema idéntico a ±12 meses); None si no se encuentra."""
    d = read_table(BOLETIN / "deudores-tipo-credito.parquet", filters=[("es_total", "==", True)])
    t = d[d["apertura"] == "total"].pivot_table(index="periodo", columns="subsistema", values="valor")
    idx = lambda p: p // 100 * 12 + p % 100   # noqa: E731

    def source(per: int, sub: str):
        x = t[sub].dropna() if sub in t else pd.Series(dtype=float)
        if per not in x.index:
            return None
        same = [p for p, v in x.items() if p != per and v == x[per] and abs(idx(p) - idx(per)) <= 12]
        return month_key(min(same, key=lambda p: abs(idx(p) - idx(per)))) if same else None

    err = [[month_key(m), s, source(m, s)] for m, s in sorted(DEBTOR_SOURCE_ERRORS) if m >= START_PERIOD]
    tot = [[month_key(m), s, kind, source(m, s)] for (m, s), kind in sorted(DEBTOR_TOTAL_ERRORS.items())
           if m >= START_PERIOD]
    return err, tot


COLS = ("tot", "atr", "ref", "cas", "meu", "deu")
# Cuadro (tema de data/processed/boletin) del que sale cada columna, para `mask_repeats`.
COL_TEMA = {"tot": "creditos-tipo-situacion", "atr": "creditos-tipo-situacion", "ref": "creditos-tipo-situacion",
            "cas": "castigos-tipo-credito", "meu": "creditos-tipo-modalidad-moneda", "deu": "deudores-tipo-credito"}


def mask_repeats(full: pd.DataFrame) -> tuple[pd.DataFrame, list[list], int]:
    """Copia de `full` (una fila por entidad, mes y tipo) con vacíos en las columnas que vienen de un cuadro en que la
    SBS repite las cifras de otro mes (`errores_origen.RANKING_REPEATS`, «row» = all: las que solo repiten el ranking
    no tocan estos cuadros). Solo para la serie de la entidad: los agregados se arman antes, con lo publicado (la SBS
    suma esas cifras en sus totales). Los castigos de 12 meses (`cas`) también quedan vacíos en los 11 meses que siguen
    a un mes repetido, porque su ventana suma ese flujo (solo pesa en CRAC Raíz 2016-03/04: las demás entidad-mes son
    el último mes de la entidad). Devuelve además la lista para la página [mes, «subsistema/entidad», mes repetido,
    «fila», motivo] y el número de valores que pasan a vacío."""
    out = full.copy()
    before = out[list(COLS)].notna().sum().sum()
    for col, tema in COL_TEMA.items():
        out.loc[source_repeat_mask(out, tema), col] = np.nan
    rep = []
    mon = out["periodo"] // 100 * 12 + out["periodo"] % 100
    for (per, sub, ent), r in source_repeats().items():
        if r["row"] != "all":
            continue
        own = (out["subsistema"] == sub) & (out["id_entidad"] == ent)
        if not (own & (out["periodo"] == per)).any():
            continue
        if repeats_tema(r, COL_TEMA["cas"]):
            m0 = per // 100 * 12 + per % 100
            out.loc[own & (mon > m0) & (mon <= m0 + 11), "cas"] = np.nan
        note = repeat_footnote(r)
        rep.append([month_key(per), f"{sub}/{ent}", month_key(r["same_as"]), "fila",
                    "nota al pie del cuadro: " + note if note else "sin nota al pie"])
    n = int(before - out[list(COLS)].notna().sum().sum())
    return out, sorted(rep), n


def series_block(g: pd.DataFrame, months: list[int], split_ok: bool) -> dict:
    """Arma {a: índice del primer mes, T: {tipo: [tot, atr, ref, cas, meu, deu]}} para un ámbito.
    meu en miles de US$; deu en número de deudores; el resto en miles de S/."""
    pos = {m: i for i, m in enumerate(months)}
    present = sorted(g["periodo"].unique())
    a, b = pos[present[0]], pos[present[-1]]
    T = {}
    for key, _, _ in TYPES:
        if key.startswith("consumo_") and not split_ok:
            continue
        s = g[g["tipo"] == key].set_index("periodo")
        if s.empty or s["tot"].abs().sum() == 0:
            continue
        arrs = []
        for col in COLS:
            v = s[col] if col in s else pd.Series(dtype=float)
            row = []
            for m in months[a:b + 1]:
                x = v.get(m, np.nan)
                row.append(None if pd.isna(x) else int(round(float(x))))
            arrs.append(row)
        T[key] = arrs
    return {"a": a, "T": T}


def aggregate(df: pd.DataFrame) -> pd.DataFrame:
    """Suma de entidades por (periodo, tipo). El saldo en ME queda vacío si las entidades con dato
    de moneda no cubren el 99.5% del saldo (p. ej. el sistema antes de 2015-09, cuando solo la banca
    publica el cuadro por moneda)."""
    g = df.assign(cov=df["tot"].where(df["meu"].notna(), 0.0))
    out = g.groupby(["periodo", "tipo"], as_index=False)[["tot", "atr", "ref", "cas", "meu", "cov"]].sum(min_count=1)
    out.loc[~(out["cov"] >= 0.995 * out["tot"]), "meu"] = np.nan
    return out.drop(columns="cov")


def add_gone_writeoffs(g: pd.DataFrame, gone: pd.DataFrame) -> pd.DataFrame:
    """Suma a un agregado los castigos de 12 meses de entidades que ya no tienen saldo en él en el mes
    (pasaron a otro subsistema, fueron absorbidas o liquidadas). Solo en los meses y tipos en que el
    agregado ya tiene mora ajustada (castigos no vacíos)."""
    if gone.empty:
        return g
    extra = gone.groupby(["periodo", "tipo"])["cas"].sum()
    add = [extra.get(k, 0.0) for k in zip(g["periodo"], g["tipo"])]
    g = g.copy()
    g["cas"] = g["cas"] + np.asarray(add, dtype=float)   # NaN + x sigue NaN: no crea meses nuevos
    return g


def build_data() -> dict:
    stocks = load_stocks()
    cas = load_writeoffs(stocks)
    meu, tc = load_currency()
    deu_ent, deu_sub, deu_sys = load_debtors()
    key = ["periodo", "subsistema", "id_entidad", "tipo"]
    full = stocks.merge(cas, on=key, how="left").merge(meu, on=key, how="left")
    # Sin castigo publicado en la ventana = 0; el consumo revolvente / no revolvente no tiene
    # castigos propios (la SBS los publica para todo el consumo), así que queda sin mora ajustada.
    # Los tipos a empresas no tienen castigos separados en la primera ventana (2010-09 agregado).
    last = int(full["periodo"].max())
    first_split = month_range(FIRST_BUSINESS_SPLIT, 210012)[11]
    has_window = (full["periodo"].isin(adj_months(last)) & ~full["tipo"].str.startswith("consumo_")
                  & ~(full["tipo"].isin(BUSINESS) & (full["periodo"] < first_split)))
    full.loc[has_window, "cas"] = full.loc[has_window, "cas"].fillna(0.0)
    # Castigos sin saldo de la entidad en ese subsistema y mes: los de una entidad que salió del subsistema
    # (traspaso, absorción, liquidación) en los 12 meses. Hasta el 2026-10-31 se perdían al cruzar con los
    # saldos; ahora cuentan en el subsistema donde se castigaron y en el sistema (no en la serie de la entidad).
    chk = cas.merge(stocks[key].drop_duplicates(), on=key, how="left", indicator=True)
    gone = chk.loc[(chk["_merge"] == "left_only") & (chk["cas"] != 0), key + ["cas"]]
    months = month_range(int(full["periodo"].min()), int(full["periodo"].max()))

    names = pd.read_csv(ENTIDADES, dtype=str).set_index("id_entidad")["nombre_actual"]
    panel = read_table(PROJECT_DIR / "data" / "processed" / "panel_entidad_mes.parquet",
                            columns=["periodo", "subsistema", "id_entidad", "nombre_entidad"])
    last_name = (panel.sort_values("periodo").groupby(["subsistema", "id_entidad"])["nombre_entidad"].last())

    scopes: dict[str, dict] = {}
    # El sistema llega hasta el último mes que publicaron los cinco subsistemas: si uno se atrasa, sumar
    # solo los demás haría caer el saldo y el crecimiento del sistema sin que haya pasado nada.
    sys_end = int(full.groupby("subsistema")["periodo"].max().min())
    sysg = add_gone_writeoffs(aggregate(full[full["periodo"] <= sys_end]), gone[gone["periodo"] <= sys_end])
    sysg.loc[sysg["tipo"] == "total", "deu"] = sysg.loc[sysg["tipo"] == "total", "periodo"].map(deu_sys)
    # En el sistema no se separa el consumo revolvente (cajas y EC no lo publican).
    scopes["sistema"] = {"n": "Sistema financiero", "s": None, **series_block(sysg, months, False)}
    for sub, label, short in SUBSYSTEMS:
        g = add_gone_writeoffs(aggregate(full[full["subsistema"] == sub]), gone[gone["subsistema"] == sub])
        g = g.merge(deu_sub[deu_sub["subsistema"] == sub].drop(columns="subsistema"), on=["periodo", "tipo"], how="left")
        scopes[sub] = {"n": label, "s": sub, **series_block(g, months, sub in SPLIT_CONSUMO)}

    full = full.merge(deu_ent, on=key, how="left")
    # Serie de la entidad sin las cifras que la SBS repite de otro mes (los agregados de arriba no cambian).
    full, rep, n_masked = mask_repeats(full)
    print(f"  Cifras repetidas de otro mes: {len(rep)} entidad-mes, {n_masked} valores de entidad vacíos "
          f"(errores_origen.RANKING_REPEATS)")
    entities = []
    for (sub, ent), g in full.groupby(["subsistema", "id_entidad"]):
        k = f"{sub}/{ent}"
        name = last_name.get((sub, ent)) or names.get(ent, ent)
        block = series_block(g, months, sub in SPLIT_CONSUMO)
        if "total" not in block["T"]:   # sin créditos en todo el periodo (p. ej. Deutsche Bank)
            continue
        scopes[k] = {"n": name, "s": sub, **block}
        entities.append(k)
    # Una entidad que cambió de subsistema tiene una serie por subsistema: «o» enlaza las otras,
    # para calcular el crecimiento anual en los 12 meses que siguen al traspaso.
    by_id: dict[str, list[str]] = {}
    for k in entities:
        by_id.setdefault(k.split("/", 1)[1], []).append(k)
    for ks in by_id.values():
        if len(ks) > 1:
            for k in ks:
                scopes[k]["o"] = [x for x in ks if x != k]

    last = months[-1]
    # Primer mes con saldo en ME del sistema (todos los subsistemas publican el cuadro por moneda).
    fx_from = int(sysg.loc[(sysg["tipo"] == "total") & sysg["meu"].notna(), "periodo"].min())
    deu_err, deu_tot_err = debtor_error_notes()
    return {
        "months": [month_key(m) for m in months],
        # Mora ajustada: trimestral desde adjFrom, mensual desde adjMonthly.
        "adjFrom": month_key(adj_months(last)[0]),
        "adjMonthly": month_key(month_range(FIRST_MONTHLY_WRITEOFF, 210012)[11]),
        "fxFrom": month_key(fx_from),
        "adjFromSub": month_key(next(m for m in adj_months(last) if m >= month_range(FIRST_BUSINESS_SPLIT, 210012)[11])),
        "tc": [None if pd.isna(tc.get(m)) else round(float(tc.get(m)), 4) for m in months],
        "types": [{"k": k, "l": l, "lv": lv} for k, l, lv in TYPES],
        "subs": [{"k": k, "l": l, "s": s} for k, l, s in SUBSYSTEMS],
        "scopes": scopes,
        "entities": entities,
        # Deudores sin dato por errores de origen de la SBS (la página muestra el último dato válido y el motivo).
        "deuErr": deu_err,
        "deuTotErr": deu_tot_err,
        # Entidad-mes con las cifras de otro mes (errores_origen.RANKING_REPEATS): [mes, ámbito, mes repetido, alcance,
        # motivo]. La página muestra el último dato válido con su mes y el motivo; en los gráficos, un hueco.
        "rep": rep,
        "hasta": month_key(last),
        # Último mes con los cinco subsistemas (= último mes del sistema): mes por defecto del tablero.
        "allHasta": month_key(sys_end),
        "generado": dt.date.today().isoformat(),
    }


def artifact_version(html: str) -> str:
    """Versión para publicar como Artifact de claude.ai: la plataforma pone su propio
    <html>/<head>/<body>, así que se dejan solo <title>, <style> y el contenido del body."""
    head = re.search(r"<head>(.*?)</head>", html, re.S).group(1)
    body = re.search(r"<body>(.*?)</body>", html, re.S).group(1)
    head = re.sub(r"\s*<meta (charset|name=\"viewport\")[^>]*>", "", head)
    head = head.replace("</title>",
                        '</title>\n<meta name="claude:viewport-fit-sides" content="cover">', 1)
    return head.strip() + "\n" + body.strip() + "\n"


def main() -> int:
    print("Armando datos de morosidad...")
    data = build_data()
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    template = TEMPLATE.read_text(encoding="utf-8")
    if PLACEHOLDER not in template:
        print(f"ERROR: la plantilla no tiene el marcador {PLACEHOLDER}")
        return 1
    html = template.replace(PLACEHOLDER, payload)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    OUT_ARTIFACT.write_text(artifact_version(html), encoding="utf-8")
    n_ent = len(data["entities"])
    print(f"  {data['months'][0]} a {data['hasta']}, {n_ent} series de entidad, datos {len(payload) / 1e6:.1f} MB")
    print(f"  Último mes con los 5 subsistemas (sistema y mes por defecto): {data['allHasta']}")
    print(f"  Escrito {OUT.relative_to(PROJECT_DIR)} y {OUT_ARTIFACT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
