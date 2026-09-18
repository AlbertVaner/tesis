"""`FlowDroneController.connect()` registra los drivers de cflib. Sin radio.

Sin `cflib.crtp.init_drivers()` la lista de drivers queda vacía y `open_link`
responde "No driver found or malformed URI" aunque la Crazyradio esté
conectada y la URI sea correcta. La ruta de Flow deck no pasa por el backend
mocap, que sí inicializa, así que lo hace el propio controlador. Se sustituye
`init_drivers` por un doble y el hilo de la radio por nada.

Desde la raíz del repositorio:

    python -m pytest -q controllers/two_drones/tests/test_flowdeck_drivers.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import cflib.crtp

PROJECT_DIR = Path(__file__).resolve().parents[3]
for directory in (PROJECT_DIR / "controllers" / "two_drones",
                  PROJECT_DIR / "controllers" / "shared"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import flowdeck_dual_backend as backend  # noqa: E402


def _controlador(monkeypatch):
    monkeypatch.setattr(backend.FlowDroneController, "_worker", lambda self: None)
    config = backend.FlowDroneConfig(name="Dron 1", uri="radio://2B1D933FCC/84/2M/E7E7E7E7E4")
    return backend.FlowDroneController(config, callback=lambda state, message: None)


def test_connect_inicializa_los_drivers_si_la_lista_esta_vacia(monkeypatch):
    llamadas: list[dict] = []
    monkeypatch.setattr(cflib.crtp, "CLASSES", [])
    monkeypatch.setattr(
        cflib.crtp, "init_drivers", lambda **kwargs: llamadas.append(kwargs)
    )

    controlador = _controlador(monkeypatch)
    controlador.connect()
    controlador.join(2.0)

    assert llamadas == [{"enable_debug_driver": False}]


def test_connect_no_duplica_los_drivers_ya_registrados(monkeypatch):
    llamadas: list[dict] = []
    monkeypatch.setattr(cflib.crtp, "CLASSES", [object])
    monkeypatch.setattr(
        cflib.crtp, "init_drivers", lambda **kwargs: llamadas.append(kwargs)
    )

    controlador = _controlador(monkeypatch)
    controlador.connect()
    controlador.join(2.0)

    assert llamadas == []
