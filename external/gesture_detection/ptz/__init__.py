"""Seguimiento de la persona con una camara IP pan/tilt.

Dos piezas separadas a proposito:

* `seguidor`: la politica (donde esta la persona -> hacia donde mover). Pura,
  sin red y sin MediaPipe, y por tanto probable sin hardware.
* `cliente`: el transporte HTTP hacia la camara Amcrest.
* `control`: aplica las ordenes en un hilo aparte, porque una peticion
  HTTP tarda ~300 ms y bloquear el bucle de vision con eso arruina el
  seguimiento.

La app que las compone es `seguir_persona.py`, en la raiz del subsistema.
"""

from .cliente import CamaraPTZ, ErrorPTZ, describir_error, resumen_capacidades
from .control import ControlPTZ
from .seguidor import (
    ENCUADRES,
    Ajustes,
    Orden,
    Seguidor,
    centro_encuadre,
    centro_torso,
    decidir_con_gesto,
    velocidad_para,
)

__all__ = [
    "ENCUADRES",
    "Ajustes",
    "CamaraPTZ",
    "ControlPTZ",
    "ErrorPTZ",
    "describir_error",
    "Orden",
    "Seguidor",
    "centro_encuadre",
    "centro_torso",
    "decidir_con_gesto",
    "resumen_capacidades",
    "velocidad_para",
]
