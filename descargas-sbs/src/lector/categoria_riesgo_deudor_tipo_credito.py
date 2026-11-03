"""Lector de «Estructura de Créditos Directos e Indirectos (y Contingentes) por Tipo de Crédito y
Categoría de Riesgo del Deudor» (tema `categoria-riesgo-deudor-tipo-credito`).

Códigos: B-230802 (banca), B-3271 (financieras), C-1233 (CMAC), C-2233 (CRAC), C-4227 (EC).

Eras de layout (revisados los 700 archivos 2015-01 → 2026-08)
-------------------------------------------------------------
Hay dos layouts, uno por familia de subsistemas, estables en todo el periodo:

A. Banca y financieras — **entidades en filas** (columna «Empresas»/«Empresas*»). Cabecera de
   dos filas: la fila de tipos de crédito (celda combinada: la etiqueta está solo en la primera
   de sus 5 columnas, se rellena hacia la derecha) y debajo los códigos de categoría como
   números 0, 1, 2, 3, 4. Una columna vacía separa cada tipo. Sin montos.
   Hojas: banca `Calif-Public ` (2015-01/02) → `P020P` → `P009P` (2015-07) → `14` (2015-10+);
   financieras `P020P` → `P010P` → `13`.
B. CMAC, CRAC y EC — **entidades en columnas** (fila de cabecera con los nombres). Columna 0 =
   tipo de crédito (solo en la primera fila del bloque, se rellena hacia abajo); columna 1 =
   categoría («Normal», «CPP», …) y al final de cada bloque una fila de monto
   «Corp. (Miles S/.)», «Grand. Empr. (Miles S/)», … Hojas `CM`, `CR`, `EDP`.
   CMAC trae dos totales: «TOTAL CAJAS MUNICIPALES DE AHORRO Y CREDITO» (subtotal sin la CMCP
   Lima) y «TOTAL CAJAS MUNICIPALES» (total del subsistema); el subtotal se omite.
   Columnas basura a la derecha que no son entidad («Chequeo de totales CR» en EC 2021-07 →
   2022-02, un «=» en CMAC 2021-10/11 y 2022-01 → 2022-08) se ignoran.
Cambio de etiqueta entre eras: «(Miles S/.)» → «(Miles S/)» (2016-03/04).

Variables (etiqueta SBS normalizada → variable)
-----------------------------------------------
- Categorías «0»…«4» (layout A) o «Normal», «CPP», «Deficiente», «Dudoso», «Pérdida»
  (layout B) → `estructura_categoria_riesgo` (porcentaje de la cartera del tipo de crédito).
- «<tipo abreviado> (Miles S/.)» (solo layout B) → `creditos_directos_indirectos`.

Tipos de crédito: «Corporativos»/«Corp.» → `corporativos`; «Grandes Empresas»/«Grand. Empr.» →
`grandes_empresas`; «Medianas Empresas»/«Med. Empr.» → `medianas_empresas`; «Pequeñas
Empresas»/«Peq. Empr.» → `pequenas_empresas`; «Microempresas»/«Microempr.» → `microempresas`;
«Consumo» → `consumo` (estos cuadros no separan revolvente / no revolvente); «Hipotecario(s)
para Vivienda»/«Hipot.» → `hipotecarios`.

Apertura: `tipo_credito|categoria` para `estructura_categoria_riesgo` (p. ej.
`consumo|cpp`); `tipo_credito` para `creditos_directos_indirectos` (p. ej. `consumo`).
Categorías: `normal`, `cpp`, `deficiente`, `dudoso`, `perdida` (0 a 4 de la SBS).

Unidades: `porcentaje` en puntos porcentuales (la SBS escribe 94.7 = 94,7 %; las 5 categorías
suman 100 por entidad y tipo; no aditivo entre entidades) y `miles_soles` para el monto
(aditivo: la suma de entidades cuadra con el total publicado).

Trampas
-------
- 2010-07 → 2010-09 (banca y financieras; extensión del 2026-10-28): una sola columna «Actividades
  Empresariales *» con los cinco tipos empresariales → tipo `empresariales`.
- «-» o vacío = sin saldo, no genera fila. En layout B una entidad sin cartera en el tipo
  trae las categorías vacías y el monto en 0 (se guarda el 0 del monto). Dentro de un tipo
  con cartera la SBS escribe 0 explícito en las categorías sin saldo: sí genera fila.
- Los códigos 0–4 son números, no texto: la cabecera se arma con `_texto`.
- EC 2016-04 y 2016-05 (C-4227, republicados «14.02.2017»): el total aún incluye a EDPYME
  Raíz (pasó a CRAC) aunque su columna ya no está → la suma de montos no cuadra con el total
  publicado (2016-04 en 6 tipos; 2016-05 solo `medianas_empresas`, 16.765 vs 17.461). Fuente.
- CMAC Piura `hipotecarios|perdida` 2023-08/09 viene negativo (−0.96 y −6.88); las 5
  categorías igual suman 100. Fuente, se guarda tal cual.
- Validado en todo el histórico: las 5 categorías suman 100 (±0,02) en las 41.890
  entidad-tipo-mes, y en layout B el % del total = promedio ponderado por monto salvo EC 2016-04/05.
- Cualquier fila/columna con cifras de entidades cuyo concepto no se reconozca lanza
  `ValueError` (layout nuevo visible en el control, no se pierde en silencio).
"""
from __future__ import annotations

