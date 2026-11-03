"""Calcula los indicadores del «Tablero de indicadores del sistema financiero» por ámbito y mes.

Ámbitos: el sistema (los 5 subsistemas), cada subsistema y cada entidad (clave `id_entidad`; una
entidad que cambió de subsistema tiene una sola serie encadenada). Meses: desde
`visual_mora.START_PERIOD` (2010-07) hasta el último mes con datos.

No reescribe reglas: importa las cargas y reglas de los tableros publicados para que cada indicador
coincida con el del tablero equivalente.
- `visual_mora`: saldos por tipo y situación (mora, cartera de alto riesgo, refinanciados, composición),
  créditos en ME y tipo de cambio implícito (crecimiento a tipo de cambio constante), castigos de 12
  meses por subsistema (`load_writeoffs`, meses de `adj_months`) y deudores.
- `visual_solvencia`: PE, APR y CET1 por entidad (`build_frame`), mínimo legal `LIMITS`.
- `visual_rentabilidad`: estados financieros (`load_statements`), flujos y promedios de 12 meses
  (`rolling_block`) y la regla de perímetro de los agregados (`scope_series`).
- `visual_liquidez`: activos líquidos y pasivos de corto plazo, RCL publicado, RFNE, depósitos totales
  (definición del ranking), depósitos en ME, adeudos, pasivo y créditos del ranking (`build_frame`).
- `visual_eeff`: tipo de cambio contable de fin de mes (`load_fx_rates`, `data/processed/tc_contable.csv`).
- Panel entidad × mes: posición global en ME (miles de S/).
- `data/processed/sf2103_deudores.parquet`: deudores únicos del sistema (trimestral).

Reglas de los agregados (detalle en el README, sección «Tablero de indicadores»):
- Subsistema = suma de sus entidades del mes y luego el cociente (Σ numerador / Σ denominador).
- Sistema = suma de los subsistemas que tienen el indicador por diseño (las empresas de créditos no
  captan depósitos ni reportan ratio de liquidez, RCL ni RFNE). Si uno de ellos no tiene dato ese mes
  (un subsistema que todavía no publica el mes, por ejemplo), el sistema queda vacío.
- Excepciones: los indicadores con flujos de 12 meses usan para el sistema la serie de
  `visual_rentabilidad` (todas las entidades con la regla de perímetro; la suma de subsistemas contaría
  dos veces a una entidad que cambia de subsistema a mitad de año); deudores del sistema = SF-2103
  (no se suman deudores); el RCL no se agrega (es el promedio de ratios diarios: solo entidad y
  subsistema publicados).
- Entidades: castigos de 12 meses por `id_entidad` (no se pierden los castigos previos a un cambio de
  subsistema); la fila de castigos duplicada de Santander Consumer en 2025-04 se queda donde están
  sus créditos ese mes.

Salidas:
    data/processed/indicadores/indicadores_ambito_mes.parquet  tabla larga (solo celdas con valor)
    data/processed/indicadores/indicadores_ambito_mes.xlsx     versión para revisar (ancha)
    data/processed/indicadores/ambitos.csv                     ámbitos: nombre, subsistema, historial, activa
    config/indicadores.csv                                      catálogo de indicadores
    data/_control/indicadores_validacion.csv                    cálculo propio vs. publicado por la SBS

Uso:
    python src/indicadores_datos.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import visual_mora as vm  # noqa: E402
import visual_solvencia as vs  # noqa: E402
import visual_rentabilidad as vr  # noqa: E402
import visual_liquidez as vl  # noqa: E402
import visual_eeff as ve  # noqa: E402
from visual_mora import (ENTIDADES, PROJECT_DIR, SUBSYSTEMS, month_key, month_range, read_table)  # noqa: E402

BOLETIN = PROJECT_DIR / "data" / "processed" / "boletin"
PANEL = PROJECT_DIR / "data" / "processed" / "panel_entidad_mes.parquet"
SF2103 = PROJECT_DIR / "data" / "processed" / "sf2103_deudores.parquet"
OUT_DIR = PROJECT_DIR / "data" / "processed" / "indicadores"
OUT_LONG = OUT_DIR / "indicadores_ambito_mes.parquet"
OUT_XLSX = OUT_DIR / "indicadores_ambito_mes.xlsx"
OUT_SCOPES = OUT_DIR / "ambitos.csv"
CATALOG_CSV = PROJECT_DIR / "config" / "indicadores.csv"
CONTROL_CSV = PROJECT_DIR / "data" / "_control" / "indicadores_validacion.csv"

SUBS = [s for s, _, _ in SUBSYSTEMS]
DEPOSIT_TAKERS = list(vl.DEPOSIT_TAKERS)
KEY = ["periodo", "subsistema", "id_entidad"]
MIN_BASE = 1000.0   # miles: bases menores a 1 millón no dan crecimiento ni ratio de liquidez (como mora y liquidez)

GROUPS = [
    ("crec", "Tamaño y crecimiento"),
    ("cal", "Calidad de cartera"),
    ("sol", "Solvencia"),
    ("ren", "Rentabilidad y eficiencia"),
    ("liq", "Liquidez y fondeo"),
    ("est", "Estructura y mercado"),
]

# Cuadros SBS por tema (banca, financieras, CMAC, CRAC, EC), para la columna «cuadros» del catálogo.
CUADROS = {
    "eeff": "Estados financieros (B-2201, B-3101, C-1101, C-2101, C-4103)",
    "sit": "Créditos por tipo y situación (B-2334, B-3220, C-1228, C-2228, C-4223)",
    "mon": "Créditos por tipo, modalidad y moneda (B-2359, B-3272, C-1261, C-2264, C-4253)",
    "cas": "Castigos por tipo de crédito (B-2369, B-3234, C-1253, C-2258, C-4242)",
    "rcg": "Ratio de capital global (B-2402, B-3302, C-1252, C-2257, C-4241)",
    "epe": "Estructura del patrimonio efectivo (B-2370, B-3252, C-1257, C-2262, C-4246)",
    "liq": "Ratios de liquidez (B-2340, B-3250, C-1244, C-2249)",
    "rcl": "Ratio de cobertura de liquidez, Anexo 15-B (B-230809, B-230810, B-230811, B-230812)",
    "rfne": "Ratio de financiación neta estable, Anexo 16-C (B-234021, B-230213, C-120212, B-230820)",
    "rank": "Ranking de créditos, depósitos y patrimonio (B-2332, B-3243, C-1205, C-2205, C-4217)",
    "pg": "Posición global en ME (B-2368, B-3266, C-1260, C-2370, C-4252)",
    "deu": "Deudores por tipo de crédito (B-230803, B-3218, C-1231, C-2231, C-4226); sistema: SF-2103",
}

ALL5 = "Los cinco subsistemas"
DEP4 = ("Banca múltiple, empresas financieras, cajas municipales y cajas rurales (las empresas de créditos no captan "
        "depósitos)")

# Catálogo: clave, grupo, etiqueta, unidad, decimales, sentido, frecuencia, lag, fórmula corta, fórmula detallada,
# cuadros, subsistemas que lo reportan, regla del sistema, nota.
# Regla del sistema: sum = Σ numeradores / Σ denominadores de los subsistemas; flows = serie de rentabilidad;
# sf = SF-2103; share = participación (créditos del ámbito / sistema); none = sin sistema.
CATALOG = [
    ("cred", "crec", "Créditos directos", "S/ mill.", 0, 0, "m", 2,
     "Saldo de créditos directos",
     "Vigentes + refinanciados y reestructurados + atrasados, a fin de mes, en millones de S/. El del BCP incluye "
     "sus sucursales en el exterior.", "sit", SUBS, "sum", ""),
    ("cred_g", "crec", "Crecimiento anual de créditos", "%·a/a", 1, 0, "m", 2,
     "Variación anual a tipo de cambio constante",
     "Créditos(t) / [créditos(t−12) + créditos en ME(t−12) en US$ × (TC(t) − TC(t−12))] − 1, con el tipo de cambio "
     "implícito del cuadro de créditos por moneda. Sin dato si la base es menor que S/ 1 millón o si falta el "
     "saldo en ME.", "mon", SUBS, "sum",
     "El cuadro por moneda existe para la banca desde julio de 2010 y para los demás subsistemas desde setiembre "
     "de 2015: el crecimiento de esos subsistemas y del sistema empieza en setiembre de 2016. No se ajusta por "
     "cambios de perímetro: cuando una entidad entra en un subsistema o sale de él, el crecimiento del subsistema "
     "queda alterado durante 12 meses, hasta que el mes de comparación refleja el mismo perímetro. Casos: banca y "
     "financieras desde enero de 2025, junio de 2025 y junio de 2026 (paso a la banca de Compartamos, Santander "
     "Consumer y Efectiva); banca y cajas rurales desde marzo de 2019 (conversión de Banco Cencosud); cajas "
     "rurales desde agosto de 2023 y abril de 2026 (salidas de CRAC Raíz y CRAC Del Centro); cajas municipales "
     "desde julio de 2024 (salida de CMAC Sullana); financieras desde setiembre de 2024 (salida de Credinka). El "
     "de una entidad que absorbe a otra o recibe su bloque patrimonial incluye la cartera recibida. El del sistema "
     "solo cambia con las entradas y salidas del conjunto de los cinco subsistemas."),
    ("dep", "crec", "Depósitos totales", "S/ mill.", 0, 0, "m", 2,
     "Depósitos del público + depósitos del sistema financiero",
     "Depósitos del público a la vista, de ahorro y a plazo (incluidos los de compensación por tiempo de servicios, "
     "CTS, y los restringidos) + depósitos del sistema financiero y de organismos internacionales, del balance. Es "
     "la definición del ranking de depósitos de la SBS.", "eeff", DEPOSIT_TAKERS, "sum", ""),
    ("dep_g", "crec", "Crecimiento anual de depósitos", "%·a/a", 1, 0, "m", 2,
     "Variación anual a tipo de cambio constante",
     "Depósitos(t) / [depósitos(t−12) + depósitos en ME(t−12) en US$ × (TC(t) − TC(t−12))] − 1, con la apertura en "
     "ME del balance y el tipo de cambio contable de fin de mes (el que la SBS imprime al pie del cuadro B-2201). "
     "Sin dato si la base es menor que S/ 1 millón.", "eeff", DEPOSIT_TAKERS, "sum",
     "Misma convención que el crecimiento de créditos: la base del año anterior se valora al tipo de cambio del "
     "mes."),
    ("act", "crec", "Activo total", "S/ mill.", 0, 0, "m", 2, "Activo total del balance",
     "Total del activo a fin de mes (columna local: el BCP sin sucursales en el exterior).", "eeff", SUBS, "sum", ""),
    ("pat", "crec", "Patrimonio", "S/ mill.", 0, 0, "m", 2, "Patrimonio contable",
     "Patrimonio del balance a fin de mes.", "eeff", SUBS, "sum", ""),
    ("deud", "crec", "Número de deudores", "miles", 1, 0, "m", 3, "Deudores con créditos directos",
     "Entidad: total del cuadro de deudores. Subsistema: fila del total del cuadro, que cuenta una sola vez a quien "
     "tiene créditos en varias entidades del subsistema. Sistema: deudores únicos del cuadro SF-2103 («Empresas de "
     "Operaciones Múltiples»), trimestral desde diciembre de 2019. Los deudores no se suman entre entidades ni entre "
     "subsistemas.", "deu", SUBS, "sf",
     "El dato del sistema es trimestral (marzo, junio, setiembre y diciembre) y sale con más rezago. Los cuadros "
     "de deudores por entidad empiezan en diciembre de 2010."),
    ("part_sub", "crec", "Participación en créditos del subsistema", "%", 2, 0, "m", 2,
     "Créditos de la entidad / créditos del subsistema",
     "Créditos directos de la entidad / suma de los créditos de las entidades de su subsistema ese mes.", "sit",
     SUBS, "none", ""),
    ("part_sis", "crec", "Participación en créditos del sistema", "%", 2, 0, "m", 2,
     "Créditos del ámbito / créditos del sistema",
     "Créditos directos de la entidad o del subsistema / créditos de los cinco subsistemas.", "sit", SUBS, "none",
     ""),
    # Calidad de cartera
    ("mora", "cal", "Morosidad", "%", 2, -1, "m", 2, "Créditos atrasados / créditos directos",
     "Créditos atrasados (vencidos + en cobranza judicial) / créditos directos, a fin de mes. Criterio de la SBS "
     "para considerar vencido un crédito: más de 15 días de atraso en los créditos corporativos, a grandes empresas "
     "y a medianas empresas; más de 30 días en los créditos a pequeñas empresas y a microempresas; en los de "
     "consumo e hipotecarios, la cuota a los 30 días de atraso y todo el saldo a los 90.",
     "sit", SUBS, "sum", ""),
    ("car", "cal", "Cartera de alto riesgo", "%", 2, -1, "m", 2,
     "(Atrasados + refinanciados y reestructurados) / directos",
     "(Créditos atrasados + refinanciados + reestructurados) / créditos directos, a fin de mes.", "sit", SUBS, "sum", ""),
    ("mora_aj", "cal", "Mora ajustada por castigos", "%", 2, -1, "m", 2,
     "(Atrasados + castigos 12 m) / (directos + castigos 12 m)",
     "(Créditos atrasados + castigos de los últimos 12 meses) / (créditos directos + castigos de los últimos 12 "
     "meses). Hasta 2015 la SBS publicaba los castigos cada trimestre, y desde 2016, cada mes: como los castigos se "
     "suman en 12 meses, hasta setiembre de 2016 solo hay dato en marzo, junio, setiembre y diciembre, y desde "
     "diciembre de 2016 hay dato cada mes.", "cas", SUBS, "sum",
     "Trimestral hasta setiembre de 2016 (solo marzo, junio, setiembre y diciembre) y mensual desde diciembre de "
     "2016. Subsistema: todos los castigos registrados en él en los 12 meses, incluidos los de entidades que ya "
     "salieron; el sistema suma los de los cinco subsistemas. Entidad: sus castigos de los 12 meses, incluidos los "
     "registrados antes de un cambio de subsistema. No es la «cartera atrasada ajustada» de los indicadores de la "
     "SBS, que suma además las transferencias de cartera atrasada del año."),
    ("refi", "cal", "Refinanciados y reestructurados", "%", 2, -1, "m", 2,
     "Refinanciados y reestructurados / directos",
     "(Créditos refinanciados + reestructurados) / créditos directos, a fin de mes.", "sit", SUBS, "sum", ""),
    ("cob", "cal", "Cobertura de cartera atrasada", "%", 1, 1, "m", 2,
     "Provisiones de créditos / créditos atrasados",
     "Provisiones para créditos directos (cuenta correctora del balance) / créditos atrasados del balance.", "eeff",
     SUBS, "sum",
     "Se usa el balance local del BCP (sin sucursales en el exterior). La SBS calcula el indicador del BCP y el de "
     "la banca múltiple con las sucursales, así que en esos dos casos el valor difiere del publicado."),
    ("cob_car", "cal", "Cobertura de cartera de alto riesgo", "%", 1, 1, "m", 2,
     "Provisiones / (atrasados + refinanciados y reestructurados)",
     "Provisiones para créditos directos / (créditos atrasados + refinanciados y reestructurados), del balance.",
     "eeff", SUBS, "sum", ""),
    ("costo_riesgo", "cal", "Costo del riesgo", "%", 2, -1, "m", 2,
     "Gasto de provisiones 12 m / créditos promedio",
     "Provisiones para créditos directos del estado de resultados en 12 meses (neto de reversiones) / promedio de "
     "los 12 saldos de fin de mes de los créditos directos del balance.",
     "eeff", SUBS, "flows", "Desde julio de 2011 (necesita 12 meses de datos)."),
    ("castigos", "cal", "Castigos", "%", 2, -1, "m", 2, "Castigos 12 m / créditos promedio",
     "Castigos de los últimos 12 meses / promedio de los 12 saldos de fin de mes de los créditos directos "
     "(del cuadro de créditos por tipo y situación).", "cas", SUBS, "sum",
     "Trimestral hasta setiembre de 2016 (solo marzo, junio, setiembre y diciembre) y mensual desde diciembre de "
     "2016, como la mora ajustada; misma regla de castigos."),
    # Solvencia
    ("rcg", "sol", "Ratio de capital global", "%", 2, 1, "m", 2,
     "Patrimonio efectivo / activos ponderados por riesgo (APR)",
     "Patrimonio efectivo (PE) / activos y contingentes ponderados por riesgo de crédito, de mercado y operacional "
     "(APR). Desde junio de 2023 la SBS no publica el PE en el cuadro del ratio de capital global: se toma el total "
     "del cuadro de estructura del patrimonio efectivo, y en pocos casos el ratio difiere del publicado. Antes de "
     "abril de 2021 la SBS no publicaba los APR: se obtienen como PE × 100 / ratio de capital global publicado. "
     "Agregados: Σ PE / Σ APR.",
     "rcg", SUBS, "sum",
     "En todos los subsistemas, la SBS publica el cuadro del ratio de capital global unas cuatro semanas después "
     "del balance, así que el ratio suele tener un mes menos de datos que los créditos."),
    ("cet1", "sol", "Capital ordinario de nivel 1", "%", 2, 1, "m", 2, "Capital ordinario de nivel 1 (CET1) / APR",
     "Capital ordinario de nivel 1 / APR. Agregados: Σ (ratio × APR) / Σ APR.", "rcg", SUBS, "sum",
     "Publicado desde junio de 2023 (estructura del patrimonio efectivo del D. Leg. N.º 1531)."),
    ("colchon", "sol", "Colchón sobre el mínimo legal", "pp", 2, 1, "m", 2,
     "Ratio de capital global − mínimo legal vigente",
     "Ratio de capital global − límite global vigente ese mes: 9.8% hasta junio de 2011 (D. Leg. N.º 1028); 10% de "
     "julio de 2011 a marzo de 2021; 8% de abril de 2021 a agosto de 2022 (Decreto de Urgencia N.º 037-2021 y "
     "D. U. N.º 003-2022); 8.5% desde setiembre de 2022 (D. U. N.º 003-2022); 9% desde abril de 2023, 9.5% desde "
     "setiembre de 2024 y 10% desde marzo de 2025 (calendario de la Res. SBS N.º 3952-2022, modificado por las "
     "Res. SBS N.º 2192-2023 y N.º 274-2024).", "rcg", SUBS, "sum",
     "No descuenta los colchones ni los requerimientos adicionales de cada entidad, que no se publican."),
    ("pat_act", "sol", "Patrimonio / activo", "%", 1, 1, "m", 2, "Patrimonio / activo total",
     "Patrimonio contable / activo total, a fin de mes.", "eeff", SUBS, "sum", ""),
    ("lev", "sol", "Apalancamiento contable", "veces", 2, -1, "m", 2, "Pasivo / (capital social + reservas)",
     "Pasivo total / (capital social + reservas), en veces: el indicador «Pasivo total / capital social y reservas» "
     "de los cuadros de indicadores financieros de la SBS.", "eeff", SUBS, "sum",
     "Se usa el balance local del BCP (sin sucursales en el exterior). La SBS calcula el indicador del BCP y el de "
     "la banca múltiple con las sucursales, así que en esos dos casos el valor difiere del publicado."),
    ("exp_pat", "sol", "Cartera atrasada neta / patrimonio", "%", 1, -1, "m", 2,
     "(Atrasados − provisiones) / patrimonio",
     "(Créditos atrasados − provisiones para créditos directos) / patrimonio, del balance. Es negativo si las "
     "provisiones superan a la cartera atrasada.", "eeff", SUBS, "sum",
     "Negativo cuando las provisiones superan a la cartera atrasada: cuanto más negativo, más cubierta está la "
     "cartera atrasada con provisiones."),
    # Rentabilidad y eficiencia
    ("roe", "ren", "ROE", "%", 2, 1, "m", 2, "Utilidad 12 m / patrimonio promedio",
     "Utilidad neta de 12 meses / promedio de los 12 saldos de fin de mes del patrimonio (t−11 … t). Flujo de 12 "
     "meses = acumulado del mes + acumulado de diciembre del año anterior − acumulado del mismo mes del año "
     "anterior.",
     "eeff", SUBS, "flows", "Sin dato si el patrimonio promedio no es positivo."),
    ("roa", "ren", "ROA", "%", 2, 1, "m", 2, "Utilidad 12 m / activo promedio",
     "Utilidad neta de 12 meses / promedio de los 12 saldos de fin de mes del activo.", "eeff", SUBS, "flows", ""),
    ("util", "ren", "Utilidad neta 12 meses", "S/ mill.", 0, 1, "m", 2, "Utilidad neta de los últimos 12 meses",
     "Resultado neto del ejercicio llevado a 12 meses (acumulado del mes + acumulado de diciembre del año anterior "
     "− acumulado del mismo mes del año anterior), en millones de S/.", "eeff", SUBS, "flows", ""),
    ("mfb_act", "ren", "Margen financiero bruto / activo", "%", 2, 1, "m", 2,
     "(Ingresos − gastos financieros) 12 m / activo promedio",
     "Margen financiero bruto (ingresos financieros − gastos financieros) de 12 meses / activo promedio.", "eeff",
     SUBS, "flows", ""),
    ("mfb_ing", "ren", "Margen financiero bruto / ingresos financieros", "%", 1, 1, "m", 2,
     "Margen financiero bruto 12 m / ingresos financieros 12 m",
     "(Ingresos financieros − gastos financieros) / ingresos financieros, ambos de 12 meses.", "eeff", SUBS,
     "flows", ""),
    ("efic", "ren", "Eficiencia", "%", 1, -1, "m", 2, "Gastos de operación / margen financiero total",
     "Gastos de operación (administrativos + depreciación + amortización) / (margen financiero bruto + ingresos "
     "por servicios − gastos por servicios), de 12 meses.", "eeff", SUBS,
     "flows",
     "Reproduce el indicador que publica la SBS para las cajas y las empresas de créditos. El de la banca y las "
     "financieras lo publica con valores acumulados en el año, así que en esos casos difiere."),
    ("gadm_cred", "ren", "Gastos administrativos / créditos", "%", 2, -1, "m", 2,
     "Gastos administrativos 12 m / créditos promedio",
     "Gastos administrativos de 12 meses / promedio de los 12 saldos de fin de mes de los créditos directos del "
     "balance.",
     "eeff", SUBS, "flows",
     "No es el indicador que publica la SBS para las cajas y las empresas de créditos, que divide entre el promedio "
     "de los créditos directos e indirectos."),
    ("prov_mfb", "ren", "Provisiones / margen financiero bruto", "%", 1, -1, "m", 2,
     "Gasto de provisiones 12 m / margen financiero bruto 12 m",
     "Provisiones para créditos directos de 12 meses / margen financiero bruto de 12 meses.", "eeff", SUBS,
     "flows", "Sin dato si el margen no es positivo."),
    # Liquidez y fondeo
    ("rl_mn", "liq", "Ratio de liquidez MN", "%", 1, 1, "m", 2,
     "Activos líquidos / pasivos de corto plazo en moneda nacional (MN)",
     "Activos líquidos / pasivos de corto plazo en moneda nacional (promedio mensual de saldos diarios, "
     "Anexo 15-C). Agregados: Σ activos líquidos / Σ pasivos de corto plazo.", "liq", DEPOSIT_TAKERS, "sum",
     "Mínimo 8% (10% si los 20 mayores depositantes superan el 25% de los depósitos, dato que no se publica; "
     "Res. SBS N.º 4221-2023, art. 45). Financieras desde octubre de 2010."),
    ("rl_me", "liq", "Ratio de liquidez ME", "%", 1, 1, "m", 2,
     "Activos líquidos / pasivos de corto plazo en moneda extranjera (ME)",
     "Activos líquidos / pasivos de corto plazo en moneda extranjera (promedio mensual de saldos diarios, "
     "Anexo 15-C). Agregados: Σ activos líquidos / Σ pasivos de corto plazo.", "liq", DEPOSIT_TAKERS, "sum",
     "Mínimo 20% (25% con la misma concentración de depositantes; Res. SBS N.º 4221-2023, art. 45). Financieras "
     "desde octubre de 2010."),
    ("rcl", "liq", "Ratio de cobertura de liquidez", "%", 1, 1, "t", 6, "RCL total publicado (trimestral)",
     "Ratio de cobertura de liquidez total publicado por la SBS: promedio de los ratios diarios del trimestre "
     "(Anexo 15-B), en el mes de cierre del trimestre.", "rcl", DEPOSIT_TAKERS, "none",
     "No se agrega: el publicado es un promedio de ratios diarios y no hay RCL del sistema. No hay total de las "
     "cajas municipales del primer trimestre de 2024. Sale con unos tres meses de rezago. Mínimo 100% en el total "
     "(Res. SBS N.º 4221-2023, art. 45)."),
    ("rfne", "liq", "Ratio de financiación neta estable", "%", 1, 1, "m", 2,
     "Financiación estable disponible / requerida",
     "Financiación estable disponible / financiación estable requerida, con saldos de fin de mes (Anexo 16-C), en %. "
     "Agregados: Σ disponible / Σ requerida.", "rfne", DEPOSIT_TAKERS, "sum",
     "La SBS lo publica desde diciembre de 2025, en veces (aquí, en %). No publicó el de agosto de 2026 (sí el de "
     "setiembre): con ese corte se muestra el de julio de 2026. Mínimo 80% desde diciembre de 2024, 90% desde "
     "diciembre de 2025 y 100% desde diciembre de 2026 (Res. SBS N.º 4221-2023). Las empresas de créditos no tienen "
     "límite y la SBS no publica su ratio."),
    ("disp_act", "liq", "Disponible / activo", "%", 1, 1, "m", 2, "Disponible / activo total",
     "Disponible del balance (caja, bancos y corresponsales, canje y otros) / activo total.", "eeff", SUBS, "sum",
     ""),
    ("cred_dep", "liq", "Créditos / depósitos", "%", 1, -1, "m", 2, "Créditos directos / depósitos totales",
     "Créditos directos del cuadro de ranking / depósitos totales del balance.", "rank", DEPOSIT_TAKERS, "sum",
     "El sistema suma solo los cuatro subsistemas que captan depósitos, en el numerador y en el denominador."),
    ("dep_pas", "liq", "Depósitos / pasivo", "%", 1, 1, "m", 2, "Depósitos totales / pasivo total",
     "Depósitos totales (definición del ranking) / pasivo total.", "eeff", DEPOSIT_TAKERS, "sum", ""),
    ("adeu_pas", "liq", "Adeudos / pasivo", "%", 1, -1, "m", 2, "Adeudos y obligaciones financieras / pasivo",
     "Adeudos y obligaciones financieras del balance / pasivo total. No incluye los valores, títulos y obligaciones "
     "en circulación (bonos) ni los depósitos del sistema financiero.", "eeff", SUBS, "sum", ""),
    # Estructura y mercado
    ("dol_cred", "est", "Dolarización de créditos", "%", 1, -1, "m", 2, "Créditos en ME / créditos",
     "Créditos brutos en ME (vigentes + refinanciados y reestructurados + atrasados, en soles) / créditos brutos, "
     "del balance.", "eeff", SUBS, "sum",
     "Se toma del balance, que tiene la apertura por moneda en todos los subsistemas desde julio de 2010 (en el "
     "BCP, sin sucursales en el exterior), y no del cuadro de créditos por moneda, que fuera de la banca empieza en "
     "setiembre de 2015."),
    ("dol_dep", "est", "Dolarización de depósitos", "%", 1, -1, "m", 2, "Depósitos en ME / depósitos",
     "Depósitos totales en ME / depósitos totales, del balance.", "eeff",
     DEPOSIT_TAKERS, "sum", ""),
    ("pg_pe", "est", "Posición global en ME / patrimonio efectivo", "%", 1, 0, "m", 2,
     "Posición global en ME / patrimonio efectivo",
     "Posición global en ME (posición de cambio del balance + derivados + delta de opciones; positiva = "
     "sobrecompra) / patrimonio efectivo del mismo mes.", "pg", SUBS, "sum",
     "Financieras desde mayo de 2011; cajas municipales, cajas rurales y empresas de créditos desde julio de 2014 "
     "(antes no hay cuadro): el sistema empieza en julio de 2014. Sale con el rezago del cuadro del ratio de "
     "capital global."),
    ("mix_emp", "est", "Cartera empresarial (corporativa, grande y mediana)", "%", 1, 0, "m", 2,
     "(Corporativos + grandes + medianas empresas) / directos",
     "Créditos corporativos, a grandes y a medianas empresas / créditos directos.", "sit", SUBS, "sum",
     "Desde octubre de 2010 (antes la SBS publicaba una sola columna, «empresariales»). Desde octubre de 2024 la "
     "Res. SBS N.º 2368-2023 separa las medianas empresas de las pequeñas y microempresas por sus ventas anuales "
     "(S/ 5 millones) y ya no por su deuda en el sistema (S/ 300 mil): la composición no es del todo comparable "
     "antes y después."),
    ("mix_mype", "est", "Cartera MYPE (pequeña y micro)", "%", 1, 0, "m", 2,
     "(Pequeñas empresas + microempresas) / directos", "Créditos a pequeñas empresas y microempresas / créditos "
     "directos.", "sit", SUBS, "sum",
     "Desde octubre de 2010. Desde octubre de 2024 la Res. SBS N.º 2368-2023 cambia el criterio que separa a las "
     "medianas empresas de las pequeñas y microempresas: la composición no es del todo comparable antes y después."),
    ("mix_cons", "est", "Cartera de consumo", "%", 1, 0, "m", 2, "Consumo / directos",
     "Créditos de consumo (revolvente y no revolvente) / créditos directos.", "sit", SUBS, "sum", ""),
    ("mix_hip", "est", "Cartera hipotecaria", "%", 1, 0, "m", 2, "Hipotecarios para vivienda / directos",
     "Créditos hipotecarios para vivienda / créditos directos.", "sit", SUBS, "sum", ""),
]
CAT = {r[0]: r for r in CATALOG}
FLOW_INDS = [r[0] for r in CATALOG if r[12] == "flows"]
PCT_SCALE = {"%": 100.0, "pp": 100.0, "%·a/a": 100.0, "veces": 1.0}


# ---------------------------------------------------------------- utilidades
def to_t(p):
    return (np.asarray(p) // 100) * 12 + np.asarray(p) % 100 - 1


def from_t(t):
    t = np.asarray(t)
    return (t // 12) * 100 + t % 12 + 1


def safe_div(a: pd.Series, b: pd.Series, positive: bool = True, min_abs: float = 0.0) -> pd.Series:
    """a / b con NaN si b no es positivo (o no supera `min_abs`)."""
    ok = b > min_abs if positive else b.abs() > min_abs
    return (a / b.where(ok)).replace([np.inf, -np.inf], np.nan)


def strkey(df: pd.DataFrame) -> pd.DataFrame:
    """subsistema e id_entidad como texto (las tablas los traen como categorías)."""
    df = df.copy()
    for c in ("subsistema", "id_entidad"):
        if c in df:
            df[c] = df[c].astype(str)
    return df


# ---------------------------------------------------------------- carga de componentes por entidad
STOCK_COLS = ["ct", "ca", "cref", "emp", "mype", "cons", "hip", "meu",
              "act", "pat", "pas", "disp", "csr", "prov", "batr", "bref", "bcd", "bcd_me",
              "dep", "dme", "ad", "rkcr", "alN", "pcN", "alE", "pcE", "fed", "fer", "rcl",
              "pe", "apr", "c1", "pg", "deu", "cas_sub"]


def load_entity_components() -> tuple[pd.DataFrame, dict]:
    """Componentes de saldo por (periodo, subsistema, entidad), en miles de S/ (meu en miles de US$; deu en
    número). Devuelve además insumos auxiliares (tipo de cambio, castigos, totales publicados)."""
    aux = {}
    # --- mora: saldos por tipo y situación
    print("Saldos por tipo y situación, moneda, castigos y deudores (visual_mora)...")
    stocks = strkey(vm.load_stocks())
    piv = stocks.pivot_table(index=KEY, columns="tipo", values=["tot", "atr", "ref"], aggfunc="sum")
    f = pd.DataFrame(index=piv.index)
    f["ct"], f["ca"], f["cref"] = piv[("tot", "total")], piv[("atr", "total")], piv[("ref", "total")]
    tot = lambda t: piv[("tot", t)] if ("tot", t) in piv.columns else pd.Series(np.nan, index=piv.index)  # noqa: E731
    big = tot("corporativos").fillna(0) + tot("grandes_empresas").fillna(0) + tot("medianas_empresas").fillna(0)
    small = tot("pequenas_empresas").fillna(0) + tot("microempresas").fillna(0)
    split = f.index.get_level_values("periodo") >= vm.FIRST_BUSINESS_SPLIT
    f["emp"] = big.where(split)
    f["mype"] = small.where(split)
    f["cons"] = tot("consumo").fillna(0)
    f["hip"] = tot("hipotecarios").fillna(0)
    meu, tc = vm.load_currency()
    meu = strkey(meu)
    f["meu"] = meu[meu["tipo"] == "total"].set_index(KEY)["meu"]
    aux["tc"] = tc
    # Castigos de 12 meses por (subsistema, entidad), como el tablero de colocaciones (para los subsistemas).
    cas = strkey(vm.load_writeoffs(stocks))
    cas = cas[cas["tipo"] == "total"].set_index(KEY)["cas"]
    f["cas_sub"] = cas
    # Para los subsistemas: todos los castigos registrados en el subsistema en los últimos 12 meses, también los
    # de entidades que ya salieron (traspaso, absorción). Cruzarlos con los saldos del mes los perdía
    # (auditoría 2026-10-31: financieras ago-2026 sin los castigos de Efectiva).
    aux["cas_sub_tot"] = cas.groupby(level=["periodo", "subsistema"]).sum()
    aux["stocks_keys"] = f.index
    deu_ent, deu_sub, deu_sys = vm.load_debtors()
    deu_ent, deu_sub = strkey(deu_ent), strkey(deu_sub)
    f["deu"] = deu_ent[deu_ent["tipo"] == "total"].set_index(KEY)["deu"]
    aux["deu_sub"] = deu_sub[deu_sub["tipo"] == "total"].set_index(["periodo", "subsistema"])["deu"]
    aux["deu_sys"] = deu_sys

    # --- estados financieros (columna local)
    print("Estados financieros (visual_rentabilidad)...")
    w = vr.load_statements()
    aux["w"] = w
    kept = pd.MultiIndex.from_frame(w[KEY].astype({"subsistema": str}))
    vars_ = ["total_activo", "patrimonio", "total_pasivo", "disponible", "patrimonio_capital_social",
             "patrimonio_reservas", "creditos_provisiones", "creditos_atrasados",
             "creditos_refinanciados_reestructurados", "creditos_vigentes"]
    e = read_table(BOLETIN / "estados-financieros.parquet", filters=[("variable", "in", vars_)],
                   columns=KEY + ["es_total", "variable", "apertura", "valor"])
    e = e[~e["es_total"] & e["apertura"].isin(["total", "me"])]
    e = e.assign(subsistema=e["subsistema"].astype(str), k=e["variable"].astype(str) + "|" + e["apertura"].astype(str))
    b = e.pivot_table(index=KEY, columns="k", values="valor", aggfunc="first")
    b = b[b.index.isin(kept)]   # sin filas en cero ni cifras repetidas (mismo criterio que rentabilidad)
    g = lambda c: b[c] if c in b.columns else pd.Series(np.nan, index=b.index)  # noqa: E731
    bal = pd.DataFrame(index=b.index)
    bal["act"] = g("total_activo|total")
    bal["pat"] = g("patrimonio|total")
    bal["pas"] = g("total_pasivo|total")
    bal["disp"] = g("disponible|total")
    bal["csr"] = g("patrimonio_capital_social|total").fillna(0) + g("patrimonio_reservas|total").fillna(0)
    bal["prov"] = -g("creditos_provisiones|total")          # viene negativa en el balance
    bal["batr"] = g("creditos_atrasados|total")
    bal["bref"] = g("creditos_refinanciados_reestructurados|total").fillna(0)
    bal["bcd"] = g("creditos_vigentes|total").fillna(0) + bal["bref"] + bal["batr"].fillna(0)
    bal["bcd_me"] = (g("creditos_vigentes|me").fillna(0) + g("creditos_refinanciados_reestructurados|me").fillna(0)
                     + g("creditos_atrasados|me").fillna(0))
    neg = (bal["prov"] < 0).sum()
    if neg:
        print(f"  AVISO: {neg} entidad-mes con provisiones de créditos positivas en el balance (signo invertido)")
    f = f.join(bal, how="outer")

    # --- liquidez y fondeo
    print("Liquidez y fondeo (visual_liquidez)...")
    lq, pub = vl.build_frame()
    lq = lq.assign(subsistema=lq["subsistema"].astype(str)).set_index(KEY)
    lqd = pd.DataFrame(index=lq.index)
    lqd["dep"] = lq[["dv", "da", "dp", "dc", "dsf"]].sum(axis=1, min_count=1)
    lqd["dme"] = lq["dme"].where(lqd["dep"].notna())
    lqd["ad"] = lq["ad"]
    lqd["rkcr"] = lq["cr"]
    for c in ["alN", "pcN", "alE", "pcE", "fed", "fer", "rcl"]:
        lqd[c] = lq[c] if c in lq else np.nan
    lcr = pub["lcr"].reset_index()
    lcr["subsistema"] = lcr["subsistema"].astype(str)
    aux["rcl_sub"] = lcr.set_index(["periodo", "subsistema"])["rcl"]
    f = f.join(lqd, how="outer")

    # --- capital
    print("Capital (visual_solvencia)...")
    sv = vs.build_frame()
    sv = sv.assign(subsistema=sv["subsistema"].astype(str)).set_index(KEY)
    f = f.join(sv[["pe", "apr", "c1"]], how="outer")

    # --- posición global (panel)
    pn = read_table(PANEL, columns=KEY + ["posicion_global_me"])
    pn = pn[pn["id_entidad"] != "_total"].assign(subsistema=lambda x: x["subsistema"].astype(str)).set_index(KEY)
    f = f.join(pn["posicion_global_me"].rename("pg"), how="left")

    f = f.reindex(columns=STOCK_COLS)
    f.index = f.index.set_names(KEY)
    f = f.reset_index()
    f["subsistema"] = f["subsistema"].astype(str)
    # Una entidad no puede estar en dos subsistemas el mismo mes: se queda donde están sus créditos (o su activo).
    dup = f.duplicated(["periodo", "id_entidad"], keep=False)
    if dup.any():
        d = f[dup].assign(_w=f.loc[dup, "ct"].fillna(-1) * 1e6 + f.loc[dup, "act"].fillna(0))
        drop = d.sort_values("_w").duplicated(["periodo", "id_entidad"], keep="last")
        dropped = d[drop]
        print(f"  Entidad en dos subsistemas el mismo mes (se queda donde están sus créditos): "
              + ", ".join(f"{r.id_entidad} {r.periodo} (se descarta {r.subsistema})" for r in dropped.itertuples()))
        f = f.drop(index=dropped.index)
    # Filas sin ningún dato útil, y entidades absorbidas o liquidadas que la SBS sigue listando en ceros (CRAC Del
    # Centro desde 2026-04: créditos, depósitos y deudores en 0, sin balance). Se conservan las que tienen activo
    # aunque no tengan créditos (Deutsche Bank, Edyficar residual 2015).
    f = f[f[["ct", "act", "pe", "dep", "alN"]].notna().any(axis=1)]
    zero = ((f["ct"].fillna(0) == 0) & (f["act"].fillna(0) == 0) & (f["dep"].fillna(0) == 0)
            & f["pe"].isna() & f["alN"].isna())
    if zero.any():
        for ent, g in f[zero].groupby("id_entidad"):
            print(f"  Filas en cero (se omiten): {ent}, {len(g)} meses ({g['periodo'].min()}-{g['periodo'].max()})")
        f = f[~zero]
    return f.reset_index(drop=True), aux


# ---------------------------------------------------------------- series por ámbito
def flows_by_period(r: pd.DataFrame) -> pd.DataFrame:
    """Salida de `rolling_block` (índice t) → índice periodo, con las columnas que usa el catálogo. Antes del
    primer mes con 12 meses de historia (2011-07) no hay flujos: se descarta el diciembre de 2010 suelto (el
    acumulado anual), como en el tablero de rentabilidad, que empieza en 2011-07."""
    out = r[["if", "gf", "pr", "si", "sg", "ga", "da", "rn", "A", "P", "C"]].copy()
    out.index = from_t(out.index)
    out.index.name = "periodo"
    first = month_range(vm.START_PERIOD, 210012)[12]
    out = out[out.index >= first]
    return out.rename(columns={"if": "if_"})


def writeoffs_by_entity(f: pd.DataFrame, months: list[int]) -> pd.DataFrame:
    """Castigos de 12 meses por `id_entidad` (aunque cambie de subsistema), en los meses de `adj_months`."""
    c = read_table(BOLETIN / "castigos-tipo-credito.parquet")
    c = c[(~c["es_total"]) & c["variable"].isin(["castigos_flujo_mensual", "castigos_flujo_trimestral"])
          & (c["apertura"] == "total")]
    c = c.assign(subsistema=c["subsistema"].astype(str))
    where = f.loc[f["ct"].notna(), KEY]
    c = c.merge(where, on=KEY, how="inner")       # Santander Consumer 2025-04: la fila de banca se descarta
    last = months[-1]
    grid = month_range(vm.writeoff_start(), last)
    flows = c.pivot_table(index="id_entidad", columns="periodo", values="valor", aggfunc="sum")
    flows = flows.reindex(columns=grid).fillna(0.0)
    roll = flows.T.rolling(12, min_periods=12).sum()
    valid = vm.adj_months(last)
    roll = roll.loc[[m for m in roll.index if m in set(valid)]]
    return roll   # índice periodo, columnas id_entidad


def rolling_mean12(s: pd.Series) -> pd.Series:
    return s.rolling(12, min_periods=12).mean()


def growth_parts(level: pd.Series, me_usd: pd.Series, fx: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Numerador (saldo t) y base a tipo de cambio constante (saldo t−12 + ME t−12 en US$ × ΔTC), sobre un
    índice mensual completo. Base vacía si falta la ME de hace 12 meses o es menor a MIN_BASE."""
    prev, prev_me = level.shift(12), me_usd.shift(12)
    base = prev + prev_me * (fx - fx.shift(12))
    base = base.where(prev.notna() & prev_me.notna() & (base >= MIN_BASE))
    return level.where(base.notna()), base


