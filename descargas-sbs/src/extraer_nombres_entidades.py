"""Extrae los nombres de entidades tal como aparecen en los Excel descargados del boletín.

La SBS escribe la misma entidad de muchas formas según el cuadro y el mes
(«B. de Crédito del Perú (con sucursales en el exterior)», «B. De Crédito del Perú»,
«B. Santander Perú » con espacio final, notas al pie con asteriscos, etc.). Este script
recorre todos los archivos de `data/raw/boletin/` y registra cada variante observada,
para mapearla después con `config/entidades/entidad_alias.csv`.

Cómo localiza los nombres sin conocer el layout de cada cuadro: busca la celda
«Total <subsistema>» (p. ej. «TOTAL BANCA MÚLTIPLE», «Total CM») y toma los textos
alineados con ella: a su izquierda si los nombres van en columnas, o encima si van en filas.

Uso:
    python extraer_nombres_entidades.py            # escribe data/processed/nombres_observados.csv
    python extraer_nombres_entidades.py --serie B-2401
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import unicodedata
import warnings
from collections import defaultdict
from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))
from lector import comun  # noqa: E402,F401  (parche de xlrd para vínculos externos ilegibles: deudores)

RAW_DIR = PROJECT_DIR / "data" / "raw" / "boletin"
OUT_CSV = PROJECT_DIR / "data" / "processed" / "nombres_observados.csv"
MONTH_ABBR = ["en", "fe", "ma", "ab", "my", "jn", "jl", "ag", "se", "oc", "no", "di"]

# «Total» seguido de algo que identifique al subsistema. Excluye totales por tipo de
# crédito o por moneda («Total», «Total MN»), que también aparecen en los cuadros.
TOTAL_RE = re.compile(
    r"^total\s+(de\s+)?(la\s+)?(banca|bancos|sistema|empresas|financieras|cajas?|cm|cmac|"
    r"cr|crac|edpymes?|e\.?\s?c\.?)\b")
# Textos que nunca son una entidad aunque queden alineados con el total.
NOT_ENTITY_RE = re.compile(
    r"^(empresas?|entidad(es)?|instituci[oó]n(es)?|total|subtotal|nota|fuente|"
    r"activos?|pasivos?|patrimonio|situaci[oó]n|concepto|categor[ií]a|cajas\s|"
    r"\(?en (miles|millones|porcentaje)|\d)", re.IGNORECASE)
# Notas al pie que explican marcas como «*», «***» o «1/»: suelen documentar cambios de
# denominación, absorciones o inicio de operaciones.
FOOTNOTE_RE = re.compile(r"^\s*(\*+|\d+\s*/)\s*\S")
FOOTNOTE_EVENT_RE = re.compile(
    r"denominaci|absorb|absorci|fusi|escisi|conversi|convirti|autoriz|inici|disoluci|liquidaci|"
    r"intervenci|cambi|transfer|bloque patrimonial", re.IGNORECASE)
NOTES_CSV = PROJECT_DIR / "data" / "processed" / "notas_entidades.csv"


def norm(text: str) -> str:
    """minúsculas, sin tildes, espacios colapsados."""
    s = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().lower()


def clean_name(text: str) -> str:
    """Nombre como lo escribe la SBS, sin espacios sobrantes (se conserva todo lo demás)."""
    return re.sub(r"\s+", " ", text).strip()


def is_name_like(value) -> bool:
    if not isinstance(value, str):
        return False
    s = clean_name(value)
    return 2 <= len(s) <= 120 and not NOT_ENTITY_RE.match(norm(s)) and re.search("[A-Za-z]", s)


def is_number(value) -> bool:
    """Cifra distinta de cero: una entidad intervenida sigue en los cuadros, pero en ceros."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return pd.notna(value) and value != 0
    if isinstance(value, str) and re.fullmatch(r"-?[\d.,]+", value.strip()):
        return re.search(r"[1-9]", value) is not None
    return False


