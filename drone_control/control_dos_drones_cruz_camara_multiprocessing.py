r"""Control high-level de uno o dos Crazyflies mediante gestos de cámara.

La cámara vive en el proceso principal y un único proceso backend conserva la
propiedad de ambas Crazyradio. Por defecto la mano izquierda controla el dron
1 y la mano derecha controla el dron 2.

Prueba sin hardware:
    python .\drone_control\control_dos_drones_cruz_camara_multiprocessing.py --dry-run

Prueba real, una mano por dron:
    python .\drone_control\control_dos_drones_cruz_camara_multiprocessing.py

Prueba real con uno:
    python .\drone_control\control_dos_drones_cruz_camara_multiprocessing.py --target drone2
"""

from __future__ import annotations

import argparse
import csv
import multiprocessing as mp
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2


MODULE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = MODULE_DIR.parent
GESTURE_DIR = PROJECT_DIR / "Gesture_control"
for directory in (MODULE_DIR, GESTURE_DIR):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from config import CAMERA_INDEX, MAX_NUM_HANDS, MIN_DETECTION_CONFIDENCE, MIN_TRACKING_CONFIDENCE
from control_dos_drones_cruz_multiprocessing import ProcessBackend, backend_process
from cruz_highlevel_backend import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_TOPIC_1,
    DEFAULT_TOPIC_2,
    DEFAULT_URI_1,
    DEFAULT_URI_2,
)
from cruz_highlevel_protocol import Command
from hand_gesture_detector import HandGestureDetector
from hand_tracker import HandTracker
from utils import calculate_fps


