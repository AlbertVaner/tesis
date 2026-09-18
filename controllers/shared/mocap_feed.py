"""Alimentación del Robotat a un Crazyflie: MQTT → frames distintos → extpos.

Recibe la pose de un rigid body por MQTT, descarta los duplicados que publica
el puente Node-RED (cada frame llega 3 a 5 veces) y entrega **cada frame
distinto una sola vez**, sin límite de tasa. Mide lo que hace falta para saber
si el flujo sirve para volar: frames distintos por segundo, hueco máximo,
latencia de origen y velocidad del marker.

No importa cflib. Quien vuela le pasa un `on_frame(frame)` que reenvía la
posición al EKF; así se prueba sin radios ni broker.

Por qué existe (ver `Tesis/60-Analisis/2026-09-12 Auditoría del controlador de
dos drones.md`): el `DroneUnit` anterior limitaba el extpos a 20 Hz y con las
ráfagas del puente dejaba pasar 7 a 13 Hz irregulares; además nunca midió el
hueco máximo ni la latencia. Aquí eso se mide y se registra siempre.
"""

from __future__ import annotations

import json
import math
import sys
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

SHARED_DIR = Path(__file__).resolve().parent
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))
from reloj import ahora  # noqa: E402
from robotat import MOCAP_TIMEOUT_S, MQTT_BROKER, MQTT_PORT  # noqa: E402

#: Los duplicados del puente llegan en ráfaga, con 1 a 2 ms entre copias; los
#: frames reales del Robotat vienen separados al menos ~16 ms (60 Hz). Un
#: mensaje que llega antes de este intervalo es una copia del anterior.
#: No se usa la posición para distinguirlos: con el dron quieto el ruido del
#: mocap es de décimas de milímetro, igual que la diferencia entre copias, y
#: un umbral de distancia tiraba frames buenos (medido el 2026-09-16: 7.9
#: frames/s con huecos de 150 ms cuando el puente publicaba a 20 Hz).
FRAME_MIN_INTERVAL_S = 0.008
#: Salvo que el marker se haya movido claramente: entonces es un frame nuevo
#: aunque llegue pegado al anterior.
FRAME_MIN_DELTA_M = 0.002
#: Ventana sobre la que se calculan la tasa de frames y el hueco máximo.
STATS_WINDOW_S = 3.0
#: Pose **congelada**: el puente sigue publicando a su ritmo pero con la misma
#: posición exacta. Un marker rastreado nunca repite el mismo valor durante
#: tanto tiempo (el ruido del mocap es de décimas de milímetro); cuando Motive
#: pierde el rigid body, el puente repite la última pose. Medido el
#: 2026-09-16 con los dos drones en el volumen: `mocap/drone4` quedó 2.7 s
#: idéntico mientras el Dron 2 despegaba, y al recuperar el rastreo la pose
#: saltó 0.9 m y el EKF quedó lejos del mocap. Una pose congelada cuenta como
#: sin mocap: no se despega y en vuelo se aterriza.
FROZEN_AFTER_S = 0.50
FROZEN_DELTA_M = 1e-6
#: Filtro de la velocidad derivada del mocap (0 = sin filtrar).
VELOCITY_ALPHA = 0.35
#: Intervalos fuera de este rango no sirven para derivar velocidad.
VELOCITY_MIN_DT_S = 0.010
VELOCITY_MAX_DT_S = 0.250
VELOCITY_MAX_MPS = 5.0


@dataclass(frozen=True)
class Frame:
    """Un frame distinto del Robotat, en metros del marco global."""

    x: float
    y: float
    z: float
    #: Cuaternión (x, y, z, w) del rigid body, si el mensaje lo trae.
    quat: tuple[float, float, float, float] | None
    #: Rumbo del rigid body en grados, derivado del cuaternión; None sin rotación.
    yaw_deg: float | None
    #: Marca del reloj local (`reloj.ahora`) al recibirlo.
    received_at: float
    #: Latencia entre la marca de tiempo del Robotat y la recepción, si viene.
    source_latency_s: float | None
    #: Roll y pitch del rigid body en grados; None sin rotación. Sirven para
    #: saber si el cuerpo está definido nivelado antes de mandarlo al EKF.
    roll_deg: float | None = None
    pitch_deg: float | None = None
    #: `identifier` (o `pid`) del mensaje: el id de streaming del rigid body
    #: en Motive. El puente publica el id 8N en `mocap/droneN` (83 -> drone3).
    identifier: str | None = None

    def xyz(self) -> tuple[float, float, float]:
        return self.x, self.y, self.z


