"""Lector de «Ratios de Liquidez en Moneda Nacional y Moneda Extranjera» (`ratios-liquidez`).

Códigos: B-2340 (banca múltiple), B-3250 (financieras), C-1244 (CMAC), C-2249 (CRAC). Las
empresas de créditos no captan depósitos y no tienen este cuadro. Revisado 2015-01 → 2026-08.

Layout
------
Una hoja por libro (nombres según era: «P025P», «P015P», «P025», «P025 (P)», «P011P», «21»,
«20», «CM», «CR»). Entidades en FILAS; conceptos en dos grupos de tres columnas:
«Liquidez en Moneda Nacional» y «Liquidez en Moneda Extranjera», cada uno con activos líquidos,
pasivos de corto plazo y ratio. Las columnas se identifican por su texto y por el grupo (primera
fila de cabecera propagada a la derecha); la columna de entidades se ubica con
`comun.es_entidad` (es la col. 1 en B-2340 2015-01 y la col. 0 en el resto). Eras:
- hasta 2019-12 (banca/financieras) la unidad va en el título del grupo («(En miles de nuevos
  soles)», «(En miles de dólares)»);
- desde 2020-01 va dentro de cada columna («Activos Líquidos (a) (En miles de soles)»).
El contenido (6 columnas) no cambia en todo el periodo.

Variables (texto → variable)
----------------------------
- «Activos Líquidos» → `activos_liquidos`
- «Pasivos de Corto Plazo» → `pasivos_corto_plazo`
- «Ratio de Liquidez (a)/(b)», «(c)/(d)» → `ratio_liquidez`

Apertura
--------
Moneda: `mn` o `me`.

Unidades
--------
MN en `miles_soles`; ME en `miles_usd` (la cabecera dice «En miles de dólares»; se exige que lo
diga, si no, error); ratios en `porcentaje` (ya vienen en puntos porcentuales: 28.73 = 28,73 %,
comprobado contra activos / pasivos).

Totales y trampas
-----------------
- Extensión 2010-07 (2026-10-28): mismo layout. Financieras empieza en 2010-10 y escribe
  «Financiera Univerasl» (errata, alias en el maestro) hasta 2014; CMAC 2010-09 deja filas «CHECK DE
  TOTALES CM/CMAC» bajo las notas, que `filas_entidad` descarta.
- CMAC: se omite «TOTAL CAJAS MUNICIPALES DE AHORRO Y CRÉDITO» (sin CMCP Lima) y se conserva el
  último total, «TOTAL CAJAS MUNICIPALES».
- Las funciones de ubicación (columna de entidades, cabeceras, filas) se reutilizan de
  `ratio_capital_global`.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from . import comun
from .ratio_capital_global import cabeceras, columna_entidades, filas_entidad

VARIABLES = [("activos liquidos", "activos_liquidos"), ("pasivos de corto plazo", "pasivos_corto_plazo"),
             ("ratio de liquidez", "ratio_liquidez")]


def mapear(propio: str, grupo: str) -> tuple[str, str, str]:
    """(variable, apertura, unidad) de una columna."""
    contexto = f"{grupo} {propio}"
    moneda = ("me" if "moneda extranjera" in grupo else "mn" if "moneda nacional" in grupo
              else None)
    variable = next((v for k, v in VARIABLES if k in propio), None)
    if not moneda or not variable:
        raise ValueError(f"columna no reconocida: {propio!r} (grupo {grupo!r})")
    if variable == "ratio_liquidez":
        return variable, moneda, "porcentaje"
    if moneda == "me":
        if "dolares" not in contexto:
            raise ValueError(f"columna ME sin «miles de dólares»: {propio!r}")
        return variable, moneda, "miles_usd"
    return variable, moneda, "miles_soles"


def leer(ruta: Path, subsistema: str, periodo: int) -> list[dict]:
    out = []
    for hoja, g in comun.abrir(ruta).items():
        ubic = columna_entidades(g, subsistema)
        if ubic is None:
            continue
        ec, filas_ok = ubic
        cab = cabeceras(g, ec, filas_ok[0])
        datos = [j for j in cab if any(comun.a_numero(g.iat[i, j]) is not None for i in filas_ok)]
        columnas = {j: mapear(*cab[j]) for j in datos}
        vistos = Counter(columnas.values())
        if any(c > 1 for c in vistos.values()):
            raise ValueError(f"{hoja}: columnas duplicadas {[m for m, c in vistos.items() if c > 1]}")
        for i in filas_entidad(g, ec, filas_ok, datos, subsistema):
            for j, (variable, apertura, unidad) in columnas.items():
                out.append(comun.registro(hoja, g.iat[i, ec], variable, apertura, g.iat[i, j], unidad))
    return out
