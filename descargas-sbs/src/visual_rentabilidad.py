"""Genera `outputs/rentabilidad_ssff.html`: tablero público de rentabilidad y eficiencia del sistema financiero.

Lee dos tablas largas de `data/processed/boletin/` (correr antes `leer_boletin.py`):
- `estados-financieros`: balance y estado de resultados por entidad y mes (B-2201, B-3101, C-1101,
  C-2101, C-4103). Las partidas del estado de resultados son ACUMULADAS de enero al mes.
- `indicadores-financieros`: ROE y ROA publicados por la SBS (B-2401, B-3301, C-1301, C-2301,
  C-4301), solo para comparar con el cálculo propio de cada subsistema.

Todo se calcula desde los montos (miles de S/):
- Flujo de 12 meses de cada partida = acumulado del mes + acumulado de diciembre del año anterior
  − acumulado del mismo mes del año anterior (en diciembre, el acumulado del año). Es la regla de las
  notas de los cuadros de indicadores de la SBS («valores anualizados»).
- Promedios = promedio de los saldos de fin de mes de los últimos 12 meses (t−11 … t), también
  como en esas notas. Se exigen los 12 meses; si falta alguno, el promedio queda vacío.
- ROE = utilidad neta de 12 meses / patrimonio promedio; ROA = utilidad / activo promedio. Con esta
  regla se reproduce el ROE y el ROA publicados por entidad (99,6 % de los entidad-mes desde 2016 a
  menos de 0,1 pp). Para los agregados hace falta una regla más: una entidad que SALE del subsistema
  (o del sistema) durante el año conserva su último acumulado en el agregado hasta diciembre. Así
  se reproduce el ROE publicado (dif. <= 0,05 pp) de financieras y cajas municipales en todos los
  meses desde 2016, el de cajas rurales en el 97 %, el de banca en el 88 % y el de empresas de
  créditos en el 80 % de los meses. Banca: el desvío (< 0,07 pp) empieza en 2025-06 con la entrada
  de Santander Consumer a mitad de año (y crece con Efectiva en 2026-06); la SBS suma a banca solo el
  resultado desde la entrada (restando el acumulado del mes previo a la entrada reproduce el 100 %
  de los meses); NO es por las sucursales del BCP en el exterior, que casi no cambian utilidad ni
  patrimonio. Esa regla de entrada empeora cajas rurales en 2019, así que no se aplica. Quedan
  desvíos sin explicar en cajas rurales (hasta 3,2 pp, 4 meses de 2016) y empresas de créditos
  (hasta 2,3 pp, 2016-2017 y 2020-2022). `check_published` imprime el ajuste.
- Historia 2010-07 → 2015-12 (agregada 2026-10-28; los indicadores empiezan en 2011-07, el primer mes con
  12 meses de historia). Por entidad, el ROE propio reproduce el publicado (< 0,1 pp) en el 98,9 % de los
  entidad-mes de 2011-07 → 2015-12. Por subsistema (dif. <= 0,05 pp): cajas municipales 100 %, banca 78 % (máx.
  0,13 pp), empresas de créditos 67 % (máx. 0,64 pp, 2012-08), cajas rurales 57 % (máx. 1,6 pp, 2015-07/08)
  y financieras 48 % (máx. 0,69 pp, 2012-2014; la regla de entrada de banca —`rw`— los reduce en parte, sin
  eliminarlos, y no se aplica). Hasta 2012-12 rige el Manual de Contabilidad anterior: la participación de
  los trabajadores es una línea propia hasta 2010 (en cero en 2011-2012, salvo tres entidades en 2011-01) y
  se suma a los gastos administrativos (`ga`), donde va desde 2011, para que la eficiencia sea comparable;
  así la identidad del estado de resultados sigue cuadrando. CMAC Pisco 2014-01 → 2014-04 repite las cifras
  del 31.12.2013 y se omite (`drop_repeated`, con la lista común de `errores_origen.py`).
- Partidas de la descomposición del ROA (flujo de 12 meses / activo promedio): ingresos y gastos
  financieros, provisiones para créditos directos, servicios financieros netos, gastos de operación
  (gastos administrativos + depreciación + amortización, como en el glosario de la SBS), otros
  (venta de cartera, otras provisiones, otros ingresos y gastos) e impuesto a la renta. Suman el ROA
  (las identidades del estado de resultados cuadran en todas las filas leídas).
- Eficiencia = gastos de operación / margen financiero total (margen bruto + ingresos − gastos por
  servicios financieros), ambos de 12 meses en todos los subsistemas. La SBS publica para banca y
  financieras el mismo cociente con valores acumulados en el año (y anualizados en cajas y EC).
- Costo del riesgo = provisiones para créditos directos de 12 meses / créditos directos promedio
  (vigentes + refinanciados y reestructurados + atrasados del balance; coinciden con el ranking).
  La partida de provisiones es neta de reversiones (es negativa en 235 entidad-mes acumulados).
- Mora = créditos atrasados / créditos directos del balance, a fin de mes.

Indicadores por trabajador (agregados 2026-10-24), con un tercer insumo:
- `personal-categoria-laboral`: número de personal a fin de mes por entidad (B-2305, B-3202,
  C-1202, C-2202, C-4206; columna «Total»). Viene del Anexo N.° 10, cuya nota 2/ pide contar a
  todo el personal, «nombrados, contratos o contratados por terceros» (incluye tercerizados).
- Utilidad por trabajador = utilidad neta de 12 meses / personal promedio de 12 meses (promedio
  de los 12 conteos de fin de mes, t−11 … t, igual que el activo promedio; se exigen los 12).
  Agregados: suma de utilidades (con la regla de perímetro de arriba) / promedio de la suma de
  trabajadores de las entidades presentes cada mes. El JSON guarda la SUMA de los 12 conteos
  (`Ts`, entera) y la página la divide entre 12.
- Créditos por trabajador = créditos directos / personal total, ambos a fin de mes, en todos los
  subsistemas. Es el indicador «Créditos directos / personal» que la SBS publica para banca y
  financieras; el de cajas municipales, cajas rurales y empresas de créditos («Créditos directos /
  empleados») divide solo entre la categoría «Empleados» (verificado en los datos), así que allí el
  tablero NO coincide con lo publicado a propósito. `check_staff` imprime el ajuste con las dos bases.
- Si a una entidad del agregado le falta el conteo de personal en un mes, el total de personal
  del agregado queda vacío ese mes (no se suma de menos).
- Composición del personal (agregada 2026-10-25): gerentes, funcionarios, empleados y otros a fin de
  mes, por entidad, subsistema y sistema (clave `mix` del JSON). Los guiones («-») del cuadro son
  cero (las cuatro categorías suman el total en todas las filas). Agregados = suma de las entidades
  listadas en el cuadro; el sistema queda vacío el mes en que falta el cuadro de algún subsistema
  (banca 2023-11). Las categorías las asigna cada entidad y no son comparables entre entidades.

Participación de los trabajadores en las utilidades (agregada 2026-10-25): desde 2011 está dentro de
los gastos de personal (Res. SBS 2740-2011) y el Boletín no la separa. Se toma de las notas de los EEFF
auditados de cada entidad (`config/participacion_trabajadores.csv`, con fuente y página), solo donde
la revelan; no hay total del sistema. La página la compara con el personal promedio del año (conteo
SBS) y con la utilidad antes de IR de diciembre del Boletín. Los ceros inferidos (la nota no trae la
línea) no se publican.

Cifras repetidas de otro mes en la serie de la entidad (2026-11-03, `errores_origen.RANKING_REPEATS`, «row» = all): en
CRAC Señor de Luren 2015-05, CRAC Raíz (Chavín) 2016-03 y 04, Financiera TFC 2019-11 y CMAC Sullana 2024-06 la SBS
repite en el estado financiero y en el cuadro de personal las cifras de otro mes (CMAC Pisco 2014-01 → 04 ya se omite
entera, `drop_repeated`). La serie de la ENTIDAD no las usa (`entity_repeats`, `entity_block`): ese mes queda vacío;
los flujos de 12 meses que usarían el acumulado repetido también (`flow_blocked`: Raíz 2017-03 y 04, que restan el
acumulado de 2016-03 y 04); los promedios de 12 meses (activo, patrimonio, créditos, personal) se calculan con los
meses válidos de la ventana (Raíz 2016-05 → 2017-03 promedia 10 u 11 meses). Ojo: Raíz absorbió a Edpyme Raíz en
may-2016, así que sin los meses previos el patrimonio promedio sube y su ROE de 2016-05 → 2017-02 queda por debajo del
publicado por la SBS (que promedia las cifras repetidas): −27,1 % frente a −30,2 % en 2016-05, 2,6 % frente a 3,0 % en
2017-02. La composición del personal (`mix`) de esos meses también queda vacía. Los agregados NO cambian: la SBS suma
las cifras repetidas en sus totales y con ellas se reproduce el ROE publicado. La página recibe la lista en `rep`
(`repeat_rows`: [mes, ámbito, mes repetido, «fila» | «flujo», motivo]): la ficha y la tabla de la entidad muestran el
último dato válido con su mes y el motivo, el ranking, la dispersión y el conteo de entidades con pérdida la omiten
con una nota, y el tooltip del hueco da el motivo. `check_entities` deja de comparar esas entidad-mes.

Agregados: los saldos de cada subsistema son la suma de sus entidades en cada mes (coincide con la
columna total del cuadro en todos los meses); los flujos siguen la regla de las salidas de arriba. El
sistema aplica la misma regla a todas las entidades (no es la suma de los subsistemas, que contaría
dos veces a una entidad que cambia de subsistema a mitad de año). Cada entidad usa su
propia historia aunque haya cambiado de subsistema (p. ej. una financiera que pasa a banco): sus
flujos y promedios de 12 meses no se cortan con el traspaso. Banca usa el BCP sin sus sucursales en
el exterior (la columna local, que es la que suma el total del cuadro de estados financieros).

Genera además `outputs/rentabilidad_ssff_artifact.html`, la versión para publicar como Artifact
de claude.ai (sin <html>/<head>/<body>).

Uso:
    python visual_rentabilidad.py
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from visual_mora import (ENTIDADES, PROJECT_DIR, SUBSYSTEMS, artifact_version, month_key, month_range,
                         read_table)
from errores_origen import (full_row_repeat_keys, income_excluded_keys, repeat_footnote,  # noqa: E402
                            source_repeats)

BOLETIN = PROJECT_DIR / "data" / "processed" / "boletin"
TEMPLATE = PROJECT_DIR / "src" / "plantillas" / "rentabilidad.html"
OUT = PROJECT_DIR / "outputs" / "rentabilidad_ssff.html"
OUT_ARTIFACT = PROJECT_DIR / "outputs" / "rentabilidad_ssff_artifact.html"
PLACEHOLDER = "/*__DATA__*/null"
PTU_FILE = PROJECT_DIR / "config" / "participacion_trabajadores.csv"

# Partidas del estado de resultados (acumuladas en el año) → clave corta del JSON.
FLOWS = {
    "ingresos_financieros": "if",
    "gastos_financieros": "gf",
    "provisiones_creditos_directos": "pr",
    "ingresos_servicios_financieros": "si",
    "gastos_servicios_financieros": "sg",
    "resultado_venta_cartera": "vc",
    "gastos_administrativos": "ga",
    "provisiones_depreciacion_amortizacion": "pda",
    "provisiones_depreciacion_amortizacion_depreciacion": "dep",
    "provisiones_depreciacion_amortizacion_amortizacion": "amo",
    "otros_ingresos_gastos": "oi",
    "impuesto_renta": "ir",
    "resultado_neto_ejercicio": "rn",
}
STOCKS = {
    "total_activo": "ac",
    "patrimonio": "pa",
    "creditos_vigentes": "cv",
    "creditos_refinanciados_reestructurados": "crr",
    "creditos_atrasados": "at",
}
# Orden de los campos en el JSON. Flujos de 12 meses: if … rn (da = depreciación + amortización,
# op = otras provisiones). Promedios de 12 meses: A, P, C. Saldos a fin de mes: ac, pa, cd, at.
# ut = utilidad acumulada en el año (como la publica la SBS). np = personal a fin de mes (número);
# Ts = suma de los 12 conteos de fin de mes de personal (t−11 … t; promedio = Ts / 12).
# rw = utilidad neta de 12 meses para la utilidad por trabajador: en un agregado excluye lo que una
# entidad ganó antes de entrar a él en el año (su personal solo cuenta desde la entrada); en una
# entidad es igual a rn.
FIELDS = ["if", "gf", "pr", "si", "sg", "vc", "ga", "da", "op", "oi", "ir", "rn",
          "A", "P", "C", "ac", "pa", "cd", "at", "ut", "np", "Ts", "rw"]
STAFF = "personal-categoria-laboral"
# Denominador del indicador publicado «créditos directos / personal | empleados» (verificado en los
# datos 2015-2026): banca y financieras usan el TOTAL del personal; cajas municipales, cajas rurales y
# empresas de créditos («Créditos Directos / Empleados») solo la categoría «Empleados».
PUB_BASIS = {"banca-multiple": "total", "empresas-financieras": "total", "cajas-municipales": "empleados",
             "cajas-rurales": "empleados", "empresas-credito": "empleados"}
PTU_VAR = "participacion_trabajadores"   # línea propia del estado de resultados solo hasta 2010 (ver load_statements)
FLOW_KEYS = ["if", "gf", "pr", "si", "sg", "vc", "ga", "da", "op", "oi", "ir", "rn"]
# Categorías del cuadro de personal, en el orden de `mix` (de la página).
MIX_CATS = ["gerentes", "funcionarios", "empleados", "otros"]


def load_statements() -> pd.DataFrame:
    """Balance y estado de resultados por (periodo, subsistema, entidad), columnas = claves cortas."""
    d = read_table(BOLETIN / "estados-financieros.parquet",
                        columns=["periodo", "subsistema", "id_entidad", "es_total", "variable", "apertura", "valor"])
    d = d[(~d["es_total"]) & (d["apertura"] == "total") & d["variable"].isin({**FLOWS, **STOCKS, PTU_VAR: "pt"})]
    w = d.pivot_table(index=["periodo", "subsistema", "id_entidad"], columns="variable", values="valor", aggfunc="sum")
    w = w.rename(columns={**FLOWS, **STOCKS, PTU_VAR: "pt"}).reindex(columns=list(FLOWS.values()) + list(STOCKS.values()) + ["pt"])
    # Las partidas que una entidad no reporta son cero (p. ej. venta de cartera antes de 2015-09, o la
    # participación de los trabajadores desde 2013, cuando la línea desaparece).
    w = w.fillna(0.0).reset_index()
    # Entidades absorbidas o liquidadas que la SBS sigue mostrando en ceros (CRAC Del Centro desde 2026-04).
    w = w[w["ac"] != 0].copy()
    # Participación de los trabajadores: hasta 2010 es una línea propia del estado de resultados (entre el
    # resultado antes de participaciones y el impuesto); desde 2011 va dentro de los gastos de personal
    # (Res. SBS 2740-2011) y la línea queda en cero (2011-2012) o desaparece (2013). Se suma a los gastos
    # administrativos para que los gastos de operación y la eficiencia sean comparables a través de 2011.
    w["ga"] = w["ga"] + w["pt"]
    w = drop_repeated(w.drop(columns="pt"))
    w["da"] = w["dep"] + w["amo"]
    w["op"] = w["pda"] - w["da"]
    w["cd"] = w["cv"] + w["crr"] + w["at"]
    w["ut"] = w["rn"]
    w["t"] = (w["periodo"] // 100) * 12 + w["periodo"] % 100 - 1   # mes como entero correlativo
    w = w.astype({"subsistema": str, "id_entidad": str}).merge(load_staff(), on=["periodo", "subsistema", "id_entidad"], how="left")
    w = impute_staff(w)
    return w.drop(columns=["pda", "dep", "amo", "cv", "crr"])


def drop_repeated(w: pd.DataFrame) -> pd.DataFrame:
    """Quita las filas de una entidad con cifras de otro mes que el total del estado de resultados de la SBS no
    incluye (`errores_origen.income_excluded_keys`): CMAC Pisco 2014-01 → 2014-04, que repite el 31.12.2013 (nota
    «La información de CMAC Pisco corresponde al 31.12.2013»; el total del cuadro no la incluye). Con su acumulado
    de diciembre en enero, su utilidad de 12 meses se duplicaría.
    Las demás entidad-mes con la fila repetida (`errores_origen.full_row_repeat_keys`: CRAC Señor de Luren 2015-05,
    Raíz 2016-03/04, TFC 2019-11, CMAC Sullana 2024-06) se dejan, porque la SBS las suma en sus totales y con ellas
    se reproduce el ROE publicado de esos años; desde el 2026-11-03 solo cuentan en los agregados: la serie de la
    entidad las deja vacías (`entity_block`).
    Hasta el 2026-11-03 la regla era «fila idéntica a la del mes anterior en todas las partidas, antes de 2015-01»,
    que daba exactamente esas 4 filas; ahora la lista es la común y la detección queda como aviso."""
    cols = list(FLOWS.values()) + list(STOCKS.values())
    w = w.sort_values(["id_entidad", "periodo"])
    key = pd.Series(list(zip(w["periodo"], w["subsistema"].astype(str), w["id_entidad"].astype(str))), index=w.index)
    rep = key.isin(income_excluded_keys())
    prev = w.groupby("id_entidad")[cols].shift(1)
    same = (w[cols] == prev).all(axis=1) & ~key.isin(full_row_repeat_keys())
    for k in key[same]:
        print(f"  AVISO: {k}: estado financiero idéntico al del mes anterior y no está en errores_origen.RANKING_REPEATS")
    for (sub, ent), g in w[rep].groupby(["subsistema", "id_entidad"]):
        print(f"  Cifras repetidas del mes anterior (se omiten): {sub} {ent}, {len(g)} meses ({g['periodo'].min()}-{g['periodo'].max()})")
    return w[~rep].copy()


def load_staff_totals() -> pd.Series:
    """TOTAL del subsistema publicado en el cuadro de personal, por (periodo, subsistema)."""
    d = read_table(BOLETIN / f"{STAFF}.parquet", columns=["periodo", "subsistema", "es_total", "variable", "apertura", "valor"])
    d = d[d["es_total"] & (d["variable"] == "numero_personal") & (d["apertura"] == "total")]
    return d.assign(subsistema=d["subsistema"].astype(str)).groupby(["periodo", "subsistema"])["valor"].first()


def credits_basis() -> pd.Series:
    """Créditos directos (miles de S/) con la cobertura del cuadro de personal: con las sucursales
    en el exterior cuando el balance las publica aparte (BCP), por (periodo, subsistema, entidad)."""
    d = read_table(BOLETIN / "estados-financieros.parquet",
                        columns=["periodo", "subsistema", "id_entidad", "es_total", "variable", "apertura", "valor"])
    d = d[(~d["es_total"]) & d["variable"].isin(["creditos_vigentes", "creditos_refinanciados_reestructurados", "creditos_atrasados"])
          & d["apertura"].isin(["total", "total|con_sucursales_exterior"])]
    d = d.assign(ext=d["apertura"] != "total", id_entidad=d["id_entidad"].astype(str), subsistema=d["subsistema"].astype(str))
    s = d.groupby(["periodo", "subsistema", "id_entidad", "ext"])["valor"].sum().unstack("ext")
    return s[True].fillna(s[False]) if True in s.columns else s[False]


def published_per_employee() -> pd.Series:
    """«Créditos directos / personal» publicado por entidad (miles de S/ por persona)."""
    d = read_table(BOLETIN / "indicadores-financieros.parquet",
                        columns=["periodo", "subsistema", "id_entidad", "es_total", "variable", "valor"])
    d = d[(~d["es_total"]) & (d["variable"] == "creditos_directos_por_empleado")]
    d = d.assign(id_entidad=d["id_entidad"].astype(str), subsistema=d["subsistema"].astype(str))
    return d.groupby(["periodo", "subsistema", "id_entidad"])["valor"].first()


IMPUTED: list[dict] = []   # meses con personal imputado (se pasan a la página)
CARRIED: list[dict] = []   # entidad-mes con el último personal publicado arrastrado (ver impute_staff)


def impute_staff(w: pd.DataFrame) -> pd.DataFrame:
    """Completa el personal de una entidad en un mes sin cuadro de personal legible, con el
    implícito en el indicador publicado: créditos directos / («créditos directos / personal»),
    redondeado. Caso conocido: banca 2023-11, cuyo archivo B-2305 trae las cifras de diciembre
    (el lector lo rechaza); el implícito de noviembre difiere del de diciembre, así que es dato
    propio de noviembre, con un error de redondeo de pocas personas (el publicado de banca viene
    redondeado a miles de soles). Solo se imputa si a TODAS las entidades del subsistema les
    falta el conteo ese mes (un archivo faltante), no huecos sueltos, y solo antes del último mes con
    cuadro de personal del subsistema, y solo en banca y financieras (en cajas y empresas de créditos el
    indicador publicado divide entre la categoría «Empleados», no entre el total)."""
    # 1) Entidad del balance que no figura en el cuadro de personal de un mes que sí se publicó, cuando
    #    el TOTAL publicado es igual a la suma de las entidades listadas: su personal es cero. Caso
    #    conocido: la Financiera Edyficar residual de 2015-03 a 2015-11 (sin créditos; tras la
    #    fusión con Mibanco), que el cuadro lista con 0 en algunos meses y omite en otros.
    tot = load_staff_totals()
    listed = load_staff().groupby(["periodo", "subsistema"])["np"].sum()
    ok = (tot - listed.reindex(tot.index)).abs() < 0.5
    covered = pd.Series(list(zip(w["periodo"], w["subsistema"])), index=w.index).map(ok).eq(True)
    #    Si la entidad sigue operando (tiene créditos, o el cuadro la vuelve a listar después con personal),
    #    no es cero: el cuadro la omite (la CRAC Nuestra Gente de 2013-01 a 2013-04, con ~1.566 trabajadores
    #    en 2012-12; Amérika Financiera 2013-08/09, sin créditos pero con 12 trabajadores en 2013-07 y 9 en
    #    2013-10). Se arrastra su último personal publicado (también por categoría, en `build_mix`) y se suma
    #    al agregado. Edyficar residual (sin créditos, listada con 0 en los meses intermedios) queda en cero.
    absent = w["np"].isna() & covered
    staff = load_staff().sort_values("periodo")
    def next_staff(i: int) -> float:
        nxt = staff[(staff["id_entidad"] == w.at[i, "id_entidad"]) & (staff["periodo"] > w.at[i, "periodo"])]
        return float(nxt["np"].iloc[0]) if len(nxt) else 0.0
    carry = absent & ((w["cd"] > 0) | pd.Series({i: next_staff(i) > 0 for i in w.index[absent]}, dtype=bool).reindex(w.index, fill_value=False))
    zero = absent & ~carry
    if zero.any():
        w.loc[zero, "np"] = 0.0
        for (sub, ent), g in w[zero].groupby(["subsistema", "id_entidad"]):
            print(f"  Personal = 0 (ausente del cuadro, sin créditos ni personal después, total cuadra): {sub} {ent}, {len(g)} meses ({g['periodo'].min()}-{g['periodo'].max()})")
    if carry.any():
        for i in w.index[carry]:
            per, ent = int(w.at[i, "periodo"]), w.at[i, "id_entidad"]
            prev = staff[(staff["id_entidad"] == ent) & (staff["periodo"] < per)]
            if prev.empty:
                continue
            src = prev.iloc[-1]
            w.at[i, "np"] = src["np"]
            CARRIED.append({"periodo": per, "subsistema": w.at[i, "subsistema"], "id_entidad": ent,
                            "src_periodo": int(src["periodo"]), "src_subsistema": src["subsistema"]})
        c = pd.DataFrame(CARRIED)
        for (sub, ent, sp), g in c.groupby(["subsistema", "id_entidad", "src_periodo"]):
            print(f"  Personal arrastrado (ausente del cuadro, sigue operando): {sub} {ent}, {len(g)} meses"
                  f" ({g['periodo'].min()}-{g['periodo'].max()}) con el de {sp}")
    miss = w["np"].isna()
    if not miss.any():
        return w
    whole = w.assign(m=miss).groupby(["periodo", "subsistema"])["m"].transform("all")
    # Solo huecos dentro de la serie: el mes más reciente sin cuadro (aún no publicado) queda vacío.
    last = w[~miss].groupby("subsistema")["periodo"].max()
    inside = w["periodo"] < w["subsistema"].map(last).fillna(0)
    # Solo donde el indicador publicado usa el total del personal (banca y financieras).
    basis_total = w["subsistema"].map(PUB_BASIS).eq("total")
    cand = w[miss & whole & inside & basis_total]
    if cand.empty:
        return w
    cd, pub = credits_basis(), published_per_employee()
    key = list(zip(cand["periodo"], cand["subsistema"].astype(str), cand["id_entidad"].astype(str)))
    est = pd.Series([cd.get(k, np.nan) / pub.get(k, np.nan) if pub.get(k, 0) else np.nan for k in key], index=cand.index).round()
    w.loc[cand.index, "np"] = est
    for (per, sub), g in w.loc[cand.index].groupby(["periodo", "subsistema"]):
        IMPUTED.append({"m": month_key(int(per)), "s": str(sub), "n": int(g["np"].notna().sum()), "f": int(g["np"].isna().sum())})
        print(f"  Personal imputado con el indicador publicado: {sub} {per}, {int(g['np'].notna().sum())} entidades"
              f" ({int(g['np'].isna().sum())} sin indicador)")
    return w


def load_staff() -> pd.DataFrame:
    """Personal total a fin de mes por (periodo, subsistema, entidad): columna `np` (número)."""
    d = read_table(BOLETIN / f"{STAFF}.parquet",
                        columns=["periodo", "subsistema", "id_entidad", "es_total", "variable", "apertura", "valor"])
    d = d[(~d["es_total"]) & (d["variable"] == "numero_personal") & (d["apertura"] == "total")]
    d = d.assign(id_entidad=d["id_entidad"].astype(str), subsistema=d["subsistema"].astype(str))
    s = d.groupby(["periodo", "subsistema", "id_entidad"])["valor"].agg(["sum", "count"])
    if (s["count"] > 1).any():
        raise ValueError("personal: más de una fila por entidad y mes")
    return s["sum"].rename("np").reset_index()


def rolling_block(g: pd.DataFrame) -> pd.DataFrame:
    """Para una serie mensual (índice t, una fila por mes, puede tener huecos) devuelve los flujos de
    12 meses y los promedios de 12 meses. Vacío si falta alguno de los meses que se necesitan."""
    t0, t1 = int(g.index.min()), int(g.index.max())
    g = g.reindex(range(t0, t1 + 1))
    if "rw" not in g:
        g["rw"] = g["rn"]
    out = pd.DataFrame(index=g.index)
    month = (g.index % 12) + 1
    for k in FLOW_KEYS + ["rw"]:
        acc = g[k]
        dec = acc.reindex(g.index - month).to_numpy()        # diciembre del año anterior
        prev = acc.reindex(g.index - 12).to_numpy()          # mismo mes del año anterior
        f = acc.to_numpy() + dec - prev
        out[k] = np.where(month == 12, acc.to_numpy(), f)
    for src, dst in (("ac", "A"), ("pa", "P"), ("cd", "C")):
        out[dst] = g[src].rolling(12, min_periods=12).mean()
    for k in ("ac", "pa", "cd", "at", "ut", "np"):
        out[k] = g[k]
    out["Ts"] = g["np"].rolling(12, min_periods=12).sum()   # vacío si falta algún conteo
    return out


def scope_series(rows: pd.DataFrame, full: pd.DataFrame | None = None) -> pd.DataFrame:
    """Serie mensual (índice t) de un agregado a partir de las filas de sus entidades.

    Saldos: suma de las entidades presentes ese mes. Partidas del estado de resultados: además, una
    entidad que sale del agregado durante el año conserva su último acumulado hasta diciembre (así
    sus resultados de enero a la salida no se pierden del flujo de 12 meses). Es la regla con la
    que se reproduce el ROE publicado por la SBS en los meses posteriores a una salida.

    `rw` (numerador de la utilidad por trabajador): como `rn`, pero a una entidad que ENTRA al
    agregado a mitad de año se le resta, hasta diciembre, el acumulado que traía del mes anterior a
    la entrada (tomado de `full`, todas las filas). Así la utilidad y el personal cubren los mismos
    meses: el personal de la entidad solo cuenta desde que entra."""
    base = rows.groupby("t")[["ac", "pa", "cd", "at", "ut"]].sum()
    # Personal: solo si todas las entidades del agregado tienen el conteo ese mes.
    staff = rows.groupby("t")["np"].agg(["sum", "count", "size"])
    base["np"] = staff["sum"].where(staff["count"] == staff["size"])
    ts = pd.Index(range(int(rows["t"].min()), int(rows["t"].max()) + 1), name="t")
    out = base.reindex(ts)
    year = ts // 12
    for k in FLOW_KEYS:
        p = rows.pivot_table(index="t", columns="id_entidad", values=k, aggfunc="sum").reindex(ts)
        p = p.groupby(year).ffill()   # arrastra el último acumulado dentro del mismo año
        out[k] = p.sum(axis=1, min_count=1)
    p = rows.pivot_table(index="t", columns="id_entidad", values="rn", aggfunc="sum").reindex(ts)
    if full is not None:
        own = full.pivot_table(index="t", columns="id_entidad", values="rn", aggfunc="sum")
        for ent in p.columns:
            inside = set(rows.loc[rows["id_entidad"] == ent, "t"])
            for te in sorted(inside):
                prev = te - 1
                if prev in inside or te % 12 == 0:   # no es entrada, o entra en enero (acumulado en cero)
                    continue
                pre = own[ent].get(prev, np.nan) if ent in own else np.nan
                if pd.isna(pre):                     # sin historia previa (entidad nueva): nada que restar
                    continue
                dec = (te // 12) * 12 + 11
                mask = (p.index >= te) & (p.index <= dec) & p[ent].notna()
                p.loc[mask, ent] = p.loc[mask, ent] - pre
    p = p.groupby(year).ffill()
    out["rw"] = p.sum(axis=1, min_count=1)
    return out


def to_block(df: pd.DataFrame, t_first: int, months_t: list[int]) -> dict:
    """{a: índice del primer mes con dato, V: [[valores por mes] por campo en el orden de FIELDS]}."""
    pos = {t: i for i, t in enumerate(months_t)}
    present = df.index[df["ac"].notna()]
    a, b = pos[int(present.min())], pos[int(present.max())]
    rng = months_t[a:b + 1]
    V = []
    for f in FIELDS:
        s = df[f].reindex(rng)
        V.append([None if pd.isna(x) else int(round(float(x))) for x in s])
    return {"a": a, "V": V}


# ---------------------------------------------------------------- cifras repetidas en la serie de la entidad
REPEAT_TEMAS = ("estados-financieros", STAFF)   # cuadros de los que salen los campos de la serie de entidad


def t_of(p: int) -> int:
    """AAAAMM → mes correlativo (el `t` de `load_statements`)."""
    return (p // 100) * 12 + p % 100 - 1


def p_of(t: int) -> int:
    """Mes correlativo → AAAAMM."""
    return (t // 12) * 100 + t % 12 + 1


def month_short(p: int) -> str:
    """AAAAMM → «mar-2016» (como `mShort` de la página)."""
    return ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "set", "oct", "nov", "dic"][p % 100 - 1] + f"-{p // 100}"


def entity_repeats(w: pd.DataFrame) -> dict[str, dict[int, dict]]:
    """{id_entidad: {t: entrada de RANKING_REPEATS}} de las entidad-mes de `w` en que la SBS repite las cifras de otro
    mes en el estado financiero y el cuadro de personal (`errores_origen.source_repeats`, «row» = all). CMAC Pisco
    2014-01 → 04 ya no está en `w` (`drop_repeated`)."""
    keys = set(zip(w["periodo"].astype(int), w["subsistema"].astype(str), w["id_entidad"].astype(str)))
    out: dict[str, dict[int, dict]] = {}
    for tema in REPEAT_TEMAS:
        for (per, sub, ent), r in source_repeats(tema).items():
            if (per, sub, ent) in keys:
                out.setdefault(ent, {})[t_of(per)] = r
    return out


def flow_blocked(ts, rep_t: set[int]) -> np.ndarray:
    """Meses cuyo flujo de 12 meses usa el acumulado de un mes repetido: el propio mes, o (salvo en diciembre) el
    diciembre anterior o el mismo mes del año anterior."""
    t = np.asarray(ts)
    month = t % 12 + 1
    reps = list(rep_t)
    own = np.isin(t, reps)
    base = (month != 12) & (np.isin(t - month, reps) | np.isin(t - 12, reps))
    return own | base


def entity_block(g: pd.DataFrame, rep_t: set[int]) -> pd.DataFrame:
    """`rolling_block` de UNA entidad sin las cifras que la SBS repitió de otro mes (`rep_t`, meses correlativos).
    Regla (2026-11-03):
    - en el mes repetido, todos los campos quedan vacíos (la página muestra el último dato válido y el motivo);
    - flujos de 12 meses: vacíos en los meses que usan el acumulado de un mes repetido (`flow_blocked`: el mes y el
      mismo mes del año siguiente; ninguno de los casos es un diciembre). No hay otra forma de calcularlos;
    - promedios de 12 meses (activo, patrimonio, créditos y personal): con los meses válidos de la ventana; el mes
      repetido no cuenta (se exigen todos los demás). Así el ROE de los 12 meses siguientes no queda vacío.
    Los agregados no pasan por aquí: la SBS suma esas cifras en sus totales y con ellas se reproduce el ROE publicado."""
    r = rolling_block(g)
    if not rep_t:
        return r
    rep_t = set(rep_t)
    r.loc[flow_blocked(r.index, rep_t), FLOW_KEYS + ["rw"]] = np.nan
    gg = g.reindex(r.index)
    is_rep = pd.Series(gg.index.isin(list(rep_t)), index=gg.index)
    for src, dst in (("ac", "A"), ("pa", "P"), ("cd", "C"), ("np", "Ts")):
        clean = gg[src].where(~is_rep)
        mean = clean.rolling(12, min_periods=1).mean()
        ok = (clean.notna() | is_rep).astype(float).rolling(12, min_periods=12).sum().eq(12)
        r[dst] = (mean * (12 if dst == "Ts" else 1)).where(ok)
    r.loc[is_rep.to_numpy(), :] = np.nan
    return r


def repeat_rows(reps: dict[str, dict[int, dict]], w: pd.DataFrame) -> list[list]:
    """Lista para la página: [mes, «subsistema/entidad», mes repetido, alcance, motivo]. Alcance «fila»: el mes con las
    cifras de otro mes (sin dato propio); «flujo»: un mes con balance propio cuyo flujo de 12 meses usaría el acumulado
    repetido (en el tercer campo, ese mes repetido)."""
    out = []
    span = w.groupby("id_entidad")["t"].agg(["min", "max"])
    sub_at = w.set_index(["id_entidad", "t"])["subsistema"]
    for ent, d in sorted(reps.items()):
        lo, hi = span.loc[ent]
        ts = np.arange(int(lo), int(hi) + 1)
        for t, r in sorted(d.items()):
            note = repeat_footnote(r)
            out.append([month_key(p_of(t)), f"{r['subsistema']}/{ent}", month_key(r["same_as"]), "fila",
                        "nota al pie del cuadro: " + note if note else "sin nota al pie"])
        for t in ts[flow_blocked(ts, set(d))]:
            t = int(t)
            if t in d or (ent, t) not in sub_at.index:
                continue
            base = next(b for b in sorted(d) if b in (t - 12, t - (t % 12 + 1)))
            r = d[base]
            note = repeat_footnote(r)
            out.append([month_key(p_of(t)), f"{sub_at[(ent, t)]}/{ent}", month_key(p_of(base)), "flujo",
                        f"en {month_short(p_of(base))} la SBS repitió las cifras de {month_short(r['same_as'])}"
                        + ("; nota al pie: " + note if note else "")])
    return out


def build_mix(months: list[int], entities: list[str], reps: dict[str, dict[int, dict]] | None = None) -> dict:
    """Personal por categoría a fin de mes: {ámbito: {a, V: [[gerentes], [funcionarios], [empleados], [otros]]}}.
    Entidades: las filas del cuadro en los meses en que la entidad está en ese subsistema. Subsistemas:
    suma de las entidades listadas. Sistema: suma de los subsistemas, solo si los cinco tienen cuadro."""
    d = read_table(BOLETIN / f"{STAFF}.parquet",
                        columns=["periodo", "subsistema", "id_entidad", "es_total", "variable", "apertura", "valor"])
    d = d[(~d["es_total"]) & (d["variable"] == "numero_personal")]
    d = d.assign(id_entidad=d["id_entidad"].astype(str), subsistema=d["subsistema"].astype(str))
    e = d.pivot_table(index=["periodo", "subsistema", "id_entidad"], columns="apertura", values="valor", aggfunc="sum")
    # Guion («-», solo en financieras) = cero: con ceros, las cuatro categorías suman el total en todas las filas.
    e[MIX_CATS] = e[MIX_CATS].fillna(0)
    # Entidad-mes ausentes del cuadro con personal arrastrado (impute_staff): también sus categorías.
    if CARRIED:
        add = [e.loc[(c["src_periodo"], c["src_subsistema"], c["id_entidad"])].rename((c["periodo"], c["subsistema"], c["id_entidad"]))
               for c in CARRIED]
        e = pd.concat([e, pd.DataFrame(add)]).sort_index()
        e.index.names = ["periodo", "subsistema", "id_entidad"]
    bad = (e[MIX_CATS].sum(axis=1) - e["total"]).abs() > 0.5
    if bad.any():
        raise ValueError(f"personal: {int(bad.sum())} filas en que las categorías no suman el total")

    def block(df: pd.DataFrame) -> dict | None:
        df = df.reindex(months)
        present = df.index[df[MIX_CATS].notna().all(axis=1)]
        if present.empty:
            return None
        a, b = months.index(int(present.min())), months.index(int(present.max()))
        rng = months[a:b + 1]
        return {"a": a, "V": [[None if pd.isna(x) else int(round(float(x))) for x in df.loc[rng, c]] for c in MIX_CATS]}

    out: dict[str, dict] = {}
    subs = e.groupby(level=["periodo", "subsistema"])[MIX_CATS].sum()
    for sub, _, _ in SUBSYSTEMS:
        if sub in subs.index.get_level_values("subsistema"):
            out[sub] = block(subs.xs(sub, level="subsistema"))
    n_subs = subs.groupby(level="periodo").size()
    sysm = subs.groupby(level="periodo").sum()
    sysm.loc[n_subs[n_subs < len(SUBSYSTEMS)].index, :] = np.nan
    out["sistema"] = block(sysm)
    pairs = set(e.index.droplevel("periodo"))
    for k in entities:
        sub, ent = k.split("/", 1)
        if (sub, ent) in pairs:
            b = block(e.xs((sub, ent), level=["subsistema", "id_entidad"])[MIX_CATS])
            if b:
                # Meses en que la SBS repitió las cifras de otro mes (`entity_repeats`): sin categorías.
                for t in (reps or {}).get(ent, {}):
                    j = months.index(p_of(t)) - b["a"] if p_of(t) in months else -1
                    if 0 <= j < len(b["V"][0]):
                        for v in b["V"]:
                            v[j] = None
                out[k] = b
    return {k: v for k, v in out.items() if v}


def check_mix(data: dict) -> None:
    """La suma de las categorías debe ser igual al personal total del ámbito (`np`). Los meses con
    personal estimado no tienen categorías y no se comparan."""
    fi = {f: i for i, f in enumerate(data["fields"])}
    print("  Composición del personal: suma de categorías vs. personal total del ámbito:")
    for sc in ["sistema"] + [s for s, _, _ in SUBSYSTEMS] + data["entities"]:
        mx, s = data["mix"].get(sc), data["scopes"][sc]
        if not mx:
            continue
        diffs = []
        n_ok = 0
        for j in range(len(mx["V"][0])):
            i = mx["a"] + j
            v = [mx["V"][c][j] for c in range(4)]
            k = i - s["a"]
            if None in v or k < 0 or k >= len(s["V"][0]):
                continue
            np_ = s["V"][fi["np"]][k]
            if np_ is not None and sum(v) == np_:
                n_ok += 1
            elif np_ is not None:
                diffs.append(f"{data['months'][i]}: {sum(v)} vs {np_}")
        if sc in ("sistema", *(x for x, _, _ in SUBSYSTEMS)):
            print(f"    {sc:22s} {n_ok} meses iguales, {len(diffs)} distintos" + (f": {'; '.join(diffs[:5])}" if diffs else ""))
        elif diffs:
            print(f"    {sc}: {len(diffs)} meses distintos: {'; '.join(diffs[:3])}")


def build_ptu(w: pd.DataFrame) -> list[dict]:
    """Participación legal de los trabajadores por entidad y ejercicio (EEFF auditados), con el
    subsistema de diciembre, el personal promedio del año y la utilidad antes de IR de diciembre."""
    p = pd.read_csv(PTU_FILE, dtype={"id_entidad": str})
    p = p[(p["ejercicio"] >= 2022) & ~((p["participacion_miles"] == 0) & (p["cero"] == "sin_linea"))]
    rows = []
    for r in p.itertuples():
        y = int(r.ejercicio)
        g = w[(w["id_entidad"] == r.id_entidad) & (w["t"] // 12 == y)]
        dec = g[g["t"] == y * 12 + 11]
        if dec.empty:
            print(f"  Participación: {r.id_entidad} {y} sin estados de diciembre en el Boletín; se omite")
            continue
        staff = g.groupby("t")["np"].sum(min_count=1)
        n = float(staff.mean()) if len(staff) == 12 and staff.notna().all() else None
        rows.append({
            "k": f"{dec['subsistema'].iloc[0]}/{r.id_entidad}", "y": y, "p": round(float(r.participacion_miles), 1),
            "ad": None if pd.isna(r.adicional_miles) else round(float(r.adicional_miles), 1), "al": r.alcance,
            "z": None if pd.isna(r.cero) else r.cero, "n": None if n is None else round(n, 1),
            "U": round(float((dec["rn"] + dec["ir"]).iloc[0]), 1), "u": r.fuente_url, "loc": r.ubicacion,
        })
    return rows


def load_published() -> pd.DataFrame:
    """ROE y ROA publicados por la SBS para el total de cada subsistema."""
    d = read_table(BOLETIN / "indicadores-financieros.parquet")
    d = d[d["es_total"] & d["variable"].isin(["roe", "roa"])]
    return d.pivot_table(index=["periodo", "subsistema"], columns="variable", values="valor", aggfunc="first")


def build_data() -> dict:
    w = load_statements()
    months = month_range(int(w["periodo"].min()), int(w["periodo"].max()))
    months_t = [(m // 100) * 12 + m % 100 - 1 for m in months]
    base_cols = FLOW_KEYS + ["ac", "pa", "cd", "at", "ut", "np"]

    scopes: dict[str, dict] = {}
    # Subsistemas: entidades del subsistema (saldos = total del cuadro), luego flujos y promedios.
    for sub, label, short in SUBSYSTEMS:
        r = rolling_block(scope_series(w[w["subsistema"] == sub], full=w))
        scopes[sub] = {"n": label, "s": sub, **to_block(r, months_t[0], months_t)}
    # Sistema: todas las entidades con la misma regla. No es la suma de los subsistemas: una entidad
    # que cambia de subsistema a mitad de año se contaría dos veces (en el que deja y en el nuevo).
    # Llega hasta el último mes que publicaron los cinco subsistemas (si uno se atrasa, faltaría entero).
    sys_end = int(w.groupby("subsistema")["periodo"].max().min())
    sysr = rolling_block(scope_series(w[w["periodo"] <= sys_end], full=w))
    scopes["sistema"] = {"n": "Sistema financiero", "s": None, **to_block(sysr, months_t[0], months_t)}

    # Entidades: flujos y promedios con su propia historia (aunque cambie de subsistema); la serie se
    # muestra en cada subsistema solo en los meses en que perteneció a él.
    names = pd.read_csv(ENTIDADES, dtype=str).set_index("id_entidad")["nombre_actual"]
    panel = read_table(PROJECT_DIR / "data" / "processed" / "panel_entidad_mes.parquet",
                            columns=["periodo", "subsistema", "id_entidad", "nombre_entidad"])
    last_name = panel.sort_values("periodo").groupby(["subsistema", "id_entidad"])["nombre_entidad"].last()
    entities = []
    # Serie de la entidad sin las cifras repetidas de otro mes (`entity_block`); los agregados de arriba las suman.
    reps = entity_repeats(w)
    for ent, g in w.groupby("id_entidad"):
        r = entity_block(g.set_index("t")[base_cols], set(reps.get(ent, {})))
        for sub in g["subsistema"].unique():
            ts = set(g.loc[g["subsistema"] == sub, "t"])
            rr = r.copy()
            rr.loc[~rr.index.isin(ts), :] = np.nan
            if rr["ac"].fillna(0).abs().sum() == 0:   # sin activos en todo el periodo
                continue
            k = f"{sub}/{ent}"
            scopes[k] = {"n": last_name.get((sub, ent)) or names.get(ent, ent), "s": sub, **to_block(rr, months_t[0], months_t)}
            entities.append(k)
    by_id: dict[str, list[str]] = {}
    for k in entities:
        by_id.setdefault(k.split("/", 1)[1], []).append(k)
    for ks in by_id.values():
        if len(ks) > 1:
            for k in ks:
                scopes[k]["o"] = [x for x in ks if x != k]

    # ROE y ROA publicados por subsistema (control y tabla de la metodología).
    pub = load_published()
    published = {}
    for sub, _, _ in SUBSYSTEMS:
        published[sub] = {
            v: [None if pd.isna(pub[v].get((m, sub), np.nan)) else round(float(pub[v].get((m, sub))), 2) for m in months]
            for v in ("roe", "roa")
        }

    return {
        "months": [month_key(m) for m in months],
        "fields": FIELDS,
        "subs": [{"k": k, "l": l, "s": s} for k, l, s in SUBSYSTEMS],
        "scopes": scopes,
        "entities": entities,
        "pub": published,
        "mix": build_mix(months, entities, reps),
        "ptu": build_ptu(w),
        "hasta": month_key(months[-1]),
        "allHasta": month_key(sys_end),   # último mes con los cinco subsistemas (el del sistema); mes inicial del tablero
        # Cifras repetidas de otro mes en la serie de la entidad: [mes, ámbito, mes repetido, «fila» | «flujo», motivo].
        "rep": repeat_rows(reps, w),
        "generado": dt.date.today().isoformat(),
    }


def check_published(data: dict) -> None:
    """Imprime el ajuste del ROE propio con el publicado por la SBS (2010-2015 y desde 2016, por separado) y el
    ROE y ROA del último mes, propio vs. publicado."""
    fi = {f: i for i, f in enumerate(data["fields"])}
    last = len(data["months"]) - 1
    for lo, hi in (("2010-07", "2015-12"), ("2016-01", "9999-12")):
        print(f"  Ajuste del ROE con el publicado, {lo} a {min(hi, data['hasta'])} (meses: dif. <= 0,05 pp, <= 0,5 pp, max.):")
        for sub, label, _ in SUBSYSTEMS:
            s, pub = data["scopes"][sub], data["pub"][sub]["roe"]
            d = []
            for i, m in enumerate(data["months"]):
                j = i - s["a"]
                if not lo <= m <= hi or j < 0 or pub[i] is None:
                    continue
                rn, P = s["V"][fi["rn"]][j], s["V"][fi["P"]][j]
                if rn is not None and P:
                    d.append((m, abs(100 * rn / P - pub[i])))
            v = np.array([x for _, x in d])
            worst = sorted(d, key=lambda z: -z[1])[:3]
            print(f"    {label:22s} n={len(v):3d}  {100 * (v <= 0.05).mean():5.1f} % / {100 * (v <= 0.5).mean():5.1f} % / {v.max():.2f} pp"
                  f"  peores: {', '.join(f'{m} {x:.2f}' for m, x in worst)}")
    print(f"  Control {data['hasta']} (cálculo propio vs. SBS):")
    for sub, label, _ in SUBSYSTEMS + [("sistema", "Sistema", "")]:
        s = data["scopes"][sub]
        # Un subsistema que todavía no publica el último mes se controla con su último mes propio.
        j = min(last - s["a"], len(s["V"][fi["rn"]]) - 1)
        i = j + s["a"]
        rn, A, P = (s["V"][fi[k]][j] for k in ("rn", "A", "P"))
        if rn is None or not A or not P:
            print(f"    {label:22s} sin dato en {data['months'][i]}")
            continue
        roe, roa = 100 * rn / P, 100 * rn / A
        p = data["pub"].get(sub, {"roe": [None] * (last + 1), "roa": [None] * (last + 1)})
        pr, pa = p["roe"][i], p["roa"][i]
        txt = f"    {label:22s} ROE {roe:6.2f}  ROA {roa:5.2f}" + (f"  ({data['months'][i]})" if i != last else "")
        if pr is not None:
            txt += f"   publicado ROE {pr:6.2f}  ROA {pa:5.2f}   (dif. {roe - pr:+.2f} / {roa - pa:+.2f})"
        print(txt)


def check_entities(data: dict) -> None:
    """Imprime el ajuste del ROE propio de cada entidad con el publicado (dif. < 0,1 pp), por periodo."""
    fi = {f: i for i, f in enumerate(data["fields"])}
    d = read_table(BOLETIN / "indicadores-financieros.parquet", columns=["periodo", "subsistema", "id_entidad", "es_total", "variable", "valor"])
    d = d[(~d["es_total"]) & (d["variable"] == "roe")]
    pub = d.assign(k=d["subsistema"].astype(str) + "/" + d["id_entidad"].astype(str)).groupby(["k", "periodo"])["valor"].first()
    months = [int(m.replace("-", "")) for m in data["months"]]
    res: dict[str, list[float]] = {"2010-2015": [], "2016+": []}
    for k in data["entities"]:
        s = data["scopes"][k]
        for j in range(len(s["V"][0])):
            i = s["a"] + j
            rn, P = s["V"][fi["rn"]][j], s["V"][fi["P"]][j]
            p = pub.get((k, months[i]))
            if rn is None or not P or p is None or pd.isna(p):
                continue
            res["2016+" if months[i] >= 201601 else "2010-2015"].append(abs(100 * rn / P - p))
    for per, v in res.items():
        v = np.array(v)
        print(f"  ROE por entidad vs. publicado, {per}: {len(v)} entidad-mes, {100 * (v < 0.1).mean():.1f} % a menos de 0,1 pp")


def check_staff(data: dict) -> dict:
    """Controles del personal: (1) total de cada subsistema armado con las entidades del balance vs.
    el TOTAL publicado en el cuadro de personal; (2) créditos directos / personal por entidad vs.
    el indicador publicado. Imprime el resultado y lo devuelve para la página."""
    fi = {f: i for i, f in enumerate(data["fields"])}
    d = read_table(BOLETIN / f"{STAFF}.parquet", columns=["periodo", "subsistema", "es_total", "variable", "apertura", "valor"])
    d = d[d["es_total"] & (d["variable"] == "numero_personal") & (d["apertura"] == "total")]
    tot = d.assign(subsistema=d["subsistema"].astype(str)).groupby(["periodo", "subsistema"])["valor"].first()
    months = [int(m.replace("-", "")) for m in data["months"]]
    print("  Personal: total del subsistema (entidades del balance) vs. TOTAL del cuadro de personal:")
    out = {"tot": {}}
    for sub, label, _ in SUBSYSTEMS:
        s = data["scopes"][sub]
        n = same = 0
        diffs = []
        for i, m in enumerate(months):
            j = i - s["a"]
            if j < 0 or j >= len(s["V"][0]) or (m, sub) not in tot.index:
                continue
            v = s["V"][fi["np"]][j]
            if v is None:
                continue
            n += 1
            if v == tot[(m, sub)]:
                same += 1
            else:
                diffs.append(f"{m}: {v} vs {int(tot[(m, sub)])}")
        out["tot"][sub] = [same, n]
        print(f"    {label:22s} {same}/{n} meses iguales" + (f"; distintos: {'; '.join(diffs[:6])}" if diffs else ""))
    cd = credits_basis()
    pub = published_per_employee()
    st = read_table(BOLETIN / f"{STAFF}.parquet", columns=["periodo", "subsistema", "id_entidad", "es_total", "variable", "apertura", "valor"])
    st = st[(~st["es_total"]) & (st["variable"] == "numero_personal") & st["apertura"].isin(["total", "empleados"])]
    st = st.assign(id_entidad=st["id_entidad"].astype(str), subsistema=st["subsistema"].astype(str))
    st = st.pivot_table(index=["periodo", "subsistema", "id_entidad"], columns="apertura", values="valor", aggfunc="sum")
    x = st.join(cd.rename("cd"), how="inner").join(pub.rename("pub"), how="inner").reset_index()
    x = x[x["pub"] > 0]
    out["cpt"] = {}
    print("  Créditos directos / personal vs. indicador publicado por entidad (a menos de 1 %):")
    for sub, label, _ in SUBSYSTEMS:
        g = x[x["subsistema"] == sub]
        res = {}
        for base in ("total", "empleados"):
            r = (g["cd"] / g[base] / g["pub"] - 1).abs()
            res[base] = [int((r <= 0.01).sum()), int(r.notna().sum())]
        out["cpt"][sub] = {"base": PUB_BASIS[sub], **res}
        print(f"    {label:22s} con el total: {res['total'][0]}/{res['total'][1]}; con «empleados»: {res['empleados'][0]}/{res['empleados'][1]}"
              f" (base esperada: {PUB_BASIS[sub]})")
    return out


def main() -> int:
    print("Armando datos de rentabilidad...")
    data = build_data()
    check_published(data)
    check_entities(data)
    check_mix(data)
    data["staff"] = {"chk": check_staff(data), "imp": IMPUTED}
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    template = TEMPLATE.read_text(encoding="utf-8")
    if PLACEHOLDER not in template:
        print(f"ERROR: la plantilla no tiene el marcador {PLACEHOLDER}")
        return 1
    html = template.replace(PLACEHOLDER, payload)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    OUT_ARTIFACT.write_text(artifact_version(html), encoding="utf-8")
    print(f"  {data['months'][0]} a {data['hasta']}, {len(data['entities'])} series de entidad, datos {len(payload) / 1e6:.1f} MB")
    print(f"  Último mes con los 5 subsistemas (sistema y mes inicial del tablero): {data['allHasta']}")
    print(f"  Escrito {OUT.relative_to(PROJECT_DIR)} y {OUT_ARTIFACT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
