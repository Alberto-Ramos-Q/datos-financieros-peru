# Paraguay (PRY) — fuentes oficiales

Descargador: `src/paises/pry.py` · Series: `config/series/PRY.csv` (36 series: 26 de los 28
indicadores comunes + 10 adicionales, 3 de ellas para la capa comparable) · Salida: `data/interim/PRY_observaciones.parquet`.

## Instituciones y accesos

| Fuente | Institución | Qué se usa | Acceso | Formato |
|---|---|---|---|---|
| `BCP` | Banco Central del Paraguay — `https://www.bcp.gov.py/web/institucional/<página>` | IPC, IMAEP, cuentas nacionales, TPM/TIB, tasas, crédito, agregados, tipo de cambio, reservas, comercio exterior, balanza de pagos, remesas, salario mínimo | Público, sin clave. Página de cada cuadro → enlace al Excel (`/documents/20117/<id>/<archivo>.xlsx/<uuid>?t=…`) | `.xlsx` irregulares (títulos, notas, celdas combinadas) |
| `BCP` | Cotización referencial histórica — `https://www.bcp.gov.py/webapps/web/cotizacion/monedas-historica` | Tipo de cambio diario USD | POST `anho=<año>&moneda=USD` a `…/monedas-historica/xls` | Tabla HTML (día × mes), una por año 2001-2026 |
| `INE` | Instituto Nacional de Estadística (ex DGEEC) — `https://www.ine.gov.py/publicacion/3/empleo` | Desempleo (EPHC trimestral) | Público | `.xlsx` |
| `MEF` | Ministerio de Economía y Finanzas — `https://www.mef.gov.py/es/situfin` y `…/viceministerio-de-economia-y-planificacion/deuda-publica` | Resultado fiscal (% PIB) y deuda pública (% PIB) | Público | `.xlsx` |

Páginas del BCP usadas (sufijo de `…/web/institucional/`): `indice-precios-al-consumidor-ipc`,
`indicador-mensual-de-actividad-economica-del-paraguay-imaep-`, `cuentas-nacionales-trimestrales-cnt-`,
`serie-historica-del-pib-base-2014`, `instrumentos-de-regulaci%C3%B3n-monetaria`,
`anexo-estadistico-indicadores-financieros`, `creditos-y-depositos`, `agregados-monetarios`,
`tipo-de-cambio-nominal-tcn-`, `tipo-de-cambio-real`, `reservas-internacionales`,
`comercio-externo-comex-mensual`, `balanza-de-pagos-y-posicion-de-inversion-internacional`,
`remesas-familiares`, `%C3%ADndice-de-sueldos-y-salarios-iss-`, `meta-de-inflacion`.

Ninguna serie requiere clave ni registro.

## Trampas encontradas

- **Cloudflare en www.bcp.gov.py.** `requests` (y por lo tanto `comun.Client`) recibe siempre
  403 "Just a moment…" por la huella TLS, aunque el User-Agent sea de navegador. `curl` pasa, con
  desafíos intermitentes. El módulo usa `CurlClient` (subprocess de `curl`, secuencial, pausa ≥ 1 s,
  hasta 6 reintentos y cookie de sesión en un temporal) **solo para ese host**; INE y MEF usan
  `comun.Client`. `comun.py` no ofrece esta vía: queda resuelto dentro del módulo.
- **Enlaces que cambian.** Los archivos del BCP llevan fecha y UUID en la URL (`Tipo de cambio
  nominal 01-10-2026.xlsx/af73…`). Se entra a la página del cuadro y se busca el enlace por el
  nombre del archivo; en `data/raw/PRY/` se guarda con un nombre estable (`bcp_tipo_cambio_nominal.xlsx`).
  La URL real queda en `data/_control/manifest_PRY.csv`.
- **TPM.xlsx desactualizado.** El archivo de la página "Tasa de Política Monetaria" termina en
  2025-12. La TPM vigente (5,50 % desde feb-2026) se toma del "Resumen Histórico Mensual LRM",
  que trae la TPM y la tasa interbancaria hasta el mes anterior.
- **Comercio exterior (cuadro 43):** los meses futuros del año en curso vienen en **0**; se
  descartan las filas con exportaciones e importaciones totales = 0. Los valores están en **miles**
  de USD (se dividen por 1000). El cuadro 49 (precios internacionales) incluye cotizaciones
  futuras hasta 2028: **no se usa**.
