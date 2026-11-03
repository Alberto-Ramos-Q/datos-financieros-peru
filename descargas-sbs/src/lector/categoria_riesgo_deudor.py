"""Lector de «Estructura de Créditos Directos e Indirectos (y Contingentes) según Categoría de
Riesgo del Deudor» (tema `categoria-riesgo-deudor`).

Códigos: B-2309 (banca), B-3205 (financieras), C-120201 (CMAC), C-220201 (CRAC), C-4201 (EC).

Eras de layout (revisados los 700 archivos 2015-01 → 2026-08)
-------------------------------------------------------------
Una sola era en los 5 subsistemas: un libro con **una hoja**, entidades en filas (columna
«Empresas»), una columna por categoría y una columna con el monto total. Cambian solo:
- el nombre de la hoja: banca `Estruct_Public` (2015-01/02) → `P019P` (2015-03) → `P008P`
  (2015-07) → `13` (desde 2015-10); financieras `Estruct_Public` → `P006P` → `12`; cajas `CM`,
  `CR`, `EDP` siempre;
- la columna de las etiquetas (columna 1 en banca 2015-01/02, columna 0 después) y la fila de la
  cabecera (fila 5 o 6) → se ubican con `comun.es_entidad`, nunca por índice;
- la etiqueta del monto: «nuevos soles» → «soles» (2016-04 cajas, 2020-01 banca/financieras),
  «Directos e Indirectos» (banca, financieras) / «Directos y Contingentes» (cajas, EC);
- notas al pie que entran y salen («Banco Ripley remitió…», «Chequeo de totales» en EC
  2021-06 → 2022-02, una fila de control con ceros bajo las notas: no es entidad y se ignora).

Variables (etiqueta SBS normalizada → variable, apertura)
--------------------------------------------------------
- «Normal (0)»                            → `estructura_categoria_riesgo`, `normal`
- «Con Problemas Potenciales (1)» / «CPP» → `estructura_categoria_riesgo`, `cpp`
- «Deficiente (2)»                        → `estructura_categoria_riesgo`, `deficiente`
- «Dudoso (3)»                            → `estructura_categoria_riesgo`, `dudoso`
- «Pérdida (4)»                           → `estructura_categoria_riesgo`, `perdida`
- «Total Créditos Directos e Indirectos 1/ (En miles de [nuevos] soles)» y
  «Total Créditos Directos y Contingentes (en miles de [nuevos] soles)»
                                          → `creditos_directos_indirectos`, `` (vacía)

Apertura: un solo token, la categoría de riesgo del deudor (`normal|cpp|deficiente|dudoso|perdida`
como valores posibles, no concatenados); vacía para el monto.

Unidades: `estructura_categoria_riesgo` en `porcentaje` (puntos porcentuales, la SBS ya los
escribe como 94.0 = 94 %; las 5 categorías suman 100 por entidad; **no aditivo** entre
entidades). `creditos_directos_indirectos` en `miles_soles` (aditivo: la suma de entidades cuadra
con el total publicado). «Indirectos» = «contingentes»: créditos indirectos al equivalente
de riesgo crediticio (factores de conversión crediticia, Res. SBS 11356-2008).

Trampas
-------
- Las celdas «-» (sin saldo en esa categoría) no generan fila; en cambio un 0 explícito sí.
- Entidades sin cartera (p. ej. Deutsche Bank Perú 2015) vienen con «-» en todas las columnas.
- El total del subsistema («TOTAL BANCA MÚLTIPLE», «TOTAL EDPYMES», «TOTAL CAJAS RURALES…»)
  se emite como una entidad más; el orquestador lo marca `es_total`.
- Si en algún libro aparece el subtotal «Total Cajas Municipales de Ahorro y Crédito» junto al
  total del subsistema, se omite (ver `_es_subtotal_cmac`).
- EC 2016-04 (C-4201-ab2016, republicado «14.02.2017»): EDPYME Raíz ya no aparece (pasó a
  CRAC, figura en C-220201 desde 2016-05) pero el «TOTAL EDPYMES» aún la incluye: suma de
  entidades 1.341.673 vs total 1.871.015 (dif. ≈ cartera de Raíz, 523.779 en 2016-03); el % del
  total tampoco es el promedio ponderado de las filas. Es la fuente: queda en
  `_control/categoria-riesgo-deudor_validacion.csv` como única diferencia.
- Validado en todo el histórico: las 5 categorías suman 100 (±1e-6) en las 7.953
  entidad-mes, y el % del total publicado = promedio de las entidades ponderado por el monto
  (dif. < 0,05 pp) en todos los meses salvo EC 2016-04.
- Cualquier columna con cifras bajo las entidades cuya cabecera no se reconozca lanza
  `ValueError`: así un layout nuevo aparece en el control en vez de perderse en silencio.
"""
from __future__ import annotations

