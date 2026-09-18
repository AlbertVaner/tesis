"""Aritmetica angular de `medir_ptz.py`. Sin camara.

El pan da la vuelta en 360 grados, asi que restar posiciones a secas produce
saltos de 350 grados donde hubo un movimiento de 10. Esa resta es lo unico de
`medir_ptz` que puede estar mal en silencio: si se equivoca, la velocidad
medida sale absurda justo en el cruce del cero, que es donde estaba la camara
del laboratorio.

Uso, desde la raiz del repositorio::

    .\\.venv\\Scripts\\python.exe -m pytest -q .\\external\\gesture_detection\\tests\\test_medir_ptz.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

MODULE_DIR = Path(__file__).resolve().parents[1]
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from medir_ptz import diferencia_angular  # noqa: E402


@pytest.mark.parametrize(
    "a, b, esperado",
    [
        (10.0, 0.0, 10.0),
        (0.0, 10.0, -10.0),
        (0.0, 0.0, 0.0),
        (90.0, 45.0, 45.0),
    ],
)
def test_resta_normal(a, b, esperado):
    assert diferencia_angular(a, b) == pytest.approx(esperado)


@pytest.mark.parametrize(
    "a, b, esperado",
    [
        (10.0, 350.0, 20.0),    # cruza el cero hacia adelante
        (350.0, 10.0, -20.0),   # y hacia atras
        (1.0, 359.0, 2.0),
        (359.0, 1.0, -2.0),
    ],
)
def test_cruce_del_cero(a, b, esperado):
    """Un movimiento de 20 grados no puede leerse como uno de 340."""
    assert diferencia_angular(a, b) == pytest.approx(esperado)


def test_siempre_devuelve_el_camino_corto():
    for a in range(0, 360, 7):
        for b in range(0, 360, 11):
            assert -180.0 <= diferencia_angular(float(a), float(b)) <= 180.0


def test_es_antisimetrica():
    for a, b in ((10.0, 350.0), (45.0, 90.0), (200.0, 30.0)):
        ida = diferencia_angular(a, b)
        vuelta = diferencia_angular(b, a)
        # El caso de 180 exactos es ambiguo por definicion y se excluye.
        if abs(ida) != 180.0:
            assert ida == pytest.approx(-vuelta)
