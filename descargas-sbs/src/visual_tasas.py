"""Genera `outputs/tasas_activas.html`: tablero público de tasas de interés activas del sistema financiero.

Insumos (correr antes `leer_tasas.py` y `leer_boletin.py`):
- `data/processed/tasas_activas.parquet`: tasas activas anuales en moneda nacional por tipo de crédito,
  subproducto y entidad, y la columna «Promedio» de cada subsistema, tal como las publica la SBS
  (cuadro «Tasas activas anuales por tipo de crédito y empresa»). Banca y financieras: promedio de las
  operaciones de los últimos 30 días útiles al corte (`diario_30d`); cajas municipales, cajas rurales
  y empresas de créditos: operaciones del mes (`mensual`).
- `data/processed/boletin/creditos-tipo-situacion.parquet`: saldo de créditos directos por tipo y
  situación, para la mora (atrasados / directos) y el tamaño de cada entidad en el mismo tipo de
  crédito (eje de la dispersión). Es el saldo en MN y ME; las tasas son solo de MN.
- `data/processed/panel_entidad_mes.parquet`: nombre vigente de cada entidad.

Reglas:
- Las tasas que se muestran son las publicadas (entidad o «Promedio» del subsistema). No se calcula
  un promedio del sistema: la SBS no publica los montos desembolsados con los que pondera, y un
  promedio simple de tasas sería engañoso.
- Cálculos propios (se rotulan como tales en la página): la mora y el saldo por tipo de cada
  subsistema (suma de entidades), y en la página la dispersión entre entidades (mínimo, cuartiles,
  mediana y máximo, sin ponderar).
- «-» (sin operaciones) queda como nulo; «s.i.» (la entidad no reportó) se marca como "s".
- Hipotecarios: la fila del tipo y la de «préstamos hipotecarios para vivienda» son idénticas en
  todos los archivos (se verifica aquí); solo se guarda el total.
- Tasa máxima del BCRP (Ley 31143) por mes en `CAPS`, con su circular de origen.

Genera además `outputs/tasas_activas_artifact.html`, la versión para publicar como Artifact de
claude.ai (sin <html>/<head>/<body>).

Uso:
    python visual_tasas.py
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from visual_mora import (ENTIDADES, PROJECT_DIR, SUBSYSTEMS, artifact_version, read_table,  # noqa: E402
                         month_key, month_range)

RATES = PROJECT_DIR / "data" / "processed" / "tasas_activas.parquet"
BOLETIN = PROJECT_DIR / "data" / "processed" / "boletin"
PANEL = PROJECT_DIR / "data" / "processed" / "panel_entidad_mes.parquet"
TEMPLATE = PROJECT_DIR / "src" / "plantillas" / "tasas.html"
OUT = PROJECT_DIR / "outputs" / "tasas_activas.html"
OUT_ARTIFACT = PROJECT_DIR / "outputs" / "tasas_activas_artifact.html"
PLACEHOLDER = "/*__DATA__*/null"

# (clave del lector, etiqueta, etiqueta corta, tipos del cuadro de créditos por situación)
TYPES = [
    ("corporativo", "Corporativos", "Corporativo", ["corporativos"]),
    ("grandes", "Grandes empresas", "Grandes", ["grandes_empresas"]),
    ("medianas", "Medianas empresas", "Medianas", ["medianas_empresas"]),
    ("pequenas", "Pequeñas empresas", "Pequeñas", ["pequenas_empresas"]),
    ("micro", "Microempresas", "Micro", ["microempresas"]),
    ("consumo", "Consumo", "Consumo", ["consumo", "consumo_revolvente", "consumo_no_revolvente"]),
    ("hipotecario", "Hipotecarios para vivienda", "Hipotecario", ["hipotecarios"]),
]
# Subproductos en el orden en que los publica la SBS: (clave, etiqueta, etiqueta corta).
_EMP = [
    ("descuentos", "Descuentos", "Descuentos"),
    ("prestamos_hasta_30d", "Préstamos hasta 30 días", "Hasta 30 días"),
    ("prestamos_31_90d", "Préstamos de 31 a 90 días", "31 a 90 días"),
    ("prestamos_91_180d", "Préstamos de 91 a 180 días", "91 a 180 días"),
    ("prestamos_181_360d", "Préstamos de 181 a 360 días", "181 a 360 días"),
    ("prestamos_mas_360d", "Préstamos a más de 360 días", "Más de 360 días"),
]
SUBPRODUCTS = {
    "corporativo": _EMP, "grandes": _EMP, "medianas": _EMP, "pequenas": _EMP,
    "micro": [
        ("tarjetas_credito", "Tarjetas de crédito", "Tarjetas"),
        ("descuentos", "Descuentos", "Descuentos"),
        ("prestamos_revolventes", "Préstamos revolventes", "Revolventes"),
        ("cuota_fija_hasta_30d", "Préstamos a cuota fija hasta 30 días", "Cuota fija ≤ 30 d"),
        ("cuota_fija_31_90d", "Préstamos a cuota fija de 31 a 90 días", "Cuota fija 31–90 d"),
        ("cuota_fija_91_180d", "Préstamos a cuota fija de 91 a 180 días", "Cuota fija 91–180 d"),
        ("cuota_fija_181_360d", "Préstamos a cuota fija de 181 a 360 días", "Cuota fija 181–360 d"),
        ("cuota_fija_mas_360d", "Préstamos a cuota fija a más de 360 días", "Cuota fija > 360 d"),
    ],
    "consumo": [
        ("tarjetas_credito", "Tarjetas de crédito", "Tarjetas"),
        ("prestamos_revolventes", "Préstamos revolventes", "Revolventes"),
        ("no_revolvente_autos", "Préstamos no revolventes para automóviles", "Automóviles"),
        ("no_revolvente_libre_hasta_360d", "Préstamos no revolventes de libre disponibilidad hasta 360 días",
         "Libre disp. ≤ 360 d"),
        ("no_revolvente_libre_mas_360d", "Préstamos no revolventes de libre disponibilidad a más de 360 días",
         "Libre disp. > 360 d"),
        ("pignoraticios", "Créditos pignoraticios", "Pignoraticios"),
    ],
    "hipotecario": [],
}
FORM = {"banca-multiple": "30d", "empresas-financieras": "30d", "cajas-municipales": "mes",
        "cajas-rurales": "mes", "empresas-credito": "mes"}

# Tasa máxima del BCRP en moneda nacional (% anual) para los créditos de consumo, consumo de bajo monto,
# pequeña empresa y microempresa (Ley 31143, art. 52 de la Ley Orgánica del BCRP; metodología de la
# Circular 0008-2021-BCRP: 2 × el promedio de 6 observaciones de fin de mes de la tasa promedio de
# consumo en MN del sistema financiero publicada por la SBS). Una fila por vigencia semestral:
# (desde AAAA-MM-DD, tasa máxima MN, nota informativa del BCRP que la anuncia). Coinciden con la serie
# diaria PD38590DD de BCRPData. El valor de un mes es el vigente el último día de ese mes.
CAPS: list[tuple[str, float, str]] = [
    ("2021-05-10", 83.40, "Nota informativa del 28-04-2021"),
    ("2021-11-01", 83.64, "Nota informativa del 14-10-2021"),
    ("2022-05-01", 83.70, "Nota informativa del 11-04-2022"),
    ("2022-11-01", 87.91, "Nota informativa del 04-10-2022"),
    ("2023-05-01", 96.32, "Nota informativa del 03-04-2023"),
    ("2023-11-01", 101.86, "Nota informativa del 04-10-2023"),
    ("2024-05-01", 109.83, "Nota informativa del 01-04-2024"),
    ("2024-11-01", 112.98, "Nota informativa del 01-10-2024"),
    ("2025-05-01", 115.14, "Nota informativa del 01-04-2025"),
    ("2025-11-01", 113.16, "Nota informativa del 01-10-2025"),
    ("2026-05-01", 114.13, "Nota informativa del 01-04-2026"),
    ("2026-11-01", 114.68, "Nota informativa del 01-10-2026"),
]
CAP_TYPES = ["consumo", "pequenas", "micro"]
# Entrada en vigencia escalonada (Circular 0008-2021-BCRP, disposición transitoria A): bancos desde el
# 10-05-2021, cajas municipales desde el 01-06-2021 y el resto de empresas desde el 01-07-2021.
CAP_START = {"banca-multiple": "2021-05-10", "cajas-municipales": "2021-06-01", "empresas-financieras": "2021-07-01",
             "cajas-rurales": "2021-07-01", "empresas-credito": "2021-07-01"}

KEY = ["periodo", "subsistema", "id_entidad"]


def load_rates() -> pd.DataFrame:
    t = pd.read_parquet(RATES)
    for c in ["subsistema", "tipo_credito", "subproducto", "sin_dato", "formulario"]:
        t[c] = t[c].astype(str)
    if (t["moneda"].astype(str) != "MN").any():
        raise ValueError("se esperaba solo moneda nacional")
    # Hipotecarios: total = vivienda en todas las celdas (si deja de serlo, hay que mostrar ambas filas).
    h = t[t["tipo_credito"] == "hipotecario"].pivot_table(
        index=["periodo", "subsistema", "entidad_original"], columns="subproducto", values="tasa")
    if ((h["total"] - h["hipotecario_vivienda"]).abs() > 1e-9).any():
        raise ValueError("hipotecarios: la fila total difiere de vivienda")
    t = t[~((t["tipo_credito"] == "hipotecario") & (t["subproducto"] != "total"))]
    t["prod"] = t["tipo_credito"] + "|" + t["subproducto"]
    # En los meses en que una entidad figura como «s.i.», el archivo trae dos columnas con su nombre:
    # una toda «-» y otra toda «s.i.» (ninguna con tasa). Se deja una fila: tasa > «s.i.» > «-».
    key = ["periodo", "subsistema", "entidad_original", "es_promedio", "prod"]
    t = (t.assign(_r=np.where(t["tasa"].notna(), 0, np.where(t["sin_dato"] == "s.i.", 1, 2)))
         .sort_values("_r").drop_duplicates(key).drop(columns="_r"))
    if t.duplicated(["periodo", "subsistema", "id_entidad", "es_promedio", "prod"]).any():
        raise ValueError("una entidad aparece en dos columnas distintas del mismo archivo")
    return t


def load_credit() -> pd.DataFrame:
    """Saldo (miles de S/) y atrasados por (periodo, subsistema, entidad, tipo del cuadro de tasas)."""
    d = read_table(BOLETIN / "creditos-tipo-situacion.parquet")
    d = d[~d["es_total"] & (d["apertura"] != "total|total")].copy()
    d[["tipo", "sit"]] = d["apertura"].str.split("|", expand=True)
    to_rate = {m: k for k, _, _, ms in TYPES for m in ms}
    d["tipo"] = d["tipo"].map(to_rate)
    d = d.dropna(subset=["tipo"])
    d["atr"] = np.where(d["sit"] == "atrasados", d["valor"], 0.0)
    g = d.groupby(KEY + ["tipo"], as_index=False).agg(tot=("valor", "sum"), atr=("atr", "sum"))
    return g


def arr(values: pd.Series, months: list[int], a: int, b: int, dec: int):
    out = []
    for m in months[a:b + 1]:
        x = values.get(m, np.nan)
        if isinstance(x, str):
            out.append(x)
        elif pd.isna(x):
            out.append(None)
        else:
            out.append(int(round(float(x))) if dec == 0 else round(float(x), dec))
    while out and out[-1] is None:
        out.pop()
    return out


def scope_block(rates: pd.DataFrame, credit: pd.DataFrame, months: list[int]) -> dict:
    """{a: índice del primer mes, R: {producto: [tasa]}, K: {tipo: [saldo]}, M: {tipo: [mora %]}}.

    En R, None = «-» (sin operaciones) y "s" = «s.i.» (no reportó)."""
    pos = {m: i for i, m in enumerate(months)}
    present = sorted(set(rates.loc[rates["tasa"].notna() | (rates["sin_dato"] == "s.i."), "periodo"]))
    present = [m for m in present if m in pos]
    if not present:
        return {}
    a, b = pos[present[0]], pos[present[-1]]
    R = {}
    for prod, g in rates.groupby("prod"):
        v = g.set_index("periodo").apply(lambda r: "s" if r["sin_dato"] == "s.i." else r["tasa"], axis=1)
        if v.map(lambda x: isinstance(x, float) and not np.isnan(x)).sum() == 0:
            continue
        R[prod] = arr(v, months, a, b, 2)
    K, M = {}, {}
    for tipo, g in credit.groupby("tipo"):
        g = g.set_index("periodo")
        k = arr(g["tot"], months, a, b, 0)
        if any(x for x in k):
            K[tipo] = k
            M[tipo] = arr((100 * g["atr"] / g["tot"]).where(g["tot"] > 0), months, a, b, 2)
    return {"a": a, "R": R, "K": K, "M": M}


def cap_by_month(months: list[int]) -> list:
    out = []
    for m in months:
        y, mm = divmod(m, 100)
        last = (dt.date(y + (mm == 12), mm % 12 + 1, 1) - dt.timedelta(days=1)).isoformat()
        val = None
        for desde, mn, _ in CAPS:
            if desde <= last:
                val = mn
        out.append(val)
    return out


def build_data() -> dict:
    rates = load_rates()
    credit = load_credit()
    months = month_range(int(rates["periodo"].min()), int(rates["periodo"].max()))
    pos = {m: i for i, m in enumerate(months)}
    credit = credit[credit["periodo"].between(months[0], months[-1])]

    names = pd.read_csv(ENTIDADES, dtype=str).set_index("id_entidad")["nombre_actual"]
    panel = read_table(PANEL, columns=["periodo", "subsistema", "id_entidad", "nombre_entidad"])
    last_name = panel.sort_values("periodo").groupby(["subsistema", "id_entidad"])["nombre_entidad"].last()

    scopes: dict[str, dict] = {}
    avg = rates[rates["es_promedio"]]
    ent = rates[~rates["es_promedio"]]
    for sub, label, _ in SUBSYSTEMS:
        c = credit[credit["subsistema"] == sub].groupby(["periodo", "tipo"], as_index=False)[["tot", "atr"]].sum()
        scopes[sub] = {"n": label, "s": sub, **scope_block(avg[avg["subsistema"] == sub], c, months)}

    entities = []
    cred_by = {k: g for k, g in credit.groupby(["subsistema", "id_entidad"])}
    for (sub, eid), g in ent.groupby(["subsistema", "id_entidad"]):
        c = cred_by.get((sub, eid), credit.iloc[0:0])
        block = scope_block(g, c, months)
        if not block or not block["R"]:
            continue  # listada siempre con «-» (p. ej. Amérika Financiera)
        k = f"{sub}/{eid}"
        scopes[k] = {"n": last_name.get((sub, eid)) or names.get(eid, eid), "s": sub, **block}
        entities.append(k)
    by_id: dict[str, list[str]] = {}
    for k in entities:
        by_id.setdefault(k.split("/", 1)[1], []).append(k)
    for ks in by_id.values():
        if len(ks) > 1:
            for k in ks:
                scopes[k]["o"] = [x for x in ks if x != k]

    # Fecha de corte de banca y financieras (último día útil consultado) por mes.
    cut = {}
    for sub in ("banca-multiple", "empresas-financieras"):
        f = rates[rates["subsistema"] == sub].drop_duplicates("periodo").set_index("periodo")["fecha_corte"]
        cut[sub] = [None if m not in f.index else f[m].strftime("%Y-%m-%d") for m in months]

    # Último mes con promedio publicado en los cinco subsistemas.
    last_by_sub = avg[avg["tasa"].notna()].groupby("subsistema")["periodo"].max()
    first_by_sub = avg[avg["tasa"].notna()].groupby("subsistema")["periodo"].min()
    all_last = int(last_by_sub.min())

    prods = []
    for k, l, s, _ in TYPES:
        prods.append({"k": f"{k}|total", "t": k, "l": l, "s": s, "lv": 0})
        for sk, sl, ss in SUBPRODUCTS[k]:
            prods.append({"k": f"{k}|{sk}", "t": k, "l": sl, "s": ss, "lv": 1})
    return {
        "months": [month_key(m) for m in months],
        "types": [{"k": k, "l": l, "s": s} for k, l, s, _ in TYPES],
        "prods": prods,
        "subs": [{"k": k, "l": l, "s": s, "f": FORM[k], "from": month_key(int(first_by_sub[k])),
                  "to": month_key(int(last_by_sub[k]))} for k, l, s in SUBSYSTEMS],
        "cut": cut,
        "cap": cap_by_month(months),
        "capTypes": CAP_TYPES,
        "caps": [{"desde": d, "mn": v, "src": s} for d, v, s in CAPS],
        "capFrom": {k: month_key(int(d[:4] + d[5:7])) for k, d in CAP_START.items()},
        "creditTo": month_key(int(credit["periodo"].max())),
        "scopes": scopes,
        "entities": entities,
        "hasta": month_key(months[-1]),
        "allHasta": month_key(all_last),
        "examples": examples(rates, months),
        "cov": coverage(rates),
        "generado": dt.date.today().isoformat(),
    }


def examples(rates: pd.DataFrame, months: list[int]) -> dict:
    """Cifras de los ejemplos de «Cómo leer los datos», recalculadas con los datos del último mes completo."""
    avg = rates[rates["es_promedio"] & rates["tasa"].notna()]
    last = int(avg.groupby("subsistema")["periodo"].max().min())
    a = avg[avg["periodo"] == last].set_index(["subsistema", "prod"])["tasa"]
    out = {"mes": month_key(last)}
    # 1) De TEA a tasa mensual equivalente (año de 360 días, mes de 30 días) y cuota de un préstamo.
    tea = float(a[("banca-multiple", "consumo|total")])
    tem = (1 + tea / 100) ** (30 / 360) - 1
    principal, n = 1000.0, 12
    cuota = principal * tem / (1 - (1 + tem) ** -n)
    out["tea"] = {"sub": "banca-multiple", "tea": round(tea, 2), "tem": round(100 * tem, 2),
                  "simple": round(tea / 12, 2), "cuota": round(cuota, 2), "total": round(cuota * n, 2),
                  "interes": round(cuota * n - principal, 2), "bullet": round(principal * tea / 100, 2)}
    # 2) El total de un tipo no es el promedio simple de sus productos (micro en banca).
    sub = "banca-multiple"
    rows = [(sk, float(a[(sub, f"micro|{sk}")])) for sk, _, _ in SUBPRODUCTS["micro"] if (sub, f"micro|{sk}") in a.index]
    vals = [v for _, v in rows]
    out["mix"] = {"sub": sub, "total": round(float(a[(sub, "micro|total")]), 2), "n": len(vals),
                  "min": round(min(vals), 2), "max": round(max(vals), 2), "simple": round(float(np.mean(vals)), 2),
                  "minK": min(rows, key=lambda r: r[1])[0], "maxK": max(rows, key=lambda r: r[1])[0]}
    # 3) Consumo por subsistema en el mismo mes.
    out["consumo"] = {s: round(float(a[(s, "consumo|total")]), 2) for s, _, _ in SUBSYSTEMS if (s, "consumo|total") in a.index}
    # 4) ¿El «Promedio» del subsistema es el promedio simple de las entidades? Celdas con ≥ 2 entidades.
    k = ["periodo", "subsistema", "prod"]
    ent = rates[~rates["es_promedio"] & rates["tasa"].notna()].groupby(k)["tasa"].agg(["mean", "count", "min", "max"])
    chk = ent.join(avg.set_index(k)["tasa"].rename("prom"), how="inner")
    chk = chk[chk["count"] >= 2]
    out["avgCheck"] = {"n": int(len(chk)),
                       "simple": round(100 * float(((chk["mean"] - chk["prom"]).abs() <= 0.01).mean()), 1),
                       "inRange": round(100 * float(((chk["prom"] >= chk["min"] - 0.01) & (chk["prom"] <= chk["max"] + 0.01)).mean()), 1)}
    # 5) El promedio cambia con la composición: consumo de las empresas de créditos, ago → set 2024.
    ec = rates[(rates["subsistema"] == "empresas-credito") & (rates["prod"] == "consumo|total")
               & rates["periodo"].isin([202408, 202409]) & rates["tasa"].notna()]
    piv = ec.pivot_table(index="entidad_original", columns="periodo", values="tasa")
    if {202408, 202409} <= set(piv.columns) and "Promedio" in piv.index:
        ents = piv.drop(index="Promedio")
        out["ec"] = {"antes": round(float(piv.at["Promedio", 202408]), 2), "despues": round(float(piv.at["Promedio", 202409]), 2),
                     "ent": [[n, round(float(r[202408]), 2), None if pd.isna(r[202409]) else round(float(r[202409]), 2)]
                             for n, r in ents.sort_values(202408, ascending=False).iterrows()]}
    return out


def coverage(rates: pd.DataFrame) -> list[dict]:
    """Cobertura por subsistema para «Cómo leer los datos»: meses, entidades y celdas sin tasa."""
    out = []
    for sub, label, _ in SUBSYSTEMS:
        r = rates[rates["subsistema"] == sub]
        e = r[~r["es_promedio"]]
        last = int(r["periodo"].max())
        n_last = e[(e["periodo"] == last) & e["tasa"].notna()]["id_entidad"].nunique()
        out.append({"k": sub, "from": month_key(int(r["periodo"].min())), "to": month_key(last),
                    "meses": int(r["periodo"].nunique()), "ent": int(e["id_entidad"].nunique()), "entLast": int(n_last),
                    "conTasa": round(100 * float(e["tasa"].notna().mean()), 1),
                    "guion": round(100 * float((e["sin_dato"] == "-").mean()), 1),
                    "si": round(100 * float((e["sin_dato"] == "s.i.").mean()), 1)})
    return out


def summary(data: dict) -> None:
    """Cifras del último mes completo, para revisar a ojo."""
    i = data["months"].index(data["allHasta"])
    print(f"  Último mes con los 5 subsistemas: {data['allHasta']}; banca y financieras hasta {data['hasta']}")
    for s in data["subs"]:
        sc = data["scopes"][s["k"]]
        j = i - sc["a"]
        vals = []
        for t in data["types"]:
            v = sc["R"].get(f"{t['k']}|total", [])
            x = v[j] if 0 <= j < len(v) else None
            vals.append(f"{t['s']} {x if x is not None else '—'}")
        n = sum(1 for k in data["entities"] if data["scopes"][k]["s"] == s["k"]
                and any(isinstance(arr_[i - data["scopes"][k]["a"]], float | int)
                        for arr_ in data["scopes"][k]["R"].values() if 0 <= i - data["scopes"][k]["a"] < len(arr_)))
        print(f"    {s['l']:<22} ({n} entidades con tasa): " + ", ".join(vals))
    if data["cap"][i] is not None:
        print(f"  Tasa máxima BCRP (MN) vigente al cierre de {data['allHasta']}: {data['cap'][i]}%")
    print(f"  Ejemplos: {data['examples']}")


def main() -> int:
    print("Armando datos de tasas activas...")
    data = build_data()
    summary(data)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    template = TEMPLATE.read_text(encoding="utf-8")
    if PLACEHOLDER not in template:
        print(f"ERROR: la plantilla no tiene el marcador {PLACEHOLDER}")
        return 1
    html = template.replace(PLACEHOLDER, payload)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    OUT_ARTIFACT.write_text(artifact_version(html), encoding="utf-8")
    print(f"  {data['months'][0]} a {data['hasta']}, {len(data['entities'])} series de entidad, datos {len(payload) / 1e6:.1f} MB")
    print(f"  Escrito {OUT.relative_to(PROJECT_DIR)} y {OUT_ARTIFACT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
