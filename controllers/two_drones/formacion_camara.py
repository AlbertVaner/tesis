"""Dos Crazyflies como uno solo para un controlador por camara: formacion.

Por que existe
--------------
El controlador por gestos de un dron (`single_drone/camera/control_camara_dron1.py`)
habla con un objeto de vuelo de interfaz pequena: `request_takeoff`,
`request_land`, `set_velocity`, `hover`, `follow_marker`, `orbit_marker`,
`emergency_stop`. `VueloFormacion` ofrece **esa misma interfaz sobre dos
vuelos**, de modo que el mismo vocabulario de gestos manda a los dos drones a
la vez sin que el controlador sepa cuantos hay.

Vive en `two_drones/` porque lo que hace es coordinar dos Crazyflies (regla 2
de `AGENTS.md`). No importa nada de `single_drone/`: recibe los vuelos ya
construidos y los trata por su interfaz. Quien los construye y los envuelve es
el controlador, que es el punto de composicion.

Que significa cada orden con dos drones
---------------------------------------
* **Despegar, aterrizar, paro, emergencia**: los dos.
* **Direcciones (gestos estaticos)**: la misma velocidad a los dos. Se mueven
  en paralelo y conservan la separacion que tenian.
* **Seguir el marker (`ven_aca`)**: cada dron tiene su ancla. Las anclas no se
  dejan donde caigan: dos drones que estaban del mismo lado del marker
  acabarian a 15 cm uno del otro. Se reparten a `+-MEDIO_ANGULO_SEGUIR_DEG`
  alrededor de la direccion media, cada dron en su lado para que no se crucen.
* **Orbitar (`circulo`)**: los dos sobre el mismo circulo, **en oposicion**. No
  basta con que cada uno persiga su punto: a la misma velocidad conservarian
  el desfase con el que entraron, que puede ser de un palmo. Se regula la
  velocidad de cada uno segun el desfase hasta llevarlo a 180 grados.

Seguridad
---------
`SupervisorSeparacion` (el de `robotat_backend.py`) vigila en un hilo propio y
aterriza a los dos si se acercan a menos de 30 cm. Y no se despega con los
drones a menos de 50 cm. Si uno aterriza solo (bateria, geocerca, watchdog),
el otro aterriza tambien: una formacion de un dron no es lo que se pidio.
"""

from __future__ import annotations

import math
from typing import Any, Callable

from robotat_backend import SEPARACION_INICIAL_M, SupervisorSeparacion

#: Medio angulo entre las dos anclas del seguimiento, visto desde el marker.
#: Con el radio de seguimiento de 0.45 m, 50 grados dejan las anclas a
#: 2 * 0.45 * sin(50) = 0.69 m, mas del doble del minimo del supervisor.
#:
#: Eran 50 grados (0.69 m). Con la repulsion actuando desde 0.80 m hacen falta
#: mas: 70 grados dejan las anclas a 2 * 0.45 * sin(70) = 0.85 m.
MEDIO_ANGULO_SEGUIR_DEG = 70.0

#: Radio minimo de la orbita con dos drones. En oposicion quedan a dos radios:
#: con 0.50 son 1.0 m en el mejor caso y no sobra nada.
RADIO_ORBITA_MIN_M = 0.60

# Pirueta en formacion
# --------------------
# Con un dron la espiral se abre y se cierra sobre su propio eje. Con dos no
# puede: acabarian los dos en el mismo eje. El eje es el punto medio entre
# ambos, que los deja **ya en oposicion**, y el radio se mantiene casi
# constante: bajan por una doble helice y suben cada uno en vertical desde donde
# termino. El avance `s` es comun, asi que si uno se retrasa el otro le espera y
# la oposicion no se rompe.
PIRUETA_RADIO_MIN_M = 0.45
PIRUETA_RADIO_MAX_M = 0.70
PIRUETA_VUELTAS = 1.5

