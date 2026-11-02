"""Archivo de revisión que acompaña al pedido: detalle por etiqueta, pendientes y resumen."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from .cubicacion_cype import Detalle
from .pesos import peso_por_metro

_ENC = PatternFill("solid", fgColor="1F4E78")
_ALERTA = PatternFill("solid", fgColor="FFF2CC")
_ROJO = PatternFill("solid", fgColor="F8CBAD")


def _hoja(wb, titulo, columnas, anchos):
    ws = wb.create_sheet(titulo)
    ws.append(columnas)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = _ENC
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for i, w in enumerate(anchos):
        ws.column_dimensions[chr(65 + i)].width = w
    ws.freeze_panes = "A2"
    return ws


def es_pendiente(d: Detalle) -> bool:
    return any("NO calculada" in o or "No se pudo" in o or "Fuera de todos" in o for o in d.observaciones)


def exportar_revision(detalles: list[Detalle], ruta: str | Path) -> Path:
    wb = Workbook()
    wb.remove(wb.active)
    cols = ["Plano", "Ciclo", "Losa", "Texto plano", "L", "Tipo", "Ø", "Cant.", "Rango (cm)", "Figura", "Lados (cm)",
            "L unit (cm)", "Peso (kg)", "Observaciones"]
    ws = _hoja(wb, "Detalle", cols, [28, 6, 11, 14, 8, 10, 5, 6, 10, 8, 22, 9, 10, 70])
    pend = _hoja(wb, "Pendientes", cols, [28, 6, 11, 14, 8, 10, 5, 6, 10, 8, 22, 9, 10, 70])
    resumen: dict[tuple, list[float]] = defaultdict(lambda: [0, 0.0])
    for d in detalles:
        lu = sum(d.lados)
        pendiente = es_pendiente(d)
        peso = 0.0 if pendiente else round(d.cantidad * lu / 100 * peso_por_metro(d.diametro), 2)
        fila = [d.plano, d.ciclo, d.losa, d.texto, d.largo, d.tipo, d.diametro, d.cantidad,
                round(d.rango_cm) if d.rango_cm else None, d.figura, " + ".join(map(str, d.lados)),
                lu, peso, "; ".join(d.observaciones)]
        ws.append(fila)
        if pendiente:
            pend.append(fila)
            for c in ws[ws.max_row]:
                c.fill = _ROJO
        elif d.observaciones:
            for c in ws[ws.max_row]:
                c.fill = _ALERTA
        if not pendiente:
            r = resumen[(d.ciclo or 0, d.plano, d.diametro)]
            r[0] += d.cantidad
            r[1] += peso
    rs = _hoja(wb, "Resumen", ["Ciclo", "Plano", "Ø (mm)", "N° barras", "Peso (kg)"], [7, 50, 8, 10, 12])
    for (ciclo, plano, diam), (n, kg) in sorted(resumen.items()):
        rs.append([ciclo or None, plano, diam, n, round(kg, 1)])
    rs.append(["TOTAL", "", "", f"=SUM(D2:D{rs.max_row})", f"=SUM(E2:E{rs.max_row})"])
    for c in rs[rs.max_row]:
        c.font = Font(bold=True)
    wb.move_sheet("Resumen", offset=-2)
    ruta = Path(ruta)
    wb.save(ruta)
    return ruta
