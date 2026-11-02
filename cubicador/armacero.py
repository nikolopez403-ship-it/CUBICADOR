"""Exportación al formato de pedido Armacero (planilla "ARM IMPORT").

Se usa la planilla original del cliente como plantilla: se editan directamente
los XML de la hoja "ARM IMPORT" para conservar intactos el catálogo con
imágenes, las fórmulas, la protección de hoja y el formato condicional
(openpyxl destruiría las imágenes en celda y las extensiones).

Columnas de entrada que se llenan (fila 6 en adelante):
    A eje/viga/losa · B partición · C piso · D ciclo · E cantidad · F Ø mm
    G figura · I marca · K..T lados A..J (cm) · AG..AJ ángulos no estándar
"""
from __future__ import annotations

import copy
import math
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from .formas import _giro
from .modelo import Trazo

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
N = f"{{{NS}}}"
HOJA = "ARM IMPORT"
FILA_INICIO = 6
FILA_FIN_PLANTILLA = 105
COLS_LADOS = ["K", "L", "M", "N", "O", "P", "Q", "R", "S", "T"]
COLS_ANG = ["AG", "AH", "AI", "AJ"]
COLS_ENTRADA = ["A", "B", "C", "D", "E", "F", "G", "I", *COLS_LADOS, *COLS_ANG]


# ---------------------------------------------------------------------------
# Asignación de figura del catálogo
# ---------------------------------------------------------------------------

@dataclass
class Figura:
    codigo: str
    lados: list[int]
    angulos: list[int] = field(default_factory=list)  # solo si difieren del catálogo
    observacion: str = ""


def _tipo_doblez(giro: float) -> str:
    g = abs(giro)
    if 70 <= g <= 110:
        return "90"
    if g > 110:
        return "<45"    # gancho sísmico (giro de 135°)
    return "<135"       # doblez suave (giro de 45°)


def _r(x: float) -> int:
    return int(round(x))


def gancho_estribo_cm(diam: int) -> int:
    return math.ceil(max(6 * diam / 10, 7.5))


# figuras de 3 tramos: (doblez1, doblez2, mismo_sentido) -> código
_FIG3 = {
    ("90", "90", True): "103A", ("<45", "<45", True): "103B", ("90", "<45", True): "103C",
    ("90", "<135", True): "103D", ("<135", "<135", True): "103E", ("<135", "<45", True): "103F",
    ("90", "90", False): "103G", ("<135", "<135", False): "103H", ("90", "<135", False): "103I",
    ("<135", "<45", False): "103J", ("90", "<45", False): "103K", ("<45", "<45", False): "103L",
}
_ORDEN_TIPO = {"90": 0, "<135": 1, "<45": 2}
# figuras de 4 tramos con dobleces a 90°, patrón de signos normalizado
_FIG4 = {(1, 1, 1): "104A", (1, -1, -1): "104G", (1, -1, 1): "104N"}


def figura_desde_trazo(tr: Trazo, diam: int) -> Figura:
    lados = tr.tramos
    n = len(lados)
    if tr.cerrado:
        if n == 4:
            # 106A: A gancho, B alto, C ancho, D alto, E ancho, F gancho
            a, b = lados[0], lados[1]
            alto, ancho = (a, b) if a <= b else (b, a)
            g = gancho_estribo_cm(diam)
            return Figura("106A", [g, _r(alto), _r(ancho), _r(alto), _r(ancho), g])
        return Figura("REVISAR", [_r(x) for x in lados], observacion=f"Estribo cerrado de {n} lados")
    if n == 1:
        return Figura("101A", [_r(lados[0])])

    v = tr.vertices
    giros = [_giro(v[i - 1], v[i], v[i + 1]) for i in range(1, len(v) - 1)] if len(v) == n + 1 else []
    if len(giros) != n - 1:
        return Figura("REVISAR", [_r(x) for x in lados], observacion="Geometría con arcos")
    tipos = [_tipo_doblez(g) for g in giros]

    if n == 2:
        cod = {"90": "102A", "<135": "102B", "<45": "102C"}[tipos[0]]
        a, b = lados
        if cod == "102A" and a > b:  # en 102A la pata corta es A
            a, b = b, a
        return Figura(cod, [_r(a), _r(b)])

    if n == 3:
        mismo = giros[0] * giros[1] > 0
        t1, t2 = tipos
        lad = list(lados)
        if _ORDEN_TIPO[t1] > _ORDEN_TIPO[t2]:   # orden canónico del catálogo
            t1, t2 = t2, t1
            lad.reverse()
        cod = _FIG3.get((t1, t2, mismo))
        if cod:
            return Figura(cod, [_r(x) for x in lad])

    if n == 4 and all(t == "90" for t in tipos):
        signos = tuple(1 if g > 0 else -1 for g in giros)
        for cand, lad in ((signos, lados), (tuple(-s for s in reversed(signos)), lados[::-1])):
            norm = tuple(s * cand[0] for s in cand)
            if norm in _FIG4:
                return Figura(_FIG4[norm], [_r(x) for x in lad])

    if n == 5 and all(t == "90" for t in tipos) and len({g > 0 for g in giros}) == 1:
        return Figura("105A", [_r(x) for x in lados])

    return Figura(f"10{min(n, 6)}A" if n <= 6 else "REVISAR", [_r(x) for x in lados[:10]],
                  observacion=f"Forma de {n} tramos sin equivalente exacto en catálogo: revisar figura")


