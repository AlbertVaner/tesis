"""Hover low-level basado en el controlador funcional de referencia."""

from __future__ import annotations

import argparse
import json
import math
import msvcrt
import threading
import time
from datetime import datetime

import cflib.crtp
import paho.mqtt.client as mqtt
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.log import LogConfig
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie


URI = "radio://0/84/2M/E7E7E7E7E4"
MQTT_BROKER = "192.168.50.200"
MQTT_PORT = 1880
MQTT_TOPIC = "mocap/drone3"

CONTROL_PERIOD_S = 0.05
MOCAP_TIMEOUT_S = 0.75
MOCAP_TAKEOFF_GRACE_S = 1.50
TAKEOFF_SPEED_M_S = 0.10
LANDING_SPEED_M_S = 0.10
KP_XY = 0.60
KP_Z = 0.80
MAX_XY_SPEED_M_S = 0.16
MAX_Z_SPEED_M_S = 0.15
TAKEOFF_TOLERANCE_M = 0.03
MAX_HORIZONTAL_ERROR_M = 0.25
MAX_HEIGHT_OVERSHOOT_M = 0.10


class FlightState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.position: tuple[float, float, float] | None = None
        self.last_update = 0.0
        self.last_timestamp: datetime | None = None
        self.cf: Crazyflie | None = None
        self.stop_event = threading.Event()
        self.emergency = threading.Event()
        self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.mqtt_client.on_message = self._on_message

    def _on_message(self, _client, _userdata, message) -> None:
        try:
            data = json.loads(message.payload.decode("utf-8"))
            timestamp = data.get("ts")
            if timestamp is not None:
                parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                # Aceptar timestamps iguales: algunos publicadores emiten
                # varios frames dentro de la misma marca temporal.
                if self.last_timestamp is not None and parsed < self.last_timestamp:
                    return
                self.last_timestamp = parsed

            position = data["payload"]["pose"]["position"]
            xyz = (
                float(position["x"]),
                float(position["y"]),
                float(position["z"]),
            )
            if not all(math.isfinite(value) for value in xyz):
                return

            with self.lock:
                self.position = xyz
                self.last_update = time.monotonic()

            if self.cf is not None:
                # El puente MQTT ya entrega metros. No rotar ni trasladar.
                self.cf.extpos.send_extpos(*xyz)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            print("Mensaje MoCap inválido ignorado.")

    def run_mqtt(self) -> None:
        self.mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        self.mqtt_client.subscribe(MQTT_TOPIC)
        self.mqtt_client.loop_start()
        self.stop_event.wait()
        self.mqtt_client.loop_stop()
        self.mqtt_client.disconnect()

    def get_position(self) -> tuple[float, float, float] | None:
        with self.lock:
            return self.position

    def fresh(self) -> bool:
        with self.lock:
            return (
                self.position is not None
                and time.monotonic() - self.last_update <= MOCAP_TIMEOUT_S
            )

    def age(self) -> float:
        with self.lock:
            if self.last_update <= 0.0:
                return math.inf
            return time.monotonic() - self.last_update

    def wait_for_mocap(self, timeout_s=10.0) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.fresh():
                return True
            time.sleep(0.05)
        return False


class Telemetry:
    def __init__(self, cf: Crazyflie, flight: FlightState) -> None:
        self.flight = flight
        self.config = LogConfig(name="LowLevelState", period_in_ms=200)
        for axis in ("x", "y", "z"):
            self.config.add_variable(f"stateEstimate.{axis}", "float")
        cf.log.add_config(self.config)
        self.config.data_received_cb.add_callback(self._callback)
        self.last_print = 0.0

    def _callback(self, _timestamp, data, _config) -> None:
        now = time.monotonic()
        if now - self.last_print < 0.5:
            return
        self.last_print = now
        mocap_position = self.flight.get_position()
        if mocap_position is None:
            return
        ex, ey, ez = (
            float(data[f"stateEstimate.{axis}"])
            for axis in ("x", "y", "z")
        )
        mx, my, mz = mocap_position
        print(
            f"EKF=({ex:+.3f}, {ey:+.3f}, {ez:+.3f}) | "
            f"MOC=({mx:+.3f}, {my:+.3f}, {mz:+.3f}) | "
            f"EKF-MOC=({ex-mx:+.3f}, {ey-my:+.3f}, {ez-mz:+.3f}) | "
            f"edad={self.flight.age():.3f}s"
        )

    def start(self) -> None:
        self.config.start()

    def stop(self) -> None:
        try:
            self.config.stop()
        except Exception:
            pass


