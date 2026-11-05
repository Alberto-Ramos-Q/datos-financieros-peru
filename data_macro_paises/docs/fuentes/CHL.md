# Chile (CHL): fuentes de datos

Script: `src/paises/chl.py` · Configuración: `config/series/CHL.csv` (39 series: 27 comunes y 12 extra)
Crudos: `data/raw/CHL/bcch_bde/` · Salida: `data/interim/CHL_observaciones.parquet`

## Instituciones y acceso

| Fuente (`fuente`) | Institución | URL | Acceso | Formato |
|---|---|---|---|---|
| `bcch_bde` | Banco Central de Chile: Base de Datos Estadísticos (BDE) | https://si3.bcentral.cl/siete | Archivo, sin clave (exportación a Excel de cada cuadro) | .xlsx con hojas `Cuadro`, `Metadatos` y `Series` |

La BDE también publica las series que originan otros organismos, y aquí se usan desde ella:
- **INE**: IPC, IPC sin volátiles (empalmado por el BCCh), IPC sin alimentos y energía (IPC SAE, índice analítico empalmado a base 2023) y la tasa de desocupación (ENE).
- **DIPRES / Ministerio de Hacienda**: balance del Gobierno Central y deuda pública como % del PIB.

En las `notas` de cada serie se indica el organismo originador.

**Cómo se descarga sin clave.** La API SieteRestWS (`si3.bcentral.cl/SieteRestWS`) exige usuario y clave, pero la exportación web es pública:
1. `GET /Siete/ES/Siete/Cuadro/<CAP>/<MN>/<CUADRO>/<ID>?cbFrecuencia=..&cbCalculo=..`. Devuelve la cookie de sesión, el token CSRF (`__RequestVerificationToken` del formulario `frmExportExcel`) y las series del cuadro (atributos `data-*` de cada checkbox).
2. `POST /Siete/ES/Siete/DownloadExcel` con `IsFullSeries=true`, `Series` (JSON con las series elegidas), `frecuencia`, `calculo`, `fechaInicio` y `fechaTermino`.

El cuadro de cada serie está en el diccionario `SOURCES` de `chl.py`, porque la exportación solo funciona dentro del cuadro al que pertenece la serie. Para agregar una serie:
1. Busca el código en la BDE.
2. Identifica un cuadro que la contenga.
3. Agrégala a `SOURCES` y a `CHL.csv`.

No hace falta ninguna clave. **No hay series con `activo=0`.**

## Trampas encontradas

