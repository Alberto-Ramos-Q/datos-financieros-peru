"""Lector de «Ganancias en Riesgo y Valor Patrimonial en Riesgo» (`ganancias-valor-patrimonial-riesgo`).

Códigos: B-2379 (banca múltiple), B-3267 (financieras), C-1262 (CMAC), C-2371 (CRAC; no
confundir con B-2371, swaps de banca), C-4254 (empresas de créditos). Se publica desde 2025-04
(riesgo de tasa de interés en el libro bancario, Res. SBS 4285-2024 y modificatorias).

Layout
------
Una hoja. Entidades en FILAS (col. 0); seis columnas con una fila de códigos internos debajo
de la cabecera («7», «9», «5»...: no tiene nombre de entidad y se ignora).

Variables (texto → variable, unidad)
------------------------------------
- «Ganancias en Riesgo (a)» → `ganancias_en_riesgo` (miles_soles)
- «Valor Patrimonial en Riesgo (b)» → `valor_patrimonial_en_riesgo` (miles_soles)
- «Patrimonio Efectivo T-1 (c)» → `patrimonio_efectivo_t_1` (miles_soles; el del mes ANTERIOR)
- «GeR (%) (d) = (a)/(c)» → `ganancias_en_riesgo_pe` (porcentaje)
- «VPR (%) (e) = (b)/(c)» → `valor_patrimonial_en_riesgo_pe` (porcentaje)
- «Requerimiento por Riesgo de Tasa de Interés en el Libro Bancario» →
  `requerimiento_tasa_interes_libro_bancario` (miles_soles; casi siempre «-»)

Apertura vacía.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from . import comun
from .ratio_capital_global import cabeceras, columna_entidades, filas_entidad

# El orden importa: el requerimiento va primero y «patrimonio efectivo» al final.
VARIABLES = [("requerimiento por riesgo de tasa", "requerimiento_tasa_interes_libro_bancario", "miles_soles"),
             ("ger (%)", "ganancias_en_riesgo_pe", "porcentaje"),
             ("vpr (%)", "valor_patrimonial_en_riesgo_pe", "porcentaje"),
             ("ganancias en riesgo", "ganancias_en_riesgo", "miles_soles"),
             ("valor patrimonial en riesgo", "valor_patrimonial_en_riesgo", "miles_soles"),
             ("patrimonio efectivo", "patrimonio_efectivo_t_1", "miles_soles")]


def mapear(propio: str, grupo: str) -> tuple[str, str]:
    par = next(((v, u) for k, v, u in VARIABLES if k in propio), None)
    if not par:
        raise ValueError(f"columna no reconocida: {propio!r} (grupo {grupo!r})")
    return par


def leer(ruta: Path, subsistema: str, periodo: int) -> list[dict]:
    out = []
    for hoja, g in comun.abrir(ruta).items():
        ubic = columna_entidades(g, subsistema)
        if ubic is None:
            continue
        ec, filas_ok = ubic
        cab = cabeceras(g, ec, filas_ok[0])
        datos = [j for j in cab if cab[j][0] or
                 any(comun.a_numero(g.iat[i, j]) is not None for i in filas_ok)]
        columnas = {j: mapear(*cab[j]) for j in datos}
        vistos = Counter(v for v, _ in columnas.values())
        if any(c > 1 for c in vistos.values()):
            raise ValueError(f"{hoja}: columnas duplicadas {[m for m, c in vistos.items() if c > 1]}")
        for i in filas_entidad(g, ec, filas_ok, datos, subsistema):
            for j, (variable, unidad) in columnas.items():
                out.append(comun.registro(hoja, g.iat[i, ec], variable, "", g.iat[i, j], unidad))
    return out
