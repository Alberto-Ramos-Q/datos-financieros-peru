# Perú — fuentes

## Institución y acceso
| Fuente | Institución | Acceso | Formato |
|---|---|---|---|
| `bcrp` | Banco Central de Reserva del Perú — BCRPData | API pública sin clave: `https://estadisticas.bcrp.gob.pe/estadisticas/series/api/CODIGO/json/INICIO/FIN/esp` | JSON (UTF-8) |
| `inei` | Instituto Nacional de Estadística e Informática — IPC a nivel nacional | Excel enlazado en `https://www.inei.gob.pe/estadisticas/indice-tematico/price-indexes/` (`n02_indice-precios_al_consumidor-nivel_nacional_<mes><aa>.xlsx`); `per.py` busca el enlace vigente y lo guarda como `data/raw/PER/inei/n02_ipc_nacional.xlsx` | Excel |

El BCRP republica las series del INEI (PBI, IPC, empleo) y del MEF (fiscal) en BCRPData, con el
mismo código para toda la historia. Catálogo completo (~17 mil series) en el proyecto hermano
`../descargas-bcrp/docs/catalogo_bcrp.csv`, que además mantiene 118 series.

## Trampas
- Sin fechas, la API devuelve solo los últimos 5 años: se pide desde 1900 (1990 en diarias).
- Rellena con `n.d.` hasta la fecha pedida: se pide hasta hoy.
- Diarias (`02.Ene.97`) y trimestrales (`T1.80`) usan años de 2 dígitos.
- Setiembre puede venir como `Set.` o `Sep.`.
- Error en la base del BCRP: `PD12301MD` el 14.Set.17 trae `'3.7512301,2011-04-07,3.75'`; queda como faltante.
- **El IPC nacional no está en BCRPData** (solo el de Lima Metropolitana y el IPC anual
  histórico). Se toma del Excel del INEI. El nombre del archivo cambia cada mes (`..._set26.xlsx`).
  En la hoja `Base Dic.2021`, el año solo aparece en enero (se rellena hacia abajo), los meses
  se escriben «Setiembre» y la variación anual de 2012 viene como `-`. La hoja `Base Dic.2011`
  (2012-2021) es la base anterior y no se usa.
- `credito_privado` (PN00535MM) **no** es MN + ME a tipo de cambio corriente: es MN + ME × 3,36
  (TC constante del BCRP). Se verificó que la identidad es exacta desde 2003 (2001-2002 usan 3,31).
  Para el crédito a TC corriente, usar `credito_privado_mn + credito_privado_me_usd × TC fin de mes`.

## Coberturas y notas de comparabilidad
- `ipc_indice`, inflación: **IPC de Lima Metropolitana** (referencia de la meta de inflación), no nacional.
- `ipc_nacional_indice`, `inflacion_nacional_12m`: **IPC a nivel nacional del INEI** (base dic-2021,
  encadenado desde 2012-01; la 12m es la publicada por el INEI, desde 2013-01). Cubre Lima
  Metropolitana y las ciudades principales (área urbana). Sirve para comparar con IPC nacionales.
- `credito_privado_mn` (PN00496MM, millones S/) y `credito_privado_me_usd` (PN00499MM, millones
  US$): crédito al sector privado de las sociedades creadoras de depósito por moneda, saldo fin
  de mes, desde 1992-01 (el total `credito_privado` empieza en 2001).
- `inflacion_subyacente_12m`: IPC sin alimentos y energía (indicador de tendencia del BCRP).
- `m2`: liquidez total de las sociedades creadoras de depósito (agregado amplio).
- `desempleo`: Lima Metropolitana, promedio móvil de 3 meses (no hay tasa nacional mensual).
- `deuda_publica_pct_pbi`: trimestral (no hay serie anual equivalente en BCRPData).
- `balanza_comercial`: desde 2012 (exportaciones e importaciones, desde 1996).
- No cubierto: `pbi_desest_trim` (BCRPData no publica el nivel trimestral desestacionalizado;
  sí la variación, en `pbi_desest_var_trim`).

## Validación de las series agregadas (descarga del 2026-10-21)
| Serie | Control | Resultado |
|---|---|---|
| `inflacion_nacional_12m` | 12m calculada desde `ipc_nacional_indice` | diferencia máx. 0,01 pp (redondeo); sep-2026 = 4,17 % en ambas |
| `inflacion_nacional_12m` | frente a la de Lima (`inflacion_12m`), 2013-2026 | diferencia media +0,07 pp, máx. 0,69 pp, correlación 0,994; sep-2026: 4,17 % nacional y 4,55 % Lima |
| `credito_privado_mn`, `credito_privado_me_usd` | MN + ME × 3,36 frente a `credito_privado` | idénticos desde 2003 |
| `credito_privado_mn`, `credito_privado_me_usd` | ME × TC fin de mes / (MN + ME × TC) frente a `dolarizacion_credito` (PN00511MM) | ≤0,06 pp de diferencia (ago-2026: 22,52 % frente a 22,50 %) |

## Cobertura (2026-10-21)
38 series, 27 de 28 indicadores comunes. Ver `data/processed/macro_series.csv`.
Más largas: inflación mensual desde 1949-02, resultado fiscal desde 1970, PBI trimestral desde 1979.

Series agregadas para la capa comparable (sin indicador común):

| nombre_corto | fuente | código | frecuencia | desde | hasta | n |
|---|---|---|---|---|---|---|
| ipc_nacional_indice | inei | `n02_ipc_nacional.xlsx\|Base Dic.2021\|Índice` | mensual | 2012-01 | 2026-09 | 177 |
| inflacion_nacional_12m | inei | `n02_ipc_nacional.xlsx\|Base Dic.2021\|Anual` | mensual | 2013-01 | 2026-09 | 165 |
| credito_privado_mn | bcrp | PN00496MM | mensual | 1992-01 | 2026-08 | 416 |
| credito_privado_me_usd | bcrp | PN00499MM | mensual | 1992-01 | 2026-08 | 416 |

## Actualizar
`python src/paises/per.py`
