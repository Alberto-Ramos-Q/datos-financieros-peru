# Ecuador (ECU) — fuentes

Script: `src/paises/ecu.py` · Series: `config/series/ECU.csv` (33 series: 22 comunes + 11 propias)
· Salida: `data/interim/ECU_observaciones.parquet`.

**Ecuador está dolarizado desde enero de 2000.** La moneda local es el dólar: no hay tipo de
cambio propio ni tasa de política monetaria, y los saldos y el PIB están en USD.

## Instituciones y accesos

| `fuente` | Institución | Acceso | Formato | Series |
|---|---|---|---|---|
| `bce_bcedata` | Banco Central del Ecuador (republica INEC, MEF, SENAE) | API REST pública de **BCEData**, sin clave. `https://contenido.bce.fin.ec/wp-json/bcedata/v1/bundle/<grupo>` da las series, frecuencias, unidades y el rango. `.../grid?id_grupo=&frecuencia=&unidad=&desde=&hasta=` da los datos. El árbol de grupos (cuadros de la IEM) está en `.../tree` | JSON | 26 |
| `bce_cnt` | BCE — Boletín de Cuentas Nacionales Trimestrales | Excel `tou_<nº>_<AAAAtt>.xlsx` (oferta y utilización) enlazado desde `https://contenido.bce.fin.ec/boletin-de-cuentas-nacionales-trimestrales/`; se toma el boletín de número mayor | Excel | 4 |
| `bce_imaec` | BCE — Índice Mensual de Actividad Económica (IMAEc) | Excel `IMAEc_<AAAAMM>.xlsx` enlazado desde `https://contenido.bce.fin.ec/imaec-cuadros-de-resultados/` | Excel | 2 |
| `bce_iem` | BCE — Información Estadística Mensual (cuadro 4.2.1, IPC del INEC) | `https://contenido.bce.fin.ec/documentos/PublicacionesNotas/Catalogo/IEMensual/m<nº>/IEM-421-e.xlsx`; la edición vigente (`m2095` = sep-2026) se toma de `https://contenido.bce.fin.ec/iem-publicaciones/` | Excel | 1 |

`codigo_fuente` en BCEData es `g<grupo>|<frecuencia>|<unidad>|<id_serie>`. El `id_serie` sale del
token base64 de la API (`'805:e02d…'`). Con ` + ` se suman dos códigos. En los Excel es
`archivo|hoja|columna[|xF]`. Ninguna fuente exige clave ni registro.

## Trampas encontradas

- **BCEData, grupo 4.2.1 (IPC), unidad «Indice»**: la fila «Índice General - IPC» trae en realidad
  la **variación acumulada en el año** (ago-2026 = 1,344, igual que la fila «Variación Acumulada»).
  El índice no está disponible en BCEData. Por eso `ipc_indice` sale del Excel IEM 4.2.1, que solo
  tiene datos desde 2020-01. Las variaciones mensual y anual sí son correctas en BCEData (desde
  2005/2006) y coinciden exactamente con el Excel.
- **Nueva base del IPC**: julio 2025-junio 2026 = 100, con la canasta ENIGHUR, vigente desde julio
  de 2026. El INEC empalmó la serie histórica; no hay salto por el cambio de base (las variaciones
  calculadas desde el índice coinciden con las publicadas).
- **INEC**: la sección de descargas del IPC está «temporalmente en mantenimiento» y los
  directorios de archivos devuelven 403. Por eso se usa la republicación del BCE.
- **Mismo `id_serie`, varias frecuencias y unidades**: por ejemplo, 2400 es mensual, trimestral y
  anual en % del PIB. Por eso el código incluye frecuencia y unidad, y cada combinación se guarda
  en su propio archivo crudo.
- La API a veces devuelve `values` como **texto con el repr de un diccionario de Python** en lugar
  de JSON. Se interpreta con `ast.literal_eval`, nunca con `eval`.
- Los periodos vienen como `'Ene 2000'`, `'2012-I'` y `'2012'`. El Excel del IMAEc usa
  `'2018.ene'` y el de CNT, `'2000.I'`.
- Los Excel de CNT, IMAEc e IEM **cambian de nombre cada publicación**. El script busca el enlace
  vigente y guarda el archivo con un nombre estable (`tou.xlsx`, `IMAEc.xlsx`, `IEM-421-e.xlsx`)
  para que `save_raw` versione los cambios.
- En el cuadro IEM 4.2.1 la cabecera del grupo es `' TOTAL  Ponderación: 100.0%'`. Además hay
  secciones de «Promedio anual» y «A diciembre» antes de las filas mensuales, que se identifican
  por el nombre del mes en la columna 2.
