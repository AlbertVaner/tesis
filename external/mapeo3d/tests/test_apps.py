"""Pruebas de las apps de `apps/`, sin cámaras y sin pantalla.

Motivo de existir: dos fallos seguidos vivieron en el código de las apps y
ninguna prueba de los módulos los detectó — uno era un `import` que faltaba y
sólo reventaba al arrancar, y el otro un cálculo que sólo se ejecutaba después
de veinte capturas manuales. Las pruebas de biblioteca no cubren eso.

Aquí se ejercita el arranque de cada app y la ruta de captura completa contra
un vídeo sintético, con la GUI neutralizada.
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

APPS = sorted((RAIZ / "apps").glob("*.py"))


# --------------------------------------------------------------- arranque


@pytest.mark.parametrize("app", APPS, ids=lambda p: p.name)
def test_la_app_arranca(app: Path):
    """`--help` ejercita los imports de módulo y `parse_args()`.

    Es la prueba que habría atrapado el `NameError: EXTENT_MINIMO` que sólo
    aparecía al ejecutar.
    """
    r = subprocess.run(
        [sys.executable, str(app), "--help"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    assert r.returncode == 0, f"{app.name} no arranca:\n{r.stderr[-2000:]}"
    assert "usage" in r.stdout.lower() or "uso" in r.stdout.lower()


# ------------------------------------------------------- captura completa


def _placa_tablero(cols: int = 9, rows: int = 6, lado: int = 60) -> np.ndarray:
    tab = np.zeros(((rows + 1) * lado, (cols + 1) * lado), np.uint8)
    for r in range(rows + 1):
        for c in range(cols + 1):
            if (r + c) % 2 == 0:
                tab[r * lado:(r + 1) * lado, c * lado:(c + 1) * lado] = 255
    b = 60
    placa = np.full((tab.shape[0] + 2 * b, tab.shape[1] + 2 * b), 255, np.uint8)
    placa[b:b + tab.shape[0], b:b + tab.shape[1]] = tab
    return placa


def _fourcc(codigo: str) -> int:
    fn = getattr(cv2, "VideoWriter_fourcc", None) or cv2.VideoWriter.fourcc
    return fn(*codigo)


@pytest.fixture(scope="module")
def video_tablero(tmp_path_factory) -> Path:
    """Vídeo con el tablero moviéndose y cambiando de tamaño en el cuadro."""
    W, H = 2304, 1296
    ruta = tmp_path_factory.mktemp("video") / "tablero.avi"
    placa = _placa_tablero()
    ph, pw = placa.shape
    wr = cv2.VideoWriter(str(ruta), _fourcc("MJPG"), 15, (W, H))
    assert wr.isOpened()
    for i in range(90):
        lienzo = np.full((H, W), 190, np.uint8)
        esc = 0.55 + 0.25 * np.sin(i / 9)
        nw = int(W * esc)
        nh = int(nw * ph / pw)
        if nh > H:
            nh = H - 4
            nw = int(nh * pw / ph)
        peq = cv2.resize(placa, (nw, nh), interpolation=cv2.INTER_AREA)
        x = int((W - nw) / 2 + (W - nw) / 2 * 0.8 * np.sin(i / 7))
        y = int((H - nh) / 2 + (H - nh) / 2 * 0.8 * np.cos(i / 11))
        x = max(0, min(W - nw, x))
        y = max(0, min(H - nh, y))
        lienzo[y:y + nh, x:x + nw] = peq
        wr.write(cv2.cvtColor(lienzo, cv2.COLOR_GRAY2BGR))
    wr.release()
    return ruta


@pytest.fixture
def sin_gui(monkeypatch):
    """Neutraliza las llamadas de ventana para poder correr sin pantalla."""
    for nombre in ("namedWindow", "resizeWindow", "imshow", "destroyAllWindows"):
        monkeypatch.setattr(cv2, nombre, lambda *a, **k: None)
    monkeypatch.setattr(cv2, "waitKey", lambda *a, **k: 255)


@pytest.fixture(scope="module")
def app_calibracion():
    spec = importlib.util.spec_from_file_location(
        "app_cal", RAIZ / "apps" / "calibrate_intrinsics.py"
    )
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _args(ruta: Path, **extra) -> argparse.Namespace:
    base = dict(
        camera=None, url=str(ruta), images=None, from_points=None,
        name="sintetica", config=None, cols=9, rows=6, square_mm=25.0,
        target=6, cooldown=0.05, min_extent=0.20, max_movement=0.0,
        display_width=960, detect_width=960, detect_every=1, out=None,
        save_frames=False,
    )
    base.update(extra)
    return argparse.Namespace(**base)


def test_captura_en_vivo_completa(app_calibracion, video_tablero, sin_gui):
    """La ruta de captura entera, con la forma de las esquinas verificada."""
    spec = app_calibracion.ChessboardSpec(9, 6, 25.0)
    puntos, tamano, _frames = app_calibracion.capturar_en_vivo(
        _args(video_tablero), spec
    )

    assert len(puntos) >= 6, "no capturó las vistas pedidas"
    assert tamano == (2304, 1296)
    for p in puntos:
        assert p.shape == (54, 1, 2), "contrato de forma roto"
        assert p.dtype == np.float32


def test_no_captura_si_el_tablero_esta_lejos(
    app_calibracion, video_tablero, sin_gui
):
    """Con un mínimo imposible no debe capturar nada automáticamente.

    Es la salvaguarda que faltaba cuando se calibró con el tablero al 6 % del
    ancho y salieron dos calibraciones inservibles.
    """
    spec = app_calibracion.ChessboardSpec(9, 6, 25.0)
    args = _args(video_tablero, min_extent=0.95, target=3)

    # El vídeo se acaba y el lector deja de entregar frames nuevos; se corta
    # por tiempo desde fuera para que la prueba no dependa de eso.
    import threading

    resultado = {}

    def correr():
        try:
            resultado["v"] = app_calibracion.capturar_en_vivo(args, spec)
        except BaseException as e:  # noqa: BLE001
            resultado["error"] = e

    h = threading.Thread(target=correr, daemon=True)
    h.start()
    h.join(timeout=25)

    # Sin esto la prueba pasaba en verde cuando el hilo reventaba, porque no
    # llegaba a evaluar ninguna aserción. Justo la salvaguarda que documenta.
    if "error" in resultado:
        raise AssertionError(
            f"capturar_en_vivo falló: {resultado['error']!r}"
        ) from resultado["error"]

    if "v" in resultado:
        puntos, _tam, _f = resultado["v"]
        assert not puntos, "capturó pese a estar por debajo del mínimo"


def test_las_capturas_respetan_el_minimo(app_calibracion, video_tablero, sin_gui):
    from mapeo3d.calibration import corner_extent

    spec = app_calibracion.ChessboardSpec(9, 6, 25.0)
    args = _args(video_tablero)
    puntos, tamano, _ = app_calibracion.capturar_en_vivo(args, spec)

    extents = [corner_extent(p, tamano) for p in puntos]
    assert min(extents) >= args.min_extent


# --------------------------------------------------------------- check_pose3d


@pytest.fixture(scope="module")
def app_pose3d():
    spec = importlib.util.spec_from_file_location(
        "app_pose3d", RAIZ / "apps" / "check_pose3d.py"
    )
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _mundo_sintetico():
    """33 landmarks con caderas en el origen, como los devuelve MediaPipe."""
    rng = np.random.default_rng(0)
    return rng.uniform(-0.6, 0.6, size=(33, 3))


def test_la_app_de_pose3d_se_importa_sin_mediapipe(app_pose3d):
    """El módulo tiene que cargar aunque MediaPipe no esté: la importación es
    perezosa y las pruebas no deben depender del backend."""
    assert hasattr(app_pose3d, "main")
    assert app_pose3d.RANGO_M > 0


def test_la_proyeccion_ortografica_centra_el_origen(app_pose3d):
    """Las caderas están en (0,0,0) y tienen que caer en el centro del panel."""
    pts = app_pose3d._proyectar(np.zeros((1, 3)), 0, 1, lado=200)
    assert pts[0] == pytest.approx([100.0, 100.0])


def test_la_escala_de_la_vista_3d_es_fija(app_pose3d):
    """Un punto a RANGO_M del origen cae en el borde, siempre.

    La escala es fija a propósito: una vista que se autoescala hace imposible
    juzgar a ojo si el esqueleto tiembla, que es lo que se viene a mirar.
    """
    lado = 200
    p = np.array([[app_pose3d.RANGO_M, 0.0, 0.0]])
    assert app_pose3d._proyectar(p, 0, 1, lado)[0][0] == pytest.approx(lado)
    # Y el doble de puntos no cambia la escala.
    dos = np.array([[app_pose3d.RANGO_M, 0.0, 0.0], [5.0, 5.0, 5.0]])
    assert app_pose3d._proyectar(dos, 0, 1, lado)[0][0] == pytest.approx(lado)


def test_la_planta_invierte_la_profundidad(app_pose3d):
    """En el plano de planta, arriba tiene que ser LEJOS."""
    lejos = np.array([[0.0, 0.0, 0.5]])
    cerca = np.array([[0.0, 0.0, -0.5]])
    y_lejos = app_pose3d._proyectar(lejos, 0, 2, 200, invertir_v=True)[0][1]
    y_cerca = app_pose3d._proyectar(cerca, 0, 2, 200, invertir_v=True)[0][1]
    assert y_lejos < y_cerca, "lejos tiene que dibujarse más arriba"


def test_los_paneles_3d_salen_del_tamano_pedido(app_pose3d):
    from mapeo3d.pose import pares_de_conexiones

    panel = app_pose3d._panel_3d(
        _mundo_sintetico(), np.full(33, 0.9), pares_de_conexiones(),
        180, "frontal", 0, 1, "x", "y",
    )
    assert panel.shape == (180, 180, 3)
    # Se dibujó algo: el panel no quedó en el gris de fondo.
    assert panel.std() > 5


def test_un_panel_3d_sin_persona_no_revienta(app_pose3d):
    from mapeo3d.pose import pares_de_conexiones

    panel = app_pose3d._panel_3d(
        None, None, pares_de_conexiones(), 180, "frontal", 0, 1, "x", "y"
    )
    assert panel.shape == (180, 180, 3)


def test_el_texto_largo_se_encoge_en_vez_de_recortarse(app_pose3d):
    """Un nombre de hueso largo se salía del panel y se perdía en silencio."""
    largo = "L.shoulder-R.shoulder"
    panel = app_pose3d._panel_texto([(largo, (255, 255, 255), 0.45)], 180)
    assert panel.shape == (180, 180, 3)
    # La última columna tiene que seguir siendo fondo: nada se salió.
    assert panel[:, -3:].std() < 1.0


def test_abreviar_nombres_de_huesos(app_pose3d):
    assert app_pose3d._corto("left_shoulder") == "L.shoulder"
    assert app_pose3d._corto("right_elbow") == "R.elbow"
    assert app_pose3d._corto("nose") == "nose"


def test_el_esqueleto_2d_no_modifica_el_frame_original(app_pose3d):
    from mapeo3d.pose import pares_de_conexiones

    frame = np.full((240, 320, 3), 100, np.uint8)
    copia = frame.copy()
    pix = np.random.default_rng(1).uniform(20, 200, size=(33, 2))
    app_pose3d.dibujar_esqueleto_2d(frame, pix, np.full(33, 0.9),
                                    pares_de_conexiones())
    assert np.array_equal(frame, copia), "dibujó sobre el frame de entrada"


def test_la_estabilidad_necesita_frames_suficientes(app_pose3d):
    from collections import deque

    from mapeo3d.pose import pares_de_huesos

    pares = pares_de_huesos()
    assert app_pose3d.estabilidad(deque([_mundo_sintetico()] * 5), pares) is None
    est = app_pose3d.estabilidad(deque([_mundo_sintetico()] * 40), pares)
    assert est is not None and est.n_frames == 40
