"""Control por gestos usando el controlador low-level validado."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import cflib.crtp
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie


LEGACY_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = Path(__file__).resolve().parents[3]
DRONE_DIR = LEGACY_DIR / "drone_control"
GESTURE_DIR = PROJECT_DIR / "Gesture_control"

for directory in (DRONE_DIR, GESTURE_DIR):
    if str(directory) not in sys.path:
        sys.path.append(str(directory))

import control as base_control
import control_lowlevel_companero as flight_control
import control_gestos_basico as gestures


# Movimientos más ágiles sin modificar la variante de gestos anterior.
GESTURE_COOLDOWN_S = 1.25


def open_panel_with_gestures(cf, diagnostic_logger) -> None:
    """Muestra el panel low-level y la cámara de gestos en paralelo."""
    print(
        "Abriendo control gestual low-level. "
        "El dron despega con botón o gesto DESPEGAR."
    )
    root = base_control.tk.Tk()
    app = flight_control.CompanionLowLevelPanel(root, cf)
    diagnostic_logger.panel = app

    stop_gesture_event = threading.Event()
    gesture_thread = threading.Thread(
        target=gestures.gesture_control_loop,
        args=(app, stop_gesture_event),
        daemon=True,
    )
    gesture_thread.start()

    try:
        root.mainloop()
    finally:
        stop_gesture_event.set()
        gesture_thread.join(timeout=1.0)


def main() -> None:
    # El módulo original de gestos consulta "dc" internamente. Se le entrega
    # el mismo módulo base configurado por control_lowlevel_companero.
    gestures.dc = flight_control.dc
    gestures.GESTURE_COOLDOWN_S = GESTURE_COOLDOWN_S
    # Pasos verticales menores para que mantener ARRIBA/ABAJO no cambie la
    # altura objetivo demasiado rápido.
    flight_control.dc.STEP_Z = 0.03

    cflib.crtp.init_drivers(enable_debug_driver=False)
    base_control.stop_mqtt_event.clear()
    mqtt_thread = threading.Thread(
        target=base_control.start_mqtt,
        daemon=True,
    )
    mqtt_thread.start()

    battery_logger = None
    diagnostic_logger = None
    try:
        print("Conectando al Crazyflie...")
        with SyncCrazyflie(
            base_control.URI,
            cf=Crazyflie(rw_cache="./cache"),
        ) as scf:
            base_control.cf_global = scf.cf
            print("Conectado correctamente.")
            flight_control.configure_lowlevel_global(base_control.cf_global)

            battery_logger = base_control.BatteryLogger(base_control.cf_global)
            battery_logger.start()
            diagnostic_logger = flight_control.DiagnosticCsvLogger(
                base_control.cf_global
            )
            diagnostic_logger.start()
            open_panel_with_gestures(base_control.cf_global, diagnostic_logger)
    except Exception as exc:
        print("Error general:", exc)
    finally:
        if diagnostic_logger is not None:
            diagnostic_logger.stop()
        if battery_logger is not None:
            battery_logger.stop()
        base_control.cf_global = None
        base_control.stop_mqtt_event.set()
        mqtt_thread.join(timeout=1.0)
        base_control.plot_flight_results()
        print("Programa terminado.")


if __name__ == "__main__":
    main()
