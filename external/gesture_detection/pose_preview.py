"""Primer prototipo: webcam -> MediaPipe Pose -> métricas visuales."""

from __future__ import annotations

import argparse
import time
from collections import deque

import cv2

from capture.webcam import WebcamCapture
from config import MIN_DETECTION_CONFIDENCE, MIN_TRACKING_CONFIDENCE
from hand_tracker import HandTracker
from pose.detector import PoseDetector
from visualization.hand_metrics import analyze_hand, draw_hand_metrics_panel
from visualization.pose_overlay import (
    draw_pose,
    draw_status_panel,
    key_landmark_visibilities,
)


class FpsMeter:
    """Calcula FPS mediante un promedio móvil para evitar parpadeos."""

    def __init__(self, window_size: int = 30):
        self._timestamps: deque[float] = deque(maxlen=window_size + 1)

    def update(self) -> float:
        self._timestamps.append(time.perf_counter())
        if len(self._timestamps) < 2:
            return 0.0
        elapsed = self._timestamps[-1] - self._timestamps[0]
        return (len(self._timestamps) - 1) / elapsed if elapsed > 0 else 0.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Visualiza MediaPipe Pose y ambas manos sin clasificar gestos "
            "ni controlar drones."
        )
    )
    parser.add_argument(
        "--camera",
        type=int,
        default=None,
        help="Índice de webcam. Si se omite, se busca automáticamente.",
    )
    parser.add_argument(
        "--max-camera-index",
        type=int,
        default=5,
        help="Último índice que se prueba durante la detección automática (default: 5).",
    )
    parser.add_argument(
        "--no-mirror",
        action="store_true",
        help="No reflejar horizontalmente la vista previa.",
    )
    return parser.parse_args()


def run(camera_index: int | None, max_camera_index: int, mirror: bool) -> None:
    fps_meter = FpsMeter()

    with WebcamCapture.open(camera_index, max_camera_index) as camera, PoseDetector(
        min_detection_confidence=MIN_DETECTION_CONFIDENCE,
        min_tracking_confidence=MIN_TRACKING_CONFIDENCE,
    ) as detector:
        hand_tracker = HandTracker(
            max_num_hands=2,
            min_detection_confidence=MIN_DETECTION_CONFIDENCE,
            min_tracking_confidence=MIN_TRACKING_CONFIDENCE,
        )
        try:
            print(f"Cámara {camera.camera_index} abierta.")
            print("Vista previa de cuerpo y manos iniciada. Presiona Q para salir.")
            print("Este modo no clasifica gestos y no se conecta al Crazyflie.")

            while True:
                success, frame = camera.read()
                if not success:
                    raise RuntimeError(
                        f"Se perdió la imagen de la cámara {camera.camera_index}."
                    )

                if mirror:
                    frame = cv2.flip(frame, 1)

                landmarks = detector.process(frame)
                annotated_frame, detected_hands = (
                    hand_tracker.process_hands_with_confidence(frame)
                )
                hand_metrics = [
                    analyze_hand(
                        hand_landmarks,
                        hand_tracker.landmark_enum,
                        handedness,
                        confidence,
                    )
                    for hand_landmarks, handedness, confidence in detected_hands
                ]

                draw_pose(annotated_frame, landmarks, detector.connections)
                visibilities = key_landmark_visibilities(
                    landmarks,
                    detector.landmark_enum,
                )
                draw_status_panel(
                    annotated_frame,
                    fps=fps_meter.update(),
                    camera_index=camera.camera_index,
                    visibilities=visibilities,
                    pose_detected=landmarks is not None,
                )
                draw_hand_metrics_panel(annotated_frame, hand_metrics)

                cv2.imshow("Vista previa de cuerpo y manos", annotated_frame)
                if cv2.waitKey(1) & 0xFF in (ord("q"), ord("Q")):
                    break
        finally:
            hand_tracker.close()


def main() -> int:
    args = parse_args()
    try:
        run(
            camera_index=args.camera,
            max_camera_index=args.max_camera_index,
            mirror=not args.no_mirror,
        )
    except (RuntimeError, ValueError) as error:
        print(f"Error: {error}")
        return 1
    finally:
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
