"""Lanzador del control Cruz multiproceso de dos drones por cámara."""

from __future__ import annotations

import sys
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parent / "controllers" / "two_drones"
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from control_dos_drones_cruz_camara_multiprocessing import main


if __name__ == "__main__":
    raise SystemExit(main())
