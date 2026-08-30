"""Interfaz segura para diagnosticar un Crazyflie de forma independiente.

El panel abre una sola Crazyradio y un solo topico MoCap. Reutiliza el lazo
low-level conservador y todas sus protecciones de MoCap, EKF y altura, pero no
exige la presencia del segundo dron.
"""

from __future__ import annotations

import argparse
import threading
import time
import tkinter as tk
from tkinter import messagebox

import cflib.crtp
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie

from control_dos_drones_botones_lowlevel import (
    LowLevelButtonFlight,
    STEP_XY_M,
    STEP_Z_M,
)
from dual_flight_logger import DualFlightLogger
from prueba_estabilidad_dos_drones_lowlevel import (
    DEFAULT_TOPIC_1,
    DEFAULT_TOPIC_2,
    DEFAULT_URI_1,
    DEFAULT_URI_2,
    DroneUnit,
)


class SingleDroneApp(tk.Tk):
    def __init__(self, unit: DroneUnit) -> None:
        super().__init__()
        self.unit = unit
        self.title(f"{unit.name} - Prueba individual low-level")
        self.geometry("760x690")
        self.resizable(False, False)

        self.link: SyncCrazyflie | None = None
        self.controller: LowLevelButtonFlight | None = None
        self.ready = False
        self.connecting = False
        self.closing = False
        self.emergency_event = threading.Event()
        self._emergency_handling = False
        prefix = unit.name.lower().replace(" ", "_")
        self.logger = DualFlightLogger(
            folder_name="datos_dron_individual",
            filename_prefix=f"prueba_{prefix}",
        )

        self.status = tk.StringVar(
            value="Conecta y valida el dron. La conexion no arranca los motores."
        )
        self.telemetry = tk.StringVar(value="Sin telemetria")
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda _event: self.emergency())
        self.after(120, self.refresh)

    def _build(self) -> None:
        tk.Label(
            self,
            text=f"PRUEBA INDIVIDUAL — {self.unit.name.upper()}",
            font=("Segoe UI", 19, "bold"),
        ).pack(pady=(16, 3))
        tk.Label(
            self,
            text="Control low-level conservador con posicion MoCap global",
            fg="#356b35",
        ).pack()

        info = tk.LabelFrame(self, text=" Configuracion ", padx=12, pady=8)
        info.pack(fill="x", padx=24, pady=14)
        tk.Label(info, text=f"Radio: {self.unit.uri}", anchor="w").pack(fill="x")
        tk.Label(info, text=f"MoCap: {self.unit.topic}", anchor="w").pack(fill="x")
        tk.Label(
            info,
            text="Solo este dron sera conectado; no se requiere el segundo marcador.",
            anchor="w",
            fg="#654f00",
        ).pack(fill="x", pady=(5, 0))

        top = tk.Frame(self)
        top.pack(pady=4)
        tk.Button(
            top,
            text="CONECTAR Y VALIDAR",
            width=22,
            command=self.connect,
        ).grid(row=0, column=0, padx=5)
        tk.Button(
            top,
            text="DESPEGAR",
            width=16,
            bg="#398a31",
            fg="white",
            command=self.takeoff,
        ).grid(row=0, column=1, padx=5)
        tk.Button(top, text="ATERRIZAR", width=16, command=self.land).grid(
            row=0, column=2, padx=5
        )
        tk.Button(
            top,
            text="EMERGENCIA (ESC)",
            width=19,
            bg="#b72f2a",
            fg="white",
            command=self.emergency,
        ).grid(row=0, column=3, padx=5)

        tk.Label(
            self,
            text=f"Movimientos: {STEP_XY_M * 100:.0f} cm horizontal / {STEP_Z_M * 100:.0f} cm vertical",
            font=("Segoe UI", 11, "bold"),
        ).pack(pady=(20, 6))
        moves = tk.Frame(self)
        moves.pack()

        def move_button(
            label: str,
            row: int,
            column: int,
            dx: float,
            dy: float,
            dz: float,
        ) -> None:
            tk.Button(
                moves,
                text=label,
                width=17,
                height=2,
                command=lambda: self.move(dx, dy, dz),
            ).grid(row=row, column=column, padx=5, pady=5)

        move_button("ADELANTE  +X", 0, 1, STEP_XY_M, 0.0, 0.0)
        move_button("IZQUIERDA  +Y", 1, 0, 0.0, STEP_XY_M, 0.0)
        tk.Button(
            moves,
            text="HOVER AQUI",
            width=17,
            height=2,
            bg="#dcefd8",
            command=self.hover_here,
        ).grid(row=1, column=1, padx=5, pady=5)
        move_button("DERECHA  -Y", 1, 2, 0.0, -STEP_XY_M, 0.0)
        move_button("ATRAS  -X", 2, 1, -STEP_XY_M, 0.0, 0.0)
        move_button("SUBIR  +Z", 0, 3, 0.0, 0.0, STEP_Z_M)
        move_button("BAJAR  -Z", 2, 3, 0.0, 0.0, -STEP_Z_M)

        telemetry_frame = tk.LabelFrame(self, text=" Telemetria en vivo ", padx=12, pady=10)
        telemetry_frame.pack(fill="x", padx=24, pady=(20, 8))
        tk.Label(
            telemetry_frame,
            textvariable=self.telemetry,
            justify="left",
            anchor="w",
            font=("Consolas", 10),
        ).pack(fill="x")
        tk.Label(
            self,
            textvariable=self.status,
            wraplength=700,
            justify="center",
            fg="#24342d",
        ).pack(padx=20, pady=12)

    def _set_status(self, text: str) -> None:
        if not self.closing:
            self.after(0, self.status.set, text)

    def connect(self) -> None:
        if self.connecting:
            return
        if self.ready:
            self.status.set(f"{self.unit.name} ya esta listo.")
            return
        self.connecting = True
        self.status.set("Validando MoCap, radio y alineacion EKF. Motores apagados.")
        threading.Thread(target=self._connect_worker, daemon=True).start()

    def _connect_worker(self) -> None:
        try:
            if not self.logger.active:
                path = self.logger.start()
                self.logger.event(self.unit.name, "INICIO_PRUEBA_INDIVIDUAL")
                print(f"Log individual: {path.resolve()}")
            self.unit.start_mocap()
            self.unit.wait_for_stable_origin()
            link = SyncCrazyflie(
                self.unit.uri,
                cf=Crazyflie(rw_cache=f"./cache_{self.unit.name.replace(' ', '_')}"),
            )
            link.open_link()
            self.link = link
            with self.unit.lock:
                self.unit.cf = link.cf
                self.unit.abort_reason = None
            self.unit.configure()
            self.unit.wait_for_ekf_alignment()
            self.emergency_event.clear()
            self._emergency_handling = False
            self.controller = LowLevelButtonFlight(
                self.unit,
                None,
                self.emergency_event,
            )
            self.ready = True
            self.logger.event(self.unit.name, "PRECHECK_OK", self.unit.status)
            self._set_status(
                "Listo. Haz primero un despegue y hover corto; ESC corta motores."
            )
        except Exception as exc:
            self.logger.event(self.unit.name, "ERROR_PRECHECK", str(exc))
            self._set_status(f"Conexion/preflight bloqueado: {exc}")
            self._disconnect()
        finally:
            self.connecting = False

    def takeoff(self) -> None:
        if not self.ready or self.controller is None:
            messagebox.showwarning("Despegue bloqueado", "Primero conecta y valida el dron.")
            return
        result = self.controller.takeoff()
        if result.ok:
            self.logger.event(self.unit.name, "DESPEGUE")
            self.status.set("Despegue solicitado; espera a que aparezca HOVER.")
        else:
            messagebox.showwarning(self.unit.name, result.message)

    def land(self) -> None:
        if self.controller is None:
            return
        result = self.controller.land()
        if result.ok:
            self.logger.event(self.unit.name, "ATERRIZAJE")
            self.status.set("Aterrizaje solicitado.")
        else:
            messagebox.showwarning(self.unit.name, result.message)

    def move(self, dx: float, dy: float, dz: float) -> None:
        if self.controller is None:
            messagebox.showwarning("Movimiento bloqueado", "Primero conecta y valida el dron.")
            return
        result = self.controller.request_move(dx, dy, dz)
        if result.ok:
            detail = f"dx={dx:+.2f}, dy={dy:+.2f}, dz={dz:+.2f}"
            self.logger.event(self.unit.name, f"MOVER {detail}")
            self.status.set(f"Objetivo actualizado: {detail}")
        else:
            self.status.set(f"Movimiento bloqueado: {result.message}")

    def hover_here(self) -> None:
        if self.controller is None:
            return
        result = self.controller.hover_here()
        if result.ok:
            self.logger.event(self.unit.name, "HOVER_POSICION_ACTUAL")
            self.status.set("La posicion MoCap actual es el nuevo objetivo.")
        else:
            messagebox.showwarning(self.unit.name, result.message)

    def emergency(self) -> None:
        if self._emergency_handling:
            return
        self._emergency_handling = True
        self.emergency_event.set()
        self.logger.event(self.unit.name, "EMERGENCIA_MANUAL")
        self.status.set("EMERGENCIA: cortando motores y cerrando la radio...")
        threading.Thread(target=self._emergency_worker, daemon=True).start()

    def _emergency_worker(self) -> None:
        self.unit.set_abort("paro de emergencia")
        self.unit.send_stop()
        self._disconnect()
        self._set_status("Motores apagados. Puedes volver a conectar para otra prueba.")

    def _disconnect(self) -> None:
        controller, self.controller = self.controller, None
        if controller is not None:
            controller.stop()
        self.unit.stop_ekf_log()
        link, self.link = self.link, None
        if link is not None:
            try:
                link.close_link()
            except Exception:
                pass
        with self.unit.lock:
            self.unit.cf = None
            self.unit.airborne = False
        self.ready = False

    def refresh(self) -> None:
        if self.closing:
            return
        if self.ready and self.emergency_event.is_set() and not self._emergency_handling:
            self._emergency_handling = True
            with self.unit.lock:
                reason = self.unit.abort_reason or "proteccion automatica"
            self.logger.event(self.unit.name, "ABORTO_AUTOMATICO", reason)
            self.status.set(f"ABORTO AUTOMATICO: {reason}. Cortando motores...")
            threading.Thread(target=self._emergency_worker, daemon=True).start()

        pose = self.unit.fresh_pose()
        with self.unit.lock:
            target = None if self.unit.target is None else list(self.unit.target)
            error = self.unit.error
            command = self.unit.command
            mode = self.unit.mode
            unit_status = self.unit.status
            ekf = self.unit.ekf_mocap_error
            battery = self.unit.battery_v
            battery_pct = self.unit.battery_level_pct
            roll = self.unit.roll_deg
            pitch = self.unit.pitch_deg
            hz = self.unit.mocap_hz
            mocap_velocity = self.unit.mocap_velocity
        pose_text = "sin posicion" if pose is None else f"({pose.x:+.3f}, {pose.y:+.3f}, {pose.z:+.3f}) m"
        target_text = "sin objetivo" if target is None else f"({target[0]:+.3f}, {target[1]:+.3f}, {target[2]:+.3f}) m"
        error_text = "-" if error is None else f"({error[0]:+.3f}, {error[1]:+.3f}, {error[2]:+.3f}) m"
        command_text = "-" if command is None else f"({command[0]:+.3f}, {command[1]:+.3f}, {command[2]:+.3f}) m/s"
        ekf_text = "-" if ekf is None else f"{ekf:.3f} m"
        battery_text = "-" if battery is None else f"{battery:.3f} V / {battery_pct}%"
        attitude = "-" if roll is None or pitch is None else f"roll={roll:+.1f}°, pitch={pitch:+.1f}°"
        velocity_text = (
            "-"
            if mocap_velocity is None
            else f"({mocap_velocity[0]:+.3f}, {mocap_velocity[1]:+.3f}, {mocap_velocity[2]:+.3f}) m/s"
        )
        self.telemetry.set(
            f"Estado:   {unit_status}\n"
            f"Modo:     {mode}\n"
            f"MoCap:    {pose_text}  @ {hz:.1f} Hz\n"
            f"Velocidad:{velocity_text}\n"
            f"Objetivo: {target_text}\n"
            f"Error:    {error_text}\n"
            f"Comando:  {command_text}\n"
            f"EKF-MoCap:{ekf_text}    Bateria: {battery_text}\n"
            f"Actitud:  {attitude}"
        )
        self.logger.sample(self.unit)
        self.after(120, self.refresh)

    def close(self) -> None:
        if self.closing:
            return
        self.closing = True
        if self.unit.airborne or self.ready:
            self.emergency_event.set()
            self.unit.send_stop()
        self._disconnect()
        self.unit.stop_mocap()
        if self.logger.active:
            self.logger.event(self.unit.name, "CIERRE_PRUEBA_INDIVIDUAL")
        path = self.logger.stop()
        if path is not None:
            print(f"CSV individual guardado: {path.resolve()}")
        self.destroy()


