# Capa comparable: guía de uso

`src/armonizar.py` convierte las series oficiales (`data/processed/macro_observaciones.parquet`)
en **indicadores con la misma definición, unidad y base en los 13 países**. Aplica las
transformaciones recomendadas en la revisión de comparabilidad
([`docs/comparabilidad/README.md`](comparabilidad/README.md)). Las series originales no se tocan:
la capa comparable es una vista derivada que se regenera desde código.

```
python src/armonizar.py          # solo la capa comparable (~1 min, sin red)
python src/actualizar_todo.py    # descarga + consolida + capa comparable
```

**Estado (2026-10-21):** 61 indicadores × 13 países = 692 pares con dato, 183 mil observaciones.
- Uso: 364 `comparable`, 196 `comparable_con_ajuste`, 127 `solo_tendencias` y 5 `no_comparable`
  (actividad mensual de ESP y USA, comercio aduanero de PAN).
- Validación: 144 pruebas, todas ok (`comparable_validacion.csv`).

**Series oficiales nuevas** descargadas para esta capa (en `config/series/<ISO3>.csv`, sin indicador común):
- `m3_amplio` (ARG, BOL, PRY, URY);
- `reservas_brutas` (BOL, COL, MEX);
- `credito_privado_mn` y `credito_privado_me_usd` (ARG, COL, PER, URY);
- `exportaciones_bienes_bp` e `importaciones_bienes_bp` (ARG, ESP, PAN, URY);
- `ipc_nacional_indice` e `inflacion_nacional_12m` (PER);
- `inflacion_sae_12m` (BRA, CHL, COL, ESP, PRY);
- `rfsp_pct_pbi` y `shrfsp_pct_pbi` (MEX);
- `deuda_publico_pct_pbi` y `desempleo_nsa` (USA);
- `deuda_publica_usd` (PRY);
- `tc_usd_venta_diario` (BOL).

Además, `config/comparable/metas_inflacion.csv`: 111 tramos de metas con fuente oficial
([detalle](comparabilidad/metas_inflacion.md)).

## Archivos (`data/processed/comparable/`)
| Archivo | Contenido |
|---|---|
| `comparable_observaciones.parquet` / `.csv` | Formato largo: `pais, indicador, frecuencia, fecha, valor, regimen` |
| `comparable_series.csv` | Una fila por país × indicador, con `uso`, grados, `cobertura`, `metodo`, `insumos`, `n_obs`, `desde`, `hasta` |
| `comparable_catalogo.csv` | Definición, unidad, frecuencia y bloque de cada indicador |
| `comparable_cobertura.csv` | Indicador × país: uso y rango de fechas |
| `comparable_panel_<frecuencia>.csv` | Panel país × fecha, una columna por indicador (**excluye** lo `no_comparable`) |
| `comparable_validacion.csv` | Pruebas de consistencia con resultado ok / REVISAR |

## Cómo leer cada fila
- **`uso`** se deriva del grado de la revisión de comparabilidad (de niveles o de variaciones,
  según el tipo de indicador):
  - `comparable`: se puede comparar directamente.
  - `comparable_con_ajuste`: comparable. El ajuste mecánico ya está aplicado o se describe en
    `metodo`.
  - `solo_tendencias`: diferencias conceptuales (cobertura, definición). Sirve para ciclos,
    variaciones y correlaciones, **no para rankings de nivel**.
  - `no_comparable`: no se usa en comparaciones entre países (fuera de los paneles).
  - `sin_grado`: serie construida sin grado en la revisión.
- **`cobertura`**: qué mide exactamente el país. Por ejemplo, IPC de la capital, desempleo urbano,
  deuda neta, reservas netas, importaciones CIF o actividad mensual proxy. Viene de
  `config/comparable/cobertura.csv`.
- **`regimen`** (por observación): marcas de periodos especiales, separadas por `;`, definidas en
  `config/comparable/regimenes.csv`. Incluyen `cepo_cambiario`, `tc_fijo`, `intervencion_indec`,
  `hiperinflacion`, `alta_inflacion`, `quiebre_credito`, `quiebre_encuesta`,
  `tpm_instrumento_variable` y `covid`. No se borra nada: se marca. En estimaciones conviene usarlas
  como dummies o excluir esos tramos.
