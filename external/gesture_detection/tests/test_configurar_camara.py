"""Plan de cambios de `configurar_camara.py` y apertura del lector RTSP. Sin camara.

Lo que puede fallar en silencio: mandar claves que ya estan bien (reinicia el
encoder sin motivo), comparar booleanos con distinta capitalizacion, o abrir
el `VideoCapture` sin limitar los hilos del decodificador.

Uso, desde la raiz del repositorio::

    .\\.venv\\Scripts\\python.exe -m pytest -q .\\external\\gesture_detection\\tests\\test_configurar_camara.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import pytest

MODULE_DIR = Path(__file__).resolve().parents[1]
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import video_source  # noqa: E402
from configurar_camara import PRINCIPAL, SUB, Ajustes, plan_cambios, resumen_stream  # noqa: E402
from ptz.cliente import _parsear_respuesta  # noqa: E402


def _config_ok() -> dict[str, str]:
    return {
        f"{SUB}.VideoEnable": "true",
        f"{SUB}.Video.resolution": "704x480",
        f"{SUB}.Video.FPS": "30",
        f"{SUB}.Video.GOP": "30",
        f"{SUB}.Video.Compression": "H.264",
        f"{SUB}.Video.BitRateControl": "CBR",
        f"{SUB}.Video.BitRate": "1024",
        f"{SUB}.AudioEnable": "false",
        f"{PRINCIPAL}.AudioEnable": "false",
    }


def test_sin_diferencias_no_hay_cambios():
    assert plan_cambios(_config_ok(), Ajustes()) == {}


def test_solo_se_mandan_las_claves_distintas():
    actual = _config_ok()
    actual[f"{SUB}.Video.resolution"] = "352x240"
    actual[f"{SUB}.AudioEnable"] = "true"
    cambios = plan_cambios(actual, Ajustes())
    assert cambios == {
        f"{SUB}.Video.resolution": "704x480",
        f"{SUB}.AudioEnable": False,
    }


def test_booleanos_se_comparan_sin_capitalizacion():
    actual = _config_ok()
    actual[f"{PRINCIPAL}.AudioEnable"] = "False"
    assert plan_cambios(actual, Ajustes()) == {}


def test_clave_ausente_cuenta_como_cambio():
    actual = _config_ok()
    del actual[f"{SUB}.Video.GOP"]
    assert plan_cambios(actual, Ajustes()) == {f"{SUB}.Video.GOP": 30}


def test_resumen_muestra_lo_esencial():
    texto = resumen_stream(_config_ok(), SUB)
    assert "704x480" in texto and "30 fps" in texto and "audio=false" in texto


@pytest.mark.parametrize("texto, esperado", [
    ("OK\r\n", {"OK": ""}),
    ("Error\n", {"Error": ""}),
    ("table.Encode[0].MainFormat[0].AudioEnable=true\n",
     {"table.Encode[0].MainFormat[0].AudioEnable": "true"}),
])
def test_parsear_respuesta_conserva_ok_y_error(texto, esperado):
    assert _parsear_respuesta(texto) == esperado


def test_el_lector_rtsp_abre_con_un_hilo_de_decodificacion():
    if not hasattr(cv2, "CAP_PROP_N_THREADS"):
        pytest.skip("OpenCV sin CAP_PROP_N_THREADS")
    assert video_source._parametros_apertura() == [cv2.CAP_PROP_N_THREADS, 1]
