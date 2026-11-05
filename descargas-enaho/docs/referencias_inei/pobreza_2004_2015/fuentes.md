# Fuentes oficiales: pobreza monetaria 2004–2015

Todas se descargaron el **2026-11-03** desde sitios oficiales (inei.gob.pe, proyectos.inei.gob.pe o
cdn.www.gob.pe). Se usó `curl` con un User-Agent de navegador; ninguna página pidió desafío anti-bot.
Las claves de la columna `fuente` de `config/pobreza_oficial_2004_2015.csv` son las de esta tabla.
En `pagina` va la página del PDF, no la numeración impresa.

| Clave | Título (INEI) | Publicado | Archivo | URL |
|---|---|---|---|---|
| R2011 | *Informe Técnico: Evolución de la Pobreza 2004-2010. Nueva Metodología* (incluye fe de erratas; serie nueva 2004–2010 con IC; grupos de departamentos 2004–2010) | 2011; esta versión del PDF es de mar-2012 | `informe_pobreza_2004-2010_nueva_metodologia.pdf` | https://proyectos.inei.gob.pe/iinei/srienaho/Descarga/DocumentosMetodologicos/2004-55/Informe-Tecnico-Pobreza.pdf |
| R2012 | *Informe Técnico: Evolución de la Pobreza 2007-2011* | may-2012 | `informe_pobreza_2007-2011.pdf` | https://www.inei.gob.pe/media/cifras_de_pobreza/pobreza_informetecnico.pdf |
| R2013 | *Informe Técnico: Evolución de la Pobreza Monetaria 2007-2012* | may-2013 | `informe_pobreza_2007-2012.pdf` | https://cdn.www.gob.pe/uploads/document/file/3297779/Informe%20T%C3%A9cnico.pdf?v=1656364592 |
| R2014 | *Evolución de la Pobreza Monetaria 2009-2013. Informe Técnico* | may-2014 | `informe_pobreza_2009-2013.pdf` | https://www.inei.gob.pe/media/cifras_de_pobreza/informetecnico.pdf |
| P2014 | *Perú: Perfil de la Pobreza por Dominios Geográficos, 2004-2013* | ago-2014 | `perfil_pobreza_dominios_2004-2013_Lib1169.pdf` | https://www.inei.gob.pe/media/MenuRecursivo/publicaciones_digitales/Est/Lib1169/libro.pdf |
| R2015 | *Informe Técnico: Evolución de la Pobreza Monetaria 2009-2014* | abr-2015 | `informe_pobreza_2009-2014.pdf` | https://www.inei.gob.pe/media/cifras_de_pobreza/informetecnico_pobreza2014.pdf |
| R2016 | *Evolución de la Pobreza Monetaria 2009-2015. Informe Técnico* (anexos con **dos decimales**) | abr-2016 | `informe_pobreza_2009-2015_Lib1347.pdf` | https://www.inei.gob.pe/media/MenuRecursivo/publicaciones_digitales/Est/Lib1347/libro.pdf |
| P2016 | *Perú: Perfil de la Pobreza por dominios geográficos, 2004-2015* | ago-2016 | `perfil_pobreza_dominios_2004-2015_Lib1370.pdf` | https://www.inei.gob.pe/media/MenuRecursivo/publicaciones_digitales/Est/Lib1370/libro.pdf |
| R2017 | *Evolución de la Pobreza Monetaria 2007-2016. Informe Técnico* | may-2017 | `informe_pobreza_2007-2016.pdf` | https://www.inei.gob.pe/media/cifras_de_pobreza/pobreza2016.pdf |
| R2018 | *Evolución de la pobreza monetaria 2007-2017. Informe técnico* | abr-2018 | `informe_pobreza_2007-2017_Lib1533.pdf` | https://www.inei.gob.pe/media/MenuRecursivo/publicaciones_digitales/Est/Lib1533/libro.pdf |
| R2020 | *Informe Técnico: Evolución de la Pobreza Monetaria 2008-2019* | may-2020 | `informe_pobreza_2008-2019.pdf` | https://www.inei.gob.pe/media/cifras_de_pobreza/informe_pobreza2019.pdf |
| R2021 | *Informe Técnico: Evolución de la Pobreza Monetaria 2009-2020* | may-2021 | `informe_pobreza_2009-2020.pdf` | https://www.inei.gob.pe/media/MenuRecursivo/publicaciones_digitales/Est/pobreza2020/Pobreza2020.pdf |
| R2022 | *Evolución de la Pobreza Monetaria 2010-2021. Informe Técnico* | may-2022 | `informe_pobreza_2010-2021.pdf` | https://www.inei.gob.pe/media/MenuRecursivo/publicaciones_digitales/Est/pobreza2021/Pobreza2021.pdf |
| R2023 | *Evolución de la Pobreza Monetaria 2011-2022. Informe Técnico* | may-2023 | `informe_pobreza_2011-2022.pdf` | https://www.inei.gob.pe/media/MenuRecursivo/publicaciones_digitales/Est/pobreza2022/Pobreza2022.pdf |
| R2024 | *Perú: Evolución de la Pobreza Monetaria 2014-2023. Informe Técnico* (**primera** con cifras puntuales por departamento, desde 2014) | may-2024 | `informe_pobreza_2014-2023.pdf` | https://cdn.www.gob.pe/uploads/document/file/6578175/5558423-peru-evolucion-de-la-pobreza-monetaria-2014-2023.pdf?v=1720047420 |
| R2025 | *Perú: Evolución de la Pobreza Monetaria, 2015-2024. Informe Técnico* | may-2025 | `informe_pobreza_2015-2024.pdf` | https://cdn.www.gob.pe/uploads/document/file/8058556/6763186-peru-evolucion-de-la-pobreza-monetaria-2015-2024.pdf |
| B2007 | *Informe Técnico: Medición de la pobreza 2004, 2005 y 2006* (**metodología anterior**; solo como referencia del quiebre, no se transcribió) | jul-2007 | `informe_medicion_pobreza_2004-2006_bol7008.pdf` | https://www.inei.gob.pe/media/MenuRecursivo/boletines/7008.pdf |
| X1 | *Población en situación de pobreza monetaria, según ámbito geográfico, 2015-2025* (xlsx, índice temático) | 2026 | `inei_cd1_82_pobreza_ambitos.xlsx` | https://www.inei.gob.pe/media/MenuRecursivo/indices_tematicos/cd1_82.xlsx |
| X2 | *Población en situación de pobreza extrema monetaria, según ámbito geográfico, 2015-2025* (xlsx) | 2026 | `inei_cd2_73_pobreza_extrema_ambitos.xlsx` | https://www.inei.gob.pe/media/MenuRecursivo/indices_tematicos/cd2_73.xlsx |