- **Cortes de muestra** (`config/comparable/cortes_muestra.csv`): tramos que sí se eliminan porque
  no miden el concepto. Por ejemplo, la TPM real de Chile antes de 2001-08, las expectativas de
  Argentina antes de 2016-06 y el M2 argentino antes de 1980.

## Indicadores
| Bloque | Indicadores |
|---|---|
| Actividad | `pbi_real_indice` y `pbi_desest_indice` (2019=100), `pbi_real_var_a` (a/a desde el nivel original), `pbi_desest_var_t` (t/t sin anualizar), `actividad_mensual_indice` / `_var_a`, `pbi_nominal_usd` |
| Precios | `ipc_indice` (2019=100), `inflacion_mensual`, `inflacion_12m`, `inflacion_12m_nacional`, `inflacion_subyacente_12m`, `inflacion_sae_12m`, `expectativa_inflacion_12m`, `meta_inflacion` (+ inferior/superior), `desvio_meta_pp`, `fuera_de_rango_meta` |
| Monetario | `tasa_politica_tea`, `tasa_interbancaria_tea`, `tasa_real_exante`, `diferencial_fed_pp`, `tasa_activa_promedio`, `tasa_pasiva_promedio`, `credito_privado_usd`, `credito_var_a`, `credito_real_var_a`, `credito_pct_pbi`, `dinero_amplio_var_a`, `dinero_amplio_pct_pbi` |
| Externo | `tc_ml_por_usd`, `tc_ml_por_usd_fin`, `depreciacion_var_a`, `volatilidad_tc`, `reservas_usd`, `reservas_brutas_usd`, `reservas_meses_importacion`, `reservas_pct_pbi`, `exportaciones_usd`, `importaciones_usd`, `balanza_comercial_usd`, `exportaciones_var_a_12m`, `importaciones_var_a_12m`, `exportaciones_bienes_trim_usd`, `importaciones_bienes_trim_usd`, `balanza_bienes_trim_usd`, `apertura_comercial_pct_pbi`, `cuenta_corriente_usd`, `cuenta_corriente_pct_pbi` |
| Fiscal | `resultado_fiscal_pct_pbi`, `resultado_fiscal_var_pp`, `deuda_publica_pct_pbi`, `deuda_publica_var_pp` |
| Laboral | `desempleo_trim`, `desempleo_anual`, `desempleo_var_a_pp`, `salario_minimo_mensual_ml`, `salario_minimo_usd`, `salario_minimo_real_indice`, `salario_minimo_real_var_a` |

## Transformaciones aplicadas
1. **Variaciones a/a desde el nivel original** en el PBI y la actividad mensual de todos los países.
   Así ECU, ESP y USA dejan de usar la variación sobre la serie desestacionalizada. Donde falta
   el nivel (USA antes de 2003) se usa la variación publicada, y `metodo` lo indica.
2. **Índices rebasados a 2019 = 100** (PBI, actividad, IPC, salario mínimo real). Esto elimina las
   diferencias de moneda, año base y anualización (factor 4 de ARG y MEX). Panamá no tiene IPC en
   2019 (empieza en 2024), así que no tiene `ipc_indice` rebasado.
3. **PBI desestacionalizado de Perú** encadenado desde la variación t/t anualizada del BCRP.
4. **Conversión a USD:**
   - flujos con el tipo de cambio promedio del periodo; saldos con el de fin de periodo;
   - España: la fuente cotiza USD por EUR, así que se invierte;
   - Bolivia: medio compra/venta;
   - Chile y Colombia: el tipo de cambio diario se re-fecha a t−1;
   - ECU, PAN y USA no se convierten.
5. **Tasas en TEA:**
   - act/360 (USA, ESP, CHL, MEX); TNA a 1 día (interbancaria de ARG);
   - Fed: punto medio del rango desde 2008-12;
   - BCE: MRO hasta 2008-09 y facilidad de depósito después;
   - ESP: €STR con el EONIA − 8,5 pb empalmado antes de 2019-10.
