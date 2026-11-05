# Uruguay (URY): fuentes de datos

Script: `src/paises/ury.py` · Configuración: `config/series/URY.csv` (38 series: 28 comunes y 10 extra, 5 de ellas para la capa comparable)
Crudos: `data/raw/URY/{bcu,bcu_cotizaciones,ine,mef}/` · Salida: `data/interim/URY_observaciones.parquet`

## Instituciones y acceso

| Fuente (`fuente`) | Institución | URL base | Acceso | Formato |
|---|---|---|---|---|
| `BCU` | Banco Central del Uruguay: Estadísticas, Política Económica y Mercados, Superintendencia de Servicios Financieros | `https://www.bcu.gub.uy/` | Archivos públicos, sin clave | .xls / .xlsx irregulares |
| `BCU` (listas) | BCU: listas del sitio (IMAE, Tasa 1 día) | `https://www.bcu.gub.uy/_layouts/15/BCU.Portal2016/BCUListasHandler.ashx` (POST `action=export`) | Público, sin clave | .xlsx generado al vuelo |
| `BCU` (cotizaciones) | BCU: web service de cotizaciones | `https://cotizaciones.bcu.gub.uy/wscotizaciones/servlet/awsbcucotizaciones` (SOAP) | Público, sin clave | XML |
| `INE` | Instituto Nacional de Estadística | `https://www5.ine.gub.uy/documents/...` (enlazados desde gub.uy/instituto-nacional-estadistica) | Archivos públicos | .xls / .xlsx |
| `MEF` | Ministerio de Economía y Finanzas: Unidad de Gestión de Deuda y Asesoría Macroeconómica | `https://deuda.mef.gub.uy/innovaportal/file/6473/1/economic-indicators-web.xlsx` y la página "Información de resultados del sector público" en gub.uy | Archivos públicos | .xlsx |

La URL exacta de cada archivo está en el diccionario `SOURCES` de `ury.py`, y queda en `data/_control/manifest_URY.csv`. `codigo_fuente` identifica **archivo | hoja | rótulo de fila o columna [| subrótulo]**, por ejemplo `Creditos.xlsx|Total Sist. Banc.|SECTOR PRIVADO|Total`. Los parsers buscan esos textos (sin tildes ni mayúsculas) y no dependen de posiciones fijas. Si un rótulo no aparece, o aparece en más de una fila con datos, el script falla con un error explícito.

- **No hay series que requieran clave.** No se registró ninguna cuenta. No hay series con `activo=0`.
- Fuentes primarias citadas por los propios archivos:
  - Salario mínimo: el MTSS (la serie es la del INE).
  - Deuda del sector público consolidado en % del PIB: el BCU (la serie es la publicada por el MEF).

## Trampas encontradas

- **Certificados TLS incompletos.** `www.bcu.gub.uy`, `cotizaciones.bcu.gub.uy` y `www5.ine.gub.uy` no envían el certificado intermedio (Abitab/Certum y Sectigo DV R36). `requests` falla con `CERTIFICATE_VERIFY_FAILED`; los navegadores y `curl` en Windows lo resuelven solos. `ca_bundle()` lee el certificado del servidor, descarga los intermedios por AIA (`caIssuers`) y arma un bundle = certifi + intermedios en la carpeta temporal del sistema. Nunca agrega raíces y **no desactiva la verificación**. Necesita el paquete `cryptography`, ya instalado. Esto se resolvió en `ury.py` porque `comun.Client` acepta `verify=` pero no arma bundles.
- **Las páginas del BCU cargan las listas de documentos por JavaScript** (SharePoint + DataTables). Los enlaces no aparecen en el HTML: se obtuvieron llamando por POST a `BCUDocumentosHandler.ashx`/`BCUListasHandler.ashx` con los parámetros que trae el script de cada página. Los archivos de series tienen URL fija, salvo la planilla mensual del MEF.
- **IMAE y Tasa 1 día no tienen archivo**: son listas de SharePoint. Se usa la exportación Excel del handler (`action=export`), que **genera bytes distintos en cada descarga**. Antes de `save_raw` se comparan las hojas con el crudo existente; si el contenido es igual se registra `sin_cambios` y no se versiona. En esa exportación, la columna de la TPM se llama **`Title`** (nombre interno de SharePoint), por eso el `codigo_fuente` la nombra así.
- **El web service de cotizaciones** no tiene datos antes del 3-1-2000 (`codigoerror 100`) y rechaza rangos de más de un año (`codigoerror 104`). Se pide un año por consulta (`cotizaciones_2225_<año>.xml`). Los años cerrados no se vuelven a pedir: solo el año en curso, el anterior y los que falten.
- **Rótulos de fecha mezclados.**
  - En la encuesta de expectativas (`IEES05I2.xlsx`), la columna "Fecha encuesta" trae fechas de Excel y textos como `Set-05` o `May-26`, con mes abreviado en español ("Set" = setiembre) y año de 2 dígitos.
  - Los cuadros de comercio exterior traen fechas con días arbitrarios (2019-01-06, 2019-02-27): se normalizan al mes y se valida que no haya meses repetidos.
