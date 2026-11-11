"""Descargador del archivo completo de Reportes de Inflación (RI) del BCRP: solo el informe.

Lee el índice oficial https://www.bcrp.gob.pe/publicaciones/reporte-de-inflacion.html y baja el
PDF del informe completo de cada RI (2002 en adelante). No baja síntesis, presentaciones,
videos, la versión HTML ni los recuadros sueltos (los recuadros están dentro del informe).

Destino: data/raw/proyecciones/BCRP_RI/<nombre oficial del archivo>.pdf, la misma carpeta donde
`descargar_proyecciones.py` ya dejó los RI de 2015 en adelante. Así todos los informes quedan en
una sola carpeta sin duplicar archivos: este script solo baja los que faltan. Los scripts que
leen esa carpeta (construir_proyecciones.py, extraer_proyecciones_inflacion.py) abren solo los
archivos listados en config/proyecciones.csv, así que los RI antiguos no los afectan.

Control:
  - data/_control/reportes_inflacion_catalogo.csv  un registro por RI (estado, origen, sha256).
  - data/_control/manifest_reportes_inflacion.csv  bitácora de cada descarga (se agrega).
  - data/_control/indice_ri/                       copia del índice usado (HTML tal cual).

bcrp.gob.pe bloquea a los scripts (Imperva, «Pardon Our Interruption»). Igual que
`descargar_proyecciones.py`, si la descarga directa no da el archivo se usa la copia del MISMO
archivo oficial en el Internet Archive (versión original `id_`, sin la barra de Wayback) y se
valida que sea un PDF completo (`%PDF` al inicio, `%%EOF` al final).

Además del índice se prueban los RI que tocan según el calendario (marzo, junio, setiembre y
diciembre) y aún no salen en la última captura del índice: así un RI nuevo se baja apenas el
Internet Archive lo tenga. Si todavía no está, queda «pendiente» (no es error).

Uso:
    python src/descargar_reportes_inflacion.py               # todos los que falten
    python src/descargar_reportes_inflacion.py --desde 2020
    python src/descargar_reportes_inflacion.py --dry-run     # arma el catálogo, no baja nada
    python src/descargar_reportes_inflacion.py --reintentar  # reintenta los «no_disponible»
    python src/descargar_reportes_inflacion.py --indice pagina.html   # índice guardado a mano
    python src/descargar_reportes_inflacion.py --importar RI-2026-12 ruta/al.pdf
                                                     # PDF oficial bajado a mano con el navegador

Los PDF bajados NO son de confianza: este script no los abre; solo valida la firma.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import hashlib
import logging
import re
import shutil
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

from descargar_proyecciones import CDX_URL, WAYBACK_RAW, Client, looks_valid

PROJECT_DIR = Path(__file__).resolve().parents[1]
INDEX_URL = "https://www.bcrp.gob.pe/publicaciones/reporte-de-inflacion.html"
BASE_URL = "https://www.bcrp.gob.pe"
DEST = PROJECT_DIR / "data" / "raw" / "proyecciones" / "BCRP_RI"
CONTROL = PROJECT_DIR / "data" / "_control"
INDEX_COPIES = CONTROL / "indice_ri"
CATALOG = CONTROL / "reportes_inflacion_catalogo.csv"
MANIFEST = CONTROL / "manifest_reportes_inflacion.csv"

MONTHS = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
          "agosto": 8, "setiembre": 9, "septiembre": 9, "octubre": 10, "noviembre": 11,
          "diciembre": 12}
MONTH_NAME = {3: "marzo", 6: "junio", 9: "setiembre", 12: "diciembre"}
QUARTER_MONTHS = (3, 6, 9, 12)   # calendario vigente desde 2016

CATALOG_FIELDS = ["ri", "anio", "mes", "archivo", "url", "origen", "estado", "via",
                  "url_descarga", "bytes", "sha256", "actualizado_en"]
STATE_FIELDS = ("estado", "via", "url_descarga", "bytes", "sha256", "actualizado_en")
MANIFEST_FIELDS = ["ri", "archivo", "url", "url_descarga", "via", "wayback_timestamp",
                   "bytes", "sha256", "descargado_en", "accion"]

log = logging.getLogger("descargador_ri")


@dataclass
class Report:
    ri: str                  # RI-AAAA-MM
    url: str                 # URL oficial del PDF
    origen: str = "indice"   # indice | calendario | manual
    estado: str = "pendiente"
    via: str = ""
    url_descarga: str = ""
    bytes: str = ""
    sha256: str = ""
    actualizado_en: str = ""

    @property
    def archivo(self) -> str:
        return self.url.rsplit("/", 1)[-1]

    @property
    def path(self) -> Path:
        return DEST / self.archivo

    def row(self) -> dict:
        d = {k: getattr(self, k) for k in CATALOG_FIELDS if hasattr(self, k)}
        d.update(anio=self.ri[3:7], mes=self.ri[8:10], archivo=self.archivo)
        return {k: d.get(k, "") for k in CATALOG_FIELDS}


# --------------------------------------------------------------------------- índice
class IndexParser(HTMLParser):
    """Enlaces (href, texto) en orden. Los comentarios HTML (enlaces desactivados) se ignoran."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join("".join(self._text).split())))
            self._href = None


