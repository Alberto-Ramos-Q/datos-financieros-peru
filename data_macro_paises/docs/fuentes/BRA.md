# Brasil (BRA): fuentes de datos

Script: `src/paises/bra.py` · Configuración: `config/series/BRA.csv` (37 series: 28 comunes y 9 extra)
Crudos: `data/raw/BRA/{bcb_sgs,ibge_sidra,bcb_focus}/` · Salida: `data/interim/BRA_observaciones.parquet`

## Instituciones y acceso

| Fuente (`fuente`) | Institución | URL | Acceso | Formato |
|---|---|---|---|---|
| `BCB-SGS` | Banco Central do Brasil, Sistema Gerenciador de Séries Temporais | `https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados?formato=json` | API pública, sin clave | JSON `[{"data": "dd/mm/aaaa", "valor": "x"}]` |
| `IBGE-SIDRA` | Instituto Brasileiro de Geografia e Estatística, SIDRA | `https://apisidra.ibge.gov.br/values/t/{tabla}/n1/all/v/{var}/p/all[/c{clas}/{cat}]` | API pública, sin clave | JSON (la primera fila es el diccionario de columnas) |
| `BCB-Focus` | Banco Central do Brasil, encuesta Focus (Expectativas de Mercado) | `https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/ExpectativasMercadoInflacao12Meses` | API OData pública, sin clave | JSON (`value`) |

- **Códigos en `codigo_fuente`:** `<código>[#<transf>+<transf>...]`. Para SGS es el código numérico; para SIDRA, `tabla/vVariable[/cClasificación=Categoría]` (p. ej. `1620/v583/c11255=90707`, donde 90707 = "PIB a preços de mercado"); para Focus, `recurso/Indicador/Suavizada=S/baseCalculo=0/Campo`. Las transformaciones (`desde`, `esc`, `neg`, `fin_mes`, `prom_mes`, `suma_trim`, `suma_anual`, `dic`, `var12m`, `acum12m`) están documentadas en el encabezado de `bra.py`.
- Para buscar códigos SGS sin entrar al SGS web: el catálogo CKAN de datos abiertos del BCB (`dadosabertos.bcb.gov.br/api/3/action/package_search?q=...`) devuelve el título oficial (los conjuntos se llaman `<código>-<título>`). Los metadatos de SIDRA están en `servicodados.ibge.gov.br/api/v3/agregados/{tabla}/metadados`.
- **No hay series que requieran clave.** No se registró ninguna cuenta. No hay series con `activo=0`.
- **No se usó** Tesouro Transparente/RTN: el resultado fiscal y la deuda en % del PIB están en el SGS (estadísticas fiscales del BCB, la referencia oficial "abaixo da linha"). Ipeadata no se usó.

## Trampas encontradas

- **Series diarias del SGS: ventana máxima de 10 años.** Sin `dataInicial`/`dataFinal`, la API rechaza la consulta. Se descargan en ventanas fijas de 10 años desde el primer año con datos (`DAILY_SGS_FIRST_YEAR` en el script: `1` desde 1984, `432` desde 1999). Los nombres de archivo son estables (`sgs_1_1994-2003.json`...), así que solo cambia la última ventana. Una ventana sin datos devuelve **404** (no una lista vacía), por eso las ventanas no empiezan antes de la serie. Para agregar otra serie diaria hay que añadirla a ese diccionario.
- **El gateway del BCB a veces corta a los 30 s** y devuelve una página HTML de error **con estado 200**. Ocurre en consultas diarias largas con la caché fría. El script valida que la respuesta sea JSON y reintenta (10, 20 y 30 s). En el reintento la respuesta suele llegar en menos de 1 s. También aparecen 502 esporádicos, que reintenta `comun.Client`.
- **Fechas futuras en el SGS.** La Meta Selic (432) se publica hasta el día de la próxima reunión del Copom, y el salario mínimo (1619) incluye los meses ya decretados. Se descartan las fechas posteriores a hoy (queda en el log).
- **Cambio de moneda (Plan Real, 1994-07-01).** Las series en niveles nominales anteriores a julio de 1994 están en cruzeiros, cruzados o cruzeiros reales. Por ejemplo, PTAX mensual (3698) en junio de 1994 = 2.296,26 y en julio = 0,9333; salario mínimo 147.627,08 → 64,79. Por eso `tc_usd_diario`, `tc_usd_promedio`, `salario_minimo` y `credito_total_sfn` llevan `desde=1994-07-01`. El crudo conserva toda la historia. **No se cortan** las variaciones (IPCA mensual, 12 meses, núcleo, IGP-M) ni el índice IPCA, que es continuo a través de las monedas: su valor de 1979 es 7,6e-9 con base dic-1993=100.
- **Signo del resultado fiscal.** El BCB publica NFSP (Necessidades de Financiamento), con positivo = déficit. `resultado_fiscal_pct_pbi` usa `neg` para que positivo = superávit, como en el resto de los países. La serie extra `nfsp_primario_pct_pib_12m` mantiene el signo original del BCB.
- **Variaciones y agregados que el BCB no publica como serie**, calculados aquí:
  - `actividad_mensual_var12m`: interanual del IBC-Br sin ajuste.
  - `inflacion_subyacente_12m`: composición de 12 meses del núcleo IPCA-MS (SGS 4466, que es variación mensual).
  - `inflacion_sae_12m`: composición de 12 meses del núcleo IPCA-EX-FE (SGS 28751, variación mensual).
  - `cuenta_corriente`: suma trimestral de la serie mensual.
  - `pbi_nominal_anual`: suma de 4 trimestres de SIDRA 1846.

  Se verificó que el PIB nominal de 2023 (10.943.344) coincide con la tabla anual 6784 (10.943.345).
