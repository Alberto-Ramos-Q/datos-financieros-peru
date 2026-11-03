"""Piezas comunes de los lectores de cuadros del boletín: apertura, celdas, entidades y salida.

Cada tema tiene su módulo en `src/lector/<tema>.py` (guiones → guiones bajos) con una función

    leer(ruta: Path, subsistema: str, periodo: int) -> list[dict]

que devuelve registros con las claves de `CAMPOS_TEMA`. El orquestador (`src/leer_boletin.py`)
agrega periodo, subsistema, tema y código, y resuelve `entidad_original` → `id_entidad`.

Formato largo, una fila por valor publicado:
    periodo | subsistema | tema | codigo | hoja | entidad_original | id_entidad | es_total
    | variable | apertura | valor | unidad
- `variable`: concepto canónico en snake_case (p. ej. `creditos_directos`, `ratio_capital_global`).
- `apertura`: desagregación canónica separada por «|» en un orden fijo documentado en cada
  módulo (p. ej. `consumo|vigentes`, `mn`); vacía si no hay.
- `unidad`: una de `UNIDADES`. Los porcentajes se guardan en puntos porcentuales (4.5 = 4,5 %).
- Si un cuadro trae subtotales que también casan con `TOTAL_RE` (p. ej. «Total Cajas Municipales
  de Ahorro y Crédito», sin la CMCP Lima), el lector devuelve solo el total del subsistema.
"""
from __future__ import annotations

import re
import sys
import unicodedata
import warnings
from pathlib import Path

import pandas as pd

SRC_DIR = Path(__file__).resolve().parents[1]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
from entidades import Maestro  # noqa: E402

MONTH_ABBR = ["en", "fe", "ma", "ab", "my", "jn", "jl", "ag", "se", "oc", "no", "di"]
CAMPOS_TEMA = ["hoja", "entidad_original", "variable", "apertura", "valor", "unidad"]
CAMPOS = ["periodo", "subsistema", "tema", "codigo", "hoja", "entidad_original", "id_entidad",
          "es_total", "variable", "apertura", "valor", "unidad"]
# `miles_soles_por_unidad`: ratios en miles de S/ (por oficina, por empleado); `puesto`: ranking.
UNIDADES = {"miles_soles", "miles_usd", "porcentaje", "veces", "numero", "dias", "soles",
            "miles_soles_por_unidad", "puesto"}
# Unidades que se pueden sumar entre entidades (sirven para validar contra el total publicado).
UNIDADES_ADITIVAS = {"miles_soles", "miles_usd", "numero", "soles"}

# Fila o columna del total del subsistema («TOTAL BANCA MÚLTIPLE», «Total CM», «Total EC»...).
TOTAL_RE = re.compile(
    r"^total\s+(de\s+)?(la\s+)?(banca|bancos|sistema|empresas?|entidades|financieras|cajas?|cm|"
    r"cmac|cr|crac|edpymes?|e\.?\s?c\.?)\b")
# Marcas de «sin dato» que la SBS escribe como texto.
SIN_DATO = {"", "-", "--", "n.d.", "nd", "n.a.", "na", "s.i.", "...", "n.s.", "ns"}

_maestro: Maestro | None = None


def norm(texto) -> str:
    """Minúsculas, sin tildes, sin notas al pie («*», «1/»), espacios colapsados. '' si no es texto."""
    if not isinstance(texto, str):
        return ""
    s = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\*+|\s\d+\s*/\s*$|\d+/\s*$", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def limpiar(texto) -> str:
    """Texto tal como lo escribe la SBS, sin espacios sobrantes."""
    return re.sub(r"\s+", " ", texto).strip() if isinstance(texto, str) else ""


def a_numero(valor) -> float | None:
    """Cifra de una celda; None si está vacía o es una marca de «sin dato»."""
    if isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return None if pd.isna(valor) else float(valor)
    if isinstance(valor, str):
        s = valor.strip().replace("\xa0", "")
        if s.lower() in SIN_DATO:
            return None
        s = s.replace(",", "")
        if re.fullmatch(r"\(?-?\d+(\.\d+)?\)?%?", s):
            negativo = s.startswith("(")
            x = float(s.strip("()%"))
            return -x if negativo else x
    return None


