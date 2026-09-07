"""Contrato entre la visión y los controladores.

El vocabulario vive aquí y en ningún otro sitio. Antes cada consumidor
—`gesture_detector.py`, `hand_gesture_detector.py`, el controlador de cámara y
el panel web— repetía sus propias cadenas, y por eso convivían `DESPEGUE` y
`DESPEGAR` para la misma orden.

Dos reglas que conviene no romper:

1. **La visión nunca produce m/s.** Produce intención normalizada en `[-1, 1]`.
   Los límites físicos (`SPEED_XY_M_S`, `MAX_HEIGHT_M`) son del controlador,
   que es quien conoce el dron y el espacio de vuelo.
2. **`confirmed=False` significa «no ejecutar».** Sirve para pintar en pantalla
   y para el CSV, nunca para mover el dron.

Ver `docs/agents/gesture_pipeline.md` §4.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Gesture(str, Enum):
    """Vocabulario único, común al detector 2D y al 3D."""

    NO_GESTURE = "NO_GESTURE"

    # Canal continuo: un brazo extendido señala hacia dónde ir.
    ARRIBA = "ARRIBA"
    ABAJO = "ABAJO"
    ADELANTE = "ADELANTE"
    ATRAS = "ATRAS"
    IZQUIERDA = "IZQUIERDA"
    DERECHA = "DERECHA"

    # Canal de eventos: las dos manos cambian el estado del vuelo.
    DESPEGAR = "DESPEGAR"
    ATERRIZAR = "ATERRIZAR"
    STOP = "STOP"


#: Gestos que cambian el estado del vuelo. Se confirman por tiempo, no se
#: repiten mientras se sostienen, y el controlador los trata como eventos.
GESTOS_DE_ESTADO = frozenset(
    {Gesture.DESPEGAR, Gesture.ATERRIZAR, Gesture.STOP}
)

@dataclass(frozen=True)
class VelocityIntent:
    """Canal continuo, en el marco del cuerpo del operador.

    Unidades normalizadas `[-1, 1]`. Los ejes son los del dron —`vx` adelante,
    `vy` a la izquierda, `vz` arriba— porque es lo que consume
    `MotionCommander.start_linear_motion()`, pero la referencia angular es la
    del **operador**: apuntar «adelante» significa hacia donde mira quien hace
    el gesto, no hacia donde apunta el dron. Alinear ambas cosas es trabajo del
    controlador, que es quien sabe el rumbo del dron.
    """

    vx: float = 0.0
    vy: float = 0.0
    vz: float = 0.0

    @property
    def quieto(self) -> bool:
        return max(abs(self.vx), abs(self.vy), abs(self.vz)) < 1e-6


@dataclass(frozen=True)
class GestureEvent:
    """Salida única del subsistema de visión."""

    gesture: Gesture
    confidence: float
    confirmed: bool                 #: pasó la persistencia temporal
    engaged: bool                   #: el operador está en modo control
    velocity: VelocityIntent
    timestamp: float                #: `time.monotonic()` de la captura
    source: str = "webcam"          #: "webcam" | "ipcam_1" | ...
    scores: dict = field(default_factory=dict)
    landmark_quality: float = 0.0   #: visibilidad media de los landmarks clave
