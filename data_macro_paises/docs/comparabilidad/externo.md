# Comparabilidad: sector externo y tipo de cambio

Bloque `externo`: `tc_usd_promedio`, `tc_usd_diario`, `reservas_internacionales`, `exportaciones`,
`importaciones`, `balanza_comercial` y `cuenta_corriente`, en 13 países. El detalle por fila está en
`externo.csv`. Revisión del 2026-10-21, hecha sobre `macro_series.csv`, `macro_observaciones.parquet`,
`docs/fuentes/*.md`, `src/paises/*.py` y la documentación oficial que se pudo consultar.

## Resumen ejecutivo

- **La cuenta corriente es el indicador más comparable del bloque.** Diez países la publican en USD y con MBP6. España requiere convertir de EUR a USD y EE.UU. usar sumas anuales, porque su serie está desestacionalizada. Solo **Panamá (MBP5)** queda en C. Calculada en % del PBI, nuestra serie reproduce las cifras oficiales de Chile, Colombia y Perú con una diferencia de ±0,1 pp.
- **El tipo de cambio sirve para convertir en casi todos los países**, pero no siempre para medir depreciación:
  - **Argentina:** periodos de cepo y cambio de metodología del A 3500 el 1/1/2026.
  - **Bolivia:** tipo fijo hasta jun-2026, la serie es de **compra** y el régimen cambia el 27/06/2026.
  - **España:** cotiza al revés (USD por EUR).
  - En los datos diarios, Chile y Colombia van **un día desfasados**: su dato del día t refleja las operaciones de t-1.
- **El comercio es comparable (A) en 8 o 9 países.** Los problemas graves son de **cobertura**:
  - **Panamá:** las exportaciones nacionales excluyen la Zona Libre de Colón (D en niveles).
  - **Uruguay:** el registro aduanero excluye las zonas francas (C).
  - Ajustes mecánicos: Argentina y España valoran las importaciones CIF, España publica en EUR y EE.UU. publica la serie desestacionalizada.
- **Reservas:** las series mezclan reservas **brutas** (7 países) y **netas** (6 países). La diferencia suele ser pequeña. La excepción es **Argentina**: sus brutas incluyen el swap con China, encajes y repos (C). EE.UU. publica las reservas trimestrales y dominadas por el oro; España las publica en EUR y como miembro del Eurosistema.
- **Pruebas:** la balanza comercial es igual a exportaciones menos importaciones en los 12 países con serie mensual. El promedio mensual del tipo de cambio coincide con el promedio de los diarios, salvo en Paraguay (archivo distinto: desvío de hasta 10 % en 2002) y en el México de 1995. Ninguna serie mostró escalas raras en meses de importación.

## Tabla resumen (grado de niveles / grado de variaciones)

| Indicador | ARG | BOL | BRA | CHL | COL | ECU | ESP | MEX | PAN | PER | PRY | URY | USA |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| tc_usd_promedio | A/C | B/C | A/A | A/A | A/A | NA | B/B | A/A | NA | A/A | A/A | A/A | NA |
| tc_usd_diario | A/C | B/C | A/A | B/B | B/B | NA | B/B | A/A | NA | A/A | A/A | A/A | NA |
| reservas_internacionales | C/C | B/B | A/A | A/A | B/A | A/A | B/B | B/A | NA | B/A | B/A | A/A | B/C |
| exportaciones | A/A | A/A | A/A | A/A | A/A | A/A | B/B | A/A | D/C | A/A | A/A | C/C | B/A |
| importaciones | B/A | A/A | A/A | A/A | A/A | A/A | B/B | A/A | C/C | A/A | A/A | C/C | B/A |
| balanza_comercial | B/B | A/A | A/A | A/A | A/A | A/A | B/B | A/A | C/C | A/A | A/A | C/C | B/A |
| cuenta_corriente | A/A | A/A | A/A | A/A | A/A | A/A | B/B | A/A | C/C | A/A | A/A | A/A | B/A |

Conteo de niveles:

| Indicador | A | B | C | D | NA |
|---|---|---|---|---|---|
| tc_usd_promedio | 8 | 2 | 0 | 0 | 3 |
| tc_usd_diario | 6 | 4 | 0 | 0 | 3 |
| reservas_internacionales | 4 | 7 | 1 | 0 | 1 |
| exportaciones | 9 | 2 | 1 | 1 | 0 |
| importaciones | 8 | 3 | 2 | 0 | 0 |
| balanza_comercial | 8 | 3 | 2 | 0 | 0 |
| cuenta_corriente | 10 | 2 | 1 | 0 | 0 |

Cómo leer los grados:
- **Tipo de cambio.** Los "niveles" se refieren a su uso como **factor de conversión a USD**, porque comparar niveles de monedas distintas no tiene sentido. Las "variaciones" se refieren a la depreciación como precio de mercado.
- **Saldos** (balanza comercial y cuenta corriente). Las "variaciones" se refieren a la dinámica (cambio en USD o en pp del PBI), no a tasas %.

## Hallazgos por indicador

### Tipo de cambio (`tc_usd_promedio`, `tc_usd_diario`)

| País | Tasa | Convención | Observación |
|---|---|---|---|
| ARG | Mayorista de referencia Com. A 3500 (BCRA) | ARS/USD | Oficial; no incluye MEP, CCL ni blue. Cepo 2011-2015 y 2019-abr 2025, con brecha >100 %. Bandas desde abr-2025. Desde el **1/1/2026** se calcula como promedio ponderado de las operaciones concertadas por pantalla en A3 Mercados (antes: encuesta de cotizaciones). |
| BOL | Tipo de cambio oficial, **compra** | BOB/USD | 6,86 fijo de 2011 al 26/06/2026 (venta 6,96). Desde el 27-29/06/2026, TCO único administrado (RD 88/2026 y RD 142/2026): 9,73, máximo de 12,64 y 12,02 al 30/09. La serie diaria **incluye fines de semana**. |
| BRA | PTAX venta | BRL/USD | Media de 4 consultas a dealers (desde 2011). Cortada en 1994-07 por el Plan Real. |
| CHL | Dólar observado | CLP/USD | Promedio ponderado del spot del MCF **del día hábil anterior**. |
| COL | TRM | COP/USD | Calculada con las operaciones de un día y vigente al día siguiente (Res. Externa 1 de 2018). Publicada **todos los días calendario**. |
| ESP | Tipo de referencia del BCE | **USD por EUR** | Concertación ~14:10 CET. Antes de 1999 es USD por ECU. |
| MEX | FIX | MXN/USD | Promedio de cotizaciones del mayoreo (liquidación t+2), por **fecha de determinación** (sale en el DOF en t+1). |
| PER | Interbancario | PEN/USD | La serie mensual es el promedio del periodo; la diaria es la **venta**. |
| PRY | Cotización referencial del BCP | PYG/USD | Mensual: promedio de compra y venta de otro archivo. Metodología oficial no verificada. |
| URY | Interbancario "dólar billete" (BCU) | UYU/USD | Compra = venta. Promedio mensual calculado aquí. Metodología oficial no verificada. |
| ECU, PAN, USA | — | — | No aplica: Ecuador y Panamá están dolarizados; el USD es la moneda de referencia. |

Por qué importa:
1. **Argentina y Bolivia.** El tipo "oficial" es el correcto para convertir las estadísticas oficiales, que también lo usan. No mide la depreciación de mercado en los periodos de control (Argentina con cepo; Bolivia con peg y mercado paralelo en 2023-2026).
   - Bolivia: la compra está 0,7 % por debajo del tipo medio de 6,91.
   - Argentina: el cambio de metodología de 2026 es menor en nivel, pero es un quiebre formal.
2. **España** cotiza al revés: una subida de la serie es apreciación del EUR, no depreciación.
3. **Estudios con datos diarios** (correlaciones, contagio, volatilidad):
   - El dólar observado y la TRM tienen un día de desfase frente al resto.
   - La TRM y la serie boliviana repiten valores en fines de semana. Eso infla el número de observaciones y baja la volatilidad medida.
   - Las horas de fijación difieren: PTAX hacia las 13 h de Brasilia, BCE a las 14:10 CET, FIX a mediodía en Ciudad de México. Con retornos de un día esto crea correlaciones asíncronas.

### Reservas internacionales

