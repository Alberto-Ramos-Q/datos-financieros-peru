"""Construye la serie oficial de concentración bancaria de Brasil (2015-2025) a partir del BCB.

Fuente: tablas de «Síntese dos indicadores de concentração» del Relatório de Economia
Bancária (REB, ediciones 2017-2023) y del Relatório de Estabilidade Financeira (REF, abr-2025
y may-2026). Los PDF están en `data/raw/internacional/brasil/pdf/` (ver `descargar_brasil.py`).

Cómo se garantiza que cada cifra es la del PDF:
1. Cada fila de cada tabla se transcribió a mano mirando la tabla renderizada como imagen
   (los PDF a veces desordenan columnas al extraer texto).
2. Este script vuelve a leer el texto de la página citada y exige que la fila transcrita
   aparezca allí como secuencia CONTIGUA de números, en el mismo orden. Si una sola cifra
   no cuadra, el script se detiene.
3. Controles internos: E.N. ≈ 1/IHHn; público + privado = 100; suma de segmentos ≈ 100.

Regla de selección por año (la edición más reciente que trae el año):
- se prefiere el método «nuevo» (REB 2021 en adelante: RC4, SFN con n2 y n4, conglomerado
  prudencial del IF.data);
- si ningún informe con método nuevo trae el año (2015-2018), se usa el método «antiguo»
  (REB 2017-2020 y Anexo C del REB 2021: RC5, segmento bancário e não bancário
  b1+b2+b3+b4+n1, base contable no declarada). Para esos años NO hay RC4 oficial del SFN.
- el RC5 se rellena junto a un RC4 solo si viene de la misma edición y su IHHn es idéntico
  (mismo perímetro); si no, queda vacío.

Salida: `data/processed/internacional/brasil_concentracion.csv` (variante
`oficial_con_estatales`). Imprime además el registro de revisiones entre ediciones.

Cálculo propio (agregado el 2026-11-04, cuando la API del IF.data volvió a responder): CR4, CR5
e IHH del segmento bancario b1+b2 con y sin bancos públicos (variantes `con_estatales` y
`sin_estatales`), desde los JSON de `data/raw/internacional/brasil/ifdata/`. Escribe también
`brasil_entidades.csv` (entidad × año × variable). Ver `docs/internacional/brasil.md` § 9.

Uso (desde la raíz del proyecto):
    python -I src/internacional/construir_brasil.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[2]
PDF_DIR = ROOT / "data" / "raw" / "internacional" / "brasil" / "pdf"
OUT_DIR = ROOT / "data" / "processed" / "internacional"
OUT_CSV = OUT_DIR / "brasil_concentracion.csv"
ENT_CSV = OUT_DIR / "brasil_entidades.csv"
IFDATA_DIR = ROOT / "data" / "raw" / "internacional" / "brasil" / "ifdata"
IFDATA_ODATA = "https://olinda.bcb.gov.br/olinda/servico/IFDATA/versao/v1/odata"
# Perímetro bancario del cálculo propio (decidido en docs/internacional/brasil.md § 9): bancos
# comerciales y múltiples con cartera comercial (b1) y múltiples sin cartera comercial o de
# inversión (b2). Fuera: cooperativas (b3), desarrollo (b4, incluido el BNDES) y no bancarias.
IFDATA_TCB = ("B1", "B2")
IFDATA_TC_PUBLIC = 1   # campo Tc del cadastro: 1 = público, 2 = privado nacional, 3 = extranjero
# Columnas por su fórmula contable (no por el nombre, que cambia entre años):
# - crédito: hasta 2024 «Carteira de Crédito Classificada» (31000000); desde 2025 (Cosif 1.5)
#   la nueva «Carteira de Crédito». Es un quiebre de definición en 2025.
# - depósitos: «Depósito Total (a)», grupo 41 completo, igual en todos los años.
IFDATA_CRED = {"[31000000]",
               "[1600000007] + [1741000007] + [1810000000] + [1887900009] + [1899600005]"}
IFDATA_DEP = {"[41000007]", "[4100000009]"}
IFDATA_MAX_UNMATCHED = 0.0001  # tolerancia para entidades sin cadastro (fracción del total)

PUB = "https://www.bcb.gov.br/content/publicacoes"
VARIABLES = ("activos", "depositos", "creditos")
VARIABLE_PT = {"activos": "Ativos totais", "depositos": "Depósitos totais",
               "creditos": "Operações de crédito"}
NUMBER_RE = re.compile(r"\d+,\d+")


@dataclass
class TableSpec:
    """Tabla oficial transcrita. `rows` mapea una clave a la fila tal como figura en el PDF.

    layout = "segmentos" (método antiguo): clave (variable, indicador); la fila recorre
             segmento × año: [SFN años..., bancário b1+b2 años..., comercial b1 años...].
    layout = "sfn" (método nuevo): clave indicador; la fila recorre variable × año:
             [activos años..., depósitos años..., créditos años...].
    """
    table_id: str
    order: int                 # orden de publicación (mayor = más reciente)
    edition: str
    pdf: str
    url: str
    page_pdf: int
    page_printed: int
    title: str
    method: str                # "antiguo" | "nuevo"
    layout: str
    years: list[int]
    rows: dict
    rc4_as_fraction: bool = False
    notes: list[str] = field(default_factory=list)

    def source_text(self) -> str:
        """Cita completa: edición, tabla, página impresa (y del PDF si difiere) y URL."""
        page = f"p. {self.page_printed}"
        if self.page_printed != self.page_pdf:
            page += f" (p. {self.page_pdf} del PDF)"
        return f"BCB, {self.edition}, {self.title}, {page}, {self.url}"


SEGMENTS_OLD = ("sfn", "bancario_b1b2", "comercial_b1")

# --------------------------------------------------------------------------------------
# Transcripción de las tablas (verificada contra la imagen de cada tabla el 2026-11-03).
# --------------------------------------------------------------------------------------
TABLES: list[TableSpec] = [
    TableSpec(
        "REB2017_T5.1", 10, "REB 2017", "reb_2017.pdf",
        f"{PUB}/relatorioeconomiabancaria/reb_2017.pdf", 89, 87,
        "Tabela 5.1 «Síntese dos indicadores de concentração»", "antiguo", "segmentos",
        [2015, 2016, 2017],
        {
            ("activos", "ihhn"): "0,1090 0,1149 0,1146 0,1311 0,1397 0,1404 0,1371 0,1541 0,1457",
            ("activos", "rc5"): "69,4 71,2 71,0 78,1 81,2 81,3 79,9 82,7 82,8",
            ("activos", "en"): "9,2 8,7 8,7 7,6 7,2 7,1 7,3 6,5 6,9",
            ("depositos", "ihhn"): "0,1481 0,1544 0,1417 0,1623 0,1710 0,1571 0,1660 0,1740 0,1598",
            ("depositos", "rc5"): "78,2 81,3 80,2 81,9 85,6 84,4 82,9 86,4 85,2",
            ("depositos", "en"): "6,8 6,5 7,1 6,2 5,8 6,4 6,0 5,7 6,3",
            ("creditos", "ihhn"): "0,1242 0,1291 0,1280 0,1551 0,1629 0,1618 0,1653 0,1723 0,1712",
            ("creditos", "rc5"): "73,2 74,3 73,2 80,9 83,3 83,5 83,5 85,7 85,9",
            ("creditos", "en"): "8,1 7,7 7,8 6,4 6,1 6,2 6,1 5,8 5,8",
        },
        notes=["operaciones domésticas; SFN = segmento bancário e não bancário (b1+b2+b3+b4+n1); "
               "activo total ajustado (ATA); depósitos − interfinanceiros + LCA + LCI + LF"],
    ),
    TableSpec(
        "REB2018_T6.3", 20, "REB 2018", "reb_2018.pdf",
        f"{PUB}/relatorioeconomiabancaria/reb_2018.pdf", 145, 144,
        "Tabela 6.3 «Síntese dos indicadores de concentração das séries temporais»",
        "antiguo", "segmentos", [2016, 2017, 2018],
        {
            ("activos", "ihhn"): "0,1149 0,1139 0,1089 0,1398 0,1396 0,1333 0,1452 0,1449 0,1389",
            ("activos", "rc5"): "71,2 70,8 69,3 81,2 81,1 79,5 82,7 82,6 81,2",
            ("activos", "en"): "8,7 8,8 9,2 7,2 7,2 7,5 6,9 6,9 7,2",
            ("depositos", "ihhn"): "0,1544 0,1411 0,1297 0,1710 0,1566 0,1447 0,1740 0,1593 0,1479",
            ("depositos", "rc5"): "81,3 80,0 78,4 85,6 84,3 82,9 86,4 85,0 83,8",
            ("depositos", "en"): "6,5 7,1 7,7 5,8 6,4 6,9 5,7 6,3 6,8",
            ("creditos", "ihhn"): "0,1291 0,1276 0,1205 0,1629 0,1614 0,1530 0,1723 0,1708 0,1630",
            ("creditos", "rc5"): "74,3 73,0 70,9 83,3 83,4 82,2 85,7 85,8 84,8",
            ("creditos", "en"): "7,7 7,8 8,3 6,1 6,2 6,5 5,8 5,9 6,1",
        },
        notes=["operaciones domésticas; SFN = b1+b2+b3+b4+n1"],
    ),
    TableSpec(
        "REB2019_T6.1", 30, "REB 2019", "reb_2019.pdf",
        f"{PUB}/relatorioeconomiabancaria/reb_2019.pdf", 124, 124,
        "Tabela 6.1 «Síntese dos indicadores de concentração das séries temporais»",
        "antiguo", "segmentos", [2017, 2018, 2019],
        {
            ("activos", "ihhn"): "0,1140 0,1090 0,1071 0,1397 0,1334 0,1308 0,1450 0,1390 0,1367",
            ("activos", "rc5"): "70,8 69,3 69,8 81,1 79,5 79,2 82,6 81,2 81,0",
            ("activos", "en"): "8,8 9,2 9,3 7,2 7,5 7,6 6,9 7,2 7,3",
            ("depositos", "ihhn"): "0,1411 0,1297 0,1263 0,1566 0,1447 0,1419 0,1593 0,1479 0,1456",
            ("depositos", "rc5"): "80,0 78,4 77,6 84,3 82,8 82,3 85,0 83,8 83,4",
            ("depositos", "en"): "7,1 7,7 7,9 6,4 6,9 7,0 6,3 6,8 6,9",
            ("creditos", "ihhn"): "0,1276 0,1205 0,1124 0,1614 0,1530 0,1427 0,1708 0,1630 0,1532",
            ("creditos", "rc5"): "73,0 70,9 69,8 83,4 82,2 80,7 85,8 84,8 83,7",
            ("creditos", "en"): "7,8 8,3 8,9 6,2 6,5 7,0 5,9 6,1 6,5",
        },
        notes=["operaciones domésticas; SFN = b1+b2+b3+b4+n1"],
    ),
    TableSpec(
        "REB2020_T6.1", 40, "REB 2020", "reb_2020.pdf",
        f"{PUB}/relatorioeconomiabancaria/reb_2020.pdf", 130, 130,
        "Tabela 6.1 «Síntese dos indicadores de concentração das séries temporais»",
        "antiguo", "segmentos", [2018, 2019, 2020],
        {
            ("activos", "ihhn"): "0,1090 0,1071 0,0983 0,1334 0,1308 0,1207 0,1390 0,1367 0,1259",
            ("activos", "rc5"): "69,3 69,8 67,0 79,5 79,2 76,0 81,2 81,0 77,6",
            ("activos", "en"): "9,2 9,3 10,2 7,5 7,6 8,3 7,2 7,3 7,9",
            ("depositos", "ihhn"): "0,1297 0,1263 0,1103 0,1447 0,1419 0,1261 0,1479 0,1456 0,1306",
            ("depositos", "rc5"): "78,4 77,6 72,7 82,8 82,3 77,7 83,8 83,4 79,1",
            ("depositos", "en"): "7,7 7,9 9,1 6,9 7,0 7,9 6,8 6,9 7,7",
            ("creditos", "ihhn"): "0,1205 0,1124 0,1069 0,1530 0,1427 0,1367 0,1630 0,1532 0,1456",
            ("creditos", "rc5"): "70,9 69,8 68,5 82,2 80,7 79,2 84,8 83,7 81,8",
            ("creditos", "en"): "8,3 8,9 9,4 6,5 7,0 7,3 6,1 6,5 6,9",
        },
        notes=["operaciones domésticas; SFN = b1+b2+b3+b4+n1 (b2 incluye bancos de câmbio)"],
    ),
    TableSpec(
        "REB2021_TA", 50, "REB 2021", "reb_2021.pdf",
        f"{PUB}/relatorioeconomiabancaria/reb_2021.pdf", 192, 192,
        "Anexo C, Tabela A «Síntese dos indicadores de concentração do SFN» (serie RC5)",
        "antiguo", "segmentos", [2018, 2019, 2020, 2021],
        {
            ("activos", "ihhn"): "0,1090 0,1071 0,0983 0,0931 0,1334 0,1308 0,1207 0,1180 "
                                 "0,1390 0,1367 0,1259 0,1232",
            ("activos", "rc5"): "69,3 69,8 67,0 65,2 79,5 79,2 76,0 74,9 81,2 81,0 77,6 76,6",
            ("activos", "en"): "9,2 9,3 10,2 10,7 7,5 7,6 8,3 8,5 7,2 7,3 7,9 8,1",
            ("depositos", "ihhn"): "0,1297 0,1263 0,1103 0,1034 0,1447 0,1419 0,1261 0,1213 "
                                   "0,1479 0,1456 0,1306 0,1262",
            ("depositos", "rc5"): "78,4 77,6 72,7 70,0 82,8 82,3 77,7 75,9 83,8 83,4 79,1 77,4",
            ("depositos", "en"): "7,7 7,9 9,1 9,7 6,9 7,0 7,9 8,2 6,8 6,9 7,7 7,9",
            ("creditos", "ihhn"): "0,1205 0,1124 0,1069 0,1034 0,1530 0,1427 0,1367 0,1345 "
                                  "0,1630 0,1532 0,1456 0,1434",
            ("creditos", "rc5"): "70,9 69,8 68,5 67,9 82,2 80,7 79,2 78,7 84,8 83,7 81,8 81,4",
            ("creditos", "en"): "8,3 8,9 9,4 9,7 6,5 7,0 7,3 7,4 6,1 6,5 6,9 7,0",
        },
        notes=["tabla publicada «para comparabilidad con las ediciones anteriores» (nota 69); "
               "mismo perímetro que REB 2017-2020"],
    ),
    TableSpec(
        "REB2022_TA", 60, "REB 2022", "reb_2022.pdf",
        f"{PUB}/relatorioeconomiabancaria/reb2022p.pdf", 216, 216,
        "Anexo C, Tabela A «Síntese dos indicadores de concentração do SFN» (serie RC5)",
        "antiguo", "segmentos", [2019, 2020, 2021, 2022],
        {
            ("activos", "ihhn"): "0,1071 0,0981 0,0928 0,0888 0,1308 0,1206 0,1179 0,1148 "
                                 "0,1367 0,1255 0,1229 0,1208",
            ("activos", "rc5"): "69,8 66,9 65,1 63,8 79,2 76,0 74,9 73,5 81,0 77,5 76,5 75,4",
            ("activos", "en"): "9,3 10,2 10,8 11,3 7,6 8,3 8,5 8,7 7,3 8,0 8,1 8,3",
            ("depositos", "ihhn"): "0,1263 0,1103 0,1032 0,0982 0,1419 0,1261 0,1213 0,1182 "
                                   "0,1456 0,1303 0,1258 0,1231",
            ("depositos", "rc5"): "77,6 72,7 70,0 68,0 82,3 77,7 75,9 74,7 83,4 79,0 77,3 76,2",
            ("depositos", "en"): "7,9 9,1 9,7 10,2 7,0 7,9 8,2 8,5 6,9 7,7 8,0 8,1",
            ("creditos", "ihhn"): "0,1124 0,1068 0,1034 0,1015 0,1427 0,1367 0,1344 0,1329 "
                                  "0,1532 0,1455 0,1431 0,1430",
            ("creditos", "rc5"): "69,8 68,5 67,9 66,9 80,7 79,2 78,7 77,6 83,7 81,8 81,3 80,6",
            ("creditos", "en"): "8,9 9,4 9,7 9,9 7,0 7,3 7,4 7,5 6,5 6,9 7,0 7,0",
        },
        notes=["el IHHn del SFN de 2020-2022 coincide con la Tabela 6.1 de la misma edición "
               "(método nuevo); el de 2019 conserva el valor del método antiguo"],
    ),
    TableSpec(
        "REB2021_T6.1", 51, "REB 2021", "reb_2021.pdf",
        f"{PUB}/relatorioeconomiabancaria/reb_2021.pdf", 95, 95,
        "Tabela 6.1 «Síntese dos indicadores de concentração do SFN»", "nuevo", "sfn",
        [2019, 2020, 2021],
        {
            "b1b2": "88,1 88,1 87,0 94,3 93,5 92,2 86,5 86,4 86,2",
            "b3": "3,3 3,8 5,3 4,7 5,3 6,0 4,3 5,1 6,1",
            "b4": "7,7 7,0 6,3 0,3 0,2 0,2 8,1 7,4 6,3",
            "n1n2": "0,9 1,1 1,4 0,7 1,0 1,6 1,1 1,1 1,4",
            "n4": "0,0 0,0 0,1 0,0 0,0 0,1 0,0 0,0 0,0",
            "publico": "42,4 40,6 38,0 39,8 34,9 32,6 47,6 45,6 43,5",
            "privado": "57,6 59,4 62,0 60,2 65,1 67,4 52,4 54,4 56,5",
            "ihhn": "0,1070 0,0981 0,0928 0,1263 0,1103 0,1032 0,1124 0,1069 0,1034",
            "en": "9,3 10,2 10,8 7,9 9,1 9,7 8,9 9,4 9,7",
            "rc4": "0,600 0,573 0,560 0,672 0,627 0,601 0,606 0,594 0,593",
        },
        rc4_as_fraction=True,
        notes=["primera edición con RC4, SFN ampliado (b1+b2+b3+b4+n1+n2+n4) y conglomerado "
               "prudencial del IF.data (nota 84); operaciones domésticas"],
    ),
    TableSpec(
        "REB2022_T6.1", 61, "REB 2022", "reb_2022.pdf",
        f"{PUB}/relatorioeconomiabancaria/reb2022p.pdf", 89, 89,
        "Tabela 6.1 «Síntese dos indicadores de concentração do SFN»", "nuevo", "sfn",
        [2020, 2021, 2022],
        {
            "b1b2": "88,1 87,0 86,8 93,5 92,2 91,1 86,4 86,2 86,1",
            "b3": "3,8 5,3 5,1 5,3 6,0 6,4 5,1 6,1 6,4",
            "b4": "7,0 6,3 4,9 0,2 0,2 0,1 7,4 6,3 5,7",
            "n1n2": "1,1 1,4 2,2 1,0 1,5 2,2 1,2 1,4 1,7",
            "n4": "0,0 0,1 0,0 0,0 0,1 0,0 0,0 0,0 0,0",
            "publico": "40,6 38,0 37,0 34,9 32,6 32,0 45,6 43,5 43,7",
            "privado": "59,4 62,0 63,0 65,1 67,4 68,0 54,4 56,5 56,3",
            "ihhn": "0,0981 0,0928 0,0888 0,1103 0,1032 0,0982 0,1068 0,1034 0,1015",
            "en": "10,2 10,8 11,3 9,1 9,7 10,2 9,4 9,7 9,9",
            "rc4": "57,3 56,0 55,7 62,7 60,1 58,9 59,4 59,3 59,0",
        },
        notes=["SFN b1+b2+b3+b4+n1+n2+n4; conglomerado prudencial (nota 74); operaciones domésticas"],
    ),
    TableSpec(
        "REB2023_T5.1", 70, "REB 2023", "reb_2023.pdf",
        f"{PUB}/relatorioeconomiabancaria/reb2023p.pdf", 57, 57,
        "Tabela 5.1 «Síntese dos indicadores de concentração do SFN»", "nuevo", "sfn",
        [2021, 2022, 2023],
        {
            "b1b2": "87,7 87,8 87,6 92,2 91,2 90,7 86,3 86,2 85,9",
            "b3": "4,5 5,1 5,5 5,9 6,4 6,6 6,0 6,3 6,8",
            "b4": "6,3 4,9 4,5 0,2 0,1 0,1 6,2 5,7 5,3",
            "n1n2": "1,5 2,0 2,2 1,6 2,2 2,4 1,5 1,7 2,0",
            "n4": "0,1 0,2 0,2 0,1 0,1 0,1 0,0 0,0 0,0",
            "publico": "38,3 37,2 37,5 32,5 31,7 32,6 43,5 43,5 44,1",
            "privado": "61,7 62,8 62,5 67,5 68,3 67,4 56,5 56,5 55,9",
            "ihhn": "0,0929 0,0896 0,0882 0,1016 0,0966 0,0945 0,1022 0,1003 0,0990",
            "en": "10,8 11,2 11,3 9,8 10,3 10,6 9,8 10,0 10,1",
            "rc4": "56,1 56,0 55,3 59,7 58,4 57,9 58,9 58,6 57,8",
        },
        notes=["SFN b1+b2+b3+b4+n1+n2+n4; conglomerado prudencial (nota 41, apéndice p. 63); "
               "última edición del REB"],
    ),
    TableSpec(
        "REF202504_T2.4.1", 80, "REF abr-2025", "ref_202504.pdf",
        f"{PUB}/ref/202504/RELESTAB202504-refPub.pdf", 75, 75,
        "Anexo estatístico, Tabela 2.4.1 «Síntese dos indicadores de concentração do SFN»",
        "nuevo", "sfn", [2022, 2023, 2024],
        {
            "b1b2": "87,8 87,6 86,6 91,2 90,7 89,0 86,2 85,8 85,0",
            "b3": "5,1 5,5 5,9 6,4 6,6 7,5 6,3 6,8 7,2",
            "b4": "4,9 4,5 4,7 0,1 0,1 0,3 5,7 5,3 5,2",
            "n1n2": "2,0 2,2 2,4 2,2 2,5 3,0 1,7 2,0 2,6",
            "n4": "0,2 0,2 0,3 0,1 0,1 0,2 0,0 0,0 0,0",
            "publico": "37,2 37,4 37,4 31,7 32,6 33,3 43,5 44,1 44,0",
            "privado": "62,8 62,6 62,6 68,3 67,4 66,7 56,5 55,9 56,0",
            "ihhn": "0,0896 0,0881 0,087 0,0966 0,0944 0,0919 0,1003 0,099 0,0986",
            "en": "11,2 11,3 11,5 10,3 10,6 10,9 10,0 10,1 10,1",
            "rc4": "56,0 55,3 54,7 58,4 57,9 57,1 58,6 57,8 57,9",
        },
        notes=["SFN b1+b2+b3+b4+n1+n2+n4; conglomerado prudencial (nota 146, p. 101); el REF "
               "imprime algunos IHHn con 3 decimales (0,087; 0,099)"],
    ),
    TableSpec(
        "REF202605_T2.2.1", 90, "REF may-2026", "ref_202605.pdf",
        f"{PUB}/ref/202605/RELESTAB202605-refPub.pdf", 66, 66,
        "Anexo estatístico, Tabela 2.2.1 «Síntese dos indicadores de concentração do SFN»",
        "nuevo", "sfn", [2023, 2024, 2025],
        {
            "b1b2": "87,6 86,6 85,8 90,7 89,0 87,8 85,8 85,0 83,5",
            "b3": "5,5 5,9 6,1 6,6 7,5 7,9 6,8 7,2 7,8",
            "b4": "4,5 4,7 4,9 0,1 0,3 0,5 5,3 5,2 5,7",
            "n1n2": "2,2 2,4 3,0 2,5 3,0 3,7 2,0 2,6 3,0",
            "n4": "0,2 0,3 0,2 0,1 0,2 0,1 0,0 0,0 0,0",
            "publico": "37,4 37,4 37,2 32,6 33,3 31,8 44,1 44,0 42,7",
            "privado": "62,6 62,6 62,8 67,4 66,7 68,2 55,9 56,0 57,3",
            "ihhn": "0,0881 0,087 0,0847 0,0944 0,0919 0,0862 0,099 0,0986 0,0944",
            "en": "11,3 11,5 11,8 10,6 10,9 11,6 10,1 10,1 10,6",
            "rc4": "55,3 54,7 54,1 57,9 57,1 55,3 57,8 57,9 57,1",
        },
        notes=["SFN b1+b2+b3+b4+n1+n2+n4; conglomerado prudencial (nota 141, p. 103); el REF "
               "imprime algunos IHHn con 3 decimales (0,087; 0,099)"],
    ),
]


def to_float(token: str) -> float:
    """Convierte '0,1090' o '69,4' (coma decimal brasileña) a float."""
    return float(token.replace(",", "."))


def page_tokens(pdf_name: str, page_pdf: int) -> list[str]:
    """Números con coma decimal de una página, en el orden en que los extrae PyMuPDF."""
    doc = pymupdf.open(PDF_DIR / pdf_name)
    text = doc[page_pdf - 1].get_text()
    return NUMBER_RE.findall(text)


def contains_contiguous(tokens: list[str], row: list[str]) -> bool:
    """¿Aparece `row` como subsecuencia contigua de `tokens`?"""
    n = len(row)
    return any(tokens[i:i + n] == row for i in range(len(tokens) - n + 1))


def verify_tables() -> None:
    """Exige que cada fila transcrita esté en la página citada; si no, se detiene."""
    errors = []
    for spec in TABLES:
        tokens = page_tokens(spec.pdf, spec.page_pdf)
        for key, row_text in spec.rows.items():
            row = row_text.split()
            if not contains_contiguous(tokens, row):
                errors.append(f"{spec.table_id} {key}: fila no encontrada en la página")
    if errors:
        raise SystemExit("Verificación contra el PDF FALLÓ:\n  " + "\n  ".join(errors))
    total = sum(len(s.rows) for s in TABLES)
    print(f"Verificación contra el PDF: {total} filas de {len(TABLES)} tablas, todas encontradas.")


def explode(spec: TableSpec) -> list[dict]:
    """Pasa una tabla a registros largos: (año, segmento, variable, indicador, valor)."""
    records = []
    ny = len(spec.years)
    for key, row_text in spec.rows.items():
        values = [to_float(t) for t in row_text.split()]
        if spec.layout == "segmentos":
            variable, indicator = key
            for s_idx, segment in enumerate(SEGMENTS_OLD):
                for y_idx, year in enumerate(spec.years):
                    records.append(dict(table=spec, year=year, segment=segment,
                                        variable=variable, indicator=indicator,
                                        value=values[s_idx * ny + y_idx]))
        else:
            indicator = key
            for v_idx, variable in enumerate(VARIABLES):
                for y_idx, year in enumerate(spec.years):
                    value = values[v_idx * ny + y_idx]
                    if indicator == "rc4" and spec.rc4_as_fraction:
                        value = round(value * 100, 1)
                    records.append(dict(table=spec, year=year, segment="sfn",
                                        variable=variable, indicator=indicator, value=value))
    return records


def internal_checks(records: list[dict]) -> None:
    """E.N. ≈ 1/IHHn, público + privado = 100 y suma de segmentos ≈ 100 (redondeo)."""
    idx = {(r["table"].table_id, r["year"], r["segment"], r["variable"], r["indicator"]): r["value"]
           for r in records}
    problems, warnings = [], []
    for (tid, year, seg, var, ind), value in idx.items():
        if ind == "ihhn":
            en = idx.get((tid, year, seg, var, "en"))
            # El IHHn impreso con 3 decimales (0,087) admite más holgura.
            if en is not None and abs(1 / value - en) > 0.16:
                problems.append(f"{tid} {year} {seg} {var}: 1/IHHn={1 / value:.2f} vs E.N.={en}")
        if ind == "publico":
            priv = idx.get((tid, year, seg, var, "privado"))
            if priv is not None and abs(value + priv - 100) > 0.11:
                problems.append(f"{tid} {year} {var}: público+privado={value + priv}")
        if ind == "b1b2":
            parts = [idx.get((tid, year, seg, var, k)) for k in ("b1b2", "b3", "b4", "n1n2", "n4")]
            if None not in parts and abs(sum(parts) - 100) > 0.31:
                # Aviso, no error: la tabla publicada no cierra (verificado en la imagen).
                warnings.append(f"{tid} {year} {var}: suma de segmentos={sum(parts):.1f} "
                                f"(anomalía del original; no afecta IHHn ni RC4)")
    if problems:
        raise SystemExit("Controles internos FALLARON:\n  " + "\n  ".join(problems))
    print("Controles internos (E.N.≈1/IHHn; público+privado=100): OK.")
    for w in warnings:
        print(f"  AVISO segmentos≈100: {w}")


def fmt_pt(value: float, indicator: str) -> str:
    """Formato brasileño para el informe de revisiones."""
    if indicator == "ihhn":
        return f"{value:.4f}".replace(".", ",")
    return f"{value:.1f}".replace(".", ",")


def revisions(records: list[dict]) -> dict:
    """Valores de un mismo (año, variable, indicador) del SFN que cambian entre ediciones."""
    groups: dict = {}
    for r in records:
        if r["segment"] != "sfn" or r["indicator"] not in ("ihhn", "rc4", "rc5", "publico"):
            continue
        key = (r["year"], r["variable"], r["indicator"])
        groups.setdefault(key, []).append(r)
    out = {}
    for key, items in groups.items():
        items.sort(key=lambda r: r["table"].order)
        distinct = {round(r["value"], 4) for r in items}
        if len(distinct) > 1:
            out[key] = items
    return out


def pick(records: list[dict], year: int, variable: str, indicator: str, method: str):
    """Registro de la edición más reciente (mayor `order`) con ese método."""
    cands = [r for r in records if r["year"] == year and r["variable"] == variable
             and r["indicator"] == indicator and r["segment"] == "sfn"
             and r["table"].method == method]
    return max(cands, key=lambda r: r["table"].order) if cands else None


def value_of(records: list[dict], table: TableSpec, year: int, variable: str,
             indicator: str):
    """Valor del SFN de una tabla concreta, o None si la tabla no lo trae."""
    for r in records:
        if (r["table"] is table and r["year"] == year and r["variable"] == variable
                and r["indicator"] == indicator and r["segment"] == "sfn"):
            return r["value"]
    return None


def build_rows(records: list[dict], revs: dict) -> list[dict]:
    """Una fila por año y variable con la cifra oficial de la edición más reciente."""
    rows = []
    for year in range(2015, 2026):
        for variable in ("creditos", "depositos", "activos"):
            ihh_rec = pick(records, year, variable, "ihhn", "nuevo")
            method = "nuevo" if ihh_rec else "antiguo"
            if ihh_rec is None:
                ihh_rec = pick(records, year, variable, "ihhn", "antiguo")
            if ihh_rec is None:
                raise SystemExit(f"Sin cifra oficial para {year} {variable}")
            spec = ihh_rec["table"]
            cr4 = value_of(records, spec, year, variable, "rc4")
            cr5 = value_of(records, spec, year, variable, "rc5")
            peso = value_of(records, spec, year, variable, "publico")
            notes = list(spec.notes)
            if method == "nuevo" and cr5 is None:
                # RC5 solo si la misma edición publica una tabla RC5 cuyo IHHn del SFN es
                # idéntico al de la tabla RC4 en las TRES variables de ese año: así se sabe que
                # es el mismo perímetro (una coincidencia en una sola variable puede ser azar).
                for t in {r["table"].table_id: r["table"] for r in records}.values():
                    if t.edition != spec.edition or t.method != "antiguo":
                        continue
                    if all(value_of(records, t, year, v, "ihhn")
                           == value_of(records, spec, year, v, "ihhn") for v in VARIABLES):
                        cr5 = value_of(records, t, year, variable, "rc5")
                        notes.append(f"cr5 de {t.edition}, {t.title.split(' «')[0]} "
                                     f"(p. {t.page_printed}): su IHHn coincide con el de la "
                                     f"tabla RC4 en las tres variables")
            if method == "antiguo":
                notes.append("RC4 del SFN no publicado para este año (el REB usaba RC5 hasta la "
                             "edición 2020); base contable no declarada en la edición")
            # Revisiones de este año/variable entre ediciones, SOLO dentro del mismo método
            # (un cambio de método es una ruptura, no una revisión; va en el informe).
            for ind in ("ihhn", "rc4", "rc5", "publico"):
                items = [r for r in revs.get((year, variable, ind), [])
                         if r["table"].method == spec.method]
                if len({round(r["value"], 4) for r in items}) > 1:
                    seq = " → ".join(f"{fmt_pt(r['value'], ind)} ({r['table'].edition}, "
                                     f"{r['table'].table_id.split('_')[1]})"
                                     for r in items)
                    notes.append(f"revisión {ind.upper()}: {seq}")
            notes.append("incluye bancos públicos; IHH = IHHn × 10 000")
            rows.append({
                "pais": "Brasil",
                "anio": year,
                "variable": variable,
                "variante": "oficial_con_estatales",
                "base": "conglomerado_prudencial" if method == "nuevo" else "no_especificada",
                "n": "",
                "cr4": f"{cr4:.1f}" if cr4 is not None else "",
                "cr5": f"{cr5:.1f}" if cr5 is not None else "",
                "ihh": str(round(ihh_rec["value"] * 10000)),
                "peso_estatal": f"{peso:.1f}" if peso is not None else "",
                "fuente": spec.source_text(),
                "notas": "; ".join(notes),
            })
    return rows


def write_csv(rows: list[dict]) -> None:
    """Escribe la salida en UTF-8 sin BOM (igual que los CSV de los demás países)."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fields = ["pais", "anio", "variable", "variante", "base", "n", "cr4", "cr5", "ihh",
              "peso_estatal", "fuente", "notas"]
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Escrito: {OUT_CSV.relative_to(ROOT)} ({len(rows)} filas)")