def keyboard_emergency(flight: FlightState) -> None:
    print("Durante el vuelo: Q = APAGAR MOTORES")
    while not flight.stop_event.is_set() and not flight.emergency.is_set():
        if msvcrt.kbhit() and msvcrt.getch().lower() == b"q":
            print("\nPARO DE EMERGENCIA")
            flight.emergency.set()
            return
        time.sleep(0.02)


def configure(cf: Crazyflie) -> None:
    cf.param.set_value("commander.enHighLevel", "0")
    cf.param.set_value("stabilizer.controller", "1")
    cf.param.set_value("stabilizer.estimator", "2")
    cf.param.set_value("kalman.resetEstimation", "1")
    time.sleep(0.1)
    cf.param.set_value("kalman.resetEstimation", "0")
    print("Esperando estabilización del EKF (5 s)...")
    time.sleep(5.0)


def stop_motors(cf: Crazyflie) -> None:
    for _ in range(15):
        try:
            cf.commander.send_stop_setpoint()
        except Exception:
            pass
        time.sleep(0.03)


def horizontal_command(ex: float, ey: float) -> tuple[float, float]:
    vx = KP_XY * ex
    vy = KP_XY * ey
    speed = math.hypot(vx, vy)
    if speed > MAX_XY_SPEED_M_S:
        scale = MAX_XY_SPEED_M_S / speed
        vx *= scale
        vy *= scale
    return vx, vy


def safety_status(
    flight: FlightState,
    target: tuple[float, float, float],
) -> str | None:
    if flight.emergency.is_set():
        return "emergency"
    if not flight.fresh():
        return "mocap"
    position = flight.get_position()
    assert position is not None
    if position[2] > target[2] + MAX_HEIGHT_OVERSHOOT_M:
        return "height"
    if math.hypot(position[0] - target[0], position[1] - target[1]) > (
        MAX_HORIZONTAL_ERROR_M
    ):
        return "horizontal"
    return None


def takeoff(
    cf: Crazyflie,
    flight: FlightState,
    target: tuple[float, float, float],
) -> str | None:
    print(
        f"Despegando low-level hasta z={target[2]:.3f} m "
        f"con vz={TAKEOFF_SPEED_M_S:.2f} m/s..."
    )
    start = flight.get_position()
    assert start is not None
    timeout = (target[2] - start[2]) / TAKEOFF_SPEED_M_S + 5.0
    deadline = time.monotonic() + timeout
    grace_deadline = time.monotonic() + MOCAP_TAKEOFF_GRACE_S

    while time.monotonic() < deadline:
        if flight.emergency.is_set():
            return "emergency"
        if time.monotonic() >= grace_deadline:
            status = safety_status(flight, target)
            if status is not None:
                return status
        position = flight.get_position()
        assert position is not None
        if position[2] >= target[2] - TAKEOFF_TOLERANCE_M:
            cf.commander.send_velocity_world_setpoint(0.0, 0.0, 0.0, 0.0)
            return None

        # Mantener el punto inicial con el mismo control P horizontal usado
        # por lowlevel_goto() en el código funcional de referencia.
        vx, vy = horizontal_command(
            target[0] - position[0],
            target[1] - position[1],
        )
        cf.commander.send_velocity_world_setpoint(
            vx, vy, TAKEOFF_SPEED_M_S, 0.0
        )
        time.sleep(CONTROL_PERIOD_S)
    return "timeout"


