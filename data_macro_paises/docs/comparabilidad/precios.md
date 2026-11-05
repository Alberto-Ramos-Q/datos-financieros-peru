# Comparabilidad entre países: precios y expectativas de inflación

Bloque `precios`. Indicadores: `ipc_indice`, `inflacion_mensual`, `inflacion_12m`,
`inflacion_subyacente_12m` y `expectativa_inflacion_12m`. Hay 13 países y 65 pares. El detalle
por par está en `precios.csv`. Revisión del 2026-10-21.

## Resumen ejecutivo

- La **inflación total (mensual y 12m) es comparable directamente en 10 de 13 países**. Las
  variaciones publicadas coinciden con las calculadas desde el índice; la diferencia máxima es de
  0,06 pp y se debe al redondeo.
- **Perú y Paraguay** miden la inflación de la capital (Lima Metropolitana y Área Metropolitana de
  Asunción), no la nacional. Es la cobertura de la meta de sus bancos centrales, así que es correcta
  para cada país, pero sus cifras se comparan **con cautela** con los IPC nacionales (grado C).
- **Error a corregir:** `inflacion_mensual` de EE.UU. es la **única serie desestacionalizada**
  del bloque. Hay que recalcularla desde el índice NSA, un ajuste mecánico (grado B).
- La **inflación subyacente no es comparable en niveles en ningún par** (11 países en C y 2 sin
  dato). Hay al menos 6 definiciones distintas: sin alimentos ni energía, sin volátiles, medias
  recortadas, exclusión variable, núcleo sin estacionales ni regulados, y sin alimentos ni
  regulados.
- **Las expectativas son comparables en 5 países** (BRA, CHL, COL, MEX, URY): son encuestas a
  analistas, mediana, a unos 12 meses. Las de **EE.UU. son de hogares** y las de **Perú se
  interpolan** desde años calendario (ambas en C). Las de **Argentina** necesitan un corte en 2016
  (grado B).
- El **índice** (`ipc_indice`) sirve para comparar solo después de rebasarlo a un periodo común.
  Las bases y los años de inicio son muy distintos: ARG desde 2016, PAN desde 2024, ECU desde 2020.

## Tabla resumen (niveles / variaciones)

| País | ipc_indice | inflacion_mensual | inflacion_12m | inflacion_subyacente_12m | expectativa_inflacion_12m |
|---|---|---|---|---|---|
| ARG | B / A | A / A | A / A | C / C | B / B |
| BOL | B / A | A / A | A / A | C / C | NA |
| BRA | B / A | A / A | A / A | C / C | A / A |
| CHL | B / A | A / A | A / A | C / C | A / A |
| COL | B / A | A / A | A / A | C / C | A / A |
| ECU | B / A | A / A | A / A | NA | NA |
| ESP | B / A | A / A | A / A | C / C | NA |
| MEX | B / A | A / A | A / A | C / C | A / A |
| PAN | B / A | A / A | A / A | NA | NA |
| PER | C / C | C / C | C / C | C / C | C / C |
| PRY | C / C | C / C | C / C | C / C | NA |
| URY | B / A | A / A | A / A | C / C | A / A |
| USA | B / A | **B / B** | A / A | C / C | C / C |

Conteo:
- `ipc_indice`: 11 B/A y 2 C.
- `inflacion_mensual`: 10 A, 1 B y 2 C.
- `inflacion_12m`: 11 A y 2 C.
- `inflacion_subyacente_12m`: 11 C y 2 NA.
- `expectativa_inflacion_12m`: 5 A, 1 B, 2 C y 5 NA.

En `ipc_indice`, el grado de niveles es B porque comparar niveles de índices con bases distintas
no tiene sentido sin rebasarlos. Para las tasas (inflación y expectativas), "niveles" es el valor
de la tasa y "variaciones" son sus cambios o su dinámica.

## Hallazgos por indicador

### 1. `ipc_indice`: cobertura, canasta y estándar

