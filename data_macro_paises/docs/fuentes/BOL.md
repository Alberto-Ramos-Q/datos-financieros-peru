# Bolivia (BOL) — fuentes oficiales

Descargador: `src/paises/bol.py` · Series: `config/series/BOL.csv` (34 series: 23 de los 28
indicadores comunes + 11 adicionales, 3 de ellas para la capa comparable) · Salida: `data/interim/BOL_observaciones.parquet`.

## Instituciones y accesos

| Fuente | Institución | Qué se usa | Acceso | Formato |
|---|---|---|---|---|
| `BCB` | Banco Central de Bolivia — páginas `https://www.bcb.gob.bo/?q=content/sector-externo-0`, `…/sector-monetario`, `…/sector-precios`, `?q=estad-sticas-semanales`, `?q=tasas-de-inter-s-activas&field_tipo_de_tasa_activa_value=asf`, `?q=tasas-de-inter-s-pasivas&field_tipo_de_tasa_pasiva_value=pa` | Tipo de cambio oficial, comercio exterior, balanza de pagos, RIN, remesas, agregados, balance del sistema financiero, inflación subyacente/núcleo, tasas del sistema financiero, estadísticas semanales | Público, sin clave; archivos en `https://www.bcb.gob.bo/webdocs/…` | `.xlsx` |
| `INE` | Instituto Nacional de Estadística — `https://www.ine.gob.bo/index.php/…` y `https://www.ine.gob.bo/referencia2017/…` | IPC (serie empalmada 1937-), PIB trimestral y anual (referencia 2017), IGAE, empleo urbano (ECE), salario mínimo nacional | Público; los Excel están en la nube Nextcloud del INE (`https://nube.ine.gob.bo/index.php/s/<token>/download`) | `.xlsx` |
| `MEFP` | Ministerio de Economía y Finanzas Públicas — `https://www.economiayfinanzas.gob.bo/index.php/ejecucion-sector-publico-no-financiero` | Operaciones consolidadas del SPNF (resultado global) | Público | `.xlsx`, uno por gestión |

Ninguna serie requiere clave ni registro. ASFI no fue necesaria: el BCB publica los agregados del
sistema financiero (crédito, tasas) con datos de la ASFI.

## Régimen cambiario (2025-2026)

Desde 2011 el tipo de cambio oficial fue fijo: **6,86 compra / 6,96 venta** Bs por USD. Según las
notas del propio BCB en el Excel de tipo de cambio oficial:
- El tipo de cambio de venta rigió **hasta el 26/06/2026** (el 27 y 28 de junio, fin de semana, se
  repite).
- **Desde el 29/06/2026** el TCO se fija según la **RD 88/2026**, y desde el **24/09/2026** según la
  **RD 142/2026**. El BCB publica un único TCO (columna "Compra"): 9,73 el 27/06/2026, máximo 12,64
  (09/09/2026), 12,02 al 30/09/2026; 11,73 en la portada del BCB el 21/10/2026.
- El BCB publicó además un "valor referencial de compra/venta del dólar" (serie 1/12/2025 – 26/6/2026)
  en una página aparte; no se incluyó (es un valor referencial del mercado, no el TCO).
- No se usaron cotizaciones paralelas de terceros.

`tc_usd_diario` y `tc_usd_promedio` usan la columna "Compra", que es la única continua antes y
después del cambio de régimen; la venta va como serie adicional (`tc_usd_venta_promedio` y
`tc_usd_venta_diario`, hasta el 26/06/2026). El tipo medio oficial hasta esa fecha es
(compra + venta) / 2: 6,91 desde 2011. Desde el 27/06/2026 solo hay un TCO, sin venta.

## Tasas monetarias (no hay tasa de política convencional)

