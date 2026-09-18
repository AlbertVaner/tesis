"""Dos Crazyflies con Flow deck vistos como el backend high-level de la cruz.

Traduce la interfaz de `cruz_highlevel_backend` —`connect`, `takeoff`, `move`,
`land`, `emergency`, `snapshot`, `close`— a uno o dos `FlowDroneController`.
Con eso, los mismos paneles y controladores por cámara sirven para las dos
formas de volar y se elige con `--backend {mocap,flowdeck}`; no hacen falta
programas paralelos por deck, que es lo que había antes de septiembre de 2026.

Qué NO puede dar el Flow deck, y por qué la traducción no es transparente
------------------------------------------------------------------------
El backend de mocap manda **posiciones absolutas**: `move` es un `go_to` a un
punto del Robotat, y por eso puede validar geocerca, separación entre drones y
ventana de altura antes de enviar nada. El Flow deck **no sabe dónde está**:
sólo integra flujo óptico, así que lo único que acepta son velocidades.

La consecuencia práctica, y hay que tenerla presente al volar:

* `snapshot()` devuelve `pose` y `target` en `None`. No es un fallo: no existe
  esa información. La altura estimada sí, y va en el texto de estado.
* **No hay geocerca ni separación mínima.** Con dos drones a la vez, el único
  que puede evitar que se acerquen es el operador. El backend de mocap sí lo
  impide; éste no puede, y por eso avisa al conectar.
* Un `move` no es un punto: es un **pulso de velocidad** de `PASO_S` segundos
  que luego se detiene solo. Sostener la tecla no acelera; cada pulsación es un
  salto corto, que es justo lo que hace `DualStepKeysMixin`.

El techo y el piso de altura, el hombre muerto y el aterrizaje por silencio sí
viven en `FlowDroneController`, así que se conservan.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Any

MODULE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = MODULE_DIR.parents[1]
SHARED_DIR = PROJECT_DIR / "controllers" / "shared"
for directory in (MODULE_DIR, SHARED_DIR):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from cruz_highlevel_backend import BridgeError, _wrap_deg  # noqa: E402
from cruz_highlevel_protocol import Command  # noqa: E402
from flowdeck_dual_backend import FlowDroneConfig, FlowDroneController  # noqa: E402

#: Duración del pulso de velocidad que produce cada orden de movimiento.
#: Más corto que el hombre muerto de `FlowDroneController` (0.80 s) para que
#: sea el temporizador de aquí quien pare, y no el de seguridad: si para el de
#: seguridad, el panel ya está en estado degradado.
PASO_S = 0.45

#: Velocidad del pulso. 0.20 m/s durante 0.45 s son unos 9 cm por pulsación,
#: del orden del paso de 10 cm que usa el backend de mocap.
PASO_VELOCIDAD_MS = 0.20

#: Velocidad de giro del pulso. 45 grados/s durante 0.45 s son 20 grados por
#: pulsación, el mismo `MAX_YAW_STEP_DEG` que acepta el protocolo de la cruz.
PASO_GIRO_DEG_S = 45.0

#: Segundos que se espera a que cada dron valide el deck y converja el EKF.
LISTO_TIMEOUT_S = 60.0


class FlowCruzBackend:
    """Uno o dos Crazyflies con Flow deck, con la interfaz del backend de la cruz."""

    def __init__(self, args: Any) -> None:
        self.active_keys: tuple[str, ...] = (
            (args.single,) if getattr(args, "single", None) else ("drone1", "drone2")
        )
        alturas = {
            "drone1": getattr(args, "altura1", None),
            "drone2": getattr(args, "altura2", None),
        }
        uris = {"drone1": args.uri1, "drone2": args.uri2}
        nombres = {"drone1": "Dron 1", "drone2": "Dron 2"}
        self.controllers: dict[str, FlowDroneController] = {}
        for key in self.active_keys:
            config = FlowDroneConfig(
                name=nombres[key],
                uri=uris[key],
                **({"takeoff_height_m": alturas[key]} if alturas[key] else {}),
            )
            self.controllers[key] = FlowDroneController(
                config, callback=self._make_callback(key)
            )
        self.yaw_target_deg = {"drone1": 0.0, "drone2": 0.0}
        self.connected = False
        self.ready = False
        self.emergency_latched = False
        self.emergency_reason: str | None = None
        self._estados: dict[str, tuple[str, str]] = {
            key: ("DESCONECTADO", "Sin conectar") for key in ("drone1", "drone2")
        }
        self._timers: list[threading.Timer] = []
        self._lock = threading.RLock()
        self._emit = None

    # ------------------------------------------------------------ interno

    def _make_callback(self, key: str):
        def callback(state: str, message: str) -> None:
            with self._lock:
                self._estados[key] = (state, message)
                if state == "EMERGENCIA":
                    self.emergency_latched = True
                    self.emergency_reason = self.emergency_reason or message
            emit = self._emit
            if emit is not None:
                nombre = self.controllers[key].config.name if key in self.controllers else key
                emit(state != "ERROR", state.lower(), f"{nombre}: {message}", None)
        return callback

    def _selected(self, command: Command) -> tuple[str, ...]:
        keys = self.active_keys if command.target == "both" else (command.target,)
        for key in keys:
            if key not in self.active_keys:
                raise BridgeError("el dron seleccionado esta deshabilitado")
        return keys

    def _require_ready(self) -> None:
        if self.emergency_latched:
            raise BridgeError("emergencia enclavada; reinicia el programa")
        if not self.ready:
            raise BridgeError("ejecuta PREFLIGHT antes de enviar comandos")

    def _pulso(self, key: str, vx: float, vy: float, vz: float, yawrate: float) -> None:
        """Manda una velocidad y programa su parada. No bloquea la interfaz."""
        controller = self.controllers[key]
        controller.velocity(vx, vy, vz, yawrate)
        timer = threading.Timer(PASO_S, controller.hover)
        timer.daemon = True
        with self._lock:
            self._timers = [t for t in self._timers if t.is_alive()]
            self._timers.append(timer)
        timer.start()

    # ------------------------------------------------------------ interfaz

    def connect(self, emit) -> None:
        self._emit = emit
        if self.emergency_latched:
            raise BridgeError("reinicia el programa despues de una emergencia")
        emit(True, "progress", "Conectando radios y validando Flow deck...", self.snapshot())
        if len(self.active_keys) > 1:
            emit(
                True,
                "warning",
                "Flow deck: sin posicion absoluta, no hay geocerca ni separacion "
                "minima entre drones. Vigila el area.",
                None,
            )
        for key in self.active_keys:
            self.controllers[key].connect()
        errores = []
        for key in self.active_keys:
            controller = self.controllers[key]
            try:
                controller.wait_ready(LISTO_TIMEOUT_S)
            except Exception as exc:
                errores.append(f"{controller.config.name}: {exc}")
        if errores:
            raise BridgeError("; ".join(errores))
        self.connected = True
        self.ready = all(self.controllers[key].ready for key in self.active_keys)
        if not self.ready:
            raise BridgeError("algun dron no quedo listo; revisa el Flow deck")
        emit(True, "ready", "Flow deck validado y estimador convergido.", self.snapshot())

    def takeoff(self, command: Command) -> None:
        self._require_ready()
        keys = self._selected(command)
        for key in keys:
            if self.controllers[key].flying:
                raise BridgeError(f"{self.controllers[key].config.name} ya esta en vuelo")
        for key in keys:
            self.yaw_target_deg[key] = 0.0
            if not self.controllers[key].takeoff():
                raise BridgeError(f"{self.controllers[key].config.name}: despegue rechazado")

    def move(self, command: Command) -> None:
        self._require_ready()
        keys = self._selected(command)
        for key in keys:
            if not self.controllers[key].flying:
                raise BridgeError(f"{self.controllers[key].config.name}: despega antes de mover")
        # Del paso en metros del protocolo a una velocidad: el signo y el eje
        # son los mismos (x adelante, y a la izquierda, z arriba); sólo cambia
        # la magnitud, porque aquí no se puede pedir un punto.
        escala = PASO_VELOCIDAD_MS / max(abs(command.dx), abs(command.dy), abs(command.dz), 1e-9)
        vx, vy, vz = command.dx * escala, command.dy * escala, command.dz * escala
        if abs(command.dx) < 1e-9 and abs(command.dy) < 1e-9 and abs(command.dz) < 1e-9:
            vx = vy = vz = 0.0
        yawrate = PASO_GIRO_DEG_S if command.dyaw > 1e-9 else (
            -PASO_GIRO_DEG_S if command.dyaw < -1e-9 else 0.0
        )
        for key in keys:
            self.yaw_target_deg[key] = _wrap_deg(self.yaw_target_deg[key] + command.dyaw)
            self._pulso(key, vx, vy, vz, yawrate)

    def follow_move(self, command: Command) -> None:
        raise BridgeError("el seguimiento del marker necesita mocap; no hay con Flow deck")

    def land(self, command: Command) -> None:
        for key in self._selected(command):
            controller = self.controllers[key]
            if controller.flying:
                controller.land()

    def emergency(self, reason: str = "orden manual") -> None:
        with self._lock:
            self.emergency_latched = True
            self.emergency_reason = reason
            self.ready = False
        for controller in self.controllers.values():
            controller.emergency_stop()

    def snapshot(self) -> dict[str, Any]:
        unidades: dict[str, Any] = {}
        for key in ("drone1", "drone2"):
            controller = self.controllers.get(key)
            estado, mensaje = self._estados[key]
            if controller is None:
                unidades[key] = {
                    "name": "Dron 1" if key == "drone1" else "Dron 2",
                    "ready": False,
                    "airborne": False,
                    "enabled": False,
                    "status": "Deshabilitado en modo de un dron",
                    "pose": None,
                    "target": None,
                    "yaw_deg": 0.0,
                    "battery_v": None,
                    "mocap_age_s": None,
                    "ekf_mocap_error_m": None,
                }
                continue
            altura = controller.height_m
            texto = f"{estado}: {mensaje}"
            if altura is not None:
                texto = f"{texto} · altura {altura:.2f} m"
            unidades[key] = {
                "name": controller.config.name,
                "ready": controller.ready,
                "airborne": controller.flying,
                "enabled": True,
                "status": texto,
                # El Flow deck no da posición absoluta; ver el docstring.
                "pose": None,
                "target": None,
                "yaw_deg": self.yaw_target_deg[key],
                "battery_v": None,
                "mocap_age_s": None,
                "ekf_mocap_error_m": None,
            }
        return {
            "mode": "flowdeck",
            "connected": self.connected,
            "ready": self.ready and not self.emergency_latched,
            "emergency": self.emergency_latched,
            "emergency_reason": self.emergency_reason,
            # Sin posición no hay separación que medir.
            "separation_m": None,
            "drone1": unidades["drone1"],
            "drone2": unidades["drone2"],
            "log_path": None,
        }

    def close(self) -> None:
        with self._lock:
            timers, self._timers = self._timers, []
        for timer in timers:
            timer.cancel()
        for controller in self.controllers.values():
            controller.close()
        for controller in self.controllers.values():
            controller.join(8.0)
        self.connected = self.ready = False


def build_backend(args: Any):
    """Backend elegido por `--backend`. Es el punto único de decisión."""
    backend = getattr(args, "backend", "mocap")
    if backend == "robotat":
        from robotat_backend import RobotatCruzBackend

        return RobotatCruzBackend(args)
    if backend == "flowdeck":
        if getattr(args, "dry_run", False):
            raise BridgeError(
                "--dry-run no existe con Flow deck: no hay simulador de deck. "
                "Usa --backend mocap --dry-run para probar la interfaz sin radio."
            )
        return FlowCruzBackend(args)
    from cruz_highlevel_backend import HardwareBackend, SimulatedBackend

    single = getattr(args, "single", None)
    return SimulatedBackend(single) if getattr(args, "dry_run", False) else HardwareBackend(args)
