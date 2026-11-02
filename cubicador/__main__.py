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

    pa2 = sub.add_parser("asistente", help="Asistente en AutoCAD: dibujar ciclos, cubicar y exportar (Windows)")
    pa2.add_argument("--acadver", help="Versión de AutoCAD (variable ACADVER), la entrega el comando CUBICAR")
    pa2.add_argument("--producto", help="Producto (variable PRODUCT), la entrega el comando CUBICAR")
    sub.add_parser("diagnostico", help="Muestra por qué no se logra conectar con AutoCAD (Windows)")

    a = ap.parse_args(argv)
    if a.modo == "cype":
        return _main_cype(a)
    if a.modo == "asistente":
        return _main_asistente(a)
    if a.modo == "diagnostico":
        from .autocad_vivo import diagnostico
        print("  " + diagnostico())
        input("Presione Enter para cerrar...")
        return 0
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
    from .lector_cype import leer_cuadrantes, leer_plano_cype
    from .pedido import generar_pedidos

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
        print("Ciclos: " + ", ".join(c.nombre for c in cuadrantes))
    planos = [(p.titulo or Path(r).stem, p) for r, p in planos]
    res = generar_pedidos(planos, a.plantilla, a.salida, a.piso, a.particion, a.ciclo,
                          cuadrantes, agrupar=not a.sin_agrupar)
    print(f"{res.etiquetas} partidas leídas")
    for ruta, nf, kg, por_d in res.archivos:
        print(f"{ruta.name}: {nf} filas, {kg:.1f} kg  " + "  ".join(f"Ø{k}={v:.0f}" for k, v in por_d.items()))
    if res.pendientes:
        print(f"⚠ {res.pendientes} partidas NO incluidas en el pedido (ver hoja 'Pendientes' de {res.revision.name})")
    return 0


def _main_asistente(a) -> int:
    from .asistente import ejecutar
    try:
        return ejecutar(acadver=a.acadver, producto=a.producto)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        input("Presione Enter para cerrar...")
        return 1


if __name__ == "__main__":
    sys.exit(main())
