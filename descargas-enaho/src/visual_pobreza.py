"""Genera `outputs/pobreza_departamental.html`: tablero de pobreza monetaria por departamento, Perú.

Lee lo ya calculado y validado (no recalcula ninguna estimación):
- `data/processed/pobreza/pobreza_departamentos.parquet`: año × unidad (pobreza total y extrema con
  IC, CV y marca de referencial; gasto, ingreso, población; grupos oficial y calculado 2016–2025).
- `data/processed/pobreza/pobreza_ambitos.parquet`: nacional, urbano y rural (y el IC del gasto y del
  ingreso por departamento).
- `data/processed/pobreza/grupos_departamentos.parquet`: IC propio de cada grupo calculado.
- `config/grupos_departamentos_oficial_2016_2025.csv` y `config/pobreza_oficial_2004_2015.csv`:
  grupos oficiales del INEI (pertenencia e intervalo publicado).
- `config/pobreza_oficial_departamental_2016_2025.csv`: IC y CV oficiales de 2025 (para el tooltip).
- `docs/referencias_inei/pobreza_2004_2015/fuentes.md`: títulos y URL oficiales de los informes.
- Geometría: `../descargas-sbs/config/geo/departamentos_svg.json` (solo lectura).

Inyecta los datos en `src/plantillas/pobreza.html` y escribe dos archivos:
- `outputs/pobreza_departamental.html` (local, se abre con doble clic);
- `outputs/pobreza_departamental_artifact.html` (para publicar como Artifact de claude.ai).

Uso:
    python src/visual_pobreza.py
"""
from __future__ import annotations

import datetime as dt
import json
import math
import re
import sys
from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parents[1]
POBREZA = PROJECT_DIR / "data" / "processed" / "pobreza"
CONFIG = PROJECT_DIR / "config"
FUENTES_2004_2015 = PROJECT_DIR / "docs" / "referencias_inei" / "pobreza_2004_2015" / "fuentes.md"
GEO = PROJECT_DIR.parent / "descargas-sbs" / "config" / "geo" / "departamentos_svg.json"
TEMPLATE = PROJECT_DIR / "src" / "plantillas" / "pobreza.html"
OUT = PROJECT_DIR / "outputs" / "pobreza_departamental.html"
OUT_ARTIFACT = PROJECT_DIR / "outputs" / "pobreza_departamental_artifact.html"
PLACEHOLDER = "/*__DATA__*/null"
# Población oficial al 30 de junio (INEI, Boletín Especial N° 24, base Censo 2017), de descargas-inei (solo lectura).
POPULATION_SOURCE = PROJECT_DIR.parent / "descargas-inei" / "data" / "processed" / "poblacion_adulta.csv"
POPULATION_FILE = PROJECT_DIR / "config" / "insumo_poblacion_adulta.csv"   # copia que viaja con el proyecto
POPULATION_COLS = ["anio", "poblacion_total", "poblacion_18_mas", "tipo_cifra", "base_censal", "fuente", "cuadro_fuente"]
POOR_COUNT_OFFICIAL = CONFIG / "pobres_nacional_oficial.csv"

# =============================================================================================
# CONFIGURACIÓN (pendientes que pueden cambiar: editar aquí, no en la plantilla)
# =============================================================================================

# Número de personas pobres (solo nacional y solo pobreza total). Método del INEI, validado el 2026-11-03
# con src/validar_poblacion_pobre.py: incidencia publicada (1 decimal) × población oficial al 30 de junio.
# Reproduce las cifras publicadas desde POOR_COUNT_CURRENT_FROM; antes, los informes usaban las proyecciones
# de población base Censo 2007 y sus cifras no son comparables con este cálculo.
POOR_COUNT_CURRENT_FROM = 2019
POOR_COUNT_TOL_MILES = 0.5

# Primer año que se publica. Validación 2004–2015 cerrada el 2026-11-03 (494/494 cifras oficiales):
# se publica toda la serie 2004–2025.
START_YEAR = 2004
# Último año: None = el último del Parquet.
END_YEAR: int | None = None

# Quiebres que se marcan en los gráficos de series. tipo «linea»: cambio desde ese año (línea
# vertical entre el año anterior y ese año); tipo «anio»: año atípico (columna sombreada).
# Textos tomados de docs/pobreza/textos_verificados.md (§3.2, §4) con su fuente.
SERIES_BREAKS = [
    {"anio": 2007, "tipo": "linea", "corto": "Nuevo marco",
     "texto": "Desde 2007 la ENAHO usa un marco muestral actualizado, una muestra renovada y un panel "
              "(viviendas que se vuelven a entrevistar) que rota un quinto cada año; de 2002 a 2006 ese panel "
              "era fijo. El INEI no lo trata como un quiebre de la serie de pobreza, pero 2004–2006 tienen "
              "menos hogares en la muestra.",
     "fuente": "INEI, Informe de Calidad de la Encuesta ENAHO 2025, págs. 11–12; Informe técnico de "
               "pobreza monetaria 2016-2025, pág. 405; Evolución de la Pobreza 2004-2010. Nueva Metodología "
               "(marzo de 2012), pág. 25"},
    {"anio": 2013, "tipo": "linea", "corto": "Lima en tres",
     "texto": "Hasta los datos de 2012 el INEI publicaba un solo «Lima» que incluía al Callao (24 "
              "unidades). Desde los datos de 2013 publica por separado Lima Metropolitana, Región Lima y "
              "el Callao (26 unidades). Antes de 2013, las tres cifras separadas de este tablero son "
              "cálculo propio con los microdatos.",
     "fuente": "INEI, Evolución de la pobreza monetaria 2007-2016, págs. 45–48; 2009-2015, pág. 47"},
    {"anio": 2020, "tipo": "anio", "corto": "Pandemia",
     "texto": "Año atípico por la modalidad de entrevista: el 49 % de la muestra se entrevistó por "
              "teléfono, con un cuestionario reducido hasta setiembre. Las preguntas para medir la "
              "pobreza monetaria se mantuvieron «con la finalidad de asegurar la comparabilidad», y 2020 "
              "forma parte de la serie oficial.",
     "fuente": "INEI, Informe técnico de pobreza monetaria 2009-2020, pág. 180; 2016-2025, pág. 76"},
]

