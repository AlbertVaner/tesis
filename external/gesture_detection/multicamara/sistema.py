"""El sistema multicamara completo: hilos, eleccion de camara, PTZ e imagen.

`SistemaMulticamara` junta N `Camara` (una por hilo, cada una con su pose, su
reconocedor y, si es PTZ, su seguimiento), el `SelectorCamara` y el dibujo de
la vista combinada. Lo usan:

* `probar_multicamara.py`, el banco de pruebas sin dron;
* `control_camara_dron1.py --multicamara`, que vuela con el evento de la
  camara activa.

Para lo segundo expone la interfaz minima de `cv2.VideoCapture`
(`isOpened`, `read`, `release`): `read()` devuelve la vista combinada, asi que
el bucle del controlador la trata como una camara mas.

Seguridad al cambiar de camara
------------------------------
`evento_activo()` es lo unico que debe ejecutar un dron. Si al tomar el mando
la camara nueva ya tenia un gesto en curso, ese gesto sale **sin confirmar**
hasta que pase por NO_GESTURE: un cambio de camara no puede disparar un
DESPEGAR ni un movimiento que nadie acaba de pedir. El gesto crudo se
conserva, asi que STOP sigue contando para la parada de emergencia.
"""

from __future__ import annotations

import dataclasses
import threading
import time
from dataclasses import dataclass

import cv2
import numpy as np

from contracts import Gesture, GestureEvent, VelocityIntent
from multicamara.rostro import SIN_ROSTRO, Rostro, caja_rostro, puntaje_rostro
from multicamara.selector import SelectorCamara
from pose.detector import PoseDetector
from pose.normalize import landmarks_to_array
from ptz import CamaraPTZ, ControlPTZ, ErrorPTZ, Seguidor, centro_encuadre
from recognition.body_3d_rules import Body3DRecognizer
from video_source import abrir, enmascarar, es_rtsp
from visualization.pose_overlay import draw_pose

ALTO_VIDEO = 720
ANCHO_PANEL = 440

FONDO = (24, 24, 28)
BLANCO = (238, 238, 242)
GRIS = (150, 150, 155)
VERDE = (120, 220, 140)
ROJO = (90, 90, 240)
AMBAR = (80, 200, 255)

#: Segundos entre reintentos de abrir una camara que no responde.
REINTENTO_S = 2.0


# ------------------------------------------------------------------ camaras


@dataclass(frozen=True)
class Estado:
    """Lo ultimo que vio una camara. Se reemplaza entero, nunca se modifica."""

    frame: np.ndarray | None
    evento: GestureEvent
    rostro: Rostro
    fps: float
    senal: bool
    seq: int
    escala_m: float = float("nan")
    #: Landmarks de este frame, para quien quiera reconocer otra cosa con
    #: ellos sin volver a pasar MediaPipe: 2D normalizados y mundo en metros.
    landmarks: object = None
    mundo: object = None
    #: `time.monotonic()` de cuando se proceso el frame.
    t: float = 0.0
    #: El frame se tomo con el PTZ girando: vale para el paro, no para
    #: clasificar movimiento (motion blur y movimiento aparente de las manos).
    moviendo: bool = False
    #: El frame tal como llego de la camara, sin esqueleto ni recuadro: para
    #: grabar imagen limpia (`GrabadorMulticamara`).
    crudo: object = None
    #: `time.time()` de cuando llego el frame, en el reloj de pared: es el que
    #: comparte con el stream principal grabado por `grabar_camaras_hd.py`.
    t_captura: float = 0.0


