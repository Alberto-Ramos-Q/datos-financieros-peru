"""Descargador de series macro de Chile (Banco Central de Chile, Base de Datos Estadísticos).

Fuente única: la BDE del BCCh (https://si3.bcentral.cl/siete), que además publica
las series que originan el INE (IPC, desempleo) y DIPRES (balance y deuda del
Gobierno Central). La API SieteRestWS exige usuario y clave; aquí se usa la
exportación a Excel de cada cuadro, que es pública y no requiere login:

1. GET del cuadro → cookie de sesión + token CSRF (`__RequestVerificationToken`)
   y la lista de series del cuadro (atributos `data-*` de cada checkbox).
2. POST a `/Siete/ES/Siete/DownloadExcel` con las series elegidas e
   `IsFullSeries=true` (todos los años) → .xlsx con hojas Cuadro / Metadatos / Series.

Uso:
    python chl.py                         # descarga y procesa todas las series activas
    python chl.py --solo-procesar         # solo reconstruye el parquet desde data/raw/CHL
    python chl.py --serie tasa_politica uf --pausa 2

Convenciones de `config/series/CHL.csv`:
- `codigo_fuente` es el código de la serie en la BDE. Si termina en `@YTYPCT`, se
  descarga con el cálculo "variación mismo período año anterior" de la propia BDE.
  Si termina en `|var12m`, se descarga el índice tal cual y la variación % en 12 meses
  se calcula aquí (para cuadros que no ofrecen YTYPCT).
- El cuadro desde el que se exporta cada código está en `SOURCES` (más abajo):
  la exportación solo funciona dentro del cuadro al que pertenece la serie.
"""
from __future__ import annotations

import argparse
import html
import io
import json
import logging
import re
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import comun  # noqa: E402

ISO3 = "CHL"
FUENTE = "bcch_bde"
BDE_CUADRO_URL = "https://si3.bcentral.cl/Siete/ES/Siete/Cuadro/"
BDE_EXPORT_URL = "https://si3.bcentral.cl/Siete/ES/Siete/DownloadExcel"

log = logging.getLogger("data_macro_paises")

