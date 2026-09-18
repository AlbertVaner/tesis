"""El dron sobre el Robotat visto desde el controlador por cámara.

Expone la misma interfaz que `HighLevelFlight` y `FlowDroneController`
(`connect`, `flying`, `busy`, `height_m`, `request_takeoff`, `request_land`,
`set_velocity`, `hover`, `emergency_stop`, `close`), de modo que
`control_camara_dron1.py` no distingue backends. La intención de velocidad
que produce la visión se manda en **modo fluido** (paquete `hover` del
firmware, como el Flow Deck): el dron se mueve mientras el gesto dure y frena
al terminar, sin los pasos `go_to` a tirones del backend de la cruz.

Vigilancia propia de la visión, encima de la del dron:

* **deadman**: sin órdenes de la cámara durante `deadman_s`, la velocidad se
  pone a cero (el flujo de velocidad no debe sobrevivir a una cámara colgada);
* **pérdida**: sin órdenes durante `lost_land_s`, se aterriza.

    flight = VueloRobotat(Opciones(uri="radio://sim", topic="mocap/drone4"), dry_run=True)
    flight.connect(); flight.request_takeoff(); flight.set_velocity(0.18, 0.0, 0.0)
"""

from __future__ import annotations

import math
import sys
import threading
from pathlib import Path
from typing import Callable

MODULE_DIR = Path(__file__).resolve().parent
SHARED_DIR = MODULE_DIR.parents[1] / "shared"
for directory in (MODULE_DIR, SHARED_DIR):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from dron_robotat import (  # noqa: E402
    GANANCIAS, LAND_DURATION_S, TAKEOFF_DURATION_S,
    DronError, DronRobotat, DronSimulado, Opciones,
)
from reloj import ahora  # noqa: E402

#: Sin órdenes de la cámara durante este tiempo se frena (velocidad cero).
VISION_DEADMAN_S = 0.40
#: Sin órdenes durante este tiempo se aterriza.
VISION_LOST_LAND_S = 2.00
#: Velocidad máxima que la cámara puede pedir, m/s. Los gestos piden 0.18 en
#: XY y 0.10 en Z; el tope deja margen sin llegar a lo que desestabiliza.
VELOCIDAD_MAX_CAMARA_MPS = 0.30
#: Seguimiento del marker 65 con este backend: lazo proporcional sobre la
#: posición estimada del dron, con zona muerta y tope propios. El seguidor
#: genérico (`marker_follow.world_velocity`) se queda en 0.10 m/s y con la
#: pose de otro receptor MQTT; aquí se usa el EKF, que es lo que el firmware
#: controla, y se permite ir más rápido porque el lazo vertical ya es estable.
SEGUIR_KP = 1.5
SEGUIR_VELOCIDAD_MPS = 0.30
SEGUIR_ZONA_MUERTA_M = 0.03
#: Órbita alrededor del marker 65 (gesto `circulo`): círculo horizontal de
#: `ORBITA_RADIO_M` a la altura del marker, recorrido a `ORBITA_VELOCIDAD_MPS`
#: en sentido antihorario visto desde arriba. El punto objetivo avanza por el
#: círculo y el dron lo persigue con el mismo lazo proporcional del
#: seguimiento más la velocidad tangencial como anticipo. Se sale aplaudiendo.
ORBITA_RADIO_M = 0.50
ORBITA_VELOCIDAD_MPS = 0.20
ORBITA_KP = 1.5
#: El objetivo va **por delante del dron sobre el círculo**, este ángulo, y no
#: a un reloj propio: si el punto avanzara solo, con el tope de velocidad el
#: dron se quedaba medio metro atrás y la "órbita" era una persecución
#: (18:59 del 2026-09-17). Enganchado a la fase real del dron el círculo se
#: dibuja a la velocidad que el dron pueda.
ORBITA_ANTICIPO_DEG = 30.0


