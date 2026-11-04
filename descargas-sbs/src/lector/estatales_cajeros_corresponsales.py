"""Lector del tema `estatales-cajeros-corresponsales` (B-5216, p=12, entidades estatales).

Cuadro «Cajeros Automáticos y Cajeros Corresponsales» del Banco de la Nación (desde 2018-06,
«… por Empresa Estatal»), por ubicación. Publicación irregular: 2013-03 → 2026-03, trimestral
(mar, jun, set, dic); 53 archivos revisados uno por uno el 2026-11-03. Fuente: Reporte 30.

Qué publica
-----------
Una fila por distrito: «Empresa» (solo en la primera fila de su bloque), «Ubicación» en tres
columnas (Departamento | Provincia | Distrito; departamento y provincia solo en la primera fila
de su bloque, se rellenan hacia abajo) y las cifras (número). La única entidad es el Banco de la
Nación («NACION» / «NACIÓN»): Agrobanco, COFIDE y el Fondo MiVivienda no tienen cajeros.

Formatos por época (todo se ubica por rótulo: cabecera en la fila con «Empresa»)
------------------------------------------------------------------------------
- 2013-03 → 2013-09: una hoja («Nación», «Public») con «Número de Cajeros Automáticos» y
  «Número de Cajeros Corresponsales 1/», cuya nota 1/ dice «Corresponde al número de
  establecimientos que cuentan con puntos de caja» → esa columna se lee como
  `establecimientos_cajeros_corresponsales` (lo que mide, según la nota). Fila «Total general».
- 2013-12 → 2015-09: dos hojas («CA»/«CC», «CAP»/«CCP», «13»/«14»): cajeros automáticos y
  cajeros corresponsales («Número de establecimientos con Cajeros Corresponsales 1/», «Número de
  Cajeros Corresponsales 2/»). Fila «Total general» / «Total General» / «Total».
- 2015-12 → 2026-03: dos hojas («CCA (P)»/«CC (P)», desde 2018-06 «Est_CCA (P)» y «Est_CC_(P)»
  / «Est_CC (P)»), rótulos «Cajeros Automáticos», «Establecimientos con Cajeros Corresponsales»
  y «Cajeros Corresponsales*». Sin fila de total.

Variables (unidad `numero`)
---------------------------
  (Número de) Cajeros Automáticos                          → cajeros_automaticos
  (Número de) establecimientos con Cajeros Corresponsales  → establecimientos_cajeros_corresponsales
  (Número de) Cajeros Corresponsales                       → cajeros_corresponsales
     (salvo 2013-03 → 2013-09, ver arriba: → establecimientos_cajeros_corresponsales)
Hasta 2016 los establecimientos y los cajeros corresponsales coinciden fila por fila; después
difieren (un establecimiento puede tener varios cajeros corresponsales).

Apertura: `departamento|provincia|distrito` (orden fijo), o `total`
------------------------------------------------------------------
- departamento: token de `creditos_departamento.DEPARTAMENTOS` (amazonas, ancash, …, ucayali;
  callao es departamento).
- provincia y distrito: nombre normalizado con `_token` (minúsculas, sin tildes, no
  alfanuméricos → «_»: «Carmen de la Legua Reynoso» → carmen_de_la_legua_reynoso,
  «Anco-Huallo» → anco_huallo). Variantes de escritura del mismo lugar unificadas en
  `PROVINCIAS_ALIAS` / `DISTRITOS_ALIAS` (casi todas: 2013-2015 frente a 2015-12 →).
  Distritos homónimos de provincias distintas no se confunden: la clave es la terna.
- `total`: la fila «Total general» / «Total» (2013-03 → 2015-09), que es el total del Banco de la
  Nación (única entidad de la hoja) y se guarda con su nombre como entidad. Para una serie
  completa del total nacional, sume los distritos (sin la apertura `total`); `validar_totales`
  comprueba que esa suma iguale al total publicado.

Trampas
-------
- 2019-06, hoja «Est_CCA (P)»: con el título «Cajeros Automáticos por Empresa Estatal» y fecha
  30-06-2019 trae los cajeros automáticos de FINANCIERAS (CrediScotia, Financiera Confianza,
  Credinka, TFC), no los del Banco de la Nación: error de origen. Esa hoja se descarta (está en
  `HOJAS_AJENAS`, y solo si de verdad no trae ninguna entidad estatal; si no, ValueError): el BN
  queda sin cajeros automáticos en 2019-06. Ojo: el maestro resuelve nombres de financieras
  aunque se pida el subsistema estatal (alias sin subsistema), así que esa hoja no aparecería
  como «sin entidad»; por eso cualquier otra hoja cuyos nombres resuelvan a una entidad NO
  estatal levanta ValueError.
- 2015-06, hoja «CC»: la fecha dice 31-03-2015, pero las cifras son nuevas (4 357 cajeros
  corresponsales frente a 3 898 en 2015-03): rótulo de fecha viejo; se acepta solo ahí
  (`FECHAS_ERRADAS`). En el resto, una fecha distinta a la del archivo levanta ValueError.
- 2013-09: columna sin rótulo a la derecha con dos cifras de trabajo (3 058 y −151): se ignoran
  las columnas sin rótulo A LA DERECHA de la última columna de datos; con rótulo desconocido o
  entre columnas de datos, ValueError.
- 2022-09 (hoja de corresponsales) y 2022-12 (hoja de cajeros automáticos): la última fila trae
  cifras sin distrito (1 y 1; 1) bajo Ucayali → distrito `no_especificado` dentro de la
  provincia en curso. Solo se admite en la última fila con cifras; en otra, ValueError.
- 2023-03, hoja de corresponsales: fechada 31-03-2023, trae EXACTAMENTE las cifras de 2022-12 en
  los 1 677 distritos (16 074 cajeros y 15 566 establecimientos); la hoja de cajeros automáticos
  sí cambia. Probable repetición de origen: se lee tal como viene (no se corrige aquí).
- Saltos grandes en corresponsales (2020-12: 17 919 → 11 400; 2024-06: 15 806 → 11 951; 2025-03:
  13 334 → 29 359) vienen así en los archivos; no se revisó la causa.
- «-» = sin cajeros (sin registro).
- Un distrito repetido dentro de la misma hoja y entidad levanta ValueError (no se suma a ciegas).
"""
from __future__ import annotations

