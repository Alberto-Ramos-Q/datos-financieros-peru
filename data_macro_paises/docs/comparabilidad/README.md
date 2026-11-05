# Comparabilidad entre países — síntesis

Revisión del 2026-10-21 de los 28 indicadores comunes × 13 países (364 pares). Cada par se
contrastó con la metodología oficial de la fuente y con el estándar internacional que
corresponde (SCN 2008, Manual del IPC, MEMF del FMI, MBP6, MEFP 2014, CIET/OIT), y se probó con
los datos.

Detalle por bloque: [`actividad.md`](actividad.md) · [`precios.md`](precios.md) ·
[`monetario.md`](monetario.md) · [`externo.md`](externo.md) · [`fiscal_laboral.md`](fiscal_laboral.md).
Matriz completa, con la diferencia, el ajuste recomendado y la referencia oficial de cada par:
[`matriz_comparabilidad.csv`](matriz_comparabilidad.csv).

> **Implementado (2026-10-21):** los ajustes de esta revisión están aplicados en la capa
> comparable (`src/armonizar.py` → `data/processed/comparable/`; guía en
> [`../comparable.md`](../comparable.md)). También se descargaron las series sugeridas en
> "Series que convendría descargar" y se armó la tabla de metas de inflación
> ([`metas_inflacion.md`](metas_inflacion.md)).

## Veredicto
**Sí se pueden hacer estudios e informes comparativos**, pero no con todos los indicadores ni para
todo tipo de comparación:
- **Variaciones y ciclos: comparables casi siempre.** El 67 % de los pares es A o B en
  variaciones. Crecimiento del PBI, inflación, tasas de política, depreciación, cuenta corriente y
  comercio sirven para comparar dinámica, sincronización y respuesta a choques.
- **Niveles: solo en los indicadores homogéneos.** En niveles hay 23 % de C/D (85 pares), concentrados en
  fiscal, deuda, tasas activas y pasivas, M2, subyacente y desempleo. Ahí las coberturas son
  distintas y no se corrigen con aritmética.
- **Un 71 % de los ajustes es automatizable** (258 de 364 pares): unidades, moneda, rebase, fin de
  periodo frente a promedio, serie original frente a desestacionalizada, recalcular variaciones.
  Hace falta una capa "comparable" antes de cualquier informe; usar `macro_comun_*` tal cual no basta.

Escala:
- **A**: directo.
- **B**: tras un ajuste mecánico.
- **C**: solo tendencias o ciclos, no niveles.
- **D**: no comparable.
- **—**: no aplica o no cubierto.

Cada celda indica *niveles / variaciones*.

