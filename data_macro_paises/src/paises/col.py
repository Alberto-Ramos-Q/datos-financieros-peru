"""Colombia: series del Banco de la República (BanRep) y del DANE.

Fuentes (todas oficiales y sin clave):
- `banrep_suameca`: servicio REST que alimenta el portal SUAMECA de estadísticas del
  BanRep. `consultaInformacionSerie?idSerie=N` devuelve la historia completa de la
  serie en JSON (fechas en milisegundos epoch, medianoche de Bogotá = 05:00 UTC).
  Incluye series que el BanRep republica de DANE, MinHacienda y Superfinanciera.
- `banrep_sdmx`: servicio SDMX oficial del BanRep (tasa interbancaria promedio mensual).
- `banrep_eme`: Excel de series históricas de la Encuesta mensual de expectativas.
- `dane`: anexos Excel del DANE (ISE y balanza comercial mensual). El nombre del
  archivo cambia cada mes, así que se busca el enlace vigente en la página del DANE.

`codigo_fuente` de SUAMECA: `ID` o `ID+ID` (suma), seguido de transformaciones
separadas por `|`:
    tipoDato=K              variación calculada por SUAMECA (11 = % mensual)
    promedio_mensual        diaria -> promedio simple del mes (descarta el mes en curso)
    fin_de_mes              diaria -> último dato del mes (descarta el mes en curso)
    anual_a_mensual         valor anual vigente todo el año -> un dato por mes
    suma_anual_pct_pib:ID   suma anual de una mensual / PIB anual (id) x 100
    div_fin_de_mes:ID       divide cada mes por el último dato diario del mes de la serie ID
                            (p. ej. COP -> USD con la TRM vigente el último día del mes)
    xF                      multiplica por F (p. ej. x1000: miles de millones -> millones)

Uso:
    python col.py                      # descargar + procesar
    python col.py --solo-procesar      # solo rehacer data/interim desde data/raw
    python col.py --serie ipc_indice tasa_politica
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import ssl
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import certifi
import pandas as pd
from requests.adapters import HTTPAdapter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import comun  # noqa: E402

ISO3 = "COL"
SUAMECA_URL = ("https://suameca.banrep.gov.co/estadisticas-economicas-back/rest/"
               "estadisticaEconomicaRestService")
SDMX_URL = "https://totoro.banrep.gov.co/nsi-jax-ws/rest/data/ESTAT,{flow},1.0/all/ALL/"
EME_URL = ("https://suameca.banrep.gov.co/archivos/encuestas/"
           "encuesta_mensual_analistas_economicos/series_historicas.xlsx")
DANE_BASE = "https://www.dane.gov.co"
# Archivo estable en data/raw -> (página del DANE, patrón del enlace vigente).
DANE_FILES = {
    "anex-ISE-9actividades.xlsx": (
        "/index.php/estadisticas-por-tema/cuentas-nacionales/indicador-de-seguimiento-a-la-economia-ise",
        r"/files/operaciones/ISE/anex-ISE-9actividades-[a-z]+\d{4}\.xlsx"),
    "anex-BCOM-Mensual.xlsx": (
        "/index.php/estadisticas-por-tema/comercio-internacional/balanza-comercial",
        r"/files/operaciones/BCOM/anex-BCOM-Mensual-[a-z]+\d{4}\.xlsx"),
    # Anexo general del IPC (no el de índices ni el de variaciones): solo se enlaza
    # desde la página de información técnica del IPC.
    "anex-IPC.xlsx": (
        "/index.php/estadisticas-por-tema/precios-y-costos/indice-de-precios-al-consumidor-ipc/"
        "ipc-informacion-tecnica",
        r"/files/operaciones/IPC/[a-z]+\d{4}/anex-IPC-[a-z]+\d{4}\.xlsx"),
}
# suameca.banrep.gov.co no envía el certificado intermedio (solo hoja + raíz): los
# navegadores y Windows lo completan solos, pero Python/requests falla. Se descarga
# el intermedio desde la URL "CA Issuers" (AIA) del propio certificado y se añade al
# contexto TLS solo para ese host. La verificación sigue activa.
SUAMECA_HOST = "https://suameca.banrep.gov.co"
SUAMECA_INTERMEDIATE_URL = "http://cacerts.digicert.com/GeoTrustEVRSACAG2.crt"
MONTHS = {m: i + 1 for i, m in enumerate(
    ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
     "septiembre", "octubre", "noviembre", "diciembre"])}
MONTHS["setiembre"] = 9
SDMX_NS = {"g": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/data/generic"}

log = comun.log


# ---------------------------------------------------------------- utilidades
def norm(text: str) -> str:
    return " ".join(str(text).split()).lower()


def to_float(values: pd.Series, name: str) -> pd.Series:
    """Convierte a número; los no numéricos se descartan (no se imputan) y se registran."""
    num = pd.to_numeric(values, errors="coerce")
    bad = values[num.isna() & values.notna() & (values.astype(str).str.strip() != "")]
    if len(bad):
        log.warning("%s: %d valores no numéricos descartados, p. ej. %s",
                    name, len(bad), bad.head(3).tolist())
    return num


def current_month_start(today: dt.date) -> pd.Timestamp:
    return pd.Timestamp(today.year, today.month, 1)


# ---------------------------------------------------------------- TLS SUAMECA
class _ContextAdapter(HTTPAdapter):
    """Adaptador de requests con un SSLContext propio."""

    def __init__(self, ctx: ssl.SSLContext, **kwargs):
        self._ctx = ctx
        super().__init__(**kwargs)

    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = self._ctx
        return super().init_poolmanager(*args, **kwargs)


def fix_suameca_tls(client: comun.Client) -> None:
    der = client.get(SUAMECA_INTERMEDIATE_URL).content
    ctx = ssl.create_default_context(cafile=certifi.where())
    ctx.load_verify_locations(cadata=ssl.DER_cert_to_PEM_cert(der))
    client.session.mount(SUAMECA_HOST, _ContextAdapter(ctx))


# ---------------------------------------------------------------- SUAMECA
def suameca_parse_code(codigo: str) -> tuple[list[str], list[str]]:
    """'375+376|x1000' -> (['375', '376'], ['x1000'])."""
    base, *ops = codigo.split("|")
    return base.split("+"), ops


def suameca_files(codigo: str) -> list[tuple[str, str | None]]:
    """(idSerie, tipoDato) que hay que descargar para un codigo_fuente."""
    ids, ops = suameca_parse_code(codigo)
    tipo = next((op.split("=")[1] for op in ops if op.startswith("tipoDato=")), None)
    out = [(i, tipo) for i in ids]
    out += [(op.split(":")[1], None) for op in ops
            if op.startswith(("suma_anual_pct_pib:", "div_fin_de_mes:"))]
    return out


def suameca_filename(id_serie: str, tipo: str | None) -> str:
    return f"{id_serie}.json" if tipo is None else f"{id_serie}_tipoDato{tipo}.json"


def suameca_url(id_serie: str, tipo: str | None) -> str:
    if tipo is None:
        return f"{SUAMECA_URL}/consultaInformacionSerie?idSerie={id_serie}"
    # cantDatos alto = toda la historia.
    return (f"{SUAMECA_URL}/consultaInformacionSerieXTipoDato?idSerie={id_serie}"
            f"&tipoDato={tipo}&cantDatos=100000")


def suameca_load(id_serie: str, tipo: str | None) -> tuple[dict, pd.Series]:
    path = comun.raw_path(ISO3, "banrep_suameca", suameca_filename(id_serie, tipo))
    payload = json.loads(path.read_bytes().decode("utf-8"))
    if isinstance(payload, list):
        payload = payload[0]
    data = payload.get("data") or []
    if not data:
        raise ValueError(f"{path.name}: sin datos")
    # Milisegundos epoch a medianoche de Bogotá (UTC-5 = 05:00 UTC). Entre may-1992 y
    # abr-1993 Colombia tuvo horario de verano (UTC-4 = 04:00 UTC): truncar daría el día
    # anterior y fechas repetidas, así que se resta 5 h y se redondea al día más cercano.
    fechas = (pd.to_datetime([d[0] for d in data], unit="ms") - pd.Timedelta(hours=5)).round("D")
    values = to_float(pd.Series([d[1] for d in data], index=fechas), f"suameca {id_serie}")
    values = values.dropna()
    if values.index.duplicated().any():
        raise ValueError(f"{path.name}: fechas repetidas")
    return payload, values.sort_index()


def suameca_series(s: dict, today: dt.date) -> pd.Series:
    ids, ops = suameca_parse_code(s["codigo_fuente"])
    tipo = next((op.split("=")[1] for op in ops if op.startswith("tipoDato=")), None)
    parts = []
    for i in ids:
        payload, values = suameca_load(i, tipo)
        if len(ids) == 1 and norm(payload.get("nombre", "")) not in norm(s["titulo_fuente"]):
            log.warning("%s: el nombre cambió\n    config: %s\n    API:    %s",
                        i, s["titulo_fuente"], payload.get("nombre"))
        parts.append(values)
    if len(parts) == 1:
        serie = parts[0]
    else:
        both = pd.concat(parts, axis=1, join="inner")
        if len(both) < max(len(p) for p in parts):
            log.info("%s: suma solo en periodos comunes (%d)", s["nombre_corto"], len(both))
        serie = both.sum(axis=1)

    cur = current_month_start(today)
    for op in ops:
        if op.startswith("tipoDato="):
            continue
        if op in ("promedio_mensual", "fin_de_mes"):
            if op == "promedio_mensual" and serie.index[0].day > 5:
                # Primer mes incompleto (la TRM empieza el 27-nov-1991): su promedio no es comparable.
                primero = serie.index[0].to_period("M")
                log.info("%s: se descarta el primer mes incompleto (%s)", s["nombre_corto"], primero)
                serie = serie[serie.index.to_period("M") > primero]
            month = serie.index.to_period("M").start_time
            serie = serie.groupby(month).mean() if op == "promedio_mensual" else serie.groupby(month).last()
            if (serie.index >= cur).any():
                log.info("%s: se descarta el mes en curso/futuro (%s)", s["nombre_corto"],
                         ", ".join(f"{d:%Y-%m}" for d in serie.index[serie.index >= cur]))
                serie = serie[serie.index < cur]
        elif op == "anual_a_mensual":
            recs = {}
            for fecha, v in serie.items():
                for m in range(1, 13):
                    f = pd.Timestamp(fecha.year, m, 1)
                    if f <= cur:
                        recs[f] = v
            serie = pd.Series(recs).sort_index()
        elif op.startswith("suma_anual_pct_pib:"):
            _, pib = suameca_load(op.split(":")[1], None)
            g = serie.groupby(serie.index.year)
            anual = g.sum()[g.count() == 12]          # solo años completos
            pib_anual = pib.groupby(pib.index.year).sum()
            ratio = (100 * anual / pib_anual).dropna()
            serie = pd.Series(ratio.values, index=[pd.Timestamp(y, 1, 1) for y in ratio.index])
        elif op.startswith("div_fin_de_mes:"):
            _, diaria = suameca_load(op.split(":")[1], None)
            fin = diaria.groupby(diaria.index.to_period("M")).last()
            meses = serie.index.to_period("M")
            if meses.duplicated().any():
                raise ValueError(f"{s['nombre_corto']}: div_fin_de_mes requiere una serie mensual")
            divisor = fin.reindex(meses)
            if divisor.isna().any():
                log.warning("%s: sin dato diario de fin de mes en %d meses (se descartan)",
                            s["nombre_corto"], int(divisor.isna().sum()))
            serie = pd.Series(serie.values / divisor.values, index=serie.index).dropna()
        elif re.fullmatch(r"x[\d.]+", op):
            serie = serie * float(op[1:])
        else:
            raise ValueError(f"Transformación desconocida: {op}")
    return serie


# ---------------------------------------------------------------- SDMX BanRep
def sdmx_series(s: dict) -> pd.Series:
    path = comun.raw_path(ISO3, "banrep_sdmx", f"{s['codigo_fuente']}.xml")
    root = ET.fromstring(path.read_bytes())
    series = root.findall(".//g:Series", SDMX_NS)
    if len(series) != 1:
        raise ValueError(f"{path.name}: se esperaba 1 serie y hay {len(series)}")
    recs = {}
    for obs in series[0].findall("g:Obs", SDMX_NS):
        periodo = obs.find("g:ObsDimension", SDMX_NS).get("value")
        valor = obs.find("g:ObsValue", SDMX_NS)
        recs[pd.Timestamp(periodo + "-01")] = valor.get("value") if valor is not None else None
    return to_float(pd.Series(recs), s["nombre_corto"]).dropna().sort_index()


# ---------------------------------------------------------------- EME (Excel)
def eme_series(s: dict) -> pd.Series:
    archivo, hoja, bloque, columna = s["codigo_fuente"].split("|")
    raw = pd.read_excel(comun.raw_path(ISO3, "banrep_eme", archivo), sheet_name=hoja, header=None)
    # Fila de encabezado: la que dice 'FECHA ENCUESTA' en la primera columna.
    hdr = next(i for i, v in raw[0].items() if norm(v) == "fecha encuesta")
    blocks = raw.iloc[hdr - 1]
    col_bloque = next(c for c, v in blocks.items() if isinstance(v, str) and bloque.lower() in norm(v))
    # Dentro del bloque (3 columnas: promedio, desviación, mediana) se busca la columna pedida.
    col = next(c for c in range(col_bloque, col_bloque + 3) if norm(raw.iat[hdr, c]) == columna.lower())
    fechas = pd.to_datetime(raw.iloc[hdr + 1:, 0], errors="coerce")
    vals = to_float(raw.iloc[hdr + 1:, col], s["nombre_corto"])
    serie = pd.Series(vals.values, index=fechas.values).dropna()
    serie = serie[serie.index.notna()]
    if not serie.between(-0.5, 1.5).all():
        raise ValueError(f"{s['nombre_corto']}: valores fuera de rango para una fracción")
    return serie * 100


# ---------------------------------------------------------------- DANE (Excel)
def dane_ise(raw: pd.DataFrame, bloque: str, fila: str, nombre: str) -> pd.Series:
    """Cuadro del ISE: varios bloques (índice, variación anual, año corrido), cada uno
    con una fila 'Concepto' (años) seguida de una fila de meses."""
    for c in [i for i, v in raw[0].items() if norm(v) == "concepto"]:
        titulo = " ".join(norm(v) for v in raw.iloc[max(0, c - 8):c, 0] if isinstance(v, str))
        if bloque.lower() not in titulo:
            continue
        # Los años recientes vienen como texto con marca de cifra preliminar ('2024p',
        # '2026pr'): se extraen los 4 dígitos. Solo están en la columna de enero.
        years = raw.iloc[c, 1:].map(
            lambda y: int(re.match(r"\s*(\d{4})", str(y))[1]) if re.match(r"\s*\d{4}", str(y)) else None)
        years = pd.to_numeric(years, errors="coerce").ffill()
        months = raw.iloc[c + 1, 1:].map(lambda m: MONTHS.get(norm(m)) if isinstance(m, str) else None)
        # La fila del total: el texto exacto, en las filas del bloque (hasta la nota 'Fuente').
        r = next(i for i in range(c + 2, len(raw))
                 if isinstance(raw.iat[i, 0], str) and norm(raw.iat[i, 0]) == fila.lower())
        recs = {}
        for col in years.index:
            if pd.isna(years[col]) or months[col] is None:
                continue
            fecha = pd.Timestamp(int(years[col]), int(months[col]), 1)
            if fecha in recs:
                raise ValueError(f"{nombre}: {fecha:%Y-%m} aparece dos veces en el encabezado")
            recs[fecha] = raw.at[r, col]
        serie = to_float(pd.Series(recs, dtype=object), nombre).dropna().sort_index()
        # Validación: meses consecutivos, sin huecos.
        if (serie.index.to_series().diff().dropna() > pd.Timedelta(days=31)).any():
            raise ValueError(f"{nombre}: huecos en la serie mensual")
        return serie
    raise ValueError(f"{nombre}: no se encontró el bloque '{bloque}'")


def dane_bcom(raw: pd.DataFrame, columna: str, nombre: str) -> pd.Series:
    hdr = next(i for i, v in raw[0].items() if norm(v) == "mes")
    col = next(c for c, v in raw.iloc[hdr].items() if norm(v) == columna.lower())
    fechas = pd.to_datetime(raw.iloc[hdr + 1:, 0], errors="coerce")
    ok = fechas.notna()
    vals = to_float(raw.iloc[hdr + 1:, col][ok], nombre)
    return pd.Series(vals.values, index=fechas[ok].values).dropna().sort_index()


def dane_ipc(raw: pd.DataFrame, columna: str, titulo: str, nombre: str) -> pd.Series:
    """Hoja del anexo general del IPC: título arriba, fila 'Año | Mes | Índice | Variación'
    y debajo 'Mensual | Año corrido | Anual'. Un año y un mes por fila."""
    top = " ".join(norm(v) for v in raw.iloc[:8, 0] if isinstance(v, str))
    if titulo.lower() not in top:
        raise ValueError(f"{nombre}: la hoja no es '{titulo}' (título: {top[:120]!r})")
    hdr = next(i for i, v in raw[0].items() if norm(v) == "año")
    col = next(c for r in (hdr, hdr + 1) for c, v in raw.iloc[r].items()
               if isinstance(v, str) and norm(v) == columna.lower())
    body = raw.iloc[hdr + 2:]
    recs = {}
    for i, mes in body[1].items():
        anio = pd.to_numeric(body.at[i, 0], errors="coerce")
        if not isinstance(mes, str) or norm(mes) not in MONTHS or pd.isna(anio):
            continue
        fecha = pd.Timestamp(int(anio), MONTHS[norm(mes)], 1)
        if fecha in recs:
            raise ValueError(f"{nombre}: {fecha:%Y-%m} aparece dos veces")
        recs[fecha] = body.at[i, col]
    serie = to_float(pd.Series(recs, dtype=object), nombre).dropna().sort_index()
    if (serie.index.to_series().diff().dropna() > pd.Timedelta(days=31)).any():
        raise ValueError(f"{nombre}: huecos en la serie mensual")
    return serie


def dane_series(s: dict) -> pd.Series:
    archivo, hoja, *resto = s["codigo_fuente"].split("|")
    raw = pd.read_excel(comun.raw_path(ISO3, "dane", archivo), sheet_name=hoja, header=None)
    if archivo.startswith("anex-ISE"):
        return dane_ise(raw, resto[0], resto[1], s["nombre_corto"])
    if archivo.startswith("anex-IPC"):
        return dane_ipc(raw, resto[0], resto[1], s["nombre_corto"])
    return dane_bcom(raw, resto[0], s["nombre_corto"])


# ---------------------------------------------------------------- descarga
def download(series: list[dict], client: comun.Client) -> None:
    done: set[str] = set()

    def save(fuente: str, filename: str, url: str, content: bytes) -> None:
        action = comun.save_raw(ISO3, fuente, filename, content, url)
        log.info("%-15s %-45s [%s]", fuente, filename, action)
        done.add(f"{fuente}/{filename}")

    for s in series:
        fuente, codigo = s["fuente"], s["codigo_fuente"]
        try:
            if fuente == "banrep_suameca":
                for id_serie, tipo in suameca_files(codigo):
                    fn = suameca_filename(id_serie, tipo)
                    if f"{fuente}/{fn}" in done:
                        continue
                    url = suameca_url(id_serie, tipo)
                    r = client.get(url)
                    payload = r.json()
                    payload = payload[0] if isinstance(payload, list) else payload
                    if not payload.get("data"):
                        raise ValueError(f"respuesta sin datos para idSerie={id_serie}")
                    save(fuente, fn, url, r.content)
            elif fuente == "banrep_sdmx":
                fn = f"{codigo}.xml"
                if f"{fuente}/{fn}" not in done:
                    url = SDMX_URL.format(flow=codigo)
                    r = client.get(url)
                    ET.fromstring(r.content)
                    save(fuente, fn, url, r.content)
            elif fuente == "banrep_eme":
                fn = codigo.split("|")[0]
                if f"{fuente}/{fn}" not in done:
                    r = client.get(EME_URL)
                    save(fuente, fn, EME_URL, r.content)
            elif fuente == "dane":
                fn = codigo.split("|")[0]
                if f"{fuente}/{fn}" not in done:
                    page, pattern = DANE_FILES[fn]
                    html = client.get(DANE_BASE + page).text
                    links = re.findall(pattern, html)
                    if not links:
                        raise ValueError(f"no se encontró el enlace a {fn} en {DANE_BASE + page}")
                    url = DANE_BASE + links[0]
                    r = client.get(url)
                    if not r.content.startswith(b"PK"):
                        raise ValueError(f"{url} no es un .xlsx")
                    log.info("DANE: archivo vigente %s", links[0].rsplit("/", 1)[-1])
                    save(fuente, fn, url, r.content)
            else:
                raise ValueError(f"fuente desconocida: {fuente}")
        except Exception as e:  # noqa: BLE001
            log.error("%s (%s): %s", s["nombre_corto"], codigo, e)


# ---------------------------------------------------------------- proceso
def process(series: list[dict], today: dt.date) -> None:
    readers = {"banrep_suameca": lambda s: suameca_series(s, today), "banrep_sdmx": sdmx_series,
               "banrep_eme": eme_series, "dane": dane_series}
    frames = []
    for s in series:
        try:
            serie = readers[s["fuente"]](s)
        except FileNotFoundError as e:
            log.warning("%s: falta el archivo crudo (%s)", s["nombre_corto"], e)
            continue
        except Exception as e:  # noqa: BLE001
            log.error("%s: no se pudo procesar: %s", s["nombre_corto"], e)
            continue
        if serie.empty:
            log.error("%s: sin observaciones", s["nombre_corto"])
            continue
        df = pd.DataFrame({"fecha": comun.period_start(pd.Series(serie.index), s["frecuencia"]),
                           "valor": serie.values})
        if df.fecha.duplicated().any():
            raise ValueError(f"{s['nombre_corto']}: periodos repetidos tras normalizar fechas")
        for col in ("fuente", "codigo_fuente", "nombre_corto", "indicador_comun", "frecuencia", "unidad"):
            df[col] = s[col]
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    out["pais"] = ISO3
    comun.write_interim(ISO3, out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--solo-procesar", action="store_true", help="no descarga; solo data/raw -> interim")
    ap.add_argument("--serie", nargs="+", help="nombre_corto de las series a descargar")
    ap.add_argument("--pausa", type=float, default=1.0, help="segundos entre peticiones (>= 1)")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # el log usa '→' y tildes

    comun.setup_logging(ISO3)
    today = dt.date.today()
    series = comun.load_series(ISO3)
    if not args.solo_procesar:
        todo = [s for s in series if not args.serie or s["nombre_corto"] in args.serie]
        client = comun.Client(pause=max(args.pausa, 1.0))
        fix_suameca_tls(client)
        download(todo, client)
    process(series, today)
    return 0


if __name__ == "__main__":
    sys.exit(main())
