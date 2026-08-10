"""Panel de botones para dos Crazyflies con posición externa ROBOTAT.

Seguridad: no envía comandos de vuelo al iniciar. Cada dron necesita conexión,
MoCap fresco y su propio botón DESPEGAR. El botón EMERGENCIA corta ambos.
"""

from __future__ import annotations

import argparse
import json
import math
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox

import cflib.crtp
import paho.mqtt.client as mqtt
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.log import LogConfig
from dual_flight_logger import DualFlightLogger


BROKER = "192.168.50.200"
PORT = 1880
DEFAULT_URI_1 = "radio://0/84/2M/E7E7E7E7E4"
DEFAULT_URI_2 = "radio://0/84/2M/E7E7E7E7E5"
DEFAULT_TOPIC_1 = "mocap/drone3"
DEFAULT_TOPIC_2 = "mocap/drone4"
MOCAP_TIMEOUT_S = 0.75
HOVER_OFFSET_M = 0.50
TAKEOFF_DURATION_S = 8.0  # 0.50 m en 8 s: despegue suave
GOTO_DURATION_XY_S = 3.0
GOTO_DURATION_Z_S = 4.0
STEP_XY_M = 0.10
STEP_Z_M = 0.08
MIN_Z_M, MAX_Z_M = 0.20, 1.10
MIN_SEPARATION_M = 0.50


@dataclass
class Pose:
    x: float
    y: float
    z: float
    received_at: float


