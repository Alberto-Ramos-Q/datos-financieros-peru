# Estados Unidos (USA): fuentes oficiales

Script: `src/paises/usa.py` · Series: `config/series/USA.csv` (35: 24 indicadores comunes + 11 extra) ·
Salida: `data/interim/USA_observaciones.parquet` · Descarga del 2026-10-21.

## Instituciones y acceso

| Fuente (`fuente`) | Institución | URL / acceso | Formato | Clave |
|---|---|---|---|---|
| `fed` | Federal Reserve Board, Data Download Program (H.15, H.10, H.8, H.6, G.17) | `https://www.federalreserve.gov/datadownload/Output.aspx?rel=<rel>&series=<md5>&filetype=csv&label=include&layout=seriescolumn&type=package` | CSV | No |
| `fed` | Federal Reserve Board, decisiones del FOMC | `https://www.federalreserve.gov/monetarypolicy/openmarket.htm` y `openmarket_archive.htm` | HTML | No |
| `bls` | Bureau of Labor Statistics, API pública **v1** | `POST https://api.bls.gov/publicAPI/v1/timeseries/data/` | JSON | No (v2 opcional con `BLS_API_KEY`) |
| `bea` | Bureau of Economic Analysis, archivos planos de NIPA | `https://apps.bea.gov/national/Release/TXT/NipaDataQ.txt` y `NipaDataA.txt` | CSV (se guarda .gz) | No |
| `bea` | BEA, tablas interactivas ITA/IIP | `POST https://apps.bea.gov/iTable/core/data/app/GetSteps` (appid 62) | JSON | No |
| `census` | Census Bureau, historia del FT-900 | `https://www.census.gov/foreign-trade/statistics/historical/exhibit_history.xlsx` | XLSX | No |
| `omb` | Office of Management and Budget, Historical Tables | índice `https://www.whitehouse.gov/omb/information-resources/budget/historical-tables/` → `hist01z2_fy<año>.xlsx`, `hist07z1_fy<año>.xlsx` | XLSX | No |
| `nyfed` | Federal Reserve Bank of New York, Survey of Consumer Expectations | `https://www.newyorkfed.org/medialibrary/interactives/sce/sce/downloads/data/frbny-sce-data.xlsx` | XLSX | No |
| `treasury` | U.S. Treasury, Fiscal Data API (Debt to the Penny) | `https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/debt_to_penny` | JSON | No |

No se usa FRED ni ningún agregador. **Ninguna serie requiere clave**: BEA y BLS v2 la piden para
su API, pero existen vías oficiales sin clave (archivos planos de BEA, tablas interactivas de BEA
y la API v1 de BLS).

## Archivos crudos (`data/raw/USA/`)
- `fed/<id>.csv`: una serie del DDP por archivo (`H15_H15_RIFSPFF_N.M.csv`); `fed/openmarket*.htm`.
- `bls/bls_<inicio>_<fin>.json`: bloques fijos de 10 años (1913-1922, …, 2023-2032) con todas las series BLS.
- `bea/NipaDataQ.txt.gz`, `bea/NipaDataA.txt.gz`: los archivos planos, comprimidos con gzip
  (sin pérdida; ~35 MB → 8 MB). `bea/ita_t1_1_qsa.json`, `bea/iip_t1_1_qnsa.json`.
- `census/exhibit_history.xlsx`, `omb/hist01z2.xlsx`, `omb/hist07z1.xlsx` (sin el año fiscal en el
  nombre, para que cada presupuesto reemplace al anterior y quede en el historial),
  `nyfed/frbny-sce-data.xlsx`, `treasury/debt_to_penny_p<página>.json`.

## Trampas encontradas
- **DDP de la Fed**: el parámetro `series` es el **md5 del «Unique Identifier»** de la serie
  (p. ej. `md5("H15/H15/RIFSPFF_N.M")`). No está documentado pero es estable y permite pedir
  cualquier serie sin armar paquetes en la web. El DDP a veces responde **200 con cuerpo vacío**
  (sobre todo con pedidos seguidos): se reintenta con espera creciente y se verifica que el CSV
  traiga la serie pedida. `ND` = sin dato (feriados): se descarta.
