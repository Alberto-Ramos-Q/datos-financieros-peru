# Colombia (COL) — fuentes

Script: `src/paises/col.py` · Series: `config/series/COL.csv` (42 series: 28 comunes + 14 propias)
· Salida: `data/interim/COL_observaciones.parquet`.

## Instituciones y accesos

| `fuente` | Institución | Acceso | Formato | Series |
|---|---|---|---|---|
| `banrep_suameca` | Banco de la República (republica también datos de DANE, MinHacienda, Superfinanciera y MinTrabajo) | REST público del portal SUAMECA, sin clave: `https://suameca.banrep.gov.co/estadisticas-economicas-back/rest/estadisticaEconomicaRestService/consultaInformacionSerie?idSerie=N` (historia completa). Variaciones calculadas por el servicio: `consultaInformacionSerieXTipoDato?idSerie=N&tipoDato=11&cantDatos=100000` | JSON | 35 |
| `banrep_sdmx` | Banco de la República | Servicio SDMX 2.1 oficial: `https://totoro.banrep.gov.co/nsi-jax-ws/rest/data/ESTAT,DF_IR_MONTHLY_HIST,1.0/all/ALL/` | XML SDMX genérico | 1 |
| `banrep_eme` | Banco de la República — Encuesta mensual de expectativas de analistas económicos | Descarga directa `https://suameca.banrep.gov.co/archivos/encuestas/encuesta_mensual_analistas_economicos/series_historicas.xlsx` | Excel | 1 |
| `dane` | DANE (ISE; balanza comercial con DIAN; IPC sin alimentos ni energéticos) | Excel enlazado desde las páginas temáticas del DANE; el script busca el enlace vigente. El anexo general del IPC (`anex-IPC-<mes><año>.xlsx`) solo se enlaza desde la página *IPC información técnica* | Excel | 6 |

Catálogo de SUAMECA (853 series, para elegir series nuevas):
`https://suameca.banrep.gov.co/buscador-de-series/rest/buscadorSeriesRestService/listarSeriesXCategoria` (JSON).
Ninguna fuente exige clave ni registro.

`codigo_fuente` en SUAMECA es el `idSerie`, con transformaciones opcionales tras `|`
(`x1000`, `promedio_mensual`, `fin_de_mes`, `anual_a_mensual`, `tipoDato=11`,
`suma_anual_pct_pib:15291`, `div_fin_de_mes:1`) o `ID+ID` para sumar. En los Excel: `archivo|hoja|bloque o columna|fila`.

## Trampas encontradas

- **Certificado TLS incompleto en suameca.banrep.gov.co**: el servidor envía solo la hoja y la
  raíz, sin el intermedio *GeoTrust EV RSA CA G2*. Los navegadores y Windows lo completan solos,
  pero `requests` falla con `CERTIFICATE_VERIFY_FAILED`. `col.py` descarga el intermedio desde su
  URL AIA oficial (`http://cacerts.digicert.com/GeoTrustEVRSACAG2.crt`) y lo añade al contexto TLS
  solo para ese host. La verificación sigue activa. `comun.Client` no permite pasar un contexto SSL,
  así que se monta un `HTTPAdapter` sobre `client.session`.
- **Fechas en milisegundos epoch** a medianoche de Bogotá (05:00 UTC). Entre el 3 de mayo de 1992
  y el 3 de abril de 1993 hubo horario de verano (04:00 UTC). Si se trunca al día se obtiene el día
  anterior y fechas repetidas en la TRM, así que se resta 5 h y se **redondea** al día.
- Las series mensuales vienen fechadas el último día del mes y las anuales el 31-dic (la deuda, el
  1-dic). Todo se normaliza con `period_start`.
- **Índice IPC con 2 decimales** (base dic-2018=100): antes de 1980 el nivel es menor que 1 y
  calcular variaciones desde el índice da errores de hasta 25 pp. Por eso `inflacion_mensual` usa la
  variación que calcula el propio servicio (`tipoDato=11`, con precisión completa) e
  `inflacion_12m` la serie publicada 15270.