class DroneUnit:
    def __init__(self, name: str, uri: str, topic: str) -> None:
        self.name, self.uri, self.topic = name, uri, topic
        self.lock = threading.RLock()
        self.pose: Pose | None = None
        self.estimate: Pose | None = None
        self.mocap_hz = 0.0
        self.mocap_interval_s = 0.0
        self.target: list[float] | None = None
        self.cf: Crazyflie | None = None
        self.connected = False
        self.ready = False
        self.airborne = False
        self.status = "Desconectado"
        self._mqtt: mqtt.Client | None = None
        self._state_log: LogConfig | None = None

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
        if self._mqtt is not None:
            self._mqtt.loop_stop()
            self._mqtt.disconnect()
            self._mqtt = None

    def _on_mocap(self, _client, _userdata, message) -> None:
        try:
            data = json.loads(message.payload.decode("utf-8"))
            position = data["payload"]["pose"]["position"]
            xyz = (float(position["x"]), float(position["y"]), float(position["z"]))
            if not all(math.isfinite(value) for value in xyz):
                return
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return
        with self.lock:
            previous = self.pose
            now = time.monotonic()
            if previous is not None:
                interval = now - previous.received_at
                if 0.0 < interval < 2.0:
                    self.mocap_interval_s = interval
                    self.mocap_hz = 1.0 / interval
            self.pose = Pose(*xyz, received_at=now)
            cf = self.cf
        if cf is not None:
            try:
                # ROBOTAT ya entrega metros y el marco global.
                cf.extpos.send_extpos(*xyz)
            except Exception:
                pass

    def fresh_pose(self) -> Pose | None:
        with self.lock:
            if self.pose is None or time.monotonic() - self.pose.received_at > MOCAP_TIMEOUT_S:
                return None
            return self.pose

    def connect(self) -> None:
        with self.lock:
            if self.cf is not None:
                return
            self.status = "Conectando…"
            self.cf = Crazyflie(rw_cache="./cache")
            self.cf.connected.add_callback(self._connected)
            self.cf.connection_failed.add_callback(self._failed)
            self.cf.connection_lost.add_callback(self._lost)
            self.cf.open_link(self.uri)

    def _connected(self, _uri: str) -> None:
        with self.lock:
            self.connected = True
            self.status = "Configurando EKF…"
            cf = self.cf
        if cf is None:
            return
        threading.Thread(target=self._configure, args=(cf,), daemon=True).start()

    def _configure(self, cf: Crazyflie) -> None:
        try:
            # No se inicializa el EKF hasta que ROBOTAT esté llegando. De otro
            # modo el indicador de la aeronave puede cambiar de estado, pero el
            # controlador no tiene una referencia de posición válida.
            with self.lock:
                self.status = f"Esperando MoCap en {self.topic}…"
            deadline = time.monotonic() + 12.0
            while time.monotonic() < deadline and self.fresh_pose() is None:
                time.sleep(0.05)
            if self.fresh_pose() is None:
                with self.lock:
                    self.status = f"Sin MoCap en {self.topic}"
                return

            cf.param.set_value("commander.enHighLevel", "1")
            cf.param.set_value("stabilizer.controller", "1")
            cf.param.set_value("stabilizer.estimator", "2")
            cf.param.set_value("kalman.resetEstimation", "1")
            time.sleep(0.1)
            cf.param.set_value("kalman.resetEstimation", "0")
            self._start_state_log(cf)
            for remaining in range(4, 0, -1):
                if self.fresh_pose() is None:
                    with self.lock:
                        self.status = "MoCap perdido durante estabilización"
                    return
                with self.lock:
                    self.status = f"Estabilizando EKF… {remaining} s"
                time.sleep(1.0)
            with self.lock:
                self.ready = True
                self.status = "Listo" if self.fresh_pose() else "MoCap perdido; no listo"
        except Exception as exc:
            with self.lock:
                self.status = f"Error configurando: {exc}"

    def _start_state_log(self, cf: Crazyflie) -> None:
        config = LogConfig(name=f"EKF_{self.name}", period_in_ms=100)
        for axis in ("x", "y", "z"):
            config.add_variable(f"stateEstimate.{axis}", "float")
        cf.log.add_config(config)
        config.data_received_cb.add_callback(self._on_ekf)
        config.start()
        self._state_log = config

    def _on_ekf(self, _timestamp, data, _logconf) -> None:
        try:
            estimate = Pose(
                float(data["stateEstimate.x"]), float(data["stateEstimate.y"]),
                float(data["stateEstimate.z"]), time.monotonic(),
            )
            with self.lock:
                self.estimate = estimate
        except (KeyError, TypeError, ValueError):
            pass

    def _failed(self, _uri: str, message: str) -> None:
        with self.lock:
            self.cf = None
            self.connected = self.ready = False
            self.status = f"Falló enlace: {message}"

    def _lost(self, _uri: str, message: str) -> None:
        with self.lock:
            self.connected = self.ready = self.airborne = False
            self.status = f"Enlace cerrado: {message}"

    def takeoff(self) -> tuple[bool, str]:
        pose = self.fresh_pose()
        with self.lock:
            if not self.ready or self.cf is None:
                return False, "Aún no está listo"
            if pose is None:
                return False, "No hay MoCap fresco"
            if self.airborne:
                return False, "Ya está en vuelo"
            self.target = [pose.x, pose.y, min(pose.z + HOVER_OFFSET_M, MAX_Z_M)]
            cf = self.cf
            target_z = self.target[2]
            self.airborne = True
            self.status = f"Despegando a {target_z:.2f} m"
        try:
            cf.high_level_commander.takeoff(target_z, TAKEOFF_DURATION_S)
            threading.Timer(TAKEOFF_DURATION_S, self._hold_target).start()
            return True, ""
        except Exception as exc:
            with self.lock:
                self.airborne = False
            return False, str(exc)

    def _hold_target(self) -> None:
        with self.lock:
            if not self.airborne or self.cf is None or self.target is None:
                return
            cf, target = self.cf, list(self.target)
            self.status = "Hover"
        try:
            cf.high_level_commander.go_to(*target, 0.0, GOTO_DURATION_XY_S, relative=False)
        except Exception:
            pass

    def move(self, dx: float, dy: float, dz: float) -> tuple[bool, str]:
        with self.lock:
            if not self.airborne or self.cf is None or self.target is None:
                return False, "Primero despega ese dron"
            self.target[0] += dx
            self.target[1] += dy
            self.target[2] = max(MIN_Z_M, min(MAX_Z_M, self.target[2] + dz))
            cf, target = self.cf, list(self.target)
            self.status = f"Objetivo: ({target[0]:.2f}, {target[1]:.2f}, {target[2]:.2f})"
        try:
            duration = GOTO_DURATION_Z_S if dz else GOTO_DURATION_XY_S
            cf.high_level_commander.go_to(*target, 0.0, duration, relative=False)
            return True, ""
        except Exception as exc:
            return False, str(exc)

    def land(self) -> None:
        with self.lock:
            cf = self.cf
            if cf is None or not self.airborne:
                return
            self.status = "Aterrizando…"
        try:
            cf.high_level_commander.land(0.0, 4.0)
        except Exception:
            pass
        with self.lock:
            self.airborne = False

    def emergency(self) -> None:
        with self.lock:
            cf = self.cf
            self.airborne = False
            self.status = "EMERGENCIA"
        if cf is not None:
            try:
                cf.high_level_commander.stop()
                for _ in range(10):
                    cf.commander.send_stop_setpoint()
                    time.sleep(0.03)
                cf.close_link()
            except Exception:
                pass