def quaternion_euler_deg(qx: float, qy: float, qz: float, qw: float) -> tuple[float, float, float]:
    """Roll, pitch y yaw en grados de un cuaternión (x, y, z, w)."""
    norm = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw)
    if norm < 1e-9:
        raise ValueError("cuaternion con norma cero")
    qx, qy, qz, qw = (value / norm for value in (qx, qy, qz, qw))
    roll = math.atan2(2.0 * (qw * qx + qy * qz), 1.0 - 2.0 * (qx * qx + qy * qy))
    sinp = 2.0 * (qw * qy - qz * qx)
    pitch = math.copysign(math.pi / 2.0, sinp) if abs(sinp) >= 1.0 else math.asin(sinp)
    yaw = math.atan2(2.0 * (qw * qz + qx * qy), 1.0 - 2.0 * (qy * qy + qz * qz))
    return math.degrees(roll), math.degrees(pitch), math.degrees(yaw)


def quaternion_yaw_deg(qx: float, qy: float, qz: float, qw: float) -> float:
    """Rumbo (giro sobre Z) de un cuaternión (x, y, z, w) en grados."""
    return quaternion_euler_deg(qx, qy, qz, qw)[2]


def parse_timestamp(value) -> datetime | None:
    """Marca de tiempo del Robotat (ISO-8601 o Unix, s o ms) en UTC."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        seconds = float(value)
        if not math.isfinite(seconds):
            return None
        if abs(seconds) >= 1e12:
            seconds /= 1000.0
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return parse_timestamp(float(text))
        except ValueError:
            pass
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def _component(data: dict, *names: str) -> float:
    for name in names:
        if name in data:
            return float(data[name])
    raise KeyError(names[0])


def parse_message(payload: bytes | str | dict, received_at: float) -> Frame:
    """Convierte un mensaje `mocap/droneN` del Robotat en `Frame`.

    Acepta `payload` o `pld`, y la rotación como `rotation` u `orientation`
    con claves `x/y/z/w` o `qx/qy/qz/qw`. Lanza `ValueError` o `KeyError` si
    el mensaje no trae una posición finita.
    """
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8")
    data = json.loads(payload) if isinstance(payload, str) else payload
    if not isinstance(data, dict):
        raise ValueError("el mensaje no es un objeto JSON")
    body = data.get("payload", data.get("pld"))
    if not isinstance(body, dict):
        raise KeyError("payload")
    pose = body["pose"]
    position = pose["position"]
    xyz = tuple(float(position[axis]) for axis in ("x", "y", "z"))
    if not all(math.isfinite(value) for value in xyz):
        raise ValueError("posicion no finita")

    quat: tuple[float, float, float, float] | None = None
    yaw_deg: float | None = None
    roll_deg: float | None = None
    pitch_deg: float | None = None
    rotation = pose.get("rotation", pose.get("orientation"))
    if isinstance(rotation, dict):
        try:
            quat = (
                _component(rotation, "qx", "x"),
                _component(rotation, "qy", "y"),
                _component(rotation, "qz", "z"),
                _component(rotation, "qw", "w"),
            )
            if all(math.isfinite(value) for value in quat):
                roll_deg, pitch_deg, yaw_deg = quaternion_euler_deg(*quat)
            else:
                quat = None
        except (KeyError, TypeError, ValueError):
            quat = None

    latency: float | None = None
    source_ts = parse_timestamp(data.get("ts"))
    if source_ts is not None:
        latency = (datetime.now(timezone.utc) - source_ts).total_seconds()
    identifier = data.get("identifier", data.get("pid"))
    identifier = None if identifier is None else str(identifier)
    return Frame(*xyz, quat, yaw_deg, received_at, latency, roll_deg, pitch_deg, identifier)


class MocapFeed:
    """Suscriptor MQTT de un rigid body que entrega frames distintos.

    `on_frame` se llama en el hilo de MQTT con cada frame nuevo; debe ser
    rápido (enviar por radio y volver). `push(frame)` permite inyectar frames
    sin broker, para pruebas y simulación.
    """

    def __init__(
        self,
        topic: str,
        on_frame: Callable[[Frame], None] | None = None,
        *,
        broker: str = MQTT_BROKER,
        port: int = MQTT_PORT,
    ) -> None:
        self.topic = topic
        self.broker = broker
        self.port = port
        self.on_frame = on_frame
        self.lock = threading.RLock()
        self.frame: Frame | None = None
        self.velocity: tuple[float, float, float] | None = None
        self.history: deque[Frame] = deque(maxlen=400)
        self.messages = 0
        self.duplicates = 0
        self.invalid = 0
        self.frames = 0
        #: Último instante en que la posición cambió de verdad.
        self.last_change_at: float | None = None
        self.latency_s: float | None = None
        self.latency_max_s: float | None = None
        self._client = None

    # -- Conexión -------------------------------------------------------------

    def start(self) -> None:
        if self._client is not None:
            return
        import paho.mqtt.client as mqtt

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.on_message = self._on_message
        client.connect(self.broker, self.port, 60)
        client.subscribe(self.topic)
        client.loop_start()
        self._client = client

    def stop(self) -> None:
        client, self._client = self._client, None
        if client is None:
            return
        try:
            client.loop_stop()
            client.disconnect()
        except Exception:
            pass

    def _on_message(self, _client, _userdata, message) -> None:
        now = ahora()
        with self.lock:
            self.messages += 1
        try:
            frame = parse_message(message.payload, now)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            with self.lock:
                self.invalid += 1
            return
        self.push(frame)

    # -- Frames ---------------------------------------------------------------

    def push(self, frame: Frame) -> bool:
        """Acepta un frame; devuelve False si era un duplicado del anterior."""
        with self.lock:
            previous = self.frame
            if previous is not None and not self._is_new(previous, frame):
                self.duplicates += 1
                return False
            self.frames += 1
            if previous is None or any(
                abs(c - p) > FROZEN_DELTA_M for c, p in zip(frame.xyz(), previous.xyz())
            ):
                self.last_change_at = frame.received_at
            self.frame = frame
            self.history.append(frame)
            self._update_velocity(previous, frame)
            if frame.source_latency_s is not None:
                self.latency_s = frame.source_latency_s
                if self.latency_max_s is None or frame.source_latency_s > self.latency_max_s:
                    self.latency_max_s = frame.source_latency_s
            callback = self.on_frame
        if callback is not None:
            callback(frame)
        return True

    @staticmethod
    def _is_new(previous: Frame, frame: Frame) -> bool:
        if frame.received_at - previous.received_at >= FRAME_MIN_INTERVAL_S:
            return True
        return any(
            abs(current - prior) > FRAME_MIN_DELTA_M
            for current, prior in zip(frame.xyz(), previous.xyz())
        )

    def _update_velocity(self, previous: Frame | None, frame: Frame) -> None:
        if previous is None:
            return
        dt = frame.received_at - previous.received_at
        if not VELOCITY_MIN_DT_S <= dt <= VELOCITY_MAX_DT_S:
            self.velocity = None
            return
        raw = tuple((c - p) / dt for c, p in zip(frame.xyz(), previous.xyz()))
        if not all(math.isfinite(v) and abs(v) <= VELOCITY_MAX_MPS for v in raw):
            self.velocity = None
            return
        if self.velocity is None:
            self.velocity = raw
        else:
            self.velocity = tuple(
                (1.0 - VELOCITY_ALPHA) * f + VELOCITY_ALPHA * r for f, r in zip(self.velocity, raw)
            )

    # -- Consultas ------------------------------------------------------------

    def frozen(self) -> bool:
        """True si la posición lleva `FROZEN_AFTER_S` sin cambiar: rastreo perdido."""
        with self.lock:
            frame, changed = self.frame, self.last_change_at
        if frame is None or changed is None:
            return False
        return frame.received_at - changed > FROZEN_AFTER_S

    def fresh(self, max_age_s: float = MOCAP_TIMEOUT_S) -> Frame | None:
        """Último frame si tiene menos de `max_age_s` y no está congelado; si no, None."""
        with self.lock:
            frame = self.frame
        if frame is None or ahora() - frame.received_at > max_age_s or self.frozen():
            return None
        return frame

    def age_s(self) -> float | None:
        with self.lock:
            frame = self.frame
        return None if frame is None else ahora() - frame.received_at

    def stats(self, window_s: float = STATS_WINDOW_S) -> dict[str, float | int | None]:
        """Tasa de frames distintos y hueco máximo en la última ventana."""
        now = ahora()
        with self.lock:
            recent = [f.received_at for f in self.history if now - f.received_at <= window_s]
            counts = {
                "mqtt_msgs": self.messages,
                "mqtt_duplicados": self.duplicates,
                "mqtt_invalidos": self.invalid,
                "frames": self.frames,
                "latencia_s": self.latency_s,
                "latencia_max_s": self.latency_max_s,
            }
        hz: float | None = None
        gap: float | None = None
        if len(recent) >= 2:
            span = recent[-1] - recent[0]
            hz = (len(recent) - 1) / span if span > 0 else None
            gap = max(b - a for a, b in zip(recent, recent[1:]))
        return counts | {"frames_hz": hz, "hueco_max_s": gap, "congelado": self.frozen()}

    def stable_window(self, seconds: float) -> list[Frame]:
        """Frames de los últimos `seconds` segundos (para el origen del preflight)."""
        now = ahora()
        with self.lock:
            return [f for f in self.history if now - f.received_at <= seconds]


__all__ = [
    "Frame",
    "MocapFeed",
    "parse_message",
    "parse_timestamp",
    "quaternion_yaw_deg",
    "quaternion_euler_deg",
    "FRAME_MIN_DELTA_M",
    "FRAME_MIN_INTERVAL_S",
    "FROZEN_AFTER_S",
]
