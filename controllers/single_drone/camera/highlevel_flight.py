"""Vuelo del Dron 1 sobre el backend high-level de la cruz, para la cámara.

Expone la misma interfaz que `FlowDroneController` (`flying`, `busy`,
`height_m`, `request_takeoff`, `request_land`, `set_velocity`, `hover`,
`emergency_stop`, `close`), de modo que `control_camara_dron1.py` no
distingue backends. La intención de velocidad que produce la visión se
convierte en pasos `go_to` que el backend valida: geocerca, ventana de
altura, mocap fresco, alineación EKF y watchdog viven allí.

    # sin radio ni mocap, con el backend simulado
    flight = HighLevelFlight(dry_run=True)
    flight.connect(); flight.request_takeoff(); flight.set_velocity(0.2, 0, 0)
"""

from __future__ import annotations

import math
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

MODULE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = MODULE_DIR.parents[2]
for directory in (
    PROJECT_DIR / "controllers" / "two_drones",
    PROJECT_DIR / "controllers" / "shared",
):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from camera_marker_runtime import HighlevelCameraMarkerRuntime  # noqa: E402
from cruz_highlevel_backend import (  # noqa: E402
    LAND_DURATION_S,
    TAKEOFF_DURATION_S,
    BridgeError,
    HardwareBackend,
    SimulatedBackend,
)
from cruz_highlevel_protocol import MAX_MOVE_STEP_M, Command  # noqa: E402
from radios import DRONE_2_URI  # noqa: E402
from robotat import DRONE_1_TOPIC, DRONE_2_TOPIC  # noqa: E402

#: Paso por orden de movimiento; el mismo que los gestos de mano de la cruz.
STEP_XY_M = 0.10
STEP_Z_M = 0.08
#: Mínimo entre dos pasos mientras se sostiene un gesto de dirección. Un go_to
#: dura 3 s; re-apuntar cada 1.25 s es lo que ya usa la cámara de la cruz.
STEP_PERIOD_S = 1.25
#: Sin órdenes de la cámara (ni siquiera hover) durante este tiempo: aterrizar.
VISION_LOST_LAND_S = 2.00


