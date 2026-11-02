"""Clasificación de la forma de una barra a partir de su trazo."""
from __future__ import annotations

import math

from .modelo import Punto, Trazo


def _giro(a: Punto, b: Punto, c: Punto) -> float:
    """Ángulo de giro (grados, con signo) en el vértice b."""
    v1 = (b[0] - a[0], b[1] - a[1])
    v2 = (c[0] - b[0], c[1] - b[1])
    ang = math.degrees(math.atan2(v2[1], v2[0]) - math.atan2(v1[1], v1[0]))
    return (ang + 180) % 360 - 180


def clasificar(trazo: Trazo | None, diametro_mm: int | None = None) -> str:
    if trazo is None:
        return "Sin dibujo"
    n = len(trazo.tramos)
    if trazo.cerrado:
        if n == 4:
            return "Estribo rectangular"
        if n == 3:
            return "Traba triangular"
        return f"Estribo cerrado ({n} lados)"
    if n == 1:
        return "Recta"

    v = trazo.vertices
    giros = [_giro(v[i - 1], v[i], v[i + 1]) for i in range(1, len(v) - 1)] if len(v) == n + 1 else []
    # Gancho: tramo extremo corto (<= 15 diámetros) con doblez >= 135°
    lim_gancho = 15 * (diametro_mm or 12) / 10
    ganchos = 0
    if giros:
        if trazo.tramos[0] <= lim_gancho and abs(giros[0]) >= 130:
            ganchos += 1
        if trazo.tramos[-1] <= lim_gancho and abs(giros[-1]) >= 130:
            ganchos += 1
    if n == 2:
        return "Recta con gancho" if ganchos == 1 else "L (un doblez)"
    if n == 3:
        if ganchos == 2:
            return "Recta con 2 ganchos"
        if giros and giros[0] * giros[1] > 0:
            return "U (dos dobleces)"
        return "Z / bayoneta"
    if n >= 4 and giros and len(set(math.copysign(1, g) for g in giros)) == 1 and ganchos == 2:
        return "Estribo abierto con ganchos"
    return f"Forma especial ({n} tramos)"


def descripcion_tramos(tramos: list[float]) -> str:
    return " + ".join(f"{t:.0f}" for t in tramos)