import datetime as dt
import re
from functools import lru_cache
from pathlib import Path

import pandas as pd

from lector import comun
from lector.creditos_departamento import DEPARTAMENTOS

UNIDAD = "numero"
CA, EST, CC = "cajeros_automaticos", "establecimientos_cajeros_corresponsales", "cajeros_corresponsales"
# Rótulo normalizado (sin «número de» ni notas «1/», «*») → variable.
COLUMNAS = {
    "cajeros automaticos": CA,
    "establecimientos con cajeros corresponsales": EST,
    "cajeros corresponsales": CC,
}
# Nota que redefine «Cajeros Corresponsales 1/» como establecimientos (2013-03 → 2013-09).
NOTA_ESTABLECIMIENTOS_RE = re.compile(r"corresponde al numero de establecimientos")
TOTAL_FILA_RE = re.compile(r"^total( general)?$")
NOTA_RE = re.compile(r"^\s*(nota|fuente|\*|\(\*\)|http|\d+\s*/)", re.IGNORECASE)
NO_ESPECIFICADO = "no_especificado"

# Variantes de escritura del mismo lugar (clave ya normalizada con `_token`).
PROVINCIAS_ALIAS = {
    "prov_const_del_callao": "callao",
    "nazca": "nasca",
}
DISTRITOS_ALIAS = {  # (departamento, provincia, distrito) → distrito
    ("lima", "lima", "pueblo_libre_magdalena_vieja"): "pueblo_libre",
    ("tacna", "tacna", "coronel_gregorio_albarracin_l"): "coronel_gregorio_albarracin_lanchipa",
    ("ucayali", "coronel_portillo", "callaria"): "calleria",
    ("pasco", "pasco", "san_fco_de_asis_de_yarusyacan"): "san_francisco_de_asis_de_yarusyacan",
    ("apurimac", "aymaraes", "huayllo"): "ihuayllo",     # solo 2015-09; Aymaraes no tiene «Huayllo»
    ("puno", "el_collao", "capaso"): "capazo",            # solo 2015-09
    ("ica", "nasca", "nazca"): "nasca",                   # 2013-03 → 2015-09
    ("cusco", "la_convencion", "quimbiri"): "kimbiri",    # 2013-03 → 2013-09
}
# No son variantes (distritos distintos que existen los dos, aunque se parezcan o se alternen en el
# tiempo): Huaya / Hualla (Víctor Fajardo), Soraya / Toraya (Aymaraes), Huacchis / Huachis
# (Huari), Tinicachi / Unicachi (Yunguyo), Cochabamba / Colcabamba (Huaraz), Mollebamba /
# Mollepata (Santiago de Chuco), Huañec / Huangáscar y Omas / Tomas (Yauyos).

