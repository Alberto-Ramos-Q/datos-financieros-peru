"""Transcribe los cuadros departamentales de gasto e ingreso (I.1, I.8, I.15, I.19, I.21) del informe
técnico de pobreza 2016-2025 del INEI.

Escribe config/gasto_ingreso_oficial_departamental_2016_2025.csv (o la ruta de --salida, para probar).
Uso: python src/transcribir_gasto_ingreso_departamental.py [--salida ruta.csv]
Se escribió el 2026-11-03, durante la validación de gasto e ingreso, para que el CSV se pueda regenerar
desde código.
Every row is checked against the printed differences (2025-2024, 2025-2019) or, for I.21,
against its own CI (value +/- 1.96*SE) and against I.19.
"""
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "docs/enaho/2025/7_Informe_tecnico_de_pobreza/07_Informe_tecnico_de_Pobreza_Monetaria_2025.pdf"
OUT = ROOT / "config/gasto_ingreso_oficial_departamental_2016_2025.csv"
if "--salida" in sys.argv:
    OUT = Path(sys.argv[sys.argv.index("--salida") + 1])
YEARS = list(range(2016, 2026))

NAMES = {
    "amazonas": "01", "ancash": "02", "apurimac": "03", "arequipa": "04", "ayacucho": "05",
    "cajamarca": "06", "prov. const. del callao": "07", "prov. constit. del callao": "07",
    "cusco": "08", "huancavelica": "09", "huanuco": "10", "ica": "11", "junin": "12",
    "la libertad": "13", "lambayeque": "14", "lima metropolitana 1/": "15LM",
    "lima metropolitana1/": "15LM", "lima 2/": "15LP", "lima2/": "15LP", "loreto": "16",
    "madre de dios": "17", "moquegua": "18", "pasco": "19", "piura": "20", "puno": "21",
    "san martin": "22", "tacna": "23", "tumbes": "24", "ucayali": "25",
}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


def page_lines(p: int) -> list[str]:
    out = subprocess.run(["pdftotext", "-raw", "-enc", "UTF-8", "-f", str(p), "-l", str(p),
                          str(PDF), "-"], capture_output=True, check=True)
    return out.stdout.decode("utf-8").splitlines()


def split_name(line: str):
    """Return (ambito_id, tokens after the name) if the line starts with a department name."""
    tokens = line.split()
    for k in range(len(tokens), 0, -1):
        name = norm(" ".join(tokens[:k]))
        if name in NAMES:
            return NAMES[name], tokens[k:]
    return None, None


def take_ints(tokens: list[str], n: int) -> tuple[list[int], list[str]]:
    """Read n integers printed with a space as thousands separator ('1 232')."""
    vals, i = [], 0
    while len(vals) < n:
        t = tokens[i]
        if re.fullmatch(r"\d", t) and i + 1 < len(tokens) and re.fullmatch(r"\d{3}", tokens[i + 1]):
            vals.append(int(t) * 1000 + int(tokens[i + 1]))
            i += 2
        elif re.fullmatch(r"\d{2,3}", t):
            vals.append(int(t))
            i += 1
        else:
            raise ValueError(f"unexpected token {t!r} in {tokens}")
    return vals, tokens[i:]


def dec(t: str) -> float:
    return float(t.replace(",", "."))


