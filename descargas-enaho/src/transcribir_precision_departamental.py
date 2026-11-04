"""Transcribe el IC 95 % y el CV oficiales de la pobreza total por departamento (Cuadro III.1).

Cada informe técnico del INEI publica la precisión solo de su último año:
    informe 2014-2023 (p. 255) → 2023 · informe 2015-2024 (p. 222) → 2024 · informe 2016-2025 (p. 232) → 2025.
Reutiliza el lector del Cuadro III.1 de `verificar_pobreza_independiente.py` (misma lectura, mismas excepciones).

Escribe `config/precision_departamental_oficial.csv` (anio, ambito_id, valor, ic_inf, ic_sup, cv, informe, pagina_pdf).
Controles: 26 unidades por informe; la cifra puntual coincide con la serie oficial transcrita
(`config/pobreza_oficial_departamental_2016_2025.csv`) y queda dentro de su IC; CV positivo.
Uso (desde la raíz del proyecto): python src/transcribir_precision_departamental.py
"""
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verificar_pobreza_independiente import CUADRO_III1, parse_cuadro_iii1, pdf_page_text  # noqa: E402

PROJECT_DIR = Path(__file__).resolve().parents[1]
OUT = PROJECT_DIR / "config" / "precision_departamental_oficial.csv"
SERIES = PROJECT_DIR / "config" / "pobreza_oficial_departamental_2016_2025.csv"
OFFICIAL_2014_2015 = PROJECT_DIR / "config" / "pobreza_oficial_2004_2015.csv"
REPORT_TITLE = {"R2024": "INEI, Evolución de la pobreza monetaria 2014-2023",
                "R2025": "INEI, Evolución de la pobreza monetaria 2015-2024",
                "I2025": "INEI, Evolución de la pobreza monetaria 2016-2025"}


def official_points() -> dict:
    s = pd.read_csv(SERIES, dtype={"ambito_id": str})
    s = s[s["indicador"] == "pobreza_total"]
    pts = {(int(r.anio), r.ambito_id): float(r.valor) for r in s.itertuples()}
    o = pd.read_csv(OFFICIAL_2014_2015)
    o = o[o["ambito"].str.startswith("dpto_") & (o["indicador"] == "pobreza_total")]
    for r in o.itertuples():
        pts[(int(r.anio), r.ambito[5:].replace("15LR", "15LP"))] = float(r.valor)
    return pts


def main() -> int:
    pts = official_points()
    rows, problems = [], []
    for key, pdf, page, first in CUADRO_III1:
        data, _ = parse_cuadro_iii1(pdf_page_text(pdf, page))
        year = first + 9
        if len(data) != 26:
            problems.append(f"{key}: {len(data)} unidades leídas (se esperan 26)")
        for uid, nums in sorted(data.items()):
            v, lo, hi, cv = nums[9], nums[10], nums[11], nums[12]
            ref = pts.get((year, uid))
            if ref is None or abs(ref - v) > 1e-9:
                problems.append(f"{key} {uid} {year}: cifra {v} frente a la serie oficial {ref}")
            if not (lo <= v <= hi) or cv <= 0:
                problems.append(f"{key} {uid} {year}: IC {lo}–{hi} o CV {cv} incoherentes con {v}")
            rows.append({"anio": year, "ambito_id": uid, "valor": v, "ic_inf": lo, "ic_sup": hi, "cv": cv,
                         "informe": REPORT_TITLE[key], "pagina_pdf": page})
    for p in problems:
        print("  PROBLEMA:", p)
    if problems:
        return 1
    df = pd.DataFrame(rows).sort_values(["anio", "ambito_id"])
    df.to_csv(OUT, index=False, encoding="utf-8")
    print(f"Escrito {OUT.relative_to(PROJECT_DIR)}: {len(df)} filas "
          f"({', '.join(str(y) for y in sorted(df['anio'].unique()))}); controles OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
