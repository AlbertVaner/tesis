"""Adaptador del Flow deck a la interfaz del backend de la cruz. Sin radios.

Sustituye `FlowDroneController` por un doble que registra las órdenes, así que
no se abre ninguna Crazyradio ni se arma ningún motor. Lo que se comprueba es
la traducción: un `move` con paso en metros tiene que salir como un pulso de
velocidad con su parada, un giro como velocidad angular, y la interfaz tiene
que declarar honestamente lo que el deck no sabe (posición, separación).

Desde la raíz del repositorio:

    python -m pytest -q controllers/two_drones/tests/test_flowdeck_cruz_backend.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_DIR = Path(__file__).resolve().parents[3]
for directory in (PROJECT_DIR / "controllers" / "two_drones",
                  PROJECT_DIR / "controllers" / "shared"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import flowdeck_cruz_backend as adaptador  # noqa: E402
from cruz_highlevel_backend import BridgeError  # noqa: E402
from cruz_highlevel_protocol import Command  # noqa: E402


class ControllerFalso:
    """Doble de `FlowDroneController`: misma interfaz, sin radio."""

    def __init__(self, config, callback=None):
        self.config = config
        self.callback = callback
        self.ready = False
        self.flying = False
        self.height_m = None
        self.velocidades: list[tuple[float, float, float, float]] = []
        self.eventos: list[str] = []

    def connect(self):
        self.eventos.append("connect")

    def wait_ready(self, timeout_s=60.0):
        self.ready = True

    def takeoff(self):
        self.flying = True
        self.eventos.append("takeoff")
        return True

    def velocity(self, vx, vy, vz, yawrate=0.0):
        self.velocidades.append((vx, vy, vz, yawrate))

    def hover(self):
        self.eventos.append("hover")

    def land(self):
        self.flying = False
        self.eventos.append("land")
        return True

    def emergency_stop(self):
        self.eventos.append("emergency")

    def close(self):
        self.eventos.append("close")

    def join(self, timeout=8.0):
        pass


@pytest.fixture
def backend(monkeypatch):
    monkeypatch.setattr(adaptador, "FlowDroneController", ControllerFalso)
    args = SimpleNamespace(uri1="uri-1", uri2="uri-2", single=None,
                           backend="flowdeck", dry_run=False)
    creado = adaptador.FlowCruzBackend(args)
    yield creado
    creado.close()


def _listo(backend):
    backend.connect(lambda *_args: None)
    backend.takeoff(Command("takeoff", "both"))
    return backend


def test_no_se_puede_mover_sin_preflight(backend):
    with pytest.raises(BridgeError, match="PREFLIGHT"):
        backend.move(Command("move", "both", 0.1, 0.0, 0.0))


def test_connect_deja_los_dos_listos(backend):
    avisos = []
    backend.connect(lambda ok, event, message, snap: avisos.append((event, message)))
    assert backend.ready and backend.connected
    # El operador tiene que enterarse de que aqui no hay geocerca.
    assert any("geocerca" in mensaje for _event, mensaje in avisos)


def test_hay_que_despegar_antes_de_mover(backend):
    backend.connect(lambda *_args: None)
    with pytest.raises(BridgeError, match="despega"):
        backend.move(Command("move", "drone1", 0.1, 0.0, 0.0))


def test_un_paso_es_un_pulso_de_velocidad(backend):
    _listo(backend)
    backend.move(Command("move", "drone1", 0.10, 0.0, 0.0))
    enviados = backend.controllers["drone1"].velocidades
    assert len(enviados) == 1
    vx, vy, vz, yawrate = enviados[0]
    assert vx == pytest.approx(adaptador.PASO_VELOCIDAD_MS)
    assert (vy, vz, yawrate) == (0.0, 0.0, 0.0)


def test_el_pulso_se_detiene_solo(backend):
    _listo(backend)
    backend.move(Command("move", "drone1", 0.10, 0.0, 0.0))
    controller = backend.controllers["drone1"]
    assert "hover" not in controller.eventos
    time.sleep(adaptador.PASO_S + 0.35)
    assert "hover" in controller.eventos, "el pulso debe pararse sin otra orden"


def test_el_signo_del_paso_se_conserva(backend):
    _listo(backend)
    backend.move(Command("move", "drone1", 0.0, -0.10, 0.08))
    vx, vy, vz, _yaw = backend.controllers["drone1"].velocidades[0]
    assert vx == 0.0 and vy < 0.0 and vz > 0.0


def test_el_giro_sale_como_velocidad_angular(backend):
    _listo(backend)
    backend.move(Command("move", "drone1", 0.0, 0.0, 0.0, 20.0))
    vx, vy, vz, yawrate = backend.controllers["drone1"].velocidades[0]
    assert (vx, vy, vz) == (0.0, 0.0, 0.0)
    assert yawrate == pytest.approx(adaptador.PASO_GIRO_DEG_S)
    backend.move(Command("move", "drone1", 0.0, 0.0, 0.0, -20.0))
    assert backend.controllers["drone1"].velocidades[1][3] == pytest.approx(
        -adaptador.PASO_GIRO_DEG_S
    )


def test_el_rumbo_se_acumula_igual_que_con_mocap(backend):
    _listo(backend)
    for _ in range(3):
        backend.move(Command("move", "drone1", 0.0, 0.0, 0.0, 20.0))
    assert backend.snapshot()["drone1"]["yaw_deg"] == pytest.approx(60.0)


def test_both_manda_a_los_dos(backend):
    _listo(backend)
    backend.move(Command("move", "both", 0.10, 0.0, 0.0))
    assert len(backend.controllers["drone1"].velocidades) == 1
    assert len(backend.controllers["drone2"].velocidades) == 1


def test_el_snapshot_no_inventa_posicion(backend):
    _listo(backend)
    snapshot = backend.snapshot()
    assert snapshot["mode"] == "flowdeck"
    assert snapshot["separation_m"] is None
    for key in ("drone1", "drone2"):
        assert snapshot[key]["pose"] is None
        assert snapshot[key]["target"] is None
        assert snapshot[key]["airborne"] is True


def test_la_altura_va_en_el_estado(backend):
    _listo(backend)
    backend.controllers["drone1"].height_m = 0.42
    assert "0.42 m" in backend.snapshot()["drone1"]["status"]


def test_la_emergencia_para_todo_y_enclava(backend):
    _listo(backend)
    backend.emergency("prueba")
    snapshot = backend.snapshot()
    assert snapshot["emergency"] and not snapshot["ready"]
    for key in ("drone1", "drone2"):
        assert "emergency" in backend.controllers[key].eventos
    with pytest.raises(BridgeError):
        backend.move(Command("move", "drone1", 0.10, 0.0, 0.0))


def test_no_hay_seguimiento_de_marker(backend):
    _listo(backend)
    with pytest.raises(BridgeError, match="mocap"):
        backend.follow_move(Command("follow_move", "drone1", 0.05, 0.0, 0.0))


def test_modo_de_un_dron(monkeypatch):
    monkeypatch.setattr(adaptador, "FlowDroneController", ControllerFalso)
    args = SimpleNamespace(uri1="uri-1", uri2="uri-2", single="drone2",
                           backend="flowdeck", dry_run=False)
    backend = adaptador.FlowCruzBackend(args)
    try:
        assert set(backend.controllers) == {"drone2"}
        snapshot = backend.snapshot()
        assert snapshot["drone1"]["enabled"] is False
        assert snapshot["drone2"]["enabled"] is True
        backend.connect(lambda *_args: None)
        with pytest.raises(BridgeError, match="deshabilitado"):
            backend.takeoff(Command("takeoff", "drone1"))
    finally:
        backend.close()


def test_close_cancela_los_temporizadores(backend):
    _listo(backend)
    backend.move(Command("move", "drone1", 0.10, 0.0, 0.0))
    backend.close()
    assert all(not timer.is_alive() for timer in backend._timers)
    assert "close" in backend.controllers["drone1"].eventos
