"""Descargador de documentos oficiales de proyecciones (BCRP y MEF).

Recorre `config/proyecciones.csv` (Reportes de Inflación del BCRP y Marcos
Macroeconómicos Multianuales del MEF) y guarda cada archivo tal cual en
`data/raw/proyecciones/<fuente>/<archivo>`. Registra cada descarga en
`data/_control/manifest_proyecciones.csv` con la URL original, la URL realmente
usada (directa o Wayback), el sha256 y el tamaño.

Orden de intentos por documento:
  1. URL oficial directa (User-Agent de navegador y pausa).
  2. Si la respuesta no es el archivo esperado (p. ej. la página de bloqueo de
     Imperva/Incapsula del BCRP), se busca en el Internet Archive (Wayback) una
     captura del MISMO archivo oficial con estado 200 y tipo PDF/XLSX, y se baja
     la versión original de la captura (sufijo `id_`, sin la barra de Wayback).

Los documentos son publicaciones cerradas: si el archivo ya existe no se vuelve a
bajar (salvo `--forzar`). Si al forzar cambia el sha256, la versión anterior se
copia a `data/_control/historial/proyecciones/` antes de reemplazarla.

Uso:
    python descargar_proyecciones.py                 # todo lo activo que falte
    python descargar_proyecciones.py --fuente MEF_MMM
    python descargar_proyecciones.py --publicacion RI-2026-06 MMM-2027-2030
    python descargar_proyecciones.py --dry-run       # solo informa
    python descargar_proyecciones.py --sin-wayback   # solo descargas directas
    python descargar_proyecciones.py --publicacion RI-2026-09 --importar ruta/al.pdf
                                                     # registrar un PDF oficial bajado a mano

Los archivos bajados NO son de confianza: este script no los abre; solo valida la
firma (los primeros bytes) para no guardar una página HTML con extensión .pdf.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import logging
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import requests

PROJECT_DIR = Path(__file__).resolve().parents[1]
CONFIG_CSV = PROJECT_DIR / "config" / "proyecciones.csv"
DEFAULT_DEST = PROJECT_DIR / "data" / "raw" / "proyecciones"
DEFAULT_CONTROL = PROJECT_DIR / "data" / "_control"
MANIFEST_NAME = "manifest_proyecciones.csv"

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
# Al Internet Archive se le habla con un User-Agent honesto: con el de Chrome desde
# python-requests responde 429 (la huella TLS no coincide con la de un navegador).
ARCHIVE_USER_AGENT = "descargas-bcrp/1.0 (python-requests; uso personal, descargas secuenciales)"
CDX_URL = "http://web.archive.org/cdx/search/cdx"
WAYBACK_RAW = "http://web.archive.org/web/{ts}id_/{url}"

# Firma de los primeros bytes según formato (xlsx es un zip).
MAGIC = {"pdf": b"%PDF", "xlsx": b"PK\x03\x04"}
MIME = {"pdf": "application/pdf",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}

MANIFEST_FIELDS = ["fuente", "publicacion", "documento", "archivo", "url_original",
                   "url_descarga", "via", "wayback_timestamp", "bytes", "sha256",
                   "descargado_en", "accion"]

log = logging.getLogger("descargador_proyecciones")


@dataclass
class Doc:
    fuente: str
    publicacion: str
    documento: str
    formato: str
    url: str
    archivo: str


class Client:
    """HTTP secuencial con pausa y reintentos (el Internet Archive a veces responde
    'Temporarily Offline' durante unos minutos)."""

    def __init__(self, pause: float, archive_pause: float = 8.0, retries: int = 5):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT,
                                     "Accept-Language": "es-PE,es;q=0.9"})
        self.pause = pause
        # El Internet Archive limita a ~15 peticiones por minuto y responde 429 si se excede.
        self.archive_pause = archive_pause
        self.retries = retries

    def get(self, url: str, params: dict | None = None, timeout: int = 300,
            ok_status: tuple[int, ...] = (200,)) -> requests.Response | None:
        is_archive = "archive.org" in url
        for attempt in range(1, self.retries + 1):
            time.sleep(self.archive_pause if is_archive else self.pause)
            wait = 15 * attempt
            try:
                headers = {"User-Agent": ARCHIVE_USER_AGENT} if is_archive else None
                r = self.session.get(url, params=params, timeout=timeout, headers=headers)
                offline = b"Temporarily Offline" in r.content[:3000]
                if r.status_code in ok_status and not offline:
                    return r
                if r.status_code == 404:
                    return r
                if r.status_code == 429:
                    wait = max(60 * attempt, int(r.headers.get("Retry-After", "0") or 0))
                msg = "archive offline" if offline else f"HTTP {r.status_code}"
            except requests.RequestException as e:
                msg = str(e)
            if attempt < self.retries:
                log.warning("  intento %d falló (%s); reintento en %d s", attempt, msg, wait)
                time.sleep(wait)
            else:
                log.warning("  sin respuesta válida tras %d intentos (%s)", attempt, msg)
        return None


def load_docs(fuentes: set[str] | None, pubs: set[str] | None) -> list[Doc]:
    with CONFIG_CSV.open(encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["activo"].strip() == "1"]
    docs = [Doc(r["fuente"], r["publicacion"], r["documento"], r["formato"], r["url"],
                r["archivo"]) for r in rows]
    if fuentes:
        docs = [d for d in docs if d.fuente in fuentes]
    if pubs:
        docs = [d for d in docs if d.publicacion in pubs]
    return docs


def looks_valid(content: bytes, formato: str) -> bool:
    """Firma correcta y archivo completo. Algunas capturas de Wayback están truncadas
    (p. ej. exactamente 1 MiB): un PDF debe terminar con '%%EOF' y un xlsx (zip) con el
    registro de fin de directorio central."""
    if content[:4] != MAGIC[formato]:
        return False
    tail = content[-4096:]
    return b"%%EOF" in tail if formato == "pdf" else b"PK\x05\x06" in tail


def wayback_snapshots(client: Client, url: str, formato: str) -> list[str]:
    """Timestamps de capturas del archivo con estado 200 y el tipo MIME correcto,
    de la más antigua a la más reciente (la más antigua es la más cercana a la
    publicación)."""
    # Se consulta sin el esquema ni la query (?v=...) para que coincidan http/https.
    bare = url.split("://", 1)[-1].split("?", 1)[0]
    params = {"url": bare, "fl": "timestamp,statuscode,mimetype,length",
              "filter": ["statuscode:200", f"mimetype:{MIME[formato]}"], "limit": "50"}
    r = client.get(CDX_URL, params=params, timeout=120)
    if r is None or r.status_code != 200:
        return []
    return [line.split()[0] for line in r.text.splitlines() if line.strip()]


def fetch(client: Client, d: Doc, use_wayback: bool) -> tuple[bytes, str, str, str] | None:
    """Devuelve (contenido, url_usada, via, timestamp_wayback) o None."""
    r = client.get(d.url, ok_status=(200,))
    if r is not None and r.status_code == 200 and looks_valid(r.content, d.formato):
        return r.content, d.url, "directo", ""
    why = "404" if (r is not None and r.status_code == 404) else "bloqueado o no válido"
    log.info("  directo: %s", why)
    if not use_wayback:
        return None
    for ts in wayback_snapshots(client, d.url, d.formato):  # de la más antigua a la más reciente
        wurl = WAYBACK_RAW.format(ts=ts, url=d.url.split("?", 1)[0])
        r = client.get(wurl)
        if r is not None and r.status_code == 200 and looks_valid(r.content, d.formato):
            return r.content, wurl, "wayback", ts
        log.info("  captura %s no válida", ts)
    log.info("  wayback: sin capturas válidas del archivo")
    return None


def append_manifest(control: Path, row: dict) -> None:
    path = control / MANIFEST_NAME
    new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


def store(d: Doc, content: bytes, used: str, via: str, ts: str, dest: Path,
          control: Path) -> str:
    """Guarda el archivo en raw/ (con historial si cambió) y lo registra en el manifest."""
    path = dest / d.fuente / d.archivo
    sha = hashlib.sha256(content).hexdigest()
    action = "nuevo"
    if path.exists():
        old_bytes = path.read_bytes()
        old = hashlib.sha256(old_bytes).hexdigest()
        if old == sha:
            action = "sin_cambios"
        elif not looks_valid(old_bytes, d.formato):
            action = "reemplaza_invalido"   # p. ej. captura truncada: no se guarda en historial
        else:
            action = "revisado"
            hist = control / "historial" / "proyecciones"
            hist.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, hist / f"{path.stem}__{dt.date.today():%Y%m%d}{path.suffix}")
    if action != "sin_cambios":
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(content)
        tmp.replace(path)
    log.info("  %s vía %s%s: %.1f MB, sha256 %s…", action, via, f" ({ts})" if ts else "",
             len(content) / 1e6, sha[:12])
    append_manifest(control, {
        "fuente": d.fuente, "publicacion": d.publicacion, "documento": d.documento,
        "archivo": d.archivo, "url_original": d.url, "url_descarga": used, "via": via,
        "wayback_timestamp": ts, "bytes": len(content), "sha256": sha,
        "descargado_en": dt.datetime.now().isoformat(timespec="seconds"), "accion": action,
    })
    return action


def process(client: Client, d: Doc, dest: Path, control: Path, force: bool,
            use_wayback: bool, dry_run: bool) -> str:
    path = dest / d.fuente / d.archivo
    if path.exists() and not force:
        log.info("%-8s %-14s %-8s ya existe", d.fuente, d.publicacion, d.documento)
        return "existente"
    log.info("%-8s %-14s %-8s %s", d.fuente, d.publicacion, d.documento, d.url)
    if dry_run:
        return "dry-run"
    got = fetch(client, d, use_wayback)
    if got is None:
        log.error("  NO CONSEGUIDO: %s %s", d.publicacion, d.documento)
        return "error"
    return store(d, *got, dest, control)


def import_local(d: Doc, src: Path, dest: Path, control: Path) -> str:
    """Registra un archivo oficial bajado a mano con un navegador (p. ej. cuando el
    BCRP bloquea al script y el Internet Archive no tiene copia). Se valida la firma
    y queda en el manifest con via=manual; la URL original es la de la config."""
    content = src.read_bytes()
    if not looks_valid(content, d.formato):
        log.error("%s no parece un %s (firma %r)", src, d.formato, content[:8])
        return "error"
    log.info("%-8s %-14s %-8s importado desde %s", d.fuente, d.publicacion, d.documento, src.name)
    return store(d, content, f"archivo local: {src.name}", "manual", "", dest, control)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fuente", nargs="+", help="BCRP_RI y/o MEF_MMM")
    ap.add_argument("--publicacion", nargs="+", help="p. ej. RI-2026-06 MMM-2027-2030")
    ap.add_argument("--forzar", action="store_true", help="volver a bajar aunque exista")
    ap.add_argument("--sin-wayback", action="store_true", help="no usar el Internet Archive")
    ap.add_argument("--dry-run", action="store_true", help="no descarga ni escribe")
    ap.add_argument("--pausa", type=float, default=2.0, help="segundos entre peticiones")
    ap.add_argument("--pausa-archivo", type=float, default=5.0,
                    help="segundos entre peticiones al Internet Archive (límite ~15/min)")
    ap.add_argument("--importar", type=Path, metavar="ARCHIVO",
                    help="registrar un archivo bajado a mano (requiere una sola --publicacion)")
    ap.add_argument("--documento", default="informe", help="con --importar: informe o cuadros")
    ap.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    ap.add_argument("--control", type=Path, default=DEFAULT_CONTROL)
    args = ap.parse_args(argv)

    (args.control / "logs").mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler(args.control / "logs" / f"{stamp}_proyecciones.log",
                                      encoding="utf-8")])

    client = Client(args.pausa, args.pausa_archivo)
    docs = load_docs(set(args.fuente) if args.fuente else None,
                     set(args.publicacion) if args.publicacion else None)
    if args.importar:
        docs = [d for d in docs if d.documento == args.documento]
        if len(docs) != 1:
            log.error("--importar requiere que --publicacion/--documento identifiquen una sola fila")
            return 1
        return 0 if import_local(docs[0], args.importar, args.dest, args.control) != "error" else 1
    log.info("Documentos a procesar: %d%s", len(docs), " (dry-run)" if args.dry_run else "")
    counts: dict[str, int] = {}
    for d in docs:
        action = process(client, d, args.dest, args.control, args.forzar,
                         not args.sin_wayback, args.dry_run)
        counts[action] = counts.get(action, 0) + 1
    log.info("Resumen: %s", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return 1 if counts.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
