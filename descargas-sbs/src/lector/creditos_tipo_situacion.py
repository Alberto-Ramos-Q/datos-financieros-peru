"""Lector del tema `creditos-tipo-situacion` (B-2334, B-3220, C-1228, C-2228, C-4223).

Cuadro «Créditos Directos según Tipo de Crédito y Situación» (miles de soles). Dos layouts
estables en todo 2015-01 → 2026-08 (revisados los 700 archivos):

- Layout «B» (banca B-2334 y financieras B-3220): entidades en FILAS (col. 0) y en COLUMNAS
  tres filas de cabecera: tipo de crédito («Corporativo», …, «Consumo», «Hipotecarios para
  Vivienda», «Total Créditos Directos»), sub-tipo solo bajo Consumo («Revolventes» / «No
  Revolventes») y situación («Vigentes», «Refinanc. y Reestruct.», «Atrasados»). Hojas: banca
  «12» (y «P007P» en 2015-08/09); financieras «F051P»/«F051P »/«P005P »/«11» según el año.
  Total del subsistema en la fila «TOTAL BANCA MÚLTIPLE» / «TOTAL EMPRESAS FINANCIERAS».
- Layout «C» (CMAC C-1228, CRAC C-2228, EC C-4223): tipo de crédito en la col. 0 (solo en la
  primera fila de cada bloque), situación en la col. 1 y entidades en COLUMNAS (cabecera en la
  fila 3, o 4 cuando hay «Actualizado el …» arriba). Hojas «CM», «CR», «EDP». La fila «Total
  Créditos Directos» no tiene situación. Consumo NO se separa en revolvente/no revolvente.

Las posiciones se ubican siempre por etiqueta: cabecera de entidades con `comun.es_entidad`,
fila/columna de tipo por las etiquetas de tipo, situación por sus etiquetas.

Variable: `creditos_directos` (miles_soles), una sola en todo el tema.

Apertura: `tipo|situacion`
  tipo:      corporativos, grandes_empresas, medianas_empresas, pequenas_empresas,
             microempresas, consumo (layout C), consumo_revolvente, consumo_no_revolvente
             (layout B), hipotecarios, total («Total Créditos Directos»)
  situacion: vigentes, refinanciados_reestructurados («Refinanc. y Reestruct.»), atrasados,
             total (solo con tipo `total`: `total|total`)
  Etiquetas SBS → tipo: «Corporativo(s)» → corporativos; «Micro Empresas»/«Microempresas» →
  microempresas; «Hipotecarios para Vivienda» → hipotecarios; «Revolventes» bajo Consumo →
  consumo_revolvente; «No Revolventes» → consumo_no_revolvente.

Trampas
-------
- 2010-07 → 2014 (extensión del 2026-10-28), layout B: nombres en la col. 1 (col. 0 vacía); banca
  2010-07 → 2010-09 y financieras 2010-07 → 2010-09 con una sola columna «Actividades
  Empresariales/productivas *» (→ `empresariales`); banca 2010-10 → 2011-03 y financieras hasta
  2011-03 sin separar el consumo (→ `consumo`); «Reestruct. y Refinanciados» = refinanciados y
  reestructurados; rótulos de tipo sueltos en columnas intermedias (financieras) se ignoran: un
  tipo empieza en su columna «Vigentes».
- Varias columnas/filas de total: CMAC trae «TOTAL CAJAS MUNICIPALES DE AHORRO Y CRÉDITO»
  (sin la CMCP Lima) y «TOTAL CAJAS MUNICIPALES»; se queda solo el ÚLTIMO (todo el
  subsistema) y se descartan los subtotales.
- EC 2021-07 → 2022-02 trae una columna de trabajo «Chequeo de totales subsistema» a la derecha
  del total: el cuadro termina en la columna del total (layout C) o en la fila del total
  (layout B); lo que hay después se ignora (notas, bloques de cuadre de la SBS como el de banca
  2025-07 bajo la nota de Santander Consumer).
- Filas separadoras sin etiqueta con ceros sueltos (CMAC 2024-06, CRAC 2016-03/04, EC 2021-05):
  se ignoran solo si todas sus cifras son 0; con cualquier cifra distinta de 0, error.
- La suma de tipos × situación de una entidad no siempre da su «Total Créditos Directos»
  publicado (B. Pichincha 2024-04: 89.032; Financiera TFC 2016-05: 29.587; total financieras
  2019-11: 16.334). Viene así en el archivo; no se corrige.
- Banca/financieras no publican un «consumo» agregado: sumar revolvente + no revolvente.
- Una columna o fila con cifras que no se puede clasificar levanta ValueError.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import pandas as pd

from lector import comun

VARIABLE = "creditos_directos"
UNIDAD = "miles_soles"

TIPOS = [  # (regex sobre la etiqueta normalizada, token)
    (r"^corporativos?$", "corporativos"),
    (r"^grandes empresas$", "grandes_empresas"),
    (r"^medianas empresas$", "medianas_empresas"),
    (r"^pequenas empresas$", "pequenas_empresas"),
    (r"^micro ?empresas$", "microempresas"),
    (r"^consumo$", "consumo"),
    (r"^hipotecarios?( para vivienda)?$", "hipotecarios"),
    (r"^total creditos directos$", "total"),
    # 2010-07 → 2013-11 (banca y financieras): los cinco tipos empresariales en una sola columna
    (r"^actividades (empresariales|productivas)$", "empresariales"),  # «Actividades productivas *» (fin. 2010)
]
SUBTIPOS = [(r"^no revolventes?$", "consumo_no_revolvente"), (r"^revolventes?$", "consumo_revolvente")]
SITUACIONES = [
    (r"^vigentes?$", "vigentes"),
    (r"^refinanc\.? y reestruct\.?$|^refinanciados y reestructurados$|^reestruct\.? y refinanc",
     "refinanciados_reestructurados"),
    (r"^atrasados?$", "atrasados"),
]
NOTA_RE = re.compile(r"^\s*(nota|fuente|\*|\(\*\)|http)", re.IGNORECASE)


def _token(texto, tabla) -> str | None:
    n = comun.norm(texto)
    return next((t for patron, t in tabla if re.match(patron, n)), None) if n else None


@lru_cache(maxsize=None)
def _es_entidad(texto: str, subsistema: str) -> bool:
    return comun.es_entidad(texto, subsistema)


def _entidad(v, subsistema: str) -> bool:
    return isinstance(v, str) and _es_entidad(v, subsistema)


def leer(ruta: Path, subsistema: str, periodo: int) -> list[dict]:
    out: list[dict] = []
    for hoja, df in comun.abrir(ruta).items():
        out += _leer_hoja(str(hoja).strip(), df, subsistema)
    return out


def _leer_hoja(hoja: str, df: pd.DataFrame, subsistema: str) -> list[dict]:
    nr, nc = df.shape
    # Layout B: nombres en la col. 0 (en 2010-2014, en la col. 1, con la col. 0 vacía).
    for ec in range(min(2, nc)):
        filas_ent = [i for i in range(nr) if _entidad(df.iat[i, ec], subsistema)]
        if len(filas_ent) >= 2:
            return _layout_b(hoja, df, subsistema, filas_ent, ec)
    h = next((i for i in range(min(nr, 20))
              if sum(_entidad(df.iat[i, j], subsistema) for j in range(nc)) >= 2), None)
    if h is not None:
        return _layout_c(hoja, df, subsistema, h)
    if any(comun.a_numero(v) is not None for v in df.to_numpy().ravel()):
        raise ValueError(f"hoja {hoja!r}: tiene cifras pero no se encontró la cabecera de entidades")
    return []


def _ultimo_total(posiciones: list[int], nombres: dict[int, str]) -> list[int]:
    """Posiciones de entidades, sin los totales que no son el último (subtotales)."""
    totales = [p for p in posiciones if comun.es_total(nombres[p])]
    return [p for p in posiciones if p not in totales[:-1]]


def _layout_b(hoja: str, df: pd.DataFrame, subsistema: str, filas_ent: list[int], ec: int = 0) -> list[dict]:
    nr, nc = df.shape
    f0 = filas_ent[0]
    cab = range(max(0, f0 - 6), f0)
    f_tipo = next((i for i in cab if sum(_token(df.iat[i, j], TIPOS) is not None for j in range(nc)) >= 3), None)
    f_sit = next((i for i in cab if sum(_token(df.iat[i, j], SITUACIONES) is not None for j in range(nc)) >= 3), None)
    if f_tipo is None or f_sit is None:
        raise ValueError(f"hoja {hoja!r}: no se ubicó la cabecera de tipo/situación")
    # Columna → apertura. El tipo y el sub-tipo se propagan a la derecha hasta el siguiente rótulo.
    aperturas: dict[int, str] = {}
    tipo = sub = None
    for j in range(ec + 1, nc):
        t = _token(df.iat[f_tipo, j], TIPOS)
        sit = _token(df.iat[f_sit, j], SITUACIONES)
        # Un bloque de tipo empieza en su columna «Vigentes» (o es el total). Financieras
        # 2010-07 → 2011-03 dejan rótulos sueltos en mayúsculas («CONSUMO», «MICROEMPRESAS»)
        # sobre columnas intermedias de otro bloque: se ignoran.
        if t and (t == "total" or sit == "vigentes"):
            tipo, sub = t, None
        for i in range(f_tipo + 1, f_sit):
            s = _token(df.iat[i, j], SUBTIPOS)
            if s:
                sub = s
        if tipo == "total":
            aperturas[j] = "total|total"
        elif tipo and sit:
            t_final = sub if (tipo == "consumo" and sub) else tipo
            aperturas[j] = f"{t_final}|{sit}"
    # Filas: desde la primera entidad hasta el último total (o hasta las notas al pie).
    nombres = {i: df.iat[i, ec] for i in filas_ent}
    totales = [i for i in filas_ent if comun.es_total(nombres[i])]
    fin = totales[-1] if totales else next(
        (i for i in range(f0, nr) if isinstance(df.iat[i, ec], str) and NOTA_RE.match(df.iat[i, ec])), nr - 1)
    filas = [i for i in range(f0, fin + 1) if i not in totales[:-1]]

    out: list[dict] = []
    for i in filas:
        nombre = df.iat[i, ec]
        cifras = [j for j in range(ec + 1, nc) if comun.a_numero(df.iat[i, j]) is not None]
        if not cifras:
            continue
        if not isinstance(nombre, str) or not nombre.strip():
            raise ValueError(f"hoja {hoja!r} fila {i}: cifras sin nombre de entidad")
        for j in cifras:
            if j not in aperturas:
                raise ValueError(f"hoja {hoja!r} fila {i} col {j}: columna sin tipo/situación")
            r = comun.registro(hoja, nombre, VARIABLE, aperturas[j], df.iat[i, j], UNIDAD)
            if r:
                out.append(r)
    return out


def _layout_c(hoja: str, df: pd.DataFrame, subsistema: str, h: int) -> list[dict]:
    nr, nc = df.shape
    cols = [j for j in range(nc) if _entidad(df.iat[h, j], subsistema)]
    nombres = {j: df.iat[h, j] for j in cols}
    totales = [j for j in cols if comun.es_total(nombres[j])]
    j_fin = totales[-1] if totales else nc - 1
    # Columnas a la derecha de la primera entidad y hasta el total con rótulo que no es entidad:
    # se incluyen igual (quedarán en «sin resolver») salvo columnas de trabajo de la SBS.
    for j in range(cols[0], j_fin + 1):
        v = df.iat[h, j]
        if j not in nombres and isinstance(v, str) and v.strip() and not re.match(r"che(qu|ck)eo", comun.norm(v)):
            nombres[j] = v
    cols = _ultimo_total(sorted(c for c in nombres if c <= j_fin), nombres)
    etiquetas = range(0, cols[0])

    out: list[dict] = []
    tipo = None
    for i in range(h + 1, nr):
        textos = [df.iat[i, k] for k in etiquetas if isinstance(df.iat[i, k], str) and df.iat[i, k].strip()]
        if any(NOTA_RE.match(t) for t in textos):
            break
        sit = None
        for t in textos:
            tipo = _token(t, TIPOS) or tipo
            sit = _token(t, SITUACIONES) or sit
        cifras = [j for j in cols if comun.a_numero(df.iat[i, j]) is not None]
        if not cifras:
            continue
        if tipo == "total" and sit is None:
            apertura = "total|total"
        elif tipo and tipo != "total" and sit:
            apertura = f"{tipo}|{sit}"
        elif not textos and all(comun.a_numero(df.iat[i, j]) == 0 for j in cifras):
            continue  # fila separadora con ceros sueltos (CMAC 2024-06, CRAC 2016-03/04, EC 2021-05)
        else:
            raise ValueError(f"hoja {hoja!r} fila {i}: no se pudo clasificar {textos!r}")
        for j in cifras:
            r = comun.registro(hoja, nombres[j], VARIABLE, apertura, df.iat[i, j], UNIDAD)
            if r:
                out.append(r)
    return out