| País | Cobertura | Meta del BC sobre este índice | Base / ponderaciones | Clasificación | Vivienda propia | Verificado |
|---|---|---|---|---|---|---|
| ARG | Nacional urbano, 6 regiones | No hay meta formal | dic-2016; ENGHo 2004/05 | CCIF 1999 | Excluida | Sí (metodología INDEC) |
| BOL | 6 capitales + 3 conurbaciones | No (tipo de cambio fijo) | 2016 | no verificado | no verificado | Cobertura sí (nota INE) |
| BRA | Familias urbanas de 1 a 40 SM, áreas SNIPC | Sí (IPCA, CMN) | POF 2017-18 | no verificado | Excluida (inferido, no verificado) | Cobertura sí (IBGE) |
| CHL | Capitales regionales y conurbaciones (urbano) | Sí | 2023; EPF IX | no verificado | no verificado | Cobertura sí (INE) |
| COL | 38 ciudades | Sí | dic-2018; ENPH 2016-17 | COICOP, 12 divisiones | **Incluye arriendo imputado** | Sí (DANE) |
| ECU | Precios de 9 ciudades urbanas; ponderaciones urbanas y rurales | No (dolarizado) | jul-2025/jun-2026; ENIGHUR 2024-25 | **CCIF 2018** (antes 1999) | Excluida (universo: viviendas alquiladas) | Sí (metodología INEC) |
| ESP | Nacional | No: el BCE apunta al IPCA de la zona euro | 2025 | **ECOICOP v2** | Excluida (práctica IPCA; no verificado en el documento) | Clasificación sí |
| MEX | 55 ciudades | Sí | 2Q jul-2018 | no verificado | **Incluye renta imputada** | Sí (INEGI, RDE 38) |
| PAN | Nacional urbano, todas las provincias | No (dolarizado) | 2024; EIGH 2017/18 | **CCIF 2018** | no verificado | Sí (nota técnica INEC) |
| PER | **Lima Metropolitana** | **Sí** (BCRP) | dic-2021; ENAPREF 2019-20 | CCIF, 12 divisiones | **Excluida** | Sí (metodología INEI) |
| PRY | **Área Metropolitana de Asunción** | **Sí** (BCP) | dic-2017; 465 productos | no verificado | no verificado | Cobertura sí (anexo BCP) |
| URY | Total país (también Montevideo e Interior) | Sí | oct-2022; ENGIH 2016-17 | **CCIF 2018** | **Excluida** (valor locativo) | Sí (metodología INE) |
| USA | Urbano (CPI-U, ~93-94% de la población) | No: la Fed apunta al PCE | Base 1982-84 | Clasificación propia del BLS | **Incluye OER** (~1/4 del índice) | Sí (BLS) |

Por qué importa:

- **Cobertura.** En PER y PRY la capital pesa menos que el país y tiene otra canasta: los
  alimentos pesan menos y los servicios más. No hay forma mecánica de llevarla a una cifra
  nacional. Por eso estos dos países quedan en C. En el resto, "nacional" quiere decir casi
  siempre *urbano nacional*, una diferencia menor que se acepta como A.
- **Vivienda propia.** EE.UU. (OER), México y Colombia imputan un alquiler a la vivienda propia. El
  resto la excluye, como recomienda el enfoque de "adquisiciones monetarias" del Manual del IPC
  2020, que admite ambos tratamientos. Lo tratamos como diferencia menor (A en las variaciones),
  **con una advertencia**: cuando hay shocks de vivienda, como en EE.UU. en 2022-2024, el
  componente imputado puede explicar cerca de 1 pp de diferencia en la inflación total. No lo
  medimos con datos del repositorio porque no contiene los subíndices.
- **Clasificación.** ECU, PAN, URY y ESP ya usan COICOP 2018 (13 divisiones). ARG, COL y PER usan
  la versión de 12 divisiones. Esto no afecta el índice general, pero sí cualquier comparación por
  división (vivienda, comunicaciones, recreación).
- **Ponderaciones antiguas.** ARG usa una canasta de 2004/05, la más antigua del bloque; según la
  prensa, el peso de vivienda pasaría de 9,4% a 14,5% con la ENGHo 2017/18. El cambio se postergó
  en feb-2026.

