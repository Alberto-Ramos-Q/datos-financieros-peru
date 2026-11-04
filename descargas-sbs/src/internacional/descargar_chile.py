"""Descargador de archivos oficiales de la CMF (Chile) para la serie de concentración bancaria.

Lee una página índice oficial de la CMF, ubica el archivo de DICIEMBRE de cada año pedido y lo
descarga a `data/raw/internacional/chile/`. Cada descarga queda registrada en
`data/_control/internacional/chile_manifest.csv` (archivo, url, fecha del servidor, bytes,
sha256, fecha de descarga).

Fuentes (`--fuente`):
- `reporte`: «Reporte Mensual de Información Financiera del Sistema Bancario» (Excel,
  consolidado). Es la fuente principal.
- `textos`: «Balance y Estado de Situación Bancos» (zip con archivos de texto b1, b2, c1, c2,
  r1). Desde 2022 trae el b2 (estado de situación financiera individual), que da la base
  individual de colocaciones.
- `filiales`: «Matrices y filiales» (PDF trimestral). Solo lista sociedades chilenas con RUT;
  no sirve para filiales en el exterior (se dejó para documentar la búsqueda).
- `--eeff-anuales AÑO`: estados financieros anuales auditados (PDF) que la CMF aloja, para los
  bancos de `--bancos`. Se usan para documentar filiales en el exterior.

Uso:
    python src/internacional/descargar_chile.py                  # reportes dic-2015 a dic-2025
    python src/internacional/descargar_chile.py --fuente todo    # reportes + zips de texto
    python src/internacional/descargar_chile.py --fuente filiales --desde 2025 --hasta 2025
    python src/internacional/descargar_chile.py --eeff-anuales 2025 --bancos 016 039 059 051 053
    python src/internacional/descargar_chile.py --dry-run        # solo lista lo que bajaría
    python src/internacional/descargar_chile.py --forzar         # vuelve a bajar aunque exista

Política de descargas (igual que `src/descargar_boletin.py`, clase SbsClient):
- una sola petición a la vez (secuencial), con pausa de al menos 1,5 s entre peticiones;
- reintentos con espera creciente ante 429 y 5xx;
- User-Agent de navegador genérico;
- escritura a `.part` y renombrado solo si la firma del archivo (OLE o ZIP) es válida;
- ante un bloqueo (403, captcha o desafío antibots) el proceso se DETIENE: no se intenta saltar.

Trampa conocida de la página: en el HTML visible, el enlace de cada mes aparece ANTES de su
título; tomar «el enlace que sigue al título» da el mes anterior. Por eso aquí se lee cada
bloque `<article ... aid-N>` completo, donde el enlace, el `aria-label` («Descargar Diciembre
2025») y el título van juntos, y se exige que los tres coincidan.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import email.utils
import hashlib
import logging
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

import requests

PROJECT_DIR = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_DIR / "data" / "raw" / "internacional" / "chile"
CONTROL_DIR = PROJECT_DIR / "data" / "_control" / "internacional"
MANIFEST_PATH = CONTROL_DIR / "chile_manifest.csv"

INDEX_URL = "https://www.cmfchile.cl/portal/estadisticas/626/w4-propertyvalue-28911.html"
ALLOWED_HOST = "www.cmfchile.cl"
INDEX_FILE_NAME = "indice_reporte_mensual_bancos.html"
REPORT_TITLE = "Reporte Mensual de Información Financiera del Sistema Bancario"


@dataclass(frozen=True)
class Source:
    """Una página índice de la CMF y el tipo de archivo mensual que lista."""
    key: str
    index_url: str
    index_file_name: str
    title: str            # prefijo del título de cada bloque, antes de «<mes> <año>»
    extensions: tuple[str, ...]


SOURCES = {
    # Reporte mensual en Excel (fuente principal de la serie).
    "reporte": Source("reporte", INDEX_URL, INDEX_FILE_NAME, REPORT_TITLE, ("xlsx", "xls")),
    # Estados financieros mensuales en texto (zip con un archivo por banco y formulario).
    # Se usa para revisar si la CMF publica balances individuales además de consolidados.
    "textos": Source("textos",
                     "https://www.cmfchile.cl/portal/estadisticas/626/w4-propertyvalue-30250.html",
                     "indice_estados_financieros_bancos.html",
                     "Balance y Estado de Situación Bancos", ("zip",)),
    # Listado trimestral de matrices y filiales (PDF): para documentar filiales en el exterior.
    # La página no llega a 2015: usar con --desde/--hasta acotados (p. ej. 2025).
    "filiales": Source("filiales",
                       "https://www.cmfchile.cl/portal/estadisticas/626/w4-propertyvalue-46305.html",
                       "indice_matrices_filiales.html", "Matrices y filiales", ("pdf",)),
}

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
MIN_PAUSE = 1.5
# Firmas válidas: Excel 97-2003 (OLE) y Excel 2007+ (ZIP).
FILE_MAGIC = {".xls": b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", ".xlsx": b"PK\x03\x04",
              ".zip": b"PK\x03\x04", ".pdf": b"%PDF"}
# Señales de una página de desafío o bloqueo en lugar del contenido esperado.
BLOCK_MARKERS = ("captcha", "cf-challenge", "challenge-platform", "access denied",
                 "request unsuccessful", "incapsula", "_incapsula_resource")

MONTHS_ES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto",
             "Septiembre", "Octubre", "Noviembre", "Diciembre"]

MANIFEST_FIELDS = ["archivo", "archivo_original", "periodo", "titulo", "url", "server_fecha",
                   "server_bytes", "sha256", "descargado_en", "accion"]

log = logging.getLogger("descargador_cmf")


class BlockedError(RuntimeError):
    """El servidor respondió con un bloqueo (403, captcha o desafío). Hay que detenerse."""


@dataclass
class ReportLink:
    aid: str
    year: int
    month: int
    title: str
    url: str
    original_name: str

    @property
    def periodo(self) -> int:
        return self.year * 100 + self.month

    @property
    def local_name(self) -> str:
        # Nombre original de la CMF + periodo, para que se lea sin abrir el manifest.
        stem, ext = self.original_name.rsplit(".", 1)
        return f"{stem}__{self.periodo}.{ext.lower()}"


class CmfClient:
    """Cliente HTTP secuencial con pausa, reintentos y detección de bloqueos."""

    def __init__(self, pause: float = MIN_PAUSE, retries: int = 5):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.pause = max(pause, MIN_PAUSE)
        self.retries = retries

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        if requests.utils.urlparse(url).hostname != ALLOWED_HOST:
            raise ValueError(f"Solo se consulta {ALLOWED_HOST}: {url}")
        for attempt in range(1, self.retries + 1):
            time.sleep(self.pause)
            try:
                resp = self.session.request(method, url, timeout=90, **kwargs)
            except (requests.ConnectionError, requests.Timeout) as exc:
                wait = 15 * attempt
                log.warning("Error de red (%s) en %s; reintento %d/%d en %ds",
                            exc, url, attempt, self.retries, wait)
                time.sleep(wait)
                continue
            if resp.status_code == 403:
                raise BlockedError(f"HTTP 403 en {url}: posible bloqueo. Se detiene la descarga.")
            if resp.status_code in (429, 500, 502, 503, 504):
                wait = 15 * attempt
                log.warning("HTTP %d en %s; reintento %d/%d en %ds",
                            resp.status_code, url, attempt, self.retries, wait)
                resp.close()
                time.sleep(wait)
                continue
            return resp
        raise RuntimeError(f"Sin respuesta válida tras {self.retries} intentos: {url}")

    def get_text(self, url: str, expected: str = REPORT_TITLE) -> tuple[str, bytes]:
        """Baja una página HTML; si parece un desafío antibots y no trae `expected`, se detiene."""
        resp = self._request("GET", url)
        resp.raise_for_status()
        content = resp.content
        # La CMF declara UTF-8 pero sirve la página en Windows-1252: se prueba en ese orden.
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("cp1252")
        lowered = text.lower()
        if expected.lower() not in lowered:
            if any(marker in lowered for marker in BLOCK_MARKERS):
                raise BlockedError(f"La respuesta de {url} parece un desafío antibots. Se detiene.")
            raise ValueError(f"La página {url} no contiene «{expected}»: ¿cambió el sitio?")
        return text, content

    def download(self, url: str, target: Path) -> dict:
        """Descarga a `target` (ya con sufijo .part). Devuelve metadatos del servidor.

        Los reportes pesan menos de 1 MB: se reciben completos en memoria, se valida el tamaño
        contra el Content-Length, se escriben al `.part` y se relee el `.part` para comparar
        su sha256 con el de lo recibido. En la primera corrida (2026-11-03), escribiendo por
        trozos directo a la unidad G: (Google Drive), tres archivos quedaron en 65 536 bytes;
        en memoria el mismo archivo llegó entero. Si algo no cuadra, se reintenta con espera
        creciente.
        """
        for attempt in range(1, self.retries + 1):
            resp = self._request("GET", url)
            resp.raise_for_status()
            content_type = resp.headers.get("Content-Type", "")
            if "text/html" in content_type.lower():
                raise BlockedError(f"Se esperaba un Excel y llegó HTML desde {url}. Se detiene.")
            last_modified = resp.headers.get("Last-Modified")
            expected = resp.headers.get("Content-Length")
            expected = int(expected) if expected else None
            content = resp.content
            problem = None
            if expected is not None and len(content) != expected:
                problem = f"recibidos {len(content)} de {expected} bytes"
            else:
                target.write_bytes(content)
                if hashlib.sha256(target.read_bytes()).hexdigest() != hashlib.sha256(content).hexdigest():
                    problem = "el .part escrito no coincide con lo recibido"
            if problem is None:
                return {
                    "server_fecha": (email.utils.parsedate_to_datetime(last_modified).isoformat()
                                     if last_modified else ""),
                    "content_length": expected,
                }
            wait = 15 * attempt
            log.warning("Descarga inválida (%s) en %s; reintento %d/%d en %ds",
                        problem, url, attempt, self.retries, wait)
            time.sleep(wait)
        raise RuntimeError(f"Descarga incompleta tras {self.retries} intentos: {url}")


def parse_index(html: str, source: Source | None = None) -> list[ReportLink]:
    """Extrae todos los archivos mensuales de una página índice de la CMF.

    Cada archivo es un bloque `<article ... aid-N>` con: el enlace
    (`articles-N_recurso_1.<ext>`), el `aria-label` «Descargar <Mes> <Año>» y el título
    («Reporte Mensual ... - <Mes> <Año>» o «Balance y Estado de Situación Bancos <mes> <año>»).
    Se exige que el `aid` del bloque, el del enlace, el mes del `aria-label` y el del título
    coincidan.
    """
    source = source or SOURCES["reporte"]
    links: list[ReportLink] = []
    pattern = re.compile(r'<article class="card ntg-recuadro-documento articulo cid-\d+ aid-(\d+)"'
                         r'.*?</article>', re.S)
    ext_pattern = "|".join(source.extensions)
    title_regex = re.compile(rf"^{re.escape(source.title)}\s*-?\s*(\w+)\s+(\d{{4}})$", re.I)
    for match in pattern.finditer(html):
        block, aid = match.group(0), match.group(1)
        href = re.search(rf'href="(articles-(\d+)_recurso_1\.({ext_pattern}))(\?[^"]*)?"',
                         block, re.I)
        # «Descargar Diciembre 2025 (xlsx...)» o «Descargar Filiales vigentes (A diciembre 2025)».
        aria = re.search(r'aria-label="Descargar [^"]*?\b(' + "|".join(MONTHS_ES + ["Setiembre"])
                         + r')\s+(\d{4})', block, re.I)
        title = re.search(r'card-title[^>]*>\s*<a[^>]*>\s*([^<]+?)\s*</a>', block)
        if not (href and aria and title):
            continue
        title_text = re.sub(r"\s+", " ", title.group(1)).strip()
        title_match = title_regex.search(title_text)
        if not title_match:
            continue
        if href.group(2) != aid:
            raise ValueError(f"Bloque {aid}: el enlace apunta a otro artículo ({href.group(1)})")
        # En los reportes antiguos el aria-label trae el mes en minúscula («diciembre 2018»).
        # Si no coinciden, el bloque es ambiguo y se descarta (la página de estados financieros
        # tiene uno: aid 39990, título «marzo 2019» y aria-label «Marzo 2020»). Si el descartado
        # fuera un diciembre pedido, `select_december` lo reporta como faltante.
        if ((aria.group(1).lower(), aria.group(2))
                != (title_match.group(1).lower(), title_match.group(2))):
            log.warning("Bloque %s descartado: aria-label «%s %s» y título «%s» no coinciden",
                        aid, aria.group(1), aria.group(2), title_text)
            continue
        month_name = title_match.group(1).capitalize()
        if month_name == "Setiembre":
            month_name = "Septiembre"
        month = MONTHS_ES.index(month_name) + 1
        links.append(ReportLink(aid=aid, year=int(title_match.group(2)), month=month,
                                title=title_text, url=urljoin(source.index_url, href.group(1)),
                                original_name=href.group(1)))
    return links


def select_december(links: list[ReportLink], first: int, last: int) -> list[ReportLink]:
    """Un reporte de diciembre por año; falla si falta alguno o hay duplicados."""
    selected: dict[int, ReportLink] = {}
    for link in links:
        if link.month == 12 and first <= link.year <= last:
            if link.year in selected:
                raise ValueError(f"Hay dos reportes de diciembre de {link.year}: "
                                 f"{selected[link.year].aid} y {link.aid}")
            selected[link.year] = link
    missing = [y for y in range(first, last + 1) if y not in selected]
    if missing:
        raise ValueError(f"No se encontró el reporte de diciembre de: {missing}")
    urls = [l.url for l in selected.values()]
    if len(set(urls)) != len(urls):
        raise ValueError("Dos años apuntan al mismo archivo")
    return [selected[y] for y in sorted(selected)]


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def has_valid_signature(path: Path, suffix: str) -> bool:
    with open(path, "rb") as fh:
        head = fh.read(8)
    return head.startswith(FILE_MAGIC[suffix])


def append_manifest(row: dict) -> None:
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    is_new = not MANIFEST_PATH.exists()
    with open(MANIFEST_PATH, "a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=MANIFEST_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow(row)


def save_index(content: bytes, source: Source) -> None:
    """Guarda la página índice tal como llegó (traza de qué enlaces había ese día).

    Solo se reescribe y se anota en el manifest si el contenido cambió.
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    target = RAW_DIR / source.index_file_name
    new_hash = hashlib.sha256(content).hexdigest()
    if target.exists() and sha256_of(target) == new_hash:
        return
    part = target.with_name(target.name + ".part")
    part.write_bytes(content)
    part.replace(target)
    append_manifest({
        "archivo": source.index_file_name,
        "archivo_original": source.index_url.rsplit("/", 1)[1],
        "periodo": "", "titulo": f"Página índice ({source.key})", "url": source.index_url,
        "server_fecha": "", "server_bytes": len(content), "sha256": new_hash,
        "descargado_en": dt.datetime.now().isoformat(timespec="seconds"), "accion": "indice"})


