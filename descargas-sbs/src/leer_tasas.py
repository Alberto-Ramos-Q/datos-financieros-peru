"""Lee las tasas activas por tipo de crédito y entidad (SBS, MN) y arma una tabla larga.

Entrada: `data/raw/tasas-activas/<subsistema>/<X>_TIActivaTipoCreditoEmpresaMN-AAAAMM.xlsx`
(X = B, F, C, R, E; ver `config/tasas.csv` y `src/descargar_tasas.py`).
Salida:
    data/processed/tasas_activas.parquet
    data/processed/_control_tasas/archivos.csv          un registro por archivo (filas o error)
    data/processed/_control_tasas/sin_resolver.csv      nombres que el maestro no reconoce
    data/processed/_control_tasas/vigencia.csv          entidad en un subsistema distinto al de su vigencia
    data/processed/_control_tasas/notas.csv             notas al pie de cada archivo
    data/processed/_control_tasas/etiquetas.csv         etiqueta × periodos en que aparece (consistencia)
    + los archivos de la validación (`validar`, ver abajo y docs/lector_tasas.md)

Estructura del archivo (una hoja «Reporte», idéntica en los 655 archivos de 2015-10 → 2026-09):
título con el subsistema, la moneda, el formulario («Realizadas en los últimos 30 Días Útiles …
al dd/mm/aaaa» en banca y financieras; «Realizadas Durante el Mes … a <Mes> del aaaa» en cajas y
EC); una fila de cabecera «Tasa Anual (%)» con los nombres cortos de las entidades («Crédito»,
«BIF», «CMAC Piura»…) y al final «Promedio» (promedio del subsistema); debajo, por filas, el tipo
de crédito y sus subproductos. «-» = sin operaciones; «s.i.» = la entidad no reportó.

Columnas de salida:
    periodo | fecha_corte | subsistema | formulario | entidad_original | id_entidad | es_promedio
    | tipo_credito | subproducto | etiqueta_original | tasa | sin_dato | moneda
- `formulario`: `diario_30d` (B, F: promedio de los últimos 30 días útiles al corte) o `mensual`
  (C, R, E: operaciones del mes). `fecha_corte`: la del título (en el mensual, el último día del mes).
- `tipo_credito`: corporativo, grandes, medianas, pequenas, micro, consumo, hipotecario.
- `subproducto`: canónico (`ETIQUETAS`); `total` en la fila del tipo de crédito.
- `etiqueta_original`, `entidad_original`: texto de la SBS sin espacios sobrantes; si la codificación
  vino rota («Pr�stamos», «Cr�dito») se repara con el diccionario de etiquetas o con el maestro.
- `tasa`: % anual (float); NaN si la celda dice «-» o «s.i.» (`sin_dato` guarda cuál de las dos).
- `id_entidad`: maestro de entidades (`entidades.py`) con el subsistema del archivo; vacío en la
  columna de promedio (`es_promedio`).

Reglas: los datos se ubican por etiqueta normalizada, nunca por posición fija; una etiqueta que no
está en el diccionario, un subproducto bajo un tipo que no le corresponde, una celda con texto
desconocido o un título cuyo mes no coincide con el del archivo hacen fallar el archivo (queda en
`archivos.csv` con el error y el script devuelve 1).

Uso:
    python -P src/leer_tasas.py                     # todo: lee, escribe el parquet y valida
    python -P src/leer_tasas.py --subsistema cajas-rurales --desde 202401
    python -P src/leer_tasas.py --solo-validar      # valida el parquet existente
"""
from __future__ import annotations

import argparse
import calendar
import csv
import datetime as dt
import itertools
import re
import sys
import time
from functools import lru_cache
from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))
from entidades import Maestro  # noqa: E402
from lector import comun  # noqa: E402

