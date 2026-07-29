"""Panel original con vuelo High Level en marco global ROBOTAT."""

from __future__ import annotations

import csv
import math
import threading
import time
from datetime import datetime
from pathlib import Path

import cflib.crtp
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.log import LogConfig
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie

import control as dc


HOVER_HEIGHT_M = 0.5
TAKEOFF_DURATION_S = 5.0
MOVE_SPEED_M_S = 0.025
MIN_MOVE_DURATION_S = 2.0
MAX_MOVE_DURATION_S = 5.0
LAND_DURATION_S = 5.0
MOCAP_TIMEOUT_S = 0.75
POSITION_TOLERANCE_M = 0.05
DIAGNOSTIC_LOG_PERIOD_MS = 50
DIAGNOSTIC_FOLDER = Path("datos_vuelo_crazyflie") / "diagnostico_ekf_mocap"

# Pasos conservadores para evitar encadenar trayectorias demasiado grandes.
dc.HOVER_HEIGHT = HOVER_HEIGHT_M
dc.STEP_XY = 0.04
dc.STEP_Z = 0.03


def configure_highlevel_global(cf) -> None:
    """Configura el mismo modo validado por hover_highlevel_global.py."""
    print("Configurando High Level Commander con MoCap global...")
    cf.param.set_value("commander.enHighLevel", "1")
    cf.param.set_value("stabilizer.controller", "1")
    cf.param.set_value("stabilizer.estimator", "2")
    time.sleep(0.5)
    cf.param.set_value("kalman.resetEstimation", "1")
    time.sleep(0.1)
    cf.param.set_value("kalman.resetEstimation", "0")
    print("Esperando estabilización del EKF (5 s)...")
    time.sleep(5.0)


class DiagnosticCsvLogger:
    """Guarda continuamente MoCap, Kalman y su diferencia en un CSV."""

    FIELDNAMES = [
        "fecha_hora",
        "tiempo_s",
        "estado_vuelo",
        "mocap_edad_s",
        "mocap_x_m",
        "mocap_y_m",
        "mocap_z_m",
        "kalman_x_m",
        "kalman_y_m",
        "kalman_z_m",
        "error_kalman_mocap_x_m",
        "error_kalman_mocap_y_m",
        "error_kalman_mocap_z_m",
        "target_x_m",
        "target_y_m",
        "target_z_m",
    ]

    def __init__(self, cf) -> None:
        DIAGNOSTIC_FOLDER.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = DIAGNOSTIC_FOLDER / f"ekf_mocap_{stamp}.csv"
        self.file = self.path.open("w", newline="", encoding="utf-8")
        self.writer = csv.DictWriter(self.file, fieldnames=self.FIELDNAMES)
        self.writer.writeheader()
        self.file.flush()
        self.start_monotonic = time.monotonic()
        self.panel = None
        self.closed = False
        self.lock = threading.Lock()

        self.config = LogConfig(
            name="DiagnosticEKFMocap",
            period_in_ms=DIAGNOSTIC_LOG_PERIOD_MS,
        )
        for axis in ("x", "y", "z"):
            self.config.add_variable(f"stateEstimate.{axis}", "float")
        cf.log.add_config(self.config)
        self.config.data_received_cb.add_callback(self._callback)
        self.config.error_cb.add_callback(self._error_callback)

    def _flight_state(self):
        if self.panel is None:
            return "conectado"
        if self.panel.is_landing:
            return "aterrizando"
        if self.panel.has_taken_off:
            return "volando"
        return "esperando"

    def _target(self):
        if self.panel is None:
            return (None, None, None)
        return (
            self.panel.target_x,
            self.panel.target_y,
            self.panel.target_z,
        )

    def _callback(self, _timestamp, data, _config) -> None:
        mx = dc.mocap_pose["x"]
        my = dc.mocap_pose["y"]
        mz = dc.mocap_pose["z"]
        kx = float(data["stateEstimate.x"])
        ky = float(data["stateEstimate.y"])
        kz = float(data["stateEstimate.z"])
        tx, ty, tz = self._target()
        mocap_age = (
            time.monotonic() - dc.last_mocap_update
            if dc.last_mocap_update > 0.0
            else None
        )

        row = {
            "fecha_hora": datetime.now().isoformat(timespec="milliseconds"),
            "tiempo_s": time.monotonic() - self.start_monotonic,
            "estado_vuelo": self._flight_state(),
            "mocap_edad_s": mocap_age,
            "mocap_x_m": mx,
            "mocap_y_m": my,
            "mocap_z_m": mz,
            "kalman_x_m": kx,
            "kalman_y_m": ky,
            "kalman_z_m": kz,
            "error_kalman_mocap_x_m": None if mx is None else kx - mx,
            "error_kalman_mocap_y_m": None if my is None else ky - my,
            "error_kalman_mocap_z_m": None if mz is None else kz - mz,
            "target_x_m": tx,
            "target_y_m": ty,
            "target_z_m": tz,
        }
        with self.lock:
            if self.closed:
                return
            self.writer.writerow(row)
            # Conservar datos incluso si hay paro de emergencia o caída.
            self.file.flush()

    def _error_callback(self, _config, message) -> None:
        print(f"Error en registro diagnóstico: {message}")

    def start(self) -> None:
        self.config.start()
        print(f"Registro EKF/MoCap activo: {self.path.resolve()}")

    def stop(self) -> None:
        with self.lock:
            if self.closed:
                return
            self.closed = True
        try:
            self.config.stop()
        except Exception:
            pass
        with self.lock:
            self.file.flush()
            self.file.close()
        print(f"Registro EKF/MoCap guardado: {self.path.resolve()}")


