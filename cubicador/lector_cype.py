"""Lector de planos de losas exportados desde CYPECAD.

Dos fuentes, una sola interpretación:
  - archivo DWG  -> `dwgread` de LibreDWG (JSON)          -> entidades_desde_json()
  - AutoCAD abierto (Windows, COM)                        -> autocad_vivo.entidades_desde_autocad()
Ambas producen una lista de `Entidad` (formato neutro) que interpreta parsear_entidades().

Estructura CYPE:
  Bloque de etiqueta (capa TEXTO) con atributos:
      CUANTIA  "Ø8a18s", "F'=Ø10a30", "F=F'=2Ø16", "F'=3Ø12"
      LARGO    "L=160"
      A..E     lados de la barra en cm (malla/suples)
      PARCIAL  "(20+150)" tramos (refuerzos)
  Datos extendidos SCAD_LOSAS que enlazan la etiqueta con:
      LWPOLYLINE capa BARRAS   (dibujo de la barra)
      DIMENSION  capa RANGOS   (ancho de distribución)
  Losas: bloque _LOSA con atributos NUMERO y E (espesor); contorno en capa temp_contornos.
  Ciclos: polilíneas cerradas + texto "C1", "C2"... en una capa con "CICLO" en el nombre.
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


# ---------------------------------------------------------------------------
# Modelo
# ---------------------------------------------------------------------------

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
class Cuadrante:
    numero: int
    nombre: str
    poligono: list[Punto]


@dataclass
class PlanoCype:
    etiquetas: list[EtiquetaCype]
    losas: list[Losa]
    rangos: list[tuple[float, tuple[Punto, Punto]]]   # (medida, segmento) de todas las cotas RANGOS
    titulo: str = ""
    barras: list[Trazo] = field(default_factory=list)                # todas las polilíneas BARRAS
    ciclos: list[Cuadrante] = field(default_factory=list)            # cuadrantes de ciclo
    muros: list[tuple[Punto, Punto]] = field(default_factory=list)   # líneas capa MUROS
    vigas: list[tuple[Punto, Punto]] = field(default_factory=list)   # líneas capa VIGAS


@dataclass
class Atributo:
    tag: str
    texto: str
    rotacion: float = 0.0


@dataclass
class Entidad:
    """Entidad del espacio modelo en formato neutro (independiente de la fuente)."""
    tipo: str                      # INSERT, LWPOLYLINE, LINE, DIMENSION, TEXT, MTEXT
    handle: int
    capa: str
    bloque: str = ""               # INSERT: nombre (efectivo) del bloque
    atributos: list[Atributo] = field(default_factory=list)
    enlaces: list[int] = field(default_factory=list)   # handles en datos extendidos (1005)
    puntos: list[Punto] = field(default_factory=list)  # LWPOLYLINE
    cerrado: bool = False
    punto: Punto | None = None     # INSERT/TEXT: punto de inserción
    inicio: Punto | None = None    # LINE
    fin: Punto | None = None
    medida: float | None = None    # DIMENSION
    segmento: tuple[Punto, Punto] | None = None   # DIMENSION: puntos de origen de líneas de extensión
    texto: str = ""                # TEXT / MTEXT


# ---------------------------------------------------------------------------
# Fuente: archivo DWG (LibreDWG)
# ---------------------------------------------------------------------------

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


def entidades_desde_json(d: dict) -> list[Entidad]:
    objs = d["OBJECTS"]
    por_h = {o["handle"][-1]: o for o in objs if "handle" in o}
    capas = {o["handle"][-1]: o.get("name") or "" for o in objs if o.get("object") == "LAYER"}
    bloques = {o["handle"][-1]: o.get("name") or "" for o in objs if o.get("object") == "BLOCK_HEADER"}
    modelo: set[int] = set()
    for o in objs:
        if o.get("object") == "BLOCK_HEADER" and (o.get("name") or "").upper() == "*MODEL_SPACE":
            modelo |= {_h(r) for r in o.get("entities", []) if isinstance(r, list)}

    res: list[Entidad] = []
    for o in objs:
        tipo = o.get("entity") or ""
        h = o.get("handle", [None])[-1]
        if not tipo or (modelo and h not in modelo):
            continue
        e = Entidad(tipo="DIMENSION" if tipo.startswith("DIMENSION") else tipo, handle=h,
                    capa=capas.get(_h(o.get("layer")), ""))
        if tipo == "INSERT":
            e.bloque = bloques.get(_h(o.get("block_header")), "")
            e.punto = _pt(o["ins_pt"])
            for a in o.get("attribs") or []:
                at = por_h.get(_h(a))
                if at and at.get("tag"):
                    e.atributos.append(Atributo(at["tag"].upper(), _texto(at.get("text_value")),
                                                float(at.get("rotation") or 0.0)))
            for x in o.get("eed", []):
                v = x.get("value")
                if isinstance(v, list) and len(v) == 3:
                    e.enlaces.append(v[-1])
        elif tipo == "LWPOLYLINE":
            e.puntos = [_pt(p) for p in o.get("points", [])]
            e.cerrado = bool(o.get("flag", 0) & 512) or bool(o.get("flag", 0) & 1)
        elif tipo == "LINE":
            e.inicio, e.fin = _pt(o["start"]), _pt(o["end"])
        elif e.tipo == "DIMENSION":
            e.medida = float(o.get("act_measurement") or 0) or None
            if o.get("xline1_pt") and o.get("xline2_pt"):
                e.segmento = (_pt(o["xline1_pt"]), _pt(o["xline2_pt"]))
        elif tipo in ("TEXT", "MTEXT"):
            e.texto = _texto(o.get("text_value"))
            if o.get("ins_pt"):
                e.punto = _pt(o["ins_pt"])
        else:
            continue
        res.append(e)
    return res


def leer_plano_cype(ruta: str | Path) -> PlanoCype:
    return parsear_entidades(entidades_desde_json(dwg_a_json(ruta)))


# ---------------------------------------------------------------------------
# Interpretación (común a todas las fuentes)
# ---------------------------------------------------------------------------

def _trazo(puntos: list[Punto], cerrado: bool) -> Trazo | None:
    pts = list(puntos)
    if len(pts) < 2:
        return None
    if cerrado:
        pts.append(pts[0])
    tramos = [math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    keep = [i for i, t in enumerate(tramos) if t > 1e-6]
    if not keep:
        return None
    pts = [pts[0]] + [pts[i + 1] for i in keep]
    return Trazo([tramos[i] for i in keep], pts, cerrado, "BARRAS")


def _enteros(valores: list[str]) -> list[int]:
    return [int(round(float(x.replace(",", ".")))) for x in valores]


def parsear_entidades(ents: list[Entidad]) -> PlanoCype:
    por_h = {e.handle: e for e in ents}
    etiquetas: list[EtiquetaCype] = []
    losas: list[Losa] = []
    titulo = ""
    rangos, contornos, barras, muros, vigas = [], [], [], [], []
    pol_ciclo: list[list[Punto]] = []
    txt_ciclo: list[tuple[str, Punto]] = []

    for e in ents:
        cp = (e.capa or "").upper()
        es_ciclo = "CICLO" in cp

        if e.tipo == "INSERT":
            atts: dict[str, str] = {}
            rot_cuantia = 0.0
            for a in e.atributos:
                atts.setdefault(a.tag, a.texto)
                if a.tag == "CUANTIA":
                    rot_cuantia = a.rotacion
            if es_ciclo:
                txt_ciclo += [(a.texto, e.punto) for a in e.atributos if a.texto]
            if "TITULO" in atts and not titulo:
                titulo = atts["TITULO"]
            if e.bloque.upper() == "_LOSA" or ("NUMERO" in atts and "E" in atts and "CUANTIA" not in atts):
                losas.append(Losa(atts.get("NUMERO", ""), atts.get("E", ""), e.punto))
                continue
            if "CUANTIA" not in atts:
                continue
            et = EtiquetaCype(cuantia=atts["CUANTIA"], largo=atts.get("LARGO", ""),
                              punto=e.punto, handle=e.handle, rotacion=rot_cuantia)
            lados = [atts[k] for k in "ABCDEFGHIJ" if atts.get(k)]
            if lados and all(re.fullmatch(r"\d+(?:[.,]\d+)?", x) for x in lados):
                et.lados = _enteros(lados)
            elif atts.get("PARCIAL"):
                et.lados = _enteros(re.findall(r"\d+(?:[.,]\d+)?", atts["PARCIAL"]))
            for h in e.enlaces:
                t = por_h.get(h)
                if not t:
                    continue
                tcp = t.capa.upper()
                if t.tipo == "LWPOLYLINE" and tcp == "BARRAS" and et.trazo is None:
                    et.trazo = _trazo(t.puntos, t.cerrado)
                elif t.tipo == "DIMENSION" and tcp == "RANGOS" and et.rango_cm is None:
                    et.rango_cm = t.medida
                    et.rango_seg = t.segmento
            etiquetas.append(et)

        elif e.tipo == "LWPOLYLINE":
            if es_ciclo and len(e.puntos) >= 3:
                pol_ciclo.append(e.puntos)
            if cp == "BARRAS":
                tr = _trazo(e.puntos, e.cerrado)
                if tr:
                    barras.append(tr)
            elif cp == "TEMP_CONTORNOS":
                contornos.append(e.puntos)
            elif cp in ("MUROS", "VIGAS"):
                (muros if cp == "MUROS" else vigas).extend(zip(e.puntos, e.puntos[1:]))

        elif e.tipo == "LINE" and cp in ("MUROS", "VIGAS"):
            (muros if cp == "MUROS" else vigas).append((e.inicio, e.fin))

        elif e.tipo == "DIMENSION" and cp == "RANGOS" and e.medida and e.segmento:
            rangos.append((e.medida, e.segmento))

        elif e.tipo in ("TEXT", "MTEXT") and es_ciclo and e.punto:
            txt_ciclo.append((e.texto, e.punto))

    for losa in losas:
        for c in contornos:
            if _dentro(losa.punto, c):
                losa.contorno = c
                break
    return PlanoCype(etiquetas, losas, rangos, titulo, barras,
                     armar_cuadrantes(pol_ciclo, txt_ciclo), muros, vigas)


# ---------------------------------------------------------------------------
# Ciclos y utilidades geométricas
# ---------------------------------------------------------------------------

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
