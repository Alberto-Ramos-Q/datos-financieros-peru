"""Lector del tema `personal-categoria-laboral` (B-2305, B-3202, C-1202, C-2202, C-4206).

Cuadro «Personal según Categoría Laboral por Empresa Bancaria / Financiera / Caja Municipal /
Caja Rural / Empresa de Créditos» (en el catálogo del boletín: «Número de Personal»), mensual,
en número de personas al cierre del mes. Fuente del cuadro (nota al pie): «Anexo N.° 10
Depósitos, Colocaciones y Personal por Oficina(s)». La nota 2/ del Anexo 10 (versión de 2017 y
la vigente desde la información de setiembre de 2025, Res. SBS 1661-2025) dice (textual,
con su errata): «Debe considerarse a todo el personal, de acuerdo con la función que desempeñan,
independientemente de si son nombrados, contratos o contratados por terceros». El Glosario SBS
(abril 2011) define «Personal» como el «total de trabajadores ..., independientemente de si son
nombrados, contratados por la institución financiera o por terceros». Es decir, el conteo
INCLUYE al personal tercerizado. Cobertura en la web de la SBS: mensual sin huecos desde 2008-03 en
los cinco subsistemas (banca y financieras desde 1998-01, cajas desde 1998 con huecos hasta 2000-11,
EC desde 2001-01).

Qué publica
-----------
Entidades en FILAS (columna rotulada «Empresas»; en banca 2015 es la segunda columna, la primera
trae el código SBS de la entidad) y cinco columnas: «Gerentes», «Funcionarios», «Empleados»,
«Otros», «Total». Fila final del total del subsistema («TOTAL BANCA MÚLTIPLE», «TOTAL EDPYMES»…).

Variable: `numero_personal` (numero); apertura = categoría laboral: `gerentes`, `funcionarios`,
`empleados`, `otros`, `total`.

Trampas
-------
- Las categorías las asigna cada entidad «de acuerdo con la función que desempeñan» y no son
  comparables entre entidades (p. ej. banca 2026-08: BBVA declara 5 428 funcionarios y 1 862
  empleados; Interbank, 66 funcionarios y 6 562 empleados). Para comparar, usar el `total`.
- Banca 2015 (formato viejo): bajo la cabecera hay una fila SIN nombre con los códigos de
  columna del Anexo 10 (260, 270, 280, 290, 295). Se ignora la fila sin nombre que aparece antes
  de la primera entidad; una fila con cifras y sin nombre DESPUÉS de la primera entidad levanta
  ValueError.
- CMAC trae «TOTAL CAJAS MUNICIPALES DE AHORRO Y CRÉDITO» (sin la CMCP Lima), «CMCP Lima» y
  «TOTAL CAJAS MUNICIPALES»: se queda solo el ÚLTIMO total (todo el subsistema).
- «EC TOTAL Servicios Financieros» es una entidad, no un total.
- «-» (p. ej. financieras: «Otros» de Financiera Surgir) es «sin dato» y no genera fila; el
  total de la entidad sí viene.
- La fecha del cuadro (fila 2) se compara con el mes del archivo: si no coincide, ValueError.
  Error de origen: B-2305 de 2023-11 trae la fecha y las cifras de 2023-12 (idénticas al archivo
  de diciembre) → queda sin filas en el control; ese mes de banca no tiene conteo publicado.
- Algunos meses traen una línea «Actualizado el …» bajo el título y notas al pie de que una
  entidad corrigió su Anexo 10 (p. ej. banca 2020-06 y 2023-11); el lector se detiene en las notas.
- Errores de origen en el total (quedan en `_control/<tema>_validacion.csv` si superan 0,5 %):
  banca 2026-05 y 2026-06, el TOTAL impreso difiere de la suma de entidades en 1 y 8 personas
  (y en gerentes 2026-04 → 2026-06); CRAC 2017-02, en 11 personas (gerentes: 40 vs 29).
- La Financiera Edyficar residual (2015-03 → 2015-11, tras la fusión con Mibanco) figura con 0 en
  algunos meses y no figura en otros; el total cuadra igual.
- Uso: el indicador publicado «Créditos directos / personal» (banca, financieras) divide entre el
  TOTAL; «Créditos directos / empleados» (CMAC, CRAC, EC) solo entre la categoría `empleados`.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import pandas as pd

from lector import comun

CATEGORIAS = [  # (regex sobre la etiqueta normalizada, token)
    (r"^gerente", "gerentes"),
    (r"^funcio", "funcionarios"),
    (r"^emplea", "empleados"),
    (r"^otro", "otros"),
    (r"^total", "total"),
]
NOTA_RE = re.compile(r"^\s*(nota|fuente|\d+\s*/|\*|\(\*\)|\+|http|actualizado)", re.IGNORECASE)


def _token(texto) -> str | None:
    n = comun.norm(texto)
    return next((t for patron, t in CATEGORIAS if re.search(patron, n)), None) if n else None


def _periodo_cuadro(df: pd.DataFrame) -> int | None:
    """Mes de la fecha del título (primeras filas), o None si no hay fecha."""
    for i in range(min(len(df), 8)):
        for v in df.iloc[i]:
            if isinstance(v, (dt.datetime, dt.date, pd.Timestamp)):
                return v.year * 100 + v.month
    return None


def _cabecera(df: pd.DataFrame) -> tuple[int, int] | None:
    nr, nc = df.shape
    for i in range(min(nr, 30)):
        for j in range(nc):
            if comun.norm(df.iat[i, j]) in ("empresas", "empresa"):
                return i, j
    return None


def leer(ruta: Path, subsistema: str, periodo: int) -> list[dict]:
    out: list[dict] = []
    for hoja, df in comun.abrir(ruta).items():
        out += _leer_hoja(str(hoja).strip(), df, subsistema, periodo)
    return out


def _leer_hoja(hoja: str, df: pd.DataFrame, subsistema: str, periodo: int) -> list[dict]:
    nr, nc = df.shape
    pos = _cabecera(df)
    if pos is None:
        if any(comun.a_numero(v) is not None for v in df.to_numpy().ravel()):
            raise ValueError(f"hoja {hoja!r}: tiene cifras pero no se encontró la cabecera «Empresas»")
        return []
    p = _periodo_cuadro(df)
    if p is not None and p != periodo:
        raise ValueError(f"hoja {hoja!r}: la fecha del cuadro es {p}, el archivo es {periodo}")
    h, je = pos
    cols = {}
    for j in range(je + 1, nc):
        if not comun.norm(df.iat[h, j]):
            continue
        t = _token(df.iat[h, j])
        if t is None:
            raise ValueError(f"hoja {hoja!r}: columna desconocida {comun.limpiar(df.iat[h, j])!r}")
        cols[j] = t
    if sorted(cols.values()) != sorted(t for _, t in CATEGORIAS):
        raise ValueError(f"hoja {hoja!r}: cabecera incompleta {sorted(cols.values())}")
    filas: dict[int, list[dict]] = {}
    for i in range(h + 1, nr):
        nombre = df.iat[i, je]
        if isinstance(nombre, str) and NOTA_RE.match(nombre):
            break
        cifras = [j for j in cols if comun.a_numero(df.iat[i, j]) is not None]
        if not cifras:
            continue
        if not comun.norm(nombre):
            if not filas or all(comun.a_numero(df.iat[i, j]) == 0 for j in cifras):
                continue   # fila de códigos de columna del Anexo 10 (banca 2015) o fila en ceros
            raise ValueError(f"hoja {hoja!r} fila {i}: cifras sin nombre de entidad")
        if not comun.es_entidad(nombre, subsistema):
            raise ValueError(f"hoja {hoja!r} fila {i}: entidad no reconocida {comun.limpiar(nombre)!r}")
        filas[i] = [comun.registro(hoja, nombre, "numero_personal", cols[j], df.iat[i, j], "numero") for j in cifras]
    totales = [i for i in filas if comun.es_total(df.iat[i, je])]
    if not totales:
        raise ValueError(f"hoja {hoja!r}: sin fila del total del subsistema")
    return [r for i, regs in filas.items() if i not in totales[:-1] for r in regs if r]
