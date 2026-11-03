"""Datos de comparación para el dashboard de inflación del Perú.

Entrega, en un solo diccionario, lo que el dashboard (`visual_inflacion.py`) necesita además del
IPC de Lima del panel BCRP:

- ``nacional``: IPC nacional del INEI (índice, variación mensual y en 12 meses).
- ``paises``: inflación a 12 meses (IPC general) de los países de la región, en formato largo.
- ``metas``: historia de metas de inflación por país.
- ``fuentes``: texto corto de la fuente de cada país.

Fuentes (solo lectura, en el repositorio hermano ``../../data_macro_paises``):

- Capa comparable: ``data/processed/comparable/comparable_observaciones.parquet`` (indicadores
  ``inflacion_12m`` e ``inflacion_mensual``). Es la serie publicada por cada fuente oficial.
- IPC nacional del Perú: ``data/processed/macro_observaciones.parquet`` (series del INEI
  ``ipc_nacional_indice`` e ``inflacion_nacional_12m``). Si no estuvieran procesadas, se lee el
  Excel crudo ``data/raw/PER/inei/n02_ipc_nacional.xlsx`` (hoja 'Base Dic.2021').
- Metas: ``config/comparable/metas_inflacion.csv``.

Decisiones de comparabilidad (ver ``data_macro_paises/docs/comparabilidad/precios.md``):

- Se usa la inflación 12m **publicada** por cada país (grado A en 9 de los 11 países de la región).
  No se recalcula desde el índice: los índices tienen bases distintas y, en algunos países,
  redondeos que distorsionan la variación (COL antes de 1980).
- PER en ``paises`` es el IPC de **Lima Metropolitana** (índice de la meta del BCRP) y PRY el del
  **Área Metropolitana de Asunción** (índice de la meta del BCP): grado C, se comparan con cautela
  con IPC nacionales. El IPC nacional del Perú va aparte, en ``nacional``.
- CHL publica la 12m empalmada base 2023 solo desde 2011-01. Antes se compone desde la variación
  mensual del BCCh (cálculo propio, recomendado en la revisión de comparabilidad). Por el redondeo
  de la mensual a 1 decimal, frente a la publicada en 2011-2026 difiere en promedio 0,09 pp
  (máx. 0,29 pp). Antes de 2010 la mensual mezcla bases antiguas sin empalmar.
- ARG (desde 2017-12, IPC nacional del INDEC) tiene inflación muy alta (cientos de %): queda
  marcada en ``nota`` y en ``HIGH_INFLATION_COUNTRIES``; conviene excluirla de gráficos de escala
  común. No se usa nada del período intervenido 2007-2015.
- PAN solo tiene datos desde 2024-01 y mezcla bases (2024 con base 2013, desde 2025 base 2024).
- ECU va un mes detrás de los demás (BCEData).
- Por defecto se devuelve desde 2000-01 para dejar fuera las hiperinflaciones (PER 1988-91,
  BOL 1982-87, BRA antes del Plan Real). ``start=None`` devuelve toda la historia; las marcas de
  régimen de la capa comparable quedan en ``nota``.

Uso::

    from inflacion_comparada import load_inflacion_comparada
    data = load_inflacion_comparada()
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

# --- Rutas (relativas a este archivo; no se lee nada al importar) ------------------------------
SRC_DIR = Path(__file__).resolve().parent
MACRO_DIR = SRC_DIR.parents[1] / "data_macro_paises"
COMPARABLE_OBS = MACRO_DIR / "data" / "processed" / "comparable" / "comparable_observaciones"
MACRO_OBS = MACRO_DIR / "data" / "processed" / "macro_observaciones"
METAS_CSV = MACRO_DIR / "config" / "comparable" / "metas_inflacion.csv"
INEI_XLSX = MACRO_DIR / "data" / "raw" / "PER" / "inei" / "n02_ipc_nacional.xlsx"
INEI_SHEET = "Base Dic.2021"

# --- Países ------------------------------------------------------------------------------------
COUNTRY_NAMES = {
    "PER": "Perú",
    "ARG": "Argentina",
    "BOL": "Bolivia",
    "BRA": "Brasil",
    "CHL": "Chile",
    "COL": "Colombia",
    "ECU": "Ecuador",
    "MEX": "México",
    "PAN": "Panamá",
    "PRY": "Paraguay",
    "URY": "Uruguay",
    "USA": "Estados Unidos",
    "ESP": "España",
}

# Región por defecto (América Latina). USA y ESP se pueden pedir con `countries=`.
DEFAULT_COUNTRIES = ["PER", "CHL", "COL", "BRA", "MEX", "BOL", "PRY", "URY", "ECU", "PAN", "ARG"]

SOURCES = {
    "PER": "INEI, IPC Lima Metropolitana (vía BCRP)",
    "ARG": "INDEC",
    "BOL": "INE Bolivia",
    "BRA": "IBGE (IPCA)",
    "CHL": "INE Chile (vía BCCh)",
    "COL": "DANE (vía BanRep)",
    "ECU": "INEC Ecuador (vía BCE)",
    "MEX": "INEGI (INPC, vía Banxico)",
    "PAN": "INEC Panamá",
    "PRY": "BCP, IPC Área Metropolitana de Asunción",
    "URY": "INE Uruguay",
    "USA": "BLS (CPI-U)",
    "ESP": "INE España",
}
SOURCE_NATIONAL = "INEI, IPC nacional (base dic-2021)"

COVERAGE = {
    "PER": "capital (Lima Metropolitana)",
    "PRY": "capital (Área Metropolitana de Asunción)",
    "BRA": "nacional urbano (16 áreas)",
    "USA": "urbano (~93 % de la población)",
}  # el resto: "nacional"

# Advertencias fijas por país (se copian a la columna `nota`).
COUNTRY_NOTES = {
    "PER": "IPC de Lima Metropolitana (índice de la meta del BCRP), no nacional",
    "PRY": "IPC de la capital (índice de la meta del BCP), comparar con cautela",
    "ARG": "inflación muy alta: excluir de gráficos de escala común",
    "PAN": "serie corta desde 2024; 2024 con base 2013 y desde 2025 base 2024",
    "ECU": "va un mes detrás de los demás países",
    "USA": "la Fed apunta al PCE, no al CPI",
    "ESP": "IPC de España; el BCE apunta al IAPC de la zona euro",
}
HIGH_INFLATION_COUNTRIES = {"ARG"}

# Inicio de la 12m publicada de Chile (base 2023); antes se compone desde la mensual.
CHL_PUBLISHED_START = pd.Timestamp("2011-01-01")

DEFAULT_START = "2000-01-01"

MONTHS_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
    "agosto": 8, "setiembre": 9, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}

METAS_COLUMNS = [
    "pais", "desde", "hasta", "tipo", "meta_centro", "rango_inferior", "rango_superior", "horizonte",
]


# --- Lectura -----------------------------------------------------------------------------------
def _read_table(stem: Path) -> pd.DataFrame:
    """Lee `<stem>.parquet`; si no se puede (falta pyarrow o el archivo), `<stem>.csv`."""
    parquet = stem.with_suffix(".parquet")
    if parquet.exists():
        try:
            return pd.read_parquet(parquet)
        except Exception:  # noqa: BLE001 - motor de parquet ausente: se usa el CSV
            pass
    df = pd.read_csv(stem.with_suffix(".csv"), encoding="utf-8-sig")
    df["fecha"] = pd.to_datetime(df["fecha"])
    return df


def _month_start(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s).dt.to_period("M").dt.to_timestamp()


def _var12m_from_monthly(monthly: pd.Series) -> pd.Series:
    """Compone la variación 12m (%) desde 12 variaciones mensuales (%) consecutivas."""
    monthly = monthly.asfreq("MS")
    log_growth = np.log1p(monthly / 100.0)
    out = np.expm1(log_growth.rolling(12, min_periods=12).sum()) * 100.0
    return out


# --- IPC nacional del Perú --------------------------------------------------------------------
def _national_from_processed() -> pd.DataFrame | None:
    obs = _read_table(MACRO_OBS)
    per = obs[(obs["pais"] == "PER") & obs["nombre_corto"].isin(
        ["ipc_nacional_indice", "inflacion_nacional_12m"])]
    if per.empty or "ipc_nacional_indice" not in set(per["nombre_corto"]):
        return None
    wide = (per.assign(fecha=_month_start(per["fecha"]))
               .pivot_table(index="fecha", columns="nombre_corto", values="valor", aggfunc="last"))
    return pd.DataFrame({
        "ipc_nacional_indice": wide["ipc_nacional_indice"],
        "var12m_publicada": wide.get("inflacion_nacional_12m"),
    })


def _national_from_excel() -> pd.DataFrame:
    """Respaldo: parsea la hoja 'Base Dic.2021' del Excel del INEI (año solo en la 1.ª fila)."""
    raw = pd.read_excel(INEI_XLSX, sheet_name=INEI_SHEET, header=None)
    header_row = raw.index[raw.iloc[:, 0].astype(str).str.strip().eq("Año")][0]
    df = raw.iloc[header_row + 1:, :6].copy()
    df.columns = ["anio", "mes", "indice", "mensual", "acumulada", "anual"]
    df["anio"] = pd.to_numeric(df["anio"], errors="coerce").ffill()
    df["mes_num"] = df["mes"].astype(str).str.strip().str.lower().map(MONTHS_ES)
    df = df.dropna(subset=["anio", "mes_num"])
    fecha = pd.to_datetime(dict(year=df["anio"].astype(int), month=df["mes_num"].astype(int), day=1))
    return pd.DataFrame({
        "ipc_nacional_indice": pd.to_numeric(df["indice"], errors="coerce").to_numpy(),
        "var12m_publicada": pd.to_numeric(df["anual"], errors="coerce").to_numpy(),  # '-' -> NaN
    }, index=pd.DatetimeIndex(fecha, name="fecha"))


def _load_national() -> pd.DataFrame:
    wide = _national_from_processed()
    if wide is None:
        wide = _national_from_excel()
    wide = wide.sort_index().asfreq("MS")
    idx = wide["ipc_nacional_indice"]
    var12m_calc = (idx / idx.shift(12) - 1.0) * 100.0
    out = pd.DataFrame({
        "fecha": wide.index,
        "ipc_nacional_indice": idx.to_numpy(),
        # La mensual no está procesada: se calcula desde el índice (4 decimales).
        "ipc_nacional_var_mensual": ((idx / idx.shift(1) - 1.0) * 100.0).to_numpy(),
        # 12m publicada por el INEI; donde falte, la calculada desde el índice.
        "ipc_nacional_var12m": wide["var12m_publicada"].fillna(var12m_calc).to_numpy(),
    })
    return out.dropna(subset=["ipc_nacional_indice"]).reset_index(drop=True)


# --- Inflación 12m por país -------------------------------------------------------------------
def _load_countries(countries: list[str], start: str | None) -> pd.DataFrame:
    obs = _read_table(COMPARABLE_OBS)
    obs = obs[obs["indicador"].isin(["inflacion_12m", "inflacion_mensual"])
              & obs["pais"].isin(countries)].copy()
    obs["fecha"] = _month_start(obs["fecha"])
    obs["regimen"] = obs["regimen"].fillna("").astype(str)

    y12 = obs[obs["indicador"] == "inflacion_12m"][["pais", "fecha", "valor", "regimen"]]
    y12 = y12.rename(columns={"valor": "inflacion_12m"}).assign(metodo="")

    if "CHL" in countries:
        # Chile: 12m compuesta desde la mensual antes de la serie publicada base 2023.
        m = obs[(obs["pais"] == "CHL") & (obs["indicador"] == "inflacion_mensual")]
        m = m.set_index("fecha").sort_index()
        comp = _var12m_from_monthly(m["valor"]).dropna()
        comp = comp[comp.index < CHL_PUBLISHED_START]
        if not comp.empty:
            reg = m["regimen"].reindex(comp.index).fillna("")
            back = pd.DataFrame({"pais": "CHL", "fecha": comp.index, "inflacion_12m": comp.to_numpy(),
                                 "regimen": reg.to_numpy(),
                                 "metodo": "12m compuesta desde la variación mensual (cálculo propio)"})
            y12 = pd.concat([back, y12], ignore_index=True)

    if start is not None:
        y12 = y12[y12["fecha"] >= pd.Timestamp(start)]

    def build_note(row) -> str:
        parts = [COUNTRY_NOTES.get(row["pais"], ""), row["metodo"]]
        parts += [r for r in row["regimen"].split(";") if r and r != "covid"]
        return "; ".join(p for p in parts if p)

    y12 = y12.dropna(subset=["inflacion_12m"]).copy()
    y12["nota"] = y12.apply(build_note, axis=1) if len(y12) else ""
    y12["pais_nombre"] = y12["pais"].map(COUNTRY_NAMES)
    y12["cobertura"] = y12["pais"].map(COVERAGE).fillna("nacional")
    cols = ["fecha", "pais", "pais_nombre", "inflacion_12m", "cobertura", "nota"]
    return y12[cols].sort_values(["pais", "fecha"]).reset_index(drop=True)


# --- Metas -------------------------------------------------------------------------------------
def _load_targets() -> pd.DataFrame:
    metas = pd.read_csv(METAS_CSV, encoding="utf-8-sig")
    for col in ("desde", "hasta"):
        metas[col] = pd.to_datetime(metas[col], errors="coerce")  # vacío -> NaT (vigente)
    extra = [c for c in metas.columns if c not in METAS_COLUMNS]
    return metas[METAS_COLUMNS + extra].sort_values(["pais", "desde"]).reset_index(drop=True)


# --- API ---------------------------------------------------------------------------------------
def load_inflacion_comparada(countries: list[str] | None = None,
                             start: str | None = DEFAULT_START) -> dict:
    """Carga los datos de comparación de inflación.

    Parámetros
    ----------
    countries : ISO3 a incluir en ``paises`` (por defecto ``DEFAULT_COUNTRIES``, América Latina
        con PER). Se pueden añadir "USA" y "ESP".
    start : primera fecha de ``paises`` (por defecto 2000-01). ``None`` = toda la historia.
        No afecta a ``nacional`` (desde 2012-01) ni a ``metas``.

    Devuelve
    --------
    dict con:
      - "nacional": DataFrame[fecha, ipc_nacional_indice, ipc_nacional_var_mensual,
        ipc_nacional_var12m]
      - "paises": DataFrame[fecha, pais, pais_nombre, inflacion_12m, cobertura, nota]
      - "metas": DataFrame[pais, desde, hasta, tipo, meta_centro, rango_inferior,
        rango_superior, horizonte, + columnas originales restantes]
      - "fuentes": dict pais -> fuente corta
    """
    countries = list(countries) if countries is not None else list(DEFAULT_COUNTRIES)
    paises = _load_countries(countries, start)
    return {
        "nacional": _load_national(),
        "paises": paises,
        "metas": _load_targets(),
        "fuentes": {p: SOURCES[p] for p in countries if p in SOURCES},
    }


if __name__ == "__main__":
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    data = load_inflacion_comparada()
    nac = data["nacional"]
    last = nac.iloc[-1]
    print("== IPC nacional (INEI) ==")
    print(f"  {nac['fecha'].min():%Y-%m} a {nac['fecha'].max():%Y-%m} ({len(nac)} meses); "
          f"último {last['fecha']:%Y-%m}: índice {last['ipc_nacional_indice']:.4f}, "
          f"mensual {last['ipc_nacional_var_mensual']:.2f} %, 12m {last['ipc_nacional_var12m']:.2f} %")

    pa = data["paises"]
    print("\n== Inflación 12m por país ==")
    summary = (pa.sort_values("fecha").groupby(["pais", "pais_nombre"])
                 .agg(desde=("fecha", "min"), hasta=("fecha", "max"), n=("fecha", "size"),
                      ultimo=("inflacion_12m", "last")).reset_index())
    for _, r in summary.iterrows():
        print(f"  {r['pais']} {r['pais_nombre']:<10} {r['desde']:%Y-%m} a {r['hasta']:%Y-%m} "
              f"({r['n']:>3})  último {r['ultimo']:7.2f} %  | {data['fuentes'][r['pais']]}")
    dups = pa.duplicated(["fecha", "pais"]).sum()
    print(f"  Duplicados fecha×país: {dups}")

    me = data["metas"]
    vig = me[me["hasta"].isna()]
    print(f"\n== Metas == {len(me)} tramos, {me['pais'].nunique()} países; vigentes:")
    for _, r in vig.iterrows():
        print(f"  {r['pais']}: {r['tipo']} centro={r['meta_centro']} "
              f"[{r['rango_inferior']}, {r['rango_superior']}] desde {r['desde']:%Y-%m-%d}")
