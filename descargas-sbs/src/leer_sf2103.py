"""Lee la tabla «Sistema Financiero: Estructura» del SF-2103 y arma la serie de deudores únicos.

Entrada: `data/raw/sf2103/SF-2103-mmAAAA.PDF` (ver `src/descargar_sf2103.py`).
Salida:
    data/processed/sf2103_deudores.parquet
    data/processed/_control_sf2103/archivos.csv      un registro por PDF: página, filas o motivo
    data/processed/_control_sf2103/validacion.csv    reglas de consistencia por periodo
    data/processed/_control_sf2103/var_anual.csv     var. % anual publicada vs. calculada con t−12
    data/processed/_control_sf2103/cruce_boletin.csv subsistemas vs. total de «deudores-tipo-credito»

La tabla es la primera del PDF (sección 1, «Créditos y depósitos del sistema financiero»). Filas:
Empresas de Operaciones Múltiples (consolidado de los cinco subsistemas del proyecto), cada
subsistema, Banca Estatal (Banco de la Nación y Agrobanco) y Sistema Financiero (total). Columnas:
número de empresas, activos, créditos y depósitos (monto, part. %, var. % anual) y «Número de
Deudores» (número, part. % y, desde 2020, var. % anual). La columna de deudores aparece en la
edición de dic-2019; las anteriores no la tienen y quedan en `archivos.csv` como «sin_deudores».

Extracción: con PyMuPDF (`pymupdf`) se leen las palabras con su posición; nada se ubica por
número de fila. La columna de deudores es la que queda bajo la cabecera «Número» de «Deudores»
(cifras alineadas a la derecha); la de empresas, bajo «Empresas». Los miles vienen con espacio
(«7 239 591», hasta 2021) o con coma («9,698,756», 2025-2026): los grupos de 3 dígitos contiguos
se unen en una sola cifra.

Columnas de salida:
    periodo | grupo_original | grupo | nivel | numero_empresas | deudores
    | participacion_publicada | var_anual_publicada | nota_definicion | definicion | archivo
- `grupo_original`: rótulo tal como sale (sin las llamadas «1/», «2/»).
- `grupo`: subsistema del proyecto (banca-multiple, empresas-financieras, cajas-municipales,
  cajas-rurales, empresas-credito) o agregado (operaciones-multiples, banca-estatal,
  sistema-financiero) o entidad (banco-nacion, agrobanco). Las EDPYME se mapean a empresas-credito.
- `nivel`: subsistema | agregado | entidad | total.
- `nota_definicion`: texto de la llamada al pie de «Deudores»; `definicion`: resumen
  (`consolida_por_tipo_empresa` hasta 2021, `unico_en_sistema` en 2025-2026).

Tablas en imagen: si la página del cuadro no tiene texto (set-2022), el lector usa las filas
de `config/sf2103_transcripcion.csv` (transcritas a mano, columna `origen` =
`transcripcion_manual`); si falta la transcripción, el archivo queda con error.

Validación (`validacion.csv`; el script devuelve 1 si algo falla):
- Consolidación: Operaciones Múltiples ≤ suma de los cinco subsistemas y ≥ el mayor de ellos;
  Operaciones Múltiples ≤ Sistema Financiero ≤ Operaciones Múltiples + Banca Estatal.
- La participación publicada se reproduce con la cifra leída (prueba de lectura celda a celda)
  y dice qué base usa: `suma_sin_consolidar` (suma de deudores de los grupos, hasta mar-2026) o
  `sistema_consolidado` (desde jun-2026, cambio de la llamada al pie).
- Cruce con el boletín: cada subsistema debe ser igual al total de su cuadro mensual de deudores
  (`deudores-tipo-credito`). Única diferencia: EC 2022-03 (`DIFERENCIAS_CONOCIDAS`).
- `var_anual.csv` / `var_anual_cuadra_eom_sf` es informativo: hasta jun-2024 la var. % anual
  publicada se reproduce con los niveles publicados; desde set-2024 ya no, porque la llamada 1/
  pasó a calcularla «con las entidades comprendidas en cada tipo de licencia en el periodo de
  análisis» (perímetro actual aplicado al año anterior).
- Observación (no regla): en dic-2019 Banca Estatal > BN + Agrobanco (así viene en el PDF).

Uso:
    python -P src/leer_sf2103.py
"""
from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