# Marca por tramo de años de las cifras DEPARTAMENTALES (tooltips y pestaña metodológica).
# hasta = None: hasta el último año. Fuente: docs/validacion_pobreza_2004_2015.md §6 y
# docs/validacion_pobreza_departamental.md §1.
YEAR_STATUS = [
    {"desde": 2004, "hasta": 2006, "corto": "Estimación propia",
     "texto": "Marco muestral anterior a 2007; estimación propia. Reproduce los límites de los grupos que "
              "el INEI publicó para esos años."},
    {"desde": 2007, "hasta": 2013, "corto": "Estimación propia",
     "texto": "Estimación propia con la metodología del INEI; el INEI no publicó cifras puntuales por "
              "departamento para estos años. Reproduce los intervalos de los grupos que publicó el INEI."},
    {"desde": 2014, "hasta": None, "corto": "Coincide con el INEI",
     "texto": "La cifra puntual coincide con la oficial del INEI."},
]
# Pobreza EXTREMA por departamento: no se contrastó con cifras puntuales del INEI (el informe 2016-2025 solo
# trae grupos; los informes antiguos no se revisaron para esto). Desde 2010 se validó con los grupos del INEI.
YEAR_STATUS_EXTREMA = [
    {"desde": 2004, "hasta": 2009, "corto": "Estimación propia",
     "texto": "Estimación propia con la metodología del INEI; no se contrastó con cifras departamentales del INEI."},
    {"desde": 2010, "hasta": None, "corto": "Estimación propia",
     "texto": "Estimación propia con la metodología del INEI. Reproduce los intervalos de los grupos de pobreza "
              "extrema que publica el INEI."},
]
# Hasta los datos de 2012 los grupos del INEI tenían un solo «Lima» con el Callao: las tres unidades
# separadas heredan ese grupo (textos_verificados.md §3.2 y §3.3).
LIMA_SPLIT_UNITS = ["15LM", "15LP", "07"]
LIMA_SPLIT_LAST_YEAR = 2012
LIMA_SPLIT_TEXT = ("En los grupos del INEI de este año, Lima Metropolitana, Región Lima y el Callao eran una sola "
                   "unidad («Lima», que incluía al Callao); aquí cada una hereda ese grupo. Sus cifras por "
                   "separado son cálculo propio con los microdatos.")
# Años atípicos que se añaden a la marca del tramo.
YEAR_EXTRA = {2020: "Año atípico (pandemia, entrevista telefónica)."}
STATUS_GENERAL = ("Serie con la metodología vigente (año base 2010, publicada en marzo de 2012): no "
                  "comparable con las cifras que el INEI publicó antes de marzo de 2012, con la metodología anterior.")

# Años con grupos oficiales del INEI («estadísticamente semejantes»), por indicador. En los demás
# años se usa la agrupación propia (grupo_*_calculado), rotulada como tal.
OFFICIAL_GROUPS_YEARS = {
    "pobreza_total": range(2004, 2026),
    "pobreza_extrema": range(2010, 2026),
}

# Gasto e ingreso real per cápita por departamento: False los quita por completo.
SHOW_SPENDING = True
# Primer año con gasto e ingreso: 2016, el primero de los Cuadros I.1 y I.15 del informe 2016-2025 con los
# que se validó el cálculo (1 300/1 300 cifras). Antes de ese año la serie no se publica (va null y el
# tablero lo explica en una nota; no se muestran guiones).
SPENDING_START_YEAR = 2016
# Años en que el IC y el CV de la pobreza TOTAL por departamento se toman del Cuadro III.1 oficial en lugar
# del cálculo propio (el INEI usa ahí un cálculo de varianza que no se reproduce con los microdatos: hasta
# 0,17 pp). La cifra puntual siempre es la calculada (cuadra al decimal con la oficial).
OFFICIAL_PRECISION_YEARS = [2023, 2024, 2025]   # cada informe publica la precisión de su último año
# Umbral de cifra referencial: CV mayor al 15 % (INEI, informe 2016-2025, pág. 232).
CV_REFERENCIAL = 15.0

# Cómo se muestran Lima y el Callao:
# - "inei26": las 26 unidades del INEI (Lima Metropolitana, Región Lima y Callao) en todos los años.
#   Antes de 2013 son cálculo propio; en 2004–2012 heredan el grupo oficial de «Lima con Callao».
# - "inei_historico": 24 unidades con «Lima con Callao» hasta 2012 y 26 desde 2013, como publicó el INEI.
UNIT_SCHEME = "inei26"

