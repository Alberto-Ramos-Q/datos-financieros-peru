# Comparabilidad entre países — bloque actividad y cuentas nacionales

Indicadores: `pbi_real_trim`, `pbi_real_var12m_trim`, `pbi_desest_trim`, `actividad_mensual_indice`,
`actividad_mensual_var12m`, `pbi_nominal_anual`. El detalle por país está en `actividad.csv`
(78 filas: 6 indicadores × 13 países). Fecha de revisión: 2026-10-21, con los datos de
`data/processed/` de ese día.

## Resumen ejecutivo

- **Las tasas de crecimiento del PIB real trimestral son el núcleo comparable del bloque.** Diez
  países publican la variación a/a sobre la serie original. Ecuador, España y EE.UU. la publican
  sobre la serie **desestacionalizada**; basta con recalcularla desde el nivel original (grado B,
  automatizable).
- **Los niveles nunca se comparan en crudo.** Hay 13 monedas, 9 años base, índices frente a moneda
  constante, y niveles **a tasa anual** en México, **Argentina** y el desestacionalizado de EE.UU.
  Con un rebase a un índice de año común quedan comparables (grado B).
- **Hallazgo nuevo:** el PIB trimestral real de **Argentina** (original y desestacionalizado) está a
  tasa anual: el promedio de los 4 trimestres es el PIB del año, y el "Total" del INDEC es un
  promedio. No está anotado en `macro_series.csv` ni en `docs/fuentes/ARG.md`. Sumar sus
  trimestres da 4 veces el PIB.
- **El indicador mensual es el eslabón débil.** España y EE.UU. usan producción industrial (grado
  D). Bolivia (IGAE base 1990, discontinuado), Panamá (IMAE base 2007, cubre ~85% del VA), Brasil
  (IBC-Br, una proxy del BCB) y Paraguay (IMAEP no conciliado) quedan en C. Solo 7 países tienen un
  mensual conciliado con su PIB.
- **El PIB nominal es coherente en escala.** La conversión a USD da órdenes de magnitud plausibles y
  el deflactor implícito vale 100 en el año base en todos los países. Argentina y Bolivia quedan en
  C para niveles en USD por sus regímenes cambiarios.
- **El PIB desestacionalizado falta en 4 países** (BOL, PAN, PER, PRY). Para Perú se puede
  reconstruir desde la variación t/t anualizada del BCRP.

## Tabla resumen (niveles / variaciones)

| País | pbi_real_trim | pbi_real_var12m_trim | pbi_desest_trim | actividad_mensual_indice | actividad_mensual_var12m | pbi_nominal_anual |
|---|---|---|---|---|---|---|
| ARG | B / A | A / A | B / A | B / A | A / A | C / A |
| BOL | B / A | A / A | NA / NA | C / C | C / C | C / A |
| BRA | B / A | A / A | B / A | C / C | C / C | B / A |
| CHL | B / A | A / A | B / A | B / A | A / A | B / A |
| COL | B / A | A / A | B / A | B / A | A / A | B / A |
| ECU | B / A | B / B | B / A | B / A | B / B | A / A |
| ESP | B / A | B / B | B / A | D / D | D / D | B / A |
| MEX | B / A | A / A | B / A | B / A | A / A | B / A |
| PAN | B / A | A / A | NA / NA | C / C | C / C | A / A |
| PER | B / A | A / A | NA / NA | B / A | A / A | B / A |
| PRY | B / A | A / A | NA / NA | C / C | C / C | B / A |
| URY | B / A | A / A | B / B | B / A | A / A | B / A |
| USA | B / A | B / B | B / A | D / D | D / D | A / A |

Cómo leer las columnas:
- **Indicadores en nivel** (`pbi_real_trim`, `pbi_desest_trim`, `actividad_mensual_indice`,
  `pbi_nominal_anual`): "niveles" es la trayectoria del nivel una vez llevado a un índice común (o
  a USD en el caso del nominal); "variaciones" son las tasas calculadas desde ese nivel.
