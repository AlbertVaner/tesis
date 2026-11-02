r"""Interfaz en HD recompuesta a partir del registro en vivo. Sin camaras.

Las pruebas de punta a punta generan videos con ffmpeg y se saltan si no esta.

Uso, desde la raiz del repositorio::

    .\.venv\Scripts\python.exe -m pytest -q .\external\gesture_detection\tests\test_renderizar_sesion_hd.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

MODULE_DIR = Path(__file__).resolve().parents[1]
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import renderizar_sesion_hd as render  # noqa: E402
from grabar_camaras_hd import buscar_ffmpeg  # noqa: E402
from visualization.registro_render import RegistroRender, leer  # noqa: E402

EPOCA = 1_793_200_000.0
FFMPEG = buscar_ffmpeg()
con_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="sin ffmpeg")


def _landmarks(x: float):
    return [SimpleNamespace(x=x, y=0.5, visibility=0.9) for _ in range(33)]


def _estado(seq: int, t: float, x: float):
    return SimpleNamespace(seq=seq, t_captura=t, senal=True, landmarks=_landmarks(x))


def test_el_registro_se_lee_ordenado_y_sin_repetir_frames(tmp_path):
    reg = RegistroRender(tmp_path, ["cam1"], [(11, 13), (13, 15)])
    reg.anotar_poses({"cam1": _estado(1, EPOCA + 0.1, 0.3)})
    reg.anotar_poses({"cam1": _estado(1, EPOCA + 0.1, 0.3)})      # mismo frame: no se repite
    reg.anotar_poses({"cam1": _estado(2, EPOCA + 0.2, 0.4)})
    reg.anotar_estado(EPOCA + 0.2, activa="cam1", gesto="ARRIBA", confirmado=True)
    reg.anotar_evento(EPOCA + 0.15, "senalero -> DESPEGAR", True)
    reg.cerrar()
    with (tmp_path / "render.jsonl").open("a", encoding="utf-8") as f:
        f.write('{"tipo":"pose","cam":"cam1"')                     # proceso muerto a medias
    inicio, poses, estados, eventos = leer(tmp_path / "render.jsonl")
    assert inicio["conexiones"] == [[11, 13], [13, 15]]
    assert [p["t"] for p in poses["cam1"]] == [EPOCA + 0.1, EPOCA + 0.2]
    assert estados[0]["gesto"] == "ARRIBA" and eventos[0]["ejecutado"] is True


def test_la_correlacion_encuentra_el_retraso_del_hd():
    t = np.arange(0, 30, 0.04)
    rng = np.random.default_rng(1)
    movimiento = np.convolve(rng.random(len(t)), np.ones(8) / 8, mode="same")
    # La imagen HD muestra a las t+0.35 lo que la pose vio a las t.
    desfase, c = render.correlacionar(t + 0.35, movimiento, t, movimiento)
    assert desfase == pytest.approx(0.35, abs=0.05) and c > 0.9


def test_una_pose_vieja_no_se_dibuja():
    escena = render.Escena({"camaras": ["cam1"]}, {"cam1": [{"t": 10.0, "lm": [[0.5, 0.5, 1]]}]}, [], [])
    assert escena.pose("cam1", 10.2) is not None
    assert escena.pose("cam1", 10.0 + render.POSE_VALIDA_S + 0.1) is None
    assert escena.pose("cam1", 9.9) is None


def _video_con_hora(ruta: Path, inicio: float, segundos: float = 3.0) -> None:
    """Un MKV como el de `grabar_camaras_hd.py`: marcas de tiempo en la hora de pared."""
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", f"testsrc2=size=1280x720:rate=20:duration={segundos}",
                    "-c:v", "libx264", "-bf", "0", "-output_ts_offset", f"{inicio}",
                    str(ruta)], check=True)


@con_ffmpeg
def test_de_punta_a_punta_sale_la_interfaz_en_1080p(tmp_path, monkeypatch):
    for n in ("cam1", "cam2"):
        _video_con_hora(tmp_path / f"{n}_hd.mkv", EPOCA)
    reg = RegistroRender(tmp_path, ["cam1", "cam2"], [(11, 13)])
    for i in range(50):
        t = EPOCA + 0.2 + i * 0.05
        reg.anotar_poses({"cam1": _estado(i, t, 0.3 + i * 0.005), "cam2": _estado(i, t, 0.6)})
        reg.anotar_estado(t, activa="cam1" if i < 25 else "cam2", gesto="ARRIBA",
                          confirmado=i > 10, estado="VOLANDO", modo="estatico")
    reg.anotar_evento(EPOCA + 1.0, "aplaudir -> MODO ESTATICO", True)
    reg.cerrar()

    monkeypatch.setattr(sys, "argv", ["x", str(tmp_path), "--desfase", "0", "--fps", "10",
                                      "--por-camara"])
    assert render.main() == 0

    cap = cv2.VideoCapture(str(tmp_path / "sesion_hd.mp4"))
    cuadros = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    ok, frame = cap.read()
    cap.release()
    assert ok and frame.shape == (1080, 1920, 3)
    assert cuadros == pytest.approx(int(2.45 * 10), abs=1)
    for nombre in ("cam1_hd_esqueleto.mp4", "cam2_hd_esqueleto.mp4", "cam1_hd.mp4", "cam2_hd.mp4"):
        assert (tmp_path / nombre).stat().st_size > 0


@con_ffmpeg
def test_las_marcas_del_mkv_son_la_hora_de_pared(tmp_path):
    _video_con_hora(tmp_path / "cam1_hd.mkv", EPOCA, segundos=1.0)
    marcas = render.marcas_de_tiempo(render._ffprobe(FFMPEG), tmp_path / "cam1_hd.mkv")
    assert len(marcas) == 20 and marcas[0] == pytest.approx(EPOCA, abs=0.01)
    fuente = render.FuenteHD(tmp_path / "cam1_hd.mkv", marcas)
    assert fuente.en(EPOCA - 1) is None
    assert fuente.en(EPOCA + 0.52) is not None and fuente.indice == 10
    fuente.cerrar()


def test_el_primer_keyframe_con_marca_cero_toma_la_hora_del_siguiente():
    marcas = render.reparar_marcas(np.array([0.0, EPOCA + 0.04, EPOCA + 0.08]))
    assert list(marcas) == [EPOCA + 0.04, EPOCA + 0.04, EPOCA + 0.08]
