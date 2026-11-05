# Panamá (PAN): fuentes de datos

Script: `src/paises/pan.py` · Configuración: `config/series/PAN.csv` (26 series: 16 comunes y 10 extra, todas activas)
Crudos: `data/raw/PAN/<fuente>/` · Salida: `data/interim/PAN_observaciones.parquet`

Panamá **no tiene banco central** y está **dolarizado**: el balboa equivale a 1 USD y circula el dólar. Por eso no existen tasa de política monetaria, tipo de cambio oficial, reservas internacionales ni agregados monetarios (M2) oficiales. Los montos en balboas se registran como USD.

## Instituciones y acceso

| Fuente (`fuente`) | Institución | URL | Acceso | Formato |
|---|---|---|---|---|
| `inec` | Instituto Nacional de Estadística y Censo (Contraloría General) | `https://www.inec.gob.pa/avance/...` (avance de cifras) y `/publicaciones/Default3.aspx?ID_PUBLICACION=...` | Archivo; la URL se busca en la página de cada publicación | .xlsx, .xls (BIFF), .csv en latin-1 |
| `sbp` | Superintendencia de Bancos de Panamá | `https://www.superbancos.gob.pa/` (portada), `/estadisticas-financieras/tasas-interes`, `/estadisticas-financieras/cartera-credito` | Archivo | .xlsx |
| `mef` | Ministerio de Economía y Finanzas | `https://www.mef.gob.pa/documentos/balance-fiscal/` | Archivo | .xlsx |

Archivos que se usan (nombre estable en `raw/PAN/`, porque el nombre publicado lleva una marca de tiempo):

| Archivo crudo | Origen |
|---|---|
| `inec/imae_serie.csv`, `inec/imae_cuadro.xlsx` | Avance de cifras, IMAE base 2007 (`ID_CATEGORIA=1&ID_CIFRAS=49`): enlaces `IMAE*.csv` y `Cuadro_IMAE*.xlsx` |
| `inec/ipc_anexo4.xlsx` | Avance de cifras, Índice de Precios (`ID_CATEGORIA=2&ID_CIFRAS=10`): `Anexo 4.xlsx` |
| `inec/pib_trimestral.xlsx` | Publicación más reciente de "PIB TRIMESTRAL" (categoría 4, subcategoría 73) |
| `inec/pib_anual.xlsx` | Publicación más reciente de "PIB ANUAL" (subcategoría 26) |
| `inec/eml_cuadro2.xlsx` | Publicación más reciente de la Encuesta de Mercado Laboral (subcategoría 38), `Cuadro 2.xlsx` |
| `inec/piem_<AAAA>_{valor_fob,valor_cif,transporte_acp}.xls` | "Principales Indicadores Económicos Mensuales - AAAA" (una página por año, de 2017 a 2026) |
| `inec/bp_<pub>_cuadro1_mbp5.xlsx` | Cuadro 1 "Componentes normalizados – MBP5" de cada publicación trimestral de la balanza de pagos (subcategoría 24) |
| `sbp/tasa_interbancaria.xlsx` | `tasas.xlsx`, enlazado en la portada de la SBP |
| `sbp/tasas_creditos.xlsx`, `sbp/tasas_depositos.xlsx` | Página de tasas de interés de la SBP |
| `sbp/re0034a_AAAAMM.xlsx` | Reporte RE0034A "Resumen de saldos de créditos locales a los sectores económicos": el del último mes (desde la página) y el de diciembre de cada año desde 2019 (ruta `reportes_estadisticos/AAAA/12/cartera_sectorial/`) |
| `mef/balance_fiscal__<nombre>.xlsx` | Todos los balances fiscales en español de la página del MEF; solo se usan los de cierre de año |

Las publicaciones históricas que ya no cambian (páginas PIEM de años anteriores, balanzas de pagos viejas, reportes de diciembre de la SBP) se bajan una sola vez. `--rehacer-historico` las vuelve a bajar. No hay series con token ni con `activo=0`.

## Trampas encontradas

