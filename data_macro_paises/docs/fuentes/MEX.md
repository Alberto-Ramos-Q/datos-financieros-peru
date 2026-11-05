# México (MEX): fuentes de datos

Script: `src/paises/mex.py` · Configuración: `config/series/MEX.csv` (38 series: 27 comunes, 11 extra; 37 activas)
Crudos: `data/raw/MEX/<fuente>/` · Salida: `data/interim/MEX_observaciones.parquet`

## Instituciones y acceso

| Fuente (`fuente`) | Institución | URL | Acceso | Formato |
|---|---|---|---|---|
| `banxico_sie` | Banco de México, Sistema de Información Económica (SIE) | `https://www.banxico.org.mx/SieInternet/consultarDirectorioInternetAction.do?accion=consultarSeries` (POST, una serie por petición) | Exportación pública "Exportar series → CSV" del SIE, **sin token** | CSV en ISO-8859-1 con encabezado de metadatos |
| `shcp_datos` | SHCP (Unidad de Planeación Económica de la Hacienda Pública), datos abiertos de RFSP y SHRFSP | API CKAN de la Plataforma Nacional de Datos Abiertos: `https://www.datos.gob.mx/api/3/action/datastore_search?resource_id=<id>&filters={"clave_concepto":"<CLAVE>"}` (el `resource_id` se obtiene en cada corrida con `package_show?id=<conjunto>`) | Pública, sin clave | JSON |
| `inegi_bie` | INEGI, API del Banco de Indicadores (BIE) | `https://www.inegi.org.mx/app/api/indicadores/desarrolladores/jsonxml/INDICATOR/{id}/es/00/false/BIE/2.0/{token}?type=json` | API con **token** (`INEGI_TOKEN`) | JSON |

El SIE de Banxico republica con su propia clave las series oficiales de **INEGI** (PIB, IGAE, INPC, balanza comercial de mercancías) y de **SHCP** (ingresos, gastos y deuda del sector público). Se toman de ahí porque el SIE tiene una exportación CSV estable y sin token. El organismo originador queda anotado en `notas`.

Parámetros del POST (los mismos del formulario web): `series=<CLAVE>`, `anoInicial=` y `anoFinal=` vacíos (toda la historia), `tipoInformacion=4,1` (niveles) o `4,4` (tasa de crecimiento anual, que calcula el SIE), `formatoCSV.x/.y`. `idCuadro` puede ser cualquiera: la serie se exporta igual aunque no pertenezca a ese cuadro.

Formato de `codigo_fuente`:
- `SR17575`: la serie del SIE en niveles.
- `SR17575:var_anual`: la misma serie exportada como tasa de crecimiento anual. Se guarda como `SR17575__var_anual.csv`.
- `SG14/SR17645`: cociente calculado en el script a partir de dos series (ver más abajo).

### Token de INEGI (solo para desempleo)

La API de INEGI pide un token gratuito: se tramita con un registro de correo en `https://www.inegi.org.mx/servicios/api_indicadores.html` ("Obtén tu token"). Hay que guardarlo en la variable de entorno `INEGI_TOKEN`, poner `activo=1` en la fila `desempleo` de `MEX.csv` y correr `python src/paises/mex.py --serie desempleo`. El token **no** se escribe en el manifest. No se registró ninguna cuenta para este trabajo.

## Trampas encontradas