def opciones_camara(
    *,
    uri: str | None,
    topic: str,
    nombre: str,
    ganancias: str = "robotat",
    parametros: dict[str, str] | None = None,
    radio_max_m: float | None = None,
    dry_run: bool = False,
    centro_geocerca: tuple[float, float] | None = None,
) -> Opciones:
    """`Opciones` del dron para la cámara: preajuste de ganancias más `--param`."""
    parametros = dict(parametros or {})
    if ganancias not in GANANCIAS:
        raise ValueError(f"juego de ganancias desconocido: {ganancias!r}")
    if not uri:
        if not dry_run:
            raise ValueError(f"hace falta la URI de {nombre} para volar de verdad")
        uri = "radio://sim/0/2M/E7E7E7E7E7"
    extra = {} if radio_max_m is None else {"radio_max_m": radio_max_m}
    if centro_geocerca is not None:
        extra["centro_geocerca"] = (float(centro_geocerca[0]), float(centro_geocerca[1]))
    return Opciones(
        uri=uri, topic=topic, nombre=nombre,
        parametros=GANANCIAS[ganancias] | parametros,
        velocidad_mps=VELOCIDAD_MAX_CAMARA_MPS,
        thrust_base_explicito="posCtlPid.thrustBase" in parametros,
        **extra,
    )