Bolivia no tiene una tasa de política monetaria con esquema de metas. Tasas monetarias oficiales
que publica el BCB:
- **Tasa premio de reporto** (MN), a la que el BCB da liquidez de corto plazo: `tasa_reporto_mn`
  (cierres de mes desde 2002-12, de las estadísticas semanales). 13,25 % a fin de sep-2026; la portada
  del BCB muestra 13,50 % (tasa premio base de reporto 7 días) al 21/10/2026.
- **Tasas de adjudicación de títulos de regulación monetaria** (LT/BT del BCB por plazo, subasta y
  mesa de dinero, archivo `Documentos Adjuntos/Titulos publicos.xlsx`). No se incorporó: la tabla tiene
  decenas de instrumentos/plazos con huecos y cambia de columnas; queda como pendiente.
- Tasa del crédito con garantía del Fondo RAL y **Tasa de Referencia (TRe)** (promedio ponderado de
  DPF del sistema, para créditos a tasa variable): disponibles, no incorporadas.

Por eso `tasa_politica` **no aplica** para Bolivia.

## Trampas encontradas

- **TLS del MEFP.** `www.economiayfinanzas.gob.bo` no envía el certificado intermedio
  (*Sectigo Public Server Authentication CA DV R36*): `requests` falla con
  `CERTIFICATE_VERIFY_FAILED`. El módulo arma un bundle = `certifi` + ese intermedio, descargado de
  la URL AIA del propio certificado (`http://crt.sectigo.com/SectigoPublicServerAuthenticationCADVR36.crt`),
  y lo pasa a `comun.Client(verify=bundle)` solo para ese host. Si el bundle no se pudiera armar,
  usa `verify=False` (último recurso) y lo deja en el log.
- **Páginas UTF-8 sin charset** (sitio `referencia2017` del INE): `requests` las decodifica como
  latin-1 y los títulos quedan como `VARIACIÃ\x93N`. Se decodifican a mano como UTF-8 y los enlaces
  se buscan por título normalizado (sin tildes).
- **Enlaces del INE en Nextcloud** (`nube.ine.gob.bo/index.php/s/<token>/download`): el token cambia
  al republicar. Se buscan por el título del cuadro en la página, no por URL fija.
- **Cambio de base del PIB.** El INE publicó cuentas nacionales con **año de referencia 2017**
  (medidas de volumen encadenadas, MCNT 2017): trimestrales 2017-T1 a 2025-T4 y anuales 2017-2024.
  La serie anterior (base 1990, 1980/1990-2024) sigue en el sitio pero no se empalma: las series
  comunes usan solo la base 2017.
- **IGAE base 1990 sin actualizar:** el INE lo publica de 2008-01 a 2024-12 y no lo ha migrado a la
  base 2017. El cuadro "variación a 12 meses" del IGAE es la variación del **promedio móvil de 12
  meses**; para `actividad_mensual_var12m` se usa "variación a similar periodo" (mismo mes del año
  anterior), verificada contra el índice (diferencia máx. 0,005).
- **IGAE:** la fila de años trae `0` en las celdas combinadas (no son datos) y `2024(p)`.
- **Tasas del sistema financiero:** un archivo por año (2001-2026), con hojas que cambian de nombre
  (`HOJA 1 SIS FIN M 2005 MN`, `MASFMN`, `PSFMN`, `MN`). Solo desde 2011 la fila de cada mes trae el
  **total del sistema**; antes, solo los totales por tipo de entidad. No se calcula ningún promedio:
  la serie empieza en 2011-01 y faltan los meses sin total (activa: 2015-01, 2017-04 a 2017-07,
  2019-07; pasiva: 2017-04 a 2017-08, 2019-07).
- **Estadísticas semanales:** el nombre del archivo cambia cada semana (`Semanal 42_2026.xlsx`). Las
  columnas son cierres de mes desde 1987 y luego `Semana n` y días del mes en curso (estos se ignoran).
- **SPNF (MEFP):** un archivo por gestión, con hojas `SPNF`, `SPNF_BCB` o `SPNF_Web`. El de 2026 es
  parcial (a julio) y se omite (solo gestiones cuyo título dice "DICIEMBRE").