- **Agregaciones de diaria a mensual** (`fin_mes`, `prom_mes`): solo meses cerrados. El mes en curso se excluye. Las series mensuales que publica el propio BCB (CDI 4392 y Selic 4189) sí traen el mes en curso parcial.
- **PNAD Continua (SIDRA 6381):** cada dato es un trimestre móvil (código 201203 = ene-feb-mar 2012). Se fecha en el último mes del trimestre. En SIDRA, los trimestres calendario usan el código `AAAA0T` (199601 = 1.er trimestre); se distinguen por la etiqueta del periodo.
- **Valores vacíos:** SIDRA marca los periodos sin dato con `...` (12 al inicio de la variación 12m del IPCA) y el SGS con `null` (4 al inicio de M2). Se descartan y se registran en el log; no se imputan.
- **M2 (27810) está en miles de R$**: se lleva a millones con `esc=0.001`.
- **`tasa_pasiva_promedio` (28663) está descontinuada desde 2024-01.** Es la única serie del BCB con la tasa media de captación CDB/RDB, y no tiene sustituta en el SGS. Además, los valores de 1994-1995 (16-20% a.a.) parecen bajos para la Selic de entonces; no se pudo verificar la metodología de esos años.
- **Núcleos del IPCA que no están en el catálogo CKAN.** La búsqueda en `dadosabertos.bcb.gov.br` solo
  devuelve 5 núcleos (MS 4466, MA 11426, EX0 11427, EX2 16121 —mal rotulado: el SGS lo llama EX1—, DP
  16122). Los nombres oficiales se confirmaron con el servicio SOAP público del SGS
  (`https://www3.bcb.gov.br/wssgs/services/FachadaWSSGS`, `getUltimoValorXML`): 27838 = EX2,
  27839 = EX3, 28750 = Percentil 55 y **28751 = «Núcleo Ex-alimentação e energia (EX-FE)»**, que es
  el que se usa para `inflacion_sae_12m` (excluye alimentación y los ítems de energía). La unidad es
  «Var. % mensual»: el acumulado 12m se calcula aquí (`acum12m`). La serie arranca en 1991-01, así
  que el 12m empieza en 1991-12 (años de alta inflación: valores de miles de % hasta 1994).
- **IGP-M (189):** el índice lo elabora la FGV (fundación privada). Se toma de la publicación del BCB en el SGS, y se dejó solo como serie extra.

## Validación (descarga del 2026-10-21)

| Dato | Parquet | Publicación oficial | OK |
|---|---|---|---|
| IPCA, variación 12 meses, set-2026 | 4,58% | 4,58% (IBGE SIDRA 1737 v2265 y BCB SGS 13522) | sí |
| Meta Selic vigente, set-2026 (fin de mes) | 13,75% | 13,75% (BCB, histórico de tasas del Copom: reunión 281 del 16-09-2026; antes 14,00%) | sí |
| PTAX venta 14 a 20-10-2026 | 5,0441 / 5,0521 / 5,0826 / 5,0564 / 5,0140 | idénticos (BCB, servicio PTAX de Olinda, `CotacaoDolarPeriodo`) | sí |
| PIB nominal 2023 | 10.943.344 millones de R$ | 10.943.345 (IBGE, Cuentas Anuales, tabla 6784) | sí |

