"""IPC por ciudades del INEI: variación mensual, acumulada y de 12 meses de las 26 ciudades del IPC nacional.

Fuente: INEI, «Informe de Precios» mensual (Informe técnico «Variación de los Indicadores de Precios de la
Economía»), Biblioteca virtual > Boletines > Informe de Precios:
    https://www.inei.gob.pe/biblioteca-virtual/boletines/informe-de-precios/<año>/<página>/
Cada informe trae el cuadro «Variación porcentual del Índice de Precios al Consumidor Nacional y de
Principales Ciudades» del mes anterior (mensual, acumulada en el año y 12 meses). El INEI no publica esa
tabla en Excel ni como serie: se arma una serie leyendo un PDF por mes. El IPC nacional (26 ciudades,
base dic-2011 y luego dic-2021) existe desde ene-2012, así que se baja desde los informes de 2012.

Qué hace (secuencial, con pausa entre pedidos y reanudable):
  1. Lee el listado de informes de cada año (desde --desde) y guarda la lista en el manifest.
  2. Baja cada PDF que aún no esté en `data/raw/inei_ipc_ciudades/pdf/` (nombre = fecha de publicación +
     nombre original, porque el INEI reutiliza nombres de archivo como «informe-de-precios-2026.pdf»).
  3. Extrae el cuadro de ciudades de cada PDF y escribe `data/processed/inei_ipc_ciudades.csv`
     (fecha, ciudad, var_mensual, var_acumulada, var_12m, archivo, url).
No salta bloqueos: si el INEI responde con un captcha o algo que no es PDF, se registra y se sigue.

Registro: `data/_control/manifest_ipc_ciudades.csv` (una fila por informe) y un log por corrida en
`data/_control/logs/`.

Uso:
    python descargar_ipc_ciudades.py                 # listar + bajar lo que falte + procesar
    python descargar_ipc_ciudades.py --solo-procesar # solo rehacer el CSV desde los PDF ya bajados
    python descargar_ipc_ciudades.py --desde 2025    # listar solo desde 2025 (corrida mensual rápida)
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import logging
import re
import sys
import time
import unicodedata
from pathlib import Path

import requests

PROJECT_DIR = Path(__file__).resolve().parents[1]
RAW = PROJECT_DIR / "data" / "raw" / "inei_ipc_ciudades"
PDF_DIR = RAW / "pdf"
CONTROL = PROJECT_DIR / "data" / "_control"
MANIFEST = CONTROL / "manifest_ipc_ciudades.csv"
LOG_DIR = CONTROL / "logs"
OUT = PROJECT_DIR / "data" / "processed" / "inei_ipc_ciudades.csv"

BASE = "https://www.inei.gob.pe"
LIST_URL = BASE + "/biblioteca-virtual/boletines/informe-de-precios/{year}/{page}/"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0 Safari/537.36")
PAUSE = 2.5          # segundos entre pedidos
FIRST_YEAR = 2012    # primer año con IPC nacional de 26 ciudades

# Ciudades del IPC nacional (nombre como lo escribe el INEI desde 2014; antes «Lima»).
CITIES = ["Abancay", "Arequipa", "Ayacucho", "Cajamarca", "Cerro de Pasco", "Chachapoyas", "Chiclayo",
          "Chimbote", "Cusco", "Huancavelica", "Huancayo", "Huánuco", "Huaraz", "Ica", "Iquitos",
          "Lima Metropolitana", "Moquegua", "Moyobamba", "Piura", "Pucallpa", "Puerto Maldonado", "Puno",
          "Tacna", "Tarapoto", "Trujillo", "Tumbes"]
NATIONAL = "Nacional"
MONTHS = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
          "setiembre": 9, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12}
MANIFEST_COLS = ["url", "fecha_publicacion", "titulo", "archivo", "bytes", "sha256", "descargado_en",
                 "estado", "mes_dato", "n_ciudades", "nota"]

log = logging.getLogger("ipc_ciudades")


def key(s: str) -> str:
    """Nombre sin tildes, espacios ni mayúsculas (pypdf a veces parte palabras: «Huancaveli ca»)."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", s.lower())


NAME_BY_KEY = {key(c): c for c in CITIES} | {"lima": "Lima Metropolitana", "pasco": "Cerro de Pasco", key(NATIONAL): NATIONAL,
                                              "totalnacional": NATIONAL}


# ---------------------------------------------------------------------------------------------
# Red
# ---------------------------------------------------------------------------------------------
class Client:
    def __init__(self) -> None:
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "es-PE,es;q=0.9"})
        self.last = 0.0

    def get(self, url: str) -> requests.Response:
        wait = PAUSE - (time.monotonic() - self.last)
        if wait > 0:
            time.sleep(wait)
        try:
            r = self.s.get(url, timeout=90)
        finally:
            self.last = time.monotonic()
        r.raise_for_status()
        return r


