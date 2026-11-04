# Descargas BCRP

Descarga 1 567 series de [BCRPData](https://estadisticas.bcrp.gob.pe/estadisticas/series/), la base
de datos del Banco Central de Reserva del Perú, con su historia completa, y arma paneles por frecuencia (diaria,
mensual, trimestral y anual).

Temas: actividad, precios, política monetaria, tasas de interés, tipo de cambio y reservas, crédito y
liquidez, mercados, sector externo, finanzas públicas, empleo y expectativas. La lista completa está
en `config/series.csv`, y el catálogo del BCRP, en `docs/catalogo_bcrp.csv`.

## Cómo correrlo

Desde esta carpeta (`descargas-bcrp/`):

```bash
python src/descargar_series.py               # descarga o actualiza todas las series activas
python src/construir_tablas.py               # regenera data/processed/ (paneles por frecuencia)

# Tableros (outputs/*.html)
python src/visual_reservas.py
python src/visual_inflacion.py
python src/visual_transmision.py

# Tablero de finanzas públicas: antes, sus insumos propios
python src/descargar_geo.py                  # límites departamentales para el mapa
python src/descargar_proyecciones.py --fuente MEF_MMM   # Marco Macroeconómico Multianual del MEF
python src/descargar_ejecucion_mef.py        # ejecución presupuestal (Consulta Amigable del MEF)
python src/descargar_fmi.py                  # comparación entre países (FMI, DataMapper)
python src/visual_finanzas.py
```

**Finanzas públicas:**
- Los indicadores de riesgo de la deuda del MEF se bajan a mano a `data/manual/mef/`
  (`Indicadores_Deuda_Publica_<MM>_<AAAA>.xlsx`).
- La población por departamento del INEI viene en `config/insumo_inei_departamentos.csv`.
- Las reglas fiscales vigentes están en `config/reglas_fiscales.csv`.
- Las cifras del FMI se usan solo para comparar países; el tablero avisa que no son las del BCRP.
- Si falta un insumo, el tablero sale sin la pestaña que lo usa y lo avisa.

Opciones útiles:

```bash
python src/descargar_series.py --serie PN01770AM PD04638PD   # solo algunas series
python src/descargar_series.py --catalogo                    # además, refresca el catálogo del BCRP
python src/descargar_series.py --dry-run                     # solo informa
```

## Cómo funciona

- Una petición por serie a la API de BCRPData, con 1 s de pausa, siempre con el rango completo de fechas.
  Sin fechas, la API devuelve solo los últimos 5 años.
- **Revisiones:** si el BCRP cambia datos ya publicados, la versión anterior se guarda en `data/_control/historial/`.
- **Errores de la fuente:** no se imputan. Un valor inválido queda como faltante y se lista en
  `data/processed/bcrp_valores_invalidos.csv`.
- Detalles del formato: las diarias y trimestrales usan años de 2 dígitos, y setiembre aparece como `Set.` o `Sep.`.

## Datos

- `data/raw/`: respuestas de la API. No se suben al repositorio.
- `data/processed/`: paneles por frecuencia. Los principales, ya listos, están en [`../datos/bcrp/`](../datos/bcrp/).

**Requisitos adicionales:** la comparación internacional de `visual_inflacion.py` y `visual_transmision.py`
usa una capa de datos macro de otros países que aún no está en este repositorio, y `visual_transmision.py`
usa además las tasas activas de [`../descargas-sbs/`](../descargas-sbs/). Los tableros ya generados de cada
corte se pueden descargar en Releases (`tableros_<corte>.zip`).