import pandas as pd
import pymupdf

PROJECT_DIR = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_DIR / "data" / "raw" / "sf2103"
OUT_FILE = PROJECT_DIR / "data" / "processed" / "sf2103_deudores.parquet"
CONTROL_DIR = PROJECT_DIR / "data" / "processed" / "_control_sf2103"
TRANSCRIPCION = PROJECT_DIR / "config" / "sf2103_transcripcion.csv"
BOLETIN_DEUDORES = PROJECT_DIR / "data" / "processed" / "boletin" / "deudores-tipo-credito.parquet"

# Diferencias con el boletín revisadas a mano: errores de origen, no del lector.
DIFERENCIAS_CONOCIDAS = {
    (202203, "empresas-credito"): (
        "SF-2103 mar-2022 dice 173 226; C-4226-ma2022 dice 175 738, con cifras por entidad idénticas "
        "a las de C-4226-ab2022 (ambos republicados el 2022-06-09). El Excel de marzo parece traer "
        "los datos de abril."),
}

MONTH_ABBR = ["en", "fe", "ma", "ab", "my", "jn", "jl", "ag", "se", "oc", "no", "di"]
FILE_RE = re.compile(r"SF-2103-([a-z]{2})(\d{4})\.PDF$", re.I)
NUM_RE = re.compile(r"^-?[\d.,]+$")
FOOTNOTE_RE = re.compile(r"^\(?\d/\)?$")
SUBSISTEMAS = ["banca-multiple", "empresas-financieras", "cajas-municipales", "cajas-rurales",
               "empresas-credito"]

# (patrón sobre el rótulo normalizado, grupo, nivel). El primero que calza gana.
GRUPOS = [
    (r"^empresas de operaciones", "operaciones-multiples", "agregado"),  # ma-2024: sin «Múltiples»
    (r"^(banca multiple|empresas bancarias)", "banca-multiple", "subsistema"),
    (r"^empresas financieras", "empresas-financieras", "subsistema"),
    (r"^cajas mun", "cajas-municipales", "subsistema"),       # «Muncipales» en mar-2021
    (r"^cajas rurales", "cajas-rurales", "subsistema"),
    (r"(desarrollo de la pequena|edpyme|empresas de creditos?$)", "empresas-credito", "subsistema"),
    (r"^banca estatal", "banca-estatal", "agregado"),
    (r"^banco de la nacion", "banco-nacion", "entidad"),
    (r"agrobanco|agropecuario", "agrobanco", "entidad"),
    (r"^sistema financiero$", "sistema-financiero", "total"),
]


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", text).strip().lower()


def classify(label: str) -> tuple[str | None, str | None]:
    key = normalize(label)
    for pattern, grupo, nivel in GRUPOS:
        if re.search(pattern, key):
            return grupo, nivel
    return None, None


def period_of(path: Path) -> int:
    m = FILE_RE.search(path.name)
    return int(m.group(2)) * 100 + MONTH_ABBR.index(m.group(1).lower()) + 1


def parse_int(text: str) -> int | None:
    if text == "-":
        return None
    if not re.fullmatch(r"\d{1,3}([ ,.]\d{3})*|\d+", text):
        raise ValueError(f"Cifra entera ilegible: {text!r}")
    return int(re.sub(r"[ ,.]", "", text))


def parse_decimal(text: str) -> float | None:
    if text in ("-", ""):
        return None
    return float(text.replace(",", "."))


def merge_cells(tokens: list[tuple]) -> list[tuple]:
    """Une los grupos de miles separados por espacio: ('7',x) ('239',x) ('591',x) -> '7 239 591'."""
    cells: list[list] = []
    for x0, x1, t in tokens:
        if (cells and re.fullmatch(r"\d{3}", t) and x0 - cells[-1][1] < 5
                and re.fullmatch(r"-?\d{1,3}( \d{3})*", cells[-1][2])):
            cells[-1][1], cells[-1][2] = x1, f"{cells[-1][2]} {t}"
        else:
            cells.append([x0, x1, t])
    return [tuple(c) for c in cells]


def find_deudores_header(words: list) -> tuple | None:
    """Cabecera «Deudores» de la tabla con su subcabecera «Número» justo debajo.

    Exigir el «Número» descarta la palabra «deudores» del texto o de las notas al pie.
    """
    for w in words:
        if normalize(w[4]).startswith("deudores") and w[0] > 450:
            below = [n for n in words if normalize(n[4]) == "numero" and 0 < n[1] - w[1] < 40
                     and n[2] > w[0] - 30 and n[0] < w[2] + 10]
            if below:
                return w, below[0]
    return None


