"""Lector del cuadro «Ranking de Créditos, Depósitos y Patrimonio».

Códigos: B-2332 (banca múltiple), B-3243 (empresas financieras), C-1205 (cajas municipales),
C-2205 (cajas rurales), C-4217 (empresas de créditos: «Ranking de Créditos y Patrimonio», sin
bloque de depósitos porque no captan).

Qué publica
-----------
Tres bloques apilados verticalmente («Créditos Directos*», «Depósitos Totales», «Patrimonio»),
cada uno con las entidades ORDENADAS DE MAYOR A MENOR: puesto, nombre, monto (miles de soles),
participación (%) y porcentaje acumulado. El orden cambia cada mes, así que la entidad se
identifica siempre por el nombre (columna ubicada con `comun.es_entidad`), nunca por la fila.
No hay fila de total del subsistema: el control `_validacion.csv` de este tema sale vacío
por construcción. Se verificó aparte que la participación suma 100 y que
participación = monto / Σ montos.

Eras de layout
--------------
Una hoja por libro: «P010P», «P031P», «41», «43», «44» (banca), «P010», «P010 (P)», «P019P»,
«40» (financieras), «CM», «CR», «EDP».
- banca y financieras: puesto en la col. 0, nombre en la col. 2, monto/part./acum. en 3-5;
  cajas y EC: puesto en 0, nombre en 1, cifras en 2-4. Se ubica todo por etiqueta: bloques por
  su título, columnas por la cabecera «Monto» / «Participación» / «Porcentaje (Acumulado)», el
  nombre con `comun.es_entidad` y el puesto como la cifra a la izquierda del nombre.
- banca 2020-01 en adelante: la hoja pasa de 78 a 72 filas (menos filas en blanco).
- EC 2015: filas de relleno sin nombre con 0 en participación (se ignoran: sin nombre no hay
  entidad).
- Entidades sin saldo: banca/financieras ponen «-» en la participación (sin registro) y 0 en
  el monto; algunas aparecen sin puesto.
- Unidad: «(En miles de nuevos soles)» hasta 2016-03, «(En miles de soles)» después.
- Cajas rurales (37 meses entre 2019-03 y 2022-04): los bloques «Depósitos Totales» y «Patrimonio»
  NO traen fila de cabecera (Empresas/Monto/Participación...); heredan las columnas del bloque
  anterior, que tiene la misma disposición.

Variables (etiqueta SBS → variable, unidad); apertura vacía
------------------------------------------------------------
Bloque «Créditos Directos» (neto de ingresos no devengados por arrendamiento financiero y
lease-back, según la nota SBS):
- «Monto» → `creditos_directos` (miles_soles)
- «Participación (%)» → `participacion_creditos_directos` (porcentaje)
- «Porcentaje Acumulado» → `participacion_acumulada_creditos_directos` (porcentaje)
- puesto (columna sin cabecera) → `puesto_creditos_directos` (puesto)
Bloque «Depósitos Totales»: `depositos_totales`, `participacion_depositos_totales`,
`participacion_acumulada_depositos_totales`, `puesto_depositos_totales`.
Bloque «Patrimonio»: `patrimonio`, `participacion_patrimonio`,
`participacion_acumulada_patrimonio`, `puesto_patrimonio`.

Trampas
-------
- CRAC 2010-11 (extensión 2010-07, 2026-10-28): todos los montos son -999999.99999 y cada entidad
  tiene 10 % de participación (error de origen): el archivo se rechaza (queda en el control).
- El puesto no es aditivo: unidad `puesto`.
- Banca hasta 2024-12: «No incluye sucursales en el exterior» (nota). Desde 2025-01 la nota
  sigue, con otro texto.
- `puesto_*` es el número publicado, no un rango recalculado: hay meses en que no coincide con
  el orden por monto (CM 2024-07/08 salta el 4 al salir CMAC Sullana; banca 2023-09 patrimonio
  pone a Scotiabank 2.º con menos patrimonio que BBVA 3.º; entidades con 0 empatadas al final,
  etc.: 112 casos con monto ≠ 0 en todo el histórico).
- Error de origen: banca 2020-06, depósitos, B. ICBC y B. Ripley tienen las participaciones
  intercambiadas respecto de sus montos.
- El porcentaje acumulado depende del orden; la última entidad con saldo suele tener 100 (o
  99.99999).
"""
from __future__ import annotations

