"""Control del Dron 1 por gestos de mano usando Flow deck v2, sin Robotat."""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

import cv2

import cflib.crtp
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie
from cflib.positioning.motion_commander import MotionCommander


MODULE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = MODULE_DIR.parent
GESTURE_DIR = PROJECT_DIR / "Gesture_control"
for directory in (MODULE_DIR, GESTURE_DIR):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from config import (  # noqa: E402
    CAMERA_INDEX,
    MIN_DETECTION_CONFIDENCE,
    MIN_TRACKING_CONFIDENCE,
)
from hand_gesture_detector import HandGestureDetector  # noqa: E402
from hand_tracker import HandTracker  # noqa: E402
from hover_flowdeck_dron1 import (  # noqa: E402
    DEFAULT_HEIGHT_M,
    arm_if_supported,
    emergency_stop_motion_commander,
    require_flow_deck,
    reset_and_wait_for_estimator,
    select_uri,
)
from utils import calculate_fps  # noqa: E402


WINDOW_NAME = "Dron 1 - Camara + Flow deck"
SPEED_XY_M_S = 0.18
SPEED_Z_M_S = 0.10
VISION_DEADMAN_S = 0.40
STOP_HOLD_S = 0.60


class CameraFlight:
    """Mantiene radio y MotionCommander con vigilancia independiente de cámara."""

    def __init__(self, uri: str) -> None:
        self.uri = uri
        self.link: SyncCrazyflie | None = None
        self.cf: Crazyflie | None = None
        self.commander: MotionCommander | None = None
        self.flying = False
        self.emergency = False
        self.lock = threading.RLock()
        self.last_vision_command = time.monotonic()
        self.motion_active = False
        self.watchdog_stop = threading.Event()
        self.watchdog = threading.Thread(target=self._watchdog_loop, daemon=True)

    def connect(self) -> None:
        print(f"Conectando el Dron 1 mediante {self.uri}...")
        self.link = SyncCrazyflie(
            self.uri, cf=Crazyflie(rw_cache="./cache_flowdeck_camera")
        )
        self.link.open_link()
        self.cf = self.link.cf
        require_flow_deck(self.cf)
        reset_and_wait_for_estimator(self.cf)
        self.watchdog.start()
        print("Preflight terminado. La cámara todavía no enciende los motores.")

    def takeoff(self) -> None:
        with self.lock:
            if self.flying or self.cf is None:
                return
            print("Gesto DESPEGAR confirmado. Despegando...")
            arm_if_supported(self.cf)
            self.commander = MotionCommander(self.cf, default_height=DEFAULT_HEIGHT_M)
            self.commander.take_off()
            self.commander.stop()
            self.flying = True
            self.motion_active = False
            self.last_vision_command = time.monotonic()

    def set_velocity(self, vx: float, vy: float, vz: float) -> None:
        with self.lock:
            if not self.flying or self.commander is None:
                return
            self.commander.start_linear_motion(vx, vy, vz)
            self.motion_active = any(abs(value) > 1e-6 for value in (vx, vy, vz))
            self.last_vision_command = time.monotonic()

    def hover(self) -> None:
        with self.lock:
            if self.flying and self.commander is not None:
                self.commander.stop()
            self.motion_active = False
            self.last_vision_command = time.monotonic()

    def land(self) -> None:
        with self.lock:
            if not self.flying or self.commander is None:
                return
            print("Aterrizando...")
            self.commander.stop()
            self.motion_active = False
            self.commander.land()
            self.commander = None
            self.flying = False
            print("Aterrizaje completado.")

    def emergency_stop(self) -> None:
        with self.lock:
            if self.cf is None:
                return
            self.emergency = True
            emergency_stop_motion_commander(self.commander, self.cf)
            self.commander = None
            self.flying = False
            self.motion_active = False

    def _watchdog_loop(self) -> None:
        while not self.watchdog_stop.wait(0.05):
            with self.lock:
                expired = (
                    self.flying
                    and self.motion_active
                    and time.monotonic() - self.last_vision_command > VISION_DEADMAN_S
                )
                if expired and self.commander is not None:
                    self.commander.stop()
                    self.motion_active = False

    def close(self) -> None:
        self.watchdog_stop.set()
        if self.watchdog.is_alive():
            self.watchdog.join(timeout=1.0)
        if not self.emergency:
            try:
                self.land()
            except Exception as error:
                print(f"No se pudo completar el aterrizaje: {error}")
        if self.link is not None:
            try:
                self.link.close_link()
            except Exception:
                pass
            self.link = None
            self.cf = None