def run_individual(name: str, uri: str, topic: str) -> None:
    cflib.crtp.init_drivers(enable_debug_driver=False)
    SingleDroneApp(DroneUnit(name, uri, topic)).mainloop()


def main(
    default_name: str = "Dron 1",
    default_uri: str | None = None,
    default_topic: str | None = None,
) -> None:
    parser = argparse.ArgumentParser(description="Interfaz low-level para un Crazyflie")
    parser.add_argument("--drone", type=int, choices=(1, 2), help="selecciona la configuracion guardada")
    parser.add_argument("--name", help="nombre mostrado; opcional")
    parser.add_argument("--uri", help="Crazyradio manual; requiere tambien --topic")
    parser.add_argument("--topic", help="topico MoCap manual; requiere tambien --uri")
    args = parser.parse_args()

    presets = {
        1: ("Dron 1", DEFAULT_URI_1, DEFAULT_TOPIC_1),
        2: ("Dron 2", DEFAULT_URI_2, DEFAULT_TOPIC_2),
    }
    if args.drone is not None:
        name, uri, topic = presets[args.drone]
    elif default_uri is not None and default_topic is not None:
        name, uri, topic = default_name, default_uri, default_topic
    elif args.uri is not None and args.topic is not None:
        name, uri, topic = default_name, args.uri, args.topic
    else:
        parser.error("usa --drone 1/2 o proporciona juntos --uri y --topic")

    # Los valores manuales, cuando se proporcionan juntos, reemplazan el preset.
    if (args.uri is None) != (args.topic is None):
        parser.error("--uri y --topic deben proporcionarse juntos")
    if args.uri is not None:
        uri, topic = args.uri, args.topic
    run_individual(args.name or name, uri, topic)


if __name__ == "__main__":
    main()