6. **Tasa real ex-ante** = (1+i)/(1+πᵉ)−1, y **diferencial frente a la Fed**, ambos en TEA.
7. **Crédito a tipo de cambio constante** (componente en ME al TC promedio de 2019) donde hay
   desglose MN/ME o un ratio de dolarización, y **crédito real** deflactado con el IPC.
8. **Dinero amplio:** M3 (incluye moneda extranjera) en lugar del M2 estrecho en ARG, BOL, PRY y URY,
   cuando existe la serie.
9. **Ratios sobre el PBI:** cuenta corriente (suma de 4 trimestres), crédito y dinero (diciembre),
   reservas (fin de año) y apertura comercial.
10. **Comercio de bienes trimestral homogéneo:** se usan los bienes de la balanza de pagos (FOB, con
    zonas francas) donde existen (ARG, ESP, PAN, URY); en el resto, la suma de aduana.
11. **Reservas:** serie bruta donde existe (BOL, COL, MEX) o donde la publicada ya es bruta; reservas
    en meses de importación y en % del PBI.
12. **Fiscal anual:**
    - el T4 de las series trimestrales (ESP, PER);
    - en MEX, los RFSP y el SHRFSP (sector público amplio);
    - en USA, la deuda en manos del público;
    - en PRY, la deuda recalculada con el PBI del BCP;
    - cambio anual en pp.
13. **Desempleo a trimestre calendario:**
    - trimestres móviles (BRA, CHL, PER): se toman mar, jun, sep y dic;
    - meses sueltos: promedio de 3 meses;
    - USA: serie sin desestacionalizar.

    Además, promedio anual y cambio a/a en pp.
14. **Salario mínimo mensual** (MEX diario × 30,4; ESP 14 pagas × 14/12), **en USD** y **real**.
15. **Metas de inflación** (`config/comparable/metas_inflacion.csv`, fuentes oficiales): centro,
    rango, desvío y fuera de rango. Para USA (la meta es sobre el PCE) y ESP (IAPC de la zona euro),
    `metodo` advierte que la meta se define sobre otro índice.

## Ejemplos
```python
import pandas as pd
base = "data/processed/comparable/"
obs = pd.read_parquet(base + "comparable_observaciones.parquet")
series = pd.read_csv(base + "comparable_series.csv")

# Panel trimestral de crecimiento, solo pares comparables y sin periodos de régimen especial
ok = series.query("indicador == 'pbi_real_var_a' and uso in ('comparable', 'comparable_con_ajuste')")
pbi = obs.merge(ok[["pais", "indicador"]]).query("regimen == ''")
tabla = pbi.pivot(index="fecha", columns="pais", values="valor")

# Tasa real ex-ante del bloque con metas de inflación
panel = pd.read_csv(base + "comparable_panel_mensual.csv", parse_dates=["fecha"])
real = panel.pivot(index="fecha", columns="pais", values="tasa_real_exante")[["BRA", "CHL", "COL", "MEX", "PER", "URY"]]
```

## Límites conocidos
- **Fiscal y deuda siguen con coberturas distintas** (`uso = solo_tendencias` en la mayoría). La
  columna `cobertura` permite agrupar: gobierno central, SPNF, gobierno general o sector público
  consolidado.
- **Tasas activas y pasivas:** se publican sin transformar; solo sirven para la dinámica dentro de
  cada país.
- **Subyacente:** `inflacion_subyacente_12m` mezcla definiciones. `inflacion_sae_12m` es más
  homogénea pero cubre 7 países (BRA, CHL, COL, ESP, PER, PRY, USA). En ESP excluye además bebidas
  y tabaco; en PRY también los servicios tarifados (ver `cobertura`).
- **Metas de inflación:** USA (PCE) y ESP desde 1999 (IAPC de la zona euro) tienen la meta sobre
  otro índice. BOL, ECU y PAN no tienen meta, y ARG solo en 2016-10 a 2018-09.
- **Desempleo:** PER (Lima) y ARG y BOL (urbano) no son nacionales; MEX no tiene dato sin
  `INEGI_TOKEN`; a USA le falta 2025-T4 (sin dato de octubre por el cierre del gobierno; no se imputa).
- **Huecos:** nunca se imputan. Si un modelo necesita series completas, se interpola en el análisis,
  nunca en `processed`.
