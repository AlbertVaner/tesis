"""Backend Flow deck: un hilo por Crazyflie, para uno o dos drones.

Lo usan el panel de teclado individual, el panel dual y los controladores por
cámara con Flow deck de uno y dos drones. Cada `FlowDroneController` es dueño
exclusivo de una Crazyradio y de un `MotionCommander`; la interfaz que lo usa
sólo encola órdenes y lee estado.

Protecciones, todas dentro del hilo:

* deadman: sin órdenes frescas se detiene el movimiento y se queda en hover;
* aterrizaje por silencio (`lost_land_s`): si nadie manda nada durante ese
  tiempo, aterriza. Una cámara colgada no debe dejar el dron en hover hasta
  agotar la batería;
* techo y piso (`max_height_m`): registra `stateEstimate.z` y bloquea el
  ascenso sobre el techo, el descenso bajo el piso y cualquier ascenso si la
  altura no es reciente.
"""

from __future__ import annotations

import queue
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from cflib.crazyflie import Crazyflie
from cflib.crazyflie.log import LogConfig
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie
from cflib.positioning.motion_commander import MotionCommander


PROJECT_DIR = Path(__file__).resolve().parents[2]
SHARED_DIR = PROJECT_DIR / "controllers" / "shared"
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))

from flowdeck_flight import (  # noqa: E402
    DEFAULT_HEIGHT_M,
    arm_if_supported,
    emergency_stop_motion_commander,
    require_flow_deck,
    reset_and_wait_for_estimator,
)


COMMAND_DEADMAN_S = 0.80
#: Techo y piso con Flow deck. El deck v2 pierde precisión de altura a pocos
#: metros, así que sostener ARRIBA no puede subir indefinidamente.
MAX_HEIGHT_M = 1.10
MIN_HEIGHT_M = 0.15
HEIGHT_STALE_S = 0.50

StateCallback = Callable[[str, str], None]


@dataclass(frozen=True)
class FlowDroneConfig:
    name: str
    uri: str
    takeoff_height_m: float = DEFAULT_HEIGHT_M
    #: Sin órdenes frescas durante este tiempo: se detiene el movimiento.
    deadman_s: float = COMMAND_DEADMAN_S
    #: Sin órdenes frescas durante este tiempo: aterriza. `None` lo desactiva.
    lost_land_s: float | None = None
    #: Techo de vuelo. `None` desactiva el registro de altura y el límite.
    max_height_m: float | None = None
    min_height_m: float = MIN_HEIGHT_M


