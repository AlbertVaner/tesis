"""Uno o dos Crazyflies con el controlador nuevo, vistos como el backend de la cruz.

Traduce la interfaz de `cruz_highlevel_backend` (`connect`, `takeoff`, `move`,
`follow_move`, `land`, `emergency`, `snapshot`, `close`) a uno o dos
`DronRobotat` de `controllers/shared/dron_robotat.py`. Con eso, los paneles de
botones, el control por cámara de dos drones y el panel web vuelan con el
núcleo que se validó el 16 de septiembre de 2026 eligiendo
`--backend robotat`, sin programas paralelos.

Qué cambia respecto al backend de mocap de la cruz
--------------------------------------------------
* Un `move` no es un `go_to` que arranca y frena: es un **pulso de velocidad
  fluida** (`fijar_velocidad`) de `PULSO_S` segundos que se detiene solo. Si
  llega otro `move` antes de que acabe, el movimiento continúa sin tirón.
  Es el mando que se sintió bien a mano.
* `follow_move` (seguimiento del marker 65 desde la cámara dual) se convierte
  en velocidad proporcional al desplazamiento pedido, con el mismo tope.
* La separación mínima entre los dos drones la vigila `SupervisorSeparacion`,
  que aterriza a los dos en vez de cortar motores.
* Cada dron guarda su CSV y sus gráficas PDF en `results/.../dron_robotat/`.

"""

from __future__ import annotations

import math
import sys
import threading
from pathlib import Path
from typing import Any, Callable

MODULE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = MODULE_DIR.parents[1]
SHARED_DIR = PROJECT_DIR / "controllers" / "shared"
for directory in (MODULE_DIR, SHARED_DIR):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from cruz_highlevel_backend import BridgeError  # noqa: E402
from cruz_highlevel_protocol import Command  # noqa: E402
from dron_robotat import (  # noqa: E402
    GANANCIAS, DronError, DronRobotat, DronSimulado, Opciones,
)
from radios import DRONE_1_LINK, DRONE_2_LINK  # noqa: E402
from reloj import ahora  # noqa: E402
from robotat import DRONE_1_TOPIC, DRONE_2_TOPIC  # noqa: E402

#: Duración del pulso de velocidad de un `move`. Con 0.25 m/s son ~11 cm por
#: orden, del orden del paso de 10 cm del protocolo; una orden nueva antes de
#: que acabe prolonga el movimiento sin parar.
PULSO_S = 0.45
#: Duración del pulso de un `follow_move`: el seguidor de la cámara dual manda
#: uno cada 0.10 s, así que el movimiento es continuo mientras siga.
PULSO_SEGUIR_S = 0.35
#: Periodo con el que el seguidor emite `follow_move` (camera_marker_runtime).
FOLLOW_PERIOD_S = 0.10
#: Velocidad de giro de un pulso: 45 °/s durante 0.45 s son los 20° del protocolo.
GIRO_DPS = 45.0
#: Separación mínima entre los dos drones en vuelo y en el suelo.
SEPARACION_MIN_M = 0.30
SEPARACION_INICIAL_M = 0.50
CLAVES = ("drone1", "drone2")
NOMBRES = {"drone1": "Dron 1", "drone2": "Dron 2"}


