"""Servidor local para el panel web de control del Crazyflie."""

from __future__ import annotations

import json
import math
import mimetypes
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import cv2


ROOT = Path(__file__).resolve().parents[1]
for folder in (ROOT / "drone_control", ROOT / "Integration", ROOT / "Gesture_control"):
    sys.path.insert(0, str(folder))

import cflib.crtp
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie

import control as base_control
import control_gestos_basico as gestures
from config import (
    CAMERA_INDEX,
    MAX_NUM_HANDS,
    MIN_DETECTION_CONFIDENCE,
    MIN_TRACKING_CONFIDENCE,
)
from hand_gesture_detector import HandGestureDetector
from hand_tracker import HandTracker
from utils import calculate_fps
from control_lowlevel_companero import (
    CONTROL_PERIOD_S,
    HOVER_HEIGHT_M,
    KP_XY,
    KP_Z,
    MAX_HORIZONTAL_ERROR_M,
    MAX_XY_SPEED_M_S,
    MAX_Z_SPEED_M_S,
    MOCAP_TIMEOUT_S,
    TAKEOFF_SPEED_M_S,
    TAKEOFF_TOLERANCE_M,
    DiagnosticCsvLogger,
    configure_lowlevel_global,
)


STATIC_DIR = Path(__file__).resolve().parent / "static"


class ImmediateRoot:
    """Adaptador mínimo para reutilizar el loop de gestos sin Tkinter."""

    def after(self, _delay, callback):
        callback()


