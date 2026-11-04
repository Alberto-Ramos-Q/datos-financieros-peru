"""Descargador de indicadores fiscales del FMI (API pública del DataMapper) para la comparación internacional.

Todos los indicadores son del gobierno general, con el mismo concepto para todos los países:
- World Economic Outlook: resultado (préstamo neto / endeudamiento neto) y deuda bruta.
- Fiscal Monitor: resultado primario, deuda neta, ingresos y gasto.

Guarda la respuesta JSON de la API tal cual en `data/raw/fmi/<indicador>.json` (todos los países) y la descripción
de los indicadores (edición, fecha de modificación) en `data/raw/fmi/indicadores.json`.

Uso:
    python descargar_fmi.py
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
from pathlib import Path

import requests

PROJECT_DIR = Path(__file__).resolve().parents[1]
RAW = PROJECT_DIR / "data" / "raw" / "fmi"
API = "https://www.imf.org/external/datamapper/api/v1/"
INDICATORS = {
    "GGXCNL_NGDP": "resultado",           # WEO: General government net lending/borrowing (% del PBI)
    "GGXWDG_NGDP": "deuda_bruta",         # WEO: General government gross debt
    "GGXONLB_G01_GDP_PT": "resultado_primario",   # Fiscal Monitor
    "GGXWDN_G01_GDP_PT": "deuda_neta",            # Fiscal Monitor
    "GGR_G01_GDP_PT": "ingresos",                 # Fiscal Monitor
    "G_X_G01_GDP_PT": "gasto",                    # Fiscal Monitor
}


def get(url: str) -> dict:
    # Se declara que se espera JSON; sin esa cabecera la API responde 403. No se imita a un navegador.
    r = requests.get(url, timeout=90, headers={"Accept": "application/json"})
    r.raise_for_status()
    return r.json()


def main() -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    meta = get(API + "indicators")["indicators"]
    keep = {k: meta.get(k) for k in INDICATORS}
    missing = [k for k, v in keep.items() if v is None]
    if missing:
        print("AVISO: indicadores que la API ya no ofrece:", missing)
    # Todo se baja a memoria primero y se escribe al final: si una descarga falla, no quedan una edición nueva
    # en indicadores.json y datos viejos en los indicadores.
    got = {}
    for code in INDICATORS:
        if keep.get(code) is None:
            continue
        time.sleep(1)
        got[code] = get(API + code)
    for code, data in got.items():
        values = data.get("values", {}).get(code, {})
        (RAW / f"{code}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        per = values.get("PER", {})
        print(f"  {code:20s} {len(values):4d} países; Perú {min(per, default='-')}–{max(per, default='-')}; "
              f"{keep[code].get('source')} (modificado {keep[code].get('last-modified', '?')})")
    (RAW / "indicadores.json").write_text(json.dumps({"descargado_en": dt.datetime.now().isoformat(timespec="seconds"),
                                                      "indicadores": keep}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
