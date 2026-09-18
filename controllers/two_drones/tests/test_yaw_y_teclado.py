"""Giro del vocabulario de vuelo y esquema de teclado. Sin radios ni ventanas.

Cubre lo que cambió al añadir rotación en septiembre de 2026:

* el protocolo acepta `dyaw`, lo limita y sigue rechazando lo que no toca;
* el backend simulado acumula el rumbo y lo envuelve en [-180, 180);
* el teclado asigna Q/E y Inicio/Fin al giro, Enter a despegar o aterrizar, y
  **R al paro**, que hasta ahora era Q.

Desde la raíz del repositorio:

    python -m pytest -q controllers/two_drones/tests/test_yaw_y_teclado.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parents[3]
for directory in (PROJECT_DIR / "controllers" / "two_drones",
                  PROJECT_DIR / "controllers" / "shared"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from cruz_highlevel_backend import SimulatedBackend, _wrap_deg  # noqa: E402
from cruz_highlevel_protocol import (  # noqa: E402
    MAX_YAW_STEP_DEG,
    Command,
    ProtocolError,
    decode_command,
)
import tk_keys  # noqa: E402


# ------------------------------------------------------------- protocolo


def test_move_acepta_dyaw():
    command = decode_command('{"action":"move","target":"drone1","dyaw":15}')
    assert command.dyaw == pytest.approx(15.0)
    assert (command.dx, command.dy, command.dz) == (0.0, 0.0, 0.0)


def test_giro_puro_es_valido():
    """Girar en el sitio no tiene traslación y debe seguir siendo un `move`."""
    command = decode_command('{"action":"move","target":"both","dyaw":-20}')
    assert command.action == "move" and command.dyaw == pytest.approx(-20.0)


def test_move_vacio_sigue_rechazado():
    with pytest.raises(ProtocolError, match="desplazamiento o un giro"):
        decode_command('{"action":"move","target":"drone1"}')


def test_dyaw_fuera_de_limite():
    with pytest.raises(ProtocolError, match="giro maximo"):
        decode_command('{"action":"move","target":"drone1","dyaw":45}')


def test_dyaw_no_numerico_ni_infinito():
    with pytest.raises(ProtocolError):
        decode_command('{"action":"move","target":"drone1","dyaw":"mucho"}')
    with pytest.raises(ProtocolError):
        decode_command('{"action":"move","target":"drone1","dyaw":1e400}')


def test_acciones_sin_giro():
    with pytest.raises(ProtocolError, match="no acepta dyaw"):
        decode_command('{"action":"takeoff","target":"both","dyaw":5}')


def test_dyaw_por_defecto_es_cero():
    assert decode_command('{"action":"land","target":"both"}').dyaw == 0.0


# ---------------------------------------------------------------- backend


def _listo() -> SimulatedBackend:
    backend = SimulatedBackend(None)
    backend.connect(lambda *_args: None)
    backend.takeoff(Command("takeoff", "both"))
    return backend


def test_el_rumbo_se_acumula():
    backend = _listo()
    for _ in range(3):
        backend.move(Command("move", "drone1", 0.0, 0.0, 0.0, 15.0))
    assert backend.snapshot()["drone1"]["yaw_deg"] == pytest.approx(45.0)


def test_el_rumbo_da_la_vuelta():
    backend = _listo()
    for _ in range(10):
        backend.move(Command("move", "drone1", 0.0, 0.0, 0.0, 20.0))
    yaw = backend.snapshot()["drone1"]["yaw_deg"]
    assert -180.0 <= yaw < 180.0
    assert yaw == pytest.approx(-160.0)


def test_el_despegue_reinicia_el_rumbo():
    backend = _listo()
    backend.move(Command("move", "drone1", 0.0, 0.0, 0.0, 20.0))
    backend.land(Command("land", "drone1"))
    backend.takeoff(Command("takeoff", "drone1"))
    assert backend.snapshot()["drone1"]["yaw_deg"] == 0.0


def test_girar_no_mueve():
    backend = _listo()
    antes = list(backend.snapshot()["drone1"]["pose"])
    backend.move(Command("move", "drone1", 0.0, 0.0, 0.0, 10.0))
    assert backend.snapshot()["drone1"]["pose"] == antes


def test_wrap_deg():
    assert _wrap_deg(0.0) == 0.0
    # El intervalo es [-180, 180): media vuelta se nombra -180, no +180.
    assert _wrap_deg(180.0) == pytest.approx(-180.0)
    assert _wrap_deg(190.0) == pytest.approx(-170.0)
    assert _wrap_deg(-190.0) == pytest.approx(170.0)
    assert _wrap_deg(720.0) == pytest.approx(0.0)


# ---------------------------------------------------------------- teclado


def test_teclas_de_giro():
    assert tk_keys.KEY_ROTATIONS["q"] == (0, 1)
    assert tk_keys.KEY_ROTATIONS["e"] == (0, -1)
    assert tk_keys.KEY_ROTATIONS["home"] == (1, 1)
    assert tk_keys.KEY_ROTATIONS["end"] == (1, -1)


def test_las_teclas_de_giro_no_mueven():
    """Ninguna tecla puede estar en las dos tablas: haría dos cosas a la vez."""
    assert not set(tk_keys.KEY_ROTATIONS) & set(tk_keys.KEY_DIRECTIONS)


def test_el_paro_es_r_y_ya_no_q():
    assert "r" in tk_keys.EMERGENCY_KEYSYMS
    assert "q" not in tk_keys.EMERGENCY_KEYSYMS
    assert "Q" not in tk_keys.EMERGENCY_KEYSYMS


def test_enter_esta_ligado():
    assert "Return" in tk_keys.TAKEOFF_LAND_KEYSYMS


def test_las_teclas_de_vuelo_estan_declaradas():
    """`_bind_flight_keys` sólo liga lo que hay en `DUAL_KEYSYMS`."""
    declaradas = {tk_keys.normalize_key(key) for key in tk_keys.DUAL_KEYSYMS}
    faltan = (set(tk_keys.KEY_DIRECTIONS) | set(tk_keys.KEY_ROTATIONS)) - declaradas
    assert not faltan, f"teclas sin ligar: {sorted(faltan)}"


def test_normalize_key():
    assert tk_keys.normalize_key("Shift_L") == "shift"
    assert tk_keys.normalize_key("Prior") == "pageup"
    assert tk_keys.normalize_key("Home") == "home"
    assert tk_keys.normalize_key("Q") == "q"


def test_el_giro_del_panel_cabe_en_el_protocolo():
    """El paso de la interfaz no puede exceder lo que el protocolo acepta."""
    import control_dos_drones_cruz_botones as panel

    assert panel.STEP_YAW_DEG <= MAX_YAW_STEP_DEG


# ------------------------------------------------- el giro cruza el proceso


def test_el_giro_llega_al_backend_del_otro_proceso():
    """El panel multiproceso habla por JSON: si no manda `dyaw`, el giro se pierde.

    Es un fallo silencioso —el `move` se acepta y el dron no gira—, así que se
    comprueba lo que sale por el cable y no sólo lo que recibe el backend.
    """
    import control_dos_drones_cruz_multiprocessing as runtime

    enviados: list[dict] = []

    class SocketFalso:
        def sendall(self, payload: bytes) -> None:
            enviados.append(__import__("json").loads(payload.decode()))

    cliente = runtime.ProcessBackend.__new__(runtime.ProcessBackend)
    cliente.socket = SocketFalso()
    cliente._lock = __import__("threading").RLock()
    cliente._closed = False
    cliente._receive = lambda: {"ok": True, "event": "move", "message": "", "snapshot": None}

    cliente.move(Command("move", "drone1", 0.0, 0.0, 0.0, 20.0))
    assert enviados[-1]["dyaw"] == pytest.approx(20.0)

    cliente.move(Command("move", "drone2", 0.10, 0.0, 0.0))
    assert enviados[-1]["dyaw"] == 0.0
    assert enviados[-1]["dx"] == pytest.approx(0.10)
