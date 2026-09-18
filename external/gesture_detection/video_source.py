"""Fuentes de video para los probadores: webcam, archivo o camara IP.

Una camara IP por RTSP no se puede leer con `cv2.VideoCapture` a secas, por
dos razones que se ven distinto pero rompen igual:

1. **OpenCV negocia UDP por defecto.** Sobre Wi-Fi eso significa paquetes
   perdidos sin retransmision: la imagen se pixela y los macrobloques
   danados se arrastran hasta el siguiente I-frame. Se arregla forzando TCP
   por `OPENCV_FFMPEG_CAPTURE_OPTIONS`, que hay que poner en el entorno
   *antes* de construir el `VideoCapture`.

2. **La lectura sincrona acumula latencia sin limite.** Con una webcam el
   driver descarta los frames viejos; por RTSP se encolan. Si el bucle de
   vision va mas lento que la camara, el retraso crece hasta hacer inutil
   cualquier prueba en vivo. Por eso `CamaraIP` lee en un hilo propio y
   **conserva solo el ultimo frame**: los intermedios se pierden a
   proposito, que es justo lo que se quiere en tiempo real.

3. **El decodificador H.264 de FFmpeg retrasa un frame por hilo.** OpenCV
   abre el decodificador con tantos hilos como nucleos tiene el PC, en modo
   *frame threading*: cada hilo decodifica un frame distinto y la salida se
   entrega `hilos - 1` frames despues de recibirla. En un PC de 8 nucleos son
   7 frames, unos 230 ms a 30 fps, sin que el ancho de banda ni la camara
   tengan nada que ver. Un solo hilo decodifica 720p a 30 fps de sobra y
   entrega cada frame en cuanto llega. Se fija con `CAP_PROP_N_THREADS`
   (OpenCV >= 4.7).

Con esos tres puntos, el resto de la latencia la pone el **encoder de la
camara**, y ahi lo que cuenta es usar el sub-stream (`subtype=1`) sin audio:
ver `configurar_camara.py`.

`abrir()` devuelve siempre un objeto con la interfaz minima de
`cv2.VideoCapture` (`isOpened`, `read`, `release`), asi que los bucles que
ya existian no cambian.

Nota de arquitectura: `external/mapeo3d/src/mapeo3d/capture/stream.py`
resuelve exactamente esto y estaria bien reutilizarlo, pero el contrato de
`external/mapeo3d/AGENTS.md` prohibe que este subsistema lo importe hasta
que la tarea T-002 del vault defina el contrato de datos. De ahi la
implementacion propia y deliberadamente minima.
"""

from __future__ import annotations

import os
import re
import threading
import time

import cv2

# Para enmascarar credenciales antes de mostrar o registrar una URL.
_CREDENCIALES = re.compile(r"://([^:/@]+):([^@/]+)@")

# TCP en vez de UDP, y sin buffer de decodificacion.
OPCIONES_RTSP = "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay"

# Hilos del decodificador. Ver el punto 3 del docstring del modulo.
HILOS_DECODIFICADOR = 1


def enmascarar(fuente) -> str:
    """Oculta usuario y contrasena de una URL RTSP.

    Nunca mostrar ni registrar una fuente sin pasarla por aqui: las URLs de
    camara llevan las credenciales en claro.
    """
    return _CREDENCIALES.sub("://***:***@", str(fuente))


def es_rtsp(fuente) -> bool:
    return isinstance(fuente, str) and fuente.lower().startswith(("rtsp://", "rtsps://"))


def _parametros_apertura() -> list[int]:
    """Parametros `(propiedad, valor)` para `cv2.VideoCapture`.

    `CAP_PROP_N_THREADS` solo existe desde OpenCV 4.7; en uno anterior se
    abre sin el, con la latencia extra de los hilos pero sin fallar.
    """
    prop = getattr(cv2, "CAP_PROP_N_THREADS", None)
    if prop is None:
        return []
    return [int(prop), HILOS_DECODIFICADOR]


class CamaraIP:
    """Lector RTSP en un hilo propio que conserva solo el ultimo frame."""

    def __init__(self, url: str, *, espera_s: float = 5.0) -> None:
        # Tiene que estar en el entorno antes de construir el VideoCapture.
        os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", OPCIONES_RTSP)
        self.url = url
        self.espera_s = espera_s
        self._cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG, _parametros_apertura())
        try:
            self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:  # pragma: no cover - depende del backend
            pass

        self._lock = threading.Lock()
        self._frame = None
        self._seq = 0
        self._leido = 0
        self._parar = threading.Event()
        self._hilo: threading.Thread | None = None
        if self._cap.isOpened():
            self._hilo = threading.Thread(
                target=self._bucle, name="CamaraIP", daemon=True
            )
            self._hilo.start()

    def _bucle(self) -> None:
        while not self._parar.is_set():
            ok, frame = self._cap.read()
            if not ok:
                time.sleep(0.01)
                continue
            with self._lock:
                self._frame = frame
                self._seq += 1

    # ------------------------------------------------ interfaz VideoCapture

    def isOpened(self) -> bool:  # noqa: N802 - nombre impuesto por cv2
        return self._cap.isOpened()

    def read(self):
        """`(ok, frame)` con el ultimo frame NUEVO.

        Espera hasta `espera_s` a que llegue uno; si no llega, devuelve
        `(False, None)` y el bucle que la usa termina, igual que haria un
        `VideoCapture` al acabarse un archivo.
        """
        limite = time.monotonic() + self.espera_s
        while time.monotonic() < limite:
            with self._lock:
                if self._frame is not None and self._seq != self._leido:
                    self._leido = self._seq
                    return True, self._frame
            time.sleep(0.002)
        return False, None

    def release(self) -> None:
        self._parar.set()
        if self._hilo is not None:
            self._hilo.join(timeout=2.0)
            self._hilo = None
        self._cap.release()


def abrir(fuente):
    """Abre webcam (indice), archivo (ruta) o camara IP (`rtsp://...`)."""
    if es_rtsp(fuente):
        return CamaraIP(fuente)
    return cv2.VideoCapture(fuente)