def process_report(client: CmfClient, link: ReportLink, force: bool, dry_run: bool) -> str:
    target = RAW_DIR / link.local_name
    if target.exists() and not force:
        log.info("Ya existe, se omite: %s", target.name)
        return "existente"
    if dry_run:
        log.info("[dry-run] bajaría %s -> %s", link.url, target.name)
        return "dry_run"
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    meta = client.download(link.url, part)
    suffix = "." + link.original_name.rsplit(".", 1)[1].lower()
    size = part.stat().st_size
    if meta["content_length"] is not None and size != meta["content_length"]:
        part.unlink(missing_ok=True)
        raise ValueError(f"Tamaño distinto al Content-Length ({size} vs {meta['content_length']})")
    if not has_valid_signature(part, suffix):
        part.unlink(missing_ok=True)
        raise ValueError(f"La firma del archivo no corresponde a {suffix}: {link.url}")
    part.replace(target)
    append_manifest({
        "archivo": target.name, "archivo_original": link.original_name, "periodo": link.periodo,
        "titulo": link.title, "url": link.url, "server_fecha": meta["server_fecha"],
        "server_bytes": size, "sha256": sha256_of(target),
        "descargado_en": dt.datetime.now().isoformat(timespec="seconds"), "accion": "nuevo"})
    log.info("Descargado %s (%d bytes)", target.name, size)
    return "nuevo"