- **Salario mínimo:** el cuadro del INE trae dos filas "2025": la segunda (DS 5503, dic-2025) es la
  gestión 2026 (nota 3). Desde 2007 rige desde el 1 de enero; antes, desde la promulgación.
- **Unidades:** M2, M'3 y el balance del sistema financiero vienen en **miles** de Bs (se dividen por 1000).
- **Capa comparable (2026-10-21).** Las tres series nuevas salen de archivos que ya se descargaban:
  - `m3_amplio`: columna `M'3` de `7. Agregados Monetarios.xlsx` (con apóstrofo; `M3` sin apóstrofo
    es solo MN + UFV). Sistema bancario hasta jun-1996 y sistema financiero desde jul-1996, igual que M2.
  - `reservas_brutas`: bloque "RESERVAS BRUTAS > TOTAL" de la hoja mensual de RIN. Identidad
    verificada: brutas − convenio de crédito recíproco y otros − pasivos por oro = RIN (diferencia 0 en
    297 meses). Entre 2007-06 y 2016-02 hay 64 meses con RIN > brutas (hasta 4,4 MUSD) porque el
    "convenio y otros" fue negativo (posición acreedora); no es un error. En 2002 el total de brutas
    supera la suma de oro, divisas, DEG y tramo FMI en hasta 10 MUSD (componente no desglosado).
  - `tc_usd_venta_diario`: columna `Venta(1)` de la hoja diaria; termina el 26/06/2026. Incluye
    fines de semana, como la compra. Diferencial venta − compra: 0,10 desde 2011; 0,01-0,02 en los
    años del crawling peg.

## Cobertura obtenida (descarga del 2026-10-21)

| nombre_corto | indicador_comun | fuente | frecuencia | desde | hasta | n |
|---|---|---|---|---|---|---|
| pbi_real_trim | pbi_real_trim | INE | trimestral | 2017-01 | 2025-10 | 36 |
| pbi_real_var12m_trim | pbi_real_var12m_trim | INE | trimestral | 2018-01 | 2025-10 | 32 |
| actividad_mensual_indice | actividad_mensual_indice | INE | mensual | 2008-01 | 2024-12 | 204 |
| actividad_mensual_var12m | actividad_mensual_var12m | INE | mensual | 2008-01 | 2024-12 | 204 |
| pbi_nominal_anual | pbi_nominal_anual | INE | anual | 2017 | 2024 | 8 |
| ipc_indice | ipc_indice | INE | mensual | 1937-01 | 2026-09 | 1077 |
| inflacion_mensual | inflacion_mensual | INE | mensual | 1937-02 | 2026-09 | 1076 |
| inflacion_12m | inflacion_12m | INE | mensual | 1938-01 | 2026-09 | 1065 |
| inflacion_subyacente_12m | inflacion_subyacente_12m | BCB | mensual | 1994-01 | 2026-08 | 392 |
| tasa_activa_promedio | tasa_activa_promedio | BCB | mensual | 2011-01 | 2026-09 | 183 |
| tasa_pasiva_promedio | tasa_pasiva_promedio | BCB | mensual | 2011-01 | 2026-09 | 183 |
| credito_privado | credito_privado | BCB | mensual | 1996-01 | 2026-08 | 368 |
| m2 | m2 | BCB | mensual | 1987-12 | 2026-08 | 454 |
| tc_usd_promedio | tc_usd_promedio | BCB | mensual | 1990-01 | 2026-09 | 441 |
| tc_usd_diario | tc_usd_diario | BCB | diaria | 1990-01-01 | 2026-09-30 | 13422 |
| reservas_internacionales | reservas_internacionales | BCB | mensual | 2002-01 | 2026-09 | 297 |
| exportaciones | exportaciones | BCB | mensual | 2012-01 | 2026-08 | 176 |
| importaciones | importaciones | BCB | mensual | 2012-01 | 2026-08 | 176 |
| balanza_comercial | balanza_comercial | BCB | mensual | 2012-01 | 2026-08 | 176 |
| cuenta_corriente | cuenta_corriente | BCB | trimestral | 2014-01 | 2026-04 | 50 |
| resultado_fiscal_pct_pbi | resultado_fiscal_pct_pbi | MEFP | anual | 2017 | 2024 | 8 |
| desempleo | desempleo | INE | mensual | 2015-10 | 2026-08 | 131 |
| salario_minimo | salario_minimo | INE | mensual | 1991-03 | 2026-10 | 428 |
| inflacion_nucleo_12m | — | BCB | mensual | 1994-01 | 2026-08 | 392 |
| tasa_reporto_mn | — | BCB | mensual | 2002-12 | 2026-09 | 276 |
| bolivianizacion_credito | — | BCB | mensual | 1998-03 | 2026-09 | 329 |
| tc_usd_venta_promedio | — | BCB | mensual | 1990-01 | 2026-06 | 438 |
| tc_usd_venta_diario | — | BCB | diaria | 1990-01-01 | 2026-06-26 | 13326 |
| m3_amplio | — | BCB | mensual | 1987-12 | 2026-08 | 454 |
| reservas_brutas | — | BCB | mensual | 2002-01 | 2026-09 | 297 |
| remesas_recibidas | — | BCB | mensual | 2006-01 | 2026-08 | 242 |
| exportaciones_gas_natural | — | BCB | mensual | 2012-01 | 2026-08 | 176 |
| cuenta_corriente_mbp5 | — | BCB | trimestral | 2001-01 | 2013-10 | 52 |
| resultado_global_spnf | — | MEFP | anual | 2017 | 2025 | 9 |

