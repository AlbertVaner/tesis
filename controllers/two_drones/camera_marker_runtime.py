"""Adaptador del seguimiento de marker al backend high-level de cámara."""
from __future__ import annotations

from pathlib import Path
import sys
import threading
import time


MODULE_DIR = Path(__file__).resolve().parent
JOYSTICK_DIR = MODULE_DIR.parent / "joystick"
for directory in (MODULE_DIR, JOYSTICK_DIR):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from cruz_highlevel_protocol import Command
from marker_follow import CameraMarkerFollower, FollowUnavailable


FOLLOW_COMMAND_PERIOD_S = 0.10


def selected_keys(target: str, snapshot: dict) -> tuple[str, ...]:
    if target == "both":
        return tuple(key for key in ("drone1", "drone2") if snapshot[key].get("enabled", True))
    return (target,)


class HighlevelCameraMarkerRuntime:
    """Convierte objetivos del marker en pasos validados del backend."""

    def __init__(self, *, enabled: bool, follower=None) -> None:
        self.follower = follower if follower is not None else (CameraMarkerFollower() if enabled else None)
        self.lock = threading.Lock()
        self.last_update = 0.0

    @property
    def active_keys(self) -> tuple[str, ...]:
        return () if self.follower is None else self.follower.active_keys

    def active_for(self, target: str, snapshot: dict) -> bool:
        keys = selected_keys(target, snapshot)
        return any(key in self.active_keys for key in keys)

    def start(self) -> None:
        if self.follower is not None:
            self.follower.start()

    def stop(self) -> None:
        if self.follower is not None:
            self.follower.stop()

    def cancel(self) -> None:
        """Cancela objetivos sin esperar al cierre del receptor MQTT."""
        if self.follower is not None:
            self.follower.deactivate()

    def activate(self, target: str, snapshot: dict) -> str:
        if self.follower is None:
            raise FollowUnavailable("Seguimiento del marker 65 no disponible en simulación")
        keys = selected_keys(target, snapshot)
        if not keys or not all(snapshot[key].get("airborne") for key in keys):
            raise FollowUnavailable("Despega el dron antes de activar el seguimiento")
        pending = tuple(key for key in keys if key not in self.follower.active_keys)
        if pending:
            positions = {key: snapshot[key].get("pose") for key in pending}
            self.follower.activate(pending, positions)
        return "SEGUIR MARKER 65 · " + "+".join(keys)

    def deactivate(self, target: str, snapshot: dict) -> str:
        keys = selected_keys(target, snapshot)
        if self.follower is not None:
            self.follower.deactivate(keys)
        return "HOVER · seguimiento detenido · " + "+".join(keys)

    def update(self, backend) -> list[str]:
        if self.follower is None or not self.follower.active_keys:
            return []
        if time.monotonic() - self.last_update < FOLLOW_COMMAND_PERIOD_S:
            return []
        if not self.lock.acquire(blocking=False):
            return []
        details = []
        try:
            self.last_update = time.monotonic()
            snapshot = backend.snapshot()
            deltas = {}
            for key in tuple(self.follower.active_keys):
                unit = snapshot[key]
                if not unit.get("airborne") or unit.get("target") is None:
                    self.follower.deactivate((key,))
                    continue
                try:
                    deltas[key] = self.follower.highlevel_delta(key, unit["target"])
                except Exception:
                    self.follower.deactivate((key,))
                    raise
            if set(deltas) == {"drone1", "drone2"} and all(
                abs(a-b) <= 1e-6 for a,b in zip(deltas["drone1"],deltas["drone2"])
            ):
                dx,dy,dz=deltas["drone1"]
                if any(abs(value)>1e-3 for value in (dx,dy,dz)):
                    getattr(backend, "follow_move", backend.move)(Command("follow_move","both",dx,dy,dz))
                    details.append(f"both: marker 65 dx={dx:+.3f} dy={dy:+.3f} dz={dz:+.3f}")
                deltas.clear()
            for key,(dx,dy,dz) in deltas.items():
                if any(abs(value) > 1e-3 for value in (dx, dy, dz)):
                    getattr(backend, "follow_move", backend.move)(Command("follow_move", key, dx, dy, dz))
                    details.append(f"{key}: marker 65 dx={dx:+.3f} dy={dy:+.3f} dz={dz:+.3f}")
            return details
        finally:
            self.lock.release()
