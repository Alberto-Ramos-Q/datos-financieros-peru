"""Lector de E-5206 «Estructura de créditos directos e indirectos según categoría de riesgo del deudor» (tema `estatales-categoria-riesgo-deudor`, p=12, entidades estatales).

Reutiliza sin cambios `lector.categoria_riesgo_deudor` (mismo formato que el cuadro de la banca); las entidades
se resuelven con los alias del maestro restringidos al subsistema `entidades-estatales`.
Agregado el 2026-11-03. Historia probada: ver la sección de entidades estatales del README.
"""
from __future__ import annotations

from lector import categoria_riesgo_deudor as _base

leer = _base.leer
