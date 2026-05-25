import sys
import time
import threading
from pathlib import Path

import cv2
import cflib.crtp
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie


# =======================================================
# RUTAS DEL PROYECTO
# =======================================================

ROOT_DIR = Path(__file__).resolve().parents[1]

DRONE_DIR = ROOT_DIR / "drone_control"
GESTURE_DIR = ROOT_DIR / "Gesture_control"

if str(DRONE_DIR) not in sys.path:
    sys.path.append(str(DRONE_DIR))

if str(GESTURE_DIR) not in sys.path:
    sys.path.append(str(GESTURE_DIR))


# =======================================================
# IMPORTAR MÓDULOS EXISTENTES
# =======================================================

import control as dc

from config import (
    CAMERA_INDEX,
    MIN_DETECTION_CONFIDENCE,
    MIN_TRACKING_CONFIDENCE,
    MAX_NUM_HANDS,
)

from hand_tracker import HandTracker
from hand_gesture_detector import HandGestureDetector
from utils import calculate_fps


# =======================================================
# CONFIGURACIÓN CONTROL POR GESTOS
# =======================================================

GESTURE_COOLDOWN_S = 1.2

# Cooldown especial para STOP, para que responda rápido.
STOP_COOLDOWN_S = 0.4

# Por seguridad operacional:
# STOP ahora SÍ ejecuta paro de emergencia: motores OFF.
STOP_CUTS_MOTORS = True


# =======================================================
# PANEL VISUAL DE CÁMARA
# =======================================================

def put_gesture_panel(frame, command, raw_command, handedness, fps, debug):
    panel_height = 145
    overlay = frame.copy()

    cv2.rectangle(
        overlay,
        (0, 0),
        (frame.shape[1], panel_height),
        (20, 20, 20),
        -1
    )

    cv2.addWeighted(overlay, 0.65, frame, 0.35, 0, frame)

    text_color = (240, 240, 240)

    cv2.putText(
        frame,
        "CONTROL GESTUAL CRAZYFLIE",
        (12, 28),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.70,
        text_color,
        2,
    )

    cv2.putText(
        frame,
        f"Comando filtrado: {command}",
        (12, 60),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.75,
        text_color,
        2,
    )

    cv2.putText(
        frame,
        f"Raw: {raw_command} | Mano: {handedness} | FPS: {fps:.1f}",
        (12, 90),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.52,
        text_color,
        2,
    )

    debug_text = (
        f"Orientacion: {debug.get('orientation')} | "
        f"T:{int(debug.get('thumb', False))} "
        f"I:{int(debug.get('index', False))} "
        f"M:{int(debug.get('middle', False))} "
        f"A:{int(debug.get('ring', False))} "
        f"m:{int(debug.get('pinky', False))}"
    )

    cv2.putText(
        frame,
        debug_text,
        (12, 118),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        text_color,
        1,
    )

    cv2.putText(
        frame,
        "q = cerrar camara | STOP = paro emergencia motores OFF",
        (12, 138),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.42,
        (80, 220, 255),
        1,
    )


# =======================================================
# EJECUTAR COMANDOS DEL DRON DESDE GESTOS
# =======================================================

def execute_gesture_command(app, detector, filtered_command):
    """
    Traduce el comando detectado por la cámara a una acción del panel/control del dron.
    """

    # ==========================
    # COMANDOS CRÍTICOS
    # ==========================

    if filtered_command == detector.DESPEGAR:
        if not app.has_taken_off and not app.is_landing:
            print("[GESTO] DESPEGAR detectado -> INICIAR HOVER")
            app.root.after(0, app.start_hover)
            return True

        return False

    if filtered_command == detector.ATERRIZAR:
        if app.has_taken_off and not app.is_landing:
            print("[GESTO] ATERRIZAR detectado -> ATERRIZAR")
            app.root.after(0, app.land_drone)
            return True

        return False

    if filtered_command == detector.STOP:
        if app.has_taken_off and not app.is_landing:
            print("[GESTO] STOP detectado -> PARO DE EMERGENCIA")

            app.root.after(
                0,
                lambda: app.emergency_motor_cut(
                    "STOP POR GESTO: motores apagados directamente"
                )
            )

            return True

        return False

    # ==========================
    # MOVIMIENTO NORMAL
    # ==========================

    if not app.has_taken_off or app.is_landing:
        return False

    if filtered_command == detector.DERECHA:
        print("[GESTO] DERECHA detectado -> mover +Y")
        app.root.after(
            0,
            lambda: app.move_drone(0.0, dc.STEP_XY, 0.0)
        )
        return True

    if filtered_command == detector.IZQUIERDA:
        print("[GESTO] IZQUIERDA detectado -> mover -Y")
        app.root.after(
            0,
            lambda: app.move_drone(0.0, -dc.STEP_XY, 0.0)
        )
        return True

    if filtered_command == detector.ARRIBA:
        print("[GESTO] ARRIBA detectado -> subir")
        app.root.after(
            0,
            lambda: app.move_drone(0.0, 0.0, dc.STEP_Z)
        )
        return True

    if filtered_command == detector.ABAJO:
        print("[GESTO] ABAJO detectado -> bajar")
        app.root.after(
            0,
            lambda: app.move_drone(0.0, 0.0, -dc.STEP_Z)
        )
        return True

    if filtered_command == detector.ADELANTE:
        print("[GESTO] ADELANTE detectado -> mover +X")
        app.root.after(
            0,
            lambda: app.move_drone(dc.STEP_XY, 0.0, 0.0)
        )
        return True

    if filtered_command == detector.ATRAS:
        print("[GESTO] ATRAS detectado -> mover -X")
        app.root.after(
            0,
            lambda: app.move_drone(-dc.STEP_XY, 0.0, 0.0)
        )
        return True

    return False


