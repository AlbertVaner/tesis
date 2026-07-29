import json
import time
import threading
import math
import csv
import os
from datetime import datetime
import tkinter as tk
from tkinter import messagebox

import matplotlib.pyplot as plt
import paho.mqtt.client as mqtt

import cflib.crtp
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie
from cflib.crazyflie.log import LogConfig


# =======================================================
# CONFIGURACIÓN CRAZYFLIE / MOCAP
# =======================================================

URI = "radio://0/84/2M/E7E7E7E7E4"

MQTT_TOPIC = "mocap/drone3"
MQTT_BROKER = "192.168.50.200"
PORT = 1880


# =======================================================
# CONFIGURACIÓN DE VUELO
# =======================================================

HOVER_HEIGHT = 0.20
TAKEOFF_TIME = 3.0
LAND_TIME = 3.0
EMERGENCY_LAND_TIME = 1.5

CONTROL_PERIOD_S = 0.05
POSITION_KP_XY = 0.60
POSITION_KP_Z = 0.80
MAX_HORIZONTAL_SPEED = 0.16
MAX_VERTICAL_SPEED = 0.10
LANDING_SPEED = 0.10
POSITION_TOLERANCE = 0.05
MOCAP_TIMEOUT_S = 0.75

STEP_XY = 0.06
STEP_Z = 0.05
MOVE_DURATION = 1.20

YAW_STEP_DEG = 15.0
YAW_STEP_RAD = math.radians(YAW_STEP_DEG)

RETURN_HOME_DURATION = 2.0

MAX_X_OFFSET_CMD = 0.80
MAX_Y_OFFSET_CMD = 0.80
MIN_HEIGHT_CMD = 0.20
MAX_HEIGHT_CMD = 0.90


# =======================================================
# CONFIGURACIÓN DE GUARDADO CSV
# =======================================================

CSV_FOLDER = "datos_vuelo_crazyflie"


# =======================================================
# LÍMITES DE SEGURIDAD ABSOLUTOS DEL MOCAP
# =======================================================

X_MIN_LIMIT = -1.17
X_MAX_LIMIT = 1.17

Y_MIN_LIMIT = -1.50
Y_MAX_LIMIT = 1.50

Z_MAX_LIMIT = 1.60


# =======================================================
# VARIABLES GLOBALES
# =======================================================

mocap_pose = {
    "x": None,
    "y": None,
    "z": None
}

battery_data = {
    "vbat": None,
    "level": None
}

cf_global = None
last_ts = None
last_mocap_update = 0.0
stop_mqtt_event = threading.Event()


# =======================================================
# DATOS PARA GRAFICAR Y GUARDAR CSV
# =======================================================

recording_active = False
t0_log = None
data_lock = threading.Lock()

real_time_data = []
real_x_data = []
real_y_data = []
real_z_data = []
real_battery_v_data = []
real_battery_level_data = []

target_time_data = []
target_x_data = []
target_y_data = []
target_z_data = []
target_yaw_data = []
target_battery_v_data = []
target_battery_level_data = []


# =======================================================
# CALLBACK MQTT
# =======================================================

def on_message(client, userdata, msg):
    global mocap_pose, cf_global, last_ts, last_mocap_update
    global recording_active, t0_log

    try:
        data = json.loads(msg.payload.decode())

        pos = data["payload"]["pose"]["position"]
        ts_str = data.get("ts", None)

        if ts_str is not None:
            msg_time = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))

            # Aceptar timestamps iguales: ROBOTAT puede publicar varios
            # frames dentro de la misma marca temporal.
            if last_ts is not None and msg_time < last_ts:
                return

            last_ts = msg_time

        # El puente MQTT de ROBOTAT ya publica estas coordenadas en metros.
        x = float(pos["x"])
        y = float(pos["y"])
        z = float(pos["z"])

        mocap_pose["x"] = x
        mocap_pose["y"] = y
        mocap_pose["z"] = z
        last_mocap_update = time.monotonic()

        # Guardar trayectoria real medida por MoCap
        if recording_active and t0_log is not None:
            with data_lock:
                t = time.time() - t0_log
                real_time_data.append(t)
                real_x_data.append(x)
                real_y_data.append(y)
                real_z_data.append(z)
                real_battery_v_data.append(battery_data["vbat"])
                real_battery_level_data.append(battery_data["level"])

        # Enviar posición externa al EKF del Crazyflie
        if cf_global is not None:
            cf_global.extpos.send_extpos(x, y, z)

    except Exception as e:
        print("Error en MQTT:", e)
        print("Mensaje recibido:", msg.payload.decode())