Notas de cobertura y unidades:
- IPC nacional base 2016 = 100, serie empalmada por el INE (sin saltos de base dentro del archivo;
  los mayores saltos mensuales son de la hiperinflación de 1985).
- `desempleo`: **área urbana** (la cifra oficial de referencia del INE, Encuesta Continua de Empleo).
- `reservas_internacionales`: RIN netas de obligaciones (incluye pasivos relacionados con oro, MBP6).
- `credito_privado`: financiamiento al sector privado del sistema financiero (bancos y no bancarias).
- `m2`: solo MN + UFV (M'2 incluye ME y MVDOL).
- `m3_amplio`: M'3 = liquidez total en MN, ME, MVDOL y UFV (efectivo + depósitos vista, ahorro,
  plazo y otros). M'3/M2 = 1,68 en ago-2026.
- `reservas_brutas`: activos de reserva brutos del BCB (oro + divisas + DEG + tramo FMI), sin
  deducir obligaciones.
- `resultado_fiscal_pct_pbi` está **calculado**: superávit/déficit global del SPNF (MEFP, Bs) / PIB
  nominal del INE (referencia 2017). Con la nueva base el PIB es mayor que el de base 1990, así que
  las ratios son menores que las publicadas antes con el PIB viejo.
- `importaciones`: FOB (ajustadas).

## Indicadores comunes no cubiertos

| indicador_comun | Motivo |
|---|---|
| `tasa_politica` | No aplica: Bolivia no tiene tasa de política convencional (ver "Tasas monetarias"); se incluye la tasa de reporto como serie adicional. |
| `tasa_interbancaria` | El BCB publica tasas interbancarias **semanales** (periodos "05 al 11 de enero") en un archivo por año con nombres irregulares (`Operac Interb …`, `53_25.xlsx`); no publica el promedio mensual y no se calcula. Pendiente. |
| `pbi_desest_trim` | El INE no publica en Excel el PIB trimestral desestacionalizado de la base 2017. |
| `expectativa_inflacion_12m` | No existe una encuesta oficial de expectativas publicada como serie. |
| `deuda_publica_pct_pbi` | El MEFP publica deuda del TGN (externa/interna) y "indicadores de endeudamiento referenciales" sin cuadro descargable de deuda total/PIB; el BCB publica la deuda externa pública en PDF. No hay serie oficial en Excel de deuda pública bruta total en % del PIB. |