# =======================================================
# LOOP DE CONTROL POR GESTOS
# =======================================================

def gesture_control_loop(app, stop_event):
    """
    Controla el dron con gestos de mano:

    DESPEGAR  -> inicia hover
    ATERRIZAR -> aterrizaje normal
    STOP      -> paro de emergencia, motores OFF
    DERECHA   -> +Y
    IZQUIERDA -> -Y
    ARRIBA    -> +Z
    ABAJO     -> -Z
    ADELANTE  -> +X
    ATRAS     -> -X
    """

    print("Iniciando ventana de control por gestos...")

    cap = cv2.VideoCapture(CAMERA_INDEX)

    if not cap.isOpened():
        print("ERROR: no se pudo abrir la cámara.")
        print("Revisa CAMERA_INDEX en Gesture_control/config.py")
        return

    tracker = HandTracker(
        max_num_hands=MAX_NUM_HANDS,
        min_detection_confidence=MIN_DETECTION_CONFIDENCE,
        min_tracking_confidence=MIN_TRACKING_CONFIDENCE,
    )

    detector = HandGestureDetector(tracker.landmark_enum)

    last_action_time = 0.0
    prev_time = 0.0

    try:
        while not stop_event.is_set() and not app.is_landing:
            success, frame = cap.read()

            if not success:
                print("ERROR: no se recibió imagen de la cámara.")
                break

            frame = cv2.flip(frame, 1)

            annotated_frame, landmarks, handedness = tracker.process(frame)

            raw_command, filtered_command, debug = detector.detect(
                landmarks,
                handedness
            )

            fps, prev_time = calculate_fps(prev_time)

            now = time.time()

            # STOP debe poder ejecutarse más rápido que los movimientos normales.
            if filtered_command == detector.STOP:
                can_execute = (now - last_action_time) >= STOP_COOLDOWN_S
            else:
                can_execute = (now - last_action_time) >= GESTURE_COOLDOWN_S

            if can_execute:
                executed = execute_gesture_command(
                    app,
                    detector,
                    filtered_command
                )

                if executed:
                    last_action_time = now

            put_gesture_panel(
                annotated_frame,
                filtered_command,
                raw_command,
                handedness if handedness is not None else "None",
                fps,
                debug,
            )

            cv2.imshow("Control gestual Crazyflie", annotated_frame)

            key = cv2.waitKey(1) & 0xFF

            if key == ord("q"):
                print("Ventana de gestos cerrada con q.")
                break

    except Exception as e:
        print("ERROR en control por gestos:", e)

    finally:
        stop_event.set()
        cap.release()
        cv2.destroyAllWindows()
        tracker.close()
        print("Control por gestos detenido.")


# =======================================================
# ABRIR PANEL + CÁMARA
# =======================================================

def open_panel_with_gestures(cf):
    print(
        "Abriendo panel de control. "
        "El dron puede despegar con botón o con gesto DESPEGAR."
    )

    root = dc.tk.Tk()
    app = dc.DroneControlPanel(root, cf)

    stop_gesture_event = threading.Event()

    gesture_thread = threading.Thread(
        target=gesture_control_loop,
        args=(app, stop_gesture_event),
        daemon=True
    )

    gesture_thread.start()

    try:
        root.mainloop()

    finally:
        stop_gesture_event.set()
        gesture_thread.join(timeout=1.0)


# =======================================================
# MAIN
# =======================================================

def main():
    cflib.crtp.init_drivers()

    mqtt_thread = threading.Thread(target=dc.start_mqtt, daemon=True)
    mqtt_thread.start()

    time.sleep(1.0)

    print("Conectando al Crazyflie...")

    battery_logger = None

    try:
        with SyncCrazyflie(dc.URI, cf=Crazyflie(rw_cache="./cache")) as scf:
            dc.cf_global = scf.cf
            print("Conectado correctamente.")

            dc.setup_crazyflie_for_mocap(dc.cf_global)

            battery_logger = dc.BatteryLogger(dc.cf_global)
            battery_logger.start()

            open_panel_with_gestures(dc.cf_global)

    except Exception as e:
        print("Error general:", e)

    finally:
        if battery_logger is not None:
            battery_logger.stop()

        dc.cf_global = None
        dc.stop_mqtt_event.set()
        mqtt_thread.join(timeout=1.0)

        dc.plot_flight_results()

        print("Programa terminado.")


if __name__ == "__main__":
    main()