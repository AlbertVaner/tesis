"""Geometria de la lamina y de los GIF de gestos dinamicos. Sin camara ni datos.

Las tomas grabadas viven en `results/`, que no se versiona, asi que aqui se
usan poses sinteticas. Lo que se comprueba es lo que se rompio de verdad al
escribir el modulo: que la ventana del dibujo cubra **solo** lo que se pinta, y
que las cajas de las dos vistas conserven la escala.

Uso, desde la raiz del repositorio:

    python -m pytest -q external/gesture_detection/tests/test_esquema_gestos_dinamicos.py
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
    LEFT_HIP,
    LEFT_SHOULDER,
    LEFT_WRIST,
    N_LANDMARKS,
    RIGHT_ELBOW,
    RIGHT_HIP,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
)
from visualization.esquema_gestos_dinamicos import (  # noqa: E402
    DIBUJADOS,
    NOSE,
    _cuello,
    _proyectar,
    _suavizar,
    _tamano_vistas,
    extension,
)

TOBILLO_IZQ, TOBILLO_DER = 27, 28


def pose(altura_munecas: float = 0.2) -> np.ndarray:
    """De pie. Las piernas van muy abajo: son las que no se dibujan."""
    P = np.zeros((N_LANDMARKS, 3))
    P[NOSE] = (0.0, 1.30, 0.05)
    P[LEFT_SHOULDER] = (0.30, 1.0, 0.0)
    P[RIGHT_SHOULDER] = (-0.30, 1.0, 0.0)
    P[LEFT_HIP] = (0.18, 0.0, 0.0)
    P[RIGHT_HIP] = (-0.18, 0.0, 0.0)
    P[LEFT_ELBOW] = (0.34, 0.55, 0.10)
    P[RIGHT_ELBOW] = (-0.34, 0.55, 0.10)
    P[LEFT_WRIST] = (0.36, altura_munecas, 0.25)
    P[RIGHT_WRIST] = (-0.36, altura_munecas, 0.25)
    P[TOBILLO_IZQ] = (0.16, -2.40, 0.0)
    P[TOBILLO_DER] = (-0.16, -2.40, 0.0)
    return P


def item(poses: np.ndarray):
    """Una entrada con la forma que consumen `extension` y el dibujo."""
    tiempos = np.linspace(0.0, len(poses) / 30.0, len(poses))
    return ("prueba", "PRUEBA", "como", "accion", poses, tiempos, 1.0, "nadie")


def test_solo_se_mide_lo_que_se_dibuja():
    """La ventana no puede llegar a los tobillos: no se pintan.

    Es el fallo que dejaba al cuerpo a un tercio de su tamano, con media celda
    en blanco debajo.
    """
    poses = np.stack([pose(), pose(0.9)])
    x0, x1, y0, y1 = extension([item(poses)], "frente")
    assert y0 > -1.0, "la ventana baja hasta las piernas"
    assert y0 < 0.0 < y1 and y1 > 1.3, "deja fuera cabeza o caderas"
    assert TOBILLO_IZQ not in DIBUJADOS and NOSE in DIBUJADOS


def test_las_dos_vistas_usan_ejes_distintos():
    """De frente manda X; de perfil, Z. Si no, `ven_aca` parece quieto."""
    P = pose()
    frente = _proyectar(P, "frente")
    perfil = _proyectar(P, "perfil")
    assert frente[LEFT_WRIST][0] == pytest.approx(P[LEFT_WRIST][0])
    assert perfil[LEFT_WRIST][0] == pytest.approx(P[LEFT_WRIST][2])
    # El vertical es el mismo en las dos: es la altura del cuerpo.
    assert frente[NOSE][1] == perfil[NOSE][1] == pytest.approx(P[NOSE][1])


def test_el_cuello_une_hombros_y_nariz():
    Q = _proyectar(pose(), "frente")
    xs, ys = _cuello(Q)
    assert xs[0] == pytest.approx(0.0), "arranca en el medio de los hombros"
    assert ys[0] == pytest.approx(1.0)
    assert (xs[1], ys[1]) == pytest.approx((Q[NOSE, 0], Q[NOSE, 1]))


def test_sin_hombros_no_hay_cuello():
    P = pose()
    P[LEFT_SHOULDER] = np.nan
    assert _cuello(_proyectar(P, "frente")) is None


def test_las_cajas_conservan_la_escala():
    """Misma escala en las dos vistas: si no, el operador sale de dos tamanos."""
    limites = {"frente": (-1.0, 1.0, 0.0, 2.0), "perfil": (-0.5, 0.5, 0.0, 2.0)}
    cajas = _tamano_vistas(limites)
    escala_frente = cajas["frente"][0] / 2.0
    escala_perfil = cajas["perfil"][0] / 1.0
    assert escala_frente == pytest.approx(escala_perfil, rel=1e-9)
    assert cajas["frente"][1] == pytest.approx(cajas["perfil"][1])
    # Y la caja tiene la proporcion de su ventana, que es lo que evita el hueco.
    assert cajas["frente"][0] / cajas["frente"][1] == pytest.approx(2.0 / 2.0)


def test_suavizado_acorta_y_no_inventa():
    T = np.array([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0], [3.0, 0.0], [4.0, 0.0]])
    S = _suavizar(T, 3)
    assert len(S) == len(T) - 2
    assert S[:, 0] == pytest.approx([1.0, 2.0, 3.0])
    assert S[:, 0].max() <= T[:, 0].max()


def test_suavizado_no_toca_una_estela_corta():
    T = np.array([[0.0, 0.0], [1.0, 1.0]])
    assert _suavizar(T, 3) is T


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
