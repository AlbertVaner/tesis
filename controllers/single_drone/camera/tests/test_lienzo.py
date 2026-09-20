"""Lienzo de `control_camara_dron1.py` y ventana sin deformar. Sin camara ni ventanas.

Desde el 2026-09-18 la camara IP esta montada de lado y el cuadro llega en
vertical (480x640 el sub-stream). Dos cosas fallaban en silencio: el texto del
panel se cortaba en un cuadro de 480 px de ancho, y una ventana apaisada de
tamano fijo aplastaba la imagen.

Uso, desde la raiz del repositorio::

    .\\.venv\\Scripts\\python.exe -m pytest -q .\\controllers\\single_drone\\camera\\tests\\test_lienzo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

CAMERA_DIR = Path(__file__).resolve().parent.parent
if str(CAMERA_DIR) not in sys.path:
    sys.path.insert(0, str(CAMERA_DIR))

import control_camara_dron1 as ctrl  # noqa: E402
from visualization.ventana import tamano_ventana  # noqa: E402


def _frame(ancho: int, alto: int):
    return np.full((alto, ancho, 3), 200, np.uint8)


def test_un_cuadro_vertical_se_completa_hasta_el_ancho_minimo():
    salida = ctrl.lienzo(_frame(480, 640))
    assert salida.shape == (ctrl.ALTO_LIENZO, ctrl.ANCHO_MINIMO_LIENZO, 3)
    # La imagen queda a la izquierda sin deformar (480x640 -> 540x720) y la
    # banda de la derecha es fondo.
    assert (salida[:, :540] == 200).all()
    assert (salida[:, 540:] == ctrl.FONDO_LIENZO[0]).all()


def test_un_cuadro_720p_no_se_toca():
    entrada = _frame(1280, 720)
    assert ctrl.lienzo(entrada) is entrada


def test_la_webcam_se_escala_sin_banda():
    assert ctrl.lienzo(_frame(640, 480)).shape == (720, 960, 3)


@pytest.mark.parametrize("ancho, alto", [(960, 720), (845, 720), (1720, 720), (1440, 2560)])
def test_la_ventana_conserva_la_proporcion(ancho, alto):
    w, h = tamano_ventana(ancho, alto)
    assert h <= 900
    assert w / h == pytest.approx(ancho / alto, rel=0.01)