- **ISE del DANE**: el nombre del archivo cambia cada mes (`anex-ISE-9actividades-ago2026.xlsx`).
  Los años preliminares vienen como texto (`2024p`, `2026pr`) y solo en la columna de enero. Un
  primer parser que los leía como número asignaba 2024-2026 a 2023 sin dar error. Ahora se extraen
  los 4 dígitos y se valida que no haya meses repetidos ni huecos.
- La hoja del ISE tiene tres bloques (índice, variación anual, año corrido). Se localizan por el
  título sobre la fila «Concepto» y la fila «Indicador de Seguimiento a la Economía», no por posición.
- La **EME** publica fracciones (0,054): se multiplica por 100. En sep-2003 solo hay promedio, sin
  mediana, así que la serie empieza en oct-2003.
- **TRM**: se publica todos los días calendario e incluye la del día siguiente. `tc_usd_promedio`
  es el promedio simple de los días del mes. Se descartan el primer mes, que está incompleto
  (empieza el 27-nov-1991), y el mes en curso. `tasa_politica` toma el último dato de cada mes,
  también sin el mes en curso.
- El salario mínimo es anual y rige de enero a diciembre: se repite en cada mes del año, hasta el
  mes en curso.
- **Cartera en moneda extranjera solo en pesos.** SUAMECA publica la cartera en ME **expresada en
  COP** (id 376, y sus componentes 364, 366, 368, 370, 372, 374); no hay serie en USD.
  `credito_privado_me_usd` la convierte con la TRM vigente el último día del mes (último dato
  diario del id 1, que se publica todos los días calendario). Es una conversión propia, no un dato
  publicado.
- **Medidas subyacentes.** BanRep publica sin alimentos (15388), sin alimentos ni regulados (15390),
  núcleo 15 y 20, y sin alimentos primarios, servicios públicos y combustibles (15402), pero no
  "sin alimentos ni energía". Esa medida la produce el **DANE** desde 2019 (COICOP: IPC sin la
  división 01 y sin energéticos) y la publica en la hoja 12 del anexo general del IPC, con historia
  desde 2009-01. El DANE define los energéticos como gas y energía eléctrica para el hogar y
  combustibles para vehículo.
- `www.banrep.gov.co` está detrás de un bloqueador anti-bots (ShieldSquare). Todo lo necesario se
  obtiene de `suameca.banrep.gov.co` y `totoro.banrep.gov.co`, que no lo tienen.

## Cobertura obtenida (descarga del 2026-10-21)

