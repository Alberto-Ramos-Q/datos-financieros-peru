"""Lector del tema `indicadores-financieros` (B-2401, B-3301, C-1301, C-2301, C-4301).

Cuadro «Indicadores Financieros por Empresa …»: indicadores en FILAS (etiqueta a la izquierda),
entidades en COLUMNAS. Un solo cuadro por libro (pero se recorren todas las hojas).

Eras de layout (revisadas sobre los 700 archivos 2015-01 → 2026-08)
-------------------------------------------------------------------
- Banca (B-2401): hoja «IND (P)» hasta 2015-10, «3» desde 2015-09. Cabecera de entidades en la
  fila 5; en 2015-01/02 la mitad de los nombres está en la fila 6 (cabecera en dos filas) y bajo
  «B. GNB» aparece «HSBC Bank Perú» como subtítulo → por columna se toma la PRIMERA celda (de
  arriba abajo) que sea entidad. En 2020-06 hay una «Hoja1» vacía (se ignora: no tiene cabecera).
  Las etiquetas aparecen repetidas en la columna 9 (segundo panel) en 2015.
- Financieras (B-3301): hoja «Ind-Fin Public» hasta 2015-10, «3» después. Desde 2019-12 trae
  una fila suelta al pie con nombres de entidades y sin cifras (se ignora: solo cuenta la
  primera fila de cabecera).
- CMAC / CRAC (C-1301 / C-2301): hoja «Indic-CM» / «Indic-CR»; cabecera en la fila 4 o 3.
  CMAC trae DOS totales: «Total CMAC» (sin la CMCP Lima) y «Total CM» (todo el subsistema).
- Empresas de créditos (C-4301): hoja «Indic-Edpyme»; DOS PANELES lado a lado: etiquetas en la
  col. 0 (entidades 1-5) y repetidas en la col. 9 (entidades 10-…, y el total). Por eso la
  etiqueta de cada celda es la cadena más cercana a su izquierda que no esté en una columna de
  entidad. Hay ceros sueltos sin etiqueta y, bajo las notas al pie, bloques de chequeo 0/1
  (2018-12 →; con la etiqueta suelta «Cartera Atrasada M.E. / …» en 2018-12 y 2019-02): el
  cuadro termina en la primera fila de notas («Nota:», «Fuente», «*», «http»).
- Las filas cambian de posición entre meses y subsistemas (se agregan «con más de 90 días» en
  2015-05, «Cartera atrasada/alto riesgo ajustada» en 2026-01, etc.): todo se ubica por etiqueta.

Variables (etiqueta SBS normalizada → variable [apertura] unidad)
----------------------------------------------------------------
La etiqueta se normaliza con `_canon` (minúsculas, sin tildes, sin paréntesis —«(criterio
SBS)», «(%)», «(al 31/07/2026)», «( N° de veces )»—, sin notas «*», sin «neta»/«anualizado»,
«sobre» → «/», «M.N.» → «mn»).

  ratio de capital global                         → ratio_capital_global                    %
  pasivo total / capital social y reservas        → pasivo_total_capital_social_reservas    veces
  creditos atrasados / creditos directos          → morosidad_creditos_atrasados [total]    %
  creditos atrasados mn / creditos directos mn    → morosidad_creditos_atrasados [mn]       %
  creditos atrasados me / creditos directos me    → morosidad_creditos_atrasados [me]       %
  creditos atrasados con mas de 90 dias de atraso / creditos directos
                                                  → morosidad_atrasados_90_dias             %
  creditos refinanciados y reestructurados / creditos directos
                                                  → ratio_refinanciados_reestructurados     %
  provisiones / creditos atrasados                → provisiones_creditos_atrasados          %
  cartera de alto riesgo / creditos directos      → morosidad_cartera_alto_riesgo           %
  cartera atrasada ajustada                       → cartera_atrasada_ajustada               %
  cartera de alto riesgo ajustada                 → cartera_alto_riesgo_ajustada            %
  gastos de administracion / activo productivo promedio
                                                  → gastos_administracion_activo_productivo %
  gastos de administracion / creditos directos e indirectos promedio
                                                  → gastos_administracion_creditos          %
  gastos de operacion / margen financiero total   → gastos_operacion_margen_financiero      %
  ingresos financieros / ingresos totales         → ingresos_financieros_ingresos_totales   %
  ingresos financieros / activo productivo promedio
                                                  → ingresos_financieros_activo_productivo  %
  creditos directos / personal | / empleados      → creditos_directos_por_empleado     miles_soles_por_unidad
  creditos directos / numero de oficinas          → creditos_directos_por_oficina      miles_soles_por_unidad
  depositos / numero de oficinas                  → depositos_por_oficina              miles_soles_por_unidad
  depositos / creditos directos                   → depositos_creditos_directos             %
  utilidad / patrimonio promedio                  → roe                                     %
  utilidad / activo promedio                      → roa                                     %
  ratio de liquidez [en] mn | me                  → ratio_liquidez [mn|me]                  %
  caja y bancos [en] mn|me / obligaciones a la vista mn|me
                                                  → caja_bancos_obligaciones_vista [mn|me]  veces
  adeudos / pasivo total                          → adeudos_pasivo_total                    %
  disponible / activo total                       → disponible_activo_total                 %
  posicion global en me / patrimonio efectivo     → posicion_global_me_patrimonio_efectivo  %
  posicion global promedio / patrimonio efectivo (banca hasta 2017-10)
                                                  → posicion_global_promedio_patrimonio_efectivo %

Apertura: solo moneda (`mn`, `me`, `total`) y solo en los indicadores que la SBS publica por
moneda (morosidad, liquidez, caja y bancos); vacía en el resto.

Unidades: los porcentajes ya vienen en puntos (2.72 = 2,72 %; comprobado: ninguna celda viene
como fracción con formato %). «Veces» y miles de soles tal como se publican.

Trampas
-------
- 2010-07 → 2012-12 (extensión del 2026-10-28): rótulos del manual anterior, mismo indicador:
  «Cartera Atrasada (MN/ME) / Créditos Directos (MN/ME)» → `morosidad_creditos_atrasados`,
  «Provisiones / Cartera Atrasada» → `provisiones_creditos_atrasados`, «… / Activo Rentable
  Promedio» → `…_activo_productivo`, «Posición Global / Patrimonio Efectivo (Promedio de saldos del
  mes)» → `posicion_global_promedio_patrimonio_efectivo`. Financieras 2010: errata «Ingresos
  FinancierosAnualizados» (se separa «anualizados»). CMAC, CRAC y EC publican
  `posicion_global_me_patrimonio_efectivo` en todo 2010-2014 (sustituto del cuadro de posición
  global antes de 2014-07, ver `consolidar.py`); financieras no publica posición global aquí.
- `ratio_capital_global` viene con rezago cuando la etiqueta dice «(al …)»: siempre en banca y
  financieras («al 31/07/2026» en el archivo de 2026-08), y en CMAC/CRAC/EC en 2025-06 y desde
  2026-03 (antes la etiqueta no trae fecha); se guarda en el periodo del archivo, sin mover.
- `creditos_directos_por_empleado`, `creditos_directos_por_oficina` y `depositos_por_oficina`
  están en miles de soles pero son ratios (no aditivos): unidad `miles_soles_por_unidad`.
- Cifras sin cabecera de entidad que se ignoran: col. 63 de banca 2015-01/02 (ceros), col. 9 de
  CRAC 2016-02 → 2016-05 (3 celdas de un panel viejo), col. 2 de CRAC 2026-03 y EC 2026-05
  (copia de la col. 1 en las filas de cartera ajustada).
- «Créditos atrasados / créditos directos» de 2015-01/02 no dice «(criterio SBS)»; desde
  2015-03 sí. Se tratan como la misma variable (mismo indicador publicado).
- Banca/financieras: «Utilidad Neta Anualizada» vs «Utilidad Anualizada» → ambos `roe`/`roa`.
- Total del subsistema: si hay varios (CMAC: «Total CMAC» y «Total CM») se deja solo el último,
  que abarca todo el subsistema; los subtotales se descartan (si no, `es_total` tendría dos
  filas por grupo).
- «TOTAL Servicios Financieros» (EC, 2023 →) es una ENTIDAD (EDPYME Servicios Financieros
  Total), no un total: `comun.es_total` no la confunde.
- Una etiqueta desconocida con cifras levanta ValueError (queda en el control de archivos):
  así un indicador nuevo de la SBS no se pierde en silencio.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import pandas as pd

from lector import comun

# etiqueta canónica → (variable, apertura, unidad)
INDICADORES: dict[str, tuple[str, str, str]] = {
    "ratio de capital global": ("ratio_capital_global", "", "porcentaje"),
    "pasivo total / capital social y reservas": ("pasivo_total_capital_social_reservas", "", "veces"),
    "creditos atrasados / creditos directos": ("morosidad_creditos_atrasados", "total", "porcentaje"),
    "creditos atrasados mn / creditos directos mn": ("morosidad_creditos_atrasados", "mn", "porcentaje"),
    "creditos atrasados me / creditos directos me": ("morosidad_creditos_atrasados", "me", "porcentaje"),
    "creditos atrasados con mas de 90 dias de atraso / creditos directos":
        ("morosidad_atrasados_90_dias", "", "porcentaje"),
    "creditos refinanciados y reestructurados / creditos directos":
        ("ratio_refinanciados_reestructurados", "", "porcentaje"),
    "provisiones / creditos atrasados": ("provisiones_creditos_atrasados", "", "porcentaje"),
    "cartera de alto riesgo / creditos directos": ("morosidad_cartera_alto_riesgo", "", "porcentaje"),
    "cartera atrasada ajustada": ("cartera_atrasada_ajustada", "", "porcentaje"),
    "cartera de alto riesgo ajustada": ("cartera_alto_riesgo_ajustada", "", "porcentaje"),
    "gastos de administracion / activo productivo promedio":
        ("gastos_administracion_activo_productivo", "", "porcentaje"),
    "gastos de administracion / creditos directos e indirectos promedio":
        ("gastos_administracion_creditos", "", "porcentaje"),
    "gastos de operacion / margen financiero total":
        ("gastos_operacion_margen_financiero", "", "porcentaje"),
    "ingresos financieros / ingresos totales": ("ingresos_financieros_ingresos_totales", "", "porcentaje"),
    "ingresos financieros / activo productivo promedio":
        ("ingresos_financieros_activo_productivo", "", "porcentaje"),
    "creditos directos / personal": ("creditos_directos_por_empleado", "", "miles_soles_por_unidad"),
    "creditos directos / empleados": ("creditos_directos_por_empleado", "", "miles_soles_por_unidad"),
    "creditos directos / numero de oficinas": ("creditos_directos_por_oficina", "", "miles_soles_por_unidad"),
    "depositos / numero de oficinas": ("depositos_por_oficina", "", "miles_soles_por_unidad"),
    "depositos / creditos directos": ("depositos_creditos_directos", "", "porcentaje"),
    "utilidad / patrimonio promedio": ("roe", "", "porcentaje"),
    "utilidad / activo promedio": ("roa", "", "porcentaje"),
    "ratio de liquidez mn": ("ratio_liquidez", "mn", "porcentaje"),
    "ratio de liquidez me": ("ratio_liquidez", "me", "porcentaje"),
    "caja y bancos mn / obligaciones a la vista mn": ("caja_bancos_obligaciones_vista", "mn", "veces"),
    "caja y bancos me / obligaciones a la vista me": ("caja_bancos_obligaciones_vista", "me", "veces"),
    "adeudos / pasivo total": ("adeudos_pasivo_total", "", "porcentaje"),
    "disponible / activo total": ("disponible_activo_total", "", "porcentaje"),
    "posicion global me / patrimonio efectivo": ("posicion_global_me_patrimonio_efectivo", "", "porcentaje"),
    "posicion global promedio / patrimonio efectivo":
        ("posicion_global_promedio_patrimonio_efectivo", "", "porcentaje"),
    # Rótulos de 2010-07 → 2012-12 (antes del Manual de Contabilidad de 2013): mismo indicador.
    "cartera atrasada / creditos directos": ("morosidad_creditos_atrasados", "total", "porcentaje"),
    "cartera atrasada mn / creditos directos mn": ("morosidad_creditos_atrasados", "mn", "porcentaje"),
    "cartera atrasada me / creditos directos me": ("morosidad_creditos_atrasados", "me", "porcentaje"),
    "provisiones / cartera atrasada": ("provisiones_creditos_atrasados", "", "porcentaje"),
    "gastos de administracion / activo rentable promedio":
        ("gastos_administracion_activo_productivo", "", "porcentaje"),
    "ingresos financieros / activo rentable promedio":
        ("ingresos_financieros_activo_productivo", "", "porcentaje"),
    # «Posición Global / Patrimonio Efectivo (Promedio de saldos del mes)»: el promedio del mes.
    "posicion global / patrimonio efectivo":
        ("posicion_global_promedio_patrimonio_efectivo", "", "porcentaje"),
}


# Primera fila de notas al pie: fin del cuadro.
NOTA_RE = re.compile(r"^\s*(nota|fuente|\*|\(\*\)|http)", re.IGNORECASE)


def _canon(texto) -> str:
    """Etiqueta comparable entre subsistemas y años (ver docstring del módulo)."""
    n = comun.norm(texto)
    n = re.sub(r"\([^)]*\)", " ", n)           # «(criterio sbs)», «(%)», «(al 31/07/2026)»
    n = re.sub(r"\(.*$", " ", n)               # paréntesis sin cerrar
    n = re.sub(r"\bm\.\s?n\.?", "mn", n)
    n = re.sub(r"\bm\.\s?e\.?", "me", n)
    n = re.sub(r"(?<=[a-z])(anualizad[oa]s?)\b", r" \1", n)  # errata «FinancierosAnualizados» (fin. 2010)
    n = re.sub(r"\b(neta|neto|anualizad[oa]s?)\b", " ", n)
    n = n.replace(" sobre ", " / ")
    n = re.sub(r"\b(en|de) (mn|me)\b", r"\2", n)  # «ratio de liquidez en mn», «caja y bancos en me»
    n = re.sub(r"\s*/\s*", " / ", n)
    return re.sub(r"\s+", " ", n).strip(" .:%")


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
    # Fila de cabecera: la primera (de arriba) con al menos dos entidades.
    h0 = next((i for i in range(min(nr, 20))
               if sum(_entidad(df.iat[i, j], subsistema) for j in range(nc)) >= 2), None)
    if h0 is None:
        if any(comun.a_numero(v) is not None for v in df.to_numpy().ravel()):
            raise ValueError(f"hoja {hoja!r}: tiene cifras pero no se encontró la cabecera de entidades")
        return []
    # Primera fila de datos: la primera, bajo la cabecera, cuya etiqueta es un indicador conocido.
    f_dato = next((i for i in range(h0 + 1, nr)
                   if any(_canon(df.iat[i, j]) in INDICADORES for j in range(nc))), nr)
    cab = range(h0, min(f_dato, h0 + 3))
    # Columna → nombre de entidad: la primera celda (de arriba) de la cabecera que es entidad.
    ent: dict[int, str] = {}
    for j in range(nc):
        for i in cab:
            if _entidad(df.iat[i, j], subsistema):
                ent[j] = df.iat[i, j]
                break
    # Varios totales (CMAC: «Total CMAC» y «Total CM»): se queda el último, el del subsistema.
    totales = [j for j, n in ent.items() if comun.es_total(n)]
    for j in totales[:-1]:
        del ent[j]
    col_ent = set(ent)
    no_etiqueta = set(totales) | col_ent

    # Fin del cuadro: la primera fila de notas al pie. Debajo, la SBS deja a veces bloques de
    # chequeo (0/1) y etiquetas sueltas («Cartera Atrasada M.E.» en EC 2018-12/2019-02).
    f_fin = next((i for i in range(f_dato, nr)
                  if any(isinstance(df.iat[i, j], str) and NOTA_RE.match(df.iat[i, j])
                         for j in range(nc) if j not in col_ent)), nr)

    out: list[dict] = []
    vistos: set[tuple] = set()
    for i in range(f_dato, f_fin):
        for j, nombre in ent.items():
            v = df.iat[i, j]
            if comun.a_numero(v) is None:
                continue
            k = j - 1
            while k >= 0 and (k in no_etiqueta or not isinstance(df.iat[i, k], str)
                              or not df.iat[i, k].strip()):
                k -= 1
            if k < 0:
                continue  # cifra suelta sin etiqueta (ceros de trabajo en EC)
            etq = _canon(df.iat[i, k])
            if etq not in INDICADORES:
                raise ValueError(f"hoja {hoja!r} fila {i}: etiqueta desconocida {df.iat[i, k]!r}")
            variable, apertura, unidad = INDICADORES[etq]
            clave = (nombre, variable, apertura)
            if clave in vistos:
                raise ValueError(f"hoja {hoja!r}: {clave} aparece dos veces")
            vistos.add(clave)
            r = comun.registro(hoja, nombre, variable, apertura, v, unidad)
            if r:
                out.append(r)
    return out
