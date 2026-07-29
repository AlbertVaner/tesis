"""Hover diagnóstico con posición ROBOTAT y orientación de la IMU."""

from __future__ import annotations

import argparse
import json
import logging
import math
import msvcrt
import threading
import time

import cflib.crtp
import paho.mqtt.client as mqtt
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.log import LogConfig
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie
from cflib.crazyflie.syncLogger import SyncLogger


URI = "radio://0/84/2M/E7E7E7E7E4"
MQTT_BROKER = "192.168.50.200"
MQTT_PORT = 1880
MQTT_TOPIC = "mocap/drone3"

DEFAULT_HEIGHT_M = 0.2
DEFAULT_HOVER_TIME_S = 5.0
TAKEOFF_TIME_S = 5.0
LAND_TIME_S = 5.0
MOCAP_TIMEOUT_S = 0.75
EXTPOS_RATE_HZ = 20.0
MAX_INITIAL_ERROR_M = 0.08
MAX_HORIZONTAL_OFFSET_M = 0.50
CONTROL_PERIOD_S = 0.05
POSITION_KP_XY = 0.60
POSITION_KP_Z = 0.80
MAX_HORIZONTAL_SPEED_M_S = 0.16
MAX_VERTICAL_SPEED_M_S = 0.10
POSITION_TOLERANCE_M = 0.03
MAX_HEIGHT_OVERSHOOT_M = 0.10
MAX_HORIZONTAL_DEVIATION_M = 0.25


class MocapPosition:
    def __init__(self) -> None:
        self.raw_position: tuple[float, float, float] | None = None
        self.raw_yaw_rad: float | None = None
        self.position: tuple[float, float, float] | None = None
        self.origin: tuple[float, float, float] | None = None
        self.frame_yaw_rad: float | None = None
        self.last_update = 0.0
        self.last_extpos_send = 0.0
        self.cf: Crazyflie | None = None
        self.stop_event = threading.Event()
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_message = self._on_message

    def _on_message(self, _client, _userdata, message) -> None:
        try:
            pose = json.loads(message.payload.decode("utf-8"))["payload"]["pose"]
            p = pose["position"]
            # El puente MQTT de ROBOTAT ya publica estas coordenadas en metros.
            xyz = (float(p["x"]), float(p["y"]), float(p["z"]))
            if not all(math.isfinite(value) for value in xyz):
                raise ValueError("posición no finita")

            rotation = pose.get("rotation", pose.get("orientation"))
            if rotation is None:
                raise KeyError("rotation/orientation")
            qx = float(rotation.get("qx", rotation.get("x")))
            qy = float(rotation.get("qy", rotation.get("y")))
            qz = float(rotation.get("qz", rotation.get("z")))
            qw = float(rotation.get("qw", rotation.get("w")))
            norm = math.sqrt(qx*qx + qy*qy + qz*qz + qw*qw)
            if not math.isfinite(norm) or norm < 1e-6:
                raise ValueError("cuaternión inválido")
            qx, qy, qz, qw = (value / norm for value in (qx, qy, qz, qw))
            yaw = math.atan2(
                2.0 * (qw * qz + qx * qy),
                1.0 - 2.0 * (qy * qy + qz * qz),
            )

            self.raw_position = xyz
            self.raw_yaw_rad = yaw
            # Mantener el marco global de ROBOTAT. Los setpoints de velocidad
            # también son globales; rotar solo la posición cambia el signo o
            # la dirección efectiva de la realimentación horizontal.
            self.position = xyz
            now = time.monotonic()
            self.last_update = now
            if (
                self.cf is not None
                and now - self.last_extpos_send >= 1.0 / EXTPOS_RATE_HZ
            ):
                # Aislamiento intencional: NO se envía orientación externa.
                self.cf.extpos.send_extpos(*xyz)
                self.last_extpos_send = now
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            logging.warning("Mensaje MoCap inválido ignorado")

    def run(self) -> None:
        self.client.connect(MQTT_BROKER, MQTT_PORT, 60)
        self.client.subscribe(MQTT_TOPIC)
        self.client.loop_start()
        self.stop_event.wait()
        self.client.loop_stop()
        self.client.disconnect()

    def fresh(self) -> bool:
        return (
            self.position is not None
            and time.monotonic() - self.last_update <= MOCAP_TIMEOUT_S
        )

    def wait(self, timeout_s=10.0) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.fresh():
                return True
            time.sleep(0.05)
        return False

    def set_local_frame(self) -> None:
        if self.raw_position is None or self.raw_yaw_rad is None:
            raise RuntimeError("pose ROBOTAT no disponible")
        self.origin = self.raw_position
        self.frame_yaw_rad = self.raw_yaw_rad
        self.position = self.raw_position


