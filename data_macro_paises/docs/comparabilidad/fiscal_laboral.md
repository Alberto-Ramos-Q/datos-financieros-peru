# Comparabilidad entre países: bloque fiscal y mercado laboral

Indicadores: `resultado_fiscal_pct_pbi`, `deuda_publica_pct_pbi`, `desempleo`, `salario_minimo`.
El detalle por fila está en `fiscal_laboral.csv`. Revisión del 2026-10-21.

## Resumen ejecutivo

- **Fiscal: ningún par de países mide exactamente lo mismo.** Las coberturas van desde la Administración Central (PRY), el GNC (COL) o el gobierno federal (USA) hasta el SPNF (PER, ECU, BOL, PAN), el gobierno general (ESP) y el sector público consolidado con el banco central incluido (BRA, URY). Seis series de resultado y siete de deuda solo sirven para tendencias (grado C).
- **Deuda: la de México es neta y no bruta.** Además, la de Argentina y la de Ecuador no están consolidadas, y la de EE.UU. incluye ~24 pp de deuda intragubernamental. Solo ESP (PDE) y CHL (gobierno central, ≈ gobierno general) son de nivel A.
- **Los cocientes calculados aquí (ARG, BOL, COL, MEX) se reproducen exactamente** con el PBI de la tabla. El problema no es aritmético sino de concepto: en MEX el balance es presupuestario y no son los RFSP; en COL la base es caja; en BOL el PBI de referencia 2017 da déficits ~1,4 pp menores que los publicados con base 1990.
- **Desempleo: el mayor riesgo es la cobertura.** PER (solo Lima Metropolitana), ARG y BOL (urbano) no son tasas nacionales. El segundo riesgo es mecánico: hay trimestres móviles fechados en su último mes (BRA, CHL, PER), meses sueltos con estacionalidad de hasta 4 pp (COL) y una serie desestacionalizada (USA). México no tiene datos.
- **Salario mínimo: todo es comparable con un ajuste mecánico (B).** Hay que pasar a USD, mensualizar la tasa diaria de México (×30,4), pasar las 14 pagas de España a 12 (×14/12) y anualizar con el número de pagos legales (13 o 14). Las variaciones nominales son comparables (A). CHL, PAN y USA no están cubiertos.
- **Comparaciones seguras:** tendencias y ciclos del déficit y la deuda en pp, desempleo nacional en promedios trimestrales o anuales (BRA, CHL, COL, ECU desde 2021, ESP, PRY, URY, USA) y salario mínimo en USD normalizado.

## Tabla resumen (niveles / variaciones)

| País | resultado_fiscal | deuda_publica | desempleo | salario_minimo |
|---|---|---|---|---|
| ARG | C / C | C / C | C / B | B / A |
| BOL | A / A | NA | C / B | B / A |
| BRA | A / A | C / C | B / B | B / A |
| CHL | A / A | A / A | B / B | NA |
| COL | C / C | C / C | B / B | B / A |
| ECU | A / A | C / C | B / C | B / A |
| ESP | B / B | A / A | A / A | B / A |
| MEX | C / C | C / C | NA | B / A |
| PAN | A / C (2 obs.) | NA | C / C | NA |
| PER | A / A | B / B | C / C | B / A |
| PRY | C / C | B / B | A / A | B / A |
| URY | C / C | C / C | B / B | B / A |
| USA | C / C | C / C | B / A | NA |

Conteo por indicador (niveles; variaciones):

- **resultado_fiscal:** niveles A6, B1, C6; variaciones A5, B1, C7.
- **deuda:** niveles A2, B2, C7, NA2; variaciones iguales.
- **desempleo:** niveles A2, B6, C4, NA1; variaciones A3, B6, C3, NA1.
- **salario_minimo:** niveles B10, NA3; variaciones A10, NA3.

Criterio usado para las variaciones:

- **Fiscal y deuda:** cambio anual en pp del PBI.
- **Desempleo:** cambio interanual en pp, en trimestres calendario.
- **Salario:** variación % nominal.

El grado C permite usar la serie para tendencias y ciclos, pero no para comparar niveles.

## Hallazgos por indicador

### 1. Resultado fiscal (% PBI)

El concepto de referencia es el resultado global (préstamo o endeudamiento neto), positivo = superávit, del SPNF, gobierno general o central. Todas las series están en el signo correcto. En BRA se invierte el NFSP del BCB (verificado en el script, operación `neg`), y en ESP se usa la serie trimestral con el signo correcto en lugar de la anual invertida del BdE.

