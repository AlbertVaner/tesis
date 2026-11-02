r"""Vista 3D del Robotat del video resumen: series en el tiempo, cuerpo y proyeccion. Sin camara.

Uso, desde la raiz del repositorio::

    .\.venv\Scripts\python.exe -m pytest -q .\external\gesture_detection\tests\test_escena_robotat.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

MODULE_DIR = Path(__file__).resolve().parents[1]
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from visualization import escena_robotat as er  # noqa: E402


def _serie(n=50, dt=0.05):
    t = 1000.0 + np.arange(n) * dt
    xyz = np.column_stack([np.linspace(0, 1, n), np.zeros(n), np.full(n, 1.0)])
    return er.Serie("x", t, xyz)


def test_una_muestra_vieja_no_se_dibuja():
    s = _serie()
    assert s.en(1000.0 - 0.1) is None
    assert s.en(s.t[-1] + er.VALIDA_S - 0.01) is not None
    assert s.en(s.t[-1] + er.VALIDA_S + 0.01) is None


def test_la_estela_son_los_ultimos_segundos():
    s = _serie(n=200)
    estela = s.estela(s.t[-1], 1.0)
    assert len(estela) == pytest.approx(21, abs=1)


def test_el_cuerpo_sigue_a_la_mano_con_retardo():
    t = 1000.0 + np.arange(100) * 0.05
    xyz = np.column_stack([np.where(t < 1001.0, 0.0, 1.0), np.zeros(100), np.full(100, 1.2)])
    cuerpo = er.cuerpo_desde_marker(er.Serie("m", t, xyz))
    x_justo_despues = cuerpo.en(1001.1)[0][0]
    x_al_final = cuerpo.en(t[-1])[0][0]
    assert 0.0 < x_justo_despues < 0.3            # no salta con la mano
    assert x_al_final > 0.9                        # pero acaba debajo de ella
    assert np.all(cuerpo.xyz[:, 2] == 0.0)         # los pies en el suelo


def test_el_centro_del_area_cae_en_el_centro_de_la_imagen():
    vista = er.Vista3D(er.cargar_config(), 480, 320)
    centro = vista.proyectar([vista.centro], 0.0)[0]
    assert centro == pytest.approx([240, 160], abs=1.0)
    img = vista.dibujar(0.0, drones=[("Dron1", (np.array([0.0, 0.0, 1.0]), 30.0), np.zeros((0, 3)))],
                        marker=(np.array([0.5, 0.5, 1.2]), 0.0), cuerpo=(np.array([0.3, 0.3, 0.0]), 0.0))
    assert img.shape == (320, 480, 3) and img.max() > 100


def test_los_drones_se_ensenan_al_despegar_y_al_empezar_a_seguir():
    eventos = [(100.0, "Dron1", "TAKEOFF"), (100.1, "Dron2", "TAKEOFF"),
               (110.0, "Dron1", "SEGUIR"), (111.0, "Dron1", "SEGUIR"), (112.0, "Dron1", "SEGUIR"),
               (120.0, "Dron1", "ORBITA"), (121.0, "Dron1", "ORBITA"),
               (140.0, "Dron1", "SEGUIR")]
    tramos = er.tramos_con_drones(eventos, duracion_s=6.0)
    # El seguir de las 110 s cuenta una vez; el de las 140 s, otra (la racha se corto).
    assert tramos == [(99.7, 106.1), (110.0, 116.0), (120.0, 126.0), (140.0, 146.0)]
