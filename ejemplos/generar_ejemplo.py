"""Genera un plano DXF de prueba (viga + estribos + losa) en centímetros."""
import sys

import ezdxf

doc = ezdxf.new("R2018", setup=True)
doc.header["$INSUNITS"] = 5  # cm
msp = doc.modelspace()
for capa in ("FIERRO", "TXT-FIERRO", "MUROS"):
    doc.layers.add(capa)

F = {"layer": "FIERRO"}
T = {"layer": "TXT-FIERRO", "height": 5}

# Viga V1: barras inferiores rectas con L=
msp.add_lwpolyline([(0, 0), (600, 0)], dxfattribs=F)
msp.add_text("M1 3%%c16 L=600", dxfattribs=T).set_placement((250, 8))

# Barra superior con patas (U invertida): 30 + 600 + 30, sin L= -> largo desde el dibujo
msp.add_lwpolyline([(0, 20), (0, 50), (600, 50), (600, 20)], dxfattribs=F)
msp.add_text("M2 2Ø12", dxfattribs=T).set_placement((250, 58))

# Barra en L dibujada con LINEs sueltas
msp.add_line((700, 0), (700, 80), dxfattribs=F)
msp.add_line((700, 80), (950, 80), dxfattribs=F)
msp.add_text("M3 4φ10 L=3.30", dxfattribs=T).set_placement((780, 88))

# Estribo rectangular 20x40 cerrado, con espaciamiento y distribución
msp.add_lwpolyline([(0, -100), (20, -100), (20, -60), (0, -60)], close=True, dxfattribs=F)
msp.add_mtext("E1 %%c8@15 en 600", dxfattribs={"layer": "TXT-FIERRO", "char_height": 5}).set_location((30, -75))

# Malla de losa: dos textos en uno, sin dibujo
msp.add_text("Ø10@20 en 450 L=500 (x2)", dxfattribs=T).set_placement((0, -200))
msp.add_text("2Ø16 + 2Ø12 L=420", dxfattribs=T).set_placement((0, -250))

# Ruido que no debe cubicarse
msp.add_text("EJE A", dxfattribs={"layer": "MUROS", "height": 10}).set_placement((0, 300))
msp.add_lwpolyline([(-50, -300), (1000, -300)], dxfattribs={"layer": "MUROS"})

# Un bloque con barra y texto (detalle repetido)
blk = doc.blocks.new("DET_BARRA")
blk.add_lwpolyline([(0, 0), (0, 15), (250, 15)], dxfattribs=F)
blk.add_text("M4 1Ø18", dxfattribs=T).set_placement((100, 20))
msp.add_blockref("DET_BARRA", (1200, 0))

salida = sys.argv[1] if len(sys.argv) > 1 else "ejemplo_viga.dxf"
doc.saveas(salida)
print("Generado", salida)
