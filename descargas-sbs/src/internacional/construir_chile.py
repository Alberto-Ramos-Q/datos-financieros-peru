"""Construye la serie de concentración bancaria de Chile (dic-2015 a dic-2025) desde la CMF.

Lee los reportes mensuales de diciembre descargados por `descargar_chile.py`
(`data/raw/internacional/chile/`) y escribe:

- `data/processed/internacional/chile_entidades.csv`: un registro por banco, año y variable
  (colocaciones brutas totales y depósitos totales, en MM$ tal como vienen).
- `data/processed/internacional/chile_concentracion.csv`: n, CR4, CR5, IHH y peso de
  BancoEstado por año, variable y variante (`con_estatales` / `sin_estatales`).

Dos bases contables:
- `consolidado` (2015-2025, colocaciones y depósitos): el reporte mensual en Excel.
- `individual` (2022-2025, solo colocaciones): archivo b2 de los zip «Balance y Estado de
  Situación Bancos» (estado de situación financiera individual). Antes de 2022 los zip no traen
  b2, y el b2 no trae depósitos. Ojo: la base individual excluye todas las filiales, también las
  domésticas (Promotora CMR Falabella, por ejemplo), no solo las del exterior.

Lectura por rótulo, nunca por posición fija:
- la hoja de activos se ubica por su título («PRINCIPALES ACTIVOS CONSOLIDADOS POR
  INSTITUCIONES») y la de pasivos por «PRINCIPALES PASIVOS CONSOLIDADOS POR INSTITUCIONES»;
- la fila de encabezado es la que dice «Instituciones»; la columna de bancos, esa misma;
- la columna de cada variable se elige por la ruta de rótulos de su encabezado:
  colocaciones = «Colocaciones» (formato 2015-2021) o «Colocaciones / Total» (2022 en adelante);
  depósitos = «Pasivos / Depósitos / Total» (2015-2021) o «Depósitos totales / Total» (2022+);
- los bancos son las filas entre el encabezado y la fila «Sistema Bancario».

Controles (el script se detiene si alguno falla):
- el título de la hoja dice «AL MES DE DICIEMBRE DE <año>» y las cifras son «millones de pesos»;
- la suma de los bancos cuadra con la fila «Sistema Bancario» (tolerancia 1 MM$ por redondeo);
- si dos hojas de activos (o de pasivos) traen la misma variable, sus cifras coinciden;
- no hay bancos repetidos en un año, ni dos años leídos del mismo archivo (sha256);
- hay exactamente una entidad estatal (BancoEstado) por año.

Uso:
    python src/internacional/construir_chile.py
"""
from __future__ import annotations

import csv
import hashlib
import re
import sys
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_DIR / "data" / "raw" / "internacional" / "chile"
MANIFEST_PATH = PROJECT_DIR / "data" / "_control" / "internacional" / "chile_manifest.csv"
OUT_DIR = PROJECT_DIR / "data" / "processed" / "internacional"
OUT_ENTITIES = OUT_DIR / "chile_entidades.csv"
OUT_CONCENTRATION = OUT_DIR / "chile_concentracion.csv"

COUNTRY = "Chile"
UNIT = "MM$"
BASE = "consolidado"
SOURCE_LABEL = ("CMF, Reporte Mensual de Información Financiera del Sistema Bancario "
                "(diciembre de cada año), cifras consolidadas")
SOURCE_LABEL_INDIVIDUAL = ("CMF, Balance y Estado de Situación Bancos (zip en texto, diciembre), "
                           "archivo b2 = estado de situación financiera individual")
STATE_BANK_PATTERN = re.compile(r"^banco del estado de chile$")
TOLERANCE_MM = 1.0  # MM$; los reportes 2015-2021 vienen redondeados a millones

ASSETS_TITLE = "principales activos consolidados por instituciones"
LIABILITIES_TITLE = "principales pasivos consolidados por instituciones"

ENTITY_COLUMNS = ["pais", "anio", "mes", "entidad", "estatal", "variable", "valor", "unidad",
                  "base", "fuente_url"]