def gesture_velocity(detector: HandGestureDetector, gesture: str) -> tuple[float, float, float] | None:
    return {
        detector.ADELANTE: (SPEED_XY_M_S, 0.0, 0.0),
        detector.ATRAS: (-SPEED_XY_M_S, 0.0, 0.0),
        detector.IZQUIERDA: (0.0, SPEED_XY_M_S, 0.0),
        detector.DERECHA: (0.0, -SPEED_XY_M_S, 0.0),
        detector.ARRIBA: (0.0, 0.0, SPEED_Z_M_S),
        detector.ABAJO: (0.0, 0.0, -SPEED_Z_M_S),
    }.get(gesture)


def draw_panel(frame, *, raw: str, gesture: str, state: str, fps: float) -> None:
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (frame.shape[1], 174), (18, 18, 18), -1)
    cv2.addWeighted(overlay, 0.72, frame, 0.28, 0, frame)
    lines = (
        "DRON 1 - CONTROL POR CAMARA + FLOW DECK",
        f"Estado: {state}    FPS: {fps:.1f}",
        f"Gesto: {gesture}    Raw: {raw}",
        "Sin mano o REPOSO = hover automatico",
        "q = aterrizar y salir | puno cerrado = EMERGENCIA",
    )
    for index, line in enumerate(lines):
        color = (80, 220, 255) if index == 4 else (240, 240, 240)
        cv2.putText(
            frame,
            line,
            (12, 28 + index * 32),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            2,
        )


def camera_loop(flight: CameraFlight, camera_index: int) -> None:
    capture = cv2.VideoCapture(camera_index)
    if not capture.isOpened():
        raise RuntimeError(f"No se pudo abrir la cámara {camera_index}.")

    tracker = HandTracker(
        max_num_hands=1,
        min_detection_confidence=MIN_DETECTION_CONFIDENCE,
        min_tracking_confidence=MIN_TRACKING_CONFIDENCE,
    )
    detector = HandGestureDetector(tracker.landmark_enum)
    previous_frame_time = 0.0
    previous_gesture = detector.SIN_DETECCION
    stop_started: float | None = None

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW_NAME, 960, 720)
    print("Muestra una mano a la cámara. Presiona q en el video para aterrizar y salir.")

    try:
        while True:
            success, frame = capture.read()
            if not success:
                raise RuntimeError("La cámara dejó de entregar imágenes.")
            frame = cv2.flip(frame, 1)
            annotated, hands = tracker.process_hands(frame)
            fps, previous_frame_time = calculate_fps(previous_frame_time)

            if hands:
                landmarks, handedness = hands[0]
                raw, gesture, _debug = detector.detect(landmarks, handedness)
            else:
                raw, gesture, _debug = detector.detect(None, None)

            displayed_gesture = gesture
            if gesture == detector.STOP and flight.flying:
                if stop_started is None:
                    stop_started = time.monotonic()
                held_for = time.monotonic() - stop_started
                displayed_gesture = f"CONFIRMANDO_STOP {held_for:.1f}/{STOP_HOLD_S:.1f}s"
                flight.hover()
                if held_for >= STOP_HOLD_S:
                    print("Puño cerrado confirmado: PARADA DE EMERGENCIA.")
                    flight.emergency_stop()
                    break
            else:
                stop_started = None
            if gesture == detector.STOP:
                pass
            elif gesture == detector.DESPEGAR and not flight.flying:
                flight.takeoff()
            elif gesture == detector.ATERRIZAR and flight.flying:
                flight.land()
            else:
                velocity = gesture_velocity(detector, gesture)
                if velocity is not None and flight.flying:
                    flight.set_velocity(*velocity)
                elif flight.flying:
                    flight.hover()

            if gesture != previous_gesture:
                print(f"Gesto: {gesture}")
                previous_gesture = gesture

            state = "VOLANDO" if flight.flying else "EN TIERRA"
            draw_panel(annotated, raw=raw, gesture=displayed_gesture, state=state, fps=fps)
            cv2.imshow(WINDOW_NAME, annotated)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        capture.release()
        tracker.close()
        cv2.destroyAllWindows()


def main() -> int:
    parser = argparse.ArgumentParser(description="Control por cámara del Dron 1 con Flow deck")
    parser.add_argument("--camera", type=int, default=CAMERA_INDEX)
    parser.add_argument("--radio", help="serial de la Crazyradio")
    parser.add_argument("--uri", help="URI completa; tiene prioridad sobre --radio")
    args = parser.parse_args()

    flight: CameraFlight | None = None
    try:
        cflib.crtp.init_drivers(enable_debug_driver=False)
        uri = select_uri(args.uri, args.radio)
        flight = CameraFlight(uri)
        flight.connect()
        camera_loop(flight, args.camera)
        return 0
    except KeyboardInterrupt:
        print("Interrupción solicitada.")
        return 130
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    finally:
        if flight is not None:
            flight.close()


if __name__ == "__main__":
    raise SystemExit(main())