def find_structure_page(doc) -> tuple[int, list] | None:
    """Página con el título «Estructura» y la cabecera «Deudores / Número» de la tabla."""
    for i, page in enumerate(doc):
        words = page.get_text("words")
        has_title = any(normalize(w[4]).startswith("estructura") for w in words)
        if has_title and find_deudores_header(words):
            return i, words
    return None


def find_image_table(doc) -> int | None:
    """Página con el título «Sistema Financiero: Estructura» pero sin texto de la tabla (imagen).

    Pasa en set-2022: el cuadro se pegó como imagen. Las ediciones de 2010 a set-2019 tienen
    otro formato (número de empresas y activos, sin deudores) y no llevan ese título.
    """
    for i, page in enumerate(doc):
        words = page.get_text("words")
        fin_y = {round(w[1]) for w in words if normalize(w[4]) == "financiero:"}
        title = [w for w in words if normalize(w[4]).startswith("estructura")
                 and any(abs(round(w[1]) - y) <= 2 for y in fin_y)]
        fuente = [w for w in words if normalize(w[4]).startswith("fuente")]
        if not (title and fuente and page.get_images()):
            continue
        # Entre el título y «Fuente:» no hay ninguna palabra: la tabla es una imagen.
        between = [w for w in words if title[0][3] + 2 < w[1] < fuente[0][1] - 2]
        if not between:
            return i
    return None


def read_transcription(path: Path, periodo: int) -> list[dict]:
    """Filas transcritas a mano de una tabla en imagen (mismas columnas que la salida)."""
    if not TRANSCRIPCION.exists():
        return []
    t = pd.read_csv(TRANSCRIPCION, encoding="utf-8")
    t = t[t["periodo"] == periodo]
    out = []
    for _, r in t.iterrows():
        grupo, nivel = classify(r["grupo_original"])
        out.append({
            "periodo": periodo, "grupo_original": r["grupo_original"], "grupo": grupo, "nivel": nivel,
            "numero_empresas": None if pd.isna(r["numero_empresas"]) else int(r["numero_empresas"]),
            "deudores": int(r["deudores"]),
            "participacion_publicada": None if pd.isna(r["participacion_publicada"]) else float(r["participacion_publicada"]),
            "var_anual_publicada": None if pd.isna(r["var_anual_publicada"]) else float(r["var_anual_publicada"]),
            "nota_definicion": r["nota_definicion"], "definicion": classify_definition(r["nota_definicion"]),
            "archivo": path.name, "origen": "transcripcion_manual",
        })
    return out


def extract_footnote(words: list, marker: str, fuente_y: float) -> str:
    """Texto de la llamada `marker` («3/») al pie de la tabla, con sus líneas de continuación."""
    rows: dict[int, list] = {}
    for x0, y0, x1, y1, t, *_ in words:
        if y0 >= fuente_y - 2:
            rows.setdefault(round((y0 + y1) / 2), []).append((x0, t))
    lines = [(y, [t for _, t in sorted(ws)]) for y, ws in sorted(rows.items())]
    # Las llamadas a veces quedan 1-2 pt arriba de su texto: se juntan filas muy próximas.
    merged: list[tuple[float, list]] = []
    for y, toks in lines:
        if merged and y - merged[-1][0] <= 3:
            merged[-1] = (y, merged[-1][1] + toks)
        else:
            merged.append((y, toks))
    out, last_y = [], None
    for y, toks in merged:
        first = toks[0]
        if out:
            if re.fullmatch(r"\d/", first) or first.lower().startswith("nota") or y - last_y > 14:
                break
            out.append(" ".join(toks))
            last_y = y
        elif first == marker or first.startswith(marker):
            out.append(" ".join(toks))
            last_y = y
    return re.sub(r"\s+", " ", " ".join(out)).strip()


def classify_definition(note: str) -> str:
    key = normalize(note)
    if "una sola vez" in key:
        return "unico_en_sistema"
    if "consolida los deudores por tipo de empresa" in key or "como unico si" in key:
        return "consolida_por_tipo_empresa"
    return "otra"


