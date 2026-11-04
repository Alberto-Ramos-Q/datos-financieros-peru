"""Construye la serie de concentración bancaria de Colombia (dic-2015 a dic-2025).

Entradas (descargadas por `descargar_colombia.py` en data/raw/internacional/colombia/):
- `cuif_bancos_AAAA12.json` (2016-2025): CUIF por entidad, SFC, datos.gov.co `mxk5-ce6w`,
  bancos (tipo 1), moneda total, valores en pesos.
- `indicadores_gerenciales_AAAA12.zip` (2015-2025): «Indicadores gerenciales NIIF» de la SFC,
  en millones de pesos. El de 2015 es la fuente de dic-2015 (el CUIF del API empieza en
  2016-01); los de 2016-2025 sirven de control cruzado con el API y para leer la
  clasificación «Bancos Públicos» (clase 2) de la SFC.

Definiciones:
- creditos (cartera bruta) = 140400 + 140800 + 141000 + 141200 + 141400 + 141600 + 141800,
  la misma que usa la SFC en el renglón «CARTERA DE CREDITOS» de sus Indicadores gerenciales
  (incluye los derechos de transferencia de cartera, con saldo solo en 2020-2021). La 140000 es
  NETA de deterioro y no se usa. La definición anterior (sin 141600/141800, la del mapeo) se
  informa en `notas` en los años en que difiere.
- depositos = 210500 + 210600 + 210700 + 210800 + 210900 + 211000 + 212000.
- Solo bancos (tipo de entidad 1), base individual (entidad vigilada, no conglomerado).
- Estatal: Banco Agrario de Colombia (código 43), único banco «público» según la SFC.

Salidas (data/processed/internacional/):
- colombia_entidades.csv
- colombia_concentracion.csv

Los controles se imprimen en pantalla; si alguno crítico falla, el script se detiene.
"""
from __future__ import annotations

import io
import json
import re
import sys
import unicodedata
import zipfile
from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_DIR / "data" / "raw" / "internacional" / "colombia"
OUT_DIR = PROJECT_DIR / "data" / "processed" / "internacional"

YEARS = range(2015, 2026)
YEARS_API = range(2016, 2026)

BASE_CREDIT_ACCOUNTS = ["140400", "140800", "141000", "141200", "141400"]  # definición del mapeo
TRANSFER_ACCOUNTS = ["141600", "141800"]          # derechos de transferencia de cartera
CREDIT_ACCOUNTS = BASE_CREDIT_ACCOUNTS + TRANSFER_ACCOUNTS  # definición final (= SFC)
IMPAIRMENT_ACCOUNTS = ["148700", "148800", "148900", "149100", "149300", "149500", "149800"]
DEPOSIT_ACCOUNTS = ["210500", "210600", "210700", "210800", "210900", "211000", "212000"]
DEPOSIT_BROAD_EXTRA = ["211600", "211800"]         # depósitos especiales, servicios de recaudo

STATE_CODES = {43}                                  # Banco Agrario de Colombia
AVAL_CODES = {1, 2, 23, 49}                         # Bogotá, Popular, Occidente, AV Villas

SOCRATA_URL = "https://www.datos.gov.co/resource/mxk5-ce6w.json"
IG_URL_2015 = ("https://www.superfinanciera.gov.co/loader.php?lServicio=Tools2&lTipo=descargas"
               "&lFuncion=descargar&idFile=1017192")
SOURCE_API = "SFC, CUIF por entidad (datos.gov.co mxk5-ce6w), corte {y}-12-31, moneda total"
SOURCE_IG = "SFC, Indicadores gerenciales NIIF dic-2015 (superfinanciera.gov.co, idFile=1017192)"

# Renglones de los Indicadores gerenciales (texto normalizado) -> concepto.
IG_ROWS = {
    "CARTERA DE CREDITOS": "creditos",
    "CARTERA DE CREDITOS Y OPERACIONES DE LEASING": "neta",
    "DETERIORO": "deterioro",
    "DETERIORO COMPONENTE CONTRACICLICO": "contraciclico",
    "DEPOSITOS EN CUENTA CORRIENTE": "210500",
    "DEPOSITOS SIMPLES": "210600",
    "CERTIFICADOS DE DEPOSITO A TERMINO": "210700",
    "DEPOSITOS DE AHORRO": "210800",
    "CUENTAS DE AHORRO ESPECIAL": "210900",
    "CERTIFICADOS DE AHORRO DE VALOR REAL": "211000",
    "DEPOSITOS ELECTRONICOS": "212000",
}

