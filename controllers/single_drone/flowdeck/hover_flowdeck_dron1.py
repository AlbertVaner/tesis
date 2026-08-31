r"""Prueba de hover del Dron 1 usando solamente el Flow deck v2.

No usa Robotat ni recibe posicion externa. Detecta una Crazyradio conectada,
valida el Flow deck, espera que el estimador Kalman converja, despega, mantiene
altura durante unos segundos y aterriza.

Uso normal:
    .\.venv\Scripts\python.exe .\controllers\single_drone\flowdeck\hover_flowdeck_dron1.py

Elegir una antena concreta:
    .\.venv\Scripts\python.exe .\controllers\single_drone\flowdeck\hover_flowdeck_dron1.py --radio 9DD2507072
"""

from __future__ import annotations

import argparse
import logging
import msvcrt
import sys
import time
from collections import deque

import cflib.crtp
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.log import LogConfig
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie
from cflib.crazyflie.syncLogger import SyncLogger
from cflib.drivers.crazyradio import get_serials
from cflib.positioning.motion_commander import MotionCommander


DRONE_1_CHANNEL = 84
DRONE_1_RATE = "2M"
DRONE_1_ADDRESS = "E7E7E7E7E4"
KNOWN_RADIOS = ("2B1D933FCC", "9DD2507072")

DEFAULT_HEIGHT_M = 0.35
DEFAULT_HOVER_S = 5.0
ESTIMATOR_TIMEOUT_S = 20.0
VARIANCE_WINDOW = 10
VARIANCE_SPREAD_LIMIT = 0.001


def connected_radios() -> list[str]:
    """Devuelve los seriales de las Crazyradio conectadas por USB."""
    return [str(serial).upper() for serial in get_serials()]


def select_uri(explicit_uri: str | None, requested_radio: str | None) -> str:
    """Construye la URI del Dron 1 usando una antena disponible."""
    if explicit_uri:
        return explicit_uri

    radios = connected_radios()
    if not radios:
        raise RuntimeError("No se detecto ninguna Crazyradio conectada por USB.")

    if requested_radio:
        serial = requested_radio.upper()
        if serial not in radios:
            raise RuntimeError(
                f"La antena {serial} no esta conectada. Detectadas: {', '.join(radios)}"
            )
    else:
        preferred = [serial for serial in KNOWN_RADIOS if serial in radios]
        serial = preferred[0] if preferred else radios[0]

    return f"radio://{serial}/{DRONE_1_CHANNEL}/{DRONE_1_RATE}/{DRONE_1_ADDRESS}"


def require_flow_deck(cf: Crazyflie) -> None:
    """Detiene la prueba si el firmware no detecta el Flow deck v2."""
    value = cf.param.get_value("deck.bcFlow2")
    if value is None or int(value) == 0:
        raise RuntimeError(
            "El Dron 1 no detecta el Flow deck v2. Apague el dron y revise el montaje."
        )
    print("Flow deck v2 detectado correctamente.")


def reset_and_wait_for_estimator(cf: Crazyflie) -> None:
    """Reinicia el Kalman y espera que sus varianzas se estabilicen."""
    print("Reiniciando el estimador Kalman...")
    cf.param.set_value("kalman.resetEstimation", "1")
    time.sleep(0.1)
    cf.param.set_value("kalman.resetEstimation", "0")
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


def arm_if_supported(cf: Crazyflie) -> None:
    """Arma explícitamente en cflib reciente; conserva compatibilidad antigua."""
    supervisor = getattr(cf, "supervisor", None)
    send_arming_request = getattr(supervisor, "send_arming_request", None)
    if callable(send_arming_request):
        send_arming_request(True)
        print("Solicitud de armado enviada.")
        time.sleep(1.0)
    else:
        # Las versiones anteriores de cflib/firmware no exponen Supervisor.
        # MotionCommander inicia el vuelo directamente en esas versiones.
        print("API antigua detectada: armado administrado por MotionCommander.")


