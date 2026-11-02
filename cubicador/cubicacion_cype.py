"""Cubicación de losas CYPECAD -> filas de pedido Armacero."""
from __future__ import annotations

import math
import re
from collections import OrderedDict
from dataclasses import dataclass, field

from .armacero import FilaPedido
from .formas import _giro
from .lector_cype import EtiquetaCype, PlanoCype, losa_de
from .modelo import Punto

_RE_CUANTIA = re.compile(
    r"^\s*(?:(?P<cara>F\s*=\s*F'|F'|F)\s*=\s*)?(?P<n>\d+)?\s*(?:%%[cC]|[ØøΦφ∅])\s*(?P<d>\d{1,2})"
    r"(?:\s*a\s*(?P<s>\d+(?:[.,]\d+)?))?\s*(?P<pos>[siSI])?\s*$"
)


@dataclass
class Detalle:
    """Fila de revisión con el origen de cada dato."""
    plano: str
    losa: str
    texto: str
    largo: str
    tipo: str
    diametro: int
    cantidad: int
    figura: str
    lados: list[int]
    rango_cm: float | None
    observaciones: list[str] = field(default_factory=list)


def interpretar_cuantia(txt: str):
    m = _RE_CUANTIA.match(txt.replace(" ", "") if "a" in txt else txt)
    if not m:
        return None
    return {
        "cara": (m.group("cara") or "").replace(" ", ""),
        "n": int(m.group("n")) if m.group("n") else None,
        "d": int(m.group("d")),
        "s": float(m.group("s").replace(",", ".")) if m.group("s") else None,
        "pos": (m.group("pos") or "").lower(),
    }


def cantidad_por_rango(rango_cm: float, esp_cm: float) -> int:
    """N = techo(rango / s) + 1: ninguna separación supera la indicada."""
    return math.ceil(rango_cm / esp_cm - 1e-6) + 1


def _dist_seg_seg(a1: Punto, a2: Punto, b1: Punto, b2: Punto) -> float:
    def ccw(p, q, r):
        return (r[1] - p[1]) * (q[0] - p[0]) - (q[1] - p[1]) * (r[0] - p[0])
    if (ccw(a1, b1, b2) > 0) != (ccw(a2, b1, b2) > 0) and (ccw(a1, a2, b1) > 0) != (ccw(a1, a2, b2) > 0):
        return 0.0

    def dps(p, a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        if dx == dy == 0:
            return math.dist(p, a)
        t = max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)))
        return math.dist(p, (a[0] + t * dx, a[1] + t * dy))
    return min(dps(a1, b1, b2), dps(a2, b1, b2), dps(b1, a1, a2), dps(b2, a1, a2))


def _tramo_principal(et: EtiquetaCype) -> tuple[Punto, Punto] | None:
    if not et.trazo:
        return None
    t = et.trazo
    i = max(range(len(t.tramos)), key=lambda k: t.tramos[k])
    return t.vertices[i], t.vertices[i + 1]


def _buscar_rango(et: EtiquetaCype, plano: PlanoCype, tol: float = 15.0) -> float | None:
    seg = _tramo_principal(et)
    if not seg:
        return None
    mejor, dmin = None, tol
    for medida, (p1, p2) in plano.rangos:
        # la cota de rango es perpendicular a la barra
        vb = (seg[1][0] - seg[0][0], seg[1][1] - seg[0][1])
        vr = (p2[0] - p1[0], p2[1] - p1[1])
        nb, nr = math.hypot(*vb), math.hypot(*vr)
        if nb == 0 or nr == 0 or abs((vb[0] * vr[0] + vb[1] * vr[1]) / (nb * nr)) > 0.2:
            continue
        d = _dist_seg_seg(seg[0], seg[1], p1, p2)
        if d <= dmin:
            mejor, dmin = medida, d
    return mejor


def _giros_reales(et: EtiquetaCype) -> list[float]:
    """Giros a ~90° del dibujo, ignorando los quiebres gráficos de CYPE (±31°)."""
    if not et.trazo:
        return []
    v = et.trazo.vertices
    return [g for g in (_giro(v[i - 1], v[i], v[i + 1]) for i in range(1, len(v) - 1)) if abs(g) >= 60]