# Cuadro de la BDE desde el que se exporta cada serie y frecuencia de exportación.
# Frecuencias BDE: DAILY | MONTHLY | QUARTERLY | ANNUAL. Si la frecuencia de
# exportación es más baja que la nativa, la BDE agrega según el atributo
# "observed" de la serie (END = fin de periodo, AVERAGED = promedio).
SOURCES: dict[str, tuple[str, str]] = {
    # Cuentas nacionales (referencia 2018)
    "F032.PIB.FLU.R.CLP.EP18.Z.Z.0.T": ("CAP_CCNN/MN_CCNN76/CCNN2018_P0_V2/637801082315858005", "QUARTERLY"),
    "F032.PIB.FLU.R.CLP.EP18.Z.Z.1.T": ("CAP_CCNN/MN_CCNN76/CCNN2018_P0_V2/637801082315858005", "QUARTERLY"),
    "F032.PIB.FLU.N.CLP.HIST18.Z.Z.0.A": ("CAP_EST_HIST/MN_EST_HIST/CCNN_HIST18_CORR/638889683495559776", "ANNUAL"),
    "F032.IMC.IND.Z.Z.EP18.Z.Z.0.M": ("CAP_CCNN/MN_CCNN76/CCNN2018_IMACEC_01_A/638131830306828693", "MONTHLY"),
    "F032.IMC.IND.Z.Z.EP18.N03.Z.0.M": ("CAP_CCNN/MN_CCNN76/CCNN2018_IMACEC_01_A/638131830306828693", "MONTHLY"),
    "F032.IMC.IND.Z.Z.EP18.Z.Z.1.M": ("CAP_ESTADIST_MACRO/MN_EST_MACRO_IV/PEM_ACTyDDA_IMACEC_2_2018/637807927445790326", "MONTHLY"),
    # Precios (originador: INE; empalmes del BCCh)
    "F074.IPC.IND.Z.EP23.C.M": ("CAP_PRECIOS/MN_CAP_PRECIOS/IPC_EMP_2023/638415285164039007", "MONTHLY"),
    "F074.IPC.VAR.Z.Z.C.M": ("CAP_PRECIOS/MN_CAP_PRECIOS/IPC_VAR_MEN1_HIST_NEW/637775996212899984", "MONTHLY"),
    "F074.IPC.IND.Z.EP09.C.M": ("CAP_PRECIOS/MN_CAP_PRECIOS/IPC_VAR_ANUAL_HIST_NEW/637776000242408435", "MONTHLY"),
    "F074.IPC.V12.Z.EP23.C.M": ("CAP_PRECIOS/MN_CAP_PRECIOS/IPC_VAREMP_2023/638415285606842418", "MONTHLY"),
    "G073.IPCSV.V12.2023.M": ("CAP_PRECIOS/MN_CAP_PRECIOS/PEM_VAR12_IPC_2023/638447991540869284", "MONTHLY"),
    "G073.IPCSV.IND.2023.M": ("CAP_PRECIOS/MN_CAP_PRECIOS/PEM_IND_IPC_2023/638447991790421422", "MONTHLY"),
    # IPC analíticos del INE, índices empalmados base 2023 (solo cálculo NONE).
    "F074.IPCSAE.IND.Z.EP23.Z.M": ("CAP_PRECIOS/MN_CAP_PRECIOS/IPC_ANA_INE_2023/638614947286134835", "MONTHLY"),
    "F073.UFF.PRE.Z.D": ("CAP_PRECIOS/MN_CAP_PRECIOS/UF_IVP_DIARIO/UF_IVP_DIARIO", "DAILY"),
    # Tasas de interés
    "F022.TPM.TIN.D001.NO.Z.D": ("CAP_TASA_INTERES/MN_TASA_INTERES_09/TPM_C1/T12", "DAILY"),
    "F022.TIB.TIP.D001.NO.Z.M": ("CAP_TASA_INTERES/MN_TASA_INTERES_09/TSF_23/T51", "MONTHLY"),
    "F022.CAP.TIN.Z.NO.Z.M": ("CAP_TASA_INTERES/MN_TASA_INTERES_09/TSF_31/T5241", "MONTHLY"),
    "F022.CAP.TIN.D089.NO.Z.M": ("CAP_TASA_INTERES/MN_TASA_INTERES_09/TSF_34/T531", "MONTHLY"),
    "F022.BCLP.TIS.AN10.NO.Z.M": ("CAP_EI/MN_EI11/EI_BONOS_GOB2/637189407352745812", "MONTHLY"),
    # Dinero y crédito
    "F021.M2.STO.N.CLP.5.M": ("CAP_DYB/MN_ESTAD_MON55/EM_NOMINALES_02_act/638653867988640983", "MONTHLY"),
    "F022.CPP.STO.Z.Z.Z.M": ("CAP_DYB/MN_ESTAD_MON55/EM_COL_SP/E25", "MONTHLY"),
    "F022.CONBI.STO.Z.Z.CLP.M": ("CAP_DYB/MN_ESTAD_MON55/EM_CDEU_BI/E21", "MONTHLY"),
    # Expectativas (Encuesta de Expectativas Económicas, BCCh)
    "F089.IPC.V12.14.M": ("CAP_EXP_ECO/MN_EXP_EC11/EXE_BCCH_01/EXE_BCCH_01", "MONTHLY"),
    "F089.TPM.TAS.14.M": ("CAP_EXP_ECO/MN_EXP_EC11/EXE_BCCH_02/EXE_BCCH_02", "MONTHLY"),
    # Sector externo
    "F073.TCO.PRE.Z.D": ("CAP_TIPO_CAMBIO/MN_TIPO_CAMBIO4/DOLAR_OBS_ADO/DOLAR_OBS_ADO", "DAILY"),
    "F073.TCR.IND.199101.M": ("CAP_ESTADIST_MACRO/MN_EST_MACRO_IV/PEM_TC/PEM_TC", "MONTHLY"),
    "F062.A5.STO.PF.USD.M": ("CAP_BDP/MN_BDP42/BP_RESERVAS/BP_RESERVAS", "MONTHLY"),
    "F068.B1.FLU.Z.0.C.N.Z.Z.Z.Z.6.0.M": ("CAP_ESTADIST_MACRO/MN_EST_MACRO_IV/PEM_BP_IndCoy_2/PEM_BP_IndCoy_2", "MONTHLY"),
    "F068.B1.FLU.Z.0.D.N.0.T.Z.Z.6.0.M": ("CAP_ESTADIST_MACRO/MN_EST_MACRO_IV/PEM_BP_IndCoy_2/PEM_BP_IndCoy_2", "MONTHLY"),
    "F068.B1.VAR.T0.0.S.N.Z.Z.Z.Z.6.0.M": ("CAP_BDP/MN_BDP42/BP6M_BAL_COM/BP6M_BAL_COM", "MONTHLY"),
    "F068.A.FLU.Z.0.S.N.Z.Z.Z.Z.6.0.T": ("CAP_BDP/MN_BDP42/BP6M_CCRTC/BP6M_CCRTC", "QUARTERLY"),
    "F019.PPB.PRE.40.M": ("CAP_ESTADIST_MACRO/MN_EST_MACRO_IV/PEM_ECIN_Precios/PEM_ECIN_Precios", "MONTHLY"),
    # Fiscal (originador: DIPRES / Ministerio de Hacienda)
    "F051.G21.PPI.C.Z.Z.A": ("CAP_FIN_PUB/MN_FIN_PUB_1/GOB_TOT_4/gob_central_5", "ANNUAL"),
    "F051.G11.PPB.C.Z.CLP.A": ("CAP_FIN_PUB/MN_FIN_PUB_1/GOB_TOT_4/gob_central_5", "ANNUAL"),
    "F051.D7.PPB.C.Z.Z.T": ("CAP_FIN_PUB/MN_FIN_PUB_1/PEM_FP_DP/637363861322851639", "ANNUAL"),
    "F051.D9.PPB.C.Z.Z.T": ("CAP_FIN_PUB/MN_FIN_PUB_1/PEM_FP_DP/637363861322851639", "ANNUAL"),
    # Mercado laboral (originador: INE, Encuesta Nacional de Empleo)
    "F049.DES.TAS.INE9.10.M": ("CAP_EMP_REM_DEM/MN_EMP_REM_DEM13/ED_TDNRM2/a4", "MONTHLY"),
}

