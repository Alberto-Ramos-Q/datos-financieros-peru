"""Lector del cuadro «Ratio de Financiación Neta Estable» (RFNE, Anexo 16-C).

Códigos: B-234021 (banca múltiple), B-230213 (empresas financieras), C-120212 (cajas
municipales), B-230820 (cajas rurales). Empresas de créditos no lo reportan. Mensual desde
2025-12; a diferencia del RCL, el archivo sí corresponde al mes de su nombre (fecha de corte
en la fila 2).

Qué publica
-----------
Una hoja por entidad (nombre en la celda sobre la cabecera) y una del agregado
(«CONSOLIDADO BM», «CONSOLIDADO CRAC»...). Filas numeradas («1», «2.1», «7.3»...) en dos
secciones, FINANCIACIÓN ESTABLE DISPONIBLE y FINANCIACIÓN ESTABLE REQUERIDA, más RESUMEN.
Columnas: valor no ponderado por vencimiento («Sin vencimiento», «Menos de 6 meses», «6 meses
a 1 año», «Más de un año») y «Valor ponderado», en miles de soles.

Variables: `<seccion>_<concepto>` con la etiqueta normalizada (p. ej.
`disponible_financiacion_minorista`, `requerida_creditos_consumo`,
`resumen_total_financiacion_estable_disponible`), unidad miles_soles; apertura
`no_ponderado|sin_vencimiento`, `no_ponderado|menos_6_meses`, `no_ponderado|6_meses_a_1_ano`,
`no_ponderado|mas_1_ano` o `ponderado`. `ratio_financiacion_neta_estable` en VECES tal como lo
publica la SBS (1,29 = 129 %; el mínimo regulatorio es 1).

Trampas
-------
- Tres filas de «Valores representativos de deuda…» (7.1 a 7.3) se distinguen solo al final
  de la etiqueta: la variable usa la etiqueta completa.
- «5 Otros pasivos» / «5.2 Otros pasivos» y «11 Otros activos» / «11.2 Otros activos» repiten
  la etiqueta: la sub-fila lleva el número al final (`disponible_otros_pasivos_5_2`).
- La fila del ratio trae la cifra solo en la columna del valor ponderado.
- Agregados y subtotales se reconocen igual que en `ratio_cobertura_liquidez`.
"""
from __future__ import annotations

from pathlib import Path

from lector import comun
from lector.ratio_cobertura_liquidez import AGREGADO_RE, SUBTOTALES, TOTAL_SUBSISTEMA, _slug

SECCIONES = {"financiacion estable disponible": "disponible", "financiacion estable requerida": "requerida",
             "resumen": "resumen"}
VENCIMIENTOS = {"sin vencimiento": "sin_vencimiento", "menos de 6 meses": "menos_6_meses",
                "6 meses a 1 ano": "6_meses_a_1_ano", "mas de un ano": "mas_1_ano"}


def _leer_hoja(hoja: str, g, subsistema: str) -> list[dict]:
    txt = [[comun.norm(v) for v in g.iloc[i]] for i in range(len(g))]
    h = next((i for i, f in enumerate(txt) if any(t.startswith("valor ponderado") for t in f)), None)
    if h is None:
        return []
    cols = {j: "ponderado" for j, t in enumerate(txt[h]) if t.startswith("valor ponderado")}
    cols.update({j: f"no_ponderado|{VENCIMIENTOS[t]}" for j, t in enumerate(txt[h + 1]) if t in VENCIMIENTOS})
    if len(cols) != 5:
        raise ValueError(f"{hoja}: cabecera con {len(cols)} columnas de valor, se esperaban 5")
    nombre = next((g.iat[i, j] for i in range(h - 1, -1, -1) for j in range(g.shape[1])
                   if txt[i][j] and comun.a_numero(g.iat[i, j]) is None
                   and not txt[i][j].startswith("ratio de financiacion")), None)
    if nombre is None or not isinstance(nombre, str):
        raise ValueError(f"{hoja}: sin nombre de entidad sobre la cabecera")
    if comun.norm(nombre) in SUBTOTALES:
        return []
    if AGREGADO_RE.fullmatch(comun.norm(nombre)):
        nombre = TOTAL_SUBSISTEMA[subsistema]
    primera = min(cols)
    salida, seccion, vistas = [], None, set()
    for i in range(h + 2, len(g)):
        etiqueta = next((t for t in txt[i][:primera] if t and comun.a_numero(t) is None), "")
        if not etiqueta:
            continue
        if etiqueta.startswith(("fuente", "nota")):
            break
        if etiqueta.startswith("ratio de financiacion neta estable"):
            salida += [comun.registro(hoja, nombre, "ratio_financiacion_neta_estable", "", g.iat[i, j], "veces")
                       for j, ap in cols.items() if ap == "ponderado"]
            continue
        nueva = next((v for k, v in SECCIONES.items() if etiqueta.startswith(k)), None)
        if nueva and all(comun.a_numero(g.iat[i, j]) is None for j in cols):
            seccion = nueva
            continue
        if seccion is None:
            raise ValueError(f"{hoja}: fila {i} «{etiqueta}» antes de la primera sección")
        variable = f"{seccion}_{_slug(etiqueta)}"
        if variable in vistas:  # «5 Otros pasivos» y «5.2 Otros pasivos»: se agrega el número
            numero = next((comun.a_numero(g.iat[i, j]) for j in range(primera)
                           if comun.a_numero(g.iat[i, j]) is not None), None)  # celda numérica (5.2)
            variable = f"{variable}_{numero:g}".replace(".", "_") if numero is not None else variable
        if variable in vistas or variable.endswith("_"):
            raise ValueError(f"{hoja}: etiqueta repetida «{etiqueta}»")
        vistas.add(variable)
        salida += [comun.registro(hoja, nombre, variable, ap, g.iat[i, j], "miles_soles")
                   for j, ap in cols.items()]
    return salida


def leer(ruta: Path, subsistema: str, periodo: int) -> list[dict]:
    salida = []
    for hoja, g in comun.abrir(ruta).items():
        salida += _leer_hoja(hoja, g, subsistema)
    return salida
