"""Mide la velocidad angular y la repetibilidad del pan/tilt de la camara.

Por que hace falta
------------------
El seguidor se mueve a pasos acotados, y cuanto recorre un paso es
`velocidad_angular x duracion`. La duracion esta atada a la latencia HTTP
(~300 ms, no se puede bajar), asi que **la velocidad angular decide si el
seguimiento se pasa de largo o no**, y no esta publicada en ninguna hoja de
datos: hay que medirla.

En simulacion, con las latencias medidas del laboratorio, el lazo es estable
por debajo de unos 140 grados/s a velocidad 1 y oscila por encima de 180. Este
script dice de que lado esta la camara.

De paso mide la **repetibilidad**: va y vuelve el mismo paso, y el residuo es
cuanto se desvia el motor al repetir un movimiento. Ese numero decide si la via
de los presets serviria el dia que se retome la calibracion.

Uso, desde la raiz del repositorio::

    .\\.venv\\Scripts\\python.exe .\\external\\gesture_detection\\medir_ptz.py ^
        --rtsp "rtsp://usuario:clave@IP:554/cam/realmonitor?channel=1&subtype=1" --confirmar

MUEVE LOS MOTORES. Requiere `--confirmar` para no ejecutarse por accidente, e
invalida cualquier calibracion extrinseca previa.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from camara_env import AYUDA_RTSP, resolver_rtsp  # noqa: E402
from ptz import CamaraPTZ, ErrorPTZ, resumen_capacidades  # noqa: E402

IZQUIERDA, DERECHA = "Left", "Right"


def diferencia_angular(a: float, b: float) -> float:
    """`a - b` en grados, teniendo en cuenta que el pan da la vuelta en 360."""
    d = (a - b + 180.0) % 360.0 - 180.0
    return d


def un_paso(camara: CamaraPTZ, codigo: str, velocidad: int, duracion: float):
    """Da un paso y devuelve `(grados_recorridos, segundos_de_motor)`.

    El tiempo se mide alrededor de las peticiones, no del `sleep`: la latencia
    HTTP forma parte de lo que el motor esta girando y hay que contarla.
    """
    antes = camara.posicion()
    if antes is None:
        raise ErrorPTZ("la camara no reporta posicion")
    t0 = time.perf_counter()
    camara.mover(codigo, velocidad)
    time.sleep(duracion)
    camara.parar(codigo)
    transcurrido = time.perf_counter() - t0
    time.sleep(0.8)                       # que el motor termine de frenar
    despues = camara.posicion()
    if despues is None:
        raise ErrorPTZ("la camara dejo de reportar posicion")
    return diferencia_angular(despues[0], antes[0]), transcurrido, despues


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--rtsp", type=resolver_rtsp, help=AYUDA_RTSP)
    p.add_argument("--host")
    p.add_argument("--user", default="admin")
    p.add_argument("--password")
    p.add_argument("--duracion", type=float, default=0.30,
                   help="Duracion de cada paso, en segundos. Por defecto: 0.30.")
    p.add_argument("--velocidades", default="1,2,3",
                   help="Velocidades a probar, separadas por comas.")
    p.add_argument("--confirmar", action="store_true",
                   help="OBLIGATORIO: confirma que se pueden mover los motores.")
    args = p.parse_args()

    if not args.confirmar:
        print("Este script MUEVE LOS MOTORES de la camara.")
        print("Invalida cualquier calibracion extrinseca previa.")
        print("Si es lo que queres, repetilo con --confirmar.")
        return 2

    if args.rtsp:
        camara = CamaraPTZ.desde_rtsp(args.rtsp)
    elif args.host:
        camara = CamaraPTZ(args.host, args.user, args.password or "")
    else:
        p.error("hace falta --rtsp o --host")

    print(f"Camara: {camara.host}")
    try:
        caps = camara.capacidades()
        print("  " + resumen_capacidades(caps))
        inicial = camara.posicion()
    except ErrorPTZ as exc:
        print(f"  no responde: {exc}")
        return 1
    if inicial is None:
        print("  la camara no reporta posicion; no se puede medir.")
        return 1

    print(f"  posicion inicial: pan {inicial[0]:.2f}  tilt {inicial[1]:.2f}")
    print(f"  pasos de {args.duracion:.2f} s\n")

    velocidades = [int(v) for v in args.velocidades.split(",") if v.strip()]
    print(f"{'vel':>4} | {'ida':>8} | {'vuelta':>8} | {'motor':>7} | "
          f"{'grados/s':>9} | {'residuo':>8}")
    print("-" * 60)

    filas = []
    try:
        for vel in velocidades:
            ida, t_ida, _ = un_paso(camara, DERECHA, vel, args.duracion)
            vuelta, t_vuelta, final = un_paso(camara, IZQUIERDA, vel, args.duracion)
            motor_s = (t_ida + t_vuelta) / 2
            grados_s = abs(ida) / t_ida if t_ida else float("nan")
            residuo = diferencia_angular(final[0], inicial[0])
            filas.append((vel, grados_s, residuo))
            print(f"{vel:>4} | {ida:>+7.2f}o | {vuelta:>+7.2f}o | {motor_s:>6.2f}s | "
                  f"{grados_s:>8.1f} | {residuo:>+7.2f}o")
            inicial = final
    except ErrorPTZ as exc:
        print(f"\nERROR: {exc}")
        return 1
    finally:
        try:
            camara.parar()
        except ErrorPTZ:
            pass

    if not filas:
        return 1

    print("\n--- Lectura ---")
    lenta = min(filas, key=lambda f: f[0])
    print(f"A velocidad {lenta[0]} la camara gira a ~{lenta[1]:.0f} grados/s.")
    if lenta[1] < 100:
        print("  Regimen ESTABLE: los ajustes por defecto del seguidor sirven.")
    elif lenta[1] < 180:
        print("  Regimen LIMITE: la confirmacion visual deberia bastar, pero")
        print("  conviene subir --zona-muerta si todavia se pasa.")
    else:
        print("  Regimen RAPIDO: un paso recorre mas que la zona muerta y")
        print("  ninguna politica basada en tiempo lo va a arreglar. Hace")
        print("  falta posicionamiento absoluto (caps.MoveAbsolutely=true).")

    peor = max(abs(f[2]) for f in filas)
    print(f"\nRepetibilidad: el residuo mayor al ir y volver es {peor:.2f} grados.")
    print("  Es cuanto se desvia el motor al repetir un movimiento; decide si")
    print("  la via de los presets serviria para recuperar una calibracion.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
