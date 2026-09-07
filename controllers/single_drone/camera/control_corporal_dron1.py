"""Vocabulario 3D de cuerpo completo para el Dron 1.

Reconoce los nueve gestos sobre `pose_world_landmarks`, los canonicaliza al
marco del cuerpo y los traduce a ordenes de vuelo. Sin `--volar` no toca la
radio, asi que se puede depurar con la webcam y sin dron.

    # leer el vocabulario en la webcam, sin dron
    python .\\controllers\\single_drone\\camera\\control_corporal_dron1.py

    # recorrido guiado por los nueve gestos, con tasa de acierto y latencia
    python .\\controllers\\single_drone\\camera\\control_corporal_dron1.py --practica

    # volar con el mocap del Robotat, mirando hacia el eje +X de la sala
    python .\\controllers\\single_drone\\camera\\control_corporal_dron1.py --volar

    # lo mismo, mirando hacia el eje +Y
    python .\\controllers\\single_drone\\camera\\control_corporal_dron1.py --volar --rumbo 90

Dos backends de vuelo, uno por defecto
--------------------------------------
**Mocap del Robotat** salvo que se pida `--flowdeck`. Ver `mocap_flight.py`:
el mocap da posicion absoluta, y con ella geofence de verdad y deteccion de
perdida de tracking, que el Flow deck no puede dar. Los dos backends exponen la
misma interfaz, asi que el reconocimiento, el panel y el CSV son identicos.

El marco de referencia
----------------------
El gesto se reconoce en **tu** marco: ADELANTE es hacia donde miras. El dron no
obedece en ese marco, y adonde hay que girarlo depende del backend:

* con **mocap**, las ordenes van en el marco de la sala; el rumbo del dron da
  igual y `--rumbo` es hacia donde miras vos, en grados antihorarios desde `+X`;
* con **Flow deck**, van en el marco del dron; `--rumbo` es cuanto esta girada
  su nariz hacia tu izquierda.

En los dos casos, un `--rumbo` equivocado manda el dron de lado.

Que hace distinto al control 2D
-------------------------------
`control_camara_flowdeck_dron1.py` clasifica en pixeles de imagen. Eso tiene
dos consecuencias que se notan en el laboratorio: ADELANTE y ATRAS no existen
—se proyectan sobre el mismo pixel que REPOSO— y los umbrales se descalibran
cuando el operador se gira, porque el ancho de hombros en la imagen se encoge
y las distancias con el. Aqui todo se mide en unidades de torso sobre el marco
del cuerpo, de modo que el criterio no depende de donde este la camara.

El vocabulario y sus umbrales viven en
`external/gesture_detection/recognition/body_3d_rules.py`. Este archivo solo
compone: camara, pose, reconocedor, panel y —si se pide— vuelo.

Seguridad
---------
* Sin `--volar` no se llama a `cflib`, no se abre radio y no se arma nada.
* Con mocap: geofence de radio, ventana de altura y parada si se pierde el
  tracking. Con `--flowdeck` se reutiliza `CameraFlight`, que trae el techo de
  altura y el watchdog de vision en dos etapas.
* STOP sostenido dispara la parada de emergencia; la tecla ESC hace lo mismo.
"""

from __future__ import annotations

import argparse
import csv
import random
import statistics
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
for directory in (MODULE_DIR, GESTURE_DIR, SHARED_DIR, JOYSTICK_DIR):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from config import (  # noqa: E402
    CAMERA_INDEX,
    MIN_DETECTION_CONFIDENCE,
    MIN_TRACKING_CONFIDENCE,
)
from contracts import GESTOS_DE_ESTADO, Gesture  # noqa: E402
from pose.detector import PoseDetector  # noqa: E402
from recognition.body_3d_rules import (  # noqa: E402
    CONO_DEG,
    Body3DRecognizer,
    separaciones_del_vocabulario,
)
from utils import calculate_fps  # noqa: E402
from hand_gesture_detector import HandGestureDetector  # noqa: E402
from hand_tracker import HandTracker  # noqa: E402
from marker_follow import CameraMarkerFollower, FOLLOW_MARKER_ID, FOLLOW_MARKER_TOPIC  # noqa: E402
from visualization.pose_overlay import draw_pose  # noqa: E402
from grafica_comandos import GraficaDeComandos  # noqa: E402
from robotat import DRONE_1_TOPIC, MQTT_BROKER, MQTT_PORT  # noqa: E402