CONCENTRATION_COLUMNS = ["pais", "anio", "variable", "variante", "base", "n", "cr4", "cr5",
                         "ihh", "peso_estatal", "fuente", "notas"]


def normalize(text: object) -> str:
    """Minúsculas, sin tildes, sin notas al pie «(1)», «(*)» y con espacios simples."""
    if not isinstance(text, str):
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"\((\d+|\*)\)", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class SheetTable:
    sheet: str
    title: str
    header_row: int
    name_col: int
    first_row: int
    total_row: int
    frame: pd.DataFrame

    def header_path(self, col: int) -> list[str]:
        """Rótulos propios de una columna, de arriba hacia abajo, sin celdas vacías."""
        cells = self.frame.iloc[self.header_row:self.first_row, col]
        return [normalize(v) for v in cells if normalize(v)]

    def entities(self) -> list[tuple[int, str]]:
        rows = []
        for idx in range(self.first_row, self.total_row):
            name = self.frame.iat[idx, self.name_col]
            if isinstance(name, str) and name.strip():
                rows.append((idx, clean_entity_name(name)))
        return rows


def clean_entity_name(name: str) -> str:
    """Quita espacios sobrantes y llamadas a nota al final («Deutsche Bank (Chile) (4)»).

    Solo se quitan paréntesis con números o asterisco; «HSBC Bank (Chile)» queda igual.
    """
    name = re.sub(r"\s+", " ", name).strip()
    return re.sub(r"(\s*\((\d+|\*)\))+$", "", name).strip()


def find_table(frame: pd.DataFrame, sheet: str, title_key: str, year: int) -> SheetTable | None:
    """Ubica título, encabezado «Instituciones» y fila «Sistema Bancario» de una hoja."""
    # El título de una tabla lleva el periodo («... AL MES DE DICIEMBRE DE 2015»). La hoja
    # «Anexos» repite los nombres de las tablas sin periodo: es un índice y se ignora.
    title = None
    for idx in range(min(12, len(frame))):
        for value in frame.iloc[idx]:
            if title_key in normalize(value) and "al mes de" in normalize(value):
                title = normalize(value)
                break
        if title:
            break
    if not title:
        return None
    expected_month = f"al mes de diciembre de {year}"
    if expected_month not in title:
        raise ValueError(f"{sheet}: el título no dice «{expected_month}»: {title!r}")
    # Unidad declarada en las primeras filas.
    head_text = " ".join(normalize(v) for v in frame.iloc[:8].to_numpy().ravel())
    if "cifras en millones de pesos" not in head_text:
        raise ValueError(f"{sheet}: no se encontró «Cifras en millones de pesos»")

    header_row = name_col = None
    for idx in range(len(frame)):
        for col, value in enumerate(frame.iloc[idx]):
            if normalize(value).startswith("instituciones"):
                header_row, name_col = idx, col
                break
        if header_row is not None:
            break
    if header_row is None:
        raise ValueError(f"{sheet}: no se encontró la fila de encabezado «Instituciones»")

    total_row = None
    for idx in range(header_row + 1, len(frame)):
        if normalize(frame.iat[idx, name_col]) == "sistema bancario":
            total_row = idx
            break
    if total_row is None:
        raise ValueError(f"{sheet}: no se encontró la fila «Sistema Bancario»")

    # Primera fila de datos: la primera, bajo el encabezado, con nombre y algún número.
    first_row = None
    for idx in range(header_row + 1, total_row):
        name = frame.iat[idx, name_col]
        numbers = pd.to_numeric(frame.iloc[idx, name_col + 1:], errors="coerce").notna().sum()
        if isinstance(name, str) and name.strip() and numbers > 0:
            first_row = idx
            break
    if first_row is None:
        raise ValueError(f"{sheet}: no hay filas de bancos")
    return SheetTable(sheet, title, header_row, name_col, first_row, total_row, frame)


def is_loans_column(path: list[str]) -> bool:
    """Colocaciones totales: «colocaciones» o «colocaciones / total»."""
    return path in (["colocaciones"], ["colocaciones", "total"])