def figura_desde_largo(largo_cm: float) -> Figura:
    return Figura("101A", [_r(largo_cm)])


def ajustar_a_largo(fig: Figura, largo_cm: float) -> Figura:
    """Ajusta el lado mayor para que la suma de lados sea el L= indicado en el plano."""
    if not fig.lados:
        return fig
    dif = _r(largo_cm) - sum(fig.lados)
    if dif:
        i = max(range(len(fig.lados)), key=lambda k: fig.lados[k])
        fig.lados[i] += dif
    return fig


# ---------------------------------------------------------------------------
# Escritura sobre la plantilla
# ---------------------------------------------------------------------------

@dataclass
class FilaPedido:
    elemento: str          # A: eje / viga / losa
    particion: str         # B: FUND, ELEV, LC, VC, BAT, OTRO
    piso: str | int        # C
    ciclo: str | int       # D
    cantidad: int          # E
    diametro: int          # F
    figura: str            # G
    lados: list[int]       # K..T
    marca: str = ""        # I
    angulos: list[int] = field(default_factory=list)  # AG..AJ


def _col_idx(col: str) -> int:
    n = 0
    for ch in col:
        n = n * 26 + ord(ch) - 64
    return n


def _split_ref(ref: str) -> tuple[str, int]:
    m = re.match(r"([A-Z]+)(\d+)", ref)
    return m.group(1), int(m.group(2))


def _ruta_hoja(z: zipfile.ZipFile, nombre: str) -> str:
    wb = etree.fromstring(z.read("xl/workbook.xml"))
    rels = etree.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    rid = None
    for s in wb.iter(f"{N}sheet"):
        if s.get("name") == nombre:
            rid = s.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
    if rid is None:
        raise ValueError(f"La plantilla no tiene la hoja '{nombre}'")
    for r in rels:
        if r.get("Id") == rid:
            return "xl/" + r.get("Target").lstrip("/").removeprefix("xl/")
    raise ValueError("Relación de hoja no encontrada")


def _celda(fila, col: str, r: int):
    ref = f"{col}{r}"
    for c in fila.findall(f"{N}c"):
        if c.get("r") == ref:
            return c
    # insertar en orden de columna
    nueva = etree.SubElement(fila, f"{N}c", r=ref)
    fila.remove(nueva)
    idx = _col_idx(col)
    for i, c in enumerate(fila.findall(f"{N}c")):
        if _col_idx(_split_ref(c.get("r"))[0]) > idx:
            c.addprevious(nueva)
            return nueva
    fila.append(nueva)
    return nueva


def _poner_valor(c, valor):
    for hijo in list(c):
        c.remove(hijo)
    for a in ("t", "vm", "cm"):
        c.attrib.pop(a, None)
    if valor is None or valor == "":
        return
    if isinstance(valor, (int, float)):
        etree.SubElement(c, f"{N}v").text = repr(valor) if isinstance(valor, float) else str(valor)
    else:
        c.set("t", "inlineStr")
        is_ = etree.SubElement(c, f"{N}is")
        etree.SubElement(is_, f"{N}t").text = str(valor)


def _limpiar_cache_formula(c):
    """Quita el valor calculado guardado para que Excel recalcule al abrir."""
    v = c.find(f"{N}v")
    if v is not None:
        c.remove(v)
    for a in ("t", "vm"):
        c.attrib.pop(a, None)


def _num_o_texto(x):
    if isinstance(x, (int, float)):
        return x
    s = str(x).strip()
    return int(s) if re.fullmatch(r"-?\d+", s) else s


