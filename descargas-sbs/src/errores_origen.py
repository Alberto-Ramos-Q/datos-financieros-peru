"""Errores de origen conocidos en los cuadros de la SBS, en un solo lugar.

Todo script que use `data/processed/boletin/deudores-tipo-credito.parquet` debe pasar los datos por
`drop_debtor_source_errors` (tableros, alerta temprana, tesis). Los datos procesados quedan tal como los
publica la SBS; la corrección se aplica al usarlos.

Lo mismo con `data/processed/boletin/ranking-creditos-depositos-patrimonio.parquet`: `drop_ranking_repeats`
quita las entidad-mes en que la SBS repite las cifras de un mes anterior (`RANKING_REPEATS`), y
`ranking_blank_months` da los subsistema-mes en que, por eso, no se puede calcular la concentración.

En 8 de esas 10 entidad-mes la SBS repite el mes anterior en casi TODOS los cuadros del boletín (balance, estado
de resultados, capital, créditos, mora, liquidez, depositantes...), no solo en el ranking: el campo `row` de cada
entrada de `RANKING_REPEATS` dice qué temas repite (revisión del 2026-11-03). Es la fuente común para cualquier
tema: `source_repeat_mask(d, tema)` marca las filas de una entidad-mes cuyas cifras de ese tema son las de otro
mes. `consolidar.py` las deja vacías en `panel_entidad_mes.parquet` (columna `repite_periodo`).

Deudores de una sola entidad repetidos (2026-11-03): `drop_debtor_source_errors` trabaja por subsistema-mes; con
`entities=True` quita además las filas de entidad de `debtor_entity_errors()` (sale de `RANKING_REPEATS`: CMAC Sullana
2024-06, C-1231 con nota). Es opcional para no cambiar la salida de quien ya la usa; los tableros la piden.

Uso:
    from errores_origen import drop_debtor_source_errors
    d = drop_debtor_source_errors(d)            # d con periodo, subsistema, apertura, es_total, valor
    d = drop_debtor_source_errors(d, entities=True)   # también las entidad-mes con deudores repetidos
    from errores_origen import drop_ranking_repeats, ranking_blank_months
    r = drop_ranking_repeats(r)                 # r con periodo, subsistema, id_entidad (largo o ancho)
    from errores_origen import source_repeat_mask
    bad = source_repeat_mask(d, "ratios-liquidez")   # d con periodo, subsistema, id_entidad (de un tema)
"""
from __future__ import annotations

import pandas as pd

# Meses enteros repetidos: el Excel trae la fecha del mes, pero repite las cifras de otro mes en todas las
# entidades y en el total (verificado el 2026-11-03 con los Excel de data/raw: C-1231, C-2231 y C-4226 de
# jun-2016, fechados 30-06-2016, = abr-2016; C-4226 de mar-2022 = abr-2022: el SF-2103 da 173 226 deudores
# para las EC en mar-2022). Esos subsistema-mes quedan sin dato.
DEBTOR_SOURCE_ERRORS = {(201606, "cajas-municipales"), (201606, "cajas-rurales"), (201606, "empresas-credito"),
                        (202203, "empresas-credito")}

# Errores solo en la columna del total de deudores (los tipos de crédito están bien), revisados el 2026-11-03:
# - "sub": solo el total consolidado del subsistema repite el de otro mes, aunque las entidades cambian.
#   Banca y financieras 2015-11 (= 2015-10: 4 169 002 y 1 778 552). CMAC, CRAC y EC 2019-10 (= 2019-04: 1 730 235,
#   596 490 y 272 168); en CMAC el total queda debajo del total sin la CMCP Lima de la misma hoja y la relación
#   total / suma de entidades cae de 0,91 a 0,86; en CRAC el total supera la suma de entidades.
# - "all": además el total de cada entidad repite el de otro mes. Financieras 2016-04 (= 2016-03) y 2016-06
#   (= 2016-05): p. ej. Financiera UNO trae 442 005 deudores de consumo y un total de 441 240.
# No es error: EC 2025-10 y 2026-04 dan el mismo total (80 754), pero las entidades y la relación total / suma
# (0,996) son coherentes con los meses vecinos: coincidencia.
DEBTOR_TOTAL_ERRORS = {(201511, "banca-multiple"): "sub", (201511, "empresas-financieras"): "sub",
                       (201910, "cajas-municipales"): "sub", (201910, "cajas-rurales"): "sub",
                       (201910, "empresas-credito"): "sub",
                       (201604, "empresas-financieras"): "all", (201606, "empresas-financieras"): "all"}

