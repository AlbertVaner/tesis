r"""Prueba conservadora de hover simultaneo para dos Crazyflies.

Se usa el mismo principio low-level que funciono con un solo dron: MoCap es el
lazo externo y cada Crazyflie recibe comandos de velocidad globales limitados.
No reutiliza el comandante high-level ni envia movimientos manuales; esta
version existe exclusivamente para medir estabilidad de altura y posicion.

Ejemplo recomendado para la primera prueba:
    .\.venv\Scripts\python.exe .\drone_control\prueba_estabilidad_dos_drones_lowlevel.py

Q corta los motores de ambos drones inmediatamente. Al finalizar, se genera un
CSV en drone_control/datos_dos_drones y se ejecuta su analizador de graficas.
"""

from __future__ import annotations

import argparse
import json
import math
import msvcrt
import subprocess
import sys
import threading
import time
from collections import deque
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import cflib.crtp
import paho.mqtt.client as mqtt
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.log import LogConfig
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie

from dual_flight_logger import DualFlightLogger


BROKER = "192.168.50.200"
PORT = 1880
# Usar el serial de cada Crazyradio es más seguro que los índices 0/1, que
# Windows puede intercambiar al reconectar los puertos USB.
DEFAULT_URI_1 = "radio://2B1D933FCC/84/2M/E7E7E7E7E4"
DEFAULT_URI_2 = "radio://9DD2507072/90/2M/E7E7E7E7E5"
DEFAULT_TOPIC_1 = "mocap/drone3"
DEFAULT_TOPIC_2 = "mocap/drone4"

# Perfil vertical del hover individual que funcionó con el Dron 2. Conserva
# todas las protecciones duales (separación, límite de altura y paro), pero
# evita que el comportamiento vertical sea distinto al de esa referencia.
CONTROL_PERIOD_S = 0.05
# El envío de posición externa comparte la misma Crazyradio con los setpoints
# de dos drones. Mantenerlo a 20 Hz por unidad replica el hover individual
# estable y evita saturar el enlace con paquetes extpos redundantes.
EXTPOS_RATE_HZ = 20.0
MOCAP_VELOCITY_ALPHA = 0.25
MOCAP_TIMEOUT_S = 0.75
PREFLIGHT_TIMEOUT_S = 15.0
PREFLIGHT_STABLE_S = 2.0
PREFLIGHT_MAX_SPREAD_M = 0.030
EKF_ALIGNMENT_M = 0.070
EKF_ALIGNMENT_HOLD_S = 1.0
EKF_ALIGNMENT_TIMEOUT_S = 12.0
TAKEOFF_RATE_M_S = 0.10
LANDING_RATE_M_S = 0.04
KP_XY = 0.45
KP_Z = 0.80
# La bateria de 450 mAh aumenta la inercia. El dron 2 recibe una pequena
# realimentacion de velocidad MoCap para amortiguar la oscilacion sin elevar KP.
DAMPING_KD_XY_DRON_2 = 0.18
MAX_XY_SPEED_M_S = 0.10
MAX_Z_SPEED_M_S = 0.10
XY_DEADBAND_M = 0.015
Z_DEADBAND_M = 0.0
COMMAND_SLEW_XY_M_S2 = 0.30
# El hover individual no filtraba la orden vertical. Este valor alto conserva
# el límite de velocidad pero hace que el setpoint alcance la orden P en un
# ciclo de 50 ms, igualando esa referencia.
COMMAND_SLEW_Z_M_S2 = 2.0
MAX_HORIZONTAL_ERROR_M = 0.30
MAX_HEIGHT_OVERSHOOT_M = 0.10
MAX_EKF_MOCAP_ERROR_M = 0.10
LANDING_MARGIN_M = 0.045
MIN_SEPARATION_M = 0.70


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
    """Estado, recepcion MoCap y lazo de velocidad de un Crazyflie."""

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
        self.abort_reason: str | None = None

    def start_mocap(self) -> None:
        if self._mqtt is not None:
            return
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.on_message = self._on_mocap
        client.connect(BROKER, PORT, 60)
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
            except Exception:
                pass

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
        with self.lock:
            cf = self.cf
            self.status = "Configurando EKF"
        if cf is None:
            raise RuntimeError(f"{self.name}: no hay enlace Crazyflie")
        if self.fresh_pose() is None:
            raise RuntimeError(f"{self.name}: no hay MoCap fresco en {self.topic}")
        cf.param.set_value("commander.enHighLevel", "0")
        cf.param.set_value("stabilizer.controller", "1")
        cf.param.set_value("stabilizer.estimator", "2")
        cf.param.set_value("kalman.resetEstimation", "1")
        time.sleep(0.10)
        cf.param.set_value("kalman.resetEstimation", "0")
        self._start_ekf_log(cf)
        with self.lock:
            self.status = "EKF estabilizando"

    def stop_ekf_log(self) -> None:
        if self._state_log is not None:
            try:
                self._state_log.stop()
            except Exception:
                pass
            self._state_log = None

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
        raise RuntimeError(f"{self.name}: EKF y MoCap no se alinearon (< {EKF_ALIGNMENT_M:.2f} m)")

    def set_abort(self, reason: str) -> None:
        with self.lock:
            self.abort_reason = reason
            self.status = f"ABORTADO: {reason}"
            self.mode = "ABORT"
            self.airborne = False

    def send_stop(self) -> None:
        with self.lock:
            cf = self.cf
            self.command = (0.0, 0.0, 0.0)
            self.airborne = False
            if self.mode != "ABORT":
                self.mode = "MOTORES_OFF"
        if cf is not None:
            for _ in range(15):
                try:
                    cf.commander.send_stop_setpoint()
                except Exception:
                    pass
                time.sleep(0.03)


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def deadband(value: float, threshold: float) -> float:
    return 0.0 if abs(value) <= threshold else value