- **ECH (`ECH0013.xlsx`):** los años son filas separadoras con notas al pie (`2015 (5)`, `2017 (7) (8)`). Entre los meses hay filas de trimestres (`Enero - Marzo/06`) y de total anual. Solo se toman los meses. La primera versión del parser no reconocía los años con notas y duplicaba periodos: lo detectó la validación de `write_interim`.
- **Excel con hojas partidas:** M2 y M3 (hoja `Fin de Mes dic98-dic09` + `Fin de Mes`) y comercio exterior (hojas hasta dic-2018 y desde ene-2019). Se unen sin solapamiento.
- **Planilla "Economic Indicators" del MEF:**
  - Las columnas 2009-2015 existen pero están vacías: la serie empieza en 2016, con el PBI base 2016.
  - La columna del año en curso es un acumulado móvil (`As of: 2026M06`), no un año calendario. Se descarta salvo que el dato sea de diciembre o del 4.º trimestre.
  - "Gross debt" aparece dos veces: gobierno central y sector público consolidado. La sección se identifica por su rótulo exacto (`Consolidated Public Sector (5)`).
- **Planilla mensual de resultados del MEF:** el nombre del archivo cambia cada mes (`Resultados Sector Público Agosto 2026.xlsx`). El enlace vigente se toma de la página del MEF y se guarda con nombre fijo (`resultados_sector_publico.xlsx`).
- **Valores "sin dato":** `-` en la TMM los días sin operaciones (22 casos), `n/d` en reservas antes de 2008 (en columnas no usadas) y celdas vacías. Se descartan y quedan en el log; no se imputan.
- **Capa comparable (2026-10-21).** Las cinco series nuevas salen de archivos que ya se descargaban:
  - `m3_amplio`: fila "13 .- M3 = (11) + (12)" de `pmam03d.xls` (selector `M3 =`). M3 = M2' (M2 +
    depósitos de ahorro previo) + depósitos en moneda extranjera de residentes, en pesos al tipo de
    cambio de fin de mes.
  - `credito_privado_mn` / `credito_privado_me_usd`: bloque "ANEXO RESIDENTES POR MONEDAS" de la hoja
    `Total Sist. Banc.` de `Creditos.xlsx` (columnas a la derecha del total en pesos). Como "SECTOR
    PRIVADO" y "Total" se repiten en tres bloques, el selector tiene tres niveles:
    `MONEDA NACIONAL|SECTOR PRIVADO|Total` y `MONEDA EXTRANJERA|SECTOR PRIVADO|Total` (soporte agregado
    en `parse_long`; los selectores de 1 y 2 niveles no cambian). La ME viene en millones de USD.
  - `exportaciones_bienes_bp` / `importaciones_bienes_bp`: filas "Crédito" y "Débito" **debajo de
    "1.A.a Bienes"** en el Cuadro Nº 1 de la balanza de pagos. "Crédito" y "Débito" se repiten en
    cada sección, así que el selector usa `Padre > Hijo` (`parse_wide_nested`). El crédito de bienes
    MBP6 = mercancías generales (incluye **zonas francas**) + exportaciones netas de bienes en
    **compraventa** (merchanting: 2.140 MUSD en 2025).
