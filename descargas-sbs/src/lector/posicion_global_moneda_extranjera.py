"""Lector de «Posición Global en Moneda Extranjera» (`posicion-global-moneda-extranjera`).

Códigos: B-2368 (banca múltiple), B-3266 (financieras), C-1260 (CMAC), C-2370 (CRAC),
C-4252 (empresas de créditos). Revisado 2015-01 → 2026-08 (B-) / 2026-07 (C-): sale un mes
después que el resto.

Layout
------
Una hoja por libro («Posición Global», «27», «26», «24», «CM», «CM (2)», «CR (2)», «EDP (2)»).
Entidades en FILAS (col. 0, ubicada con `comun.es_entidad`), cuatro columnas de conceptos en
una sola fila de cabecera. Igual en todo el periodo y en los 5 subsistemas (una sola era); las
columnas se identifican por su texto.

Variables (texto → variable)
----------------------------
- «Posición de Cambio de Balance en M.E. (a)» → `posicion_cambio_balance`
- «Posición Neta en Derivados de M.E. (b)» → `posicion_neta_derivados`
- «Delta de las Posiciones Netas en Opciones sobre M.E. (c)» → `delta_opciones`
- «Posición Global en M.E. (a)+(b)+(c)» → `posicion_global_me`

Apertura
--------
Vacía (el cuadro no desagrega).

Unidades
--------
`miles_soles` (título «En miles de (nuevos) soles»); las posiciones pueden ser negativas
(posición corta/de sobreventa). Las celdas «-» son «sin dato» y no se emiten, salvo la posición global de una
entidad con la de balance publicada (CMCP Lima desde 2026-06): se calcula (a)+(b)+(c) con los «-» en cero.

Totales y trampas
-----------------
- Extensión 2010-07 (2026-10-28): banca 2010 (hoja «Hoja1») y financieras 2011-05 → 2012-12 traen
  3 columnas: «Posición de Cambio en M. E. (a)» (→ `posicion_cambio_balance`), derivados (b) y
  «Posición Global (a)+(b)»; el delta de opciones (c) aparece en 2011 (banca) / 2013 (financieras).
  Financieras empieza en 2011-05; CMAC, CRAC y EC en 2014-07 (antes: indicador publicado
  posición global / PE, marcado en el panel por `consolidar.py`). Errata «Financira Proempresa»
  (2013-01) resuelta en el maestro.
- CMAC 2026-06 → : aparecen «TOTAL CAJAS MUNICIPALES DE AHORRO Y CRÉDITO» (sin CMCP Lima) y
  «TOTAL CAJAS MUNICIPALES»; se conserva solo el último (el más amplio).
- Las funciones de ubicación (columna de entidades, cabeceras, filas) se reutilizan de
  `ratio_capital_global`.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from . import comun
from .ratio_capital_global import cabeceras, columna_entidades, filas_entidad

UNIDAD = "miles_soles"
VARIABLES = [("delta de las posiciones netas en opciones", "delta_opciones"),
             ("posicion neta en derivados", "posicion_neta_derivados"),
             ("posicion de cambio de balance", "posicion_cambio_balance"),
             # banca 2010 y financieras hasta 2012: «Posición de Cambio en M. E. (a)», sin delta
             # de opciones; global = (a)+(b)
             ("posicion de cambio en m", "posicion_cambio_balance"),
             ("posicion global", "posicion_global_me")]


def mapear(propio: str, grupo: str) -> str:
    variable = next((v for k, v in VARIABLES if k in propio), None)
    if not variable:
        raise ValueError(f"columna no reconocida: {propio!r} (grupo {grupo!r})")
    return variable


def leer(ruta: Path, subsistema: str, periodo: int) -> list[dict]:
    out = []
    for hoja, g in comun.abrir(ruta).items():
        ubic = columna_entidades(g, subsistema)
        if ubic is None:
            continue
        ec, filas_ok = ubic
        cab = cabeceras(g, ec, filas_ok[0])
        # Columna con dato = la que tiene cabecera reconocible o alguna cifra en las entidades
        # (la col. de derivados puede venir toda en «-»).
        datos = [j for j in cab if cab[j][0] or
                 any(comun.a_numero(g.iat[i, j]) is not None for i in filas_ok)]
        columnas = {j: mapear(*cab[j]) for j in datos}
        vistos = Counter(columnas.values())
        if any(c > 1 for c in vistos.values()):
            raise ValueError(f"{hoja}: columnas duplicadas {[m for m, c in vistos.items() if c > 1]}")
        glob = next((j for j, v in columnas.items() if v == "posicion_global_me"), None)
        for i in filas_entidad(g, ec, filas_ok, datos, subsistema):
            for j, variable in columnas.items():
                out.append(comun.registro(hoja, g.iat[i, ec], variable, "", g.iat[i, j], UNIDAD))
            # CMCP Lima desde 2026-06: posición global «-» con la de balance (a) publicada. La cabecera define la global
            # como (a)+(b)+(c): se calcula con los «-» en cero. (El total publicado de las cajas no la incluye.)
            celda = g.iat[i, glob] if glob is not None else None
            if periodo >= 202606 and isinstance(celda, str) and celda.strip() == "-":
                partes = [comun.a_numero(g.iat[i, j]) for j, v in columnas.items() if v != "posicion_global_me"]
                if any(x is not None for x in partes):
                    out.append(comun.registro(hoja, g.iat[i, ec], "posicion_global_me", "",
                                              sum(x for x in partes if x is not None), UNIDAD))
    return out