def list_year(client: Client, year: int) -> list[dict]:
    rows, page, total = [], 1, None
    while True:
        url = LIST_URL.format(year=year, page=page)
        html = client.get(url).content.decode("cp1252", errors="replace")
        if total is None:
            m = re.search(r"Resultado\s+\d+\s+de\s+\d+\s+de\s+(\d+)", html)
            total = int(m.group(1)) if m else 0
        found = re.findall(r'<tr[^>]*rel="([^"]+\.pdf)"[^>]*>\s*<td[^>]*>\s*([\d/]+)\s*</td>\s*<td>([^<]*)</td>',
                           html, flags=re.I)
        for rel, fecha, titulo in found:
            d, mth, y = fecha.split("/")
            rows.append({"url": rel if rel.startswith("http") else BASE + rel,
                         "fecha_publicacion": f"{y}-{mth}-{d}", "titulo": " ".join(titulo.split())})
        if not found or len(rows) >= total or page > 20:
            break
        page += 1
    log.info("listado %d: %d informes", year, len(rows))
    return rows


def local_name(row: dict) -> str:
    base = re.sub(r"[^A-Za-z0-9_.-]", "_", row["url"].rsplit("/", 1)[-1])
    return f"{row['fecha_publicacion']}_{base}"


# ---------------------------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------------------------
def read_manifest() -> dict[tuple[str, str], dict]:
    if not MANIFEST.exists():
        return {}
    with MANIFEST.open(encoding="utf-8-sig", newline="") as f:
        return {(r["url"], r["fecha_publicacion"]): r for r in csv.DictReader(f)}


def write_manifest(man: dict[tuple[str, str], dict]) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(man.values(), key=lambda r: (r["fecha_publicacion"], r["url"]))
    tmp = MANIFEST.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(MANIFEST)


# ---------------------------------------------------------------------------------------------
# Lectura del cuadro de ciudades
# ---------------------------------------------------------------------------------------------
NUM = r"(?:-?\d+,\d+|-{1,3}|n\.d\.?)"
ROW_RE = re.compile(r"^\s*([A-Za-zÁÉÍÓÚÜÑáéíóúüñ. ]+?)\s+(" + NUM + r"(?:\s+" + NUM + r")*)\s*$")
TITLE_RE = re.compile(r"principales\s*ciudades", re.I)
# pypdf a veces parte palabras («SETI EMBRE»): se tolera un espacio entre letras.
MONTH_RE = re.compile(r"(?<![a-z])(" + "|".join(r"\s?".join(m) for m in MONTHS) + r")\s*(?:de\s+)?(\d{4})\b", re.I)


def clean_line(line: str) -> str:
    """Repara números partidos por pypdf: «0 ,28» «- 1,38» «111, 99»."""
    line = re.sub(r"(\d)\s+,", r"\1,", line)
    line = re.sub(r",\s+(\d)", r",\1", line)
    line = re.sub(r"(?<![\d,])-\s+(\d)", r"-\1", line)
    return line


def to_float(tok: str) -> float | None:
    if not re.match(r"^-?\d+,\d+$", tok):
        return None
    return float(tok.replace(",", "."))


def parse_city_table(text: str, fallback: dt.date | None = None) -> tuple[dt.date | None, dict[str, list[float | None]], int]:
    """Del texto de una página: (mes del dato, {ciudad: [mensual, acumulada, 12 meses]}).

    Formatos vistos: tres columnas (mes, acumulada en el año, 12 meses); en los informes de diciembre solo
    mes y «Ene-Dic» (= 12 meses); en los de enero, solo mes y 12 meses (la acumulada es la del mes); en 2012
    el nacional trae solo mes y acumulada (aún no había índice nacional de un año antes)."""
    rows: dict[str, list[str]] = {}
    first_row = None
    # pypdf a veces deja la inicial sola en una línea («N» / «acional 0,15 3,87 4,06», ago-2026).
    text = re.sub(r"(?m)^\s*([A-ZÁÉÍÓÚ])\s*\n(?=[a-záéíóúñ])", r"\1", text)
    lines = text.splitlines()
    for j, raw in enumerate(lines):
        m = ROW_RE.match(clean_line(raw))
        if not m:
            continue
        name = NAME_BY_KEY.get(key(m.group(1)))
        if not name or name in rows:
            continue
        rows[name] = m.group(2).split()
        if first_row is None:
            first_row = j
    multi = sum(len(t) >= 2 for t in rows.values())
    # Una sola columna (ene-feb 2022, cambio de base: solo la variación del mes). Se acepta solo si también
    # viene el nacional, para no confundirla con el cuadro de ponderaciones por ciudad.
    only_month = multi < 20 and len(rows.get(NATIONAL, [])) == 1 and len(rows) >= 20
    if multi < 20 and not only_month:
        return None, {}, 0
    # Mes del dato: el primer «<mes> <año>» del encabezado del cuadro (antes de la primera fila).
    head = "\n".join(lines[:first_row])
    t = TITLE_RE.search(head)
    mm = MONTH_RE.search(head, t.end() if t else 0) or MONTH_RE.search(head)
    month = dt.date(int(mm.group(2)), MONTHS[re.sub(r"\s", "", mm.group(1)).lower()], 1) if mm else None
    cm = month or fallback  # algunos cuadros de 2012 no traen el mes como texto
    out: dict[str, list[float | None]] = {}
    for name, toks in rows.items():
        v = [to_float(x) for x in toks]
        if len(v) == 3:
            out[name] = v
        elif len(v) == 2 and cm is not None and cm.month == 12:
            out[name] = [v[0], v[1], v[1]]
        elif len(v) == 2 and cm is not None and cm.month == 1:
            out[name] = [v[0], v[0], v[1]]
        elif len(v) == 2:
            out[name] = [v[0], v[1], None]
        elif len(v) == 1 and only_month:
            out[name] = [v[0], v[0] if cm is not None and cm.month == 1 else None, None]
    return month, out, (1 if only_month else max(len(t) for t in rows.values()))


