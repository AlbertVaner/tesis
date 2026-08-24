"""Control gestual de dos Crazyflies con el lazo low-level validado.

La interfaz conserva todos los botones del panel de dos drones y agrega una
camara con dos modos seguros:

* Independiente: mano Right -> Dron 1; mano Left -> Dron 2.
* Derecha ambos: la mano Right controla ambos drones en sincronizacion.

DESPEGAR y ATERRIZAR requieren sostener el gesto durante un segundo. El punio
cerrado sostenido medio segundo es un paro de emergencia global.
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import cflib.crtp

from control_dos_drones_botones_lowlevel import App as ButtonApp
from prueba_estabilidad_dos_drones_lowlevel import (
    DEFAULT_TOPIC_1,
    DEFAULT_TOPIC_2,
    DEFAULT_URI_1,
    DEFAULT_URI_2,
    MIN_SEPARATION_M,
    DroneUnit,
)


ROOT_DIR = Path(__file__).resolve().parents[1]
GESTURE_DIR = ROOT_DIR / "Gesture_control"
if str(GESTURE_DIR) not in sys.path:
    sys.path.insert(0, str(GESTURE_DIR))

from config import CAMERA_INDEX, MIN_DETECTION_CONFIDENCE, MIN_TRACKING_CONFIDENCE
from hand_gesture_detector import HandGestureDetector
from hand_tracker import HandTracker


GESTURE_COOLDOWN_S = 1.25
STOP_HOLD_S = 0.50

GESTURE_MOVES = {
    "ADELANTE": (0.05, 0.0, 0.0),
    "ATRAS": (-0.05, 0.0, 0.0),
    # Mantener la misma convención gestual que el controlador individual.
    "DERECHA": (0.0, 0.05, 0.0),
    "IZQUIERDA": (0.0, -0.05, 0.0),
    "ARRIBA": (0.0, 0.0, 0.03),
    "ABAJO": (0.0, 0.0, -0.03),
}
GESTURE_FLIGHT_COMMANDS = {"DESPEGAR", "ATERRIZAR"}
GESTURE_SETTLE_XY_M = 0.06
GESTURE_SETTLE_Z_M = 0.05

GESTURE_LOG_COLUMNS = [
    "fecha_hora", "tiempo_s", "modo", "mano", "comando_crudo",
    "comando_filtrado", "accion_intentada", "feedback", "orientacion",
    "pulgar_extendido", "indice_extendido", "medio_extendido",
    "anular_extendido", "menique_extendido",
]


class GestureDualApp(ButtonApp):
    """Panel low-level con una fuente adicional de comandos: dos manos."""

    def __init__(self, first: DroneUnit, second: DroneUnit, camera_index: int) -> None:
        self.camera_index = camera_index
        self._camera_stop = threading.Event()
        self._camera_thread: threading.Thread | None = None
        self._camera_lock = threading.RLock()
        self._camera_active = False
        self._camera_state = "Camara detenida. Puedes activarla incluso antes de despegar."
        self._gesture_mode_value = "INDEPENDIENTE"
        self._last_action = {"Right": 0.0, "Left": 0.0, "Both": 0.0}
        self._critical_consumed = {"Right": None, "Left": None}
        self._stop_started_at: float | None = None
        super().__init__(first, second)
        self.title("Dos Crazyflies - gestos y botones low-level")
        self.geometry("940x980")
        # En la presentacion anterior el panel de gestos quedaba debajo del
        # borde visible en pantallas pequenas. Esta maquina usa Windows.
        self.state("zoomed")

    def _build(self) -> None:
        super()._build()

        import tkinter as tk

        self.gesture_mode = tk.StringVar(value="INDEPENDIENTE")
        self.gesture_text = tk.StringVar(value=self._camera_state)
        self._gesture_window: tk.Toplevel | None = None
        tk.Button(
            self.top_controls,
            text="GESTOS / CAMARA",
            width=20,
            bg="#285a8f",
            fg="white",
            command=self.open_gesture_window,
        ).grid(row=0, column=4, padx=5)

    def open_gesture_window(self) -> None:
        """Abre un panel compacto siempre visible para la camara y sus modos."""
        import tkinter as tk

        if self._gesture_window is not None and self._gesture_window.winfo_exists():
            self._gesture_window.deiconify()
            self._gesture_window.lift()
            self._gesture_window.focus_force()
            return

        window = tk.Toplevel(self)
        self._gesture_window = window
        window.title("Gestos y camara - dos Crazyflies")
        window.geometry("640x285")
        window.resizable(False, False)
        window.transient(self)
        window.columnconfigure(0, weight=1)

        tk.Label(window, text="CONTROL POR GESTOS", font=("Segoe UI", 14, "bold")).grid(row=0, column=0, pady=(14, 8))
        modes = tk.Frame(window)
        modes.grid(row=1, column=0, padx=20, sticky="w")
        tk.Radiobutton(
            modes,
            text="Independiente: Right -> Dron 1 | Left -> Dron 2",
            variable=self.gesture_mode,
            value="INDEPENDIENTE",
            command=lambda: self._set_gesture_mode("INDEPENDIENTE"),
        ).pack(anchor="w")
        tk.Radiobutton(
            modes,
            text="Derecha controla ambos drones",
            variable=self.gesture_mode,
            value="DERECHA_AMBOS",
            command=lambda: self._set_gesture_mode("DERECHA_AMBOS"),
        ).pack(anchor="w")
        tk.Radiobutton(
            modes,
            text="Pausar gestos (solo observar camara)",
            variable=self.gesture_mode,
            value="PAUSADO",
            command=lambda: self._set_gesture_mode("PAUSADO"),
        ).pack(anchor="w")

        actions = tk.Frame(window)
        actions.grid(row=2, column=0, pady=10)
        tk.Button(actions, text="ACTIVAR CAMARA", width=22, bg="#398a31", fg="white", command=self.start_camera).grid(row=0, column=0, padx=5)
        tk.Button(actions, text="DETENER CAMARA", width=22, command=self.stop_camera).grid(row=0, column=1, padx=5)
        tk.Label(window, textvariable=self.gesture_text, wraplength=590, justify="left", fg="#24342d").grid(row=3, column=0, padx=20, sticky="w")
        tk.Label(
            window,
            text="Mantener un movimiento repite cada 1.25 s. Punio 0.5 s: emergencia.",
            fg="#6b3d1a",
        ).grid(row=4, column=0, pady=(8, 0))
        window.protocol("WM_DELETE_WINDOW", window.destroy)

    def _set_gesture_mode(self, mode: str) -> None:
        with self._camera_lock:
            self._gesture_mode_value = mode
            self._critical_consumed = {"Right": None, "Left": None}
        names = {
            "INDEPENDIENTE": "Modo independiente seleccionado.",
            "DERECHA_AMBOS": "Modo sincronizado seleccionado: solo mano Right mueve a ambos.",
            "PAUSADO": "Gestos pausados: la camara puede seguir mostrando detecciones.",
        }
        self._set_camera_state(names[mode])

    def _set_camera_state(self, message: str) -> None:
        with self._camera_lock:
            self._camera_state = message

    def refresh(self) -> None:
        super().refresh()
        if hasattr(self, "gesture_text"):
            with self._camera_lock:
                active = self._camera_active
                message = self._camera_state
            prefix = "CAMARA ACTIVA - " if active else "CAMARA DETENIDA - "
            self.gesture_text.set(prefix + message)

    def start_camera(self) -> None:
        if self._camera_thread is not None and self._camera_thread.is_alive():
            self._set_camera_state("La camara ya esta activa.")
            return
        self._camera_stop.clear()
        self._camera_thread = threading.Thread(target=self._camera_loop, daemon=True, name="GestosDosDrones")
        self._camera_thread.start()

    def stop_camera(self) -> None:
        self._camera_stop.set()
        self._set_camera_state("Cerrando ventana de camara...")

    def emergency(self) -> None:
        self._camera_stop.set()
        super().emergency()

    def close(self) -> None:
        self._camera_stop.set()
        thread = self._camera_thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        super().close()

    def _gesture_single(self, unit: DroneUnit, command: str, hand: str) -> str:
        controller = self._controller_for(unit)
        movement = GESTURE_MOVES.get(command)
        if not self.ready or controller is None:
            return "Sistema no listo"
        if command == "DESPEGAR":
            result = controller.takeoff()
        elif command == "ATERRIZAR":
            result = controller.land()
        elif movement is not None:
            pose = unit.fresh_pose()
            with controller.lock:
                requested = None if controller.requested is None else list(controller.requested)
            if pose is None or requested is None:
                return f"{unit.name}: esperando posicion valida"
            if (
                math.hypot(requested[0] - pose.x, requested[1] - pose.y) > GESTURE_SETTLE_XY_M
                or abs(requested[2] - pose.z) > GESTURE_SETTLE_Z_M
            ):
                return f"{unit.name}: esperando alcanzar el objetivo anterior"
            result = controller.request_move(*movement)
        else:
            return "Gesto sin accion de vuelo"
        if result.ok:
            self.logger.event(unit.name, f"GESTO_{command}", f"mano={hand}; modo=independiente")
            return f"{hand} {command} -> {unit.name}"
        return f"{unit.name}: {result.message}"

    def _gesture_both(self, command: str) -> str:
        movement = GESTURE_MOVES.get(command)
        first_controller = self._controller_for(self.first)
        second_controller = self._controller_for(self.second)
        if not self.ready or first_controller is None or second_controller is None:
            return "Sistema no listo"
        if command in GESTURE_FLIGHT_COMMANDS:
            first_result = first_controller.takeoff() if command == "DESPEGAR" else first_controller.land()
            second_result = second_controller.takeoff() if command == "DESPEGAR" else second_controller.land()
            if first_result.ok:
                self.logger.event(self.first.name, f"GESTO_CONJUNTO_{command}", "mano=Right; modo=ambos")
            if second_result.ok:
                self.logger.event(self.second.name, f"GESTO_CONJUNTO_{command}", "mano=Right; modo=ambos")
            if first_result.ok and second_result.ok:
                return f"Right {command} -> ambos drones"
            failures = []
            if not first_result.ok:
                failures.append(f"Dron 1: {first_result.message}")
            if not second_result.ok:
                failures.append(f"Dron 2: {second_result.message}")
            return " | ".join(failures)
        if movement is None:
            return "Gesto sin accion de vuelo"

        # No acumular objetivos mientras cualquiera de los drones todavía
        # persigue el paso anterior. Mantener el gesto reintentará luego.
        for unit, controller in (
            (self.first, first_controller),
            (self.second, second_controller),
        ):
            pose = unit.fresh_pose()
            with controller.lock:
                requested = None if controller.requested is None else list(controller.requested)
            if pose is None or requested is None:
                return f"{unit.name}: esperando posicion valida"
            if (
                math.hypot(requested[0] - pose.x, requested[1] - pose.y) > GESTURE_SETTLE_XY_M
                or abs(requested[2] - pose.z) > GESTURE_SETTLE_Z_M
            ):
                return f"Esperando que {unit.name} alcance el objetivo anterior"

        first_result, first_target = first_controller.preview_move(*movement)
        second_result, second_target = second_controller.preview_move(*movement)
        if not first_result.ok or not second_result.ok or first_target is None or second_target is None:
            return "Ambos deben estar en hover antes del gesto conjunto"
        if math.dist(first_target, second_target) < MIN_SEPARATION_M:
            return "Gesto bloqueado: separacion objetivo insuficiente"
        with first_controller.lock, second_controller.lock:
            if first_controller.phase != "HOVER" or second_controller.phase != "HOVER":
                return "Ambos deben estar en hover antes del gesto conjunto"
            first_controller.requested = list(first_target)
            second_controller.requested = list(second_target)
        for unit in self.units:
            self.logger.event(unit.name, f"GESTO_CONJUNTO_{command}", "mano=Right; modo=ambos")
        return f"Right {command} -> ambos drones"

    def _execute_hand_command(self, hand: str, command: str, now: float) -> str | None:
        with self._camera_lock:
            mode = self._gesture_mode_value
            if command in {"REPOSO", "SIN_DETECCION"}:
                self._critical_consumed[hand] = None
                return None
        if mode == "PAUSADO" or (command not in GESTURE_MOVES and command not in GESTURE_FLIGHT_COMMANDS):
            return None
        # Los comandos críticos se ejecutan una sola vez mientras se mantienen.
        # Cambiar a otro gesto los vuelve a habilitar sin exigir REPOSO.
        if command in GESTURE_FLIGHT_COMMANDS and self._critical_consumed[hand] == command:
            return None
        if command not in GESTURE_FLIGHT_COMMANDS:
            self._critical_consumed[hand] = None
        key = "Both" if mode == "DERECHA_AMBOS" and hand == "Right" else hand
        if now - self._last_action[key] < GESTURE_COOLDOWN_S:
            return None
        if mode == "INDEPENDIENTE":
            unit = self.first if hand == "Right" else self.second
            message = self._gesture_single(unit, command, hand)
        elif hand == "Right":
            message = self._gesture_both(command)
        else:
            return None
        self._last_action[key] = now
        if command in GESTURE_FLIGHT_COMMANDS:
            with self._camera_lock:
                self._critical_consumed[hand] = command
        return message

    def _request_gesture_emergency(self) -> None:
        if self.emergency_event.is_set():
            return
        self.logger.event("SISTEMA", "EMERGENCIA_POR_GESTO", "punio cerrado sostenido")
        self._camera_stop.set()
        # Igual que en el control previo de gestos: se agenda en el hilo Tk.
        self.after(0, self.emergency)

    @staticmethod
    def _draw_overlay(frame, mode: str, hand_data: dict[str, tuple[str, str]], feedback: str) -> None:
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (frame.shape[1], 142), (12, 30, 12), -1)
        cv2.addWeighted(overlay, 0.72, frame, 0.28, 0, frame)
        cv2.putText(frame, "CONTROL GESTUAL - DOS CRAZYFLIES", (12, 27), cv2.FONT_HERSHEY_SIMPLEX, 0.70, (235, 255, 235), 2)
        cv2.putText(frame, f"Modo: {mode}", (12, 54), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (180, 240, 180), 1)
        y = 80
        for hand in ("Right", "Left"):
            raw, filtered = hand_data.get(hand, ("SIN_DETECCION", "SIN_DETECCION"))
            cv2.putText(frame, f"{hand}: {filtered}  (raw: {raw})", (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (240, 240, 240), 1)
            y += 22
        cv2.putText(frame, feedback[:100], (12, 136), cv2.FONT_HERSHEY_SIMPLEX, 0.43, (70, 225, 255), 1)

    def _camera_loop(self) -> None:
        cap = cv2.VideoCapture(self.camera_index)
        if not cap.isOpened():
            self._set_camera_state(f"No se pudo abrir la camara {self.camera_index}. Prueba --camera 1.")
            return
        tracker = None
        try:
            tracker = HandTracker(
                max_num_hands=2,
                min_detection_confidence=MIN_DETECTION_CONFIDENCE,
                min_tracking_confidence=MIN_TRACKING_CONFIDENCE,
            )
            detectors = {
                "Right": HandGestureDetector(tracker.landmark_enum),
                "Left": HandGestureDetector(tracker.landmark_enum),
            }
            with self._camera_lock:
                self._camera_active = True
                self._critical_consumed = {"Right": None, "Left": None}
            self._set_camera_state("Camara activa. q cierra solo la camara.")

            log_folder = Path(__file__).resolve().parent / "datos_dos_drones"
            log_folder.mkdir(exist_ok=True)
            log_path = log_folder / f"gestos_dos_drones_{datetime.now():%Y%m%d_%H%M%S}.csv"
            log_file = log_path.open("w", newline="", encoding="utf-8")
            log_writer = csv.DictWriter(log_file, fieldnames=GESTURE_LOG_COLUMNS)
            log_writer.writeheader()
            log_file.flush()
            log_start = time.monotonic()
            print(f"Registro gestual dual activo: {log_path.resolve()}")

            while not self._camera_stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    self._set_camera_state("No se recibio imagen de la camara.")
                    break
                frame = cv2.flip(frame, 1)
                annotated, detected = tracker.process_hands(frame)
                by_hand = {hand: None for hand in detectors}
                for landmarks, handedness in detected:
                    if handedness in by_hand and by_hand[handedness] is None:
                        by_hand[handedness] = landmarks

                now = time.monotonic()
                hand_data: dict[str, tuple[str, str]] = {}
                stop_detected = False
                feedback = "Muestra los gestos. q = cerrar camara."
                for hand, detector in detectors.items():
                    raw, filtered, debug = detector.detect(by_hand[hand], hand)
                    hand_data[hand] = (raw, filtered)
                    command_is_stable = raw == filtered
                    if command_is_stable and filtered == detector.STOP:
                        stop_detected = True
                    # El suavizado puede conservar el gesto anterior durante
                    # unos frames después de retirar la mano. No ejecutar una
                    # orden hasta que lectura cruda y filtrada coincidan.
                    action = (
                        self._execute_hand_command(hand, filtered, now)
                        if command_is_stable
                        else None
                    )
                    if action is not None:
                        feedback = action
                        self._set_camera_state(action)
                    log_writer.writerow({
                        "fecha_hora": datetime.now().isoformat(timespec="milliseconds"),
                        "tiempo_s": time.monotonic() - log_start,
                        "modo": self._gesture_mode_value,
                        "mano": hand,
                        "comando_crudo": raw,
                        "comando_filtrado": filtered,
                        "accion_intentada": action is not None,
                        "feedback": action or "",
                        "orientacion": debug.get("orientation"),
                        "pulgar_extendido": debug.get("thumb", False),
                        "indice_extendido": debug.get("index", False),
                        "medio_extendido": debug.get("middle", False),
                        "anular_extendido": debug.get("ring", False),
                        "menique_extendido": debug.get("pinky", False),
                    })
                log_file.flush()

                if stop_detected:
                    if self._stop_started_at is None:
                        self._stop_started_at = now
                        feedback = "STOP detectado: manten el punio 0.5 s para emergencia"
                    elif now - self._stop_started_at >= STOP_HOLD_S:
                        feedback = "EMERGENCIA POR GESTO"
                        self._request_gesture_emergency()
                        break
                else:
                    self._stop_started_at = None

                with self._camera_lock:
                    mode = self._gesture_mode_value
                self._draw_overlay(annotated, mode, hand_data, feedback)
                cv2.imshow("Gestos - dos Crazyflies", annotated)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    self._set_camera_state("Camara cerrada con q.")
                    break
        except Exception as exc:
            self._set_camera_state(f"Error en control gestual: {exc}")
            print("Error en control gestual:", exc)
        finally:
            self._camera_stop.set()
            with self._camera_lock:
                self._camera_active = False
            cap.release()
            cv2.destroyAllWindows()
            if tracker is not None:
                tracker.close()
            if "log_file" in locals():
                log_file.flush()
                log_file.close()
                print(f"Registro gestual dual guardado: {log_path.resolve()}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Control low-level de dos Crazyflies por botones y gestos")
    parser.add_argument("--uri1", default=DEFAULT_URI_1)
    parser.add_argument("--uri2", default=DEFAULT_URI_2)
    parser.add_argument("--topic1", default=DEFAULT_TOPIC_1)
    parser.add_argument("--topic2", default=DEFAULT_TOPIC_2)
    parser.add_argument("--camera", type=int, default=CAMERA_INDEX, help="Indice OpenCV de la camara")
    args = parser.parse_args()

    cflib.crtp.init_drivers(enable_debug_driver=False)
    GestureDualApp(
        DroneUnit("Dron 1", args.uri1, args.topic1),
        DroneUnit("Dron 2", args.uri2, args.topic2),
        args.camera,
    ).mainloop()


if __name__ == "__main__":
    main()
