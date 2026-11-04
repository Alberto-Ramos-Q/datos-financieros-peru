"""Lector de E-5302 «Estructura del patrimonio efectivo» (tema `estatales-estructura-patrimonio-efectivo`, p=12, entidades estatales).

Reutiliza sin cambios `lector.estructura_patrimonio_efectivo` (mismo formato que el cuadro de la banca); las entidades
se resuelven con los alias del maestro restringidos al subsistema `entidades-estatales`.
Agregado el 2026-11-03. Historia probada: ver la sección de entidades estatales del README.
"""
from __future__ import annotations

from lector import estructura_patrimonio_efectivo as _base

leer = _base.leer
