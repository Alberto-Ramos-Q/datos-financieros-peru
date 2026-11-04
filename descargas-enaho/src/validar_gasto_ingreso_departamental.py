"""Valida el gasto y el ingreso per cápita por departamento (2016-2025) contra el INEI.

Fuente: INEI, «Perú: Evolución de la pobreza monetaria 2016-2025. Informe técnico»
(docs/enaho/2025/7_Informe_tecnico_de_pobreza/07_Informe_tecnico_de_Pobreza_Monetaria_2025.pdf).
Cifras transcritas en config/gasto_ingreso_oficial_departamental_2016_2025.csv (26 unidades del
INEI × 10 años por cuadro):
- Cuadro I.1  p.176  gasto real per cápita mensual (S/ 2025, precios de Lima Met.); CV 2025.
- Cuadro I.8  p.191  gasto nominal per cápita mensual (S/ corrientes); CV 2025.
- Cuadro I.15 p.206  ingreso real per cápita mensual (S/ 2025, precios de Lima Met.); CV 2025.
- Cuadro I.19 p.218  ingreso «nominal» per cápita mensual; CV 2025.
- Cuadro I.21 pp.221-224  el mismo ingreso «nominal» con error estándar e IC 95 % de cada año.

Calculado:
- gasto_real_pc, gasto_nominal_pc, ingreso_real_pc: data/processed/pobreza/pobreza_ambitos.parquet
  (ambito_tipo == "departamento_inei"), generado por src/pobreza_departamental.py.
- Ingreso «nominal» de I.19/I.21 (no está en el Parquet): inghog1d / (12·mieperho·i00), es decir,
  a soles de 2025 pero sin deflactor espacial ld (docs/validacion_cifras_oficiales.md §5 punto 3).
  Se calcula aquí con load_year() de pobreza_departamental.py (peso floor(factor07·mieperho + 0,5),
  deflactores de data/processed/deflactores/) y survey_ratio() con varianza sobre la submuestra.

Tolerancias (cifras oficiales redondeadas al sol y el CV a un decimal): soles ≤ 0,5;
CV ≤ 0,05 puntos; error estándar e IC (redondeados al sol) ≤ 0,5.

Uso (desde la raíz de descargas-enaho, después de correr pobreza_departamental.py):
    python src/validar_gasto_ingreso_departamental.py
No escribe archivos: solo imprime. Informe: docs/validacion_pobreza_departamental.md §7.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from construir_deflactores import build_dominio_a  # noqa: E402
from pobreza_departamental import inei_unit_mask, inei_units, load_year  # noqa: E402
from validar_cifras_oficiales import (  # noqa: E402
    YEARS, Z_95, load_price_coefficients, load_spatial_deflator, survey_ratio)

ROOT = Path(__file__).resolve().parents[1]
LONG_FILE = ROOT / "data" / "processed" / "pobreza" / "pobreza_ambitos.parquet"
OFFICIAL_FILE = ROOT / "config" / "gasto_ingreso_oficial_departamental_2016_2025.csv"
TOL_SOLES, TOL_CV = 0.5, 0.05
EPS = 1e-9

# (cuadro, indicador) en el orden del informe
TABLES = [("Cuadro I.1", "gasto_real_pc"), ("Cuadro I.8", "gasto_nominal_pc"),
          ("Cuadro I.15", "ingreso_real_pc"), ("Cuadro I.19", "ingreso_i19_pc"),
          ("Cuadro I.21", "ingreso_i19_pc")]


def summary(label: str, diffs: pd.Series, tol: float) -> tuple[int, int]:
    diffs = diffs.dropna()
    ok = int((diffs.abs() <= tol + EPS).sum())
    print(f"  {label:<52} {ok:>4}/{len(diffs):<4} dentro de ±{tol}   máx |dif| = "
          f"{diffs.abs().max():.3f}")
    return ok, len(diffs)


def compute_income_i19() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Ingreso per cápita de los Cuadros I.19/I.21: inghog1d / (12·mieperho·i00), sin ld.

    Devuelve (estimaciones, diagnóstico). El diagnóstico trae, por año y unidad:
    - el EE del mismo ingreso con otras definiciones de la varianza (para el Cuadro I.21);
    - variantes de punto que muestran qué pasa si se usa la definición equivocada: ingreso con
      ld (= ingreso real), ingreso nominal puro (sin i00) y gasto real con i00 en vez de i0k.
    """
    coefficients, ld_table = load_price_coefficients(), load_spatial_deflator()
    rows, diag = [], []
    for year in YEARS:
        df = load_year(year, coefficients, ld_table)
        people = 12.0 * df["mieperho"]
        y = df["inghog1d"] / (people * df["i00"])
        variants = {"ingreso_con_ld": df["inghog1d"] / (people * df["ld"] * df["i00"]),
                    "ingreso_nominal_puro": df["inghog1d"] / people,
                    "gasto_real_i00": df["gashog2d"] / (people * df["ld"] * df["i00"])}
        dominio_a = build_dominio_a(df)
        strata = {"subpop_estrato": df["estrato"],
                  "subpop_dominio_x_estrato": df["dominio"] * 10 + df["estrato"],
                  "subpop_dominioA_x_estrato": dominio_a * 10 + df["estrato"]}
        w, psu = df["facpob07"], df["conglome"]
        for code in inei_units():
            mask = inei_unit_mask(df, code)
            est, se = survey_ratio(y, df["one"], w, df["estrato"], psu, mask, subset=True)
            rows.append(dict(anio=year, ambito_id=code, indicador="ingreso_i19_pc", valor=est,
                             ee=se, ic_inf=est - Z_95 * se, ic_sup=est + Z_95 * se,
                             cv=100 * se / est))
            d = dict(anio=year, ambito_id=code, ee_submuestra_estrato=se)
            for name, s in strata.items():
                d[f"ee_{name}"] = survey_ratio(y, df["one"], w, s, psu, mask)[1]
            for name, v in variants.items():
                d[name] = float((w * v)[mask].sum() / w[mask].sum())
            diag.append(d)
    return pd.DataFrame(rows), pd.DataFrame(diag)


