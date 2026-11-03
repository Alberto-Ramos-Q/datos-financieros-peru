"""Lector de «Morosidad según tipo y modalidad de crédito» (tema `morosidad-tipo-credito-modalidad`).

Códigos: B-2362 (banca), B-3257 (financieras), C-1242 (CMAC), C-2247 (CRAC), C-4234 (EC).

Eras de layout (revisados los 700 archivos 2015-01 → 2026-08)
-------------------------------------------------------------
Una sola era en los 5 subsistemas: una hoja con **entidades en columnas** (fila «Concepto» con
los nombres) y conceptos en filas: un bloque por tipo de crédito, cuya primera fila
(«Créditos corporativos», «Créditos a grandes empresas», …) es la morosidad del tipo y las
siguientes las de cada modalidad; al final «Total Créditos Directos». Cambian:
- la columna de etiquetas (0 en banca, 1 en el resto) y la fila de entidades (5 en banca, 4 en
  el resto) → se ubican con `comun.es_entidad`;
- la hoja: banca `16` → `P011P` (2015-08) → `16` (2015-10+); financieras ` Morosidad (P)`
  (con espacio, 2015-01/02) → `Morosidad (P)` → `P007P` (2015-07) → `15`; cajas
  `CM Morosidad`, `CR Morosidad`, `EDP Morosidad`;
- CMAC trae una columna «CAJAS MUNICIPALES DE AHORRO Y CREDITO» (subtotal sin la CMCP Lima)
  antes de «TOTAL CAJAS MUNICIPALES»: no es entidad para el maestro y se ignora; si llegara a
  escribirse «Total Cajas Municipales de Ahorro…» junto a otro total, se omite igual;
- «Pignoraticios» solo existe en cajas (consumo); banca/financieras no la traen;
- banca 2020-01 → 2021-01 rotula la última fila «Total Créditos Directo (en miles S/)», pero
  las cifras son la morosidad total en % (3.18, igual que el resto de meses): se lee como
  `total|total` en `porcentaje`.

Variables
---------
Una sola: `ratio_morosidad` (créditos atrasados / créditos directos, en %, según el balance de
comprobación). Etiqueta del tipo → token `tipo_credito`:
«Créditos corporativos» → `corporativos`; «Créditos a grandes empresas» → `grandes_empresas`;
«Créditos a medianas empresas» → `medianas_empresas`; «Créditos (a) pequeñas empresas» →
`pequenas_empresas`; «Créditos a microempresas» → `microempresas`; «Créditos de consumo» →
`consumo`; «Créditos hipotecarios para vivienda» → `hipotecarios`; «Total Créditos Directos» →
`total`.
Etiqueta de la modalidad → token `modalidad`: «Tarjetas de crédito» → `tarjetas_credito`;
«Descuentos» → `descuentos`; «Préstamos» → `prestamos`; «Préstamos revolventes» →
`prestamos_revolventes`; «Préstamos no revolventes» → `prestamos_no_revolventes`;
«Préstamos autos» → `prestamos_autos` (parte de no revolventes); «Préstamos Mivivienda» →
`prestamos_mivivienda`; «Factoring» → `factoring`; «Arrendamiento financiero y Lease-back» →
`arrendamiento_financiero`; «Comercio exterior» → `comercio_exterior`; «Pignoraticios» →
`pignoraticios`; «Otros 1/» → `otros`; la fila del tipo → `total`.

Apertura: `tipo_credito|modalidad` (p. ej. `consumo|tarjetas_credito`, `consumo|total`,
`total|total`).

Unidades: `porcentaje` en puntos porcentuales (la SBS escribe 2.59 = 2,59 %). No aditivo.

Trampas
-------
- 2010-2014 (extensión del 2026-10-28): banca empieza en 2010-09 (2010-07/08 no publicados) y en
  2010-09 trae un solo bloque «Actividades Empresariales *» (→ `empresariales`); financieras
  empieza en 2010-10. El cuadro termina en la primera nota al pie (en financieras 2011-01 hay un 0
  suelto debajo de las notas).
- «-» = sin saldo en la modalidad; un 0 explícito = saldo sin atrasos.
- Las sub-modalidades de préstamos vienen sangradas con espacios («   Préstamos revolventes»):
  `comun.norm` los quita; la jerarquía queda implícita en el token (`prestamos_*`).
- Una fila con cifras de entidades y etiqueta desconocida, o una modalidad antes del primer
  tipo, lanza `ValueError`.
- Valores fuera de [0, 100] publicados por la SBS (83 celdas, se guardan tal cual): negativos
  cuando el saldo atrasado de la modalidad es negativo (p. ej. BCP `grandes_empresas|
  tarjetas_credito` 2016–2019, hasta −0.9; B. de Comercio −45) y 100.00001 por redondeo.
- CRAC 2021-12 (C-2247-di2021, «Actualizado al 14/02/2022»): las cifras no cuadran con los
  meses vecinos ni con la morosidad contable del cuadro por días (C-2230): Cencosud Scotia
  12.83 vs 2.87, total 10.52 vs 8.00. Es la fuente; se lee tal cual y queda como alerta.
  En el resto de meses `total|total` coincide con `ratio_morosidad` de
  `morosidad-dias-incumplimiento` (diferencia mediana 0).
"""
from __future__ import annotations