- **Indicadores que ya son tasas** (`*_var12m*`): las dos columnas valen lo mismo. Se refieren a la
  tasa publicada y a sus cambios (aceleración o desaceleración).

Conteo de grados por indicador:

| Indicador | Niveles | Variaciones |
|---|---|---|
| pbi_real_trim | B 13 | A 13 |
| pbi_real_var12m_trim | A 10, B 3 | A 10, B 3 |
| pbi_desest_trim | B 9, NA 4 | A 8, B 1, NA 4 |
| actividad_mensual_indice | B 7, C 4, D 2 | A 7, C 4, D 2 |
| actividad_mensual_var12m | A 6, B 1, C 4, D 2 | A 6, B 1, C 4, D 2 |
| pbi_nominal_anual | A 3, B 8, C 2 | A 13 |

## Hallazgos por indicador

### pbi_real_trim (PIB real trimestral, original)

- **Estándar y base.** Según el cuadro de CEPAL (2021) y las fuentes nacionales, las series siguen
  dos familias:
  - **Volumen encadenado** (lo que recomienda el SCN 2008): BRA (ref. 2010), CHL (2018), COL
    (2015), ECU (2018), PAN (2018), BOL (2017), ESP (2020, SEC 2010) y USA (Fisher, dólares de
    2017).
  - **Base fija a precios constantes**: ARG (2004), PER (2007), PRY (2014), URY (2016) y MEX
    (2018).

  Perú y Argentina tienen años base de hace 19 y 22 años. En una base fija lejana, el sesgo de
  sustitución puede mover el crecimiento agregado algunas décimas. Esto es inferido, no se midió.
  No es corregible, pero tampoco cambia las tendencias.
- **Unidad.** Hay tres casos especiales:
  - BRA y ESP publican **índices**, no moneda.
  - MEX y **ARG** publican niveles **a tasa anual** (el promedio de los trimestres es el PIB
    anual). Para ARG se confirmó en el Cuadro 1 del *Informe de avance del nivel de actividad* del
    INDEC (II-2026): el "Total 2025" (739.729) es el promedio de los trimestres. En la base, el
    promedio de 2004 (485.115) es igual al PIB nominal de 2004.
  - USA (ND000334) es el nivel trimestral **sin anualizar**, y solo existe desde 2002.
- **Cobertura temporal.** Cuatro países tienen series cortas por cambio de base sin empalme
  oficial: BOL (desde 2017), PAN (2018), URY (2016) y USA NSA (2002).
- **Preliminares.** BOL desde 2019, PRY desde 2015, PAN desde 2024 (2025-26 estimados) y ARG 2025-26.
  BEA revisa en tres estimaciones trimestrales más las actualizaciones anuales. Ninguna serie del
  repositorio guarda vintages.

### pbi_real_var12m_trim

- **Prueba de recálculo desde el nivel original:** la diferencia es 0 o menos de 0,06 pp en ARG,
  BOL, BRA, CHL, COL, MEX, PAN, PER, PRY y URY.
- **Tres países publican la tasa sobre la serie desestacionalizada.** Recalculada desde su nivel
  desestacionalizado, la diferencia es 0 en ECU y ESP, y 0,05 pp en USA:

  | País | Ajuste de la tasa oficial | Diferencia máxima con la original | Desv. estándar |
  |---|---|---|---|
  | ECU | Estacionalidad | 2,8 pp | 0,58 |
  | ESP | Estacionalidad y calendario (CVEC) | 0,7 pp | 0,27 |
  | USA | Estacionalidad | 1,7 pp | 0,40 |

  Mezclarlas con las demás introduce un error del orden de 0,3–0,6 pp por trimestre, y en algunos
  trimestres de 1,5–3 pp. Esto importa en estudios de ciclo y de turning points.