class HighLevelGlobalPanel(dc.DroneControlPanel):
    """Conserva la interfaz original y cambia únicamente la capa de vuelo."""

    def _position_control_loop(self):
        # La clase base inicia este hilo, pero esta variante usa exclusivamente
        # High Level Commander. No se deben mezclar comandos de velocidad.
        self.control_stop_event.wait()

    def _mocap_is_fresh(self):
        return (
            dc.last_mocap_update > 0.0
            and time.monotonic() - dc.last_mocap_update <= MOCAP_TIMEOUT_S
        )

    def _wait_interruptible(self, duration_s):
        deadline = time.monotonic() + duration_s
        while time.monotonic() < deadline:
            if self.is_landing:
                return False
            if not self._mocap_is_fresh():
                self.emergency_motor_cut(
                    "MOCAP PERDIDO: motores apagados"
                )
                return False
            time.sleep(0.05)
        return True

    def _movement_duration(self):
        """Duración proporcional a la distancia medida por el MoCap."""
        if (
            self.target_x is None
            or self.target_y is None
            or self.target_z is None
            or dc.mocap_pose["x"] is None
            or dc.mocap_pose["y"] is None
            or dc.mocap_pose["z"] is None
        ):
            return MIN_MOVE_DURATION_S

        distance = math.sqrt(
            (self.target_x - dc.mocap_pose["x"]) ** 2
            + (self.target_y - dc.mocap_pose["y"]) ** 2
            + (self.target_z - dc.mocap_pose["z"]) ** 2
        )
        return max(
            MIN_MOVE_DURATION_S,
            min(MAX_MOVE_DURATION_S, distance / MOVE_SPEED_M_S),
        )

    def _start_hover_sequence(self):
        if not dc.wait_for_mocap_position(timeout=10.0):
            dc.messagebox.showerror(
                "Error",
                "No hay datos válidos de MoCap. No se despega.",
            )
            return

        if not self._mocap_is_fresh():
            dc.messagebox.showerror(
                "Error",
                "La última posición MoCap es demasiado antigua.",
            )
            return

        try:
            self.start_hover_button.config(
                state="disabled",
                text="DESPEGANDO...",
            )

            self.x0 = dc.mocap_pose["x"]
            self.y0 = dc.mocap_pose["y"]
            self.z0 = dc.mocap_pose["z"]
            self.target_x = self.x0
            self.target_y = self.y0
            self.target_z = self.z0 + HOVER_HEIGHT_M
            self.target_yaw = 0.0

            print(
                "Punto inicial global: "
                f"x={self.x0:.3f}, y={self.y0:.3f}, z={self.z0:.3f}"
            )
            print(
                "Objetivo High Level global: "
                f"x={self.target_x:.3f}, "
                f"y={self.target_y:.3f}, "
                f"z={self.target_z:.3f}"
            )

            self.has_taken_off = True
            self.mocap_fault_triggered = False
            self.commander.takeoff(
                absolute_height_m=self.target_z,
                duration_s=TAKEOFF_DURATION_S,
                yaw=self.target_yaw,
            )

            if not self._wait_interruptible(TAKEOFF_DURATION_S + 0.5):
                return

            # Fijar explícitamente XYZ después de completar la trayectoria
            # de despegue, igual que en la prueba High Level validada.
            self.commander.go_to(
                self.target_x,
                self.target_y,
                self.target_z,
                yaw=self.target_yaw,
                duration_s=MIN_MOVE_DURATION_S,
                relative=False,
            )
            if not self._wait_interruptible(MIN_MOVE_DURATION_S):
                return

            self.safety_label.config(
                text="Seguridad: hover High Level activo",
                fg="green",
            )
            self.start_hover_button.config(
                text="HOVER HIGH LEVEL ACTIVO",
                bg="gray",
                fg="white",
                state="disabled",
            )
            self.set_movement_buttons_state("normal")
            print("Hover High Level iniciado. Controles habilitados.")

        except Exception as exc:
            print("Error iniciando hover High Level:", exc)
            dc.messagebox.showerror(
                "Error",
                f"No se pudo iniciar hover:\n{exc}",
            )
            self.emergency_motor_cut(
                "FALLO DURANTE DESPEGUE: motores apagados"
            )

    def send_goto(self):
        if not self.has_taken_off or self.is_landing:
            return
        duration = self._movement_duration()
        print(
            f"Trayectoria suavizada: duración={duration:.2f} s, "
            f"velocidad de referencia≈{MOVE_SPEED_M_S:.3f} m/s"
        )
        self.commander.go_to(
            self.target_x,
            self.target_y,
            self.target_z,
            yaw=self.target_yaw,
            duration_s=duration,
            relative=False,
        )
        dc.log_target(
            self.target_x,
            self.target_y,
            self.target_z,
            self.target_yaw,
        )

    def rotate_drone(self, dyaw):
        if self.is_landing or not self.has_taken_off:
            return
        with self.lock:
            self.target_yaw += dyaw
            # Mantener el ángulo acotado evita crecer indefinidamente.
            self.target_yaw = (
                self.target_yaw + math.pi
            ) % (2.0 * math.pi) - math.pi
            print(
                f"Nuevo yaw objetivo: "
                f"{math.degrees(self.target_yaw):.1f} grados"
            )
            self.send_goto()

    def emergency_motor_cut(self, reason="Paro de emergencia"):
        if self.is_landing:
            return
        try:
            self.commander.stop()
        except Exception:
            pass
        super().emergency_motor_cut(reason)

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
                print(
                    f"Aterrizando High Level hasta z={self.z0:.3f} m..."
                )
                self.commander.land(
                    absolute_height_m=self.z0,
                    duration_s=LAND_DURATION_S,
                    yaw=self.target_yaw,
                )

                deadline = time.monotonic() + LAND_DURATION_S + 1.0
                while time.monotonic() < deadline:
                    if not self._mocap_is_fresh():
                        print("MoCap perdido durante el aterrizaje.")
                        break
                    if dc.mocap_pose["z"] <= self.z0 + POSITION_TOLERANCE_M:
                        break
                    time.sleep(0.05)

                self.commander.stop()
                for _ in range(15):
                    self.cf.commander.send_stop_setpoint()
                    time.sleep(0.03)
                print("Aterrizaje High Level completado.")
        except Exception as exc:
            print("Error durante aterrizaje:", exc)
            for _ in range(15):
                try:
                    self.cf.commander.send_stop_setpoint()
                except Exception:
                    pass
                time.sleep(0.03)
        finally:
            if dc.recording_active:
                dc.stop_recording(save_csv=True)
            try:
                self.root.destroy()
            except Exception:
                pass


def open_panel(cf, diagnostic_logger) -> None:
    root = dc.tk.Tk()
    panel = HighLevelGlobalPanel(root, cf)
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
        with SyncCrazyflie(
            dc.URI,
            cf=Crazyflie(rw_cache="./cache"),
        ) as scf:
            dc.cf_global = scf.cf
            print("Conectado correctamente.")
            configure_highlevel_global(dc.cf_global)
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
