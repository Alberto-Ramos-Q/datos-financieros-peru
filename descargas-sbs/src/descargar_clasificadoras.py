"""Descargador de los informes de las clasificadoras de riesgo publicados en la extranet de la SBS.

La SBS publica cada semestre los informes de clasificación de las empresas supervisadas en
`https://extranet.sbs.gob.pe/iece/descargar?codClasificadora=X&codPeriodo=AAAAPP&numArchivo=N&numVersion=1`
(PP = 01 para la publicación del primer semestre, con información a diciembre del año anterior;
02 para la del segundo, con información a junio). No hay un índice público: los números de archivo
son correlativos desde 1, así que se recorren con HEAD (la respuesta trae el nombre del PDF en
Content-Disposition) hasta encontrar `--fin-huecos` números seguidos sin archivo.

Dos pasos:
1. `indice`: arma `data/raw/clasificadoras/indice.csv` (un registro por archivo encontrado). Los
   periodos ya recorridos no se vuelven a consultar, salvo los dos más recientes, que pueden crecer.
2. `pdf`: descarga solo los informes de entidades de los cinco subsistemas de crédito, reconocidos
   por el nombre del archivo con `config/clasificadoras_alias.csv`, a
   `data/raw/clasificadoras/<clasificadora>/<codPeriodo>/<numArchivo>_<archivo>`.
   Los nombres que no se reconocen quedan en `data/_control/clasificadoras_sin_alias.csv` para revisión.

Uso:
    python descargar_clasificadoras.py indice                 # todas las clasificadoras, 2015 → hoy
    python descargar_clasificadoras.py indice --clasificadora 000409 --desde 2024
    python descargar_clasificadoras.py pdf
    python descargar_clasificadoras.py pdf --dry-run

Secuencial y lento a propósito (regla del proyecto): una petición cada `--pausa` segundos, nunca en
paralelo. Se detiene si el servidor responde 403 (bloqueo de Imperva).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import sys
import time
import unicodedata
from pathlib import Path

import requests

from descargar_boletin import (DEFAULT_CONTROL, DEFAULT_DEST, USER_AGENT, log, prevent_sleep,
                               setup_logging, sha256_of)

PROJECT_DIR = Path(__file__).resolve().parents[1]
ALIAS_CSV = PROJECT_DIR / "config" / "clasificadoras_alias.csv"
URL = "https://extranet.sbs.gob.pe/iece/descargar"
CARPETA = "clasificadoras"
# Códigos documentados en alerta-temprana-ssff/docs/eventos.md.
CLASIFICADORAS = {
    "000406": "moodys-local",   # antes Equilibrium
    "000408": "apoyo",          # Apoyo & Asociados (Fitch)
    "000409": "pcr",            # Pacific Credit Rating
    "000410": "microrate",
}
DESDE = 2015
PDF_MAGIC = b"%PDF"
INDEX_FIELDS = ["cod_clasificadora", "clasificadora", "cod_periodo", "num_archivo", "num_version",
                "archivo", "bytes", "consultado_en"]


class Blocked(RuntimeError):
    """El servidor respondió 403: hay que parar y esperar."""


class ExtranetClient:
    """Cliente secuencial con pausa y reintentos (mismo criterio que `SbsClient`)."""

    def __init__(self, pause: float, retries: int = 4):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.pause = pause
        self.retries = retries

    def _request(self, method: str, params: dict, **kwargs) -> requests.Response:
        for attempt in range(1, self.retries + 1):
            time.sleep(self.pause)
            try:
                resp = self.session.request(method, URL, params=params, timeout=60, **kwargs)
                if resp.status_code == 403:
                    raise Blocked(f"HTTP 403 en {params}")
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"HTTP {resp.status_code}")
                return resp
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as exc:
                wait = 15 * attempt
                log.warning("Error de red (%s); reintento %d/%d en %ds", exc, attempt, self.retries, wait)
                time.sleep(wait)
        raise RuntimeError(f"Sin respuesta tras {self.retries} intentos: {params}")

    def head(self, params: dict) -> tuple[str, int] | None:
        resp = self._request("HEAD", params)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        if "html" in resp.headers.get("Content-Type", "").lower():
            # Una página HTML con 200 suele ser el desafío de Imperva, no un informe. Los informes antiguos
            # llegan a veces como application/octet-stream: se aceptan.
            raise Blocked(f"Respuesta HTML ({resp.headers.get('Content-Type')}) en {params}")
        disp = resp.headers.get("Content-Disposition", "")
        # Entre comillas el nombre puede traer «;» (tildes como «&#769;»); sin comillas termina en «;».
        match = re.search(r'filename="([^"]+)"', disp) or re.search(r"filename=([^;]+)", disp)
        return (match.group(1).strip() if match else ""), int(resp.headers.get("Content-Length", 0))

    def download(self, params: dict, target: Path) -> None:
        resp = self._request("GET", params, stream=True)
        resp.raise_for_status()
        with open(target, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 16):
                fh.write(chunk)


def params_of(cod: str, periodo: str, num: int, version: int = 1) -> dict:
    return dict(codClasificadora=cod, codPeriodo=periodo, numArchivo=num, numVersion=version)


def iter_semesters(desde: int, hasta: dt.date):
    """Periodos AAAA01/AAAA02 del más reciente al más antiguo (lo útil llega primero)."""
    last = hasta.year * 100 + (2 if hasta.month >= 7 else 1)
    year, sem = divmod(last, 100)
    while year >= desde:
        yield f"{year}{sem:02d}"
        year, sem = (year, 1) if sem == 2 else (year - 1, 2)


def load_index(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def write_index(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows, key=lambda r: (r["cod_clasificadora"], r["cod_periodo"], int(r["num_archivo"])))
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=INDEX_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def scan_period(client: ExtranetClient, cod: str, periodo: str, start: int, gap_end: int,
                gap_start: int) -> list[dict]:
    """Recorre numArchivo desde `start` hasta `gap_end` huecos seguidos tras el último hallazgo."""
    found, misses, num, any_hit = [], 0, start, start > 1
    while True:
        res = client.head(params_of(cod, periodo, num))
        if res is None:
            misses += 1
            if misses >= (gap_end if any_hit else gap_start):
                return found
        else:
            any_hit, misses = True, 0
            name, size = res
            found.append({"cod_clasificadora": cod, "clasificadora": CLASIFICADORAS[cod],
                          "cod_periodo": periodo, "num_archivo": num, "num_version": 1,
                          "archivo": name, "bytes": size,
                          "consultado_en": dt.datetime.now().isoformat(timespec="seconds")})
        num += 1


def run_index(args, client: ExtranetClient, dest: Path) -> int:
    path = dest / CARPETA / "indice.csv"
    rows = load_index(path)
    known: dict[tuple[str, str], int] = {}
    for r in rows:
        key = (r["cod_clasificadora"], r["cod_periodo"])
        known[key] = max(known.get(key, 0), int(r["num_archivo"]))
    done_path = DEFAULT_CONTROL / "clasificadoras_periodos_recorridos.csv"
    done = set()
    if done_path.exists():
        with open(done_path, encoding="utf-8") as fh:
            done = {tuple(line.strip().split(",")) for line in fh if line.strip()}

    periods = list(iter_semesters(args.desde, dt.date.today()))
    recent = set(periods[:2])
    codes = args.clasificadora or list(CLASIFICADORAS)
    for periodo in periods:
        for cod in codes:
            key = (cod, periodo)
            if key in done and periodo not in recent:
                continue
            start = known.get(key, 0) + 1
            new = scan_period(client, cod, periodo, start, args.fin_huecos, args.huecos_inicio)
            rows.extend(new)
            write_index(path, rows)
            if key not in done:
                done.add(key)
                with open(done_path, "a", encoding="utf-8") as fh:
                    fh.write(f"{cod},{periodo}\n")
            log.info("%s %s: %d archivos nuevos (total del periodo %d)", CLASIFICADORAS[cod], periodo,
                     len(new), known.get(key, 0) + len(new))
    log.info("Índice: %d archivos en %s", len(rows), path)
    return 0


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", text)


def load_aliases(path: Path) -> list[tuple[str, str]]:
    """(patrón normalizado, id_entidad); el patrón más largo gana."""
    with open(path, encoding="utf-8") as fh:
        pairs = [(normalize(r["patron"]), r["id_entidad"].strip()) for r in csv.DictReader(fh)]
    return sorted(pairs, key=lambda p: -len(p[0]))


def match_entity(file_name: str, aliases: list[tuple[str, str]]) -> str | None:
    """id_entidad, '' si el patrón marca un archivo a ignorar (seguros, otros), None si no hay patrón."""
    norm = normalize(file_name)
    for pattern, ident in aliases:
        if pattern and pattern in norm:
            return ident
    return None


def run_pdf(args, client: ExtranetClient, dest: Path) -> int:
    rows = load_index(dest / CARPETA / "indice.csv")
    aliases = load_aliases(ALIAS_CSV)
    unmatched, todo = {}, []
    for r in rows:
        ident = match_entity(r["archivo"], aliases)
        if ident is None:
            unmatched[r["archivo"]] = r
        elif ident:
            todo.append(r)
    with open(DEFAULT_CONTROL / "clasificadoras_sin_alias.csv", "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=INDEX_FIELDS)
        writer.writeheader()
        writer.writerows(unmatched.values())
    log.info("Índice %d · entidades de crédito %d · sin alias %d", len(rows), len(todo), len(unmatched))

    errors = 0
    for r in todo:
        local = (dest / CARPETA / r["clasificadora"] / r["cod_periodo"]
                 / f"{int(r['num_archivo']):03d}_{r['archivo']}")
        if local.exists() and local.stat().st_size == int(r["bytes"]):
            continue
        if args.dry_run:
            log.info("[dry-run] %s", local.relative_to(dest))
            continue
        tmp_dir = DEFAULT_CONTROL / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp = tmp_dir / "clasificadora.pdf"
        try:
            client.download(params_of(r["cod_clasificadora"], r["cod_periodo"], int(r["num_archivo"])), tmp)
            with open(tmp, "rb") as fh:
                if fh.read(4) != PDF_MAGIC:
                    raise ValueError("no es PDF")
            local.parent.mkdir(parents=True, exist_ok=True)
            tmp.replace(local)
            log.info("NUEVO %s (%s)", local.relative_to(dest), sha256_of(local)[:12])
        except Blocked:
            raise
        except Exception as exc:  # una falla no detiene el resto
            log.error("FALLA %s: %s", r["archivo"], exc)
            errors += 1
    return 1 if errors else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Informes de clasificadoras de riesgo (extranet SBS).")
    parser.add_argument("paso", choices=["indice", "pdf"])
    parser.add_argument("--destino", type=Path, default=DEFAULT_DEST)
    parser.add_argument("--clasificadora", action="append", choices=list(CLASIFICADORAS))
    parser.add_argument("--desde", type=int, default=DESDE, help="Año inicial.")
    parser.add_argument("--pausa", type=float, default=1.0, help="Segundos entre peticiones.")
    parser.add_argument("--fin-huecos", type=int, default=30,
                        help="Números seguidos sin archivo, tras un hallazgo, para cerrar el periodo.")
    parser.add_argument("--huecos-inicio", type=int, default=80,
                        help="Números sin archivo, sin hallazgos aún, para dar el periodo por vacío.")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    setup_logging(DEFAULT_CONTROL)
    prevent_sleep()
    client = ExtranetClient(pause=args.pausa)
    log.info("Clasificadoras | paso %s | desde %s | pausa %.1f s", args.paso, args.desde, args.pausa)
    try:
        if args.paso == "indice":
            return run_index(args, client, args.destino)
        return run_pdf(args, client, args.destino)
    except Blocked as exc:
        log.error("BLOQUEO: %s. Esperar unas horas antes de reintentar.", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