def ri_from_url(url: str) -> str | None:
    """RI-AAAA-MM según el nombre del archivo (p. ej. Reporte-Inflacion-Mayo-2007.pdf)."""
    name = url.rsplit("/", 1)[-1].lower()
    m = re.search(r"(" + "|".join(MONTHS) + r")-(\d{4})", name)
    return f"RI-{m.group(2)}-{MONTHS[m.group(1)]:02d}" if m else None


def is_report(href: str, text: str) -> bool:
    """El informe completo: PDF bajo /Reporte-Inflacion/ que no es síntesis ni presentación.
    En el índice se rotula «Reporte», «Reporte (PDF)» o, hasta 2006, con el nombre del mes."""
    h = href.lower().split("?", 1)[0]
    t = text.lower()
    return ("/reporte-inflacion/" in h and h.endswith(".pdf")
            and not re.search(r"sintesis|presentacion", h.rsplit("/", 1)[-1])
            and "síntesis" not in t and "presentaci" not in t and t != "ppt")


def parse_index(html: str) -> list[Report]:
    p = IndexParser()
    p.feed(html)
    out: dict[str, Report] = {}
    for href, text in p.links:
        if not is_report(href, text):
            continue
        url = urljoin(BASE_URL, href)
        ri = ri_from_url(url)
        if ri is None:
            log.warning("informe sin mes-año en el nombre, se omite: %s", url)
            continue
        if ri in out and out[ri].url != url:
            log.warning("%s tiene dos informes en el índice: %s y %s", ri, out[ri].url, url)
            continue
        out[ri] = Report(ri, url)
    return list(out.values())


def is_blocked(content: bytes) -> bool:
    head = content[:20000].lower()
    return b"pardon our interruption" in head or b"incapsula" in head


