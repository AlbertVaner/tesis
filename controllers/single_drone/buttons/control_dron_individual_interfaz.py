"""Panel de botones para un solo Crazyflie: la interfaz de la cruz en modo de un dron.

Usa el mismo backend high-level y las mismas protecciones que el control de
dos drones; sólo habilita el dron elegido.

    .\\.venv\\Scripts\\python.exe .\\controllers\\single_drone\\buttons\\control_dron_individual_interfaz.py --drone 1
    .\\.venv\\Scripts\\python.exe .\\controllers\\single_drone\\buttons\\control_dron_individual_interfaz.py --drone 2 --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[3]
for directory in (PROJECT_DIR / "controllers" / "two_drones", PROJECT_DIR / "controllers" / "shared"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from control_dos_drones_cruz_botones import HighLevelButtonsApp  # noqa: E402
from cruz_highlevel_backend import HardwareBackend, SimulatedBackend  # noqa: E402
from dual_cli import add_dual_drone_arguments  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Control high-level por botones para un Crazyflie")
    parser.add_argument("--drone", choices=("1", "2"), default="1", help="cuál de los dos drones de la cruz se habilita")
    add_dual_drone_arguments(parser, single=False)
    args = parser.parse_args()
    args.single = f"drone{args.drone}"
    try:
        backend = SimulatedBackend(args.single) if args.dry_run else HardwareBackend(args)
    except Exception as exc:
        print(f"No se pudo iniciar el backend: {exc}", file=sys.stderr)
        return 2
    HighLevelButtonsApp(backend, dry_run=args.dry_run).mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
