"""Estimación de landmarks corporales 2D, una imagen a la vez.

Este subpaquete **no sabe que existen varias cámaras** ni cómo se triangula:
recibe una imagen y devuelve landmarks normalizados con su confianza. La
agregación multivista es de `triangulation/`. Ver AGENTS.md.

`detector` importa MediaPipe de forma perezosa, así que `landmarks` puede
usarse —y probarse— sin tenerlo instalado.
"""

from .canonical import (
    CALENTAMIENTO,
    CONDICION_MINIMA,
    EstimadorDeEscala,
    MarcoCorporal,
    canonicalizar,
    canonicalizar_secuencia,
    escala_de_sesion,
    marco_corporal,
    normalizar,
    rasgos_de_sesion,
)
from .eventos import (
    FACTOR_SALIDA,
    HUECO_MAXIMO_S,
    MIN_DURACION_S,
    Episodio,
    detectar_episodios,
    distancia,
    rapidez,
    umbral_por_percentil,
)
from .draw import (
    COLOR_DER,
    COLOR_IZQ,
    SUELO_M,
    a_escena,
    camara_orbital,
    dibujar_esqueleto_2d,
    dibujar_esqueleto_3d,
    dibujar_rejilla,
    proyectar,
)
from .quality import (
    CLAVE,
    MARGEN,
    Encuadre,
    Jitter,
    evaluar_encuadre,
    jitter_en_reposo,
)
from .landmarks import (
    CONEXIONES,
    HUESOS,
    INDICE,
    N_LANDMARKS,
    NOMBRES,
    Landmarks2D,
    pares_de_conexiones,
    pares_de_huesos,
)

__all__ = [
    "FACTOR_SALIDA",
    "HUECO_MAXIMO_S",
    "MIN_DURACION_S",
    "Episodio",
    "detectar_episodios",
    "distancia",
    "rapidez",
    "umbral_por_percentil",
    "CALENTAMIENTO",
    "CONDICION_MINIMA",
    "EstimadorDeEscala",
    "MarcoCorporal",
    "canonicalizar",
    "canonicalizar_secuencia",
    "escala_de_sesion",
    "marco_corporal",
    "normalizar",
    "rasgos_de_sesion",
    "COLOR_DER",
    "COLOR_IZQ",
    "SUELO_M",
    "a_escena",
    "camara_orbital",
    "dibujar_esqueleto_2d",
    "dibujar_esqueleto_3d",
    "dibujar_rejilla",
    "proyectar",
    "CLAVE",
    "MARGEN",
    "Encuadre",
    "Jitter",
    "evaluar_encuadre",
    "jitter_en_reposo",
    "CONEXIONES",
    "HUESOS",
    "INDICE",
    "NOMBRES",
    "N_LANDMARKS",
    "Landmarks2D",
    "pares_de_conexiones",
    "pares_de_huesos",
    "ModeloNoEncontrado",
    "PoseDetector",
    "resolver_modelo",
]


def __getattr__(nombre: str):
    """Difiere la importación de MediaPipe hasta que se pida el detector."""
    if nombre in ("PoseDetector", "ModeloNoEncontrado", "resolver_modelo"):
        from . import detector

        return getattr(detector, nombre)
    raise AttributeError(f"module {__name__!r} has no attribute {nombre!r}")
