"""Argumentos de línea de comandos comunes a los lanzadores de dos drones."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SHARED_DIR = Path(__file__).resolve().parents[1] / "shared"
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))
from radios import DRONE_1_URI, DRONE_2_URI  # noqa: E402
from robotat import DRONE_1_TOPIC, DRONE_2_TOPIC  # noqa: E402

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8766


def add_dual_drone_arguments(
    parser: argparse.ArgumentParser,
    *,
    single: bool = True,
    dry_run: str | None = "simula Robotat y radios; nunca activa motores",
    server: bool = False,
) -> argparse.ArgumentParser:
    """Añade `--uri1/--uri2/--topic1/--topic2` y, opcionalmente, `--single`,
    `--dry-run` (con la ayuda dada) y `--host/--port` del backend."""
    if server:
        parser.add_argument("--host", default=DEFAULT_HOST)
        parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--uri1", default=DRONE_1_URI)
    parser.add_argument("--uri2", default=DRONE_2_URI)
    parser.add_argument("--topic1", default=DRONE_1_TOPIC)
    parser.add_argument("--topic2", default=DRONE_2_TOPIC)
    if single:
        parser.add_argument("--single", choices=("drone1", "drone2"), help="habilita solamente un dron")
    if dry_run is not None:
        parser.add_argument("--dry-run", action="store_true", help=dry_run)
    return parser
