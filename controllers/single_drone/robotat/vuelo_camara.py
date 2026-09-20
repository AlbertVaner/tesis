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
from dataclasses import dataclass
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
    FLUID_Z_CEILING_MARGIN_M, FLUID_Z_FLOOR_MARGIN_M, GANANCIAS, LAND_DURATION_S,
    MAX_TARGET_Z_M, MIN_TARGET_Z_M, TAKEOFF_DURATION_S,
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
#: Techo de lo que se puede pedir con `--velocidad-tope`. Por encima de esto
#: no hay ningun vuelo que lo respalde, y un error de tecleo (5 en vez de 0.5)
#: no debe llegar al dron.
VELOCIDAD_TOPE_ABSOLUTO_MPS = 0.60
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
    velocidad_max_mps: float = VELOCIDAD_MAX_CAMARA_MPS,
) -> Opciones:
    """`Opciones` del dron para la cámara: preajuste de ganancias más `--param`.

    `velocidad_max_mps` es el tope de TODO lo que la camara puede pedir, y es
    lo que de verdad fija la velocidad del seguimiento y de la orbita: los dos
    saturan. En la orbita, con el objetivo 30 grados por delante y Kp 1.5, el
    termino proporcional ya vale 0.39 m/s a 0.50 m de radio, asi que el dron
    orbita al tope, no a `velocidad_orbita_mps`. Los gestos de direccion piden
    una velocidad fija (0.18 m/s) y no cambian con esto.
    """
    velocidad_max_mps = max(0.05, min(float(velocidad_max_mps), VELOCIDAD_TOPE_ABSOLUTO_MPS))
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
        velocidad_mps=velocidad_max_mps,
        thrust_base_explicito="posCtlPid.thrustBase" in parametros,
        **extra,
    )


def altura_alcanzable(z: float, origen_z: float) -> float:
    """`z` recortada a la banda de altura que el modo fluido puede mantener.

    El marker 65 lo lleva el operador en la mano, a 1.2-1.5 m, y el modo fluido
    no sube de `MAX_TARGET_Z_M - FLUID_Z_CEILING_MARGIN_M` (0.90 m sobre el
    origen). Sin este recorte el error vertical **no se anulaba nunca**: en los
    vuelos del 2026-09-18 el dron paso todo el seguimiento y la orbita con
    0.4-0.6 m de error en Z, que con Kp 1.5 son 0.6-0.9 m/s pedidos hacia
    arriba. Como la velocidad total se acota a 0.30 m/s, esa componente se
    llevaba casi todo: con `uz=+0.9, uy=-0.5` quedaban 0.14 m/s en horizontal.
    Por eso seguir y orbitar salian lentos y poco marcados.
    """
    bajo = origen_z + MIN_TARGET_Z_M + FLUID_Z_FLOOR_MARGIN_M
    alto = origen_z + MAX_TARGET_Z_M - FLUID_Z_CEILING_MARGIN_M
    return max(bajo, min(alto, float(z)))


#: Ganancia del error de radio en la órbita, (m/s) por metro.
ORBITA_KP_RADIO = 1.5

#: Zona de exclusión alrededor del marker 65, que es la mano del operador.
#: Dentro de `radio`, a cualquier velocidad se le quita la parte que acerca al
#: marker y se le suma un empuje hacia fuera. Vale para todo lo que mueve al
#: dron —seguir, orbitar y las direcciones de los gestos estáticos—, no sólo
#: para el seguimiento: un ADELANTE con `--rumbo` equivocado también trae el
#: dron hacia el operador (vuelo de las 17:33 del 2026-09-18).
EXCLUSION_MARKER_KP = 1.5
EXCLUSION_MARKER_MAX_MPS = 0.30


