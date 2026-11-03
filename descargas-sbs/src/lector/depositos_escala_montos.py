"""Lector del cuadro «Depósitos según Escala de Montos» (Anexo 13 SBS).

Códigos: B-2321 (banca múltiple), B-3256 (empresas financieras), C-1211 (cajas municipales),
C-2211 (cajas rurales). Empresas de créditos no capta depósitos: no tiene este cuadro.

Qué publica
-----------
El cuadro NO trae datos por entidad: es el agregado del subsistema, abierto por tipo de depósito
(bloques de filas), tramo de monto (filas dentro de cada bloque) y tipo de depositante
(grupos de columnas), con dos medidas por depositante: «Número» y «Monto (en miles)».
Como no hay columna de entidad, cada registro se emite con `entidad_original` sintética
«Total <subsistema>» (p. ej. «Total Banca Múltiple»), que `comun.TOTAL_RE` reconoce como el
total del subsistema (`es_total = True`, sin `id_entidad`). Por eso el control
`_validacion.csv` de este tema siempre sale vacío (no hay entidades que sumar); la
consistencia interna (tramos → bloque, depositantes → TOTAL, tipos → «Depósitos Totales»)
se verificó aparte.

Eras de layout (2015-01 → 2026-08)
----------------------------------
Una sola hoja por libro, de nombre cambiante: «P004P», «P003P», «Financ.», «Financ.(P)»,
«P002P», «6», «CM», «CR». La estructura es la misma en todo el histórico, pero:
- la cabecera empieza en la fila 3 o 4 según el subsistema (banca/financieras traen
  «Cuadro N° 04» o una fila vacía arriba);
- banca y financieras tienen 5 bloques (Vista, Ahorro, Plazo, CTS, Totales); cajas municipales
  y rurales no tienen «Depósitos Vista» (4 bloques);
- banca y financieras tienen 14 tramos; cajas, 17 (tres tramos chicos adicionales);
- en financieras (algunos meses desde 2019) aparecen columnas intermedias sin cabecera
  rellenas de ceros (cols. 10, 12, 14...): se ignoran porque solo se leen columnas cuya
  cabecera es «Número» o «Monto»;
- unidad del monto: «(en miles)» o «(Miles de soles)» → miles_soles; los límites de tramo
  están «( En nuevos soles )» / «( En soles )».
Todo se ubica por etiqueta: fila de cabecera = la que tiene «Escala»; grupos de depositante por
etiqueta (con «forward fill» horizontal); bloques por la etiqueta «Depósitos ...»; tramos por
«Hasta» / «de ... a ...».

Variables (etiqueta SBS → variable, unidad)
-------------------------------------------
- «Número»               → `numero_depositantes` (numero). Es número de depositantes, no de
                            cuentas: en «Depósitos Totales» el número es MENOR que la suma de los
                            tipos (quien tiene ahorro y CTS cuenta una vez), mientras que el monto
                            sí suma exacto.
- «Monto (en miles)» / «Monto (Miles de soles)» → `depositos` (miles_soles).

Apertura: `tipo_deposito|tipo_depositante|tramo`
------------------------------------------------
- tipo_deposito: «Depósitos Vista» → `vista`, «Depósitos de Ahorro» → `ahorro`,
  «Depósitos a Plazo» → `plazo`, «Depósitos CTS» → `cts`, «Depósitos Totales» → `total`.
- tipo_depositante: «Personas Naturales» → `personas_naturales`; dentro de «Personas Jurídicas»:
  «Privadas sin fines de lucro» → `pj_sin_fines_lucro`, «Otras personas jurídicas» → `pj_otras`;
  «TOTAL» → `total`.
- tramo: los límites en soles se definen como múltiplos de la cobertura del Fondo de Seguro de
  Depósitos (FSD), que se actualiza cada trimestre (S/ 94 182 en 2015-01, S/ 122 000 en
  2026-08), así que los soles cambian de un trimestre a otro. Para que la apertura sea estable
  se normaliza a múltiplos de la cobertura: cobertura = límite inferior del último tramo
  («de X a más») / 100, y cada límite se divide por ella. Tokens: `hasta_0.1fsd`,
  `0.1fsd_a_0.25fsd`, ..., `100fsd_a_mas`; `total` para la fila del bloque (todos los tramos).
  Múltiplos posibles: 0.01, 0.03, 0.05 (solo cajas), 0.1, 0.25, 0.5, 1, 2, 4, 6, 8, 10, 15, 20,
  50, 100. Si un límite no es uno de esos múltiplos el lector falla (cambio de esquema a revisar).
  Para recuperar el tramo en soles: múltiplo × cobertura FSD del trimestre.

Trampas
-------
- Extensión 2010-07 (2026-10-28): financieras empieza en 2010-10; hasta ~2013 los tramos empiezan
  en «hasta 0,1 FSD» (aperturas `hasta_0.1fsd`, `0.1fsd_a_…`) y no en 0,01. Financieras 2011-08 y
  2012-07 traen la cabecera incompleta: se leen por posición con control de sumas
  (`_leer_hoja_por_posicion`).
- Los tramos de «Depósitos Totales» clasifican al depositante por su depósito total, no por
  cada tipo: por tramo, Totales ≠ Vista + Ahorro + Plazo + CTS (solo cuadra el monto en la fila
  `total` de tramos). Los tramos sí suman exacto al total de su bloque.
- Inconsistencia de origen: en financieras 2019-11 la columna TOTAL de «Número» es menor que
  la suma de los depositantes (p. ej. CTS: naturales 98 243, TOTAL 87 391). Se publica tal cual.
- Tramos vacíos (sin cifra) no generan registro; «0» sí.
- Títulos con «( )» o notas al pie largas al final de la hoja: no afectan (se ignoran filas que
  no son bloque ni tramo).
"""
from __future__ import annotations