- **Paquetes completos del DDP** (`Output.aspx?rel=H15&filetype=zip`) existen, pero pesan 2-8 MB
  comprimidos por release y cambian a diario; solo se usaron para explorar códigos.
- **Tasa de política**: el DDP no trae el rango objetivo de los fondos federales. Se reconstruye
  desde la tabla de decisiones del FOMC: las fechas son de **entrada en vigor** (el recorte decidido
  el 31-jul-2019 figura el 1-ago), el nivel es un rango (`3.75-4.00`) o, hasta 2008, un objetivo
  puntual. Se toma el límite superior vigente al fin de cada mes, desde jul-1990 hasta el mes en
  curso. Las filas pueden traer notas (`March 4 *`).
- **BLS v1**: máximo 10 años y 25 series por petición, **25 peticiones por día y por IP**. Una
  corrida completa usa 12: no correr más de dos veces al día sin clave. Todas las series BLS van
  en las **mismas** peticiones (hoy 7 series por petición), así que agregar una serie no suma
  peticiones. Para una serie que empieza tarde, `--bls-desde AAAA` pide solo los bloques que llegan
  a ese año (LNU04000000 se agregó con `--bls-desde 1948`: 9 peticiones; los bloques 1913-1942
  quedaron como estaban y no la contienen, lo que es correcto porque no tiene datos antes de 1948). BLS **no publica las
  variaciones** como series: inflación mensual y de 12 meses se calculan desde el índice (así las
  calcula BLS). `M13` es el promedio anual y se ignora. El acceso a los archivos planos
  (`download.bls.gov`) devuelve 403 sin un User-Agent con correo de contacto: no se usa.
- **Oct-2025 sin IPC ni desempleo**: BLS no recogió datos por el cierre del gobierno federal (valor
  `-`). No se imputa: faltan ese mes en `ipc_indice`, `desempleo` y `desempleo_nsa`, y por eso faltan oct-2025 en
  `inflacion_12m`/`inflacion_subyacente_12m`, oct y nov-2025 en `inflacion_mensual`, y faltarán
  oct-2026 en las de 12 meses.
- **BEA sin clave**: la API exige registro; los archivos planos de NIPA son la vía oficial sin
  clave. El enlace «download all data» de las tablas ITA está roto (404); se usa el mismo
  servicio JSON que alimenta las tablas interactivas, pidiendo todos los años y todas las líneas. La
  línea se elige por número **y** se comprueba su rótulo: si BEA renumera, el procesamiento falla
  en vez de tomar otra línea.
- **PBI real sin desestacionalizar**: BEA solo lo publica desde 2002 (Tabla 8.1.6, a tasa
  trimestral, no anualizada). El nivel desestacionalizado (`A191RX`) está a **tasa anual (SAAR)**:
  no se puede comparar directamente con el NSA (≈ 4 veces mayor).
- **OMB**: la URL de cada tabla incluye el año del presupuesto (`_fy2027`), así que se busca en
  la página índice. Los años son **fiscales** (oct-sep); el presupuesto FY2027 trae datos efectivos
  hasta 2025 y, si en el futuro trae estimaciones, quedan fuera porque solo se leen filas con año
  de 4 dígitos (se descarta también el «TQ» de 1976).
- **OMB 7.1, columnas**: la tabla trae en millones (columnas 1-5) y en % del PIB (6-10) la deuda
  bruta, la tenida por cuentas del gobierno federal, la **en manos del público** (total, Reserva
  Federal y otros). `deuda_publica_pct_pbi` usa la columna 6 (bruta) y `deuda_publico_pct_pbi` la
  8 (en manos del público, total). El rótulo de la columna 8 se comprueba al procesar
  (`OMB_HEADER_CHECK`): si OMB reordena la tabla, el procesamiento falla en vez de tomar otra columna.
- **bls.gov bloquea clientes no navegador** (las tablas HTML de «The Employment Situation»
  devuelven una página de acceso denegado): la validación se hace contra la API oficial.
- **Census**: la hoja mezcla filas de año, «Jan. - Dec.» y meses; los meses futuros del año en
  curso vienen vacíos.
