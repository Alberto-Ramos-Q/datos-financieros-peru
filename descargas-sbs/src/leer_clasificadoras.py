"""Lee los informes de clasificadoras (PDF de la extranet SBS) y arma la serie de clasificaciones por entidad.

Entrada: data/raw/clasificadoras/indice.csv y los PDF bajados por `descargar_clasificadoras.py pdf`.
Para cada informe se extrae, del texto de las dos primeras páginas (`pdftotext -layout`):
- la clasificación de la ENTIDAD (fortaleza financiera), en la escala de la SBS (Res. SBS 18400-2010):
  A+ … E-. PCR la escribe con prefijo (PEB- → B-); las clasificaciones de instrumentos (AA-.pe, CP-1, etc.) se
  ignoran;
- la perspectiva (Estable, Positiva, Negativa, En desarrollo);
- la fecha de comité.
Cada clasificadora tiene su propio formato, así que hay reglas por clasificadora (ver PATTERNS) y se guarda qué
regla resolvió cada dato. Lo que no se pudo leer queda con `rating` vacío para revisión.

Salidas (data/processed/):
- clasificaciones_informes.parquet / .xlsx: un registro por informe (entidad, clasificadora, periodo de la
  información, comité, clasificación, perspectiva, regla y archivo).
- clasificaciones.parquet: panel entidad × mes con lo conocido en cada mes (el informe cuenta desde el mes de su
  comité y vence a los VIGENCIA_MESES si no se renueva): peor clasificación vigente entre clasificadoras
  (`cl_peor`, `cl_peor_num`, 1 = A+ … 15 = E-), número de clasificadoras, si alguna tiene perspectiva negativa,
  si hubo una rebaja en los últimos 12 meses y el detalle en texto.

Uso: python leer_clasificadoras.py [--muestra CARPETA]   (--muestra: solo prueba las reglas sobre PDFs sueltos)
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parents[1]
RAW = PROJECT_DIR / "data" / "raw" / "clasificadoras"
PROCESSED = PROJECT_DIR / "data" / "processed"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from descargar_clasificadoras import ALIAS_CSV, load_aliases, match_entity  # noqa: E402

GRADES = [f"{l}{s}" for l in "ABCDE" for s in ("+", "", "-")]
GRADE_NUM = {g: i + 1 for i, g in enumerate(GRADES)}
VIGENCIA_MESES = 12
OUTLOOKS = {"estable": "Estable", "positiva": "Positiva", "negativa": "Negativa", "en desarrollo": "En desarrollo",
            "en observacion": "En observación", "observacion": "En observación"}
MONTHS = {m: i + 1 for i, m in enumerate(["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                          "septiembre", "octubre", "noviembre", "diciembre"])}
MONTHS["setiembre"] = 9
MONTHS_ABBR = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8, "set": 9, "sep": 9,
               "oct": 10, "nov": 11, "dic": 12}
G = r"((?-i:[A-E][+-]?))(?![A-Za-z0-9.+-])"  # categoría de entidad (siempre mayúscula, aunque se use re.I)
OUT = r"(estable|positiva|negativa|en desarrollo|en observaci[oó]n)"


def fold(text: str) -> str:
    """Minúsculas sin tildes, para buscar palabras clave (las clasificaciones se leen del texto original)."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def pdf_text(path: Path, pages: int = 3) -> str:
    res = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", "-f", "1", "-l", str(pages), str(path), "-"],
                         capture_output=True, timeout=60)
    return res.stdout.decode("utf-8", "replace")


# ---------------------------------------------------------------- reglas por clasificadora
def _first(patterns: list[tuple[str, str]], text: str, flags=re.I) -> tuple[str | None, str | None]:
    for name, pat in patterns:
        m = re.search(pat, text, flags)
        if m:
            return m.group(1).upper(), name
    return None, None


