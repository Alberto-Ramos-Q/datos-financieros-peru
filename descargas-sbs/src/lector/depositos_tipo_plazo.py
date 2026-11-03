"""Lector del cuadro «Depósitos del Público por Tipo de Depósito y Plazo».

Códigos: B-220513 (banca múltiple, 2015-01 → 2026-08, faltan 2015-07 y 2016-11 en la SBS) y
B-3251 (empresas financieras, desde 2015-09). Cajas y empresas de créditos no publican este cuadro.

Qué publica
-----------
Saldos PROMEDIO de los depósitos del público por entidad (filas) y tipo de depósito / plazo
(columnas), una hoja por moneda. Fuente: «Reporte N° 6-B: Tasas de interés pasivas sobre
saldos». En 2015-01 → 2015-03 el subtítulo dice explícitamente «Promedio de saldos diarios a
<mes>»; desde 2015-04 ese subtítulo se reemplaza por una fecha, pero la fuente es la misma y las
cifras siguen siendo promedios (p. ej. financieras 2015-09 tienen decimales periódicos de /22 y
2023-06 de /21: días hábiles del mes). Por eso la variable es `depositos_saldo_promedio`, que NO
equivale al saldo de fin de mes del balance.

Eras de layout
--------------
Dos hojas por libro (MN y ME) con nombres que cambian: «M.N.»/«M.E.» (2015-01 → 07),
«P017P-1»/«P017P-2» (2015-08 → 09), «23-1»/«23-2» (2015-10), «24»/«25» (banca desde 2015-11),
«23»/«24» o «24 » (financieras); en financieras 2016-12 hay además una «Hoja2» vacía (se
ignora: no tiene cabecera). La moneda NO se deduce del nombre de la hoja sino del título
(«... en Moneda Nacional ...» / «... en Moneda Extranjera ...») y se contrasta con la unidad
(«(En miles de nuevos soles)» / «(En miles de soles)» → miles_soles; «(En miles de dólares)» →
miles_usd). La cabecera de columnas (fila con «Cuenta Corriente» ... «Total») se ubica por
etiqueta; la columna de entidades, con `comun.es_entidad`. Desde 2022-11 financieras agrega
«Empresas» como cabecera de la columna de nombres (no afecta).

Variable y unidades
-------------------
- `depositos_saldo_promedio`: miles_soles (hoja MN) o miles_usd (hoja ME). No hay columna en
  moneda total.

Apertura: `moneda|tipo_deposito`
--------------------------------
- moneda: `mn`, `me`.
- tipo_deposito (etiqueta SBS → token):
  «Cuenta Corriente» → `cuenta_corriente`; «Ahorros» → `ahorro`;
  bajo «Cuentas a Plazo»: «Hasta 30 días» → `plazo_hasta_30d`, «De 31 a 90 días» →
  `plazo_31_a_90d`, «De 91 a 180 días» → `plazo_91_a_180d`, «De 181 a 360 días» →
  `plazo_181_a_360d`, «Más de 360 días» → `plazo_mas_360d`;
  «C.T.S.» → `cts`; «Total» → `total`. (No se publica el subtotal de plazo.)

Trampas
-------
- Fila del total: «TOTAL BANCA MÚLTIPLE» / «TOTAL EMPRESAS FINANCIERAS» (el orquestador la
  marca `es_total`).
- Notas al pie con nombres de entidades («Bank of China inició operaciones...») están debajo de
  la fila «Fuente»: solo se leen filas con cifras en las columnas de datos y antes de «Fuente».
- Entidades sin depósitos aparecen con 0 en todas las columnas (se conservan los ceros).
- Error de origen (validación): financieras 2016-10 → 2017-02, hoja MN, la celda del TOTAL en
  «Cuenta Corriente» está en soles y no en miles (p. ej. 2016-10: 1 677 587,5 vs. Crediscotia,
  única con saldo, 1 677,6). El «Total» de esa fila sí cuadra. Se deja tal como se publica;
  son las 5 filas de `_validacion.csv`.
- Error de origen menor: financieras 2024-07 ME, «Financiera Surgir*»: tipos suman 1,60 y su
  «Total» dice 1,91 (miles de USD).
"""
from __future__ import annotations

from pathlib import Path

from lector import comun

COLUMNAS = {
    "cuenta corriente": "cuenta_corriente",
    "ahorros": "ahorro",
    "hasta 30 dias": "plazo_hasta_30d",
    "de 31 a 90 dias": "plazo_31_a_90d",
    "de 91 a 180 dias": "plazo_91_a_180d",
    "de 181 a 360 dias": "plazo_181_a_360d",
    "mas de 360 dias": "plazo_mas_360d",
    "c.t.s.": "cts",
    "total": "total",
}
VARIABLE = "depositos_saldo_promedio"


def _moneda(textos: list[str]) -> tuple[str, str]:
    titulo = " ".join(textos)
    mn, me = "moneda nacional" in titulo, "moneda extranjera" in titulo
    soles = any(t.startswith("(en miles de") and "soles" in t for t in textos)
    dolares = any(t.startswith("(en miles de") and "dolares" in t for t in textos)
    if mn and not me and soles and not dolares:
        return "mn", "miles_soles"
    if me and not mn and dolares and not soles:
        return "me", "miles_usd"
    raise ValueError(f"moneda/unidad ambigua: mn={mn} me={me} soles={soles} dolares={dolares}")


def _leer_hoja(nombre_hoja: str, g, subsistema: str) -> list[dict]:
    txt = [[comun.norm(v) for v in g.iloc[i]] for i in range(len(g))]
    h = next((i for i, f in enumerate(txt) if "cuenta corriente" in f), None)
    if h is None:
        return []
    columnas = {}
    for j, t in enumerate(txt[h]):
        if not t:
            continue
        if t not in COLUMNAS:
            raise ValueError(f"{nombre_hoja}: columna desconocida {t!r}")
        columnas[j] = COLUMNAS[t]
    if len(columnas) != len(COLUMNAS):
        raise ValueError(f"{nombre_hoja}: faltan columnas: {sorted(set(COLUMNAS.values()) - set(columnas.values()))}")
    moneda, unidad = _moneda([t for f in txt[:h] for t in f if t])
    primera = min(columnas)
    # Columna de entidades: la que más nombres reconoce el maestro (a la izquierda de los datos)
    votos = {j: sum(comun.es_entidad(g.iat[i, j], subsistema) for i in range(h + 1, len(g)))
             for j in range(primera)}
    jn = max(votos, key=votos.get)
    if votos[jn] == 0:
        raise ValueError(f"{nombre_hoja}: no se encontró la columna de entidades")
    salida = []
    for i in range(h + 1, len(g)):
        nombre = g.iat[i, jn]
        n = comun.norm(nombre)
        if n.startswith("fuente") or n.startswith("nota"):
            break
        if not n or all(comun.a_numero(g.iat[i, j]) is None for j in columnas):
            continue
        for j, tipo in columnas.items():
            salida.append(comun.registro(nombre_hoja, nombre, VARIABLE, f"{moneda}|{tipo}",
                                         g.iat[i, j], unidad))
    return salida


def leer(ruta: Path, subsistema: str, periodo: int) -> list[dict]:
    salida = []
    for nombre_hoja, g in comun.abrir(ruta).items():
        salida += _leer_hoja(nombre_hoja, g, subsistema)
    return salida
