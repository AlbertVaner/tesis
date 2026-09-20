"""`--rtsp env`: URL de la camara desde el entorno o el `.env`. Sin camara.

Lo que puede fallar en silencio: una clave con `@` o `:` que rompe la URL si
no se escapa, un `.env` que pisa al entorno real, o un mensaje de error que
ensena la clave.

Uso, desde la raiz del repositorio::

    .\\.venv\\Scripts\\python.exe -m pytest -q .\\external\\gesture_detection\\tests\\test_camara_env.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pytest

MODULE_DIR = Path(__file__).resolve().parents[1]
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import camara_env  # noqa: E402
from camara_env import leer_env, resolver_rtsp, url_desde_entorno  # noqa: E402

SIN_ARCHIVO = Path("no-existe.env")


def test_una_url_literal_se_deja_como_esta():
    url = "rtsp://u:c@10.0.0.1:554/cam/realmonitor?channel=1&subtype=0"
    assert resolver_rtsp(url) == url


def test_arma_la_url_con_los_valores_por_defecto():
    url = url_desde_entorno({"CAM_HOST": "10.0.0.5", "CAM_PASSWORD": "abc"}, SIN_ARCHIVO)
    assert url == "rtsp://admin:abc@10.0.0.5:554/cam/realmonitor?channel=1&subtype=1"


def test_la_clave_se_escapa():
    url = url_desde_entorno({"CAM_HOST": "h", "CAM_PASSWORD": "a@b:c/d"}, SIN_ARCHIVO)
    assert "admin:a%40b%3Ac%2Fd@h:554" in url


def test_usuario_subtype_y_puerto_se_pueden_cambiar():
    url = url_desde_entorno({"CAM_HOST": "h", "CAM_PASSWORD": "p", "CAM_USER": "op",
                             "CAM_SUBTYPE": "0", "CAM_RTSP_PORT": "8554"}, SIN_ARCHIVO)
    assert url == "rtsp://op:p@h:8554/cam/realmonitor?channel=1&subtype=0"


def test_si_falta_algo_lo_dice_sin_ensenar_valores():
    with pytest.raises(ValueError) as exc:
        url_desde_entorno({"CAM_PASSWORD": "secreta"}, SIN_ARCHIVO)
    assert "CAM_HOST" in str(exc.value)
    assert "secreta" not in str(exc.value)


def test_el_env_se_lee_y_el_entorno_real_manda(tmp_path):
    archivo = tmp_path / ".env"
    archivo.write_text('# camara\nCAM_HOST=10.0.0.9\nCAM_PASSWORD="del archivo"\n\nbasura\n',
                       encoding="utf-8")
    assert leer_env(archivo) == {"CAM_HOST": "10.0.0.9", "CAM_PASSWORD": "del archivo"}
    url = url_desde_entorno({"CAM_HOST": "10.0.0.77"}, archivo)
    assert "@10.0.0.77:" in url and "del%20archivo" in url


def test_argparse_recibe_un_error_legible(monkeypatch, tmp_path):
    monkeypatch.setattr(camara_env, "ARCHIVO_ENV", tmp_path / ".env")
    for clave in ("CAM_HOST", "CAM_PASSWORD"):
        monkeypatch.delenv(clave, raising=False)
    with pytest.raises(argparse.ArgumentTypeError):
        resolver_rtsp("env")