def rating_moodys(text: str):
    # «Entidad   A-   Estable» en el cuadro de clasificaciones (Moody's Local y Equilibrium); en los informes de
    # Equilibrium la categoría puede quedar una o dos líneas arriba o abajo de la etiqueta.
    lines = text.splitlines()
    for i, line in enumerate(lines):
        # 2017-2019: el cuadro va a la derecha de «Sesión de Comité: …», así que «Entidad» no abre la línea.
        m = re.search(r"(?:^|\s{2,})Entidad\s{2,}" + G + r"(?:\s{2,}(?i:" + OUT + r"))?", line)
        if m:
            return m.group(1), "cuadro Entidad", (m.group(2) or None)
        if not re.match(r"^\s*Entidad\b", line):
            continue
        near = "\n".join(lines[max(i - 2, 0):i + 3])
        m = re.search(r"\(modificada\)(?:\s*|[^\n]*\n\s*)de\s+([A-E][+-]?)\s+a\s+" + G, near)
        if m:
            return m.group(2), "cuadro Entidad (modificada de X a Y)", None, m.group(1)
    # Equilibrium hasta ~2016: el fundamento dice «decidió mantener la categoría B+ asignada como Entidad».
    # «cate-/goría» suele venir cortada por guion al final de la línea.
    m = re.search(r"(?:categor|gor)[ií]a\s+" + G + r"\s+(?:asignada\s+|otorgada\s+)?como\s+Entidad", text)
    if m:
        return m.group(1), "texto «categoría X como Entidad»", None
    # «Historia de Clasificación: Entidad → C- (fecha), ↓ D»: la última flecha es la vigente. El símbolo inicial es
    # un glifo propio de la fuente, por eso se acepta cualquier carácter no alfanumérico. Sin flechas
    # («Entidad B (27.03.98), B+ (29.11.01)») la vigente es la última categoría con fecha. La historia puede
    # seguir en las líneas de abajo, en la misma columna, hasta la etiqueta del instrumento siguiente.
    m = re.search(r"Historia\s+de\s+Clasificaci[oó]n\*?:\s*Entidad[^A-Za-z0-9]{0,6}" + G + r"[^\n]*", text)
    if m:
        seg = m.group(0)
        col = m.start() - (text.rfind("\n", 0, m.start()) + 1)
        for nxt in text[m.end():].splitlines()[1:4]:
            part = nxt[max(col - 2, 0):].strip()
            if not part or re.match(r"[A-Za-zÁÉÍÓÚáéíóú]{3,}", part):
                break
            seg += " " + part
        arrows = re.findall(r"[↓↑]\s*" + G, seg)
        dated = re.findall(G + r"\s*\(\d", seg)
        return (arrows[-1] if arrows else dated[-1] if dated else m.group(1)), "historia de clasificación", None
    for i, line in enumerate(lines):
        if re.match(r"^\s*Entidad\b", line):
            for j in (i + 1, i - 1):
                if 0 <= j < len(lines):
                    m = re.match(r"^\s*" + G + r"(?:\s{2,}|\s*$)", lines[j])
                    if m:
                        return m.group(1), "cuadro Entidad (línea vecina)", None
    g, rule = _first([("texto «categoría X como Entidad»", r"categor[ií]a\s+" + G + r"\s+como\s+Entidad"),
                      ("texto «como Entidad … X»", r"como\s+Entidad[^.]{0,80}?categor[ií]a\s+" + G)], text)
    return g, rule, None


APOYO_LABEL = r"(?:Instituci[oó]n|Fortaleza)"
APOYO_TOKEN = r"(?<![A-Za-z0-9.(])" + G


def _apoyo_box(lines: list[str]):
    # Cuadro «Ratings  Actual  Anterior» en la columna derecha: la fila de la entidad se llama «Institución» o
    # (desde 2025) «Fortaleza Financiera», y su categoría puede estar en la misma línea, justo arriba o justo abajo.
    # Solo se mira la columna del cuadro, porque a la izquierda corre el texto («A diciembre…»).
    for i, line in enumerate(lines[:60]):
        h = re.search(r"Ratings?\s+Actual\s+Anterior", line)
        if not h:
            continue
        col = max(h.start() - 3, 0)
        segs = [ln[col:] for ln in lines[i + 1:i + 14]]
        for k, seg in enumerate(segs):
            if re.search(APOYO_LABEL, seg):
                for j in (k, k - 1, k + 1):
                    if 0 <= j < len(segs):
                        toks = re.findall(APOYO_TOKEN, segs[j])
                        if toks and (j == k or not re.search(r"[a-z]{4,}", segs[j])):
                            return toks[0]
                return None
    return None