| País | Cobertura | Base | Concepto | ¿Lo calculamos? |
|---|---|---|---|---|
| ARG | Sector Público Nacional no financiero (sin provincias) | caja | resultado financiero | sí: IMIG / PBI INDEC |
| BOL | SPNF consolidado | caja (inferido) | global | sí: MEFP / PBI INE ref. 2017 |
| BRA | Sector público consolidado (incluye BCB y estatales sin Petrobras ni Eletrobras) | debajo de la línea; intereses devengados | NFSP nominal sin desvalorización cambial | no (solo el signo) |
| CHL | Gobierno Central Total | devengado | balance global | no |
| COL | Gobierno Nacional Central | caja | balance | sí: suma de 12 meses / PBI DANE |
| ECU | SPNF | devengado | resultado global | no |
| ESP | Administraciones públicas (gobierno general, SEC 2010) | devengado | capacidad o necesidad de financiación, suma móvil de 4 trimestres | no (se toma el T4) |
| MEX | Sector público **presupuestario** | flujos de caja | balance público (no RFSP) | sí: SG14 / PBI |
| PAN | SPNF | no verificado | balance total | no |
| PER | SPNF | no verificado | resultado económico | no |
| PRY | Administración Central (MEFP 2001) | no verificado | préstamo o endeudamiento neto | no |
| URY | Sector Público Consolidado (incluye BCU y BSE) | no verificado | resultado global | no |
| USA | Gobierno federal (presupuesto unificado), año fiscal oct-sep | mayormente caja | superávit o déficit | no |

Por qué importa:

- **Las coberturas centrales (ARG, COL, PRY, USA) no se deben comparar en niveles con SPNF o gobierno general.** En PRY quedan fuera los entes descentralizados (IPS, con superávit). En COL quedan fuera los territorios y Ecopetrol. En USA quedan fuera estados y municipios.
- **MEX está subestimado frente a su medida oficial amplia.** Tiene -4,97 % en 2024, mientras que el CEFP reporta RFSP de ~5,9 % del PIB para 2024.
- **COL difiere del MFMP (causación) hasta en ~1 pp,** según lo documentado en `docs/fuentes/COL.md`.
- **URY y BRA incluyen al banco central.** Su resultado cuasifiscal, más los swaps en el caso de BRA (no verificado), mete ruido que no tienen los SPNF.
- **USA mide año fiscal:** FY2025 va de oct-2024 a sep-2025 y está fechado en 2025-01-01, desfasado un trimestre del año calendario.
- **No hay series de resultado primario homogéneas en el bloque.** Solo existen como extras en BRA (`nfsp_primario_pct_pib_12m`) y ARG (mensual en pesos). Comparar el resultado global mezcla el esfuerzo fiscal con la carga de intereses: BRA tiene ~-8 % de resultado global, casi todo intereses.
- **Estándar MEFP:** solo PRY declara MEFP 2001 en la fuente, y ESP sigue SEC 2010. No se verificó la versión (1986, 2001 o 2014) que aplican PER, ECU, BOL, PAN y CHL.

### 2. Deuda pública (% PBI)

El concepto de referencia es la deuda bruta, consolidada, nominal y de fin de año.

- **ESP (A):** deuda PDE o Maastricht del gobierno general, consolidada y a valor nominal. Es el estándar.
- **CHL (A):** deuda bruta del Gobierno Central. Es ≈ gobierno general porque los municipios casi no se endeudan (inferido). Como referencia, la deuda neta es de 26,6 % en 2025, frente a 41,5 % de la bruta.
- **PER (B):** deuda bruta del SPNF, trimestral. Hay que tomar el T4.
- **PRY (B):**
  - Cubre el Sector Público Total.
  - El MEF divide el saldo en USD entre su propio PIB en USD.
  - En 2026 cambió ese denominador (41,1 % → 32,2 % sin que cambie la deuda), así que el cierre de 2026 tendrá un quiebre. Conviene recalcular con el PBI del BCP y el tipo de cambio.
- **ARG (C):**
  - Cubre la Administración Central, **sin consolidar**: incluye la deuda con el BCRA, el FGS y el BNA.
  - Muy sensible a la valoración cambiaria: 2023 = 154,5 % frente a 82,5 % en 2024. La presentación de Finanzas confirma ~155-157 % para 2023, frente a 91-98 % con otras métricas.
  - El salto se explica porque el stock va valuado al tipo de cambio de fin de año, después de la devaluación de dic-2023, y se divide entre un PBI del año. Esto es una inferencia sobre el mecanismo.
