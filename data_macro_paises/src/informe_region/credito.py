"""Bloque «Crédito, dinero y salarios» del informe «El Perú frente a la región».

Lee la capa comparable (data/processed/comparable) y respeta la columna `uso`, las marcas
de régimen y los cortes de muestra. Para el Perú, las variables reales que se comparan entre
países (crédito real y salario mínimo real) se deflactan con el IPC nacional del INEI, que se
toma de data/processed/macro_observaciones.parquet; el IPC de Lima queda como contraste.

Devuelve un diccionario con el contrato común del informe
(id, titulo, resumen, kpis, graficos, tablas, advertencias).

Uso:
    python src/informe_region/credito.py   # escribe data/processed/informe_region/credito.json
"""
from __future__ import annotations

import fnmatch
import json
import math
import re
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
COMPARABLE_DIR = ROOT / "data" / "processed" / "comparable"
OUT_PATH = ROOT / "data" / "processed" / "informe_region" / "credito.json"

NAMES = {
    "PER": "Perú", "CHL": "Chile", "COL": "Colombia", "MEX": "México", "BRA": "Brasil",
    "ARG": "Argentina", "ECU": "Ecuador", "URY": "Uruguay", "PRY": "Paraguay",
    "BOL": "Bolivia", "PAN": "Panamá", "ESP": "España", "USA": "Estados Unidos",
}
CURRENCY = {
    "PER": "sol", "CHL": "peso chileno", "COL": "peso colombiano", "MEX": "peso mexicano",
    "BRA": "real", "ARG": "peso argentino", "URY": "peso uruguayo", "PRY": "guaraní",
    "BOL": "boliviano",
}
ALL_COUNTRIES = list(NAMES)
# Regla común del informe: medianas y puestos solo con América Latina (ESP y USA son referencia)
LATAM = ["PER", "CHL", "COL", "MEX", "BRA", "ARG", "ECU", "URY", "PRY", "BOL", "PAN"]
# Gráficos de escala común en % real: sin Argentina (inflación muy alta)
REGION_EX_ARG = [p for p in LATAM if p != "ARG"]
# Núcleo de pares con metas de inflación y tipo de cambio flotante
CORE_PEERS = ["CHL", "COL", "BRA", "MEX", "URY"]
USABLE = {"comparable", "comparable_con_ajuste"}
# Marcas de régimen que invalidan la variación; covid-19 se conserva y se avisa
BAD_REGIMES = {"quiebre_credito", "salto_no_explicado", "intervencion_indec",
               "hiperinflacion", "alta_inflacion", "quiebre_dinero"}
START_TREND = pd.Timestamp("2015-01-01")
BASE_START, BASE_END = pd.Timestamp("2015-01-01"), pd.Timestamp("2019-12-01")

# Reajuste de la RMV publicado en El Peruano (DS 015-2026-TR, 28-set-2026), vigente desde 2026-10-01.
# Solo se usa en textos mientras la serie del BCRP no lo recoja; nunca se agrega a la serie.
RMV_NEW = {"valor": 1230.0, "desde": pd.Timestamp("2026-10-01"), "norma": "DS 015-2026-TR"}

# Descripciones de régimen redactadas para el informe (con fuente oficial)
REGIME_TEXT = {
    ("BOL", "tc_oficial_unico"): ("desde el 29 de junio de 2026 el BCB calcula el tipo de cambio oficial "
                                  "a partir de operaciones de mercado (RD 88/2026), una serie con menos "
                                  "de 12 meses de historia"),
}

MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "setiembre", "octubre", "noviembre", "diciembre"]
MONTHS_SHORT = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "set", "oct", "nov", "dic"]

COVERAGE_LABEL = {
    "sistema_financiero": "Sistema financiero",
    "sistema_bancario": "Bancos",
    "sociedades_creadoras_deposito": "Sociedades creadoras de depósito",
    "banca_comercial": "Solo banca comercial",
    "ifm_y_otras_if": "IFM y otras instituciones financieras",
}
USO_LABEL = {
    "comparable": "Comparable",
    "comparable_con_ajuste": "Comparable con ajuste",
    "solo_tendencias": "Solo tendencias",
    "no_comparable": "No comparable",
}
CREDIT_SOURCES = ("Crédito: BCRP, BCCh, BanRep, BCB (Brasil), Banxico, BCU, BCP (Paraguay), "
                  "BCB (Bolivia), BCE (Ecuador), SBP (Panamá), BCRA, Banco de España y Reserva "
                  "Federal; IPC de los institutos de estadística y bancos centrales de cada país "
                  "(Perú: IPC nacional del INEI)")
WAGE_SOURCES = ("Salario mínimo: BCRP, BanRep, BCB (Brasil), Banxico, BCP (Paraguay), INE (Bolivia), "
                "INE (Uruguay), BCE (Ecuador), Banco de España y datos.gob.ar (Argentina); tipo de "
                "cambio e IPC oficiales de cada país (Perú: IPC nacional del INEI); "
                "El Peruano (DS 015-2026-TR)")


# ---------------------------------------------------------------- utilidades de formato
def fmt_num(x: float, dec: int = 1) -> str:
    """Número con coma decimal, punto de miles y signo menos tipográfico (U+2212)."""
    s = f"{abs(x):,.{dec}f}".replace(",", " ").replace(".", ",").replace(" ", ".")
    return ("−" + s) if (x < 0 and round(abs(x), dec) != 0) else s


def month_long(ts: pd.Timestamp) -> str:
    return f"{MONTHS[ts.month - 1]} de {ts.year}"


def month_short(ts: pd.Timestamp) -> str:
    return f"{MONTHS_SHORT[ts.month - 1]}-{ts.year}"


def iso(ts: pd.Timestamp) -> str:
    return ts.strftime("%Y-%m-%d")


def r1(x) -> float | None:
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), 1)