def extract(pdf_path: Path, fallback: dt.date | None = None) -> tuple[dt.date | None, dict[str, list[float | None]], str]:
    import pypdf  # import aquí para que listar/bajar no dependa de pypdf

    reader = pypdf.PdfReader(str(pdf_path))
    best: tuple[dt.date | None, dict, str] = (None, {}, "sin cuadro de ciudades")
    best_score = (0, 0)
    for i, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except Exception as e:  # noqa: BLE001
            log.warning("%s pág. %d: %s", pdf_path.name, i + 1, e)
            continue
        if "pasco" not in text.lower():
            continue
        month, rows, ncol = parse_city_table(text, fallback)
        # Se prefiere el cuadro con más ciudades y, a igualdad, el de más columnas: algunos informes traen
        # antes un gráfico con solo la variación del mes (feb-2014, pág. 4).
        score = (len(rows), ncol)
        if rows and score > best_score:
            best, best_score = (month, rows, f"pág. {i + 1}"), score
    return best


# ---------------------------------------------------------------------------------------------
# Corrida
# ---------------------------------------------------------------------------------------------
def download(client: Client, man: dict, desde: int) -> None:
    today = dt.date.today()
    listed: list[dict] = []
    for year in range(desde, today.year + 1):
        try:
            listed += list_year(client, year)
        except Exception as e:  # noqa: BLE001
            log.error("listado %d: %s", year, e)
    for row in listed:
        k = (row["url"], row["fecha_publicacion"])
        rec = man.get(k) or {c: "" for c in MANIFEST_COLS} | row
        rec["titulo"] = row["titulo"]
        man[k] = rec
    write_manifest(man)
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    todo = [r for r in man.values() if int(r["fecha_publicacion"][:4]) >= desde
            and not (r["estado"] == "ok" and (PDF_DIR / r["archivo"]).exists())]
    log.info("por bajar: %d de %d informes", len(todo), len(man))
    for n, rec in enumerate(sorted(todo, key=lambda r: r["fecha_publicacion"]), 1):
        fn = local_name(rec)
        try:
            r = client.get(rec["url"])
            if not r.content.startswith(b"%PDF"):
                raise ValueError(f"no es un PDF (Content-Type {r.headers.get('Content-Type')}); "
                                 "posible bloqueo o página de error")
            (PDF_DIR / fn).write_bytes(r.content)
            rec.update(archivo=fn, bytes=str(len(r.content)), sha256=hashlib.sha256(r.content).hexdigest(),
                       descargado_en=dt.datetime.now().isoformat(timespec="seconds"), estado="ok", nota="")
            log.info("[%d/%d] %s  %s (%d KB)", n, len(todo), rec["fecha_publicacion"], fn, len(r.content) // 1024)
        except Exception as e:  # noqa: BLE001
            rec.update(estado="error", nota=str(e)[:200])
            log.error("[%d/%d] %s: %s", n, len(todo), rec["url"], e)
        write_manifest(man)   # tras cada archivo: reanudable


def process(man: dict) -> int:
    recs, by_month = [], {}
    for rec in sorted(man.values(), key=lambda r: r["fecha_publicacion"]):
        if rec["estado"] != "ok" or not (PDF_DIR / rec["archivo"]).exists():
            continue
        try:
            pub = dt.date.fromisoformat(rec["fecha_publicacion"])
            expected = (pub.replace(day=1) - dt.timedelta(days=1)).replace(day=1)
            month, rows, where = extract(PDF_DIR / rec["archivo"], expected)
        except Exception as e:  # noqa: BLE001
            rec.update(mes_dato="", n_ciudades="0", nota=f"no se pudo leer: {e}"[:200])
            log.error("%s: %s", rec["archivo"], e)
            continue
        if not rows:
            rec.update(mes_dato="", n_ciudades="0",
                       nota="sin cuadro de ciudades (informe que no es del IPC nacional o formato distinto)")
            continue
        pub = dt.date.fromisoformat(rec["fecha_publicacion"])
        expected = (pub.replace(day=1) - dt.timedelta(days=1)).replace(day=1)
        note = ""
        if month is None:
            month, note = expected, "; mes inferido de la fecha de publicación (el cuadro no lo trae como texto)"
        elif month != expected:
            note = f"; ojo: el cuadro dice {month:%Y-%m} y la fecha de publicación sugiere {expected:%Y-%m}"
        rec["n_ciudades"] = str(len([c for c in rows if c != NATIONAL]))
        rec["mes_dato"] = month.isoformat()[:7]
        if month < dt.date(FIRST_YEAR, 1, 1):
            rec["nota"] = where + "; anterior al IPC nacional (ene-2012): no se usa"
            continue
        missing = [c for c in CITIES if c not in rows]
        rec["nota"] = (where + ("; faltan: " + ", ".join(missing) if missing else "")
                       + ("; sin fila del nacional" if NATIONAL not in rows else "") + note)
        if note:
            log.warning("%s: %s", rec["archivo"], note[2:])
        if missing:
            log.warning("%s: %s, mes %s", rec["archivo"], rec["nota"], month)
            continue
        # Un mismo mes en dos informes (fe de erratas o versión «_1»): se queda el más reciente,
        # avisando si las cifras difieren.
        prev = by_month.get(month)
        if prev is not None and prev[0] != rows:
            log.warning("%s: el mes %s ya venía en %s con otras cifras; se usa el más reciente",
                        rec["archivo"], month, prev[1]["archivo"])
        by_month[month] = (rows, rec)
    write_manifest(man)
    for month in sorted(by_month):
        rows, rec = by_month[month]
        for city, (vm, va, v12) in rows.items():
            recs.append({"fecha": month.isoformat(), "ciudad": city, "var_mensual": vm, "var_acumulada": va,
                         "var_12m": v12, "archivo": rec["archivo"], "url": rec["url"]})
    if not recs:
        log.error("no se extrajo ningún cuadro")
        return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(recs[0]))
        w.writeheader()
        w.writerows(recs)
    months = sorted(by_month)
    gaps = [m for a, m in zip(months, months[1:]) if (m.year * 12 + m.month) - (a.year * 12 + a.month) != 1]
    log.info("%s: %d filas, %d meses (%s a %s)%s", OUT.name, len(recs), len(months), months[0], months[-1],
             f"; huecos antes de: {', '.join(str(g)[:7] for g in gaps)}" if gaps else ", sin huecos")
    check(by_month)
    return 0


