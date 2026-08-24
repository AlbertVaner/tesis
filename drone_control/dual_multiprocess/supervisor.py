"""Supervisor principal del control gestual multiproceso."""

from __future__ import annotations

import argparse
import ctypes
import csv
import math
import multiprocessing as mp
import msvcrt
import os
import queue
import time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .camera_worker import camera_worker
from .drone_worker import drone_worker
from .protocol import (
    GESTURE_MAX_AGE_S,
    GESTURE_MOVES,
    GESTURE_SETTLE_XY_M,
    GESTURE_SETTLE_Z_M,
    MIN_SEPARATION_M,
    SYNCHRONIZED_DELAY_S,
    TRANSACTION_TIMEOUT_S,
)


DEFAULT_URI_1 = "radio://2B1D933FCC/84/2M/E7E7E7E7E4"
DEFAULT_URI_2 = "radio://9DD2507072/90/2M/E7E7E7E7E5"
DEFAULT_TOPIC_1 = "mocap/drone3"
DEFAULT_TOPIC_2 = "mocap/drone4"
DEFAULT_CAMERA_INDEX = 0
READY_TIMEOUT_S = 45.0
INSTANCE_MUTEX_NAME = "Local\\TesisCrazyflieDualMultiprocess"


CSV_COLUMNS = [
    "fecha_hora", "tiempo_s", "kind", "source", "pid", "drone", "event", "message",
    "seq", "stage", "ok", "mode", "hand", "raw", "filtered", "command_name",
    "phase", "status", "airborne",
    "pose_x", "pose_y", "pose_z", "origin_x", "origin_y", "origin_z",
    "requested_x", "requested_y", "requested_z", "target_x", "target_y", "target_z",
    "error_x", "error_y", "error_z", "command_x", "command_y", "command_z",
    "estimate_x", "estimate_y", "estimate_z", "ekf_mocap_error", "separation",
    "roll_deg", "pitch_deg", "battery_v", "battery_level_pct", "mocap_hz",
    "mocap_age_s", "mocap_vx_m_s", "mocap_vy_m_s", "mocap_vz_m_s",
    "peer_age_s", "control_dt_s", "control_max_dt_s",
    "control_overruns", "camera_fps", "traceback",
]


