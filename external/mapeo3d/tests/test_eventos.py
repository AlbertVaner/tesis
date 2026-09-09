"""Detección de episodios: la propiedad que importa es la independencia del
frame rate.

Todo lo demás del módulo existe para conseguir eso. Si el mismo movimiento
grabado a 30 y a 15 fps no da el mismo número de episodios, el detector no
sirve para lo que se construyó.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from mapeo3d.pose import (  # noqa: E402
    N_LANDMARKS,
    detectar_episodios,
    distancia,
    rapidez,
    umbral_por_percentil,
)


def palmadas(n=4, fps=30.0, duracion_s=10.0, ancho_s=0.45, semilla=0):
    """Señal de distancia entre muñecas con `n` acercamientos."""
    rng = np.random.default_rng(semilla)
    t = np.arange(0, duracion_s, 1.0 / fps)
    s = np.full(len(t), 0.9)
    for k in range(n):
        centro = duracion_s * (k + 0.5) / n
        s = np.minimum(s, 0.9 - 0.8 * np.exp(-((t - centro) / (ancho_s / 2.5)) ** 2))
    return t, s + rng.normal(0, 0.01, len(t))


# ------------------------------------------------- la propiedad que importa


@pytest.mark.parametrize("fps_alto,fps_bajo", [(30.0, 15.0), (60.0, 20.0)])
def test_el_conteo_no_depende_del_frame_rate(fps_alto, fps_bajo):
    """Es la razón de ser del módulo: 15 fps perdía el 42 % de los eventos
    buscando el instante del contacto; buscando el episodio no pierde nada."""
    t_a, s_a = palmadas(n=5, fps=fps_alto)
    t_b, s_b = palmadas(n=5, fps=fps_bajo)
    u = 0.35
    assert len(detectar_episodios(s_a, t_a, umbral=u)) == 5
    assert len(detectar_episodios(s_b, t_b, umbral=u)) == 5


def test_decimar_la_senal_no_cambia_el_conteo():
    """Mismo material, la mitad de los frames: mismo resultado."""
    t, s = palmadas(n=6, fps=30.0)
    completo = detectar_episodios(s, t, umbral=0.35)
    for fase in (0, 1):
        mitad = detectar_episodios(s[fase::2], t[fase::2], umbral=0.35)
        assert len(mitad) == len(completo) == 6


def test_contar_instantes_sobrecuenta_un_solo_evento():
    """El fallo real del método ingenuo, medido sobre la grabación: buscar
    mínimos locales dio 48 detecciones donde hubo 11 acercamientos.

    Con la señal temblando, un único evento sostenido produce varios mínimos
    locales. El detector de episodios cuenta uno."""
    fps = 30.0
    t = np.arange(0, 4.0, 1.0 / fps)
    rng = np.random.default_rng(11)
    s = np.where((t > 1.0) & (t < 2.0), 0.20, 0.90) + rng.normal(0, 0.03, len(t))

    def minimos(x, u):
        return sum(1 for i in range(1, len(x) - 1)
                   if x[i] < u and x[i] <= x[i - 1] and x[i] <= x[i + 1])

    assert minimos(s, 0.35) > 3, "el metodo ingenuo deberia sobrecontar"
    assert len(detectar_episodios(s, t, umbral=0.35)) == 1


# ------------------------------------------------------------- histéresis


def test_la_histeresis_evita_contar_un_evento_muchas_veces():
    """Una señal que tiembla justo en el umbral: sin banda muerta produce
    una ráfaga de detecciones donde hubo un solo evento."""
    fps = 30.0
    t = np.arange(0, 4.0, 1.0 / fps)
    rng = np.random.default_rng(3)
    s = np.where((t > 1.0) & (t < 2.0), 0.30, 0.90)
    s = s + rng.normal(0, 0.05, len(t))          # ruido que cruza el umbral

    con = detectar_episodios(s, t, umbral=0.35, factor_salida=1.35)
    sin = detectar_episodios(s, t, umbral=0.35, factor_salida=1.0)
    assert len(con) == 1
    assert len(sin) > len(con), "sin histeresis deberia fragmentarse"


def test_dos_eventos_separados_no_se_funden():
    t, s = palmadas(n=2, fps=30.0, duracion_s=6.0)
    assert len(detectar_episodios(s, t, umbral=0.35)) == 2


# ------------------------------------------------------------- robustez


def test_los_huecos_cortos_no_parten_un_episodio():
    """La pose se pierde durante decimas de segundo con frecuencia; partir
    por eso daria dos detecciones donde hubo una."""
    t, s = palmadas(n=1, fps=30.0, duracion_s=4.0)
    i = int(np.argmin(s))
    s[i - 1:i + 2] = np.nan                       # 3 frames = 100 ms
    assert len(detectar_episodios(s, t, umbral=0.35, hueco_maximo_s=0.25)) == 1


def test_un_hueco_largo_si_cierra_el_episodio():
    t, s = palmadas(n=1, fps=30.0, duracion_s=4.0)
    i = int(np.argmin(s))
    s[i - 15:i + 15] = np.nan                     # 1 s sin datos
    assert len(detectar_episodios(s, t, umbral=0.35, hueco_maximo_s=0.25)) <= 1


def test_los_destellos_cortos_se_descartan():
    fps = 30.0
    t = np.arange(0, 3.0, 1.0 / fps)
    s = np.full(len(t), 0.9)
    s[40] = 0.1                                   # un solo frame
    assert detectar_episodios(s, t, umbral=0.35, min_duracion_s=0.10) == []
    assert len(detectar_episodios(s, t, umbral=0.35, min_duracion_s=0.0)) == 1


def test_una_senal_toda_por_debajo_da_un_solo_episodio():
    t = np.arange(0, 2.0, 1 / 30.0)
    assert len(detectar_episodios(np.full(len(t), 0.1), t, umbral=0.35)) == 1


def test_una_senal_toda_por_encima_no_da_ninguno():
    t = np.arange(0, 2.0, 1 / 30.0)
    assert detectar_episodios(np.full(len(t), 0.9), t, umbral=0.35) == []


def test_una_senal_vacia_no_revienta():
    assert detectar_episodios(np.array([]), umbral=0.35) == []


def test_senal_y_tiempos_de_distinto_largo_fallan():
    with pytest.raises(ValueError):
        detectar_episodios(np.zeros(10), np.zeros(5), umbral=0.5)


# ------------------------------------------------------ contenido del episodio


def test_el_episodio_localiza_su_pico():
    t, s = palmadas(n=1, fps=30.0, duracion_s=4.0, semilla=7)
    ep = detectar_episodios(s, t, umbral=0.35)[0]
    assert ep.pico == pytest.approx(int(np.argmin(s)), abs=2)
    assert ep.valor_pico == pytest.approx(s.min(), abs=0.02)
    assert ep.inicio <= ep.pico <= ep.fin
    assert ep.t_pico == pytest.approx(t[ep.pico])
    assert 0.2 < ep.duracion_s < 1.0
    assert ep.n_frames == ep.fin - ep.inicio + 1


# --------------------------------------------------------------- señales


def _sec(t=50):
    rng = np.random.default_rng(1)
    return rng.uniform(-0.5, 0.5, size=(t, N_LANDMARKS, 3))


def test_distancia_entre_landmarks():
    S = np.zeros((3, N_LANDMARKS, 3))
    S[:, 5] = [0.3, 0.0, 0.0]
    assert distancia(S, 5, 6) == pytest.approx([0.3, 0.3, 0.3])


def test_distancia_rechaza_formas_incoherentes():
    with pytest.raises(ValueError):
        distancia(np.zeros((10, 33)), 0, 1)


def test_la_rapidez_usa_el_intervalo_real_y_no_el_nominal():
    """Con jitter, dividir por 1/fps nominal mete error en cada muestra."""
    S = np.zeros((3, N_LANDMARKS, 3))
    S[1, 0] = [0.1, 0, 0]
    S[2, 0] = [0.2, 0, 0]
    t = np.array([0.0, 0.05, 0.20])               # intervalos muy distintos
    v = rapidez(S, 0, t)
    assert np.isnan(v[0])
    assert v[1] == pytest.approx(0.1 / 0.05)
    assert v[2] == pytest.approx(0.1 / 0.15)


def test_el_umbral_por_percentil_se_adapta_a_la_senal():
    # El percentil 12 sólo cae en la parte baja si esa parte es >= 12 %.
    s = np.concatenate([np.full(80, 1.0), np.full(20, 0.2)])
    assert umbral_por_percentil(s, 12.0) == pytest.approx(0.2, abs=0.15)
    assert umbral_por_percentil(s, 50.0) == pytest.approx(1.0)
    assert np.isnan(umbral_por_percentil(np.array([np.nan, np.nan])))
