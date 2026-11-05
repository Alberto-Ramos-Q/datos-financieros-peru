# Comparabilidad entre países: bloque monetario y financiero

Indicadores: `tasa_politica`, `tasa_interbancaria`, `tasa_activa_promedio`, `tasa_pasiva_promedio`,
`credito_privado`, `m2`. El detalle fila por fila está en `monetario.csv`. Escala: A (directo), B (ajuste
mecánico), C (con cautela: solo tendencias), D (no comparable), NA (no aplica o no está cubierto).

## Resumen ejecutivo

- **Las tasas de corto plazo (política e interbancaria) son el núcleo comparable del bloque.** Tras dos o tres
  ajustes mecánicos, el spread interbancaria − política es ≤ 0,2 pp en 9 de los 10 países que tienen ambas series.
  Los ajustes son: base efectiva anual común, punto medio del rango de la Fed y MRO antes de 2008 para el BCE.
  Argentina es la excepción: el instrumento cambió varias veces y la tasa está en TNA.
- **Las tasas activas y pasivas no son comparables en niveles en la mayoría de los países.** Se mezclan tres familias:
  1. promedios del sistema sobre operaciones nuevas;
  2. promedios sobre saldos, que incluyen depósitos a la vista (PER TIPMN/TAMN, ESP, PRY);
  3. tasas de un plazo o producto (ARG, CHL, COL DTF, prime de EE.UU., referencial corporativa de ECU).

  La tasa pasiva de Perú (2,4 %) y la de España (0,6 %) quedan por debajo de su TPM porque incluyen la vista; no
  es que la remuneración sea menor.