def fuera_del_marker(
    vel: tuple[float, float, float], pose: tuple[float, float, float],
    marker: tuple[float, float, float], radio_m: float,
) -> tuple[float, float, float]:
    """`vel` corregida para que el dron no entre en el círculo del marker."""
    dx, dy = pose[0] - marker[0], pose[1] - marker[1]
    d = math.hypot(dx, dy)
    if radio_m <= 0.0 or d >= radio_m:
        return vel
    ux, uy = (1.0, 0.0) if d < 1e-6 else (dx / d, dy / d)
    vx, vy = vel[0], vel[1]
    hacia = -(vx * ux + vy * uy)
    if hacia > 0.0:
        vx, vy = vx + hacia * ux, vy + hacia * uy
    empuje = min(EXCLUSION_MARKER_MAX_MPS, EXCLUSION_MARKER_KP * (radio_m - d))
    return vx + empuje * ux, vy + empuje * uy, vel[2]


def velocidad_de_orbita(
    pose: tuple[float, float, float], centro: tuple[float, float, float],
    radio_m: float, velocidad_mps: float, z_objetivo: float,
) -> tuple[float, float, float]:
    """Velocidad para orbitar `centro` a `radio_m`, en sentido antihorario.

    Tangencial a `velocidad_mps` más una corrección **radial** proporcional al
    error de radio, y la vertical hacia `z_objetivo`.

    Sustituye a perseguir un punto 30° por delante sobre el círculo. Aquello no
    mantenía el radio: la cuerda hacia el punto apunta hacia dentro y, con la
    dirección normalizada, el equilibrio quedaba en `R·cos(30°) − 0.067`, o sea
    **0.37 m para un círculo de 0.50**. En el vuelo de las 18:05 del 2026-09-18
    los dos drones orbitaban en oposición correcta (desfase 180-200°) pero a
    0.15-0.30 m del centro, es decir, a 0.4 m uno del otro y pegados a la mano
    del operador.
    """
    dx, dy = pose[0] - centro[0], pose[1] - centro[1]
    r = math.hypot(dx, dy)
    if r < 1e-3:
        return (velocidad_mps, 0.0, ORBITA_KP * (z_objetivo - pose[2]))   # en el centro: salir
    ux, uy = dx / r, dy / r                        # radial hacia fuera
    radial = ORBITA_KP_RADIO * (radio_m - r)
    return (radial * ux - velocidad_mps * uy,
            radial * uy + velocidad_mps * ux,
            ORBITA_KP * (z_objetivo - pose[2]))


# ---------------------------------------------------------------- pirueta
#
# La maniobra de la demo de Bitcraze en IROS 2018: **una espiral hacia abajo y
# la vuelta hacia arriba por el eje central de la espiral**
# (https://www.bitcraze.io/2018/10/the-iros-2018-demo/). Ellos la suben al
# firmware como trayectoria polinómica y suavizan altura y radio con senos para
# que no haya discontinuidades; aquí se usa la misma forma y los mismos senos,
# pero se vuela como la órbita: Python manda velocidades en modo fluido y la
# posición la cierra el firmware. Así pasa por la geocerca, por la zona de
# exclusión del marker y por la repulsión entre drones, igual que todo lo demás.

ESPIRAL_VUELTAS = 2.0
ESPIRAL_RADIO_M = 0.40
#: Altura más baja de la espiral, sobre el origen del despegue.
ESPIRAL_Z_BAJA_M = 0.35
ESPIRAL_KP = 1.5
#: Fracción del tope de velocidad a la que se recorre el tramo más rápido.
ESPIRAL_FRACCION_TOPE = 0.80
ESPIRAL_V_SUBIDA_MPS = 0.15
#: Si el dron se queda más atrás que esto, el punto que persigue le espera. Es
#: la lección de la órbita: un punto que avanza solo deja al dron medio metro
#: atrás y la figura se convierte en una persecución.
ESPIRAL_RETRASO_MAX_M = 0.25


@dataclass(frozen=True)
class PlanEspiral:
    """Una pirueta concreta. `s` va de 0 a 1 en la bajada y de 1 a 2 en la subida."""

    centro: tuple[float, float]
    z_alta: float
    z_baja: float
    radio_m: float
    #: 0 si el dron empieza en el eje (un dron: abre la espiral y la cierra);
    #: su distancia al eje si ya está fuera (formación: radio casi constante).
    radio_inicial_m: float
    fase0: float
    vueltas: float
    t_bajada_s: float
    t_subida_s: float


