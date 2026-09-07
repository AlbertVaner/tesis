"""El controlador corporal sobre el backend high-level, con el backend simulado.

Sin radio, sin mocap y sin camara. Se comprueba la traduccion de intencion de
velocidad a pasos `go_to`, que el backend siga mandando (geocerca), el
watchdog de vision y el seguimiento del marker por `follow_move`.

Uso, desde la raiz del repositorio:

    .\\.venv\\Scripts\\python.exe .\\controllers\\single_drone\\camera\\tests\\test_highlevel_flight.py
"""

from __future__ import annotations

import math
import sys
import time
from pathlib import Path

CAMERA_DIR = Path(__file__).resolve().parents[1]
if str(CAMERA_DIR) not in sys.path:
    sys.path.insert(0, str(CAMERA_DIR))

import highlevel_flight as hf  # noqa: E402
from cruz_highlevel_backend import (  # noqa: E402
    MAX_HORIZONTAL_FROM_ORIGIN_M,
    TAKEOFF_RELATIVE_M,
)

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))


def nuevo(**kw) -> tuple[hf.HighLevelFlight, list[str]]:
    logs: list[str] = []
    flight = hf.HighLevelFlight(dry_run=True, log=logs.append, **kw)
    flight.connect()
    return flight, logs


def pose(flight) -> list[float]:
    return list(flight.backend.snapshot()["drone1"]["pose"])


class FakeFollower:
    """Doble de CameraMarkerFollower: un marker fijo 2 cm delante del dron."""

    def __init__(self) -> None:
        self.active_keys: tuple[str, ...] = ()
        self.activations: list = []

    def activate(self, keys, positions=None) -> None:
        self.activations.append((tuple(keys), positions))
        self.active_keys = tuple(keys)

    def deactivate(self, keys=None) -> None:
        self.active_keys = ()

    def highlevel_delta(self, key, current_target):
        return (0.02, 0.0, 0.0)

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


def main() -> int:
    hf.TAKEOFF_DURATION_S = 0.0
    hf.LAND_DURATION_S = 0.0
    hf.STEP_PERIOD_S = 0.0

    # -- despegue y altura ---------------------------------------------------
    flight, logs = nuevo()
    check("en tierra tras el preflight", not flight.flying and flight.height_m == 0.0)
    check("despega", flight.request_takeoff() and flight.flying)
    check("altura sobre el origen", abs(flight.height_m - TAKEOFF_RELATIVE_M) < 1e-6, f"{flight.height_m}")
    check("no despega dos veces", flight.request_takeoff() is False)

    # -- pasos por intencion de velocidad -----------------------------------
    antes = pose(flight)
    flight.set_velocity(0.18, 0.0, 0.0)
    despues = pose(flight)
    check("ADELANTE = un paso de 0.10 m en +x",
          abs(despues[0] - antes[0] - hf.STEP_XY_M) < 1e-9 and despues[1] == antes[1], f"{antes}->{despues}")
    antes = pose(flight)
    flight.set_velocity(0.10, -0.10, 0.0)
    despues = pose(flight)
    check("diagonal = paso maximo en cada eje",
          abs(despues[0] - antes[0] - hf.STEP_XY_M) < 1e-9 and abs(despues[1] - antes[1] + hf.STEP_XY_M) < 1e-9)
    antes = pose(flight)
    flight.set_velocity(0.0, 0.0, -0.10)
    despues = pose(flight)
    check("ABAJO = paso de 0.08 m en -z", abs(despues[2] - antes[2] + hf.STEP_Z_M) < 1e-9)
    antes = pose(flight)
    flight.set_velocity(0.0, 0.0, 0.0)
    flight.hover()
    check("velocidad cero y hover no mueven", pose(flight) == antes)

    # -- ritmo de pasos ------------------------------------------------------
    hf.STEP_PERIOD_S = 10.0
    flight._last_step = 0.0
    antes = pose(flight)
    flight.set_velocity(0.18, 0.0, 0.0)
    flight.set_velocity(0.18, 0.0, 0.0)
    check("dentro del periodo solo sale un paso", abs(pose(flight)[0] - antes[0] - hf.STEP_XY_M) < 1e-9)
    hf.STEP_PERIOD_S = 0.0

    # -- geocerca del backend ------------------------------------------------
    rechazos_antes = sum("rechazada" in line for line in logs)
    for _ in range(12):
        flight.set_velocity(0.18, 0.0, 0.0)
    origen = flight.backend.snapshot()["drone1"]["origin"]
    p = pose(flight)
    radio = math.hypot(p[0] - origen[0], p[1] - origen[1])
    check("la geocerca del backend frena el avance",
          radio <= MAX_HORIZONTAL_FROM_ORIGIN_M + 1e-9 and sum("rechazada" in line for line in logs) > rechazos_antes,
          f"radio={radio:.2f}")

    # -- seguimiento del marker ---------------------------------------------
    follower = FakeFollower()
    antes = pose(flight)
    flight.follow_marker(follower)
    check("seguir marker activa y da un paso follow_move",
          follower.activations and abs(pose(flight)[0] - antes[0] - 0.02) < 1e-9, f"{antes}->{pose(flight)}")

    # -- aterrizaje y emergencia --------------------------------------------
    check("aterriza", flight.request_land("prueba") and not flight.flying)
    check("no aterriza dos veces", flight.request_land() is False)
    flight.request_takeoff()
    flight.emergency_stop()
    check("emergencia deja de volar y bloquea el despegue",
          not flight.flying and flight.request_takeoff() is False and flight.backend.emergency_latched)
    flight.close()

    # -- busy durante la maniobra -------------------------------------------
    hf.TAKEOFF_DURATION_S = 5.0
    flight, _ = nuevo()
    flight.request_takeoff()
    antes = pose(flight)
    flight.set_velocity(0.18, 0.0, 0.0)
    check("busy durante el despegue ignora movimientos", flight.busy and pose(flight) == antes)
    flight.close()
    hf.TAKEOFF_DURATION_S = 0.0

    # -- watchdog de vision --------------------------------------------------
    hf.VISION_LOST_LAND_S = 0.30
    flight, logs = nuevo()
    flight.request_takeoff()
    plazo = time.monotonic() + 2.0
    while time.monotonic() < plazo and flight.flying:
        time.sleep(0.05)
    check("sin ordenes de la camara aterriza solo", not flight.flying and any("aterrizando" in line for line in logs))
    flight.close()

    fallos = 0
    for nombre, ok, detalle in results:
        print(f"[{'OK  ' if ok else 'FALLA'}] {nombre}" + (f"  ({detalle})" if detalle and not ok else ""))
        fallos += not ok
    print(f"\n{len(results) - fallos}/{len(results)} comprobaciones correctas")
    print("Esto valida la traduccion sobre el backend simulado, no el vuelo.")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