### 2. `inflacion_mensual` e `inflacion_12m`

- Son series publicadas por la fuente, salvo en EE.UU., donde se calculan desde el índice igual
  que lo hace el BLS. Todas son originales salvo `inflacion_mensual` de EE.UU., que viene de
  CUSR0000SA0 (desestacionalizada).
  **Corregido el 2026-10-21:** ahora `inflacion_mensual` de EE.UU. se calcula desde CUUR0000SA0
  (original) y la desestacionalizada pasó a la serie extra `inflacion_mensual_desest`. Grado: A/A.
- **Redondeo de la fuente:** ARG, ESP y CHL publican con 1 decimal, BRA, MEX y COL con 2, y el resto
  con precisión completa. Es irrelevante para la variación 12m. En la mensual introduce un ruido
  de hasta ±0,05 pp.
- **PRY** calcula la variación desde un índice redondeado a 1 decimal. La mensual queda en
  escalones de ~0,07 pp (por ejemplo, ago-2026 = 0,0%).
- **Quiebres:**
  - ARG: solo desde 2017. La serie extra `*_bcra_hist` arrastra el IPC-GBA intervenido de
    2007-2015 (D en ese tramo).
  - PAN: la variación 12m de 2024 está calculada con la base 2013 y la de 2025 en adelante con la
    base 2024.
  - CHL: `inflacion_mensual` desde 1928 mezcla bases sin empalmar; `inflacion_12m` empieza en 2011.
  - COL: no se deben recalcular variaciones desde el índice antes de 1980, por el error de redondeo.
  - Hiperinflaciones o inflación muy alta: BOL 1985 (23.447% a 12 meses), PER 1990 (12.377%),
    BRA 1990 (6.821%), además de ARG, URY y MEX en los 80. Los índices son continuos a través de
    los cambios de moneda (BRA, URY, BOL), pero cualquier estudio de régimen normal debe separar
    esos tramos.

### 3. `inflacion_subyacente_12m`: no hay dos iguales

| País | Definición | Tipo | Quién la publica |
|---|---|---|---|
| ARG | Núcleo: sin estacionales ni regulados | Exclusión fija | INDEC |
| BOL | ITI Subyacente: sin los 5 mayores y 5 menores cambios por ciudad ni estacionales | Exclusión variable | BCB |
| BRA | IPCA-MS, medias recortadas con suavizado (12m calculado aquí) | Estadística | BCB |
| CHL | IPC sin volátiles (IPCSV), 172 subclases en la base 2023 | Exclusión fija por volatilidad | INE / BCCh |
| COL | Sin alimentos ni regulados | Exclusión fija | BanRep (datos DANE) |
| ESP | Sin alimentos no elaborados ni productos energéticos | Exclusión fija | INE |
| MEX | Subyacente: sin agropecuarios, energéticos ni tarifas del gobierno | Exclusión fija | INEGI / Banxico |
| PER | Sin alimentos y energía (Lima) | Exclusión fija | BCRP (datos INEI) |
| PRY | Sin frutas y verduras ni servicios tarifados (la X1 excluye además combustibles) | Exclusión fija | BCP |
| URY | IPC-CE VFCTA: sin frutas, verduras, combustibles, tarifas ni administrados (desde 2023-10) | Exclusión fija | INE |
| USA | Sin alimentos ni energía | Exclusión fija | BLS |
| ECU, PAN | No publican subyacente oficial | — | — |

La medida más cercana a una común es "sin alimentos y energía", que aplican de forma estricta solo
EE.UU. y Perú. Las demás excluyen además los regulados (COL, MEX, URY, ARG) o menos componentes
(ESP conserva los alimentos elaborados, PRY conserva la energía). Por eso todas quedan en C.

### 4. `expectativa_inflacion_12m`

