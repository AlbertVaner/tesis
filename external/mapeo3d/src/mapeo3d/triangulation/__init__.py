"""Triangulación: de landmarks 2D de N vistas a puntos 3D.

Este subpaquete no sabe de RTSP ni del estimador de pose. Recibe matrices de
proyección y puntos 2D. Se prueba entero con datos sintéticos, sin cámaras.
Ver docs/triangulation.md.

`dlt` es el método desnudo; `robust` le añade ponderación, rechazo de vistas
que alucinan y umbral de aceptación; `metrics` mide la calidad del resultado
sin verdad de terreno.
"""

from .dlt import (
    ANGULO_MAX_DEG,
    ANGULO_MIN_DEG,
    MIN_VISTAS,
    angulo_utilizable,
    camera_center,
    grid_spacing,
    project,
    ray_angle_deg,
    reprojection_error,
    triangulate,
    triangulate_many,
)
from .metrics import (
    EstabilidadSegmentos,
    segment_length_stability,
    segment_lengths,
)
from .robust import (
    PESO_MINIMO,
    UMBRAL_PUNTO_PX,
    UMBRAL_VISTA_PX,
    Punto3D,
    angulo_util_deg,
    triangulate_landmarks,
    triangulate_robust,
)

__all__ = [
    "ANGULO_MAX_DEG",
    "ANGULO_MIN_DEG",
    "MIN_VISTAS",
    "PESO_MINIMO",
    "UMBRAL_PUNTO_PX",
    "UMBRAL_VISTA_PX",
    "EstabilidadSegmentos",
    "Punto3D",
    "angulo_util_deg",
    "angulo_utilizable",
    "camera_center",
    "grid_spacing",
    "project",
    "ray_angle_deg",
    "reprojection_error",
    "segment_length_stability",
    "segment_lengths",
    "triangulate",
    "triangulate_landmarks",
    "triangulate_many",
    "triangulate_robust",
]
