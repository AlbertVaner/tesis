"""Recepción y conversión de poses ROBOTAT publicadas por MQTT."""

from __future__ import annotations

import json
import math
import threading
import time
from dataclasses import dataclass
from typing import Callable

import paho.mqtt.client as mqtt


@dataclass(frozen=True)
class Pose:
    x: float
    y: float
    z: float
    roll_deg: float
    pitch_deg: float
    yaw_deg: float
    received_at: float

    @property
    def age_s(self) -> float:
        return time.monotonic() - self.received_at


def quaternion_to_euler_deg(qx: float, qy: float, qz: float, qw: float) -> tuple[float, float, float]:
    """Convierte el cuaternión ROS/ROBOTAT (x, y, z, w) a roll, pitch, yaw."""
    norm = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw)
    if norm < 1e-9:
        raise ValueError("cuaternión con norma cero")
    qx, qy, qz, qw = (value / norm for value in (qx, qy, qz, qw))

    sinr_cosp = 2.0 * (qw * qx + qy * qz)
    cosr_cosp = 1.0 - 2.0 * (qx * qx + qy * qy)
    roll = math.atan2(sinr_cosp, cosr_cosp)

    sinp = 2.0 * (qw * qy - qz * qx)
    pitch = math.copysign(math.pi / 2.0, sinp) if abs(sinp) >= 1.0 else math.asin(sinp)

    siny_cosp = 2.0 * (qw * qz + qx * qy)
    cosy_cosp = 1.0 - 2.0 * (qy * qy + qz * qz)
    yaw = math.atan2(siny_cosp, cosy_cosp)
    return tuple(math.degrees(angle) for angle in (roll, pitch, yaw))


def _component(data: dict, long_name: str, short_name: str) -> float:
    if long_name in data:
        return float(data[long_name])
    return float(data[short_name])


def parse_robotat_pose(message: bytes | dict) -> Pose:
    """Acepta los formatos ``mocap/all`` y ``mocap/allv2`` de ROBOTAT."""
    data = json.loads(message.decode("utf-8")) if isinstance(message, bytes) else message
    payload = data.get("payload", data.get("pld"))
    if payload is None:
        raise KeyError("El mensaje no contiene payload/pld")
    pose = payload["pose"]
    position = pose["position"]
    rotation = pose.get("rotation", pose.get("orientation"))
    if rotation is None:
        raise KeyError("El mensaje no contiene rotation/orientation")

    x, y, z = (float(position[key]) for key in ("x", "y", "z"))
    qx = _component(rotation, "qx", "x")
    qy = _component(rotation, "qy", "y")
    qz = _component(rotation, "qz", "z")
    qw = _component(rotation, "qw", "w")
    if not all(math.isfinite(value) for value in (x, y, z, qx, qy, qz, qw)):
        raise ValueError("pose no finita")
    roll, pitch, yaw = quaternion_to_euler_deg(qx, qy, qz, qw)
    return Pose(x, y, z, roll, pitch, yaw, time.monotonic())


class MocapReceiver:
    """Suscriptor MQTT seguro para una sola pose de ROBOTAT."""

    def __init__(
        self,
        topic: str,
        broker: str = "192.168.50.200",
        port: int = 1880,
        on_pose: Callable[[Pose], None] | None = None,
        required_identifier: int | None = None,
    ) -> None:
        self.topic = topic
        self.broker = broker
        self.port = port
        self.on_pose = on_pose
        self.required_identifier = required_identifier
        self._pose: Pose | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.error = ""

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    def snapshot(self) -> Pose | None:
        with self._lock:
            return self._pose

    def fresh(self, timeout_s: float) -> bool:
        pose = self.snapshot()
        return pose is not None and pose.age_s <= timeout_s

    def _on_message(self, _client, _userdata, message) -> None:
        try:
            data = json.loads(message.payload.decode("utf-8"))
            identifier = data.get("identifier", data.get("pid"))
            if self.required_identifier is not None and str(identifier) != str(self.required_identifier):
                return
            pose = parse_robotat_pose(data)
            with self._lock:
                self._pose = pose
                self.error = ""
            if self.on_pose is not None:
                self.on_pose(pose)
        except Exception as exc:
            self.error = f"Pose inválida: {exc}"

    def _run(self) -> None:
        client = mqtt.Client()
        client.on_message = self._on_message
        try:
            client.connect(self.broker, self.port, 60)
            client.subscribe(self.topic)
            print(f"MoCap conectado: {self.topic}")
            while not self._stop.is_set():
                client.loop(timeout=0.1)
        except Exception as exc:
            self.error = f"MQTT {self.topic}: {exc}"
            print(self.error)
        finally:
            try:
                client.disconnect()
            except Exception:
                pass
