"""Lector de «Balance General y Estado de Ganancias y Pérdidas» (tema `estados-financieros`).

Códigos: B-2201 (banca múltiple), B-3101 (financieras), C-1101 (CMAC), C-2101 (CRAC),
C-4103 (empresas de créditos). Revisado sobre 2015-01 → 2026-08 (700 libros).

Layout (igual en las cinco series y todos los años; solo cambian nombres de hoja y filas)
------------------------------------------------------------------------------------------
- Hojas: Balance General y Estado de Ganancias y Pérdidas. Nombres según era:
  «05-BG (P)»/«06-EGP (P)» (banca y financieras hasta 2015-10), «1»/«2» (desde 2015-11),
  «bg_cm»/«gyp_cm», «bg_cr»/«gyp_cr», «bg_edp»/«gyp_edp». El tipo de hoja no se deduce del
  nombre ni del título: cada etiqueta se reconoce por sí misma.
- Entidades en COLUMNAS: una fila de cabecera con el nombre de la entidad y, debajo, una fila
  «MN | ME | TOTAL» con las tres columnas de cada entidad. La cabecera se ubica con
  `comun.es_entidad`; las columnas de cada entidad, con la fila MN/ME/TOTAL.
- El balance trae DOS bloques en la misma hoja (cabecera «Activo …» y más abajo «Pasivo …»,
  cada uno con su fila de entidades). La columna de etiquetas se repite cada 3 entidades
  (para impresión): esas columnas no tienen MN/ME/TOTAL y se ignoran.
- La columna de etiquetas es la 0, salvo el EGP de banca/financieras 2015-01→2015-10 (col. 1).
- Jerarquía: los rubros principales van en MAYÚSCULAS («DISPONIBLE», «CRÉDITOS NETOS…»); los
  subrubros en tipo título. La sangría NO es fiable (empresas de créditos 2015 tiene subrubros
  sin sangría) y «C.T.S.» está en mayúsculas pero es subrubro: un rubro principal es una
  etiqueta en mayúsculas que además está en `SECCIONES`.
- Incluye columna «Total <subsistema>» (→ es_total en el orquestador).

Hojas que NO se leen (documentado)
----------------------------------
- «Indic-Edpyme» (C-4103 2015-10 y 2024-08) y «3» (B-3101 2023-08, 2023-11, 2024-08): copia
  del cuadro de Indicadores Financieros que la SBS dejó por error dentro del libro. Su tema
  propio es `indicadores-financieros` (B-3301/C-4301); se detecta por el título
  «Indicadores Financieros» y se omite para no mezclar temas.
- «Hoja1» vacía de B-2201 2020-08.

Columnas de entidad especiales
------------------------------
- Banca: «Banco de Crédito con Sucursales en el Exterior» (BCP consolidado con sus sucursales,
  todo el periodo), «Interbank Perú con Sucursales en el Exterior» (2015-01 → 2020-12) y
  «Scotiabank Perú con Sucursales en el Exterior» (2015-01 → 2016-12) → misma entidad que la
  columna local (`bcp`, `interbank`, `scotiabank-peru`), con el token `con_sucursales_exterior`
  al final de la apertura. Se reconocen porque el nombre dice «sucursales en el exterior» y la
  entidad ya aparece en otra columna del bloque.
  «Total Banca Múltiple Incluye Sucursales en el Exterior» se OMITE: es derivable
  (total + BCP consolidado − BCP) y, como el orquestador lo marcaría como total, duplicaría el
  total en la validación.
- CMAC: «TOTAL CAJAS MUNICIPALES DE AHORRO Y CRÉDITO» (sin la CMCP Lima) se OMITE; se conserva
  «TOTAL CAJAS MUNICIPALES» (incluye CMCP Lima). Regla general: si hay varios totales en un
  bloque, se queda el último (el más amplio).

Variables (etiqueta SBS normalizada → variable)
-----------------------------------------------
Ver `SECCIONES` (rubros principales) y `SUBRUBROS` (subrubros, por rubro). El nombre del
subrubro lleva delante el del rubro y, si hay tercer nivel, el del subrubro intermedio
(p. ej. «Otros» bajo «Vigentes» → `creditos_vigentes_otros`; «C.T.S.» bajo «Depósitos a Plazo»
→ `obligaciones_publico_depositos_plazo_cts`). Variantes unificadas:
«Inmueble(s), Mobiliario y Equipo Neto»; «bienes realizables, recibidos…» con coma o punto;
«Provisones/Provisiones para Créditos Indirectos»; «…Bienes Realizados, Recidos en Pago…»
(errata CMAC/CRAC) = «…Bienes Realizables, Recibidos en Pago…»; «Pérdida/Pérdidas por
Inversiones en Subsidiarias…»; «Resultado antes de(l) Impuesto a la Renta»;
«Utilidad (Pérdida) por Venta de Cartera (Crediticia)» y «Ganancia (Pérdida) por Venta de
Cartera» (2015-09) → `resultado_venta_cartera`; «FONDOS INTERBANCARIOS» del activo →
`fondos_interbancarios_activo` y del pasivo → `fondos_interbancarios_pasivo`.

Apertura
--------
`<moneda>` con moneda ∈ {mn, me, total}; en las columnas consolidadas con sucursales en el
exterior, `<moneda>|con_sucursales_exterior`.

Unidades
--------
`miles_soles` en todos los casos (el título dice «En miles de (nuevos) soles»; la columna ME
está expresada en soles al tipo de cambio contable).

Manual anterior (2010-07 → 2012-12; agregado el 2026-10-28)
-----------------------------------------------------------
Mismo layout y hojas, otro plan de cuentas (el Manual de Contabilidad vigente desde 2013-01 cambió
61 rótulos). Solo para periodo <= 2012-12 (`FIN_MANUAL_ANTERIOR`) se suman a los mapas vigentes
`SECCIONES_2012` y `SUBRUBROS_2012`:
1. Alias directos → la variable de siempre: «Inversiones/Créditos netos de provisiones e ingresos
   no devengados», «Rendimientos devengados por cobrar», «Bienes realizables, recibidos en pago,
   adjudicados y fuera de uso netos» (incluye los fuera de uso), «Activo fijo neto de
   depreciación» (cajas), «Otros activos neto», «Cuentas por pagar netas», «Intereses y otros
   gastos devengados por pagar», «Provisiones (para) incobrabilidad de créditos» →
   `provisiones_creditos_directos`, «Utilidad (pérdida) neta» → `resultado_neto_ejercicio`,
   «Contingentes acreedoras» → `contingentes` (con los mismos cuatro subrubros), «Ingresos (gastos)
   extraordinarios y de ejercicios anteriores» (rubro de cajas/EC) → `otros_ingresos_gastos`, y los
   subrubros «Intereses (y comisiones) por …» de ingresos y gastos financieros, «Ingresos/Gastos
   por operaciones contingentes» → `…_creditos_indirectos`, «Negociables disponibles para la
   venta», «Financieras a vencimiento», «Instituciones financieras del país», etc.
2. Sin equivalente desde 2013 → variable propia (no se fuerzan en otra): `participacion_trabajadores`
   (desde 2013 va dentro de gastos de personal), `resultado_antes_participaciones_impuesto_renta`
   (no hay subtotal equivalente; `resultado_antes_impuesto_renta` NO se emite antes de 2013),
   `provisiones_creditos_contingentes` (pasivo; desde 2013 es `provisiones_pasivo_creditos_indirectos`
   dentro de `provisiones_pasivo`, que antes no existe), `patrimonio_capital_adicional_ajustes` (dos
   líneas desde 2013), `patrimonio_resultados_no_realizados`, `ingresos/gastos_financieros_reajuste_indexacion`,
   `provisiones_depreciacion_amortizacion_contingencias_otras` (desde 2013 se abre en créditos
   indirectos, bienes realizables y otras) y la apertura de otros ingresos y gastos
   (`otros_ingresos_gastos_recuperacion_creditos`, `_extraordinarios`, `_ejercicios_anteriores`).
3. Contingentes deudoras y cuentas de orden (desaparecen en 2013) → `contingentes_deudoras` (=
   contingentes acreedoras), `cuentas_orden_deudoras`/`_acreedoras`,
   `contracuenta_cuentas_orden_deudoras`/`_acreedoras`, `fideicomisos_comisiones_confianza_deudoras`/`_acreedoras`.
Comprobado en 2010-07 → 2012-12: activo = suma de rubros, pasivo + patrimonio = total, resultado
antes de participaciones − participación − impuesto = utilidad neta, contingentes deudoras =
acreedoras (diferencias < 0,1 miles). Desde 2013-01 los créditos se netean de los ingresos no
devengados por arrendamiento financiero (nota «**»): quiebre menor en bancos con leasing.
- CMAC 2014-01 → 2014-04: «CMAC Pisco (*)» repite las cifras del 31.12.2013 (nota «La información de
  CMAC Pisco corresponde al 31.12.2013») y el total del estado de resultados «(**)» no la incluye:
  la validación suma ≠ total falla en esos cuatro meses (error de origen, no se corrige).

Trampas
-------
- Filas que se mueven entre meses y subsistemas (CMAC/CRAC no tienen «Comercio Exterior»;
  «Tarjetas de Crédito» aparece en CRAC desde 2019-03 y en CMAC desde 2022-09; obligaciones
  subordinadas desde 2021-12 en CRAC/EC…): todo se ubica por etiqueta.
- Cabeceras incompletas o erróneas en el bloque del pasivo, resueltas con la del otro bloque de
  la misma hoja (las columnas son las mismas): EC 2022-03 sin el nombre «Servicios Financieros
  Total»; EC 2022 → 2026 sin la fila MN/ME/TOTAL de Volvo Finance (se aplica el patrón
  MN/ME/TOTAL de las demás); B-3101 2024-10 → 2026-08 con «Financiera Proempresa» repetida en
  lugar de «Financiera Surgir». Contradicciones no explicadas por una errata → `ValueError`.
- El mismo banco con nombres distintos en activo y pasivo («CRAC Censosud Scotia»/«CRAC CAT»,
  «CMAC Arequipa (*)»): se comparan por id del maestro; cada bloque conserva su nombre impreso.
- Cifras sueltas fuera de las columnas de entidad: ceros en columnas separadoras (banca y
  financieras), sumas de control en B-3101 2025-09 (cols. 4 y 8) y a la derecha del cuadro
  (CMAC 2017-06 → 2017-08, col. 56): se ignoran. Dos o más columnas contiguas con cifras y sin
  entidad (una entidad sin cabecera) → `ValueError`.
- EC 2015-01 → 2023-03: el total se rotula «TOTAL ENTIDADES DE DESARROLLO DE LA PEQUEÑA Y MICRO
  EMPRESA».
- Una etiqueta con cifras que no esté mapeada levanta `ValueError` (queda en el control del
  orquestador) en vez de inventar una variable.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import comun

UNIDAD = "miles_soles"
MONEDAS = {"mn": "mn", "me": "me", "total": "total"}
SUPERINDICES = "".join(chr(c) for c in (0xB9, 0xB2, 0xB3, *range(0x2070, 0x207A)))

# Rubros principales (etiqueta en MAYÚSCULAS) → variable. «fondos interbancarios» depende
# del bloque (activo/pasivo) y se resuelve aparte.
SECCIONES = {
    # Balance: activo
    "disponible": "disponible",
    "fondos interbancarios": None,
    "inversiones netas de provisiones": "inversiones_netas",
    "creditos netos de provisiones y de ingresos no devengados": "creditos_netos",
    "cuentas por cobrar netas de provisiones": "cuentas_por_cobrar_netas",
    "rendimientos por cobrar": "rendimientos_por_cobrar",
    "bienes realizables recibidos en pago y adjudicados netos": "bienes_realizables_netos",
    "inmuebles mobiliario y equipo neto": "inmuebles_mobiliario_equipo_neto",
    "inmueble mobiliario y equipo neto": "inmuebles_mobiliario_equipo_neto",
    "otros activos": "otros_activos",
    "total activo": "total_activo",
    # Balance: pasivo y patrimonio
    "obligaciones con el publico": "obligaciones_publico",
    "depositos del sistema financiero y organismos internacionales": "depositos_sistema_financiero",
    "adeudos y obligaciones financieras": "adeudos",
    "obligaciones en circulacion no subordinadas": "obligaciones_circulacion_no_subordinadas",
    "cuentas por pagar": "cuentas_por_pagar",
    "intereses y otros gastos por pagar": "intereses_por_pagar",
    "otros pasivos": "otros_pasivos",
    "provisiones": "provisiones_pasivo",
    "obligaciones en circulacion subordinadas": "obligaciones_circulacion_subordinadas",
    "total pasivo": "total_pasivo",
    "patrimonio": "patrimonio",
    "total pasivo y patrimonio": "total_pasivo_patrimonio",
    "contingentes": "contingentes",
    # Estado de ganancias y pérdidas
    "ingresos financieros": "ingresos_financieros",
    "gastos financieros": "gastos_financieros",
    "margen financiero bruto": "margen_financiero_bruto",
    "provisiones para creditos directos": "provisiones_creditos_directos",
    "margen financiero neto": "margen_financiero_neto",
    "ingresos por servicios financieros": "ingresos_servicios_financieros",
    "gastos por servicios financieros": "gastos_servicios_financieros",
    "utilidad perdida por venta de cartera": "resultado_venta_cartera",
    "utilidad perdida por venta de cartera crediticia": "resultado_venta_cartera",
    "ganancia perdida por venta de cartera": "resultado_venta_cartera",
    "margen operacional": "margen_operacional",
    "gastos administrativos": "gastos_administrativos",
    "margen operacional neto": "margen_operacional_neto",
    "provisiones depreciacion y amortizacion": "provisiones_depreciacion_amortizacion",
    "otros ingresos y gastos": "otros_ingresos_gastos",
    "resultado antes de impuesto a la renta": "resultado_antes_impuesto_renta",
    "resultado antes del impuesto a la renta": "resultado_antes_impuesto_renta",
    "impuesto a la renta": "impuesto_renta",
    "resultado neto del ejercicio": "resultado_neto_ejercicio",
}

# Subrubros por rubro (variable del rubro → {etiqueta normalizada: variable}).
SUBRUBROS = {
    "disponible": {
        "caja": "disponible_caja",
        "bancos y corresponsales": "disponible_bancos_corresponsales",
        "canje": "disponible_canje",
        "otros": "disponible_otros",
    },
    "inversiones_netas": {
        "inversiones a valor razonable con cambios en resultados": "inversiones_valor_razonable_resultados",
        "inversiones disponibles para la venta": "inversiones_disponibles_venta",
        "inversiones a vencimiento": "inversiones_vencimiento",
        "inversiones en subsidiarias asociadas y negocios conjuntos": "inversiones_subsidiarias",
        "inversiones en commodities": "inversiones_commodities",
        "provisiones": "inversiones_provisiones",
    },
    "creditos_netos": {
        "vigentes": "creditos_vigentes",
        "cuentas corrientes": "creditos_vigentes_cuentas_corrientes",
        "tarjetas de credito": "creditos_vigentes_tarjetas_credito",
        "descuentos": "creditos_vigentes_descuentos",
        "factoring": "creditos_vigentes_factoring",
        "prestamos": "creditos_vigentes_prestamos",
        "arrendamiento financiero": "creditos_vigentes_arrendamiento_financiero",
        "hipotecarios para vivienda": "creditos_vigentes_hipotecarios_vivienda",
        "comercio exterior": "creditos_vigentes_comercio_exterior",
        "creditos por liquidar": "creditos_vigentes_por_liquidar",
        "otros": "creditos_vigentes_otros",
        "refinanciados y reestructurados": "creditos_refinanciados_reestructurados",
        "atrasados": "creditos_atrasados",
        "vencidos": "creditos_atrasados_vencidos",
        "en cobranza judicial": "creditos_atrasados_cobranza_judicial",
        "provisiones": "creditos_provisiones",
        "intereses y comisiones no devengados": "creditos_intereses_no_devengados",
    },
    "rendimientos_por_cobrar": {
        "disponible": "rendimientos_por_cobrar_disponible",
        "fondos interbancarios": "rendimientos_por_cobrar_fondos_interbancarios",
        "inversiones": "rendimientos_por_cobrar_inversiones",
        "creditos": "rendimientos_por_cobrar_creditos",
        "cuentas por cobrar": "rendimientos_por_cobrar_cuentas_por_cobrar",
    },
    "obligaciones_publico": {
        "depositos a la vista": "obligaciones_publico_depositos_vista",
        "depositos de ahorro": "obligaciones_publico_depositos_ahorro",
        "depositos a plazo": "obligaciones_publico_depositos_plazo",
        "certificados bancarios y de depositos": "obligaciones_publico_depositos_plazo_certificados",
        "cuentas a plazo": "obligaciones_publico_depositos_plazo_cuentas_plazo",
        "c t s": "obligaciones_publico_depositos_plazo_cts",
        "otros": "obligaciones_publico_depositos_plazo_otros",
        "depositos restringidos": "obligaciones_publico_depositos_restringidos",
        "otras obligaciones": "obligaciones_publico_otras_obligaciones",
        "a la vista": "obligaciones_publico_otras_obligaciones_vista",
        "relacionadas con inversiones": "obligaciones_publico_otras_obligaciones_inversiones",
    },
    "depositos_sistema_financiero": {
        "depositos a la vista": "depositos_sistema_financiero_vista",
        "depositos de ahorro": "depositos_sistema_financiero_ahorro",
        "depositos a plazo": "depositos_sistema_financiero_plazo",
    },
    "adeudos": {
        "instituciones del pais": "adeudos_pais",
        "instituciones del exterior y organismos internacionales": "adeudos_exterior",
    },
    "obligaciones_circulacion_no_subordinadas": {
        "bonos de arrendamiento financiero": "obligaciones_circulacion_no_subordinadas_bonos_arrendamiento",
        "instrumentos hipotecarios": "obligaciones_circulacion_no_subordinadas_instrumentos_hipotecarios",
        "otros instrumentos de deuda": "obligaciones_circulacion_no_subordinadas_otros_instrumentos",
    },
    "intereses_por_pagar": {
        "obligaciones con el publico": "intereses_por_pagar_obligaciones_publico",
        "depositos del sistema financiero y organismos internacionales": "intereses_por_pagar_depositos_sistema_financiero",
        "fondos interbancarios": "intereses_por_pagar_fondos_interbancarios",
        "adeudos y obligaciones financieras": "intereses_por_pagar_adeudos",
        "obligaciones en circulacion no subordinadas": "intereses_por_pagar_obligaciones_circulacion_no_subordinadas",
        "cuentas por pagar": "intereses_por_pagar_cuentas_por_pagar",
    },
    "provisiones_pasivo": {
        "creditos indirectos": "provisiones_pasivo_creditos_indirectos",
        "otras provisiones": "provisiones_pasivo_otras",
    },
    "patrimonio": {
        "capital social": "patrimonio_capital_social",
        "capital adicional": "patrimonio_capital_adicional",
        "reservas": "patrimonio_reservas",
        "ajustes al patrimonio": "patrimonio_ajustes",
        "resultados acumulados": "patrimonio_resultados_acumulados",
        "resultado neto del ejercicio": "patrimonio_resultado_neto_ejercicio",
    },
    "contingentes": {
        "avales cartas fianza cartas de credito y aceptaciones bancarias": "contingentes_avales_cartas_fianza",
        "lineas de credito no utilizadas y creditos concedidos no desembolsados": "contingentes_lineas_no_utilizadas",
        "instrumentos financieros derivados": "contingentes_derivados",
        "otras cuentas contingentes": "contingentes_otras",
    },
    "ingresos_financieros": {
        "disponible": "ingresos_financieros_disponible",
        "fondos interbancarios": "ingresos_financieros_fondos_interbancarios",
        "inversiones": "ingresos_financieros_inversiones",
        "creditos directos": "ingresos_financieros_creditos_directos",
        "ganancias por valorizacion de inversiones": "ingresos_financieros_valorizacion_inversiones",
        "ganancias por inversiones en subsidiarias asociadas y negocios conjuntos": "ingresos_financieros_inversiones_subsidiarias",
        "diferencia de cambio": "ingresos_financieros_diferencia_cambio",
        "ganancias en productos financieros derivados": "ingresos_financieros_derivados",
        "otros": "ingresos_financieros_otros",
    },
    "gastos_financieros": {
        "obligaciones con el publico": "gastos_financieros_obligaciones_publico",
        "depositos del sistema financiero y organismos financieros internacionales": "gastos_financieros_depositos_sistema_financiero",
        "fondos interbancarios": "gastos_financieros_fondos_interbancarios",
        "adeudos y obligaciones financieras": "gastos_financieros_adeudos",
        "obligaciones en circulacion no subordinadas": "gastos_financieros_obligaciones_circulacion_no_subordinadas",
        "obligaciones en circulacion subordinadas": "gastos_financieros_obligaciones_circulacion_subordinadas",
        "perdida por valorizacion de inversiones": "gastos_financieros_valorizacion_inversiones",
        "perdida por inversiones en subsidiarias asociadas y negocios conjuntos": "gastos_financieros_inversiones_subsidiarias",
        "perdidas por inversiones en subsidiarias asociadas y negocios conjuntos": "gastos_financieros_inversiones_subsidiarias",
        "primas al fondo de seguro de depositos": "gastos_financieros_primas_fondo_seguro_depositos",
        "diferencia de cambio": "gastos_financieros_diferencia_cambio",
        "perdidas en productos financieros derivados": "gastos_financieros_derivados",
        "otros": "gastos_financieros_otros",
    },
    "ingresos_servicios_financieros": {
        "cuentas por cobrar": "ingresos_servicios_financieros_cuentas_por_cobrar",
        "creditos indirectos": "ingresos_servicios_financieros_creditos_indirectos",
        "fideicomisos y comisiones de confianza": "ingresos_servicios_financieros_fideicomisos",
        "ingresos diversos": "ingresos_servicios_financieros_diversos",
    },
    "gastos_servicios_financieros": {
        "cuentas por pagar": "gastos_servicios_financieros_cuentas_por_pagar",
        "creditos indirectos": "gastos_servicios_financieros_creditos_indirectos",
        "fideicomisos y comisiones de confianza": "gastos_servicios_financieros_fideicomisos",
        "gastos diversos": "gastos_servicios_financieros_diversos",
    },
    "gastos_administrativos": {
        "personal": "gastos_administrativos_personal",
        "directorio": "gastos_administrativos_directorio",
        "servicios recibidos de terceros": "gastos_administrativos_servicios_terceros",
        "impuestos y contribuciones": "gastos_administrativos_impuestos_contribuciones",
    },
    "provisiones_depreciacion_amortizacion": {
        "provisiones para creditos indirectos": "provisiones_depreciacion_amortizacion_creditos_indirectos",
        "provisones para creditos indirectos": "provisiones_depreciacion_amortizacion_creditos_indirectos",
        "provisiones por perdida por deterioro de inversiones": "provisiones_depreciacion_amortizacion_deterioro_inversiones",
        "provisiones para incobrabilidad de cuentas por cobrar": "provisiones_depreciacion_amortizacion_incobrabilidad_cuentas_por_cobrar",
        "provisiones para bienes realizables recibidos en pago y adjudicados": "provisiones_depreciacion_amortizacion_bienes_realizables",
        "provisiones para bienes realizados recidos en pago y adjudicados": "provisiones_depreciacion_amortizacion_bienes_realizables",
        "otras provisiones": "provisiones_depreciacion_amortizacion_otras",
        "depreciacion": "provisiones_depreciacion_amortizacion_depreciacion",
        "amortizacion": "provisiones_depreciacion_amortizacion_amortizacion",
    },
}

# Manual de Contabilidad anterior (cuadros hasta 2012-12). El layout es el mismo; cambia el plan de
# cuentas. Se usan SOLO si el periodo es <= FIN_MANUAL_ANTERIOR (desde 2013-01 nada cambia) y se
# suman a los mapas vigentes. Tres tipos de fila (ver «Manual anterior» en el docstring):
#   1. alias directos: misma partida con otro rótulo -> la variable de siempre;
#   2. partidas sin equivalente desde 2013 -> variable propia (no se fuerzan en otra);
#   3. cuentas de orden y contingentes deudoras -> variable propia (desaparecen en 2013).
FIN_MANUAL_ANTERIOR = 201212
SECCIONES_2012 = {
    # 1. alias directos
    "inversiones netas de provisiones e ingresos no devengados": "inversiones_netas",
    "creditos netos de provisiones e ingresos no devengados": "creditos_netos",
    "rendimientos devengados por cobrar": "rendimientos_por_cobrar",
    "bienes realizables recibidos en pago adjudicados y fuera de uso netos": "bienes_realizables_netos",
    "activo fijo neto de depreciacion": "inmuebles_mobiliario_equipo_neto",
    "otros activos neto": "otros_activos",
    "depositos del sist financiero y org internacionales": "depositos_sistema_financiero",
    "cuentas por pagar netas": "cuentas_por_pagar",
    "intereses y otros gastos devengados por pagar": "intereses_por_pagar",
    "contingentes acreedoras": "contingentes",
    "provisiones para incobrabilidad de creditos": "provisiones_creditos_directos",
    "provisiones incobrabilidad de creditos": "provisiones_creditos_directos",
    "ingresos gastos extraordinarios y de ejercicios anteriores": "otros_ingresos_gastos",  # CMAC/CRAC/EC
    "utilidad perdida neta": "resultado_neto_ejercicio",
    # 2. sin equivalente desde 2013
    "provisiones por creditos contingentes": "provisiones_creditos_contingentes",
    "utilidad perdida antes de participaciones e impuesto a la renta":
        "resultado_antes_participaciones_impuesto_renta",
    "participacion de trabajadores": "participacion_trabajadores",
    # 3. cuentas de orden y contingentes deudoras
    "contingentes deudoras": "contingentes_deudoras",
    "cuentas de orden deudoras": "cuentas_orden_deudoras",
    "contracuenta de cuentas de orden acreedoras": "contracuenta_cuentas_orden_acreedoras",
    "fideicomisos y comisiones de confianza deudoras": "fideicomisos_comisiones_confianza_deudoras",
    "contracuenta de cuentas de orden deudoras": "contracuenta_cuentas_orden_deudoras",
    "cuentas de orden acreedoras": "cuentas_orden_acreedoras",
    "fideicomisos y comisiones de confianza acreedoras": "fideicomisos_comisiones_confianza_acreedoras",
}
SUBRUBROS_2012 = {
    "inversiones_netas": {
        "inversiones en subsidiarias y asociadas": "inversiones_subsidiarias",
        "negociables disponibles para la venta": "inversiones_disponibles_venta",
        "financieras a vencimiento": "inversiones_vencimiento",
    },
    "obligaciones_publico": {
        "depositos de ahorros": "obligaciones_publico_depositos_ahorro",
        "certificados bancarios y de deposito": "obligaciones_publico_depositos_plazo_certificados",
        "relacionadas con inversiones negociables y a vencimiento":
            "obligaciones_publico_otras_obligaciones_inversiones",
    },
    "depositos_sistema_financiero": {
        "depositos de ahorros": "depositos_sistema_financiero_ahorro",
    },
    "adeudos": {
        "instituciones financieras del pais": "adeudos_pais",
        "empresas del exterior y organismos internacionales": "adeudos_exterior",
    },
    "patrimonio": {
        "resultados netos del ejercicio": "patrimonio_resultado_neto_ejercicio",
        # sin equivalente: desde 2013 son dos líneas (capital adicional; ajustes al patrimonio)
        "capital adicional y ajustes al patrimonio": "patrimonio_capital_adicional_ajustes",
        "resultados no realizados": "patrimonio_resultados_no_realizados",
    },
    "ingresos_financieros": {
        "intereses por disponible": "ingresos_financieros_disponible",
        "intereses por disponibles": "ingresos_financieros_disponible",
        "intereses y comisiones por fondos interbancarios": "ingresos_financieros_fondos_interbancarios",
        "ingresos por inversiones": "ingresos_financieros_inversiones",
        "ingresos por valorizacion de inversiones": "ingresos_financieros_valorizacion_inversiones",
        "ganancias por inversiones en subsidiarias y asociadas": "ingresos_financieros_inversiones_subsidiarias",
        "intereses y comisiones por creditos": "ingresos_financieros_creditos_directos",
        "reajuste por indexacion": "ingresos_financieros_reajuste_indexacion",  # sin equivalente
    },
    "gastos_financieros": {
        "intereses y comisiones por obligaciones con el publico": "gastos_financieros_obligaciones_publico",
        "intereses por depositos del sistema financiero y organismos internacionales":
            "gastos_financieros_depositos_sistema_financiero",
        "intereses por depositos del sist financ y org internacionales":
            "gastos_financieros_depositos_sistema_financiero",
        "intereses y comisiones por fondos interbancarios": "gastos_financieros_fondos_interbancarios",
        "intereses y comisiones por adeudos y obligaciones financieras": "gastos_financieros_adeudos",
        "intereses por obligaciones en circulacion no subordinadas":
            "gastos_financieros_obligaciones_circulacion_no_subordinadas",
        "intereses por obligaciones en circulacion subordinadas":
            "gastos_financieros_obligaciones_circulacion_subordinadas",
        "perdidas por inversiones en subsidiarias y asociadas": "gastos_financieros_inversiones_subsidiarias",
        "reajuste por indexacion": "gastos_financieros_reajuste_indexacion",  # sin equivalente
    },
    "ingresos_servicios_financieros": {
        "ingresos de cuentas por cobrar": "ingresos_servicios_financieros_cuentas_por_cobrar",
        "intereses de cuentas por cobrar": "ingresos_servicios_financieros_cuentas_por_cobrar",
        "ingresos por operaciones contingentes": "ingresos_servicios_financieros_creditos_indirectos",
        "ingresos por fideicomisos y comisiones de confianza": "ingresos_servicios_financieros_fideicomisos",
    },
    "gastos_servicios_financieros": {
        "gastos de cuentas por pagar": "gastos_servicios_financieros_cuentas_por_pagar",
        "gastos por operaciones contingentes": "gastos_servicios_financieros_creditos_indirectos",
        "gastos por fideicomisos y comisiones de confianza": "gastos_servicios_financieros_fideicomisos",
    },
    "provisiones_depreciacion_amortizacion": {
        # sin equivalente: desde 2013 se abre en créditos indirectos, bienes realizables y otras
        "provisiones para contingencias y otras": "provisiones_depreciacion_amortizacion_contingencias_otras",
    },
    "otros_ingresos_gastos": {  # sin equivalente: desde 2013 el rubro no se abre
        "ingresos gastos por recuperacion de creditos": "otros_ingresos_gastos_recuperacion_creditos",
        "ingresos gastos extraordinarios": "otros_ingresos_gastos_extraordinarios",
        "ingresos gastos de ejercicios anteriores": "otros_ingresos_gastos_ejercicios_anteriores",
    },
}


def mapas(periodo: int) -> tuple[dict, dict]:
    """(SECCIONES, SUBRUBROS) del plan de cuentas vigente en el periodo."""
    if periodo > FIN_MANUAL_ANTERIOR:
        return SECCIONES, SUBRUBROS
    return _MAPAS_2012


_MAPAS_2012 = ({**SECCIONES, **SECCIONES_2012},
               {k: {**SUBRUBROS.get(k, {}), **SUBRUBROS_2012.get(k, {})}
                for k in set(SUBRUBROS) | set(SUBRUBROS_2012)})


def clave(texto) -> str:
    """Etiqueta comparable: `comun.norm` + sin superíndices ni puntuación («C.T.S.» → «c t s»)."""
    if not isinstance(texto, str):
        return ""
    s = comun.norm(texto.translate({ord(c): " " for c in SUPERINDICES}))
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def es_mayuscula(texto: str) -> bool:
    letras = re.sub(r"[^A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", "", texto)
    return bool(letras) and letras == letras.upper()


def texto(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def filas_cabecera(g, subsistema: str) -> list[int]:
    """Filas con al menos un nombre de entidad (cabeceras de bloque)."""
    filas = []
    for i in range(g.shape[0]):
        if any(comun.es_entidad(v, subsistema) for v in g.iloc[i, 1:] if isinstance(v, str)):
            filas.append(i)
    return filas


def columnas_entidad(g, h: int, subsistema: str) -> tuple[int, list[tuple[int, str, str]]]:
    """(columna de etiquetas, [(columna, entidad, moneda)]) del bloque con cabecera en la fila h."""
    nc = g.shape[1]
    primera = min(j for j in range(1, nc) if comun.es_entidad(g.iat[h, j], subsistema))
    # Fila MN/ME/TOTAL: la primera debajo de la cabecera que tenga «MN».
    sub = next((i for i in range(h + 1, min(h + 4, g.shape[0]))
                if any(comun.norm(v) == "mn" for v in g.iloc[i, primera:])), None)
    if sub is None:
        raise ValueError(f"fila {h}: no se encontró la fila MN/ME/TOTAL")
    # Nombres de entidad: todo texto de la cabecera a la derecha de la primera entidad,
    # salvo las marcas de columna de etiquetas («Activo», «Pasivo»).
    marcas = [j for j in range(primera, nc) if texto(g.iat[h, j])]
    nombres = {j: texto(g.iat[h, j]) for j in marcas
               if comun.norm(g.iat[h, j]) not in ("activo", "pasivo")}
    # Columnas de cada entidad: desde su nombre hasta la siguiente marca de cabecera.
    spans = {}
    for j in nombres:
        fin = min([k for k in marcas if k > j] + [nc])
        spans[j] = {k - j: MONEDAS[comun.norm(g.iat[sub, k])] for k in range(j, fin)
                    if comun.norm(g.iat[sub, k]) in MONEDAS}
    # Si a una entidad le falta la fila MN/ME/TOTAL (Volvo Finance en el pasivo de EC
    # 2022-2026), se usa el patrón de desplazamientos de las demás entidades del bloque.
    patrones = [tuple(sorted(s.items())) for s in spans.values() if len(s) == 3]
    patron = dict(max(set(patrones), key=patrones.count)) if patrones else {}
    cols = []
    for j, nombre in nombres.items():
        for d, moneda in sorted((spans[j] or patron).items()):
            cols.append((j + d, nombre, moneda))
    # Columna de etiquetas: la de más a la derecha antes de la primera entidad con texto en
    # las filas de datos.
    datos = range(sub + 1, min(sub + 8, g.shape[0]))
    lab = max((j for j in range(primera) if any(texto(g.iat[i, j]) for i in datos)), default=0)
    return lab, cols


es_total = comun.es_total


def ident(nombre: str, subsistema: str):
    """Clave de comparación de una entidad: id del maestro, «TOTAL» o el nombre normalizado."""
    if es_total(nombre):
        return "TOTAL"
    return comun.resolver_entidad(comun.limpiar(nombre), subsistema)[0] or comun.norm(nombre)


def repetidas(cols, subsistema: str) -> set:
    """Entidades (no totales) que aparecen en más de una posición de la cabecera del bloque."""
    vistas = [ident(n, subsistema) for _, n, m in cols
              if m == "mn" and "sucursales" not in comun.norm(n)]
    return {k for k in vistas if k != "TOTAL" and vistas.count(k) > 1}


def depurar_entidades(cols, subsistema: str):
    """Quita totales redundantes y marca el BCP consolidado (ver docstring del módulo)."""
    totales = [n for _, n, _ in cols if es_total(n) and "sucursales" not in comun.norm(n)]
    ultimo_total = totales[-1] if totales else None
    ids = {}
    for _, n, _ in cols:
        if not es_total(n) and "sucursales" not in comun.norm(n):
            ids[comun.resolver_entidad(comun.limpiar(n), subsistema)[0]] = n
    salida = []
    for j, n, moneda in cols:
        nn = comun.norm(n)
        if es_total(n):
            if "sucursales" in nn or n != ultimo_total:
                continue
            salida.append((j, n, moneda))
        elif "sucursales en el exterior" in nn and (
                comun.resolver_entidad(comun.limpiar(n), subsistema)[0] in ids):
            salida.append((j, n, f"{moneda}|con_sucursales_exterior"))
        else:
            salida.append((j, n, moneda))
    return salida


def leer(ruta: Path, subsistema: str, periodo: int) -> list[dict]:
    secciones, subrubros = mapas(periodo)
    out = []
    for hoja, g in comun.abrir(ruta).items():
        if g.empty:
            continue
        titulo = " ".join(comun.norm(v) for v in g.iloc[:6].values.ravel() if isinstance(v, str))
        if "indicadores financieros" in titulo:
            continue  # copia del cuadro de indicadores (otro tema); ver docstring
        cabeceras = filas_cabecera(g, subsistema)
        bloques = [columnas_entidad(g, h, subsistema) for h in cabeceras]
        # Los bloques de una hoja (activo y pasivo) comparten columnas. Si a la cabecera de un
        # bloque le falta una entidad (EC 2022-03: «Servicios Financieros Total» sin nombre en
        # el pasivo) se completa con las de los otros bloques; si se contradicen, error.
        # La comparación es por entidad resuelta: el mismo banco puede estar escrito distinto
        # en cada bloque («CRAC Censosud Scotia» / «CRAC CAT», «CMAC Arequipa (*)»).
        # Errata conocida: B-3101 2024-10 → 2026-08 rotula «Financiera Proempresa» DOS veces en
        # la cabecera del pasivo (la segunda es Surgir, como dice la del activo): un nombre
        # repetido dentro de un bloque cede ante el nombre de la misma columna en otro bloque.
        repetidos = [repetidas(cols, subsistema) for _, cols in bloques]
        union: dict[int, tuple[str, str]] = {}
        for (_, cols), rep in sorted(zip(bloques, repetidos), key=lambda x: len(x[1])):
            for j, n, m in cols:
                if j not in union and ident(n, subsistema) not in rep:
                    union[j] = (n, m)
        por_bloque = []
        for (_, cols), rep in zip(bloques, repetidos):
            propias = {}
            for j, n, m in cols:
                if j in union and (ident(union[j][0], subsistema), union[j][1]) != (ident(n, subsistema), m):
                    if ident(n, subsistema) not in rep:
                        raise ValueError(f"{hoja} col {j}: bloques con entidades distintas "
                                         f"({union[j][0]!r} vs {n!r})")
                    continue  # nombre repetido por errata: vale el del otro bloque
                propias[j] = (n, m)
            completas = dict(union)
            completas.update(propias)  # cada bloque con sus propios nombres
            por_bloque.append(depurar_entidades(
                [(j, n, m) for j, (n, m) in sorted(completas.items())], subsistema))
        mapeadas = set(union) | {j for _, cols in bloques for j, _, _ in cols}
        ultima = max(mapeadas, default=0)
        for b, (h, (lab, _), cols) in enumerate(zip(cabeceras, bloques, por_bloque)):
            fin = cabeceras[b + 1] if b + 1 < len(cabeceras) else g.shape[0]
            bloque = comun.norm(g.iat[h, lab])  # «activo», «pasivo» o "" (EGP)
            seccion = None
            for i in range(h + 1, fin):
                raw = texto(g.iat[i, lab])
                if not raw:
                    continue
                valores = [(n, m, g.iat[i, j]) for j, n, m in cols]
                if all(comun.a_numero(v) is None for _, _, v in valores):
                    continue  # títulos, notas, «Tipo de cambio contable…»
                # Cifras fuera de las columnas de entidad. Una entidad sin cabecera dejaría 2-3
                # columnas contiguas con cifras → error. Se ignoran: cifras sueltas en una
                # columna separadora (ceros en banca/financieras; sumas de control en B-3101
                # 2025-09 cols. 4 y 8) y todo lo que está a la derecha de la última entidad
                # (cálculos de control, p. ej. CMAC 2017-06 → 2017-08 col. 56).
                sueltas = {j for j in range(lab + 1, ultima)
                           if j not in mapeadas and comun.a_numero(g.iat[i, j]) not in (None, 0)}
                huerfanas = sorted(j for j in sueltas if j + 1 in sueltas or j - 1 in sueltas)
                if huerfanas:
                    raise ValueError(f"{hoja} fila {i}: cifras en columnas sin entidad {huerfanas}")
                k = clave(raw)
                if es_mayuscula(raw) and k in secciones:
                    variable = secciones[k]
                    if variable is None:  # fondos interbancarios
                        if bloque not in ("activo", "pasivo"):
                            raise ValueError(f"{hoja} fila {i}: «{raw}» fuera de bloque activo/pasivo")
                        variable = f"fondos_interbancarios_{bloque}"
                    seccion = variable
                else:
                    variable = subrubros.get(seccion, {}).get(k)
                    if variable is None:
                        raise ValueError(f"{hoja} fila {i}: etiqueta no mapeada «{raw}» (rubro {seccion})")
                for entidad, apertura, v in valores:
                    out.append(comun.registro(hoja, entidad, variable, apertura, v, UNIDAD))
    return out
