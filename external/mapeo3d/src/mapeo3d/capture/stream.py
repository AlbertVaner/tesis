"""Lectura de un stream de vídeo sin acumular latencia.

El problema que resuelve este módulo está explicado en docs/capture.md: un
`cv2.VideoCapture.read()` llamado desde el bucle principal devuelve el frame
más viejo de la cola del decodificador, no el más reciente, y el retraso crece
sin que la imagen dé ninguna señal.

La solución es un hilo dedicado que lee continuamente y conserva **sólo el
último frame**. Si el consumidor no llega a tiempo, el frame anterior se
descarta. Es lo correcto: un frame viejo no sirve para control.

Este módulo no sabe qué es una persona. Entrega frames con marca de tiempo.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

import cv2

from .urls import mask_url

log = logging.getLogger(__name__)


def _ahora() -> float:
    """Reloj para las marcas de tiempo de llegada.

    Es `perf_counter` y no `monotonic` por una razón concreta y medida: en
    Windows **`time.monotonic()` avanza a saltos de 15.6 ms**, mientras que la
    tolerancia de emparejamiento entre cámaras es de 17 ms. Con esa
    granularidad todas las marcas caen sobre una rejilla más gruesa que la
    decisión que hay que tomar con ellas, y el emparejamiento por vecino más
    cercano deja de significar nada. `perf_counter` es igual de monotónico y
    resuelve 0.1 us. Ver docs/capture.md.

    Medido en la máquina de desarrollo (Windows 11):

        monotonic      salto mínimo real  15.0000 ms
        perf_counter   salto mínimo real   0.0001 ms
    """
    return time.perf_counter()


@dataclass
class StreamStats:
    """Estadísticas de una cámara durante una sesión.

    No son un extra de depuración: `fps_recibidos` es la fuente de la
    verificación obligatoria de frame rate descrita en docs/capture.md.
    Con la visión nocturna apagada, la exposición automática puede bajar el
    frame rate por su cuenta y el síntoma es invisible.
    """

    frames_recibidos: int = 0
    frames_descartados: int = 0
    reconexiones: int = 0
    primer_frame_t: float | None = None
    ultimo_frame_t: float | None = None
    lecturas_fallidas: int = 0

    @property
    def duracion_s(self) -> float:
        if self.primer_frame_t is None or self.ultimo_frame_t is None:
            return 0.0
        return self.ultimo_frame_t - self.primer_frame_t

    @property
    def fps_recibidos(self) -> float:
        """fps medios realmente recibidos, no los declarados por la cámara."""
        if self.duracion_s <= 0 or self.frames_recibidos < 2:
            return 0.0
        return (self.frames_recibidos - 1) / self.duracion_s

    def resumen(self) -> str:
        return (
            f"{self.frames_recibidos} frames en {self.duracion_s:.2f} s "
            f"({self.fps_recibidos:.2f} fps recibidos), "
            f"{self.frames_descartados} descartados, "
            f"{self.reconexiones} reconexiones, "
            f"{self.lecturas_fallidas} lecturas fallidas"
        )


@dataclass
class _UltimoFrame:
    frame: object | None = None
    timestamp: float = 0.0
    seq: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)


class CameraStream:
    """Lector de una cámara en un hilo propio, con reconexión automática.

    Uso::

        stream = CameraStream(url, name="cam1")
        stream.start()
        try:
            while True:
                resultado = stream.read()
                if resultado is None:
                    continue          # todavía no hay frame nuevo
                frame, t = resultado
                ...
        finally:
            stream.stop()

    `read()` no bloquea nunca al hilo lector y devuelve `None` si no hay un
    frame *nuevo* desde la última llamada.
    """

    def __init__(
        self,
        url: str | int,
        name: str = "cam",
        *,
        reconnect_after_s: float = 2.0,
        open_timeout_ms: int = 5000,
        prefer_tcp: bool = True,
    ) -> None:
        self.url = url
        self.name = name
        self.reconnect_after_s = reconnect_after_s
        self.open_timeout_ms = open_timeout_ms
        self.prefer_tcp = prefer_tcp

        self.stats = StreamStats()
        self._ultimo = _UltimoFrame()
        self._ultimo_seq_leido = 0
        self._parar = threading.Event()
        self._hilo: threading.Thread | None = None
        self._resolucion: tuple[int, int] | None = None
        self._fps_declarados: float = 0.0

    # ---------------------------------------------------------------- ciclo

    def start(self) -> "CameraStream":
        if self._hilo is not None:
            return self
        self._parar.clear()
        self._hilo = threading.Thread(
            target=self._bucle, name=f"CameraStream-{self.name}", daemon=True
        )
        self._hilo.start()
        return self

    def stop(self) -> None:
        self._parar.set()
        if self._hilo is not None:
            self._hilo.join(timeout=5.0)
            self._hilo = None

    def __enter__(self) -> "CameraStream":
        return self.start()

    def __exit__(self, *_exc: object) -> None:
        self.stop()

    # --------------------------------------------------------------- lectura

    def read(self) -> tuple[object, float] | None:
        """Devuelve `(frame, timestamp)` si hay uno nuevo, o `None`.

        El timestamp es de **llegada** al PC, con reloj monotónico. No es el
        reloj de la cámara: ver docs/capture.md.
        """
        with self._ultimo.lock:
            if self._ultimo.frame is None or self._ultimo.seq == self._ultimo_seq_leido:
                return None
            self._ultimo_seq_leido = self._ultimo.seq
            return self._ultimo.frame, self._ultimo.timestamp

    def read_latest(self) -> tuple[object, float] | None:
        """Como `read()`, pero devuelve el último frame aunque ya se haya leído.

        Útil para visualización; no para el lazo de procesamiento, donde
        procesar dos veces el mismo frame falsea las estadísticas.
        """
        with self._ultimo.lock:
            if self._ultimo.frame is None:
                return None
            return self._ultimo.frame, self._ultimo.timestamp

    # ------------------------------------------------------------ propiedades

    @property
    def resolucion(self) -> tuple[int, int] | None:
        """(ancho, alto) reportados por el decodificador, o None si no hay conexión."""
        return self._resolucion

    @property
    def fps_declarados(self) -> float:
        """fps que declara el stream. NO confiar en este número: ver `stats`."""
        return self._fps_declarados

    @property
    def conectado(self) -> bool:
        return self._ultimo.frame is not None and (
            _ahora() - self._ultimo.timestamp
        ) < self.reconnect_after_s

    # ----------------------------------------------------------------- hilo

    def _abrir(self) -> cv2.VideoCapture | None:
        es_rtsp = isinstance(self.url, str) and self.url.startswith("rtsp://")
        if self.prefer_tcp and es_rtsp:
            # Fuerza TCP y reduce el buffer del decodificador. OpenCV lee estas
            # opciones de la variable de entorno; se aplican al abrir.
            import os

            os.environ.setdefault(
                "OPENCV_FFMPEG_CAPTURE_OPTIONS",
                "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay",
            )

        if isinstance(self.url, int):
            # Webcam local: backend por defecto, no FFMPEG.
            cap = cv2.VideoCapture(self.url)
        else:
            cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
        try:
            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, self.open_timeout_ms)
            cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, self.open_timeout_ms)
        except Exception:  # pragma: no cover - depende del backend
            pass
        # No todos los backends respetan BUFFERSIZE. Por eso el hilo
        # descartador es obligatorio y no una optimización.
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:  # pragma: no cover
            pass

        if not cap.isOpened():
            cap.release()
            return None

        ancho = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        alto = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if ancho and alto:
            self._resolucion = (ancho, alto)
        self._fps_declarados = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        return cap

    def _bucle(self) -> None:
        cap: cv2.VideoCapture | None = None
        ultimo_ok = _ahora()

        while not self._parar.is_set():
            if cap is None:
                cap = self._abrir()
                if cap is None:
                    log.warning(
                        "[%s] no se pudo abrir %s; reintentando",
                        self.name,
                        mask_url(self.url),
                    )
                    self._parar.wait(self.reconnect_after_s)
                    continue
                ultimo_ok = _ahora()

            ok, frame = cap.read()
            ahora = _ahora()

            if not ok or frame is None:
                self.stats.lecturas_fallidas += 1
                if ahora - ultimo_ok > self.reconnect_after_s:
                    log.warning("[%s] stream caído; reconectando", self.name)
                    cap.release()
                    cap = None
                    self.stats.reconexiones += 1
                    continue
                # Fallo transitorio: ceder un poco de CPU y reintentar.
                self._parar.wait(0.01)
                continue

            ultimo_ok = ahora
            self.stats.frames_recibidos += 1
            if self.stats.primer_frame_t is None:
                self.stats.primer_frame_t = ahora
            self.stats.ultimo_frame_t = ahora

            with self._ultimo.lock:
                # Si el consumidor no leyó el frame anterior, se pierde. Es
                # deliberado: entregar frames viejos es peor que perderlos.
                if (
                    self._ultimo.frame is not None
                    and self._ultimo.seq != self._ultimo_seq_leido
                ):
                    self.stats.frames_descartados += 1
                self._ultimo.frame = frame
                self._ultimo.timestamp = ahora
                self._ultimo.seq += 1

        if cap is not None:
            cap.release()