- **Nombres de archivo con marca de tiempo.** Por ejemplo, `A0705547520261014084610Anexo 4.xlsx`. El script busca el enlace por patrón en la página y guarda con nombre fijo.
- **Las .xls de los PIEM traen hojas de otros indicadores.** Por ejemplo, `transporte_acp.xls` incluye también construcción y viajeros. La tabla se localiza **por el título** en las primeras filas ("Valor FOB de las exportaciones", "Autoridad del Canal de Panamá"), nunca por el nombre de la hoja o del archivo.
- **Estructura año/mes de los PIEM.** Cada archivo trae filas de acumulados por año (2022, 2023…) y, debajo de los dos últimos años, filas de meses. Después vienen bloques de "Variación porcentual" con rótulos de mes que **no** son datos: el parser se detiene en ellos. Cada archivo anual cubre su año y el anterior. El archivo más nuevo manda, así que cada mes queda con su versión más revisada.
- **Rótulos que cambian entre años.** Canal: "Tránsito de naves" (hasta 2024) frente a "Tránsito de buques" (desde 2025), e "Ingresos por peaje" frente a "Ingresos por peajes". Un primer intento tomó la columna de buques Neopanamax en los años viejos: se busca la primera columna "Tránsito de…" (bloque TOTAL). Se comprobó que los meses superpuestos coinciden entre archivos de años sucesivos.
- **Exportaciones FOB del INEC.** Son exportaciones **nacionales**: no incluyen las reexportaciones de la Zona Libre de Colón ni de las zonas francas, que son la mayor parte del comercio de bienes en la balanza de pagos. Entre ediciones hay revisiones grandes (inclusión del cobre de 2019 en adelante): se usa siempre la edición más nueva.
- **IPC: cambio de base en septiembre de 2025.** La base 2024=100 rige desde sep-2025 y el INEC la retropola hasta ene-2024 (Anexo 4). La serie base 2013 (hasta ago-2025) solo está en cuadros anuales sueltos con otro diseño y **no se empalma**. Por eso `ipc_indice` empieza en 2024-01. La interanual de 2024 la publica el INEC con la base 2013. No hay inflación subyacente oficial.
- **IMAE.** El CSV (`IMAE AIG`) tiene la serie original y la tendencia-ciclo desde 2016 con 1 decimal. El cuadro .xlsx tiene más decimales pero solo desde 2022, y es el único que trae la variación interanual oficial. Las gráficas .xlsx no traen datos.
- **SBP, crédito RE0034A.** (1) El título dice "En Millones de Balboas", pero desde los reportes de 2023-12 los valores vienen **en balboas**: se detecta por magnitud (más de 1e7) y se reescala. (2) Los meses futuros del año vienen en **0** y se descartan (son marcadores, no datos). (3) La ruta histórica empieza en 2019/12; 2018/12 da 404.
- **SBP, tasa interbancaria.** Es semanal y con varios plazos. Las semanas en **0** (sin operaciones en ese plazo) se descartan. En plazos largos (3 y 6 meses) son muy frecuentes y hay notas de "solo un banco reportó": por eso se usa el plazo de **1 semana**. El dato mensual es el promedio simple de las semanas con dato. El mes en curso queda con las semanas disponibles.
- **SBP, tasas de crédito y depósito.** "N.D." = sin dato; se descarta (p. ej. vivienda no preferencial en los primeros años).
- **INEC, PIB trimestral.** El CSV publicado trae **rótulos de trimestre equivocados**: después de 2022-Q2 repite "2021-Q3" y "2021-Q4". Se usa el .xlsx, con filas de año y de trimestre (I a IV). En el .xlsx la columna del PIB se rotula "PIB a precios de comprador" en una hoja y "PRODUCTO INTERNO BRUTO…" en otra.
- **INEC, PIB anual.** La hoja "Contenido" repite los títulos de los cuadros: la búsqueda exige también el rótulo de la columna.
- **Balanza de pagos.** Cada publicación cubre 2 años más el año en curso, con columnas "Total", trimestres y acumulados ("Enero a septiembre", "Primer semestre") que se descartan. Se unen todas las publicaciones con el diseño actual (la serie arranca en 2015-T1); la más nueva manda. Las de 2012-2014 tienen otro diseño (solo enero-septiembre, rótulos "Primero/Tercero") y se omiten, porque dejarían años sin el 4.º trimestre. En la serie final se verificó que la suma de los trimestres coincide con el total anual. Ojo: las ediciones preliminares tuvieron revisiones grandes (2023-T3 pasó de −5 855 a −990 millones).
- **Bienes de balanza de pagos: crédito y débito.** Van en las subfilas «crédito» y «débito» debajo
  de «A. Bienes» (en algunas ediciones viejas hay una fila vacía en medio). El cuadro publica los
  **débitos con signo negativo**: `importaciones_bienes_bp` cambia el signo (importaciones positivas)
  y el procesamiento falla si algún débito viniera positivo. La fila de «A. Bienes» y sus subfilas
  traen además el n.º de línea repetido en una columna a la derecha (no es un dato; no cae en las
  columnas trimestrales). Las publicaciones que no tienen «A. Bienes» con ese diseño se omiten igual
  que para `balanza_comercial`, así que las cuatro series de balanza de pagos comparten cobertura.
- **MEF.** Hay archivos mensuales (enero-mes) y de cierre; solo los de cierre ("Diciembre" / "Diciembre") dan el resultado anual. El "% del PIB" viene como fracción y se multiplica por 100, y se valida contra Balance Total / PIB nominal estimado del mismo cuadro (tolerancia 0.15 pp). En la página hay archivos en inglés ("Fiscal-Balance…", "-EN"), que se excluyen. Tres de ellos quedaron bajados en la primera corrida (antes de afinar el filtro) y se ignoran al procesar, porque no tienen la hoja en español.

