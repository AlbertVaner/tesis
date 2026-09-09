"""El controlador corporal sobre el backend high-level, con el backend simulado.

Sin radio, sin mocap y sin camara. Se comprueba la traduccion de intencion de
velocidad a pasos `go_to`, que el backend siga mandando (geocerca), el
watchdog de vision y el seguimiento del marker por `follow_move`.

Uso, desde la raiz del repositorio:

    .\\.venv\\Scripts\\python.exe -m pytest -q .\\controllers\\single_drone\\camera\\tests\\test_highlevel_flight.py
"""

from __future__ import annotations

import math
import sys
import time
from pathlib import Path

import pytest

CAMERA_DIR = Path(__file__).resolve().parents[1]
if str(CAMERA_DIR) not in sys.path:
    sys.path.insert(0, str(CAMERA_DIR))

import highlevel_flight as hf  # noqa: E402
from cruz_highlevel_backend import (  # noqa: E402
    MAX_HORIZONTAL_FROM_ORIGIN_M,
    TAKEOFF_RELATIVE_M,
)


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


@pytest.fixture(autouse=True)
def sin_esperas(monkeypatch: pytest.MonkeyPatch) -> None:
    """Maniobras instantaneas y sin periodo entre pasos, como en el runner original."""
    monkeypatch.setattr(hf, "TAKEOFF_DURATION_S", 0.0)
    monkeypatch.setattr(hf, "LAND_DURATION_S", 0.0)
    monkeypatch.setattr(hf, "STEP_PERIOD_S", 0.0)


@pytest.fixture
def vuelo():
    """Un HighLevelFlight simulado ya conectado (en tierra) y su bitacora."""
    logs: list[str] = []
    flight = hf.HighLevelFlight(dry_run=True, log=logs.append)
    flight.connect()
    try:
        yield flight, logs
    finally:
        flight.close()


# -- despegue y altura ---------------------------------------------------


def test_despegue_y_altura(vuelo) -> None:
    flight, _ = vuelo
    assert not flight.flying and flight.height_m == 0.0, "en tierra tras el preflight"
    assert flight.request_takeoff() and flight.flying, "despega"
    assert abs(flight.height_m - TAKEOFF_RELATIVE_M) < 1e-6, \
        f"altura sobre el origen: {flight.height_m}"
    assert flight.request_takeoff() is False, "no despega dos veces"


# -- pasos por intencion de velocidad -----------------------------------


def test_pasos_por_intencion_de_velocidad(vuelo) -> None:
    flight, _ = vuelo
    flight.request_takeoff()

    antes = pose(flight)
    flight.set_velocity(0.18, 0.0, 0.0)
    despues = pose(flight)
    assert abs(despues[0] - antes[0] - hf.STEP_XY_M) < 1e-9 and despues[1] == antes[1], \
        f"ADELANTE = un paso de 0.10 m en +x: {antes}->{despues}"

    antes = pose(flight)
    flight.set_velocity(0.10, -0.10, 0.0)
    despues = pose(flight)
    assert abs(despues[0] - antes[0] - hf.STEP_XY_M) < 1e-9 \
        and abs(despues[1] - antes[1] + hf.STEP_XY_M) < 1e-9, \
        "diagonal = paso maximo en cada eje"

    antes = pose(flight)
    flight.set_velocity(0.0, 0.0, -0.10)
    despues = pose(flight)
    assert abs(despues[2] - antes[2] + hf.STEP_Z_M) < 1e-9, "ABAJO = paso de 0.08 m en -z"

    antes = pose(flight)
    flight.set_velocity(0.0, 0.0, 0.0)
    flight.hover()
    assert pose(flight) == antes, "velocidad cero y hover no mueven"


# -- ritmo de pasos ------------------------------------------------------


def test_dentro_del_periodo_solo_sale_un_paso(vuelo, monkeypatch: pytest.MonkeyPatch) -> None:
    flight, _ = vuelo
    flight.request_takeoff()

    monkeypatch.setattr(hf, "STEP_PERIOD_S", 10.0)
    flight._last_step = 0.0
    antes = pose(flight)
    flight.set_velocity(0.18, 0.0, 0.0)
    flight.set_velocity(0.18, 0.0, 0.0)
    assert abs(pose(flight)[0] - antes[0] - hf.STEP_XY_M) < 1e-9, \
        "dentro del periodo solo sale un paso"


# -- geocerca del backend ------------------------------------------------


def test_la_geocerca_del_backend_frena_el_avance(vuelo) -> None:
    flight, logs = vuelo
    flight.request_takeoff()

    rechazos_antes = sum("rechazada" in line for line in logs)
    for _ in range(12):
        flight.set_velocity(0.18, 0.0, 0.0)
    origen = flight.backend.snapshot()["drone1"]["origin"]
    p = pose(flight)
    radio = math.hypot(p[0] - origen[0], p[1] - origen[1])
    assert radio <= MAX_HORIZONTAL_FROM_ORIGIN_M + 1e-9 \
        and sum("rechazada" in line for line in logs) > rechazos_antes, \
        f"la geocerca del backend frena el avance: radio={radio:.2f}"


# -- seguimiento del marker ---------------------------------------------


def test_seguir_marker_activa_y_da_un_paso_follow_move(vuelo) -> None:
    flight, _ = vuelo
    flight.request_takeoff()

    follower = FakeFollower()
    antes = pose(flight)
    flight.follow_marker(follower)
    assert follower.activations and abs(pose(flight)[0] - antes[0] - 0.02) < 1e-9, \
        f"seguir marker activa y da un paso follow_move: {antes}->{pose(flight)}"


# -- aterrizaje y emergencia --------------------------------------------


def test_aterrizaje_y_emergencia(vuelo) -> None:
    flight, _ = vuelo
    flight.request_takeoff()

    assert flight.request_land("prueba") and not flight.flying, "aterriza"
    assert flight.request_land() is False, "no aterriza dos veces"
    flight.request_takeoff()
    flight.emergency_stop()
    assert not flight.flying and flight.request_takeoff() is False \
        and flight.backend.emergency_latched, \
        "emergencia deja de volar y bloquea el despegue"


# -- busy durante la maniobra -------------------------------------------


def test_busy_durante_el_despegue_ignora_movimientos(vuelo, monkeypatch: pytest.MonkeyPatch) -> None:
    flight, _ = vuelo
    monkeypatch.setattr(hf, "TAKEOFF_DURATION_S", 5.0)
    flight.request_takeoff()
    antes = pose(flight)
    flight.set_velocity(0.18, 0.0, 0.0)
    assert flight.busy and pose(flight) == antes, "busy durante el despegue ignora movimientos"


# -- watchdog de vision --------------------------------------------------


def test_sin_ordenes_de_la_camara_aterriza_solo(vuelo, monkeypatch: pytest.MonkeyPatch) -> None:
    flight, logs = vuelo
    monkeypatch.setattr(hf, "VISION_LOST_LAND_S", 0.30)
    flight.request_takeoff()
    plazo = time.monotonic() + 2.0
    while time.monotonic() < plazo and flight.flying:
        time.sleep(0.05)
    assert not flight.flying and any("aterrizando" in line for line in logs), \
        "sin ordenes de la camara aterriza solo"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