RAW_DIR = PROJECT_DIR / "data" / "raw" / "tasas-activas"
TASAS_CSV = PROJECT_DIR / "config" / "tasas.csv"
OUT_FILE = PROJECT_DIR / "data" / "processed" / "tasas_activas.parquet"
CONTROL_DIR = PROJECT_DIR / "data" / "processed" / "_control_tasas"
PANEL_FILE = PROJECT_DIR / "data" / "processed" / "panel_entidad_mes.parquet"

COLUMNAS = ["periodo", "fecha_corte", "subsistema", "formulario", "entidad_original", "id_entidad",
            "es_promedio", "tipo_credito", "subproducto", "etiqueta_original", "tasa", "sin_dato",
            "moneda"]
FORMULARIOS = {"diario": "diario_30d", "mensual": "mensual"}  # config/tasas.csv → salida
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "setiembre",
         "octubre", "noviembre", "diciembre"]
TASA_MAXIMA = 500.0   # % anual: por encima se señala en la validación
TOLERANCIA_PROMEDIO = 0.01  # puntos porcentuales (las tasas vienen con 2 decimales)


def clave(texto) -> str:
    """Clave de comparación de etiquetas, robusta a la codificación rota de la SBS.

    Se ELIMINA todo carácter no ASCII (no se transcribe): así «Préstamos», «Prestamos» no, pero
    «Pr�stamos» (tilde perdida en el origen) y «Préstamos» dan la misma clave «prstamos».
    Además minúsculas, espacios colapsados y sin «:» final.
    """
    if not isinstance(texto, str):
        return ""
    s = re.sub(r"[^\x00-\x7f]", "", texto).lower()
    return re.sub(r"\s+", " ", s).strip(" :")


# --------------------------------------------------------------------------------------------
# Diccionario de etiquetas → canónico. La etiqueta legible es la que imprime la SBS (con tildes);
# la búsqueda se hace por `clave()`. Si la SBS agrega o renombra una fila, se agrega aquí (y se
# documenta el periodo en docs/lector_tasas.md); mientras tanto el archivo falla.
# --------------------------------------------------------------------------------------------
TIPOS = {
    "Corporativos": "corporativo",
    "Grandes Empresas": "grandes",
    "Medianas Empresas": "medianas",
    "Pequeñas Empresas": "pequenas",
    "Microempresas": "micro",
    "Consumo": "consumo",
    "Hipotecarios": "hipotecario",
}
ETIQUETAS = {
    "Descuentos": "descuentos",
    "Préstamos hasta 30 días": "prestamos_hasta_30d",
    "Préstamos de 31 a 90 días": "prestamos_31_90d",
    "Préstamos de 91 a 180 días": "prestamos_91_180d",
    "Préstamos de 181 a 360 días": "prestamos_181_360d",
    "Préstamos a más de 360 días": "prestamos_mas_360d",
    "Tarjetas de Crédito": "tarjetas_credito",
    "Préstamos Revolventes": "prestamos_revolventes",
    "Préstamos a cuota fija hasta 30 días": "cuota_fija_hasta_30d",
    "Préstamos a cuota fija de 31 a 90 días": "cuota_fija_31_90d",
    "Préstamos a cuota fija de 91 a 180 días": "cuota_fija_91_180d",
    "Préstamos a cuota fija de 181 a 360 días": "cuota_fija_181_360d",
    "Préstamos a cuota fija a más de 360 días": "cuota_fija_mas_360d",
    "Préstamos no Revolventes para automóviles": "no_revolvente_autos",
    "Préstamos no Revolventes para libre disponibilidad hasta 360 días": "no_revolvente_libre_hasta_360d",
    "Préstamos no Revolventes para libre disponibilidad a más de 360 días": "no_revolvente_libre_mas_360d",
    "Créditos pignoraticios": "pignoraticios",
    "Préstamos hipotecarios para vivienda": "hipotecario_vivienda",
}
_EMPRESAS = ["descuentos", "prestamos_hasta_30d", "prestamos_31_90d", "prestamos_91_180d",
             "prestamos_181_360d", "prestamos_mas_360d"]