def opciones_desde_args(args: Any, clave: str) -> Opciones:
    """`Opciones` de un dron a partir de los argumentos comunes de la cruz."""
    parametros = dict(GANANCIAS[getattr(args, "ganancias", "robotat") or "robotat"])
    explicito = False
    for item in getattr(args, "param", None) or ():
        nombre, sep, valor = str(item).partition("=")
        if sep and nombre.strip() and valor.strip():
            parametros[nombre.strip()] = valor.strip()
            explicito = explicito or nombre.strip() == "posCtlPid.thrustBase"
    link = DRONE_1_LINK if clave == "drone1" else DRONE_2_LINK
    uri = getattr(args, "uri1" if clave == "drone1" else "uri2", None)
    if getattr(args, "dry_run", False) or not uri:
        uri = f"radio://sim/{link[0]}/{link[1]}/{link[2]}"
    topic = getattr(args, "topic1" if clave == "drone1" else "topic2", None) or (
        DRONE_1_TOPIC if clave == "drone1" else DRONE_2_TOPIC
    )
    extra: dict[str, Any] = {}
    radio_max = getattr(args, "radio_max", None)
    if radio_max is not None:
        extra["radio_max_m"] = float(radio_max)
    altura = getattr(args, "altura", None)
    if altura:
        extra["altura_m"] = float(altura)
    centro = getattr(args, "centro_geocerca", None)
    if centro is not None:
        extra["centro_geocerca"] = (float(centro[0]), float(centro[1]))
    return Opciones(
        uri=uri, topic=topic, nombre=NOMBRES[clave], parametros=parametros,
        velocidad_mps=float(getattr(args, "velocidad", None) or 0.25),
        thrust_base_explicito=explicito, **extra,
    )


def separacion(estados: dict[str, Any], claves: Any = None) -> float | None:
    """Menor distancia entre dos poses del mocap, o None si no hay dos poses.

    Con dos drones es la distancia entre ambos; con tres o más, la del par más
    cercano. `claves` limita la cuenta a esos drones (por defecto, todos).
    """
    # Un dron sin pose no anula la vigilancia de los demás pares.
    poses = [estados[c].mocap for c in (estados if claves is None else claves)
             if c in estados and estados[c].mocap is not None]
    if len(poses) < 2:
        return None
    return min(math.dist(a, b) for i, a in enumerate(poses) for b in poses[i + 1:])


class SupervisorSeparacion:
    """Aterriza a todos los drones si dos de ellos, en vuelo, se acercan a menos de `minimo_m`."""

    def __init__(self, drones: dict[str, Any], *, log: Callable[[str], None] = print,
                 minimo_m: float = SEPARACION_MIN_M) -> None:
        self.drones = drones
        self.log = log
        self.minimo_m = minimo_m
        self.disparado = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="SeparacionRobotat", daemon=True)

    def start(self) -> None:
        if not self._thread.is_alive():
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def comprobar(self) -> float | None:
        """Una comprobación; devuelve la separación mínima. Se puede llamar sin hilo."""
        estados = {c: d.estado() for c, d in self.drones.items()}
        dist = separacion(estados)
        en_vuelo = [c for c in estados if estados[c].en_vuelo and not estados[c].emergencia]
        # Sólo cuentan los pares con los dos en el aire: un dron posado junto a
        # otro que vuela no dispara nada, igual que con dos drones.
        dist_vuelo = separacion(estados, en_vuelo)
        if dist_vuelo is not None and dist_vuelo < self.minimo_m and not self.disparado:
            self.disparado = True
            self.log(f"SEPARACION {dist_vuelo:.2f} m < {self.minimo_m:.2f} m: aterrizando todos")
            for c in self.drones:
                try:
                    detener = getattr(self.drones[c], "_detener_fluido", None)
                    if detener is not None:
                        detener()
                    self.drones[c].land()
                except Exception as exc:
                    self.log(f"{c}: no pudo aterrizar: {exc}")
        if dist is not None and dist >= self.minimo_m and len(en_vuelo) < 2:
            self.disparado = False
        return dist

    def _loop(self) -> None:
        while not self._stop.wait(0.10):
            try:
                self.comprobar()
            except Exception as exc:
                self.log(f"Supervisor: {exc}")