| País | Quién responde | Estadístico | Horizonte exacto | Fecha de la encuesta → fecha asignada |
|---|---|---|---|---|
| ARG | Analistas (REM) | Mediana | Próximos 12 meses | Últimos 3 días hábiles del mes t → t |
| BRA | Analistas (Focus) | Mediana, suavizada, respuestas de 30 días | 12 meses adelante | Último dato del mes t → t |
| CHL | Académicos, consultores y ejecutivos financieros (EEE) | Mediana | Variación 12m del IPC "en 11 meses" (mes t+11) | Primeros días del mes t → t |
| COL | Entidades financieras y centros de investigación (EME) | Mediana | 12 meses | Publicación a mediados del mes t → t |
| MEX | Especialistas del sector privado | Mediana | Próximos 12 meses | Mes t → t (faltan los diciembres) |
| PER | Sistema financiero y analistas | Promedio simple de los dos grupos | **Interpolado** desde el año en curso y el siguiente | Segunda quincena del mes t → t |
| URY | Analistas (BCU) | Mediana | Próximos 12 meses | "Fecha encuesta" → t |
| USA | **Hogares** (SCE, panel de ~1.300) | Mediana | Un año adelante | Durante el mes t → t |
| BOL, ECU, ESP, PAN, PRY | Sin encuesta oficial cargada | — | — | — |

- **ARG.** La serie del BCRA mezcla dos encuestas: el REM 2004-2012, cuyos encuestados pronosticaban
  el IPC-GBA oficial intervenido (de ahí el ~10% de 2007-2012), y el REM actual desde jun-2016. Hay
  un hueco de oct-2012 a may-2016. La nota de `macro_series.csv` dice que "el REM empezó en 2016",
  pero el documento metodológico del BCRA se refiere a la experiencia del REM entre 2004 y 2012.
  Hay que truncar desde 2016-06.
- **PER.** No hay una pregunta directa a 12 meses. Según las notas del BCRP, que no pudimos abrir
  porque el sitio bloquea la descarga y solo vimos los extractos del buscador y de la prensa, se
  pondera la expectativa del año en curso por los meses restantes y la del año siguiente por el
  complemento. El resultado se promedia entre sistema financiero y analistas. Es una construcción
  distinta: grado C.
- **USA.** Los hogares tienen un sesgo conocido hacia arriba. En los datos, la expectativa de la
  SCE supera en promedio en +0,6 pp a la inflación corriente, mientras que en las encuestas de
  analistas queda entre −0,3 y −0,9 pp por debajo (ver pruebas). No se debe mezclar en niveles.
- **Horizontes.** Las diferencias de ±1 mes (CHL "en 11 meses" frente a "próximos 12 meses") no
  cambian el grado.

## Pruebas empíricas

Todas se hicieron sobre `macro_observaciones.parquet`, con scripts temporales que no forman parte del proyecto.

1. **Inflación 12m recalculada desde el índice frente a la publicada** (diferencia absoluta
   máxima en todo el tramo común):

   | País | Diferencia máx. | Lectura |
   |---|---|---|
   | BOL, ECU, PAN, PER, PRY, USA | 0,000 pp | Idénticas |
   | URY | 0,007 | Redondeo |
   | MEX | 0,005 (desde 2000) | Redondeo |
   | BRA | 0,009 | Redondeo |
   | COL | 0,023 desde 2000; **25,4 pp** antes de 1980 | Índice con 2 decimales |
   | ARG, ESP | 0,05 | Publicación con 1 decimal |
   | CHL | 0,057 | Publicación con 1 decimal |

   Conclusión: no hay quiebres de base ocultos en ninguna serie del repositorio.

2. **Inflación mensual publicada frente a la calculada desde el índice.** En 12 países la
   diferencia es ≤0,06 pp (COL ≤0,017 desde 2000; ARG y ESP ≤0,05; CHL ≤0,06). En **EE.UU.** la
   diferencia absoluta media es de **0,16 pp/mes** (máximo 0,55 desde 2000), porque la serie es SA
   y el índice NSA.