def plan_orbita(
    centro: tuple[float, float, float], radio_m: float, theta: float, velocidad_mps: float,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Punto del círculo en `theta` (a la altura del centro) y velocidad tangencial."""
    objetivo = (centro[0] + radio_m * math.cos(theta), centro[1] + radio_m * math.sin(theta), centro[2])
    tangente = (-velocidad_mps * math.sin(theta), velocidad_mps * math.cos(theta), 0.0)
    return objetivo, tangente


class VueloRobotat:
    """Un Crazyflie sobre el Robotat como backend de un controlador por cámara."""

    def __init__(
        self,
        opciones: Opciones,
        *,
        dry_run: bool = False,
        log: Callable[[str], None] = print,
        deadman_s: float = VISION_DEADMAN_S,
        lost_land_s: float = VISION_LOST_LAND_S,
        key: str = "drone1",
        velocidad_seguir_mps: float = SEGUIR_VELOCIDAD_MPS,
        radio_orbita_m: float = ORBITA_RADIO_M,
        velocidad_orbita_mps: float = ORBITA_VELOCIDAD_MPS,
    ) -> None:
        self.opciones = opciones
        self.dry_run = dry_run
        self.log = log
        self.deadman_s = deadman_s
        self.lost_land_s = lost_land_s
        #: Clave con la que el seguidor del marker ancla a este dron.
        self.KEY = key
        self.velocidad_seguir_mps = max(0.05, min(float(velocidad_seguir_mps), opciones.velocidad_mps))
        self.radio_orbita_m = max(0.05, float(radio_orbita_m))
        self.velocidad_orbita_mps = max(0.05, min(float(velocidad_orbita_mps), opciones.velocidad_mps))
        #: (ángulo en rad, instante) de la órbita en curso; None si no orbita.
        self._orbita: tuple[float, float] | None = None
        self._ultimo_objetivo_evento_s = -1e9
        self.dron = DronSimulado(opciones, log=log) if dry_run else DronRobotat(opciones, log=log)
        self.lock = threading.RLock()
        self.emergency = False
        self._last_order = ahora()
        self._watchdog_stop = threading.Event()
        self._watchdog = threading.Thread(target=self._watchdog_loop, name="vision-watchdog", daemon=True)

    # -- Conexión ------------------------------------------------------------

    def connect(self) -> None:
        self.dron.preflight(lambda m: self.log(f"[preflight] {m}"))
        self._touch()
        self._watchdog.start()
        self.log("Preflight terminado. La cámara todavía no enciende los motores.")

    def wait_ready(self) -> None:
        """El preflight ya es síncrono; existe por compatibilidad con Flow Deck."""

    def set_params(self, params: dict[str, str]) -> dict[str, str]:
        """Los parámetros se aplican en el preflight desde `Opciones`; devuelve lo aplicado."""
        aplicados = dict(self.dron.estado().parametros)
        faltan = {k: v for k, v in (params or {}).items() if aplicados.get(k) != str(v)}
        if faltan:
            self.log("[param] no aplicados (pasarlos antes de connect, en Opciones): "
                     + ", ".join(f"{k}={v}" for k, v in faltan.items()))
        return aplicados

    # -- Estado --------------------------------------------------------------

    @property
    def flying(self) -> bool:
        return not self.emergency and self.dron.estado().en_vuelo

    @property
    def busy(self) -> bool:
        """Despegando o aterrizando: no se aceptan velocidades."""
        return self.dron.estado().maniobra_hasta_s > ahora()

    @property
    def height_m(self) -> float | None:
        """Altura sobre el origen del preflight, o `None` sin pose."""
        e = self.dron.estado()
        if e.mocap is None or e.origen is None:
            return None
        return float(e.mocap[2]) - float(e.origen[2])

    # -- Órdenes -------------------------------------------------------------

    def _touch(self) -> None:
        with self.lock:
            self._last_order = ahora()

    def request_takeoff(self) -> bool:
        if self.emergency or self.busy or self.flying:
            return False
        self.log("Gesto DESPEGAR confirmado. Despegando...")
        try:
            self.dron.takeoff()
        except DronError as exc:
            self.log(f"Despegue rechazado: {exc}")
            return False
        self._touch()
        return True

    def request_land(self, reason: str = "gesto") -> bool:
        if self.busy or not self.flying:
            return False
        self.log(f"Aterrizando ({reason})...")
        try:
            self.dron.land()
        except DronError as exc:
            self.log(f"Aterrizaje rechazado: {exc}")
            return False
        self._touch()
        return True

    def set_velocity(self, vx: float, vy: float, vz: float) -> None:
        """Velocidad en el marco del Robotat, m/s, mientras dure el gesto."""
        self._touch()
        if not self.flying or self.busy:
            return
        norm = math.sqrt(vx * vx + vy * vy + vz * vz)
        if norm <= 1e-6:
            self._frenar()
            return
        try:
            self.dron.fijar_velocidad(vx, vy, vz, 0.0, velocidad_mps=min(norm, self.opciones.velocidad_mps))
        except DronError as exc:
            self.log(f"Velocidad rechazada: {exc}")

    def hover(self) -> None:
        """La cámara sigue viva pero no pide movimiento: frenar si se movía."""
        self._touch()
        self._orbita = None
        self._frenar()

    def _frenar(self) -> None:
        if self.dron.estado().modo != "FLUIDO":
            return
        try:
            self.dron.fijar_velocidad(0.0, 0.0, 0.0, 0.0)
        except DronError:
            pass

    def emergency_stop(self) -> None:
        with self.lock:
            self.emergency = True
        self.dron.emergency("STOP por cámara")

    def orbit_marker(self, marker_follow) -> None:
        """Un paso de órbita alrededor del marker 65 (gesto `circulo`).

        El objetivo está sobre el círculo horizontal de `radio_orbita_m`
        centrado en el marker, a su altura, `ORBITA_ANTICIPO_DEG` por delante
        de la fase actual del dron (sentido antihorario). El dron lo persigue
        con el lazo proporcional más la velocidad tangencial: si va lento el
        objetivo le espera, si va rápido no se le escapa. Termina cuando el
        controlador pide `hover()` (aplauso), que borra el estado.
        """
        self._touch()
        if not self.flying or self.busy:
            return
        e = self.dron.estado()
        pose = e.ekf if e.ekf is not None else e.mocap
        if pose is None:
            raise RuntimeError("sin posicion del dron para orbitar")
        centro = marker_follow.marker_position()
        radio = self.radio_orbita_m
        ahora_s = ahora()
        # Fase real del dron respecto al centro; el objetivo va un tramo por delante.
        if math.hypot(pose[0] - centro[0], pose[1] - centro[1]) < 1e-3:
            fase = self._orbita[0] if self._orbita is not None else 0.0
        else:
            fase = math.atan2(pose[1] - centro[1], pose[0] - centro[0])
        theta = fase + math.radians(ORBITA_ANTICIPO_DEG)
        self._orbita = (theta, ahora_s)
        objetivo, tangente = plan_orbita(centro, radio, theta, self.velocidad_orbita_mps)
        self._registrar_objetivo("ORBITA", objetivo, centro)
        vel = [ORBITA_KP * (o - p) + f for o, p, f in zip(objetivo, pose, tangente)]
        norm = math.sqrt(sum(v * v for v in vel))
        if norm <= 1e-6:
            return
        self.dron.fijar_velocidad(vel[0], vel[1], vel[2], 0.0,
                                  velocidad_mps=min(norm, self.opciones.velocidad_mps))

    def _registrar_objetivo(self, etiqueta: str, objetivo, centro) -> None:
        """Deja en el CSV del dron, una vez por segundo, adónde se le pide ir."""
        t = ahora()
        if t - self._ultimo_objetivo_evento_s < 1.0:
            return
        self._ultimo_objetivo_evento_s = t
        evento = getattr(self.dron, "_evento", None)
        if evento is None:
            return
        texto = f"objetivo=({objetivo[0]:+.2f},{objetivo[1]:+.2f},{objetivo[2]:+.2f})"
        if centro is not None:
            texto += f" marker=({centro[0]:+.2f},{centro[1]:+.2f},{centro[2]:+.2f})"
        evento(etiqueta, texto)

    def follow_marker(self, marker_follow) -> None:
        """Un paso de seguimiento del marker 65: velocidad hacia el ancla.

        El ancla la fija `marker_follow` al activarse: a `FOLLOW_RADIUS_M` del
        marker en horizontal, en la dirección en que estaba el dron, y **a la
        altura del marker** (el dron busca su mismo nivel en Z). La velocidad es
        `SEGUIR_KP · error`, acotada a `velocidad_seguir_mps`, con zona
        muerta; el error se mide con la posición que estima el dron.
        """
        self._touch()
        if not self.flying or self.busy:
            return
        e = self.dron.estado()
        pose = e.ekf if e.ekf is not None else e.mocap
        if pose is None:
            raise RuntimeError("sin posicion del dron para seguir el marker")
        if not marker_follow.active(self.KEY):
            # `level`: el ancla queda a la altura del marker, no a la del dron.
            marker_follow.activate((self.KEY,), {self.KEY: pose}, level=True)
        desired = marker_follow.desired(self.KEY)
        self._registrar_objetivo("SEGUIR", desired, None)
        vel = []
        for objetivo, actual in zip(desired, pose):
            error = objetivo - actual
            vel.append(0.0 if abs(error) <= SEGUIR_ZONA_MUERTA_M else SEGUIR_KP * error)
        norm = math.sqrt(sum(v * v for v in vel))
        if norm <= 1e-6:
            self._frenar()
            return
        self.dron.fijar_velocidad(vel[0], vel[1], vel[2], 0.0,
                                  velocidad_mps=min(norm, self.velocidad_seguir_mps))

    # -- Vigilancia y cierre -------------------------------------------------

    def _watchdog_loop(self) -> None:
        while not self._watchdog_stop.wait(0.10):
            with self.lock:
                silence = ahora() - self._last_order
            try:
                if self.emergency or not self.flying:
                    continue
                if silence >= self.deadman_s and self.dron.estado().modo == "FLUIDO":
                    self.log(f"Sin órdenes de la cámara durante {silence:.1f} s: frenando.")
                    self.dron.fijar_velocidad(0.0, 0.0, 0.0, 0.0)
                if silence >= self.lost_land_s and not self.busy:
                    self.log(f"Sin órdenes de la cámara durante {silence:.1f} s: aterrizando.")
                    self.request_land("watchdog de visión")
            except Exception as error:
                self.log(f"Watchdog: {error}")

    def join(self, timeout: float | None = None) -> None:
        """Compatibilidad con `FlowDroneController.join`; no hay hilo que esperar."""

    def close(self) -> None:
        self._watchdog_stop.set()
        if self._watchdog.is_alive():
            self._watchdog.join(timeout=1.0)
        # Aterriza si sigue en vuelo, cierra la radio y guarda el CSV.
        self.dron.close()


__all__ = [
    "VueloRobotat", "opciones_camara", "plan_orbita",
    "SEGUIR_KP", "SEGUIR_VELOCIDAD_MPS", "SEGUIR_ZONA_MUERTA_M",
    "ORBITA_RADIO_M", "ORBITA_VELOCIDAD_MPS", "ORBITA_KP",
    "VISION_DEADMAN_S", "VISION_LOST_LAND_S", "VELOCIDAD_MAX_CAMARA_MPS",
    "LAND_DURATION_S", "TAKEOFF_DURATION_S",
]
