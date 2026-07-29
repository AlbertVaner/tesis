"""Hover High Level con posición global de ROBOTAT."""

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

MOCAP_TIMEOUT_S = 0.75
MOCAP_START_GRACE_S = 1.50
TAKEOFF_DURATION_S = 5.0
GOTO_DURATION_S = 2.0
LAND_DURATION_S = 5.0
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
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_message = self._on_message

    def _on_message(self, _client, _userdata, message) -> None:
        try:
            data = json.loads(message.payload.decode("utf-8"))
            timestamp = data.get("ts")
            if timestamp is not None:
                parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                if self.last_timestamp is not None and parsed < self.last_timestamp:
                    return
                self.last_timestamp = parsed

            source = data["payload"]["pose"]["position"]
            xyz = (
                float(source["x"]),
                float(source["y"]),
                float(source["z"]),
            )
            if not all(math.isfinite(value) for value in xyz):
                return

            with self.lock:
                self.position = xyz
                self.last_update = time.monotonic()

            if self.cf is not None:
                # ROBOTAT/MQTT ya entrega metros en el marco global.
                self.cf.extpos.send_extpos(*xyz)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            print("Mensaje MoCap inválido ignorado.")

    def run_mqtt(self) -> None:
        self.client.connect(MQTT_BROKER, MQTT_PORT, 60)
        self.client.subscribe(MQTT_TOPIC)
        self.client.loop_start()
        self.stop_event.wait()
        self.client.loop_stop()
        self.client.disconnect()

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
    def __init__(
        self,
        cf: Crazyflie,
        flight: FlightState,
        target: tuple[float, float, float],
    ) -> None:
        self.flight = flight
        self.target = target
        self.last_print = 0.0
        self.config = LogConfig(name="HighLevelState", period_in_ms=200)
        for axis in ("x", "y", "z"):
            self.config.add_variable(f"stateEstimate.{axis}", "float")
        cf.log.add_config(self.config)
        self.config.data_received_cb.add_callback(self._callback)

    def _callback(self, _timestamp, data, _config) -> None:
        now = time.monotonic()
        if now - self.last_print < 0.5:
            return
        self.last_print = now
        mocap = self.flight.get_position()
        if mocap is None:
            return
        estimate = tuple(
            float(data[f"stateEstimate.{axis}"])
            for axis in ("x", "y", "z")
        )
        error = tuple(
            self.target[index] - estimate[index]
            for index in range(3)
        )
        print(
            f"EKF=({estimate[0]:+.3f}, {estimate[1]:+.3f}, "
            f"{estimate[2]:+.3f}) | "
            f"MOC=({mocap[0]:+.3f}, {mocap[1]:+.3f}, {mocap[2]:+.3f}) | "
            f"ERR=({error[0]:+.3f}, {error[1]:+.3f}, {error[2]:+.3f}) | "
            f"edad={self.flight.age():.3f}s"
        )

    def start(self) -> None:
        self.config.start()

    def stop(self) -> None:
        try:
            self.config.stop()
        except Exception:
            pass


def configure(cf: Crazyflie) -> None:
    cf.param.set_value("commander.enHighLevel", "1")
    cf.param.set_value("stabilizer.controller", "1")
    cf.param.set_value("stabilizer.estimator", "2")
    cf.param.set_value("kalman.resetEstimation", "1")
    time.sleep(0.1)
    cf.param.set_value("kalman.resetEstimation", "0")
    print("Esperando estabilización del EKF (5 s)...")
    time.sleep(5.0)


def keyboard_emergency(flight: FlightState) -> None:
    print("Durante el vuelo: Q = APAGAR MOTORES")
    while not flight.stop_event.is_set() and not flight.emergency.is_set():
        if msvcrt.kbhit() and msvcrt.getch().lower() == b"q":
            print("\nPARO DE EMERGENCIA")
            flight.emergency.set()
            return
        time.sleep(0.02)


def stop_motors(cf: Crazyflie) -> None:
    try:
        cf.high_level_commander.stop()
    except Exception:
        pass
    for _ in range(15):
        try:
            cf.commander.send_stop_setpoint()
        except Exception:
            pass
        time.sleep(0.03)


def monitor(
    flight: FlightState,
    target: tuple[float, float, float],
    duration_s: float,
    grace_s: float = 0.0,
) -> str | None:
    start_time = time.monotonic()
    deadline = start_time + duration_s
    while time.monotonic() < deadline:
        if flight.emergency.is_set():
            return "emergency"
        if time.monotonic() - start_time >= grace_s and not flight.fresh():
            return "mocap"
        position = flight.get_position()
        if position is not None:
            horizontal_error = math.hypot(
                position[0] - target[0],
                position[1] - target[1],
            )
            if horizontal_error > MAX_HORIZONTAL_ERROR_M:
                return "horizontal"
            if position[2] > target[2] + MAX_HEIGHT_OVERSHOOT_M:
                return "height"
        time.sleep(0.03)
    return None


def monitor_landing(
    flight: FlightState,
    start: tuple[float, float, float],
    duration_s: float,
) -> str | None:
    """Espera el descenso sin aplicar el límite de altura del hover."""
    deadline = time.monotonic() + duration_s
    while time.monotonic() < deadline:
        if flight.emergency.is_set():
            return "emergency"
        if not flight.fresh():
            return "mocap"
        position = flight.get_position()
        if position is not None:
            if position[2] <= start[2] + 0.04:
                return None
            if math.hypot(
                position[0] - start[0],
                position[1] - start[1],
            ) > MAX_HORIZONTAL_ERROR_M:
                return "horizontal"
        time.sleep(0.03)
    return "landing_timeout"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Hover High Level en marco global ROBOTAT"
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
                raise RuntimeError("MoCap perdido antes de preparar el vuelo")
            start = flight.get_position()
            assert start is not None
            target = (start[0], start[1], start[2] + args.height)
            print(
                f"Objetivo global: "
                f"x={target[0]:.3f}, y={target[1]:.3f}, z={target[2]:.3f}"
            )
            input("Área despejada. ENTER para volar...")

            telemetry = Telemetry(cf, flight, target)
            telemetry.start()
            threading.Thread(
                target=keyboard_emergency,
                args=(flight,),
                daemon=True,
            ).start()

            commander = cf.high_level_commander
            print(
                f"High Level takeoff hasta z={target[2]:.3f} m "
                f"en {TAKEOFF_DURATION_S:.1f} s..."
            )
            commander.takeoff(
                absolute_height_m=target[2],
                duration_s=TAKEOFF_DURATION_S,
                yaw=0.0,
            )
            flying = True
            result = monitor(
                flight,
                target,
                TAKEOFF_DURATION_S + 0.5,
                grace_s=MOCAP_START_GRACE_S,
            )

            if result is None:
                print("Fijando objetivo High Level...")
                commander.go_to(
                    target[0],
                    target[1],
                    target[2],
                    yaw=0.0,
                    duration_s=GOTO_DURATION_S,
                    relative=False,
                )
                result = monitor(
                    flight,
                    target,
                    args.hover_time,
                )

            if result is None:
                print("Aterrizando High Level...")
                commander.land(
                    absolute_height_m=start[2],
                    duration_s=LAND_DURATION_S,
                    yaw=0.0,
                )
                landing_result = monitor_landing(
                    flight,
                    start,
                    LAND_DURATION_S + 0.5,
                )
                if landing_result is not None:
                    print(f"Advertencia de aterrizaje: {landing_result}")
            elif result == "mocap":
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