# Conversión a la unidad del indicador común (la BDE publica PIB y agregados en
# miles de millones de pesos; el esquema común usa millones).
FACTOR = {
    "F032.PIB.FLU.R.CLP.EP18.Z.Z.0.T": 1000,
    "F032.PIB.FLU.R.CLP.EP18.Z.Z.1.T": 1000,
    "F032.PIB.FLU.N.CLP.HIST18.Z.Z.0.A": 1000,
    "F021.M2.STO.N.CLP.5.M": 1000,
    "F022.CPP.STO.Z.Z.Z.M": 1000,
    "F022.CONBI.STO.Z.Z.CLP.M": 1000,
}

# Series diarias que se guardan como mensuales: cómo se agrega el mes.
# (codigo_fuente, frecuencia de config) → "last" (fin de periodo) | "mean" (promedio)
DAILY_TO_MONTHLY = {
    ("F022.TPM.TIN.D001.NO.Z.D", "mensual"): "last",
    ("F073.TCO.PRE.Z.D", "mensual"): "mean",
}

BDE_FREQ = {"DAILY": "diaria", "MONTHLY": "mensual", "QUARTERLY": "trimestral", "ANNUAL": "anual"}


def split_code(codigo: str) -> tuple[str, str]:
    """'F032...0.M@YTYPCT' → ('F032...0.M', 'YTYPCT'); sin sufijo, cálculo NONE.
    El sufijo local '|var12m' no cambia la descarga."""
    code, _, calc = codigo.split("|")[0].partition("@")
    return code, calc or "NONE"


def pct_change_12m(values: pd.Series) -> pd.Series:
    """Variación % respecto al mismo mes del año anterior (exige ese mes exacto)."""
    per = values.index.to_period("M")
    base = pd.Series(values.values, index=per).reindex(per - 12).values
    return (100 * (values / base - 1)).dropna()


def raw_name(cuadro: str, freq: str, calc: str) -> str:
    cuadro_id = cuadro.split("/")[2]
    return f"{cuadro_id}__{freq}__{calc}.xlsx"


# ---------------------------------------------------------------------------
# Descarga
# ---------------------------------------------------------------------------

def plan_downloads(series: list[dict]) -> dict[tuple[str, str, str], set[str]]:
    """Agrupa las series por (cuadro, frecuencia, cálculo): una exportación por grupo."""
    groups: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for s in series:
        code, calc = split_code(s["codigo_fuente"])
        if code not in SOURCES:
            log.error("%s: el código %s no tiene cuadro en SOURCES; se omite", s["nombre_corto"], code)
            continue
        cuadro, freq = SOURCES[code]
        groups[(cuadro, freq, calc)].add(code)
    return groups


