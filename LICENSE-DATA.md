# Licencia de los datos

Las tablas de [`datos/`](datos/), las publicadas en Releases y los datos incluidos en los tableros se
distribuyen bajo **Creative Commons Atribución 4.0 Internacional (CC BY 4.0)**:
https://creativecommons.org/licenses/by/4.0/deed.es

Puedes copiarlos, redistribuirlos, transformarlos y usarlos para cualquier fin, incluso comercial,
siempre que des el crédito correspondiente.

## Cómo citar

> Fuente: Superintendencia de Banca, Seguros y AFP (SBS) — Boletín Estadístico del Sistema Financiero.
> Procesado por Elisban Alberto Ramos Quispe, *Datos financieros del Perú*,
> https://github.com/Alberto-Ramos-Q/datos-financieros-peru

Para las demás fuentes, cambia la primera línea por la que corresponda:

- BCRP: «Fuente: Banco Central de Reserva del Perú (BCRP) — BCRPData».
- INEI: «Fuente: Instituto Nacional de Estadística e Informática (INEI) — Encuesta Nacional de Hogares (ENAHO)».
- MEF: «Fuente: Ministerio de Economía y Finanzas (MEF) — Consulta Amigable, Marco Macroeconómico Multianual o
  indicadores de deuda pública», según el dato.
- Consejo Fiscal: «Fuente: Consejo Fiscal del Perú».
- FMI: «Fuente: Fondo Monetario Internacional (FMI)».
- Comparación internacional: «Fuente: Comisión para el Mercado Financiero (Chile), Superintendencia Financiera de
  Colombia y Banco Central do Brasil».
- Series de otros países (`data_macro_paises/`): la institución oficial de cada serie, indicada en
  `data/processed/macro_series.csv` y en `data_macro_paises/docs/fuentes/`.

## Excepción: geometría del mapa

Los límites departamentales de `descargas-sbs/config/geo/` (`peru_departamental_simple.geojson` y su derivado
`departamentos_svg.json`, que también va dentro de los tableros de crédito por departamento, finanzas públicas y
pobreza por departamento) **no** están bajo
CC BY 4.0. Provienen del repositorio [juaneladio/peru-geojson](https://github.com/juaneladio/peru-geojson)
(límites del INEI, 2007) y se distribuyen bajo la **Mozilla Public License 2.0**:
https://www.mozilla.org/en-US/MPL/2.0/ (detalle en `descargas-sbs/config/geo/README.md`).

## Excepción: datos del FMI

Los datos del Fondo Monetario Internacional que aparecen en el tablero de finanzas públicas (World Economic Outlook y
Fiscal Monitor, usados para comparar al Perú con otros países) **no** están bajo CC BY 4.0. Se rigen por los términos
de datos del FMI (https://www.imf.org/en/about/copyright-and-terms). Esos términos permiten redistribuirlos y crear
derivados citando la fuente y sin alterar los datos, y piden permiso del FMI (copyright@imf.org) para cualquier uso
comercial. Cita: «Source: International Monetary Fund, World Economic Outlook Database / Fiscal Monitor,
https://www.imf.org/external/datamapper/». La mediana regional que muestra el tablero es cálculo propio.

## Alcance

La licencia cubre el trabajo de recopilación, limpieza y estructuración. Los datos originales son
información pública de la SBS, el BCRP, el INEI, el MEF, el Consejo Fiscal, el FMI, los supervisores de Chile,
Colombia y Brasil, y los bancos centrales, institutos de estadística y ministerios de los 13 países de
`data_macro_paises/`, y se rigen por las condiciones de esas instituciones. En particular, los microdatos de la ENAHO
se rigen por las condiciones de uso del INEI y los datos del FMI, por sus propios términos (ver la excepción de arriba). Este repositorio no
redistribuye los microdatos de la ENAHO: solo el código que los descarga y las estimaciones que salen de ellos.
Este repositorio no es una publicación oficial: ante cualquier diferencia, vale la cifra de la fuente.