| Indicador | ARG | BOL | BRA | CHL | COL | ECU | ESP | MEX | PAN | PER | PRY | URY | USA |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `pbi_real_trim` | B/A | B/A | B/A | B/A | B/A | B/A | B/A | B/A | B/A | B/A | B/A | B/A | B/A |
| `pbi_real_var12m_trim` | A/A | A/A | A/A | A/A | A/A | B/B | B/B | A/A | A/A | A/A | A/A | A/A | B/B |
| `pbi_desest_trim` | B/A | — | B/A | B/A | B/A | B/A | B/A | B/A | — | — | — | B/B | B/A |
| `actividad_mensual_indice` | B/A | C/C | C/C | B/A | B/A | B/A | D/D | B/A | C/C | B/A | C/C | B/A | D/D |
| `actividad_mensual_var12m` | A/A | C/C | C/C | A/A | A/A | B/B | D/D | A/A | C/C | A/A | C/C | A/A | D/D |
| `pbi_nominal_anual` | C/A | C/A | B/A | B/A | B/A | A/A | B/A | B/A | A/A | B/A | B/A | B/A | A/A |
| `ipc_indice` | B/A | B/A | B/A | B/A | B/A | B/A | B/A | B/A | B/A | C/C | C/C | B/A | B/A |
| `inflacion_mensual` | A/A | A/A | A/A | A/A | A/A | A/A | A/A | A/A | A/A | C/C | C/C | A/A | A/A |
| `inflacion_12m` | A/A | A/A | A/A | A/A | A/A | A/A | A/A | A/A | A/A | C/C | C/C | A/A | A/A |
| `inflacion_subyacente_12m` | C/C | C/C | C/C | C/C | C/C | — | C/C | C/C | — | C/C | C/C | C/C | C/C |
| `tasa_politica` | C/C | — | A/A | B/B | A/A | — | B/B | B/A | — | A/A | A/A | A/A | B/A |
| `tasa_interbancaria` | B/B | — | A/A | B/A | A/A | — | A/A | B/A | C/C | A/A | A/A | A/A | A/A |
| `tasa_activa_promedio` | C/C | A/A | A/A | C/C | A/A | C/C | A/A | — | — | C/C | C/C | A/A | C/C |
| `tasa_pasiva_promedio` | C/C | A/A | C/C | C/C | C/C | C/C | C/C | C/C | — | C/C | C/C | A/A | — |
| `credito_privado` | A/B | A/A | A/A | A/B | A/B | A/A | C/B | C/B | A/A | B/A | C/B | A/B | C/C |
| `m2` | C/C | C/C | A/A | A/A | A/A | C/B | C/C | A/A | — | A/B | C/C | C/C | A/A |
| `expectativa_inflacion_12m` | B/B | — | A/A | A/A | A/A | — | — | A/A | — | C/C | — | A/A | C/C |
| `tc_usd_promedio` | A/C | B/C | A/A | A/A | A/A | — | B/B | A/A | — | A/A | A/A | A/A | — |
| `tc_usd_diario` | A/C | B/C | A/A | B/B | B/B | — | B/B | A/A | — | A/A | A/A | A/A | — |
| `reservas_internacionales` | C/C | B/B | A/A | A/A | B/A | A/A | B/B | B/A | — | B/A | B/A | A/A | B/C |
| `exportaciones` | A/A | A/A | A/A | A/A | A/A | A/A | B/B | A/A | D/C | A/A | A/A | C/C | B/A |
| `importaciones` | B/A | A/A | A/A | A/A | A/A | A/A | B/B | A/A | C/C | A/A | A/A | C/C | B/A |
| `balanza_comercial` | B/B | A/A | A/A | A/A | A/A | A/A | B/B | A/A | C/C | A/A | A/A | C/C | B/A |
| `cuenta_corriente` | A/A | A/A | A/A | A/A | A/A | A/A | B/B | A/A | C/C | A/A | A/A | A/A | B/A |
| `resultado_fiscal_pct_pbi` | C/C | A/A | A/A | A/A | C/C | A/A | B/B | C/C | A/C | A/A | C/C | C/C | C/C |
| `deuda_publica_pct_pbi` | C/C | — | C/C | A/A | C/C | C/C | A/A | C/C | — | B/B | B/B | C/C | C/C |
| `desempleo` | C/B | C/B | B/B | B/B | B/B | B/C | A/A | — | C/C | C/C | A/A | B/B | B/A |
| `salario_minimo` | B/A | B/A | B/A | — | B/A | B/A | B/A | B/A | — | B/A | B/A | B/A | — |

**Pares A o B por país** (de 28, en variaciones):

| CHL | COL | BRA | ESP | MEX | URY | PER | ARG | ECU | BOL | PRY | USA | PAN |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 24 | 24 | 23 | 22 | 22 | 21 | 19 | 18 | 18 | 17 | 16 | 15 | 7 |

El núcleo más comparable son las economías con metas de inflación y tipo de cambio flotante:
Chile, Colombia, Brasil, México, Uruguay y Perú. España y EE.UU. sirven como referencia externa.
Argentina y Bolivia necesitan variables de régimen (cepo, tipo de cambio fijo). Ecuador y
Panamá (dolarizados) se comparan aparte, o solo en actividad, precios y sector externo.

