"""Descargador de las tasas activas por tipo de crédito y empresa (SBS), siempre en moneda nacional.

Página: TIActivaTipoCreditoEmpresa.aspx?tip=B|F|C|R|E (protegida por Imperva → navegador
headless con Playwright). Qué se descarga por subsistema (`config/tasas.csv`):
- B (banca) y F (financieras), formulario diario: la tasa del último día útil de cada mes
  cerrado (lunes a viernes que no sea feriado nacional del Perú).
- C (cajas municipales), R (cajas rurales) y E (empresas de créditos), formulario mensual:
  cada mes hasta el último disponible.

Cada Excel se guarda como `data/raw/tasas-activas/<subsistema>/<tip>_TIActivaTipoCreditoEmpresaMN-AAAAMM.xlsx`
(el nombre lleva el mes de los datos, no la fecha de descarga) y se registra en el mismo
`data/_control/manifest.csv` del boletín. Si al revisar un mes ya descargado el contenido
cambió, la versión anterior va a `data/_control/historial/`.

Uso:
    python descargar_tasas.py                    # completa los meses faltantes y revisa el último
    python descargar_tasas.py --tip E --desde 201501
    python descargar_tasas.py --revisar-meses 3  # vuelve a bajar los 3 últimos meses y compara
    python descargar_tasas.py --dry-run
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import re
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import holidays
import openpyxl
from playwright.sync_api import Page, sync_playwright

from descargar_boletin import (DEFAULT_CONTROL, EXCEL_MAGIC, PROJECT_DIR, USER_AGENT, append_manifest,
                               iter_periods, log, prevent_sleep, setup_logging, sha256_of)

TASAS_CSV = PROJECT_DIR / "config" / "tasas.csv"
DEST = PROJECT_DIR / "data" / "raw" / "tasas-activas"
URL = "https://www.sbs.gob.pe/app/pp/EstadisticasSAEEPortal/Paginas/TIActivaTipoCreditoEmpresa.aspx?tip={tip}"
MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto",
         "Setiembre", "Octubre", "Noviembre", "Diciembre"]
SEL = "#ctl00_cphContent_"
TIMEOUT_MS = 90_000


@dataclass
class Tasa:
    tip: str
    subsistema: str
    formulario: str  # "diario" | "mensual"
    desde: int

    def archivo(self, periodo: int) -> Path:
        return DEST / self.subsistema / f"{self.tip}_TIActivaTipoCreditoEmpresaMN-{periodo}.xlsx"


def load_tasas() -> list[Tasa]:
    with open(TASAS_CSV, encoding="utf-8") as fh:
        return [Tasa(r["tip"], r["subsistema"], r["formulario"], int(r["desde"]))
                for r in csv.DictReader(fh) if r["activo"].strip() == "1"]


def dias_utiles_desc(periodo: int):
    """Días del mes del último hacia atrás, sin fines de semana ni feriados nacionales."""
    y, m = divmod(periodo, 100)
    feriados = holidays.Peru(years=y)
    d = dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)
    while d.month == m:
        if d.weekday() < 5 and d not in feriados:
            yield d
        d -= dt.timedelta(days=1)


def ultimo_mes_cerrado(hoy: dt.date) -> int:
    return hoy.year * 100 + hoy.month - 1 if hoy.month > 1 else (hoy.year - 1) * 100 + 12


def abrir_pagina(page: Page, tip: str, selector: str) -> None:
    page.goto(URL.format(tip=tip), wait_until="domcontentloaded", timeout=TIMEOUT_MS)
    page.wait_for_selector(selector, timeout=TIMEOUT_MS)
    time.sleep(1.5)


def consultar_dia(page: Page, fecha: dt.date) -> bool:
    """Consulta un día en el formulario diario; False si la SBS no tiene datos de esa fecha."""
    texto = f"{fecha:%d/%m/%Y}"
    entrada = page.locator(f"{SEL}rdpDate_dateInput")
    entrada.click()
    entrada.fill("")
    entrada.type(texto, delay=40)
    entrada.press("Tab")
    time.sleep(1)
    page.click(f"{SEL}btnConsultar")
    try:
        page.wait_for_function(
            "f => (document.querySelector('#ctl00_cphContent_lblMensajeFecha')||{}).innerText?.includes(f)",
            arg=texto, timeout=TIMEOUT_MS)
    except Exception:
        return False
    time.sleep(1.5)
    # Algunas fechas (p. ej. 30/06/2017) responden sin tabla ni campo de moneda: sin datos.
    if page.locator(f"{SEL}hdTipoMoneda").count() == 0:
        return False
    return page.input_value(f"{SEL}hdTipoMoneda") == "MN"


def mes_mostrado(page: Page) -> int | None:
    """Mes de los datos según la etiqueta («… por tipo de Crédito a Agosto del 2026»)."""
    m = re.search(r"a (\w+) del (\d{4})", page.inner_text(f"{SEL}lblMensajeFecha"))
    nombre = m.group(1).capitalize().replace("Septiembre", "Setiembre") if m else ""
    return int(m.group(2)) * 100 + MESES.index(nombre) + 1 if nombre in MESES else None


def consultar_mes(page: Page, periodo: int) -> bool:
    y, m = divmod(periodo, 100)
    page.evaluate("([a, m]) => { $find('ctl00_cphContent_rAnio').findItemByText(a).select();"
                  " $find('ctl00_cphContent_rMes').findItemByText(m).select(); }", [str(y), MESES[m - 1]])
    time.sleep(1)
    page.click(f"{SEL}btnConsultaMensual")
    page.wait_for_load_state("domcontentloaded")
    try:
        page.wait_for_function(
            "t => (document.querySelector('#ctl00_cphContent_lblMensajeFecha')||{}).innerText?.includes(t)",
            arg=f"{MESES[m - 1]} del {y}", timeout=TIMEOUT_MS)
    except Exception:
        return False
    time.sleep(1.5)
    # Algunas fechas (p. ej. 30/06/2017) responden sin tabla ni campo de moneda: sin datos.
    if page.locator(f"{SEL}hdTipoMoneda").count() == 0:
        return False
    return page.input_value(f"{SEL}hdTipoMoneda") == "MN"


def exportar(page: Page, boton: str, tmp: Path) -> Path:
    with page.expect_download(timeout=TIMEOUT_MS) as info:
        page.click(f"{SEL}{boton}")
    destino = tmp / info.value.suggested_filename
    info.value.save_as(destino)
    with open(destino, "rb") as fh:
        if not fh.read(8).startswith(EXCEL_MAGIC):
            raise ValueError(f"la descarga no es un Excel: {destino.name}")
    return destino


def huella(path: Path) -> str:
    """Hash de los valores de las celdas.

    El Excel se genera al vuelo y cambia de bytes en cada descarga (metadatos de creación)
    aunque los datos sean iguales: el sha256 del archivo no sirve para detectar cambios.
    """
    libro = openpyxl.load_workbook(path, read_only=True, data_only=True)
    h = hashlib.sha256()
    for hoja in libro.worksheets:
        h.update(hoja.title.encode())
        for fila in hoja.iter_rows(values_only=True):
            h.update(repr(fila).encode())
    libro.close()
    return h.hexdigest()


def guardar(tasa: Tasa, periodo: int, descargado: Path, consulta: str, control: Path) -> str:
    """Mueve la descarga a raw/; si ya existía con otros datos, archiva la anterior."""
    final = tasa.archivo(periodo)
    final.parent.mkdir(parents=True, exist_ok=True)
    nuevo_hash = sha256_of(descargado)
    accion = "nuevo"
    if final.exists():
        if huella(final) == huella(descargado):
            descargado.unlink()
            return "sin_cambios"
        hist = control / "historial" / "tasas-activas" / tasa.subsistema
        hist.mkdir(parents=True, exist_ok=True)
        fecha = dt.date.fromtimestamp(final.stat().st_mtime)
        shutil.move(str(final), hist / f"{final.stem}__{fecha:%Y%m%d}{final.suffix}")
        accion = "republicado"
    shutil.move(str(descargado), final)
    append_manifest(control / "manifest.csv", {
        "carpeta": f"tasas-activas/{tasa.subsistema}", "archivo": final.name, "periodo": periodo,
        "url": URL.format(tip=tasa.tip), "server_fecha": consulta, "server_bytes": final.stat().st_size,
        "sha256": nuevo_hash, "descargado_en": dt.datetime.now().isoformat(timespec="seconds"),
        "accion": accion})
    log.info("%s: %s (%s)", accion.upper(), final.relative_to(DEST.parent), consulta)
    return accion


def descargar_diario(page: Page, tasa: Tasa, periodo: int, control: Path) -> str:
    for intento, fecha in enumerate(dias_utiles_desc(periodo)):
        if intento == 3:
            break
        # Tras exportar o consultar, el formulario queda a medio postback: se recarga cada vez.
        abrir_pagina(page, tasa.tip, f"{SEL}btnExportar")
        if consultar_dia(page, fecha):
            return guardar(tasa, periodo, exportar(page, "btnExportar", control / "tmp"),
                           f"{fecha:%d/%m/%Y}", control)
        log.warning("%s %s: sin datos el %s; pruebo el día útil anterior", tasa.tip, periodo, fecha)
    return "no_disponible"


def descargar_mensual(page: Page, tasa: Tasa, periodo: int, control: Path) -> str:
    abrir_pagina(page, tasa.tip, f"{SEL}btnExportarM")
    if not consultar_mes(page, periodo):
        return "no_disponible"
    return guardar(tasa, periodo, exportar(page, "btnExportarM", control / "tmp"),
                   f"{MESES[periodo % 100 - 1]} {periodo // 100}", control)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Descarga las tasas activas (MN) de la SBS.")
    p.add_argument("--tip", action="append", help="B, F, C, R o E. Repetible.")
    p.add_argument("--desde", type=int, help="AAAAMM (ignora el de config/tasas.csv).")
    p.add_argument("--hasta", type=int, help="AAAAMM (por defecto, el último mes cerrado o disponible).")
    p.add_argument("--revisar-meses", type=int, default=1,
                   help="Vuelve a descargar los últimos N meses ya guardados y compara (0 = no).")
    p.add_argument("--pausa", type=float, default=2.0, help="Segundos entre consultas.")
    p.add_argument("--dry-run", action="store_true", help="Solo informa los meses que bajaría.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    control = DEFAULT_CONTROL
    log_file = setup_logging(control)
    prevent_sleep()
    (control / "tmp").mkdir(parents=True, exist_ok=True)
    tasas = [t for t in load_tasas() if not args.tip or t.tip in args.tip]
    totales: dict[str, int] = {}
    errores = 0
    with sync_playwright() as pw:
        navegador = pw.chromium.launch(headless=True)
        contexto = navegador.new_context(user_agent=USER_AGENT, locale="es-PE", accept_downloads=True)
        for tasa in tasas:
            page = contexto.new_page()
            mensual = tasa.formulario == "mensual"
            boton = "btnExportarM" if mensual else "btnExportar"
            try:
                abrir_pagina(page, tasa.tip, f"{SEL}{boton}")
                # Formulario mensual: la página abre en el último mes disponible.
                ultimo = mes_mostrado(page) if mensual else ultimo_mes_cerrado(dt.date.today())
            except Exception as exc:
                log.error("FALLA %s: no abre la página (%s)", tasa.tip, exc)
                errores += 1
                page.close()
                continue
            hasta = min(args.hasta or ultimo, ultimo)
            periodos = list(iter_periods(args.desde or tasa.desde, hasta))
            revisar = set(periodos[-args.revisar_meses:]) if args.revisar_meses else set()
            pendientes = [p for p in periodos if p in revisar or not tasa.archivo(p).exists()]
            log.info("%s (%s): último %s, %d meses por consultar", tasa.tip, tasa.subsistema, ultimo,
                     len(pendientes))
            for periodo in pendientes:
                if args.dry_run:
                    log.info("DRY-RUN %s %s", tasa.tip, periodo)
                    continue
                accion = "error"
                for intento in range(1, 4):
                    try:
                        accion = (descargar_mensual if mensual else descargar_diario)(page, tasa, periodo, control)
                        break
                    except Exception as exc:  # la página quedó en mal estado: se recarga
                        log.warning("%s %s: intento %d falló (%s)", tasa.tip, periodo, intento, exc)
                        time.sleep(10 * intento)
                        try:
                            abrir_pagina(page, tasa.tip, f"{SEL}{boton}")
                        except Exception:
                            pass
                if accion == "error":
                    log.error("FALLA %s %s", tasa.tip, periodo)
                    errores += 1
                totales[accion] = totales.get(accion, 0) + 1
                time.sleep(args.pausa)
            page.close()
        navegador.close()
    log.info("Resumen tasas: %s", ", ".join(f"{k}={v}" for k, v in sorted(totales.items())) or "nada que hacer")
    log.info("Log: %s", log_file)
    return 1 if errores else 0


if __name__ == "__main__":
    sys.exit(main())