def exportar_armacero(filas: list[FilaPedido], plantilla: str | Path, salida: str | Path) -> Path:
    plantilla, salida = Path(plantilla), Path(salida)
    with zipfile.ZipFile(plantilla) as z:
        ruta_hoja = _ruta_hoja(z, HOJA)
        hoja = etree.fromstring(z.read(ruta_hoja))
        wb_xml = etree.fromstring(z.read("xl/workbook.xml"))
        ct_xml = z.read("[Content_Types].xml")
        rels_xml = z.read("xl/_rels/workbook.xml.rels")
        nombres = z.namelist()

    sd = hoja.find(f"{N}sheetData")
    filas_xml = {int(r.get("r")): r for r in sd.findall(f"{N}row")}
    ultima = max(FILA_FIN_PLANTILLA, FILA_INICIO + len(filas) - 1)

    # Fórmulas de la fila modelo (fila 6, con shared formulas expandidas a texto)
    modelo = filas_xml[FILA_FIN_PLANTILLA]
    formulas_modelo: dict[str, str] = {}
    fila6 = filas_xml[FILA_INICIO]
    for c in fila6.findall(f"{N}c"):
        f = c.find(f"{N}f")
        if f is not None and f.text:
            col, _ = _split_ref(c.get("r"))
            formulas_modelo[col] = f.text

    for r in range(FILA_INICIO, ultima + 1):
        fila = filas_xml.get(r)
        if fila is None or r > FILA_FIN_PLANTILLA:
            # clonar la fila modelo (estilos) y escribir fórmulas explícitas
            nueva = copy.deepcopy(modelo)
            nueva.set("r", str(r))
            for c in nueva.findall(f"{N}c"):
                col, _ = _split_ref(c.get("r"))
                c.set("r", f"{col}{r}")
                for hijo in list(c):
                    c.remove(hijo)
                for a in ("t", "vm"):
                    c.attrib.pop(a, None)
                if col in formulas_modelo:
                    txt = re.sub(r"(?<![A-Z$'!])([A-Z]{1,2})6(?!\d)", rf"\g<1>{r}", formulas_modelo[col])
                    etree.SubElement(c, f"{N}f").text = txt
            if fila is not None:
                sd.replace(fila, nueva)
            else:
                ant = filas_xml.get(r - 1)
                ant.addnext(nueva) if ant is not None else sd.append(nueva)
            filas_xml[r] = fila = nueva

        dato = filas[r - FILA_INICIO] if r - FILA_INICIO < len(filas) else None
        valores: dict[str, object] = {col: None for col in COLS_ENTRADA}
        if dato:
            valores.update({
                "A": dato.elemento, "B": dato.particion, "C": _num_o_texto(dato.piso),
                "D": _num_o_texto(dato.ciclo), "E": dato.cantidad, "F": dato.diametro,
                "G": dato.figura, "I": dato.marca or None,
            })
            for col, lado in zip(COLS_LADOS, dato.lados):
                valores[col] = lado
            for col, ang in zip(COLS_ANG, dato.angulos):
                valores[col] = ang
        for col, val in valores.items():
            _poner_valor(_celda(fila, col, r), val)
        for c in fila.findall(f"{N}c"):
            if c.find(f"{N}f") is not None:
                _limpiar_cache_formula(c)

    # Peso total y rangos de formato condicional si se extendió la tabla
    if ultima > FILA_FIN_PLANTILLA:
        for f in hoja.iter(f"{N}f"):
            if f.text and "AA6:AA105" in f.text:
                f.text = f.text.replace("AA6:AA105", f"AA6:AA{ultima}")
        for el in hoja.iter():
            if el.tag.endswith("sqref") and el.text:
                el.text = re.sub(r"([A-Z]+)6:([A-Z]+)105\b", rf"\g<1>6:\g<2>{ultima}", el.text)
            if el.get("sqref"):
                el.set("sqref", re.sub(r"([A-Z]+)6:([A-Z]+)105\b", rf"\g<1>6:\g<2>{ultima}", el.get("sqref")))
        dim = hoja.find(f"{N}dimension")
        if dim is not None:
            dim.set("ref", f"A1:AJ{max(ultima, 602)}")
    # B2 (nombre sugerido) y B3 (peso total): limpiar caché
    for r in (2, 3):
        for c in filas_xml[r].findall(f"{N}c"):
            if c.find(f"{N}f") is not None:
                _limpiar_cache_formula(c)

    # Forzar recálculo completo al abrir y eliminar calcChain
    calc = wb_xml.find(f"{N}calcPr")
    if calc is None:
        calc = etree.SubElement(wb_xml, f"{N}calcPr")
    calc.set("fullCalcOnLoad", "1")
    ct = re.sub(rb'<Override[^>]*calcChain[^>]*/>', b"", ct_xml)
    rels = re.sub(rb'<Relationship[^>]*calcChain[^>]*/>', b"", rels_xml)

    reemplazos = {
        ruta_hoja: etree.tostring(hoja, xml_declaration=True, encoding="UTF-8", standalone=True),
        "xl/workbook.xml": etree.tostring(wb_xml, xml_declaration=True, encoding="UTF-8", standalone=True),
        "[Content_Types].xml": ct,
        "xl/_rels/workbook.xml.rels": rels,
    }
    tmp = Path(tempfile.mkstemp(suffix=".xlsx")[1])
    with zipfile.ZipFile(plantilla) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            if item.filename == "xl/calcChain.xml":
                continue
            data = reemplazos.get(item.filename, zin.read(item.filename))
            zout.writestr(item, data)
    shutil.move(tmp, salida)
    return salida
