"""Maquina de modos del vocabulario. Sin camara, sin dron.

`Simulador` (probado en `test_probar_vocabulario.py`) envuelve esta maquina;
aqui se comprueba lo que el controlador real necesita de ella directamente:
que no lleve la cuenta de `en_aire` por su cuenta, que el senalero decida
segun lo que le digan, y que el paro deje todo listo para arrancar de nuevo.

Uso, desde la raiz del repositorio:

    python -m pytest -q external/gesture_detection/tests/test_vocabulario.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
GESTURE_DIR = TESTS_DIR.parent
if str(GESTURE_DIR) not in sys.path:
    sys.path.insert(0, str(GESTURE_DIR))

from recognition.vocabulario import (  # noqa: E402
    ATERRIZAR,
    DESPEGAR,
    DINAMICO,
    ESTATICO,
    HOVER,
    IGNORADO,
    MANUAL,
    PARO,
    Decision,
    MaquinaDeModos,
)


def test_la_decision_se_desempaqueta_como_tupla():
    accion, motivo = Decision("MODO ESTATICO")
    assert (accion, motivo) == ("MODO ESTATICO", "")
    assert Decision("MODO ESTATICO") == ("MODO ESTATICO", "")
    assert Decision("MODO ESTATICO").ejecutar
    assert not Decision(IGNORADO, "paro activo").ejecutar


def test_el_senalero_decide_con_lo_que_le_dicen_no_con_memoria():
    m = MaquinaDeModos()
    assert m.gesto("senalero", en_aire=False) == (DESPEGAR, "")
    # Si el backend rechazo el despegue, el siguiente senalero vuelve a pedirlo.
    assert m.gesto("senalero", en_aire=False) == (DESPEGAR, "")
    assert m.gesto("senalero", en_aire=True) == (ATERRIZAR, "")


def test_los_comportamientos_exigen_estar_en_el_aire():
    m = MaquinaDeModos()
    assert m.gesto("ven_aca", en_aire=False) == (IGNORADO, "en el suelo (senalero primero)")
    assert m.comportamiento == HOVER
    assert m.gesto("ven_aca", en_aire=True) == ("SEGUIR", "")
    assert m.comportamiento == "SEGUIR"
    assert m.gesto("circulo", en_aire=True) == ("ORBITAR", "")
    assert m.comportamiento == "ORBITAR"


def test_hover_olvida_el_comportamiento():
    m = MaquinaDeModos()
    m.gesto("ven_aca", en_aire=True)
    m.hover()
    assert m.comportamiento == HOVER


def test_navegar_y_soltar():
    m = MaquinaDeModos()
    assert m.navegar("ADELANTE", en_aire=True).motivo.startswith("modo dinamico")
    m.gesto("aplaudir", en_aire=True)
    assert m.control == ESTATICO
    assert m.navegar("ADELANTE", en_aire=False) == (IGNORADO, "en el suelo")
    assert m.navegar("ADELANTE", en_aire=True) == (MANUAL, "")
    assert m.soltar_navegacion()          # habia navegacion manual
    assert not m.soltar_navegacion() or m.comportamiento == MANUAL


def test_el_paro_bloquea_y_al_soltar_arranca_en_dinamico():
    m = MaquinaDeModos()
    m.gesto("senalero", en_aire=False)
    m.gesto("aplaudir", en_aire=True)
    m.navegar("ARRIBA", en_aire=True)
    assert m.paro() == (PARO, "")
    assert m.paro_activo and m.control == DINAMICO and m.comportamiento == HOVER
    assert m.gesto("senalero", en_aire=False) == (IGNORADO, "paro activo")
    assert m.navegar("ARRIBA", en_aire=True) == (IGNORADO, "paro activo")
    m.soltar_paro()
    assert m.gesto("senalero", en_aire=False) == (DESPEGAR, "")


def test_reset_vuelve_al_arranque():
    m = MaquinaDeModos()
    m.gesto("aplaudir", en_aire=False)
    m.paro()
    m.reset()
    assert (m.control, m.comportamiento, m.paro_activo) == (DINAMICO, HOVER, False)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
