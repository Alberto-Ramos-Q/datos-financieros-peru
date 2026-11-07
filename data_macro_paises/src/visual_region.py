"""Genera `outputs/peru_region.html`: informe «El Perú frente a la región».

Arma los tres bloques del informe (crecimiento, crédito y sector externo) con los módulos de
`src/informe_region/`, los normaliza, les agrega el periodo de cada dato y el corte de la
información, y los inyecta como JSON en la plantilla `src/plantillas/region.html`. El HTML
resultante es autocontenido (sin librerías externas) y se abre con doble clic.

Por cada bloque:
  1. llama a `informe_region.<id>.build(comparable_dir)`;
  2. si el módulo no existe o falla, lee `data/processed/informe_region/<id>.json`;
  3. si tampoco hay JSON, omite la pestaña con un aviso en consola (nunca en la página).

Uso:
    python visual_region.py                 # módulos, con respaldo en los JSON
    python visual_region.py --solo-json     # no corre los módulos: solo lee los JSON
    python visual_region.py --json-dir RUTA --salida RUTA   # para pruebas fuera del proyecto
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib
import json
import math
import re
import sys
import traceback
from collections import Counter
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_DIR / "src"
COMPARABLE_DIR = PROJECT_DIR / "data" / "processed" / "comparable"
BLOCK_JSON_DIR = PROJECT_DIR / "data" / "processed" / "informe_region"
TEMPLATE = SRC_DIR / "plantillas" / "region.html"
OUT = PROJECT_DIR / "outputs" / "peru_region.html"
PLACEHOLDER = "/*__DATA__*/null"

# Orden fijo de las pestañas: (id del módulo, nombre de la pestaña).
BLOCKS = [("crecimiento", "Crecimiento"), ("credito", "Crédito"), ("externo", "Externo y fiscal")]
FMTS = {"pct1", "pct2", "num1", "num0", "pp1"}
TIPOS = {"lineas", "barras", "barras_h", "dispersion"}
MES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "set", "oct", "nov", "dic"]
MES_LARGO = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
             "setiembre", "octubre", "noviembre", "diciembre"]
FREQ_WORDS = {"año": "A", "trimestre": "Q", "mes": "M"}
MONTH_NAMES = r"(enero|febrero|marzo|abril|mayo|junio|julio|agosto|setiembre|septiembre|octubre|noviembre|diciembre)"
MONTH_ABBR = r"\b(ene|feb|mar|abr|may|jun|jul|ago|set|sep|oct|nov|dic)-\d{4}\b"
# Lo que no debe aparecer nunca en la página publicada.
FORBIDDEN = [r"[A-Za-z]:\\", r"\.py\b", r"scratchpad", r"\bagentes?\b", r"/Users/", r"\\Users\\"]


def warn(msg: str) -> None:
    print(f"  [aviso] {msg}")


# ---------- Limpieza de tipos (numpy, NaN) ----------
def clean(obj):
    """Convierte a tipos JSON puros; NaN e infinitos pasan a None."""
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if hasattr(obj, "item") and not isinstance(obj, (str, bytes)):   # escalares de numpy
        try:
            obj = obj.item()
        except (ValueError, TypeError):
            pass
    if hasattr(obj, "isoformat"):   # fechas de pandas/datetime
        return obj.isoformat()[:10]
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


# ---------- Fechas y frecuencias ----------
def parse_date(s) -> dt.date | None:
    if not isinstance(s, str) or not re.match(r"^\d{4}-\d{2}-\d{2}", s):
        return None
    try:
        return dt.date.fromisoformat(s[:10])
    except ValueError:
        return None


def freq_from_dates(dates: list[dt.date]) -> str | None:
    """Frecuencia según la separación típica entre fechas consecutivas."""
    ds = sorted(set(dates))
    if len(ds) < 2:
        return None
    gaps = sorted((b - a).days for a, b in zip(ds, ds[1:]))
    med = gaps[len(gaps) // 2]
    if med <= 7:
        return "D"
    if med <= 45:
        return "M"
    if med <= 120:
        return "Q"
    return "A"


def freq_from_text(text: str) -> str | None:
    """Frecuencia según el texto (título, subtítulo, nota, etiqueta)."""
    t = (text or "").lower()
    m = re.search(r"últim[oa]s? (año|trimestre|mes)\b", t)
    if m:
        return FREQ_WORDS[m.group(1)]
    if re.search(r"trimestr|\b\d{4}-t[1-4]\b|\bt[1-4]\b", t):
        return "Q"
    if re.search(MONTH_NAMES, t) or re.search(MONTH_ABBR, t) or re.search(r"\bmes(es)?\b|mensual", t):
        return "M"
    if re.search(r"\baños?\b|\banual\b", t):
        return "A"
    return None


def freq_fallback(dates: list[dt.date]) -> str:
    """Sin más pistas: el 1 de enero indica un dato anual; cualquier otro mes, mensual."""
    return "A" if dates and all(d.month == 1 and d.day == 1 for d in dates) else "M"


def period_label(d: dt.date, freq: str) -> str:
    if freq == "A":
        return str(d.year)
    if freq == "Q":
        return f"{d.year}-T{(d.month - 1) // 3 + 1}"
    if freq == "D":
        return f"{d.day} {MES[d.month - 1]} {d.year}"
    return f"{MES[d.month - 1]}-{d.year}"


def period_end(d: dt.date, freq: str) -> dt.date:
    """Último día del periodo que empieza en d (las fechas marcan el inicio del periodo)."""
    if freq == "A":
        return dt.date(d.year, 12, 31)
    if freq == "D":
        return d
    months = 3 if freq == "Q" else 1
    k = d.year * 12 + d.month - 1 + months
    return dt.date(k // 12, k % 12 + 1, 1) - dt.timedelta(days=1)


# ---------- Carga de cada bloque ----------
def load_block(block_id: str, json_dir: Path, use_modules: bool) -> tuple[dict | None, str]:
    if use_modules:
        try:
            if str(SRC_DIR) not in sys.path:
                sys.path.insert(0, str(SRC_DIR))
            mod = importlib.import_module(f"informe_region.{block_id}")
            data = mod.build(COMPARABLE_DIR)
            if isinstance(data, dict):
                return data, "módulo"
            warn(f"{block_id}: build() no devolvió un diccionario; se usa el JSON.")
        except ModuleNotFoundError as e:
            warn(f"{block_id}: no se encontró el módulo ({e}); se usa el JSON.")
        except Exception:   # el módulo de otro bloque no debe tumbar el informe
            warn(f"{block_id}: el módulo falló; se usa el JSON. Detalle:")
            traceback.print_exc(limit=3)
    path = json_dir / f"{block_id}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8")), "json"
        except (OSError, json.JSONDecodeError) as e:
            warn(f"{block_id}: no se pudo leer {path.name} ({e}).")
    return None, ""


def normalize_kpis(kpis: list, block_id: str) -> tuple[list[dict], list[dt.date]]:
    out, ends = [], []
    for k in kpis or []:
        if not isinstance(k, dict) or k.get("val") is None or not k.get("lab"):
            warn(f"{block_id}: KPI sin valor u etiqueta omitido ({k.get('lab') if isinstance(k, dict) else k}).")
            continue
        fmt = k.get("fmt") if k.get("fmt") in FMTS else "num1"
        d = parse_date(k.get("fecha"))
        sub = str(k.get("sub") or "")
        item = {"lab": str(k["lab"]), "val": float(k["val"]), "fmt": fmt, "unit": str(k.get("unit") or ""), "sub": sub}
        if d:
            freq = FREQ_EXPLICIT.get(str(k.get("frecuencia") or "")) or freq_from_text(f"{k['lab']} {sub}") or freq_fallback([d])
            item["per"] = k.get("periodo") or period_label(d, freq)
            # El periodo solo se repite si el texto no lo trae ya (todas las subetiquetas citan el año).
            item["show_per"] = str(d.year) not in sub
            ends.append(period_end(d, freq))
        else:
            warn(f"{block_id}: KPI «{k['lab']}» sin fecha válida.")
        out.append(item)
    return out, ends


FREQ_EXPLICIT = {"anual": "A", "trimestral": "Q", "mensual": "M", "diaria": "D", "A": "A", "Q": "Q", "M": "M", "D": "D"}


REFERENCE_COUNTRIES = {"ESP", "USA"}


def normalize_chart(g: dict, block_id: str) -> tuple[dict | None, list[dt.date]]:
    gid = g.get("id") or "grafico"
    tipo = g.get("tipo")
    if tipo not in TIPOS:
        warn(f"{block_id}/{gid}: tipo de gráfico desconocido ({tipo}); se omite.")
        return None, []
    series, dates_all, per_series_freq = [], [], []
    for s in g.get("series") or []:
        pts = [p for p in (s.get("puntos") or []) if isinstance(p, (list, tuple)) and len(p) >= 2 and p[1] is not None]
        if tipo == "dispersion" and pts and not isinstance(pts[0][0], str):
            pts = [p for p in pts if p[0] is not None]
        if not pts:
            continue
        if isinstance(pts[0][0], str):
            pts = sorted(pts, key=lambda p: p[0])
        ds = [d for d in (parse_date(p[0]) for p in pts) if d]
        ds += [d for d in (parse_date(p[2]) for p in pts if len(p) > 2) if d]
        dates_all += ds
        f = freq_from_dates(ds)
        if f:
            per_series_freq.append(f)
        item = {"pais": str(s.get("pais") or ""), "nombre": str(s.get("nombre") or s.get("pais") or ""),
                "puntos": [list(p) for p in pts]}
        if s.get("corto"):   # nombre corto opcional para la etiqueta al final de la línea
            item["corto"] = str(s["corto"])
        # España y EE. UU. son referencia: no entran en medianas ni puestos. En las barras se rotulan
        # siempre así, para que no se lean como parte del orden de la región.
        if tipo in ("barras", "barras_h") and item["pais"] in REFERENCE_COUNTRIES \
                and "referencia" not in item["nombre"]:
            item["nombre"] += " (referencia)"
        series.append(item)
    if not series:
        warn(f"{block_id}/{gid}: sin series con datos; se omite.")
        return None, []
    freq = FREQ_EXPLICIT.get(str(g.get("frecuencia") or ""))
    if not freq and per_series_freq:
        freq = Counter(per_series_freq).most_common(1)[0][0]
    if not freq:
        freq = (freq_from_text(f"{g.get('titulo', '')} {g.get('subtitulo', '')}")
                or freq_from_text(g.get("nota", "")) or freq_fallback(dates_all))
    out = {k: v for k, v in g.items() if k not in ("series",)}
    out.update({"id": str(gid), "tipo": tipo, "titulo": str(g.get("titulo") or ""),
                "subtitulo": str(g.get("subtitulo") or ""), "unidad": str(g.get("unidad") or ""),
                "nota": str(g.get("nota") or ""), "fuente": str(g.get("fuente") or ""),
                "frec": freq, "series": series})
    return out, [period_end(d, freq) for d in dates_all]


def normalize_block(raw: dict, block_id: str, tab_name: str) -> dict:
    raw = clean(raw)
    kpis, ends = normalize_kpis(raw.get("kpis"), block_id)
    charts = []
    for g in raw.get("graficos") or []:
        c, e = normalize_chart(g, block_id)
        if c:
            charts.append(c)
            ends += e
    tables = []
    for t in raw.get("tablas") or []:
        if not t.get("columnas") or not t.get("filas"):
            warn(f"{block_id}: tabla «{t.get('titulo', t.get('id'))}» vacía; se omite.")
            continue
        tables.append({"id": str(t.get("id") or f"t{len(tables)}"), "titulo": str(t.get("titulo") or ""),
                       "columnas": [str(c) for c in t["columnas"]], "filas": t["filas"],
                       "nota": str(t.get("nota") or "")})
    corte = max(ends) if ends else None
    return {"id": block_id, "tab": tab_name, "titulo": str(raw.get("titulo") or tab_name),
            "resumen": [str(x) for x in raw.get("resumen") or []], "kpis": kpis, "graficos": charts,
            "tablas": tables, "advertencias": [str(x) for x in raw.get("advertencias") or []],
            "corte": corte.isoformat() if corte else None}


def unify_pct(obj):
    """Porcentaje pegado al número, como en el resto de la serie de tableros: «2,6 %» → «2,6%»."""
    if isinstance(obj, str):
        return re.sub(r"(\d)[ \u00a0\u202f]%", r"\1%", obj)
    if isinstance(obj, list):
        return [unify_pct(v) for v in obj]
    if isinstance(obj, dict):
        return {k: unify_pct(v) for k, v in obj.items()}
    return obj


def long_month(d: dt.date) -> str:
    return f"{MES_LARGO[d.month - 1]} de {d.year}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Genera el informe «El Perú frente a la región».")
    ap.add_argument("--solo-json", action="store_true", help="no correr los módulos; leer solo los JSON")
    ap.add_argument("--json-dir", type=Path, default=BLOCK_JSON_DIR, help="carpeta con <bloque>.json")
    ap.add_argument("--salida", type=Path, default=OUT, help="HTML de salida")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):   # consola de Windows: que las tildes no fallen
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("Informe «El Perú frente a la región»")
    blocks = []
    for block_id, tab_name in BLOCKS:
        raw, origin = load_block(block_id, args.json_dir, not args.solo_json)
        if raw is None:
            warn(f"{block_id}: sin módulo ni JSON; se omite la pestaña «{tab_name}».")
            continue
        b = normalize_block(raw, block_id, tab_name)
        print(f"  {tab_name}: {origin}, {len(b['kpis'])} indicadores, {len(b['graficos'])} gráficos, "
              f"{len(b['tablas'])} tablas, datos hasta {b['corte']}")
        blocks.append(b)
    if not blocks:
        print("  [error] No hay ningún bloque con datos; no se genera el HTML.")
        return 1

    cortes = [dt.date.fromisoformat(b["corte"]) for b in blocks if b["corte"]]
    corte = max(cortes) if cortes else None
    today = dt.date.today()
    data = {"generado": today.isoformat(), "corte": corte.isoformat() if corte else None,
            "corte_lab": long_month(corte) if corte else None, "bloques": unify_pct(blocks)}

    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("</", "<\\/")
    for pat in FORBIDDEN:
        hits = sorted(set(m.group(0) for m in re.finditer(pat, payload)))
        if hits:
            warn(f"los textos de los bloques contienen algo que no debería publicarse ({pat}): {hits[:5]}")
    html = TEMPLATE.read_text(encoding="utf-8")
    if PLACEHOLDER not in html:
        print("  [error] La plantilla no tiene el marcador de datos.")
        return 1
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(html.replace(PLACEHOLDER, payload), encoding="utf-8")
    print(f"  Escrito {args.salida.name} ({args.salida.stat().st_size / 1024:.0f} KB); "
          f"corte {data['corte_lab']}; generado {today.isoformat()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