def export_cuadro(client: comun.Client, cuadro: str, freq: str, calc: str,
                  codes: set[str]) -> tuple[bytes, str]:
    """Exporta a Excel la historia completa de `codes` desde el cuadro de la BDE."""
    url = f"{BDE_CUADRO_URL}{cuadro}?cbFrecuencia={freq}&cbCalculo={calc}"
    page = client.get(url).text
    m = re.search(r'id="frmExportExcel".*?name="__RequestVerificationToken" type="hidden" value="([^"]+)"',
                  page, re.S)
    if not m:
        raise RuntimeError(f"{cuadro}: no se encontró el formulario de exportación")
    token = m.group(1)
    freqs = re.findall(r'<option value="([A-Z]+)"', page.split('id="cbFrecuencia"')[1].split("</select>")[0])
    if freq not in freqs:
        raise RuntimeError(f"{cuadro}: la frecuencia {freq} no está disponible ({freqs})")
    # Trampa: aun con IsFullSeries=true, la exportación respeta el rango de años del
    # cuadro, que por defecto empieza en 2010 o 2013. Se piden explícitamente el
    # primer y el último año que ofrece el cuadro (p. ej. el IPC histórico, 1928).
    years = re.findall(r'<option value="(\d{4})"',
                       page.split('id="cbFechaInicio"')[1].split("</select>")[0]) \
        if 'id="cbFechaInicio"' in page else []
    first_year, last_year = (min(years), max(years)) if years else ("", "")
    cuadro_id = cuadro.split("/")[2]
    items, found = [], set()
    for chk in re.finditer(r'<input type="checkbox" class="chkGrid"(.*?)/>', page, re.S):
        a = dict(re.findall(r'data-([a-z]+)="([^"]*)"', chk.group(1)))
        if a.get("serie") in codes and a["serie"] not in found:
            found.add(a["serie"])
            items.append({"serie_id": a["serie"], "header_id": a.get("header", a["serie"]),
                          "name": html.unescape(a.get("name", "")), "nameEng": a.get("nameeng", ""),
                          "calculo": calc, "key": a.get("key", ""), "observed": a.get("observed", ""),
                          "frecuencia": a.get("frecuencia", ""), "decimales": a.get("decimales", "2"),
                          "index": int(a.get("index", 0) or 0)})
    missing = codes - found
    if missing:
        raise RuntimeError(f"{cuadro}: el cuadro ya no contiene {sorted(missing)}")
    data = {"__RequestVerificationToken": token, "IsVertical": "true", "IsFullSeries": "true",
            "codCuadro": cuadro_id, "Series": json.dumps(items), "frecuencia": freq,
            "calculo": calc, "fechaInicio": first_year, "fechaDiaria": "", "fechaTermino": last_year,
            "SoloSeries": "N"}
    r = client.post(BDE_EXPORT_URL, data=data, timeout=300)
    if "spreadsheetml" not in r.headers.get("content-type", ""):
        raise RuntimeError(f"{cuadro}: la exportación no devolvió un Excel ({r.text[:150]!r})")
    return r.content, url


def same_xlsx_data(path: Path, content: bytes) -> bool:
    """El .xlsx de la BDE cambia de bytes en cada exportación (marca de tiempo interna):
    se compara el contenido de las hojas para no versionar archivos idénticos."""
    if not path.exists():
        return False
    try:
        old = pd.read_excel(path, sheet_name=None, header=None)
        new = pd.read_excel(io.BytesIO(content), sheet_name=None, header=None)
    except Exception:  # noqa: BLE001 — si no se puede leer, se guarda la nueva versión
        return False
    return old.keys() == new.keys() and all(old[k].equals(new[k]) for k in old)


def download(series: list[dict], pause: float) -> int:
    client = comun.Client(pause=pause)
    errors = 0
    for (cuadro, freq, calc), codes in plan_downloads(series).items():
        name = raw_name(cuadro, freq, calc)
        try:
            content, url = export_cuadro(client, cuadro, freq, calc, codes)
        except Exception as e:  # noqa: BLE001
            log.error("%s: %s", name, e)
            errors += 1
            continue
        if same_xlsx_data(comun.raw_path(ISO3, FUENTE, name), content):
            action = "sin_cambios"
        else:
            action = comun.save_raw(ISO3, FUENTE, name, content, url)
        log.info("%-48s %d serie(s)  [%s]", name, len(codes), action)
    return errors


