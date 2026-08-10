"""Prueba segura de conexión a un Crazyflie.

No arma ni envía setpoints: solo abre el enlace, confirma la conexión y lo
cierra. Útil después de asignar una nueva dirección de radio al dron.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time

import cflib.crtp
from cflib.crazyflie import Crazyflie


DEFAULT_URI = "radio://0/84/2M/E7E7E7E7E5"


def main() -> int:
    parser = argparse.ArgumentParser(description="Prueba segura de enlace Crazyflie")
    parser.add_argument("--uri", default=DEFAULT_URI, help="URI del Crazyflie a probar")
    parser.add_argument("--timeout", type=float, default=10.0, help="Tiempo máximo de conexión (s)")
    args = parser.parse_args()

    connected = threading.Event()
    failed = threading.Event()
    failure_message = [""]

    cflib.crtp.init_drivers(enable_debug_driver=False)
    cf = Crazyflie(rw_cache="./cache")

    def on_connected(uri: str) -> None:
        print(f"\nCONECTADO CORRECTAMENTE a: {uri}")
        print("No se enviaron comandos de vuelo ni se armaron motores.")
        connected.set()

    def on_connection_failed(uri: str, message: str) -> None:
        failure_message[0] = message
        print(f"\nFALLO DE CONEXIÓN a {uri}: {message}")
        failed.set()

    def on_connection_lost(uri: str, message: str) -> None:
        if not connected.is_set():
            failure_message[0] = message
            failed.set()
        print(f"Conexión cerrada: {message}")

    cf.connected.add_callback(on_connected)
    cf.connection_failed.add_callback(on_connection_failed)
    cf.connection_lost.add_callback(on_connection_lost)

    print("=" * 58)
    print("PRUEBA SEGURA DE CONEXIÓN — MOTORES DESACTIVADOS")
    print(f"URI: {args.uri}")
    print("Asegúrate de cerrar CFclient, la web y otros scripts que usen la antena.")
    print("=" * 58)

    try:
        cf.open_link(args.uri)
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline and not connected.is_set() and not failed.is_set():
            time.sleep(0.05)

        if connected.is_set():
            time.sleep(1.0)
            return_code = 0
        elif failed.is_set():
            return_code = 1
        else:
            print(f"\nTIEMPO AGOTADO: no hubo respuesta en {args.timeout:.1f} s.")
            return_code = 1
    except Exception as exc:  # muestra un diagnóstico útil sin tocar el dron
        print(f"\nERROR AL ABRIR EL ENLACE: {exc}")
        return_code = 1
    finally:
        try:
            cf.close_link()
        except Exception:
            pass

    if return_code:
        print("\nVerifica: batería encendida, URI, antena libre y canal 84 / 2M.")
    else:
        print("\nPrueba superada. El URI ya se puede usar en tus programas.")
    return return_code


if __name__ == "__main__":
    sys.exit(main())
