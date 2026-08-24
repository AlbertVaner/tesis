"""Proceso de vision: OpenCV/MediaPipe no comparte el nucleo del control."""

from __future__ import annotations

import sys
import os
import time
import traceback
from pathlib import Path

from .protocol import (
    FLIGHT_COMMANDS,
    GESTURE_MOVES,
    STOP_HOLD_S,
    safe_put,
)


def camera_worker(camera_index: int, mode: str, gesture_queue, emergency_event, shutdown_event) -> None:
    """Detecta gestos y emite intenciones; nunca conoce objetos Crazyflie."""
    import cv2

    root_dir = Path(__file__).resolve().parents[2]
    gesture_dir = root_dir / "Gesture_control"
    if str(gesture_dir) not in sys.path:
        sys.path.insert(0, str(gesture_dir))

    from config import MIN_DETECTION_CONFIDENCE, MIN_TRACKING_CONFIDENCE
    from hand_gesture_detector import HandGestureDetector
    from hand_tracker import HandTracker

    cap = cv2.VideoCapture(camera_index)
    tracker = None
    failed = False
    try:
        if not cap.isOpened():
            raise RuntimeError(f"no se pudo abrir la camara {camera_index}")
        tracker = HandTracker(
            max_num_hands=2,
            min_detection_confidence=MIN_DETECTION_CONFIDENCE,
            min_tracking_confidence=MIN_TRACKING_CONFIDENCE,
        )
        detectors = {
            "Right": HandGestureDetector(tracker.landmark_enum),
            "Left": HandGestureDetector(tracker.landmark_enum),
        }
        active_command: dict[str, str | None] = {"Right": None, "Left": None}
        stop_started_at = None
        next_sample = 0.0
        previous_frame_at = time.monotonic()
        camera_fps = 0.0
        feedback = "Camara lista. Q = EMERGENCIA"
        safe_put(gesture_queue, _camera_event("CAMERA_READY", feedback), important=True)

        while not shutdown_event.is_set() and not emergency_event.is_set():
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError("la camara dejo de entregar imagenes")
            frame = cv2.flip(frame, 1)
            annotated, detected = tracker.process_hands(frame)
            by_hand = {"Right": None, "Left": None}
            for landmarks, handedness in detected:
                if handedness in by_hand and by_hand[handedness] is None:
                    by_hand[handedness] = landmarks

            now = time.monotonic()
            frame_interval = max(1e-6, now - previous_frame_at)
            previous_frame_at = now
            instantaneous_fps = 1.0 / frame_interval
            camera_fps = instantaneous_fps if camera_fps == 0.0 else 0.90 * camera_fps + 0.10 * instantaneous_fps
            hand_data: dict[str, tuple[str, str]] = {}
            detections = {}
            for hand, detector in detectors.items():
                raw, filtered, debug = detector.detect(by_hand[hand], hand)
                hand_data[hand] = (raw, filtered)
                stable = raw == filtered
                detections[hand] = (detector, raw, filtered, debug, stable)

            # Primero se clasifican ambas manos. Si cualquiera muestra STOP,
            # ese frame no puede emitir simultaneamente una orden de vuelo de
            # la otra mano.
            stable_stop = any(
                stable and filtered == detector.STOP
                for detector, _raw, filtered, _debug, stable in detections.values()
            )

            for hand, (detector, raw, filtered, debug, stable) in detections.items():
                controls_in_mode = mode == "independent" or hand == "Right"
                if stable and controls_in_mode:
                    desired = (
                        filtered
                        if not stable_stop and filtered in FLIGHT_COMMANDS
                        else None
                    )
                    previous = active_command[hand]
                    if desired != previous:
                        if previous in GESTURE_MOVES:
                            safe_put(
                                gesture_queue,
                                {
                                    "kind": "gesture_release",
                                    "timestamp": now,
                                    "hand": hand,
                                    "command": previous,
                                    "mode": mode,
                                    "camera_fps": camera_fps,
                                },
                                important=True,
                            )
                        active_command[hand] = desired
                        if desired is not None:
                            message = {
                                "kind": "gesture",
                                "timestamp": now,
                                "hand": hand,
                                "raw": raw,
                                "filtered": filtered,
                                "command": desired,
                                "mode": mode,
                                "camera_fps": camera_fps,
                                "debug": debug,
                            }
                            if safe_put(gesture_queue, message, important=True):
                                if desired in GESTURE_MOVES:
                                    feedback = f"{hand}: {desired} sostenido"
                                else:
                                    feedback = f"{hand}: {desired} enviado"
                        elif previous in GESTURE_MOVES:
                            feedback = f"{hand}: {previous} liberado"

                if now >= next_sample:
                    safe_put(
                        gesture_queue,
                        {
                            "kind": "gesture_sample",
                            "timestamp": now,
                            "hand": hand,
                            "raw": raw,
                            "filtered": filtered,
                            "mode": mode,
                            "camera_fps": camera_fps,
                            "debug": debug,
                        },
                    )

            if now >= next_sample:
                next_sample = now + 0.10

            if stable_stop:
                if stop_started_at is None:
                    stop_started_at = now
                    feedback = "STOP detectado: manten el puno 0.5 s"
                elif now - stop_started_at >= STOP_HOLD_S:
                    feedback = "EMERGENCIA POR GESTO"
                    safe_put(gesture_queue, _camera_event("GESTURE_EMERGENCY", feedback), important=True)
                    emergency_event.set()
                    break
            else:
                stop_started_at = None

            _draw_overlay(cv2, annotated, mode, hand_data, feedback)
            cv2.imshow("Gestos multiproceso - dos Crazyflies", annotated)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                feedback = "EMERGENCIA solicitada con Q"
                safe_put(gesture_queue, _camera_event("KEYBOARD_EMERGENCY", feedback), important=True)
                emergency_event.set()
                break
    except Exception as exc:
        failed = True
        safe_put(
            gesture_queue,
            _camera_event("CAMERA_FAILED", str(exc), traceback=traceback.format_exc()),
            important=True,
        )
        emergency_event.set()
    finally:
        cap.release()
        cv2.destroyAllWindows()
        if tracker is not None:
            tracker.close()
        safe_put(
            gesture_queue,
            _camera_event("CAMERA_STOPPED", "camara finalizada", failed=failed),
            important=True,
        )