from pathlib import Path

from lector import comun

BLOQUES = {
    "creditos directos": "creditos_directos",
    "depositos totales": "depositos_totales",
    "patrimonio": "patrimonio",
}


def _medidas(fila: list[str], fila_sig: list[str]) -> dict[int, str]:
    cols = {}
    for j, t in enumerate(fila):
        if t == "monto":
            cols[j] = "monto"
        elif t == "participacion":
            cols[j] = "participacion"
        elif t == "porcentaje" and fila_sig[j] == "acumulado":
            cols[j] = "acumulado"
        elif t and t != "empresas":
            raise ValueError(f"cabecera desconocida {t!r}")
    return cols


def _leer_hoja(nombre_hoja: str, g, subsistema: str) -> list[dict]:
    txt = [[comun.norm(v) for v in g.iloc[i]] for i in range(len(g))]
    titulos = [(i, BLOQUES[t]) for i, f in enumerate(txt) for t in f if t in BLOQUES]
    if not titulos:
        return []
    cabecera = " ".join(t for f in txt[:titulos[0][0]] for t in f)
    if "miles de nuevos soles" not in cabecera and "miles de soles" not in cabecera:
        raise ValueError(f"{nombre_hoja}: unidad (miles de soles) no encontrada")
    esperados = 2 if subsistema == "empresas-credito" else 3
    if len(titulos) != esperados:
        raise ValueError(f"{nombre_hoja}: {len(titulos)} bloques, se esperaban {esperados}")
    salida = []
    cols = None
    for k, (ini, bloque) in enumerate(titulos):
        fin = titulos[k + 1][0] if k + 1 < len(titulos) else len(g)
        h = next((i for i in range(ini, fin) if "monto" in txt[i]), None)
        if h is not None:
            cols = _medidas(txt[h], txt[h + 1])
        elif cols is None:
            raise ValueError(f"{nombre_hoja}: el primer bloque ({bloque}) no tiene cabecera")
        else:
            h = ini - 1  # bloque sin cabecera: hereda las columnas del bloque anterior
        if sorted(cols.values()) != ["acumulado", "monto", "participacion"]:
            raise ValueError(f"{nombre_hoja}: columnas incompletas en {bloque}: {cols}")
        primera = min(cols)
        votos = {j: sum(comun.es_entidad(g.iat[i, j], subsistema) for i in range(h + 1, fin))
                 for j in range(primera)}
        jn = max(votos, key=votos.get)
        if votos[jn] == 0:
            raise ValueError(f"{nombre_hoja}: sin entidades en el bloque {bloque}")
        variables = {"monto": (bloque, "miles_soles"),
                     "participacion": (f"participacion_{bloque}", "porcentaje"),
                     "acumulado": (f"participacion_acumulada_{bloque}", "porcentaje")}
        for i in range(h + 2, fin):
            nombre = g.iat[i, jn]
            n = comun.norm(nombre)
            if n.startswith("nota") or n.startswith("fuente") or n.startswith("*"):
                break
            if not n:
                continue
            for j, med in cols.items():
                var, unidad = variables[med]
                salida.append(comun.registro(nombre_hoja, nombre, var, "", g.iat[i, j], unidad))
            puestos = [comun.a_numero(g.iat[i, j]) for j in range(jn)]
            puestos = [x for x in puestos if x is not None]
            if puestos:
                salida.append(comun.registro(nombre_hoja, nombre, f"puesto_{bloque}", "",
                                             puestos[0], "puesto"))
    return salida


def leer(ruta: Path, subsistema: str, periodo: int) -> list[dict]:
    salida = []
    for nombre_hoja, g in comun.abrir(ruta).items():
        salida += _leer_hoja(nombre_hoja, g, subsistema)
    # CRAC 2010-11 (C-2205-no2010): todos los montos vienen como -999999.99999 y cada entidad con
    # 10 % de participación (error de origen). Se rechaza el archivo en vez de guardar basura.
    if any(r and abs(r["valor"] + 999999.99999) < 1e-3 for r in salida):
        raise ValueError("montos con el valor centinela -999999.99999 (error de origen): archivo rechazado")
    return salida
