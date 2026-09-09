"""Pruebas de `calibration/` sin cámaras.

Se proyectan puntos de un tablero con una matriz de cámara **conocida** y se
comprueba que la calibración la recupera. Es la validación de nivel 1 que exige
AGENTS.md: si esto falla, todo lo que se construya encima está mal.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mapeo3d.calibration import (  # noqa: E402
    COHERENCIA_SISTEMATICA,
    EXTENT_MINIMO,
    CameraIntrinsics,
    ChessboardSpec,
    calibrate,
    cargar_puntos,
    corner_centroid,
    corner_extent,
    corner_movement,
    diagnosticar,
    escribir_reporte,
    find_corners,
    find_corners_preview,
    guardar_puntos,
)

# Cámara de referencia: la Tapo C210 medida el 2026-09-02.
ANCHO, ALTO = 2304, 1296
FOCAL = 1776.0
SPEC = ChessboardSpec(cols=9, rows=6, square_mm=25.0)


@pytest.fixture(scope="module")
def K_real() -> np.ndarray:
    return np.array(
        [[FOCAL, 0, ANCHO / 2], [0, FOCAL, ALTO / 2], [0, 0, 1]], dtype=np.float64
    )


@pytest.fixture(scope="module")
def vistas_sinteticas(K_real: np.ndarray) -> list[np.ndarray]:
    """Proyecciones del tablero desde poses variadas, sin distorsión."""
    objp = SPEC.object_points()
    rng = np.random.default_rng(0)
    puntos: list[np.ndarray] = []
    for _ in range(24):
        rvec = rng.uniform(-0.45, 0.45, 3)
        tvec = np.array(
            [rng.uniform(-0.25, 0.25), rng.uniform(-0.15, 0.15), rng.uniform(0.7, 1.6)]
        )
        pts, _ = cv2.projectPoints(objp, rvec, tvec, K_real, np.zeros(5))
        xs, ys = pts[:, 0, 0], pts[:, 0, 1]
        if xs.min() < 0 or xs.max() > ANCHO or ys.min() < 0 or ys.max() > ALTO:
            continue  # el tablero se sale del cuadro
        puntos.append(pts.astype(np.float32))
    assert len(puntos) >= 10, "no se generaron suficientes vistas sintéticas"
    return puntos


@pytest.fixture(scope="module")
def intrinsecos(vistas_sinteticas: list[np.ndarray]) -> CameraIntrinsics:
    return calibrate(vistas_sinteticas, SPEC, (ANCHO, ALTO), camera="sintetica")


def test_recupera_la_focal(intrinsecos: CameraIntrinsics):
    assert abs(intrinsecos.fx - FOCAL) / FOCAL < 0.01


def test_rms_bajo_con_datos_limpios(intrinsecos: CameraIntrinsics):
    # Sin ruido en las proyecciones, el ajuste debe ser casi exacto.
    assert intrinsecos.rms < 0.01


def test_fov_derivado_coincide_con_la_medicion(intrinsecos: CameraIntrinsics):
    """El FOV del ajuste debe coincidir con el medido con cinta el 2026-09-02.

    Medición: cámara a 0.98 m, sujeto a 2.22 m, borde inferior a 0.17 m
    -> 65.9° H, 40.1° V. Ver docs/hardware.md.
    """
    assert abs(intrinsecos.fov_h_deg - 65.9) < 0.5
    assert abs(intrinsecos.fov_v_deg - 40.1) < 0.5
    assert abs(intrinsecos.cobertura_vertical_por_metro - 0.730) < 0.01


def test_distancia_minima(intrinsecos: CameraIntrinsics):
    # Con la cámara a la altura óptima, cuerpo entero con brazos en alto.
    assert abs(intrinsecos.distancia_minima(2.20, 1.10) - 3.01) < 0.05
    # A menor altura hace falta más distancia.
    assert intrinsecos.distancia_minima(2.20, 0.98) > intrinsecos.distancia_minima(
        2.20, 1.10
    )


def test_guardar_y_cargar(intrinsecos: CameraIntrinsics, tmp_path: Path):
    ruta = intrinsecos.save(tmp_path / "i.yaml")
    otra = CameraIntrinsics.load(ruta)
    assert np.allclose(otra.K, intrinsecos.K)
    assert np.allclose(otra.dist, intrinsecos.dist)
    assert otra.image_size == intrinsecos.image_size


def test_reporte_documenta_el_residual(intrinsecos: CameraIntrinsics, tmp_path: Path):
    """docs/calibration.md: sin residual documentado, no es citable."""
    texto = escribir_reporte(intrinsecos, tmp_path / "r.md").read_text(encoding="utf-8")
    assert "RMS de reproyección" in texto
    assert f"{intrinsecos.fov_h_deg:.1f}" in texto


def test_rechaza_pocas_vistas(vistas_sinteticas: list[np.ndarray]):
    with pytest.raises(ValueError, match="al menos 5"):
        calibrate(vistas_sinteticas[:3], SPEC, (ANCHO, ALTO))


# --------------------------------------------------------------- detección


def _render_tablero(spec: ChessboardSpec, lado: int = 60) -> np.ndarray:
    """Dibuja un tablero con borde blanco (la detección necesita zona muerta)."""
    cols, rows = spec.cols + 1, spec.rows + 1
    tab = np.zeros((rows * lado, cols * lado), np.uint8)
    for r in range(rows):
        for c in range(cols):
            if (r + c) % 2 == 0:
                tab[r * lado : (r + 1) * lado, c * lado : (c + 1) * lado] = 255
    borde = 80
    img = np.full((tab.shape[0] + 2 * borde, tab.shape[1] + 2 * borde), 255, np.uint8)
    img[borde : borde + tab.shape[0], borde : borde + tab.shape[1]] = tab
    return img


def test_detecta_tablero_frontal():
    esquinas = find_corners(_render_tablero(SPEC), SPEC)
    assert esquinas is not None
    assert len(esquinas) == SPEC.n_corners


def test_detecta_tablero_inclinado():
    img = _render_tablero(SPEC)
    h, w = img.shape
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([[60, 20], [w - 20, 70], [w - 70, h - 25], [25, h - 60]])
    warp = cv2.warpPerspective(
        img, cv2.getPerspectiveTransform(src, dst), (w, h), borderValue=255
    )
    esquinas = find_corners(warp, SPEC)
    assert esquinas is not None
    assert len(esquinas) == SPEC.n_corners


def test_sin_tablero_devuelve_none():
    ruido = np.random.default_rng(1).integers(0, 255, (480, 640), dtype=np.uint8)
    assert find_corners(ruido, SPEC) is None


def test_object_points_en_metros():
    pts = SPEC.object_points()
    assert pts.shape == (SPEC.n_corners, 3)
    assert np.allclose(pts[:, 2], 0.0)  # tablero plano
    # La separación entre esquinas contiguas es el lado de la casilla.
    # OpenCV numera las esquinas por filas, con x variando primero.
    assert abs(float(pts[1, 0] - pts[0, 0]) - 0.025) < 1e-6
    assert abs(float(pts[1, 1] - pts[0, 1])) < 1e-9


def test_preview_coincide_espacialmente_con_la_exacta():
    """La vista previa reduce la imagen; debe situar el tablero igual de bien.

    Sólo se compara la posición: el ORDEN de las esquinas puede empezar por otra
    esquina del tablero, y para dibujar el overlay y decidir si la vista es
    nueva eso da igual. La precisión subpíxel se obtiene al capturar, volviendo
    a detectar sobre el frame completo.
    """
    base = _render_tablero(SPEC)
    grande = cv2.resize(base, (2304, 1296), interpolation=cv2.INTER_LINEAR)

    exactas = find_corners(grande, SPEC)
    preview = find_corners_preview(grande, SPEC, max_width=960)
    assert exactas is not None and preview is not None
    assert len(preview) == SPEC.n_corners

    # Cada esquina de la vista previa cae junto a alguna de las exactas.
    a = exactas.reshape(-1, 2)
    b = preview.reshape(-1, 2)
    distancias = np.min(np.linalg.norm(a[None, :, :] - b[:, None, :], axis=2), axis=1)
    assert distancias.max() < 4.0

    # Y el centroide, que es lo que usa el criterio de vista nueva, coincide.
    cx_e, cy_e = corner_centroid(exactas)
    cx_p, cy_p = corner_centroid(preview)
    assert abs(cx_e - cx_p) < 3.0 and abs(cy_e - cy_p) < 3.0


def test_preview_no_reescala_si_ya_es_pequena():
    """Con una imagen por debajo del umbral no debe tocar nada."""
    img = _render_tablero(SPEC)
    assert img.shape[1] <= 960
    esquinas = find_corners_preview(img, SPEC, max_width=960)
    assert esquinas is not None
    assert len(esquinas) == SPEC.n_corners


# ------------------------------------------------- regresión: forma (N,1,2)


def test_find_corners_respeta_el_contrato_de_forma():
    """Todo detector debe devolver (N, 1, 2) float32.

    Regresión de un fallo real (2026-09-02): `findChessboardCornersSB` en
    OpenCV 5 devuelve (N, 2), que OpenCV interpreta como 1 canal en lugar de 2.
    Mezclar esa forma con la salida de `projectPoints` hacía reventar el
    cálculo del error por vista DESPUÉS de capturar las 20 vistas, perdiéndolas.
    """
    grande = cv2.resize(_render_tablero(SPEC), (2304, 1296))
    for esquinas in (find_corners(grande, SPEC),
                     find_corners_preview(grande, SPEC, 960)):
        assert esquinas is not None
        assert esquinas.shape == (SPEC.n_corners, 1, 2)
        assert esquinas.dtype == np.float32


def test_calibrate_tolera_formas_mezcladas(vistas_sinteticas: list[np.ndarray]):
    """Aunque una vista llegue como (N,2), calibrate debe funcionar.

    Es la segunda mitad de la defensa: aunque un detector nuevo devuelva otra
    forma, la calibración la normaliza en lugar de fallar.
    """
    mezcla = [
        v.reshape(-1, 2) if i % 2 else v for i, v in enumerate(vistas_sinteticas)
    ]
    intr = calibrate(mezcla, SPEC, (ANCHO, ALTO), camera="mezcla")
    assert abs(intr.fx - FOCAL) / FOCAL < 0.01
    assert intr.per_view_errors.size == len(mezcla)


# ------------------------------------------------- persistencia de capturas


def test_guardar_y_recuperar_capturas(
    vistas_sinteticas: list[np.ndarray], tmp_path: Path
):
    """Las esquinas se persisten antes de calibrar, para no perder la sesión."""
    ruta = guardar_puntos(
        vistas_sinteticas, SPEC, (ANCHO, ALTO), "cam1", tmp_path / "p.npz"
    )
    puntos, spec, tamano, nombre = cargar_puntos(ruta)

    assert len(puntos) == len(vistas_sinteticas)
    assert (spec.cols, spec.rows, spec.square_mm) == (
        SPEC.cols, SPEC.rows, SPEC.square_mm
    )
    assert tamano == (ANCHO, ALTO)
    assert nombre == "cam1"

    # Y recalibrar desde el archivo da el mismo resultado.
    intr = calibrate(puntos, spec, tamano, camera=nombre)
    assert abs(intr.fx - FOCAL) / FOCAL < 0.01


# ------------------------------------------------------------- diagnóstico


def _vistas_a_distancia(K: np.ndarray, z_min: float, z_max: float, n: int = 20):
    """Vistas sintéticas con el tablero a la distancia pedida."""
    objp = SPEC.object_points()
    rng = np.random.default_rng(3)
    salida = []
    for _ in range(n * 4):
        if len(salida) >= n:
            break
        rvec = rng.uniform(-0.4, 0.4, 3)
        tvec = np.array([
            rng.uniform(-0.15, 0.15), rng.uniform(-0.10, 0.10),
            rng.uniform(z_min, z_max),
        ])
        pts, _ = cv2.projectPoints(objp, rvec, tvec, K, np.zeros(5))
        xs, ys = pts[:, 0, 0], pts[:, 0, 1]
        if xs.min() < 0 or xs.max() > ANCHO or ys.min() < 0 or ys.max() > ALTO:
            continue
        salida.append(pts.astype(np.float32))
    return salida


def test_corner_extent_mide_la_fraccion_del_ancho():
    grande = cv2.resize(_render_tablero(SPEC), (2304, 1296))
    esquinas = find_corners(grande, SPEC)
    ext = corner_extent(esquinas, (2304, 1296))
    # El tablero renderizado ocupa casi todo el cuadro.
    assert 0.5 < ext <= 1.0


def test_diagnostico_detecta_tablero_lejano(K_real: np.ndarray):
    """Es el fallo real de la sesión del 2026-09-02: tablero al 6-14 % del ancho."""
    lejanas = _vistas_a_distancia(K_real, 2.0, 3.0)
    assert lejanas, "no se generaron vistas lejanas"
    hallazgos = diagnosticar(lejanas, (ANCHO, ALTO))
    assert any("demasiado pequeño" in h for h in hallazgos)
    ext = max(corner_extent(np.asarray(v), (ANCHO, ALTO)) for v in lejanas)
    assert ext < EXTENT_MINIMO


def test_diagnostico_no_se_queja_de_vistas_buenas(K_real: np.ndarray):
    cercanas = _vistas_a_distancia(K_real, 0.45, 0.75)
    assert cercanas, "no se generaron vistas cercanas"
    ext = [corner_extent(np.asarray(v), (ANCHO, ALTO)) for v in cercanas]
    assert max(ext) >= EXTENT_MINIMO
    hallazgos = diagnosticar(cercanas, (ANCHO, ALTO))
    assert not any("demasiado pequeño" in h for h in hallazgos)


def test_reporte_incluye_diagnostico(
    intrinsecos: CameraIntrinsics, vistas_sinteticas, tmp_path: Path
):
    texto = escribir_reporte(
        intrinsecos, tmp_path / "r.md", puntos_imagen=vistas_sinteticas
    ).read_text(encoding="utf-8")
    assert "Diagnóstico de las vistas" in texto
    assert "Tamaño del tablero en el cuadro" in texto


# --------------------------------------- coherencia: doblado vs. ruido


def _vistas_con_deformacion(K: np.ndarray, curvatura: float, ruido: float,
                            n: int = 18, semilla: int = 11):
    """Vistas de un tablero que puede estar curvado y/o observado con ruido.

    `curvatura` desplaza las esquinas en Z como un cilindro: es exactamente lo
    que hace un tablero de papel doblado. `ruido` añade error independiente por
    esquina, que es lo que hace el desenfoque.
    """
    rng = np.random.default_rng(semilla)
    objp = SPEC.object_points().copy()
    # Curvatura cilíndrica alrededor del eje Y del tablero.
    x = objp[:, 0] - objp[:, 0].mean()
    objp[:, 2] = curvatura * (x ** 2)

    salida = []
    for _ in range(n * 4):
        if len(salida) >= n:
            break
        rvec = rng.uniform(-0.4, 0.4, 3)
        tvec = np.array([rng.uniform(-0.1, 0.1), rng.uniform(-0.08, 0.08),
                         rng.uniform(0.5, 0.8)])
        pts, _ = cv2.projectPoints(objp, rvec, tvec, K, np.zeros(5))
        xs, ys = pts[:, 0, 0], pts[:, 0, 1]
        if xs.min() < 0 or xs.max() > ANCHO or ys.min() < 0 or ys.max() > ALTO:
            continue
        if ruido:
            pts = pts + rng.normal(0, ruido, pts.shape)
        salida.append(pts.astype(np.float32))
    return salida


def test_coherencia_alta_con_tablero_doblado(K_real: np.ndarray):
    """Un tablero curvado da residual sistemático.

    `curvatura=1.0` equivale a unos 10 mm de flecha en un tablero de 240 mm, y
    reproduce el RMS de ~3 px que dieron cam1 y cam2 el 2026-09-02 sosteniendo
    la hoja a mano.
    """
    vistas = _vistas_con_deformacion(K_real, curvatura=1.0, ruido=0.0)
    assert len(vistas) >= 8
    intr = calibrate(vistas, SPEC, (ANCHO, ALTO), camera="doblado")
    assert intr.rms > 0.5, "la deformación debería subir el RMS"
    assert intr.residual_coherence >= COHERENCIA_SISTEMATICA


def test_coherencia_baja_con_ruido_aleatorio(K_real: np.ndarray):
    """Desenfoque/trepidación: mismo RMS alto, pero residual sin estructura."""
    vistas = _vistas_con_deformacion(K_real, curvatura=0.0, ruido=1.5)
    assert len(vistas) >= 8
    intr = calibrate(vistas, SPEC, (ANCHO, ALTO), camera="ruidoso")
    assert intr.rms > 0.5
    assert intr.residual_coherence < COHERENCIA_SISTEMATICA


def test_diagnostico_distingue_las_dos_causas(K_real: np.ndarray):
    doblado = _vistas_con_deformacion(K_real, curvatura=1.0, ruido=0.0)
    i1 = calibrate(doblado, SPEC, (ANCHO, ALTO))
    h1 = diagnosticar(doblado, (ANCHO, ALTO), i1.rms, i1.residual_coherence)
    assert any("SISTEMÁTICO" in h for h in h1)

    ruidoso = _vistas_con_deformacion(K_real, curvatura=0.0, ruido=1.5)
    i2 = calibrate(ruidoso, SPEC, (ANCHO, ALTO))
    h2 = diagnosticar(ruidoso, (ANCHO, ALTO), i2.rms, i2.residual_coherence)
    assert not any("SISTEMÁTICO" in h for h in h2)
    assert any("aleatorio" in h for h in h2)


# ------------------------------------------- rechazo de vistas atípicas


def test_rechaza_vistas_movidas(K_real: np.ndarray, vistas_sinteticas):
    """Unas pocas vistas malas arrastran el ajuste entero.

    Caso real (cam1, 2026-09-02): 16 vistas entre 0.4 y 1.7 px y 4 entre 5.2 y
    7.3 px daban RMS 2.94. Descartando esas 4, RMS 0.97 y el mismo FOV.
    """
    rng = np.random.default_rng(21)
    contaminadas = [v.copy() for v in vistas_sinteticas]
    # Cuatro vistas "movidas": desplazamiento coherente grande.
    for i in (1, 5, 9, 13):
        if i < len(contaminadas):
            contaminadas[i] = contaminadas[i] + rng.normal(0, 6, contaminadas[i].shape)

    sin = calibrate(contaminadas, SPEC, (ANCHO, ALTO), rechazar_atipicas=False)
    con = calibrate(contaminadas, SPEC, (ANCHO, ALTO))

    assert con.n_descartadas > 0, "no descartó ninguna vista mala"
    assert con.rms < sin.rms / 2, "el rechazo debería bajar mucho el RMS"
    assert abs(con.fx - FOCAL) / FOCAL < 0.02


def test_no_descarta_si_todas_son_buenas(vistas_sinteticas):
    intr = calibrate(vistas_sinteticas, SPEC, (ANCHO, ALTO))
    assert intr.n_descartadas == 0


# ------------------------------------------------- puerta de quietud


def test_corner_movement_distingue_quieto_de_movido():
    a = np.zeros((SPEC.n_corners, 1, 2), np.float32)
    assert corner_movement(a, a) == 0.0
    assert corner_movement(a, a + 10.0) > 2.0
    # Sin detección previa no se puede comparar: no capturar.
    assert corner_movement(None, a) == float("inf")
    # Distinto número de esquinas tampoco es comparable.
    assert corner_movement(a, a[:10]) == float("inf")
