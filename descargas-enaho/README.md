# Descargas ENAHO

Descarga los microdatos de la [Encuesta Nacional de Hogares (ENAHO)](https://proyectos.inei.gob.pe/microdatos/)
del INEI, 2004–2025, los convierte a Parquet y calcula la pobreza monetaria por departamento con el método del
INEI. Con eso se arma el tablero de pobreza monetaria por departamento.

Las cifras son **cálculo propio con los microdatos del INEI**, validado contra lo que publica el INEI:
- 2016–2025: nacional, área, región, dominio y departamentos, más gasto e ingreso por departamento.
- 2004–2015: cifras de los informes técnicos de cada año.

Las cifras propias cuadran con las oficiales. Los archivos `config/*_oficial*.csv` son las cifras del INEI
transcritas para esos controles.

## Cómo correrlo

Requiere las dependencias de [`../requirements.txt`](../requirements.txt) (incluido `pyreadstat`). Desde esta
carpeta (`descargas-enaho/`), en este orden:

```bash
# 1. Microdatos (lo ya descargado o construido se omite)
python src/descargar_enaho.py --desde 2004    # zips del portal de microdatos del INEI + documentación
python src/construir_parquet.py               # zips → Parquet
python src/construir_catalogo.py              # catálogo de variables
python src/construir_deflactores.py           # deflactores temporal y espacial
python src/validar_cifras_oficiales.py        # control de calidad

# 2. Pobreza por departamento y controles
python src/pobreza_departamental.py           # ~15 min: data/processed/pobreza/
python src/validar_poblacion_pobre.py         # personas pobres con el método del INEI

# 3. Tablero (outputs/pobreza_departamental.html, se abre con doble clic)
python src/visual_pobreza.py
```

- **Descarga respetuosa:** secuencial y con pausa entre archivos.
- **Población oficial:** `config/insumo_poblacion_adulta.csv` (INEI, Boletín Especial N.° 24, base Censo 2017).
- **Mapa:** usa `../descargas-sbs/config/geo/departamentos_svg.json`. Ver la excepción de licencia en
  [`../LICENSE-DATA.md`](../LICENSE-DATA.md).
- **Controles contra los PDF del INEI:** `verificar_pobreza_independiente.py`, `validar_pobreza_departamental.py`
  y `transcribir_*.py` leen los informes técnicos en PDF del INEI. Esos PDF no están en el repositorio; las
  referencias están en la nota metodológica del tablero. `verificar_pobreza_independiente.py` requiere además
  `pdftotext` (xpdf o poppler) en el PATH.

## Datos

- `data/raw/`: los zips tal como los publica el INEI. No se suben al repositorio.
- `data/processed/`: Parquet por año y tabla, y los resultados de pobreza. No se suben al repositorio.
- Los microdatos son del INEI y se rigen por sus condiciones de uso.
