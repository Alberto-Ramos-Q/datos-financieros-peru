"""Lector de los balances de las entidades estatales (tema `estatales-estados-financieros`, p=12).

Códigos: B-5102 (Banco de la Nación), B-5103 (COFIDE), B-5104 (Agrobanco), B-5105 (Fondo
MiVivienda). Subsistema `entidades-estatales` (agregado el 2026-11-03): NO entra en los totales
de los 5 subsistemas ni en `panel_entidad_mes` (ver la sección del README).

El formato es el del Balance General y EGP de la banca (B-2201): cabecera «Activo | <entidad>»,
fila «MN | ME | TOTAL», rubros en MAYÚSCULAS. Una sola entidad por libro, rotulada «Nación»,
«Agrobanco», etc. (alias del maestro restringidos al subsistema). Por eso se reutiliza
`estados_financieros.leer` con estas variantes de etiqueta, propias de los cuadros estatales:
- «CRÉDITOS NETOS DE PROVISIONES» (banca: «… y de ingresos no devengados»);
- «Depósitos del Sistema Financiero y Org. Internacionales» (también «Org,») en intereses por pagar;
- hasta 2012: «Líneas de Crédito no Utilizadas y Créditos Concedidos no Utilizados»,
  «Intereses por Obligaciones en Circulación no Subordinados» y la errata «Pérdoda».
Las variables quedan con los mismos nombres que en la banca, para que las fórmulas del ranking
(créditos = vigentes + refinanciados + atrasados; depósitos = obligaciones con el público −
otras obligaciones + depósitos del sistema financiero) valgan igual.
"""
from __future__ import annotations

from pathlib import Path

from lector import comun
from lector import estados_financieros as ef

EXTRA_SECCIONES = {
    "creditos netos de provisiones": "creditos_netos",
}
EXTRA_SUBRUBROS = {
    "intereses_por_pagar": {
        "depositos del sistema financiero y org internacionales":
            "intereses_por_pagar_depositos_sistema_financiero",
    },
    "contingentes": {
        "lineas de credito no utilizadas y creditos concedidos no utilizados": "contingentes_lineas_no_utilizadas",
    },
    "gastos_financieros": {
        "intereses por obligaciones en circulacion no subordinados":
            "gastos_financieros_obligaciones_circulacion_no_subordinadas",
    },
    "provisiones_depreciacion_amortizacion": {
        "provisiones por perdoda por deterioro de inversiones":
            "provisiones_depreciacion_amortizacion_deterioro_inversiones",
    },
}

# Fondo MiVivienda (B-5105): sus préstamos a las IFI se registran como cuentas por cobrar, así que su
# EGP abre ingresos y gastos financieros de cuentas por cobrar/pagar (sin equivalente en la banca).
# Hasta 2012 trae además inversiones «negociables para intermediación financiera» y «permanentes», y
# créditos indirectos dentro de contingentes. Variables nuevas, solo de este tema.
EXTRA_SUBRUBROS["ingresos_financieros"] = {
    "cuentas por cobrar": "ingresos_financieros_cuentas_por_cobrar",              # 2013 →
    "ingresos de cuentas por cobrar": "ingresos_financieros_cuentas_por_cobrar",  # → 2012
}
EXTRA_SUBRUBROS["gastos_financieros"].update({
    "cuentas por pagar": "gastos_financieros_cuentas_por_pagar",                  # 2013 →
    "intereses comisiones y otros gastos de cuentas por pagar": "gastos_financieros_cuentas_por_pagar",  # → 2012
})
EXTRA_SUBRUBROS["inversiones_netas"] = {
    "negociables para intermediacion financiera": "inversiones_negociables_intermediacion_financiera",
    "permanentes": "inversiones_permanentes",
}
EXTRA_SUBRUBROS["contingentes"]["creditos indirectos"] = "contingentes_creditos_indirectos"

# Filas que NO son datos y se descartan (verificado el 2026-11-03 en los Excel):
# - COFIDE 2013-04, hoja «BG COF» fila 59: «Tipo de Cambio Contable: S/. 2.646» trae una suma de control
#   igual al TOTAL ACTIVO (7 254 998,121 frente a 7 254 998,127).
# - COFIDE 2013-03, fila 136: la nota «1/ Incluye gastos devengados por pagar.» con un 0 suelto.
DESCARTAR = "_descartar"
EXTRA_SUBRUBROS["total_activo"] = {"tipo de cambio contable s 2 646": DESCARTAR}
EXTRA_SUBRUBROS["contingentes"]["1 incluye gastos devengados por pagar"] = DESCARTAR


# Cada libro es de UNA entidad, la del código. Rótulos de otra entidad = errata de la SBS; solo se aceptan las
# verificadas (2026-11-03): Agrobanco 2013-01 y 2013-02, hoja «EGP AGROB», rotulada «Nación» (copia del BN;
# las cifras son de Agrobanco: resultado neto 2 569,6 y 4 771,3 frente a 78 120,7 y 117 720,1 del BN).
ENTIDAD_CODIGO = {"B-5102": ("banco-de-la-nacion", "Banco de la Nación"), "B-5103": ("cofide", "COFIDE"),
                  "B-5104": ("agrobanco", "Agrobanco"), "B-5105": ("fondo-mivivienda", "Fondo MiVivienda")}
ERRATAS_ROTULO = {("B-5104", 201301), ("B-5104", 201302)}


def leer(ruta: Path, subsistema: str, periodo: int) -> list[dict]:
    filas = ef.leer(ruta, subsistema, periodo, extra=(EXTRA_SECCIONES, EXTRA_SUBRUBROS))
    filas = [r for r in filas if r and r["variable"] != DESCARTAR]
    codigo = ruta.stem.rsplit("-", 1)[0].upper()
    esperado, nombre = ENTIDAD_CODIGO[codigo]
    for r in filas:
        ident = comun.resolver_entidad(r["entidad_original"], subsistema, periodo)[0]
        if ident != esperado:
            if (codigo, periodo) not in ERRATAS_ROTULO:
                raise ValueError(f"{r['hoja']}: rótulo «{r['entidad_original']}» ({ident}) en un libro de {esperado}")
            r["entidad_original"] = nombre
    return filas
