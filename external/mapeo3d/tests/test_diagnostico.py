"""Medidas de diagnóstico de cámara: jitter, encuadre y latencia.

Todo con datos sintéticos. Las tres medidas deciden dónde se montan las
cámaras, que es la decisión más difícil de deshacer del proyecto, así que
conviene que la aritmética esté probada antes de tomarla.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from mapeo3d.capture import Latencia, brillo, detectar_flanco  # noqa: E402
from mapeo3d.pose import (  # noqa: E402
    CLAVE,
    INDICE,
    N_LANDMARKS,
    evaluar_encuadre,
    jitter_en_reposo,
)


# ------------------------------------------------------------------ jitter


def _quieto(t=200, ruido_px=1.5, semilla=0):
    """Sujeto inmóvil: todo lo que se mueva es error del estimador."""
    rng = np.random.default_rng(semilla)
    base = rng.uniform(200, 900, size=(N_LANDMARKS, 2))
    return base + rng.normal(0.0, ruido_px, size=(t, N_LANDMARKS, 2))


def test_el_jitter_recupera_el_ruido_inyectado():
    """Con ruido isótropo de sigma por eje, el radio tiene sigma ~= sigma."""
    j = jitter_en_reposo(_quieto(ruido_px=2.0), distancia_m=3.0)
    # El radio de un gaussiano 2D no tiene la misma sigma que cada eje, pero sí
    # queda en el mismo orden; lo que importa es que sea proporcional.
    assert 0.8 < j.mediana_clave_px < 3.0
    j2 = jitter_en_reposo(_quieto(ruido_px=4.0, semilla=1))
    assert j2.mediana_clave_px > 1.7 * j.mediana_clave_px


def test_el_jitter_no_confunde_movimiento_con_ruido():
    """Una deriva lenta no es ruido, pero sí la ve: por eso el sujeto va QUIETO."""
    s = _quieto(ruido_px=0.5)
    s[:, :, 0] += np.linspace(0, 100, len(s))[:, None]
    j = jitter_en_reposo(s)
    assert j.mediana_clave_px > 10, "una deriva de 100 px debería notarse"


def test_los_landmarks_poco_visibles_no_cuentan():
    s = _quieto(ruido_px=1.0)
    vis = np.full((len(s), N_LANDMARKS), 0.9)
    i = INDICE["left_wrist"]
    vis[:, i] = 0.1
    s[:, i, :] += np.random.default_rng(3).normal(0, 60, size=(len(s), 2))

    j = jitter_en_reposo(s, vis, min_visibilidad=0.5)
    assert j.n[i] == 0
    assert np.isnan(j.desviacion_px[i])
    # Y el resumen global no se contamina con ese landmark.
    assert j.mediana_clave_px < 3.0


def test_el_jitter_en_milimetros_escala_con_la_distancia():
    """Un píxel abarca más milímetros cuanto más lejos está el sujeto."""
    j = jitter_en_reposo(_quieto(ruido_px=2.0), distancia_m=3.0)
    mm3 = j.milimetros(fx_px=950.0)
    mm6 = j.milimetros(fx_px=950.0, distancia_m=6.0)
    assert mm6 == pytest.approx(2 * mm3, rel=1e-6)
    assert np.isnan(j.milimetros(fx_px=0.0))


def test_el_jitter_rechaza_formas_incoherentes():
    with pytest.raises(ValueError):
        jitter_en_reposo(np.zeros((10, 33)))


def test_los_landmarks_clave_son_reales():
    assert all(n in INDICE for n in CLAVE)


# ---------------------------------------------------------------- encuadre


def _dentro(t=100, margen=0.15):
    rng = np.random.default_rng(5)
    return rng.uniform(margen, 1.0 - margen, size=(t, N_LANDMARKS, 2))


def test_un_cuerpo_entero_dentro_del_cuadro_pasa():
    e = evaluar_encuadre(_dentro())
    assert e.cabe
    assert e.fraccion_completa == 1.0
    assert not e.landmarks_problematicos


def test_un_tobillo_fuera_del_cuadro_se_detecta():
    """Es el caso real: la persona cabe «casi» y MediaPipe inventa los pies."""
    s = _dentro()
    s[:, INDICE["left_ankle"], 1] = 0.995      # por debajo del borde inferior
    e = evaluar_encuadre(s)
    assert not e.cabe
    assert "left_ankle" in e.landmarks_problematicos


def test_el_encuadre_distingue_frames_buenos_de_malos():
    s = _dentro(t=100)
    s[:30, INDICE["right_wrist"], 0] = 0.999
    e = evaluar_encuadre(s)
    assert e.fraccion_completa == pytest.approx(0.70, abs=0.01)
    assert e.n_frames == 100


def test_detecta_los_brazos_en_alto():
    """Las muñecas por encima de los hombros: y menor en coordenadas de imagen."""
    s = _dentro()
    s[:, INDICE["left_shoulder"], 1] = 0.5
    s[:, INDICE["right_shoulder"], 1] = 0.5
    s[:, INDICE["left_wrist"], 1] = 0.2
    s[:, INDICE["right_wrist"], 1] = 0.2
    e = evaluar_encuadre(s)
    assert e.fraccion_con_brazos > 0.9


def test_el_encuadre_rechaza_formas_incoherentes():
    with pytest.raises(ValueError):
        evaluar_encuadre(np.zeros((10, 33)))


# ---------------------------------------------------------------- latencia


def _serie(latencia_s, fps=30.0, n=40, base=20.0, salto=180.0, ruido=1.0,
           semilla=0):
    """Frames a `fps` con un escalón de brillo `latencia_s` tras el destello."""
    rng = np.random.default_rng(semilla)
    t = np.arange(n) / fps
    t_destello = t[n // 2] - 0.001
    b = np.full(n, base) + rng.normal(0, ruido, n)
    b[t >= t_destello + latencia_s] += salto
    return t, b, t_destello


def test_la_latencia_se_recupera_dentro_de_un_frame():
    t, b, t0 = _serie(latencia_s=0.080)
    lat = detectar_flanco(t, b, t0)
    assert lat is not None
    # El primer frame iluminado no cae exactamente en la latencia real: se
    # recupera con la resolución del frame rate, que es lo máximo posible.
    assert 0.080 <= lat <= 0.080 + 1 / 30.0 + 1e-9


def test_sin_destello_no_inventa_una_medida():
    """Devolver None es parte del contrato: una medida dudosa contamina."""
    t, b, t0 = _serie(latencia_s=0.0, salto=0.0)
    assert detectar_flanco(t, b, t0) is None


def test_un_frame_brillante_suelto_no_cuenta_como_destello():
    """Artefacto de compresión: brilla un frame y vuelve al reposo."""
    t, b, t0 = _serie(latencia_s=0.200, salto=180.0)
    i = np.flatnonzero(t >= t0)[1]
    b[i] += 200.0                              # pico aislado antes del destello
    lat = detectar_flanco(t, b, t0)
    assert lat is not None and lat > 0.15, "picó con el artefacto"


def test_con_poca_historia_previa_no_mide():
    t = np.array([0.0, 0.01, 0.5, 0.51])
    b = np.array([20.0, 20.0, 200.0, 200.0])
    assert detectar_flanco(t, b, 0.02) is None


def test_un_sensor_sin_ruido_no_dispara_con_cualquier_cosa():
    """Con sigma cero el umbral sería el propio reposo; hay suelo de ruido."""
    t = np.linspace(0, 1, 40)
    b = np.full(40, 20.0)
    b[25:] += 0.4                              # variación mínima, no un destello
    assert detectar_flanco(t, b, t[20]) is None


def test_el_resumen_de_latencia_agrega_bien():
    lat = Latencia(muestras_s=[0.10, 0.12, 0.11, 0.30], intentos=6)
    assert lat.n == 4
    assert lat.mediana_ms == pytest.approx(115.0)
    assert lat.min_ms == pytest.approx(100.0)
    assert "4/6" in lat.resumen()


def test_una_campana_sin_medidas_lo_dice():
    lat = Latencia(intentos=10)
    assert lat.n == 0
    assert np.isnan(lat.mediana_ms)
    assert "sin medidas" in lat.resumen()


def test_el_brillo_promedia_y_acepta_gris_y_color():
    color = np.full((100, 100, 3), 128, np.uint8)
    gris = np.full((100, 100), 128, np.uint8)
    assert brillo(color) == pytest.approx(128.0)
    assert brillo(gris) == pytest.approx(128.0)
