"""Backend reutilizable para controlar dos Crazyflies con Flow deck."""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable

from cflib.crazyflie import Crazyflie
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie
from cflib.positioning.motion_commander import MotionCommander

from hover_flowdeck_dron1 import (
    DEFAULT_HEIGHT_M,
    arm_if_supported,
    emergency_stop_motion_commander,
    require_flow_deck,
    reset_and_wait_for_estimator,
)


COMMAND_DEADMAN_S = 0.80
StateCallback = Callable[[str, str], None]


@dataclass(frozen=True)
class FlowDroneConfig:
    name: str
    uri: str


class FlowDroneController:
    """Un hilo es dueño exclusivo de una Crazyradio y un Crazyflie."""

    def __init__(self, config: FlowDroneConfig, callback: StateCallback) -> None:
        self.config = config
        self.callback = callback
        self.commands: queue.Queue[tuple[str, object | None]] = queue.Queue()
        self.emergency_event = threading.Event()
        self.lock = threading.RLock()
        self.thread: threading.Thread | None = None
        self.connected = False
        self.ready = False
        self.flying = False
        self.busy = False
        self.state = "DESCONECTADO"

    def _publish(self, state: str, message: str) -> None:
        with self.lock:
            self.state = state
        self.callback(state, message)

    def connect(self) -> None:
        with self.lock:
            if self.thread is not None and self.thread.is_alive():
                return
            self.busy = True
        self.emergency_event.clear()
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def takeoff(self) -> None:
        with self.lock:
            if not self.ready or self.flying or self.busy:
                return
            self.busy = True
        self.commands.put(("takeoff", None))

    def velocity(self, vx: float, vy: float, vz: float) -> None:
        with self.lock:
            if not self.flying:
                return
        self.commands.put(("velocity", (vx, vy, vz)))

    def land(self) -> None:
        with self.lock:
            if not self.flying or self.busy:
                return
            self.busy = True
        self.commands.put(("land", None))

    def emergency_stop(self) -> None:
        self.emergency_event.set()

    def close(self) -> None:
        self.commands.put(("close", None))

    def join(self, timeout: float = 8.0) -> None:
        if self.thread is not None:
            self.thread.join(timeout=timeout)

    def _worker(self) -> None:
        commander: MotionCommander | None = None
        emergency = False
        motion_active = False
        last_motion_command = time.monotonic()
        try:
            self._publish("CONECTANDO", "Abriendo radio y validando Flow deck...")
            with SyncCrazyflie(
                self.config.uri,
                cf=Crazyflie(
                    rw_cache=f"./cache_flowdeck_{self.config.name.lower().replace(' ', '_')}"
                ),
            ) as scf:
                with self.lock:
                    self.connected = True
                require_flow_deck(scf.cf)
                reset_and_wait_for_estimator(scf.cf)
                with self.lock:
                    self.ready = True
                    self.busy = False
                self._publish("LISTO", "Flow deck detectado y estimador estable.")

                while True:
                    if self.emergency_event.is_set():
                        emergency = True
                        emergency_stop_motion_commander(commander, scf.cf)
                        commander = None
                        with self.lock:
                            self.flying = False
                            self.ready = False
                            self.busy = False
                        self._publish("EMERGENCIA", "Motores detenidos; revisa el dron.")
                        break
                    try:
                        command, payload = self.commands.get(timeout=0.05)
                    except queue.Empty:
                        if (
                            commander is not None
                            and motion_active
                            and time.monotonic() - last_motion_command > COMMAND_DEADMAN_S
                        ):
                            commander.stop()
                            motion_active = False
                        continue

                    if command == "takeoff":
                        self._publish("DESPEGANDO", "Despegando a altura segura...")
                        arm_if_supported(scf.cf)
                        commander = MotionCommander(scf, default_height=DEFAULT_HEIGHT_M)
                        commander.take_off()
                        commander.stop()
                        with self.lock:
                            self.flying = True
                            self.busy = False
                        self._publish("VOLANDO", "Hover; esperando comandos.")
                    elif command == "velocity" and commander is not None:
                        vx, vy, vz = payload  # type: ignore[misc]
                        commander.start_linear_motion(vx, vy, vz)
                        motion_active = any(abs(v) > 1e-6 for v in (vx, vy, vz))
                        last_motion_command = time.monotonic()
                    elif command == "land" and commander is not None:
                        self._publish("ATERRIZANDO", "Ejecutando aterrizaje normal...")
                        commander.stop()
                        motion_active = False
                        commander.land()
                        commander = None
                        with self.lock:
                            self.flying = False
                            self.busy = False
                        self._publish("EN TIERRA", "Aterrizaje completado.")
                    elif command == "close":
                        if commander is not None:
                            self._publish("ATERRIZANDO", "Aterrizando antes de cerrar...")
                            commander.stop()
                            commander.land()
                            commander = None
                        break
        except Exception as error:
            self._publish("ERROR", str(error))
        finally:
            if commander is not None and not emergency:
                try:
                    commander.stop()
                    commander.land()
                except Exception:
                    pass
            with self.lock:
                self.connected = False
                self.ready = False
                self.flying = False
                self.busy = False
            if not emergency and self.state != "ERROR":
                self._publish("DESCONECTADO", "Conexión cerrada.")
