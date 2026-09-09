r"""Comparacion de trayectorias por DTW y calculo del umbral.

Sin camara y sin MediaPipe. Se comprueba la mecanica que hace util a un
clasificador de secuencias:

* que DTW absorba un cambio de ritmo pero no confunda gestos distintos;
* que la banda impida el alineamiento patologico que hace pasar cualquier cosa;
* que el umbral salga de medir positivos y negativos, no de una opinion.

Uso, desde la raiz del repositorio:

    .\.venv\Scripts\python.exe -m pytest -q .\external\gesture_detection\tests\test_dtw.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

TESTS_DIR = Path(__file__).resolve().parent
GESTURE_DIR = TESTS_DIR.parent
if str(GESTURE_DIR) not in sys.path:
    sys.path.insert(0, str(GESTURE_DIR))

from recognition.dtw import dtw_distancia, umbral_por_separacion  # noqa: E402

MUESTRAS = 45


def trayectoria(fase: float = 0.0, ritmo: float = 1.0, profundidad: float = 0.0,
                duracion_s: float = 3.0) -> np.ndarray:
    """Un movimiento continuo de dos landmarks, como matriz `(MUESTRAS, 6)`."""
    t = np.linspace(0.0, duracion_s, MUESTRAS)
    w = 2 * np.pi * 0.7 * ritmo
    a = np.stack([0.3 * np.sin(w * t + fase),
                  0.2 * np.cos(w * t + fase),
                  np.full(len(t), profundidad)], axis=1)
    return np.concatenate([a, -a], axis=1)


# ------------------------------------------------------------------- DTW


def test_una_trayectoria_consigo_misma_da_cero() -> None:
    v = trayectoria()
    assert dtw_distancia(v, v) < 1e-9, \
        f"distancia consigo misma: {dtw_distancia(v, v):.2e}"


def test_dtw_absorbe_un_cambio_de_ritmo() -> None:
    """La misma persona hace el mismo gesto un 20-30 % mas rapido entre
    repeticiones. Comparar muestra a muestra lo penalizaria como otro gesto."""
    va, vb = trayectoria(ritmo=1.0), trayectoria(ritmo=1.2)
    d_dtw = dtw_distancia(va, vb)
    d_directa = float(np.linalg.norm(va - vb, axis=1).mean())
    assert d_dtw < d_directa, (
        "DTW penaliza el cambio de ritmo menos que la comparacion directa: "
        f"DTW {d_dtw:.3f} vs directa {d_directa:.3f}"
    )


def test_dos_gestos_distintos_quedan_lejos() -> None:
    va, vb = trayectoria(), trayectoria(profundidad=0.8)
    assert dtw_distancia(va, vb) > 0.5, \
        f"dos trayectorias distintas quedan lejos: {dtw_distancia(va, vb):.3f}"


def test_la_banda_impide_el_alineamiento_patologico() -> None:
    """Sin banda, DTW alinea un pulso con cualquier cosa y devuelve una
    distancia pequeña que no significa nada."""
    temprano = np.zeros((MUESTRAS, 6))
    temprano[2:] = 1.0
    tardio = np.zeros((MUESTRAS, 6))
    tardio[MUESTRAS - 2:] = 1.0
    con = dtw_distancia(temprano, tardio, banda=0.25)
    sin = dtw_distancia(temprano, tardio, banda=1.0)
    assert con > sin, (
        "la banda impide alinear cosas separadas en el tiempo: "
        f"banda 0.25 -> {con:.3f}, sin banda -> {sin:.3f}"
    )


def test_dtw_rechaza_formas_incompatibles() -> None:
    with pytest.raises(ValueError):
        dtw_distancia(np.zeros((10, 6)), np.zeros((10, 4)))


def test_una_trayectoria_vacia_da_infinito() -> None:
    assert not np.isfinite(dtw_distancia(np.zeros((0, 6)), trayectoria())), \
        "trayectoria vacia -> inf"


# --------------------------------------------------------------- umbral


def test_el_umbral_sale_de_las_dos_mitades() -> None:
    u, exactitud = umbral_por_separacion([0.1, 0.2, 0.15], [0.8, 0.9, 0.75])
    assert 0.2 < u < 0.75 and exactitud == 1.0, \
        f"umbral entre los dos grupos: u={u:.3f} exactitud={exactitud:.2f}"


def test_sin_negativos_no_hay_umbral() -> None:
    u, exactitud = umbral_por_separacion([0.1, 0.2], [])
    assert not np.isfinite(u) and exactitud == 0.0, \
        f"sin material negativo no se inventa un umbral: u={u}"


def test_grupos_solapados_lo_dicen_en_la_exactitud() -> None:
    u, exactitud = umbral_por_separacion([0.1, 0.9], [0.2, 0.8])
    assert exactitud < 0.8, f"si no separan, la exactitud lo dice: exactitud {exactitud:.2f}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
