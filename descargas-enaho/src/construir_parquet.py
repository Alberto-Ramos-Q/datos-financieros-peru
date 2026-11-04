"""Convierte los zips de microdatos ENAHO (data/raw) a Parquet (data/processed), sin extraer.

Lee cada tabla (.csv o .dta) directamente desde el zip y escribe
data/processed/<año>/<nombre original en minúsculas>.parquet
p. ej. data/processed/2025/enaho01-2025-607.parquet, data/processed/2025/sumaria-2025.parquet

Tipos: las llaves (conglome, vivienda, hogar, codperso, ubigeo…) y toda columna con ceros a la
izquierda quedan como texto; el resto pasa a número si todos sus valores lo son. Blancos → nulo.
Las llaves de ancho fijo con espacios a la izquierda (" 24" en STATA 2004-2006) se rellenan con
ceros ("024") para que crucen con las demás tablas del año. En STATA, las columnas guardadas
como texto (p. ej. p607 y p607a1 en 2005 y 2007) también se convierten a número si corresponde.
Nombres de columna en minúsculas (el INEI alterna mayúsculas entre años).

Uso:
    python src/construir_parquet.py            # todos los años en data/raw
    python src/construir_parquet.py 2025       # años puntuales
    python src/construir_parquet.py --rehacer  # reescribe aunque el Parquet ya exista
"""
from __future__ import annotations

import argparse
import io
import logging
import os
import re
import tempfile
import zipfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
OUT_DIR = ROOT / "data" / "processed"

LEADING_ZERO = re.compile(r"^0\d")
PANDAS_DTA_VERSIONS = {105, 108, 111, 113, 114, 115}  # formatos binarios que lee pandas
# Llaves de unión y ubicación: siempre texto, para que los merges no fallen entre módulos/años
KEY_COLS = {"conglome", "vivienda", "hogar", "codperso", "ubigeo", "nconglome",
            "sub_conglome", "codinfor"}

log = logging.getLogger("enaho")


def read_csv_member(raw: bytes) -> pd.DataFrame:
    header = raw[:2000].split(b"\n", 1)[0]
    sep = ";" if header.count(b";") > header.count(b",") else ","
    df = pd.read_csv(io.BytesIO(raw), sep=sep, dtype=str, encoding="latin1",
                     keep_default_na=False)
    return infer_types(df, decimal="," if sep == ";" else ".")


def pad_key(s: pd.Series) -> pd.Series:
    """Llave de ancho fijo con espacios a la izquierda (" 24", STATA 2004-2006) → ceros ("024")."""
    s = s.str.replace(r"^ +(?=\S)", lambda m: "0" * len(m.group()), regex=True)
    return s.str.strip().replace("", pd.NA).astype("string")


def infer_types(df: pd.DataFrame, decimal: str) -> pd.DataFrame:
    for col in df.columns:
        if col.strip().lower() in KEY_COLS:
            df[col] = pad_key(df[col])
            continue
        s = df[col].str.strip().replace("", pd.NA)
        values = s.dropna()
        if values.empty:
            df[col] = s.astype("string")
            continue
        if values.str.match(LEADING_ZERO).any():  # código: conservar ceros
            df[col] = s.astype("string")
            continue
        num = pd.to_numeric(values.str.replace(decimal, ".", regex=False), errors="coerce")
        if num.notna().all():
            num = num.reindex(s.index)
            is_int = (num.dropna() % 1 == 0).all()
            df[col] = num.astype("Int64") if is_int else num
        else:
            df[col] = s.astype("string")
    return df


def read_dta_member(raw: bytes) -> pd.DataFrame:
    if raw[0] in PANDAS_DTA_VERSIONS or raw[:1] == b"<":  # "<" = formato XML (117+)
        df = pd.read_stata(io.BytesIO(raw), convert_categoricals=False)
    else:  # p. ej. versión 110 (Stata 7) en 2004-2007: pandas no la lee
        import pyreadstat
        with tempfile.NamedTemporaryFile(suffix=".dta", delete=False) as tmp:
            tmp.write(raw)
        try:
            df, _ = pyreadstat.read_dta(tmp.name, apply_value_formats=False)
        finally:
            os.unlink(tmp.name)
    # Llaves numéricas → texto sin ".0"; columnas de texto (en 2005 y 2007 hay códigos como
    # p607 o p607a1 guardados como texto) pasan por la misma inferencia que el CSV.
    for col in df.columns:
        if col.lower() in KEY_COLS and df[col].dtype != object:
            df[col] = df[col].astype("Int64").astype("string")
    text_cols = [c for c in df.columns if df[c].dtype == object or c.lower() in KEY_COLS]
    if text_cols:
        sub = df[text_cols].astype("string").fillna("")
        df[text_cols] = infer_types(sub, decimal=".")
    return df


def convert_zip(zip_path: Path, out_dir: Path, redo: bool) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        members = [m for m in zf.namelist() if m.lower().endswith((".csv", ".dta"))]
        for member in members:
            target = out_dir / f"{Path(member).stem.lower()}.parquet"
            if target.exists() and not redo:
                log.info("[omitido] %s", target.relative_to(ROOT).as_posix())
                continue
            raw = zf.read(member)
            df = read_dta_member(raw) if member.lower().endswith(".dta") else read_csv_member(raw)
            df.columns = [c.strip().lower() for c in df.columns]
            out_dir.mkdir(parents=True, exist_ok=True)
            df.to_parquet(target, index=False)
            log.info("[ok] %s  %d filas × %d cols  (%.1f MB)",
                     target.relative_to(ROOT).as_posix(), len(df), df.shape[1],
                     target.stat().st_size / 1e6)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("years", nargs="*", type=int)
    parser.add_argument("--rehacer", action="store_true", help="reescribir Parquet existentes")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

    year_dirs = sorted(p for p in RAW_DIR.iterdir() if p.is_dir() and p.name.isdigit())
    for year_dir in year_dirs:
        if args.years and int(year_dir.name) not in args.years:
            continue
        for zip_path in sorted(year_dir.glob("*.zip")):
            convert_zip(zip_path, OUT_DIR / year_dir.name, args.rehacer)


if __name__ == "__main__":
    main()