def names_near_total(df: pd.DataFrame, row: int, col: int) -> list[tuple[str, bool]]:
    """(nombre, tiene_datos) alineados con la celda total: a la izquierda o encima.

    `tiene_datos` distingue a las entidades con cifras de las cabeceras antiguas que la SBS
    deja olvidadas al final de algunas hojas (p. ej. «Financiera Edyficar» en 2026).
    """
    n_rows, n_cols = df.shape
    # Nombres en columnas: el total está en la misma fila de cabecera; los datos, debajo
    # (una entidad puede ocupar varias columnas: MN, ME, total).
    horizontal = []
    for j in range(col - 1, 0, -1):
        v = df.iat[row, j]
        if is_name_like(v):
            block = df.iloc[row + 1:row + 60, j:min(j + 4, n_cols)].to_numpy().ravel()
            horizontal.append((clean_name(v), any(is_number(x) for x in block)))
    # Nombres en filas: el total está en la misma columna, debajo; los datos, a la derecha.
    vertical = []
    for i in range(row - 1, -1, -1):
        v = df.iat[i, col]
        if is_name_like(v):
            vertical.append((clean_name(v), any(is_number(x) for x in df.iloc[i, col + 1:])))
        elif isinstance(v, str) and NOT_ENTITY_RE.match(norm(v)):
            break  # llegó a la cabecera «Empresas»
        elif pd.isna(v) and vertical and i < row - 1 and pd.isna(df.iat[i + 1, col]):
            break  # dos celdas vacías seguidas: terminó la lista
    best = horizontal if len(horizontal) >= len(vertical) else vertical
    return best[::-1]


def extract_file(path: Path) -> tuple[set[tuple[str, bool]], set[str]]:
    """((nombre, tiene_datos), notas al pie que hablan de eventos societarios)."""
    engine = "openpyxl" if path.read_bytes()[:2] == b"PK" else "xlrd"
    names: set[tuple[str, bool]] = set()
    notes: set[str] = set()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        book = pd.ExcelFile(path, engine=engine)
        for sheet in book.sheet_names:
            df = book.parse(sheet, header=None, dtype=object)
            for (i, j), v in df.stack().items():
                if not isinstance(v, str):
                    continue
                if TOTAL_RE.match(norm(v)):
                    names.update(names_near_total(df, i, df.columns.get_loc(j)))
                elif FOOTNOTE_RE.match(v) and FOOTNOTE_EVENT_RE.search(v):
                    notes.add(clean_name(v))
    return names, notes


def period_of(file_name: str) -> int:
    m = re.search(r"-([a-z]{2})(\d{4})\.", file_name, re.IGNORECASE)
    return int(m.group(2)) * 100 + MONTH_ABBR.index(m.group(1).lower()) + 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--serie", action="append", help="Código(s) a procesar, p. ej. B-2401.")
    args = parser.parse_args()

    # (subsistema, nombre) -> {codigos, periodos, archivos}
    seen: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"codigos": set(), "periodos": set(), "periodos_con_datos": set()})
    # (subsistema, nota) -> periodos y cuadros donde aparece
    seen_notes: dict[tuple[str, str], dict] = defaultdict(lambda: {"codigos": set(), "periodos": set()})
    files = sorted(RAW_DIR.glob("*/*/*.XLS"))
    if args.serie:
        files = [f for f in files if f.name.rsplit("-", 1)[0] in args.serie]
    errors = 0
    for n, path in enumerate(files, 1):
        subsistema = path.parent.parent.name
        codigo = path.name.rsplit("-", 1)[0]
        try:
            names, notes = extract_file(path)
        except Exception as exc:  # un archivo dañado no detiene el resto
            print(f"ERROR {path.name}: {exc}", file=sys.stderr)
            errors += 1
            continue
        periodo = period_of(path.name)
        for name, has_data in names:
            rec = seen[(subsistema, name)]
            rec["codigos"].add(codigo)
            rec["periodos"].add(periodo)
            if has_data:
                rec["periodos_con_datos"].add(periodo)
        for note in notes:
            rec = seen_notes[(subsistema, note)]
            rec["codigos"].add(codigo)
            rec["periodos"].add(periodo)
        if n % 200 == 0:
            print(f"{n}/{len(files)} archivos", file=sys.stderr)

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["subsistema", "nombre_original", "nombre_normalizado", "primer_periodo",
                    "ultimo_periodo", "n_periodos", "primer_periodo_con_datos",
                    "ultimo_periodo_con_datos", "n_cuadros", "cuadros"])
        for (subsistema, name), rec in sorted(seen.items()):
            per = sorted(rec["periodos"])
            con_datos = sorted(rec["periodos_con_datos"]) or [""]
            w.writerow([subsistema, name, norm(name), per[0], per[-1], len(per),
                        con_datos[0], con_datos[-1], len(rec["codigos"]),
                        " ".join(sorted(rec["codigos"]))])
    with open(NOTES_CSV, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["subsistema", "nota", "primer_periodo", "ultimo_periodo", "cuadros"])
        for (subsistema, note), rec in sorted(seen_notes.items()):
            per = sorted(rec["periodos"])
            w.writerow([subsistema, note, per[0], per[-1], " ".join(sorted(rec["codigos"]))])
    print(f"{len(files)} archivos, {len(seen)} variantes, {len(seen_notes)} notas, "
          f"{errors} errores -> {OUT_CSV.parent}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
