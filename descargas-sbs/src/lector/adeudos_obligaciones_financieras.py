"""Lector del cuadro «Estructura de los Adeudos y Obligaciones Financieras».

Códigos: B-2310 (banca múltiple), B-3239 (empresas financieras, desde 2015-09), C-1219 (cajas
municipales), C-2219 (cajas rurales), C-4214 (empresas de créditos, antes EDPYMEs).

Qué publica
-----------
Por entidad (filas): la estructura porcentual de sus adeudos y obligaciones financieras según
origen del acreedor (país / exterior y organismos internacionales) y plazo (corto / largo), y el
saldo total de adeudos y obligaciones financieras en miles de soles. Los cuatro porcentajes de
cada entidad suman 100.

Eras de layout
--------------
Una hoja por libro: «P034P» / «P026P» / «35» / «37» (banca), «34» (financieras), «CM (2)»,
«CR (2)», «Edp (2)». La estructura no cambia en el histórico; lo que cambia:
- banca y financieras: la unidad del total está dentro de la etiqueta de la columna
  («Total Adeudos y Obligaciones Financieras (En miles de nuevos soles)» hasta 2019-12,
  «(En miles de soles)» desde 2020-01); cajas y empresas de créditos la ponen en la fila de
  abajo («( En miles de nuevos soles )» hasta 2016-03, «( En miles de soles )» después);
- banca/financieras marcan los ceros con «-» (→ sin registro); cajas/EC escriben 0;
- la fila de cabecera empieza en la fila 4 o 5 según el subsistema; la hoja de EC 2026 tiene
  ~200 filas, casi todas vacías.
Todo se ubica por etiqueta: fila de cabecera = la que tiene «Instituciones del País»; columnas
por grupo (forward fill horizontal) + «Corto Plazo»/«Largo plazo» en la fila siguiente; columna
de entidades con `comun.es_entidad`.

Variables (etiqueta SBS → variable, unidad)
-------------------------------------------
- columnas de estructura (en porcentaje) → `participacion_adeudos` (porcentaje, puntos
  porcentuales: 31.2 = 31,2 % del total de adeudos de la entidad).
- «Total Adeudos y Obligaciones Financieras» → `adeudos_obligaciones_financieras`
  (miles_soles), apertura `total|total`.

Apertura: `origen|plazo`
------------------------
- origen: «Instituciones del País» → `pais`; «Instituciones del Exterior y Organismos
  Internacionales» → `exterior`; `total` para la columna del total.
- plazo: «Corto Plazo» → `corto_plazo`; «Largo Plazo» → `largo_plazo`; `total`.

Trampas
-------
- Cajas municipales traen DOS filas de total: «TOTAL CAJAS MUNICIPALES DE AHORRO Y CRÉDITO»
  (subtotal de las CMAC, antes de CMCP Lima) y «TOTAL CAJAS MUNICIPALES» (todo el subsistema).
  Ambas casan con `comun.TOTAL_RE`, y sumarlas rompería la validación: se conserva solo el
  ÚLTIMO total de la hoja (el del subsistema) y se descarta el subtotal CMAC (se recalcula
  sumando las CMAC si hace falta).
- Notas al pie que empiezan con «Nota»/«Fuente» cortan la lectura.
- Error de origen (única fila de `_validacion.csv`): empresas de créditos 2016-05, el
  «TOTAL EDPYMES» (951 001,7) omite a EDPYME Acceso Crediticio (155 417,6), que sí figura en
  la lista; la estructura % del total también está calculada sin ella.
- Errores de origen en %: financieras 2024-05 Financiera Proempresa (sus 4 % suman 56,5 y el
  total del subsistema 99,5); EC 2017-03/04 EDPYME GMG suma 100,04/100,01. Se publican tal cual.
- Entidades sin adeudos: cajas/EC publican 0 en todo (sus % suman 0, no 100).
- Empresas financieras: en `data/raw` no está B-3239 de 2026-08 (último mes: 2026-07).
- El total publicado del subsistema en porcentaje es el promedio ponderado por saldo; no se
  valida por suma (unidad no aditiva). La validación aditiva solo aplica al saldo en miles.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from lector import comun

ORIGEN = {
    "instituciones del pais": "pais",
    "instituciones del exterior y organismos internacionales": "exterior",
}
PLAZO = {"corto plazo": "corto_plazo", "largo plazo": "largo_plazo"}


def _leer_hoja(nombre_hoja: str, g, subsistema: str) -> list[dict]:
    txt = [[comun.norm(v) for v in g.iloc[i]] for i in range(len(g))]
    h = next((i for i, f in enumerate(txt) if "instituciones del pais" in f), None)
    if h is None:
        return []
    columnas = {}  # j -> (variable, apertura, unidad)
    grupo = ""
    unidad_total = None
    for j in range(g.shape[1]):
        if txt[h][j]:
            grupo = txt[h][j]
        if grupo in ORIGEN:
            p = txt[h + 1][j]
            if not p:
                continue
            if p not in PLAZO:
                raise ValueError(f"{nombre_hoja}: plazo desconocido {p!r}")
            columnas[j] = ("participacion_adeudos", f"{ORIGEN[grupo]}|{PLAZO[p]}", "porcentaje")
        elif grupo.startswith("total adeudos y obligaciones financieras") and txt[h][j]:
            debajo = " ".join(txt[i][j] for i in range(h, min(h + 3, len(g))))
            if "miles de nuevos soles" in debajo or "miles de soles" in debajo:
                unidad_total = "miles_soles"
            else:
                raise ValueError(f"{nombre_hoja}: unidad del total no encontrada")
            columnas[j] = ("adeudos_obligaciones_financieras", "total|total", unidad_total)
        elif txt[h][j] and grupo != "empresas":
            raise ValueError(f"{nombre_hoja}: columna desconocida {grupo!r}")
    if len(columnas) != 5 or unidad_total is None:
        raise ValueError(f"{nombre_hoja}: se esperaban 4 columnas de estructura y el total, hay {len(columnas)}")
    if not any(t == "(en porcentaje)" for f in txt[:h] for t in f):
        raise ValueError(f"{nombre_hoja}: no se encontró «(En porcentaje)»")
    primera = min(columnas)
    votos = {j: sum(comun.es_entidad(g.iat[i, j], subsistema) for i in range(h + 1, len(g)))
             for j in range(primera)}
    jn = max(votos, key=votos.get)
    if votos[jn] == 0:
        raise ValueError(f"{nombre_hoja}: no se encontró la columna de entidades")

    filas = []
    for i in range(h + 2, len(g)):
        nombre = g.iat[i, jn]
        n = comun.norm(nombre)
        if n.startswith("nota") or n.startswith("fuente"):
            break
        if not n:
            continue
        # filas con nombre y celdas en blanco (no «-») son texto suelto: se saltan
        if all(pd.isna(g.iat[i, j]) for j in columnas):
            continue
        filas.append(i)
    totales = [i for i in filas if comun.es_total(g.iat[i, jn])]
    descartar = set(totales[:-1])  # subtotal CMAC en cajas municipales
    salida = []
    for i in filas:
        if i in descartar:
            continue
        for j, (var, ap, unidad) in columnas.items():
            salida.append(comun.registro(nombre_hoja, g.iat[i, jn], var, ap, g.iat[i, j], unidad))
    return salida


def leer(ruta: Path, subsistema: str, periodo: int) -> list[dict]:
    salida = []
    for nombre_hoja, g in comun.abrir(ruta).items():
        salida += _leer_hoja(nombre_hoja, g, subsistema)
    return salida