def _camera_event(event: str, message: str, **extra):
    return {
        "kind": "camera_event",
        "pid": os.getpid(),
        "timestamp": time.monotonic(),
        "event": event,
        "message": message,
        **extra,
    }


def _draw_overlay(cv2, frame, mode: str, hand_data: dict[str, tuple[str, str]], feedback: str) -> None:
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (frame.shape[1], 145), (12, 30, 12), -1)
    cv2.addWeighted(overlay, 0.72, frame, 0.28, 0, frame)
    title = "MULTIPROCESO - DOS CRAZYFLIES"
    cv2.putText(frame, title, (12, 27), cv2.FONT_HERSHEY_SIMPLEX, 0.68, (235, 255, 235), 2)
    mode_text = "Right -> ambos" if mode == "both" else "Right -> Dron 1 | Left -> Dron 2"
    cv2.putText(frame, f"Modo: {mode_text}", (12, 54), cv2.FONT_HERSHEY_SIMPLEX, 0.51, (180, 240, 180), 1)
    y = 80
    for hand in ("Right", "Left"):
        raw, filtered = hand_data.get(hand, ("SIN_DETECCION", "SIN_DETECCION"))
        cv2.putText(frame, f"{hand}: {filtered} (raw: {raw})", (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (240, 240, 240), 1)
        y += 22
    cv2.putText(frame, feedback[:96], (12, 137), cv2.FONT_HERSHEY_SIMPLEX, 0.43, (70, 225, 255), 1)