- **H.8 y H.6** son **promedios mensuales** (no fin de periodo). H.8 en millones; H.6 en miles
  de millones (se multiplica ×1000 con el sufijo `|x1000`).
- **Treasury**: la API devuelve dólares (se convierte a millones) y pagina de a 10 000 filas.

## Validación (2026-10-21)
- IPC sep-2026 contra la nota de BLS: índice NSA 336,940; 12 meses 3,7 % (calculado 3,74); mensual
  desestacionalizado 0,6 % (calculado 0,65); subyacente 2,6 % (calculado 2,56). Valores históricos
  calculados = publicados: jun-2022 9,1 %, dic-2022 6,5 %, dic-2024 2,9 %, mar-1980 14,8 %.
- Desempleo sep-2026 4,2 % y empleo no agrícola +29 mil, iguales a «The Employment Situation».
- `desempleo_nsa` (LNU04000000, agregada el 2026-10-21): sep-2026 4,0 %, ago-2026 4,3 % (respuesta de
  la API v1 del BLS). Coherencia con la desestacionalizada: en los 77 años completos el promedio anual
  NSA − SA es en media −0,0001 pp, con máximo |0,14| pp en 1949 y |0,03| pp desde 1990; correlación
  mensual 0,97. El patrón estacional es el esperado (enero +0,4 pp, abril −0,4 pp, julio +0,3 pp).
- `deuda_publico_pct_pbi` (OMB 7.1, col. 8, agregada el 2026-10-21): FY2025 99,5 %, FY2024 97,4 %. La
  diferencia con la bruta (123,3 % − 99,5 % = 23,8 pp) es igual a la columna 7 (tenida por cuentas del
  gobierno federal) en los 86 años, salvo redondeo (≤ 0,1 pp).
- Tasa de política: rango 3,75-4,00 % desde el 17-sep-2026 (límite superior 4,00). La EFFR mensual
  queda dentro del rango en los meses sin cambios (desvíos solo en meses con cambio a mitad de mes,
  p. ej. mar-2020).
- Saltos en niveles revisados: crédito +4,9 % en abr-2010 (consolidación de titulizaciones por
  FAS 166/167; H.8 publica los niveles sin ajustar por quiebres) y +6,4 % en ene-1958 (el CSV no
  lo explica; para crecimientos conviene usar las tasas «break adjusted» de H.8, p. ej.
  `B1020NCBCMG`); M2 +6,5 % en abr-2020 (pandemia, real). No hay cambios de base sin documentar: CPI-U
  base 1982-84, IP base 2017, índice dólar base ene-2006.

## Cobertura obtenida