# Subproductos permitidos bajo cada tipo, en el orden en que los publica la SBS.
SUBPRODUCTOS = {
    "corporativo": _EMPRESAS,
    "grandes": _EMPRESAS,
    "medianas": _EMPRESAS,
    "pequenas": _EMPRESAS,
    "micro": ["tarjetas_credito", "descuentos", "prestamos_revolventes", "cuota_fija_hasta_30d",
              "cuota_fija_31_90d", "cuota_fija_91_180d", "cuota_fija_181_360d", "cuota_fija_mas_360d"],
    "consumo": ["tarjetas_credito", "prestamos_revolventes", "no_revolvente_autos",
                "no_revolvente_libre_hasta_360d", "no_revolvente_libre_mas_360d", "pignoraticios"],
    "hipotecario": ["hipotecario_vivienda"],
}
_TIPOS_K = {clave(k): (k, v) for k, v in TIPOS.items()}
_ETIQ_K = {clave(k): (k, v) for k, v in ETIQUETAS.items()}
assert len(_TIPOS_K) == len(TIPOS) and len(_ETIQ_K) == len(ETIQUETAS)
assert not set(_TIPOS_K) & set(_ETIQ_K)
assert all(s in ETIQUETAS.values() for v in SUBPRODUCTOS.values() for s in v)

# Primera palabra de las notas al pie (debajo del cuadro): no son etiquetas de datos.
NOTA_RE = re.compile(r"^\s*(nota|\*|\(\*\)|\d+\.|informaci|las tasas|actualizado|mediante|el registro|"
                     r"en modificaci|fuente)", re.IGNORECASE)

_maestro: Maestro | None = None


def maestro() -> Maestro:
    global _maestro
    if _maestro is None:
        _maestro = Maestro()
    return _maestro


@lru_cache(maxsize=None)
def resolver(nombre: str, subsistema: str) -> tuple[str, str | None, bool]:
    """(nombre reparado, id_entidad, es_promedio).

    Si el nombre trae el carácter de reemplazo «�» (tilde perdida) y no se reconoce tal cual, se
    prueba cada vocal tildada o «ñ» en su lugar; se acepta solo si una única entidad casa.
    """
    if clave(nombre) == "promedio":
        return nombre, None, True
    m = maestro()
    i = m.resolver(nombre, subsistema)
    if i or "�" not in nombre:
        return nombre, i, False
    huecos = nombre.count("�")
    hallados: dict[str, str] = {}
    for letras in itertools.product("áéíóúñ", repeat=min(huecos, 3)):
        candidato = nombre
        for c in letras:
            candidato = candidato.replace("�", c, 1)
        try:
            j = m.resolver(candidato, subsistema)
        except ValueError:
            j = None
        if j:
            hallados.setdefault(j, candidato)
    if len(hallados) == 1:
        j, candidato = hallados.popitem()
        return candidato, j, False
    return nombre, None, False


def leer_titulo(df: pd.DataFrame, fila_cab: int) -> tuple[str, dt.date, str]:
    """(formulario, fecha_corte, moneda) desde los textos sobre la cabecera."""
    textos = [df.iat[i, j] for i in range(fila_cab) for j in range(df.shape[1])
              if isinstance(df.iat[i, j], str)]
    titulo = next((t for t in textos if "tasas activas" in clave(t)), None)
    if titulo is None:
        raise ValueError("no se encontró el título «Tasas Activas Anuales …»")
    k = clave(titulo)
    if "moneda nacional" in k:
        moneda = "MN"
    elif "moneda extranjera" in k:
        moneda = "ME"
    else:
        raise ValueError(f"no se reconoce la moneda en el título: {titulo!r}")
    if re.search(r"ltimos 30 d", k):
        formulario = "diario_30d"
    elif "durante el mes" in k:
        formulario = "mensual"
    else:
        raise ValueError(f"no se reconoce el formulario en el título: {titulo!r}")
    if m := re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})\s*$", k):
        fecha = dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    elif m := re.search(r"\ba (\w+) del? (\d{4})\s*$", k):
        mes = m.group(1).replace("septiembre", "setiembre")
        if mes not in MESES:
            raise ValueError(f"mes desconocido en el título: {titulo!r}")
        y, mm = int(m.group(2)), MESES.index(mes) + 1
        fecha = dt.date(y, mm, calendar.monthrange(y, mm)[1])
    else:
        raise ValueError(f"no se encontró la fecha en el título: {titulo!r}")
    return formulario, fecha, moneda


