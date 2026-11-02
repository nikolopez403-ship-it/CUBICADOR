"""Asistente dentro de AutoCAD: pide dibujar los cuadrantes de ciclo, cubica y exporta.

Se lanza con el comando CUBICAR de AutoCAD (cubicar.lsp) o con
    python -m cubicador asistente
con AutoCAD abierto y el plano de losas CYPE activo.

Flujo:
  1. Lee el plano activo (y, si se quiere, los demás planos abiertos: malla, refuerzos...).
  2. Si ya hay cuadrantes en la capa CICLOS ofrece usarlos, agregar más o redibujarlos.
  3. Pide dibujar cada ciclo: Rectángulo (2 esquinas), Polígono (clic a clic) o Seleccionar
     una polilínea cerrada existente. Los dibuja en la capa CICLOS con el texto C1, C2...
  4. Pide piso y partición, cubica y genera un Excel por ciclo con la planilla Armacero,
     más el archivo de revisión, en la carpeta del plano.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
from pathlib import Path

from .lector_cype import Cuadrante, PlanoCype, parsear_entidades
from .pedido import generar_pedidos

CAPA_CICLOS = "CICLOS"
PARTICIONES = ["LC", "VC", "ELEV", "FUND", "BAT", "OTRO"]


# ---------------------------------------------------------------------------
# Configuración persistente (plantilla, último piso...)
# ---------------------------------------------------------------------------

def _ruta_config() -> Path:
    base = os.environ.get("APPDATA") or Path.home() / ".config"
    return Path(base) / "cubicador" / "config.json"


def cargar_config(ruta: Path | None = None) -> dict:
    ruta = ruta or _ruta_config()
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def guardar_config(cfg: dict, ruta: Path | None = None) -> None:
    ruta = ruta or _ruta_config()
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Interfaz con AutoCAD (envoltorio de doc.Utility y del espacio modelo)
# ---------------------------------------------------------------------------

def _vpt(p):
    """Punto 3D como VARIANT para COM (en pruebas se devuelve la tupla)."""
    try:
        import pythoncom  # type: ignore
        import win32com.client  # type: ignore
        return win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, (float(p[0]), float(p[1]), 0.0))
    except ImportError:
        return (float(p[0]), float(p[1]), 0.0)


def _varr(valores):
    try:
        import pythoncom  # type: ignore
        import win32com.client  # type: ignore
        return win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [float(v) for v in valores])
    except ImportError:
        return [float(v) for v in valores]


class InterfazAutoCAD:
    def __init__(self, acad, doc):
        self.acad, self.doc = acad, doc
        self.u = doc.Utility

    # --- mensajes y preguntas ---
    def msg(self, texto: str) -> None:
        print(texto)
        try:
            self.u.Prompt("\n" + texto)
        except Exception:  # noqa: BLE001
            pass

    def palabra(self, pregunta: str, opciones: list[str], defecto: str | None) -> str | None:
        """Devuelve la opción elegida, el defecto con Enter, o None con Esc."""
        try:
            self.u.InitializeUserInput(0, " ".join(opciones))
            r = self.u.GetKeyword("\n" + pregunta)
        except Exception:  # noqa: BLE001
            return None
        return r or defecto

    def texto(self, pregunta: str, defecto: str = "") -> str | None:
        try:
            r = self.u.GetString(1, f"\n{pregunta} <{defecto}>: ")
        except Exception:  # noqa: BLE001
            return None
        return (r or "").strip() or defecto

    def punto(self, pregunta: str, base=None):
        try:
            if base is None:
                p = self.u.GetPoint(Prompt="\n" + pregunta)
            else:
                p = self.u.GetPoint(_vpt(base), "\n" + pregunta)
        except TypeError:
            try:
                import pythoncom  # type: ignore
                p = self.u.GetPoint(pythoncom.Empty, "\n" + pregunta)
            except Exception:  # noqa: BLE001
                return None
        except Exception:  # noqa: BLE001  Enter / Esc
            return None
        return (float(p[0]), float(p[1]))

    def esquina(self, base, pregunta: str):
        try:
            p = self.u.GetCorner(_vpt(base), "\n" + pregunta)
        except Exception:  # noqa: BLE001
            return None
        return (float(p[0]), float(p[1]))

    def entidad(self, pregunta: str):
        try:
            r = self.u.GetEntity(Prompt="\n" + pregunta)
        except Exception:  # noqa: BLE001
            return None
        return r[0] if isinstance(r, tuple) else r

    # --- dibujo ---
    def preparar_capa(self) -> None:
        try:
            capa = self.doc.Layers.Add(CAPA_CICLOS)
            capa.Color = 6  # magenta
        except Exception:  # noqa: BLE001
            pass

    def polilinea(self, puntos, color: int):
        coords = [v for p in puntos for v in (p[0], p[1])]
        pl = self.doc.ModelSpace.AddLightWeightPolyline(_varr(coords))
        pl.Closed = True
        pl.Layer = CAPA_CICLOS
        pl.Color = color
        try:
            pl.ConstantWidth = 0.0
        except Exception:  # noqa: BLE001
            pass
        return pl

    def rotulo(self, texto: str, punto, altura: float, color: int):
        t = self.doc.ModelSpace.AddText(texto, _vpt(punto), altura)
        t.Layer = CAPA_CICLOS
        t.Color = color
        return t

    def linea(self, a, b):
        ln = self.doc.ModelSpace.AddLine(_vpt(a), _vpt(b))
        ln.Layer = CAPA_CICLOS
        return ln

    def borrar(self, handles: list[int]) -> None:
        for h in handles:
            try:
                self.doc.HandleToObject(format(h, "X")).Delete()
            except Exception:  # noqa: BLE001
                pass

    def regenerar(self) -> None:
        try:
            self.doc.Regen(1)
        except Exception:  # noqa: BLE001
            pass

    def elegir_plantilla(self, actual: str | None) -> str | None:
        """Diálogo de Windows para elegir la planilla Armacero; si no hay, se pide la ruta."""
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            r = filedialog.askopenfilename(title="Seleccione la planilla de pedido Armacero (.xlsx)",
                                           filetypes=[("Excel", "*.xlsx")],
                                           initialdir=str(Path(actual).parent) if actual else None)
            root.destroy()
            return r or None
        except Exception:  # noqa: BLE001
            return self.texto("Ruta de la planilla de pedido Armacero (.xlsx)", actual or "")


# ---------------------------------------------------------------------------
# Flujo
# ---------------------------------------------------------------------------

def _centroide(pol):
    return (sum(p[0] for p in pol) / len(pol), sum(p[1] for p in pol) / len(pol))


def _tamano(pol):
    xs, ys = [p[0] for p in pol], [p[1] for p in pol]
    return min(max(xs) - min(xs), max(ys) - min(ys))


def _dibujar_ciclo(ui: InterfazAutoCAD, n: int) -> tuple[list | None, bool]:
    """Pide un cuadrante. Devuelve (polígono, seguir)."""
    modo = ui.palabra(f"Ciclo {n} - dibuje el cuadrante [Rectangulo/Poligono/Seleccionar/Terminar] "
                      f"<Rectangulo>: ", ["Rectangulo", "Poligono", "Seleccionar", "Terminar"], "Rectangulo")
    if modo is None or modo == "Terminar":
        return None, False
    if modo == "Rectangulo":
        p1 = ui.punto(f"Ciclo {n} - primera esquina: ")
        if p1 is None:
            return None, True
        p2 = ui.esquina(p1, f"Ciclo {n} - esquina opuesta: ")
        if p2 is None:
            return None, True
        return [p1, (p2[0], p1[1]), p2, (p1[0], p2[1])], True
    if modo == "Poligono":
        pts, temporales = [], []
        while True:
            txt = f"Ciclo {n} - punto {len(pts) + 1}" + (" (Enter para cerrar)" if len(pts) >= 3 else "") + ": "
            p = ui.punto(txt, pts[-1] if pts else None)
            if p is None:
                break
            if pts:
                temporales.append(ui.linea(pts[-1], p))
            pts.append(p)
        for t in temporales:
            try:
                t.Delete()
            except Exception:  # noqa: BLE001
                pass
        if len(pts) < 3:
            ui.msg("Se necesitan al menos 3 puntos; cuadrante descartado.")
            return None, True
        return pts, True
    if modo == "Seleccionar":
        ent = ui.entidad(f"Ciclo {n} - seleccione una polilínea cerrada: ")
        if ent is None:
            return None, True
        try:
            c = list(ent.Coordinates)
            pol = [(c[i], c[i + 1]) for i in range(0, len(c) - 1, 2)]
        except Exception:  # noqa: BLE001
            ui.msg("El objeto seleccionado no es una polilínea.")
            return None, True
        if len(pol) < 3:
            ui.msg("La polilínea debe tener al menos 3 vértices.")
            return None, True
        return pol, True
    return None, True


def _leer_doc(ui: InterfazAutoCAD, doc, lector) -> tuple[list, PlanoCype]:
    ui.msg(f"Leyendo {doc.Name} ...")
    ents = lector(doc, lambda i, t: print(f"  {i}/{t} objetos", end="\r"))
    plano = parsear_entidades(ents)
    ui.msg(f"  {len(plano.etiquetas)} etiquetas de armadura, {len(plano.losas)} losas.")
    return ents, plano


def ejecutar(ui: InterfazAutoCAD | None = None, lector=None, config: Path | None = None) -> int:
    if ui is None:
        from .autocad_vivo import conectar
        acad, doc = conectar()
        ui = InterfazAutoCAD(acad, doc)
    if lector is None:
        from .autocad_vivo import entidades_desde_autocad as lector
    acad, doc = ui.acad, ui.doc
    cfg = cargar_config(config)

    ui.msg("=== CUBICADOR DE FIERRO - pedido Armacero por ciclos ===")

    # 1. Planos a cubicar
    ents, plano = _leer_doc(ui, doc, lector)
    planos: list[tuple[str, PlanoCype]] = []
    if plano.etiquetas:
        planos.append((plano.titulo or doc.Name, plano))
    otros = []
    try:
        otros = [d for d in acad.Documents if d.Name != doc.Name]
    except Exception:  # noqa: BLE001
        pass
    if otros:
        nombres = ", ".join(d.Name for d in otros)
        r = ui.palabra(f"Hay otros planos abiertos ({nombres}). ¿Cubicarlos también? [Si/No] <Si>: ",
                       ["Si", "No"], "Si")
        if r == "Si":
            for d in otros:
                _, p = _leer_doc(ui, d, lector)
                if p.etiquetas:
                    planos.append((p.titulo or d.Name, p))
    if not planos:
        ui.msg("No se encontraron etiquetas de armadura CYPE (CUANTIA/LARGO) en los planos abiertos.")
        return 2

    # 2. Cuadrantes existentes
    cuadrantes: list[Cuadrante] = list(plano.ciclos)
    if cuadrantes:
        lista = ", ".join(c.nombre for c in cuadrantes)
        r = ui.palabra(f"El plano ya tiene cuadrantes de ciclo ({lista}). [Usar/Agregar/Redibujar] <Usar>: ",
                       ["Usar", "Agregar", "Redibujar"], "Usar")
        if r is None:
            ui.msg("Cancelado.")
            return 1
        if r == "Redibujar":
            ui.borrar([e.handle for e in ents if "CICLO" in (e.capa or "").upper()
                       and e.tipo in ("LWPOLYLINE", "TEXT", "MTEXT")])
            cuadrantes = []
        dibujar = r != "Usar"
    else:
        ui.msg("Dibuje los cuadrantes de cada ciclo. Las barras que toquen dos ciclos quedan en el menor.")
        dibujar = True

    # 3. Dibujo de cuadrantes
    if dibujar:
        ui.preparar_capa()
        n = max((c.numero for c in cuadrantes), default=0) + 1
        while True:
            pol, seguir = _dibujar_ciclo(ui, n)
            if pol:
                color = [1, 3, 5, 2, 4, 6, 30, 140][(n - 1) % 8]
                ui.polilinea(pol, color)
                ui.rotulo(f"C{n}", _centroide(pol), max(_tamano(pol) / 12, 20.0), color)
                ui.regenerar()
                cuadrantes.append(Cuadrante(n, f"C{n}", pol))
                ui.msg(f"Ciclo C{n} dibujado.")
                n += 1
            if not seguir:
                break
    if not cuadrantes:
        r = ui.palabra("No hay cuadrantes. ¿Generar un solo pedido sin ciclos? [Si/No] <Si>: ", ["Si", "No"], "Si")
        if r != "Si":
            ui.msg("Cancelado.")
            return 1

    # 4. Datos del pedido
    titulo = " ".join(p.titulo for _, p in planos)
    m = re.search(r"(\d+)\s*[°º]?\s*PISO", titulo.upper())
    piso = ui.texto("Piso", m.group(1) if m else str(cfg.get("piso", "")))
    if piso is None:
        return 1
    part_def = "LC" if "CIELO" in titulo.upper() else cfg.get("particion", "LC")
    particion = ui.palabra(f"Partición [{'/'.join(PARTICIONES)}] <{part_def}>: ", PARTICIONES, part_def)
    if particion is None:
        return 1

    plantilla = cfg.get("plantilla")
    if not plantilla or not Path(plantilla).exists():
        ui.msg("Seleccione la planilla de pedido Armacero que se usará como base.")
        plantilla = ui.elegir_plantilla(plantilla)
        if not plantilla or not Path(plantilla).exists():
            ui.msg("No se seleccionó una planilla válida. Cancelado.")
            return 1

    carpeta = Path(getattr(doc, "Path", "") or Path.home() / "Documents") / "Pedidos fierro"
    base = carpeta / f"P{piso} - {particion}.xlsx"

    # 5. Cubicar y exportar
    ui.msg("Cubicando...")
    res = generar_pedidos(planos, plantilla, base, piso, particion, "", cuadrantes or None)
    cfg.update(plantilla=str(plantilla), piso=piso, particion=particion)
    guardar_config(cfg, config)

    ui.msg("=== RESULTADO ===")
    total = 0.0
    for ruta, nf, kg, por_d in res.archivos:
        total += kg
        ui.msg(f"{ruta.name}: {nf} filas, {kg:,.0f} kg  ("
               + ", ".join(f"Ø{k}: {v:,.0f}" for k, v in por_d.items()) + ")")
    ui.msg(f"Total: {total:,.0f} kg")
    if res.pendientes:
        ui.msg(f"ATENCIÓN: {res.pendientes} partidas sin cantidad o fuera de los ciclos; "
               f"revise la hoja 'Pendientes' de {res.revision.name}")
    ui.msg(f"Archivos guardados en: {carpeta}")
    if sys.platform == "win32":
        try:
            os.startfile(carpeta)  # type: ignore[attr-defined]
        except OSError:
            pass
    return 0
