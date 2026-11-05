"""Une las tablas de cada país (`data/interim/<ISO3>_observaciones.parquet`) en
tablas comparables en `data/processed/`:

    macro_observaciones.parquet / .csv   largo: todas las series de todos los países
    macro_series.csv                     dimensión de series: fuente, código, título, unidad, notas, cobertura
    macro_cobertura.csv                  país × indicador común: 'desde → hasta (n)'
    macro_comun_<frecuencia>.csv         panel país × fecha con una columna por indicador común

Uso:
    python consolidar.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun  # noqa: E402

OUT_DIR = comun.PROJECT_DIR / "data" / "processed"


def load_config() -> pd.DataFrame:
    frames = []
    for path in sorted((comun.CONFIG_DIR / "series").glob("*.csv")):
        df = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
        df.insert(0, "pais", path.stem)
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def main() -> int:
    files = sorted(comun.INTERIM_DIR.glob("*_observaciones.parquet"))
    if not files:
        print("No hay nada en data/interim/: corre primero los scripts de src/paises/.")
        return 1
    obs = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    obs["indicador_comun"] = obs["indicador_comun"].fillna("")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    obs.to_parquet(OUT_DIR / "macro_observaciones.parquet", index=False)
    obs.to_csv(OUT_DIR / "macro_observaciones.csv", index=False, encoding="utf-8-sig")

    cover = (obs.groupby(["pais", "nombre_corto"])
             .fecha.agg(n_obs="count", desde="min", hasta="max").reset_index())
    cfg = load_config()
    series = cfg.merge(cover, on=["pais", "nombre_corto"], how="left")
    series.to_csv(OUT_DIR / "macro_series.csv", index=False, encoding="utf-8-sig")

    common = pd.read_csv(comun.CONFIG_DIR / "indicadores_comunes.csv", encoding="utf-8-sig")
    com = obs[obs.indicador_comun != ""]
    cell = (com.groupby(["pais", "indicador_comun", "frecuencia"]).fecha
            .agg(["min", "max", "count"]).reset_index())
    cell["texto"] = (cell["min"].dt.strftime("%Y-%m") + " → " + cell["max"].dt.strftime("%Y-%m")
                     + " (" + cell["count"].astype(str) + ")")
    matrix = (cell.pivot(index="indicador_comun", columns="pais", values="texto")
              .reindex(common.indicador_comun).fillna(""))
    matrix.to_csv(OUT_DIR / "macro_cobertura.csv", encoding="utf-8-sig")

    # Un indicador puede venir en distinta frecuencia según el país (p. ej. desempleo
    # mensual o trimestral): cada panel junta lo que el país publica en esa frecuencia.
    for freq in comun.FREQUENCIES:
        sub = com[com.frecuencia == freq]
        if sub.empty:
            continue
        cols = [c for c in common.indicador_comun if c in set(sub.indicador_comun)]
        panel = (sub.pivot_table(index=["pais", "fecha"], columns="indicador_comun",
                                 values="valor", aggfunc="first")[cols].sort_index())
        panel.to_csv(OUT_DIR / f"macro_comun_{freq}.csv", encoding="utf-8-sig")

    n_common = (matrix != "").sum()
    print(f"{len(obs):,} observaciones · {obs.pais.nunique()} países · "
          f"{obs.groupby('pais').nombre_corto.nunique().sum()} series")
    print("Indicadores comunes cubiertos por país (de", len(common), "):")
    for pais, n in n_common.items():
        print(f"  {pais}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
