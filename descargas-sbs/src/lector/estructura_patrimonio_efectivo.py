"""Lector de «Estructura del Patrimonio Efectivo» (`estructura-patrimonio-efectivo`).

Códigos: B-2370 (banca múltiple), B-3252 (financieras), C-1257 (CMAC), C-2262 (CRAC),
C-4246 (empresas de créditos). Los C- salen un mes después que el resto.

Layout
------
Una hoja. Entidades en FILAS (col. 0 o col. 1 según el año: se ubica con el maestro) y el
patrimonio efectivo por componente en columnas, en miles de soles. Dos eras:
- hasta 2022: «Nivel 1 (a)», «Nivel 2 (b)», «Nivel 3 (c)», «Total (d)=(a)+(b)+(c)»;
- desde 2023 (Basilea III): «Capital Ordinario de Nivel 1», «Capital Adicional de Nivel 1»
  (bajo «Patrimonio Efectivo de Nivel 1»), «Patrimonio Efectivo de Nivel 2»,
  «Patrimonio Efectivo Total».

Unidades (trampa)
-----------------
Banca y financieras publican todo en miles de soles. CMAC, CRAC y empresas de créditos
(«(En porcentaje)» bajo el título) publican los COMPONENTES como % del total y solo el total en
miles: esos componentes salen como `participacion_patrimonio_efectivo` (porcentaje). El título
no es fiable (EC jun-jul 2026 dice «miles» y trae %): se decide por los datos, si los
componentes de cada entidad suman ~100 y el total no. Desde 2026
algunos cuadros cuelgan una columna «Check de totales», que se ignora.

Variable y apertura
-------------------
`patrimonio_efectivo` (miles_soles; o `participacion_patrimonio_efectivo` en porcentaje, ver
arriba) con apertura `nivel1`, `nivel2`, `nivel3`, `total` (era 1)
o `capital_ordinario_nivel1`, `capital_adicional_nivel1`, `nivel2`, `total` (era 2). El lector
no suma componentes: el nivel 1 de la era 2 es ordinario + adicional (lo calcula `consolidar.py`).

Uso: el total es el patrimonio efectivo publicado también después de 2023-06, cuando el cuadro
de ratio de capital global dejó de traerlo; la estructura mide la calidad del capital.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from . import comun
from .ratio_capital_global import cabeceras, columna_entidades, filas_entidad

UNIDAD = "miles_soles"
VARIABLE = "patrimonio_efectivo"
VARIABLE_PCT = "participacion_patrimonio_efectivo"
# El orden importa: «capital ordinario de nivel 1» contiene «nivel 1».
APERTURAS = [("capital ordinario", "capital_ordinario_nivel1"), ("capital adicional", "capital_adicional_nivel1"),
             ("total", "total"), ("nivel 3", "nivel3"), ("nivel 2", "nivel2"), ("nivel 1", "nivel1")]


def mapear(propio: str, grupo: str) -> str:
    apertura = next((v for k, v in APERTURAS if k in propio), None)
    if not apertura:
        raise ValueError(f"columna no reconocida: {propio!r} (grupo {grupo!r})")
    return apertura


def en_porcentaje(g, filas: list[int], columnas: dict[int, str]) -> bool:
    """True si los componentes son % del total: suman ~100 por entidad y el total no."""
    comp = [j for j, a in columnas.items() if a != "total"]
    tot = next((j for j, a in columnas.items() if a == "total"), None)
    sumas, totales = [], []
    for i in filas:
        vals = [comun.a_numero(g.iat[i, j]) for j in comp]
        if vals and all(v is not None for v in vals):
            sumas.append(sum(vals))
            totales.append(comun.a_numero(g.iat[i, tot]) if tot is not None else None)
    if not sumas:
        return False
    cerca = [abs(x - 100) < 0.5 for x in sumas]
    return sum(cerca) > len(cerca) / 2 and not all(t is not None and abs(t - 100) < 0.5 for t in totales)


def leer(ruta: Path, subsistema: str, periodo: int) -> list[dict]:
    out = []
    for hoja, g in comun.abrir(ruta).items():
        ubic = columna_entidades(g, subsistema)
        if ubic is None:
            continue
        ec, filas_ok = ubic
        cab = cabeceras(g, ec, filas_ok[0])
        datos = [j for j in cab if "check" not in cab[j][1] and (cab[j][0] or
                 any(comun.a_numero(g.iat[i, j]) is not None for i in filas_ok))]
        columnas = {j: mapear(*cab[j]) for j in datos}
        vistos = Counter(columnas.values())
        if any(c > 1 for c in vistos.values()):
            raise ValueError(f"{hoja}: columnas duplicadas {[m for m, c in vistos.items() if c > 1]}")
        pct = en_porcentaje(g, filas_ok, columnas)
        for i in filas_entidad(g, ec, filas_ok, datos, subsistema):
            for j, apertura in columnas.items():
                if pct and apertura != "total":
                    out.append(comun.registro(hoja, g.iat[i, ec], VARIABLE_PCT, apertura, g.iat[i, j], "porcentaje"))
                else:
                    out.append(comun.registro(hoja, g.iat[i, ec], VARIABLE, apertura, g.iat[i, j], UNIDAD))
    return out
