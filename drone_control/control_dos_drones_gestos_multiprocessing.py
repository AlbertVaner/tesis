r"""Lanzador del control gestual multiproceso para dos Crazyflies.

Prueba sin motores:
    .\.venv\Scripts\python.exe .\drone_control\control_dos_drones_gestos_multiprocessing.py --preflight-only

Control sincronizado con la mano derecha:
    .\.venv\Scripts\python.exe .\drone_control\control_dos_drones_gestos_multiprocessing.py --mode both
"""

from __future__ import annotations

import multiprocessing as mp

from dual_multiprocess.supervisor import main


if __name__ == "__main__":
    mp.freeze_support()
    main()