def diagnostics(official: pd.DataFrame, diag: pd.DataFrame) -> None:
    """Causas de lo que no cuadra y sensibilidad a las trampas conocidas."""
    off = {c: official[official["cuadro"] == c].set_index(["anio", "ambito_id"])
           for c in ("Cuadro I.1", "Cuadro I.15", "Cuadro I.19", "Cuadro I.21")}
    d = diag.set_index(["anio", "ambito_id"])

    print("\nDiagnóstico A — EE del Cuadro I.21 con otras definiciones de la varianza "
          "(PSU = conglome; oficial vs calculado)")
    se_off = off["Cuadro I.21"]["ee"]
    for col in [c for c in d.columns if c.startswith("ee_")]:
        dif = d[col] - se_off
        print(f"  {col[3:]:<28} ±0,5: {int((dif.abs() <= TOL_SOLES + EPS).sum()):>3}/260  "
              f"±1: {int((dif.abs() <= 1 + EPS).sum()):>3}/260  EE oficial/calculado medio "
              f"{(se_off / d[col]).mean():.3f}  máx |dif| {dif.abs().max():.2f}")

    print("\nDiagnóstico B — ¿el EE 2025 del I.21 es coherente con el CV 2025 del I.19 "
          "(mismo informe)?")
    i19 = off["Cuadro I.19"].xs(2025, level=0)
    i21 = off["Cuadro I.21"].xs(2025, level=0)
    implied = 100 * i21["ee"] / i21["valor"]
    slack = 0.05 + 100 * 0.5 / i21["valor"]  # redondeo del CV (0,05) y del EE (0,5 soles)
    bad = (implied - i19["cv"]).abs() > slack + EPS
    print(f"  CV implícito en el I.21 (EE/valor) incompatible con el CV impreso en el I.19, aun "
          f"con redondeo: {int(bad.sum())}/26")
    for code in bad[bad].index:
        print(f"    {code:<5} {inei_units()[code]:<34} CV I.19 {i19.at[code, 'cv']:.1f}   "
              f"EE I.21 {i21.at[code, 'ee']:.0f} → CV {implied[code]:.2f}   EE que implica el "
              f"CV del I.19: {i19.at[code, 'cv'] * i19.at[code, 'valor'] / 100:.1f}")

    print("\nDiagnóstico C — sensibilidad: definiciones equivocadas, ¿cuántas cifras cuadrarían "
          "(±0,5)?")
    checks = [("I.19 con ld (= ingreso real)", "ingreso_con_ld", "Cuadro I.19"),
              ("I.19 nominal puro inghog1d/(12·mieperho)", "ingreso_nominal_puro", "Cuadro I.19"),
              ("I.1 con i00 sobre gashog2d (no por grupo)", "gasto_real_i00", "Cuadro I.1")]
    for label, col, cuadro in checks:
        dif = d[col] - off[cuadro]["valor"]
        print(f"  {label:<44} {int((dif.abs() <= TOL_SOLES + EPS).sum()):>3}/260   "
              f"máx |dif| {dif.abs().max():7.1f}   dif media {dif.mean():+7.1f}")