import re
from pathlib import Path

from lector import comun

CATEGORIAS = [
    (re.compile(r"^normal\b"), "normal"),
    (re.compile(r"^(con problemas potenciales|cpp)\b"), "cpp"),
    (re.compile(r"^deficiente\b"), "deficiente"),
    (re.compile(r"^dudoso\b"), "dudoso"),
    (re.compile(r"^perdida\b"), "perdida"),
]
MONTO_RE = re.compile(r"^total creditos directos (e indirectos|y contingentes)")


def _es_subtotal_cmac(nombre) -> bool:
    """Subtotal de las CMAC sin la CMCP («Total Cajas Municipales de Ahorro y Crédito»)."""
    return "cajas municipales de ahorro" in comun.norm(nombre)


def _texto(v) -> str:
    """Texto normalizado de una celda de cabecera (los números, como texto: «0», «1»...)."""
    if isinstance(v, str):
        return comun.norm(v)
    if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v:
        return str(int(v)) if float(v).is_integer() else str(v)
    return ""


def _concepto(cabecera: str) -> tuple[str, str, str] | None:
    """(variable, apertura, unidad) de una columna según su cabecera normalizada."""
    if MONTO_RE.match(cabecera):
        return "creditos_directos_indirectos", "", "miles_soles"
    for patron, categoria in CATEGORIAS:
        if patron.match(cabecera):
            return "estructura_categoria_riesgo", categoria, "porcentaje"
    return None


DESDE_CEROS = 202606   # formato con «-» por cero; antes, la historia queda como se leyó al estimar el modelo


def _leer_hoja(nombre_hoja: str, g, subsistema: str, ceros: bool = False) -> list[dict]:
    # Columna de las entidades: la que tiene más nombres reconocidos.
    hits = {}
    for j in range(g.shape[1]):
        filas = [i for i in range(g.shape[0]) if comun.es_entidad(g.iat[i, j], subsistema)]
        if filas:
            hits[j] = filas
    if not hits:
        return []
    col_ent = max(hits, key=lambda j: len(hits[j]))
    filas_ent = hits[col_ent]
    if len(filas_ent) < 2:
        return []
    # Subtotal CMAC: se omite solo si hay además otro total.
    totales = [i for i in filas_ent if comun.es_total(g.iat[i, col_ent])]
    if len(totales) > 1:
        filas_ent = [i for i in filas_ent if not (i in totales and _es_subtotal_cmac(g.iat[i, col_ent]))]
    primera = min(filas_ent)

    regs = []
    cat_cols = {}   # columna → categoría, para los ceros escritos «-» (abajo)
    for j in range(col_ent + 1, g.shape[1]):
        cabecera = " ".join(t for t in (_texto(g.iat[i, j]) for i in range(primera)) if t)
        concepto = _concepto(cabecera)
        con_cifras = any(comun.a_numero(g.iat[i, j]) is not None for i in filas_ent)
        if concepto is None:
            if con_cifras:
                raise ValueError(f"hoja {nombre_hoja!r}: columna {j} sin concepto conocido: {cabecera!r}")
            continue
        variable, apertura, unidad = concepto
        if variable == "estructura_categoria_riesgo":
            cat_cols[j] = apertura
        for i in filas_ent:
            r = comun.registro(nombre_hoja, g.iat[i, col_ent], variable, apertura, g.iat[i, j], unidad)
            if r:
                regs.append(r)
    # Desde 2026-06 (DESDE_CEROS) la SBS escribe «-» en las categorías vacías de una entidad (p. ej. Banco BCI Perú: normal 98,80
    # + CPP 1,20 = 100; deficiente, dudoso y pérdida «-»). Si las categorías con cifra ya suman 100, las «-» son 0.
    for i in (filas_ent if ceros else []):
        vals = {c: comun.a_numero(g.iat[i, j]) for j, c in cat_cols.items()}
        con = [v for v in vals.values() if v is not None]
        if con and len(con) < len(vals) and abs(sum(con) - 100) <= 0.01:
            for j, c in cat_cols.items():
                if vals[c] is None and isinstance(g.iat[i, j], str) and g.iat[i, j].strip() == "-":
                    regs.append(comun.registro(nombre_hoja, g.iat[i, col_ent], "estructura_categoria_riesgo", c, 0.0,
                                               "porcentaje"))
    return regs


def leer(ruta: Path, subsistema: str, periodo: int) -> list[dict]:
    regs = []
    for nombre_hoja, g in comun.abrir(ruta).items():
        regs += _leer_hoja(nombre_hoja.strip(), g, subsistema, ceros=periodo >= DESDE_CEROS)
    if not regs:
        raise ValueError("ninguna hoja con datos por entidad")
    return regs