# Errores de origen revisados (ver Trampas).
HOJAS_AJENAS = {(201906, "est_cca (p)")}       # (periodo, hoja normalizada): cuadro de otro subsistema
FECHAS_ERRADAS = {(201506, "cc"): 201503}      # (periodo, hoja normalizada): fecha impresa aceptada
ESTATALES = {"banco-de-la-nacion", "agrobanco", "cofide", "fondo-mivivienda"}


def _token(texto) -> str:
    """Clave de lugar: minúsculas, sin tildes, no alfanuméricos → «_»."""
    return re.sub(r"[^a-z0-9]+", "_", comun.norm(texto)).strip("_")


def _texto(v) -> bool:
    """True si la celda trae texto que no es una marca de «sin dato»."""
    return isinstance(v, str) and v.strip().lower() not in comun.SIN_DATO


@lru_cache(maxsize=None)
def _resolver(nombre: str, subsistema: str, periodo: int) -> str | None:
    return comun.resolver_entidad(nombre, subsistema, periodo)[0]


def leer(ruta: Path, subsistema: str, periodo: int) -> list[dict]:
    """Registros de B-5216 de un trimestre; ValueError si el libro no trae el cuadro."""
    out: list[dict] = []
    for hoja, df in comun.abrir(ruta).items():
        out += _leer_hoja(str(hoja).strip(), df, subsistema, periodo)
    if not out:
        raise ValueError("no se encontró ninguna cifra de cajeros")
    return out


def _cabecera(df: pd.DataFrame) -> tuple[int, int] | None:
    """(fila, columna) de la celda «Empresa»; None si no está en las primeras filas."""
    nr, nc = df.shape
    for i in range(min(nr, 20)):
        for j in range(nc):
            if comun.norm(df.iat[i, j]) == "empresa":
                return i, j
    return None


def _fecha(df: pd.DataFrame, h: int) -> int | None:
    """AAAAMM de la fecha de corte impresa sobre la cabecera."""
    for i in range(h):
        for v in df.iloc[i]:
            if isinstance(v, (dt.datetime, pd.Timestamp)):
                return v.year * 100 + v.month
    return None


def _columnas(hoja: str, df: pd.DataFrame, h: int, jt: int) -> dict[int, str]:
    """Columna → variable, por rótulo, a la derecha de la columna Distrito."""
    nr, nc = df.shape
    notas = [comun.norm(v) for v in df.to_numpy().ravel() if isinstance(v, str)]
    nota_est = any(NOTA_ESTABLECIMIENTOS_RE.search(n) for n in notas)
    cols: dict[int, str] = {}
    sin_rotulo: list[int] = []
    for j in range(jt + 1, nc):
        bruto = df.iat[h, j]
        if not _texto(bruto):
            sin_rotulo.append(j)
            continue
        t = re.sub(r"^numero de ", "", comun.norm(bruto))
        if t not in COLUMNAS:
            raise ValueError(f"hoja {hoja!r} col {j}: columna desconocida {comun.limpiar(bruto)!r}")
        var = COLUMNAS[t]
        # «Número de Cajeros Corresponsales 1/» con la nota «1/ Corresponde al número de
        # establecimientos…» (2013-03 → 2013-09) mide establecimientos.
        if var == CC and nota_est and re.search(r"1\s*/\s*$", comun.limpiar(bruto)):
            var = EST
        if var in cols.values():
            raise ValueError(f"hoja {hoja!r}: columna repetida {var!r}")
        cols[j] = var
    if not cols:
        raise ValueError(f"hoja {hoja!r}: cabecera sin columnas de datos")
    ultima = max(cols)
    for j in sin_rotulo:
        if j < ultima and any(comun.a_numero(df.iat[i, j]) is not None for i in range(h + 2, nr)):
            raise ValueError(f"hoja {hoja!r} col {j}: columna sin rótulo con cifras entre columnas de datos")
    return cols