class FlowDroneController:
    """Un hilo es dueño exclusivo de una Crazyradio y un Crazyflie."""

    def __init__(self, config: FlowDroneConfig, callback: StateCallback | None = None) -> None:
        self.config = config
        self.callback = callback or (
            lambda state, message: print(f"[{config.name}] {state}: {message}")
        )
        self.commands: queue.Queue[tuple[str, object | None]] = queue.Queue()
        self.emergency_event = threading.Event()
        self.lock = threading.RLock()
        self.thread: threading.Thread | None = None
        self.connected = False
        self.ready = False
        self.flying = False
        self.busy = False
        self.state = "DESCONECTADO"
        self.error = ""
        # Altura estimada por el Crazyflie (sólo con `max_height_m`).
        self.height_m: float | None = None
        self.height_time = 0.0
        self._height_log: LogConfig | None = None
        self._height_warned = False
        self._last_command = time.monotonic()
        self._motion_active = False

    # -- Estado --------------------------------------------------------------

    @property
    def motion_active(self) -> bool:
        with self.lock:
            return self._motion_active

    def _publish(self, state: str, message: str) -> None:
        with self.lock:
            self.state = state
            if state in ("ERROR", "EMERGENCIA"):
                self.error = message
        self.callback(state, message)

    # -- Órdenes (cualquier hilo) --------------------------------------------

    def connect(self) -> None:
        with self.lock:
            if self.thread is not None and self.thread.is_alive():
                return
            self.busy = True
        self.emergency_event.clear()
        self.thread = threading.Thread(target=self._worker, name=f"flowdeck-{self.config.name}", daemon=True)
        self.thread.start()

    def wait_ready(self, timeout_s: float = 60.0) -> None:
        """Bloquea hasta que termina el preflight; lanza `RuntimeError` si falló."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            with self.lock:
                if self.ready:
                    return
                thread_alive = self.thread is not None and self.thread.is_alive()
                error = self.error
            if not thread_alive:
                raise RuntimeError(error or f"{self.config.name}: la conexión terminó sin quedar lista")
            time.sleep(0.05)
        raise RuntimeError(f"{self.config.name}: el preflight no terminó en {timeout_s:.0f} s")

    def takeoff(self) -> bool:
        with self.lock:
            if not self.ready or self.flying or self.busy:
                return False
            self.busy = True
        self.commands.put(("takeoff", None))
        return True

    def velocity(self, vx: float, vy: float, vz: float) -> None:
        with self.lock:
            if not self.flying:
                return
        self.commands.put(("velocity", (vx, vy, vz)))

    def hover(self) -> None:
        with self.lock:
            if not self.flying:
                return
        self.commands.put(("hover", None))

    def land(self) -> bool:
        with self.lock:
            if not self.flying or self.busy:
                return False
            self.busy = True
        self.commands.put(("land", None))
        return True

    def emergency_stop(self) -> None:
        self.emergency_event.set()

    def close(self, wait_s: float | None = None) -> None:
        self.commands.put(("close", None))
        if wait_s is not None:
            self.join(wait_s)

    def join(self, timeout: float = 8.0) -> None:
        if self.thread is not None:
            self.thread.join(timeout=timeout)

    # Nombres que usan los controladores por cámara.
    request_takeoff = takeoff
    set_velocity = velocity

    def request_land(self, reason: str = "") -> bool:
        if reason:
            print(f"[{self.config.name}] Aterrizando ({reason})...")
        return self.land()

    # -- Altura --------------------------------------------------------------

    def _start_height_log(self, cf: Crazyflie) -> None:
        """Registra stateEstimate.z para poder limitar la altura en vuelo."""
        try:
            log_config = LogConfig(name=f"Altura{self.config.name.replace(' ', '')}", period_in_ms=100)
            log_config.add_variable("stateEstimate.z", "float")
            log_config.data_received_cb.add_callback(self._on_height)
            cf.log.add_config(log_config)
            log_config.start()
            self._height_log = log_config
            print(f"[{self.config.name}] Registro de altura activo. Techo: {self.config.max_height_m:.2f} m.")
        except Exception as error:
            # Sin altura confiable el ascenso queda bloqueado en _limit_vertical.
            print(f"[{self.config.name}] AVISO: no se pudo registrar la altura ({error}). "
                  "El ascenso quedará bloqueado por seguridad.")

    def _stop_height_log(self) -> None:
        if self._height_log is not None:
            try:
                self._height_log.stop()
            except Exception:
                pass
            self._height_log = None

    def _on_height(self, _timestamp, data, _logconf) -> None:
        with self.lock:
            self.height_m = float(data["stateEstimate.z"])
            self.height_time = time.monotonic()

    def _limit_vertical(self, vz: float) -> float:
        """Bloquea ascenso sobre el techo y descenso bajo el piso."""
        if self.config.max_height_m is None:
            return vz
        with self.lock:
            height, height_time = self.height_m, self.height_time
        fresh = height is not None and time.monotonic() - height_time <= HEIGHT_STALE_S
        if not fresh:
            if vz > 0.0 and not self._height_warned:
                print(f"[{self.config.name}] Altura no disponible: ascenso bloqueado por seguridad.")
                self._height_warned = True
            return min(vz, 0.0)
        if vz > 0.0 and height >= self.config.max_height_m:
            return 0.0
        if vz < 0.0 and height <= self.config.min_height_m:
            return 0.0
        return vz

    # -- Hilo dueño de la radio ---------------------------------------------

    def _worker(self) -> None:
        emergency = False
        try:
            self._publish("CONECTANDO", "Abriendo radio y validando Flow deck...")
            with SyncCrazyflie(
                self.config.uri,
                cf=Crazyflie(rw_cache=f"./cache/flowdeck_{self.config.name.lower().replace(' ', '_')}"),
            ) as scf:
                with self.lock:
                    self.connected = True
                require_flow_deck(scf.cf)
                reset_and_wait_for_estimator(scf.cf)
                if self.config.max_height_m is not None:
                    self._start_height_log(scf.cf)
                with self.lock:
                    self.ready = True
                    self.busy = False
                self._publish("LISTO", "Flow deck detectado y estimador estable.")
                emergency = self._serve(scf.cf)
        except Exception as error:
            self._publish("ERROR", str(error))
        finally:
            self._stop_height_log()
            with self.lock:
                self.connected = False
                self.ready = False
                self.flying = False
                self.busy = False
                self._motion_active = False
            if not emergency and self.state != "ERROR":
                self._publish("DESCONECTADO", "Conexión cerrada.")

    def _serve(self, cf) -> bool:
        """Atiende la cola hasta `close` o emergencia. Devuelve si hubo emergencia."""
        commander: MotionCommander | None = None
        try:
            while True:
                if self.emergency_event.is_set():
                    emergency_stop_motion_commander(commander, cf)
                    commander = None
                    with self.lock:
                        self.flying = False
                        self.ready = False
                        self.busy = False
                        self._motion_active = False
                    self._publish("EMERGENCIA", "Motores detenidos; revisa el dron antes de reconectar.")
                    return True
                try:
                    command, payload = self.commands.get(timeout=0.05)
                except queue.Empty:
                    if commander is not None:
                        self._watch(commander)
                    continue

                if command == "takeoff":
                    self._publish("DESPEGANDO", "Despegando a altura segura...")
                    arm_if_supported(cf)
                    commander = MotionCommander(cf, default_height=self.config.takeoff_height_m)
                    # take_off() bloquea; el lock queda libre para las interfaces.
                    commander.take_off()
                    commander.stop()
                    with self.lock:
                        self.flying = True
                        self.busy = False
                        self._motion_active = False
                        self._last_command = time.monotonic()
                    self._publish("VOLANDO", "Hover; esperando comandos.")
                elif command == "velocity" and commander is not None:
                    vx, vy, vz = payload  # type: ignore[misc]
                    vz = self._limit_vertical(vz)
                    commander.start_linear_motion(vx, vy, vz)
                    with self.lock:
                        self._motion_active = any(abs(value) > 1e-6 for value in (vx, vy, vz))
                        self._last_command = time.monotonic()
                elif command == "hover" and commander is not None:
                    commander.stop()
                    with self.lock:
                        self._motion_active = False
                        self._last_command = time.monotonic()
                elif command == "land" and commander is not None:
                    self._publish("ATERRIZANDO", "Ejecutando aterrizaje normal...")
                    commander.stop()
                    commander.land()
                    commander = None
                    with self.lock:
                        self.flying = False
                        self.busy = False
                        self._motion_active = False
                    self._publish("EN TIERRA", "Aterrizaje completado.")
                elif command == "close":
                    if commander is not None:
                        self._publish("ATERRIZANDO", "Aterrizando antes de cerrar...")
                        commander.stop()
                        commander.land()
                        commander = None
                    return False
        finally:
            if commander is not None:
                # Salida por excepción: intentar dejar el dron en el suelo.
                try:
                    commander.stop()
                    commander.land()
                except Exception:
                    pass

    def _watch(self, commander: MotionCommander) -> None:
        """Deadman y aterrizaje por silencio; corre en el hilo dueño de la radio."""
        with self.lock:
            if not self.flying or self.busy:
                return
            silence = time.monotonic() - self._last_command
            moving = self._motion_active
        if self.config.lost_land_s is not None and silence >= self.config.lost_land_s:
            print(f"[{self.config.name}] Sin órdenes durante {silence:.1f} s: aterrizando.")
            with self.lock:
                self.busy = True
            self.commands.put(("land", None))
            return
        if moving and silence > self.config.deadman_s:
            commander.stop()
            with self.lock:
                self._motion_active = False
