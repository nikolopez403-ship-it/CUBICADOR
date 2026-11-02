"""Conexión en vivo con AutoCAD (Windows, COM/ActiveX).  Requiere: pip install pywin32

- conectar():                  sesión de AutoCAD abierta.
- entidades_desde_autocad():  lee el espacio modelo de un dibujo abierto al formato
                               neutro `Entidad` (mismo que el lector de archivos DWG).
- leer_autocad():              lector genérico (planos no CYPE) usado por `cubicador vivo`.
"""
from __future__ import annotations

import math
import time

from .lector_cype import Atributo, Entidad
from .modelo import Dibujo, Texto, Trazo

CAPAS_UTILES = {"BARRAS", "RANGOS", "MUROS", "VIGAS", "TEMP_CONTORNOS"}


def conectar():
    try:
        import win32com.client  # type: ignore
    except ImportError as e:
        raise RuntimeError("La conexión con AutoCAD requiere Windows y 'pip install pywin32'.") from e
    try:
        acad = win32com.client.GetActiveObject("AutoCAD.Application")
    except Exception as e:  # noqa: BLE001
        raise RuntimeError("No se encontró una sesión de AutoCAD abierta.") from e
    return acad, acad.ActiveDocument


def reintentar(f, intentos: int = 8):
    """AutoCAD rechaza llamadas COM mientras está ocupado ("Call was rejected by callee")."""
    for i in range(intentos):
        try:
            return f()
        except Exception as e:  # noqa: BLE001
            if i == intentos - 1 or "rejected" not in str(e).lower() and "-2147418111" not in str(e):
                raise
            time.sleep(0.25 * (i + 1))


def _p2(p) -> tuple[float, float]:
    return (float(p[0]), float(p[1]))


def _xdata_handles(ent, app: str = "SCAD_LOSAS") -> list[int]:
    """Handles (código 1005) de los datos extendidos de una entidad."""
    try:
        tipos, valores = ent.GetXData(app)
    except Exception:  # noqa: BLE001  (algunas versiones de pywin32 exigen VARIANT por referencia)
        try:
            import pythoncom  # type: ignore
            import win32com.client  # type: ignore
            t = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_VARIANT, None)
            v = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_VARIANT, None)
            ent.GetXData(app, t, v)
            tipos, valores = t.value, v.value
        except Exception:  # noqa: BLE001
            return []
    res = []
    for tp, val in zip(tipos or (), valores or ()):
        if int(tp) == 1005:
            try:
                res.append(int(str(val), 16))
            except ValueError:
                pass
    return res


def _segmento_dim(ent, medida: float):
    for a, b in (("ExtLine1Point", "ExtLine2Point"),):
        try:
            return _p2(getattr(ent, a)), _p2(getattr(ent, b))
        except Exception:  # noqa: BLE001
            pass
    # Cota girada: COM no expone sus puntos de definición; se reconstruye sobre la línea de cota
    try:
        c = _p2(ent.TextPosition)
        ang = float(ent.Rotation)
        u = (math.cos(ang), math.sin(ang))
        m = medida / 2
        return (c[0] - u[0] * m, c[1] - u[1] * m), (c[0] + u[0] * m, c[1] + u[1] * m)
    except Exception:  # noqa: BLE001
        return None