def print_revisions(revs: dict) -> None:
    """Imprime el registro de revisiones (para el informe de trabajo)."""
    print("\nRevisiones del SFN entre ediciones (método entre corchetes):")
    for (year, variable, ind), items in sorted(revs.items()):
        seq = " → ".join(f"{fmt_pt(r['value'], ind)} [{r['table'].edition} "
                         f"{r['table'].table_id.split('_')[1]}, {r['table'].method}]"
                         for r in items)
        print(f"  {year} {variable:9s} {ind:7s}: {seq}")


def print_ref_b1_annex() -> None:
    """Serie complementaria (NO va al CSV): IHH y RC4 de diciembre del segmento bancário
    comercial (b1) en los anexos xlsx del REF 2017-2018 (hojas «IHH» y «RC4»).

    Perímetro distinto del SFN: solo b1 («bancos múltiplos com carteira comercial, bancos
    comerciais e Caixa Econômica Federal») y, según la nota 105 del REB 2017, operaciones
    en Brasil y en el exterior. Columnas del xlsx: Ativos, Operações de crédito, Depósitos.
    """
    import datetime as dt
    import openpyxl

    xlsx_dir = ROOT / "data" / "raw" / "internacional" / "brasil" / "xlsx"
    print("\nComplementaria: REF, anexo estadístico, segmento bancário comercial (b1), diciembre")
    for name in ("ref_201704_anexo.xlsx", "ref_201710_anexo.xlsx", "ref_201804_anexo.xlsx"):
        path = xlsx_dir / name
        if not path.exists():
            print(f"  falta {name}")
            continue
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        for sheet in ("IHH", "RC4"):
            for row in wb[sheet].iter_rows(values_only=True):
                cells = [c for c in row if c is not None]
                dates = [c for c in cells if isinstance(c, dt.datetime)]
                if dates and dates[0].month == 12 and dates[0].year >= 2015:
                    nums = [c for c in cells if isinstance(c, float)]
                    print(f"  {name} {sheet} dic-{dates[0].year}: ativos={nums[0]:.2f} "
                          f"crédito={nums[1]:.2f} depósitos={nums[2]:.2f}")