class Camara(threading.Thread):
    """Lee una fuente, detecta la pose y reconoce gestos en su propio hilo.

    Con `ptz`, ademas mueve su pan/tilt para seguir a la persona, con la misma
    politica que `seguir_persona.py` (`ptz/seguidor.py`): pasos cortos,
    confirmados en la imagen, y sin girar mientras hay un gesto en curso salvo
    que la persona se vaya a salir del cuadro. Cada camara sigue por su
    cuenta, sea o no la activa: asi la que tome el mando ya tiene a la persona
    encuadrada.
    """

    def __init__(self, nombre: str, fuente, *, ptz: bool = False,
                 dry_run: bool = False) -> None:
        super().__init__(name=f"Camara-{nombre}", daemon=True)
        self.nombre = nombre
        self.fuente = fuente
        self.ptz = ptz
        self.dry_run = dry_run
        self.seguir = threading.Event()
        self.seguir.set()
        #: Lo pone quien reconoce gestos que esta camara no ve por si sola
        #: (un segmento dinamico, la X del paro): mientras dure, no gira.
        self.gesto_externo = threading.Event()
        self.ptz_estado = "sin PTZ"
        self._reconocedor = Body3DRecognizer(source=nombre)
        self._lock = threading.Lock()
        self._estado = Estado(None, self._reconocedor.update(None), SIN_ROSTRO, 0.0, False, 0)
        self._parar = threading.Event()
        self._reiniciar = threading.Event()

    @property
    def estado(self) -> Estado:
        with self._lock:
            return self._estado

    def reiniciar(self) -> None:
        self._reiniciar.set()

    def parar(self) -> None:
        self._parar.set()

    def _publicar(self, **cambios) -> None:
        with self._lock:
            e = self._estado
            self._estado = dataclasses.replace(e, seq=e.seq + 1, **cambios)

    def _abrir_ptz(self):
        """`(seguidor, control)` o `(None, None)` si esta camara no se mueve."""
        if not self.ptz or not es_rtsp(self.fuente):
            return None, None
        camara = CamaraPTZ.desde_rtsp(self.fuente, dry_run=self.dry_run)
        try:
            pos = camara.posicion()
        except ErrorPTZ as exc:
            print(f"[{self.nombre}] PTZ no responde, sigue sin moverse: {exc}", flush=True)
            self.ptz_estado = "PTZ sin respuesta"
            return None, None
        if pos:
            print(f"[{self.nombre}] PTZ en pan {pos[0]:.1f} tilt {pos[1]:.1f}"
                  + ("  [DRY-RUN]" if self.dry_run else ""), flush=True)
        self.ptz_estado = "siguiendo"
        return Seguidor(), ControlPTZ(camara)

    def run(self) -> None:
        # MediaPipe se construye en el hilo que lo usa.
        detector = PoseDetector()
        seguidor, control = self._abrir_ptz()
        captura = None
        fps = 0.0
        anterior = time.monotonic()
        try:
            while not self._parar.is_set():
                if captura is None or not captura.isOpened():
                    if captura is not None:
                        captura.release()
                    captura = abrir(self.fuente)
                    if not captura.isOpened():
                        print(f"[{self.nombre}] no abre {enmascarar(self.fuente)}; "
                              f"reintento en {REINTENTO_S:.0f} s", flush=True)
                        self._publicar(senal=False, rostro=SIN_ROSTRO)
                        self._parar.wait(REINTENTO_S)
                        continue

                ok, crudo = captura.read()
                t_captura = time.time()
                if not ok:
                    self._publicar(senal=False, rostro=SIN_ROSTRO,
                                   evento=self._reconocedor.update(None))
                    if not es_rtsp(self.fuente):
                        captura.release()   # archivo acabado o webcam caida
                        captura = None
                    continue

                if self._reiniciar.is_set():
                    self._reiniciar.clear()
                    self._reconocedor.reset()

                frame = crudo.copy()
                alto, ancho = frame.shape[:2]
                landmarks, mundo = detector.process_full(frame)
                evento = self._reconocedor.update(mundo)
                rostro = puntaje_rostro(landmarks, ancho, alto)
                ahora = time.monotonic()

                moviendo = False
                if control is not None:
                    self._seguir(seguidor, control, landmarks, evento, ahora)
                    moviendo = seguidor.en_movimiento(ahora) or control.dando_la_vuelta
                    if control.dando_la_vuelta:
                        # Girando casi una vuelta: la imagen no vale para
                        # elegir camara. Que no la gane un frame borroso.
                        rostro = SIN_ROSTRO

                draw_pose(frame, landmarks, detector.connections)
                _dibujar_rostro(frame, landmarks, rostro)

                fps = 0.9 * fps + 0.1 / max(ahora - anterior, 1e-3)
                anterior = ahora
                self._publicar(frame=frame, evento=evento, rostro=rostro, fps=fps,
                               senal=True, escala_m=self._reconocedor.scale.scale_m,
                               landmarks=landmarks, mundo=mundo, t=ahora, moviendo=moviendo,
                               crudo=crudo, t_captura=t_captura)
        finally:
            if control is not None:
                # Nunca dejar el motor girando.
                control.pedir(seguidor.detener())
                control.cerrar()
            if captura is not None:
                captura.release()
            detector.close()

    def _seguir(self, seguidor, control, landmarks, evento, ahora) -> None:
        if not self.seguir.is_set():
            control.pedir(seguidor.detener(ahora))
            self.ptz_estado = "pausado"
            return
        puntos, visibilidad = landmarks_to_array(landmarks)
        centro = centro_encuadre(puntos, visibilidad, seguidor.ajustes) if puntos.size else None
        en_curso = evento.gesture is not Gesture.NO_GESTURE or self.gesto_externo.is_set()
        control.pedir(seguidor.decidir_con_gesto(centro, ahora, gesto_en_curso=en_curso))
        if control.dando_la_vuelta:
            self.ptz_estado = "dando la vuelta"
        elif control.tope:
            self.ptz_estado = f"tope {control.tope}"
        else:
            self.ptz_estado = f"PTZ {seguidor.activo}" if seguidor.activo else "siguiendo"


