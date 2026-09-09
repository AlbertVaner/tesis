"""Adaptador pequeño de MediaPipe Pose para video en tiempo real."""

from __future__ import annotations

import cv2

try:
    import mediapipe as mp

    _mp_pose = mp.solutions.pose
except (AttributeError, ImportError):
    try:
        from mediapipe.python import solutions as _solutions
    except ImportError as error:
        # MediaPipe 1.0 elimino `mp.solutions`. Este subsistema usa 0.10.14,
        # la del `.venv` de `tesis`. El sintoma tipico es haber activado el
        # `.venv` de `mapeo_tridimensional_con_camaras` (mediapipe 1.0) y
        # haber cambiado de carpeta: el prompt muestra `(.venv)` igual.
        import sys

        version = getattr(mp, "__version__", "desconocida")
        raise ImportError(
            f"mediapipe {version} en {sys.executable} no trae `mp.solutions`; "
            "external/gesture_detection necesita mediapipe 0.10.14. Ejecuta con "
            r"el interprete de tesis: .\.venv\Scripts\python.exe <script>, "
            r"o activa ese entorno: deactivate; .\.venv\Scripts\Activate.ps1"
        ) from error

    _mp_pose = _solutions.pose


class PoseDetector:
    """Convierte frames BGR en landmarks sin aplicar clasificación."""

    def __init__(
        self,
        min_detection_confidence: float = 0.6,
        min_tracking_confidence: float = 0.6,
        model_complexity: int = 1,
    ):
        self._pose = _mp_pose.Pose(
            static_image_mode=False,
            model_complexity=model_complexity,
            enable_segmentation=False,
            min_detection_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )

    @property
    def landmark_enum(self):
        return _mp_pose.PoseLandmark

    @property
    def connections(self):
        return _mp_pose.POSE_CONNECTIONS

    def process(self, frame):
        landmarks, _world = self.process_full(frame)
        return landmarks

    def process_full(self, frame):
        """Devuelve `(landmarks, world_landmarks)`, o `(None, None)`.

        `pose_landmarks` esta normalizado al encuadre y sirve para dibujar.
        `pose_world_landmarks` esta en **metros**, centrado en la cadera, y es
        el unico que permite razonar en 3D; es lo que consume
        `pose/normalize.py`. Una sola inferencia produce los dos, asi que no
        hay motivo para llamar dos veces.
        """
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        rgb_frame.flags.writeable = False
        results = self._pose.process(rgb_frame)
        rgb_frame.flags.writeable = True

        if results.pose_landmarks is None:
            return None, None
        world = getattr(results, "pose_world_landmarks", None)
        return results.pose_landmarks.landmark, (
            None if world is None else world.landmark
        )

    def close(self) -> None:
        self._pose.close()

    def __enter__(self) -> "PoseDetector":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