def is_deposits_column(path: list[str]) -> bool:
    """Depósitos totales: «pasivos / depositos / total» o «depositos totales / total»."""
    return path in (["pasivos", "depositos", "total"], ["depositos totales", "total"],
                    ["depositos", "total"])


VARIABLES = {
    "creditos": (ASSETS_TITLE, is_loans_column),
    "depositos": (LIABILITIES_TITLE, is_deposits_column),
}


def read_variable(sheets: dict[str, pd.DataFrame], year: int, variable: str) -> dict:
    """Lee una variable de todas las hojas que la traen y exige que coincidan."""
    title_key, matcher = VARIABLES[variable]
    readings = []
    for sheet, frame in sheets.items():
        table = find_table(frame, sheet, title_key, year)
        if table is None:
            continue
        cols = [c for c in range(table.name_col + 1, frame.shape[1])
                if matcher(table.header_path(c))]
        if not cols:
            continue
        if len(cols) > 1:
            raise ValueError(f"{year} {sheet}: más de una columna para {variable}: {cols}")
        col = cols[0]
        values = {}
        for idx, name in table.entities():
            raw = frame.iat[idx, col]
            number = pd.to_numeric(raw, errors="coerce")
            if pd.isna(number):
                raise ValueError(f"{year} {sheet}: valor no numérico para {name}: {raw!r}")
            if name in values:
                raise ValueError(f"{year} {sheet}: banco repetido: {name}")
            values[name] = float(number)
        total = float(pd.to_numeric(frame.iat[table.total_row, col]))
        readings.append({"sheet": sheet, "col": col, "path": table.header_path(col),
                         "values": values, "system_total": total, "title": table.title})
    if not readings:
        raise ValueError(f"{year}: no se encontró la columna de {variable}")
    first = readings[0]
    for other in readings[1:]:
        if other["values"].keys() != first["values"].keys() or any(
                abs(other["values"][k] - v) > 1e-6 for k, v in first["values"].items()):
            raise ValueError(f"{year}: {variable} difiere entre {first['sheet']} y {other['sheet']}")
    first["sheets_checked"] = [r["sheet"] for r in readings]
    return first


def load_manifest() -> dict[int, dict[str, dict]]:
    """Último registro del manifest por periodo y tipo de archivo (excel o zip)."""
    with open(MANIFEST_PATH, encoding="utf-8", newline="") as fh:
        rows = [r for r in csv.DictReader(fh) if r["periodo"]]
    out: dict[int, dict[str, dict]] = {}
    for row in rows:
        ext = row["archivo"].rsplit(".", 1)[1].lower()
        kind = "excel" if ext in ("xls", "xlsx") else ext
        if kind == "pdf":
            continue  # estados financieros anuales y filiales: se citan en el informe
        out.setdefault(int(row["periodo"]), {})[kind] = row
    return out


def verified_path(record: dict, seen_hashes: dict[str, str]) -> Path:
    """Ruta del archivo, tras comprobar su sha256 y que no se use dos veces."""
    path = RAW_DIR / record["archivo"]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != record["sha256"]:
        raise ValueError(f"{path.name}: el sha256 no coincide con el manifest")
    if digest in seen_hashes:
        raise ValueError(f"{path.name} y {seen_hashes[digest]} son el mismo archivo")
    seen_hashes[digest] = path.name
    return path


def concentration(values: pd.Series) -> dict:
    """n, CR4, CR5 (en %) e IHH (0 a 10 000) sobre entidades con valor positivo."""
    positive = values[values > 0]
    shares = positive / positive.sum() * 100
    ordered = shares.sort_values(ascending=False)
    return {"n": int(len(positive)), "cr4": ordered.head(4).sum(), "cr5": ordered.head(5).sum(),
            "ihh": float((shares ** 2).sum()), "shares": ordered}


