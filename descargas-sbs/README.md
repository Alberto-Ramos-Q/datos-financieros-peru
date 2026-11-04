# Descargas SBS

Descarga, lee y consolida los reportes públicos de la Superintendencia de Banca, Seguros y AFP (SBS):

- **Boletín Estadístico del Sistema Financiero:** 146 cuadros en total entre cinco subsistemas (banca múltiple,
  empresas financieras, cajas municipales, cajas rurales y empresas de crédito), desde 2010 o desde que la
  SBS publica cada cuadro.
- **Tasas activas** por tipo de crédito y entidad, en moneda nacional, desde 2015.
- **SF-2103 «Evolución del Sistema Financiero»:** deudores únicos del sistema por grupo, trimestral.
- **Clasificaciones de riesgo** de las entidades, desde los informes públicos de las clasificadoras.
- **Maestro de entidades** (`config/entidades/`): reconoce las variantes de nombre de cada entidad, sus cambios
  de nombre y de subsistema, fusiones y salidas.

## Cómo correrlo

Requiere Python 3.11 o superior y las dependencias de [`../requirements.txt`](../requirements.txt) (incluido
`python -m playwright install chromium`, que usa la descarga de tasas). Desde esta carpeta (`descargas-sbs/`),
en este orden:

```bash
# 1. Descargar (incremental: solo lo nuevo o lo republicado)
python src/descargar_boletin.py              # Boletín Estadístico (la primera vez tarda varias horas)
python src/descargar_tasas.py                # tasas activas
python src/descargar_sf2103.py               # SF-2103 (PDF trimestral)
python src/descargar_clasificadoras.py indice
python src/descargar_clasificadoras.py pdf

# 2. Leer y consolidar
python src/leer_boletin.py                   # Excel → data/processed/boletin/<tema>.parquet
python -P src/leer_tasas.py                  # → data/processed/tasas_activas.parquet
python -P src/leer_sf2103.py                 # → data/processed/sf2103_deudores.parquet
python -P src/leer_clasificadoras.py         # → data/processed/clasificaciones.parquet
python src/consolidar.py                     # dataset maestro + panel entidad × mes
python src/indicadores_datos.py              # indicadores por ámbito y mes

# 3. Tableros (outputs/*.html, se abren con doble clic)
python src/visual_mora.py
python src/visual_solvencia.py
python src/visual_rentabilidad.py
python src/visual_regional.py
python src/visual_liquidez.py
python src/visual_tasas.py
python src/visual_eeff.py
python src/visual_indicadores.py

# Tablero de concentración y alcance (con comparación internacional)
python src/eventos_mercado.py                # entradas, salidas y fusiones de entidades (control)
python src/internacional/descargar_chile.py
python src/internacional/descargar_colombia.py
python src/internacional/descargar_brasil.py
python src/internacional/construir_peru.py
python src/internacional/construir_chile.py
python src/internacional/construir_colombia.py
python src/internacional/construir_brasil.py
python src/visual_mercado.py
```

**Concentración y alcance:**
- La comparación internacional usa los datos públicos de la CMF (Chile), la Superintendencia Financiera (Colombia)
  y el Banco Central do Brasil.
- Los descargadores van de a un servidor por vez y con pausa.
- La población adulta del INEI viene en `config/insumo_poblacion_adulta.csv`.
- Los errores de origen de la SBS (meses en que un cuadro repite cifras de otro mes) están listados en
  `src/errores_origen.py`. Todos los tableros los aplican.

Opciones útiles:

```bash
python src/descargar_boletin.py --dry-run                     # solo informa qué bajaría
python src/descargar_boletin.py --serie B-2201 --desde 202401 # una serie desde un mes
python src/descargar_boletin.py --barrido 1                   # solo meses nuevos + revisión del último
python src/revisar_temas.py                                   # cobertura y validación por tema
```

## Cómo funciona

- **Descarga respetuosa:** secuencial, con pausa de ~1 s entre archivos. Los servidores de la SBS cortan la
  conexión si reciben peticiones en paralelo.
- **Republicaciones:** si la SBS corrige un archivo ya publicado, el descargador lo detecta, lo reemplaza y
  guarda la versión anterior en `data/_control/historial/`.
- **Lectores por tema** (`src/lector/`): cada cuadro del boletín tiene su lector, que normaliza nombres de
  entidades, unidades y fechas, y valida los totales contra los que publica la SBS.
- **Último mes desigual:** cada tablero muestra el último dato publicado de cada indicador con su mes, porque
  la SBS no publica todos los cuadros a la vez.
- `config/series.csv` lista las series que se descargan; para agregar una, se añade una fila (los códigos están
  en `docs/catalogo_boletin.csv`).

## Datos

- `data/raw/`: los Excel y PDF tal como los publica la SBS. No se suben al repositorio.
- `data/processed/`: tablas en parquet. Las principales, ya listas, están en [`../datos/sbs/`](../datos/sbs/).

**Requisito adicional:** `visual_regional.py --insumos` (rehacer población y VAB por departamento) lee datos
procesados del INEI que aún no están en este repositorio. Sin esa opción, el tablero usa el insumo guardado en
`config/insumos_departamentales.csv`.
