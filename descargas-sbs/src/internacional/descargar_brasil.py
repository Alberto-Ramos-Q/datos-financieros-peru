"""Descarga las fuentes oficiales del BCB para la serie de concentración bancaria de Brasil.

Dos tipos de fuente, ambas del Banco Central do Brasil:

1. PDF de publicaciones (www.bcb.gov.br):
   - Relatório de Economia Bancária (REB), ediciones 2017 a 2023 (descontinuado por la
     Resolución BCB 460, de 25/3/2025).
   - Relatório de Estabilidade Financeira (REF), ediciones de 2025 y 2026, que heredan los
     indicadores de concentración del SFN.
2. Consultas OData del IF.data (olinda.bcb.gov.br): cadastro y valores de diciembre de
   cada año, para el cálculo propio por conglomerado prudencial.

Reglas de cortesía con el servidor (política del proyecto):
- peticiones SECUENCIALES, nunca en paralelo, con pausa >= 1,5 s entre ellas;
- reintentos con espera creciente ante errores transitorios (5xx, red);
- ante un 403 o un 429 se DETIENE todo (posible bloqueo): no se reintenta ni se sortea;
- se escribe primero a `.part` y se renombra solo si la descarga terminó bien;
- User-Agent genérico, sin correos ni nombres de personas.

Destino: `data/raw/internacional/brasil/` (pdf/ y ifdata/).
Manifest: `data/_control/internacional/brasil_manifest.csv`.

Uso (desde la raíz del proyecto):
    python -I src/internacional/descargar_brasil.py pdf
    python -I src/internacional/descargar_brasil.py ifdata --anios 2015-2025
    python -I src/internacional/descargar_brasil.py ifdata --anios 2025 --solo-cadastro
    python -I src/internacional/descargar_brasil.py pdf --forzar     # vuelve a bajar todo
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import sys
import time
import zlib
from pathlib import Path
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw" / "internacional" / "brasil"
MANIFEST = ROOT / "data" / "_control" / "internacional" / "brasil_manifest.csv"

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) research-downloader/1.0"
PAUSE_SECONDS = 2.0          # >= 1,5 s exigido por la política del proyecto
MAX_ATTEMPTS = 4
BACKOFF_SECONDS = (5, 15, 45)  # espera creciente entre reintentos
TIMEOUT = (30, 300)          # (conexión, lectura) en segundos

PUB = "https://www.bcb.gov.br/content/publicacoes"
ODATA = "https://olinda.bcb.gov.br/olinda/servico/IFDATA/versao/v1/odata"

# Ediciones con indicadores de concentración del SFN (o candidatas a tenerlos).
# La URL de cada edición se ubicó sondeando el servidor del BCB (HEAD) el 2026-11-03.
PDF_SOURCES = [
    # (archivo local, url, descripción)
    ("reb_2017.pdf", f"{PUB}/relatorioeconomiabancaria/reb_2017.pdf", "REB 2017"),
    ("reb_2018.pdf", f"{PUB}/relatorioeconomiabancaria/reb_2018.pdf", "REB 2018"),
    ("reb_2019.pdf", f"{PUB}/relatorioeconomiabancaria/reb_2019.pdf", "REB 2019"),
    ("reb_2020.pdf", f"{PUB}/relatorioeconomiabancaria/reb_2020.pdf", "REB 2020"),
    ("reb_2021.pdf", f"{PUB}/relatorioeconomiabancaria/reb_2021.pdf", "REB 2021"),
    ("reb_2022.pdf", f"{PUB}/relatorioeconomiabancaria/reb2022p.pdf", "REB 2022"),
    ("reb_2023.pdf", f"{PUB}/relatorioeconomiabancaria/reb2023p.pdf", "REB 2023"),
    ("ref_202504.pdf", f"{PUB}/ref/202504/RELESTAB202504-refPub.pdf", "REF abr-2025"),
    ("ref_202510.pdf", f"{PUB}/ref/202510/RELESTAB202510-refPub.pdf", "REF oct-2025"),
    ("ref_202605.pdf", f"{PUB}/ref/202605/RELESTAB202605-refPub.pdf", "REF may-2026"),
    ("ref_202610.pdf", f"{PUB}/ref/202610/RELESTAB202610-refPub.pdf", "REF oct-2026"),
    # REF de 2016-2020: según la nota 105 del REB 2017, el REF de esa época usaba el IHH y
    # el RC4 (con operaciones en el exterior). Se bajan para buscar el RC4 de 2015-2018.
    ("ref_201604.pdf", f"{PUB}/ref/201604/RELESTAB201604-refPub.pdf", "REF abr-2016"),
    ("ref_201609.pdf", f"{PUB}/ref/201609/RELESTAB201609-refPub.pdf", "REF sep-2016"),
    ("ref_201704.pdf", f"{PUB}/ref/201704/RELESTAB201704-refPub.pdf", "REF abr-2017"),
    ("ref_201710.pdf", f"{PUB}/ref/201710/RELESTAB201710-refPub.pdf", "REF oct-2017"),
    ("ref_201804.pdf", f"{PUB}/ref/201804/RELESTAB201804-refPub.pdf", "REF abr-2018"),
    ("ref_201810.pdf", f"{PUB}/ref/201810/RELESTAB201810-refPub.pdf", "REF oct-2018"),
    ("ref_201904.pdf", f"{PUB}/ref/201904/RELESTAB201904-refPub.pdf", "REF abr-2019"),
    ("ref_201910.pdf", f"{PUB}/ref/201910/RELESTAB201910-refPub.pdf", "REF oct-2019"),
    ("ref_202004.pdf", f"{PUB}/ref/202004/RELESTAB202004-refPub.pdf", "REF abr-2020"),
    # Guia para Análise de Atos de Concentração (umbrales del IHH): texto oficial del
    # Comunicado, para resolver el número que el REF cita de dos formas (22.366 / 22.322).
    ("comunicado_22366_2012.pdf",
     "https://www.bcb.gov.br/content/estabilidadefinanceira/Organizacao/"
     "Guia_analise_acordo_concentracao_COMUNICADO22366.pdf",
     "BCB, Comunicado 22.366/2012 (Guia de atos de concentração)"),
]

# Anexos estadísticos (xlsx) del REF de 2017-2019: ahí quedaron las series del IHH y del
# RC4 del «segmento bancário» que el PDF ya no trae (los enlaces del PDF, en /htms/, dan 404;
# la ruta vigente se ubicó por sondeo el 2026-11-03). Se bajan junto con los PDF.
XLSX_SOURCES = [
    (f"ref_{m}_anexo.xlsx", f"{PUB}/ref/{m}/RELESTAB{m}-refAnexoEstatistico.xlsx",
     f"REF {m} anexo estadístico")
    for m in ("201704", "201710", "201804", "201810", "201904", "201910")
]

# IF.data: TipoInstituicao = 1 -> conglomerados prudenciales e instituciones independientes.
IFDATA_TIPO_PRUDENCIAL = 1
# Informes de valores: 1 = Resumo (activo total, cartera de crédito), 3 = Passivo (depósitos).
IFDATA_REPORTS = ("1", "3")

MANIFEST_FIELDS = ["archivo", "fuente", "url", "http_status", "bytes", "sha256",
                   "server_last_modified", "descargado_en", "accion"]


class BlockedError(RuntimeError):
    """El servidor respondió 403 o 429: se detiene todo sin intentar sortearlo."""


def log(msg: str) -> None:
    """Escribe una línea de registro con hora local."""
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def sha256_of(path: Path) -> str:
    """SHA-256 del archivo, leído por bloques."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def append_manifest(row: dict) -> None:
    """Agrega una fila al manifest (lo crea con encabezado si no existe)."""
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    new = not MANIFEST.exists()
    with open(MANIFEST, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=MANIFEST_FIELDS)
        if new:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in MANIFEST_FIELDS})