import re
from pathlib import Path

from lector import comun

TOTAL_SUBSISTEMA = {
    "banca-multiple": "Total Banca Múltiple",
    "empresas-financieras": "Total Empresas Financieras",
    "cajas-municipales": "Total Cajas Municipales",
    "cajas-rurales": "Total Cajas Rurales",
}
TIPO_DEPOSITO = {
    "depositos vista": "vista",
    "depositos de ahorro": "ahorro",
    "depositos a plazo": "plazo",
    "depositos cts": "cts",
    "depositos totales": "total",
}
DEPOSITANTE = {
    "personas naturales": "personas_naturales",
    "privadas sin fines de lucro": "pj_sin_fines_lucro",
    "otras personas juridicas": "pj_otras",
    "total": "total",
}
MEDIDA = {"numero": ("numero_depositantes", "numero"), "monto": ("depositos", "miles_soles")}
MULTIPLOS = (0.01, 0.03, 0.05, 0.1, 0.25, 0.5, 1, 2, 4, 6, 8, 10, 15, 20, 50, 100)


def _fmt(m: float) -> str:
    return f"{m:g}fsd"


def _multiplo(limite: float, cobertura: float) -> float:
    x = limite / cobertura
    for m in MULTIPLOS:
        if abs(x - m) <= 1e-6 * max(1, m) + 1e-9:
            return m
    raise ValueError(f"límite de tramo {limite} no es múltiplo conocido de la cobertura {cobertura}")


def _celdas(g, i, hasta_col):
    return [g.iat[i, j] for j in range(hasta_col)]


def _leer_hoja(nombre_hoja, g, entidad):
    filas_txt = [[comun.norm(v) for v in g.iloc[i]] for i in range(len(g))]
    # Fila de cabecera: «Escala»
    h = next((i for i, f in enumerate(filas_txt) if "escala" in f), None)
    if h is None:
        return []
    # Fila de medidas (Número / Monto) debajo de la cabecera
    hm = next((i for i in range(h, min(h + 6, len(g))) if "numero" in filas_txt[i]), None)
    if hm is None or sum(filas_txt[hm][j] in MEDIDA for j in range(g.shape[1])) != 8:
        return _leer_hoja_por_posicion(nombre_hoja, g, entidad, filas_txt, h)
    # Forward-fill horizontal de los dos niveles de cabecera de depositante
    ncol = g.shape[1]
    top, sub, t, s = [], [], "", ""
    for j in range(ncol):
        if filas_txt[h][j]:
            t, s = filas_txt[h][j], ""
        if h + 1 < hm and filas_txt[h + 1][j]:
            s = filas_txt[h + 1][j]
        top.append(t)
        sub.append(s)
    columnas = {}  # j -> (variable, unidad, depositante)
    for j in range(ncol):
        med = filas_txt[hm][j]
        if med not in MEDIDA:
            continue
        etiqueta = sub[j] if top[j] == "personas juridicas" else top[j]
        if etiqueta not in DEPOSITANTE:
            raise ValueError(f"{nombre_hoja}: depositante desconocido {etiqueta!r} en col {j}")
        columnas[j] = (*MEDIDA[med], DEPOSITANTE[etiqueta])
    if len(columnas) != 8:
        raise ValueError(f"{nombre_hoja}: se esperaban 8 columnas Número/Monto, hay {len(columnas)}")
    # El monto debe venir en miles
    unidad_txt = " ".join(filas_txt[i][j] for i in range(hm, min(hm + 2, len(g)))
                          for j in columnas if columnas[j][0] == "depositos")
    if "miles" not in unidad_txt:
        raise ValueError(f"{nombre_hoja}: no se encontró la unidad «miles» del monto")
    return _bloques(nombre_hoja, g, entidad, filas_txt, hm, columnas)


