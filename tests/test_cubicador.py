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
