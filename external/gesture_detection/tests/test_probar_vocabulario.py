"""Supervisor simulado del probador de vocabulario. Sin camara.

Verifica la secuencia que el vocabulario tiene que soportar: los dos modos
son excluyentes y el aplauso conmuta, el senalero alterna despegue y
aterrizaje segun el estado, los comportamientos exigen estar en el aire, la
navegacion solo actua en modo estatico, y el paro lo apaga todo y bloquea
hasta que se suelta.

Uso, desde la raiz del repositorio:

    python -m pytest -q external/gesture_detection/tests/test_probar_vocabulario.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
GESTURE_DIR = TESTS_DIR.parent
if str(GESTURE_DIR) not in sys.path:
    sys.path.insert(0, str(GESTURE_DIR))

from contracts import VelocityIntent  # noqa: E402
from probar_vocabulario import DINAMICO, ESTATICO, Simulador  # noqa: E402


def test_arranca_en_dinamico_y_el_aplauso_conmuta():
    s = Simulador()
    assert s.control == DINAMICO
    assert s.gesto("aplaudir") == ("MODO ESTATICO", "")
    assert s.control == ESTATICO
    assert s.gesto("aplaudir") == ("MODO DINAMICO", "")
    assert s.control == DINAMICO


def test_secuencia_dinamica():
    s = Simulador()
    assert s.gesto("ven_aca")[0] == "ignorado"          # en el suelo
    assert s.gesto("senalero") == ("DESPEGAR", "")
    assert s.gesto("ven_aca") == ("SEGUIR", "")
    assert s.gesto("arco") == ("ALEJARSE", "")
    assert s.gesto("circulo") == ("ORBITAR", "")
    assert s.gesto("senalero") == ("ATERRIZAR", "")
    assert s.comportamiento == "hover" and not s.en_aire


def test_dinamicos_ignorados_en_modo_estatico():
    s = Simulador()
    s.gesto("senalero")
    s.gesto("aplaudir")
    for g in ("senalero", "ven_aca", "arco", "circulo"):
        accion, motivo = s.gesto(g)
        assert accion == "ignorado" and "modo estatico" in motivo, g
    assert s.en_aire                                    # cambiar de modo no aterriza


def test_navegacion_solo_en_modo_estatico_y_en_el_aire():
    s = Simulador()
    v = VelocityIntent(vx=1.0)
    assert "modo dinamico" in s.navegar("ADELANTE", v)[1]
    s.gesto("aplaudir")
    assert s.navegar("ADELANTE", v) == ("ignorado", "en el suelo")
    s.gesto("aplaudir"); s.gesto("senalero"); s.gesto("aplaudir")
    assert s.navegar("ADELANTE", v) == ("MANUAL", "")
    assert s.comportamiento == "MANUAL" and s.velocidad == v
    s.soltar_navegacion()
    assert s.comportamiento == "MANUAL" and s.velocidad == VelocityIntent()


def test_cambiar_de_modo_deja_hover():
    s = Simulador()
    s.gesto("senalero"); s.gesto("circulo")
    s.gesto("aplaudir")
    assert s.comportamiento == "hover" and s.en_aire
    s.navegar("ARRIBA", VelocityIntent(vz=1.0))
    s.gesto("aplaudir")
    assert s.comportamiento == "hover" and s.velocidad == VelocityIntent()


def test_estado_estatico_solo_en_modo_estatico():
    s = Simulador()
    assert "modo dinamico" in s.gesto("DESPEGAR")[1]
    s.gesto("aplaudir")
    assert s.gesto("ATERRIZAR") == ("ignorado", "ya en el suelo")
    assert s.gesto("DESPEGAR") == ("DESPEGAR", "")
    assert s.gesto("DESPEGAR") == ("ignorado", "ya en el aire")
    s.navegar("ADELANTE", VelocityIntent(vx=1.0))
    assert s.gesto("STOP") == ("HOVER", "") and s.comportamiento == "hover"
    assert s.gesto("ATERRIZAR") == ("ATERRIZAR", "") and not s.en_aire


def test_paro_apaga_y_vuelve_a_dinamico():
    s = Simulador()
    s.gesto("senalero"); s.gesto("aplaudir")
    s.navegar("ADELANTE", VelocityIntent(vx=1.0))
    assert s.paro().startswith("PARO: aterrizaje")
    assert not s.en_aire and s.control == DINAMICO and s.comportamiento == "hover"
    assert s.gesto("aplaudir") == ("ignorado", "paro activo")
    assert s.navegar("ADELANTE", VelocityIntent(vx=1.0)) == ("ignorado", "paro activo")
    s.soltar_paro()
    assert s.gesto("senalero") == ("DESPEGAR", "")


def test_gesto_desconocido():
    s = Simulador()
    accion, motivo = s.gesto("saludar")
    assert accion == "ignorado" and "sin comando" in motivo


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
