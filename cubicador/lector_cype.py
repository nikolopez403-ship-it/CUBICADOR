"""Lector de planos de losas exportados desde CYPECAD (DWG).

Usa `dwgread` de LibreDWG para volcar el DWG a JSON (más robusto que dwg2dxf
para estos archivos) y extrae las etiquetas de armadura de CYPE:

  Bloque de etiqueta (capa TEXTO) con atributos:
      CUANTIA  "Ø8a18s", "F'=Ø10a30", "F=F'=2Ø16", "F'=3Ø12"
      LARGO    "L=160"
      A..E     lados de la barra en cm (malla/suples)
      PARCIAL  "(20+150)" tramos (refuerzos)
  Datos extendidos SCAD_LOSAS que enlazan la etiqueta con:
      LWPOLYLINE capa BARRAS   (dibujo de la barra)
      DIMENSION  capa RANGOS   (ancho de distribución)

  Losas: bloque _LOSA con atributos NUMERO y E (espesor).
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .modelo import Punto, Trazo


@dataclass
class EtiquetaCype:
    cuantia: str
    largo: str = ""
    lados: list[int] = field(default_factory=list)   # A..E o PARCIAL
    punto: Punto = (0.0, 0.0)
    trazo: Trazo | None = None
    rango_cm: float | None = None
    rango_seg: tuple[Punto, Punto] | None = None
    rotacion: float = 0.0          # radianes, del texto CUANTIA (dirección de la barra)
    handle: int = 0


@dataclass
class Losa:
    numero: str
    espesor: str
    punto: Punto
    contorno: list[Punto] | None = None


@dataclass
class PlanoCype:
    etiquetas: list[EtiquetaCype]
    losas: list[Losa]
    rangos: list[tuple[float, tuple[Punto, Punto]]]   # (medida, segmento) de todas las cotas RANGOS
    titulo: str = ""
    barras: list[Trazo] = field(default_factory=list)          # todas las polilíneas BARRAS
    muros: list[tuple[Punto, Punto]] = field(default_factory=list)   # líneas capa MUROS
    vigas: list[tuple[Punto, Punto]] = field(default_factory=list)   # líneas capa VIGAS
    ciclos: list["Cuadrante"] = field(default_factory=list)   # cuadrantes dibujados en capa *CICLO*


@dataclass
class Cuadrante:
    numero: int
    nombre: str
    poligono: list[Punto]


def _buscar_dwgread() -> str:
    for cand in (os.environ.get("DWGREAD"), shutil.which("dwgread"),
                 "/opt/libredwg/bin/dwgread"):
        if cand and Path(cand).exists():
            return cand
    raise RuntimeError("No se encontró 'dwgread' (LibreDWG). Defina la variable DWGREAD con su ruta.")


def dwg_a_json(ruta: str | Path) -> dict:
    exe = _buscar_dwgread()
    with tempfile.TemporaryDirectory() as tmp:
        salida = Path(tmp) / "plano.json"
        env = dict(os.environ)
        lib = Path(exe).resolve().parent.parent / "lib"
        if lib.exists():
            env["LD_LIBRARY_PATH"] = f"{lib}:{env.get('LD_LIBRARY_PATH', '')}"
        subprocess.run([exe, "-O", "JSON", "-o", str(salida), str(ruta)],
                       check=False, capture_output=True, env=env)
        if not salida.exists() or salida.stat().st_size == 0:
            raise RuntimeError(f"dwgread no pudo leer {ruta}")
        # LibreDWG escribe textos en la codificación del dibujo (no siempre UTF-8)
        return json.loads(salida.read_text(encoding="latin-1"), strict=False)


def _h(ref) -> int | None:
    return ref[-1] if isinstance(ref, list) and ref else None


def _pt(p) -> Punto:
    return (float(p[0]), float(p[1]))


def _texto(s: str | None) -> str:
    if not s:
        return ""
    try:  # reparar textos UTF-8 leídos como latin-1
        s = s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return s.strip()


def _trazo_lw(o: dict) -> Trazo | None:
    pts = [_pt(p) for p in o.get("points", [])]
    if len(pts) < 2:
        return None
    cerrado = bool(o.get("flag", 0) & 512) or bool(o.get("flag", 0) & 1)
    if cerrado:
        pts.append(pts[0])
    tramos = [math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    keep = [i for i, t in enumerate(tramos) if t > 1e-6]
    pts = [pts[0]] + [pts[i + 1] for i in keep]
    return Trazo([tramos[i] for i in keep], pts, cerrado, "BARRAS")


def _segmento_cota(o: dict) -> tuple[Punto, Punto] | None:
    p1, p2 = o.get("xline1_pt"), o.get("xline2_pt")
    if p1 and p2:
        return _pt(p1), _pt(p2)
    return None


def leer_plano_cype(ruta: str | Path) -> PlanoCype:
    d = dwg_a_json(ruta)
    objs = d["OBJECTS"]
    por_h = {o["handle"][-1]: o for o in objs if "handle" in o}
    capas = {o["handle"][-1]: o.get("name") for o in objs if o.get("object") == "LAYER"}
    bloques = {o["handle"][-1]: o.get("name") for o in objs if o.get("object") == "BLOCK_HEADER"}
    ents_modelo: set[int] = set()
    for o in objs:
        if o.get("object") == "BLOCK_HEADER" and (o.get("name") or "").upper() == "*MODEL_SPACE":
            ents_modelo |= {_h(r) for r in o.get("entities", []) if isinstance(r, list)}

    def capa(o):
        return capas.get(_h(o.get("layer")), "")

    def en_modelo(o):
        return not ents_modelo or o.get("handle", [None])[-1] in ents_modelo

    etiquetas: list[EtiquetaCype] = []
    losas: list[Losa] = []
    titulo = ""
    for o in objs:
        if o.get("entity") != "INSERT" or not o.get("attribs") or not en_modelo(o):
            continue
        atts = {}
        for a in o["attribs"]:
            at = por_h.get(_h(a))
            if at and at.get("tag"):
                atts.setdefault(at["tag"].upper(), _texto(at.get("text_value")))
        nombre_blq = bloques.get(_h(o.get("block_header")), "") or ""
        if "TITULO" in atts and not titulo:
            titulo = atts["TITULO"]
        if nombre_blq.upper() == "_LOSA" or ("NUMERO" in atts and "E" in atts and "CUANTIA" not in atts):
            losas.append(Losa(atts.get("NUMERO", ""), atts.get("E", ""), _pt(o["ins_pt"])))
            continue
        if "CUANTIA" not in atts:
            continue
        et = EtiquetaCype(cuantia=atts["CUANTIA"], largo=atts.get("LARGO", ""),
                          punto=_pt(o["ins_pt"]), handle=o["handle"][-1])
        for a in o["attribs"]:
            at = por_h.get(_h(a))
            if at and (at.get("tag") or "").upper() == "CUANTIA":
                et.rotacion = float(at.get("rotation") or 0.0)
        lados = [atts[k] for k in "ABCDEFGHIJ" if atts.get(k)]
        if lados and all(re.fullmatch(r"\d+(?:[.,]\d+)?", x) for x in lados):
            et.lados = [int(round(float(x.replace(",", ".")))) for x in lados]
        elif atts.get("PARCIAL"):
            nums = re.findall(r"\d+(?:[.,]\d+)?", atts["PARCIAL"])
            et.lados = [int(round(float(x.replace(",", ".")))) for x in nums]
        for e in o.get("eed", []):
            v = e.get("value")
            if not (isinstance(v, list) and len(v) == 3):
                continue
            t = por_h.get(v[-1])
            if not t:
                continue
            tipo, cp = t.get("entity", ""), capa(t)
            if tipo == "LWPOLYLINE" and cp.upper() == "BARRAS" and et.trazo is None:
                et.trazo = _trazo_lw(t)
            elif tipo.startswith("DIMENSION") and cp.upper() == "RANGOS" and et.rango_cm is None:
                et.rango_cm = float(t.get("act_measurement") or 0) or None
                et.rango_seg = _segmento_cota(t)
        etiquetas.append(et)

    rangos = []
    contornos = []
    barras: list[Trazo] = []
    muros: list[tuple[Punto, Punto]] = []
    vigas: list[tuple[Punto, Punto]] = []
    pol_ciclo: list[list[Punto]] = []
    txt_ciclo: list[tuple[str, Punto]] = []
    for o in objs:
        if not en_modelo(o):
            continue
        cp = capa(o) or ""
        if "CICLO" in cp.upper():
            if o.get("entity") == "LWPOLYLINE" and len(o.get("points", [])) >= 3:
                pol_ciclo.append([_pt(p) for p in o["points"]])
            elif o.get("entity") in ("TEXT", "MTEXT") and o.get("ins_pt"):
                txt_ciclo.append((_texto(o.get("text_value")), _pt(o["ins_pt"])))
            elif o.get("entity") == "INSERT" and o.get("attribs"):
                for a in o["attribs"]:
                    at = por_h.get(_h(a))
                    if at and at.get("text_value"):
                        txt_ciclo.append((_texto(at["text_value"]), _pt(o["ins_pt"])))
        if cp.upper() in ("MUROS", "VIGAS"):
            destino = muros if cp.upper() == "MUROS" else vigas
            if o.get("entity") == "LINE":
                destino.append((_pt(o["start"]), _pt(o["end"])))
            elif o.get("entity") == "LWPOLYLINE":
                pts = [_pt(q) for q in o.get("points", [])]
                destino.extend(zip(pts, pts[1:]))
        if o.get("entity") == "LWPOLYLINE" and cp.upper() == "BARRAS":
            tr = _trazo_lw(o)
            if tr:
                barras.append(tr)
        if o.get("entity", "").startswith("DIMENSION") and capa(o).upper() == "RANGOS":
            seg = _segmento_cota(o)
            if seg and o.get("act_measurement"):
                rangos.append((float(o["act_measurement"]), seg))
        elif o.get("entity") == "LWPOLYLINE" and capa(o).lower() == "temp_contornos":
            contornos.append([_pt(p) for p in o.get("points", [])])

    for losa in losas:
        for c in contornos:
            if _dentro(losa.punto, c):
                losa.contorno = c
                break
    plano = PlanoCype(etiquetas, losas, rangos, titulo, barras, armar_cuadrantes(pol_ciclo, txt_ciclo))
    plano.muros, plano.vigas = muros, vigas
    return plano


def armar_cuadrantes(poligonos: list[list[Punto]], textos: list[tuple[str, Punto]]) -> list[Cuadrante]:
    """Une cada polígono de ciclo con el texto (C1, CICLO 2, 3...) que está dentro."""
    res = []
    for pol in poligonos:
        for txt, pt in textos:
            m = re.search(r"(\d+)", txt or "")
            if m and _dentro(pt, pol):
                res.append(Cuadrante(int(m.group(1)), txt.strip(), pol))
                break
    return sorted(res, key=lambda c: c.numero)


def leer_cuadrantes(ruta: str | Path) -> list[Cuadrante]:
    """Cuadrantes desde un archivo aparte (DXF o DWG): polilíneas cerradas + texto en capa *CICLO*."""
    ruta = Path(ruta)
    if ruta.suffix.lower() == ".dwg":
        return leer_plano_cype(ruta).ciclos
    import ezdxf
    from ezdxf import recover
    doc, _ = recover.readfile(str(ruta))
    pols, txts = [], []
    for e in doc.modelspace():
        if "CICLO" not in e.dxf.get("layer", "").upper():
            continue
        if e.dxftype() == "LWPOLYLINE":
            pols.append([(p[0], p[1]) for p in e.get_points()])
        elif e.dxftype() == "TEXT":
            txts.append((e.dxf.text, (e.dxf.insert.x, e.dxf.insert.y)))
        elif e.dxftype() == "MTEXT":
            txts.append((e.plain_text(), (e.dxf.insert.x, e.dxf.insert.y)))
    return armar_cuadrantes(pols, txts)


def _dentro(p: Punto, poli: list[Punto]) -> bool:
    x, y = p
    dentro = False
    n = len(poli)
    for i in range(n):
        x1, y1 = poli[i]
        x2, y2 = poli[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            dentro = not dentro
    return dentro


def losa_de(p: Punto, losas: list[Losa]) -> Losa | None:
    for l in losas:
        if l.contorno and _dentro(p, l.contorno):
            return l
    return min(losas, key=lambda l: math.dist(p, l.punto)) if losas else None
