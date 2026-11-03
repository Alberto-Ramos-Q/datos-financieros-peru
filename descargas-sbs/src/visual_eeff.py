"""Genera `outputs/eeff_ssff.html`: tablero público de la composición del balance general y del estado de
resultados de las empresas del sistema financiero.

Lee una tabla larga de `data/processed/boletin/` (correr antes `leer_boletin.py`):
- `estados-financieros`: balance general y estado de ganancias y pérdidas por entidad y mes (B-2201 banca,
  B-3101 financieras, C-1101 cajas municipales, C-2101 cajas rurales, C-4103 empresas de créditos), en
  miles de S/, con apertura MN / ME / total (la ME ya viene en soles, al tipo de cambio contable). Las
  partidas del estado de resultados son ACUMULADAS de enero al mes.

Árbol de cuentas (`NODES`): las líneas del cuadro de la SBS en su orden, con su padre. Verificado en los
datos (2010-07 → 2026-08, apertura total, todas las filas entidad-mes): cada padre es la suma de sus hijos
(diferencia <= 1 miles o 0,05 %) en el 100 % de las filas, y la cadena del estado de resultados cuadra en
el 100 %:
- margen financiero bruto = ingresos financieros − gastos financieros;
- margen financiero neto = bruto − provisiones para créditos directos;
- margen operacional = neto + ingresos − gastos por servicios financieros + resultado por venta de cartera
  (línea propia desde 2015-08; antes no existe). La diferencia de cambio y la valorización de inversiones
  NO van aparte: son subcuentas de los ingresos y de los gastos financieros;
- margen operacional neto = margen operacional − gastos administrativos;
- resultado antes de impuesto = margen operacional neto − provisiones, depreciación y amortización + otros
  ingresos y gastos;
- resultado neto = resultado antes de impuesto − impuesto a la renta. Hasta 2012-12 el subtotal es «antes
  de participaciones e impuesto» y la participación de los trabajadores se resta aparte (en cero en
  2011-2012 salvo tres entidades en 2011-01; desde 2011 va en gastos de personal, Res. SBS 2740-2011).
  Las dos versiones del subtotal se unen en un solo nodo (`resultado_antes_impuesto_renta`): ocupan el
  mismo lugar de la cascada y cumplen la misma identidad en su periodo; solo cambia el rótulo (`l0`).
- activo = pasivo + patrimonio en el 100 % de las filas; el resultado del ejercicio del patrimonio es igual
  al del estado de resultados salvo CMAC Piura 2016-01 → 2016-04 (hasta 141 miles; error de origen).
Signos: en el balance todos los hijos SUMAN (las provisiones y los intereses no devengados vienen
negativos). En el estado de resultados los gastos, provisiones e impuesto vienen POSITIVOS y restan en la
cascada (`sg` = −1); otros ingresos y gastos y venta de cartera vienen con su signo (`sg` = +1).

Cambios de plan de cuentas (Manual anterior hasta 2012-12; ver el lector): las líneas que solo existen en
un periodo son nodos propios con su vigencia (`from` / `to`), sin forzar equivalencias: capital adicional
y ajustes (juntos hasta 2012; separados desde 2013), resultados no realizados (hasta 2012), provisiones por
créditos contingentes (pasivo, hasta 2012) frente a «Provisiones» del pasivo (créditos indirectos y otras,
desde 2013), reajuste por indexación (hasta 2012), provisiones para contingencias y otras (hasta 2012)
frente a créditos indirectos, bienes realizables y otras provisiones (desde 2013), la apertura de otros
ingresos y gastos (hasta 2012), inversiones en commodities (desde 2013). Quedan FUERA del árbol las
contingentes deudoras (= acreedoras) y las cuentas de orden, que el cuadro trae solo hasta 2012.

Ámbitos:
- Entidades: filas sin `es_total`, columna local (la del BCP sin sus sucursales en el exterior, que es la
  que suma el total del cuadro; las columnas «con sucursales en el exterior» se descartan). Se quitan las
  filas con activo cero (entidades absorbidas que la SBS sigue mostrando, p. ej. CRAC Del Centro 2026) y
  las que repiten el mes anterior en todas las partidas antes de 2015-01 (CMAC Pisco 2014-01 → 2014-04;
  mismo criterio que `visual_rentabilidad.drop_repeated`). Cada entidad tiene UNA serie con toda su
  historia (aunque cambie de subsistema) y la lista de tramos en que perteneció a cada subsistema (`m`):
  sus flujos de 12 meses no se cortan con el traspaso, igual que en el tablero de rentabilidad.
- Subsistemas y sistema: suma de las entidades presentes cada mes (controlada contra el total del cuadro).
  El sistema suma todas las entidades (no los subsistemas).
- Dentro de su vigencia, una línea que la entidad no reporta es cero (el cuadro no trae la fila: p. ej.
  comercio exterior en las cajas); fuera de su vigencia o en un mes sin estado, vacía.

Estado de resultados:
- `V` trae el ACUMULADO publicado (enero → mes). La página calcula el flujo de 12 meses con la regla de
  las notas de indicadores de la SBS: acumulado del mes + acumulado de diciembre del año anterior −
  acumulado del mismo mes del año anterior (en diciembre, el del año); vacío si falta alguno.
- Agregados: para el flujo de 12 meses, una entidad que SALE del agregado durante el año conserva su
  último acumulado hasta diciembre (regla con la que se reproduce el ROE publicado; ver
  `visual_rentabilidad.scope_series`). Ese acumulado «con arrastre» es V + `D` (`D` disperso: solo los
  meses donde difiere). El acumulado publicado (V) no lleva arrastre: es la suma de las presentes.
- Activo promedio de 12 meses (para el estado de resultados en % del activo): promedio de los 12 saldos de
  fin de mes t−11 … t del total activo; vacío si falta alguno. Lo calcula la página.
- Control: el flujo de 12 meses del resultado neto calculado así es idéntico al del tablero de rentabilidad
  en todos los ámbitos y meses (10.897 ámbito-mes) con los acumulados sin redondear; con los acumulados
  enteros del JSON (los que usa la página) difiere a lo sumo en 1 miles por redondeo (`check_profit`).

Controles contra el cuadro (`check_totals`): la suma de las entidades es el total del cuadro en todas las
celdas mes-subsistema-línea, salvo CMAC 2014-01 → 2014-04 en el balance: ese total incluye las cifras
repetidas de CMAC Pisco (del 31.12.2013) que aquí se omiten (el total del estado de resultados no las
incluye). MN + ME = total en el 100 % de las filas.

Tipo de cambio constante y rendimientos (v2, 2026-10-29): la página valúa la ME del mes al tipo de cambio de
hace 12 meses (saldo − ME × (1 − TC(t−12)/TC(t))) y descompone el crecimiento anual del activo y del pasivo y
patrimonio en contribuciones de sus rubros más un efecto del tipo de cambio; y calcula rendimientos y costos
implícitos por partida y moneda (flujo de 12 meses / promedio de 12 saldos). El tipo de cambio es el contable de
la nota de cada cuadro B-2201 (difiere del interbancario de fin de mes del BCRP en menos de S/ 0.02).

Trampas para leer los datos:
- En enero el resultado del ejercicio del patrimonio vuelve a empezar y el del año anterior pasa a
  resultados acumulados (hasta que la junta lo capitaliza, lo reparte o lo lleva a reservas).
- 2013-01 (Manual de Contabilidad modificado): los intereses y comisiones no devengados de los créditos
  caen de −2,99 a −0,21 mil millones en el sistema y los créditos vigentes de arrendamiento financiero
  bajan 2,6 mil millones (se netean en la propia línea); los créditos netos no se mueven. El salto del
  activo de banca ese mes (+8,2 mil millones) es del negocio (disponible, depósitos a plazo, adeudos).
- La diferencia de cambio del estado de resultados viene casi toda como ingreso (gasto 0,2 mil millones
  frente a 2,8 en el sistema en 2025-12): es un resultado neto de cambio, no un ingreso por intereses.
- Líneas que solo existen en algunos subsistemas o desde cierto año en un subsistema (cuentas corrientes y
  comercio exterior: banca y financieras; tarjetas de crédito: CRAC desde 2019-03, CMAC desde 2022-09; las
  empresas de créditos no tienen depósitos del público ni del sistema financiero; obligaciones
  subordinadas: CRAC y EC desde 2021-12): fuera de esos tramos son cero.

Datos de la página: el marcador `/*__DATA__*/null` de la plantilla se reemplaza por un literal de texto con
el JSON comprimido (gzip, en base64; `encode`), que la página descomprime al cargar con
`DecompressionStream("gzip")`. Comprimido la página queda en ~5 MB; el JSON plano pasa de 9 MB (unas 160
líneas × 78 series de entidad × 194 meses). Esquema del JSON, cifras enteras en miles de S/:
- `months`: ["2010-07", …]; `hasta`, `generado`.
- `nodes`: [{k, l, l0?, p, e, lv, sg, sub?, from?, to?}] en el orden del cuadro. `p`: índice del padre
  (−1 si no tiene); `e`: "A" activo, "P" pasivo, "K" patrimonio, "T" total pasivo y patrimonio,
  "C" contingentes, "R" estado de resultados; `lv`: nivel (0 totales y rubros del EGP, 1 rubros, 2-3
  detalle); `sg`: signo con que el nodo entra a su padre o a la cascada; `sub`: 1 si es subtotal de la
  cascada; `from`/`to`: vigencia "AAAA-MM" si no cubre todo el periodo; `l0`: rótulo hasta 2012-12.
- `fx`: índices de los nodos con apertura en moneda extranjera (`X`, en el mismo orden): todo el balance y
  las líneas del estado de resultados de los rendimientos y costos implícitos (`YIELD_FLOWS`). MN = total − ME.
- `tc`: tipo de cambio contable de fin de mes (soles por dólar), uno por mes (`load_fx_rates`).
- `groups`: {"A" | "P": [{l, short, m, ks}]} rubros del resumen, de la comparación y de la contribución al
  crecimiento (los mismos con los que `check_growth` controla que las contribuciones sumen el total).
- `subs`: [{k, l, s}] los cinco subsistemas.
- `scopes`: {"sistema" | subsistema: {n, a, V, X, D}}: `a` índice del primer mes; `V[i]`: serie del nodo i
  desde `a` (null si es cero en todo el rango: la página lo lee como 0 en los meses con ese estado y dentro
  de la vigencia del nodo); `X[j]`: ME del nodo `fx[j]`; `D`: {"i": [[mes desde `a`, dif], …]}, arrastre
  de las salidas para los flujos de 12 meses del nodo i del EGP; `DX`: lo mismo para la ME de esos nodos.
- `ents`: {id: {n: {subsistema: nombre}, a, V, X, m: [[subsistema, desde, hasta], …]}}: índices de mes
  absolutos en `m`; meses sin dato de la entidad, null en todas sus series.
- `entities`: ["subsistema/id", …] para los selectores (como en rentabilidad).

Genera además `outputs/eeff_ssff_artifact.html`, la versión para publicar como Artifact de claude.ai
(sin <html>/<head>/<body>), si existe la plantilla `src/plantillas/eeff.html`.

Uso:
    python visual_eeff.py [--json RUTA]   (--json escribe además el JSON suelto)
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import gzip
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from visual_mora import (ENTIDADES, PROJECT_DIR, SUBSYSTEMS, artifact_version, month_key, month_range,
                         read_table)

BOLETIN = PROJECT_DIR / "data" / "processed" / "boletin"
TEMPLATE = PROJECT_DIR / "src" / "plantillas" / "eeff.html"
OUT = PROJECT_DIR / "outputs" / "eeff_ssff.html"
OUT_ARTIFACT = PROJECT_DIR / "outputs" / "eeff_ssff_artifact.html"
RENTABILIDAD_OUT = PROJECT_DIR / "outputs" / "rentabilidad_ssff.html"
PLACEHOLDER = "/*__DATA__*/null"
# Textos de las pestañas «Cuentas» y «Cómo leer»: archivos editables, auditados aparte, que se incrustan tal cual.
# Tipo de cambio contable de la SBS (nota «Tipo de Cambio Contable: S/ x,xxx» de cada cuadro B-2201): se lee
# de los Excel originales (solo lectura) y se guarda en processed; solo se vuelven a leer los meses nuevos.
RAW_B2201 = PROJECT_DIR / "data" / "raw" / "boletin" / "banca-multiple" / "estados-financieros"
TC_CACHE = PROJECT_DIR / "data" / "processed" / "tc_contable.csv"
MONTH_ABBR = ["en", "fe", "ma", "ab", "my", "jn", "jl", "ag", "se", "oc", "no", "di"]
GLOSARIO = PROJECT_DIR / "config" / "eeff_glosario.json"
CAMBIOS = PROJECT_DIR / "config" / "eeff_cambios.json"
TEXT_PLACEHOLDER = "/*__TEXTOS__*/null"

# (variable, rótulo, rótulo hasta 2012-12 o None, padre, estado, signo en el padre o la cascada, subtotal)
# en el orden del cuadro. Rótulos del cuadro de la SBS (los subrubros, sin repetir el rubro).
NODES = [
    # Activo
    ("disponible", "Disponible", None, "total_activo", "A", 1, 0),
    ("disponible_caja", "Caja", None, "disponible", "A", 1, 0),
    ("disponible_bancos_corresponsales", "Bancos y corresponsales", None, "disponible", "A", 1, 0),
    ("disponible_canje", "Canje", None, "disponible", "A", 1, 0),
    ("disponible_otros", "Otros", None, "disponible", "A", 1, 0),
    ("fondos_interbancarios_activo", "Fondos interbancarios", None, "total_activo", "A", 1, 0),
    ("inversiones_netas", "Inversiones netas de provisiones",
     "Inversiones netas de provisiones e ingresos no devengados", "total_activo", "A", 1, 0),
    ("inversiones_valor_razonable_resultados", "A valor razonable con cambios en resultados", None, "inversiones_netas", "A", 1, 0),
    ("inversiones_disponibles_venta", "Disponibles para la venta", "Negociables disponibles para la venta", "inversiones_netas", "A", 1, 0),
    ("inversiones_vencimiento", "A vencimiento", "Financieras a vencimiento", "inversiones_netas", "A", 1, 0),
    ("inversiones_subsidiarias", "En subsidiarias, asociadas y negocios conjuntos", "En subsidiarias y asociadas", "inversiones_netas", "A", 1, 0),
    ("inversiones_commodities", "En commodities", None, "inversiones_netas", "A", 1, 0),
    ("inversiones_provisiones", "Provisiones", None, "inversiones_netas", "A", 1, 0),
    ("creditos_netos", "Créditos netos de provisiones y de ingresos no devengados",
     "Créditos netos de provisiones e ingresos no devengados", "total_activo", "A", 1, 0),
    ("creditos_vigentes", "Vigentes", None, "creditos_netos", "A", 1, 0),
    ("creditos_vigentes_cuentas_corrientes", "Cuentas corrientes", None, "creditos_vigentes", "A", 1, 0),
    ("creditos_vigentes_tarjetas_credito", "Tarjetas de crédito", None, "creditos_vigentes", "A", 1, 0),
    ("creditos_vigentes_descuentos", "Descuentos", None, "creditos_vigentes", "A", 1, 0),
    ("creditos_vigentes_factoring", "Factoring", None, "creditos_vigentes", "A", 1, 0),
    ("creditos_vigentes_prestamos", "Préstamos", None, "creditos_vigentes", "A", 1, 0),
    ("creditos_vigentes_arrendamiento_financiero", "Arrendamiento financiero", None, "creditos_vigentes", "A", 1, 0),
    ("creditos_vigentes_hipotecarios_vivienda", "Hipotecarios para vivienda", None, "creditos_vigentes", "A", 1, 0),
    ("creditos_vigentes_comercio_exterior", "Comercio exterior", None, "creditos_vigentes", "A", 1, 0),
    ("creditos_vigentes_por_liquidar", "Créditos por liquidar", None, "creditos_vigentes", "A", 1, 0),
    ("creditos_vigentes_otros", "Otros", None, "creditos_vigentes", "A", 1, 0),
    ("creditos_refinanciados_reestructurados", "Refinanciados y reestructurados", None, "creditos_netos", "A", 1, 0),
    ("creditos_atrasados", "Atrasados", None, "creditos_netos", "A", 1, 0),
    ("creditos_atrasados_vencidos", "Vencidos", None, "creditos_atrasados", "A", 1, 0),
    ("creditos_atrasados_cobranza_judicial", "En cobranza judicial", None, "creditos_atrasados", "A", 1, 0),
    ("creditos_provisiones", "Provisiones", None, "creditos_netos", "A", 1, 0),
    ("creditos_intereses_no_devengados", "Intereses y comisiones no devengados", None, "creditos_netos", "A", 1, 0),
    ("cuentas_por_cobrar_netas", "Cuentas por cobrar netas de provisiones", None, "total_activo", "A", 1, 0),
    ("rendimientos_por_cobrar", "Rendimientos por cobrar", "Rendimientos devengados por cobrar", "total_activo", "A", 1, 0),
    ("rendimientos_por_cobrar_disponible", "Disponible", None, "rendimientos_por_cobrar", "A", 1, 0),
    ("rendimientos_por_cobrar_fondos_interbancarios", "Fondos interbancarios", None, "rendimientos_por_cobrar", "A", 1, 0),
    ("rendimientos_por_cobrar_inversiones", "Inversiones", None, "rendimientos_por_cobrar", "A", 1, 0),
    ("rendimientos_por_cobrar_creditos", "Créditos", None, "rendimientos_por_cobrar", "A", 1, 0),
    ("rendimientos_por_cobrar_cuentas_por_cobrar", "Cuentas por cobrar", None, "rendimientos_por_cobrar", "A", 1, 0),
    ("bienes_realizables_netos", "Bienes realizables, recibidos en pago y adjudicados netos",
     "Bienes realizables, recibidos en pago, adjudicados y fuera de uso netos", "total_activo", "A", 1, 0),
    ("inmuebles_mobiliario_equipo_neto", "Inmuebles, mobiliario y equipo neto", None, "total_activo", "A", 1, 0),
    ("otros_activos", "Otros activos", "Otros activos neto", "total_activo", "A", 1, 0),
    ("total_activo", "Total activo", None, None, "A", 1, 0),
    # Pasivo
    ("obligaciones_publico", "Obligaciones con el público", None, "total_pasivo", "P", 1, 0),
    ("obligaciones_publico_depositos_vista", "Depósitos a la vista", None, "obligaciones_publico", "P", 1, 0),
    ("obligaciones_publico_depositos_ahorro", "Depósitos de ahorro", None, "obligaciones_publico", "P", 1, 0),
    ("obligaciones_publico_depositos_plazo", "Depósitos a plazo", None, "obligaciones_publico", "P", 1, 0),
    ("obligaciones_publico_depositos_plazo_certificados", "Certificados bancarios y de depósitos", None,
     "obligaciones_publico_depositos_plazo", "P", 1, 0),
    ("obligaciones_publico_depositos_plazo_cuentas_plazo", "Cuentas a plazo", None, "obligaciones_publico_depositos_plazo", "P", 1, 0),
    ("obligaciones_publico_depositos_plazo_cts", "C.T.S.", None, "obligaciones_publico_depositos_plazo", "P", 1, 0),
    ("obligaciones_publico_depositos_plazo_otros", "Otros", None, "obligaciones_publico_depositos_plazo", "P", 1, 0),
    ("obligaciones_publico_depositos_restringidos", "Depósitos restringidos", None, "obligaciones_publico", "P", 1, 0),
    ("obligaciones_publico_otras_obligaciones", "Otras obligaciones", None, "obligaciones_publico", "P", 1, 0),
    ("obligaciones_publico_otras_obligaciones_vista", "A la vista", None, "obligaciones_publico_otras_obligaciones", "P", 1, 0),
    ("obligaciones_publico_otras_obligaciones_inversiones", "Relacionadas con inversiones", None,
     "obligaciones_publico_otras_obligaciones", "P", 1, 0),
    ("depositos_sistema_financiero", "Depósitos del sistema financiero y organismos internacionales", None, "total_pasivo", "P", 1, 0),
    ("depositos_sistema_financiero_vista", "Depósitos a la vista", None, "depositos_sistema_financiero", "P", 1, 0),
    ("depositos_sistema_financiero_ahorro", "Depósitos de ahorro", None, "depositos_sistema_financiero", "P", 1, 0),
    ("depositos_sistema_financiero_plazo", "Depósitos a plazo", None, "depositos_sistema_financiero", "P", 1, 0),
    ("fondos_interbancarios_pasivo", "Fondos interbancarios", None, "total_pasivo", "P", 1, 0),
    ("adeudos", "Adeudos y obligaciones financieras", None, "total_pasivo", "P", 1, 0),
    ("adeudos_pais", "Instituciones del país", "Instituciones financieras del país", "adeudos", "P", 1, 0),
    ("adeudos_exterior", "Instituciones del exterior y organismos internacionales",
     "Empresas del exterior y organismos internacionales", "adeudos", "P", 1, 0),
    ("obligaciones_circulacion_no_subordinadas", "Obligaciones en circulación no subordinadas", None, "total_pasivo", "P", 1, 0),
    ("obligaciones_circulacion_no_subordinadas_bonos_arrendamiento", "Bonos de arrendamiento financiero", None,
     "obligaciones_circulacion_no_subordinadas", "P", 1, 0),
    ("obligaciones_circulacion_no_subordinadas_instrumentos_hipotecarios", "Instrumentos hipotecarios", None,
     "obligaciones_circulacion_no_subordinadas", "P", 1, 0),
    ("obligaciones_circulacion_no_subordinadas_otros_instrumentos", "Otros instrumentos de deuda", None,
     "obligaciones_circulacion_no_subordinadas", "P", 1, 0),
    ("cuentas_por_pagar", "Cuentas por pagar", "Cuentas por pagar netas", "total_pasivo", "P", 1, 0),
    ("intereses_por_pagar", "Intereses y otros gastos por pagar", "Intereses y otros gastos devengados por pagar", "total_pasivo", "P", 1, 0),
    ("intereses_por_pagar_obligaciones_publico", "Obligaciones con el público", None, "intereses_por_pagar", "P", 1, 0),
    ("intereses_por_pagar_depositos_sistema_financiero", "Depósitos del sistema financiero y organismos internacionales", None,
     "intereses_por_pagar", "P", 1, 0),
    ("intereses_por_pagar_fondos_interbancarios", "Fondos interbancarios", None, "intereses_por_pagar", "P", 1, 0),
    ("intereses_por_pagar_adeudos", "Adeudos y obligaciones financieras", None, "intereses_por_pagar", "P", 1, 0),
    ("intereses_por_pagar_obligaciones_circulacion_no_subordinadas", "Obligaciones en circulación no subordinadas", None,
     "intereses_por_pagar", "P", 1, 0),
    ("intereses_por_pagar_cuentas_por_pagar", "Cuentas por pagar", None, "intereses_por_pagar", "P", 1, 0),
    ("otros_pasivos", "Otros pasivos", None, "total_pasivo", "P", 1, 0),
    ("provisiones_creditos_contingentes", "Provisiones por créditos contingentes", None, "total_pasivo", "P", 1, 0),
    ("provisiones_pasivo", "Provisiones", None, "total_pasivo", "P", 1, 0),
    ("provisiones_pasivo_creditos_indirectos", "Créditos indirectos", None, "provisiones_pasivo", "P", 1, 0),
    ("provisiones_pasivo_otras", "Otras provisiones", None, "provisiones_pasivo", "P", 1, 0),
    ("obligaciones_circulacion_subordinadas", "Obligaciones en circulación subordinadas", None, "total_pasivo", "P", 1, 0),
    ("total_pasivo", "Total pasivo", None, "total_pasivo_patrimonio", "P", 1, 0),
    # Patrimonio
    ("patrimonio", "Patrimonio", None, "total_pasivo_patrimonio", "K", 1, 0),
    ("patrimonio_capital_social", "Capital social", None, "patrimonio", "K", 1, 0),
    ("patrimonio_capital_adicional", "Capital adicional", None, "patrimonio", "K", 1, 0),
    ("patrimonio_capital_adicional_ajustes", "Capital adicional y ajustes al patrimonio", None, "patrimonio", "K", 1, 0),
    ("patrimonio_reservas", "Reservas", None, "patrimonio", "K", 1, 0),
    ("patrimonio_ajustes", "Ajustes al patrimonio", None, "patrimonio", "K", 1, 0),
    ("patrimonio_resultados_no_realizados", "Resultados no realizados", None, "patrimonio", "K", 1, 0),
    ("patrimonio_resultados_acumulados", "Resultados acumulados", None, "patrimonio", "K", 1, 0),
    ("patrimonio_resultado_neto_ejercicio", "Resultado neto del ejercicio", "Resultados netos del ejercicio", "patrimonio", "K", 1, 0),
    ("total_pasivo_patrimonio", "Total pasivo y patrimonio", None, None, "T", 1, 0),
    # Contingentes (fuera del balance)
    ("contingentes", "Contingentes", "Contingentes acreedoras", None, "C", 1, 0),
    ("contingentes_avales_cartas_fianza", "Avales, cartas fianza, cartas de crédito y aceptaciones bancarias", None, "contingentes", "C", 1, 0),
    ("contingentes_lineas_no_utilizadas", "Líneas de crédito no utilizadas y créditos concedidos no desembolsados", None,
     "contingentes", "C", 1, 0),
    ("contingentes_derivados", "Instrumentos financieros derivados", None, "contingentes", "C", 1, 0),
    ("contingentes_otras", "Otras cuentas contingentes", None, "contingentes", "C", 1, 0),
    # Estado de ganancias y pérdidas (acumulado de enero al mes)
    ("ingresos_financieros", "Ingresos financieros", None, None, "R", 1, 0),
    ("ingresos_financieros_disponible", "Disponible", "Intereses por disponible", "ingresos_financieros", "R", 1, 0),
    ("ingresos_financieros_fondos_interbancarios", "Fondos interbancarios", "Intereses y comisiones por fondos interbancarios",
     "ingresos_financieros", "R", 1, 0),
    ("ingresos_financieros_inversiones", "Inversiones", "Ingresos por inversiones", "ingresos_financieros", "R", 1, 0),
    ("ingresos_financieros_creditos_directos", "Créditos directos", "Intereses y comisiones por créditos", "ingresos_financieros", "R", 1, 0),
    ("ingresos_financieros_valorizacion_inversiones", "Ganancias por valorización de inversiones",
     "Ingresos por valorización de inversiones", "ingresos_financieros", "R", 1, 0),
    ("ingresos_financieros_inversiones_subsidiarias", "Ganancias por inversiones en subsidiarias, asociadas y negocios conjuntos",
     "Ganancias por inversiones en subsidiarias y asociadas", "ingresos_financieros", "R", 1, 0),
    ("ingresos_financieros_diferencia_cambio", "Diferencia de cambio", None, "ingresos_financieros", "R", 1, 0),
    ("ingresos_financieros_derivados", "Ganancias en productos financieros derivados", None, "ingresos_financieros", "R", 1, 0),
    ("ingresos_financieros_reajuste_indexacion", "Reajuste por indexación", None, "ingresos_financieros", "R", 1, 0),
    ("ingresos_financieros_otros", "Otros", None, "ingresos_financieros", "R", 1, 0),
    ("gastos_financieros", "Gastos financieros", None, None, "R", -1, 0),
    ("gastos_financieros_obligaciones_publico", "Obligaciones con el público", "Intereses y comisiones por obligaciones con el público",
     "gastos_financieros", "R", 1, 0),
    ("gastos_financieros_depositos_sistema_financiero", "Depósitos del sistema financiero y organismos financieros internacionales",
     "Intereses por depósitos del sistema financiero y organismos internacionales", "gastos_financieros", "R", 1, 0),
    ("gastos_financieros_fondos_interbancarios", "Fondos interbancarios", "Intereses y comisiones por fondos interbancarios",
     "gastos_financieros", "R", 1, 0),
    ("gastos_financieros_adeudos", "Adeudos y obligaciones financieras", "Intereses y comisiones por adeudos y obligaciones financieras",
     "gastos_financieros", "R", 1, 0),
    ("gastos_financieros_obligaciones_circulacion_no_subordinadas", "Obligaciones en circulación no subordinadas",
     "Intereses por obligaciones en circulación no subordinadas", "gastos_financieros", "R", 1, 0),
    ("gastos_financieros_obligaciones_circulacion_subordinadas", "Obligaciones en circulación subordinadas",
     "Intereses por obligaciones en circulación subordinadas", "gastos_financieros", "R", 1, 0),
    ("gastos_financieros_valorizacion_inversiones", "Pérdida por valorización de inversiones", None, "gastos_financieros", "R", 1, 0),
    ("gastos_financieros_inversiones_subsidiarias", "Pérdidas por inversiones en subsidiarias, asociadas y negocios conjuntos",
     "Pérdidas por inversiones en subsidiarias y asociadas", "gastos_financieros", "R", 1, 0),
    ("gastos_financieros_primas_fondo_seguro_depositos", "Primas al Fondo de Seguro de Depósitos", None, "gastos_financieros", "R", 1, 0),
    ("gastos_financieros_diferencia_cambio", "Diferencia de cambio", None, "gastos_financieros", "R", 1, 0),
    ("gastos_financieros_derivados", "Pérdidas en productos financieros derivados", None, "gastos_financieros", "R", 1, 0),
    ("gastos_financieros_reajuste_indexacion", "Reajuste por indexación", None, "gastos_financieros", "R", 1, 0),
    ("gastos_financieros_otros", "Otros", None, "gastos_financieros", "R", 1, 0),
    ("margen_financiero_bruto", "Margen financiero bruto", None, None, "R", 1, 1),
    ("provisiones_creditos_directos", "Provisiones para créditos directos", "Provisiones para incobrabilidad de créditos", None, "R", -1, 0),
    ("margen_financiero_neto", "Margen financiero neto", None, None, "R", 1, 1),
    ("ingresos_servicios_financieros", "Ingresos por servicios financieros", None, None, "R", 1, 0),
    ("ingresos_servicios_financieros_cuentas_por_cobrar", "Cuentas por cobrar", "Ingresos de cuentas por cobrar",
     "ingresos_servicios_financieros", "R", 1, 0),
    ("ingresos_servicios_financieros_creditos_indirectos", "Créditos indirectos", "Ingresos por operaciones contingentes",
     "ingresos_servicios_financieros", "R", 1, 0),
    ("ingresos_servicios_financieros_fideicomisos", "Fideicomisos y comisiones de confianza", None, "ingresos_servicios_financieros", "R", 1, 0),
    ("ingresos_servicios_financieros_diversos", "Ingresos diversos", None, "ingresos_servicios_financieros", "R", 1, 0),
    ("gastos_servicios_financieros", "Gastos por servicios financieros", None, None, "R", -1, 0),
    ("gastos_servicios_financieros_cuentas_por_pagar", "Cuentas por pagar", "Gastos de cuentas por pagar", "gastos_servicios_financieros", "R", 1, 0),
    ("gastos_servicios_financieros_creditos_indirectos", "Créditos indirectos", "Gastos por operaciones contingentes",
     "gastos_servicios_financieros", "R", 1, 0),
    ("gastos_servicios_financieros_fideicomisos", "Fideicomisos y comisiones de confianza", None, "gastos_servicios_financieros", "R", 1, 0),
    ("gastos_servicios_financieros_diversos", "Gastos diversos", None, "gastos_servicios_financieros", "R", 1, 0),
    ("resultado_venta_cartera", "Utilidad (pérdida) por venta de cartera", None, None, "R", 1, 0),
    ("margen_operacional", "Margen operacional", None, None, "R", 1, 1),
    ("gastos_administrativos", "Gastos administrativos", None, None, "R", -1, 0),
    ("gastos_administrativos_personal", "Personal", None, "gastos_administrativos", "R", 1, 0),
    ("gastos_administrativos_directorio", "Directorio", None, "gastos_administrativos", "R", 1, 0),
    ("gastos_administrativos_servicios_terceros", "Servicios recibidos de terceros", None, "gastos_administrativos", "R", 1, 0),
    ("gastos_administrativos_impuestos_contribuciones", "Impuestos y contribuciones", None, "gastos_administrativos", "R", 1, 0),
    ("margen_operacional_neto", "Margen operacional neto", None, None, "R", 1, 1),
    ("provisiones_depreciacion_amortizacion", "Provisiones, depreciación y amortización", None, None, "R", -1, 0),
    ("provisiones_depreciacion_amortizacion_creditos_indirectos", "Provisiones para créditos indirectos", None,
     "provisiones_depreciacion_amortizacion", "R", 1, 0),
    ("provisiones_depreciacion_amortizacion_deterioro_inversiones", "Provisiones por pérdida por deterioro de inversiones", None,
     "provisiones_depreciacion_amortizacion", "R", 1, 0),
    ("provisiones_depreciacion_amortizacion_incobrabilidad_cuentas_por_cobrar", "Provisiones para incobrabilidad de cuentas por cobrar", None,
     "provisiones_depreciacion_amortizacion", "R", 1, 0),
    ("provisiones_depreciacion_amortizacion_bienes_realizables", "Provisiones para bienes realizables, recibidos en pago y adjudicados", None,
     "provisiones_depreciacion_amortizacion", "R", 1, 0),
    ("provisiones_depreciacion_amortizacion_contingencias_otras", "Provisiones para contingencias y otras", None,
     "provisiones_depreciacion_amortizacion", "R", 1, 0),
    ("provisiones_depreciacion_amortizacion_otras", "Otras provisiones", None, "provisiones_depreciacion_amortizacion", "R", 1, 0),
    ("provisiones_depreciacion_amortizacion_depreciacion", "Depreciación", None, "provisiones_depreciacion_amortizacion", "R", 1, 0),
    ("provisiones_depreciacion_amortizacion_amortizacion", "Amortización", None, "provisiones_depreciacion_amortizacion", "R", 1, 0),
    ("otros_ingresos_gastos", "Otros ingresos y gastos", None, None, "R", 1, 0),
    ("otros_ingresos_gastos_recuperacion_creditos", "Ingresos (gastos) por recuperación de créditos", None, "otros_ingresos_gastos", "R", 1, 0),
    ("otros_ingresos_gastos_extraordinarios", "Ingresos (gastos) extraordinarios", None, "otros_ingresos_gastos", "R", 1, 0),
    ("otros_ingresos_gastos_ejercicios_anteriores", "Ingresos (gastos) de ejercicios anteriores", None, "otros_ingresos_gastos", "R", 1, 0),
    ("resultado_antes_impuesto_renta", "Resultado antes de impuesto a la renta",
     "Utilidad (pérdida) antes de participaciones e impuesto a la renta", None, "R", 1, 1),
    ("participacion_trabajadores", "Participación de trabajadores", None, None, "R", -1, 0),
    ("impuesto_renta", "Impuesto a la renta", None, None, "R", -1, 0),
    ("resultado_neto_ejercicio", "Resultado neto del ejercicio", "Utilidad (pérdida) neta", None, "R", 1, 1),
]
KEYS = [n[0] for n in NODES]
POS = {k: i for i, k in enumerate(KEYS)}
PARENT = {n[0]: n[3] for n in NODES}
FLOWS = [n[0] for n in NODES if n[4] == "R"]
# Hasta 2012-12 el subtotal se llama «antes de participaciones e impuesto»: mismo nodo (ver docstring).
RENAMED = {"resultado_antes_participaciones_impuesto_renta": "resultado_antes_impuesto_renta"}
# Fuera del árbol: contingentes deudoras (= acreedoras) y cuentas de orden, solo hasta 2012-12.
MEMO = {"contingentes_deudoras", "cuentas_orden_deudoras", "cuentas_orden_acreedoras",
        "contracuenta_cuentas_orden_deudoras", "contracuenta_cuentas_orden_acreedoras",
        "fideicomisos_comisiones_confianza_deudoras", "fideicomisos_comisiones_confianza_acreedoras"}
# Apertura en moneda extranjera: todas las cuentas del balance (para la variación a tipo de cambio constante
# en cada fila del árbol) y las líneas del estado de resultados de los rendimientos y costos implícitos.
YIELD_FLOWS = ["ingresos_financieros_disponible", "ingresos_financieros_fondos_interbancarios",
               "ingresos_financieros_inversiones", "ingresos_financieros_creditos_directos",
               "gastos_financieros_obligaciones_publico", "gastos_financieros_depositos_sistema_financiero",
               "gastos_financieros_fondos_interbancarios", "gastos_financieros_adeudos",
               "gastos_financieros_obligaciones_circulacion_no_subordinadas",
               "gastos_financieros_obligaciones_circulacion_subordinadas",
               "gastos_financieros_primas_fondo_seguro_depositos"]
# Rubros del resumen, de la comparación y de la contribución al crecimiento (la página los lee del JSON):
# (rótulo, rótulo corto, [rótulo mediano para gráficos angostos,] cuentas).
# Cada lado debe cubrir todos los hijos de su total (lo comprueba `check_growth`).
GROUPS = {
    "A": [("Disponible y fondos interbancarios", "Disponible", ["disponible", "fondos_interbancarios_activo"]),
          ("Inversiones", "Inversiones", ["inversiones_netas"]),
          ("Créditos netos", "Créditos netos", ["creditos_netos"]),
          ("Inmuebles, mobiliario y equipo", "Inmuebles", ["inmuebles_mobiliario_equipo_neto"]),
          ("Cuentas por cobrar, rendimientos, bienes realizables y otros", "Otros activos", "Cuentas por cobrar, bienes y otros",
           ["cuentas_por_cobrar_netas", "rendimientos_por_cobrar", "bienes_realizables_netos", "otros_activos"])],
    "P": [("Obligaciones con el público (sobre todo depósitos)", "Público", "Obligaciones con el público", ["obligaciones_publico"]),
          ("Depósitos del sistema financiero", "Sist. financiero", ["depositos_sistema_financiero"]),
          ("Adeudos y obligaciones financieras", "Adeudos", ["adeudos"]),
          ("Valores en circulación", "Valores", ["obligaciones_circulacion_no_subordinadas", "obligaciones_circulacion_subordinadas"]),
          ("Interbancarios, cuentas e intereses por pagar, provisiones y otros pasivos", "Otros pasivos", "Cuentas por pagar y otros pasivos",
           ["fondos_interbancarios_pasivo", "cuentas_por_pagar", "intereses_por_pagar", "otros_pasivos",
            "provisiones_creditos_contingentes", "provisiones_pasivo"]),
          ("Patrimonio", "Patrimonio", ["patrimonio"])],
}
TOL_ABS, TOL_REL = 1.0, 0.0005   # tolerancia de cuadre: 1 miles o 0,05 %


def level(k: str) -> int:
    """0: totales del balance y rubros del estado de resultados; 1: rubros del balance; 2-3: detalle."""
    p = PARENT[k]
    if NODES[POS[k]][4] == "R":
        return 0 if p is None else 1 + level(p)
    if k in BG_TOP:
        return 0
    return 1 if p in BG_TOP else 1 + level(p)


BG_TOP = {"total_activo", "total_pasivo_patrimonio", "total_pasivo", "patrimonio", "contingentes"}
FX = [k for k in KEYS if NODES[POS[k]][4] != "R" or k in YIELD_FLOWS]
FX_FLOWS = [k for k in FX if k in FLOWS]


def t_index(p: int) -> int:
    return (p // 100) * 12 + p % 100 - 1


def read_fx_note(path: Path) -> float | None:
    """Tipo de cambio contable de la nota del cuadro («S/. 2.823» hasta 2015, «S/ 3,362» después)."""
    import re
    for df in pd.read_excel(path, sheet_name=None, header=None).values():
        for v in df.to_numpy().ravel():
            m = re.search(r"Tipo de Cambio Contable:\s*S/\.?\s*(\d+[.,]\d+)", str(v), re.I)
            if m:
                return float(m.group(1).replace(",", "."))
    return None


def load_fx_rates(months: list[int]) -> dict[int, float]:
    """{periodo: soles por dólar} al cierre de cada mes, con el que la SBS convierte la ME del Boletín."""
    cache = pd.read_csv(TC_CACHE) if TC_CACHE.exists() else pd.DataFrame(columns=["periodo", "tc", "archivo"])
    have = set(cache["periodo"].astype(int))
    new = []
    for p in months:
        if p in have:
            continue
        f = RAW_B2201 / f"B-2201-{MONTH_ABBR[p % 100 - 1]}{p // 100}.XLS"
        tc = read_fx_note(f) if f.exists() else None
        if tc is None:
            raise ValueError(f"Sin tipo de cambio contable para {p} ({f.name})")
        new.append({"periodo": p, "tc": tc, "archivo": f.name})
    if new:
        cache = (pd.concat([cache, pd.DataFrame(new)]) if len(cache) else pd.DataFrame(new)).sort_values("periodo")
        TC_CACHE.parent.mkdir(parents=True, exist_ok=True)
        cache.to_csv(TC_CACHE, index=False)
        print(f"  Tipo de cambio contable: {len(new)} meses leídos de los cuadros B-2201")
    return {int(p): float(t) for p, t in zip(cache["periodo"], cache["tc"])}


def load_rows() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(total, me, mn, total del cuadro): filas (periodo, subsistema, id_entidad) × variable en miles de S/."""
    d = read_table(BOLETIN / "estados-financieros.parquet",
                   columns=["periodo", "subsistema", "id_entidad", "es_total", "variable", "apertura", "valor"])
    d = d[d["apertura"].isin(["total", "me", "mn"]) & ~d["variable"].isin(MEMO)].copy()
    d["variable"] = d["variable"].astype(str).replace(RENAMED)
    d["subsistema"] = d["subsistema"].astype(str)
    unknown = set(d["variable"]) - set(KEYS)
    if unknown:
        raise ValueError(f"Variables sin nodo en el árbol: {sorted(unknown)}")
    idx = ["periodo", "subsistema", "id_entidad"]
    ent = d[~d["es_total"]]
    dup = ent.duplicated(idx + ["variable", "apertura"])
    if dup.any():
        raise ValueError(f"Filas repetidas entidad-mes-variable: {ent[dup].head()}")
    wide = {ap: ent[ent["apertura"] == ap].pivot(index=idx, columns="variable", values="valor").reindex(columns=KEYS)
            for ap in ("total", "me", "mn")}
    tot = d[d["es_total"] & (d["apertura"] == "total")]
    tot = tot.pivot_table(index=["periodo", "subsistema"], columns="variable", values="valor", aggfunc="first").reindex(columns=KEYS)
    return wide["total"], wide["me"], wide["mn"], tot


