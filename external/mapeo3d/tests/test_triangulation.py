"""Pruebas del DLT, sin cámaras y sin calibración.

Se define un punto 3D conocido, se proyecta con matrices sintéticas, y se
comprueba que la reconstrucción vuelve al punto original. Es la validación de
nivel 1 que exige AGENTS.md: si esto falla, todo lo que se construya encima
está mal.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mapeo3d.triangulation import (  # noqa: E402
    MIN_VISTAS,
    angulo_utilizable,
    camera_center,
    grid_spacing,
    project,
    ray_angle_deg,
    reprojection_error,
    triangulate,
    triangulate_many,
)

FOCAL = 1710.0
W, H = 2304, 1296
K = np.array([[FOCAL, 0, W / 2], [0, FOCAL, H / 2], [0, 0, 1]], dtype=np.float64)


def _P(R: np.ndarray, C: np.ndarray) -> np.ndarray:
    """Matriz de proyección de una cámara con rotación R y centro C."""
    t = -R @ np.asarray(C, dtype=np.float64).reshape(3, 1)
    return K @ np.hstack([R, t])


@pytest.fixture
def par_estereo():
    """Dos cámaras separadas 1.5 m, la segunda girada 30° hacia el centro."""
    import cv2

    Pa = _P(np.eye(3), np.zeros(3))
    R = cv2.Rodrigues(np.array([0.0, np.deg2rad(30.0), 0.0]))[0]
    Pb = _P(R, np.array([1.5, 0.0, 0.0]))
    return np.stack([Pa, Pb])


def test_reconstruye_un_punto_conocido(par_estereo):
    X = np.array([0.6, -0.05, 2.0])
    obs = np.stack([project(P, X)[0] for P in par_estereo])
    Xr = triangulate(par_estereo, obs)
    assert np.linalg.norm(Xr - X) < 1e-6


def test_reconstruye_muchos_puntos(par_estereo):
    X = np.array([[0.6, -0.05, 2.0], [0.8, 0.1, 2.2], [0.5, 0.02, 1.9]])
    obs = np.stack([project(P, X) for P in par_estereo])
    Xr = triangulate_many(par_estereo, obs)
    assert np.abs(Xr - X).max() < 1e-6


def test_tolera_ruido_de_deteccion(par_estereo):
    """Con ruido realista de 0.25 px el error 3D debe quedar en milímetros."""
    rng = np.random.default_rng(0)
    X = np.array([[0.6, 0.0, 2.0]])
    obs = np.stack([project(P, X) for P in par_estereo])
    obs = obs + rng.normal(0, 0.25, obs.shape)
    Xr = triangulate_many(par_estereo, obs)
    assert np.linalg.norm(Xr - X) < 0.01  # < 1 cm


def test_mas_vistas_reducen_el_error():
    """El DLT es N-vistas: añadir cámaras debe mejorar, no romper."""
    import cv2

    rng = np.random.default_rng(1)
    X = np.array([[0.0, 0.0, 2.0]])
    Ps = []
    for ang in (-40, -20, 20, 40):
        R = cv2.Rodrigues(np.array([0.0, np.deg2rad(-ang), 0.0]))[0]
        C = np.array([np.sin(np.deg2rad(ang)) * 1.5, 0.0, 0.0])
        Ps.append(_P(R, C))
    Ps = np.stack(Ps)

    errores = {}
    for n in (2, 4):
        acc = []
        for _ in range(40):
            obs = np.stack([project(P, X) for P in Ps[:n]])
            obs = obs + rng.normal(0, 0.5, obs.shape)
            acc.append(np.linalg.norm(triangulate_many(Ps[:n], obs) - X))
        errores[n] = float(np.mean(acc))
    assert errores[4] < errores[2]


def test_rechaza_una_sola_vista(par_estereo):
    with pytest.raises(ValueError, match="al menos"):
        triangulate(par_estereo[:1], np.array([[100.0, 100.0]]))
    assert MIN_VISTAS == 2


def test_error_de_reproyeccion(par_estereo):
    X = np.array([[0.6, 0.0, 2.0]])
    obs = np.stack([project(P, X) for P in par_estereo])
    Xr = triangulate_many(par_estereo, obs)
    assert reprojection_error(par_estereo, obs, Xr).max() < 1e-6


def test_centros_opticos(par_estereo):
    assert np.linalg.norm(camera_center(par_estereo[0])) < 1e-9
    assert np.linalg.norm(camera_center(par_estereo[1]) - np.array([1.5, 0, 0])) < 1e-6


def test_angulo_entre_rayos(par_estereo):
    ang = ray_angle_deg(par_estereo[0], par_estereo[1], np.array([0.6, 0.0, 2.0]))
    assert 20.0 < ang < 90.0
    assert angulo_utilizable(ang)


def test_angulos_degenerados_se_rechazan():
    """Los dos extremos son igual de malos: paralelo y colineal."""
    assert not angulo_utilizable(2.0)      # rayos casi paralelos
    assert not angulo_utilizable(179.0)    # rayos casi colineales
    assert angulo_utilizable(77.0)         # esquinas adyacentes del Robotat
    assert angulo_utilizable(103.0)


def test_grid_spacing_mide_la_casilla(par_estereo):
    """Comprobación métrica absoluta: una rejilla de 24 mm debe medir 24 mm."""
    cols, rows, lado = 9, 6, 0.024
    ij = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2) * lado
    X = np.hstack([ij + np.array([0.4, -0.05]), np.full((len(ij), 1), 2.0)])
    obs = np.stack([project(P, X) for P in par_estereo])
    Xr = triangulate_many(par_estereo, obs)
    media, desv = grid_spacing(Xr, cols, rows)
    assert abs(media - lado) < 1e-6
    assert desv < 1e-6