STEP_XY_M = 0.10
STEP_Z_M = 0.08
GESTURE_COOLDOWN_S = 1.25
STOP_COOLDOWN_S = 0.40
WINDOW_NAME = "Control Cruz por cámara"
CSV_FIELDS = (
    "fecha_hora",
    "tiempo_s",
    "fps",
    "destino",
    "mano",
    "comando_crudo",
    "comando_filtrado",
    "comando_ejecutado",
    "detalle",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Control Cruz multiproceso por gestos de cámara")
    parser.add_argument(
        "--target",
        choices=("hands", "drone1", "drone2", "both"),
        default="hands",
        help="hands: izquierda=dron 1 y derecha=dron 2",
    )
    parser.add_argument("--camera", type=int, default=CAMERA_INDEX)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--uri1", default=DEFAULT_URI_1)
    parser.add_argument("--uri2", default=DEFAULT_URI_2)
    parser.add_argument("--topic1", default=DEFAULT_TOPIC_1)
    parser.add_argument("--topic2", default=DEFAULT_TOPIC_2)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    args.single = args.target if args.target in ("drone1", "drone2") else None
    return args


def airborne_states(backend: ProcessBackend, target: str) -> tuple[bool, ...]:
    snapshot = backend.snapshot()
    keys = ("drone1", "drone2") if target == "both" else (target,)
    return tuple(bool(snapshot[key].get("airborne")) for key in keys)


def execute_command(backend: ProcessBackend, detector: HandGestureDetector, gesture: str, target: str) -> str | None:
    if gesture == detector.DESPEGAR:
        states = airborne_states(backend, target)
        if not any(states):
            backend.takeoff(Command("takeoff", target))
            return f"TAKEOFF {target}"
        return None
    if gesture == detector.ATERRIZAR:
        if any(airborne_states(backend, target)):
            backend.land(Command("land", target))
            return f"LAND {target}"
        return None
    if gesture == detector.STOP:
        if any(airborne_states(backend, target)):
            backend.emergency("STOP detectado por cámara")
            return "EMERGENCIA BOTH"
        return None
    if not all(airborne_states(backend, target)):
        return None

    movements = {
        detector.DERECHA: (0.0, -STEP_XY_M, 0.0),
        detector.IZQUIERDA: (0.0, STEP_XY_M, 0.0),
        detector.ARRIBA: (0.0, 0.0, STEP_Z_M),
        detector.ABAJO: (0.0, 0.0, -STEP_Z_M),
        detector.ADELANTE: (STEP_XY_M, 0.0, 0.0),
        detector.ATRAS: (-STEP_XY_M, 0.0, 0.0),
    }
    movement = movements.get(gesture)
    if movement is None:
        return None
    backend.move(Command("move", target, *movement))
    return f"GOTO {target} dx={movement[0]:+.2f} dy={movement[1]:+.2f} dz={movement[2]:+.2f}"


def draw_panel(frame, *, hand_status: list[str], detail: str, fps: float) -> None:
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (frame.shape[1], 176), (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.68, frame, 0.32, 0, frame)
    lines = (
        "CONTROL CRUZ POR CAMARA — HIGH-LEVEL MULTIPROCESO",
        f"FPS: {fps:.1f} | Izquierda = Dron 1 | Derecha = Dron 2",
        hand_status[0] if hand_status else "Sin manos detectadas",
        hand_status[1] if len(hand_status) > 1 else "",
        f"Ultima orden: {detail or 'ninguna'}",
        "q = aterrizar y salir | puno = EMERGENCIA",
    )
    for index, line in enumerate(lines):
        color = (80, 220, 255) if index == len(lines) - 1 else (240, 240, 240)
        cv2.putText(frame, line, (12, 25 + index * 29), cv2.FONT_HERSHEY_SIMPLEX, 0.50, color, 2)


def resize_to_fill(frame, width: int, height: int):
    """Escala y recorta la imagen para llenar la ventana sin deformarla."""
    if width <= 1 or height <= 1:
        return frame
    source_height, source_width = frame.shape[:2]
    scale = max(width / source_width, height / source_height)
    resized_width = max(width, round(source_width * scale))
    resized_height = max(height, round(source_height * scale))
    resized = cv2.resize(frame, (resized_width, resized_height), interpolation=cv2.INTER_LINEAR)
    left = (resized_width - width) // 2
    top = (resized_height - height) // 2
    return resized[top : top + height, left : left + width]


def camera_loop(backend: ProcessBackend, args: argparse.Namespace) -> None:
    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        raise RuntimeError(f"no se pudo abrir la cámara {args.camera}")
    tracker = HandTracker(
        max_num_hands=max(2, MAX_NUM_HANDS),
        min_detection_confidence=MIN_DETECTION_CONFIDENCE,
        min_tracking_confidence=MIN_TRACKING_CONFIDENCE,
    )
    detectors = {
        "Left": HandGestureDetector(tracker.landmark_enum),
        "Right": HandGestureDetector(tracker.landmark_enum),
        "single": HandGestureDetector(tracker.landmark_enum),
    }
    output_dir = PROJECT_DIR / "datos_dos_drones"
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = output_dir / f"gestos_cruz_multiprocessing_{stamp}.csv"
    session_start = time.monotonic()
    previous_frame_time = 0.0
    last_action_time = {"drone1": 0.0, "drone2": 0.0, "both": 0.0}
    last_detail = ""
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW_NAME, 960, 720)

    try:
        with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
            writer.writeheader()
            while True:
                success, frame = cap.read()
                if not success:
                    raise RuntimeError("la cámara dejó de entregar imágenes")
                frame = cv2.flip(frame, 1)
                annotated, detected_hands = tracker.process_hands(frame)
                fps, previous_frame_time = calculate_fps(previous_frame_time)
                now = time.monotonic()
                assignments = []
                if args.target == "hands":
                    for landmarks, handedness in detected_hands:
                        if handedness in ("Left", "Right"):
                            assignments.append((landmarks, handedness, "drone1" if handedness == "Left" else "drone2"))
                elif detected_hands:
                    landmarks, handedness = detected_hands[0]
                    assignments.append((landmarks, handedness or "single", args.target))

                hand_status: list[str] = []
                seen_detector_keys: set[str] = set()
                for landmarks, handedness, target in assignments:
                    detector_key = handedness if handedness in ("Left", "Right") else "single"
                    seen_detector_keys.add(detector_key)
                    detector = detectors[detector_key]
                    raw, filtered, _debug = detector.detect(landmarks, handedness)
                    cooldown = STOP_COOLDOWN_S if filtered == detector.STOP else GESTURE_COOLDOWN_S
                    executed = False
                    if now - last_action_time[target] >= cooldown:
                        try:
                            detail = execute_command(backend, detector, filtered, target)
                            if detail:
                                last_detail = detail
                                last_action_time[target] = now
                                executed = True
                                print(f"[GESTO {handedness}] {detail}")
                        except Exception as exc:
                            last_detail = f"ERROR: {exc}"
                            print(last_detail)
                    hand_status.append(f"Mano {handedness}: {filtered} -> {target}")
                    writer.writerow(
                        {
                            "fecha_hora": datetime.now().isoformat(timespec="milliseconds"),
                            "tiempo_s": now - session_start,
                            "fps": fps,
                            "destino": target,
                            "mano": handedness,
                            "comando_crudo": raw,
                            "comando_filtrado": filtered,
                            "comando_ejecutado": executed,
                            "detalle": last_detail if executed else "",
                        }
                    )
                # Si una mano desaparece se cancela su confirmación pendiente
                # de DESPEGAR/ATERRIZAR; el tiempo fuera de cámara no cuenta.
                relevant_keys = ("Left", "Right") if args.target == "hands" else ("single",)
                for detector_key in relevant_keys:
                    if detector_key not in seen_detector_keys:
                        detectors[detector_key].detect(None, detector_key)
                csv_file.flush()
                try:
                    _x, _y, window_width, window_height = cv2.getWindowImageRect(WINDOW_NAME)
                except cv2.error:
                    window_height, window_width = annotated.shape[:2]
                displayed = resize_to_fill(annotated, window_width, window_height)
                draw_panel(displayed, hand_status=hand_status, detail=last_detail, fps=fps)
                cv2.imshow(WINDOW_NAME, displayed)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    finally:
        cap.release()
        cv2.destroyAllWindows()
        tracker.close()
        print(f"Registro de gestos guardado: {csv_path.resolve()}")


def main() -> int:
    args = parse_args()
    context = mp.get_context("spawn")
    process = context.Process(target=backend_process, args=(args,), name="CruzCameraHardwareBackend")
    process.start()
    backend: ProcessBackend | None = None
    try:
        backend = ProcessBackend(process, args.host, args.port)
        backend.connect(lambda ok, event, message, _snapshot: print(f"[{event}] {message}"))
        print(f"Preflight terminado. La cámara controlará: {args.target}")
        camera_loop(backend, args)
        landing_target = "both" if args.target == "hands" else args.target
        if any(airborne_states(backend, landing_target)):
            print("Aterrizando antes de cerrar...")
            backend.land(Command("land", landing_target))
        return 0
    finally:
        if backend is not None:
            backend.close()
        elif process.is_alive():
            process.terminate()
            process.join(timeout=3.0)


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())