- **IPC desde 1950:** años en filas; 1950-1963 solo promedio anual; desde 1964 cada año va
  seguido de sus meses (`ENE`…`SEPT`). Se toman solo los meses.
- **Fechas mezcladas** en un mismo cuadro: `datetime`, `'may-26 *'`, `'SET-11'`, `'2026*'`,
  `'2025 1/'`, `'1er Trimestre(*)'`. Se parsean por texto, no por posición.
- **Reservas (cuadro 56a):** cada mes está fechado con el día del último dato (`2026-09-25`);
  se normaliza al mes. Hay filas anuales (1990-1993) que se omiten.
- **Balanza de pagos:** el encabezado de año `2014*` aparece desplazado al 3.er trimestre; el año
  se arrastra hacia la derecha y se ignoran las columnas `Total`.
- **Deuda pública (MEF):** el encabezado mezcla años (2004-2019 y 2020-2022 en la posición de
  diciembre), fechas y textos `dic-23*`. Se toman solo los cierres de año. Ojo: el MEF divide el
  saldo en USD por el PIB en USD del año (2025: 49.717 millones; 2026: 63.814), así que la ratio
  cae de 41,1 % (dic-2025) a 32,2 % (ene-2026) sin que cambie la deuda; la serie anual no se ve
  afectada porque solo usa cierres de año.
- **Salario mínimo:** el cuadro trae el promedio anual y los subperiodos de vigencia
  (`Enero/Junio`, `Julio/Diciembre`, `Julio/Septiembre`); se expande a meses con el valor vigente.
- **Marcadores sin dato** (`s/d`, `-`, `ND`): no se imputan, se descartan y quedan en el log
  (p. ej. TIB 2015-01 = `s/d`).
- **Capa comparable (2026-10-21).** Las tres series nuevas salen de archivos que ya se descargaban:
  - `m3_amplio`: columna `M3` ("e = c + d") de `Agregados Monetarios.xlsx`. Empieza en **1989-03**,
    aunque M2 empieza en 1962: antes no hay depósitos en moneda extranjera en el cuadro. Identidad
    M3 = M2 + depósitos en ME verificada (diferencia < 1e-7 en todos los meses).
  - `deuda_publica_usd`: la misma fila "Deuda Sector Público Total" de la hoja `1. Saldo` que usa
    `deuda_publica_pct_pbi`, pero el valor en millones de USD (el cuadro dice "(En millones de USD)";
    el parser lo verifica). Mismos cierres de año. deuda_usd / (% PIB) reproduce el PIB en USD del
    MEF (2025: 49.717 millones).
  - `inflacion_sae_12m`: **anexo del IPC, CUADRO 5**, columna "IPC sin Alim, Comb, Serv. Tarif" →
    "Variación%" → "Inter.". Es exactamente la medida pedida (sin alimentos, combustibles ni
    tarifados). El encabezado tiene dos filas con celdas combinadas y las variaciones a la derecha
    del índice; el parser (`p_anexo_ipc_var`) verifica que la columna no pase al bloque siguiente
    ("IPCSAE"). La variación publicada = la calculada desde el índice del mismo cuadro (diferencia 0
    en 369 meses). Jul y ago-2026 dan el mismo valor (1,278 %) porque el índice, publicado con un
    decimal, no varió en ninguno de los dos años (134,7); no es un error de carga. El cuadro trae
    también el "IPCSAE" (definición no documentada en el archivo), que no se cargó.

## Cobertura obtenida (descarga del 2026-10-21)