### pbi_desest_trim

- **Prueba de estacionalidad residual.** Se hizo un ANOVA de la dlog trimestral sobre dummies de
  trimestre, excluyendo 2020-21:
  - Las series originales dan p<0,001 y R² entre 0,53 y 0,98.
  - Las desestacionalizadas dan p entre 0,23 y 0,95 en 8 de 9 países.
  - **Uruguay** da p=0,047 (R² 0,24): la dlog media del T1 es +1,3 pp. El patrón T1 fuerte y T2
    débil aparece en 2017, 2018 y 2023. Puede ser la cosecha o la sequía de 2023, pero es un
    indicio de estacionalidad residual que conviene validar.
- **Restricción anual.** En ARG, COL, ECU y ESP la suma anual del desestacionalizado es igual a la
  del original, así que el ajuste está restringido al total anual. En BRA, CHL y MEX no lo está
  (difiere hasta ±0,3%). Es una diferencia menor en las tasas, pero explica por qué el crecimiento
  anual "desestacionalizado" no coincide con el oficial.
- **Unidad.** USA está a **SAAR**: su promedio anual es igual a la suma NSA. Las tasas titulares de
  BEA son t/t anualizadas: un 0,5% t/t se publica como ~2,0%. MEX y ARG también están a tasa anual.
  La t/t calculada desde el nivel no se ve afectada por la anualización, porque el factor 4 se
  cancela.
- **Métodos verificados:**
  - X-13 ARIMA-SEATS: CHL (método indirecto), COL (con efecto calendario, Semana Santa y año
    bisiesto) y MEX (estacionalidad y calendario).
  - Estacionalidad y calendario: ESP; su documento metodológico describe TRAMO-SEATS y JDemetra+.
  - TRAMO-SEATS: PER, en el ajuste del BCRP.
  - No verificados: ARG, BRA, ECU y URY.

  Las diferencias de método y de tratamiento del calendario son menores para tasas t/t, por eso el
  grado es A.
- **Perú.** `pbi_desest_var_trim` (PN37939AQ) no es la t/t simple: en los datos es la **t/t
  anualizada**. En 2025-T3 vale 6,4%, y la t/t del mensual desestacionalizado es 1,57%
  (1,0157⁴−1 ≈ 6,4%). Conviene anotarlo en `macro_series`. Con esa serie se puede reconstruir el
  nivel.

### actividad_mensual_indice / actividad_mensual_var12m

- **Qué mide cada indicador:**
  - **Estimaciones mensuales del PIB conciliadas con el trimestral:** EMAE (ARG), Imacec (CHL),
    IMAEc (ECU), PBI mensual (PER) e IMAE (URY). La diferencia en el crecimiento anual frente al
    PIB trimestral es 0,00 pp. IGAE (MEX, MAE 0,13 pp) e ISE (COL, 0,20 pp) están casi
    conciliados.
  - **Proxies no conciliadas:**
    - IBC-Br (BRA): el BCB lo construye por el lado de la oferta, sin balanceo, y recomienda
      compararlo en horizonte anual. MAE 0,55 pp y máximo 1,6.
    - IMAEP (PRY): MAE 0,96 pp; 2013: +15,8% frente a +8,3% del PIB.
    - IMAE de PAN: base 2007, frente a un PIB de referencia 2018; cubre ~85% del VA. MAE 0,9 pp.
    - IGAE de BOL: base 1990, discontinuado en 2024-12. MAE 1,8 pp; 2024: +0,7% frente a −1,1%.
  - **Producción industrial, no toda la economía:** el IPI de ESP y la IP G.17 de USA
    (manufactura, minería y servicios públicos). Frente al PIB, la correlación del crecimiento
    anual es 0,91 en ESP y 0,67 en USA. En 2023-24 la IP de USA cayó y el PIB creció ~3%. Ninguno
    de los dos países publica un mensual oficial de toda la economía.