# Totales iguales a los de un mes cercano que se revisaron y no son error.
DEBTOR_TOTAL_COINCIDENCES = {(202510, "empresas-credito"), (202604, "empresas-credito")}

# Cuadro equivocado en «Número de Depositantes por Tipo de Depósito» (revisado el 2026-11-04 con el Excel de data/raw):
# C-2255-en2021.XLS trae «Depósitos por Tipo y Persona de las Cajas Rurales (En miles de soles)», no número de personas
# (CRAC Raíz: 774 379 «depositantes» frente a 85 656 en dic-2020 y 85 832 en feb-2021; cifras con decimales). El lector
# lo lee igual porque las cabeceras de columnas son las mismas. Ese subsistema-mes queda sin depositantes (entidades y
# total). La escala de montos del mismo mes (C-2211) está bien. Es el único subsistema-mes con cifras no enteras.
DEPOSITOR_SOURCE_ERRORS = {(202101, "cajas-rurales"): "el cuadro de depositantes de ese mes trae los montos de "
                                                      "«Depósitos por Tipo y Persona» (en miles de soles), no personas"}

# Auditoría independiente del tablero de concentración (2026-11-04), confirmada con los Excel de data/raw:
# - Deudores de una entidad que faltan en algunas columnas (no repiten otro mes: vienen en cero). C-4226 de may-2015:
#   EDPYME Marcimex (hoy Progreso, id edpyme-progreso) trae 0 deudores de consumo y 39 en total, frente a 25 233 de
#   consumo en abril y 22 135 en junio; la fila TOTAL EDPYMES tampoco los incluye (consumo 145 964 → 123 551 → 147 082).
#   Esa entidad-mes queda sin deudores y el total del subsistema queda sin dato en esas columnas.
DEBTOR_ENTITY_GAPS = {(201505, "empresas-credito", "edpyme-progreso"): (
    ["consumo", "total"],
    "el cuadro de deudores de ese mes trae 0 deudores de consumo de EDPYME Marcimex (hoy Progreso), frente a 25,233 en "
    "abril y 22,135 en junio, y el total de las empresas de créditos tampoco los incluye")}
# - Una celda imposible en depositantes: C-1250 de abr-2026, CMAC Piura, ahorro de «otras personas jurídicas» = 10 302
#   (unos 40 000 en los meses vecinos), con un total de 84 815 mayor que ahorro + plazo + CTS (61 627). La escala de
#   montos (C-1211) trae la misma caída. Queda sin dato esa apertura de la entidad y del subsistema (y los grupos que la
#   suman: personas jurídicas y todos); el total de depósitos de la entidad no se toca.
DEPOSITOR_FIELD_ERRORS = {(202604, "cajas-municipales", "cmac-piura", "ahorro|pj_otras"): (
    "el cuadro de ese mes trae para la CMAC Piura 10,302 depositantes de ahorro personas jurídicas (unos 40,000 en los "
    "meses vecinos), menos que su total menos los otros tipos")}
# - Escala de montos con el perímetro de otro mes: B-3256 de jun-2026 todavía incluye a Efectiva (S/ 1 174 millones y
#   72 120 depositantes), que ese mes ya figura en la banca (ranking, depositantes y escala B-2321). En may-2026 y
#   jul-2026 la escala coincide con el ranking. Esa escala queda sin dato (el sistema contaría a Efectiva dos veces).
# - Tipos de crédito por entidad repetidos (informativo; ningún tablero usa los tipos por entidad, solo el total de la
#   entidad y la fila del subsistema, que sí cambian): B-3218 de dic-2015 repite en estas 10 financieras los 7 tipos de
#   nov-2015, mientras su total cambia (Credinka: mismos tipos, total 59 339 → 60 375, confirmado en el Excel). Quien use
#   los tipos por entidad de ese mes debe dejarlos sin dato. Nota: nov-2015 es también el mes con el total repetido
#   (DEBTOR_TOTAL_ERRORS).
DEBTOR_TYPE_REPEATS = {(201512, "empresas-financieras"): ["compartamos", "confianza", "credinka", "efectiva", "infinance-xp",
                                                          "mitsui-auto-finance", "proempresa", "qapaq", "santander-consumer",
                                                          "tfc"]}
