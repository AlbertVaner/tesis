r"""Laminas del vocabulario de cuerpo: gestos dinamicos y gestos estaticos.

Dos figuras con el mismo lenguaje que `esquema_cadenas_control.py`: celdas
numeradas, solo el nombre del gesto, la paleta de las laminas de gestos y el
operador como esqueleto. El pie de figura lo pone el documento.

* **Dinamicos** (`senalero`, `aplaudir`, `ven_aca`, `arco`, `circulo`): el
  recorrido en papel cebolla y la estela de las munecas, de frente y de
  perfil. Las coordenadas salen de las tomas grabadas, con el medoide DTW de
  cada gesto, igual que en
  `external/gesture_detection/visualization/esquema_gestos_dinamicos.py`, de
  donde se reutilizan la seleccion y el dibujo.
* **Estaticos** (`ARRIBA` ... `DERECHA` y el paro con la X sobre la cabeza):
  una postura por celda, de frente y de perfil, con el dron y el sentido en
  que se mueve. Las posturas son sinteticas, construidas en el marco del
  cuerpo con las direcciones **medidas** de
  `recognition/body_3d_rules.DIRECCIONES` y la geometria de
  `recognition/paro_estatico.py`; no hay tomas grabadas de esas posturas.

Uso, desde la raiz del repositorio:

    python .\thesis\figuras\esquema_gestos.py
    python .\thesis\figuras\esquema_gestos.py --lamina estaticos

Sale PNG a 300 ppp y PDF vectorial en `results/graphs/esquemas_gestos/<hoy>/`.
No abre camara, ni radio, ni controladores.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import numpy as np

FIGURAS_DIR = Path(__file__).resolve().parent
PROJECT_DIR = FIGURAS_DIR.parents[1]
GESTURE_DIR = PROJECT_DIR / "external" / "gesture_detection"
for ruta in (FIGURAS_DIR, GESTURE_DIR, GESTURE_DIR / "visualization"):
    if str(ruta) not in sys.path:
        sys.path.insert(0, str(ruta))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import FancyArrowPatch, Rectangle, RegularPolygon  # noqa: E402

from esquema_cadenas_control import (  # noqa: E402
    ACENTO,
    BORDE,
    GRIS,
    MUNECA_DER,
    MUNECA_IZQ,
    NUMERO,
    SECUNDARIO,
    TINTA,
    _dron,
    _linea,
    _punta,
)
import esquema_gestos_dinamicos as dinamicos  # noqa: E402
from construir_plantillas import CARPETAS_VOCABULARIO  # noqa: E402
from contracts import Gesture  # noqa: E402
from pose.normalize import (  # noqa: E402
    LEFT_ELBOW,
    LEFT_HIP,
    LEFT_SHOULDER,
    LEFT_WRIST,
    RIGHT_ELBOW,
    RIGHT_HIP,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
)
from recognition.body_3d_rules import DIRECCIONES  # noqa: E402

NOSE = 0

#: Rejilla en pulgadas. Dos columnas, como la lamina de gestos dinamicos.
COLUMNAS = 2
CELDA_ANCHO_IN = 4.75
SEPARACION_IN = 0.18
MARGEN_IN = 0.30
CABECERA_IN = 0.30
PIE_IN = 0.30
NOMBRE_ALTO_IN = 0.55        # banda del nombre bajo las vistas
BANDA_ALTO_IN = 2.05         # alto disponible para las vistas
HUECO_VISTAS_IN = 0.25


# ------------------------------------------------------------ estaticos

#: Proporciones del esqueleto en el marco del cuerpo (origen en la cadera,
#: unidades de torso): hombros a 1.0 de altura, nariz a 1.30, brazo de 1.05.
#: Son las medidas que usan `body_3d_rules` y `paro_estatico`.
HOMBRO_Y, NARIZ_Y, MEDIO_HOMBRO, MEDIO_CADERA = 1.00, 1.30, 0.42, 0.28
BRAZO, ANTEBRAZO = 0.52, 0.53

#: Catalogo de posturas estaticas, en el orden de la lamina. Las seis
#: direcciones son las de `DIRECCIONES` (una por brazo extendido; el otro
#: cuelga) y el paro es la X sobre la cabeza de `paro_estatico`. La flecha del
#: dron es el sentido en que se mueve, en la vista del panel del dron.
ESTATICOS = (
    ("ARRIBA", Gesture.ARRIBA, "der", (0, 1)),
    ("ABAJO", Gesture.ABAJO, "der", (0, -1)),
    ("ADELANTE", Gesture.ADELANTE, "der", (0.62, 0.62)),
    ("ATRÁS", Gesture.ATRAS, "der", (-0.62, -0.62)),
    ("IZQUIERDA", Gesture.IZQUIERDA, "izq", (-1, 0)),
    ("DERECHA", Gesture.DERECHA, "der", (1, 0)),
    ("PARO", None, None, None),
)


def _esqueleto_base() -> np.ndarray:
    P = np.full((33, 3), np.nan)
    P[NOSE] = (0.0, NARIZ_Y, 0.06)
    P[LEFT_SHOULDER] = (MEDIO_HOMBRO, HOMBRO_Y, 0.0)
    P[RIGHT_SHOULDER] = (-MEDIO_HOMBRO, HOMBRO_Y, 0.0)
    P[LEFT_HIP] = (MEDIO_CADERA, 0.0, 0.0)
    P[RIGHT_HIP] = (-MEDIO_CADERA, 0.0, 0.0)
    return P


def _indices(lado: str) -> tuple[int, int, int]:
    if lado == "izq":
        return LEFT_SHOULDER, LEFT_ELBOW, LEFT_WRIST
    return RIGHT_SHOULDER, RIGHT_ELBOW, RIGHT_WRIST


def _colgar(P: np.ndarray, lado: str) -> None:
    s = 1 if lado == "izq" else -1
    hombro, codo, muneca = _indices(lado)
    P[codo] = P[hombro] + (s * 0.08, -BRAZO, 0.02)
    P[muneca] = P[codo] + (s * 0.03, -ANTEBRAZO, 0.04)


def postura(gesto: Gesture | None, brazo: str | None) -> np.ndarray:
    """Pose `(33, 3)` de la postura, en el marco del cuerpo."""
    P = _esqueleto_base()
    if gesto is None:
        # X sobre la cabeza: munecas por encima de la nariz, cruzadas y juntas
        # (`paro_estatico`: cruce >= 0.10, separacion <= 0.60).
        # Los antebrazos se cruzan a la altura de la frente y las munecas
        # asoman al otro lado: asi la X se lee como X y no como un pico.
        P[RIGHT_ELBOW] = (-0.60, 1.55, 0.06)
        P[LEFT_ELBOW] = (0.60, 1.55, 0.06)
        P[RIGHT_WRIST] = (0.28, 1.95, 0.10)
        P[LEFT_WRIST] = (-0.28, 1.95, 0.10)
        return P
    d = np.asarray(DIRECCIONES[gesto], dtype=float)
    d /= np.linalg.norm(d)
    hombro, codo, muneca = _indices(brazo)
    s = 1 if brazo == "izq" else -1
    if gesto is Gesture.ATRAS:
        # El hombro no da la extension: el codo se dobla y se abre al costado
        # (medido en `body_3d_rules`, seccion ATRAS).
        P[codo] = P[hombro] + BRAZO * d + (s * 0.16, 0.06, 0.0)
        P[muneca] = P[hombro] + 0.85 * d + (s * 0.10, 0.0, 0.0)
    else:
        P[codo] = P[hombro] + BRAZO * d
        P[muneca] = P[hombro] + (BRAZO + ANTEBRAZO) * d
    _colgar(P, "der" if brazo == "izq" else "izq")
    return P


def dibujar_postura(ax, P: np.ndarray, vista: str, brazo: str | None,
                    limites) -> None:
    ax.set_aspect("equal", adjustable="box")
    ax.axis("off")
    ax.set_title("de frente" if vista == "frente" else "de perfil",
                 fontsize=8.5, color=SECUNDARIO, pad=1)
    Q = dinamicos._proyectar(P, vista)
    for a, b in dinamicos.HUESOS:
        _linea(ax, [Q[a, 0], Q[b, 0]], [Q[a, 1], Q[b, 1]], lw=1.9)
    cuello = dinamicos._cuello(Q)
    if cuello is not None:
        _linea(ax, *cuello, lw=1.9)
    ax.plot(Q[NOSE, 0], Q[NOSE, 1], "o", color=TINTA, markersize=5.5, zorder=4)
    # La muneca que senala, con el color de su lado; en la X, las dos.
    lados = (("der", RIGHT_WRIST, MUNECA_DER), ("izq", LEFT_WRIST, MUNECA_IZQ))
    for lado, indice, color in lados:
        if brazo is None or brazo == lado:
            ax.plot(Q[indice, 0], Q[indice, 1], "o", color=color, markersize=5,
                    markerfacecolor="white", markeredgewidth=1.6, zorder=5)
    ax.set_xlim(limites[0], limites[1])
    ax.set_ylim(limites[2], limites[3])


def dibujar_dron(ax, flecha) -> None:
    """Panel del dron: hacia donde se mueve, o el paro."""
    ax.set_aspect("equal", adjustable="box")
    ax.axis("off")
    ax.set_title("dron", fontsize=8.5, color=SECUNDARIO, pad=1)
    ax.set_xlim(-1, 1)
    ax.set_ylim(-1, 1)
    if flecha is None:
        _dron(ax, -0.22, -0.05, s=1.15)
        ax.add_patch(RegularPolygon((0.62, 0.05), 8, radius=0.30,
                                    orientation=np.pi / 8, facecolor="white",
                                    edgecolor=ACENTO, linewidth=2.0, zorder=4))
        _linea(ax, [0.50, 0.74], [0.05, 0.05], ACENTO, 2.4, z=5)
        return
    fx, fy = flecha
    _dron(ax, -0.18 * fx, -0.18 * fy, s=1.15)
    p0 = np.array([0.32 * fx, 0.30 * fy])
    p1 = np.array([0.90 * fx, 0.88 * fy])
    _linea(ax, [p0[0], p1[0] - 0.12 * fx], [p0[1], p1[1] - 0.12 * fy],
           ACENTO, 2.4, z=5)
    _punta(ax, p0, p1, ACENTO, escala=16, z=6)


# --------------------------------------------------------------- celdas


def _marco(fig, nx, ny, x0, y0, ch, numero) -> None:
    fig.patches.append(Rectangle(
        (nx(x0), ny(y0)), nx(CELDA_ANCHO_IN), ny(ch), transform=fig.transFigure,
        facecolor="white", edgecolor=BORDE, linewidth=0.8, zorder=0))
    fig.text(nx(x0 + 0.10), ny(y0 + ch - 0.22), f"{numero:02d}", fontsize=9,
             fontweight="bold", color=NUMERO)


def _nombre(fig, nx, ny, x0, y0, nombre) -> None:
    fig.text(nx(x0 + CELDA_ANCHO_IN / 2), ny(y0 + NOMBRE_ALTO_IN / 2), nombre,
             ha="center", va="center", fontsize=13.5, fontweight="bold",
             color=TINTA)


def _escala(limites: dict, paneles_extra_u: float = 0.0) -> float:
    """Pulgadas por unidad de torso, comun a todas las vistas y celdas."""
    alto = max(l[3] - l[2] for l in limites.values())
    anchos = sum(l[1] - l[0] for l in limites.values()) + paneles_extra_u
    n_paneles = len(limites) + (1 if paneles_extra_u else 0)
    disponible = CELDA_ANCHO_IN - 0.40 - HUECO_VISTAS_IN * (n_paneles - 1)
    return min(BANDA_ALTO_IN / alto, disponible / anchos)


def _limites_comunes(poses_por_vista: dict, margen: float = 0.12) -> dict:
    limites = {}
    for vista, puntos in poses_por_vista.items():
        todos = np.vstack(puntos)
        # Mas aire arriba: ahi va el rotulo de la vista y el brazo en ARRIBA.
        limites[vista] = [todos[:, 0].min() - margen, todos[:, 0].max() + margen,
                          todos[:, 1].min() - margen, todos[:, 1].max() + 2.2 * margen]
    y0 = min(l[2] for l in limites.values())
    y1 = max(l[3] for l in limites.values())
    return {v: (l[0], l[1], y0, y1) for v, l in limites.items()}


def _lamina(n_celdas: int, alto_vistas: float, destino: Path, clave: str,
            pintar_celda, pintar_leyenda) -> tuple[Path, Path]:
    filas = (n_celdas + 1 + COLUMNAS - 1) // COLUMNAS      # +1: la leyenda
    celda_alto = alto_vistas + NOMBRE_ALTO_IN + 0.40
    W = 2 * MARGEN_IN + COLUMNAS * CELDA_ANCHO_IN + (COLUMNAS - 1) * SEPARACION_IN
    H = CABECERA_IN + filas * celda_alto + (filas - 1) * SEPARACION_IN + PIE_IN
    fig = plt.figure(figsize=(W, H))
    fig.patch.set_facecolor("white")

    def nx(x):
        return x / W

    def ny(y):
        return y / H

    for k in range(n_celdas + 1):
        fila, col = divmod(k, COLUMNAS)
        x0 = MARGEN_IN + col * (CELDA_ANCHO_IN + SEPARACION_IN)
        y0 = H - CABECERA_IN - (fila + 1) * celda_alto - fila * SEPARACION_IN
        if k < n_celdas:
            _marco(fig, nx, ny, x0, y0, celda_alto, k + 1)
            pintar_celda(fig, nx, ny, x0, y0, celda_alto, k)
        else:
            pintar_leyenda(fig, nx, ny, x0, y0, celda_alto)

    destino.mkdir(parents=True, exist_ok=True)
    base = destino / clave
    png, pdf = base.with_suffix(".png"), base.with_suffix(".pdf")
    fig.savefig(png, dpi=300, facecolor="white")
    fig.savefig(pdf, facecolor="white")
    plt.close(fig)
    return png, pdf


def _leyenda(fig, nx, ny, x0, y0, ch, entradas) -> None:
    fig.text(nx(x0 + 0.10), ny(y0 + ch - 0.22), "LECTURA", fontsize=9,
             fontweight="bold", color=NUMERO)
    for k, (handle, texto) in enumerate(entradas):
        y = y0 + ch - 0.62 - 0.36 * k
        handle(fig, nx, ny, x0 + 0.20, y)
        fig.text(nx(x0 + 0.72), ny(y), texto, fontsize=9, color=SECUNDARIO,
                 va="center")


def _trazo(color, alpha=1.0, ls="-"):
    def pintar(fig, nx, ny, x, y):
        fig.lines.append(Line2D([nx(x), nx(x + 0.40)], [ny(y), ny(y)],
                                transform=fig.transFigure, color=color, lw=2,
                                alpha=alpha, linestyle=ls))
    return pintar


def _marcador(color):
    def pintar(fig, nx, ny, x, y):
        fig.lines.append(Line2D([nx(x + 0.20)], [ny(y)], transform=fig.transFigure,
                                marker="o", color=color, markersize=6,
                                markerfacecolor="white", markeredgewidth=1.6,
                                linestyle="none"))
    return pintar


def _flecha_acento(fig, nx, ny, x, y):
    fig.patches.append(FancyArrowPatch(
        (nx(x), ny(y)), (nx(x + 0.42), ny(y)), transform=fig.transFigure,
        arrowstyle="-|>", mutation_scale=14, color=ACENTO, linewidth=2))


def _octagono(fig, nx, ny, x, y):
    fig.patches.append(RegularPolygon(
        (nx(x + 0.20), ny(y)), 8, radius=0.075 / 10.0, orientation=np.pi / 8,
        transform=fig.transFigure, facecolor="white", edgecolor=ACENTO,
        linewidth=1.8))


# ------------------------------------------------------------ dinamicos


def lamina_dinamicos(destino: Path, carpetas: list[Path]) -> tuple[Path, Path]:
    tomas = dinamicos.cargar_vocabulario(carpetas)
    if not tomas:
        raise SystemExit(f"No hay tomas en {', '.join(str(c) for c in carpetas)}.")
    seleccion = []
    for clave, nombre, como, accion in dinamicos.CATALOGO:
        toma, _ = dinamicos.toma_representativa(tomas, clave)
        poses, tiempos = dinamicos.recorrido(toma)
        seleccion.append((clave, nombre, como, accion, poses, tiempos))
        print(f"  {clave:9s} toma de {toma.persona}")

    vistas = ("frente", "perfil")
    limites = {v: dinamicos.extension(seleccion, v) for v in vistas}
    y0c = min(limites[v][2] for v in vistas)
    y1c = max(limites[v][3] for v in vistas)
    limites = {v: (l[0], l[1], y0c, y1c) for v, l in limites.items()}
    escala = _escala(limites)
    cajas = {v: ((l[1] - l[0]) * escala, (l[3] - l[2]) * escala)
             for v, l in limites.items()}
    alto_vistas = max(c[1] for c in cajas.values())

    def celda(fig, nx, ny, x0, y0, ch, k):
        _, nombre, _, _, poses, _ = seleccion[k]
        ancho_total = sum(cajas[v][0] for v in vistas) + HUECO_VISTAS_IN
        cursor = x0 + (CELDA_ANCHO_IN - ancho_total) / 2
        base = y0 + NOMBRE_ALTO_IN + 0.06
        for vista in vistas:
            w, h = cajas[vista]
            ax = fig.add_axes([nx(cursor), ny(base), nx(w), ny(h)])
            ax.set_zorder(4)
            dinamicos.dibujar_vista(
                ax, poses, vista,
                "de frente" if vista == "frente" else "de perfil",
                limites[vista])
            cursor += w + HUECO_VISTAS_IN
        _nombre(fig, nx, ny, x0, y0, nombre)

    def leyenda(fig, nx, ny, x0, y0, ch):
        _leyenda(fig, nx, ny, x0, y0, ch, (
            (_trazo(MUNECA_DER), "estela de la muñeca derecha"),
            (_trazo(MUNECA_IZQ), "estela de la muñeca izquierda"),
            (_marcador(GRIS), "donde empieza la estela; la punta, donde acaba"),
            (_trazo(TINTA, alpha=0.22), "esqueleto al empezar el gesto"),
            (_trazo(TINTA), "esqueleto al terminar"),
        ))

    return _lamina(len(seleccion), alto_vistas, destino, "gestos_dinamicos",
                   celda, leyenda)


# ------------------------------------------------------------ estaticos


def lamina_estaticos(destino: Path) -> tuple[Path, Path]:
    items = [(nombre, postura(g, brazo), brazo, flecha)
             for nombre, g, brazo, flecha in ESTATICOS]
    vistas = ("frente", "perfil")
    puntos = {v: [] for v in vistas}
    for _, P, _, _ in items:
        for v in vistas:
            Q = dinamicos._proyectar(P, v)[list(dinamicos.DIBUJADOS)]
            puntos[v].append(Q[np.all(np.isfinite(Q), axis=1)])
    limites = _limites_comunes(puntos)
    # El panel del dron es cuadrado y mide lo que la vista mas alta.
    alto_u = limites["frente"][3] - limites["frente"][2]
    escala = _escala(limites, paneles_extra_u=alto_u)
    cajas = {v: ((l[1] - l[0]) * escala, (l[3] - l[2]) * escala)
             for v, l in limites.items()}
    lado_dron = alto_u * escala
    alto_vistas = lado_dron

    def celda(fig, nx, ny, x0, y0, ch, k):
        nombre, P, brazo, flecha = items[k]
        ancho_total = (sum(cajas[v][0] for v in vistas) + lado_dron
                       + 2 * HUECO_VISTAS_IN)
        cursor = x0 + (CELDA_ANCHO_IN - ancho_total) / 2
        base = y0 + NOMBRE_ALTO_IN + 0.06
        for vista in vistas:
            w, h = cajas[vista]
            ax = fig.add_axes([nx(cursor), ny(base), nx(w), ny(h)])
            ax.set_zorder(4)
            dibujar_postura(ax, P, vista, brazo, limites[vista])
            cursor += w + HUECO_VISTAS_IN
        ax = fig.add_axes([nx(cursor), ny(base), nx(lado_dron), ny(lado_dron)])
        ax.set_zorder(4)
        dibujar_dron(ax, flecha)
        _nombre(fig, nx, ny, x0, y0, nombre)

    def leyenda(fig, nx, ny, x0, y0, ch):
        _leyenda(fig, nx, ny, x0, y0, ch, (
            (_marcador(MUNECA_DER), "muñeca derecha que señala"),
            (_marcador(MUNECA_IZQ), "muñeca izquierda que señala"),
            (_flecha_acento, "sentido en que se mueve el dron"),
            (_octagono, "el dron frena; sostenido, aterriza"),
        ))

    return _lamina(len(items), alto_vistas, destino, "gestos_estaticos",
                   celda, leyenda)


# ------------------------------------------------------------------ main


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Laminas del vocabulario de cuerpo: dinamicos y estaticos")
    parser.add_argument("--lamina", choices=("dinamicos", "estaticos"),
                        help="solo una; por defecto, las dos")
    parser.add_argument("--carpeta", nargs="+",
                        help="carpetas de tomas para los dinamicos; "
                             "por defecto las del vocabulario")
    parser.add_argument("--salida", help="carpeta de destino")
    args = parser.parse_args()

    destino = (Path(args.salida) if args.salida
               else PROJECT_DIR / "results" / "graphs" / "esquemas_gestos"
               / date.today().isoformat())
    carpetas = ([Path(c) for c in args.carpeta] if args.carpeta
                else [PROJECT_DIR / "results" / "data" / "gestos" / fecha
                      for fecha in CARPETAS_VOCABULARIO])

    if args.lamina in (None, "dinamicos"):
        png, pdf = lamina_dinamicos(destino, carpetas)
        print(f"PNG: {png}\nPDF: {pdf}")
    if args.lamina in (None, "estaticos"):
        png, pdf = lamina_estaticos(destino)
        print(f"PNG: {png}\nPDF: {pdf}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