- **La API REST del SIE (`SieAPIRest`) y la del BIE de INEGI piden token.** La exportación CSV del formulario web del SIE no lo pide y entrega la historia completa.
- **"Fecha de consulta" en el CSV del SIE.** Cada exportación trae la línea `"Fecha de consulta: dd/mm/aaaa hh:mm:ss"`, así que el archivo nunca es idéntico byte a byte. `mex.py` compara el contenido sin esa línea antes de llamar a `save_raw`; si no, cada corrida versionaría las 31 series en `_control/historial/`.
- **`N/E` = sin dato.** Aparece en fines de semana, en meses sin encuesta y antes del inicio real de una serie (p. ej. Cetes 28 entre 1978 y 1982). Se descartan y el log cuenta cuántos hay por serie. No hay valores no numéricos de otro tipo.
- **El PIB trimestral de INEGI está a tasa anual.** Los niveles trimestrales (`SR17575`, `SR17622`, `SR17645`) son flujos anualizados: el PIB de un año es el **promedio** de sus 4 trimestres, no la suma. Comprobado: el promedio nominal de 2023 da 31.87 billones de MXN y la suma daría 127 billones. `pbi_nominal_anual` se calcula como ese promedio y solo para años con 4 trimestres.
- **Unidad mal rotulada en el SIE.** `SR17575` (PIB real original) dice "Pesos", pero la escala es de millones de pesos, igual que `SR17622` y `SR17645`.
- **Escalas en miles.** Crédito (`SF269832`) y M2 (`SF311418`) vienen en miles de pesos, y exportaciones, importaciones y balanza (`SE36593`, `SE36595`, `SE28294`) en miles de USD. Se dividen entre 1000 (diccionario `SCALE`).
- **Tasa objetivo.** Solo existe como serie diaria (`SF61745`, desde el 21-01-2008; antes Banxico usaba el "corto"). El valor mensual es el último dato del mes. El mes en curso queda con el último dato disponible.
- **Salario mínimo.** El SIE lo publica **por día** (`SL11298`, zona general, sin la Zona Libre de la Frontera Norte). No se convierte; el equivalente mensual de CONASAMI es × 30.4.
- **Reservas.** `SF29656` es la reserva internacional en la definición de la Ley del Banco de México (reserva bruta menos pasivos a menos de 6 meses): es neta. Los meses de enero a noviembre de 1995 vienen como N/E.
- **SHCP (Estadísticas Oportunas) no responde desde esta red.** Los dominios `finanzaspublicas.hacienda.gob.mx`, `secciones.hacienda.gob.mx` y `www.transparenciapresupuestaria.gob.mx` dan *timeout* de TCP (probado varias veces el 2026-10-21). Por eso `resultado_fiscal_pct_pbi` y `deuda_publica_pct_pbi` se **calculan** con series SHCP publicadas en el SIE (ver la sección de cortes).
- **RFSP y SHRFSP: solo por la API del datastore.** SHCP publica los conjuntos en `datos.gob.mx` (organización `secretaria_hacienda`), pero la URL de descarga del CSV (`repodatos.atdt.gob.mx/api_update/secretaria_hacienda/...`) responde **403 Access Denied** (Akamai) desde esta red, con o sin encabezados de navegador. El `datastore_search` de CKAN en `www.datos.gob.mx` sí responde y devuelve los mismos registros. Se filtra por `clave_concepto` para que cada respuesta sea pequeña (el conjunto RFSP tiene 43 mil filas y el límite por página es 32 000). Los montos vienen como texto, en **miles de pesos**, con el mes en letras. La API no publica el cociente en % del PIB: se calcula.
- **El SIE no tiene los RFSP.** El sector 9 (finanzas públicas) solo trae ingresos y gastos presupuestarios, deuda neta y el déficit por intermediación financiera (CF72).
- **Reserva bruta.** La "Reserva Internacional Bruta" del estado de cuenta (`SF43660`) es semanal y en pesos. La serie mensual en USD es la de activos de reserva oficiales de la plantilla del FMI (`SF110168`, cuadro CF456): en jul-2026 coincide exactamente con `SF43660` del 31-07-2026 dividido por el FIX (263 601,5 millones de USD).
- Consola de Windows: `comun.write_interim` registra el carácter `→`, que cp1252 no puede imprimir. El script reconfigura `stdout` a UTF-8 (no se modificó `comun.py`).

## Cortes metodológicos que hay que conocer

- **INPC (`SP1`).** Banxico lo encadena desde 1969 con base 2Q julio 2018 = 100. No hay saltos de base: la inflación mensual y la 12m calculadas desde el índice coinciden con las publicadas (diferencia 0.00 en todos los meses desde 2000).
- **PIB e IGAE.** Base 2018 de INEGI, con historia retropolada oficial desde 1993. No se empalma con bases anteriores.
- **Crédito al sector privado (`SF269832`).** Metodología 2018 del financiamiento de la banca comercial, desde 2009-07. Hay series de metodologías 2000 y 2016 en el SIE, pero no se empalman.
- **Indicadores fiscales CALCULADOS** (la fila lo dice en `notas`):
  - `resultado_fiscal_pct_pbi` = balance público presupuestario acumulado a diciembre (`SG14`) / PIB nominal anual × 100. Cobertura: sector público presupuestario (flujos de caja). **No** son los RFSP de SHCP.
  - `deuda_publica_pct_pbi` = deuda **neta** total del sector público económico amplio en diciembre (`SG193`, miles de millones × 1000) / PIB nominal anual × 100. No es deuda bruta ni el SHRFSP.
  - `rfsp_pct_pbi` = suma enero-diciembre de los RFSP del sector público federal (`RF000000SPFC`, SHCP, metodología vigente desde 2008, miles de pesos × 1e-3) / PIB nominal anual × 100. Solo años con 12 meses. **Signo de la fuente: negativo = requerimiento (déficit)**; los informes de SHCP lo presentan como número positivo ("RFSP de 5,7 % del PIB"). La metodología anterior (2001-2014, trimestral, `rfsp_metodologia_anterior`) no se empalma.
  - `shrfsp_pct_pbi` = SHRFSP de diciembre (`SHRF5000`, conjunto "SHRFSP - Deuda Amplia (2000-a la fecha)"; trimestral 2000-2013 y mensual desde 2014) / PIB nominal anual × 100. Es el saldo **neto** amplio (pasivos menos activos financieros) que SHCP usa como medida oficial de deuda.
  - El PIB de los cocientes es el vigente hoy en el SIE (INEGI, base 2018). SHCP calculó sus cocientes con el PIB disponible en cada momento: pueden diferir unas décimas.

