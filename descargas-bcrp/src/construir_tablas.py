"""Convierte los JSON descargados del BCRP en tablas listas para pandas y Power BI.

Lee `data/raw/<frecuencia>/CODIGO.json` (solo las series activas de
`config/series.csv`) y escribe en `data/processed/`:

    bcrp_observaciones.parquet / .csv   formato largo: una fila por serie × periodo
    bcrp_series.csv                     dimensión de series: tema, título, cobertura
    bcrp_panel_<frecuencia>.csv         formato ancho: una columna por serie (nombre_corto)

La fecha de cada periodo es su primer día (mes, trimestre o año); en las diarias,
el día mismo. La etiqueta original del BCRP se conserva en `periodo_bcrp`.

Uso:
    python construir_tablas.py
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parents[1]
SERIES_CSV = PROJECT_DIR / "config" / "series.csv"
RAW_DIR = PROJECT_DIR / "data" / "raw"
OUT_DIR = PROJECT_DIR / "data" / "processed"

MONTHS = {m: i + 1 for i, m in enumerate(
    ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"])}
MONTHS["set"] = 9  # el BCRP a veces escribe «Set.» por setiembre
FREQ_ORDER = ["mensual", "trimestral", "anual", "diaria"]


def full_year(yy: str, today: dt.date) -> int:
    """Años de 2 dígitos ('97', '26') de las series diarias y trimestrales."""
    if len(yy) == 4:
        return int(yy)
    y = int(yy)
    return 2000 + y if y <= today.year % 100 else 1900 + y


def parse_period(label: str, frecuencia: str, today: dt.date) -> dt.date:
    if frecuencia == "mensual":            # 'Ene.1994'
        mes, anio = label.split(".")
        return dt.date(full_year(anio, today), MONTHS[mes[:3].lower()], 1)
    if frecuencia == "trimestral":         # 'T1.80'
        trim, anio = label.split(".")
        return dt.date(full_year(anio, today), 3 * int(trim[1]) - 2, 1)
    if frecuencia == "anual":              # '1922'
        return dt.date(int(label), 1, 1)
    if frecuencia == "diaria":             # '02.Ene.97'
        dia, mes, anio = label.split(".")
        return dt.date(full_year(anio, today), MONTHS[mes[:3].lower()], int(dia))
    raise ValueError(f"Frecuencia desconocida: {frecuencia}")


def read_series(row: pd.Series, today: dt.date,
                invalid: list[dict]) -> tuple[pd.DataFrame, str] | None:
    path = RAW_DIR / row.frecuencia / f"{row.codigo}.json"
    if not path.exists():
        print(f"  falta {path.relative_to(PROJECT_DIR)} (¿no se descargó?)")
        return None
    payload = json.loads(path.read_bytes().decode("utf-8"))
    recs = []
    for p in payload["periods"]:
        v = p["values"][0] if p.get("values") else None
        if v in (None, "", "n.d."):
            continue
        try:
            value = float(v)
        except ValueError:
            # Errores de la propia base del BCRP (p. ej. PD12301MD el 14.Set.17 trae
            # '3.7512301,2011-04-07,3.75'): no se imputan, quedan como faltantes y listados.
            invalid.append({"codigo": row.codigo, "nombre_corto": row.nombre_corto,
                            "periodo_bcrp": p["name"], "valor_bcrp": v})
            continue
        recs.append({"fecha": parse_period(p["name"], row.frecuencia, today),
                     "periodo_bcrp": p["name"], "valor": value})
    df = pd.DataFrame(recs)
    df.insert(0, "codigo", row.codigo)
    df.insert(1, "nombre_corto", row.nombre_corto)
    df.insert(2, "frecuencia", row.frecuencia)
    df.insert(3, "tema", row.tema)
    return df, payload["config"]["series"][0]["name"]


def main() -> int:
    # La consola de Windows (cp1252) no puede imprimir «→»: sin esto el script se cae a mitad.
    sys.stdout.reconfigure(encoding="utf-8")
    today = dt.date.today()
    cfg = pd.read_csv(SERIES_CSV, dtype=str, encoding="utf-8-sig")
    cfg = cfg[cfg.activo.str.strip() == "1"]

    frames, meta, invalid = [], [], []
    for row in cfg.itertuples(index=False):
        res = read_series(row, today, invalid)
        if res is None:
            continue
        df, api_name = res
        dup = df.duplicated("fecha").sum()
        if dup:
            raise ValueError(f"{row.codigo}: {dup} periodos repetidos tras convertir fechas")
        frames.append(df)
        meta.append({"codigo": row.codigo, "nombre_corto": row.nombre_corto,
                     "frecuencia": row.frecuencia, "tema": row.tema,
                     "titulo_bcrp": api_name, "n_obs": len(df),
                     "desde": df.fecha.min(), "hasta": df.fecha.max()})

    obs = pd.concat(frames, ignore_index=True)
    obs["fecha"] = pd.to_datetime(obs.fecha)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    obs.to_parquet(OUT_DIR / "bcrp_observaciones.parquet", index=False)
    obs.to_csv(OUT_DIR / "bcrp_observaciones.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(meta).to_csv(OUT_DIR / "bcrp_series.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(invalid, columns=["codigo", "nombre_corto", "periodo_bcrp", "valor_bcrp"]).to_csv(
        OUT_DIR / "bcrp_valores_invalidos.csv", index=False, encoding="utf-8-sig")
    for bad in invalid:
        print(f"  AVISO valor no numérico (queda como faltante): {bad['codigo']} "
              f"{bad['periodo_bcrp']} = {bad['valor_bcrp']!r}")

    for freq in FREQ_ORDER:
        sub = obs[obs.frecuencia == freq]
        if sub.empty:
            continue
        # Columnas en el orden de config/series.csv, no alfabético.
        cols = [c for c in cfg.nombre_corto if c in set(sub.nombre_corto)]
        panel = sub.pivot(index="fecha", columns="nombre_corto", values="valor")[cols].sort_index()
        panel.to_csv(OUT_DIR / f"bcrp_panel_{freq}.csv", encoding="utf-8-sig")
        print(f"  panel {freq:10s} {panel.shape[0]:6d} periodos × {panel.shape[1]:3d} series  "
              f"({panel.index.min():%Y-%m-%d} → {panel.index.max():%Y-%m-%d})")

    print(f"observaciones: {len(obs):,} filas de {obs.codigo.nunique()} series")
    return 0


if __name__ == "__main__":
    sys.exit(main())
