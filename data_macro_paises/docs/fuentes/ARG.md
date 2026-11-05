# Argentina (ARG): fuentes de datos

Script: `src/paises/arg.py` · Configuración: `config/series/ARG.csv` (42 series: 28 comunes y 14 extra, 5 de ellas para la capa comparable)
Crudos: `data/raw/ARG/<fuente>/` · Salida: `data/interim/ARG_observaciones.parquet`

## Instituciones y acceso

| Fuente (`fuente`) | Institución | URL | Acceso | Formato |
|---|---|---|---|---|
| `bcra` | Banco Central de la República Argentina | `https://api.bcra.gob.ar/estadisticas/v4.0/Monetarias/{id}` | API, sin clave | JSON |
| `indec` | INDEC: IPC | `https://www.indec.gob.ar/ftp/cuadros/economia/serie_ipc_divisiones.csv` | Archivo | CSV en latin-1, separado por `;`, con coma decimal |
| `datos_gob_ar` | API de Series de Tiempo del Estado argentino (Subsecretaría de Programación Macroeconómica, MECON) | `https://apis.datos.gob.ar/series/api/series/` | API, sin clave | JSON |
| `mecon_finanzas` | Secretaría de Finanzas (MECON): datos trimestrales de la deuda | `https://www.argentina.gob.ar/economia/finanzas/datos-trimestrales-de-la-deuda` | Archivo | .xlsx |

En `datos_gob_ar`, el organismo **originador** de cada serie figura en `notas`:
- INDEC: cuentas nacionales, EMAE, comercio exterior (ICA), balanza de pagos y EPH.
- Secretaría de Hacienda: IMIG.
- Secretaría de Trabajo: SMVM.

No hay series que requieran clave ni series con `activo=0`.

## Trampas encontradas

- **La API del BCRA v3 está deprecada.** `/estadisticas/v3.0/...` responde `410 "Método correspondiente a la v3 ha sido deprecado"`. Se usa la **v4.0**, que tiene un catálogo de 1610 variables (`/Monetarias?offset=&limit=`, que se guarda en `raw/ARG/bcra/catalogo_*.json`).
- **Límite de 3000 registros por consulta en BCRA v4.** Las series diarias se piden en **ventanas fijas de 5 años**, desde el año de `primerFechaInformada` (el script pagina con `offset` si una ventana pasara de 3000). Las ventanas son fijas para que los bloques viejos no cambien en cada corrida: la API ordena de más reciente a más antiguo, y una paginación simple cambiaría todos los archivos cada día. Las mensuales se piden en una sola consulta.
- **Unidades del BCRA.** Los agregados mensuales (M2 `1618`, base monetaria `1606`) vienen en **miles** de ARS y se dividen por 1000. Están reexpresados en pesos actuales desde 1940, así que hasta ~1965 el saldo redondeado es **0**. Esos ceros se descartan (no son datos) y los valores de los años 60 y 70 tienen poca precisión.
- **Tasa de política monetaria.** La variable `6` ya no está en "Principales Variables". Se usa la `160` ("Tasas de interés de política monetaria"), que cubre del 16-12-2015 al **10-07-2025**: desde esa fecha el BCRA no fija una tasa de política (fin de las LEFI; régimen de agregados). La serie termina ahí; no se imputa.
- **Tasa activa promedio.** El BCRA no publica una tasa activa promedio del sistema. Se usa la tasa de **documentos a sola firma** (variable `1216`, mensual, Informe Monetario) como aproximación, y está anotado en `notas`.
- **Series diarias agregadas a mensuales.** Las series diarias se agregan a mensuales así:
  - promedio del mes: tasas BAIBAR, plazo fijo a 30 días y BADLAR, y el tipo de cambio Com. A 3500;
  - último dato del mes: tasa de política y préstamos al sector privado.

  El mes en curso, incompleto, se excluye.
- **El IPC de la API de series llega con un mes de rezago** (agosto de 2026, mientras INDEC ya publicó septiembre). Por eso el IPC se toma del **CSV de INDEC**, que está al día. Ese CSV usa `NA` para "sin dato" (la primera variación mensual y las primeras 12 interanuales), que se descartan y se dejan registradas en el log.
- **Fracciones en la API de series.** El EMAE a/a, la tasa de desempleo y los `representation_mode` vienen como fracción (0,079) y se multiplican por 100.
- **Metadata errónea en la API de series.** `3.2_OGP_D_2004_T_17` aparece como "Oferta global total ... Anual", pero es el **PIB desestacionalizado** trimestral: sus sumas anuales coinciden con las del PIB original (`4.2_OGP_2004_T_17`).
- **Una serie listada pero vacía.** `452.3_RESULTADO_ERO_0_M_20_25` (IMIG, resultado financiero mensual) aparece en el buscador hasta agosto de 2026, pero la API devuelve `data: []`. Se descartó, y se borró el archivo crudo vacío que se había bajado.
- **SMVM** (`57.1_SMVMM_0_M_34`):
  - Antes de 1992 está en signos monetarios ya extinguidos ($ ley 18.188, $a, australes): mezclarlos con pesos rompería la serie, así que se conserva desde enero de 1992 (324 observaciones excluidas).
  - La API trae aumentos **ya decretados a futuro** (hasta abril de 2027); se recorta al mes en curso.