def concentration_rows_for(year: int, variable: str, values: pd.Series, state_name: str,
                           base: str, source: str, note_base: str) -> list[dict]:
    """Filas `con_estatales` y `sin_estatales` de un año, variable y base."""
    zero = [n for n, v in values.items() if v <= 0]
    if zero:
        note_base += f"; sin saldo (excluidas de n): {', '.join(zero)}"
    full = concentration(values)
    state_share = full["shares"].get(state_name, 0.0)
    rank = list(full["shares"].index).index(state_name) + 1
    private = concentration(values.drop(state_name))
    return [
        {"pais": COUNTRY, "anio": year, "variable": variable, "variante": "con_estatales",
         "base": base, "n": full["n"], "cr4": round(full["cr4"], 4), "cr5": round(full["cr5"], 4),
         "ihh": round(full["ihh"], 2), "peso_estatal": round(state_share, 4), "fuente": source,
         "notas": note_base + f"; incluye a BancoEstado (puesto {rank})"},
        {"pais": COUNTRY, "anio": year, "variable": variable, "variante": "sin_estatales",
         "base": base, "n": private["n"], "cr4": round(private["cr4"], 4),
         "cr5": round(private["cr5"], 4), "ihh": round(private["ihh"], 2), "peso_estatal": None,
         "fuente": source,
         "notas": note_base + f"; excluye a BancoEstado (su peso en el total con estatales "
                  f"es {state_share:.2f} %)"},
    ]


# --- Base individual: archivos de texto b1 (consolidado) y b2 (individual) de la CMF ----------
# Según `metadata/documentacion.pdf` del zip (CMF): b1 = «Estado de situación financiera
# consolidado», b2 = «Estado de situación financiera individual»; columnas: código de 9 dígitos
# y cuatro montos en pesos (moneda chilena no reajustable, reajustable por IPC, reajustable por
# tipo de cambio y moneda extranjera). El b2 solo trae colocaciones (modelo_mb2.txt), no
# depósitos, y aparece desde los archivos de 2022 (nuevo Compendio de Normas Contables).
TOTAL_LOANS_CODE = "500000000"  # «TOTAL COLOCACIONES» (rubro 50000)
SYSTEM_CODE = "999"


def read_text_statement(raw: bytes) -> tuple[str, str, dict[str, float]]:
    """Lee un archivo b1/b2: devuelve (código de banco, razón social, {cuenta: monto en $})."""
    lines = raw.decode("cp1252").splitlines()
    head = lines[0].split("\t")
    code = head[0].strip()
    name = head[1].strip() if len(head) > 1 else ""
    accounts: dict[str, float] = {}
    for line in lines[1:]:
        parts = [p.strip() for p in line.split("\t") if p.strip()]
        if len(parts) < 2:
            continue
        if parts[0] in accounts:
            raise ValueError(f"Cuenta repetida {parts[0]} en el archivo del banco {code}")
        accounts[parts[0]] = sum(float(p.replace(",", ".")) for p in parts[1:])
    return code, name, accounts


def read_individual_loans(zip_path: Path, periodo: int) -> dict[str, dict]:
    """Total de colocaciones por banco en b1 y b2 (en MM$), indexado por código CMF."""
    banks: dict[str, dict] = {}
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.namelist():
            match = re.match(r"^(b[12])(\d{6})(\d{3})\.txt$", member.rsplit("/", 1)[-1], re.I)
            if not match:
                continue
            kind, file_period, code = match.group(1).lower(), int(match.group(2)), match.group(3)
            if file_period != periodo:
                raise ValueError(f"{member}: periodo {file_period} distinto de {periodo}")
            bank_code, name, accounts = read_text_statement(archive.read(member))
            if bank_code.zfill(3) != code:
                raise ValueError(f"{member}: el código interno {bank_code} no coincide")
            if TOTAL_LOANS_CODE not in accounts:
                raise ValueError(f"{member}: falta la cuenta {TOTAL_LOANS_CODE}")
            entry = banks.setdefault(code, {"nombre_cmf": name})
            entry[kind] = accounts[TOTAL_LOANS_CODE] / 1e6
    return banks