def wait_for_start_confirmation() -> bool:
    """Espera ENTER para volar; Q cancela sin encender los motores."""
    print("\nDron validado y listo.")
    print("Alejese de las helices y despeje el area de vuelo.")
    print("Presione ENTER para despegar o Q para cancelar.")
    while True:
        key = msvcrt.getwch()
        if key in ("\r", "\n"):
            return True
        if key.lower() == "q":
            return False


def emergency_motor_stop(cf: Crazyflie) -> None:
    """Corta los motores inmediatamente; el dron caera si esta volando."""
    print("\nPARADA DE EMERGENCIA: cortando motores.")
    # Se repite para aumentar la probabilidad de entrega por radio.
    for _ in range(5):
        cf.commander.send_stop_setpoint()
        time.sleep(0.02)


def emergency_stop_motion_commander(
    commander: MotionCommander | None, cf: Crazyflie
) -> None:
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


def hold_hover(commander: MotionCommander, cf: Crazyflie, hover_s: float) -> bool:
    """Mantiene el hover; devuelve False si Q produjo un corte de emergencia."""
    print(f"Hover durante {hover_s:.1f} s.")
    print("Q = CORTE INMEDIATO DE MOTORES | Ctrl+C = aterrizaje normal")
    deadline = time.monotonic() + hover_s
    while time.monotonic() < deadline:
        if msvcrt.kbhit():
            key = msvcrt.getwch()
            if key.lower() == "q":
                emergency_stop_motion_commander(commander, cf)
                return False
        # Reafirma la orden de quedarse quieto y permite leer el teclado rápido.
        commander.stop()
        time.sleep(0.05)
    return True


def hover(uri: str, height_m: float, hover_s: float) -> None:
    """Conecta el Dron 1, hace hover y garantiza un intento de aterrizaje."""
    print(f"Conectando el Dron 1 mediante {uri}...")
    with SyncCrazyflie(uri, cf=Crazyflie(rw_cache="./cache_flowdeck")) as scf:
        require_flow_deck(scf.cf)
        reset_and_wait_for_estimator(scf.cf)

        if not wait_for_start_confirmation():
            print("Prueba cancelada. Los motores no fueron encendidos.")
            return

        print(f"Despegando a {height_m:.2f} m...")
        arm_if_supported(scf.cf)

        commander = MotionCommander(scf, default_height=height_m)
        emergency = False
        try:
            commander.take_off()
            commander.stop()
            emergency = not hold_hover(commander, scf.cf, hover_s)
        finally:
            if not emergency:
                print("Iniciando aterrizaje normal...")
                commander.land()

        if emergency:
            print("Motores detenidos por Q. No intente despegar de nuevo sin revisar el dron.")
        else:
            print("Aterrizaje completado.")


def positive_float(value: str) -> float:
    number = float(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("el valor debe ser mayor que cero")
    return number


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Hover del Dron 1 con Flow deck v2, sin Robotat."
    )
    parser.add_argument(
        "--radio",
        help="serial de la Crazyradio; si se omite, selecciona una conectada",
    )
    parser.add_argument(
        "--uri",
        help="URI completa; tiene prioridad sobre --radio",
    )
    parser.add_argument(
        "--altura",
        type=positive_float,
        default=DEFAULT_HEIGHT_M,
        help=f"altura del hover en metros (predeterminado: {DEFAULT_HEIGHT_M})",
    )
    parser.add_argument(
        "--tiempo",
        type=positive_float,
        default=DEFAULT_HOVER_S,
        help=f"duracion del hover en segundos (predeterminado: {DEFAULT_HOVER_S})",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 0.20 <= args.altura <= 1.0:
        print("ERROR: use una altura entre 0.20 m y 1.00 m.", file=sys.stderr)
        return 2

    logging.basicConfig(level=logging.ERROR)
    try:
        cflib.crtp.init_drivers(enable_debug_driver=False)
        uri = select_uri(args.uri, args.radio)
        hover(uri, args.altura, args.tiempo)
    except KeyboardInterrupt:
        print("\nInterrupcion solicitada; se ejecuto la salida segura del vuelo.")
        return 130
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
