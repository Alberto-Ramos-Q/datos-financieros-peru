"""Descargador reproducible de los datos de Colombia para la serie de concentración bancaria.

Fuentes oficiales (ambas de la Superintendencia Financiera de Colombia, SFC):

1. CUIF por entidad en datos.gov.co (API Socrata, conjunto `mxk5-ce6w`, «Información
   financiera con fines de supervisión – CUIF por moneda Entidades vigiladas»).
   Licencia CC BY-SA 4.0 (compartir igual si se redistribuyen los datos).
   El conjunto empieza en 2016-01: no tiene dic-2015.
   Se trae, con una consulta SoQL filtrada por año, SOLO:
     - tipo_entidad = 1 (establecimientos bancarios),
     - corte de diciembre (fecha_corte = AAAA-12-31),
     - moneda = 0 (total),
     - cuentas de nivel 4 dígitos de los grupos 14 (cartera y deterioro) y 21
       (instrumentos financieros a costo amortizado: depósitos y otros), más los
       totales 100000, 140000, 200000 y 210000 para controles.
2. «Indicadores gerenciales – NIIF» de diciembre de cada año 2015-2025 en
   superfinanciera.gov.co (zip con un .xls por mes, cifras en millones de pesos y una
   columna por entidad). El de dic-2015 es la única fuente oficial por entidad para ese
   corte; los demás se usan como control cruzado con el CUIF y para leer la clasificación
   «Bancos Públicos» que hace la propia SFC.

3. Documentos de apoyo: «Principales variables» de dic-2025 (SFC; clasificación público /
   privado y notas de fusiones) y los estados financieros del Banco Agrario al 30-09-2025
   (naturaleza jurídica y accionistas; fuente: el mismo banco).

Reglas (política de descargas del proyecto):
- Peticiones SECUENCIALES, pausa >= 1,5 s entre peticiones (por defecto 2 s).
- Reintentos con espera creciente ante 429 y 5xx (y errores de red).
- Ante 403, captcha o respuesta no esperada (HTML en lugar de JSON/zip) se DETIENE.
- User-Agent genérico, sin datos personales.
- Escritura a `.part` y renombrado al terminar; manifest con sha256.

Uso:
    python descargar_colombia.py                 # descarga lo que falte
    python descargar_colombia.py --forzar        # vuelve a descargar todo
    python descargar_colombia.py --dry-run       # solo lista lo que haría
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import sys
import time
from pathlib import Path

import requests

PROJECT_DIR = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_DIR / "data" / "raw" / "internacional" / "colombia"
MANIFEST = PROJECT_DIR / "data" / "_control" / "internacional" / "colombia_manifest.csv"

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) concentracion-bancaria/1.0"
SOCRATA_RESOURCE = "https://www.datos.gov.co/resource/mxk5-ce6w.json"
SOCRATA_VIEW = "https://www.datos.gov.co/api/views/mxk5-ce6w.json"
SFC_LOADER = "https://www.superfinanciera.gov.co/loader.php"
SFC_IG_PAGE = ("https://www.superfinanciera.gov.co/publicaciones/10084493/informes-y-cifrascifras"
               "establecimientos-de-creditoinformacion-periodicamensualindicadores-gerenciales-"
               "niif-10084493/")

YEARS_API = range(2016, 2026)
PAGE_LIMIT = 50000
RETRY_STATUS = {429, 500, 502, 503, 504}

# idFile de «Indicadores Gerenciales - Diciembre AAAA», leídos de SFC_IG_PAGE (2026-11-03).
IG_DECEMBER_FILES = {
    2015: 1017192, 2016: 1022792, 2017: 1029749, 2018: 1036022, 2019: 1043408,
    2020: 1050816, 2021: 1058877, 2022: 1064827, 2023: 1069928, 2024: 1074153,
    2025: 1081063,
}

# Otros documentos oficiales: (archivo local, URL, firma inicial esperada, nota).
EXTRA_FILES = [
    ("principales_variables_202512.xlsx",
     f"{SFC_LOADER}?lServicio=Tools2&lTipo=descargas&lFuncion=descargar&idFile=1081061", b"PK",
     "SFC, Principales variables de los establecimientos de credito, dic-2025 (hoja PV3: "
     "clasificacion publico/privado por entidad; notas de fusiones y conversiones). Pagina: "
     "https://www.superfinanciera.gov.co/publicaciones/60949"),
    ("banco_agrario_eeff_separados_2025-09-30.pdf",
     "https://www.bancoagrario.gov.co/sites/default/files/2025-12/"
     "notas_y_eeff_separado_a_30_de_septiembre_de_2025.pdf", b"%PDF",
     "Banco Agrario de Colombia, estados financieros separados al 30-09-2025: naturaleza "
     "juridica (p. 10) y composicion accionaria (nota 24, p. 52)"),
]

SELECT_COLUMNS = ("tipo_entidad, nombre_tipo_entidad, codigo_entidad, nombre_entidad, fecha_corte, "
                  "cuenta, nombre_cuenta, moneda, nombre_moneda, signo_valor, valor")


class BlockedError(RuntimeError):
    """El servidor bloqueó o respondió algo que no es el dato esperado: no se insiste."""


class PoliteClient:
    """Cliente HTTP secuencial con pausa fija entre peticiones y reintentos crecientes."""

    def __init__(self, pause: float, retries: int = 5):
        if pause < 1.5:
            raise ValueError("La pausa mínima entre peticiones es 1,5 s")
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.pause = pause
        self.retries = retries
        self._last = 0.0

    def get(self, url: str, params: dict | None = None) -> requests.Response:
        for attempt in range(1, self.retries + 1):
            wait = self.pause - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            try:
                resp = self.session.get(url, params=params, timeout=180)
                self._last = time.monotonic()
            except (requests.ConnectionError, requests.Timeout) as exc:
                self._last = time.monotonic()
                backoff = 10 * attempt
                print(f"  error de red ({exc}); reintento {attempt}/{self.retries} en {backoff} s")
                time.sleep(backoff)
                continue
            if resp.status_code in RETRY_STATUS:
                backoff = 10 * attempt
                print(f"  HTTP {resp.status_code}; reintento {attempt}/{self.retries} en {backoff} s")
                time.sleep(backoff)
                continue
            if resp.status_code in (401, 403):
                raise BlockedError(f"HTTP {resp.status_code} en {resp.url}: posible bloqueo, se detiene")
            resp.raise_for_status()
            return resp
        raise RuntimeError(f"Sin respuesta válida tras {self.retries} intentos: {url}")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def write_atomic(target: Path, content: bytes) -> None:
    """Escribe a `<archivo>.part` y renombra al terminar."""
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    part.write_bytes(content)
    part.replace(target)


def load_manifest() -> list[dict]:
    if not MANIFEST.exists():
        return []
    with open(MANIFEST, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def save_manifest(rows: list[dict]) -> None:
    fields = ["archivo", "url_o_consulta", "bytes", "sha256", "fecha_descarga", "filas", "nota"]
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    part = MANIFEST.with_name(MANIFEST.name + ".part")
    with open(part, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in sorted(rows, key=lambda r: r["archivo"]):
            writer.writerow({k: row.get(k, "") for k in fields})
    part.replace(MANIFEST)


def upsert(manifest: list[dict], entry: dict) -> None:
    manifest[:] = [r for r in manifest if r["archivo"] != entry["archivo"]]
    manifest.append(entry)


def soql_where(year: int) -> str:
    return (f"tipo_entidad='1' AND moneda='0' AND fecha_corte='{year}-12-31T00:00:00.000' AND "
            "(cuenta in ('100000','140000','200000','210000') OR cuenta like '14__00' "
            "OR cuenta like '21__00')")


def download_cuif_year(client: PoliteClient, year: int) -> tuple[bytes, str, int]:
    """Trae los bancos de dic-`year`; pagina si hiciera falta. Devuelve (json, consulta, filas)."""
    rows: list[dict] = []
    offset = 0
    while True:
        params = {"$select": SELECT_COLUMNS, "$where": soql_where(year),
                  "$order": "codigo_entidad, cuenta", "$limit": str(PAGE_LIMIT),
                  "$offset": str(offset)}
        resp = client.get(SOCRATA_RESOURCE, params=params)
        if "json" not in resp.headers.get("Content-Type", ""):
            raise BlockedError(f"Respuesta no JSON en {resp.url}: posible bloqueo o cambio del API")
        page = resp.json()
        rows.extend(page)
        if len(page) < PAGE_LIMIT:
            break
        offset += PAGE_LIMIT
    query_url = requests.Request("GET", SOCRATA_RESOURCE, params={
        "$select": SELECT_COLUMNS, "$where": soql_where(year), "$order": "codigo_entidad, cuenta",
        "$limit": str(PAGE_LIMIT)}).prepare().url
    content = json.dumps(rows, ensure_ascii=False, indent=0).encode("utf-8")
    return content, query_url, len(rows)


def download_ig(client: PoliteClient, id_file: int) -> tuple[bytes, str, str]:
    params = {"lServicio": "Tools2", "lTipo": "descargas", "lFuncion": "descargar",
              "idFile": str(id_file)}
    resp = client.get(SFC_LOADER, params=params)
    content = resp.content
    if not content.startswith(b"PK"):
        raise BlockedError(f"El archivo {id_file} no es un zip (¿bloqueo o página HTML?): {resp.url}")
    disposition = resp.headers.get("Content-Disposition", "")
    return content, resp.url, disposition


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--pausa", type=float, default=2.0, help="segundos entre peticiones (>= 1,5)")
    parser.add_argument("--forzar", action="store_true", help="vuelve a descargar lo ya presente")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    client = PoliteClient(pause=args.pausa)
    manifest = load_manifest()

    tasks: list[tuple[str, str, object]] = [("ficha", "cuif_mxk5-ce6w_ficha.json", None)]
    tasks += [("cuif", f"cuif_bancos_{y}12.json", y) for y in YEARS_API]
    tasks += [("ig", f"indicadores_gerenciales_{y}12.zip", y) for y in sorted(IG_DECEMBER_FILES)]
    tasks += [("extra", name, (url, magic, nota)) for name, url, magic, nota in EXTRA_FILES]

    try:
        for kind, name, key in tasks:
            target = RAW_DIR / name
            if target.exists() and not args.forzar:
                print(f"ya existe: {name}")
                continue
            if args.dry_run:
                print(f"[dry-run] descargaría {name}")
                continue
            print(f"descargando {name} ...")
            nota, filas = "", ""
            if kind == "ficha":
                resp = client.get(SOCRATA_VIEW)
                content, url = resp.content, resp.url
                json.loads(content)  # valida que sea JSON
                nota = "ficha (metadatos y licencia) del conjunto"
            elif kind == "cuif":
                content, url, n = download_cuif_year(client, key)
                filas = str(n)
                if n == 0:
                    raise RuntimeError(f"La consulta de {key} no devolvió filas")
                nota = f"CUIF bancos (tipo 1), moneda total, dic-{key}, cuentas 14xx00 y 21xx00 + totales"
            elif kind == "ig":
                content, url, disposition = download_ig(client, IG_DECEMBER_FILES[key])
                nota = f"Indicadores gerenciales NIIF dic-{key}; {disposition}; pagina {SFC_IG_PAGE}"
            else:
                url, magic, nota = key
                content = client.get(url).content
                if not content.startswith(magic):
                    raise BlockedError(f"{name}: el contenido no es el esperado (¿bloqueo?): {url}")
            write_atomic(target, content)
            upsert(manifest, {"archivo": name, "url_o_consulta": url, "bytes": len(content),
                              "sha256": sha256_of(target),
                              "fecha_descarga": dt.datetime.now().isoformat(timespec="seconds"),
                              "filas": filas, "nota": nota})
            save_manifest(manifest)
            print(f"  ok: {len(content):,} bytes {('· ' + filas + ' filas') if filas else ''}")
    except BlockedError as exc:
        print(f"DETENIDO: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