# ------------------------------------------------------------- enclavamiento


def sin_gesto(fuente: str = "multicamara") -> GestureEvent:
    return GestureEvent(Gesture.NO_GESTURE, 0.0, False, False, VelocityIntent(),
                        time.monotonic(), source=fuente)


class Enclavamiento:
    """Tras un cambio de camara, lo que ya estaba confirmado no se ejecuta.

    Queda sin confirmar hasta que la camara nueva vea NO_GESTURE. Ver el
    docstring del modulo.
    """

    def __init__(self) -> None:
        self.camara: str | None = None
        self.bloqueado = False

    def filtrar(self, camara: str | None, evento: GestureEvent) -> GestureEvent:
        if camara != self.camara:
            self.camara = camara
            self.bloqueado = evento.gesture is not Gesture.NO_GESTURE
        elif evento.gesture is Gesture.NO_GESTURE:
            self.bloqueado = False
        if self.bloqueado and evento.confirmed:
            return dataclasses.replace(evento, confirmed=False)
        return evento


# ------------------------------------------------------------------- sistema


class SistemaMulticamara:
    """N camaras, la activa y la vista combinada. Tambien hace de `VideoCapture`."""

    def __init__(self, fuentes: list[tuple[str, object]], *, ptz: bool = True,
                 dry_run: bool = False, selector: SelectorCamara | None = None) -> None:
        self.camaras = [Camara(n, f, ptz=ptz, dry_run=dry_run) for n, f in fuentes]
        self.selector = selector or SelectorCamara()
        self.estados: dict[str, Estado] = {c.nombre: c.estado for c in self.camaras}
        self.activa: str | None = None
        self._enclavamiento = Enclavamiento()
        self._gesto_externo = False
        self._iniciado = False
        self._ultimo_seq: dict[str, int] = {}
        #: Alto que `read()` deja libre sobre las miniaturas, para el panel
        #: de texto que el llamante pinte encima.
        self.alto_cabecera = 0

    # -------------------------------------------------------------- ciclo

    def iniciar(self) -> "SistemaMulticamara":
        if not self._iniciado:
            for cam in self.camaras:
                cam.start()
            self._iniciado = True
        return self

    def actualizar(self) -> str | None:
        """Lee el ultimo estado de cada camara y decide la activa."""
        self.estados = {c.nombre: c.estado for c in self.camaras}
        puntajes = {n: e.rostro.puntaje for n, e in self.estados.items() if e.senal}
        anterior = self.activa
        en_gesto = self._gesto_externo or (
            anterior in self.estados
            and self.estados[anterior].evento.gesture is not Gesture.NO_GESTURE)
        self.activa = self.selector.actualizar(puntajes, en_gesto=en_gesto)
        return self.activa

    def gesto_en_curso(self, en_curso: bool) -> None:
        """Avisa de un gesto que el sistema no ve por si solo (dinamico, paro).

        Mientras dure, la camara activa no cambia por preferencia y no gira;
        las demas siguen moviendose para tener encuadrado al operador.
        """
        self._gesto_externo = en_curso
        for cam in self.camaras:
            if en_curso and cam.nombre == self.activa:
                cam.gesto_externo.set()
            else:
                cam.gesto_externo.clear()

    def evento_activo(self) -> GestureEvent:
        """El evento que se puede ejecutar: el de la activa, con el enclavamiento."""
        if self.activa not in self.estados:
            return self._enclavamiento.filtrar(None, sin_gesto())
        return self._enclavamiento.filtrar(self.activa, self.estados[self.activa].evento)

    @property
    def escala_m(self) -> float:
        e = self.estados.get(self.activa)
        return e.escala_m if e is not None else float("nan")

    def fijar(self, nombre: str | None) -> None:
        if nombre is None or nombre in self.estados:
            self.selector.fijar(nombre)

    def alternar_seguimiento(self) -> bool:
        """Pausa o reanuda el PTZ de todas. Devuelve `True` si queda siguiendo."""
        pausar = self.siguiendo
        for cam in self.camaras:
            (cam.seguir.clear if pausar else cam.seguir.set)()
        return not pausar

    @property
    def siguiendo(self) -> bool:
        return all(c.seguir.is_set() for c in self.camaras)

    def reiniciar(self) -> None:
        for cam in self.camaras:
            cam.reiniciar()

    def cerrar(self) -> None:
        for cam in self.camaras:
            cam.parar()
        for cam in self.camaras:
            if cam.is_alive():
                cam.join(timeout=3.0)

    # ------------------------------------------------ interfaz VideoCapture

    def isOpened(self) -> bool:  # noqa: N802 - nombre impuesto por cv2
        return True

    def read(self, espera_s: float = 0.1):
        """`(True, vista)`. Espera hasta `espera_s` a que alguna camara traiga algo nuevo."""
        self.iniciar()
        limite = time.monotonic() + espera_s
        while time.monotonic() < limite:
            seqs = {c.nombre: c.estado.seq for c in self.camaras}
            if seqs != self._ultimo_seq:
                self._ultimo_seq = seqs
                break
            time.sleep(0.003)
        self.actualizar()
        return True, self.componer(alto_cabecera=self.alto_cabecera)

    def release(self) -> None:
        self.cerrar()

    # ------------------------------------------------------------- dibujo

    def componer(self, cabecera=None, alto_cabecera: int = 0):
        """Activa en grande a la izquierda y todas en miniatura a la derecha.

        `cabecera(panel)` dibuja lo que el llamante quiera en los primeros
        `alto_cabecera` pixeles del panel derecho.
        """
        estado = self.estados.get(self.activa) if self.activa else None
        principal = estado.frame if estado is not None else None
        if principal is None:
            principal = np.full((ALTO_VIDEO, ALTO_VIDEO * 4 // 3, 3), FONDO, np.uint8)
            _texto(principal, "Nadie a la vista", (40, ALTO_VIDEO // 2), GRIS, 1.0, 2)
        else:
            fa, fw = principal.shape[:2]
            principal = cv2.resize(principal, (int(fw * ALTO_VIDEO / fa), ALTO_VIDEO))

        panel = np.full((ALTO_VIDEO, ANCHO_PANEL, 3), FONDO, np.uint8)
        if cabecera is not None:
            cabecera(panel)
        zona_alto = ALTO_VIDEO - alto_cabecera
        columnas, filas = rejilla(len(self.camaras), ANCHO_PANEL, zona_alto)
        cw, ch = ANCHO_PANEL // columnas, zona_alto // filas
        for i, cam in enumerate(self.camaras):
            fila, col = divmod(i, columnas)
            x, y = col * cw, alto_cabecera + fila * ch
            panel[y:y + ch, x:x + cw] = _miniatura(cam, self.estados[cam.nombre],
                                                   cw, ch, cam.nombre == self.activa)
        return np.hstack([principal, panel])


# -------------------------------------------------------------------- dibujo


def _texto(img, txt, xy, color=BLANCO, escala=0.46, grosor=1) -> None:
    cv2.putText(img, txt, xy, cv2.FONT_HERSHEY_SIMPLEX, escala, color, grosor, cv2.LINE_AA)


def _dibujar_rostro(frame, landmarks, rostro: Rostro) -> None:
    """Recuadro de la cara con su puntaje: verde si manda, ambar si se ve a medias."""
    alto, ancho = frame.shape[:2]
    caja = caja_rostro(landmarks, ancho, alto)
    if caja is None:
        return
    color = VERDE if rostro.puntaje >= 0.5 else AMBAR if rostro.puntaje >= 0.2 else ROJO
    x0, y0, x1, y1 = caja
    cv2.rectangle(frame, (x0, y0), (x1, y1), color, 2)
    _texto(frame, f"rostro {rostro.puntaje:.2f}", (x0, max(14, y0 - 6)), color, 0.5)


def _encajar(frame, ancho: int, alto: int):
    """`frame` dentro de `ancho` x `alto` sin deformarlo, con bandas."""
    celda = np.full((alto, ancho, 3), FONDO, np.uint8)
    if frame is None:
        return celda
    fa, fw = frame.shape[:2]
    escala = min(ancho / fw, alto / fa)
    w, h = max(1, int(fw * escala)), max(1, int(fa * escala))
    x, y = (ancho - w) // 2, (alto - h) // 2
    celda[y:y + h, x:x + w] = cv2.resize(frame, (w, h))
    return celda


def _miniatura(cam: Camara, estado: Estado, ancho, alto, activa: bool):
    celda = _encajar(estado.frame, ancho, alto)
    if not estado.senal:
        celda //= 3
        _texto(celda, "SIN SENAL", (10, alto // 2), ROJO, 0.6, 2)
    color = VERDE if activa else GRIS
    cv2.rectangle(celda, (0, 0), (ancho - 1, alto - 1), color, 4 if activa else 1)
    cv2.rectangle(celda, (0, 0), (ancho, 24), FONDO, -1)
    _texto(celda, f"{cam.nombre}  rostro {estado.rostro.puntaje:.2f}  {estado.fps:4.1f} fps",
           (8, 17), color, 0.44)
    # Barra del puntaje de rostro, a lo ancho del pie.
    cv2.rectangle(celda, (0, alto - 6), (int(ancho * estado.rostro.puntaje), alto), color, -1)
    if cam.ptz:
        _texto(celda, cam.ptz_estado, (8, 42), GRIS, 0.42)
    if estado.evento.gesture is not Gesture.NO_GESTURE:
        _texto(celda, estado.evento.gesture.value, (8, alto - 14),
               VERDE if estado.evento.confirmed else AMBAR, 0.5, 1)
    return celda


def rejilla(n: int, ancho: int, alto: int) -> tuple[int, int]:
    """Columnas y filas que dejan las miniaturas mas grandes para `n` camaras."""
    mejor = (1, n)
    mejor_lado = 0.0
    for columnas in range(1, n + 1):
        filas = -(-n // columnas)
        lado = min(ancho / columnas / 4, alto / filas / 3)   # celdas 4:3
        if lado > mejor_lado:
            mejor, mejor_lado = (columnas, filas), lado
    return mejor