- **Fechas futuras:** la Unidad Indexada se publica por adelantado (hasta el 10 del mes siguiente). Se descartan las fechas posteriores a hoy.
- **Cálculos propios** (el organismo no publica la serie con esa forma):
  - `pbi_real_var12m_trim` y `actividad_mensual_var12m`: interanuales desde los niveles.
  - `pbi_nominal_anual`: suma de 4 trimestres.
  - `tc_usd_promedio`: promedio de las cotizaciones diarias. El BCU publica promedios mensuales en un PDF/XLS por mes.
  - `reservas_internacionales` y `tasa_politica`: último dato del mes.
  - `balanza_comercial`: exportaciones FOB menos importaciones FOB.
  - `salario_minimo`: el INE publica el importe por fecha de vigencia; se repite cada mes hasta el siguiente cambio.

  Las agregaciones desde datos diarios incluyen solo meses cerrados.
- **Cambios de moneda:** el IPC (desde 1937) y el salario mínimo (desde 1969) ya vienen expresados en la moneda actual por el INE, así que se conserva toda la historia. Las series en niveles del BCU empiezan después del peso uruguayo de 1993 (la más antigua es de 1998).

## Validación (descarga del 2026-10-21)

| Dato | Parquet | Publicación oficial | OK |
|---|---|---|---|
| IPC, variación 12 meses, set-2026 | 4,676% | 4,676% (INE, cuadro IPC) | sí |
| IPC, variación 12 meses, jul-2026 | 4,266% | 4,27% (MEF, Economic Indicators, "Consumer inflation, eop", 2026M07) | sí |
| TPM, jul-2026 (fin de mes) | 5,75% | 5,75% (MEF, Economic Indicators, "Monetary Policy Interest Rate", 2026M07) | sí |
| Dólar, 31-07-2026 | 40,273 | 40,273 (BCU, Principales Agregados Monetarios, "Tipo de cambio fin de período") y 40,273 (MEF, "Nominal exchange rate eop") | sí |
| Tasa pasiva y tasa activa en $, jun-2026 | 4,956% / 15,566% | 4,956% / 15,566% (MEF, "Interest rate on local currency deposits/loans") | sí |
| M3, ago-2026 | 1.977.225,7 | 1.977.225,7 millones de $ (BCU, `pmam03d.xls`, "13 .- M3", última información 31/08/2026) | sí |
| Crédito privado MN / ME, ago-2026 | 601.758,5 / 13.138,8 | mismos valores (BCU-SSF, `Creditos.xlsx`, anexo residentes por monedas) | sí |
| Bienes BP, 2026-T2 (crédito / débito) | 4.179,3 / 3.671,4 | mismos valores (BCU, `dse_bp_m6_arm_scn.xlsx`, Cuadro Nº 1, 2026*.II) | sí |

Controles de consistencia:
- **Inflación 12m calculada desde `ipc_indice`** frente a la publicada: diferencia máxima de 0,0074 pp en toda la serie desde 1938 (redondeo).
- **IMAE interanual calculado** frente al del MEF (may-2026): -1,348% frente a -1,352%. La diferencia se explica por revisiones posteriores del IMAE.
- **Escalas:**
  - Exportaciones e importaciones: alrededor de 1.000 millones de USD por mes (el BCU publica en miles; se dividió por 1000).
  - Crédito privado: 1,13 billones de $.
  - Reservas: 18.216 millones de USD.
- **`m3_amplio` ≥ `m2`** en los 333 meses (M3/M2 entre 2,61 y 2,72: el peso de los depósitos en dólares).
- **Crédito MN + ME × TC** (dólar billete del último día hábil del mes, `tc_usd_diario`) frente a
  `credito_privado`: diferencia mediana 0,03 %, máxima 0,41 % (2002-07) y 0,16 % desde 2010; la
  diferencia es el tipo de cambio que usa la SSF. El crédito en ME es el 47 % del total en ago-2026.
- **Bienes de la balanza de pagos frente a la suma trimestral del registro aduanero** (58 trimestres):
  - Exportaciones: la BP supera a las cumplidas en **+54 % en promedio** (rango +37 % a +81 %). En
    2025: BP 16.641 MUSD = mercancías generales 14.501 + compraventa 2.140; aduana 11.205. La
    diferencia de mercancías generales (3.296 MUSD) son sobre todo las exportaciones desde **zonas
    francas** (celulosa, entre otras), que el registro aduanero excluye.
  - Importaciones: la BP supera a las cumplidas FOB en **+13 % en promedio** (rango +9 % a +20 %),
    por las importaciones de zonas francas y ajustes de cobertura.

