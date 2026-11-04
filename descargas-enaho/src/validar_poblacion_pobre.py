"""Valida el número de personas pobres (nacional) frente a las cifras publicadas por el INEI.

Hallazgo (2026-11-03): el INEI no expande con los factores de la ENAHO. Calcula
    pobres = incidencia publicada (redondeada a 1 decimal) × población oficial al 30 de junio
con la población de las Estimaciones y Proyecciones vigentes (Boletín Especial N° 24, base Censo 2017).
- 2019–2025: reproduce las 7 cifras publicadas con diferencias de redondeo (±0,5 mil).
- 2012–2017: las cifras publicadas usan las proyecciones anteriores (base Censo 2007), vigentes cuando
  salió cada informe; con la población actual dan entre 185 y 272 mil menos. Es un efecto de época.
- La suma de factores de la ENAHO (factor07·mieperho) da ~1,2–1,6 % más población que la oficial,
  por eso el total «propio» (8 946 534 en 2025) no coincide con el publicado (8 828 mil).

Solo imprime; no escribe archivos. Uso (desde la raíz del proyecto):
    python src/validar_poblacion_pobre.py
Lee: config/pobres_nacional_oficial.csv, data/processed/pobreza/pobreza_ambitos.parquet y
config/insumo_poblacion_adulta.csv (copia de ../descargas-inei, que se refresca sola si está al lado).
"""
from pathlib import Path
import sys

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parents[1]
OFFICIAL = PROJECT_DIR / "config" / "pobres_nacional_oficial.csv"
AMBITOS = PROJECT_DIR / "data" / "processed" / "pobreza" / "pobreza_ambitos.parquet"
from visual_pobreza import read_population  # noqa: E402  (copia en config/, refrescada desde descargas-inei)
TOL_MILES = 0.5            # redondeo a miles del INEI
CURRENT_VINTAGE_FROM = 2019  # desde aquí los informes usan la población base Censo 2017


def main() -> int:
    off = pd.read_csv(OFFICIAL)
    pop = read_population()
    amb = pd.read_parquet(AMBITOS)
    nat = amb[amb["ambito_tipo"] == "nacional"].pivot(index="anio", columns="indicador", values="valor")

    rows = []
    for r in off.itertuples():
        y = r.anio
        inc_own = nat.loc[y, "pobreza_total"]
        inei_method = round(inc_own, 1) / 100 * pop[y] / 1000        # miles
        expanded = nat.loc[y, "poblacion_pobre_total"] / 1000         # miles, factores ENAHO
        rows.append({
            "anio": y, "publicado": r.pobres_miles_publicado, "metodo_inei": inei_method,
            "dif_metodo": r.pobres_miles_publicado - inei_method,
            "expansion_enaho": expanded, "dif_expansion": r.pobres_miles_publicado - expanded,
            "pobl_implicita_M": r.pobres_miles_publicado / (r.incidencia_publicada / 100) / 1000,
            "pobl_oficial_M": pop[y] / 1e6, "pobl_enaho_M": nat.loc[y, "poblacion"] / 1e6,
            "fuente": f"{r.fuente}, p. {r.pagina_pdf}",
        })
    t = pd.DataFrame(rows)
    pd.set_option("display.width", 200)
    print(t.round(2).to_string(index=False))

    cur = t[t["anio"] >= CURRENT_VINTAGE_FROM]
    ok = (cur["dif_metodo"].abs() <= TOL_MILES).sum()
    print(f"\n{CURRENT_VINTAGE_FROM}–2025 (población vigente): {ok}/{len(cur)} dentro de ±{TOL_MILES} mil; "
          f"máx. |dif.| = {cur['dif_metodo'].abs().max():.2f} mil")
    old = t[t["anio"] < CURRENT_VINTAGE_FROM]
    print(f"2012–2017 (publicados con proyecciones base Censo 2007): diferencia con la población vigente "
          f"{old['dif_metodo'].min():+.0f} a {old['dif_metodo'].max():+.0f} mil (efecto de época, no error)")
    print(f"Expansión con factores ENAHO frente a lo publicado, {CURRENT_VINTAGE_FROM}–2025: "
          f"{cur['dif_expansion'].min():+.0f} a {cur['dif_expansion'].max():+.0f} mil")
    return 0 if ok == len(cur) else 1


if __name__ == "__main__":
    sys.exit(main())
