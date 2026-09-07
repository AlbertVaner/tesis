"""Control del Dron 1 por gestos de mano usando Flow deck v2, sin Robotat."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2

import cflib.crtp


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
from hand_gesture_detector import HandGestureDetector  # noqa: E402
from hand_tracker import HandTracker  # noqa: E402
from flowdeck_dual_backend import MAX_HEIGHT_M, FlowDroneConfig, FlowDroneController  # noqa: E402
from radios import select_uri  # noqa: E402
from utils import calculate_fps  # noqa: E402
from marker_follow import (  # noqa: E402
    CameraMarkerFollower,
    FOLLOW_MARKER_ID,
    FOLLOW_MARKER_TOPIC,
)
from grafica_comandos import GraficaDeComandos  # noqa: E402
from robotat import DRONE_1_TOPIC  # noqa: E402


WINDOW_NAME = "Dron 1 - Camara + Flow deck"
SPEED_XY_M_S = 0.18
SPEED_Z_M_S = 0.10
STOP_HOLD_S = 0.60

# --- Watchdog de visión -----------------------------------------------------
# Etapa 1: sin órdenes frescas se detiene el movimiento y se queda en hover.
# Etapa 2: si el silencio persiste se aterriza. Una cámara colgada no debe
# dejar el dron en hover hasta agotar la batería. El techo de altura
# (MAX_HEIGHT_M) y ambas etapas viven en FlowDroneController.
VISION_DEADMAN_S = 0.40
VISION_LOST_LAND_S = 2.00


def flowdeck_controller(uri: str, name: str = "Dron 1") -> FlowDroneController:
    """Backend Flow deck del Dron 1 con techo de altura y watchdog de visión."""
    return FlowDroneController(FlowDroneConfig(
        name,
        uri,
        deadman_s=VISION_DEADMAN_S,
        lost_land_s=VISION_LOST_LAND_S,
        max_height_m=MAX_HEIGHT_M,
    ))


def gesture_velocity(detector: HandGestureDetector, gesture: str) -> tuple[float, float, float] | None:
    return {
        detector.ADELANTE: (SPEED_XY_M_S, 0.0, 0.0),
        detector.ATRAS: (-SPEED_XY_M_S, 0.0, 0.0),
        detector.IZQUIERDA: (0.0, SPEED_XY_M_S, 0.0),
        detector.DERECHA: (0.0, -SPEED_XY_M_S, 0.0),
        detector.ARRIBA: (0.0, 0.0, SPEED_Z_M_S),
        detector.ABAJO: (0.0, 0.0, -SPEED_Z_M_S),
    }.get(gesture)


def _comando_ejecutado(
    detector: HandGestureDetector, gesture: str, flight: FlowDroneController,
    marker_follow: CameraMarkerFollower,
) -> str:
    """Lo que el controlador atendió en el frame, no sólo lo que vio la mano.

    Mientras el seguimiento del marker está activo, los gestos de dirección
    se ignoran; registrarlos como comandos haría mentir a la gráfica.
    """
    if (
        gesture not in (detector.STOP, detector.DETENER_SEGUIMIENTO)
        and flight.flying
        and marker_follow.active("drone1")
    ):
        return detector.SEGUIR_MARKER
    return gesture


def draw_panel(
    frame, *, raw: str, gesture: str, state: str, fps: float, height: str
) -> None:
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (frame.shape[1], 206), (18, 18, 18), -1)
    cv2.addWeighted(overlay, 0.72, frame, 0.28, 0, frame)
    lines = (
        "DRON 1 - CONTROL POR CAMARA + FLOW DECK",
        f"Estado: {state}    FPS: {fps:.1f}",
        f"Altura: {height}    Techo: {MAX_HEIGHT_M:.2f} m",
        f"Gesto: {gesture}    Raw: {raw}",
        "Sin mano o REPOSO = hover automatico",
        "dedo medio = seguir marker 65 | rock = detener | puno = EMERGENCIA",
    )
    for index, line in enumerate(lines):
        color = (80, 220, 255) if index == 5 else (240, 240, 240)
        cv2.putText(
            frame,
            line,
            (12, 28 + index * 32),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            2,
        )


def camera_loop(
    flight: FlowDroneController,
    camera_index: int,
    marker_follow: CameraMarkerFollower,
    grafica: GraficaDeComandos | None = None,
) -> None:
    capture = cv2.VideoCapture(camera_index)
    if not capture.isOpened():
        raise RuntimeError(f"No se pudo abrir la cámara {camera_index}.")

    tracker = HandTracker(
        max_num_hands=1,
        min_detection_confidence=MIN_DETECTION_CONFIDENCE,
        min_tracking_confidence=MIN_TRACKING_CONFIDENCE,
    )
    detector = HandGestureDetector(tracker.landmark_enum)
    previous_frame_time = 0.0
    previous_gesture = detector.SIN_DETECCION
    stop_started: float | None = None
    t0 = time.monotonic()

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW_NAME, 960, 720)
    print("Muestra una mano a la cámara. Presiona q en el video para aterrizar y salir.")

    try:
        while True:
            success, frame = capture.read()
            if not success:
                raise RuntimeError("La cámara dejó de entregar imágenes.")
            frame = cv2.flip(frame, 1)
            annotated, hands = tracker.process_hands(frame)
            fps, previous_frame_time = calculate_fps(previous_frame_time)

            if hands:
                landmarks, handedness = hands[0]
                raw, gesture, _debug = detector.detect(landmarks, handedness)
            else:
                raw, gesture, _debug = detector.detect(None, None)

            displayed_gesture = gesture
            if gesture == detector.STOP and flight.flying:
                if stop_started is None:
                    stop_started = time.monotonic()
                held_for = time.monotonic() - stop_started
                displayed_gesture = f"CONFIRMANDO_STOP {held_for:.1f}/{STOP_HOLD_S:.1f}s"
                flight.hover()
                if held_for >= STOP_HOLD_S:
                    print("Puño cerrado confirmado: PARADA DE EMERGENCIA.")
                    if grafica is not None:
                        grafica.evento(time.monotonic() - t0, "EMERGENCIA (puno)")
                    flight.emergency_stop()
                    break
            else:
                stop_started = None

            if gesture == detector.STOP:
                pass
            elif gesture == detector.SEGUIR_MARKER and flight.flying:
                try:
                    if not marker_follow.active("drone1"):
                        marker_follow.activate(("drone1",))
                    flight.set_velocity(*marker_follow.body_velocity("drone1"))
                    displayed_gesture = "SIGUIENDO MARKER 65"
                except Exception as error:
                    displayed_gesture = f"NO SIGUE: {error}"
                    flight.hover()
            elif gesture == detector.DETENER_SEGUIMIENTO:
                marker_follow.deactivate(("drone1",))
                displayed_gesture = "SEGUIMIENTO DETENIDO"
                flight.hover()
            elif marker_follow.active("drone1") and flight.flying:
                try:
                    flight.set_velocity(*marker_follow.body_velocity("drone1"))
                    displayed_gesture = "SIGUIENDO MARKER 65"
                except Exception as error:
                    displayed_gesture = f"SEGUIMIENTO DETENIDO: {error}"
                    flight.hover()
            elif gesture == detector.DESPEGAR and not flight.flying:
                flight.request_takeoff()
            elif gesture == detector.ATERRIZAR and flight.flying:
                flight.request_land()
            else:
                velocity = gesture_velocity(detector, gesture)
                if velocity is not None and flight.flying:
                    flight.set_velocity(*velocity)
                elif flight.flying:
                    flight.hover()

            if gesture != previous_gesture:
                print(f"Gesto: {gesture}")
                previous_gesture = gesture

            if flight.busy:
                state = "MANIOBRANDO"
            elif flight.flying:
                state = "VOLANDO"
            else:
                state = "EN TIERRA"
            if grafica is not None:
                grafica.anotar(
                    time.monotonic() - t0,
                    _comando_ejecutado(detector, gesture, flight, marker_follow),
                    estado=state,
                )
            height = (
                f"{flight.height_m:.2f} m" if flight.height_m is not None else "s/d"
            )
            draw_panel(
                annotated,
                raw=raw,
                gesture=displayed_gesture,
                state=state,
                fps=fps,
                height=height,
            )
            cv2.imshow(WINDOW_NAME, annotated)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        capture.release()
        tracker.close()
        cv2.destroyAllWindows()


def main() -> int:
    parser = argparse.ArgumentParser(description="Control por cámara del Dron 1 con Flow deck")
    parser.add_argument("--camera", type=int, default=CAMERA_INDEX)
    parser.add_argument("--radio", help="serial de la Crazyradio")
    parser.add_argument("--uri", help="URI completa; tiene prioridad sobre --radio")
    parser.add_argument("--marker-id", type=int, default=FOLLOW_MARKER_ID)
    parser.add_argument("--marker-topic", default=FOLLOW_MARKER_TOPIC)
    parser.add_argument("--topic-dron", default=DRONE_1_TOPIC)
    parser.add_argument("--sin-grafica", action="store_true",
                        help="no guardar la gráfica de tiempo contra comandos")
    args = parser.parse_args()

    flight: FlowDroneController | None = None
    marker_follow: CameraMarkerFollower | None = None
    grafica = GraficaDeComandos(
        "control_camara_flowdeck_dron1", activo=not args.sin_grafica
    )
    try:
        cflib.crtp.init_drivers(enable_debug_driver=False)
        uri = select_uri(args.uri, args.radio)
        flight = flowdeck_controller(uri)
        flight.connect()
        flight.wait_ready()
        marker_follow = CameraMarkerFollower(
            marker_id=args.marker_id,
            marker_topic=args.marker_topic,
            drone_topics={"drone1": args.topic_dron},
        )
        marker_follow.start()
        camera_loop(flight, args.camera, marker_follow, grafica)
        return 0
    except KeyboardInterrupt:
        print("Interrupción solicitada.")
        return 130
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    finally:
        if marker_follow is not None:
            marker_follow.stop()
        if flight is not None:
            flight.close(wait_s=10.0)
        # Después de cerrar la radio: matplotlib no debe retrasar el aterrizaje.
        grafica.guardar()


if __name__ == "__main__":
    raise SystemExit(main())
