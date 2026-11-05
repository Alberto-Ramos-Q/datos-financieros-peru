"""Corre el descargador de cada país, consolida y arma la capa comparable (armonizar.py).

Los países van uno tras otro (cada uno contra servidores distintos, pero así el
log queda legible y ningún sitio recibe ráfagas). Si un país falla, se sigue con
el resto y se informa al final.

Uso:
    python actualizar_todo.py                    # todos los países
    python actualizar_todo.py --paises chl mex   # solo algunos
    python actualizar_todo.py --solo-procesar    # rehace interim/processed sin red
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--paises", nargs="+", help="códigos ISO3 en minúscula (por defecto, todos)")
    ap.add_argument("--solo-procesar", action="store_true")
    args = ap.parse_args()

    scripts = sorted(p for p in (SRC / "paises").glob("*.py") if not p.stem.startswith("_"))
    if args.paises:
        scripts = [p for p in scripts if p.stem in {x.lower() for x in args.paises}]
    failed = []
    for script in scripts:
        print(f"\n===== {script.stem.upper()} =====", flush=True)
        cmd = [sys.executable, str(script)] + (["--solo-procesar"] if args.solo_procesar else [])
        if subprocess.run(cmd).returncode != 0:
            failed.append(script.stem.upper())

    print("\n===== CONSOLIDAR =====", flush=True)
    rc = subprocess.run([sys.executable, str(SRC / "consolidar.py")]).returncode
    if rc == 0:
        print("\n===== CAPA COMPARABLE =====", flush=True)
        rc = subprocess.run([sys.executable, str(SRC / "armonizar.py")]).returncode
    if failed:
        print(f"\nPaíses con error: {', '.join(failed)} (ver data/_control/logs/)")
    return 1 if failed or rc else 0


if __name__ == "__main__":
    sys.exit(main())