class RobotatCruzBackend:
    """Uno o dos `DronRobotat` con la interfaz del backend de la cruz."""

    def __init__(self, args: Any, *, log: Callable[[str], None] = print) -> None:
        self.active_keys: tuple[str, ...] = (
            (args.single,) if getattr(args, "single", None) else CLAVES
        )
        self.dry_run = bool(getattr(args, "dry_run", False))
        self.log = log
        self.drones: dict[str, Any] = {}
        for key in self.active_keys:
            opciones = opciones_desde_args(args, key)
            self.drones[key] = (DronSimulado if self.dry_run else DronRobotat)(
                opciones, log=lambda m, k=key: self.log(f"[{NOMBRES[k]}] {m}")
            )
        self.supervisor = SupervisorSeparacion(self.drones, log=self.log)
        self.connected = False
        self.ready = False
        self.emergency_latched = False
        self.emergency_reason: str | None = None
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------ interno

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

    def _pulso(self, key: str, ux: float, uy: float, uz: float, uyaw: float,
               velocidad_mps: float | None, duracion_s: float) -> None:
        """Velocidad ahora y parada programada; una orden nueva reprograma la parada."""
        dron = self.drones[key]
        try:
            dron.fijar_velocidad(ux, uy, uz, uyaw, velocidad_mps=velocidad_mps)
        except DronError as exc:
            raise BridgeError(f"{NOMBRES[key]}: {exc}") from exc
        with self._lock:
            anterior = self._timers.pop(key, None)
            if anterior is not None:
                anterior.cancel()
            timer = threading.Timer(duracion_s, self._frenar, args=(key,))
            timer.daemon = True
            self._timers[key] = timer
            timer.start()

    def _frenar(self, key: str) -> None:
        try:
            if self.drones[key].estado().modo == "FLUIDO":
                self.drones[key].fijar_velocidad(0.0, 0.0, 0.0, 0.0)
        except Exception as exc:
            self.log(f"{NOMBRES[key]}: no pudo frenar: {exc}")

    def _cancelar_pulsos(self) -> None:
        with self._lock:
            timers, self._timers = list(self._timers.values()), {}
        for timer in timers:
            timer.cancel()

    # ------------------------------------------------------------ interfaz

    def connect(self, emit) -> None:
        if self.emergency_latched:
            raise BridgeError("reinicia el programa despues de una emergencia")
        if self.ready:
            return
        for key in self.active_keys:
            emit(True, "progress", f"{NOMBRES[key]}: preflight...", self.snapshot())
            try:
                self.drones[key].preflight(lambda m, k=key: emit(True, "progress", f"{NOMBRES[k]}: {m}", None))
            except DronError as exc:
                raise BridgeError(str(exc)) from exc
        if len(self.active_keys) > 1:
            dist = separacion({k: self.drones[k].estado() for k in self.active_keys})
            if dist is not None and dist < SEPARACION_INICIAL_M:
                raise BridgeError(f"separacion inicial {dist:.2f} m; se requieren {SEPARACION_INICIAL_M:.2f} m")
            self.supervisor.start()
        self.connected = self.ready = True
        emit(True, "ready", "Preflight correcto; controlador Robotat listo.", self.snapshot())

    def takeoff(self, command: Command) -> None:
        self._require_ready()
        keys = self._selected(command)
        for key in keys:
            if self.drones[key].estado().en_vuelo:
                raise BridgeError(f"{NOMBRES[key]} ya esta en vuelo")
        for key in keys:
            try:
                self.drones[key].takeoff()
            except DronError as exc:
                raise BridgeError(f"{NOMBRES[key]}: {exc}") from exc

    def move(self, command: Command) -> None:
        """Paso del protocolo (dx, dy, dz, dyaw) como pulso de velocidad fluida."""
        self._require_ready()
        keys = self._selected(command)
        for key in keys:
            if not self.drones[key].estado().en_vuelo:
                raise BridgeError(f"{NOMBRES[key]}: despega antes de mover")
        uyaw = 1.0 if command.dyaw > 1e-9 else (-1.0 if command.dyaw < -1e-9 else 0.0)
        for key in keys:
            self._pulso(key, command.dx, command.dy, command.dz, uyaw, None, PULSO_S)

    def follow_move(self, command: Command) -> None:
        """Desplazamiento pedido por el seguidor como velocidad: delta / periodo."""
        self._require_ready()
        keys = self._selected(command)
        for key in keys:
            if not self.drones[key].estado().en_vuelo:
                raise BridgeError(f"{NOMBRES[key]}: despega antes de seguir")
        norm = math.sqrt(command.dx ** 2 + command.dy ** 2 + command.dz ** 2)
        if norm <= 1e-9:
            for key in keys:
                self._frenar(key)
            return
        for key in keys:
            self._pulso(key, command.dx, command.dy, command.dz, 0.0, norm / FOLLOW_PERIOD_S, PULSO_SEGUIR_S)

    def land(self, command: Command) -> None:
        for key in self._selected(command):
            with self._lock:
                timer = self._timers.pop(key, None)
            if timer is not None:
                timer.cancel()
            try:
                self.drones[key].land()
            except DronError as exc:
                raise BridgeError(f"{NOMBRES[key]}: {exc}") from exc

    def emergency(self, reason: str = "orden manual") -> None:
        with self._lock:
            if self.emergency_latched:
                return
            self.emergency_latched = True
            self.emergency_reason = reason
            self.ready = False
        self._cancelar_pulsos()
        for key in self.active_keys:
            try:
                self.drones[key].emergency(reason)
            except Exception as exc:
                self.log(f"{NOMBRES[key]}: fallo en la emergencia: {exc}")

    def snapshot(self) -> dict[str, Any]:
        unidades: dict[str, Any] = {}
        estados = {k: d.estado() for k, d in self.drones.items()}
        for key in CLAVES:
            e = estados.get(key)
            if e is None:
                unidades[key] = {
                    "name": NOMBRES[key], "ready": False, "airborne": False, "enabled": False,
                    "status": "Deshabilitado en modo de un dron", "pose": None, "target": None,
                    "origin": None, "yaw_deg": 0.0, "battery_v": None, "battery_level_pct": None,
                    "mocap_age_s": None, "ekf_age_s": None, "estimate": None,
                    "mqtt_source_latency_s": None, "mocap_hz": None, "ekf_mocap_error_m": None,
                }
                continue
            unidades[key] = {
                "name": NOMBRES[key], "ready": e.listo, "airborne": e.en_vuelo, "enabled": True,
                "status": f"[{e.modo}] {e.detalle}",
                "pose": None if e.mocap is None else list(e.mocap),
                "target": None if e.objetivo is None else list(e.objetivo),
                "origin": None if e.origen is None else list(e.origen),
                "yaw_deg": e.objetivo_yaw_deg, "battery_v": e.bateria_v, "battery_level_pct": None,
                "mocap_age_s": e.mocap_edad_s, "ekf_age_s": None,
                "estimate": None if e.ekf is None else list(e.ekf),
                "mqtt_source_latency_s": e.mqtt_latencia_s, "mocap_hz": e.mocap_frames_hz,
                "ekf_mocap_error_m": e.error_ekf_mocap_m,
            }
        emergencia = self.emergency_latched or any(e.emergencia for e in estados.values())
        rutas = [e.csv for e in estados.values() if e.csv]
        return {
            "mode": "robotat" + (" (dry-run)" if self.dry_run else ""),
            "connected": self.connected,
            "ready": self.ready and not emergencia,
            "emergency": emergencia,
            "emergency_reason": self.emergency_reason or next(
                (e.razon_emergencia for e in estados.values() if e.razon_emergencia), None),
            "separation_m": separacion(estados),
            "drone1": unidades["drone1"],
            "drone2": unidades["drone2"],
            "log_path": "; ".join(rutas) if rutas else None,
        }

    def close(self) -> None:
        self._cancelar_pulsos()
        self.supervisor.stop()
        hilos = [threading.Thread(target=self.drones[k].close, daemon=True) for k in self.active_keys]
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join(timeout=12.0)
        self.connected = self.ready = False


__all__ = ["RobotatCruzBackend", "SupervisorSeparacion", "opciones_desde_args", "separacion",
           "PULSO_S", "PULSO_SEGUIR_S", "SEPARACION_MIN_M", "SEPARACION_INICIAL_M"]