- **ECU.** La var12m oficial está calculada sobre la serie desestacionalizada. Frente a la original
  difiere hasta 8 pp (2025-06: −6,5% frente a +1,6%). Se recalcula desde el índice original.
- **PAN.** La var12m oficial solo existe desde 2022, pero el índice del CSV permite calcularla desde
  2017 (±0,03 pp de error por el redondeo a 1 decimal).
- **Cálculos propios:** BRA, PRY, URY y USA (var12m) se calculan en el procesamiento, y la prueba
  los reproduce exactamente.

### pbi_nominal_anual

- **Escala.** Todas las series están en millones de moneda local corriente; ECU y PAN, en USD.
  Hay tres construcciones correctas que conviene tener presentes:
  - MEX es el **promedio** de 4 trimestres a tasa anual (la suma daría 4×).
  - BRA, ESP y URY son **suma** de 4 trimestres. BRA coincide con la cuenta anual y ESP con el PIB
    PDE.
  - ARG viene directo de la serie anual, así que no le afecta la anualización trimestral.
- **Conversión a USD.** Se usó el TC promedio anual del propio repositorio. Resultados para 2024,
  en miles de millones de USD:

  | País | 2024 |
  |---|---|
  | ARG | 638 |
  | BOL | 55 |
  | BRA | 2.186 |
  | CHL | 329 |
  | COL | 421 |
  | ECU | 124 |
  | ESP | 1.730 |
  | MEX | 1.832 |
  | PAN | 87 |
  | PER | 295 |
  | PRY | 45 |
  | URY | 82 |
  | USA | 29.381 |

  Los órdenes de magnitud son coherentes con las estimaciones internacionales conocidas. Ojo: esto
  es inferido, porque no se descargó el WEO para contrastarlo.
- **Argentina y Bolivia.** En ambos el TC oficial no refleja el mercado en parte del período:
  - ARG: cepo de 2011-15 y de 2019-25.
  - BOL: TC fijo de 6,96 con mercado paralelo desde 2023.

  Por eso el nivel en USD es C. Las variaciones nominales en moneda local son A, pero en ARG
  reflejan sobre todo la inflación.
- **Deflactor implícito.** Se calculó como nominal anual sobre la suma (o promedio) del real
  trimestral, y vale 100,0 en el año base en todos los países salvo ARG. En ARG da 25,0 si se suman
  los trimestres, lo que confirma la anualización, y 100 si se promedian.
- **Coberturas cortas.** BOL va de 2017 a 2024 y PAN de 2018 a 2025. Para PAN existe una **serie
  homogénea oficial 1996-2024** (INEC, nota metodológica de octubre de 2025, base 2018 y SCN 2008)
  que no está incorporada. URY empieza en 2016.

## Pruebas empíricas (resumen)

| Prueba | Qué se hizo | Resultado | Conclusión |
|---|---|---|---|
| Var12m recalculada | (X_t/X_{t-k}−1)·100 desde el nivel original, frente a la publicada | Dif. ≤0,06 pp en 10 países (trimestral) y 11 (mensual, sin ESP/USA). ECU: máx. 2,8 pp (trim.) y 8,1 pp (mens.); ESP 0,7; USA 1,7 | ECU, ESP y USA publican sobre la serie desestacionalizada; recalcular |
| Var12m desde el nivel desestacionalizado | Lo mismo, con `pbi_desest_trim` | Dif. 0 en ECU y ESP; 0,05 en USA | Confirma que su a/a oficial es desestacionalizada |
| Estacionalidad residual | ANOVA de dlog por trimestre/mes, sin 2020-21 | Desestacionalizadas: p entre 0,23 y 0,95, salvo URY p=0,047. Extras mensuales desestacionalizadas (ARG, BRA, CHL, MEX, PER, URY): p ≥0,6 | Ajustes correctos; Uruguay a validar |
| Trimestral frente a mensual | Crecimiento anual: suma de 4T frente a promedio de 12 meses, 2010+ | Dif. 0,00 en ARG, CHL, ECU, PER y URY; MEX 0,13; COL 0,20; BRA 0,55; PAN 0,92; PRY 0,96; BOL 1,79; ESP 1,59; USA 2,16 (MAE en pp) | Ver la clasificación del mensual |
| Suma anual SA frente a NSA | Cociente de las sumas anuales | Igual en ARG, COL, ECU y ESP; ±0,3% en BRA, CHL y MEX; URY es un índice; USA da 4× (SAAR) | Unidades distintas: rebasar |
| Escala del PIB nominal | Conversión a USD y deflactor en el año base | Deflactor = 100 en el año base; ARG = 25 con suma | Confirma que ARG está a tasa anual |