def celda(valor) -> tuple[float, str]:
    """(tasa, sin_dato). Texto desconocido → ValueError (no se pierde en silencio)."""
    if isinstance(valor, str):
        s = valor.strip()
        if s.lower() in comun.SIN_DATO:
            return float("nan"), s.lower() or "vacio"
        x = comun.a_numero(s)
        if x is None:
            raise ValueError(f"celda con texto desconocido: {valor!r}")
        return x, ""
    x = comun.a_numero(valor)
    return (float("nan"), "vacio") if x is None else (x, "")


def leer_archivo(ruta: Path, subsistema: str, periodo: int) -> tuple[list[dict], list[str], dict]:
    """Filas del archivo, notas al pie y metadatos (formulario, fecha de corte, nº de entidades)."""
    hojas = comun.abrir(ruta)
    if len(hojas) != 1:
        raise ValueError(f"se esperaba una hoja, hay {list(hojas)}")
    df = next(iter(hojas.values()))
    nr, nc = df.shape
    cab = [(i, j) for i in range(nr) for j in range(nc) if clave(df.iat[i, j]).startswith("tasa anual")]
    if len(cab) != 1:
        raise ValueError(f"se esperaba una celda «Tasa Anual (%)», hay {len(cab)}")
    fc, jc = cab[0]
    formulario, fecha, moneda = leer_titulo(df, fc)
    if fecha.year * 100 + fecha.month != periodo:
        raise ValueError(f"el título es de {fecha:%Y-%m} y el archivo dice {periodo}")

    # Columnas de entidades: textos a la derecha de «Tasa Anual (%)».
    columnas: dict[int, tuple[str, str | None, bool]] = {}
    for j in range(jc + 1, nc):
        v = df.iat[fc, j]
        if isinstance(v, str) and v.strip():
            columnas[j] = resolver(comun.limpiar(v), subsistema)
        elif any(comun.a_numero(df.iat[i, j]) is not None for i in range(fc + 1, nr)):
            raise ValueError(f"columna {j} con cifras y sin nombre de entidad")
    if sum(p for _, _, p in columnas.values()) != 1:
        raise ValueError("se esperaba exactamente una columna «Promedio»")

    filas: list[dict] = []
    notas: list[str] = []
    tipo = None
    vistos: set[tuple[str, str]] = set()
    fin = False
    for i in range(fc + 1, nr):
        etiqueta = df.iat[i, jc]
        valores = [df.iat[i, j] for j in columnas]
        con_dato = any(isinstance(v, str) and v.strip() or comun.a_numero(v) is not None for v in valores)
        if not isinstance(etiqueta, str) or not etiqueta.strip():
            if con_dato:
                raise ValueError(f"fila {i} con cifras y sin etiqueta")
            fin = fin or bool(filas)  # la primera fila vacía tras los datos cierra el cuadro
            continue
        k = clave(etiqueta)
        if k in _TIPOS_K and not fin:
            texto, tipo = _TIPOS_K[k]
            sub = "total"
        elif k in _ETIQ_K and not fin:
            texto, sub = _ETIQ_K[k]
            if tipo is None or sub not in SUBPRODUCTOS[tipo]:
                raise ValueError(f"fila {i}: «{comun.limpiar(etiqueta)}» bajo el tipo {tipo!r}")
        elif NOTA_RE.match(etiqueta) or fin:
            if con_dato:
                raise ValueError(f"fila {i}: nota o texto con cifras: {comun.limpiar(etiqueta)[:60]!r}")
            notas.append(comun.limpiar(etiqueta.replace("&nbsp;", " ")))
            fin = True
            continue
        else:
            raise ValueError(f"fila {i}: etiqueta desconocida {comun.limpiar(etiqueta)!r} "
                             "(agregarla a ETIQUETAS/TIPOS si es legítima)")
        if (tipo, sub) in vistos:
            raise ValueError(f"fila {i}: {tipo}/{sub} repetido")
        vistos.add((tipo, sub))
        for j, (nombre, id_entidad, es_promedio) in columnas.items():
            tasa, sin_dato = celda(df.iat[i, j])
            filas.append({"entidad_original": nombre, "id_entidad": id_entidad, "es_promedio": es_promedio,
                          "tipo_credito": tipo, "subproducto": sub, "etiqueta_original": texto,
                          "tasa": tasa, "sin_dato": sin_dato})
    esperados = {(t, s) for t, subs in SUBPRODUCTOS.items() for s in ["total", *subs]}
    if faltan := esperados - vistos:
        raise ValueError(f"faltan filas: {sorted(faltan)}")
    meta = {"formulario": formulario, "fecha_corte": fecha, "moneda": moneda,
            "entidades": len(columnas) - 1}
    return filas, notas, meta


