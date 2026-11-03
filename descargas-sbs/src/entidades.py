"""Maestro de entidades del sistema financiero: reconoce cualquier variante de nombre de la SBS.

La SBS escribe la misma entidad de muchas formas («B. de Crédito del Perú (con sucursales
en el exterior)», «Banco de Crédito del Perú», «CMAC Piura***», «CRAC Censosud Scotia»...)
y además las entidades cambian de nombre y de subsistema (Compartamos Financiera →
Compartamos Banco; CrediScotia → Financiera Santander Consumer → Santander Consumer Bank).

Tablas curadas en `config/entidades/`:
- `entidad.csv`           una fila por entidad: id estable que no cambia aunque cambie el nombre.
- `entidad_alias.csv`     clave normalizada → id_entidad (todas las variantes vistas). Columnas
                          opcionales `desde`/`hasta` (AAAAMM): el alias solo vale en ese rango.
                          Sirve cuando el MISMO nombre designa a dos entidades según el mes
                          («Financiera Confianza» = la financiera original hasta 2013-04 y la
                          ex CRAC Nuestra Gente desde 2013-05).
- `entidad_vigencia.csv`  nombre y subsistema de cada entidad por periodo (historial).
- `entidad_evento.csv`    cambios de nombre o subsistema, fusiones, ingresos y salidas, con resolución SBS.

Uso desde otro proyecto:
    import sys; sys.path.insert(0, r"<ruta>/descargas-sbs/src")
    from entidades import Maestro
    m = Maestro()
    m.resolver("B. de Crédito del Perú (con sucursales en el exterior)")   # -> "bcp"
    m.vigencia("santander-consumer", 202504)   # -> subsistema y nombre vigentes ese mes
"""
from __future__ import annotations

import csv
import re
import unicodedata
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config" / "entidades"

# Abreviaturas de la SBS → forma larga, aplicadas sobre el texto ya normalizado.
PREFIJOS = [
    (r"^b\. ?", "banco "),
    (r"^bco\.? ", "banco "),
    (r"^cmac ", "caja municipal "),
    (r"^cmcp ", "caja municipal de credito popular "),
    (r"^caja municipal de ahorro y credito( de)? ", "caja municipal "),
    (r"^crac ", "caja rural "),
    (r"^caja rural de ahorro y credito ", "caja rural "),
    # Empresas de créditos: la misma entidad aparece como «EDPYME Alternativa»,
    # «EC Alternativa» y «Alternativa» según el mes y el cuadro → se quita el prefijo.
    (r"^(edpyme|ec|e\. ?c\.|empresa de creditos?|entidad de desarrollo a la pequena y micro empresa) ", ""),
]
# Superíndices de nota al pie («Vívela¹»): NFKD los convertiría en dígitos pegados al nombre.
SUPERINDICES = "".join(chr(c) for c in (0xB9, 0xB2, 0xB3, *range(0x2070, 0x207A)))
SUFIJOS_SOCIETARIOS = r"\b(s\.?\s?a\.?\s?a\.?|s\.?\s?a\.?|s\.?\s?a\.?\s?c\.?)$"


def normalizar(nombre: str) -> str:
    """Clave de comparación: sin tildes, notas al pie, paréntesis, razón social ni puntuación.

    >>> normalizar("B. De Crédito del Perú (con sucursales en el exterior)")
    'banco de credito del peru'
    >>> normalizar("CMAC Piura***")
    'caja municipal piura'
    >>> normalizar("EDPYME Alternativa") == normalizar("EC Alternativa") == normalizar("Alternativa***")
    True
    >>> normalizar("Vívela¹")
    'vivela'
    """
    s = nombre.translate({ord(c): " " for c in SUPERINDICES})
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\([^)]*\)", " ", s)                  # «(con sucursales…)», «(*)»
    s = re.sub(r"con\s+sucursales\s+en\s+el\s+exterior", " ", s)
    s = re.sub(r"\s*\d+\s*/\s*$|^\s*/?\d+\s*/?\s*|\s/\d+\s*$", " ", s)  # notas «1/», «/2»
    s = re.sub(r"\*+", " ", s)                        # notas «*», «***»
    s = re.sub(r"\s+", " ", s).strip()
    for patron, reemplazo in PREFIJOS:
        s = re.sub(patron, reemplazo, s)
    s = re.sub(SUFIJOS_SOCIETARIOS, "", s).strip()
    s = re.sub(r"[^a-z0-9& ]", " ", s)                # «Oh!», comillas, puntos
    return re.sub(r"\s+", " ", s).strip()


def _leer(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


class Maestro:
    """Carga las tablas curadas y resuelve nombres a `id_entidad`."""

    def __init__(self, config_dir: Path = CONFIG_DIR):
        self.entidades = {r["id_entidad"]: r for r in _leer(config_dir / "entidad.csv")}
        self.vigencias = _leer(config_dir / "entidad_vigencia.csv")
        self.eventos = _leer(config_dir / "entidad_evento.csv")
        # clave -> [(id_entidad, subsistema o "", desde o 0, hasta o 0)]; 0 = sin límite
        self._alias: dict[str, list[tuple[str, str, int, int]]] = {}
        for r in _leer(config_dir / "entidad_alias.csv"):
            self._alias.setdefault(r["clave"], []).append(
                (r["id_entidad"], r["subsistema"], int(r.get("desde") or 0), int(r.get("hasta") or 0)))
        explicitas = set(self._alias)
        for r in self.vigencias:  # el nombre vigente también es un alias válido
            clave = normalizar(r["nombre"])
            # Si la clave ya está en entidad_alias.csv, manda esa tabla (que puede acotar por
            # periodo); si no, un nombre repetido entre dos vigencias sería siempre ambiguo.
            if clave not in explicitas:
                self._alias.setdefault(clave, []).append((r["id_entidad"], r["subsistema"], 0, 0))

    def resolver(self, nombre: str, subsistema: str | None = None, periodo: int | None = None) -> str | None:
        """id_entidad para un nombre tal como aparece en un cuadro; None si no se reconoce.

        Con `periodo` (AAAAMM) se usan los alias vigentes ese mes; sin él, los que no tienen
        `hasta` (el significado actual del nombre). Las vigencias con subsistema `edpyme` valen
        en los cuadros de `empresas-credito` (la SBS publica las EDPYME en ese subsistema).
        """
        candidatos = {i for i, sub, desde, hasta in self._alias.get(normalizar(nombre), [])
                      if (not subsistema or not sub or sub == subsistema
                          or (sub == "edpyme" and subsistema == "empresas-credito"))
                      and ((not desde or desde <= periodo) and (not hasta or periodo <= hasta)
                           if periodo else not hasta)}
        if len(candidatos) > 1:
            raise ValueError(f"Nombre ambiguo {nombre!r}: {sorted(candidatos)}; indique el subsistema")
        return candidatos.pop() if candidatos else None

    def vigencia(self, id_entidad: str, periodo: int) -> dict | None:
        """Nombre y subsistema vigentes de la entidad en el periodo AAAAMM.

        Se basa en los eventos oficiales, no en el nombre impreso en el archivo: la SBS
        republica meses antiguos con el nombre actual de la entidad.
        """
        for r in self.vigencias:
            if (r["id_entidad"] == id_entidad and (not r["desde"] or int(r["desde"]) <= periodo)
                    and (not r["hasta"] or periodo <= int(r["hasta"]))):
                return r
        return None
