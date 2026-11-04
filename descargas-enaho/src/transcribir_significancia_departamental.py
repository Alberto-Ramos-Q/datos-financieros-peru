"""Transcribe la significancia oficial de los cambios de la pobreza total por departamento.

Fuente: Cuadro III.1 («Perú: evolución de la incidencia de la pobreza, según ámbito geográfico…
y departamento») de tres informes técnicos del INEI. Cada fila departamental trae 10 cifras
anuales, el IC 95 % y el CV del último año y dos bloques «Dif. % | P>t | Significancia»:

    informe     PDF, página del PDF      comparaciones
    2014-2023   R2024, p. 255            2023/2022, 2023/2019
    2015-2024   R2025, p. 222            2024/2023, 2024/2019
    2016-2025   informe 2025, p. 232     2025/2024, 2025/2019

Las tres páginas solo traen filas de departamentos (los ámbitos están en otras páginas del
cuadro), así que solo se transcriben las 26 unidades departamentales del INEI.

Método de lectura: la tabla está impresa rotada 90° en una página vertical, y `pdftotext -layout`
desordena los bloques de P>t en R2024 y R2025 (los valores p de «2023/2019» salen en otra línea).
Por eso se lee con PyMuPDF (`page.get_text("words")`), que da la posición de cada palabra:
  - cada fila del cuadro es una franja vertical de la página (misma x);
  - el orden de las columnas es el de y decreciente (el texto corre de abajo hacia arriba).
Se agrupan las palabras por x y se ordenan por y. Un «-» suelto se une con el número siguiente
(signo partido, p. ej. «- 5,3» en Ucayali 2025).

Controles (si alguno falla, el script termina con código 1):
  1. Estructura: 26 filas por página, nombres en el orden esperado, 17 números por fila, cada
     campo en su columna (misma banda de y en las 26 filas) y estimación dentro de su IC.
  2. Cobertura: 26 unidades × 6 comparaciones = 156 filas, sin duplicados.
  3. Diferencias: `dif_pp` = cifra del año − cifra del año de comparación de la misma fila, ± 0,1.
  4. Estrellas frente al valor p, según la nota del cuadro: *** p < 0,01; ** p < 0,05;
     * p < 0,10. Como P>t viene redondeado a 2 decimales, un caso es «compatible» si alguna
     p dentro de [P>t − 0,005; P>t + 0,005) da esas estrellas. Lo incompatible solo se acepta si
     figura en KNOWN_STAR_ANOMALIES (verificado en la imagen de la página).
  5. Cruce con `config/pobreza_oficial_departamental_2016_2025.csv`: `dif_pp` de 2025 frente a
     `control_dif_2025_2024` y `control_dif_2025_2019`, con signo; y las 260 cifras anuales
     2016–2025 de la misma página frente a la columna `valor`.

Uso (desde la raíz del proyecto):
    python src/transcribir_significancia_departamental.py
    python src/transcribir_significancia_departamental.py --imagenes <carpeta>   # + revisión visual
Escribe `config/significancia_departamental_oficial.csv`. Requiere PyMuPDF (`import pymupdf`).
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import unicodedata
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
OUT_CSV = ROOT / "config/significancia_departamental_oficial.csv"
PRIOR_CSV = ROOT / "config/pobreza_oficial_departamental_2016_2025.csv"
REFS = ROOT / "docs/referencias_inei/pobreza_2004_2015"

CUADRO = "Cuadro III.1"
BASE_YEAR = 2019  # segunda comparación de los tres informes

REPORTS = [
    dict(informe="2014-2023", pdf=REFS / "informe_pobreza_2014-2023.pdf", page=255,
         first_year=2014),
    dict(informe="2015-2024", pdf=REFS / "informe_pobreza_2015-2024.pdf", page=222,
         first_year=2015),
    dict(informe="2016-2025", pdf=ROOT / "docs/enaho/2025/7_Informe_tecnico_de_pobreza/"
         "07_Informe_tecnico_de_Pobreza_Monetaria_2025.pdf", page=232, first_year=2016),
]

# Orden de las filas en el Cuadro III.1 (igual en los tres informes) y su ambito_id.
ROW_ORDER = [
    ("amazonas", "01"), ("ancash", "02"), ("apurimac", "03"), ("arequipa", "04"),
    ("ayacucho", "05"), ("cajamarca", "06"), ("cusco", "08"), ("huancavelica", "09"),
    ("huanuco", "10"), ("ica", "11"), ("junin", "12"), ("lalibertad", "13"),
    ("lambayeque", "14"), ("limametropolitana", "15LM"), ("provconstdelcallao", "07"),
    ("lima", "15LP"), ("loreto", "16"), ("madrededios", "17"), ("moquegua", "18"),
    ("pasco", "19"), ("piura", "20"), ("puno", "21"), ("sanmartin", "22"), ("tacna", "23"),
    ("tumbes", "24"), ("ucayali", "25"),
]
# Variantes de nombre por informe. En R2024 la etiqueta del Callao es «Prov. Constitucional del
# Callao», pero la línea de la columna la recorta en la impresión: se ve «…del Ca» y PyMuPDF solo
# devuelve los caracteres visibles. `pdftotext` sí recupera «llao» (pegado al 13,7 de 2014), así que
# el texto completo está en el PDF. Verificado en la imagen de la página el 2026-11-03.
LABEL_EXCEPTIONS = {
    ("2014-2023", "provconstitucionaldelca"): ("07", "Prov. Constitucional del Callao"),
}
ALIASES = {"provconstitucionaldelcallao": "provconstdelcallao"}

# Casos en que las estrellas impresas no son compatibles con P>t ni con su redondeo. Se aceptan
# solo si están aquí, con lo que se ve en la imagen de la página: (informe, anio_comparacion,
# ambito_id) -> (P>t, estrellas). Revisión visual del 2026-11-03.
KNOWN_STAR_ANOMALIES: dict[tuple[str, int, str], tuple[float, str]] = {
    # R2025, p. 222, Ayacucho 2024/2019: se lee «-6,6 0,05» sin estrella. Con P>t = 0,05 la
    # nota exige «*» (si p < 0,05, «**»): falta la marca en el cuadro publicado.
    ("2015-2024", 2019, "05"): (0.05, ""),
}

NUMBER = re.compile(r"^-?\d+,\d+$")
STARS = {"*", "**", "***"}
TOL_DIF = 0.1 + 1e-9       # pp: diferencia impresa frente a la de las cifras redondeadas
TOL_BAND = 6.0             # pt: dispersión máxima de un campo entre filas (banda de columna)
TABLE_Y = (80.0, 780.0)    # pt: banda vertical de la tabla en las tres páginas
N_NUMBERS = 17             # 10 años + IC inf + IC sup + CV + (dif, p) × 2

# Índices de los campos de cada fila
I_INF, I_SUP, I_CV = 10, 11, 12
I_DIF1, I_P1, I_DIF2, I_P2 = 13, 14, 15, 16

results: list[tuple[str, bool, str]] = []


def record(name: str, passed: bool, detail: str) -> None:
    results.append((name, passed, detail))
    print(f"  [{'OK ' if passed else 'FALLA'}] {name}: {detail}")


def letters_key(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", ascii_text.lower())


def to_float(text: str) -> float:
    return float(text.replace(",", "."))


# ---------------------------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------------------------
def page_rows(page: pymupdf.Page) -> list[dict]:
    """Agrupa las palabras de la tabla rotada en filas (franjas de x) ordenadas por y decreciente."""
    # Solo la banda de la tabla: fuera quedan el encabezado y el pie de página (texto horizontal).
    words = [w for w in page.get_text("words") if TABLE_Y[0] < (w[1] + w[3]) / 2 < TABLE_Y[1]]
    numeric_x = sorted(w[0] for w in words if NUMBER.match(w[4]))
    centers: list[list[float]] = []
    for x in numeric_x:
        if centers and x - centers[-1][-1] <= 3.0:
            centers[-1].append(x)
        else:
            centers.append([x])
    rows = []
    for xs in centers:
        cx = sorted(xs)[len(xs) // 2]
        tokens = sorted(((w[4], (w[1] + w[3]) / 2) for w in words if abs(w[0] - cx) <= 3.0),
                        key=lambda t: -t[1])
        rows.append(dict(x=cx, tokens=tokens))
    return rows


def parse_row(tokens: list[tuple[str, float]]) -> dict:
    """Separa nombre, 17 números (con su y) y las estrellas de cada bloque de significancia."""
    name: list[str] = []
    nums: list[tuple[float, float]] = []
    stars = {I_P1: "", I_P2: ""}
    pending_sign = False
    for text, y in tokens:
        if NUMBER.match(text):
            value = to_float(text)
            if pending_sign:
                if value < 0:
                    raise ValueError(f"doble signo en «- {text}»")
                value, pending_sign = -value, False
            nums.append((value, y))
        elif text == "-" and nums:
            pending_sign = True
        elif text in STARS and nums:
            idx = len(nums) - 1
            if idx not in stars or stars[idx]:
                raise ValueError(f"estrellas «{text}» fuera de una columna de significancia")
            stars[idx] = text
        elif not nums:
            name.append(text)
        else:
            raise ValueError(f"palabra inesperada dentro de la fila: «{text}»")
    if pending_sign:
        raise ValueError("signo «-» sin número")
    return dict(name=" ".join(name), nums=nums, stars=stars)


def read_report(rep: dict) -> tuple[list[dict], list[str]]:
    """Lee la página del informe; devuelve las filas y los problemas de estructura."""
    problems: list[str] = []
    with pymupdf.open(rep["pdf"]) as doc:
        raw_rows = page_rows(doc[rep["page"] - 1])
    if len(raw_rows) != len(ROW_ORDER):
        problems.append(f"{len(raw_rows)} filas (se esperan {len(ROW_ORDER)})")
    rows = []
    for pos, raw in enumerate(raw_rows):
        try:
            row = parse_row(raw["tokens"])
        except ValueError as exc:
            problems.append(f"fila {pos + 1}: {exc}")
            continue
        key = letters_key(row["name"])
        label = row["name"]
        if (rep["informe"], key) in LABEL_EXCEPTIONS:
            unit, label = LABEL_EXCEPTIONS[(rep["informe"], key)]
            key = "provconstdelcallao"
        key = ALIASES.get(key, key)
        expected_key, unit = ROW_ORDER[pos] if pos < len(ROW_ORDER) else (None, None)
        if key != expected_key:
            problems.append(f"fila {pos + 1}: «{row['name']}» (se esperaba {expected_key})")
            continue
        if len(row["nums"]) != N_NUMBERS:
            problems.append(f"{unit}: {len(row['nums'])} números (se esperan {N_NUMBERS})")
            continue
        row.update(ambito_id=unit, label=label, x=raw["x"])
        rows.append(row)
    # Cada campo debe caer en la misma banda de y en todas las filas (columna del cuadro).
    if len(rows) == len(ROW_ORDER):
        for i in range(N_NUMBERS):
            ys = [r["nums"][i][1] for r in rows]
            if max(ys) - min(ys) > TOL_BAND:
                problems.append(f"campo {i}: y entre {min(ys):.1f} y {max(ys):.1f}")
        for r in rows:
            v = [n for n, _ in r["nums"]]
            if not v[I_INF] <= v[9] <= v[I_SUP]:
                problems.append(f"{r['ambito_id']}: estimación {v[9]} fuera de su IC")
    return rows, problems


# ---------------------------------------------------------------------------------------------
# Reglas de significancia
# ---------------------------------------------------------------------------------------------
def stars_for(p: float) -> str:
    """Nota del Cuadro III.1: * p < 0,10; ** p < 0,05; *** p < 0,01."""
    if p < 0.01:
        return "***"
    if p < 0.05:
        return "**"
    if p < 0.10:
        return "*"
    return ""


def stars_compatible(p_printed: float) -> set[str]:
    """Estrellas posibles para una p real en [P>t − 0,005; P>t + 0,005) (P>t con 2 decimales)."""
    lo, hi = max(p_printed - 0.005, 0.0), p_printed + 0.005 - 1e-12
    options = {stars_for(lo), stars_for(hi)}
    options |= {stars_for(c) for c in (0.01, 0.05, 0.10) if lo <= c <= hi}
    return options


# ---------------------------------------------------------------------------------------------
# Revisión visual
# ---------------------------------------------------------------------------------------------
def render_rows(rep: dict, rows: list[dict], units: list[str], out: Path) -> None:
    """Imagen horizontal (página girada 90°) de las filas indicadas, con la cabecera del cuadro."""
    sel = [r for r in rows if r["ambito_id"] in units]
    xs = [r["x"] for r in sel]
    with pymupdf.open(rep["pdf"]) as doc:
        page = doc[rep["page"] - 1]
        ys = [y for r in rows for _, y in r["nums"]]
        clip = pymupdf.Rect(min(xs) - 4, min(ys) - 35, max(xs) + 13, page.rect.height - 95)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(3, 3).prerotate(90), clip=clip)
        pix.save(out)


# ---------------------------------------------------------------------------------------------
# Principal
# ---------------------------------------------------------------------------------------------
def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--imagenes", type=Path, help="carpeta donde guardar recortes PNG")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):  # consola cp1252 de Windows: no romper por un carácter
        sys.stdout.reconfigure(errors="replace")

    print("1. Lectura y estructura del Cuadro III.1")
    out_rows: list[dict] = []
    annual: dict[tuple[str, int, str], float] = {}
    by_report: dict[str, list[dict]] = {}
    for rep in REPORTS:
        rows, problems = read_report(rep)
        by_report[rep["informe"]] = rows
        record(f"Estructura {rep['informe']} (p. {rep['page']})", not problems,
               "26 filas en orden, 17 números por fila, columnas alineadas, estimación dentro "
               "del IC" if not problems else "; ".join(problems))
        last = rep["first_year"] + 9
        for r in rows:
            v = [n for n, _ in r["nums"]]
            for k in range(10):
                annual[(rep["informe"], rep["first_year"] + k, r["ambito_id"])] = v[k]
            for comp, i_dif, i_p in ((last - 1, I_DIF1, I_P1), (BASE_YEAR, I_DIF2, I_P2)):
                out_rows.append(dict(
                    anio=last, anio_comparacion=comp, ambito_id=r["ambito_id"],
                    ambito_pdf=r["label"], dif_pp=v[i_dif], p_valor=v[i_p],
                    significancia=r["stars"][i_p], cuadro=CUADRO, pagina=rep["page"],
                    informe=rep["informe"],
                    _calc=v[9] - v[comp - rep["first_year"]]))

    print("\n2. Cobertura")
    keys = [(r["informe"], r["anio_comparacion"], r["ambito_id"]) for r in out_rows]
    units = {u for _, u in ROW_ORDER}
    per_comp: dict[tuple[str, int], set[str]] = {}
    for inf, comp, u in keys:
        per_comp.setdefault((inf, comp), set()).add(u)
    ok = (len(out_rows) == 156 and len(set(keys)) == 156 and len(per_comp) == 6
          and all(s == units for s in per_comp.values()))
    record("Cobertura", ok, f"{len(set(keys))} filas únicas de {len(out_rows)}; "
           f"{len(per_comp)} comparaciones × 26 unidades")

    print("\n3. Diferencias impresas frente a las cifras de la misma fila")
    gaps = [abs(r["dif_pp"] - r["_calc"]) for r in out_rows]
    bad = [r for r, g in zip(out_rows, gaps) if g > TOL_DIF]
    exact = sum(g <= 0.05 for g in gaps)
    record("Diferencias ± 0,1", not bad and len(gaps) == 156,
           f"{len(gaps) - len(bad)}/{len(gaps)} cuadran; {exact} exactas (<= 0,05), "
           f"{len(gaps) - exact - len(bad)} a 0,1 por redondeo; dif. máx. {max(gaps):.2f} pp"
           + "".join(f"\n      {r['informe']} {r['anio']}/{r['anio_comparacion']} "
                     f"{r['ambito_id']}: impresa {r['dif_pp']}, calculada {r['_calc']:.1f}"
                     for r in bad))

    print("\n4. Estrellas frente al valor p (nota: * p<0,10; ** p<0,05; *** p<0,01)")
    n_exact, borderline, anomalies, failures = 0, [], [], []
    for r in out_rows:
        key = (r["informe"], r["anio_comparacion"], r["ambito_id"])
        desc = (f"{r['informe']} {r['anio']}/{r['anio_comparacion']} {r['ambito_id']} "
                f"({r['ambito_pdf']}): dif {r['dif_pp']:+.1f}, P>t {r['p_valor']:.2f}, "
                f"«{r['significancia']}»")
        if r["significancia"] == stars_for(r["p_valor"]):
            n_exact += 1
        elif r["significancia"] in stars_compatible(r["p_valor"]):
            borderline.append(desc + f" (con P>t exacto serían «{stars_for(r['p_valor'])}»)")
        elif KNOWN_STAR_ANOMALIES.get(key) == (r["p_valor"], r["significancia"]):
            anomalies.append(desc + f" (con P>t serían «{stars_for(r['p_valor'])}»; "
                             "verificado en la imagen)")
        else:
            failures.append(desc + f" (se esperaba «{stars_for(r['p_valor'])}»)")
    record("Estrellas", not failures,
           f"{n_exact}/156 coinciden con P>t; {len(borderline)} casos límite compatibles con el "
           f"redondeo; {len(anomalies)} anomalías verificadas; {len(failures)} sin explicar")
    for label, items in (("Caso límite", borderline), ("Anomalía", anomalies),
                         ("Sin explicar", failures)):
        for d in items:
            print(f"      {label}: {d}")

    print("\n5. Cruce con config/pobreza_oficial_departamental_2016_2025.csv")
    with PRIOR_CSV.open(encoding="utf-8", newline="") as f:
        prior = [p for p in csv.DictReader(f) if p["indicador"] == "pobreza_total"]
    ctrl = {(p["ambito_id"], c): float(p[f"control_dif_2025_{c}"])
            for p in prior if p["anio"] == "2025" for c in (2024, 2019)}
    mine = {(r["ambito_id"], r["anio_comparacion"]): r["dif_pp"]
            for r in out_rows if r["informe"] == "2016-2025"}
    mism = [f"{k}: {mine.get(k)} vs {v}" for k, v in ctrl.items() if mine.get(k) != v]
    same_sign = sum((mine.get(k, 0) > 0) == (v > 0) and (mine.get(k, 0) < 0) == (v < 0)
                    for k, v in ctrl.items())
    record("control_dif_2025_* (con signo)", len(ctrl) == 52 and not mism,
           f"{52 - len(mism) if len(ctrl) == 52 else len(ctrl) - len(mism)}/{len(ctrl)} iguales; "
           f"signo igual en {same_sign}/{len(ctrl)} (el CSV previo guarda la diferencia en pp "
           "con signo)" + ("; " + "; ".join(mism) if mism else ""))
    val_mism = [f"{p['anio']} {p['ambito_id']}: {annual.get(('2016-2025', int(p['anio']), p['ambito_id']))}"
                f" vs {p['valor']}" for p in prior
                if annual.get(("2016-2025", int(p["anio"]), p["ambito_id"])) != float(p["valor"])]
    record("Cifras anuales 2016–2025 (asignación de filas)", len(prior) == 260 and not val_mism,
           f"{len(prior) - len(val_mism)}/{len(prior)} iguales a `valor`"
           + ("; " + "; ".join(val_mism[:5]) if val_mism else ""))

    print("\n6. Resumen: unidades con cambio significativo al 5 % (** o ***)")
    for rep in REPORTS:
        last = rep["first_year"] + 9
        for comp in (last - 1, BASE_YEAR):
            sel = [r for r in out_rows if r["informe"] == rep["informe"]
                   and r["anio_comparacion"] == comp]
            sig = [r for r in sel if r["significancia"] in ("**", "***")]
            up = sum(r["dif_pp"] > 0 for r in sig)
            p_lt = sum(r["p_valor"] < 0.05 for r in sel)
            print(f"  {last}/{comp}: {len(sig):2d}/26 (suben {up}, bajan {len(sig) - up}); "
                  f"con P>t impreso < 0,05: {p_lt}; al 10 % (cualquier estrella): "
                  f"{sum(bool(r['significancia']) for r in sel)}")

    if args.imagenes:
        args.imagenes.mkdir(parents=True, exist_ok=True)
        for rep in REPORTS:
            rows = by_report[rep["informe"]]
            halves = [[u for _, u in ROW_ORDER[:13]], [u for _, u in ROW_ORDER[13:]]]
            for k, sel in enumerate(halves, 1):
                out = args.imagenes / f"cuadro_iii1_{rep['informe']}_parte{k}.png"
                render_rows(rep, rows, sel, out)
                print(f"Imagen: {out}")

    n_fail = sum(not p for _, p, _ in results)
    if n_fail:
        print(f"\nControles: {len(results) - n_fail}/{len(results)} cuadran. "
              f"No se escribe {OUT_CSV.name}.")
        return 1
    fields = ["anio", "anio_comparacion", "ambito_id", "ambito_pdf", "dif_pp", "p_valor",
              "significancia", "cuadro", "pagina", "informe"]
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(fields)
        for r in out_rows:
            w.writerow([r["anio"], r["anio_comparacion"], r["ambito_id"], r["ambito_pdf"],
                        f"{r['dif_pp']:.1f}", f"{r['p_valor']:.2f}", r["significancia"],
                        r["cuadro"], r["pagina"], r["informe"]])
    print(f"\nEscrito {OUT_CSV.relative_to(ROOT).as_posix()} ({len(out_rows)} filas)")
    print(f"Controles: {len(results)}/{len(results)} cuadran")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
