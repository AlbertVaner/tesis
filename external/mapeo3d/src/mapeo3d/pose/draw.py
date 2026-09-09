"""Dibujado de esqueletos: overlay 2D y vista 3D en perspectiva.

Es presentación, no algoritmo: no decide nada sobre la pose, sólo la pinta.
Vive aquí y no en una app para que las apps no se copien el código entre sí.

Por qué una vista 3D en PERSPECTIVA y no ortográfica
-----------------------------------------------------
Tres proyecciones ortográficas —frontal, perfil, planta— son lo mejor para
*medir*: no deforman y se leen como un plano. Pero no comunican «esto es 3D» a
quien lo ve por primera vez, porque cada panel por separado parece 2D.

Una vista en perspectiva que **gira**, con una rejilla de suelo como referencia,
sí lo comunica: el cerebro reconstruye el volumen del movimiento relativo. Por
eso conviven las dos y no sobra ninguna.

Marco de coordenadas
--------------------
MediaPipe entrega `x` a la derecha, `y` hacia **abajo** y `z` alejándose de la
cámara. Aquí se convierte a un marco de escena más natural para dibujar —`X` a
la derecha, `Y` en profundidad, `Z` hacia **arriba**— porque con `Z` arriba la
rejilla del suelo es el plano `Z = constante` y la órbita es un giro en azimut.
"""

from __future__ import annotations

import cv2
import numpy as np

# Colores por lado. Que izquierda y derecha se distingan es lo que deja ver a
# simple vista si el modelo intercambió los lados, que es su fallo típico
# cuando el sujeto está de espaldas.
COLOR_IZQ = (90, 200, 250)     # ámbar
COLOR_DER = (250, 180, 90)     # azul
COLOR_CENTRO = (120, 220, 140)
COLOR_HUESO = (150, 150, 150)

# Altura del suelo respecto del origen (las caderas), en metros. Una persona
# de pie tiene las caderas a ~0.95 m del suelo.
SUELO_M = -0.95


def a_escena(mundo: np.ndarray) -> np.ndarray:
    """De MediaPipe (x der, y abajo, z lejos) a escena (X der, Y prof, Z arriba)."""
    P = np.asarray(mundo, dtype=np.float64).reshape(-1, 3)
    return np.stack([P[:, 0], P[:, 2], -P[:, 1]], axis=1)


def camara_orbital(azimut_deg: float, elevacion_deg: float,
                   distancia_m: float) -> tuple[np.ndarray, np.ndarray]:
    """Base de una cámara que orbita el origen mirándolo.

    Returns:
        `(ojo, base)` con `base` de forma `(3, 3)`: filas derecha, arriba y
        adelante en coordenadas de escena.
    """
    a = np.radians(azimut_deg)
    e = np.radians(elevacion_deg)
    ojo = distancia_m * np.array([np.cos(e) * np.cos(a),
                                  np.cos(e) * np.sin(a),
                                  np.sin(e)])
    adelante = -ojo / np.linalg.norm(ojo)
    arriba_mundo = np.array([0.0, 0.0, 1.0])
    derecha = np.cross(adelante, arriba_mundo)
    n = np.linalg.norm(derecha)
    if n < 1e-9:                       # mirando justo desde arriba
        derecha = np.array([1.0, 0.0, 0.0])
    else:
        derecha = derecha / n
    arriba = np.cross(derecha, adelante)
    return ojo, np.stack([derecha, arriba, adelante])


def proyectar(puntos_escena: np.ndarray, ojo: np.ndarray, base: np.ndarray,
              lado: int, focal_px: float) -> tuple[np.ndarray, np.ndarray]:
    """Proyección en perspectiva. Devuelve `(pixeles, delante)`.

    `delante` marca qué puntos están por delante de la cámara: los de detrás no
    se pueden dibujar y hay que descartarlos, no proyectarlos al revés.
    """
    P = np.asarray(puntos_escena, dtype=np.float64).reshape(-1, 3)
    v = P - ojo
    cam = v @ base.T                                  # (N, 3): der, arriba, adelante
    z = cam[:, 2]
    delante = z > 0.05
    zz = np.where(delante, z, 1.0)
    x = lado / 2.0 + focal_px * cam[:, 0] / zz
    y = lado / 2.0 - focal_px * cam[:, 1] / zz
    return np.stack([x, y], axis=1), delante & np.all(np.isfinite(P), axis=1)