def _apoyo_actual_column(lines: list[str]):
    # 2015-2020: «Rating / Actual / Anterior» en la columna izquierda; la categoría actual queda debajo de «Actual»
    # (con la anterior a su derecha). Se lee solo la franja de esa columna.
    for i, line in enumerate(lines[:40]):
        h = re.search(r"Actual\s+Anterior", line)
        if not h:
            continue
        a, b = max(h.start() - 8, 0), h.end() + 6
        cell = r"[A-E][+-]?(?:\s*\(pe\))?"
        for nxt in lines[i + 1:i + 6]:
            # La franja no puede cortar una palabra del texto vecino («En comité» → «E»): se mueven los bordes
            # hasta un espacio.
            lo, hi = a, b
            while 0 < lo < len(nxt) and nxt[lo - 1].isalnum() and nxt[lo].isalnum():
                lo += 1
            while lo < hi < len(nxt) and nxt[hi - 1].isalnum() and nxt[hi].isalnum():
                hi -= 1
            # Puede seguir «NR»/«NM» (no clasificado / no modificado) o una viñeta del texto vecino.
            if re.fullmatch(r"\s*" + cell + r"(?:\s+(?:" + cell + r"|NR|NM))?[^A-Za-z0-9]*", nxt[lo:hi]):
                tok = re.search(APOYO_TOKEN, nxt[lo:hi])
                if tok:
                    return tok.group(1)
        return None
    return None


def _apoyo_stacked(lines: list[str]):
    # Formato 2015-2020: «Rating / Institución» y «Rating Actual / Anterior / Fecha Cambio» en líneas separadas;
    # la categoría actual queda sola en su línea (a veces con la anterior y la fecha del cambio a la derecha).
    for i, line in enumerate(lines[:40]):
        if re.match(r"^\s*Instituci[oó]n\s*$", line):
            for nxt in lines[i + 1:i + 10]:
                m = re.match(r"^\s{4,}" + G + r"(?:\s{2,}|\s*$)", nxt[:60])
                if m:
                    return m.group(1)
    return None


def rating_apoyo(text: str):
    # Fila «Institución (1)   A-   A-» del cuadro de ratings (actual y anterior).
    # La llamada de nota puede venir como «(1)», «1» pegado o « 1» separado (2025-2026: «Institución 1   A   A»).
    m = re.search(r"Instituci[oó]n(?:\s*\(?\d\)?)?\s{2,}" + G, text)
    if m:
        return m.group(1), "fila Institución", None
    m = re.search(r"Fortaleza(?:\s+Financiera)?(?:\s?\d)?\s{2,}" + G, text)
    if m:
        return m.group(1), "fila Fortaleza Financiera", None
    lines = text.splitlines()
    # 2026: la categoría va en la misma línea del título «Ratings» (actual y anterior, o N.R.) y la etiqueta
    # «Fortaleza / Financiera» queda debajo, partida en dos líneas.
    for i, line in enumerate(lines[:30]):
        m = re.search(r"Ratings?\s{2,}" + G + r"(?:\s{2,}(?:" + G + r"|N\.?R\.?))?\s*$", line)
        if m and any(re.search(APOYO_LABEL, nxt) for nxt in lines[i + 1:i + 4]):
            return m.group(1), "título Ratings con categoría", None
    g = _apoyo_box(lines)
    if g:
        return g, "cuadro Ratings", None
    g = _apoyo_actual_column(lines)
    if g:
        return g, "columna Actual", None
    g = _apoyo_stacked(lines)
    if g:
        return g, "cuadro Rating apilado", None
    g, rule = _first([("texto «Institución … X»", r"clasificaci[oó]n\s+de\s+(?:riesgo\s+de\s+)?Instituci[oó]n\s+"
                                                   r"(?:se\s+\w+\s+en|de|en)\s+" + G),
                      ("texto «X … como Institución»", r"\b" + G + r"\s+(?:como|a\s+la)\s+Instituci[oó]n")], text)
    return g, rule, None


