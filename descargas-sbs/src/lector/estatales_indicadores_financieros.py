"""Lector de E-5201 «Indicadores Financieros por Entidad Estatal (BN, COFIDE, Agrobanco en columnas)» (tema `estatales-indicadores-financieros`, p=12, entidades estatales).

Reutiliza sin cambios `lector.indicadores_financieros` (mismo formato que el cuadro de la banca); las entidades
se resuelven con los alias del maestro restringidos al subsistema `entidades-estatales`.
Agregado el 2026-11-03. Historia probada: ver la sección de entidades estatales del README.
"""
from __future__ import annotations

from lector import indicadores_financieros as _base

leer = _base.leer