class WebFlightController:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.root = ImmediateRoot()
        self.cf = None
        self.connection_thread = None
        self.control_thread = None
        self.camera_thread = None
        self.camera_frame = None
        self.camera_condition = threading.Condition()
        self.shutdown_event = threading.Event()
        self.control_stop_event = threading.Event()
        self.emergency_event = threading.Event()
        self.camera_stop_event = threading.Event()
        self.connected = False
        self.connecting = False
        self.has_taken_off = False
        self.is_landing = False
        self.flight_mode = "desconectado"
        self.error_message = ""
        self.x0 = self.y0 = self.z0 = None
        self.target_x = self.target_y = self.target_z = None
        self.target_yaw = 0.0
        self.battery_logger = None
        self.diagnostic_logger = None

    def _mocap_fresh(self) -> bool:
        return (
            base_control.last_mocap_update > 0.0
            and time.monotonic() - base_control.last_mocap_update <= MOCAP_TIMEOUT_S
        )

    def connect(self) -> None:
        with self.lock:
            if self.connecting:
                return
            # Tras un paro no se reconecta la radio: solo se rearma el panel.
            # No se envía ningún comando a los motores en este punto.
            if self.connected:
                if self.flight_mode == "emergencia":
                    self.error_message = "Esperando que termine la desconexión de emergencia"
                return
            self.connecting = True
            self.error_message = ""
            self.shutdown_event.clear()
            self.control_stop_event.clear()
            base_control.stop_mqtt_event.clear()
            self.connection_thread = threading.Thread(
                target=self._connection_worker, daemon=True
            )
            self.connection_thread.start()

    def _connection_worker(self) -> None:
        mqtt_thread = threading.Thread(target=base_control.start_mqtt, daemon=True)
        mqtt_thread.start()
        try:
            cflib.crtp.init_drivers(enable_debug_driver=False)
            with SyncCrazyflie(
                base_control.URI, cf=Crazyflie(rw_cache="./cache")
            ) as scf:
                self.cf = scf.cf
                base_control.cf_global = self.cf
                configure_lowlevel_global(self.cf)
                self.battery_logger = base_control.BatteryLogger(self.cf)
                self.battery_logger.start()
                self.diagnostic_logger = DiagnosticCsvLogger(self.cf)
                self.diagnostic_logger.panel = self
                self.diagnostic_logger.start()
                with self.lock:
                    self.connected = True
                    self.connecting = False
                    self.flight_mode = "listo"
                with self.lock:
                    self._ensure_control_loop_locked()
                self.shutdown_event.wait()
        except Exception as exc:
            with self.lock:
                self.error_message = str(exc)
                self.connecting = False
                self.connected = False
                self.flight_mode = "error"
        finally:
            self._cleanup()
            base_control.stop_mqtt_event.set()
            mqtt_thread.join(timeout=1.0)

    def _cleanup(self) -> None:
        self.camera_stop_event.set()
        with self.camera_condition:
            self.camera_condition.notify_all()
        self.control_stop_event.set()
        if self.diagnostic_logger is not None:
            self.diagnostic_logger.stop()
            self.diagnostic_logger = None
        if self.battery_logger is not None:
            self.battery_logger.stop()
            self.battery_logger = None
        base_control.cf_global = None
        self.cf = None
        with self.lock:
            self.connected = False
            self.connecting = False
            self.has_taken_off = False
            self.is_landing = False
            if self.flight_mode != "error":
                self.flight_mode = "desconectado"

    def disconnect(self) -> None:
        if self.has_taken_off:
            self.emergency_motor_cut("Desconexión solicitada")
        self.shutdown_event.set()

    def _ensure_control_loop_locked(self) -> None:
        """Recrea el loop si un aborto de seguridad lo había detenido."""
        if self.cf is None:
            return
        if self.control_thread is None or not self.control_thread.is_alive():
            self.control_thread = threading.Thread(
                target=self._control_loop, daemon=True
            )
            self.control_thread.start()

    def _control_loop(self) -> None:
        while not self.control_stop_event.is_set():
            with self.lock:
                active = self.has_taken_off and not self.is_landing
                target = (self.target_x, self.target_y, self.target_z)
                mode = self.flight_mode
                cf = self.cf
            if active and cf is not None:
                if not self._mocap_fresh():
                    self.emergency_motor_cut("MoCap perdido")
                    return
                x = base_control.mocap_pose["x"]
                y = base_control.mocap_pose["y"]
                z = base_control.mocap_pose["z"]
                if None not in (x, y, z, *target):
                    ex, ey, ez = target[0] - x, target[1] - y, target[2] - z
                    if math.hypot(ex, ey) > MAX_HORIZONTAL_ERROR_M:
                        self.emergency_motor_cut("Desviación horizontal excesiva")
                        return
                    vx, vy = KP_XY * ex, KP_XY * ey
                    speed = math.hypot(vx, vy)
                    if speed > MAX_XY_SPEED_M_S:
                        scale = MAX_XY_SPEED_M_S / speed
                        vx, vy = vx * scale, vy * scale
                    vz = TAKEOFF_SPEED_M_S if mode == "despegando" else max(
                        -MAX_Z_SPEED_M_S, min(MAX_Z_SPEED_M_S, KP_Z * ez)
                    )
                    cf.commander.send_velocity_world_setpoint(vx, vy, vz, 0.0)
            time.sleep(CONTROL_PERIOD_S)

    def start_hover(self) -> None:
        with self.lock:
            if not self.connected or self.has_taken_off or self.is_landing:
                return
            if not self._mocap_fresh():
                self.error_message = "No hay una posición MoCap reciente"
                return
            self.x0 = base_control.mocap_pose["x"]
            self.y0 = base_control.mocap_pose["y"]
            self.z0 = base_control.mocap_pose["z"]
            self.target_x, self.target_y = self.x0, self.y0
            self.target_z = self.z0 + HOVER_HEIGHT_M
            self.emergency_event.clear()
            self.has_taken_off = True
            self.flight_mode = "despegando"
            self._ensure_control_loop_locked()
        threading.Thread(target=self._await_takeoff, daemon=True).start()

    def _await_takeoff(self) -> None:
        deadline = time.monotonic() + HOVER_HEIGHT_M / TAKEOFF_SPEED_M_S + 5.0
        while time.monotonic() < deadline and not self.is_landing:
            if not self._mocap_fresh():
                self.emergency_motor_cut("MoCap perdido durante el despegue")
                return
            if base_control.mocap_pose["z"] >= self.target_z - TAKEOFF_TOLERANCE_M:
                with self.lock:
                    self.flight_mode = "hover"
                return
            time.sleep(CONTROL_PERIOD_S)
        if not self.is_landing:
            self.emergency_motor_cut("Timeout de despegue")

    def move_drone(self, dx, dy, dz) -> None:
        with self.lock:
            if not self.has_taken_off or self.is_landing:
                return
            self.target_x += dx
            self.target_y += dy
            self.target_z += dz
            self.target_x = max(self.x0 - base_control.MAX_X_OFFSET_CMD,
                                min(self.x0 + base_control.MAX_X_OFFSET_CMD, self.target_x))
            self.target_y = max(self.y0 - base_control.MAX_Y_OFFSET_CMD,
                                min(self.y0 + base_control.MAX_Y_OFFSET_CMD, self.target_y))
            self.target_z = max(self.z0 + base_control.MIN_HEIGHT_CMD,
                                min(self.z0 + base_control.MAX_HEIGHT_CMD, self.target_z))

    def land_drone(self) -> None:
        if not self.has_taken_off or self.is_landing:
            return
        threading.Thread(target=self._land_worker, daemon=True).start()

    def _land_worker(self) -> None:
        with self.lock:
            self.emergency_event.clear()
            self.is_landing = True
            self.flight_mode = "aterrizando"
        deadline = time.monotonic() + 10.0
        while (
            time.monotonic() < deadline
            and self._mocap_fresh()
            and not self.emergency_event.is_set()
        ):
            if base_control.mocap_pose["z"] <= self.z0 + 0.04:
                break
            self.cf.commander.send_velocity_world_setpoint(0.0, 0.0, -0.10, 0.0)
            time.sleep(CONTROL_PERIOD_S)
        if self.emergency_event.is_set():
            return
        self._stop_motors()
        with self.lock:
            self.has_taken_off = False
            self.is_landing = False
            self.flight_mode = "listo"

    def _stop_motors(self) -> None:
        if self.cf is None:
            return
        self.cf.commander.send_velocity_world_setpoint(0.0, 0.0, 0.0, 0.0)
        for _ in range(15):
            self.cf.commander.send_stop_setpoint()
            time.sleep(0.03)

    def emergency_motor_cut(self, reason="Paro de emergencia") -> None:
        with self.lock:
            if self.flight_mode == "emergencia":
                return
            self.emergency_event.set()
            self.is_landing = True
            self.flight_mode = "emergencia"
            self.error_message = reason
        self._stop_motors()
        with self.lock:
            self.has_taken_off = False
            self.is_landing = False
        self.shutdown_event.set()

    def start_camera(self) -> None:
        if self.camera_thread is not None and self.camera_thread.is_alive():
            return
        self.camera_stop_event.clear()
        gestures.dc = base_control
        gestures.GESTURE_COOLDOWN_S = 0.70
        self.camera_thread = threading.Thread(
            target=self._web_gesture_loop,
            daemon=True,
        )
        self.camera_thread.start()

    def stop_camera(self) -> None:
        self.camera_stop_event.set()
        with self.camera_condition:
            self.camera_condition.notify_all()

    def _web_gesture_loop(self) -> None:
        """Reconoce gestos y publica el video anotado en la página."""
        cap = cv2.VideoCapture(CAMERA_INDEX)
        if not cap.isOpened():
            with self.lock:
                self.error_message = "No se pudo abrir la cámara"
            self.camera_stop_event.set()
            return

        tracker = HandTracker(
            max_num_hands=MAX_NUM_HANDS,
            min_detection_confidence=MIN_DETECTION_CONFIDENCE,
            min_tracking_confidence=MIN_TRACKING_CONFIDENCE,
        )
        detector = HandGestureDetector(tracker.landmark_enum)
        last_action_time = 0.0
        previous_time = 0.0

        try:
            while not self.camera_stop_event.is_set() and not self.is_landing:
                success, frame = cap.read()
                if not success:
                    with self.lock:
                        self.error_message = "No se recibió imagen de la cámara"
                    break

                frame = cv2.flip(frame, 1)
                annotated, landmarks, handedness = tracker.process(frame)
                raw, command, debug = detector.detect(landmarks, handedness)
                fps, previous_time = calculate_fps(previous_time)
                now = time.time()
                cooldown = (
                    gestures.STOP_COOLDOWN_S
                    if command == detector.STOP
                    else gestures.GESTURE_COOLDOWN_S
                )
                if now - last_action_time >= cooldown:
                    if gestures.execute_gesture_command(self, detector, command):
                        last_action_time = now

                gestures.put_gesture_panel(
                    annotated,
                    command,
                    raw,
                    handedness if handedness is not None else "None",
                    fps,
                    debug,
                )
                encoded, jpeg = cv2.imencode(
                    ".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 82]
                )
                if encoded:
                    with self.camera_condition:
                        self.camera_frame = jpeg.tobytes()
                        self.camera_condition.notify_all()
        except Exception as exc:
            with self.lock:
                self.error_message = f"Error en cámara: {exc}"
        finally:
            self.camera_stop_event.set()
            cap.release()
            tracker.close()
            with self.camera_condition:
                self.camera_condition.notify_all()

    def camera_stream(self):
        """Genera un stream MJPEG para la etiqueta de imagen de la web."""
        while not self.camera_stop_event.is_set():
            with self.camera_condition:
                if self.camera_frame is None:
                    self.camera_condition.wait(timeout=1.0)
                frame = self.camera_frame
            if frame is not None:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    + f"Content-Length: {len(frame)}\r\n\r\n".encode("ascii")
                    + frame
                    + b"\r\n"
                )

    def status(self) -> dict:
        with self.lock:
            mocap = dict(base_control.mocap_pose)
            target = {"x": self.target_x, "y": self.target_y, "z": self.target_z}
            return {
                "connected": self.connected,
                "connecting": self.connecting,
                "flying": self.has_taken_off,
                "landing": self.is_landing,
                "camera": bool(self.camera_thread and self.camera_thread.is_alive()),
                "mode": self.flight_mode,
                "mocap": mocap,
                "target": target,
                "battery": dict(base_control.battery_data),
                "error": self.error_message,
            }


