"""Encuadre vertical del seguidor PTZ: pecho al centro sin cortar cabeza ni pies.

Sin camara ni MediaPipe: los landmarks se fabrican. Lo que puede fallar en
silencio es el signo de una correccion (bajar la camara cuando hay que
subirla), o que una parte del cuerpo cortada no dispare ningun paso por caer
el pecho dentro de la zona muerta.

Uso, desde la raiz del repositorio::

    .\\.venv\\Scripts\\python.exe -m pytest -q .\\external\\gesture_detection\\tests\\test_ptz_encuadre.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

MODULE_DIR = Path(__file__).resolve().parents[1]
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from ptz import Ajustes, Seguidor, centro_encuadre, centro_torso  # noqa: E402
from ptz.seguidor import ABAJO, ARRIBA, extremos_cuerpo  # noqa: E402


def persona(cabeza: float, pies: float, *, x: float = 0.5, pies_visibles: bool = True):
    """Landmarks de una persona de pie entre `cabeza` (coronilla) y `pies`.

    Proporciones de un adulto: nariz al 7 % de la altura, hombros al 18 %,
    caderas al 50 %. La coronilla que estima `extremos_cuerpo` es
    nariz - 0.6 x (hombros - nariz), que con estas cifras cae en el 0.4 %.
    """
    alto = pies - cabeza
    puntos = np.zeros((33, 3))
    puntos[:, 0] = x
    puntos[:, 1] = cabeza + 0.5 * alto
    vis = np.ones(33)
    puntos[0, 1] = cabeza + 0.07 * alto
    puntos[[11, 12], 1] = cabeza + 0.18 * alto
    puntos[[23, 24], 1] = cabeza + 0.50 * alto
    puntos[[27, 28, 29, 30, 31, 32], 1] = pies
    if not pies_visibles:
        vis[[27, 28, 29, 30, 31, 32]] = 0.1
    return puntos, vis


def error_y(puntos, vis, ajustes: Ajustes) -> float:
    return centro_encuadre(puntos, vis, ajustes)[1] - ajustes.objetivo_y


def pecho_de(cabeza: float, pies: float) -> float:
    alto = pies - cabeza
    return cabeza + (0.18 + 0.25 * (0.50 - 0.18)) * alto


# ----------------------------------------------------------------- modos


def test_torso_es_el_comportamiento_anterior():
    p, v = persona(0.2, 0.8)
    assert centro_encuadre(p, v, Ajustes(encuadre="torso")) == centro_torso(p, v)


def test_pecho_queda_por_encima_del_centro_del_torso():
    p, v = persona(0.2, 0.8)
    y_pecho = centro_encuadre(p, v, Ajustes(encuadre="pecho"))[1]
    assert y_pecho == pytest.approx(pecho_de(0.2, 0.8))
    assert y_pecho < centro_torso(p, v)[1]


def test_la_x_es_siempre_la_del_torso():
    p, v = persona(0.2, 0.8, x=0.7)
    for modo in ("cuerpo", "pecho", "torso"):
        assert centro_encuadre(p, v, Ajustes(encuadre=modo))[0] == pytest.approx(0.7)


def test_sin_persona_no_hay_centro():
    assert centro_encuadre(np.empty((0, 3)), np.empty((0,)), Ajustes()) is None


# ---------------------------------------------------------------- cuerpo


def test_lejos_de_los_bordes_manda_el_pecho():
    # Persona pequena y holgada: los margenes no actuan.
    p, v = persona(0.35, 0.75)
    a = Ajustes()
    assert error_y(p, v, a) == pytest.approx(pecho_de(0.35, 0.75) - 0.5)


def test_pies_cortados_bajan_la_camara_aunque_el_pecho_este_en_la_zona_muerta():
    # Cabe entera (alto 0.70) pero esta baja: los pies pasan del margen inferior.
    p, v = persona(0.29, 0.99)
    a = Ajustes()
    assert abs(pecho_de(0.29, 0.99) - 0.5) < a.arrancar_en_tilt   # el pecho solo no moveria
    e = error_y(p, v, a)
    assert e > a.arrancar_en_tilt
    orden = Seguidor(a).decidir(centro_encuadre(p, v, a), 10.0)
    assert orden is not None and orden.codigo == ABAJO


def test_cabeza_cortada_sube_la_camara():
    p, v = persona(0.02, 0.60)
    a = Ajustes()
    e = error_y(p, v, a)
    assert e < -a.arrancar_en_tilt
    orden = Seguidor(a).decidir(centro_encuadre(p, v, a), 10.0)
    assert orden is not None and orden.codigo == ARRIBA


def test_un_pie_predicho_fuera_del_cuadro_cuenta_aunque_no_se_vea():
    p, v = persona(0.35, 1.05, pies_visibles=False)
    _techo, suelo = extremos_cuerpo(p, v, Ajustes())
    assert suelo == pytest.approx(1.05)
    assert error_y(p, v, Ajustes()) > 0


def test_un_pie_tapado_dentro_del_cuadro_no_dice_nada():
    # Una mesa tapa los pies: poco visibles y predichos dentro del cuadro.
    p, v = persona(0.35, 0.80, pies_visibles=False)
    a = Ajustes()
    assert extremos_cuerpo(p, v, a)[1] is None
    assert error_y(p, v, a) == pytest.approx(pecho_de(0.35, 0.80) - 0.5)


def test_si_no_cabe_manda_la_cabeza():
    # Muy cerca: el cuerpo ocupa mas que el cuadro. Bajar a por los pies
    # sacaria la cabeza, asi que los pies se ignoran.
    p, v = persona(0.12, 1.20, pies_visibles=False)
    a = Ajustes()
    e = error_y(p, v, a)
    techo, _ = extremos_cuerpo(p, v, a)
    assert e <= techo - a.margen_superior + 1e-9
    assert e < a.arrancar_en_tilt            # no hay paso urgente hacia abajo


def test_corregir_el_error_deja_el_cuerpo_dentro_de_los_margenes():
    a = Ajustes()
    for cabeza, pies in [(0.29, 0.99), (0.02, 0.60), (0.20, 0.97), (0.05, 0.80)]:
        p, v = persona(cabeza, pies)
        e = error_y(p, v, a)
        techo, suelo = extremos_cuerpo(p, v, a)
        # Corregir `e` desplaza todo `-e`. Un paso urgente puede pasarse de lo
        # justo, pero nunca hasta sacar la otra punta del cuerpo.
        assert techo - e >= a.margen_superior - 1e-9, (cabeza, pies)
        assert suelo - e <= 1 - a.margen_inferior + a.arrancar_en_tilt * 1.05 + 1e-9


def test_centrada_y_holgada_no_pide_nada():
    a = Ajustes()
    alto = 0.6
    cabeza = 0.5 - (0.18 + 0.25 * 0.32) * alto       # pecho justo en 0.5
    p, v = persona(cabeza, cabeza + alto)
    assert error_y(p, v, a) == pytest.approx(0.0, abs=1e-9)
    assert Seguidor(a).decidir(centro_encuadre(p, v, a), 10.0) is None
