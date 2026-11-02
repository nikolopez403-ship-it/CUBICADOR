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

## Uso en AutoCAD o GstarCAD (Windows): comando CUBICAR

Funciona con AutoCAD completo, GstarCAD, BricsCAD y ZWCAD (no con AutoCAD LT, que no tiene ActiveX).

1. Ejecute `windows\instalar.bat` una vez: si no hay Python lo instala (winget), instala las
   dependencias y genera `windows\cubicar.lsp`.
2. Si no pudo instalar Python solo, instálelo desde python.org marcando *Add python.exe to PATH*.
3. En AutoCAD: `APPLOAD` → cargue `windows\cubicar.lsp` (agréguelo al *Maletín de inicio*).
4. Con el plano de losas CYPE abierto (y el de refuerzos también abierto si corresponde), escriba **CUBICAR**:
   - pregunta si cubicar también los demás planos abiertos,
   - si ya hay cuadrantes en la capa `CICLOS`: *Usar / Agregar / Redibujar*,
   - pide cada ciclo: **Rectángulo** (2 esquinas), **Polígono** (clic a clic, Enter para cerrar),
     **Seleccionar** una polilínea existente o **Terminar**; los dibuja en `CICLOS` con el texto C1, C2…,
   - pide piso y partición (sugeridos desde el título del plano),
   - la primera vez pide la planilla Armacero base (queda recordada),
   - genera `Pedidos fierro\P12 - LC - C1.xlsx`, `... - C2.xlsx`… y `P12 - LC_revision.xlsx`
     en la carpeta del plano, y abre la carpeta.

Lee el dibujo directamente desde AutoCAD (no necesita LibreDWG ni guardar el DWG).

## Planos de losas CYPECAD → pedido Armacero (consola)

    python -m cubicador cype PLANO_MALLA.dwg PLANO_REFUERZOS.dwg \
        --plantilla Pedido_Fe.xlsx --piso 12 --ciclo 3 -o "P12 - LC - C3.xlsx"

Requiere `dwgread` de LibreDWG (variable `DWGREAD` con su ruta si no está en el PATH).

- Lee los bloques de etiqueta de CYPE (CUANTIA, LARGO, lados A..E, PARCIAL) y sus enlaces
  `SCAD_LOSAS` a la polilínea (capa BARRAS) y la cota de rango (capa RANGOS).
- Cantidad: `Ø8a18` con rango R → techo(R/18) + 1; `F=F'=2Ø16` → 2 inf. + 2 sup.; `F'=3Ø12` → 3.
- Figura: sin lados = 101A; 2 lados = 102A (A = pata); 3 = 103A; 4 = 104A; 5 = 105A.
  Los quiebres de ±31° que CYPE dibuja para separar barras superpuestas se ignoran.
- Columna A = losa (bloque `_LOSA` + contorno), I (marca) = INF / SUP / SUPLE / REF.
- Escribe sobre la planilla original (conserva catálogo, imágenes, fórmulas y protección)
  y extiende la tabla si hay más de 100 filas.
- Barras sin cota de rango: el rango es el largo del muro que cruzan (si no hay muro, la viga).
- **Ciclos:** dibuje en AutoCAD polilíneas cerradas en una capa llamada p.ej. `CICLOS`, con un texto
  `C1`, `C2`… dentro de cada una (en el mismo plano o en un DXF aparte con `--ciclos`). Cada barra
  va al ciclo del cuadrante donde cae; si toca dos cuadrantes queda en el de menor número.
  Las barras de un rango se ubican una a una, así un grupo puede repartirse. Sale un Excel por ciclo.
- Genera además `*_revision.xlsx`: detalle por etiqueta con observaciones, **pendientes**
  (barras sin cota de rango, que no entran al pedido) y resumen de kg por diámetro.

## Tests

    python -m pytest
