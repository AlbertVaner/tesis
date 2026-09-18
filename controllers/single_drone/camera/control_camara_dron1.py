"""Control de un Crazyflie por camara: reconocedor, backend y dron elegibles.

Por defecto vuela el Dron 1; `--dron 2` cambia enlace de radio, topico mocap
y nombre en el CSV del backend (util para comparar los dos aparatos con el
mismo controlador). Un solo bucle de camara para los tres reconocedores y los
dos backends:

    --reconocedor cuerpo       vocabulario 3D estatico de cuerpo entero, MediaPipe Pose  [por defecto]
    --reconocedor manos        gestos de una mano en 2D, MediaPipe Hands
    --reconocedor vocabulario  dinamicos por DTW + estaticos + paro, con dos modos excluyentes
    --backend mocap            Robotat + backend high-level de la cruz                    [por defecto]
    --backend flowdeck         Flow deck v2 con MotionCommander

El vocabulario completo
-----------------------
`--reconocedor vocabulario` es el mismo bucle que `probar_vocabulario.py`
(`external/gesture_detection/`) con el dron real en vez del simulado. Arranca
en modo dinamico; `aplaudir` cambia de modo y deja hover.

    modo dinamico   senalero            despega en el suelo, aterriza en el aire
                    ven_aca             sigue al marker 65
                    arco, circulo       todavia sin vuelo: hover y aviso (T-005, paso 2)
    modo estatico   ARRIBA ... DERECHA  velocidad mientras se sostiene, en el aire
    siempre         X sobre la cabeza   1 s: aterriza y bloquea hasta soltar;
                                        sostenida 3 s: corte de motores

Necesita el banco `models/plantillas_vocabulario.npz` (ver el README de
`gesture_detection`, "Flujo completo"). Que gesto vale en que modo lo decide
`recognition/vocabulario.py`; aqui solo se traduce cada decision a una orden.

    python .\\controllers\\single_drone\\camera\\control_camara_dron1.py --reconocedor vocabulario
    python .\\controllers\\single_drone\\camera\\control_camara_dron1.py --reconocedor vocabulario --volar --dry-run

Con la camara IP del laboratorio (`--rtsp`) y, si se quiere, su pan/tilt
siguiendo al operador (`--seguir`), como en `probar_vocabulario.py`: la camara
no gira mientras hay un gesto en curso y los frames tomados girando se marcan
como huecos en vez de alimentar al reconocedor.

    python .\\controllers\\single_drone\\camera\\control_camara_dron1.py --reconocedor vocabulario ^
        --rtsp "rtsp://usuario:clave@IP:554/cam/realmonitor?channel=1&subtype=1" --seguir --volar --dry-run

Sin `--volar` no se importa `cflib`, no se abre radio y no se arma nada: sirve
para leer los gestos con la webcam en cualquier maquina. Con `--volar --dry-run`
el backend high-level es simulado.

    # leer el vocabulario corporal en la webcam, sin dron
    python .\\controllers\\single_drone\\camera\\control_camara_dron1.py

    # volar con el mocap del Robotat, mirando hacia el eje +X de la sala
    python .\\controllers\\single_drone\\camera\\control_camara_dron1.py --volar

    # lo mismo, mirando hacia +Y
    python .\\controllers\\single_drone\\camera\\control_camara_dron1.py --volar --rumbo 90

    # gestos de una mano en 2D, sobre Flow deck
    python .\\controllers\\single_drone\\camera\\control_camara_dron1.py --reconocedor manos --backend flowdeck --volar

El recorrido guiado por los nueve gestos, con tasa de acierto y latencia, vive
en `external/gesture_detection/probar_gestos_3d.py --practica`: no necesita dron.

El marco de referencia
----------------------
El gesto se reconoce en **tu** marco: ADELANTE es hacia donde miras. El dron no
obedece en ese marco, y adonde hay que girarlo depende del backend:

* con **mocap**, las ordenes van en el marco de la sala; el rumbo del dron da
  igual y `--rumbo` es hacia donde miras vos, en grados antihorarios desde `+X`;
* con **Flow deck**, van en el marco del dron; `--rumbo` es cuanto esta girada
  su nariz hacia tu izquierda.

En los dos casos, un `--rumbo` equivocado manda el dron de lado.

Seguridad
---------
* STOP sostenido dispara la parada de emergencia (0.6 s con la mano, 2 s con
  el cuerpo); la tecla ESC hace lo mismo.
* Con mocap: geocerca, ventana de altura, mocap fresco, alineacion EKF y
  separacion los valida el backend de la cruz; sin ordenes de la camara
  aterriza.
* Con Flow deck: techo de altura y watchdog de vision en dos etapas del
  `FlowDroneController`.
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

MODULE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = MODULE_DIR.parents[2]
GESTURE_DIR = PROJECT_DIR / "external" / "gesture_detection"
SHARED_DIR = PROJECT_DIR / "controllers" / "shared"
JOYSTICK_DIR = PROJECT_DIR / "controllers" / "joystick"
TWO_DRONES_DIR = PROJECT_DIR / "controllers" / "two_drones"
ROBOTAT_DIR = PROJECT_DIR / "controllers" / "single_drone" / "robotat"  # vuelo_camara.py
for directory in (MODULE_DIR, GESTURE_DIR, SHARED_DIR, JOYSTICK_DIR, TWO_DRONES_DIR, ROBOTAT_DIR):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from config import (  # noqa: E402
    CAMERA_INDEX,
    MIN_DETECTION_CONFIDENCE,
    MIN_TRACKING_CONFIDENCE,
)
from contracts import GESTOS_DE_ESTADO, Gesture, GestureEvent, VelocityIntent  # noqa: E402
from csv_session import CsvSession  # noqa: E402
from grafica_comandos import GraficaDeComandos  # noqa: E402
from hand_gesture_detector import HandGestureDetector  # noqa: E402
from hand_tracker import HandTracker  # noqa: E402
from marker_follow import CameraMarkerFollower, FOLLOW_MARKER_ID, FOLLOW_MARKER_TOPIC  # noqa: E402
from pose.detector import PoseDetector  # noqa: E402
from pose.normalize import body_frame, landmarks_to_array  # noqa: E402
from ptz import (  # noqa: E402
    Ajustes as AjustesPTZ,
    CamaraPTZ,
    ControlPTZ,
    ErrorPTZ,
    Seguidor,
    centro_torso,
    decidir_con_gesto,
)
from recognition.body_3d_rules import (  # noqa: E402
    CONO_DEG,
    VELOCIDADES,
    Body3DRecognizer,
    separaciones_del_vocabulario,
)
from recognition.dinamicos import ENTRADA_RAPIDEZ, BancoDinamico, ReconocedorDinamico  # noqa: E402
from recognition.paro_estatico import INSTRUCCION, POSTURAS, ReglaParo  # noqa: E402
from recognition.vocabulario import (  # noqa: E402
    ATERRIZAR,
    DESPEGAR,
    DINAMICO,
    ESTATICO,
    HOVER,
    IGNORADO,
    PARO,
    Decision,
    MaquinaDeModos,
)
from robotat import DRONE_1_TOPIC, DRONE_2_TOPIC, MQTT_BROKER, MQTT_PORT  # noqa: E402
from utils import calculate_fps  # noqa: E402
from video_source import abrir, enmascarar  # noqa: E402
from visualization.pose_overlay import draw_pose  # noqa: E402

#: Nombre de la carpeta de resultados: `results/{data,graphs}/<CONTROLADOR>/`.
CONTROLADOR = "control_camara_dron1"

#: `--dron N`: clave en el backend de la cruz, nombre y topico mocap por defecto.
DRONES = {
    1: ("drone1", "Dron 1", DRONE_1_TOPIC),
    2: ("drone2", "Dron 2", DRONE_2_TOPIC),
}


def datos_del_dron(args) -> tuple[str, str, str]:
    """`(clave, nombre, topico)` del dron elegido; `--topico-dron` manda."""
    clave, nombre, topico = DRONES[int(args.dron)]
    return clave, nombre, args.topico_dron or topico

#: Velocidad que se pide por cada gesto de direccion. Con Flow deck son m/s
#: reales; con mocap el backend high-level las convierte en pasos go_to.
SPEED_XY_M_S = 0.18
SPEED_Z_M_S = 0.10

# --- Watchdog de vision -----------------------------------------------------
# Etapa 1: sin ordenes frescas se detiene el movimiento y se queda en hover.
# Etapa 2: si el silencio persiste se aterriza. Una camara colgada no debe
# dejar el dron en hover hasta agotar la bateria. Con Flow deck las dos etapas
# viven en FlowDroneController; con mocap, la segunda en HighLevelFlight.
VISION_DEADMAN_S = 0.40
VISION_LOST_LAND_S = 2.00

COLOR_OK = (120, 220, 140)
COLOR_AVISO = (80, 200, 255)
COLOR_TEXTO = (240, 240, 240)
COLOR_APAGADO = (150, 150, 150)
COLOR_ALARMA = (80, 80, 255)

SEGUIR_MARKER = HandGestureDetector.SEGUIR_MARKER
DETENER_SEGUIMIENTO = HandGestureDetector.DETENER_SEGUIMIENTO


# ----------------------------------------------------------------- backends


def flowdeck_controller(uri: str, name: str = "Dron 1"):
    """Backend Flow deck del Dron 1 con techo de altura y watchdog de vision."""
    from flowdeck_dual_backend import MAX_HEIGHT_M, FlowDroneConfig, FlowDroneController

    return FlowDroneController(FlowDroneConfig(
        name,
        uri,
        deadman_s=VISION_DEADMAN_S,
        lost_land_s=VISION_LOST_LAND_S,
        max_height_m=MAX_HEIGHT_M,
    ))


def crear_vuelo(args):
    """Conecta el backend pedido. Solo aqui se importa `cflib`."""
    clave, nombre, topico = datos_del_dron(args)
    uri = None
    if not args.dry_run:
        import cflib.crtp
        from radios import DRONE_LINKS, select_uri

        cflib.crtp.init_drivers(enable_debug_driver=False)
        uri = select_uri(args.uri, args.radio, DRONE_LINKS[int(args.dron) - 1])
    if args.backend == "flowdeck":
        if args.dry_run:
            raise SystemExit("--backend flowdeck no tiene --dry-run; el simulado es el del mocap")
        flight = flowdeck_controller(uri, nombre)
        flight.connect()
        flight.wait_ready()
        return flight
    if args.backend == "robotat":
        # Controlador nuevo de un dron (single_drone/robotat): modo fluido en
        # vez de pasos go_to; los parametros del firmware van en las opciones
        # y se aplican en el preflight.
        from vuelo_camara import VueloRobotat, opciones_camara

        opciones = opciones_camara(
            uri=uri, topic=topico, nombre=nombre, ganancias=args.ganancias,
            parametros=parametros_firmware(args), radio_max_m=args.radio_max,
            dry_run=args.dry_run, centro_geocerca=args.centro_geocerca,
        )
        flight = VueloRobotat(opciones, dry_run=args.dry_run, key=clave,
                              velocidad_seguir_mps=args.velocidad_seguir,
                              radio_orbita_m=args.radio_orbita)
        flight.connect()
        return flight
    from highlevel_flight import HighLevelFlight

    flight = HighLevelFlight(uri=uri, topic=topico, dry_run=args.dry_run, key=clave)
    flight.connect()
    flight.set_params(parametros_firmware(args))
    return flight


def parametros_firmware(args) -> dict[str, str]:
    """`--param grupo.nombre=valor`, repetible, como diccionario ordenado."""
    params: dict[str, str] = {}
    for item in args.param or ():
        nombre, sep, valor = item.partition("=")
        if not sep or not nombre.strip() or not valor.strip() or "." not in nombre:
            raise SystemExit(f"--param espera grupo.nombre=valor, no {item!r}")
        params[nombre.strip()] = valor.strip()
    return params


# ------------------------------------------------------------- reconocedores
#
# Los dos entregan lo mismo por frame: la imagen para mostrar, un
# `GestureEvent` del contrato y la etiqueta de mano para el marker 65.


def _gesto_de_mano(detector: HandGestureDetector, manos) -> str:
    if manos:
        puntos, lateralidad = manos[0]
        return detector.detect(puntos, lateralidad)[1]
    return detector.detect(None, None)[1]


class ReconocedorCuerpo:
    """Vocabulario 3D de cuerpo entero, mas los dos gestos de mano del marker."""

    nombre = "cuerpo"
    titulo = "VOCABULARIO 3D"
    #: Segundos sosteniendo STOP antes de la parada de emergencia.
    stop_hold_s = 2.00
    ayuda = "q = salir   ESC = emergencia   r = reiniciar reconocedor"
    marker_ayuda = "dedo medio = seguir marker 65 | rock = detener"

    def __init__(self, camara: int) -> None:
        self.reconocedor = Body3DRecognizer(source=f"webcam{camara}")
        self.detector = PoseDetector(
            min_detection_confidence=MIN_DETECTION_CONFIDENCE,
            min_tracking_confidence=MIN_TRACKING_CONFIDENCE,
        )
        self.tracker_mano = HandTracker(max_num_hands=1)
        self.detector_mano = HandGestureDetector(self.tracker_mano.landmark_enum)

    @property
    def escala_m(self) -> float:
        return self.reconocedor.scale.scale_m

    def procesar(self, frame):
        # La inferencia va sobre la imagen SIN voltear. Volteada, MediaPipe
        # intercambia las etiquetas anatomicas y con ellas se invierte el eje X
        # del marco corporal: IZQUIERDA y DERECHA salen cambiadas. El espejo se
        # aplica al final, solo para mostrar.
        landmarks, world = self.detector.process_full(frame)
        evento = self.reconocedor.update(world)
        draw_pose(frame, landmarks, self.detector.connections)
        frame, manos = self.tracker_mano.process_hands(frame)
        gesto_mano = _gesto_de_mano(self.detector_mano, manos)
        return cv2.flip(frame, 1), evento, gesto_mano

    def lineas(self, evento: GestureEvent, fps: float) -> list[tuple[str, tuple]]:
        v = evento.velocity
        falta = evento.scores.get("falta_s", 0.0)
        color = COLOR_OK if evento.confirmed else COLOR_AVISO
        if evento.gesture is Gesture.NO_GESTURE:
            color = COLOR_APAGADO
        return [
            (f"Gesto: {evento.gesture.value}{'  CONFIRMADO' if evento.confirmed else ''}", color),
            (f"Comando: vx {v.vx:+.1f}  vy {v.vy:+.1f}  vz {v.vz:+.1f}"
             f"    {'' if falta <= 0 else f'sostener {falta:.1f} s mas'}", COLOR_TEXTO),
            (f"Torso: {self.escala_m * 100:.0f} cm   Calidad: {evento.landmark_quality:.2f}"
             f"   FPS: {fps:.1f}", COLOR_TEXTO),
        ]

    def reset(self) -> None:
        self.reconocedor.reset()

    def close(self) -> None:
        self.detector.close()
        self.tracker_mano.close()


def evento_de_mano(gesto: str) -> GestureEvent:
    """Traduce la etiqueta del detector de mano al contrato `GestureEvent`.

    El detector ya filtra por votacion y sostiene los gestos criticos, asi
    que lo que devuelve se considera confirmado. Lo que no es una orden de
    vuelo (REPOSO, SIN_DETECCION, los gestos del marker) es NO_GESTURE.
    """
    try:
        g = Gesture(gesto)
    except ValueError:
        g = Gesture.NO_GESTURE
    velocidad = ReconocedorManos.DIRECCIONES.get(g, VelocityIntent())
    hay = g is not Gesture.NO_GESTURE
    return GestureEvent(
        gesture=g, confidence=1.0 if hay else 0.0, confirmed=hay, engaged=True,
        velocity=velocidad, timestamp=time.monotonic(),
    )


class ReconocedorManos:
    """Gestos de una mano en 2D. Prototipo anterior al vocabulario corporal."""

    nombre = "manos"
    titulo = "GESTOS DE MANO 2D"
    stop_hold_s = 0.60
    ayuda = "q = salir   ESC = emergencia   sin mano o REPOSO = hover"
    marker_ayuda = "dedo medio = seguir marker 65 | rock = detener"
    DIRECCIONES = {
        Gesture.ADELANTE: VelocityIntent(vx=1.0),
        Gesture.ATRAS: VelocityIntent(vx=-1.0),
        Gesture.IZQUIERDA: VelocityIntent(vy=1.0),
        Gesture.DERECHA: VelocityIntent(vy=-1.0),
        Gesture.ARRIBA: VelocityIntent(vz=1.0),
        Gesture.ABAJO: VelocityIntent(vz=-1.0),
    }

    def __init__(self, camara: int) -> None:
        self.tracker = HandTracker(
            max_num_hands=1,
            min_detection_confidence=MIN_DETECTION_CONFIDENCE,
            min_tracking_confidence=MIN_TRACKING_CONFIDENCE,
        )
        self.detector = HandGestureDetector(self.tracker.landmark_enum)
        self.raw = self.detector.SIN_DETECCION
        self.escala_m = float("nan")

    def procesar(self, frame):
        # Los umbrales de la mano se ajustaron sobre la imagen volteada.
        frame = cv2.flip(frame, 1)
        frame, manos = self.tracker.process_hands(frame)
        if manos:
            self.raw, gesto, _ = self.detector.detect(*manos[0])
        else:
            self.raw, gesto, _ = self.detector.detect(None, None)
        return frame, evento_de_mano(gesto), gesto

    def lineas(self, evento: GestureEvent, fps: float) -> list[tuple[str, tuple]]:
        color = COLOR_APAGADO if evento.gesture is Gesture.NO_GESTURE else COLOR_OK
        return [
            (f"Gesto: {evento.gesture.value}    Raw: {self.raw}", color),
            (f"FPS: {fps:.1f}", COLOR_TEXTO),
        ]

    def reset(self) -> None:
        pass

    def close(self) -> None:
        self.tracker.close()


# ------------------------------------------------------ vocabulario completo
#
# Dinamicos por DTW, estaticos por reglas y paro, con la maquina de modos de
# `recognition/vocabulario.py`. Es el bucle de `probar_vocabulario.py` con el
# dron real en vez del simulado: el orden de prioridad es el mismo (paro,
# dinamico, comportamiento en curso, estaticos).

#: Banco de plantillas por defecto del vocabulario.
BANCO_VOCABULARIO = PROJECT_DIR / "models" / "plantillas_vocabulario.npz"
#: X sostenida este tiempo mas alla de la confirmacion del paro: corte de
#: motores. Aterrizar es lo primero porque no rompe el dron; cortar, lo
#: segundo, para cuando aterrizar no alcanza.
PARO_CORTE_EXTRA_S = 2.0
#: Tras soltar el paro, segundos en que se descarta el canal dinamico: bajar
#: los brazos es un movimiento y cerraria un segmento.
DESCARTE_TRAS_PARO_S = 1.0
#: Segundos que la ultima accion del vocabulario se queda en pantalla.
MOSTRAR_ACCION_S = 2.5
#: Gestos estaticos que son navegacion continua.
NAVEGACION = frozenset(VELOCIDADES)
#: Comportamientos que el vocabulario pide y que todavia no tienen vuelo.
SIN_VUELO = frozenset({"ALEJARSE"})


def _sin_gesto(evento: GestureEvent) -> GestureEvent:
    """El mismo evento, pero sin orden: para pintar y registrar, no para mover."""
    return dataclasses.replace(
        evento, gesture=Gesture.NO_GESTURE, confirmed=False, velocity=VelocityIntent(),
    )


class ReconocedorVocabulario:
    """Dinamicos (DTW) + estaticos + paro, con dos modos excluyentes.

    Por frame hace dos cosas separadas para poder probarlas sin camara:
    `observar()` alimenta los tres canales y deja las observaciones en
    atributos; `aplicar()` decide con ellas y manda al backend de vuelo.
    """

    nombre = "vocabulario"
    titulo = "VOCABULARIO DINAMICO + ESTATICO"
    ayuda = "q = salir   ESC = emergencia   r = reiniciar   aplaudir = cambiar de modo"
    marker_ayuda = "ven_aca = seguir marker 65 | X sobre la cabeza = paro"

    def __init__(self, camara, *, banco: BancoDinamico, paro: str = "cabeza",
                 confirmacion_s: float | None = None, detector=None) -> None:
        self.detector = detector if detector is not None else PoseDetector(
            min_detection_confidence=MIN_DETECTION_CONFIDENCE,
            min_tracking_confidence=MIN_TRACKING_CONFIDENCE,
        )
        self.dinamico = ReconocedorDinamico(banco)
        fuente = "ipcam" if isinstance(camara, str) else f"webcam{camara}"
        self.estatico = Body3DRecognizer(source=fuente)
        # Seguimiento PTZ opcional: `activar_seguimiento()` lo enciende.
        self.seguidor: Seguidor | None = None
        self.control_ptz: ControlPTZ | None = None
        self.ajustes_ptz = AjustesPTZ()
        self.estado_camara = ""
        self.regla = ReglaParo(paro, confirmacion_s)
        self.maquina = MaquinaDeModos()
        #: Sostener el paro este tiempo corta motores; lo muestra el panel.
        self.stop_hold_s = self.regla.confirmacion_s + PARO_CORTE_EXTRA_S
        self._escalas: list[float] = []
        self.escala_m = float("nan")
        # Observaciones del ultimo frame; `aplicar` decide con ellas.
        self.pose: np.ndarray | None = None
        self.paro_disparado = False
        self.deteccion = None
        #: fraccion de distancia DTW por debajo de la cual un gesto se confunde con aplaudir
        self.margen_aplauso = MARGEN_APLAUSO
        self.evento_estatico: GestureEvent | None = None
        # Para la consola, la grafica y el panel: `(texto, marcar en la grafica)`.
        self.novedades: list[tuple[str, bool]] = []
        self.ultima_accion: tuple[float, str] | None = None
        self._t_paro_soltado = -np.inf

    @property
    def modo(self) -> str:
        return self.maquina.control

    @property
    def comportamiento(self) -> str:
        return self.maquina.comportamiento

    # -- seguimiento PTZ ------------------------------------------------------

    def activar_seguimiento(self, control: ControlPTZ, ajustes: AjustesPTZ) -> None:
        """La camara sigue al operador con su pan/tilt, como en el probador."""
        self.control_ptz = control
        self.ajustes_ptz = ajustes
        self.seguidor = Seguidor(ajustes)
        self.estado_camara = "centrada"

    def _seguir_camara(self, lm2d, t: float) -> bool:
        """Un paso del seguimiento. `True` si el frame se tomo con la camara girando.

        Va ANTES del reconocedor porque puede invalidar el frame: unos
        landmarks con motion blur inventan segmentos, y el propio giro anade
        movimiento aparente a las manos. Un hueco es lo honesto.
        """
        if self.seguidor is None or self.control_ptz is None:
            return False
        puntos2d, vis2d = landmarks_to_array(lm2d)
        centro = (
            centro_torso(puntos2d, vis2d, visibilidad_min=self.ajustes_ptz.visibilidad_min)
            if puntos2d.size else None
        )
        self.control_ptz.pedir(decidir_con_gesto(
            self.seguidor, centro, t, gesto_en_curso=self.dinamico.en_segmento))
        if self.dinamico.en_segmento:
            self.estado_camara = "quieta (gesto en curso)"
        elif self.seguidor.activo:
            self.estado_camara = f"siguiendo {self.seguidor.activo}"
        else:
            self.estado_camara = "centrada"
        return self.seguidor.en_movimiento(t)

    # -- vision ---------------------------------------------------------------

    def procesar(self, frame):
        # Sin voltear, por lo mismo que `ReconocedorCuerpo`: en espejo
        # MediaPipe intercambia izquierda y derecha, y el cruce de munecas
        # de la X cambia de signo.
        lm2d, mundo_lm = self.detector.process_full(frame)
        t = time.monotonic()
        mundo, vis = landmarks_to_array(mundo_lm)
        pose = None
        if mundo.size:
            marco = body_frame(mundo, vis)
            if marco is not None and marco.valid:
                # La misma normalizacion con que se construyeron las
                # plantillas: marco del cuerpo y mediana del torso.
                self._escalas.append(marco.torso_length_m)
                del self._escalas[:-900]
                self.escala_m = float(np.median(self._escalas))
                pose = marco.apply(mundo) / self.escala_m
        if self._seguir_camara(lm2d, t):
            pose = None
        evento = self.observar(pose, mundo_lm, t)
        draw_pose(frame, lm2d, self.detector.connections)
        return cv2.flip(frame, 1), evento, ""

    def observar(self, pose, mundo_lm, t: float) -> GestureEvent:
        """Alimenta los tres canales con un frame.

        Devuelve el evento estatico para el panel y el CSV, **sin** gestos de
        estado: DESPEGAR, ATERRIZAR y STOP de `body_3d_rules` los sustituyen
        el senalero y la X, igual que en `probar_vocabulario.py`.
        """
        self.novedades = []
        self.pose = pose
        self.paro_disparado = self.regla.actualizar(pose, t)
        self.deteccion = det = self.dinamico.actualizar(pose, t)
        if det is not None:
            if det.gesto:
                self.novedades.append(
                    (f"dinamico: {det.gesto}   d={det.distancia:.3f} margen={det.margen:.3f}", False))
            else:
                self.novedades.append(
                    (f"dinamico: no reconocido ({det.motivo or 'lejos de todas'})"
                     f"   d={det.distancia:.3f}", False))
        evento = self.estatico.update(mundo_lm, t)
        if self.regla.activo or self.regla.cumple:
            # La X no es una direccion, y el reposo tras soltarla no hereda.
            self.estatico.reset()
            evento = _sin_gesto(evento)
        elif evento.gesture in GESTOS_DE_ESTADO:
            evento = _sin_gesto(evento)
        self.evento_estatico = evento
        return evento

    # -- decision -------------------------------------------------------------

    def _anotar(self, gesto: str, decision: Decision) -> None:
        accion, motivo = decision
        texto = f"{gesto} -> {accion}" if not motivo else f"{gesto} ignorado: {motivo}"
        self.novedades.append((texto, not motivo))
        self.ultima_accion = (time.monotonic(), texto)

    @staticmethod
    def _dejar_de_seguir(marker_follow, clave: str = "drone1") -> None:
        if marker_follow is not None and marker_follow.active(clave):
            marker_follow.deactivate((clave,))

    def aplicar(self, flight, *, t: float, speed_xy: float, speed_z: float,
                rumbo_deg: float, rotar, marker_follow, marker_body_frame: bool,
                clave: str = "drone1") -> tuple[str | None, bool]:
        """Un frame de decision: `(aviso para el panel, pedir emergencia)`.

        Quien dice si el dron esta en el aire es el backend, no la maquina:
        un despegue rechazado o un aterrizaje del watchdog no la desincronizan.
        """
        m = self.maquina
        en_aire = flight.flying
        if not en_aire and m.comportamiento != HOVER:
            # Aterrizo sin que lo pidiera un gesto: olvidar SEGUIR o MANUAL.
            m.hover()
            self._dejar_de_seguir(marker_follow, clave)

        # 1. Paro. Manda sobre los dos modos y bloquea hasta soltar.
        if self.paro_disparado:
            m.paro()
            self.dinamico.reset()
            self.estatico.reset()
            self._dejar_de_seguir(marker_follow, clave)
            if en_aire:
                flight.request_land("PARO por gesto")
            self._anotar("X sobre la cabeza", Decision(PARO))
        if self.regla.activo:
            if self.regla.sostenido_s >= self.stop_hold_s:
                return "PARO sostenido: EMERGENCIA", True
            flight.hover()
            falta = self.stop_hold_s - self.regla.sostenido_s
            return f"PARO: suelta los brazos para rearmar ({falta:.1f} s para cortar motores)", False
        if m.paro_activo:
            m.soltar_paro()
            self._t_paro_soltado = t
            self.dinamico.reset()

        # 2. Dinamico. Corre en los dos modos porque el aplauso que conmuta es
        # dinamico; lo demas lo filtra la maquina.
        det = self.deteccion
        if det is not None and det.gesto:
            if t - self._t_paro_soltado < DESCARTE_TRAS_PARO_S:
                self._anotar(det.gesto, Decision(IGNORADO, "movimiento del paro"))
            elif _confundible_con_aplauso(det, self.margen_aplauso):
                # Un aplauso leido como circulo pondria al dron a orbitar en
                # vez de dejarlo en hover (18:59 del 2026-09-17). Si el
                # aplauso queda cerca en distancia DTW, no se ejecuta.
                self._anotar(det.gesto, Decision(IGNORADO, "demasiado parecido a aplaudir"))
            else:
                decision = m.gesto(det.gesto, en_aire=en_aire)
                self._anotar(det.gesto, decision)
                if decision.ejecutar:
                    self.estatico.reset()           # que el reposo tras el gesto no herede
                    self._dejar_de_seguir(marker_follow, clave)
                if decision.accion == DESPEGAR:
                    flight.request_takeoff()
                elif decision.accion == ATERRIZAR:
                    flight.request_land(f"gesto {det.gesto}")

        # 3. Comportamiento continuo pedido por un gesto dinamico.
        if m.comportamiento == "SEGUIR":
            try:
                _seguir_marker(flight, marker_follow, marker_body_frame, clave)
                return "SIGUIENDO MARKER 65 (ven_aca)", False
            except Exception as error:
                print(f"Seguimiento detenido: {error}")
                m.hover()
                flight.hover()
                return f"NO SIGUE: {error}", False
        if m.comportamiento == "ORBITAR":
            try:
                _orbitar_marker(flight, marker_follow)
                return "ORBITANDO EL MARKER 65 (circulo) - aplaude para salir", False
            except Exception as error:
                print(f"Orbita detenida: {error}")
                m.hover()
                flight.hover()
                return f"NO ORBITA: {error}", False
        if m.comportamiento in SIN_VUELO:
            flight.hover()
            return f"{m.comportamiento}: sin implementacion de vuelo, hover", False

        # 4. Estaticos: solo en modo estatico y en el aire.
        ev = self.evento_estatico
        if ev is not None and ev.gesture in NAVEGACION and ev.confirmed:
            decision = m.navegar(ev.gesture.value, en_aire=en_aire)
            if decision.ejecutar:
                v = ev.velocity
                vx, vy = rotar(v.vx, v.vy, rumbo_deg)
                flight.set_velocity(vx * speed_xy, vy * speed_xy, v.vz * speed_z)
                return None, False
            flight.hover()
            # En modo dinamico un brazo extendido no es una orden y no hace
            # falta decirlo cada frame; en modo estatico si interesa el motivo.
            return (f"{ev.gesture.value} ignorado: {decision.motivo}"
                    if m.control == ESTATICO else None), False
        m.soltar_navegacion()
        flight.hover()
        return None, False

    # -- panel ----------------------------------------------------------------

    def banner(self) -> tuple[str, tuple]:
        """Texto grande del panel: el modo y lo que hace el dron, de un vistazo."""
        m = self.maquina
        if m.paro_activo or self.regla.activo:
            return "PARO", COLOR_ALARMA
        modo = "DINAMICO" if m.control == DINAMICO else "ESTATICO"
        detalle = {
            "SEGUIR": "SIGUIENDO MARKER", "ORBITAR": "ORBITANDO MARKER",
            "ALEJARSE": "ALEJARSE", "MANUAL": "MANUAL",
        }.get(m.comportamiento, "")
        return (f"{modo}  ·  {detalle}" if detalle else modo), COLOR_AVISO

    def lineas(self, evento: GestureEvent, fps: float) -> list[tuple[str, tuple]]:
        m = self.maquina
        lineas: list[tuple[str, tuple]] = []
        if m.paro_activo or self.regla.activo:
            lineas.append(("PARO DE EMERGENCIA: suelta los brazos para rearmar", COLOR_ALARMA))
        else:
            lineas.append((f"Modo: {m.control.upper()}    comportamiento: {m.comportamiento}",
                           COLOR_AVISO))
        if self.dinamico.en_segmento:
            lineas.append((f"Dinamico: grabando gesto {self.dinamico.segmento_s:.1f} s", COLOR_OK))
        else:
            lineas.append((f"Dinamico: esperando movimiento   rapidez "
                           f"{self.dinamico.rapidez:.2f} / {ENTRADA_RAPIDEZ:.2f}", COLOR_APAGADO))
        if self.ultima_accion and time.monotonic() - self.ultima_accion[0] < MOSTRAR_ACCION_S:
            lineas.append((self.ultima_accion[1], COLOR_OK))
        activo = m.control == ESTATICO and not m.paro_activo
        falta = evento.scores.get("falta_s", 0.0)
        texto = f"Estatico: {evento.gesture.value}{'  CONFIRMADO' if evento.confirmed else ''}"
        if not activo:
            texto += "   (inactivos en modo dinamico)"
        elif falta > 0 and evento.gesture is not Gesture.NO_GESTURE:
            texto += f"   sostener {falta:.1f} s mas"
        lineas.append((texto, COLOR_OK if (activo and evento.confirmed) else COLOR_APAGADO))
        torso = f"{self.escala_m * 100:.0f} cm" if np.isfinite(self.escala_m) else "s/d"
        lineas.append((f"Torso: {torso}   Calidad: {evento.landmark_quality:.2f}   FPS: {fps:.1f}",
                       COLOR_TEXTO))
        if self.seguidor is not None:
            lineas.append((f"Camara: {self.estado_camara}",
                           COLOR_AVISO if self.dinamico.en_segmento else COLOR_OK))
        return lineas

    def reset(self) -> None:
        self.dinamico.reset()
        self.estatico.reset()
        self.regla.reset()
        self.maquina.reset()
        self.ultima_accion = None

    def close(self) -> None:
        self.detector.close()


RECONOCEDORES = {"cuerpo": ReconocedorCuerpo, "manos": ReconocedorManos}


def cargar_banco(args) -> BancoDinamico | None:
    """Banco DTW del vocabulario, o `None` si el reconocedor no lo usa.

    Se comprueba antes de abrir radio o camara: sin banco no hay nada que volar.
    """
    if args.reconocedor != "vocabulario":
        return None
    ruta = Path(args.banco) if args.banco else BANCO_VOCABULARIO
    if not ruta.exists():
        raise SystemExit(
            f"No hay banco en {ruta}. Construilo con construir_plantillas.py "
            "(external/gesture_detection/README.md, 'Flujo completo').")
    banco = BancoDinamico.cargar(ruta)
    print(f"Banco: {ruta.name}   gestos: {', '.join(banco.clases)}"
          + ("   (+ rechazo)" if banco.tiene_rechazo else
             "   SIN rechazo: aceptara cualquier movimiento"))
    print(f"  umbral {banco.umbral:.3f}   margen {banco.margen:.3f}")
    if banco.umbrales:
        print("  umbral por gesto: " + "  ".join(
            f"{g} {banco.umbrales[g]:.3f}" for g in sorted(banco.umbrales)
            if g in banco.clases))
    return banco


def preparar_seguimiento(args) -> tuple[ControlPTZ | None, AjustesPTZ | None]:
    """Cliente PTZ y ajustes para `--seguir`, o `(None, None)` sin el.

    Se conecta antes de abrir radio o camara: si la camara no responde al
    PTZ, mejor saberlo sin un dron armado.
    """
    if not args.seguir:
        return None, None
    if not args.rtsp or args.reconocedor != "vocabulario":
        raise SystemExit("--seguir necesita --rtsp y --reconocedor vocabulario.")
    zona_tilt = args.zona_muerta if args.zona_muerta_tilt is None else args.zona_muerta_tilt
    ajustes = AjustesPTZ(
        arrancar_en=args.zona_muerta,
        parar_en=min(AjustesPTZ.parar_en, args.zona_muerta * 0.6),
        arrancar_en_tilt=zona_tilt,
        parar_en_tilt=min(AjustesPTZ.parar_en_tilt, zona_tilt * 0.6),
        objetivo_y=args.centro_y,
        velocidad_max=args.velocidad_max,
        seguir_tilt=not args.sin_tilt,
    )
    camara = CamaraPTZ.desde_rtsp(args.rtsp, dry_run=args.ptz_dry_run)
    try:
        pos = camara.posicion()
    except ErrorPTZ as exc:
        raise SystemExit(f"La camara no responde al PTZ: {exc}")
    print(f"Seguimiento PTZ activo en {camara.host}"
          + ("   [PTZ DRY-RUN]" if args.ptz_dry_run else ""))
    if pos:
        print(f"  posicion inicial: pan {pos[0]:.1f}  tilt {pos[1]:.1f}")
    print("  La camara NO se mueve mientras hay un gesto en curso.")
    return ControlPTZ(camara), ajustes


def crear_reconocedor(args, banco: BancoDinamico | None, fuente):
    if args.reconocedor != "vocabulario":
        return RECONOCEDORES[args.reconocedor](args.camera)
    reconocedor = ReconocedorVocabulario(
        fuente, banco=banco, paro=args.paro, confirmacion_s=args.confirmacion)
    regla = reconocedor.regla
    print(f"Paro: {INSTRUCCION[regla.postura]}: {regla.confirmacion_s:.1f} s aterriza, "
          f"{reconocedor.stop_hold_s:.1f} s corta motores.")
    print("Arranca en modo dinamico; aplaudi para pasar a los estaticos y otra vez para volver.")
    return reconocedor


# --------------------------------------------------------------------- CSV


def _columnas_dinamico(det) -> dict[str, str]:
    """Columnas del CSV para la detección dinámica cerrada en este frame."""
    if det is None:
        return {}
    distancias = dict(getattr(det, "distancias", {}) or {})
    ordenadas = sorted(distancias.items(), key=lambda kv: kv[1])
    segundo = ordenadas[1][0] if len(ordenadas) > 1 else ""
    return {
        "gesto_dinamico": det.gesto or f"rechazado:{det.motivo}",
        "dist_dinamico": f"{det.distancia:.3f}",
        "margen_dinamico": "" if not np.isfinite(det.margen) else f"{det.margen:.3f}",
        "segundo_dinamico": segundo,
    }


class Registro(CsvSession):
    """Una fila por frame en `results/data/control_camara_dron1/<dia>/<sesion>.csv`."""

    CAMPOS = [
        "t_s", "reconocedor", "gesto", "confirmado", "enganchado", "confianza",
        "vx", "vy", "vz", "calidad", "escala_m", "gesto_mano", "estado", "fps",
        "modo", "comportamiento",       # solo el vocabulario completo los llena
        # deteccion dinamica (DTW) cerrada en este frame: gesto o vacio si se
        # rechazo, distancia, margen sobre el segundo y cual era el segundo
        "gesto_dinamico", "dist_dinamico", "margen_dinamico", "segundo_dinamico",
    ]

    def __init__(self, sesion: str) -> None:
        super().__init__(self.CAMPOS, folder_name=CONTROLADOR, filename_prefix=sesion)

    def anotar(self, reconocedor, evento: GestureEvent, gesto_mano: str, estado: str, fps: float) -> None:
        v = evento.velocity
        self.write(self._base_row(
            reconocedor=reconocedor.nombre, gesto=evento.gesture.value,
            confirmado=int(evento.confirmed), enganchado=int(evento.engaged),
            confianza=f"{evento.confidence:.3f}",
            vx=f"{v.vx:.2f}", vy=f"{v.vy:.2f}", vz=f"{v.vz:.2f}",
            calidad=f"{evento.landmark_quality:.3f}",
            escala_m="" if not np.isfinite(reconocedor.escala_m) else f"{reconocedor.escala_m:.4f}",
            gesto_mano=gesto_mano, estado=estado, fps=f"{fps:.1f}",
            modo=getattr(reconocedor, "modo", ""),
            comportamiento=getattr(reconocedor, "comportamiento", ""),
            **_columnas_dinamico(getattr(reconocedor, "deteccion", None)),
        ))


# -------------------------------------------------------------------- panel


def _texto(frame, linea, fila, color=COLOR_TEXTO, escala=0.55):
    cv2.putText(frame, linea, (12, 28 + fila * 26), cv2.FONT_HERSHEY_SIMPLEX,
                escala, color, 1, cv2.LINE_AA)


def dibujar_panel(frame, reconocedor, evento, *, fps, estado, altura,
                  stop_desde, seguimiento, nombre="Dron 1") -> None:
    lineas = [(f"{nombre.upper()} - {reconocedor.titulo}    {estado}", COLOR_TEXTO)]
    lineas += reconocedor.lineas(evento, fps)
    lineas.append((f"Altura: {altura}    {reconocedor.marker_ayuda}", COLOR_TEXTO))
    if stop_desde is not None:
        lineas.append((f"STOP sostenido {time.monotonic() - stop_desde:.1f}/"
                       f"{reconocedor.stop_hold_s:.1f} s -> EMERGENCIA", COLOR_ALARMA))
    if seguimiento:
        lineas.append((seguimiento, COLOR_AVISO))
    lineas.append((reconocedor.ayuda, COLOR_APAGADO))

    alto_panel = 26 * len(lineas) + 18
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (frame.shape[1], alto_panel), (18, 18, 18), -1)
    cv2.addWeighted(overlay, 0.74, frame, 0.26, 0, frame)
    for fila, (linea, color) in enumerate(lineas):
        _texto(frame, linea, fila, color, 0.5 if fila == len(lineas) - 1 else 0.55)
    # Modo en grande, debajo del panel y a la derecha: se lee desde el area
    # de vuelo sin acercarse a la pantalla.
    banner = getattr(reconocedor, "banner", None)
    if banner is not None:
        texto, color = banner()
        escala, grosor = 1.5, 3
        (ancho, alto), _ = cv2.getTextSize(texto, cv2.FONT_HERSHEY_DUPLEX, escala, grosor)
        x = max(12, frame.shape[1] - ancho - 24)
        y = alto_panel + alto + 24
        fondo = frame.copy()
        cv2.rectangle(fondo, (x - 12, y - alto - 12), (x + ancho + 12, y + 12), (18, 18, 18), -1)
        cv2.addWeighted(fondo, 0.7, frame, 0.3, 0, frame)
        cv2.putText(frame, texto, (x, y), cv2.FONT_HERSHEY_DUPLEX, escala, color, grosor, cv2.LINE_AA)


# ------------------------------------------------------- marcos de referencia
#
# El gesto se reconoce en el marco del OPERADOR. El dron no obedece en ese
# marco, asi que hay que girarlo, y adonde depende del backend de vuelo.


def al_marco_del_dron(vx: float, vy: float, rumbo_deg: float) -> tuple[float, float]:
    """Del marco del operador al del **dron**. Solo para el backend Flow deck.

    `MotionCommander` manda en el marco del dron, y con Flow deck el rumbo del
    dron es el que tenia al armarse, sin referencia externa. `rumbo_deg` es
    cuanto esta girada la nariz del dron **hacia tu izquierda** respecto de la
    direccion en la que miras.
    """
    a = np.radians(rumbo_deg)
    c, s = np.cos(a), np.sin(a)
    return vx * c + vy * s, -vx * s + vy * c


def al_marco_del_mundo(vx: float, vy: float, rumbo_deg: float) -> tuple[float, float]:
    """Del marco del operador al de la **sala**. Para el backend de mocap.

    El backend high-level manda en el marco del Robotat, asi que el rumbo del
    dron deja de importar, pero aparece el otro: hacia donde mira el operador.
    `rumbo_deg` es esa direccion, en grados antihorarios desde el eje `+X`.
    """
    a = np.radians(rumbo_deg)
    c, s = np.cos(a), np.sin(a)
    return vx * c - vy * s, vx * s + vy * c


# ------------------------------------------------------------ gesto -> orden


def _aplicar(flight, evento, speed_xy, speed_z, rumbo_deg=0.0,
             rotar=al_marco_del_dron) -> None:
    """Traduce el evento a una orden del Dron 1.

    Solo se ejecuta lo confirmado. La vision produce intencion normalizada y
    es aqui, que es quien conoce el dron, donde se convierte en m/s.
    """
    g = evento.gesture
    if g is Gesture.DESPEGAR and evento.confirmed and not flight.flying:
        flight.request_takeoff()
        return
    if g is Gesture.ATERRIZAR and evento.confirmed and flight.flying:
        flight.request_land("gesto ATERRIZAR")
        return
    if not flight.flying:
        return
    if g in GESTOS_DE_ESTADO or evento.velocity.quieto or not evento.confirmed:
        flight.hover()
        return
    v = evento.velocity
    vx, vy = rotar(v.vx, v.vy, rumbo_deg)
    flight.set_velocity(vx * speed_xy, vy * speed_xy, v.vz * speed_z)


#: Un gesto dinámico se ignora si la plantilla de `aplaudir` queda a menos de
#: esta fracción de distancia de la ganadora (0.20 = un 20 % más lejos, o
#: menos). Aplaudir es el conmutador de modo: confundirlo con `circulo` pone
#: al dron a orbitar en vez de dejarlo en hover.
MARGEN_APLAUSO = 0.20


def _confundible_con_aplauso(det, margen: float = MARGEN_APLAUSO) -> bool:
    """True si `det` no es `aplaudir` pero `aplaudir` quedó demasiado cerca."""
    if det.gesto in (None, "aplaudir"):
        return False
    distancias = getattr(det, "distancias", {}) or {}
    d_aplauso = distancias.get("aplaudir")
    if d_aplauso is None or det.distancia <= 0:
        return False
    return d_aplauso <= det.distancia * (1.0 + margen)


def _orbitar_marker(flight, marker_follow) -> None:
    """Un paso de órbita alrededor del marker 65; sólo el backend `robotat` sabe hacerlo."""
    if marker_follow is None:
        raise RuntimeError("receptor del marker 65 inactivo")
    orbitar = getattr(flight, "orbit_marker", None)
    if orbitar is None:
        raise RuntimeError("la orbita necesita --backend robotat")
    orbitar(marker_follow)


def _seguir_marker(flight, marker_follow, marker_body_frame: bool,
                   clave: str = "drone1") -> None:
    """Un paso de seguimiento del marker 65, en el backend que toque.

    Sobre el backend high-level el seguimiento son pasos `follow_move`
    validados por la cruz; sobre Flow deck es una velocidad relativa.
    """
    if marker_follow is None:
        raise RuntimeError("receptor del marker 65 inactivo")
    seguir = getattr(flight, "follow_marker", None)
    if seguir is not None:
        seguir(marker_follow)
        return
    if not marker_follow.active(clave):
        marker_follow.activate((clave,))
    velocity = (
        marker_follow.body_velocity(clave) if marker_body_frame
        else marker_follow.world_velocity(clave)
    )
    flight.set_velocity(*velocity)


def _comando_ejecutado(evento, gesto_mano, flight, marker_follow,
                       clave: str = "drone1") -> tuple[str, bool]:
    """`(comando, confirmado)` que el controlador atendio en el frame.

    Sigue la misma prioridad que `bucle`: STOP primero, despues los gestos de
    mano del marker y el seguimiento activo, y solo al final el vocabulario.
    La grafica tiene que contar lo que el dron hizo, no solo lo que la
    camara vio.
    """
    if evento.gesture is Gesture.STOP:
        return Gesture.STOP.value, evento.confirmed
    if gesto_mano in (SEGUIR_MARKER, DETENER_SEGUIMIENTO):
        return gesto_mano, True
    if (flight is not None and flight.flying and marker_follow is not None
            and marker_follow.active(clave)):
        return SEGUIR_MARKER, True
    return evento.gesture.value, evento.confirmed


def _altura(flight) -> str:
    altura = flight.height_m
    return f"{altura:.2f} m" if altura is not None else "s/d"


# --------------------------------------------------------------------- bucle


def bucle(*, camara, reconocedor, flight, registro, velocidades,
          rumbo_deg=0.0, rotar=al_marco_del_dron,
          marker_follow: CameraMarkerFollower | None = None,
          marker_body_frame: bool = False,
          grafica: GraficaDeComandos | None = None,
          clave: str = "drone1", nombre: str = "Dron 1") -> None:
    speed_xy, speed_z = velocidades
    ventana = f"{nombre} - Control por camara"
    # Webcam por indice o camara IP por `rtsp://`; el lector RTSP corre en un
    # hilo y entrega solo el ultimo frame, para no acumular latencia.
    capture = abrir(camara)
    if not capture.isOpened():
        raise RuntimeError(f"No se pudo abrir la camara {enmascarar(camara)}.")

    anterior = 0.0
    ultimo_gesto = None
    ultimo_gesto_mano = None
    stop_desde: float | None = None
    t0 = time.monotonic()
    # Un reconocedor con `aplicar` decide el solo que hacer con el dron
    # (paro, modos, seguimiento, navegacion); los demas pasan por `_aplicar`.
    aplicar = getattr(reconocedor, "aplicar", None)

    cv2.namedWindow(ventana, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(ventana, 1024, 768)
    print("Ponte frente a la camara. q para salir, ESC para emergencia.")

    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                raise RuntimeError("La camara dejo de entregar imagenes.")
            frame, evento, gesto_mano = reconocedor.procesar(frame)
            fps, anterior = calculate_fps(anterior)
            ahora = time.monotonic()
            seguimiento = None

            # --- STOP sostenido = emergencia --------------------------------
            if evento.gesture is Gesture.STOP:
                stop_desde = stop_desde or ahora
            else:
                stop_desde = None

            if flight is not None:
                if stop_desde and ahora - stop_desde >= reconocedor.stop_hold_s:
                    print("STOP sostenido: PARADA DE EMERGENCIA.")
                    if grafica is not None:
                        grafica.evento(ahora - t0, "EMERGENCIA (STOP sostenido)")
                    flight.emergency_stop()
                    break
                if evento.gesture is Gesture.STOP:
                    # STOP pausa cualquier seguimiento desde el primer frame;
                    # si se sostiene, el bloque anterior lo eleva a emergencia.
                    flight.hover()
                elif aplicar is not None:
                    seguimiento, emergencia = aplicar(
                        flight, t=ahora, speed_xy=speed_xy, speed_z=speed_z,
                        rumbo_deg=rumbo_deg, rotar=rotar, marker_follow=marker_follow,
                        marker_body_frame=marker_body_frame, clave=clave)
                    if emergencia:
                        print("PARO sostenido: PARADA DE EMERGENCIA.")
                        if grafica is not None:
                            grafica.evento(ahora - t0, "EMERGENCIA (PARO sostenido)")
                        flight.emergency_stop()
                        break
                elif gesto_mano == DETENER_SEGUIMIENTO:
                    if marker_follow is not None:
                        marker_follow.deactivate((clave,))
                    flight.hover()
                    seguimiento = "SEGUIMIENTO DETENIDO"
                elif flight.flying and (
                    gesto_mano == SEGUIR_MARKER
                    or (marker_follow is not None and marker_follow.active(clave))
                ):
                    try:
                        _seguir_marker(flight, marker_follow, marker_body_frame, clave)
                        seguimiento = "SIGUIENDO MARKER 65"
                    except Exception as error:
                        print(f"Seguimiento detenido: {error}")
                        flight.hover()
                        seguimiento = f"NO SIGUE: {error}"
                else:
                    _aplicar(flight, evento, speed_xy, speed_z, rumbo_deg, rotar)

            if evento.gesture is not ultimo_gesto:
                marca = " (confirmado)" if evento.confirmed else ""
                print(f"[{ahora - t0:6.2f} s] {evento.gesture.value}{marca}")
                ultimo_gesto = evento.gesture
            if gesto_mano in (SEGUIR_MARKER, DETENER_SEGUIMIENTO) and gesto_mano != ultimo_gesto_mano:
                print(f"[{ahora - t0:6.2f} s] mano: {gesto_mano}")
            ultimo_gesto_mano = gesto_mano
            for texto, marcar in getattr(reconocedor, "novedades", ()):
                print(f"[{ahora - t0:6.2f} s] {texto}")
                if marcar and grafica is not None:
                    grafica.evento(ahora - t0, texto)

            if flight is None:
                estado, altura = "SIMULACION (sin dron)", "s/d"
            elif flight.busy:
                estado, altura = "MANIOBRANDO", _altura(flight)
            elif flight.flying:
                estado, altura = "VOLANDO", _altura(flight)
            else:
                estado, altura = "EN TIERRA", _altura(flight)

            registro.anotar(reconocedor, evento, gesto_mano, estado, fps)
            if grafica is not None:
                comando, confirmado = _comando_ejecutado(
                    evento, gesto_mano, flight, marker_follow, clave)
                grafica.anotar(ahora - t0, comando, confirmado=confirmado, estado=estado)
            dibujar_panel(frame, reconocedor, evento, fps=fps, estado=estado,
                          altura=altura, stop_desde=stop_desde, seguimiento=seguimiento,
                          nombre=nombre)
            cv2.imshow(ventana, frame)

            tecla = cv2.waitKey(1) & 0xFF
            if tecla == ord("q"):
                break
            if tecla == 27 and flight is not None:
                print("ESC: parada de emergencia.")
                if grafica is not None:
                    grafica.evento(ahora - t0, "EMERGENCIA (ESC)")
                flight.emergency_stop()
                break
            if tecla == ord("r"):
                reconocedor.reset()
            if cv2.getWindowProperty(ventana, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        capture.release()
        reconocedor.close()
        cv2.destroyAllWindows()


# ---------------------------------------------------------------------- main


def _resumen_vocabulario() -> None:
    peor = separaciones_del_vocabulario()[0]
    print(f"Vocabulario 3D: nueve gestos, cono de aceptacion {CONO_DEG:.0f} deg.")
    print(f"Par mas cercano: {peor[0].value} / {peor[1].value} a "
          f"{peor[2]:.0f} deg de separacion.")


def _preflight(args) -> None:
    """Lo que hay que tener claro antes de encender motores."""
    print()
    print("ANTES DE VOLAR")
    if args.backend == "mocap":
        print("  Backend: high-level de la cruz sobre el mocap del Robotat"
              + (" (SIMULADO)" if args.dry_run else "") + ".")
        clave, nombre, topico = datos_del_dron(args)
        print(f"  {nombre} ({clave}), topico {topico}.")
        params = parametros_firmware(args)
        if params:
            print("  Parametros del firmware tras conectar: "
                  + ", ".join(f"{k}={v}" for k, v in params.items()))
        if args.rumbo == 0.0:
            print("  --rumbo 0: se asume que miras hacia el eje +X del Robotat.")
            print("  Si miras hacia otro lado, pasalo con --rumbo o ADELANTE lo mandara de lado.")
        else:
            print(f"  --rumbo {args.rumbo:+.0f} deg: mirando a esa direccion del Robotat.")
    else:
        print("  Backend: Flow deck v2, sin referencia externa.")
        print(f"  --rumbo {args.rumbo:+.0f} deg: nariz del dron girada hacia tu izquierda.")
    if args.reconocedor == "vocabulario":
        print("  X sobre la cabeza: 1 s aterriza, sostenida 3 s corta motores. ESC corta.")
        print("  arco y circulo todavia no vuelan: dejan el dron en hover.")
    else:
        print("  STOP sostenido o ESC cortan los motores.")
    print("  La primera prueba, sin helices.")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Control de un Crazyflie por camara y gestos (--dron 1 por defecto)")
    parser.add_argument("--reconocedor", choices=(*RECONOCEDORES, "vocabulario"), default="cuerpo",
                        help="cuerpo: vocabulario 3D estatico (por defecto); manos: una mano "
                             "en 2D; vocabulario: dinamicos por DTW + estaticos + paro, con "
                             "dos modos excluyentes")
    parser.add_argument("--banco",
                        help="con --reconocedor vocabulario: banco de plantillas DTW; "
                             f"por defecto {BANCO_VOCABULARIO.relative_to(PROJECT_DIR)}")
    parser.add_argument("--paro", choices=sorted(POSTURAS), default="cabeza",
                        help="con --reconocedor vocabulario: postura del paro de emergencia")
    parser.add_argument("--confirmacion", type=float,
                        help="segundos a sostener el paro para aterrizar; por defecto segun postura")
    parser.add_argument("--backend", choices=("mocap", "flowdeck", "robotat"), default="mocap",
                        help="mocap: high-level de la cruz sobre el Robotat (por defecto); "
                             "flowdeck: MotionCommander con Flow deck v2; "
                             "robotat: controlador nuevo de un dron (single_drone/robotat), "
                             "movimiento fluido por velocidad y ganancias validadas")
    parser.add_argument("--ganancias", default="robotat",
                        help="con --backend robotat: juego de ganancias del firmware "
                             "(robotat, mitad, mitad-xy, fabrica); por defecto robotat")
    parser.add_argument("--radio-max", type=float, default=None,
                        help="con --backend robotat: geocerca horizontal desde el origen, m "
                             "(por defecto la del controlador, 0.5)")
    parser.add_argument("--velocidad-seguir", type=float, default=0.30,
                        help="con --backend robotat: velocidad maxima al perseguir el marker 65, "
                             "m/s (por defecto 0.30; el seguidor generico usa 0.10)")
    parser.add_argument("--centro-geocerca", type=float, nargs=2, metavar=("X", "Y"), default=None,
                        help="con --backend robotat: centro de la geocerca en el marco del Robotat, m "
                             "(por defecto el punto de despegue). Para seguir u orbitar el marker por "
                             "toda el area: --centro-geocerca 0 -0.4 --radio-max 1.5")
    parser.add_argument("--radio-orbita", type=float, default=0.50,
                        help="con --backend robotat y --reconocedor vocabulario: radio de la "
                             "orbita del gesto circulo alrededor del marker 65, m (defecto 0.50)")
    parser.add_argument("--camera", type=int, default=CAMERA_INDEX)
    parser.add_argument("--rtsp",
                        help="URL RTSP de una camara IP en vez de la webcam. Fuerza TCP y "
                             "lee en un hilo aparte, asi que no acumula latencia.")
    parser.add_argument("--seguir", action="store_true",
                        help="con --reconocedor vocabulario y --rtsp: la camara sigue al "
                             "operador con su pan/tilt. No se mueve mientras hay un gesto "
                             "en curso.")
    parser.add_argument("--ptz-dry-run", action="store_true",
                        help="con --seguir, decide pero no mueve los motores")
    parser.add_argument("--zona-muerta", type=float, default=AjustesPTZ.arrancar_en,
                        help="con --seguir: cuanto puede descentrarse antes de mover la "
                             f"camara. Por defecto: {AjustesPTZ.arrancar_en}")
    parser.add_argument("--zona-muerta-tilt", type=float,
                        help="con --seguir: idem en vertical. Por defecto, igual que --zona-muerta")
    parser.add_argument("--centro-y", type=float, default=AjustesPTZ.objetivo_y,
                        help="con --seguir: donde dejar el torso en vertical (0 arriba, 1 abajo). "
                             f"Mas de 0.5 deja aire sobre la cabeza. Por defecto: {AjustesPTZ.objetivo_y}")
    parser.add_argument("--velocidad-max", type=int, default=AjustesPTZ.velocidad_max,
                        help=f"con --seguir: velocidad PTZ maxima. Por defecto: {AjustesPTZ.velocidad_max}")
    parser.add_argument("--sin-tilt", action="store_true",
                        help="con --seguir: seguir solo en horizontal")
    parser.add_argument("--volar", action="store_true",
                        help="conecta el dron elegido con --dron y ejecuta los comandos")
    parser.add_argument("--dry-run", action="store_true",
                        help="con --volar y mocap: backend high-level simulado, sin radio ni mocap")
    parser.add_argument(
        "--rumbo", type=float, default=0.0,
        help="con mocap: hacia donde miras, en grados antihorarios desde el eje +X del "
             "Robotat. Con Flow deck: cuanto esta girada la nariz del dron hacia tu izquierda")
    parser.add_argument("--dron", type=int, choices=(1, 2), default=1,
                        help="que Crazyflie vuela este controlador: fija su enlace de radio, "
                             "su topico mocap y su nombre en el CSV del backend (por defecto 1)")
    parser.add_argument("--topico-dron", default=None,
                        help=f"topico MQTT con la pose del dron; por defecto {DRONE_1_TOPIC} "
                             f"para --dron 1 y {DRONE_2_TOPIC} para --dron 2")
    parser.add_argument("--id-dron", type=int, default=None,
                        help="identificador del marcador del Dron 1 para el seguimiento, "
                             "si el topico publica varios cuerpos")
    parser.add_argument("--broker", default=MQTT_BROKER, help="broker MQTT del receptor del marker")
    parser.add_argument("--puerto-mqtt", type=int, default=MQTT_PORT)
    parser.add_argument("--marker-id", type=int, default=FOLLOW_MARKER_ID)
    parser.add_argument("--marker-topic", default=FOLLOW_MARKER_TOPIC)
    parser.add_argument("--param", action="append", metavar="GRUPO.NOMBRE=VALOR",
                        help="con --backend mocap: parametro del firmware a fijar tras conectar, "
                             "repetible. Para probar contra la oscilacion del hover: "
                             "--param locSrv.extPosStdDev=0.05 --param posCtlPid.xKp=1.0. "
                             "Viven en RAM; se pierden al reiniciar el dron")
    parser.add_argument("--radio", help="serial de la Crazyradio")
    parser.add_argument("--uri", help="URI completa; tiene prioridad sobre --radio")
    parser.add_argument("--sin-csv", action="store_true")
    parser.add_argument("--sin-grafica", action="store_true",
                        help="no guardar la grafica de tiempo contra comandos")
    args = parser.parse_args()

    if args.reconocedor == "cuerpo":
        _resumen_vocabulario()
    banco = cargar_banco(args)          # sale antes de abrir nada si falta
    fuente = args.rtsp if args.rtsp else args.camera
    clave, nombre, topico = datos_del_dron(args)
    control_ptz, ajustes_ptz = preparar_seguimiento(args)
    rotar = al_marco_del_mundo if args.backend == "mocap" else al_marco_del_dron
    if not args.volar:
        print("Modo simulacion: no se abre la radio ni se arma el dron. "
              "Usa --volar para volar de verdad.")
    else:
        _preflight(args)

    flight = None
    marker_follow = None
    # CSV y grafica comparten etiqueta para que se emparejen a simple vista.
    sesion = datetime.now().strftime("sesion_%H%M%S")
    registro = Registro(sesion)
    if not args.sin_csv:
        registro.start(filename=sesion)
    grafica = GraficaDeComandos(CONTROLADOR, sesion=sesion, activo=not args.sin_grafica)
    try:
        if args.volar:
            flight = crear_vuelo(args)
            if not args.dry_run:
                marker_follow = CameraMarkerFollower(
                    marker_id=args.marker_id,
                    marker_topic=args.marker_topic,
                    drone_topics={clave: topico},
                    drone_identifiers={clave: args.id_dron},
                    broker=args.broker,
                    port=args.puerto_mqtt,
                )
                marker_follow.start()
        reconocedor = crear_reconocedor(args, banco, fuente)
        if control_ptz is not None:
            reconocedor.activar_seguimiento(control_ptz, ajustes_ptz)
        bucle(camara=fuente, reconocedor=reconocedor, flight=flight,
              registro=registro, velocidades=(SPEED_XY_M_S, SPEED_Z_M_S),
              rumbo_deg=args.rumbo, rotar=rotar, marker_follow=marker_follow,
              marker_body_frame=args.backend == "flowdeck", grafica=grafica,
              clave=clave, nombre=nombre)
        if registro.path is not None:
            print(f"Registro: {registro.path}")
        return 0
    except KeyboardInterrupt:
        print("Interrupcion solicitada.")
        return 130
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    finally:
        registro.stop(generate_graphs=False)
        if control_ptz is not None:
            control_ptz.cerrar()        # deja el motor parado
        if marker_follow is not None:
            marker_follow.stop()
        if flight is not None:
            flight.close()
            if hasattr(flight, "join"):
                flight.join(10.0)
        # Despues de cerrar la radio: matplotlib no debe retrasar el aterrizaje.
        grafica.guardar()


if __name__ == "__main__":
    raise SystemExit(main())
