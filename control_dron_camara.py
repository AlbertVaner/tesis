"""Lanzador del control de un Crazyflie por cámara y gestos."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
INTEGRATION_DIR = ROOT / "archive" / "legacy" / "Integration"
if str(INTEGRATION_DIR) not in sys.path:
    sys.path.insert(0, str(INTEGRATION_DIR))

from control_gestos_lowlevel_companero import main


if __name__ == "__main__":
    main()
