"""Adaptador headless del marker joystick; no abre radios ni controla drones.

Lee la pose del rigid body del joystick por MQTT y la traduce a una intención
de velocidad con zona muerta y rampa. Quien vuela con esa intención es el
backend high-level de la cruz, a través de `two_drones/experiment_session.py`.
"""

from __future__ import annotations

import math
import sys
import time
from pathlib import Path

SHARED_DIR = Path(__file__).resolve().parents[1] / "shared"
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))
from marker_mocap import MocapReceiver  # noqa: E402
from robotat import ALL_MARKERS_TOPIC  # noqa: E402

# --- Ajustar solamente estas constantes después de la prueba sin hélices. ---
MAX_HORIZONTAL_SPEED_M_S = 0.12
#: Zona muerta amplia: el marker debe inclinarse de forma deliberada.
TILT_DEADZONE_DEG = 12.0
TILT_FULL_SPEED_DEG = 28.0
VERTICAL_DEADZONE_M = 0.08
#: Bajar el marker más de 10 cm bajo el cero durante `LAND_HOLD_S` pide aterrizar.
LAND_MARKER_BELOW_M = -0.10
LAND_HOLD_S = 0.50
#: Signos observados en la prueba sin hélices.
PITCH_TO_X_SIGN = 1.0
ROLL_TO_Y_SIGN = 1.0


def angle_delta_deg(now: float, reference: float) -> float:
    """Diferencia angular en [-180, 180], segura al cruzar ±180°."""
    return (now - reference + 180.0) % 360.0 - 180.0


def tilt_to_speed(angle_deg: float) -> float:
    """Zona muerta amplia y rampa suave desde 12° hasta 28°."""
    magnitude = abs(angle_deg)
    if magnitude <= TILT_DEADZONE_DEG:
        return 0.0
    ramp = (magnitude - TILT_DEADZONE_DEG) / (TILT_FULL_SPEED_DEG - TILT_DEADZONE_DEG)
    return math.copysign(MAX_HORIZONTAL_SPEED_M_S * max(0.0, min(1.0, ramp)), angle_deg)


class MarkerInput:
    def __init__(self, marker_id: int) -> None:
        self.receiver = MocapReceiver(ALL_MARKERS_TOPIC, required_identifier=marker_id)
        self.zero = None
        self.below_since: float | None = None

    def start(self) -> None:
        self.receiver.start()

    def stop(self) -> None:
        self.receiver.stop()

    def calibrate(self) -> None:
        pose = self.receiver.fresh_pose()
        if pose is None:
            raise ValueError("No hay una pose reciente del marker seleccionado")
        self.zero = pose
        self.below_since = None

    def read(self) -> dict:
        pose = self.receiver.fresh_pose()
        if pose is None:
            return {
                "fresh": False,
                "calibrated": self.zero is not None,
                "message": self.receiver.error or "Esperando marker",
            }
        if self.zero is None:
            return {"fresh": True, "calibrated": False, "message": "Coloca el marker a nivel y establece cero"}
        roll = angle_delta_deg(pose.roll_deg, self.zero.roll_deg)
        pitch = angle_delta_deg(pose.pitch_deg, self.zero.pitch_deg)
        dz = pose.z - self.zero.z
        if dz < LAND_MARKER_BELOW_M:
            if self.below_since is None:
                self.below_since = time.monotonic()
        else:
            self.below_since = None
        return {
            "fresh": True,
            "calibrated": True,
            "roll": roll,
            "pitch": pitch,
            "dz": 0 if abs(dz) <= VERTICAL_DEADZONE_M else dz,
            "vx": PITCH_TO_X_SIGN * tilt_to_speed(pitch),
            "vy": ROLL_TO_Y_SIGN * tilt_to_speed(roll),
            "land": self.below_since is not None and time.monotonic() - self.below_since >= LAND_HOLD_S,
            "message": "Marker activo",
        }
