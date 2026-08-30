r"""Backend Python/cflib para dos Crazyflies con control high-level.

Este proceso es el unico dueno de las Crazyradio, alimenta el EKF con Robotat y
conserva los bloqueos de seguridad. El modo ``--dry-run`` permite probar toda
la logica sin hardware. El servidor JSON queda disponible para diagnósticos,
pero la interfaz normal es completamente Python.

Ejemplos:
    python .\drone_control\cruz_highlevel_backend.py --dry-run
    python .\drone_control\cruz_highlevel_backend.py
"""

from __future__ import annotations

import argparse
import math
import socket
import sys
import threading
import time
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit


MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from cruz_highlevel_protocol import Command, ProtocolError, decode_command, encode_response


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8766
DEFAULT_URI_1 = "radio://2B1D933FCC/84/2M/E7E7E7E7E4"
DEFAULT_URI_2 = "radio://9DD2507072/90/2M/E7E7E7E7E5"
DEFAULT_TOPIC_1 = "mocap/drone3"
DEFAULT_TOPIC_2 = "mocap/drone4"

TAKEOFF_RELATIVE_M = 0.35
TAKEOFF_DURATION_S = 5.0
GOTO_DURATION_XY_S = 3.0
GOTO_DURATION_Z_S = 4.0
LAND_HEIGHT_M = 0.03
LAND_DURATION_S = 4.0
MIN_SEPARATION_M = 0.70
EMERGENCY_SEPARATION_M = 0.50
MAX_HORIZONTAL_FROM_ORIGIN_M = 0.50
MIN_TARGET_Z_M = 0.20
MAX_TARGET_Z_M = 1.10
MAX_EKF_MOCAP_ERROR_M = 0.15

Emitter = Callable[[bool, str, str, dict[str, Any] | None], None]


class BridgeError(RuntimeError):
    """Operacion rechazada por estado o seguridad."""


def _selected(command: Command) -> tuple[str, ...]:
    if command.target == "both":
        return ("drone1", "drone2")
    return (command.target,)


