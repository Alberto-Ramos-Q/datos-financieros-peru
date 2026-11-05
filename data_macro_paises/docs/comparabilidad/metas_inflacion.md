# Metas de inflación por país (historia)

Tabla: `config/comparable/metas_inflacion.csv`. Tiene 111 tramos para 13 países y se revisó el
2026-10-21. Sirve para calcular la desviación de `inflacion_12m` respecto de la meta de cada banco
central.

## Cómo leer la tabla

- **Una fila por tramo vigente**, sin solapamientos dentro de cada país. `hasta` vacío = vigente hoy.
- **`desde`** es la fecha desde la que rige la meta. En las metas anuales es el 1 de enero del año
  al que se refieren, aunque se anunciaran meses antes (o, en PER 1994–1999, meses después). La
  fecha de anuncio va en `notas`.
- **Periodo sin fila = sin meta explícita.** Por ejemplo, la Fed antes de 2012, ARG antes de
  oct-2016 o PRY antes de 2011. Solo hay filas `sin_meta` para BOL, ECU y PAN (nunca tuvieron meta)
  y para ARG desde oct-2018 (abandono de la meta).
- **Anuncios que nunca rigieron** (BRA 2003 3,25 % y 2004 3,75 %; ARG 2018 8–12 %, 2019 y 2020)
  quedan fuera de la tabla. Se mencionan en `notas` del tramo que los reemplazó.
- **Cálculo sugerido de la desviación:**
  - Con `meta_centro`: `inflacion_12m − meta_centro`.
  - Si solo hay rango: usar el punto medio y marcar el dato.
  - Con `techo`: la distancia al techo, o `max(0, inflación − techo)`.
  - Con `horizonte = diciembre_de_cada_anio`: la meta se evalúa en el dato de diciembre. En los
    otros meses la desviación es solo indicativa.
- **Validación (Python):** el script comprueba lo siguiente, y la tabla pasa todo sin errores ni
  huecos entre tramos consecutivos:
  - no hay solapes por país y hay a lo sumo un tramo vigente;
  - `desde < hasta`;
  - el centro está dentro del rango y los rangos no están invertidos;
  - los tipos y horizontes son válidos;
  - todas las filas tienen `fuente_url`.

## Resumen por país

| País | Tramos | Régimen actual | Historia |
|---|---|---|---|
| ARG | 5 | Sin meta (desde oct-2018) | 4T-2016: objetivo de ≤1,5 % mensual. 2017: 12–17 %. 2018: 15 % (recalibrado el 28-dic-2017), luego < 22 % a 12 meses (jun-2018, acuerdo con el FMI). Desde el 1-oct-2018: meta de base monetaria. |
| BOL | 2 | Sin meta | Ancla cambiaria hasta el 25-jun-2026. Desde el 26-jun-2026: tipo de cambio flexible y ancla en la base monetaria. Primera meta de inflación prevista para anunciarse en jul-2028, con horizonte a 2030. |
| BRA | 27 | 3 % ±1,5 continuo (desde 2025) | Metas anuales del CMN para 1999–2024. La banda pasó de ±2 a ±2,5 (2003–2005), a ±2 (2006–2016) y a ±1,5 (desde 2017). |
| CHL | 11 | 3 % (2–4 %), horizonte de unos 2 años | Metas anuales decrecientes en 1991–2000, de 15–20 % a 3,5 %. Meta continua del 3 % desde 2001. |
| COL | 19 | 3 % ±1 (desde 2010) | Metas anuales en 1992–2009, puntuales hasta 2002 y después en rango. |
| ECU | 1 | Sin meta (dolarizado, desde 2000) | — |
| ESP | 6 | 2 % simétrico, IAPC zona euro | Banco de España 1995–1998 (IPC España): < 3 %, 2,5 % y cerca del 2 %. BCE: < 2 % (1999), "inferior pero cerca del 2 %" (may-2003) y 2 % simétrico (jul-2021, confirmado en jun-2025). |
| MEX | 9 | 3 % ±1, permanente (desde 2003) | Metas anuales en 1995–1999 (de 42 % a 13 %) y techos en 2000–2002 (10 %, 6,5 % y 4,5 %). |
| PAN | 1 | Sin meta (dólar de curso legal desde 1904) | — |
| PER | 11 | 2 % (1–3 %) continuo (desde feb-2007) | Rangos anuales en 1994–2001. 2,5 % ±1 desde 2002: a diciembre hasta 2005 y continuo desde 2006. |
| PRY | 5 | 3,5 % ±2 (desde 2025) | Metas explícitas desde 2011: 5 ±2,5, después 5 ±2 (2014), 4,5 ±2 (2015), 4 ±2 (2017) y 3,5 ±2 (2025). |
| URY | 11 | 4,5 % ±1,5 (3–6 %) | Rangos móviles del COPOM en 2004–2007. Después: 3–7 % (2008), 4–6 % (jun-2011), 3–7 % (jul-2014), 3–6 % (sep-2022) y meta puntual de 4,5 % con tolerancia (dic-2024/2025). |
| USA | 3 | 2 % PCE, meta flexible (desde ago-2025) | 2 % PCE desde ene-2012. Promedio flexible (FAIT) entre ago-2020 y ago-2025. |