| Serie (`nombre_corto`) | Común | Fuente | `codigo_fuente` | Frecuencia | Desde | Hasta | n |
|---|---|---|---|---|---|---|---|
| pbi_real_trim | sí | bea | `ND000334` | trimestral | 2002-T1 | 2026-T2 | 98 |
| pbi_real_var12m_trim | sí | bea | `A191RO` | trimestral | 1948-T1 | 2026-T2 | 314 |
| pbi_desest_trim | sí | bea | `A191RX` | trimestral | 1947-T1 | 2026-T2 | 318 |
| actividad_mensual_indice | sí | fed | `G17/IP_MAJOR_INDUSTRY_GROUPS/IP.B50001.N` | mensual | 1919-01 | 2026-09 | 1293 |
| actividad_mensual_var12m | sí | fed | `G17/IP_MAJOR_INDUSTRY_GROUPS/IP.B50001.N\|var12m` | mensual | 1920-01 | 2026-09 | 1281 |
| pbi_nominal_anual | sí | bea | `A191RC` | anual | 1929 | 2025 | 97 |
| ipc_indice | sí | bls | `CUUR0000SA0` | mensual | 1913-01 | 2026-09 | 1364 |
| inflacion_mensual | sí | bls | `CUUR0000SA0\|var1m` | mensual | 1913-02 | 2026-09 | 1362 |
| inflacion_12m | sí | bls | `CUUR0000SA0\|var12m` | mensual | 1914-01 | 2026-09 | 1352 |
| inflacion_subyacente_12m | sí | bls | `CUUR0000SA0L1E\|var12m` | mensual | 1958-01 | 2026-09 | 824 |
| tasa_politica | sí | fed | `fomc_target_upper` | mensual | 1990-07 | 2026-10 | 436 |
| tasa_interbancaria | sí | fed | `H15/H15/RIFSPFF_N.M` | mensual | 1954-07 | 2026-09 | 867 |
| tasa_activa_promedio | sí | fed | `H15/H15/RIFSPBLP_N.M` | mensual | 1949-01 | 2026-09 | 933 |
| credito_privado | sí | fed | `H8/H8/B1020NCBDM` | mensual | 1947-01 | 2026-09 | 957 |
| m2 | sí | fed | `H6/H6_M2/M2_N.M\|x1000` | mensual | 1959-01 | 2026-08 | 812 |
| expectativa_inflacion_12m | sí | nyfed | `SCE:Median one-year ahead expected inflation rate` | mensual | 2013-06 | 2026-09 | 160 |
| reservas_internacionales | sí | bea | `IIP T1.1 L11` | trimestral | 2006-T1 | 2026-T2 | 82 |
| exportaciones | sí | census | `FT900 exhibit_history: Exports Goods` | mensual | 1992-01 | 2026-08 | 416 |
| importaciones | sí | census | `FT900 exhibit_history: Imports Goods` | mensual | 1992-01 | 2026-08 | 416 |
| balanza_comercial | sí | census | `FT900 exhibit_history: Balance Goods` | mensual | 1992-01 | 2026-08 | 416 |
| cuenta_corriente | sí | bea | `ITA T1.1 L30` | trimestral | 1960-T1 | 2026-T2 | 266 |
| resultado_fiscal_pct_pbi | sí | omb | `hist01z2: Total Surplus or Deficit (-)` | anual | 1930 | 2025 | 96 |
| deuda_publica_pct_pbi | sí | omb | `hist07z1: Gross Federal Debt % GDP` | anual | 1940 | 2025 | 86 |
| desempleo | sí | bls | `LNS14000000` | mensual | 1948-01 | 2026-09 | 944 |
| desempleo_nsa | | bls | `LNU04000000` | mensual | 1948-01 | 2026-09 | 944 |
| deuda_publico_pct_pbi | | omb | `hist07z1: Debt Held by the Public % GDP` | anual | 1940 | 2025 | 86 |
| inflacion_mensual_desest | | bls | `CUSR0000SA0\|var1m` | mensual | 1947-02 | 2026-09 | 954 |
| indice_dolar_amplio | | fed | `H10/H10/JRXWTFB_N.M` | mensual | 2006-01 | 2026-09 | 249 |
| indice_dolar_amplio_diario | | fed | `H10/H10/JRXWTFB_N.B` | diaria | 2006-01-02 | 2026-10-16 | 5212 |
| usd_por_eur_diario | | fed | `H10/H10/RXI$US_N.B.EU` | diaria | 1999-01-04 | 2026-10-16 | 6969 |
| tasa_interbancaria_diaria | | fed | `H15/H15/RIFSPFF_N.B` | diaria | 1954-07-01 | 2026-10-19 | 18183 |
| bono_tesoro_10a | | fed | `H15/H15/RIFLGFCY10_N.M` | mensual | 1953-04 | 2026-09 | 882 |
| empleo_no_agricola | | bls | `CES0000000001` | mensual | 1939-01 | 2026-09 | 1053 |
| balanza_bienes_servicios | | census | `FT900 exhibit_history: Balance Total` | mensual | 1992-01 | 2026-08 | 416 |
| deuda_federal_total_diaria | | treasury | `debt_to_penny: tot_pub_debt_out_amt\|x0.000001` | diaria | 1993-04-01 | 2026-10-19 | 8416 |

Total: 58 554 observaciones.

`codigo_fuente` admite un sufijo de transformación tras `|`, que se aplica al procesar:
`var1m` y `var12m` (variación % frente al mes anterior / al mismo mes del año anterior; exige meses
contiguos) y `x<f>` (escala). Los códigos de BEA iTable, Census, OMB y NY Fed son rótulos legibles que
`usa.py` traduce a tabla/línea/columna (diccionarios `BEA_ITABLES`, `CENSUS_COLS`, `OMB_TABLES`).

