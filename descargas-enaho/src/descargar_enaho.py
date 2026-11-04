"""Descarga la ENAHO anual (zips de microdatos + documentación) del portal de microdatos del INEI.

- Microdatos → data/raw/<año>/AAAAMMDD_enaho<año>_<código>-Modulo<NN>.zip  (sin descomprimir)
  Formato CSV desde 2008; STATA para 2004-2007 (el portal no ofrece CSV esos años).
- Documentación → docs/enaho/<año>/  completa para el último año; para los demás solo
  diccionario, ficha técnica y cuestionario ENAHO.01 (sirven para detectar cambios entre años).
- Registro de cada descarga → data/_control/manifest.csv

Uso:
    python src/descargar_enaho.py                          # último año publicado
    python src/descargar_enaho.py 2023 2024                # años puntuales
    python src/descargar_enaho.py --desde 2004             # toda la serie
    python src/descargar_enaho.py --desde 2004 --estimar   # solo tamaños, no descarga
    python src/descargar_enaho.py 2025 --all               # todos los módulos, no solo los de config

Política de descarga (igual que descargas-sbs): peticiones secuenciales, pausa entre
cada una, reintentos con espera creciente ante errores 429/5xx, y escritura a un
archivo .part que solo se renombra si el zip está completo.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import logging
import re
import time
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
CONTROL_DIR = ROOT / "data" / "_control"
MANIFEST = CONTROL_DIR / "manifest.csv"
SIZES_FILE = CONTROL_DIR / "tamanos_portal.csv"
DOCS_DIR = ROOT / "docs" / "enaho"
MODULES_FILE = ROOT / "config" / "modulos.csv"

PORTAL = "https://proyectos.inei.gob.pe/microdatos"
BASE = "https://proyectos.inei.gob.pe"
SURVEY = "Condiciones de Vida y Pobreza - ENAHO"  # metodología actualizada
PERIOD_ANNUAL = "55"  # Anual (Ene-Dic)
FIRST_YEAR = 2004
FORMATS = ("CSV", "STATA")  # en orden de preferencia
SHORT_DOCS = re.compile(r"diccionario|ficha|cuestionario-enaho01\.zip", re.IGNORECASE)
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
MANIFEST_FIELDS = ["fecha_descarga", "anio", "modulo", "formato", "archivo", "url",
                   "bytes", "sha256"]

log = logging.getLogger("enaho")


class InieClient:
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
                resp = self.session.request(method, url, timeout=120, **kwargs)
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"HTTP {resp.status_code}")
                return resp
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as exc:
                wait = 10 * attempt
                log.warning("Error de red (%s) en %s; reintento %d/%d en %ds",
                            exc, url, attempt, self.retries, wait)
                time.sleep(wait)
        raise RuntimeError(f"Sin respuesta tras {self.retries} intentos: {url}")

    def post_text(self, page: str, year: int) -> str:
        fields = {"bandera": "1", "_cmbEncuesta": SURVEY, "_cmbAnno": str(year),
                  "_cmbTrimestre": PERIOD_ANNUAL}
        resp = self._request("POST", f"{PORTAL}/{page}", data=fields)
        resp.raise_for_status()
        return resp.content.decode("latin1")

    def size(self, url_path: str) -> int | None:
        resp = self._request("HEAD", f"{BASE}{url_path}", allow_redirects=True)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return int(resp.headers.get("Content-Length", 0)) or None

    def download(self, url_path: str, target: Path) -> None:
        part = target.with_name(target.name + ".part")
        resp = self._request("GET", f"{BASE}{url_path}", stream=True)
        resp.raise_for_status()
        with open(part, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
        with zipfile.ZipFile(part) as zf:
            bad = zf.testzip()
        if bad:
            raise RuntimeError(f"Zip dañado ({bad}): {url_path}")
        part.replace(target)


def configured_modules() -> dict[str, str]:
    with open(MODULES_FILE, encoding="utf-8") as fh:
        return {r["modulo"]: r["nombre"] for r in csv.DictReader(fh) if r["activo"] == "1"}


def module_links(client: InieClient, year: int) -> tuple[str, dict[str, str]]:
    """(formato, {número de módulo: ruta del zip}) publicados para la ENAHO anual del año."""
    html = client.post_text("cambiaPeriodo.asp", year)
    for fmt in FORMATS:
        links = re.findall(rf'href="(/iinei/srienaho/descarga/{fmt}/\d+-Modulo(\d+)\.zip)"', html)
        if links:
            return fmt, {num: path for path, num in links}
    return "", {}


def doc_links(client: InieClient, year: int) -> list[str]:
    html = client.post_text("CambiaPeriodoDoc.asp", year)
    return re.findall(r'href="(/iinei/srienaho/descarga/DocumentosZIP/[^"]+\.zip)"', html)


def append_manifest(row: dict) -> None:
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    is_new = not MANIFEST.exists()
    with open(MANIFEST, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=MANIFEST_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow(row)


def download_module(client: InieClient, year: int, module: str, fmt: str, url_path: str) -> None:
    original = Path(url_path).stem  # p. ej. 1031-Modulo13
    year_dir = RAW_DIR / str(year)
    if list(year_dir.glob(f"*_enaho{year}_{original}.zip")):
        log.info("[omitido] %s (%d): ya existe en data/raw", original, year)
        return
    year_dir.mkdir(parents=True, exist_ok=True)
    today = dt.date.today()
    target = year_dir / f"{today:%Y%m%d}_enaho{year}_{original}.zip"
    client.download(url_path, target)
    append_manifest({
        "fecha_descarga": today.isoformat(), "anio": year, "modulo": module, "formato": fmt,
        "archivo": target.relative_to(ROOT).as_posix(), "url": f"{BASE}{url_path}",
        "bytes": target.stat().st_size,
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
    })
    log.info("[ok] %s (%.1f MB)", target.name, target.stat().st_size / 1e6)


def download_docs(client: InieClient, year: int, full: bool) -> None:
    out_dir = DOCS_DIR / str(year)
    for url_path in doc_links(client, year):
        name = Path(url_path).stem
        if (out_dir / name).exists() or not (full or SHORT_DOCS.search(Path(url_path).name)):
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / f"{name}.zip"
        client.download(url_path, target)
        with zipfile.ZipFile(target) as zf:
            zf.extractall(out_dir / name)
        target.unlink()  # se conserva solo el contenido extraído (PDF)
        log.info("[doc] %d/%s", year, name)


def estimate(client: InieClient, years: list[int], modules: set[str] | None) -> None:
    """Consulta tamaños (HEAD) sin descargar y los guarda en data/_control/."""
    rows = []
    for year in years:
        fmt, links = module_links(client, year)
        links = {m: p for m, p in links.items() if modules is None or m in modules}
        for module, url_path in sorted(links.items()):
            rows.append({"anio": year, "modulo": module, "formato": fmt,
                         "zip": Path(url_path).name, "bytes": client.size(url_path) or ""})
        year_mb = sum(r["bytes"] or 0 for r in rows if r["anio"] == year) / 1e6
        log.info("%d: %d módulos (%s), %.1f MB", year, len(links), fmt or "-", year_mb)

    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    with open(SIZES_FILE, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["anio", "modulo", "formato", "zip", "bytes"])
        writer.writeheader()
        writer.writerows(rows)
    log.info("Total: %d zips, %.2f GB → %s", len(rows),
             sum(r["bytes"] or 0 for r in rows) / 1e9, SIZES_FILE.relative_to(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("years", nargs="*", type=int)
    parser.add_argument("--desde", type=int, help="todos los años desde este hasta el actual")
    parser.add_argument("--all", action="store_true", help="todos los módulos publicados")
    parser.add_argument("--no-docs", action="store_true", help="omitir documentación")
    parser.add_argument("--estimar", action="store_true", help="solo consultar tamaños")
    parser.add_argument("--pausa", type=float, default=1.0, help="segundos entre peticiones")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

    client = InieClient(pause=args.pausa)
    modules = None if args.all else set(configured_modules())
    years = set(args.years)
    if args.desde:
        years |= set(range(max(args.desde, FIRST_YEAR), dt.date.today().year + 1))
    if not years:  # por defecto, el último año publicado
        year = dt.date.today().year
        while not module_links(client, year)[1]:
            year -= 1
        years = {year}

    if args.estimar:
        estimate(client, sorted(years), modules)
        return

    latest = None
    for year in sorted(years):
        fmt, links = module_links(client, year)
        if not links:
            log.info("%d: sin ENAHO anual publicada", year)
            continue
        latest = year
        if modules is not None and (missing := modules - set(links)):
            log.warning("ENAHO %d: módulos no publicados %s", year, sorted(missing))
        for module, url_path in sorted(links.items()):
            if modules is None or module in modules:
                download_module(client, year, module, fmt, url_path)
    if not args.no_docs:
        for year in sorted(years):
            if year <= (latest or 0):
                download_docs(client, year, full=(year == latest))


if __name__ == "__main__":
    main()
