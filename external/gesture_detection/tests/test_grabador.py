r"""Grabacion de la interfaz a velocidad real. Sin camara.

Uso, desde la raiz del repositorio::

    .\.venv\Scripts\python.exe -m pytest -q .\external\gesture_detection\tests\test_grabador.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

MODULE_DIR = Path(__file__).resolve().parents[1]
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from visualization.grabador import (  # noqa: E402
    MAX_REPETIDOS, TAMANO_CAMARA, GrabadorMulticamara, GrabadorVideo, cuadros_pendientes, encajar,
)


def test_un_bucle_lento_repite_cuadros_y_uno_rapido_los_descarta():
    assert cuadros_pendientes(0.0, 0.0, 0) == 1              # el primero siempre entra
    assert cuadros_pendientes(0.5, 0.0, 1) == 10             # medio segundo de retraso a 20 fps
    assert cuadros_pendientes(0.51, 0.0, 11) == 0            # va por delante: no se escribe


def test_una_pausa_larga_no_congela_el_bucle_escribiendo():
    assert cuadros_pendientes(60.0, 0.0, 1) == MAX_REPETIDOS


def test_el_video_dura_lo_que_duro_la_sesion(tmp_path):
    ruta = tmp_path / "captures" / "sesion.mp4"
    grabador = GrabadorVideo(ruta)
    t = 0.0
    for i in range(45):                                       # bucle irregular: 22-30 fps y un paron
        frame = np.full((720, 960, 3), (i * 5) % 255, np.uint8)
        grabador.escribir(frame, t)
        t += 1.5 if i == 20 else (0.033 if i % 2 else 0.045)
    grabador.cerrar()
    assert grabador.duracion_s == pytest.approx(t, abs=0.2)
    cap = cv2.VideoCapture(str(ruta))
    assert cap.isOpened() and int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) == grabador.escritos
    ok, leido = cap.read()
    cap.release()
    assert ok and leido.shape == (720, 960, 3)


def test_si_el_lienzo_cambia_de_tamano_no_se_rompe_el_archivo(tmp_path):
    grabador = GrabadorVideo(tmp_path / "v.mp4")
    grabador.escribir(np.zeros((720, 960, 3), np.uint8), 0.0)
    grabador.escribir(np.zeros((720, 1280, 3), np.uint8), 0.1)
    grabador.cerrar()
    assert grabador.escritos >= 2


def test_encajar_no_deforma_y_sin_frame_da_un_cuadro_negro():
    ancho, alto = TAMANO_CAMARA
    assert encajar(None).shape == (alto, ancho, 3)
    panoramico = np.full((720, 1280, 3), 255, np.uint8)       # 16:9 dentro de 4:3: bandas arriba y abajo
    celda = encajar(panoramico)
    assert celda.shape == (alto, ancho, 3)
    assert celda[0, ancho // 2].max() == 0 and celda[alto // 2, ancho // 2].min() == 255


def test_las_camaras_quedan_alineadas_aunque_una_tarde_en_conectar(tmp_path):
    grabador = GrabadorMulticamara(tmp_path, ["cam1", "cam2"], sufijo="_limpio")
    frame = np.zeros((480, 640, 3), np.uint8)
    t = 0.0
    for i in range(30):
        grabador.escribir({"cam1": frame, "cam2": frame if i > 10 else None}, t)
        t += 0.05
    grabador.cerrar()
    escritos = {n: g.escritos for n, g in grabador.grabadores.items()}
    assert escritos["cam1"] == escritos["cam2"] > 0
    assert sorted(r.name for r in grabador.rutas) == ["cam1_limpio.mp4", "cam2_limpio.mp4"]