def slew(previous: float, requested: float, max_acceleration: float, dt: float) -> float:
    delta = clamp(requested - previous, -max_acceleration * dt, max_acceleration * dt)
    return previous + delta


def print_status(units: tuple[DroneUnit, DroneUnit]) -> None:
    lines = []
    for unit in units:
        pose = unit.fresh_pose()
        with unit.lock:
            target = unit.target
            error = unit.error
            command = unit.command
            ekf_error = unit.ekf_mocap_error
            status = unit.status
            mode = unit.mode
        pose_text = "sin MoCap" if pose is None else f"z={pose.z:.3f}"
        target_text = "-" if target is None else f"z*={target[2]:.3f}"
        error_text = "-" if error is None else f"ez={error[2]:+.3f}"
        command_text = "-" if command is None else f"vz={command[2]:+.3f}"
        ekf_text = "-" if ekf_error is None else f"EKF-MoCap={ekf_error:.3f}"
        lines.append(f"{unit.name} [{mode}] {pose_text} {target_text} {error_text} {command_text} {ekf_text} | {status}")
    print("\n".join(lines))


def control_loop(
    unit: DroneUnit,
    other: DroneUnit,
    height_m: float,
    hold_s: float,
    start_event: threading.Event,
    emergency_event: threading.Event,
) -> None:
    """Genera una trayectoria vertical lenta y un hover P-controlado por MoCap."""
    try:
        if not start_event.wait(timeout=5.0):
            unit.set_abort("inicio sincronizado no recibido")
            emergency_event.set()
            return
        with unit.lock:
            origin = unit.origin
            cf = unit.cf
            unit.airborne = True
            unit.mode = "TAKEOFF"
            unit.status = "Despegue low-level lento"
        if origin is None or cf is None:
            unit.set_abort("sin origen o enlace")
            emergency_event.set()
            return

        takeoff_time = height_m / TAKEOFF_RATE_M_S
        takeoff_end = time.monotonic() + takeoff_time
        hold_end = takeoff_end + hold_s
        target_z = origin[2]
        previous_command = (0.0, 0.0, 0.0)
        previous_time = time.monotonic()

        while True:
            now = time.monotonic()
            dt = max(0.001, min(0.15, now - previous_time))
            previous_time = now
            pose = unit.fresh_pose()
            other_pose = other.fresh_pose()
            if emergency_event.is_set():
                unit.set_abort("paro global")
                return
            if pose is None:
                unit.set_abort(f"MoCap sin actualizar por > {MOCAP_TIMEOUT_S:.2f} s")
                emergency_event.set()
                return
            if other_pose is None:
                unit.set_abort("MoCap del otro dron perdido")
                emergency_event.set()
                return

            with unit.lock:
                estimate = unit.estimate
            if estimate is not None:
                ekf_error = math.dist(estimate.xyz(), pose.xyz())
                with unit.lock:
                    unit.ekf_mocap_error = ekf_error
                if ekf_error > MAX_EKF_MOCAP_ERROR_M:
                    unit.set_abort(f"EKF-MoCap={ekf_error:.3f} m")
                    emergency_event.set()
                    return

            separation = math.dist(pose.xyz(), other_pose.xyz())
            with unit.lock:
                unit.separation = separation
            if separation < MIN_SEPARATION_M:
                unit.set_abort(f"separacion {separation:.2f} m < {MIN_SEPARATION_M:.2f} m")
                emergency_event.set()
                return

            if now < takeoff_end:
                target_z = min(origin[2] + height_m, target_z + TAKEOFF_RATE_M_S * dt)
                mode = "TAKEOFF"
            elif now < hold_end:
                target_z = origin[2] + height_m
                mode = "HOVER"
            else:
                target_z = max(origin[2], target_z - LANDING_RATE_M_S * dt)
                mode = "LANDING"

            target = (origin[0], origin[1], target_z)
            ex, ey, ez = target[0] - pose.x, target[1] - pose.y, target[2] - pose.z
            horizontal_error = math.hypot(ex, ey)
            if horizontal_error > MAX_HORIZONTAL_ERROR_M:
                unit.set_abort(f"error horizontal {horizontal_error:.3f} m")
                emergency_event.set()
                return
            if pose.z > origin[2] + height_m + MAX_HEIGHT_OVERSHOOT_M:
                unit.set_abort("sobrepaso vertical")
                emergency_event.set()
                return

            requested_vx = clamp(KP_XY * deadband(ex, XY_DEADBAND_M), -MAX_XY_SPEED_M_S, MAX_XY_SPEED_M_S)
            requested_vy = clamp(KP_XY * deadband(ey, XY_DEADBAND_M), -MAX_XY_SPEED_M_S, MAX_XY_SPEED_M_S)
            requested_vz = clamp(KP_Z * deadband(ez, Z_DEADBAND_M), -MAX_Z_SPEED_M_S, MAX_Z_SPEED_M_S)
            command = (
                slew(previous_command[0], requested_vx, COMMAND_SLEW_XY_M_S2, dt),
                slew(previous_command[1], requested_vy, COMMAND_SLEW_XY_M_S2, dt),
                slew(previous_command[2], requested_vz, COMMAND_SLEW_Z_M_S2, dt),
            )
            previous_command = command
            try:
                cf.commander.send_velocity_world_setpoint(*command, 0.0)
            except Exception as exc:
                unit.set_abort(f"fallo enviando setpoint: {exc}")
                emergency_event.set()
                return

            with unit.lock:
                unit.target = list(target)
                unit.error = (ex, ey, ez)
                unit.command = command
                unit.mode = mode
                unit.status = "Hover estable" if mode == "HOVER" else mode

            if mode == "LANDING" and target_z <= origin[2] + 0.002 and pose.z <= origin[2] + LANDING_MARGIN_M:
                with unit.lock:
                    unit.status = "Aterrizado"
                    unit.mode = "LANDED"
                    unit.command = (0.0, 0.0, 0.0)
                    unit.airborne = False
                try:
                    cf.commander.send_velocity_world_setpoint(0.0, 0.0, 0.0, 0.0)
                except Exception:
                    pass
                return
            time.sleep(max(0.0, CONTROL_PERIOD_S - (time.monotonic() - now)))
    finally:
        # El hilo finaliza y el monitor principal detecta su estado con is_alive().
        pass


