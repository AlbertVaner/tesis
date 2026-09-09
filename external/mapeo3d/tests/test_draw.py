"""Dibujado 3D: cambio de marco, cámara orbital y proyección en perspectiva.

Es código de presentación, pero la geometría se puede equivocar en silencio:
una vista 3D mal proyectada sigue pareciendo un esqueleto plausible. Estas
pruebas fijan las tres cosas que, si se rompen, hacen que la demo enseñe algo
falso.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from mapeo3d.pose import (  # noqa: E402
    N_LANDMARKS,
    a_escena,
    camara_orbital,
    dibujar_esqueleto_2d,
    dibujar_esqueleto_3d,
    dibujar_rejilla,
    pares_de_conexiones,
    proyectar,
)
from mapeo3d.pose.landmarks import NOMBRES  # noqa: E402


# --------------------------------------------------------------- marco


def test_el_cambio_de_marco_pone_z_hacia_arriba():
    """MediaPipe tiene `y` hacia ABAJO; la escena lo quiere hacia arriba."""
    # Un punto por encima de las caderas tiene y negativa en MediaPipe.
    arriba_mp = np.array([[0.0, -0.5, 0.0]])
    assert a_escena(arriba_mp)[0, 2] == pytest.approx(0.5)

    # z de MediaPipe (alejarse) pasa a ser la profundidad Y de la escena.
    lejos_mp = np.array([[0.0, 0.0, 0.4]])
    assert a_escena(lejos_mp)[0, 1] == pytest.approx(0.4)

    # x no cambia.
    assert a_escena(np.array([[0.3, 0.0, 0.0]]))[0, 0] == pytest.approx(0.3)


# --------------------------------------------------------------- cámara


def test_la_camara_orbital_mira_al_origen_y_es_ortonormal():
    ojo, base = camara_orbital(35.0, 20.0, 2.5)
    assert np.linalg.norm(ojo) == pytest.approx(2.5)
    # "Adelante" apunta del ojo al origen.
    assert np.allclose(base[2], -ojo / np.linalg.norm(ojo))
    # Base ortonormal.
    assert np.allclose(base @ base.T, np.eye(3), atol=1e-9)


def test_el_azimut_gira_alrededor_del_eje_vertical():
    ojo0, _ = camara_orbital(0.0, 0.0, 2.0)
    ojo90, _ = camara_orbital(90.0, 0.0, 2.0)
    assert ojo0 == pytest.approx([2.0, 0.0, 0.0], abs=1e-9)
    assert ojo90 == pytest.approx([0.0, 2.0, 0.0], abs=1e-9)


def test_mirando_desde_arriba_no_degenera():
    """Con elevación 90° el producto vectorial con la vertical se anula."""
    _ojo, base = camara_orbital(0.0, 90.0, 2.0)
    assert np.all(np.isfinite(base))
    assert np.allclose(base @ base.T, np.eye(3), atol=1e-6)


# ----------------------------------------------------------- proyección


def test_el_origen_cae_en_el_centro_del_panel():
    ojo, base = camara_orbital(-70.0, 16.0, 2.4)
    pix, ok = proyectar(np.zeros((1, 3)), ojo, base, lado=400, focal_px=360.0)
    assert ok[0]
    assert pix[0] == pytest.approx([200.0, 200.0], abs=1e-6)


def test_lo_que_esta_detras_de_la_camara_se_marca_no_visible():
    """Sin esta comprobación un punto de detrás se proyecta invertido y
    aparece como un miembro imposible al otro lado de la pantalla."""
    ojo, base = camara_orbital(0.0, 0.0, 2.0)   # ojo en (2, 0, 0), mira a -X
    detras = np.array([[5.0, 0.0, 0.0]])        # más lejos aún en +X
    _pix, ok = proyectar(detras, ojo, base, lado=400, focal_px=360.0)
    assert not ok[0]


def test_lo_mas_cercano_se_ve_mas_grande():
    """Comprobación de que la proyección es en perspectiva y no ortográfica."""
    ojo, base = camara_orbital(0.0, 0.0, 3.0)
    cerca = np.array([[0.0, 0.5, 0.0], [0.0, -0.5, 0.0]])
    lejos = np.array([[-1.5, 0.5, 0.0], [-1.5, -0.5, 0.0]])
    pc, okc = proyectar(cerca, ojo, base, 400, 360.0)
    pl, okl = proyectar(lejos, ojo, base, 400, 360.0)
    assert okc.all() and okl.all()
    separacion_cerca = abs(pc[0, 0] - pc[1, 0])
    separacion_lejos = abs(pl[0, 0] - pl[1, 0])
    assert separacion_cerca > separacion_lejos * 1.3


def test_los_no_finitos_no_se_dan_por_visibles():
    ojo, base = camara_orbital(30.0, 10.0, 2.0)
    p = np.array([[0.0, 0.0, 0.0], [np.nan, 0.0, 0.0]])
    _pix, ok = proyectar(p, ojo, base, 400, 360.0)
    assert ok[0] and not ok[1]


# ------------------------------------------------------------- dibujado


def _esqueleto():
    rng = np.random.default_rng(0)
    return rng.uniform(-0.5, 0.5, size=(N_LANDMARKS, 3))


def test_dibuja_algo_en_el_panel_3d():
    panel = np.full((300, 300, 3), 24, np.uint8)
    ojo, base = camara_orbital(-70.0, 16.0, 2.4)
    dibujar_esqueleto_3d(panel, _esqueleto(), np.full(N_LANDMARKS, 0.9),
                         pares_de_conexiones(), NOMBRES, ojo, base, 270.0)
    assert panel.std() > 5, "no pintó nada"


def test_un_esqueleto_con_nan_no_revienta():
    mundo = _esqueleto()
    mundo[5:9] = np.nan
    panel = np.full((300, 300, 3), 24, np.uint8)
    ojo, base = camara_orbital(20.0, 10.0, 2.4)
    dibujar_esqueleto_3d(panel, mundo, np.full(N_LANDMARKS, 0.9),
                         pares_de_conexiones(), NOMBRES, ojo, base, 270.0)
    assert np.all(np.isfinite(panel.astype(float)))


def test_los_landmarks_poco_visibles_no_se_dibujan():
    conexiones = pares_de_conexiones()
    ojo, base = camara_orbital(-70.0, 16.0, 2.4)
    visible = np.full((300, 300, 3), 24, np.uint8)
    oculto = visible.copy()
    dibujar_esqueleto_3d(visible, _esqueleto(), np.full(N_LANDMARKS, 0.9),
                         conexiones, NOMBRES, ojo, base, 270.0)
    dibujar_esqueleto_3d(oculto, _esqueleto(), np.zeros(N_LANDMARKS),
                         conexiones, NOMBRES, ojo, base, 270.0)
    assert visible.std() > 5
    assert oculto.std() < 1, "dibujó landmarks que nadie ve"


def test_la_rejilla_se_dibuja_a_la_altura_pedida():
    ojo, base = camara_orbital(-70.0, 25.0, 2.4)
    arriba = np.full((300, 300, 3), 24, np.uint8)
    abajo = arriba.copy()
    dibujar_rejilla(arriba, ojo, base, 270.0, altura_m=0.0)
    dibujar_rejilla(abajo, ojo, base, 270.0, altura_m=-0.9)
    assert arriba.std() > 1 and abajo.std() > 1
    assert not np.array_equal(arriba, abajo), "la altura no tuvo efecto"


def test_el_overlay_2d_no_toca_el_frame_original():
    frame = np.full((240, 320, 3), 100, np.uint8)
    copia = frame.copy()
    pix = np.random.default_rng(1).uniform(20, 200, size=(N_LANDMARKS, 2))
    salida = dibujar_esqueleto_2d(frame, pix, np.full(N_LANDMARKS, 0.9),
                                  pares_de_conexiones())
    assert np.array_equal(frame, copia)
    assert not np.array_equal(salida, frame)