- **Resultado fiscal en % del PIB.** No hay una serie oficial publicada en % del PIB. Se calcula el resultado financiero anual del Sector Público Nacional no financiero, base caja (IMIG, Secretaría de Hacienda), dividido por el PIB nominal de INDEC (×100). Los resultados (2024: +0,30%; 2025: +0,17%) coinciden con lo comunicado oficialmente para 2024.
- **Deuda.** El Excel de Finanzas cambia de nombre cada trimestre (`deuda_publica_30-06-2026_0.xlsx`). El script toma el primer enlace de la página y lo guarda como `deuda_publica.xlsx`; `save_raw` versiona los cambios. Se usa la fila "Deuda Bruta de la Administración Central" de la hoja A.4.7, que **incluye** la deuda elegible no presentada al canje, y solo las columnas anuales (2000-2025).
- **Capa comparable (2026-10-21).** Series nuevas, sin indicador común:
  - `m3_amplio`: variable BCRA **1623** "M3 en moneda local y extranjera" (mensual, miles de ARS → /1000).
    Existe también la 1624 (M3 solo en pesos); se usa la total porque incluye los depósitos en USD.
    Igual que M2, viene reexpresada en pesos actuales desde 1940: 286 ceros por redondeo (hasta 1964)
    se descartan.
  - `credito_privado_mn` / `credito_privado_me_usd`: variables **1342** (millones de ARS) y **1356**
    (millones de USD), "Total de préstamos de efectivo otorgados al sector privado" de la categoría
    Préstamos por línea; diarias → último dato del mes. Se eligieron las de *efectivo* y no las
    1341/1355 ("total de préstamos", que suman préstamos de títulos e intereses documentados)
    porque `credito_privado` (var. 26) = 1342 + 1356 × TC Com. A 3500 **exactamente** (diferencia
    máx. 0,001 % en 366 meses); con 1341/1355 la suma excede a la 26 en ~0,35 %.
  - `exportaciones_bienes_bp` / `importaciones_bienes_bp`: `160.2_CTA_CORFOB_0_T_59` y
    `160.2_CTA_CORRFOB_0_T_59` de la API de series (dataset 160, balanza de pagos MBP6 de INDEC,
    trimestral desde 2006). Las importaciones de la balanza de pagos están valoradas **FOB**; las del
    ICA (`importaciones`) son CIF.
- **PIB trimestral a tasa anual** (detectado en la revisión de comparabilidad, 2026-10-21). `pbi_real_trim`
  y `pbi_desest_trim` vienen a tasa anual: el promedio de los 4 trimestres de 2004 es 485.115, el PIB
  del año base. El PIB anual es el **promedio** de los trimestres, no la suma. Igual que México.

## Cortes metodológicos que hay que conocer

- **Intervención del INDEC (2007-2015).** Entre enero de 2007 y fines de 2015 el IPC-GBA de INDEC fue intervenido y subestimó la inflación. En 2016 INDEC declaró la emergencia estadística y discontinuó las series. Por eso:
  - `ipc_indice`, `inflacion_mensual`, `inflacion_12m` e `inflacion_subyacente_12m` usan solo el **IPC nacional base diciembre de 2016 = 100** (desde diciembre de 2016). No se empalma con el IPC-GBA.
  - Las series extra `inflacion_mensual_bcra_hist` (desde 1943) e `inflacion_12m_bcra_hist` (desde 1944) del BCRA empalman el IPC-GBA, **incluido el período intervenido**: por ejemplo, 9,8% a/a en diciembre de 2006 y 9,1% en marzo de 2007, valores oficiales pero no creíbles. Usarlas con cautela entre 2007 y 2015. Para 2016 el BCRA usa otra fuente provisoria. Desde 2017 coinciden exactamente con INDEC (diferencia 0,0).
  - Las cuentas nacionales base 2004 se publicaron en 2016 y corrigieron la serie de PIB del período intervenido. La revisión ya está incorporada en las series usadas.