Las pruebas se hicieron con scripts temporales que no forman parte del proyecto; sus resultados están en este
documento.

## Recomendaciones para la "versión comparable"

1. **Variación a/a del PIB real desde el nivel original para todos.** Recalcularla en ECU (desde
   `Dem_Cad_bru`), ESP (desde `CNTR6721`) y USA (desde `ND000334`, 2003 en adelante). Para USA
   antes de 2003, conservar A191RO con una marca `base_ajuste=desestacionalizada`. Agregar una
   columna `base_variacion` ∈ {original, desestacionalizada} en `macro_series`.
2. **Rebase de niveles a un índice común** (p. ej. promedio de 2019 = 100) para `pbi_real_trim`,
   `pbi_desest_trim` y `actividad_mensual_indice`. Esto elimina las diferencias de moneda, de año
   base y la anualización (factor 4 en ARG, MEX y USA-SAAR).
3. **Documentar la anualización de ARG.** Anotar en `macro_series.notas` y en `ARG.md` que
   `pbi_real_trim` y `pbi_desest_trim` están a tasa anual. Si se calcula un anual real desde los
   trimestres, que sea el **promedio** (igual que para MEX).
4. **Crecimiento t/t desestacionalizado sin anualizar** como estándar del bloque. Anotar que el
   PN37939AQ de Perú y las tasas titulares de BEA son anualizadas. Para PER, construir
   `pbi_desest_trim` encadenando PN37939AQ.
5. **ECU mensual.** Recalcular `actividad_mensual_var12m` desde el IMAEc original.
6. **PAN.** Extender `actividad_mensual_var12m` desde el índice del CSV (2017+). Incorporar la serie
   homogénea anual 1996-2024 del INEC para `pbi_nominal_anual` y, si se publica, la real.
7. **PIB nominal en USD:**
   - Dividir por la media anual de `tc_usd_promedio` (en ESP, multiplicar, porque está en USD por
     EUR).
   - ECU, PAN y USA no necesitan conversión.
   - Marcar ARG y BOL con advertencia de régimen cambiario.
8. **Marcar el mensual por "tipo":** `pbi_mensual_conciliado` (ARG, CHL, COL, ECU, MEX, PER, URY),
   `proxy_no_conciliada` (BRA, PRY, PAN, BOL) y `produccion_industrial` (ESP, USA). Esto permite
   filtrar automáticamente en los estudios.
9. **Validar el desestacionalizado de Uruguay** re-desestacionalizando `pbi_real_trim` con X-13.
   Hoy no hay `statsmodels` en el entorno; habría que instalarlo o usar X-13 del Census.
10. **Guardar vintages** de las series con cifras preliminares (BOL, PAN, PRY, ARG y USA) para
    medir revisiones.

## Qué estudios son válidos con este bloque

**Válidos:**
- Comparar el crecimiento real a/a trimestral entre los 13 países, una vez recalculado desde el
  original en ECU, ESP y USA. Con el matiz de la base fija en ARG, PER, PRY, URY y MEX: no
  sobreinterpretar diferencias menores de ~0,5 pp.
