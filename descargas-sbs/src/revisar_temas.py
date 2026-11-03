"""Revisión de cobertura y coherencia de las tablas procesadas del boletín (cualquier tema).

Complementa los controles que escribe `leer_boletin.py` (`_control/<tema>_validacion.csv`):
mira qué meses y entidades hay en cada `data/processed/boletin/<tema>.parquet` y resume las
violaciones de la validación. No modifica los parquet.

Por tema escribe `data/processed/boletin/_control/<tema>_cobertura.csv`, una fila por
subsistema × código: primer y último mes, meses esperados (desde `config/series.csv` hasta el
último mes del tema), meses con dato, meses faltantes (lista AAAAMM), archivos en `data/raw` sin
filas en el parquet, entidades por mes (mín./mediana/máx.) y saltos de ±3 o más entidades
entre meses consecutivos.

Cruces adicionales (si existen los parquet involucrados):
- `creditos-departamento`: el TOTAL de cada entidad (miles de soles) vs. `creditos_directos` del
  ranking (`ranking-creditos-depositos-patrimonio`); lista diferencias > 1 % en
  `_control/creditos-departamento_cruce_ranking.csv`.

Uso:
    python revisar_temas.py                                   # todos los temas con parquet
    python revisar_temas.py --tema deudores-tipo-credito --tema creditos-departamento
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))
from lector import comun  # noqa: E402

RAW_DIR = PROJECT_DIR / "data" / "raw" / "boletin"
OUT_DIR = PROJECT_DIR / "data" / "processed" / "boletin"
SERIES_CSV = PROJECT_DIR / "config" / "series.csv"


def meses(desde: int, hasta: int) -> list[int]:
    out, (y, m) = [], divmod(desde, 100)
    while y * 100 + m <= hasta:
        out.append(y * 100 + m)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def cobertura(tema: str, df: pd.DataFrame, series: pd.DataFrame) -> pd.DataFrame:
    ultimo = int(df["periodo"].max())
    filas = []
    for s in series[series["tema"] == tema].itertuples():
        d = df[(df["subsistema"] == s.subsistema) & (df["codigo"] == s.codigo)]
        fin = min(ultimo, int(s.hasta)) if "hasta" in series and pd.notna(s.hasta) else ultimo
        esperados = meses(max(int(s.desde), 199001), fin)
        con_dato = sorted(d["periodo"].unique())
        faltan = [p for p in esperados if p not in set(con_dato)]
        crudos = {comun.periodo_de(r) for r in (RAW_DIR / s.subsistema / tema).glob(f"{s.codigo}-*.XLS")}
        sin_filas = sorted(p for p in crudos if p not in set(con_dato) and int(s.desde) <= p <= fin)
        n_ent = (d[~d["es_total"]].groupby("periodo")["entidad_original"].nunique()
                 .reindex(con_dato).fillna(0).astype(int))
        cambio = n_ent.diff()
        filas.append({
            "subsistema": s.subsistema, "codigo": s.codigo,
            "primer_mes": con_dato[0] if con_dato else None, "ultimo_mes": con_dato[-1] if con_dato else None,
            "meses_esperados": len(esperados), "meses_con_dato": len(con_dato), "meses_faltantes": len(faltan),
            "lista_faltantes": " ".join(map(str, faltan)),
            "archivos_sin_filas": " ".join(map(str, sin_filas)),
            "meses_sin_total": int((~d.groupby("periodo")["es_total"].any()).sum()) if len(d) else 0,
            "entidades_min": int(n_ent.min()) if len(n_ent) else 0,
            "entidades_mediana": float(n_ent.median()) if len(n_ent) else 0,
            "entidades_max": int(n_ent.max()) if len(n_ent) else 0,
            "saltos_entidades": " ".join(f"{p}:{int(cambio[p]):+d}" for p in cambio[cambio.abs() >= 3].index),
        })
    return pd.DataFrame(filas)


def cruce_departamento_ranking() -> pd.DataFrame | None:
    a, b = OUT_DIR / "creditos-departamento.parquet", OUT_DIR / "ranking-creditos-depositos-patrimonio.parquet"
    if not (a.exists() and b.exists()):
        return None
    clave = ["periodo", "subsistema", "id_entidad"]
    dep = pd.read_parquet(a)
    dep = dep[(dep["variable"] == "creditos_directos") & dep["id_entidad"].notna()]
    ran = pd.read_parquet(b, columns=clave + ["variable", "valor"])
    ran = ran[(ran["variable"] == "creditos_directos") & ran["id_entidad"].notna()]
    x = dep[clave + ["entidad_original", "valor"]].merge(
        ran[clave + ["valor"]].rename(columns={"valor": "ranking"}), on=clave, how="inner")
    x["dif_rel"] = (x["valor"] - x["ranking"]).abs() / x["ranking"].abs().clip(lower=1)
    return x


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--tema", action="append", help="Tema(s); por defecto todos los que tienen parquet.")
    args = p.parse_args()
    series = pd.read_csv(SERIES_CSV, dtype={"desde": int})
    series = series[series["activo"].astype(str).str.strip() == "1"]
    temas = args.tema or sorted(r.stem for r in OUT_DIR.glob("*.parquet"))
    control = OUT_DIR / "_control"
    for tema in temas:
        ruta = OUT_DIR / f"{tema}.parquet"
        if not ruta.exists():
            print(f"{tema}: sin parquet (correr leer_boletin.py --tema {tema})")
            continue
        df = pd.read_parquet(ruta, columns=["periodo", "subsistema", "codigo", "entidad_original", "es_total"])
        cob = cobertura(tema, df, series)
        cob.to_csv(control / f"{tema}_cobertura.csv", index=False, encoding="utf-8")
        print(f"\n== {tema}: {len(df):,} filas, {df['periodo'].min()}-{df['periodo'].max()}")
        print(cob[["subsistema", "codigo", "primer_mes", "ultimo_mes", "meses_con_dato", "meses_faltantes",
                   "entidades_min", "entidades_max", "meses_sin_total"]].to_string(index=False))
        for c in ("lista_faltantes", "archivos_sin_filas", "saltos_entidades"):
            for r in cob[cob[c] != ""].itertuples():
                print(f"  {c} {r.subsistema}: {getattr(r, c)}")
        val = control / f"{tema}_validacion.csv"
        if val.exists():
            v = pd.read_csv(val)
            grupos = v.groupby("regla").size().to_dict() if "regla" in v else {"suma_entidades!=total": len(v)}
            print(f"  validación: {len(v)} violaciones {grupos if len(v) else ''}")
        if tema == "creditos-departamento":
            x = cruce_departamento_ranking()
            if x is not None:
                malos = x[x["dif_rel"] > 0.01].sort_values("dif_rel", ascending=False)
                malos.to_csv(control / f"{tema}_cruce_ranking.csv", index=False, encoding="utf-8")
                print(f"  cruce TOTAL vs ranking: {len(x):,} pares entidad-mes; mediana dif. "
                      f"{x['dif_rel'].median():.2%}; {len(malos)} con dif. > 1 %")
    return 0


if __name__ == "__main__":
    sys.exit(main())