El informe más reciente, *Perú: Evolución de la Pobreza Monetaria 2016-2025* (may-2026), ya está en
`docs/enaho/2025/7_Informe_tecnico_de_pobreza/` y empieza en 2016, así que no aporta cifras 2004–2015.

## Qué se usó de cada fuente

| Cifra | Fuente vigente (la más reciente que la publica) | Cuadro y página del PDF |
|---|---|---|
| Ámbitos (nacional, área, Lima Met., resto urbano, regiones, dominios) 2004–2006 | P2016 (valor); R2011 (IC y regiones) | P2016 C4.1–4.2 p.89; R2011 p.25 (total) y p.28 (extrema) |
| Ámbitos 2007 | R2018 | III.1 p.128; III.4 p.131 |
| Ámbitos 2008 | R2020 | III.1 p.127; III.4 p.130 |
| Ámbitos 2009–2015 con dos decimales | R2016 (coinciden con las vigentes al redondear) | III.1 p.120; III.4 p.121 |
| Ámbitos 2009–2015 con un decimal | R2021 a R2025 según el año | III.1 / III.4 de cada informe |
| IC y CV de cada año | el informe de ese año: R2011 (2004–2010, sin CV), R2012 (2011), R2013 (2012), R2014 (2013), R2015 (2014), R2016 (2015) | anexo III.1 / III.4 |
| Departamentos, cifra puntual 2014 y 2015 | R2024 (2014) y R2025 (2015) | III.1 p.255 y p.222 |
| Grupos de departamentos, pobreza total | R2011 (2004–2006, composición y rango), R2018 (2007), R2020 (2008), R2021 (2009), R2022 (2010), R2023 (2011–2013), R2024 (2014), R2025 (2015) | C3.2 / C4.2: p.18, 47, 42, 45, 63, 68, 73, 72 |
| Grupos de departamentos, pobreza extrema | R2022 (2010), R2023 (2011–2013), R2024 (2014), R2025 (2015) | C3.4 / C4.4: p.70, 77, 80, 78 |

