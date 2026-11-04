"""Lector del tema `estatales-fideicomisos` (E-5202, p=12, entidades estatales).

Cuadro «Fideicomisos y Comisiones de Confianza por Entidad Estatal» (en miles de soles; «miles
de nuevos soles» hasta 2015-10; fuente: Balance de Comprobación). Mensual, 2010-07 → 2026-09
(195 archivos revisados uno por uno el 2026-11-03).

Qué publica
-----------
Entidades en FILAS (columna rotulada «Empresas»: «Nación», «Cofide», «Agrobanco»; el Fondo
MiVivienda no aparece nunca) y conceptos en COLUMNAS, con dos filas de cabecera: la segunda solo
tiene los sub-rótulos del grupo «Ingresos» / «Ingresos de la entidad». Sin fila de total: el
cuadro no trae total del subsistema (y `comun.validar_totales` no tiene nada que comparar).

Formatos por época (las columnas se ubican siempre por rótulo, nunca por posición)
------------------------------------------------------------------------------
- 2010-07 → 2015-01: hoja «Hoja1» (más «Hoja2»/«Hoja3» vacías) hasta 2011-08, «Estat» desde
  2011-09; tabla desde la col. 1 (col. 0 vacía). Columnas: Activos de Fideicomisos, Pasivos de
  Fideicomisos, Comisiones de Confianza, Ingresos (Fideicomisos | Comisiones de confianza).
- 2015-02 → 2016-12 y 2017-02: mismas 5 columnas, tabla desde la col. 0; hoja «Estat», «7N»
  (2015-10) u «11» (desde 2015-11).
- 2017-01 y 2017-03 → 2026-09: hoja «11», 8 columnas: Activos, Gastos, Pasivos, Ingresos y
  Patrimonio de Fideicomisos, Comisiones de Confianza, Ingresos de la entidad (Por Fideicomisos |
  Por Comisiones de confianza). 2017-02 vuelve al formato de 5 columnas (así viene en el archivo).

Variables (todas en `miles_soles`; apertura vacía salvo `ingresos_entidad`)
-------------------------------------------------------------------------
  Activos de Fideicomisos         → activos_fideicomisos
  Gastos de Fideicomisos          → gastos_fideicomisos        (2017-01 y 2017-03 →)
  Pasivos de Fideicomisos         → pasivos_fideicomisos
  Ingresos de Fideicomisos        → ingresos_fideicomisos      (2017-01 y 2017-03 →)
  Patrimonio de Fideicomisos      → patrimonio_fideicomisos    (2017-01 y 2017-03 →)
  Comisiones de Confianza         → comisiones_confianza       (recursos administrados en
                                                                comisiones de confianza)
  Ingresos | Ingresos de la entidad → ingresos_entidad, apertura (un nivel, orden fijo):
      fideicomisos          («Fideicomisos» / «Por Fideicomisos»)
      comisiones_confianza  («Comisiones de confianza» / «Por Comisiones de confianza»)
  `ingresos_fideicomisos` son los ingresos de los patrimonios fideicometidos; `ingresos_entidad`
  son los ingresos que la entidad (fiduciaria / comisionista) registra por esos servicios. El
  grupo «Ingresos» de 2010-2016 es el mismo concepto que «Ingresos de la entidad» (misma escala:
  COFIDE ~16 mil en 2016-06 frente a ~25 mil en 2019-12, no los ~670 mil de los fideicomisos).

Saldos y flujos
---------------
Activos, pasivos, patrimonio y comisiones de confianza son saldos a fin de mes. Los ingresos y
gastos son ACUMULADOS en el año: `ingresos_entidad` vuelve a empezar cada enero (COFIDE 2019-12:
25 211; 2020-01: 2 547). `ingresos_fideicomisos` / `gastos_fideicomisos` de COFIDE NO siempre se
reinician en enero (2020-01: 600 296 frente a 670 455 en 2019-12 y 69 930 en 2020-02; en 2021 y
2026 tampoco en febrero): cada patrimonio fideicometido tiene su propio cierre. No calcular flujos
mensuales por diferencia sin revisar esos meses.

Trampas
-------
- «-» (2010-2015, 2017-09) y 0 (resto) marcan lo mismo: la entidad no tiene ese concepto
  (Agrobanco no tiene fideicomisos, solo comisiones de confianza). «-» no genera registro; 0 sí.
- La unidad sobre la cabecera debe ser «(En miles de [nuevos] soles)»; si no, ValueError.
- La fecha de la celda bajo el título debe ser la del nombre del archivo (las 195 coinciden); si
  no, ValueError (sería un archivo de otro mes).
- Un rótulo de columna desconocido, un sub-rótulo fuera del grupo de ingresos, una columna sin
  rótulo con cifras, una fila con cifras y sin nombre, dos hojas con el cuadro o un libro sin
  ningún dato levantan ValueError. El cuadro termina en la nota al pie («NOTA:» / «Fuente:»).

Control (`validar_totales`)
---------------------------
Sin total publicado, el control es la identidad contable del patrimonio fideicometido, por
entidad y mes: activos_fideicomisos = pasivos_fideicomisos + patrimonio_fideicomisos (solo los
meses con las tres cifras, 2017-01 y 2017-03 →). Se listan solo las violaciones.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import pandas as pd

from lector import comun

UNIDAD = "miles_soles"
# Rótulo de la primera fila de cabecera (normalizado) → variable, para columnas sin sub-rótulo.
COLUMNAS = {
    "activos de fideicomisos": "activos_fideicomisos",
    "gastos de fideicomisos": "gastos_fideicomisos",
    "pasivos de fideicomisos": "pasivos_fideicomisos",
    "ingresos de fideicomisos": "ingresos_fideicomisos",
    "patrimonio de fideicomisos": "patrimonio_fideicomisos",
    "comisiones de confianza": "comisiones_confianza",
}
# Grupo con sub-rótulos en la segunda fila de cabecera.
GRUPO_INGRESOS = {"ingresos", "ingresos de la entidad"}
VARIABLE_INGRESOS = "ingresos_entidad"
SUB_INGRESOS = {
    "fideicomisos": "fideicomisos",
    "por fideicomisos": "fideicomisos",
    "comisiones de confianza": "comisiones_confianza",
    "por comisiones de confianza": "comisiones_confianza",
}
NOTA_RE = re.compile(r"^\s*(nota|fuente|\*|\(\*\)|http|\d+\s*/)", re.IGNORECASE)
UNIDAD_RE = re.compile(r"^\(?en miles de (nuevos )?soles\)?$")


def leer(ruta: Path, subsistema: str, periodo: int) -> list[dict]:
    """Registros de E-5202 de un mes; ValueError si el libro no trae el cuadro."""
    out: list[dict] = []
    hojas_con_cuadro = []
    for hoja, df in comun.abrir(ruta).items():
        regs = _leer_hoja(str(hoja).strip(), df, periodo)
        if regs is not None:
            hojas_con_cuadro.append(str(hoja).strip())
            out += regs
    if len(hojas_con_cuadro) > 1:
        raise ValueError(f"el cuadro aparece en varias hojas: {hojas_con_cuadro}")
    if not out:
        raise ValueError("no se encontró ninguna cifra del cuadro de fideicomisos")
    return out


def _cabecera(df: pd.DataFrame) -> tuple[int, int] | None:
    """(fila, columna) de la celda «Empresas» en las primeras filas; None si no está."""
    nr, nc = df.shape
    for i in range(min(nr, 20)):
        for j in range(nc):
            if comun.norm(df.iat[i, j]) == "empresas":
                return i, j
    return None


def _fecha(df: pd.DataFrame, h: int) -> dt.datetime | None:
    """Fecha de corte: la celda de fecha que está sobre la cabecera."""
    for i in range(h):
        for v in df.iloc[i]:
            if isinstance(v, (dt.datetime, pd.Timestamp)):
                return v
    return None


def _columnas(hoja: str, df: pd.DataFrame, h: int, je: int) -> dict[int, tuple[str, str]]:
    """Columna → (variable, apertura), leyendo las dos filas de cabecera por rótulo."""
    nr, nc = df.shape
    cols: dict[int, tuple[str, str]] = {}
    grupo = False  # dentro del grupo «Ingresos» (sus sub-columnas no repiten el rótulo de arriba)
    for j in range(je + 1, nc):
        arriba = comun.norm(df.iat[h, j])
        abajo = comun.norm(df.iat[h + 1, j]) if h + 1 < nr else ""
        if arriba in COLUMNAS:
            if abajo:
                raise ValueError(f"hoja {hoja!r}: sub-rótulo {abajo!r} bajo {arriba!r}")
            cols[j] = (COLUMNAS[arriba], "")
            grupo = False
        elif arriba in GRUPO_INGRESOS or (not arriba and grupo):
            grupo = True
            if abajo not in SUB_INGRESOS:
                raise ValueError(f"hoja {hoja!r} col {j}: sub-rótulo de ingresos desconocido {abajo!r}")
            cols[j] = (VARIABLE_INGRESOS, SUB_INGRESOS[abajo])
        elif not arriba and not abajo:
            # Columna sin rótulo: solo se admite vacía.
            if any(comun.a_numero(df.iat[i, j]) is not None for i in range(h + 2, nr)):
                raise ValueError(f"hoja {hoja!r} col {j}: columna sin rótulo con cifras")
        else:
            raise ValueError(f"hoja {hoja!r} col {j}: columna desconocida "
                             f"{comun.limpiar(df.iat[h, j]) or comun.limpiar(df.iat[h + 1, j])!r}")
    claves = list(cols.values())
    repetidas = {c for c in claves if claves.count(c) > 1}
    if repetidas:
        raise ValueError(f"hoja {hoja!r}: columnas repetidas {sorted(repetidas)}")
    if not cols:
        raise ValueError(f"hoja {hoja!r}: cabecera sin columnas de datos")
    return cols


def _leer_hoja(hoja: str, df: pd.DataFrame, periodo: int) -> list[dict] | None:
    """Registros de la hoja; None si la hoja no tiene el cuadro (hojas vacías)."""
    if df.empty:
        return None
    pos = _cabecera(df)
    if pos is None:
        if any(comun.a_numero(v) is not None for v in df.to_numpy().ravel()):
            raise ValueError(f"hoja {hoja!r}: tiene cifras pero no se encontró la cabecera «Empresas»")
        return None
    h, je = pos
    fecha = _fecha(df, h)
    if fecha is None:
        raise ValueError(f"hoja {hoja!r}: sin fecha de corte sobre la cabecera")
    if fecha.year * 100 + fecha.month != periodo:
        raise ValueError(f"hoja {hoja!r}: la fecha del cuadro ({fecha:%Y-%m}) no es la del archivo ({periodo})")
    if not any(UNIDAD_RE.match(comun.norm(v)) for i in range(h) for v in df.iloc[i]):
        raise ValueError(f"hoja {hoja!r}: no dice «(En miles de soles)» sobre la cabecera")
    cols = _columnas(hoja, df, h, je)

    nr, nc = df.shape
    out: list[dict] = []
    for i in range(h + 2, nr):
        nombre = df.iat[i, je]
        if isinstance(nombre, str) and NOTA_RE.match(nombre):
            break
        cifras = [j for j in cols if comun.a_numero(df.iat[i, j]) is not None]
        if not cifras:
            continue
        if not comun.norm(nombre):
            raise ValueError(f"hoja {hoja!r} fila {i}: cifras sin nombre de entidad")
        for j in cifras:
            variable, apertura = cols[j]
            r = comun.registro(hoja, nombre, variable, apertura, df.iat[i, j], UNIDAD)
            if r:
                out.append(r)
    return out


def validar_totales(df: pd.DataFrame, tolerancia: float = 0.005) -> pd.DataFrame:
    """Control interno: activos = pasivos + patrimonio de los fideicomisos, por entidad y mes.

    Columnas como las de `comun.validar_totales` + `entidad_original` y `regla`; `suma_entidades`
    es aquí pasivos + patrimonio y `total` los activos publicados. Solo violaciones (diferencia
    relativa mayor que la tolerancia). Se agrega además la validación estándar (vacía: el cuadro
    no trae total del subsistema).
    """
    claves = ["periodo", "subsistema", "codigo", "hoja", "variable", "apertura", "unidad"]
    cols = claves + ["entidad_original", "suma_entidades", "total", "dif_rel", "regla"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    a = comun.validar_totales(df, tolerancia).assign(entidad_original="", regla="suma_entidades!=total")
    por_ent = ["periodo", "subsistema", "codigo", "hoja", "entidad_original"]
    x = df[df["variable"].isin(["activos_fideicomisos", "pasivos_fideicomisos", "patrimonio_fideicomisos"])]
    w = x.pivot_table(index=por_ent, columns="variable", values="valor", aggfunc="sum").dropna()
    if w.empty:
        return a.reindex(columns=cols)
    b = w.reset_index()
    b["suma_entidades"] = b["pasivos_fideicomisos"] + b["patrimonio_fideicomisos"]
    b["total"] = b["activos_fideicomisos"]
    b["dif_rel"] = (b["suma_entidades"] - b["total"]).abs() / b["total"].abs().clip(lower=1)
    b = b[b["dif_rel"] > tolerancia].assign(variable="activos_fideicomisos", apertura="", unidad=UNIDAD,
                                           regla="pasivos+patrimonio!=activos")
    return pd.concat([a, b], ignore_index=True)[cols].sort_values(["regla", "dif_rel"], ascending=[True, False])
