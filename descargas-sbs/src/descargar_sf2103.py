"""Descargador del cuadro SF-2103 «Evolución del Sistema Financiero» (PDF trimestral).

Es la única publicación de la SBS con el número de deudores ÚNICOS de todo el sistema
financiero (cada deudor contado una vez aunque tenga créditos en varias entidades o
subsistemas). Se publica para marzo, junio, setiembre y diciembre; los demás meses dan 404.

Sigue las convenciones de `descargar_boletin.py` (reutiliza su cliente HTTP, manifest,
historial y logs): baja solo lo nuevo o lo republicado y guarda la versión reemplazada en
`data/_control/historial/sf2103/`.

Uso:
    python descargar_sf2103.py                        # trimestres desde 2010-03 hasta hoy
    python descargar_sf2103.py --dry-run              # solo informa
    python descargar_sf2103.py --desde 202403
    python descargar_sf2103.py --meses todos          # sondea también los meses no trimestrales
    python descargar_sf2103.py --barrido 6            # incremental + revisa de t-6 a t (meses)

Secuencial y lento a propósito (regla del proyecto): una petición cada `--pausa` segundos
(3 s por defecto), nunca en paralelo.
"""
from __future__ import annotations

import argparse
import datetime as dt
import shutil
import sys
from pathlib import Path

from descargar_boletin import (BASE_URL, DEFAULT_CONTROL, DEFAULT_DEST, MONTH_ABBR,
                               MONTH_FOLDERS, SbsClient, append_manifest, iter_periods,
                               load_manifest, log, needs_check, prevent_sleep, select_periods,
                               setup_logging, sha256_of)

CODIGO = "SF-2103"
CARPETA = "sf2103"          # data/raw/sf2103/SF-2103-mmAAAA.PDF
DESDE = 201003              # la edición más antigua conocida es dic-2010
TRIMESTRALES = (3, 6, 9, 12)
PDF_MAGIC = b"%PDF"


def build_file_name(periodo: int) -> str:
    year, month = divmod(periodo, 100)
    return f"{CODIGO}-{MONTH_ABBR[month - 1]}{year}.PDF"


def build_url(periodo: int) -> str:
    year, month = divmod(periodo, 100)
    return f"{BASE_URL}/{year}/{MONTH_FOLDERS[month - 1]}/{build_file_name(periodo)}"


def is_valid_pdf(path: Path, expected_size: int) -> bool:
    with open(path, "rb") as fh:
        head = fh.read(4)
    return path.stat().st_size == expected_size and head == PDF_MAGIC


def process_period(client: SbsClient, periodo: int, dest: Path, control: Path,
                   manifest: dict, dry_run: bool) -> str:
    """Misma lógica que `descargar_boletin.process_file`, con validación de PDF."""
    file_name = build_file_name(periodo)
    url = build_url(periodo)
    local = dest / CARPETA / file_name
    record = manifest.get((CARPETA, file_name))

    remote = client.head(url)
    if remote is None:
        return "no_publicado"
    if local.exists() and not needs_check(local, remote, record):
        return "sin_cambios"

    action = "nuevo" if not local.exists() else "revisar"
    if dry_run:
        log.info("[dry-run] %s %s/%s (servidor %s, %d bytes)", action, CARPETA, file_name,
                 remote.last_modified.date(), remote.size)
        return action

    tmp_dir = control / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp = tmp_dir / file_name
    client.download(url, tmp)
    if not is_valid_pdf(tmp, remote.size):
        tmp.unlink(missing_ok=True)
        raise ValueError(f"Descarga inválida (no es PDF o tamaño distinto): {url}")

    new_hash = sha256_of(tmp)
    if local.exists():
        if sha256_of(local) == new_hash:
            tmp.unlink()
            action = "registrado"
        else:
            stamp = dt.datetime.fromtimestamp(local.stat().st_mtime).strftime("%Y%m%d")
            archived = control / "historial" / CARPETA / f"{local.stem}__{stamp}{local.suffix}"
            archived.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(local, archived)
            action = "republicado"
            log.info("Versión anterior guardada en %s", archived)

    if action != "registrado":
        local.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(tmp, local)
        log.info("%s: %s/%s", action.upper(), CARPETA, file_name)

    row = {"carpeta": CARPETA, "archivo": file_name, "periodo": periodo, "url": url,
           "server_fecha": remote.last_modified.isoformat(), "server_bytes": remote.size,
           "sha256": new_hash, "descargado_en": dt.datetime.now().isoformat(timespec="seconds"),
           "accion": action}
    append_manifest(control / "manifest.csv", row)
    manifest[(CARPETA, file_name)] = row
    return action


def parse_args() -> argparse.Namespace:
    today = dt.date.today()
    parser = argparse.ArgumentParser(description="Descarga el SF-2103 (Evolución del SF) de la SBS.")
    parser.add_argument("--destino", type=Path, default=DEFAULT_DEST)
    parser.add_argument("--control", type=Path, default=None)
    parser.add_argument("--desde", type=int, default=DESDE, help="Periodo inicial AAAAMM.")
    parser.add_argument("--hasta", type=int, default=today.year * 100 + today.month)
    parser.add_argument("--meses", choices=["trimestrales", "todos"], default="trimestrales",
                        help="«todos» sondea también los meses no trimestrales (cobertura).")
    parser.add_argument("--pausa", type=float, default=3.0,
                        help="Segundos entre peticiones (por defecto 3: descarga lenta a propósito).")
    parser.add_argument("--barrido", type=int, default=None,
                        help="Incremental: trimestres nuevos + revisión de t-N a t (N en meses; "
                             "t = último trimestre que tenemos). Sin esta opción: revisión completa.")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    control = args.control or (DEFAULT_CONTROL if args.destino == DEFAULT_DEST
                               else args.destino.parent / "_control")
    log_file = setup_logging(control)
    prevent_sleep()
    log.info("SF-2103 | Destino: %s | Control: %s | meses: %s | dry-run: %s",
             args.destino, control, args.meses, args.dry_run)

    manifest = load_manifest(control / "manifest.csv")
    client = SbsClient(pause=args.pausa)
    totals: dict[str, int] = {}
    published: list[int] = []
    errors = 0
    periods = [p for p in iter_periods(args.desde, args.hasta)
               if args.meses == "todos" or p % 100 in TRIMESTRALES]
    periods = select_periods(periods, lambda p: (args.destino / CARPETA / build_file_name(p)).exists(),
                             args.barrido)
    log.info("Modo: %s", "revisión completa" if args.barrido is None
             else f"incremental con barrido t-{args.barrido}")
    for periodo in periods:
        try:
            action = process_period(client, periodo, args.destino, control, manifest, args.dry_run)
        except Exception as exc:  # una falla no detiene el resto
            log.error("FALLA %s %s: %s", CODIGO, periodo, exc)
            action, errors = "error", errors + 1
        if action not in ("no_publicado", "error"):
            published.append(periodo)
        totals[action] = totals.get(action, 0) + 1

    log.info("Periodos publicados entre los consultados (%d): %s", len(published), " ".join(map(str, published)))
    log.info("Resumen: %s", ", ".join(f"{k}={v}" for k, v in sorted(totals.items())))
    log.info("Log: %s", log_file)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