def _load_json(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)["value"]


def _concentration(values: list[float]) -> dict:
    """CR4, CR5 e IHH (0-10 000) sobre las entidades con valor > 0 (igual que Chile/Colombia)."""
    ordered = sorted((v for v in values if v > 0), reverse=True)
    total = sum(ordered)
    shares = [v / total * 100 for v in ordered]
    return {"n": len(shares), "cr4": sum(shares[:4]), "cr5": sum(shares[:5]),
            "ihh": sum(s * s for s in shares), "total": total}


def ifdata_year(year: int) -> tuple[list[dict], list[str]]:
    """Entidades b1+b2 de diciembre de `year` (créditos y depósitos) desde IF.data tipo 1.

    Tipo 1 = conglomerados prudenciales e instituciones independientes. Devuelve las filas
    por entidad y las notas de control del año. Se detiene ante cualquier inconsistencia.
    """
    am = f"{year}12"
    cad = {r["CodInst"]: r for r in _load_json(IFDATA_DIR / f"cadastro_{am}.json")}
    picked, missing = {}, {}
    for variable, report, formulas in (("creditos", "1", IFDATA_CRED), ("depositos", "3", IFDATA_DEP)):
        vals, seen = {}, set()
        for r in _load_json(IFDATA_DIR / f"valores_{am}_tipo1_rel{report}.json"):
            if r["DescricaoColuna"] in formulas:
                if r["CodInst"] in seen:
                    raise SystemExit(f"IF.data {am}: {r['CodInst']} repetido en {variable}")
                seen.add(r["CodInst"])
                if r["Saldo"] is None:   # sin dato (no entregó el balance): no es un cero
                    missing.setdefault(variable, []).append(r["CodInst"])
                else:
                    vals[r["CodInst"]] = float(r["Saldo"])
        if not vals:
            raise SystemExit(f"IF.data {am}: no se encontró la columna de {variable}")
        picked[variable] = vals
    notes = []
    for variable, cods in missing.items():
        banks = [cad[c]["NomeInstituicao"] for c in cods if c in cad and cad[c]["Tcb"] in IFDATA_TCB]
        if banks:
            notes.append(f"{variable}: sin dato en IF.data (no entregó el balance), fuera del cálculo: "
                         f"{', '.join(sorted(banks))}")
    # Entidades sin cadastro: solo se aceptan si su peso es despreciable.
    for variable, vals in picked.items():
        total = sum(vals.values())
        unmatched = {c: v for c, v in vals.items() if c not in cad}
        if unmatched:
            share = sum(unmatched.values()) / total
            if share > IFDATA_MAX_UNMATCHED:
                raise SystemExit(f"IF.data {am}: sin cadastro {unmatched} ({share:.4%})")
            notes.append(f"{variable}: {len(unmatched)} entidad sin cadastro descartada "
                         f"({', '.join(sorted(unmatched))}; {share:.4%} del total del tipo 1)")
    # Doble conteo: una institución que reporta sola y cuyo conglomerado prudencial también
    # reporta ya está dentro de ese conglomerado.
    reporting = set(picked["creditos"]) | set(picked["depositos"])
    dropped = sorted(c for c in reporting if c in cad and not c.startswith("C")
                     and cad[c].get("CodConglomeradoPrudencial") in reporting)
    rows = []
    for variable, vals in picked.items():
        for cod, value in vals.items():
            info = cad.get(cod)
            if info is None or cod in dropped or info["Tcb"] not in IFDATA_TCB:
                continue
            rows.append({"pais": "Brasil", "anio": year, "mes": 12, "entidad": info["NomeInstituicao"],
                         "cod_inst": cod, "tcb": info["Tcb"], "tc": info["Tc"],
                         "estatal": info["Tc"] == IFDATA_TC_PUBLIC, "variable": variable,
                         "valor": value, "unidad": "brl", "base": "conglomerado_prudencial",
                         "fuente_url": f"{IFDATA_ODATA}/IfDataValores (AnoMes={am}, TipoInstituicao=1, "
                                       f"Relatorio={'1' if variable == 'creditos' else '3'})"})
    if dropped:
        names = [f"{cad[c]['NomeInstituicao']} ({cad[c]['Tcb']})" for c in dropped
                 if cad[c]["Tcb"] in IFDATA_TCB]
        notes.append(f"{len(dropped)} instituciones independientes descartadas porque su conglomerado "
                     f"prudencial también reporta" + (f"; b1/b2 entre ellas: {', '.join(names)}" if names else ""))
    return rows, notes