3. **Ajuste estacional.** Corrimos un ANOVA del desvío de la inflación mensual respecto de su media
   móvil de 13 meses, por mes calendario, desde 2010 (desde 2017 para ARG). En 9 países la
   estacionalidad es significativa (p < 1e-5): BRA, CHL, COL, ECU, ESP, MEX, PER, PRY y URY. En
   ARG, BOL y PAN es débil (p = 0,07-0,12), por muestra corta o baja estacionalidad, y la
   documentación confirma que son originales. **EE.UU.: F = 0,4, p = 0,97**, sin estacionalidad, lo
   que confirma que es SA. La misma prueba sobre la variación calculada desde el índice NSA de
   EE.UU. da F = 14,2.

4. **Correlación de la subyacente con la total (12m, desde 2018).**

   | País | Correlación de niveles | Correlación de Δ mensual | Desv. est. sub / total |
   |---|---|---|---|
   | BOL | **0,998** | 0,96 | 1,00 |
   | ARG | 0,997 | 0,99 | 1,01 |
   | PRY | 0,98 | 0,85 | 0,94 |
   | CHL | 0,97 | 0,73 | 0,78 |
   | COL | 0,94 | 0,81 | 0,80 |
   | USA | 0,92 | 0,67 | 0,70 |
   | PER | 0,89 | 0,67 | **0,51** |
   | MEX | 0,84 | 0,46 | 0,96 |
   | URY (36 meses) | 0,74 | 0,64 | 1,26 |
   | BRA | 0,72 | 0,44 | 0,91 |
   | ESP | **0,67** | 0,22 | 0,79 |

   - La subyacente de BOL casi no filtra nada. El núcleo del BCB (serie extra) filtra más:
     correlación 0,976 y Δ 0,81.
   - En ARG la correlación alta se explica por la inflación alta y generalizada.
   - La X1 de PRY se separa más de la total (0,875).
   - Conclusión: las subyacentes tienen propiedades estadísticas muy distintas y no son
     intercambiables entre países.

5. **Desfase de las expectativas.**
   - **Fechas.** Revisamos la última fecha disponible. CHL, COL y URY ya tienen oct-2026, con la
     inflación solo hasta sep-2026, lo que es coherente con encuestas de principio de mes. Las
     demás llegan a sep-2026.
   - **Correlaciones.** Correlacionamos Δ expectativa(t) con Δ inflación(t−j). No aparece un pico
     anómalo que indique fechas corridas un mes: en CHL el máximo está en j = 0 (0,50), en PER en
     j = 1 (0,50) y en COL es plano entre j = −1 y 1.
   - **RMSE.** El error frente a la inflación realizada a t+11 y a t+12 casi no cambia (diferencia
     de 0,02 a 0,1 pp), así que no se puede distinguir un desfase de un mes.
   - **Huecos.** ARG tiene 45 meses faltantes (2005-01 y oct-2012/may-2016), MEX los diciembres de
     2020 a 2025 y CHL feb-ago 2001.
   - **Sesgo medio** (expectativa − inflación corriente, desde 2010; ARG desde 2017): USA +0,62;
     URY −0,30; PER −0,47; MEX −0,49; CHL −0,84; BRA −0,91; COL −0,95; ARG −18,5 (desinflación de
     2024).
   - Conclusión: no hay series desfasadas. La diferencia relevante es quién responde.

## Recomendaciones para la versión comparable

Transformaciones automatizables, en orden de prioridad:

1. **USA `inflacion_mensual`:** recalcularla desde `CUUR0000SA0` (NSA). Para eso, cambiar
   `codigo_fuente` a `CUUR0000SA0|var1m` y conservar la SA como serie extra
   (`inflacion_mensual_sa`).
2. **ARG `expectativa_inflacion_12m`:** filtrar a fecha ≥ 2016-06.
3. **Rebasar `ipc_indice`** a un periodo común. Usar dic-2021 o el promedio de 2019. Solo valen
   los países con dato en ese periodo, porque PAN empieza en 2024.
4. **Marcar tramos de régimen:** hiperinflación o inflación muy alta (BOL 1982-87, PER 1988-91,
   BRA antes de 1995, ARG `*_bcra_hist` 2007-2015 como no confiable). Agregar una columna `flag`
   en la vista comparable en vez de borrar datos.