## Validación (descarga del 2026-10-21)

| Dato | Parquet | Publicación oficial | OK |
|---|---|---|---|
| Tasa objetivo vigente (21-10-2026) | 6.50 | 6.50 (portada de Banxico, canal `singleTasaObj`) | sí |
| FIX del 20-10-2026 | 18.4200 | 18.4200 (portada de Banxico, `singleFix`) | sí |
| Inflación anual, septiembre de 2026 | 3.45 | 3.45 (portada de Banxico, `singleInflacion`) | sí |
| Inflación subyacente anual, septiembre de 2026 | 3.75 | 3.75 (portada de Banxico, `singleInflacionSub`) | sí |
| TIIE de fondeo | 6.52 (promedio de sep-2026) | 6.52 (dato diario del 20-10-2026) | coherente |

Controles de consistencia:
- **Inflación 12m calculada desde `ipc_indice`** frente a `SP30578`: diferencia de 0.00 desde 2000 (con redondeo a 2 decimales, como la fuente). Lo mismo con la inflación mensual.
- **PIB real:** la variación interanual calculada desde `pbi_real_trim` coincide con `pbi_real_var12m_trim` (la exportada por el SIE) en ±0.1 pp.
- **Escala del PIB anual:** el promedio de 2023 da 31.87 billones de MXN corrientes (ver la trampa del PIB anualizado).
- **Fiscales:** el balance de 2024 da −4.97 % del PIB y la deuda neta 46.2 %, órdenes de magnitud coherentes con lo que publica SHCP (que usa otra cobertura).
- **RFSP frente al balance presupuestario:** `rfsp_pct_pbi − resultado_fiscal_pct_pbi` promedia −0,85 pp en 2008-2025 (entre +0,02 y −1,79 pp; 2024: −5,76 frente a −4,97). Es la diferencia esperada de ~1 pp por la cobertura amplia (IPAB, FARAC, Pidiregas, banca de desarrollo y adecuaciones).
- **RFSP oficial:** 2024 = −5,76 % y 2023 = −4,30 % del PIB; SHCP informó RFSP de 5,7 % y 4,3 % del PIB.
- **SHRFSP oficial:** 2024 = 51,9 % y 2023 = 46,6 % del PIB; SHCP/CEFP reportaron 51,4 % y 46,8 %. La diferencia (≤0,5 pp) viene del PIB revisado que se usa aquí.
- **Reservas:** `reservas_brutas` ≥ `reservas_internacionales` en los 320 meses comunes (mínimo +773 millones de USD en nov-2015; ago-2026: 265 970,6 frente a 258 478,7).

## Cobertura obtenida