def clean(x):
    """NaN / inf → None, redondeo moderado para el JSON."""
    if x is None:
        return None
    if isinstance(x, float):
        return None if (math.isnan(x) or math.isinf(x)) else round(x, 4)
    return x


def join_es(items: list[str]) -> str:
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " y " + items[-1]


# ---------------------------------------------------------------- carga de datos
def _read_with_retry(reader, path: Path, tries: int = 6, wait: int = 30):
    """Lee un archivo que puede estar reescribiéndose; reintenta antes de fallar."""
    last = None
    for _ in range(tries):
        try:
            return reader(path)
        except Exception as exc:  # archivo a medio escribir o bloqueado
            last = exc
            time.sleep(wait)
    raise last


class Data:
    """Acceso a la capa comparable con régimen, cortes y el deflactor nacional del Perú."""

    def __init__(self, comparable_dir: Path):
        comparable_dir = Path(comparable_dir)
        self.obs = _read_with_retry(pd.read_parquet, comparable_dir / "comparable_observaciones.parquet")
        self.obs["fecha"] = pd.to_datetime(self.obs["fecha"])
        self.obs["regimen"] = self.obs["regimen"].fillna("")
        self.series = _read_with_retry(pd.read_csv, comparable_dir / "comparable_series.csv")
        config_dir = comparable_dir.parents[2] / "config" / "comparable"
        self.regimes = self._load_csv(config_dir / "regimenes.csv")
        self._apply_cuts(self._load_csv(config_dir / "cortes_muestra.csv"))
        # Series reemplazadas (Perú con IPC nacional); las de la capa siguen en get_capa
        self.override: dict[tuple[str, str], pd.DataFrame] = {}
        self.lima: dict[str, pd.Series] = {}
        self._peru_national(comparable_dir.parent / "macro_observaciones.parquet")

    @staticmethod
    def _load_csv(path: Path) -> pd.DataFrame:
        if not path.exists():
            return pd.DataFrame()
        return pd.read_csv(path, encoding="utf-8-sig")

    def _apply_cuts(self, cuts: pd.DataFrame) -> None:
        # Los cortes ya vienen aplicados en la capa; se reaplican por robustez (idempotente)
        if cuts.empty:
            return
        keep = pd.Series(True, index=self.obs.index)
        for _, c in cuts.iterrows():
            pats = [p.strip() for p in str(c["indicadores"]).split(",")]
            hit_ind = self.obs["indicador"].apply(lambda i: any(fnmatch.fnmatch(i, p) for p in pats))
            m = (self.obs["pais"] == c["pais"]) & hit_ind
            desde = pd.to_datetime(c["desde"]) if pd.notna(c["desde"]) else pd.Timestamp.min
            hasta = pd.to_datetime(c["hasta"]) if pd.notna(c["hasta"]) else pd.Timestamp.max
            inside = self.obs["fecha"].between(desde, hasta)
            keep &= ~(m & ~inside) if c["tipo"] == "mantener" else ~(m & inside)
        self.obs = self.obs[keep]

    def _peru_national(self, macro_path: Path) -> None:
        """Crédito real y salario mínimo real del Perú con el IPC nacional del INEI."""
        if not macro_path.exists():
            return
        macro = _read_with_retry(pd.read_parquet, macro_path)
        ipc = macro[(macro["pais"] == "PER") & (macro["nombre_corto"] == "ipc_nacional_indice")]
        ipc = ipc.assign(fecha=pd.to_datetime(ipc["fecha"])).set_index("fecha")["valor"].sort_index()
        if ipc.empty:
            return
        ipc_12 = ipc / ipc.shift(12, freq="MS") - 1  # inflación a/a nacional
        ipc_12 = ipc_12.dropna()

        # Guardar las versiones con IPC de Lima para el contraste
        for ind in ("credito_real_var_a", "salario_minimo_real_var_a", "salario_minimo_real_indice"):
            self.lima[ind] = self.get_capa(ind, "PER")

        # Crédito: variación nominal a TC constante de la capa, deflactada con el IPC nacional
        nom = self.get_capa("credito_var_a", "PER", with_regime=True)
        idx = nom.index.intersection(ipc_12.index)
        real = ((1 + nom.loc[idx, "valor"] / 100) / (1 + ipc_12.loc[idx]) - 1) * 100
        self.override[("credito_real_var_a", "PER")] = pd.DataFrame(
            {"valor": real, "regimen": nom.loc[idx, "regimen"]})

        # Salario mínimo: índice real 2019 = 100 y variación real a/a
        w = self.get_capa("salario_minimo_mensual_ml", "PER", with_regime=True)
        idx = w.index.intersection(ipc.index)
        real_w = w.loc[idx, "valor"] / ipc.loc[idx]
        base = real_w[real_w.index.year == 2019]
        if len(base) == 12:
            self.override[("salario_minimo_real_indice", "PER")] = pd.DataFrame(
                {"valor": real_w / base.mean() * 100, "regimen": w.loc[idx, "regimen"]})
        var = (real_w / real_w.shift(12, freq="MS") - 1).dropna() * 100
        self.override[("salario_minimo_real_var_a", "PER")] = pd.DataFrame(
            {"valor": var, "regimen": w.loc[var.index, "regimen"]})

    def meta(self, ind: str, pais: str) -> dict:
        row = self.series[(self.series["indicador"] == ind) & (self.series["pais"] == pais)]
        return {} if row.empty else row.iloc[0].to_dict()

    def uso(self, ind: str, pais: str) -> str | None:
        return self.meta(ind, pais).get("uso")

    def usable(self, ind: str, pais: str) -> bool:
        return self.uso(ind, pais) in USABLE

    def get_capa(self, ind: str, pais: str, desde: pd.Timestamp | None = None,
                 with_regime: bool = False):
        """Serie de la capa sin los tramos con régimen que invalida la medida."""
        d = self.obs[(self.obs["indicador"] == ind) & (self.obs["pais"] == pais)]
        d = d[d["valor"].notna()]
        bad = d["regimen"].str.split(";").map(lambda labels: bool(set(labels) & BAD_REGIMES)).astype(bool)
        d = d[~bad.to_numpy()].sort_values("fecha").set_index("fecha")[["valor", "regimen"]]
        if desde is not None:
            d = d[d.index >= desde]
        return d if with_regime else d["valor"]

    def get(self, ind: str, pais: str, desde: pd.Timestamp | None = None,
            with_regime: bool = False):
        """Como get_capa, pero con las series reemplazadas (Perú con IPC nacional)."""
        if (ind, pais) not in self.override:
            return self.get_capa(ind, pais, desde, with_regime)
        d = self.override[(ind, pais)].dropna(subset=["valor"]).sort_index()
        if desde is not None:
            d = d[d.index >= desde]
        return d if with_regime else d["valor"]

    def last(self, ind: str, pais: str, until: pd.Timestamp | None = None):
        """Último valor publicado (hasta `until` si se da): (fecha, valor, regimen) o None."""
        d = self.get(ind, pais, with_regime=True)
        if until is not None:
            d = d[d.index <= until]
        if d.empty:
            return None
        return d.index[-1], float(d["valor"].iloc[-1]), d["regimen"].iloc[-1]

    def at(self, ind: str, pais: str, month: pd.Timestamp):
        """Valor de un mes exacto o None."""
        s = self.get(ind, pais)
        return float(s.loc[month]) if month in s.index else None

    def regime_text(self, pais: str, label: str) -> str:
        if (pais, label) in REGIME_TEXT:
            return REGIME_TEXT[(pais, label)]
        if self.regimes.empty:
            return label
        r = self.regimes[(self.regimes["pais"] == pais) & (self.regimes["etiqueta"] == label)]
        desc = label if r.empty else str(r.iloc[0]["descripcion"])
        desc = re.sub(r"\s*\([^)]*\)", "", desc).rstrip(".")
        return desc[:1].lower() + desc[1:]