5. **Subyacente armonizada "sin alimentos y energía"** donde exista oficialmente. Hoy la tienen USA
   y PER. Habría que agregar CHL (IPC SAE del INE), BRA (EX-FE del BCB) y PRY (X1 o "sin alimentos,
   combustibles y tarifados" del Cuadro 5). Para BOL, usar `inflacion_nucleo_12m` en lugar del ITI
   Subyacente. Así el grado podría subir a B en esos países.
6. **Cobertura PER/PRY:** agregar el IPC nacional del INEI (Perú) como serie extra para
   comparaciones de cobertura país. En PRY no existe una alternativa nacional oficial.
7. **Huecos:** no imputar (USA oct-2025, MEX diciembres). Si un modelo necesita series completas,
   interpolar en la vista, nunca en `processed`.

## Qué estudios son válidos con este bloque

**Válidos:**
- Comparar la inflación total 12m y mensual (NSA, tras corregir EE.UU.) entre ARG (desde 2017),
  BOL, BRA, CHL, COL, ECU, ESP, MEX, PAN, URY y USA: niveles, persistencia, volatilidad y
  sincronía del ciclo inflacionario.
- Ranking de países por inflación y episodios de desinflación, si se incluye a PER y PRY con una
  nota de cobertura (su sesgo frente a una medida nacional suele ser pequeño, pero no está medido).
- Medir la inflación frente a la meta *de cada país*: para PER y PRY el índice de la capital es
  justamente el de la meta.
- Credibilidad y anclaje de expectativas entre BRA, CHL, COL, MEX, URY y ARG (desde 2016).
- Dinámica de la subyacente *dentro* de cada país y correlaciones o ciclos entre países.

**No válidos o con reservas fuertes:**
- Comparar niveles de inflación subyacente entre países ("la core de México es mayor que la de
  Chile"): cada país usa otra definición.
- Mezclar las expectativas de EE.UU. (hogares) con las de analistas en un panel de niveles, o
  comparar el nivel de las de Perú (interpoladas, promedio) con medianas de otros países sin
  advertirlo.
- Usar ARG antes de 2017 (IPC) o las expectativas de ARG antes de 2016 en comparaciones.
- Comparar el nivel de los índices sin rebasarlos, o la inflación acumulada de PAN y ECU antes de
  2024 y 2020 sin un empalme documentado.
- Comparar la inflación de ESP con la de la zona euro (habría que usar el IPCA) o la de EE.UU. con
  la meta de la Fed (el PCE no está en el repositorio).
- Comparar componentes por división COICOP sin conciliar las versiones 1999 y 2018.

## Fuentes consultadas

Documentación oficial (las marcadas con * se leyeron completas o en la parte relevante):
- INDEC, *Metodología del IPC* (base dic-2016)*: https://www.indec.gob.ar/ftp/cuadros/economia/metodologia_ipc_nacional_2019.pdf
- BCRA, *Relevamiento de Expectativas de Mercado (REM)*, dic-2024*: https://www.bcra.gob.ar/archivos/Pdfs/PublicacionesEstadisticas/consideraciones-relevamiento-expectativas-mercado.pdf
- INE Bolivia, notas del Excel de la serie empalmada del IPC*, y BCB, notas de "Inflacion subyacente.xlsx" e "Inflacion nucleo.xlsx"* (crudos del repositorio; página https://www.bcb.gob.bo/?q=content/sector-precios).
- IBGE, IPCA: https://www.ibge.gov.br/estatisticas/economicas/precos-e-custos/9256-indice-nacional-de-precos-ao-consumidor-amplo.html
- BCB, Nota Técnica 57 (dic-2025), metodología de los núcleos: https://www.bcb.gov.br/content/publicacoes/notastecnicas/NT_57_202512.pdf
- BCB, API Olinda de expectativas (Focus): https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/ExpectativasMercadoInflacao12Meses
- INE Chile, IPC base 2023: https://www.ine.gob.cl/estadisticas/economia/indices-de-precio-e-inflacion/indice-de-precios-al-consumidor
- BCCh, reestimación del IPC sin volátiles: https://www.bcentral.cl/w/reestimacion-del-ipc-sin-volatiles-tras-el-cambio-de-canasta ; boletín de la EEE: https://si3.bcentral.cl/estadisticas/Principal1/informes/BOLETIN/listado/BJ001a_Coment.pdf
- DANE, actualización metodológica del IPC 2019: https://www.dane.gov.co/index.php/estadisticas-por-tema/precios-y-costos/indice-de-precios-al-consumidor-ipc/ipc-actualizacion-metodologica-2019
- BanRep, ficha metodológica de la EME: https://www.banrep.gov.co/sites/default/files/paginas/encuesta-expectativas-mensual-analistas-ficha-metodologica.pdf
- INEC Ecuador, *Metodología del IPC base jul-2025/jun-2026*: https://www.ecuadorencifras.gob.ec/documentos/web-inec/Inflacion/2026/julio/Metodologia_Indice_de_Precios_al_Consumidor_IPC.pdf
- INE España, *Principales características de la base 2025*: https://www.ine.es/metodologia/t25/principales_caracteristicas_base_2025.pdf ; nota de prensa: https://ine.es/dyngs/Prensa/adIPC0126.htm
- INEGI, *Revista de Datos y Estadística* 38 (renta de vivienda e imputación): https://rde.inegi.org.mx/wp-content/uploads/2022/pdf/RDE38/RDE38_art05.pdf
- Banxico, encuestas a especialistas: https://www.banxico.org.mx/publicaciones-y-prensa/encuestas-sobre-las-expectativas-de-los-especialis/
- INEC Panamá, *Nota técnica del IPC base 2024*: https://www.inec.gob.pa/archivos/P053342420260819111558NOTA%20T%C3%89CNICA%20IPC%202025.pdf
- INEI, *Metodología del IPC de Lima Metropolitana, base dic-2021*: https://www.inei.gob.pe/media/MenuRecursivo/metodologias/metodologia_ipclm_dic_2021.pdf
- BCRP, Notas de Estudios (expectativas; solo extractos del buscador, el sitio bloqueó la descarga): https://www.bcrp.gob.pe/docs/Publicaciones/Notas-Estudios/2024/nota-de-estudios-53-2024.pdf
- BCP, anexo estadístico del IPC (crudo del repositorio)* y página de la metodología base 2017 (no accesible, error 403): https://www.bcp.gov.py/web/institucional/w/indice-de-precios-al-consumidor-ipc-metodologia-base-diciembre-2017
- INE Uruguay, *Metodología IPC base oct-2022*: https://www5.ine.gub.uy/documents/Estad%C3%ADsticasecon%C3%B3micas/PDF/IPC/2022/Metodolog%C3%ADa%20IPC%202022.pdf ; página del IPC y la subyacente: https://www.gub.uy/instituto-nacional-estadistica/indice-precios-consumo
- BLS, ficha sobre OER y alquiler: https://www.bls.gov/cpi/factsheets/owners-equivalent-rent-and-rent.htm
- FRBNY, *Staff Report 800* (diseño de la SCE): https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr800.pdf

Fuentes secundarias (solo como indicio, marcadas como no verificadas en el texto): prensa sobre la
postergación del nuevo IPC de INDEC (iProfesional, feb-2026), la X1 de Paraguay (La Nación PY) y el
peso de la vivienda propia en el INPC (Crónica, may-2025).

**No verificado en la documentación oficial:**
- Clasificación y tratamiento de la vivienda propia en BOL, BRA, CHL y PRY.
- Exclusión de la vivienda propia en el IPC de ESP base 2025.
- Definición oficial de la subyacente de COL en la web del BanRep.
- Detalle de la suavización del Focus.
- Si la mediana de la SCE se calcula sobre respuestas puntuales o sobre medias de densidad.
- Horizonte exacto de la EME (COL) y de la encuesta del BCU (URY).