def figura_cype(lados: list[int], giros: list[float], largo: int | None, obs: list[str]) -> tuple[str, list[int]]:
    n = len(lados)
    if n == 0:
        return "101A", [largo] if largo else []
    if n == 1:
        return "101A", lados
    mismo_sentido = len({g > 0 for g in giros}) <= 1
    if giros and len(giros) != n - 1:
        obs.append("El dibujo no coincide con los lados de la etiqueta: figura asumida por cantidad de lados")
    if n == 2:
        return "102A", sorted(lados)                      # A = pata corta
    if n == 3:
        if len(giros) == 2 and not mismo_sentido:
            return "103G", lados
        return "103A", lados
    if n == 4:
        main = max(range(4), key=lambda k: lados[k])
        lad = lados if main == 1 else lados[::-1]         # 104A: pata, principal, pata, retorno
        if len(giros) == 3 and not mismo_sentido:
            obs.append("Forma de 4 lados con dobleces en sentidos distintos: revisar figura")
        return "104A", lad
    if n == 5:
        if len(giros) == 4 and not mismo_sentido:
            obs.append("Forma de 5 lados con dobleces en sentidos distintos: revisar figura")
        return "105A", lados
    obs.append(f"Barra de {n} lados: revisar figura")
    return f"10{min(n, 6)}A", lados[:10]


def cubicar_cype(plano: PlanoCype, nombre_plano: str, particion: str, piso, ciclo,
                 agrupar: bool = True) -> tuple[list[FilaPedido], list[Detalle]]:
    detalles: list[Detalle] = []
    for et in plano.etiquetas:
        obs: list[str] = []
        c = interpretar_cuantia(et.cuantia)
        losa = losa_de(et.punto, plano.losas)
        nombre_losa = f"Losa {losa.numero}" if losa and losa.numero else "Losa ?"
        if not c:
            detalles.append(Detalle(nombre_plano, nombre_losa, et.cuantia, et.largo, "?", 0, 0, "REVISAR", [], None,
                                    ["No se pudo interpretar la cuantía"]))
            continue
        m = re.search(r"\d+", et.largo or "")
        largo = int(m.group()) if m else None

        # Tipo / posición
        if c["cara"] == "F=F'":
            tipo, caras = "REF F=F'", 2
        elif c["cara"] == "F'":
            tipo, caras = ("SUPLE" if c["s"] else "REF SUP"), 1
        elif c["cara"] == "F":
            tipo, caras = "REF INF", 1
        else:
            tipo, caras = {"s": "SUP", "i": "INF"}.get(c["pos"], "MALLA"), 1

        # Cantidad
        rango = et.rango_cm
        if c["n"]:
            cant = c["n"] * caras
            if caras == 2:
                obs.append(f"F=F': {c['n']} inferiores + {c['n']} superiores")
        elif c["s"]:
            if rango is None:
                rango = _buscar_rango(et, plano)
                if rango:
                    obs.append("Rango tomado de la cota que cruza la barra (rango compartido)")
            if rango:
                cant = cantidad_por_rango(rango, c["s"])
            else:
                cant = 1
                obs.append("Sin cota de rango: cantidad NO calculada, revisar")
        else:
            cant = 1
            obs.append("Cantidad no indicada")

        lados = list(et.lados)
        if lados and largo and sum(lados) != largo:
            obs.append(f"Suma de lados ({sum(lados)}) distinta de L={largo}")
        fig, lad = figura_cype(lados, _giros_reales(et), largo, obs)
        if not lad:
            obs.append("Sin largo")
        detalles.append(Detalle(nombre_plano, nombre_losa, et.cuantia.replace("%%c", "Ø").replace("%%C", "Ø"),
                                et.largo, tipo, c["d"], cant, fig, lad, rango, obs))

    # Filas de pedido (agrupando barras idénticas de una misma losa)
    grupos: "OrderedDict[tuple, FilaPedido]" = OrderedDict()
    for d in sorted(detalles, key=lambda x: (x.losa, x.diametro, x.figura, x.lados)):
        if d.cantidad <= 0 or not d.lados or any("NO calculada" in o for o in d.observaciones):
            continue  # pendientes: van solo al archivo de revisión
        clave = (d.losa, d.diametro, d.figura, tuple(d.lados), d.tipo) if agrupar else (id(d),)
        if clave in grupos:
            grupos[clave].cantidad += d.cantidad
        else:
            grupos[clave] = FilaPedido(d.losa, particion, piso, ciclo, d.cantidad, d.diametro,
                                       d.figura, list(d.lados), marca=d.tipo)
    return list(grupos.values()), detalles
