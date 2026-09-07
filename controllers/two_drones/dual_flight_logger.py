"""CSV de telemetría para las sesiones de dos Crazyflies."""

from __future__ import annotations

import sys
import time
from pathlib import Path

SHARED_DIR = Path(__file__).resolve().parents[1] / "shared"
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))
from csv_session import CsvSession  # noqa: E402


COLUMNS = [
    "t_s", "kind", "event", "drone", "status", "uri", "topic", "airborne",
    "mocap_x_m", "mocap_y_m", "mocap_z_m", "mocap_age_s", "mocap_hz", "mocap_interval_s",
    "mocap_vx_m_s", "mocap_vy_m_s", "mocap_vz_m_s",
    "ekf_x_m", "ekf_y_m", "ekf_z_m", "ekf_age_s",
    "target_x_m", "target_y_m", "target_z_m",
    "mode", "origin_x_m", "origin_y_m", "origin_z_m",
    "error_x_m", "error_y_m", "error_z_m",
    "cmd_vx_m_s", "cmd_vy_m_s", "cmd_vz_m_s",
    "ekf_mocap_error_m", "separation_m",
    "roll_deg", "pitch_deg", "battery_v", "battery_level_pct",
]


class DualFlightLogger(CsvSession):
    def __init__(
        self,
        *,
        folder_name: str = "dos_drones",
        filename_prefix: str = "sesion_dos_drones",
    ) -> None:
        super().__init__(COLUMNS, folder_name=folder_name, filename_prefix=filename_prefix)

    def _row(self, kind: str, **values) -> dict:
        return self._base_row(kind=kind, **values)

    def event(self, drone: str, name: str, status: str = "") -> None:
        self.write(self._row("event", drone=drone, event=name, status=status), flush=True)

    def sample(self, unit) -> None:
        if not self.active:
            return
        with unit.lock:
            pose, estimate = unit.pose, unit.estimate
            target = None if unit.target is None else list(unit.target)
            now = time.monotonic()
            values = {
                "drone": unit.name, "status": unit.status, "uri": unit.uri, "topic": unit.topic,
                "airborne": unit.airborne,
                "mode": getattr(unit, "mode", ""),
            }
            if pose is not None:
                values |= {
                    "mocap_x_m": pose.x, "mocap_y_m": pose.y, "mocap_z_m": pose.z,
                    "mocap_age_s": round(now - pose.received_at, 4),
                    "mocap_hz": round(unit.mocap_hz, 2), "mocap_interval_s": round(unit.mocap_interval_s, 4),
                }
            mocap_velocity = getattr(unit, "mocap_velocity", None)
            if mocap_velocity is not None:
                values |= {
                    "mocap_vx_m_s": mocap_velocity[0],
                    "mocap_vy_m_s": mocap_velocity[1],
                    "mocap_vz_m_s": mocap_velocity[2],
                }
            if estimate is not None:
                values |= {"ekf_x_m": estimate.x, "ekf_y_m": estimate.y, "ekf_z_m": estimate.z, "ekf_age_s": round(now - estimate.received_at, 4)}
            if target is not None:
                values |= {"target_x_m": target[0], "target_y_m": target[1], "target_z_m": target[2]}
            for name, keys in (
                ("origin", ("origin_x_m", "origin_y_m", "origin_z_m")),
                ("error", ("error_x_m", "error_y_m", "error_z_m")),
                ("command", ("cmd_vx_m_s", "cmd_vy_m_s", "cmd_vz_m_s")),
            ):
                vector = getattr(unit, name, None)
                if vector is not None:
                    values |= dict(zip(keys, vector))
            for name in ("ekf_mocap_error", "separation"):
                scalar = getattr(unit, name, None)
                if scalar is not None:
                    values[f"{name}_m"] = scalar
            values |= {
                "roll_deg": getattr(unit, "roll_deg", None),
                "pitch_deg": getattr(unit, "pitch_deg", None),
                "battery_v": getattr(unit, "battery_v", None),
                "battery_level_pct": getattr(unit, "battery_level_pct", None),
            }
        self.write(self._row("sample", **values))

    def _analyze(self, path: Path) -> Path:
        from analizar_sesion_dos_drones import analyze_session

        return analyze_session(path)
