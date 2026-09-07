"""Estado de un Crazyflie sobre el Robotat: pose MQTT, extpos, telemetría EKF y preflight.

Lo usa el backend high-level de la cruz (`cruz_highlevel_backend.py`) para uno
o dos drones. No decide vuelo: recibe la pose del Robotat, la reenvía al EKF
por `extpos`, registra la estimación del dron y valida que ambas coincidan
antes de armar.
"""

from __future__ import annotations

import json
import math
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.log import LogConfig

SHARED_DIR = Path(__file__).resolve().parents[1] / "shared"
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))
from crazyflie_link import configure_estimator  # noqa: E402
from robotat import MOCAP_TIMEOUT_S, MQTT_BROKER, MQTT_PORT  # noqa: E402

# El envío de posición externa comparte la misma Crazyradio con los setpoints
# de dos drones. Mantenerlo a 20 Hz por unidad replica el hover individual
# estable y evita saturar el enlace con paquetes extpos redundantes.
EXTPOS_RATE_HZ = 20.0
MOCAP_VELOCITY_ALPHA = 0.25
PREFLIGHT_TIMEOUT_S = 15.0
PREFLIGHT_STABLE_S = 2.0
PREFLIGHT_MAX_SPREAD_M = 0.030
EKF_ALIGNMENT_M = 0.070
EKF_ALIGNMENT_HOLD_S = 1.0
EKF_ALIGNMENT_TIMEOUT_S = 12.0


def parse_mqtt_timestamp(value) -> datetime | None:
    """Convierte timestamps Robotat ISO-8601 o Unix a UTC."""
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
            return parse_mqtt_timestamp(float(text))
        except ValueError:
            pass
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def mqtt_timestamp_is_older(current: datetime | None, previous: datetime | None) -> bool:
    """Indica un retroceso real; timestamps repetidos siguen siendo válidos."""
    return current is not None and previous is not None and current < previous


@dataclass(frozen=True)
class Pose:
    x: float
    y: float
    z: float
    received_at: float

    def xyz(self) -> tuple[float, float, float]:
        return self.x, self.y, self.z