| IPCA-EX-FE, var. mensual set-2026 | 0,35% (SGS 28751, JSON) | 0,35% (BCB, SGS por el servicio SOAP `getUltimoValorXML`) | sí |

Controles de consistencia:
- **`inflacion_sae_12m` (EX-FE 12m, agregada el 2026-10-21)**: set-2026 4,71 % (IPCA 4,58 %, IPCA-MS 4,43 %).
  Correlación desde 1996: 0,97 con el IPCA-MS y 0,88 con el IPCA (desde 2006: 0,95 y 0,70). Promedio
  1996-2026: 6,12 % frente a 6,18 % (MS) y 6,39 % (IPCA). No siempre queda entre la total y el MS (162
  de 369 meses): son núcleos de método distinto (exclusión frente a medias recortadas), y en jun-set 2026
  el EX-FE queda por encima de ambos (es decir, alimentos y energía suben menos que el resto).
- **Inflación 12m calculada desde `ipc_indice`** frente a la publicada `inflacion_12m`: diferencia máxima de 0,009 pp desde 1995 (redondeo a 2 decimales); set-2026 = 4,576 frente a 4,58.
- **Escalas:**
  - M2: 7,79 billones de R$ (millones en el parquet).
  - Crédito privado: 7,10 billones de R$.
  - Reservas: 362.821 millones de USD.
  - Exportaciones mensuales: alrededor de 33.000 millones de USD.

  Todo es coherente con las magnitudes publicadas.

## Cobertura obtenida

