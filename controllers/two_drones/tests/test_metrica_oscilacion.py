"""Metrica de oscilacion. Sin hardware y sin CSV reales.

Se comprueba contra senales sinteticas de frecuencia y amplitud conocidas,
que es la unica forma de saber que el numero significa lo que dice. Sin esto,
comparar dos corridas seria comparar dos numeros mal calculados.

Uso, desde la raiz del repositorio::

    .\\.venv\\Scripts\\python.exe -m pytest -q .\\controllers\\two_drones\\tests\\test_metrica_oscilacion.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from metrica_oscilacion import medir_desde_filas, medir_oscilacion  # noqa: E402


def _seno(frecuencia_hz, amplitud, duracion=10.0, fs=60.0, eje="x"):
    n = int(duracion * fs)
    t = [i / fs for i in range(n)]
    v = [amplitud * math.sin(2 * math.pi * frecuencia_hz * ti) for ti in t]
    ceros = [0.0] * n
    return (t, v, ceros) if eje == "x" else (t, ceros, v)


# ------------------------------------------------------------- frecuencia


@pytest.mark.parametrize("f", [0.25, 0.5, 1.0, 2.0])
def test_recupera_la_frecuencia_de_un_seno(f):
    t, ex, ey = _seno(f, 0.2)
    m = medir_oscilacion(t, ex, ey)
    assert m is not None
    assert m.frecuencia_hz == pytest.approx(f, rel=0.1)


def test_toma_la_frecuencia_del_eje_que_mas_se_mueve():
    """El eje quieto suele ser ruido; el numero tiene que salir del otro."""
    t, _, ey = _seno(0.5, 0.3, eje="y")
    ex = [0.001 * math.sin(2 * math.pi * 7.0 * ti) for ti in t]   # ruido rapido
    m = medir_oscilacion(t, ex, ey)
    assert m.frecuencia_hz == pytest.approx(0.5, rel=0.15)


# --------------------------------------------------------------- amplitud


def test_una_senal_quieta_no_oscila():
    t = [i / 60 for i in range(300)]
    m = medir_oscilacion(t, [0.0] * 300, [0.0] * 300)
    assert m.rms_error_m == pytest.approx(0.0)
    assert m.frecuencia_hz == pytest.approx(0.0)
    assert m.reversiones == 0


def test_un_error_constante_cuenta_como_error_pero_no_como_oscilacion():
    """Estar siempre desviado 10 cm es un problema distinto a oscilar."""
    t = [i / 60 for i in range(300)]
    m = medir_oscilacion(t, [0.10] * 300, [0.0] * 300)
    assert m.rms_error_m == pytest.approx(0.10, rel=1e-6)
    assert m.frecuencia_hz == pytest.approx(0.0)


def test_mas_amplitud_da_mas_rms():
    t, ex, ey = _seno(0.5, 0.10)
    chico = medir_oscilacion(t, ex, ey)
    t, ex, ey = _seno(0.5, 0.30)
    grande = medir_oscilacion(t, ex, ey)
    assert grande.rms_error_m > chico.rms_error_m
    assert grande.frecuencia_hz == pytest.approx(chico.frecuencia_hz, rel=0.1)


def test_el_rms_de_un_seno_es_amplitud_sobre_raiz_de_dos():
    t, ex, ey = _seno(0.5, 0.20, duracion=20.0)
    m = medir_oscilacion(t, ex, ey)
    assert m.rms_error_m == pytest.approx(0.20 / math.sqrt(2), rel=0.05)


# ------------------------------------------------------------ casos borde


def test_sin_muestras_suficientes_devuelve_none():
    assert medir_oscilacion([], [], []) is None
    assert medir_oscilacion([0.0, 1.0], [0.0, 0.0], [0.0, 0.0]) is None


def test_duracion_nula_devuelve_none():
    assert medir_oscilacion([1.0] * 8, [0.0] * 8, [0.0] * 8) is None


# ----------------------------------------------------------- desde filas


def _fila(t, x, y, tx=0.0, ty=0.0, airborne="True"):
    return {"kind": "sample", "t_s": str(t), "airborne": airborne,
            "mocap_x_m": str(x), "mocap_y_m": str(y),
            "target_x_m": str(tx), "target_y_m": str(ty)}


def test_desde_filas_ignora_eventos_y_suelo():
    filas = [{"kind": "event", "t_s": "0", "event": "TAKEOFF"}]
    filas += [_fila(i / 60, 5.0, 5.0, airborne="False") for i in range(60)]
    filas += [_fila(1.0 + i / 60, 0.1 * math.sin(2 * math.pi * 0.5 * i / 60), 0.0)
              for i in range(600)]
    m = medir_desde_filas(filas)
    assert m is not None
    assert m.muestras == 600, "las muestras en suelo no deben entrar"
    assert m.rms_error_m < 0.2, "el 5.0 del suelo habria disparado el rms"


def test_desde_filas_sin_columnas_no_revienta():
    assert medir_desde_filas([{"kind": "sample", "t_s": "0"}]) is None