def configure_kalman(cf: Crazyflie) -> None:
    cf.param.set_value("stabilizer.controller", "1")
    cf.param.set_value("stabilizer.estimator", "2")
    cf.param.set_value("commander.enHighLevel", "0")
    time.sleep(0.5)
    cf.param.set_value("kalman.resetEstimation", "1")
    time.sleep(0.1)
    cf.param.set_value("kalman.resetEstimation", "0")
    time.sleep(0.5)


def wait_for_kalman(scf: SyncCrazyflie, timeout_s=15.0) -> None:
    config = LogConfig(name="KalmanVariance", period_in_ms=100)
    for axis in ("X", "Y", "Z"):
        config.add_variable(f"kalman.varP{axis}", "float")

    history = {axis: [] for axis in ("X", "Y", "Z")}
    deadline = time.monotonic() + timeout_s
    with SyncLogger(scf, config) as logger:
        for _, data, _ in logger:
            for axis in ("X", "Y", "Z"):
                values = history[axis]
                values.append(float(data[f"kalman.varP{axis}"]))
                if len(values) > 10:
                    values.pop(0)
            stable = all(
                len(values) == 10
                and all(math.isfinite(v) for v in values)
                and max(values) - min(values) < 0.001
                for values in history.values()
            )
            if stable:
                print(
                    "Kalman convergió: "
                    + ", ".join(
                        f"varP{a}={history[a][-1]:.6f}" for a in ("X", "Y", "Z")
                    )
                )
                return
            if time.monotonic() >= deadline:
                raise TimeoutError("Kalman no convergió; vuelo cancelado")


def read_estimate(scf: SyncCrazyflie) -> dict[str, float]:
    config = LogConfig(name="InitialEstimate", period_in_ms=100)
    for name in (
        "stateEstimate.x",
        "stateEstimate.y",
        "stateEstimate.z",
        "stateEstimate.roll",
        "stateEstimate.pitch",
        "stateEstimate.yaw",
    ):
        config.add_variable(name)
    with SyncLogger(scf, config) as logger:
        for _, data, _ in logger:
            return {name: float(value) for name, value in data.items()}
    raise RuntimeError("no se pudo leer stateEstimate")