class PoliteClient:
    """Cliente HTTP secuencial: pausa entre peticiones, reintentos y corte ante bloqueo."""

    def __init__(self, pause: float = PAUSE_SECONDS) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.pause = max(pause, 1.5)
        self._last = 0.0

    def _wait(self) -> None:
        elapsed = time.monotonic() - self._last
        if elapsed < self.pause:
            time.sleep(self.pause - elapsed)

    def fetch_to(self, url: str, dest: Path) -> requests.Response:
        """Descarga `url` a `dest` vía `dest.part`; devuelve la respuesta (cabeceras)."""
        part = dest.with_name(dest.name + ".part")
        for attempt in range(1, MAX_ATTEMPTS + 1):
            self._wait()
            try:
                with self.session.get(url, stream=True, timeout=TIMEOUT) as resp:
                    self._last = time.monotonic()
                    if resp.status_code in (403, 429):
                        raise BlockedError(f"HTTP {resp.status_code} en {url}")
                    if resp.status_code >= 500:
                        raise requests.HTTPError(f"HTTP {resp.status_code}", response=resp)
                    resp.raise_for_status()
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    # Se cuentan los bytes escritos en vez de usar stat(): en la unidad de
                    # Google Drive el tamaño reportado justo después de cerrar puede estar
                    # desfasado (falso «incompleto» observado el 2026-11-03).
                    written = 0
                    with open(part, "wb") as fh:
                        for chunk in resp.raw.stream(1 << 16, decode_content=False):
                            fh.write(chunk)
                            written += len(chunk)
                    expected = resp.headers.get("Content-Length")
                    if expected and written != int(expected):
                        raise IOError(f"tamaño incompleto ({written} de {expected})")
                    if resp.headers.get("Content-Encoding", "").lower() in ("gzip", "deflate"):
                        raw = part.read_bytes()
                        wbits = 16 + zlib.MAX_WBITS if "gzip" in resp.headers["Content-Encoding"].lower() else zlib.MAX_WBITS
                        part.write_bytes(zlib.decompress(raw, wbits))
                    part.replace(dest)
                    return resp
            except BlockedError:
                part.unlink(missing_ok=True)
                raise
            except (requests.RequestException, IOError) as exc:
                self._last = time.monotonic()
                part.unlink(missing_ok=True)
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status is not None and 400 <= status < 500:
                    raise  # error del cliente: reintentar no sirve
                if attempt == MAX_ATTEMPTS:
                    raise
                wait = BACKOFF_SECONDS[min(attempt - 1, len(BACKOFF_SECONDS) - 1)]
                log(f"  intento {attempt} falló ({exc}); reintento en {wait} s")
                time.sleep(wait)
        raise RuntimeError("inalcanzable")