## Problemas de fondo (no se arreglan con aritmética)
1. **Fiscal y deuda: coberturas institucionales incompatibles.** Se mezclan gobierno central o
   federal (PRY, COL, USA, ARG), sector público no financiero (PER, ECU, BOL, PAN), gobierno general
   (ESP) y sector público consolidado con el banco central (BRA, URY).
   - La deuda de México es **neta**; la de Argentina y Ecuador no está consolidada; la de EE.UU.
     incluye la deuda intragubernamental (+23,8 pp del PBI).
   - Un ranking de niveles de déficit o deuda con estos datos sería engañoso.
2. **IPC y desempleo de capitales.** Perú usa Lima Metropolitana (IPC y desempleo) y Paraguay el
   Área Metropolitana de Asunción (IPC). En Argentina y Bolivia el desempleo es urbano.
   - Son las medidas oficiales de referencia, pero no son nacionales.
3. **Tasas activas y pasivas: tres conceptos distintos.** Hay promedios sobre saldos que incluyen
   depósitos a la vista (Perú, España, Paraguay), tasas de un solo plazo o producto (DTF, plazo fijo
   30 días, prime, documentos a sola firma) y el costo de fondeo de México (CPP).
   - No sirven para comparar spreads bancarios entre países.
4. **M2 estrecho en cuatro países.** Argentina, Bolivia, Paraguay y Uruguay excluyen moneda
   extranjera o plazo fijo; en economías dolarizadas parcialmente eso cambia mucho el agregado.
5. **Actividad mensual.** España y EE.UU. solo tienen producción industrial (D frente a los
   indicadores de toda la economía). Bolivia, Brasil, Panamá y Paraguay publican indicadores que no
   concilian con el PBI (0,6 a 1,8 pp de diferencia anual).
6. **Comercio de Panamá y Uruguay.** Excluyen la Zona Libre de Colón y las zonas francas
   (celulosa, en Uruguay). Las exportaciones de Panamá son 0,9 mil millones de USD frente a 14 mil
   millones de importaciones.
7. **Subyacente: al menos 6 definiciones** (exclusión, medias recortadas, sin volátiles, sin
   regulados). Solo vale para la dinámica dentro de cada país.

## Ajustes mecánicos a automatizar (capa "comparable")
Por orden de impacto:

| # | Transformación | Afecta a |
|---|---|---|
| 1 | Recalcular las variaciones a/a desde el **nivel original** (no desde el desestacionalizado) | PBI de ECU, ESP y USA; IMAEc de ECU |
| 2 | **Convertir a USD**: flujos con tipo de cambio promedio, saldos con fin de periodo. España a USD por EUR invertido | PBI nominal, comercio, cuenta corriente, reservas, crédito, salario mínimo |
| 3 | **Rebasar índices** a un año común (anula también el factor 4 de los PBI trimestrales a tasa anual de ARG y MEX) | PBI real, IPC, actividad mensual |
| 4 | **Tasas a efectiva anual**, punto medio del rango del FOMC, MRO del BCE antes de 2008-09, TPM de Chile solo desde 2001-08 | Tasa de política e interbancaria |
| 5 | **Desempleo a trimestre calendario**: re-fechar los trimestres móviles (BRA, CHL, PER) y usar la serie sin desestacionalizar de EE.UU. | Desempleo |
| 6 | **Salario mínimo mensual**: MEX ×30,4 (viene por día), ESP ×14/12 (14 pagas) | Salario mínimo |
| 7 | **Importaciones CIF a FOB** y recalcular la balanza | ARG, ESP, PAN |
| 8 | **Crédito a tipo de cambio constante** y variables para los quiebres (Sareb 2012 y Circular 4/2004 en ESP) | Crédito privado |
| 9 | **Variables de régimen**: INDEC intervenido 2007–2015, cepo argentino, tipo de cambio fijo de Bolivia hasta 2026-06, hiperinflaciones, cambios de base sin empalmar | Todos los de ARG, BOL, BRA, PAN |
| 10 | **Cortes de muestra**: expectativas de ARG desde 2016-06; M2 de ARG desde ~1979 | Expectativas, M2 |