## Validación (2026-10-21)

| Dato | Publicación oficial | Serie | Resultado |
|---|---|---|---|
| IPC sep-2026 | Portada BCB (indicadores de inflación, sep-2026): IPC 152,85; mensual 0,85 %; 12 meses 5,70 % | `ipc_indice` 152,85; `inflacion_mensual` 0,845; `inflacion_12m` 5,699 | ✔ |
| TCO 30/09/2026 | Estadísticas semanales del BCB (fila "Tipo de Cambio Oficial (Bs/USD)", cierre de sep-2026): 12,02 | `tc_usd_diario` 2026-09-30 = 12,02 | ✔ |
| RIN sep-2026 | Estadísticas semanales del BCB ("RIN incluyendo obligaciones relativas al oro", sep-2026): 3.781,3 | `reservas_internacionales` 2026-09 = 3.781,3 | ✔ |
| Tasa de reporto | Estadísticas semanales: 13,25 % fin de sep-2026 y 13,50 % al 09/10/2026; portada BCB: 13,50 % al 21/10/2026 | `tasa_reporto_mn` 2026-09 = 13,25 | ✔ |
| Salario mínimo 2026 | INE: DS 5503, Bs 3.300 vigente para la gestión 2026 | `salario_minimo` 2026-01 a 2026-10 = 3.300 | ✔ |
| M'3 ago-2026 | Estadísticas semanales del BCB (fila "M'3", cierre de ago-2026): 356.915,7 millones de Bs | `m3_amplio` 2026-08 = 356.915,7 | ✔ |
| Reservas brutas sep-2026 | Estadísticas semanales del BCB ("Reservas Internacionales Brutas (I + II + III + IV)", sep-2026): 3.932,8 | `reservas_brutas` 2026-09 = 3.932,8 | ✔ |
| TC venta 26/06/2026 | Nota del Excel de TCO: venta 6,96 vigente hasta el 26/06/2026 | `tc_usd_venta_diario` 2026-06-26 = 6,96 (último dato) | ✔ |

Controles internos:
- Inflación 12m y mensual calculadas desde el índice = publicadas por el INE (diferencia máx. 0,000).
- `pbi_real_var12m_trim` = variación calculada desde `pbi_real_trim` (diferencia 0).
- `actividad_mensual_var12m` = variación calculada desde el IGAE (diferencia máx. 0,005).
- `m3_amplio` ≥ `m2` en los 454 meses (cociente mínimo 1,61).
- Promedio mensual de `tc_usd_venta_diario` = `tc_usd_venta_promedio` publicado: diferencia 0 desde
  2012; hasta 0,29 % en 1990-2011 (crawling peg).

## Pendientes

- IGAE: el INE no lo publica desde 2024-12 (base 1990); revisar si sale un indicador mensual con la
  base 2017.
- Tasa interbancaria: decidir si se agrega como serie semanal (no hay frecuencia semanal en el esquema
  común) o si el BCB publica un promedio mensual en otro cuadro.
- Títulos de regulación monetaria del BCB (tasas de adjudicación por plazo) como serie adicional.
- Deuda pública: buscar un cuadro oficial de deuda total/PIB (memoria del MEFP o del BCB).
- Serie del PIB base 1990 (1980-2024) como serie adicional de largo plazo, si se necesita historia.

## Cómo actualizar

```
python src/paises/bol.py                    # descarga (≈ 3-4 min: ~75 archivos) y procesa todo
python src/paises/bol.py --solo-procesar    # reprocesa data/raw/BOL sin red
python src/paises/bol.py --serie tc_usd_diario ipc_indice   # descarga solo esos archivos
```
