"""Panel de botones para dos Crazyflies con el controlador low-level estable.

Esta variante conserva el panel de botones, pero reemplaza los comandos
high-level por el lazo externo de MoCap validado en la prueba de estabilidad.
Cada dron tiene un lazo P de velocidad global con limites, zona muerta y rampa
de despegue lenta. Los movimientos manuales cambian el mismo objetivo global.

Ejecutar:
    .\.venv\Scripts\python.exe .\drone_control\control_dos_drones_botones_lowlevel.py
"""

from __future__ import annotations

import argparse
import math
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox

import cflib.crtp
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie

from dual_flight_logger import DualFlightLogger
from prueba_estabilidad_dos_drones_lowlevel import (
    BROKER,
    COMMAND_SLEW_XY_M_S2,
    COMMAND_SLEW_Z_M_S2,
    DEFAULT_TOPIC_1,
    DEFAULT_TOPIC_2,
    DEFAULT_URI_1,
    DEFAULT_URI_2,
    DAMPING_KD_XY_DRON_2,
    EKF_ALIGNMENT_M,
    KP_XY,
    KP_Z,
    LANDING_MARGIN_M,
    LANDING_RATE_M_S,
    MAX_EKF_MOCAP_ERROR_M,
    MAX_HEIGHT_OVERSHOOT_M,
    MAX_HORIZONTAL_ERROR_M,
    MAX_XY_SPEED_M_S,
    MAX_Z_SPEED_M_S,
    MIN_SEPARATION_M,
    MOCAP_TIMEOUT_S,
    TAKEOFF_RATE_M_S,
    XY_DEADBAND_M,
    Z_DEADBAND_M,
    DroneUnit,
    clamp,
    deadband,
    run_analysis,
    slew,
)


HOVER_OFFSET_M = 0.35
STEP_XY_M = 0.10
STEP_Z_M = 0.04
MAX_MANUAL_XY_OFFSET_M = 0.30
MIN_MANUAL_HEIGHT_M = 0.20
MAX_MANUAL_HEIGHT_M = 0.65
CONTROL_PERIOD_S = 0.05
TAKEOFF_SETTLE_XY_M = 0.08
TAKEOFF_SETTLE_Z_M = 0.04
MOVE_SETTLE_XY_M = 0.04
MOVE_SETTLE_Z_M = 0.03


@dataclass
class TargetChange:
    ok: bool
    message: str = ""


