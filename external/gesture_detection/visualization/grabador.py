"""Grabar en video lo que se muestra en la ventana, a velocidad real.

Por que no basta con `cv2.VideoWriter.write(frame)` en cada vuelta
------------------------------------------------------------------
Un archivo de video tiene una tasa de cuadros **fija**, y el bucle de vision
no: va a 22-30 fps segun lo que cueste cada frame, y se para varios segundos
cuando la camara IP da la vuelta. Escribiendo un cuadro por vuelta, un vuelo de
dos minutos sale de minuto y medio o de tres, y lo que se ve ya no coincide con
el CSV de la sesion. Aqui cada frame se escribe **tantas veces como haga falta
para que el video vaya al ritmo del reloj**: si el bucle se retrasa se repite
el ultimo cuadro, y si va mas rapido que el video se descarta alguno.

Graba el lienzo tal como se ensena (imagen de la camara, esqueleto y panel),
que es la interfaz. No graba el resto del escritorio.
"""

from __future__ import annotations

from pathlib import Path

import cv2

FPS_VIDEO = 20.0
#: Tope de cuadros repetidos de una vez: tras una pausa larga no se rellena el
#: hueco entero de golpe, que congelaria el bucle escribiendo a disco.
MAX_REPETIDOS = 60


def cuadros_pendientes(t: float, t0: float, escritos: int, fps: float = FPS_VIDEO) -> int:
    """Cuantas veces hay que escribir el frame de `t` para seguir al reloj."""
    debidos = int((t - t0) * fps) + 1
    return max(0, min(MAX_REPETIDOS, debidos - escritos))


class GrabadorVideo:
    """`escribir(frame, t)` en cada vuelta del bucle; `cerrar()` al salir."""

    def __init__(self, ruta: Path, *, fps: float = FPS_VIDEO) -> None:
        self.ruta = Path(ruta)
        self.fps = float(fps)
        self.escritos = 0
        self._writer = None
        self._t0: float | None = None
        self._tamano: tuple[int, int] | None = None

    def escribir(self, frame, t: float) -> None:
        alto, ancho = frame.shape[:2]
        if self._writer is None:
            self.ruta.parent.mkdir(parents=True, exist_ok=True)
            self._tamano = (ancho, alto)
            self._writer = cv2.VideoWriter(str(self.ruta), cv2.VideoWriter_fourcc(*"mp4v"),
                                           self.fps, self._tamano)
            self._t0 = t
            if not self._writer.isOpened():
                raise RuntimeError(f"no se pudo abrir el video {self.ruta}")
        if (ancho, alto) != self._tamano:
            frame = cv2.resize(frame, self._tamano)        # el contenedor no admite otro tamano
        for _ in range(cuadros_pendientes(t, self._t0, self.escritos, self.fps)):
            self._writer.write(frame)
            self.escritos += 1

    @property
    def duracion_s(self) -> float:
        return self.escritos / self.fps

    def cerrar(self) -> None:
        if self._writer is not None:
            self._writer.release()
            self._writer = None
