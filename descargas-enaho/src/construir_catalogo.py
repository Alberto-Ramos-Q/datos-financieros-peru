"""Genera el catálogo de la base ENAHO a partir de los Parquet de data/processed.

Salidas:
- docs/catalogo_enaho.md                       resumen legible (regenerado, no editar a mano)
- data/_control/catalogo_variables.parquet     una fila por año × tabla × columna (tipo, % nulos)

Uso: python src/construir_catalogo.py   (correr después de construir_parquet.py)
"""
from __future__ import annotations

import csv
import datetime as dt
import re
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
PROC_DIR = ROOT / "data" / "processed"
MANIFEST = ROOT / "data" / "_control" / "manifest.csv"
VARS_OUT = ROOT / "data" / "_control" / "catalogo_variables.parquet"
MD_OUT = ROOT / "docs" / "catalogo_enaho.md"

# Variables clave para seguir su disponibilidad año a año: (tabla genérica, columna, descripción)
KEY_VARS = [
    ("sumaria", "factor07", "Factor de expansión del hogar"),
    ("sumaria", "mieperho", "Miembros del hogar"),
    ("sumaria", "gashog1d", "Gasto monetario del hogar (anual)"),
    ("sumaria", "gashog2d", "Gasto total del hogar (anual)"),
    ("sumaria", "inghog2d", "Ingreso neto total del hogar (anual)"),
    ("sumaria", "gru21hd", "Vestido y calzado: compra (Sumaria 8 grupos)"),
    ("sumaria", "ld", "Deflactor espacial (base Lima Metropolitana)"),
    ("sumaria", "pobreza", "Condición de pobreza"),
    ("sumaria", "estrato", "Estrato geográfico (1–5 urbano, 6–8 rural)"),
    ("sumaria", "dominio", "Dominio geográfico (8 = Lima Metropolitana)"),
    ("enaho01-607", "p607n", "Ítem de vestido y calzado (1–7)"),
    ("enaho01-607", "p607a1", "Forma de obtención: comprado"),
    ("enaho01-607", "p607aa", "Lugar de compra (canal)"),
    ("enaho01-607", "i607b", "Monto comprado anualizado e imputado"),
    ("enaho01a-300", "i311b$1", "Uniforme escolar anualizado"),
    ("enaho01a-300", "i311b$2", "Calzado escolar anualizado"),
    ("enaho01-200", "facpob07", "Factor de expansión de personas"),
    ("enaho01-200", "p203", "Parentesco con el jefe del hogar"),
    ("enaho01-200", "p204", "¿Es miembro del hogar?"),
]


def generic_name(stem: str, year: str) -> str:
    """enaho01-2025-607 → enaho01-607 · sumaria-2025-12g → sumaria-12g (2017 trae '-12')."""
    name = re.sub(rf"-{year}(?=-|$)", "", stem)
    return "sumaria-12g" if name == "sumaria-12" else name


def scan() -> tuple[pd.DataFrame, pd.DataFrame]:
    tables, columns = [], []
    for path in sorted(PROC_DIR.glob("*/*.parquet")):
        if not path.parent.name.isdigit():  # p. ej. deflactores/: no son microdatos de un año
            continue
        year, stem = path.parent.name, path.stem
        meta = pq.ParquetFile(path)
        name = generic_name(stem, year)
        tables.append({"anio": int(year), "tabla": name, "archivo": stem,
                       "filas": meta.metadata.num_rows, "columnas": meta.metadata.num_columns,
                       "mb": round(path.stat().st_size / 1e6, 2)})
        schema = meta.schema_arrow
        null_counts = {}
        for rg in range(meta.num_row_groups):
            stats = meta.metadata.row_group(rg)
            for i in range(stats.num_columns):
                col = stats.column(i)
                n = col.statistics.null_count if col.statistics is not None else None
                null_counts[col.path_in_schema] = (null_counts.get(col.path_in_schema) or 0) + (n or 0)
        for field in schema:
            pct = 100 * null_counts.get(field.name, 0) / max(meta.metadata.num_rows, 1)
            columns.append({"anio": int(year), "tabla": name, "columna": field.name,
                            "tipo": str(field.type), "pct_nulos": round(pct, 1)})
    return pd.DataFrame(tables), pd.DataFrame(columns)


