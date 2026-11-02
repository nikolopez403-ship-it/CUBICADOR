# Cubicador de fierro para AutoCAD

Lee planos de cálculo (DXF, DWG o el dibujo abierto en AutoCAD), interpreta las
anotaciones de armadura y genera una cubicación detallada en Excel: marca,
cantidad, diámetro, forma, tramos, largo unitario y total, peso y resumen por diámetro.

## Instalación

    pip install -r requirements.txt

## Uso

    # Desde un archivo (DXF directo; DWG requiere ODA File Converter instalado)
    python -m cubicador archivo PLANO.dxf -o cubicacion.xlsx --capas-fierro "*FIERRO*,ARM*"

    # En vivo con AutoCAD abierto (Windows): pide seleccionar la zona en pantalla
    python -m cubicador vivo --seleccion -o cubicacion.xlsx

Opciones: `--unidad-dibujo mm|cm|m` (por defecto `$INSUNITS`), `--unidad-texto auto|cm|m|mm`,
`--capas-texto`, `--radio` (distancia máx. texto‑barra en cm), `--sin-ganchos`.

## Qué interpreta

| Texto en plano          | Resultado                                     |
|-------------------------|-----------------------------------------------|
| `M1 3Ø16 L=600`         | 3 barras Ø16 de 6,00 m                        |
| `4φ10 L=3.30`           | largo en metros (detección automática)        |
| `E1 Ø8@15 en 600`       | 600/15 + 1 = 41 estribos                      |
| `Ø10@20 en 450 (x2)`    | cantidad calculada y multiplicada por 2       |
| `2Ø16 + 2Ø12 L=420`     | dos partidas que comparten el largo           |
| `M5 2Ø12 (25+300+25)`   | largo desde los tramos indicados              |

Símbolos aceptados: `Ø ø φ Φ ∅ %%c fi`.

**Geometría:** cada texto se asocia a la polilínea (o cadena de LINEs) más cercana en las capas de
fierro. De ahí se obtienen los tramos y la forma (recta, L, U, Z, gancho, estribo cerrado). Si no hay `L=`,
el largo sale del dibujo; a los estribos cerrados se les suman 2 ganchos sísmicos de 135°
(6db ≥ 7,5 cm). Si `L=` y el dibujo difieren más de 5 %, queda la observación.

Se recorre el contenido de bloques (INSERT), los MTEXT, los atributos y los multileaders (se usa la
punta de la flecha para asociar).

**Excel:** hoja *Detalle* (filas con observaciones en amarillo) y hoja *Resumen por diámetro*
(barras, metros, kg y barras de 12 m aprox.).

## Limitaciones actuales

- Depende de que la armadura esté anotada con texto. Planos con cuadros de doblado en tablas
  o con notaciones propias de cada oficina pueden requerir ajustar `cubicador/parser.py`.
- Con espaciamiento sin largo de distribución (`Ø8@20` solo) se asume 1 y se marca para revisar.
- No descuenta traslapes ni optimiza cortes.
- La conexión en vivo (`autocad_vivo.py`) usa COM de AutoCAD y no está probada en Windows todavía.

## Tests

    python -m pytest
