"""Proceso propietario de una Crazyradio y un Crazyflie.

No se comparte ningun objeto de cflib entre procesos. El trabajador recibe
ordenes de alto nivel por una Queue y mantiene localmente el lazo de 20 Hz.
"""

from __future__ import annotations

import math
import os
import queue
import time
import traceback
from typing import Any

from .protocol import (
    CONTROL_PERIOD_S,
    GESTURE_KP_XY,
    GESTURE_MAX_XY_SPEED_M_S,
    GESTURE_SLEW_XY_M_S2,
    GESTURE_SETTLE_XY_M,
    GESTURE_SETTLE_Z_M,
    HOVER_OFFSET_M,
    MAX_MANUAL_HEIGHT_M,
    MAX_MANUAL_XY_OFFSET_M,
    MIN_MANUAL_HEIGHT_M,
    PEER_TIMEOUT_S,
    STATE_PERIOD_S,
    TAKEOFF_SETTLE_XY_M,
    TAKEOFF_SETTLE_Z_M,
    read_shared_pose,
    safe_put,
    write_shared_pose,
)


class WorkerController:
    """Control de vuelo local y participante de transacciones prepare/commit."""

    def __init__(self, unit, own_pose, peer_pose, emergency_event, event_queue) -> None:
        self.unit = unit
        self.own_pose = own_pose
        self.peer_pose = peer_pose
        self.emergency_event = emergency_event
        self.event_queue = event_queue
        self.phase = "IDLE"
        self.requested: list[float] | None = None
        self.landing_target: list[float] | None = None
        self.pending: dict[str, Any] | None = None
        self.scheduled: dict[str, Any] | None = None
        self.previous_command = (0.0, 0.0, 0.0)
        self.previous_time = time.monotonic()
        self.control_dt_s = 0.0
        self.control_max_dt_s = 0.0
        self.control_overruns = 0
        self._motors_stopped = False

    def _response(self, seq: int, stage: str, ok: bool, message: str = "", **extra) -> None:
        safe_put(
            self.event_queue,
            {
                "kind": "response",
                "drone": self.unit.name,
                "seq": seq,
                "stage": stage,
                "ok": ok,
                "message": message,
                "timestamp": time.monotonic(),
                **extra,
            },
            important=True,
        )

    def prepare(self, message: dict[str, Any]) -> None:
        seq = int(message["seq"])
        action = str(message["action"])
        payload = message.get("payload") or {}
        pose = self.unit.fresh_pose()
        with self.unit.lock:
            origin = self.unit.origin
            cf = self.unit.cf

        if self.emergency_event.is_set():
            self._response(seq, "PREPARED", False, "emergencia activa")
            return
        if self.pending is not None or self.scheduled is not None:
            self._response(seq, "PREPARED", False, "hay otra transaccion pendiente")
            return
        if pose is None or origin is None or cf is None:
            self._response(seq, "PREPARED", False, "enlace, origen o MoCap no disponible")
            return

        candidate: list[float] | None = None
        if action == "DESPEGAR":
            if self.phase not in ("IDLE", "LANDED"):
                self._response(seq, "PREPARED", False, f"fase actual: {self.phase}")
                return
            candidate = [origin[0], origin[1], origin[2] + HOVER_OFFSET_M]
        elif action == "ATERRIZAR":
            if self.phase in ("IDLE", "LANDED"):
                self._response(seq, "PREPARED", False, "el dron no esta en vuelo")
                return
            candidate = [pose.x, pose.y, pose.z]
        elif action == "MOVER":
            if self.phase != "HOVER" or self.requested is None:
                self._response(seq, "PREPARED", False, "el hover aun no esta activo")
                return
            allow_unsettled = bool(payload.get("allow_unsettled", False))
            if not allow_unsettled and (
                math.hypot(self.requested[0] - pose.x, self.requested[1] - pose.y) > GESTURE_SETTLE_XY_M
                or abs(self.requested[2] - pose.z) > GESTURE_SETTLE_Z_M
            ):
                self._response(seq, "PREPARED", False, "esperando alcanzar el objetivo anterior")
                return
            dx, dy, dz = (float(payload.get(axis, 0.0)) for axis in ("dx", "dy", "dz"))
            candidate = [
                _clamp(self.requested[0] + dx, origin[0] - MAX_MANUAL_XY_OFFSET_M, origin[0] + MAX_MANUAL_XY_OFFSET_M),
                _clamp(self.requested[1] + dy, origin[1] - MAX_MANUAL_XY_OFFSET_M, origin[1] + MAX_MANUAL_XY_OFFSET_M),
                _clamp(self.requested[2] + dz, origin[2] + MIN_MANUAL_HEIGHT_M, origin[2] + MAX_MANUAL_HEIGHT_M),
            ]
            candidate_error_xy = math.hypot(candidate[0] - pose.x, candidate[1] - pose.y)
            if candidate_error_xy > 0.90 * _flight_constant("MAX_HORIZONTAL_ERROR_M"):
                self._response(
                    seq,
                    "PREPARED",
                    False,
                    f"el primer paso dejaria un error horizontal de {candidate_error_xy:.3f} m",
                )
                return
        else:
            self._response(seq, "PREPARED", False, f"accion desconocida: {action}")
            return

        self.pending = {"seq": seq, "action": action, "candidate": candidate}
        self._response(seq, "PREPARED", True, candidate=candidate, phase=self.phase)

    def accept_commit(self, message: dict[str, Any]) -> None:
        seq = int(message["seq"])
        if self.pending is None or int(self.pending["seq"]) != seq:
            self._response(seq, "COMMITTED", False, "no existe PREPARE correspondiente")
            return
        self.scheduled = {
            **self.pending,
            "execute_at": float(message.get("execute_at", time.monotonic())),
        }
        self.pending = None

    def cancel(self, seq: int) -> None:
        if self.pending is not None and int(self.pending["seq"]) == seq:
            self.pending = None
        if self.scheduled is not None and int(self.scheduled["seq"]) == seq:
            self.scheduled = None

    def apply_scheduled(self, now: float) -> None:
        if self.scheduled is None or now < float(self.scheduled["execute_at"]):
            return
        transaction = self.scheduled
        self.scheduled = None
        seq = int(transaction["seq"])
        action = str(transaction["action"])
        candidate = list(transaction["candidate"])
        try:
            if action == "DESPEGAR":
                self.requested = candidate
                self.landing_target = None
                self.phase = "TAKEOFF"
                self._motors_stopped = False
                with self.unit.lock:
                    self.unit.airborne = True
                    self.unit.mode = "TAKEOFF"
                    self.unit.status = f"Despegue multiproceso a {candidate[2]:.2f} m"
            elif action == "ATERRIZAR":
                self.landing_target = candidate
                self.phase = "LANDING"
                with self.unit.lock:
                    self.unit.mode = "LANDING"
                    self.unit.status = "Aterrizaje multiproceso"
            elif action == "MOVER":
                if self.phase != "HOVER":
                    raise RuntimeError(f"la fase cambio a {self.phase}")
                self.requested = candidate
            self._response(seq, "COMMITTED", True, action=action, candidate=candidate)
        except Exception as exc:
            self._response(seq, "COMMITTED", False, str(exc), action=action)

    def _target_for_cycle(self, dt: float) -> tuple[str, tuple[float, float, float]] | None:
        with self.unit.lock:
            origin = self.unit.origin
            current_target = None if self.unit.target is None else list(self.unit.target)
        if origin is None or self.requested is None:
            return None
        if self.phase == "TAKEOFF":
            previous_z = origin[2] if current_target is None else current_target[2]
            target = (
                origin[0],
                origin[1],
                min(self.requested[2], previous_z + _flight_constant("TAKEOFF_RATE_M_S") * dt),
            )
            pose = self.unit.fresh_pose()
            ramp_complete = target[2] >= self.requested[2] - 0.001
            physically_settled = (
                pose is not None
                and math.hypot(self.requested[0] - pose.x, self.requested[1] - pose.y)
                <= TAKEOFF_SETTLE_XY_M
                and abs(self.requested[2] - pose.z) <= TAKEOFF_SETTLE_Z_M
            )
            if ramp_complete and physically_settled:
                self.phase = "HOVER"
        elif self.phase == "HOVER":
            target = tuple(self.requested)
        elif self.phase == "LANDING":
            if self.landing_target is None:
                return None
            self.landing_target[2] = max(
                origin[2],
                self.landing_target[2] - _flight_constant("LANDING_RATE_M_S") * dt,
            )
            target = tuple(self.landing_target)
        else:
            return None
        return self.phase, target

    def control_cycle(self, now: float) -> None:
        raw_dt = max(0.0, now - self.previous_time)
        self.control_dt_s = raw_dt
        self.control_max_dt_s = max(self.control_max_dt_s, raw_dt)
        if raw_dt > CONTROL_PERIOD_S * 1.5:
            self.control_overruns += 1
        dt = max(0.001, min(0.15, raw_dt))
        self.previous_time = now
        self.apply_scheduled(now)
        target_data = self._target_for_cycle(dt)
        if target_data is None:
            self.previous_command = (0.0, 0.0, 0.0)
            return

        phase, target = target_data
        pose = self.unit.fresh_pose()
        peer_xyz, peer_age = read_shared_pose(self.peer_pose)
        if pose is None:
            self.abort(f"MoCap sin actualizar por > {_flight_constant('MOCAP_TIMEOUT_S'):.2f} s")
            return
        if peer_xyz is None or peer_age > PEER_TIMEOUT_S:
            self.abort(f"MoCap del otro dron perdido ({peer_age:.2f} s)")
            return
        separation = math.dist(pose.xyz(), peer_xyz)
        if separation < _flight_constant("MIN_SEPARATION_M"):
            self.abort(f"separacion {separation:.2f} m < {_flight_constant('MIN_SEPARATION_M'):.2f} m")
            return

        with self.unit.lock:
            estimate = self.unit.estimate
            mocap_velocity = self.unit.mocap_velocity
            origin = self.unit.origin
            cf = self.unit.cf
        if cf is None or origin is None:
            self.abort("enlace u origen no disponible")
            return
        ekf_error = None if estimate is None else math.dist(estimate.xyz(), pose.xyz())
        if ekf_error is not None and ekf_error > _flight_constant("MAX_EKF_MOCAP_ERROR_M"):
            self.abort(f"EKF-MoCap={ekf_error:.3f} m")
            return

        ex, ey, ez = target[0] - pose.x, target[1] - pose.y, target[2] - pose.z
        if math.hypot(ex, ey) > _flight_constant("MAX_HORIZONTAL_ERROR_M"):
            self.abort(f"error horizontal {math.hypot(ex, ey):.3f} m")
            return
        if pose.z > origin[2] + MAX_MANUAL_HEIGHT_M + _flight_constant("MAX_HEIGHT_OVERSHOOT_M"):
            self.abort("sobrepaso vertical")
            return

        xy_kp = GESTURE_KP_XY if phase == "HOVER" else _flight_constant("KP_XY")
        xy_max_speed = (
            GESTURE_MAX_XY_SPEED_M_S
            if phase == "HOVER"
            else _flight_constant("MAX_XY_SPEED_M_S")
        )
        xy_slew = (
            GESTURE_SLEW_XY_M_S2
            if phase == "HOVER"
            else _flight_constant("COMMAND_SLEW_XY_M_S2")
        )
        damping_kd_xy = (
            _flight_constant("DAMPING_KD_XY_DRON_2")
            if self.unit.name == "Dron 2"
            else 0.0
        )
        measured_vx, measured_vy = (
            (0.0, 0.0)
            if mocap_velocity is None
            else (mocap_velocity[0], mocap_velocity[1])
        )
        requested_command = (
            _clamp(
                xy_kp * _deadband(ex, _flight_constant("XY_DEADBAND_M"))
                - damping_kd_xy * measured_vx,
                -xy_max_speed,
                xy_max_speed,
            ),
            _clamp(
                xy_kp * _deadband(ey, _flight_constant("XY_DEADBAND_M"))
                - damping_kd_xy * measured_vy,
                -xy_max_speed,
                xy_max_speed,
            ),
            _clamp(_flight_constant("KP_Z") * _deadband(ez, _flight_constant("Z_DEADBAND_M")), -_flight_constant("MAX_Z_SPEED_M_S"), _flight_constant("MAX_Z_SPEED_M_S")),
        )
        command = (
            _slew(self.previous_command[0], requested_command[0], xy_slew, dt),
            _slew(self.previous_command[1], requested_command[1], xy_slew, dt),
            _slew(self.previous_command[2], requested_command[2], _flight_constant("COMMAND_SLEW_Z_M_S2"), dt),
        )
        self.previous_command = command
        try:
            cf.commander.send_velocity_world_setpoint(*command, 0.0)
        except Exception as exc:
            self.abort(f"fallo enviando setpoint: {exc}")
            return

        with self.unit.lock:
            self.unit.target = list(target)
            self.unit.error = (ex, ey, ez)
            self.unit.command = command
            self.unit.ekf_mocap_error = ekf_error
            self.unit.separation = separation
            self.unit.mode = phase
            self.unit.status = "Hover multiproceso activo" if phase == "HOVER" else phase

        if (
            phase == "LANDING"
            and target[2] <= origin[2] + 0.002
            and pose.z <= origin[2] + _flight_constant("LANDING_MARGIN_M")
        ):
            self.phase = "LANDED"
            with self.unit.lock:
                self.unit.airborne = False
                self.unit.mode = "LANDED"
                self.unit.status = "Aterrizado"
            try:
                cf.commander.send_stop_setpoint()
            except Exception:
                pass
            self._motors_stopped = True

    def abort(self, reason: str) -> None:
        if self.emergency_event.is_set():
            return
        self.unit.set_abort(reason)
        self.emergency_event.set()
        safe_put(
            self.event_queue,
            {
                "kind": "event",
                "drone": self.unit.name,
                "event": "ABORT",
                "message": reason,
                "timestamp": time.monotonic(),
            },
            important=True,
        )
        with self.unit.lock:
            cf = self.unit.cf
        if cf is not None:
            try:
                cf.commander.send_stop_setpoint()
            except Exception:
                pass

    def stop_motors_once(self) -> None:
        if self._motors_stopped:
            return
        self._motors_stopped = True
        self.phase = "ABORT" if self.emergency_event.is_set() else self.phase
        self.unit.send_stop()

    def snapshot(self) -> dict[str, Any]:
        pose = self.unit.fresh_pose()
        peer_xyz, peer_age = read_shared_pose(self.peer_pose)
        with self.unit.lock:
            estimate = self.unit.estimate
            mocap_velocity = self.unit.mocap_velocity
            origin = self.unit.origin
            target = self.unit.target
            error = self.unit.error
            command = self.unit.command
            return {
                "kind": "state",
                "drone": self.unit.name,
                "pid": os.getpid(),
                "timestamp": time.monotonic(),
                "phase": self.phase,
                "status": self.unit.status,
                "airborne": self.unit.airborne,
                "pose": None if pose is None else list(pose.xyz()),
                "origin": None if origin is None else list(origin),
                "estimate": None if estimate is None else list(estimate.xyz()),
                "requested": None if self.requested is None else list(self.requested),
                "target": None if target is None else list(target),
                "error": None if error is None else list(error),
                "command": None if command is None else list(command),
                "ekf_mocap_error": self.unit.ekf_mocap_error,
                "separation": self.unit.separation,
                "roll_deg": self.unit.roll_deg,
                "pitch_deg": self.unit.pitch_deg,
                "battery_v": self.unit.battery_v,
                "battery_level_pct": self.unit.battery_level_pct,
                "mocap_hz": self.unit.mocap_hz,
                "mocap_velocity": None if mocap_velocity is None else list(mocap_velocity),
                "mocap_age_s": None if pose is None else max(0.0, time.monotonic() - pose.received_at),
                "peer_pose": None if peer_xyz is None else list(peer_xyz),
                "peer_age_s": peer_age,
                "control_dt_s": self.control_dt_s,
                "control_max_dt_s": self.control_max_dt_s,
                "control_overruns": self.control_overruns,
            }