class LowLevelButtonFlight:
    """Lazo de control continuo de una unidad y objetivo editable con botones."""

    def __init__(self, unit: DroneUnit, other: DroneUnit | None, emergency: threading.Event) -> None:
        self.unit = unit
        self.other = other
        self.emergency = emergency
        self.lock = threading.RLock()
        self.phase = "IDLE"
        self.requested: list[float] | None = None
        self.landing_target: list[float] | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name=f"LowLevel-{unit.name}")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)

    def takeoff(self) -> TargetChange:
        pose = self.unit.fresh_pose()
        with self.unit.lock:
            origin = self.unit.origin
            cf = self.unit.cf
        if origin is None or cf is None:
            return TargetChange(False, "El dron todavia no esta listo")
        if pose is None:
            return TargetChange(False, "No hay MoCap fresco")
        with self.lock:
            if self.phase not in ("IDLE", "LANDED"):
                return TargetChange(False, "Ese dron ya esta en vuelo")
            self.requested = [origin[0], origin[1], origin[2] + HOVER_OFFSET_M]
            self.landing_target = None
            self.phase = "TAKEOFF"
        with self.unit.lock:
            self.unit.airborne = True
            self.unit.mode = "TAKEOFF"
            self.unit.status = f"Despegando lentamente a {self.requested[2]:.2f} m"
        return TargetChange(True)

    def request_move(self, dx: float, dy: float, dz: float) -> TargetChange:
        pose = self.unit.fresh_pose()
        with self.lock, self.unit.lock:
            origin = self.unit.origin
            current = None if self.requested is None else list(self.requested)
            phase = self.phase
        if phase != "HOVER" or origin is None or current is None:
            return TargetChange(False, "Espera a que el hover este activo antes de moverlo")
        if pose is None:
            return TargetChange(False, "No hay MoCap fresco")
        if (
            math.hypot(current[0] - pose.x, current[1] - pose.y) > MOVE_SETTLE_XY_M
            or abs(current[2] - pose.z) > MOVE_SETTLE_Z_M
        ):
            return TargetChange(False, "Espera a que alcance el objetivo anterior")
        candidate = [
            clamp(current[0] + dx, origin[0] - MAX_MANUAL_XY_OFFSET_M, origin[0] + MAX_MANUAL_XY_OFFSET_M),
            clamp(current[1] + dy, origin[1] - MAX_MANUAL_XY_OFFSET_M, origin[1] + MAX_MANUAL_XY_OFFSET_M),
            clamp(current[2] + dz, origin[2] + MIN_MANUAL_HEIGHT_M, origin[2] + MAX_MANUAL_HEIGHT_M),
        ]
        if math.dist(candidate, current) < 1e-6:
            return TargetChange(False, "Limite manual alcanzado; el objetivo no cambio")
        other_pose = None if self.other is None else self.other.fresh_pose()
        if other_pose is not None and math.dist(candidate, other_pose.xyz()) < MIN_SEPARATION_M:
            return TargetChange(False, f"Movimiento bloqueado: mantén {MIN_SEPARATION_M:.2f} m de separación")
        with self.lock:
            self.requested = candidate
        return TargetChange(True)

    def preview_move(self, dx: float, dy: float, dz: float) -> tuple[TargetChange, list[float] | None]:
        """Calcula un objetivo sin modificarlo; se usa para mover ambos a la vez."""
        with self.lock, self.unit.lock:
            origin = self.unit.origin
            current = None if self.requested is None else list(self.requested)
            phase = self.phase
        if phase != "HOVER" or origin is None or current is None:
            return TargetChange(False, "Espera a que el hover este activo antes de moverlo"), None
        candidate = [
            clamp(current[0] + dx, origin[0] - MAX_MANUAL_XY_OFFSET_M, origin[0] + MAX_MANUAL_XY_OFFSET_M),
            clamp(current[1] + dy, origin[1] - MAX_MANUAL_XY_OFFSET_M, origin[1] + MAX_MANUAL_XY_OFFSET_M),
            clamp(current[2] + dz, origin[2] + MIN_MANUAL_HEIGHT_M, origin[2] + MAX_MANUAL_HEIGHT_M),
        ]
        if math.dist(candidate, current) < 1e-6:
            return TargetChange(False, "Limite manual alcanzado; el objetivo no cambio"), None
        return TargetChange(True), candidate

    def apply_target(self, candidate: list[float]) -> TargetChange:
        """Aplica un objetivo ya validado, solamente mientras el dron hace hover."""
        with self.lock:
            if self.phase != "HOVER":
                return TargetChange(False, "El hover ya no esta activo")
            self.requested = list(candidate)
        return TargetChange(True)

    def hover_here(self) -> TargetChange:
        pose = self.unit.fresh_pose()
        with self.lock:
            phase = self.phase
        if phase != "HOVER" or pose is None:
            return TargetChange(False, "Hover disponible solo cuando el dron ya esta estable")
        with self.lock:
            self.requested = [pose.x, pose.y, pose.z]
        return TargetChange(True)

    def land(self) -> TargetChange:
        pose = self.unit.fresh_pose()
        with self.lock, self.unit.lock:
            origin = self.unit.origin
            phase = self.phase
        if phase in ("IDLE", "LANDED"):
            return TargetChange(False, "Ese dron no esta en vuelo")
        if pose is None or origin is None:
            return TargetChange(False, "No se puede aterrizar sin MoCap fresco")
        with self.lock:
            self.landing_target = [pose.x, pose.y, pose.z]
            self.phase = "LANDING"
        with self.unit.lock:
            self.unit.mode = "LANDING"
            self.unit.status = "Aterrizaje low-level lento"
        return TargetChange(True)

    def _abort(self, reason: str) -> None:
        self.unit.set_abort(reason)
        # El evento global hace que la interfaz corte ambos enlaces enseguida.
        # Este stop adicional protege al dron que detecto primero la condicion.
        with self.unit.lock:
            cf = self.unit.cf
        if cf is not None:
            try:
                cf.commander.send_stop_setpoint()
            except Exception:
                pass
        self.emergency.set()

    def _target_for_cycle(self, dt: float) -> tuple[str, tuple[float, float, float]] | None:
        with self.lock, self.unit.lock:
            origin = self.unit.origin
            requested = None if self.requested is None else list(self.requested)
            phase = self.phase
            landing_target = None if self.landing_target is None else list(self.landing_target)
        if origin is None or requested is None:
            return None
        if phase == "TAKEOFF":
            target = (origin[0], origin[1], min(requested[2], (self.unit.target or list(origin))[2] + TAKEOFF_RATE_M_S * dt))
            pose = self.unit.fresh_pose()
            ramp_complete = target[2] >= requested[2] - 0.001
            physically_settled = (
                pose is not None
                and math.hypot(requested[0] - pose.x, requested[1] - pose.y)
                <= TAKEOFF_SETTLE_XY_M
                and abs(requested[2] - pose.z) <= TAKEOFF_SETTLE_Z_M
            )
            if ramp_complete and physically_settled:
                with self.lock:
                    self.phase = "HOVER"
                phase = "HOVER"
        elif phase == "HOVER":
            target = tuple(requested)
        elif phase == "LANDING":
            if landing_target is None:
                return None
            landing_target[2] = max(origin[2], landing_target[2] - LANDING_RATE_M_S * dt)
            with self.lock:
                self.landing_target = landing_target
            target = tuple(landing_target)
        else:
            return None
        return phase, target

    def _loop(self) -> None:
        previous_command = (0.0, 0.0, 0.0)
        previous_time = time.monotonic()
        while not self._stop.is_set():
            now = time.monotonic()
            dt = max(0.001, min(0.15, now - previous_time))
            previous_time = now
            if self.emergency.is_set():
                time.sleep(CONTROL_PERIOD_S)
                continue
            target_data = self._target_for_cycle(dt)
            if target_data is None:
                previous_command = (0.0, 0.0, 0.0)
                time.sleep(CONTROL_PERIOD_S)
                continue
            phase, target = target_data
            pose = self.unit.fresh_pose()
            other_pose = None if self.other is None else self.other.fresh_pose()
            if pose is None:
                self._abort(f"MoCap sin actualizar por > {MOCAP_TIMEOUT_S:.2f} s")
                continue
            if self.other is not None and other_pose is None:
                self._abort("MoCap del otro dron perdido")
                continue
            separation = None if other_pose is None else math.dist(pose.xyz(), other_pose.xyz())
            if separation is not None and separation < MIN_SEPARATION_M:
                self._abort(f"separacion {separation:.2f} m < {MIN_SEPARATION_M:.2f} m")
                continue
            with self.unit.lock:
                estimate = self.unit.estimate
                mocap_velocity = self.unit.mocap_velocity
                origin = self.unit.origin
                cf = self.unit.cf
            if cf is None or origin is None:
                self._abort("enlace u origen no disponible")
                continue
            if estimate is not None:
                ekf_error = math.dist(estimate.xyz(), pose.xyz())
                if ekf_error > MAX_EKF_MOCAP_ERROR_M:
                    self._abort(f"EKF-MoCap={ekf_error:.3f} m")
                    continue
            else:
                ekf_error = None
            ex, ey, ez = target[0] - pose.x, target[1] - pose.y, target[2] - pose.z
            horizontal_error = math.hypot(ex, ey)
            if horizontal_error > MAX_HORIZONTAL_ERROR_M:
                self._abort(f"error horizontal {horizontal_error:.3f} m")
                continue
            if pose.z > origin[2] + MAX_MANUAL_HEIGHT_M + MAX_HEIGHT_OVERSHOOT_M:
                self._abort("sobrepaso vertical")
                continue
            damping_kd_xy = DAMPING_KD_XY_DRON_2 if self.unit.name == "Dron 2" else 0.0
            measured_vx, measured_vy = (
                (0.0, 0.0)
                if mocap_velocity is None
                else (mocap_velocity[0], mocap_velocity[1])
            )
            requested_command = (
                clamp(
                    KP_XY * deadband(ex, XY_DEADBAND_M) - damping_kd_xy * measured_vx,
                    -MAX_XY_SPEED_M_S,
                    MAX_XY_SPEED_M_S,
                ),
                clamp(
                    KP_XY * deadband(ey, XY_DEADBAND_M) - damping_kd_xy * measured_vy,
                    -MAX_XY_SPEED_M_S,
                    MAX_XY_SPEED_M_S,
                ),
                clamp(KP_Z * deadband(ez, Z_DEADBAND_M), -MAX_Z_SPEED_M_S, MAX_Z_SPEED_M_S),
            )
            command = (
                slew(previous_command[0], requested_command[0], COMMAND_SLEW_XY_M_S2, dt),
                slew(previous_command[1], requested_command[1], COMMAND_SLEW_XY_M_S2, dt),
                slew(previous_command[2], requested_command[2], COMMAND_SLEW_Z_M_S2, dt),
            )
            previous_command = command
            try:
                cf.commander.send_velocity_world_setpoint(*command, 0.0)
            except Exception as exc:
                self._abort(f"fallo enviando setpoint: {exc}")
                continue
            with self.unit.lock:
                self.unit.target = list(target)
                self.unit.error = (ex, ey, ez)
                self.unit.command = command
                self.unit.ekf_mocap_error = ekf_error
                self.unit.separation = separation
                self.unit.mode = phase
                self.unit.status = "Hover low-level activo" if phase == "HOVER" else phase
            if phase == "LANDING" and target[2] <= origin[2] + .002 and pose.z <= origin[2] + LANDING_MARGIN_M:
                with self.lock:
                    self.phase = "LANDED"
                with self.unit.lock:
                    self.unit.airborne = False
                    self.unit.mode = "LANDED"
                    self.unit.status = "Aterrizado"
                try:
                    cf.commander.send_stop_setpoint()
                except Exception:
                    pass
            time.sleep(max(0.0, CONTROL_PERIOD_S - (time.monotonic() - now)))


