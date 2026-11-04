"""Lector de E-5205 «Créditos directos según tipo de crédito y situación (BN y Agrobanco en filas)» (tema `estatales-creditos-tipo-situacion`, p=12, entidades estatales).

Reutiliza sin cambios `lector.creditos_tipo_situacion` (mismo formato que el cuadro de la banca); las entidades
se resuelven con los alias del maestro restringidos al subsistema `entidades-estatales`.
Agregado el 2026-11-03. Historia probada: ver la sección de entidades estatales del README.
"""
from __future__ import annotations

from lector import creditos_tipo_situacion as _base

leer = _base.leer