import re
from pathlib import Path

from lector import comun

TIPOS = [
    (re.compile(r"^creditos corporativos$"), "corporativos"),
    (re.compile(r"^creditos (a )?grandes empresas$"), "grandes_empresas"),
    (re.compile(r"^creditos (a )?medianas empresas$"), "medianas_empresas"),
    (re.compile(r"^creditos (a )?pequenas empresas$"), "pequenas_empresas"),
    (re.compile(r"^creditos (a )?microempresas$"), "microempresas"),
    (re.compile(r"^creditos (de )?consumo$"), "consumo"),
    (re.compile(r"^creditos hipotecarios( para vivienda)?$"), "hipotecarios"),
    (re.compile(r"^total creditos directos?\b"), "total"),
    # banca 2010-09: los cinco tipos empresariales en un solo bloque «Actividades Empresariales *»
    (re.compile(r"^(creditos a )?actividades empresariales$"), "empresariales"),
]
MODALIDADES = [
    (re.compile(r"^tarjetas? de credito$"), "tarjetas_credito"),
    (re.compile(r"^descuentos?$"), "descuentos"),
    (re.compile(r"^prestamos$"), "prestamos"),
    (re.compile(r"^prestamos revolventes$"), "prestamos_revolventes"),
    (re.compile(r"^prestamos no revolventes$"), "prestamos_no_revolventes"),
    (re.compile(r"^prestamos (para )?autos?$"), "prestamos_autos"),
    (re.compile(r"^prestamos mivivienda$"), "prestamos_mivivienda"),
    (re.compile(r"^factoring$"), "factoring"),
    (re.compile(r"^arrendamiento financiero( y lease-? ?back)?$"), "arrendamiento_financiero"),
    (re.compile(r"^comercio exterior$"), "comercio_exterior"),
    (re.compile(r"^pignoraticios?$"), "pignoraticios"),
    (re.compile(r"^otros$"), "otros"),
]


def _buscar(tabla, texto: str) -> str | None:
    for patron, token in tabla:
        if patron.match(texto):
            return token
    return None


def _es_subtotal_cmac(nombre) -> bool:
    return "cajas municipales de ahorro" in comun.norm(nombre)


def _leer_hoja(hoja: str, g, subsistema: str) -> list[dict]:
    por_fila: dict[int, list[int]] = {}
    for i in range(g.shape[0]):
        cols = [j for j in range(g.shape[1]) if comun.es_entidad(g.iat[i, j], subsistema)]
        if cols:
            por_fila[i] = cols
    if not por_fila:
        return []
    fila_ent = max(por_fila, key=lambda i: len(por_fila[i]))
    cols_ent = por_fila[fila_ent]
    if len(cols_ent) < 2:
        return []
    totales = [j for j in cols_ent if comun.es_total(g.iat[fila_ent, j])]
    if len(totales) > 1:
        cols_ent = [j for j in cols_ent if not (j in totales and _es_subtotal_cmac(g.iat[fila_ent, j]))]
    primera = min(cols_ent)

    regs = []
    tipo_actual = None
    for i in range(fila_ent + 1, g.shape[0]):
        etiquetas = [comun.norm(g.iat[i, j]) for j in range(primera)]
        etiqueta = next((e for e in etiquetas if e), "")
        if etiqueta.startswith(("nota", "fuente", "http")):
            break  # notas al pie: debajo puede haber cifras sueltas (un 0 en fin. 2011-01)
        con_cifras = any(comun.a_numero(g.iat[i, j]) is not None for j in cols_ent)
        tipo = _buscar(TIPOS, etiqueta)
        if tipo:
            tipo_actual = tipo
            apertura = f"{tipo}|total"
        else:
            modalidad = _buscar(MODALIDADES, etiqueta)
            if modalidad and tipo_actual and tipo_actual != "total":
                apertura = f"{tipo_actual}|{modalidad}"
            else:
                if con_cifras:
                    raise ValueError(f"hoja {hoja!r}: fila {i} sin concepto conocido: {etiqueta!r} "
                                     f"(tipo actual {tipo_actual})")
                continue
        for j in cols_ent:
            r = comun.registro(hoja, g.iat[fila_ent, j], "ratio_morosidad", apertura, g.iat[i, j], "porcentaje")
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