class Telemetry:
    def __init__(self, cf: Crazyflie, target, mocap: MocapPosition) -> None:
        self.cf = cf
        self.target = target
        self.mocap = mocap
        self.configs: list[LogConfig] = []
        self.last_print = 0.0
        self.motors = {"motor.m1": 0, "motor.m2": 0, "motor.m3": 0, "motor.m4": 0}

    def start(self) -> None:
        state_config = LogConfig(name="FlightState", period_in_ms=200)
        for name in ("stateEstimate.x", "stateEstimate.y", "stateEstimate.z"):
            state_config.add_variable(name, "float")

        motor_config = LogConfig(name="FlightMotors", period_in_ms=200)
        for name in ("motor.m1", "motor.m2", "motor.m3", "motor.m4"):
            motor_config.add_variable(name, "uint32_t")

        for config in (state_config, motor_config):
            self.cf.log.add_config(config)
            config.error_cb.add_callback(
                lambda _config, message: print(f"Error telemetría: {message}")
            )
        state_config.data_received_cb.add_callback(self._state_callback)
        motor_config.data_received_cb.add_callback(self._motor_callback)
        state_config.start()
        motor_config.start()
        self.configs = [state_config, motor_config]

    def stop(self) -> None:
        for config in self.configs:
            try:
                config.stop()
            except Exception:
                pass

    def _motor_callback(self, _timestamp, data, _config) -> None:
        self.motors.update(data)

    def _state_callback(self, _timestamp, data, _config) -> None:
        now = time.monotonic()
        if now - self.last_print < 0.5:
            return
        self.last_print = now
        x, y, z = (float(data[f"stateEstimate.{a}"]) for a in ("x", "y", "z"))
        tx, ty, tz = self.target
        mocap_position = self.mocap.position
        if mocap_position is None:
            mocap_text = "MOC no disponible"
            estimate_mocap_text = ""
        else:
            mx, my, mz = mocap_position
            mocap_text = f"MOC x={mx:+.3f} y={my:+.3f} z={mz:+.3f}"
            estimate_mocap_text = (
                f" | EST-MOC=({x-mx:+.3f}, {y-my:+.3f}, {z-mz:+.3f})"
            )
        print(
            f"EST x={x:+.3f} y={y:+.3f} z={z:+.3f} | "
            f"{mocap_text}{estimate_mocap_text} | "
            f"ERR dx={tx-x:+.3f} dy={ty-y:+.3f} dz={tz-z:+.3f} | "
            f"M=[{int(self.motors['motor.m1'])}, "
            f"{int(self.motors['motor.m2'])}, "
            f"{int(self.motors['motor.m3'])}, "
            f"{int(self.motors['motor.m4'])}]"
        )


def stop_motors(cf: Crazyflie) -> None:
    for _ in range(15):
        try:
            cf.commander.send_stop_setpoint()
        except Exception:
            pass
        time.sleep(0.03)


def create_crazyflie() -> Crazyflie:
    """
    Crea el enlace sin el ping de estadísticas de cflib 0.1.28.

    Esa versión puede llenar la cola del RadioDriver y luego intenta hacer
    join() al propio hilo de ping durante la desconexión.
    """
    cf = Crazyflie(rw_cache="./cache")
    cf.link_statistics.start = lambda: None
    cf.link_statistics.stop = lambda: None
    return cf


def keyboard_emergency(event: threading.Event) -> None:
    print("Durante el vuelo: Q = APAGAR MOTORES")
    while not event.is_set():
        if msvcrt.kbhit() and msvcrt.getch().lower() == b"q":
            print("\nPARO DE EMERGENCIA")
            event.set()
            return
        time.sleep(0.02)


def monitor(duration, mocap, emergency, check_mocap=True):
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        if emergency.is_set():
            return "emergency"
        if check_mocap and not mocap.fresh():
            return "mocap"
        time.sleep(0.03)
    return None


def send_position_velocity(cf, mocap, target) -> None:
    """Convierte error de posición en velocidad global limitada."""
    if mocap.position is None:
        raise RuntimeError("posición MoCap no disponible")

    x, y, z = mocap.position
    tx, ty, tz = target
    vx = POSITION_KP_XY * (tx - x)
    vy = POSITION_KP_XY * (ty - y)
    horizontal_speed = math.hypot(vx, vy)
    if horizontal_speed > MAX_HORIZONTAL_SPEED_M_S:
        factor = MAX_HORIZONTAL_SPEED_M_S / horizontal_speed
        vx *= factor
        vy *= factor

    vz = max(
        -MAX_VERTICAL_SPEED_M_S,
        min(MAX_VERTICAL_SPEED_M_S, POSITION_KP_Z * (tz - z)),
    )
    cf.commander.send_velocity_world_setpoint(vx, vy, vz, 0.0)


