"""Lee los cuadros descargados del boletín y arma una tabla larga por tema (entidad × mes × variable).

Para cada tema de `config/series.csv` usa su lector `src/lector/<tema>.py`, resuelve cada
nombre de entidad con el maestro (`entidades.py`) y escribe:

    data/processed/boletin/<tema>.parquet      columnas: ver `lector/comun.py`
    data/processed/boletin/_control/<tema>_archivos.csv   filas leídas o error por archivo
    data/processed/boletin/_control/<tema>_sin_resolver.csv  nombres que el maestro no reconoce
    data/processed/boletin/_control/<tema>_validacion.csv    suma de entidades ≠ total publicado
                                                             (o la regla propia del lector si
                                                             define `validar_totales(df)`)

Los temas de las entidades estatales (subsistema `entidades-estatales`, temas `estatales-*`, 2026-11-03)
van a `data/processed/boletin_estatales/` con su propio `_control/`: así `consolidar.py`, que lee todo
`data/processed/boletin/`, no los suma a los 5 subsistemas. Un tema no puede mezclar ambos.

Uso:
    python leer_boletin.py                              # todos los temas con lector
    python leer_boletin.py --tema indicadores-financieros
    python leer_boletin.py --tema ratio-capital-global --subsistema cajas-rurales --desde 202401
"""
from __future__ import annotations

import argparse
import csv
import importlib
import sys
import time
from functools import lru_cache
from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))
from lector import comun  # noqa: E402

RAW_DIR = PROJECT_DIR / "data" / "raw" / "boletin"
OUT_DIR = PROJECT_DIR / "data" / "processed" / "boletin"
# Entidades estatales (p=12; BN, COFIDE, Agrobanco, Fondo MiVivienda; 2026-11-03): sus temas van a otra
# carpeta para que `consolidar.py` (que lee todo `OUT_DIR`) y los tableros no los sumen a los 5 subsistemas.
ESTATALES = "entidades-estatales"
OUT_DIR_ESTATALES = PROJECT_DIR / "data" / "processed" / "boletin_estatales"
SERIES_CSV = PROJECT_DIR / "config" / "series.csv"


@lru_cache(maxsize=None)
def resolver(nombre: str, subsistema: str, periodo: int) -> tuple[str | None, bool]:
    return comun.resolver_entidad(nombre, subsistema, periodo)


def modulo_de(tema: str):
    try:
        return importlib.import_module(f"lector.{tema.replace('-', '_')}")
    except ModuleNotFoundError:
        return None


def carpeta_salida(tema: str, series: list[dict]) -> Path:
    """OUT_DIR, u OUT_DIR_ESTATALES si todas las series del tema son de entidades estatales."""
    subs = {s["subsistema"] for s in series if s["tema"] == tema}
    if ESTATALES in subs and subs != {ESTATALES}:
        raise ValueError(f"{tema}: mezcla entidades estatales con otros subsistemas ({sorted(subs)})")
    return OUT_DIR_ESTATALES if subs == {ESTATALES} else OUT_DIR