def _tolerar_supbook_ilegible() -> None:
    """Parche de xlrd: no fallar por una referencia a otro libro (registro SUPBOOK) ilegible.

    Algunos .XLS de la SBS traen un vínculo externo cuya ruta no se puede decodificar
    (p. ej. B-230803 de 2015-07: `UnicodeDecodeError` en `Book.handle_supbook`) y xlrd aborta
    el libro entero aunque las celdas estén bien. El parche solo actúa ante ese error: deja el
    vínculo como «tipo desconocido» (lo mismo que xlrd asigna antes de leerlo) y conserva el
    conteo de vínculos, así que los índices de los siguientes no se corren. Los cuadros solo
    usan valores, nunca fórmulas que apunten a otros libros. Los archivos que ya se leían bien
    pasan por el método original sin cambios.
    """
    import xlrd.book

    original = xlrd.book.Book.handle_supbook
    if getattr(original, "_parche_sbs", False):
        return

    def handle_supbook(self, data):
        n_tipos, n_vinculos = len(self._supbook_types), self._supbook_count
        try:
            original(self, data)
        except UnicodeDecodeError:
            del self._supbook_types[n_tipos:]
            self._supbook_types.append(None)
            self._supbook_count = n_vinculos + 1

    handle_supbook._parche_sbs = True
    xlrd.book.Book.handle_supbook = handle_supbook


_tolerar_supbook_ilegible()


def motor(ruta: Path) -> str:
    """xlsx real (firma PK) u OLE2; nunca se decide por la extensión."""
    with open(ruta, "rb") as fh:
        return "openpyxl" if fh.read(2) == b"PK" else "xlrd"


def abrir(ruta: Path) -> dict[str, pd.DataFrame]:
    """Todas las hojas como grillas de celdas (dtype object, sin cabecera, índices 0..n)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        libro = pd.ExcelFile(ruta, engine=motor(ruta))
        return {h: libro.parse(h, header=None, dtype=object) for h in libro.sheet_names}


def periodo_de(ruta: Path) -> int:
    m = re.search(r"-([a-z]{2})(\d{4})\.", ruta.name, re.IGNORECASE)
    return int(m.group(2)) * 100 + MONTH_ABBR.index(m.group(1).lower()) + 1


def codigo_de(ruta: Path) -> str:
    return ruta.name.rsplit("-", 1)[0]


def es_total(nombre: str) -> bool:
    return bool(TOTAL_RE.match(norm(nombre)))


def resolver_entidad(nombre: str, subsistema: str, periodo: int | None = None) -> tuple[str | None, bool]:
    """(id_entidad, es_total). El total del subsistema no tiene id_entidad.

    `periodo` (AAAAMM) distingue nombres que designan a entidades distintas según el mes
    (alias con `desde`/`hasta` en el maestro); sin él vale el significado actual del nombre.
    """
    global _maestro
    if es_total(nombre):
        return None, True
    if _maestro is None:
        _maestro = Maestro()
    try:
        return _maestro.resolver(nombre, subsistema, periodo), False
    except ValueError:
        return None, False


def es_entidad(nombre, subsistema: str) -> bool:
    """True si el texto es el nombre de una entidad conocida o el total del subsistema.

    Útil para ubicar la fila (o columna) de cabecera con los nombres de las entidades.
    """
    if not isinstance(nombre, str) or not nombre.strip():
        return False
    i, total = resolver_entidad(nombre, subsistema)
    return total or i is not None


def registro(hoja: str, entidad: str, variable: str, apertura: str, valor, unidad: str) -> dict | None:
    """Registro de salida de un tema; None si la celda no tiene cifra."""
    x = a_numero(valor)
    if x is None:
        return None
    return {"hoja": hoja, "entidad_original": limpiar(entidad), "variable": variable,
            "apertura": apertura, "valor": x, "unidad": unidad}


def validar_totales(df: pd.DataFrame, tolerancia: float = 0.005) -> pd.DataFrame:
    """Compara la suma de entidades con el total publicado (solo unidades aditivas).

    Devuelve los grupos cuya diferencia relativa supera la tolerancia. Columnas: claves del
    grupo, suma_entidades, total, dif_rel.
    """
    d = df[df["unidad"].isin(UNIDADES_ADITIVAS)]
    claves = ["periodo", "subsistema", "codigo", "hoja", "variable", "apertura", "unidad"]
    tot = d[d["es_total"]].groupby(claves)["valor"].sum().rename("total")
    ent = d[~d["es_total"]].groupby(claves)["valor"].sum().rename("suma_entidades")
    x = pd.concat([ent, tot], axis=1, join="inner").reset_index()
    x["dif_rel"] = (x["suma_entidades"] - x["total"]).abs() / x["total"].abs().clip(lower=1)
    return x[x["dif_rel"] > tolerancia].sort_values("dif_rel", ascending=False)