def vigencias(w: pd.DataFrame) -> dict[str, tuple[int, int]]:
    """Primer y último mes con la línea en algún cuadro."""
    per = w.index.get_level_values("periodo")
    out = {}
    for k in KEYS:
        has = w[k].notna().to_numpy()
        out[k] = (int(per[has].min()), int(per[has].max()))
    return out


def clean(w: pd.DataFrame, me: pd.DataFrame, vig: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Ceros dentro de la vigencia, filas en cero y meses repetidos fuera."""
    per = w.index.get_level_values("periodo").to_numpy()
    has_bg = w["total_activo"].notna().to_numpy()
    has_r = w["resultado_neto_ejercicio"].notna().to_numpy()
    for k in KEYS:
        a, b = vig[k]
        inside = (per >= a) & (per <= b) & (has_r if k in FLOWS else has_bg)
        for frame in (w, me):
            col = frame[k].to_numpy(copy=True)
            col[inside & np.isnan(col)] = 0.0
            col[~inside] = np.nan
            frame[k] = col
    # Entidades absorbidas o liquidadas que la SBS sigue mostrando en ceros (CRAC Del Centro desde 2026-04).
    zero = w.index[(w["total_activo"] == 0)]
    if len(zero):
        z = pd.DataFrame(list(zero), columns=["periodo", "subsistema", "id_entidad"])
        for (s, e), g in z.groupby(["subsistema", "id_entidad"]):
            print(f"  Activo cero (se omite): {s} {e}, {len(g)} meses ({g['periodo'].min()}-{g['periodo'].max()})")
    w = w[w["total_activo"].isna() | (w["total_activo"] != 0)]
    # Mismo criterio que visual_rentabilidad.drop_repeated: fila idéntica a la del mes anterior en TODAS
    # las partidas, solo antes de 2015-01.
    r = w.reset_index().sort_values(["id_entidad", "periodo"])
    prev = r.groupby("id_entidad")[KEYS].shift(1)
    same = ((r[KEYS] == prev) | (r[KEYS].isna() & prev.isna())).all(axis=1) & (r["periodo"] < 201501)
    for (s, e), g in r[same].groupby(["subsistema", "id_entidad"]):
        print(f"  Cifras repetidas del mes anterior (se omiten): {s} {e}, {len(g)} meses ({g['periodo'].min()}-{g['periodo'].max()})")
    drop = pd.MultiIndex.from_frame(r.loc[same, ["periodo", "subsistema", "id_entidad"]])
    w = w[~w.index.isin(drop)]
    me = me.reindex(w.index)
    return w, me


def series(values: np.ndarray) -> list | None:
    """Lista de enteros (None donde falta); None si la serie es vacía o cero en todo el rango."""
    vals = [None if np.isnan(x) else int(round(float(x))) for x in values]
    if not any(vals):
        return None
    return vals


def block(frame: pd.DataFrame, fx: pd.DataFrame, t0: int) -> dict:
    """{a, V, X} de una serie mensual con índice t (correlativo de meses), desde su primer mes."""
    ts = range(int(frame.index.min()), int(frame.index.max()) + 1)
    f = frame.reindex(ts)
    x = fx.reindex(ts)
    return {"a": int(frame.index.min()) - t0,
            "V": [series(f[k].to_numpy(dtype=float)) for k in KEYS],
            "X": [series(x[k].to_numpy(dtype=float)) for k in FX]}


def carry(rows: pd.DataFrame, ts: pd.Index, keys: list[str] = FLOWS) -> pd.DataFrame:
    """Acumulado del EGP con arrastre: la entidad que sale del agregado durante el año conserva su último
    acumulado hasta diciembre (misma regla que `visual_rentabilidad.scope_series`)."""
    year = ts // 12
    out = pd.DataFrame(index=ts)
    for k in keys:
        p = rows.pivot_table(index="t", columns="id_entidad", values=k, aggfunc="sum").reindex(ts)
        out[k] = p.groupby(year).ffill().sum(axis=1, min_count=1)
    return out


def sparse_diff(q: pd.DataFrame, v: pd.DataFrame, keys: list[str], ts: pd.Index) -> dict:
    """{índice del nodo: [[mes desde el primero, diferencia], …]} donde el acumulado con arrastre difiere."""
    out = {}
    diff = (q[keys] - v[keys]).round()
    for k in keys:
        nz = diff[k][diff[k].abs() >= 1]
        if len(nz):
            out[str(POS[k])] = [[int(t - ts[0]), int(val)] for t, val in nz.items()]
    return out


def flow12(acc: pd.Series) -> pd.Series:
    """Flujo de 12 meses desde el acumulado (índice t continuo): acumulado + diciembre anterior − mismo mes
    del año anterior; en diciembre, el acumulado."""
    t = acc.index.to_numpy()
    month = t % 12 + 1
    dec = acc.reindex(t - month).to_numpy()
    prev = acc.reindex(t - 12).to_numpy()
    cur = acc.to_numpy()
    return pd.Series(np.where(month == 12, cur, cur + dec - prev), index=acc.index)


def build_data() -> tuple[dict, dict]:
    w, me, mn, tot = load_rows()
    vig = vigencias(pd.concat([w, tot.assign(id_entidad="_total").set_index("id_entidad", append=True)]))
    w, me = clean(w, me, vig)
    mn = mn.reindex(w.index)
    months = month_range(int(w.index.get_level_values("periodo").min()), int(w.index.get_level_values("periodo").max()))
    fx_rate = load_fx_rates(months)
    t0 = t_index(months[0])
    r = w.reset_index()
    r["t"] = r["periodo"].map(t_index)
    rme = me.reset_index()
    rme["t"] = rme["periodo"].map(t_index)
    twice = r.groupby(["t", "id_entidad"])["subsistema"].nunique()
    if (twice > 1).any():
        raise ValueError(f"Entidad en dos subsistemas el mismo mes: {twice[twice > 1].head()}")

    nodes = []
    for k, l, l0, p, e, sg, sub in NODES:
        a, b = vig[k]
        n = {"k": k, "l": l, "p": POS[p] if p else -1, "e": e, "lv": level(k), "sg": sg}
        if l0:
            n["l0"] = l0
        if sub:
            n["sub"] = 1
        if a > months[0]:
            n["from"] = month_key(a)
        if b < months[-1]:
            n["to"] = month_key(b)
        nodes.append(n)

    scopes: dict[str, dict] = {}
    controls = {"agg": {}}
    # El sistema llega hasta el último mes que publicaron los cinco subsistemas: si uno se atrasa, la suma
    # de los demás no es el sistema.
    sys_end = int(r.groupby("subsistema")["t"].max().min())
    for key, label, rows, rows_me in [(s, l, r[r["subsistema"] == s], rme[rme["subsistema"] == s]) for s, l, _ in SUBSYSTEMS] + [
            ("sistema", "Sistema financiero", r[r["t"] <= sys_end], rme[rme["t"] <= sys_end])]:
        v = rows.groupby("t")[KEYS].sum(min_count=1)
        x = rows_me.groupby("t")[FX].sum(min_count=1)
        ts = pd.Index(range(int(v.index.min()), int(v.index.max()) + 1), name="t")
        q = carry(rows, ts)
        qx = carry(rows_me, ts, FX_FLOWS)
        D, DX = sparse_diff(q, v.reindex(ts), FLOWS, ts), sparse_diff(qx, x.reindex(ts), FX_FLOWS, ts)
        scopes[key] = {"n": label, **block(v, x, t0), "D": D, "DX": DX}
        controls["agg"][key] = (v.reindex(ts), q)

    names = pd.read_csv(ENTIDADES, dtype=str).set_index("id_entidad")["nombre_actual"]
    panel = read_table(PROJECT_DIR / "data" / "processed" / "panel_entidad_mes.parquet",
                       columns=["periodo", "subsistema", "id_entidad", "nombre_entidad"])
    last_name = panel.sort_values("periodo").groupby(["subsistema", "id_entidad"])["nombre_entidad"].last()
    ents, entities = {}, []
    for ent, g in r.groupby("id_entidad"):
        g = g.set_index("t").sort_index()
        b = block(g[KEYS], rme[rme["id_entidad"] == ent].set_index("t")[FX], t0)
        spans = []
        for sub, gs in g.groupby("subsistema"):
            ts = sorted(gs.index)
            start = prev = ts[0]
            for t in ts[1:] + [None]:
                if t is None or t != prev + 1:
                    spans.append([sub, int(start - t0), int(prev - t0)])
                    start = t
                prev = t if t is not None else prev
        spans.sort(key=lambda s: s[1])
        subs = sorted({s[0] for s in spans}, key=lambda s: min(x[1] for x in spans if x[0] == s))
        ents[ent] = {"n": {s: (last_name.get((s, ent)) or names.get(ent, ent)) for s in subs}, **b, "m": spans}
        entities += [f"{s}/{ent}" for s in subs]

    data = {
        "months": [month_key(m) for m in months],
        "nodes": nodes,
        "fx": [POS[k] for k in FX],
        "tc": [fx_rate[m] for m in months],
        "groups": {side: [{"l": x[0], "short": x[1], "m": x[2] if len(x) == 4 else x[0], "ks": x[-1]} for x in g] for side, g in GROUPS.items()},
        "subs": [{"k": k, "l": l, "s": s} for k, l, s in SUBSYSTEMS],
        "scopes": scopes,
        "ents": ents,
        "entities": entities,
        "hasta": month_key(months[-1]),
        "generado": dt.date.today().isoformat(),
    }
    controls.update({"w": w, "me": me, "mn": mn, "tot": tot, "r": r, "t0": t0, "months": months})
    return data, controls


def _ok(lhs: pd.Series, rhs: pd.Series) -> tuple[int, int, float]:
    m = lhs.notna()
    res = (lhs - rhs)[m]
    tol = np.maximum(TOL_ABS, TOL_REL * lhs.abs())[m]
    return int(m.sum()), int((res.abs() > tol).sum()), float(res.abs().max()) if m.any() else 0.0


def check_tree(ctl: dict) -> None:
    """Padre = suma de hijos e identidades del estado de resultados, por fila entidad-mes (total y ME)."""
    for label, w in (("total", ctl["w"]), ("ME", ctl["me"])):
        kids: dict[str, list[str]] = {}
        for k, p in PARENT.items():
            if p:
                kids.setdefault(p, []).append(k)
        lines = []
        for p, ch in kids.items():
            if label == "ME" and p not in FX:
                continue
            ch = [c for c in ch if label == "total" or c in FX]
            if label == "ME" and len(ch) < len(kids[p]):
                continue
            n, bad, mx = _ok(w[p], w[ch].sum(axis=1, min_count=1))
            lines.append((p, n, bad, mx))
        n = sum(x[1] for x in lines)
        bad = sum(x[2] for x in lines)
        print(f"  Árbol ({label}): {len(lines)} padres, {n} comparaciones, {bad} fuera de tolerancia")
        for p, nn, b, mx in lines:
            if b:
                print(f"    {p}: {b} de {nn} (máx. {mx:.1f})")
    w = ctl["w"]
    g = w.get
    ids = [
        ("activo = pasivo + patrimonio", g("total_activo"), g("total_pasivo") + g("patrimonio")),
        ("margen bruto = IF - GF", g("margen_financiero_bruto"), g("ingresos_financieros") - g("gastos_financieros")),
        ("margen neto = bruto - provisiones", g("margen_financiero_neto"), g("margen_financiero_bruto") - g("provisiones_creditos_directos")),
        ("margen operacional = neto + ISF - GSF + venta de cartera", g("margen_operacional"),
         g("margen_financiero_neto") + g("ingresos_servicios_financieros") - g("gastos_servicios_financieros") + g("resultado_venta_cartera").fillna(0)),
        ("margen operacional neto = operacional - GA", g("margen_operacional_neto"), g("margen_operacional") - g("gastos_administrativos")),
        ("resultado antes de IR = MON - PDA + otros", g("resultado_antes_impuesto_renta"),
         g("margen_operacional_neto") - g("provisiones_depreciacion_amortizacion") + g("otros_ingresos_gastos")),
        ("resultado neto = antes de IR - participación - IR", g("resultado_neto_ejercicio"),
         g("resultado_antes_impuesto_renta") - g("participacion_trabajadores").fillna(0) - g("impuesto_renta")),
        ("resultado del patrimonio = resultado del EGP", g("patrimonio_resultado_neto_ejercicio"), g("resultado_neto_ejercicio")),
    ]
    for name, lhs, rhs in ids:
        n, bad, mx = _ok(lhs, rhs)
        print(f"  {name}: {n - bad} de {n} cuadran ({(n - bad) / n:.4%}; máx. dif. {mx:.1f})")
    # MN + ME = total
    n, bad, mx = 0, 0, 0.0
    for k in KEYS:
        nn, b, m = _ok(w[k], ctl["mn"][k] + ctl["me"][k])
        n, bad, mx = n + nn, bad + b, max(mx, m)
    print(f"  MN + ME = total: {n - bad} de {n} ({(n - bad) / n:.4%}; máx. dif. {mx:.1f})")


def check_totals(ctl: dict) -> None:
    """Suma de entidades = columna total del cuadro, por mes, subsistema y línea."""
    r, tot = ctl["r"], ctl["tot"]
    s = r.groupby(["periodo", "subsistema"])[KEYS].sum(min_count=1)
    tot = tot.reindex(s.index)
    rows = []
    for k in KEYS:
        lhs, rhs = tot[k], s[k]
        m = lhs.notna() & rhs.notna()
        res = (lhs - rhs)[m]
        tol = np.maximum(TOL_ABS, TOL_REL * lhs.abs())[m]
        bad = res[res.abs() > tol]
        rows += [(k, i[0], i[1], float(v), float(lhs[i])) for i, v in bad.items()]
    n = int(tot.notna().sum().sum())
    print(f"  Suma de entidades = total del cuadro: {n - len(rows)} de {n} celdas mes-subsistema-línea")
    if rows:
        b = pd.DataFrame(rows, columns=["var", "periodo", "subsistema", "dif", "total"])
        for (p, sub), g in b.groupby(["periodo", "subsistema"]):
            top = g.reindex(g["dif"].abs().sort_values(ascending=False).index).head(3)
            print(f"    {p} {sub}: {len(g)} líneas; " + "; ".join(f"{x.var} {x.dif:,.0f}" for x in top.itertuples()))


def check_profit(data: dict, ctl: dict) -> None:
    """Flujo de 12 meses del resultado neto = el del tablero de rentabilidad (campo `rn`, redondeado a
    miles). Dos comparaciones: con los acumulados sin redondear (el método debe dar lo mismo en todos los
    ámbito-mes) y con los acumulados enteros del JSON, que son los que usa la página (difieren a lo sumo
    en el redondeo)."""
    if not RENTABILIDAD_OUT.exists():
        print("  (sin el tablero de rentabilidad para comparar)")
        return
    html = RENTABILIDAD_OUT.read_text(encoding="utf-8")
    rent, _ = json.JSONDecoder().raw_decode(html, html.index('{"months":'))
    fi = rent["fields"].index("rn")
    t0, r = ctl["t0"], ctl["r"]
    k = POS["resultado_neto_ejercicio"]
    own = r.pivot_table(index="t", columns="id_entidad", values="resultado_neto_ejercicio", aggfunc="sum")

    def mine(key: str, rounded: bool) -> dict[str, float]:
        if "/" in key:
            sub, ent = key.split("/", 1)
            e = data["ents"][ent]
            if rounded:
                acc = pd.Series(e["V"][k], index=range(t0 + e["a"], t0 + e["a"] + len(e["V"][k])), dtype=float)
            else:
                acc = own[ent].dropna()
                acc = acc.reindex(range(int(acc.index.min()), int(acc.index.max()) + 1))
            f = flow12(acc)
            inside = {t for s, a, b in e["m"] if s == sub for t in range(t0 + a, t0 + b + 1)}
            f = f[f.index.isin(inside)]
        else:
            sc = data["scopes"][key]
            if rounded:
                acc = pd.Series(sc["V"][k], index=range(t0 + sc["a"], t0 + sc["a"] + len(sc["V"][k])), dtype=float)
                for i, dv in sc["D"].get(str(k), []):
                    acc.iloc[i] += dv
            else:
                acc = ctl["agg"][key][1]["resultado_neto_ejercicio"]
            f = flow12(acc)
        return {data["months"][int(t - t0)]: x for t, x in f.items() if not np.isnan(x)}

    for rounded in (False, True):
        n = bad = 0
        worst = 0.0
        sample = []
        for key, sc in rent["scopes"].items():
            ref = {rent["months"][sc["a"] + i]: x for i, x in enumerate(sc["V"][fi]) if x is not None}
            got = mine(key, rounded)
            for m in set(ref) | set(got):
                n += 1
                x, y = ref.get(m), got.get(m)
                same = x is not None and y is not None and x == int(round(y))
                if not same:
                    bad += 1
                    dif = abs(x - y) if x is not None and y is not None else float("inf")
                    worst = max(worst, dif)
                    if len(sample) < 5:
                        sample.append((key, m, x, None if y is None else round(y)))
        what = "acumulados enteros (los de la página)" if rounded else "acumulados sin redondear"
        print(f"  Resultado neto 12 m vs rentabilidad, {what}: {n - bad} de {n} ámbito-mes idénticos"
              + (f"; máx. dif. {worst:,.0f} miles" if bad else ""))
        for x in sample if not rounded else []:
            print(f"    {x}")


def check_growth(data: dict) -> None:
    """Contribución al crecimiento anual, con los enteros del JSON y la misma regla que la página: para cada
    rubro g, (saldo_t − ME_t × (1 − TC_{t−12}/TC_t) − saldo_{t−12}) / total_{t−12} a tipo de cambio constante,
    más un efecto del tipo de cambio común = Σ ME_t × (1 − TC_{t−12}/TC_t) / total_{t−12}. Controla, en
    todos los ámbitos y meses, que (1) los rubros cubren todos los hijos del total, (2) los rubros más el
    efecto del tipo de cambio suman el crecimiento en soles corrientes y (3) los rubros suman el crecimiento a
    tipo de cambio constante calculado sobre el total."""
    months, tc, fx = data["months"], data["tc"], data["fx"]
    n = len(months)
    nodes = data["nodes"]
    idx = {nd["k"]: i for i, nd in enumerate(nodes)}
    for side, parent, extra in (("A", "total_activo", set()), ("P", "total_pasivo", {"patrimonio"})):
        kids = {nd["k"] for nd in nodes if nd["p"] >= 0 and nodes[nd["p"]]["k"] == parent} | extra
        got = {k for x in GROUPS[side] for k in x[-1]}
        if got != kids:
            raise ValueError(f"Rubros de {side} no cubren el total: faltan {kids - got}, sobran {got - kids}")
    ta = idx["total_activo"]

    def full(sc: dict, i: int, me: bool) -> list:
        nd = nodes[i]
        pres = sc["V"][ta]
        src = sc["X"][fx.index(i)] if me else sc["V"][i]
        out = [None] * n
        for j, p in enumerate(pres or []):
            m = months[sc["a"] + j]
            if p is None or ("from" in nd and m < nd["from"]) or ("to" in nd and m > nd["to"]):
                continue
            out[sc["a"] + j] = (src[j] if src else 0) or 0
        return out

    worst = [0.0, 0.0]
    cnt = 0
    for name, sc in list(data["scopes"].items()) + list(data["ents"].items()):
        for side, top in (("A", "total_activo"), ("P", "total_pasivo_patrimonio")):
            T, TX = full(sc, idx[top], False), full(sc, idx[top], True)
            gs = [[(full(sc, idx[k], False), full(sc, idx[k], True)) for k in x[-1]] for x in GROUPS[side]]
            for j in range(12, n):
                if T[j] is None or not T[j - 12]:
                    continue
                f = 1 - tc[j - 12] / tc[j]
                const, fxe = 0.0, 0.0
                for g in gs:
                    v = sum(s[j] for s, _ in g if s[j] is not None)
                    vp = sum(s[j - 12] for s, _ in g if s[j - 12] is not None)
                    x = sum(xx[j] for _, xx in g if xx[j] is not None)
                    const += (v - x * f - vp) / T[j - 12]
                    fxe += x * f / T[j - 12]
                cur = (T[j] - T[j - 12]) / T[j - 12]
                tot_const = (T[j] - TX[j] * f - T[j - 12]) / T[j - 12]
                # En miles de S/: lo que queda es el redondeo de los enteros (rubros frente al total).
                worst[0] = max(worst[0], abs(const + fxe - cur) * T[j - 12])
                worst[1] = max(worst[1], abs(const - tot_const) * T[j - 12])
                cnt += 1
    print(f"  Contribución al crecimiento: {cnt} ámbito-mes-lado; rubros + efecto del TC = crecimiento corriente "
          f"(máx. dif. {worst[0]:.1f} miles); rubros = crecimiento a TC constante del total (máx. dif. {worst[1]:.1f} miles; "
          f"redondeo de los enteros; la página usa la suma de los rubros como total)")
    if max(worst) > 8:   # hasta 3 miles de redondeo en cada uno de los dos meses, más la ME
        raise ValueError("La contribución al crecimiento no cuadra")


def encode(data: dict) -> str:
    """JSON → gzip → base64, como literal de JavaScript para el marcador de la plantilla. La página lo
    descomprime con `DecompressionStream("gzip")`. Comprimido para que la página quede en ~5 MB (el
    JSON plano pasa de 9 MB)."""
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return json.dumps(base64.b64encode(gzip.compress(raw, compresslevel=9, mtime=0)).decode("ascii"))


def load_texts() -> dict:
    """Glosario de cuentas y cambios normativos para la página. `config/eeff_glosario.json`:
    {intro: [párrafos], conceptos: [fichas], cuentas: [fichas con `var`]}; `config/eeff_cambios.json`:
    {resumen: [{t: título en negrita, x: texto, items?: [subviñetas], post?: texto después}], normas:
    [{fecha_vigencia, norma, cambio, efecto, fuente_url}]} (o solo la lista de normas), en orden cronológico.
    Con `"provisional": true` en uno de los dos la página muestra un aviso en esa pestaña y NO se publica."""
    glos = json.loads(GLOSARIO.read_text(encoding="utf-8"))
    camb = json.loads(CAMBIOS.read_text(encoding="utf-8"))
    if isinstance(camb, list):
        camb = {"resumen": [], "normas": camb}
    known = set(KEYS) | MEMO | set(RENAMED)
    unknown = [c.get("var") for c in glos.get("cuentas", []) if c.get("var") not in known]
    covered = {c.get("var") for c in glos.get("cuentas", [])}
    missing = [k for k in KEYS if k not in covered]
    print(f"  Glosario: {len(glos.get('cuentas', []))} fichas de cuentas, {len(glos.get('conceptos', []))} conceptos; "
          f"{len(missing)} nodos sin ficha; {len(camb.get('normas', []))} normas en cambios")
    if unknown:
        print(f"  AVISO: fichas con variable que no está en el árbol: {unknown}")
    prov = [nm for nm, t in (("Cuentas", glos), ("Cómo leer y cambios", camb)) if t.get("provisional")]
    if prov:
        print(f"  AVISO: textos PROVISIONALES ({', '.join(prov)}): la página muestra un aviso; no publicar")
    return {"glosario": glos, "cambios": camb, "provisional": prov}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path, help="escribe además el JSON suelto en esta ruta")
    args = ap.parse_args()
    print("Armando datos de estados financieros...")
    data, ctl = build_data()
    check_tree(ctl)
    check_totals(ctl)
    check_profit(data, ctl)
    check_growth(data)
    plain = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    payload = encode(data)
    print(f"  {data['months'][0]} a {data['hasta']}, {len(data['entities'])} series de entidad, "
          f"JSON {len(plain) / 1e6:.1f} MB, comprimido en base64 {len(payload) / 1e6:.1f} MB")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(plain, encoding="utf-8")
        print(f"  Escrito {args.json}")
    if not TEMPLATE.exists():
        print(f"  (sin plantilla {TEMPLATE.name}: no se escribe el HTML)")
        return 0
    template = TEMPLATE.read_text(encoding="utf-8")
    if PLACEHOLDER not in template:
        print(f"ERROR: la plantilla no tiene el marcador {PLACEHOLDER}")
        return 1
    if TEXT_PLACEHOLDER not in template:
        print(f"ERROR: la plantilla no tiene el marcador {TEXT_PLACEHOLDER}")
        return 1
    texts = json.dumps(load_texts(), ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = template.replace(PLACEHOLDER, payload).replace(TEXT_PLACEHOLDER, texts)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    OUT_ARTIFACT.write_text(artifact_version(html), encoding="utf-8")
    print(f"  Escrito {OUT.relative_to(PROJECT_DIR)} ({len(html) / 1e6:.1f} MB) y {OUT_ARTIFACT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
