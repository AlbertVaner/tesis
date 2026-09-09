"""Patrón de calibración: definición y detección.

Se soporta el tablero de ajedrez clásico, que es el que se imprime en dos
minutos y no necesita nada más. La estructura deja sitio para ChArUco más
adelante sin cambiar el resto del pipeline.

Nota de nomenclatura que confunde a todo el mundo: un tablero impreso de 10×7
casillas tiene **9×6 esquinas interiores**, y lo que se declara aquí son las
esquinas interiores, no las casillas.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class ChessboardSpec:
    """Tablero de ajedrez para calibración.

    Args:
        cols: esquinas interiores a lo ancho (casillas − 1).
        rows: esquinas interiores a lo alto (casillas − 1).
        square_mm: lado de una casilla, en milímetros, **medido sobre el papel
            impreso**. La impresora casi nunca respeta la escala del PDF, así
            que hay que medirlo con regla, no confiar en el valor nominal.
    """

    cols: int = 9
    rows: int = 6
    square_mm: float = 25.0

    @property
    def pattern_size(self) -> tuple[int, int]:
        return (self.cols, self.rows)

    @property
    def n_corners(self) -> int:
        return self.cols * self.rows

    def object_points(self) -> np.ndarray:
        """Coordenadas 3D de las esquinas en el marco del tablero, en metros.

        El tablero es plano, así que Z = 0 para todas.
        """
        pts = np.zeros((self.n_corners, 3), np.float32)
        pts[:, :2] = np.mgrid[0 : self.cols, 0 : self.rows].T.reshape(-1, 2)
        return pts * (self.square_mm / 1000.0)

    def describe(self) -> str:
        casillas = f"{self.cols + 1}×{self.rows + 1}"
        return (
            f"tablero de {self.cols}×{self.rows} esquinas interiores "
            f"({casillas} casillas), casilla de {self.square_mm:.1f} mm"
        )


# Criterio de parada para el refinamiento subpíxel de las esquinas.
_CRITERIO = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)


def _normalizar(esquinas: np.ndarray) -> np.ndarray:
    """Devuelve siempre `(N, 1, 2)` float32.

    Distintos detectores y distintas versiones de OpenCV devuelven formas
    distintas: `findChessboardCornersSB` en OpenCV 5 devuelve `(N, 2)` mientras
    que el detector clásico devuelve `(N, 1, 2)`. OpenCV interpreta la primera
    como una matriz de 1 canal y la segunda como 2 canales, y eso hace fallar
    cualquier operación que las mezcle.

    Todo el repositorio asume `(N, 1, 2)`. Este es el único sitio donde se
    garantiza.
    """
    return np.asarray(esquinas, dtype=np.float32).reshape(-1, 1, 2)


def find_corners(
    imagen: np.ndarray,
    spec: ChessboardSpec,
    *,
    refinar: bool = True,
    rapido: bool = False,
) -> np.ndarray | None:
    """Busca el tablero en una imagen y devuelve las esquinas subpíxel.

    Devuelve un array `(N, 1, 2)` float32 como espera OpenCV, o `None` si el
    tablero no aparece completo. Un tablero parcialmente visible no sirve: la
    detección es todo o nada.

    Args:
        refinar: aplica `cornerSubPix`. Imprescindible para calibrar.
        rapido: salta el detector SB exhaustivo. **El modo exhaustivo sobre una
            imagen de 3 MP tarda cientos de milisegundos**, lo que hace inusable
            una vista en vivo. Usar `rapido=True` (o mejor, `find_corners_preview`)
            para el indicador en pantalla, y el modo normal sólo al capturar.
    """
    gris = imagen if imagen.ndim == 2 else cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY)

    # Primero el detector clásico: es mucho más barato y con refinamiento
    # subpíxel da la misma precisión. El SB exhaustivo cuesta segundos sobre
    # una imagen de 3 MP y sólo compensa cuando el clásico falla.
    ok, esquinas = cv2.findChessboardCorners(
        gris,
        spec.pattern_size,
        flags=(cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE),
    )
    if ok:
        if refinar:
            esquinas = cv2.cornerSubPix(
                gris, _normalizar(esquinas), (11, 11), (-1, -1), _CRITERIO
            )
        return _normalizar(esquinas)

    # Respaldo: SB ("sector based"), más robusto con imágenes movidas o mal
    # iluminadas, pero mucho más caro. No está en todas las builds.
    if not rapido and hasattr(cv2, "findChessboardCornersSB"):
        ok, esquinas = cv2.findChessboardCornersSB(
            gris,
            spec.pattern_size,
            flags=cv2.CALIB_CB_EXHAUSTIVE | cv2.CALIB_CB_ACCURACY,
        )
        if ok:
            return _normalizar(esquinas)

    return None


def find_corners_preview(
    imagen: np.ndarray,
    spec: ChessboardSpec,
    max_width: int = 960,
) -> np.ndarray | None:
    """Detección barata para la vista en vivo, en coordenadas de la imagen original.

    Reduce la imagen antes de buscar y devuelve las esquinas reescaladas al
    tamaño original. **No refina a subpíxel**: sirve para saber si el tablero
    está en cuadro y dónde, no para calibrar.

    El motivo es de coste: buscar el tablero a 2304×1296 con el detector
    exhaustivo tarda del orden de cientos de milisegundos por frame, y la vista
    se vuelve inusable. Reduciendo a 960 px y saltando el modo exhaustivo baja
    a unas decenas de milisegundos.

    Al capturar de verdad hay que volver a llamar a `find_corners` sobre el
    frame a resolución completa: es lo que da la precisión subpíxel que la
    calibración necesita.
    """
    alto, ancho = imagen.shape[:2]
    if ancho <= max_width:
        return find_corners(imagen, spec, refinar=False, rapido=True)

    escala = max_width / float(ancho)
    pequena = cv2.resize(
        imagen, (max_width, int(round(alto * escala))), interpolation=cv2.INTER_AREA
    )
    esquinas = find_corners(pequena, spec, refinar=False, rapido=True)
    if esquinas is None:
        return None
    return _normalizar(esquinas / escala)


def draw_corners(
    imagen: np.ndarray, spec: ChessboardSpec, esquinas: np.ndarray
) -> np.ndarray:
    """Dibuja el tablero detectado sobre una copia de la imagen."""
    salida = imagen.copy()
    cv2.drawChessboardCorners(salida, spec.pattern_size, esquinas, True)
    return salida


def corner_span(esquinas: np.ndarray, tamano: tuple[int, int]) -> float:
    """Fracción del área de la imagen que ocupa el tablero, en `[0, 1]`.

    Sirve para exigir vistas de cerca y de lejos: una calibración hecha sólo
    con el tablero pequeño y centrado estima mal la distorsión de los bordes.
    """
    pts = esquinas.reshape(-1, 2)
    ancho = float(pts[:, 0].max() - pts[:, 0].min())
    alto = float(pts[:, 1].max() - pts[:, 1].min())
    return (ancho * alto) / float(tamano[0] * tamano[1])


def corner_extent(esquinas: np.ndarray, tamano: tuple[int, int]) -> float:
    """Lado mayor del tablero como fracción del ancho de la imagen.

    Es **la medida que más determina la calidad de una calibración**. Las
    esquinas se localizan con precisión de fracciones de píxel; si el tablero
    ocupa 150 px de ancho en una imagen de 2304, ese error relativo es 30 veces
    mayor que si ocupa 800 px, y la focal queda sin determinar: el ajuste
    converge, pero a un valor que cambia varios cientos de píxeles con
    cualquier perturbación.

    Objetivo práctico: **0.30 o más**. Por debajo de 0.20 la calibración no es
    utilizable por muy bajo que parezca el RMS.
    """
    pts = esquinas.reshape(-1, 2)
    lado = max(
        float(pts[:, 0].max() - pts[:, 0].min()),
        float(pts[:, 1].max() - pts[:, 1].min()),
    )
    return lado / float(tamano[0])


def corner_movement(
    anterior: np.ndarray | None, actual: np.ndarray | None
) -> float:
    """Cuánto se movió el tablero entre dos detecciones, en píxeles.

    Devuelve la mediana del desplazamiento de las esquinas, o `inf` si no se
    pueden comparar (falta una detección, o cambió el número de esquinas).

    Sirve para no capturar frames movidos. Un frame movido no es "una vista un
    poco peor": con obturador rodante es la observación de un tablero
    deformado, y contamina el ajuste entero. Medido sobre vídeo sintético, un
    par de frames quietos da 0.0 px y un par en movimiento 38.7 px: la
    separación es amplia y un umbral de 2 px los distingue sin ambigüedad.
    """
    if anterior is None or actual is None:
        return float("inf")
    a = np.asarray(anterior).reshape(-1, 2)
    b = np.asarray(actual).reshape(-1, 2)
    if a.shape != b.shape:
        return float("inf")
    return float(np.median(np.linalg.norm(b - a, axis=1)))


def corner_centroid(esquinas: np.ndarray) -> tuple[float, float]:
    """Centro del tablero en píxeles, para medir cobertura del cuadro."""
    pts = esquinas.reshape(-1, 2)
    return float(pts[:, 0].mean()), float(pts[:, 1].mean())