## Casos especiales

### Metas sobre otro índice (`coincide_con_repositorio = no`)

- **USA (3 tramos):** la meta es el PCE (BEA) y el repositorio usa el CPI-U (BLS). El CPI suele
  quedar unos 0,3–0,5 pp por encima del PCE, por ponderaciones, cobertura y fórmula; el dato no
  está medido en el repositorio. La desviación con el CPI va sesgada hacia arriba.
- **ESP, BCE (3 tramos, desde 1999):** la meta es el IAPC de la **zona euro**, no el IPC de
  España. Una desviación positiva del IPC español no implica un incumplimiento del BCE. Los tramos
  del Banco de España de 1995–1998 sí se definen sobre el IPC español (`si`).
- **ARG, 4T-2016 (1 tramo):** el objetivo se medía con el IPC-GBA; el IPC nacional del repositorio
  empieza en dic-2016.
- **PER y PRY:** la meta se define sobre el IPC de Lima Metropolitana y sobre el IPC del BCP (Área
  Metropolitana de Asunción), los mismos índices del repositorio (`si`). En las comparaciones
  entre países hay que recordar que cubren solo la capital (ver `precios.md`).
- **URY antes de 2011:** el IPC del INE de entonces cubría, según parece, solo Montevideo (no
  verificado). La tabla pone `si` porque la meta usaba el IPC oficial vigente, pero conviene
  revisar cómo empalma el repositorio la serie total país.

### Metas anuales y medición en diciembre

- **Metas anuales decrecientes** (`meta_anual_decreciente`): CHL 1991–2000, COL 1992–2002, MEX
  1995–1999 y PER 1994–2001. Las de MEX 2000–2002 se anunciaron como techo y van con `tipo = techo`.
- Las de COL no fueron estrictamente decrecientes: en 1997 subió a 18 % desde el 17 % de 1996.
- En COL 2003–2009, BanRep fijaba rangos con una meta puntual "para efectos legales". Esa meta
  está verificada solo en 2005, 2006 y 2009. En 2003, 2004, 2007 y 2008 va como `rango`.
- **BRA 1999–2024:** metas por año calendario del CMN (dic-dic).
- **PER 2002–2005:** se evaluaba a diciembre, igual que en las metas anuales.

### Cambios de régimen y particularidades

- **BRA 1999:** el régimen nació con el Decreto 3.088 (21-jun-1999). El tramo empieza el
  30-jun-1999, fecha de la Res. 2.615, aunque la meta se mide sobre dic-1998 a dic-1999.
- **BRA 2003–2004:** las metas originales (3,25 % y 3,75 %) se revisaron antes de entrar en vigor
  y quedaron en 4 % ±2,5 y 5,5 % ±2,5. Además, el BCB trabajó con una "meta ajustada" de 8,5 %
  para 2003 (Carta Abierta del 21-ene-2003). En la tabla va la meta del CMN; la ajustada va en
  notas.
