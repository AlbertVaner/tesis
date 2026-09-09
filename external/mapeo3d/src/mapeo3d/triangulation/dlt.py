"""Triangulación lineal de N vistas por DLT.

Este módulo no sabe qué es RTSP ni qué es MediaPipe: recibe matrices de
proyección y puntos 2D, y devuelve puntos 3D con su residual. Se prueba entero
con datos sintéticos, sin cámaras. Ver docs/triangulation.md.

El método
---------
Para un punto 3D `X` visto por la cámara `i` con matriz `P_i` en la posición de
imagen `(u, v)`, cada vista aporta dos ecuaciones lineales::

    u · P[2] − P[0] = 0
    v · P[2] − P[1] = 0

Se apilan las filas de todas las vistas y se resuelve `A·X = 0` por SVD.

La consecuencia práctica es que **el DLT es N-vistas por naturaleza**: pasar de
2 a 6 cámaras es apilar más filas, no cambiar de algoritmo.
"""

from __future__ import annotations

import numpy as np

# Un punto reconstruido desde menos vistas que esto no es utilizable.
MIN_VISTAS = 2

# Ángulo entre rayos fuera de este rango: la intersección queda indeterminada.
# Cerca de 0° los rayos son paralelos; cerca de 180°, colineales. Ver
# docs/triangulation.md.
ANGULO_MIN_DEG = 20.0
ANGULO_MAX_DEG = 160.0


def triangulate(
    proyecciones: np.ndarray,
    puntos: np.ndarray,
    pesos: np.ndarray | None = None,
) -> np.ndarray:
    """Triangula un punto visto por N cámaras.

    Args:
        proyecciones: `(N, 3, 4)`, una matriz de proyección por vista.
        puntos: `(N, 2)`, la observación en cada vista.
        pesos: `(N,)` opcional. Una vista donde el estimador 2D apenas ve el
            punto debe influir poco, no igual.

    Returns:
        `(3,)` con el punto en el marco de las matrices de proyección.
    """
    P = np.asarray(proyecciones, dtype=np.float64)
    x = np.asarray(puntos, dtype=np.float64)
    n = len(P)
    if n < MIN_VISTAS:
        raise ValueError(f"Hacen falta al menos {MIN_VISTAS} vistas; hay {n}.")

    A = np.empty((2 * n, 4), dtype=np.float64)
    A[0::2] = x[:, 0:1] * P[:, 2, :] - P[:, 0, :]
    A[1::2] = x[:, 1:2] * P[:, 2, :] - P[:, 1, :]

    if pesos is not None:
        w = np.asarray(pesos, dtype=np.float64).reshape(-1, 1)
        A[0::2] *= w
        A[1::2] *= w

    _, _, Vt = np.linalg.svd(A)
    X = Vt[-1]
    if abs(X[3]) < 1e-12:
        # Punto en el infinito: rayos paralelos.
        return np.full(3, np.nan)
    return X[:3] / X[3]


def triangulate_many(
    proyecciones: np.ndarray,
    puntos: np.ndarray,
    pesos: np.ndarray | None = None,
) -> np.ndarray:
    """Triangula K puntos vistos por las mismas N cámaras.

    Args:
        proyecciones: `(N, 3, 4)`.
        puntos: `(N, K, 2)`.
        pesos: `(N, K)` opcional.

    Returns:
        `(K, 3)`.
    """
    P = np.asarray(proyecciones, dtype=np.float64)
    x = np.asarray(puntos, dtype=np.float64)
    k = x.shape[1]
    salida = np.empty((k, 3), dtype=np.float64)
    for j in range(k):
        w = None if pesos is None else np.asarray(pesos)[:, j]
        salida[j] = triangulate(P, x[:, j, :], w)
    return salida


