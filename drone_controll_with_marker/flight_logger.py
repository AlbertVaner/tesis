"""Registro CSV reproducible para las sesiones de control por marker."""

from __future__ import annotations

import csv
import threading
import time
from datetime import datetime
from pathlib import Path

from marker_mocap import Pose


CSV_COLUMNS = [
    "t_s", "tipo", "evento", "estado_marker", "marker_x_m", "marker_y_m", "marker_z_m",
    "marker_dz_m", "roll_deg", "pitch_deg", "yaw_deg", "roll_rel_deg", "pitch_rel_deg",
    "drone_x_m", "drone_y_m", "drone_z_m", "drone_dz_m", "target_z_m",
    "vx_cmd_m_s", "vy_cmd_m_s", "vz_cmd_m_s",
]


class MarkerFlightLogger:
    def __init__(self) -> None:
        self._file = None
        self._writer = None
        self._t0 = 0.0
        self.path: Path | None = None
        self._lock = threading.RLock()

    @property
    def active(self) -> bool:
        return self._writer is not None

    def start(self) -> Path:
        with self._lock:
            self.stop()
            folder = Path(__file__).resolve().parent / "datos_marker"
            folder.mkdir(exist_ok=True)
            self.path = folder / f"sesion_marker_{datetime.now():%Y%m%d_%H%M%S}.csv"
            self._file = self.path.open("w", newline="", encoding="utf-8")
            self._writer = csv.DictWriter(self._file, fieldnames=CSV_COLUMNS)
            self._writer.writeheader()
            self._t0 = time.monotonic()
            return self.path

    def stop(self) -> Path | None:
        with self._lock:
            if self._file is not None:
                self._file.flush()
                self._file.close()
            self._file = None
            self._writer = None
            return self.path

    def _base_row(self, kind: str, event: str = "") -> dict:
        return {column: "" for column in CSV_COLUMNS} | {
            "t_s": round(time.monotonic() - self._t0, 4),
            "tipo": kind,
            "evento": event,
        }

    def event(self, name: str) -> None:
        with self._lock:
            if self._writer is None:
                return
            self._writer.writerow(self._base_row("evento", name))
            self._file.flush()

    def sample(
        self,
        marker: Pose | None,
        drone: Pose | None,
        zero: Pose | None,
        launch: Pose | None,
        command: dict,
    ) -> None:
        with self._lock:
            if self._writer is None:
                return
            row = self._base_row("muestra")
            row.update({
                "estado_marker": command.get("state", "SIN_DATOS"),
                "marker_dz_m": command.get("marker_dz", ""),
                "roll_rel_deg": command.get("roll_rel", ""),
                "pitch_rel_deg": command.get("pitch_rel", ""),
                "target_z_m": command.get("target_z", ""),
                "vx_cmd_m_s": command.get("vx", 0.0),
                "vy_cmd_m_s": command.get("vy", 0.0),
                "vz_cmd_m_s": command.get("vz", 0.0),
            })
            if marker is not None:
                row.update({
                    "marker_x_m": marker.x, "marker_y_m": marker.y, "marker_z_m": marker.z,
                    "roll_deg": marker.roll_deg, "pitch_deg": marker.pitch_deg, "yaw_deg": marker.yaw_deg,
                })
            if drone is not None:
                row.update({
                    "drone_x_m": drone.x, "drone_y_m": drone.y, "drone_z_m": drone.z,
                    "drone_dz_m": drone.z - launch.z if launch is not None else "",
                })
            self._writer.writerow(row)