def read_pdf(path: Path) -> tuple[list[dict], dict]:
    periodo = period_of(path)
    info = {"archivo": path.name, "periodo": periodo, "pagina": None, "filas": 0, "estado": "", "detalle": ""}
    with pymupdf.open(path) as doc:
        found = find_structure_page(doc)
        if found is None:
            image_page = find_image_table(doc)
            if image_page is not None:
                info.update(pagina=image_page + 1, estado="tabla_en_imagen",
                            detalle="La tabla es una imagen sin texto: se usa config/sf2103_transcripcion.csv")
            else:
                info["estado"] = "sin_deudores"
                info["detalle"] = "No hay tabla «Sistema Financiero: Estructura» con columna «Deudores»"
            return [], info
        page_no, words = found
    info["pagina"] = page_no + 1
    words = [w[:5] for w in words]

    # Cabeceras (las de la tabla están a la derecha del rótulo, x0 > 150).
    deud, num_hdr = find_deudores_header(words)
    m = re.search(r"(\d)/", deud[4])
    marker = f"{m.group(1)}/" if m else None
    if marker is None:
        near = [w for w in words if re.fullmatch(r"\d/", w[4]) and abs(w[1] - deud[1]) < 15
                and deud[0] - 5 <= w[0] <= deud[2] + 30]
        marker = near[0][4] if near else None
    header_band = [w for w in words if abs(w[1] - deud[1]) < 45]
    emp_hdr = next(w for w in header_band if normalize(w[4]) == "empresas" and w[0] > 150)
    part_hdr = [w for w in header_band if normalize(w[4]) == "part.%" and w[0] > num_hdr[2] - 5]
    var_hdr = [w for w in header_band if normalize(w[4]) == "var.%" and w[0] > num_hdr[2] - 5]
    fuente = next(w for w in words if normalize(w[4]).startswith("fuente") and w[1] > deud[1])
    # La tabla empieza bajo la última línea de cabecera («anual», «(Millones S/)», «Part.%»…).
    header_words = [w for w in header_band if w[0] > 150 and normalize(w[4]) in
                    {"anual", "(millones", "s/)", "part.%", "numero", "empresas", "monto", "var.%"}]
    top, bottom = max(w[3] for w in header_words), fuente[1]

    def center(w):
        return (w[0] + w[2]) / 2

    # Filas de la tabla: palabras entre la cabecera y «Fuente», agrupadas por altura (±3 pt).
    body = sorted((w for w in words if top < (w[1] + w[3]) / 2 < bottom), key=lambda w: (w[1] + w[3]) / 2)
    rows: list[list] = []
    for w in body:
        yc = (w[1] + w[3]) / 2
        if rows and yc - rows[-1][0] <= 3:
            rows[-1][1].append(w)
        else:
            rows.append([yc, [w]])

    out = []
    for _, ws in rows:
        ws = sorted(ws, key=lambda w: w[0])
        label = " ".join(re.sub(r"(\d/|\*)+$", "", w[4]) for w in ws
                         if not NUM_RE.match(w[4]) and w[4] != "-" and not FOOTNOTE_RE.match(w[4]))
        label = re.sub(r"\s+", " ", label).strip()
        nums = [(w[0], w[2], w[4]) for w in ws if (NUM_RE.match(w[4]) or w[4] == "-") and w[0] > 200]
        if not nums:
            continue
        if not label:
            raise ValueError(f"Fila con cifras y sin rótulo: {nums}")
        cells = merge_cells(nums)

        def pick(hdr, tol=25):
            best = min(cells, key=lambda c: abs((c[0] + c[1]) / 2 - center(hdr)))
            return best[2] if abs((best[0] + best[1]) / 2 - center(hdr)) <= tol else None

        deud_txt = pick(num_hdr)
        if deud_txt is None:
            raise ValueError(f"Sin cifra bajo «Número de Deudores» en «{label}»")
        grupo, nivel = classify(label)
        out.append({
            "periodo": periodo, "grupo_original": label, "grupo": grupo, "nivel": nivel,
            "numero_empresas": parse_int(pick(emp_hdr) or "-"),
            "deudores": parse_int(deud_txt),
            "participacion_publicada": parse_decimal(pick(part_hdr[0], 15) or "") if part_hdr else None,
            "var_anual_publicada": parse_decimal(pick(var_hdr[0], 15) or "") if var_hdr else None,
            "archivo": path.name, "origen": "texto_pdf",
        })
    note = extract_footnote(words, marker, fuente[1]) if marker else ""
    for r in out:
        r["nota_definicion"] = note
        r["definicion"] = classify_definition(note)
    unknown = [r["grupo_original"] for r in out if r["grupo"] is None]
    if unknown:
        raise ValueError(f"Rótulos sin grupo: {unknown}")
    info.update(filas=len(out), estado="ok", detalle=f"llamada {marker}: {note[:120]}")
    return out, info