# =======================================================
# MQTT
# =======================================================

def start_mqtt():
    client = mqtt.Client()
    client.on_message = on_message

    client.connect(MQTT_BROKER, PORT, 60)
    client.subscribe(MQTT_TOPIC)

    print(f"MQTT conectado. Escuchando tópico: {MQTT_TOPIC}")

    while not stop_mqtt_event.is_set():
        client.loop(timeout=0.1)

    client.disconnect()
    print("MQTT desconectado.")


# =======================================================
# ESPERAR MOCAP
# =======================================================

def wait_for_mocap_position(timeout=10.0):
    print("Esperando posición inicial del MoCap...")

    start = time.time()

    while time.time() - start < timeout:
        if (
            mocap_pose["x"] is not None and
            mocap_pose["y"] is not None and
            mocap_pose["z"] is not None
        ):
            print(
                "Posición inicial detectada: "
                f"x={mocap_pose['x']:.3f}, "
                f"y={mocap_pose['y']:.3f}, "
                f"z={mocap_pose['z']:.3f}"
            )
            return True

        time.sleep(0.05)

    print("ERROR: No llegó posición válida del MoCap.")
    return False


# =======================================================
# CONFIGURAR CRAZYFLIE
# =======================================================

def setup_crazyflie_for_mocap(cf):
    print("Configurando Crazyflie para MoCap...")

    cf.param.set_value("stabilizer.controller", "1")
    cf.param.set_value("stabilizer.estimator", "2")
    cf.param.set_value("commander.enHighLevel", "0")

    time.sleep(0.5)

    print("Reiniciando estimador Kalman...")
    cf.param.set_value("kalman.resetEstimation", "1")
    time.sleep(0.1)
    cf.param.set_value("kalman.resetEstimation", "0")

    time.sleep(3.0)
    print("Estimador listo.")


# =======================================================
# BATERÍA
# =======================================================

class BatteryLogger:
    def __init__(self, cf):
        self.cf = cf
        self.log_config = None

    def start(self):
        try:
            self.log_config = LogConfig(name="Battery", period_in_ms=1000)

            self.log_config.add_variable("pm.vbat", "float")
            self.log_config.add_variable("pm.batteryLevel", "uint8_t")

            self.cf.log.add_config(self.log_config)

            self.log_config.data_received_cb.add_callback(self._battery_callback)
            self.log_config.error_cb.add_callback(self._battery_error)

            self.log_config.start()
            print("Logger de batería iniciado.")

        except Exception as e:
            print("No se pudo iniciar el logger de batería:", e)

    def stop(self):
        try:
            if self.log_config is not None:
                self.log_config.stop()
                print("Logger de batería detenido.")
        except Exception as e:
            print("Error deteniendo logger de batería:", e)

    def _battery_callback(self, timestamp, data, logconf):
        battery_data["vbat"] = data.get("pm.vbat", None)
        battery_data["level"] = data.get("pm.batteryLevel", None)

    def _battery_error(self, logconf, msg):
        print("Error en logger de batería:", msg)


# =======================================================
# REGISTRO DE DATOS Y CSV
# =======================================================

def start_recording():
    global recording_active, t0_log
    global real_time_data, real_x_data, real_y_data, real_z_data
    global real_battery_v_data, real_battery_level_data
    global target_time_data, target_x_data, target_y_data, target_z_data, target_yaw_data
    global target_battery_v_data, target_battery_level_data

    with data_lock:
        real_time_data = []
        real_x_data = []
        real_y_data = []
        real_z_data = []
        real_battery_v_data = []
        real_battery_level_data = []

        target_time_data = []
        target_x_data = []
        target_y_data = []
        target_z_data = []
        target_yaw_data = []
        target_battery_v_data = []
        target_battery_level_data = []

        t0_log = time.time()
        recording_active = True

    print("Registro de datos iniciado.")


def stop_recording(save_csv=True):
    global recording_active

    was_recording = recording_active

    with data_lock:
        recording_active = False

    print("Registro de datos detenido.")

    if save_csv and was_recording:
        filename = save_recorded_data_to_csv()
        if filename is not None:
            print(f"CSV guardado en: {filename}")
            return filename

    return None


