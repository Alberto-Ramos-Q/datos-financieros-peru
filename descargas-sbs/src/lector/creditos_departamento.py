"""Lector del tema `creditos-departamento` (B-2349, B-3228, C-1223, C-2223, C-4219).

Cuadro «Estructura de los Créditos Directos por Departamento» (en porcentaje; fuente: Anexo
N° 10 Depósitos, Colocaciones y Personal por Oficinas).

Qué publica
-----------
Entidades en FILAS (columna rotulada «Empresas») y en COLUMNAS los departamentos: el % del
crédito directo de cada entidad colocado en cada departamento (cada fila suma 100) y una
última columna «TOTAL (En miles de soles)» con el crédito directo total de la entidad.
- Banca agrega la columna «Sucursales en el Exterior».
- Las empresas de créditos (y a veces financieras/CRAC) solo listan los departamentos donde
  opera alguna entidad: las columnas se leen SIEMPRE por rótulo, nunca por posición.
- Los rótulos cambian de tildes entre cuadros («Apurímac»/«Apurimac», «San Martín»/«San
  Martin», «Huánuco»/«Huanuco»): se normalizan con `comun.norm`.
- Fila final del total del subsistema («TOTAL BANCA MÚLTIPLE»).

Variables y apertura (`departamento`, un nivel)
-----------------------------------------------
- `participacion_creditos_directos` (porcentaje): % publicado. Apertura = departamento:
  amazonas, ancash, apurimac, arequipa, ayacucho, cajamarca, callao, cusco, huancavelica,
  huanuco, ica, junin, la_libertad, lambayeque, lima, loreto, madre_de_dios, moquegua, pasco,
  piura, puno, san_martin, tacna, tumbes, ucayali, exterior («Sucursales en el Exterior»).
- `creditos_directos` (miles_soles): columna TOTAL publicada; apertura `total`.
- `creditos_directos_calculado` (miles_soles): monto por departamento DERIVADO aquí =
  participación × TOTAL / 100 (el % viene con precisión completa, así que reproduce el monto
  de origen salvo redondeo). Misma apertura que la participación. No es una cifra impresa en
  el cuadro: se agrega para no tener que recalcularlo en cada proyecto.

Trampas
-------
- La columna TOTAL dice «(En miles de soles)» en unos cuadros y solo «TOTAL» en otros (CMAC
  2015, EC): la unidad es siempre miles de soles (cuadra con el ranking de créditos).
- «-» = la entidad no opera en ese departamento (sin registro); 0 también aparece.
- CMAC: bajo la cabecera hay una fila de códigos de trabajo sin nombre (100, 200, … 2500) que
  se ignora; trae «TOTAL CAJAS MUNICIPALES DE AHORRO Y CRÉDITO» (sin CMCP Lima), «CMCP Lima» y
  «TOTAL CAJAS MUNICIPALES»: se queda solo el ÚLTIMO total.
- «EC TOTAL Servicios Financieros» es una entidad, no un total (TOTAL_RE exige empezar por
  «total»).
- Entidades sin créditos (p. ej. Deutsche Bank 2015) traen «-» en toda la fila: sin registros.
- Validación propia (`validar_totales`): la estándar sobre los montos (suma de entidades vs.
  total del subsistema, por departamento y en el TOTAL) + la suma de % por entidad ≈ 100.
- Un rótulo de columna desconocido, o una fila con cifras y sin nombre después de la primera
  entidad, levanta ValueError.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from lector import comun

DEPARTAMENTOS = {
    "amazonas": "amazonas", "ancash": "ancash", "apurimac": "apurimac", "arequipa": "arequipa",
    "ayacucho": "ayacucho", "cajamarca": "cajamarca", "callao": "callao", "cusco": "cusco",
    "cuzco": "cusco", "huancavelica": "huancavelica", "huanuco": "huanuco", "ica": "ica",
    "junin": "junin", "la libertad": "la_libertad", "lambayeque": "lambayeque", "lima": "lima",
    "loreto": "loreto", "madre de dios": "madre_de_dios", "moquegua": "moquegua",
    "pasco": "pasco", "piura": "piura", "puno": "puno", "san martin": "san_martin",
    "tacna": "tacna", "tumbes": "tumbes", "ucayali": "ucayali",
    "sucursales en el exterior": "exterior",
}
TOTAL_COL_RE = re.compile(r"^total\b\s*(\((en )?miles de (nuevos )?soles\))?$")
NOTA_RE = re.compile(r"^\s*(nota|fuente|\d+\s*/|\*|\(\*\)|http)", re.IGNORECASE)
PCT, MONTO, CALC = "participacion_creditos_directos", "creditos_directos", "creditos_directos_calculado"


def leer(ruta: Path, subsistema: str, periodo: int) -> list[dict]:
    out: list[dict] = []
    for hoja, df in comun.abrir(ruta).items():
        out += _leer_hoja(str(hoja).strip(), df, subsistema)
    return out


def _cabecera(df: pd.DataFrame) -> tuple[int, int] | None:
    """(fila, columna) de «Empresas» en la fila que tiene al menos 3 departamentos."""
    nr, nc = df.shape
    for i in range(min(nr, 30)):
        txt = [comun.norm(v) for v in df.iloc[i]]
        if sum(t in DEPARTAMENTOS for t in txt) >= 3 and "empresas" in txt:
            return i, txt.index("empresas")
    return None


def _leer_hoja(hoja: str, df: pd.DataFrame, subsistema: str) -> list[dict]:
    nr, nc = df.shape
    pos = _cabecera(df)
    if pos is None:
        if any(comun.a_numero(v) is not None for v in df.to_numpy().ravel()):
            raise ValueError(f"hoja {hoja!r}: tiene cifras pero no se encontró la cabecera de departamentos")
        return []
    h, je = pos
    deps: dict[int, str] = {}
    j_total = None
    for j in range(je + 1, nc):
        t = comun.norm(df.iat[h, j])
        if not t:
            continue
        if t in DEPARTAMENTOS:
            if DEPARTAMENTOS[t] in deps.values():
                raise ValueError(f"hoja {hoja!r}: departamento repetido {t!r}")
            deps[j] = DEPARTAMENTOS[t]
        elif TOTAL_COL_RE.match(t):
            if j_total is not None:
                raise ValueError(f"hoja {hoja!r}: dos columnas TOTAL")
            j_total = j
        else:
            raise ValueError(f"hoja {hoja!r}: columna desconocida {comun.limpiar(df.iat[h, j])!r}")
    if j_total is None:
        raise ValueError(f"hoja {hoja!r}: sin columna TOTAL (miles de soles)")
    cols = list(deps) + [j_total]

    filas: dict[int, list[dict]] = {}
    hubo_entidad = False
    for i in range(h + 1, nr):
        nombre = df.iat[i, je]
        if isinstance(nombre, str) and NOTA_RE.match(nombre):
            break
        cifras = [j for j in cols if comun.a_numero(df.iat[i, j]) is not None]
        if not cifras:
            continue
        if not comun.norm(nombre):
            if not hubo_entidad or all(comun.a_numero(df.iat[i, j]) == 0 for j in cifras):
                continue  # códigos de trabajo bajo la cabecera (CMAC: 100, 200…) o ceros sueltos
            raise ValueError(f"hoja {hoja!r} fila {i}: cifras sin nombre de entidad")
        hubo_entidad = True
        total = comun.a_numero(df.iat[i, j_total])
        regs = [comun.registro(hoja, nombre, MONTO, "total", total, "miles_soles")]
        for j, dep in deps.items():
            pct = comun.a_numero(df.iat[i, j])
            regs.append(comun.registro(hoja, nombre, PCT, dep, pct, "porcentaje"))
            if pct is not None and total is not None:
                regs.append(comun.registro(hoja, nombre, CALC, dep, pct * total / 100, "miles_soles"))
        filas[i] = regs
    totales = [i for i in filas if comun.es_total(df.iat[i, je])]
    return [r for i, regs in filas.items() if i not in totales[:-1] for r in regs if r]


def validar_totales(df: pd.DataFrame, tolerancia: float = 0.005) -> pd.DataFrame:
    """Validación estándar sobre los montos + suma de participaciones por entidad.

    Reglas (columna `regla`), solo violaciones:
    - `suma_entidades!=total`: `comun.validar_totales` (montos en miles de soles: el TOTAL y el
      monto calculado por departamento).
    - `suma_pct!=100`: por entidad (y por el total del subsistema), la suma de participaciones
      se aleja de 100 en más de 0,5 pp (solo entidades con TOTAL distinto de 0).
    """
    claves = ["periodo", "subsistema", "codigo", "hoja", "variable", "apertura", "unidad"]
    cols = claves + ["entidad_original", "suma_entidades", "total", "dif_rel", "regla"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    a = comun.validar_totales(df, tolerancia).assign(entidad_original="", regla="suma_entidades!=total")
    por_ent = ["periodo", "subsistema", "codigo", "hoja", "entidad_original"]
    pct = df[df["variable"] == PCT].groupby(por_ent)["valor"].sum().rename("suma_entidades")
    tot = df[(df["variable"] == MONTO) & (df["valor"] != 0)].set_index(por_ent)["valor"]
    b = pct[pct.index.isin(tot.index)].reset_index()
    b = b[(b["suma_entidades"] - 100).abs() > 0.5].assign(
        variable=PCT, apertura="total", unidad="porcentaje", total=100.0, regla="suma_pct!=100")
    b["dif_rel"] = (b["suma_entidades"] - 100).abs() / 100
    return pd.concat([a, b], ignore_index=True)[cols].sort_values(["regla", "dif_rel"], ascending=[True, False])
