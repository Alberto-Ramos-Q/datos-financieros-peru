"""Lector de «Requerimiento de Patrimonio Efectivo por Riesgo de Mercado» (`requerimiento-patrimonio-riesgo-mercado`).

Códigos: B-2337 (banca múltiple), B-3265 (financieras), C-1259 (CMAC), R-2369 (CRAC; OJO,
prefijo «R», C-2369 no existe), C-4251 (empresas de créditos). Los C- y R- salen un mes
después que el resto.

Layout
------
Una hoja («26», «Req Patrim»...). Entidades en FILAS (col. 0), cinco columnas bajo la cabecera
«Requerimiento de Patrimonio Efectivo por Riesgo de Mercado»: cambiario, precio, tasa de interés
(cartera de negociación), commodities y total. Se identifican por su texto.

Variable y apertura
-------------------
`requerimiento_riesgo_mercado` con apertura `cambiario`, `precio`, `tasa_interes`,
`commodities`, `total`; unidad `miles_soles`. El total coincide con
`ratio-capital-global` / `requerimiento_patrimonio_efectivo|riesgo_mercado`.

Trampas
-------
- Las celdas «-» son «sin dato» (en la práctica, cero) y no se emiten.
- Algunos libros declaran ~200 filas, casi todas vacías; los datos acaban en el total.
- Las funciones de ubicación se reutilizan de `ratio_capital_global`, como en
  `posicion_global_moneda_extranjera`.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from . import comun
from .ratio_capital_global import cabeceras, columna_entidades, filas_entidad

UNIDAD = "miles_soles"
VARIABLE = "requerimiento_riesgo_mercado"
APERTURAS = [("requerimiento total", "total"), ("cambiario", "cambiario"), ("precio", "precio"),
             ("tasa de interes", "tasa_interes"), ("commodities", "commodities")]


def mapear(propio: str, grupo: str) -> str:
    apertura = next((v for k, v in APERTURAS if k in propio), None)
    if not apertura:
        raise ValueError(f"columna no reconocida: {propio!r} (grupo {grupo!r})")
    return apertura


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
        vistos = Counter(columnas.values())
        if any(c > 1 for c in vistos.values()):
            raise ValueError(f"{hoja}: columnas duplicadas {[m for m, c in vistos.items() if c > 1]}")
        for i in filas_entidad(g, ec, filas_ok, datos, subsistema):
            for j, apertura in columnas.items():
                out.append(comun.registro(hoja, g.iat[i, ec], VARIABLE, apertura, g.iat[i, j], UNIDAD))
    return out