- **BRA 2025:** meta continua de IPCA a 12 meses. Se considera incumplida tras 6 meses seguidos
  fuera de la banda (Decreto 12.079 y Res. CMN 5.141).
- **ARG:**
  - La meta de 2017 se fijó cuando aún no existía el IPC nacional; se evaluó con él.
  - El 7-jun-2018 se reemplazó la meta de 15 % por la de < 22 % a 12 meses.
  - Desde el 1-oct-2018 el ancla es la base monetaria, después agregados y bandas cambiarias.
  - Hasta 2026 no hay meta de inflación.
- **USA:** el objetivo numérico (2 %) no cambió en 2012–2026; cambió la estrategia, con la
  compensación por promedio entre ago-2020 y ago-2025. Por eso hay tres tramos con la misma cifra.
- **ESP 1995–1996:** el "por debajo del 3 %" era un objetivo de convergencia a alcanzar en unos
  tres años, no un techo para cada mes. La desviación de esos años debe leerse frente a una senda
  (referencia intermedia: 3,5–4 % a comienzos de 1996).
- **URY 2004–2007:** el COPOM fijaba rangos para ventanas móviles de 12 a 18 meses que se solapaban.
  Para evitar solapes, cada rango rige desde el inicio de su ventana hasta que empieza la ventana
  del rango siguiente. 2007 se asigna a 4,5–6,5 %, el rango con que el BCU evaluó ese año. El 4–6 %
  anunciado para 2008 rigió solo hasta la ampliación a 3–7 % en ene-2008.
- **URY dic-2024:** el paso de "rango meta 3–6 %" a "meta de 4,5 % ±1,5" no cambia las cifras.
  Cambia el encuadre, y la fecha de corte es convencional.
- **CHL desde 2001:** un solo tramo. El horizonte pasó de 12–24 meses a "en torno a 2 años", en
  una fecha no verificada entre 2005 y 2008.
- **BOL:** el BCB y el Programa Fiscal-Financiero publican **proyecciones** de inflación de fin de
  año, a veces con rango (IPM de ene-2017: 5 % ±1), pero no son metas. La reforma de jun-2026
  prevé el paso a metas de inflación hacia 2028–2030.

## Fuentes

Todas las filas tienen una URL oficial en `fuente_url`. Las principales:

- **BRA:**
  - BCB, *Histórico de metas para a inflação*: https://www.bcb.gov.br/controleinflacao/historicometas
    (la versión en texto está en `/api/paginasite/sitebcb/controleinflacao/historicometas`).
  - Res. CMN 5.141: https://www.bcb.gov.br/estabilidadefinanceira/exibenormativo?tipo=Resolu%C3%A7%C3%A3o%20CMN&numero=5141
  - Decreto 12.079 (Cámara de Diputados).
- **ARG:** BCRA:
  - comunicados del 27-sep-2016 y del 28-dic-2017;
  - IPOM de jul-2017;
  - documento técnico del 7-jun-2018;
  - IPOM de oct-2018;
  - *Objetivos y Planes* 2016–2026.
- **USA:** Federal Reserve, comunicados de prensa del 25-ene-2012, 27-ago-2020 y 22-ago-2025, y
  *Statement on Longer-Run Goals* (PDF).
- **ESP / BCE:**
  - Diarios de Sesiones del Congreso (comparecencias del gobernador del BdE, 1994 y 1997);
  - Boletín Económico del BdE (1997);
  - Ley 13/1994 (BOE);
  - notas de prensa del BCE del 13-oct-1998, 8-may-2003, 8-jul-2021 y 30-jun-2025.
- **CHL:** BCCh:
  - Documentos de Trabajo 55, 106, 115 y 408;
  - Memorias Anuales 1998, 1999 y 2000;
  - *Chile's monetary policy*;
  - Boletines de nov-2005 y abr-2008.
- **MEX:** Banxico, Informes Anuales 1995–2002 y Programa Monetario 2023.
- **COL:** BanRep, Borradores de Economía 141 y 202, Informes de la Junta Directiva al Congreso
  (mar-2003 a mar-2010) y comunicado de oct-2009.
