"""Lector del tema `deudores-tipo-credito` (B-230803, B-3218, C-1231, C-2231, C-4226).

Cuadro «Número de Deudores según Tipo de Crédito» (Anexo 6 - Reporte Crediticio de Deudores;
solo deudores con crédito directo). Se descarga desde 2010-12: antes (p. ej. 2010-07) el cuadro
salía del Anexo 5 con solo tres tipos (actividades empresariales, consumo, hipotecario) y no es
comparable; con la tipificación de 7 tipos (Res. SBS 11356-2008) el formato es estable.

Qué publica
-----------
Entidades en FILAS y una columna por tipo de crédito. La cabecera es la fila que tiene
«Empresas» en la columna de entidades: «Deudores Corporativos», «Deudores Grandes Empresas»,
«Deudores Medianas Empresas», «Deudores Pequeñas Empresas», «Deudores Microempresas»,
«Deudores de Créditos de Consumo», «Deudores de Créditos de Hipotecarios para Vivienda» y
«Total de deudores 2/» (CMAC/CRAC/EC: «Total2/»). Encima hay filas de trabajo de la SBS
(códigos 3, 4, 6…, rótulos cortos «Corporativo», «Consumo»…) que se ignoran; debajo de la
cabecera, una fila con «Revolventes» bajo la columna de consumo.
Fila final del total del subsistema («TOTAL BANCA MÚLTIPLE 1/», «TOTAL EMPRESAS DE CRÉDITOS 1/»).

Variable: `numero_deudores` (numero).

Apertura: `tipo` (un nivel)
  corporativos, grandes_empresas, medianas_empresas, pequenas_empresas, microempresas,
  consumo, hipotecarios, total («Total de deudores»). Mismos tokens que
  `creditos_tipo_situacion`. Si algún periodo trajera consumo separado en dos columnas
  («Revolventes» / «No Revolventes» debajo de la cabecera), salen como consumo_revolvente y
  consumo_no_revolvente; no ocurrió en 2010-12 → 2026-08.

Trampas
-------
- EL CONTEO NO ES ÚNICO (notas al pie del cuadro):
  * 1/ el total del subsistema consolida deudores: una persona con créditos del mismo tipo en
    dos bancos cuenta una vez. La suma de entidades es MAYOR o igual que el total publicado.
  * 2/ el total por entidad consolida entre tipos: un deudor con consumo e hipotecario en la
    misma entidad cuenta una vez. La suma de tipos de una entidad es MAYOR o igual que su total.
  Por eso este tema no usa la validación estándar (suma de entidades = total); la regla propia
  está en `validar_totales` (ver abajo). Nunca sumar deudores entre entidades ni entre tipos.
- «Revolventes» bajo «Deudores de Créditos de Consumo» es un rótulo heredado: la columna es
  TODO el consumo (Compartamos, que no emite tarjetas, tiene miles de deudores ahí).
- La columna de entidades no siempre es la primera: en 2010-2015 (banca) hay una columna
  previa con nombres en mayúsculas («B B V A BANCO CONTIN», «COMERCIO»…); se usa la columna
  rotulada «Empresas».
- Algunos libros traen un vínculo externo ilegible que rompía xlrd (banca 2015-07); lo
  resuelve el parche de `comun.py`.
- Res. SBS 2368-2023: desde 2024-10 cambia la tipificación de los créditos empresariales
  (nota al pie); los deudores corporativos/grandes/medianas/pequeñas/micro no son del todo
  comparables antes y después.
- CMAC trae «TOTAL CAJAS MUNICIPALES DE AHORRO Y CRÉDITO» (sin CMCP Lima) y luego el total con
  CMCP: se queda solo el ÚLTIMO total.
- Una columna con rótulo desconocido, o una fila con cifras y sin nombre, levanta ValueError.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from lector import comun

VARIABLE = "numero_deudores"
UNIDAD = "numero"

TIPOS = [  # (regex sobre la etiqueta normalizada, token); el orden importa
    (r"^total\b", "total"),
    (r"corporativ", "corporativos"),
    (r"grandes? empresas", "grandes_empresas"),
    (r"medianas? empresas", "medianas_empresas"),
    (r"pequenas? empresas", "pequenas_empresas"),
    (r"micro ?empresas", "microempresas"),
    (r"consumo", "consumo"),
    (r"hipotecari", "hipotecarios"),
]
SUBTIPOS = [(r"^no revolventes?$", "consumo_no_revolvente"), (r"^revolventes?$", "consumo_revolvente")]
NOTA_RE = re.compile(r"^\s*(nota|fuente|\d+\s*/|\*|\(\*\)|http)", re.IGNORECASE)


def _token(texto, tabla) -> str | None:
    n = comun.norm(texto)
    return next((t for patron, t in tabla if re.search(patron, n)), None) if n else None


def leer(ruta: Path, subsistema: str, periodo: int) -> list[dict]:
    out: list[dict] = []
    for hoja, df in comun.abrir(ruta).items():
        out += _leer_hoja(str(hoja).strip(), df, subsistema)
    return out


def _cabecera(df: pd.DataFrame) -> tuple[int, int] | None:
    """(fila, columna) de la celda «Empresas» que encabeza la columna de entidades."""
    nr, nc = df.shape
    for i in range(min(nr, 30)):
        for j in range(nc):
            if comun.norm(df.iat[i, j]) in ("empresas", "empresa"):
                return i, j
    return None


def _leer_hoja(hoja: str, df: pd.DataFrame, subsistema: str) -> list[dict]:
    nr, nc = df.shape
    pos = _cabecera(df)
    if pos is None:
        if any(comun.a_numero(v) is not None for v in df.to_numpy().ravel()):
            raise ValueError(f"hoja {hoja!r}: tiene cifras pero no se encontró la cabecera «Empresas»")
        return []
    h, je = pos
    tipos: dict[int, str] = {}
    for j in range(je + 1, nc):
        v = df.iat[h, j]
        if not comun.norm(v):
            continue
        t = _token(v, TIPOS)
        if t is None:
            raise ValueError(f"hoja {hoja!r}: columna de tipo desconocida {comun.limpiar(v)!r}")
        tipos[j] = t
    if "total" not in tipos.values() or len(tipos) < 5:
        raise ValueError(f"hoja {hoja!r}: cabecera incompleta {sorted(tipos.values())}")

    # Filas bajo la cabecera y antes de la primera entidad: sub-rótulos de consumo.
    i = h + 1
    subtipos: dict[int, str] = {}
    while i < nr and not comun.norm(df.iat[i, je]):
        for j in range(je + 1, nc):
            v = df.iat[i, j]
            if not comun.norm(v):
                continue
            s = _token(v, SUBTIPOS)
            if s is None:
                if comun.a_numero(v) is not None:
                    raise ValueError(f"hoja {hoja!r} fila {i}: cifras sin nombre de entidad")
                raise ValueError(f"hoja {hoja!r} fila {i}: sub-rótulo desconocido {comun.limpiar(v)!r}")
            if tipos.get(j) != "consumo":
                raise ValueError(f"hoja {hoja!r} fila {i}: «{comun.limpiar(v)}» fuera de la columna de consumo")
            subtipos[j] = s
        i += 1
    # Solo si el consumo viene en dos columnas (revolvente y no revolvente) se separa; un
    # «Revolventes» suelto sobre la única columna de consumo es un rótulo heredado.
    if len(set(subtipos.values())) == 2:
        tipos.update(subtipos)
    elif list(tipos.values()).count("consumo") > 1:
        raise ValueError(f"hoja {hoja!r}: varias columnas de consumo sin sub-rótulo")

    filas: dict[int, list[dict]] = {}
    for i in range(i, nr):
        nombre = df.iat[i, je]
        if isinstance(nombre, str) and NOTA_RE.match(nombre):
            break
        cifras = [j for j in tipos if comun.a_numero(df.iat[i, j]) is not None]
        if not cifras:
            continue
        if not comun.norm(nombre):
            if all(comun.a_numero(df.iat[i, j]) == 0 for j in cifras):
                continue  # fila separadora con ceros sueltos
            raise ValueError(f"hoja {hoja!r} fila {i}: cifras sin nombre de entidad")
        filas[i] = [comun.registro(hoja, nombre, VARIABLE, tipos[j], df.iat[i, j], UNIDAD) for j in cifras]
    totales = [i for i in filas if comun.es_total(df.iat[i, je])]
    return [r for i, regs in filas.items() if i not in totales[:-1] for r in regs if r]


def validar_totales(df: pd.DataFrame, tolerancia: float = 0.005) -> pd.DataFrame:
    """Validación propia: el conteo de deudores se consolida, así que las sumas son COTAS.

    Reglas (columna `regla`), se listan solo las violaciones:
    - `suma_entidades<total`: por periodo × subsistema × tipo, la suma de entidades debe ser
      ≥ el total del subsistema publicado (nota 1/: el total cuenta una vez al deudor que está
      en varias entidades).
    - `suma_tipos<total_entidad`: por entidad, la suma de los tipos debe ser ≥ su total
      (nota 2/: el total de la entidad cuenta una vez al deudor con varios tipos).
    - `max_tipo>total_entidad`: ningún tipo puede superar el total de la entidad.
    Columnas: las de `comun.validar_totales` + `entidad_original` y `regla`.
    """
    claves = ["periodo", "subsistema", "codigo", "hoja", "variable", "apertura", "unidad"]
    cols = claves + ["entidad_original", "suma_entidades", "total", "dif_rel", "regla"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    partes = []
    tot = df[df["es_total"]].groupby(claves)["valor"].sum().rename("total")
    ent = df[~df["es_total"]].groupby(claves)["valor"].sum().rename("suma_entidades")
    x = pd.concat([ent, tot], axis=1, join="inner").reset_index()
    x["entidad_original"] = ""
    x["regla"] = "suma_entidades<total"
    partes.append(x[x["suma_entidades"] < x["total"] * (1 - tolerancia)])

    por_ent = ["periodo", "subsistema", "codigo", "hoja", "variable", "unidad", "entidad_original"]
    tipos = df[df["apertura"] != "total"].groupby(por_ent)["valor"].agg(["sum", "max"])
    tot_e = df[df["apertura"] == "total"].set_index(por_ent)["valor"].rename("total")
    y = tipos.join(tot_e, how="inner").reset_index()
    y["apertura"] = "total"
    a = y[y["sum"] < y["total"] * (1 - tolerancia)].assign(regla="suma_tipos<total_entidad",
                                                           suma_entidades=lambda d: d["sum"])
    b = y[y["max"] > y["total"] * (1 + tolerancia)].assign(regla="max_tipo>total_entidad",
                                                          suma_entidades=lambda d: d["max"])
    partes += [a, b]
    out = pd.concat(partes, ignore_index=True)
    out["dif_rel"] = (out["suma_entidades"] - out["total"]).abs() / out["total"].abs().clip(lower=1)
    return out[cols].sort_values(["regla", "dif_rel"], ascending=[True, False])
