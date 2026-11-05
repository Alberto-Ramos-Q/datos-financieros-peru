# Series macroeconómicas de 13 países

Descarga series macroeconómicas de 13 países **solo de las publicaciones oficiales de cada país**: banco
central, instituto de estadística, ministerio de economía o hacienda y superintendencias. No usa agregadores
(FRED, Banco Mundial, FMI, CEPAL, OCDE, etc.). Cada serie conserva toda la historia que publica su fuente.

Países: Perú, España, Estados Unidos, Chile, Argentina, Colombia, Ecuador, México, Panamá, Brasil, Uruguay,
Paraguay y Bolivia.

**En este repositorio la usan dos tableros del BCRP** (`../descargas-bcrp/`):
- *Inflación*: Lima frente al promedio nacional, la evolución en la región y las metas de inflación por país;
- *Transmisión de la política monetaria*: las tasas de política de la región y la tasa de la Fed.

Sin estos datos, esos dos tableros se generan sin esas secciones. Por eso este proyecto se corre **antes** que
los tableros del BCRP.

## Cómo correrlo

Requiere las dependencias de [`../requirements.txt`](../requirements.txt) y `curl` (lo usa el descargador de
Paraguay). Desde esta carpeta (`data_macro_paises/`):

```bash
python src/actualizar_todo.py                   # descarga los 13 países, consolida y arma la capa comparable (~1 h)
python src/actualizar_todo.py --paises chl mex  # solo algunos países
python src/actualizar_todo.py --solo-procesar   # rehace data/interim y data/processed sin red (~2 min)
python src/paises/col.py --serie trm_diaria     # una serie de un país
```

- Descargas secuenciales, con pausa de al menos 1 s. Cada país va contra sus propios servidores.
- Si un archivo oficial cambió, la versión anterior se guarda en `data/_control/historial/`.
- **Estados Unidos:** la API v1 del BLS permite 25 consultas por día y una corrida usa 12. Conviene correr
  Estados Unidos como máximo dos veces al día, o definir `BLS_API_KEY` (gratuita) para usar la v2.
- **Claves opcionales** (ninguna es obligatoria): `INEGI_TOKEN` habilita el desempleo de México;
  `BLS_API_KEY`, la API v2 del BLS.
- **Accesos frágiles:**
  - el Banco Central del Paraguay está detrás de Cloudflare y se baja con `curl`;
  - los servidores del Banco de la República (Colombia), el BCU, el INE de Uruguay y el MEFP de Bolivia no envían
    el certificado intermedio: el script completa la cadena sin desactivar la verificación;
  - la exportación Excel de la base de datos del Banco Central de Chile depende de un token del formulario.

  Si un país falla, ver su ficha en [`docs/fuentes/`](docs/fuentes/).

## Qué produce

- `data/processed/macro_observaciones.parquet`: todas las series en formato largo (país, fuente, código, fecha,
  valor, unidad).
- `data/processed/macro_series.csv`: título oficial, unidad, notas y cobertura de cada serie.
- `data/processed/comparable/`: **capa comparable entre países** (`src/armonizar.py`): 61 indicadores homogéneos
  (variaciones, índices 2019=100, conversión a USD, tasas en TEA, desvío frente a la meta de inflación), con el
  grado de comparabilidad de cada par país × indicador. Guía en [`docs/comparable.md`](docs/comparable.md).

## Antes de comparar entre países

Los indicadores comunes tienen la misma definición, pero **no siempre la misma cobertura o unidad**. La revisión
de los 364 pares indicador × país está en [`docs/comparabilidad/`](docs/comparabilidad/). Lo principal:
- **No aplican** por dolarización (Ecuador, Panamá) o por la unión monetaria (España): tasa de política propia,
  tipo de cambio y, en algunos casos, reservas y M2.
- **Coberturas parciales:** el IPC y el desempleo del Perú en esta base son de Lima Metropolitana; la deuda de
  México es neta; en Estados Unidos, el resultado fiscal y la deuda son del gobierno federal.
- **Cálculos propios con series oficiales** (no publicados así por la fuente): el resultado fiscal en % del PBI de
  Argentina, Colombia, México y Bolivia; la suma móvil de 4 trimestres del déficit de España; la inflación de
  Estados Unidos desde el CPI; las variaciones de 12 meses del IMAEP de Paraguay; y la balanza comercial de
  Uruguay.
- **Errores de la propia fuente:** no se imputan; quedan como faltantes.

## Estructura

```
data_macro_paises/
├── config/
│   ├── indicadores_comunes.csv      los 28 indicadores homologados
│   ├── series/<ISO3>.csv            qué se descarga de cada país (editar aquí, no en el código)
│   └── comparable/                  metas de inflación, regímenes, cortes de muestra y cobertura
├── src/
│   ├── comun.py                     cliente HTTP y utilidades comunes
│   ├── paises/<iso3>.py             descargador y procesador de cada país
│   ├── consolidar.py                data/interim → data/processed
│   ├── armonizar.py                 capa comparable
│   └── actualizar_todo.py           corre todo
└── docs/
    ├── fuentes/<ISO3>.md            fuentes, accesos, trampas del formato y cobertura de cada país
    ├── comparabilidad/              revisión de comparabilidad entre países
    └── comparable.md                guía de la capa comparable
```

Los datos (`data/`) no están en el repositorio: los genera el código desde cada fuente oficial.
