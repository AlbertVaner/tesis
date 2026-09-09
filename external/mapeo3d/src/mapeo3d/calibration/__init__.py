"""Calibración: intrínsecos, extrínsecos y matrices de proyección.

Este subpaquete es la **única fuente de matrices de cámara** del repositorio.
Ningún otro módulo construye una matriz de proyección por su cuenta ni asume
un orden de cámaras. Ver docs/calibration.md.
"""

from .board import (
    ChessboardSpec,
    corner_centroid,
    corner_extent,
    corner_movement,
    corner_span,
    draw_corners,
    find_corners,
    find_corners_preview,
)
from .extrinsics import (
    EXTENT_MINIMO_ESTEREO,
    MINIMO_BLOQUE,
    MINIMO_PARES,
    UMBRAL_COHERENCIA_PX,
    Coherencia,
    ParesIncoherentes,
    StereoExtrinsics,
    analizar_coherencia,
    calibrate_stereo,
    pose_relativa_de_un_par,
)
from .intrinsics import (
    COHERENCIA_SISTEMATICA,
    EXTENT_MINIMO,
    EXTENT_OBJETIVO,
    RMS_ACEPTABLE_PX,
    CameraIntrinsics,
    calibrate,
    cargar_puntos,
    diagnosticar,
    escribir_reporte,
    guardar_puntos,
    resumen_vistas,
)

__all__ = [
    "EXTENT_MINIMO_ESTEREO",
    "MINIMO_BLOQUE",
    "MINIMO_PARES",
    "UMBRAL_COHERENCIA_PX",
    "Coherencia",
    "ParesIncoherentes",
    "analizar_coherencia",
    "pose_relativa_de_un_par",
    "StereoExtrinsics",
    "calibrate_stereo",
    "CameraIntrinsics",
    "ChessboardSpec",
    "COHERENCIA_SISTEMATICA",
    "EXTENT_MINIMO",
    "EXTENT_OBJETIVO",
    "RMS_ACEPTABLE_PX",
    "calibrate",
    "cargar_puntos",
    "diagnosticar",
    "corner_centroid",
    "corner_extent",
    "corner_movement",
    "corner_span",
    "draw_corners",
    "escribir_reporte",
    "guardar_puntos",
    "resumen_vistas",
    "find_corners",
    "find_corners_preview",
]