class App(tk.Tk):
    def __init__(self, first: DroneUnit, second: DroneUnit) -> None:
        super().__init__()
        self.title("Dos Crazyflies - Control low-level por botones")
        self.geometry("900x830")
        self.first, self.second = first, second
        self.units = (first, second)
        self.links: list[SyncCrazyflie] = []
        self.ready = False
        self.connecting = False
        self.emergency_event = threading.Event()
        self._emergency_handling = False
        self.controllers: dict[str, LowLevelButtonFlight] = {}
        self.logger = DualFlightLogger()
        self.selected = tk.StringVar(value=first.name)
        self.status = tk.StringVar(value="Conecta los dos drones. No se enviaran comandos de vuelo al conectar.")
        self.unit_text = {unit.name: tk.StringVar(value="Desconectado") for unit in self.units}
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda _event: self.emergency())
        self.after(150, self.refresh)

    def _build(self) -> None:
        tk.Label(self, text="CONTROL LOW-LEVEL DE DOS DRONES", font=("Segoe UI", 18, "bold")).pack(pady=(14, 2))
        tk.Label(self, text="MoCap ROBOTAT - rampa lenta, limites de velocidad y paro inmediato", fg="#356b35").pack()
        top = tk.Frame(self)
        top.pack(pady=14)
        self.top_controls = top
        tk.Button(top, text="CONECTAR Y VALIDAR", width=24, command=self.connect_both).grid(row=0, column=0, padx=5)
        tk.Button(top, text="DESPEGAR AMBOS", width=22, bg="#398a31", fg="white", command=self.takeoff_both).grid(row=0, column=1, padx=5)
        tk.Button(top, text="ATERRIZAR AMBOS", width=22, command=self.land_both).grid(row=0, column=2, padx=5)
        tk.Button(top, text="EMERGENCIA", width=18, bg="#b72f2a", fg="white", command=self.emergency).grid(row=0, column=3, padx=5)

        cards = tk.Frame(self)
        cards.pack(fill="x", padx=26)
        for column, unit in enumerate(self.units):
            frame = tk.LabelFrame(cards, text=f" {unit.name} ", padx=12, pady=10)
            frame.grid(row=0, column=column, padx=8, sticky="nsew")
            cards.grid_columnconfigure(column, weight=1)
            tk.Radiobutton(frame, text="Controlar este dron", variable=self.selected, value=unit.name).pack(anchor="w")
            tk.Label(frame, text=f"URI: {unit.uri}", wraplength=360, justify="left").pack(anchor="w", pady=(4, 0))
            tk.Label(frame, text=f"MoCap: {unit.topic}").pack(anchor="w")
            tk.Label(frame, textvariable=self.unit_text[unit.name], wraplength=360, justify="left", fg="#24342d").pack(anchor="w", pady=(7, 6))
            buttons = tk.Frame(frame)
            buttons.pack()
            tk.Button(buttons, text="DESPEGAR", width=14, bg="#398a31", fg="white", command=lambda u=unit: self.takeoff(u)).grid(row=0, column=0, padx=3)
            tk.Button(buttons, text="ATERRIZAR", width=14, command=lambda u=unit: self.land(u)).grid(row=0, column=1, padx=3)

        tk.Label(self, text="Movimiento del dron seleccionado (5 cm horizontal / 4 cm vertical)", font=("Segoe UI", 11, "bold")).pack(pady=(22, 5))
        move = tk.Frame(self)
        move.pack()
        def button(label: str, row: int, column: int, dx: float, dy: float, dz: float) -> None:
            tk.Button(move, text=label, width=15, height=2, command=lambda: self.move(dx, dy, dz)).grid(row=row, column=column, padx=4, pady=4)
        button("ADELANTE", 0, 1, STEP_XY_M, 0.0, 0.0)
        button("IZQUIERDA", 1, 0, 0.0, STEP_XY_M, 0.0)
        tk.Button(move, text="HOVER AQUI", width=15, height=2, command=self.hover_here).grid(row=1, column=1, padx=4, pady=4)
        button("DERECHA", 1, 2, 0.0, -STEP_XY_M, 0.0)
        button("ATRAS", 2, 1, -STEP_XY_M, 0.0, 0.0)
        button("SUBIR", 0, 3, 0.0, 0.0, STEP_Z_M)
        button("BAJAR", 2, 3, 0.0, 0.0, -STEP_Z_M)

        tk.Label(
            self,
            text="Movimiento sincronizado: ambos drones (mismo desplazamiento global)",
            font=("Segoe UI", 11, "bold"),
            fg="#356b35",
        ).pack(pady=(16, 5))
        move_both = tk.Frame(self)
        move_both.pack()

        def both_button(label: str, row: int, column: int, dx: float, dy: float, dz: float) -> None:
            tk.Button(
                move_both,
                text=label,
                width=18,
                height=2,
                bg="#dcefd8",
                command=lambda: self.move_both(dx, dy, dz),
            ).grid(row=row, column=column, padx=4, pady=4)

        both_button("AMBOS ADELANTE", 0, 1, STEP_XY_M, 0.0, 0.0)
        both_button("AMBOS IZQUIERDA", 1, 0, 0.0, STEP_XY_M, 0.0)
        tk.Button(move_both, text="HOVER AMBOS AQUI", width=18, height=2, command=self.hover_both_here).grid(row=1, column=1, padx=4, pady=4)
        both_button("AMBOS DERECHA", 1, 2, 0.0, -STEP_XY_M, 0.0)
        both_button("AMBOS ATRAS", 2, 1, -STEP_XY_M, 0.0, 0.0)
        both_button("AMBOS SUBIR", 0, 3, 0.0, 0.0, STEP_Z_M)
        both_button("AMBOS BAJAR", 2, 3, 0.0, 0.0, -STEP_Z_M)
        tk.Label(self, textvariable=self.status, wraplength=850, justify="center").pack(pady=17)

    def connect_both(self) -> None:
        if self.connecting:
            return
        if self.ready:
            self.status.set("Los dos drones ya estan listos.")
            return
        self.connecting = True
        self.status.set("Conectando y validando MoCap/EKF. Los motores permanecen apagados.")
        threading.Thread(target=self._connect_worker, daemon=True).start()

    def _connect_worker(self) -> None:
        try:
            if not self.logger.active:
                path = self.logger.start()
                self.logger.event("SISTEMA", "INICIO_SESION_BOTONES_LOWLEVEL")
                print(f"Log CSV: {path}")
            for unit in self.units:
                unit.start_mocap()
            origins = [unit.wait_for_stable_origin() for unit in self.units]
            if math.dist(origins[0], origins[1]) < MIN_SEPARATION_M:
                raise RuntimeError(f"Los drones deben separarse al menos {MIN_SEPARATION_M:.2f} m")
            # Durante esta fase unit.cf permanece en None: no se mandan extpos
            # al primer dron hasta que el enlace del segundo este listo.
            new_links: list[SyncCrazyflie] = []
            try:
                for unit in self.units:
                    link = SyncCrazyflie(unit.uri, cf=Crazyflie(rw_cache=f"./cache_{unit.name.replace(' ', '_')}"))
                    link.open_link()
                    new_links.append(link)
            except Exception:
                # Si el segundo enlace falla, libera de inmediato el primero para
                # permitir corregir el URI/canal y volver a intentar sin reiniciar.
                for link in reversed(new_links):
                    try:
                        link.close_link()
                    except Exception:
                        pass
                raise
            self.links = new_links
            for unit, link in zip(self.units, self.links):
                with unit.lock:
                    unit.cf = link.cf
            for unit in self.units:
                unit.configure()
            for unit in self.units:
                unit.wait_for_ekf_alignment()
                self.logger.event(unit.name, "PRECHECK_OK", unit.status)
            self.emergency_event.clear()
            self._emergency_handling = False
            self.controllers = {
                self.first.name: LowLevelButtonFlight(self.first, self.second, self.emergency_event),
                self.second.name: LowLevelButtonFlight(self.second, self.first, self.emergency_event),
            }
            self.ready = True
            self.status.set("Listo. Despega ambos o selecciona un dron para despegarlo.")
        except Exception as exc:
            self.status.set(f"Error de conexion/preflight: {exc}")
            self.logger.event("SISTEMA", "ERROR_PRECHECK", str(exc))
            self._disconnect_links()
        finally:
            self.connecting = False

    def _controller_for(self, unit: DroneUnit) -> LowLevelButtonFlight | None:
        return self.controllers.get(unit.name)

    def takeoff(self, unit: DroneUnit) -> None:
        controller = self._controller_for(unit)
        if not self.ready or controller is None:
            messagebox.showwarning("Despegue bloqueado", "Primero conecta y espera que ambos drones esten Listo.")
            return
        result = controller.takeoff()
        if result.ok:
            self.logger.event(unit.name, "DESPEGUE_LOWLEVEL", unit.status)
        else:
            messagebox.showwarning(unit.name, result.message)

    def takeoff_both(self) -> None:
        if not self.ready:
            messagebox.showwarning("Despegue bloqueado", "Primero conecta y valida MoCap/EKF.")
            return
        results = [(unit, self._controller_for(unit).takeoff()) for unit in self.units if self._controller_for(unit) is not None]
        failures = [f"{unit.name}: {result.message}" for unit, result in results if not result.ok]
        for unit, result in results:
            if result.ok:
                self.logger.event(unit.name, "DESPEGUE_CONJUNTO_LOWLEVEL", unit.status)
        if failures:
            messagebox.showwarning("Despegue conjunto bloqueado", "\n".join(failures))

    def land(self, unit: DroneUnit) -> None:
        controller = self._controller_for(unit)
        if controller is None:
            return
        result = controller.land()
        if result.ok:
            self.logger.event(unit.name, "ATERRIZAJE_LOWLEVEL", unit.status)
        else:
            messagebox.showwarning(unit.name, result.message)

    def land_both(self) -> None:
        for unit in self.units:
            controller = self._controller_for(unit)
            if controller is not None:
                result = controller.land()
                if result.ok:
                    self.logger.event(unit.name, "ATERRIZAJE_CONJUNTO_LOWLEVEL", unit.status)

    def selected_unit(self) -> DroneUnit:
        return self.first if self.selected.get() == self.first.name else self.second

    def move(self, dx: float, dy: float, dz: float) -> None:
        unit = self.selected_unit()
        controller = self._controller_for(unit)
        if controller is None:
            messagebox.showwarning("Movimiento bloqueado", "Primero conecta el sistema.")
            return
        result = controller.request_move(dx, dy, dz)
        if result.ok:
            self.logger.event(unit.name, f"MOVER dx={dx:+.2f}, dy={dy:+.2f}, dz={dz:+.2f}")
        else:
            messagebox.showwarning(unit.name, result.message)

    def move_both(self, dx: float, dy: float, dz: float) -> None:
        """Mueve ambos objetivos juntos; nunca aplica un cambio parcial."""
        first_controller = self._controller_for(self.first)
        second_controller = self._controller_for(self.second)
        if not self.ready or first_controller is None or second_controller is None:
            messagebox.showwarning("Movimiento conjunto bloqueado", "Primero conecta y valida ambos drones.")
            return

        first_result, first_target = first_controller.preview_move(dx, dy, dz)
        second_result, second_target = second_controller.preview_move(dx, dy, dz)
        if not first_result.ok or not second_result.ok or first_target is None or second_target is None:
            details = []
            if not first_result.ok:
                details.append(f"Dron 1: {first_result.message}")
            if not second_result.ok:
                details.append(f"Dron 2: {second_result.message}")
            messagebox.showwarning("Movimiento conjunto bloqueado", "\n".join(details))
            return

        if math.dist(first_target, second_target) < MIN_SEPARATION_M:
            messagebox.showwarning("Movimiento conjunto bloqueado", f"La separacion objetivo seria menor a {MIN_SEPARATION_M:.2f} m.")
            return

        # Ambas referencias se actualizan bajo los dos locks: si alguno deja de
        # estar en hover, no se actualiza ningun objetivo.
        with first_controller.lock, second_controller.lock:
            if first_controller.phase != "HOVER" or second_controller.phase != "HOVER":
                messagebox.showwarning("Movimiento conjunto bloqueado", "Ambos drones deben estar en hover.")
                return
            first_controller.requested = list(first_target)
            second_controller.requested = list(second_target)

        detail = f"dx={dx:+.2f}, dy={dy:+.2f}, dz={dz:+.2f}"
        self.logger.event(self.first.name, f"MOVER_CONJUNTO {detail}")
        self.logger.event(self.second.name, f"MOVER_CONJUNTO {detail}")
        self.status.set(f"Movimiento sincronizado aplicado: {detail}")

    def hover_both_here(self) -> None:
        """Fija el objetivo de ambos en sus posiciones actuales de MoCap."""
        first_controller = self._controller_for(self.first)
        second_controller = self._controller_for(self.second)
        if not self.ready or first_controller is None or second_controller is None:
            messagebox.showwarning("Hover conjunto bloqueado", "Primero conecta y valida ambos drones.")
            return
        first_pose, second_pose = self.first.fresh_pose(), self.second.fresh_pose()
        if first_pose is None or second_pose is None:
            messagebox.showwarning("Hover conjunto bloqueado", "Se necesita MoCap fresco de ambos drones.")
            return
        with first_controller.lock, second_controller.lock:
            if first_controller.phase != "HOVER" or second_controller.phase != "HOVER":
                messagebox.showwarning("Hover conjunto bloqueado", "Ambos drones deben estar en hover.")
                return
            first_controller.requested = [first_pose.x, first_pose.y, first_pose.z]
            second_controller.requested = [second_pose.x, second_pose.y, second_pose.z]
        self.logger.event(self.first.name, "HOVER_CONJUNTO_POSICION_ACTUAL")
        self.logger.event(self.second.name, "HOVER_CONJUNTO_POSICION_ACTUAL")
        self.status.set("Hover conjunto fijado en las posiciones actuales.")

    def hover_here(self) -> None:
        unit = self.selected_unit()
        controller = self._controller_for(unit)
        if controller is None:
            return
        result = controller.hover_here()
        if result.ok:
            self.logger.event(unit.name, "HOVER_POSICION_ACTUAL")
        else:
            messagebox.showwarning(unit.name, result.message)

    def _stop_motors_pair(self) -> None:
        for unit in self.units:
            with unit.lock:
                unit.set_abort("paro de emergencia")
        for _ in range(15):
            for unit in self.units:
                with unit.lock:
                    cf = unit.cf
                if cf is not None:
                    try:
                        cf.commander.send_stop_setpoint()
                    except Exception:
                        pass
            time.sleep(.03)

    def emergency(self) -> None:
        if self._emergency_handling:
            return
        self._emergency_handling = True
        self.emergency_event.set()
        self.logger.event("SISTEMA", "EMERGENCIA")
        self.status.set("EMERGENCIA enviada. Cortando motores y cerrando enlaces...")
        threading.Thread(target=self._emergency_worker, daemon=True).start()

    def _emergency_worker(self) -> None:
        self._stop_motors_pair()
        self._disconnect_links()
        self.ready = False
        self.status.set("Motores apagados. Presiona CONECTAR Y VALIDAR para una nueva sesion.")

    def _disconnect_links(self) -> None:
        controllers = list(self.controllers.values())
        self.controllers = {}
        for controller in controllers:
            controller.stop()
        for unit in self.units:
            unit.stop_ekf_log()
        for link in reversed(self.links):
            try:
                link.close_link()
            except Exception:
                pass
        self.links = []
        for unit in self.units:
            with unit.lock:
                unit.cf = None
                unit.airborne = False

    def refresh(self) -> None:
        if self.ready and self.emergency_event.is_set() and not self._emergency_handling:
            # Un controlador detecto una condicion insegura (altura, MoCap,
            # separacion, EKF...). No basta dejar de mandar velocidades: se
            # cortan ambos motores y se guardan los motivos en el CSV.
            self._emergency_handling = True
            reasons = []
            for unit in self.units:
                with unit.lock:
                    if unit.abort_reason:
                        reasons.append(f"{unit.name}: {unit.abort_reason}")
            self.logger.event("SISTEMA", "ABORTO_AUTOMATICO", " | ".join(reasons))
            self.status.set("ABORTO AUTOMATICO. Cortando motores de ambos drones...")
            threading.Thread(target=self._emergency_worker, daemon=True).start()
        for unit in self.units:
            pose = unit.fresh_pose()
            with unit.lock:
                target = unit.target
                mode = unit.mode
                status = unit.status
                ekf_error = unit.ekf_mocap_error
                hz = unit.mocap_hz
            mocap = "sin MoCap" if pose is None else f"x={pose.x:+.2f}, y={pose.y:+.2f}, z={pose.z:+.2f} m"
            target_text = "sin objetivo" if target is None else f"z*={target[2]:.2f} m"
            ekf_text = "sin EKF" if ekf_error is None else f"EKF-MoCap={ekf_error:.3f} m"
            self.unit_text[unit.name].set(f"{status}\nModo: {mode} | MoCap {hz:.1f} Hz | {mocap}\n{target_text} | {ekf_text}")
            self.logger.sample(unit)
        self.after(150, self.refresh)

    def close(self) -> None:
        if any(unit.airborne for unit in self.units):
            self.emergency_event.set()
            self._stop_motors_pair()
        self._disconnect_links()
        for unit in self.units:
            unit.stop_mocap()
        if self.logger.active:
            self.logger.event("SISTEMA", "CIERRE_SESION")
        path = self.logger.stop()
        if path is not None:
            print(f"CSV guardado: {path}")
            run_analysis(path)
        self.destroy()


def main() -> None:
    parser = argparse.ArgumentParser(description="Control low-level por botones para dos Crazyflies")
    parser.add_argument("--uri1", default=DEFAULT_URI_1)
    parser.add_argument("--uri2", default=DEFAULT_URI_2)
    parser.add_argument("--topic1", default=DEFAULT_TOPIC_1)
    parser.add_argument("--topic2", default=DEFAULT_TOPIC_2)
    args = parser.parse_args()
    cflib.crtp.init_drivers(enable_debug_driver=False)
    App(DroneUnit("Dron 1", args.uri1, args.topic1), DroneUnit("Dron 2", args.uri2, args.topic2)).mainloop()


if __name__ == "__main__":
    main()
