"""Lector de B-5215 «Créditos Directos y Depósitos por Oficinas» (tema `estatales-creditos-depositos-oficinas`, p=12, entidades estatales).

Cuadro «Depósitos y Créditos por Oficina del Banco de la Nación [y Agrobanco]» (en miles de
soles; fuente: Anexo N° 10 Depósitos, Colocaciones y Personal por Oficina). Subsistema
`entidades-estatales` (agregado el 2026-11-03): no entra en los totales de los 5 subsistemas.

Qué publica
-----------
Una fila por OFICINA: Empresa | Ubicación (Departamento | Provincia | Distrito) | Código
Oficina | Depósitos a la Vista, de Ahorro y a Plazo (M.N | M.E. | Total cada uno) | Total
Depósitos | Créditos Directos (M.N | M.E.) | Total Créditos. Cabecera en dos filas («Empresa
… Total Créditos» y debajo «Departamento | Provincia | Distrito | M.N | M.E. | Total …»).

Formatos por época (siempre 18 columnas con los mismos rótulos; se ubican por rótulo)
-------------------------------------------------------------------------------------
- 2011-01 → 2011-12: hoja «Hoja1» (+ «Hoja2»/«Hoja3» vacías), cabecera en la fila 4. TODAS las
  celdas vienen llenas (empresa y ubicación repetidas en cada fila). Sin «Total general».
- 2012-01 → 2013-10: «Hoja1», cabecera en la fila 3, celdas COMBINADAS, sin «Total general».
- 2013-11 → 2015-08: hojas «Hoja2», «Hoja4», «Hoja5», «Créditos y depósitos por of…»; celdas
  combinadas y fila final «Total general». 2013-12 trae además «Hoja1» con el Anexo 10 CRUDO
  (27 columnas «Concepto | Entidad | Fecha | Cod Pais …», en SOLES): se descarta; oficina por
  oficina coincide exactamente con la hoja publicada × 1000 (474 oficinas).
  2015-04 → 2015-08: sin fecha en el título.
- 2015-09 → 2026-09: hoja «12» (2015-10: «8N»), título desde la fila 1, cabecera en la fila 5
  (2016-10: fila 4, con «Actualizado al 23-12-2016»), unidad «(En miles de soles)».
- Empresas: solo «NACION» hasta 2016-07; «AGROBANCO» desde 2016-08 (el título lo nombra desde
  2017-01); «COFIDE» UNA sola vez (2018-11: una oficina en Lima | Lima | San Isidro).

Variables (miles_soles) y apertura `moneda|departamento|provincia|distrito|codigo_oficina`
------------------------------------------------------------------------------------------
- `depositos_vista`, `depositos_ahorro`, `depositos_plazo`: moneda `mn`, `me`, `total`.
- `depositos_totales`: solo `total` (el cuadro no abre «Total Depósitos» por moneda).
- `creditos_directos`: `mn`, `me` («Créditos Directos») y `total` («Total Créditos»).
- La ME viene en miles de soles (equivalente): MN + ME = Total.
- departamento: token canónico de `lector.creditos_departamento.DEPARTAMENTOS` (amazonas,
  la_libertad, madre_de_dios, san_martin…). provincia y distrito: `comun.norm` (minúsculas,
  sin tildes) y todo lo que no sea letra o dígito → «_» («Jose Luis Bustamante y Rivero» →
  `jose_luis_bustamante_y_rivero`, «Callería» → `calleria`). Se conservan como se publican:
  p. ej. la provincia del Callao es `callao` hasta 2014-01 y `prov_const_del_callao` desde
  2014-02; el distrito de Coronel Portillo es `callaria` hasta 2022-12 y `calleria` después.
- codigo_oficina: el código entero publicado («618»); único por empresa y mes (se verifica).
  Vacío en dos casos documentados abajo (2014-03 y la oficina de Huarmey 2023-11 → 2025-06).
- `entidad_original`: texto de la columna Empresa («NACION», «AGROBANCO», «COFIDE»).

Relleno de las celdas combinadas
--------------------------------
Desde 2012 la empresa, el departamento, la provincia y el DISTRITO solo vienen en la primera
fila de su grupo (varias oficinas pueden compartir distrito: Arequipa, San Isidro…). Cada fila
«empieza» en un nivel (empresa, departamento, provincia, distrito, o ninguno = otra oficina del
mismo distrito): debe traer llenos ese nivel y todos los inferiores, y se heredan solo los
superiores. Las columnas se fijan por rótulo, así que un distrito nunca se toma por provincia;
una fila con un hueco intermedio levanta ValueError (salvo el caso Huarmey, ver abajo).

Control con el «Total general» y oficinas omitidas
--------------------------------------------------
«Total general» (desde 2013-11; falta en 2017-11, 2019-10/11, 2020-01/03/04/06/07) suma todas
las empresas. No se emite (no es el total de un subsistema y el maestro no lo reconoce), pero
se compara, columna por columna, con la suma de las oficinas leídas:
- suma > total → ValueError (filas de más: se leyó algo que no es oficina).
- suma = total → libro «verificado».
- suma < total → libro «incompleto»: la SBS BORRÓ filas de oficinas del cuadro pero las dejó en
  el total. Ocurre en 2026-04 → 2026-09 (p. ej. 2026-08: faltan 324 557 de depósitos y
  105 571 de créditos; el «Total general» sí coincide con el balance). Al borrar la primera fila de un grupo combinado desaparece su rótulo y las
  oficinas siguientes quedan bajo el rótulo del grupo ANTERIOR (p. ej. 2026-04: Agrobanco 53
  «Mariscal Ramón Castilla» bajo Lima porque se borró Iquitos, primera fila de Loreto; 2026-07:
  BN 791 y 852 bajo «San Miguel» porque se borró la 483, primera de «Santa Anita»). En esos
  libros, la ubicación HEREDADA de cada oficina se toma de los 12 meses verificados anteriores
  (la más reciente para el mismo código y empresa) cuando los niveles impresos en su propia
  fila coinciden con los de ese mes; lo impreso en la fila nunca se cambia (2026-08 reimprime
  algunas oficinas con otra ubicación: BN 624 en la nueva provincia Putumayo, 203 en Huaytará,
  134 en Guadalupe; se respetan), y las oficinas nuevas heredan como siempre.
  Las oficinas omitidas no se pueden recuperar: sus montos solo están en el total.
- 2026-07 y 2026-08: DEBAJO del «Total general» hay un bloque residual (oficinas con cifras
  diminutas y un segundo «Total general»). Se lee solo hasta el PRIMER total.

Errores de origen documentados
------------------------------
- 2014-03: el cuadro viene AGREGADO POR DISTRITO (435 filas en vez de ~477) y la columna
  «Código Oficina» es la SUMA de los códigos de sus oficinas (Chiclayo 44 + 533 = «577»,
  Guadalupe 137 + 608 = «745»), que choca con códigos reales. Ese mes se emite codigo_oficina
  vacío (`CODIGO_SUMADO`); los totales sí cuadran con el balance.
- 2023-11 → 2025-06: la oficina de Huarmey (Áncash, código 127 los demás meses) viene con la
  provincia pero sin distrito ni código. Se emite `…|ancash|huarmey||` (sin inventar datos).
- 2018-11: faltan 9 oficinas de Agrobanco (también en el «Total general»: el cuadro cuadra
  consigo mismo pero queda 116 207 por debajo del balance de Agrobanco).
- 2014-12: créditos del BN 181 588 por debajo del balance (depósitos exactos).
Fuera de esos meses, la suma de oficinas del BN y de Agrobanco coincide con el balance del
mismo mes (créditos = vigentes + refinanciados y reestructurados + atrasados; depósitos =
obligaciones con el público − otras obligaciones + depósitos del sistema financiero).

Otras trampas
-------------
- Notas al pie («Nota: …», «Fuente: Anexo 10 …») cierran la tabla.
- Agrobanco no capta depósitos: publica 0 en todas las columnas de depósitos (se conservan).
- La fecha del título (celda fecha o «Al 30 de Setiembre de 2011») debe ser el mes del archivo.
- Validación propia (`validar_totales`): por oficina, vista + ahorro + plazo = total depósitos
  y MN + ME = total en cada variable.
- `diagnostico(ruta, subsistema, periodo)` devuelve el estado del libro (verificado,
  sin_total, incompleto), lo que falta frente al «Total general» y las ubicaciones corregidas.
- Rótulo de columna desconocido, empresa que el maestro no reconoce, departamento fuera de la
  lista, unidad distinta de miles de soles, libro sin hoja del cuadro o con dos, hoja con
  cifras sin cabecera, oficina repetida, o libro incompleto sin mes verificado anterior para
  corregir ubicaciones: ValueError.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import pandas as pd

from lector import comun
from lector.creditos_departamento import DEPARTAMENTOS

# (rótulo superior, rótulo inferior) normalizados → (variable, moneda)
COLUMNAS = {
    ("depositos a la vista", "m.n"): ("depositos_vista", "mn"),
    ("depositos a la vista", "m.e."): ("depositos_vista", "me"),
    ("depositos a la vista", "total"): ("depositos_vista", "total"),
    ("depositos de ahorro", "m.n"): ("depositos_ahorro", "mn"),
    ("depositos de ahorro", "m.e."): ("depositos_ahorro", "me"),
    ("depositos de ahorro", "total"): ("depositos_ahorro", "total"),
    ("depositos a plazo", "m.n"): ("depositos_plazo", "mn"),
    ("depositos a plazo", "m.e."): ("depositos_plazo", "me"),
    ("depositos a plazo", "total"): ("depositos_plazo", "total"),
    ("total depositos", ""): ("depositos_totales", "total"),
    ("creditos directos", "m.n"): ("creditos_directos", "mn"),
    ("creditos directos", "m.e."): ("creditos_directos", "me"),
    ("total creditos", ""): ("creditos_directos", "total"),
}
# Columnas descriptivas: (rótulo superior, rótulo inferior) → nombre interno
DESCRIPTIVAS = {
    ("empresa", ""): "empresa",
    ("ubicacion", "departamento"): "departamento",
    ("ubicacion", "provincia"): "provincia",
    ("ubicacion", "distrito"): "distrito",
    ("codigo oficina", ""): "codigo",
}
NIVELES = ["empresa", "departamento", "provincia", "distrito"]
GEO = NIVELES[1:]
UNIDAD_RE = re.compile(r"^\(en miles de (nuevos )?soles\)$")
FIN_RE = re.compile(r"^(nota|fuente)\b")
TOTAL_GENERAL = "total general"
# Cabecera del Anexo 10 crudo que acompaña al cuadro en 2013-12 («Hoja1»).
CRUDO = {"concepto", "entidad", "fecha", "cod pais", "codigo oficina"}
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]
FECHA_RE = re.compile(r"^al \d{1,2} de ([a-z]+) de (\d{4})$")
# Meses en que «Código Oficina» es la suma de los códigos de un distrito (ver docstring).
CODIGO_SUMADO = {201403}
TOL = 0.01  # miles de soles, para comparar la suma de oficinas con el «Total general»
MESES_REFERENCIA = 12  # meses verificados que se miran para corregir ubicaciones heredadas


@dataclass
class Oficina:
    """Una fila de oficina tal como se lee, antes de resolver la ubicación heredada."""
    fila: int
    impreso: dict[str, str]          # nivel → texto impreso en la fila ('' si viene vacío)
    k: int                           # primer nivel impreso (len(NIVELES) = ninguno)
    codigo: str
    cifras: dict[tuple[str, str], float | None]
    ubicacion: dict[str, str] = field(default_factory=dict)  # nivel → empresa / token final


@dataclass
class Libro:
    hoja: str
    oficinas: list[Oficina]
    estado: str                      # verificado | sin_total | incompleto
    faltante: dict[tuple[str, str], float]  # «Total general» − suma de oficinas (incompleto)


def token(texto: str) -> str:
    """Nombre geográfico normalizado: `comun.norm` y todo lo que no sea [a-z0-9] → «_»."""
    return re.sub(r"[^a-z0-9]+", "_", comun.norm(texto)).strip("_")


def _token_nivel(nivel: str, texto: str, hoja: str, fila: int) -> str:
    """Token de un nivel: la empresa tal cual; el departamento, contra la lista canónica."""
    if nivel == "empresa":
        return texto
    if nivel == "departamento":
        dep = comun.norm(texto)
        if dep not in DEPARTAMENTOS or DEPARTAMENTOS[dep] == "exterior":
            raise ValueError(f"hoja {hoja!r} fila {fila}: departamento desconocido {texto!r}")
        return DEPARTAMENTOS[dep]
    return token(texto)


# --------------------------------------------------------------------------- lectura del libro

def leer(ruta: Path, subsistema: str, periodo: int) -> list[dict]:
    """Registros de todas las oficinas del libro (ver el docstring del módulo)."""
    libro = _libro_ubicado(ruta, subsistema, periodo)
    salida = []
    for o in libro.oficinas:
        geo = "|".join([o.ubicacion[n] for n in GEO] + [o.codigo])
        for (variable, moneda), valor in o.cifras.items():
            salida.append(comun.registro(libro.hoja, o.ubicacion["empresa"], variable,
                                         f"{moneda}|{geo}", valor, "miles_soles"))
    return salida


def diagnostico(ruta: Path, subsistema: str, periodo: int) -> dict:
    """Estado del libro, faltante frente al «Total general» y ubicaciones corregidas."""
    libro = _leer_libro(ruta, subsistema, periodo)
    crudo = _ubicar(libro, None)
    final = _libro_ubicado(ruta, subsistema, periodo)
    corregidas = [(o.ubicacion["empresa"], o.codigo, "|".join(c[n] for n in GEO),
                   "|".join(o.ubicacion[n] for n in GEO))
                  for c, o in zip(crudo, final.oficinas) if c != o.ubicacion]
    ref = _referencia(ruta, subsistema, periodo)[0] if libro.estado == "incompleto" else None
    return {"estado": libro.estado, "oficinas": len(libro.oficinas), "faltante": libro.faltante,
            "periodo_referencia": ref, "corregidas": corregidas}


@lru_cache(maxsize=64)
def _leer_libro(ruta: Path, subsistema: str, periodo: int) -> Libro:
    """Ubica la única hoja del cuadro (las demás: vacías o el Anexo 10 crudo) y la lee."""
    libros = []
    for hoja, df in comun.abrir(ruta).items():
        h = _cabecera(df)
        if h is None:
            if _es_crudo(df):
                continue
            if any(comun.a_numero(v) is not None for v in df.to_numpy().ravel()):
                raise ValueError(f"hoja {hoja!r}: tiene cifras pero no la cabecera «Empresa … Total Créditos»")
            continue
        libros.append(_leer_hoja(str(hoja).strip(), df, h, subsistema, periodo))
    if len(libros) != 1:
        raise ValueError(f"se esperaba una hoja del cuadro y hay {len(libros)}: {[l.hoja for l in libros]}")
    return libros[0]


def _cabecera(df: pd.DataFrame) -> int | None:
    """Fila con «Empresa», «Codigo Oficina» y «Total Creditos»."""
    for i in range(min(len(df), 30)):
        txt = {comun.norm(v) for v in df.iloc[i]}
        if {"empresa", "codigo oficina", "total creditos"} <= txt:
            return i
    return None


def _es_crudo(df: pd.DataFrame) -> bool:
    """Hoja con el Anexo 10 crudo (cabecera «Concepto | Entidad | Fecha | Cod Pais …»)."""
    return len(df) > 0 and CRUDO <= {comun.norm(v) for v in df.iloc[0]}


def _titulo(df: pd.DataFrame, h: int, hoja: str, periodo: int) -> None:
    """Verifica el título (por oficina), la unidad (miles de soles) y la fecha si la hay."""
    textos, fechas = [], []
    for i in range(h):
        for v in df.iloc[i]:
            if isinstance(v, (dt.datetime, pd.Timestamp)):
                fechas.append(v.year * 100 + v.month)
            elif comun.norm(v):
                t = comun.norm(v)
                textos.append(t)
                m = FECHA_RE.match(t)
                if m:
                    mes = "septiembre" if m.group(1) == "setiembre" else m.group(1)
                    if mes not in MESES:
                        raise ValueError(f"hoja {hoja!r}: mes desconocido en el título {t!r}")
                    fechas.append(int(m.group(2)) * 100 + MESES.index(mes) + 1)
    if not any(t.startswith("depositos y creditos por oficina") for t in textos):
        raise ValueError(f"hoja {hoja!r}: título inesperado {textos[:2]}")
    if sum(bool(UNIDAD_RE.match(t)) for t in textos) != 1:
        raise ValueError(f"hoja {hoja!r}: no se encontró la unidad «(En miles de soles)»: {textos}")
    if any(f != periodo for f in fechas):
        raise ValueError(f"hoja {hoja!r}: la fecha del título {fechas} no es el periodo {periodo}")


def _columnas(df: pd.DataFrame, h: int, hoja: str) -> tuple[dict[str, int], dict[int, tuple[str, str]]]:
    """Ubica por rótulo las columnas descriptivas y las de cifras (rótulo superior arrastrado)."""
    desc: dict[str, int] = {}
    datos: dict[int, tuple[str, str]] = {}
    arriba = ""
    for j in range(df.shape[1]):
        t1, t2 = comun.norm(df.iat[h, j]), comun.norm(df.iat[h + 1, j])
        if t1:
            arriba = t1
        if not t1 and not t2:
            continue
        clave = (arriba, t2)
        if clave in DESCRIPTIVAS:
            desc[DESCRIPTIVAS[clave]] = j
        elif clave in COLUMNAS:
            datos[j] = COLUMNAS[clave]
        else:
            raise ValueError(f"hoja {hoja!r}: columna desconocida {comun.limpiar(df.iat[h, j])!r}"
                             f" / {comun.limpiar(df.iat[h + 1, j])!r} (col {j})")
    faltan = set(DESCRIPTIVAS.values()) - set(desc)
    if faltan:
        raise ValueError(f"hoja {hoja!r}: faltan columnas descriptivas {sorted(faltan)}")
    if sorted(datos.values()) != sorted(COLUMNAS.values()):
        raise ValueError(f"hoja {hoja!r}: columnas de cifras incompletas o repetidas: "
                         f"{sorted(set(COLUMNAS.values()) - set(datos.values()))}")
    if max(desc.values()) >= min(datos):
        raise ValueError(f"hoja {hoja!r}: columnas descriptivas a la derecha de las cifras")
    return desc, datos


def _codigo(valor, hoja: str, i: int) -> str:
    """Código de oficina como entero en texto («618»)."""
    x = comun.a_numero(valor)
    if x is None or x != int(x) or x < 0:
        raise ValueError(f"hoja {hoja!r} fila {i}: código de oficina inválido {valor!r}")
    return str(int(x))


def _leer_hoja(hoja: str, df: pd.DataFrame, h: int, subsistema: str, periodo: int) -> Libro:
    """Filas de oficina con lo impreso en cada una, y el estado frente al «Total general»."""
    _titulo(df, h, hoja, periodo)
    desc, datos = _columnas(df, h, hoja)
    oficinas: list[Oficina] = []
    total_general: dict[tuple[str, str], float | None] | None = None
    for i in range(h + 2, len(df)):
        primera = comun.norm(df.iat[i, desc["empresa"]])
        if FIN_RE.match(primera):
            break
        if primera == TOTAL_GENERAL:
            total_general = {datos[j]: comun.a_numero(df.iat[i, j]) for j in datos}
            break  # 2026-07/08: lo que sigue al primer total es un bloque residual
        impreso = {n: comun.limpiar(df.iat[i, desc[n]]) for n in NIVELES}
        cifras = {datos[j]: comun.a_numero(df.iat[i, j]) for j in datos}
        hay_cifras = any(v is not None for v in cifras.values())
        codigo_vacio = comun.a_numero(df.iat[i, desc["codigo"]]) is None
        if not any(impreso.values()) and not hay_cifras and codigo_vacio:
            continue  # fila en blanco
        if not hay_cifras:
            raise ValueError(f"hoja {hoja!r} fila {i}: oficina sin cifras {list(impreso.values())}")
        llenos = [n for n in NIVELES if impreso[n]]
        k = NIVELES.index(llenos[0]) if llenos else len(NIVELES)
        # Caso Huarmey (2023-11 → 2025-06): provincia impresa, sin distrito ni código.
        sin_distrito = bool(llenos) and llenos == NIVELES[k:-1] and codigo_vacio
        if llenos != NIVELES[k:] and not sin_distrito:
            raise ValueError(f"hoja {hoja!r} fila {i}: ubicación con huecos {impreso} (no se puede heredar)")
        if k > 0 and not oficinas:
            raise ValueError(f"hoja {hoja!r} fila {i}: cifras antes de la primera empresa")
        if k == 0 and not comun.es_entidad(impreso["empresa"], subsistema):
            raise ValueError(f"hoja {hoja!r} fila {i}: empresa desconocida {impreso['empresa']!r}")
        if sin_distrito or periodo in CODIGO_SUMADO:
            codigo = ""
        else:
            codigo = _codigo(df.iat[i, desc["codigo"]], hoja, i)
        oficinas.append(Oficina(i, impreso, k, codigo, cifras))
    if not oficinas:
        raise ValueError(f"hoja {hoja!r}: no se leyó ninguna oficina")
    estado, faltante = "sin_total", {}
    if total_general is not None:
        estado = "verificado"
        for clave, t in total_general.items():
            suma = sum(o.cifras[clave] or 0.0 for o in oficinas)
            if t is None:
                raise ValueError(f"hoja {hoja!r}: «Total general» sin cifra en {clave}")
            tol = TOL + 1e-9 * abs(t)
            if suma > t + tol:
                raise ValueError(f"hoja {hoja!r}: {'|'.join(clave)}: suma de oficinas {suma:,.3f} "
                                 f"mayor que el «Total general» {t:,.3f}")
            if suma < t - tol:
                estado = "incompleto"
                faltante[clave] = t - suma
    libro = Libro(hoja, oficinas, estado, faltante)
    _ubicar(libro, None)  # valida departamentos y herencia aunque luego se corrija
    return libro


# ----------------------------------------------------------------- ubicación (relleno hacia abajo)

def _ubicar(libro: Libro, ref: dict | None) -> list[dict[str, str]]:
    """Resuelve la ubicación de cada oficina heredando hacia abajo; devuelve copia de cada una.

    Con `ref` ({(empresa, codigo): {nivel: token}} del último mes verificado), los niveles
    HEREDADOS de una oficina se reemplazan por los de `ref` si los niveles impresos en su fila
    coinciden con los de `ref`. Lo corregido pasa a las filas siguientes que heredan de ella.
    """
    actual = {n: "" for n in NIVELES}
    vistos: set = set()
    salida = []
    for o in libro.oficinas:
        u = dict(actual)
        for n in NIVELES[o.k:]:
            u[n] = _token_nivel(n, o.impreso[n], libro.hoja, o.fila) if o.impreso[n] else ""
        if ref is not None and 0 < o.k and o.codigo:
            r = ref.get((u["empresa"], o.codigo))
            if r is not None and all(u[n] == r[n] for n in NIVELES[o.k:]):
                for n in NIVELES[1:o.k]:
                    u[n] = r[n]
        if not u["departamento"] or not u["provincia"]:
            raise ValueError(f"hoja {libro.hoja!r} fila {o.fila}: ubicación incompleta {u}")
        if not u["distrito"] and o.codigo:
            raise ValueError(f"hoja {libro.hoja!r} fila {o.fila}: oficina {o.codigo} sin distrito")
        clave = (u["empresa"], o.codigo) if o.codigo else (u["empresa"], *[u[n] for n in GEO])
        if clave in vistos:
            raise ValueError(f"hoja {libro.hoja!r} fila {o.fila}: oficina repetida {clave}")
        vistos.add(clave)
        o.ubicacion = u
        salida.append(dict(u))
        actual = u
    return salida


@lru_cache(maxsize=16)
def _referencia(ruta: Path, subsistema: str, periodo: int) -> tuple[int, dict]:
    """Ubicaciones de los últimos `MESES_REFERENCIA` meses VERIFICADOS anteriores a `periodo`.

    Misma carpeta y código. Para cada (empresa, código) vale la ubicación del mes más reciente
    en que aparece (algunas oficinas faltan algún mes, p. ej. Agrobanco 53 y BN 730 en 2026-03).
    Devuelve (último mes verificado, {(empresa, código): {nivel: token}}).
    """
    codigo = comun.codigo_de(ruta)
    previos = sorted(((comun.periodo_de(p), p) for p in ruta.parent.glob(f"{codigo}-*.XLS")
                      if comun.periodo_de(p) < periodo), reverse=True)
    ref: dict = {}
    usados: list[int] = []
    for per, p in previos:
        if per in CODIGO_SUMADO:
            continue
        try:
            libro = _leer_libro(p, subsistema, per)
        except ValueError:
            continue
        if libro.estado != "verificado":
            continue
        for u, o in zip(_ubicar(libro, None), libro.oficinas):
            if o.codigo:
                ref.setdefault((u["empresa"], o.codigo), u)
        usados.append(per)
        if len(usados) == MESES_REFERENCIA:
            break
    if not usados:
        raise ValueError("libro incompleto (filas borradas) y sin mes verificado anterior para corregir ubicaciones")
    return usados[0], ref


def _libro_ubicado(ruta: Path, subsistema: str, periodo: int) -> Libro:
    """Libro con la ubicación final; si está incompleto, corrige lo heredado con la referencia."""
    libro = _leer_libro(ruta, subsistema, periodo)
    ref = _referencia(ruta, subsistema, periodo)[1] if libro.estado == "incompleto" else None
    _ubicar(libro, ref)
    return libro


# ---------------------------------------------------------------------------------- validación

def validar_totales(df: pd.DataFrame, tolerancia: float = 0.005) -> pd.DataFrame:
    """Controles internos por oficina (solo violaciones; columna `regla`).

    - `vista+ahorro+plazo!=total`: depósitos a la vista + ahorro + plazo (moneda total) frente a
      `depositos_totales`.
    - `mn+me!=total`: en cada variable con apertura por moneda, MN + ME frente a total.
    Diferencia relativa como en `comun.validar_totales` (|dif| / max(|total|, 1)).
    """
    claves = ["periodo", "subsistema", "codigo", "hoja", "entidad_original", "variable", "apertura", "unidad"]
    cols = claves + ["suma_entidades", "total", "dif_rel", "regla"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    d = df.copy()
    partes = d["apertura"].str.split("|", n=1, expand=True)
    d["moneda"], d["oficina"] = partes[0], partes[1]
    base = ["periodo", "subsistema", "codigo", "hoja", "entidad_original", "oficina"]
    t = d[d["moneda"] == "total"]
    comp = t[t["variable"].isin(["depositos_vista", "depositos_ahorro", "depositos_plazo"])]
    s = comp.groupby(base)["valor"].sum().rename("suma_entidades")
    tot = t[t["variable"] == "depositos_totales"].set_index(base)["valor"].rename("total")
    a = pd.concat([s, tot], axis=1, join="inner").reset_index()
    a = a.assign(variable="depositos_totales", regla="vista+ahorro+plazo!=total")
    m = d[d["moneda"].isin(["mn", "me"])]
    s = m.groupby(base + ["variable"])["valor"].sum().rename("suma_entidades")
    tot = t.set_index(base + ["variable"])["valor"].rename("total")
    b = pd.concat([s, tot], axis=1, join="inner").reset_index().assign(regla="mn+me!=total")
    x = pd.concat([a, b], ignore_index=True)
    x["apertura"] = "total|" + x["oficina"]
    x["unidad"] = "miles_soles"
    x["dif_rel"] = (x["suma_entidades"] - x["total"]).abs() / x["total"].abs().clip(lower=1)
    x = x[x["dif_rel"] > tolerancia]
    return x[cols].sort_values(["regla", "dif_rel"], ascending=[True, False])