# ---------------------------------------------------------------------------
# Procesamiento (solo lee data/raw/CHL)
# ---------------------------------------------------------------------------

def read_export(path: Path) -> pd.DataFrame:
    """Excel de la BDE → DataFrame (index fecha, columnas = códigos de serie)."""
    book = pd.read_excel(path, sheet_name=None, header=None)
    codes = [str(c).strip() for c in book["Series"].iloc[1:, 0].dropna()]
    cuadro = book["Cuadro"]
    header_row = cuadro.index[cuadro.iloc[:, 0].astype(str).str.strip() == "Periodo"][0]
    data = cuadro.iloc[header_row + 1:, : len(codes) + 1].copy()
    data.columns = ["fecha"] + codes
    data = data[data["fecha"].notna()]
    data["fecha"] = pd.to_datetime(data["fecha"], errors="raise")
    return data.set_index("fecha")


def build_series(s: dict) -> pd.DataFrame:
    code, calc = split_code(s["codigo_fuente"])
    cuadro, freq = SOURCES[code]
    path = comun.raw_path(ISO3, FUENTE, raw_name(cuadro, freq, calc))
    if not path.exists():
        raise FileNotFoundError(f"falta el archivo crudo {path.name}")
    raw = read_export(path)[code]
    values = pd.to_numeric(raw, errors="coerce")
    bad = raw.notna() & values.isna()
    if bad.any():
        log.warning("%s: %d valores no numéricos descartados (p. ej. %r)",
                    s["nombre_corto"], bad.sum(), raw[bad].iloc[0])
    # El factor de unidad solo aplica a niveles, no a variaciones % calculadas por la BDE.
    values = values.dropna() * (FACTOR.get(code, 1) if calc == "NONE" else 1)
    if s["codigo_fuente"].endswith("|var12m"):
        values = pct_change_12m(values)

    freq_cfg = s["frecuencia"]
    agg = DAILY_TO_MONTHLY.get((code, freq_cfg))
    if agg:
        # El mes en curso está incompleto: su promedio o "fin de mes" no es el dato del mes.
        current = pd.Timestamp.today().to_period("M")
        values = values[values.index.to_period("M") < current]
        values = values.groupby(values.index.to_period("M")).agg(agg)
        values.index = values.index.to_timestamp()
    elif BDE_FREQ[freq] != freq_cfg:
        raise ValueError(f"{s['nombre_corto']}: frecuencia BDE {freq} ≠ config {freq_cfg}")

    df = pd.DataFrame({"pais": ISO3,
                       "fecha": comun.period_start(pd.Series(values.index), freq_cfg).values,
                       "valor": values.values})
    for col in ("fuente", "codigo_fuente", "nombre_corto", "indicador_comun", "frecuencia", "unidad"):
        df[col] = s[col]
    return df


def process(series: list[dict]) -> int:
    frames, errors = [], 0
    for s in series:
        try:
            frames.append(build_series(s))
        except Exception as e:  # noqa: BLE001
            log.error("%s: %s", s["nombre_corto"], e)
            errors += 1
    if not frames:
        log.error("No hay series para procesar")
        return errors + 1
    comun.write_interim(ISO3, pd.concat(frames, ignore_index=True))
    return errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--solo-procesar", action="store_true", help="no descarga; solo procesa data/raw/CHL")
    ap.add_argument("--serie", nargs="+", help="nombre_corto a descargar (el parquet se rehace con todas)")
    ap.add_argument("--pausa", type=float, default=1.0, help="segundos entre peticiones (mín. 1)")
    args = ap.parse_args(argv)
    # La consola de Windows usa cp1252 y comun.py loguea "→": sin esto, logging falla.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    comun.setup_logging(ISO3)

    series = comun.load_series(ISO3)
    errors = 0
    if not args.solo_procesar:
        target = series
        if args.serie:
            target = [s for s in series if s["nombre_corto"] in set(args.serie)]
            unknown = set(args.serie) - {s["nombre_corto"] for s in target}
            if unknown:
                log.warning("No están activas en config/series/CHL.csv: %s", ", ".join(sorted(unknown)))
        log.info("Descargando %d serie(s) de la BDE del Banco Central de Chile", len(target))
        errors += download(target, max(args.pausa, 1.0))
    errors += process(series)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