def log_target(x, y, z, yaw):
    if recording_active and t0_log is not None:
        with data_lock:
            t = time.time() - t0_log
            target_time_data.append(t)
            target_x_data.append(x)
            target_y_data.append(y)
            target_z_data.append(z)
            target_yaw_data.append(math.degrees(yaw))
            target_battery_v_data.append(battery_data["vbat"])
            target_battery_level_data.append(battery_data["level"])


def save_recorded_data_to_csv():
    with data_lock:
        rt = list(real_time_data)
        rx = list(real_x_data)
        ry = list(real_y_data)
        rz = list(real_z_data)
        rbv = list(real_battery_v_data)
        rbl = list(real_battery_level_data)

        tt = list(target_time_data)
        tx = list(target_x_data)
        ty = list(target_y_data)
        tz = list(target_z_data)
        tyaw = list(target_yaw_data)
        tbv = list(target_battery_v_data)
        tbl = list(target_battery_level_data)

    if len(rt) == 0 and len(tt) == 0:
        print("No hay datos para guardar en CSV.")
        return None

    os.makedirs(CSV_FOLDER, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(CSV_FOLDER, f"vuelo_crazyflie_{timestamp}.csv")

    with open(filename, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)

        writer.writerow([
            "tipo",
            "tiempo_s",
            "x_m",
            "y_m",
            "z_m",
            "yaw_deg",
            "bateria_v",
            "bateria_porcentaje"
        ])

        for i in range(len(rt)):
            writer.writerow([
                "real_mocap",
                rt[i],
                rx[i],
                ry[i],
                rz[i],
                "",
                rbv[i],
                rbl[i]
            ])

        for i in range(len(tt)):
            writer.writerow([
                "objetivo_enviado",
                tt[i],
                tx[i],
                ty[i],
                tz[i],
                tyaw[i],
                tbv[i],
                tbl[i]
            ])

    return filename


# =======================================================
# PANEL DE CONTROL
# =======================================================

class DroneControlPanel:
    def __init__(self, root, cf):
        self.root = root
        self.cf = cf
        self.commander = cf.high_level_commander

        self.x0 = None
        self.y0 = None
        self.z0 = None

        self.target_x = None
        self.target_y = None
        self.target_z = None
        self.target_yaw = 0.0

        self.has_taken_off = False
        self.is_landing = False
        self.lock = threading.Lock()
        self.control_stop_event = threading.Event()
        self.mocap_fault_triggered = False
        self.control_thread = threading.Thread(
            target=self._position_control_loop,
            daemon=True
        )
        self.control_thread.start()

        self.root.title("Panel de control Crazyflie - MoCap")
        self.root.geometry("820x940")
        self.root.resizable(False, False)

        self.create_widgets()
        self.set_movement_buttons_state("disabled")
        self.update_labels()
        self.check_safety_limits()

    def _mocap_is_fresh(self):
        return (
            last_mocap_update > 0.0
            and time.monotonic() - last_mocap_update <= MOCAP_TIMEOUT_S
        )

    def _position_control_loop(self):
        """Control P de posición a 20 Hz con velocidades en marco global."""
        while not self.control_stop_event.is_set():
            if self.has_taken_off and not self.is_landing:
                if not self._mocap_is_fresh():
                    if not self.mocap_fault_triggered:
                        self.mocap_fault_triggered = True
                        self.emergency_motor_cut(
                            "MOCAP PERDIDO: motores apagados"
                        )
                    break

                with self.lock:
                    targets = (
                        self.target_x,
                        self.target_y,
                        self.target_z,
                    )

                if all(value is not None for value in targets):
                    ex = targets[0] - mocap_pose["x"]
                    ey = targets[1] - mocap_pose["y"]
                    ez = targets[2] - mocap_pose["z"]

                    vx = POSITION_KP_XY * ex
                    vy = POSITION_KP_XY * ey
                    horizontal_speed = math.hypot(vx, vy)
                    if horizontal_speed > MAX_HORIZONTAL_SPEED:
                        factor = MAX_HORIZONTAL_SPEED / horizontal_speed
                        vx *= factor
                        vy *= factor

                    vz = max(
                        -MAX_VERTICAL_SPEED,
                        min(MAX_VERTICAL_SPEED, POSITION_KP_Z * ez)
                    )
                    self.cf.commander.send_velocity_world_setpoint(
                        float(vx), float(vy), float(vz), 0.0
                    )

            time.sleep(CONTROL_PERIOD_S)

    def create_widgets(self):
        title = tk.Label(
            self.root,
            text="Panel de control Crazyflie",
            font=("Arial", 16, "bold")
        )
        title.pack(pady=10)

        info = tk.Label(
            self.root,
            text=(
                "Primero presiona INICIAR HOVER. "
                f"El dron despegará a {HOVER_HEIGHT:.2f} m."
            ),
            font=("Arial", 10)
        )
        info.pack(pady=5)

        self.pose_label = tk.Label(
            self.root,
            text="MoCap: esperando...",
            font=("Consolas", 10)
        )
        self.pose_label.pack(pady=5)

        self.target_label = tk.Label(
            self.root,
            text="Target: no iniciado",
            font=("Consolas", 10)
        )
        self.target_label.pack(pady=5)

        self.battery_label = tk.Label(
            self.root,
            text="Batería: esperando...",
            font=("Consolas", 11, "bold")
        )
        self.battery_label.pack(pady=5)

        self.safety_label = tk.Label(
            self.root,
            text="Seguridad: esperando hover",
            font=("Arial", 10, "bold"),
            fg="blue"
        )
        self.safety_label.pack(pady=5)

        self.start_hover_button = tk.Button(
            self.root,
            text="INICIAR HOVER",
            width=28,
            height=2,
            bg="green",
            fg="white",
            font=("Arial", 12, "bold"),
            command=self.start_hover
        )
        self.start_hover_button.pack(pady=10)

        self.record_button = tk.Button(
            self.root,
            text="INICIAR GRABACIÓN",
            width=28,
            height=2,
            bg="purple",
            fg="white",
            font=("Arial", 11, "bold"),
            command=self.toggle_recording
        )
        self.record_button.pack(pady=8)

        frame = tk.Frame(self.root)
        frame.pack(pady=10)

        self.btn_up = tk.Button(
            frame,
            text="↑ Arriba",
            width=14,
            height=2,
            command=lambda: self.move_drone(0.0, 0.0, STEP_Z)
        )
        self.btn_up.grid(row=0, column=1, padx=5, pady=5)

        self.btn_forward = tk.Button(
            frame,
            text="Frente",
            width=14,
            height=2,
            command=lambda: self.move_drone(STEP_XY, 0.0, 0.0)
        )
        self.btn_forward.grid(row=1, column=1, padx=5, pady=5)

        self.btn_left = tk.Button(
            frame,
            text="← Izquierda",
            width=14,
            height=2,
            command=lambda: self.move_drone(0.0, -STEP_XY, 0.0)
        )
        self.btn_left.grid(row=2, column=0, padx=5, pady=5)

        self.btn_hover = tk.Button(
            frame,
            text="Mantener",
            width=14,
            height=2,
            command=self.hold_position
        )
        self.btn_hover.grid(row=2, column=1, padx=5, pady=5)

        self.btn_right = tk.Button(
            frame,
            text="Derecha →",
            width=14,
            height=2,
            command=lambda: self.move_drone(0.0, STEP_XY, 0.0)
        )
        self.btn_right.grid(row=2, column=2, padx=5, pady=5)

        self.btn_back = tk.Button(
            frame,
            text="Atrás",
            width=14,
            height=2,
            command=lambda: self.move_drone(-STEP_XY, 0.0, 0.0)
        )
        self.btn_back.grid(row=3, column=1, padx=5, pady=5)

        self.btn_down = tk.Button(
            frame,
            text="↓ Abajo",
            width=14,
            height=2,
            command=lambda: self.move_drone(0.0, 0.0, -STEP_Z)
        )
        self.btn_down.grid(row=4, column=1, padx=5, pady=5)

        self.btn_yaw_left = tk.Button(
            frame,
            text="↺ Rotar izq.",
            width=14,
            height=2,
            command=lambda: self.rotate_drone(YAW_STEP_RAD)
        )
        self.btn_yaw_left.grid(row=5, column=0, padx=5, pady=5)

        self.btn_home = tk.Button(
            frame,
            text="🏠 Centro",
            width=14,
            height=2,
            bg="lightblue",
            fg="black",
            font=("Arial", 10, "bold"),
            command=self.return_home
        )
        self.btn_home.grid(row=5, column=1, padx=5, pady=5)

        self.btn_yaw_right = tk.Button(
            frame,
            text="Rotar der. ↻",
            width=14,
            height=2,
            command=lambda: self.rotate_drone(-YAW_STEP_RAD)
        )
        self.btn_yaw_right.grid(row=5, column=2, padx=5, pady=5)

        buttons_frame = tk.Frame(self.root)
        buttons_frame.pack(pady=20)

        self.land_button = tk.Button(
            buttons_frame,
            text="ATERRIZAR",
            width=24,
            height=2,
            bg="orange",
            fg="black",
            font=("Arial", 12, "bold"),
            command=self.land_drone
        )
        self.land_button.grid(row=0, column=0, padx=15, pady=10)

        self.emergency_button = tk.Button(
            buttons_frame,
            text="PARO: MOTORES OFF",
            width=24,
            height=2,
            bg="red",
            fg="white",
            font=("Arial", 12, "bold"),
            command=self.emergency_land
        )
        self.emergency_button.grid(row=0, column=1, padx=15, pady=10)

        note = tk.Label(
            self.root,
            text=(
                "Auto-paro de motores si: "
                "x fuera de [-1.17, 1.17] m, "
                "y fuera de [-1.50, 1.50] m, "
                "o z > 1.60 m."
            ),
            font=("Arial", 9)
        )
        note.pack(pady=5)

        axes_note = tk.Label(
            self.root,
            text=(
                "Ejes actuales: Frente=+X, Atrás=-X, Derecha=+Y, Izquierda=-Y.\n"
                "Yaw: si gira al lado contrario, cambia los signos en los botones de rotación."
            ),
            font=("Arial", 8)
        )
        axes_note.pack(pady=2)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def set_movement_buttons_state(self, state):
        buttons = [
            self.record_button,
            self.btn_up,
            self.btn_down,
            self.btn_left,
            self.btn_right,
            self.btn_forward,
            self.btn_back,
            self.btn_hover,
            self.btn_yaw_left,
            self.btn_yaw_right,
            self.btn_home,
            self.land_button
        ]

        for btn in buttons:
            btn.config(state=state)

        self.emergency_button.config(state="normal")

    def disable_all_buttons(self):
        buttons = [
            self.start_hover_button,
            self.record_button,
            self.btn_up,
            self.btn_down,
            self.btn_left,
            self.btn_right,
            self.btn_forward,
            self.btn_back,
            self.btn_hover,
            self.btn_yaw_left,
            self.btn_yaw_right,
            self.btn_home,
            self.land_button,
            self.emergency_button
        ]

        for btn in buttons:
            try:
                btn.config(state="disabled")
            except Exception:
                pass

    def toggle_recording(self):
        global recording_active

        if not self.has_taken_off:
            messagebox.showwarning(
                "Grabación no iniciada",
                "Primero inicia el hover antes de grabar."
            )
            return

        if not recording_active:
            start_recording()

            self.record_button.config(
                text="DETENER Y GUARDAR CSV",
                bg="darkred",
                fg="white"
            )

            print("Grabación activada desde el panel.")

        else:
            filename = stop_recording(save_csv=True)

            self.record_button.config(
                text="INICIAR GRABACIÓN",
                bg="purple",
                fg="white"
            )

            if filename is not None:
                messagebox.showinfo(
                    "CSV guardado",
                    f"Datos guardados correctamente en:\n{filename}"
                )
            else:
                messagebox.showwarning(
                    "Sin datos",
                    "No se grabaron datos suficientes para guardar."
                )

    def start_hover(self):
        if self.has_taken_off or self.is_landing:
            return

        threading.Thread(target=self._start_hover_sequence, daemon=True).start()

    def _start_hover_sequence(self):
        if not wait_for_mocap_position(timeout=10.0):
            messagebox.showerror(
                "Error",
                "No hay datos válidos de MoCap. No se despega."
            )
            return

        try:
            self.start_hover_button.config(state="disabled", text="DESPEGANDO...")

            self.x0 = mocap_pose["x"]
            self.y0 = mocap_pose["y"]
            self.z0 = mocap_pose["z"]

            self.target_x = self.x0
            self.target_y = self.y0
            self.target_z = self.z0 + HOVER_HEIGHT
            self.target_yaw = 0.0

            print(
                "Punto inicial de hover: "
                f"x0={self.x0:.3f}, y0={self.y0:.3f}, z0={self.z0:.3f}"
            )

            print(
                f"Despegando low-level a {HOVER_HEIGHT:.2f} m "
                f"(vz máx={MAX_VERTICAL_SPEED:.2f} m/s)..."
            )
            self.has_taken_off = True
            self.mocap_fault_triggered = False

            deadline = time.monotonic() + (
                HOVER_HEIGHT / MAX_VERTICAL_SPEED + 5.0
            )
            while (
                not self.is_landing
                and mocap_pose["z"] < self.target_z - POSITION_TOLERANCE
            ):
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        "No se alcanzó la altura de hover a tiempo"
                    )
                time.sleep(CONTROL_PERIOD_S)

            if self.is_landing:
                return

            self.safety_label.config(
                text="Seguridad: hover activo",
                fg="green"
            )

            self.start_hover_button.config(
                text="HOVER ACTIVO",
                bg="gray",
                fg="white",
                state="disabled"
            )

            self.set_movement_buttons_state("normal")

            print("Hover iniciado. Controles habilitados.")

        except Exception as e:
            print("Error iniciando hover:", e)
            messagebox.showerror("Error", f"No se pudo iniciar hover:\n{e}")

            self.emergency_motor_cut(
                "FALLO DURANTE DESPEGUE: motores apagados"
            )

            if recording_active:
                stop_recording(save_csv=True)

    def clamp_targets(self):
        if self.x0 is None or self.y0 is None or self.z0 is None:
            return

        self.target_x = max(
            self.x0 - MAX_X_OFFSET_CMD,
            min(self.x0 + MAX_X_OFFSET_CMD, self.target_x)
        )

        self.target_y = max(
            self.y0 - MAX_Y_OFFSET_CMD,
            min(self.y0 + MAX_Y_OFFSET_CMD, self.target_y)
        )

        min_z = self.z0 + MIN_HEIGHT_CMD
        max_z = self.z0 + MAX_HEIGHT_CMD

        self.target_z = max(
            min_z,
            min(max_z, self.target_z)
        )

    def send_goto(self):
        if not self.has_taken_off:
            print("El dron aún no está en hover.")
            return

        log_target(
            self.target_x,
            self.target_y,
            self.target_z,
            self.target_yaw
        )

    def move_drone(self, dx, dy, dz):
        if self.is_landing or not self.has_taken_off:
            return

        with self.lock:
            self.target_x += dx
            self.target_y += dy
            self.target_z += dz

            self.clamp_targets()

            print(
                f"Nuevo target: "
                f"x={self.target_x:.3f}, "
                f"y={self.target_y:.3f}, "
                f"z={self.target_z:.3f}, "
                f"yaw={math.degrees(self.target_yaw):.1f}°"
            )

            self.send_goto()

    def rotate_drone(self, dyaw):
        if self.is_landing or not self.has_taken_off:
            return

        print(
            "Rotación deshabilitada temporalmente en modo low-level."
        )

    def return_home(self):
        if self.is_landing or not self.has_taken_off:
            return

        with self.lock:
            self.target_x = self.x0
            self.target_y = self.y0
            self.target_z = self.z0 + HOVER_HEIGHT
            self.target_yaw = 0.0

            print(
                "Regresando al centro: "
                f"x={self.target_x:.3f}, "
                f"y={self.target_y:.3f}, "
                f"z={self.target_z:.3f}, "
                f"yaw={math.degrees(self.target_yaw):.1f}°"
            )

            self.send_goto()

    def hold_position(self):
        if self.is_landing or not self.has_taken_off:
            return

        with self.lock:
            print("Manteniendo posición objetivo.")
            self.send_goto()

    def land_drone(self):
        if not self.has_taken_off:
            print("El dron no ha despegado. Cerrando panel.")
            self.root.destroy()
            return

        threading.Thread(
            target=self._land_sequence,
            args=(LAND_TIME, "Aterrizaje normal"),
            daemon=True
        ).start()

    def emergency_land(self):
        threading.Thread(
            target=self.emergency_motor_cut,
            args=("PARO DE EMERGENCIA: motores apagados directamente",),
            daemon=True
        ).start()

    def auto_land_due_to_limits(self):
        threading.Thread(
            target=self.emergency_motor_cut,
            args=("LÍMITE SUPERADO: motores apagados automáticamente",),
            daemon=True
        ).start()

    def emergency_motor_cut(self, reason="Paro de emergencia: motores apagados"):
        """
        Apaga motores directamente.
        El Crazyflie caerá. Usar solo en emergencia real.
        """
        if self.is_landing:
            return

        self.is_landing = True
        self.control_stop_event.set()
        self.disable_all_buttons()

        print(reason)

        try:
            self.safety_label.config(text=reason, fg="red")
        except Exception:
            pass

        try:
            # Cortar motores directamente
            for _ in range(15):
                self.cf.commander.send_stop_setpoint()
                time.sleep(0.05)

            print("Motores apagados directamente.")

        except Exception as e:
            print("Error apagando motores:", e)

        finally:
            if recording_active:
                stop_recording(save_csv=True)

            try:
                self.root.destroy()
            except Exception:
                pass

    def _land_sequence(self, duration, reason):
        if self.is_landing:
            return

        self.is_landing = True
        self.control_stop_event.set()
        self.disable_all_buttons()

        print(reason)

        try:
            self.safety_label.config(text=reason, fg="red")
        except Exception:
            pass

        try:
            if self.has_taken_off:
                print("Aterrizando low-level...")
                deadline = time.monotonic() + max(
                    duration,
                    (
                        max(0.0, mocap_pose["z"] - self.z0)
                        / LANDING_SPEED
                    ) + 2.0
                )
                while (
                    self._mocap_is_fresh()
                    and mocap_pose["z"] > self.z0 + 0.04
                    and time.monotonic() < deadline
                ):
                    self.cf.commander.send_velocity_world_setpoint(
                        0.0, 0.0, -LANDING_SPEED, 0.0
                    )
                    time.sleep(CONTROL_PERIOD_S)

                self.cf.commander.send_velocity_world_setpoint(
                    0.0, 0.0, 0.0, 0.0
                )
                for _ in range(15):
                    self.cf.commander.send_stop_setpoint()
                    time.sleep(0.03)
                print("Aterrizaje completado.")
            else:
                print("Emergencia presionada antes del despegue. No había vuelo activo.")

        except Exception as e:
            print("Error durante aterrizaje:", e)

        finally:
            if recording_active:
                stop_recording(save_csv=True)

            try:
                self.root.destroy()
            except Exception:
                pass

    def check_safety_limits(self):
        if self.is_landing:
            return

        if not self.has_taken_off:
            self.safety_label.config(
                text="Seguridad: esperando hover",
                fg="blue"
            )
            self.root.after(100, self.check_safety_limits)
            return

        if (
            mocap_pose["x"] is not None and
            mocap_pose["y"] is not None and
            mocap_pose["z"] is not None
        ):
            x = mocap_pose["x"]
            y = mocap_pose["y"]
            z = mocap_pose["z"]

            limit_exceeded = (
                x < X_MIN_LIMIT or
                x > X_MAX_LIMIT or
                y < Y_MIN_LIMIT or
                y > Y_MAX_LIMIT or
                z > Z_MAX_LIMIT
            )

            if limit_exceeded:
                print(
                    "LÍMITE DE SEGURIDAD SUPERADO: "
                    f"x={x:.3f}, y={y:.3f}, z={z:.3f}"
                )

                self.safety_label.config(
                    text=(
                        "Seguridad: LÍMITE SUPERADO "
                        f"x={x:.2f}, y={y:.2f}, z={z:.2f}"
                    ),
                    fg="red"
                )

                self.auto_land_due_to_limits()
                return

            else:
                self.safety_label.config(
                    text=(
                        "Seguridad: dentro de límites | "
                        f"x={x:.2f}, y={y:.2f}, z={z:.2f}"
                    ),
                    fg="green"
                )

        self.root.after(100, self.check_safety_limits)

    def on_close(self):
        if self.is_landing:
            return

        if self.has_taken_off:
            if messagebox.askyesno(
                "Cerrar panel",
                "El dron está volando. ¿Quieres aterrizar antes de cerrar?"
            ):
                self.land_drone()
        else:
            self.root.destroy()

    def update_labels(self):
        if (
            mocap_pose["x"] is not None and
            mocap_pose["y"] is not None and
            mocap_pose["z"] is not None
        ):
            self.pose_label.config(
                text=(
                    f"MoCap actual: "
                    f"x={mocap_pose['x']:.3f} m | "
                    f"y={mocap_pose['y']:.3f} m | "
                    f"z={mocap_pose['z']:.3f} m"
                )
            )

        if self.target_x is not None:
            self.target_label.config(
                text=(
                    f"Target: "
                    f"x={self.target_x:.3f} m | "
                    f"y={self.target_y:.3f} m | "
                    f"z={self.target_z:.3f} m | "
                    f"yaw={math.degrees(self.target_yaw):.1f}°"
                )
            )
        else:
            self.target_label.config(text="Target: no iniciado")

        vbat = battery_data["vbat"]
        level = battery_data["level"]

        if vbat is not None and level is not None:
            self.battery_label.config(
                text=f"Batería: {vbat:.2f} V | {level}%"
            )
        elif vbat is not None:
            self.battery_label.config(
                text=f"Batería: {vbat:.2f} V"
            )
        else:
            self.battery_label.config(
                text="Batería: esperando datos..."
            )

        if not self.is_landing:
            self.root.after(150, self.update_labels)