## Cortes metodológicos que hay que conocer

- **Cuentas nacionales base 2018.** El PIB trimestral y el anual (volumen encadenado, año de referencia 2018) empiezan en 2018. La serie base 2007 no se empalma. Cifras de 2024 preliminares y de 2025-2026 estimadas.
- **IMAE base 2007.** Es distinta de la base 2018 del PIB: el INEC sigue publicando el IMAE con base 2007.
- **IPC base 2024 desde 2024-01.** No hay continuidad con la base 2013 (ver trampas).
- **Desempleo.** Es **anual** (Encuesta de Mercado Laboral). El mes de levantamiento varía: 2021 octubre, 2022 abril, 2024 octubre (revisado), 2025 septiembre. No hay dato de 2020 (la encuesta telefónica de ese año no es comparable). 2011 y 2012 están marcados como revisados (R).

## Validación (descarga del 2026-10-21)

| Dato | Parquet | Publicación oficial | OK |
|---|---|---|---|
| IPC Nacional Urbano, septiembre de 2026: índice / var. mensual / var. interanual | 102.534 / 0.535 % / 2.792 % | 102.5 / 0.5 % / 2.8 % (INEC, "Comentario sobre el IPC Nacional Urbano: septiembre de 2026", PDF) | sí |
| IMAE agosto de 2026, var. interanual de la serie original | 7.36 % | 7.36 % (INEC, comentario del IMAE de agosto de 2026); agosto de 2025: 1.61 % en ambos | sí |
| PIB real II trim. 2026, var. interanual | 6.38 % | 6.4 % (INEC, comentario del PIB trimestral II-2026) | sí |
| Balance del SPNF 2025 | −3.68 % del PIB | −3.7 % (MEF, Balance-Fiscal-ES-2025-2024, celda "% del PIB") | sí |

Controles de consistencia:
- **Inflación 12m calculada desde `ipc_indice`** frente a la publicada: diferencia < 0.001 pp en todos los meses de 2025-2026 (2024 no se puede calcular con la base 2024). Lo mismo con la variación mensual.
- **PIB:** la variación interanual calculada desde `pbi_real_trim` coincide con `pbi_real_var12m_trim`, y la suma de los 4 trimestres nominales coincide con `pbi_nominal_anual` en 2018-2025.
- **IMAE:** la variación interanual calculada desde el índice del CSV coincide con la del cuadro (±0.03 pp por el redondeo a 1 decimal).
- **Balanza de pagos:** la suma de los trimestres de 2024 y 2025 coincide con el total anual publicado.
- **Bienes de balanza de pagos (agregados el 2026-10-21):** 2026-T2 = 5 203,5 (crédito) y 8 326,2
  (débito) millones, iguales al Cuadro 1 de la publicación más reciente; las sumas de 2024 (15 831,8 /
  26 193,9) y 2025 (15 709,5 / 28 202,8) coinciden con la columna «Total». `exportaciones_bienes_bp` −
  `importaciones_bienes_bp` = `balanza_comercial` en los 46 trimestres (diferencia 0,0).
- **Bienes de balanza de pagos frente al comercio del PIEM:** no son comparables en nivel, y es lo
  esperado. En 2024 las exportaciones del PIEM (`exportaciones`, nacionales FOB) suman 890 millones
  y las de balanza de pagos 15 832, porque estas incluyen (Cuadro 1, líneas 15-19) las
  reexportaciones de la Zona Libre de Colón (12 208), las zonas procesadoras (1 511) y las
  reexportaciones nacionales (193); menos ajustes de cobertura (−1 302, sobre todo reexportaciones de
  la ZLC al propio Panamá) y de momento de registro (−244); y más bienes adquiridos en puerto
  (combustible para buques y aeronaves, 2 561). En importaciones, el PIEM (CIF, sin ZLC) suma 13 992
  y la balanza de pagos 26 194 (1,9 veces): la balanza suma las importaciones de la ZLC (12 647 CIF)
  y de las zonas procesadoras (2 964), pasa todo a FOB (las importaciones nacionales FOB son 12 586,
  unos 1 400 millones menos que las CIF del PIEM) y agrega ajustes (+5 100). La razón importaciones BP
  / PIEM CIF fue 1,73-2,07 en 2016-2025.
- **PIEM:** los meses superpuestos entre ediciones sucesivas coinciden, salvo revisiones documentadas.

## Cobertura obtenida

