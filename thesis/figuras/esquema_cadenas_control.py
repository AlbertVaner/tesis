r"""Laminas de la cadena de control y del flujo de realimentacion externa.

Sustituyen a los dos diagramas de cajas del documento (`cadena_principal_control`
y `Flujo_realimentacion_externa`). Dicen lo mismo, con el lenguaje grafico de
`external/gesture_detection/visualization/esquema_gestos_dinamicos.py`: celdas
numeradas, pictogramas de trazo, la misma paleta y el operador dibujado como el
esqueleto de las laminas de gestos, para que todas las figuras se lean como del
mismo trabajo.

Anaden una sola cosa a los originales: las etapas se agrupan en **en tierra** y
**a bordo del Crazyflie**, y el salto de una fila a la otra es el enlace de radio.
Por eso el flujo de realimentacion incluye la Crazyradio, que el diagrama
original omitia: la posicion externa tambien cruza por ella.

Uso, desde la raiz del repositorio:

    python .\thesis\figuras\esquema_cadenas_control.py
    python .\thesis\figuras\esquema_cadenas_control.py --salida .\thesis\figuras\salida

Sale PNG a 300 ppp y PDF vectorial en `results/graphs/esquemas_control/<hoy>/`.

Es solo dibujo: no importa controladores, ni abre camara, radio ni broker.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import numpy as np

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import (  # noqa: E402
    Circle,
    Ellipse,
    FancyArrowPatch,
    FancyBboxPatch,
    Polygon,
    Rectangle,
)

PROJECT_DIR = Path(__file__).resolve().parents[2]

#: Paleta. Es la de `esquema_gestos_dinamicos.py` y `esquema_gestos_mano.m`.
TINTA = (0.10, 0.16, 0.22)
GRIS = (0.60, 0.65, 0.69)
ACENTO = (0.85, 0.33, 0.10)
ACENTO_TEXTO = tuple(0.85 * c for c in ACENTO)
MUNECA_DER = (0.12, 0.44, 0.73)
MUNECA_IZQ = (0.78, 0.12, 0.32)
BORDE = (0.85, 0.88, 0.90)
SECUNDARIO = (0.30, 0.35, 0.39)
NUMERO = (0.45, 0.50, 0.55)
BANDA = (0.965, 0.972, 0.978)

#: Rejilla en pulgadas, como las otras laminas.
COLUMNAS = 4
CELDA_ANCHO_IN = 1.95
CELDA_ALTO_IN = 1.98
HUECO_IN = 0.62          # entre celdas de una fila: ahi va la flecha y su rotulo
CANAL_IN = 0.95          # entre las dos filas: ahi va el enlace de radio
MARGEN_IN = 0.30
CABECERA_IN = 0.22
PIE_IN = 0.30
ROTULO_FILA_IN = 0.30    # rotulo "EN TIERRA" / "A BORDO" encima de cada fila

#: Caja del pictograma dentro de la celda, en pulgadas.
PICTO_ANCHO_IN = 1.55
PICTO_ALTO_IN = 1.12

LW = 1.7


# ------------------------------------------------------------- pictogramas
#
# Cada pictograma dibuja en un eje de -1.38..1.38 por -1..1 (la proporcion de
# la caja), con `aspect=equal`. Solo trazo, extremos redondos, y el acento
# reservado para lo que la etapa *entrega*.


def _linea(ax, xs, ys, color=TINTA, lw=LW, alpha=1.0, ls="-", z=3):
    ax.plot(xs, ys, color=color, linewidth=lw, alpha=alpha, linestyle=ls,
            solid_capstyle="round", solid_joinstyle="round",
            dash_capstyle="round", zorder=z)


def _punta(ax, p0, p1, color, escala=11, z=5):
    ax.annotate("", xy=p1, xytext=p0, zorder=z,
                arrowprops=dict(arrowstyle="-|>", color=color, linewidth=0,
                                mutation_scale=escala, shrinkA=0, shrinkB=0))


def _dron(ax, cx, cy, s=1.0, color=TINTA, lw=LW, z=3):
    """El dron de `esquema_gestos_mano.m`: brazos en X y cuatro rotores."""
    dx, dy = 0.34 * s, 0.17 * s
    for sx, sy in ((-1, -1), (-1, 1), (1, -1), (1, 1)):
        _linea(ax, [cx, cx + sx * dx], [cy, cy + sy * dy], color, lw, z=z)
        ax.add_patch(Ellipse((cx + sx * dx, cy + sy * dy), 0.36 * s, 0.15 * s,
                             facecolor="white", edgecolor=color, linewidth=lw,
                             zorder=z + 1))
    ax.add_patch(Rectangle((cx - 0.085 * s, cy - 0.06 * s), 0.17 * s, 0.12 * s,
                           facecolor=color, edgecolor=color, zorder=z + 2))


def _ondas(ax, cx, cy, radios, angulo0, angulo1, color=ACENTO, lw=LW):
    for r in radios:
        t = np.radians(np.linspace(angulo0, angulo1, 24))
        _linea(ax, cx + r * np.cos(t), cy + r * np.sin(t), color, lw, z=4)


def picto_operador(ax):
    """El monigote de la lamina de gestos, con el brazo en papel cebolla."""
    # El brazo y su estela ocupan el lado izquierdo: el tronco va desplazado a
    # la derecha para que el conjunto quede centrado en la caja.
    ox = 0.30
    hombro_d, hombro_i = np.array([ox - 0.30, 0.22]), np.array([ox + 0.30, 0.22])
    cadera_d, cadera_i = np.array([ox - 0.20, -0.78]), np.array([ox + 0.20, -0.78])
    cuerpo = [(hombro_d, hombro_i), (cadera_d, cadera_i),
              (hombro_d, cadera_d), (hombro_i, cadera_i)]
    for a, b in cuerpo:
        _linea(ax, [a[0], b[0]], [a[1], b[1]], lw=1.9)
    _linea(ax, [ox, ox + 0.02], [0.22, 0.62], lw=1.9)
    ax.plot(ox + 0.02, 0.62, "o", color=TINTA, markersize=5.5, zorder=4)
    # Brazo izquierdo del operador (a la derecha de la hoja), en reposo.
    _linea(ax, [ox + 0.30, ox + 0.40, ox + 0.44], [0.22, -0.24, -0.70], lw=1.9)
    ax.plot(ox + 0.44, -0.70, "o", color=MUNECA_IZQ, markersize=4.2,
            markerfacecolor="white", markeredgewidth=1.3, zorder=5)

    # Brazo derecho: tres instantes, del mas claro al mas oscuro.
    angulos = np.radians([-62, 8, 58])
    munecas = []
    for k, ang in enumerate(angulos):
        alfa = 0.20 + 0.80 * k / 2
        codo = hombro_d + 0.46 * np.array([-np.cos(ang * 0.55 - 0.35),
                                           np.sin(ang * 0.55 - 0.35)])
        muneca = codo + 0.46 * np.array([-np.cos(ang), np.sin(ang)])
        munecas.append(muneca)
        _linea(ax, [hombro_d[0], codo[0], muneca[0]],
               [hombro_d[1], codo[1], muneca[1]], lw=1.9, alpha=alfa)
    # Estela de la muneca, que es lo que el reconocedor compara.
    t = np.linspace(0, 1, 40)
    ang = np.radians(-62 + 120 * t)
    codo = hombro_d[None, :] + 0.46 * np.column_stack(
        [-np.cos(ang * 0.55 - 0.35), np.sin(ang * 0.55 - 0.35)])
    T = codo + 0.46 * np.column_stack([-np.cos(ang), np.sin(ang)])
    T = T + 0.11 * (T - hombro_d) / np.linalg.norm(T - hombro_d, axis=1)[:, None]
    _linea(ax, T[:, 0], T[:, 1], MUNECA_DER, 1.7, alpha=0.9, z=4)
    ax.plot(T[0, 0], T[0, 1], "o", color=MUNECA_DER, markersize=4.2,
            markerfacecolor="white", markeredgewidth=1.3, zorder=5)
    _punta(ax, T[-3], T[-1], MUNECA_DER, escala=12)


def picto_interfaz(ax):
    """Ventana con la vista de camara y los botones de orden."""
    ax.add_patch(FancyBboxPatch((-1.05, -0.78), 2.10, 1.56,
                                boxstyle="round,pad=0,rounding_size=0.08",
                                facecolor="white", edgecolor=TINTA,
                                linewidth=LW, zorder=2))
    _linea(ax, [-1.05, 1.05], [0.50, 0.50])
    for k in range(3):
        ax.add_patch(Circle((-0.88 + 0.17 * k, 0.64), 0.045, facecolor=GRIS,
                            edgecolor="none", zorder=4))
    # Vista de camara con un esqueleto diminuto.
    ax.add_patch(Rectangle((-0.90, -0.62), 0.92, 0.98, facecolor=BANDA,
                           edgecolor=GRIS, linewidth=1.0, zorder=3))
    cx, cy = -0.44, -0.20
    for xs, ys in (([-0.13, 0.13], [0.16, 0.16]), ([-0.09, 0.09], [-0.26, -0.26]),
                   ([-0.13, -0.09], [0.16, -0.26]), ([0.13, 0.09], [0.16, -0.26]),
                   ([0, 0], [0.16, 0.33]),
                   ([-0.13, -0.30, -0.36], [0.16, 0.26, 0.46]),
                   ([0.13, 0.19, 0.21], [0.16, -0.04, -0.22])):
        _linea(ax, cx + np.array(xs), cy + np.array(ys), lw=1.2, z=4)
    ax.plot(cx, cy + 0.34, "o", color=TINTA, markersize=3.0, zorder=5)
    # Botones; el activo, en acento.
    for fila in range(3):
        for col in range(2):
            activo = (fila, col) == (0, 1)
            ax.add_patch(FancyBboxPatch(
                (0.20 + 0.40 * col, 0.12 - 0.37 * fila), 0.30, 0.24,
                boxstyle="round,pad=0,rounding_size=0.05",
                facecolor=ACENTO if activo else "white",
                edgecolor=ACENTO if activo else TINTA, linewidth=1.2, zorder=4))


def picto_seguridad(ax):
    """Escudo: lo que pasa por aqui sale acotado."""
    y = np.array([0.80, 0.62, 0.05, -0.42, -0.84])
    x = np.array([0.0, 0.62, 0.62, 0.40, 0.0])
    xs = np.concatenate([x, -x[-2::-1]])
    ys = np.concatenate([y, y[-2::-1]])
    ax.add_patch(Polygon(np.column_stack([xs, ys]), closed=True,
                         facecolor="white", edgecolor=TINTA, linewidth=LW,
                         joinstyle="round", zorder=3))
    _linea(ax, [-0.27, -0.06, 0.30], [0.02, -0.22, 0.30], ACENTO, 2.6, z=4)
    # Cotas a los lados: los limites de altura y velocidad.
    for sx in (-1, 1):
        _linea(ax, [sx * 0.98, sx * 0.98], [-0.55, 0.55], GRIS, 1.1)
        for yy in (-0.55, 0.55):
            _linea(ax, [sx * 0.90, sx * 1.06], [yy, yy], GRIS, 1.1)


def picto_radio(ax):
    """Crazyradio: dongle USB con antena."""
    ax.add_patch(Rectangle((-1.12, -0.42), 0.34, 0.40, facecolor="white",
                           edgecolor=TINTA, linewidth=LW, zorder=3))
    for yy in (-0.30, -0.14):
        ax.add_patch(Rectangle((-1.03, yy - 0.035), 0.12, 0.07, facecolor=GRIS,
                               edgecolor="none", zorder=4))
    ax.add_patch(FancyBboxPatch((-0.78, -0.52), 1.10, 0.60,
                                boxstyle="round,pad=0,rounding_size=0.07",
                                facecolor="white", edgecolor=TINTA,
                                linewidth=LW, zorder=3))
    ax.add_patch(Circle((-0.55, -0.22), 0.05, facecolor=ACENTO,
                        edgecolor="none", zorder=4))
    _linea(ax, [0.32, 0.50, 0.50], [-0.22, -0.22, 0.62], lw=2.2)
    ax.plot(0.50, 0.62, "o", color=TINTA, markersize=4.5, zorder=4)
    _ondas(ax, 0.50, 0.62, (0.24, 0.43, 0.62), -42, 42)


def picto_highlevel(ax):
    """Trayectoria planificada: despegar, trasladarse, aterrizar."""
    _linea(ax, [-1.20, 1.20], [-0.70, -0.70], GRIS, 1.2)
    for x in np.arange(-1.10, 1.21, 0.22):
        _linea(ax, [x, x - 0.09], [-0.70, -0.82], GRIS, 1.0)
    t = np.linspace(0, 1, 60)
    suave = 3 * t**2 - 2 * t**3
    sube = np.column_stack([-0.85 + 0.0 * t, -0.70 + 1.02 * suave])
    cruza = np.column_stack([-0.85 + 1.70 * suave, 0.32 + 0.0 * t])
    baja = np.column_stack([0.85 + 0.0 * t, 0.32 - 1.02 * suave])
    ruta = np.vstack([sube, cruza, baja])
    _linea(ax, ruta[:, 0], ruta[:, 1], ACENTO, 1.6, ls=(0, (3.2, 2.6)), z=3)
    _punta(ax, (0.85, -0.50), (0.85, -0.68), ACENTO)
    for p in ((-0.85, -0.70), (-0.85, 0.32), (0.85, 0.32), (0.85, -0.70)):
        ax.plot(*p, "o", color=ACENTO, markersize=4.5, markerfacecolor="white",
                markeredgewidth=1.4, zorder=5)
    _dron(ax, 0.0, 0.38, s=0.95)


def picto_controlador(ax):
    """Microcontrolador con el lazo cerrado dentro."""
    ax.add_patch(FancyBboxPatch((-0.62, -0.62), 1.24, 1.24,
                                boxstyle="round,pad=0,rounding_size=0.08",
                                facecolor="white", edgecolor=TINTA,
                                linewidth=LW, zorder=3))
    for v in (-0.36, -0.12, 0.12, 0.36):
        for s in (-1, 1):
            _linea(ax, [s * 0.62, s * 0.84], [v, v], lw=1.4)
            _linea(ax, [v, v], [s * 0.62, s * 0.84], lw=1.4)
    # Lazo: un arco casi cerrado con punta, alrededor del nombre del regulador.
    ang = np.radians(np.linspace(60, 385, 70))
    _linea(ax, 0.40 * np.cos(ang), 0.40 * np.sin(ang), ACENTO, 1.8, z=4)
    _punta(ax, (0.40 * np.cos(ang[-4]), 0.40 * np.sin(ang[-4])),
           (0.40 * np.cos(ang[-1]), 0.40 * np.sin(ang[-1])), ACENTO, escala=12)
    ax.text(0, -0.01, "PID", ha="center", va="center", fontsize=8.5,
            fontweight="bold", color=TINTA, zorder=5)


def picto_motores(ax):
    """El dron con el empuje de sus cuatro rotores."""
    _dron(ax, 0.0, -0.38, s=1.75)
    for sx, sy in ((-1, -1), (-1, 1), (1, -1), (1, 1)):
        x, y = sx * 0.34 * 1.75, -0.38 + sy * 0.17 * 1.75
        largo = 0.40 if sy < 0 else 0.62
        _linea(ax, [x, x], [y + 0.04, y + largo - 0.16], ACENTO, 2.2, z=6)
        _punta(ax, (x, y + largo - 0.24), (x, y + largo), ACENTO, escala=13, z=6)


def picto_robotat(ax):
    """Camaras de captura de movimiento mirando al marker del dron."""
    _linea(ax, [-1.25, 1.25], [0.82, 0.82], GRIS, 1.2)
    objetivo = np.array([0.0, -0.42])
    for sx in (-1, 1):
        base = np.array([sx * 0.98, 0.62])
        d = (objetivo - base) / np.linalg.norm(objetivo - base)
        n = np.array([-d[1], d[0]])
        cuerpo = np.array([base - 0.13 * n - 0.17 * d, base + 0.13 * n - 0.17 * d,
                           base + 0.13 * n + 0.17 * d, base - 0.13 * n + 0.17 * d])
        _linea(ax, [base[0], base[0]], [0.82, 0.70], lw=1.3)
        ax.add_patch(Polygon(cuerpo, closed=True, facecolor="white",
                             edgecolor=TINTA, linewidth=LW, joinstyle="round",
                             zorder=4))
        lente = base + 0.17 * d
        ax.add_patch(Polygon(np.array([lente - 0.07 * n, lente + 0.07 * n,
                                       lente + 0.11 * n + 0.10 * d,
                                       lente - 0.11 * n + 0.10 * d]),
                             closed=True, facecolor=TINTA, edgecolor=TINTA,
                             linewidth=1.0, zorder=4))
        for giro in (-0.20, 0.20):
            c, s = np.cos(giro), np.sin(giro)
            r = np.array([c * d[0] - s * d[1], s * d[0] + c * d[1]])
            p0, p1 = lente + 0.14 * d, lente + 1.18 * r
            _linea(ax, [p0[0], p1[0]], [p0[1], p1[1]], MUNECA_DER, 1.0,
                   alpha=0.75, ls=(0, (2.5, 2.5)), z=2)
    _dron(ax, objetivo[0], objetivo[1] - 0.12, s=1.05)
    ax.plot(objetivo[0], objetivo[1] + 0.06, "o", color=ACENTO, markersize=5.5,
            markerfacecolor="white", markeredgewidth=1.7, zorder=7)


def picto_mqtt(ax):
    """Broker: uno publica, el broker reparte a los suscritos."""
    centro = np.array([0.0, 0.0])
    publica = np.array([-1.02, 0.0])
    suscritos = [np.array([1.02, 0.58]), np.array([1.02, 0.0]),
                 np.array([1.02, -0.58])]
    for k, p in enumerate([publica, *suscritos]):
        a, b = (p, centro) if k == 0 else (centro, p)
        d = (b - a) / np.linalg.norm(b - a)
        r_a, r_b = (0.17, 0.36) if k == 0 else (0.36, 0.17)
        p0, p1 = a + r_a * d, b - (r_b + 0.04) * d
        color = ACENTO if k in (0, 2) else GRIS
        _linea(ax, [p0[0], p1[0]], [p0[1], p1[1]], color, 1.5)
        _punta(ax, p1 - 0.12 * d, p1 + 0.03 * d, color, escala=10)
        ax.add_patch(Circle(p, 0.15, facecolor="white", edgecolor=TINTA,
                            linewidth=1.4, zorder=4))
    ax.add_patch(Circle(centro, 0.34, facecolor="white", edgecolor=TINTA,
                        linewidth=LW, zorder=4))
    # Mensajes en cola dentro del broker.
    for yy in (0.11, 0.0, -0.11):
        _linea(ax, [-0.16, 0.16], [yy, yy], lw=1.3, z=5)


def picto_computadora(ax):
    """Portatil con la pose que acaba de recibir."""
    ax.add_patch(FancyBboxPatch((-0.78, -0.40), 1.56, 1.10,
                                boxstyle="round,pad=0,rounding_size=0.07",
                                facecolor="white", edgecolor=TINTA,
                                linewidth=LW, zorder=3))
    ax.add_patch(Polygon(np.array([[-0.78, -0.48], [0.78, -0.48],
                                   [1.04, -0.74], [-1.04, -0.74]]),
                         closed=True, facecolor="white", edgecolor=TINTA,
                         linewidth=LW, joinstyle="round", zorder=3))
    _linea(ax, [-0.22, 0.22], [-0.63, -0.63], GRIS, 1.3)
    # Tres trazas: x, y, z llegando en el tiempo.
    t = np.linspace(-0.60, 0.60, 50)
    for k, (yy, color) in enumerate(((0.44, MUNECA_DER), (0.16, ACENTO),
                                     (-0.13, MUNECA_IZQ))):
        onda = 0.07 * np.sin(5.2 * t + 1.7 * k) + 0.03 * np.sin(11 * t + k)
        _linea(ax, t, yy + onda, color, 1.4, z=4)


def picto_extpos(ax):
    """El paquete: una cabecera y los campos de la posicion."""
    campos = (("x", 0.46), ("y", 0.46), ("z", 0.46), ("q", 0.46))
    x0, y0, alto = -1.10, -0.42, 0.62
    ax.add_patch(Rectangle((x0, y0), 0.36, alto, facecolor=TINTA,
                           edgecolor=TINTA, linewidth=LW, zorder=3))
    cursor = x0 + 0.36
    for nombre, ancho in campos:
        opcional = nombre == "q"
        ax.add_patch(Rectangle((cursor, y0), ancho, alto, facecolor="white",
                               edgecolor=GRIS if opcional else TINTA,
                               linewidth=1.2 if opcional else LW,
                               linestyle=(0, (2.5, 2)) if opcional else "-",
                               zorder=2 if opcional else 3))
        ax.text(cursor + ancho / 2, y0 + alto / 2 - 0.01, nombre, ha="center",
                va="center", fontsize=9.5, fontstyle="italic",
                color=GRIS if opcional else ACENTO_TEXTO,
                fontweight="bold", zorder=5)
        cursor += ancho
    # El paquete llega por radio: la marca va sobre la cabecera.
    _ondas(ax, -0.92, 0.42, (0.14, 0.27), 20, 160, lw=1.4)
    ax.plot(-0.92, 0.42, "o", color=ACENTO, markersize=3.2, zorder=4)


def picto_ekf(ax):
    """Prediccion ancha, medida, y la estimacion estrecha que sale."""
    _linea(ax, [-1.20, 1.20], [-0.70, -0.70], GRIS, 1.2)
    x = np.linspace(-1.15, 1.15, 160)

    def campana(mu, sigma, alto):
        return -0.70 + alto * np.exp(-0.5 * ((x - mu) / sigma) ** 2)

    _linea(ax, x, campana(-0.22, 0.46, 0.62), GRIS, 1.6, ls=(0, (3, 2.4)))
    _linea(ax, x, campana(0.34, 0.30, 0.86), MUNECA_DER, 1.5, alpha=0.9)
    y_est = campana(0.17, 0.16, 1.42)
    ax.fill_between(x, -0.70, y_est, color=ACENTO, alpha=0.10, zorder=2)
    _linea(ax, x, y_est, ACENTO, 2.0, z=4)
    _linea(ax, [0.17, 0.17], [-0.70, 0.72], ACENTO, 1.0, ls=(0, (2, 2)))
    ax.plot(0.34, -0.70, "o", color=MUNECA_DER, markersize=4.5,
            markerfacecolor="white", markeredgewidth=1.4, zorder=6)


# ------------------------------------------------------------------ laminas

#: `(pictograma, nombre, que hace, donde vive)` por etapa y, entre etapas, el
#: rotulo de lo que viaja. Las cuatro primeras van en tierra; el resto, a bordo.
LAMINAS = {
    "cadena_principal_control": dict(
        titulo="Cadena principal de control",
        subtitulo="De la orden del operador al empuje de los motores: "
                  "cada etapa entrega a la siguiente lo que rotula la flecha",
        etapas=(
            (picto_operador, "OPERADOR",
             "Da la orden con un gesto\no con una tecla.", "cámara · teclado"),
            (picto_interfaz, "INTERFAZ GRÁFICA",
             "Reconoce la orden y muestra\nel estado del vuelo.",
             "Python · Tk y OpenCV"),
            (picto_seguridad, "BACKEND DE\nSEGURIDAD",
             "Acota velocidad y altura\ny vigila la separación.",
             "Python · núcleo de vuelo"),
            (picto_radio, "CRAZYRADIO",
             "Enlaza la computadora\ncon el dron.", "cflib · USB a 2.4 GHz"),
            (picto_highlevel, "COMANDANTE\nHIGH-LEVEL",
             "Planifica despegue,\ntraslado y aterrizaje.", "firmware"),
            (picto_controlador, "CONTROLADOR\nEMBARCADO",
             "Cierra los lazos de posición,\nvelocidad y actitud.",
             "firmware · PID en cascada"),
            (picto_motores, "MOTORES",
             "Cuatro rotores convierten\nla señal en empuje.",
             "motores DC sin núcleo"),
        ),
        canal="enlace inalámbrico de 2.4 GHz: aquí la orden deja la computadora",
        enlaces=("gesto\no tecla", "orden", "orden\nacotada", "radio / CRTP",
                 "setpoints", "PWM"),
    ),
    "flujo_realimentacion_externa": dict(
        titulo="Flujo de realimentación externa",
        subtitulo="De las cámaras del Robotat al estimador del dron: "
                  "la posición la mide el laboratorio y el lazo lo cierra el firmware",
        etapas=(
            (picto_robotat, "ROBOTAT",
             "Seis cámaras infrarrojas\nmiden la pose del marker.",
             "OptiTrack · captura de mov."),
            (picto_mqtt, "MQTT",
             "El broker publica cada pose\nen el tópico del dron.",
             "publicar / suscribir"),
            (picto_computadora, "COMPUTADORA",
             "Descarta los frames repetidos\ny reenvía cada pose nueva.",
             "Python · mocap_feed"),
            (picto_radio, "CRAZYRADIO",
             "Enlaza la computadora\ncon el dron.", "cflib · USB a 2.4 GHz"),
            (picto_extpos, "EXTPOS",
             "Paquete de posición externa:\nx, y, z y orientación.",
             "CRTP · localización"),
            (picto_ekf, "EKF DEL\nCRAZYFLIE",
             "Funde la posición externa\ncon la IMU.",
             "firmware · filtro de Kalman"),
            (picto_controlador, "CONTROLADOR\nEMBARCADO",
             "Usa el estado estimado\npara cerrar el lazo.",
             "firmware · PID en cascada"),
        ),
        canal="el mismo enlace de la cadena de control, con cada frame nuevo del Robotat",
        enlaces=("pose /\nmocap", "mensajes", "posición\nexterna",
                 "radio / CRTP", "x, y, z", "estado\nestimado"),
    ),
}

EN_TIERRA = 4


def _celda(fig, nx, ny, x0, y0, numero, etapa) -> None:
    picto, nombre, que_hace, donde = etapa
    cw, ch = CELDA_ANCHO_IN, CELDA_ALTO_IN
    fig.patches.append(Rectangle(
        (nx(x0), ny(y0)), nx(cw), ny(ch), transform=fig.transFigure,
        facecolor="white", edgecolor=BORDE, linewidth=0.8, zorder=1))
    fig.text(nx(x0 + 0.09), ny(y0 + ch - 0.17), f"{numero:02d}", fontsize=8.5,
             fontweight="bold", color=NUMERO, va="center")

    ax = fig.add_axes([nx(x0 + (cw - PICTO_ANCHO_IN) / 2),
                       ny(y0 + ch - 0.16 - PICTO_ALTO_IN),
                       nx(PICTO_ANCHO_IN), ny(PICTO_ALTO_IN)])
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlim(-PICTO_ANCHO_IN / PICTO_ALTO_IN, PICTO_ANCHO_IN / PICTO_ALTO_IN)
    ax.set_ylim(-1, 1)
    ax.axis("off")
    ax.patch.set_alpha(0)
    # Por encima del rectangulo blanco de la celda, que es un artista de figura.
    ax.set_zorder(4)
    picto(ax)

    cx = x0 + cw / 2
    # El titulo de la figura y lo que hace cada etapa los pone el documento, en
    # el pie y en el texto; dentro de la celda solo queda el nombre. `que_hace`
    # y `donde` se conservan en `LAMINAS` como fuente para ese pie.
    fig.text(nx(cx), ny(y0 + 0.36), nombre, ha="center", va="center",
             fontsize=10.5, fontweight="bold", color=TINTA, linespacing=1.15)


def _flecha(fig, nx, ny, p0, p1, color=TINTA, lw=1.5):
    fig.patches.append(FancyArrowPatch(
        (nx(p0[0]), ny(p0[1])), (nx(p1[0]), ny(p1[1])),
        transform=fig.transFigure, arrowstyle="-|>", mutation_scale=13,
        color=color, linewidth=lw, shrinkA=0, shrinkB=0, zorder=6))


def lamina(clave: str, destino: Path) -> tuple[Path, Path]:
    spec = LAMINAS[clave]
    etapas, enlaces = spec["etapas"], spec["enlaces"]

    W = 2 * MARGEN_IN + COLUMNAS * CELDA_ANCHO_IN + (COLUMNAS - 1) * HUECO_IN
    H = (CABECERA_IN + 2 * (ROTULO_FILA_IN + CELDA_ALTO_IN) + CANAL_IN + PIE_IN)
    fig = plt.figure(figsize=(W, H))
    fig.patch.set_facecolor("white")

    def nx(x: float) -> float:
        return x / W

    def ny(y: float) -> float:
        return y / H

    y_fila = [H - CABECERA_IN - ROTULO_FILA_IN - CELDA_ALTO_IN]
    y_fila.append(y_fila[0] - CANAL_IN - ROTULO_FILA_IN - CELDA_ALTO_IN)

    def x_col(col: int) -> float:
        return MARGEN_IN + col * (CELDA_ANCHO_IN + HUECO_IN)

    # Banda y rotulo de cada fila: donde corre cada etapa.
    for fila, (rotulo, n) in enumerate((("EN TIERRA", EN_TIERRA),
                                        ("A BORDO DEL CRAZYFLIE",
                                         len(etapas) - EN_TIERRA))):
        ancho = n * CELDA_ANCHO_IN + (n - 1) * HUECO_IN + 0.24
        fig.patches.append(FancyBboxPatch(
            (nx(MARGEN_IN - 0.12), ny(y_fila[fila] - 0.12)), nx(ancho),
            ny(CELDA_ALTO_IN + ROTULO_FILA_IN + 0.16),
            boxstyle="round,pad=0,rounding_size=0.008",
            transform=fig.transFigure, facecolor=BANDA, edgecolor="none",
            zorder=0))
        fig.text(nx(MARGEN_IN + 0.02), ny(y_fila[fila] + CELDA_ALTO_IN + 0.15),
                 rotulo, fontsize=8, fontweight="bold", color=NUMERO,
                 va="center")

    posiciones = []
    for k, etapa in enumerate(etapas):
        fila, col = (0, k) if k < EN_TIERRA else (1, k - EN_TIERRA)
        x0, y0 = x_col(col), y_fila[fila]
        posiciones.append((x0, y0))
        _celda(fig, nx, ny, x0, y0, k + 1, etapa)

    # Flechas dentro de una fila, con el rotulo de lo que viaja encima.
    y_flecha = CELDA_ALTO_IN - 0.16 - PICTO_ALTO_IN / 2
    for k, rotulo in enumerate(enlaces):
        if k == EN_TIERRA - 1:
            continue
        x0, y0 = posiciones[k]
        xa, xb = x0 + CELDA_ANCHO_IN + 0.05, x0 + CELDA_ANCHO_IN + HUECO_IN - 0.05
        y = y0 + y_flecha
        _flecha(fig, nx, ny, (xa, y), (xb, y))
        fig.text(nx((xa + xb) / 2), ny(y + 0.09), rotulo, ha="center",
                 va="bottom", fontsize=7.4, color=SECUNDARIO, linespacing=1.2)

    # El salto de fila es el enlace de radio: sale por debajo de la Crazyradio,
    # cruza el canal y entra por arriba de la primera etapa a bordo.
    xr = posiciones[EN_TIERRA - 1][0] + CELDA_ANCHO_IN / 2
    xd = posiciones[EN_TIERRA][0] + CELDA_ANCHO_IN / 2
    y_sale = y_fila[0] - 0.14
    y_canal = y_fila[0] - 0.12 - (CANAL_IN - 0.06) / 2
    y_entra = y_fila[1] + CELDA_ALTO_IN + ROTULO_FILA_IN + 0.07
    fig.lines.append(Line2D(
        [nx(xr), nx(xr), nx(xd), nx(xd)],
        [ny(y_sale), ny(y_canal), ny(y_canal), ny(y_entra + 0.08)],
        transform=fig.transFigure, color=ACENTO, linewidth=1.7,
        linestyle=(0, (3.4, 2.6)), dash_capstyle="round",
        solid_joinstyle="round", zorder=6))
    _flecha(fig, nx, ny, (xd, y_entra + 0.14), (xd, y_entra), ACENTO, lw=0)
    x_medio = (xr + xd) / 2
    fig.text(nx(x_medio), ny(y_canal + 0.10), enlaces[EN_TIERRA - 1],
             ha="center", va="bottom", fontsize=9, fontweight="bold",
             color=ACENTO_TEXTO)
    fig.text(nx(x_medio), ny(y_canal - 0.10),
             spec["canal"],
             ha="center", va="top", fontsize=7.6, color=SECUNDARIO)
    # Ondas a los dos lados del rotulo, para que el trazo se lea como radio.
    eje = fig.add_axes([0, 0, 1, 1], zorder=7)
    eje.set_xlim(0, W)
    eje.set_ylim(0, H)
    eje.axis("off")
    eje.patch.set_alpha(0)
    for sx, x in ((-1, xd + 0.95), (1, xr - 0.95)):
        a0, a1 = (135, 225) if sx < 0 else (-45, 45)
        for r in (0.10, 0.18, 0.26):
            t = np.radians(np.linspace(a0, a1, 20))
            eje.plot(x + r * np.cos(t), y_canal + r * np.sin(t), color=ACENTO,
                     linewidth=1.3, solid_capstyle="round")

    # El hueco de la segunda fila lleva la leyenda.
    xl = x_col(COLUMNAS - 1) + 0.10
    yl = y_fila[1] + CELDA_ALTO_IN / 2
    leyenda = (
        (TINTA, "-", "señal por cable o\ndentro de un programa"),
        (ACENTO, (0, (3.4, 2.6)), "enlace de radio"),
    )
    fig.text(nx(xl), ny(yl + 0.58), "LECTURA", fontsize=8, fontweight="bold",
             color=NUMERO, va="center")
    for k, (color, estilo, texto) in enumerate(leyenda):
        y = yl + 0.14 - 0.52 * k
        fig.lines.append(Line2D([nx(xl), nx(xl + 0.42)], [ny(y), ny(y)],
                                transform=fig.transFigure, color=color,
                                linewidth=1.6, linestyle=estilo,
                                dash_capstyle="round"))
        _flecha(fig, nx, ny, (xl + 0.40, y), (xl + 0.54, y), color, lw=0)
        fig.text(nx(xl + 0.66), ny(y), texto, fontsize=7.8, color=SECUNDARIO,
                 va="center", linespacing=1.3)

    destino.mkdir(parents=True, exist_ok=True)
    base = destino / clave
    png, pdf = base.with_suffix(".png"), base.with_suffix(".pdf")
    fig.savefig(png, dpi=300, facecolor="white")
    fig.savefig(pdf, facecolor="white")
    plt.close(fig)
    return png, pdf


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Laminas de la cadena de control y de la realimentacion externa")
    parser.add_argument("--lamina", choices=sorted(LAMINAS),
                        help="solo una de las dos; por defecto, ambas")
    parser.add_argument("--salida", help="carpeta de destino")
    args = parser.parse_args()

    destino = (Path(args.salida) if args.salida
               else PROJECT_DIR / "results" / "graphs" / "esquemas_control"
               / date.today().isoformat())
    for clave in ([args.lamina] if args.lamina else LAMINAS):
        png, pdf = lamina(clave, destino)
        print(f"PNG: {png}\nPDF: {pdf}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