| nombre_corto | código fuente | indicador común | frec. | desde | hasta | n |
|---|---|---|---|---|---|---|
| `pbi_real_trim` | SIDRA 1620/v583 | pbi_real_trim | trimestral | 1996-T1 | 2026-T2 | 122 |
| `pbi_real_var12m_trim` | SIDRA 5932/v6561 | pbi_real_var12m_trim | trimestral | 1996-T1 | 2026-T2 | 122 |
| `pbi_desest_trim` | SIDRA 1621/v584 | pbi_desest_trim | trimestral | 1996-T1 | 2026-T2 | 122 |
| `actividad_mensual_indice` | SGS 24363 (IBC-Br) | actividad_mensual_indice | mensual | 2003-01 | 2026-08 | 284 |
| `actividad_mensual_var12m` | SGS 24363#var12m | actividad_mensual_var12m | mensual | 2004-01 | 2026-08 | 272 |
| `pbi_nominal_anual` | SIDRA 1846/v585#suma_anual | pbi_nominal_anual | anual | 1996 | 2025 | 30 |
| `ipc_indice` | SIDRA 1737/v2266 (IPCA) | ipc_indice | mensual | 1979-12 | 2026-09 | 562 |
| `inflacion_mensual` | SIDRA 1737/v63 | inflacion_mensual | mensual | 1980-01 | 2026-09 | 561 |
| `inflacion_12m` | SIDRA 1737/v2265 | inflacion_12m | mensual | 1980-12 | 2026-09 | 550 |
| `inflacion_subyacente_12m` | SGS 4466#acum12m (IPCA-MS) | inflacion_subyacente_12m | mensual | 1992-11 | 2026-09 | 407 |
| `tasa_politica` | SGS 432#fin_mes (Meta Selic) | tasa_politica | mensual | 1999-03 | 2026-09 | 331 |
| `tasa_interbancaria` | SGS 4392 (CDI) | tasa_interbancaria | mensual | 1986-08 | 2026-10 | 483 |
| `tasa_activa_promedio` | SGS 20714 | tasa_activa_promedio | mensual | 2011-03 | 2026-08 | 186 |
| `tasa_pasiva_promedio` | SGS 28663 (CDB/RDB) | tasa_pasiva_promedio | mensual | 1994-08 | 2024-01 | 354 |
| `credito_privado` | SGS 22052 | credito_privado | mensual | 2012-01 | 2026-08 | 176 |
| `m2` | SGS 27810#esc | m2 | mensual | 2001-12 | 2026-08 | 297 |
| `expectativa_inflacion_12m` | Focus IPCA 12m#fin_mes | expectativa_inflacion_12m | mensual | 2001-12 | 2026-09 | 298 |
| `tc_usd_promedio` | SGS 3698 | tc_usd_promedio | mensual | 1994-07 | 2026-09 | 387 |
| `tc_usd_diario` | SGS 1 (PTAX) | tc_usd_diario | diaria | 1994-07-01 | 2026-10-20 | 8108 |
| `reservas_internacionales` | SGS 3546 | reservas_internacionales | mensual | 1971-01 | 2026-09 | 669 |
| `exportaciones` | SGS 22708 | exportaciones | mensual | 1995-01 | 2026-08 | 380 |
| `importaciones` | SGS 22709 | importaciones | mensual | 1995-01 | 2026-08 | 380 |
| `balanza_comercial` | SGS 22707 | balanza_comercial | mensual | 1995-01 | 2026-08 | 380 |
| `cuenta_corriente` | SGS 22701#suma_trim | cuenta_corriente | trimestral | 1995-T1 | 2026-T2 | 126 |
| `resultado_fiscal_pct_pbi` | SGS 5727#dic+neg | resultado_fiscal_pct_pbi | anual | 2002 | 2025 | 24 |
| `deuda_publica_pct_pbi` | SGS 13762#dic (DBGG) | deuda_publica_pct_pbi | anual | 2006 | 2025 | 20 |
| `desempleo` | SIDRA 6381/v4099 (PNAD C.) | desempleo | mensual | 2012-03 | 2026-08 | 174 |
| `salario_minimo` | SGS 1619 | salario_minimo | mensual | 1994-07 | 2026-10 | 388 |
| `ibc_br_desest` | SGS 24364 | — | mensual | 2003-01 | 2026-08 | 284 |
| `ipca15_mensual` | SGS 7478 | — | mensual | 2000-05 | 2026-09 | 317 |
| `selic_efetiva_mensal` | SGS 4189 | — | mensual | 1986-08 | 2026-10 | 483 |
| `igpm_mensal` | SGS 189 (FGV) | — | mensual | 1989-06 | 2026-09 | 448 |
| `credito_total_sfn` | SGS 20539 | — | mensual | 1994-07 | 2026-08 | 386 |
| `cuenta_corriente_mensual` | SGS 22701 | — | mensual | 1995-01 | 2026-08 | 380 |
| `selic_meta_diaria` | SGS 432 | — | diaria | 1999-03-05 | 2026-10-21 | 10093 |
| `nfsp_primario_pct_pib_12m` | SGS 5793 | — | mensual | 2002-11 | 2026-08 | 286 |
| `inflacion_sae_12m` | SGS 28751#acum12m (IPCA-EX-FE) | — | mensual | 1991-12 | 2026-09 | 418 |

## Indicadores comunes no cubiertos

Ninguno: los 28 están cubiertos. Con reservas:
- `tasa_pasiva_promedio`: termina en 2024-01 (serie descontinuada por el BCB).
- `pbi_real_trim`: es un índice de volumen encadenado (1995=100), no reales en R$ constantes. El IBGE no publica una serie trimestral larga a precios constantes.
- `inflacion_subyacente_12m`, `actividad_mensual_var12m`, `cuenta_corriente` y `pbi_nominal_anual` se calculan desde series oficiales (ver Trampas).

## Pendientes

- Buscar una fuente oficial que reemplace a la tasa media de captación (28663), por ejemplo las estadísticas de captación del BCB o de B3. Hoy `tasa_pasiva_promedio` está congelada en 2024-01.
- Opcional: núcleo alternativo (promedio de los 5 núcleos que sigue el Copom) en vez de solo IPCA-MS. El
  núcleo por exclusión de alimentos y energía ya está como extra (`inflacion_sae_12m`, EX-FE).
- Opcional: resultado del Tesouro Nacional (RTN) como serie extra del gobierno central.

## Cómo actualizar

```
python src/paises/bra.py                    # descarga todo y reconstruye el parquet (~4 min)
python src/paises/bra.py --solo-procesar    # solo reprocesa data/raw/BRA
python src/paises/bra.py --serie tc_usd_diario tasa_politica   # descarga solo esas series
```
