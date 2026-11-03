"""Lector del cuadro «Ratio de Cobertura de Liquidez» (RCL, Anexo 15-B).

Códigos: B-230809 (banca múltiple), B-230810 (empresas financieras), B-230811 (cajas
municipales), B-230812 (cajas rurales). Empresas de créditos no lo reportan. Se publica desde
2024-06.

Qué publica
-----------
Una hoja por entidad (nombre en la celda sobre la cabecera, p. ej. «Interbank», «ALFIN») y una
hoja del agregado del subsistema («BM», «CONSOLIDADO_BM», «EF»...). En cada hoja, saldos
promedio diarios del TRIMESTRE en tres grupos de columnas (Moneda nacional en miles de S/,
Moneda extranjera en miles de US$, Total en miles de S/) × «Importe base» / «Importe ajustado»:
- ACTIVOS LÍQUIDOS DE ALTA CALIDAD: ALAC nivel 1, 2A, 2B
- FLUJOS ENTRANTES 30 DÍAS: fondos disponibles en el sistema financiero, créditos, otros
- FLUJOS SALIENTES 30 DÍAS: financiación minorista (estable / menos estable), depósitos
  operacionales y no operacionales, adeudos, otros financiamientos mayoristas, reportes,
  otros, obligaciones contingentes (líneas no utilizadas, otras)
- RESUMEN: total ALAC, total flujos entrantes y salientes
- «RATIO DE COBERTURA DE LIQUIDEZ (%)»: un valor por moneda, en la columna «ajustado».

Periodo: OJO, el archivo NO es del mes de su nombre. Es trimestral y sale con ~3 meses de
rezago: «B-230809-jn2024» trae el «promedio diario de enero a marzo de 2024». `periodo_dato`
lee ese rótulo y el orquestador asigna el registro al mes de cierre del trimestre (202403).

Variables: `<seccion>_<concepto>` con el texto de la etiqueta normalizado (p. ej.
`alac_alac_nivel_1`, `entrantes_creditos`, `salientes_financiacion_minorista`,
`resumen_total_alac`); `ratio_cobertura_liquidez` (porcentaje) con apertura `mn`/`me`/`total`.
Apertura de los saldos: `moneda|importe` (`mn|base`, `mn|ajustado`, `me|...`, `total|...`);
unidad miles_soles (mn, total) o miles_usd (me).

Trampas
-------
- Celdas sueltas a la izquierda de la fila del ratio («23», «0»): se ignoran porque solo se
  leen las columnas ubicadas por la cabecera.
- Cajas municipales traen dos agregados: «CMAC y CMCP» (el subsistema: es el total) y «CMAC»
  (sin la CMCP Lima: se descarta). Las hojas de entidad se llaman «3_CMAC AREQUIPA»; la entidad
  se toma de la celda sobre la cabecera («CMAC AREQUIPA»).
- El orden y el nombre de las hojas cambian entre archivos (2024: «BM» primero; 2025: los
  bancos por tamaño y «CONSOLIDADO_BM» al final): la entidad se toma del rótulo de la hoja,
  nunca de su posición.
"""
from __future__ import annotations

import re
from pathlib import Path

from lector import comun

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "setiembre", "octubre", "noviembre", "diciembre"]
TOTAL_SUBSISTEMA = {
    "banca-multiple": "Total Banca Múltiple",
    "empresas-financieras": "Total Empresas Financieras",
    "cajas-municipales": "Total Cajas Municipales",
    "cajas-rurales": "Total Cajas Rurales",
}
# Rótulo (completo) de la hoja del agregado del subsistema.
AGREGADO_RE = re.compile(r"consolidado.*|banca multiple|empresas financieras|cajas? municipales|"
                         r"cajas? rurales|bm|ef|cm|cmac y cmcp( lima)?|cr|crac")
# Subtotales que no son el subsistema completo: «CMAC» sin la CMCP Lima.
SUBTOTALES = {"cmac", "consolidado cmac"}
SECCIONES = {"activos liquidos de alta calidad": "alac", "flujos entrantes": "entrantes",
             "flujos salientes": "salientes", "resumen": "resumen"}