def rating_pcr(text: str):
    # Encabezado (antes de «Significado de la clasificación»): la primera fila con categorías de fortaleza
    # financiera (PEA … PEE; las de instrumentos son PEAA, PE1, etc.) es el historial, y su última columna es la
    # vigente. Las filas del cuadro salen desalineadas de sus etiquetas, por eso no se usa la etiqueta.
    head = re.split(r"Significado\s+de\s+la", text, maxsplit=1)[0]
    lines = head.splitlines()
    # Formato 2026: etiqueta «Fortaleza Financiera» y la categoría (con o sin PE) una o dos líneas debajo, en la
    # columna izquierda.
    for i, line in enumerate(lines):
        h = re.search(r"Fortaleza\s+Financiera", line)
        if h and h.start() < 60 and not re.sub(r"Calificaci[oó]n", "", line[:h.start()]).strip():
            cut = h.end() + 10
            for nxt in lines[i + 1:i + 4]:
                m = re.fullmatch(r"\s*(?:PE)?" + G + r"\s*", nxt[:cut])
                if m and not (len(nxt) > cut and nxt[cut].isalnum()):  # no cortar «Estable» → «E»
                    return m.group(1), "cuadro Fortaleza Financiera (debajo)", None
    for i, line in enumerate(lines):
        toks = re.findall(r"(?<![A-Za-z])PE" + G, line)
        # Una línea de prosa («ratificar … Financiera en PEB+, de los Depósitos … en PEA+») no es el historial.
        prose = len(re.findall(r"(?<![A-Za-zÁÉÍÓÚáéíóú])[a-záéíóú]{3,}", line)) >= 4
        if toks and not prose and not re.search(r"Categor[ií]a", line):
            # La perspectiva vigente es la de la última columna: la más a la derecha en las líneas del cuadro.
            outs = [(m.start(), m.group(1)) for nxt in lines[i:i + 4] for m in re.finditer(OUT, nxt, re.I)]
            return (toks[-1], "historial del encabezado (última columna)", (max(outs)[1] if outs else None),
                    (toks[-2] if len(toks) > 1 else None))
    m = re.search(r"^\s*Fortaleza\s+Financiera\s{2,}" + G + r"(?:\s{2,}" + OUT + r")?", head, re.M | re.I)
    if m:  # formato antiguo, sin prefijo PE
        return m.group(1), "cuadro Fortaleza Financiera", (m.group(2) or None)
    flat = re.sub(r"\s+", " ", text)
    g, rule = _first([
        ("texto «de PEX a PEY»", r"de\s+[\"“”']?PE[A-E][+-]?[\"“”']?\s+a\s+[\"“”']?PE" + G),
        ("texto «PEX a/de la Fortaleza Financiera»",
         r"(?:calificaci[oó]n|clasificaci[oó]n|categor[ií]a)\s+(?:de\s+|en\s+)?[\"“”']?PE" + G
         + r"[\"“”']?\s+(?:a|de|para)\s+la\s+Fortaleza\s+Financiera"),
        ("texto «Fortaleza Financiera en PEX»", r"Fortaleza\s+Financiera\s+en\s+PE" + G),
        ("texto «Fortaleza Financiera» de X", r"Fortaleza\s+Financiera[\"“”']?\s+de\s+[\"“”']?" + G + r"[\"“”']?[\s.,]"),
    ], flat)
    return g, rule, None


def rating_microrate(text: str):
    m = re.search(r"CALIFICACI[OÓ]N\s*\n(?:\s*\n)*\s*" + G + r"\s*$", text, re.M)
    if m:
        return m.group(1), "portada CALIFICACIÓN", None
    m = re.search(r"CALIFICACI[OÓ]N[^\n]*\n(?:[^\n]*\n){0,3}?\s*" + G + r"(?:\s|$)", text)
    if m:
        return m.group(1), "bloque CALIFICACIÓN", None
    return None, None, None