# Estados financieros anuales auditados que la CMF aloja en su sitio. La URL sale del índice
# oficial «Estados Financieros Anuales Bancos y Cooperativas de Ahorro y Crédito 2025»
# (https://www.cmfchile.cl/portal/estadisticas/626/articles-110289_recurso_1.pdf).
ANNUAL_EEFF_URL = "https://www.cmfchile.cl/bancos/estados_anuales/{year}/Bancos-{year}/{year}12-{code}.pdf"


def download_annual_eeff(client: CmfClient, year: int, codes: list[str], force: bool,
                         dry_run: bool) -> int:
    """Baja los estados financieros anuales (PDF) de los bancos pedidos, uno a la vez."""
    errors = 0
    for code in codes:
        code = code.zfill(3)
        url = ANNUAL_EEFF_URL.format(year=year, code=code)
        name = url.rsplit("/", 1)[1]
        link = ReportLink(aid=f"eeff-{code}", year=year, month=12,
                          title=f"Estados financieros anuales {year}, banco {code}",
                          url=url, original_name=name)
        try:
            process_report(client, link, force, dry_run)
        except BlockedError:
            raise
        except Exception as exc:
            log.error("FALLA %s: %s", url, exc)
            errors += 1
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Descarga los reportes de diciembre de la CMF.")
    parser.add_argument("--desde", type=int, default=2015, help="Primer año (diciembre).")
    parser.add_argument("--hasta", type=int, default=2025, help="Último año (diciembre).")
    parser.add_argument("--pausa", type=float, default=2.0,
                        help=f"Segundos entre peticiones (mínimo {MIN_PAUSE}).")
    parser.add_argument("--forzar", action="store_true", help="Vuelve a bajar aunque exista.")
    parser.add_argument("--dry-run", action="store_true", help="Solo lista; no baja los archivos.")
    parser.add_argument("--fuente", choices=["reporte", "textos", "filiales", "todo"],
                        default="reporte",
                        help="reporte = Excel del reporte mensual (por defecto); textos = zip de "
                             "estados financieros en texto; filiales = PDF de matrices y filiales "
                             "(usar con --desde 2025); todo = reporte + textos.")
    parser.add_argument("--anios", type=int, nargs="*",
                        help="Solo estos años dentro de --desde/--hasta (p. ej. para textos).")
    parser.add_argument("--eeff-anuales", type=int, metavar="AÑO",
                        help="En lugar de las páginas índice, baja los estados financieros "
                             "anuales (PDF) de ese año para los bancos de --bancos.")
    parser.add_argument("--bancos", nargs="*", default=["016", "039", "059", "051", "053"],
                        help="Códigos CMF de banco para --eeff-anuales (por defecto BCI 016, "
                             "Itaú 039, BTG 059, Falabella 051 y Ripley 053).")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    client = CmfClient(pause=args.pausa)
    keys = ["reporte", "textos"] if args.fuente == "todo" else [args.fuente]
    errors = 0
    if args.eeff_anuales:
        keys = []
    try:
        if args.eeff_anuales:
            errors += download_annual_eeff(client, args.eeff_anuales, args.bancos, args.forzar,
                                           args.dry_run)
        for key in keys:
            source = SOURCES[key]
            html, raw = client.get_text(source.index_url, expected=source.title)
            links = parse_index(html, source)
            log.info("[%s] la página índice lista %d archivos mensuales", key, len(links))
            selected = select_december(links, args.desde, args.hasta)
            if args.anios:
                selected = [l for l in selected if l.year in args.anios]
            if not args.dry_run:
                save_index(raw, source)
            for link in selected:
                log.info("[%s] %d-12: %s (%s)", key, link.year, link.original_name, link.title)
                try:
                    process_report(client, link, args.forzar, args.dry_run)
                except BlockedError:
                    raise
                except Exception as exc:  # una falla no detiene el resto, salvo un bloqueo
                    log.error("FALLA %s: %s", link.periodo, exc)
                    errors += 1
    except BlockedError as exc:
        log.error("BLOQUEO: %s", exc)
        return 2
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