- CNT publica **miles de USD**: se multiplica por 0,001 para tener millones.
- **La variación interanual oficial (PIB trimestral e IMAEc) se calcula sobre la serie
  desestacionalizada.** El BCE no publica la de la serie original, que en 2026T2 es 1,55 % frente
  al 2,15 % oficial. Se usa la oficial, pero no es comparable con países que reportan la variación
  de la serie original.
- **Desempleo (ENEMDU)**: hasta 2013 es semestral, de 2014 a 2020 trimestral y desde 2021 mensual,
  así que hay meses sin dato. En 2020 hay un quiebre metodológico de la ENEMDU (ver INEC).
- La deuda interna pública salta +61 % en jun-2021 (17,7 a 28,5 mil millones). Coincide con el
  reconocimiento de la deuda del Gobierno con el BCE tras la reforma monetaria de 2021. Es un dato
  de la fuente, no un error de lectura.

## Cobertura obtenida (descarga del 2026-10-21)

| nombre_corto | indicador común | frecuencia | fuente | desde | hasta | n |
|---|---|---|---|---|---|---|
| pbi_real_trim | pbi_real_trim | trimestral | bce_cnt | 2000T1 | 2026T2 | 106 |
| pbi_real_var12m_trim | pbi_real_var12m_trim | trimestral | bce_cnt | 2001T1 | 2026T2 | 102 |
| pbi_desest_trim | pbi_desest_trim | trimestral | bce_cnt | 2000T1 | 2026T2 | 106 |
| actividad_mensual_indice | actividad_mensual_indice | mensual | bce_imaec | 2018-01 | 2026-08 | 104 |
| actividad_mensual_var12m | actividad_mensual_var12m | mensual | bce_imaec | 2019-01 | 2026-08 | 92 |
| pbi_nominal_anual | pbi_nominal_anual | anual | bce_bcedata | 1965 | 2025 | 61 |
| ipc_indice | ipc_indice | mensual | bce_iem | 2020-01 | 2026-09 | 81 |
| inflacion_mensual | inflacion_mensual | mensual | bce_bcedata | 2005-02 | 2026-08 | 259 |
| inflacion_12m | inflacion_12m | mensual | bce_bcedata | 2006-01 | 2026-08 | 248 |
| tasa_activa_promedio | tasa_activa_promedio | mensual | bce_bcedata | 2015-01 | 2026-10 | 142 |
| tasa_pasiva_promedio | tasa_pasiva_promedio | mensual | bce_bcedata | 2015-01 | 2026-10 | 142 |
| credito_privado | credito_privado | mensual | bce_bcedata | 2003-02 | 2026-08 | 283 |
| m2 | m2 | mensual | bce_bcedata | 2000-01 | 2026-08 | 320 |
| reservas_internacionales | reservas_internacionales | mensual | bce_bcedata | 2000-01 | 2026-09 | 321 |
| exportaciones | exportaciones | mensual | bce_bcedata | 1990-01 | 2026-08 | 440 |
| importaciones | importaciones | mensual | bce_bcedata | 1990-01 | 2026-08 | 440 |
| balanza_comercial | balanza_comercial | mensual | bce_bcedata | 1990-01 | 2026-08 | 440 |
| cuenta_corriente | cuenta_corriente | trimestral | bce_bcedata | 2016T1 | 2026T2 | 42 |
| resultado_fiscal_pct_pbi | resultado_fiscal_pct_pbi | anual | bce_bcedata | 2012 | 2025 | 14 |
| deuda_publica_pct_pbi | deuda_publica_pct_pbi | anual | bce_bcedata | 1996 | 2025 | 30 |
| desempleo | desempleo | mensual | bce_bcedata | 2007-12 | 2026-05 | 105 |
| salario_minimo | salario_minimo | mensual | bce_bcedata | 2005-01 | 2026-09 | 261 |
| riesgo_pais_embi | — | mensual | bce_bcedata | 2000-01 | 2026-09 | 321 |
| precio_crudo_oriente_napo | — | mensual | bce_bcedata | 2000-01 | 2026-08 | 320 |
| exportaciones_petroleras | — | mensual | bce_bcedata | 1990-01 | 2026-08 | 440 |
| m1 | — | mensual | bce_bcedata | 2000-01 | 2026-08 | 320 |
| base_monetaria | — | mensual | bce_bcedata | 2000-01 | 2026-08 | 320 |
| deuda_externa_publica | — | mensual | bce_bcedata | 2000-01 | 2026-08 | 320 |
| deuda_interna_publica | — | mensual | bce_bcedata | 2000-01 | 2026-07 | 319 |
| empleo_adecuado | — | mensual | bce_bcedata | 2007-12 | 2026-05 | 105 |
| desempleo_urbano | — | mensual | bce_bcedata | 2007-12 | 2026-05 | 105 |
| inflacion_alimentos_12m | — | mensual | bce_bcedata | 2006-01 | 2026-08 | 248 |
| pbi_desest_var_trim | — | trimestral | bce_cnt | 2000T2 | 2026T2 | 105 |