def build_ifdata_rows() -> tuple[list[dict], list[dict]]:
    """Cálculo propio con y sin bancos públicos (segmento b1+b2), dic-2015 a dic-2025."""
    entities, out = [], []
    for year in range(2015, 2026):
        rows, notes = ifdata_year(year)
        entities += rows
        for variable in ("creditos", "depositos"):
            cur = [r for r in rows if r["variable"] == variable]
            full = _concentration([r["valor"] for r in cur])
            private = _concentration([r["valor"] for r in cur if not r["estatal"]])
            public = sum(r["valor"] for r in cur if r["estatal"] and r["valor"] > 0)
            ranked = sorted((r for r in cur if r["valor"] > 0), key=lambda r: -r["valor"])
            top4 = ", ".join(f"{r['entidad'].replace(' - PRUDENCIAL', '')}"
                             f"{' (público)' if r['estatal'] else ''}" for r in ranked[:4])
            n_pub = sum(1 for r in cur if r["estatal"] and r["valor"] > 0)
            definition = ("cartera de crédito clasificada (cuenta 31000000)" if variable == "creditos"
                          and year < 2025 else "cartera de crédito, Cosif 1.5 (quiebre de definición "
                          "en 2025)" if variable == "creditos" else "depósito total (grupo 41, incluye "
                          "interfinancieros)")
            common = [f"segmento bancario b1+b2 del IF.data (conglomerados prudenciales e instituciones "
                      f"independientes); sin cooperativas, bancos de desarrollo (BNDES) ni no bancarias",
                      definition, "entidades con valor > 0"] + [
                      n for n in notes if not n.startswith(("creditos:", "depositos:"))
                      or n.startswith(variable + ":")]
            source = (f"BCB, IF.data (API OData), cadastro y relatorio "
                      f"{'1 «Resumo»' if variable == 'creditos' else '3 «Passivo»'}, dic-{year}, {IFDATA_ODATA}")
            for variant, m, extra in (
                    ("con_estatales", full, [f"incluye {n_pub} bancos públicos (Tc = 1); 4 mayores: {top4}"]),
                    ("sin_estatales", private, [f"excluye los bancos públicos (su peso en el total con "
                                                f"estatales es {public / full['total'] * 100:.2f} %)"])):
                out.append({"pais": "Brasil", "anio": year, "variable": variable, "variante": variant,
                            "base": "conglomerado_prudencial", "n": m["n"], "cr4": f"{m['cr4']:.4f}",
                            "cr5": f"{m['cr5']:.4f}", "ihh": f"{m['ihh']:.2f}",
                            "peso_estatal": f"{public / full['total'] * 100:.4f}" if variant == "con_estatales" else "",
                            "fuente": source, "notas": "; ".join(common + extra)})
    return entities, out