- **El rango de años por defecto de cada cuadro.** Aunque se pida `IsFullSeries=true`, la exportación respeta el rango de años del cuadro, que por defecto empieza en 2010 o 2013. El script lee del `<select id="cbFechaInicio">` el primer y el último año disponibles y los envía. Sin esto, el IMACEC empezaba en 2013 en vez de 1996, y el IPC en 2010 en vez de 1928.
- **El .xlsx cambia de bytes en cada exportación** (marca de tiempo interna). Antes de llamar a `save_raw` se compara el contenido de las hojas. Si es idéntico, se registra `sin_cambios` y no se versiona.
- **Frecuencias agregadas por la BDE.** Al exportar una serie diaria en frecuencia mensual, la BDE agrega según su atributo `observed` (`AVERAGED` = promedio). Para la TPM se quiere el **fin de periodo**, así que se descarga diaria y el script toma el último dato del mes. El tipo de cambio promedio también se calcula desde la serie diaria. Se excluye el mes en curso, que está incompleto.
- **Variaciones calculadas por la BDE.** `pbi_real_var12m_trim` y `actividad_mensual_var12m` se piden con `cbCalculo=YTYPCT` (sufijo `@YTYPCT` en `codigo_fuente`). Se verificó que coinciden exactamente con la variación calculada desde los niveles.
- **Unidades.** La BDE publica el PIB, M2 y las colocaciones en **miles de millones de pesos**. Se multiplican por 1000 para llevarlos a millones (diccionario `FACTOR`; no se aplica a las variaciones).
- **TPM antes de agosto de 2001.** La TPM se fijaba como tasa **real** (sobre UF). En agosto de 2001 pasa de 3,5 a 6,5 por la nominalización, no por un cambio de política.
- **IPC: cambios de base.** `ipc_indice` es el índice INE empalmado a base 2023=100, desde diciembre de 2009. `inflacion_mensual` es la serie histórica del BCCh desde 1928. `inflacion_12m` usa la serie empalmada base 2023 (desde 2011), y no la "histórica" `F074.IPC.IND.Z.EP09.C.M`. Esta última trae ceros de relleno en 1928 y difiere hasta 0,7 pp de la vigente en el tramo común, porque mantiene las cifras con bases anteriores.
- **Desempleo.** La serie es del INE con proyecciones de población del Censo 2017 y empieza en 2010. Cada dato es un trimestre móvil y se fecha en su último mes.
- **Códigos engañosos.** La tasa de colocación de 90 días a 1 año en pesos tiene el código `F022.CAP.TIN.Z.NO.Z.M`: dice `CAP`, como las captaciones, aunque está en el cuadro de colocaciones TSF_31. Se verificó que es mayor que la tasa de captación (15,3% frente a 4,1% en septiembre de 2026).
- **La UF incluye valores a futuro**, ya fijados hasta el día 9 del mes siguiente.
- **IPC SAE: no hay 12m publicada en base 2023.** El índice SAE empalmado a base 2023
  (`F074.IPCSAE.IND.Z.EP23.Z.M`, cuadro `IPC_ANA_INE_2023`, desde dic-2009) solo se exporta con
  cálculo `NONE` (el cuadro no ofrece YTYPCT), y la variación mensual está en otro cuadro
  (`IPC_VARM_ANA_INE_2023`). La 12m publicada `F074.IPCSAE.VIN.Z.EP09.C.M` (cuadro
  `IPC_VAR_ANUAL_HIST_NEW`) se cortó en dic-2023 y conserva cifras de bases anteriores sin
  re-empalmar. Por eso `inflacion_sae_12m` se **calcula** en `chl.py` desde el índice (sufijo
  `|var12m` en `codigo_fuente`). Frente a la histórica publicada, la diferencia media es de 0,04-0,2 pp
  por año, salvo 2014 (0,45 pp; máx. 0,68) y 2019 (0,53 pp; máx. 0,74), los años que siguen a los
  cambios de base 2013 y 2018.
- **Consola de Windows.** `comun.py` loguea el carácter "→", y la consola cp1252 lo rechaza. El script reconfigura `sys.stdout` a UTF-8 antes de `setup_logging`.

## Validación (descarga del 2026-10-21)

| Dato | Parquet | Publicación oficial | OK |
|---|---|---|---|
| Dólar observado del 21-10-2026 | 978,56 | 978,56 (BCCh, Indicadores diarios) | sí |
| UF del 21-10-2026 | 41.194,55 | 41.194,55 (BCCh, Indicadores diarios) | sí |
| TPM vigente (septiembre de 2026, fin de mes) | 4,50% | 4,50% (BCCh, Indicadores diarios, serie TPM) | sí |
| IPC septiembre de 2026, var. mensual | 0,4% | 0,4% (BCCh, Indicadores diarios, serie IPC) | sí |

Controles de consistencia:
- **Inflación 12m calculada desde `ipc_indice`** frente a la publicada `inflacion_12m`: diferencia máxima de 0,1 pp en 189 meses (por redondeo del índice a 2 decimales); septiembre de 2026 = 4,1% en ambas.
- **Variación mensual calculada desde el índice** frente a `inflacion_mensual`: diferencia máxima de 0,1 pp.
- **IMACEC y PIB a/a de la BDE** frente a los calculados desde los niveles: diferencia menor que 1e-12.
- **IPC SAE (`inflacion_sae_12m`)**: el boletín del INE de septiembre de 2026 informa una variación mensual del "IPC menos alimentos y energía" de 0,1 %; el índice de la BDE da 110,62 → 110,74 (+0,11 %). La 12m de sep-2026 es 3,16 % (IPCSV 3,19 %, IPC general 4,1 %). Correlación de 0,964 con `inflacion_subyacente_12m` en 2010-2026.

