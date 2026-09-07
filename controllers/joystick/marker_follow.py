"""Seguimiento relativo de un marker Robotat para controladores de cámara.

Este módulo sólo interpreta poses. No abre radios ni envía órdenes de vuelo.
El seguimiento conserva una separación tridimensional fija respecto al marker.
"""
from __future__ import annotations

import math
from pathlib import Path
import sys


MODULE_DIR = Path(__file__).resolve().parent
SHARED_DIR = MODULE_DIR.parent / "shared"
for directory in (MODULE_DIR, SHARED_DIR):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from marker_mocap import MocapReceiver  # noqa: E402
from robotat import ALL_MARKERS_TOPIC, MOCAP_TIMEOUT_S, MQTT_BROKER, MQTT_PORT  # noqa: E402


FOLLOW_MARKER_ID = 65
FOLLOW_MARKER_TOPIC = ALL_MARKERS_TOPIC
FOLLOW_TIMEOUT_S = MOCAP_TIMEOUT_S
FOLLOW_RADIUS_M = 0.45
FOLLOW_DEADZONE_M = 0.02
FOLLOW_KP = 1.50
FOLLOW_MAX_SPEED_M_S = 0.10
FOLLOW_MAX_STEP_M = 0.025


class FollowUnavailable(RuntimeError):
    """No se puede iniciar o conservar un seguimiento seguro."""


def _fresh(pose) -> bool:
    return pose is not None and pose.age_s <= FOLLOW_TIMEOUT_S


def _xyz(value) -> tuple[float, float, float]:
    if hasattr(value, "x"):
        result = (float(value.x), float(value.y), float(value.z))
    else:
        result = tuple(float(component) for component in value)
    if len(result) != 3 or not all(math.isfinite(component) for component in result):
        raise FollowUnavailable("Pose no válida para seguimiento")
    return result


def world_to_body(vx: float, vy: float, yaw_deg: float) -> tuple[float, float]:
    """Convierte una velocidad del marco Robotat al marco del Crazyflie."""
    yaw = math.radians(yaw_deg)
    return (
        math.cos(yaw) * vx + math.sin(yaw) * vy,
        -math.sin(yaw) * vx + math.cos(yaw) * vy,
    )


class CameraMarkerFollower:
    """Mantiene anclas independientes para uno o dos drones."""

    def __init__(
        self,
        *,
        marker_id: int = FOLLOW_MARKER_ID,
        marker_topic: str = FOLLOW_MARKER_TOPIC,
        drone_topics: dict[str, str] | None = None,
        drone_identifiers: dict[str, int | None] | None = None,
        broker: str = MQTT_BROKER,
        port: int = MQTT_PORT,
        receiver_factory=MocapReceiver,
    ) -> None:
        self.marker = receiver_factory(marker_topic, broker=broker, port=port, required_identifier=marker_id)
        self.drones = {
            key: receiver_factory(
                topic,
                broker=broker,
                port=port,
                required_identifier=(drone_identifiers or {}).get(key),
            )
            for key, topic in (drone_topics or {}).items()
        }
        self.offsets: dict[str, tuple[float, float, float]] = {}
        self.marker_origins: dict[str, tuple[float, float, float]] = {}

    @property
    def active_keys(self) -> tuple[str, ...]:
        return tuple(self.offsets)

    def active(self, key: str) -> bool:
        return key in self.offsets

    def start(self) -> None:
        self.marker.start()
        for receiver in self.drones.values():
            receiver.start()

    def stop(self) -> None:
        self.offsets.clear()
        self.marker_origins.clear()
        self.marker.stop()
        for receiver in self.drones.values():
            receiver.stop()

    def activate(self, keys, positions: dict[str, object] | None = None) -> None:
        marker = self.marker.snapshot()
        if not _fresh(marker):
            detail = self.marker.error or "marker sin pose reciente"
            raise FollowUnavailable(f"No se puede seguir el marker 65: {detail}")
        marker_xyz = _xyz(marker)
        resolved: dict[str, tuple[float, float, float]] = {}
        for key in keys:
            pose = (positions or {}).get(key)
            if pose is None and key in self.drones:
                pose = self.drones[key].snapshot()
                if not _fresh(pose):
                    detail = self.drones[key].error or "pose del dron no reciente"
                    raise FollowUnavailable(f"{key}: {detail}")
            if pose is None:
                raise FollowUnavailable(f"{key}: falta pose para iniciar seguimiento")
            drone_xyz = _xyz(pose)
            initial_offset = tuple(drone_xyz[i] - marker_xyz[i] for i in range(3))
            distance = math.dist(drone_xyz, marker_xyz)
            if distance <= 1e-6:
                resolved[key] = (0.0, 0.0, FOLLOW_RADIUS_M)
            else:
                resolved[key] = tuple(
                    component * FOLLOW_RADIUS_M / distance for component in initial_offset
                )
        self.offsets.update(resolved)
        self.marker_origins.update({key: marker_xyz for key in resolved})

    def deactivate(self, keys=None) -> None:
        if keys is None:
            self.offsets.clear()
        else:
            for key in keys:
                self.offsets.pop(key, None)
                self.marker_origins.pop(key, None)
        if keys is None:
            self.marker_origins.clear()

    def desired(self, key: str) -> tuple[float, float, float]:
        if key not in self.offsets:
            raise FollowUnavailable(f"{key}: seguimiento inactivo")
        marker = self.marker.snapshot()
        if not _fresh(marker):
            self.deactivate()
            raise FollowUnavailable("Se perdió el marker 65; seguimiento detenido")
        marker_xyz = _xyz(marker)
        offset = self.offsets[key]
        return tuple(marker_xyz[i] + offset[i] for i in range(3))

    def highlevel_delta(self, key: str, current_target) -> tuple[float, float, float]:
        desired = self.desired(key)
        current = _xyz(current_target)
        return (
            max(-FOLLOW_MAX_STEP_M, min(FOLLOW_MAX_STEP_M, desired[0] - current[0])),
            max(-FOLLOW_MAX_STEP_M, min(FOLLOW_MAX_STEP_M, desired[1] - current[1])),
            max(-FOLLOW_MAX_STEP_M, min(FOLLOW_MAX_STEP_M, desired[2] - current[2])),
        )

    def _world_velocity_and_pose(self, key: str):
        receiver = self.drones.get(key)
        pose = None if receiver is None else receiver.snapshot()
        if not _fresh(pose):
            self.deactivate((key,))
            detail = "pose del dron no reciente" if receiver is None else (receiver.error or "pose del dron no reciente")
            raise FollowUnavailable(f"{key}: {detail}; seguimiento detenido")
        desired = self.desired(key)
        current = _xyz(pose)
        errors = [desired[i] - current[i] for i in range(3)]
        world = []
        for error in errors:
            speed = 0.0 if abs(error) <= FOLLOW_DEADZONE_M else FOLLOW_KP * error
            world.append(max(-FOLLOW_MAX_SPEED_M_S, min(FOLLOW_MAX_SPEED_M_S, speed)))
        return (world[0], world[1], world[2]), pose

    def world_velocity(self, key: str) -> tuple[float, float, float]:
        """Velocidad para un backend `send_velocity_world_setpoint`."""
        velocity, _pose = self._world_velocity_and_pose(key)
        return velocity

    def body_velocity(self, key: str) -> tuple[float, float, float]:
        """Velocidad para MotionCommander, expresada en el marco del dron."""
        (world_x, world_y, world_z), pose = self._world_velocity_and_pose(key)
        vx, vy = world_to_body(world_x, world_y, float(pose.yaw_deg))
        return vx, vy, world_z
