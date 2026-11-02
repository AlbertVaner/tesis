r"""Grabacion del stream principal con ffmpeg. Sin camara ni ffmpeg.

Uso, desde la raiz del repositorio::

    .\.venv\Scripts\python.exe -m pytest -q .\external\gesture_detection\tests\test_grabar_camaras_hd.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

MODULE_DIR = Path(__file__).resolve().parents[1]
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import grabar_camaras_hd as hd  # noqa: E402

URL = "rtsp://admin:secreta@192.168.1.7:554/cam/realmonitor?channel=1&subtype=1"


def test_pide_el_stream_principal_de_la_misma_camara():
    assert hd.stream_principal(URL).endswith("channel=1&subtype=0")
    assert hd.stream_principal("rtsp://h/x?channel=1") == "rtsp://h/x?channel=1&subtype=0"
    assert hd.stream_principal("rtsp://h/x") == "rtsp://h/x?subtype=0"


def test_copia_el_video_sin_recodificar_ni_audio(tmp_path):
    cmd = hd.comando_ffmpeg("ffmpeg", URL, tmp_path / "cam1_hd.mkv")
    assert cmd[cmd.index("-c") + 1] == "copy"
    assert "-an" in cmd and cmd[cmd.index("-rtsp_transport") + 1] == "tcp"
    # La hora de llegada como marca, y conservada: es lo que alinea el render.
    assert cmd.index("-use_wallclock_as_timestamps") < cmd.index("-i") < cmd.index("-copyts")
    assert cmd[-1] == str(tmp_path / "cam1_hd.mkv")


def test_las_camaras_se_graban_en_alta_aunque_el_env_pida_vga(tmp_path):
    grabador = hd.GrabadorRTSP([("cam1", URL)], tmp_path, ffmpeg="ffmpeg")
    assert grabador.camaras[0][1].endswith("subtype=0")
    assert grabador.ruta("cam1") == tmp_path / "cam1_hd.mkv"


def test_sin_ffmpeg_avisa_como_instalarlo(tmp_path, monkeypatch):
    monkeypatch.setattr(hd, "buscar_ffmpeg", lambda: None)
    with pytest.raises(RuntimeError, match="winget"):
        hd.GrabadorRTSP([("cam1", URL)], tmp_path)