| País | Concepto | Nota |
|---|---|---|
| ARG | Brutas | Incluyen el swap con China, encajes en USD y repos (no son de libre disponibilidad). |
| BOL | **Netas** de obligaciones | Incluyen pasivos relacionados con el oro; alto peso del oro. |
| BRA | Brutas, concepto liquidez | Incluyen líneas con recompra. |
| CHL | Brutas (activos de reserva MBP6) | — |
| COL | **Netas** (brutas − pasivos de corto plazo) | Diferencia pequeña. Incluyen FLAR. |
| ECU | Brutas (RI) | Dolarizado: respaldan depósitos en el BCE. |
| ESP | Brutas del BdE, en **EUR** | Parte del Eurosistema; no hay política cambiaria nacional. |
| MEX | **Netas** según la Ley de Banxico | Bruta − pasivos a menos de 6 meses. |
| PAN | No aplica | Sin banco central. |
| PER | **RIN** | Incluyen depósitos de la banca (encaje) y del sector público: en la práctica, cercanas a las brutas. |
| PRY | **RIN** | Incluyen FLAR. |
| URY | Brutas (activos de reserva) | Incluyen encajes por depósitos en USD. |
| USA | Brutas (PII de BEA), **trimestrales** | Oro a valor de mercado; el oro es la mayor parte. |

Por qué importa:
- **Escala de la diferencia.** Brutas y netas difieren poco donde los pasivos de corto plazo son chicos (Colombia, México, Perú). Difieren mucho donde las brutas incluyen fondos prestados (Argentina).
- **Encajes en reservas.** Perú, Uruguay y Argentina incluyen los encajes en dólares de la banca. Eso las infla frente a países poco dolarizados.
- **Variaciones mensuales.** Incluyen efectos de valoración: precio del oro y tipo de cambio de las otras monedas. **No son flujos de balanza de pagos.** Esto pesa sobre todo en EE.UU. y Bolivia, donde el oro tiene mucho peso.
- **Estándar.** Ninguna serie está en una moneda distinta del USD salvo España. Los bancos centrales siguen en general el MBP6 o la plantilla de reservas del FMI. El BdE cita las *Operational Guidelines* de 2013. Uruguay rotula su serie como MBP5. Para los demás no se verificó la versión.

### Exportaciones, importaciones y balanza comercial

**Base de registro.**
- **Base balanza de pagos:** Brasil, Chile, EE.UU., Paraguay (balanza de bienes del BCP) y la balanza de Panamá.
- **Registro aduanero:** Argentina, Bolivia (ajustadas), Colombia, Ecuador, España, México, Perú, Uruguay y las series de exportaciones e importaciones de Panamá.

Las dos bases difieren, sobre todo, en el traspaso de propiedad, el merchanting, los bienes para transformación y las zonas francas. En países sin zonas francas grandes, la diferencia suele ser pequeña. No se cuantificó país por país.

**Valoración de importaciones.**
- FOB: 10 países.
- **CIF:** Argentina, España y Panamá.
- EE.UU. usa el valor aduanero, aproximadamente FOB.

Usar CIF sube el nivel de importaciones en un 5-10 % (rango típico; no hay un factor oficial por país en el repositorio) y baja la balanza en la misma cuantía. Las variaciones apenas cambian.

**Cobertura: el problema principal.**
- **Panamá.** El INEC aplica el **sistema especial de comercio** (desde 1958): la Zona Libre de Colón, las zonas francas y los depósitos quedan fuera del territorio aduanero.
  - Las exportaciones nacionales fueron 0,9 mil millones de USD en 2024 (−76 % por el cierre de Cobre Panamá), frente a 14 mil millones de importaciones CIF.
  - En cambio, `balanza_comercial` de Panamá es el saldo de bienes de la balanza de pagos (trimestral, MBP5, con la ZLC). **No es** X − M de las series mensuales.
- **Uruguay.** Las exportaciones e importaciones "cumplidas" del BCU excluyen las zonas francas, donde están, entre otras, las plantas de celulosa. La balanza es un cálculo nuestro (X − M aduanero).
- **Paraguay.** Al revés: el total incluye **reexportaciones** (~32 % de las exportaciones en feb-2023) y "otros". Es consistente con la balanza de pagos, pero no mide "producción nacional exportada".