def indicators(c: pd.DataFrame, lg: pd.Series, tc: pd.Series, tcc: pd.Series) -> dict[str, tuple[pd.Series, pd.Series]]:
    """{clave: (numerador, denominador)} sobre el índice mensual de `c` (componentes del ámbito). El valor es
    num / den en la escala de la unidad (ver `finish`). Para montos el denominador es None."""
    o: dict[str, tuple] = {}
    ct = c["ct"]
    o["cred"] = (ct, None)
    o["cred_g"] = growth_parts(ct, c["meu"], tc)
    dme_usd = c["dme"] / tcc
    o["dep"] = (c["dep"], None)
    o["dep_g"] = growth_parts(c["dep"], dme_usd, tcc)
    o["act"] = (c["act"], None)
    o["pat"] = (c["pat"], None)
    o["deud"] = (c["deu"], None)
    pos = ct.where(ct > 0)
    o["mora"] = (c["ca"], pos)
    o["car"] = (c["ca"] + c["cref"], pos)
    o["refi"] = (c["cref"], pos)
    cas = c["cas"]
    o["mora_aj"] = ((c["ca"] + cas).where(cas.notna() & pos.notna()), (ct + cas).where(cas.notna() & pos.notna()))
    o["cob"] = (c["prov"], c["batr"].where(c["batr"] > 0))
    car_b = c["batr"] + c["bref"]
    o["cob_car"] = (c["prov"], car_b.where(car_b > 0))
    C = c["C"].where(c["C"] > 0)
    o["costo_riesgo"] = (c["pr"].where(C.notna()), C)
    cavg = c["ctavg"].where(c["ctavg"] > 0)
    o["castigos"] = (cas.where(cavg.notna()), cavg.where(cas.notna()))
    apr = c["apr"].where(c["apr"] > 0)
    o["rcg"] = (c["pe"].where(apr.notna()), apr.where(c["pe"].notna()))
    o["cet1"] = (c["c1"].where(apr.notna()), apr.where(c["c1"].notna()))
    o["colchon"] = ((c["pe"] - lg * c["apr"] / 100).where(apr.notna()), apr.where(c["pe"].notna()))
    act = c["act"].where(c["act"] > 0)
    o["pat_act"] = (c["pat"].where(act.notna()), act.where(c["pat"].notna()))
    o["lev"] = (c["pas"], c["csr"].where(c["csr"] > 0))
    pat = c["pat"].where(c["pat"] > 0)
    o["exp_pat"] = ((c["batr"] - c["prov"]).where(pat.notna()), pat.where(c["batr"].notna() & c["prov"].notna()))
    P, A = c["P"].where(c["P"] > 0), c["A"].where(c["A"] > 0)
    mfb = c["if_"] - c["gf"]
    o["roe"] = (c["rn"].where(P.notna()), P.where(c["rn"].notna()))
    o["roa"] = (c["rn"].where(A.notna()), A.where(c["rn"].notna()))
    o["util"] = (c["rn"], None)
    o["mfb_act"] = (mfb.where(A.notna()), A.where(mfb.notna()))
    ifp = c["if_"].where(c["if_"] > 0)
    o["mfb_ing"] = (mfb.where(ifp.notna()), ifp.where(mfb.notna()))
    mft = mfb + c["si"] - c["sg"]
    mftp = mft.where(mft > 0)
    gop = c["ga"] + c["da"]
    o["efic"] = (gop.where(mftp.notna()), mftp.where(gop.notna()))
    o["gadm_cred"] = (c["ga"].where(C.notna()), C.where(c["ga"].notna()))
    mfbp = mfb.where(mfb > 0)
    o["prov_mfb"] = (c["pr"].where(mfbp.notna()), mfbp.where(c["pr"].notna()))
    pcn = c["pcN"].where(c["pcN"] >= MIN_BASE)
    pce = c["pcE"].where(c["pcE"] >= MIN_BASE)
    o["rl_mn"] = (c["alN"].where(pcn.notna()), pcn.where(c["alN"].notna()))
    o["rl_me"] = (c["alE"].where(pce.notna()), pce.where(c["alE"].notna()))
    o["rcl"] = (c["rcl"], None)
    fer = c["fer"].where(c["fer"] > 0)
    o["rfne"] = (c["fed"].where(fer.notna()), fer.where(c["fed"].notna()))
    o["disp_act"] = (c["disp"].where(act.notna()), act.where(c["disp"].notna()))
    dep = c["dep"].where(c["dep"] >= MIN_BASE)
    o["cred_dep"] = (c["rkcr"].where(dep.notna()), dep.where(c["rkcr"].notna()))
    pas = c["pas"].where(c["pas"] > 0)
    o["dep_pas"] = (c["dep"].where(pas.notna()), pas.where(c["dep"].notna()))
    o["adeu_pas"] = (c["ad"].where(pas.notna()), pas.where(c["ad"].notna()))
    bcd = c["bcd"].where(c["bcd"] > 0)
    o["dol_cred"] = (c["bcd_me"].where(bcd.notna()), bcd.where(c["bcd_me"].notna()))
    depp = c["dep"].where(c["dep"] > 0)
    o["dol_dep"] = (c["dme"].where(depp.notna()), depp.where(c["dme"].notna()))
    pe = c["pe"].where(c["pe"] > 0)
    o["pg_pe"] = (c["pg"].where(pe.notna()), pe.where(c["pg"].notna()))
    for k, col in (("mix_emp", "emp"), ("mix_mype", "mype"), ("mix_cons", "cons"), ("mix_hip", "hip")):
        o[k] = (c[col].where(pos.notna()), pos.where(c[col].notna()))
    return o