def cargar_config() -> dict[str, dict]:
    with open(TASAS_CSV, encoding="utf-8") as fh:
        return {r["subsistema"]: r for r in csv.DictReader(fh)}


def leer_todo(subsistemas: list[str] | None, desde: int, hasta: int) -> tuple[pd.DataFrame, int]:
    config = cargar_config()
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    partes, log, notas = [], [], []
    errores = 0
    for sub, cfg in config.items():
        if subsistemas and sub not in subsistemas:
            continue
        patron = f"{cfg['tip']}_TIActivaTipoCreditoEmpresa*-*.xlsx"
        for ruta in sorted((RAW_DIR / sub).glob(patron)):
            m = re.search(r"-(\d{6})\.xlsx$", ruta.name)
            periodo = int(m.group(1))
            if not desde <= periodo <= hasta:
                continue
            try:
                filas, ns, meta = leer_archivo(ruta, sub, periodo)
                if meta["formulario"] != FORMULARIOS[cfg["formulario"]]:
                    raise ValueError(f"formulario {meta['formulario']} y config/tasas.csv dice {cfg['formulario']}")
            except Exception as exc:  # un archivo raro no detiene el resto; queda en el control
                errores += 1
                log.append((ruta.name, sub, periodo, "", "", 0, 0, f"{type(exc).__name__}: {exc}"))
                continue
            log.append((ruta.name, sub, periodo, meta["fecha_corte"].isoformat(), meta["formulario"],
                        meta["entidades"], len(filas), ""))
            notas += [(sub, periodo, n) for n in ns]
            d = pd.DataFrame(filas)
            d.insert(0, "periodo", periodo)
            d.insert(1, "fecha_corte", pd.Timestamp(meta["fecha_corte"]))
            d.insert(2, "subsistema", sub)
            d.insert(3, "formulario", meta["formulario"])
            d["moneda"] = meta["moneda"]
            partes.append(d)
    with open(CONTROL_DIR / "archivos.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["archivo", "subsistema", "periodo", "fecha_corte", "formulario", "entidades",
                    "filas", "error"])
        w.writerows(log)
    pd.DataFrame(notas, columns=["subsistema", "periodo", "nota"]).to_csv(
        CONTROL_DIR / "notas.csv", index=False, encoding="utf-8")
    if not partes:
        return pd.DataFrame(columns=COLUMNAS), errores
    df = pd.concat(partes, ignore_index=True)[COLUMNAS]
    for c in ["subsistema", "formulario", "tipo_credito", "subproducto", "moneda", "sin_dato"]:
        df[c] = df[c].astype("category")
    return df, errores


