"""Descargador de la ejecución presupuestal del MEF (Consulta Amigable, Transparencia Económica).

Navega la Consulta Amigable con los mismos envíos de formulario que hace el navegador al pulsar sus
botones, y guarda cada tabla tal como se muestra en `data/raw/mef_ejecucion/<año>/<tipo>__<vista>.csv`.
No evade ninguna protección: si el sitio responde con un bloqueo o un desafío, se detiene.

Vistas (por año y por tipo de gasto: «todo» = actividades y proyectos, «proyectos» = solo inversión):
- nivel                      gobierno nacional (E), gobiernos locales (M), gobiernos regionales (R)
- nivel_<X>__mes             gasto de cada nivel por mes (para el avance acumulado mes a mes)
- nivel_E__sector            gobierno nacional por sector
- nivel_R__departamento      gobiernos regionales por departamento
- nivel_M__departamento      municipalidades agregadas por departamento
- departamento               todos los niveles por departamento («¿dónde se gasta?»)
- nivel_R__dep_<NN>__mes     cada gobierno regional por mes (solo proyectos; año en curso y anterior)

Columnas de la Consulta: PIA, PIM, certificación, compromiso anual, atención de compromiso mensual,
devengado, girado y avance % (= devengado / PIM). En las vistas por mes, PIA y PIM vienen vacíos.

Los años cerrados no se vuelven a bajar salvo con --refrescar; el año en curso y el anterior, siempre.

Uso:
    python descargar_ejecucion_mef.py                  # 2012 al año en curso
    python descargar_ejecucion_mef.py --desde 2020
    python descargar_ejecucion_mef.py --refrescar      # vuelve a bajar todo
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import logging
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

PROJECT_DIR = Path(__file__).resolve().parents[1]
RAW = PROJECT_DIR / "data" / "raw" / "mef_ejecucion"
CONTROL = PROJECT_DIR / "data" / "_control"
BASE = "https://apps5.mineco.gob.pe/transparencia/Navegador/"
AP = {"todo": "ActProy", "proyectos": "Proyecto"}
COLS = ["codigo", "nombre", "pia", "pim", "certificacion", "compromiso_anual", "atencion_compromiso_mensual",
        "devengado", "girado", "avance_pct"]
PAUSE = 1.5
log = logging.getLogger("mef_ejecucion")


class Blocked(RuntimeError):
    pass


class Navigator:
    def __init__(self):
        self.s = requests.Session()
        # Cliente genérico; sin datos personales en la cabecera.
        self.s.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) descarga-datos-publicos"
        self.n_requests = 0

    def _check(self, r: requests.Response) -> requests.Response:
        self.n_requests += 1
        low = r.text[:5000].lower()
        if r.status_code != 200 or "request unsuccessful" in low or "captcha" in low:
            raise Blocked(f"respuesta {r.status_code}: {r.text[:200]!r}")
        return r

    def _get(self, url, **kw):
        return self._retry(lambda: self.s.get(url, timeout=90, **kw))

    def _post(self, url, data):
        return self._retry(lambda: self.s.post(url, data=data, timeout=120))

    def _retry(self, fn, tries: int = 3):
        """Reintenta solo cortes de red (no bloqueos ni respuestas raras), con espera creciente."""
        for k in range(tries):
            try:
                return fn()
            except (requests.Timeout, requests.ConnectionError) as e:
                if k == tries - 1:
                    raise
                log.warning("corte de red (%s); reintento en %d s", type(e).__name__, 10 * (k + 1))
                time.sleep(10 * (k + 1))

    def start(self, year: int, ap: str):
        time.sleep(PAUSE)
        r = self._check(self._get(f"{BASE}Navegar.aspx?y={year}&ap={ap}"))
        soup = BeautifulSoup(r.text, "html.parser")
        shown = soup.find("select", {"name": "ctl00$CPH1$DrpYear"}).select_one("option[selected]")
        if shown is None or shown.get("value") != str(year):
            raise RuntimeError(f"la página no muestra el año {year}")
        return soup, r.url

    def click(self, soup, url, label: str, row: dict | None = None):
        btn = soup.find("input", {"type": "submit", "value": label})
        if btn is None:
            disp = [b.get("value") for b in soup.select("input[type=submit]")]
            raise RuntimeError(f"no está el botón «{label}» (hay: {disp})")
        data = {i.get("name"): i.get("value", "") for i in soup.select("input[type=hidden]")}
        for sel in soup.select("select"):
            opt = sel.select_one("option[selected]") or sel.select_one("option")
            data[sel.get("name")] = opt.get("value") if opt else ""
        data[btn.get("name")] = btn.get("value")
        if row:
            data[row["radio_name"]] = row["radio_value"]
        time.sleep(PAUSE)
        r = self._check(self._post(url, data))
        return BeautifulSoup(r.text, "html.parser"), r.url

    def navigate(self, year: int, ap: str, steps: list[tuple[str, str | None]]) -> list[dict]:
        """steps: [(botón, código de fila a elegir para el paso siguiente o None)]."""
        soup, url = self.start(year, ap)
        row = None
        rows: list[dict] = []
        for label, code in steps:
            soup, url = self.click(soup, url, label, row)
            rows = parse_table(soup)
            row = None
            if code is not None:
                row = next((r for r in rows if r["codigo"] == code), None)
                if row is None:
                    raise RuntimeError(f"no está la fila {code} tras «{label}»")
        return rows


def parse_table(soup) -> list[dict]:
    out = []
    for tr in soup.select("tr"):
        radio = tr.select_one("input[type=radio]")
        tds = tr.find_all("td")
        if radio is None or len(tds) < 10:
            continue
        cells = [td.get_text(" ", strip=True) for td in tds]
        label = cells[1]
        code, _, name = label.partition(":")
        rec = {"codigo": code.strip(), "nombre": name.strip().lstrip("'").strip(),
               "radio_name": radio.get("name"), "radio_value": radio.get("value")}
        for col, v in zip(COLS[2:], cells[2:10]):
            rec[col] = v
        out.append(rec)
    return out


MIN_ROWS = {"nivel": 3, "departamento": 25, "sector": 15, "mes": 1}


def validate(name: str, rows: list[dict]) -> None:
    """Antes de guardar: filas mínimas por vista y avance coherente con devengado / PIM (si el sitio cambia de
    columnas, los números se correrían en silencio)."""
    kind = next((k for k in MIN_ROWS if name.endswith(k)), None)
    if kind and len(rows) < MIN_ROWS[kind]:
        raise ValueError(f"{name}: {len(rows)} filas (mínimo {MIN_ROWS[kind]})")
    for r in rows:
        try:
            pim = float(r["pim"].replace(",", "") or 0)
            dev = float(r["devengado"].replace(",", "") or 0)
            av = float(r["avance_pct"] or 0)
        except ValueError:
            raise ValueError(f"{name}: valores no numéricos en {r.get('nombre')}") from None
        if pim > 0 and abs(dev / pim * 100 - av) > 0.2:
            raise ValueError(f"{name}: avance {av} no cuadra con devengado/PIM en {r.get('nombre')}")


def save(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def views_for(year: int, tipo: str, current: int) -> list[tuple[str, list]]:
    v = [("nivel", [("Nivel de Gobierno", None)])]
    for lv in ["E", "M", "R"]:
        v.append((f"nivel_{lv}__mes", [("Nivel de Gobierno", lv), ("Mes", None)]))
    v += [("nivel_E__sector", [("Nivel de Gobierno", "E"), ("Sector", None)]),
          ("nivel_R__departamento", [("Nivel de Gobierno", "R"), ("Departamento", None)]),
          ("nivel_M__departamento", [("Nivel de Gobierno", "M"), ("Departamento", None)]),
          ("departamento", [("Departamento", None)])]
    return v


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--desde", type=int, default=2012)
    ap.add_argument("--refrescar", action="store_true", help="vuelve a bajar también los años cerrados")
    args = ap.parse_args()

    today = dt.date.today()
    current = today.year
    (CONTROL / "logs").mkdir(parents=True, exist_ok=True)
    logfile = CONTROL / "logs" / f"mef_ejecucion_{dt.datetime.now():%Y%m%d_%H%M%S}.log"
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S",
                        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(logfile, encoding="utf-8")])
    nav = Navigator()
    manifest = []
    # Años cerrados que se bajaron antes de terminar (p. ej., en marzo de ese año): hay que volver a bajarlos.
    man_path = CONTROL / "manifest_mef_ejecucion.csv"
    last_dl = {}
    if man_path.exists():
        with open(man_path, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                y = int(row["anio"])
                last_dl[y] = max(last_dl.get(y, ""), row["descargado_en"])
    try:
        for year in range(args.desde, current + 1):
            closed_early = year < current - 1 and last_dl.get(year, "9999") < f"{year + 1}-01-15"
            fresh = year >= current - 1 or args.refrescar or closed_early
            for tipo, apv in AP.items():
                for name, steps in views_for(year, tipo, current):
                    path = RAW / str(year) / f"{tipo}__{name}.csv"
                    if path.exists() and not fresh:
                        continue
                    try:
                        rows = nav.navigate(year, apv, steps)
                        validate(name, rows)
                    except (RuntimeError, ValueError) as e:   # el año aún no existe en el sitio, falta un botón, etc.
                        log.error("%s %s %s: %s (se conserva lo anterior)", year, tipo, name, e)
                        continue
                    save(path, rows)
                    manifest.append({"anio": year, "tipo": tipo, "vista": name, "filas": len(rows),
                                     "descargado_en": dt.datetime.now().isoformat(timespec="seconds")})
                    log.info("%s %-9s %-24s %3d filas", year, tipo, name, len(rows))
            # Cada gobierno regional por mes (solo inversión), año en curso y anterior.
            if year >= current - 1:
                deps = [r["codigo"] for r in nav.navigate(year, AP["proyectos"], [("Nivel de Gobierno", "R"), ("Departamento", None)])]
                for code in deps:
                    path = RAW / str(year) / f"proyectos__nivel_R__dep_{code}__mes.csv"
                    try:
                        rows = nav.navigate(year, AP["proyectos"], [("Nivel de Gobierno", "R"), ("Departamento", code), ("Mes", None)])
                        validate("mes", rows)
                    except (RuntimeError, ValueError) as e:
                        log.error("%s gobierno regional %s por mes: %s", year, code, e)
                        continue
                    save(path, rows)
                    manifest.append({"anio": year, "tipo": "proyectos", "vista": f"nivel_R__dep_{code}__mes",
                                     "filas": len(rows), "descargado_en": dt.datetime.now().isoformat(timespec="seconds")})
                log.info("%s proyectos  gobiernos regionales por mes: %d", year, len(deps))
    except Blocked as e:
        log.error("El sitio bloqueó o desafió la consulta; se detiene sin reintentar: %s", e)
        return 2
    finally:
        mpath = CONTROL / "manifest_mef_ejecucion.csv"
        new = not mpath.exists()
        with open(mpath, "a", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["anio", "tipo", "vista", "filas", "descargado_en"])
            if new:
                w.writeheader()
            w.writerows(manifest)
        log.info("peticiones: %d; vistas guardadas: %d", nav.n_requests, len(manifest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