def finish(k: str, num: pd.Series, den) -> pd.DataFrame:
    """Valor en la unidad de la página. Montos en millones de S/ (deudores en miles)."""
    u = CAT[k][3]
    if den is None:
        if u == "S/ mill.":
            val = num / 1000
        elif u == "miles":
            val = num / 1000
        else:
            val = num
        den_s = pd.Series(np.nan, index=num.index)
    else:
        den_s = den
        ok = num.notna() & den.notna() & (den != 0)
        val = (num / den.where(ok))
        if k in ("cred_g", "dep_g"):
            val = 100 * (val - 1)
        else:
            val = val * PCT_SCALE[u]
    df = pd.DataFrame({"valor": val, "numerador": num, "denominador": den_s})
    df.loc[df["valor"].isna(), ["numerador", "denominador"]] = np.nan
    return df.replace([np.inf, -np.inf], np.nan)


# ---------------------------------------------------------------- armado
def build() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    f, aux = load_entity_components()
    months = month_range(int(f["periodo"].min()), int(f["periodo"].max()))
    midx = pd.Index(months, name="periodo")
    tc = aux["tc"].reindex(midx)
    fx = ve.load_fx_rates(months)
    tcc = pd.Series(fx).reindex(midx)
    lg = pd.Series([next((r[1] for r in reversed(vs.LIMITS) if m >= r[0]), np.nan) for m in months], index=midx)
    valid_adj = set(vm.adj_months(months[-1]))
    w = aux["w"].astype({"subsistema": str, "id_entidad": str})
    cas_ent = writeoffs_by_entity(f, months)

    long_parts = []
    scope_meta = []

    def emit(key: str, tipo: str, sub_series, comp: pd.DataFrame) -> dict:
        res = {}
        for k, (num, den) in indicators(comp, lg, tc, tcc).items():
            df = finish(k, num, den)
            res[k] = df
        return res

    # --- subsistemas
    sub_res, sub_comp = {}, {}
    for sub, label, short in SUBSYSTEMS:
        rows = f[f["subsistema"] == sub]
        comp = rows.groupby("periodo")[STOCK_COLS].sum(min_count=1).reindex(midx)
        # Saldo en ME del subsistema vacío si las entidades con dato de moneda no cubren el 99,5 % (regla de mora).
        cov = rows.assign(x=rows["ct"].where(rows["meu"].notna(), 0.0)).groupby("periodo")["x"].sum().reindex(midx)
        comp.loc[~(cov >= 0.995 * comp["ct"]), "meu"] = np.nan
        # Deudores: fila TOTAL publicada (consolidada), no la suma de entidades.
        comp["deu"] = aux["deu_sub"].xs(sub, level="subsistema").reindex(midx) if sub in aux["deu_sub"].index.get_level_values(1) else np.nan
        # RCL: el publicado del subsistema.
        r = aux["rcl_sub"]
        comp["rcl"] = r.xs(sub, level="subsistema").reindex(midx) if len(r) and sub in r.index.get_level_values("subsistema") else np.nan
        # Castigos: por (subsistema, entidad) como el tablero de colocaciones; en meses válidos, 0 si no hubo.
        ct_tot = aux["cas_sub_tot"]
        cs = (ct_tot.xs(sub, level="subsistema") if sub in ct_tot.index.get_level_values("subsistema")
              else pd.Series(dtype=float)).reindex(midx).fillna(0.0)
        comp["cas"] = cs.where(cs.index.isin(valid_adj) & comp["ct"].notna())
        comp["ctavg"] = rolling_mean12(comp["ct"])
        fl = flows_by_period(vr.rolling_block(vr.scope_series(w[w["subsistema"] == sub], full=w))).reindex(midx)
        comp = comp.join(fl)
        sub_comp[sub] = comp
        sub_res[sub] = emit(sub, "sub", None, comp)

    # --- sistema: Σ numeradores / Σ denominadores de los subsistemas que reportan el indicador
    sys_fl = flows_by_period(vr.rolling_block(vr.scope_series(w, full=w))).reindex(midx)
    sys_comp = pd.DataFrame({c: pd.concat([sub_comp[s][c] for s in SUBS], axis=1).sum(axis=1, min_count=1)
                             for c in STOCK_COLS if c not in ("rcl", "deu")}).reindex(midx)
    sys_comp = sys_comp.join(sys_fl)
    for c in ["cas", "ctavg"]:
        sys_comp[c] = pd.concat([sub_comp[s][c] for s in SUBS], axis=1).sum(axis=1, min_count=1)
    sys_comp["rcl"] = np.nan
    sys_comp["deu"] = aux["deu_sys"].reindex(midx)
    sys_own = emit("sistema", "sis", None, sys_comp)
    sys_res = {}
    for k, row in CAT.items():
        rule, reporters = row[12], row[11]
        if rule == "none":
            continue
        have = pd.concat([sub_res[s][k]["valor"].notna() for s in reporters], axis=1).all(axis=1)
        if rule == "sum":
            num = pd.concat([sub_res[s][k]["numerador"] for s in reporters], axis=1).sum(axis=1, min_count=1)
            den = pd.concat([sub_res[s][k]["denominador"] for s in reporters], axis=1).sum(axis=1, min_count=1)
            if CAT[k][3] in ("S/ mill.", "miles"):
                df = finish(k, num.where(have), None)
            else:
                df = finish(k, num.where(have), den.where(have))
        elif rule == "flows":
            df = sys_own[k].copy()
            df.loc[~have] = np.nan
        elif rule == "sf":
            df = sys_own[k].copy()
        sys_res[k] = df
    # Participación del subsistema en el sistema.
    sis_ct = sys_res["cred"]["numerador"]
    for sub in SUBS:
        ct = sub_comp[sub]["ct"]
        sub_res[sub]["part_sis"] = finish("part_sis", ct.where(sis_ct.notna()), sis_ct.where(ct.notna()))

    # --- entidades: serie encadenada por id_entidad
    names = pd.read_csv(ENTIDADES, dtype=str).set_index("id_entidad")["nombre_actual"]
    panel = read_table(PANEL, columns=["periodo", "id_entidad", "nombre_entidad"])
    last_name = panel[panel["id_entidad"] != "_total"].sort_values("periodo").groupby("id_entidad")["nombre_entidad"].last()
    ent_res = {}
    sub_last = {sub: int(sub_comp[sub]["ct"].last_valid_index()) for sub in SUBS}
    for ent, rows in f.groupby("id_entidad"):
        rows = rows.sort_values("periodo")
        comp = rows.set_index("periodo")[STOCK_COLS].reindex(midx)
        home = rows.set_index("periodo")["subsistema"].reindex(midx)
        comp["cas"] = cas_ent[ent].reindex(midx) if ent in cas_ent.columns else np.nan
        comp.loc[~(comp.index.isin(valid_adj)) | comp["ct"].isna(), "cas"] = np.nan
        comp.loc[comp.index.isin(valid_adj) & comp["ct"].notna() & comp["cas"].isna(), "cas"] = 0.0
        comp["ctavg"] = rolling_mean12(comp["ct"])
        g = w[w["id_entidad"] == ent]
        if len(g):
            fl = flows_by_period(vr.rolling_block(g.set_index("t")[vr.FLOW_KEYS + ["ac", "pa", "cd", "at", "ut", "np"]]))
            comp = comp.join(fl.reindex(midx))
        else:
            for col in ["if_", "gf", "pr", "si", "sg", "ga", "da", "rn", "A", "P", "C"]:
                comp[col] = np.nan
        res = {k: v for k, v in emit(ent, "ent", home, comp).items()}
        # Participaciones: créditos / créditos de su subsistema de ese mes y / sistema.
        sub_ct = pd.Series([sub_comp[s]["ct"].get(m, np.nan) if isinstance(s, str) else np.nan
                            for m, s in zip(midx, home)], index=midx)
        res["part_sub"] = finish("part_sub", comp["ct"].where(sub_ct > 0), sub_ct.where(comp["ct"].notna() & (sub_ct > 0)))
        res["part_sis"] = finish("part_sis", comp["ct"].where(sis_ct > 0), sis_ct.where(comp["ct"].notna() & (sis_ct > 0)))
        if not any(df["valor"].notna().any() for df in res.values()):
            continue
        ent_res[ent] = (res, home)
        present = home.dropna()
        runs, prev = [], None
        for m, s in present.items():
            if s != prev:
                runs.append([month_key(int(m)), s])
                prev = s
        last_m = int(present.index.max())
        scope_meta.append({
            "ambito": ent, "tipo": "ent", "nombre": last_name.get(ent) or names.get(ent, ent),
            "subsistema": present.iloc[-1], "historial": json.dumps(runs, ensure_ascii=False),
            # Activa = tiene créditos o activo en el último mes que publicó su subsistema (un subsistema puede ir un
            # mes atrás: empresas de créditos sin set-2026 el 2026-10-31).
            "activa": bool(last_m == sub_last.get(present.iloc[-1]) and (pd.notna(comp["ct"].get(last_m))
                                                                        or pd.notna(comp["act"].get(last_m)))),
            "desde": month_key(int(present.index.min())), "hasta": month_key(last_m),
            "cred_ultimo": float(comp["ct"].get(last_m)) if pd.notna(comp["ct"].get(last_m)) else np.nan,
        })

    # --- tabla larga
    def add(key, tipo, sub, res, home=None):
        for k, df in res.items():
            d = df[df["valor"].notna()].copy()
            if d.empty:
                continue
            d["ambito"], d["tipo"], d["indicador"] = key, tipo, k
            d["subsistema"] = home.reindex(d.index).values if home is not None else sub
            long_parts.append(d.reset_index())

    add("sistema", "sis", None, sys_res)
    for sub, label, short in SUBSYSTEMS:
        add(sub, "sub", sub, sub_res[sub])
    for ent, (res, home) in ent_res.items():
        add(ent, "ent", None, res, home)
    long = pd.concat(long_parts, ignore_index=True)
    long = long[["ambito", "tipo", "subsistema", "periodo", "indicador", "valor", "numerador", "denominador"]]
    long["periodo"] = long["periodo"].astype(int)

    meta = pd.DataFrame(
        [{"ambito": "sistema", "tipo": "sis", "nombre": "Sistema financiero (5 subsistemas)", "subsistema": None,
          "historial": "[]", "activa": True}]
        + [{"ambito": s, "tipo": "sub", "nombre": l, "subsistema": s, "historial": "[]", "activa": True, "corto": c}
           for s, l, c in SUBSYSTEMS]
        + scope_meta)
    info = {"months": months, "lg": lg, "sub_comp": sub_comp, "sys_comp": sys_comp}
    return long, meta, info


