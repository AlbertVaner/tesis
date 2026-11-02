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

`GrabadorMulticamara` graba ademas cada camara en su propio archivo, con el
mismo reloj que la interfaz: el segundo 40 de `cam3.mp4` es el segundo 40 del
video de la interfaz y del CSV, asi que se pueden montar en paralelo al editar.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

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


#: Tamano de cada video por camara: el sub-stream de las Amcrest (640x480).
#: Un frame de otra proporcion entra con bandas, sin deformarse.
TAMANO_CAMARA = (640, 480)


def encajar(frame, tamano: tuple[int, int] = TAMANO_CAMARA, texto: str = "conectando..."):
    """`frame` dentro de `tamano` con bandas; sin frame, un cuadro negro con `texto`."""
    ancho, alto = tamano
    celda = np.zeros((alto, ancho, 3), np.uint8)
    if frame is None:
        cv2.putText(celda, texto, (24, alto // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                    (160, 160, 160), 2, cv2.LINE_AA)
        return celda
    fa, fw = frame.shape[:2]
    if (fw, fa) == (ancho, alto):
        return frame
    escala = min(ancho / fw, alto / fa)
    w, h = max(1, int(fw * escala)), max(1, int(fa * escala))
    x, y = (ancho - w) // 2, (alto - h) // 2
    celda[y:y + h, x:x + w] = cv2.resize(frame, (w, h))
    return celda


class GrabadorMulticamara:
    """Un MP4 por camara, todos con el reloj de la interfaz.

    `escribir({"cam1": frame, ...}, t)` en cada vuelta del bucle. Una camara
    que todavia no trae imagen (o la perdio) graba un cuadro negro: asi todos
    los archivos empiezan en el mismo instante y duran lo mismo.
    """

    def __init__(self, carpeta: Path, nombres, *, sufijo: str = "",
                 fps: float = FPS_VIDEO, tamano: tuple[int, int] = TAMANO_CAMARA) -> None:
        self.carpeta = Path(carpeta)
        self.tamano = tamano
        self.grabadores = {n: GrabadorVideo(self.carpeta / f"{n}{sufijo}.mp4", fps=fps)
                           for n in nombres}

    def escribir(self, frames: dict, t: float) -> None:
        for nombre, grabador in self.grabadores.items():
            grabador.escribir(encajar(frames.get(nombre), self.tamano), t)

    @property
    def rutas(self) -> list[Path]:
        return [g.ruta for g in self.grabadores.values() if g.escritos]

    def cerrar(self) -> None:
        for grabador in self.grabadores.values():
            grabador.cerrar()