import re
from pathlib import Path

from lector import comun

TIPOS = [
    (re.compile(r"^(creditos )?corporativos?\b|^corp\b"), "corporativos"),
    (re.compile(r"^(creditos (a )?)?grandes empresas\b|^grand\.? empr"), "grandes_empresas"),
    (re.compile(r"^(creditos (a )?)?medianas empresas\b|^med\.? empr"), "medianas_empresas"),
    (re.compile(r"^(creditos (a )?)?pequenas empresas\b|^peq\.? empr"), "pequenas_empresas"),
    (re.compile(r"^(creditos (a )?)?microempr"), "microempresas"),
    (re.compile(r"^(creditos (de )?)?consumo\b"), "consumo"),
    (re.compile(r"^(creditos )?hipot"), "hipotecarios"),
    # banca 2010-07 → 2010-09: los cinco tipos empresariales en una sola columna
    (re.compile(r"^actividades empresariales\b"), "empresariales"),
]
CATEGORIAS = [
    (re.compile(r"^(0|normal)$"), "normal"),
    (re.compile(r"^(1|cpp|con problemas potenciales)$"), "cpp"),
    (re.compile(r"^(2|deficiente)$"), "deficiente"),
    (re.compile(r"^(3|dudoso)$"), "dudoso"),
    (re.compile(r"^(4|perdida)$"), "perdida"),
]
MONTO_RE = re.compile(r"\(miles s/\.?\)$")


def _texto(v) -> str:
    """Texto normalizado de una celda de cabecera (los números, como texto: «0», «1»...)."""
    if isinstance(v, str):
        return comun.norm(v)
    if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v:
        return str(int(v)) if float(v).is_integer() else str(v)
    return ""


def _tipo(texto: str) -> str | None:
    for patron, tipo in TIPOS:
        if patron.search(texto):
            return tipo
    return None


def _categoria(texto: str) -> str | None:
    for patron, cat in CATEGORIAS:
        if patron.match(texto):
            return cat
    return None


def _es_subtotal_cmac(nombre) -> bool:
    """Subtotal de las CMAC sin la CMCP («Total Cajas Municipales de Ahorro y Crédito»)."""
    return "cajas municipales de ahorro" in comun.norm(nombre)


def _sin_subtotal(posiciones: list[int], nombre_en) -> list[int]:
    totales = [p for p in posiciones if comun.es_total(nombre_en(p))]
    if len(totales) > 1:
        return [p for p in posiciones if not (p in totales and _es_subtotal_cmac(nombre_en(p)))]
    return posiciones


