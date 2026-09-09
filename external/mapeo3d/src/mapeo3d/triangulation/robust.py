"""Triangulación robusta de N vistas: ponderación, rechazo y aceptación.

El DLT desnudo de `dlt.py` trata todas las vistas por igual, y no todas merecen
lo mismo. Este módulo añade las tres capas que describe docs/triangulation.md,
en orden:

1. **Ponderación por confianza.** Cada vista pesa según lo que el estimador 2D
   diga de ese landmark.
2. **Rechazo de vistas discrepantes.** Un estimador 2D no falla suavemente:
   **alucina**. Confunde el codo izquierdo con el derecho, o pone una muñeca en
   un objeto del fondo, y lo reporta con confianza alta. Una sola vista así
   arrastra el punto varios centímetros. Se elimina la peor mientras su
   residual supere el umbral y queden vistas suficientes.
3. **Umbral de aceptación.** Un punto con pocas vistas, residual alto o
   geometría degenerada **no se reporta como válido**: sale `NaN` con
   confianza 0. Es mejor que el consumidor sepa que no hay dato a que reciba un
   número inventado.

Por qué el rechazo deja de ser opcional con seis cámaras
--------------------------------------------------------
Con las cámaras en anillo alrededor del operador, en todo momento **la mitad lo
ve de espaldas**. MediaPipe sigue devolviendo landmarks desde atrás, pero con
izquierda y derecha intercambiadas, y la confianza que reporta no refleja ese
error. Sin esta capa, las muñecas saltan de un lado al otro del cuerpo.

Este módulo sigue sin saber qué es RTSP ni qué es MediaPipe: recibe matrices de
proyección y puntos 2D **ya rectificados**. Ver la precondición en `dlt.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .dlt import (
    ANGULO_MAX_DEG,
    ANGULO_MIN_DEG,
    MIN_VISTAS,
    camera_center,
    project,
    triangulate,
)

# Residual por vista por encima del cual se sospecha que la vista alucinó.
# En píxeles, sobre la imagen a resolución de trabajo.
UMBRAL_VISTA_PX = 12.0

# Residual medio por encima del cual el punto entero no se acepta.
UMBRAL_PUNTO_PX = 8.0

# Una vista cuyo peso esté por debajo de esto no entra siquiera al ajuste.
PESO_MINIMO = 0.30


@dataclass
class Punto3D:
    """Un landmark reconstruido, con todo lo que hace falta para confiar en él.

    `residual`, `n_vistas` y `angulo_deg` no son detalles de depuración: son lo
    que permite al consumidor distinguir un codo bien medido de uno
    reconstruido a duras penas desde dos vistas casi colineales. Un sistema de
    control que no puede hacer esa distinción no es seguro.
    """

    xyz: np.ndarray
    residual: float
    n_vistas: int
    vistas: np.ndarray = field(default_factory=lambda: np.zeros(0, bool))
    angulo_deg: float = 0.0
    valido: bool = False

    @property
    def confianza(self) -> float:
        """`[0, 1]`, 0 si el punto no es utilizable."""
        if not self.valido:
            return 0.0
        return float(np.clip(1.0 - self.residual / UMBRAL_PUNTO_PX, 0.0, 1.0))


def angulo_util_deg(centros: np.ndarray, punto3d: np.ndarray) -> float:
    """Mejor ángulo de triangulación disponible entre pares de vistas.

    **Los dos extremos son igual de malos**: cerca de 0° los rayos son
    paralelos, cerca de 180° colineales, y en ambos casos la intersección queda
    indeterminada a lo largo de la línea de visión. Así que la calidad de un
    par es `min(θ, 180 − θ)`, y la del conjunto es la del mejor par: basta una
    pareja bien condicionada para fijar la profundidad.

    Con seis cámaras en anillo y el operador en el centro, los pares adyacentes
    dan 60° (óptimo), los siguientes 120° (que puntúan igual que 60°), y los
    opuestos 180° (inservibles como par, aunque cada cámara siga aportando su
    rayo al ajuste).
    """
    X = np.asarray(punto3d, dtype=np.float64).ravel()
    C = np.asarray(centros, dtype=np.float64).reshape(-1, 3)
    if len(C) < 2 or not np.all(np.isfinite(X)):
        return 0.0
    v = X - C
    n = np.linalg.norm(v, axis=1)
    bueno = n > 1e-12
    if bueno.sum() < 2:
        return 0.0
    u = v[bueno] / n[bueno, None]
    cos = np.clip(u @ u.T, -1.0, 1.0)
    ang = np.degrees(np.arccos(cos))
    np.fill_diagonal(ang, 0.0)
    return float(np.max(np.minimum(ang, 180.0 - ang)))


def triangulate_robust(
    proyecciones: np.ndarray,
    puntos: np.ndarray,
    pesos: np.ndarray | None = None,
    *,
    centros: np.ndarray | None = None,
    umbral_vista_px: float = UMBRAL_VISTA_PX,
    umbral_punto_px: float = UMBRAL_PUNTO_PX,
    peso_minimo: float = PESO_MINIMO,
    min_vistas: int = MIN_VISTAS,
    angulo_min: float = ANGULO_MIN_DEG,
    angulo_max: float = ANGULO_MAX_DEG,
) -> Punto3D:
    """Triangula un punto descartando las vistas que no encajan.

    Args:
        proyecciones: `(N, 3, 4)`.
        puntos: `(N, 2)` **rectificados**, en píxeles.
        pesos: `(N,)` en `[0, 1]`. Sin pesos, todas las vistas valen igual.
        centros: `(N, 3)` opcional, los centros ópticos ya calculados. Al
            triangular 33 landmarks con las mismas cámaras, recalcularlos por
            landmark cuesta 33 SVD innecesarias.

    Returns:
        `Punto3D`. Si no se pudo reconstruir, `xyz` es `NaN` y `valido` False.
    """
    P = np.asarray(proyecciones, dtype=np.float64)
    x = np.asarray(puntos, dtype=np.float64).reshape(-1, 2)
    n = len(P)
    w = (np.ones(n) if pesos is None
         else np.asarray(pesos, dtype=np.float64).ravel())
    if centros is None:
        centros = np.array([camera_center(p) for p in P])
    centros = np.asarray(centros, dtype=np.float64).reshape(-1, 3)

    nulo = Punto3D(np.full(3, np.nan), float("inf"), 0, np.zeros(n, bool))

    # Capa 1: fuera las vistas que ni siquiera dicen ver el landmark, y las que
    # traen coordenadas no finitas.
    vivos = [
        i for i in range(n)
        if w[i] >= peso_minimo and np.all(np.isfinite(x[i]))
    ]
    if len(vivos) < min_vistas:
        return nulo

    # Capa 2: ajustar, medir el residual de cada vista, tirar la peor, repetir.
    X = np.full(3, np.nan)
    residuales = np.zeros(0)
    while True:
        X = triangulate(P[vivos], x[vivos], w[vivos])
        if not np.all(np.isfinite(X)):
            return nulo
        residuales = np.array(
            [float(np.linalg.norm(project(P[i], X)[0] - x[i])) for i in vivos]
        )
        peor = int(np.argmax(residuales))
        if residuales[peor] <= umbral_vista_px or len(vivos) <= min_vistas:
            break
        vivos.pop(peor)

    # Capa 3: ¿es aceptable lo que quedó?
    mascara = np.zeros(n, bool)
    mascara[vivos] = True
    residual = float(np.mean(residuales))
    angulo = angulo_util_deg(centros[vivos], X)
    valido = bool(
        len(vivos) >= min_vistas
        and residual <= umbral_punto_px
        and angulo_min <= angulo <= angulo_max
    )
    if not valido:
        return Punto3D(np.full(3, np.nan), residual, len(vivos), mascara,
                       angulo, False)
    return Punto3D(X, residual, len(vivos), mascara, angulo, True)


def triangulate_landmarks(
    proyecciones: np.ndarray,
    puntos: np.ndarray,
    pesos: np.ndarray | None = None,
    **opciones,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Triangula K landmarks vistos por las mismas N cámaras.

    Args:
        proyecciones: `(N, 3, 4)`.
        puntos: `(N, K, 2)` rectificados, en píxeles.
        pesos: `(N, K)` opcional.

    Returns:
        `(xyz, residual, n_vistas, angulo, confianza)` con formas
        `(K, 3)`, `(K,)`, `(K,)`, `(K,)`, `(K,)`. Los landmarks no reconstruidos
        llevan `NaN` en `xyz` y 0 en `confianza`.
    """
    P = np.asarray(proyecciones, dtype=np.float64)
    x = np.asarray(puntos, dtype=np.float64)
    k = x.shape[1]
    w = None if pesos is None else np.asarray(pesos, dtype=np.float64)
    # Los centros ópticos no dependen del landmark: una vez, no K veces.
    centros = np.array([camera_center(p) for p in P])

    xyz = np.full((k, 3), np.nan)
    residual = np.full(k, np.inf)
    n_vistas = np.zeros(k, dtype=int)
    angulo = np.zeros(k)
    confianza = np.zeros(k)
    for j in range(k):
        r = triangulate_robust(
            P, x[:, j, :], None if w is None else w[:, j],
            centros=centros, **opciones,
        )
        xyz[j] = r.xyz
        residual[j] = r.residual
        n_vistas[j] = r.n_vistas
        angulo[j] = r.angulo_deg
        confianza[j] = r.confianza
    return xyz, residual, n_vistas, angulo, confianza