# Geocerca comun
# --------------
# Cada `DronRobotat` tiene su geocerca centrada en **su propio** punto de
# despegue. Con dos drones eso no vale: el 2026-09-18 a las 18:05 despegaron a
# 1.54 m uno del otro con `--radio-max 1.0`, y la zona donde los dos podian
# estar a la vez era una lente de **0.46 m de ancho**. Al orbitar dentro de
# ella cada cerca quitaba la componente hacia fuera y empujaba a su dron hacia
# dentro, es decir, **hacia el otro**, y como la cerca se aplica despues que la
# repulsion, ganaba. Llegaron a 0.28 m. En formacion la cerca es una sola, con
# el centro en el punto medio de los dos despegues (o el de `--centro-geocerca`).
#: Holgura minima entre cada dron en el suelo y el borde de la cerca comun.
MARGEN_GEOCERCA_MIN_M = 0.30

#: Reparto de velocidad en la orbita. Los dos van a `ESCALA_BASE` del tope; el
#: que va por delante del desfase deseado frena y el otro acelera, con
#: `GANANCIA_DESFASE` por radian de error, sin salir de los limites.
#:
#: Eran 0.55 y 0.25. En el vuelo del 2026-09-18 a las 17:33 no bastaron: los
#: drones entraron a 52 grados uno del otro y, con el horizontal ademas
#: estrangulado por el error en Z, cerraban el desfase a unos 8 grados por
#: segundo. El operador movio el marker 1.3 m en 3 s, los dos quedaron del
#: mismo lado del circulo y llegaron a 0.29 m: aterrizo el supervisor.
ESCALA_BASE = 0.75
ESCALA_MIN = 0.35
ESCALA_MAX = 1.00
GANANCIA_DESFASE = 0.50

# Repulsion entre drones
# ----------------------
# El reparto de anclas y el desfase de la orbita separan a los drones **cuando
# la geometria acompana**. No la acompana siempre: el centro de la orbita es un
# marker que lleva una persona en la mano. La repulsion no depende de nada de
# eso: mira la distancia horizontal entre los dos y, por debajo de
# `DISTANCIA_REPULSION_M`, empuja a cada uno en la direccion opuesta al otro y
# le va quitando peso a la orden original hasta anularla en `DISTANCIA_DURA_M`.
# El supervisor (0.30 m) sigue siendo la ultima red, no la primera.
#: Eran 0.60 y 0.40. En el vuelo de las 18:05 los drones siguieron acercandose
#: 3 s despues de entrar en la zona: la respuesta del dron es lenta y hace
#: falta empezar antes.
DISTANCIA_REPULSION_M = 0.80
DISTANCIA_DURA_M = 0.55
GANANCIA_REPULSION = 1.5          # (m/s) por metro dentro de la zona
REPULSION_MAX_MPS = 0.30


def velocidad_con_repulsion(
    vel: tuple[float, float, float],
    propio: tuple[float, float, float],
    otro: tuple[float, float, float],
) -> tuple[float, float, float]:
    """`vel` corregida para que este dron no se acerque al otro.

    Solo en horizontal: los dos vuelan a la misma altura y separarlos en Z los
    llevaria contra el techo o el suelo del modo fluido.
    """
    dx, dy = propio[0] - otro[0], propio[1] - otro[1]
    d = math.hypot(dx, dy)
    if d >= DISTANCIA_REPULSION_M:
        return vel
    if d < 1e-6:
        ux, uy = 1.0, 0.0                      # superpuestos: cualquier direccion vale
    else:
        ux, uy = dx / d, dy / d
    empuje = min(REPULSION_MAX_MPS, GANANCIA_REPULSION * (DISTANCIA_REPULSION_M - d))
    # Peso de la orden original: 1 en el borde de la zona, 0 en la distancia dura.
    peso = max(0.0, min(1.0, (d - DISTANCIA_DURA_M) / (DISTANCIA_REPULSION_M - DISTANCIA_DURA_M)))
    vx, vy = vel[0] * peso, vel[1] * peso
    # De lo que quede de la orden, fuera la parte que acerca al otro.
    hacia = -(vx * ux + vy * uy)
    if hacia > 0.0:
        vx, vy = vx + hacia * ux, vy + hacia * uy
    return vx + empuje * ux, vy + empuje * uy, vel[2]