class HighLevelFlight:
    """Un dron de la cruz visto como el backend de un controlador por cámara."""

    KEY = "drone1"

    def __init__(
        self,
        *,
        uri: str | None = None,
        topic: str = DRONE_1_TOPIC,
        dry_run: bool = False,
        log=print,
    ) -> None:
        if dry_run:
            self.backend = SimulatedBackend(self.KEY)
        else:
            if not uri:
                raise ValueError("hace falta la URI del Dron 1 para volar de verdad")
            self.backend = HardwareBackend(SimpleNamespace(
                uri1=uri, uri2=DRONE_2_URI, topic1=topic, topic2=DRONE_2_TOPIC, single=self.KEY,
            ))
        self.dry_run = dry_run
        self.log = log
        self.lock = threading.RLock()
        self.emergency = False
        self._busy_until = 0.0
        self._last_step = 0.0
        self._last_order = time.monotonic()
        self._runtime: HighlevelCameraMarkerRuntime | None = None
        self._watchdog_stop = threading.Event()
        self._watchdog = threading.Thread(target=self._watchdog_loop, name="vision-watchdog", daemon=True)

    # -- Conexión ------------------------------------------------------------

    def connect(self) -> None:
        def emit(_ok, _event, message, _snapshot) -> None:
            self.log(f"[preflight] {message}")

        self.backend.connect(emit)
        self._touch()
        self._watchdog.start()
        self.log("Preflight high-level terminado. La cámara todavía no enciende los motores.")

    # -- Estado --------------------------------------------------------------

    def _unit(self) -> dict:
        return self.backend.snapshot()[self.KEY]

    @property
    def flying(self) -> bool:
        return not self.emergency and bool(self._unit().get("airborne"))

    @property
    def busy(self) -> bool:
        with self.lock:
            return time.monotonic() < self._busy_until

    @property
    def height_m(self) -> float | None:
        """Altura sobre el origen del preflight, o `None` sin pose."""
        unit = self._unit()
        pose, origin = unit.get("pose"), unit.get("origin")
        if pose is None or origin is None:
            return None
        return float(pose[2]) - float(origin[2])

    # -- Órdenes -------------------------------------------------------------

    def _touch(self) -> None:
        with self.lock:
            self._last_order = time.monotonic()

    def _send(self, command: Command, busy_s: float = 0.0) -> bool:
        try:
            getattr(self.backend, command.action)(command)
        except BridgeError as exc:
            self.log(f"Orden {command.action} rechazada: {exc}")
            return False
        with self.lock:
            self._busy_until = max(self._busy_until, time.monotonic() + busy_s)
            self._last_order = time.monotonic()
        return True

    def request_takeoff(self) -> bool:
        if self.emergency or self.busy or self.flying:
            return False
        self.log("Gesto DESPEGAR confirmado. Despegando high-level...")
        return self._send(Command("takeoff", self.KEY), TAKEOFF_DURATION_S)

    def request_land(self, reason: str = "gesto") -> bool:
        if self.busy or not self.flying:
            return False
        self.log(f"Aterrizando ({reason})...")
        return self._send(Command("land", self.KEY), LAND_DURATION_S + 0.5)

    def set_velocity(self, vx: float, vy: float, vz: float) -> None:
        """Convierte la intención de velocidad en un paso `go_to` acotado."""
        self._touch()
        if not self.flying or self.busy:
            return
        largest = max(abs(vx), abs(vy))
        dx = dy = dz = 0.0
        if largest > 1e-6:
            dx = STEP_XY_M * vx / largest
            dy = STEP_XY_M * vy / largest
        if abs(vz) > 1e-6:
            dz = math.copysign(STEP_Z_M, vz)
        if not any(abs(value) > 1e-9 for value in (dx, dy, dz)):
            return
        with self.lock:
            if time.monotonic() - self._last_step < STEP_PERIOD_S:
                return
            self._last_step = time.monotonic()
        clamp = lambda value: max(-MAX_MOVE_STEP_M, min(MAX_MOVE_STEP_M, value))  # noqa: E731
        self._send(Command("move", self.KEY, clamp(dx), clamp(dy), clamp(dz)))

    def hover(self) -> None:
        # El commander high-level mantiene la última posición por sí solo;
        # sólo hay que dejar constancia de que la cámara sigue viva.
        self._touch()

    def emergency_stop(self) -> None:
        with self.lock:
            self.emergency = True
        self.backend.emergency("STOP por cámara")

    def follow_marker(self, marker_follow) -> None:
        """Un paso de seguimiento del marker 65 como `follow_move` validado."""
        if self._runtime is None or self._runtime.follower is not marker_follow:
            self._runtime = HighlevelCameraMarkerRuntime(enabled=True, follower=marker_follow)
        self._touch()
        if not self.flying:
            return
        if self.KEY not in self._runtime.active_keys:
            self._runtime.activate(self.KEY, self.backend.snapshot())
        self._runtime.update(self.backend)

    # -- Vigilancia y cierre -------------------------------------------------

    def _watchdog_loop(self) -> None:
        while not self._watchdog_stop.wait(0.10):
            with self.lock:
                silence = time.monotonic() - self._last_order
            if silence < VISION_LOST_LAND_S:
                continue
            try:
                if self.emergency or self.busy or not self.flying:
                    continue
                self.log(f"Sin órdenes de la cámara durante {silence:.1f} s: aterrizando.")
                self.request_land("watchdog de visión")
            except Exception as error:
                self.log(f"Watchdog: {error}")

    def close(self) -> None:
        self._watchdog_stop.set()
        if self._watchdog.is_alive():
            self._watchdog.join(timeout=1.0)
        if self._runtime is not None:
            self._runtime.cancel()
        # Aterriza si sigue en vuelo, cierra la radio y guarda CSV y gráficas.
        self.backend.close()
