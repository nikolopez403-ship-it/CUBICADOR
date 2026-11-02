"""Asistente completo contra un AutoCAD simulado: dibujar ciclos -> cubicar -> Excel."""
import json
import sys
from pathlib import Path

import openpyxl
from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).parent))
import autocad_simulado as sim  # noqa: E402

from cubicador.asistente import InterfazAutoCAD, ejecutar  # noqa: E402
from cubicador.autocad_vivo import entidades_desde_autocad  # noqa: E402
from cubicador.lector_cype import Atributo, Entidad  # noqa: E402


def _plantilla(ruta):
    wb = Workbook()
    ws = wb.active
    ws.title = "ARM IMPORT"
    ws["B3"] = "=SUM(AA6:AA105)"
    for r in range(6, 106):
        ws[f"H{r}"] = f'=IF(SUM(K{r}:T{r})=0,"",SUM(K{r}:T{r}))'
    wb.save(ruta)


def _plano():
    # Malla Ø8a20 inferior, barra vertical de 300 cm, rango horizontal de 400 cm -> 21 barras en x = 0..400
    return [
        Entidad("INSERT", 0x10, "TEXTO", bloque="ETIQ", punto=(5, 100),
                atributos=[Atributo("CUANTIA", "%%c8a20i", 1.5708), Atributo("LARGO", "L=300")],
                enlaces=[0x11, 0x12]),
        Entidad("LWPOLYLINE", 0x11, "BARRAS", puntos=[(0, 0), (0, 300)]),
        Entidad("DIMENSION", 0x12, "RANGOS", medida=400.0, segmento=((0, 150), (400, 150))),
        Entidad("INSERT", 0x13, "0", bloque="_LOSA", punto=(200, 200),
                atributos=[Atributo("NUMERO", "501"), Atributo("E", "15")]),
        Entidad("INSERT", 0x14, "0", bloque="ROTULO", punto=(0, -100),
                atributos=[Atributo("TITULO", "ARMADURA LOSAS CIELO 5° PISO")]),
    ]


def test_asistente_dibuja_ciclos_y_exporta(tmp_path):
    _plantilla(tmp_path / "plantilla.xlsx")
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"plantilla": str(tmp_path / "plantilla.xlsx")}))
    guion = ["Rectangulo", (-10, -10), (200, 310),      # C1: hasta x=200 (la barra en x=200 toca ambos)
             "", (200, -10), (410, 310),                # C2 (Enter = Rectángulo)
             "Terminar", "", ""]                        # piso y partición sugeridos
    doc = sim.Documento("losa.dwg", str(tmp_path), [sim.com_desde_entidad(e) for e in _plano()], guion)
    assert ejecutar(InterfazAutoCAD(sim.Aplicacion([doc]), doc), entidades_desde_autocad, cfg) == 0

    carpeta = tmp_path / "Pedidos fierro"
    c1 = openpyxl.load_workbook(carpeta / "P5 - LC - C1.xlsx")["ARM IMPORT"]
    c2 = openpyxl.load_workbook(carpeta / "P5 - LC - C2.xlsx")["ARM IMPORT"]
    fila = lambda ws: [ws[f"{c}6"].value for c in "ABCDEFG"] + [ws["K6"].value]
    assert fila(c1) == ["Losa 501", "LC", 5, 1, 11, 8, "101A", 300]   # 0..200: 11 barras (amarre en x=200)
    assert fila(c2) == ["Losa 501", "LC", 5, 2, 10, 8, "101A", 300]   # 220..400: 10 barras
    dibujados = [e for e in doc.ModelSpace.ents if e.Layer == "CICLOS"]
    assert sorted(getattr(e, "TextString", "") for e in dibujados) == ["", "", "C1", "C2"]


def test_asistente_usa_cuadrantes_existentes(tmp_path):
    _plantilla(tmp_path / "plantilla.xlsx")
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"plantilla": str(tmp_path / "plantilla.xlsx")}))
    ents = _plano() + [
        Entidad("LWPOLYLINE", 0x20, "CICLOS", puntos=[(-10, -10), (410, -10), (410, 310), (-10, 310)], cerrado=True),
        Entidad("TEXT", 0x21, "CICLOS", texto="C4", punto=(200, 150)),
    ]
    doc = sim.Documento("losa.dwg", str(tmp_path), [sim.com_desde_entidad(e) for e in ents], ["Usar", "", ""])
    assert ejecutar(InterfazAutoCAD(sim.Aplicacion([doc]), doc), entidades_desde_autocad, cfg) == 0
    ws = openpyxl.load_workbook(tmp_path / "Pedidos fierro" / "P5 - LC - C4.xlsx")["ARM IMPORT"]
    assert ws["D6"].value == 4 and ws["E6"].value == 21
