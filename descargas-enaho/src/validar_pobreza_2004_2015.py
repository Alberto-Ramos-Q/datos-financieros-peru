"""Contraste de la pobreza monetaria 2004-2015 de la base local con las cifras oficiales del INEI.

Solo incidencias puntuales (el cálculo con IC lo hace otro script). Lee
`config/pobreza_oficial_2004_2015.csv` (transcripción de los informes técnicos; ver
`docs/referencias_inei/pobreza_2004_2015/fuentes.md`) y `data/processed/<año>/sumaria-<año>.parquet`.
Solo imprime; no escribe archivos (salvo `--salida`, que guarda el detalle en CSV).

Metodología (rutinas INEI, igual que `validar_cifras_oficiales.py` y `docs/validacion_cifras_oficiales.md` §3):
- Peso de personas: round(factor07 * mieperho, 1). Universo: la Sumaria.
- Pobre: pobreza <= 2; pobre extremo: pobreza == 1. Se verifica que `pobreza` cuadre con
  gashog2d / (12 * mieperho) frente a linpe / linea.
- Área: urbana = estrato <= 5 o dominio == 8 (Lima Metropolitana siempre urbana, como la rutina INEI).
- Región: costa = dominio 1-3 u 8; sierra = 4-6; selva = 7. Dominios costa/sierra/selva x urbana/rural
  sin Lima Metropolitana; Lima Metropolitana = dominio 8 (provincia de Lima + Callao).
- Departamentos: ubigeo[:2]. Códigos especiales: 15LM = provincia de Lima (ubigeo 1501),
  15LR = región Lima (dpto 15 sin 1501), "15+07" = Lima con Callao (definición INEI hasta 2012).
- Grupos de departamentos («grupos robustos»): los límites publicados son el IC 95 % de la incidencia
  conjunta del grupo; se compara la incidencia conjunta local con el punto medio del intervalo.

Uso:
    python src/validar_pobreza_2004_2015.py            # resumen
    python src/validar_pobreza_2004_2015.py --detalle  # todas las comparaciones
    python src/validar_pobreza_2004_2015.py --salida comparacion.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_CSV = ROOT / "config" / "pobreza_oficial_2004_2015.csv"
YEARS = range(2004, 2016)
REQUIRED = ["ubigeo", "dominio", "estrato", "pobreza", "linea", "linpe", "gashog2d", "mieperho",
            "factor07"]
TOL = 0.1          # pp, como en validar_cifras_oficiales.py
TOL_MIDPOINT = 0.1  # pp, punto medio del IC de un grupo (dos límites redondeados a 0,1)


def load_sumaria(year: int) -> pd.DataFrame:
    path = ROOT / "data" / "processed" / str(year) / f"sumaria-{year}.parquet"
    df = pd.read_parquet(path)
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise SystemExit(f"{year}: faltan columnas {missing} en {path.name}")
    df = df[REQUIRED].copy()
    for col in ["pobreza", "linea", "linpe", "gashog2d", "mieperho", "factor07", "dominio", "estrato"]:
        df[col] = df[col].astype("float64")
    df["peso"] = (df["factor07"] * df["mieperho"]).round(1)
    df["pobre"] = (df["pobreza"] <= 2).astype(float)
    df["extremo"] = (df["pobreza"] == 1).astype(float)
    df["urbana"] = (df["estrato"] <= 5) | (df["dominio"] == 8)
    df["region"] = np.select([df["dominio"].isin([1, 2, 3, 8]), df["dominio"].isin([4, 5, 6])],
                             ["costa", "sierra"], "selva")
    df["dpto"] = df["ubigeo"].str[:2]
    df["prov"] = df["ubigeo"].str[:4]
    return df


def check_poverty_variable(df: pd.DataFrame) -> tuple[int, int]:
    """Hogares cuya `pobreza` no cuadra con gashog2d/(12*mieperho) frente a linpe y linea."""
    gpcm = df["gashog2d"] / (12 * df["mieperho"])
    recomputed = np.where(gpcm < df["linpe"], 1, np.where(gpcm < df["linea"], 2, 3))
    bad = recomputed != df["pobreza"].to_numpy()
    return int(bad.sum()), len(df)


def code_mask(df: pd.DataFrame, code: str) -> pd.Series:
    if code == "15LM":
        return df["prov"] == "1501"
    if code == "15LR":
        return (df["dpto"] == "15") & (df["prov"] != "1501")
    return df["dpto"] == code


def ambito_mask(df: pd.DataFrame, ambito: str) -> pd.Series:
    lima = df["dominio"] == 8
    if ambito == "nacional":
        return pd.Series(True, index=df.index)
    if ambito == "area_urbana":
        return df["urbana"]
    if ambito == "area_rural":
        return ~df["urbana"]
    if ambito == "lima_metropolitana":
        return lima
    if ambito == "resto_urbano":
        return df["urbana"] & ~lima
    if ambito == "resto_pais":
        return ~lima
    if ambito.startswith("region_"):
        return df["region"] == ambito.removeprefix("region_")
    if ambito.startswith("dominio_"):
        region, area = ambito.removeprefix("dominio_").split("_")
        mask = (df["region"] == region) & ~lima
        return mask & (df["urbana"] if area == "urbana" else ~df["urbana"])
    if ambito.startswith("dpto_"):
        code = ambito.removeprefix("dpto_")
        return code_mask(df, code)
    if ambito.startswith("grupo"):
        codes = ambito.split(":", 1)[1].split("+")
        mask = pd.Series(False, index=df.index)
        for code in codes:
            mask |= code_mask(df, code)
        return mask
    raise ValueError(f"ámbito desconocido: {ambito}")


def incidence(df: pd.DataFrame, mask: pd.Series, indicador: str) -> float:
    col = "pobre" if indicador.startswith("pobreza_total") else "extremo"
    w = df.loc[mask, "peso"]
    return float(np.average(df.loc[mask, col], weights=w) * 100)


def range_check(df: pd.DataFrame, ambito: str, lo: float, hi: float) -> tuple[float, float, bool, str]:
    """Grupos 2004-2006 del informe de mar-2012 (límites en % enteros).

    Un departamento: los límites son su IC 95 % redondeado -> la estimación debe caer dentro.
    Varios: los límites son la menor y la mayor estimación puntual de los miembros (redondeadas a
    entero) -> se comparan con el mínimo y el máximo locales. «Lima» = Lima + Callao.
    Devuelve (referencia, local, ok, tipo de comparación); en varios, local = máx. |desvío|.
    """
    codes = ambito.split(":", 1)[1].split("+")
    units = [c for c in codes if c != "07"]
    points = []
    for code in units:
        mask = code_mask(df, code)
        if code == "15" and "07" in codes:
            mask = mask | (df["dpto"] == "07")
        points.append(incidence(df, mask, "pobreza_total"))
    if len(points) == 1:
        p = points[0]
        return (lo + hi) / 2, p, lo - 0.5 <= p <= hi + 0.5, "IC entero (1 dpto)"
    dev = max(abs(min(points) - lo), abs(max(points) - hi))
    return np.nan, dev, dev <= 0.5 + 1e-9, "rango de puntos (mín.-máx.)"


def ambito_tipo(ambito: str) -> str:
    if ambito.startswith("grupo"):
        return "grupo de dptos"
    if ambito.startswith("dpto_"):
        return "departamento"
    if ambito.startswith("dominio_"):
        return "dominio"
    if ambito.startswith("region_"):
        return "región"
    if ambito.startswith("area_"):
        return "área"
    return "nacional y Lima" if ambito in ("nacional", "lima_metropolitana") else "otros ámbitos"


def compare(official: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for year in YEARS:
        df = load_sumaria(year)
        bad, n = check_poverty_variable(df)
        print(f"{year}: {n:,} hogares; `pobreza` no cuadra con gashog2d/(12*mieperho) en {bad} hogares")
        for r in official[official["anio"] == year].itertuples(index=False):
            if r.indicador.endswith("_rango"):
                ref, local, ok, kind = range_check(df, r.ambito, r.ic_inf, r.ic_sup)
                rows.append(dict(anio=year, indicador=r.indicador, ambito=r.ambito,
                                 tipo="grupo 2004-2006 (rango)", comparacion=kind, oficial=ref,
                                 local=local, dif=np.nan, ok=ok, dentro_ic=None,
                                 fuente=r.fuente, pagina=r.pagina))
                continue
            local = incidence(df, ambito_mask(df, r.ambito), r.indicador)
            if pd.notna(r.valor):
                ref, kind = r.valor, "valor"
                tol = TOL
            elif pd.notna(r.ic_inf):
                ref, kind = (r.ic_inf + r.ic_sup) / 2, "punto medio IC"
                tol = TOL_MIDPOINT
            else:
                ref, kind, tol = np.nan, "sin cifra (solo pertenencia)", np.nan
            diff = local - ref if pd.notna(ref) else np.nan
            in_ic = (r.ic_inf - 0.05 <= local <= r.ic_sup + 0.05) if pd.notna(r.ic_inf) else None
            rows.append(dict(anio=year, indicador=r.indicador, ambito=r.ambito, tipo=ambito_tipo(r.ambito),
                             comparacion=kind, oficial=ref, local=local, dif=diff,
                             ok=(abs(diff) <= tol + 1e-9) if pd.notna(diff) else None,
                             dentro_ic=in_ic, fuente=r.fuente, pagina=r.pagina))
    return pd.DataFrame(rows)


def print_summary(res: pd.DataFrame) -> None:
    ranges = res[res["tipo"] == "grupo 2004-2006 (rango)"]
    comp = res[res["ok"].notna() & (res["tipo"] != "grupo 2004-2006 (rango)")]
    print("\nResumen (cifras con valor o IC publicado):")
    summary = comp.groupby(["anio", "tipo"]).agg(
        n=("ok", "size"), ok=("ok", "sum"), dif_max=("dif", lambda s: s.abs().max()))
    print(summary.to_string(float_format=lambda v: f"{v:.2f}"))
    by_type = comp.groupby("tipo").agg(n=("ok", "size"), ok=("ok", "sum"),
                                        dif_max=("dif", lambda s: s.abs().max()))
    print("\nPor tipo de ámbito:")
    print(by_type.to_string(float_format=lambda v: f"{v:.2f}"))
    total, good = len(comp), int(comp["ok"].sum())
    print(f"\nTotal: {good}/{total} dentro de ±{TOL} pp; diferencia máxima {comp['dif'].abs().max():.3f} pp")
    ic = res[res["dentro_ic"].notna()]
    print(f"Estimación local dentro del IC publicado: {int(ic['dentro_ic'].sum())}/{len(ic)}")
    bad = comp[~comp["ok"].astype(bool)]
    if not bad.empty:
        print("\nFuera de tolerancia:")
        print(bad[["anio", "indicador", "ambito", "comparacion", "oficial", "local", "dif", "fuente"]]
              .to_string(index=False, float_format=lambda v: f"{v:.2f}"))
    if not ranges.empty:
        print(f"\nGrupos 2004-2006 (informe mar-2012, límites en % enteros): "
              f"{int(ranges['ok'].sum())}/{len(ranges)} cuadran (tolerancia ±0,5 por redondeo a entero)")
        print(ranges[["anio", "ambito", "comparacion", "local", "ok"]]
              .rename(columns={"local": "local (1 dpto: estimación; varios: máx. desvío)"})
              .to_string(index=False, float_format=lambda v: f"{v:.2f}"))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--detalle", action="store_true", help="imprime todas las comparaciones")
    parser.add_argument("--salida", type=Path, help="guarda el detalle en un CSV")
    args = parser.parse_args(argv)
    official = pd.read_csv(OFFICIAL_CSV, dtype={"pagina": str})
    res = compare(official)
    if args.detalle:
        with pd.option_context("display.max_rows", None, "display.width", 200):
            print(res.to_string(index=False, float_format=lambda v: f"{v:.2f}"))
    print_summary(res)
    if args.salida:
        res.to_csv(args.salida, index=False, float_format="%.3f")
        print(f"\nDetalle guardado en {args.salida}")
    return 0 if bool(res["ok"].dropna().all()) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