def escalas_de_orbita(fase_a: float, fase_b: float) -> tuple[float, float]:
    """Escala de velocidad de cada dron para llevar su desfase a 180 grados.

    `fase_*` son los angulos de cada dron sobre el circulo, en radianes, y la
    orbita es antihoraria. `desfase` es cuanto va A por delante de B. Si es
    menos de media vuelta, A tiene que adelantarse: A acelera y B frena; si es
    mas, al reves. En oposicion exacta los dos van a `ESCALA_BASE`.
    """
    desfase = (fase_a - fase_b) % (2.0 * math.pi)
    error = math.pi - desfase                  # > 0: A tiene que adelantarse
    ajuste = GANANCIA_DESFASE * error
    limitar = lambda v: max(ESCALA_MIN, min(ESCALA_MAX, v))  # noqa: E731
    return limitar(ESCALA_BASE + ajuste), limitar(ESCALA_BASE - ajuste)


def posiciones_de_anclaje(
    marker: tuple[float, float, float],
    poses: dict[str, tuple[float, float, float]],
    medio_angulo_deg: float = MEDIO_ANGULO_SEGUIR_DEG,
) -> dict[str, tuple[float, float, float]]:
    """Posiciones ficticias desde las que anclar a dos drones al marker.

    `CameraMarkerFollower.activate` pone el ancla de cada dron en la direccion
    en la que ese dron estaba respecto al marker. Dandole posiciones ficticias
    se elige esa direccion: la media de los dos, girada `+-medio_angulo`. Cada
    dron se queda con el lado en el que ya estaba, para que al ir a su ancla no
    se cruce con el otro.
    """
    (ka, pa), (kb, pb) = list(poses.items())[:2]
    ax, ay = pa[0] - marker[0], pa[1] - marker[1]
    bx, by = pb[0] - marker[0], pb[1] - marker[1]
    mx, my = ax + bx, ay + by
    if math.hypot(mx, my) < 1e-6:              # uno a cada lado del marker: ya estan bien
        return {ka: tuple(pa), kb: tuple(pb)}
    medio = math.atan2(my, mx)
    # Signo del lado de A respecto a la direccion media (producto vectorial).
    lado_a = 1.0 if (mx * ay - my * ax) >= 0.0 else -1.0
    delta = math.radians(medio_angulo_deg)
    salida = {}
    for clave, pose, lado in ((ka, pa, lado_a), (kb, pb, -lado_a)):
        angulo = medio + lado * delta
        salida[clave] = (marker[0] + math.cos(angulo), marker[1] + math.sin(angulo), float(pose[2]))
    return salida


class SeguidorFormacion:
    """El seguidor del marker visto por el controlador como si hubiera un dron.

    El controlador pregunta `active(clave)` y llama `deactivate((clave,))` con
    la clave de **un** dron. En formacion esas dos operaciones valen para todos
    los drones; lo demas se delega tal cual.
    """

    def __init__(self, seguidor: Any, claves: tuple[str, ...]) -> None:
        self._seguidor = seguidor
        self._claves = tuple(claves)

    def active(self, _clave: str | None = None) -> bool:
        return any(self._seguidor.active(c) for c in self._claves)

    def deactivate(self, _claves=None) -> None:
        self._seguidor.deactivate(self._claves)

    def __getattr__(self, nombre: str) -> Any:
        return getattr(self._seguidor, nombre)