def _leer_hoja(hoja: str, df: pd.DataFrame, subsistema: str, periodo: int) -> list[dict]:
    if df.empty:
        return []
    pos = _cabecera(df)
    if pos is None:
        if any(comun.a_numero(v) is not None for v in df.to_numpy().ravel()):
            raise ValueError(f"hoja {hoja!r}: tiene cifras pero no se encontró la cabecera «Empresa»")
        return []
    h, je = pos
    nr, nc = df.shape
    jd, jp, jt = je + 1, je + 2, je + 3
    sub = [comun.norm(df.iat[h + 1, j]) if j < nc else "" for j in (jd, jp, jt)]
    if sub != ["departamento", "provincia", "distrito"]:
        raise ValueError(f"hoja {hoja!r}: bajo «Ubicación» se esperaba Departamento | Provincia | Distrito, hay {sub}")
    fecha = _fecha(df, h)
    clave_hoja = (periodo, comun.norm(hoja))
    if fecha is None:
        raise ValueError(f"hoja {hoja!r}: sin fecha de corte sobre la cabecera")
    if fecha != periodo and FECHAS_ERRADAS.get(clave_hoja) != fecha:
        raise ValueError(f"hoja {hoja!r}: la fecha del cuadro ({fecha}) no es la del archivo ({periodo})")
    cols = _columnas(hoja, df, h, jt)

    # Filas con cifras, con empresa / departamento / provincia rellenados hacia abajo.
    filas: list[tuple[int, str, str, str, str]] = []   # (fila, empresa, departamento, provincia, distrito)
    totales: list[int] = []
    empresa = dep = prov = None
    for i in range(h + 2, nr):
        e = df.iat[i, je]
        if _texto(e) and NOTA_RE.match(e):
            break
        cifras = [j for j in cols if comun.a_numero(df.iat[i, j]) is not None]
        if _texto(e) and TOTAL_FILA_RE.match(comun.norm(e)):
            if any(_texto(df.iat[i, j]) for j in (jd, jp, jt)):
                raise ValueError(f"hoja {hoja!r} fila {i}: fila de total con ubicación")
            if cifras:
                totales.append(i)
            continue
        if _texto(e):
            empresa = comun.limpiar(e)
            dep = prov = None  # cada empresa empieza su propio bloque de ubicaciones
        if _texto(df.iat[i, jd]):
            d = comun.norm(df.iat[i, jd])
            if d not in DEPARTAMENTOS or DEPARTAMENTOS[d] == "exterior":
                raise ValueError(f"hoja {hoja!r} fila {i}: departamento desconocido {comun.limpiar(df.iat[i, jd])!r}")
            dep, prov = DEPARTAMENTOS[d], None
            if not _texto(df.iat[i, jp]):
                raise ValueError(f"hoja {hoja!r} fila {i}: departamento sin provincia")
        if _texto(df.iat[i, jp]):
            prov = PROVINCIAS_ALIAS.get(_token(df.iat[i, jp]), _token(df.iat[i, jp]))
            if not _texto(df.iat[i, jt]):
                raise ValueError(f"hoja {hoja!r} fila {i}: provincia sin distrito")
        if not cifras:
            if any(_texto(df.iat[i, j]) for j in range(nc)) and not _texto(df.iat[i, jt]):
                raise ValueError(f"hoja {hoja!r} fila {i}: fila con texto que no se reconoce")
            continue
        if empresa is None or dep is None or prov is None:
            raise ValueError(f"hoja {hoja!r} fila {i}: cifras sin empresa, departamento o provincia")
        dist = _token(df.iat[i, jt]) if _texto(df.iat[i, jt]) else NO_ESPECIFICADO
        dist = DISTRITOS_ALIAS.get((dep, prov, dist), dist)
        filas.append((i, empresa, dep, prov, dist))

    if not filas and not totales:
        return []
    # Distrito sin nombre: solo en la última fila con cifras (2022-09, 2022-12).
    for k, (i, *_resto, dist) in enumerate(filas):
        if dist == NO_ESPECIFICADO and k != len(filas) - 1:
            raise ValueError(f"hoja {hoja!r} fila {i}: cifras sin distrito")
    empresas = list(dict.fromkeys(f[1] for f in filas))
    ids = {n: _resolver(n, subsistema, periodo) for n in empresas}
    if clave_hoja in HOJAS_AJENAS:
        if any(i in ESTATALES for i in ids.values()):
            raise ValueError(f"hoja {hoja!r}: figura como cuadro ajeno pero trae una entidad estatal ({ids})")
        return []
    ajenas = {n: i for n, i in ids.items() if i is not None and i not in ESTATALES}
    if ajenas:
        raise ValueError(f"hoja {hoja!r}: entidades que no son estatales {ajenas} (¿cuadro de otro subsistema?)")
    if totales and len(empresas) != 1:
        raise ValueError(f"hoja {hoja!r}: fila de total con {len(empresas)} empresas; no se sabe de quién es")
    if len(totales) > 1:
        raise ValueError(f"hoja {hoja!r}: varias filas de total {totales}")

    out: list[dict] = []
    vistas: set[tuple[str, str]] = set()
    for i, empresa, dep, prov, dist in filas:
        apertura = f"{dep}|{prov}|{dist}"
        if (empresa, apertura) in vistas:
            raise ValueError(f"hoja {hoja!r} fila {i}: ubicación repetida {apertura!r}")
        vistas.add((empresa, apertura))
        for j, var in cols.items():
            r = comun.registro(hoja, empresa, var, apertura, df.iat[i, j], UNIDAD)
            if r:
                out.append(r)
    for i in totales:
        for j, var in cols.items():
            r = comun.registro(hoja, empresas[0], var, "total", df.iat[i, j], UNIDAD)
            if r:
                out.append(r)
    return out