WINDOW_NAME = "Dron 1 - Vocabulario corporal 3D"

#: Segundos sosteniendo STOP antes de la parada de emergencia. Igual que en el
#: controlador 2D, para que el reflejo del operador sea el mismo en los dos.
STOP_HOLD_S = 2.00

#: Segundos que se concede a cada gesto en el modo practica antes de darlo por
#: fallado. Cuatro veces la confirmacion mas larga del reconocedor.
PRACTICA_LIMITE_S = 4.0

# Mocap: broker y topico vienen de `shared/robotat.py`, que no arrastra `cflib`
# ni `tkinter`, para que el banco de pruebas corra en cualquier maquina con
# webcam. La envolvente de vuelo sigue en `control_with_marker` y la importa
# `mocap_flight.py`. Si el Dron 1 publica en otro topico, pasalo con --topico-dron.
TOPICO_DRON = DRONE_1_TOPIC

COLOR_OK = (120, 220, 140)
COLOR_AVISO = (80, 200, 255)
COLOR_TEXTO = (240, 240, 240)
COLOR_APAGADO = (150, 150, 150)

INSTRUCCIONES = {
    Gesture.ARRIBA: "un brazo recto hacia arriba",
    Gesture.ABAJO: "un brazo abajo y al frente, a 45 grados",
    Gesture.ADELANTE: "un brazo al frente, horizontal",
    Gesture.ATRAS: "un brazo abajo y hacia atras",
    Gesture.IZQUIERDA: "brazo IZQUIERDO extendido a tu izquierda",
    Gesture.DERECHA: "brazo DERECHO extendido a tu derecha",
    Gesture.DESPEGAR: "las dos manos sobre los hombros",
    Gesture.ATERRIZAR: "los dos brazos en cruz",
    Gesture.STOP: "las dos manos JUNTAS delante del pecho",
}


# --------------------------------------------------------------------- CSV