class SessionLogger:
    """Unico escritor de disco de la arquitectura multiproceso."""

    def __init__(self) -> None:
        folder = Path(__file__).resolve().parents[1] / "datos_dos_drones"
        folder.mkdir(exist_ok=True)
        self.path = folder / f"multiprocessing_dos_drones_{datetime.now():%Y%m%d_%H%M%S}.csv"
        self._file = self.path.open("w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        self._writer.writeheader()
        self._start = time.monotonic()
        self._rows_since_flush = 0

    def write(self, message: dict[str, Any], source: str) -> None:
        row: dict[str, Any] = {
            "fecha_hora": datetime.now().isoformat(timespec="milliseconds"),
            "tiempo_s": time.monotonic() - self._start,
            "source": source,
            **message,
        }
        if "command" in message and isinstance(message["command"], str):
            row["command_name"] = message["command"]
        for key in ("pose", "origin", "requested", "target", "error", "estimate"):
            _flatten_xyz(row, key, message.get(key))
        velocity = message.get("mocap_velocity")
        if isinstance(velocity, (list, tuple)) and len(velocity) == 3:
            row["mocap_vx_m_s"], row["mocap_vy_m_s"], row["mocap_vz_m_s"] = velocity
        if isinstance(message.get("command"), (list, tuple)):
            _flatten_xyz(row, "command", message.get("command"))
        self._writer.writerow({column: _csv_value(row.get(column)) for column in CSV_COLUMNS})
        self._rows_since_flush += 1
        if self._rows_since_flush >= 20 or message.get("kind") != "state":
            self._file.flush()
            self._rows_since_flush = 0

    def close(self) -> None:
        self._file.flush()
        self._file.close()


class SingleInstanceGuard:
    """Impide que dos supervisores reclamen las mismas radios en Windows."""

    def __init__(self, name: str) -> None:
        self._handle = None
        self.acquired = True
        if os.name != "nt":
            return
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.CreateMutexW(None, True, name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self._handle = handle
        self.acquired = ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS
        if not self.acquired:
            kernel32.CloseHandle(handle)
            self._handle = None

    def close(self) -> None:
        if self._handle is None or os.name != "nt":
            return
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.ReleaseMutex.argtypes = (wintypes.HANDLE,)
        kernel32.ReleaseMutex.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.ReleaseMutex(self._handle)
        kernel32.CloseHandle(self._handle)
        self._handle = None


class Supervisor:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.context = mp.get_context("spawn")
        self.flight_events = self.context.Queue(maxsize=1024)
        self.gestures = self.context.Queue(maxsize=512)
        self.commands = {
            "Dron 1": self.context.Queue(maxsize=64),
            "Dron 2": self.context.Queue(maxsize=64),
        }
        nan = float("nan")
        self.shared_pose = {
            "Dron 1": self.context.Array("d", [nan, nan, nan, 0.0], lock=True),
            "Dron 2": self.context.Array("d", [nan, nan, nan, 0.0], lock=True),
        }
        self.emergency_event = self.context.Event()
        self.shutdown_event = self.context.Event()
        self.latest: dict[str, dict[str, Any]] = {}
        self.ready: set[str] = set()
        self.worker_failures: dict[str, str] = {}
        self.responses: dict[tuple[int, str, str], dict[str, Any]] = {}
        self.held_gestures: dict[str, dict[str, Any]] = {}
        self.held_expected: dict[str, dict[str, list[float]]] = {}
        self.held_attempt_signature: dict[str, tuple[float, ...]] = {}
        self.sequence = 0
        self.logger = SessionLogger()
        self.drone_processes: dict[str, mp.Process] = {}
        self.camera_process: mp.Process | None = None
        self.worker_uris: dict[str, str] = {}

    def run(self) -> int:
        print(f"Registro central activo: {self.logger.path.resolve()}")
        try:
            self.worker_uris = self._resolve_worker_uris()
            self._start_drone_processes()
            if not self._wait_until_ready():
                return 2
            if not self._validate_preflight():
                self.emergency_event.set()
                return 2
            if self.args.preflight_only:
                print("PREFLIGHT APROBADO: ambos enlaces, MoCap, EKF e IPC estan listos.")
                print("No se enviaron setpoints de vuelo ni se arrancaron motores.")
                return 0

            self.camera_process = self.context.Process(
                target=camera_worker,
                name="CameraWorker",
                args=(
                    self.args.camera,
                    self.args.mode,
                    self.gestures,
                    self.emergency_event,
                    self.shutdown_event,
                ),
            )
            self.camera_process.start()
            print(f"Camara en proceso PID {self.camera_process.pid}. Q en camara o terminal = EMERGENCIA.")
            print(f"Modo activo: {'mano Right controla ambos' if self.args.mode == 'both' else 'control independiente por mano'}.")
            return self._event_loop()
        except KeyboardInterrupt:
            print("\nEMERGENCIA por Ctrl+C.")
            self.emergency_event.set()
            return 130
        except Exception as exc:
            print(f"ERROR antes del vuelo: {exc}")
            if self.drone_processes:
                self.emergency_event.set()
            return 2
        finally:
            self._shutdown()

    def _resolve_worker_uris(self) -> dict[str, str]:
        """Convierte seriales a indices USB antes de crear procesos.

        cflib resuelve una URI con serial enumerando y leyendo el descriptor de
        todos los dongles. Dos procesos haciendo eso a la vez pueden producir
        ``device has no langid`` con libusb-win32. Los trabajadores reciben
        indices numericos y ya no vuelven a leer descriptores USB.
        """
        configured = {"Dron 1": self.args.uri1, "Dron 2": self.args.uri2}
        serial_names = {
            name: urlsplit(uri).netloc.upper()
            for name, uri in configured.items()
            if not _is_numeric_radio_uri(uri)
        }
        serials: tuple[str, ...] = ()
        fallback_to_order = False
        if serial_names:
            try:
                from cflib.drivers.crazyradio import _find_devices, get_serials

                serials = tuple(serial.upper() for serial in get_serials())
            except Exception as exc:
                devices = tuple(_find_devices())
                if len(configured) == 2 and len(serial_names) == 2 and len(devices) == 2:
                    fallback_to_order = True
                    print(
                        "ADVERTENCIA USB: Windows no permitio leer los seriales, pero "
                        "se detectaron exactamente dos Crazyradio. Se usaran indices "
                        "0 y 1; canal y direccion siguen identificando cada dron. "
                        f"Detalle: {exc}"
                    )
                else:
                    raise RuntimeError(
                        "no se pudieron resolver las Crazyradio de forma inequivoca. "
                        f"Dongles detectados={len(devices)}; detalle: {exc}"
                    ) from exc

        resolved: dict[str, str] = {}
        for configured_index, (name, uri) in enumerate(configured.items()):
            parts = urlsplit(uri)
            if _is_numeric_radio_uri(uri):
                resolved[name] = uri
                continue
            serial = serial_names[name]
            if fallback_to_order:
                index = configured_index
                print(
                    f"{name}: indice USB {index}, canal {parts.path.strip('/').split('/')[0]} "
                    f"(serial configurado {serial})."
                )
            elif serial not in serials:
                raise RuntimeError(
                    f"{name}: no se encontro Crazyradio serial {serial}. "
                    f"Detectadas: {serials or 'ninguna'}"
                )
            else:
                index = serials.index(serial)
                print(f"{name}: Crazyradio {serial} resuelta una vez como indice USB {index}.")
            resolved[name] = urlunsplit((parts.scheme, str(index), parts.path, parts.query, parts.fragment))

        numeric_ids = [int(urlsplit(uri).netloc) for uri in resolved.values()]
        if len(set(numeric_ids)) != len(numeric_ids):
            raise RuntimeError("ambos drones quedaron asignados al mismo indice Crazyradio")
        return resolved

    def _start_drone_processes(self) -> None:
        specs = {
            "Dron 1": (self.worker_uris["Dron 1"], self.args.topic1, "Dron 2"),
            "Dron 2": (self.worker_uris["Dron 2"], self.args.topic2, "Dron 1"),
        }
        for name, (uri, topic, peer_name) in specs.items():
            process = self.context.Process(
                target=drone_worker,
                name=name.replace(" ", ""),
                args=(
                    name,
                    uri,
                    topic,
                    self.commands[name],
                    self.flight_events,
                    self.shared_pose[name],
                    self.shared_pose[peer_name],
                    self.emergency_event,
                    self.shutdown_event,
                ),
            )
            process.start()
            self.drone_processes[name] = process
            print(f"{name}: proceso PID {process.pid}, radio {uri}, MoCap {topic}")

    def _wait_until_ready(self) -> bool:
        deadline = time.monotonic() + READY_TIMEOUT_S
        while time.monotonic() < deadline and not self.emergency_event.is_set():
            self._pump_flight_event(timeout=0.10)
            if self.ready == set(self.drone_processes):
                return True
            for name, process in self.drone_processes.items():
                if not process.is_alive() and name not in self.ready:
                    print(f"ERROR: {name} termino durante el preflight (exitcode={process.exitcode}).")
                    self.emergency_event.set()
                    return False
        if self.worker_failures:
            details = " | ".join(
                f"{name}: {message}" for name, message in self.worker_failures.items()
            )
            print(f"ERROR: preflight interrumpido por fallo de trabajador. {details}")
            return False
        if self.emergency_event.is_set():
            print("ERROR: preflight interrumpido por el evento de emergencia.")
            return False
        missing = sorted(set(self.drone_processes) - self.ready)
        print(f"ERROR: preflight agotado; faltan: {', '.join(missing)}")
        self.emergency_event.set()
        return False

    def _validate_preflight(self) -> bool:
        states = [self.latest.get(name) for name in ("Dron 1", "Dron 2")]
        if any(not state or not state.get("pose") for state in states):
            print("ERROR: no hay una posicion valida de ambos drones al terminar preflight.")
            return False
        separation = math.dist(states[0]["pose"], states[1]["pose"])
        if separation < MIN_SEPARATION_M:
            print(f"ERROR: separacion inicial {separation:.2f} m < {MIN_SEPARATION_M:.2f} m.")
            return False
        print(f"PREFLIGHT: ambos procesos listos; separacion inicial {separation:.2f} m.")
        for state in states:
            print(
                f"  {state['drone']}: pose={_xyz_text(state.get('pose'))}, "
                f"bateria={_number_text(state.get('battery_v'), 2)} V, "
                f"MoCap={_number_text(state.get('mocap_hz'), 1)} Hz"
            )
        return True

    def _event_loop(self) -> int:
        while not self.shutdown_event.is_set() and not self.emergency_event.is_set():
            self._pump_flight_event(timeout=0.02)
            self._drain_gestures()
            if msvcrt.kbhit() and msvcrt.getwch().lower() == "q":
                print("EMERGENCIA solicitada desde la terminal.")
                self.emergency_event.set()
                break
            for name, process in self.drone_processes.items():
                if not process.is_alive():
                    print(f"EMERGENCIA: el proceso de {name} termino (exitcode={process.exitcode}).")
                    self.emergency_event.set()
                    break
            if self.camera_process is not None and not self.camera_process.is_alive():
                # CAMERA_FAILED y Q ya activan el Event. Si desaparece sin aviso,
                # se adopta igualmente el estado mas seguro.
                print("EMERGENCIA: el proceso de camara termino.")
                self.emergency_event.set()
                break
        if self.emergency_event.is_set():
            print("PARO GLOBAL ACTIVO: ambos trabajadores cortaran motores localmente.")
            return 3
        return 0

    def _drain_gestures(self) -> None:
        critical: dict[str, dict[str, Any]] = {}
        for _ in range(256):
            try:
                message = self.gestures.get_nowait()
            except queue.Empty:
                break
            self.logger.write(message, "camera")
            kind = message.get("kind")
            if kind == "gesture":
                command = str(message.get("command", ""))
                hand = str(message.get("hand", ""))
                age = time.monotonic() - float(message.get("timestamp", time.monotonic()))
                if command in {"DESPEGAR", "ATERRIZAR"}:
                    if age > GESTURE_MAX_AGE_S:
                        continue
                    critical[hand] = message
                    self._clear_held_gesture(hand)
                elif command in GESTURE_MOVES:
                    # La camara emite una sola transicion. El supervisor
                    # conserva la intencion mientras la mano siga sostenida.
                    self.held_gestures[hand] = message
                    self.held_expected.pop(hand, None)
                    self.held_attempt_signature.pop(hand, None)
            elif kind == "gesture_release":
                hand = str(message.get("hand", ""))
                active = self.held_gestures.get(hand)
                if active is not None and active.get("command") == message.get("command"):
                    self._clear_held_gesture(hand)
            elif kind == "camera_event":
                print(f"CAMARA {message.get('event')}: {message.get('message', '')}")

        if critical:
            # Despegue y aterrizaje siguen siendo eventos de una sola vez.
            # Nunca se combinan con un movimiento en el mismo ciclo.
            for hand in ("Right", "Left"):
                message = critical.get(hand)
                if message is not None:
                    result, _candidates = self._execute_gesture(message)
                    print(result)
            return
        self._advance_held_gestures()

    def _clear_held_gesture(self, hand: str) -> None:
        self.held_gestures.pop(hand, None)
        self.held_expected.pop(hand, None)
        self.held_attempt_signature.pop(hand, None)

    def _advance_held_gestures(self) -> None:
        """Encadena pasos solo cuando la telemetria confirma el anterior."""
        for hand in ("Right", "Left"):
            message = self.held_gestures.get(hand)
            if message is None:
                continue
            ready, signature = self._movement_ready(hand, message)
            if not ready or signature == self.held_attempt_signature.get(hand):
                continue
            self.held_attempt_signature[hand] = signature
            previous = {
                name: list(self.latest[name]["requested"])
                for name in self._gesture_targets(hand)
                if self.latest.get(name, {}).get("requested") is not None
            }
            first_step = hand not in self.held_expected
            result, candidates = self._execute_gesture(
                {**message, "first_step": first_step}
            )
            print(result)
            if candidates:
                self.held_expected[hand] = candidates
                if previous and all(
                    name in previous and math.dist(candidate, previous[name]) < 1e-6
                    for name, candidate in candidates.items()
                ):
                    print(f"{hand} {message['command']}: limite manual alcanzado; gesto liberado")
                    self._clear_held_gesture(hand)

    def _movement_ready(
        self,
        hand: str,
        gesture: dict[str, Any],
    ) -> tuple[bool, tuple[float, ...]]:
        targets = self._gesture_targets(hand)
        expected = self.held_expected.get(hand)
        signature: list[float] = []
        for name in targets:
            state = self.latest.get(name, {})
            pose = state.get("pose")
            requested = state.get("requested")
            if state.get("phase") != "HOVER" or pose is None or requested is None:
                return False, ()
            signature.append(float(state.get("timestamp", 0.0)))
            if expected is not None:
                expected_target = expected.get(name)
                if expected_target is None or math.dist(requested, expected_target) > 0.005:
                    return False, ()
                if (
                    math.hypot(requested[0] - pose[0], requested[1] - pose[1])
                    > GESTURE_SETTLE_XY_M
                    or abs(requested[2] - pose[2]) > GESTURE_SETTLE_Z_M
                ):
                    return False, ()
        return True, tuple(signature)

    def _gesture_targets(self, hand: str) -> list[str]:
        if self.args.mode == "both":
            return ["Dron 1", "Dron 2"] if hand == "Right" else []
        return ["Dron 1" if hand == "Right" else "Dron 2"]

    def _execute_gesture(
        self,
        gesture: dict[str, Any],
    ) -> tuple[str, dict[str, list[float]]]:
        command = str(gesture["command"])
        hand = str(gesture["hand"])
        targets = self._gesture_targets(hand)
        if not targets:
            return f"{hand} {command}: ignorado en modo ambos", {}

        if command == "DESPEGAR":
            action, payload = "DESPEGAR", {}
        elif command == "ATERRIZAR":
            action, payload = "ATERRIZAR", {}
        elif command in GESTURE_MOVES:
            dx, dy, dz = GESTURE_MOVES[command]
            action, payload = "MOVER", {
                "dx": dx,
                "dy": dy,
                "dz": dz,
                "allow_unsettled": bool(gesture.get("first_step", False)),
            }
        else:
            return f"{hand} {command}: sin accion", {}
        ok, detail, candidates = self._transaction(targets, action, payload)
        prefix = "OK" if ok else "BLOQUEADO"
        return f"{prefix}: {hand} {command} -> {', '.join(targets)}. {detail}", candidates

    def _transaction(
        self,
        targets: list[str],
        action: str,
        payload: dict[str, float],
    ) -> tuple[bool, str, dict[str, list[float]]]:
        self.sequence += 1
        seq = self.sequence
        prepare = {"kind": "PREPARE", "seq": seq, "action": action, "payload": payload}
        if not all(self._send(name, prepare) for name in targets):
            self._cancel(targets, seq)
            return False, "no se pudo encolar PREPARE", {}

        prepared = self._wait_for_stage(targets, seq, "PREPARED", TRANSACTION_TIMEOUT_S)
        if prepared is None:
            self._cancel(targets, seq)
            return False, "timeout esperando PREPARED", {}
        failures = [f"{name}: {reply.get('message')}" for name, reply in prepared.items() if not reply.get("ok")]
        if failures:
            self._cancel(targets, seq)
            return False, " | ".join(failures), {}
        if not self._targets_are_safe(targets, prepared):
            self._cancel(targets, seq)
            return False, f"objetivo rechazado por separacion minima de {MIN_SEPARATION_M:.2f} m", {}

        execute_at = time.monotonic() + SYNCHRONIZED_DELAY_S
        commit = {"kind": "COMMIT", "seq": seq, "execute_at": execute_at}
        if not all(self._send(name, commit) for name in targets):
            self.emergency_event.set()
            return False, "fallo parcial enviando COMMIT; se activo emergencia", {}
        committed = self._wait_for_stage(targets, seq, "COMMITTED", TRANSACTION_TIMEOUT_S)
        if committed is None or any(not reply.get("ok") for reply in committed.values()):
            # Despues de COMMIT ya no es seguro asumir que ninguno ejecuto.
            self.emergency_event.set()
            return False, "confirmacion COMMITTED incompleta; se activo emergencia", {}
        candidates = {
            name: list(prepared[name]["candidate"])
            for name in targets
            if prepared[name].get("candidate") is not None
        }
        return True, f"transaccion {seq} confirmada por {len(targets)} proceso(s)", candidates

    def _targets_are_safe(
        self,
        targets: list[str],
        prepared: dict[str, dict[str, Any]],
    ) -> bool:
        if len(targets) == 2:
            first = prepared[targets[0]].get("candidate")
            second = prepared[targets[1]].get("candidate")
            return first is not None and second is not None and math.dist(first, second) >= MIN_SEPARATION_M

        name = targets[0]
        peer = "Dron 2" if name == "Dron 1" else "Dron 1"
        candidate = prepared[name].get("candidate")
        peer_state = self.latest.get(peer, {})
        if candidate is None:
            return False
        peer_positions = [peer_state.get("pose"), peer_state.get("requested")]
        return all(position is None or math.dist(candidate, position) >= MIN_SEPARATION_M for position in peer_positions)

    def _wait_for_stage(
        self,
        targets: list[str],
        seq: int,
        stage: str,
        timeout: float,
    ) -> dict[str, dict[str, Any]] | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self.emergency_event.is_set():
            found = {
                name: self.responses[(seq, stage, name)]
                for name in targets
                if (seq, stage, name) in self.responses
            }
            if len(found) == len(targets):
                for name in targets:
                    self.responses.pop((seq, stage, name), None)
                return found
            self._pump_flight_event(timeout=min(0.05, deadline - time.monotonic()))
        return None

    def _pump_flight_event(self, timeout: float = 0.0) -> None:
        try:
            message = self.flight_events.get(timeout=max(0.0, timeout))
        except queue.Empty:
            return
        self.logger.write(message, "flight")
        kind = message.get("kind")
        drone = message.get("drone")
        if kind == "state" and drone:
            self.latest[drone] = message
        elif kind == "response" and drone:
            key = (int(message["seq"]), str(message["stage"]), str(drone))
            self.responses[key] = message
        elif kind == "event":
            event = message.get("event")
            print(f"{drone} {event}: {message.get('message', '')}")
            if event == "READY":
                self.ready.add(str(drone))
                state = message.get("state")
                if isinstance(state, dict):
                    self.latest[str(drone)] = state
            elif event == "WORKER_FAILED":
                self.worker_failures[str(drone)] = str(message.get("message", "fallo desconocido"))

    def _send(self, drone: str, message: dict[str, Any]) -> bool:
        try:
            self.commands[drone].put(message, timeout=0.25)
            return True
        except queue.Full:
            return False

    def _cancel(self, targets: list[str], seq: int) -> None:
        for name in targets:
            self._send(name, {"kind": "CANCEL", "seq": seq})

    def _shutdown(self) -> None:
        if self.emergency_event.is_set():
            for name in self.commands:
                self._send(name, {"kind": "EMERGENCY"})
            time.sleep(0.60)
        self.shutdown_event.set()
        for name in self.commands:
            self._send(name, {"kind": "SHUTDOWN"})

        processes = list(self.drone_processes.values())
        if self.camera_process is not None:
            processes.append(self.camera_process)
        for process in processes:
            process.join(timeout=5.0)
        for process in processes:
            if process.is_alive():
                print(f"Forzando cierre del proceso {process.name}; no respondio al apagado.")
                process.terminate()
                process.join(timeout=2.0)

        # Recupera los ultimos eventos y estados antes de cerrar el CSV.
        while True:
            try:
                message = self.flight_events.get_nowait()
            except queue.Empty:
                break
            self.logger.write(message, "flight")
        while True:
            try:
                message = self.gestures.get_nowait()
            except queue.Empty:
                break
            self.logger.write(message, "camera")
        self.logger.close()
        print(f"Registro multiproceso guardado: {self.logger.path.resolve()}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Control low-level multiproceso de dos Crazyflies por camara"
    )
    parser.add_argument("--uri1", default=DEFAULT_URI_1)
    parser.add_argument("--uri2", default=DEFAULT_URI_2)
    parser.add_argument("--topic1", default=DEFAULT_TOPIC_1)
    parser.add_argument("--topic2", default=DEFAULT_TOPIC_2)
    parser.add_argument("--camera", type=int, default=DEFAULT_CAMERA_INDEX)
    parser.add_argument(
        "--mode",
        choices=("both", "independent"),
        default="both",
        help="both: Right controla ambos; independent: una mano por dron",
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="valida radios, MoCap, EKF e IPC y sale sin arrancar motores",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    guard = SingleInstanceGuard(INSTANCE_MUTEX_NAME)
    if not guard.acquired:
        print(
            "ERROR: ya existe otra ejecucion del controlador multiproceso. "
            "Cierra esa ventana con Q o Ctrl+C antes de iniciar otra."
        )
        raise SystemExit(4)
    try:
        raise SystemExit(Supervisor(args).run())
    finally:
        guard.close()


def _is_numeric_radio_uri(uri: str) -> bool:
    netloc = urlsplit(uri).netloc
    return len(netloc) < 10 and netloc.isdigit()


def _flatten_xyz(row: dict[str, Any], prefix: str, values) -> None:
    if isinstance(values, (list, tuple)) and len(values) >= 3:
        row[f"{prefix}_x"], row[f"{prefix}_y"], row[f"{prefix}_z"] = values[:3]


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return int(value)
    return value


def _xyz_text(values) -> str:
    if not isinstance(values, (list, tuple)) or len(values) < 3:
        return "-"
    return f"({values[0]:.3f}, {values[1]:.3f}, {values[2]:.3f})"


def _number_text(value, decimals: int) -> str:
    return "-" if value is None else f"{value:.{decimals}f}"