- **Cambios de base del IPC.** Las bases fueron 1988, 1999 y abril de 2008 (IPC-GBA, intervenida) y, desde 2016, abril de 2016 (IPC-GBA) y diciembre de 2016 (IPC nacional, la actual). No se cargaron índices de bases anteriores.
- **Cambios de moneda.** Peso ley 18.188 (1970), peso argentino (1983), austral (1985) y peso (1992). Las series del BCRA en ARS (M2, base monetaria) están reexpresadas en pesos actuales; el SMVM se recorta a 1992.
- **Tipo de cambio.** `tc_usd_*` es el **oficial** mayorista Com. A 3500 (desde marzo de 2002). No incluye el dólar paralelo, por la regla de fuentes. Desde abril de 2025 rige un régimen de bandas cambiarias (variables BCRA `1187`/`1188`, no cargadas).

## Validación (descarga del 2026-10-21)

| Dato | Parquet | Publicación oficial | OK |
|---|---|---|---|
| Inflación a/a, septiembre de 2026 | 33,4% | 33,4% (BCRA, Principales Variables, var. `28`; INDEC CSV) | sí |
| Inflación mensual, septiembre de 2026 | 1,9% | 1,9% (BCRA var. `27`) | sí |
| TC Com. A 3500 del 20-10-2026 | 1524,8401 | 1524,8401 (`ultValorInformado` del catálogo BCRA v4) | sí |
| TC minorista del 20-10-2026 | 1545,01 | 1545,01 (catálogo BCRA) | sí |
| Reservas a fin de septiembre de 2026 | 46.092 | 46.092 (catálogo BCRA) | sí |
| M3 total a fin de agosto de 2026 (var. 1623) | 254.440.706 | 254.440.706.244 miles de ARS (`ultValorInformado` del catálogo BCRA) | sí |
| Préstamos en pesos al sector privado, 31-08-2026 (var. 1342) | 107.333.886 | 107.333.886 (consulta directa a la API v4) | sí |
| Préstamos en USD al sector privado, 31-08-2026 (var. 1356) | 25.475 | 25.475 (consulta directa a la API v4) | sí |
| Exportaciones de bienes BP, 2026-T2 | 27.557,2 | 27.557,2 (CSV de la distribución 160.2 de datos.gob.ar, originador INDEC) | sí |
| REM a 12 meses, septiembre de 2026 | 21,1% | 21,1% (catálogo BCRA) | sí |

Controles de consistencia:
- **Inflación 12m calculada desde `ipc_indice`** frente a la publicada por INDEC: diferencia de **0,0** en 106 meses. Lo mismo ocurre con la variación mensual y con la inflación núcleo 12m calculada desde el índice núcleo.
- **PIB a/a de la API** frente al calculado desde los niveles: diferencia menor que 1e-13.
- **EMAE a/a** frente al calculado desde el índice: diferencia menor que 1e-15.
- **`m3_amplio` ≥ `m2`** en los 745 meses comunes (M3/M2 = 2,66 en ago-2026).
- **Crédito MN + ME × TC** (TC Com. A 3500 del último día hábil del mes) frente a `credito_privado`:
  diferencia mediana 0,000 %, máxima 0,001 %. El crédito en USD es el 27 % del total en sep-2026.
- **Bienes de la balanza de pagos frente a la suma trimestral del ICA** (82 trimestres, 2006-2026):
  exportaciones +0,1 % en promedio (rango −0,5 % a +1,2 %: ajustes de cobertura y momento de
  registro; Argentina no tiene zonas francas relevantes en el ICA). Importaciones BP (FOB) −4,8 %
  en promedio (rango −7,0 % a −3,9 %) frente al ICA (CIF): es el flete y seguro, más ajustes.

## Cobertura obtenida