class Registro:
    """Una fila por frame en `results/data/control_corporal_dron1/`."""

    CAMPOS = (
        "t", "gesto", "confirmado", "enganchado", "confianza",
        "vx", "vy", "vz", "calidad", "escala_m", "objetivo", "fps",
    )

    def __init__(self, activo: bool = True, sesion: str | None = None) -> None:
        self.ruta: Path | None = None
        self._archivo = None
        self._writer = None
        if not activo:
            return
        carpeta = (
            PROJECT_DIR / "results" / "data" / "control_corporal_dron1"
            / datetime.now().strftime("%Y-%m-%d")
        )
        carpeta.mkdir(parents=True, exist_ok=True)
        nombre = sesion or datetime.now().strftime("sesion_%H%M%S")
        self.ruta = carpeta / f"{nombre}.csv"
        self._archivo = self.ruta.open("w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._archivo)
        self._writer.writerow(self.CAMPOS)

    def anotar(self, t, evento, escala_m, objetivo, fps) -> None:
        if self._writer is None:
            return
        v = evento.velocity
        self._writer.writerow([
            f"{t:.3f}", evento.gesture.value, int(evento.confirmed),
            int(evento.engaged), f"{evento.confidence:.3f}",
            f"{v.vx:.2f}", f"{v.vy:.2f}", f"{v.vz:.2f}",
            f"{evento.landmark_quality:.3f}", f"{escala_m:.4f}",
            objetivo or "", f"{fps:.1f}",
        ])

    def cerrar(self) -> None:
        if self._archivo is not None:
            self._archivo.close()
            self._archivo = None


# ----------------------------------------------------------------- practica


class Practica:
    """Recorrido guiado por el vocabulario, con acierto y latencia.

    Es la medida que hace falta para la tesis: cuanto tarda el sistema en
    reconocer cada gesto y cuales se confunden entre si. Un gesto que el
    operador no consigue producir en `PRACTICA_LIMITE_S` cuenta como fallo,
    no como dato faltante.
    """

    def __init__(self, semilla: int | None = None) -> None:
        self.orden = list(INSTRUCCIONES)
        random.Random(semilla).shuffle(self.orden)
        self.i = 0
        self.inicio = time.monotonic()
        self.latencias: list[tuple[Gesture, float]] = []
        self.fallos: list[tuple[Gesture, Gesture]] = []

    @property
    def objetivo(self) -> Gesture | None:
        return self.orden[self.i] if self.i < len(self.orden) else None

    @property
    def terminado(self) -> bool:
        return self.i >= len(self.orden)

    @property
    def transcurrido(self) -> float:
        return time.monotonic() - self.inicio

    def _avanzar(self) -> None:
        self.i += 1
        self.inicio = time.monotonic()

    def actualizar(self, evento) -> None:
        objetivo = self.objetivo
        if objetivo is None:
            return
        if evento.confirmed and evento.gesture is objetivo:
            self.latencias.append((objetivo, self.transcurrido))
            self._avanzar()
        elif self.transcurrido > PRACTICA_LIMITE_S:
            self.fallos.append((objetivo, evento.gesture))
            self._avanzar()

    def saltar(self) -> None:
        objetivo = self.objetivo
        if objetivo is not None:
            self.fallos.append((objetivo, Gesture.NO_GESTURE))
            self._avanzar()

    def resumen(self) -> str:
        total = len(self.latencias) + len(self.fallos)
        if total == 0:
            return "Practica sin datos."
        lineas = [
            "",
            "=" * 58,
            f"Practica: {len(self.latencias)}/{total} gestos reconocidos "
            f"({100 * len(self.latencias) / total:.0f} %)",
        ]
        if self.latencias:
            tiempos = [t for _, t in self.latencias]
            lineas.append(
                f"Latencia hasta confirmar: mediana {statistics.median(tiempos):.2f} s"
                f"   peor {max(tiempos):.2f} s"
            )
            lineas.append("")
            for gesto, t in self.latencias:
                lineas.append(f"  {gesto.value:<10} {t:5.2f} s")
        if self.fallos:
            lineas.append("")
            lineas.append("No reconocidos (se pedia -> se leyo):")
            for pedido, leido in self.fallos:
                lineas.append(f"  {pedido.value:<10} -> {leido.value}")
        lineas.append("=" * 58)
        return "\n".join(lineas)


# -------------------------------------------------------------------- panel


def _texto(frame, linea, fila, color=COLOR_TEXTO, escala=0.55):
    cv2.putText(frame, linea, (12, 28 + fila * 26), cv2.FONT_HERSHEY_SIMPLEX,
                escala, color, 1, cv2.LINE_AA)


def dibujar_panel(frame, evento, *, escala_m, fps, estado, altura, practica,
                  stop_desde) -> None:
    alto_panel = 232 if practica else 198
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (frame.shape[1], alto_panel), (18, 18, 18), -1)
    cv2.addWeighted(overlay, 0.74, frame, 0.26, 0, frame)

    v = evento.velocity
    color_gesto = COLOR_OK if evento.confirmed else COLOR_AVISO
    if evento.gesture is Gesture.NO_GESTURE:
        color_gesto = COLOR_APAGADO

    _texto(frame, f"DRON 1 - VOCABULARIO 3D    {estado}", 0)
    _texto(frame, f"Gesto: {evento.gesture.value}"
                  f"{'  CONFIRMADO' if evento.confirmed else ''}", 1, color_gesto,
           0.62)
    falta = evento.scores.get("falta_s", 0.0)
    _texto(frame, f"Comando: vx {v.vx:+.1f}  vy {v.vy:+.1f}  vz {v.vz:+.1f}"
                  f"    {'' if falta <= 0 else f'sostener {falta:.1f} s mas'}", 2)
    _texto(frame, f"Torso: {escala_m * 100:.0f} cm   Calidad: "
                  f"{evento.landmark_quality:.2f}   FPS: {fps:.1f}   "
                  f"Altura: {altura}", 3)

    fila = 4
    if stop_desde is not None:
        _texto(frame, f"STOP sostenido {time.monotonic() - stop_desde:.1f}/"
                      f"{STOP_HOLD_S:.1f} s -> EMERGENCIA", fila, (80, 80, 255))
        fila += 1
    if practica is not None and not practica.terminado:
        objetivo = practica.objetivo
        _texto(frame, f"HAZ: {objetivo.value}  ({INSTRUCCIONES[objetivo]})",
               fila, COLOR_AVISO, 0.6)
        _texto(frame, f"quedan {PRACTICA_LIMITE_S - practica.transcurrido:.1f} s"
                      f"   {practica.i + 1}/{len(practica.orden)}", fila + 1)
        fila += 2
    _texto(frame, "q = salir   ESC = emergencia   r = reiniciar reconocedor"
                  f"{'   n = saltar' if practica else ''}", fila, COLOR_APAGADO,
           0.5)


