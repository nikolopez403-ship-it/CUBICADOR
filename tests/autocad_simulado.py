"""AutoCAD simulado (modelo de objetos COM mínimo) para probar el asistente sin Windows."""
from __future__ import annotations

import math


class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)
        self.borrado = False

    def Delete(self):
        self.borrado = True


class Atributo(_Obj):
    pass


class Entidad(_Obj):
    def GetAttributes(self):
        return tuple(self.atributos)

    def GetXData(self, app):
        if app != "SCAD_LOSAS" or not self.enlaces:
            return (), ()
        return (1001,) + (1005,) * len(self.enlaces), ("SCAD_LOSAS",) + tuple(format(h, "X") for h in self.enlaces)


def com_desde_entidad(e) -> Entidad:
    """Convierte una Entidad neutra (de un DWG real) en el objeto que expondría AutoCAD por COM."""
    base = dict(Layer=e.capa, Handle=format(e.handle, "X"))
    p3 = lambda p: (p[0], p[1], 0.0)
    if e.tipo == "INSERT":
        return Entidad(ObjectName="AcDbBlockReference", EffectiveName=e.bloque, Name=e.bloque,
                       InsertionPoint=p3(e.punto), HasAttributes=bool(e.atributos),
                       atributos=[Atributo(TagString=a.tag, TextString=a.texto, Rotation=a.rotacion)
                                  for a in e.atributos], enlaces=e.enlaces, **base)
    if e.tipo == "LWPOLYLINE":
        return Entidad(ObjectName="AcDbPolyline", Coordinates=tuple(v for p in e.puntos for v in p),
                       Closed=e.cerrado, **base)
    if e.tipo == "LINE":
        return Entidad(ObjectName="AcDbLine", StartPoint=p3(e.inicio), EndPoint=p3(e.fin), **base)
    if e.tipo == "DIMENSION":
        # cota girada: COM no expone ExtLine1Point; solo TextPosition y Rotation
        (a, b) = e.segmento or ((0, 0), (0, 0))
        return Entidad(ObjectName="AcDbRotatedDimension", Measurement=e.medida or 0.0,
                       TextPosition=((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, 0.0),
                       Rotation=math.atan2(b[1] - a[1], b[0] - a[0]), **base)
    if e.tipo in ("TEXT", "MTEXT"):
        return Entidad(ObjectName="AcDbText", TextString=e.texto, InsertionPoint=p3(e.punto or (0, 0)), **base)
    return Entidad(ObjectName="AcDbCircle", **base)


class ModelSpace:
    def __init__(self, entidades):
        self.ents = list(entidades)
        self._h = 0xF000000

    @property
    def Count(self):
        return len(self.ents)

    def Item(self, i):
        return self.ents[i]

    def _nuevo(self, ent):
        self._h += 1
        ent.Handle = format(self._h, "X")
        self.ents.append(ent)
        return ent

    def AddLightWeightPolyline(self, coords):
        return self._nuevo(Entidad(ObjectName="AcDbPolyline", Coordinates=tuple(coords), Closed=False, Layer="0"))

    def AddText(self, texto, punto, altura):
        return self._nuevo(Entidad(ObjectName="AcDbText", TextString=texto, InsertionPoint=tuple(punto), Layer="0"))

    def AddLine(self, a, b):
        return self._nuevo(Entidad(ObjectName="AcDbLine", StartPoint=tuple(a), EndPoint=tuple(b), Layer="0"))


class Cancelado(Exception):
    pass


class Utility:
    """Responde con un guion de entradas: palabras, puntos (tuplas) o None (= Enter/Esc)."""
    def __init__(self, guion):
        self.guion = list(guion)
        self.prompts = []

    def _sig(self, prompt):
        self.prompts.append(prompt)
        r = self.guion.pop(0)
        if r is None:
            raise Cancelado(prompt)
        return r

    def Prompt(self, t):
        self.prompts.append(t)

    def InitializeUserInput(self, bits, kw=""):
        pass

    def GetKeyword(self, prompt):
        return self._sig(prompt)

    def GetString(self, permitir_espacios, prompt):
        return self._sig(prompt)

    def GetPoint(self, *args, Prompt=None):
        return (*self._sig(Prompt or args[-1]), 0.0)

    def GetCorner(self, base, prompt):
        return (*self._sig(prompt), 0.0)

    def GetEntity(self, Prompt=None):
        return self._sig(Prompt), (0, 0, 0)


class Documento:
    def __init__(self, nombre, ruta, entidades, guion=()):
        self.Name, self.Path = nombre, ruta
        self.ModelSpace = ModelSpace(entidades)
        self.Utility = Utility(guion)
        self.Layers = _Obj(Add=lambda n: _Obj(Color=0))

    def HandleToObject(self, h):
        for e in self.ModelSpace.ents:
            if e.Handle == h:
                return e
        raise KeyError(h)

    def Regen(self, x):
        pass


class Aplicacion:
    def __init__(self, documentos):
        self.Documents = documentos
        self.ActiveDocument = documentos[0]
