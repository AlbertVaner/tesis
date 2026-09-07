"""Marco corporal: la pose vista desde el cuerpo y no desde la cámara.

`pose_world_landmarks` viene en metros pero **alineado con la cámara**: `x` a la
derecha, `y` abajo, `z` alejándose de *esa* cámara. La misma pose vista desde
dos cámaras separadas un ángulo produce dos juegos de números distintos,
girados justamente ese ángulo. Medido en el repositorio de mapeo, simulando una
segunda cámara del anillo del Robotat:

    ángulo entre cámaras    sin canonicalizar    canonicalizado
           10                     10.8 %             0.00 %
           60  (adyacentes)       62.0 %             0.00 %
          120                    107.4 %             0.00 %

Un 62 % es del orden del movimiento entero: cambiar de cámara a mitad de un
gesto corrompería cualquier ventana temporal de clasificación.

Este módulo construye ejes a partir del **propio cuerpo**: origen en el centro
de las caderas, `X` de la cadera derecha a la izquierda, `Y` hacia los hombros,
`Z` el producto vectorial, es decir hacia donde mira el operador. Lo que queda
no depende del punto de vista ni de la estatura, que es la condición previa
para cualquier clasificador (Ibañez et al. centran y normalizan por escala
corporal antes de clasificar).

Hace falta con una cámara o con seis: con una sola ya sirve, porque vuelve
comparables a dos sujetos de estatura distinta.

Lo que NO arregla
-----------------
Canonicalizar no mejora una vista mala; puede empeorarla. Si el operador está
de perfil el ancho de caderas se desploma, la dirección de `X` pasa a ser ruido
y la pose entera queda girada un ángulo arbitrario. Por eso `BodyFrame` expone
su `condition` y su `valid`, y por eso un marco mal condicionado se descarta en
lugar de usarse.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

# Índices de MediaPipe Pose. Se escriben literales para que el módulo no
# dependa de tener el enum de mediapipe cargado (por ejemplo, en pruebas).
LEFT_SHOULDER = 11
RIGHT_SHOULDER = 12
LEFT_ELBOW = 13
RIGHT_ELBOW = 14
LEFT_WRIST = 15
RIGHT_WRIST = 16
LEFT_HIP = 23
RIGHT_HIP = 24

N_LANDMARKS = 33

#: Los cuatro que definen el marco. Si alguno falta, no hay marco.
FRAME_LANDMARKS = (LEFT_HIP, RIGHT_HIP, LEFT_SHOULDER, RIGHT_SHOULDER)

# Ancho de caderas dividido por largo de torso. Por debajo de esto la dirección
# lateral está mal determinada y el marco gira de forma arbitraria.
#
# Fijado sobre dos grabaciones reales de 60 s. De frente la condición ronda
# 0.41-0.43 de mediana. Lo que hay por debajo del umbral es catastrófico, no
# mediocre:
#
#     umbral   frames que pasan   error de los que pasan   de los que NO
#      0.10        99.8 %               13.4 %                 33.9 %
#      0.18        97.9 %               13.0 %                 30.4 %
#      0.30        77.8 %               10.2 %                 24.7 %
#
# Es una puerta de validez, no un criterio de calidad: rechaza un 1-2 % y lo
# que rechaza tiene tres veces el error medio. Para *ordenar* vistas buenas
# entre sí no sirve; la `visibility` del modelo predice mejor (rho -0.75 frente
# a -0.28). Se toma 0.18 porque conserva el 98 % del material.
MIN_CONDITION = 0.18

#: Frames que acumula el estimador de escala antes de dar un valor. A 15-30 fps
#: son 2-4 s: suficiente para una mediana estable sin hacer esperar.
WARMUP_FRAMES = 45

#: Visibilidad mínima exigida a los landmarks que definen el marco.
MIN_VISIBILITY = 0.5


def landmarks_to_array(landmarks) -> tuple[np.ndarray, np.ndarray]:
    """Convierte los landmarks de MediaPipe en `(K, 3)` y `(K,)`.

    Sirve tanto para `pose_landmarks` (normalizados a la imagen) como para
    `pose_world_landmarks` (metros, centrados en la cadera).
    """
    if landmarks is None:
        return np.empty((0, 3)), np.empty((0,))
    points = np.array([[lm.x, lm.y, lm.z] for lm in landmarks], dtype=np.float64)
    visibility = np.array(
        [getattr(lm, "visibility", 1.0) for lm in landmarks], dtype=np.float64
    )
    return points, visibility


def yaw_camara(world: np.ndarray) -> float:
    """Hacia donde mira el cuerpo respecto de la camara, en grados.

    `pose_world_landmarks` viene alineado con la camara: `x` a la derecha, `z`
    alejandose. El eje de hombros proyectado en el plano horizontal da
    directamente el giro: de frente apunta a lo largo de `x` y vale 0; de
    perfil apunta a lo largo de `z` y vale +-90. El signo distingue hacia que
    lado se giro el sujeto.

    Sirve para **recuperar la orientacion de una grabacion sin depender de lo
    que se anoto a mano**, que es mas fiable que la etiqueta tecleada. Se
    promedian hombros y caderas porque cualquiera de los dos puede fallar en un
    frame suelto.
    """
    P = np.asarray(world, dtype=np.float64)
    if P.ndim == 2:
        P = P[None, ...]
    hombros = P[:, LEFT_SHOULDER] - P[:, RIGHT_SHOULDER]
    caderas = P[:, LEFT_HIP] - P[:, RIGHT_HIP]
    a = np.degrees(np.arctan2(hombros[:, 2], hombros[:, 0]))
    b = np.degrees(np.arctan2(caderas[:, 2], caderas[:, 0]))
    with np.errstate(invalid="ignore"):
        return float(np.nanmedian(np.nanmedian(np.stack([a, b]), axis=0)))


@dataclass
class BodyFrame:
    """Sistema de referencia anclado al cuerpo, en el instante de un frame."""

    origin: np.ndarray          #: (3,) centro de las caderas
    rotation: np.ndarray        #: (3,3) filas: X lateral, Y vertical, Z frontal
    hip_width_m: float
    torso_length_m: float

    @property
    def condition(self) -> float:
        """Cuán bien determinado está el eje lateral, en `[0, ~0.6]`.

        Es el ancho de caderas relativo al torso. De frente ronda 0.35-0.43; de
        perfil se desploma, y con él la fiabilidad de todo el marco.
        """
        if self.torso_length_m <= 1e-6:
            return 0.0
        return self.hip_width_m / self.torso_length_m

    @property
    def valid(self) -> bool:
        return self.condition >= MIN_CONDITION

    def apply(self, points: np.ndarray) -> np.ndarray:
        """Lleva puntos del marco de la cámara al marco del cuerpo."""
        P = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        return (P - self.origin) @ self.rotation.T


def body_frame(
    world: np.ndarray,
    visibility: np.ndarray | None = None,
    *,
    min_visibility: float = MIN_VISIBILITY,
) -> BodyFrame | None:
    """Construye el marco del cuerpo, o `None` si no se puede.

    Devolver `None` es parte del contrato. Un marco inventado a partir de una
    cadera que el modelo no ve produce una pose plausible y equivocada, que es
    peor que no tener dato.
    """
    P = np.asarray(world, dtype=np.float64).reshape(-1, 3)
    idx = list(FRAME_LANDMARKS)
    if P.shape[0] <= max(idx) or not np.all(np.isfinite(P[idx])):
        return None
    if visibility is not None:
        v = np.asarray(visibility, dtype=np.float64).ravel()
        if v.size <= max(idx) or np.min(v[idx]) < min_visibility:
            return None

    hip_l, hip_r = P[LEFT_HIP], P[RIGHT_HIP]
    sho_l, sho_r = P[LEFT_SHOULDER], P[RIGHT_SHOULDER]

    origin = (hip_l + hip_r) / 2.0
    shoulders = (sho_l + sho_r) / 2.0

    # X: lateral, de la cadera DERECHA a la IZQUIERDA del sujeto. Se usa la
    # lateralidad anatómica que ya trae MediaPipe, no la de la imagen: es lo
    # que hace que el resultado no dependa de desde dónde se mire.
    x = hip_l - hip_r
    hip_width = float(np.linalg.norm(x))
    if hip_width < 1e-6:
        return None
    x = x / hip_width

    # Y: hacia los hombros, ortogonalizado contra X. Caderas y columna no son
    # perpendiculares exactas, y suponerlo metería una inclinación falsa.
    y = shoulders - origin
    torso = float(np.linalg.norm(y))
    y = y - np.dot(y, x) * x
    ny = float(np.linalg.norm(y))
    if ny < 1e-6 or torso < 1e-6:
        return None
    y = y / ny

    z = np.cross(x, y)
    return BodyFrame(origin, np.stack([x, y, z]), hip_width, torso)


class ScaleEstimator:
    """Escala corporal en vivo: mediana acumulada con calentamiento.

    Offline la escala se calcula de una vez sobre toda la sesión. En vivo no se
    puede, y usar el torso del frame actual reintroduce justo el ruido que se
    quería evitar: normalizar por frame empeoró la variación de longitudes de
    hueso de 10.4 % a 15.4 %. Este estimador acumula y, una vez caliente,
    devuelve una mediana que ya casi no se mueve.
    """

    def __init__(self, warmup: int = WARMUP_FRAMES, memory: int = 900) -> None:
        self.warmup = warmup
        self._lengths: deque[float] = deque(maxlen=memory)

    def observe(self, frame: BodyFrame | None) -> None:
        if frame is not None and frame.valid:
            self._lengths.append(frame.torso_length_m)

    @property
    def ready(self) -> bool:
        return len(self._lengths) >= self.warmup

    @property
    def scale_m(self) -> float:
        if not self._lengths:
            return float("nan")
        return float(np.median(self._lengths))

    @property
    def n(self) -> int:
        return len(self._lengths)


def normalize(canonical: np.ndarray, scale_m: float) -> np.ndarray:
    """Divide por la escala corporal. Deja la pose adimensional."""
    P = np.asarray(canonical, dtype=np.float64)
    if not np.isfinite(scale_m) or scale_m <= 1e-6:
        return np.full_like(P, np.nan)
    return P / scale_m
