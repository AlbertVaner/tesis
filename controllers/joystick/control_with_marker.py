"""Control low-level del Crazyflie con inclinación y altura de un marker ROBOTAT.

Primero ejecute marker_orientation_check.py y confirme el tópico y los signos.
"""

from __future__ import annotations

import argparse
import math
import sys
import threading
import time
import tkinter as tk
from pathlib import Path

import cflib.crtp
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie

from flight_logger import MarkerFlightLogger
from marker_mocap import MocapReceiver, Pose

PROJECT_DIR = Path(__file__).resolve().parents[2]
SHARED_DIR = PROJECT_DIR / "controllers" / "shared"
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))
from gui_pdf_capture import auto_save_gui_pdf, install_gui_pdf_capture


# --- Ajustar solamente estas constantes después de la prueba sin hélices. ---
DEFAULT_URI = "radio://0/84/2M/E7E7E7E7E4"
DEFAULT_DRONE_TOPIC = "mocap/drone3"
DEFAULT_MARKER_TOPIC = "mocap/all"
DEFAULT_MARKER_ID = 64
MQTT_BROKER = "192.168.50.200"
MQTT_PORT = 1880

CONTROL_PERIOD_S = 0.05
MOCAP_TIMEOUT_S = 0.75
HOVER_HEIGHT_M = 0.50
MIN_HEIGHT_M = 0.25
MAX_HEIGHT_M = 1.10
MAX_VERTICAL_SPEED_M_S = 0.15
MAX_HORIZONTAL_SPEED_M_S = 0.12
VERTICAL_KP = 0.55
MAX_RADIUS_M = 0.65

# Zona muerta amplia: el marker debe inclinarse de forma deliberada.
TILT_DEADZONE_DEG = 12.0
TILT_FULL_SPEED_DEG = 28.0
VERTICAL_DEADZONE_M = 0.08
LAND_MARKER_BELOW_M = -0.10
LAND_HOLD_S = 0.50
MARKER_LOSS_LAND_S = 1.00

# Si la prueba visual muestra una dirección invertida, cambiar solo a -1.0.
PITCH_TO_X_SIGN = 1.0
ROLL_TO_Y_SIGN = 1.0


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def angle_delta_deg(now: float, reference: float) -> float:
    """Diferencia angular en [-180, 180], segura al cruzar ±180°."""
    return (now - reference + 180.0) % 360.0 - 180.0


def tilt_to_speed(angle_deg: float) -> float:
    """Zona muerta amplia y rampa suave desde 12° hasta 28°."""
    magnitude = abs(angle_deg)
    if magnitude <= TILT_DEADZONE_DEG:
        return 0.0
    ramp = (magnitude - TILT_DEADZONE_DEG) / (TILT_FULL_SPEED_DEG - TILT_DEADZONE_DEG)
    return math.copysign(MAX_HORIZONTAL_SPEED_M_S * clamp(ramp, 0.0, 1.0), angle_deg)