## Cobertura obtenida

| nombre_corto | código fuente (archivo / rótulo) | indicador común | frec. | desde | hasta | n |
|---|---|---|---|---|---|---|
| `pbi_real_trim` | Actividades_K.xlsx / PRODUCTO INTERNO BRUTO | pbi_real_trim | trimestral | 2016-T1 | 2026-T2 | 42 |
| `pbi_real_var12m_trim` | idem #var12m | pbi_real_var12m_trim | trimestral | 2017-T1 | 2026-T2 | 38 |
| `pbi_desest_trim` | Desestacionalizado.xlsx / PRODUCTO INTERNO BRUTO | pbi_desest_trim | trimestral | 2016-T1 | 2026-T2 | 42 |
| `actividad_mensual_indice` | imae.xlsx / IMAE | actividad_mensual_indice | mensual | 2016-01 | 2026-07 | 127 |
| `actividad_mensual_var12m` | idem #var12m | actividad_mensual_var12m | mensual | 2017-01 | 2026-07 | 115 |
| `pbi_nominal_anual` | Actividades_C.xlsx #suma_anual | pbi_nominal_anual | anual | 2016 | 2025 | 10 |
| `ipc_indice` | ipc_general_base2022.xlsx / Índice | ipc_indice | mensual | 1937-07 | 2026-09 | 1071 |
| `inflacion_mensual` | idem / Mensual | inflacion_mensual | mensual | 1937-08 | 2026-09 | 1070 |
| `inflacion_12m` | idem / Acum.12 meses | inflacion_12m | mensual | 1938-07 | 2026-09 | 1059 |
| `inflacion_subyacente_12m` | ipc_subyacente.xlsx / IPC_CE VFCTA / Var. 12M | inflacion_subyacente_12m | mensual | 2023-10 | 2026-09 | 36 |
| `tasa_politica` | tasa_1_dia.xlsx / Title #fin_mes | tasa_politica | mensual | 2020-09 | 2026-09 | 73 |
| `tasa_interbancaria` | tasa_1_dia.xlsx / TMM Promedio del mes | tasa_interbancaria | mensual | 2020-09 | 2026-09 | 73 |
| `tasa_activa_promedio` | tasas.xls / Activas $ / PROMEDIO | tasa_activa_promedio | mensual | 1998-01 | 2026-08 | 344 |
| `tasa_pasiva_promedio` | tasas.xls / Pasivas $ / PROMEDIO | tasa_pasiva_promedio | mensual | 1998-01 | 2026-08 | 344 |
| `credito_privado` | Creditos.xlsx / SECTOR PRIVADO / Total | credito_privado | mensual | 1998-12 | 2026-08 | 333 |
| `m2` | pmam03d.xls / M 2 = | m2 | mensual | 1998-12 | 2026-08 | 333 |
| `expectativa_inflacion_12m` | IEES05I2.xlsx / próximos doce meses / Mediana | expectativa_inflacion_12m | mensual | 2004-01 | 2026-10 | 274 |
| `tc_usd_promedio` | WS cotizaciones 2225 #prom_mes | tc_usd_promedio | mensual | 2000-01 | 2026-09 | 321 |
| `tc_usd_diario` | WS cotizaciones 2225 / TCV | tc_usd_diario | diaria | 2000-01-03 | 2026-10-20 | 6653 |
| `reservas_internacionales` | reservas.xls / ACTIVOS DE RESERVA #fin_mes | reservas_internacionales | mensual | 2002-06 | 2026-09 | 292 |
| `exportaciones` | exp_ciiu_val.xls / TOTAL EXPORTACIONES | exportaciones | mensual | 2000-01 | 2026-08 | 320 |
| `importaciones` | imp_gce_val.xls / TOTAL IMPORTACIONES FOB | importaciones | mensual | 2000-01 | 2026-08 | 320 |
| `balanza_comercial` | exportaciones − importaciones | balanza_comercial | mensual | 2000-01 | 2026-08 | 320 |
| `cuenta_corriente` | dse_bp_m6_arm_scn.xlsx / 1. Cuenta Corriente | cuenta_corriente | trimestral | 2012-T1 | 2026-T2 | 58 |
| `resultado_fiscal_pct_pbi` | economic-indicators-web.xlsx / SPC fiscal balance | resultado_fiscal_pct_pbi | anual | 2016 | 2025 | 10 |
| `deuda_publica_pct_pbi` | economic-indicators-web.xlsx / SPC Gross debt | deuda_publica_pct_pbi | anual | 2016 | 2025 | 10 |
| `desempleo` | ECH0013.xlsx / Total Pais | desempleo | mensual | 2006-01 | 2026-08 | 248 |
| `salario_minimo` | salario_minimo_nacional.xls / Importe #ffill_mes | salario_minimo | mensual | 1969-12 | 2026-10 | 683 |
| `imae_desest` | imae.xlsx / Desestacionalizado | — | mensual | 2016-01 | 2026-07 | 127 |
| `ui_diaria` | unidad_indexada.xls / Pesos ($) | — | diaria | 2002-06-01 | 2026-10-21 | 8909 |
| `ims_nominal_indice` | IMSN_M_B08.xls / Índice | — | mensual | 2002-12 | 2026-08 | 285 |
| `inflacion_subyacente_vfc_12m` | ipc_subyacente.xlsx / IPC_CE VFC / Var. 12M | — | mensual | 2023-10 | 2026-09 | 36 |
| `resultado_global_spc_mensual` | resultados_sector_publico.xlsx / RESULTADO GLOBAL SPC | — | mensual | 1999-01 | 2026-08 | 332 |
| `m3_amplio` | pmam03d.xls / M3 = | — | mensual | 1998-12 | 2026-08 | 333 |
| `credito_privado_mn` | Creditos.xlsx / MONEDA NACIONAL / SECTOR PRIVADO / Total | — | mensual | 1998-12 | 2026-08 | 333 |
| `credito_privado_me_usd` | Creditos.xlsx / MONEDA EXTRANJERA / SECTOR PRIVADO / Total | — | mensual | 1998-12 | 2026-08 | 333 |
| `exportaciones_bienes_bp` | dse_bp_m6_arm_scn.xlsx / 1.A.a Bienes > Crédito | — | trimestral | 2012-T1 | 2026-T2 | 58 |
| `importaciones_bienes_bp` | dse_bp_m6_arm_scn.xlsx / 1.A.a Bienes > Débito | — | trimestral | 2012-T1 | 2026-T2 | 58 |

