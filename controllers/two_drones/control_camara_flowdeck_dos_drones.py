"""Control por cámara de uno o dos Crazyflies con Flow deck, sin Robotat."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import cflib.crtp


MODULE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = MODULE_DIR.parents[1]
GESTURE_DIR = PROJECT_DIR / "external" / "gesture_detection"
for directory in (MODULE_DIR, GESTURE_DIR):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from config import CAMERA_INDEX, MIN_DETECTION_CONFIDENCE, MIN_TRACKING_CONFIDENCE  # noqa: E402
from flowdeck_dual_backend import FlowDroneConfig, FlowDroneController  # noqa: E402
from hand_gesture_detector import HandGestureDetector  # noqa: E402
from hand_tracker import HandTracker  # noqa: E402
from panel_control_flowdeck_dos_drones import resolve_uris  # noqa: E402
from utils import calculate_fps  # noqa: E402


WINDOW_NAME = "Control por camara - Dos drones Flow deck"
SPEED_XY = 0.18
SPEED_Z = 0.10
STOP_HOLD_S = 0.60


def gesture_velocity(detector: HandGestureDetector, gesture: str) -> tuple[float, float, float] | None:
    return {
        detector.ADELANTE: (SPEED_XY, 0.0, 0.0),
        detector.ATRAS: (-SPEED_XY, 0.0, 0.0),
        detector.IZQUIERDA: (0.0, SPEED_XY, 0.0),
        detector.DERECHA: (0.0, -SPEED_XY, 0.0),
        detector.ARRIBA: (0.0, 0.0, SPEED_Z),
        detector.ABAJO: (0.0, 0.0, -SPEED_Z),
    }.get(gesture)


def wait_for_preflight(controllers: list[FlowDroneController], timeout: float = 25.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if all(controller.ready for controller in controllers):
            return
        errors = [controller for controller in controllers if controller.state == "ERROR"]
        if errors:
            details = "; ".join(f"{c.config.name}: {c.state}" for c in errors)
            raise RuntimeError(f"falló el preflight: {details}")
        time.sleep(0.1)
    raise RuntimeError("los drones no terminaron el preflight en 25 segundos")


def targets_for_mode(mode: str) -> tuple[int, ...]:
    if mode == "drone1":
        return (0,)
    if mode == "drone2":
        return (1,)
    return (0, 1)


def draw_panel(frame, controllers: list[FlowDroneController], statuses: list[str], fps: float) -> None:
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (frame.shape[1], 190), (18, 18, 18), -1)
    cv2.addWeighted(overlay, 0.72, frame, 0.28, 0, frame)
    lines = [
        "CONTROL POR CAMARA - FLOW DECK SIN ROBOTAT",
        f"Dron 1: {controllers[0].state} | Dron 2: {controllers[1].state} | FPS: {fps:.1f}",
        statuses[0] if statuses else "Sin manos detectadas = hover",
        statuses[1] if len(statuses) > 1 else "",
        "q = aterrizar y salir | puno 0.6 s = EMERGENCIA",
    ]
    for index, line in enumerate(lines):
        color = (80, 220, 255) if index == 4 else (240, 240, 240)
        cv2.putText(frame, line, (12, 28 + index * 36), cv2.FONT_HERSHEY_SIMPLEX, 0.52, color, 2)


def camera_loop(
    controllers: list[FlowDroneController], active_indices: tuple[int, ...], mode: str, camera: int
) -> None:
    capture = cv2.VideoCapture(camera)
    if not capture.isOpened():
        raise RuntimeError(f"no se pudo abrir la cámara {camera}")
    tracker = HandTracker(
        max_num_hands=2 if mode == "hands" else 1,
        min_detection_confidence=MIN_DETECTION_CONFIDENCE,
        min_tracking_confidence=MIN_TRACKING_CONFIDENCE,
    )
    detectors = {
        "Left": HandGestureDetector(tracker.landmark_enum),
        "Right": HandGestureDetector(tracker.landmark_enum),
        "single": HandGestureDetector(tracker.landmark_enum),
    }
    stop_started: dict[int, float | None] = {0: None, 1: None}
    previous_frame_time = 0.0
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW_NAME, 1000, 740)

    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                raise RuntimeError("la cámara dejó de entregar imágenes")
            frame = cv2.flip(frame, 1)
            annotated, hands = tracker.process_hands(frame)
            fps, previous_frame_time = calculate_fps(previous_frame_time)
            assignments: list[tuple[object, str, tuple[int, ...]]] = []

            if mode == "hands":
                for landmarks, handedness in hands:
                    if handedness == "Left":
                        assignments.append((landmarks, "Left", (0,)))
                    elif handedness == "Right":
                        assignments.append((landmarks, "Right", (1,)))
            elif hands:
                landmarks, _handedness = hands[0]
                assignments.append((landmarks, "single", active_indices))

            seen: set[int] = set()
            statuses: list[str] = []
            emergency_triggered = False
            for landmarks, detector_key, indices in assignments:
                detector = detectors[detector_key]
                raw, gesture, _debug = detector.detect(landmarks, detector_key)
                shown = gesture
                velocity = gesture_velocity(detector, gesture)
                for index in indices:
                    seen.add(index)
                    controller = controllers[index]
                    if gesture == detector.STOP and controller.flying:
                        if stop_started[index] is None:
                            stop_started[index] = time.monotonic()
                        held = time.monotonic() - (stop_started[index] or time.monotonic())
                        shown = f"CONFIRMANDO_STOP {held:.1f}/{STOP_HOLD_S:.1f}s"
                        controller.velocity(0.0, 0.0, 0.0)
                        if held >= STOP_HOLD_S:
                            controller.emergency_stop()
                            emergency_triggered = True
                    else:
                        stop_started[index] = None
                        if gesture == detector.DESPEGAR:
                            controller.takeoff()
                        elif gesture == detector.ATERRIZAR:
                            controller.land()
                        elif velocity is not None:
                            controller.velocity(*velocity)
                        else:
                            controller.velocity(0.0, 0.0, 0.0)
                names = "+".join(f"D{i + 1}" for i in indices)
                statuses.append(f"{detector_key}: {shown} -> {names} (raw {raw})")

            for index in active_indices:
                if index not in seen:
                    controllers[index].velocity(0.0, 0.0, 0.0)
                    stop_started[index] = None

            draw_panel(annotated, controllers, statuses, fps)
            cv2.imshow(WINDOW_NAME, annotated)
            if emergency_triggered:
                print("Parada de emergencia confirmada por cámara.")
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
            if cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        capture.release()
        tracker.close()
        cv2.destroyAllWindows()


def main() -> int:
    parser = argparse.ArgumentParser(description="Cámara para dos drones con Flow deck")
    parser.add_argument(
        "--target",
        choices=("hands", "drone1", "drone2", "both"),
        default="hands",
        help="hands: mano izquierda=Dron 1 y derecha=Dron 2; both: una mano controla ambos",
    )
    parser.add_argument("--camera", type=int, default=CAMERA_INDEX)
    parser.add_argument("--uri1")
    parser.add_argument("--uri2")
    args = parser.parse_args()

    controllers: list[FlowDroneController] = []
    try:
        cflib.crtp.init_drivers(enable_debug_driver=False)
        uri1, uri2 = resolve_uris(args.uri1, args.uri2)
        controllers = [
            FlowDroneController(
                FlowDroneConfig("Dron 1", uri1),
                lambda state, message: print(f"[Dron 1] {state}: {message}"),
            ),
            FlowDroneController(
                FlowDroneConfig("Dron 2", uri2),
                lambda state, message: print(f"[Dron 2] {state}: {message}"),
            ),
        ]
        active_indices = targets_for_mode(args.target)
        active = [controllers[index] for index in active_indices]
        for controller in active:
            controller.connect()
        wait_for_preflight(active)
        camera_loop(controllers, active_indices, args.target, args.camera)
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    finally:
        for controller in controllers:
            controller.close()
        for controller in controllers:
            controller.join()


if __name__ == "__main__":
    raise SystemExit(main())