def series_table(page: int, cuadro: str, indicator: str) -> list[dict]:
    rows = []
    for line in page_lines(page):
        aid, rest = split_name(line)
        if aid is None:
            continue
        vals, rest = take_ints(rest, 10)
        nums = [dec(t) for t in rest if re.fullmatch(r"-?\d+,\d+", t)]
        cv, var1, _, dif1, _, var2, _, dif2, _ = nums
        v = dict(zip(YEARS, vals))
        # controls: printed differences are computed with unrounded values (|err| <= 1)
        assert abs(dif1 - (v[2025] - v[2024])) <= 1.0 + 1e-9, (cuadro, aid, dif1)
        assert abs(dif2 - (v[2025] - v[2019])) <= 1.0 + 1e-9, (cuadro, aid, dif2)
        assert abs(var1 - 100 * dif1 / v[2024]) <= 0.1, (cuadro, aid, var1)
        assert abs(var2 - 100 * dif2 / v[2019]) <= 0.1, (cuadro, aid, var2)
        for y in YEARS:
            rows.append(dict(anio=y, ambito_id=aid, indicador=indicator, valor=v[y],
                             ee=None, ic_inf=None, ic_sup=None, cv=cv if y == 2025 else None,
                             cuadro=cuadro, pagina=page,
                             control_dif_2025_2024=dif1 if y == 2025 else None,
                             control_dif_2025_2019=dif2 if y == 2025 else None))
    assert len(rows) == 260, (cuadro, len(rows))
    return rows


def table_i21() -> list[dict]:
    rows = []
    blocks = {221: [2016, 2017, 2018], 222: [2019, 2020, 2021], 223: [2022, 2023, 2024],
              224: [2025]}
    for page, years in blocks.items():
        n = 0
        for line in page_lines(page):
            aid, rest = split_name(line)
            if aid is None:
                continue
            n += 1
            vals, rest = take_ints(rest, 4 * len(years))
            for j, y in enumerate(years):
                val, se, lo, hi = vals[4 * j: 4 * j + 4]
                # CI = value +/- 1.96*SE (all three rounded to the sol)
                # (structural check: midpoint ~ value, half-width ~ 1.96*SE, ordered)
                assert lo < val < hi and abs((lo + hi) / 2 - val) <= 1.0, (aid, y, vals[4*j:4*j+4])
                if abs((hi - lo) / 2 - 1.96 * se) > 1.5:
                    print(f"  I.21 {y} {aid}: SE {se} vs CI half-width/1.96 = "
                          f"{(hi - lo) / 2 / 1.96:.2f}  {vals[4*j:4*j+4]}")
                rows.append(dict(anio=y, ambito_id=aid, indicador="ingreso_i19_pc", valor=val,
                                 ee=se, ic_inf=lo, ic_sup=hi, cv=None, cuadro="Cuadro I.21",
                                 pagina=page, control_dif_2025_2024=None,
                                 control_dif_2025_2019=None))
        assert n == 26, (page, n)
    return rows


def main() -> int:
    rows = (series_table(176, "Cuadro I.1", "gasto_real_pc")
            + series_table(191, "Cuadro I.8", "gasto_nominal_pc")
            + series_table(206, "Cuadro I.15", "ingreso_real_pc")
            + series_table(218, "Cuadro I.19", "ingreso_i19_pc")
            + table_i21())
    df = pd.DataFrame(rows)
    # I.21 must repeat I.19
    a = df[df.cuadro == "Cuadro I.19"].set_index(["anio", "ambito_id"])["valor"]
    b = df[df.cuadro == "Cuadro I.21"].set_index(["anio", "ambito_id"])["valor"]
    diff = (a - b.reindex(a.index)).abs()
    print("I.19 vs I.21 distinct values:", int((diff > 0).sum()))
    print(df.loc[df.cuadro == "Cuadro I.21"].set_index(["anio", "ambito_id"]).loc[diff[diff > 0].index, "valor"]
          if (diff > 0).any() else "")
    assert df.groupby(["cuadro", "anio"]).size().eq(26).all()
    df = df.sort_values(["cuadro", "indicador", "ambito_id", "anio"],
                        key=lambda s: s.map({"Cuadro I.1": 1, "Cuadro I.8": 2, "Cuadro I.15": 3,
                                             "Cuadro I.19": 4, "Cuadro I.21": 5}).fillna(0)
                        if s.name == "cuadro" else s)
    df.to_csv(OUT, index=False, encoding="utf-8", float_format="%g")
    print(f"written {OUT} ({len(df)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
