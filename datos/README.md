# Datos

Tablas listas para usar. Se leen directo desde GitHub con pandas (los `.csv.gz` también:
pandas los descomprime solo).

```python
import pandas as pd
base = "https://raw.githubusercontent.com/Alberto-Ramos-Q/datos-financieros-peru/main/datos"
panel = pd.read_csv(f"{base}/sbs/panel_entidad_mes.csv")
```

| Archivo | Qué contiene | Filas | Columnas | Tamaño |
|---|---|---:|---:|---:|
| [`sbs/panel_entidad_mes.csv`](sbs/panel_entidad_mes.csv) | Panel entidad × mes: tamaño, calidad de cartera, solvencia, rentabilidad, liquidez y sensibilidad de cada entidad (55 indicadores). | 11 606 | 62 | 5,7 MB |
| [`sbs/indicadores_ambito_mes.csv.gz`](sbs/indicadores_ambito_mes.csv.gz) | Indicadores por ámbito (sistema, subsistema y entidad) y mes, en formato largo, con numerador y denominador. | 465 668 | 8 | 10,7 MB |
| [`sbs/tasas_activas.csv.gz`](sbs/tasas_activas.csv.gz) | Tasas activas en moneda nacional por tipo de crédito y entidad. | 349 646 | 13 | 2,1 MB |
| [`sbs/indicadores_financieros.csv.gz`](sbs/indicadores_financieros.csv.gz) | Cuadro de indicadores financieros del Boletín Estadístico (tal como lo publica la SBS, en formato largo). | 219 621 | 12 | 2,4 MB |
| [`sbs/clasificaciones.csv`](sbs/clasificaciones.csv) | Clasificaciones de riesgo de cada entidad por mes (peor y mejor clasificación vigente, número de clasificadoras, perspectiva). | 6 261 | 9 | 0,7 MB |
| [`sbs/sf2103_deudores.csv`](sbs/sf2103_deudores.csv) | Deudores únicos del sistema financiero por grupo (reporte SF-2103), trimestral. | 270 | 12 | 90 KB |
| [`sbs/entidades.csv`](sbs/entidades.csv) | Maestro de entidades: identificador, nombre y subsistema. | 105 | 7 | 22 KB |
| [`bcrp/bcrp_series.csv`](bcrp/bcrp_series.csv) | Catálogo de las series: código del BCRP, frecuencia, tema, nombre corto y título. | 1 567 | 8 | 0,3 MB |
| [`bcrp/bcrp_panel_mensual.csv`](bcrp/bcrp_panel_mensual.csv) | Panel de series mensuales (una columna por serie). | 933 | 967 | 4,7 MB |
| [`bcrp/bcrp_panel_trimestral.csv`](bcrp/bcrp_panel_trimestral.csv) | Panel de series trimestrales. | 190 | 282 | 0,5 MB |
| [`bcrp/bcrp_panel_anual.csv`](bcrp/bcrp_panel_anual.csv) | Panel de series anuales. | 104 | 291 | 0,2 MB |
| [`bcrp/bcrp_panel_diaria.csv`](bcrp/bcrp_panel_diaria.csv) | Panel de series diarias. | 8 283 | 31 | 1,7 MB |

Las columnas de cada tabla están en [`DICCIONARIO.md`](DICCIONARIO.md).

**Convenciones:**
- `periodo`: mes en formato AAAAMM. `id_entidad`: identificador estable de la entidad (ver `sbs/entidades.csv`).
- Montos de la SBS en miles de soles, salvo que la columna indique otra unidad.
- `sbs/entidades.csv`: lee la columna `ruc` como texto (`dtype={"ruc": str}`) para no perder dígitos.
- Un valor vacío significa que la fuente no lo publicó para ese periodo; no se imputa.

**Tablas completas en parquet** (dataset maestro del boletín, estados financieros por entidad, todos los
cuadros del boletín y todas las observaciones del BCRP): en [Releases](../../../releases), un paquete por corte.

Licencia: [CC BY 4.0](../LICENSE-DATA.md). Cita la fuente original (SBS o BCRP) y este repositorio.