def get_index(client: Client, local: Path | None) -> tuple[str, str, bool]:
    """Devuelve (html, procedencia, bcrp_bloquea) y guarda la copia en indice_ri/."""
    INDEX_COPIES.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d")
    if local:
        raw = local.read_bytes()
        return raw.decode("utf-8", errors="replace"), f"archivo local: {local.name}", True
    else:
        r = client.get(INDEX_URL)
        if r is not None and r.status_code == 200 and not is_blocked(r.content) \
                and b"Reporte-Inflacion" in r.content:
            raw, src, blocked = r.content, "directo", False
        else:
            log.info("índice: bcrp.gob.pe bloquea la descarga; uso la última captura de Wayback")
            blocked, raw = True, b""
            cdx = client.get(CDX_URL, params={"url": INDEX_URL.split("://", 1)[1],
                                              "fl": "timestamp", "filter": "statuscode:200",
                                              "limit": "-10"}, timeout=120)
            stamps = cdx.text.split() if cdx is not None and cdx.status_code == 200 else []
            for ts in reversed(stamps):   # de la más reciente hacia atrás
                w = client.get(WAYBACK_RAW.format(ts=ts, url=INDEX_URL))
                body = w.content if w is not None else b""
                if body[:2] == b"\x1f\x8b":   # a veces la captura llega aún comprimida
                    body = gzip.decompress(body)
                if w is not None and w.status_code == 200 and b"Reporte-Inflacion" in body:
                    raw, src, stamp = body, f"wayback {ts}", ts
                    break
            if not raw:
                raise RuntimeError("no conseguí el índice (ni directo ni en Wayback); "
                                   "use --indice con la página guardada desde el navegador")
    (INDEX_COPIES / f"reporte-de-inflacion_{stamp}.html").write_bytes(raw)
    return raw.decode("utf-8", errors="replace"), src, blocked


def calendar_reports(reports: list[Report], today: dt.date) -> list[Report]:
    """RI trimestrales posteriores al último del índice cuyo mes ya llegó, con el patrón de
    nombre vigente (reporte-de-inflacion-<mes>-<año>.pdf)."""
    last = max(r.ri for r in reports)
    y, m = int(last[3:7]), int(last[8:10])
    out = []
    while True:
        nxt = [q for q in QUARTER_MONTHS if q > m]
        y, m = (y, nxt[0]) if nxt else (y + 1, QUARTER_MONTHS[0])
        if dt.date(y, m, 1) > today:
            return out
        mes = MONTH_NAME[m]
        out.append(Report(f"RI-{y}-{m:02d}", f"{BASE_URL}/docs/Publicaciones/Reporte-Inflacion/"
                                             f"{y}/{mes}/reporte-de-inflacion-{mes}-{y}.pdf",
                          "calendario"))


# --------------------------------------------------------------------------- descarga
def wayback_snapshots(client: Client, url: str) -> list[str]:
    """Capturas con estado 200: primero las de tipo PDF, luego el resto (en capturas antiguas
    el servidor a veces declaraba otro tipo MIME). La más antigua primero."""
    bare = url.split("://", 1)[-1].split("?", 1)[0]
    r = client.get(CDX_URL, params={"url": bare, "fl": "timestamp,mimetype",
                                    "filter": "statuscode:200", "limit": "50"}, timeout=120)
    if r is None or r.status_code != 200:
        return []
    rows = [line.split() for line in r.text.splitlines() if len(line.split()) == 2]
    return ([ts for ts, mime in rows if mime == "application/pdf"]
            + [ts for ts, mime in rows if mime != "application/pdf"])


def fetch(client: Client, rep: Report, try_direct: bool) -> tuple[bytes, str, str, str] | None:
    if try_direct:
        r = client.get(rep.url)
        if r is not None and r.status_code == 200 and looks_valid(r.content, "pdf"):
            return r.content, rep.url, "directo", ""
    for ts in wayback_snapshots(client, rep.url)[:6]:
        wurl = WAYBACK_RAW.format(ts=ts, url=rep.url)
        r = client.get(wurl)
        if r is not None and r.status_code == 200 and looks_valid(r.content, "pdf"):
            return r.content, wurl, "wayback", ts
        log.info("  captura %s no válida", ts)
    return None


def append_manifest(row: dict) -> None:
    new = not MANIFEST.exists()
    with MANIFEST.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


