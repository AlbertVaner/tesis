"""Captura de vídeo: clientes RTSP, marcas de tiempo y sincronización.

Este subpaquete no sabe qué es una persona. Entrega frames con marca de
tiempo de llegada y no acumula latencia. Ver docs/capture.md.
"""

from .config import (
    CameraConfig,
    CaptureConfig,
    Config,
    ConfigNotFound,
    find_config,
    load_config,
)
from .latency import (
    UMBRAL_SIGMA,
    Latencia,
    brillo,
    detectar_flanco,
)
from .probe import (
    PUERTO_RTSP,
    Sondeo,
    cabecera_autorizacion,
    describe,
    escanear,
    prefijo_local,
    puerto_abierto,
    sondear,
)
from .stream import CameraStream, StreamStats
from .sync import (
    ESPERA_MAXIMA_S,
    HISTORIA,
    TOLERANCIA_S,
    ConjuntoSincronizado,
    MultiCameraSync,
    SyncStats,
    VistaSincronizada,
)
from .urls import RTSP_PATHS, UnknownCameraModel, build_rtsp_url, mask_url

__all__ = [
    "PUERTO_RTSP",
    "Sondeo",
    "cabecera_autorizacion",
    "describe",
    "escanear",
    "prefijo_local",
    "puerto_abierto",
    "sondear",
    "Latencia",
    "UMBRAL_SIGMA",
    "brillo",
    "detectar_flanco",
    "ESPERA_MAXIMA_S",
    "HISTORIA",
    "TOLERANCIA_S",
    "ConjuntoSincronizado",
    "MultiCameraSync",
    "SyncStats",
    "VistaSincronizada",
    "CameraConfig",
    "CameraStream",
    "CaptureConfig",
    "Config",
    "ConfigNotFound",
    "RTSP_PATHS",
    "StreamStats",
    "UnknownCameraModel",
    "build_rtsp_url",
    "find_config",
    "load_config",
    "mask_url",
]
