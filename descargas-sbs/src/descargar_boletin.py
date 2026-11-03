"""Descargador de reportes del Boletín Estadístico de la SBS.

Recorre las series de `config/series.csv`, consulta al servidor de la SBS
(intranet2.sbs.gob.pe) qué periodos existen y descarga solo lo nuevo o lo
republicado. Las versiones reemplazadas se conservan en la carpeta de historial.

Uso:
    python descargar_boletin.py                       # corrida normal (revisa todo)
    python descargar_boletin.py --dry-run             # solo informa, no descarga
    python descargar_boletin.py --serie B-2201 --desde 202401
    python descargar_boletin.py --barrido 1           # incremental + revisa t-1 y t
    python descargar_boletin.py --barrido 6           # incremental + revisa de t-6 a t

Sin --barrido es la revisión completa: consulta todos los meses de todas las series (también
los huecos) y, al terminar el recorrido, deja la marca `data/_control/ultima_revision_completa.txt`.
Con --barrido N la corrida es incremental: por cada serie, t = último periodo que ya tenemos;
se consultan los meses posteriores a t (nuevos) y se revisan de t-N a t (republicaciones).

Las descargas son secuenciales y con pausa: Imperva (el CDN de la SBS) corta
la conexión si se hacen peticiones en paralelo.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import email.utils
import hashlib
import logging
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import requests

PROJECT_DIR = Path(__file__).resolve().parents[1]
SERIES_CSV = PROJECT_DIR / "config" / "series.csv"
DEFAULT_DEST = PROJECT_DIR / "data" / "raw"
# Historial, manifest y logs van FUERA de data/raw: Folder.Files de Power BI es
# recursivo y leería las versiones anteriores como si fueran datos vigentes.
DEFAULT_CONTROL = PROJECT_DIR / "data" / "_control"

BASE_URL = "https://intranet2.sbs.gob.pe/estadistica/financiera"
MONTH_FOLDERS = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
                 "Agosto", "Setiembre", "Octubre", "Noviembre", "Diciembre"]
MONTH_ABBR = ["en", "fe", "ma", "ab", "my", "jn", "jl", "ag", "se", "oc", "no", "di"]
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
# Firmas válidas: Excel 97-2003 (OLE) y Excel 2007+ (ZIP). Algunos .XLS de la SBS son xlsx.
EXCEL_MAGIC = (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", b"PK\x03\x04")

MANIFEST_FIELDS = ["carpeta", "archivo", "periodo", "url", "server_fecha",
                   "server_bytes", "sha256", "descargado_en", "accion"]

log = logging.getLogger("descargador_sbs")


@dataclass
class Series:
    subsistema: str
    tema: str
    codigo: str
    fuente: str
    desde: int
    hasta: int | None = None  # último periodo (series sustitutas que dejan de usarse); None = sin fin

    @property
    def carpeta(self) -> str:
        return f"{self.fuente}/{self.subsistema}/{self.tema}"


@dataclass
class RemoteInfo:
    size: int
    last_modified: dt.datetime


class SbsClient:
    """Cliente HTTP secuencial con pausa y reintentos."""

    def __init__(self, pause: float, retries: int = 5):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.pause = pause
        self.retries = retries

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        for attempt in range(1, self.retries + 1):
            time.sleep(self.pause)
            try:
                resp = self.session.request(method, url, timeout=60, **kwargs)
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"HTTP {resp.status_code}")
                return resp
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as exc:
                wait = 10 * attempt
                log.warning("Error de red (%s) en %s; reintento %d/%d en %ds",
                            exc, url, attempt, self.retries, wait)
                time.sleep(wait)
        raise RuntimeError(f"Sin respuesta tras {self.retries} intentos: {url}")

    def head(self, url: str) -> RemoteInfo | None:
        resp = self._request("HEAD", url, allow_redirects=True)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return RemoteInfo(
            size=int(resp.headers["Content-Length"]),
            last_modified=email.utils.parsedate_to_datetime(resp.headers["Last-Modified"]),
        )

    def download(self, url: str, target: Path) -> None:
        resp = self._request("GET", url, stream=True)
        resp.raise_for_status()
        with open(target, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 16):
                fh.write(chunk)


def build_file_name(codigo: str, periodo: int) -> str:
    year, month = divmod(periodo, 100)
    return f"{codigo}-{MONTH_ABBR[month - 1]}{year}.XLS"


def build_url(codigo: str, periodo: int) -> str:
    year, month = divmod(periodo, 100)
    return f"{BASE_URL}/{year}/{MONTH_FOLDERS[month - 1]}/{build_file_name(codigo, periodo)}"


def iter_periods(start: int, end: int):
    year, month = divmod(start, 100)
    while year * 100 + month <= end:
        yield year * 100 + month
        month += 1
        if month > 12:
            year, month = year + 1, 1


def shift_period(periodo: int, months: int) -> int:
    year, month = divmod(periodo, 100)
    total = year * 12 + (month - 1) + months
    return (total // 12) * 100 + total % 12 + 1


def select_periods(periods: list[int], has_local, barrido: int | None) -> list[int]:
    """Meses a consultar de una serie.

    barrido None = revisión completa (todos). Con barrido N: t = último mes que ya tenemos;
    se consultan los posteriores a t y se revisan de t-N a t. Lo anterior a t-N (incluidos
    los huecos, meses que la SBS nunca publicó) solo se consulta en la revisión completa.
    Si no tenemos ningún mes de la serie, se consultan todos (serie nueva).
    """
    if barrido is None:
        return list(periods)
    locales = [p for p in periods if has_local(p)]
    if not locales:
        return list(periods)
    desde = shift_period(max(locales), -barrido)
    return [p for p in periods if p >= desde]


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_valid_excel(path: Path, expected_size: int) -> bool:
    with open(path, "rb") as fh:
        head = fh.read(8)
    return path.stat().st_size == expected_size and head.startswith(EXCEL_MAGIC)


def load_series(path: Path) -> list[Series]:
    with open(path, encoding="utf-8") as fh:
        return [Series(r["subsistema"], r["tema"], r["codigo"], r["fuente"], int(r["desde"]),
                       int(r["hasta"]) if (r.get("hasta") or "").strip() else None)
                for r in csv.DictReader(fh) if r["activo"].strip() == "1"]


def load_manifest(path: Path) -> dict[tuple[str, str], dict]:
    """Último registro por (carpeta, archivo)."""
    if not path.exists():
        return {}
    with open(path, encoding="utf-8", newline="") as fh:
        return {(r["carpeta"], r["archivo"]): r for r in csv.DictReader(fh)}


def append_manifest(path: Path, row: dict) -> None:
    is_new = not path.exists()
    with open(path, "a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=MANIFEST_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow(row)


def needs_check(local: Path, remote: RemoteInfo, record: dict | None) -> bool:
    """¿El archivo del servidor podría ser distinto al local?"""
    if record is not None:
        return (int(record["server_bytes"]) != remote.size
                or record["server_fecha"] != remote.last_modified.isoformat())
    # Sin historial: comparamos contra el archivo local (descargado a mano).
    local_mtime = dt.datetime.fromtimestamp(local.stat().st_mtime, dt.timezone.utc)
    return local.stat().st_size != remote.size or remote.last_modified > local_mtime


def process_file(client: SbsClient, series: Series, periodo: int, dest: Path,
                 control: Path, manifest: dict, dry_run: bool) -> str:
    file_name = build_file_name(series.codigo, periodo)
    url = build_url(series.codigo, periodo)
    local = dest / series.carpeta / file_name
    record = manifest.get((series.carpeta, file_name))

    remote = client.head(url)
    if remote is None:
        return "no_publicado"
    if local.exists() and not needs_check(local, remote, record):
        return "sin_cambios"

    action = "nuevo" if not local.exists() else "revisar"
    if dry_run:
        log.info("[dry-run] %s %s/%s (servidor %s, %d bytes)", action, series.carpeta,
                 file_name, remote.last_modified.date(), remote.size)
        return action

    tmp_dir = control / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp = tmp_dir / file_name
    client.download(url, tmp)
    if not is_valid_excel(tmp, remote.size):
        tmp.unlink(missing_ok=True)
        raise ValueError(f"Descarga inválida (no es Excel o tamaño distinto): {url}")

    new_hash = sha256_of(tmp)
    if local.exists():
        if sha256_of(local) == new_hash:
            # Mismo contenido: solo registramos la fecha del servidor.
            tmp.unlink()
            action = "registrado"
        else:
            stamp = dt.datetime.fromtimestamp(local.stat().st_mtime).strftime("%Y%m%d")
            archived = control / "historial" / series.carpeta / f"{local.stem}__{stamp}{local.suffix}"
            archived.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(local, archived)
            action = "republicado"
            log.info("Versión anterior guardada en %s", archived)

    if action != "registrado":
        local.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(tmp, local)
        log.info("%s: %s/%s", action.upper(), series.carpeta, file_name)

    row = {"carpeta": series.carpeta, "archivo": file_name, "periodo": periodo, "url": url,
           "server_fecha": remote.last_modified.isoformat(), "server_bytes": remote.size,
           "sha256": new_hash, "descargado_en": dt.datetime.now().isoformat(timespec="seconds"),
           "accion": action}
    append_manifest(control / "manifest.csv", row)
    manifest[(series.carpeta, file_name)] = row
    return action


def prevent_sleep() -> None:
    """Evita que Windows suspenda el equipo mientras corre el proceso.

    Si la laptop se suspende, la petición en curso queda congelada durante horas.
    El estado se libera solo al terminar el proceso.
    """
    if sys.platform == "win32":
        import ctypes
        es_continuous, es_system_required = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(es_continuous | es_system_required)


def setup_logging(control: Path) -> Path:
    log_dir = control / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{dt.datetime.now():%Y%m%d_%H%M%S}.log"
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S")
    for handler in (logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler()):
        handler.setFormatter(fmt)
        log.addHandler(handler)
    log.setLevel(logging.INFO)
    return log_file


def parse_args() -> argparse.Namespace:
    today = dt.date.today()
    parser = argparse.ArgumentParser(description="Descarga reportes del Boletín Estadístico SBS.")
    parser.add_argument("--destino", type=Path, default=DEFAULT_DEST,
                        help="Carpeta raíz de los Excel (por defecto, data/raw del proyecto).")
    parser.add_argument("--control", type=Path, default=None,
                        help="Carpeta de manifest, historial y logs (por defecto, data/_control).")
    parser.add_argument("--serie", action="append",
                        help="Código(s) a procesar, p. ej. B-2201. Repetible.")
    parser.add_argument("--desde", type=int, help="Periodo inicial AAAAMM (ignora el de series.csv).")
    parser.add_argument("--hasta", type=int, default=today.year * 100 + today.month,
                        help="Periodo final AAAAMM (por defecto, el mes actual).")
    parser.add_argument("--barrido", type=int, default=None,
                        help="Incremental: meses nuevos + revisión de t-N a t, con t = último mes "
                             "que tenemos de cada serie. Sin esta opción: revisión completa.")
    parser.add_argument("--pausa", type=float, default=1.0, help="Segundos entre peticiones.")
    parser.add_argument("--dry-run", action="store_true", help="Solo informa; no descarga nada.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    control = args.control or (DEFAULT_CONTROL if args.destino == DEFAULT_DEST
                               else args.destino.parent / "_control")
    log_file = setup_logging(control)
    prevent_sleep()
    log.info("Destino: %s | Control: %s | dry-run: %s", args.destino, control, args.dry_run)

    series_list = [s for s in load_series(SERIES_CSV) if s.fuente == "boletin"]
    if args.serie:
        series_list = [s for s in series_list if s.codigo in args.serie]
    manifest = load_manifest(control / "manifest.csv")
    client = SbsClient(pause=args.pausa)

    log.info("Modo: %s", "revisión completa" if args.barrido is None
             else f"incremental con barrido t-{args.barrido}")
    totals: dict[str, int] = {}
    errors = 0
    for series in series_list:
        start = args.desde or series.desde
        end = min(args.hasta, series.hasta) if series.hasta else args.hasta
        carpeta = args.destino / series.carpeta
        periods = select_periods(
            list(iter_periods(start, end)),
            lambda p: (carpeta / build_file_name(series.codigo, p)).exists(),
            args.barrido)
        for periodo in periods:
            try:
                action = process_file(client, series, periodo, args.destino, control,
                                      manifest, args.dry_run)
            except Exception as exc:  # una falla no detiene el resto
                log.error("FALLA %s %s: %s", series.codigo, periodo, exc)
                action, errors = "error", errors + 1
            totals[action] = totals.get(action, 0) + 1

    summary = ", ".join(f"{k}={v}" for k, v in sorted(totals.items()))
    log.info("Resumen: %s", summary)
    # La marca solo se deja si el recorrido completo llegó al final (no si se cortó a mano).
    if args.barrido is None and not (args.serie or args.desde or args.dry_run):
        marca = control / "ultima_revision_completa.txt"
        marca.write_text(f"{dt.date.today():%Y%m} {dt.datetime.now():%Y-%m-%d %H:%M} "
                         f"errores={errors} {summary}\n", encoding="utf-8")
        log.info("Revisión completa terminada: marca en %s", marca)
    log.info("Log: %s", log_file)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