def check(by_month: dict) -> None:
    """Controles internos: la acumulada debe encadenar las mensuales (con redondeo a 2 decimales)."""
    worst = (0.0, None, None)
    for month, (rows, _) in by_month.items():
        prev_m = dt.date(month.year - (month.month == 1), 12 if month.month == 1 else month.month - 1, 1)
        if month.month == 1 or prev_m not in by_month:
            continue
        for city, (vm, va, _) in rows.items():
            pa = by_month[prev_m][0].get(city, [None, None])[1]
            if None in (vm, va, pa):
                continue
            d = abs(((1 + pa / 100) * (1 + vm / 100) - 1) * 100 - va)
            if d > worst[0]:
                worst = (d, month, city)
    log.info("control acumulada = acumulada previa encadenada con la mensual: diferencia máx. %.3f pp (%s, %s)",
             worst[0], worst[1], worst[2])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--solo-procesar", action="store_true", help="no conectarse: rehacer el CSV desde los PDF")
    ap.add_argument("--desde", type=int, default=FIRST_YEAR, help=f"primer año del listado (por defecto {FIRST_YEAR})")
    a = ap.parse_args(argv)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logfile = LOG_DIR / f"ipc_ciudades_{dt.datetime.now():%Y%m%d_%H%M%S}.log"
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(logfile, encoding="utf-8"), logging.StreamHandler(sys.stdout)])
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # consola de Windows
    except Exception:  # noqa: BLE001
        pass
    man = read_manifest()
    if not a.solo_procesar:
        download(Client(), man, max(a.desde, FIRST_YEAR))
    return process(man)


if __name__ == "__main__":
    sys.exit(main())
