"""Compatibilidad con la interfaz corporal anterior."""

from pose.detector import PoseDetector
from visualization.pose_overlay import draw_pose


class PoseTracker(PoseDetector):
    def __init__(self, min_detection_confidence=0.6, min_tracking_confidence=0.6):
        super().__init__(
            min_detection_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )

    def process(self, frame):
        landmarks = super().process(frame)
        annotated_frame = frame.copy()
        draw_pose(annotated_frame, landmarks, self.connections)
        return annotated_frame, landmarks