Notas de contenido:
- `reservas_internacionales`: las «Reservas Internacionales (RI)» del BCE, saldo bruto a fin de mes.
- Tasas activa y pasiva: las **referenciales** vigentes en el mes (BCEData 1.10.1, desde 2015). No
  son el promedio ponderado de todas las operaciones.
- `resultado_fiscal_pct_pbi`: resultado global del Sector Público No Financiero, base devengado
  (MEF/BCE), desde 2012.
- `deuda_publica_pct_pbi`: deuda **agregada** (sin consolidar) = deuda externa pública + deuda
  interna pública, ambas en % del PIB y publicadas por el BCE (2025: 39,7 + 26,6 = 66,3 %). El
  indicador legal del MEF es la deuda **consolidada**, más baja porque descuenta la deuda entre
  entidades públicas, y solo está en boletines PDF.
- `salario_minimo`: Salario Básico Unificado (SBU), 482 USD en 2026.
- `riesgo_pais_embi`: el índice lo calcula JP Morgan, pero el BCE lo publica como serie oficial
  en el cuadro IEM 3.4.3, a fin de mes.

## Indicadores comunes no cubiertos

| indicador | motivo |
|---|---|
| `tasa_politica` | No aplica: economía dolarizada, el BCE no tiene tasa de política monetaria. |
| `tc_usd_promedio`, `tc_usd_diario` | No aplica: la moneda de curso legal es el USD. |
| `tasa_interbancaria` | El BCE no publica una tasa interbancaria en BCEData ni en la IEM; el mercado interbancario es marginal. |
| `inflacion_subyacente_12m` | El INEC no publica una inflación subyacente oficial en las fuentes accesibles, y su sección del IPC está en mantenimiento. |
| `expectativa_inflacion_12m` | No hay encuesta oficial de expectativas de inflación (el BCE solo publica el Índice de Expectativas de la Economía, que no es de precios). |

## Validación (2026-10-21)

- **Reservas internacionales** sep-2026: 11.775,11 M USD, igual que el cuadro IEM 1.2.1 (edición
  m2095).
- **Comercio** ago-2026: exportaciones 3.509,10 e importaciones 3.298,14 M USD, iguales que el
  cuadro IEM 3.2.3.
- **Inflación** ago-2026: 12 meses 1,12 % y mensual 0,04 %, iguales que el cuadro IEM 4.2.1. En
  sep-2026 el IEM ya trae 1,34 % a 12 meses, pero BCEData todavía no lo incorpora.
- **Inflación calculada desde el índice** (IEM) frente a la publicada (BCEData), 2021-2026:
  diferencia máxima de 2e-14 pp, tanto en 12 meses como mensual. Confirma que no hay salto por la
  nueva base.
- **PIB**: los niveles brutos y desestacionalizados de CNT son coherentes (2026T2: 29.470 y 29.711
  M USD de 2018). El PIB nominal anual de 2025 es 130.321 M USD.
- **Saltos**: todos los cambios grandes tienen explicación económica (crisis de 2008-09 en el
  riesgo país, COVID en 2020, petróleo). La deuda interna de jun-2021 se documenta arriba.

## Pendientes

- Alargar `ipc_indice` antes de 2020 cuando el INEC reabra las descargas (serie histórica
  empalmada desde 2005). Otra opción es reconstruirlo desde la variación mensual oficial, pero
  sería un empalme propio.
- `cuenta_corriente`: BCEData solo publica la balanza de pagos MBP6 desde 2016. Buscar la serie
  2000-2015 en los boletines de balanza de pagos del BCE.
- Tasas referenciales anteriores a 2015: están en ediciones antiguas de la IEM y no en BCEData.
- Revisar si BCEData corrige la fila del índice del IPC; si lo hace, pasar `ipc_indice` a BCEData.

## Cómo actualizar

```
python src/paises/ecu.py                    # descarga todo y regenera el parquet
python src/paises/ecu.py --solo-procesar    # solo data/raw/ECU -> data/interim
python src/paises/ecu.py --serie ipc_indice desempleo   # descarga solo esas
```