class MarkerFlightApp:
    def __init__(self, cf: Crazyflie, drone_rx: MocapReceiver, marker_rx: MocapReceiver) -> None:
        self.cf = cf
        self.drone_rx = drone_rx
        self.marker_rx = marker_rx
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.has_taken_off = False
        self.is_landing = False
        self.zero: Pose | None = None
        self.launch_pose: Pose | None = None
        self.target_z: float | None = None
        self.status = "Listo: establezca cero del marker"
        self.land_below_since: float | None = None
        self.marker_lost_since: float | None = None
        self.logger = MarkerFlightLogger()
        self.last_command = {
            "state": "NEUTRO", "marker_dz": 0.0, "roll_rel": 0.0,
            "pitch_rel": 0.0, "target_z": 0.0, "vx": 0.0, "vy": 0.0, "vz": 0.0,
        }

        self.root = tk.Tk()
        self.root.title("Crazyflie · Control por marker ROBOTAT")
        self.root.geometry("780x620")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._create_widgets()
        install_gui_pdf_capture(self.root, "gui_control_marker")

        self.control_thread = threading.Thread(target=self._control_loop, daemon=True)
        self.control_thread.start()
        self._refresh_ui()

    def _create_widgets(self) -> None:
        tk.Label(self.root, text="Control del dron con marker ROBOTAT", font=("Arial", 18, "bold")).pack(pady=(16, 4))
        tk.Label(self.root, text=(
            "Zona muerta: ±12° · Máx. horizontal: 0.12 m/s · "
            "Aterriza si el marker baja más de 10 cm"
        ), fg="#52615a").pack()
        self.status_label = tk.Label(self.root, text="", font=("Arial", 11, "bold"), fg="#146c43")
        self.status_label.pack(pady=12)
        self.drone_label = tk.Label(self.root, text="Dron: esperando MoCap", justify="left", font=("Consolas", 12))
        self.drone_label.pack(pady=8)
        self.marker_label = tk.Label(self.root, text="Marker: esperando MoCap", justify="left", font=("Consolas", 12))
        self.marker_label.pack(pady=8)
        self.command_label = tk.Label(self.root, text="Comandos: sin cero", justify="left", font=("Consolas", 12), fg="#063970")
        self.command_label.pack(pady=12)

        actions = tk.Frame(self.root)
        actions.pack(pady=14)
        self.zero_button = tk.Button(actions, text="1. ESTABLECER CERO", command=self.set_zero, bg="#1f7a35", fg="white", width=22, height=2, font=("Arial", 11, "bold"))
        self.zero_button.grid(row=0, column=0, padx=8, pady=8)
        self.takeoff_button = tk.Button(actions, text="2. DESPEGAR · 0.50 m", command=self.takeoff, bg="#217eae", fg="white", width=22, height=2, font=("Arial", 11, "bold"))
        self.takeoff_button.grid(row=0, column=1, padx=8, pady=8)
        self.land_button = tk.Button(actions, text="ATERRIZAR", command=self.land, bg="#e68a00", fg="black", width=22, height=2, font=("Arial", 11, "bold"))
        self.land_button.grid(row=1, column=0, padx=8, pady=8)
        self.emergency_button = tk.Button(actions, text="PARO DE EMERGENCIA", command=lambda: self.emergency_stop("Paro manual"), bg="#bd3d36", fg="white", width=22, height=2, font=("Arial", 11, "bold"))
        self.emergency_button.grid(row=1, column=1, padx=8, pady=8)
        tk.Label(self.root, text=(
            "Antes de despegar: marker nivelado, cero establecido y ambos MoCap en verde.\n"
            "Si el sentido X/Y está invertido, edite PITCH_TO_X_SIGN o ROLL_TO_Y_SIGN."
        ), fg="#52615a", justify="center").pack(pady=10)

    @staticmethod
    def _pose_text(name: str, pose: Pose | None) -> str:
        if pose is None:
            return f"{name}: sin datos"
        return (
            f"{name}: X={pose.x:+.3f}  Y={pose.y:+.3f}  Z={pose.z:+.3f} m"
            f"\n        Roll={pose.roll_deg:+.1f}°  Pitch={pose.pitch_deg:+.1f}°  Yaw={pose.yaw_deg:+.1f}°  edad={pose.age_s:.2f} s"
        )

    def _fresh(self, receiver: MocapReceiver) -> Pose | None:
        pose = receiver.snapshot()
        return pose if pose is not None and pose.age_s <= MOCAP_TIMEOUT_S else None

    def set_zero(self) -> None:
        marker = self._fresh(self.marker_rx)
        if marker is None:
            self.status = "No se pudo establecer cero: marker sin señal reciente"
            return
        if self.has_taken_off:
            self.status = "No se puede cambiar el cero durante el vuelo"
            return
        self.zero = marker
        path = self.logger.start()
        self.logger.event("CERO_ESTABLECIDO")
        self.status = f"Cero establecido. Registro: {path.name}"

    def takeoff(self) -> None:
        marker = self._fresh(self.marker_rx)
        drone = self._fresh(self.drone_rx)
        if self.zero is None:
            self.status = "Primero presione ESTABLECER CERO"
            return
        if marker is None or drone is None:
            self.status = "No despega: falta MoCap reciente del marker o dron"
            return
        if self.has_taken_off or self.is_landing:
            return
        self.launch_pose = drone
        self.target_z = drone.z + HOVER_HEIGHT_M
        self.has_taken_off = True
        self.land_below_since = None
        self.marker_lost_since = None
        self.logger.event("DESPEGUE_SOLICITADO")
        self.status = f"Despegando a {HOVER_HEIGHT_M:.2f} m. Control del marker activo."

    def land(self) -> None:
        if not self.has_taken_off or self.is_landing:
            return
        threading.Thread(target=self._land_worker, args=("Aterrizaje solicitado",), daemon=True).start()

    def _land_worker(self, reason: str) -> None:
        with self.lock:
            if self.is_landing:
                return
            self.is_landing = True
            self.status = reason
            self.logger.event(reason.upper())
        floor_z = self.launch_pose.z if self.launch_pose is not None else -math.inf
        deadline = time.monotonic() + 12.0
        try:
            while time.monotonic() < deadline:
                drone = self._fresh(self.drone_rx)
                if drone is None or drone.z <= floor_z + 0.04:
                    break
                self.cf.commander.send_velocity_world_setpoint(0.0, 0.0, -0.10, 0.0)
                time.sleep(CONTROL_PERIOD_S)
        finally:
            self._stop_motors()
            with self.lock:
                self.has_taken_off = False
                self.is_landing = False
                self.target_z = None
                self.zero = None
                csv_path = self.logger.stop()
                self.status = f"Aterrizado. CSV guardado: {csv_path.name if csv_path else 'sin registro'}"

    def emergency_stop(self, reason: str) -> None:
        with self.lock:
            if self.is_landing:
                return
            self.is_landing = True
            self.has_taken_off = False
            self.status = f"EMERGENCIA: {reason}. Motores apagados."
            self.logger.event(f"EMERGENCIA_{reason.upper()}")
        self._stop_motors()
        self.logger.stop()

    def _stop_motors(self) -> None:
        try:
            self.cf.commander.send_velocity_world_setpoint(0.0, 0.0, 0.0, 0.0)
            for _ in range(15):
                self.cf.commander.send_stop_setpoint()
                time.sleep(0.03)
        except Exception as exc:
            self.status = f"Error al apagar motores: {exc}"

    def _control_loop(self) -> None:
        while not self.stop_event.is_set():
            drone = self._fresh(self.drone_rx)
            marker = self._fresh(self.marker_rx)
            if drone is not None:
                try:
                    self.cf.extpos.send_extpos(drone.x, drone.y, drone.z)
                except Exception:
                    pass

            if self.has_taken_off and not self.is_landing:
                if drone is None:
                    self.emergency_stop("MoCap del dron perdido")
                elif marker is None:
                    if self.marker_lost_since is None:
                        self.marker_lost_since = time.monotonic()
                        self.status = "Marker perdido: manteniendo hover antes de aterrizar"
                    elif time.monotonic() - self.marker_lost_since >= MARKER_LOSS_LAND_S:
                        self.land()
                else:
                    self.marker_lost_since = None
                    self._send_marker_command(drone, marker)
            if self.logger.active:
                self.logger.sample(marker, drone, self.zero, self.launch_pose, self.last_command)
            time.sleep(CONTROL_PERIOD_S)

    def _send_marker_command(self, drone: Pose, marker: Pose) -> None:
        assert self.zero is not None and self.launch_pose is not None
        roll = angle_delta_deg(marker.roll_deg, self.zero.roll_deg)
        pitch = angle_delta_deg(marker.pitch_deg, self.zero.pitch_deg)
        marker_dz = marker.z - self.zero.z

        if marker_dz < LAND_MARKER_BELOW_M:
            if self.land_below_since is None:
                self.land_below_since = time.monotonic()
                self.status = "Marker abajo: confirme 0.5 s para aterrizar"
            elif time.monotonic() - self.land_below_since >= LAND_HOLD_S:
                self.land()
                return
        else:
            self.land_below_since = None

        usable_dz = 0.0 if abs(marker_dz) <= VERTICAL_DEADZONE_M else marker_dz
        self.target_z = clamp(
            self.launch_pose.z + HOVER_HEIGHT_M + usable_dz,
            self.launch_pose.z + MIN_HEIGHT_M,
            self.launch_pose.z + MAX_HEIGHT_M,
        )
        vx = PITCH_TO_X_SIGN * tilt_to_speed(pitch)
        vy = ROLL_TO_Y_SIGN * tilt_to_speed(roll)
        radius = math.hypot(drone.x - self.launch_pose.x, drone.y - self.launch_pose.y)
        if radius >= MAX_RADIUS_M and (drone.x - self.launch_pose.x) * vx + (drone.y - self.launch_pose.y) * vy > 0:
            vx = vy = 0.0
            self.status = "Límite horizontal alcanzado: vuelva el marker a nivel"
        else:
            self.status = "Control marker activo"
        vz = clamp(VERTICAL_KP * (self.target_z - drone.z), -MAX_VERTICAL_SPEED_M_S, MAX_VERTICAL_SPEED_M_S)
        horizontal = []
        if vx > 0.001:
            horizontal.append("ADELANTE")
        elif vx < -0.001:
            horizontal.append("ATRÁS")
        if vy > 0.001:
            horizontal.append("DERECHA")
        elif vy < -0.001:
            horizontal.append("IZQUIERDA")
        if marker_dz > VERTICAL_DEADZONE_M:
            horizontal.append("SUBIR")
        elif marker_dz < LAND_MARKER_BELOW_M:
            horizontal.append("ATERRIZAR")
        elif marker_dz < -VERTICAL_DEADZONE_M:
            horizontal.append("BAJAR")
        self.last_command = {
            "state": " + ".join(horizontal) if horizontal else "NEUTRO",
            "marker_dz": marker_dz,
            "roll_rel": roll,
            "pitch_rel": pitch,
            "target_z": self.target_z,
            "vx": vx,
            "vy": vy,
            "vz": vz,
        }
        self.cf.commander.send_velocity_world_setpoint(vx, vy, vz, 0.0)

    def _refresh_ui(self) -> None:
        drone = self.drone_rx.snapshot()
        marker = self.marker_rx.snapshot()
        self.drone_label.config(text=self._pose_text("Dron", drone))
        self.marker_label.config(text=self._pose_text("Marker", marker))
        color = "#146c43" if self._fresh(self.drone_rx) and self._fresh(self.marker_rx) else "#b3261e"
        self.status_label.config(text=self.status, fg=color if "EMERGENCIA" not in self.status else "#b3261e")
        if self.zero is not None and marker is not None:
            roll = angle_delta_deg(marker.roll_deg, self.zero.roll_deg)
            pitch = angle_delta_deg(marker.pitch_deg, self.zero.pitch_deg)
            dz = marker.z - self.zero.z
            self.command_label.config(text=(
                f"Relativo al cero: ΔZ={dz:+.3f} m · ΔRoll={roll:+.1f}° · ΔPitch={pitch:+.1f}°\n"
                f"Comando actual: VX={PITCH_TO_X_SIGN*tilt_to_speed(pitch):+.2f}  VY={ROLL_TO_Y_SIGN*tilt_to_speed(roll):+.2f} m/s"
            ))
        else:
            self.command_label.config(text="Comandos: establezca el cero con el marker nivelado")
        if not self.stop_event.is_set():
            self.root.after(100, self._refresh_ui)

    def close(self) -> None:
        auto_save_gui_pdf(self.root)
        if self.has_taken_off and not self.is_landing:
            self.emergency_stop("Ventana cerrada")
        self.stop_event.set()
        self.logger.stop()
        self.drone_rx.stop()
        self.marker_rx.stop()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def configure_for_mocap(cf: Crazyflie) -> None:
    cf.param.set_value("stabilizer.controller", "1")
    cf.param.set_value("stabilizer.estimator", "2")
    cf.param.set_value("commander.enHighLevel", "0")
    time.sleep(0.4)
    cf.param.set_value("kalman.resetEstimation", "1")
    time.sleep(0.1)
    cf.param.set_value("kalman.resetEstimation", "0")
    time.sleep(3.0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Control Crazyflie con marker ROBOTAT")
    parser.add_argument("--uri", default=DEFAULT_URI)
    parser.add_argument("--drone-topic", default=DEFAULT_DRONE_TOPIC)
    parser.add_argument("--marker-topic", default=DEFAULT_MARKER_TOPIC)
    parser.add_argument("--marker-id", type=int, default=DEFAULT_MARKER_ID)
    args = parser.parse_args()

    drone_rx = MocapReceiver(args.drone_topic, MQTT_BROKER, MQTT_PORT)
    marker_rx = MocapReceiver(
        args.marker_topic,
        MQTT_BROKER,
        MQTT_PORT,
        required_identifier=args.marker_id,
    )
    drone_rx.start()
    marker_rx.start()
    cflib.crtp.init_drivers(enable_debug_driver=False)
    try:
        print(f"Conectando al Crazyflie {args.uri}...")
        with SyncCrazyflie(args.uri, cf=Crazyflie(rw_cache=str(Path("cache")))) as scf:
            print("Conectado. Configurando EKF y MoCap...")
            configure_for_mocap(scf.cf)
            MarkerFlightApp(scf.cf, drone_rx, marker_rx).run()
    except Exception as exc:
        print(f"Error general: {exc}")
    finally:
        drone_rx.stop()
        marker_rx.stop()


if __name__ == "__main__":
    main()