**Moneda y ajuste estacional.**
- España publica en EUR.
- EE.UU. publica la serie desestacionalizada; los demás, la original.
- Para tasas interanuales o sumas anuales, el ajuste estacional casi no influye. Para niveles mensuales o variaciones mes a mes, sí.

**Revisiones.** España (últimos meses provisionales), EE.UU. (revisión anual del FT-900) y Panamá (revisiones grandes entre ediciones) revisan los datos. El repositorio siempre toma la edición más nueva.

### Cuenta corriente

- **Estándar:** MBP6 en 12 países.
  - Bolivia desde 2014; Uruguay desde 2012. Las series MBP5 anteriores no están empalmadas.
  - Ecuador solo desde 2016.
  - Perú migró al MBP6 según la Nota de Estudios 13-2022 del BCRP; no se verificó si retropoló toda la serie desde 1994.
  - **Panamá usa MBP5.** El saldo total de cuenta corriente cambia poco entre manuales, pero no hay forma mecánica de pasar de uno a otro. Además, sus revisiones son enormes (2023-T3: de −5.855 a −990 millones).
- **Moneda:** EUR en España; USD en el resto.
- **Ajuste estacional:** solo EE.UU. está desestacionalizado.
- **Frecuencia:** trimestral en todos los países. En Brasil es la suma exacta de los meses (verificado).

## Pruebas empíricas

Las pruebas se hicieron con scripts temporales que no forman parte del proyecto; sus resultados están en este documento.

**1. Balanza = exportaciones − importaciones.** Se cumple de forma exacta o con diferencias de redondeo de ≤1 millón en los 12 países con balanza mensual:
- Diferencia exacta (0,000): ARG, BOL, CHL, COL, ECU, MEX, PER, PRY y URY.
- Diferencia de redondeo: BRA (máx. 0,1), ESP (máx. 1) y USA (máx. 1).
- **Panamá no cumple, y es esperable.** Su saldo trimestral de balanza de pagos (con ZLC) promedia −2.345 millones por trimestre. El X − M del INEC sumado por trimestre promedia −2.794 millones. En 2026-T2 la diferencia es de ~980 millones.

**2. Cuenta corriente anual en % del PBI.** Se calculó con `pbi_nominal_anual` convertido con el promedio anual de `tc_usd_promedio` (1 para ECU, PAN y USA; para ESP, todo en EUR).

| País | Año | Calculado | Oficial | Fuente del oficial |
|---|---|---|---|---|
| CHL | 2025 | −1,22 % | −1,2 % | BCCh, marzo de 2026 |
| CHL | 2024 | −1,17 % | −1,5 % | dato publicado entonces; probablemente revisado después, no verificado |
| COL | 2025 | −2,42 % | −2,4 % | BanRep, según La República |
| COL | 2024 | −1,68 % | −1,7 % | BanRep, según La República |
| PER | 2024 | 2,36 % | 2,4 % | Memoria BCRP 2025 (la Nota Semanal de feb-2026 decía 2,2 %) |
| PER | 2025 | 3,53 % | 3,5 % | Memoria BCRP 2025 (la Nota Semanal de feb-2026 decía 3,1 %) |
| USA | 2024 | −4,08 % | −4,0 % | BEA, 25/03/2026 |
| USA | 2025 | −3,81 % | −3,6 % | BEA, 25/03/2026 |

La diferencia de EE.UU. en 2025 se explica porque nuestra serie ya trae el 2025-T1 en −438 mil millones, mayor que en esa publicación. Probablemente es la revisión anual de junio de 2026 (no verificado).

Otros años calculados, sin contraste oficial:

| País | 2023 | 2024 | 2025 |
|---|---|---|---|
| ARG | −3,42 % | 0,92 % | −1,14 % |
| BRA | — | −2,99 % | −2,96 % |
| ECU | — | 5,73 % | 5,86 % |
| ESP | — | 3,34 % | 3,24 % |
| MEX | — | −0,92 % | −0,51 % |
| PAN | −3,19 % | 0,43 % | — |
| URY | — | −0,71 % | −0,28 % |

Conclusión: las escalas, los signos y las conversiones cuadran. La receta "PBI nominal / TC promedio anual" reproduce las cifras oficiales con un error de ±0,1-0,3 pp. Las diferencias mayores vienen de revisiones.