### Decisiones y diferencias con el esquema común
- **tc_usd_promedio / tc_usd_diario: no aplican** (el dólar es la moneda local). En su lugar
  van como extras el índice del dólar amplio de la Fed (H.10, mensual y diario) y el USD por EUR
  diario de la Fed (útil para cruzar con España). No se mapea el índice al indicador común porque
  no es «moneda local por USD» y mezclaría unidades en las comparaciones entre países.
- **tasa_politica**: límite superior del rango objetivo (antes de dic-2008, objetivo puntual).
- **tasa_activa_promedio**: tasa *prime* (referencia de los bancos), no un promedio ponderado:
  EE.UU. no publica una tasa activa promedio del sistema.
- **actividad_mensual_***: producción industrial (G.17) sin desestacionalizar; la variación se
  calcula. EE.UU. no publica un indicador mensual de actividad de toda la economía.
- **credito_privado**: préstamos y leasing de todos los bancos comerciales (H.8), promedio mensual.
- **expectativa_inflacion_12m**: mediana a 1 año de la encuesta a consumidores de la Fed de
  Nueva York (banco de la Reserva Federal); desde jun-2013.
- **reservas_internacionales**: activos de reserva de la posición de inversión internacional
  (BEA), **trimestrales** desde 2006, brutos y con el oro a valor de mercado. El Tesoro publica la
  posición semanal solo como páginas HTML sueltas, sin serie descargable.
- **Comercio**: bienes, base balanza de pagos, desestacionalizado (FT-900); importaciones a valor
  aduanero (≈ FOB).
- **Fiscal**: gobierno **federal** (presupuesto unificado), año fiscal oct-sep; deuda bruta federal
  (incluye ~24 pp de deuda intragubernamental). La deuda **en manos del público** va como extra
  `deuda_publico_pct_pbi` (más cercana a la deuda consolidada de otros países).
- **desempleo**: nacional, desestacionalizada. La serie original (sin desestacionalizar, la
  comparable con los demás países) va como extra `desempleo_nsa` (LNU04000000).
- **inflacion_mensual**: desde el índice NSA, como en los demás países; la cifra titular
  desestacionalizada del BLS va como extra `inflacion_mensual_desest`.

## Indicadores comunes no cubiertos
| Indicador | Motivo |
|---|---|
| `tasa_pasiva_promedio` | No hay serie oficial vigente descargable: los CD de H.15 se discontinuaron en 2016 y las «national rates» de la FDIC solo se publican como páginas mensuales sueltas (sin archivo histórico). |
| `tc_usd_promedio`, `tc_usd_diario` | No aplican: el USD es la moneda local (ver extras del índice del dólar). |
| `salario_minimo` | El salario mínimo federal es por hora (7,25 USD desde jul-2009, no mensual) y la tabla histórica del Departamento de Trabajo (dol.gov) devuelve 403 a descargas automatizadas. |

## Pendientes
- Si BLS bloquea por exceso de peticiones (`REQUEST_NOT_PROCESSED`), esperar al día siguiente o
  definir `BLS_API_KEY` (registro gratuito en `https://data.bls.gov/registrationEngine/`; con clave
  se usa la API v2, 500 peticiones/día). El script nunca guarda la clave.
- El servicio JSON de las tablas interactivas de BEA no está documentado: si cambia, la alternativa
  oficial es la API de BEA con clave (`BEA_API_KEY`, registro en `https://apps.bea.gov/API/signup/`),
  que habría que implementar.
- Las reservas trimestrales podrían complementarse con la serie semanal del Tesoro si algún día
  se publica como archivo.

## Cómo actualizar
```
python src/paises/usa.py                        # descarga y procesa (~40 peticiones; 12 a BLS)
python src/paises/usa.py --serie tasa_politica  # solo esa descarga; el procesamiento es completo
python src/paises/usa.py --solo-procesar        # sin red
python src/paises/usa.py --serie desempleo_nsa --bls-desde 1948   # BLS solo desde el bloque 1943-1952 (9 peticiones)
```
Con `--serie`, pedir una serie BLS descarga igualmente todas las series BLS (comparten los
archivos por bloque de años); las series de BEA NIPA y de Census también comparten archivo.