class SimulatedBackend:
    """Backend determinista para verificar la interfaz sin radios ni motores."""

    def __init__(self, single: str | None = None) -> None:
        self.active_keys = (single,) if single else ("drone1", "drone2")
        self.connected = False
        self.ready = False
        self.emergency_latched = False
        self.emergency_reason: str | None = None
        self.units = {
            "drone1": self._unit("Dron 1", 0.0, 0.0, 0.05),
            "drone2": self._unit("Dron 2", 0.0, 0.90, 0.05),
        }
        for key, unit in self.units.items():
            unit["enabled"] = key in self.active_keys
            if key not in self.active_keys:
                unit["status"] = "Deshabilitado en modo de un dron"

    def _selected(self, command: Command) -> tuple[str, ...]:
        keys = self.active_keys if command.target == "both" else (command.target,)
        if any(key not in self.active_keys for key in keys):
            raise BridgeError("el dron seleccionado esta deshabilitado")
        return keys

    @staticmethod
    def _unit(name: str, x: float, y: float, z: float) -> dict[str, Any]:
        return {
            "name": name,
            "ready": False,
            "airborne": False,
            "status": "Simulacion desconectada",
            "pose": [x, y, z],
            "target": [x, y, z],
            "origin": [x, y, z],
            "battery_v": 4.05,
            "mocap_age_s": 0.0,
            "ekf_mocap_error_m": 0.0,
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            "mode": "dry-run",
            "connected": self.connected,
            "ready": self.ready,
            "emergency": self.emergency_latched,
            "emergency_reason": self.emergency_reason,
            "separation_m": None if len(self.active_keys) < 2 else round(
                math.dist(self.units["drone1"]["pose"], self.units["drone2"]["pose"]), 3
            ),
            "drone1": dict(self.units["drone1"]),
            "drone2": dict(self.units["drone2"]),
            "log_path": None,
        }

    def connect(self, emit: Emitter) -> None:
        if self.emergency_latched:
            raise BridgeError("reinicia el puente despues de una emergencia")
        emit(True, "progress", "Simulando MoCap, radios y alineacion EKF...", self.snapshot())
        time.sleep(0.15)
        self.connected = self.ready = True
        for key in self.active_keys:
            unit = self.units[key]
            unit["ready"] = True
            unit["status"] = "Listo (simulado)"

    def takeoff(self, command: Command) -> None:
        self._require_ready()
        for key in self._selected(command):
            unit = self.units[key]
            if unit["airborne"]:
                raise BridgeError(f"{unit['name']} ya esta en vuelo")
        for key in self._selected(command):
            unit = self.units[key]
            unit["target"] = [unit["pose"][0], unit["pose"][1], unit["origin"][2] + TAKEOFF_RELATIVE_M]
            unit["pose"] = list(unit["target"])
            unit["airborne"] = True
            unit["status"] = "Hover high-level (simulado)"

    def move(self, command: Command) -> None:
        self._require_ready()
        keys = self._selected(command)
        candidates: dict[str, list[float]] = {}
        for key in keys:
            unit = self.units[key]
            if not unit["airborne"]:
                raise BridgeError(f"{unit['name']}: despega antes de mover")
            candidates[key] = [
                unit["target"][0] + command.dx,
                unit["target"][1] + command.dy,
                unit["target"][2] + command.dz,
            ]
            self._validate_target(key, candidates[key])
        if len(candidates) == 2 and math.dist(candidates["drone1"], candidates["drone2"]) < MIN_SEPARATION_M:
            raise BridgeError(f"movimiento bloqueado: separacion menor de {MIN_SEPARATION_M:.2f} m")
        for key, candidate in candidates.items():
            unit = self.units[key]
            unit["target"] = unit["pose"] = candidate
            unit["status"] = "Objetivo high-level alcanzado (simulado)"

    def land(self, command: Command) -> None:
        for key in self._selected(command):
            unit = self.units[key]
            unit["target"] = list(unit["origin"])
            unit["pose"] = list(unit["origin"])
            unit["airborne"] = False
            unit["status"] = "Aterrizado (simulado)"

    def emergency(self, reason: str = "orden manual") -> None:
        self.emergency_latched = True
        self.emergency_reason = reason
        self.ready = False
        for unit in self.units.values():
            unit["airborne"] = False
            unit["ready"] = False
            unit["status"] = f"EMERGENCIA (simulada): {reason}"

    def close(self) -> None:
        self.connected = self.ready = False

    def _require_ready(self) -> None:
        if self.emergency_latched:
            raise BridgeError("emergencia enclavada; reinicia el puente")
        if not self.ready:
            raise BridgeError("ejecuta PREFLIGHT antes de enviar comandos")

    def _validate_target(self, key: str, candidate: list[float]) -> None:
        unit = self.units[key]
        origin = unit["origin"]
        if math.hypot(candidate[0] - origin[0], candidate[1] - origin[1]) > MAX_HORIZONTAL_FROM_ORIGIN_M:
            raise BridgeError("objetivo fuera del radio horizontal permitido")
        if not MIN_TARGET_Z_M <= candidate[2] <= MAX_TARGET_Z_M:
            raise BridgeError("objetivo fuera del rango vertical permitido")
        if len(self.active_keys) > 1:
            other_key = "drone2" if key == "drone1" else "drone1"
            if math.dist(candidate, self.units[other_key]["pose"]) < MIN_SEPARATION_M:
                raise BridgeError(f"movimiento bloqueado: separacion menor de {MIN_SEPARATION_M:.2f} m")