def _hoja_filas(hoja: str, g, sub: str, col_ent: int, filas_ent: list[int]) -> list[dict]:
    """Layout A: entidades en filas; tipo (combinado) y código de categoría en la cabecera."""
    primera = min(filas_ent)
    tipo_col: dict[int, str] = {}
    cat_col: dict[int, str] = {}
    for i in range(primera):
        textos = {j: _texto(g.iat[i, j]) for j in range(col_ent + 1, g.shape[1])}
        if sum(1 for t in textos.values() if t and _tipo(t)) >= 2:   # fila de tipos: rellenar →
            actual = None
            for j in sorted(textos):
                if textos[j]:
                    actual = _tipo(textos[j])
                if actual:
                    tipo_col[j] = actual
        else:
            for j, t in textos.items():
                if t and _categoria(t):
                    cat_col[j] = _categoria(t)
    regs = []
    for j in range(col_ent + 1, g.shape[1]):
        con_cifras = any(comun.a_numero(g.iat[i, j]) is not None for i in filas_ent)
        if j not in tipo_col or j not in cat_col:
            if con_cifras:
                raise ValueError(f"hoja {hoja!r}: columna {j} sin tipo/categoría reconocidos")
            continue
        apertura = f"{tipo_col[j]}|{cat_col[j]}"
        for i in filas_ent:
            r = comun.registro(hoja, g.iat[i, col_ent], "estructura_categoria_riesgo", apertura,
                               g.iat[i, j], "porcentaje")
            if r:
                regs.append(r)
    return regs


def _hoja_columnas(hoja: str, g, sub: str, fila_ent: int, cols_ent: list[int]) -> list[dict]:
    """Layout B: entidades en columnas; tipo (col. 0, rellenado ↓) y categoría/monto en filas."""
    primera = min(cols_ent)
    regs = []
    tipo_actual = None
    for i in range(fila_ent + 1, g.shape[0]):
        etiquetas = [_texto(g.iat[i, j]) for j in range(primera)]
        etiquetas = [e for e in etiquetas if e]
        con_cifras = any(comun.a_numero(g.iat[i, j]) is not None for j in cols_ent)
        variable = apertura = unidad = None
        for e in etiquetas:
            t = _tipo(e)
            if t and not MONTO_RE.search(e):
                tipo_actual = t
        etiqueta = etiquetas[-1] if etiquetas else ""
        if MONTO_RE.search(etiqueta):
            t = _tipo(etiqueta)
            if t != tipo_actual:
                raise ValueError(f"hoja {hoja!r}: fila {i} monto {etiqueta!r} fuera de su bloque {tipo_actual}")
            variable, apertura, unidad = "creditos_directos_indirectos", t, "miles_soles"
        elif _categoria(etiqueta) and tipo_actual:
            variable, apertura, unidad = ("estructura_categoria_riesgo",
                                          f"{tipo_actual}|{_categoria(etiqueta)}", "porcentaje")
        if variable is None:
            if con_cifras:
                raise ValueError(f"hoja {hoja!r}: fila {i} sin concepto conocido: {etiquetas!r}")
            continue
        for j in cols_ent:
            r = comun.registro(hoja, g.iat[fila_ent, j], variable, apertura, g.iat[i, j], unidad)
            if r:
                regs.append(r)
    return regs


def _leer_hoja(hoja: str, g, sub: str) -> list[dict]:
    celdas = [(i, j) for i in range(g.shape[0]) for j in range(g.shape[1])
              if comun.es_entidad(g.iat[i, j], sub)]
    if len(celdas) < 2:
        return []
    por_col: dict[int, list[int]] = {}
    por_fila: dict[int, list[int]] = {}
    for i, j in celdas:
        por_col.setdefault(j, []).append(i)
        por_fila.setdefault(i, []).append(j)
    col_ent = max(por_col, key=lambda j: len(por_col[j]))
    fila_ent = max(por_fila, key=lambda i: len(por_fila[i]))
    if len(por_col[col_ent]) >= len(por_fila[fila_ent]):
        filas = _sin_subtotal(sorted(por_col[col_ent]), lambda i: g.iat[i, col_ent])
        return _hoja_filas(hoja, g, sub, col_ent, filas)
    cols = _sin_subtotal(sorted(por_fila[fila_ent]), lambda j: g.iat[fila_ent, j])
    return _hoja_columnas(hoja, g, sub, fila_ent, cols)


def leer(ruta: Path, subsistema: str, periodo: int) -> list[dict]:
    regs = []
    for nombre_hoja, g in comun.abrir(ruta).items():
        regs += _leer_hoja(nombre_hoja.strip(), g, subsistema)
    if not regs:
        raise ValueError("ninguna hoja con datos por entidad")
    return regs