def download_one(client: PoliteClient, url: str, dest: Path, fuente: str,
                 force: bool, validate=None) -> str:
    """Baja un recurso si no existe (o si `force`), valida y lo anota en el manifest."""
    if dest.exists() and not force:
        log(f"ya existe, se omite: {dest.name}")
        return "omitido"
    action = "revisar" if dest.exists() else "nuevo"
    log(f"descargando {fuente}: {url}")
    resp = client.fetch_to(url, dest)
    if validate is not None:
        validate(dest)
    append_manifest({
        "archivo": dest.relative_to(RAW_DIR).as_posix(),
        "fuente": fuente,
        "url": url,
        "http_status": resp.status_code,
        "bytes": dest.stat().st_size,
        "sha256": sha256_of(dest),
        "server_last_modified": resp.headers.get("Last-Modified", ""),
        "descargado_en": dt.datetime.now().isoformat(timespec="seconds"),
        "accion": action,
    })
    log(f"  ok: {dest.name} ({dest.stat().st_size:,} bytes)")
    return action


def validate_pdf(path: Path) -> None:
    """Comprueba la firma %PDF; si no la tiene, borra el archivo y falla."""
    with open(path, "rb") as fh:
        head = fh.read(4)
    if head != b"%PDF":
        path.unlink()
        raise ValueError(f"{path.name} no es un PDF (cabecera {head!r})")