| nombre_corto | indicador común | frecuencia | desde | hasta | n |
|---|---|---|---|---|---|
| actividad_mensual_indice | actividad_mensual_indice | mensual | 2016-01 | 2026-08 | 128 |
| actividad_mensual_var12m | actividad_mensual_var12m | mensual | 2022-01 | 2026-08 | 56 |
| balanza_comercial | balanza_comercial | trimestral | 2015-T1 | 2026-T2 | 46 |
| credito_privado | credito_privado | mensual | 2018-12 | 2026-08 | 93 |
| cuenta_corriente | cuenta_corriente | trimestral | 2015-T1 | 2026-T2 | 46 |
| desempleo | desempleo | anual | 2001 | 2026 | 25 |
| exportaciones | exportaciones | mensual | 2016-01 | 2026-08 | 128 |
| importaciones | importaciones | mensual | 2016-01 | 2026-08 | 128 |
| inflacion_12m | inflacion_12m | mensual | 2024-01 | 2026-09 | 33 |
| inflacion_mensual | inflacion_mensual | mensual | 2024-01 | 2026-09 | 33 |
| ipc_indice | ipc_indice | mensual | 2024-01 | 2026-09 | 33 |
| pbi_nominal_anual | pbi_nominal_anual | anual | 2018 | 2025 | 8 |
| pbi_real_trim | pbi_real_trim | trimestral | 2018-T1 | 2026-T2 | 34 |
| pbi_real_var12m_trim | pbi_real_var12m_trim | trimestral | 2019-T1 | 2026-T2 | 30 |
| resultado_fiscal_pct_pbi | resultado_fiscal_pct_pbi | anual | 2024 | 2025 | 2 |
| tasa_interbancaria | tasa_interbancaria | mensual | 2006-02 | 2026-10 | 249 |
| canal_ingresos_peaje | — | mensual | 2017-01 | 2026-08 | 116 |
| canal_transitos | — | mensual | 2017-01 | 2026-08 | 116 |
| imae_tendencia_ciclo | — | mensual | 2016-01 | 2026-08 | 128 |
| pbi_nominal_trim | — | trimestral | 2018-T1 | 2026-T2 | 34 |
| tasa_ahorro | — | mensual | 2001-12 | 2026-08 | 297 |
| tasa_credito_comercio_mayor | — | mensual | 2001-12 | 2026-08 | 297 |
| tasa_dpf_1_anio | — | mensual | 2001-12 | 2026-08 | 297 |
| tasa_prestamo_personal | — | mensual | 2001-12 | 2026-08 | 297 |
| exportaciones_bienes_bp | — | trimestral | 2015-T1 | 2026-T2 | 46 |
| importaciones_bienes_bp | — | trimestral | 2015-T1 | 2026-T2 | 46 |

## Indicadores comunes no cubiertos

| Indicador | Motivo |
|---|---|
| `tasa_politica` | No aplica: no hay banco central ni política monetaria propia (dolarización). |
| `tc_usd_promedio`, `tc_usd_diario` | No aplica: balboa = USD 1:1 por ley. |
| `reservas_internacionales` | No aplica: sin banco central no hay reservas oficiales publicadas. El Banco Nacional publica sus estados financieros, pero no una serie de reservas. |
| `m2` | No hay agregado monetario oficial (el dólar circula sin medición de efectivo). La SBP publica depósitos, pero no M2. |
| `expectativa_inflacion_12m` | No hay encuesta oficial de expectativas. |
| `inflacion_subyacente_12m` | El INEC no publica inflación subyacente. |
| `pbi_desest_trim` | El INEC no publica el PIB trimestral desestacionalizado (el IMAE solo trae tendencia-ciclo, que va como extra). |
| `tasa_activa_promedio`, `tasa_pasiva_promedio` | La SBP publica tasas por producto (préstamo personal, comercio, depósitos a plazo y de ahorro), pero no un promedio del sistema. Se incluyen 4 de ellas como extras. |
| `deuda_publica_pct_pbi` | El MEF publica la deuda pública en informes PDF, sin una serie histórica en Excel. La balanza de pagos (Cuadro 9) solo trae deuda externa. |
| `salario_minimo` | No hay un salario mínimo único: el decreto fija tasas por hora según región, actividad y tamaño de empresa (PDF del MITRADEL). |

## Pendientes

- IPC: empalmar, si se requiere, la base 2013 (2013-2025) con la base 2024 usando el Anexo 3 (comparativo de bases 2024-2025). Habría que documentarlo como serie calculada.
- Fiscal: solo hay dos cierres en Excel (2024 y 2025). Los años anteriores están en PDF.
- Hecho (2026-10-21): exportaciones e importaciones de bienes de balanza de pagos con la Zona Libre de
  Colón (`exportaciones_bienes_bp`, `importaciones_bienes_bp`; trimestrales, MBP5, desde 2015-T1). Las
  publicaciones 2012-2014 tienen otro diseño y no se usan.
- Si el INEC publica la retropolación del PIB base 2018 antes de 2018, ampliar `pbi_real_trim`.
