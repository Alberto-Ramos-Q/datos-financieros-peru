"""Lector del tema `creditos-tipo-modalidad-porcentaje` (B-3235, C-1243, C-2248, C-4235).

SUSTITUTO de `creditos-tipo-modalidad-moneda` para financieras, CMAC, CRAC y EC antes de 2015-09,
cuando la SBS aún no publicaba el cuadro con moneda (B-3272, C-1261, C-2264, C-4253). Se lee
de 2010-07 (financieras: 2010-10, primer mes publicado) a 2015-08: `desde`/`hasta` en
`config/series.csv`. Agregado el 2026-10-28 con la extensión del boletín a 2010-07. Banca no
lo necesita: B-2359 (con moneda) existe en todo el periodo.

Cuadro «Estructura de los créditos directos según tipo y modalidad» (en porcentaje). Fuente:
balance de comprobación.

Qué publica
-----------
- Entidades en COLUMNAS (una por entidad, sin moneda), con la columna del total del subsistema.
  CMAC trae además «CAJAS MUNICIPALES DE AHORRO Y CREDITO» (subtotal sin la CMCP Lima, que se
  descarta) y «TOTAL CAJAS MUNICIPALES».
- Filas: mismos bloques que el cuadro con moneda (fila de tipo «Créditos corporativos»… y sus
  modalidades) y al pie «Total Créditos Directos (En Miles S/.)» con el saldo de cada entidad.
- Cada celda es el % del crédito directo TOTAL de la entidad (los tipos suman 100 por columna),
  no el % dentro del tipo.

Variables y apertura (`tipo|modalidad`, mismos tokens que `creditos-tipo-modalidad-moneda`
sin el nivel de moneda; «Otros 1/» → `otros`)
---------------------------------------------------------------------------------------------
- `participacion_creditos_directos` (porcentaje): % publicado.
- `creditos_directos` (miles_soles): fila «Total Créditos Directos»; apertura `total|total`.
- `creditos_directos_calculado` (miles_soles): monto DERIVADO aquí = % × total / 100, misma
  apertura que la participación. Comparable con la apertura `<tipo>|<modalidad>|total` del
  cuadro con moneda; NO sirve para la dolarización (no hay moneda).
Lo que viene de este sustituto se reconoce por el tema (y el código B-3235/C-1243/C-2248/C-4235).

Trampas
-------
- «Créditos pequeñas empresas» (sin «a») y «Otros 1/»: variantes de rótulo propias de este cuadro.
- CMAC, CRAC y EC 2010-07 → 2010-09: un solo bloque «Créditos a actividades empresariales *» → tipo
  `empresariales`. CRAC 2015-06 → 2015-08: una columna rotulada «0» con solo ceros (se ignora).
- B-3235 2014-12: una fila sin rótulo y solo ceros bajo el consumo; se ignora (con alguna cifra
  distinta de 0 sería error).
- Un rótulo de fila desconocido con cifras, o una cabecera de columna que no sea entidad, total
  ni el subtotal de CMAC, levanta ValueError.
- Validación propia (`validar_totales`): la estándar sobre los montos + la suma de los tipos
  por entidad ≈ 100 (±0,5 pp).
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import pandas as pd

from lector import comun
from lector.creditos_tipo_modalidad_moneda import MODALIDADES as _MODALIDADES, TIPOS as _TIPOS

PCT, MONTO, CALC = "participacion_creditos_directos", "creditos_directos", "creditos_directos_calculado"
MODALIDADES = _MODALIDADES + [(r"^otros$", "otros")]  # «Otros 1/» (la nota 1/ la quita `norm`)
TIPOS = _TIPOS + [(r"^creditos? (a )?pequenas empresas$", "pequenas_empresas")]  # «Créditos pequeñas empresas»
TIPOS += [(r"^creditos a actividades empresariales$", "empresariales")]  # cajas y EC 2010-07 → 2010-09
TOTAL_FILA_RE = re.compile(r"^total creditos directos\b")
SUBTOTAL_COL_RE = re.compile(r"^cajas municipales de ahorro y credito$")  # CMAC sin CMCP Lima
FIN_RE = re.compile(r"^(nota|fuente|http|1/|\*)")


def _token(texto, tabla) -> str | None:
    n = re.sub(r"\s+", " ", comun.norm(texto))
    return next((t for patron, t in tabla if re.match(patron, n)), None) if n else None


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
    j0 = min(j for j in range(nc) if _entidad(df.iat[h, j], subsistema))
    columnas: dict[int, str] = {}
    descartadas: set[int] = set()
    for j in range(j0, nc):
        v = df.iat[h, j]
        if not isinstance(v, str) or not v.strip():
            # CRAC 2015-06 → 2015-08: columna con «0» por nombre (entidad que salió) y solo ceros.
            if all(comun.a_numero(df.iat[i, j]) in (None, 0) for i in range(h + 1, nr)):
                descartadas.add(j)
            continue
        if _entidad(v, subsistema):
            columnas[j] = v
        elif SUBTOTAL_COL_RE.match(comun.norm(v)):
            descartadas.add(j)
        else:
            raise ValueError(f"hoja {hoja!r} col {j}: cabecera no reconocida {v!r}")
    totales = [j for j, n in columnas.items() if comun.es_total(n)]
    for j in totales[:-1]:  # varios totales: se queda el último (todo el subsistema)
        descartadas.add(j)
        del columnas[j]

    filas: list[tuple[str, str, dict[int, float]]] = []  # (tipo, modalidad, {col: valor})
    total_fila: dict[int, float] = {}
    tipo = None
    for i in range(h + 1, nr):
        textos = [df.iat[i, k] for k in range(j0) if isinstance(df.iat[i, k], str) and df.iat[i, k].strip()]
        etq = textos[-1] if textos else ""
        n = comun.norm(etq)
        if n and FIN_RE.match(n):
            break
        cifras = {j: comun.a_numero(df.iat[i, j]) for j in range(j0, nc)}
        cifras = {j: x for j, x in cifras.items() if x is not None}
        if TOTAL_FILA_RE.match(n):
            total_fila = {j: x for j, x in cifras.items() if j in columnas}
            continue
        t = _token(etq, TIPOS)
        if t:
            tipo, modalidad = t, "total"
        else:
            modalidad = _token(etq, MODALIDADES)
        if not cifras:
            continue
        if not n and all(x == 0 for x in cifras.values()):
            continue  # fila sin rótulo y solo ceros (B-3235 2014-12, tras «Otros» de consumo)
        if modalidad is None or tipo is None:
            raise ValueError(f"hoja {hoja!r} fila {i}: etiqueta desconocida {etq!r}")
        fuera = [j for j in cifras if j not in columnas and j not in descartadas]
        if fuera:
            raise ValueError(f"hoja {hoja!r} fila {i}: cifras en columnas sin entidad {fuera}")
        filas.append((tipo, modalidad, {j: x for j, x in cifras.items() if j in columnas}))

    out: list[dict] = []
    for j, nombre in columnas.items():
        total = total_fila.get(j)
        if total is not None:
            out.append(comun.registro(hoja, nombre, MONTO, "total|total", total, "miles_soles"))
        for tipo, modalidad, valores in filas:
            if j not in valores:
                continue
            ap = f"{tipo}|{modalidad}"
            out.append(comun.registro(hoja, nombre, PCT, ap, valores[j], "porcentaje"))
            if total is not None:
                out.append(comun.registro(hoja, nombre, CALC, ap, round(valores[j] * total / 100, 5),
                                          "miles_soles"))
    return [r for r in out if r]


def validar_totales(df: pd.DataFrame, tolerancia: float = 0.005) -> pd.DataFrame:
    """Validación estándar sobre los montos + suma de los tipos por entidad ≈ 100.

    Reglas (columna `regla`), solo violaciones:
    - `suma_entidades!=total`: `comun.validar_totales` (montos en miles de soles).
    - `suma_pct!=100`: la suma de las filas de tipo (`<tipo>|total`) de una entidad con saldo
      distinto de 0 se aleja de 100 en más de 0,5 pp.
    """
    claves = ["periodo", "subsistema", "codigo", "hoja", "variable", "apertura", "unidad"]
    cols = claves + ["entidad_original", "suma_entidades", "total", "dif_rel", "regla"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    a = comun.validar_totales(df, tolerancia).assign(entidad_original="", regla="suma_entidades!=total")
    por_ent = ["periodo", "subsistema", "codigo", "hoja", "entidad_original"]
    tipos = df[(df["variable"] == PCT) & df["apertura"].str.endswith("|total")]
    pct = tipos.groupby(por_ent)["valor"].sum().rename("suma_entidades")
    tot = df[(df["variable"] == MONTO) & (df["valor"] != 0)].set_index(por_ent)["valor"]
    b = pct[pct.index.isin(tot.index)].reset_index()
    b = b[(b["suma_entidades"] - 100).abs() > 0.5].assign(
        variable=PCT, apertura="total|total", unidad="porcentaje", total=100.0, regla="suma_pct!=100")
    b["dif_rel"] = (b["suma_entidades"] - 100).abs() / 100
    return pd.concat([a, b], ignore_index=True)[cols].sort_values(["regla", "dif_rel"], ascending=[True, False])
