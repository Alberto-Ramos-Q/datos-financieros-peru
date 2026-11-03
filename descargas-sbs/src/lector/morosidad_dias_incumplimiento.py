"""Lector de «Ratios de Morosidad según días de incumplimiento» (tema `morosidad-dias-incumplimiento`).

Códigos: B-220512 (banca), B-3230 (financieras), C-1230 (CMAC), C-2230 (CRAC), C-4225 (EC).

Eras de layout (revisados los 700 archivos 2015-01 → 2026-08)
-------------------------------------------------------------
Una sola era en los 5 subsistemas: una hoja, entidades en filas (columna «Empresas»), cabecera
de dos filas: «Porcentaje de créditos con» (combinada sobre 4 columnas) / «Más de N días de
incumplimiento» y una quinta columna «Morosidad según criterio contable SBS». Solo cambian:
- el nombre de la hoja: banca `Ratio Morosidad` (2015-01) → `P012P` (2015-07) → `17`
  (2015-10+); financieras `P008P` → `16` → `Boletin Public` (2015-04) → `P008P` → `16`;
  cajas `CM`, `CR`, `EDP`;
- la fila de cabecera (fila 3/4 en cajas, 5/6 en banca y financieras) → se ubica con
  `comun.es_entidad`;
- las marcas de nota («*», «**» en banca; «1/», «2/» en el resto), que `comun.norm` quita;
- notas al pie que entran y salen («+ Banco GNB remitió…», «…más de 15 días calendario de
  atraso» en 2020: está debajo de las entidades y no se toma como cabecera).

Variables (etiqueta SBS normalizada → variable, apertura)
--------------------------------------------------------
- «Porcentaje de créditos con | Más de 30 días de incumplimiento»  → `ratio_morosidad_dias_incumplimiento`, `mas_30_dias`
- «… Más de 60 días de incumplimiento»                             → `ratio_morosidad_dias_incumplimiento`, `mas_60_dias`
- «… Más de 90 días de incumplimiento*» (estándar Basilea II)      → `ratio_morosidad_dias_incumplimiento`, `mas_90_dias`
- «… Más de 120 días de incumplimiento»                            → `ratio_morosidad_dias_incumplimiento`, `mas_120_dias`
- «Morosidad según criterio contable SBS**» (créditos atrasados /
  créditos directos)                                               → `ratio_morosidad`, `` (vacía)

Apertura: un token, el tramo de días de incumplimiento (`mas_30_dias`, `mas_60_dias`,
`mas_90_dias`, `mas_120_dias`); vacía para `ratio_morosidad`.

Unidades: todo en `porcentaje`, puntos porcentuales (la SBS ya escribe 3.31 = 3,31 %; nada en
fracción). No aditivo entre entidades: el orquestador no lo valida contra el total; los
tramos son acumulados y deben decrecer (30 ≥ 60 ≥ 90 ≥ 120).

Trampas
-------
- CMAC (todo el periodo): fila «TOTAL CAJAS MUNICIPALES DE AHORRO Y CRÉDITO» (subtotal de las
  CMAC sin la CMCP Lima) entre las CMAC y la CMCP; se omite y queda solo «TOTAL CAJAS
  MUNICIPALES» (total del subsistema). Ojo: ese subtotal no se puede reconstruir desde este
  cuadro (no trae saldos para ponderar las CMAC).
- Entidades sin cartera (Citibank 2026, Bank of China, BCI) vienen con «-»: no generan fila.
- `ratio_morosidad` viene redondeado a 2 decimales en banca y financieras (2.72), con
  decimales completos en cajas y EC. Coincide (mediana de diferencia 0) con `total|total` de
  `morosidad-tipo-credito-modalidad`, salvo CRAC 2021-12, cuyo cuadro C-2247 trae cifras
  incoherentes (ver ese módulo).
- Fuente con errores propios: BBVA 2022-02 publica más de 30 días (2.61) < más de 60 (3.87);
  se guarda tal cual.
- Una columna con cifras bajo las entidades y cabecera desconocida lanza `ValueError`.
"""
from __future__ import annotations

import re
from pathlib import Path

from lector import comun

DIAS_RE = re.compile(r"mas de (\d+) dias de incumplimiento")
CONTABLE_RE = re.compile(r"morosidad segun criterio contable")


def _concepto(cabecera: str) -> tuple[str, str] | None:
    m = DIAS_RE.search(cabecera)
    if m:
        return "ratio_morosidad_dias_incumplimiento", f"mas_{m.group(1)}_dias"
    if CONTABLE_RE.search(cabecera):
        return "ratio_morosidad", ""
    return None


def _es_subtotal_cmac(nombre) -> bool:
    """Subtotal de las CMAC sin la CMCP («Total Cajas Municipales de Ahorro y Crédito»)."""
    return "cajas municipales de ahorro" in comun.norm(nombre)


def _leer_hoja(hoja: str, g, subsistema: str) -> list[dict]:
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
    # CMAC: fila «TOTAL CAJAS MUNICIPALES DE AHORRO Y CRÉDITO» (subtotal sin la CMCP Lima) además
    # de «TOTAL CAJAS MUNICIPALES»: se omite el subtotal para no tener dos totales.
    totales = [i for i in filas_ent if comun.es_total(g.iat[i, col_ent])]
    if len(totales) > 1:
        filas_ent = [i for i in filas_ent if not (i in totales and _es_subtotal_cmac(g.iat[i, col_ent]))]
    primera = min(filas_ent)
    regs = []
    for j in range(col_ent + 1, g.shape[1]):
        # Cabecera de la columna: solo las celdas propias (no se rellena la combinada
        # «Porcentaje de créditos con», no hace falta para distinguir los conceptos).
        cabecera = " ".join(comun.norm(g.iat[i, j]) for i in range(primera) if comun.norm(g.iat[i, j]))
        concepto = _concepto(cabecera)
        if concepto is None:
            if any(comun.a_numero(g.iat[i, j]) is not None for i in filas_ent):
                raise ValueError(f"hoja {hoja!r}: columna {j} sin concepto conocido: {cabecera!r}")
            continue
        variable, apertura = concepto
        for i in filas_ent:
            r = comun.registro(hoja, g.iat[i, col_ent], variable, apertura, g.iat[i, j], "porcentaje")
            if r:
                regs.append(r)
    return regs


def leer(ruta: Path, subsistema: str, periodo: int) -> list[dict]:
    regs = []
    for nombre_hoja, g in comun.abrir(ruta).items():
        regs += _leer_hoja(nombre_hoja.strip(), g, subsistema)
    if not regs:
        raise ValueError("ninguna hoja con datos por entidad")
    return regs
