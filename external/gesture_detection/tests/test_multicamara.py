"""Multicamara: puntaje de rostro, eleccion de camara y comandos. Sin camara.

Lo que puede fallar en silencio: una camara que ve la nuca y gana porque
MediaPipe inventa una cara, un selector que parpadea entre dos camaras
parecidas o que cambia a mitad de un gesto, y un DESPEGAR que se ejecuta dos
veces porque dos camaras lo vieron.

Uso, desde la raiz del repositorio::

    .\\.venv\\Scripts\\python.exe -m pytest -q .\\external\\gesture_detection\\tests\\test_multicamara.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

MODULE_DIR = Path(__file__).resolve().parents[1]
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from camara_env import camaras_desde_entorno  # noqa: E402
from contracts import Gesture, GestureEvent, VelocityIntent  # noqa: E402
from multicamara.rostro import caja_rostro, puntaje_rostro  # noqa: E402
from multicamara.selector import SelectorCamara  # noqa: E402
from multicamara.sistema import Enclavamiento, rejilla  # noqa: E402
from probar_multicamara import Comandos  # noqa: E402

SIN_ARCHIVO = Path("no-existe.env")


# ------------------------------------------------------------------ rostro


def _cara(nariz_x: float, oreja_izq_x: float = 0.55, oreja_der_x: float = 0.45,
          vis: float = 0.95):
    """33 landmarks con solo la cara colocada; el resto invisible."""
    lm = [SimpleNamespace(x=0.5, y=0.5, visibility=0.0) for _ in range(33)]
    lm[0] = SimpleNamespace(x=nariz_x, y=0.3, visibility=vis)
    lm[2] = SimpleNamespace(x=nariz_x + 0.02, y=0.28, visibility=vis)
    lm[5] = SimpleNamespace(x=nariz_x - 0.02, y=0.28, visibility=vis)
    lm[7] = SimpleNamespace(x=oreja_izq_x, y=0.3, visibility=vis)
    lm[8] = SimpleNamespace(x=oreja_der_x, y=0.3, visibility=vis)
    return lm


def test_de_frente_puntua_alto():
    r = puntaje_rostro(_cara(0.50), 640, 480)
    assert r.frontal == pytest.approx(1.0)
    assert r.puntaje > 0.8


def test_de_lado_puntua_menos_que_de_frente():
    frente = puntaje_rostro(_cara(0.50), 640, 480).puntaje
    tres_cuartos = puntaje_rostro(_cara(0.53), 640, 480).puntaje
    perfil = puntaje_rostro(_cara(0.56), 640, 480).puntaje
    assert frente > tres_cuartos > perfil
    assert perfil == 0.0


def test_de_espaldas_no_hay_rostro():
    # Las orejas cruzadas: la izquierda de la persona a la izquierda de la imagen.
    assert puntaje_rostro(_cara(0.50, 0.45, 0.55), 640, 480).puntaje == 0.0


def test_sin_persona_no_hay_rostro():
    assert puntaje_rostro(None, 640, 480).puntaje == 0.0


def test_mas_cerca_desempata_pero_no_manda():
    lejos = puntaje_rostro(_cara(0.50, 0.51, 0.49), 640, 480)
    cerca = puntaje_rostro(_cara(0.50, 0.56, 0.44), 640, 480)
    assert cerca.puntaje > lejos.puntaje
    # Una cara lejana de frente gana a una cercana de tres cuartos.
    cerca_girada = puntaje_rostro(_cara(0.535, 0.56, 0.44), 640, 480)
    assert lejos.puntaje > cerca_girada.puntaje


def test_caja_del_rostro_rodea_la_nariz_y_no_existe_de_espaldas():
    x0, y0, x1, y1 = caja_rostro(_cara(0.50), 640, 480)
    assert x0 < 320 < x1 and y0 < 0.3 * 480 < y1
    assert caja_rostro(_cara(0.50, 0.45, 0.55), 640, 480) is None
    assert caja_rostro(None, 640, 480) is None


# ---------------------------------------------------------------- selector


def test_elige_la_primera_camara_que_ve_la_cara():
    s = SelectorCamara()
    assert s.actualizar({"cam1": 0.1, "cam2": 0.1}, ahora=0.0) is None
    assert s.actualizar({"cam1": 0.1, "cam2": 0.7}, ahora=0.1) == "cam2"


def test_no_cambia_por_poco():
    s = SelectorCamara()
    s.actualizar({"cam1": 0.7, "cam2": 0.6}, ahora=0.0)
    for i in range(1, 50):
        assert s.actualizar({"cam1": 0.7, "cam2": 0.8}, ahora=i * 0.1) == "cam1"


def test_cambia_si_la_otra_gana_claro_y_sostenido():
    s = SelectorCamara(sostener_s=0.6)
    s.actualizar({"cam1": 0.7, "cam2": 0.3}, ahora=0.0)
    assert s.actualizar({"cam1": 0.4, "cam2": 0.9}, ahora=1.0) == "cam1"
    assert s.actualizar({"cam1": 0.4, "cam2": 0.9}, ahora=1.5) == "cam1"
    assert s.actualizar({"cam1": 0.4, "cam2": 0.9}, ahora=1.7) == "cam2"


def test_un_bache_reinicia_la_espera():
    s = SelectorCamara(sostener_s=0.6)
    s.actualizar({"cam1": 0.7, "cam2": 0.3}, ahora=0.0)
    s.actualizar({"cam1": 0.4, "cam2": 0.9}, ahora=1.0)
    s.actualizar({"cam1": 0.4, "cam2": 0.45}, ahora=1.4)
    assert s.actualizar({"cam1": 0.4, "cam2": 0.9}, ahora=1.7) == "cam1"


def test_no_cambia_a_mitad_de_un_gesto():
    s = SelectorCamara(sostener_s=0.6)
    s.actualizar({"cam1": 0.7, "cam2": 0.3}, ahora=0.0)
    for i in range(20):
        assert s.actualizar({"cam1": 0.4, "cam2": 0.9}, en_gesto=True,
                            ahora=1.0 + i * 0.1) == "cam1"


def test_si_la_activa_pierde_la_cara_cambia_aunque_haya_gesto():
    s = SelectorCamara(perdida_s=1.0)
    s.actualizar({"cam1": 0.7, "cam2": 0.3}, ahora=0.0)
    assert s.actualizar({"cam1": 0.0, "cam2": 0.5}, en_gesto=True, ahora=1.0) == "cam1"
    assert s.actualizar({"cam1": 0.0, "cam2": 0.5}, en_gesto=True, ahora=2.1) == "cam2"


def test_camara_fija_manda_hasta_volver_a_automatico():
    s = SelectorCamara(sostener_s=0.0)
    s.actualizar({"cam1": 0.9, "cam2": 0.1}, ahora=0.0)
    s.fijar("cam2")
    assert s.actualizar({"cam1": 0.9, "cam2": 0.1}, ahora=5.0) == "cam2"
    s.fijar(None)
    # cam2 no ve la cara: se suelta por la regla de perdida, no al instante.
    assert s.actualizar({"cam1": 0.9, "cam2": 0.1}, ahora=6.0) == "cam2"
    assert s.actualizar({"cam1": 0.9, "cam2": 0.1}, ahora=7.1) == "cam1"


# ---------------------------------------------------------------- comandos


def _evento(gesto: Gesture, confirmado: bool) -> GestureEvent:
    return GestureEvent(gesto, 1.0, confirmado, True, VelocityIntent(), 0.0)


def test_un_gesto_sostenido_es_un_solo_comando():
    c = Comandos()
    c.actualizar(0.0, "cam1", _evento(Gesture.NO_GESTURE, False))
    emitidos = [c.actualizar(t, "cam1", _evento(Gesture.DESPEGAR, True)) for t in (1, 2, 3)]
    assert emitidos == [Gesture.DESPEGAR, None, None]


def test_cambiar_de_camara_no_repite_el_gesto_en_curso():
    c = Comandos()
    c.actualizar(0.0, "cam1", _evento(Gesture.NO_GESTURE, False))
    assert c.actualizar(1.0, "cam1", _evento(Gesture.DESPEGAR, True)) is Gesture.DESPEGAR
    assert c.actualizar(2.0, "cam2", _evento(Gesture.DESPEGAR, True)) is None
    assert c.actualizar(3.0, "cam2", _evento(Gesture.DESPEGAR, True)) is None
    c.actualizar(4.0, "cam2", _evento(Gesture.NO_GESTURE, False))
    assert c.actualizar(5.0, "cam2", _evento(Gesture.DESPEGAR, True)) is Gesture.DESPEGAR


# ----------------------------------------------------------- enclavamiento


def test_al_cambiar_de_camara_no_se_ejecuta_lo_ya_confirmado():
    e = Enclavamiento()
    assert e.filtrar("cam1", _evento(Gesture.NO_GESTURE, False)).confirmed is False
    assert e.filtrar("cam1", _evento(Gesture.ARRIBA, True)).confirmed is True
    # cam2 toma el mando con ARRIBA ya confirmado: no se ejecuta...
    assert e.filtrar("cam2", _evento(Gesture.ARRIBA, True)).confirmed is False
    assert e.filtrar("cam2", _evento(Gesture.ARRIBA, True)).confirmed is False
    # ...hasta pasar por NO_GESTURE.
    e.filtrar("cam2", _evento(Gesture.NO_GESTURE, False))
    assert e.filtrar("cam2", _evento(Gesture.ARRIBA, True)).confirmed is True


def test_el_enclavamiento_conserva_el_gesto_crudo_para_el_stop():
    e = Enclavamiento()
    filtrado = e.filtrar("cam1", _evento(Gesture.STOP, True))
    assert filtrado.gesture is Gesture.STOP and filtrado.confirmed is False


def test_al_arrancar_con_un_gesto_sostenido_tampoco_se_ejecuta():
    e = Enclavamiento()
    assert e.filtrar("cam1", _evento(Gesture.DESPEGAR, True)).confirmed is False


# ----------------------------------------------------------------- entorno


def test_lee_todas_las_camaras_del_entorno_con_credenciales_comunes():
    camaras = camaras_desde_entorno(
        {"CAM_HOST": "10.0.0.1", "CAM2_HOST": "10.0.0.2", "CAM4_HOST": "10.0.0.4",
         "CAM_PASSWORD": "abc"}, SIN_ARCHIVO)
    assert [n for n, _ in camaras] == ["cam1", "cam2", "cam4"]
    assert camaras[1][1] == "rtsp://admin:abc@10.0.0.2:554/cam/realmonitor?channel=1&subtype=1"


def test_cada_camara_puede_tener_su_clave():
    camaras = camaras_desde_entorno(
        {"CAM_HOST": "h1", "CAM2_HOST": "h2", "CAM_PASSWORD": "a", "CAM2_PASSWORD": "b"},
        SIN_ARCHIVO)
    assert ":a@h1:" in camaras[0][1] and ":b@h2:" in camaras[1][1]


def test_sin_camaras_avisa_sin_mostrar_claves():
    with pytest.raises(ValueError) as exc:
        camaras_desde_entorno({"CAM_PASSWORD": "secreta"}, SIN_ARCHIVO)
    assert "CAM_HOST" in str(exc.value) and "secreta" not in str(exc.value)


# ------------------------------------------------------------------ dibujo


@pytest.mark.parametrize("n, esperado", [(1, (1, 1)), (2, (1, 2)), (6, (2, 3))])
def test_rejilla_de_miniaturas(n, esperado):
    assert rejilla(n, 440, 520) == esperado


# ------------------------------------------------------ gesto externo y PTZ


def test_un_gesto_externo_congela_solo_la_camara_activa_y_la_eleccion():
    from multicamara.sistema import SistemaMulticamara
    s = SistemaMulticamara([("cam1", 0), ("cam2", 1)], ptz=False)
    s.activa = "cam1"
    s.gesto_en_curso(True)
    assert s.camaras[0].gesto_externo.is_set() and not s.camaras[1].gesto_externo.is_set()
    # Con el gesto en curso la activa no cambia por preferencia.
    s.selector.activa = "cam1"
    for i in range(20):
        assert s.selector.actualizar({"cam1": 0.5, "cam2": 0.95}, en_gesto=s._gesto_externo,
                                     ahora=i * 0.1) == "cam1"
    s.gesto_en_curso(False)
    assert not any(c.gesto_externo.is_set() for c in s.camaras)
