"""Operaciones sobre un enlace Crazyflie que todos los controladores repiten.

Configurar el estimador para posición externa, reiniciar el Kalman, armar y
cortar motores. Ninguna función abre ni cierra la radio: reciben el `cf` ya
conectado.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

SHARED_DIR = Path(__file__).resolve().parent
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))
from flowdeck_feedback import configure_flowdeck_feedback  # noqa: E402


def reset_kalman(cf, hold_s: float = 0.10) -> None:
    """Pulso de `kalman.resetEstimation`."""
    cf.param.set_value("kalman.resetEstimation", "1")
    time.sleep(hold_s)
    cf.param.set_value("kalman.resetEstimation", "0")


def configure_estimator(
    cf,
    *,
    high_level: bool,
    settle_before_reset_s: float = 0.0,
    settle_after_reset_s: float = 0.0,
) -> None:
    """Prepara el Crazyflie para volar con posición externa del Robotat.

    Excluye la realimentación del Flow deck (si lo hay), fija controlador PID
    y estimador Kalman, activa o desactiva el commander high-level y reinicia
    el Kalman. Los tiempos de asentamiento los decide cada controlador.
    """
    configure_flowdeck_feedback(cf, enabled=False)
    cf.param.set_value("commander.enHighLevel", "1" if high_level else "0")
    cf.param.set_value("stabilizer.controller", "1")
    cf.param.set_value("stabilizer.estimator", "2")
    if settle_before_reset_s:
        time.sleep(settle_before_reset_s)
    reset_kalman(cf)
    if settle_after_reset_s:
        time.sleep(settle_after_reset_s)


def arm_if_supported(cf, *, log=print) -> None:
    """Arma explícitamente en cflib reciente; conserva compatibilidad antigua."""
    supervisor = getattr(cf, "supervisor", None)
    send_arming_request = getattr(supervisor, "send_arming_request", None)
    if callable(send_arming_request):
        send_arming_request(True)
        log("Solicitud de armado enviada.")
        time.sleep(1.0)
    else:
        # Las versiones anteriores de cflib/firmware no exponen Supervisor.
        # MotionCommander inicia el vuelo directamente en esas versiones.
        log("API antigua detectada: armado administrado por MotionCommander.")


def stop_motors(
    *cfs,
    repeats: int,
    interval_s: float,
    zero_velocity_first: bool = False,
) -> Exception | None:
    """Corta los motores de uno o varios Crazyflie repitiendo el stop setpoint.

    Se repite para aumentar la probabilidad de entrega por radio. Con varios
    `cf` se intercalan las repeticiones para que ninguno espere al otro. Las
    excepciones no interrumpen el corte; se devuelve la última para que el
    llamador la reporte si quiere.
    """
    last_error: Exception | None = None
    cfs = tuple(cf for cf in cfs if cf is not None)
    if zero_velocity_first:
        for cf in cfs:
            try:
                cf.commander.send_velocity_world_setpoint(0.0, 0.0, 0.0, 0.0)
            except Exception as exc:
                last_error = exc
    for _ in range(repeats):
        for cf in cfs:
            try:
                cf.commander.send_stop_setpoint()
            except Exception as exc:
                last_error = exc
        time.sleep(interval_s)
    return last_error