def _suave(u: float) -> float:
    """0 → 1 sin saltos de velocidad en los extremos."""
    u = max(0.0, min(1.0, u))
    return (1.0 - math.cos(math.pi * u)) / 2.0


def plan_espiral(
    pose: tuple[float, float, float], origen_z: float, tope_mps: float, *,
    centro: tuple[float, float] | None = None, radio_m: float = ESPIRAL_RADIO_M,
    vueltas: float = ESPIRAL_VUELTAS,
) -> PlanEspiral:
    """Pirueta que empieza donde está el dron. Sin `centro`, alrededor de sí mismo."""
    eje = (float(pose[0]), float(pose[1])) if centro is None else (float(centro[0]), float(centro[1]))
    dx, dy = pose[0] - eje[0], pose[1] - eje[1]
    r0 = math.hypot(dx, dy)
    z_baja = origen_z + ESPIRAL_Z_BAJA_M
    z_alta = max(altura_alcanzable(pose[2], origen_z), z_baja + 0.30)
    z_alta = altura_alcanzable(z_alta, origen_z)
    v = max(0.05, ESPIRAL_FRACCION_TOPE * tope_mps)
    return PlanEspiral(
        centro=eje, z_alta=z_alta, z_baja=z_baja, radio_m=radio_m,
        radio_inicial_m=r0 if r0 > 0.05 else 0.0,
        fase0=math.atan2(dy, dx) if r0 > 0.05 else 0.0, vueltas=vueltas,
        t_bajada_s=max(6.0, 2.0 * math.pi * vueltas * max(radio_m, r0) / v),
        t_subida_s=max(2.0, (z_alta - z_baja) / ESPIRAL_V_SUBIDA_MPS),
    )


def punto_espiral(plan: PlanEspiral, s: float) -> tuple[float, float, float]:
    """Dónde tiene que estar el dron en el avance `s` de la pirueta."""
    s = max(0.0, min(2.0, s))
    bajada = min(s, 1.0)
    if plan.radio_inicial_m <= 0.0:
        radio = plan.radio_m * math.sin(math.pi * bajada)      # se abre y se cierra sobre el eje
    else:
        radio = plan.radio_inicial_m + (plan.radio_m - plan.radio_inicial_m) * _suave(4.0 * bajada)
    theta = plan.fase0 + 2.0 * math.pi * plan.vueltas * bajada
    x = plan.centro[0] + radio * math.cos(theta)
    y = plan.centro[1] + radio * math.sin(theta)
    if s <= 1.0:
        z = plan.z_alta - (plan.z_alta - plan.z_baja) * _suave(s)
    else:
        z = plan.z_baja + (plan.z_alta - plan.z_baja) * _suave(s - 1.0)
    return x, y, z


def avance_espiral(plan: PlanEspiral, s: float, dt: float, retraso_m: float) -> float:
    """El `s` siguiente. Con el dron retrasado, el punto le espera."""
    if retraso_m > ESPIRAL_RETRASO_MAX_M:
        return s
    duracion = plan.t_bajada_s if s < 1.0 else plan.t_subida_s
    return min(2.0, s + max(0.0, dt) / duracion)