- **El M2 no es un concepto homogéneo.**
  - ARG (sin plazo fijo), BOL (sin DPF ni ME), PRY y URY (sin ME) son agregados estrechos.
  - PER es liquidez total con ME, ESP no incluye el efectivo y PAN no tiene M2.
  - Para comparar, conviene usar "dinero amplio con ME" (M3 o M'3 nacional).
- **La cobertura institucional del crédito privado difiere.** MEX (solo banca comercial, ~20 % del PBI) y USA (solo
  bancos comerciales, promedio mensual) subestiman el crédito total. ESP incluye las IF no monetarias y tiene los
  quiebres de 2005 y 2012. En los países con ME a tipo de cambio corriente (URY, PRY, MEX, ARG), el crecimiento
  incluye la revaluación cambiaria.
- **Válido:** ciclos de tasas, pass-through medido con tasas comparables y crecimiento real del crédito (a TC
  constante). **No válido sin ajustes:** rankings de spreads bancarios, de "profundidad" (M2/PBI) o de crédito/PBI
  con MEX, USA, ARG, URY o PRY tal como están.

## Tabla resumen (niveles / variaciones)

| Indicador | ARG | BOL | BRA | CHL | COL | ECU | ESP | MEX | PAN | PER | PRY | URY | USA |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| tasa_politica | C/C | NA | A/A | B/B | A/A | NA | B/B | B/A | NA | A/A | A/A | A/A | B/A |
| tasa_interbancaria | B/B | NA | A/A | B/A | A/A | NA | A/A | B/A | C/C | A/A | A/A | A/A | A/A |
| tasa_activa_promedio | C/C | A/A | A/A | C/C | A/A | C/C | A/A | NA | NA | C/C | C/C | A/A | C/C |
| tasa_pasiva_promedio | C/C | A/A | C/C | C/C | C/C | C/C | C/C | C/C | NA | C/C | C/C | A/A | NA |
| credito_privado | A/B | A/A | A/A | A/B | A/B | A/A | C/B | C/B | A/A | B/A | C/B | A/B | C/C |
| m2 | C/C | C/C | A/A | A/A | A/A | C/B | C/C | A/A | NA | A/B | C/C | C/C | A/A |

Conteo de grados (niveles):

| Indicador | A | B | C | NA |
|---|---|---|---|---|
| tasa_politica | 5 | 4 | 1 | 3 |
| tasa_interbancaria | 7 | 3 | 1 | 2 |
| tasa_activa_promedio | 5 | 0 | 6 | 2 |
| tasa_pasiva_promedio | 2 | 0 | 9 | 2 |
| credito_privado | 8 | 1 | 4 | 0 |
| m2 | 6 | 0 | 6 | 1 |

Ningún par recibió D: todos sirven al menos para tendencias, con las salvedades indicadas.

## Hallazgos por indicador

### Tasa de política
- **Instrumento por país:**

  | País | Instrumento | Detalle |
  |---|---|---|
  | BRA | Meta Selic | fin de mes, TEA base 252 |
  | CHL | TPM | nominal desde el 2001-08-09; antes, tasa real sobre la UF |
  | COL | Tasa de intervención | E.A. |
  | MEX | Tasa objetivo | nominal, desde 2008 |
  | PER | Tasa de referencia | meta de la interbancaria |
  | PRY | TPM | desde 2011-05 |
  | URY | TPM | desde 2020-09 |
  | USA | Límite superior del rango del FOMC | objetivo puntual hasta dic-2008 |
  | ESP | Facilidad de depósito del BCE | |
  | ARG | Serie "tasas de política" del BCRA | 2015-12 a 2025-07, con instrumentos cambiantes (LEBAC, corredor de pases a 7 días, LELIQ, pases pasivos, LEFI) |

  BOL, ECU y PAN no aplican. Para Bolivia, la tasa de reporto es una facilidad de liquidez y no debe usarse como TPM.
- **El dato es a fin de mes en todos los países.** Se comprobó en el código: `#fin_mes`, último dato diario o
  reconstrucción desde las fechas de cambio.
- **Por qué importa:**
  - El límite superior de la Fed sobrestima en ~0,125 pp la tasa efectiva.
  - La DFR del BCE subestima en ~1 pp la orientación de 1999-2008, porque entonces el BCE dirigía la política con
    la MRO y el EONIA superaba a la DFR en ~1,05 pp.
  - La TPM chilena antes de ago-2001 es real: el paso de 3,5 a 6,5 es la nominalización, no un cambio de política.
  - Convención de capitalización: BRA, COL y PER publican en efectiva anual; MEX, CHL, USA y el BCE en nominal
    simple (base 360). Con tasas de 11-14 % la diferencia es de 0,6-0,9 pp.

### Tasa interbancaria
- **Plazo y garantía:** todas son overnight salvo Panamá (hasta 1 semana).
  - Sin garantía: EFFR, €STR, TIB-COL, TIB-CHL, interbancaria del Perú, BAIBAR, TMM-URY y CDI. El CDI es un depósito
    interbancario de B3, no un repo.
  - Colateralizada: la TIIE de fondeo de México es un reporto con títulos gubernamentales.

  El efecto de la garantía en el nivel es pequeño (MEX: +0,02 pp frente a la objetivo).
- **Unidad:** ARG está en TNA. Con tasas de 30-120 %, la TEA es mucho mayor; por ejemplo, una TNA del 100 % a
  1 día equivale a una TEA del ~171 %.
- **Cobertura temporal:** ESP solo desde 2019-10 (el EONIA está como extra), URY desde 2020-09 y PRY desde 2015.
- **Panamá:** la tasa está en USD, es semanal y se promedia de forma simple. Sigue a la EFFR (−0,15 pp); sirve para
  tendencias, no como tasa de un banco central.

### Tasas activas
- **Promedio del sistema sobre operaciones nuevas (A):**
  - BRA (concesiones del SFN, libres y dirigidas; el rotativo eleva el nivel a ~30 %)
  - COL (colocación total ponderada por desembolsos)
  - BOL (sistema financiero en MN, efectiva)
  - ESP (tipo sintético de nuevas operaciones a hogares y SNF, ponderado por saldos vivos de cada categoría; está
    verificado en la nota (b) del cuadro 2.10 del Boletín Estadístico del BdE)
  - URY (créditos en pesos no reajustables a empresas y familias)
- **No son promedios del sistema (C):**
  - ARG: documentos a sola firma, un solo producto, en TNA.
  - CHL: tramo de 90 días a 1 año no reajustable.
  - ECU: la "activa referencial" corresponde al segmento productivo corporativo. El dato de 2026-08 (6,79 %)
    coincide con el corporativo publicado.
  - PER: la TAMN se calcula sobre saldos (la FTAMN usa operaciones de 30 días).
  - PRY: ponderada por saldos según la nota del repositorio.
  - USA: prime = TPM + 3 pp por convención.
  - MEX y PAN no tienen serie.
- **Por qué importa:** un spread activa − pasiva entre países mezcla la composición de la cartera, el uso de saldos
  frente a flujos y el plazo. Por ejemplo, el spread de Perú (12,6 pp) se infla porque combina una TAMN con
  tarjetas sobre saldos con una TIPMN que incluye la vista.

### Tasas pasivas
- **Solo plazo, todos los plazos (A):** BOL (DPF) y URY (plazo fijo en pesos).
- **Un plazo único (C):** ARG (30 días, TNA), CHL (30-89 días) y COL (DTF a 90 días).
- **Promedios sobre saldos que incluyen la vista (C):**
  - PER (TIPMN: corriente, ahorro y plazo; según la metadata del BCRP)
  - ESP (el sintético incluye vista, plazo y cesiones; verificado en la nota del BdE)
  - PRY (el total mezcla vista ~1,2 % y plazo ~6,5 %)
- **Costo de fondeo (C):** MEX (CPP, sobre el stock de pasivos).
- **Otros casos:**
  - BRA: CDB pós-fixado, descontinuado en 2024-01 y con una relación errática frente al CDI.
  - ECU: referencial con ponderación no verificada.
  - USA y PAN no tienen serie.

### Crédito al sector privado
- **Cobertura institucional:**
  - Sociedades de depósito o sistema financiero: ARG (entidades financieras), BOL (bancos y no bancarias desde
    1996-07), BRA (SFN), COL (establecimientos de crédito), ECU (sistema financiero), PER (SCD).
  - Solo bancos: CHL (incluye el SPNF, marginal), MEX (solo banca comercial), PAN, PRY (bancos y financieras, sin
    cooperativas), URY y USA (solo bancos comerciales).
- **Sectores de contraparte:**
  - ESP incluye las IF no monetarias ("otros sectores residentes").
  - USA incluye todos los préstamos y leasing de los bancos comerciales (domésticos y foreign-related; excluye
    thrifts y credit unions, según el About de H.8).
- **Moneda extranjera:**
  - A TC corriente: ARG, CHL, COL, MEX, PRY y URY.
  - A TC constante: PER.
  - En USD: ECU y PAN.
- **Tipo de dato:** USA es promedio mensual de datos semanales; el resto es fin de mes.
- **Quiebres:**
  - ESP: +6,6 % en 2005-06 (Circular 4/2004) y −5,0 % en 2012-12 (Sareb).
  - USA: +4,9 % en 2010-04 (FAS 166/167).
  - BOL: +12,7 % en 1996-07 (incorporación de las no bancarias).
  - URY: +16,6 % en 2008-05 sin movimiento cambiario (no explicado).
  - ARG: saltos de ±14-18 % en 2002 (pesificación).
  - PER: caídas en algunos eneros (2003 y 2006, ~−2,5 a −2,9 %; no explicadas).

### M2
- **Solo moneda nacional:** BOL (sin DPF), PRY y URY; los depósitos en ME van en M'2/M'3 o M3. CHL deja la ME en M3,
  pero la dolarización es baja.
- **ARG:** según el catálogo del BCRA, M2 = M1 + cajas de ahorro (excluye el plazo fijo, que está en M3). Además está
  reexpresado en pesos actuales: los valores anteriores a ~1979 son pocos pesos redondeados (en 1966 hay un solo valor
  distinto), así que esas variaciones son ruido de redondeo.
- **PER:** liquidez total de las SCD, MN + ME a TC corriente; es un agregado amplio.
- **ESP:** es la contribución española al M2 de la UEM, sin efectivo y con pasivos frente a residentes de toda la
  zona euro.
- **USA:** H.6 es promedio mensual sin desestacionalizar e incluye los fondos MMF minoristas. El cambio de may-2020
  reclasifica el ahorro a M1 sin cambiar el M2.
- **MEX:** metodología 2018 (MEFP 2016); incluye los fondos de inversión de deuda.
- **BRA:** M2 "novo" (revisión de 2018, historia desde 2001-12).
- **ECU:** en USD; caída de −16 % en 2003-02, que coincide con el inicio del Panorama financiero.
- **PAN:** no aplica.

## Pruebas empíricas

Las pruebas se hicieron con scripts temporales que no forman parte del proyecto; sus resultados están en este documento.

**1. Spread interbancaria − política (pp, mensual).** La tasa de política es a fin de mes, así que en los meses con
cambio de tasa el spread salta. Por eso también se comparó contra el promedio diario de la TPM donde hay serie diaria
(BRA, PER).

| País | Mediana (toda la serie) | Media 2023+ | Comentario |
|---|---|---|---|
| ARG | −6,65 | −3,98 | No comparable: la TPM no era una tasa overnight (LELIQ, pases) |
| BRA | −0,11 | −0,12 | CDI ≈ Meta Selic − 0,10 de forma estructural (frente al promedio diario de la meta: −0,10 a −0,26) |
| CHL | 0,00 | 0,08 | Media total de 0,81 por 1997-2001: la TPM era real y la TIB nominal (p. ej., 1998-07: TPM 8,5 frente a TIB 20,3) |
| COL | 0,00 | −0,08 | Confirma que la TPM está en E.A. El IBR overnight nominal queda ~0,5-1 pp por debajo; llevado a E.A. coincide con la TPM |
| ESP | −0,07 | −0,09 | €STR ≈ DFR − 0,08. Con EONIA y DFR, el spread era de +1,05 a +1,15 en 2001-2007 (régimen de la MRO); con EONIA y MRO, ~0,05 |
| MEX | 0,02 | 0,07 | Reporto colateralizado ≈ objetivo |
| PER | 0,00 | 0,01 | Frente al promedio diario de la tasa de referencia: 0,01 pp (2003-2026) |
| PRY | −0,14 | 0,03 | |
| URY | 0,00 | 0,01 | |
| USA | −0,08 | −0,15 | EFFR − punto medio del rango (desde 2009): ~0,00 (−0,21 en 2022 por las subidas rápidas) |

Conclusión: después de los ajustes (punto medio de la Fed, MRO antes de 2008 para el BCE y TPM nominal en CHL), la
política y la interbancaria miden el mismo concepto en todos los países salvo ARG.

**2. Pass-through: Δ12m de las tasas activa o pasiva frente a Δ12m de la tasa de política (2012+).**

| Tasa | Países con beta alta | Países con beta baja |
|---|---|---|
| Pasiva | CHL 0,98, COL 0,96, ARG 0,90, URY 0,72, MEX 0,69 | ESP 0,14, PRY 0,24, PER 0,36 |
| Activa | USA 0,99 (prime mecánica), BRA 0,99, CHL 0,95, ESP 0,83 | PER 0,52, PRY 0,44 |

Las betas bajas son las de las series sobre saldos o que incluyen la vista. La diferencia de pass-through entre
países es, en buena parte, un artefacto de la definición.

**3. Niveles en ventana común (sep-2024 a ago-2025, %).**

| País | Activa | Pasiva | TPM |
|---|---|---|---|
| PER | 14,9 | 2,4 | 4,8 |
| ESP | 4,2 | 0,6 | DFR 2,65 |
| CHL | 14,1 | 4,7 | 5,0 |
| COL | 14,5 | 9,2 | 9,6 |
| URY | 17,0 | 7,3 | 8,9 |
| BRA | 30,2 | — | 13,3 |

En PER y ESP, que las pasivas queden tan por debajo de la TPM es la firma de la inclusión de la vista.

**4. Crédito/PBI y M2/PBI (saldo de diciembre / `pbi_nominal_anual`, %).**

| País | Crédito 2019 | Crédito 2024 | M2 2019 | M2 2024 | Lectura |
|---|---|---|---|---|---|
| ARG | 11,6 | 11,3 | 12,7 | 12,2 | M2 sin plazo fijo |
| BOL | 54,8 | 58,3 | 31,9 | 46,4 | M2 sin DPF ni ME |
| BRA | 44,4 | 52,6 | 41,9 | 56,5 | |
| CHL | 85,1 | 71,6 | 78,4 | 62,0 | |
| COL | 46,0 | 39,9 | 47,1 | 48,6 | |
| ECU | 41,4 | 54,9 | 53,9 | 71,5 | |
| ESP | 90,6 | 70,7 | 99,5 | 99,7 | Incluye IF no monetarias; M2 sin efectivo |
| MEX | 19,6 | 21,1 | 37,1 | 46,4 | Solo banca comercial |
| PAN | 78,5 | 71,2 | — | — | |
| PER | 42,2 | 36,8 | 42,8 | 45,5 | Crédito a TC constante |
| PRY | 40,1 | 49,2 | 22,5 | 25,6 | M2 solo MN |
| URY | 25,0 | 29,4 | 15,3 | 18,6 | M2 solo MN |
| USA | 46,8 | 43,1 | 71,8 | 73,6 | Solo bancos comerciales, promedio mensual |

Los valores atípicos coinciden con las diferencias de cobertura documentadas: el M2 de ARG, URY, PRY y BOL es
estrecho, y el crédito de MEX y USA cubre solo bancos. No aparecen errores de escala: todos los ratios son
plausibles.

**5. Saltos bruscos en saldos.** Se usó un z robusto de la variación m/m frente a la mediana móvil de 25 meses.

- Confirmados o documentados: ESP 2005-06 (+6,6 %, z=10) y 2012-12 (−5,0 %); USA 2010-04 (+4,9 %) y 1958-01
  (+6,4 %); BOL 1996-07 (+12,7 %, z=14) y 2023-05 (−4,2 %, z=−15); ARG 2002 (±14-18 %).
- Nuevos o no explicados:
  - URY, crédito 2008-05: +16,6 % con el TC −0,3 %.
  - ECU, M2 2003-02: −16,1 %, z=−13.
  - PRY, M2 1975-03/04: −36 % y +68 %; parece un error de la fuente.
  - PER, crédito: eneros de 2003 (−2,9 %) y 2006 (−2,5 %).
  - URY, M2 2010-03/04: +7,9 % y −7,8 %.
- Diciembres altos en M2 (aguinaldo) en BOL, COL, MEX, PER y URY: son estacionalidad, no quiebres.

**6. Efecto cambiario en el crédito.** Regresión de la variación m/m del crédito sobre la variación m/m del TC
(2010+): URY 0,43, PRY 0,38, MEX 0,17, ARG 0,12, CHL 0,10, COL 0,07, PER 0,00 y BOL −0,01. Confirma que PER está a
TC constante y que en URY y PRY una devaluación infla el "crecimiento" del crédito.

## Recomendaciones para la versión comparable

**1. Base común de tasas: TEA.**
- Nominal act/360 overnight (USA, ESP, MEX, CHL): r_TEA = (1+r/360)^365 − 1.
- TNA de ARG a plazo n días: (1+TNA·n/365)^(365/n) − 1, con n=1 para BAIBAR, 30 para plazo fijo y el plazo del
  instrumento para la TPM.
- BRA (base 252), COL, PER y BOL ya están en TEA.
- Es automatizable.

**2. Tasa de política "efectiva":**
- USA: punto medio del rango (límite superior − 0,125) desde 2008-12.
- ESP: MRO (`tasa_bce_mro`) hasta 2008-09 y DFR después.
- CHL: cortar antes de 2001-08 o nominalizar con la variación de la UF.
- ARG: agregar una columna de régimen o instrumento.
- Todo es automatizable salvo el régimen de ARG.

**3. Interbancaria ESP larga:** EONIA hasta 2019-09 y luego €STR + 0,085, o €STR desde 2019-10 con el EONIA empalmado.
Es automatizable.

**4. Tasas activas y pasivas:** no construir una "versión comparable" de niveles con las series actuales.
- Para comparar niveles entre países, descargar (pendiente) series de **operaciones nuevas, depósitos a plazo**:
  - PER: FTAMN/FTIPMN o la pasiva a plazo.
  - ESP: depósitos a plazo de nuevas operaciones (capítulo 19 del BdE).
  - PRY: tasa de depósitos a plazo.
  - CHL: promedio de todos los plazos.
- Mientras tanto, usar solo variaciones dentro de cada familia.

**5. Crédito privado:**
- Calcular el crecimiento a TC constante donde haya componente en ME: COL (375 + 376/TC·TC_base) y PRY (con
  `dolarizacion_credito_privado`) son automatizables; URY (MN y ME en Creditos.xlsx) y ARG o MEX requieren descargar
  el componente en ME.
- Neutralizar los quiebres: ESP 2005-06 y 2012-12, USA 2010-04 y BOL 1996-07. Usar factores de enlace o las tasas
  ajustadas de quiebres de la fuente.
- Deflactar con el IPC para el crecimiento real.
- Para crédito/PBI de PER, usar la serie a TC corriente.

**6. M2 "amplio":** reemplazar o agregar la serie por país.
- ARG: M3 en moneda local (BCRA 1624) o M3 total (1623).
- BOL: M'3.
- PRY: M3.
- URY: M3 (M2 + depósitos en ME).
- Mantener BRA, CHL, COL, MEX, PER y USA.
- Marcar ECU antes de 2003-02 y PRY 1975-03.
- No usar el M2 de ARG antes de 1980 para variaciones.
- Es automatizable una vez descargadas las series alternativas.

**7. Fin de mes frente a promedio:** USA (crédito H.8 y M2 H.6) no se puede reconstruir a fin de mes, porque H.6 solo
publica promedios mensuales desde 2021. Hay que documentarlo; en las variaciones de 12 meses el efecto es menor.

## Qué estudios son válidos

**Válidos:**
- Ciclos de política monetaria y sincronización de tasas de política e interbancarias (con los ajustes 1-3).
- Diferenciales de tasas de corto plazo frente a la Fed.
- Pass-through tasa de política → interbancaria.
- Crecimiento real del crédito a TC constante.
- Correlaciones crédito-actividad.
- Crecimiento del dinero amplio una vez armado el M2 amplio.

**Con cautela (C):**
- Pass-through hacia las tasas activas y pasivas: hay que comparar familias homogéneas (por ejemplo, BOL, URY, COL
  y BRA para la activa).
- Crédito/PBI de MEX, USA y ESP: son coberturas distintas.

**No válidos con las series actuales:**
- Rankings de spread bancario (activa − pasiva) entre países.
- Comparar niveles de tasas pasivas (PER o ESP frente al resto).
- Rankings de M2/PBI con ARG, BOL, PRY y URY.
- Crédito/PBI de USA como medida de apalancamiento privado (excluye el mercado de capitales).
- Cualquier uso de la TPM de ARG después de 2025-07 o como tasa overnight.

## Fuentes consultadas

**Verificado en la fuente oficial (directamente o por su resumen):**
- BCRA, catálogo de la API v4.0, descripciones oficiales de las variables 11, 12, 26, 160, 1216, 1233, 1234, 1618,
  1623 y 1624 (copia local en `data/raw/ARG/bcra/catalogo_*.json`): https://api.bcra.gob.ar/estadisticas/v4.0/Monetarias
- Banco de España, Boletín Estadístico, cuadro 2.10, nota (b) sobre los tipos sintéticos:
  https://www.bde.es/webbde/es/estadis/infoest/a0210.pdf
- BCE, cambios al marco operativo (13-mar-2024; DFR como tasa de orientación y spread MRO-DFR de 15 pb):
  https://www.ecb.europa.eu/press/pr/date/2024/html/ecb.pr240313~807e240020.en.html
- Federal Reserve:
  - H.8 About (cobertura y promedios pro rata de datos semanales): https://www.federalreserve.gov/releases/h8/about.htm
  - H.6 (definición de M2 y cambio de may-2020): https://www.federalreserve.gov/releases/h6/
- BCB Brasil, datos abiertos:
  - Serie 20714 (operaciones nuevas, libre + dirigido, ponderada por monto):
    https://dadosabertos.bcb.gov.br/dataset/20714-taxa-media-de-juros-das-operacoes-de-credito---total
  - Serie 27810 (M2 nuevo, revisión de 2018): https://dadosabertos.bcb.gov.br/dataset/27810-sgs
- Banco Central de Chile:
  - Agregados monetarios (M2 = M1 + depósitos a plazo; ME en M3):
    https://www.bcentral.cl/web/banco-central/areas/estadisticas/agregados-monetarios
  - DT 197, nominalización de 2001: https://www.bcentral.cl/en/content/-/details/documento-de-trabajo-n-197
  - EEE 113, estadísticas de tasas: https://www.bcentral.cl/documents/33528/2546075/see113.pdf (base 360 simple, según
    el resumen de los boletines; el PDF no se leyó completo)