- **BRA (C):** DBGG con la metodología del BCB de 2008. Cuenta las compromisadas del BCB y no toda su cartera de títulos del Tesoro, así que queda unos 9 pp por debajo del concepto del FMI (2012: 58,7 % frente a 68 %, según la prensa).
- **MEX (C):** es deuda **neta** del sector público económico amplio y la calculamos nosotros: 46,2 % en 2024, frente a un SHRFSP oficial de 51,4 % (CEFP). No es ni bruta ni el SHRFSP.
- **ECU (C):** es una suma propia de deuda externa más interna, **sin consolidar**, así que queda por encima del indicador legal consolidado del MEF. Tiene un salto en jun-2021 por el reconocimiento de la deuda con el BCE.
- **COL (C):** solo cubre el Gobierno Nacional Central.
- **URY (C):** Sector Público Consolidado. Incluye el BCU (inferido), solo empieza en 2016 y el valor de 2025 (75,0 %, frente a 67,5 %) está pendiente de confirmar.
- **USA (C):**
  - Es la deuda bruta federal: 123,3 % en FY2025.
  - Incluye 23,8 pp en manos de los fondos del propio gobierno.
  - La deuda en manos del público es 99,5 % y sale de la misma tabla OMB 7.1.
  - No incluye estados ni gobiernos locales.
- **BOL y PAN (NA):** no hay serie oficial descargable.
- **Valoración:** todas las series son nominales (valor facial). No hay ninguna a valor de mercado.

### 3. Desempleo

| País | Encuesta | Cobertura | Edad | Frecuencia y tipo de dato | Ajuste estacional |
|---|---|---|---|---|---|
| ARG | EPH | 31 aglomerados urbanos (~2/3 de la población) | 10+ (verificado: la batería laboral se aplica a la población de 10 años y más) | trimestral | original |
| BOL | ECE | urbana | no verificado | mensual, un mes por dato | original |
| BRA | PNAD Contínua | nacional | 14+ | trimestre móvil fechado en su último mes | original |
| CHL | ENE | nacional | 15+ | trimestre móvil fechado en su último mes | original |
| COL | GEIH | nacional | 15+ (rediseño, series empalmadas) | mensual, un mes por dato | original |
| ECU | ENEMDU | nacional | no verificado | semestral hasta 2013, trimestral 2014-20, mensual desde 2021 | original |
| ESP | EPA | nacional | 16+ | trimestral | original |
| MEX | ENOE | — | — | sin datos (falta token) | — |
| PAN | EML | nacional | 15+ | anual, mes variable | original |
| PER | EPE | **Lima Metropolitana** | 14+ | trimestre móvil fechado en su último mes | original |
| PRY | EPHC | nacional sin 2 departamentos | 15+ | trimestral | original |
| URY | ECH | total país | no verificado | mensual, un mes por dato | original |
| USA | CPS | nacional | 16+ | mensual | **desestacionalizada** |

CIET:

- COL (rediseño de la GEIH) declara las resoluciones de la 17.ª, 19.ª y 20.ª CIET (verificado).
- PRY usa la terminología de la 19.ª CIET ("fuerza de trabajo"), según material secundario. No se verificó en la metodología oficial.
- Para el resto no se verificó la resolución aplicada.

La 19.ª CIET cambia sobre todo la medición de la *ocupación* (excluye la producción para autoconsumo). Su efecto sobre la *tasa de desocupación* es pequeño, así que no se considera la fuente principal de incomparabilidad.

Quiebres relevantes:

- **COL:** rediseño de la GEIH en 2021-22.
- **URY:** encuesta telefónica en 2020 y panel rotativo desde jul-2021. El INE pide cautela en la comparación intertemporal.
- **ECU:** cambio de frecuencia y de diseño en 2020-21.
- **CHL:** la recalibración con el Censo 2017 se retropoló a 2010, así que la serie desde 2010 no tiene quiebre.
- **BRA:** la serie empieza en 2012 y no se empalma con la PME.

### 4. Salario mínimo

