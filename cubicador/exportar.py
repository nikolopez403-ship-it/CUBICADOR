"""Exportación de la cubicación a Excel y CSV."""
from __future__ import annotations

import csv
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .cubicacion import Partida, resumen_por_diametro

_ENC = PatternFill("solid", fgColor="1F4E78")
_ALERTA = PatternFill("solid", fgColor="FFF2CC")

COLUMNAS = [
    ("Marca", "marca", 9), ("Cant.", "cantidad", 7), ("Ø (mm)", "diametro", 8),
    ("Esp. (cm)", "espaciamiento_cm", 9), ("Forma", "forma", 24), ("Tramos (cm)", "tramos", 22),
    ("L unit. (m)", "largo_unitario_m", 11), ("L total (m)", "largo_total_m", 11),
    ("kg/m", "kg_m", 7), ("Peso (kg)", "peso_kg", 11), ("Fuente largo", "fuente_largo", 22),
    ("Capa", "capa", 14), ("Texto en plano", "texto_original", 30), ("Observaciones", "observaciones", 60),
]


def _encabezado(ws, titulos: list[str]):
    ws.append(titulos)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = _ENC
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.freeze_panes = "A2"


def a_excel(partidas: list[Partida], ruta: str | Path, titulo: str = "") -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Detalle"
    _encabezado(ws, [c[0] for c in COLUMNAS])
    for p in partidas:
        fila = []
        for _, attr, _ in COLUMNAS:
            v = getattr(p, attr)
            fila.append("; ".join(v) if isinstance(v, list) else v)
        ws.append(fila)
        if p.observaciones:
            for c in ws[ws.max_row]:
                c.fill = _ALERTA
    fin = ws.max_row
    ws.append([])
    ws.append(["TOTAL"] + [""] * 6 + [f"=SUM(H2:H{fin})", "", f"=SUM(J2:J{fin})"])
    for c in ws[ws.max_row]:
        c.font = Font(bold=True)
    for i, (_, _, ancho) in enumerate(COLUMNAS, 1):
        ws.column_dimensions[get_column_letter(i)].width = ancho

    rs = wb.create_sheet("Resumen por diámetro")
    _encabezado(rs, ["Ø (mm)", "N° barras", "Largo total (m)", "kg/m", "Peso (kg)", "Barras de 12 m (aprox.)"])
    for r in resumen_por_diametro(partidas):
        rs.append([r["diametro"], r["barras"], r["largo_m"], r["kg_m"], r["peso_kg"], r["barras_12m"]])
    n = rs.max_row
    rs.append(["TOTAL", f"=SUM(B2:B{n})", f"=SUM(C2:C{n})", "", f"=SUM(E2:E{n})", f"=SUM(F2:F{n})"])
    for c in rs[rs.max_row]:
        c.font = Font(bold=True)
    for col in "ABCDEF":
        rs.column_dimensions[col].width = 16
    if titulo:
        rs.insert_rows(1)
        rs["A1"] = titulo
        rs["A1"].font = Font(bold=True, size=13)

    ruta = Path(ruta)
    wb.save(ruta)
    return ruta


def a_csv(partidas: list[Partida], ruta: str | Path) -> Path:
    ruta = Path(ruta)
    with ruta.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow([c[0] for c in COLUMNAS])
        for p in partidas:
            w.writerow(["; ".join(v) if isinstance(v := getattr(p, a), list) else v for _, a, _ in COLUMNAS])
    return ruta
