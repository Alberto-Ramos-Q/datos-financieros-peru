"""Concentración bancaria de Perú para la comparación internacional (diciembre de 2015 a 2025).

Mismo formato que las salidas de Chile, Colombia y Brasil (`data/processed/internacional/`):
    peru_entidades.csv       pais, anio, mes, entidad, estatal, variable, valor, unidad, base, fuente_url
    peru_concentracion.csv   pais, anio, variable, variante, base, n, cr4, cr5, ihh, peso_estatal, fuente, notas

Perímetro (decisión del usuario, 2026-11-03: «con estatales» por defecto, con selector):
- `sin_estatales`: banca múltiple. Montos del ranking B-2332 (`panel_entidad_mes`: créditos directos y
  depósitos totales). «No incluye sucursales en el exterior»: es una base individual.
- `con_estatales`: banca múltiple + Banco de la Nación + Agrobanco, de `panel_estatales_mes`, con la misma
  fórmula del ranking aplicada a sus balances B-5102/B-5104. Agrobanco no capta depósitos.
  No se usa el SF-2103 ni la Carpeta SIF para el BN: hasta al menos ene-2023 solo incluían sus créditos de
  consumo e hipotecarios (docs/cobertura_sbs_p12_p14.md § 2.1).
Participaciones sobre la suma de las entidades del perímetro. IHH de 0 a 10 000.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parents[2]
PROCESSED = PROJECT_DIR / "data" / "processed"
OUT_DIR = PROCESSED / "internacional"
YEARS = range(2015, 2026)
VARIABLES = {"creditos_directos": "creditos", "depositos_totales": "depositos"}
FUENTE_BANCA = "SBS, ranking B-2332 (Boletín Estadístico, banca múltiple)"
FUENTE_EST = "SBS, Balance General B-5102 (BN) y B-5104 (Agrobanco), Boletín Estadístico p=12"
URL = "https://www.sbs.gob.pe/app/stats_net/stats/EstadisticaBoletinEstadistico.aspx"


def load_entities() -> pd.DataFrame:
    periods = [y * 100 + 12 for y in YEARS]
    bank = pd.read_parquet(PROCESSED / "panel_entidad_mes.parquet",
                           columns=["periodo", "subsistema", "id_entidad", "nombre_entidad", *VARIABLES])
    bank = bank[(bank.subsistema == "banca-multiple") & (bank.id_entidad != "_total") & bank.periodo.isin(periods)]
    bank = bank.assign(estatal=False, fuente=FUENTE_BANCA)
    state = pd.read_parquet(PROCESSED / "panel_estatales_mes.parquet",
                            columns=["periodo", "subsistema", "id_entidad", "nombre_entidad", *VARIABLES])
    state = state[state.periodo.isin(periods)].assign(estatal=True, fuente=FUENTE_EST)
    df = pd.concat([bank, state], ignore_index=True)
    long = df.melt(id_vars=["periodo", "id_entidad", "nombre_entidad", "estatal", "fuente"],
                   value_vars=list(VARIABLES), var_name="variable", value_name="valor")
    long["variable"] = long["variable"].map(VARIABLES)
    long = long[long.valor.notna() & (long.valor > 0)]
    return long


def concentration(shares: pd.Series) -> dict:
    s = shares.sort_values(ascending=False)
    return {"n": len(s), "cr4": round(s.head(4).sum(), 1), "cr5": round(s.head(5).sum(), 1),
            "ihh": round((s ** 2).sum())}


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    long = load_entities()
    dup = long.duplicated(["periodo", "id_entidad", "variable"])
    if dup.any():
        raise ValueError(f"entidades duplicadas: {long[dup].head()}")
    ent = pd.DataFrame({"pais": "PER", "anio": long.periodo // 100, "mes": long.periodo % 100,
                        "entidad": long.nombre_entidad.astype(str), "estatal": long.estatal,
                        "variable": long.variable, "valor": long.valor.round(3), "unidad": "miles_soles",
                        "base": "individual", "fuente_url": URL})
    ent = ent.sort_values(["anio", "variable", "valor"], ascending=[True, True, False])
    ent.to_csv(OUT_DIR / "peru_entidades.csv", index=False, encoding="utf-8")

    rows = []
    for (year, var), g in ent.groupby(["anio", "variable"]):
        for variante, sub in [("con_estatales", g), ("sin_estatales", g[~g.estatal])]:
            shares = sub.valor / sub.valor.sum() * 100
            peso = round(shares[sub.estatal].sum(), 1) if variante == "con_estatales" else None
            nota = ("BN y Agrobanco desde sus balances (B-5102/B-5104); Agrobanco no capta depósitos"
                    if variante == "con_estatales" else "Banca múltiple (ranking B-2332)")
            rows.append({"pais": "PER", "anio": year, "variable": var, "variante": variante, "base": "individual",
                         **concentration(shares), "peso_estatal": peso,
                         "fuente": FUENTE_BANCA + (" + " + FUENTE_EST if variante == "con_estatales" else ""),
                         "notas": nota})
    conc = pd.DataFrame(rows)
    conc.to_csv(OUT_DIR / "peru_concentracion.csv", index=False, encoding="utf-8")
    print(conc[["anio", "variable", "variante", "n", "cr4", "cr5", "ihh", "peso_estatal"]].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