def store(rep: Report, content: bytes, used: str, via: str, ts: str) -> None:
    sha = hashlib.sha256(content).hexdigest()
    action = "nuevo"
    if rep.path.exists():
        old = rep.path.read_bytes()
        if hashlib.sha256(old).hexdigest() == sha:
            action = "sin_cambios"
        elif looks_valid(old, "pdf"):
            action = "revisado"
            hist = CONTROL / "historial" / "proyecciones"
            hist.mkdir(parents=True, exist_ok=True)
            shutil.copy2(rep.path, hist / f"{rep.path.stem}__{dt.date.today():%Y%m%d}.pdf")
        else:
            action = "reemplaza_invalido"
    if action != "sin_cambios":
        DEST.mkdir(parents=True, exist_ok=True)
        tmp = rep.path.with_suffix(".pdf.tmp")
        tmp.write_bytes(content)
        tmp.replace(rep.path)
    now = dt.datetime.now().isoformat(timespec="seconds")
    rep.estado, rep.via, rep.url_descarga = "descargado", via, used
    rep.bytes, rep.sha256, rep.actualizado_en = str(len(content)), sha, now
    log.info("  %s vía %s%s: %.1f MB", action, via, f" ({ts})" if ts else "", len(content) / 1e6)
    append_manifest({"ri": rep.ri, "archivo": rep.archivo, "url": rep.url, "url_descarga": used,
                     "via": via, "wayback_timestamp": ts, "bytes": len(content), "sha256": sha,
                     "descargado_en": now, "accion": action})


# --------------------------------------------------------------------------- catálogo
def load_catalog() -> dict[str, dict]:
    if not CATALOG.exists():
        return {}
    with CATALOG.open(encoding="utf-8-sig", newline="") as f:
        return {r["ri"]: r for r in csv.DictReader(f)}


def write_catalog(reports: list[Report]) -> None:
    tmp = CATALOG.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CATALOG_FIELDS)
        w.writeheader()
        w.writerows(r.row() for r in sorted(reports, key=lambda r: r.ri))
    tmp.replace(CATALOG)


def merge_previous(reports: list[Report], prev: dict[str, dict]) -> list[Report]:
    """Conserva el estado de corridas anteriores y los RI ya bajados que el índice no trae
    (del calendario o importados a mano)."""
    seen = {r.ri for r in reports}
    for rep in reports:
        old = prev.get(rep.ri)
        if old and old["url"] == rep.url:
            for k in STATE_FIELDS:
                setattr(rep, k, old[k])
            if old["origen"] == "manual":
                rep.origen = "manual"
    for ri, old in prev.items():
        if ri not in seen and old["estado"] == "descargado":
            rep = Report(ri, old["url"], old["origen"])
            for k in STATE_FIELDS:
                setattr(rep, k, old[k])
            reports.append(rep)
    return reports


