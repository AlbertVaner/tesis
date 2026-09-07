"""Control del Dron 1 por camara: reconocedor y backend elegibles.

Un solo bucle de camara para los dos reconocedores y los dos backends:

    --reconocedor cuerpo   vocabulario 3D de cuerpo entero, MediaPipe Pose  [por defecto]
    --reconocedor manos    gestos de una mano en 2D, MediaPipe Hands
    --backend mocap        Robotat + backend high-level de la cruz          [por defecto]
    --backend flowdeck     Flow deck v2 con MotionCommander

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
for directory in (MODULE_DIR, GESTURE_DIR, SHARED_DIR, JOYSTICK_DIR, TWO_DRONES_DIR):
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
from recognition.body_3d_rules import (  # noqa: E402
    CONO_DEG,
    Body3DRecognizer,
    separaciones_del_vocabulario,
)
from robotat import DRONE_1_TOPIC, MQTT_BROKER, MQTT_PORT  # noqa: E402
from utils import calculate_fps  # noqa: E402
from visualization.pose_overlay import draw_pose  # noqa: E402

#: Nombre de la carpeta de resultados: `results/{data,graphs}/<CONTROLADOR>/`.
CONTROLADOR = "control_camara_dron1"
WINDOW_NAME = "Dron 1 - Control por camara"

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
    uri = None
    if not args.dry_run:
        import cflib.crtp
        from radios import select_uri

        cflib.crtp.init_drivers(enable_debug_driver=False)
        uri = select_uri(args.uri, args.radio)
    if args.backend == "flowdeck":
        if args.dry_run:
            raise SystemExit("--backend flowdeck no tiene --dry-run; el simulado es el del mocap")
        flight = flowdeck_controller(uri)
        flight.connect()
        flight.wait_ready()
        return flight
    from highlevel_flight import HighLevelFlight

    flight = HighLevelFlight(uri=uri, topic=args.topico_dron, dry_run=args.dry_run)
    flight.connect()
    return flight


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


RECONOCEDORES = {"cuerpo": ReconocedorCuerpo, "manos": ReconocedorManos}


# --------------------------------------------------------------------- CSV


class Registro(CsvSession):
    """Una fila por frame en `results/data/control_camara_dron1/<dia>/<sesion>.csv`."""

    CAMPOS = [
        "t_s", "reconocedor", "gesto", "confirmado", "enganchado", "confianza",
        "vx", "vy", "vz", "calidad", "escala_m", "gesto_mano", "estado", "fps",
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
        ))


# -------------------------------------------------------------------- panel


def _texto(frame, linea, fila, color=COLOR_TEXTO, escala=0.55):
    cv2.putText(frame, linea, (12, 28 + fila * 26), cv2.FONT_HERSHEY_SIMPLEX,
                escala, color, 1, cv2.LINE_AA)


def dibujar_panel(frame, reconocedor, evento, *, fps, estado, altura,
                  stop_desde, seguimiento) -> None:
    lineas = [(f"DRON 1 - {reconocedor.titulo}    {estado}", COLOR_TEXTO)]
    lineas += reconocedor.lineas(evento, fps)
    lineas.append((f"Altura: {altura}    dedo medio = seguir marker 65 | rock = detener",
                   COLOR_TEXTO))
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


def _seguir_marker(flight, marker_follow, marker_body_frame: bool) -> None:
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
    if not marker_follow.active("drone1"):
        marker_follow.activate(("drone1",))
    velocity = (
        marker_follow.body_velocity("drone1") if marker_body_frame
        else marker_follow.world_velocity("drone1")
    )
    flight.set_velocity(*velocity)


def _comando_ejecutado(evento, gesto_mano, flight, marker_follow) -> tuple[str, bool]:
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
            and marker_follow.active("drone1")):
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
          grafica: GraficaDeComandos | None = None) -> None:
    speed_xy, speed_z = velocidades
    capture = cv2.VideoCapture(camara)
    if not capture.isOpened():
        raise RuntimeError(f"No se pudo abrir la camara {camara}.")

    anterior = 0.0
    ultimo_gesto = None
    ultimo_gesto_mano = None
    stop_desde: float | None = None
    t0 = time.monotonic()

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW_NAME, 1024, 768)
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
                elif gesto_mano == DETENER_SEGUIMIENTO:
                    if marker_follow is not None:
                        marker_follow.deactivate(("drone1",))
                    flight.hover()
                    seguimiento = "SEGUIMIENTO DETENIDO"
                elif flight.flying and (
                    gesto_mano == SEGUIR_MARKER
                    or (marker_follow is not None and marker_follow.active("drone1"))
                ):
                    try:
                        _seguir_marker(flight, marker_follow, marker_body_frame)
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
                comando, confirmado = _comando_ejecutado(evento, gesto_mano, flight, marker_follow)
                grafica.anotar(ahora - t0, comando, confirmado=confirmado, estado=estado)
            dibujar_panel(frame, reconocedor, evento, fps=fps, estado=estado,
                          altura=altura, stop_desde=stop_desde, seguimiento=seguimiento)
            cv2.imshow(WINDOW_NAME, frame)

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
            if cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1:
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
        print(f"  Topico del Dron 1: {args.topico_dron}.")
        if args.rumbo == 0.0:
            print("  --rumbo 0: se asume que miras hacia el eje +X del Robotat.")
            print("  Si miras hacia otro lado, pasalo con --rumbo o ADELANTE lo mandara de lado.")
        else:
            print(f"  --rumbo {args.rumbo:+.0f} deg: mirando a esa direccion del Robotat.")
    else:
        print("  Backend: Flow deck v2, sin referencia externa.")
        print(f"  --rumbo {args.rumbo:+.0f} deg: nariz del dron girada hacia tu izquierda.")
    print("  STOP sostenido o ESC cortan los motores. La primera prueba, sin helices.")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Control del Dron 1 por camara y gestos")
    parser.add_argument("--reconocedor", choices=tuple(RECONOCEDORES), default="cuerpo",
                        help="cuerpo: vocabulario 3D (por defecto); manos: una mano en 2D")
    parser.add_argument("--backend", choices=("mocap", "flowdeck"), default="mocap",
                        help="mocap: high-level de la cruz sobre el Robotat (por defecto); "
                             "flowdeck: MotionCommander con Flow deck v2")
    parser.add_argument("--camera", type=int, default=CAMERA_INDEX)
    parser.add_argument("--volar", action="store_true",
                        help="conecta el Dron 1 y ejecuta los comandos")
    parser.add_argument("--dry-run", action="store_true",
                        help="con --volar y mocap: backend high-level simulado, sin radio ni mocap")
    parser.add_argument(
        "--rumbo", type=float, default=0.0,
        help="con mocap: hacia donde miras, en grados antihorarios desde el eje +X del "
             "Robotat. Con Flow deck: cuanto esta girada la nariz del dron hacia tu izquierda")
    parser.add_argument("--topico-dron", default=DRONE_1_TOPIC,
                        help="topico MQTT con la pose del Dron 1")
    parser.add_argument("--id-dron", type=int, default=None,
                        help="identificador del marcador del Dron 1 para el seguimiento, "
                             "si el topico publica varios cuerpos")
    parser.add_argument("--broker", default=MQTT_BROKER, help="broker MQTT del receptor del marker")
    parser.add_argument("--puerto-mqtt", type=int, default=MQTT_PORT)
    parser.add_argument("--marker-id", type=int, default=FOLLOW_MARKER_ID)
    parser.add_argument("--marker-topic", default=FOLLOW_MARKER_TOPIC)
    parser.add_argument("--radio", help="serial de la Crazyradio")
    parser.add_argument("--uri", help="URI completa; tiene prioridad sobre --radio")
    parser.add_argument("--sin-csv", action="store_true")
    parser.add_argument("--sin-grafica", action="store_true",
                        help="no guardar la grafica de tiempo contra comandos")
    args = parser.parse_args()

    if args.reconocedor == "cuerpo":
        _resumen_vocabulario()
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
                    drone_topics={"drone1": args.topico_dron},
                    drone_identifiers={"drone1": args.id_dron},
                    broker=args.broker,
                    port=args.puerto_mqtt,
                )
                marker_follow.start()
        reconocedor = RECONOCEDORES[args.reconocedor](args.camera)
        bucle(camara=args.camera, reconocedor=reconocedor, flight=flight,
              registro=registro, velocidades=(SPEED_XY_M_S, SPEED_Z_M_S),
              rumbo_deg=args.rumbo, rotar=rotar, marker_follow=marker_follow,
              marker_body_frame=args.backend == "flowdeck", grafica=grafica)
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
