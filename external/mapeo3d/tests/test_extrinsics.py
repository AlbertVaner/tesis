"""Pruebas de la calibración estéreo, sin cámaras.

Se simulan dos cámaras con una pose CONOCIDA y se comprueba que la calibración
la recupera. La prueba que más importa es la métrica absoluta: triangular el
tablero y medir la casilla reconstruida. Un error de escala reproyecta
perfectamente y no aparece en ningún residual, pero sí en ese número.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mapeo3d.calibration import (  # noqa: E402
    EXTENT_MINIMO_ESTEREO,
    MINIMO_PARES,
    RMS_ACEPTABLE_PX,
    CameraIntrinsics,
    ChessboardSpec,
    ParesIncoherentes,
    StereoExtrinsics,
    analizar_coherencia,
    calibrate_stereo,
    pose_relativa_de_un_par,
)
from mapeo3d.triangulation import grid_spacing, triangulate_many  # noqa: E402

W, H, FOCAL = 2304, 1296, 1710.0
SPEC = ChessboardSpec(9, 6, 24.0)
BASE_REAL = 1.50
YAW_REAL = 30.0


@pytest.fixture(scope="module")
def intrinsecos():
    K = np.array([[FOCAL, 0, W / 2], [0, FOCAL, H / 2], [0, 0, 1]], np.float64)
    d = np.zeros(5)
    return (CameraIntrinsics("cam1", (W, H), K.copy(), d.copy(), 0.4, 20),
            CameraIntrinsics("cam2", (W, H), K.copy(), d.copy(), 0.4, 20))


@pytest.fixture(scope="module")
def pose_real():
    R = cv2.Rodrigues(np.array([0.0, np.deg2rad(YAW_REAL), 0.0]))[0]
    C = np.array([BASE_REAL, 0.0, 0.0])
    T = (-R @ C.reshape(3, 1)).ravel()
    return R, T


@pytest.fixture(scope="module")
def pares(intrinsecos, pose_real):
    """Pares del tablero visibles en las dos cámaras, con ruido realista."""
    R, T = pose_real
    K = intrinsecos[0].K
    d = np.zeros(5)
    objp = SPEC.object_points()
    rng = np.random.default_rng(4)
    pa, pb = [], []
    for _ in range(600):
        if len(pa) >= 18:
            break
        rv = rng.uniform(-0.30, 0.30, 3)
        tv = np.array([rng.uniform(0.35, 1.10), rng.uniform(-0.25, 0.25),
                       rng.uniform(1.7, 2.6)])
        A, _ = cv2.projectPoints(objp, rv, tv, K, d)
        Rb = R @ cv2.Rodrigues(rv)[0]
        tb = R @ tv.reshape(3, 1) + T.reshape(3, 1)
        if tb[2, 0] < 0.3:
            continue
        B, _ = cv2.projectPoints(objp, cv2.Rodrigues(Rb)[0], tb, K, d)

        def dentro(p):
            x, y = p[:, 0, 0], p[:, 0, 1]
            return x.min() > 0 and x.max() < W and y.min() > 0 and y.max() < H

        if not (dentro(A) and dentro(B)):
            continue
        pa.append((A + rng.normal(0, 0.25, A.shape)).astype(np.float32))
        pb.append((B + rng.normal(0, 0.25, B.shape)).astype(np.float32))
    assert len(pa) >= MINIMO_PARES
    return pa, pb


@pytest.fixture(scope="module")
def extrinsecos(pares, intrinsecos):
    return calibrate_stereo(pares[0], pares[1], *intrinsecos, SPEC)


def test_recupera_la_linea_base(extrinsecos):
    assert abs(extrinsecos.baseline_m - BASE_REAL) < 0.01


def test_recupera_el_angulo_entre_ejes(extrinsecos):
    assert abs(extrinsecos.angulo_entre_ejes_deg - YAW_REAL) < 1.0


def test_rms_aceptable(extrinsecos):
    assert extrinsecos.rms < 1.0
    assert extrinsecos.calidad_aceptable


def test_escala_metrica_correcta(extrinsecos, pares):
    """La casilla reconstruida debe medir lo que mide el tablero.

    Es la única comprobación absoluta de la cadena entera. Ningún residual de
    reproyección detecta un error de escala.
    """
    Pa, Pb = extrinsecos.projection_matrices()
    medias = []
    for a, b in zip(*pares):
        pts = np.stack([np.asarray(a).reshape(-1, 2),
                        np.asarray(b).reshape(-1, 2)])
        X = triangulate_many(np.stack([Pa, Pb]), pts)
        m, _ = grid_spacing(X, SPEC.cols, SPEC.rows)
        medias.append(m * 1000.0)
    media = float(np.mean(medias))
    assert abs(media - SPEC.square_mm) / SPEC.square_mm < 0.01


def test_rechaza_pares_desiguales(intrinsecos, pares):
    with pytest.raises(ValueError, match="no se corresponden"):
        calibrate_stereo(pares[0], pares[1][:-1], *intrinsecos, SPEC)


def test_rechaza_pocos_pares(intrinsecos, pares):
    with pytest.raises(ValueError, match="al menos"):
        calibrate_stereo(pares[0][:3], pares[1][:3], *intrinsecos, SPEC)


def test_descarta_pares_atipicos(intrinsecos, pares):
    """Unos pocos pares movidos no deben arrastrar el ajuste."""
    rng = np.random.default_rng(7)
    pa = [p.copy() for p in pares[0]]
    pb = [p.copy() for p in pares[1]]
    for i in (2, 6, 10):
        pb[i] = pb[i] + rng.normal(0, 8, pb[i].shape)

    sin = calibrate_stereo(pa, pb, *intrinsecos, SPEC, rechazar_atipicos=False)
    con = calibrate_stereo(pa, pb, *intrinsecos, SPEC)

    assert con.n_descartados > 0
    assert con.rms < sin.rms
    assert abs(con.baseline_m - BASE_REAL) < 0.02


def test_guardar_y_cargar(extrinsecos, tmp_path: Path):
    ruta = extrinsecos.save(tmp_path / "e.yaml")
    otro = StereoExtrinsics.load(ruta)
    assert np.allclose(otro.R, extrinsecos.R)
    assert np.allclose(otro.T, extrinsecos.T)
    assert abs(otro.baseline_m - extrinsecos.baseline_m) < 1e-9


def test_matrices_de_proyeccion_necesitan_intrinsecos(extrinsecos, tmp_path):
    """Cargado de disco, sin intrínsecos, no puede componer las matrices."""
    otro = StereoExtrinsics.load(extrinsecos.save(tmp_path / "e.yaml"))
    with pytest.raises(ValueError, match="intrínsecos"):
        otro.projection_matrices()


def test_el_umbral_estereo_es_mucho_menor_que_el_de_intrinsecos():
    """Son problemas distintos y el umbral lo refleja.

    En intrínsecos se estima la focal y el tablero debe subtender un ángulo
    grande (mínimo 20 % del ancho). En estéreo los intrínsecos van fijos y sólo
    se estiman 6 parámetros desde ~1000 correspondencias, así que basta con
    mucho menos. Medido: el error de escala pasa de +6.96 % al 3 % de extent a
    +0.34 % al 6.3 %, y a +0.17 % al 8.8 %.
    """
    from mapeo3d.calibration import EXTENT_MINIMO

    assert EXTENT_MINIMO_ESTEREO < EXTENT_MINIMO
    assert 0.05 <= EXTENT_MINIMO_ESTEREO <= 0.12


def test_estereo_funciona_con_tablero_pequeno(intrinsecos, pose_real):
    """Con el tablero al ~6 % del ancho la línea base sigue siendo correcta."""
    R, T = pose_real
    K = intrinsecos[0].K
    d = np.zeros(5)
    objp = SPEC.object_points()
    rng = np.random.default_rng(9)
    pa, pb, exts = [], [], []
    from mapeo3d.calibration import corner_extent

    for _ in range(4000):
        if len(pa) >= 18:
            break
        rv = rng.uniform(-0.30, 0.30, 3)
        # Lejos: el tablero se ve pequeño en ambas.
        tv = np.array([rng.uniform(0.4, 1.1), rng.uniform(-0.3, 0.3),
                       rng.uniform(2.8, 3.8)])
        A, _ = cv2.projectPoints(objp, rv, tv, K, d)
        Rb = R @ cv2.Rodrigues(rv)[0]
        tb = R @ tv.reshape(3, 1) + T.reshape(3, 1)
        if tb[2, 0] < 0.3:
            continue
        B, _ = cv2.projectPoints(objp, cv2.Rodrigues(Rb)[0], tb, K, d)

        def dentro(p):
            x, y = p[:, 0, 0], p[:, 0, 1]
            return x.min() > 0 and x.max() < W and y.min() > 0 and y.max() < H

        if not (dentro(A) and dentro(B)):
            continue
        An = (A + rng.normal(0, 0.25, A.shape)).astype(np.float32)
        Bn = (B + rng.normal(0, 0.25, B.shape)).astype(np.float32)
        pa.append(An)
        pb.append(Bn)
        exts.append(min(corner_extent(An, (W, H)), corner_extent(Bn, (W, H))))

    assert len(pa) >= MINIMO_PARES
    assert np.mean(exts) < 0.10, "el escenario debería dar un tablero pequeño"

    ext = calibrate_stereo(pa, pb, *intrinsecos, SPEC)
    assert abs(ext.baseline_m - BASE_REAL) / BASE_REAL < 0.01
    assert abs(ext.angulo_entre_ejes_deg - YAW_REAL) < 1.0


# --------------------------------------------------------------------------
# Coherencia entre pares: detectar que una cámara se movió a mitad de sesión
# --------------------------------------------------------------------------


def _sesion(intrinsecos, semilla, mover_en=None, grados=0.0, n=18):
    """Genera pares, opcionalmente girando la cámara B a partir de un par."""
    K = intrinsecos[0].K
    d = np.zeros(5)
    objp = SPEC.object_points()
    rng = np.random.default_rng(semilla)
    pa, pb = [], []
    for _ in range(4000):
        if len(pa) >= n:
            break
        extra = grados if (mover_en is not None and len(pa) >= mover_en) else 0.0
        R = cv2.Rodrigues(np.array([0.0, np.deg2rad(YAW_REAL + extra), 0.0]))[0]
        T = (-R @ np.array([BASE_REAL, 0.0, 0.0]).reshape(3, 1)).ravel()
        rv = rng.uniform(-0.30, 0.30, 3)
        tv = np.array([rng.uniform(0.35, 1.10), rng.uniform(-0.25, 0.25),
                       rng.uniform(1.7, 2.6)])
        A, _ = cv2.projectPoints(objp, rv, tv, K, d)
        tb = R @ tv.reshape(3, 1) + T.reshape(3, 1)
        if tb[2, 0] < 0.3:
            continue
        B, _ = cv2.projectPoints(objp, cv2.Rodrigues(R @ cv2.Rodrigues(rv)[0])[0],
                                 tb, K, d)

        def dentro(p):
            x, y = p[:, 0, 0], p[:, 0, 1]
            return x.min() > 0 and x.max() < W and y.min() > 0 and y.max() < H

        if not (dentro(A) and dentro(B)):
            continue
        pa.append((A + rng.normal(0, 0.25, A.shape)).astype(np.float32))
        pb.append((B + rng.normal(0, 0.25, B.shape)).astype(np.float32))
    return pa, pb


def test_camaras_quietas_son_coherentes(intrinsecos, pares):
    coh = analizar_coherencia(pares[0], pares[1], *intrinsecos, SPEC)
    assert not coh.hay_movimiento
    assert coh.coherente
    assert len(coh.consenso) == len(pares[0])


def test_detecta_que_una_camara_se_movio(intrinsecos):
    """El fallo más caro de la calibración estéreo tiene que reportarse solo.

    Si una cámara se reapunta a mitad de sesión, `stereoCalibrate` intenta
    ajustar una sola pose rígida a dos geometrías y devuelve un RMS enorme sin
    ninguna pista de la causa. Aquí se detecta antes de ajustar.
    """
    pa, pb = _sesion(intrinsecos, 21, mover_en=9, grados=20.0)
    coh = analizar_coherencia(pa, pb, *intrinsecos, SPEC)
    assert coh.hay_movimiento
    assert len(coh.bloques) >= 2
    assert 6 <= coh.movimiento_en <= 12
    assert "SE MOVIÓ" in coh.diagnostico()


def test_calibrar_rechaza_una_sesion_con_movimiento(intrinsecos):
    pa, pb = _sesion(intrinsecos, 21, mover_en=9, grados=20.0)
    with pytest.raises(ParesIncoherentes):
        calibrate_stereo(pa, pb, *intrinsecos, SPEC)


def test_se_puede_forzar_el_ajuste_incoherente(intrinsecos):
    """Forzar debe funcionar, para poder inspeccionar, pero dar mal RMS."""
    pa, pb = _sesion(intrinsecos, 21, mover_en=9, grados=20.0)
    ext = calibrate_stereo(pa, pb, *intrinsecos, SPEC, exigir_coherencia=False)
    assert ext.rms > RMS_ACEPTABLE_PX
    assert ext.coherencia is not None and ext.coherencia.hay_movimiento


def test_un_par_solo_determina_la_geometria(intrinsecos, pares, pose_real):
    """Base del detector: un tablero visto por las dos cámaras basta."""
    R_real, T_real = pose_real
    objp = SPEC.object_points()
    ia, ib = intrinsecos
    R, T = pose_relativa_de_un_par(
        objp, pares[0][0], pares[1][0],
        ia.K, ia.dist.reshape(1, -1), ib.K, ib.dist.reshape(1, -1),
    )
    assert abs(np.linalg.norm(T) - BASE_REAL) < 0.05
    cos = (np.trace(R @ R_real.T) - 1) / 2
    assert np.degrees(np.arccos(np.clip(cos, -1, 1))) < 2.0


# --------------------------------------------------------------------------
# Rectificación antes de triangular
# --------------------------------------------------------------------------


def test_sin_rectificar_la_escala_sale_mal(intrinsecos, pose_real):
    """Triangular las esquinas tal como se detectan mete la distorsión dentro.

    No rompe nada visible — el residual puede seguir bajo — pero sesga la
    escala reconstruida. Con la distorsión de una Tapo son varios puntos
    porcentuales, y se confunde con un problema del montaje.
    """
    dist = np.array([-0.42, 0.22, 0.006, 0.0003, -0.088])
    K = intrinsecos[0].K
    ia = CameraIntrinsics("cam1", (W, H), K.copy(), dist.copy(), 0.9, 14)
    ib = CameraIntrinsics("cam2", (W, H), K.copy(), dist.copy(), 1.1, 14)
    R, T = pose_real
    objp = SPEC.object_points()
    rng = np.random.default_rng(31)
    pa, pb = [], []
    for _ in range(4000):
        if len(pa) >= 12:
            break
        rv = rng.uniform(-0.30, 0.30, 3)
        tv = np.array([rng.uniform(0.35, 1.10), rng.uniform(-0.25, 0.25),
                       rng.uniform(1.5, 2.2)])
        A, _ = cv2.projectPoints(objp, rv, tv, K, dist)
        tb = R @ tv.reshape(3, 1) + T.reshape(3, 1)
        if tb[2, 0] < 0.3:
            continue
        B, _ = cv2.projectPoints(objp, cv2.Rodrigues(R @ cv2.Rodrigues(rv)[0])[0],
                                 tb, K, dist)

        def dentro(p):
            x, y = p[:, 0, 0], p[:, 0, 1]
            return x.min() > 0 and x.max() < W and y.min() > 0 and y.max() < H

        if not (dentro(A) and dentro(B)):
            continue
        pa.append(A.astype(np.float32))
        pb.append(B.astype(np.float32))

    ext = calibrate_stereo(pa, pb, ia, ib, SPEC)
    Pa, Pb = ext.projection_matrices()

    def casilla(rectificar: bool) -> float:
        ms = []
        for a, b in zip(pa, pb):
            if rectificar:
                pts = np.stack([ia.undistort_points(a), ib.undistort_points(b)])
            else:
                pts = np.stack([np.asarray(a).reshape(-1, 2),
                                np.asarray(b).reshape(-1, 2)])
            X = triangulate_many(np.stack([Pa, Pb]), pts)
            m, _ = grid_spacing(X, SPEC.cols, SPEC.rows)
            ms.append(m * 1000.0)
        return float(np.mean(ms))

    err_con = abs(casilla(True) - SPEC.square_mm) / SPEC.square_mm
    err_sin = abs(casilla(False) - SPEC.square_mm) / SPEC.square_mm
    assert err_con < 0.01, f"rectificando debería dar la casilla real: {err_con:.3%}"
    assert err_sin > 0.02, "sin rectificar debería salir mal, y por eso importa"
