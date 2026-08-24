"""Protocolo IPC compartido por supervisor, camara y trabajadores de vuelo."""

from __future__ import annotations

import math
import queue
import time
from typing import Any


CONTROL_PERIOD_S = 0.05
STATE_PERIOD_S = 0.10
PEER_TIMEOUT_S = 0.75
TRANSACTION_TIMEOUT_S = 1.25
SYNCHRONIZED_DELAY_S = 0.10

HOVER_OFFSET_M = 0.35
TAKEOFF_SETTLE_XY_M = 0.08
TAKEOFF_SETTLE_Z_M = 0.04
MAX_MANUAL_XY_OFFSET_M = 0.30
MIN_MANUAL_HEIGHT_M = 0.20
MAX_MANUAL_HEIGHT_M = 0.55
GESTURE_SETTLE_XY_M = 0.040
GESTURE_SETTLE_Z_M = 0.030
GESTURE_MAX_AGE_S = 0.35
STOP_HOLD_S = 0.50
MIN_SEPARATION_M = 0.70

# Perfil conservador: los logs mostraron orbitas crecientes con 0.65/0.15/0.45.
# La respuesta continua se obtiene encadenando objetivos al alcanzarlos, no
# aumentando la ganancia hasta volver inestable el hover.
GESTURE_KP_XY = 0.45
GESTURE_MAX_XY_SPEED_M_S = 0.10
GESTURE_SLEW_XY_M_S2 = 0.30

GESTURE_MOVES = {
    "ADELANTE": (0.10, 0.0, 0.0),
    "ATRAS": (-0.10, 0.0, 0.0),
    "DERECHA": (0.0, 0.10, 0.0),
    "IZQUIERDA": (0.0, -0.10, 0.0),
    "ARRIBA": (0.0, 0.0, 0.04),
    "ABAJO": (0.0, 0.0, -0.04),
}
FLIGHT_COMMANDS = set(GESTURE_MOVES) | {"DESPEGAR", "ATERRIZAR"}


def safe_put(target_queue, message: dict[str, Any], *, important: bool = False) -> bool:
    """Encola sin permitir que telemetria secundaria bloquee un lazo critico."""
    try:
        if important:
            target_queue.put(message, timeout=0.25)
        else:
            target_queue.put_nowait(message)
        return True
    except queue.Full:
        return False


def write_shared_pose(shared_pose, pose) -> None:
    """Publica x/y/z y antiguedad para que el otro nucleo compruebe seguridad."""
    if pose is None:
        return
    with shared_pose.get_lock():
        shared_pose[0] = float(pose.x)
        shared_pose[1] = float(pose.y)
        shared_pose[2] = float(pose.z)
        shared_pose[3] = float(pose.received_at)


def read_shared_pose(shared_pose) -> tuple[tuple[float, float, float] | None, float]:
    with shared_pose.get_lock():
        x, y, z, received_at = (float(value) for value in shared_pose[:])
    if not all(math.isfinite(value) for value in (x, y, z)) or received_at <= 0.0:
        return None, math.inf
    return (x, y, z), max(0.0, time.monotonic() - received_at)