# Regiones naturales y dominios (validados: 594/594 en 2016–2025 y 494/494 en 2004–2015, incluidos estos ámbitos).
REGIONES = [("costa", "Costa"), ("sierra", "Sierra"), ("selva", "Selva")]
DOMINIOS = [("costa_urbana", "Costa urbana"), ("costa_rural", "Costa rural"), ("sierra_urbana", "Sierra urbana"),
            ("sierra_rural", "Sierra rural"), ("selva_urbana", "Selva urbana"), ("selva_rural", "Selva rural"),
            ("lima_metropolitana_callao", "Lima Metropolitana y el Callao")]

# Hitos de la serie nacional de pobreza total, con frases textuales del INEI (textos_verificados.md §5).
HITOS = [
    {"anio": 2010, "desde": 2004,
     "cita": "entre el año 2004 y 2010 la incidencia de la pobreza en la serie actualizada se redujo en 27,9 puntos "
             "porcentuales, al pasar de 58,7% a 30,8%",
     "fuente": "INEI, Evolución de la Pobreza 2004-2010. Nueva Metodología (marzo de 2012), pág. 12"},
    {"anio": 2020, "desde": 2019,
     "cita": "Para el año 2020, el 30,1% de la población del país … se encontraban en situación de pobreza … los "
             "niveles de pobreza han sufrido un fuerte incremento de 9,9 puntos porcentuales, que equivale a 3 "
             "millones 330 mil personas pobres, más que en el año 2019",
     "fuente": "INEI, Informe técnico de pobreza monetaria 2009-2020, pág. 39"},
    {"anio": 2021, "desde": 2020,
     "cita": "Para el año 2021, el 25,9% … los niveles de pobreza han sufrido una disminución de 4,2 puntos "
             "porcentuales … Al comparar estos resultados con el nivel obtenido en el año 2019 (prepandemia), se "
             "observa que los niveles de pobreza han sufrido un incremento de 5,7 puntos porcentuales",
     "fuente": "INEI, Informe técnico de pobreza monetaria 2010-2021, pág. 56"},
    {"anio": 2025, "desde": 2024,
     "cita": "En el año 2025, la pobreza monetaria afectó al 25,7% de la población del país … el nivel de pobreza "
             "disminuyó en 1,9 puntos porcentuales, siendo este resultado altamente significativo … Al comparar este "
             "resultado con el obtenido el año 2019 (prepandemia), se observa que el nivel de pobreza se ha "
             "incrementado en 5,5 puntos porcentuales, de forma muy altamente significativa …",
     "fuente": "INEI, Informe técnico de pobreza monetaria 2016-2025, pág. 68"},
]

# Significancia oficial de los cambios por departamento (Cuadro III.1 de los informes 2014-2023, 2015-2024 y
# 2016-2025), transcrita por src/transcribir_significancia_departamental.py.
SIGNIFICANCE_CSV = CONFIG / "significancia_departamental_oficial.csv"

# Significancia de los cambios nacionales publicada por el INEI (no se calcula aquí).
# Clave: (año, año de comparación, indicador). Textos de textos_verificados.md §5 y §2.2.
NATIONAL_SIGNIFICANCE = {
    (2025, 2024, "pobreza_total"): {"txt": "altamente significativa (p < 0,05)",
                                   "fuente": "INEI, Informe técnico de pobreza monetaria 2016-2025, pág. 68"},
    (2025, 2019, "pobreza_total"): {"txt": "muy altamente significativa (p < 0,01)",
                                   "fuente": "INEI, Informe técnico de pobreza monetaria 2016-2025, pág. 68"},
}

# Notas de grupos concretos (erratas del INEI y correcciones), visibles en el tablero.
GROUP_NOTES = {
    ("pobreza_total", 2007, 1): "El cuadro de grupos del informe de marzo de 2012 publica 61–72 % para este "
                                "grupo, una errata: la estimación de Huancavelica es 85,0 %. Se usa el intervalo "
                                "publicado en el informe 2007-2017 (80,9–89,1 %).",
    ("pobreza_extrema", 2018, 3): "Errata del INEI: para el año 2018, el Cuadro 4.4 del informe 2016-2025 omite "
                                  "Apurímac y La Libertad (solo lista "
                                  "24 de las 26 unidades). Se añaden a este grupo porque caen en su posición "
                                  "del ordenamiento y, con ellos, el intervalo del grupo reproduce el publicado "
                                  "(2,6–3,6 %).",
}

# =============================================================================================

