r"""Hover de un Crazyflie con Flow deck v2, a elección del dron. Sin Robotat.

No usa mocap ni recibe posición externa: detecta la Crazyradio, valida el Flow
deck, espera a que converja el estimador, despega, mantiene la altura unos
segundos y aterriza. Es la prueba mínima de que un dron vuela solo con el deck,
antes de meterlo en un panel o en el control por cámara.

    .\.venv\Scripts\python.exe .\controllers\single_drone\hover_flowdeck.py
    .\.venv\Scripts\python.exe .\controllers\single_drone\hover_flowdeck.py --drone 2
    .\.venv\Scripts\python.exe .\controllers\single_drone\hover_flowdeck.py --altura 0.4 --tiempo 8

Teclado, el mismo que los paneles desde septiembre de 2026: **R corta motores**
en el acto y Ctrl+C aterriza de forma normal. Antes el corte era Q; cambió al
asignar Q y E al giro en los paneles, y aquí se sigue para no tener dos teclas
de emergencia distintas según el programa.

Vive en `single_drone/` y no en una carpeta por deck porque el deck es una
opción de vuelo, no una categoría de control: lo elige `--backend flowdeck` en
los controladores. Este archivo es la excepción justificada, porque no es un
controlador sino una prueba de hardware de un solo dron.
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

SHARED_DIR = Path(__file__).resolve().parents[1] / "shared"
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))
from crazyflie_link import arm_if_supported  # noqa: E402
from flowdeck_flight import (  # noqa: E402
    DEFAULT_HEIGHT_M,
    emergency_stop_motion_commander,
    require_flow_deck,
    reset_and_wait_for_estimator,
)
from radios import DRONE_1_LINK, DRONE_2_LINK, make_uri, select_radio  # noqa: E402

DEFAULT_HOVER_S = 5.0
MIN_HEIGHT_M = 0.20
MAX_HEIGHT_M = 1.00


def wait_for_start_confirmation() -> bool:
    """Espera ENTER para volar; R cancela sin encender los motores."""
    print("\nDron validado y listo.")
    print("Alejate de las helices y despeja el area de vuelo.")
    print("ENTER para despegar, R para cancelar.")
    while True:
        key = msvcrt.getwch()
        if key in ("\r", "\n"):
            return True
        if key.lower() == "r":
            return False


def hold_hover(commander: MotionCommander, cf: Crazyflie, hover_s: float) -> bool:
    """Mantiene el hover; devuelve False si R produjo un corte de emergencia."""
    print(f"Hover durante {hover_s:.1f} s.")
    print("R = CORTE INMEDIATO DE MOTORES | Ctrl+C = aterrizaje normal")
    deadline = time.monotonic() + hover_s
    while time.monotonic() < deadline:
        if msvcrt.kbhit():
            key = msvcrt.getwch()
            if key.lower() == "r":
                emergency_stop_motion_commander(commander, cf)
                return False
        # Reafirma la orden de quedarse quieto y deja leer el teclado rapido.
        commander.stop()
        time.sleep(0.05)
    return True


def hover(uri: str, nombre: str, height_m: float, hover_s: float) -> None:
    """Conecta el dron elegido, hace hover y garantiza un intento de aterrizaje."""
    print(f"Conectando el {nombre} mediante {uri}...")
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
            print("Motores detenidos por R. No despegues de nuevo sin revisar el dron.")
        else:
            print("Aterrizaje completado.")


def positive_float(value: str) -> float:
    number = float(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("el valor debe ser mayor que cero")
    return number


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Hover de un Crazyflie con Flow deck v2, sin Robotat"
    )
    parser.add_argument("--drone", choices=("1", "2"), default="1",
                        help="cual de los dos drones de la cruz vuela")
    parser.add_argument("--radio", help="serial de la Crazyradio; si se omite, "
                                        "selecciona una conectada")
    parser.add_argument("--uri", help="URI completa; tiene prioridad sobre "
                                      "--drone y --radio")
    parser.add_argument("--altura", type=positive_float, default=DEFAULT_HEIGHT_M,
                        help=f"altura del hover en metros (predeterminado: {DEFAULT_HEIGHT_M})")
    parser.add_argument("--tiempo", type=positive_float, default=DEFAULT_HOVER_S,
                        help=f"duracion del hover en segundos (predeterminado: {DEFAULT_HOVER_S})")
    return parser.parse_args()


def resolve_uri(args: argparse.Namespace) -> str:
    """URI del dron elegido. `--uri` gana; si no, el enlace de ese dron."""
    if args.uri:
        return args.uri
    link = DRONE_1_LINK if args.drone == "1" else DRONE_2_LINK
    return make_uri(select_radio(args.radio), link)


def main() -> int:
    args = parse_args()
    if not MIN_HEIGHT_M <= args.altura <= MAX_HEIGHT_M:
        print(f"ERROR: usa una altura entre {MIN_HEIGHT_M:.2f} m y "
              f"{MAX_HEIGHT_M:.2f} m.", file=sys.stderr)
        return 2

    logging.basicConfig(level=logging.ERROR)
    try:
        cflib.crtp.init_drivers(enable_debug_driver=False)
        hover(resolve_uri(args), f"Dron {args.drone}", args.altura, args.tiempo)
    except KeyboardInterrupt:
        print("\nInterrupcion solicitada; se ejecuto la salida segura del vuelo.")
        return 130
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
