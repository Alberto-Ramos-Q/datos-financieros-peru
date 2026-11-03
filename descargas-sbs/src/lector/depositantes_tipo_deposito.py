"""Lector del cuadro «Número de Personas por Tipo de Depósito» (depositantes por entidad).

Códigos: B-2373 (banca múltiple), B-3232 (empresas financieras), C-1250 (cajas municipales),
C-2255 (cajas rurales). Empresas de créditos no captan depósitos.

Qué publica
-----------
Entidades en FILAS (col. 0) y en COLUMNAS dos filas de cabecera: tipo de depósito («Depósitos
a la Vista», «de Ahorros», «a Plazo», «CTS», «Totales»; propagado a la derecha) × tipo de
depositante («Personas Naturales», «Personas Jurídicas sin Fines de Lucro», «Otras Personas
Jurídicas»). Fila final del total del subsistema («TOTAL BANCA MÚLTIPLE»).

Variable: `numero_depositantes` (numero); apertura `tipo_deposito|tipo_depositante` con los
mismos códigos que `depositos_escala_montos` (`vista`, `ahorro`, `plazo`, `cts`, `total` ×
`personas_naturales`, `pj_sin_fines_lucro`, `pj_otras`, `total`).

Uso: con los depósitos de la entidad da el depósito promedio por depositante, la medida de
concentración disponible por entidad (la SBS no publica la escala de montos ni los 20
principales depositantes por entidad).

Trampas
-------
- Columna de los nombres: casi siempre la 0, pero en banca 2015-01 y en los cuadros 2010-2014 de
  banca y financieras va en la 1 (col. 0 vacía). Hasta el 2026-10-28 el lector miraba solo la
  col. 0 y devolvía 0 filas SIN error (B-2373-en2015). Ahora la columna es la que tiene más
  nombres de entidad bajo la cabecera, y una fila con cifras sin nombre levanta ValueError.
- Es número de personas: en «Depósitos Totales» una persona con ahorro y CTS cuenta una vez,
  así que los totales son menores que la suma de los tipos.
- Las entidades se ubican con el maestro (`comun.es_entidad`) y las columnas por etiqueta.
- CMAC trae «TOTAL CAJAS MUNICIPALES DE AHORRO Y CRÉDITO» (sin la CMCP Lima), luego «CMCP
  Lima» y «TOTAL CAJAS MUNICIPALES»: se queda solo el ÚLTIMO total (todo el subsistema).
"""
from __future__ import annotations

from pathlib import Path

from lector import comun

TIPO_DEPOSITO = {"depositos a la vista": "vista", "depositos vista": "vista", "depositos de ahorro": "ahorro",
                 "depositos a plazo": "plazo", "depositos cts": "cts", "depositos totales": "total"}
DEPOSITANTE = {"personas naturales": "personas_naturales", "personas juridicas sin": "pj_sin_fines_lucro",
               "privadas sin fines": "pj_sin_fines_lucro", "otras personas juridicas": "pj_otras",
               "total": "total"}


def _columna_entidad(g, desde: int, subsistema: str) -> int:
    """Columna con más nombres de entidad bajo la cabecera (0 casi siempre; 1 en banca 2015-01 y
    en los cuadros 2010-2014 de banca y financieras, con la col. 0 vacía)."""
    conteo = {j: sum(comun.es_entidad(g.iat[i, j], subsistema) for i in range(desde, len(g)))
              for j in range(min(3, g.shape[1]))}
    return max(conteo, key=lambda j: (conteo[j], -j))


def _leer_hoja(hoja: str, g, subsistema: str) -> list[dict]:
    txt = [[comun.norm(v) for v in g.iloc[i]] for i in range(len(g))]
    h = next((i for i, f in enumerate(txt) if any(t.startswith("depositos totales") for t in f)), None)
    if h is None:
        return []
    ec = _columna_entidad(g, h + 2, subsistema)
    cols, tipo = {}, None
    for j in range(ec + 1, g.shape[1]):
        tipo = next((v for k, v in TIPO_DEPOSITO.items() if txt[h][j].startswith(k)), tipo)
        dep = next((v for k, v in DEPOSITANTE.items() if txt[h + 1][j].startswith(k)), None)
        if txt[h + 1][j] and dep is None:
            raise ValueError(f"{hoja}: depositante desconocido «{txt[h + 1][j]}»")
        if tipo and dep:
            cols[j] = f"{tipo}|{dep}"
    if not any(ap.startswith("total|") for ap in cols.values()):
        raise ValueError(f"{hoja}: sin columnas de «Depósitos Totales»")
    filas = {}
    for i in range(h + 2, len(g)):
        nombre = g.iat[i, ec]
        n = comun.norm(nombre)
        if n.startswith(("fuente", "nota")):
            break
        if not n:
            if any(comun.a_numero(g.iat[i, j]) not in (None, 0) for j in cols):
                raise ValueError(f"{hoja}: fila {i} con cifras y sin nombre de entidad (col. {ec})")
            continue
        if not comun.es_entidad(nombre, subsistema):
            if any(comun.a_numero(g.iat[i, j]) is not None for j in cols):
                raise ValueError(f"{hoja}: fila «{nombre}» con cifras y sin entidad reconocida")
            continue
        filas[i] = [comun.registro(hoja, nombre, "numero_depositantes", ap, g.iat[i, j], "numero")
                    for j, ap in cols.items()]
    totales = [i for i in filas if comun.es_total(g.iat[i, ec])]
    return [r for i, regs in filas.items() if i not in totales[:-1] for r in regs]  # sin subtotal CMAC


def leer(ruta: Path, subsistema: str, periodo: int) -> list[dict]:
    salida = []
    for hoja, g in comun.abrir(ruta).items():
        salida += _leer_hoja(hoja, g, subsistema)
    return salida