- **PER:** BCRP:
  - Revista *Estudios Económicos* 7 (Cuadro 1);
  - Programa Monetario de ene-2002;
  - Reporte de Inflación de ene-2006;
  - Memoria 2007.
  - El sitio bloquea el acceso directo; se leyó en copias de archive.org de las mismas URL
    oficiales.
- **PRY:** BCP:
  - serie oficial *Meta de inflación* (xlsx);
  - notas de prensa de dic-2014, feb-2017 y dic-2024;
  - anuncio del régimen de may-2011.
  - El sitio responde 403; se leyó en archive.org.
- **URY:**
  - BCU, Informes de Política Monetaria 2003–2013 y IPOM de oct-2026;
  - MEF, comunicados del Comité de Coordinación Macroeconómica (27-ago-2020 y 20-dic-2024).
- **BOL:**
  - Ley 1670 del BCB;
  - IPM de ene-2017;
  - comunicado CP 14/2021 (Programa Fiscal-Financiero);
  - Programa Monetario 2026;
  - RIPoM del III-2026.
- **ECU:** Código Orgánico Monetario y Financiero (copia publicada por la SEPS).
- **PAN:** Ley 84 de 1904 (reproducción de la Biblioteca Nacional) y Constitución de 1972 (Órgano
  Judicial).

Fuentes secundarias, usadas solo para orientarse y no para cifras: el FMI (PRY 2008), LatinNews
(fecha de URY 2008) y la prensa sobre BOL y ARG.

## Qué quedó sin verificar

Tramos incluidos con algún dato sin verificar (lo indican las `notas`):

- **CHL 1992–1994:** las cifras (15, 11 y 10 %) salen de una tabla del BCCh y parecen centros de
  rangos. Los rangos (13–16, 10–12 y 9–11 %) no se verificaron, y el 15 % de 1992 no coincide con
  el centro de 13–16.
- **URY:**
  - No se verificó en fuente oficial la fecha en que el 4–6 % pasó a 3–7 % (ene-2008; el 11-ene
    sale de una fuente secundaria). Afecta a los tramos que empiezan el 2008-01-01 y el
    2008-01-11.
  - Inicio del 4–6 %: jun-2011 o may-2011, según el informe.
- **COL:** las metas puntuales legales de 2003, 2004, 2007 y 2008, por lo que esas filas solo
  tienen rango.
- **PER:** la fecha del paso a la medición continua (ene-2006 según el Reporte de Inflación,
  feb-2007 según la Memoria 2007).
- **CHL:** la fecha del cambio de horizonte, de 12–24 meses a 2 años.
- **ARG:** la fecha del primer anuncio del objetivo del 4T-2016. Tampoco se revisaron uno por uno
  los *Objetivos y Planes* de 2021–2023, aunque los de 2019–2020 y 2024–2026 no tienen meta.
- **BRA 2025:** el "horizonte de 24 meses", que no figura en el decreto ni en la resolución.
- **ESP:**
  - los objetivos propios de 1996;
  - la fecha exacta de la programación de 1997;
  - la primera reunión del BCE que aplicó la estrategia de 2021.
- **ECU:** la fecha del R.O. de la Ley de Transformación Económica (13-mar-2000), confirmada solo en
  fuentes secundarias.
- **PAN:** una declaración oficial expresa de que no hay banco central emisor.
- **BOL:** el tipo de cambio fijo desde nov-2011.

Omitido por falta de respaldo oficial:

- COL 1991 (sin cifra oficial).
- ARG 2016, rango de 20–25 % (anuncio del Ejecutivo, no del BCRA).
- PRY 2008, rango de 2,5–7,5 % sobre inflación subyacente (solo en el FMI).
- PRY 2004–2010 (no se hallaron rangos del BCP).
- MEX antes de 1995 (el Informe Anual 1994 no da cifra).
- Una supuesta senda de URY hacia 3–5 % o 4 % (no hay anuncio oficial hasta oct-2026).