def year_summary(years: list[int]) -> pd.DataFrame:
    with open(MANIFEST, encoding="utf-8") as fh:
        manifest = pd.DataFrame(csv.DictReader(fh))
    manifest["anio"] = manifest.anio.astype(int)
    manifest["bytes"] = manifest.bytes.astype(int)
    rows = []
    for year in years:
        s = pd.read_parquet(PROC_DIR / str(year) / f"sumaria-{year}.parquet",
                            columns=["conglome", "factor07", "mieperho"])
        s[["factor07", "mieperho"]] = s[["factor07", "mieperho"]].astype("float64")  # Stata: float32
        m = manifest[manifest.anio == year]
        rows.append({
            "anio": year,
            "formato_fuente": ", ".join(sorted(m.formato.unique())),
            "codigo_encuesta": m.url.str.extract(r"/(\d+)-Modulo")[0].iloc[0],
            "zips_mb": round(m.bytes.sum() / 1e6, 1),
            "hogares_muestra": len(s),
            "hogares_expandidos_mill": round(s.factor07.sum() / 1e6, 2),
            "personas_expandidas_mill": round((s.factor07 * s.mieperho).sum() / 1e6, 2),
            "digitos_conglome": "/".join(map(str, sorted(s.conglome.str.len().unique()))),
        })
    return pd.DataFrame(rows)


def to_md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(map(str, cols)) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join("" if pd.isna(v) else str(v) for v in row) + " |"
              for row in df.itertuples(index=False)]
    return "\n".join(lines)


def main() -> None:
    tables, columns = scan()
    VARS_OUT.parent.mkdir(parents=True, exist_ok=True)
    columns.to_parquet(VARS_OUT, index=False)
    years = sorted(tables.anio.unique())

    summary = year_summary(years)
    rows_matrix = tables.pivot_table(index="tabla", columns="anio", values="filas", aggfunc="sum")
    main_tables = ["enaho01-100", "enaho01-200", "enaho01a-300", "enaho01a-500",
                   "enaho01-607", "sumaria", "sumaria-12g"]
    rows_matrix = rows_matrix.reindex([t for t in main_tables if t in rows_matrix.index])
    rows_matrix = rows_matrix.T.reset_index().rename(columns={"anio": "año"})
    for c in rows_matrix.columns[1:]:
        rows_matrix[c] = rows_matrix[c].map(lambda v: "—" if pd.isna(v) else f"{int(v):,}")

    present = columns.assign(ok=True).set_index(["tabla", "columna", "anio"]).ok
    avail = []
    for table, col, desc in KEY_VARS:
        yrs = [y for y in years if present.get((table, col, y), False)]
        missing = [y for y in years if y not in yrs]
        avail.append({"tabla": table, "variable": col, "descripción": desc,
                      "años": f"{yrs[0]}–{yrs[-1]}" if yrs else "—",
                      "faltan en": ", ".join(map(str, missing)) or "ninguno"})

    other = tables[~tables.tabla.isin(main_tables)].groupby("tabla").anio.agg(["min", "max", "count"])

    md = f"""# Catálogo de la base ENAHO

> Generado por `src/construir_catalogo.py` el {dt.date.today():%Y-%m-%d}. **No editar a mano**: volver a
> correr el script después de `construir_parquet.py`. Detalle columna por columna (tipo y % de
> nulos por año): `data/_control/catalogo_variables.parquet`.

## Resumen por año
{to_md(summary)}

- `hogares_muestra`: hogares en la Sumaria (entrevista completa o incompleta).
- `hogares/personas_expandidas`: suma de `factor07` y `factor07 × mieperho`. Los saltos entre
  periodos reflejan sobre todo cambios en las proyecciones de población usadas para calibrar el
  factor, no cambios reales: para comparar años usar cifras per cápita o tasas.
- `digitos_conglome`: el código de conglomerado cambia de largo entre periodos. No afecta
  cruces dentro de un año; sí cualquier intento de seguir conglomerados entre años.

## Filas por tabla principal y año
{to_md(rows_matrix)}

Nombres de tabla sin el año: `enaho01-607` = `data/processed/<año>/enaho01-<año>-607.parquet`;
`sumaria` = `sumaria-<año>.parquet`.

## Disponibilidad de variables clave
{to_md(pd.DataFrame(avail))}

## Otras tablas (auxiliares de los zips)
{to_md(other.reset_index().rename(columns={"min": "desde", "max": "hasta", "count": "años"}))}
"""
    MD_OUT.write_text(md, encoding="utf-8")
    print(f"Catálogo: {len(tables)} tablas, {len(columns)} columnas -> {MD_OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