- Ciclos, sincronización, correlaciones y turning points con el PIB trimestral desestacionalizado
  (t/t sin anualizar), en los 9 países con serie.
- Trayectorias de nivel rebasadas (p. ej. "cuánto está el PIB por encima de 2019").
- Nowcasting y ciclo mensual con los 7 países de mensual conciliado. Con BRA, PRY, PAN y BOL, solo
  como señal de ciclo.
- Tamaño relativo de las economías en USD corrientes, salvo ARG y BOL, que necesitan advertencia.

**No válidos:**
- Comparar niveles de PIB real en moneda local, o sumar o promediar niveles entre países.
- Comparar ratios al PIB construidos con PIB trimestral sumado en ARG o MEX (daría 4×).
- Usar el IPI de ESP o la IP de USA como "actividad económica" junto a los IMAE/IGAE de los demás.
- Mezclar tasas a/a sobre series desestacionalizadas (ECU, ESP y USA oficiales) con tasas sobre
  series originales, o tasas t/t anualizadas (USA, PER) con tasas sin anualizar.
- Estudios de largo plazo (antes de 2016-2018) para BOL, PAN y URY sin empalmes documentados.
- Ranking de tamaño o PIB per cápita en USD de Argentina y Bolivia al tipo oficial sin advertencia.

## Verificado frente a inferido

- **Verificado en documentación oficial:**
  - INDEC: niveles trimestrales a tasa anual (el Total es un promedio) y datos preliminares.
  - BCB: IBC-Br por el lado de la oferta, sin balanceo, con recomendación de comparar en horizonte
    anual.
  - DANE: X-13 con calendario y Semana Santa, encadenado con referencia 2015.
  - BCCh: X-13 ARIMA-SEATS con método indirecto, y Compilación de Referencia 2018.
  - INE España: SEC 2010, índices encadenados, corrección de calendario y coherencia anual.
  - INEC Panamá: IMAE base 2007 encadenado con 85% del VA y X-13; serie homogénea 1996-2024 con
    SCN 2008.
  - INEI: X-13 para el índice mensual; la base 2007 conserva aspectos del SCN 1993 e incorpora
    recomendaciones del SCN 2008.
  - BEA: consistencia con el SNA y estimaciones advance, second y third.
  - Fed G.17: cobertura, índice Fisher y base 2017.
  - CEPAL (2021): bases y precios constantes frente a encadenados.
- **Inferido o no verificado:**
  - La versión del SCN en BRA, COL, MEX, PRY y URY.
  - Que la base 2018 de MEX siga a precios constantes (base fija): CEPAL lo indica para la base
    2013.
  - El método de desestacionalización en ARG, BRA, ECU y URY.
  - El sesgo de la base fija lejana.
  - La plausibilidad del PIB en USD (no se contrastó con el WEO).
  - Que PN37939AQ sea la t/t anualizada: se dedujo de los datos, porque BCRPData no rotula la
    unidad.

## Fuentes consultadas

- INDEC, *Informe de avance del nivel de actividad*, II trim. 2026:
  https://www.indec.gob.ar/uploads/informesdeprensa/pib_09_26065D6A3612.pdf
- INDEC, Metodología nº 21 (citada en el informe):
  https://www.indec.gob.ar/ftp/cuadros/economia/metodologia_21_cuentas_nacionales.pdf
- CEPAL, *Seminario SCN hacia 2025* (años base y valoración por país, jun-2021):
  https://cepal.org/sites/default/files/presentations/seminario-scn-hacia-2025-datos-metadatos-contexto-alc-jun2021_0.pdf
- CEPAL, presentación de Bolivia (referencia 2017, SCN 2008):
  https://rtc-cea.cepal.org/sites/default/files/2026-06/presentacion-bolivia_0.pdf
