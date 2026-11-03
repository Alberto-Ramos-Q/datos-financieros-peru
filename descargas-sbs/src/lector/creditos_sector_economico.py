"""Lector de «Créditos a Actividades Empresariales por Sector Económico» (`creditos-sector-economico`).

Códigos: B-2336 (banca múltiple), B-3221 (financieras), C-1216 (CMAC), C-2216 (CRAC),
C-4210 (empresas de créditos).

Layout (TRANSPUESTO)
--------------------
Sectores en FILAS (col. 0) y entidades en COLUMNAS: la fila de cabecera empieza con «Sector
Económico» y trae el nombre de cada entidad; la última columna es «Total» (el subsistema).
Bajo la cabecera puede haber una fila con nombres anteriores de la entidad («Deutsche Bank
Perú») y otra con códigos internos («6», «22»...): no tienen rótulo de sector y se ignoran.
Termina en «TOTAL CRÉDITOS A ACTIVIDADES EMPRESARIALES» y notas («Fuente», «NOTA», «1/»).

Variable y apertura
-------------------
`creditos_sector` (miles_soles; créditos directos corporativos, a grandes, medianas, pequeñas y
microempresas) con apertura = rótulo del sector normalizado (p. ej. `industria_manufacturera`,
`comercio`) y `total`.

Trampas
-------
- La clasificación cambió a CIIU Rev. 4 a mediados de la serie (nota «1/ A partir de julio
  del …»): los rótulos de sector no son comparables entre eras («Minería» → «Explotación de
  Minas y Canteras»; «Hoteles y Restaurantes» → «Alojamiento y Servicios de Comida»). Para
  series largas usar medidas que no dependen del rótulo (concentración HHI, sector principal).
- CMAC trae dos columnas de total: «TOTAL CAJAS MUNICIPALES DE AHORRO Y CRÉDITO» (sin CMCP
  Lima) y «TOTAL CAJAS MUNICIPALES»; se queda la última. Su fila total se llama «CREDITOS
  CORPORATIVOS, A GRANDES, A MEDIANAS, A PEQUEÑAS Y A MICROEMPRESAS».
- La columna «Total» (a veces «Total (En miles de soles)») no la reconoce `comun.es_total` (no dice «Total banca…»): se renombra al
  total del subsistema.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import comun

UNIDAD = "miles_soles"
VARIABLE = "creditos_sector"
TOTAL_SUBSISTEMA = {
    "banca-multiple": "Total Banca Múltiple",
    "empresas-financieras": "Total Empresas Financieras",
    "cajas-municipales": "Total Cajas Municipales",
    "cajas-rurales": "Total Cajas Rurales",
    "empresas-credito": "Total Empresas de Créditos",
}


def _slug(texto: str) -> str:
    s = re.sub(r"\(.*?\)|\d+/", " ", comun.norm(texto))
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def _leer_hoja(hoja: str, g, subsistema: str) -> list[dict]:
    h = next((i for i in range(min(len(g), 20)) if comun.norm(g.iat[i, 0]).startswith("sector economico")), None)
    if h is None:
        return []
    cols = {}
    for j in range(1, g.shape[1]):
        nombre = g.iat[h, j]
        if comun.norm(nombre).startswith("total") and not comun.es_entidad(nombre, subsistema):  # «Total (En miles de soles)»
            cols[j] = TOTAL_SUBSISTEMA[subsistema]
        elif comun.es_entidad(nombre, subsistema):
            cols[j] = nombre
        elif comun.norm(nombre):
            raise ValueError(f"{hoja}: columna «{nombre}» no es una entidad conocida")
    if not cols:
        raise ValueError(f"{hoja}: cabecera sin entidades")
    totales = [j for j, n in cols.items() if comun.es_total(n)]
    for j in totales[:-1]:  # sin el subtotal CMAC (sin CMCP Lima)
        del cols[j]
    salida = []
    for i in range(h + 1, len(g)):
        etiqueta = comun.norm(g.iat[i, 0])
        if etiqueta.startswith(("fuente", "nota", "1/", "2/")):
            break
        if not etiqueta:
            continue
        apertura = "total" if etiqueta.startswith(("total", "creditos corporativos")) else _slug(g.iat[i, 0])
        salida += [comun.registro(hoja, nombre, VARIABLE, apertura, g.iat[i, j], UNIDAD) for j, nombre in cols.items()]
        if apertura == "total":
            break
    vistas = [r["apertura"] for r in salida if r and r["entidad_original"] == comun.limpiar(cols[max(cols)])]
    if len(vistas) != len(set(vistas)):
        raise ValueError(f"{hoja}: sector repetido")
    return salida


def leer(ruta: Path, subsistema: str, periodo: int) -> list[dict]:
    salida = []
    for hoja, g in comun.abrir(ruta).items():
        salida += _leer_hoja(hoja, g, subsistema)
    return salida