def validate(df: pd.DataFrame) -> pd.DataFrame:
    """Reglas por periodo. Los deudores se consolidan: los agregados son ≤ la suma de sus partes."""
    rows = []
    for periodo, g in df.groupby("periodo"):
        v = g.set_index("grupo")["deudores"]
        sub = v.reindex(SUBSISTEMAS)
        s5, eom, sf = sub.sum(), v.get("operaciones-multiples"), v.get("sistema-financiero")
        be, bn, agro = v.get("banca-estatal"), v.get("banco-nacion"), v.get("agrobanco")
        checks = {
            "cinco_subsistemas_presentes": sub.notna().all(),
            "eom_menor_igual_suma_subsistemas": eom <= s5,
            "eom_mayor_igual_max_subsistema": eom >= sub.max(),
            "eom_menor_igual_sistema": eom <= sf,
            "sistema_menor_igual_eom_mas_estatal": sf <= eom + be,
            "estatal_mayor_igual_bn": be >= bn,
        }
        # Observación, no regla: en dic-2019 Banca Estatal (601 116) supera a BN + Agrobanco
        # (600 177); la fila del BN lleva la llamada «1/ Sólo considera los créditos de consumo e
        # hipotecario». Es así en el PDF.
        obs = {"estatal_menor_igual_bn_mas_agrobanco": be <= bn + agro}
        # Base de la participación publicada: el total consolidado o la suma sin consolidar.
        agregado = s5 + bn + agro
        base = set()
        for _, r in g[g["nivel"].isin(["subsistema", "entidad"])].iterrows():
            p = r["participacion_publicada"]
            if pd.isna(p):
                continue
            ok_sf = abs(r["deudores"] / sf * 100 - p) <= 0.051
            ok_ag = abs(r["deudores"] / agregado * 100 - p) <= 0.051
            if ok_sf != ok_ag:      # si ambas bases dan lo mismo (cifras chicas), no informa
                base.add("sistema_consolidado" if ok_sf else "suma_sin_consolidar")
            elif not ok_sf:
                base.add("no_cuadra")
        checks["participacion_cuadra"] = "no_cuadra" not in base and bool(base)
        rows.append({"periodo": periodo, **{k: bool(x) for k, x in checks.items()},
                     "todas_ok": all(bool(x) for x in checks.values()),
                     **{f"obs_{k}": bool(x) for k, x in obs.items()},
                     "base_participacion": "|".join(sorted(base)),
                     "suma_subsistemas": int(s5), "operaciones_multiples": eom,
                     "ratio_duplicacion": round(s5 / eom, 4), "sistema_financiero": sf})
    out = pd.DataFrame(rows)
    var = annual_change(df)
    agg = var[var["grupo"].isin(["operaciones-multiples", "sistema-financiero"])]
    flag = agg.groupby("periodo")["cuadra"].all()
    out["var_anual_cuadra_eom_sf"] = out["periodo"].map(flag).astype("object")
    return out


def annual_change(df: pd.DataFrame) -> pd.DataFrame:
    """Var. % anual publicada frente a la calculada con el nivel publicado doce meses antes.

    Tolerancia: la variación viene con un decimal, así que «cuadra» si |calculada − publicada|
    ≤ 0,051 pp. Solo hay pares cuando existe la edición t−12. En los subsistemas puede no cuadrar
    por diseño: desde 2025 la SBS calcula la variación con las entidades de cada tipo de licencia
    en el mes de análisis (llamada 1/), y hubo conversiones de financieras a bancos.
    """
    lvl = df.set_index(["periodo", "grupo"])["deudores"].astype(float)
    rows = []
    for _, r in df.iterrows():
        key = (r["periodo"] - 100, r["grupo"])
        if pd.isna(r["var_anual_publicada"]) or key not in lvl.index:
            continue
        calc = (r["deudores"] / lvl[key] - 1) * 100
        rows.append({"periodo": r["periodo"], "grupo": r["grupo"], "deudores": r["deudores"],
                     "deudores_t_12": int(lvl[key]), "var_calculada": round(calc, 3),
                     "var_publicada": r["var_anual_publicada"],
                     "cuadra": abs(calc - r["var_anual_publicada"]) <= 0.051})
    return pd.DataFrame(rows, columns=["periodo", "grupo", "deudores", "deudores_t_12",
                                       "var_calculada", "var_publicada", "cuadra"])