class App(tk.Tk):
    def __init__(self, first: DroneUnit, second: DroneUnit) -> None:
        super().__init__()
        self.title("Control seguro — dos Crazyflies")
        self.geometry("780x570")
        self.first, self.second = first, second
        self.logger = DualFlightLogger()
        self.selected = tk.StringVar(value=first.name)
        self.status = tk.StringVar(value="Conecta los drones y verifica MoCap antes de despegar.")
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(150, self.refresh)

    def _build(self) -> None:
        tk.Label(self, text="CONTROL DE DOS DRONES", font=("Segoe UI", 18, "bold")).pack(pady=(14, 3))
        tk.Label(self, text="High Level + ROBOTAT · No despega automáticamente", fg="#356b35").pack()
        top = tk.Frame(self)
        top.pack(pady=15)
        tk.Button(top, text="CONECTAR AMBOS", width=22, command=self.connect_both).grid(row=0, column=0, padx=6)
        tk.Button(top, text="DESPEGAR AMBOS", width=22, bg="#398a31", fg="white", command=self.takeoff_both).grid(row=0, column=1, padx=6)
        tk.Button(top, text="EMERGENCIA — AMBOS", width=24, bg="#b72f2a", fg="white", command=self.emergency).grid(row=0, column=2, padx=6)

        cards = tk.Frame(self)
        cards.pack(fill="x", padx=24)
        for column, unit in enumerate((self.first, self.second)):
            frame = tk.LabelFrame(cards, text=f" {unit.name} ", padx=12, pady=10)
            frame.grid(row=0, column=column, padx=8, sticky="nsew")
            cards.grid_columnconfigure(column, weight=1)
            tk.Radiobutton(frame, text="Controlar este dron", variable=self.selected, value=unit.name).pack(anchor="w")
            tk.Label(frame, text=f"URI: {unit.uri}", wraplength=310, justify="left").pack(anchor="w", pady=4)
            tk.Label(frame, text=f"MoCap: {unit.topic}").pack(anchor="w")
            tk.Button(frame, text="DESPEGAR 0.50 m", width=20, bg="#398a31", fg="white", command=lambda u=unit: self.takeoff(u)).pack(pady=(10, 4))
            tk.Button(frame, text="ATERRIZAR", width=20, command=unit.land).pack()

        tk.Label(self, text="Movimiento del dron seleccionado (pasos de 10 cm / 8 cm)", font=("Segoe UI", 11, "bold")).pack(pady=(22, 5))
        move = tk.Frame(self)
        move.pack()
        button = lambda label, x, y, dx, dy, dz: tk.Button(move, text=label, width=14, height=2, command=lambda: self.move(dx, dy, dz)).grid(row=x, column=y, padx=4, pady=4)
        button("↑ ADELANTE", 0, 1, STEP_XY_M, 0, 0)
        button("← IZQUIERDA", 1, 0, 0, STEP_XY_M, 0)
        button("HOVER", 1, 1, 0, 0, 0)
        button("DERECHA →", 1, 2, 0, -STEP_XY_M, 0)
        button("↓ ATRÁS", 2, 1, -STEP_XY_M, 0, 0)
        button("SUBIR", 0, 3, 0, 0, STEP_Z_M)
        button("BAJAR", 2, 3, 0, 0, -STEP_Z_M)
        tk.Label(self, textvariable=self.status, wraplength=730, justify="center").pack(pady=16)

    def connect_both(self) -> None:
        try:
            if not self.logger.active:
                path = self.logger.start()
                self.logger.event("SISTEMA", "INICIO_SESION")
                print(f"Log CSV: {path}")
            self.first.start_mocap()
            self.second.start_mocap()
            self.first.connect()
            self.second.connect()
            self.status.set("Conectando ambos y esperando estabilización del EKF…")
        except Exception as exc:
            self.status.set(f"Error conectando: {exc}")

    def selected_unit(self) -> DroneUnit:
        return self.first if self.selected.get() == self.first.name else self.second

    def takeoff(self, unit: DroneUnit) -> None:
        ok, message = unit.takeoff()
        if not ok:
            messagebox.showwarning(unit.name, message)
        else:
            self.logger.event(unit.name, "DESPEGUE", unit.status)

    def takeoff_both(self) -> None:
        """Ordena los dos takeoff sin esperar a que termine el primero."""
        pose1, pose2 = self.first.fresh_pose(), self.second.fresh_pose()
        if pose1 is None or pose2 is None:
            messagebox.showwarning("Despegue bloqueado", "Ambos drones necesitan MoCap fresco.")
            return
        not_ready = []
        for unit in (self.first, self.second):
            with unit.lock:
                if not unit.ready or unit.cf is None or unit.airborne:
                    not_ready.append(f"{unit.name}: {unit.status}")
        if not_ready:
            messagebox.showwarning("Despegue bloqueado", "Ambos drones deben estar Listo.\n" + "\n".join(not_ready))
            return
        if math.dist((pose1.x, pose1.y, pose1.z), (pose2.x, pose2.y, pose2.z)) < MIN_SEPARATION_M:
            messagebox.showwarning("Despegue bloqueado", f"Separa los drones al menos {MIN_SEPARATION_M:.2f} m antes de despegar.")
            return
        first_ok, first_message = self.first.takeoff()
        second_ok, second_message = self.second.takeoff()
        if first_ok:
            self.logger.event(self.first.name, "DESPEGUE_CONJUNTO", self.first.status)
        if second_ok:
            self.logger.event(self.second.name, "DESPEGUE_CONJUNTO", self.second.status)
        if not first_ok or not second_ok:
            problems = []
            if not first_ok:
                problems.append(f"Dron 1: {first_message}")
            if not second_ok:
                problems.append(f"Dron 2: {second_message}")
            messagebox.showwarning("Despegue conjunto bloqueado", "\n".join(problems))

    def move(self, dx: float, dy: float, dz: float) -> None:
        unit = self.selected_unit()
        other = self.second if unit is self.first else self.first
        with unit.lock:
            candidate = None if unit.target is None else (unit.target[0] + dx, unit.target[1] + dy, unit.target[2] + dz)
        other_pose = other.fresh_pose()
        if candidate and other_pose and math.dist(candidate, (other_pose.x, other_pose.y, other_pose.z)) < MIN_SEPARATION_M:
            messagebox.showwarning("Movimiento bloqueado", f"Mantén al menos {MIN_SEPARATION_M:.2f} m de separación del otro dron.")
            return
        ok, message = unit.move(dx, dy, dz)
        if not ok:
            messagebox.showwarning(unit.name, message)
        else:
            self.logger.event(unit.name, f"MOVER dx={dx:+.2f}, dy={dy:+.2f}, dz={dz:+.2f}", unit.status)

    def emergency(self) -> None:
        # Un paro de emergencia no debe requerir una segunda interacción.
        self.logger.event("SISTEMA", "EMERGENCIA")
        self.first.emergency()
        self.second.emergency()
        self.logger.stop()
        self.status.set("EMERGENCIA enviada. Reinicia el programa antes de reconectar.")

    def refresh(self) -> None:
        parts = []
        for unit in (self.first, self.second):
            pose = unit.fresh_pose()
            pos = "sin MoCap" if pose is None else f"({pose.x:+.2f}, {pose.y:+.2f}, {pose.z:+.2f})"
            with unit.lock:
                parts.append(f"{unit.name}: {unit.status} · {pos}")
        if not self.status.get().startswith(("Error", "EMERGENCIA")):
            self.status.set("\n".join(parts))
        self.logger.sample(self.first)
        self.logger.sample(self.second)
        self.after(150, self.refresh)

    def close(self) -> None:
        self.logger.event("SISTEMA", "CIERRE_SESION")
        self.first.land()
        self.second.land()
        self.first.stop_mocap()
        self.second.stop_mocap()
        path = self.logger.stop()
        if path is not None:
            print(f"Log guardado: {path}")
        self.destroy()


def main() -> None:
    parser = argparse.ArgumentParser(description="Control por botones de dos Crazyflies")
    parser.add_argument("--uri1", default=DEFAULT_URI_1)
    parser.add_argument("--uri2", default=DEFAULT_URI_2)
    parser.add_argument("--topic1", default=DEFAULT_TOPIC_1)
    parser.add_argument("--topic2", default=DEFAULT_TOPIC_2)
    args = parser.parse_args()
    cflib.crtp.init_drivers(enable_debug_driver=False)
    App(DroneUnit("Dron 1", args.uri1, args.topic1), DroneUnit("Dron 2", args.uri2, args.topic2)).mainloop()


if __name__ == "__main__":
    main()