class HardwareBackend:
    """Backend cflib persistente; solo esta clase toca las Crazyradio."""

    def __init__(self, args: argparse.Namespace) -> None:
        # Importaciones diferidas: --dry-run funciona incluso sin cflib/paho.
        import cflib.crtp as crtp
        from cflib.crazyflie import Crazyflie
        from cflib.crazyflie.syncCrazyflie import SyncCrazyflie
        from dual_flight_logger import DualFlightLogger
        from prueba_estabilidad_dos_drones_lowlevel import DroneUnit

        self._crtp = crtp
        self._Crazyflie = Crazyflie
        self._SyncCrazyflie = SyncCrazyflie
        self._logger = DualFlightLogger(
            folder_name="datos_dos_drones",
            filename_prefix="python_highlevel_cruz",
        )
        self.units = {
            "drone1": DroneUnit("Dron 1", args.uri1, args.topic1),
            "drone2": DroneUnit("Dron 2", args.uri2, args.topic2),
        }
        self.active_keys = (args.single,) if getattr(args, "single", None) else ("drone1", "drone2")
        self.connected = False
        self.ready = False
        self.emergency_latched = False
        self.emergency_reason: str | None = None
        self._stack: ExitStack | None = None
        self._stop_event = threading.Event()
        self._monitor_thread: threading.Thread | None = None
        self._state_lock = threading.RLock()
        self._closing = False
        self.analysis_path: Path | None = None

    def _selected(self, command: Command) -> tuple[str, ...]:
        keys = self.active_keys if command.target == "both" else (command.target,)
        if any(key not in self.active_keys for key in keys):
            raise BridgeError("el dron seleccionado esta deshabilitado")
        return keys

    def connect(self, emit: Emitter) -> None:
        with self._state_lock:
            if self.emergency_latched:
                raise BridgeError("reinicia el puente despues de una emergencia")
            if self.ready:
                return
        try:
            emit(True, "progress", "Esperando origen Robotat estable...", self.snapshot())
            for key in self.active_keys:
                unit = self.units[key]
                unit.start_mocap()
            origins = [self.units[key].wait_for_stable_origin() for key in self.active_keys]
            separation = None if len(origins) == 1 else math.dist(origins[0], origins[1])
            if separation is not None and separation < MIN_SEPARATION_M:
                raise BridgeError(
                    f"separacion inicial {separation:.2f} m; se requieren {MIN_SEPARATION_M:.2f} m"
                )

            emit(True, "progress", "Resolviendo Crazyradio por serial...", self.snapshot())
            resolved = self._resolve_uris()
            for key, uri in resolved.items():
                self.units[key].uri = uri

            self._crtp.init_drivers(enable_debug_driver=False)
            stack = ExitStack()
            self._stack = stack
            links = []
            emit(True, "progress", "Abriendo enlaces de radio; motores aun apagados...", self.snapshot())
            for key in self.active_keys:
                unit = self.units[key]
                cache = f"./cache_{unit.name.replace(' ', '_')}"
                link = stack.enter_context(
                    self._SyncCrazyflie(unit.uri, cf=self._Crazyflie(rw_cache=cache))
                )
                links.append(link)
            for key, link in zip(self.active_keys, links):
                unit = self.units[key]
                with unit.lock:
                    unit.cf = link.cf

            emit(True, "progress", "Configurando controlador high-level y alineando EKF...", self.snapshot())
            for key in self.active_keys:
                unit = self.units[key]
                self._configure_highlevel(unit)
            for key in self.active_keys:
                unit = self.units[key]
                unit.wait_for_ekf_alignment()
            path = self._logger.start()
            detail = "modo_un_dron" if separation is None else f"separacion={separation:.3f} m"
            self._logger.event("SISTEMA", "PREFLIGHT_HIGHLEVEL_OK", detail)
            with self._state_lock:
                self.connected = self.ready = True
            self._start_monitor()
            emit(True, "progress", f"Preflight correcto. CSV: {path}", self.snapshot())
        except Exception:
            self._cleanup_links()
            raise

    def _configure_highlevel(self, unit: Any) -> None:
        with unit.lock:
            cf = unit.cf
            unit.status = "Configurando high-level"
        if cf is None or unit.fresh_pose() is None:
            raise BridgeError(f"{unit.name}: falta enlace o MoCap fresco")
        cf.param.set_value("commander.enHighLevel", "1")
        cf.param.set_value("stabilizer.controller", "1")
        cf.param.set_value("stabilizer.estimator", "2")
        cf.param.set_value("kalman.resetEstimation", "1")
        time.sleep(0.10)
        cf.param.set_value("kalman.resetEstimation", "0")
        unit._start_ekf_log(cf)
        with unit.lock:
            unit.status = "EKF high-level estabilizando"
            unit.mode = "PREFLIGHT_HIGHLEVEL"

    def takeoff(self, command: Command) -> None:
        self._require_ready()
        keys = self._selected(command)
        poses = {key: self.units[key].fresh_pose() for key in keys}
        if any(pose is None for pose in poses.values()):
            raise BridgeError("MoCap no esta fresco en todos los drones seleccionados")
        for key in keys:
            unit = self.units[key]
            with unit.lock:
                if unit.airborne:
                    raise BridgeError(f"{unit.name} ya esta en vuelo")
        self._require_safe_separation()
        prepared: list[tuple[Any, float]] = []
        for key in keys:
            unit = self.units[key]
            pose = poses[key]
            target_z = min(pose.z + TAKEOFF_RELATIVE_M, MAX_TARGET_Z_M)
            with unit.lock:
                unit.target = [pose.x, pose.y, target_z]
                unit.airborne = True
                unit.mode = "TAKEOFF_HIGHLEVEL"
                unit.status = f"Despegando high-level a {target_z:.2f} m"
                prepared.append((unit, target_z))
        try:
            for unit, target_z in prepared:
                unit.cf.high_level_commander.takeoff(target_z, TAKEOFF_DURATION_S)
                self._logger.event(unit.name, "TAKEOFF_HIGHLEVEL", unit.status)
        except Exception as exc:
            self.emergency(f"fallo enviando takeoff: {exc}")
            raise BridgeError(f"fallo enviando takeoff: {exc}") from exc

    def move(self, command: Command) -> None:
        self._require_ready()
        keys = self._selected(command)
        candidates: dict[str, list[float]] = {}
        for key in keys:
            unit = self.units[key]
            with unit.lock:
                if not unit.airborne or unit.target is None:
                    raise BridgeError(f"{unit.name}: despega antes de mover")
                candidates[key] = [
                    unit.target[0] + command.dx,
                    unit.target[1] + command.dy,
                    unit.target[2] + command.dz,
                ]
            self._validate_target(key, candidates[key])
        if len(candidates) == 2 and math.dist(candidates["drone1"], candidates["drone2"]) < MIN_SEPARATION_M:
            raise BridgeError(f"movimiento bloqueado: separacion menor de {MIN_SEPARATION_M:.2f} m")
        duration = GOTO_DURATION_Z_S if abs(command.dz) > 1e-9 else GOTO_DURATION_XY_S
        try:
            for key in keys:
                unit = self.units[key]
                unit.cf.high_level_commander.go_to(*candidates[key], 0.0, duration, relative=False)
        except Exception as exc:
            self.emergency(f"fallo enviando go_to: {exc}")
            raise BridgeError(f"fallo enviando go_to: {exc}") from exc
        for key in keys:
            unit = self.units[key]
            candidate = candidates[key]
            with unit.lock:
                unit.target = candidate
                unit.mode = "GOTO_HIGHLEVEL"
                unit.status = f"Objetivo ({candidate[0]:+.2f}, {candidate[1]:+.2f}, {candidate[2]:+.2f})"
            self._logger.event(unit.name, "GOTO_HIGHLEVEL", unit.status)

    def land(self, command: Command) -> None:
        keys = self._selected(command)
        for key in keys:
            unit = self.units[key]
            with unit.lock:
                if unit.cf is None or not unit.airborne:
                    continue
                unit.mode = "LANDING_HIGHLEVEL"
                unit.status = "Aterrizando high-level"
                unit.target = [unit.target[0], unit.target[1], LAND_HEIGHT_M]
            try:
                unit.cf.high_level_commander.land(LAND_HEIGHT_M, LAND_DURATION_S)
                self._logger.event(unit.name, "LAND_HIGHLEVEL", unit.status)
            except Exception as exc:
                self.emergency(f"fallo enviando land: {exc}")
                raise BridgeError(f"fallo enviando land: {exc}") from exc
            threading.Timer(LAND_DURATION_S + 0.5, self._mark_landed, args=(unit,)).start()

    @staticmethod
    def _mark_landed(unit: Any) -> None:
        with unit.lock:
            unit.airborne = False
            unit.mode = "LANDED"
            unit.status = "Aterrizado"

    def emergency(self, reason: str = "orden manual") -> None:
        with self._state_lock:
            if self.emergency_latched:
                return
            self.emergency_latched = True
            self.emergency_reason = reason
            self.ready = False
        self._logger.event("SISTEMA", "EMERGENCIA_HIGHLEVEL", reason)
        for key in self.active_keys:
            unit = self.units[key]
            with unit.lock:
                cf = unit.cf
                unit.airborne = False
                unit.mode = "EMERGENCY"
                unit.status = f"EMERGENCIA: {reason}"
            if cf is None:
                continue
            try:
                cf.high_level_commander.stop()
            except Exception:
                pass
            for _ in range(10):
                try:
                    cf.commander.send_stop_setpoint()
                except Exception:
                    pass
                time.sleep(0.02)

    def snapshot(self) -> dict[str, Any]:
        snapshots = {key: self._unit_snapshot(unit) for key, unit in self.units.items()}
        for key, unit_snapshot in snapshots.items():
            unit_snapshot["enabled"] = key in self.active_keys
            if key not in self.active_keys:
                unit_snapshot["status"] = "Deshabilitado en modo de un dron"
        poses = [snapshots[key]["pose"] for key in self.active_keys]
        separation = None if len(poses) < 2 or any(pose is None for pose in poses) else math.dist(*poses)
        return {
            "mode": "hardware",
            "connected": self.connected,
            "ready": self.ready,
            "emergency": self.emergency_latched,
            "emergency_reason": self.emergency_reason,
            "separation_m": separation,
            "drone1": snapshots["drone1"],
            "drone2": snapshots["drone2"],
            "log_path": None if self._logger.path is None else str(self._logger.path),
        }

    @staticmethod
    def _unit_snapshot(unit: Any) -> dict[str, Any]:
        with unit.lock:
            now = time.monotonic()
            pose = unit.pose
            estimate = unit.estimate
            if pose is not None and estimate is not None:
                unit.ekf_mocap_error = math.dist(pose.xyz(), estimate.xyz())
            if pose is not None and unit.target is not None:
                unit.error = tuple(target - current for target, current in zip(unit.target, pose.xyz()))
            return {
                "name": unit.name,
                "ready": unit.cf is not None,
                "airborne": unit.airborne,
                "status": unit.status,
                "pose": None if pose is None else list(pose.xyz()),
                "target": None if unit.target is None else list(unit.target),
                "origin": None if unit.origin is None else list(unit.origin),
                "battery_v": unit.battery_v,
                "battery_level_pct": unit.battery_level_pct,
                "mocap_age_s": None if pose is None else now - pose.received_at,
                "mocap_hz": unit.mocap_hz,
                "ekf_mocap_error_m": unit.ekf_mocap_error,
            }

    def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        try:
            if any(self.units[key].airborne for key in self.active_keys) and not self.emergency_latched:
                self.land(Command("land", "both"))
                time.sleep(LAND_DURATION_S + 0.6)
        finally:
            self._stop_event.set()
            self._cleanup_links()

    def _cleanup_links(self) -> None:
        for key in self.active_keys:
            unit = self.units[key]
            unit.stop_ekf_log()
            unit.stop_mocap()
            with unit.lock:
                unit.cf = None
        if self._stack is not None:
            try:
                self._stack.close()
            except Exception:
                pass
            self._stack = None
        self.connected = self.ready = False
        self._logger.stop()
        self.analysis_path = self._logger.analysis_path

    def _start_monitor(self) -> None:
        self._stop_event.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, name="HighLevelSafetyMonitor", daemon=True
        )
        self._monitor_thread.start()

    def _monitor_loop(self) -> None:
        while not self._stop_event.wait(0.10):
            poses = [self.units[key].fresh_pose() for key in self.active_keys]
            separation = (
                None
                if len(poses) < 2 or any(pose is None for pose in poses)
                else math.dist(poses[0].xyz(), poses[1].xyz())
            )
            for key in self.active_keys:
                unit = self.units[key]
                with unit.lock:
                    unit.separation = separation
            for key in self.active_keys:
                unit = self.units[key]
                self._logger.sample(unit)
            if not any(self.units[key].airborne for key in self.active_keys):
                continue
            try:
                self._watchdog_check()
            except BridgeError as exc:
                print(f"WATCHDOG: {exc}", flush=True)
                self.emergency(str(exc))
                return

    def _watchdog_check(self) -> None:
        for key in self.active_keys:
            unit = self.units[key]
            if not unit.airborne:
                continue
            pose = unit.fresh_pose()
            if pose is None:
                raise BridgeError(f"{unit.name}: Robotat dejo de actualizar")
            with unit.lock:
                estimate = unit.estimate
            if estimate is not None:
                error = math.dist(pose.xyz(), estimate.xyz())
                if error > MAX_EKF_MOCAP_ERROR_M:
                    raise BridgeError(f"{unit.name}: EKF-MoCap={error:.3f} m")
        self._require_safe_separation(emergency_limit=True)

    def _require_ready(self) -> None:
        if self.emergency_latched:
            raise BridgeError("emergencia enclavada; reinicia el puente")
        if not self.ready:
            raise BridgeError("ejecuta PREFLIGHT antes de enviar comandos")

    def _require_safe_separation(self, *, emergency_limit: bool = False) -> None:
        if len(self.active_keys) < 2:
            return
        poses = [self.units[key].fresh_pose() for key in self.active_keys]
        if any(pose is None for pose in poses):
            raise BridgeError("no hay pose fresca de ambos drones")
        separation = math.dist(poses[0].xyz(), poses[1].xyz())
        limit = EMERGENCY_SEPARATION_M if emergency_limit else MIN_SEPARATION_M
        if separation < limit:
            raise BridgeError(f"separacion {separation:.2f} m < {limit:.2f} m")

    def _validate_target(self, key: str, candidate: list[float]) -> None:
        unit = self.units[key]
        with unit.lock:
            origin = unit.origin
        if origin is None:
            raise BridgeError("origen no definido")
        if math.hypot(candidate[0] - origin[0], candidate[1] - origin[1]) > MAX_HORIZONTAL_FROM_ORIGIN_M:
            raise BridgeError("objetivo fuera del radio horizontal permitido")
        if not MIN_TARGET_Z_M <= candidate[2] <= MAX_TARGET_Z_M:
            raise BridgeError("objetivo fuera del rango vertical permitido")
        if len(self.active_keys) < 2:
            return
        other_key = "drone2" if key == "drone1" else "drone1"
        other = self.units[other_key].fresh_pose()
        if other is None:
            raise BridgeError("sin pose fresca del otro dron")
        if math.dist(candidate, other.xyz()) < MIN_SEPARATION_M:
            raise BridgeError(f"movimiento bloqueado: separacion menor de {MIN_SEPARATION_M:.2f} m")

    def _resolve_uris(self) -> dict[str, str]:
        configured = {key: self.units[key].uri for key in self.active_keys}
        serial_names = {
            key: urlsplit(uri).netloc.upper()
            for key, uri in configured.items()
            if not urlsplit(uri).netloc.isdigit()
        }
        serials: tuple[str, ...] = ()
        fallback_to_order = False
        if serial_names:
            from cflib.drivers.crazyradio import _find_devices, get_serials

            try:
                serials = tuple(serial.upper() for serial in get_serials())
            except Exception as exc:
                devices = tuple(_find_devices())
                if len(devices) == 2 and len(serial_names) == 2:
                    fallback_to_order = True
                    print(
                        "ADVERTENCIA USB: no se leyeron seriales; se usaran indices 0 y 1. "
                        f"Detalle: {exc}",
                        flush=True,
                    )
                else:
                    raise BridgeError(
                        f"no se pudieron resolver las Crazyradio; detectadas={len(devices)}: {exc}"
                    ) from exc
        resolved: dict[str, str] = {}
        for index, (key, uri) in enumerate(configured.items()):
            parts = urlsplit(uri)
            if parts.netloc.isdigit():
                resolved[key] = uri
                continue
            serial = serial_names[key]
            if fallback_to_order:
                usb_index = index
            elif serial in serials:
                usb_index = serials.index(serial)
            else:
                raise BridgeError(f"Crazyradio {serial} no encontrada; detectadas={serials or 'ninguna'}")
            resolved[key] = urlunsplit(
                (parts.scheme, str(usb_index), parts.path, parts.query, parts.fragment)
            )
            print(f"{self.units[key].name}: Crazyradio {serial} -> USB {usb_index}", flush=True)
        if len(self.active_keys) == 2 and len({urlsplit(uri).netloc for uri in resolved.values()}) != 2:
            raise BridgeError("ambos drones quedaron asignados a la misma Crazyradio")
        return resolved


