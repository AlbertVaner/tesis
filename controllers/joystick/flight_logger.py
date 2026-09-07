"""Registro CSV reproducible para las sesiones de control por marker."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from marker_mocap import Pose

SHARED_DIR = Path(__file__).resolve().parents[1] / "shared"
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))
from csv_session import RESULTS_DIR, CsvSession  # noqa: E402


CSV_COLUMNS = [
    "t_s", "tipo", "evento", "estado_marker", "marker_x_m", "marker_y_m", "marker_z_m",
    "marker_dz_m", "roll_deg", "pitch_deg", "yaw_deg", "roll_rel_deg", "pitch_rel_deg",
    "drone_x_m", "drone_y_m", "drone_z_m", "drone_dz_m", "target_z_m",
    "vx_cmd_m_s", "vy_cmd_m_s", "vz_cmd_m_s",
]


class MarkerFlightLogger(CsvSession):
    def __init__(self) -> None:
        super().__init__(CSV_COLUMNS, folder_name="marker", filename_prefix="sesion_marker")

    def event(self, name: str) -> None:
        self.write(self._base_row(tipo="evento", evento=name), flush=True)

    def sample(
        self,
        marker: Pose | None,
        drone: Pose | None,
        zero: Pose | None,
        launch: Pose | None,
        command: dict,
    ) -> None:
        if not self.active:
            return
        row = self._base_row(
            tipo="muestra",
            estado_marker=command.get("state", "SIN_DATOS"),
            marker_dz_m=command.get("marker_dz", ""),
            roll_rel_deg=command.get("roll_rel", ""),
            pitch_rel_deg=command.get("pitch_rel", ""),
            target_z_m=command.get("target_z", ""),
            vx_cmd_m_s=command.get("vx", 0.0),
            vy_cmd_m_s=command.get("vy", 0.0),
            vz_cmd_m_s=command.get("vz", 0.0),
        )
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
        self.write(row)

    def _analyze(self, path: Path) -> Path:
        analyzer = Path(__file__).resolve().parent / "analyze_marker_session.py"
        subprocess.run([sys.executable, str(analyzer), str(path)], check=True)
        return RESULTS_DIR / "graphs" / "marker" / path.parent.name / path.stem