class DroneUnit:
    """Estado y recepción MoCap de un Crazyflie."""

    def __init__(self, name: str, uri: str, topic: str) -> None:
        self.name = name
        self.uri = uri
        self.topic = topic
        self.lock = threading.RLock()
        self.cf: Crazyflie | None = None
        self.pose: Pose | None = None
        self.mocap_velocity: tuple[float, float, float] | None = None
        self.estimate: Pose | None = None
        self.history: deque[Pose] = deque(maxlen=240)
        self.mocap_hz = 0.0
        self.mocap_interval_s = 0.0
        self._intervals: deque[float] = deque(maxlen=30)
        self._last_extpos_send = 0.0
        self.extpos_submitted = 0
        self.extpos_errors = 0
        self.extpos_last_error: str | None = None
        self.mqtt_total_msgs = 0
        self.mqtt_accepted_msgs = 0
        self.mqtt_out_of_order_msgs = 0
        self.mqtt_invalid_msgs = 0
        self.mqtt_source_latency_s: float | None = None
        self.mqtt_source_latency_max_s: float | None = None
        self.mqtt_last_source_ts: datetime | None = None
        self._mqtt: mqtt.Client | None = None
        self._state_log: LogConfig | None = None
        self.origin: tuple[float, float, float] | None = None
        self.target: list[float] | None = None
        self.error: tuple[float, float, float] | None = None
        self.command: tuple[float, float, float] | None = None
        self.ekf_mocap_error: float | None = None
        self.separation: float | None = None
        self.roll_deg: float | None = None
        self.pitch_deg: float | None = None
        self.battery_v: float | None = None
        self.battery_level_pct: int | None = None
        self.airborne = False
        self.mode = "PREFLIGHT"
        self.status = "Esperando MoCap"

    # -- MoCap ---------------------------------------------------------------

    def start_mocap(self) -> None:
        if self._mqtt is not None:
            return
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.on_message = self._on_mocap
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.subscribe(self.topic)
        client.loop_start()
        self._mqtt = client

    def stop_mocap(self) -> None:
        if self._mqtt is None:
            return
        try:
            self._mqtt.loop_stop()
            self._mqtt.disconnect()
        finally:
            self._mqtt = None

    def _on_mocap(self, _client, _userdata, message) -> None:
        with self.lock:
            self.mqtt_total_msgs += 1
        try:
            data = json.loads(message.payload.decode("utf-8"))
            position = data["payload"]["pose"]["position"]
            xyz = tuple(float(position[axis]) for axis in ("x", "y", "z"))
            if not all(math.isfinite(value) for value in xyz):
                raise ValueError("pose no finita")
            source_ts = parse_mqtt_timestamp(data.get("ts"))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            with self.lock:
                self.mqtt_invalid_msgs += 1
            return

        now = time.monotonic()
        source_latency_s = None
        if source_ts is not None:
            source_latency_s = (datetime.now(timezone.utc) - source_ts).total_seconds()
        with self.lock:
            # Robotat puede publicar varios frames validos dentro de la misma
            # marca temporal. Solo rechazamos retrocesos reales.
            if mqtt_timestamp_is_older(source_ts, self.mqtt_last_source_ts):
                self.mqtt_out_of_order_msgs += 1
                return
            if source_ts is not None:
                self.mqtt_last_source_ts = source_ts
                self.mqtt_source_latency_s = source_latency_s
                if (
                    self.mqtt_source_latency_max_s is None
                    or source_latency_s > self.mqtt_source_latency_max_s
                ):
                    self.mqtt_source_latency_max_s = source_latency_s
            self.mqtt_accepted_msgs += 1
            previous = self.pose
            if previous is not None:
                interval = now - previous.received_at
                if 0.0 < interval < 1.0:
                    self._intervals.append(interval)
                    self.mocap_interval_s = sum(self._intervals) / len(self._intervals)
                    self.mocap_hz = 1.0 / self.mocap_interval_s
                if 0.015 <= interval <= 0.25:
                    raw_velocity = tuple(
                        (current - prior) / interval
                        for current, prior in zip(xyz, previous.xyz())
                    )
                    if all(math.isfinite(value) and abs(value) <= 5.0 for value in raw_velocity):
                        if self.mocap_velocity is None:
                            self.mocap_velocity = raw_velocity
                        else:
                            alpha = MOCAP_VELOCITY_ALPHA
                            self.mocap_velocity = tuple(
                                (1.0 - alpha) * filtered + alpha * raw
                                for filtered, raw in zip(self.mocap_velocity, raw_velocity)
                            )
                else:
                    self.mocap_velocity = None
            self.pose = Pose(*xyz, received_at=now)
            self.history.append(self.pose)
            cf = self.cf
            should_send_extpos = (
                cf is not None
                and now - self._last_extpos_send >= 1.0 / EXTPOS_RATE_HZ
            )
            if should_send_extpos:
                self._last_extpos_send = now
        if should_send_extpos:
            try:
                # El puente ROBOTAT publica metros en el marco global.
                cf.extpos.send_extpos(*xyz)
                with self.lock:
                    # La llamada retorno sin error; no confirma recepcion en firmware.
                    self.extpos_submitted += 1
            except Exception as exc:
                with self.lock:
                    self.extpos_errors += 1
                    self.extpos_last_error = f"{type(exc).__name__}: {exc}"

    def mqtt_metrics(self) -> dict[str, float | int | str | None]:
        with self.lock:
            discarded = self.mqtt_out_of_order_msgs + self.mqtt_invalid_msgs
            acceptance = (
                self.mqtt_accepted_msgs / self.mqtt_total_msgs
                if self.mqtt_total_msgs
                else 0.0
            )
            return {
                "mqtt_total_msgs": self.mqtt_total_msgs,
                "mqtt_accepted_msgs": self.mqtt_accepted_msgs,
                "mqtt_discarded_msgs": discarded,
                "mqtt_out_of_order_msgs": self.mqtt_out_of_order_msgs,
                "mqtt_invalid_msgs": self.mqtt_invalid_msgs,
                "mqtt_acceptance_ratio": acceptance,
                "mqtt_source_latency_s": self.mqtt_source_latency_s,
                "mqtt_source_latency_max_s": self.mqtt_source_latency_max_s,
                "mqtt_source_ts": (
                    None
                    if self.mqtt_last_source_ts is None
                    else self.mqtt_last_source_ts.isoformat()
                ),
            }

    def fresh_pose(self) -> Pose | None:
        with self.lock:
            if self.pose is None or time.monotonic() - self.pose.received_at > MOCAP_TIMEOUT_S:
                return None
            return self.pose

    # -- EKF -----------------------------------------------------------------

    def _start_ekf_log(self, cf: Crazyflie) -> None:
        config = LogConfig(name=f"State_{self.name.replace(' ', '')}", period_in_ms=50)
        for axis in ("x", "y", "z"):
            config.add_variable(f"stateEstimate.{axis}", "float")
        config.add_variable("stabilizer.roll", "float")
        config.add_variable("stabilizer.pitch", "float")
        config.add_variable("pm.vbat", "float")
        config.add_variable("pm.batteryLevel", "uint8_t")
        cf.log.add_config(config)
        config.data_received_cb.add_callback(self._on_ekf)
        config.start()
        self._state_log = config

    def _on_ekf(self, _timestamp, data, _logconf) -> None:
        try:
            estimate = Pose(
                float(data["stateEstimate.x"]),
                float(data["stateEstimate.y"]),
                float(data["stateEstimate.z"]),
                time.monotonic(),
            )
        except (KeyError, TypeError, ValueError):
            return
        with self.lock:
            self.estimate = estimate
            self.roll_deg = float(data.get("stabilizer.roll", 0.0))
            self.pitch_deg = float(data.get("stabilizer.pitch", 0.0))
            self.battery_v = float(data.get("pm.vbat", 0.0))
            self.battery_level_pct = int(data.get("pm.batteryLevel", 0))

    def configure(self) -> None:
        """Prepara el EKF para posición externa con el commander high-level activo."""
        with self.lock:
            cf = self.cf
            self.status = "Configurando high-level"
        if cf is None:
            raise RuntimeError(f"{self.name}: no hay enlace Crazyflie")
        if self.fresh_pose() is None:
            raise RuntimeError(f"{self.name}: no hay MoCap fresco en {self.topic}")
        configure_estimator(cf, high_level=True)
        self._start_ekf_log(cf)
        with self.lock:
            self.status = "EKF high-level estabilizando"
            self.mode = "PREFLIGHT_HIGHLEVEL"

    def stop_ekf_log(self) -> None:
        if self._state_log is not None:
            try:
                self._state_log.stop()
            except Exception:
                pass
            self._state_log = None

    # -- Preflight -----------------------------------------------------------

    def wait_for_stable_origin(self) -> tuple[float, float, float]:
        """Promedia una ventana de MoCap inmovil para reducir el salto inicial."""
        deadline = time.monotonic() + PREFLIGHT_TIMEOUT_S
        max_samples = 0
        best_spread = None
        while time.monotonic() < deadline:
            now = time.monotonic()
            with self.lock:
                samples = [sample for sample in self.history if now - sample.received_at <= PREFLIGHT_STABLE_S]
            max_samples = max(max_samples, len(samples))
            if len(samples) >= 20:
                xs, ys, zs = zip(*(sample.xyz() for sample in samples))
                spread = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
                best_spread = spread if best_spread is None else min(best_spread, spread)
                if spread <= PREFLIGHT_MAX_SPREAD_M:
                    origin = (
                        sum(xs) / len(xs),
                        sum(ys) / len(ys),
                        sum(zs) / len(zs),
                    )
                    with self.lock:
                        self.origin = origin
                        self.target = list(origin)
                        self.status = "Origen MoCap estable"
                    return origin
            time.sleep(0.05)
        metrics = self.mqtt_metrics()
        spread_text = "sin ventana suficiente" if best_spread is None else f"mejor dispersion={best_spread:.3f} m"
        raise RuntimeError(
            f"{self.name}: el marcador no estuvo estable por {PREFLIGHT_STABLE_S:.1f} s "
            f"(max_muestras={max_samples}, {spread_text}, "
            f"MQTT={metrics['mqtt_total_msgs']}, aceptados={metrics['mqtt_accepted_msgs']}, "
            f"descartados={metrics['mqtt_discarded_msgs']})"
        )

    def wait_for_ekf_alignment(self) -> None:
        deadline = time.monotonic() + EKF_ALIGNMENT_TIMEOUT_S
        aligned_since: float | None = None
        while time.monotonic() < deadline:
            pose = self.fresh_pose()
            with self.lock:
                estimate = self.estimate
            if pose is not None and estimate is not None:
                error = math.dist(pose.xyz(), estimate.xyz())
                with self.lock:
                    self.ekf_mocap_error = error
                if error <= EKF_ALIGNMENT_M:
                    aligned_since = aligned_since or time.monotonic()
                    if time.monotonic() - aligned_since >= EKF_ALIGNMENT_HOLD_S:
                        with self.lock:
                            self.status = "Listo para prueba"
                        return
                else:
                    aligned_since = None
            time.sleep(0.05)
        detail = (
            f"{self.name}: EKF y MoCap no se alinearon (< {EKF_ALIGNMENT_M:.2f} m)\n"
            + self.ekf_alignment_diagnostic()
        )
        print(detail, flush=True)
        raise RuntimeError(detail)

    def ekf_alignment_diagnostic(self) -> str:
        """Describe el ultimo estado recibido sin consultar ni configurar hardware."""
        now = time.monotonic()
        with self.lock:
            pose, estimate, cf = self.pose, self.estimate, self.cf
            submitted, errors = self.extpos_submitted, self.extpos_errors
            last_error = self.extpos_last_error
            roll, pitch, battery = self.roll_deg, self.pitch_deg, self.battery_v

        def describe(value: Pose | None) -> str:
            if value is None:
                return "sin datos"
            xyz = ", ".join(f"{coordinate:+.3f}" for coordinate in value.xyz())
            return f"({xyz}) m; edad={now - value.received_at:.3f} s"

        difference = "sin datos comparables"
        if pose is not None and estimate is not None:
            difference = f"{math.dist(pose.xyz(), estimate.xyz()):.3f} m (ultimas muestras)"
        # Solo cache local de parametros: no solicita lecturas por radio.
        values = {} if cf is None else cf.param.values
        estimator = values.get("stabilizer", {}).get("estimator", "desconocido")
        reset = values.get("kalman", {}).get("resetEstimation", "desconocido")
        lines = [
            f"URI={self.uri}; topic={self.topic}",
            f"MoCap: {describe(pose)}",
            f"EKF: {describe(estimate)}; diferencia={difference}",
            f"Extpos acumulado: llamadas sin error={submitted}; errores={errors} (sin acuse del dron)",
            f"Parametros en cache: stabilizer.estimator={estimator}; kalman.resetEstimation={reset}",
            f"Ultima telemetria: roll={roll}; pitch={pitch}; bateria={battery}",
        ]
        if last_error is not None:
            lines.append(f"Ultimo error extpos: {last_error}")
        return "\n".join(lines)