def keyboard_emergency(emergency_event: threading.Event) -> None:
    print("Durante el vuelo: Q = PARO DE EMERGENCIA DE AMBOS")
    while not emergency_event.is_set():
        if msvcrt.kbhit() and msvcrt.getch().lower() == b"q":
            print("\nPARO DE EMERGENCIA ACTIVADO")
            emergency_event.set()
            return
        time.sleep(0.02)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prueba low-level de estabilidad para dos Crazyflies")
    parser.add_argument("--uri1", default=DEFAULT_URI_1)
    parser.add_argument("--uri2", default=DEFAULT_URI_2)
    parser.add_argument("--topic1", default=DEFAULT_TOPIC_1)
    parser.add_argument("--topic2", default=DEFAULT_TOPIC_2)
    parser.add_argument("--height", type=float, default=0.35, help="ascenso relativo en metros (por defecto: 0.35)")
    parser.add_argument("--hold", type=float, default=12.0, help="segundos de hover que se registraran (por defecto: 12)")
    parser.add_argument("--preflight-only", action="store_true", help="valida MoCap y EKF sin armar motores")
    args = parser.parse_args()
    if not 0.25 <= args.height <= 0.50:
        parser.error("--height debe estar entre 0.25 y 0.50 m")
    if args.hold < 5.0:
        parser.error("--hold debe ser de al menos 5 s para medir estabilidad")
    return args


def run_analysis(csv_path: Path) -> None:
    analyzer = Path(__file__).with_name("analizar_sesion_dos_drones.py")
    try:
        subprocess.run([sys.executable, str(analyzer), str(csv_path)], check=False)
    except Exception as exc:
        print(f"No se pudo iniciar el analisis automatico: {exc}")