def leer_tema(tema: str, series: list[dict], desde: int, hasta: int, base: Path = OUT_DIR) -> pd.DataFrame:
    mod = modulo_de(tema)
    control = base / "_control"
    control.mkdir(parents=True, exist_ok=True)
    partes, log = [], []
    for s in series:
        carpeta = RAW_DIR / s["subsistema"] / tema
        for ruta in sorted(carpeta.glob(f"{s['codigo']}-*.XLS")):
            periodo = comun.periodo_de(ruta)
            # El `desde` (y el `hasta`, si lo hay) de series.csv manda: archivos fuera de ese rango
            # (p. ej. historia bajada antes de adaptar el lector a sus formatos, o meses de un
            # cuadro sustituto posteriores a su `hasta`) quedan en raw pero no se leen.
            if not max(desde, int(s["desde"])) <= periodo <= min(hasta, int(s.get("hasta") or 999999)):
                continue
            try:
                filas = [r for r in mod.leer(ruta, s["subsistema"], periodo) if r]
                # Cuadros con rezago (p. ej. el RCL trimestral): el lector dice a qué mes
                # corresponden los datos, que no es el del nombre del archivo.
                if hasattr(mod, "periodo_dato"):
                    periodo_dato = mod.periodo_dato(ruta, periodo)
                else:
                    periodo_dato = periodo
                log.append((ruta.name, s["subsistema"], periodo_dato, len(filas), ""))
            except Exception as exc:  # un archivo raro no detiene el resto; queda en el control
                log.append((ruta.name, s["subsistema"], periodo, 0, f"{type(exc).__name__}: {exc}"))
                continue
            if filas:
                d = pd.DataFrame(filas, columns=comun.CAMPOS_TEMA)
                d.insert(0, "periodo", periodo_dato)
                d.insert(1, "subsistema", s["subsistema"])
                d.insert(2, "tema", tema)
                d.insert(3, "codigo", s["codigo"])
                partes.append(d)
    with open(control / f"{tema}_archivos.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["archivo", "subsistema", "periodo", "filas", "error"])
        w.writerows(log)
    if not partes:
        return pd.DataFrame(columns=comun.CAMPOS)
    df = pd.concat(partes, ignore_index=True)
    # El periodo cuenta: un mismo nombre puede ser otra entidad en otro mes (Financiera Confianza
    # original hasta 2013-04, `confianza-original`).
    res = [resolver(n, sub, int(per)) for n, sub, per in
           zip(df["entidad_original"], df["subsistema"], df["periodo"])]
    df["id_entidad"] = [r[0] for r in res]
    df["es_total"] = [r[1] for r in res]
    df = df[comun.CAMPOS]
    sin = (df[df["id_entidad"].isna() & ~df["es_total"]]
           .groupby(["subsistema", "entidad_original"])["periodo"].agg(["min", "max", "count"]))
    sin.to_csv(control / f"{tema}_sin_resolver.csv", encoding="utf-8")
    # Temas cuyo total no es la suma de entidades (p. ej. deudores, que se consolidan) traen
    # su propia regla de validación en el lector.
    validar = getattr(mod, "validar_totales", comun.validar_totales)
    validar(df).to_csv(control / f"{tema}_validacion.csv", index=False, encoding="utf-8")
    return df


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--tema", action="append", help="Tema(s) a leer; por defecto todos los que tienen lector.")
    p.add_argument("--subsistema", action="append")
    p.add_argument("--desde", type=int, default=0, help="AAAAMM")
    p.add_argument("--hasta", type=int, default=999999, help="AAAAMM")
    p.add_argument("--destino", type=Path, default=OUT_DIR,
                   help="Carpeta de salida del parquet (para pruebas, p. ej. una carpeta temporal).")
    args = p.parse_args()

    with open(SERIES_CSV, encoding="utf-8") as fh:
        series = [r for r in csv.DictReader(fh) if r["activo"].strip() in ("1", "si", "sí", "true")]
    if args.subsistema:
        series = [s for s in series if s["subsistema"] in args.subsistema]
    temas = args.tema or sorted({s["tema"] for s in series if modulo_de(s["tema"])})
    args.destino.mkdir(parents=True, exist_ok=True)
    errores = 0
    for tema in temas:
        if not modulo_de(tema):
            print(f"{tema}: sin lector (falta src/lector/{tema.replace('-', '_')}.py)")
            errores += 1
            continue
        t0 = time.time()
        base = carpeta_salida(tema, series)
        destino = args.destino if base == OUT_DIR else (
            OUT_DIR_ESTATALES if args.destino == OUT_DIR else args.destino)
        destino.mkdir(parents=True, exist_ok=True)
        df = leer_tema(tema, [s for s in series if s["tema"] == tema], args.desde, args.hasta, base)
        df.to_parquet(destino / f"{tema}.parquet", index=False)
        archivos = pd.read_csv(base / "_control" / f"{tema}_archivos.csv")
        n_err = int(archivos["error"].notna().sum())
        errores += n_err
        sin = int((df["id_entidad"].isna() & ~df["es_total"]).sum()) if len(df) else 0
        print(f"{tema}: {len(archivos)} archivos, {n_err} con error, {len(df):,} filas, "
              f"{sin} filas sin entidad, {time.time() - t0:.0f} s")
    return 1 if errores else 0


if __name__ == "__main__":
    sys.exit(main())