def project(proyeccion: np.ndarray, puntos3d: np.ndarray) -> np.ndarray:
    """Proyecta puntos 3D con una matriz `(3, 4)`. Devuelve `(K, 2)`."""
    X = np.asarray(puntos3d, dtype=np.float64).reshape(-1, 3)
    Xh = np.hstack([X, np.ones((len(X), 1))])
    p = Xh @ np.asarray(proyeccion, dtype=np.float64).T
    with np.errstate(invalid="ignore", divide="ignore"):
        return p[:, :2] / p[:, 2:3]


def reprojection_error(
    proyecciones: np.ndarray,
    puntos: np.ndarray,
    puntos3d: np.ndarray,
) -> np.ndarray:
    """Error de reproyección en píxeles, por punto: `(K,)`.

    Es lo que permite al consumidor decidir si confía en un landmark. Sin esta
    medida, un codo bien medido y uno reconstruido a duras penas desde dos
    vistas casi colineales son indistinguibles. Ver docs/triangulation.md.
    """
    P = np.asarray(proyecciones, dtype=np.float64)
    x = np.asarray(puntos, dtype=np.float64)
    errores = []
    for i in range(len(P)):
        pred = project(P[i], puntos3d)
        errores.append(np.linalg.norm(pred - x[i], axis=1))
    return np.nanmean(np.array(errores), axis=0)


def ray_angle_deg(
    proyeccion_a: np.ndarray,
    proyeccion_b: np.ndarray,
    punto3d: np.ndarray,
) -> float:
    """Ángulo entre los rayos de dos cámaras hacia un punto, en grados.

    Es lo que determina la incertidumbre de la triangulación, más que el número
    de cámaras. **Los dos extremos son igual de malos**: cerca de 0° los rayos
    son casi paralelos, cerca de 180° casi colineales, y en ambos casos la
    intersección queda indeterminada a lo largo de la línea de visión.
    """
    ca = camera_center(proyeccion_a)
    cb = camera_center(proyeccion_b)
    X = np.asarray(punto3d, dtype=np.float64).ravel()
    va = X - ca
    vb = X - cb
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na < 1e-12 or nb < 1e-12:
        return 0.0
    cos = float(np.clip(np.dot(va, vb) / (na * nb), -1.0, 1.0))
    return float(np.degrees(np.arccos(cos)))


def camera_center(proyeccion: np.ndarray) -> np.ndarray:
    """Centro óptico de una cámara a partir de su matriz `(3, 4)`."""
    P = np.asarray(proyeccion, dtype=np.float64)
    _, _, Vt = np.linalg.svd(P)
    C = Vt[-1]
    return C[:3] / C[3]


def angulo_utilizable(angulo_deg: float) -> bool:
    """¿El ángulo entre rayos está en la zona donde la triangulación informa?"""
    return ANGULO_MIN_DEG <= angulo_deg <= ANGULO_MAX_DEG


def grid_spacing(puntos3d: np.ndarray, cols: int, rows: int) -> tuple[float, float]:
    """Separación media entre puntos contiguos de una rejilla reconstruida.

    Sirve como **comprobación métrica absoluta** de una calibración: si se
    triangulan las esquinas de un tablero cuya casilla mide 24 mm y la
    reconstrucción da 24 mm, la cadena entera —intrínsecos, extrínsecos y
    escala— es correcta. Ningún residual de reproyección prueba eso: un error
    de escala reproyecta perfectamente.

    Args:
        puntos3d: `(cols*rows, 3)` en orden de fila.
        cols, rows: forma de la rejilla.

    Returns:
        `(media, desviación)` en las mismas unidades que `puntos3d`.
    """
    X = np.asarray(puntos3d, dtype=np.float64).reshape(rows, cols, 3)
    d_h = np.linalg.norm(np.diff(X, axis=1), axis=2).ravel()
    d_v = np.linalg.norm(np.diff(X, axis=0), axis=2).ravel()
    d = np.concatenate([d_h, d_v])
    d = d[np.isfinite(d)]
    if d.size == 0:
        return float("nan"), float("nan")
    return float(d.mean()), float(d.std())
