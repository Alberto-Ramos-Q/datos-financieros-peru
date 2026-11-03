# Geometría departamental para el mapa del crédito por departamento

| Archivo | Qué es |
|---|---|
| `peru_departamental_simple.geojson` | Original, sin cambios: límites de los 24 departamentos y la Provincia Constitucional del Callao (25 polígonos, WGS84). |
| `departamentos_svg.json` | Derivado para el tablero: proyectado y simplificado, un trazo SVG por departamento (clave = la del lector del boletín). |

- **Fuente:** repositorio público [juaneladio/peru-geojson](https://github.com/juaneladio/peru-geojson),
  archivo `peru_departamental_simple.geojson`
  (<https://raw.githubusercontent.com/juaneladio/peru-geojson/master/peru_departamental_simple.geojson>).
  Según su README, los límites departamentales son del **INEI (2007)**, distribuidos por el Geoservidor del
  MINAM y GEOIDEP. Bajado el 2026-10-23 (139 681 bytes, sha256 `3d34d545…1290`, el mismo que usa `../descargas-bcrp`).
- **Licencia:** Mozilla Public License 2.0 (archivo `LICENSE` del repositorio). Es una licencia por archivo: el
  derivado `departamentos_svg.json` se distribuye bajo la misma licencia, y la página pública lo cita con el
  enlace al repositorio. El GeoJSON original se guarda aquí sin modificar.
- **Uso:** solo para dibujar. Ninguna cifra sale de la geometría.
- **Cómo se arma** (`python src/visual_regional.py --geo`): proyección equirrectangular con el coseno de la
  latitud media (ancho 1000 unidades) y Douglas–Peucker por arco: cada tramo de borde entre dos nudos se
  simplifica una sola vez y se reusa en los dos departamentos que lo comparten, así no se abren huecos. El original
  ya viene simplificado: 3 344 → 3 271 vértices con tolerancia 0,6 unidades (~41 KB). `focus` es el centro del
  Callao, que la página usa para el recuadro ampliado de Lima y Callao. Los parámetros quedan en `meta`.