def dibujar_rejilla(panel: np.ndarray, ojo: np.ndarray, base: np.ndarray,
                    focal_px: float, *, extension_m: float = 1.2,
                    paso_m: float = 0.3, altura_m: float = SUELO_M,
                    color=(58, 58, 58)) -> None:
    """Rejilla de suelo. Sin ella la vista 3D no da sensación de profundidad."""
    lado = panel.shape[0]
    ticks = np.arange(-extension_m, extension_m + 1e-9, paso_m)
    segmentos = []
    for t in ticks:
        segmentos.append(([-extension_m, t, altura_m], [extension_m, t, altura_m]))
        segmentos.append(([t, -extension_m, altura_m], [t, extension_m, altura_m]))
    puntos = np.array([p for seg in segmentos for p in seg])
    pix, ok = proyectar(puntos, ojo, base, lado, focal_px)
    for i in range(0, len(pix), 2):
        if ok[i] and ok[i + 1]:
            cv2.line(panel, tuple(pix[i].astype(int)),
                     tuple(pix[i + 1].astype(int)), color, 1, cv2.LINE_AA)


def _color_de(indice: int, nombres) -> tuple[int, int, int]:
    n = nombres[indice]
    if n.startswith("left_"):
        return COLOR_IZQ
    if n.startswith("right_"):
        return COLOR_DER
    return COLOR_CENTRO


def dibujar_esqueleto_3d(panel: np.ndarray, mundo: np.ndarray,
                         visibilidad: np.ndarray, conexiones: np.ndarray,
                         nombres, ojo: np.ndarray, base: np.ndarray,
                         focal_px: float, *, min_vis: float = 0.3,
                         grosor: int = 3) -> None:
    """Pinta el esqueleto en perspectiva, de atrás hacia adelante."""
    lado = panel.shape[0]
    escena = a_escena(mundo)
    pix, ok = proyectar(escena, ojo, base, lado, focal_px)
    prof = (escena - ojo) @ base[2]

    # Pintar primero lo lejano: sin esto un brazo que pasa por detrás del
    # torso se dibuja encima y la pose se lee al revés.
    orden = sorted(range(len(conexiones)),
                   key=lambda k: -float(np.mean(prof[conexiones[k]])))
    for k in orden:
        a, b = conexiones[k]
        if not (ok[a] and ok[b]) or visibilidad[a] < min_vis or visibilidad[b] < min_vis:
            continue
        cv2.line(panel, tuple(pix[a].astype(int)), tuple(pix[b].astype(int)),
                 COLOR_HUESO, grosor, cv2.LINE_AA)

    for i in np.argsort(-prof):
        if not ok[i] or visibilidad[i] < min_vis:
            continue
        cv2.circle(panel, tuple(pix[i].astype(int)), grosor + 1,
                   _color_de(int(i), nombres), -1, cv2.LINE_AA)


def dibujar_esqueleto_2d(frame: np.ndarray, pix: np.ndarray,
                         visibilidad: np.ndarray, conexiones: np.ndarray,
                         *, min_vis: float = 0.3,
                         color=(90, 200, 120)) -> np.ndarray:
    """Overlay sobre una copia del frame. **No modifica el original.**"""
    salida = frame.copy()
    for a, b in conexiones:
        if visibilidad[a] < min_vis or visibilidad[b] < min_vis:
            continue
        cv2.line(salida, tuple(np.round(pix[a]).astype(int)),
                 tuple(np.round(pix[b]).astype(int)), color, 2, cv2.LINE_AA)
    for i, p in enumerate(pix):
        if visibilidad[i] < min_vis:
            continue
        c = (60, 220, 255) if visibilidad[i] > 0.7 else (60, 130, 180)
        cv2.circle(salida, tuple(np.round(p).astype(int)), 4, c, -1, cv2.LINE_AA)
    return salida