| nombre_corto | indicador común | frecuencia | desde | hasta | n |
|---|---|---|---|---|---|
| actividad_mensual_indice | actividad_mensual_indice | mensual | 1993-01 | 2026-07 | 403 |
| actividad_mensual_var12m | actividad_mensual_var12m | mensual | 1994-01 | 2026-07 | 391 |
| balanza_comercial | balanza_comercial | mensual | 1980-01 | 2026-08 | 560 |
| credito_privado | credito_privado | mensual | 2009-07 | 2026-08 | 206 |
| cuenta_corriente | cuenta_corriente | trimestral | 2002-T1 | 2026-T2 | 98 |
| deuda_publica_pct_pbi | deuda_publica_pct_pbi | anual | 1993 | 2025 | 33 |
| expectativa_inflacion_12m | expectativa_inflacion_12m | mensual | 1999-01 | 2026-09 | 327 |
| exportaciones | exportaciones | mensual | 1993-01 | 2026-08 | 404 |
| importaciones | importaciones | mensual | 1993-01 | 2026-08 | 404 |
| inflacion_12m | inflacion_12m | mensual | 1970-01 | 2026-09 | 681 |
| inflacion_mensual | inflacion_mensual | mensual | 1969-02 | 2026-09 | 692 |
| inflacion_subyacente_12m | inflacion_subyacente_12m | mensual | 1983-01 | 2026-09 | 525 |
| ipc_indice | ipc_indice | mensual | 1969-01 | 2026-09 | 693 |
| m2 | m2 | mensual | 2000-12 | 2026-08 | 309 |
| pbi_desest_trim | pbi_desest_trim | trimestral | 1993-T1 | 2026-T2 | 134 |
| pbi_nominal_anual | pbi_nominal_anual | anual | 1993 | 2025 | 33 |
| pbi_real_trim | pbi_real_trim | trimestral | 1993-T1 | 2026-T2 | 134 |
| pbi_real_var12m_trim | pbi_real_var12m_trim | trimestral | 1994-T1 | 2026-T2 | 130 |
| reservas_internacionales | reservas_internacionales | mensual | 1995-12 | 2026-09 | 370 |
| reservas_brutas | — | mensual | 2000-01 | 2026-08 | 320 |
| resultado_fiscal_pct_pbi | resultado_fiscal_pct_pbi | anual | 1993 | 2025 | 33 |
| rfsp_pct_pbi | — | anual | 2008 | 2025 | 18 |
| shrfsp_pct_pbi | — | anual | 2000 | 2025 | 26 |
| salario_minimo | salario_minimo | mensual | 1964-01 | 2026-09 | 753 |
| tasa_interbancaria | tasa_interbancaria | mensual | 2006-01 | 2026-09 | 249 |
| tasa_pasiva_promedio | tasa_pasiva_promedio | mensual | 1975-08 | 2026-09 | 614 |
| tasa_politica | tasa_politica | mensual | 2008-01 | 2026-10 | 226 |
| tc_usd_diario | tc_usd_diario | diaria | 1991-11-12 | 2026-10-20 | 8782 |
| tc_usd_promedio | tc_usd_promedio | mensual | 1991-01 | 2026-09 | 429 |
| balance_publico_acum | — | mensual | 1977-01 | 2026-08 | 596 |
| ccp_mn | — | mensual | 1996-02 | 2026-09 | 368 |
| cetes_28_promedio | — | mensual | 1982-09 | 2026-09 | 511 |
| deuda_neta_spea | — | mensual | 1980-01 | 2026-07 | 559 |
| igae_desest | — | mensual | 1993-01 | 2026-07 | 403 |
| pib_nominal_trim | — | trimestral | 1993-T1 | 2026-T2 | 134 |
| remesas | — | mensual | 1995-01 | 2026-08 | 380 |
| tiie_28_promedio | — | mensual | 1995-03 | 2026-09 | 379 |

## Indicadores comunes no cubiertos

- `tasa_activa_promedio`: Banxico no publica una tasa activa promedio del sistema. El SIE solo tiene tasas por segmento (tarjetas, consumo no revolvente, CAT hipotecario), y ninguna representa el total.
- `desempleo`: la tasa de desocupación nacional de la ENOE solo está en el BIE/API de INEGI, que pide token. Está configurada con `activo=0` y lectura desde `INEGI_TOKEN`. **El código BIE `444612` está pendiente de confirmar** con el token: no se pudo verificar sin él. En el SIE solo existe la tasa urbana de la ENEU (`SL1`), que llega hasta 2005.

## Pendientes

- Obtener `INEGI_TOKEN`, confirmar el id BIE de la tasa de desocupación nacional mensual (ENOE, 15 años y más) y activar `desempleo`.
- Los RFSP y el SHRFSP ya están como series propias (`rfsp_pct_pbi`, `shrfsp_pct_pbi`, desde la API de datos.gob.mx). Decidir (y documentar) si reemplazan a `resultado_fiscal_pct_pbi` y `deuda_publica_pct_pbi` como indicadores comunes; no se cambió la definición vigente.
- Si el CSV de `repodatos.atdt.gob.mx` o Estadísticas Oportunas vuelven a responder, se pueden descargar los cocientes en % del PIB publicados por SHCP para contrastar.
- Opcional: empalmar el crédito con las metodologías 2000 y 2016 para tener historia antes de 2009.
