"""Construccion del backend de hardware. Sin radios y sin volar.

Existe por un fallo real del 2026-09-12: al hacer configurable el ritmo de
extpos se uso `EXTPOS_RATE_HZ` dentro de `HardwareBackend.__init__` sin
importarlo alli. `compileall` no detecta nombres sin definir y ninguna prueba
tocaba ese camino, asi que el error aparecio en el laboratorio, con el dron
delante:

    No se pudo iniciar el backend: name 'EXTPOS_RATE_HZ' is not defined

Construir el backend no abre radios ni manda nada: solo resuelve imports y
arma las unidades. Es barato de probar y cubre toda esa clase de fallo.

Uso, desde la raiz del repositorio::

    .\\.venv\\Scripts\\python.exe -m pytest -q .\\controllers\\two_drones\\tests\\test_backend_construccion.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
for ruta in (RAIZ, RAIZ.parent / "shared"):
    if str(ruta) not in sys.path:
        sys.path.insert(0, str(ruta))

cruz_highlevel_backend = pytest.importorskip("cruz_highlevel_backend")


def _args(**extra) -> argparse.Namespace:
    base = dict(
        uri1="radio://0/84/2M/E7E7E7E7E4",
        uri2="radio://0/90/2M/E7E7E7E7E5",
        topic1="mocap/drone3",
        topic2="mocap/drone4",
        single="drone1",
    )
    base.update(extra)
    return argparse.Namespace(**base)


@pytest.fixture
def backend():
    pytest.importorskip("cflib")
    return cruz_highlevel_backend.HardwareBackend(_args(extpos_hz=40.0))


def test_el_backend_se_construye_sin_radios(backend):
    """Si falta un import en __init__, esto revienta aqui y no en el laboratorio."""
    assert set(backend.units) == {"drone1", "drone2"}


def test_snapshot_funciona_sin_radios(backend):
    """El segundo fallo del 2026-09-12: `reloj` importado dentro de __init__.

    Quedaba como variable local de ese metodo, asi que `_unit_snapshot` no lo
    veia y el panel reventaba al pintar el primer estado. Construir el backend
    no basta como prueba: hay que EJECUTAR sus caminos de lectura.
    """
    estado = backend.snapshot()
    assert isinstance(estado, dict)
    assert "mode" in estado, "el panel lee 'mode' nada mas arrancar"


def test_snapshot_trae_una_entrada_por_dron(backend):
    estado = backend.snapshot()
    for clave in ("drone1", "drone2"):
        assert clave in estado


def test_snapshot_se_puede_repetir(backend):
    """El panel lo llama en bucle; no puede depender de estado de la primera vez."""
    for _ in range(3):
        assert backend.snapshot()


def test_el_ritmo_de_extpos_llega_a_las_unidades(backend):
    for unidad in backend.units.values():
        assert unidad.extpos_rate_hz == 40.0


def test_sin_el_argumento_se_usa_el_valor_por_defecto():
    pytest.importorskip("cflib")
    from drone_unit import EXTPOS_RATE_HZ
    hb = cruz_highlevel_backend.HardwareBackend(_args())
    for unidad in hb.units.values():
        assert unidad.extpos_rate_hz == EXTPOS_RATE_HZ


def test_single_deja_una_sola_unidad_activa(backend):
    assert backend.active_keys == ("drone1",)


def test_sin_single_se_activan_las_dos():
    pytest.importorskip("cflib")
    hb = cruz_highlevel_backend.HardwareBackend(_args(single=None))
    assert set(hb.active_keys) == {"drone1", "drone2"}