# ---------------------------------------------------------------- catálogo
def catalog_frame(long: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (k, g, lab, u, d, s, q, lag, fc, fd, cu, rep, rule, nota) in CATALOG:
        x = long[long["indicador"] == k]
        desde = month_key(int(x["periodo"].min())) if len(x) else ""
        by_sub = {sub: (month_key(int(x.loc[x["ambito"] == sub, "periodo"].min()))
                        if (x["ambito"] == sub).any() else "—") for sub in SUBS}
        sysx = x[x["ambito"] == "sistema"]
        if rule == "none" and k == "rcl":
            cob = "Entidades y subsistemas que captan depósitos (publicado por la SBS); sin dato del sistema"
        elif k == "part_sub":
            cob = "Solo entidades"
        elif k == "part_sis":
            cob = "Entidades y subsistemas (créditos de los cinco subsistemas)"
        elif rep == SUBS:
            cob = ALL5
        else:
            cob = DEP4
        rows.append({
            "clave": k, "grupo": g, "grupo_etiqueta": dict(GROUPS)[g], "etiqueta": lab, "unidad": u, "decimales": d,
            "sentido": s, "frecuencia": q, "lag": lag, "formula_corta": fc, "formula_detallada": fd,
            "cuadros_sbs": CUADROS[cu], "desde": desde,
            "sistema_desde": month_key(int(sysx["periodo"].min())) if len(sysx) else "—",
            "cobertura": cob,
            "cobertura_por_subsistema": "; ".join(f"{dict((a, c) for a, _, c in SUBSYSTEMS)[s_]} {v}" for s_, v in by_sub.items()),
            "regla_sistema": {"sum": "Σ numeradores / Σ denominadores de los subsistemas",
                              "flows": "serie de 12 meses de todas las entidades (regla de perímetro de rentabilidad)",
                              "sf": "SF-2103 (deudores únicos, trimestral)", "none": "sin sistema"}[rule],
            "notas": nota,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- validación contra lo publicado
# (indicador propio, tema, variable publicada, apertura, transformación del publicado, tolerancia en la unidad del
# indicador). El RCG se compara con el cuadro de capital: el de «indicadores financieros» viene con un mes de rezago
# (etiqueta «al …»), así que no sirve para validar el mes.
PUBLISHED = [
    ("mora", "indicadores-financieros", "morosidad_creditos_atrasados", "total", None, 0.05),
    ("car", "indicadores-financieros", "morosidad_cartera_alto_riesgo", None, None, 0.05),
    ("refi", "indicadores-financieros", "ratio_refinanciados_reestructurados", None, None, 0.05),
    ("cob", "indicadores-financieros", "provisiones_creditos_atrasados", None, None, 0.5),
    ("rcg", "ratio-capital-global", "ratio_capital_global", None, None, 0.05),
    ("lev", "indicadores-financieros", "pasivo_total_capital_social_reservas", None, None, 0.05),
    ("roe", "indicadores-financieros", "roe", None, None, 0.1),
    ("roa", "indicadores-financieros", "roa", None, None, 0.05),
    ("efic", "indicadores-financieros", "gastos_operacion_margen_financiero", None, None, 0.5),
    ("gadm_cred", "indicadores-financieros", "gastos_administracion_creditos", None, None, 0.1),
    ("rl_mn", "indicadores-financieros", "ratio_liquidez", "mn", None, 0.05),
    ("rl_me", "indicadores-financieros", "ratio_liquidez", "me", None, 0.05),
    ("adeu_pas", "indicadores-financieros", "adeudos_pasivo_total", None, None, 0.1),
    ("disp_act", "indicadores-financieros", "disponible_activo_total", None, None, 0.1),
    ("cred_dep", "indicadores-financieros", "depositos_creditos_directos", None, "inv", 0.5),
    ("pg_pe", "indicadores-financieros", "posicion_global_me_patrimonio_efectivo", None, None, 0.5),
    ("mora_aj", "indicadores-financieros", "cartera_atrasada_ajustada", None, None, 0.05),
    ("rcl", "ratio-cobertura-liquidez", "ratio_cobertura_liquidez", "total", None, 0.05),
]
# Explicación de las diferencias conocidas (se escribe en la columna «comentario» del control).
COMMENTS = {
    "efic": "Banca y financieras: la SBS publica el cociente con valores acumulados en el año (aquí, 12 meses); "
            "cajas y EC coinciden.",
    "gadm_cred": "Definición distinta: la SBS divide entre créditos directos E INDIRECTOS promedio; el tablero, entre "
                 "créditos directos (cajas rurales tienen muchos contingentes). No se espera que coincida.",
    "roe": "Agregados: regla de perímetro de rentabilidad (desvíos conocidos en banca desde 2025-06, CRAC 2016, EC "
           "2016-2017 y 2020-2022, y 2010-2015).",
    "roa": "Igual que el ROE.",
    "rcg": "Entidad: desde 2023-06 el PE es el total del cuadro de estructura del PE (como el tablero de solvencia) y "
           "puede diferir del RCG publicado; antes es identidad.",
    "mora_aj": "Publicado desde 2026-01. Coincide exacto en la mayoría de entidades; en otras la SBS suma más castigos "
               "que los del cuadro de castigos (ver informe).",
    "pg_pe": "Desde 2026-03 el ratio publicado de cajas y EC deja de ser PG(t)/PE(t) (ver panel). Antes de 2015 el "
             "publicado usa otro PE.",
    "cob": "Provisiones y atrasados del balance (columna local).",
    "cred_dep": "La SBS publica depósitos / créditos (cajas): se compara con 1 / (créditos / depósitos).",
    "rcl": "Entidades y subsistemas: el tablero usa el publicado tal cual (control de lectura).",
}


def validate(long: pd.DataFrame) -> pd.DataFrame:
    tables = {}
    rows = []
    for k, tema, var, ap, tr, tol in PUBLISHED:
        if tema not in tables:
            t = read_table(BOLETIN / f"{tema}.parquet", columns=KEY + ["es_total", "variable", "apertura", "valor"])
            tables[tema] = strkey(t)
        p = tables[tema]
        p = p[p["variable"] == var]
        if ap is not None:
            p = p[p["apertura"] == ap]
        if tr == "inv":
            p = p.assign(valor=10000 / p["valor"].where(p["valor"] > 0))
        mine = long[long["indicador"] == k]
        for nivel, pp, mm, on in (
                ("entidad", p[~p["es_total"]], mine[mine["tipo"] == "ent"].rename(columns={"ambito": "id_entidad"}),
                 ["periodo", "subsistema", "id_entidad"]),
                ("subsistema", p[p["es_total"]], mine[mine["tipo"] == "sub"], ["periodo", "subsistema"])):
            x = pp.groupby(on)["valor"].first().rename("pub").reset_index().merge(
                mm[on + ["valor"]], on=on, how="inner").dropna()
            if x.empty:
                continue
            x["dif"] = x["valor"] - x["pub"]
            for sub in SUBS:
                for tramo, lo, hi in (("2010-07 a 2015-12", 0, 201512), ("2016-01 en adelante", 201601, 999912)):
                    y = x[(x["subsistema"] == sub) & x["periodo"].between(lo, hi)]
                    if y.empty:
                        continue
                    ad = y["dif"].abs()
                    worst = y.loc[ad.sort_values(ascending=False).index[:5]]
                    rows.append({
                        "indicador": k, "publicado": f"{tema}: {var}" + (f"|{ap}" if ap else ""), "nivel": nivel,
                        "subsistema": sub, "tramo": tramo, "n": len(y), "tolerancia": tol,
                        "pct_dentro": round(100 * (ad <= tol).mean(), 1),
                        "mediana_dif_abs": round(float(ad.median()), 4), "max_dif_abs": round(float(ad.max()), 3),
                        "casos_peores": "; ".join(
                            f"{r.periodo}{' ' + r.id_entidad if nivel == 'entidad' else ''}: "
                            f"{r.valor:.2f} vs {r.pub:.2f}" for r in worst.itertuples() if abs(r.dif) > tol),
                        "comentario": COMMENTS.get(k, ""),
                    })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- controles de rango
RANGES = {"mora": (0, 100), "car": (0, 100), "refi": (0, 100), "mora_aj": (0, 100), "cob": (0, 2000),
          "cob_car": (0, 2000), "rcg": (0, 300), "cet1": (0, 300), "pat_act": (-50, 100), "lev": (0, 200),
          "roe": (-300, 300), "roa": (-50, 50), "efic": (0, 500), "rl_mn": (0, 2000), "rl_me": (0, 50000),
          "disp_act": (0, 100), "dep_pas": (0, 100), "adeu_pas": (0, 100), "dol_cred": (0, 100),
          "dol_dep": (0, 100), "mix_emp": (0, 100.01), "mix_mype": (0, 100.01), "mix_cons": (0, 100.01),
          "mix_hip": (0, 100.01), "part_sub": (0, 100.01), "part_sis": (0, 100.01), "castigos": (0, 100),
          "costo_riesgo": (-20, 100), "cred_dep": (0, 10000)}


def range_checks(long: pd.DataFrame) -> list[str]:
    lines = []
    for k, (lo, hi) in RANGES.items():
        x = long[long["indicador"] == k]
        bad = x[(x["valor"] < lo) | (x["valor"] > hi)]
        if len(bad):
            lines.append(f"{k}: {len(bad)} valores fuera de [{lo}, {hi}] — "
                         + ", ".join(f"{r.ambito} {r.periodo} {r.valor:.1f}" for r in bad.head(6).itertuples()))
    inf = long["valor"].abs() > 1e12
    if inf.any():
        lines.append(f"{int(inf.sum())} valores no finitos o enormes")
    neg_prov = long[(long["indicador"] == "cob") & (long["numerador"] < 0)]
    if len(neg_prov):
        lines.append(f"provisiones negativas (signo invertido) en {len(neg_prov)} ámbito-mes: "
                     + ", ".join(f"{r.ambito} {r.periodo}" for r in neg_prov.head(5).itertuples()))
    return lines


# ---------------------------------------------------------------- Excel para revisar
def write_excel(long: pd.DataFrame, meta: pd.DataFrame, cat: pd.DataFrame, val: pd.DataFrame) -> None:
    order = [r[0] for r in CATALOG]
    labels = dict(zip(cat["clave"], cat["etiqueta"]))
    names = meta.set_index("ambito")["nombre"]
    wide = long.pivot_table(index=["tipo", "ambito", "periodo"], columns="indicador", values="valor", aggfunc="first")
    wide = wide.reindex(columns=[k for k in order if k in wide.columns]).reset_index()
    wide.insert(2, "nombre", wide["ambito"].map(names))
    sub_of = long.drop_duplicates(["ambito", "periodo"]).set_index(["ambito", "periodo"])["subsistema"]
    wide.insert(3, "subsistema", [sub_of.get((a, p)) for a, p in zip(wide["ambito"], wide["periodo"])])
    last = int(long["periodo"].max())
    snap = wide[wide["periodo"] == last]
    with pd.ExcelWriter(OUT_XLSX) as xl:
        cat.to_excel(xl, sheet_name="catalogo", index=False)
        snap.rename(columns=labels).to_excel(xl, sheet_name=f"ultimo_mes_{last}", index=False)
        wide[wide["tipo"] != "ent"].rename(columns=labels).to_excel(xl, sheet_name="sistema_subsistemas", index=False)
        wide[wide["tipo"] == "ent"].rename(columns=labels).to_excel(xl, sheet_name="entidades", index=False)
        meta.to_excel(xl, sheet_name="ambitos", index=False)
        val.to_excel(xl, sheet_name="validacion", index=False)


def summary(long: pd.DataFrame) -> None:
    last = int(long["periodo"].max())
    keys = ["cred", "cred_g", "dep", "mora", "car", "mora_aj", "rcg", "roe", "roa", "efic", "rl_mn", "cred_dep", "dol_cred"]
    x = long[long["tipo"].isin(["sis", "sub"])]
    print(f"\nÚltimo mes {month_key(last)} (sistema: último mes con dato si es anterior):")
    print(f"  {'ámbito':<22}" + "".join(f"{k:>10}" for k in keys))
    for amb in ["sistema"] + SUBS:
        vals = []
        for k in keys:
            y = x[(x["ambito"] == amb) & (x["indicador"] == k)]
            if y.empty:
                vals.append("        —")
                continue
            r = y.loc[y["periodo"].idxmax()]
            tag = "" if r["periodo"] == last else "*"
            vals.append(f"{r['valor']:>9.2f}{tag}" if tag else f"{r['valor']:>10.2f}")
        print(f"  {amb:<22}" + "".join(vals))
    print("  (* = último mes con dato anterior al corte)")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    long, meta, info = build()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    long.to_parquet(OUT_LONG, index=False)
    meta.to_csv(OUT_SCOPES, index=False, encoding="utf-8")
    cat = catalog_frame(long)
    cat.to_csv(CATALOG_CSV, index=False, encoding="utf-8")
    print("\nValidación contra lo publicado por la SBS...")
    val = validate(long)
    CONTROL_CSV.parent.mkdir(parents=True, exist_ok=True)
    val.to_csv(CONTROL_CSV, index=False, encoding="utf-8")
    pd.set_option("display.width", 250)
    agg = val.assign(ok=val["n"] * val["pct_dentro"] / 100).groupby(["indicador", "nivel", "tramo"], sort=False).agg(
        n=("n", "sum"), ok=("ok", "sum"), max_dif=("max_dif_abs", "max"))
    agg["pct_dentro"] = (100 * agg["ok"] / agg["n"]).round(1)
    print(agg[["n", "pct_dentro", "max_dif"]].to_string())
    print("\nControles de rango:")
    lines = range_checks(long)
    for ln in lines or ["sin valores fuera de rango"]:
        print("  " + ln)
    summary(long)
    write_excel(long, meta, cat, val)
    n_ent = int((meta["tipo"] == "ent").sum())
    print(f"\n{len(long):,} celdas con valor; {n_ent} entidades; {month_key(info['months'][0])} a {month_key(info['months'][-1])}")
    print(f"Escrito {OUT_LONG.relative_to(PROJECT_DIR)}, {OUT_XLSX.name}, {OUT_SCOPES.name}, "
          f"{CATALOG_CSV.relative_to(PROJECT_DIR)} y {CONTROL_CSV.relative_to(PROJECT_DIR)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