| nombre_corto | indicador común | frecuencia | fuente | desde | hasta | n |
|---|---|---|---|---|---|---|
| pbi_real_trim | pbi_real_trim | trimestral | banrep_suameca | 2005T1 | 2026T2 | 86 |
| pbi_real_var12m_trim | pbi_real_var12m_trim | trimestral | banrep_suameca | 2006T1 | 2026T2 | 82 |
| pbi_desest_trim | pbi_desest_trim | trimestral | banrep_suameca | 2005T1 | 2026T2 | 86 |
| actividad_mensual_indice | actividad_mensual_indice | mensual | dane | 2005-01 | 2026-08 | 260 |
| actividad_mensual_var12m | actividad_mensual_var12m | mensual | dane | 2006-01 | 2026-08 | 248 |
| pbi_nominal_anual | pbi_nominal_anual | anual | banrep_suameca | 1975 | 2025 | 51 |
| ipc_indice | ipc_indice | mensual | banrep_suameca | 1954-07 | 2026-09 | 867 |
| inflacion_mensual | inflacion_mensual | mensual | banrep_suameca | 1954-08 | 2026-09 | 866 |
| inflacion_12m | inflacion_12m | mensual | banrep_suameca | 1955-07 | 2026-09 | 855 |
| inflacion_subyacente_12m | inflacion_subyacente_12m | mensual | banrep_suameca | 1983-03 | 2026-09 | 523 |
| tasa_politica | tasa_politica | mensual | banrep_suameca | 1998-02 | 2026-09 | 344 |
| tasa_interbancaria | tasa_interbancaria | mensual | banrep_sdmx | 1995-03 | 2026-09 | 379 |
| tasa_activa_promedio | tasa_activa_promedio | mensual | banrep_suameca | 2002-05 | 2026-09 | 293 |
| tasa_pasiva_promedio | tasa_pasiva_promedio | mensual | banrep_suameca | 1986-01 | 2026-09 | 489 |
| credito_privado | credito_privado | mensual | banrep_suameca | 2002-05 | 2026-09 | 293 |
| m2 | m2 | mensual | banrep_suameca | 1984-01 | 2026-09 | 513 |
| expectativa_inflacion_12m | expectativa_inflacion_12m | mensual | banrep_eme | 2003-10 | 2026-10 | 277 |
| tc_usd_promedio | tc_usd_promedio | mensual | banrep_suameca | 1991-12 | 2026-09 | 418 |
| tc_usd_diario | tc_usd_diario | diaria | banrep_suameca | 1991-11-27 | 2026-10-21 | 12748 |
| reservas_internacionales | reservas_internacionales | mensual | banrep_suameca | 1960-01 | 2026-09 | 801 |
| exportaciones | exportaciones | mensual | dane | 2007-01 | 2026-08 | 236 |
| importaciones | importaciones | mensual | dane | 2007-01 | 2026-08 | 236 |
| balanza_comercial | balanza_comercial | mensual | dane | 2007-01 | 2026-08 | 236 |
| cuenta_corriente | cuenta_corriente | trimestral | banrep_suameca | 2000T1 | 2026T2 | 106 |
| resultado_fiscal_pct_pbi | resultado_fiscal_pct_pbi | anual | banrep_suameca | 2004 | 2025 | 22 |
| deuda_publica_pct_pbi | deuda_publica_pct_pbi | anual | banrep_suameca | 1995 | 2025 | 31 |
| desempleo | desempleo | mensual | banrep_suameca | 2001-01 | 2026-08 | 308 |
| salario_minimo | salario_minimo | mensual | banrep_suameca | 1984-01 | 2026-10 | 514 |
| ibr_overnight | — | diaria | banrep_suameca | 2008-01-02 | 2026-10-21 | 4585 |
| ibr_3m | — | diaria | banrep_suameca | 2012-08-01 | 2026-10-21 | 3466 |
| tes_cero_cupon_10a | — | diaria | banrep_suameca | 2003-01-02 | 2026-10-16 | 5787 |
| tasa_credito_consumo | — | mensual | banrep_suameca | 2002-05 | 2026-09 | 293 |
| m1 | — | mensual | banrep_suameca | 1984-01 | 2026-09 | 513 |
| base_monetaria | — | mensual | banrep_suameca | 1984-01 | 2026-09 | 513 |
| itcr_ipc | — | mensual | banrep_suameca | 1986-12 | 2026-09 | 478 |
| remesas_ingresos | — | mensual | banrep_suameca | 2000-01 | 2026-08 | 320 |
| terminos_intercambio | — | mensual | banrep_suameca | 1995-01 | 2026-07 | 379 |
| tasa_ocupacion | — | mensual | banrep_suameca | 2001-01 | 2026-08 | 308 |
| reservas_brutas | — | mensual | banrep_suameca (15050) | 1960-01 | 2026-09 | 801 |
| credito_privado_mn | — | mensual | banrep_suameca (375) | 2002-05 | 2026-09 | 293 |
| credito_privado_me_usd | — | mensual | banrep_suameca (376 / TRM fin de mes) | 2002-05 | 2026-09 | 293 |
| inflacion_sae_12m | — | mensual | dane (anex-IPC, hoja 12) | 2010-01 | 2026-09 | 201 |

Unidades: los saldos en pesos se pasan de miles de millones a **millones COP** (`x1000`) para
seguir `indicadores_comunes.csv`. El crédito privado es la cartera bruta en moneda legal más la
cartera en moneda extranjera expresada en pesos (ids 375 + 376). Las reservas son **netas**
(`reservas_internacionales`); las brutas (`reservas_brutas`, id 15050) incluyen el FLAR.
Las importaciones son **FOB**.

## Indicadores comunes no cubiertos o cubiertos con reservas