def lowlevel_takeoff_and_hover(cf, mocap, target, hover_time, emergency):
    print(
        "Despegando low-level "
        f"(vz máx={MAX_VERTICAL_SPEED_M_S:.2f} m/s)..."
    )
    assert mocap.position is not None
    height_change = max(0.0, target[2] - mocap.position[2])
    takeoff_deadline = (
        time.monotonic()
        + height_change / MAX_VERTICAL_SPEED_M_S
        + 5.0
    )

    while True:
        if emergency.is_set():
            return "emergency"
        if not mocap.fresh():
            return "mocap"
        assert mocap.position is not None
        if mocap.position[2] > target[2] + MAX_HEIGHT_OVERSHOOT_M:
            return "overshoot"
        if math.hypot(
            mocap.position[0] - target[0],
            mocap.position[1] - target[1],
        ) > MAX_HORIZONTAL_DEVIATION_M:
            return "horizontal"

        send_position_velocity(cf, mocap, target)
        if mocap.position[2] >= target[2] - POSITION_TOLERANCE_M:
            break
        if time.monotonic() >= takeoff_deadline:
            return "timeout"
        time.sleep(CONTROL_PERIOD_S)

    print(f"Hover durante {hover_time:.1f} s...")
    hover_deadline = time.monotonic() + hover_time
    while time.monotonic() < hover_deadline:
        if emergency.is_set():
            return "emergency"
        if not mocap.fresh():
            return "mocap"
        assert mocap.position is not None
        if mocap.position[2] > target[2] + MAX_HEIGHT_OVERSHOOT_M:
            return "overshoot"
        if math.hypot(
            mocap.position[0] - target[0],
            mocap.position[1] - target[1],
        ) > MAX_HORIZONTAL_DEVIATION_M:
            return "horizontal"
        send_position_velocity(cf, mocap, target)
        time.sleep(CONTROL_PERIOD_S)
    return None


def lowlevel_land(cf, mocap, landing_target, emergency):
    print("Aterrizando low-level...")
    deadline = time.monotonic() + LAND_TIME_S + 3.0
    while time.monotonic() < deadline:
        if emergency.is_set() or not mocap.fresh():
            break
        assert mocap.position is not None
        x, y, z = mocap.position
        if z <= landing_target[2] + 0.04:
            break

        vx = POSITION_KP_XY * (landing_target[0] - x)
        vy = POSITION_KP_XY * (landing_target[1] - y)
        horizontal_speed = math.hypot(vx, vy)
        if horizontal_speed > MAX_HORIZONTAL_SPEED_M_S:
            factor = MAX_HORIZONTAL_SPEED_M_S / horizontal_speed
            vx *= factor
            vy *= factor
        cf.commander.send_velocity_world_setpoint(
            vx, vy, -MAX_VERTICAL_SPEED_M_S, 0.0
        )
        time.sleep(CONTROL_PERIOD_S)

    cf.commander.send_velocity_world_setpoint(0.0, 0.0, 0.0, 0.0)