| nombre_corto | código fuente | frec. | desde | hasta | n |
|---|---|---|---|---|---|
| actividad_mensual_indice | `143.3_NO_PR_2004_A_21` | mensual | 2004-01 | 2026-07 | 271 |
| actividad_mensual_var12m | `143.3_ICE_SERVIA_2004_A_25` | mensual | 2005-01 | 2026-07 | 259 |
| balanza_comercial | `74.3_ISC_0_M_19` | mensual | 1992-01 | 2026-08 | 416 |
| credito_privado | `26` | mensual | 1996-04 | 2026-09 | 366 |
| cuenta_corriente | `160.2_TL_CUENNTE_0_T_22` | trimestral | 2006-01 | 2026-04 | 82 |
| *credito_privado_me_usd* (extra) | `1356` | mensual | 1996-04 | 2026-09 | 366 |
| *credito_privado_mn* (extra) | `1342` | mensual | 1996-04 | 2026-09 | 366 |
| *exportaciones_bienes_bp* (extra) | `160.2_CTA_CORFOB_0_T_59` | trimestral | 2006-01 | 2026-04 | 82 |
| *importaciones_bienes_bp* (extra) | `160.2_CTA_CORRFOB_0_T_59` | trimestral | 2006-01 | 2026-04 | 82 |
| *m3_amplio* (extra) | `1623` | mensual | 1964-04 | 2026-08 | 749 |
| desempleo | `45.2_ECTDT_0_T_33` | trimestral | 2003-01 | 2026-04 | 92 |
| deuda_publica_pct_pbi | `A.4.7\|Deuda Bruta de la Administración Central` | anual | 2000 | 2025 | 26 |
| expectativa_inflacion_12m | `29` | mensual | 2004-01 | 2026-09 | 228 |
| exportaciones | `74.3_IET_0_M_16` | mensual | 1992-01 | 2026-08 | 416 |
| importaciones | `74.3_IIT_0_M_25` | mensual | 1992-01 | 2026-08 | 416 |
| inflacion_12m | `0\|Nacional\|v_i_a_IPC` | mensual | 2017-12 | 2026-09 | 106 |
| inflacion_mensual | `0\|Nacional\|v_m_IPC` | mensual | 2017-01 | 2026-09 | 117 |
| inflacion_subyacente_12m | `Núcleo\|Nacional\|v_i_a_IPC` | mensual | 2017-12 | 2026-09 | 106 |
| ipc_indice | `0\|Nacional\|Indice_IPC` | mensual | 2016-12 | 2026-09 | 118 |
| m2 | `1618` | mensual | 1964-08 | 2026-08 | 745 |
| pbi_desest_trim | `3.2_OGP_D_2004_T_17` | trimestral | 2004-01 | 2026-04 | 90 |
| pbi_nominal_anual | `4.3_OGP_2004_A_17` | anual | 2004 | 2025 | 22 |
| pbi_real_trim | `4.2_OGP_2004_T_17` | trimestral | 2004-01 | 2026-04 | 90 |
| pbi_real_var12m_trim | `4.2_OGP_2004_T_17@percent_change_a_year_ago` | trimestral | 2005-01 | 2026-04 | 86 |
| reservas_internacionales | `1605` | mensual | 1940-01 | 2026-09 | 1041 |
| resultado_fiscal_pct_pbi | `452.2_RESULTADO_ERO_0_T_20_31/4.3_OGP_2004_A_17` | anual | 2016 | 2025 | 10 |
| salario_minimo | `57.1_SMVMM_0_M_34` | mensual | 1992-01 | 2026-10 | 418 |
| tasa_activa_promedio | `1216` | mensual | 1993-06 | 2026-09 | 400 |
| tasa_interbancaria | `11` | mensual | 1999-01 | 2026-09 | 332 |
| tasa_pasiva_promedio | `12` | mensual | 1985-08 | 2026-09 | 471 |
| tasa_politica | `160` | mensual | 2015-12 | 2025-07 | 116 |
| tc_usd_diario | `5` | diaria | 2002-03-04 | 2026-10-20 | 6037 |
| tc_usd_promedio | `5` | mensual | 2002-03 | 2026-09 | 295 |
| *base_monetaria* (extra) | `1606` | mensual | 1966-12 | 2026-08 | 717 |
| *cer* (extra) | `30` | diaria | 2002-02-02 | 2026-10-21 | 9028 |
| *emae_desest* (extra) | `143.3_NO_PR_2004_A_31` | mensual | 2004-01 | 2026-07 | 271 |
| *inflacion_12m_bcra_hist* (extra) | `28` | mensual | 1944-01 | 2026-09 | 993 |
| *inflacion_mensual_bcra_hist* (extra) | `27` | mensual | 1943-02 | 2026-09 | 1004 |
| *ipc_nucleo_indice* (extra) | `Núcleo\|Nacional\|Indice_IPC` | mensual | 2016-12 | 2026-09 | 118 |
| *resultado_primario_spn_mensual* (extra) | `452.3_RESULTADO_RIO_0_M_18_54` | mensual | 2016-01 | 2026-08 | 128 |
| *tasa_badlar* (extra) | `7` | mensual | 1999-01 | 2026-09 | 333 |
| *tc_minorista_diario* (extra) | `4` | diaria | 2010-06-01 | 2026-10-20 | 3988 |

## Indicadores comunes no cubiertos

Ninguno: los 28 están cubiertos. Con salvedades:
- `tasa_politica` termina en julio de 2025, por un cambio de régimen.
- `tasa_activa_promedio` es una aproximación.
- `desempleo` es trimestral (no hay tasa mensual oficial).
- `resultado_fiscal_pct_pbi` es un cociente calculado.

## Pendientes

- Resultado fiscal antes de 2016: la API tiene el Esquema AIF con metodologías 1993-2006 y 2007-2014 (datasets 377/379). Habría que evaluar el empalme.
- PIB antes de 2004: existe la base 1993 (`2.2_OGP_1993_T_17`), pero no está empalmada con la base 2004 y cubre el período intervenido.
- Si la API de series vuelve a publicar `452.3_RESULTADO_ERO_0_M_20_25`, reincorporarla como extra.