- BCRP, metadata de tasas (TIPMN sobre saldos de corriente, ahorro y plazo; FTIPMN de 30 días): se consultó por el
  resumen del buscador, porque el sitio bloquea la descarga automática.
  https://www.bcrp.gob.pe/docs/Estadisticas/NEDD/Metadata/Metadata_Tasas.pdf
- Banxico, metodología 2018 de los agregados:
  https://www.banxico.org.mx/publicaciones-y-prensa/agregados-monetarios-y-actividad-financiera/agregados-monetarios-activida.html
- BCB Bolivia, metadatos de dinero en sentido amplio y crédito:
  https://www.bcb.gob.bo/webdocs/serviciosbcb/metadatos/dineroensentidoamplio.pdf
- BanRep, implementación de la política monetaria:
  https://www.banrep.gov.co/es/politica-monetaria-cambiaria/implementacion-politica-monetaria

**Solo fuentes secundarias (marcadas como inferidas o "no verificado" en el CSV):**
- Ecuador: definición de la tasa activa referencial (segmento corporativo, 84-91 días) según la UASB y la prensa;
  no se encontró la nota del BCE.
- Paraguay: composición vista/plazo de la tasa pasiva, según la prensa que cita al BCP.
- Uruguay: TPM desde sep-2020, según la prensa y la CEPAL.
- México: composición del CPP, según CMIC y el DOF.
- Panamá: la metodología de la tasa interbancaria de la SBP no se encontró.
- Bolivia: no se encontró cobertura de la caída de 2023-05 (Fassil).
- Uruguay: no se encontró cobertura del salto de 2008-05.

**Material local:** `config/indicadores_comunes.csv`, `config/series/*.csv`, `docs/fuentes/*.md`,
`src/paises/{pry,bol,usa,pan,arg}.py`, `data/processed/macro_series.csv` y `macro_observaciones.parquet`.