## Cobertura obtenida

| nombre_corto | código fuente | frec. | desde | hasta | n |
|---|---|---|---|---|---|
| actividad_mensual_indice | `F032.IMC.IND.Z.Z.EP18.Z.Z.0.M` | mensual | 1996-01 | 2026-08 | 368 |
| actividad_mensual_var12m | `F032.IMC.IND.Z.Z.EP18.Z.Z.0.M@YTYPCT` | mensual | 1997-01 | 2026-08 | 356 |
| balanza_comercial | `F068.B1.VAR.T0.0.S.N.Z.Z.Z.Z.6.0.M` | mensual | 2003-01 | 2026-09 | 285 |
| credito_privado | `F022.CPP.STO.Z.Z.Z.M` | mensual | 2004-01 | 2026-07 | 271 |
| cuenta_corriente | `F068.A.FLU.Z.0.S.N.Z.Z.Z.Z.6.0.T` | trimestral | 2003-01 | 2026-04 | 94 |
| desempleo | `F049.DES.TAS.INE9.10.M` | mensual | 2010-03 | 2026-08 | 198 |
| deuda_publica_pct_pbi | `F051.D7.PPB.C.Z.Z.T` | anual | 2006 | 2025 | 20 |
| expectativa_inflacion_12m | `F089.IPC.V12.14.M` | mensual | 2001-01 | 2026-10 | 303 |
| exportaciones | `F068.B1.FLU.Z.0.C.N.Z.Z.Z.Z.6.0.M` | mensual | 2003-01 | 2026-09 | 285 |
| importaciones | `F068.B1.FLU.Z.0.D.N.0.T.Z.Z.6.0.M` | mensual | 2003-01 | 2026-09 | 285 |
| inflacion_12m | `F074.IPC.V12.Z.EP23.C.M` | mensual | 2011-01 | 2026-09 | 189 |
| inflacion_mensual | `F074.IPC.VAR.Z.Z.C.M` | mensual | 1928-03 | 2026-09 | 1183 |
| inflacion_subyacente_12m | `G073.IPCSV.V12.2023.M` | mensual | 1999-12 | 2026-09 | 322 |
| ipc_indice | `F074.IPC.IND.Z.EP23.C.M` | mensual | 2009-12 | 2026-09 | 202 |
| m2 | `F021.M2.STO.N.CLP.5.M` | mensual | 1986-01 | 2026-09 | 489 |
| pbi_desest_trim | `F032.PIB.FLU.R.CLP.EP18.Z.Z.1.T` | trimestral | 1996-01 | 2026-04 | 122 |
| pbi_nominal_anual | `F032.PIB.FLU.N.CLP.HIST18.Z.Z.0.A` | anual | 1960 | 2025 | 66 |
| pbi_real_trim | `F032.PIB.FLU.R.CLP.EP18.Z.Z.0.T` | trimestral | 1996-01 | 2026-04 | 122 |
| pbi_real_var12m_trim | `F032.PIB.FLU.R.CLP.EP18.Z.Z.0.T@YTYPCT` | trimestral | 1997-01 | 2026-04 | 118 |
| reservas_internacionales | `F062.A5.STO.PF.USD.M` | mensual | 1982-01 | 2026-09 | 537 |
| resultado_fiscal_pct_pbi | `F051.G21.PPI.C.Z.Z.A` | anual | 1990 | 2025 | 36 |
| tasa_activa_promedio | `F022.CAP.TIN.Z.NO.Z.M` | mensual | 1990-01 | 2026-09 | 441 |
| tasa_interbancaria | `F022.TIB.TIP.D001.NO.Z.M` | mensual | 1996-01 | 2026-09 | 369 |
| tasa_pasiva_promedio | `F022.CAP.TIN.D089.NO.Z.M` | mensual | 1982-01 | 2026-09 | 537 |
| tasa_politica | `F022.TPM.TIN.D001.NO.Z.D` | mensual | 1997-02 | 2026-09 | 356 |
| tc_usd_diario | `F073.TCO.PRE.Z.D` | diaria | 1982-08-09 | 2026-10-21 | 11023 |
| tc_usd_promedio | `F073.TCO.PRE.Z.D` | mensual | 1982-08 | 2026-09 | 530 |
| *balance_estructural_pct_pbi* (extra) | `F051.G11.PPB.C.Z.CLP.A` | anual | 2001 | 2025 | 25 |
| *colocaciones_consumo* (extra) | `F022.CONBI.STO.Z.Z.CLP.M` | mensual | 1983-01 | 2026-09 | 525 |
| *deuda_neta_gc_pct_pbi* (extra) | `F051.D9.PPB.C.Z.Z.T` | anual | 2006 | 2025 | 20 |
| *expectativa_tpm_11m* (extra) | `F089.TPM.TAS.14.M` | mensual | 2002-01 | 2026-10 | 298 |
| *imacec_desest* (extra) | `F032.IMC.IND.Z.Z.EP18.Z.Z.1.M` | mensual | 1996-01 | 2026-08 | 368 |
| *imacec_no_minero* (extra) | `F032.IMC.IND.Z.Z.EP18.N03.Z.0.M` | mensual | 1996-01 | 2026-08 | 368 |
| *inflacion_sae_12m* (extra, calculada) | `F074.IPCSAE.IND.Z.EP23.Z.M\|var12m` | mensual | 2010-12 | 2026-09 | 190 |
| *ipc_sin_volatiles_indice* (extra) | `G073.IPCSV.IND.2023.M` | mensual | 1998-12 | 2026-09 | 334 |
| *precio_cobre* (extra) | `F019.PPB.PRE.40.M` | mensual | 1960-01 | 2026-09 | 801 |
| *tasa_bono_10a_pesos* (extra) | `F022.BCLP.TIS.AN10.NO.Z.M` | mensual | 2004-07 | 2026-09 | 267 |
| *tipo_cambio_real* (extra) | `F073.TCR.IND.199101.M` | mensual | 1986-01 | 2026-08 | 488 |
| *uf* (extra) | `F073.UFF.PRE.Z.D` | diaria | 1977-08-01 | 2026-11-09 | 17998 |

## Indicadores comunes no cubiertos

| Indicador | Motivo |
|---|---|
| `salario_minimo` | El Ingreso Mínimo Mensual no está en la BDE. La Dirección del Trabajo (dt.gob.cl) solo publica el valor vigente en una página de consulta (553.553 pesos desde el 01-05-2026, Ley 21.830), y los montos históricos están dispersos en leyes y circulares de SUSESO, en PDF. No existe una serie oficial descargable. |

## Pendientes

- Salario mínimo: evaluar un scraper de las leyes de reajuste en el Diario Oficial, o mantener una tabla documentada a mano (requiere una decisión, porque no sería una descarga reproducible).
- Desempleo antes de 2010: el BCCh tiene cuadros con las proyecciones de los censos 2002 y 2017 (`ED_TDNRM_HIST*`), con otra metodología. Evaluar si conviene agregarlos como serie extra.
- La exportación web no es una API documentada: si el BCCh cambia el formulario `frmExportExcel` o los atributos `data-*`, el script falla con un mensaje explícito. La alternativa estable sería la API SieteRestWS con `BCCH_USER`/`BCCH_PASS` (registro gratuito en si3.bcentral.cl), que no se implementó para no registrar cuentas.
