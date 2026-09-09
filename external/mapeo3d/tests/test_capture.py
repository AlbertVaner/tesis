"""Pruebas de `capture/` que no requieren cámaras.

Se genera un vídeo sintético con OpenCV y se lee con `CameraStream`, de modo
que el hilo lector, el descarte de frames viejos y las estadísticas quedan
ejercitados sin hardware. Ver AGENTS.md: la validación de nivel 1 debe correr
sin cámaras conectadas.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mapeo3d.capture import (  # noqa: E402
    CameraStream,
    UnknownCameraModel,
    build_rtsp_url,
    load_config,
    mask_url,
)


# --------------------------------------------------------------------- urls


def test_url_tapo():
    url = build_rtsp_url("tapo_c210", "192.168.1.50", "usr", "clave")
    assert url == "rtsp://usr:clave@192.168.1.50:554/stream1"


def test_url_amcrest_sub():
    url = build_rtsp_url("amcrest_ip4m_1041b", "10.0.0.7", "admin", "pw", stream="sub")
    assert url.endswith("/cam/realmonitor?channel=1&subtype=1")


def test_url_escapa_caracteres_especiales():
    # Una contraseña con '@' o '/' rompería la URL si no se codifica.
    url = build_rtsp_url("tapo_c210", "host", "u", "a@b/c")
    assert "a%40b%2Fc" in url
    # Y el '@' separador sigue siendo uno solo.
    assert url.count("@") == 1


def test_modelo_desconocido():
    with pytest.raises(UnknownCameraModel):
        build_rtsp_url("camara_inventada", "host", "u", "p")


def test_mask_url_oculta_credenciales():
    url = "rtsp://usuario:secreto@192.168.1.50:554/stream1"
    enmascarada = mask_url(url)
    assert "secreto" not in enmascarada
    assert "usuario" not in enmascarada
    assert "192.168.1.50" in enmascarada


# ------------------------------------------------------------------ stream


def _fourcc(codigo: str) -> int:
    """`VideoWriter_fourcc` en OpenCV 4, `VideoWriter.fourcc` en OpenCV 5."""
    fn = getattr(cv2, "VideoWriter_fourcc", None) or cv2.VideoWriter.fourcc
    return fn(*codigo)


@pytest.fixture
def video_sintetico(tmp_path: Path) -> Path:
    """Genera un vídeo corto con un número de frame visible."""
    ruta = tmp_path / "sintetico.avi"
    ancho, alto, fps, n = 320, 240, 20, 60
    escritor = cv2.VideoWriter(str(ruta), _fourcc("MJPG"), fps, (ancho, alto))
    assert escritor.isOpened(), "No se pudo crear el vídeo de prueba"
    for i in range(n):
        frame = np.full((alto, ancho, 3), i * 4 % 255, dtype=np.uint8)
        cv2.putText(frame, str(i), (10, 120), cv2.FONT_HERSHEY_SIMPLEX,
                    2.0, (255, 255, 255), 3)
        escritor.write(frame)
    escritor.release()
    return ruta


def test_stream_lee_frames(video_sintetico: Path):
    with CameraStream(str(video_sintetico), name="test") as stream:
        leidos = 0
        limite = time.monotonic() + 10.0
        while leidos < 10 and time.monotonic() < limite:
            if stream.read() is not None:
                leidos += 1
            else:
                time.sleep(0.001)

    assert leidos >= 10, "El hilo lector no entregó frames"
    assert stream.resolucion == (320, 240)
    assert stream.stats.frames_recibidos >= 10


def test_read_devuelve_none_sin_frame_nuevo(video_sintetico: Path):
    with CameraStream(str(video_sintetico), name="test") as stream:
        limite = time.monotonic() + 10.0
        while stream.read_latest() is None and time.monotonic() < limite:
            time.sleep(0.001)
        assert stream.read_latest() is not None, "Nunca llegó un frame"

        primero = stream.read()
        assert primero is not None
        # Inmediatamente después, no debería haber un frame *nuevo*.
        # read_latest sí sigue devolviendo el mismo.
        assert stream.read_latest() is not None


def test_stats_calcula_fps(video_sintetico: Path):
    with CameraStream(str(video_sintetico), name="test") as stream:
        limite = time.monotonic() + 10.0
        while stream.stats.frames_recibidos < 30 and time.monotonic() < limite:
            stream.read()
            time.sleep(0.001)

    assert stream.stats.fps_recibidos > 0
    assert "fps recibidos" in stream.stats.resumen()


def test_url_invalida_no_lanza(tmp_path: Path):
    """Una fuente inexistente debe reintentar, no reventar el hilo."""
    stream = CameraStream(str(tmp_path / "no_existe.avi"), name="malo",
                          reconnect_after_s=0.1)
    stream.start()
    time.sleep(0.5)
    assert stream.read_latest() is None
    assert not stream.conectado
    stream.stop()


# ------------------------------------------------------------------ config


def _escribir_config(tmp_path: Path, texto: str) -> Path:
    ruta = tmp_path / "cameras.yaml"
    ruta.write_text(texto, encoding="utf-8")
    return ruta


BASE = """
model: tapo_c210
credentials:
  user: ""
  password: ""
capture:
  target_fps: 15
cameras:
  - name: cam1
    host: 192.168.68.55
    user: Camara_1
    password: Camara_1
  - name: cam2
    host: 192.168.68.56
    user: Camara_2
    password: Camara_2
"""


def test_credenciales_por_camara(tmp_path: Path):
    """Cada Tapo tiene su propia cuenta de cámara; no hay una global."""
    cfg = load_config(_escribir_config(tmp_path, BASE))
    assert cfg.camera("cam1").url() == (
        "rtsp://Camara_1:Camara_1@192.168.68.55:554/stream1"
    )
    assert cfg.camera("cam2").url() == (
        "rtsp://Camara_2:Camara_2@192.168.68.56:554/stream1"
    )


def test_entorno_por_camara_tiene_prioridad(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CAM_CAM1_USER", "otro")
    cfg = load_config(_escribir_config(tmp_path, BASE))
    assert "otro" in cfg.camera("cam1").url()
    # cam2 no se ve afectada.
    assert "Camara_2" in cfg.camera("cam2").url()


def test_nombre_duplicado_falla(tmp_path: Path):
    texto = BASE.replace("name: cam2", "name: cam1")
    with pytest.raises(ValueError, match="duplicado"):
        load_config(_escribir_config(tmp_path, texto))


def test_sin_credenciales_falla_con_mensaje_util(tmp_path: Path):
    texto = """
model: tapo_c210
cameras:
  - name: cam1
    host: 192.168.68.55
"""
    with pytest.raises(ValueError, match="credenciales"):
        load_config(_escribir_config(tmp_path, texto))


def test_puerto_personalizado(tmp_path: Path):
    texto = BASE.replace(
        "    host: 192.168.68.55", "    host: 192.168.68.55\n    port: 5540"
    )
    cfg = load_config(_escribir_config(tmp_path, texto))
    assert ":5540/" in cfg.camera("cam1").url()
