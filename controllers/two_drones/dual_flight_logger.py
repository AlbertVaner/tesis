"""CSV de telemetría para las sesiones de dos Crazyflies."""

from __future__ import annotations

import csv
import threading
import time
from datetime import datetime
from pathlib import Path


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


class DualFlightLogger:
    def __init__(
        self,
        *,
        folder_name: str = "dos_drones",
        filename_prefix: str = "sesion_dos_drones",
    ) -> None:
        self._lock = threading.RLock()
        self._file = None
        self._writer = None
        self._start = 0.0
        self.path: Path | None = None
        self.folder_name = folder_name
        self.filename_prefix = filename_prefix
        self.analysis_path: Path | None = None

    @property
    def active(self) -> bool:
        return self._writer is not None

    def start(self) -> Path:
        with self._lock:
            self.stop(generate_graphs=False)
            day = datetime.now().strftime("%Y-%m-%d")
            folder = Path(__file__).resolve().parents[2] / "results" / "data" / self.folder_name / day
            folder.mkdir(parents=True, exist_ok=True)
            self.path = folder / f"{self.filename_prefix}_{datetime.now():%Y%m%d_%H%M%S}.csv"
            self._file = self.path.open("w", newline="", encoding="utf-8")
            self._writer = csv.DictWriter(self._file, fieldnames=COLUMNS)
            self._writer.writeheader()
            self._start = time.monotonic()
            return self.path

    def _row(self, kind: str, **values) -> dict:
        return {key: "" for key in COLUMNS} | {"t_s": round(time.monotonic() - self._start, 4), "kind": kind} | values

    def event(self, drone: str, name: str, status: str = "") -> None:
        with self._lock:
            if self._writer is None:
                return
            self._writer.writerow(self._row("event", drone=drone, event=name, status=status))
            self._file.flush()

    def sample(self, unit) -> None:
        with self._lock:
            if self._writer is None:
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
                origin = getattr(unit, "origin", None)
                if origin is not None:
                    values |= {
                        "origin_x_m": origin[0], "origin_y_m": origin[1], "origin_z_m": origin[2],
                    }
                error = getattr(unit, "error", None)
                if error is not None:
                    values |= {
                        "error_x_m": error[0], "error_y_m": error[1], "error_z_m": error[2],
                    }
                command = getattr(unit, "command", None)
                if command is not None:
                    values |= {
                        "cmd_vx_m_s": command[0], "cmd_vy_m_s": command[1], "cmd_vz_m_s": command[2],
                    }
                ekf_mocap_error = getattr(unit, "ekf_mocap_error", None)
                if ekf_mocap_error is not None:
                    values["ekf_mocap_error_m"] = ekf_mocap_error
                separation = getattr(unit, "separation", None)
                if separation is not None:
                    values["separation_m"] = separation
                values |= {
                    "roll_deg": getattr(unit, "roll_deg", None),
                    "pitch_deg": getattr(unit, "pitch_deg", None),
                    "battery_v": getattr(unit, "battery_v", None),
                    "battery_level_pct": getattr(unit, "battery_level_pct", None),
                }
            self._writer.writerow(self._row("sample", **values))

    def stop(self, *, generate_graphs: bool = True) -> Path | None:
        with self._lock:
            was_active = self._file is not None
            if self._file is not None:
                self._file.flush()
                self._file.close()
            self._file = self._writer = None
            path = self.path
        if generate_graphs and was_active and path is not None and path.exists():
            try:
                from analizar_sesion_dos_drones import analyze_session

                self.analysis_path = analyze_session(path)
                print(f"Graficas PDF guardadas en: {self.analysis_path}")
            except Exception as exc:
                print(f"ADVERTENCIA: no se pudieron generar las graficas PDF: {exc}")
        return path
