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
from pathlib import Path

import cflib.crtp
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie
from cflib.positioning.motion_commander import MotionCommander

SHARED_DIR = Path(__file__).resolve().parents[2] / "shared"
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))
from flowdeck_flight import (  # noqa: E402
    DEFAULT_HEIGHT_M,
    arm_if_supported,
    emergency_stop_motion_commander,
    require_flow_deck,
    reset_and_wait_for_estimator,
)
from radios import select_uri  # noqa: E402

DEFAULT_HOVER_S = 5.0


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
    with SyncCrazyflie(uri, cf=Crazyflie(rw_cache="./cache/flowdeck")) as scf:
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
