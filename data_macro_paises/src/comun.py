"""Utilidades compartidas por los descargadores de cada país.

Cada país tiene su módulo en `src/paises/<iso3>.py` con dos pasos separados:

1. **Descargar**: baja de la fuente oficial y guarda la respuesta tal cual con
   `save_raw()` en `data/raw/<ISO3>/<fuente>/`. Si el archivo cambió, la versión
   previa va a `data/_control/historial/` y todo queda en `manifest_<ISO3>.csv`.
2. **Procesar**: lee SOLO `data/raw/` (sin red) y escribe con `write_interim()` la
   tabla larga normalizada `data/interim/<ISO3>_observaciones.parquet`.

Esquema de la tabla larga (validado en `write_interim`):
    pais, fuente, codigo_fuente, nombre_corto, indicador_comun, frecuencia,
    fecha, valor, unidad
- `fecha`: primer día del periodo (mes, trimestre, año); en diarias, el día.
- `frecuencia`: diaria | mensual | trimestral | anual.
- `indicador_comun`: clave de `config/indicadores_comunes.csv` o vacío.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import logging
import shutil
import sys
import time
from pathlib import Path

import pandas as pd
import requests

PROJECT_DIR = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_DIR / "config"
RAW_DIR = PROJECT_DIR / "data" / "raw"
INTERIM_DIR = PROJECT_DIR / "data" / "interim"
# Historial, manifest y logs van FUERA de data/raw: Folder.Files de Power BI es
# recursivo y leería las versiones anteriores como si fueran datos vigentes.
CONTROL_DIR = PROJECT_DIR / "data" / "_control"

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
FREQUENCIES = ("diaria", "mensual", "trimestral", "anual")
INTERIM_COLUMNS = ["pais", "fuente", "codigo_fuente", "nombre_corto", "indicador_comun",
                   "frecuencia", "fecha", "valor", "unidad"]
SERIES_FIELDS = ["fuente", "codigo_fuente", "nombre_corto", "indicador_comun", "frecuencia",
                 "unidad", "activo", "titulo_fuente", "notas"]
MANIFEST_FIELDS = ["pais", "fuente", "archivo", "url", "bytes", "sha256",
                   "descargado_en", "accion"]

log = logging.getLogger("data_macro_paises")


def setup_logging(iso3: str) -> None:
    """Log a consola y a `data/_control/logs/<ISO3>_AAAAMMDD_HHMMSS.log`."""
    # La consola de Windows (cp1252) no acepta caracteres como '→' del log.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logs = CONTROL_DIR / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler(logs / f"{iso3}_{stamp}.log", encoding="utf-8")],
        force=True)


class Client:
    """Cliente HTTP secuencial con pausa y reintentos (no paralelizar: varios
    sitios oficiales cortan la conexión o bloquean la IP)."""

    def __init__(self, pause: float = 1.0, retries: int = 4, headers: dict | None = None,
                 verify: bool | str = True):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        if headers:
            self.session.headers.update(headers)
        self.session.verify = verify
        self.pause = pause
        self.retries = retries

    def get(self, url: str, timeout: int = 120, **kwargs) -> requests.Response:
        return self.request("GET", url, timeout=timeout, **kwargs)

    def post(self, url: str, timeout: int = 120, **kwargs) -> requests.Response:
        return self.request("POST", url, timeout=timeout, **kwargs)

    def request(self, method: str, url: str, **kwargs) -> requests.Response:
        for attempt in range(1, self.retries + 1):
            time.sleep(self.pause)
            try:
                r = self.session.request(method, url, **kwargs)
                r.raise_for_status()
                return r
            except requests.RequestException as e:
                if attempt == self.retries:
                    raise
                wait = 5 * attempt
                log.warning("Intento %d falló (%s); reintento en %d s", attempt, e, wait)
                time.sleep(wait)
        raise RuntimeError("inalcanzable")


def load_series(iso3: str, only_active: bool = True) -> list[dict]:
    """Filas de `config/series/<ISO3>.csv`."""
    path = CONFIG_DIR / "series" / f"{iso3}.csv"
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if only_active:
        rows = [r for r in rows if r["activo"].strip() == "1"]
    return rows


def raw_path(iso3: str, fuente: str, filename: str) -> Path:
    return RAW_DIR / iso3 / fuente / filename


def save_raw(iso3: str, fuente: str, filename: str, content: bytes, url: str) -> str:
    """Guarda la respuesta tal cual. Devuelve la acción: nuevo | actualizado | sin_cambios.

    Si el archivo existía con otro contenido, la versión previa se copia a
    `data/_control/historial/<ISO3>/<fuente>/<nombre>__AAAAMMDD<ext>`.
    """
    path = raw_path(iso3, fuente, filename)
    digest = hashlib.sha256(content).hexdigest()
    if path.exists():
        if hashlib.sha256(path.read_bytes()).hexdigest() == digest:
            return "sin_cambios"
        hist = CONTROL_DIR / "historial" / iso3 / fuente
        hist.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, hist / f"{path.stem}__{dt.date.today():%Y%m%d}{path.suffix}")
        action = "actualizado"
    else:
        action = "nuevo"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(content)
    tmp.replace(path)
    _append_manifest(iso3, {"pais": iso3, "fuente": fuente, "archivo": filename, "url": url,
                      "bytes": len(content), "sha256": digest,
                      "descargado_en": dt.datetime.now().isoformat(timespec="seconds"),
                      "accion": action})
    return action


def _append_manifest(iso3: str, row: dict) -> None:
    # Un manifest por país: los descargadores de países distintos pueden correr a la vez.
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    path = CONTROL_DIR / f"manifest_{iso3}.csv"
    new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


def period_start(fecha: pd.Series, frecuencia: str) -> pd.Series:
    """Normaliza fechas al primer día del periodo."""
    fecha = pd.to_datetime(fecha)
    if frecuencia == "mensual":
        return fecha.dt.to_period("M").dt.start_time
    if frecuencia == "trimestral":
        return fecha.dt.to_period("Q").dt.start_time
    if frecuencia == "anual":
        return fecha.dt.to_period("Y").dt.start_time
    return fecha.dt.normalize()


def write_interim(iso3: str, df: pd.DataFrame) -> Path:
    """Valida el esquema común y escribe `data/interim/<ISO3>_observaciones.parquet`."""
    missing = set(INTERIM_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"Faltan columnas: {sorted(missing)}")
    df = df[INTERIM_COLUMNS].copy()
    df["pais"] = iso3
    df["indicador_comun"] = df["indicador_comun"].fillna("")
    df["fecha"] = pd.to_datetime(df["fecha"])
    df["valor"] = pd.to_numeric(df["valor"], errors="raise").astype(float)

    bad_freq = set(df.frecuencia) - set(FREQUENCIES)
    if bad_freq:
        raise ValueError(f"Frecuencias no válidas: {bad_freq}")
    common = _common_indicators()
    bad_ind = set(df.indicador_comun) - common - {""}
    if bad_ind:
        raise ValueError(f"indicador_comun fuera de config/indicadores_comunes.csv: {bad_ind}")
    # Un indicador común = una sola serie por país.
    per_ind = df[df.indicador_comun != ""].groupby("indicador_comun").nombre_corto.nunique()
    if (per_ind > 1).any():
        raise ValueError(f"Indicador común con más de una serie: {list(per_ind[per_ind > 1].index)}")
    per_name = df.groupby("nombre_corto")[["fuente", "codigo_fuente", "frecuencia"]].nunique()
    if (per_name > 1).any(axis=None):
        raise ValueError("nombre_corto repetido para series distintas")
    dup = df.duplicated(["nombre_corto", "fecha"])
    if dup.any():
        raise ValueError(f"{dup.sum()} periodos repetidos, p. ej. {df[dup].head(3).to_dict('records')}")
    df = df.dropna(subset=["valor"])

    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    out = INTERIM_DIR / f"{iso3}_observaciones.parquet"
    df.sort_values(["nombre_corto", "fecha"]).to_parquet(out, index=False)
    summary = df.groupby(["nombre_corto", "frecuencia"]).fecha.agg(["min", "max", "count"])
    log.info("%s: %d observaciones de %d series → %s", iso3, len(df), len(summary), out.name)
    for (name, freq), r in summary.iterrows():
        log.info("  %-34s %-10s n=%6d  %s → %s", name, freq, r["count"],
                 f"{r['min']:%Y-%m-%d}", f"{r['max']:%Y-%m-%d}")
    return out


def _common_indicators() -> set[str]:
    with (CONFIG_DIR / "indicadores_comunes.csv").open(encoding="utf-8-sig", newline="") as f:
        return {r["indicador_comun"] for r in csv.DictReader(f)}
