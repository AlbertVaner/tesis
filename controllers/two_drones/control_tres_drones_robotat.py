r"""Panel de teclado para tres Crazyflies sobre el Robotat, con el controlador nuevo.

Es `control_dos_drones_robotat.py` con una tercera columna: tres instancias
independientes de `DronRobotat` (`controllers/shared`), cada una con su rigid
body y su CSV, y el mismo supervisor de separación, que con tres vigila los
tres pares y aterriza a todos si dos drones en vuelo se acercan a menos de
`SEPARACION_MIN_M`.

    .\.venv\Scripts\python.exe .\controllers\two_drones\control_tres_drones_robotat.py --dry-run
    .\.venv\Scripts\python.exe .\controllers\two_drones\control_tres_drones_robotat.py --uri3 radio://9DD2507072/90/2M/E7E7E7E7E6 --topic3 mocap/drone5 --velocidad 0.25 --radio-max 1.0

El tercer dron no tiene identidad por defecto: fuera de `--dry-run` hay que
dar `--uri3` y `--topic3` (la URI del ejemplo es sólo el formato). Con dos
Crazyradio, el Dron 3 **comparte antena** con el dron cuyo serial lleve su
URI; cflib lo admite dentro de un mismo proceso, pero los dos drones se
reparten el ancho de banda de esa radio, y si además están en canales
distintos la radio cambia de canal en cada paquete. Conviene que compartan
canal (mismo canal, distinta dirección).

Teclado: Dron 1 y Dron 2 como en el panel dual (`shared/tk_keys.py`); Dron 3
con I/J/K/L, Y sube, H baja y U/O giran. Mantener la tecla mueve; soltarla
frena. Enter despega o aterriza los tres; **R corta motores de los tres**.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import urlsplit

MODULE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = MODULE_DIR.parents[1]
SHARED_DIR = PROJECT_DIR / "controllers" / "shared"
for directory in (MODULE_DIR, SHARED_DIR):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from control_dos_drones_robotat import (  # noqa: E402
    BOTONES_DIRECCION, PanelDosRobotat, build_parser as build_parser_dual, opciones_dual,
)
from dron_robotat import DronRobotat, DronSimulado, Opciones  # noqa: E402
from tk_keys import KEY_DIRECTIONS, KEY_ROTATIONS  # noqa: E402

CLAVES = ("drone1", "drone2", "drone3")
#: URI y tópico del Dron 3 sólo para `--dry-run`; nunca llegan a una radio.
URI3_SIMULADA = "radio://sim/0/2M/DRON3"
TOPIC3_SIMULADO = "mocap/sim3"

#: Teclas del Dron 3 (ranura 2), con el mismo convenio de `tk_keys`: +1 en el
#: giro es antihorario visto desde arriba. No pisan W/A/S/D, Q/E, R ni Enter.
KEY_DIRECTIONS_3 = {
    "i": (2, 1, 0, 0), "k": (2, -1, 0, 0),
    "j": (2, 0, 1, 0), "l": (2, 0, -1, 0),
    "y": (2, 0, 0, 1), "h": (2, 0, 0, -1),
}
KEY_ROTATIONS_3 = {"u": (2, 1), "o": (2, -1)}
#: En mayúscula también: Shift (bajar el Dron 1) cambia el keysym de la letra.
KEYSYMS_3 = tuple(k for letra in "ijklyhuo" for k in (letra, letra.upper()))
BOTONES_DIRECCION_3 = (
    ("Adelante", "i"), ("Atrás", "k"), ("Izquierda", "j"), ("Derecha", "l"),
    ("Subir", "y"), ("Bajar", "h"), ("Giro izq", "u"), ("Giro der", "o"),
)
AYUDA_TECLADO_TRIPLE = (
    "D1: WASD + Espacio/Shift + Q/E giro    D2: flechas + RePág/AvPág + Inicio/Fin giro\n"
    "D3: IJKL + Y/H subir y bajar + U/O giro\n"
    "ENTER = despegar o aterrizar    R = EMERGENCIA"
)


def _enlace(uri: str) -> tuple[str, str]:
    """(antena, canal/tasa/dirección) de una URI de cflib, en mayúsculas."""
    partes = urlsplit(uri)
    return partes.netloc.upper(), partes.path.strip("/").upper()


def opciones_triple(args: argparse.Namespace, *, log=print) -> dict[str, Opciones]:
    """Una `Opciones` por dron. El Dron 3 exige `--uri3` y `--topic3` con hardware."""
    if not args.dry_run and not (args.uri3 and args.topic3):
        raise RuntimeError(
            "el Dron 3 no tiene identidad por defecto: indica --uri3 "
            "(radio://<serial o indice>/<canal>/2M/<direccion>) y --topic3 (rigid body del Robotat)"
        )
    opciones = opciones_dual(args)
    uri3 = URI3_SIMULADA if args.dry_run else args.uri3
    topic3 = args.topic3 or TOPIC3_SIMULADO
    base = opciones["drone2"]
    for clave in ("drone1", "drone2"):
        otro = opciones[clave]
        if otro.topic == topic3:
            raise RuntimeError(f"--topic3 es el mismo rigid body que {otro.nombre}: {topic3}")
        if args.dry_run:
            continue
        antena, enlace = _enlace(otro.uri)
        antena3, enlace3 = _enlace(uri3)
        if enlace == enlace3:
            raise RuntimeError(f"--uri3 apunta al mismo Crazyflie que {otro.nombre}: {enlace3}")
        if antena == antena3:
            aviso = f"Dron 3 comparte la Crazyradio {antena3} con {otro.nombre}"
            if enlace.split("/")[0] != enlace3.split("/")[0]:
                aviso += "; canales distintos: la radio cambia de canal en cada paquete"
            log(aviso)
    opciones["drone3"] = Opciones(
        uri=uri3, topic=topic3, nombre="Dron 3",
        ext_pos_std_m=base.ext_pos_std_m, parametros=dict(base.parametros), altura_m=base.altura_m,
        radio_max_m=base.radio_max_m, velocidad_mps=base.velocidad_mps,
        thrust_base_explicito=base.thrust_base_explicito, centro_geocerca=base.centro_geocerca,
    )
    return opciones


class PanelTresRobotat(PanelDosRobotat):
    """El panel dual con tres columnas y las teclas del Dron 3."""

    TITULO = "Tres Crazyflies sobre el Robotat"
    GEOMETRIA = ("1340x680", 1200, 600)
    TODOS = "todos"
    KEY_DIRECTIONS = KEY_DIRECTIONS | KEY_DIRECTIONS_3
    KEY_ROTATIONS = KEY_ROTATIONS | KEY_ROTATIONS_3
    KEYSYMS_EXTRA = KEYSYMS_3
    BOTONES = BOTONES_DIRECCION | {"drone3": BOTONES_DIRECCION_3}
    AYUDA = AYUDA_TECLADO_TRIPLE


def build_parser() -> argparse.ArgumentParser:
    parser = build_parser_dual()
    parser.description = "Tres Crazyflies sobre el Robotat con el controlador nuevo"
    parser.add_argument("--uri3", help="URI del Dron 3; obligatoria sin --dry-run. Puede llevar el serial de una "
                                       "Crazyradio que ya use otro dron (antena compartida)")
    parser.add_argument("--topic3", help="topico del Dron 3 en el Robotat; obligatorio sin --dry-run")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 0.05 <= args.velocidad <= 0.5:
        raise SystemExit("--velocidad debe estar entre 0.05 y 0.5 m/s")
    try:
        opciones = opciones_triple(args)
    except RuntimeError as exc:
        print(f"No se pudo preparar los drones: {exc}", file=sys.stderr)
        return 2
    drones = {
        c: (DronSimulado(o) if args.dry_run else DronRobotat(o)) for c, o in opciones.items()
    }
    for o in opciones.values():
        print(f"{o.nombre}: uri={o.uri} topic={o.topic}")
    PanelTresRobotat(drones, dry_run=args.dry_run).mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
