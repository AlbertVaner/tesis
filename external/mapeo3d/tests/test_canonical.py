"""Marco corporal: invariancia a la vista y a la estatura.

La propiedad que justifica el módulo es que **la misma pose vista desde
cámaras distintas produzca los mismos números**. Todo lo demás es accesorio, y
si esa falla el módulo no sirve para nada.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from mapeo3d.pose import (  # noqa: E402
    CONDICION_MINIMA,
    INDICE,
    N_LANDMARKS,
    EstimadorDeEscala,
    canonicalizar,
    canonicalizar_secuencia,
    escala_de_sesion,
    marco_corporal,
    normalizar,
    rasgos_de_sesion,
)

I = INDICE


def cuerpo(ancho_caderas=0.26, ancho_hombros=0.38, torso=0.50,
           semilla=0) -> np.ndarray:
    """Pose sintética en el marco de una cámara, como la da MediaPipe.

    `y` crece hacia ABAJO, que es el convenio de MediaPipe.
    """
    rng = np.random.default_rng(semilla)
    P = rng.uniform(-0.4, 0.4, size=(N_LANDMARKS, 3))
    P[I["left_hip"]] = [ancho_caderas / 2, 0.0, 0.0]
    P[I["right_hip"]] = [-ancho_caderas / 2, 0.0, 0.0]
    P[I["left_shoulder"]] = [ancho_hombros / 2, -torso, 0.0]
    P[I["right_shoulder"]] = [-ancho_hombros / 2, -torso, 0.0]
    P[I["left_wrist"]] = [0.55, -0.35, 0.10]
    P[I["right_wrist"]] = [-0.55, -0.35, 0.10]
    return P


def rotar_y(P, grados):
    """Lo que vería otra cámara del anillo, `grados` más allá."""
    a = np.radians(grados)
    c, s = np.cos(a), np.sin(a)
    return P @ np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]]).T


# ------------------------------------------------------- la propiedad clave


@pytest.mark.parametrize("grados", [10, 30, 60, 90, 120, 180, -45])
def test_la_pose_canonica_no_depende_de_la_camara(grados):
    """Es la razón de ser del módulo: conmutar de cámara deja de notarse."""
    P = cuerpo()
    a = canonicalizar(P)
    b = canonicalizar(rotar_y(P, grados))
    assert a is not None and b is not None
    assert np.allclose(a, b, atol=1e-9), f"difieren al girar {grados}°"


def test_sin_canonicalizar_si_depende_de_la_camara():
    """Comprobación de que la prueba anterior no es trivialmente cierta."""
    P = cuerpo()
    assert not np.allclose(P, rotar_y(P, 60), atol=1e-3)


def test_tampoco_depende_de_donde_este_la_persona():
    P = cuerpo()
    desplazada = P + np.array([1.7, -0.4, 2.9])
    assert np.allclose(canonicalizar(P), canonicalizar(desplazada), atol=1e-9)


def test_normalizado_no_depende_de_la_estatura():
    """Dos sujetos con la misma pose y distinto tamaño dan los mismos rasgos."""
    chico = cuerpo()
    grande = chico * 1.35
    a = normalizar(canonicalizar(chico), escala_de_sesion(chico[None]))
    b = normalizar(canonicalizar(grande), escala_de_sesion(grande[None]))
    assert np.allclose(a, b, atol=1e-9)


def test_la_lateralidad_se_conserva():
    """Canonicalizar NO debe volver simétrica la pose: izquierda es izquierda.

    Si un espejo diese el mismo resultado, «brazo derecho arriba» y «brazo
    izquierdo arriba» serían el mismo gesto.
    """
    P = cuerpo()
    espejo = P * np.array([-1.0, 1.0, 1.0])
    a, b = canonicalizar(P), canonicalizar(espejo)
    assert a is not None and b is not None
    assert not np.allclose(a, b, atol=1e-3)


# ------------------------------------------------------------------ marco


def test_el_marco_es_ortonormal_y_esta_en_las_caderas():
    m = marco_corporal(cuerpo())
    assert m is not None
    assert np.allclose(m.rotacion @ m.rotacion.T, np.eye(3), atol=1e-9)
    assert np.allclose(m.origen, [0.0, 0.0, 0.0], atol=1e-9)
    assert m.ancho_caderas_m == pytest.approx(0.26)
    assert m.largo_torso_m == pytest.approx(0.50)


def test_el_eje_vertical_apunta_a_los_hombros():
    """En el marco del cuerpo los hombros quedan por ENCIMA del origen."""
    c = canonicalizar(cuerpo())
    assert c[I["left_shoulder"]][1] > 0.3
    assert c[I["left_hip"]][1] == pytest.approx(0.0, abs=1e-9)


def test_el_eje_lateral_separa_izquierda_de_derecha():
    c = canonicalizar(cuerpo())
    assert c[I["left_hip"]][0] > 0 > c[I["right_hip"]][0]


def test_los_ejes_se_ortogonalizan_aunque_el_torso_este_inclinado():
    """Caderas y columna no son perpendiculares exactas; suponerlo inclinaría
    la pose entera."""
    P = cuerpo()
    P[I["left_shoulder"]] += [0.12, 0.0, 0.0]     # hombros desplazados
    P[I["right_shoulder"]] += [0.12, 0.0, 0.0]
    m = marco_corporal(P)
    assert m is not None
    assert np.allclose(m.rotacion @ m.rotacion.T, np.eye(3), atol=1e-9)


# ------------------------------------------------------------- validez


def test_de_perfil_el_marco_se_declara_no_utilizable():
    """El ancho de caderas se desploma y el eje lateral pasa a ser ruido."""
    P = cuerpo(ancho_caderas=0.03)
    m = marco_corporal(P)
    assert m is not None
    assert m.condicion < CONDICION_MINIMA
    assert not m.valido
    assert canonicalizar(P) is None
    # Se puede pedir igualmente, para inspeccionar.
    assert canonicalizar(P, exigir_valido=False) is not None


def test_de_frente_la_condicion_es_holgada():
    m = marco_corporal(cuerpo())
    assert m.condicion == pytest.approx(0.52, abs=0.02)
    assert m.valido


def test_sin_los_landmarks_del_marco_no_hay_marco():
    """Devolver None es el contrato: un marco inventado gira la pose entera."""
    P = cuerpo()
    P[I["right_hip"]] = np.nan
    assert marco_corporal(P) is None
    assert canonicalizar(P) is None


def test_una_cadera_que_el_modelo_no_ve_invalida_el_marco():
    P = cuerpo()
    v = np.full(N_LANDMARKS, 0.9)
    v[I["left_hip"]] = 0.1
    assert marco_corporal(P, v) is None
    assert marco_corporal(P, v, min_visibilidad=0.05) is not None


def test_caderas_coincidentes_no_revientan():
    assert marco_corporal(cuerpo(ancho_caderas=0.0)) is None


# ---------------------------------------------------------------- secuencia


def test_la_secuencia_marca_nan_donde_no_hay_marco():
    S = np.stack([cuerpo(semilla=i) for i in range(6)])
    S[2, I["left_hip"]] = np.nan
    S[4] = cuerpo(ancho_caderas=0.02)          # de perfil
    C = canonicalizar_secuencia(S)
    assert C.shape == S.shape
    assert np.all(np.isnan(C[2])) and np.all(np.isnan(C[4]))
    assert np.all(np.isfinite(C[0])) and np.all(np.isfinite(C[5]))


def test_la_secuencia_rechaza_formas_incoherentes():
    with pytest.raises(ValueError):
        canonicalizar_secuencia(np.zeros((10, 33)))


def test_la_escala_de_sesion_es_el_torso_mediano():
    S = np.stack([cuerpo(torso=0.48), cuerpo(torso=0.50), cuerpo(torso=0.52)])
    assert escala_de_sesion(S) == pytest.approx(0.50)


def test_los_rasgos_salen_adimensionales_y_estables():
    S = np.stack([cuerpo(semilla=i) for i in range(20)])
    rasgos, escala = rasgos_de_sesion(S)
    assert escala == pytest.approx(0.50)
    assert rasgos.shape == S.shape
    # Torso de largo 1 tras normalizar.
    torso = np.linalg.norm(rasgos[:, I["left_shoulder"]] - rasgos[:, I["left_hip"]],
                           axis=1)
    assert np.allclose(torso, np.median(torso), rtol=0.05)


# ------------------------------------------------------------ escala en vivo


def test_el_estimador_de_escala_calienta_y_luego_se_estabiliza():
    est = EstimadorDeEscala(calentamiento=10)
    assert not est.listo and np.isnan(est.escala_m)
    rng = np.random.default_rng(0)
    for _ in range(30):
        est.observar(marco_corporal(cuerpo(torso=0.50 + rng.normal(0, 0.01))))
    assert est.listo and est.n == 30
    assert est.escala_m == pytest.approx(0.50, abs=0.01)


def test_el_estimador_ignora_los_marcos_invalidos():
    est = EstimadorDeEscala(calentamiento=5)
    for _ in range(10):
        est.observar(marco_corporal(cuerpo(ancho_caderas=0.02)))   # de perfil
        est.observar(None)
    assert est.n == 0 and not est.listo


def test_normalizar_con_escala_invalida_no_inventa_numeros():
    c = canonicalizar(cuerpo())
    assert np.all(np.isnan(normalizar(c, 0.0)))
    assert np.all(np.isnan(normalizar(c, float("nan"))))