# - No es error confirmado: B-2373 de jul-2024 trae 2 107 908 depositantes a la vista personas naturales del BCP (1 657 905
#   en junio y 1 730 013 en agosto). Es así en el Excel y no contradice otra cifra: se deja como lo publica la SBS.
DEPOSIT_SCALE_ERRORS = {(202606, "empresas-financieras"): (
    "la escala de montos de las financieras de ese mes todavía incluye a Efectiva, que ese mes ya figura en la banca")}


def debtor_error_masks(d: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """(filas de meses repetidos, filas con el total repetido) para un DataFrame de deudores."""
    key = pd.Series(list(zip(d["periodo"], d["subsistema"])), index=d.index)
    bad = key.isin(DEBTOR_SOURCE_ERRORS)
    kind = key.map(DEBTOR_TOTAL_ERRORS)
    tot = d["apertura"] == "total"
    bad_tot = tot & ((kind == "all") | ((kind == "sub") & d["es_total"].astype(bool)))
    return bad, bad_tot


def debtor_entity_errors() -> set[tuple[int, str, str]]:
    """(periodo, subsistema, id_entidad) en que los deudores de UNA entidad repiten los de otro mes (todas las aperturas;
    el total del subsistema la suma tal cual). Sale de `RANKING_REPEATS` (entradas cuyo «row» incluye
    `deudores-tipo-credito`): hoy solo CMAC Sullana 2024-06 (C-1231 con la nota «La información de CMAC Sullana
    corresponde al 31/05/2024»). Las demás entidad-mes de esa lista traen deudores propios («row_except»)."""
    return set(source_repeats(DEBTOR_TEMA))


def debtor_entity_error_mask(d: pd.DataFrame) -> pd.Series:
    """True en las filas de entidad (no de total) de `d` con deudores repetidos de otro mes (`debtor_entity_errors`)."""
    return source_repeat_mask(d, DEBTOR_TEMA) & ~d["es_total"].astype(bool)


def drop_debtor_source_errors(d: pd.DataFrame, verbose: bool = True, entities: bool = False) -> pd.DataFrame:
    """Quita los subsistema-mes repetidos y los totales repetidos; avisa si aparece otro total sospechoso.
    Con `entities=True` quita además las entidad-mes con los deudores repetidos (`debtor_entity_errors`: CMAC Sullana
    2024-06). Es opcional para no cambiar la salida de los proyectos que ya la usan (alerta temprana, tesis): los
    tableros de este proyecto la piden desde el 2026-11-03; las filas de total no se tocan."""
    bad, bad_tot = debtor_error_masks(d)
    bad_ent = debtor_entity_error_mask(d) if entities else pd.Series(False, index=d.index)
    if verbose:
        extra = (f" y {int(bad_ent.sum())} filas de entidades con deudores repetidos "
                 f"({len(debtor_entity_errors())} entidad-mes)" if entities else "")
        print(f"  Deudores: {int(bad.sum())} filas descartadas por meses repetidos ({len(DEBTOR_SOURCE_ERRORS)} "
              f"subsistema-mes) y {int(bad_tot.sum())} totales repetidos ({len(DEBTOR_TOTAL_ERRORS)} subsistema-mes)"
              + extra)
    out = d[~bad & ~bad_tot & ~bad_ent]
    if verbose:
        warn_repeated_totals(out)
    return out


def warn_repeated_totals(d: pd.DataFrame) -> None:
    """Aviso para las próximas actualizaciones: un total de subsistema idéntico al de otro mes cercano (±6)."""
    t = d[d["es_total"].astype(bool) & (d["apertura"] == "total")].pivot_table(
        index="periodo", columns="subsistema", values="valor")
    for sub in t.columns:
        x = t[sub].dropna()
        months = x.index // 100 * 12 + x.index % 100
        for per, v in x.items():
            m = per // 100 * 12 + per % 100
            near = x[(x.index != per) & (abs(months - m) <= 6)]
            if (near == v).any() and (per, sub) not in DEBTOR_TOTAL_COINCIDENCES:
                print(f"  AVISO: total de deudores de {sub} {per} igual al de otro mes cercano ({int(v):,}): revisar el Excel")


# ---------------------------------------------------------------- ranking de créditos, depósitos y patrimonio
# Entidad-mes en que el ranking (B-2332, B-3243, C-1205, C-2205, C-4217) repite exactamente los tres montos
# (créditos directos, depósitos totales y patrimonio) del mes anterior. Revisión sistemática del 2026-11-03 sobre
# todo el parquet (2010-07 en adelante): son los únicos 10 casos con los tres montos iguales, y todos están
# confirmados con los Excel de data/raw. En 9 la SBS lo dice en una nota al pie («La información de ... corresponde
# al ...»); en CMAC Sullana 2014-11 no hay nota, pero el cuadro de créditos por tipo y situación del mismo mes sí
# trae cifras nuevas de Sullana (≈ S/ 1 577 mill. frente a 1 522 mill. del ranking, que es el de octubre).
# El panel (`consolidar.py`) toma créditos y depósitos del ranking: desde el 2026-11-03 deja vacías esas celdas (y
# las de los demás temas repetidos, ver «row» abajo) y marca la fila en `repite_periodo`.
# No son error (revisados): repeticiones de una sola variable mientras las otras dos cambian. Depósitos de
# financieras que casi no captan (Compartamos 2010-10, 2010-12 y 2011-04; Efectiva 2011-07/08, 2012-04 y 2012-06;
# Credinka 2014-09; inFinance-XP 2014-01) y créditos de Bank of China 2021-08 (S/ 22 mill., un solo crédito).
# Acción («action»):
# - "drop_entity": se quita la entidad ese mes y la concentración se calcula con las demás. Solo cuando su
#   participación es residual (< 1 % en las tres variables). Caja Pisco (0,4 %): el HHI de las CMAC sube 8 a 10
#   puntos y el C4 0,2 pp (en el sistema, < 1 punto y < 0,03 pp), y el subsistema y el sistema no pierden 4 meses.
# - "blank_month": la entidad pesa (5 % a 37 % del subsistema): quitarla movería el HHI y el C4 tanto como un
#   cambio real de mercado, y dejar la cifra vieja es usar un dato que no es de ese mes. El subsistema queda sin
#   concentración ese mes (y el sistema también, porque necesita todos los subsistemas); la entidad, sin monto.
#
# Qué más repite cada entidad-mes (revisión del 2026-11-03 de los 28 temas de data/processed/boletin, entidad por
# entidad y variable por variable contra el mes anterior, y de las notas al pie de todos los Excel de ese mes):
# - «same_as»: mes cuyas cifras repite la SBS (el de la nota «corresponde al ...»).
# - «row»: "all" = repite el mes anterior en todos los temas salvo los de «row_except»; "ranking" = solo el ranking.
#   En los temas repetidos las cifras son idénticas (salvo redondeo: algunos indicadores pasan de 2 decimales a más, y
#   los montos en ME de «créditos por tipo, modalidad y moneda» se vuelven a convertir con el tipo de cambio del mes).
#   «row_except» lista los temas que en ese mes traen cifras propias (o ninguna cifra) de la entidad.
# - «income_total»: si el total del subsistema del estado de resultados incluye a la entidad («included»; también
#   el del balance y los demás cuadros: la SBS suma las cifras repetidas) o no («excluded»: solo CMAC Pisco, nota
#   «(**) No considera la información de CMAC Pisco»). Con él `visual_rentabilidad.drop_repeated` decide qué filas
#   omite (las excluidas: así se reproduce el ROE publicado).
# Búsqueda de otros casos (todas las entidad-mes desde 2010-07): fuera de estas 8 con «row» = "all", ninguna repite
# más de la mitad del balance (la siguiente es Amerika Financiera 2013-11, 53 %, una financiera casi sin operaciones
# cuyas partidas no se mueven; luego Edyficar 2015 en liquidación, ≤ 40 %), y ninguna repite a la vez dos de los
# cuadros principales (balance, créditos por situación, departamento, sector, categoría de riesgo, capital, morosidad
# por tipo). Hay repeticiones de UN cuadro (no de la fila), documentadas en el README y que no se tocan aquí: RCG de
# CRAC Chavín 2010-08 → 2011-02 y 2014-12 → 2015-09 y de todas las CMAC en 2012-02 (sección de solvencia), y depósitos
# por tipo y plazo de toda la banca en 2016-08.
_ROW_NOTE_PISCO = ("los 19 cuadros del mes con la nota «(*) La información de CMAC Pisco corresponde al 31.12.2013» "
                   "(indicadores: «****»); deudores (C-1231) trae cifras propias; castigos es trimestral (el de mar-2014 "
                   "repite el de dic-2013)")
RANKING_REPEATS = [
    {"periodo": 201401, "subsistema": "cajas-municipales", "id_entidad": "caja-pisco", "action": "drop_entity",
     "note": "C-1205 ene-2014: «(*) La información de CMAC Pisco corresponde al 31.12.2013»; 0,4 % de las CMAC; "
             "disuelta en may-2014 (Res. SBS 3028-2014)",
     "same_as": 201312, "row": "all", "row_except": ("deudores-tipo-credito",), "income_total": "excluded",
     "row_note": _ROW_NOTE_PISCO},
    {"periodo": 201402, "subsistema": "cajas-municipales", "id_entidad": "caja-pisco", "action": "drop_entity",
     "note": "C-1205 feb-2014: misma nota (31.12.2013); 0,4 % de las CMAC",
     "same_as": 201312, "row": "all", "row_except": ("deudores-tipo-credito",), "income_total": "excluded",
     "row_note": _ROW_NOTE_PISCO},
    {"periodo": 201403, "subsistema": "cajas-municipales", "id_entidad": "caja-pisco", "action": "drop_entity",
     "note": "C-1205 mar-2014: misma nota (31.12.2013); 0,4 % de las CMAC",
     "same_as": 201312, "row": "all", "row_except": ("deudores-tipo-credito",), "income_total": "excluded",
     "row_note": _ROW_NOTE_PISCO},
    {"periodo": 201404, "subsistema": "cajas-municipales", "id_entidad": "caja-pisco", "action": "drop_entity",
     "note": "C-1205 abr-2014: misma nota (31.12.2013); 0,4 % de las CMAC",
     "same_as": 201312, "row": "all", "row_except": ("deudores-tipo-credito",), "income_total": "excluded",
     "row_note": _ROW_NOTE_PISCO},
    {"periodo": 201411, "subsistema": "cajas-municipales", "id_entidad": "cmac-sullana", "action": "blank_month",
     "note": "C-1205 nov-2014 (actualizado al 05.03.2015) repite oct-2014 sin nota; créditos por tipo y situación "
             "y patrimonio del balance de nov-2014 sí cambian (patrimonio 229 867 frente a 227 157); 11 % de las CMAC; "
             "la entidad sigue operando",
     "same_as": 201410, "row": "ranking", "row_except": (), "income_total": "included",
     "row_note": "solo el ranking: los otros 21 cuadros del mes traen cifras de noviembre y ninguno tiene nota"},
    {"periodo": 201505, "subsistema": "cajas-rurales", "id_entidad": "caja-senor-de-luren", "action": "blank_month",
     "note": "C-2205 may-2015: «(*) La información de CRAC Señor de Luren corresponde al 30.04.2015»; 37 % de las "
             "CRAC; disuelta en jun-2015 (Res. SBS 3503-2015), bloque a CMAC Arequipa",
     "same_as": 201504, "row": "all", "row_except": ("indicadores-financieros", "deudores-tipo-credito"),
     "income_total": "included",
     "row_note": "16 cuadros con la nota (*); capital, estructura del PE, posición global y requerimiento por riesgo de "
                 "mercado repiten abril sin nota; los indicadores (C-2301, sin nota) sí traen cifras de mayo (morosidad "
                 "28,14 % frente a 26,65 %) y los deudores también"},
    {"periodo": 201603, "subsistema": "cajas-rurales", "id_entidad": "crac-raiz", "action": "blank_month",
     "note": "C-2205 mar-2016: «(*) La información de CRAC Chavín corresponde al 29.02.2016»; 10 % de las CRAC; "
             "absorbe a Edpyme Raíz en may-2016 (Res. SBS 3006-2016)",
     "same_as": 201602, "row": "all", "row_except": ("deudores-tipo-credito",), "income_total": "included",
     "row_note": "los 22 cuadros del mes con la nota «La información de CRAC Chavín corresponde al 29.02.2016» "
                 "(categoría de riesgo por tipo de crédito, en cero); deudores trae cifras propias"},
    {"periodo": 201604, "subsistema": "cajas-rurales", "id_entidad": "crac-raiz", "action": "blank_month",
     "note": "C-2205 abr-2016: misma nota (29.02.2016); 10 % de las CRAC",
     "same_as": 201602, "row": "all", "row_except": ("deudores-tipo-credito",), "income_total": "included",
     "row_note": "19 cuadros con la nota (29.02.2016); capital, posición global y riesgo de mercado repiten febrero "
                 "sin nota; deudores trae cifras propias"},
    {"periodo": 201911, "subsistema": "empresas-financieras", "id_entidad": "tfc", "action": "blank_month",
     "note": "B-3243 nov-2019: «* La información de Financiera TFC corresponde al 31/10/2019» (Res. SBS 5855-2019, "
             "disolución); 6 % de las financieras",
     "same_as": 201910, "row": "all",
     "row_except": ("deudores-tipo-credito", "depositos-tipo-plazo", "ratios-liquidez"), "income_total": "included",
     "row_note": "21 cuadros con la nota (31/10/2019); ratios de liquidez «Información No Disponible» (vacío); "
                 "depósitos por tipo y plazo (saldo promedio) y deudores, sin nota, traen cifras propias"},
    {"periodo": 202406, "subsistema": "cajas-municipales", "id_entidad": "cmac-sullana", "action": "blank_month",
     "note": "C-1205 jun-2024: «** La información de CMAC Sullana corresponde al 31/05/2024» (Res. SBS 2497-2024, "
             "disolución); 5,5 % de las CMAC; bloque a CMAC Piura en jul-2024",
     "same_as": 202405, "row": "all", "row_except": ("tarjetas-credito-tipo",), "income_total": "included",
     "row_note": "los 21 cuadros de entidades del mes con la nota (31/05/2024), también deudores (C-1231; "
                 "`drop_debtor_source_errors` la quita solo con `entities=True`); tarjetas, vacío"},
]
RANKING_AMOUNTS = ["creditos_directos", "depositos_totales", "patrimonio"]


def ranking_repeat_keys() -> set[tuple[int, str, str]]:
    """(periodo, subsistema, id_entidad) de todas las entidad-mes repetidas."""
    return {(r["periodo"], r["subsistema"], r["id_entidad"]) for r in RANKING_REPEATS}


def ranking_blank_months() -> set[tuple[int, str]]:
    """(periodo, subsistema) que quedan sin concentración (acción "blank_month")."""
    return {(r["periodo"], r["subsistema"]) for r in RANKING_REPEATS if r["action"] == "blank_month"}


def ranking_affected_months() -> set[tuple[int, str]]:
    """(periodo, subsistema) con alguna entidad repetida: ahí las participaciones publicadas por la SBS se
    calcularon con la cifra vieja y no se comparan con las calculadas."""
    return {(r["periodo"], r["subsistema"]) for r in RANKING_REPEATS}


def drop_ranking_repeats(d: pd.DataFrame, verbose: bool = True) -> pd.DataFrame:
    """Quita las filas de las entidad-mes de `RANKING_REPEATS` (formato largo o ancho: basta con periodo,
    subsistema e id_entidad). En formato largo con los tres montos, avisa si aparece otra repetición."""
    if verbose and {"variable", "valor"} <= set(d.columns):
        warn_ranking_repeats(d)
    key = pd.Series(list(zip(d["periodo"], d["subsistema"], d["id_entidad"])), index=d.index)
    bad = key.isin(ranking_repeat_keys())
    if verbose:
        print(f"  Ranking: {key[bad].nunique()} entidad-mes descartadas por repetir el mes anterior "
              f"({len(RANKING_REPEATS)} conocidas; {len(ranking_blank_months())} subsistema-mes quedan sin concentración)")
    return d[~bad]


def warn_ranking_repeats(d: pd.DataFrame) -> None:
    """Aviso para las próximas actualizaciones: entidad con los tres montos idénticos a los del mes anterior."""
    x = d[d["variable"].isin(RANKING_AMOUNTS)]
    if "es_total" in x:
        x = x[~x["es_total"].astype(bool)]
    if x["variable"].nunique() < len(RANKING_AMOUNTS):
        return
    w = (x.pivot_table(index=["subsistema", "id_entidad", "periodo"], columns="variable", values="valor", aggfunc="first")
         .reindex(columns=RANKING_AMOUNTS).reset_index().sort_values(["subsistema", "id_entidad", "periodo"]))
    month = w["periodo"] // 100 * 12 + w["periodo"] % 100
    ent = [w["subsistema"], w["id_entidad"]]
    consecutive = (month - month.groupby(ent).shift()) == 1
    same = pd.concat([w[c].fillna(0).eq(w[c].groupby(ent).shift().fillna(0)) for c in RANKING_AMOUNTS], axis=1).all(axis=1)
    positive = (w[RANKING_AMOUNTS].fillna(0) > 0).any(axis=1)
    known = ranking_repeat_keys()
    for r in w[consecutive & same & positive].itertuples(index=False):
        if (r.periodo, r.subsistema, r.id_entidad) not in known:
            print(f"  AVISO: ranking de {r.subsistema} {r.periodo}: {r.id_entidad} repite los tres montos del mes "
                  f"anterior: revisar la nota al pie del Excel y agregarlo a RANKING_REPEATS")


# ---------------------------------------------------------------- otros temas: la fila repetida (campo «row»)
RANKING_TEMA = "ranking-creditos-depositos-patrimonio"
DEBTOR_TEMA = "deudores-tipo-credito"


def repeats_tema(r: dict, tema: str) -> bool:
    """¿La entrada `r` de `RANKING_REPEATS` repite las cifras de `tema` (nombre del parquet de data/processed/boletin)?"""
    if tema == RANKING_TEMA:
        return True
    return r["row"] == "all" and tema not in r["row_except"]


def source_repeats(tema: str | None = None) -> dict[tuple[int, str, str], dict]:
    """{(periodo, subsistema, id_entidad): entrada} de las entidad-mes cuyas cifras de `tema` repiten otro mes
    (con tema None: las 10 de `RANKING_REPEATS`, repitan lo que repitan)."""
    return {(r["periodo"], r["subsistema"], r["id_entidad"]): r for r in RANKING_REPEATS
            if tema is None or repeats_tema(r, tema)}


def full_row_repeat_keys() -> set[tuple[int, str, str]]:
    """(periodo, subsistema, id_entidad) en que la SBS repite el mes anterior en casi todos los cuadros («row» = all)."""
    return {k for k, r in source_repeats().items() if r["row"] == "all"}


def source_repeat_mask(d: pd.DataFrame, tema: str) -> pd.Series:
    """True en las filas de `d` (de un solo tema, largo o ancho: basta con periodo, subsistema e id_entidad) cuyas
    cifras repiten las de otro mes. Las filas de total (`es_total` o id_entidad «_total») nunca se marcan: la SBS suma
    las cifras repetidas en sus totales (salvo el estado de resultados de CMAC Pisco, ver «income_total»)."""
    keys = source_repeats(tema)
    if not keys or d.empty:
        return pd.Series(False, index=d.index)
    sub = d["subsistema"].astype(str)
    ent = d["id_entidad"].astype(object)
    key = pd.Series(list(zip(d["periodo"].astype(int), sub, ent)), index=d.index)
    return key.isin(set(keys))


def income_excluded_keys() -> set[tuple[int, str, str]]:
    """Entidad-mes repetidas que el total del estado de resultados de la SBS NO incluye (CMAC Pisco 2014-01 → 04)."""
    return {k for k, r in source_repeats("estados-financieros").items() if r["income_total"] == "excluded"}


def repeat_footnote(r: dict) -> str | None:
    """Texto de la nota al pie de la SBS («La información de ... corresponde al ...») de una entrada de
    `RANKING_REPEATS`, entre comillas latinas; si la entrada dice «misma nota», la de la primera entrada de la misma
    entidad y mes repetido. None si la SBS no puso nota (CMAC Sullana 2014-11)."""
    for x in [r] + [x for x in RANKING_REPEATS if x["id_entidad"] == r["id_entidad"] and x["same_as"] == r["same_as"]]:
        if "«" in x["note"]:
            return x["note"][x["note"].index("«"):x["note"].index("»") + 1]
    return None