UNITS = [
    ("01", "Amazonas", None, "amazonas"), ("02", "Áncash", None, "ancash"),
    ("03", "Apurímac", None, "apurimac"), ("04", "Arequipa", None, "arequipa"),
    ("05", "Ayacucho", None, "ayacucho"), ("06", "Cajamarca", None, "cajamarca"),
    ("07", "Callao", "Provincia Constitucional del Callao", "callao"), ("08", "Cusco", None, "cusco"),
    ("09", "Huancavelica", None, "huancavelica"), ("10", "Huánuco", None, "huanuco"),
    ("11", "Ica", None, "ica"), ("12", "Junín", None, "junin"),
    ("13", "La Libertad", None, "la_libertad"), ("14", "Lambayeque", None, "lambayeque"),
    ("15LM", "Lima Metropolitana", "Lima Metropolitana: los 43 distritos de la provincia de Lima, sin el Callao", None),
    ("15LP", "Región Lima", "Región Lima («Lima 2/» en los cuadros del INEI): provincias de Barranca, "
                            "Cajatambo, Canta, Cañete, Huaral, Huarochirí, Huaura, Oyón y Yauyos", "lima"),
    ("16", "Loreto", None, "loreto"), ("17", "Madre de Dios", None, "madre_de_dios"),
    ("18", "Moquegua", None, "moquegua"), ("19", "Pasco", None, "pasco"),
    ("20", "Piura", None, "piura"), ("21", "Puno", None, "puno"),
    ("22", "San Martín", None, "san_martin"), ("23", "Tacna", None, "tacna"),
    ("24", "Tumbes", None, "tumbes"), ("25", "Ucayali", None, "ucayali"),
    ("15C", "Lima (con el Callao)", "Lima con el Callao: departamento de Lima más la Provincia Constitucional del "
                               "Callao (la unidad «Lima» de los informes del INEI hasta los datos de 2012)", None),
]
UNITS26 = [u[0] for u in UNITS if u[0] != "15C"]
UNITS24 = [u for u in UNITS26 if u not in ("15LM", "15LP", "07")] + ["15C"]
IND = {"pobreza_total": "pt", "pobreza_extrema": "pe"}

WARNINGS: list[str] = []


def warn(msg: str) -> None:
    WARNINGS.append(msg)
    print(f"  AVISO: {msg}")


def num(v, nd: int = 3):
    if v is None or (isinstance(v, float) and math.isnan(v)) or pd.isna(v):
        return None
    return round(float(v), nd)


def units_for_year(year: int) -> list[str]:
    if UNIT_SCHEME == "inei26":
        return UNITS26
    if UNIT_SCHEME == "inei_historico":
        return UNITS24 if year <= 2012 else UNITS26
    raise ValueError(f"UNIT_SCHEME desconocido: {UNIT_SCHEME}")


def year_status(year: int) -> dict:
    for s in YEAR_STATUS:
        if s["desde"] <= year and (s["hasta"] is None or year <= s["hasta"]):
            return s
    raise ValueError(f"YEAR_STATUS no cubre {year}")