## Indicadores comunes no cubiertos

Ninguno: los 28 están cubiertos. Con reservas:
- **Historia corta por cambio de base o de régimen**:
  - Cuentas nacionales y IMAE base 2016 (desde 2016).
  - Balanza de pagos MBP6 (desde 2012).
  - TPM (desde set-2020, cuando el BCU volvió a usar la tasa como instrumento; antes fijaba metas de agregados).
  - Subyacente IPC-CE (desde oct-2023 en 12 meses).
  - Indicadores fiscales en % del PBI (desde 2016).

  El BCU no publica empalmes de las bases anteriores.
- **`balanza_comercial`** es exportaciones menos importaciones del registro aduanero (sin zonas francas). No coincide con la balanza de bienes de la balanza de pagos; para eso están `exportaciones_bienes_bp` e `importaciones_bienes_bp` (trimestrales, desde 2012).
- **`tasa_activa_promedio` y `tasa_pasiva_promedio`** son en moneda nacional no reajustable. Uruguay está muy dolarizado: en `tasas.xls` también están las tasas en UI y en dólares.

## Pendientes

- Empalmar las cuentas nacionales base 2005 (1997-2016) y la balanza de pagos MBP5 (1999-2011), ambas publicadas por el BCU en planillas aparte, para alargar el PBI, el IMAE y la cuenta corriente.
- Revisar la deuda del SPC de 2025 (75,01% del PBI frente a 67,5% en 2024): es el dato publicado por el MEF, pero el salto y el valor redondo merecen confirmarse con la planilla de deuda del BCU (`resdspg.xls`, en millones de USD).
- Opcional: tasas en dólares y en UI y depósitos (archivos de la SSF ya identificados: `tasas.xls`, `Depositos.xlsx`). El crédito por moneda ya está cargado.

## Cómo actualizar

```
python src/paises/ury.py                    # descarga todo y reconstruye el parquet (~2 min)
python src/paises/ury.py --solo-procesar    # solo reprocesa data/raw/URY
python src/paises/ury.py --serie tc_usd_diario tasa_politica   # descarga solo esas series
```
