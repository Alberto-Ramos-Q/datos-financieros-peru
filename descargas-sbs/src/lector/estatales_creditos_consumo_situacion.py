"""Lector de E-5203 «Créditos de consumo según situación» (tema `estatales-creditos-consumo-situacion`, p=12, entidades estatales).

Cuadro «Situación de Créditos de Consumo del Banco de la Nación»: solo el BN, sin columna de
entidad (la entidad sale del título). Agregado el 2026-11-03; revisados los 193 archivos
2010-07 → 2026-08 (falta 2011-04 en la SBS).

Qué publica
-----------
Un bloque vertical en una sola hoja, con los rótulos en una columna (`jl`) y las cifras a su
derecha:
- fila del título «Situación de Créditos de Consumo del Banco de la Nación»;
- fila de la unidad «(En miles de nuevos soles)» (→ 2015-10) / «(En miles de soles)» (2015-11 →);
- fila de cabecera «Vigentes | Refinanciados | Vencidos | En Cobranza Judicial | Total»;
- fila «Saldo de Créditos de Consumo» con las cinco cifras (miles de S/; fuente: Balance de
  Comprobación);
- fila «Número de Deudores de Créditos de Consumo» con una cifra bajo «Vigentes»;
- fila «Número de Tarjetas de Crédito de Créditos de Consumo» (solo 2017-01 →; Reporte 7).
- filas «Fuente: …» y, en 2025-07 → 2026-01, una nota sobre el conteo de deudores.

Variables y aperturas (mismos nombres que los lectores del sistema privado)
-------------------------------------------------------------------------
- `creditos_directos` (miles_soles), apertura `tipo|situacion` como en `creditos_tipo_situacion`,
  con tipo siempre `consumo`:
    «Vigentes» → `consumo|vigentes`; «Refinanciados» → `consumo|refinanciados`;
    «Vencidos» → `consumo|vencidos`; «En Cobranza Judicial» → `consumo|cobranza_judicial`;
    «Total» → `consumo|total`.
  Ojo: aquí «Refinanciados» no dice «y reestructurados» (por eso no se usa el token
  `refinanciados_reestructurados`), y los atrasados vienen abiertos en vencidos + cobranza
  judicial (atrasados = vencidos + cobranza_judicial; no se publica ese agregado).
- `numero_deudores` (numero), apertura `consumo` (como en `deudores_tipo_credito`).
- `numero_tarjetas_credito` (numero), apertura `consumo` (como en `tarjetas_credito_tipo`).
`entidad_original` es siempre «Banco de la Nación» (el maestro lo resuelve en el subsistema
`entidades-estatales`).

Formatos por época
------------------
- 2010-07 → 2011-07 y 2011-09: hoja «Hoja1» (más «Hoja2»/«Hoja3» vacías), rótulos en la col. 1
  (2011-07: en la col. 0).
- 2011-08 y 2011-10 → 2015-09: hoja «Nación»; rótulos en la col. 1 o en la col. 0 según el mes
  (16 meses entre 2012-01 y 2015-09 en la col. 0). 2013-03 trae además «Al 31 de Marzo de 2013».
- 2015-10: hoja «6N»; 2015-11 →: hoja «10». Rótulos en la col. 1 salvo 2015-11 y 2019-10 (col. 0).
- 2017-01 →: se agrega la fila del número de tarjetas de crédito.
- 2026-03 →: desaparece la fila «Fuente: Balance de Comprobación» y todo sube una fila; en
  2026-08 la cifra de deudores está en la fila de su «Fuente» y no en la del rótulo.
La posición de cada cosa se ubica por su etiqueta, nunca por número de fila o columna.

Trampas
-------
- Título con errata «Banco de la Nacón» hasta 2016-11; se acepta y se registra como
  «Banco de la Nación».
- Desde 2013-11, cuando los rótulos van en la col. 1, la col. 0 de la fila del saldo trae un
  código de trabajo de la SBS (61): se ignora (solo en esa fila y a la izquierda del rótulo).
  En 2023-09 el mismo código aparece copiado a la derecha del «Total» (col. 8): se ignora solo
  si es igual al de la izquierda.
- 2023-04 → 2023-08 y 2024-05/06 traen a la derecha (col. 8-14) una SEGUNDA copia del cuadro,
  con su propio título. Es una copia de trabajo con las cifras del mes ANTERIOR (p. ej. el bloque
  derecho de 2023-05 = bloque izquierdo de 2023-04). Se lee solo el primer bloque (el izquierdo).
- CAMBIO DE DEFINICIÓN de `numero_deudores`: hasta 2026-01 la fuente es el Anexo 5 (Informe de
  Clasificación de Deudores y Provisiones) y, según la nota de 2025-07 → 2026-01, se SUMAN los
  deudores de consumo revolvente y no revolvente (quien tiene ambos cuenta dos veces). Desde
  2026-02 la fuente es el Anexo 6 (Reporte Crediticio de Deudores) y la serie cae de ~800 mil a
  ~650 mil. No es comparable antes y después; no se corrige. Antes de 2025-07 la nota no
  aparece, pero la fuente es la misma (Anexo 5).
- DEUDORES = 0 en 2018-08, 2023-06, 2023-08 y 2024-08 (celda numérica 0, también en la copia
  de trabajo de 2023-06/08), con un saldo de consumo de S/ 4-9 mil millones y 700-800 mil deudores
  en los meses vecinos. Es un «sin dato» de la SBS: el lector no guarda esa fila (regla: deudores
  = 0 con saldo total > 0). Esos meses tienen 6 filas en vez de 7.
- Otros saltos de nivel que vienen así en el archivo (no se corrigen): deudores 2013-05 = 498 675
  (vecinos ~530 mil, punto atípico); 2023-01: deudores −9,7 % (703 545 → 635 008) y tarjetas
  −26,8 % (260 791 → 190 893); 2026-02: deudores −20,9 % por el cambio a Anexo 6 (arriba).
- Vigentes + Refinanciados + Vencidos + Judicial = Total en los 193 meses (diferencia < 1e-9;
  regla propia en `validar_totales`). El saldo cuadra con el consumo del BN en E-5205
  (`estatales-creditos-tipo-situacion`, revolvente + no revolvente) en los 116 meses comunes
  2017-01 → 2026-08 (diferencia < 0,004 miles de S/), incluidos los meses con copia de trabajo.
- Cualquier rótulo, fuente, cabecera o cifra que no se reconozca levanta ValueError; también si
  no hay cuadro, si hay más de una hoja con cuadro o si la fecha «Al …» no es la del archivo.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from lector import comun

ENTIDAD = "Banco de la Nación"
UNIDAD_SALDO = "miles_soles"

# Título del cuadro (normalizado). Acepta la errata «Nacón» de 2010-07 → 2016-11.
TITULO_RE = re.compile(r"^situacion de creditos de consumo del banco de la naci?on$")
UNIDAD_RE = re.compile(r"^\(en miles de (nuevos )?soles\)$")
FECHA_RE = re.compile(r"^al (\d{1,2}) de ([a-z]+) de (\d{4})$")
MESES = {m: k for k, m in enumerate(["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
                                     "agosto", "setiembre", "octubre", "noviembre", "diciembre"], 1)}
MESES["septiembre"] = 9

# Rótulos de fila con cifras → (variable, unidad). El saldo lleva la apertura por columna.
FILAS = [
    (re.compile(r"^saldo de creditos de consumo$"), "creditos_directos", UNIDAD_SALDO),
    (re.compile(r"^numero de deudores de creditos de consumo$"), "numero_deudores", "numero"),
    (re.compile(r"^numero de tarjetas de credito de creditos de consumo$"), "numero_tarjetas_credito", "numero"),
]
# Cabecera de situaciones → token de situación (apertura `consumo|<token>`).
SITUACIONES = [
    (re.compile(r"^vigentes?$"), "vigentes"),
    (re.compile(r"^refinanciados?$"), "refinanciados"),
    (re.compile(r"^vencidos?$"), "vencidos"),
    (re.compile(r"^en cobranza judicial$"), "cobranza_judicial"),
    (re.compile(r"^total$"), "total"),
]
# Fuentes conocidas (filas «Fuente: …») y notas al pie sin cifras.
FUENTES = [
    re.compile(r"^fuente: balance de comprobacion\.?$"),
    re.compile(r"^fuente: anexo (n )?5( informe de clasificacion de deudores y provisiones)?\.?$"),
    re.compile(r"^fuente: anexo (n )?6( - reporte crediticio de deudores)?\.?$"),
    re.compile(r"^fuente: reporte 7( tarjetas de credito)?\.?$"),
]
NOTAS = [
    re.compile(r"^se considera la suma de deudores de consumo revolvente y consumo no revolvente\b"),
]


def leer(ruta: Path, subsistema: str, periodo: int) -> list[dict]:
    """Registros del cuadro E-5203 (ver docstring del módulo). Exactamente una hoja con cuadro."""
    hojas = []
    for hoja, df in comun.abrir(ruta).items():
        regs = _leer_hoja(str(hoja).strip(), df, periodo)
        if regs is not None:
            hojas.append((hoja, regs))
    if not hojas:
        raise ValueError("ninguna hoja tiene el cuadro «Situación de Créditos de Consumo del Banco de la Nación»")
    if len(hojas) > 1:
        raise ValueError(f"varias hojas con el cuadro: {[h for h, _ in hojas]!r}")
    return hojas[0][1]


def _celdas_num(df: pd.DataFrame) -> set[tuple[int, int]]:
    nr, nc = df.shape
    return {(i, j) for i in range(nr) for j in range(nc) if comun.a_numero(df.iat[i, j]) is not None}


def _leer_hoja(hoja: str, df: pd.DataFrame, periodo: int) -> list[dict] | None:
    """Registros de una hoja; None si la hoja no tiene nada (p. ej. «Hoja2» vacía)."""
    nr, nc = df.shape
    titulos = [(i, j) for i in range(nr) for j in range(nc) if TITULO_RE.match(comun.norm(df.iat[i, j]))]
    numeros = _celdas_num(df)
    if not titulos:
        textos = [comun.limpiar(df.iat[i, j]) for i in range(nr) for j in range(nc) if comun.norm(df.iat[i, j])]
        if numeros or textos:
            raise ValueError(f"hoja {hoja!r}: tiene contenido pero no el título del cuadro "
                             f"(primeros textos: {textos[:3]!r})")
        return None
    # Primer bloque = el de más a la izquierda. Otro título más a la derecha marca una copia de
    # trabajo (2023-04 → 2023-08, 2024-05/06: cifras del mes anterior) que se descarta entera.
    it, jl = min(titulos, key=lambda t: (t[1], t[0]))
    otros = sorted({j for _, j in titulos if j > jl})
    if any(j == jl for i, j in titulos if i != it):
        raise ValueError(f"hoja {hoja!r}: el título aparece dos veces en la misma columna {jl}")
    j_fin = (otros[0] - 1) if otros else nc  # columnas del bloque: jl .. j_fin-1 (deja libre la col. del código)

    # Cabecera de situaciones: la fila con «Vigentes» … «Total» a la derecha de `jl`.
    # Es la primera fila con algún rótulo de situación; en ella todo rótulo debe ser conocido.
    f_cab, columnas = None, {}
    for i in range(it + 1, nr):
        textos = {j: comun.norm(df.iat[i, j]) for j in range(jl + 1, j_fin)
                  if comun.norm(df.iat[i, j]) and comun.a_numero(df.iat[i, j]) is None}
        toks = {j: next((tok for patron, tok in SITUACIONES if patron.match(n)), None) for j, n in textos.items()}
        if not any(toks.values()):
            continue
        desconocidos = [comun.limpiar(df.iat[i, j]) for j, t in toks.items() if t is None]
        if desconocidos:
            raise ValueError(f"hoja {hoja!r} fila {i}: cabecera de situación desconocida {desconocidos!r}")
        f_cab, columnas = i, toks
        break
    esperados = {tok for _, tok in SITUACIONES}
    if f_cab is None or sorted(columnas.values()) != sorted(esperados):
        raise ValueError(f"hoja {hoja!r}: cabecera de situaciones incompleta o repetida "
                         f"{sorted(columnas.values())!r}")
    j_total = max(columnas)

    usadas: set[tuple[int, int]] = set()
    out: list[dict] = []
    vistos: set[str] = set()
    unidad_ok = False
    fila_saldo = None
    i = it + 1
    while i < nr:
        n = comun.norm(df.iat[i, jl])
        if not n:
            i += 1
            continue
        fila = next(((v, u) for patron, v, u in FILAS if patron.match(n)), None)
        if fila is None:
            _rotulo_sin_cifras(hoja, i, n, df.iat[i, jl], periodo)
            unidad_ok = unidad_ok or bool(UNIDAD_RE.match(n))
            i += 1
            continue
        variable, unidad = fila
        if variable in vistos:
            raise ValueError(f"hoja {hoja!r} fila {i}: rótulo repetido {comun.limpiar(df.iat[i, jl])!r}")
        vistos.add(variable)
        if variable == "creditos_directos":
            fila_saldo = i
            for j, tok in columnas.items():
                r = comun.registro(hoja, ENTIDAD, variable, f"consumo|{tok}", df.iat[i, j], unidad)
                if r:
                    out.append(r)
                    usadas.add((i, j))
            if not any(r["variable"] == variable and r["apertura"] == "consumo|total" for r in out):
                raise ValueError(f"hoja {hoja!r} fila {i}: saldo de consumo sin cifra en «Total»")
            i += 1
            continue
        # Deudores / tarjetas: una sola cifra, en la fila del rótulo o (2026-08) en la de su «Fuente».
        # Filas candidatas: la del rótulo, las siguientes sin rótulo y la primera fila con rótulo
        # que siga, solo si es su «Fuente: …» (esa fila se valida al llegar a ella en el bucle).
        k = i + 1
        while k < nr and not comun.norm(df.iat[k, jl]):
            k += 1
        filas_val = list(range(i, k))
        if k < nr and comun.norm(df.iat[k, jl]).startswith("fuente"):
            filas_val.append(k)
        cand = [(a, j) for a in filas_val for j in range(jl + 1, j_fin) if (a, j) in numeros]
        if len(cand) != 1:
            raise ValueError(f"hoja {hoja!r} fila {i}: se esperaba una cifra para "
                             f"{comun.limpiar(df.iat[i, jl])!r} y hay {len(cand)}")
        a, j = cand[0]
        usadas.add((a, j))
        saldo = next((r["valor"] for r in out if r["apertura"] == "consumo|total"), None)
        if saldo is None:
            raise ValueError(f"hoja {hoja!r} fila {i}: {comun.limpiar(df.iat[i, jl])!r} aparece antes del saldo")
        if variable == "numero_deudores" and comun.a_numero(df.iat[a, j]) == 0 and saldo > 0:
            # 2018-08, 2023-06, 2023-08, 2024-08: la SBS escribe 0 deudores con S/ 4-9 mil millones
            # de saldo (meses vecinos: 700-800 mil). Es un «sin dato»: no se guarda.
            i += 1
            continue
        out.append(comun.registro(hoja, ENTIDAD, variable, "consumo", df.iat[a, j], unidad))
        i += 1

    if "creditos_directos" not in vistos:
        raise ValueError(f"hoja {hoja!r}: no se encontró la fila «Saldo de Créditos de Consumo»")
    if "numero_deudores" not in vistos:
        raise ValueError(f"hoja {hoja!r}: no se encontró la fila «Número de Deudores de Créditos de Consumo»")
    if periodo >= 201701 and "numero_tarjetas_credito" not in vistos:
        raise ValueError(f"hoja {hoja!r}: falta la fila de tarjetas de crédito (se publica desde 2017-01)")
    if not unidad_ok:
        raise ValueError(f"hoja {hoja!r}: no se encontró la unidad «(En miles de soles)»")

    # Toda cifra de la hoja debe haberse usado, salvo el código de trabajo de la SBS a la
    # izquierda del saldo (y su copia a la derecha del «Total», 2023-09) y la copia de trabajo
    # a la derecha (otro título).
    codigos = {comun.a_numero(df.iat[fila_saldo, j]) for j in range(jl) if (fila_saldo, j) in numeros}
    for (a, j) in sorted(numeros - usadas):
        if otros and j >= otros[0] - 1:
            continue  # copia de trabajo del mes anterior (con su propio código en la col. previa)
        if a == fila_saldo and (j < jl or (j > j_total and comun.a_numero(df.iat[a, j]) in codigos)):
            continue  # código de trabajo de la SBS (61)
        raise ValueError(f"hoja {hoja!r} fila {a} col {j}: cifra no reconocida {df.iat[a, j]!r}")
    return out


def _rotulo_sin_cifras(hoja: str, i: int, n: str, original, periodo: int) -> None:
    """Valida un rótulo que no lleva cifras (título, unidad, fecha, fuente, nota); si no, ValueError."""
    if TITULO_RE.match(n) or UNIDAD_RE.match(n):
        return
    if any(p.match(n) for p in FUENTES) or any(p.match(n) for p in NOTAS):
        return
    m = FECHA_RE.match(n)
    if m:
        if int(m.group(3)) * 100 + MESES.get(m.group(2), 0) != periodo:
            raise ValueError(f"hoja {hoja!r} fila {i}: fecha {comun.limpiar(original)!r} distinta del periodo {periodo}")
        return
    if n.startswith("fuente"):
        raise ValueError(f"hoja {hoja!r} fila {i}: fuente desconocida {comun.limpiar(original)!r}")
    raise ValueError(f"hoja {hoja!r} fila {i}: rótulo desconocido {comun.limpiar(original)!r}")


def validar_totales(df: pd.DataFrame, tolerancia: float = 0.005) -> pd.DataFrame:
    """Regla propia (no hay filas de total de subsistema: solo el BN).

    `suma_situaciones!=total`: por periodo × hoja × entidad, vigentes + refinanciados + vencidos
    + cobranza judicial del saldo de consumo debe igualar el `consumo|total` publicado (diferencia
    absoluta > 1 miles de S/, o relativa > `tolerancia`: es una identidad contable y en la historia
    la diferencia es < 1e-9). Se listan solo las violaciones, con las
    columnas de `comun.validar_totales` más `entidad_original` y `regla`.
    """
    claves = ["periodo", "subsistema", "codigo", "hoja", "variable", "unidad", "entidad_original"]
    cols = ["periodo", "subsistema", "codigo", "hoja", "variable", "apertura", "unidad",
            "entidad_original", "suma_entidades", "total", "dif_rel", "regla"]
    d = df[df["variable"] == "creditos_directos"]
    if d.empty:
        return pd.DataFrame(columns=cols)
    partes = d[d["apertura"] != "consumo|total"].groupby(claves)["valor"].sum().rename("suma_entidades")
    tot = d[d["apertura"] == "consumo|total"].set_index(claves)["valor"].rename("total")
    x = pd.concat([partes, tot], axis=1, join="inner").reset_index()
    x["apertura"] = "consumo|total"
    x["regla"] = "suma_situaciones!=total"
    dif = (x["suma_entidades"] - x["total"]).abs()
    x["dif_rel"] = dif / x["total"].abs().clip(lower=1)
    return x[(dif > 1) | (x["dif_rel"] > tolerancia)][cols].sort_values("dif_rel", ascending=False)