**3. Tipo de cambio promedio frente al promedio de los diarios.** Diferencia relativa entre el promedio mensual cargado y el promedio de los datos diarios:

| País | Resultado |
|---|---|
| ARG, CHL, COL, URY | 0,000 %: el promedio es un cálculo propio desde el diario |
| BRA | ≤0,006 % |
| ESP | ≤0,005 % |
| MEX | ≤0,01 % desde 1998; desvíos en 1991-1997 (máx. 3,7 % hacia dic-1994/1995) |
| BOL | 0,000 % desde 2012; desvíos <0,3 % en 1990-2011, con crawling peg |
| PER | sesgo de −0,02 a −0,05 %: el mensual es el promedio y el diario es la venta |
| PRY | −0,04 a −0,15 % desde 2020; hasta 10 % en 2002 (19 meses con desvío >0,5 %): el mensual viene de otro archivo del BCP |

En Colombia, promediar todos los días calendario o solo los hábiles cambia el promedio hasta 0,49 %. En Bolivia, hasta 1,7 %.

Conclusión: las series mensuales y diarias son coherentes entre sí. En Paraguay, no conviene mezclar las dos en 2002-2003.

**4. Reservas en meses de importación.** Último dato, con el promedio de importaciones de los últimos 12 meses.

| País | Meses | Rango histórico |
|---|---|---|
| ARG | 7,8 | 3,5-17,1 |
| BOL | 5,1 | 1,8-21,0 |
| BRA | 14,8 | 6,5-31,7 |
| CHL | 7,1 | 4,4-10,7 |
| COL | 11,1 | 7,4-17,5 |
| ECU | 4,2 | 1,1-5,1 |
| ESP | 2,8 | 0,5-8,7 |
| MEX | 4,0 | 2,2-6,2 |
| PER | 17,2 | 12,7-26,7 |
| PRY | 6,9 | 2,2-12,2 |
| URY | 17,0 | 3,2-28,5 |
| USA | 4,6 (trimestral) | 1,4-5,3 |

Notas:
- España se calculó en EUR con EUR.
- EE.UU. se calculó con importaciones desestacionalizadas.

No hay escalas raras: las conversiones de miles a millones de México, Paraguay, Uruguay, España y Panamá están bien. Los valores altos de Perú y Uruguay se explican por el concepto: incluyen encajes de depósitos en dólares y, en Uruguay, las importaciones excluyen las zonas francas. No es un error de escala. El de Argentina (7,8) está inflado por el swap.

## Recomendaciones para la "versión comparable"

Transformaciones automatizables, en orden de impacto:
1. **España a USD.**
   - Comercio mensual: multiplicar por el `tc_usd_promedio` del mes (USD por EUR).
   - Cuenta corriente: multiplicar por el promedio trimestral.
   - Reservas: multiplicar por el USD/EUR del último día hábil del mes, tomado de `tc_usd_diario`.
   - Para el tipo de cambio comparable (moneda local por USD), invertir la serie: 1/valor.
2. **Importaciones a FOB en Argentina y España.** Aplicar un factor CIF/FOB y marcar la serie como aproximada. Lo ideal es reemplazarla por los bienes FOB de la balanza de pagos (trimestral). Después, recalcular la balanza FOB-FOB.
3. **EE.UU.** Usar la serie no desestacionalizada (FT-900 y ITA 1.1 no desestacionalizada) o trabajar con sumas anuales. Muestrear las reservas de los demás países a fin de trimestre para compararlas con EE.UU.
4. **Tipo de cambio diario.**
   - Quitar fines de semana y festivos con valor repetido (COL, BOL).
   - Reasignar el dólar observado y la TRM a la fecha de operación (t − 1 día hábil).
   - Bolivia: usar el medio compra/venta hasta el 26/06/2026 y crear una variable de régimen.
5. **Variables de régimen o quiebre:**
   - ARG: cepo (2011-10 a 2015-12 y 2019-09 a 2025-04) y metodología A 3500 (2026-01).
   - BOL: peg hasta 2026-06.
   - CC MBP5/MBP6 en BOL (2014) y URY (2012).
   - Inicio de Ecuador en 2016.