failures: list[str] = []


def check(ok: bool, message: str, critical: bool = True) -> None:
    """Imprime el resultado de un control y acumula los fallos críticos."""
    print(f"  [{'OK' if ok else ('FALLA' if critical else 'AVISO')}] {message}")
    if not ok and critical:
        failures.append(message)


def normalize(text) -> str:
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", text).strip().upper()


# --------------------------------------------------------------------------- lectura

def load_api() -> pd.DataFrame:
    rows = []
    for year in YEARS_API:
        path = RAW_DIR / f"cuif_bancos_{year}12.json"
        rows += json.loads(path.read_text(encoding="utf-8"))
    df = pd.DataFrame(rows)
    df["anio"] = df.fecha_corte.str[:4].astype(int)
    df["codigo"] = df.codigo_entidad.astype(int)
    df["valor"] = df.valor.astype(float)
    # Signo: el CUIF trae el valor absoluto y el signo aparte.
    df.loc[df.signo_valor == "-", "valor"] *= -1
    return df


def read_ig(year: int) -> tuple[pd.DataFrame, str]:
    """Devuelve (largo por banco y concepto en millones de pesos, texto del corte)."""
    path = RAW_DIR / f"indicadores_gerenciales_{year}12.zip"
    with zipfile.ZipFile(path) as zf:
        sheet = pd.read_excel(io.BytesIO(zf.read(zf.namelist()[0])), header=None)
    label_col = sheet.iloc[:20, 2].map(normalize)
    row_of = {name: label_col[label_col == name].index[0]
              for name in ("TIPO", "CLASE", "CODIGO", "NOMBRE DE LA ENTIDAD")}
    cut_text = str(sheet.iat[row_of["NOMBRE DE LA ENTIDAD"] + 1, 2])
    labels = []
    for i in range(sheet.shape[0]):
        cells = [sheet.iat[i, k] for k in (2, 1, 0)]
        labels.append(next((normalize(c) for c in cells if pd.notna(c) and normalize(c)), ""))
    first_row = {}
    for i, lab in enumerate(labels):
        if lab in IG_ROWS and lab not in first_row and i > row_of["NOMBRE DE LA ENTIDAD"]:
            first_row[lab] = i
    missing = set(IG_ROWS) - set(first_row)
    if missing:
        raise ValueError(f"Indicadores gerenciales {year}: faltan renglones {missing}")
    out = []
    for j in range(3, sheet.shape[1]):
        tipo = str(sheet.iat[row_of["TIPO"], j]).strip()
        code = sheet.iat[row_of["CODIGO"], j]
        if tipo not in ("1", "1.0") or pd.isna(code) or float(code) <= 0:
            continue  # solo bancos individuales (no totales por grupo)
        for lab, concept in IG_ROWS.items():
            value = sheet.iat[first_row[lab], j]
            out.append({"anio": year, "codigo": int(float(code)),
                        "nombre_ig": str(sheet.iat[row_of["NOMBRE DE LA ENTIDAD"], j]).strip(),
                        "clase": str(sheet.iat[row_of["CLASE"], j]).strip(),
                        "concepto": concept, "mm": float(value) if pd.notna(value) else 0.0})
    # Columna «Total Bancos» para control de sumas.
    hdr = sheet.iloc[row_of["NOMBRE DE LA ENTIDAD"], :].map(normalize)
    total_col = hdr[hdr == "TOTAL BANCOS"].index[0]
    for lab, concept in IG_ROWS.items():
        value = sheet.iat[first_row[lab], total_col]
        out.append({"anio": year, "codigo": 0, "nombre_ig": "TOTAL BANCOS", "clase": "",
                    "concepto": concept, "mm": float(value) if pd.notna(value) else 0.0})
    return pd.DataFrame(out), cut_text


# --------------------------------------------------------------------------- métricas

def concentration(values: pd.Series) -> dict:
    """n, CR4, CR5 (en %) e IHH (0 a 10 000) sobre las entidades con valor positivo."""
    s = values[values > 0].sort_values(ascending=False)
    shares = 100 * s / s.sum()
    return {"n": int(len(s)), "cr4": round(shares.head(4).sum(), 1),
            "cr5": round(shares.head(5).sum(), 1), "ihh": int(round((shares ** 2).sum()))}


def shares_of(values: pd.Series) -> pd.Series:
    s = values[values > 0]
    return 100 * s / s.sum()