def validar_totales(df: pd.DataFrame, tolerancia: float = 0.005) -> pd.DataFrame:
    """Control interno: suma de distritos = fila «Total general» publicada (2013-03 → 2015-09).

    Por periodo, hoja, entidad y variable. Columnas como las de `comun.validar_totales` +
    `entidad_original` y `regla`; `suma_entidades` es aquí la suma de los distritos. Solo
    violaciones. Se agrega la validación estándar (vacía: no hay total del subsistema).
    """
    claves = ["periodo", "subsistema", "codigo", "hoja", "variable", "apertura", "unidad"]
    cols = claves + ["entidad_original", "suma_entidades", "total", "dif_rel", "regla"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    a = comun.validar_totales(df, tolerancia).assign(entidad_original="", regla="suma_entidades!=total")
    g = ["periodo", "subsistema", "codigo", "hoja", "entidad_original", "variable", "unidad"]
    tot = df[df["apertura"] == "total"].groupby(g)["valor"].sum().rename("total")
    suma = df[df["apertura"] != "total"].groupby(g)["valor"].sum().rename("suma_entidades")
    b = pd.concat([suma, tot], axis=1, join="inner").reset_index()
    b["dif_rel"] = (b["suma_entidades"] - b["total"]).abs() / b["total"].abs().clip(lower=1)
    b = b[b["dif_rel"] > tolerancia].assign(apertura="total", regla="suma_distritos!=total")
    return pd.concat([a, b], ignore_index=True).reindex(columns=cols).sort_values(
        ["regla", "dif_rel"], ascending=[True, False])
