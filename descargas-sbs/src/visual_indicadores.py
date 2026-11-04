"""Genera `outputs/indicadores_ssff.html`: tablero público de indicadores del sistema financiero.

Lee lo que calcula `indicadores_datos.py` (correrlo antes):
- `data/processed/indicadores/indicadores_ambito_mes.parquet`: tabla larga ámbito × mes × indicador;
- `data/processed/indicadores/ambitos.csv`: nombre, subsistema, historial de subsistema y si la entidad opera;
- `config/indicadores.csv`: catálogo (etiqueta, unidad, decimales, sentido, frecuencia, rezago, fórmula corta y
  detallada, cuadros SBS, desde y primer mes del sistema, cobertura, notas);
- `data/_control/indicadores_validacion.csv`: comparación con lo publicado por la SBS → `valid` y `validNote`;
- `data/processed/indicadores/repeticiones.json`: entidad-mes en que la SBS repite las cifras de otro mes (`rep`:
  [mes, entidad, mes repetido, alcance «fila» / «ranking», motivo]) y los huecos que dejan en cada indicador de la
  entidad (`repGap`: {entidad: {indicador: [[desde, hasta, n.º de rep]]}}, también los de 12 meses). La página
  muestra en tablas, fichas y KPI el último dato válido con su mes y el motivo, y en los gráficos el motivo del hueco;
y además:
- `data/processed/clasificaciones_informes.parquet`: última clasificación vigente de cada clasificadora por
  entidad (regla de `leer_clasificadoras.py`: un informe rige desde el mes de su comité —o abril/octubre si no se
  leyó— por 12 meses o hasta el siguiente de la misma clasificadora; los preliminares ya vienen descartados si
  hay final);
- `data/processed/clasificaciones.parquet`: peor categoría vigente por mes (`cl_peor_num`) → `ratingHist`;
- `config/indicadores_perfil.csv` (si existe): giro principal de cada entidad con su fuente → `perfil`.

Arma el JSON con el contrato de `docs/tablero_indicadores/diseno.md`, lo comprime como `visual_eeff.encode`
(gzip + base64) y lo inyecta en `src/plantillas/indicadores.html` en el marcador `/*__DATA__*/null`. Escribe
`outputs/indicadores_ssff.html` y `outputs/indicadores_ssff_artifact.html` (sin <html>/<head>/<body>). Si la
plantilla no existe, escribe solo `data/processed/indicadores/payload_muestra.json` (sin comprimir).

Uso:
    python src/visual_indicadores.py [--muestra]   (--muestra: escribe también el JSON sin comprimir)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from visual_mora import (PROJECT_DIR, SUBSYSTEMS, artifact_version, debtor_error_notes, month_key,  # noqa: E402
                         month_range)
from visual_solvencia import LIMITS  # noqa: E402
from visual_eeff import encode  # noqa: E402
from leer_clasificadoras import GRADES, VIGENCIA_MESES, add_months, known_month  # noqa: E402
from indicadores_datos import (GROUPS, OUT_DIR, OUT_LONG, OUT_REPEATS, OUT_SCOPES, CATALOG_CSV, CONTROL_CSV,  # noqa: E402
                               CUADROS)

TEMPLATE = PROJECT_DIR / "src" / "plantillas" / "indicadores.html"
OUT = PROJECT_DIR / "outputs" / "indicadores_ssff.html"
OUT_ARTIFACT = PROJECT_DIR / "outputs" / "indicadores_ssff_artifact.html"
SAMPLE = OUT_DIR / "payload_muestra.json"
PERFIL = PROJECT_DIR / "config" / "indicadores_perfil.csv"
RATINGS = PROJECT_DIR / "data" / "processed" / "clasificaciones_informes.parquet"
RATING_PANEL = PROJECT_DIR / "data" / "processed" / "clasificaciones.parquet"
PLACEHOLDER = "/*__DATA__*/null"
MAX_MB = 6.0
# Columnas del perfil que pasan a la página (pública). Las de trabajo (confianza, notas, fecha de revisión, nombre,
# subsistema) se quedan fuera.
PERFIL_FIELDS = ["giro", "fuente", "url_fuente", "segmento_principal", "cartera_mix", "grupo_controlador"]

# Escala de la página: Res. SBS 18400-2010, art. 17 (A a E; los signos + y − solo de A a D, la E no lleva signo):
# 13 categorías. `GRADES` de leer_clasificadoras numera 15 (incluye E+ y E-, que la norma no tiene); se renumera
# el historial a esta escala y falla si aparece una categoría fuera de ella.
SBS_SCALE = [g for g in GRADES if g[0] != "E"] + ["E"]
TO_SBS_NUM = {GRADES.index(g) + 1: k + 1 for k, g in enumerate(SBS_SCALE)}

AGENCY = {
    "moodys-local": "Moody's Local Perú (antes Equilibrium)",
    "apoyo": "Apoyo & Asociados (Fitch)",
    "pcr": "PCR (Pacific Credit Rating)",
    "microrate": "MicroRate",
}


# Nombres visibles. El sistema se rotula «Sistema (5 subsistemas)» y no «Sistema financiero»: no es el sistema
# financiero de la SBS (no incluye la banca estatal ni las cooperativas). Se fija aquí para no cambiar `ambitos.csv`.
SYSTEM_NAME = "Sistema (5 subsistemas)"
# Etiqueta corta de los subsistemas en encabezados y rótulos de gráficos: sin las siglas «CMAC», «CRAC» y «EC», que
# junto a «CMAC Arequipa» o «CRAC Los Andes» parecen otra entidad (`visual_mora.SUBSYSTEMS` lo comparten otros
# tableros, por eso se sobrescribe solo en este).
SUB_SHORT = {"cajas-municipales": "Cajas mun.", "cajas-rurales": "Cajas rur.", "empresas-credito": "Emp. créd."}

# Cuadros SBS legibles (campo `cu`). `cuadros_sbs` del catálogo trae «Tema (código banca, financieras, cajas
# municipales, cajas rurales, empresas de créditos)»; aquí cada código lleva su subsistema, se omiten los de
# subsistemas sin el indicador y se agregan los cuadros que el cálculo usa además del principal.
SUB_NAMES = [l.lower() for _, l, _ in SUBSYSTEMS]
CU_EXTRA = {
    "cred_g": [("sit", "saldo total, del cuadro de créditos por tipo y situación")],
    "mora_aj": [("sit", "créditos y créditos atrasados, del cuadro de créditos por tipo y situación")],
    "castigos": [("sit", "créditos promedio, del cuadro de créditos por tipo y situación")],
    "rcg": [("epe", "patrimonio efectivo desde junio de 2023, del cuadro de estructura del patrimonio efectivo")],
    "colchon": [("epe", "patrimonio efectivo desde junio de 2023, del cuadro de estructura del patrimonio efectivo")],
    "pg_pe": [("rcg", "patrimonio efectivo, del cuadro del ratio de capital global"),
              ("epe", "desde junio de 2023, del cuadro de estructura del patrimonio efectivo")],
    "cred_dep": [("eeff", "depósitos, de los estados financieros")],
}

# Validación (`D.valid`): se excluyen los indicadores cuya comparación con la SBS no valida el cálculo.
# - Difieren por diseño del indicador publicado (lo dicen sus notas del catálogo): eficiencia (banca y financieras,
#   valores acumulados en el año), gastos administrativos / créditos (la SBS divide entre directos e indirectos) y
#   mora ajustada por castigos (la SBS suma las transferencias de cartera atrasada).
# - El RCL no se calcula: el tablero usa el publicado, así que la comparación es solo un control de lectura.
# Cobertura de cartera atrasada y apalancamiento sí se incluyen: solo el BCP y la banca difieren (sucursales).
VALID_DESIGN = ["efic", "gadm_cred", "mora_aj"]
VALID_READ = ["rcl"]
VALID_BRANCHES = ["cob", "lev"]
VALID_LEVELS = ["entidad", "subsistema"]
VALID_ART = {"efic": "la", "gadm_cred": "los", "mora_aj": "la", "rcl": "el", "cob": "la", "lev": "el"}
VALID_QUAL = {"efic": " (en la banca y las financieras)"}


def lc_label(label: str) -> str:
    """Etiqueta en mitad de frase: inicial en minúscula salvo que empiece por una sigla (ROE, RCL)."""
    return label if re.match(r"^[A-ZÁÉÍÓÚÑ]{2,}\b", label) else label[:1].lower() + label[1:]


def list_y(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " y " + items[-1]


def readable_cuadros(raw: str, by_sub: str) -> tuple[str, str]:
    """(tema, «código (subsistema), …») desde «Tema (B-…, …)[; sistema: …]» del catálogo."""
    m = re.match(r"^(.*?) \(([^)]*)\)(.*)$", raw)
    if not m:
        return raw, ""
    theme, codes, rest = m.group(1).replace(" en ME", " en moneda extranjera"), m.group(2).split(", "), m.group(3)
    have = [not v.endswith("—") for v in by_sub.split("; ")] if by_sub else []
    keep = [i for i in range(len(codes)) if not have or not any(have) or (i < len(have) and have[i])]
    txt = list_y([f"{codes[i]} ({SUB_NAMES[i]})" for i in keep])
    if rest.startswith("; sistema: SF-2103"):
        txt += "; sistema: SF-2103 (deudores únicos de las empresas de operaciones múltiples)"
    return theme, txt


def build_cu(r) -> str | None:
    if not r.cuadros_sbs:
        return None
    theme, txt = readable_cuadros(r.cuadros_sbs, r.cobertura_por_subsistema)
    parts = [f"{theme}: {txt}" if txt else theme]
    for key, lead in CU_EXTRA.get(r.clave, []):
        parts.append(f"{lead}: {readable_cuadros(CUADROS[key], r.cobertura_por_subsistema)[1]}")
    return "; ".join(parts)


def load_inputs():
    long = pd.read_parquet(OUT_LONG)
    cat = pd.read_csv(CATALOG_CSV, dtype=str, keep_default_na=False)
    meta = pd.read_csv(OUT_SCOPES, dtype=str, keep_default_na=False)
    return long, cat, meta


def build_ind(cat: pd.DataFrame) -> list[dict]:
    out = []
    for r in cat.itertuples():
        sd = r.sistema_desde if r.sistema_desde not in ("", "—") and r.sistema_desde != r.desde else None
        out.append({"k": r.clave, "g": r.grupo, "l": r.etiqueta, "u": r.unidad, "d": int(r.decimales),
                    "s": int(r.sentido), "q": r.frecuencia, "lag": int(r.lag), "f": r.formula_corta,
                    "fd": r.formula_detallada or None, "cu": build_cu(r), "sd": sd,
                    "desde": r.desde or None, "cob": r.cobertura, "nota": r.notas})
    return out


def build_valid(cat: pd.DataFrame) -> tuple[list[dict], str | None]:
    """Resumen de `data/_control/indicadores_validacion.csv` por indicador y nivel: % de casos (entidad-mes o
    subsistema-mes) a la tolerancia o menos del publicado por la SBS, ponderado por n sobre tramos y subsistemas."""
    if not CONTROL_CSV.exists():
        print("  AVISO: no existe el control de validación; D.valid vacío")
        return [], None
    v = pd.read_csv(CONTROL_CSV)
    labels = dict(zip(cat["clave"], cat["etiqueta"]))
    units = dict(zip(cat["clave"], cat["unidad"]))
    v = v[~v["indicador"].isin(VALID_DESIGN + VALID_READ) & v["nivel"].isin(VALID_LEVELS)]
    v = v.assign(ok=v["n"] * v["pct_dentro"] / 100)
    g = v.groupby(["indicador", "nivel"]).agg(n=("n", "sum"), ok=("ok", "sum"), tol=("tolerancia", "first"))
    order = {k: i for i, k in enumerate(cat["clave"])}
    rows = sorted(g.reset_index().itertuples(), key=lambda r: (order.get(r.indicador, 999), VALID_LEVELS.index(r.nivel)))
    out = [{"k": r.indicador, "label": labels.get(r.indicador, r.indicador), "nivel": r.nivel,
            "tol": f"{r.tol:g} " + ("veces" if units.get(r.indicador) == "veces" else "pp"),
            "pct": round(100 * r.ok / r.n, 1), "n": int(r.n)} for r in rows]
    def lab(ks):   # «la eficiencia (en la banca y las financieras), los gastos … y la mora …», con las etiquetas
        return list_y([f"{VALID_ART[k]} {lc_label(labels[k])}{VALID_QUAL.get(k, '')}" for k in ks if k in labels])
    note = (f"No se incluyen, porque difieren por diseño del indicador que publica la SBS (ver sus notas), "
            f"{lab(VALID_DESIGN)}. Tampoco {lab(VALID_READ)}, que se toma tal como lo publica la SBS. En "
            f"{lab(VALID_BRANCHES)}, el BCP y la banca múltiple difieren por diseño, porque la SBS los calcula con "
            "las sucursales en el exterior; esos casos sí entran en las cifras.")
    return out, note


def scope_block(x: pd.DataFrame, pos: dict, dec: dict) -> dict:
    """{a, V} de un ámbito: cada arreglo empieza en el índice `a` (primer mes con algún dato del ámbito) y llega
    hasta el último mes con dato de ESE indicador (la página completa con null hasta el final)."""
    a = pos[int(x["periodo"].min())]
    V = {}
    for k, g in x.groupby("indicador", sort=False):
        idx = g["periodo"].map(pos).to_numpy()
        arr = [None] * (int(idx.max()) - a + 1)
        d = dec[k] + 1
        for i, v in zip(idx, g["valor"].to_numpy()):
            arr[int(i) - a] = round(float(v), d) if d > 0 else int(round(float(v)))
        V[k] = arr
    return {"a": a, "V": V}


def build_ratings(entities: set[str], months: list[int]) -> tuple[dict, dict]:
    """Última clasificación vigente de cada clasificadora y la peor categoría por mes."""
    rep = pd.read_parquet(RATINGS)
    rep = rep[rep["rating"].notna() & rep["id_entidad"].isin(entities)].copy()
    rep["desde"] = rep.apply(known_month, axis=1)
    rep = rep.sort_values(["id_entidad", "clasificadora", "desde", "num_archivo"])
    rep = rep.drop_duplicates(["id_entidad", "clasificadora", "desde"], keep="last")
    today = int(dt.date.today().strftime("%Y%m"))
    ratings: dict[str, list] = {}
    for (ent, ag), g in rep.groupby(["id_entidad", "clasificadora"]):
        g = g[g["desde"] <= today]
        if g.empty:
            continue
        r = g.iloc[-1]
        if add_months(int(r["desde"]), VIGENCIA_MESES - 1) < today:   # vencido: no se renovó en 12 meses
            continue
        fc = r["fecha_comite"]
        ratings.setdefault(ent, []).append({
            "c": AGENCY.get(ag, ag), "r": r["rating"], "p": r["perspectiva"] if isinstance(r["perspectiva"], str) else None,
            "fc": fc.strftime("%Y-%m-%d") if pd.notna(fc) else None, "inf": month_key(int(r["periodo_informacion"])),
        })
    for ent in ratings:   # la más reciente primero
        ratings[ent].sort(key=lambda z: (z["fc"] or "", z["inf"]), reverse=True)
    panel = pd.read_parquet(RATING_PANEL, columns=["periodo", "id_entidad", "cl_peor_num"])
    pos = {m: i for i, m in enumerate(months)}
    panel = panel[panel["id_entidad"].isin(entities) & panel["periodo"].isin(pos)]
    hist = {}
    for ent, g in panel.groupby("id_entidad"):
        idx = g["periodo"].map(pos)
        a, b = int(idx.min()), int(idx.max())
        v = [None] * (b - a + 1)
        for i, x in zip(idx, g["cl_peor_num"]):
            v[int(i) - a] = None if pd.isna(x) else TO_SBS_NUM[int(x)]
        hist[ent] = {"a": a, "v": v}
    return ratings, hist


def build_perfil(entities: set[str]) -> dict:
    """Giro principal desde `config/indicadores_perfil.csv` (lo escribe otro paso); vacío si aún no existe."""
    if not PERFIL.exists():
        print("  AVISO: no existe config/indicadores_perfil.csv; perfil vacío")
        return {}
    p = pd.read_csv(PERFIL, dtype=str, keep_default_na=False)
    out = {}
    for r in p.to_dict("records"):
        ent = r.pop("id_entidad", "")
        if ent not in entities:
            continue
        rec = {k: v for k, v in r.items() if k in PERFIL_FIELDS and v not in ("", None)}
        if rec.get("giro"):
            out[ent] = rec
    missing = sorted(entities - set(out))
    print(f"  Perfil: {len(out)} entidades con giro; {len(missing)} sin perfil")
    return out


def build_data() -> dict:
    long, cat, meta = load_inputs()
    months = month_range(int(long["periodo"].min()), int(long["periodo"].max()))
    pos = {m: i for i, m in enumerate(months)}
    dec = dict(zip(cat["clave"], cat["decimales"].astype(int)))
    order = list(cat["clave"])
    long = long.assign(_o=long["indicador"].map({k: i for i, k in enumerate(order)})).sort_values(["ambito", "_o", "periodo"])

    sys_rows = long[long["ambito"] == "sistema"]
    sys_hasta = {k: month_key(int(g["periodo"].max())) for k, g in sys_rows.groupby("indicador")}

    scopes: dict[str, dict] = {}
    groups = {k: g for k, g in long.groupby("ambito", sort=False)}
    scopes["sistema"] = {"n": SYSTEM_NAME, "t": "sis", "s": None, **scope_block(groups["sistema"], pos, dec)}
    for sub, label, short in SUBSYSTEMS:
        scopes[sub] = {"n": label, "t": "sub", "s": sub, **scope_block(groups[sub], pos, dec)}
    ents = meta[meta["tipo"] == "ent"].copy()
    ents["cred"] = pd.to_numeric(ents["cred_ultimo"], errors="coerce").fillna(-1)
    ents["act_b"] = ents["activa"].eq("True")
    sub_order = {s: i for i, (s, _, _) in enumerate(SUBSYSTEMS)}
    ents = ents.assign(_s=ents["subsistema"].map(sub_order)).sort_values(["_s", "act_b", "cred", "nombre"],
                                                                         ascending=[True, False, False, True])
    entities = []
    for r in ents.itertuples():
        if r.ambito not in groups:
            continue
        scopes[r.ambito] = {"n": r.nombre, "t": "ent", "s": r.subsistema, "sh": json.loads(r.historial),
                            "act": bool(r.act_b), **scope_block(groups[r.ambito], pos, dec)}
        entities.append(r.ambito)

    ratings, hist = build_ratings(set(entities), months)
    lg = [next((row[1] for row in reversed(LIMITS) if mm >= row[0]), None) for mm in months]
    hasta = month_key(int(long["periodo"].max()))
    valid, valid_note = build_valid(cat)
    # Deudores con errores de origen (errores_origen.py): esos subsistema-mes quedan sin `deud` en los datos; la
    # página explica el hueco en la nota de la celda y en el tooltip de los gráficos (mismo formato que mora_ssff).
    deu_err, deu_tot_err = debtor_error_notes()
    # Cifras repetidas de otro mes (errores_origen.RANKING_REPEATS): las series de entidad ya vienen sin esos valores.
    reps = json.loads(OUT_REPEATS.read_text(encoding="utf-8")) if OUT_REPEATS.exists() else {"rep": [], "repGap": {}}
    rep_gap = {e: g for e, g in reps["repGap"].items() if e in scopes}
    return {
        "generado": dt.date.today().isoformat(),
        "months": [month_key(mm) for mm in months],
        "hasta": hasta,
        "sysHasta": sys_hasta,
        "groups": [{"k": k, "l": l} for k, l in GROUPS],
        "ind": build_ind(cat),
        "valid": valid,
        "validNote": valid_note,
        "subs": [{"k": k, "l": l, "c": SUB_SHORT.get(k, c)} for k, l, c in SUBSYSTEMS],
        "scopes": scopes,
        "entities": entities,
        "perfil": build_perfil(set(entities)),
        "ratings": ratings,
        "ratingHist": hist,
        "ratingScale": SBS_SCALE,
        "limits": {"lg": lg},
        "deuErr": deu_err,
        "deuTotErr": deu_tot_err,
        "rep": [r for r in reps["rep"] if r[1] in scopes],
        "repGap": rep_gap,
    }


def check(data: dict) -> None:
    """Controles del payload: contrato, alineación y cifras del último mes."""
    N = len(data["months"])
    problems = []
    keys = {i["k"] for i in data["ind"]}
    for key, sc in data["scopes"].items():
        for k, v in sc["V"].items():
            if k not in keys:
                problems.append(f"{key}: indicador {k} fuera del catálogo")
            if sc["a"] + len(v) > N:
                problems.append(f"{key}/{k}: arreglo más largo que months")
    for e in data["entities"]:
        sc = data["scopes"][e]
        if sc["sh"] and sc["sh"][-1][1] != sc["s"]:
            problems.append(f"{e}: s distinto del último tramo de sh")
    print(f"  Contrato: {len(data['scopes'])} ámbitos ({len(data['entities'])} entidades, "
          f"{sum(data['scopes'][e]['act'] for e in data['entities'])} activas), {len(data['ind'])} indicadores, "
          f"{len(data['ratings'])} entidades con clasificación vigente, {len(data['ratingHist'])} con historial; "
          + ("sin problemas" if not problems else f"{len(problems)} problemas: {problems[:5]}"))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--muestra", action="store_true", help="escribe también el JSON sin comprimir")
    args = ap.parse_args()
    print("Armando el tablero de indicadores...")
    data = build_data()
    check(data)
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    lit = encode(data)
    mb_raw, mb = len(raw.encode("utf-8")) / 1e6, len(lit) / 1e6
    print(f"  JSON {mb_raw:.1f} MB; comprimido (gzip + base64) {mb:.2f} MB")
    if mb > MAX_MB:
        print(f"  AVISO: el payload comprimido pasa de {MAX_MB} MB")
    if args.muestra or not TEMPLATE.exists():
        SAMPLE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        print(f"  Escrito {SAMPLE.relative_to(PROJECT_DIR)}")
    if not TEMPLATE.exists():
        print(f"  La plantilla {TEMPLATE.relative_to(PROJECT_DIR)} aún no existe: no se genera la página")
        return 0
    template = TEMPLATE.read_text(encoding="utf-8")
    if PLACEHOLDER not in template:
        print(f"ERROR: la plantilla no tiene el marcador {PLACEHOLDER}")
        return 1
    html = template.replace(PLACEHOLDER, lit, 1)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    OUT_ARTIFACT.write_text(artifact_version(html), encoding="utf-8")
    print(f"  {data['months'][0]} a {data['hasta']}; página {len(html.encode('utf-8')) / 1e6:.2f} MB")
    print(f"  Escrito {OUT.relative_to(PROJECT_DIR)} y {OUT_ARTIFACT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