Series que convendría **descargar** para subir de grado:
- M3 o agregados con moneda extranjera para ARG, PRY, URY y BOL.
- Reservas brutas de BOL, COL y MEX.
- IPC nacional del INEI para Perú.
- Subyacente "sin alimentos y energía" donde exista (CHL, BRA EX-FE, PRY X1, núcleo de BOL).
- RFSP y SHRFSP para México.
- Deuda en manos del público para EE.UU.

## Qué estudios son viables
**Sólidos** (con la capa comparable):
- **Ciclo económico y sincronización:** crecimiento a/a del PBI en los 13 países; variación t/t
  desestacionalizada en 9 países; ciclo mensual en los 7 con indicador conciliado (ARG, CHL, COL,
  ECU, MEX, PER, URY).
- **Inflación y desinflación:** inflación total en 11 países, más PER y PRY con la advertencia de
  cobertura; desvío frente a la meta; episodio post-2021.
- **Política monetaria:** ciclos de la tasa de política, diferencial frente a la Fed, tasa real
  ex-ante (tasa de política − expectativas) en BRA, CHL, COL, MEX y URY, ARG desde 2016-06.
- **Vulnerabilidad externa:** cuenta corriente en % del PBI en los 12 países MBP6; dinámica de
  exportaciones e importaciones; reservas en meses de importación, con la advertencia de
  brutas frente a netas.
- **Tipo de cambio:** depreciación y volatilidad de las monedas flotantes (BRA, CHL, COL, MEX, PER,
  PRY, URY).
- **Crédito:** crecimiento real a tipo de cambio constante.
- **Salario mínimo en USD.**

**Solo tendencias o ciclos** (no niveles ni rankings):
- Déficit y deuda pública: cambios en pp dentro de cada país.
- Desempleo: nivel comparable solo en los 8 países con tasa nacional (BRA, CHL, COL, ECU desde
  2021, ESP, PRY, URY, USA).
- Subyacente, M2, tasas activas y pasivas.

**No válidos:**
- Rankings de déficit o deuda que mezclen coberturas.
- Spreads bancarios entre países.
- IPC o desempleo de Lima tomados como nacionales.
- Apertura comercial de Panamá y Uruguay.
- Producción industrial de ESP o USA frente al IMACEC o IGAE.
- Volatilidad cambiaria de Bolivia o de Argentina en el cepo.

## Correcciones aplicadas durante la revisión
- **USA `inflacion_mensual`:** venía de la serie desestacionalizada. Ahora se calcula desde el
  índice original, como en los demás países; la versión del BLS quedó en
  `inflacion_mensual_desest`.
- **ARG `pbi_real_trim` y `pbi_desest_trim`:** documentado que vienen a tasa anual (el anual es el
  promedio de los trimestres). El PBI nominal anual y el ratio fiscal estaban bien.
- **ARG `expectativa_inflacion_12m`:** corregida la nota. Mezcla el REM de 2004–2012 con el
  actual desde 2016-06.

## Lo que no se pudo verificar
Está marcado como "no verificado" en `matriz_comparabilidad.csv`:
- La versión del SCN en BRA, COL, MEX, PRY y URY, y el método de desestacionalización en ARG, BRA,
  ECU y URY.
- El tratamiento de la vivienda propia en el IPC de BOL, BRA, CHL, PRY y ESP.
- La metodología de tasas de ECU, PRY y PAN, y la definición de las reservas netas y de la TIPMN
  de Perú (el sitio del BCRP bloqueó la descarga de los PDF).
- La deuda de 2025 de URY y la edad mínima de la encuesta laboral en BOL, ECU y URY.