# ------------------------------------------------------- marcos de referencia
#
# El gesto se reconoce en el marco del OPERADOR. El dron no obedece en ese
# marco, asi que hay que girarlo, y adonde depende del backend de vuelo.


def al_marco_del_dron(vx: float, vy: float, rumbo_deg: float) -> tuple[float, float]:
    """Del marco del operador al del **dron**. Solo para el backend Flow deck.

    El gesto esta en **tu** marco: ADELANTE es hacia donde miras vos.
    `MotionCommander` manda en el marco del dron, y con Flow deck el rumbo del
    dron es el que tenia al armarse, sin referencia externa. Si no coinciden y
    no se corrige, ADELANTE lo manda de lado.

    `rumbo_deg` es cuanto esta girada la nariz del dron **hacia tu izquierda**
    respecto de la direccion en la que miras.
    """
    a = np.radians(rumbo_deg)
    c, s = np.cos(a), np.sin(a)
    return vx * c + vy * s, -vx * s + vy * c


def al_marco_del_mundo(vx: float, vy: float, rumbo_deg: float) -> tuple[float, float]:
    """Del marco del operador al de la **sala**. Para el backend de mocap.

    `send_velocity_world_setpoint` manda en el marco del Robotat, asi que el
    rumbo del dron deja de importar —eso si lo resuelve el mocap— pero aparece
    el otro: hacia donde mira el operador.

    `rumbo_deg` es la direccion en la que mira el operador medida en el marco
    del Robotat, en grados y en sentido antihorario desde el eje `+X`.
    """
    a = np.radians(rumbo_deg)
    c, s = np.cos(a), np.sin(a)
    return vx * c - vy * s, vx * s + vy * c



# --------------------------------------------------------------------- bucle