def main() -> int:
    print("== Lectura")
    api = load_api()
    ig = {y: read_ig(y) for y in YEARS}
    ig_long = pd.concat([v[0] for v in ig.values()], ignore_index=True)
    print(f"  CUIF: {len(api)} filas; Indicadores gerenciales: {len(ig)} archivos")

    print("== Controles de la extracción del API")
    check(set(api.tipo_entidad) == {"1"} and set(api.moneda) == {"0"},
          "solo tipo de entidad 1 y moneda 0 (total)")
    check(sorted(api.anio.unique()) == list(YEARS_API), "hay datos en los 10 diciembres 2016-2025")
    check(set(api.fecha_corte.str[5:10]) == {"12-31"}, "todos los cortes son 31 de diciembre")
    dups = api.duplicated(["anio", "codigo", "cuenta"]).sum()
    check(dups == 0, f"sin filas duplicadas (año, entidad, cuenta): {dups}")
    names_per_code = api.groupby(["anio", "codigo"]).nombre_entidad.nunique().max()
    check(names_per_code == 1, "un solo nombre por código y año")
    check((api.signo_valor == "+").all(), "todas las cuentas usadas vienen con signo +", critical=False)

    # ---- tabla banco-año desde el API
    wide = api.pivot_table(index=["anio", "codigo"], columns="cuenta", values="valor",
                           aggfunc="sum").fillna(0.0)
    for acc in CREDIT_ACCOUNTS + IMPAIRMENT_ACCOUNTS + DEPOSIT_ACCOUNTS + \
            DEPOSIT_BROAD_EXTRA + ["140000"]:
        if acc not in wide.columns:
            wide[acc] = 0.0
    bank = pd.DataFrame(index=wide.index)
    bank["creditos"] = wide[CREDIT_ACCOUNTS].sum(axis=1)
    bank["creditos_mapeo"] = wide[BASE_CREDIT_ACCOUNTS].sum(axis=1)
    bank["transferencia"] = wide[TRANSFER_ACCOUNTS].sum(axis=1)
    bank["deterioro"] = wide[IMPAIRMENT_ACCOUNTS].sum(axis=1)
    bank["neta"] = wide["140000"]
    bank["depositos"] = wide[DEPOSIT_ACCOUNTS].sum(axis=1)
    bank["depositos_amplia"] = bank.depositos + wide[DEPOSIT_BROAD_EXTRA].sum(axis=1)
    bank = bank.reset_index()
    latest_name = (api.sort_values("anio").groupby("codigo").nombre_entidad.last())
    bank["entidad"] = bank.codigo.map(latest_name)

    print("== Control 1: reconstrucción de dic-2025 del mapeo (miles de millones de COP)")
    b25 = bank[bank.anio == 2025]
    tot = {k: b25[k].sum() / 1e9 for k in ("creditos", "deterioro", "neta")}
    print(f"  cartera bruta {tot['creditos']:,.1f} · deterioro {tot['deterioro']:,.1f} · "
          f"140000 {tot['neta']:,.1f} · bancos {len(b25)}")
    check(round(tot["creditos"]) == 729161, "cartera bruta = 729 161")
    # El mapeo da 39 207 y 689 954: son redondeos de 39 207,5 y 689 953,3 (diferencia < 1).
    check(abs(tot["deterioro"] - 39207) < 1, "deterioro (148700 a 149800) = 39 207 (± 1 por redondeo)")
    check(abs(tot["creditos"] - tot["deterioro"] - tot["neta"]) < 0.5, "bruta - deterioro = 140000")

    print("== Control 2: bruta - deterioro = 140000, por banco y año (tolerancia 1 millón de pesos)")
    gap = bank.creditos - bank.deterioro - bank.neta
    gap_old = bank.creditos_mapeo - bank.deterioro - bank.neta
    for year in YEARS_API:
        m = bank.anio == year
        exact = int((gap[m].abs() < 1e6).sum())
        exact_old = int((gap_old[m].abs() < 1e6).sum())
        print(f"  {year}: {exact}/{int(m.sum())} bancos cuadran con la definición final; "
              f"{exact_old}/{int(m.sum())} con la del mapeo (sin 141600+141800); "
              f"141600+141800 = {bank.transferencia[m].sum() / 1e9:,.1f} mil millones")
    check((gap.abs() < 1e6).all(), "con la definición final cuadran todos los bancos en los 10 años")

    print("== Control 3: Indicadores gerenciales (SFC) frente al API, 2016-2025 (millones)")
    ig_w = ig_long[ig_long.codigo > 0].pivot_table(index=["anio", "codigo"], columns="concepto",
                                                    values="mm", aggfunc="sum")
    ig_w["depositos"] = ig_w[DEPOSIT_ACCOUNTS].sum(axis=1)
    ig_api_years = ig_w[ig_w.index.get_level_values("anio") >= 2016]
    cmp = bank.set_index(["anio", "codigo"]).join(ig_api_years, rsuffix="_ig", how="outer")
    only_api = cmp[cmp.depositos_ig.isna()].index.tolist()
    only_ig = cmp[cmp.creditos.isna()].index.tolist()
    print(f"  bancos solo en el API: {only_api}; solo en los Indicadores: {only_ig}")
    both = cmp.dropna(subset=["creditos", "depositos_ig"])
    dep_diff = (both.depositos / 1e6 - both.depositos_ig).abs()
    check((dep_diff < 0.5).all(), f"depósitos: {len(both)} banco-año, diferencia máxima "
                                  f"{dep_diff.max():.3f} millones")
    cred_diff = (both.creditos / 1e6 - both.creditos_ig).abs()
    check((cred_diff < 0.5).all(), "cartera bruta = renglón «CARTERA DE CREDITOS» del IG en "
                                   f"{len(both)} banco-año, diferencia máxima "
                                   f"{cred_diff.max():.3f} millones")
    estat = ig_long[(ig_long.codigo > 0)].drop_duplicates(["anio", "codigo"])
    public = estat[estat.clase == "2"].groupby("anio").codigo.apply(set)
    check(all(public.get(y, set()) == STATE_CODES for y in YEARS),
          "en los 11 Indicadores gerenciales, el único banco de clase 2 (público) es el código 43")

    print("== Control 4: dic-2015 desde los Indicadores gerenciales")
    i15 = ig_w.loc[2015].copy()
    net_gap = (i15.creditos - i15.deterioro - i15.contraciclico - i15.neta).abs()
    check((net_gap < 0.5).all(), f"bruta - deterioro - contracíclico = neta en los {len(i15)} bancos")
    tot15 = ig_long[(ig_long.anio == 2015) & (ig_long.codigo == 0)].set_index("concepto").mm
    sum_gap_c = abs(i15.creditos.sum() - tot15["creditos"])
    sum_gap_d = abs(i15[DEPOSIT_ACCOUNTS].sum(axis=1).sum() - tot15[DEPOSIT_ACCOUNTS].sum())
    check(sum_gap_c < 1 and sum_gap_d < 1, "la suma de los bancos = columna «Total Bancos» "
                                           f"(dif. {sum_gap_c:.2f} y {sum_gap_d:.2f} millones)")
    print(f"  corte del archivo: {ig[2015][1]}")

    # ---- tabla larga por entidad
    b15 = i15.reset_index()[["codigo", "creditos", "depositos"]]
    b15["anio"] = 2015
    b15["entidad"] = b15.codigo.map(latest_name)
    check(b15.entidad.notna().all(), "todos los códigos de dic-2015 existen en el API (nombre estable)")
    b15["unidad"], b15["fuente_url"] = "millones_cop", IG_URL_2015
    b_api = bank[["anio", "codigo", "entidad", "creditos", "depositos"]].copy()
    b_api["unidad"], b_api["fuente_url"] = "pesos_cop", SOCRATA_URL
    panel = pd.concat([b15, b_api], ignore_index=True)
    panel["estatal"] = panel.codigo.isin(STATE_CODES)

    print("== Control 5: entidades por año, duplicados y años vacíos")
    dups = panel.duplicated(["anio", "codigo"]).sum() + panel.duplicated(["anio", "entidad"]).sum()
    check(dups == 0, "ningún banco repetido en un mismo año (por código ni por nombre)")
    counts = panel.groupby("anio").codigo.nunique()
    check(sorted(counts.index) == list(YEARS), "los 11 años tienen datos")
    print("  bancos por año: " + ", ".join(f"{y}: {n}" for y, n in counts.items()))

    long = panel.melt(id_vars=["anio", "codigo", "entidad", "estatal", "unidad", "fuente_url"],
                      value_vars=["creditos", "depositos"], var_name="variable", value_name="valor")
    ent = pd.DataFrame({"pais": "COL", "anio": long.anio, "mes": 12, "entidad": long.entidad,
                        "estatal": long.estatal, "variable": long.variable,
                        "valor": long.valor.round(2), "unidad": long.unidad,
                        "base": "individual", "fuente_url": long.fuente_url})
    ent = ent.sort_values(["anio", "variable", "valor"], ascending=[True, True, False])

    # ---- concentración
    rows = []
    for year in YEARS:
        p = panel[panel.anio == year].set_index("codigo")
        source = SOURCE_IG if year == 2015 else SOURCE_API.format(y=year)
        extra = bank[bank.anio == year].set_index("codigo") if year >= 2016 else None
        for variable in ("creditos", "depositos"):
            for variante in ("con_estatales", "sin_estatales"):
                sub = p if variante == "con_estatales" else p[~p.index.isin(STATE_CODES)]
                stats = concentration(sub[variable])
                peso = (round(shares_of(sub[variable])[lambda s: s.index.isin(STATE_CODES)].sum(), 1)
                        if variante == "con_estatales" else None)
                # Informativo: Grupo Aval agrupado como una sola entidad.
                grouped = sub[variable].groupby(
                    sub.index.map(lambda c: "AVAL" if c in AVAL_CODES else c)).sum()
                aval = concentration(grouped)
                notes = [f"Informativo, Grupo Aval agrupado (Bogotá+Occidente+Popular+AV Villas): "
                         f"CR4 {aval['cr4']}, IHH {aval['ihh']}"]
                if year == 2015:
                    notes.append("dic-2015 desde Indicadores gerenciales (millones de pesos, cifras "
                                 "con corte a 19-feb-2016); el CUIF de datos.gov.co empieza en 2016-01")
                if extra is not None:
                    alt_sub = extra if variante == "con_estatales" else \
                        extra[~extra.index.isin(STATE_CODES)]
                    if variable == "creditos" and alt_sub.transferencia.sum() > 0:
                        alt = concentration(alt_sub.creditos_mapeo)
                        notes.append("Incluye 141600+141800 derechos de transferencia de cartera "
                                     f"({alt_sub.transferencia.sum() / 1e9:,.0f} mil millones); "
                                     "sin ellos (definición del mapeo) "
                                     f"CR4 {alt['cr4']}, IHH {alt['ihh']}")
                    if variable == "depositos":
                        alt = concentration(alt_sub.depositos_amplia)
                        notes.append("Sensibilidad: + 211600 depósitos especiales y 211800 recaudo: "
                                     f"CR4 {alt['cr4']}, IHH {alt['ihh']}")
                notes.append("Estatal: Banco Agrario de Colombia" if variante == "con_estatales"
                             else "Sin Banco Agrario")
                rows.append({"pais": "COL", "anio": year, "variable": variable, "variante": variante,
                             "base": "individual", **stats, "peso_estatal": peso,
                             "fuente": source, "notas": "; ".join(notes)})
    conc = pd.DataFrame(rows)

    print("== Control 6: concentración dic-2025 frente al mapeo")
    expected = {("creditos", "con_estatales"): (67.3, 74.3, 1416, 3.3),
                ("creditos", "sin_estatales"): (69.6, 76.8, 1503, None),
                ("depositos", "con_estatales"): (66.0, 73.3, 1379, 1.8),
                ("depositos", "sin_estatales"): (67.2, 74.6, 1426, None)}
    for (variable, variante), (cr4, cr5, ihh, peso) in expected.items():
        r = conc[(conc.anio == 2025) & (conc.variable == variable) & (conc.variante == variante)].iloc[0]
        got_peso = None if pd.isna(r.peso_estatal) else r.peso_estatal
        check((r.cr4, r.cr5, r.ihh, got_peso) == (cr4, cr5, ihh, peso),
              f"{variable}/{variante}: CR4 {r.cr4} CR5 {r.cr5} IHH {r.ihh} peso {got_peso} "
              f"(mapeo {cr4} / {cr5} / {ihh} / {peso})")

    if failures:
        print(f"\nSe detiene: {len(failures)} control(es) crítico(s) fallaron:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ent.to_csv(OUT_DIR / "colombia_entidades.csv", index=False, encoding="utf-8")
    conc.to_csv(OUT_DIR / "colombia_concentracion.csv", index=False, encoding="utf-8")
    print(f"\nEscrito: {len(ent)} filas en colombia_entidades.csv y {len(conc)} en "
          "colombia_concentracion.csv")
    print(conc[["anio", "variable", "variante", "n", "cr4", "cr5", "ihh", "peso_estatal"]]
          .to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
