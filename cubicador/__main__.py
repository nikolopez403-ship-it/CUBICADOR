"""Línea de comandos.

    python -m cubicador archivo PLANO.dxf -o cubicacion.xlsx
    python -m cubicador vivo --seleccion -o cubicacion.xlsx      (Windows + AutoCAD abierto)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .cubicacion import Opciones, cubicar, resumen_por_diametro
from .exportar import a_csv, a_excel


def _lista(s: str | None):
    return [x.strip() for x in s.split(",") if x.strip()] if s else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="cubicador", description="Cubicación de fierro desde planos AutoCAD")
    sub = ap.add_subparsers(dest="modo", required=True)
    pa = sub.add_parser("archivo", help="Leer un DXF o DWG")
    pa.add_argument("plano")
    sub.add_parser("vivo", help="Leer el dibujo abierto en AutoCAD (Windows)").add_argument(
        "--seleccion", action="store_true", help="Pedir al usuario que seleccione la zona")

    for p in (pa, sub.choices["vivo"]):
        p.add_argument("-o", "--salida", default="cubicacion.xlsx", help=".xlsx o .csv")
        p.add_argument("--unidad-dibujo", choices=["mm", "cm", "m"], help="Unidades del dibujo (por defecto $INSUNITS)")
        p.add_argument("--unidad-texto", choices=["auto", "cm", "m", "mm"], default="auto", help="Unidad de L= en los textos")
        p.add_argument("--capas-fierro", help="Patrones de capas de barras, ej: '*FIERRO*,ARM*'")
        p.add_argument("--capas-texto", help="Patrones de capas de textos de armadura")
        p.add_argument("--radio", type=float, default=60.0, help="Distancia máx. texto-barra en cm (60)")
        p.add_argument("--sin-ganchos", action="store_true", help="No sumar ganchos de 135° a estribos")

    a = ap.parse_args(argv)
    kw = dict(unidad_dibujo=a.unidad_dibujo, capas_fierro=_lista(a.capas_fierro), capas_texto=_lista(a.capas_texto))
    try:
        if a.modo == "archivo":
            from .lector_dxf import leer_dxf
            dibujo = leer_dxf(a.plano, **kw)
        else:
            from .autocad_vivo import leer_autocad
            dibujo = leer_autocad(seleccion=a.seleccion, **kw)
    except (RuntimeError, OSError, IOError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    op = Opciones(unidad_texto=a.unidad_texto, radio_asociacion_cm=a.radio, ganchos_estribo=not a.sin_ganchos)
    partidas = cubicar(dibujo, op)
    if not partidas:
        print("No se encontraron anotaciones de armadura (textos con Ø).", file=sys.stderr)
        return 2

    salida = Path(a.salida)
    (a_csv if salida.suffix.lower() == ".csv" else a_excel)(partidas, salida)

    print(f"{len(dibujo.textos)} textos, {len(dibujo.trazos)} trazos leídos · {len(partidas)} partidas")
    print(f"{'Ø':>4} {'barras':>7} {'largo (m)':>10} {'peso (kg)':>10}")
    total = 0.0
    for r in resumen_por_diametro(partidas):
        print(f"{r['diametro']:>4} {r['barras']:>7} {r['largo_m']:>10.2f} {r['peso_kg']:>10.2f}")
        total += r["peso_kg"]
    print(f"Total: {total:.2f} kg")
    alertas = sum(1 for p in partidas if p.observaciones)
    if alertas:
        print(f"⚠ {alertas} partidas con observaciones (marcadas en amarillo en el Excel)")
    print(f"Guardado en {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