FLIGHT = WebFlightController()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, _format, *_args):
        return

    def _json(self, payload, status=HTTPStatus.OK):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        size = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(size) or b"{}")

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/status":
            return self._json(FLIGHT.status())
        if path == "/api/camera/stream":
            if not (FLIGHT.camera_thread and FLIGHT.camera_thread.is_alive()):
                self.send_error(HTTPStatus.SERVICE_UNAVAILABLE, "Cámara inactiva")
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.end_headers()
            try:
                for frame in FLIGHT.camera_stream():
                    self.wfile.write(frame)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        if path == "/":
            path = "/index.html"
        target = (STATIC_DIR / path.lstrip("/")).resolve()
        if STATIC_DIR not in target.parents or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(str(target))[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            payload = self._body()
            if path == "/api/connect":
                FLIGHT.connect()
            elif path == "/api/takeoff":
                FLIGHT.start_hover()
            elif path == "/api/land":
                FLIGHT.land_drone()
            elif path == "/api/emergency":
                FLIGHT.emergency_motor_cut("Paro de emergencia desde la web")
            elif path == "/api/camera/start":
                FLIGHT.start_camera()
            elif path == "/api/camera/stop":
                FLIGHT.stop_camera()
            elif path == "/api/move":
                direction = payload.get("direction")
                commands = {
                    "forward": (0.08, 0.0, 0.0), "back": (-0.08, 0.0, 0.0),
                    "right": (0.0, 0.08, 0.0), "left": (0.0, -0.08, 0.0),
                    "up": (0.0, 0.0, 0.05), "down": (0.0, 0.0, -0.05),
                }
                if direction not in commands:
                    return self._json({"error": "Dirección inválida"}, HTTPStatus.BAD_REQUEST)
                FLIGHT.move_drone(*commands[direction])
            else:
                return self._json({"error": "Ruta no encontrada"}, HTTPStatus.NOT_FOUND)
            return self._json(FLIGHT.status())
        except Exception as exc:
            return self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)


if __name__ == "__main__":
    print("UVG Drone Lab disponible en http://127.0.0.1:8765")
    ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