def controles_entidades(df: pd.DataFrame) -> tuple[int, int]:
    """Escribe sin_resolver.csv y vigencia.csv. Devuelve (nº sin resolver, nº discrepancias)."""
    ent = df[~df["es_promedio"]].drop_duplicates(["periodo", "subsistema", "entidad_original", "id_entidad"])
    sin = (ent[ent["id_entidad"].isna()].groupby(["subsistema", "entidad_original"], observed=True)["periodo"]
           .agg(desde="min", hasta="max", meses="count").reset_index())
    sin.to_csv(CONTROL_DIR / "sin_resolver.csv", index=False, encoding="utf-8")
    # Vigencia: ¿el maestro dice que la entidad estaba en este subsistema ese mes?
    # Las EDPYME («edpyme» en el maestro) se publican junto con las empresas de créditos.
    m = maestro()
    filas = []
    for r in ent[ent["id_entidad"].notna()].itertuples():
        v = m.vigencia(r.id_entidad, r.periodo)
        sub_vig = v["subsistema"] if v else ""
        equivalente = sub_vig == r.subsistema or (sub_vig == "edpyme" and r.subsistema == "empresas-credito")
        if not equivalente:
            filas.append((r.subsistema, r.id_entidad, r.entidad_original, r.periodo, sub_vig,
                          v["nombre"] if v else ""))
    vig = pd.DataFrame(filas, columns=["subsistema", "id_entidad", "entidad_original", "periodo",
                                       "subsistema_vigencia", "nombre_vigencia"])
    if len(vig):
        vig = (vig.groupby(["subsistema", "id_entidad", "entidad_original", "subsistema_vigencia",
                            "nombre_vigencia"])["periodo"].agg(desde="min", hasta="max", meses="count")
               .reset_index())
    vig.to_csv(CONTROL_DIR / "vigencia.csv", index=False, encoding="utf-8")
    return len(sin), len(vig)


