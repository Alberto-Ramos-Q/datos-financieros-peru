"""Lector de «Requerimiento de Patrimonio Efectivo y Ratio de Capital Global» (`ratio-capital-global`).

Códigos: B-2402 (banca múltiple), B-3302 (financieras), C-1252 (CMAC), C-2257 (CRAC),
C-4241 (empresas de créditos). Revisado sobre 2015-01 → 2026-08 (B-) / 2026-07 (C-): el cuadro
sale un mes después que el resto.

Layout
------
Una hoja por libro («Palanca-Global», «Palanca-GlobalP», «Ratio de capital CM/CR/EDP», «8»,
«9»). Entidades en FILAS (columna 0; se ubica con `comun.es_entidad`), conceptos en columnas
con una cabecera de 2-4 filas encima de la primera entidad. Cada columna se identifica por su
texto (y el del grupo de la primera fila de cabecera, propagado a la derecha), nunca por
posición. Eras encontradas (iguales en los 5 subsistemas):

- E1 2015-01 → 2021-03: requerimiento de PE por riesgo de crédito (a), mercado (b),
  operacional (c), total (d); patrimonio efectivo total (e); RCG = e / (d / 10 %).
- E2 2021-04 → 2023-05: además APR (activos y contingentes ponderados por riesgo) por crédito,
  mercado, operacional y total; RCG = PE / APR. (2021-05/06 y 2022-08/09 traen en la col. 28
  una columna de control «Comprob. ratio k» que se ignora.)
- E3 2023-06 → : requerimientos (a, b, c) sin total; APR (d, e, f) y total (g); ratios de capital
  ordinario de nivel 1 / APR, de patrimonio efectivo de nivel 1 / APR y RCG. Ya NO publica el
  patrimonio efectivo total. (Financieras/banca 2023-06 → 2025-04 rotulan la col. 11 «Ratio de
  requerimiento de patrimonio efectivo de nivel 1»: es el mismo PE N1 / APR.)

Variables (texto de la columna → variable, unidad)
--------------------------------------------------
- «Requerimiento de patrimonio efectivo … por riesgo de X» → `requerimiento_patrimonio_efectivo`
  (miles_soles); apertura = tipo de riesgo.
- «Activos (y contingentes) ponderados por riesgo … de X» → `activos_ponderados_riesgo`
  (miles_soles); apertura = tipo de riesgo.
- «Patrimonio efectivo total» → `patrimonio_efectivo` (miles_soles).
- «Ratio de capital global» → `ratio_capital_global` (porcentaje).
- «Capital ordinario de nivel 1 / APR» → `ratio_capital_ordinario_nivel1` (porcentaje).
- «Patrimonio efectivo de nivel 1 / APR» → `ratio_patrimonio_efectivo_nivel1` (porcentaje).

Apertura
--------
Tipo de riesgo: `riesgo_credito`, `riesgo_mercado`, `riesgo_operacional` o `total`; vacía en
las variables sin desagregación.

Unidades
--------
Montos en miles de soles (título «En miles de (nuevos) soles»). Los ratios vienen ya en
porcentaje (13.76 = 13,76 %, comprobado contra PE / APR) y se guardan tal cual.

Totales y trampas
-----------------
- CMAC: «TOTAL CAJAS MUNICIPALES DE AHORRO Y CRÉDITO» (sin CMCP Lima) se OMITE; se conserva el
  último total, «TOTAL CAJAS MUNICIPALES» (incluye CMCP Lima). Regla: si hay varios totales, vale
  el último.
- Banca 2022-07 → 2022-09: la SBS ajustó el total «para incluir/considerar a BCI» (nota al pie).
- Las filas de entidad se mueven entre meses (entradas, salidas, renombres): se leen todas las
  filas con nombre y cifras entre la primera y la última entidad reconocida.
- Una columna con cifras que no se reconoce levanta `ValueError` (queda en el control).
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from . import comun

FECHA_RE = re.compile(r"^\d{4}-\d{2}-\d{2}|publicad|^al \d")


def texto(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def columna_entidades(g, subsistema: str) -> tuple[int, list[int]] | None:
    """(columna de nombres, filas con entidad reconocida) o None si la hoja no tiene entidades."""
    cuenta = Counter()
    for i in range(g.shape[0]):
        for j in range(min(4, g.shape[1])):
            if comun.es_entidad(g.iat[i, j], subsistema):
                cuenta[j] += 1
    if not cuenta:
        return None
    ec = cuenta.most_common(1)[0][0]
    return ec, [i for i in range(g.shape[0]) if comun.es_entidad(g.iat[i, ec], subsistema)]


def cabeceras(g, ec: int, r0: int) -> dict[int, tuple[str, str]]:
    """{columna: (texto propio, texto del grupo)} con las filas de cabecera sobre la fila r0.

    Filas de cabecera: las de las 8 anteriores a r0 con texto en 2+ columnas a la derecha de la
    de entidades (descarta título, fecha y unidad). El grupo es el texto de la primera fila de
    cabecera propagado hacia la derecha («REQUERIMIENTO DE PATRIMONIO EFECTIVO» cubre a, b, c, d).
    """
    nc = g.shape[1]
    filas = [i for i in range(max(0, r0 - 8), r0)
             if sum(1 for j in range(ec + 1, nc)
                    if texto(g.iat[i, j]) and not FECHA_RE.search(comun.norm(g.iat[i, j]))) >= 2]
    out = {}
    grupo = ""
    for j in range(ec + 1, nc):
        if filas and texto(g.iat[filas[0], j]):
            grupo = comun.norm(g.iat[filas[0], j])
        propio = " ".join(comun.norm(g.iat[i, j]) for i in filas if texto(g.iat[i, j]))
        out[j] = (propio, grupo)
    return out


def filas_entidad(g, ec: int, filas_ok: list[int], datos: list[int], subsistema: str) -> list[int]:
    """Filas con nombre y cifras desde la primera entidad reconocida; si hay varios totales,
    solo el último (el más amplio)."""
    r0, r1 = filas_ok[0], filas_ok[-1]
    filas = []
    for i in range(r0, g.shape[0]):
        nombre = texto(g.iat[i, ec])
        if re.match(r"che(ck|queo)\b", comun.norm(nombre)):
            continue  # filas de trabajo de la SBS bajo las notas («CHECK DE TOTALES CM», CMAC 2010-09)
        n_cifras = sum(comun.a_numero(g.iat[i, j]) is not None for j in datos)
        if nombre and n_cifras and (i <= r1 or n_cifras >= 2):
            filas.append(i)
    totales = [i for i in filas if comun.es_total(g.iat[i, ec])]
    return [i for i in filas if i not in totales[:-1]]


def mapear(propio: str, grupo: str) -> tuple[str, str, str] | None:
    """(variable, apertura, unidad) de una columna; None si es una columna de control."""
    if "comprob" in propio:
        return None
    if "capital ordinario de nivel 1" in propio:
        return "ratio_capital_ordinario_nivel1", "", "porcentaje"
    if "patrimonio efectivo de nivel 1" in propio:
        return "ratio_patrimonio_efectivo_nivel1", "", "porcentaje"
    if "ratio de capital global" in propio:
        return "ratio_capital_global", "", "porcentaje"
    if "patrimonio efectivo total" in propio:
        return "patrimonio_efectivo", "", "miles_soles"
    riesgo = next((f"riesgo_{r}" for r in ("credito", "mercado", "operacional") if r in propio),
                  "total" if "total" in propio else None)
    if riesgo:
        if "ponderados" in propio or "ponderados" in grupo:
            return "activos_ponderados_riesgo", riesgo, "miles_soles"
        if "requerimiento" in propio or "requerimiento" in grupo:
            return "requerimiento_patrimonio_efectivo", riesgo, "miles_soles"
    raise ValueError(f"columna no reconocida: {propio!r} (grupo {grupo!r})")


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
        vistos = Counter(m for m in columnas.values() if m)
        if any(c > 1 for c in vistos.values()):
            raise ValueError(f"{hoja}: columnas duplicadas {[m for m, c in vistos.items() if c > 1]}")
        for i in filas_entidad(g, ec, filas_ok, datos, subsistema):
            for j, m in columnas.items():
                if m:
                    out.append(comun.registro(hoja, g.iat[i, ec], m[0], m[1], g.iat[i, j], m[2]))
    return out
