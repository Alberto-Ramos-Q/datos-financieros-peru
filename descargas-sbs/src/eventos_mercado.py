"""Eventos que cambian la estructura del mercado de crédito (2010-07 → último mes), para el tablero de concentración.

Cruza los eventos curados (`config/entidades/entidad_evento.csv`) con lo que muestran los cuadros SBS y escribe
`config/entidades/eventos_mercado.csv`: una fila por evento y subsistema afectado (dos filas si el evento toca dos
subsistemas), con el primer mes en que el cambio se ve en los cuadros.

Datos que lee:
- `data/processed/boletin/ranking-creditos-depositos-patrimonio.parquet`: créditos directos, depósitos totales y
  patrimonio por entidad y mes (filas `es_total == False`).
- `data/processed/boletin/deudores-tipo-credito.parquet`: deudores por entidad (apertura `total`), para contrastar y
  para fechar ingresos que el ranking trae en ceros (CRAC Del Centro 2014-09).
- `config/entidades/entidad_evento.csv`, `entidad_vigencia.csv` y `entidad.csv` (vía `entidades.Maestro`).

Reglas:
- Una entidad «figura» en un subsistema y mes si el ranking trae créditos, depósitos o patrimonio > 0. Así no
  cuentan las filas en ceros de entidades que ya salieron (la SBS sigue listando algunas) y sí cuenta una entidad
  que ya opera pero aún no tiene créditos (Bank of China 2020-07 → 2021-06).
- `periodo` (AAAAMM) = primer mes en que el cambio se ve en los cuadros:
  ingreso → primer mes en que figura (en el ranking o en deudores); salida e intervención → mes siguiente al último en que figura; absorción →
  mes siguiente al último con créditos > 0 de la absorbida (o el mes de la resolución si la absorbida no está en
  los cuadros, p. ej. empresas de factoring); cambio de subsistema → primer mes en el subsistema nuevo;
  transferencia de cartera → mes con la mayor caída de créditos del cedente entre el mes de la resolución y dos
  meses después.
- `id_entidad`: la que entra, sale, es intervenida o cambia de subsistema; en absorción y transferencia de
  cartera, la que recibe. `id_entidad_relacionada`: la absorbida o cedente.
- Una salida o intervención cuyo bloque asume otra entidad (Señor de Luren, Sullana, Credinka 2024) queda en la
  fila de absorción, con las resoluciones de ambas; intervención y disolución del mismo mes, en una fila
  `intervencion`. Las adjudicaciones de bloque suman su resolución a la absorción correspondiente.

Validación (se imprime): todo cambio en el conjunto de entidades de cada subsistema (aparece / desaparece /
cambia de subsistema) debe tener una fila en ±1 mes; saltos de participación en créditos > `--umbral` pp sin
evento (si los créditos de la propia entidad varían > 10 % en el mes, el evento tiene que ser suyo; si no, el salto
es efecto del denominador y basta un evento del subsistema); los saltos revisados sin evento oficial están en
`REVIEWED_JUMPS`; desfases > 1 mes entre la fecha del evento y su reflejo en los cuadros; eventos aún sin reflejo;
diferencias con deudores; subsistema de los datos vs. `entidad_vigencia.csv`. Sale con código 1 si falta algún
evento, si hay un salto sin evento ni revisión o si alguna etiqueta pasa de 60 caracteres.

Uso:
    python src/eventos_mercado.py                  # valida y escribe config/entidades/eventos_mercado.csv
    python src/eventos_mercado.py --umbral 3 --solo-validar
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))
from entidades import Maestro  # noqa: E402
from errores_origen import drop_debtor_source_errors  # noqa: E402

CONFIG_DIR = PROJECT_DIR / "config" / "entidades"
EVENTS_CSV = CONFIG_DIR / "entidad_evento.csv"
OUT_CSV = CONFIG_DIR / "eventos_mercado.csv"
BOLETIN = PROJECT_DIR / "data" / "processed" / "boletin"
RANKING = BOLETIN / "ranking-creditos-depositos-patrimonio.parquet"
DEUDORES = BOLETIN / "deudores-tipo-credito.parquet"

START_PERIOD = 201007
SUBSYSTEMS = ["banca-multiple", "empresas-financieras", "cajas-municipales", "cajas-rurales", "empresas-credito"]
SIZE_VARS = ["creditos_directos", "depositos_totales", "patrimonio"]
OUT_COLUMNS = ["periodo", "subsistema", "id_entidad", "id_entidad_relacionada", "tipo", "etiqueta_corta",
               "resolucion", "fuente", "confianza"]
MAX_LABEL = 60
OWN_CHANGE = 0.10   # variación mensual de créditos de la entidad a partir de la cual un salto exige evento propio
CONFIDENCE_RANK = {"alta": 2, "media": 1, "baja": 0}
# Si dos eventos caen en el mismo mes, subsistema y entidad, queda uno (el de mayor prioridad) con las
# resoluciones y fuentes de ambos.
TYPE_PRIORITY = ["absorcion", "fusion", "transferencia_cartera", "intervencion", "cambio_subsistema", "ingreso",
                 "salida"]
SUBSYSTEM_NOUN = {"banca-multiple": "banco", "empresas-financieras": "financiera", "cajas-municipales": "caja municipal",
                  "cajas-rurales": "caja rural", "empresas-credito": "empresa de créditos"}

# Etiquetas (≤ 60 caracteres) por (tipo, id_entidad, id_entidad_relacionada). Un evento nuevo sin etiqueta aquí
# recibe una genérica armada con el nombre vigente (ver `default_label`).
LABELS = {
    ("ingreso", "mitsui-auto-finance", ""): "Mitsui Masa Leasing pasa a financiera (Mitsui Auto Finance)",
    ("ingreso", "crac-incasur", ""): "Ingresa CRAC Incasur",
    ("ingreso", "inversiones-la-cruz", ""): "Ingresa Edpyme Inversiones La Cruz",
    ("ingreso", "crac-cencosud-scotia", ""): "Ingresa Banco Cencosud",
    ("ingreso", "icbc-peru", ""): "Ingresa ICBC Perú Bank",
    ("ingreso", "bbva-consumer-finance", ""): "Ingresa BBVA Consumer Finance Edpyme",
    ("ingreso", "edpyme-gmg-servicios-peru", ""): "Ingresa Edpyme GMG Servicios Perú",
    ("ingreso", "crac-del-centro", ""): "Ingresa CRAC Del Centro",
    ("ingreso", "santander-consumo", ""): "Ingresa Edpyme Santander Consumo Perú",
    ("ingreso", "bank-of-china-peru", ""): "Ingresa Bank of China (Perú)",
    ("ingreso", "total-servicios-financieros", ""): "Leasing Total pasa a EDPYME (TOTAL Serv. Financieros)",
    ("ingreso", "bci-peru", ""): "Ingresa Banco BCI Perú",
    ("ingreso", "volvo-finance", ""): "Volvo Leasing pasa a empresa de créditos (Volvo Finance)",
    ("ingreso", "surgir", ""): "Ingresa Financiera Surgir",
    ("salida", "caja-pisco", ""): "SBS disuelve y liquida CMAC Pisco",
    ("salida", "edpyme-credijet-del-peru", ""): "Edpyme Credijet pasa a emisora de dinero electrónico",
    ("salida", "deutsche-bank-peru", ""): "Deutsche Bank Perú entra en liquidación",
    ("salida", "edpyme-gmg-servicios-peru", ""): "Edpyme GMG se disuelve (voluntaria)",
    ("salida", "edpyme-progreso", ""): "Edpyme Progreso deja de ser supervisada",
    ("salida", "caja-sipan", ""): "CRAC Sipán se disuelve (voluntaria)",
    ("salida", "bbva-consumer-finance", ""): "BBVA Consumer Finance se disuelve (voluntaria)",
    ("salida", "credivision", ""): "Edpyme Credivisión deja de ser supervisada",
    ("salida", "amerika-financiera", ""): "Amérika Financiera se disuelve (voluntaria)",
    ("salida", "acceso-crediticio", ""): "SBS revoca la licencia de Acceso Crediticio",
    ("salida", "inversiones-la-cruz", ""): "Inversiones La Cruz deja de ser supervisada",
    ("intervencion", "tfc", ""): "SBS interviene y liquida Financiera TFC",
    ("intervencion", "crac-raiz", ""): "SBS interviene y liquida CRAC Raíz",
    ("intervencion", "crac-del-centro", ""): "SBS interviene y liquida CRAC Del Centro",
    ("absorcion", "amerika-financiera", "america-factoring"): "Amérika Financiera absorbe a América Factoring",
    ("absorcion", "qapaq", "caja-profinanzas"): "Financiera Universal absorbe a CRAC Profinanzas",
    ("absorcion", "confianza", "confianza-original"): "Nuestra Gente absorbe a Fin. Confianza y pasa a financiera",
    ("absorcion", "mibanco", "edyficar"): "Mibanco absorbe el negocio de Financiera Edyficar",
    ("absorcion", "credinka", "caja-credinka"): "Fin. Nueva Visión absorbe a CRAC Credinka (Fin. Credinka)",
    ("absorcion", "tfc", "caja-los-libertadores-de-ayacucho"): "Financiera TFC absorbe a CRAC Los Libertadores",
    ("absorcion", "crac-raiz", "edpyme-raiz"): "CRAC Chavín absorbe a Edpyme Raíz (CRAC Raíz)",
    ("absorcion", "credinka", "caja-cajamarca"): "Financiera Credinka absorbe a CRAC Cajamarca",
    ("absorcion", "crac-los-andes", "solidaridad"): "CRAC Los Andes absorbe a Edpyme Solidaridad",
    ("absorcion", "total-servicios-financieros", "factoring-total"): "TOTAL Serv. Financieros absorbe a Factoring Total",
    ("absorcion", "cmac-arequipa", "caja-senor-de-luren"): "CMAC Arequipa asume CRAC Señor de Luren (intervenida)",
    ("absorcion", "cmac-piura", "cmac-sullana"): "CMAC Piura asume CMAC Sullana (intervenida)",
    ("absorcion", "cmac-arequipa", "credinka"): "CMAC Arequipa asume Financiera Credinka (intervenida)",
    ("cambio_subsistema", "proempresa", ""): "Edpyme Proempresa pasa a financiera",
    ("cambio_subsistema", "confianza", ""): "Caja Nuestra Gente pasa a financiera (Fin. Confianza)",
    ("cambio_subsistema", "credinka", ""): "Edpyme Nueva Visión pasa a financiera",
    ("cambio_subsistema", "crac-cencosud-scotia", ""): "Banco Cencosud pasa a caja rural (Caja CAT Perú)",
    ("cambio_subsistema", "compartamos", ""): "Compartamos Financiera pasa a banco",
    ("cambio_subsistema", "santander-consumer", ""): "Financiera Santander Consumer pasa a banco",
    ("cambio_subsistema", "efectiva", ""): "Financiera Efectiva pasa a banco",
    ("transferencia_cartera", "pichincha", "amerika-financiera"): "Amérika Financiera cede su cartera a Banco Financiero",
    ("transferencia_cartera", "scotiabank-peru", "citibank-peru"): "Citibank transfiere su banca minorista a Scotiabank",
}

# Saltos de participación > umbral revisados el 2026-11-03 que no tienen evento oficial ubicado. Se informan,
# no se marcan en el tablero. Clave: (subsistema, periodo, id_entidad).
REVIEWED_JUMPS = {
    ("cajas-rurales", 201112, "confianza"):
        "CRAC Nuestra Gente: créditos de consumo vigentes caen de S/ 156 MM a S/ 59 MM (venta o traslado de "
        "cartera de consumo); no se ubicó resolución ni hecho de importancia.",
    ("empresas-credito", 201407, "bbva-consumer-finance"):
        "BBVA Consumer Finance Edpyme pasa de S/ 15 MM a S/ 132 MM en un mes (probable compra de cartera "
        "vehicular); sin fuente oficial ubicada.",
    ("empresas-credito", 202002, "bbva-consumer-finance"):
        "BBVA Consumer Finance: créditos caen de S/ 552 MM a S/ 449 MM (venta de cartera previa a su "
        "liquidación de 2022); sin fuente oficial ubicada.",
    ("empresas-credito", 202105, "bbva-consumer-finance"):
        "BBVA Consumer Finance en reducción de cartera antes de su disolución (2022-02); coincide con la salida "
        "de Edpyme GMG.",
}


def month_index(p: int) -> int:
    return (p // 100) * 12 + p % 100 - 1


def add_months(p: int, n: int) -> int:
    y, m = divmod(month_index(p) + n, 12)
    return y * 100 + m + 1


def event_period(fecha: str) -> int:
    return int(fecha[:4] + fecha[5:7])


def norm_subsystem(sub: str) -> str | None:
    """Subsistema de los cuadros: las EDPYME se publican con las empresas de créditos; «otro» no es un subsistema."""
    sub = {"edpyme": "empresas-credito"}.get(sub, sub)
    return sub if sub in SUBSYSTEMS else None


# --------------------------------------------------------------------------------------------- datos

def load_ranking() -> pd.DataFrame:
    r = pd.read_parquet(RANKING, columns=["periodo", "subsistema", "id_entidad", "es_total", "variable", "valor"])
    r = r[~r["es_total"] & r["variable"].isin(SIZE_VARS)]
    wide = r.pivot_table(index=["periodo", "subsistema", "id_entidad"], columns="variable", values="valor",
                         aggfunc="first").reset_index()
    wide["figura"] = (wide[SIZE_VARS].fillna(0) > 0).any(axis=1)
    wide["con_creditos"] = wide["creditos_directos"].fillna(0) > 0
    return wide


def load_debtors() -> pd.DataFrame:
    d = pd.read_parquet(DEUDORES, columns=["periodo", "subsistema", "id_entidad", "es_total", "variable", "apertura",
                                           "valor"])
    # Sin los subsistema-mes que repiten otro mes (sus entidades serían las de ese otro mes) ni los totales repetidos.
    d = drop_debtor_source_errors(d)
    d = d[~d["es_total"] & (d["variable"] == "numero_deudores") & (d["apertura"] == "total") & (d["valor"] > 0)]
    return d[["periodo", "subsistema", "id_entidad"]].drop_duplicates()


def set_changes(present: pd.DataFrame, months: dict[str, list[int]]) -> pd.DataFrame:
    """Entidades que aparecen o desaparecen entre meses consecutivos con dato de cada subsistema."""
    out = []
    for sub, g in present.groupby("subsistema"):
        sets = g.groupby("periodo")["id_entidad"].apply(set).to_dict()
        ps = [p for p in months[sub] if p in sets]
        for a, b in zip(ps, ps[1:]):
            out += [(b, sub, e, "aparece") for e in sorted(sets[b] - sets[a])]
            out += [(b, sub, e, "desaparece") for e in sorted(sets[a] - sets[b])]
    return pd.DataFrame(out, columns=["periodo", "subsistema", "id_entidad", "cambio"])


def share_jumps(wide: pd.DataFrame, threshold: float) -> pd.DataFrame:
    c = wide[wide["con_creditos"]].copy()
    c["participacion"] = 100 * c["creditos_directos"] / c.groupby(["periodo", "subsistema"])["creditos_directos"].transform("sum")
    c = c.sort_values("periodo")
    grp = c.groupby(["subsistema", "id_entidad"])
    c["participacion_previa"] = grp["participacion"].shift()
    c["delta_pp"] = c["participacion"] - c["participacion_previa"]
    c["var_creditos"] = c["creditos_directos"] / grp["creditos_directos"].shift() - 1
    return c.loc[c["delta_pp"].abs() > threshold,
                 ["subsistema", "periodo", "id_entidad", "participacion_previa", "participacion", "delta_pp",
                  "var_creditos"]]


# --------------------------------------------------------------------------------------------- eventos

class Presence:
    def __init__(self, wide: pd.DataFrame, debtors: pd.DataFrame):
        self.debtors = {k: sorted(g["periodo"]) for k, g in debtors.groupby(["id_entidad", "subsistema"])}
        self.months = {s: sorted(g["periodo"].unique()) for s, g in wide.groupby("subsistema")}
        self.listed = {k: sorted(g["periodo"]) for k, g in wide[wide["figura"]].groupby(["id_entidad", "subsistema"])}
        self.credit = {k: sorted(g["periodo"]) for k, g in wide[wide["con_creditos"]].groupby(["id_entidad", "subsistema"])}
        self.credits = wide.set_index(["id_entidad", "subsistema", "periodo"])["creditos_directos"].fillna(0)

    def subsystems_of(self, entity: str) -> list[str]:
        return [s for (e, s) in self.listed if e == entity]

    def first_in(self, entity, sub, lo, hi=None, debtors=False):
        ps = self.listed.get((entity, sub), []) + (self.debtors.get((entity, sub), []) if debtors else [])
        return next((p for p in sorted(ps) if p >= lo and (hi is None or p <= hi)), None)

    def next_month(self, sub, p):
        return next((q for q in self.months[sub] if q > p), None)

    def exit_after(self, entity, sub, upto, credit=False):
        """Mes siguiente al último en que figura (o tiene créditos) hasta `upto`; None si no figuró."""
        ps = [p for p in (self.credit if credit else self.listed).get((entity, sub), []) if p <= upto]
        return (self.next_month(sub, ps[-1]), ps[-1]) if ps else (None, None)

    def sub_at(self, entity, p):
        return next((s for s in SUBSYSTEMS if p in self.listed.get((entity, s), [])), None)


def market_rows(events: pd.DataFrame, pres: Presence) -> tuple[pd.DataFrame, list[str]]:
    """Convierte cada evento de `entidad_evento.csv` en filas por subsistema afectado."""
    rows, notes = [], []
    last = max(max(v) for v in pres.months.values())

    def row(p, sub, tipo, ent, rel, ev):
        rows.append(dict(periodo=p, subsistema=sub, tipo=tipo, id_entidad=ent, id_entidad_relacionada=rel or "",
                         resolucion=ev["resolucion"], fuente=ev["fuente"], confianza=ev["confianza"],
                         fecha=ev["fecha"], ym=event_period(ev["fecha"]), fila=ev.name))

    for _, ev in events.iterrows():
        tipo, x, y = ev["tipo_evento"], ev["id_entidad"], ev["id_entidad_relacionada"]
        ym = event_period(ev["fecha"])
        if ym < add_months(START_PERIOD, -24):        # muy anterior a la ventana: no puede verse en los cuadros
            continue
        sa, sd = norm_subsystem(ev["subsistema_antes"]), norm_subsystem(ev["subsistema_despues"])
        if tipo == "cambio_subsistema" and sa is None and sd:
            tipo = "ingreso"                            # p. ej. Leasing Total → EDPYME
        elif tipo == "cambio_subsistema" and sd is None and sa:
            tipo = "salida"                             # p. ej. Credijet → emisora de dinero electrónico
        label = f"fila {ev.name + 2} {x} {ev['fecha']} {ev['tipo_evento']}"

        if tipo == "ingreso" and sd:
            if START_PERIOD in pres.listed.get((x, sd), []) and ym <= START_PERIOD:
                continue                                # ya estaba al inicio de la ventana
            # primer mes en el ranking o en deudores (CRAC Del Centro figura en ceros en el ranking hasta 2015-02)
            p = pres.first_in(x, sd, add_months(ym, -1), add_months(ym, 24), debtors=True)
            if p is None:
                notes.append(f"sin reflejo en los cuadros (a {last}): {label}")
            elif p > START_PERIOD:
                row(p, sd, "ingreso", x, "", ev)
        elif tipo in ("salida", "intervencion") and sa:
            p, _ = pres.exit_after(x, sa, add_months(ym, 2))
            if p is not None and p > START_PERIOD:
                row(p, sa, tipo, x, "", ev)
        elif tipo == "cambio_subsistema" and sa and sd and sa != sd:
            if START_PERIOD in pres.listed.get((x, sd), []) and ym <= START_PERIOD:
                continue                                # ya estaba en el subsistema nuevo al inicio de la ventana
            p = pres.first_in(x, sd, add_months(ym, -1), add_months(ym, 3))
            if p is None or not any(q < p for q in pres.listed.get((x, sa), [])):
                notes.append(f"cambio de subsistema sin reflejo {sa}→{sd}: {label}")
            elif p > START_PERIOD:
                row(p, sa, "cambio_subsistema", x, "", ev)
                row(p, sd, "cambio_subsistema", x, "", ev)
        elif tipo in ("absorcion", "fusion"):
            if not y:
                notes.append(f"{tipo} sin entidad relacionada (no se ubica en el mercado): {label}")
                continue
            exits = [(*pres.exit_after(y, s, add_months(ym, 2), credit=True), s) for s in pres.subsystems_of(y)]
            exits = [e for e in exits if e[0] is not None and e[1] >= add_months(ym, -3)]
            if exits:
                p, _, sy = max(exits, key=lambda e: e[1])
                subs = [sy]
            else:                                       # la absorbida no figura en los cuadros (factoring)
                p, subs = ym, []
            sx = pres.sub_at(x, p)
            subs += [sx] if sx and sx not in subs else []
            if p > START_PERIOD and subs:
                for s in subs:
                    row(p, s, tipo, x, y, ev)
            elif p > START_PERIOD:
                notes.append(f"absorción sin reflejo: {label}")
        elif tipo == "transferencia_bloque":
            sx = pres.sub_at(x, ym) or pres.sub_at(x, add_months(ym, -1))
            if sx is None or not y:
                continue
            cands = [add_months(ym, k) for k in range(3)]
            drops = {p: pres.credits.get((x, sx, add_months(p, -1)), 0) - pres.credits.get((x, sx, p), 0) for p in cands}
            p = max(drops, key=drops.get)
            if p > START_PERIOD:
                for s in dict.fromkeys([sx, pres.sub_at(y, p)]):
                    if s:
                        row(p, s, "transferencia_cartera", y, x, ev)
    return pd.DataFrame(rows), notes


def join_unique(values) -> str:
    """Une textos separados por « ; » sin repetir; «Res. SBS 03341-2024» y «Res. SBS 3341-2024» son la misma."""
    out, seen = [], set()
    for v in values:
        for part in str(v).split(" ; "):
            part = part.strip()
            key = re.sub(r"\b0+(\d)", r"\1", part)
            if part and part != "nan" and key not in seen:
                seen.add(key)
                out.append(part)
    return " ; ".join(out)


def consolidate(m: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """Une duplicados: mismo evento en dos filas, salida/intervención cubierta por absorción, adjudicaciones."""
    m = m.copy()
    m["prioridad"] = m["tipo"].map({t: i for i, t in enumerate(TYPE_PRIORITY)})
    m["desfase"] = (m["periodo"].map(month_index) - m["ym"].map(month_index)).abs()
    m["grupo"] = range(len(m))

    # salida / intervención cuyo bloque asume otra entidad en el mismo subsistema (±1 mes) → a la absorción
    for i, r in m[m["tipo"].isin(["salida", "intervencion"])].iterrows():
        hit = m[(m["tipo"] == "absorcion") & (m["subsistema"] == r["subsistema"])
                & (m["id_entidad_relacionada"] == r["id_entidad"])
                & ((m["periodo"].map(month_index) - month_index(r["periodo"])).abs() <= 1)]
        if len(hit):
            m.loc[i, "grupo"] = m.loc[hit.index[0], "grupo"]
            m.loc[i, "prioridad"] = 99
    # mismo mes, subsistema y entidad → un grupo
    for _, g in m.groupby(["periodo", "subsistema", "id_entidad"]):
        m.loc[g.index, "grupo"] = m.loc[g.index, "grupo"].min()

    # adjudicaciones de bloque: su resolución se suma a la absorción del mismo par (±1 mes)
    adj = events[events["tipo_evento"] == "adjudicacion_bloque"]
    extra_res: dict[int, list[str]] = {}
    for _, a in adj.iterrows():
        hit = m[(m["tipo"] == "absorcion") & (m["id_entidad"] == a["id_entidad"])
                & (m["id_entidad_relacionada"] == a["id_entidad_relacionada"])
                & ((m["ym"].map(month_index) - month_index(event_period(a["fecha"]))).abs() <= 1)]
        for g in hit["grupo"].unique():
            extra_res.setdefault(g, []).append((a["resolucion"], a["fuente"]))

    out = []
    for g, rows in m.groupby("grupo"):
        rows = rows.sort_values(["prioridad", "desfase", "fecha"])
        head = rows.iloc[0].to_dict()
        extras = extra_res.get(g, [])
        ordered = rows.sort_values(["prioridad", "fecha"])
        head["resolucion"] = join_unique(list(ordered["resolucion"]) + [e[0] for e in extras])
        head["fuente"] = join_unique(list(ordered["fuente"]) + [e[1] for e in extras])
        head["confianza"] = min(rows["confianza"], key=lambda c: CONFIDENCE_RANK.get(c, -1))
        head["filas"] = ",".join(str(int(f) + 2) for f in sorted(rows["fila"]))
        out.append(head)
    out = pd.DataFrame(out)
    # las dos filas (una por subsistema) de un mismo evento llevan las mismas resoluciones, fuentes y confianza
    key = ["periodo", "tipo", "id_entidad", "id_entidad_relacionada"]
    for _, g in out.groupby(key):
        out.loc[g.index, "resolucion"] = join_unique(g["resolucion"])
        out.loc[g.index, "fuente"] = join_unique(g["fuente"])
        out.loc[g.index, "confianza"] = min(g["confianza"], key=lambda c: CONFIDENCE_RANK.get(c, -1))
    return out


def short_name(maestro: Maestro, entity: str, periodo: int) -> str:
    v = maestro.vigencia(entity, periodo) or maestro.vigencia(entity, add_months(periodo, -1))
    return v["nombre"] if v else maestro.entidades.get(entity, {}).get("nombre_actual", entity)


def default_label(r, maestro: Maestro) -> str:
    before = add_months(r["periodo"], -1)
    x = short_name(maestro, r["id_entidad"], before if r["tipo"] in ("salida", "intervencion", "cambio_subsistema")
                   else r["periodo"])
    y = short_name(maestro, r["id_entidad_relacionada"], before) if r["id_entidad_relacionada"] else ""
    text = {"ingreso": f"Ingresa {x}", "salida": f"Sale {x}", "intervencion": f"SBS interviene y liquida {x}",
            "absorcion": f"{x} absorbe a {y}", "fusion": f"{x} se fusiona con {y}",
            "transferencia_cartera": f"{y} transfiere cartera a {x}",
            "cambio_subsistema": f"{x} cambia de subsistema"}[r["tipo"]]
    return text[:MAX_LABEL]


# --------------------------------------------------------------------------------------------- principal

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--umbral", type=float, default=3.0, help="salto de participación en créditos (pp) a revisar")
    ap.add_argument("--solo-validar", action="store_true", help="no escribe eventos_mercado.csv")
    args = ap.parse_args()

    maestro = Maestro()
    events = pd.read_csv(EVENTS_CSV, dtype=str, keep_default_na=False)
    wide = load_ranking()
    debtors = load_debtors()
    pres = Presence(wide, debtors)
    last = int(wide["periodo"].max())

    raw, notes = market_rows(events, pres)
    m = consolidate(raw, events)
    m["etiqueta_corta"] = [LABELS.get((r["tipo"], r["id_entidad"], r["id_entidad_relacionada"])) or default_label(r, maestro)
                           for _, r in m.iterrows()]
    sin_etiqueta = [(r["tipo"], r["id_entidad"], r["id_entidad_relacionada"]) for _, r in m.iterrows()
                    if (r["tipo"], r["id_entidad"], r["id_entidad_relacionada"]) not in LABELS]
    largas = m[m["etiqueta_corta"].str.len() > MAX_LABEL]
    m = m.sort_values(["periodo", "subsistema", "prioridad", "id_entidad"]).reset_index(drop=True)

    print(f"Ranking {START_PERIOD} → {last}; {len(m)} filas de eventos de mercado "
          f"({m.groupby(['periodo', 'id_entidad', 'tipo']).ngroups} eventos).")

    # 1) todo cambio en el conjunto de entidades (figura en el ranking) debe tener evento
    present = wide[wide["figura"]][["periodo", "subsistema", "id_entidad"]]
    changes = set_changes(present, pres.months)
    def covered(r) -> str:
        own = m[(m["subsistema"] == r["subsistema"])
                & ((m["id_entidad"] == r["id_entidad"]) | (m["id_entidad_relacionada"] == r["id_entidad"]))]
        cand = own[(own["periodo"].map(month_index) - month_index(r["periodo"])).abs() <= 1]
        if len(cand):
            return "; ".join(f"{c.tipo} {c.periodo}" for c in cand.itertuples())
        # ingresó antes (visible en deudores) y el ranking la trae en ceros unos meses: CRAC Del Centro 2014-09
        earlier = own[(own["periodo"] < r["periodo"]) & (own["periodo"] >= add_months(r["periodo"], -12))]
        if r["cambio"] == "aparece" and earlier["tipo"].isin(["ingreso", "cambio_subsistema"]).any():
            return f"ingreso previo {earlier.iloc[-1]['periodo']} (ranking en ceros)"
        # cascarón: deja de figurar meses después de haber cedido su negocio (Edyficar 2015-12, tras la escisión
        # de 2015-03); no cambia el mercado de crédito.
        prev = add_months(r["periodo"], -1)
        if r["cambio"] == "desaparece" and not pres.credits.get((r["id_entidad"], r["subsistema"], prev), 0):
            earlier = own[own["periodo"] < r["periodo"]]
            if len(earlier):
                return f"sin créditos desde {earlier.iloc[-1]['tipo']} {earlier.iloc[-1]['periodo']}"
        return ""
    changes["evento"] = changes.apply(covered, axis=1)
    missing = changes[changes["evento"] == ""]
    print(f"\n[1] Cambios en el conjunto de entidades (ranking, figura = créditos/depósitos/patrimonio > 0): "
          f"{len(changes)}; sin evento: {len(missing)}")
    for r in missing.itertuples():
        print(f"    FALTA EVENTO {r.periodo} {r.subsistema} {r.id_entidad} {r.cambio}")
    for r in changes[changes["evento"].str.startswith(("ingreso previo", "sin créditos"))].itertuples():
        print(f"    sin fila propia: {r.periodo} {r.subsistema} {r.id_entidad} {r.cambio} ({r.evento})")

    # 2) cambios solo en créditos (la entidad sigue figurando, con créditos en 0)
    credit_changes = set_changes(wide[wide["con_creditos"]][["periodo", "subsistema", "id_entidad"]], pres.months)
    keyset = set(map(tuple, changes[["periodo", "subsistema", "id_entidad"]].values))
    only_credit = credit_changes[[tuple(k) not in keyset for k in credit_changes[["periodo", "subsistema", "id_entidad"]].values]]
    print(f"\n[2] Cambios solo en créditos directos (la entidad figura con créditos en 0): {len(only_credit)}")
    for r in only_credit.itertuples():
        print(f"    {r.periodo} {r.subsistema} {r.id_entidad} créditos {r.cambio}")

    # 3) saltos de participación
    jumps = share_jumps(wide, args.umbral)
    print(f"\n[3] Saltos de participación en créditos > {args.umbral} pp: {len(jumps)}")
    n_unexplained = 0
    for r in jumps.itertuples():
        ev = m[(m["subsistema"] == r.subsistema)
               & ((m["periodo"].map(month_index) - month_index(r.periodo)).abs() <= 1)]
        # Si los créditos de la propia entidad cambian poco, el salto es efecto del denominador (entró o salió
        # otra) y basta un evento del subsistema; si cambian mucho, el evento debe ser de la propia entidad.
        if abs(r.var_creditos) > OWN_CHANGE:
            ev = ev[(ev["id_entidad"] == r.id_entidad) | (ev["id_entidad_relacionada"] == r.id_entidad)]
        why = REVIEWED_JUMPS.get((r.subsistema, r.periodo, r.id_entidad))
        if len(ev):
            continue
        n_unexplained += why is None
        tag = "revisado, sin evento oficial" if why else "SIN EVENTO"
        print(f"    {tag}: {r.periodo} {r.subsistema} {r.id_entidad} {r.participacion_previa:.1f} → "
              f"{r.participacion:.1f} ({r.delta_pp:+.1f} pp){' — ' + why if why else ''}")

    # 4) desfases entre la fecha del evento y su reflejo en los cuadros
    lag = m[m["desfase"] > 1]
    print(f"\n[4] Eventos cuyo reflejo en los cuadros difiere > 1 mes de la fecha registrada: {len(lag)}")
    for r in lag.itertuples():
        print(f"    {r.id_entidad} {r.tipo}: fecha {r.fecha} → cuadros {r.periodo} (filas {r.filas} de entidad_evento.csv)")

    # 5) eventos sin reflejo o no ubicables
    print(f"\n[5] Eventos de entidad_evento.csv no llevados al mercado: {len(notes)}")
    for n in notes:
        print(f"    {n}")

    # 6) deudores: mismo cambio en el otro cuadro
    debt = set_changes(debtors, {s: sorted(g["periodo"].unique()) for s, g in debtors.groupby("subsistema")})
    debt = debt[debt["periodo"] > 201012]
    dk = set(map(tuple, debt[["periodo", "subsistema", "id_entidad", "cambio"]].values))
    rk = set(map(tuple, changes[["periodo", "subsistema", "id_entidad", "cambio"]].values))
    print(f"\n[6] Deudores (desde 2010-12) vs. ranking: cambios solo en deudores {len(dk - rk)}, solo en ranking {len(rk - dk)}")
    for k in sorted(dk - rk):
        print(f"    solo deudores: {k}")
    for k in sorted(rk - dk):
        if k[0] > 201012:
            print(f"    solo ranking:  {k}")

    # 7) subsistema de los datos vs. entidad_vigencia.csv
    bad = []
    for r in present.itertuples():
        v = maestro.vigencia(r.id_entidad, r.periodo)
        if v is None or norm_subsystem(v["subsistema"]) != r.subsistema:
            bad.append((r.id_entidad, r.periodo, r.subsistema, v["subsistema"] if v else None))
    print(f"\n[7] Entidad-mes cuyo subsistema en los cuadros no coincide con entidad_vigencia.csv: {len(bad)}")
    if bad:
        summary = (pd.DataFrame(bad, columns=["id_entidad", "periodo", "en_cuadros", "en_vigencia"]).fillna("—")
                   .groupby(["id_entidad", "en_cuadros", "en_vigencia"])["periodo"].agg(["min", "max", "count"]))
        for (ent, sub, vig), r in summary.iterrows():
            print(f"    {ent}: {r['min']} → {r['max']} ({r['count']} meses) en {sub}; vigencia dice {vig}")

    if sin_etiqueta:
        print(f"\nEventos con etiqueta genérica (agregar a LABELS): {sin_etiqueta}")
    if len(largas):
        print(f"\nEtiquetas de más de {MAX_LABEL} caracteres: {list(largas['etiqueta_corta'])}")
    low = m[m["confianza"] != "alta"]
    print(f"\nFilas con confianza distinta de alta: {len(low)}")
    for r in low.itertuples():
        print(f"    {r.periodo} {r.subsistema} {r.id_entidad} {r.tipo} ({r.confianza})")

    if not args.solo_validar:
        m[OUT_COLUMNS].to_csv(OUT_CSV, index=False, encoding="utf-8", lineterminator="\n")
        print(f"\nEscrito {OUT_CSV.relative_to(PROJECT_DIR)} ({len(m)} filas)")
    return 1 if len(missing) or n_unexplained or len(largas) else 0


if __name__ == "__main__":
    sys.exit(main())
