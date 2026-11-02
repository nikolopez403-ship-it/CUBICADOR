"""Lectura de planos DXF/DWG con ezdxf hacia el modelo intermedio.

- Explora el espacio modelo, incluyendo el contenido de bloques (INSERT),
  con las coordenadas ya transformadas.
- Los DWG se convierten a DXF usando ODA File Converter (gratuito), que debe
  estar instalado: https://www.opendesign.com/guestfiles/oda_file_converter
"""
from __future__ import annotations

import fnmatch
import math
from pathlib import Path

import ezdxf
from ezdxf import disassemble

from .modelo import Dibujo, Punto, Texto, Trazo

# Factor de unidades de dibujo -> cm según $INSUNITS
_INSUNITS_A_CM = {1: 2.54, 4: 0.1, 5: 1.0, 6: 100.0, 2: 30.48}
_UNIDAD_A_CM = {"mm": 0.1, "cm": 1.0, "m": 100.0}


def abrir_documento(ruta: str | Path):
    ruta = Path(ruta)
    if ruta.suffix.lower() == ".dwg":
        from ezdxf.addons import odafc
        if not odafc.is_installed():
            raise RuntimeError(
                "Para leer DWG se necesita ODA File Converter instalado "
                "(o guarde el plano como DXF desde AutoCAD: comando DXFOUT)."
            )
        return odafc.readfile(str(ruta))
    return ezdxf.readfile(str(ruta))


def factor_unidades(doc, unidad: str | None) -> float:
    if unidad:
        return _UNIDAD_A_CM[unidad]
    return _INSUNITS_A_CM.get(doc.header.get("$INSUNITS", 0), 1.0)


def _capa_ok(capa: str, filtros: list[str] | None) -> bool:
    if not filtros:
        return True
    return any(fnmatch.fnmatch(capa.upper(), f.upper()) for f in filtros)


def _trazo_desde_polilinea(entidad, k: float) -> Trazo | None:
    tramos: list[float] = []
    vertices: list[Punto] = []
    largo_arcos = 0.0
    for sub in entidad.virtual_entities():
        t = sub.dxftype()
        if t == "LINE":
            a, b = sub.dxf.start, sub.dxf.end
            lg = math.dist((a.x, a.y), (b.x, b.y)) * k
            if lg > 1e-6:
                tramos.append(lg)
                if not vertices:
                    vertices.append((a.x * k, a.y * k))
                vertices.append((b.x * k, b.y * k))
        elif t == "ARC":
            ang = math.radians((sub.dxf.end_angle - sub.dxf.start_angle) % 360)
            largo_arcos += sub.dxf.radius * ang * k
    if not tramos:
        return None
    return Trazo(
        tramos=tramos,
        vertices=vertices,
        cerrado=bool(entidad.is_closed),
        capa=entidad.dxf.layer,
        largo_arcos=largo_arcos,
    )


def _encadenar_lineas(lineas: list[tuple[Punto, Punto, str]], tol: float) -> list[Trazo]:
    """Une LINEs sueltas que comparten extremos en cadenas (barras dibujadas con líneas)."""
    pendientes = list(lineas)
    trazos: list[Trazo] = []
    while pendientes:
        a, b, capa = pendientes.pop()
        cadena = [a, b]
        cambio = True
        while cambio:
            cambio = False
            for i, (p, q, c) in enumerate(pendientes):
                if c != capa:
                    continue
                if math.dist(cadena[-1], p) <= tol:
                    cadena.append(q)
                elif math.dist(cadena[-1], q) <= tol:
                    cadena.append(p)
                elif math.dist(cadena[0], q) <= tol:
                    cadena.insert(0, p)
                elif math.dist(cadena[0], p) <= tol:
                    cadena.insert(0, q)
                else:
                    continue
                pendientes.pop(i)
                cambio = True
                break
        cerrado = len(cadena) > 3 and math.dist(cadena[0], cadena[-1]) <= tol
        if cerrado:
            cadena = cadena[:-1] + [cadena[0]]
        tramos = [math.dist(cadena[i], cadena[i + 1]) for i in range(len(cadena) - 1)]
        trazos.append(Trazo(tramos=tramos, vertices=cadena, cerrado=cerrado, capa=capa))
    return trazos


def leer_dxf(
    ruta: str | Path,
    unidad_dibujo: str | None = None,
    capas_fierro: list[str] | None = None,
    capas_texto: list[str] | None = None,
) -> Dibujo:
    """Lee un DXF/DWG y devuelve textos y trazos en cm.

    capas_fierro: patrones (comodines) de capas donde se dibujan las barras,
                  p.ej. ["*FIERRO*", "ARM*"]. None = todas.
    capas_texto:  patrones de capas de textos de armadura. None = todas.
    """
    doc = abrir_documento(ruta)
    k = factor_unidades(doc, unidad_dibujo)
    msp = doc.modelspace()
    dibujo = Dibujo(origen=str(ruta))
    lineas: list[tuple[Punto, Punto, str]] = []

    for e in disassemble.recursive_decompose(msp):
        t = e.dxftype()
        capa = e.dxf.get("layer", "0")
        try:
            if t in ("TEXT", "ATTRIB") and _capa_ok(capa, capas_texto):
                p = e.dxf.insert
                dibujo.textos.append(Texto(e.dxf.text, (p.x * k, p.y * k), capa))
            elif t == "MTEXT" and _capa_ok(capa, capas_texto):
                p = e.dxf.insert
                dibujo.textos.append(Texto(e.plain_text(), (p.x * k, p.y * k), capa))
            elif t in ("MULTILEADER", "MLEADER") and _capa_ok(capa, capas_texto):
                ctx = e.context
                if ctx.mtext is None:
                    continue
                from ezdxf.tools.text import plain_mtext
                txt = plain_mtext(ctx.mtext.default_content)
                ins = ctx.mtext.insert
                flecha = None
                for leader in ctx.leaders:
                    for linea in leader.lines:
                        if linea.vertices:
                            v = linea.vertices[0]
                            flecha = (v.x * k, v.y * k)
                            break
                    if flecha:
                        break
                dibujo.textos.append(Texto(txt, (ins.x * k, ins.y * k), capa, flecha))
            elif t in ("LWPOLYLINE", "POLYLINE") and _capa_ok(capa, capas_fierro):
                tr = _trazo_desde_polilinea(e, k)
                if tr:
                    dibujo.trazos.append(tr)
            elif t == "LINE" and _capa_ok(capa, capas_fierro):
                a, b = e.dxf.start, e.dxf.end
                lineas.append(((a.x * k, a.y * k), (b.x * k, b.y * k), capa))
        except (AttributeError, ezdxf.DXFError):
            continue  # entidad dañada o incompleta: se omite

    dibujo.trazos.extend(_encadenar_lineas(lineas, tol=0.5))
    return dibujo
