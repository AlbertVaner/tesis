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
from ptz.cliente import (  # noqa: E402
    CLAVE_FLIP,
    CLAVE_MIRROR,
    CLAVE_ROTACION,
    CamaraPTZ,
    _parsear_respuesta,
)
from ptz.seguidor import Orden  # noqa: E402


def _config_ok() -> dict[str, str]:
    return {
        f"{SUB}.VideoEnable": "true",
        f"{SUB}.Video.resolution": "640x480",
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
        f"{SUB}.Video.resolution": "640x480",
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
    assert "640x480" in texto and "30 fps" in texto and "audio=false" in texto


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


def test_sin_rotar_la_rotacion_no_se_toca():
    assert CLAVE_ROTACION not in Ajustes().deseado()


def test_rotar_270_pide_rotate90_2():
    actual = _config_ok() | {CLAVE_ROTACION: "0", CLAVE_FLIP: "false", CLAVE_MIRROR: "false"}
    assert plan_cambios(actual, Ajustes(rotar=270)) == {CLAVE_ROTACION: 2}
    actual[CLAVE_ROTACION] = "2"
    assert plan_cambios(actual, Ajustes(rotar=270)) == {}


def test_rotar_180_son_los_dos_volteos_y_quita_la_rotacion():
    # De montada de lado (270) a boca abajo.
    actual = _config_ok() | {CLAVE_ROTACION: "2", CLAVE_FLIP: "false", CLAVE_MIRROR: "false"}
    assert plan_cambios(actual, Ajustes(rotar=180)) == {
        CLAVE_ROTACION: 0, CLAVE_FLIP: True, CLAVE_MIRROR: True}


class _CamaraSinRed(CamaraPTZ):
    """Cliente real con la red sustituida: registra lo que se pediria."""

    def __init__(self, rotate90: str, *, flip: bool = False, mirror: bool = False) -> None:
        super().__init__("camara.invalid", "u", "c", log=lambda _m: None)
        self.rotate90 = rotate90
        self.flip, self.mirror = flip, mirror
        self.pedidos: list[dict] = []

    def _pedir_en(self, cgi, params):
        self.pedidos.append(dict(params))
        if params.get("action") == "getConfig":
            return {f"table.{CLAVE_ROTACION}": self.rotate90,
                    f"table.{CLAVE_FLIP}": str(self.flip).lower(),
                    f"table.{CLAVE_MIRROR}": str(self.mirror).lower()}
        return {"OK": ""}

    def codigos_movidos(self) -> list[str]:
        return [p["code"] for p in self.pedidos if p.get("action") == "start"]


@pytest.mark.parametrize("rotate90, esperado", [
    ("0", ["Right", "Left", "Down", "Up"]),
    # Camara montada de lado, imagen enderezada con 270: el eje horizontal del
    # cuadro es el motor de tilt y el vertical el de pan.
    ("2", ["Down", "Up", "Left", "Right"]),
    ("1", ["Up", "Down", "Right", "Left"]),
])
def test_aplicar_cruza_los_ejes_segun_la_rotacion(rotate90, esperado):
    cam = _CamaraSinRed(rotate90)
    for codigo in ("Right", "Left", "Down", "Up"):
        cam.aplicar(Orden(codigo, 1))
    assert cam.codigos_movidos() == esperado


def test_la_rotacion_se_lee_una_sola_vez_y_parar_usa_el_codigo_del_motor():
    cam = _CamaraSinRed("2")
    cam.aplicar(Orden("Right", 1))
    cam.aplicar(Orden("stop"))
    cam.aplicar(Orden("Left", 1))
    lecturas = [p for p in cam.pedidos if p.get("action") == "getConfig"]
    paradas = [p["code"] for p in cam.pedidos if p.get("action") == "stop"]
    assert len(lecturas) == 1
    assert paradas == ["Down"]


def test_mover_no_traduce():
    cam = _CamaraSinRed("2")
    cam.mover("Left", 1)
    assert cam.codigos_movidos() == ["Left"]


def test_boca_abajo_no_se_invierte_nada_porque_ya_lo_hace_el_firmware():
    # Medido el 2026-09-18 con Flip + Mirror: un pulso de Left llevo la vista a
    # la izquierda del cuadro y uno de Up la subio. La primera version invertia
    # los cuatro sentidos por geometria y la camara giraba al reves.
    cam = _CamaraSinRed("0", flip=True, mirror=True)
    for codigo in ("Right", "Left", "Down", "Up"):
        cam.aplicar(Orden(codigo, 1))
    assert cam.codigos_movidos() == ["Right", "Left", "Down", "Up"]


def test_con_flip_up_baja_la_lectura_del_tilt():
    # Medido: con Flip, un pulso de Up llevo el tilt de 2.0 a -6.3.
    assert _CamaraSinRed("0", flip=True, mirror=True).sentido_tilt("Up") == -1
    assert _CamaraSinRed("0", flip=True, mirror=True).sentido_tilt("Down") == 1
    assert _CamaraSinRed("0").sentido_tilt("Up") == 1
    assert _CamaraSinRed("0").sentido_tilt("Left") == 0