class VueloFormacion:
    """Varios vuelos con la interfaz de uno. Pensado y probado para dos."""

    def __init__(self, vuelos: dict[str, Any], *, log: Callable[[str], None] = print,
                 vigilar_separacion: bool = True) -> None:
        if len(vuelos) < 2:
            raise ValueError("una formacion necesita al menos dos vuelos")
        self.vuelos = dict(vuelos)
        self.log = log
        self.KEY = next(iter(self.vuelos))
        self.supervisor = (
            SupervisorSeparacion({c: v.dron for c, v in self.vuelos.items()}, log=log)
            if vigilar_separacion else None
        )
        self._estaban_volando = False
        self.repulsiones = 0
        #: [planes por dron, s, instante] de la pirueta en curso; None si no hay.
        self._pirueta: list | None = None
        #: Motivo por el que la geocerca comun no deja despegar, o None.
        self.geocerca_estrecha: str | None = None
        #: Lo mismo en una linea corta, para el panel de la camara. El
        #: 2026-09-18 el motivo solo salia por la consola: el operador hizo el
        #: gesto de despegar dos veces, no paso nada y no habia forma de saber
        #: por que mirando la ventana.
        self.aviso: str | None = None
        for vuelo in self.vuelos.values():
            if getattr(vuelo, "radio_orbita_m", RADIO_ORBITA_MIN_M) < RADIO_ORBITA_MIN_M:
                vuelo.radio_orbita_m = RADIO_ORBITA_MIN_M
        claves = list(self.vuelos)
        for clave in claves[:2]:
            otra = claves[1] if clave == claves[0] else claves[0]
            self.vuelos[clave].modificar_velocidad = self._repulsor(clave, otra)

    def vigilar_marker(self, marker_follow: Any, radio_m: float) -> None:
        """Zona de exclusion alrededor del marker, en todos los drones."""
        for vuelo in self.vuelos.values():
            vigilar = getattr(vuelo, "vigilar_marker", None)
            if vigilar is not None:
                vigilar(marker_follow, radio_m)

    def _pose(self, clave: str) -> tuple[float, float, float] | None:
        e = self.vuelos[clave].dron.estado()
        pose = e.mocap if e.mocap is not None else e.ekf
        return None if pose is None else tuple(pose)

    def _repulsor(self, propia: str, otra: str):
        def modificar(vel):
            a, b = self._pose(propia), self._pose(otra)
            if a is None or b is None:
                return vel
            nueva = velocidad_con_repulsion(tuple(vel), a, b)
            if nueva != tuple(vel):
                self.repulsiones += 1
            return nueva
        return modificar

    # -- lo que el controlador lee ------------------------------------------

    def _primero(self) -> Any:
        return self.vuelos[self.KEY]

    @property
    def opciones(self) -> Any:
        return self._primero().opciones

    @property
    def velocidad_seguir_mps(self) -> float:
        return self._primero().velocidad_seguir_mps

    @property
    def velocidad_orbita_mps(self) -> float:
        return self._primero().velocidad_orbita_mps

    @property
    def radio_orbita_m(self) -> float:
        return self._primero().radio_orbita_m

    @property
    def emergency(self) -> bool:
        return any(v.emergency for v in self.vuelos.values())

    @property
    def flying(self) -> bool:
        """En formacion solo se vuela con todos en el aire."""
        return all(v.flying for v in self.vuelos.values())

    @property
    def alguno_volando(self) -> bool:
        return any(v.flying for v in self.vuelos.values())

    @property
    def busy(self) -> bool:
        return any(v.busy for v in self.vuelos.values())

    @property
    def height_m(self) -> float | None:
        alturas = [v.height_m for v in self.vuelos.values() if v.height_m is not None]
        return min(alturas) if alturas else None

    # -- conexion -----------------------------------------------------------

    def connect(self) -> None:
        for clave, vuelo in self.vuelos.items():
            self.log(f"[formacion] preflight de {clave}")
            vuelo.connect()
        self._geocerca_comun()
        if self.supervisor is not None:
            self.supervisor.start()

    def _geocerca_comun(self) -> None:
        """Una sola geocerca para todos, y comprobar que caben dentro con holgura."""
        origenes = {}
        for clave, vuelo in self.vuelos.items():
            e = vuelo.dron.estado()
            origen = getattr(e, "origen", None) or e.mocap
            if origen is None:
                return
            origenes[clave] = origen
        opciones = [v.opciones for v in self.vuelos.values()]
        centro = next((o.centro_geocerca for o in opciones
                       if getattr(o, "centro_geocerca", None) is not None), None)
        if centro is None:
            n = len(origenes)
            centro = (sum(o[0] for o in origenes.values()) / n, sum(o[1] for o in origenes.values()) / n)
        for o in opciones:
            o.centro_geocerca = (float(centro[0]), float(centro[1]))
        radio = min(float(getattr(o, "radio_max_m", 1.0)) for o in opciones)
        lejos = {c: math.hypot(p[0] - centro[0], p[1] - centro[1]) for c, p in origenes.items()}
        peor = max(lejos, key=lejos.get)
        self.log(f"[formacion] geocerca comun: centro ({centro[0]:+.2f}, {centro[1]:+.2f}), radio {radio:.2f} m; "
                 + ", ".join(f"{c} a {d:.2f} m del centro" for c, d in lejos.items()))
        if radio - lejos[peor] < MARGEN_GEOCERCA_MIN_M:
            self.geocerca_estrecha = (
                f"{peor} esta a {lejos[peor]:.2f} m del centro de la geocerca y el radio es {radio:.2f} m: "
                f"quedan {radio - lejos[peor]:.2f} m de holgura y hacen falta {MARGEN_GEOCERCA_MIN_M:.2f}. "
                f"Acercar los drones o volar con --radio-max {lejos[peor] + 0.6:.1f}.")
            self.aviso = (f"NO DESPEGA: drones a {2 * lejos[peor]:.1f} m entre si y radio {radio:.1f}. "
                          f"Acercarlos a {2 * (radio - MARGEN_GEOCERCA_MIN_M):.1f} m o menos, "
                          f"o --radio-max {lejos[peor] + 0.6:.1f}")
            self.log("[formacion] NO SE DESPEGARA: " + self.geocerca_estrecha)

    def wait_ready(self) -> None:
        for vuelo in self.vuelos.values():
            vuelo.wait_ready()

    def set_params(self, params: dict[str, str]) -> dict[str, str]:
        aplicados: dict[str, str] = {}
        for vuelo in self.vuelos.values():
            aplicados = vuelo.set_params(params)
        return aplicados

    def separacion_m(self) -> float | None:
        poses = [v.dron.estado().mocap for v in self.vuelos.values()]
        if any(p is None for p in poses):
            return None
        return min(math.dist(a, b) for i, a in enumerate(poses) for b in poses[i + 1:])

    # -- ordenes ------------------------------------------------------------

    def request_takeoff(self) -> bool:
        if self.alguno_volando or self.busy or self.emergency:
            return False
        if self.geocerca_estrecha is not None:
            self.log("Despegue rechazado: " + self.geocerca_estrecha)
            return False
        dist = self.separacion_m()
        if dist is not None and dist < SEPARACION_INICIAL_M:
            self.aviso = (f"NO DESPEGA: drones a {dist:.2f} m entre si; "
                          f"separarlos al menos {SEPARACION_INICIAL_M:.2f} m")
            self.log("Despegue rechazado: " + self.aviso)
            return False
        self.aviso = None
        despegados = []
        for clave, vuelo in self.vuelos.items():
            if vuelo.request_takeoff():
                despegados.append(clave)
                continue
            self.log(f"[formacion] {clave} no despego: aterrizando a los demas.")
            for otro in despegados:
                self.vuelos[otro].request_land("el otro dron no despego")
            return False
        self._estaban_volando = True
        return True

    def request_land(self, reason: str = "gesto") -> bool:
        hechos = [v.request_land(reason) for v in self.vuelos.values() if v.flying or v.busy]
        self._estaban_volando = False
        return any(hechos)

    def emergency_stop(self) -> None:
        for vuelo in self.vuelos.values():
            try:
                vuelo.emergency_stop()
            except Exception as exc:  # noqa: BLE001 - hay que cortar tambien al otro
                self.log(f"[formacion] emergencia: {exc}")

    def _todos_o_ninguno(self) -> bool:
        """`True` si se puede mandar movimiento. Si uno cayo solo, aterriza el resto."""
        if self.flying:
            return not self.busy
        if self._estaban_volando and self.alguno_volando and not self.busy:
            self._estaban_volando = False
            self.log("[formacion] un dron dejo de volar: aterrizando al otro.")
            for vuelo in self.vuelos.values():
                if vuelo.flying:
                    vuelo.request_land("el otro dron dejo de volar")
        return False

    def set_velocity(self, vx: float, vy: float, vz: float) -> None:
        if not self._todos_o_ninguno():
            self._mantener_vivos()
            return
        for vuelo in self.vuelos.values():
            vuelo.set_velocity(vx, vy, vz)

    def hover(self) -> None:
        self._pirueta = None
        self._todos_o_ninguno()
        for vuelo in self.vuelos.values():
            vuelo.hover()

    def _mantener_vivos(self) -> None:
        """Sin movimiento que mandar, cada vuelo sigue oyendo a la camara.

        Cada `VueloRobotat` tiene su vigilante: 2 s sin ordenes y aterriza. Si
        mientras despegan no se les dijera nada, aterrizarian nada mas subir.
        """
        for vuelo in self.vuelos.values():
            vuelo.hover()

    def follow_marker(self, marker_follow: Any) -> None:
        if not self._todos_o_ninguno():
            self._mantener_vivos()
            return
        seguidor = getattr(marker_follow, "_seguidor", marker_follow)
        claves = tuple(self.vuelos)
        if not all(seguidor.active(c) for c in claves):
            poses = {}
            for clave, vuelo in self.vuelos.items():
                e = vuelo.dron.estado()
                pose = e.ekf if e.ekf is not None else e.mocap
                if pose is None:
                    raise RuntimeError(f"sin posicion de {clave} para seguir el marker")
                poses[clave] = tuple(pose)
            ficticias = posiciones_de_anclaje(seguidor.marker_position(), poses)
            seguidor.activate(claves, ficticias, level=True)
        for vuelo in self.vuelos.values():
            vuelo.follow_marker(seguidor)

    def pirueta(self, *, reloj: Callable[[], float] | None = None) -> bool:
        """Un paso de la pirueta en doble helice. `True` al terminar."""
        if not self._todos_o_ninguno():
            self._mantener_vivos()
            return False
        import time as _time

        t = (reloj or _time.monotonic)()
        if self._pirueta is None:
            poses = {c: self._pose(c) for c in self.vuelos}
            if any(p is None for p in poses.values()):
                raise RuntimeError("sin posicion de un dron para la pirueta")
            n = len(poses)
            eje = (sum(p[0] for p in poses.values()) / n, sum(p[1] for p in poses.values()) / n)
            lejos = max(math.hypot(p[0] - eje[0], p[1] - eje[1]) for p in poses.values())
            radio = max(PIRUETA_RADIO_MIN_M, min(PIRUETA_RADIO_MAX_M, lejos))
            planes = {}
            for clave, vuelo in self.vuelos.items():
                crear = getattr(vuelo, "plan_de_pirueta", None)
                if crear is None:
                    raise RuntimeError("la pirueta necesita --backend robotat")
                planes[clave] = crear(eje, radio, PIRUETA_VUELTAS)
            self._pirueta = [planes, 0.0, t]
            self.log(f"[formacion] pirueta en doble helice: eje ({eje[0]:+.2f}, {eje[1]:+.2f}), "
                     f"radio {radio:.2f} m, {PIRUETA_VUELTAS} vueltas.")
        planes, s, t_previo = self._pirueta
        retrasos = [self.vuelos[c].pirueta_paso(planes[c], s) for c in self.vuelos]
        primero = planes[next(iter(planes))]
        s = self.vuelos[self.KEY].avanzar_pirueta(primero, s, min(0.2, t - t_previo), max(retrasos))
        self._pirueta = [planes, s, t]
        if s >= 2.0 and max(retrasos) <= 0.10:
            self._pirueta = None
            self._mantener_vivos()
            return True
        return False

    def orbit_marker(self, marker_follow: Any) -> None:
        if not self._todos_o_ninguno():
            self._mantener_vivos()
            return
        seguidor = getattr(marker_follow, "_seguidor", marker_follow)
        centro = seguidor.marker_position()
        (ka, va), (kb, vb) = list(self.vuelos.items())[:2]
        fases = []
        for vuelo in (va, vb):
            e = vuelo.dron.estado()
            pose = e.ekf if e.ekf is not None else e.mocap
            if pose is None:
                raise RuntimeError("sin posicion de un dron para orbitar")
            fases.append(math.atan2(pose[1] - centro[1], pose[0] - centro[0]))
        escala_a, escala_b = escalas_de_orbita(fases[0], fases[1])
        va.orbit_marker(seguidor, escala_velocidad=escala_a)
        vb.orbit_marker(seguidor, escala_velocidad=escala_b)

    # -- cierre -------------------------------------------------------------

    def join(self, timeout: float | None = None) -> None:
        for vuelo in self.vuelos.values():
            vuelo.join(timeout)

    def close(self) -> None:
        if self.supervisor is not None:
            self.supervisor.stop()
        for clave, vuelo in self.vuelos.items():
            try:
                vuelo.close()
            except Exception as exc:  # noqa: BLE001 - cerrar tambien al otro
                self.log(f"[formacion] al cerrar {clave}: {exc}")