def bucle(*, camara, flight, practica, registro, velocidades,
          rumbo_deg=0.0, rotar=al_marco_del_dron,
          marker_follow: CameraMarkerFollower | None = None,
          marker_body_frame: bool = False,
          grafica: GraficaDeComandos | None = None) -> Practica | None:
    speed_xy, speed_z = velocidades
    capture = cv2.VideoCapture(camara)
    if not capture.isOpened():
        raise RuntimeError(f"No se pudo abrir la camara {camara}.")

    reconocedor = Body3DRecognizer(source=f"webcam{camara}")
    detector = PoseDetector(
        min_detection_confidence=MIN_DETECTION_CONFIDENCE,
        min_tracking_confidence=MIN_TRACKING_CONFIDENCE,
    )
    tracker_mano = HandTracker(max_num_hands=1)
    detector_mano = HandGestureDetector(tracker_mano.landmark_enum)
    anterior = 0.0
    ultimo_gesto = None
    ultimo_gesto_mano = None
    stop_desde: float | None = None
    t0 = time.monotonic()

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW_NAME, 1024, 768)
    print("Ponte de frente y a cuerpo entero. q para salir.")

    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                raise RuntimeError("La camara dejo de entregar imagenes.")
            # La inferencia va sobre la imagen SIN voltear. Volteada, MediaPipe
            # intercambia las etiquetas anatomicas —llama "izquierda" a lo que
            # ve a la derecha del encuadre— y con ellas se invierte el eje X del
            # marco corporal: IZQUIERDA y DERECHA salen cambiadas. El espejo se
            # aplica al final, solo para mostrar.
            landmarks, world = detector.process_full(frame)
            fps, anterior = calculate_fps(anterior)

            evento = reconocedor.update(world)
            draw_pose(frame, landmarks, detector.connections)
            frame, manos = tracker_mano.process_hands(frame)
            if manos:
                puntos_mano, lateralidad = manos[0]
                _raw_mano, gesto_mano, _debug = detector_mano.detect(puntos_mano, lateralidad)
            else:
                _raw_mano, gesto_mano, _debug = detector_mano.detect(None, None)

            # --- STOP sostenido = emergencia --------------------------------
            if evento.gesture is Gesture.STOP:
                stop_desde = stop_desde or time.monotonic()
            else:
                stop_desde = None

            if flight is not None:
                if stop_desde and time.monotonic() - stop_desde >= STOP_HOLD_S:
                    print("STOP sostenido: PARADA DE EMERGENCIA.")
                    if grafica is not None:
                        grafica.evento(time.monotonic() - t0,
                                       "EMERGENCIA (STOP sostenido)")
                    flight.emergency_stop()
                    break
                if evento.gesture is Gesture.STOP:
                    # STOP corporal pausa cualquier seguimiento desde el
                    # primer frame; si se sostiene, el bloque anterior eleva
                    # la acción a emergencia.
                    flight.hover()
                elif gesto_mano == detector_mano.DETENER_SEGUIMIENTO:
                    if marker_follow is not None:
                        marker_follow.deactivate(("drone1",))
                    flight.hover()
                elif gesto_mano == detector_mano.SEGUIR_MARKER and flight.flying:
                    try:
                        if marker_follow is None:
                            raise RuntimeError("receptor del marker 65 inactivo")
                        if not marker_follow.active("drone1"):
                            marker_follow.activate(("drone1",))
                        velocity = (
                            marker_follow.body_velocity("drone1") if marker_body_frame
                            else marker_follow.world_velocity("drone1")
                        )
                        flight.set_velocity(*velocity)
                    except Exception as error:
                        print(f"Seguimiento detenido: {error}")
                        flight.hover()
                elif marker_follow is not None and marker_follow.active("drone1") and flight.flying:
                    try:
                        velocity = (
                            marker_follow.body_velocity("drone1") if marker_body_frame
                            else marker_follow.world_velocity("drone1")
                        )
                        flight.set_velocity(*velocity)
                    except Exception as error:
                        print(f"Seguimiento detenido: {error}")
                        flight.hover()
                else:
                    _aplicar(flight, evento, speed_xy, speed_z, rumbo_deg,
                             rotar)

            if evento.gesture is not ultimo_gesto:
                marca = " (confirmado)" if evento.confirmed else ""
                print(f"[{time.monotonic() - t0:6.2f} s] {evento.gesture.value}{marca}")
                ultimo_gesto = evento.gesture
            if gesto_mano in (detector_mano.SEGUIR_MARKER, detector_mano.DETENER_SEGUIMIENTO) and gesto_mano != ultimo_gesto_mano:
                print(f"[{time.monotonic() - t0:6.2f} s] mano: {gesto_mano}")
            ultimo_gesto_mano = gesto_mano

            if practica is not None:
                practica.actualizar(evento)
                if practica.terminado:
                    break

            if flight is None:
                estado, altura = "SIMULACION (sin dron)", "s/d"
            elif flight.busy:
                estado, altura = "MANIOBRANDO", _altura(flight)
            elif flight.flying:
                estado, altura = "VOLANDO", _altura(flight)
            else:
                estado, altura = "EN TIERRA", _altura(flight)

            registro.anotar(
                time.monotonic() - t0, evento, reconocedor.scale.scale_m,
                practica.objetivo.value
                if practica and practica.objetivo else None,
                fps,
            )
            if grafica is not None:
                comando, confirmado = _comando_ejecutado(
                    evento, gesto_mano, detector_mano, flight, marker_follow)
                grafica.anotar(time.monotonic() - t0, comando,
                               confirmado=confirmado, estado=estado)
            frame = cv2.flip(frame, 1)
            dibujar_panel(frame, evento, escala_m=reconocedor.scale.scale_m,
                          fps=fps, estado=estado, altura=altura,
                          practica=practica, stop_desde=stop_desde)
            cv2.imshow(WINDOW_NAME, frame)

            tecla = cv2.waitKey(1) & 0xFF
            if tecla == ord("q"):
                break
            if tecla == 27 and flight is not None:
                print("ESC: parada de emergencia.")
                if grafica is not None:
                    grafica.evento(time.monotonic() - t0, "EMERGENCIA (ESC)")
                flight.emergency_stop()
                break
            if tecla == ord("r"):
                reconocedor.reset()
            if tecla == ord("n") and practica is not None:
                practica.saltar()
                if practica.terminado:
                    break
            if cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        capture.release()
        detector.close()
        tracker_mano.close()
        cv2.destroyAllWindows()
    return practica