def validate_xlsx(path: Path) -> None:
    """Comprueba la firma ZIP (PK) de un .xlsx; si no la tiene, borra el archivo y falla."""
    with open(path, "rb") as fh:
        head = fh.read(2)
    if head != b"PK":
        path.unlink()
        raise ValueError(f"{path.name} no es un xlsx (cabecera {head!r})")


def validate_odata_json(path: Path) -> None:
    """Comprueba que la respuesta OData sea JSON con la clave `value`."""
    try:
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        if "value" not in payload:
            raise ValueError("sin clave 'value'")
    except Exception as exc:
        path.unlink(missing_ok=True)
        raise ValueError(f"{path.name}: respuesta OData inválida ({exc})") from exc


def odata_url(function: str, params: dict) -> str:
    """Arma la URL OData con alias de parámetros (`@Nombre`) y `$format=json`.

    Los `$` se codifican como %24: así el WAF del BCB no rechaza la petición
    (con `$top` y `@` crudos devolvió un 403 «Requisição inválida» el 2026-11-03).
    """
    aliases = ",".join(f"{k}=@{k}" for k in params)
    query = "&".join(f"@{k}={quote(str(v), safe='')}" for k, v in params.items())
    return f"{ODATA}/{function}({aliases})?{query}&%24format=json"


def run_pdf(client: PoliteClient, force: bool) -> None:
    """Descarga las ediciones del REB y del REF listadas en `PDF_SOURCES`."""
    for name, url, desc in PDF_SOURCES:
        download_one(client, url, RAW_DIR / "pdf" / name, desc, force, validate_pdf)
    for name, url, desc in XLSX_SOURCES:
        download_one(client, url, RAW_DIR / "xlsx" / name, desc, force, validate_xlsx)


def run_ifdata(client: PoliteClient, years: list[int], force: bool, only_cadastro: bool) -> None:
    """Descarga cadastro y valores (Resumo y Passivo) de diciembre de cada año."""
    for year in years:
        anomes = year * 100 + 12
        dest_dir = RAW_DIR / "ifdata"
        url = odata_url("IfDataCadastro", {"AnoMes": anomes})
        download_one(client, url, dest_dir / f"cadastro_{anomes}.json",
                     f"IF.data cadastro {anomes}", force, validate_odata_json)
        if only_cadastro:
            continue
        for report in IFDATA_REPORTS:
            url = odata_url("IfDataValores", {"AnoMes": anomes,
                                              "TipoInstituicao": IFDATA_TIPO_PRUDENCIAL,
                                              "Relatorio": f"'{report}'"})
            download_one(client, url,
                         dest_dir / f"valores_{anomes}_tipo{IFDATA_TIPO_PRUDENCIAL}_rel{report}.json",
                         f"IF.data valores {anomes} tipo {IFDATA_TIPO_PRUDENCIAL} relatorio {report}",
                         force, validate_odata_json)


def parse_years(text: str) -> list[int]:
    """Convierte '2015-2025' o '2015,2018' en una lista de años."""
    years: list[int] = []
    for part in text.split(","):
        if "-" in part:
            a, b = part.split("-")
            years.extend(range(int(a), int(b) + 1))
        else:
            years.append(int(part))
    return years


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("modo", choices=["pdf", "ifdata"])
    parser.add_argument("--anios", default="2015-2025", help="años para IF.data (diciembre)")
    parser.add_argument("--solo-cadastro", action="store_true")
    parser.add_argument("--forzar", action="store_true", help="vuelve a bajar lo que ya existe")
    parser.add_argument("--pausa", type=float, default=PAUSE_SECONDS)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    client = PoliteClient(args.pausa)
    try:
        if args.modo == "pdf":
            run_pdf(client, args.forzar)
        else:
            run_ifdata(client, parse_years(args.anios), args.forzar, args.solo_cadastro)
    except BlockedError as exc:
        log(f"DETENIDO: posible bloqueo del servidor ({exc}). No se reintenta.")
        return 2
    except Exception as exc:  # noqa: BLE001 - se informa y se sale con código de error
        log(f"ERROR: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
