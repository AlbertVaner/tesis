"""Regla estatica del paro de emergencia. Sin camara y sin MediaPipe.

Poses sinteticas en el marco del cuerpo (torso = 1.0). Se verifica que la X
sobre la cabeza dispare al sostenerse, que no dispare antes, que un cruce
casual de brazos sobre el pecho no la active, que los brazos arriba SIN cruzar
(el senalero) tampoco, que un hueco corto de pose no rompa la racha y que un
hueco largo si.

Uso, desde la raiz del repositorio:

    python -m pytest -q external/gesture_detection/tests/test_paro_estatico.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

TESTS_DIR = Path(__file__).resolve().parent
GESTURE_DIR = TESTS_DIR.parent
if str(GESTURE_DIR) not in sys.path:
    sys.path.insert(0, str(GESTURE_DIR))

from pose.normalize import (  # noqa: E402
    LEFT_ELBOW,
    LEFT_SHOULDER,
    LEFT_WRIST,
    N_LANDMARKS,
    RIGHT_ELBOW,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
)
from recognition.paro_estatico import NOSE, ReglaParo  # noqa: E402

FPS = 30.0


def base() -> np.ndarray:
    """De pie, brazos a los lados. +X izquierda del sujeto, +Y arriba."""
    P = np.zeros((N_LANDMARKS, 3))
    P[NOSE] = (0.0, 1.30, 0.05)
    P[LEFT_SHOULDER] = (0.30, 1.0, 0.0)
    P[RIGHT_SHOULDER] = (-0.30, 1.0, 0.0)
    P[LEFT_ELBOW] = (0.35, 0.55, 0.0)
    P[RIGHT_ELBOW] = (-0.35, 0.55, 0.0)
    P[LEFT_WRIST] = (0.35, 0.15, 0.05)
    P[RIGHT_WRIST] = (-0.35, 0.15, 0.05)
    return P


def x_cabeza() -> np.ndarray:
    P = base()
    P[LEFT_ELBOW] = (0.25, 1.35, 0.15)
    P[RIGHT_ELBOW] = (-0.25, 1.35, 0.15)
    P[LEFT_WRIST] = (-0.12, 1.55, 0.15)     # izquierda cruza a la derecha
    P[RIGHT_WRIST] = (0.12, 1.55, 0.15)     # derecha cruza a la izquierda
    return P


def brazos_cruzados_pecho() -> np.ndarray:
    P = base()
    P[LEFT_ELBOW] = (0.25, 0.70, 0.15)
    P[RIGHT_ELBOW] = (-0.25, 0.70, 0.15)
    P[LEFT_WRIST] = (-0.20, 0.80, 0.20)
    P[RIGHT_WRIST] = (0.20, 0.80, 0.20)
    return P


def senalero(k: int) -> np.ndarray:
    """Brazos arriba, antebrazos oscilando: las munecas NO se cruzan."""
    P = base()
    d = 0.15 * np.sin(2 * np.pi * k / 20)
    P[LEFT_ELBOW] = (0.35, 1.30, 0.10)
    P[RIGHT_ELBOW] = (-0.35, 1.30, 0.10)
    P[LEFT_WRIST] = (0.30 + d, 1.60, 0.10)
    P[RIGHT_WRIST] = (-0.30 + d, 1.60, 0.10)
    return P


def correr(regla, poses, t0=0.0):
    disparos = []
    for k, P in enumerate(poses):
        if regla.actualizar(P, t0 + k / FPS):
            disparos.append(k)
    return disparos


def test_dispara_al_sostener():
    regla = ReglaParo("cabeza")
    poses = [base()] * 10 + [x_cabeza()] * 60
    d = correr(regla, poses)
    assert len(d) == 1, d
    assert 10 + 29 <= d[0] <= 10 + 31, d      # ~1.0 s despues de empezar
    assert regla.activo


def test_no_dispara_si_no_se_sostiene():
    regla = ReglaParo("cabeza")
    poses = [x_cabeza()] * 20 + [base()] * 20 + [x_cabeza()] * 20
    assert correr(regla, poses) == []
    assert not regla.activo


def test_cruce_casual_en_el_pecho_no_es_paro():
    regla = ReglaParo("cabeza")
    assert correr(regla, [brazos_cruzados_pecho()] * 120) == []
    faltan = [m.etiqueta for m in regla.medidas if not m.cumple]
    assert "munecas sobre nariz" in faltan


def test_senalero_no_es_paro():
    regla = ReglaParo("cabeza")
    assert correr(regla, [senalero(k) for k in range(120)]) == []


def test_hueco_corto_no_rompe_y_largo_si():
    corto = [x_cabeza()] * 15 + [None] * 4 + [x_cabeza()] * 40
    assert len(correr(ReglaParo("cabeza"), corto)) == 1
    largo = [x_cabeza()] * 15 + [None] * 15 + [x_cabeza()] * 20
    assert correr(ReglaParo("cabeza"), largo) == []


def test_dispara_una_vez_y_se_rearma():
    regla = ReglaParo("cabeza")
    poses = [x_cabeza()] * 60 + [base()] * 30 + [x_cabeza()] * 60
    d = correr(regla, poses)
    assert len(d) == 2, d


def test_postura_pecho_con_sus_umbrales():
    regla = ReglaParo("pecho")
    P = brazos_cruzados_pecho()            # munecas a 0.80: pasa el 0.70
    assert len(correr(regla, [P] * 90)) == 1
    bajo = brazos_cruzados_pecho()
    bajo[LEFT_WRIST][1] = bajo[RIGHT_WRIST][1] = 0.55
    assert correr(ReglaParo("pecho"), [bajo] * 90) == []


def test_pose_incompleta_no_rompe():
    regla = ReglaParo("cabeza")
    P = x_cabeza()
    P[NOSE] = np.nan
    assert correr(regla, [P] * 60) == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