# ---------------------------------------------------------------- piezas del bloque
def bar_chart(data: Data, ind: str, countries: list[str], month: pd.Timestamp | None = None,
              order: str = "valor") -> list[dict]:
    """Un punto por país: el del mes `month` o, si falta, el último publicado antes (con su fecha)."""
    out = []
    for p in countries:
        lv = data.last(ind, p, until=month)
        if lv is None:
            continue
        out.append({"pais": p, "nombre": NAMES[p], "puntos": [[iso(lv[0]), clean(lv[1])]]})
    if order == "valor":
        return sorted(out, key=lambda s: -s["puntos"][0][1])
    # Orden fijo (no ranking): Perú primero y el resto alfabético
    return sorted(out, key=lambda s: (s["pais"] != "PER", s["nombre"]))


def line_series(data: Data, ind: str, countries: list[str], desde=START_TREND,
                nombre: dict | None = None, corto: dict | None = None) -> list[dict]:
    out = []
    for p in countries:
        s = data.get(ind, p, desde=desde)
        if s.empty:
            continue
        item = {"pais": p, "nombre": (nombre or {}).get(p, NAMES[p])}
        if corto and p in corto:  # etiqueta corta al final de la línea (opcional)
            item["corto"] = corto[p]
        item["puntos"] = [[iso(f), clean(float(v))] for f, v in s.items()]
        out.append(item)
    return out


def base_average(s: pd.Series, min_obs: int = 48) -> float:
    w = s[(s.index >= BASE_START) & (s.index <= BASE_END)]
    return float(w.mean()) if len(w) >= min_obs else float("nan")


def value_12m_before(s: pd.Series):
    if s.empty:
        return float("nan")
    target = s.index[-1] - pd.DateOffset(months=12)
    return float(s.loc[target]) if target in s.index else float("nan")


def peer_countries(data: Data, ind: str) -> list[str]:
    """Pares comparables del Perú: América Latina sin Argentina y con uso comparable."""
    return [p for p in REGION_EX_ARG if p != "PER" and data.usable(ind, p)]


def reference_month(data: Data, ind: str, share: float = 0.75):
    """Mes más reciente que el Perú comparte con al menos `share` de sus pares comparables."""
    peers = peer_countries(data, ind)
    per = data.get(ind, "PER")
    for m in reversed(per.index):
        n = sum(1 for p in peers if data.at(ind, p, m) is not None)
        if peers and n >= share * len(peers):
            return m
    return per.index[-1] if not per.empty else None


def same_month_median(data: Data, ind: str, month: pd.Timestamp, exclude: set[str]):
    """Mediana de los pares comparables (sin Argentina ni `exclude`) con dato en el mismo mes."""
    vals = {}
    for p in REGION_EX_ARG:
        if p in exclude or not data.usable(ind, p):
            continue
        v = data.at(ind, p, month)
        if v is not None:
            vals[p] = v
    med = float(pd.Series(list(vals.values())).median()) if vals else float("nan")
    return med, vals


def coverage_label(meta: dict) -> str:
    raw = str(meta.get("cobertura") or "")
    key = raw.split(" (")[0].strip()
    return COVERAGE_LABEL.get(key, key.replace("_", " ").capitalize() if key else "")


