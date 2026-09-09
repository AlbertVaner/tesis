"""Landmarks corporales 2D de una sola imagen, con su confianza.

Este módulo no sabe que existen varias cámaras, ni qué es RTSP, ni cómo se
triangula. Describe **el resultado de mirar una imagen**: dónde están las
articulaciones y cuánto se confía en cada una. Ver AGENTS.md, punto 3.

Convención de coordenadas
-------------------------
Las posiciones se guardan **normalizadas** en `[0, 1]` —`x` dividido por el
ancho, `y` por el alto— porque es lo que devuelve el backend y porque así el
resultado no depende de la resolución a la que se procesó. Quien triangula
necesita píxeles, y para eso está `to_pixels()`: la conversión ocurre una vez,
en un sitio, y no se reparte por el código llamante.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# Los 33 landmarks del modelo Pose de MediaPipe, en su orden canónico.
NOMBRES: tuple[str, ...] = (
    "nose",
    "left_eye_inner", "left_eye", "left_eye_outer",
    "right_eye_inner", "right_eye", "right_eye_outer",
    "left_ear", "right_ear",
    "mouth_left", "mouth_right",
    "left_shoulder", "right_shoulder",
    "left_elbow", "right_elbow",
    "left_wrist", "right_wrist",
    "left_pinky", "right_pinky",
    "left_index", "right_index",
    "left_thumb", "right_thumb",
    "left_hip", "right_hip",
    "left_knee", "right_knee",
    "left_ankle", "right_ankle",
    "left_heel", "right_heel",
    "left_foot_index", "right_foot_index",
)

N_LANDMARKS = len(NOMBRES)

INDICE = {nombre: i for i, nombre in enumerate(NOMBRES)}


# Segmentos de longitud aproximadamente constante, para validar la
# reconstrucción 3D **sin verdad de terreno**.
#
# El razonamiento es el que hace útil esta lista: un antebrazo mide lo mismo en
# todos los frames de una sesión, pase lo que pase con el sujeto. Así que la
# desviación estándar de su longitud reconstruida a lo largo de la sesión es
# una medida directa de la calidad de la triangulación, y no necesita MoCap, ni
# marcadores, ni un objeto de referencia en escena. Ver docs/triangulation.md.
#
# Sólo se listan segmentos entre articulaciones separadas por hueso. Nada que
# cruce la cabeza, las manos o los pies: ahí los landmarks son estimaciones de
# superficie y su separación cambia con la pose.
HUESOS: tuple[tuple[str, str], ...] = (
    ("left_shoulder", "left_elbow"),      # brazo
    ("right_shoulder", "right_elbow"),
    ("left_elbow", "left_wrist"),         # antebrazo
    ("right_elbow", "right_wrist"),
    ("left_hip", "left_knee"),            # muslo
    ("right_hip", "right_knee"),
    ("left_knee", "left_ankle"),          # pantorrilla
    ("right_knee", "right_ankle"),
    ("left_shoulder", "right_shoulder"),  # ancho de hombros
    ("left_hip", "right_hip"),            # ancho de caderas
    ("left_shoulder", "left_hip"),        # torso
    ("right_shoulder", "right_hip"),
)


# Esqueleto para dibujar. Se define aquí y no se importa de MediaPipe a
# propósito: es una constante de presentación, y traerla de la biblioteca
# obligaría a importar MediaPipe sólo para pintar una línea.
#
# Se omite el detalle de la cara (ojos, boca, orejas): son diez landmarks que
# no aportan nada a un gesto corporal y ensucian la vista.
CONEXIONES: tuple[tuple[str, str], ...] = (
    ("left_shoulder", "right_shoulder"),
    ("left_shoulder", "left_elbow"), ("left_elbow", "left_wrist"),
    ("right_shoulder", "right_elbow"), ("right_elbow", "right_wrist"),
    ("left_wrist", "left_thumb"), ("left_wrist", "left_index"),
    ("left_wrist", "left_pinky"), ("left_pinky", "left_index"),
    ("right_wrist", "right_thumb"), ("right_wrist", "right_index"),
    ("right_wrist", "right_pinky"), ("right_pinky", "right_index"),
    ("left_shoulder", "left_hip"), ("right_shoulder", "right_hip"),
    ("left_hip", "right_hip"),
    ("left_hip", "left_knee"), ("left_knee", "left_ankle"),
    ("right_hip", "right_knee"), ("right_knee", "right_ankle"),
    ("left_ankle", "left_heel"), ("left_heel", "left_foot_index"),
    ("left_ankle", "left_foot_index"),
    ("right_ankle", "right_heel"), ("right_heel", "right_foot_index"),
    ("right_ankle", "right_foot_index"),
)


def pares_de_conexiones() -> np.ndarray:
    """`CONEXIONES` como índices `(M, 2)`, para dibujar."""
    return np.array([[INDICE[a], INDICE[b]] for a, b in CONEXIONES], dtype=int)


def pares_de_huesos(
    huesos: tuple[tuple[str, str], ...] = HUESOS,
) -> np.ndarray:
    """Convierte `HUESOS` en índices `(M, 2)` para `triangulation.metrics`.

    `triangulation/` no conoce MediaPipe ni nombres de articulaciones: recibe
    pares de índices. Esta función es la frontera entre los dos vocabularios.
    """
    return np.array([[INDICE[a], INDICE[b]] for a, b in huesos], dtype=int)


@dataclass
class Landmarks2D:
    """Landmarks de **una** imagen de **una** cámara.

    Args:
        xy: `(K, 2)` normalizado a `[0, 1]`.
        visibility: `(K,)` probabilidad de que el landmark **no esté ocluido**.
            Es la que debe ponderar la vista al triangular: una cámara que
            apenas ve el codo tiene que influir poco, no igual.
        presence: `(K,)` probabilidad de que el landmark esté dentro del
            cuadro. Se conserva para filtrar, no para ponderar.
        image_size: `(ancho, alto)` de la imagen procesada, en píxeles.
        timestamp: segundos, reloj monotónico, el de llegada del frame.
        world: `(K, 3)` opcional, la estimación **monocular** de MediaPipe en
            metros con origen en el punto medio de las caderas. No está en el
            marco de la sala y su profundidad sale de un prior aprendido, no de
            geometría: sirve como referencia a comparar contra la
            triangulación, nunca como sustituto. Ver docs/architecture.md.
    """

    xy: np.ndarray
    visibility: np.ndarray
    presence: np.ndarray
    image_size: tuple[int, int]
    timestamp: float = 0.0
    world: np.ndarray | None = None
    camera: str = ""

    def __post_init__(self) -> None:
        self.xy = np.asarray(self.xy, dtype=np.float64).reshape(-1, 2)
        k = len(self.xy)
        self.visibility = np.asarray(self.visibility, dtype=np.float64).ravel()
        self.presence = np.asarray(self.presence, dtype=np.float64).ravel()
        if len(self.visibility) != k or len(self.presence) != k:
            raise ValueError(
                f"xy tiene {k} landmarks pero visibility "
                f"{len(self.visibility)} y presence {len(self.presence)}."
            )
        if self.world is not None:
            self.world = np.asarray(self.world, dtype=np.float64).reshape(-1, 3)

    @property
    def n(self) -> int:
        return len(self.xy)

    def to_pixels(self) -> np.ndarray:
        """`(K, 2)` en píxeles de la imagen original.

        Es lo que consume la triangulación, **después** de pasar por
        `CameraIntrinsics.undistort_points()`. Saltarse la rectificación no
        rompe nada visible pero sesga la escala; ver docs/triangulation.md.
        """
        ancho, alto = self.image_size
        return self.xy * np.array([float(ancho), float(alto)])

    def confianza(self) -> np.ndarray:
        """Peso `(K,)` para la triangulación ponderada.

        Es `visibility` a secas. MediaPipe la define como la probabilidad de
        que el landmark sea visible y **no esté ocluido**, que es exactamente
        el criterio por el que una vista debe pesar más o menos en el DLT.

        `presence` responde otra pregunta —si el landmark está dentro del
        cuadro— y **no vale siempre 1**: en la Tasks API se ha observado entre
        0.06 y 0.91 sobre una misma detección. Se expone para filtrar, pero no
        se multiplica: son dos preguntas distintas, y multiplicarlas penalizaría
        dos veces al mismo landmark contra el umbral absoluto `PESO_MINIMO` de
        `triangulation.robust`.
        """
        return self.visibility.copy()

    def __getitem__(self, nombre: str) -> np.ndarray:
        """Posición normalizada de un landmark por nombre."""
        return self.xy[INDICE[nombre]]