# --------------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--desde", type=int, help="primer año")
    ap.add_argument("--hasta", type=int, help="último año")
    ap.add_argument("--dry-run", action="store_true", help="arma el catálogo, no descarga")
    ap.add_argument("--reintentar", action="store_true", help="reintenta los «no_disponible»")
    ap.add_argument("--forzar", action="store_true", help="vuelve a bajar aunque exista")
    ap.add_argument("--indice", type=Path, help="índice guardado a mano desde el navegador")
    ap.add_argument("--importar", nargs=2, metavar=("RI", "ARCHIVO"),
                    help="registrar un PDF oficial bajado a mano, p. ej. RI-2026-12 x.pdf")
    ap.add_argument("--pausa", type=float, default=2.0)
    ap.add_argument("--pausa-archivo", type=float, default=5.0,
                    help="segundos entre peticiones al Internet Archive (límite ~15/min)")
    args = ap.parse_args(argv)

    (CONTROL / "logs").mkdir(parents=True, exist_ok=True)
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(
            CONTROL / "logs" / f"{dt.datetime.now():%Y%m%d_%H%M%S}_reportes_inflacion.log",
            encoding="utf-8")])
    prev = load_catalog()

    if args.importar:
        ri, src = args.importar[0], Path(args.importar[1])
        m = re.fullmatch(r"RI-(\d{4})-(\d{2})", ri)
        if not m:
            log.error("RI debe tener la forma RI-AAAA-MM")
            return 1
        content = src.read_bytes()
        if not looks_valid(content, "pdf"):
            log.error("%s no es un PDF completo", src)
            return 1
        if ri in prev:
            rep = Report(ri, prev[ri]["url"], "manual")
        else:   # URL según el patrón vigente: así el nombre del archivo es el oficial
            y, mo = int(m.group(1)), int(m.group(2))
            mes = MONTH_NAME.get(mo) or next(k for k, v in MONTHS.items() if v == mo)
            rep = Report(ri, f"{BASE_URL}/docs/Publicaciones/Reporte-Inflacion/{y}/{mes}/"
                             f"reporte-de-inflacion-{mes}-{y}.pdf", "manual")
        store(rep, content, f"archivo local: {src.name}", "manual", "")
        others = [r for r in merge_previous([], prev) if r.ri != ri]
        write_catalog(others + [rep])
        return 0

    client = Client(args.pausa, args.pausa_archivo)
    html, src, blocked = get_index(client, args.indice)
    reports = parse_index(html)
    log.info("Índice (%s): %d informes, %s a %s", src, len(reports),
             min(r.ri for r in reports), max(r.ri for r in reports))
    known = {r.ri for r in reports}
    reports += [c for c in calendar_reports(reports, dt.date.today()) if c.ri not in known]
    reports = merge_previous(reports, prev)
    reports.sort(key=lambda r: r.ri)

    todo = [r for r in reports
            if (args.desde is None or int(r.ri[3:7]) >= args.desde)
            and (args.hasta is None or int(r.ri[3:7]) <= args.hasta)]
    counts: dict[str, int] = {}
    new_failures = 0
    try:
        for rep in todo:
            if rep.path.exists() and not args.forzar and looks_valid(rep.path.read_bytes(), "pdf"):
                if rep.estado != "descargado":   # archivo presente pero sin registro
                    content = rep.path.read_bytes()
                    rep.estado, rep.via = "descargado", rep.via or "ya_estaba"
                    rep.bytes, rep.sha256 = str(len(content)), hashlib.sha256(content).hexdigest()
                counts["existente"] = counts.get("existente", 0) + 1
                continue
            if rep.estado == "no_disponible" and not (args.reintentar or args.forzar):
                counts["no_disponible"] = counts.get("no_disponible", 0) + 1
                continue
            log.info("%s %s", rep.ri, rep.archivo)
            if args.dry_run:
                counts["dry-run"] = counts.get("dry-run", 0) + 1
                continue
            got = fetch(client, rep, try_direct=not blocked)
            if got is None:
                # Un RI del calendario que aún no está en Wayback sigue «pendiente».
                rep.estado = "pendiente" if rep.origen == "calendario" else "no_disponible"
                rep.actualizado_en = dt.datetime.now().isoformat(timespec="seconds")
                if rep.estado == "no_disponible":
                    new_failures += 1
                    log.warning("  NO CONSEGUIDO")
                else:
                    log.info("  aún no está en el Internet Archive (pendiente)")
                counts[rep.estado] = counts.get(rep.estado, 0) + 1
                continue
            store(rep, *got)
            counts[got[2]] = counts.get(got[2], 0) + 1
            write_catalog(reports)   # guarda avance: la corrida puede durar media hora o más
    finally:
        write_catalog(reports)

    log.info("Corrida: %s", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    log.info("Carpeta %s: %d de %d informes; no disponibles: %d; pendientes: %d",
             DEST.relative_to(PROJECT_DIR).as_posix(),
             sum(r.estado == "descargado" for r in reports), len(reports),
             sum(r.estado == "no_disponible" for r in reports),
             sum(r.estado == "pendiente" for r in reports))
    return 1 if new_failures else 0


if __name__ == "__main__":
    sys.exit(main())
