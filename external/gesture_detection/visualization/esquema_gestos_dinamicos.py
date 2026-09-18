r"""Lamina de los gestos dinamicos y de la orden que producen en el dron.

Es el equivalente de `esquema_gestos_mano.m` para el vocabulario que reconoce
DTW. Cambia una cosa esencial y por eso no es el mismo dibujo: un gesto de mano
es una **postura** y cabe en una figura quieta; `aplaudir` o `circulo` son un
**recorrido**, y una sola pose no los distingue de nada.

Asi que cada celda muestra el recorrido:

* el esqueleto en varios instantes, del mas claro (empieza) al mas oscuro
  (termina), que es lo que en dibujo se llama papel cebolla;
* la **estela de las munecas**, con una punta de flecha en el sentido del
  movimiento, que es literalmente lo que DTW compara;
* dos vistas, **de frente y de perfil**. Sin la de perfil, `ven_aca` parece que
  no se mueve: su recorrido es hacia el cuerpo, o sea en profundidad.

Las coordenadas **no son sinteticas**: salen de las tomas grabadas. De cada
gesto se dibuja la toma frontal mas representativa, la que menos dista de las
demas del mismo gesto segun DTW, que es la definicion de medoide. Asi la lamina
no ilustra lo que el autor cree que hace la gente, sino lo que las ocho personas
hicieron de verdad.

Uso, desde la raiz del repositorio:

    python .\external\gesture_detection\visualization\esquema_gestos_dinamicos.py
    python .\external\gesture_detection\visualization\esquema_gestos_dinamicos.py --animar
    python .\external\gesture_detection\visualization\esquema_gestos_dinamicos.py --gestos aplaudir,circulo

Sale PNG a 300 ppp y PDF vectorial en `results/graphs/gestos_dinamicos/<hoy>/`.
Con `--animar` ademas un GIF por gesto, que es la forma mas directa de explicar
como se hace: se ve el gesto entero a su velocidad real.

No abre camara, ni radio, ni controladores.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import numpy as np

MODULE_DIR = Path(__file__).resolve().parent
GESTURE_DIR = MODULE_DIR.parent
PROJECT_DIR = GESTURE_DIR.parents[1]
if str(GESTURE_DIR) not in sys.path:
    sys.path.insert(0, str(GESTURE_DIR))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

from construir_plantillas import CARPETAS_VOCABULARIO, canonicalizar, ventana  # noqa: E402
from dataset.storage import cargar_todas  # noqa: E402
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
from recognition.dinamicos import recortar_quietud  # noqa: E402
from recognition.dtw import dtw_distancia  # noqa: E402

NOSE = 0

#: Vocabulario, en el orden de la lamina, con lo que hay que decirle a quien lo
#: va a hacer y lo que el dron obedece. La columna de la orden sale de
#: `probar_vocabulario.Simulador`; si alli cambia, aqui tambien.
CATALOGO = (
    ("senalero", "SEÑALERO",
     "Dos brazos arriba, codos altos.\nOscila los antebrazos 3 o 4 veces.",
     "despega si esta en el suelo,\naterriza si esta en el aire"),
    ("aplaudir", "APLAUDIR",
     "Aplaude 3 o 4 veces\na la altura del pecho.",
     "cambia de modo:\ndinamico <-> estatico"),
    ("ven_aca", "VEN ACA",
     "UNA mano a la altura del pecho.\nLlama hacia ti 3 veces.",
     "sigue al marker"),
    ("arco", "ARCO",
     "Sube los dos brazos por los lados\nhasta arriba, despacio, sin repetir.",
     "se aleja del marker"),
    ("circulo", "CIRCULO",
     "UNA mano, todo el brazo estirado.\nUn circulo grande, 2 vueltas.",
     "orbita el marker"),
)

#: Huesos que se dibujan. Sin piernas: el vocabulario es de brazos, y las
#: piernas solo anaden tinta y ruido de deteccion.
HUESOS = (
    (LEFT_SHOULDER, RIGHT_SHOULDER),
    (LEFT_HIP, RIGHT_HIP),
    (LEFT_SHOULDER, LEFT_HIP),
    (RIGHT_SHOULDER, RIGHT_HIP),
    (LEFT_SHOULDER, LEFT_ELBOW),
    (LEFT_ELBOW, LEFT_WRIST),
    (RIGHT_SHOULDER, RIGHT_ELBOW),
    (RIGHT_ELBOW, RIGHT_WRIST),
)

#: Landmarks que aparecen en el dibujo. La ventana se calcula **solo** con
#: estos: MediaPipe entrega 33, y las piernas llegan a -2.5 torsos por debajo
#: de la cadera. Incluirlas en la ventana, sin dibujarlas, dejaba al cuerpo a un
#: tercio de su tamano y media celda en blanco.
DIBUJADOS = tuple(sorted({NOSE, *(i for hueso in HUESOS for i in hueso)}))

#: Esqueletos que se superponen en cada vista. Cuatro bastan para leer el
#: recorrido; con mas, los brazos se tapan entre si y la celda es una mancha.
N_POSES = 4

#: Paleta. Es la de `esquema_gestos_mano.m` para que las dos laminas se lean
#: como del mismo trabajo.
TINTA = (0.10, 0.16, 0.22)
GRIS = (0.60, 0.65, 0.69)
ACENTO = (0.85, 0.33, 0.10)
MUNECA_DER = (0.12, 0.44, 0.73)
MUNECA_IZQ = (0.78, 0.12, 0.32)
BORDE = (0.85, 0.88, 0.90)
SECUNDARIO = (0.30, 0.35, 0.39)


# --------------------------------------------------------------- material


def cargar_vocabulario(carpetas: list[Path]) -> list:
    tomas = []
    for carpeta in carpetas:
        tomas.extend(cargar_todas(carpeta))
    return tomas


def toma_representativa(tomas: list, gesto: str) -> tuple:
    """Medoide DTW del gesto entre las tomas de frente.

    El medoide es la toma que menos dista de todas las demas de su clase: la
    mas parecida a "como lo hace la gente". Se limita a las frontales porque la
    lamina se dibuja de frente y una toma girada saldria escorzada.
    """
    candidatas = [t for t in tomas
                  if t.gesto == gesto and abs(t.orientacion_deg) < 1.0]
    if not candidatas:
        candidatas = [t for t in tomas if t.gesto == gesto]
    if not candidatas:
        raise SystemExit(f"No hay tomas del gesto {gesto!r} en el material.")

    ventanas, validas = [], []
    for t in candidatas:
        v = ventana(t, 24, False)
        if v is not None:
            ventanas.append(v)
            validas.append(t)
    if not ventanas:
        raise SystemExit(f"Ninguna toma de {gesto!r} tiene pose suficiente.")
    if len(ventanas) == 1:
        return validas[0], 0.0

    n = len(ventanas)
    D = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            D[i, j] = D[j, i] = dtw_distancia(ventanas[i], ventanas[j])
    sumas = D.sum(axis=1)
    k = int(np.argmin(sumas))
    return validas[k], float(sumas[k] / (n - 1))


def recorrido(toma) -> tuple[np.ndarray, np.ndarray]:
    """`(poses, tiempos)` canonicalizadas, en unidades de torso y sin quietud."""
    r = canonicalizar(toma)
    if r is None:
        raise SystemExit(f"La toma {toma.etiqueta} no tiene marco corporal.")
    return recortar_quietud(*r)


def duracion_mediana(tomas: list, gesto: str) -> float:
    """Cuanto dura el gesto en el material, ya recortada la quietud."""
    duraciones = []
    for t in tomas:
        if t.gesto != gesto:
            continue
        r = canonicalizar(t)
        if r is None:
            continue
        _, ts = recortar_quietud(*r)
        if len(ts) > 1:
            duraciones.append(float(ts[-1] - ts[0]))
    return float(np.median(duraciones)) if duraciones else float("nan")


# ---------------------------------------------------------------- dibujo


def _cuello(Q: np.ndarray) -> tuple | None:
    """Segmento del punto medio de los hombros a la nariz, ya proyectado.

    MediaPipe no da un landmark de cuello, asi que este segmento no puede vivir
    en `HUESOS`. Sin el, la cabeza sale flotando medio torso por encima del
    tronco y el monigote no se lee como una persona.
    """
    hombros = Q[[LEFT_SHOULDER, RIGHT_SHOULDER]]
    if not (np.all(np.isfinite(hombros)) and np.all(np.isfinite(Q[NOSE]))):
        return None
    medio = hombros.mean(axis=0)
    return ([medio[0], Q[NOSE, 0]], [medio[1], Q[NOSE, 1]])


def _proyectar(P: np.ndarray, vista: str) -> np.ndarray:
    """`(K, 2)` en la vista pedida.

    Marco del cuerpo: `+X` a la izquierda del sujeto, `+Y` arriba, `+Z` hacia
    donde mira. De frente se dibuja con el horizontal en `+X`, que es lo que ve
    quien esta enfrente: la mano izquierda del operador cae a la derecha de la
    hoja. De perfil, el horizontal es `+Z`, con el sujeto mirando a la derecha.
    """
    if vista == "frente":
        return np.column_stack([P[:, 0], P[:, 1]])
    return np.column_stack([P[:, 2], P[:, 1]])


def _suavizar(T: np.ndarray, ventana_frames: int = 3) -> np.ndarray:
    """Media movil de la estela.

    Es el mismo suavizado de `recognition/dinamicos.py`, no un maquillaje: el
    reconocedor tampoco mira la senal cruda. Sin el, el temblor de deteccion de
    MediaPipe llena la celda de dientes de sierra y tapa la forma del gesto.
    """
    if len(T) < ventana_frames:
        return T
    nucleo = np.ones(ventana_frames) / ventana_frames
    return np.column_stack([np.convolve(T[:, j], nucleo, mode="valid")
                            for j in range(T.shape[1])])


def extension(seleccion: list, vista: str) -> tuple[float, float, float, float]:
    """Ventana comun a todas las celdas para esa vista.

    **La escala es la misma en toda la lamina, a proposito.** Si cada celda se
    ajustase a su gesto, un `ven_aca` de 20 cm y un `arco` de brazos abiertos
    saldrian del mismo tamano y la lamina mentiria sobre la amplitud, que es
    justo una de las cosas que distingue a un gesto de otro.
    """
    puntos = []
    for item in seleccion:
        poses = item[4]
        for k in range(len(poses)):
            Q = _proyectar(poses[k], vista)[list(DIBUJADOS)]
            puntos.append(Q[np.all(np.isfinite(Q), axis=1)])
    todos = np.vstack(puntos)
    margen = 0.12
    return (todos[:, 0].min() - margen, todos[:, 0].max() + margen,
            todos[:, 1].min() - margen, todos[:, 1].max() + margen)


def dibujar_vista(ax, poses: np.ndarray, vista: str, titulo: str,
                  limites: tuple[float, float, float, float] | None = None) -> None:
    # `box` y no `datalim`: `datalim` estira los limites de cada eje por su
    # cuenta y rompe la escala comun, que es lo unico que hace comparables las
    # celdas. El hueco que `box` dejaria se evita dando a la caja exactamente la
    # proporcion de la ventana, en `_tamano_vistas`.
    ax.set_aspect("equal", adjustable="box")
    ax.axis("off")
    ax.set_title(titulo, fontsize=8.5, color=SECUNDARIO, pad=1)

    puntos = []
    indices = np.linspace(0, len(poses) - 1, N_POSES).round().astype(int)
    for orden, k in enumerate(indices):
        # El primero casi transparente y el ultimo opaco: se lee el sentido del
        # tiempo sin poner numeros encima del esqueleto.
        alfa = 0.16 + 0.74 * (orden / max(N_POSES - 1, 1))
        Q = _proyectar(poses[k], vista)
        for a, b in HUESOS:
            if not (np.all(np.isfinite(Q[a])) and np.all(np.isfinite(Q[b]))):
                continue
            ax.plot([Q[a, 0], Q[b, 0]], [Q[a, 1], Q[b, 1]],
                    color=TINTA, alpha=alfa, linewidth=1.9,
                    solid_capstyle="round", zorder=2)
        cuello = _cuello(Q)
        if cuello is not None:
            ax.plot(*cuello, color=TINTA, alpha=alfa, linewidth=1.9,
                    solid_capstyle="round", zorder=2)
        if np.all(np.isfinite(Q[NOSE])):
            ax.plot(Q[NOSE, 0], Q[NOSE, 1], "o", color=TINTA, alpha=alfa,
                    markersize=5.5, zorder=2)
        recorte = Q[list(DIBUJADOS)]
        puntos.append(recorte[np.all(np.isfinite(recorte), axis=1)])

    for indice, color in ((RIGHT_WRIST, MUNECA_DER), (LEFT_WRIST, MUNECA_IZQ)):
        T = _proyectar(poses[:, indice], vista)
        T = T[np.all(np.isfinite(T), axis=1)]
        if len(T) < 4:
            continue
        T = _suavizar(T)
        ax.plot(T[:, 0], T[:, 1], color=color, linewidth=1.7, alpha=0.85,
                zorder=3, solid_capstyle="round")
        # Donde empieza y hacia donde va. Sin las dos marcas, una estela
        # cerrada como la del circulo no dice ni el sentido ni el arranque.
        ax.plot(T[0, 0], T[0, 1], "o", color=color, markersize=4.5,
                markerfacecolor="white", markeredgewidth=1.4, zorder=4)
        p0, p1 = T[-2], T[-1]
        if np.linalg.norm(p1 - p0) > 1e-6:
            ax.annotate("", xy=p1, xytext=p0, zorder=4,
                        arrowprops=dict(arrowstyle="-|>", color=color,
                                        linewidth=0, mutation_scale=14))
        puntos.append(T)

    if limites is not None:
        ax.set_xlim(limites[0], limites[1])
        ax.set_ylim(limites[2], limites[3])
        return
    todos = np.vstack(puntos)
    margen = 0.15
    ax.set_xlim(todos[:, 0].min() - margen, todos[:, 0].max() + margen)
    ax.set_ylim(todos[:, 1].min() - margen, todos[:, 1].max() + margen)


#: Rejilla en pulgadas, como la lamina de los gestos de mano: se fija el tamano
#: fisico de la celda y la figura se dimensiona a partir de el. Trabajar en
#: pulgadas y convertir al final evita que el texto se salga de la celda al
#: cambiar el numero de gestos, que es lo que pasa al mezclar fracciones.
CELDA_ANCHO_IN = 4.75
SEPARACION_IN = 0.18
MARGEN_IN = 0.30
CABECERA_IN = 1.00
PIE_IN = 0.55
COLUMNAS = 2


def lamina(seleccion: list, destino: Path) -> tuple[Path, Path]:
    n = len(seleccion)
    cols = min(COLUMNAS, n)
    filas = (n + cols - 1) // cols

    limites = {vista: extension(seleccion, vista) for vista in ("frente", "perfil")}
    # Las dos vistas comparten el eje vertical: es la misma coordenada Y del
    # cuerpo. Igualarlo evita que el mismo operador salga de dos estaturas.
    y0_comun = min(limites[v][2] for v in limites)
    y1_comun = max(limites[v][3] for v in limites)
    limites = {v: (l[0], l[1], y0_comun, y1_comun) for v, l in limites.items()}
    cajas = _tamano_vistas(limites)

    # La celda se dimensiona a partir del dibujo, no al reves. Fijar el alto de
    # antemano dejaba una banda en blanco cuando la ventana comun resultaba
    # ancha, que es lo que pasa en cuanto entra el circulo.
    alto_vista = max(cajas[v][1] for v in ("frente", "perfil"))
    celda_alto = TEXTO_ALTO_IN + alto_vista + 0.34

    W = 2 * MARGEN_IN + cols * CELDA_ANCHO_IN + (cols - 1) * SEPARACION_IN
    H = CABECERA_IN + filas * celda_alto + (filas - 1) * SEPARACION_IN + PIE_IN

    fig = plt.figure(figsize=(W, H))
    fig.patch.set_facecolor("white")

    def nx(x: float) -> float:
        return x / W

    def ny(y: float) -> float:
        return y / H

    fig.text(0.5, ny(H - 0.42), "Gestos dinamicos y orden que producen en el dron",
             ha="center", va="center", fontsize=20, fontweight="bold", color=TINTA)
    fig.text(0.5, ny(H - 0.72),
             "Recorrido medido con MediaPipe Pose  ->  clasificado por DTW  ->  orden al Crazyflie",
             ha="center", va="center", fontsize=10, color=SECUNDARIO)

    for k, item in enumerate(seleccion):
        fila, col = divmod(k, cols)
        x0 = MARGEN_IN + col * (CELDA_ANCHO_IN + SEPARACION_IN)
        y0 = H - CABECERA_IN - (fila + 1) * celda_alto - fila * SEPARACION_IN
        _celda(fig, nx, ny, x0, y0, celda_alto, k + 1, item, limites, cajas)

    pie = [
        Line2D([], [], color=MUNECA_DER, lw=2, label="Muneca derecha"),
        Line2D([], [], color=MUNECA_IZQ, lw=2, label="Muneca izquierda"),
        Line2D([], [], color=TINTA, lw=2, alpha=0.22, label="Inicio del gesto"),
        Line2D([], [], color=TINTA, lw=2, label="Final del gesto"),
    ]
    fig.legend(handles=pie, loc="center", ncol=4, frameon=False, fontsize=9.5,
               bbox_to_anchor=(0.5, ny(PIE_IN * 0.55)))

    destino.mkdir(parents=True, exist_ok=True)
    base = destino / "esquema_gestos_dinamicos"
    png, pdf = base.with_suffix(".png"), base.with_suffix(".pdf")
    fig.savefig(png, dpi=300, facecolor="white")
    fig.savefig(pdf, facecolor="white")
    plt.close(fig)
    return png, pdf


#: Espacio disponible para las dos vistas dentro de la celda, en pulgadas.
BANDA_ANCHO_IN = CELDA_ANCHO_IN - 0.50
BANDA_ALTO_IN = 1.95

#: Alto reservado al bloque de texto de la celda: nombre, como se hace, orden
#: al dron y la linea de procedencia.
TEXTO_ALTO_IN = 1.22


def _tamano_vistas(limites: dict) -> dict:
    """Caja de cada vista, con la proporcion exacta de su ventana.

    Dandole a la caja la proporcion de los datos, `aspect='equal'` no tiene que
    encoger nada y no queda franja en blanco; y como la escala en pulgadas por
    unidad de torso es la misma para las dos vistas y para todas las celdas,
    los gestos siguen siendo comparables entre si.
    """
    anchos = {v: l[1] - l[0] for v, l in limites.items()}
    alto = max(l[3] - l[2] for l in limites.values())
    # Escala limitada por lo alto y por lo ancho de la banda; manda la menor.
    por_alto = BANDA_ALTO_IN / alto
    por_ancho = (BANDA_ANCHO_IN - 0.25) / sum(anchos.values())
    escala = min(por_alto, por_ancho)
    return {v: (anchos[v] * escala, alto * escala) for v in limites}


def _celda(fig, nx, ny, x0, y0, ch, numero, item, limites, cajas) -> None:
    """Una celda: las dos vistas arriba, el texto abajo. Todo en pulgadas."""
    clave, nombre, como, accion, poses, tiempos, duracion, persona = item
    cw = CELDA_ANCHO_IN

    fig.patches.append(plt.Rectangle(
        (nx(x0), ny(y0)), nx(cw), ny(ch), transform=fig.transFigure,
        facecolor="none", edgecolor=BORDE, linewidth=0.8, zorder=0))
    fig.text(nx(x0 + 0.10), ny(y0 + ch - 0.22), f"{numero:02d}", fontsize=9,
             fontweight="bold", color=(0.45, 0.50, 0.55))

    # Las dos vistas ocupan la banda de arriba; el texto, la de abajo. Van
    # centradas en la celda y apoyadas en la misma linea de base, para que el
    # suelo del operador coincida en las dos.
    ancho_total = sum(cajas[v][0] for v in ("frente", "perfil")) + 0.25
    alto_vista = max(cajas[v][1] for v in ("frente", "perfil"))
    base_vistas = y0 + ch - alto_vista - 0.22
    cursor = x0 + (cw - ancho_total) / 2
    for vista, titulo in (("frente", "de frente"), ("perfil", "de perfil")):
        ancho_vista, alto_v = cajas[vista]
        ax = fig.add_axes([nx(cursor), ny(base_vistas),
                           nx(ancho_vista), ny(alto_v)])
        dibujar_vista(ax, poses, vista, titulo, limites[vista])
        cursor += ancho_vista + 0.25

    fig.text(nx(x0 + cw / 2), ny(y0 + 1.02), nombre, ha="center", va="center",
             fontsize=13.5, fontweight="bold", color=TINTA)
    fig.text(nx(x0 + cw / 2), ny(y0 + 0.68), como, ha="center", va="center",
             fontsize=9.5, color=SECUNDARIO, linespacing=1.4)
    fig.text(nx(x0 + cw / 2), ny(y0 + 0.32), f"Dron: {accion}", ha="center",
             va="center", fontsize=9.5, fontweight="bold",
             color=tuple(0.85 * c for c in ACENTO), linespacing=1.35)
    fig.text(nx(x0 + cw / 2), ny(y0 + 0.10),
             f"dura {duracion:.1f} s de mediana   ·   toma de {persona}",
             ha="center", va="center", fontsize=8, color=(0.55, 0.58, 0.62))


# -------------------------------------------------------------- animacion

#: Cuadros por segundo del GIF. El material se grabo a 26-30 fps; 20 basta para
#: que el gesto se lea con naturalidad y pesa un tercio menos.
GIF_FPS = 20

#: Cuantos segundos de estela se conservan detras de la muneca. Con la estela
#: entera, `aplaudir` y `circulo` terminan siendo un ovillo y no se distingue
#: por donde va la mano ahora; con una cola corta se ve el gesto y su forma.
GIF_ESTELA_S = 1.2


def animar(item, destino: Path, limites=None) -> Path:
    """GIF del gesto: el esqueleto moviendose a su velocidad real.

    Es la forma mas directa de explicar el vocabulario. La lamina dice como es
    el recorrido; el GIF lo *ensena*, que para alguien que va a hacer el gesto
    por primera vez es otra cosa.

    La estela no es completa sino una cola de `GIF_ESTELA_S`: se ve por donde
    acaba de pasar la mano sin que la celda se llene de lineas.
    """
    from matplotlib.animation import FuncAnimation, PillowWriter

    clave, nombre, como, accion, poses, tiempos, duracion, persona = item
    vistas = ("frente", "perfil")
    if limites is None:
        limites = {v: extension([item], v) for v in vistas}
        y0 = min(limites[v][2] for v in vistas)
        y1 = max(limites[v][3] for v in vistas)
        limites = {v: (l[0], l[1], y0, y1) for v, l in limites.items()}

    # Remuestreo a paso constante: el material tiene jitter entre cuadros y un
    # GIF de periodo fijo lo mostraria como tirones que el operador no hizo.
    t0, t1 = float(tiempos[0]), float(tiempos[-1])
    n_cuadros = max(int(round((t1 - t0) * GIF_FPS)), 8)
    rejilla = np.linspace(t0, t1, n_cuadros)
    P = np.stack([
        np.column_stack([np.interp(rejilla, tiempos, poses[:, j, e])
                         for e in range(3)])
        for j in range(poses.shape[1])
    ], axis=1)

    anchos = [limites[v][1] - limites[v][0] for v in vistas]
    alto = limites["frente"][3] - limites["frente"][2]
    escala = 3.0 / alto
    fig = plt.figure(figsize=(sum(anchos) * escala + 1.1, alto * escala + 2.10),
                     dpi=110)
    fig.patch.set_facecolor("white")
    W, H = fig.get_size_inches()

    fig.text(0.5, 1 - 0.30 / H, nombre, ha="center", va="center",
             fontsize=17, fontweight="bold", color=TINTA)
    fig.text(0.5, 1 - 0.60 / H, como.replace("\n", "   ·   "), ha="center",
             va="center", fontsize=10, color=SECUNDARIO)
    fig.text(0.5, 0.60 / H, f"Dron: {accion}".replace("\n", " "), ha="center",
             va="center", fontsize=10.5, fontweight="bold",
             color=tuple(0.85 * c for c in ACENTO))

    ejes, cursor = {}, 0.6
    for j, vista in enumerate(vistas):
        ancho = anchos[j] * escala
        ax = fig.add_axes([cursor / W, 0.95 / H, ancho / W, alto * escala / H])
        ax.set_aspect("equal", adjustable="box")
        ax.axis("off")
        ax.set_xlim(limites[vista][0], limites[vista][1])
        ax.set_ylim(limites[vista][2], limites[vista][3])
        ax.set_title("de frente" if vista == "frente" else "de perfil",
                     fontsize=9.5, color=SECUNDARIO, pad=3)
        ejes[vista] = ax
        cursor += ancho

    # Artistas fijos que se actualizan; recrearlos en cada cuadro multiplica por
    # diez el tiempo de escritura del GIF.
    huesos, cabezas, cuellos, estelas, manos = {}, {}, {}, {}, {}
    for vista, ax in ejes.items():
        huesos[vista] = [ax.plot([], [], color=TINTA, linewidth=2.6,
                                 solid_capstyle="round", zorder=3)[0]
                         for _ in HUESOS]
        cabezas[vista] = ax.plot([], [], "o", color=TINTA, markersize=9,
                                 zorder=3)[0]
        cuellos[vista] = ax.plot([], [], color=TINTA, linewidth=2.6,
                                 solid_capstyle="round", zorder=3)[0]
        estelas[vista], manos[vista] = {}, {}
        for indice, color in ((RIGHT_WRIST, MUNECA_DER), (LEFT_WRIST, MUNECA_IZQ)):
            estelas[vista][indice] = ax.plot([], [], color=color, linewidth=2.2,
                                             alpha=0.85, zorder=2,
                                             solid_capstyle="round")[0]
            manos[vista][indice] = ax.plot([], [], "o", color=color,
                                           markersize=6, zorder=4)[0]

    barra = fig.add_axes([0.55 / W, 0.26 / H, (W - 1.10) / W, 0.07 / H])
    barra.set_xlim(0, 1)
    barra.set_ylim(0, 1)
    barra.axis("off")
    barra.add_patch(plt.Rectangle((0, 0), 1, 1, color=(0.90, 0.92, 0.94)))
    avance = barra.add_patch(plt.Rectangle((0, 0), 0, 1, color=ACENTO))
    reloj = fig.text(1 - 0.08 / W, 0.295 / H, "0.0 s", ha="right", va="center",
                     fontsize=9, color=(0.55, 0.58, 0.62))

    cola = max(int(round(GIF_ESTELA_S * GIF_FPS)), 4)

    def pintar(k: int):
        for vista, ax in ejes.items():
            Q = _proyectar(P[k], vista)
            for linea, (a, b) in zip(huesos[vista], HUESOS):
                if np.all(np.isfinite(Q[a])) and np.all(np.isfinite(Q[b])):
                    linea.set_data([Q[a, 0], Q[b, 0]], [Q[a, 1], Q[b, 1]])
                else:
                    linea.set_data([], [])
            cuello = _cuello(Q)
            cuellos[vista].set_data(*(cuello if cuello is not None else ([], [])))
            if np.all(np.isfinite(Q[NOSE])):
                cabezas[vista].set_data([Q[NOSE, 0]], [Q[NOSE, 1]])
            for indice in (RIGHT_WRIST, LEFT_WRIST):
                T = _proyectar(P[max(0, k - cola): k + 1, indice], vista)
                T = T[np.all(np.isfinite(T), axis=1)]
                estelas[vista][indice].set_data(
                    (T[:, 0], T[:, 1]) if len(T) > 1 else ([], []))
                manos[vista][indice].set_data(
                    ([Q[indice, 0]], [Q[indice, 1]])
                    if np.all(np.isfinite(Q[indice])) else ([], []))
        avance.set_width((k + 1) / n_cuadros)
        reloj.set_text(f"{rejilla[k] - t0:.1f} s")
        return []

    anim = FuncAnimation(fig, pintar, frames=n_cuadros,
                         interval=1000.0 / GIF_FPS, blit=False)
    destino.mkdir(parents=True, exist_ok=True)
    ruta = destino / f"gesto_{clave}.gif"
    anim.save(ruta, writer=PillowWriter(fps=GIF_FPS), savefig_kwargs={"facecolor": "white"})
    plt.close(fig)
    return ruta


# ------------------------------------------------------------------ main


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Lamina de los gestos dinamicos, dibujada desde las tomas reales")
    parser.add_argument("--carpeta", nargs="+",
                        help="carpetas de tomas; por defecto las del vocabulario vigente")
    parser.add_argument("--gestos",
                        help="subconjunto separado por comas; por defecto los cinco")
    parser.add_argument("--salida", help="carpeta de destino")
    parser.add_argument("--animar", action="store_true",
                        help="ademas de la lamina, un GIF por gesto")
    args = parser.parse_args()

    carpetas = ([Path(c) for c in args.carpeta] if args.carpeta
                else [PROJECT_DIR / "results" / "data" / "gestos" / fecha
                      for fecha in CARPETAS_VOCABULARIO])
    quiere = ([g.strip() for g in args.gestos.split(",") if g.strip()]
              if args.gestos else [c[0] for c in CATALOGO])
    destino = (Path(args.salida) if args.salida
               else PROJECT_DIR / "results" / "graphs" / "gestos_dinamicos"
               / date.today().isoformat())

    tomas = cargar_vocabulario(carpetas)
    if not tomas:
        print(f"No hay tomas en {', '.join(str(c) for c in carpetas)}.",
              file=sys.stderr)
        return 1
    print(f"Material: {', '.join(str(c) for c in carpetas)}  ({len(tomas)} tomas)")

    seleccion = []
    for clave, nombre, como, accion in CATALOGO:
        if clave not in quiere:
            continue
        toma, distancia = toma_representativa(tomas, clave)
        poses, tiempos = recorrido(toma)
        duracion = duracion_mediana(tomas, clave)
        seleccion.append((clave, nombre, como, accion, poses, tiempos,
                          duracion, toma.persona))
        print(f"  {clave:9s} toma de {toma.persona:20s} "
              f"{tiempos[-1] - tiempos[0]:4.1f} s   "
              f"distancia media al resto {distancia:.3f}")

    if not seleccion:
        print(f"Ningun gesto de {quiere} esta en el catalogo.", file=sys.stderr)
        return 1

    png, pdf = lamina(seleccion, destino)
    print(f"\nPNG: {png}\nPDF: {pdf}")

    if args.animar:
        for item in seleccion:
            ruta = animar(item, destino)
            print(f"GIF: {ruta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