def build_individual(year: int, path: Path,
                     consolidated: pd.Series) -> tuple[pd.Series, list[dict], dict]:
    """Colocaciones individuales por banco, con los nombres del reporte consolidado.

    El nombre se asigna emparejando el total consolidado del b1 con la cifra del Excel
    (diferencia < 1 MM$, emparejamiento único). Así se controla, de paso, que el b1 y el Excel
    digan lo mismo.
    """
    banks = read_individual_loans(path, year * 100 + 12)
    system = banks.pop(SYSTEM_CODE, None)
    if system is None or "b2" not in system or "b1" not in system:
        raise ValueError(f"{year}: el zip no trae b1/b2 del sistema (código 999)")
    individual, used, matches = {}, set(), []
    for code, entry in sorted(banks.items()):
        if "b1" not in entry or "b2" not in entry:
            raise ValueError(f"{year}: el banco {code} no tiene b1 y b2")
        candidates = [n for n, v in consolidated.items() if abs(v - entry["b1"]) < TOLERANCE_MM]
        if len(candidates) != 1 or candidates[0] in used:
            raise ValueError(f"{year}: no se pudo emparejar el banco {code} ({entry['nombre_cmf']})")
        used.add(candidates[0])
        individual[candidates[0]] = entry["b2"]
        matches.append({"anio": year, "codigo_cmf": code, "nombre_cmf": entry["nombre_cmf"],
                        "entidad": candidates[0], "b1_consolidado": entry["b1"],
                        "b2_individual": entry["b2"], "diferencia": entry["b1"] - entry["b2"]})
    missing = set(consolidated.index) - used
    if missing:
        raise ValueError(f"{year}: bancos del Excel sin b2: {missing}")
    values = pd.Series(individual)
    diff = values.sum() - system["b2"]
    if abs(diff) > TOLERANCE_MM:
        raise ValueError(f"{year}: suma b2 {values.sum():,.0f} vs sistema {system['b2']:,.0f}")
    if abs(consolidated.sum() - system["b1"]) > TOLERANCE_MM:
        raise ValueError(f"{year}: el b1 del sistema no cuadra con el Excel")
    control = {"anio": year, "variable": "creditos", "base": "individual",
               "hoja": path.name, "n_filas": len(values), "suma_bancos": values.sum(),
               "sistema_bancario": system["b2"], "diferencia": diff}
    return values, matches, control


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    manifest = load_manifest()
    entity_rows, concentration_rows, control_rows, match_rows = [], [], [], []
    seen_hashes: dict[str, str] = {}

    for periodo in sorted(manifest):
        year, month = divmod(periodo, 100)
        if month != 12 or not 2015 <= year <= 2025:
            continue
        record = manifest[periodo]["excel"]
        path = verified_path(record, seen_hashes)
        sheets = pd.read_excel(path, sheet_name=None, header=None)
        index_text = " ".join(normalize(v) for f in sheets.values() for v in f.to_numpy().ravel()
                              if isinstance(v, str) and "provisori" in v.lower())
        provisional = "es provisoria" in index_text
        # Fecha de actualización que la CMF imprime en la hoja «Anexos» («Act.: 08/03/2016»).
        update_stamps = sorted({m.group(1) for f in sheets.values() for v in f.to_numpy().ravel()
                                if isinstance(v, str)
                                for m in [re.search(r"Act\.?:\s*([\d/]+(?:\s+[\d:]+)?)", v)] if m})
        note_base = (f"Archivo {record['archivo_original']}; "
                     f"{'reporte provisorio según la CMF; ' if provisional else ''}"
                     f"{'actualizado ' + ' / '.join(update_stamps) + '; ' if update_stamps else ''}"
                     f"suma de bancos = fila «Sistema Bancario»; entidades con valor > 0")

        per_year = {}
        for variable in VARIABLES:
            reading = read_variable(sheets, year, variable)
            values = pd.Series(reading["values"])
            state = [name for name in values.index if STATE_BANK_PATTERN.match(normalize(name))]
            if len(state) != 1:
                raise ValueError(f"{year}: se esperaba un BancoEstado y hay {state}")
            bank_sum = values.sum()
            diff = bank_sum - reading["system_total"]
            if abs(diff) > TOLERANCE_MM:
                raise ValueError(f"{year} {variable}: suma de bancos {bank_sum:,.0f} vs "
                                 f"Sistema Bancario {reading['system_total']:,.0f}")
            control_rows.append({"anio": year, "variable": variable, "base": BASE,
                                 "hoja": reading["sheet"],
                                 "hojas_cotejadas": "; ".join(reading["sheets_checked"]),
                                 "rotulo": " / ".join(reading["path"]),
                                 "n_filas": len(values), "suma_bancos": bank_sum,
                                 "sistema_bancario": reading["system_total"], "diferencia": diff,
                                 "provisorio": provisional,
                                 "actualizado": " / ".join(update_stamps)})
            per_year[variable] = (values, state[0])
            for name, value in values.items():
                entity_rows.append({"pais": COUNTRY, "anio": year, "mes": 12, "entidad": name,
                                    "estatal": name == state[0], "variable": variable,
                                    "valor": value, "unidad": UNIT, "base": BASE,
                                    "fuente_url": record["url"]})
            concentration_rows += concentration_rows_for(year, variable, values, state[0], BASE,
                                                         SOURCE_LABEL, note_base)

        # Base individual: solo colocaciones y solo si el zip del año trae archivos b2.
        zip_record = manifest[periodo].get("zip")
        if zip_record is None:
            continue
        zip_path = verified_path(zip_record, seen_hashes)
        with zipfile.ZipFile(zip_path) as archive:
            has_b2 = any(re.match(r"^b2\d{9}\.txt$", m.rsplit("/", 1)[-1], re.I)
                         for m in archive.namelist())
        if not has_b2:
            continue
        loans, state_name = per_year["creditos"]
        values, matches, control = build_individual(year, zip_path, loans)
        match_rows += matches
        control_rows.append(control)
        for name, value in values.items():
            entity_rows.append({"pais": COUNTRY, "anio": year, "mes": 12, "entidad": name,
                                "estatal": name == state_name, "variable": "creditos",
                                "valor": value, "unidad": UNIT, "base": "individual",
                                "fuente_url": zip_record["url"]})
        note = (f"Archivo {zip_record['archivo_original']} (b2 = estado de situación financiera "
                f"individual, cuenta 500000000 «TOTAL COLOCACIONES», suma de las 4 columnas de "
                f"moneda); suma de bancos = sistema (código 999); entidades con valor > 0; "
                f"OJO: la base individual excluye todas las filiales, también las domésticas "
                f"(p. ej. Promotora CMR Falabella)")
        concentration_rows += concentration_rows_for(year, "creditos", values, state_name,
                                                     "individual", SOURCE_LABEL_INDIVIDUAL, note)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df_entities = pd.DataFrame(entity_rows, columns=ENTITY_COLUMNS)
    dup = df_entities.duplicated(["anio", "variable", "base", "entidad"])
    if dup.any():
        raise ValueError(f"Entidades duplicadas: {df_entities[dup]}")
    df_conc = pd.DataFrame(concentration_rows, columns=CONCENTRATION_COLUMNS)
    df_entities.to_csv(OUT_ENTITIES, index=False, encoding="utf-8")
    df_conc.to_csv(OUT_CONCENTRATION, index=False, encoding="utf-8")

    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 20)
    print("CONTROLES")
    print(pd.DataFrame(control_rows).to_string(index=False))
    print("\nCONSOLIDADO (b1) FRENTE A INDIVIDUAL (b2), COLOCACIONES EN MM$")
    df_match = pd.DataFrame(match_rows)
    if not df_match.empty:
        df_match["pct_fuera"] = df_match["diferencia"] / df_match["b1_consolidado"] * 100
        print(df_match.round(1).to_string(index=False))
    print("\nCONCENTRACIÓN")
    print(df_conc.drop(columns=["fuente", "notas"]).to_string(index=False))
    print(f"\nEscrito: {OUT_ENTITIES}\nEscrito: {OUT_CONCENTRATION}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


