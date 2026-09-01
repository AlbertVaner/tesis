"""Adaptador pequeño de MediaPipe Pose para video en tiempo real."""

from __future__ import annotations

import cv2

try:
    import mediapipe as mp

    _mp_pose = mp.solutions.pose
except (AttributeError, ImportError):
    from mediapipe.python import solutions as _solutions

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
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        rgb_frame.flags.writeable = False
        results = self._pose.process(rgb_frame)
        rgb_frame.flags.writeable = True

        if results.pose_landmarks is None:
            return None
        return results.pose_landmarks.landmark

    def close(self) -> None:
        self._pose.close()

    def __enter__(self) -> "PoseDetector":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