def hover(
    cf: Crazyflie,
    flight: FlightState,
    target: tuple[float, float, float],
    duration_s: float,
) -> str | None:
    print(f"Hover low-level durante {duration_s:.1f} s...")
    deadline = time.monotonic() + duration_s
    while time.monotonic() < deadline:
        status = safety_status(flight, target)
        if status is not None:
            return status
        position = flight.get_position()
        assert position is not None
        ex = target[0] - position[0]
        ey = target[1] - position[1]
        ez = target[2] - position[2]
        vx, vy = horizontal_command(ex, ey)
        vz = max(-MAX_Z_SPEED_M_S, min(MAX_Z_SPEED_M_S, KP_Z * ez))
        cf.commander.send_velocity_world_setpoint(vx, vy, vz, 0.0)
        time.sleep(CONTROL_PERIOD_S)
    return None


def land(
    cf: Crazyflie,
    flight: FlightState,
    start: tuple[float, float, float],
) -> None:
    print("Aterrizando low-level...")
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        if flight.emergency.is_set() or not flight.fresh():
            break
        position = flight.get_position()
        assert position is not None
        if position[2] <= start[2] + 0.04:
            break
        vx, vy = horizontal_command(
            start[0] - position[0],
            start[1] - position[1],
        )
        cf.commander.send_velocity_world_setpoint(
            vx, vy, -LANDING_SPEED_M_S, 0.0
        )
        time.sleep(CONTROL_PERIOD_S)
    cf.commander.send_velocity_world_setpoint(0.0, 0.0, 0.0, 0.0)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Hover low-level basado en el código funcional"
    )
    parser.add_argument("--height", type=float, default=0.15)
    parser.add_argument("--hover-time", type=float, default=3.0)
    args = parser.parse_args()
    if not 0.10 <= args.height <= 0.40:
        parser.error("--height debe estar entre 0.10 y 0.40 m")
    if args.hover_time <= 0.0:
        parser.error("--hover-time debe ser positivo")
    return args


def main() -> None:
    args = parse_args()
    flight = FlightState()
    mqtt_thread = threading.Thread(target=flight.run_mqtt, daemon=True)
    mqtt_thread.start()
    cf: Crazyflie | None = None
    telemetry: Telemetry | None = None
    flying = False

    try:
        print(f"Esperando MoCap global en {MQTT_TOPIC}...")
        if not flight.wait_for_mocap():
            raise RuntimeError("No se recibió posición MoCap")
        start = flight.get_position()
        assert start is not None
        print(
            f"Posición inicial global: "
            f"x={start[0]:.3f}, y={start[1]:.3f}, z={start[2]:.3f}"
        )

        cflib.crtp.init_drivers(enable_debug_driver=False)
        with SyncCrazyflie(
            URI, cf=Crazyflie(rw_cache="./cache")
        ) as scf:
            cf = scf.cf
            flight.cf = cf
            configure(cf)

            if not flight.fresh():
                raise RuntimeError("MoCap perdido antes del vuelo")
            start = flight.get_position()
            assert start is not None
            target = (start[0], start[1], start[2] + args.height)
            print(
                f"Objetivo global: "
                f"x={target[0]:.3f}, y={target[1]:.3f}, z={target[2]:.3f}"
            )
            input("Área despejada. ENTER para volar...")

            telemetry = Telemetry(cf, flight)
            telemetry.start()
            threading.Thread(
                target=keyboard_emergency,
                args=(flight,),
                daemon=True,
            ).start()

            flying = True
            result = takeoff(cf, flight, target)
            if result is None:
                result = hover(cf, flight, target, args.hover_time)
            if result is None:
                land(cf, flight, start)
            else:
                if result == "mocap":
                    print(
                        f"ABORTANDO: mocap "
                        f"(último paquete hace {flight.age():.2f} s)"
                    )
                else:
                    print(f"ABORTANDO: {result}")

            stop_motors(cf)
            flying = False
            print("Motores apagados.")

    except KeyboardInterrupt:
        print("\nCtrl+C recibido.")
    except Exception as exc:
        print(f"ERROR: {exc}")
    finally:
        if telemetry is not None:
            telemetry.stop()
        if cf is not None and flying:
            stop_motors(cf)
        flight.cf = None
        flight.stop_event.set()
        mqtt_thread.join(timeout=1.0)
        print("Prueba finalizada.")


if __name__ == "__main__":
    main()
