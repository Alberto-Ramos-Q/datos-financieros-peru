"""Lector del tema `creditos-tipo-modalidad-moneda` (B-2359, B-3272, C-1261, C-2264, C-4253).

Cuadro «Créditos Directos por Tipo, Modalidad y Moneda» («Detalle de créditos por tipo,
modalidad y moneda»). Banca desde 2015-01; financieras, CMAC, CRAC y EC desde 2015-09 (antes no
se publicó). Un solo layout en todo el periodo (668 archivos revisados):

- Filas: bloques por tipo de crédito. Fila de tipo («   Créditos corporativo», «   Créditos a
  grandes empresas», …, «   Créditos de consumo», «   Créditos hipotecarios para vivienda»)
  seguida de sus modalidades; al final «Total Créditos:» y «Tipo de Cambio:» (se ignora).
- Columnas: cada entidad ocupa TRES columnas, rotuladas en la fila bajo el nombre:
  «MN (S/ Miles)», «ME (US$ miles)», «Total (S/ Miles)» («S/.» hasta 2019). El nombre de la
  entidad está solo en la primera de las tres.
- Banca 2015-08 → 2015-10: las etiquetas están en la col. 1, no en la 0 (hoja «P010P» en
  2015-08/09); la cabecera de entidades está en la fila 4 (en CMAC 2023-12, en la 5). Por eso
  la etiqueta de cada fila es la cadena más a la derecha antes de la primera columna de
  entidad, y la cabecera se ubica con `comun.es_entidad`.
Hojas: banca «15»/«P010P», financieras «14», CMAC «CM», CRAC «CR», EC «EDP».

Variable: `creditos_directos` (una sola en todo el tema).

Apertura: `tipo|modalidad|moneda`
  tipo: corporativos, grandes_empresas, medianas_empresas, pequenas_empresas, microempresas,
        consumo, hipotecarios, total («Total Créditos:» → `total|total|<moneda>`)
  modalidad (etiqueta SBS → token):
        fila de tipo «Créditos …»                → total
        Sobregiros en cuenta corriente           → sobregiros
        Tarjetas de crédito                      → tarjetas_credito
        Descuentos                               → descuentos
        Préstamos                                → prestamos
        Factoring                                → factoring
        Arrendamiento financiero y Lease-back    → arrendamiento_financiero
        Comercio exterior                        → comercio_exterior
        Otros créditos … (de cada tipo)          → otros
        Préstamos Revolventes (consumo)          → prestamos_revolventes
        Préstamos no Revolventes (consumo)       → prestamos_no_revolventes
        Préstamos autos (consumo)                → prestamos_autos
        Pignoraticios (consumo)                  → pignoraticios
        Préstamos Mivivienda (hipotecarios)      → prestamos_mivivienda
  JERARQUÍA (no sumar todo): en consumo, prestamos = prestamos_revolventes +
  prestamos_no_revolventes, y prestamos_autos ⊂ prestamos_no_revolventes. En hipotecarios,
  prestamos y prestamos_mivivienda son disjuntos.
  moneda: mn (miles_soles), me (miles_usd), total (miles_soles; MN + ME al tipo de cambio).

Trampas
-------
- Banca 2010-07 → 2014 (extensión del 2026-10-28): mismo layout (la col. 0 trae códigos de fila
  100…5800 y la fila 3 códigos de entidad, que se ignoran); 2010-07 → 2010-09 con un solo bloque
  «Actividades Empresariales *» → tipo `empresariales`; «Banco HSBC» (2010-12 → 2013-01) es
  `gnb-peru`. Financieras, CMAC, CRAC y EC no tienen este cuadro antes de 2015-09: sustituto en
  porcentaje y sin moneda en `creditos-tipo-modalidad-porcentaje`.
- Varias columnas de total: CMAC trae «TOTAL CAJAS MUNICIPALES DE AHORRO Y CRÉDITO» y luego
  «TOTAL CAJAS MUNICIPALES» (con la CMCP Lima): se queda solo el último bloque de total.
- «Préstamos» aparece en casi todos los tipos: la modalidad se interpreta según el último
  rótulo de tipo visto (los tipos se ubican por etiqueta, no por posición).
- «Tipo de Cambio:» tiene una cifra en la primera columna de entidad: no es de la entidad y se
  descarta (el cuadro termina ahí).
- EC 2021-07: el bloque de «EDPYME Servicios Financieros Total» (cols. 25-27) viene SIN nombre
  en la cabecera (en 2021-06 y 2021-08 sí lo tiene). Un bloque nuevo se detecta por el reinicio
  de monedas (… Total → MN); si no tiene nombre se DESCARTA (no se adivina la entidad). Por eso
  en EC 2021-07 la suma de entidades queda por debajo del total publicado.
- CRAC 2019-03 → 2022-09: la fila «Créditos a grandes empresas» de CRAC Raíz está vacía aunque
  sus modalidades (descuentos, préstamos, arrendamiento) tienen cifras; el total del sistema sí
  las incluye → la validación de `grandes_empresas|total|*` no cuadra. Es así en el archivo.
- EC 2024-09 →: una fila de modalidad trae un 0 en lugar del rótulo y solo ceros: se ignora
  (una fila sin rótulo con alguna cifra distinta de 0 levanta error).
- Una etiqueta desconocida con cifras o una columna sin moneda levantan ValueError.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import pandas as pd

from lector import comun

VARIABLE = "creditos_directos"
UNIDADES = {"mn": "miles_soles", "me": "miles_usd", "total": "miles_soles"}
TIPOS = [  # fila de tipo: (regex sobre la etiqueta normalizada, token)
    (r"^creditos? corporativos?$", "corporativos"),
    (r"^creditos? a grandes empresas$", "grandes_empresas"),
    (r"^creditos? a medianas empresas$", "medianas_empresas"),
    (r"^creditos? a pequenas empresas$", "pequenas_empresas"),
    (r"^creditos? a micro ?empresas$", "microempresas"),
    (r"^creditos? de consumo$", "consumo"),
    (r"^creditos? hipotecarios? para vivienda$", "hipotecarios"),
    # banca 2010-07 → 2010-09: los cinco tipos empresariales en un solo bloque
    (r"^actividades empresariales$", "empresariales"),
]
MODALIDADES = [
    (r"^sobregiros?( en cuenta corriente)?$", "sobregiros"),
    (r"^tarjetas? de credito$", "tarjetas_credito"),
    (r"^descuentos?$", "descuentos"),
    (r"^prestamos$", "prestamos"),
    (r"^factoring$", "factoring"),
    (r"^arrendamiento financiero( y lease-?back)?$", "arrendamiento_financiero"),
    (r"^comercio exterior$", "comercio_exterior"),
    (r"^otros creditos\b", "otros"),
    (r"^prestamos revolventes$", "prestamos_revolventes"),
    (r"^prestamos no revolventes$", "prestamos_no_revolventes"),
    (r"^prestamos (para )?autos?$", "prestamos_autos"),
    (r"^pignoraticios?$", "pignoraticios"),
    (r"^prestamos mi ?vivienda$", "prestamos_mivivienda"),
]
TOTAL_RE = re.compile(r"^total creditos:?$")
FIN_RE = re.compile(r"^(tipo de cambio|fuente|nota)")


def _token(texto, tabla) -> str | None:
    n = re.sub(r"\s+", " ", comun.norm(texto))
    return next((t for patron, t in tabla if re.match(patron, n)), None) if n else None


def _moneda(texto) -> str | None:
    n = comun.norm(texto)
    m = re.match(r"^(mn|me|total)\b", n)
    return m.group(1) if m else None


@lru_cache(maxsize=None)
def _es_entidad(texto: str, subsistema: str) -> bool:
    return comun.es_entidad(texto, subsistema)


def _entidad(v, subsistema: str) -> bool:
    return isinstance(v, str) and _es_entidad(v, subsistema)


def leer(ruta: Path, subsistema: str, periodo: int) -> list[dict]:
    out: list[dict] = []
    for hoja, df in comun.abrir(ruta).items():
        out += _leer_hoja(str(hoja).strip(), df, subsistema)
    return out


def _leer_hoja(hoja: str, df: pd.DataFrame, subsistema: str) -> list[dict]:
    nr, nc = df.shape
    h = next((i for i in range(min(nr, 20))
              if sum(_entidad(df.iat[i, j], subsistema) for j in range(nc)) >= 2), None)
    if h is None:
        if any(comun.a_numero(v) is not None for v in df.to_numpy().ravel()):
            raise ValueError(f"hoja {hoja!r}: tiene cifras pero no se encontró la cabecera de entidades")
        return []
    f_mon = next((i for i in range(h + 1, min(h + 3, nr))
                  if sum(_moneda(df.iat[i, j]) is not None for j in range(nc)) >= 3), None)
    if f_mon is None:
        raise ValueError(f"hoja {hoja!r}: no se ubicó la fila de monedas (MN / ME / Total)")
    # Inicio de cada bloque de entidad: celda de la cabecera con texto (entidad o no).
    inicios = {j: df.iat[h, j] for j in range(nc)
               if isinstance(df.iat[h, j], str) and df.iat[h, j].strip()}
    j0 = min(j for j in inicios if _entidad(inicios[j], subsistema))
    inicios = {j: n for j, n in inicios.items() if j >= j0}
    totales = [j for j, n in inicios.items() if comun.es_total(n)]
    # Columna → (entidad, moneda). Cada columna pertenece al último inicio a su izquierda.
    columnas: dict[int, tuple[str, str]] = {}
    duenio: dict[int, int | None] = {}
    actual = None
    sin_nombre: set[int] = set()
    mon_previa = None
    for j in range(j0, nc):
        mon = _moneda(df.iat[f_mon, j])
        if j in inicios:
            actual = j
        elif mon == "mn" and mon_previa == "total":
            actual = -j  # bloque nuevo sin nombre de entidad en la cabecera (EC 2021-07)
        mon_previa = mon or mon_previa
        duenio[j] = actual
        if actual is not None and actual < 0:
            sin_nombre.add(j)
        elif mon and actual is not None:
            columnas[j] = (inicios[actual], mon)
    # Se descartan los subtotales (todos los totales salvo el último) y lo que queda a la
    # derecha de las columnas del último total (columnas de trabajo).
    descartadas: set[int] = set(sin_nombre)
    if totales:
        descartadas |= {j for j in range(j0, nc)
                        if duenio[j] in totales[:-1] or abs(duenio[j] or 0) > totales[-1]
                        or (duenio[j] == totales[-1] and j not in columnas)}
        columnas = {j: v for j, v in columnas.items() if j not in descartadas}

    out: list[dict] = []
    tipo = None
    for i in range(f_mon + 1, nr):
        textos = [df.iat[i, k] for k in range(j0) if isinstance(df.iat[i, k], str) and df.iat[i, k].strip()]
        etq = textos[-1] if textos else ""
        n = comun.norm(etq)
        if FIN_RE.match(n):
            break
        cifras = [j for j in range(j0, nc) if comun.a_numero(df.iat[i, j]) is not None]
        t = _token(etq, TIPOS)
        if t:
            tipo, modalidad = t, "total"
        elif TOTAL_RE.match(n):
            tipo, modalidad = "total", "total"
        else:
            modalidad = _token(etq, MODALIDADES)
        if not cifras:
            continue
        if not n and all(comun.a_numero(df.iat[i, j]) == 0 for j in cifras):
            continue  # fila sin etiqueta y solo ceros (EC 2024-09 →: un 0 en lugar del rótulo)
        if modalidad is None or tipo is None:
            raise ValueError(f"hoja {hoja!r} fila {i}: etiqueta desconocida {etq!r}")
        for j in cifras:
            if j in descartadas:
                continue
            if j not in columnas:
                raise ValueError(f"hoja {hoja!r} fila {i} col {j}: columna sin entidad/moneda")
            nombre, mon = columnas[j]
            r = comun.registro(hoja, nombre, VARIABLE, f"{tipo}|{modalidad}|{mon}",
                               df.iat[i, j], UNIDADES[mon])
            if r:
                out.append(r)
    return out