def velocidad_de_espiral(
    plan: PlanEspiral, s: float, pose: tuple[float, float, float],
) -> tuple[tuple[float, float, float], float]:
    """Velocidad para seguir la pirueta en `s`, y cuánto va retrasado el dron."""
    objetivo = punto_espiral(plan, s)
    duracion = plan.t_bajada_s if s < 1.0 else plan.t_subida_s
    ds = 0.05 / duracion                                   # derivada numérica a 50 ms
    siguiente = punto_espiral(plan, s + ds)
    retraso = math.dist(objetivo, pose)
    anticipo = [(b - a) / 0.05 for a, b in zip(objetivo, siguiente)] if s + ds <= 2.0 else [0.0] * 3
    return tuple(f + ESPIRAL_KP * (o - p) for f, o, p in zip(anticipo, objetivo, pose)), retraso


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
        #: [plan, s, instante] de la pirueta propia en curso; None si no hay.
        self._espiral: list | None = None
        #: Función `(vx, vy, vz) -> (vx, vy, vz)` que ve pasar toda velocidad
        #: antes de mandarla. Con un dron no hay ninguna; la formación de dos
        #: (`two_drones/formacion_camara.py`) pone aquí la repulsión entre drones.
        self.modificar_velocidad: Callable[[tuple[float, float, float]],
                                           tuple[float, float, float]] | None = None
        #: Seguidor del marker y radio de su zona de exclusión (0 = sin zona).
        self._marker_vigilado = None
        self.exclusion_marker_m = 0.0
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
        vx, vy, vz = self._modificada((vx, vy, vz))
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
        self._espiral = None
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

    def orbit_marker(self, marker_follow, *, escala_velocidad: float = 1.0) -> None:
        """Un paso de órbita alrededor del marker 65 (gesto `circulo`).

        `escala_velocidad` (0-1) baja el tope de velocidad de este paso. Con un
        dron no se usa; con dos en formación (`two_drones/formacion_camara.py`)
        es lo que los mantiene en oposición sobre el círculo: a la misma
        velocidad conservarían el desfase con el que entraron.

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
        objetivo = (objetivo[0], objetivo[1], self._z_alcanzable(objetivo[2], e))
        self._registrar_objetivo("ORBITA", objetivo, centro)
        del tangente                               # el objetivo sólo se registra; manda la ley polar
        escala = max(0.1, min(1.0, float(escala_velocidad)))
        tope = self.opciones.velocidad_mps
        vel = list(velocidad_de_orbita(pose, centro, radio, tope * escala, objetivo[2]))
        # La escala frena la órbita, **no** la repulsión: antes el dron frenado
        # al 35 % también escapaba del otro al 35 %.
        norm = math.sqrt(sum(v * v for v in vel))
        if norm > tope * escala > 0.0:
            vel = [v * tope * escala / norm for v in vel]
        vel = list(self._modificada(tuple(vel)))
        norm = math.sqrt(sum(v * v for v in vel))
        if norm <= 1e-6:
            return
        self.dron.fijar_velocidad(vel[0], vel[1], vel[2], 0.0, velocidad_mps=min(norm, tope))

    def vigilar_marker(self, marker_follow, radio_m: float) -> None:
        """Desde ahora ninguna orden acerca el dron a menos de `radio_m` del marker."""
        self._marker_vigilado = getattr(marker_follow, "_seguidor", marker_follow)
        self.exclusion_marker_m = max(0.0, float(radio_m))

    def pirueta_paso(self, plan: PlanEspiral, s: float) -> float:
        """Un paso de la pirueta `plan` en el avance `s`. Devuelve el retraso en metros.

        Lo usa la formación, que lleva un `s` común para los dos drones. Con un
        dron solo se llama a `pirueta()`.
        """
        self._touch()
        if not self.flying or self.busy:
            return 0.0
        e = self.dron.estado()
        pose = e.ekf if e.ekf is not None else e.mocap
        if pose is None:
            raise RuntimeError("sin posicion del dron para la pirueta")
        vel, retraso = velocidad_de_espiral(plan, s, tuple(pose))
        self._registrar_objetivo("PIRUETA", punto_espiral(plan, s), None)
        vel = list(self._modificada(tuple(vel)))
        norm = math.sqrt(sum(v * v for v in vel))
        if norm > 1e-6:
            self.dron.fijar_velocidad(vel[0], vel[1], vel[2], 0.0,
                                      velocidad_mps=min(norm, self.opciones.velocidad_mps))
        return retraso

    def plan_de_pirueta(self, eje: tuple[float, float], radio_m: float, vueltas: float) -> PlanEspiral:
        """Plan de este dron para una pirueta alrededor de `eje` (formación)."""
        e = self.dron.estado()
        pose = e.ekf if e.ekf is not None else e.mocap
        if pose is None:
            raise RuntimeError("sin posicion del dron para la pirueta")
        origen = getattr(e, "origen", None)
        return plan_espiral(tuple(pose), float(origen[2]) if origen is not None else 0.0,
                            self.opciones.velocidad_mps, centro=eje, radio_m=radio_m, vueltas=vueltas)

    @staticmethod
    def avanzar_pirueta(plan: PlanEspiral, s: float, dt: float, retraso_m: float) -> float:
        return avance_espiral(plan, s, dt, retraso_m)

    def pirueta(self) -> bool:
        """Un paso de la pirueta alrededor de donde estaba el dron. `True` al terminar."""
        if not self.flying or self.busy:
            self._touch()
            return False
        if self._espiral is None:
            e = self.dron.estado()
            pose = e.ekf if e.ekf is not None else e.mocap
            if pose is None:
                raise RuntimeError("sin posicion del dron para la pirueta")
            origen = getattr(e, "origen", None)
            plan = plan_espiral(tuple(pose), float(origen[2]) if origen is not None else 0.0,
                                self.opciones.velocidad_mps)
            self._espiral = [plan, 0.0, ahora()]
            self.log(f"Pirueta: {plan.vueltas:.0f} vueltas de {plan.radio_m:.2f} m bajando de "
                     f"{plan.z_alta:.2f} a {plan.z_baja:.2f} m y subida por el eje, "
                     f"~{plan.t_bajada_s + plan.t_subida_s:.0f} s.")
        plan, s, t_previo = self._espiral
        t = ahora()
        retraso = self.pirueta_paso(plan, s)
        self._espiral = [plan, avance_espiral(plan, s, min(0.2, t - t_previo), retraso), t]
        if self._espiral[1] >= 2.0 and retraso <= 0.10:
            self._espiral = None
            self._frenar()
            return True
        return False

    def _modificada(self, vel: tuple[float, float, float]) -> tuple[float, float, float]:
        if self.modificar_velocidad is not None:
            vel = tuple(float(c) for c in self.modificar_velocidad(vel))
        if self._marker_vigilado is not None and self.exclusion_marker_m > 0.0:
            try:
                marker = self._marker_vigilado.marker_position()
            except Exception:                      # sin marker reciente no hay zona que guardar
                return vel
            e = self.dron.estado()
            pose = e.mocap if e.mocap is not None else e.ekf
            if pose is not None:
                vel = fuera_del_marker(vel, tuple(pose), tuple(marker), self.exclusion_marker_m)
        return vel

    @staticmethod
    def _z_alcanzable(z: float, estado) -> float:
        origen = getattr(estado, "origen", None)
        return altura_alcanzable(z, float(origen[2]) if origen is not None else 0.0)

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
        desired = (desired[0], desired[1], self._z_alcanzable(desired[2], e))
        self._registrar_objetivo("SEGUIR", desired, None)
        vel = []
        for objetivo, actual in zip(desired, pose):
            error = objetivo - actual
            vel.append(0.0 if abs(error) <= SEGUIR_ZONA_MUERTA_M else SEGUIR_KP * error)
        vel = list(self._modificada(tuple(vel)))
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
    "PlanEspiral", "VueloRobotat", "altura_alcanzable", "avance_espiral", "opciones_camara",
    "plan_espiral", "plan_orbita", "punto_espiral",
    "SEGUIR_KP", "SEGUIR_VELOCIDAD_MPS", "SEGUIR_ZONA_MUERTA_M",
    "ORBITA_RADIO_M", "ORBITA_VELOCIDAD_MPS", "ORBITA_KP",
    "VISION_DEADMAN_S", "VISION_LOST_LAND_S", "VELOCIDAD_MAX_CAMARA_MPS",
    "LAND_DURATION_S", "TAKEOFF_DURATION_S",
]
