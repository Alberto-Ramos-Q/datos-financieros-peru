"""Lector del tema `tarjetas-credito-tipo` (B-2363, B-3242, C-1235, C-2240, C-4229).

Banca y financieras: «Número de Tarjetas de Crédito por Tipo» (Reporte 7). CMAC, CRAC y EC:
«Número de tarjetas de crédito y débito». Dos layouts, ambos con entidades en FILAS (columna
rotulada «Empresas») y el total del subsistema al final.

- Layout «por tipo» (B-2363, B-3242): una columna por tipo de crédito al que está asociada la
  tarjeta: «Créditos de Consumo», «Créditos Corporativos», «Créditos a Grandes Empresas»,
  «Créditos a Mediana(s) Empresas», «Créditos a Pequeñas Empresas», «Créditos a
  Microempresas», «Total *». Banca 2015: la columna de entidades es la segunda.
- Layout «crédito y débito» (C-1235, C-2240, C-4229): «Nº TARJETAS DE DÉBITO» y «Nº TARJETAS
  DE CRÉDITO» (sin apertura por tipo de crédito). Debajo de cada rótulo, una fila de fechas:
  débito trae DOS columnas, el mismo mes del año anterior y el mes del cuadro; se toma solo la
  del mes del archivo (la del año anterior ya está en el archivo de ese mes). EC solo publica
  crédito (no captan depósitos, no emiten débito).

Variables (numero) y apertura (`tipo`, un nivel)
------------------------------------------------
- `numero_tarjetas_credito`: apertura consumo, corporativos, grandes_empresas,
  medianas_empresas, pequenas_empresas, microempresas, total (layout por tipo); solo `total`
  en CMAC, CRAC y EC.
- `numero_tarjetas_debito`: apertura `total`; solo CMAC y CRAC.

Trampas
-------
- Banca y financieras 2010-07 y 2010-08 (extensión del 2026-10-28): publican el cuadro «crédito y
  débito» (como las cajas, con el mes del año anterior) y sin la celda «Empresas»: la cabecera
  es la fila «N° Tarjetas de …» y la columna de entidades la que más nombres tiene. Esos dos
  meses dan solo `total` de crédito y de débito; el tipo de crédito empieza en 2010-09.
- Res. SBS 2368-2023 (nota al pie desde 2024-10): cambia la tipificación de los créditos
  empresariales; las tarjetas corporativas/grandes/…/micro no son del todo comparables antes y
  después. El consumo y el total no se ven afectados.
- CMAC trae «TOTAL CAJAS MUNICIPALES DE AHORRO Y CRÉDITO» (sin CMCP Lima), «CMCP Lima» y
  «TOTAL CAJAS MUNICIPALES»: se queda solo el ÚLTIMO total.
- «EC TOTAL Servicios Financieros» es una entidad, no un total.
- Una columna con rótulo desconocido, una fecha de columna que no es el mes del archivo ni el
  mismo mes del año anterior, o una fila con cifras y sin nombre levanta ValueError.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import pandas as pd

from lector import comun

TIPOS = [  # (regex sobre la etiqueta normalizada, token); el orden importa
    (r"^total$", "total"),
    (r"consumo", "consumo"),
    (r"corporativ", "corporativos"),
    (r"grandes? empresas", "grandes_empresas"),
    (r"medianas? empresas", "medianas_empresas"),
    (r"pequenas? empresas", "pequenas_empresas"),
    (r"micro ?empresas", "microempresas"),
]
CLASES = [(r"tarjetas de debito", "numero_tarjetas_debito"), (r"tarjetas de credito", "numero_tarjetas_credito")]
NOTA_RE = re.compile(r"^\s*(nota|fuente|\d+\s*/|\*|\(\*\)|http)", re.IGNORECASE)


def _token(texto, tabla) -> str | None:
    n = comun.norm(texto)
    return next((t for patron, t in tabla if re.search(patron, n)), None) if n else None


def _periodo_celda(v) -> int | None:
    if isinstance(v, (dt.datetime, dt.date, pd.Timestamp)):
        return v.year * 100 + v.month
    return None


def leer(ruta: Path, subsistema: str, periodo: int) -> list[dict]:
    out: list[dict] = []
    for hoja, df in comun.abrir(ruta).items():
        out += _leer_hoja(str(hoja).strip(), df, subsistema, periodo)
    return out


def _cabecera(df: pd.DataFrame, subsistema: str) -> tuple[int, int] | None:
    nr, nc = df.shape
    for i in range(min(nr, 30)):
        for j in range(nc):
            if comun.norm(df.iat[i, j]) in ("empresas", "empresa"):
                return i, j
    # Banca y financieras 2010-07/08: cuadro «crédito y débito» sin la celda «Empresas». La fila de
    # cabecera es la de «N° Tarjetas de …»; la columna de entidades, la que más nombres tiene.
    for i in range(min(nr, 30)):
        clases = [j for j in range(nc) if _token(df.iat[i, j], CLASES)]
        if clases:
            conteo = {j: sum(comun.es_entidad(df.iat[k, j], subsistema) for k in range(i + 1, nr))
                      for j in range(min(clases))}
            je = max(conteo, key=conteo.get, default=None)
            if je is not None and conteo[je] >= 2:
                return i, je
    return None


def _columnas(hoja: str, df: pd.DataFrame, h: int, je: int, periodo: int) -> tuple[dict, int]:
    """Columna → (variable, apertura) y primera fila de datos."""
    nr, nc = df.shape
    rotulos = {j: df.iat[h, j] for j in range(je + 1, nc) if comun.norm(df.iat[h, j])}
    if any(_token(v, CLASES) for v in rotulos.values()):
        # Layout crédito y débito: la clase se propaga a la derecha; la fila siguiente trae fechas.
        anio_antes = periodo - 100
        cols, clase = {}, None
        for j in range(je + 1, nc):
            if j in rotulos:
                clase = _token(rotulos[j], CLASES)
                if clase is None:
                    raise ValueError(f"hoja {hoja!r}: columna desconocida {comun.limpiar(rotulos[j])!r}")
            if clase is None:
                continue
            fecha = df.iat[h + 1, j] if h + 1 < nr else None
            p = _periodo_celda(fecha)
            if p is None and comun.norm(fecha):
                raise ValueError(f"hoja {hoja!r}: fecha de columna ilegible {fecha!r}")
            if p == periodo or (p is None and j in rotulos):
                cols[j] = (clase, "total")
            elif p is not None and p != anio_antes:
                raise ValueError(f"hoja {hoja!r}: columna con fecha {p}, el archivo es {periodo}")
        clases = [c for c, _ in cols.values()]
        if len(clases) != len(set(clases)):
            raise ValueError(f"hoja {hoja!r}: varias columnas del mes para la misma clase {clases}")
        return cols, h + 2
    cols = {}
    for j, v in rotulos.items():
        t = _token(v, TIPOS)
        if t is None:
            raise ValueError(f"hoja {hoja!r}: columna de tipo desconocida {comun.limpiar(v)!r}")
        cols[j] = ("numero_tarjetas_credito", t)
    if "total" not in [a for _, a in cols.values()] or len(cols) < 4:
        raise ValueError(f"hoja {hoja!r}: cabecera incompleta {sorted(a for _, a in cols.values())}")
    return cols, h + 1


def _leer_hoja(hoja: str, df: pd.DataFrame, subsistema: str, periodo: int) -> list[dict]:
    nr, nc = df.shape
    pos = _cabecera(df, subsistema)
    if pos is None:
        if any(comun.a_numero(v) is not None for v in df.to_numpy().ravel()):
            raise ValueError(f"hoja {hoja!r}: tiene cifras pero no se encontró la cabecera «Empresas»")
        return []
    h, je = pos
    cols, ini = _columnas(hoja, df, h, je, periodo)
    if not cols:
        raise ValueError(f"hoja {hoja!r}: sin columnas del mes {periodo}")
    filas: dict[int, list[dict]] = {}
    for i in range(ini, nr):
        nombre = df.iat[i, je]
        if isinstance(nombre, str) and NOTA_RE.match(nombre):
            break
        cifras = [j for j in cols if comun.a_numero(df.iat[i, j]) is not None]
        if not cifras:
            continue
        if not comun.norm(nombre):
            if all(comun.a_numero(df.iat[i, j]) == 0 for j in cifras):
                continue
            raise ValueError(f"hoja {hoja!r} fila {i}: cifras sin nombre de entidad")
        filas[i] = [comun.registro(hoja, nombre, cols[j][0], cols[j][1], df.iat[i, j], "numero") for j in cifras]
    totales = [i for i in filas if comun.es_total(df.iat[i, je])]
    return [r for i, regs in filas.items() if i not in totales[:-1] for r in regs if r]