PATTERNS = {"moodys-local": rating_moodys, "apoyo": rating_apoyo, "pcr": rating_pcr, "microrate": rating_microrate}


def outlook(text: str, rule_outlook: str | None) -> str | None:
    if rule_outlook:
        return OUTLOOKS.get(fold(rule_outlook))
    # Cuadro con «Perspectiva» y el valor debajo, en la misma columna (Apoyo).
    lines = [fold(x) for x in text.splitlines()]
    for i, line in enumerate(lines):
        for m in re.finditer(r"\bperspectivas?\b", line):
            c = m.start()
            for nxt in lines[i + 1:i + 3]:
                hit = re.match(r"\s*" + fold(OUT), nxt[max(c - 3, 0):c + 25])
                if hit:
                    return OUTLOOKS.get(hit.group(1))
    f = fold(re.sub(r"\s+", " ", text))
    for pat in (r"perspectivas?\s*(?:es|:)?\s*" + OUT, r"con\s+perspectiva\s+" + OUT,
                r"perspectivas?\s+(?:de\s+la\s+clasificacion\s+)?(?:se\s+mantiene|es)\s+" + OUT):
        m = re.search(fold(pat), f)
        if m:
            return OUTLOOKS.get(m.group(1))
    return None


def committee_date(text: str) -> tuple[pd.Timestamp | None, str | None]:
    f = fold(re.sub(r"\s+", " ", text))
    m = re.search(r"fecha\s+de\s+comite\s*:?\s*(\d{1,2})\s+de\s+([a-z]+)\s+(?:de\s+|del\s+)?(\d{4})", f)
    if m and m.group(2) in MONTHS:
        return pd.Timestamp(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1))), "fecha de comité"
    m = re.search(r"comites?\s+de\s+fechas?\s+(\d{1,2})/(\d{1,2})/(\d{2,4})", f)
    if m:
        y = int(m.group(3))
        return pd.Timestamp(y + 2000 if y < 100 else y, int(m.group(2)), int(m.group(1))), "comité dd/mm/aaaa"
    m = re.search(r"fecha\s+de\s+comite\s*:?\s*(\d{1,2})/(\d{1,2})/(\d{4})", f)
    if m:
        return pd.Timestamp(int(m.group(3)), int(m.group(2)), int(m.group(1))), "fecha de comité dd/mm/aaaa"
    m = re.search(r"fecha\s+de\s+comite\s+([a-z]{3})\w*\s+(\d{2,4})", f)
    if m and m.group(1) in MONTHS_ABBR:
        y = int(m.group(2))
        return pd.Timestamp(y + 2000 if y < 100 else y, MONTHS_ABBR[m.group(1)], 1), "fecha de comité (mes)"
    m = re.search(r"sesion\s+de\s+comite[^.]{0,40}?(\d{1,2})\s+de\s+([a-z]+)\s+(?:de\s+|del\s+)?(\d{4})", f)
    if m and m.group(2) in MONTHS:
        return pd.Timestamp(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1))), "sesión de comité"
    return None, None


def parse_report(path: Path, agency: str) -> dict:
    text = pdf_text(path)
    # Las reglas devuelven (categoría, regla, perspectiva) y algunas también la categoría anterior que trae el informe.
    res = PATTERNS[agency](text)
    grade, rule, rule_out = res[:3]
    prev = res[3] if len(res) > 3 and res[3] in GRADE_NUM else None
    grade = grade if grade in GRADE_NUM else None
    comm, comm_rule = committee_date(text)
    return {"rating": grade, "rating_num": GRADE_NUM.get(grade), "regla_rating": rule,
            "rating_anterior_informe": prev if grade else None,
            "perspectiva": outlook(text, rule_out), "fecha_comite": comm, "regla_comite": comm_rule,
            "texto_vacio": int(len(text.strip()) < 200)}


