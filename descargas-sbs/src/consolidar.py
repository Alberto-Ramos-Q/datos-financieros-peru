"""Junta las tablas del lector en un dataset maestro y arma el panel entidad × mes.

Parte de `data/processed/boletin/<tema>.parquet` (salida de `leer_boletin.py`) y escribe:

    data/processed/boletin_maestro.parquet     todos los temas en una sola tabla larga, mismas
                                               columnas que cada tema + nombre_entidad
    data/processed/panel_entidad_mes.parquet   una fila por mes × subsistema × entidad (y el
    data/processed/panel_entidad_mes.xlsx      total de cada subsistema), una columna por
                                               indicador de `config/panel.csv`

El maestro tiene más de 10 millones de filas: no cabe en Excel, se usa desde Power BI o pandas.
El panel sí cabe; el Excel trae además una hoja «diccionario» con la definición de cada columna.

Cifras repetidas de otro mes (2026-11-03): en las entidad-mes de `errores_origen.RANKING_REPEATS` la SBS publica
las cifras de un mes anterior (en 8 de ellas en casi todos los cuadros; en CMAC Sullana 2014-11, solo en el
ranking). El maestro queda tal como lo publica la SBS; en el panel, `anular_repeticiones` deja vacías las celdas de
esas entidad-mes que vienen de un tema repetido (también las calculadas con él) y la columna `repite_periodo` dice qué
mes repite la SBS. Las filas del total (`_total`) no cambian: la SBS suma las cifras repetidas en sus totales.

Uso:
    python consolidar.py                      # escribe en data/processed
    python consolidar.py --salida C:/tmp/x    # escribe el maestro y el panel en otra carpeta (para comparar)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))
from entidades import Maestro  # noqa: E402
from errores_origen import RANKING_TEMA, full_row_repeat_keys, repeats_tema, source_repeats  # noqa: E402

TEMAS_DIR = PROJECT_DIR / "data" / "processed" / "boletin"
OUT_DIR = PROJECT_DIR / "data" / "processed"
PANEL_CSV = PROJECT_DIR / "config" / "panel.csv"
# Entidades estatales (p=12), aparte: ver `consolidar_estatales`.
TEMAS_DIR_ESTATALES = PROJECT_DIR / "data" / "processed" / "boletin_estatales"
PANEL_ESTATALES_CSV = PROJECT_DIR / "config" / "panel_estatales.csv"
ENTIDADES_PANEL_ESTATAL = ["banco-de-la-nacion", "agrobanco"]
ENTIDADES_ESTATALES = {"banco-de-la-nacion", "agrobanco", "cofide", "fondo-mivivienda"}
SERIES_CSV = PROJECT_DIR / "config" / "series.csv"

CLAVE = ["periodo", "subsistema", "id_entidad"]
ID_TOTAL = "_total"  # id_entidad de la fila del total del subsistema en el panel
# Historia 2010-07 → 2014-12 (extensión del 2026-10-28): antes de este mes, y solo donde falta el
# cuadro, se usan sustitutos marcados (ver `sustituir_posicion_global`).
INICIO_SIN_SUSTITUTOS = 201501
NOMBRE_SUBSISTEMA = {
    "banca-multiple": "Banca múltiple",
    "empresas-financieras": "Empresas financieras",
    "cajas-municipales": "Cajas municipales",
    "cajas-rurales": "Cajas rurales",
    "empresas-credito": "Empresas de créditos",
}
# Calculados en `calculados()` desde otros cuadros: columna -> (pilar, descripción, unidad, tema SBS).
CALCULADOS = {
    "numero_depositantes": ("liquidez", "Número de personas con depósitos en la entidad (suma de personas naturales, "
                            "jurídicas sin fines de lucro y otras jurídicas en «Depósitos totales»)",
                            "numero", "depositantes-tipo-deposito"),
    "deposito_promedio_depositante": ("liquidez", "Depósitos totales / número de depositantes, en soles: "
                                      "concentración por entidad (la SBS no publica los 20 principales depositantes)",
                                      "soles", "depositantes-tipo-deposito"),
    "depositos_hasta_1fsd": ("liquidez", "Depósitos en tramos de saldo de hasta 1 vez la cobertura del FSD / "
                             "depósitos totales. Solo en la fila del total: la SBS publica la escala por subsistema",
                             "porcentaje", "depositos-escala-montos"),
    "depositos_mas_10fsd": ("liquidez", "Depósitos en tramos desde 10 veces la cobertura del FSD / depósitos "
                            "totales: concentración en grandes depositantes (solo fila del total)",
                            "porcentaje", "depositos-escala-montos"),
    "depositos_mas_100fsd": ("liquidez", "Depósitos en el tramo desde 100 veces la cobertura del FSD / "
                             "depósitos totales (solo fila del total del subsistema)",
                             "porcentaje", "depositos-escala-montos"),
    "dolarizacion_creditos": ("sensibilidad", "Créditos brutos en ME / créditos brutos (vigentes + refinanciados "
                              "y reestructurados + atrasados), desde el balance", "porcentaje", "estados-financieros"),
    "dolarizacion_depositos": ("sensibilidad", "Obligaciones con el público en ME / obligaciones con el público, "
                               "desde el balance (EC no capta depósitos)", "porcentaje", "estados-financieros"),
    "activo_me": ("sensibilidad", "Activo en ME / activo total, desde el balance", "porcentaje", "estados-financieros"),
    "pasivo_me": ("sensibilidad", "Pasivo en ME / pasivo total, desde el balance", "porcentaje", "estados-financieros"),
    "capital_nivel1_pe": ("solvencia", "Patrimonio efectivo de nivel 1 / patrimonio efectivo total: calidad del capital "
                          "(desde 2023, nivel 1 = capital ordinario + adicional)", "porcentaje",
                          "estructura-patrimonio-efectivo"),
    "concentracion_sectorial_hhi": ("sensibilidad", "Índice Herfindahl-Hirschman de los créditos a actividades "
                                    "empresariales por sector económico (0-10.000; >2.500 = concentrado). No depende "
                                    "de los rótulos de sector, que cambiaron a CIIU Rev. 4", "indice",
                                    "creditos-sector-economico"),
    "sector_principal": ("sensibilidad", "Participación del sector con más créditos empresariales en la entidad",
                         "porcentaje", "creditos-sector-economico"),
}
# Indicadores calculados a partir de columnas del panel: columna -> (numerador, denominador, pilar, descripción).
DERIVADAS = {
    "disponible_activo": ("disponible", "activo_total", "liquidez",
                          "Disponible / activo total (calculado desde el balance; todos los subsistemas)"),
    "creditos_depositos": ("creditos_directos", "depositos_totales", "liquidez",
                           "Créditos directos / depósitos totales (calculado; EC no capta depósitos)"),
    "posicion_global_me_pe": ("posicion_global_me", "patrimonio_efectivo", "sensibilidad",
                              "Posición global en ME / patrimonio efectivo: exposición cambiaria (calculado; el "
                              "ratio publicado en los indicadores de cajas y EC no es PG(t)/PE(t) desde 2026-03)"),
    "requerimiento_mercado_pe": ("requerimiento_riesgo_mercado", "patrimonio_efectivo", "sensibilidad",
                                 "Requerimiento de patrimonio por riesgo de mercado / patrimonio efectivo (calculado)"),
}


# Partidas del balance (apertura mn/me/total) que se suman para cada indicador de dolarización.
BALANCE_ME = {
    "creditos_vigentes": "dolarizacion_creditos",
    "creditos_refinanciados_reestructurados": "dolarizacion_creditos",
    "creditos_atrasados": "dolarizacion_creditos",
    "obligaciones_publico": "dolarizacion_depositos",
    "total_activo": "activo_me",
    "total_pasivo": "pasivo_me",
}


def cargar_temas() -> pd.DataFrame:
    partes = []
    for ruta in sorted(TEMAS_DIR.glob("*.parquet")):
        df = pd.read_parquet(ruta)
        df["apertura"] = df["apertura"].fillna("")
        partes.append(df)
        print(f"  {ruta.stem}: {len(df):,} filas")
    df = pd.concat(partes, ignore_index=True)
    # concat pierde las categorías cuando difieren entre temas: se reconstruyen sobre el total.
    return df.astype({c: "category" for c in
                      ["subsistema", "tema", "codigo", "hoja", "entidad_original", "id_entidad",
                       "variable", "apertura", "unidad"]})


def nombres(df: pd.DataFrame, maestro: Maestro) -> pd.Series:
    """Nombre vigente de la entidad en cada periodo (o el nombre actual si no hay vigencia)."""
    pares = df[["id_entidad", "periodo"]].drop_duplicates().dropna()
    def nombre(id_entidad: str, periodo: int) -> str:
        v = maestro.vigencia(id_entidad, int(periodo))
        return v["nombre"] if v else maestro.entidades[id_entidad]["nombre_actual"]
    pares["nombre_entidad"] = [nombre(i, p) for i, p in zip(pares.id_entidad, pares.periodo)]
    out = df[["id_entidad", "periodo"]].merge(pares, how="left", on=["id_entidad", "periodo"])
    out.loc[df.es_total.to_numpy(), "nombre_entidad"] = (
        "Total " + df.loc[df.es_total, "subsistema"].astype(str).map(NOMBRE_SUBSISTEMA).str.lower())
    return out["nombre_entidad"].astype("category").to_numpy()


def _con_clave(df: pd.DataFrame) -> pd.DataFrame:
    df = df.astype({"subsistema": str, "id_entidad": object, "apertura": str})
    df["id_entidad"] = df["id_entidad"].where(~df.es_total, ID_TOTAL)
    return df.dropna(subset=["id_entidad"])


def _limites_fsd(tramo: str) -> tuple[float, float]:
    """'2fsd_a_4fsd' -> (2, 4); 'hasta_0.1fsd' -> (0, 0.1); '100fsd_a_mas' -> (100, inf)."""
    if tramo.startswith("hasta_"):
        return 0.0, float(tramo[6:-3])
    ini, fin = tramo.split("_a_")
    return float(ini[:-3]), float("inf") if fin == "mas" else float(fin[:-3])


def calculados(maestro_df: pd.DataFrame) -> pd.DataFrame:
    """Indicadores que la SBS no publica para todas las entidades, calculados desde los cuadros.

    - cartera_alto_riesgo: (atrasados + refinanciados y reestructurados) / créditos directos,
      desde «Créditos según tipo y situación». Reproduce la morosidad y la CAR publicadas en
      los indicadores de cajas y EC (diferencia ≤ 0,005 pp en el 99 % de los casos).
    - depositos_hasta_1fsd / depositos_mas_10fsd / depositos_mas_100fsd: participación de los
      depósitos en tramos de saldo de hasta 1, desde 10 y desde 100 veces la cobertura del
      Fondo de Seguro de Depósitos («Depósitos según escala de montos», todos los tipos y
      depositantes). Aproximan la concentración de depositantes, pero solo por subsistema: el
      cuadro no se publica por entidad, ni tampoco el ratio de los 20 principales depositantes.
    - capital_nivel1_pe y patrimonio_efectivo_publicado: desde «Estructura del patrimonio
      efectivo» (nivel 1 = capital ordinario + adicional desde 2023; en CMAC, CRAC y EC los
      componentes ya vienen como % del total).
    - concentracion_sectorial_hhi / sector_principal: desde «Créditos a actividades
      empresariales por sector económico» (sectores con saldo negativo cuentan como 0).
    - dolarizacion_creditos / dolarizacion_depositos / activo_me / pasivo_me: apertura «me»
      sobre «total» de las partidas del balance (`BALANCE_ME`).
    """
    partes = []
    sit = _con_clave(maestro_df[(maestro_df.tema == "creditos-tipo-situacion")])
    tipo, situacion = sit.apertura.str.split("|").str[0], sit.apertura.str.split("|").str[1]
    por_sit = sit[tipo != "total"].assign(s=situacion).pivot_table(
        index=CLAVE, columns="s", values="valor", aggfunc="sum")
    total = sit[sit.apertura == "total|total"].set_index(CLAVE).valor
    car = (por_sit.atrasados + por_sit.refinanciados_reestructurados) / total.where(total != 0) * 100
    partes.append(car.rename("cartera_alto_riesgo"))

    esc = maestro_df[(maestro_df.tema == "depositos-escala-montos")
                     & (maestro_df.variable == "depositos")]
    esc = _con_clave(esc[esc.apertura.astype(str).str.startswith("total|total|")])
    tramo = esc.apertura.str.split("|").str[2]
    total = esc[tramo == "total"].set_index(CLAVE).valor
    esc = esc[tramo != "total"]
    limites = tramo[tramo != "total"].map(_limites_fsd)
    for col, filtro in [("depositos_hasta_1fsd", limites.str[1] <= 1),
                        ("depositos_mas_10fsd", limites.str[0] >= 10),
                        ("depositos_mas_100fsd", limites.str[0] >= 100)]:
        suma = esc.assign(v=esc.valor.where(filtro, 0)).groupby(CLAVE).v.sum()
        partes.append((suma / total.where(total != 0) * 100).rename(col))

    dep = _con_clave(maestro_df[(maestro_df.tema == "depositantes-tipo-deposito")
                                & maestro_df.apertura.astype(str).str.startswith("total|")])
    partes.append(dep.groupby(CLAVE).valor.sum().rename("numero_depositantes"))

    pe = _con_clave(maestro_df[maestro_df.tema == "estructura-patrimonio-efectivo"])
    if len(pe):
        comp = pe.pivot_table(index=CLAVE, columns=["variable", "apertura"], values="valor", aggfunc="first")
        total = comp[("patrimonio_efectivo", "total")]

        def nivel1(var):  # era 1: nivel1; era 2: capital ordinario + adicional
            col = lambda a: comp[(var, a)] if (var, a) in comp else pd.Series(float("nan"), comp.index)
            return col("nivel1").fillna(col("capital_ordinario_nivel1") + col("capital_adicional_nivel1").fillna(0))

        # banca y financieras en miles; CMAC, CRAC y EC publican los componentes en % del total
        ratio = (nivel1("patrimonio_efectivo") / total.where(total != 0) * 100).fillna(
            nivel1("participacion_patrimonio_efectivo"))
        partes.append(ratio.rename("capital_nivel1_pe"))
        partes.append(total.rename("patrimonio_efectivo_publicado"))

    sec = _con_clave(maestro_df[(maestro_df.tema == "creditos-sector-economico")])
    sec = sec[sec.apertura != "total"]
    if len(sec):
        part = sec.valor.clip(lower=0) / sec.groupby(CLAVE).valor.transform(lambda v: v.clip(lower=0).sum())
        sec = sec.assign(p=part.where(part.notna()))
        partes.append((sec.assign(p2=sec.p ** 2).groupby(CLAVE).p2.sum(min_count=1) * 10000)
                      .rename("concentracion_sectorial_hhi"))
        partes.append((sec.groupby(CLAVE).p.max() * 100).rename("sector_principal"))

    # Exposición en ME desde el balance: participación de la apertura «me» en el total.
    bal = maestro_df[(maestro_df.tema == "estados-financieros") & maestro_df.variable.isin(BALANCE_ME)
                     & maestro_df.apertura.isin(["me", "total"])]
    bal = _con_clave(bal).astype({"variable": str})
    bal["columna"] = bal.variable.map(BALANCE_ME)
    sumas = bal.pivot_table(index=CLAVE, columns=["columna", "apertura"], values="valor", aggfunc="sum")
    for col in sorted(set(BALANCE_ME.values())):
        total = sumas[(col, "total")]
        partes.append((sumas[(col, "me")] / total.where(total != 0) * 100).rename(col))
    return pd.concat(partes, axis=1).round(4)


def sustituir_posicion_global(panel: pd.DataFrame, maestro_df: pd.DataFrame) -> None:
    """Sustituto de `posicion_global_me_pe` antes de 2015 donde no hay cuadro de posición global.

    CMAC, CRAC y EC publican «Posición Global en M.E.» (C-1260, C-2370, C-4252) recién desde 2014-07
    y financieras (B-3266) desde 2011-05. Antes, si falta el cociente calculado, se toma el
    indicador publicado «Posición global en ME / patrimonio efectivo» del cuadro de indicadores
    (`posicion_global_me_patrimonio_efectivo`; financieras no lo publica). No es idéntico a
    PG(t) / PE(t) (la SBS usa su propio PE del mes). Las celdas sustituidas quedan marcadas con
    «indicador» en `posicion_global_me_pe_origen`; el resto, vacías. Desde 2015-01 no se toca nada.
    """
    if "posicion_global_me_pe" not in panel.columns:
        return
    ind = maestro_df[(maestro_df.tema == "indicadores-financieros")
                     & (maestro_df.variable == "posicion_global_me_patrimonio_efectivo")
                     & (maestro_df.periodo < INICIO_SIN_SUSTITUTOS)]
    ind = _con_clave(ind).groupby(CLAVE).valor.first().reindex(panel.index)
    usar = (panel["posicion_global_me_pe"].isna() & ind.notna()
            & (panel.index.get_level_values("periodo") < INICIO_SIN_SUSTITUTOS))
    panel["posicion_global_me_pe"] = panel["posicion_global_me_pe"].mask(usar, ind)
    panel["posicion_global_me_pe_origen"] = pd.Series("indicador", index=panel.index).where(usar)


def temas_de_columnas(definicion: pd.DataFrame) -> dict[str, set[str]]:
    """Temas del boletín de los que sale cada columna del panel (para saber qué celdas anular en una entidad-mes
    con cifras repetidas). Las derivadas heredan los de su numerador y denominador."""
    temas = {r.columna: {r.tema} for r in definicion.itertuples()}
    for col, (_, _, _, tema) in CALCULADOS.items():
        temas[col] = {tema}
    # Rellenos de `armar_panel`: PE desde la estructura del PE; depósito promedio con depósitos del ranking.
    temas.setdefault("patrimonio_efectivo", set()).add("estructura-patrimonio-efectivo")
    temas["deposito_promedio_depositante"] = temas["deposito_promedio_depositante"] | {RANKING_TEMA}
    for col, (num, den, _, _) in DERIVADAS.items():
        temas[col] = temas.get(num, set()) | temas.get(den, set())
    return temas


def anular_repeticiones(panel: pd.DataFrame, definicion: pd.DataFrame, car_publicada: pd.Series | None) -> None:
    """Deja vacías (NaN) las celdas de las entidad-mes de `errores_origen.RANKING_REPEATS` que vienen de un tema en
    que la SBS repite las cifras de otro mes, y agrega `repite_periodo` (AAAAMM del mes repetido; vacío en el resto).

    Una celda se anula si alguno de sus temas de origen está repetido (`temas_de_columnas`). Casos especiales:
    `cartera_alto_riesgo` publicada (indicadores) o calculada (créditos por situación), según de dónde salió; y el
    sustituto de `posicion_global_me_pe` antes de 2015 (indicadores). Las filas `_total` no se tocan: la SBS suma
    las cifras repetidas en sus totales (y el total del ranking es la suma de lo publicado). `panel` va indexado por
    CLAVE y se modifica en el sitio.
    """
    temas = temas_de_columnas(definicion)
    panel["repite_periodo"] = pd.array([pd.NA] * len(panel), dtype="Int64")
    n_celdas = 0
    for key, r in source_repeats().items():
        if key not in panel.index:
            continue
        panel.loc[key, "repite_periodo"] = r["same_as"]
        cols = []
        for col in panel.columns:
            if col == "cartera_alto_riesgo" and car_publicada is not None:
                origen = "indicadores-financieros" if car_publicada.get(key, False) else "creditos-tipo-situacion"
                rep = repeats_tema(r, origen)
            elif (col == "posicion_global_me_pe" and "posicion_global_me_pe_origen" in panel.columns
                  and panel.at[key, "posicion_global_me_pe_origen"] == "indicador"):
                rep = repeats_tema(r, "indicadores-financieros")
            else:
                rep = any(repeats_tema(r, t) for t in temas.get(col, ()))
            if rep and pd.notna(panel.at[key, col]):
                cols.append(col)
        panel.loc[key, cols] = float("nan")
        if "posicion_global_me_pe" in cols:
            panel.loc[key, "posicion_global_me_pe_origen"] = None
        n_celdas += len(cols)
    print(f"  Cifras repetidas de otro mes: {int(panel['repite_periodo'].notna().sum())} entidad-mes "
          f"({len(full_row_repeat_keys())} con casi toda la fila), {n_celdas} celdas vacías (errores_origen.RANKING_REPEATS)")


def avisar_filas_repetidas(panel: pd.DataFrame) -> None:
    """Aviso para las próximas actualizaciones: entidad con el balance (activo, patrimonio, disponible y utilidad
    acumulada) idéntico al del mes anterior que no está en `RANKING_REPEATS`."""
    cols = ["activo_total", "patrimonio", "disponible", "utilidad_neta_acumulada"]
    p = panel[cols].drop(index=ID_TOTAL, level="id_entidad").reset_index().sort_values(["subsistema", "id_entidad", "periodo"])
    mes = p["periodo"] // 100 * 12 + p["periodo"] % 100
    g = [p["subsistema"], p["id_entidad"]]
    seguido = (mes - mes.groupby(g).shift()) == 1
    igual = pd.concat([p[c].eq(p[c].groupby(g).shift()) for c in cols], axis=1).all(axis=1) & (p["activo_total"] > 0)
    conocidas = set(source_repeats())
    for r in p[seguido & igual].itertuples(index=False):
        if (r.periodo, r.subsistema, r.id_entidad) not in conocidas:
            print(f"  AVISO: {r.subsistema} {r.periodo} {r.id_entidad}: balance idéntico al del mes anterior: revisar las "
                  f"notas al pie («La información de ... corresponde al ...») y agregarlo a errores_origen.RANKING_REPEATS")


def armar_panel(maestro_df: pd.DataFrame, definicion: pd.DataFrame) -> pd.DataFrame:
    filtro = definicion[["columna", "tema", "variable", "apertura"]]
    # Se filtra antes del merge: el maestro tiene más de 10 millones de filas con columnas categóricas.
    sel = maestro_df[maestro_df.tema.isin(filtro.tema) & maestro_df.variable.isin(filtro.variable)]
    sel = sel.astype({"tema": str, "variable": str, "apertura": str, "subsistema": str,
                      "id_entidad": object, "nombre_entidad": object})
    largo = sel.merge(filtro, on=["tema", "variable", "apertura"], how="inner")
    largo["id_entidad"] = largo["id_entidad"].where(~largo.es_total, ID_TOTAL)
    largo = largo.dropna(subset=["id_entidad"])

    # Una celda del panel debe venir de un solo valor publicado.
    conflicto = largo.groupby(CLAVE + ["columna"]).valor.nunique()
    conflicto = conflicto[conflicto > 1]
    if len(conflicto):
        print(f"  AVISO: {len(conflicto)} celdas con más de un valor distinto; se toma el primero")
        print(conflicto.head(10).to_string())

    panel = largo.pivot_table(index=CLAVE, columns="columna", values="valor", aggfunc="first")
    panel = panel.reindex(columns=list(definicion.columna))
    # Entidades absorbidas o liquidadas que la SBS mantiene en el cuadro en ceros (p. ej.
    # Solidaridad desde 2017-06): sin ningún valor distinto de cero no son una observación.
    panel = panel[(panel.fillna(0) != 0).any(axis=1)]

    # El ranking no publica total del subsistema: se completa sumando las entidades.
    aditivas = [c for c in ["creditos_directos", "depositos_totales"] if c in panel.columns]
    suma = panel[aditivas].drop(index=ID_TOTAL, level="id_entidad").groupby(
        level=["periodo", "subsistema"]).sum(min_count=1)
    es_tot = panel.index.get_level_values("id_entidad") == ID_TOTAL
    claves_tot = panel.index[es_tot].droplevel("id_entidad")
    panel.loc[es_tot, aditivas] = panel.loc[es_tot, aditivas].fillna(
        suma.reindex(claves_tot).set_axis(panel.index[es_tot]))
    calc = calculados(maestro_df).reindex(panel.index)
    # Desde 2023-06 el cuadro de RCG ya no trae el patrimonio efectivo total: se toma de la
    # estructura del PE y, si falta, de RCG = PE / APR.
    if "patrimonio_efectivo_publicado" in calc:
        panel["patrimonio_efectivo"] = panel["patrimonio_efectivo"].fillna(calc["patrimonio_efectivo_publicado"])
    if {"patrimonio_efectivo", "ratio_capital_global", "activos_ponderados_riesgo"} <= set(panel.columns):
        panel["patrimonio_efectivo"] = panel["patrimonio_efectivo"].fillna(
            (panel["ratio_capital_global"] * panel["activos_ponderados_riesgo"] / 100).round(2))
    for col, (num, den, _, _) in DERIVADAS.items():
        panel[col] = (panel[num] / panel[den].where(panel[den] != 0) * 100).round(4)
    sustituir_posicion_global(panel, maestro_df)
    car_publicada = panel["cartera_alto_riesgo"].notna() if "cartera_alto_riesgo" in panel.columns else None
    if "cartera_alto_riesgo" in panel.columns:  # publicada solo por cajas y EC
        panel["cartera_alto_riesgo"] = panel["cartera_alto_riesgo"].fillna(calc["cartera_alto_riesgo"])
    for col in CALCULADOS:  # vacía si su tema aún no tiene datos
        panel[col] = calc[col] if col in calc else float("nan")
    if "depositos_totales" in panel.columns:
        panel["deposito_promedio_depositante"] = (
            panel["depositos_totales"] * 1000 / panel["numero_depositantes"].where(panel["numero_depositantes"] > 0)
        ).round(2)
    anular_repeticiones(panel, definicion, car_publicada)
    avisar_filas_repetidas(panel)
    panel = panel.reset_index()

    nombre = (largo.drop_duplicates(CLAVE).set_index(CLAVE)["nombre_entidad"].astype(str))
    panel.insert(3, "nombre_entidad", panel.set_index(CLAVE).index.map(nombre))
    panel.insert(4, "es_total", panel.id_entidad == ID_TOTAL)
    panel.insert(1, "fecha", pd.to_datetime(panel.periodo.astype(str), format="%Y%m")
                 + pd.offsets.MonthEnd(0))
    orden_sub = {s: i for i, s in enumerate(NOMBRE_SUBSISTEMA)}
    panel = panel.sort_values(["periodo", "subsistema", "es_total", "nombre_entidad"],
                              key=lambda s: s.map(orden_sub) if s.name == "subsistema" else s)
    return panel.reset_index(drop=True)


def diccionario(panel: pd.DataFrame, definicion: pd.DataFrame, maestro_df: pd.DataFrame) -> pd.DataFrame:
    series = pd.read_csv(SERIES_CSV)
    codigos = series.groupby("tema").codigo.agg(", ".join)
    unidades = (maestro_df[["tema", "variable", "apertura", "unidad"]].drop_duplicates()
                .astype(str).set_index(["tema", "variable", "apertura"]).unidad)
    filas = [
        {"columna": "periodo", "pilar": "clave", "descripcion": "Mes del cuadro, AAAAMM"},
        {"columna": "fecha", "pilar": "clave", "descripcion": "Último día del mes"},
        {"columna": "subsistema", "pilar": "clave", "descripcion": "Subsistema SBS de la entidad en ese mes"},
        {"columna": "id_entidad", "pilar": "clave",
         "descripcion": f"Identificador estable de la entidad (config/entidades/entidad.csv); «{ID_TOTAL}» = total del subsistema"},
        {"columna": "nombre_entidad", "pilar": "clave", "descripcion": "Nombre vigente de la entidad en ese mes"},
        {"columna": "es_total", "pilar": "clave", "descripcion": "Fila del total del subsistema publicado por la SBS"},
    ]
    for r in definicion.itertuples():
        filas.append({"columna": r.columna, "pilar": r.pilar, "descripcion": r.descripcion,
                      "unidad": unidades.get((r.tema, r.variable, r.apertura), ""),
                      "tema_sbs": r.tema, "cuadros_sbs": codigos.get(r.tema, ""),
                      "variable_origen": r.variable + (f" [{r.apertura}]" if r.apertura else "")})
    for col, (num, den, pilar, desc) in DERIVADAS.items():
        filas.append({"columna": col, "pilar": pilar, "descripcion": desc, "unidad": "porcentaje",
                      "variable_origen": f"{num} / {den} × 100"})
    for col, (pilar, desc, unidad, tema) in CALCULADOS.items():
        filas.append({"columna": col, "pilar": pilar, "descripcion": desc, "unidad": unidad,
                      "tema_sbs": tema, "cuadros_sbs": codigos.get(tema, ""), "variable_origen": "calculado"})
    if "posicion_global_me_pe_origen" in panel.columns:
        filas.append({"columna": "posicion_global_me_pe_origen", "pilar": "sensibilidad",
                      "descripcion": "«indicador» = posicion_global_me_pe tomada del indicador publicado «Posición global "
                                     "en ME / patrimonio efectivo» porque no existe el cuadro de posición global (CMAC, "
                                     "CRAC y EC antes de 2014-07; solo antes de 2015-01). Vacía = calculada del cuadro",
                      "unidad": "texto", "tema_sbs": "indicadores-financieros",
                      "cuadros_sbs": codigos.get("indicadores-financieros", ""),
                      "variable_origen": "posicion_global_me_patrimonio_efectivo (sustituto)"})
    filas.append({"columna": "repite_periodo", "pilar": "calidad",
                  "descripcion": "AAAAMM del mes cuyas cifras repite la SBS en esta entidad-mes (nota «La información de ... "
                                 "corresponde al ...»; lista y evidencia en src/errores_origen.py, RANKING_REPEATS). Las "
                                 "celdas que vienen de un cuadro repetido quedan vacías: en 8 entidad-mes casi toda la fila, "
                                 "en CMAC Sullana 2014-11 solo las del ranking. Vacía = cifras del mes",
                  "unidad": "AAAAMM", "variable_origen": "errores_origen.RANKING_REPEATS"})
    dic = pd.DataFrame(filas)
    con_dato = panel[~panel.es_total]
    for f in dic.itertuples():
        if f.pilar == "clave":
            continue
        d = con_dato.loc[con_dato[f.columna].notna(), ["periodo", "subsistema"]]
        dic.loc[f.Index, "desde"] = d.periodo.min() if len(d) else None
        dic.loc[f.Index, "hasta"] = d.periodo.max() if len(d) else None
        dic.loc[f.Index, "subsistemas"] = ", ".join(s for s in NOMBRE_SUBSISTEMA if s in set(d.subsistema))
    return dic


def escribir_excel(panel: pd.DataFrame, dic: pd.DataFrame, ruta: Path) -> None:
    with pd.ExcelWriter(ruta, engine="openpyxl") as xl:
        panel.to_excel(xl, sheet_name="panel", index=False)
        dic.to_excel(xl, sheet_name="diccionario", index=False)
        hoja = xl.sheets["panel"]
        hoja.freeze_panes = "G2"
        hoja.auto_filter.ref = hoja.dimensions
        for celda in hoja[1]:
            hoja.column_dimensions[celda.column_letter].width = max(11, min(len(str(celda.value)) + 2, 28))
        hoja.column_dimensions["E"].width = 34
        for fila in hoja.iter_rows(min_row=2, min_col=2, max_col=2):
            fila[0].number_format = "yyyy-mm-dd"
        hoja_d = xl.sheets["diccionario"]
        hoja_d.freeze_panes = "B2"
        for letra, ancho in zip("ABCDEFGHIJ", [32, 13, 80, 14, 34, 36, 48, 9, 9, 70]):
            hoja_d.column_dimensions[letra].width = ancho


def consolidar_estatales(out_dir: Path) -> None:
    """Maestro y panel de las entidades estatales (p=12), aparte del panel principal (2026-11-03).

    Parte de `data/processed/boletin_estatales/<tema>.parquet` (`leer_boletin.py` escribe ahí los temas
    `estatales-*`) y escribe:
        boletin_maestro_estatales.parquet  todos los temas estatales, incluidos COFIDE, Fondo MiVivienda y
                                           los totales que publica la SBS («Total Entidades Estatales»)
        panel_estatales_mes.parquet        una fila por mes × entidad, SOLO Banco de la Nación y Agrobanco
                                           (decisión del usuario: el mismo criterio de la Carpeta SIF, que no
                                           incluye a COFIDE ni al Fondo), columnas de `config/panel_estatales.csv`
    No toca `boletin_maestro.parquet` ni `panel_entidad_mes.parquet`: los tableros, la alerta temprana y las
    tesis no ven estas entidades. No hay fila «_total»: el consolidado de la SBS incluye a COFIDE y al Fondo.
    `creditos_directos` y `depositos_totales` se calculan del balance con la fórmula del ranking B-2332
    (vigentes + refinanciados y reestructurados + atrasados; obligaciones con el público − otras obligaciones +
    depósitos del sistema financiero), que reproduce el ranking de la banca con 0,0000 % de diferencia
    (docs/cobertura_sbs_p12_p14.md § 4).
    """
    rutas = sorted(TEMAS_DIR_ESTATALES.glob("*.parquet"))
    if not rutas:
        print("Estatales: no hay temas en data/processed/boletin_estatales (se omite)")
        return
    print("Maestro estatal:")
    partes = []
    for ruta in rutas:
        df = pd.read_parquet(ruta)
        df["apertura"] = df["apertura"].fillna("")
        partes.append(df)
        print(f"  {ruta.stem}: {len(df):,} filas")
    m = pd.concat(partes, ignore_index=True)
    # Resguardo: el maestro resuelve alias sin subsistema en cualquier subsistema (p. ej. B-5216 2019-06 trae
    # por error cajeros de financieras). Ninguna fila estatal puede ser de otra entidad.
    ajenas = set(m.id_entidad.dropna().unique()) - ENTIDADES_ESTATALES
    if ajenas:
        raise ValueError(f"entidades no estatales en boletin_estatales: {sorted(ajenas)}")
    maestro = Maestro()
    pares = m.loc[~m.es_total, ["id_entidad", "periodo"]].drop_duplicates().dropna()
    nombre = {}
    for i, p in zip(pares.id_entidad, pares.periodo):
        v = maestro.vigencia(i, int(p))
        nombre[(i, p)] = v["nombre"] if v else maestro.entidades[i]["nombre_actual"]
    m.insert(7, "nombre_entidad", [("Total entidades estatales" if t else nombre.get((i, p)))
                                   for i, p, t in zip(m.id_entidad, m.periodo, m.es_total)])
    m = m.astype({c: "category" for c in ["subsistema", "tema", "codigo", "hoja", "entidad_original",
                                          "id_entidad", "nombre_entidad", "variable", "apertura", "unidad"]})
    ruta = out_dir / "boletin_maestro_estatales.parquet"
    m.to_parquet(ruta, index=False)
    print(f"  -> {ruta.name}: {len(m):,} filas")

    print("Panel estatal:")
    definicion = pd.read_csv(PANEL_ESTATALES_CSV, dtype=str).fillna("")
    filtro = definicion[["columna", "tema", "variable", "apertura"]]
    sel = m[m.id_entidad.isin(ENTIDADES_PANEL_ESTATAL) & ~m.es_total]
    sel = sel.astype({"tema": str, "variable": str, "apertura": str, "subsistema": str,
                      "id_entidad": str, "nombre_entidad": str})
    largo = sel.merge(filtro, on=["tema", "variable", "apertura"], how="inner")
    conflicto = largo.groupby(CLAVE + ["columna"]).valor.nunique()
    conflicto = conflicto[conflicto > 1]
    if len(conflicto):
        print(f"  AVISO: {len(conflicto)} celdas con más de un valor distinto; se toma el primero")
        print(conflicto.head(10).to_string())
    panel = largo.pivot_table(index=CLAVE, columns="columna", values="valor", aggfunc="first")
    panel = panel.reindex(columns=list(definicion.columna))
    # Fórmula del ranking; un componente vacío deja vacío el resultado (no se rellena con cero).
    panel["creditos_directos"] = (panel["creditos_vigentes"] + panel["creditos_refinanciados_reestructurados"]
                                  + panel["creditos_atrasados"])
    panel["depositos_totales"] = (panel["obligaciones_publico"] - panel["otras_obligaciones"]
                                  + panel["depositos_sistema_financiero"])
    panel["disponible_activo"] = (panel["disponible"] / panel["activo_total"].where(panel["activo_total"] != 0)
                                  * 100).round(4)
    panel["creditos_depositos"] = (panel["creditos_directos"]
                                   / panel["depositos_totales"].where(panel["depositos_totales"] != 0) * 100).round(4)
    panel = panel.reset_index()
    nombres_panel = largo.drop_duplicates(CLAVE).set_index(CLAVE)["nombre_entidad"]
    panel.insert(3, "nombre_entidad", panel.set_index(CLAVE).index.map(nombres_panel))
    panel.insert(1, "fecha", pd.to_datetime(panel.periodo.astype(str), format="%Y%m") + pd.offsets.MonthEnd(0))
    panel = panel.sort_values(["id_entidad", "periodo"]).reset_index(drop=True)
    panel.to_parquet(out_dir / "panel_estatales_mes.parquet", index=False)
    print(f"  -> panel_estatales_mes.parquet: {len(panel):,} filas × {panel.shape[1]} columnas, "
          f"entidades {sorted(panel.id_entidad.unique())}, {panel.periodo.min()}-{panel.periodo.max()}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--salida", type=Path, default=OUT_DIR,
                    help="carpeta del maestro y del panel (por defecto data/processed)")
    out_dir = ap.parse_args().salida
    out_dir.mkdir(parents=True, exist_ok=True)
    print("Maestro:")
    maestro_df = cargar_temas()
    maestro_df.insert(7, "nombre_entidad", nombres(maestro_df, Maestro()))
    ruta = out_dir / "boletin_maestro.parquet"
    maestro_df.to_parquet(ruta, index=False)
    print(f"  -> {ruta.name}: {len(maestro_df):,} filas, {ruta.stat().st_size / 1e6:.0f} MB")

    print("Panel:")
    definicion = pd.read_csv(PANEL_CSV, dtype=str).fillna("")
    panel = armar_panel(maestro_df, definicion)
    panel.to_parquet(out_dir / "panel_entidad_mes.parquet", index=False)
    escribir_excel(panel, diccionario(panel, definicion, maestro_df), out_dir / "panel_entidad_mes.xlsx")
    print(f"  -> panel_entidad_mes.parquet / .xlsx: {len(panel):,} filas × {panel.shape[1]} columnas, "
          f"{panel.id_entidad.nunique() - 1} entidades, {panel.periodo.min()}-{panel.periodo.max()}")
    consolidar_estatales(out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
