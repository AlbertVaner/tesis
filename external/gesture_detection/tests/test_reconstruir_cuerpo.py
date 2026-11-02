r"""Esqueleto 3D del operador en el marco del Robotat: ejes, colocacion y mano del marker. Sin camara.

Uso, desde la raiz del repositorio::

    .\.venv\Scripts\python.exe -m pytest -q .\external\gesture_detection\tests\test_reconstruir_cuerpo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

MODULE_DIR = Path(__file__).resolve().parents[1]
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import reconstruir_cuerpo as rc  # noqa: E402


def _cuerpo():
    """33 landmarks de MediaPipe (x der., y abajo, z lejos) de alguien de pie."""
    rel = np.zeros((33, 3))
    rel[0] = [0.0, -0.65, 0.0]                      # nariz
    rel[11], rel[12] = [-0.18, -0.5, 0.0], [0.18, -0.5, 0.0]
    rel[15], rel[16] = [-0.25, 0.0, -0.3], [0.25, -0.1, -0.3]   # munecas, hacia la camara
    rel[27], rel[28] = [-0.1, 0.9, 0.0], [0.1, 0.9, 0.0]        # tobillos
    vis = np.ones(33)
    return rel, vis


def test_la_camara_mira_del_poste_al_operador():
    derecha, adelante = rc.ejes_de_camara([-2.0, 0.0], [0.0, 0.0])
    assert adelante == pytest.approx([1.0, 0.0])
    # Mirando hacia +x, la derecha de la imagen es -y.
    assert derecha == pytest.approx([0.0, -1.0])


def test_arriba_de_mediapipe_es_z_del_robotat_y_lejos_es_hacia_donde_mira():
    rel, _ = _cuerpo()
    p = rc.al_robotat(rel, *rc.ejes_de_camara([-2.0, 0.0], [0.0, 0.0]))
    assert p[0, 2] == pytest.approx(0.65)            # la nariz queda arriba
    assert p[16, 0] == pytest.approx(-0.3)           # la muneca adelantada hacia la camara (-x)
    assert p[16, 1] == pytest.approx(-0.25)          # y a la derecha de la imagen (-y)


def test_la_mano_cae_en_el_marker_y_los_pies_en_el_suelo():
    rel, vis = _cuerpo()
    p = rc.al_robotat(rel, *rc.ejes_de_camara([-2.0, 0.0], [0.5, 0.5]))
    marker = np.array([0.4, 0.3, 1.0])
    cuerpo = rc.colocar(p, vis, marker, "der")
    assert cuerpo[16, :2] == pytest.approx(marker[:2])
    assert min(cuerpo[27, 2], cuerpo[28, 2]) == pytest.approx(0.0)


def test_la_mano_del_marker_es_la_que_esta_a_su_altura():
    rel, vis = _cuerpo()
    p = rc.al_robotat(rel, *rc.ejes_de_camara([-2.0, 0.0], [0.0, 0.0]))
    # Pies en el suelo -> cadera a 0.9 m; muneca derecha a 1.0 m, izquierda a 0.9 m.
    assert rc.mano_del_marker([(p, vis, np.array([0.0, 0.0, 1.0]))] * 5) == "der"
    assert rc.mano_del_marker([(p, vis, np.array([0.0, 0.0, 0.9]))] * 5) == "izq"
