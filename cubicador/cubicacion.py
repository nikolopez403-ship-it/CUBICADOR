"""Motor de cubicación: asocia anotaciones con trazos y calcula largos y pesos."""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

from .formas import clasificar, descripcion_tramos
from .modelo import Dibujo, Punto, Trazo
from .parser import Anotacion, interpretar
from .pesos import es_diametro_comercial, peso_por_metro


@dataclass
class Opciones:
    unidad_texto: str = "auto"          # unidad de L= y "en": auto | cm | m | mm
    radio_asociacion_cm: float = 60.0   # distancia máxima texto-barra
    ganchos_estribo: bool = True        # suma ganchos de 135° a estribos cerrados sin L=
    tolerancia_diferencia: float = 0.05 # avisa si L= y el dibujo difieren más de 5 %


@dataclass
class Partida:
    marca: str
    diametro: int
    cantidad: int
    forma: str
    tramos: str
    largo_unitario_m: float
    largo_total_m: float
    kg_m: float
    peso_kg: float
    espaciamiento_cm: float | None
    capa: str
    texto_original: str
    fuente_largo: str
    observaciones: list[str] = field(default_factory=list)


def _dist_punto_segmento(p: Punto, a: Punto, b: Punto) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    if dx == dy == 0:
        return math.dist(p, a)
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy)))
    return math.dist(p, (ax + t * dx, ay + t * dy))


def _dist_trazo(p: Punto, tr: Trazo) -> float:
    v = tr.vertices
    if len(v) < 2:
        return math.inf
    return min(_dist_punto_segmento(p, v[i], v[i + 1]) for i in range(len(v) - 1))


def _trazo_cercano(p: Punto, trazos: list[Trazo], radio: float, usados: set[int]) -> Trazo | None:
    mejor, dmin = None, radio
    for i, tr in enumerate(trazos):
        if i in usados:
            continue
        d = _dist_trazo(p, tr)
        if d <= dmin:
            mejor, dmin = i, d
    if mejor is None:
        return None
    usados.add(mejor)
    return trazos[mejor]


def _gancho_estribo_cm(diam: int) -> float:
    # Gancho sísmico 135°: extensión 6db >= 7.5 cm (ACI 318 25.3.2 / NCh430), + doblez ~ 2db
    return max(6 * diam / 10, 7.5) + 2 * diam / 10


def _calcular(an: Anotacion, tr: Trazo | None, capa: str, op: Opciones, n: int) -> Partida:
    obs: list[str] = []
    forma = clasificar(tr, an.diametro)
    tramos = ""

    # --- Largo unitario ---
    largo_geo = tr.largo_desarrollado if tr else None
    if an.tramos_cm:
        tramos = descripcion_tramos(an.tramos_cm)
    elif tr:
        tramos = descripcion_tramos(tr.tramos)

    if an.largo_cm:
        largo, fuente = an.largo_cm, "Texto (L=)"
        if largo_geo and abs(largo_geo - largo) / largo > op.tolerancia_diferencia:
            obs.append(f"L= del texto ({largo:.0f} cm) difiere del dibujo ({largo_geo:.0f} cm)")
    elif an.tramos_cm:
        largo, fuente = sum(an.tramos_cm), "Texto (tramos)"
    elif largo_geo:
        largo, fuente = largo_geo, "Dibujo"
        if tr and tr.cerrado and op.ganchos_estribo:
            largo += 2 * _gancho_estribo_cm(an.diametro)
            fuente = "Dibujo + 2 ganchos 135°"
    else:
        largo, fuente = 0.0, "—"
        obs.append("Sin largo: no hay L= ni dibujo asociado")

    # --- Cantidad ---
    if an.cantidad:
        cant = an.cantidad
    elif an.espaciamiento_cm and an.distribucion_cm:
        cant = math.floor(an.distribucion_cm / an.espaciamiento_cm) + 1
        obs.append(f"Cantidad calculada: {an.distribucion_cm:.0f}/{an.espaciamiento_cm:.0f} + 1")
    elif an.espaciamiento_cm:
        cant = 1
        obs.append("Indica espaciamiento sin largo de distribución ('en ...'): revisar cantidad")
    else:
        cant = 1
        obs.append("Cantidad no indicada: se asume 1")
    cant *= an.multiplicador
    if an.multiplicador > 1:
        obs.append(f"Multiplicado x{an.multiplicador}")

    if not es_diametro_comercial(an.diametro):
        obs.append(f"Ø{an.diametro} no es un diámetro comercial habitual")

    kg_m = peso_por_metro(an.diametro)
    lu = largo / 100
    return Partida(
        marca=an.marca or f"#{n}",
        diametro=an.diametro,
        cantidad=cant,
        forma=forma,
        tramos=tramos,
        largo_unitario_m=round(lu, 2),
        largo_total_m=round(lu * cant, 2),
        kg_m=kg_m,
        peso_kg=round(lu * cant * kg_m, 2),
        espaciamiento_cm=an.espaciamiento_cm,
        capa=capa,
        texto_original=an.texto_original,
        fuente_largo=fuente,
        observaciones=obs,
    )


def cubicar(dibujo: Dibujo, op: Opciones | None = None) -> list[Partida]:
    op = op or Opciones()
    partidas: list[Partida] = []
    usados: set[int] = set()
    n = 0
    for tx in dibujo.textos:
        anotaciones = interpretar(tx.contenido, op.unidad_texto)
        for an in anotaciones:
            n += 1
            ref = tx.punto_flecha or tx.punto
            # Solo se asocia trazo cuando el texto describe una sola barra
            tr = _trazo_cercano(ref, dibujo.trazos, op.radio_asociacion_cm, usados) if len(anotaciones) == 1 else None
            partidas.append(_calcular(an, tr, tx.capa, op, n))
    return partidas


def resumen_por_diametro(partidas: list[Partida]) -> list[dict]:
    acc: dict[int, dict] = defaultdict(lambda: {"largo_m": 0.0, "peso_kg": 0.0, "barras": 0})
    for p in partidas:
        a = acc[p.diametro]
        a["largo_m"] += p.largo_total_m
        a["peso_kg"] += p.peso_kg
        a["barras"] += p.cantidad
    return [
        {"diametro": d, "barras": v["barras"], "largo_m": round(v["largo_m"], 2),
         "kg_m": peso_por_metro(d), "peso_kg": round(v["peso_kg"], 2),
         "barras_12m": math.ceil(v["largo_m"] / 12)}
        for d, v in sorted(acc.items())
    ]
