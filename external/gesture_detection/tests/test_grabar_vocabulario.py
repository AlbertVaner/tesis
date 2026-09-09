"""Guion del vocabulario final. Sin camara y sin MediaPipe.

Verifica lo que cuesta descubrir a mitad de una sesion: que cada gesto tenga
sus repeticiones en cada angulo, que la numeracion no se pise, que el paro y
el reposo esten, y que `--solo` y `--sin-negativos` recorten lo que dicen.

Uso, desde la raiz del repositorio:

    python -m pytest -q external/gesture_detection/tests/test_grabar_vocabulario.py
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
GESTURE_DIR = TESTS_DIR.parent
if str(GESTURE_DIR) not in sys.path:
    sys.path.insert(0, str(GESTURE_DIR))

import grabar_vocabulario as gv  # noqa: E402


def test_guion_completo():
    guion = gv.construir_guion()
    cuenta = Counter((g, a) for g, a, _ in guion)
    for angulo, reps in gv.ANGULOS:
        for gesto in gv.GESTOS:
            assert cuenta[(gesto, angulo)] == reps, (gesto, angulo)
        assert cuenta[(gv.PARO, angulo)] == 1
    for angulo, reps in gv.REPOSO:
        assert cuenta[("reposo", angulo)] == reps
    assert cuenta[("otro", 0.0)] == len(gv.OTRO_QUE)
    esperado = (sum(r for _, r in gv.ANGULOS) * len(gv.GESTOS)
                + len(gv.ANGULOS) + sum(r for _, r in gv.REPOSO)
                + len(gv.OTRO_QUE))
    assert len(guion) == esperado


def test_numeracion_por_combinacion():
    guion = gv.construir_guion()
    vistos = set()
    for gesto, angulo, numero in guion:
        assert (gesto, angulo, numero) not in vistos, "numero repetido"
        vistos.add((gesto, angulo, numero))
    numeros = [n for g, a, n in guion if g == "otro"]
    assert numeros == list(range(1, len(gv.OTRO_QUE) + 1))


def test_agrupado_por_angulo():
    """Girarse es lo lento: un angulo no debe volver a aparecer despues."""
    guion = gv.construir_guion(reposo=(), otro=0)
    orden = []
    for _, a, _ in guion:
        if not orden or orden[-1] != a:
            orden.append(a)
    assert len(orden) == len(set(orden))


def test_solo_y_sin_negativos():
    guion = gv.construir_guion(gestos=("senalero", "circulo"), reposo=(),
                               otro=0, con_paro=False)
    assert {g for g, _, _ in guion} == {"senalero", "circulo"}


def test_instrucciones_para_todo():
    for gesto, _, numero in gv.construir_guion():
        texto = gv.instruccion(gesto, numero)
        assert texto and texto != gesto, gesto
    otros = {gv.instruccion("otro", n) for n in range(1, len(gv.OTRO_QUE) + 1)}
    assert len(otros) == len(gv.OTRO_QUE)


def test_duracion_razonable():
    minutos = gv.duracion_estimada_min(gv.construir_guion())
    assert 8 <= minutos <= 25, minutos


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
