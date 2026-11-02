"""Interpretación de las anotaciones de armadura escritas en el plano.

Formatos reconocidos (combinables, en cualquier orden después del diámetro):

    3Ø12                     cantidad + diámetro
    M1 3Ø12 L=450            marca + cantidad + diámetro + largo
    Ø8@20                    diámetro + espaciamiento
    E Ø8 a 20 en 450         estribos, espaciamiento y largo de distribución
    2φ16 L=6.20 (x4)         largo en metros, repetido en 4 elementos
    %%c10@15                 código AutoCAD de Ø

El símbolo de diámetro puede venir como Ø, ø, φ, Φ, ∅, %%c o "fi".
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_SIMBOLOS_DIAMETRO = re.compile(r"%%[cC]|[ØøφΦ∅]|\bfi\b|\bFI\b|\bdiam\.?", re.UNICODE)

_RE_ANOTACION = re.compile(
    r"""
    (?:(?P<marca>\b[A-Z]{1,3}-?\d{1,3}[a-z]?)(?:\s*:\s*|\s+))?   # marca opcional: M1, B12, E-3
    (?:(?P<cant>\d{1,4})\s*[xX]?\s*)?                           # cantidad opcional
    Ø\s*(?P<diam>\d{1,2})(?![\d.,])                             # diámetro (obligatorio)
    (?P<resto>.*)
    """,
    re.VERBOSE,
)

_NUM = r"(\d+(?:[.,]\d+)?)"
_RE_ESP = re.compile(r"(?:@|\ba\b|c/|\bcada\b)\s*" + _NUM, re.IGNORECASE)
_RE_LARGO = re.compile(r"\bL\s*[=:]?\s*" + _NUM)
_RE_DIST = re.compile(r"\ben\s+" + _NUM, re.IGNORECASE)
_RE_MULT = re.compile(r"\(\s*[xX]\s*(\d+)\s*\)|\(\s*(\d+)\s*veces\s*\)", re.IGNORECASE)
_RE_TRAMOS = re.compile(r"\(\s*(\d+(?:[.,]\d+)?(?:\s*\+\s*\d+(?:[.,]\d+)?)+)\s*\)")


@dataclass
class Anotacion:
    texto_original: str
    diametro: int
    marca: str | None = None
    cantidad: int | None = None
    espaciamiento_cm: float | None = None
    largo_cm: float | None = None
    distribucion_cm: float | None = None
    multiplicador: int = 1
    tramos_cm: list[float] | None = None   # p.ej. "(25+300+25)"


def normalizar(texto: str) -> str:
    t = _SIMBOLOS_DIAMETRO.sub("Ø", texto)
    t = t.replace(" ", " ")
    return re.sub(r"\s+", " ", t).strip()


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def _a_cm(valor: float, crudo: str, unidad: str) -> float:
    """Convierte un largo escrito en el texto a cm.

    unidad: 'cm', 'm', 'mm' o 'auto'. En 'auto' se asume metros si el número
    tiene decimales y es menor que 30 (p.ej. L=6.20) y centímetros en otro caso.
    """
    if unidad == "m":
        return valor * 100
    if unidad == "mm":
        return valor / 10
    if unidad == "cm":
        return valor
    if ("." in crudo or "," in crudo) and valor < 30:
        return valor * 100
    return valor


def interpretar(texto: str, unidad_texto: str = "auto") -> list[Anotacion]:
    """Devuelve las anotaciones de fierro encontradas en un texto.

    Un texto puede contener varias anotaciones separadas por '+', ';' o salto
    de línea (p.ej. "2Ø16 + 2Ø12").
    """
    resultado: list[Anotacion] = []
    normal = normalizar(texto.replace("\\P", "\n"))
    # Separar por ; o saltos de línea; '+' solo si separa dos anotaciones con Ø
    partes = re.split(r"[;\n]|\+(?=\s*\d*\s*Ø)", normal)
    for parte in partes:
        parte = parte.strip()
        m = _RE_ANOTACION.search(parte)
        if not m:
            continue
        diam = int(m.group("diam"))
        if diam < 5 or diam > 40:
            continue
        resto = m.group("resto") or ""
        a = Anotacion(texto_original=texto.strip(), diametro=diam, marca=m.group("marca"))
        if m.group("cant"):
            a.cantidad = int(m.group("cant"))
        if (e := _RE_ESP.search(resto)):
            a.espaciamiento_cm = _a_cm(_num(e.group(1)), e.group(1), "cm" if unidad_texto == "auto" else unidad_texto)
        if (l := _RE_LARGO.search(resto)):
            a.largo_cm = _a_cm(_num(l.group(1)), l.group(1), unidad_texto)
        if (d := _RE_DIST.search(resto)):
            a.distribucion_cm = _a_cm(_num(d.group(1)), d.group(1), unidad_texto)
        if (x := _RE_MULT.search(resto)):
            a.multiplicador = int(x.group(1) or x.group(2))
        if (t := _RE_TRAMOS.search(resto)):
            a.tramos_cm = [_num(v) for v in re.split(r"\s*\+\s*", t.group(1))]
        resultado.append(a)
    # "2Ø16 + 2Ø12 L=420": el largo/espaciamiento escrito al final aplica a todo el grupo
    if len(resultado) > 1:
        ultimo = resultado[-1]
        for a in resultado[:-1]:
            for attr in ("largo_cm", "espaciamiento_cm", "distribucion_cm"):
                if getattr(a, attr) is None:
                    setattr(a, attr, getattr(ultimo, attr))
    return resultado
