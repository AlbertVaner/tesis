"""Argumentos de línea de comandos comunes a los lanzadores de dos drones."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SHARED_DIR = Path(__file__).resolve().parents[1] / "shared"
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))
from radios import DRONE_1_URI, DRONE_2_URI  # noqa: E402
from drone_unit import EXTPOS_RATE_HZ  # noqa: E402
from robotat import DRONE_1_TOPIC, DRONE_2_TOPIC  # noqa: E402

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8766


def add_dual_drone_arguments(
    parser: argparse.ArgumentParser,
    *,
    single: bool = True,
    dry_run: str | None = "simula Robotat y radios; nunca activa motores",
    server: bool = False,
    backend: bool = False,
) -> argparse.ArgumentParser:
    """Añade `--uri1/--uri2/--topic1/--topic2` y, opcionalmente, `--single`,
    `--dry-run` (con la ayuda dada), `--host/--port` y `--backend`."""
    if backend:
        parser.add_argument(
            "--backend",
            choices=("mocap", "flowdeck", "robotat"),
            default="mocap",
            help="mocap: high-level de la cruz sobre el Robotat, con geocerca y "
                 "separacion minima. flowdeck: sin posicion absoluta ni "
                 "geocerca, y sin --dry-run. robotat: controlador nuevo de "
                 "controllers/shared/dron_robotat.py (mando fluido por velocidad, ganancias "
                 "validadas, CSV y graficas PDF por dron)",
        )
        parser.add_argument("--ganancias", default="robotat",
                            help="con --backend robotat: juego de ganancias del firmware "
                                 "(robotat, mitad, mitad-xy, fabrica)")
        parser.add_argument("--velocidad", type=float, default=0.25,
                            help="con --backend robotat: velocidad del mando fluido, m/s")
        parser.add_argument("--radio-max", type=float, default=None,
                            help="con --backend robotat: geocerca horizontal, m (defecto 0.5)")
        parser.add_argument("--centro-geocerca", type=float, nargs=2, metavar=("X", "Y"), default=None,
                            help="con --backend robotat: centro de la geocerca en el marco del Robotat")
        if "--param" not in parser._option_string_actions:
            parser.add_argument("--param", action="append", metavar="GRUPO.NOMBRE=VALOR",
                                help="con --backend robotat: parametro del firmware; repetible")
    if server:
        parser.add_argument("--host", default=DEFAULT_HOST)
        parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--uri1", default=DRONE_1_URI)
    parser.add_argument("--uri2", default=DRONE_2_URI)
    parser.add_argument("--topic1", default=DRONE_1_TOPIC)
    parser.add_argument("--topic2", default=DRONE_2_TOPIC)
    parser.add_argument(
        "--extpos-hz", type=float, default=EXTPOS_RATE_HZ,
        help="Ritmo de envio de posicion externa al EKF, en Hz. El MoCap "
             f"publica a ~60. Por defecto: {EXTPOS_RATE_HZ:.0f}.")
    if single:
        parser.add_argument("--single", choices=("drone1", "drone2"), help="habilita solamente un dron")
    if dry_run is not None:
        parser.add_argument("--dry-run", action="store_true", help=dry_run)
    return parser
