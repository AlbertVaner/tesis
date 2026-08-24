"""Panel de control basado en el vuelo low-level funcional de referencia."""

from __future__ import annotations

import math
import threading
import time

import cflib.crtp
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie

import control as dc
from control_highlevel_global import DiagnosticCsvLogger


# Parámetros copiados de flight_purepursuit.py y conservadores para gestos.
HOVER_HEIGHT_M = 0.3
CONTROL_PERIOD_S = 0.05
TAKEOFF_SPEED_M_S = 0.10
KP_XY = 0.60
KP_Z = 0.40
MAX_XY_SPEED_M_S = 0.10
MAX_Z_SPEED_M_S = 0.15
TAKEOFF_TOLERANCE_M = 0.05
MAX_HORIZONTAL_ERROR_M = 0.30
MOCAP_TIMEOUT_S = 0.75

# La interfaz heredada toma estas constantes del módulo control.
dc.HOVER_HEIGHT = HOVER_HEIGHT_M
dc.STEP_XY = 0.05
dc.STEP_Z = 0.05


def configure_lowlevel_global(cf) -> None:
    print("Configurando control low-level con MoCap global...")
    cf.param.set_value("commander.enHighLevel", "0")
    cf.param.set_value("stabilizer.controller", "1")
    cf.param.set_value("stabilizer.estimator", "2")
    cf.param.set_value("kalman.resetEstimation", "1")
    time.sleep(0.1)
    cf.param.set_value("kalman.resetEstimation", "0")
    print("Esperando estabilización del EKF (5 s)...")
    time.sleep(5.0)


class CompanionLowLevelPanel(dc.DroneControlPanel):
    """Panel original con la arquitectura global/low-level del compañero."""

    def _mocap_is_fresh(self):
        return (
            dc.last_mocap_update > 0.0
            and time.monotonic() - dc.last_mocap_update <= MOCAP_TIMEOUT_S
        )

    def _position_control_loop(self):
        while not self.control_stop_event.is_set():
            if self.has_taken_off and not self.is_landing:
                if not self._mocap_is_fresh():
                    self.emergency_motor_cut("MOCAP PERDIDO: motores apagados")
                    return

                with self.lock:
                    target = (self.target_x, self.target_y, self.target_z)
                    mode = getattr(self, "flight_mode", "hover")

                if all(value is not None for value in target):
                    ex = target[0] - dc.mocap_pose["x"]
                    ey = target[1] - dc.mocap_pose["y"]
                    ez = target[2] - dc.mocap_pose["z"]
                    if math.hypot(ex, ey) > MAX_HORIZONTAL_ERROR_M:
                        self.emergency_motor_cut(
                            "DESVIACIÓN HORIZONTAL EXCESIVA: motores apagados"
                        )
                        return

                    vx = KP_XY * ex
                    vy = KP_XY * ey
                    speed = math.hypot(vx, vy)
                    if speed > MAX_XY_SPEED_M_S:
                        scale = MAX_XY_SPEED_M_S / speed
                        vx *= scale
                        vy *= scale

                    if mode == "takeoff":
                        vz = TAKEOFF_SPEED_M_S
                    else:
                        vz = max(
                            -MAX_Z_SPEED_M_S,
                            min(MAX_Z_SPEED_M_S, KP_Z * ez),
                        )
                    self.cf.commander.send_velocity_world_setpoint(
                        float(vx), float(vy), float(vz), 0.0
                    )
            time.sleep(CONTROL_PERIOD_S)

    def _start_hover_sequence(self):
        if not dc.wait_for_mocap_position(timeout=10.0):
            dc.messagebox.showerror("Error", "No hay datos válidos de MoCap.")
            return
        if not self._mocap_is_fresh():
            dc.messagebox.showerror("Error", "MoCap no está actualizado.")
            return

        self.start_hover_button.config(state="disabled", text="DESPEGANDO...")
        self.x0 = dc.mocap_pose["x"]
        self.y0 = dc.mocap_pose["y"]
        self.z0 = dc.mocap_pose["z"]
        self.target_x = self.x0
        self.target_y = self.y0
        self.target_z = self.z0 + HOVER_HEIGHT_M
        self.target_yaw = 0.0
        self.flight_mode = "takeoff"
        self.has_taken_off = True

        print(
            "Despegue low-level global: "
            f"origen=({self.x0:.3f}, {self.y0:.3f}, {self.z0:.3f}), "
            f"objetivo z={self.target_z:.3f}"
        )
        timeout = HOVER_HEIGHT_M / TAKEOFF_SPEED_M_S + 5.0
        deadline = time.monotonic() + timeout
        while not self.is_landing:
            if dc.mocap_pose["z"] >= self.target_z - TAKEOFF_TOLERANCE_M:
                self.flight_mode = "hover"
                self.safety_label.config(
                    text="Seguridad: hover low-level activo", fg="green"
                )
                self.start_hover_button.config(
                    text="HOVER LOW-LEVEL ACTIVO",
                    bg="gray",
                    fg="white",
                    state="disabled",
                )
                self.set_movement_buttons_state("normal")
                print("Hover low-level iniciado. Controles habilitados.")
                return
            if time.monotonic() >= deadline:
                self.emergency_motor_cut(
                    "TIMEOUT DE DESPEGUE: motores apagados"
                )
                return
            time.sleep(CONTROL_PERIOD_S)

    def send_goto(self):
        # El objetivo ya lo consume el lazo continuo; no hay go_to().
        dc.log_target(
            self.target_x,
            self.target_y,
            self.target_z,
            self.target_yaw,
        )

    def rotate_drone(self, _dyaw):
        print("Yaw no está habilitado en esta variante low-level.")


def open_panel(cf, diagnostic_logger) -> None:
    root = dc.tk.Tk()
    panel = CompanionLowLevelPanel(root, cf)
    diagnostic_logger.panel = panel
    root.mainloop()


def main() -> None:
    cflib.crtp.init_drivers(enable_debug_driver=False)
    dc.stop_mqtt_event.clear()
    mqtt_thread = threading.Thread(target=dc.start_mqtt, daemon=True)
    mqtt_thread.start()
    battery_logger = None
    diagnostic_logger = None

    try:
        print("Conectando al Crazyflie...")
        with SyncCrazyflie(dc.URI, cf=Crazyflie(rw_cache="./cache")) as scf:
            dc.cf_global = scf.cf
            configure_lowlevel_global(dc.cf_global)
            battery_logger = dc.BatteryLogger(dc.cf_global)
            battery_logger.start()
            diagnostic_logger = DiagnosticCsvLogger(dc.cf_global)
            diagnostic_logger.start()
            open_panel(dc.cf_global, diagnostic_logger)
    except Exception as exc:
        print("Error general:", exc)
    finally:
        if diagnostic_logger is not None:
            diagnostic_logger.stop()
        if battery_logger is not None:
            battery_logger.stop()
        dc.cf_global = None
        dc.stop_mqtt_event.set()
        mqtt_thread.join(timeout=1.0)
        dc.plot_flight_results()
        print("Programa terminado.")


if __name__ == "__main__":
    main()