MONEDAS = {"moneda nacional": "mn", "moneda extranjera": "me", "total": "total"}
UNIDAD = {"mn": "miles_soles", "me": "miles_usd", "total": "miles_soles"}
PERIODO_RE = re.compile(r"promedio diario de (\w+)(?: a (\w+))? de (\d{4})")


def periodo_dato(ruta: Path, periodo: int) -> int:
    """Último mes del trimestre que reporta el archivo (rótulo «promedio diario de X a Y de AAAA»)."""
    for g in comun.abrir(ruta).values():
        for v in g.iloc[:6].to_numpy().ravel():
            m = PERIODO_RE.search(comun.norm(v))
            if m:
                return int(m.group(3)) * 100 + MESES.index(m.group(2) or m.group(1)) + 1
    raise ValueError("no encuentro el rótulo «promedio diario de …»")


def _slug(texto: str) -> str:
    s = re.sub(r"\(.*?\)|30 dias", " ", comun.norm(texto))
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def _leer_hoja(hoja: str, g, subsistema: str) -> list[dict]:
    txt = [[comun.norm(v) for v in g.iloc[i]] for i in range(len(g))]
    h = next((i for i, f in enumerate(txt) if any(t.startswith("moneda nacional") for t in f)), None)
    if h is None:
        return []
    # Columnas: grupo de moneda (fila h, propagado a la derecha) × importe (fila h + 1).
    cols, moneda = {}, None
    for j, t in enumerate(txt[h]):
        moneda = next((v for k, v in MONEDAS.items() if t.startswith(k)), moneda)
        imp = txt[h + 1][j]
        if moneda and imp.startswith("importe"):
            cols[j] = (moneda, "ajustado" if "ajustado" in imp else "base")
    if len(cols) != 6:
        raise ValueError(f"{hoja}: cabecera con {len(cols)} columnas de importe, se esperaban 6")
    nombre = next((g.iat[i, j] for i in range(h - 1, -1, -1) for j in range(g.shape[1])
                   if txt[i][j] and "promedio" not in txt[i][j] and "ratio de cobertura" not in txt[i][j]),
                  None)
    if nombre is None:
        raise ValueError(f"{hoja}: sin nombre de entidad sobre la cabecera")
    if comun.norm(nombre) in SUBTOTALES:
        return []
    if AGREGADO_RE.fullmatch(comun.norm(nombre)):
        nombre = TOTAL_SUBSISTEMA[subsistema]
    primera = min(cols)
    salida, seccion = [], None
    for i in range(h + 2, len(g)):
        etiqueta = next((t for t in txt[i][:primera] if t and comun.a_numero(t) is None), "")
        if not etiqueta:
            continue
        if etiqueta.startswith(("fuente", "nota")):
            break
        if etiqueta.startswith("ratio de cobertura de liquidez"):
            for j, (mon, imp) in cols.items():
                if imp == "ajustado":
                    salida.append(comun.registro(hoja, nombre, "ratio_cobertura_liquidez", mon,
                                                 g.iat[i, j], "porcentaje"))
            continue
        nueva = next((v for k, v in SECCIONES.items() if etiqueta.startswith(k)), None)
        valores = {j: g.iat[i, j] for j in cols}
        if nueva and all(comun.a_numero(v) is None for v in valores.values()):
            seccion = nueva
            continue
        if seccion is None:
            raise ValueError(f"{hoja}: fila {i} «{etiqueta}» antes de la primera sección")
        variable = f"{seccion}_{_slug(etiqueta)}"
        for j, (mon, imp) in cols.items():
            salida.append(comun.registro(hoja, nombre, variable, f"{mon}|{imp}", valores[j], UNIDAD[mon]))
    return salida


def leer(ruta: Path, subsistema: str, periodo: int) -> list[dict]:
    salida = []
    for hoja, g in comun.abrir(ruta).items():
        salida += _leer_hoja(hoja, g, subsistema)
    return salida
