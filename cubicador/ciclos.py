"""Reparto de las barras en ciclos de hormigonado según cuadrantes dibujados en CAD.

Regla:
  - Cada barra pertenece al ciclo del cuadrante en que queda.
  - Si una barra toca más de un cuadrante (viene del ciclo siguiente y amarra al
    actual), queda en el ciclo de MENOR número.
  - Las barras distribuidas en un rango se ubican una por una a lo largo de la cota
    de rango, así un mismo grupo puede repartirse entre dos ciclos.
"""
from __future__ import annotations

import copy
import math

from .lector_cype import Cuadrante, EtiquetaCype, PlanoCype, _dentro
from .modelo import Punto


def _cortan(a: Punto, b: Punto, c: Punto, d: Punto) -> bool:
    def o(p, q, r):
        v = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        return 0 if abs(v) < 1e-9 else (1 if v > 0 else -1)
    o1, o2, o3, o4 = o(a, b, c), o(a, b, d), o(c, d, a), o(c, d, b)
    return o1 != o2 and o3 != o4


def toca(polilinea: list[Punto], poligono: list[Punto]) -> bool:
    if any(_dentro(p, poligono) for p in polilinea):
        return True
    n = len(poligono)
    for i in range(len(polilinea) - 1):
        for j in range(n):
            if _cortan(polilinea[i], polilinea[i + 1], poligono[j], poligono[(j + 1) % n]):
                return True
    return False


def ciclo_de(polilinea: list[Punto], cuadrantes: list[Cuadrante]) -> int | None:
    tocados = [c.numero for c in cuadrantes if toca(polilinea, c.poligono)]
    return min(tocados) if tocados else None


def _interseccion_rectas(p, u, q, v) -> Punto | None:
    den = u[0] * v[1] - u[1] * v[0]
    if abs(den) < 1e-9:
        return None
    t = ((q[0] - p[0]) * v[1] - (q[1] - p[1]) * v[0]) / den
    return (p[0] + t * u[0], p[1] + t * u[1])


def _barra_dibujada(et: EtiquetaCype, plano: PlanoCype, largo: float | None) -> list[Punto]:
    """Polilínea de la barra: la enlazada; si no, la barra BARRAS paralela más cercana de
    largo parecido (refuerzos); si no, un segmento sobre el texto en su dirección."""
    if et.trazo:
        return et.trazo.vertices
    u = (math.cos(et.rotacion), math.sin(et.rotacion))
    mejor, dmin = None, 150.0
    for tr in plano.barras:
        if largo and abs(tr.largo_desarrollado - largo) > 0.15 * largo:
            continue
        i = max(range(len(tr.tramos)), key=lambda k: tr.tramos[k])
        a, b = tr.vertices[i], tr.vertices[i + 1]
        v = (b[0] - a[0], b[1] - a[1])
        nv = math.hypot(*v)
        if nv == 0 or abs((v[0] * u[0] + v[1] * u[1]) / nv) < 0.95:
            continue
        from .cubicacion_cype import _dist_seg_seg
        d = _dist_seg_seg(et.punto, et.punto, a, b)
        if d < dmin:
            mejor, dmin = tr, d
    if mejor:
        return mejor.vertices
    l = (largo or 100) / 2
    return [(et.punto[0] - u[0] * l, et.punto[1] - u[1] * l), (et.punto[0] + u[0] * l, et.punto[1] + u[1] * l)]


def instancias(et: EtiquetaCype, cantidad: int, plano: PlanoCype, largo: float | None) -> list[list[Punto]]:
    """Una polilínea por barra real."""
    base = _barra_dibujada(et, plano, largo)
    if cantidad <= 1 or not et.rango_seg or not et.trazo:
        return [base] * max(cantidad, 0)
    p1, p2 = et.rango_seg
    i = max(range(len(et.trazo.tramos)), key=lambda k: et.trazo.tramos[k])
    a, b = et.trazo.vertices[i], et.trazo.vertices[i + 1]
    x0 = _interseccion_rectas(a, (b[0] - a[0], b[1] - a[1]), p1, (p2[0] - p1[0], p2[1] - p1[1]))
    if x0 is None:
        return [base] * cantidad
    res = []
    for k in range(cantidad):
        t = k / (cantidad - 1)
        q = (p1[0] + (p2[0] - p1[0]) * t, p1[1] + (p2[1] - p1[1]) * t)
        dx, dy = q[0] - x0[0], q[1] - x0[1]
        res.append([(x + dx, y + dy) for x, y in base])
    return res


def repartir_por_ciclo(detalles, plano: PlanoCype, cuadrantes: list[Cuadrante]):
    """Divide cada Detalle en uno por ciclo, con la cantidad de barras que cae en cada uno."""
    salida = []
    for d in detalles:
        if d.etiqueta is None or d.cantidad <= 0 or any("NO calculada" in o for o in d.observaciones):
            salida.append(d)
            continue
        conteo: dict[int | None, int] = {}
        for pl in instancias(d.etiqueta, d.cantidad, plano, sum(d.lados) or None):
            c = ciclo_de(pl, cuadrantes)
            conteo[c] = conteo.get(c, 0) + 1
        for c, n in sorted(conteo.items(), key=lambda x: (x[0] is None, x[0] or 0)):
            nd = copy.copy(d)
            nd.observaciones = list(d.observaciones)
            nd.cantidad, nd.ciclo = n, c
            if c is None:
                nd.observaciones.append("Fuera de todos los cuadrantes de ciclo: no incluida en el pedido")
            elif len(conteo) > 1:
                nd.observaciones.append(f"Grupo repartido entre ciclos {sorted(k for k in conteo if k)}")
            salida.append(nd)
    return salida