def credit_note(pais: str, meta: dict) -> str:
    metodo = str(meta.get("metodo") or "")
    notes = []
    if pais == "ARG":
        notes.append("inflación muy alta: variación real muy volátil")
    if pais in ("ECU", "PAN"):
        notes.append("economía dolarizada (saldo en USD)")
    elif "TC promedio 2019" in metodo:
        notes.append("moneda extranjera a tipo de cambio constante de 2019")
    elif pais in ("CHL", "MEX"):
        notes.append("moneda extranjera a tipo de cambio corriente (efecto pequeño)")
    elif pais in ("BRA", "ESP"):
        notes.append("moneda extranjera marginal")
    if pais == "PER":
        notes.append("deflactado con el IPC nacional del INEI")
    if pais == "PRY":
        notes.append("deflactado con el IPC de Asunción")
    if pais == "USA":
        notes.append("promedio mensual; solo bancos comerciales; referencia")
    if pais == "ESP":
        notes.append("quiebres de 2005 y 2012 excluidos; referencia")
    txt = "; ".join(notes)
    return txt[:1].upper() + txt[1:]


# ---------------------------------------------------------------- construcción
def build(comparable_dir: Path) -> dict:
    data = Data(Path(comparable_dir))
    resumen, kpis, graficos, tablas, advertencias = [], [], [], [], []
    CR = "credito_real_var_a"
    per_national = ("credito_real_var_a", "PER") in data.override
    lima_cr = data.lima.get(CR, pd.Series(dtype=float))

    # ---- 1. Crecimiento real del crédito: Perú frente a la mediana del mismo mes
    per_cr = data.last(CR, "PER")
    # Mes común: el más reciente que el Perú comparte con al menos el 75 % de sus pares
    month_cr = reference_month(data, CR)
    med_txt_mex = ""
    if per_cr is not None and month_cr is not None:
        f, v, _ = per_cr
        vr = data.at(CR, "PER", month_cr)
        med, vals = same_month_median(data, CR, month_cr, exclude={"PER"})
        med_no_mex, _ = same_month_median(data, CR, month_cr, exclude={"PER", "MEX"})
        v1, vr1, m1 = r1(v), r1(vr), r1(med)
        gap = round(vr1 - m1, 1)
        n_peers = len(peer_countries(data, CR))
        verbo = "creció" if v >= 0 else "se contrajo"
        pos = "por encima de" if gap > 0 else "por debajo de" if gap < 0 else "igual a"
        quien = (("de los otros " if len(vals) == n_peers else f"de {len(vals)} de los ")
                 + f"{n_peers} países comparables de la región")
        if month_cr == f:
            resumen.append(
                f"El crédito al sector privado del Perú {verbo} {fmt_num(abs(v1))} % real en los doce "
                f"meses a {month_long(f)}, a tipo de cambio constante y deflactado con el IPC nacional; "
                f"está {fmt_num(abs(gap))} pp {pos} la mediana de {fmt_num(m1)} % {quien}.")
        else:
            resumen.append(
                f"El crédito al sector privado del Perú {verbo} {fmt_num(abs(v1))} % real en los doce "
                f"meses a {month_long(f)}, a tipo de cambio constante y deflactado con el IPC nacional. "
                f"En {month_long(month_cr)}, el último mes con datos de casi toda la región, creció "
                f"{fmt_num(vr1)} %, {fmt_num(abs(gap))} pp {pos} la mediana de {fmt_num(m1)} % {quien}.")
        if "MEX" in vals:
            if r1(med_no_mex) == m1:
                med_txt_mex = (f" México cubre solo la banca comercial; la mediana de {month_short(month_cr)} "
                               f"es {fmt_num(m1)} % con él y sigue en {fmt_num(m1)} % sin él.")
            else:
                med_txt_mex = (f" México cubre solo la banca comercial; la mediana de {month_short(month_cr)} "
                               f"es {fmt_num(m1)} % con él y {fmt_num(r1(med_no_mex))} % sin él.")
        kpis.append({"lab": "Crédito real al sector privado, Perú", "val": v1, "fmt": "pct1",
                     "unit": "% a/a", "sub": "a tipo de cambio constante, deflactado con el IPC nacional",
                     "fecha": iso(f)})
        kpis.append({"lab": "Perú frente a la mediana regional", "val": gap, "fmt": "pp1", "unit": "pp",
                     "sub": f"{month_short(month_cr)}: Perú {fmt_num(vr1)} % y mediana {quien} "
                            f"{fmt_num(m1)} %",
                     "fecha": iso(month_cr)})

    # Trayectoria del Perú: mínimo reciente (desde 2021-07, fuera del tramo covid-19) y promedio 2015-2019
    per_s = data.get(CR, "PER", with_regime=True)
    if not per_s.empty:
        vals_s = per_s["valor"]
        post = vals_s[vals_s.index >= pd.Timestamp("2021-07-01")]
        avg_base = base_average(vals_s)
        if not post.empty:
            fmin, vmin = post.idxmin(), float(post.min())
            cur = float(vals_s.iloc[-1])
            prev_hi = vals_s[(vals_s.index < vals_s.index[-1]) & (vals_s >= cur)]
            since = ""
            if not prev_hi.empty and prev_hi.index[-1] < vals_s.index[-2]:
                f_hi = prev_hi.index[-1]
                covid = (" (periodo covid-19)"
                         if "covid" in per_s.loc[f_hi, "regimen"].split(";") else "")
                since = f"; es el ritmo más alto desde {month_long(f_hi)}{covid}"
            rel = "por encima" if r1(cur) > r1(avg_base) else "por debajo" if r1(cur) < r1(avg_base) else "en línea"
            resumen.append(
                f"Tras tocar {fmt_num(vmin)} % en {month_long(fmin)}, el crecimiento real del crédito "
                f"peruano se recuperó hasta {fmt_num(cur)} %{since}, {rel} de su promedio de 2015-2019 "
                f"({fmt_num(avg_base)} %).")

    lima_note = ""
    if per_cr is not None and per_cr[0] in lima_cr.index:
        lima_note = (f" Con el IPC de Lima Metropolitana, el crédito real del Perú habría crecido "
                     f"{fmt_num(float(lima_cr.loc[per_cr[0]]))} % en {month_short(per_cr[0])}.")
    elif per_cr is not None and not lima_cr.empty:
        lima_note = (f" Con el IPC de Lima Metropolitana, el último dato ({month_short(lima_cr.index[-1])}) "
                     f"es {fmt_num(float(lima_cr.iloc[-1]))} %.")

    graficos.append({
        "id": "credito_real_ultimo",
        "titulo": "Crecimiento real del crédito al sector privado",
        "subtitulo": (f"Variación % a/a del saldo deflactado con el IPC; {month_long(month_cr)}, último "
                      f"mes con datos de casi toda la región" if month_cr is not None else
                      "Variación % a/a del saldo deflactado con el IPC; último dato de cada país"),
        "tipo": "barras_h", "unidad": "% a/a",
        "series": bar_chart(data, CR, [p for p in REGION_EX_ARG if data.usable(CR, p)], month=month_cr),
        "nota": ("Moneda extranjera a tipo de cambio constante de 2019 donde hay desglose (Perú, Colombia, "
                 "Uruguay, Paraguay y Bolivia). En Chile y México la parte en moneda extranjera va a tipo "
                 "de cambio corriente (efecto pequeño); en Brasil es marginal. Ecuador y Panamá están "
                 "dolarizados. Argentina se excluye por su inflación muy alta (ver tabla). Perú se deflacta "
                 "con el IPC nacional del INEI y Paraguay con el IPC de Asunción. Cada barra lleva su fecha."
                 + med_txt_mex + lima_note),
        "fuente": CREDIT_SOURCES,
    })

    # ---- 2. Ciclo del crédito: Perú frente a sus pares (desde 2015)
    graficos.append({
        "id": "credito_real_ciclo",
        "titulo": "Ciclo del crédito: Perú frente a sus pares",
        "subtitulo": "Crédito real al sector privado, variación % a/a mensual desde 2015",
        "tipo": "lineas", "unidad": "% a/a",
        "series": line_series(data, CR, ["PER"] + [p for p in CORE_PEERS if data.usable(CR, p)]),
        "nota": ("Pares con metas de inflación y tipo de cambio flotante. Perú, deflactado con el IPC "
                 "nacional del INEI. Marzo de 2020 a junio de 2021 es un periodo marcado como covid-19: "
                 "las variaciones de ese tramo reflejan medidas excepcionales y se leen con cautela."),
        "fuente": CREDIT_SOURCES,
    })

    # ---- 3. Crédito / PBI (sin ranking; solo series con perímetro comparable)
    CP = "credito_pct_pbi"
    depth_countries = [p for p in REGION_EX_ARG if data.usable(CP, p)]
    depth_out = [p for p in LATAM if p not in depth_countries]
    perim = {}
    for p in depth_countries:
        perim.setdefault(coverage_label(data.meta(CP, p)).lower(), []).append(NAMES[p])
    perim_txt = "; ".join(f"{k}: {join_es(sorted(v))}" for k, v in perim.items())
    old_years = [f"{NAMES[p]} tiene el dato de {data.last(CP, p)[0].year}" for p in depth_countries
                 if data.last(CP, p) is not None
                 and data.last(CP, p)[0] < max(data.last(CP, q)[0] for q in depth_countries
                                               if data.last(CP, q) is not None)]
    esp = data.last(CP, "ESP")
    esp_txt = (f" España ({fmt_num(esp[1])} % en {esp[0].year}) no se incluye: su serie suma "
               f"intermediarios financieros no monetarios, un perímetro más amplio."
               if esp is not None else "")
    graficos.append({
        "id": "credito_pct_pbi",
        "titulo": "Crédito al sector privado en % del PBI",
        "subtitulo": "Saldo de diciembre sobre el PBI nominal del año; último año disponible",
        "tipo": "barras_h", "unidad": "% del PBI",
        "series": bar_chart(data, CP, depth_countries, order="fijo"),
        "nota": ("No es un ranking: el perímetro de cada serie difiere (" + perim_txt + "). "
                 + (join_es(old_years) + ". " if old_years else "")
                 + "Fuera: " + join_es([NAMES[p] for p in depth_out])
                 + " (México cubre solo la banca comercial, Paraguay no incluye cooperativas y Argentina "
                   "tiene inflación muy alta)." + esp_txt
                 + " En el Perú el saldo va a tipo de cambio corriente."),
        "fuente": CREDIT_SOURCES + "; PBI nominal de las cuentas nacionales",
    })
    per_depth = data.last(CP, "PER")
    if per_depth is not None:
        kpis.append({"lab": "Crédito al sector privado, Perú", "val": r1(per_depth[1]), "fmt": "num1",
                     "unit": "% del PBI", "sub": f"saldo de diciembre de {per_depth[0].year}",
                     "fecha": iso(per_depth[0])})

    # ---- 4. Perú: crédito, liquidez y tasas (solo tendencia dentro del país)
    graficos.append({
        "id": "peru_credito_liquidez",
        "titulo": "Perú: crédito y liquidez",
        "subtitulo": "Variación % a/a nominal desde 2015",
        "tipo": "lineas", "unidad": "% a/a",
        "series": (line_series(data, "credito_var_a", ["PER"],
                               nombre={"PER": "Crédito al sector privado (TC constante)"},
                               corto={"PER": "Crédito (TC const.)"})
                   + line_series(data, "dinero_amplio_var_a", ["PER"],
                                 nombre={"PER": "Liquidez total (TC corriente)"},
                                 corto={"PER": "Liquidez (TC corr.)"})),
        "nota": ("Ambas series son del Perú. La liquidez total de las sociedades creadoras de depósito "
                 "incluye moneda extranjera a tipo de cambio corriente. El dinero amplio no se compara "
                 "entre países porque cada uno define el agregado de forma distinta."),
        "fuente": "BCRP",
    })
    rates_series = (line_series(data, "tasa_activa_promedio", ["PER"], nombre={"PER": "Activa (TAMN)"}, corto={"PER": "TAMN"})
                    + line_series(data, "tasa_pasiva_promedio", ["PER"], nombre={"PER": "Pasiva (TIPMN)"}, corto={"PER": "TIPMN"})
                    + line_series(data, "tasa_politica_tea", ["PER"], nombre={"PER": "Tasa de referencia del BCRP"},
                                 corto={"PER": "Referencia"}))
    graficos.append({
        "id": "peru_tasas",
        "titulo": "Perú: tasas de interés en soles",
        "subtitulo": "% efectivo anual, fin de mes, desde 2015",
        "tipo": "lineas", "unidad": "% anual",
        "series": rates_series,
        "nota": ("TAMN y TIPMN son promedios de la banca sobre saldos: la activa incluye tarjetas y "
                 "cambia también con la composición de la cartera, y la pasiva incluye depósitos a la "
                 "vista. La tasa que mide el traspaso de la política monetaria es la de operaciones de "
                 "los últimos 30 días (FTAMN), que está en el tablero de transmisión. Sirven para seguir "
                 "la tendencia dentro del Perú: no se comparan sus niveles ni sus spreads con otros "
                 "países, que publican tasas con definiciones distintas."),
        "fuente": "BCRP",
    })
    act = data.get("tasa_activa_promedio", "PER")
    pol = data.last("tasa_politica_tea", "PER")
    if not act.empty and pol is not None:
        a_now, a_12 = float(act.iloc[-1]), value_12m_before(act)
        diff = a_now - a_12
        dir_txt = "más" if diff > 0 else "menos"
        older = act[act.index < act.index[-1]]
        cmp = older[older >= a_now] if diff > 0 else older[older <= a_now]
        since = ""
        if not cmp.empty and cmp.index[-1] < older.index[-1]:
            since = f", el nivel más {'alto' if diff > 0 else 'bajo'} desde {month_long(cmp.index[-1])}"
        pol_s = data.get("tasa_politica_tea", "PER")
        changes = pol_s[pol_s.diff().fillna(0) != 0]
        pol_since = (f", sin cambios desde {month_long(changes.index[-1])}"
                     if not changes.empty and changes.index[-1] < pol_s.index[-1] else "")
        resumen.append(
            f"En el Perú, la tasa activa promedio en soles (TAMN) llegó a {fmt_num(a_now, 1)} % en "
            f"{month_long(act.index[-1])}{since}, {fmt_num(abs(diff), 1)} pp {dir_txt} que un año antes, "
            f"mientras la tasa de referencia del BCRP está en {fmt_num(pol[1], 2)} %{pol_since}; al ser un "
            f"promedio sobre saldos, la TAMN también refleja la composición de la cartera.")

    # ---- 5. Salario mínimo en USD y real
    SU, SR, SV = "salario_minimo_usd", "salario_minimo_real_indice", "salario_minimo_real_var_a"
    per_wage = data.last(SU, "PER")
    month_w = reference_month(data, SU)
    wage_latam = [p for p in REGION_EX_ARG if data.usable(SU, p) and data.last(SU, p) is not None]
    bars_wage = bar_chart(data, SU, wage_latam, month=month_w)
    wage_notes = []
    for s in bars_wage:
        p = s["pais"]
        lv = data.last(SU, p, until=month_w)
        for lab in filter(None, lv[2].split(";")):
            wage_notes.append(f"en {NAMES[p]}, {data.regime_text(p, lab)}")

    # Anuncio del reajuste de la RMV mientras la serie no lo recoja
    ml = data.get("salario_minimo_mensual_ml", "PER")
    rmv_txt = ""
    if not ml.empty and ml.index[-1] < RMV_NEW["desde"] and float(ml.iloc[-1]) < RMV_NEW["valor"]:
        alza = (RMV_NEW["valor"] / float(ml.iloc[-1]) - 1) * 100
        rmv_txt = (f"Desde el 1 de octubre de 2026 la RMV es S/ {fmt_num(RMV_NEW['valor'], 0).replace('.', ' ')} "
                   f"({RMV_NEW['norma']}), un alza nominal de {fmt_num(alza)} %; la serie del BCRP llega a "
                   f"{month_long(ml.index[-1])}.")

    # Ejemplo de efecto cambiario: la moneda que más se apreció frente al USD en 12 meses
    fx_txt = ""
    if month_w is not None:
        moves = {}
        for p in wage_latam:
            tc = data.get("tc_ml_por_usd", p)
            prev = month_w - pd.DateOffset(months=12)
            if p in CURRENCY and month_w in tc.index and prev in tc.index:
                moves[p] = (float(tc.loc[month_w]) / float(tc.loc[prev]) - 1) * 100
        if moves:
            p_min = min(moves, key=moves.get)
            if moves[p_min] < 0:
                fx_txt = (f" Por ejemplo, entre {month_short(month_w - pd.DateOffset(months=12))} y "
                          f"{month_short(month_w)} el {CURRENCY[p_min]} se apreció frente al dólar (el tipo de "
                          f"cambio bajó {fmt_num(abs(moves[p_min]))} %), lo que eleva el salario de "
                          f"{NAMES[p_min]} en USD sin que cambie en moneda local.")

    graficos.append({
        "id": "salario_minimo_usd",
        "titulo": "Salario mínimo mensual en dólares",
        "subtitulo": (f"USD por mes al tipo de cambio promedio del mes; {month_long(month_w)}, último mes "
                      f"con datos de casi toda la región" if month_w is not None else "USD por mes"),
        "tipo": "barras_h", "unidad": "USD por mes",
        "series": bars_wage,
        "nota": ("México: salario diario × 30,4. Chile, sin serie oficial descargable; Panamá fija mínimos "
                 "por región y actividad. Argentina queda fuera de la comparación (ver tabla). España (14 pagas llevadas a 12) se muestra en la tabla como referencia. "
                 "El nivel en USD depende del tipo de cambio." + fx_txt
                 + (" " + rmv_txt if rmv_txt else "")
                 + (" Nota cambiaria: " + "; ".join(wage_notes) + "." if wage_notes else "")),
        "fuente": WAGE_SOURCES,
    })

    real_countries = [p for p in REGION_EX_ARG if data.usable(SR, p)]
    per_ri_lima = data.lima.get(SR, pd.Series(dtype=float))
    per_rv_lima = data.lima.get(SV, pd.Series(dtype=float))
    lima_w = ""
    if month_w is not None and month_w in per_rv_lima.index and month_w in per_ri_lima.index:
        lima_w = (f" Con el IPC de Lima Metropolitana, el Perú tendría un índice de "
                  f"{fmt_num(float(per_ri_lima.loc[month_w]))} y una variación real de "
                  f"{fmt_num(float(per_rv_lima.loc[month_w]))} % a/a en {month_short(month_w)}.")
    graficos.append({
        "id": "salario_minimo_real",
        "titulo": "Poder adquisitivo del salario mínimo",
        "subtitulo": "Salario mínimo real, índice 2019 = 100, mensual desde 2015",
        "tipo": "lineas", "unidad": "índice 2019 = 100",
        "series": line_series(data, SR, ["PER"] + [p for p in real_countries if p != "PER"]),
        "nota": ("Deflactado con el IPC de cada país (Perú: IPC nacional del INEI; Paraguay: Asunción). "
                 "El índice compara la evolución de cada país frente a su propio 2019, no niveles entre "
                 "países. Argentina se excluye por su inflación muy alta; Ecuador no tiene índice "
                 "rebasado a 2019." + (" " + rmv_txt if rmv_txt else "") + lima_w),
        "fuente": WAGE_SOURCES,
    })

    if per_wage is not None:
        ranked = [s for s in bars_wage if s["puntos"][0][0] == iso(month_w)]
        rank_codes = [s["pais"] for s in sorted(ranked, key=lambda s: -s["puntos"][0][1])]
        rank = rank_codes.index("PER") + 1
        kpis.append({"lab": "Salario mínimo, Perú", "val": round(per_wage[1], 0), "fmt": "num0",
                     "unit": "USD/mes",
                     "sub": f"puesto {rank} de {len(rank_codes)} países comparables de la región en "
                            f"{month_short(month_w)}",
                     "fecha": iso(per_wage[0])})
        per_rv, per_ri = data.last(SV, "PER"), data.last(SR, "PER")
        when = ("ese mes" if month_w == per_wage[0]
                else f"en {month_long(month_w)}, el último mes con datos de casi toda la región")
        txt = (f"El salario mínimo del Perú equivalía a {fmt_num(per_wage[1], 0)} USD al mes en "
               f"{month_long(per_wage[0])}, puesto {rank} de {len(rank_codes)} países comparables de la "
               f"región {when}")
        if per_rv is not None:
            txt += (f"; en términos reales {'subía' if per_rv[1] >= 0 else 'caía'} "
                    f"{fmt_num(abs(per_rv[1]))} % a/a con el IPC nacional")
            sub = f"IPC nacional; índice 2019 = 100: {fmt_num(per_ri[1])}" if per_ri else "IPC nacional"
            if rmv_txt:
                sub += f"; dato anterior al reajuste de oct-2026 (RMV S/ 1 230)"
            kpis.append({"lab": "Salario mínimo real, Perú", "val": r1(per_rv[1]), "fmt": "pct1",
                         "unit": "% a/a", "sub": sub, "fecha": iso(per_rv[0])})
        if per_ri is not None:
            d = per_ri[1] - 100
            txt += (f" y quedaba {fmt_num(abs(d))} % {'por debajo' if d < 0 else 'por encima'} "
                    f"de su poder adquisitivo de 2019")
        resumen.append(txt + (". " + rmv_txt if rmv_txt else "."))

    # ---- Tablas
    rows = []
    for p in ALL_COUNTRIES:
        s = data.get(CR, p)
        if s.empty:
            continue
        meta = data.meta(CR, p)
        cur, prev, avg = float(s.iloc[-1]), value_12m_before(s), base_average(s)
        gap = round(r1(cur) - r1(avg), 1) if not math.isnan(avg) else None
        uso = USO_LABEL.get(meta.get("uso"), meta.get("uso"))
        if p in ("ESP", "USA"):
            uso = f"{uso} (referencia)"
        rows.append([NAMES[p], r1(cur), iso(s.index[-1]), r1(prev), r1(avg), gap,
                     coverage_label(meta), uso, credit_note(p, meta)])
    rows.sort(key=lambda r: (r[0] != "Perú", r[0] in ("España", "Estados Unidos"),
                             -(r[1] if r[1] is not None else -1e9)))
    tablas.append({
        "id": "credito_real_tabla",
        "titulo": "Crédito real al sector privado: último dato, hace un año y promedio 2015-2019",
        "columnas": ["País", "Var. real a/a (%)", "Fecha", "Hace 12 meses (%)", "Promedio 2015-2019 (%)",
                     "Frente a 2015-2019 (pp)", "Cobertura", "Uso", "Nota"],
        "filas": rows,
        "nota": ("La brecha frente al promedio de 2015-2019 compara a cada país consigo mismo, por lo que "
                 "no depende de diferencias de cobertura. El promedio se exige con al menos 48 meses de "
                 "dato. España y Estados Unidos son referencia y no entran en medianas ni puestos; Estados "
                 "Unidos (solo bancos comerciales) se lee solo como tendencia." + lima_note),
    })

    wrows = []
    for p in LATAM + ["ESP"]:
        u = data.last(SU, p)
        if u is None:
            continue
        rv, ri = data.last(SV, p), data.last(SR, p)
        wrows.append([NAMES[p], round(u[1], 0), iso(u[0]), r1(rv[1]) if rv else None,
                      r1(ri[1]) if ri else None, iso(rv[0]) if rv else None])
    # Perú primero, luego la región de mayor a menor y España al final como referencia
    wrows.sort(key=lambda r: (r[0] != "Perú", r[0] == "España", -(r[1] or 0)))
    tablas.append({
        "id": "salario_minimo_tabla",
        "titulo": "Salario mínimo: en dólares y en términos reales",
        "columnas": ["País", "USD por mes", "Fecha", "Var. real a/a (%)", "Índice real (2019 = 100)",
                     "Fecha del dato real"],
        "filas": wrows,
        "nota": ("Último dato publicado de cada país. Perú, deflactado con el IPC nacional del INEI. "
                 "España: 14 pagas llevadas a 12 (× 14/12), como referencia externa. Argentina: variación "
                 "real con inflación muy alta. Ecuador no tiene índice real rebasado a 2019."
                 + (" " + rmv_txt if rmv_txt else "")),
    })

    # ---- Advertencias (generadas con los datos)
    arg = data.get(CR, "ARG")
    if not arg.empty:
        recent = arg[arg.index >= arg.index[-1] - pd.DateOffset(months=36)]
        advertencias.append(
            f"Argentina queda fuera de los gráficos de crédito y salario real: con inflación muy alta, su "
            f"crédito real osciló entre {fmt_num(float(recent.min()))} % y {fmt_num(float(recent.max()))} % "
            f"a/a en los últimos tres años. No entra en medianas, puestos ni gráficos de comparación; "
            f"se muestra solo en las tablas.")
    advertencias.append(
        "Las medianas y los puestos usan solo los países comparables de América Latina (sin Argentina) "
        "en un mes común: el más reciente que el Perú comparte con al menos el 75 % de ellos. España y "
        "Estados Unidos son referencia. El crédito de Estados Unidos (solo bancos "
        "comerciales) sirve solo para tendencias." + med_txt_mex)
    advertencias.append(
        "En Chile y México la parte en moneda extranjera del crédito va a tipo de cambio corriente (efecto "
        "pequeño); en Brasil y España es marginal.")
    if per_national:
        advertencias.append(
            "Para comparar con otros países, el crédito real y el salario mínimo real del Perú se deflactan "
            "con el IPC nacional del INEI, no con el de Lima Metropolitana (que se da como contraste). "
            "Paraguay se deflacta con el IPC de Asunción, que no es nacional.")
    else:
        advertencias.append(
            "El crédito real y el salario mínimo real del Perú se deflactan con el IPC de Lima "
            "Metropolitana y los de Paraguay con el de Asunción, no con un IPC nacional.")
    pan_cr = data.get(CR, "PAN")
    advertencias.append(
        "Ecuador y Panamá están dolarizados: el ajuste por tipo de cambio no aplica. Panamá no tiene "
        "dinero amplio, tasas ni salario mínimo único en estos datos"
        + (f", y su crédito real empieza en {month_short(pan_cr.index[0])} (IPC disponible desde 2024)"
           if not pan_cr.empty else "") + ".")
    advertencias.append(
        "Las tasas activas y pasivas y el dinero amplio se usan solo como tendencia dentro de cada país: "
        "miden conceptos distintos según el país y no permiten comparar niveles ni spreads bancarios.")
    last_dates = [data.last(CR, p)[0] for p in REGION_EX_ARG if data.last(CR, p) is not None]
    if last_dates:
        advertencias.append(
            f"Los últimos datos de crédito van de {month_long(min(last_dates))} a "
            f"{month_long(max(last_dates))} según el país; no se rellenan huecos.")
    advertencias.append("El salario mínimo en USD depende del tipo de cambio de cada mes." + fx_txt)
    if rmv_txt:
        advertencias.append(rmv_txt + " La caída del salario mínimo real del Perú es anterior a ese reajuste.")
    for n in wage_notes:
        advertencias.append(f"Salario mínimo en USD: {n}.")

    return {"id": "credito", "titulo": "Crédito, dinero y salarios", "resumen": resumen, "kpis": kpis,
            "graficos": graficos, "tablas": tablas, "advertencias": advertencias}