def drone_worker(
    name: str,
    uri: str,
    topic: str,
    command_queue,
    event_queue,
    own_pose,
    peer_pose,
    emergency_event,
    shutdown_event,
) -> None:
    """Punto de entrada del proceso. Solo aqui se inicializa la Crazyradio."""
    unit = None
    controller = None
    try:
        import cflib.crtp
        from cflib.crazyflie import Crazyflie
        from cflib.crazyflie.syncCrazyflie import SyncCrazyflie
        from prueba_estabilidad_dos_drones_lowlevel import DroneUnit

        cflib.crtp.init_drivers(enable_debug_driver=False)
        unit = DroneUnit(name, uri, topic)
        unit.start_mocap()
        safe_put(event_queue, _event(name, "PREFLIGHT", "esperando origen MoCap estable"), important=True)
        unit.wait_for_stable_origin()
        if emergency_event.is_set() or shutdown_event.is_set():
            return

        cache_name = name.replace(" ", "_")
        with SyncCrazyflie(uri, cf=Crazyflie(rw_cache=f"./cache_{cache_name}")) as scf:
            unit.cf = scf.cf
            try:
                unit.configure()
                unit.wait_for_ekf_alignment()
                controller = WorkerController(unit, own_pose, peer_pose, emergency_event, event_queue)
                pose = unit.fresh_pose()
                write_shared_pose(own_pose, pose)
                safe_put(event_queue, _event(name, "READY", "radio, MoCap y EKF listos", state=controller.snapshot()), important=True)

                next_control = time.monotonic()
                next_state = time.monotonic()
                while not shutdown_event.is_set():
                    now = time.monotonic()
                    pose = unit.fresh_pose()
                    write_shared_pose(own_pose, pose)

                    while True:
                        try:
                            message = command_queue.get_nowait()
                        except queue.Empty:
                            break
                        kind = message.get("kind")
                        if kind == "PREPARE":
                            controller.prepare(message)
                        elif kind == "COMMIT":
                            controller.accept_commit(message)
                        elif kind == "CANCEL":
                            controller.cancel(int(message["seq"]))
                        elif kind == "EMERGENCY":
                            emergency_event.set()
                        elif kind == "SHUTDOWN":
                            shutdown_event.set()

                    if emergency_event.is_set():
                        controller.stop_motors_once()
                    elif now >= next_control:
                        controller.control_cycle(now)
                        next_control = now + CONTROL_PERIOD_S
                    if now >= next_state:
                        safe_put(event_queue, controller.snapshot())
                        next_state = now + STATE_PERIOD_S
                    time.sleep(0.002)
            finally:
                # El stop debe enviarse antes de que SyncCrazyflie cierre el
                # enlace; hacerlo en el finally exterior seria demasiado tarde.
                if controller is not None:
                    controller.stop_motors_once()
                # Detener tambien el bloque de log antes de desconectar evita
                # callbacks tardios de cflib ("no LogEntry to handle").
                unit.stop_ekf_log()
    except Exception as exc:
        emergency_event.set()
        safe_put(
            event_queue,
            _event(name, "WORKER_FAILED", str(exc), traceback=traceback.format_exc()),
            important=True,
        )
    finally:
        if controller is not None:
            safe_put(event_queue, controller.snapshot())
        if unit is not None:
            unit.stop_ekf_log()
            unit.stop_mocap()
        safe_put(event_queue, _event(name, "STOPPED", "proceso de vuelo finalizado"), important=True)


def _event(drone: str, event: str, message: str, **extra) -> dict[str, Any]:
    return {
        "kind": "event",
        "drone": drone,
        "pid": os.getpid(),
        "event": event,
        "message": message,
        "timestamp": time.monotonic(),
        **extra,
    }


def _flight_constant(name: str) -> float:
    # Import diferido: el proceso de camara nunca carga cflib ni este modulo.
    from prueba_estabilidad_dos_drones_lowlevel import __dict__ as constants

    return float(constants[name])


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _deadband(value: float, threshold: float) -> float:
    return 0.0 if abs(value) <= threshold else value


def _slew(previous: float, requested: float, acceleration: float, dt: float) -> float:
    return previous + _clamp(requested - previous, -acceleration * dt, acceleration * dt)
