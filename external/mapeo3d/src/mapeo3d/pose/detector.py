"""Estimación de landmarks 2D con MediaPipe Pose (Tasks API).

Una instancia por cámara. El detector no sabe que hay más cámaras: recibe una
imagen y devuelve `Landmarks2D`. La agregación multivista es de
`triangulation/`. Ver AGENTS.md, punto 3.

Por qué la Tasks API y no `mp.solutions`
----------------------------------------
**`mediapipe` 1.0 eliminó `mp.solutions` por completo.** El código que hace
`mp.solutions.pose.Pose(...)` —incluido el de `external/gesture_detection/` en
el repositorio `tesis`— sólo funciona con 0.10.x. Este módulo usa la Tasks API,
que además es la que encaja con seis cámaras: `RunningMode.VIDEO` mantiene el
tracking entre frames por instancia, y cada cámara tiene la suya.

El modelo va aparte
-------------------
A diferencia de `mp.solutions`, la Tasks API **no trae el modelo incluido**: hay
que darle un archivo `.task`. Se busca, en orden: el argumento explícito, la
variable de entorno ``MAPEO3D_POSE_MODEL``, y `models/` en la raíz del
repositorio. Si no aparece, el error dice de dónde descargarlo en lugar de
fallar por dentro de MediaPipe.

Costo medido
------------
En un Intel de 24 núcleos, frames de 1280x720, un proceso por cámara:

    procesos    lite (ms/frame)   full (ms/frame)
        1            12.6              24.9
        2            13.9              26.4
        4            16.2              30.1
        6            19.1              33.9

Con seis cámaras: 52 fps por cámara con `lite`, 29.5 con `full`. El escalado es
casi lineal, así que el cuello de botella de un sistema de seis no es la
inferencia sino la decodificación de los seis streams. Ver docs/pose.md.
"""

from __future__ import annotations

import os
from pathlib import Path

import cv2
import numpy as np

from .landmarks import Landmarks2D

RAIZ = Path(__file__).resolve().parents[3]

# Nombres de archivo que se buscan en `models/`, del más barato al más caro.
MODELOS_CONOCIDOS = (
    "pose_landmarker_lite.task",
    "pose_landmarker_full.task",
    "pose_landmarker_heavy.task",
)

URL_MODELOS = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_lite/float16/latest/pose_landmarker_lite.task"
)


class ModeloNoEncontrado(FileNotFoundError):
    """No hay un archivo `.task` con el que construir el detector."""


def resolver_modelo(ruta: str | Path | None = None) -> Path:
    """Localiza el `.task` del modelo de pose."""
    if ruta is not None:
        p = Path(ruta)
        if not p.exists():
            raise ModeloNoEncontrado(f"No existe el modelo: {p}")
        return p

    del_entorno = os.environ.get("MAPEO3D_POSE_MODEL")
    if del_entorno:
        p = Path(del_entorno)
        if not p.exists():
            raise ModeloNoEncontrado(
                f"MAPEO3D_POSE_MODEL apunta a {p}, que no existe."
            )
        return p

    for nombre in MODELOS_CONOCIDOS:
        p = RAIZ / "models" / nombre
        if p.exists():
            return p

    raise ModeloNoEncontrado(
        "No se encontró el modelo de pose. La Tasks API de MediaPipe no lo "
        "trae incluido.\n\n"
        "Descargarlo una vez:\n"
        "  mkdir models\n"
        f"  curl -L -o models/pose_landmarker_lite.task {URL_MODELOS}\n\n"
        "O indicar otra ubicación con --model o con la variable de entorno "
        "MAPEO3D_POSE_MODEL."
    )


class PoseDetector:
    """MediaPipe Pose sobre una cámara.

    Uso::

        with PoseDetector(camera="cam1") as det:
            lm = det.detect(frame_bgr, timestamp_s)
            if lm is not None:
                pix = lm.to_pixels()

    Args:
        model_path: `.task` a usar. Por defecto se resuelve solo.
        camera: nombre, sólo para etiquetar el resultado.
        min_deteccion, min_presencia, min_tracking: umbrales de MediaPipe.
        con_world: pedir también `pose_world_landmarks`, la estimación
            monocular en metros. Cuesta lo mismo —MediaPipe ya la calcula— y es
            la referencia contra la que se compara la triangulación.
    """

    def __init__(
        self,
        model_path: str | Path | None = None,
        *,
        camera: str = "cam",
        min_deteccion: float = 0.5,
        min_presencia: float = 0.5,
        min_tracking: float = 0.5,
        con_world: bool = True,
    ) -> None:
        # Importar aquí y no arriba: permite importar el paquete, correr las
        # pruebas y usar el resto del pipeline en una máquina sin MediaPipe.
        from mediapipe.tasks.python.core.base_options import BaseOptions
        from mediapipe.tasks.python.vision import (
            PoseLandmarker,
            PoseLandmarkerOptions,
            RunningMode,
        )

        self.camera = camera
        self.con_world = con_world
        self.model_path = resolver_modelo(model_path)
        self._landmarker = PoseLandmarker.create_from_options(
            PoseLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(self.model_path)),
                running_mode=RunningMode.VIDEO,
                num_poses=1,
                min_pose_detection_confidence=min_deteccion,
                min_pose_presence_confidence=min_presencia,
                min_tracking_confidence=min_tracking,
                output_segmentation_masks=False,
            )
        )
        # RunningMode.VIDEO exige marcas de tiempo en milisegundos
        # ESTRICTAMENTE crecientes. A 30 fps dos frames consecutivos distan 33
        # ms y no hay problema, pero al redondear a entero dos frames cercanos
        # pueden caer en el mismo milisegundo y MediaPipe lanza una excepción
        # que aborta la cámara entera. Se lleva un contador propio.
        self._ultimo_ms = -1

    # ---------------------------------------------------------------- uso

    def detect(
        self, imagen_bgr: np.ndarray, timestamp_s: float
    ) -> Landmarks2D | None:
        """Devuelve los landmarks de un frame, o `None` si no hay persona.

        Args:
            imagen_bgr: frame tal como lo entrega OpenCV.
            timestamp_s: marca de tiempo de llegada, en segundos, monotónica.
        """
        import mediapipe as mp

        alto, ancho = imagen_bgr.shape[:2]
        rgb = cv2.cvtColor(imagen_bgr, cv2.COLOR_BGR2RGB)
        imagen = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

        ms = max(int(timestamp_s * 1000.0), self._ultimo_ms + 1)
        self._ultimo_ms = ms

        res = self._landmarker.detect_for_video(imagen, ms)
        if not res.pose_landmarks:
            return None

        puntos = res.pose_landmarks[0]
        xy = np.array([[p.x, p.y] for p in puntos], dtype=np.float64)
        vis = np.array([_o_cero(p.visibility) for p in puntos], dtype=np.float64)
        pre = np.array([_o_cero(p.presence) for p in puntos], dtype=np.float64)

        world = None
        if self.con_world and res.pose_world_landmarks:
            world = np.array(
                [[p.x, p.y, p.z] for p in res.pose_world_landmarks[0]],
                dtype=np.float64,
            )

        return Landmarks2D(
            xy=xy,
            visibility=vis,
            presence=pre,
            image_size=(ancho, alto),
            timestamp=timestamp_s,
            world=world,
            camera=self.camera,
        )

    def close(self) -> None:
        self._landmarker.close()

    def __enter__(self) -> "PoseDetector":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def _o_cero(v: float | None) -> float:
    """`visibility` y `presence` llegan como `None` en algunos modelos."""
    return 0.0 if v is None else float(v)
