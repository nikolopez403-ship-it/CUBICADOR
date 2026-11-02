import subprocess
import sys
from pathlib import Path

import pytest

from cubicador.cubicacion import Opciones, cubicar
from cubicador.formas import clasificar
from cubicador.lector_dxf import leer_dxf
from cubicador.modelo import Trazo
from cubicador.parser import interpretar

RAIZ = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("texto,diam,cant,largo,esp", [
    ("3Ø12", 12, 3, None, None),
    ("M1 3%%c16 L=600", 16, 3, 600, None),
    ("M3 4φ10 L=3.30", 10, 4, 330, None),
    ("Ø8@20", 8, None, None, 20),
    ("E1 ø8 a 15 en 450", 8, None, None, 15),
    ("B2: 2∅22 L=1250", 22, 2, 1250, None),
])
def test_interpretar(texto, diam, cant, largo, esp):
    (a,) = interpretar(texto)
    assert a.diametro == diam
    assert a.cantidad == cant
    assert (a.largo_cm and round(a.largo_cm)) == largo
    assert a.espaciamiento_cm == esp


def test_grupo_comparte_largo():
    a, b = interpretar("2Ø16 + 2Ø12 L=420")
    assert (a.diametro, b.diametro) == (16, 12)
    assert a.largo_cm == b.largo_cm == 420


def test_multiplicador_y_tramos():
    (a,) = interpretar("M5 2Ø12 (25+300+25) (x4)")
    assert a.multiplicador == 4
    assert a.tramos_cm == [25, 300, 25]


def test_textos_que_no_son_fierro():
    assert interpretar("EJE A") == []
    assert interpretar("NPT +3.50") == []


def test_formas():
    assert clasificar(Trazo([600], [(0, 0), (600, 0)])) == "Recta"
    assert clasificar(Trazo([30, 600, 30], [(0, 30), (0, 0), (600, 0), (600, 30)])) == "U (dos dobleces)"
    rect = [(0, 0), (20, 0), (20, 40), (0, 40), (0, 0)]
    assert clasificar(Trazo([20, 40, 20, 40], rect, cerrado=True)) == "Estribo rectangular"


@pytest.fixture(scope="module")
def plano(tmp_path_factory):
    ruta = tmp_path_factory.mktemp("dxf") / "ej.dxf"
    subprocess.run([sys.executable, str(RAIZ / "ejemplos/generar_ejemplo.py"), str(ruta)], check=True)
    return ruta


def test_cubicacion_plano_ejemplo(plano):
    partidas = {p.marca: p for p in cubicar(leer_dxf(plano, capas_fierro=["FIERRO"]), Opciones())}
    assert partidas["M1"].largo_total_m == 18.0
    assert partidas["M2"].forma == "U (dos dobleces)" and partidas["M2"].largo_unitario_m == 6.6
    assert partidas["M3"].forma == "L (un doblez)"          # dibujada con LINEs sueltas
    assert partidas["E1"].cantidad == 41                    # 600/15 + 1
    assert partidas["E1"].forma == "Estribo rectangular"
    assert partidas["M4"].largo_unitario_m == 2.65          # dentro de un bloque
    assert "EJE A" not in [p.texto_original for p in partidas.values()]


# --- CYPE / Armacero -------------------------------------------------------
from cubicador.cubicacion_cype import cantidad_por_rango, figura_cype, interpretar_cuantia


@pytest.mark.parametrize("txt,esperado", [
    ("%%c8a18s", {"cara": "", "n": None, "d": 8, "s": 18.0, "pos": "s"}),
    ("F'=%%c10a30", {"cara": "F'", "n": None, "d": 10, "s": 30.0, "pos": ""}),
    ("F=F'=2%%c16", {"cara": "F=F'", "n": 2, "d": 16, "s": None, "pos": ""}),
    ("F'=3%%C12", {"cara": "F'", "n": 3, "d": 12, "s": None, "pos": ""}),
])
def test_cuantia_cype(txt, esperado):
    assert interpretar_cuantia(txt) == esperado


def test_cantidad_por_rango():
    assert cantidad_por_rango(560, 18) == 33   # techo(31.1) + 1
    assert cantidad_por_rango(540, 18) == 31   # exacto: 30 + 1


def test_figuras_cype():
    assert figura_cype([], [], 450, []) == ("101A", [450])
    assert figura_cype([150, 20], [90], None, []) == ("102A", [20, 150])
    assert figura_cype([12, 300, 12], [90, 90], None, []) == ("103A", [12, 300, 12])
    assert figura_cype([8, 12, 120, 12, 8], [-90] * 4, None, []) == ("105A", [8, 12, 120, 12, 8])


def test_exportar_armacero(tmp_path):
    from openpyxl import Workbook
    from cubicador.armacero import FilaPedido, exportar_armacero
    import openpyxl
    # plantilla mínima con la estructura de la hoja ARM IMPORT
    wb = Workbook()
    ws = wb.active
    ws.title = "ARM IMPORT"
    ws["B2"] = '=CONCATENATE(C6," - ",B6)'
    ws["B3"] = "=SUM(AA6:AA105)"
    for r in range(6, 106):
        ws[f"H{r}"] = f'=IF(SUM(K{r}:T{r})=0,"",SUM(K{r}:T{r}))'
        ws[f"AA{r}"] = f'=IFERROR(Z{r}*E{r},"")'
    wb.save(tmp_path / "plantilla.xlsx")
    filas = [FilaPedido("Losa 1", "LC", 12, 3, 5, 10, "103A", [12, 300, 12])] * 120
    exportar_armacero(filas, tmp_path / "plantilla.xlsx", tmp_path / "out.xlsx")
    out = openpyxl.load_workbook(tmp_path / "out.xlsx")["ARM IMPORT"]
    assert [out[f"{c}6"].value for c in "ABCDEFG"] == ["Losa 1", "LC", 12, 3, 5, 10, "103A"]
    assert out["M6"].value == 12 and out["K125"].value == 12
    assert out["H125"].value.startswith("=IF(SUM(K125:T125)")
    assert out["B3"].value == "=SUM(AA6:AA125)"


# --- Ciclos ------------------------------------------------------------------
def test_ciclo_menor_si_toca_dos_cuadrantes():
    from cubicador.ciclos import ciclo_de
    from cubicador.lector_cype import Cuadrante
    c1 = Cuadrante(1, "C1", [(0, 0), (100, 0), (100, 100), (0, 100)])
    c2 = Cuadrante(2, "C2", [(100, 0), (200, 0), (200, 100), (100, 100)])
    assert ciclo_de([(10, 50), (90, 50)], [c1, c2]) == 1
    assert ciclo_de([(110, 50), (190, 50)], [c1, c2]) == 2
    assert ciclo_de([(150, 50), (95, 50)], [c1, c2]) == 1      # viene de C2 y amarra en C1
    assert ciclo_de([(300, 50), (400, 50)], [c1, c2]) is None


def test_rango_por_largo_de_muro():
    from cubicador.cubicacion_cype import _rango_por_apoyo
    from cubicador.lector_cype import EtiquetaCype
    from cubicador.modelo import Trazo
    et = EtiquetaCype("F'=Ø10a30", trazo=Trazo([300], [(0, -150), (0, 150)]))
    muro = [((-200, 0), (100, 0)), ((100, 0), (370, 0)),       # cara 1 partida en dos líneas
            ((-200, 15), (370, 15))]                           # cara 2
    largo, _ = _rango_por_apoyo(et, muro)
    assert round(largo) == 570