def main() -> None:
    args = parse_args()
    first = DroneUnit("Dron 1", args.uri1, args.topic1)
    second = DroneUnit("Dron 2", args.uri2, args.topic2)
    units = (first, second)
    logger = DualFlightLogger()
    emergency_event = threading.Event()
    start_event = threading.Event()
    threads: list[threading.Thread] = []

    cflib.crtp.init_drivers(enable_debug_driver=False)
    for unit in units:
        unit.start_mocap()
    try:
        print(f"Esperando MoCap: {first.topic} y {second.topic}...")
        origins = [unit.wait_for_stable_origin() for unit in units]
        separation = math.dist(origins[0], origins[1])
        if separation < MIN_SEPARATION_M:
            raise RuntimeError(
                f"Drones demasiado cerca: {separation:.2f} m. Se requieren al menos {MIN_SEPARATION_M:.2f} m."
            )
        print(
            f"Origen Dron 1: ({origins[0][0]:+.3f}, {origins[0][1]:+.3f}, {origins[0][2]:+.3f})\n"
            f"Origen Dron 2: ({origins[1][0]:+.3f}, {origins[1][1]:+.3f}, {origins[1][2]:+.3f})\n"
            f"Separacion inicial: {separation:.2f} m"
        )

        with ExitStack() as stack:
            # No asignar unit.cf todavia: el callback MQTT solo manda extpos
            # cuando existe cf. Asi el primer dron no ocupa la Crazyradio con
            # paquetes MoCap mientras se establece el enlace del segundo.
            links: list[SyncCrazyflie] = []
            for unit in units:
                scf = stack.enter_context(SyncCrazyflie(unit.uri, cf=Crazyflie(rw_cache=f"./cache_{unit.name.replace(' ', '_')}")))
                links.append(scf)
            for unit, scf in zip(units, links):
                with unit.lock:
                    unit.cf = scf.cf
            for unit in units:
                unit.configure()
            print("Esperando alineacion EKF - MoCap en ambos drones...")
            for unit in units:
                unit.wait_for_ekf_alignment()
            print_status(units)

            if args.preflight_only:
                print("Preflight correcto. No se enviaron comandos de vuelo.")
                return

            log_path = logger.start()
            logger.event("SISTEMA", "INICIO_PRUEBA_ESTABILIDAD", f"altura={args.height:.2f} m; hold={args.hold:.1f} s")
            for unit in units:
                logger.event(unit.name, "PRECHECK_OK", unit.status)
            print(f"Log CSV: {log_path}")
            input(
                f"Area despejada. ENTER para despegue simultaneo bajo control low-level "
                f"(altura relativa {args.height:.2f} m)..."
            )

            for unit, other in ((first, second), (second, first)):
                thread = threading.Thread(
                    target=control_loop,
                    args=(unit, other, args.height, args.hold, start_event, emergency_event),
                    daemon=True,
                    name=f"Control-{unit.name}",
                )
                threads.append(thread)
                thread.start()
            threading.Thread(target=keyboard_emergency, args=(emergency_event,), daemon=True).start()
            print("Despegando ambos con rampa vertical de 0.04 m/s...")
            start_event.set()

            last_print = 0.0
            while any(thread.is_alive() for thread in threads):
                now = time.monotonic()
                logger.sample(first)
                logger.sample(second)
                if now - last_print >= 0.75:
                    print_status(units)
                    last_print = now
                if emergency_event.is_set():
                    break
                time.sleep(CONTROL_PERIOD_S)

            for thread in threads:
                thread.join(timeout=0.5)
            if emergency_event.is_set():
                logger.event("SISTEMA", "ABORTO_O_EMERGENCIA")
                print("Deteniendo ambos drones por seguridad...")
            else:
                logger.event("SISTEMA", "ATERRIZAJE_COMPLETADO")
                print("Prueba completada y aterrizaje solicitado.")
            for unit in units:
                unit.send_stop()
                logger.sample(unit)
                logger.event(unit.name, "FINAL", unit.status)

    except KeyboardInterrupt:
        emergency_event.set()
        print("Interrupcion de teclado: apagando motores.")
        for unit in units:
            unit.set_abort("interrupcion de teclado")
            unit.send_stop()
    except Exception as exc:
        emergency_event.set()
        print(f"ERROR: {exc}")
        for unit in units:
            unit.set_abort(str(exc))
            unit.send_stop()
    finally:
        for unit in units:
            unit.stop_ekf_log()
            unit.stop_mocap()
        if logger.active:
            logger.event("SISTEMA", "FIN_SESION")
        path = logger.stop()
        if path is not None:
            print(f"CSV guardado: {path}")
            run_analysis(path)


if __name__ == "__main__":
    main()