- BCB, *IBC-Br e PIB: aspectos metodológicos e comparações*:
  https://www.bcb.gov.br/conteudo/relatorioinflacao/EstudosEspeciais/Metodologia_ibc-br_pib_estudos_especiais.pdf
- IBGE, nota técnica de las CNT (revisiones):
  https://www.ibge.gov.br/novo-portal-destaques/26231-nota-tecnica-sistema-de-contas-nacionais-trimestrais-3-trimestre-de-2019.html
- BCCh, Compilación de Referencia 2018:
  https://www.bcentral.cl/contenido/-/details/publicaciones/estadistica/cuentas-nacionales-de-chile-compilacion-de-referencia-2018
  ; nota sobre X-13: https://si3.bcentral.cl/estadisticas/Principal1/informes/BOLETIN/listado/BC001_2_Coment.pdf
- DANE, especificaciones del ajuste estacional del ISE:
  https://www.dane.gov.co/files/investigaciones/boletines/pib/ISE-especificaciones-modelos-ajuste-nal-noviembre2022.pdf
- BCE, metodología de las CNT (vista en el extracto del buscador; la descarga dio 403):
  https://datosabiertos.gob.ec/dataset/7d5ad4b3-a8f7-42d9-8103-81336a592ea6/resource/2b396e79-241b-485d-aa14-c8defc5f5199/download/metodologia-de-las-cuentas-nacionales-trimestrales.docx
- INE España, metodología de la CNTR: https://www.ine.es/daco/daco43/metodologia_cntr.pdf
- INEGI, cambio de año base SCNM 2018:
  https://www.inegi.org.mx/contenidos/saladeprensa/boletines/2023/SCNM/Act_SCNM_2018.docx
  ; boletín del IGAE (X-13ARIMA-SEATS): https://www.inegi.org.mx/contenidos/saladeprensa/boletines/2019/igae/igae2019_12.docx
- INEC Panamá, serie homogénea 1996-2024:
  https://www.inec.gob.pa/archivos/P0705547520251023143625Metodolog%C3%ADa%20Serie%20Homog%C3%A9nea%201996-2024.pdf
  ; nota técnica del IMAE base 2007:
  https://www.inec.gob.pa/archivos/A0705547520230519164310A0705547520230419150330Nota%20T%C3%A9cnica%20IMAE%20A%C3%B1o%20Base%202007.pdf
- INEI, marco conceptual de la base 2007:
  https://www.inei.gob.pe/media/MenuRecursivo/publicaciones_digitales/Est/Lib1799/cap04.pdf
  ; desestacionalización: https://www.inei.gob.pe/media/MenuRecursivo/metodologias/metodologia-de-desestacionalizacion.pdf
- BCRP, serie PN37939AQ:
  https://estadisticas.bcrp.gob.pe/estadisticas/series/quarterly/results/PN37939AQ/html
  ; Reporte de Inflación de junio de 2019, recuadro 3 (TRAMO-SEATS; leído en el extracto del buscador):
  https://www.bcrp.gob.pe/docs/Publicaciones/Reporte-Inflacion/2019/junio/ri-junio-2019-recuadro-3.pdf
- BCP, metodología del año base 2014 (página localizada, no leída en detalle):
  https://www.bcp.gov.py/web/institucional/w/sistema-de-cuentas-nacionales-de-paraguay-metodologia-a%C3%B1o-base-2014
- MEF Uruguay, ficha técnica del PIB real (base 2016; base 2005 anterior):
  https://www.mef.gub.uy/innovaportal/file/30704/18/ficha-tecnica-pib-real.pdf
- BEA, NIPA Handbook, cap. 1: https://www.bea.gov/resources/methodologies/nipa-handbook/pdf/chapter-01.pdf
- Federal Reserve, About G.17: https://www.federalreserve.gov/releases/g17/About.htm
- Referencias de estándar: SCN 2008 (ONU) y SEC 2010 (Eurostat).
