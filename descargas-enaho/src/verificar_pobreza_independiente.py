"""Verificación independiente de la pobreza por departamento 2004–2025 (cuenta claude, 2026-11-03).

Vía paralela a `src/pobreza_departamental.py`, que **no se importa**: lee la Sumaria directo, estima
la incidencia y su IC 95 % con su propio código y lee los PDF del INEI con `pdftotext -layout`.

Controles:
  1. Recálculo de las 26 unidades × 22 años × {pobreza total, extrema} (1 144 cifras) frente a
     `data/processed/pobreza/pobreza_departamentos.parquet`: cifra puntual, IC, CV y n de hogares.
  2. Cuadro III.1 (pobreza total por departamento) de tres informes del INEI frente al Parquet:
     R2024 (2014–2023), R2025 (2015–2024) e informe 2025 (2016–2025). Se compara la cifra puntual
     de los 10 años; el IC y el CV del último año se informan sin exigirlos (el INEI usa un cálculo
     de varianza que no se reproduce exacto; ver docs/validacion_pobreza_departamental.md).
  3. Grupos oficiales de departamentos con pobreza estadísticamente semejante:
     - 2004–2006 (R2011, solo rangos enteros): regla de «rango» (ver `check_range_groups`);
     - 2007–2008 (R2018 y R2020): IC conjunto del grupo **sin estratos** (UPM = conglome);
     - 2009–2015 y 2016–2025: IC conjunto del grupo con estratos.
  4. Errata del INEI de marzo de 2012 (R2011, p. 18 del PDF): 2007, grupo 1, Huancavelica «61 % 72 %».

Diseño muestral: estimador de razón por linealización, estratos = `estrato`, UPM = `conglome`
(dentro del estrato), t de Student con gl = UPM − estratos. Peso = floor(factor07 × mieperho + 0,5).

Uso (desde la raíz del proyecto; tarda unos minutos):
    python src/verificar_pobreza_independiente.py
Solo lee e imprime. Sale con código 0 si todo cuadra y 1 si algo falla.
Requiere `pdftotext` (xpdf o poppler) en el PATH y `scipy` (viene con scikit-learn).
"""
from __future__ import annotations

import re
import subprocess
import sys
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
YEARS = range(2004, 2026)
UNITS_26 = [f"{i:02d}" for i in range(1, 26) if i != 15] + ["15LM", "15LP"]

DEPARTMENTS_PARQUET = ROOT / "data/processed/pobreza/pobreza_departamentos.parquet"
OFFICIAL_2004_2015 = ROOT / "config/pobreza_oficial_2004_2015.csv"
OFFICIAL_GROUPS_2016_2025 = ROOT / "config/grupos_departamentos_oficial_2016_2025.csv"
REFS = ROOT / "docs/referencias_inei/pobreza_2004_2015"

# Cuadro III.1 departamental: (PDF, página del PDF, primer año de la serie de 10 años)
CUADRO_III1 = [
    ("R2024", REFS / "informe_pobreza_2014-2023.pdf", 255, 2014),
    ("R2025", REFS / "informe_pobreza_2015-2024.pdf", 222, 2015),
    ("I2025", ROOT / "docs/enaho/2025/7_Informe_tecnico_de_pobreza/"
              "07_Informe_tecnico_de_Pobreza_Monetaria_2025.pdf", 232, 2016),
]
# Excepción documentada: en R2024 (p. 255) pdftotext pega la fila del Callao («Calla1o3,7»): el «1»
# de 13,7 queda dentro del nombre. Se repara en `parse_cuadro_iii1`; el valor reparado debe ser el
# que se leyó en la imagen de la página (13,7 para 2014, verificado a ojo el 2026-11-03).
PASTED_ROW_VISUAL = {("R2024", "07"): (2014, 13.7)}

R2011_PDF = REFS / "informe_pobreza_2004-2010_nueva_metodologia.pdf"
R2011_PAGE = 18

TOL_SAME = 1e-6        # pp: el recálculo debe dar la misma cifra puntual
TOL_CI_RECALC = 0.005  # pp: IC del recálculo frente al Parquet
TOL_CV_RECALC = 0.005  # puntos de CV
TOL_PUBLISHED = 0.05 + 1e-9  # pp: cifra publicada con un decimal