| nombre_corto | indicador_comun | fuente | frecuencia | desde | hasta | n |
|---|---|---|---|---|---|---|
| pbi_real_trim | pbi_real_trim | BCP | trimestral | 1994-01 | 2026-04 | 130 |
| pbi_real_var12m_trim | pbi_real_var12m_trim | BCP | trimestral | 1995-01 | 2026-04 | 126 |
| actividad_mensual_indice | actividad_mensual_indice | BCP | mensual | 1994-01 | 2026-08 | 392 |
| actividad_mensual_var12m | actividad_mensual_var12m | BCP | mensual | 1995-01 | 2026-08 | 380 |
| pbi_nominal_anual | pbi_nominal_anual | BCP | anual | 1950 | 2024 | 75 |
| ipc_indice | ipc_indice | BCP | mensual | 1964-01 | 2026-09 | 753 |
| inflacion_mensual | inflacion_mensual | BCP | mensual | 1965-01 | 2026-09 | 741 |
| inflacion_12m | inflacion_12m | BCP | mensual | 1965-01 | 2026-09 | 741 |
| inflacion_subyacente_12m | inflacion_subyacente_12m | BCP | mensual | 1993-12 | 2026-09 | 394 |
| tasa_politica | tasa_politica | BCP | mensual | 2011-05 | 2026-09 | 185 |
| tasa_interbancaria | tasa_interbancaria | BCP | mensual | 2015-02 | 2026-09 | 140 |
| tasa_activa_promedio | tasa_activa_promedio | BCP | mensual | 2011-01 | 2026-08 | 188 |
| tasa_pasiva_promedio | tasa_pasiva_promedio | BCP | mensual | 2011-01 | 2026-08 | 188 |
| credito_privado | credito_privado | BCP | mensual | 1995-03 | 2026-08 | 372 |
| m2 | m2 | BCP | mensual | 1962-01 | 2026-09 | 777 |
| tc_usd_promedio | tc_usd_promedio | BCP | mensual | 1997-01 | 2026-09 | 357 |
| tc_usd_diario | tc_usd_diario | BCP | diaria | 2001-01-29 | 2026-10-21 | 6460 |
| reservas_internacionales | reservas_internacionales | BCP | mensual | 1994-01 | 2026-09 | 386 |
| exportaciones | exportaciones | BCP | mensual | 1994-01 | 2026-09 | 393 |
| importaciones | importaciones | BCP | mensual | 1994-01 | 2026-09 | 393 |
| balanza_comercial | balanza_comercial | BCP | mensual | 1994-01 | 2026-09 | 393 |
| cuenta_corriente | cuenta_corriente | BCP | trimestral | 2008-01 | 2026-04 | 74 |
| resultado_fiscal_pct_pbi | resultado_fiscal_pct_pbi | MEF | anual | 2003 | 2025 | 23 |
| deuda_publica_pct_pbi | deuda_publica_pct_pbi | MEF | anual | 2004 | 2025 | 22 |
| desempleo | desempleo | INE | trimestral | 2017-01 | 2026-04 | 38 |
| salario_minimo | salario_minimo | BCP | mensual | 1980-01 | 2026-09 | 556 |
| imaep_sin_agro_binacionales | — | BCP | mensual | 1994-01 | 2026-08 | 392 |
| inflacion_subyacente_x1_12m | — | BCP | mensual | 1993-12 | 2026-09 | 394 |
| meta_inflacion | — | BCP | mensual | 2011-01 | 2026-12 | 192 |
| dolarizacion_credito_privado | — | BCP | mensual | 1995-03 | 2026-08 | 372 |
| remesas_familiares | — | BCP | mensual | 2008-01 | 2026-05 | 221 |
| exportaciones_soja_grano | — | BCP | mensual | 1994-01 | 2026-09 | 393 |
| tcr_multilateral | — | BCP | mensual | 1995-01 | 2026-08 | 380 |
| m3_amplio | — | BCP | mensual | 1989-03 | 2026-09 | 451 |
| deuda_publica_usd | — | MEF | anual | 2004 | 2025 | 22 |
| inflacion_sae_12m | — | BCP | mensual | 1995-01 | 2026-09 | 381 |

Notas de cobertura y unidades:
- IPC: cobertura **Área Metropolitana de Asunción** (el IPC oficial del BCP), base dic-2017 = 100,
  serie empalmada por el BCP (sin saltos de base dentro del archivo).
- `actividad_mensual_var12m` está **calculada** desde el índice oficial del IMAEP (el Excel no trae
  la variación; solo el informe PDF).
- `desempleo` es **trimestral** (frecuencia oficial de la EPHC; no hay tasa mensual).
- `resultado_fiscal_pct_pbi`: Administración Central (préstamo neto/endeudamiento neto, MEFP 2001).
  `deuda_publica_pct_pbi`: deuda bruta del Sector Público Total.
- `reservas_internacionales`: RIN, saldo a fin de mes, incluye FLAR.
- `importaciones`: valoradas FOB.
- `m3_amplio`: M2 + depósitos en moneda extranjera valorados en guaraníes (millones de ₲). M3/M2 =
  1,67 en sep-2026; una devaluación lo infla.