def parse_args():
    parser = argparse.ArgumentParser(description="Hover con posición ROBOTAT")
    parser.add_argument("--height", type=float, default=DEFAULT_HEIGHT_M)
    parser.add_argument("--hover-time", type=float, default=DEFAULT_HOVER_TIME_S)
    parser.add_argument("--x", type=float)
    parser.add_argument("--y", type=float)
    args = parser.parse_args()
    if not 0.15 <= args.height <= 0.60:
        parser.error("--height debe estar entre 0.15 y 0.60 m")
    if args.hover_time <= 0:
        parser.error("--hover-time debe ser positivo")
    if (args.x is None) != (args.y is None):
        parser.error("--x y --y deben proporcionarse juntos")
    return args


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.ERROR)
    mocap = MocapPosition()
    mqtt_thread = threading.Thread(target=mocap.run, daemon=True)
    mqtt_thread.start()
    emergency = threading.Event()
    link_lost = threading.Event()
    cf: Crazyflie | None = None
    flying = False
    telemetry: Telemetry | None = None

    try:
        print(f"Esperando posición ROBOTAT en {MQTT_TOPIC}...")
        if not mocap.wait():
            raise RuntimeError("no se recibió posición MoCap")
        assert mocap.raw_position is not None
        assert mocap.raw_yaw_rad is not None
        input(
            "Coloca el dron quieto y nivelado. ENTER para fijar el punto inicial..."
        )
        mocap.set_local_frame()
        time.sleep(0.3)
        assert mocap.origin is not None
        assert mocap.frame_yaw_rad is not None
        raw_x, raw_y, raw_z = mocap.origin
        start_x, start_y, start_z = mocap.position
        target_x = start_x if args.x is None else start_x + args.x
        target_y = start_y if args.y is None else start_y + args.y
        target_z = start_z + args.height
        offset = math.hypot(target_x - start_x, target_y - start_y)
        if offset > MAX_HORIZONTAL_OFFSET_M:
            raise ValueError(f"objetivo XY demasiado lejano: {offset:.2f} m")

        print(
            f"ROBOTAT global: x={raw_x:.3f}, y={raw_y:.3f}, z={raw_z:.3f}, "
            f"yaw={math.degrees(mocap.frame_yaw_rad):.1f}°"
        )
        print(
            "Usando marco global ROBOTAT sin rotación ni traslación"
        )
        print(
            f"Objetivo global: x={target_x:.3f}, y={target_y:.3f}, "
            f"z={target_z:.3f}"
        )

        cflib.crtp.init_drivers(enable_debug_driver=False)
        print(f"Conectando a {URI}...")
        with SyncCrazyflie(URI, cf=create_crazyflie()) as scf:
            cf = scf.cf
            def on_disconnected(_uri) -> None:
                if flying:
                    print("\nENLACE CRAZYRADIO PERDIDO")
                mocap.cf = None
                link_lost.set()
                emergency.set()

            cf.disconnected.add_callback(on_disconnected)
            mocap.cf = cf
            configure_kalman(cf)
            print("Esperando convergencia de Kalman...")
            wait_for_kalman(scf)

            state = read_estimate(scf)
            assert mocap.position is not None
            mx, my, mz = mocap.position
            errors = (
                state["stateEstimate.x"] - mx,
                state["stateEstimate.y"] - my,
                state["stateEstimate.z"] - mz,
            )
            print(
                "Estimador: "
                f"x={state['stateEstimate.x']:.3f}, "
                f"y={state['stateEstimate.y']:.3f}, "
                f"z={state['stateEstimate.z']:.3f}, "
                f"roll={state['stateEstimate.roll']:.1f}°, "
                f"pitch={state['stateEstimate.pitch']:.1f}°, "
                f"yaw={state['stateEstimate.yaw']:.1f}°"
            )
            print(
                f"Error Est-MoCap: dx={errors[0]:+.3f}, "
                f"dy={errors[1]:+.3f}, dz={errors[2]:+.3f} m"
            )
            if max(abs(value) for value in errors) > MAX_INITIAL_ERROR_M:
                raise RuntimeError(
                    "stateEstimate no coincide con MoCap; vuelo cancelado"
                )

            input("Área despejada. ENTER para volar...")
            if link_lost.is_set():
                raise RuntimeError(
                    "el enlace Crazyradio se perdió antes del despegue"
                )
            threading.Thread(
                target=keyboard_emergency, args=(emergency,), daemon=True
            ).start()
            telemetry = Telemetry(
                cf, (target_x, target_y, target_z), mocap
            )
            telemetry.start()

            flying = True
            result = lowlevel_takeoff_and_hover(
                cf,
                mocap,
                (target_x, target_y, target_z),
                args.hover_time,
                emergency,
            )

            if result == "emergency":
                print("Cortando motores.")
            elif result == "mocap":
                print("MoCap perdido: cortando motores.")
            elif result == "overshoot":
                print("Altura de seguridad superada: cortando motores.")
            elif result == "timeout":
                print("Timeout de despegue: cortando motores.")
            elif result == "horizontal":
                print("Desviación horizontal excesiva: cortando motores.")
            else:
                print("Hover terminado.")
                lowlevel_land(
                    cf,
                    mocap,
                    (start_x, start_y, start_z),
                    emergency,
                )

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
        emergency.set()
        mocap.cf = None
        mocap.stop_event.set()
        mqtt_thread.join(timeout=1.0)
        print("Prueba finalizada.")


if __name__ == "__main__":
    main()
