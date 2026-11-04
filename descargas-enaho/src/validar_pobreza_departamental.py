"""Valida data/processed/pobreza/ (src/pobreza_departamental.py) contra el INEI, 2016-2025.

Fuente: INEI, «Perú: Evolución de la pobreza monetaria 2016-2025. Informe técnico»
(docs/enaho/2025/7_Informe_tecnico_de_pobreza/07_Informe_tecnico_de_Pobreza_Monetaria_2025.pdf).
Cifras transcritas en config/:
- pobreza_oficial_departamental_2016_2025.csv   Cuadro III.1 p.232 (26 unidades × 10 años;
  IC 95 % y CV solo 2025).
- grupos_departamentos_oficial_2016_2025.csv    Cuadros 4.2 (p.76-77) y 4.4 (p.81-82): grupos de
  departamentos con pobreza total / extrema estadísticamente semejante y el IC 95 % de cada grupo.
Además repite, con las salidas de pobreza_departamental.py, las cifras de nacional, área, región y
dominio que ya valida src/validar_cifras_oficiales.py (prueba de que los ámbitos están bien armados).

Tolerancias (las cifras oficiales están redondeadas a 1 decimal): punto ≤ 0,05 pp; límites de IC
≤ 0,06 pp; CV ≤ 0,05 puntos; gasto/ingreso ≤ 0,5 soles.

Uso (desde la raíz de descargas-enaho, después de correr pobreza_departamental.py):
    python src/validar_pobreza_departamental.py
No escribe archivos: solo imprime. Informe: docs/validacion_pobreza_departamental.md
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validar_cifras_oficiales import OFFICIAL_SERIES, YEARS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "processed" / "pobreza"
OFFICIAL_DEP = ROOT / "config" / "pobreza_oficial_departamental_2016_2025.csv"
OFFICIAL_GROUPS = ROOT / "config" / "grupos_departamentos_oficial_2016_2025.csv"
TOL_POINT, TOL_CI, TOL_CV, TOL_SOLES = 0.05, 0.06, 0.05, 0.5
EPS = 1e-9

# ámbito de validar_cifras_oficiales.py -> (ambito_tipo, ambito_id) en pobreza_ambitos
AREA_MAP = {
    "nacional": ("nacional", "PE"), "urbana": ("area", "urbana"), "rural": ("area", "rural"),
    "lima_metropolitana": ("dominio_inei", "lima_metropolitana_callao"),
    "resto_urbano": ("ambito_geografico", "resto_urbano"),
    "costa": ("region_natural", "costa"), "sierra": ("region_natural", "sierra"),
    "selva": ("region_natural", "selva"),
    **{f"{r}_{a}": ("dominio_inei", f"{r}_{a}") for r in ("costa", "sierra", "selva")
       for a in ("urbana", "rural")},
}


def summary(label: str, diffs: pd.Series, tol: float) -> tuple[int, int]:
    ok = int((diffs.abs() <= tol + EPS).sum())
    print(f"  {label:<58} {ok:>4}/{len(diffs):<4} dentro de ±{tol}   máx |dif| = "
          f"{diffs.abs().max():.3f}")
    return ok, len(diffs)


def rand_index(a: dict, b: dict) -> float:
    pairs = list(itertools.combinations(sorted(set(a) & set(b)), 2))
    return float(np.mean([(a[x] == a[y]) == (b[x] == b[y]) for x, y in pairs]))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    long = pd.read_parquet(OUT_DIR / "pobreza_ambitos.parquet")
    groups = pd.read_parquet(OUT_DIR / "grupos_departamentos.parquet")
    official = pd.read_csv(OFFICIAL_DEP, dtype={"ambito_id": str})
    off_groups = pd.read_csv(OFFICIAL_GROUPS, dtype={"ambito_ids": str})
    totals = []

    # 1) Cuadro III.1: pobreza total por departamento -------------------------------------
    print("\n1) Cuadro III.1 p.232 — pobreza total por departamento (26 unidades INEI)")
    calc = long[(long["ambito_tipo"] == "departamento_inei")
                & (long["indicador"] == "pobreza_total")]
    m = official.merge(calc, on=["anio", "ambito_id"], suffixes=("_oficial", ""), how="left")
    if m["valor"].isna().any():
        print("  FALTAN años/unidades en pobreza_ambitos: correr pobreza_departamental.py 2016 2025")
        return 1
    m["dif"] = m["valor"] - m["valor_oficial"]
    totals.append(summary("Incidencia 2016-2025 (punto)", m["dif"], TOL_POINT))
    m25 = m[m["anio"] == 2025]
    ci = pd.concat([m25["ic_inf"] - m25["ic_inf_oficial"], m25["ic_sup"] - m25["ic_sup_oficial"]])
    totals.append(summary("IC 95 % 2025 (límites)", ci, TOL_CI))
    totals.append(summary("CV 2025", m25["cv"] - m25["cv_oficial"], TOL_CV))
    print(f"  (con ±0,1: IC {(ci.abs() <= 0.1 + EPS).sum()}/52, "
          f"CV {((m25['cv'] - m25['cv_oficial']).abs() <= 0.1 + EPS).sum()}/26; "
          f"misma marca «referencial» (CV > 15) en "
          f"{((m25['cv'] > 15) == (m25['cv_oficial'] > 15)).sum()}/26)")
    worst = m.reindex(m["dif"].abs().sort_values(ascending=False).index).head(5)
    print("  Mayores diferencias en el punto:")
    for r in worst.itertuples():
        print(f"    {r.anio} {r.ambito_oficial:<26} oficial {r.valor_oficial:5.1f}  "
              f"calculado {r.valor:6.2f}  dif {r.dif:+.3f}")
    print("  Precisión 2025 por unidad (oficial / calculado):")
    for r in m25.sort_values("ambito_id").itertuples():
        print(f"    {r.ambito_oficial:<26} IC {r.ic_inf_oficial:4.1f}-{r.ic_sup_oficial:4.1f} / "
              f"{r.ic_inf:5.2f}-{r.ic_sup:5.2f}   CV {r.cv_oficial:4.1f} / {r.cv:5.2f}")

    # 2) Cuadros 4.2 y 4.4: IC de los grupos oficiales -------------------------------------
    print("\n2) Cuadros 4.2 y 4.4 — IC 95 % de los grupos oficiales (pobreza del conjunto)")
    off_groups["key"] = off_groups["ambito_ids"].str.split(";").map(lambda x: ";".join(sorted(x)))
    g = groups[groups["fuente_grupo"] == "oficial"]
    mg = off_groups.merge(g, left_on=["indicador", "anio", "key"],
                          right_on=["indicador", "anio", "ambito_ids"], suffixes=("_oficial", ""),
                          how="left")
    for indicator in ("pobreza_total", "pobreza_extrema"):
        x = mg[mg["indicador"] == indicator]
        diffs = pd.concat([x["ic_inf"] - x["ic_inf_oficial"], x["ic_sup"] - x["ic_sup_oficial"]])
        totals.append(summary(f"{indicator}: límites del IC de {len(x)} grupos", diffs, TOL_CI))
    bad = mg[((mg["ic_inf"] - mg["ic_inf_oficial"]).abs() > TOL_CI + EPS)
             | ((mg["ic_sup"] - mg["ic_sup_oficial"]).abs() > TOL_CI + EPS)]
    for r in bad.itertuples():
        print(f"    fuera: {r.indicador} {r.anio} grupo {r.grupo_oficial}: oficial "
              f"{r.ic_inf_oficial}-{r.ic_sup_oficial}, calculado {r.ic_inf:.2f}-{r.ic_sup:.2f}")
    print(f"  Pares dentro de un mismo grupo oficial con |t| ≥ 1,96: "
          f"{int((mg['t_max_interno'] >= 1.96).sum())} de {len(mg)} grupos tienen al menos uno "
          f"(máx |t| = {mg.loc[np.isfinite(mg['t_max_interno']), 't_max_interno'].max():.1f})")

    # 3) Grupos calculados vs oficiales ----------------------------------------------------
    print("\n3) Grupos calculados (partición óptima, k ≤ 5) vs oficiales")
    for indicator in ("pobreza_total", "pobreza_extrema"):
        rands, same_partition, same_label, n_units = [], 0, 0, 0
        line = []
        for year in YEARS:
            o = off_groups[(off_groups["indicador"] == indicator) & (off_groups["anio"] == year)]
            c = groups[(groups["indicador"] == indicator) & (groups["anio"] == year)
                       & (groups["fuente_grupo"] == "calculado")]
            om = {u: gr for gr, ids in zip(o["grupo"], o["ambito_ids"]) for u in ids.split(";")}
            cm = {u: gr for gr, ids in zip(c["grupo"], c["ambito_ids"]) for u in ids.split(";")}
            ri = rand_index(om, cm)
            rands.append(ri)
            same_partition += ri == 1.0
            same_label += sum(om[u] == cm[u] for u in om)
            n_units += len(om)
            line.append(f"{year}: k {len(set(om.values()))}/{len(set(cm.values()))} Rand {ri:.2f}")
        print(f"  {indicator}: Rand medio {np.mean(rands):.3f}; particiones idénticas "
              f"{same_partition}/10; unidades con el mismo n.º de grupo {same_label}/{n_units} "
              f"({100 * same_label / n_units:.0f} %)")
        print("    " + " · ".join(line))

    # 4) Ámbitos ya validados (nacional, área, región, dominio) ----------------------------
    print("\n4) Ámbitos de validar_cifras_oficiales.py, recalculados por pobreza_departamental.py")
    rows = []
    for indicator in ("pobreza_total", "pobreza_extrema", "gasto_real_pc", "gasto_nominal_pc",
                      "ingreso_real_pc"):
        spec = OFFICIAL_SERIES[indicator]
        for area, values in spec["valores"].items():
            tipo, ident = AREA_MAP[area]
            sub = long[(long["ambito_tipo"] == tipo) & (long["ambito_id"] == ident)
                       & (long["indicador"] == indicator)].set_index("anio")["valor"]
            for year, value in zip(YEARS, values):
                if year in sub.index:
                    rows.append(dict(indicador=indicator, dif=sub[year] - value,
                                     tol=TOL_POINT if spec["unidad"] == "%" else TOL_SOLES))
    r = pd.DataFrame(rows)
    for (label, tol), x in r.groupby([r["indicador"].str.startswith("pobreza"), "tol"]):
        totals.append(summary("pobreza total y extrema (%)" if label else "gasto e ingreso (S/)",
                              x["dif"], tol))

    # 5) Diagnóstico de definiciones de Lima ------------------------------------------------
    print("\n5) Definiciones de Lima (población estimada 2025, personas)")
    pop = long[(long["anio"] == 2025) & (long["indicador"] == "poblacion")]
    get = lambda t, i: float(pop[(pop.ambito_tipo == t) & (pop.ambito_id == i)]["valor"].iloc[0])
    print(f"  dominio 8 «Lima Met. y Callao» = {get('dominio_inei', 'lima_metropolitana_callao'):,.0f}"
          f"  |  1501 Lima Met. (43 distritos) + 07 Callao = "
          f"{get('departamento_inei', '15LM') + get('departamento_inei', '07'):,.0f}")
    print(f"  departamento 15 Lima = {get('departamento', '15'):,.0f}  |  15LM + 15LP = "
          f"{get('departamento_inei', '15LM') + get('departamento_inei', '15LP'):,.0f}")

    ok = sum(a for a, _ in totals)
    n = sum(b for _, b in totals)
    print(f"\nRESUMEN: {ok}/{n} comparaciones dentro de tolerancia "
          "(detalle de lo que no cuadra en docs/validacion_pobreza_departamental.md §4)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
