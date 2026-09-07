"""Preparación y parada de un Crazyflie que vuela con Flow deck v2.

Compartido por el hover individual, el panel de teclado, el control por
cámara con Flow deck y el backend dual. No abre radios.
"""

from __future__ import annotations

import sys
import time
from collections import deque
from pathlib import Path

from cflib.crazyflie.log import LogConfig
from cflib.crazyflie.syncLogger import SyncLogger

SHARED_DIR = Path(__file__).resolve().parent
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))
from crazyflie_link import arm_if_supported, reset_kalman, stop_motors  # noqa: E402,F401
from flowdeck_feedback import configure_flowdeck_feedback  # noqa: E402

DEFAULT_HEIGHT_M = 0.35
ESTIMATOR_TIMEOUT_S = 20.0
VARIANCE_WINDOW = 10
VARIANCE_SPREAD_LIMIT = 0.001


def require_flow_deck(cf) -> None:
    """Detiene la prueba si el firmware no detecta el Flow deck v2."""
    value = cf.param.get_value("deck.bcFlow2")
    if value is None or int(value) == 0:
        raise RuntimeError(
            "El dron no detecta el Flow deck v2. Apague el dron y revise el montaje."
        )
    print("Flow deck v2 detectado correctamente.")


def reset_and_wait_for_estimator(cf) -> None:
    """Reinicia el Kalman y espera que sus varianzas se estabilicen."""
    configure_flowdeck_feedback(cf, enabled=True)
    print("Reiniciando el estimador Kalman...")
    reset_kalman(cf)
    time.sleep(1.0)

    log_config = LogConfig(name="KalmanVariance", period_in_ms=100)
    log_config.add_variable("kalman.varPX", "float")
    log_config.add_variable("kalman.varPY", "float")
    log_config.add_variable("kalman.varPZ", "float")

    history = {axis: deque(maxlen=VARIANCE_WINDOW) for axis in ("X", "Y", "Z")}
    deadline = time.monotonic() + ESTIMATOR_TIMEOUT_S

    with SyncLogger(cf, log_config) as logger:
        for _, data, _ in logger:
            for axis in history:
                history[axis].append(float(data[f"kalman.varP{axis}"]))

            full = all(len(values) == VARIANCE_WINDOW for values in history.values())
            stable = full and all(
                max(values) - min(values) < VARIANCE_SPREAD_LIMIT
                for values in history.values()
            )
            if stable:
                print("Estimador estable.")
                return
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "El estimador no se estabilizo en 20 s. No se iniciara el vuelo."
                )


def emergency_motor_stop(cf) -> None:
    """Corta los motores inmediatamente; el dron caera si esta volando."""
    print("\nPARADA DE EMERGENCIA: cortando motores.")
    stop_motors(cf, repeats=5, interval_s=0.02)


def emergency_stop_motion_commander(commander, cf) -> None:
    """Detiene el transmisor de MotionCommander antes de cortar los motores."""
    if commander is not None:
        motion_thread = getattr(commander, "_thread", None)
        if motion_thread is not None:
            try:
                motion_thread.stop()
            except Exception:
                pass
        # Impide que land()/stop() reutilicen un hilo que ya fue detenido.
        if hasattr(commander, "_thread"):
            commander._thread = None
        if hasattr(commander, "_is_flying"):
            commander._is_flying = False
    emergency_motor_stop(cf)