def cross_check_boletin(df: pd.DataFrame) -> pd.DataFrame:
    """Compara cada subsistema con el total del cuadro mensual de deudores por tipo de crédito."""
    if not BOLETIN_DEUDORES.exists():
        return pd.DataFrame()
    b = pd.read_parquet(BOLETIN_DEUDORES, columns=["periodo", "subsistema", "es_total", "apertura", "valor"])
    b = b[b["es_total"] & (b["apertura"] == "total")].rename(columns={"subsistema": "grupo", "valor": "boletin"})
    m = df[df["nivel"] == "subsistema"][["periodo", "grupo", "deudores"]].merge(
        b[["periodo", "grupo", "boletin"]], on=["periodo", "grupo"], how="left")
    m["diferencia"] = m["deudores"] - m["boletin"]
    m["explicacion"] = [DIFERENCIAS_CONOCIDAS.get((p, g), "") for p, g in zip(m["periodo"], m["grupo"])]
    return m


def main() -> int:
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(RAW_DIR.glob("SF-2103-*.PDF"), key=period_of)
    rows, infos, errors = [], [], 0
    for path in files:
        try:
            out, info = read_pdf(path)
            if info["estado"] == "tabla_en_imagen":
                out = read_transcription(path, info["periodo"])
                if not out:
                    raise ValueError("Tabla en imagen sin transcripción en config/sf2103_transcripcion.csv")
                info.update(estado="transcrito", filas=len(out))
        except Exception as exc:  # un PDF raro no detiene el resto, pero queda registrado
            out, errors = [], errors + 1
            info = {"archivo": path.name, "periodo": period_of(path), "pagina": None, "filas": 0,
                    "estado": "error", "detalle": str(exc)}
        rows += out
        infos.append(info)
        print(f"{path.name}: {info['estado']} ({info['filas']} filas)")
    pd.DataFrame(infos).to_csv(CONTROL_DIR / "archivos.csv", index=False, encoding="utf-8")
    if not rows:
        print("Sin filas de deudores.")
        return 1
    cols = ["periodo", "grupo_original", "grupo", "nivel", "numero_empresas", "deudores",
            "participacion_publicada", "var_anual_publicada", "nota_definicion", "definicion", "origen", "archivo"]
    df = pd.DataFrame(rows)[cols]
    for c in ("numero_empresas", "deudores"):
        df[c] = df[c].astype("Int64")
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_FILE, index=False)

    val = validate(df)
    val.to_csv(CONTROL_DIR / "validacion.csv", index=False, encoding="utf-8")
    annual_change(df).to_csv(CONTROL_DIR / "var_anual.csv", index=False, encoding="utf-8")
    cruce = cross_check_boletin(df)
    if not cruce.empty:
        cruce.to_csv(CONTROL_DIR / "cruce_boletin.csv", index=False, encoding="utf-8")
    # Sin dato del boletín (mes aún no leído) no es diferencia; se informa aparte.
    bad_cruce = int((cruce["diferencia"].notna() & (cruce["diferencia"] != 0)
                     & (cruce["explicacion"] == "")).sum()) if not cruce.empty else 0
    sin_boletin = int(cruce["boletin"].isna().sum()) if not cruce.empty else 0
    print(f"{len(df)} filas, {df['periodo'].nunique()} periodos -> {OUT_FILE}")
    print(f"Validación: {int(val['todas_ok'].sum())}/{len(val)} periodos sin observaciones; "
          f"cruce con el boletín: {bad_cruce} diferencias sin explicar "
          f"({len(DIFERENCIAS_CONOCIDAS)} conocidas), {sin_boletin} sin dato del boletín")
    return 1 if errors or not val["todas_ok"].all() or bad_cruce else 0


if __name__ == "__main__":
    sys.exit(main())