6. **Reservas brutas en todos los países** (requiere descargar series adicionales): brutas del BCB (BOL), RIB de BanRep (COL) y reserva bruta del SIE (MEX). En Perú, la RIN ya es casi bruta. Para Argentina, documentar a mano unas netas estimadas.

No automatizables (requieren otra fuente):
- Exportaciones de Panamá con reexportaciones de la ZLC (balanza de pagos trimestral).
- Comercio de Uruguay con zonas francas (balanza de pagos del BCU).
- Empalmes MBP5-MBP6 de cuenta corriente.

## Qué comparaciones son válidas

**Válidas:**
- Cuenta corriente en USD o en % del PBI, anual o en suma de 4 trimestres, entre los 12 países MBP6. Incluye España tras convertir a USD y EE.UU. con sumas anuales. Panamá, solo como referencia.
- Tasas interanuales de exportaciones e importaciones en USD en los países con grado A: ciclos de comercio, sensibilidad a términos de intercambio y correlaciones.
- Balanza comercial en USD o en % del PBI entre los países FOB-FOB: BOL, BRA, CHL, COL, ECU, MEX, PER y PRY (y EE.UU. con sumas anuales).
- Depreciación mensual entre monedas flotantes: BRA, CHL, COL, MEX, PER, PRY y URY (ARG, solo fuera del cepo).
- Conversión a USD de cualquier serie nominal con `tc_usd_promedio`: para flujos, el promedio del periodo; para saldos, el de fin de periodo, tomado del diario.

**Con cautela (C):**
- Reservas en meses de importación o en % del PBI, por la mezcla de brutas y netas y por los encajes incluidos. Válidas para tendencias propias de cada país, no para rankings de adecuación, en especial con Argentina, EE.UU. y España.
- Comercio de Uruguay y Panamá: sirve para la dinámica de su territorio aduanero, no para medir apertura comercial ni su peso exportador.

**No válidas:**
- Comparar el **nivel** de exportaciones de Panamá (D) con otros países, o su apertura comercial (X + M)/PBI.
- Medir volatilidad cambiaria o pass-through con el tipo oficial de Bolivia (2011-2026) o de Argentina en cepo.
- Correlacionar retornos diarios sin alinear las fechas de Chile y Colombia ni quitar los fines de semana.
- Tratar las variaciones de reservas como flujos de intervención: incluyen valoración (oro, tipo de cambio).

## Lo verificado y lo inferido

- **Verificado en documentación oficial:**
  - Metodología A 3500 de 2026 (BCRA).
  - Dólar observado del día hábil anterior (BCCh).
  - Vigencia de la TRM (SFC).
  - PTAX como media de 4 consultas (BCB, datos abiertos).
  - FIX (Banxico).
  - Tipo de referencia del BCE (USD por EUR, 14:10 CET).
  - Concepto liquidez de las reservas de Brasil (BCB).
  - RIN de Colombia (ficha de BanRep).
  - Reservas del BdE (glosario).
  - Sistema especial de comercio de Panamá (INEC).
  - Cuenta corriente oficial de Chile, Perú y EE.UU.
- **Tomado de la documentación del repositorio (`docs/fuentes`), que cita las notas de las fuentes:**
  - Régimen boliviano de 2026.
  - Composición de las RIN de Bolivia.
  - Exclusión de zonas francas en Uruguay.
  - Valoración FOB/CIF por país.
- **Inferido o no verificado:**
  - Metodologías del tipo de cambio de Paraguay y Uruguay.
  - Definición exacta de la RIN de Perú: el PDF de metadatos del BCRP bloqueó la descarga.
  - Tamaño de la diferencia neta/bruta en COL, MEX y PRY.
  - Peso del swap en Argentina (solo fuentes de prensa).
  - Diferencias entre la base aduanera y la de balanza de pagos en Brasil.
  - Factor CIF/FOB.
  - Si el BCRP retropoló la MBP6.
  - Inclusión de la energía eléctrica binacional en las exportaciones de Paraguay.

## Fuentes consultadas