# =======================================================
# GRAFICAR RESULTADOS
# =======================================================

def plot_flight_results():
    with data_lock:
        if len(real_time_data) < 2:
            print("No hay suficientes datos reales para graficar.")
            return

        rt = list(real_time_data)
        rx = list(real_x_data)
        ry = list(real_y_data)
        rz = list(real_z_data)

        tt = list(target_time_data)
        tx = list(target_x_data)
        ty = list(target_y_data)
        tz = list(target_z_data)
        tyaw = list(target_yaw_data)

    print("Generando gráficas del vuelo...")

    fig = plt.figure(figsize=(8, 6))
    ax = fig.add_subplot(111, projection="3d")

    ax.plot(rx, ry, rz, label="Trayectoria real MoCap")
    ax.scatter(rx[0], ry[0], rz[0], marker="o", s=70, label="Inicio")
    ax.scatter(rx[-1], ry[-1], rz[-1], marker="x", s=90, label="Final")

    ax.set_xlabel("X [m]")
    ax.set_ylabel("Y [m]")
    ax.set_zlabel("Z [m]")
    ax.set_title("Trayectoria 3D real del Crazyflie")
    ax.legend()
    ax.grid(True)

    plt.figure(figsize=(8, 6))
    plt.plot(rx, ry, label="Trayectoria real MoCap")

    if len(tx) > 0:
        plt.plot(tx, ty, "--", label="Objetivos enviados")

    plt.scatter(rx[0], ry[0], marker="o", s=70, label="Inicio real")
    plt.scatter(rx[-1], ry[-1], marker="x", s=90, label="Final real")

    plt.xlabel("X [m]")
    plt.ylabel("Y [m]")
    plt.title("Trayectoria X-Y: real vs objetivos")
    plt.axis("equal")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()

    plt.figure(figsize=(10, 5))
    plt.plot(rt, rx, label="X real [m]")
    plt.plot(rt, ry, label="Y real [m]")
    plt.plot(rt, rz, label="Z real [m]")

    if len(tt) > 0:
        plt.plot(tt, tx, "--", label="X objetivo [m]")
        plt.plot(tt, ty, "--", label="Y objetivo [m]")
        plt.plot(tt, tz, "--", label="Z objetivo [m]")

    plt.xlabel("Tiempo [s]")
    plt.ylabel("Posición [m]")
    plt.title("Posición real y objetivo vs tiempo")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()

    if len(tt) > 0:
        plt.figure(figsize=(9, 4))
        plt.plot(tt, tyaw, label="Yaw objetivo [°]")
        plt.xlabel("Tiempo [s]")
        plt.ylabel("Yaw [grados]")
        plt.title("Yaw objetivo enviado al Crazyflie")
        plt.grid(True)
        plt.legend()
        plt.tight_layout()

    plt.show()