# ---------------------------------------------------------------------------------------------
# Fuentes de los informes 2004–2015 (título y URL oficial)
# ---------------------------------------------------------------------------------------------
def load_sources() -> dict:
    out = {}
    for line in FUENTES_2004_2015.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\|\s*([A-Z]\d{4}|[A-Z]\d)\s*\|(.+?)\|(.+?)\|(.+?)\|\s*(https?://\S+)\s*\|", line)
        if not m:
            continue
        title = re.sub(r"\s*\(.*$", "", m.group(2).strip()).replace("*", "").strip()
        pub = m.group(3).strip()
        pub = "mar-2012" if "mar-2012" in pub else pub
        out[m.group(1)] = {"t": "INEI, " + title, "pub": pub, "url": m.group(5)}
    out["POB25"] = {"t": "INEI, Perú: Evolución de la pobreza monetaria 2016-2025. Informe técnico", "pub": "may-2026",
                    "url": "https://cdn.www.gob.pe/uploads/document/file/9911234/8087825-informe-tecnico-de-pobreza-monetaria-2016-2025.pdf?v=1777993734"}
    print(f"  fuentes 2004–2015: {len(out) - 1} informes con URL oficial")
    return out


# ---------------------------------------------------------------------------------------------
# Grupos
# ---------------------------------------------------------------------------------------------
def official_groups(sources: dict) -> dict:
    """{(indicador, año): {"kind", "list": [{g, ids, lo, hi, fuente, nota}]}} con los grupos del INEI."""
    out: dict = {}
    # 2016–2025: Cuadros 4.2 y 4.4 del informe 2016-2025.
    g = pd.read_csv(CONFIG / "grupos_departamentos_oficial_2016_2025.csv", dtype=str)
    for r in g.itertuples():
        key = (r.indicador, int(r.anio))
        out.setdefault(key, {"kind": "ic", "list": []})["list"].append({
            "g": int(r.grupo), "ids": r.ambito_ids.split(";"), "lo": float(r.ic_inf), "hi": float(r.ic_sup),
            "fuente": f"{sources['POB25']['t']}, {r.cuadro}, pág. {r.pagina}", "url": sources["POB25"]["url"]})
    # 2004–2015: informes de cada año (config/pobreza_oficial_2004_2015.csv, filas grupoN:...).
    o = pd.read_csv(CONFIG / "pobreza_oficial_2004_2015.csv", dtype=str)
    o = o[o["ambito"].str.startswith("grupo")]
    for r in o.itertuples():
        year = int(r.anio)
        ind = "pobreza_total" if r.indicador.startswith("pobreza_total") else "pobreza_extrema"
        kind = "rango" if r.indicador.endswith("_rango") else "ic"
        gnum, ids = r.ambito.split(":")
        ids = ids.split("+")
        if year <= 2012:
            if ("15" in ids) != ("07" in ids):
                raise ValueError(f"Grupo {r.ambito} {year}: «15» y «07» deben ir juntos (Lima con Callao)")
            ids = [i for i in ids if i not in ("15", "07")] + (["15C"] if "15" in ids else [])
        ids = ["15LP" if i == "15LR" else i for i in ids]
        src = sources.get(r.fuente.split("|")[0], {"t": r.fuente, "url": None})
        out.setdefault((ind, year), {"kind": kind, "list": []})["list"].append({
            "g": int(gnum.replace("grupo", "")), "ids": ids, "lo": float(r.ic_inf), "hi": float(r.ic_sup),
            "fuente": f"{src['t']}, pág. {r.pagina.split('|')[0]} del PDF", "url": src.get("url")})
    for (ind, year), v in out.items():
        v["list"].sort(key=lambda x: x["g"])
        for item in v["list"]:
            note = GROUP_NOTES.get((ind, year, item["g"]))
            if note:
                item["nota"] = note
    return out


def build_groups(dep: pd.DataFrame, years: list[int], sources: dict) -> dict:
    off = official_groups(sources)
    calc = pd.read_parquet(POBREZA / "grupos_departamentos.parquet")
    calc = calc[calc["fuente_grupo"] == "calculado"]
    out = {"pt": {}, "pe": {}}
    for ind, short in IND.items():
        for y in years:
            if y in OFFICIAL_GROUPS_YEARS[ind]:
                if (ind, y) not in off:
                    raise ValueError(f"OFFICIAL_GROUPS_YEARS incluye {ind} {y}, pero no hay grupos oficiales transcritos")
                v = off[(ind, y)]
                members = sorted(i for it in v["list"] for i in it["ids"])
                expected = sorted(UNITS24 if "15C" in members else UNITS26)
                if members != expected:
                    warn(f"grupos oficiales {ind} {y}: la pertenencia no es una partición de las unidades "
                         f"(sobran {set(members) - set(expected)}, faltan {set(expected) - set(members)})")
                # Control 2016–2025: la pertenencia transcrita coincide con la columna del Parquet.
                if y >= 2016:
                    col = dep[(dep["anio"] == y) & dep["en_cuadro_inei_26"]].set_index("ambito_id")[f"grupo_{ind}_oficial"]
                    for it in v["list"]:
                        for i in it["ids"]:
                            if int(col[i]) != it["g"]:
                                warn(f"grupo oficial {ind} {y} {i}: CSV {it['g']} vs Parquet {col[i]}")
                out[short][y] = {"src": "oficial", "kind": v["kind"], "k": len(v["list"]), "list": v["list"]}
            else:
                c = calc[(calc["indicador"] == ind) & (calc["anio"] == y)].sort_values("grupo")
                if c.empty:
                    raise ValueError(f"Sin agrupación calculada para {ind} {y}")
                lst = [{"g": int(r.grupo), "ids": r.ambito_ids.split(";"), "lo": num(r.ic_inf, 2), "hi": num(r.ic_sup, 2),
                        "v": num(r.valor, 2)} for r in c.itertuples()]
                col = dep[(dep["anio"] == y) & dep["en_cuadro_inei_26"]].set_index("ambito_id")[f"grupo_{ind}_calculado"]
                for it in lst:
                    for i in it["ids"]:
                        if int(col[i]) != it["g"]:
                            warn(f"grupo calculado {ind} {y} {i}: grupos {it['g']} vs Parquet {col[i]}")
                out[short][y] = {"src": "calculado", "kind": "ic_propio", "k": len(lst), "list": lst}
    n_off = {s: sum(1 for v in out[s].values() if v["src"] == "oficial") for s in out}
    print(f"  grupos: oficiales total {n_off['pt']} años, extrema {n_off['pe']} años; el resto, agrupación propia")
    return out


# ---------------------------------------------------------------------------------------------
# Series
# ---------------------------------------------------------------------------------------------
def series(df: pd.DataFrame, years: list[int], col: str, nd: int) -> list:
    s = df.set_index("anio")[col].reindex(years)
    return [num(v, nd) for v in s.values]


def mask_before(arr: list, years: list[int], first: int) -> list:
    return [None if y < first else v for y, v in zip(years, arr)]


def apply_official_precision(units: dict, years: list[int], inei: dict) -> None:
    """Reemplaza IC, CV y marca referencial de la pobreza total por los del Cuadro III.1 en
    OFFICIAL_PRECISION_YEARS; controla que la cifra puntual calculada redondee a la oficial."""
    for y in OFFICIAL_PRECISION_YEARS:
        if y not in years:
            continue
        off = inei.get(str(y))
        if not off:
            raise ValueError(f"OFFICIAL_PRECISION_YEARS incluye {y}, pero no hay IC oficial transcrito")
        k = years.index(y)
        for uid in UNITS26:
            v, lo, hi, cv = off[uid]
            u = units[uid]
            if abs(u["pt"][k] - v) > 0.05 + 1e-9:
                raise ValueError(f"{uid} {y}: la cifra calculada {u['pt'][k]} no redondea a la oficial {v}")
            u["pt_lo"][k], u["pt_hi"][k], u["pt_cv"][k] = float(lo), float(hi), float(cv)
            u["pt_ref"][k] = int(float(cv) > CV_REFERENCIAL)
        # «Lima con Callao» no está en el Cuadro III.1: su precisión queda calculada.
    print(f"  IC y CV oficiales (Cuadro III.1) de la pobreza total por departamento en {OFFICIAL_PRECISION_YEARS}")


def build_units(dep: pd.DataFrame, amb: pd.DataFrame, years: list[int]) -> dict:
    out = {}
    gasto_ic = amb[amb["ambito_tipo"].isin(["departamento_inei", "departamento_inei_24"])
                   & amb["indicador"].isin(["gasto_real_pc", "ingreso_real_pc"])]
    for uid, *_ in UNITS:
        d = dep[dep["ambito_id"] == uid]
        if d["anio"].nunique() != len(d):
            raise ValueError(f"Unidad {uid} con años repetidos")
        missing = sorted(set(years) - set(d["anio"]))
        if missing:
            raise ValueError(f"Unidad {uid} sin datos en {missing}")
        # Los totales de personas por departamento no se publican: el INEI no los publica y no se pueden validar.
        u = {"n": series(d, years, "n_hogares", 0)}
        for ind, short in IND.items():
            u[short] = series(d, years, ind, 6)
            u[short + "_lo"] = series(d, years, ind + "_ic_inf", 6)
            u[short + "_hi"] = series(d, years, ind + "_ic_sup", 6)
            u[short + "_cv"] = series(d, years, ind + "_cv", 5)
            u[short + "_ref"] = [int(bool(v)) for v in d.set_index("anio")[ind + "_referencial"].reindex(years)]
        if SHOW_SPENDING:
            for ind, short in [("gasto_real_pc", "gr"), ("ingreso_real_pc", "ir")]:
                u[short] = series(d, years, ind, 4)
                g = gasto_ic[(gasto_ic["ambito_id"] == uid) & (gasto_ic["indicador"] == ind)]
                if g.empty:
                    raise ValueError(f"Sin IC de {ind} para {uid}")
                diff = (g.set_index("anio")["valor"].reindex(years) - d.set_index("anio")[ind].reindex(years)).abs().max()
                if diff > 1e-6:
                    warn(f"{ind} {uid}: departamentos y ámbitos difieren en {diff:.4f}")
                u[short + "_lo"] = series(g, years, "ic_inf", 4)
                u[short + "_hi"] = series(g, years, "ic_sup", 4)
                u[short + "_cv"] = series(g, years, "cv", 5)
                for key in (short, short + "_lo", short + "_hi", short + "_cv"):
                    u[key] = mask_before(u[key], years, SPENDING_START_YEAR)
        # Control: la marca referencial del Parquet es CV > 15 (no ≥).
        for short in IND.values():
            for k, (cv, ref) in enumerate(zip(u[short + "_cv"], u[short + "_ref"])):
                if cv is not None and int(cv > CV_REFERENCIAL) != ref:
                    warn(f"{uid} {years[k]} {short}: CV {cv} y marca referencial {ref} no concuerdan")
        out[uid] = u
    return out


def build_ambitos(amb: pd.DataFrame, years: list[int]) -> dict:
    out = {}
    main = [("nacional", "PE", "PE"), ("area", "urbana", "urbana"), ("area", "rural", "rural")]
    extra = [("region_natural", rid, "reg_" + rid) for rid, _ in REGIONES] + \
            [("dominio_inei", did, "dom_" + did) for did, _ in DOMINIOS]
    for tipo, aid, key in main + extra:
        a = amb[(amb["ambito_tipo"] == tipo) & (amb["ambito_id"] == aid)]
        u = {}
        is_main = (tipo, aid, key) in main
        inds = [("pobreza_total", "pt", 6), ("pobreza_extrema", "pe", 6)]
        if SHOW_SPENDING and is_main:
            inds += [("gasto_real_pc", "gr", 4), ("ingreso_real_pc", "ir", 4)]
        for ind, short, nd in inds:
            s = a[a["indicador"] == ind]
            if s["anio"].nunique() != len(years) or set(s["anio"]) != set(years):
                raise ValueError(f"Ámbito {aid} {ind}: años incompletos")
            u[short] = series(s, years, "valor", nd)
            u[short + "_lo"] = series(s, years, "ic_inf", nd)
            u[short + "_hi"] = series(s, years, "ic_sup", nd)
            u[short + "_cv"] = series(s, years, "cv", 5)
            if short in ("gr", "ir"):
                for col in (short, short + "_lo", short + "_hi", short + "_cv"):
                    u[col] = mask_before(u[col], years, SPENDING_START_YEAR)
            if ind.startswith("pobreza"):
                u[short + "_ref"] = [int(bool(v)) for v in s.set_index("anio")["referencial"].reindex(years)]
        out[key] = u
    return out


def build_changes(units: dict, years: list[int]) -> dict:
    """{año: {año_comparación: {ambito_id: [dif_pp, p_valor, estrellas]}}} desde el CSV oficial. Controla que la
    diferencia publicada concuerde (±0,1) con la resta de las cifras calculadas redondeadas a un decimal."""
    if not SIGNIFICANCE_CSV.exists():
        warn(f"No existe {SIGNIFICANCE_CSV.name}: el tablero sale sin la sección de cambios")
        return {"data": {}, "meta": {}}
    c = pd.read_csv(SIGNIFICANCE_CSV, dtype={"ambito_id": str}, keep_default_na=False)
    c = c[c["ambito_id"].isin(UNITS26)]
    out: dict = {}
    meta: dict = {}
    for r in c.itertuples():
        y, b = int(r.anio), int(r.anio_comparacion)
        if y not in years or b not in years:
            continue
        u = units[r.ambito_id]["pt"]
        calc = round(u[years.index(y)], 1) - round(u[years.index(b)], 1)
        if abs(calc - float(r.dif_pp)) > 0.1 + 1e-9:
            warn(f"cambio {r.ambito_id} {y}/{b}: INEI {r.dif_pp} vs cifras {calc:.1f}")
        out.setdefault(str(y), {}).setdefault(str(b), {})[r.ambito_id] = [float(r.dif_pp), float(r.p_valor), r.significancia]
        meta[str(y)] = {"informe": str(r.informe), "pagina": str(r.pagina), "cuadro": str(r.cuadro)}
    for y, d in out.items():
        for b, m in d.items():
            if set(m) != set(UNITS26):
                warn(f"cambios {y}/{b}: faltan {set(UNITS26) - set(m)}")
    print(f"  cambios con significancia oficial: {', '.join(f'{y}/{b}' for y in sorted(out) for b in sorted(out[y]))}")
    return {"data": out, "meta": meta}


def round_half_up(v: float, nd: int = 1) -> float:
    """Redondeo como la cifra publicada (y como toFixed en el navegador para estos valores)."""
    from decimal import Decimal, ROUND_HALF_UP
    return float(Decimal(repr(v)).quantize(Decimal(1).scaleb(-nd), rounding=ROUND_HALF_UP))



def read_population() -> pd.Series:
    """Población total al 30 de junio por año (INEI, Boletín Especial N.° 24). Lee la copia de
    `config/insumo_poblacion_adulta.csv`; si `../descargas-inei` está al lado, antes la refresca desde ahí."""
    if POPULATION_SOURCE.exists():
        new = pd.read_csv(POPULATION_SOURCE)[POPULATION_COLS].to_csv(index=False, lineterminator="\n")
        if not POPULATION_FILE.exists() or POPULATION_FILE.read_text(encoding="utf-8") != new:
            POPULATION_FILE.write_text(new, encoding="utf-8")
    return pd.read_csv(POPULATION_FILE).set_index("anio")["poblacion_total"]

def build_poor_count(amb: dict, years: list[int]) -> dict:
    """Personas pobres, Perú (miles): incidencia redondeada × población oficial al 30 de junio."""
    pop = read_population()
    missing = [y for y in years if y not in pop.index]
    if missing:
        raise ValueError(f"Falta la población oficial de {missing} en {POPULATION_FILE.name}")
    inc = amb["PE"]["pt"]
    # 3 decimales: el navegador redondea al entero; con 1 decimal habría doble redondeo (9 780,49 → 9 780,5 → 9 781).
    miles = [round(round_half_up(inc[i]) / 100 * float(pop[y]) / 1000, 3) for i, y in enumerate(years)]
    off = pd.read_csv(POOR_COUNT_OFFICIAL)
    off = off[off["metodo_derivacion"].str.startswith(("directo", "diferencia")) & ~off["metodo_derivacion"].str.contains("otra")]
    pub = {int(r.anio): {"miles": int(r.pobres_miles_publicado), "fuente": f"{r.fuente}, pág. {r.pagina_pdf}"}
           for r in off.itertuples() if r.anio in years}
    for y, v in pub.items():
        calc = miles[years.index(y)]
        shown = int(round_half_up(calc, 0))       # lo que muestra el tablero (miles enteros)
        if y >= POOR_COUNT_CURRENT_FROM and (abs(calc - v["miles"]) > POOR_COUNT_TOL_MILES or shown != v["miles"]):
            raise ValueError(f"Personas pobres {y}: se mostraría {shown} mil ({calc:.3f}) frente a {v['miles']} mil publicado")
    return {"miles": miles, "pob": [int(pop[y]) for y in years], "pub": {str(y): v for y, v in pub.items()},
            "desde": POOR_COUNT_CURRENT_FROM,
            "fuentePob": "INEI, Perú: Estimaciones y Proyecciones de la Población Nacional, 1950-2070 (Boletín Especial N° 24), población al 30 de junio"}


def build_inei_2025() -> dict:
    """IC y CV oficiales del Cuadro III.1 (último año de cada informe), de
    config/precision_departamental_oficial.csv (src/transcribir_precision_departamental.py)."""
    o = pd.read_csv(CONFIG / "precision_departamental_oficial.csv", dtype={"ambito_id": str})
    return {str(int(y)): {r.ambito_id: [r.valor, r.ic_inf, r.ic_sup, r.cv] for r in g.itertuples()}
            for y, g in o.groupby("anio")}


def build_precision_sources() -> dict:
    o = pd.read_csv(CONFIG / "precision_departamental_oficial.csv").drop_duplicates("anio")
    return {str(int(r.anio)): f"Cuadro III.1 del informe {r.informe.split()[-1]}, pág. {r.pagina_pdf}" for r in o.itertuples()}


def build_geo() -> dict:
    g = json.loads(GEO.read_text(encoding="utf-8"))
    keys = {u[3] for u in UNITS if u[3]}
    if set(g["paths"]) != keys:
        raise ValueError(f"La geometría no tiene las 25 claves esperadas: {set(g['paths']) ^ keys}")
    return {"w": g["w"], "h": g["h"], "paths": g["paths"]}


def artifact_version(html: str) -> str:
    """Versión para publicar como Artifact de claude.ai (igual que los tableros hermanos): la plataforma
    pone su propio <html>/<head>/<body>, así que se dejan solo <title>, <style> y el contenido del body."""
    head = re.search(r"<head>(.*?)</head>", html, re.S).group(1)
    body = re.search(r"<body>(.*?)</body>", html, re.S).group(1)
    head = re.sub(r"\s*<meta (charset|name=\"viewport\")[^>]*>", "", head)
    head = head.replace("</title>", '</title>\n<meta name="claude:viewport-fit-sides" content="cover">', 1)
    return head.strip() + "\n" + body.strip() + "\n"


def main() -> int:
    print("Tablero de pobreza monetaria por departamento")
    dep = pd.read_parquet(POBREZA / "pobreza_departamentos.parquet")
    amb = pd.read_parquet(POBREZA / "pobreza_ambitos.parquet")
    end = END_YEAR or int(dep["anio"].max())
    years = list(range(START_YEAR, end + 1))
    if not set(years) <= set(dep["anio"].astype(int)):
        raise ValueError(f"El Parquet no cubre {years[0]}–{years[-1]}")
    sources = load_sources()
    inei = build_inei_2025()
    units = build_units(dep, amb, years)
    apply_official_precision(units, years, inei)

    data = {
        "gen": dt.date.today().isoformat(), "years": years, "end": end, "start": START_YEAR,
        "showSpending": SHOW_SPENDING, "spendStart": SPENDING_START_YEAR, "scheme": UNIT_SCHEME,
        "precOficial": [y for y in OFFICIAL_PRECISION_YEARS if y in years],
        "precSrc": build_precision_sources(),
        "units": [{"id": i, "name": n, "long": lg or n, "map": m} for i, n, lg, m in UNITS],
        "unitsByYear": {str(y): units_for_year(y) for y in years},
        "dep": units,
        "amb": (ambitos := build_ambitos(amb, years)),
        "pobres": build_poor_count(ambitos, years),
        "groups": build_groups(dep, years, sources),
        "status": [{**s, "hasta": s["hasta"] or end} for s in YEAR_STATUS],
        "statusYear": {str(y): {"corto": year_status(y)["corto"],
                                "texto": year_status(y)["texto"] + (" " + YEAR_EXTRA[y] if y in YEAR_EXTRA else "")}
                       for y in years},
        "statusYearPe": {str(y): next(s for s in YEAR_STATUS_EXTREMA if s["desde"] <= y and (s["hasta"] is None or y <= s["hasta"]))["texto"]
                                 + (" " + YEAR_EXTRA[y] if y in YEAR_EXTRA else "") for y in years},
        "limaSplit": {"units": LIMA_SPLIT_UNITS, "last": LIMA_SPLIT_LAST_YEAR, "texto": LIMA_SPLIT_TEXT},
        "statusGeneral": STATUS_GENERAL,
        "breaks": [b for b in SERIES_BREAKS if START_YEAR < b["anio"] <= end or (b["tipo"] == "anio" and START_YEAR <= b["anio"] <= end)],
        "sig": {f"{a}-{b}-{IND[i]}": v for (a, b, i), v in NATIONAL_SIGNIFICANCE.items()},
        "chg": build_changes(units, years),
        "hitos": [h for h in HITOS if h["desde"] in years and h["anio"] in years],
        "regiones": [{"k": "reg_" + k, "n": n} for k, n in REGIONES],
        "dominios": [{"k": "dom_" + k, "n": n} for k, n in DOMINIOS],
        "inei": inei,
        "sources": [{"k": k, **v} for k, v in sources.items() if k != "POB25"],
        "geo": build_geo(),
    }

    # Controles impresos
    nat = data["amb"]["PE"]
    print(f"  años {years[0]}–{years[-1]}; unidades por año: {len(data['unitsByYear'][str(years[0])])} "
          f"({UNIT_SCHEME}); gasto e ingreso: {'sí' if SHOW_SPENDING else 'no'}")
    print(f"  nacional {end}: pobreza total {nat['pt'][-1]:.2f} % (IC {nat['pt_lo'][-1]:.2f}–{nat['pt_hi'][-1]:.2f}), "
          f"extrema {nat['pe'][-1]:.2f} %, personas pobres {data['pobres']['miles'][-1]:,.1f} mil (método INEI)")
    pubs = data["pobres"]["pub"]
    ok = [y for y in pubs if int(y) >= POOR_COUNT_CURRENT_FROM]
    print(f"  personas pobres: {len(ok)} cifras publicadas desde {POOR_COUNT_CURRENT_FROM} reproducidas exactamente en miles")

    html = TEMPLATE.read_text(encoding="utf-8")
    if PLACEHOLDER not in html:
        raise ValueError(f"La plantilla no tiene el marcador {PLACEHOLDER}")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = html.replace(PLACEHOLDER, payload)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"  {OUT.relative_to(PROJECT_DIR)}  ({OUT.stat().st_size / 1024:.0f} KB; datos {len(payload) / 1024:.0f} KB)")
    art = artifact_version(html)
    for bad in ("G:\\", "C:\\", "data/processed", "config/", "docs/", ".parquet", "descargas-"):
        if bad in art:
            raise ValueError(f"La versión para publicar contiene un detalle interno: {bad!r}")
    OUT_ARTIFACT.write_text(art, encoding="utf-8")
    print(f"  {OUT_ARTIFACT.relative_to(PROJECT_DIR)}  (versión para publicar en claude.ai)")
    if WARNINGS:
        print(f"  {len(WARNINGS)} aviso(s): revisar arriba")
    return 0


if __name__ == "__main__":
    sys.exit(main())