def show_worst(m: pd.DataFrame, col: str, n: int = 3) -> None:
    worst = m.reindex(m[f"dif_{col}"].abs().sort_values(ascending=False).index).head(n)
    for r in worst.itertuples():
        off, calc = getattr(r, f"{col}_oficial"), getattr(r, col)
        print(f"      {r.anio} {r.ambito_id:<5} {inei_units()[r.ambito_id]:<34} oficial "
              f"{off:8.1f}  calculado {calc:9.2f}  dif {getattr(r, f'dif_{col}'):+.2f}")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    official = pd.read_csv(OFFICIAL_FILE, dtype={"ambito_id": str})
    long = pd.read_parquet(LONG_FILE)
    calc = long[long["ambito_tipo"] == "departamento_inei"][
        ["anio", "ambito_id", "indicador", "valor", "ee", "ic_inf", "ic_sup", "cv"]]
    print("Calculando el ingreso de los Cuadros I.19/I.21 (inghog1d / (12·mieperho·i00)) ...")
    income_i19, diag = compute_income_i19()
    calc = pd.concat([calc, income_i19], ignore_index=True)

    totals, by_indicator = [], {}
    for cuadro, indicator in TABLES:
        off = official[official["cuadro"] == cuadro]
        page = "-".join(str(p) for p in sorted({off["pagina"].min(), off["pagina"].max()}))
        m = off.merge(calc, on=["anio", "ambito_id", "indicador"], suffixes=("_oficial", ""),
                      how="left")
        if m["valor"].isna().any():
            print(f"  FALTAN años/unidades para {cuadro}: correr pobreza_departamental.py 2016 2025")
            return 1
        print(f"\n{cuadro} p.{page} — {indicator} ({len(m)} cifras: 26 unidades × 10 años)")
        for col in ("valor", "ee", "ic_inf", "ic_sup", "cv"):
            m[f"dif_{col}"] = m[col] - m[f"{col}_oficial"]
        res = summary("Punto 2016-2025", m["dif_valor"], TOL_SOLES)
        totals.append(res)
        by_indicator.setdefault(cuadro, []).append(res + (m["dif_valor"].abs().max(),))
        show_worst(m, "valor")
        if m["cv_oficial"].notna().any():
            totals.append(summary("CV 2025", m["dif_cv"], TOL_CV))
            m25 = m[m["anio"] == 2025]
            print(f"    (CV con ±0,1: {(m25['dif_cv'].abs() <= 0.1 + EPS).sum()}/26; marca "
                  f"«referencial» (CV > 15) igual en "
                  f"{((m25['cv'] > 15) == (m25['cv_oficial'] > 15)).sum()}/26)")
        if m["ee_oficial"].notna().any():
            totals.append(summary("Error estándar 2016-2025", m["dif_ee"], TOL_SOLES))
            ci = pd.concat([m["dif_ic_inf"], m["dif_ic_sup"]])
            totals.append(summary("IC 95 % 2016-2025 (límites)", ci, TOL_SOLES))
            print(f"    (EE con ±1: {(m['dif_ee'].abs() <= 1 + EPS).sum()}/260; IC con ±1: "
                  f"{(ci.abs() <= 1 + EPS).sum()}/520)")
            show_worst(m, "ee")

    # Controles de consistencia interna del informe ----------------------------------------
    print("\nControles internos de las cifras oficiales")
    i19 = official[official["cuadro"] == "Cuadro I.19"].set_index(["anio", "ambito_id"])["valor"]
    i21 = official[official["cuadro"] == "Cuadro I.21"].set_index(["anio", "ambito_id"])["valor"]
    print(f"  I.21 repite el punto de I.19: {(i19 == i21.reindex(i19.index)).sum()}/{len(i19)}")
    i15 = official[official["cuadro"] == "Cuadro I.15"].set_index(["anio", "ambito_id"])["valor"]
    for code in ("15LM", "07"):  # ld = 1 en Lima Met. y Callao: real e I.19 deben coincidir
        same = (i15.xs(code, level=1) == i19.xs(code, level=1)).sum()
        print(f"  {code}: I.15 (con ld) = I.19 (sin ld) en {same}/10 años (ld = 1 en Lima Met.)")

    diagnostics(official, diag)

    ok, n = map(sum, zip(*totals))
    print(f"\nTOTAL: {ok}/{n} comparaciones dentro de tolerancia")
    print("Por cuadro (punto): " + " · ".join(
        f"{c} {r[0][0]}/{r[0][1]} (máx {r[0][2]:.2f})" for c, r in by_indicator.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
