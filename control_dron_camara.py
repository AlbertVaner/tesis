"""Lanzador canónico del control de un Crazyflie por cámara y gestos."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CAMERA_DIR = ROOT / "controllers" / "single_drone" / "camera"
if str(CAMERA_DIR) not in sys.path:
    sys.path.insert(0, str(CAMERA_DIR))

from control_camara_dron1 import main


if __name__ == "__main__":
    raise SystemExit(main())