- BCRA, nueva metodología del tipo de cambio de referencia Com. A 3500 (vigente desde el 1/1/2026): https://www.bcra.gob.ar/noticias/con-el-aporte-de-los-principales-actores-del-mercado-el-bcra-aprobo-una-nueva-metodologia-para-el-calculo-del-tipo-de-cambio-de-referencia-a-3500/
- BCB (Bolivia), sector externo (tipo de cambio oficial, RIN, balanza comercial, balanza de pagos): https://www.bcb.gob.bo/?q=content/sector-externo-0
- BCB (Brasil), PTAX, boletines diarios: https://dadosabertos.bcb.gov.br/dataset/dolar-americano-usd-todos-os-boletins-diarios
- BCB (Brasil), reservas, concepto liquidez: https://dadosabertos.bcb.gov.br/dataset/13982-reservas-internacionais---conceito-liquidez---total---diaria
- BCCh, metodología del dólar observado: https://si3.bcentral.cl/estadisticas/Principal1/Metodologias/EC/PARIDADES/Dolar_observado.pdf
- BCCh, Anuario de Balanza de Pagos 2025: https://si3.bcentral.cl/estadisticas/Principal1/Informes/AnuarioBDP/pdf/Anuario_BDP_2025.pdf
- SFC (Colombia), antecedentes normativos de la TRM: https://www.superfinanciera.gov.co/jsp/10100375
- BanRep, ficha metodológica de reservas internacionales: https://www.banrep.gov.co/sites/default/files/SCE_GT_RI_Ficha_Metodologica_RI_v4.pdf
- BCE, euro foreign exchange reference rates: https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html
- Banco de España, glosario de reservas internacionales: https://www.bde.es/webbe/es/estadisticas/recursos/glosario/conceptos/reservas-internacionales-activos-reserva.html
- Banxico, tipo de cambio FIX: https://www.banxico.org.mx/tipcamb/tipCamMIAction.do?idioma=sp
- CEFP (Cámara de Diputados de México), reserva internacional (Ley del Banco de México): https://www.cefp.gob.mx/publicaciones/documento/2020/cefp0492020.pdf
- BCRP, nota metodológica de los tipos de cambio (solo el resumen del buscador; el PDF bloqueó la descarga): https://www.bcrp.gob.pe/docs/Estadisticas/Operaciones-Monetarias-Cambiarias/nota-metodologica-tipos-de-cambio-publicados-por-el-bcrp.pdf
- BCRP, metadatos de la RIN (no leído completo): https://www.bcrp.gob.pe/docs/Estadisticas/NEDD/Metadata/Metadata_RIN.pdf
- BCRP, Guía Metodológica de la Nota Semanal 2025 (migración al MBP6): https://www.bcrp.gob.pe/docs/Publicaciones/Guia-Metodologica/2025/guia-metodologica-2025-11.pdf
- BCRP, Memoria 2025: https://www.bcrp.gob.pe/docs/Publicaciones/Memoria/2025/memoria-bcrp-2025-0.pdf
- INDEC, Intercambio comercial argentino: https://www.indec.gob.ar/ftp/ica_digital/ica_d_01_26ABE4F7373E/
- INEC Panamá, notas explicativas de comercio exterior (sistema especial): https://www.inec.gob.pa/archivos/P07055475202401160959487.NOTAS%20EXPLICATIVAS_2022.pdf
- Ministerio de Economía de Paraguay, Reporte de Comercio Exterior (mar-2025): https://economia.gov.py/application/files/2117/4583/6975/RCE_Marzo_2025_v1.pdf
- BEA, revisión anual de comercio de bienes y servicios 2026 (FT-900): https://bea.gov/news/2026/us-international-trade-goods-and-services-annual-revision
- BEA, transacciones internacionales del 4.º trimestre y del año 2025: https://www.bea.gov/news/2026/us-international-transactions-and-investment-position-4th-quarter-and-year-2025
- BEA, información adicional sobre la PII: https://www.bea.gov/us-international-transactions-and-investment-position-release-additional-information
- Prensa usada solo para contrastar cifras (no metodología): La República (cuenta corriente de Colombia 2025), https://www.larepublica.co/economia/deficit-corriente-en-2025-alcanzo-us-10-883-millones-lo-que-representa-2-4-del-pib-4339276
- Estándares de referencia: FMI, *Manual de Balanza de Pagos y Posición de Inversión Internacional*, 6.ª edición (MBP6), y *International Reserves and Foreign Currency Liquidity: Guidelines for a Data Template* (2013).
