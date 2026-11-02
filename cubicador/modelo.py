"""Modelo intermedio independiente de la fuente (DXF, DWG o AutoCAD en vivo).

Todas las coordenadas y largos geométricos se guardan en CENTÍMETROS
(la conversión desde las unidades del dibujo se hace en el lector).
"""
from __future__ import annotations

from dataclasses import dataclass, field

Punto = tuple[float, float]


@dataclass
class Texto:
    contenido: str
    punto: Punto            # punto de inserción (cm)
    capa: str = ""
    punto_flecha: Punto | None = None   # extremo de la flecha si viene de un multileader


@dataclass
class Trazo:
    """Polilínea (o cadena de líneas) que representa el dibujo de una barra."""
    tramos: list[float]     # largos de los tramos rectos (cm)
    vertices: list[Punto]   # vértices (cm)
    cerrado: bool = False
    capa: str = ""
    largo_arcos: float = 0.0  # largo desarrollado de los doblados en arco (cm)

    @property
    def largo_desarrollado(self) -> float:
        return sum(self.tramos) + self.largo_arcos


@dataclass
class Dibujo:
    textos: list[Texto] = field(default_factory=list)
    trazos: list[Trazo] = field(default_factory=list)
    origen: str = ""
