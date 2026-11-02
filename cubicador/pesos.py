"""Pesos nominales de barras de refuerzo (NCh204 / ASTM A615), en kg/m.

Fórmula: peso = 0.00617 * d^2  (d en mm). Se dejan los valores tabulados
habituales en Chile para los diámetros comerciales.
"""

PESO_KG_M: dict[int, float] = {
    6: 0.222,
    8: 0.395,
    10: 0.617,
    12: 0.888,
    16: 1.580,
    18: 2.000,
    22: 2.980,
    25: 3.850,
    28: 4.830,
    32: 6.310,
    36: 7.990,
}


def peso_por_metro(diametro_mm: int) -> float:
    """Peso nominal en kg/m. Para diámetros no tabulados usa la fórmula."""
    if diametro_mm in PESO_KG_M:
        return PESO_KG_M[diametro_mm]
    return round(0.00617 * diametro_mm**2, 3)


def es_diametro_comercial(diametro_mm: int) -> bool:
    return diametro_mm in PESO_KG_M