# ---------------------------------------------------------------- JSON
def _to_json_safe(obj):
    if isinstance(obj, dict):
        return {k: _to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_json_safe(v) for v in obj]
    if isinstance(obj, float):
        return clean(obj)
    if hasattr(obj, "item"):  # escalares de numpy
        return _to_json_safe(obj.item())
    return obj


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    result = _to_json_safe(build(COMPARABLE_DIR))
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=1, allow_nan=False), encoding="utf-8")

    # Controles
    print(f"Escrito: {OUT_PATH.relative_to(ROOT)}")
    print("\nResumen:")
    for r in result["resumen"]:
        print(" -", r)
    print("\nKPIs:")
    for k in result["kpis"]:
        print(f" - {k['lab']}: {k['val']} {k['unit']} ({k['fecha']}) | {k['sub']}")
    print("\nGráficos:")
    for g in result["graficos"]:
        npts = sum(len(s["puntos"]) for s in g["series"])
        nulls = sum(1 for s in g["series"] for pt in s["puntos"] if pt[1] is None)
        print(f" - {g['id']} [{g['tipo']}]: {len(g['series'])} series, {npts} puntos, {nulls} nulos | "
              + ", ".join(s["pais"] for s in g["series"]))
    print("\nTablas:")
    for t in result["tablas"]:
        print(f" - {t['id']}: {len(t['filas'])} filas")
    print("\nAdvertencias:")
    for a in result["advertencias"]:
        print(" -", a)
    # Controles de estilo
    text = json.dumps(result, ensure_ascii=False)
    for bad in ("septiembre", "–", "aún no", "COVID", "capa", "agente", ".py"):
        if bad in text:
            print(f"AVISO de estilo: aparece «{bad}»")
