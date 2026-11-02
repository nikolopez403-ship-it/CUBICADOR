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

    pc = sub.add_parser("cype", help="Planos de losas CYPECAD (DWG) -> pedido Armacero")
    pc.add_argument("planos", nargs="+", help="Uno o más DWG del mismo pedido")
    pc.add_argument("--plantilla", required=True, help="Planilla de pedido Armacero (.xlsx) a usar de base")
    pc.add_argument("-o", "--salida", default="pedido.xlsx")
    pc.add_argument("--piso", required=True)
    pc.add_argument("--ciclo", default="", help="Ciclo fijo para todo el pedido (si no hay cuadrantes)")
    pc.add_argument("--ciclos", help="DXF/DWG con los cuadrantes de ciclo (polilíneas cerradas + texto "
                                     "'C1', 'C2'... en una capa con 'CICLO' en el nombre). Si se omite, "
                                     "se buscan en los mismos planos.")
    pc.add_argument("--particion", default="LC", help="FUND, ELEV, LC, VC, BAT u OTRO (LC)")
    pc.add_argument("--sin-agrupar", action="store_true", help="Una fila por etiqueta, sin sumar barras iguales")

    a = ap.parse_args(argv)
    if a.modo == "cype":
        return _main_cype(a)
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


def _main_cype(a) -> int:
    from collections import defaultdict

    from .armacero import exportar_armacero
    from .cubicacion_cype import cubicar_cype
    from .lector_cype import leer_cuadrantes, leer_plano_cype
    from .pesos import peso_por_metro
    from .revision import exportar_revision, es_pendiente

    try:
        planos = [(r, leer_plano_cype(r)) for r in a.planos]
        cuadrantes = leer_cuadrantes(a.ciclos) if a.ciclos else [c for _, p in planos for c in p.ciclos]
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    if a.ciclos and not cuadrantes:
        print("Error: no se encontraron cuadrantes (polilínea cerrada + texto con número en capa *CICLO*)",
              file=sys.stderr)
        return 1
    if cuadrantes:
        print("Ciclos: " + ", ".join(f"{c.nombre}" for c in cuadrantes))

    filas, detalles = [], []
    for ruta, plano in planos:
        nombre = plano.titulo or Path(ruta).stem
        f, d = cubicar_cype(plano, nombre, a.particion, a.piso, a.ciclo,
                            agrupar=not a.sin_agrupar, cuadrantes=cuadrantes or None)
        filas += f
        detalles += d
        print(f"{nombre}: {len(d)} etiquetas -> {len(f)} filas")

    salida = Path(a.salida)
    salida.parent.mkdir(parents=True, exist_ok=True)
    por_ciclo: dict = defaultdict(list)
    for fl in filas:
        por_ciclo[fl.ciclo if cuadrantes else None].append(fl)
    for ciclo, fls in sorted(por_ciclo.items(), key=lambda x: x[0] or 0):
        destino = salida if ciclo is None else salida.with_name(f"{salida.stem} - C{ciclo}{salida.suffix}")
        exportar_armacero(fls, a.plantilla, destino)
        kg = defaultdict(float)
        for r in fls:
            kg[r.diametro] += r.cantidad * sum(r.lados) / 100 * peso_por_metro(r.diametro)
        print(f"{destino.name}: {len(fls)} filas, {sum(kg.values()):.1f} kg  "
              + "  ".join(f"Ø{k}={v:.0f}" for k, v in sorted(kg.items())))
    rev = salida.with_name(salida.stem + "_revision.xlsx")
    exportar_revision(detalles, rev)
    pend = sum(1 for d in detalles if es_pendiente(d))
    if pend:
        print(f"⚠ {pend} partidas NO incluidas en el pedido (ver hoja 'Pendientes' de {rev.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