# ---------------------------------------------------------------- serie
def info_period(cod_periodo: str) -> int:
    """La publicación del semestre 01 trae información a diciembre del año anterior; la del 02, a junio."""
    year, sem = int(cod_periodo[:4]), int(cod_periodo[4:])
    return (year - 1) * 100 + 12 if sem == 1 else year * 100 + 6


def known_month(row) -> int:
    """Mes desde el que el informe se conoce: el del comité; si no se leyó, abril (semestre 01) u octubre (02)."""
    if pd.notna(row["fecha_comite"]):
        return row["fecha_comite"].year * 100 + row["fecha_comite"].month
    year, sem = int(row["cod_periodo"][:4]), int(row["cod_periodo"][4:])
    return year * 100 + (4 if sem == 1 else 10)


def month_range(a: int, b: int) -> list[int]:
    out, y, m = [], *divmod(a, 100)
    while y * 100 + m <= b:
        out.append(y * 100 + m)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def add_months(p: int, k: int) -> int:
    y, m = divmod(p, 100)
    t = y * 12 + m - 1 + k
    return (t // 12) * 100 + t % 12 + 1


def build_panel(rep: pd.DataFrame, last_month: int) -> pd.DataFrame:
    ok = rep[rep["rating"].notna()].copy()
    ok["desde"] = ok.apply(known_month, axis=1)
    # Si hay dos informes del mismo periodo (preliminar y final), manda el último número de archivo.
    ok = ok.sort_values(["id_entidad", "clasificadora", "desde", "num_archivo"])
    ok = ok.drop_duplicates(["id_entidad", "clasificadora", "desde"], keep="last")
    rows = []
    for (ent, ag), g in ok.groupby(["id_entidad", "clasificadora"]):
        g = g.reset_index(drop=True)
        for i, r in g.iterrows():
            end = add_months(r["desde"], VIGENCIA_MESES - 1)
            if i + 1 < len(g):
                end = min(end, add_months(g.at[i + 1, "desde"], -1))
            # Rebaja: peor que el informe previo de la misma clasificadora o que la categoría anterior que trae el
            # propio informe (cubre los semestres sin informe en la extranet).
            prevs = [g.at[i - 1, "rating_num"] if i > 0 else None,
                     GRADE_NUM.get(r.get("rating_anterior_informe"))]
            down = any(x is not None and pd.notna(x) and r["rating_num"] > x for x in prevs)
            for p in month_range(r["desde"], min(end, last_month)):
                rows.append({"periodo": p, "id_entidad": ent, "clasificadora": ag, "rating": r["rating"],
                             "rating_num": r["rating_num"], "perspectiva": r["perspectiva"],
                             "desde": r["desde"], "rebaja": int(down), "rebaja_mes": r["desde"] if down else None})
    m = pd.DataFrame(rows)
    if m.empty:
        return m
    label = {"moodys-local": "Moody's Local", "apoyo": "Apoyo", "pcr": "PCR", "microrate": "MicroRate"}
    m["txt"] = [f"{label[a]} {r} ({(p or 'sin perspectiva').lower()}, desde {d // 100}-{d % 100:02d})"
                for a, r, p, d in zip(m["clasificadora"], m["rating"], m["perspectiva"], m["desde"])]
    g = m.groupby(["periodo", "id_entidad"])
    panel = pd.DataFrame({
        "cl_peor_num": g["rating_num"].max(),
        "cl_mejor_num": g["rating_num"].min(),
        "cl_n": g["clasificadora"].nunique(),
        "cl_perspectiva_negativa": g["perspectiva"].apply(lambda s: bool((s == "Negativa").any())),
        "cl_detalle": g["txt"].apply(lambda s: " · ".join(sorted(s))),
    }).reset_index()
    panel["cl_peor"] = panel["cl_peor_num"].map(lambda k: GRADES[int(k) - 1])
    # Rebaja de cualquier clasificadora conocida en los 12 meses previos (incluido el mes).
    downs = m.loc[m["rebaja"] == 1, ["id_entidad", "rebaja_mes"]].drop_duplicates()
    dset = downs.groupby("id_entidad")["rebaja_mes"].apply(list).to_dict()
    panel["cl_rebaja_12m"] = [any(add_months(p, -11) <= d <= p for d in dset.get(e, []))
                              for p, e in zip(panel["periodo"], panel["id_entidad"])]
    return panel


def run_sample(folder: Path) -> None:
    codes = {"_ml_": "moodys-local", "_eq_": "moodys-local", "_aai_": "apoyo", "_pcr_": "pcr", "_mr_": "microrate",
             "_410_": "microrate"}
    rows = []
    for pdf in sorted(folder.glob("*.pdf")):
        agency = next((a for k, a in codes.items() if k in pdf.name), None)
        if agency:
            rows.append({"archivo": pdf.name, "clasificadora": agency, **parse_report(pdf, agency)})
    df = pd.DataFrame(rows)
    pd.set_option("display.width", 220)
    print(df[["archivo", "rating", "regla_rating", "perspectiva", "fecha_comite", "regla_comite"]].to_string(index=False))
    print(f"\n{df['rating'].notna().sum()}/{len(df)} con clasificación · {df['perspectiva'].notna().sum()} con perspectiva · "
          f"{df['fecha_comite'].notna().sum()} con comité")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--muestra", type=Path)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    if args.muestra:
        run_sample(args.muestra)
        return 0

    idx = pd.read_csv(RAW / "indice.csv", dtype={"cod_clasificadora": str, "cod_periodo": str})
    aliases = load_aliases(ALIAS_CSV)
    idx["id_entidad"] = idx["archivo"].map(lambda n: match_entity(n, aliases))
    idx = idx[idx["id_entidad"].fillna("") != ""].copy()
    rows = []
    for r in idx.itertuples():
        path = RAW / r.clasificadora / r.cod_periodo / f"{int(r.num_archivo):03d}_{r.archivo}"
        if not path.exists():
            continue
        rows.append({"id_entidad": r.id_entidad, "clasificadora": r.clasificadora, "cod_periodo": r.cod_periodo,
                     "num_archivo": int(r.num_archivo), "archivo": r.archivo,
                     "preliminar": int("prelim" in fold(r.archivo)),
                     "periodo_informacion": info_period(r.cod_periodo), **parse_report(path, r.clasificadora)})
    rep = pd.DataFrame(rows)
    # Los preliminares solo cuentan si no hay informe final de la misma entidad, clasificadora y periodo.
    final = rep[rep["preliminar"] == 0].set_index(["id_entidad", "clasificadora", "cod_periodo"]).index
    rep = rep[(rep["preliminar"] == 0) | ~rep.set_index(["id_entidad", "clasificadora", "cod_periodo"]).index.isin(final)]
    rep = rep.sort_values(["id_entidad", "clasificadora", "cod_periodo", "num_archivo"]).reset_index(drop=True)

    last_month = int(pd.Timestamp.today().strftime("%Y%m"))
    panel = build_panel(rep, last_month)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    rep.to_parquet(PROCESSED / "clasificaciones_informes.parquet", index=False)
    panel.to_parquet(PROCESSED / "clasificaciones.parquet", index=False)
    with pd.ExcelWriter(PROCESSED / "clasificaciones.xlsx") as xl:
        rep.to_excel(xl, sheet_name="informes", index=False)
        rep[rep["rating"].isna()].to_excel(xl, sheet_name="sin_leer", index=False)
        panel.to_excel(xl, sheet_name="panel_mensual", index=False)
    print(f"Informes: {len(rep)} ({rep['rating'].notna().mean():.0%} con clasificación, "
          f"{rep['perspectiva'].notna().mean():.0%} con perspectiva, {rep['fecha_comite'].notna().mean():.0%} con comité); "
          f"entidades: {rep['id_entidad'].nunique()}; panel: {len(panel)} entidad-mes")
    print(rep.groupby("clasificadora")["rating"].apply(lambda s: f"{s.notna().sum()}/{len(s)}").to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
