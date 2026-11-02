"""Conexión en vivo con AutoCAD abierto (solo Windows, vía COM/ActiveX).

Lee el dibujo activo (o solo la selección del usuario) sin necesidad de
guardar el archivo. Requiere:  pip install pywin32

Uso:
    python -m cubicador vivo --seleccion -o cubicacion.xlsx
"""
from __future__ import annotations

import math
import time

from .lector_dxf import _UNIDAD_A_CM, _INSUNITS_A_CM, _capa_ok, _encadenar_lineas
from .modelo import Dibujo, Texto, Trazo


def _conectar():
    try:
        import win32com.client  # type: ignore
    except ImportError as e:
        raise RuntimeError("La conexión en vivo requiere Windows y 'pip install pywin32'.") from e
    try:
        acad = win32com.client.GetActiveObject("AutoCAD.Application")
    except Exception as e:  # noqa: BLE001
        raise RuntimeError("No se encontró una sesión de AutoCAD abierta.") from e
    return acad, acad.ActiveDocument


def _reintentar(f, intentos: int = 5):
    """AutoCAD rechaza llamadas COM mientras está ocupado: se reintenta."""
    for i in range(intentos):
        try:
            return f()
        except Exception:  # noqa: BLE001
            if i == intentos - 1:
                raise
            time.sleep(0.3)


def leer_autocad(
    seleccion: bool = False,
    unidad_dibujo: str | None = None,
    capas_fierro: list[str] | None = None,
    capas_texto: list[str] | None = None,
) -> Dibujo:
    acad, doc = _conectar()
    if unidad_dibujo:
        k = _UNIDAD_A_CM[unidad_dibujo]
    else:
        k = _INSUNITS_A_CM.get(int(doc.GetVariable("INSUNITS")), 1.0)

    if seleccion:
        nombre = "CUBICADOR_SEL"
        try:
            doc.SelectionSets.Item(nombre).Delete()
        except Exception:  # noqa: BLE001
            pass
        ss = doc.SelectionSets.Add(nombre)
        doc.Utility.Prompt("\nSeleccione la zona a cubicar y presione Enter...\n")
        ss.SelectOnScreen()
        entidades = [ss.Item(i) for i in range(ss.Count)]
    else:
        ms = doc.ModelSpace
        entidades = [ms.Item(i) for i in range(ms.Count)]

    dibujo = Dibujo(origen=f"AutoCAD: {doc.Name}")
    lineas = []

    def procesar(ent):
        nombre = _reintentar(lambda: ent.ObjectName)
        capa = ent.Layer
        if nombre in ("AcDbText", "AcDbAttribute") and _capa_ok(capa, capas_texto):
            p = ent.InsertionPoint
            dibujo.textos.append(Texto(ent.TextString, (p[0] * k, p[1] * k), capa))
        elif nombre == "AcDbMText" and _capa_ok(capa, capas_texto):
            from ezdxf.tools.text import plain_mtext
            p = ent.InsertionPoint
            dibujo.textos.append(Texto(plain_mtext(ent.TextString), (p[0] * k, p[1] * k), capa))
        elif nombre == "AcDbMLeader" and _capa_ok(capa, capas_texto):
            from ezdxf.tools.text import plain_mtext
            v = ent.GetLeaderLineVertices(0)
            flecha = (v[0] * k, v[1] * k) if v else None
            p = ent.TextLocation if hasattr(ent, "TextLocation") else v
            dibujo.textos.append(Texto(plain_mtext(ent.TextString), (p[0] * k, p[1] * k), capa, flecha))
        elif nombre == "AcDbPolyline" and _capa_ok(capa, capas_fierro):
            c = list(ent.Coordinates)
            pts = [(c[i] * k, c[i + 1] * k) for i in range(0, len(c), 2)]
            if ent.Closed and pts:
                pts.append(pts[0])
            tramos = [math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
            if tramos:
                dibujo.trazos.append(Trazo(tramos, pts, bool(ent.Closed), capa))
        elif nombre == "AcDbLine" and _capa_ok(capa, capas_fierro):
            a, b = ent.StartPoint, ent.EndPoint
            lineas.append(((a[0] * k, a[1] * k), (b[0] * k, b[1] * k), capa))
        elif nombre == "AcDbBlockReference":
            for sub in ent.Explode():   # devuelve copias temporales transformadas
                try:
                    procesar(sub)
                finally:
                    sub.Delete()
            if ent.HasAttributes:
                for att in ent.GetAttributes():
                    procesar(att)

    for ent in entidades:
        try:
            procesar(ent)
        except Exception:  # noqa: BLE001
            continue

    dibujo.trazos.extend(_encadenar_lineas(lineas, tol=0.5))
    return dibujo
