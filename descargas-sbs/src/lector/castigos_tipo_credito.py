"""Lector del tema `castigos-tipo-credito` (B-2369, B-3234, C-1253, C-2258, C-4242).

Cuadro «Flujo de Créditos Castigados por Tipo de Crédito y Empresa …» (miles de soles).
Un solo layout en los 5 subsistemas y en todo 2015-03 → 2026-08 (660 archivos revisados):
entidades en FILAS (col. 0), tipos de crédito en COLUMNAS. Cabecera en dos filas: arriba
«Empresas» | «Flujo Trimestral/Mensual de castigos» (o «Flujo de castigos») | «Total»; debajo
«Corporativos», «Grandes Empresas», «Medianas Empresas», «Pequeñas Empresas»,
«Microempresas»/«Micro empresas», «Consumo», «Hipotecario(s)». La columna «Total» (suma de
tipos) solo está rotulada en la fila de arriba.

Hojas: banca «Cred_Castig» (2015) y «20» (2015-12 →), «Hoja1» en las republicaciones de
2024-01 → 2025-12; financieras «Public» (2015-03/06) y «19»; CMAC «CM», CRAC «CR», EC «EDP».

Frecuencia
----------
- 2015 (mar, jun, set, dic): flujo TRIMESTRAL → variable `castigos_flujo_trimestral`. Se decide
  por la cabecera («Flujo Trimestral de castigos», «… en el IV trimestre 2015»): en financieras
  2015-09 el título dice «en el mes de septiembre» pero la columna dice «Flujo Trimestral»; manda
  la columna. Incluso 2015-12 es trimestral en los 5 subsistemas (el README dice mensual desde
  2015-12: los archivos dicen lo contrario).
- 2016-01 →: flujo MENSUAL → variable `castigos_flujo_mensual`.
No hay archivos de 2015-01/02, 04/05, 07/08, 10/11 (no se publicaron).

Variables: `castigos_flujo_mensual`, `castigos_flujo_trimestral` (miles_soles).

Apertura: `tipo` — corporativos, grandes_empresas, medianas_empresas, pequenas_empresas,
microempresas, consumo, hipotecarios, total (columna «Total»). Sin separación revolvente /
no revolvente ni por moneda.

Trampas
-------
- 2010-2014 (extensión del 2026-10-28): trimestral (mar, jun, set, dic; banca desde 2010-09), los
  nombres en la col. 1 (col. 0 vacía) y, hasta 2011-06 en banca, una sola columna «Actividades
  Empresariales *» (→ `empresariales`) en vez de los cinco tipos empresariales.
- Las celdas «-» (cero en la práctica) no se guardan: `comun.a_numero` las trata como sin dato.
  Algunos importes llegan como texto («31598.11846»): `comun.a_numero` los convierte.
- CMAC trae «TOTAL CAJAS MUNICIPALES DE AHORRO Y CRÉDITO» (sin la CMCP Lima), luego «CMCP
  Lima» y «TOTAL CAJAS MUNICIPALES»: se queda solo el ÚLTIMO total (todo el subsistema).
- Financieras rotulan el total «TOTAL EMPRESA FINANCIERA» (singular).
- El cuadro termina en la fila del total: debajo hay notas y, en EC 2022-02 → 2022-07, una fila
  de trabajo «CHECK TOTALES EDP» con ceros, que se ignoran.
- Filas separadoras sin nombre con ceros (EC 2021-06 → 2023-07): se ignoran si todo es 0.
- «EC Volvo Finance» aparece DOS veces en EC 2024-06 (filas idénticas, todo 0): se guarda una;
  una entidad repetida con cifras distintas levanta ValueError.
- Banca 2025-04 (republicado el 2026-09-29) lista «Santander Consumer Bank» con 27.104 de
  consumo, pero el «TOTAL BANCA MÚLTIPLE» no lo incluye (en abril de 2025 aún era financiera):
  la suma de entidades supera al total en consumo y total. Es así en el archivo; no se corrige.
- Una fila con cifras cuyo rótulo no es entidad se emite igual (aparece en «sin resolver»);
  una columna con cifras sin tipo de crédito levanta ValueError.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import pandas as pd

from lector import comun

UNIDAD = "miles_soles"
TIPOS = [  # (regex sobre la etiqueta normalizada, token)
    (r"^corporativos?$", "corporativos"),
    (r"^grandes empresas$", "grandes_empresas"),
    (r"^medianas empresas$", "medianas_empresas"),
    (r"^pequenas empresas$", "pequenas_empresas"),
    (r"^micro ?empresas$", "microempresas"),
    (r"^consumo$", "consumo"),
    (r"^hipotecarios?( para vivienda)?$", "hipotecarios"),
    (r"^total$", "total"),
    # banca 2010-09 → 2011-06 (y financieras de esos años): los tipos empresariales juntos
    (r"^actividades empresariales$", "empresariales"),
]
NOTA_RE = re.compile(r"^\s*(nota|fuente|\*|\(\*\)|http)", re.IGNORECASE)


def _token(texto) -> str | None:
    n = re.sub(r"\s+", " ", comun.norm(texto))
    return next((t for patron, t in TIPOS if re.match(patron, n)), None) if n else None


@lru_cache(maxsize=None)
def _es_entidad(texto: str, subsistema: str) -> bool:
    return comun.es_entidad(texto, subsistema)


def _es_fila_entidad(v, subsistema: str) -> bool:
    return isinstance(v, str) and (_es_entidad(v, subsistema) or comun.es_total(v))


def leer(ruta: Path, subsistema: str, periodo: int) -> list[dict]:
    out: list[dict] = []
    for hoja, df in comun.abrir(ruta).items():
        out += _leer_hoja(str(hoja).strip(), df, subsistema)
    return out


def _leer_hoja(hoja: str, df: pd.DataFrame, subsistema: str) -> list[dict]:
    nr, nc = df.shape
    # Nombres en la col. 0 (2015 →) o en la col. 1 (2010-2014, con la col. 0 vacía).
    ec, filas_ent = 0, []
    for ec in range(min(2, nc)):
        filas_ent = [i for i in range(nr) if _es_fila_entidad(df.iat[i, ec], subsistema)]
        if len(filas_ent) >= 2:
            break
    if len(filas_ent) < 2:
        if any(comun.a_numero(v) is not None for v in df.to_numpy().ravel()):
            raise ValueError(f"hoja {hoja!r}: tiene cifras pero no se encontraron filas de entidades")
        return []
    f0 = filas_ent[0]
    cab = range(max(0, f0 - 8), f0)
    # Fila de tipos: la de la cabecera con más rótulos de tipo de crédito.
    f_tipo = max(cab, key=lambda i: sum(_token(df.iat[i, j]) not in (None, "total") for j in range(nc)))
    en_fila = {_token(df.iat[f_tipo, j]) for j in range(nc)} - {None, "total"}
    if len(en_fila) < (3 if "empresariales" in en_fila else 5):
        raise ValueError(f"hoja {hoja!r}: no se ubicó la fila de tipos de crédito")
    tipos: dict[int, str] = {}
    for j in range(ec + 1, nc):
        for i in range(f_tipo - 2, f_tipo + 1):  # «Total» está en la fila de arriba
            t = _token(df.iat[i, j])
            if t:
                tipos[j] = t
                break
    textos_cab = " ".join(comun.norm(df.iat[i, j]) for i in range(0, f0) for j in range(nc))
    variable = "castigos_flujo_trimestral" if "trimestr" in textos_cab else "castigos_flujo_mensual"

    nombres = {i: df.iat[i, ec] for i in filas_ent}
    totales = [i for i in filas_ent if comun.es_total(nombres[i])]
    fin = totales[-1] if totales else next(
        (i for i in range(f0, nr) if isinstance(df.iat[i, ec], str) and NOTA_RE.match(df.iat[i, ec])), nr) - 1

    out: list[dict] = []
    vistas: dict[str, list] = {}
    for i in range(f0, fin + 1):
        if i in totales[:-1]:
            continue  # subtotal (CMAC sin la CMCP Lima)
        cifras = [j for j in range(ec + 1, nc) if comun.a_numero(df.iat[i, j]) is not None]
        if not cifras:
            continue
        nombre = nombres.get(i, df.iat[i, ec])
        if not isinstance(nombre, str) or not nombre.strip():
            if all(comun.a_numero(df.iat[i, j]) == 0 for j in cifras):
                continue  # fila separadora con ceros sueltos (EC 2021-06 → 2023-07)
            raise ValueError(f"hoja {hoja!r} fila {i}: cifras sin nombre de entidad")
        valores = [comun.a_numero(df.iat[i, j]) for j in range(ec + 1, nc)]
        clave = comun.limpiar(nombre)
        if clave in vistas:
            if vistas[clave] == valores:
                continue  # fila repetida idéntica («EC Volvo Finance» dos veces en EC 2024-06)
            raise ValueError(f"hoja {hoja!r} fila {i}: {nombre!r} repetida con cifras distintas")
        vistas[clave] = valores
        for j in cifras:
            if j not in tipos:
                raise ValueError(f"hoja {hoja!r} fila {i} col {j}: columna sin tipo de crédito")
            r = comun.registro(hoja, nombre, variable, tipos[j], df.iat[i, j], UNIDAD)
            if r:
                out.append(r)
    return out