| País | Unidad en la tabla | Único o variable | Pagos al año (inferido de la legislación; no verificado en esta revisión) |
|---|---|---|---|
| ARG | ARS/mes | único nacional | 13 (SAC) |
| BOL | BOB/mes | único | 13 (aguinaldo; el segundo aguinaldo es condicional y no se considera) |
| BRA | BRL/mes | nacional; hay pisos estatales más altos | 13 |
| COL | COP/mes | único | 13 (prima); no incluye el auxilio de transporte |
| ECU | USD/mes | único (SBU) | ~14 (décimo tercero y décimo cuarto) |
| ESP | EUR/mes **en 14 pagas** | único | 14 |
| MEX | MXN/**día** | zona general; la ZLFN es aparte y más alta | 365 días + 15 de aguinaldo |
| PER | PEN/mes | único (RMV) | 14 o más (2 gratificaciones + CTS; régimen general) |
| PRY | PYG/mes | único | 13 |
| URY | UYU/mes | nacional; los Consejos de Salarios fijan mínimos más altos | 13 |
| CHL, PAN, USA | — | no cubiertos (PAN por región, actividad y tamaño; USA por hora) | — |

Ninguna serie está convertida a USD ni anualizada en la tabla. Todas son nominales en moneda local.

## Pruebas empíricas

1. **Recálculo de los cocientes fiscales con el PBI de la tabla.**
   - BOL: `resultado_global_spnf / pbi_nominal_anual × 100` reproduce los 8 años al tercer decimal (2024: -32.929 / 379.230 = -8,683 %).
   - MEX: SG14 de diciembre / `pbi_nominal_anual` reproduce la serie (2024: -4,965 %), y la deuda neta ×1000 / PBI da 46,21 %.
   - ARG: con los crudos de datos.gob.ar, 2023 da -8,418 / 193,946 billones = -4,34 % y 2024 da +0,30 % (coincide con lo comunicado oficialmente).
   - Contraste externo de BOL: CEPAL da -10,1 % para 2024. Implica un PBI de ~326 mil millones de Bs, frente a 379 mil millones en la referencia 2017, una diferencia del 16 %. El déficit no cambia, cambia el denominador (inferido).
   - Contraste externo de MEX: el SHRFSP de 2024 es 51,4 % (CEFP), frente a 46,2 % de deuda neta.
   - Conclusión: la aritmética está bien. Las diferencias con las cifras oficiales son de concepto o de denominador.
2. **ESP, suma móvil:** el T4 de 2024 es -3,2 % (coincide con el PDE notificado, ~3,2 %) y el de 2023 es -3,3 %. La revisión posterior del PDE es de ~3,5 %, según mi recuerdo, sin verificar en la fuente. Puede haber diferencias de vintage de 0,1-0,2 pp.
3. **Deuda, magnitudes de 2025:** ESP 100,7; USA 123,3 (99,5 en manos del público); BRA 78,6; ARG 78,1; URY 75,0; ECU 66,3; COL 62,9; MEX 49,9 (neta); CHL 41,5; PRY 41,1; PER 30,1. El salto de ARG en 2023 (154,5 %) es el caso más extremo de valoración cambiaria.
4. **Trimestre móvil frente a promedio de meses:**
   - BRA: la media anual de los 4 trimestres calendario (meses 3, 6, 9 y 12) en 2025 es 5,88 %, frente a 5,95 % de la media de los 12 trimestres móviles. Es una diferencia menor, pero no son la misma cifra.
   - COL: en 2025 los meses sueltos van de 11,6 % (enero) a 7,0 % (noviembre). La media móvil de 3 meses suaviza el rango a 10,5-7,7.
   - URY: los promedios trimestrales de 2025 son 8,0, 7,7, 6,9 y 7,2.
5. **Estacionalidad** (desvío medio por mes frente al promedio del año, 2015-2025 sin 2020-21):
   - Amplitud: COL 4,1 pp; BOL 1,8; PER 1,6; BRA 1,2; ECU 0,9; URY 0,7; CHL 0,7; **USA 0,16** (desestacionalizada).
   - Volatilidad mensual (desvío estándar de la diferencia mensual): COL 1,30; BOL 0,72; BRA 0,30 y CHL 0,31 (trimestres móviles).
   - Conclusión: comparar meses sueltos entre países es inválido. Hay que agregar a trimestres o años.
6. **Salario mínimo en USD** (promedio de 2025, con `tc_usd_promedio`):

   | País | USD/mes (unidad de la fuente) | USD/mes equivalente con pagos extra (×N/12) |
   |---|---|---|
   | ESP | 1.337 (14 pagas; equivale a 1.560 en 12) | 1.560 |
   | URY | 575 | 623 |
   | ECU | 470 | 548 |
   | MEX | **14,5 por día** → 442 al mes (×30,4) | 460 |
   | BOL | 401 | 434 |
   | PRY | 379 | 411 |
   | COL | 352 | 381 |
   | PER | 317 | 370 |
   | BRA | 272 | 295 |
   | ARG | 253 | 275 |

   - Los órdenes de magnitud son razonables una vez que México se pasa de día a mes. Sin ese paso, México aparece en 14,5 "USD/mes".
   - Advertencia para BOL: el tipo de cambio oficial fijo (~6,86) sobrevaluaba el boliviano hasta 2025, y en 2026 el tipo de cambio de la tabla salta a ~10,7-11,8. El salario en USD de Bolivia tendrá un quiebre en 2026.
7. **Desempleo de ARG, verificación puntual:** el 2T-2026 de la tabla es 7,9 %, igual que en el informe de prensa del INDEC.

## Recomendaciones para la "versión comparable"

Transformaciones automatizables, para una capa derivada `comparable` en `processed/` sin tocar las series originales:

1. **Fiscal y deuda anual a partir de trimestrales:** para ESP (`resultado_fiscal_pct_pbi`) y PER (`deuda_publica_pct_pbi`), tomar `fecha.month == 10` (T4) y re-fechar al año.
2. **Etiquetas obligatorias de cobertura:** añadir la columna `cobertura_institucional` ∈ {AC/GNC/federal, GC, SPNF, GG, SPC con banco central} y la columna `base` ∈ {caja, devengado}. Filtrar o agrupar por ellas en cualquier gráfico de niveles.
3. **Alternativas de deuda en USA:** exponer "deuda en manos del público" (OMB 7.1, columna 8) como serie alternativa.
4. **PRY, deuda:** recalcular con el saldo en USD × `tc_usd_promedio` (o fin de año) / `pbi_nominal_anual` del BCP, para no heredar el cambio de denominador del MEF en 2026.
5. **Desempleo a trimestre calendario:**
   - Series de un mes por dato (BOL, COL, ECU desde 2021, URY, USA): promedio de los 3 meses del trimestre.
   - Trimestres móviles (BRA, CHL, PER): tomar los meses 3, 6, 9 y 12 y re-fecharlos al primer mes del trimestre, como en ARG, ESP y PRY.
   - USA: preferir LNU04000000 (sin ajuste) para homogeneizar con el resto, o desestacionalizar todas con X-13.
   - Calcular además el promedio anual y la variación interanual en pp.
6. **Dummies de quiebre en desempleo:** URY 2020-21, COL 2021-22, ECU 2020-21. Marcar además ARG, BOL y PER como no nacionales.
7. **Salario mínimo:**
   - `smin_mensual_lc`: MEX × 30,4; ESP × 14/12 si se quiere un mensual equivalente en 12 pagos.
   - `smin_usd`: dividir por `tc_usd_promedio`. ESP se **multiplica**, porque su tipo de cambio es USD por EUR, y ECU no se convierte.
   - `smin_anual_usd`: con la tabla de pagos anuales (13 o 14; MEX 365 + 15 días).
   - Opcional: `smin_real` deflactando con `ipc_indice`.

No automatizables (requieren otra fuente): RFSP y SHRFSP de México, balance en causación del MFMP de Colombia, SPNF de Paraguay y Uruguay, deuda consolidada de Ecuador y de Argentina en manos de privados, gobierno general de USA (BEA o FMI). Para un panel homogéneo de niveles fiscales, la alternativa práctica es complementar con FMI WEO o GFS (gobierno general) como serie de contraste, dejando claro que no es la fuente nacional.

## Qué estudios son válidos y cuáles no

**Válidos:**

- Ciclos y tendencias fiscales en pp del PBI: deterioro de 2020 y consolidación posterior, correlación del déficit con el ciclo del PBI o con los términos de intercambio. Vale para todas las series, con grado C o mejor.
- Niveles de déficit entre ESP, PER, ECU, BOL, PAN, BRA y CHL, con la cobertura etiquetada (SPNF o gobierno general).
- Niveles de deuda entre ESP y CHL, y PER con el T4. Los demás solo como "orden de magnitud con cobertura declarada".
- Desempleo nacional en promedios trimestrales o anuales: BRA, CHL, COL, ECU (2021+), ESP, PRY, URY y USA. Ley de Okun por país y sincronía de ciclos con variaciones interanuales en pp.
- Salario mínimo en USD normalizado (mensual y anual con pagos extra), su poder adquisitivo real y su relación con el PBI per cápita.

**No válidos:**

- Rankings de nivel de déficit o deuda que mezclen coberturas, por ejemplo MEX (presupuestario o deuda neta) frente a ESP (PDE), o ARG (Administración Central sin consolidar) frente a cualquiera.
- Usar la deuda de ARG en años de devaluación como medida de solvencia comparativa.
- Comparar meses sueltos de desempleo entre países (estacionalidad de 0,7-4 pp), o la tasa de PER (Lima) como si fuera nacional.
- Comparar el salario mínimo de México sin mensualizar, o el de España sin ajustar las 14 pagas.
- Comparar el salario de BOL en USD a través del cambio de régimen cambiario de 2025-26.
- Estudios largos de desempleo de URY, COL o ECU que crucen sus rediseños sin dummies.

## Fuentes consultadas

Documentación oficial:

- INDEC, EPH, informe de prensa del 2T-2026: https://www.indec.gob.ar/uploads/informesdeprensa/mercado_trabajo_eph_2trim26433FCBC5A8.pdf (31 aglomerados urbanos, batería laboral para 10 años y más, 7,9 %).
- DANE, nuevo enfoque de la GEIH: https://www.dane.gov.co/files/investigaciones/fichas/empleo/Comunicado_prensa_nuevo_enfoque_GEIH.pdf (CIET 17, 19 y 20; PET de 15+; CNPV 2018).
- INE Chile, fortalecimiento de la ENE: https://www.ine.cl/docs/default-source/ocupacion-y-desocupacion/publicaciones-y-anuarios/separatas/temáticas/separata-técnica-fortalecimiento-ene-febrero-2020.pdf y la metodología ENE 2020: https://si3.bcentral.cl/estadisticas/Principal1/Metodologias/MLD/INE/Metodologia_ENE_ene_2020.pdf
- INE Uruguay, nota metodológica de la ECH de julio de 2021: https://www5.ine.gub.uy/documents/ANDA/ECH/2021/Nota%20metodologica%20ECH%20Julio%202021.pdf
- INEI, boletines de la EPE de Lima Metropolitana (PET de 14+, trimestre móvil): https://www.inei.gob.pe/media/MenuRecursivo/boletines/11118.pdf
- INE Paraguay, EPHC: https://www.ine.gov.py/publicacion/3/empleo
- INE Bolivia, ECE (catálogo ANDA): https://anda.ine.gob.bo/index.php/catalog/254
- BCB, dataset 13762 (DBGG, metodología de 2008): https://dadosabertos.bcb.gov.br/en/dataset/13762-divida-bruta-do-governo-geral--pib---metodologia-utilizada-a-partir-de-2008
- OMB, Historical Tables 1.2 y 7.1: https://www.whitehouse.gov/omb/budget/historical-tables/
- Secretaría de Finanzas de Argentina, datos trimestrales de la deuda: https://www.argentina.gob.ar/economia/finanzas/datos-trimestrales-de-la-deuda
- CEFP (Cámara de Diputados, México), nota 008/2025 (SHRFSP y RFSP de 2024): https://cefp.gob.mx/publicaciones/nota/2025/notacefp0082025.pdf
- MEFP Bolivia, ejecución del SPNF: https://www.economiayfinanzas.gob.bo/index.php/ejecucion-sector-publico-no-financiero
- BLS, definiciones de la CPS: https://www.bls.gov/cps/definitions.htm

Secundarias, usadas solo como contraste:

- CEPAL, Balance Preliminar o Estudio Económico de Bolivia (déficit de 2024 de ~10,1 %).
- Prensa brasileña de 2013 sobre la diferencia entre la DBGG del BCB y la del FMI.
- Presentaciones de Finanzas de Argentina citadas por Chequeado.

Material local: `data/processed/macro_series.csv`, `macro_observaciones.parquet`, `docs/fuentes/*.md` y `src/paises/{arg,bol,bra,col,esp,mex}.py`.

**Afirmaciones sin verificar en la documentación oficial (inferidas):**

- La base caja del SPNF de Bolivia.
- Que el PBI base 1990 explique la diferencia de Bolivia con CEPAL.
- La inclusión de los swaps en los intereses del NFSP de Brasil.
- Que la deuda del SPC de Uruguay incluya los instrumentos del BCU.
- Que el sector público total de Paraguay tenga menos déficit que la Administración Central.
- El número de pagos anuales de salario de cada país (tomado de la legislación laboral conocida, no contrastado aquí).
- La edad mínima en BOL, ECU y URY.
- La versión del MEFP que aplican PER, ECU, PAN y CHL.
