"""Registro MoCap/EKF compartido por el control con cámara y la app web."""

from __future__ import annotations

import csv
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from cflib.crazyflie.log import LogConfig

import control as dc


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DIAGNOSTIC_FOLDER = PROJECT_ROOT / "datos_vuelo_crazyflie"
GRAPH_ANALYZER = PROJECT_ROOT / "drone_control" / "analizar_sesion_dos_drones.py"


class DiagnosticCsvLogger:
    """Guarda MoCap, EKF, objetivo y genera figuras PDF al finalizar."""

    FIELDNAMES = [
        "fecha_hora", "tiempo_s", "estado_vuelo", "mocap_edad_s",
        "mocap_x_m", "mocap_y_m", "mocap_z_m",
        "kalman_x_m", "kalman_y_m", "kalman_z_m",
        "error_kalman_mocap_x_m", "error_kalman_mocap_y_m", "error_kalman_mocap_z_m",
        "target_x_m", "target_y_m", "target_z_m",
    ]

    def __init__(self, cf) -> None:
        DIAGNOSTIC_FOLDER.mkdir(parents=True, exist_ok=True)
        self.path = DIAGNOSTIC_FOLDER / f"ekf_mocap_{datetime.now():%Y%m%d_%H%M%S}.csv"
        self.file = self.path.open("w", newline="", encoding="utf-8")
        self.writer = csv.DictWriter(self.file, fieldnames=self.FIELDNAMES)
        self.writer.writeheader()
        self.file.flush()
        self.start_monotonic = time.monotonic()
        self.panel = None
        self.closed = False
        self.lock = threading.Lock()
        self.config = LogConfig(name="DiagnosticEKFMocap", period_in_ms=50)
        for axis in ("x", "y", "z"):
            self.config.add_variable(f"stateEstimate.{axis}", "float")
        cf.log.add_config(self.config)
        self.config.data_received_cb.add_callback(self._callback)
        self.config.error_cb.add_callback(self._error_callback)

    def _callback(self, _timestamp, data, _config) -> None:
        mocap = tuple(dc.mocap_pose[axis] for axis in ("x", "y", "z"))
        kalman = tuple(float(data[f"stateEstimate.{axis}"]) for axis in ("x", "y", "z"))
        target = (
            getattr(self.panel, "target_x", None),
            getattr(self.panel, "target_y", None),
            getattr(self.panel, "target_z", None),
        )
        state = "conectado"
        if self.panel is not None:
            state = "aterrizando" if self.panel.is_landing else "volando" if self.panel.has_taken_off else "esperando"
        row = {
            "fecha_hora": datetime.now().isoformat(timespec="milliseconds"),
            "tiempo_s": time.monotonic() - self.start_monotonic,
            "estado_vuelo": state,
            "mocap_edad_s": None if dc.last_mocap_update <= 0 else time.monotonic() - dc.last_mocap_update,
        }
        for index, axis in enumerate(("x", "y", "z")):
            row[f"mocap_{axis}_m"] = mocap[index]
            row[f"kalman_{axis}_m"] = kalman[index]
            row[f"error_kalman_mocap_{axis}_m"] = None if mocap[index] is None else kalman[index] - mocap[index]
            row[f"target_{axis}_m"] = target[index]
        with self.lock:
            if not self.closed:
                self.writer.writerow(row)
                self.file.flush()

    @staticmethod
    def _error_callback(_config, message) -> None:
        print(f"Error en registro diagnostico: {message}")

    def start(self) -> None:
        self.config.start()
        print(f"Registro EKF/MoCap activo: {self.path}")

    def stop(self) -> None:
        with self.lock:
            if self.closed:
                return
            self.closed = True
        try:
            self.config.stop()
        except Exception:
            pass
        with self.lock:
            self.file.flush()
            self.file.close()
        print(f"Registro EKF/MoCap guardado: {self.path}")
        try:
            subprocess.run([sys.executable, str(GRAPH_ANALYZER), str(self.path)], check=True)
        except Exception as exc:
            print(f"No se pudieron crear las graficas PDF: {exc}")