def _comando_ejecutado(evento, gesto_mano, detector_mano, flight,
                       marker_follow) -> tuple[str, bool]:
    """`(comando, confirmado)` que el controlador atendio en el frame.

    Sigue la misma prioridad que `bucle`: STOP corporal primero, despues los
    gestos de mano del marker y el seguimiento activo, y solo al final el
    vocabulario corporal. La grafica tiene que contar lo que el dron hizo,
    no solo lo que la camara vio.
    """
    if evento.gesture is Gesture.STOP:
        return Gesture.STOP.value, evento.confirmed
    if gesto_mano in (detector_mano.SEGUIR_MARKER,
                      detector_mano.DETENER_SEGUIMIENTO):
        return gesto_mano, True
    if (flight is not None and flight.flying and marker_follow is not None
            and marker_follow.active("drone1")):
        return detector_mano.SEGUIR_MARKER, True
    return evento.gesture.value, evento.confirmed


def _altura(flight) -> str:
    return f"{flight.height_m:.2f} m" if flight.height_m is not None else "s/d"


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
    if g in GESTOS_DE_ESTADO or evento.velocity.quieto:
        flight.hover()
        return
    v = evento.velocity
    vx, vy = rotar(v.vx, v.vy, rumbo_deg)
    flight.set_velocity(vx * speed_xy, vy * speed_xy, v.vz * speed_z)


# ---------------------------------------------------------------------- main


def _resumen_vocabulario() -> None:
    peor = separaciones_del_vocabulario()[0]
    print(f"Vocabulario: {len(INSTRUCCIONES)} gestos. "
          f"Cono de aceptacion {CONO_DEG:.0f} deg.")
    print(f"Par mas cercano: {peor[0].value} / {peor[1].value} a "
          f"{peor[2]:.0f} deg de separacion.")