def entidad_desde_com(ent) -> Entidad | None:
    nombre = reintentar(lambda: ent.ObjectName)
    capa = ent.Layer or ""
    cp = capa.upper()
    ciclo = "CICLO" in cp
    h = int(ent.Handle, 16)

    if nombre == "AcDbBlockReference":
        try:
            bloque = ent.EffectiveName
        except Exception:  # noqa: BLE001
            bloque = ent.Name
        e = Entidad("INSERT", h, capa, bloque=bloque or "", punto=_p2(ent.InsertionPoint))
        if ent.HasAttributes:
            for a in ent.GetAttributes():
                e.atributos.append(Atributo((a.TagString or "").upper(), (a.TextString or "").strip(),
                                            float(a.Rotation or 0.0)))
        e.enlaces = _xdata_handles(ent) if any(a.tag == "CUANTIA" for a in e.atributos) else []
        return e
    if nombre == "AcDbPolyline" and (cp in CAPAS_UTILES or ciclo):
        c = list(ent.Coordinates)
        return Entidad("LWPOLYLINE", h, capa, puntos=[(c[i], c[i + 1]) for i in range(0, len(c) - 1, 2)],
                       cerrado=bool(ent.Closed))
    if nombre == "AcDbLine" and cp in ("MUROS", "VIGAS"):
        return Entidad("LINE", h, capa, inicio=_p2(ent.StartPoint), fin=_p2(ent.EndPoint))
    if "Dimension" in nombre and cp == "RANGOS":
        medida = float(ent.Measurement)
        return Entidad("DIMENSION", h, capa, medida=medida, segmento=_segmento_dim(ent, medida))
    if nombre in ("AcDbText", "AcDbMText") and ciclo:
        return Entidad("TEXT", h, capa, texto=(ent.TextString or "").strip(), punto=_p2(ent.InsertionPoint))
    return None


def entidades_desde_autocad(doc, progreso=None) -> list[Entidad]:
    ms = doc.ModelSpace
    total = reintentar(lambda: ms.Count)
    res: list[Entidad] = []
    for i in range(total):
        try:
            ent = reintentar(lambda: ms.Item(i))
            e = entidad_desde_com(ent)
        except Exception:  # noqa: BLE001  entidad dañada o proxy: se omite
            continue
        if e:
            res.append(e)
        if progreso and i % 250 == 0:
            progreso(i, total)
    return res


# ---------------------------------------------------------------------------
# Lector genérico (planos no CYPE) para `cubicador vivo`
# ---------------------------------------------------------------------------

def leer_autocad(seleccion: bool = False, unidad_dibujo: str | None = None,
                 capas_fierro: list[str] | None = None, capas_texto: list[str] | None = None) -> Dibujo:
    from .lector_dxf import _INSUNITS_A_CM, _UNIDAD_A_CM, _capa_ok, _encadenar_lineas
    from ezdxf.tools.text import plain_mtext

    _, doc = conectar()
    k = _UNIDAD_A_CM[unidad_dibujo] if unidad_dibujo else _INSUNITS_A_CM.get(int(doc.GetVariable("INSUNITS")), 1.0)
    if seleccion:
        try:
            doc.SelectionSets.Item("CUBICADOR_SEL").Delete()
        except Exception:  # noqa: BLE001
            pass
        ss = doc.SelectionSets.Add("CUBICADOR_SEL")
        doc.Utility.Prompt("\nSeleccione la zona a cubicar y presione Enter...\n")
        ss.SelectOnScreen()
        entidades = [ss.Item(i) for i in range(ss.Count)]
    else:
        ms = doc.ModelSpace
        entidades = [ms.Item(i) for i in range(ms.Count)]

    dibujo = Dibujo(origen=f"AutoCAD: {doc.Name}")
    lineas = []
    for ent in entidades:
        try:
            nombre, capa = reintentar(lambda: ent.ObjectName), ent.Layer
            if nombre in ("AcDbText", "AcDbAttribute") and _capa_ok(capa, capas_texto):
                p = ent.InsertionPoint
                dibujo.textos.append(Texto(ent.TextString, (p[0] * k, p[1] * k), capa))
            elif nombre == "AcDbMText" and _capa_ok(capa, capas_texto):
                p = ent.InsertionPoint
                dibujo.textos.append(Texto(plain_mtext(ent.TextString), (p[0] * k, p[1] * k), capa))
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
            elif nombre == "AcDbBlockReference" and ent.HasAttributes:
                for att in ent.GetAttributes():
                    p = att.InsertionPoint
                    dibujo.textos.append(Texto(att.TextString, (p[0] * k, p[1] * k), capa))
        except Exception:  # noqa: BLE001
            continue
    dibujo.trazos.extend(_encadenar_lineas(lineas, tol=0.5))
    return dibujo