class JsonLineServer:
    def __init__(self, host: str, port: int, backend: Any) -> None:
        self.host = host
        self.port = port
        self.backend = backend
        self._client: socket.socket | None = None
        self._send_lock = threading.Lock()
        self._shutdown = False

    def serve(self) -> None:
        self._start_keyboard_emergency()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((self.host, self.port))
            server.listen(1)
            print(f"Backend high-level escuchando en {self.host}:{self.port}", flush=True)
            print("Q/Ctrl+C o el boton EMERGENCIA detienen los motores.", flush=True)
            while not self._shutdown:
                client, address = server.accept()
                print(f"Cliente local conectado desde {address[0]}:{address[1]}", flush=True)
                with client:
                    self._client = client
                    self._send(True, "hello", "Puente conectado; ejecuta PREFLIGHT.", self.backend.snapshot())
                    self._serve_client(client)
                    self._client = None
                if not self._shutdown and self._is_airborne():
                    print("El cliente se desconecto durante el vuelo: aterrizaje automatico.", flush=True)
                    try:
                        self.backend.land(Command("land", "both"))
                    except Exception as exc:
                        print(f"Fallo el aterrizaje automatico: {exc}; EMERGENCIA.", flush=True)
                        self.backend.emergency()
        self.backend.close()

    def _serve_client(self, client: socket.socket) -> None:
        buffer = b""
        while not self._shutdown:
            chunk = client.recv(4096)
            if not chunk:
                return
            buffer += chunk
            while b"\n" in buffer:
                raw, buffer = buffer.split(b"\n", 1)
                if raw.strip():
                    self._handle(raw.decode("utf-8", errors="replace"))

    def _is_airborne(self) -> bool:
        snapshot = self.backend.snapshot()
        return bool(snapshot["drone1"]["airborne"] or snapshot["drone2"]["airborne"])

    def _start_keyboard_emergency(self) -> None:
        if sys.platform != "win32":
            return

        def watch() -> None:
            import _thread
            import msvcrt

            while not self._shutdown:
                if msvcrt.kbhit():
                    key = msvcrt.getch().lower()
                    if key == b"q":
                        print("\nEMERGENCIA por teclado Q.", flush=True)
                        self.backend.emergency()
                    elif key == b"\x03":
                        # El lector msvcrt consume Ctrl+C. Lo reinyectamos en
                        # el hilo principal para conservar el cierre normal.
                        _thread.interrupt_main()
                time.sleep(0.02)

        threading.Thread(target=watch, name="KeyboardEmergency", daemon=True).start()

    def _handle(self, line: str) -> None:
        try:
            command = decode_command(line)
            if command.action == "connect":
                self.backend.connect(self._send)
                message = "Preflight correcto; control high-level listo."
            elif command.action == "takeoff":
                self.backend.takeoff(command)
                message = "Takeoff high-level enviado."
            elif command.action == "move":
                self.backend.move(command)
                message = "go_to high-level enviado."
            elif command.action == "land":
                self.backend.land(command)
                message = "Land high-level enviado."
            elif command.action == "emergency":
                self.backend.emergency()
                message = "EMERGENCIA enviada; reinicia el puente para reconectar."
            elif command.action == "shutdown":
                message = "Cerrando puente de forma segura."
                self._shutdown = True
            else:
                message = "Estado actualizado."
            self._send(True, command.action, message, self.backend.snapshot())
        except (ProtocolError, BridgeError, RuntimeError, OSError) as exc:
            self._send(False, "error", str(exc), self.backend.snapshot())
        except Exception as exc:
            self._send(False, "error", f"fallo inesperado: {exc}", self.backend.snapshot())

    def _send(
        self,
        ok: bool,
        event: str,
        message: str,
        snapshot: dict[str, Any] | None = None,
    ) -> None:
        client = self._client
        if client is None:
            return
        try:
            with self._send_lock:
                client.sendall(
                    encode_response(ok=ok, event=event, message=message, snapshot=snapshot)
                )
        except OSError:
            pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backend Python para control high-level de dos Crazyflies")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--uri1", default=DEFAULT_URI_1)
    parser.add_argument("--uri2", default=DEFAULT_URI_2)
    parser.add_argument("--topic1", default=DEFAULT_TOPIC_1)
    parser.add_argument("--topic2", default=DEFAULT_TOPIC_2)
    parser.add_argument("--single", choices=("drone1", "drone2"), help="habilita solamente un dron")
    parser.add_argument("--dry-run", action="store_true", help="simula radios y Robotat; nunca arma motores")
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost"}:
        parser.error("por seguridad, --host solo puede ser 127.0.0.1 o localhost")
    if not 1024 <= args.port <= 65535:
        parser.error("--port debe estar entre 1024 y 65535")
    return args


def main() -> int:
    args = parse_args()
    backend = SimulatedBackend(args.single) if args.dry_run else HardwareBackend(args)
    print("MODO SIMULADO: no se abrira hardware." if args.dry_run else "MODO HARDWARE: preflight no despega automaticamente.", flush=True)
    try:
        JsonLineServer(args.host, args.port, backend).serve()
        return 0
    except KeyboardInterrupt:
        print("\nInterrupcion: EMERGENCIA y cierre seguro.", flush=True)
        backend.emergency()
        backend.close()
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