# --------------------------------------------------------------------------------------------
# Validación
# --------------------------------------------------------------------------------------------
def _iter_periodos(desde: int, hasta: int):
    y, m = divmod(desde, 100)
    while y * 100 + m <= hasta:
        yield y * 100 + m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def validar(df: pd.DataFrame, destino: Path = CONTROL_DIR) -> dict:
    """Controles de calidad sobre la tabla larga; escribe un CSV por control en `destino`.

    - cobertura.csv: periodo × subsistema → nº de entidades (vacío = falta el archivo).
    - entidades_vs_panel.csv: entidades con tasa vs. entidades del panel entidad × mes, por mes.
    - rango.csv: tasas > TASA_MAXIMA o ≤ 0.
    - series_entidad_subproducto.csv: primer/último mes con tasa, meses y huecos por entidad × subproducto.
    - promedio.csv: promedio del subsistema fuera del [mín, máx] de las entidades.
    - etiquetas.csv: cada etiqueta con su primer y último periodo (consistencia 2015 → 2026).
    - resumen.csv: una línea por control.
    """
    destino.mkdir(parents=True, exist_ok=True)
    config = cargar_config()
    resumen = []
    ent = df[~df["es_promedio"]]

    # 1. Cobertura periodo × subsistema.
    n_ent = (ent.drop_duplicates(["periodo", "subsistema", "entidad_original"])
             .groupby(["periodo", "subsistema"], observed=True).size().unstack("subsistema"))
    hasta = int(df["periodo"].max())
    faltan = []
    for sub, cfg in config.items():
        ult = int(df.loc[df["subsistema"] == sub, "periodo"].max()) if (df["subsistema"] == sub).any() else hasta
        for p in _iter_periodos(int(cfg["desde"]), ult):
            if sub not in n_ent or p not in n_ent.index or pd.isna(n_ent.at[p, sub]):
                faltan.append((sub, p))
    n_ent.to_csv(destino / "cobertura.csv", encoding="utf-8")
    resumen.append(("cobertura", len(faltan),
                    "meses sin archivo desde el inicio de config/tasas.csv: "
                    + (", ".join(f"{s} {p}" for s, p in faltan) or "ninguno")))

    # 2. Entidades vs. panel entidad × mes: columnas del archivo, entidades con al menos una tasa
    #    y entidades del panel. Los meses fuera del panel (p. ej. el último de B y F) quedan sin cifra.
    con_tasa = ent[ent["tasa"].notna()]
    ids_de = lambda s: set(s.dropna())  # noqa: E731
    cols = ent.groupby(["periodo", "subsistema"], observed=True)["id_entidad"].agg(ids_de)
    t = con_tasa.groupby(["periodo", "subsistema"], observed=True)["id_entidad"].agg(ids_de)
    pn = pd.Series(dtype=object)
    if PANEL_FILE.exists():
        panel = pd.read_parquet(PANEL_FILE, columns=["periodo", "subsistema", "id_entidad", "es_total"])
        panel = panel[~panel["es_total"].astype(bool)]
        pn = panel.groupby(["periodo", "subsistema"])["id_entidad"].agg(set)
    filas = []
    for (p, sub), ids in cols.items():
        con = t.get((p, sub), set())
        pids = pn.get((p, sub))
        filas.append((p, sub, len(ids), len(con), None if pids is None else len(pids),
                      " ".join(sorted(ids - con)),
                      "" if pids is None else " ".join(sorted(pids - ids)),
                      "" if pids is None else " ".join(sorted(ids - pids))))
    vp = pd.DataFrame(filas, columns=["periodo", "subsistema", "entidades_archivo", "entidades_con_tasa",
                                      "entidades_panel", "en_archivo_sin_tasa", "solo_en_panel",
                                      "solo_en_tasas"])
    vp.to_csv(destino / "entidades_vs_panel.csv", index=False, encoding="utf-8")
    dif = vp[(vp["solo_en_tasas"] != "") | (vp["solo_en_panel"] != "")]
    resumen.append(("entidades_vs_panel", len(dif),
                    "meses × subsistema en que las entidades del archivo difieren de las del panel"))
    resumen.append(("entidades_sin_tasa", int((vp["en_archivo_sin_tasa"] != "").sum()),
                    "meses × subsistema con alguna entidad listada pero todo «-»/«s.i.»"))

    # 3. Rango de tasas.
    fuera = df[(df["tasa"] > TASA_MAXIMA) | (df["tasa"] <= 0)]
    fuera.to_csv(destino / "rango.csv", index=False, encoding="utf-8")
    resumen.append(("rango", len(fuera), f"celdas con tasa > {TASA_MAXIMA:g} % o <= 0"))

    # 4. Entidad × subproducto: aparecen / desaparecen.
    claves = ["subsistema", "id_entidad", "tipo_credito", "subproducto"]
    g = con_tasa.dropna(subset=["id_entidad"]).groupby(claves, observed=True)["periodo"]
    meses_pub = {sub: sorted(df.loc[df["subsistema"] == sub, "periodo"].unique()) for sub in config}
    filas = []
    for k, periodos in g:
        ps = sorted(set(periodos))
        universo = [p for p in meses_pub[k[0]] if ps[0] <= p <= ps[-1]]
        filas.append((*k, ps[0], ps[-1], len(ps), len(universo) - len(ps)))
    series = pd.DataFrame(filas, columns=[*claves, "primer_periodo", "ultimo_periodo", "meses_con_tasa",
                                          "huecos"])
    series.to_csv(destino / "series_entidad_subproducto.csv", index=False, encoding="utf-8")
    resumen.append(("series_entidad_subproducto", int((series["huecos"] > 0).sum()),
                    f"{len(series)} series entidad × subproducto; las que tienen huecos intermedios"))

    # 5. Promedio del subsistema dentro del [mín, máx] de las entidades.
    k5 = ["periodo", "subsistema", "tipo_credito", "subproducto"]
    rango = con_tasa.groupby(k5, observed=True)["tasa"].agg(minimo="min", maximo="max", entidades="count")
    prom = df[df["es_promedio"]].set_index(k5)["tasa"].rename("promedio")
    pr = rango.join(prom, how="outer").reset_index()
    pr["fuera_de_rango"] = ((pr["promedio"] < pr["minimo"] - TOLERANCIA_PROMEDIO)
                            | (pr["promedio"] > pr["maximo"] + TOLERANCIA_PROMEDIO))
    pr["promedio_sin_entidades"] = pr["promedio"].notna() & pr["entidades"].isna()
    pr["entidades_sin_promedio"] = pr["promedio"].isna() & pr["entidades"].notna()
    malos = pr[pr["fuera_de_rango"] | pr["promedio_sin_entidades"] | pr["entidades_sin_promedio"]]
    malos.to_csv(destino / "promedio.csv", index=False, encoding="utf-8")
    resumen.append(("promedio_fuera_de_rango", int(pr["fuera_de_rango"].sum()),
                    f"de {int(pr['promedio'].notna().sum())} promedios publicados (tolerancia "
                    f"{TOLERANCIA_PROMEDIO} pp)"))
    resumen.append(("promedio_sin_entidades", int(pr["promedio_sin_entidades"].sum()),
                    "promedio publicado y ninguna entidad con tasa"))
    resumen.append(("entidades_sin_promedio", int(pr["entidades_sin_promedio"].sum()),
                    "entidades con tasa y promedio «-»"))

    # 6. Consistencia de etiquetas entre años.
    et = (df.drop_duplicates(["periodo", "subsistema", "tipo_credito", "subproducto"])
          .groupby(["tipo_credito", "subproducto", "etiqueta_original"], observed=True)
          .agg(primer_periodo=("periodo", "min"), ultimo_periodo=("periodo", "max"),
               archivos=("periodo", "size")).reset_index())
    et.to_csv(destino / "etiquetas.csv", index=False, encoding="utf-8")
    n_arch = df.drop_duplicates(["periodo", "subsistema"]).shape[0]
    resumen.append(("etiquetas", int((et["archivos"] != n_arch).sum()),
                    f"etiquetas que no están en los {n_arch} archivos"))

    out = pd.DataFrame(resumen, columns=["control", "casos", "detalle"])
    out.to_csv(destino / "resumen.csv", index=False, encoding="utf-8")
    return {r[0]: r[1] for r in resumen}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--subsistema", action="append")
    p.add_argument("--desde", type=int, default=0, help="AAAAMM")
    p.add_argument("--hasta", type=int, default=999999, help="AAAAMM")
    p.add_argument("--destino", type=Path, default=OUT_FILE, help="Parquet de salida (para pruebas).")
    p.add_argument("--solo-validar", action="store_true", help="Valida el parquet existente.")
    args = p.parse_args()

    t0 = time.time()
    if args.solo_validar:
        df, errores = pd.read_parquet(args.destino), 0
    else:
        df, errores = leer_todo(args.subsistema, args.desde, args.hasta)
        sin, vig = controles_entidades(df)
        args.destino.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(args.destino, index=False)
        archivos = df.drop_duplicates(["periodo", "subsistema"]).shape[0]
        print(f"tasas activas: {archivos} archivos leídos, {errores} con error, {len(df):,} filas, "
              f"{sin} nombres sin resolver, {vig} discrepancias de vigencia, {time.time() - t0:.0f} s")
        errores += sin
    for control, casos in validar(df).items():
        print(f"  {control}: {casos}")
    return 1 if errores else 0


if __name__ == "__main__":
    sys.exit(main())
