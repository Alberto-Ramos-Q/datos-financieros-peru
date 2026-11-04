"""Lector de R-0001 «Ratio de cobertura de liquidez» (tema `estatales-ratio-cobertura-liquidez`, p=12, entidades estatales).

Reutiliza sin cambios `lector.ratio_cobertura_liquidez` (mismo formato que el cuadro de la banca); las entidades
se resuelven con los alias del maestro restringidos al subsistema `entidades-estatales`.
Agregado el 2026-11-03. Historia probada: ver la sección de entidades estatales del README.
"""
from __future__ import annotations

from lector import ratio_cobertura_liquidez as _base

leer = _base.leer
periodo_dato = _base.periodo_dato

# Agregados de las estatales («CONSOLIDADO_BN» en el RCL, idéntico a la hoja «Nacion» porque solo el BN
# reporta; «CONSOLIDADO BANCA ESTATAL» en el RFNE, que incluye COFIDE y Fondo MiVivienda) = total del
# subsistema. Agregar la clave no cambia nada para los demás subsistemas (verificado 2026-11-03).
_base.TOTAL_SUBSISTEMA.setdefault("entidades-estatales", "Total Entidades Estatales")