- `deuda_publica_usd`: deuda bruta del Sector Público Total en millones de USD (misma cobertura que
  `deuda_publica_pct_pbi`). La deuda interna está convertida a USD por el MEF.
- `inflacion_sae_12m`: sin alimentos, combustibles ni servicios tarifados, Área Metropolitana de
  Asunción.

## Indicadores comunes no cubiertos

| indicador_comun | Motivo |
|---|---|
| `pbi_desest_trim` | El BCP no publica en Excel el PIB trimestral desestacionalizado (el archivo de CNT solo trae series originales). |
| `expectativa_inflacion_12m` | La Encuesta de Expectativas de Variables Económicas (EVE) existe desde 2006, pero se publica solo como PDF mensual (un informe por mes). No es razonable reconstruir la historia parseando cientos de PDF. |

## Validación (2026-10-21)

| Dato | Publicación oficial | Serie | Resultado |
|---|---|---|---|
| Inflación interanual sep-2026 | Informe de Inflación Sep-2026 (BCP): "La inflación interanual se ubicó en 1,7 % en septiembre"; índice 141,6 | `inflacion_12m` = 1,724; `ipc_indice` = 141,6 | ✔ |
| IPC mensual ago-2026 | Comunicado CPM sep-2026: "la variación mensual del IPC fue de 0 %" | `inflacion_mensual` 2026-08 = 0,0 | ✔ |
| TPM vigente | Comunicado CPM sep-2026: "mantener la TPM en 5,50 % anual" | `tasa_politica` 2026-09 = 5,50 | ✔ |
| Tipo de cambio 20/10/2026 | Planilla de cotizaciones BCP del martes 20/10/2026: USD 5.757,08 | `tc_usd_diario` = 5.757,08 | ✔ |
| M3 sep-2026 | `Agregados Monetarios.xlsx` del BCP (actualizado el 2026-10-21): M3 = 173.393.440 millones de ₲ (M2 = 103.719.413) | `m3_amplio` 2026-09 = 173.393.440 | ✔ |
| Deuda total dic-2025 | `Estadisticas_Deuda_Publica` del MEF, hoja 1. Saldo: 20.447,9 MUSD (41,1 % del PIB) | `deuda_publica_usd` 2025 = 20.447,9 | ✔ |
| Inflación SAE sep-2026 | Anexo del IPC (BCP), cuadro 5: índice 134,7, variación interanual 1,51 % | `inflacion_sae_12m` 2026-09 = 1,507 | ✔ |

Controles internos:
- Inflación 12m y mensual calculadas desde el índice = publicadas (diferencia máx. 0,000 en 741 meses).
- `pbi_real_var12m_trim` = variación calculada desde `pbi_real_trim` (diferencia 0).
- Promedio mensual de `tc_usd_diario` vs `tc_usd_promedio`: diferencia < 0,35 % desde 2010
  (el mensual promedia compra y venta).
- Mayores saltos mensuales del IPC: 1974 (shock petrolero) y 1985 (devaluación); no hay saltos por
  cambio de base.
- `m3_amplio` ≥ `m2` en los 451 meses (cociente mínimo 1,01, en 1989).
- `inflacion_sae_12m` (1,51 % en sep-2026) queda por debajo de la subyacente (1,95 %) y de la total
  (1,72 %), coherente con que excluye además los alimentos.

## Pendientes

- Expectativas de inflación (EVE): solo PDF; evaluar extraer la tabla "Resultados del presente mes"
  de los informes más recientes si se necesita.
- PIB desestacionalizado: consultar si el BCP lo publica en el boletín de CNT (PDF).
- `pbi_nominal_anual` llega a 2024 (actualización anual del BCP en diciembre).
- Si el BCP endurece Cloudflare y `curl` deja de pasar, la descarga del BCP fallará con
  "desafío Cloudflare" en el log: no hay vía oficial alternativa sin navegador.

## Cómo actualizar

```
python src/paises/pry.py                    # descarga (≈ 2 min) y procesa todo
python src/paises/pry.py --solo-procesar    # reprocesa data/raw/PRY sin red
python src/paises/pry.py --serie tasa_politica ipc_indice   # descarga solo esos archivos
```