Si el valor y el IC vienen de publicaciones distintas, `fuente` y `pagina` llevan las dos separadas
por `|` (primero la del valor y luego la del IC), p. ej. `P2016|R2011` y `89|25`. El IC solo se toma
si el informe del año publica la misma estimación puntual que la serie vigente.

## Codificación de `ambito` en el CSV

- `nacional`, `area_urbana`, `area_rural`, `resto_urbano`, `resto_pais` (país sin Lima Met.).
- `lima_metropolitana`: Lima Metropolitana **con** el Callao (dominio 8); así la publican los
  anexos de ámbitos de todos los años.
- `region_costa|sierra|selva`; `dominio_<region>_<area>` (sin Lima Metropolitana).
- `dpto_XX`: departamento por `ubigeo[:2]`. `dpto_15LM` es la provincia de Lima (43 distritos,
  ubigeo 1501), `dpto_15LR` la región Lima (sus otras nueve provincias) y `dpto_07` el Callao.
- `grupoN:c1+c2+…`: grupo N de departamentos «estadísticamente semejantes». `15+07` es «Lima», que
  incluía al Callao hasta los datos de 2012. Desde 2013 los grupos separan `15LM`, `15LR` y `07`.
  `ic_inf` y `ic_sup` son los límites publicados (IC 95 % de la incidencia conjunta del grupo) y
  `valor` va vacío.
- Indicador `pobreza_total_rango` (solo 2004–2006, R2011 p.18): los límites del cuadro de grupos del
  informe de marzo de 2012 vienen en % enteros y **no** son el IC del grupo. Lo que muestran depende
  del grupo:
  - en los grupos de un departamento, su IC 95 % redondeado;
  - en los de varios departamentos, la menor y la mayor estimación puntual de los miembros,
    redondeadas a entero.

  El INEI no lo explica en el informe. Se dedujo contrastando con la base local, y se cumple en los
  17 grupos de 2004–2006 y en los de 2010 (ver la validación, §2.3). En 2007 el grupo 1 (Huancavelica,
  61–72) es una errata: la estimación es 85,0 y R2018 publica 80,9–89,1. Por eso de ese cuadro solo
  se transcribieron 2004–2006.

## Cómo se transcribió

1. Las tablas se leyeron con PyMuPDF a partir de las coordenadas y la dirección de cada línea de
   texto: los anexos vienen rotados 90° y `pdftotext -layout` desordena filas y columnas. Las tablas
   del informe R2011 y todos los cuadros de grupos se cotejaron además con la página renderizada.
2. `cifras_todas_publicaciones.csv` guarda todas las cifras 2004–2015 leídas de los anexos de las 16
   publicaciones (2 523 filas: una por publicación, año, ámbito e indicador; `rank` ordena las
   publicaciones de la más antigua a la más reciente). Sirve para cotejar publicaciones. Las 377 claves
   (año × indicador × ámbito) que aparecen en más de una publicación coinciden al redondear a un
   decimal, salvo las de 2013 del perfil P2014 (ver la validación, §2.2).
3. La transcripción manual de R2011 (155 cifras) coincide en todos los casos con las publicaciones
   posteriores.
4. No entró nada dudoso:
   - Sierra y Selva 2005 van sin valor, porque el PDF los deja en blanco; solo llevan el IC.
   - Del cuadro de grupos de R2011 no se tomó 2007–2010, porque para esos años hay cuadros más
     recientes con IC y el de 2007 tiene una errata.
   - No se usó la serie de metodología anterior (B2007 y la «serie anterior» de R2011, con
     proyecciones del CPV 1993).
