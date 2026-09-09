"""Configuración raíz de pytest: rutas de import comunes a todos los tests.

Los scripts del repositorio se ejecutan directamente y resuelven sus imports
por `sys.path` (ver AGENTS.md, "Reglas de dependencias"). Este archivo pone
esas carpetas en el `sys.path` una sola vez para que ningún test tenga que
repetir el bloque `sys.path.insert`. Los tests de `external/mapeo3d/` añaden
su propio `src/`.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

RUTAS = (
    "controllers/shared",
    "controllers/two_drones",
    "controllers/joystick",
    "controllers/single_drone/camera",
    "controllers/single_drone/buttons",
    "external/gesture_detection",
    "web",
)

for rel in RUTAS:
    ruta = str(ROOT / rel)
    if ruta not in sys.path:
        sys.path.insert(0, ruta)