ORDEN_POSICION = [("numero", "personas_naturales"), ("monto", "personas_naturales"),
                  ("numero", "pj_sin_fines_lucro"), ("monto", "pj_sin_fines_lucro"),
                  ("numero", "pj_otras"), ("monto", "pj_otras"), ("numero", "total"), ("monto", "total")]


def _leer_hoja_por_posicion(nombre_hoja, g, entidad, filas_txt, h):
    """Cabecera incompleta (financieras 2011-08 sin «Personas Naturales»/«Número»; 2012-07 sin la
    fila Número/Monto): las 8 columnas con cifras en la fila del primer bloque se asignan en el
    orden fijo del cuadro (naturales, sin fines de lucro, otras jurídicas, total × número, monto)
    y se acepta solo si, en todas las filas, número y monto del total = suma de los tres tipos.
    """
    i0 = next((i for i in range(h + 1, len(g)) if filas_txt[i][0].startswith("depositos")), None)
    if i0 is None:
        raise ValueError(f"{nombre_hoja}: sin fila de medidas ni bloques de depósitos")
    cols = [j for j in range(1, g.shape[1]) if comun.a_numero(g.iat[i0, j]) is not None]
    if len(cols) != 8:
        raise ValueError(f"{nombre_hoja}: cabecera incompleta y {len(cols)} columnas con cifras (se esperaban 8)")
    columnas = {j: (*MEDIDA[m], dep) for j, (m, dep) in zip(cols, ORDEN_POSICION)}
    for i in range(i0, len(g)):
        v = [comun.a_numero(g.iat[i, j]) or 0 for j in cols]
        if any(comun.a_numero(g.iat[i, j]) is not None for j in cols):
            for k in (0, 1):  # número y monto
                if abs(v[k] + v[k + 2] + v[k + 4] - v[k + 6]) > 0.01 * max(1, abs(v[k + 6])):
                    raise ValueError(f"{nombre_hoja}: cabecera incompleta y el orden fijo no cuadra (fila {i})")
    return _bloques(nombre_hoja, g, entidad, filas_txt, h, columnas)


def _bloques(nombre_hoja, g, entidad, filas_txt, hm, columnas):
    primera = min(columnas)

    # Recorre bloques y tramos
    crudos = []  # (tipo, (lo, hi) | None, fila)
    tipo = None
    for i in range(hm + 1, len(g)):
        etiquetas = [x for x in filas_txt[i][:primera] if x]
        if not etiquetas:
            continue
        cab = etiquetas[0]
        if cab.startswith("depositos"):
            if cab not in TIPO_DEPOSITO:
                raise ValueError(f"{nombre_hoja}: bloque desconocido {cab!r}")
            tipo = TIPO_DEPOSITO[cab]
            crudos.append((tipo, None, i))
            continue
        if cab not in ("hasta", "de") or tipo is None:
            continue  # notas, fuente
        nums = [comun.a_numero(v) for v in _celdas(g, i, primera)]
        nums = [x for x in nums if x is not None]
        if cab == "hasta":
            lo, hi = 0.0, nums[0]
        elif "mas" in etiquetas:
            lo, hi = nums[0], None
        else:
            lo, hi = nums[0], nums[1]
        crudos.append((tipo, (lo, hi), i))
    if not crudos:
        raise ValueError(f"{nombre_hoja}: sin bloques de depósitos")
    ultimos = [r[1][0] for r in crudos if r[1] and r[1][1] is None]
    cobertura = max(ultimos) / 100
    salida = []
    for tipo, tramo, i in crudos:
        if tramo is None:
            tok = "total"
        else:
            lo, hi = tramo
            if hi is None:
                tok = f"{_fmt(_multiplo(lo, cobertura))}_a_mas"
            elif lo == 0:
                tok = f"hasta_{_fmt(_multiplo(hi, cobertura))}"
            else:
                tok = f"{_fmt(_multiplo(lo, cobertura))}_a_{_fmt(_multiplo(hi, cobertura))}"
        for j, (var, unidad, dep) in columnas.items():
            salida.append(comun.registro(nombre_hoja, entidad, var, f"{tipo}|{dep}|{tok}",
                                         g.iat[i, j], unidad))
    return salida


def leer(ruta: Path, subsistema: str, periodo: int) -> list[dict]:
    entidad = TOTAL_SUBSISTEMA[subsistema]
    salida = []
    for nombre_hoja, g in comun.abrir(ruta).items():
        salida += _leer_hoja(nombre_hoja, g, entidad)
    return salida
