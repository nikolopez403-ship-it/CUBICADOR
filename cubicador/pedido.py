"""Proceso completo: planos CYPE + cuadrantes -> pedidos Armacero por ciclo + revisión."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .armacero import exportar_armacero
from .cubicacion_cype import cubicar_cype
from .lector_cype import Cuadrante, PlanoCype
from .pesos import peso_por_metro
from .revision import es_pendiente, exportar_revision


@dataclass
class Resultado:
    archivos: list[tuple[Path, int, float, dict]] = field(default_factory=list)  # (ruta, filas, kg, kg por Ø)
    revision: Path | None = None
    pendientes: int = 0
    etiquetas: int = 0


def generar_pedidos(planos: list[tuple[str, PlanoCype]], plantilla: str | Path, salida: str | Path,
                    piso, particion: str = "LC", ciclo_fijo="",
                    cuadrantes: list[Cuadrante] | None = None, agrupar: bool = True) -> Resultado:
    """`salida` es la ruta base: con ciclos se generan '<base> - C1.xlsx', '<base> - C2.xlsx'..."""
    salida = Path(salida)
    salida.parent.mkdir(parents=True, exist_ok=True)
    filas, detalles = [], []
    for nombre, plano in planos:
        f, d = cubicar_cype(plano, nombre, particion, piso, ciclo_fijo, agrupar=agrupar,
                            cuadrantes=cuadrantes or None)
        filas += f
        detalles += d

    res = Resultado(etiquetas=len(detalles))
    por_ciclo: dict = defaultdict(list)
    for fl in filas:
        por_ciclo[fl.ciclo if cuadrantes else None].append(fl)
    for ciclo, fls in sorted(por_ciclo.items(), key=lambda x: x[0] or 0):
        destino = salida if ciclo is None else salida.with_name(f"{salida.stem} - C{ciclo}{salida.suffix}")
        exportar_armacero(fls, plantilla, destino)
        kg: dict[int, float] = defaultdict(float)
        for r in fls:
            kg[r.diametro] += r.cantidad * sum(r.lados) / 100 * peso_por_metro(r.diametro)
        res.archivos.append((destino, len(fls), sum(kg.values()), dict(sorted(kg.items()))))
    res.revision = exportar_revision(detalles, salida.with_name(salida.stem + "_revision.xlsx"))
    res.pendientes = sum(1 for d in detalles if es_pendiente(d))
    return res
