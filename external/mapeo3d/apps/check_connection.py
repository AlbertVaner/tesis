"""Diagnostica por qué no conecta una cámara IP.

`check_stream.py` dice «no llegó ningún frame» y ahí se acaba: OpenCV no
distingue una IP equivocada de una contraseña mal puesta o de una ruta RTSP que
no existe en ese modelo, y las tres se arreglan de forma distinta. Esta app
habla RTSP directamente y dice cuál de las tres es.

Ejemplos
--------
Buscar cámaras en la red local::

    python apps/check_connection.py --scan

Diagnosticar una cámara de la configuración::

    python apps/check_connection.py --camera cam3

Probar una IP y unas credenciales sueltas, sin tocar la configuración::

    python apps/check_connection.py --host 192.168.1.108 --user admin --password ***

Sondear todas las cámaras configuradas::

    python apps/check_connection.py --todas
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from mapeo3d.capture import (  # noqa: E402
    ConfigNotFound,
    escanear,
    load_config,
    prefijo_local,
    sondear,
)
from mapeo3d.capture.urls import RTSP_PATHS  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Diagnostica la conexión con una cámara IP.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    modo = p.add_mutually_exclusive_group(required=True)
    modo.add_argument("--scan", action="store_true",
                      help="Buscar cámaras con RTSP abierto en la red local.")
    modo.add_argument("--camera", help="Cámara de la configuración.")
    modo.add_argument("--host", help="IP a sondear directamente.")
    modo.add_argument("--todas", action="store_true",
                      help="Sondear todas las cámaras de la configuración.")

    p.add_argument("--config", help="Ruta de configuración alternativa.")
    p.add_argument("--user", help="Usuario, si no se usa la configuración.")
    p.add_argument("--password", help="Contraseña, si no se usa la configuración.")
    p.add_argument("--port", type=int, default=554)
    p.add_argument("--prefijo", help="Subred a escanear, p. ej. 192.168.1")
    p.add_argument("--timeout", type=float, default=2.0)
    return p.parse_args()


def _credenciales(args) -> tuple[str, str]:
    usuario = args.user or os.environ.get("CAM_USER", "")
    clave = args.password or os.environ.get("CAM_PASSWORD", "")
    return usuario, clave


def modo_scan(args) -> int:
    prefijo = args.prefijo or prefijo_local()
    if not prefijo:
        print("No se pudo determinar la subred local. Indicarla con --prefijo.",
              file=sys.stderr)
        return 1
    print(f"Buscando cámaras con el puerto {args.port} abierto en "
          f"{prefijo}.1-254 …")
    encontradas = escanear(prefijo, args.port)
    if not encontradas:
        print("\nNinguna. Cosas que comprobar:")
        print("  - El PC y la cámara tienen que estar en la MISMA subred.")
        print(f"    El PC está en {prefijo}.x")
        print("  - Una Amcrest recién sacada de la caja hay que ACTIVARLA antes")
        print("    (crear la contraseña de administrador por su web o su app).")
        print("    Sin activar, el servicio RTSP no se levanta.")
        print("  - Si la cámara está por Wi-Fi y el PC por cable (o al revés),")
        print("    puede que estén en redes distintas aunque lo parezca.")
        print("  - Probar otra subred con --prefijo 192.168.0")
        return 1
    print(f"\nEncontradas {len(encontradas)}:")
    for h in encontradas:
        print(f"  {h}:{args.port}")
    print("\nPara diagnosticar una:")
    print(f"  python apps/check_connection.py --host {encontradas[0]} "
          f"--user admin --password TU_CLAVE")
    return 0


def informar(sondeo, nombre: str = "") -> None:
    print()
    print("=" * 68)
    if nombre:
        print(f"Cámara «{nombre}»")
    print(sondeo.resumen())
    print()
    print(sondeo.diagnostico())


def main() -> int:
    args = parse_args()

    if args.scan:
        return modo_scan(args)

    objetivos: list[tuple[str, str, str, str, int]] = []   # nombre,host,u,c,puerto

    if args.host:
        u, c = _credenciales(args)
        if not u:
            print("AVISO: sin usuario. Se sondeará hasta el 401, que ya dice si\n"
                  "la cámara está viva y habla RTSP.\n")
        objetivos.append(("", args.host, u, c, args.port))
    else:
        try:
            cfg = load_config(args.config)
        except ConfigNotFound as e:
            print(e, file=sys.stderr)
            return 1
        camaras = cfg.cameras if args.todas else [cfg.camera(args.camera)]
        for cam in camaras:
            objetivos.append((cam.name, cam.host, cam.user, cam.password,
                              cam.port))

    fallos = 0
    for nombre, host, usuario, clave, puerto in objetivos:
        s = sondear(host, usuario, clave, puerto, timeout=args.timeout)
        informar(s, nombre)
        if not s.conecta:
            fallos += 1
        elif nombre:
            print(f"\n  Ya podés correr:  python apps/check_stream.py "
                  f"--camera {nombre}")

    if fallos:
        print()
        print("-" * 68)
        print("Modelos y rutas RTSP que conoce el repositorio:")
        for modelo, rutas in RTSP_PATHS.items():
            print(f"  {modelo}")
            for k, v in rutas.items():
                print(f"      {k}: {v}")
        print()
        print("Si tu cámara usa otra ruta, se añade en "
              "src/mapeo3d/capture/urls.py")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