# =======================================================
# ABRIR PANEL SIN DESPEGAR
# =======================================================

def open_panel(cf):
    print("Abriendo panel de control. El dron NO despegará hasta presionar INICIAR HOVER.")

    root = tk.Tk()
    app = DroneControlPanel(root, cf)
    root.mainloop()


# =======================================================
# MAIN
# =======================================================

def main():
    global cf_global

    cflib.crtp.init_drivers()

    mqtt_thread = threading.Thread(target=start_mqtt, daemon=True)
    mqtt_thread.start()

    time.sleep(1.0)

    print("Conectando al Crazyflie...")

    battery_logger = None

    try:
        with SyncCrazyflie(URI, cf=Crazyflie(rw_cache="./cache")) as scf:
            cf_global = scf.cf
            print("Conectado correctamente.")

            setup_crazyflie_for_mocap(cf_global)

            battery_logger = BatteryLogger(cf_global)
            battery_logger.start()

            open_panel(cf_global)

    except Exception as e:
        print("Error general:", e)

    finally:
        if battery_logger is not None:
            battery_logger.stop()

        cf_global = None
        stop_mqtt_event.set()
        mqtt_thread.join(timeout=1.0)

        plot_flight_results()

        print("Programa terminado.")


if __name__ == "__main__":
    main()
