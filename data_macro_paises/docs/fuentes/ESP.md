# España (ESP): fuentes oficiales

Script: `src/paises/esp.py` · Series: `config/series/ESP.csv` (35: 27 indicadores comunes + 8 extra) ·
Salida: `data/interim/ESP_observaciones.parquet` · Descarga del 2026-10-21.

## Instituciones y acceso

| Fuente (`fuente`) | Institución | Acceso | Formato | Clave |
|---|---|---|---|---|
| `bde` | Banco de España: servicio web de estadísticas | API `https://app.bde.es/bierest/resources/srdatosapp/listaSeries?idioma=es&series=<código>&rango=MAX` ([documentación](https://www.bde.es/webbe/es/estadisticas/recursos/api-estadisticas-bde.html)) | JSON | No |
| `ine` | Instituto Nacional de Estadística: API Tempus | `https://servicios.ine.es/wstempus/js/ES/DATOS_SERIE/<código>?date=19000101:21001231` | JSON | No |

El BdE redistribuye, con su propio código, series de otros organismos oficiales: los tipos del
BCE y el €STR (Eurosistema), el comercio exterior (Departamento de Aduanas de la AEAT /
Ministerio de Economía), el déficit y la deuda PDE (IGAE / BdE) y el SMI (Ministerio de Trabajo).
No se usa ningún agregador.

Para buscar códigos del BdE sirve el archivo con todos los CSV del Boletín Estadístico,
`https://www.bde.es/webbe/es/estadisticas/compartido/datos/zip/be.zip` (cabeceras con código,
descripción, unidades y frecuencia; en latin-1), y los CSV de cada cuadro, p. ej.
`.../datos/csv/ti_1_7.csv` (mercado monetario). Para el INE: `TABLAS_OPERACION/<op>` y
`SERIES_TABLA/<tabla>`.

## Archivos crudos (`data/raw/ESP/`)
- `bde/<código>.json`: respuesta de `listaSeries` con `rango=MAX` (los caracteres raros del
  código se reemplazan por `_` en el nombre del archivo).
- `bde/DTCCBCEUSDEUR.B_<año>.json`: la serie diaria, un archivo por año (ver trampas).
- `ine/<código>.json`: respuesta de `DATOS_SERIE`.

## Trampas encontradas
- **BdE, rango**: sin `rango` la API devuelve solo 30 meses. `MAX` vale para mensuales,
  trimestrales y anuales; **para diarias el máximo es 36M**, así que se pide año por año
  (`rango=1999`, …). Cada respuesta anual trae además el 31-dic del año anterior: al procesar,
  cada archivo aporta solo las fechas de su año.
- **BdE, fechas**: vienen como `2026-09-01T08:15:00Z` (día 1 del periodo; la hora no significa
  nada) y en **orden descendente**.
- **BdE, valores nulos**: la serie diaria trae `null` en los festivos de TARGET (134
  descartados); no se imputan.
- **BdE, unidades**: el campo `simbolo` no es confiable (`DANPDE2010_PIBPM` dice «K EUR» pero
  está en millones). Las escalas se comprobaron por magnitud; crédito y reservas vienen en
  miles y se convierten con el sufijo `|x0.001`.
- **BdE, signo**: la serie anual `DANPDE2010_S0000P_APU` («capacidad o necesidad de
  financiación», % PIB) trae el **signo invertido** (2007: −1,9 cuando hubo superávit). Por eso
  `resultado_fiscal_pct_pbi` usa `DTNSEC2010_S0000P_APU_SUMAMOVIL` (suma móvil de 4 trimestres,
  con el signo correcto; el dato del T4 es el del año).
- **BdE, la API va comprimida** (gzip): `requests` la descomprime; con `curl` hace falta `--compressed`.
- **BdE, versión del PIB anual**: `DANPDE2010_PIBPM` (rotulada «CNE. Base 2016») coincide con
  la CNTR hasta 2022 pero usa una versión anterior para 2023-2025. Se descartó: `pbi_nominal_anual`
  es la suma de los cuatro trimestres de la CNTR del INE (`CNTR6548|sumanual`, solo años completos).
- **INE, rango**: sin parámetros `DATOS_SERIE` devuelve solo el último dato; se pide
  `date=19000101:21001231`.
- **INE, fechas**: algunos registros antiguos no traen `Fecha`; el periodo se arma con `Anyo` +
  `FK_Periodo` (1-12 meses, 19-22 trimestres, 28 año).
- **INE, cambio de base del IPC**: en enero de 2026 el INE pasó a **base 2025**. Las series base
  2021 (`IPC251852`, …) terminan en dic-2025; las nuevas (`IPC2907xx`, `IPC2925xx`) reescalan el
  índice desde 2002 y las tasas desde 1961/62, sin saltos. El índice arranca en 2002 porque el
  INE no publica el índice encadenado anterior en esa tabla.
- **INE, IPI**: la variación anual no existe para 1975 (12 nulos descartados).
- **API de la AEAT/DataComex**: no fue necesaria; el comercio exterior se toma del BdE.
- **BdE, bienes de la balanza de pagos solo trimestrales**: la balanza mensual (cuadro 17.3 del
  Boletín, `DEEM...`) publica **bienes y servicios juntos** (`T.C.GS` / `T.D.GS`) y turismo, pero no
  los bienes por separado (`DEEM...T.C.G...` → «La serie no existe»). Los bienes están en la
  trimestral (cuadro 17.4, `DEEQ.N.ES.W1.S1.S1.T.C.G._Z._Z._Z.EUR._T._X.N.ALL` ingresos y `T.D.G`
  pagos), desde 1993-T1. Se encontraron buscando en `catalogo_be.csv` del `be.zip`.
- **INE, «sin alimentos ni energía»**: el INE no publica un grupo que excluya solo alimentos y
  energía. El agregado oficial más cercano (tabla 76130, grupos especiales) es «General sin
  alimentos ni bebidas ni tabaco ni productos energéticos» (`IPC292478`, variación anual; índice
  `IPC292479`), equivalente al «sin energía, alimentos, alcohol ni tabaco» habitual en la zona euro.
  Excluye también bebidas y tabaco. No confundir con la subyacente (`IPC292510`), que solo excluye
  alimentos **no elaborados** y energía.

## Validación (2026-10-21)
- IPC sep-2026: 12 meses 4,9 %, mensual 0,3 %, subyacente 3,1 %; coincide con la nota de prensa
  del INE del 14-oct-2026. La tasa de 12 meses y la mensual **calculadas desde el índice**
  coinciden con las publicadas en los 285 meses comparables (diferencia máxima 0,0 y 0,1 pp por redondeo).
- Facilidad de depósito: 2,50 % desde el 16-sep-2026 (MRO 2,65 %); coincide con la tabla de tipos
  oficiales del BCE. La serie mensual es de **fin de mes** (jun-2024 = 3,75 tras el recorte del 12-jun).
- USD/EUR diario: 1,1590 el 1-sep-2026 y 1,1355 el 30-sep-2026, iguales a los tipos de referencia
  del BCE; la media de los diarios de septiembre (1,1513) es igual a la serie mensual `D_1PFJ1001`.
- PIB nominal: la suma trimestral de la CNTR coincide exactamente con el PIB anual de la PDE del BdE
  en 1995-2022.
- Saltos en niveles revisados: crédito +6,6 % en jun-2005 (Circular 4/2004: reincorporación de
  titulizaciones al balance) y −5,0 % en dic-2012 (traspaso de activos a la Sareb). Son
  **quiebres reales de la fuente, no se corrigen**. El IPI salta en septiembre por la
  estacionalidad de agosto (serie original). El SMI sube 22,3 % en ene-2019 (dato real).

Series agregadas el 2026-10-21 para la capa comparable:
- `exportaciones_bienes_bp` / `importaciones_bienes_bp`: 2026-T2 = 105 073 / 123 097 millones de EUR,
  iguales al cuadro 17.4 del Boletín Estadístico (`be1704.csv`). Frente al comercio aduanero (suma
  trimestral de `exportaciones` FOB e `importaciones` CIF): exportaciones BP / aduanas = 1,02 de
  mediana (0,98-1,08); importaciones BP (FOB) / aduanas (CIF) = 1,00 de mediana (0,96-1,06). Pese a
  la valoración FOB, las importaciones BP no quedan por debajo de las CIF: el BdE descuenta fletes y
  seguros pero suma ajustes de cobertura y de cambio de propiedad (bienes que no pasan por Aduanas)
  que lo compensan. Anual 2025: exportaciones 387,1 (aduanas) vs 391,5 (BP) mil millones; importaciones
  444,1 (CIF) vs 441,8 (BP FOB).
- `inflacion_sae_12m` (`IPC292478`): sep-2026 3,4 % (total 4,9 %, subyacente 3,1 %). La tasa calculada
  desde el índice `IPC292479` coincide con la publicada en los 285 meses comparables (±0,05 pp por
  redondeo). Correlación 0,96 con la subyacente y 0,72 con la total (2002-2026). **No siempre queda
  entre la total y la subyacente** (solo en 140 de 297 meses): al excluir también los alimentos
  elaborados queda en promedio 0,25 pp por debajo de la subyacente, y hasta 2,6 pp por debajo en
  dic-2022, cuando los alimentos elaborados subían a dos dígitos. Es el comportamiento esperado.

## Cobertura obtenida

| Serie (`nombre_corto`) | Común | Fuente | `codigo_fuente` | Frecuencia | Desde | Hasta | n |
|---|---|---|---|---|---|---|---|
| pbi_real_trim | sí | ine | `CNTR6721` | trimestral | 1995-T1 | 2026-T2 | 126 |
| pbi_real_var12m_trim | sí | ine | `CNTR6654` | trimestral | 1996-T1 | 2026-T2 | 122 |
| pbi_desest_trim | sí | ine | `CNTR6652` | trimestral | 1995-T1 | 2026-T2 | 126 |
| actividad_mensual_indice | sí | ine | `IPI13491` | mensual | 1975-01 | 2026-08 | 620 |
| actividad_mensual_var12m | sí | ine | `IPI13868` | mensual | 1976-01 | 2026-08 | 608 |
| pbi_nominal_anual | sí | ine | `CNTR6548\|sumanual` | anual | 1995 | 2025 | 31 |
| ipc_indice | sí | ine | `IPC290751` | mensual | 2002-01 | 2026-09 | 297 |
| inflacion_mensual | sí | ine | `IPC290752` | mensual | 1961-02 | 2026-09 | 788 |
| inflacion_12m | sí | ine | `IPC290750` | mensual | 1962-01 | 2026-09 | 777 |
| inflacion_subyacente_12m | sí | ine | `IPC292510` | mensual | 2002-01 | 2026-09 | 297 |
| tasa_politica | sí | bde | `D_1NBCEB72` | mensual | 1999-01 | 2026-09 | 333 |
| tasa_interbancaria | sí | bde | `D_1NBAA572` | mensual | 2019-10 | 2026-09 | 84 |
| tasa_activa_promedio | sí | bde | `D_1TI2TSINA` | mensual | 2003-01 | 2026-08 | 284 |
| tasa_pasiva_promedio | sí | bde | `D_1TI2TSINP` | mensual | 2003-01 | 2026-08 | 284 |
| credito_privado | sí | bde | `D_BFEA1000S\|x0.001` | mensual | 1962-01 | 2026-07 | 775 |
| m2 | sí | bde | `D_MESM2EELIPBIF` | mensual | 1997-09 | 2026-08 | 348 |
| tc_usd_promedio | sí | bde | `D_1PFJ1001` | mensual | 1979-01 | 2026-09 | 573 |
| tc_usd_diario | sí | bde | `DTCCBCEUSDEUR.B` | diaria | 1999-01-04 | 2026-10-16 | 7116 |
| reservas_internacionales | sí | bde | `DEEM.N.ES.W1.S121.S1.LE.A.FA.R.F._Z.EUR.X1._X.N.ALL\|x0.001` | mensual | 1987-01 | 2026-09 | 477 |
| exportaciones | sí | bde | `DXEXLIMPESA1GRU0000.M` | mensual | 1987-01 | 2026-07 | 475 |
| importaciones | sí | bde | `DXEMLIMPESA1GRU0000.M` | mensual | 1987-01 | 2026-07 | 475 |
| balanza_comercial | sí | bde | `DXESLIMPESA1GRU0000.M` | mensual | 1987-01 | 2026-07 | 475 |
| cuenta_corriente | sí | bde | `DEEQ.N.ES.W1.S1.S1.T.B.CA._Z._Z._Z.EUR._T._X.N.ALL` | trimestral | 1993-T1 | 2026-T2 | 134 |
| resultado_fiscal_pct_pbi | sí | bde | `DTNSEC2010_S0000P_APU_SUMAMOVIL` | trimestral | 1995-T4 | 2026-T2 | 123 |
| deuda_publica_pct_pbi | sí | bde | `DANPDE2010_P0000P_PS_APU` | anual | 1995 | 2025 | 31 |
| desempleo | sí | ine | `EPA452434` | trimestral | 2002-T1 | 2026-T2 | 98 |
| salario_minimo | sí | bde | `D_1LK00510` | mensual | 1980-06 | 2026-06 | 553 |
| tasa_bce_mro | | bde | `D_1TFK09A0_BCE` | mensual | 1999-01 | 2026-09 | 333 |
| eonia | | bde | `D_1NBAA372` | mensual | 2001-01 | 2021-12 | 252 |
| euribor_12m | | bde | `D_1NBAF472` | mensual | 1999-01 | 2026-09 | 333 |
| bono_10a | | bde | `D_G2B1I0ZP` | mensual | 1991-11 | 2026-09 | 419 |
| inflacion_acumulada_anio | | ine | `IPC290753` | mensual | 1962-01 | 2026-09 | 777 |
| exportaciones_bienes_bp | | bde | `DEEQ.N.ES.W1.S1.S1.T.C.G._Z._Z._Z.EUR._T._X.N.ALL` | trimestral | 1993-T1 | 2026-T2 | 134 |
| importaciones_bienes_bp | | bde | `DEEQ.N.ES.W1.S1.S1.T.D.G._Z._Z._Z.EUR._T._X.N.ALL` | trimestral | 1993-T1 | 2026-T2 | 134 |
| inflacion_sae_12m | | ine | `IPC292478` | mensual | 2002-01 | 2026-09 | 297 |

Total: 19 109 observaciones.

### Decisiones y diferencias con el esquema común
- **tasa_politica**: España no tiene tasa propia. Se usa el tipo de la **facilidad de depósito del
  BCE** (desde marzo de 2024 el BCE declara que orienta su política a través de ese tipo), en la
  versión publicada por el BdE. El tipo de las operaciones principales va como extra (`tasa_bce_mro`).
- **tasa_interbancaria**: €STR solo desde oct-2019; el EONIA (2001-2021) queda como extra `eonia`.
  No se empalman.
- **Moneda**: reservas, comercio y cuenta corriente están en **millones de EUR** (no USD), como
  publica la fuente; `tc_usd_*` está en **USD por EUR** (no EUR por USD).
- **Importaciones** CIF; exportaciones FOB. Para comparar FOB-FOB están los bienes de la balanza de
  pagos (`exportaciones_bienes_bp`, `importaciones_bienes_bp`), solo trimestrales y en EUR.
- **actividad_mensual_***: España no publica un indicador mensual de actividad de toda la
  economía; se usa el IPI general (serie original).
- **desempleo**: trimestral (EPA, 16 años y más). No hay tasa oficial mensual.
- **m2**: contribución española al M2 de la UEM, **sin efectivo** (el BCE no asigna billetes por país).
- **pbi_real_***: el INE publica el volumen encadenado como índice 2020=100, no en euros.

## Indicadores comunes no cubiertos
| Indicador | Motivo |
|---|---|
| `expectativa_inflacion_12m` | El BdE no hace una encuesta de expectativas de inflación. Las alternativas son de la zona euro (SPF y encuesta de consumidores del BCE) o privadas (panel de Funcas): no son una encuesta oficial española. |

## Pendientes
- Si se quisiera el IPC anterior a 2002 en nivel, habría que empalmar con las bases antiguas del INE
  (tablas «Series desde enero de 1961» solo traen tasas).
- Desempleo EPA anterior a 2002: el INE lo publica en tablas de bases antiguas (no se empalman).
- El crédito tiene los quiebres de 2005 y 2012 descritos arriba; si se usa para tasas de crecimiento,
  conviene usar las tasas ajustadas por operaciones del BdE (`be0319`), no los saldos.

## Cómo actualizar
```
python src/paises/esp.py                       # descarga y procesa (≈ 55 peticiones, 1 s de pausa)
python src/paises/esp.py --serie ipc_indice    # solo esa descarga; el procesamiento es completo
python src/paises/esp.py --solo-procesar       # sin red
```
Si el log avisa «el título no coincide», el organismo renombró o reutilizó el código: revisar
antes de usar el dato.
