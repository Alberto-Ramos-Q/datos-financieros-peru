"""Lector de E-5204 «Requerimiento de Patrimonio Efectivo y Ratio de Capital Global» (tema `estatales-ratio-capital-global`, p=12, entidades estatales).

Reutiliza sin cambios `lector.ratio_capital_global` (mismo formato que el cuadro de la banca); las entidades
se resuelven con los alias del maestro restringidos al subsistema `entidades-estatales`.
Agregado el 2026-11-03. Historia probada: ver la sección de entidades estatales del README.
"""
from __future__ import annotations

from pathlib import Path

from lector import comun
from lector import ratio_capital_global as _base

# 2016-01 → 2017-01 el cuadro trae la columna «BANCA ESTATAL» (agregado de las estatales): se rotula
# como total del subsistema para que `comun.es_total` la reconozca.
AGREGADOS = {"banca estatal"}


def leer(ruta: Path, subsistema: str, periodo: int) -> list[dict]:
    filas = [r for r in _base.leer(ruta, subsistema, periodo) if r]
    for r in filas:
        if comun.norm(r["entidad_original"]) in AGREGADOS:
            r["entidad_original"] = "Total Entidades Estatales"
    return filas