def write_entities(rows: list[dict]) -> None:
    fields = ["pais", "anio", "mes", "entidad", "cod_inst", "tcb", "tc", "estatal", "variable",
              "valor", "unidad", "base", "fuente_url"]
    with open(ENT_CSV, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Escrito: {ENT_CSV.relative_to(ROOT)} ({len(rows)} filas)")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    verify_tables()
    records = [rec for spec in TABLES for rec in explode(spec)]
    internal_checks(records)
    revs = revisions(records)
    rows = build_rows(records, revs)
    entities, own = build_ifdata_rows()
    write_entities(entities)
    write_csv(rows + own)
    print("\nCálculo propio (IF.data, b1+b2):")
    for r in own:
        print(f"  {r['anio']} {r['variable']:9s} {r['variante']:13s} n={r['n']:>3} cr4={float(r['cr4']):5.1f} "
              f"cr5={float(r['cr5']):5.1f} ihh={float(r['ihh']):6.0f} público={r['peso_estatal'][:5] or '—'}")
    print("\nSerie oficial (SFN):")
    for r in rows:
        print(f"  {r['anio']} {r['variable']:9s} cr4={r['cr4'] or '—':>5} cr5={r['cr5'] or '—':>5} "
              f"ihh={r['ihh']:>5} público={r['peso_estatal'] or '—':>5}  {r['fuente'].split(',')[1]}")
    print_revisions(revs)
    print_ref_b1_annex()
    return 0


if __name__ == "__main__":
    sys.exit(main())
