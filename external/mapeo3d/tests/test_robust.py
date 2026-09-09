"""Triangulación robusta de N vistas, con datos sintéticos y sin cámaras.

El escenario de todas las pruebas es el montaje real previsto: **seis cámaras
en anillo** alrededor de una sala, mirando al centro, con el operador dentro.
Ver docs/triangulation.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from mapeo3d.triangulation import (  # noqa: E402
    ANGULO_MIN_DEG,
    MIN_VISTAS,
    angulo_util_deg,
    camera_center,
    project,
    segment_length_stability,
    segment_lengths,
    triangulate_landmarks,
    triangulate_robust,
)

ANCHO, ALTO = 1280, 720
FOCAL = 900.0


def _K() -> np.ndarray:
    return np.array([[FOCAL, 0, ANCHO / 2], [0, FOCAL, ALTO / 2], [0, 0, 1.0]])


def anillo(n: int = 6, radio: float = 2.5, altura: float = 1.6) -> np.ndarray:
    """`(n, 3, 4)`: n cámaras en círculo mirando al centro de la sala.

    Es la geometría de docs/hardware.md: con el operador en el centro, dos
    cámaras separadas un ángulo `t` en el anillo dan un ángulo de triangulación
    cercano a `t`, algo menor porque las cámaras van por encima del sujeto.
    """
    K = _K()
    Ps = []
    for i in range(n):
        t = 2.0 * np.pi * i / n
        C = np.array([radio * np.cos(t), radio * np.sin(t), altura])
        # Eje óptico hacia el centro de la sala, a la altura del pecho.
        z = np.array([0.0, 0.0, 1.2]) - C
        z /= np.linalg.norm(z)
        x = np.cross(np.array([0.0, 0.0, 1.0]), z)
        x /= np.linalg.norm(x)
        y = np.cross(z, x)
        R = np.stack([x, y, z])
        Ps.append(K @ np.hstack([R, (-R @ C).reshape(3, 1)]))
    return np.array(Ps)


def proyectar(Ps: np.ndarray, X: np.ndarray, ruido: float = 0.0,
              rng=None) -> np.ndarray:
    """`(N, K, 2)` con ruido gaussiano opcional en píxeles."""
    X = np.asarray(X, dtype=np.float64).reshape(-1, 3)
    obs = np.array([project(P, X) for P in Ps])
    if ruido > 0:
        rng = rng or np.random.default_rng(0)
        obs = obs + rng.normal(0.0, ruido, obs.shape)
    return obs


# --------------------------------------------------------------- geometría


def _angulo(C, i, j, punto):
    a, b = C[i] - punto, C[j] - punto
    cos = np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))
    return np.degrees(np.arccos(np.clip(cos, -1, 1)))


def test_el_anillo_de_seis_da_angulos_cercanos_a_60_120_180():
    """Adyacentes ~60°, siguientes ~120°, opuestas ~180°.

    No son exactos porque las cámaras van por encima del punto observado: esa
    diferencia de altura impide que dos cámaras opuestas queden perfectamente
    alineadas con él. Ver `test_la_altura_de_montaje_rescata_al_par_opuesto`.
    """
    C = np.array([camera_center(P) for P in anillo(6)])
    pecho = np.array([0.0, 0.0, 1.2])

    assert _angulo(C, 0, 1, pecho) == pytest.approx(59.2, abs=0.5)
    assert _angulo(C, 0, 2, pecho) == pytest.approx(117.6, abs=0.5)
    assert _angulo(C, 0, 3, pecho) == pytest.approx(161.8, abs=0.5)


def test_el_par_opuesto_casi_no_puntua_y_el_adyacente_si():
    """180° es tan inservible como 0°: la calidad de un par es min(t, 180-t)."""
    C = np.array([camera_center(P) for P in anillo(6)])
    pecho = np.array([0.0, 0.0, 1.2])

    assert angulo_util_deg(C[[0, 3]], pecho) == pytest.approx(18.2, abs=0.5)
    assert angulo_util_deg(C[[0, 1]], pecho) == pytest.approx(59.2, abs=0.5)
    # 120° puntúa igual que 60°: ambos distan lo mismo de los extremos.
    assert angulo_util_deg(C[[0, 2]], pecho) == pytest.approx(62.4, abs=0.5)


def test_la_altura_de_montaje_rescata_al_par_opuesto():
    """Cuanto más abajo el landmark, mejor condicionado el par opuesto.

    Consecuencia de montaje, no un detalle del test: con las cámaras a 1.6 m y
    un anillo de 2.5 m de radio, dos cámaras enfrentadas quedan a 18° de
    calidad sobre el pecho —por debajo del mínimo de 20°— pero a 27° sobre la
    cadera. Subir las cámaras aleja al par opuesto de la colinealidad.
    """
    C = np.array([camera_center(P) for P in anillo(6)])

    pecho = angulo_util_deg(C[[0, 3]], np.array([0.0, 0.0, 1.2]))
    cadera = angulo_util_deg(C[[0, 3]], np.array([0.0, 0.0, 1.0]))
    assert pecho < ANGULO_MIN_DEG < cadera


def test_dos_camaras_opuestas_no_se_aceptan():
    """Rayos colineales: la intersección queda indeterminada."""
    Ps = anillo(6)
    X = np.array([[0.0, 0.0, 1.2]])
    obs = proyectar(Ps, X)
    r = triangulate_robust(Ps[[0, 3]], obs[[0, 3], 0, :])
    assert not r.valido
    assert np.all(np.isnan(r.xyz))


# ------------------------------------------------------------ reconstrucción


def test_reconstruye_un_punto_conocido_sin_ruido():
    Ps = anillo(6)
    X = np.array([[0.3, -0.2, 1.4]])
    r = triangulate_robust(Ps, proyectar(Ps, X)[:, 0, :])
    assert r.valido
    assert r.n_vistas == 6
    assert np.allclose(r.xyz, X[0], atol=1e-6)


def test_con_ruido_realista_el_error_es_milimetrico():
    """0.5 px de ruido de detección sobre seis vistas a 2.5 m."""
    Ps = anillo(6)
    rng = np.random.default_rng(7)
    X = np.array([[0.2, 0.1, 1.3]])
    errores = []
    for _ in range(60):
        r = triangulate_robust(Ps, proyectar(Ps, X, 0.5, rng)[:, 0, :])
        assert r.valido
        errores.append(np.linalg.norm(r.xyz - X[0]))
    assert np.mean(errores) < 0.005, f"error medio {np.mean(errores) * 1000:.1f} mm"


def test_una_vista_que_alucina_se_descarta():
    """El caso de la muñeca puesta en un objeto del fondo, con confianza alta.

    Es lo que pasa cuando MediaPipe ve al operador de espaldas e intercambia
    izquierda y derecha. Sin esta capa, un solo error de 200 px arrastra el
    punto varios centímetros.
    """
    Ps = anillo(6)
    X = np.array([[0.0, 0.0, 1.4]])
    obs = proyectar(Ps, X)[:, 0, :]
    obs[4] += np.array([180.0, -120.0])

    ingenuo = triangulate_robust(
        Ps, obs, umbral_vista_px=1e9, umbral_punto_px=1e9
    )
    robusto = triangulate_robust(Ps, obs)

    assert robusto.valido
    assert not robusto.vistas[4], "no descartó la vista que alucinó"
    assert robusto.n_vistas == 5
    assert np.linalg.norm(robusto.xyz - X[0]) < 1e-4
    assert np.linalg.norm(ingenuo.xyz - X[0]) > 10 * np.linalg.norm(
        robusto.xyz - X[0]
    )


def test_dos_vistas_que_alucinan_tambien():
    Ps = anillo(6)
    X = np.array([[-0.4, 0.25, 1.1]])
    obs = proyectar(Ps, X)[:, 0, :]
    obs[1] += np.array([-150.0, 90.0])
    obs[5] += np.array([100.0, 140.0])
    r = triangulate_robust(Ps, obs)
    assert r.valido and r.n_vistas == 4
    assert not r.vistas[1] and not r.vistas[5]
    assert np.linalg.norm(r.xyz - X[0]) < 1e-4


def test_las_vistas_de_poca_confianza_no_entran():
    Ps = anillo(6)
    X = np.array([[0.1, 0.1, 1.5]])
    obs = proyectar(Ps, X)[:, 0, :]
    obs[2] += np.array([300.0, 300.0])          # basura...
    pesos = np.ones(6)
    pesos[2] = 0.05                              # ...pero declarada como tal
    r = triangulate_robust(Ps, obs, pesos)
    assert r.valido and not r.vistas[2]


def test_pocas_vistas_no_se_reportan_como_validas():
    Ps = anillo(6)
    X = np.array([[0.0, 0.0, 1.2]])
    obs = proyectar(Ps, X)[:, 0, :]
    pesos = np.zeros(6)
    pesos[0] = 1.0                               # una sola vista utilizable
    r = triangulate_robust(Ps, obs, pesos)
    assert not r.valido
    assert r.confianza == 0.0
    assert np.all(np.isnan(r.xyz))


def test_un_landmark_no_finito_no_rompe_nada():
    Ps = anillo(6)
    X = np.array([[0.0, 0.2, 1.3]])
    obs = proyectar(Ps, X)[:, 0, :]
    obs[3] = np.nan
    r = triangulate_robust(Ps, obs)
    assert r.valido and not r.vistas[3] and r.n_vistas == 5


# ------------------------------------------------------------- lote de 33


def test_triangula_un_esqueleto_entero():
    Ps = anillo(6)
    rng = np.random.default_rng(3)
    X = rng.uniform([-0.5, -0.5, 0.8], [0.5, 0.5, 1.9], size=(33, 3))
    obs = proyectar(Ps, X, 0.5, rng)
    pesos = np.full((6, 33), 0.9)

    xyz, residual, n_vistas, angulo, conf = triangulate_landmarks(Ps, obs, pesos)

    assert xyz.shape == (33, 3)
    assert np.all(np.isfinite(xyz))
    assert np.all(n_vistas == 6)
    assert np.all(conf > 0)
    assert np.max(np.linalg.norm(xyz - X, axis=1)) < 0.01
    assert np.all(angulo > 50.0)


def test_los_landmarks_ocluidos_salen_nan_no_inventados():
    """Mejor que el consumidor sepa que no hay dato a que reciba un número."""
    Ps = anillo(6)
    rng = np.random.default_rng(11)
    X = rng.uniform([-0.4, -0.4, 0.9], [0.4, 0.4, 1.8], size=(33, 3))
    obs = proyectar(Ps, X, 0.4, rng)
    pesos = np.full((6, 33), 0.9)
    pesos[:, 7] = 0.0                            # landmark 7 no lo ve nadie

    xyz, _residual, n_vistas, _ang, conf = triangulate_landmarks(Ps, obs, pesos)

    assert np.all(np.isnan(xyz[7]))
    assert conf[7] == 0.0 and n_vistas[7] == 0
    otros = [i for i in range(33) if i != 7]
    assert np.all(np.isfinite(xyz[otros]))


# --------------------------------------------------------------- métricas


def test_la_longitud_de_un_segmento_es_la_distancia():
    X = np.array([[0.0, 0.0, 0.0], [0.3, 0.0, 0.0], [0.3, 0.4, 0.0]])
    L = segment_lengths(X, np.array([[0, 1], [1, 2], [0, 2]]))
    assert L == pytest.approx([0.3, 0.4, 0.5])


def test_un_hueso_rigido_da_variacion_casi_nula():
    """La medida que valida la reconstrucción sin verdad de terreno.

    Un brazo de 30 cm que se mueve por la sala tiene que medir 30 cm en todos
    los frames. Lo que se reporta es cuánto se desvía de eso.
    """
    Ps = anillo(6)
    rng = np.random.default_rng(5)
    pares = np.array([[0, 1]])
    secuencia = []
    for t in np.linspace(0, 2 * np.pi, 40):
        codo = np.array([0.25 * np.cos(t), 0.25 * np.sin(t), 1.3])
        # Muñeca a 30 cm exactos del codo, en dirección variable.
        d = np.array([np.cos(t * 1.7), np.sin(t * 1.7), 0.4])
        muneca = codo + 0.30 * d / np.linalg.norm(d)
        X = np.stack([codo, muneca])
        xyz, *_ = triangulate_landmarks(Ps, proyectar(Ps, X, 0.5, rng))
        secuencia.append(xyz)

    est = segment_length_stability(np.array(secuencia), pares)
    assert est.n[0] == 40
    assert est.media[0] == pytest.approx(0.30, abs=0.002)
    assert est.variacion[0] < 0.01, f"variación {est.variacion[0] * 100:.2f} %"


def test_una_reconstruccion_peor_da_mas_variacion():
    """La medida tiene que separar una reconstrucción buena de una mala.

    Si no distingue, no sirve para comparar triangulación contra
    `pose_world_landmarks`, que es para lo que existe.
    """
    rng = np.random.default_rng(13)
    base = np.zeros((50, 2, 3))
    base[:, 1, 0] = 0.30
    buena = base + rng.normal(0, 0.001, base.shape)
    mala = base + rng.normal(0, 0.02, base.shape)
    pares = np.array([[0, 1]])

    v_buena = segment_length_stability(buena, pares).variacion_media
    v_mala = segment_length_stability(mala, pares).variacion_media
    assert v_buena < v_mala / 5


def test_los_frames_sin_dato_no_cuentan():
    sec = np.zeros((10, 2, 3))
    sec[:, 1, 0] = 0.25
    sec[3:6] = np.nan
    est = segment_length_stability(sec, np.array([[0, 1]]))
    assert est.n[0] == 7
    assert est.media[0] == pytest.approx(0.25)


def test_un_segmento_casi_sin_muestras_se_reporta_sin_datos():
    sec = np.full((10, 2, 3), np.nan)
    sec[:2] = 0.0
    sec[:2, 1, 0] = 0.25
    est = segment_length_stability(sec, np.array([[0, 1]]), minimo_frames=5)
    assert est.n[0] == 2
    assert np.isnan(est.media[0])


# ------------------------------------------------------------------ pose


def test_los_pares_de_huesos_apuntan_a_landmarks_reales():
    from mapeo3d.pose import HUESOS, N_LANDMARKS, pares_de_huesos

    pares = pares_de_huesos()
    assert pares.shape == (len(HUESOS), 2)
    assert pares.min() >= 0 and pares.max() < N_LANDMARKS
    assert all(a != b for a, b in pares)


def test_landmarks2d_convierte_a_pixeles():
    from mapeo3d.pose import Landmarks2D

    lm = Landmarks2D(
        xy=np.array([[0.5, 0.5], [0.0, 1.0]]),
        visibility=np.array([0.9, 0.2]),
        presence=np.array([1.0, 1.0]),
        image_size=(1280, 720),
    )
    assert lm.n == 2
    assert np.allclose(lm.to_pixels(), [[640.0, 360.0], [0.0, 720.0]])
    assert lm.confianza() == pytest.approx([0.9, 0.2])


def test_landmarks2d_rechaza_formas_incoherentes():
    from mapeo3d.pose import Landmarks2D

    with pytest.raises(ValueError):
        Landmarks2D(
            xy=np.zeros((33, 2)),
            visibility=np.zeros(10),
            presence=np.zeros(33),
            image_size=(1280, 720),
        )