NAMES_III1 = {
    "amazonas": "01", "ancash": "02", "apurimac": "03", "arequipa": "04", "ayacucho": "05",
    "cajamarca": "06", "cusco": "08", "huancavelica": "09", "huanuco": "10", "ica": "11",
    "junin": "12", "lalibertad": "13", "lambayeque": "14", "limametropolitana": "15LM",
    "provconstdelcallao": "07", "provconstitucionaldelcallao": "07", "lima": "15LP",
    "loreto": "16", "madrededios": "17", "moquegua": "18", "pasco": "19", "piura": "20",
    "puno": "21", "sanmartin": "22", "tacna": "23", "tumbes": "24", "ucayali": "25",
}

results: list[dict] = []


def record(name: str, ok: int, total: int, detail: str, passed: bool | None = None) -> None:
    passed = (ok == total and total > 0) if passed is None else passed
    results.append(dict(name=name, ok=ok, total=total, detail=detail, passed=passed))
    print(f"  [{'OK' if passed else 'FALLA'}] {name}: {ok}/{total} — {detail}", flush=True)


# ---------------------------------------------------------------------------------------------
# Datos y estimador
# ---------------------------------------------------------------------------------------------
def load_sumaria(year: int) -> pd.DataFrame:
    s = pd.read_parquet(ROOT / f"data/processed/{year}/sumaria-{year}.parquet",
                        columns=["conglome", "ubigeo", "estrato", "mieperho", "pobreza", "factor07"])
    s = s[s["factor07"].notna() & s["pobreza"].notna()].reset_index(drop=True)
    if s["estrato"].isna().any() or s["conglome"].isna().any():
        raise ValueError(f"{year}: estrato o conglome nulos")
    poverty = s["pobreza"].astype(float)
    dpto = s["ubigeo"].str[:2]
    unit = np.where(dpto != "15", dpto, np.where(s["ubigeo"].str[:4] == "1501", "15LM", "15LP"))
    return pd.DataFrame({
        "conglome": s["conglome"].astype(str),
        "estrato": s["estrato"].astype(str),
        "w": np.floor(s["factor07"].astype(float) * s["mieperho"].astype(float) + 0.5),
        "pobreza_total": poverty.isin([1, 2]).astype(float),
        "pobreza_extrema": (poverty == 1).astype(float),
        "unit": unit,
    })


class Design:
    """Diseño de una Sumaria: con estratos (estrato, conglome) o sin estratos (UPM = conglome)."""

    def __init__(self, s: pd.DataFrame, stratified: bool = True):
        strata = s["estrato"] if stratified else pd.Series("0", index=s.index)
        psu_key = strata + "_" + s["conglome"]
        self.psu, psu_labels = pd.factorize(psu_key)
        strata_codes = pd.factorize(strata)[0]
        self.n_psu = len(psu_labels)
        self.psu_stratum = np.zeros(self.n_psu, dtype=int)
        self.psu_stratum[self.psu] = strata_codes
        self.n_h = np.bincount(self.psu_stratum).astype(float)
        self.t = stats.t.ppf(0.975, self.n_psu - len(self.n_h))
        self.w = s["w"].to_numpy()
        self.unit = s["unit"].to_numpy()
        self.s = s

    def estimate(self, units: list[str], indicator: str) -> dict:
        """Incidencia (%) en el dominio `units`, con IC 95 % y CV (%)."""
        y = self.s[indicator].to_numpy()
        wd = self.w * np.isin(self.unit, units)
        total_w = wd.sum()
        ratio = (wd * y).sum() / total_w
        z = wd * (y - ratio) / total_w
        z_psu = np.bincount(self.psu, weights=z, minlength=self.n_psu)
        mean_h = np.bincount(self.psu_stratum, weights=z_psu) / self.n_h
        ss_h = np.bincount(self.psu_stratum, weights=(z_psu - mean_h[self.psu_stratum]) ** 2)
        valid = self.n_h > 1
        se = np.sqrt((self.n_h[valid] / (self.n_h[valid] - 1) * ss_h[valid]).sum())
        return dict(v=100 * ratio, lo=100 * (ratio - self.t * se), hi=100 * (ratio + self.t * se),
                    cv=100 * se / ratio if ratio > 0 else np.nan, n=int((wd > 0).sum()))