def _preflight(args) -> None:
    """Lo que hay que tener claro antes de encender motores."""
    print()
    print("ANTES DE VOLAR")
    if args.flowdeck:
        print("  Posicionamiento: FLOW DECK. Sin posicion absoluta: no hay")
        print("  geofence, y la altura se integra desde el despegue.")
        print("  Los gestos estan en TU marco: ADELANTE es hacia donde miras.")
        if abs(args.rumbo) < 1e-6:
            print("  --rumbo 0: se asume que la nariz del dron apunta adonde "
                  "miras vos.")
            print("  Si no es asi, medi el angulo y pasalo con --rumbo, o "
                  "ADELANTE lo mandara de lado.")
        else:
            print(f"  --rumbo {args.rumbo:+.0f} deg: nariz del dron girada "
                  f"hacia tu izquierda esa cantidad.")
    else:
        print(f"  Posicionamiento: MOCAP del Robotat, topico "
              f"{args.topico_dron}"
              + (f" (id {args.id_dron})" if args.id_dron is not None else ""))
        print("  Las ordenes van en el marco de la SALA, asi que el rumbo del")
        print("  dron da igual. El que importa es el tuyo.")
        if abs(args.rumbo) < 1e-6:
            print("  --rumbo 0: se asume que miras hacia el eje +X del "
                  "Robotat.")
            print("  Si mirás hacia otro lado, pasalo con --rumbo o ADELANTE "
                  "lo mandara de lado.")
        else:
            print(f"  --rumbo {args.rumbo:+.0f} deg: mirando a esa direccion "
                  f"del Robotat.")
    print("  La primera prueba, sin helices.")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Vocabulario corporal 3D para el Dron 1")
    parser.add_argument("--camera", type=int, default=CAMERA_INDEX)
    parser.add_argument("--practica", action="store_true",
                        help="recorrido guiado por los nueve gestos")
    parser.add_argument("--semilla", type=int, default=None,
                        help="orden reproducible en el modo practica")
    parser.add_argument("--volar", action="store_true",
                        help="conecta el Dron 1 y ejecuta los comandos")
    parser.add_argument(
        "--flowdeck", action="store_true",
        help="volar con Flow deck en vez del mocap del Robotat")
    parser.add_argument(
        "--rumbo", type=float, default=0.0,
        help="con mocap: hacia donde miras, en grados antihorarios desde el "
             "eje +X del Robotat. Con --flowdeck: cuanto esta girada la nariz "
             "del dron hacia tu izquierda")
    parser.add_argument("--topico-dron", default=TOPICO_DRON,
                        help="topico MQTT con la pose del Dron 1")
    parser.add_argument("--id-dron", type=int, default=None,
                        help="identificador del marcador del Dron 1, si el "
                             "topico publica varios cuerpos")
    parser.add_argument("--broker", default=MQTT_BROKER)
    parser.add_argument("--puerto-mqtt", type=int, default=MQTT_PORT)
    parser.add_argument("--marker-id", type=int, default=FOLLOW_MARKER_ID)
    parser.add_argument("--marker-topic", default=FOLLOW_MARKER_TOPIC)
    parser.add_argument("--radio", help="serial de la Crazyradio")
    parser.add_argument("--uri", help="URI completa; tiene prioridad sobre --radio")
    parser.add_argument("--sin-csv", action="store_true")
    parser.add_argument("--sin-grafica", action="store_true",
                        help="no guardar la grafica de tiempo contra comandos")
    args = parser.parse_args()

    _resumen_vocabulario()
    rotar = al_marco_del_dron if args.flowdeck else al_marco_del_mundo
    if not args.volar:
        print("Modo simulacion: no se abre la radio ni se arma el dron. "
              "Usa --volar para volar de verdad.")
    else:
        _preflight(args)

    flight = None
    marker_follow = None
    # CSV y grafica comparten etiqueta para que se emparejen a simple vista.
    sesion = datetime.now().strftime("sesion_%H%M%S")
    registro = Registro(activo=not args.sin_csv, sesion=sesion)
    grafica = GraficaDeComandos("control_corporal_dron1", sesion=sesion,
                                activo=not args.sin_grafica)
    velocidades = (0.0, 0.0)
    try:
        if args.volar:
            # Importar aqui y no arriba: en simulacion no hace falta cflib ni
            # los backends de vuelo, y asi el banco de pruebas corre en
            # cualquier maquina con webcam.
            import cflib.crtp

            from control_camara_flowdeck_dron1 import (
                SPEED_XY_M_S,
                SPEED_Z_M_S,
            )
            from radios import select_uri

            velocidades = (SPEED_XY_M_S, SPEED_Z_M_S)
            cflib.crtp.init_drivers(enable_debug_driver=False)
            uri = select_uri(args.uri, args.radio)
            if args.flowdeck:
                from control_camara_flowdeck_dron1 import CameraFlight

                flight = CameraFlight(uri)
            else:
                from mocap_flight import MocapFlight

                flight = MocapFlight(
                    uri, topico_dron=args.topico_dron, broker=args.broker,
                    puerto=args.puerto_mqtt, id_dron=args.id_dron,
                )
            flight.connect()
            marker_follow = CameraMarkerFollower(
                marker_id=args.marker_id,
                marker_topic=args.marker_topic,
                drone_topics={"drone1": args.topico_dron},
                drone_identifiers={"drone1": args.id_dron},
                broker=args.broker,
                port=args.puerto_mqtt,
            )
            marker_follow.start()

        practica = Practica(args.semilla) if args.practica else None
        practica = bucle(camara=args.camera, flight=flight, practica=practica,
                         registro=registro, velocidades=velocidades,
                         rumbo_deg=args.rumbo, rotar=rotar,
                         marker_follow=marker_follow,
                         marker_body_frame=args.flowdeck,
                         grafica=grafica)
        if practica is not None:
            print(practica.resumen())
        if registro.ruta is not None:
            print(f"Registro: {registro.ruta}")
        return 0
    except KeyboardInterrupt:
        print("Interrupcion solicitada.")
        return 130
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    finally:
        registro.cerrar()
        if marker_follow is not None:
            marker_follow.stop()
        if flight is not None:
            flight.close()
        # Despues de cerrar la radio: matplotlib no debe retrasar el aterrizaje.
        grafica.guardar()


if __name__ == "__main__":
    raise SystemExit(main())