Están los 28. Cuatro tienen reservas:
- `resultado_fiscal_pct_pbi` es un **cálculo propio** con dos series oficiales: la suma anual del
  balance mensual del Gobierno Nacional Central en base caja (MHCP, id 16725) dividida por el PIB
  nominal anual (DANE, id 15291). Sale de 2004 a 2025, solo con años completos. Difiere del balance
  oficial del Marco Fiscal de Mediano Plazo (base causación) hasta en ~1 pp: 2019 −2,2 frente a
  −2,5, y 2011 −2,0 frente a −2,8. La serie oficial en % del PIB del BanRep (id 15327) se cortó en
  2019, y MinHacienda no publica una serie descargable: su portal es Oracle WebCenter.
- La variación anual del PIB y del ISE se calcula sobre la serie original, no la desestacionalizada.
- `tasa_activa_promedio` es la tasa de colocación total, desde 2002. `tasa_pasiva_promedio` es la
  DTF a 90 días, la tasa pasiva de referencia del país.
- Las exportaciones e importaciones mensuales del DANE empiezan en 2007 en el anexo de balanza
  comercial. Hay series de exportaciones desde 1970, pero son anuales por país.

## Validación (2026-10-21)

- **TRM** del 2026-10-21: 3.163,76 en SUAMECA y en el SDMX `DF_TRM_DAILY_LATEST`. Coinciden.
- **Tasa de política**: el último dato diario es 12,25 % (2026-10-21) y coincide con el SDMX
  `DF_CBR_DAILY_LATEST`. La mensual de sep-2026 es 12,00 %, el último día de ese mes.
- **IPC sep-2026**: el índice es 161,00 en SUAMECA y en el anexo oficial del DANE
  (`anex-IPC-Indices-sep2026.xlsx`). La inflación a 12 meses publicada es 6,29 %. Calculada desde el
  índice, da 6,285 % (6,28 % con el índice de 2 decimales del DANE): la diferencia es de redondeo.
- **12 meses desde el índice frente a la publicada**: diferencia máxima de 0,023 pp desde 2000 y de
  1,2 pp en 1980-1999. Antes de 1980 es grande por el redondeo del índice; para esos años usar la
  serie publicada. La variación mensual de `tipoDato=11` coincide con la del índice (≤0,017 pp
  desde 2000).
- **Series agregadas para la capa comparable:**
  - `reservas_brutas` ≥ `reservas_internacionales` en 787 de 801 meses; los 14 restantes
    (1988-1998) son diferencias de redondeo de ≤0,25 millones de USD. Desde 2016 la diferencia
    media es de 14 millones (sep-2026: 67 250,5 brutas frente a 67 228,0 netas).
  - `credito_privado_mn` + `credito_privado_me_usd` × TRM de fin de mes reproduce `credito_privado`
    exactamente (por construcción; diferencia relativa < 1e-15). Sep-2026: 776,8 billones COP en MN y
    4 218 millones USD en ME (TRM 3 341,23).
  - `inflacion_sae_12m`: sep-2026 = 6,48 % y coincide con la calculada desde el índice publicado
    (150,80 / 141,62). Correlación de 0,995 con la sin alimentos ni regulados (6,03 %).
- **Saltos**: se revisaron los cambios mayores a 50 %. Todos tienen explicación económica (COVID
  en 2020, cambios de signo en saldos) y no hay saltos por cambio de base. El ISE (año de referencia
  2015), el PIB (base 2015 desde 2005) y el IPC (base dic-2018) son series empalmadas por la fuente.

## Pendientes

- Si MinHacienda publica en formato descargable el balance del GNC en % del PIB (base causación),
  reemplazar el cálculo propio.
- Para alargar el comercio exterior mensual antes de 2007, revisar los anexos históricos del DANE
  o las series de la balanza de pagos del BanRep.
- El certificado intermedio se descarga en cada corrida. Si DigiCert cambia la URL AIA, actualizar
  `SUAMECA_INTERMEDIATE_URL`; aparece en el detalle del certificado del sitio.

## Cómo actualizar

```
python src/paises/col.py                    # descarga todo y regenera el parquet
python src/paises/col.py --solo-procesar    # solo data/raw/COL -> data/interim
python src/paises/col.py --serie tc_usd_diario tasa_politica   # descarga solo esas
```