def round_half_up(x: float) -> int:
    return int(np.floor(x + 0.5))


# ---------------------------------------------------------------------------------------------
# Lectura de PDF
# ---------------------------------------------------------------------------------------------
def pdf_page_text(pdf: Path, page: int) -> str:
    out = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", "-f", str(page), "-l", str(page),
                          str(pdf), "-"], capture_output=True, check=True)
    return out.stdout.decode("utf-8", errors="replace")


def letters_key(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", ascii_text.lower())


ROW_III1 = re.compile(r"^\s*(?P<label>.+?)\s+(?:\d+/\s+)?(?P<nums>-?\d+,\d.*)$")
# Fila pegada: un número interrumpe la última palabra del nombre y el resto del número le sigue
# sin espacio. «Prov. Constitucional del Calla1o3,7» → nombre «…Callao», primer número «13,7».
PASTED_LABEL = re.compile(r"^(?P<pre>.*[A-Za-z])(?P<d1>\d+)(?P<post>[a-z]*)(?P<d2>\d+,\d+)$")


def parse_cuadro_iii1(text: str) -> tuple[dict[str, list[float]], list[str]]:
    """Filas departamentales: 10 años + IC inferior + IC superior + CV del último año."""
    rows: dict[str, list[float]] = {}
    notes: list[str] = []
    for line in text.splitlines():
        m = ROW_III1.match(line)
        if not m:
            continue
        label, nums_text = m.group("label"), m.group("nums")
        repaired = None
        pasted = PASTED_LABEL.match(label.strip())
        if pasted:
            label = pasted.group("pre") + pasted.group("post")
            repaired = pasted.group("d1") + pasted.group("d2")
            nums_text = repaired + " " + nums_text
        key = letters_key(label)
        if key not in NAMES_III1:
            continue
        nums = re.findall(r"-?\d+,\d+", nums_text)
        if len(nums) < 13:
            continue
        unit = NAMES_III1[key]
        if unit in rows:
            raise ValueError(f"fila repetida para {unit}: {line.strip()[:60]}")
        rows[unit] = [float(x.replace(",", ".")) for x in nums[:13]]
        if repaired:
            notes.append(f"{unit}: fila pegada «{m.group('label').strip()[-12:]}…» reparada → "
                         f"primer número {repaired.replace(',', '.')}")
    return rows, notes


# ---------------------------------------------------------------------------------------------
# Controles
# ---------------------------------------------------------------------------------------------
def check_recalculation(designs: dict[int, Design], dep: pd.DataFrame) -> None:
    print("\n1. Recálculo desde Sumaria frente a pobreza_departamentos.parquet", flush=True)
    rows = []
    for year in YEARS:
        d = designs[year]
        for unit in UNITS_26:
            for ind in ("pobreza_total", "pobreza_extrema"):
                rows.append(dict(anio=year, ambito_id=unit, ind=ind, **d.estimate([unit], ind)))
    me = pd.DataFrame(rows)
    diffs = []
    for ind in ("pobreza_total", "pobreza_extrema"):
        cols = [ind, f"{ind}_ic_inf", f"{ind}_ic_sup", f"{ind}_cv", "n_hogares"]
        m = me[me["ind"] == ind].merge(dep[["anio", "ambito_id"] + cols], on=["anio", "ambito_id"],
                                       how="left")
        # Incidencia 0 (pobreza extrema en algunos años del Callao, Ica, Tacna): CV indefinido en
        # ambos lados; cuenta como coincidencia.
        both_undefined = m["cv"].isna() & m[f"{ind}_cv"].isna()
        diffs.append(pd.DataFrame({
            "missing": m[ind].isna(),
            "d_v": (m["v"] - m[ind]).abs(),
            "d_ci": np.maximum((m["lo"] - m[f"{ind}_ic_inf"]).abs(), (m["hi"] - m[f"{ind}_ic_sup"]).abs()),
            "d_cv": (m["cv"] - m[f"{ind}_cv"]).abs().where(~both_undefined, 0.0),
            "cv_undefined": both_undefined,
            "d_n": (m["n"] - m["n_hogares"]).abs(),
        }))
    d = pd.concat(diffs, ignore_index=True)
    total = len(d)
    present = (~d["missing"]).sum()
    record("filas con par en el Parquet", int(present), total, "26 unidades × 22 años × 2 indicadores")
    record("cifra puntual idéntica", int((d["d_v"] <= TOL_SAME).sum()), total,
           f"máx. |dif.| = {d['d_v'].max():.2e} pp (tol. {TOL_SAME:g})")
    record("límites del IC", int((d["d_ci"] <= TOL_CI_RECALC).sum()), total,
           f"máx. |dif.| = {d['d_ci'].max():.4f} pp (tol. {TOL_CI_RECALC})")
    record("CV", int((d["d_cv"] <= TOL_CV_RECALC).sum()), total,
           f"máx. |dif.| = {d['d_cv'].max():.4f} (tol. {TOL_CV_RECALC}); "
           f"{int(d['cv_undefined'].sum())} con incidencia 0 y CV indefinido en ambos")
    record("n de hogares", int((d["d_n"] == 0).sum()), total, f"máx. |dif.| = {d['d_n'].max():.0f}")


def check_cuadro_iii1(dep: pd.DataFrame) -> None:
    print("\n2. Cuadro III.1 (pobreza total por departamento) de tres informes frente al Parquet",
          flush=True)
    dep = dep.set_index(["anio", "ambito_id"])
    n_ok = n_total = 0
    max_diff = 0.0
    bad: list[str] = []
    for tag, pdf, page, first_year in CUADRO_III1:
        text = pdf_page_text(pdf, page)
        if "III.1" not in text:
            record(f"{tag} p.{page}", 0, 1, "la página no contiene el Cuadro III.1")
            continue
        rows, notes = parse_cuadro_iii1(text)
        for note in notes:
            print(f"     {tag}: {note}")
        missing = sorted(set(UNITS_26) - set(rows))
        record(f"{tag} p.{page}: unidades leídas", len(rows), 26,
               "faltan " + ", ".join(missing) if missing else "las 26")
        for (ptag, unit), (vyear, vvalue) in PASTED_ROW_VISUAL.items():
            if ptag == tag and unit in rows:
                got = rows[unit][vyear - first_year]
                record(f"{tag} fila pegada {unit} {vyear} = lectura visual {vvalue}",
                       int(abs(got - vvalue) < 1e-9), 1, f"leído {got}")
        last = first_year + 9
        ci_diff = cv_diff = 0.0
        for unit, vals in rows.items():
            for i in range(10):
                calc = dep.loc[(first_year + i, unit), "pobreza_total"]
                diff = abs(calc - vals[i])
                n_total += 1
                max_diff = max(max_diff, diff)
                if diff <= TOL_PUBLISHED:
                    n_ok += 1
                else:
                    bad.append(f"{tag} {unit} {first_year + i}: publicado {vals[i]}, calculado {calc:.3f}")
            r = dep.loc[(last, unit)]
            ci_diff = max(ci_diff, abs(r["pobreza_total_ic_inf"] - vals[10]),
                          abs(r["pobreza_total_ic_sup"] - vals[11]))
            cv_diff = max(cv_diff, abs(r["pobreza_total_cv"] - vals[12]))
        print(f"     {tag} (informativo, no se exige): IC {last} máx. |dif.| = {ci_diff:.3f} pp; "
              f"CV {last} máx. |dif.| = {cv_diff:.3f}")
    record("cifras puntuales (3 informes × 26 unidades × 10 años)", n_ok, n_total,
           f"máx. |dif.| = {max_diff:.3f} pp (tol. ±0,05)" + ("; fuera: " + "; ".join(bad) if bad else ""))


def group_units(ids: list[str]) -> list[str]:
    units: list[str] = []
    for i in ids:
        units += {"15": ["15LM", "15LP"], "15LR": ["15LP"]}.get(i, [i])
    return units


def load_groups() -> pd.DataFrame:
    old = pd.read_csv(OFFICIAL_2004_2015, dtype=str)
    old = old[old["ambito"].str.startswith("grupo")]
    old = pd.DataFrame({
        "anio": old["anio"].astype(int),
        "indicador": old["indicador"],
        "grupo": old["ambito"].str.extract(r"grupo(\d+)")[0].astype(int),
        "ids": old["ambito"].str.split(":").str[1].str.split("+"),
        "ic_inf": old["ic_inf"].astype(float), "ic_sup": old["ic_sup"].astype(float),
        "fuente": old["fuente"] + " p." + old["pagina"],
    })
    new = pd.read_csv(OFFICIAL_GROUPS_2016_2025, dtype=str)
    new = pd.DataFrame({
        "anio": new["anio"].astype(int), "indicador": new["indicador"],
        "grupo": new["grupo"].astype(int), "ids": new["ambito_ids"].str.split(";"),
        "ic_inf": new["ic_inf"].astype(float), "ic_sup": new["ic_sup"].astype(float),
        "fuente": "I2025 " + new["cuadro"] + " p." + new["pagina"],
    })
    g = pd.concat([old, new], ignore_index=True)
    g["units"] = g["ids"].map(group_units)
    return g.sort_values(["anio", "indicador", "grupo"]).reset_index(drop=True)


def check_partition(groups: pd.DataFrame) -> None:
    ok = total = 0
    bad = []
    for (year, ind), g in groups.groupby(["anio", "indicador"]):
        units = [u for us in g["units"] for u in us]
        total += 1
        if sorted(units) == sorted(UNITS_26):
            ok += 1
        else:
            extra = sorted({u for u in units if units.count(u) > 1})
            missing = sorted(set(UNITS_26) - set(units))
            bad.append(f"{year} {ind}: repetidas {extra}, faltan {missing}")
    record("cada año × indicador reparte las 26 unidades una sola vez", ok, total,
           "; ".join(bad) if bad else "sin repetidas ni faltantes")


def check_range_groups(groups: pd.DataFrame, designs: dict[int, Design]) -> None:
    """2004–2006: el INEI publica rangos enteros. Regla: grupo de un solo departamento (incluido
    «Lima con Callao», ids 15+07) → su IC redondeado al entero; grupo de varios → mínimo y máximo
    de las estimaciones puntuales de sus departamentos, redondeados (Lima = Lima con Callao)."""
    g = groups[groups["indicador"] == "pobreza_total_rango"]
    ok = 0
    bad = []
    for r in g.itertuples():
        d = designs[r.anio]
        ids = [i for i in r.ids if i != "07"]
        if len(ids) == 1:
            e = d.estimate(r.units, "pobreza_total")
            calc = (round_half_up(e["lo"]), round_half_up(e["hi"]))
        else:
            points = [d.estimate(["15LM", "15LP", "07"] if i == "15" else group_units([i]),
                                 "pobreza_total")["v"] for i in ids]
            calc = (round_half_up(min(points)), round_half_up(max(points)))
        pub = (round_half_up(r.ic_inf), round_half_up(r.ic_sup))
        if calc == pub:
            ok += 1
        else:
            bad.append(f"{r.anio} grupo {r.grupo}: publicado {pub}, calculado {calc}")
    record("2004–2006, regla de rango (R2011 p.18)", ok, len(g), "; ".join(bad) if bad else "exactos")


def check_ci_groups(groups: pd.DataFrame, designs: dict[int, Design], years: range, label: str,
                    stratified_designs: dict[int, Design] | None = None) -> None:
    g = groups[groups["anio"].isin(years) & (groups["indicador"] != "pobreza_total_rango")]
    ok = 0
    max_diff = 0.0
    bad = []
    for r in g.itertuples():
        e = designs[r.anio].estimate(r.units, r.indicador)
        diff = max(abs(e["lo"] - r.ic_inf), abs(e["hi"] - r.ic_sup))
        max_diff = max(max_diff, diff)
        if diff <= TOL_PUBLISHED:
            ok += 1
        else:
            bad.append(f"{r.anio} {r.indicador} grupo {r.grupo}: publicado {r.ic_inf}–{r.ic_sup}, "
                       f"calculado {e['lo']:.2f}–{e['hi']:.2f}")
    record(f"{label}: grupos con ambos límites ±0,05", ok, len(g),
           f"{2 * len(g)} límites; máx. |dif.| = {max_diff:.3f} pp" + ("; fuera: " + "; ".join(bad) if bad else ""))


def count_matches(groups: pd.DataFrame, designs: dict[int, Design], years: range) -> tuple[int, int]:
    g = groups[groups["anio"].isin(years) & (groups["indicador"] != "pobreza_total_rango")]
    ok = 0
    for r in g.itertuples():
        e = designs[r.anio].estimate(r.units, r.indicador)
        ok += max(abs(e["lo"] - r.ic_inf), abs(e["hi"] - r.ic_sup)) <= TOL_PUBLISHED
    return int(ok), len(g)


def check_errata_2012(groups: pd.DataFrame, designs: dict[int, Design],
                      unstratified: dict[int, Design]) -> None:
    """R2011 (marzo de 2012) p.18: la columna de rangos se lee en orden; los 17 primeros pares son
    los grupos de 2004–2006 y el 18.º es 2007, grupo 1 (Huancavelica)."""
    text = pdf_page_text(R2011_PDF, R2011_PAGE)
    pairs = [(int(a), int(b)) for a, b in re.findall(r"(\d+)%\s+(\d+)%", text)]
    rango = groups[groups["indicador"] == "pobreza_total_rango"]
    expected = [(round_half_up(a), round_half_up(b)) for a, b in zip(rango["ic_inf"], rango["ic_sup"])]
    record("R2011 p.18: 17 rangos 2004–2006 iguales a config/pobreza_oficial_2004_2015.csv",
           sum(p == e for p, e in zip(pairs, expected)), len(expected), f"{len(pairs)} pares leídos")
    if len(pairs) < 18:
        record("errata 2007 grupo 1", 0, 1, "no se encontró el 18.º par en la página")
        return
    pub = pairs[17]
    point = designs[2007].estimate(["09"], "pobreza_total")
    no_strata = unstratified[2007].estimate(["09"], "pobreza_total")
    r2018 = groups[(groups["anio"] == 2007) & (groups["grupo"] == 1)].iloc[0]
    confirmed = (pub == (61, 72) and not (pub[0] <= point["v"] <= pub[1])
                 and r2018.ic_inf <= point["v"] <= r2018.ic_sup)
    record("errata de marzo de 2012 (2007, grupo 1, Huancavelica)", int(confirmed), 1,
           f"R2011 publica {pub[0]} %–{pub[1]} %; estimación {point['v']:.2f}; R2018 {r2018.ic_inf}–"
           f"{r2018.ic_sup}; sin estratos {no_strata['lo']:.2f}–{no_strata['hi']:.2f}")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("Verificación independiente de la pobreza departamental 2004–2025", flush=True)
    print("Cargando Sumaria 2004–2025…", flush=True)
    sumarias = {year: load_sumaria(year) for year in YEARS}
    designs = {year: Design(s) for year, s in sumarias.items()}
    unstratified = {year: Design(sumarias[year], stratified=False) for year in (2007, 2008, 2009)}
    dep = pd.read_parquet(DEPARTMENTS_PARQUET)

    check_recalculation(designs, dep)
    check_cuadro_iii1(dep)

    print("\n3. Grupos oficiales de departamentos estadísticamente semejantes", flush=True)
    groups = load_groups()
    check_partition(groups)
    check_range_groups(groups, designs)
    check_ci_groups(groups, unstratified, range(2007, 2009), "2007–2008 sin estratos (UPM = conglome)")
    ok, n = count_matches(groups, designs, range(2007, 2009))
    print(f"     2007–2008 con estratos (informativo): {ok}/{n} grupos")
    ok, n = count_matches(groups, unstratified, range(2009, 2010))
    print(f"     2009 sin estratos (informativo): {ok}/{n} grupos")
    check_ci_groups(groups, designs, range(2009, 2016), "2009–2015 con estratos")
    check_ci_groups(groups, designs, range(2016, 2026), "2016–2025 con estratos")

    print("\n4. Errata del INEI de marzo de 2012", flush=True)
    check_errata_2012(groups, designs, unstratified)

    failed = [r for r in results if not r["passed"]]
    print("\n" + "=" * 80)
    if failed:
        print(f"RESULTADO: {len(failed)} de {len(results)} controles fallaron:")
        for r in failed:
            print(f"  - {r['name']}: {r['ok']}/{r['total']} — {r['detail']}")
        return 1
    print(f"RESULTADO: los {len(results)} controles cuadran.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
