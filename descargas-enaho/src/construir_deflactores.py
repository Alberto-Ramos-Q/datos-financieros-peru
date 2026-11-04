"""Construye las tablas de deflactores de la ENAHO, listas para unir, en data/processed/deflactores/.

Fuente: rutinas oficiales del INEI que vienen con la documentación del último año
(docs/enaho/<año>/1_Rutinas-medicion-pobreza/):
- ipc-BASE-2009nh.dta  IPC mensual por ciudad (26 ciudades) 1997-<año>, general (i00) y 8 grupos
                        (i01-i08), con `ponderad` para agregar ciudades a departamento.
- despacial_ldnew.dta  deflactor espacial `ld` por dominioA (17 valores; Lima Metropolitana = 1).

Salidas:
- deflactor_temporal.parquet  año × departamento: IPC promedio anual (`ipc_i0k`, nivel) y coeficiente
                              respecto del año base (`def_i0k` = IPC del año / IPC del año base).
- deflactor_espacial.parquet  dominioA × ld, con su descripción.

Método (replica 02_Programa-actualización_de_la_pobreza-<año>.do; validado en
validar_cifras_oficiales.py contra el gasto real y el vestido real oficiales 2016-2025):
1. IPC por ciudad × ponderad, sumado al departamento (Áncash = Huaraz + Chimbote; San Martín =
   Moyobamba + Tarapoto; en 1997-2008 Tarapoto no tiene IPC y queda solo Moyobamba).
2. Media simple de los 12 meses del año.
3. Coeficiente = IPC promedio del año / IPC promedio del año base, por departamento.
4. Callao no tiene IPC propio: usa el de Lima (fila 07 copiada de 15, `ipc_fuente` = "Lima").

Uso:
    python src/construir_deflactores.py               # año base = último año del IPC
    python src/construir_deflactores.py --base 2020   # otro año base

Soles reales de un grupo k (precios promedio del año base, en Lima Metropolitana):
    real = nominal / (def_i0k[año, dpto] * ld[dominioA])
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "docs" / "enaho"
OUT_DIR = ROOT / "data" / "processed" / "deflactores"
TEMPORAL_FILE = OUT_DIR / "deflactor_temporal.parquet"
SPATIAL_FILE = OUT_DIR / "deflactor_espacial.parquet"

INDEX_COLS = [f"i0{k}" for k in range(9)]
GROUPS = {
    "i00": "General",
    "i01": "Alimentos y bebidas",
    "i02": "Vestido y calzado",
    "i03": "Alquiler de vivienda, combustible y electricidad",
    "i04": "Muebles, enseres y mantenimiento de la vivienda",
    "i05": "Cuidado y conservación de la salud",
    "i06": "Transportes y comunicaciones",
    "i07": "Esparcimiento, diversión, servicios culturales y de enseñanza",
    "i08": "Otros bienes y servicios",
}
DEPARTMENTS = {
    "01": "Amazonas", "02": "Áncash", "03": "Apurímac", "04": "Arequipa", "05": "Ayacucho",
    "06": "Cajamarca", "07": "Callao", "08": "Cusco", "09": "Huancavelica", "10": "Huánuco",
    "11": "Ica", "12": "Junín", "13": "La Libertad", "14": "Lambayeque", "15": "Lima",
    "16": "Loreto", "17": "Madre de Dios", "18": "Moquegua", "19": "Pasco", "20": "Piura",
    "21": "Puno", "22": "San Martín", "23": "Tacna", "24": "Tumbes", "25": "Ucayali",
}
# dominioA de las rutinas INEI: dominios 1-6 × área, selva alta/baja × área, Lima Metropolitana
SPATIAL_DOMAINS = {
    1: "Costa norte urbana", 2: "Costa norte rural", 3: "Costa centro urbana",
    4: "Costa centro rural", 5: "Costa sur urbana", 6: "Costa sur rural",
    7: "Sierra norte urbana", 8: "Sierra norte rural", 9: "Sierra centro urbana",
    10: "Sierra centro rural", 11: "Sierra sur urbana", 12: "Sierra sur rural",
    13: "Selva alta urbana", 14: "Selva alta rural", 15: "Selva baja urbana",
    16: "Selva baja rural", 17: "Lima Metropolitana",
}
LOW_JUNGLE_DPTOS = ["16", "17", "25"]  # Loreto, Madre de Dios, Ucayali


def routines_dir() -> Path:
    """Carpeta de rutinas del último año con documentación completa."""
    candidates = sorted(DOCS_DIR.glob("*/1_Rutinas-medicion-pobreza"))
    if not candidates:
        raise FileNotFoundError("No hay rutinas INEI en docs/enaho/<año>/: correr descargar_enaho.py")
    return candidates[-1]


def build_temporal(base_year: int | None = None) -> pd.DataFrame:
    ipc_file = next(routines_dir().glob("Pobreza-*/Bases/ipc-BASE-2009nh.dta"))
    ipc = pd.read_stata(ipc_file)
    ipc = ipc.rename(columns={ipc.columns[0]: "anio"})
    ipc["anio"] = ipc["anio"].astype(int)
    ipc["dpto"] = ipc["ubigeo"].str[:2]
    for col in INDEX_COLS:
        ipc[col] = ipc[col].astype(float) * ipc["ponderad"].astype(float)
    monthly = ipc.groupby(["anio", "mes", "dpto"])[INDEX_COLS].sum(min_count=1)
    annual = monthly.groupby(["anio", "dpto"]).mean()

    base_year = base_year or int(annual.index.get_level_values("anio").max())
    coef = annual.div(annual.xs(base_year, level="anio"), level="dpto")

    out = pd.concat([annual.add_prefix("ipc_"), coef.add_prefix("def_")], axis=1).reset_index()
    out["ipc_fuente"] = "propio"
    callao = out[out.dpto == "15"].assign(dpto="07", ipc_fuente="Lima")
    out = pd.concat([out, callao]).sort_values(["anio", "dpto"]).reset_index(drop=True)
    out.insert(2, "departamento", out.dpto.map(DEPARTMENTS))
    out["anio_base"] = base_year
    return out


def build_spatial() -> pd.DataFrame:
    ld_file = next(routines_dir().glob("Vulnerabilidad_*/bases/despacial_ldnew.dta"))
    ld = pd.read_stata(ld_file)
    out = pd.DataFrame({"dominio_a": ld["dominioA"].astype(int), "ld": ld["ld"].astype(float)})
    out["descripcion"] = out.dominio_a.map(SPATIAL_DOMAINS)
    return out


def build_dominio_a(df: pd.DataFrame) -> pd.Series:
    """dominioA de un hogar a partir de `dominio`, `estrato` y `ubigeo` (para unir el `ld`).

    Dominios 1-7: 2·(dominio−1)+1 si urbano (estrato ≤ 5), +1 si rural; la selva (dominio 7) de
    Loreto, Madre de Dios y Ucayali es selva baja (15/16); dominio 8 = Lima Metropolitana (17).
    Verificado: coincide con el `ld` de la Sumaria 2012-2025 (validar_cifras_oficiales.py).
    """
    dom = df["dominio"].astype(int)
    rural = (df["estrato"].astype(float) > 5).astype(int)
    out = 2 * (dom - 1) + 1 + rural
    low_jungle = (dom == 7) & df["ubigeo"].str[:2].isin(LOW_JUNGLE_DPTOS)
    out = out.where(~low_jungle, 15 + rural)
    return out.where(dom != 8, 17)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", type=int, help="año base (por defecto, el último del IPC)")
    args = parser.parse_args()

    temporal, spatial = build_temporal(args.base), build_spatial()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    temporal.to_parquet(TEMPORAL_FILE, index=False)
    spatial.to_parquet(SPATIAL_FILE, index=False)
    for path, df in ((TEMPORAL_FILE, temporal), (SPATIAL_FILE, spatial)):
        print(f"[ok] {path.relative_to(ROOT).as_posix()}  {len(df)} filas × {df.shape[1]} cols  "
              f"({path.stat().st_size / 1e3:.0f} KB)")
    print(f"Años {temporal.anio.min()}-{temporal.anio.max()}, base {temporal.anio_base.iloc[0]}, "
          f"{temporal.dpto.nunique()} departamentos; nulos: {int(temporal.isna().sum().sum())}")


if __name__ == "__main__":
    main()
