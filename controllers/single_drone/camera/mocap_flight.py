"""Vuelo del Dron 1 con el posicionamiento del Robotat, para control corporal.

Expone **la misma interfaz que `CameraFlight`** —`connect`, `close`, `flying`,
`busy`, `height_m`, `request_takeoff`, `request_land`, `set_velocity`, `hover`,
`emergency_stop`— para que `control_corporal_dron1.py` no tenga que saber cual
de los dos esta usando. El reconocimiento de gestos, el panel y el CSV son
identicos con Flow deck y con mocap.

Por que hace falta un backend aparte
------------------------------------
No es una variante del de Flow deck: son **configuraciones de firmware
mutuamente excluyentes**.

    Flow deck                        Mocap del Robotat
    -----------------------------    --------------------------------------
    deck.bcFlow2 obligatorio         no hace falta ningun deck
    commander.enHighLevel = 1        commander.enHighLevel = 0
    MotionCommander                  cf.commander.send_velocity_world_setpoint
    take_off()/land() bloqueantes    rampas propias sobre el setpoint
    altura por stateEstimate.z       posicion absoluta por MQTT + extpos

`MotionCommander` **es** el commander de alto nivel, asi que apagarlo lo
inutiliza. De ahi que este archivo vuele en un lazo propio: el setpoint de
velocidad caduca en el firmware, y hay que reenviarlo.

Lo que el mocap permite y el Flow deck no
-----------------------------------------
* **Geofence de verdad.** `MAX_RADIUS_M` necesita posicion absoluta.
* **Altura absoluta**, no integrada desde el despegue.
* **Perdida de tracking detectable**: sin poses frescas se corta, en vez de
  seguir volando a ciegas.

Lo que el mocap NO resuelve
---------------------------
Saber hacia donde mira el **operador**. `send_velocity_world_setpoint` manda en
el marco de la sala, y el gesto esta en el marco del operador; hace falta el
angulo entre ambos. El rumbo del *dron* deja de importar —eso si lo resuelve el
marco del mundo— pero el del operador hay que darlo, con `--rumbo` o con un
marcador puesto encima. Ver `control_corporal_dron1.py`.

Seguridad
---------
La envolvente (altura, radio, velocidades, timeout de mocap) se importa de
`controllers/joystick/control_with_marker.py`, que es donde se ajusto volando.
No se redefine aqui: si hay que cambiarla, se cambia alli y valen las dos.
"""

from __future__ import annotations

import math
import sys
import threading
import time
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = MODULE_DIR.parents[2]
JOYSTICK_DIR = PROJECT_DIR / "controllers" / "joystick"
SHARED_DIR = PROJECT_DIR / "controllers" / "shared"
for directory in (JOYSTICK_DIR, SHARED_DIR):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import cflib.crtp  # noqa: E402,F401  (lo inicializa el lanzador)
from cflib.crazyflie import Crazyflie  # noqa: E402
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie  # noqa: E402

# La envolvente de vuelo y el receptor MQTT ya existen y estan probados en el
# controlador de marker. Se importan en vez de copiarse para que no haya dos
# limites de altura distintos en el repositorio.
from control_with_marker import (  # noqa: E402
    CONTROL_PERIOD_S,
    MAX_HEIGHT_M,
    MAX_RADIUS_M,
    MAX_VERTICAL_SPEED_M_S,
    MIN_HEIGHT_M,
    MOCAP_TIMEOUT_S,
    VERTICAL_KP,
    clamp,
    configure_for_mocap,
)
from crazyflie_link import arm_if_supported, stop_motors  # noqa: E402
from marker_mocap import MocapReceiver, Pose  # noqa: E402

#: Altura de hover sobre el punto de despegue. Mas baja que la del marker
#: (0.50 m) porque aqui el operador esta gesticulando y conviene margen.
ALTURA_HOVER_M = 0.45

#: Tolerancia para dar por terminado el despegue.
TOLERANCIA_DESPEGUE_M = 0.08

#: Tope del despegue y del aterrizaje antes de rendirse.
LIMITE_MANIOBRA_S = 12.0

#: Velocidad de descenso en el aterrizaje.
DESCENSO_M_S = 0.10

#: Altura sobre el punto de despegue a la que se dan por apagados los motores.
SUELO_M = 0.04

# Watchdog de vision, en dos etapas. Los mismos valores que
# `control_camara_flowdeck_dron1.py`: sin ordenes frescas primero se detiene el
# movimiento, y si el silencio persiste se aterriza. Una camara colgada no debe
# dejar el dron en hover hasta agotar la bateria.
VISION_DEADMAN_S = 0.40
VISION_LOST_LAND_S = 2.00


class MocapFlight:
    """Mantiene radio, mocap y lazo de velocidad para el Dron 1."""

    def __init__(
        self,
        uri: str,
        *,
        topico_dron: str,
        broker: str,
        puerto: int,
        id_dron: int | None = None,
        altura_hover_m: float = ALTURA_HOVER_M,
        radio_max_m: float = MAX_RADIUS_M,
    ) -> None:
        self.uri = uri
        self.altura_hover_m = altura_hover_m
        self.radio_max_m = radio_max_m

        self.dron_rx = MocapReceiver(
            topico_dron, broker, puerto, required_identifier=id_dron
        )
        self.link: SyncCrazyflie | None = None
        self.cf: Crazyflie | None = None

        self.flying = False
        self.busy = False
        self.emergency = False
        self._aterrizando = False
        self.lock = threading.RLock()

        self.pose_despegue: Pose | None = None
        self.objetivo_z: float | None = None
        self._suelo_z: float | None = None
        self._comando = (0.0, 0.0, 0.0)          # vx, vy en mundo; vz en m/s
        self.ultima_orden = time.monotonic()
        self.motion_active = False
        self.estado = "sin conectar"

        self._parar = threading.Event()
        self._lazo = threading.Thread(
            target=self._lazo_de_control, name="mocap-control", daemon=True
        )
        self._maniobra: threading.Thread | None = None

    # -- Conexion ------------------------------------------------------------

    def connect(self) -> None:
        print(f"Escuchando el mocap en {self.dron_rx.topic}...")
        self.dron_rx.start()
        pose = self._esperar_mocap()
        self._suelo_z = pose.z
        print(f"Pose del dron recibida: x={pose.x:+.2f} y={pose.y:+.2f} "
              f"z={pose.z:+.2f} m")

        print(f"Conectando el Dron 1 mediante {self.uri}...")
        self.link = SyncCrazyflie(self.uri, cf=Crazyflie(rw_cache="./cache/mocap"))
        self.link.open_link()
        self.cf = self.link.cf

        print("Configurando el EKF para posicion externa...")
        configure_for_mocap(self.cf)
        # Sin MotionCommander no hay nadie que arme por nosotros. En cflib
        # antigua esta llamada no hace nada, que es el comportamiento de hoy
        # del controlador de marker.
        arm_if_supported(self.cf)

        self._lazo.start()
        self.estado = "en tierra"
        print("Preflight terminado. La camara todavia no enciende los motores.")

    def _esperar_mocap(self, espera_s: float = 10.0) -> Pose:
        limite = time.monotonic() + espera_s
        while time.monotonic() < limite:
            pose = self.dron_rx.fresh_pose(MOCAP_TIMEOUT_S)
            if pose is not None:
                return pose
            time.sleep(0.05)
        detalle = self.dron_rx.error or "no llego ninguna pose"
        raise RuntimeError(
            f"Sin poses del mocap en {self.dron_rx.topic}: {detalle}. "
            f"Revisa el broker, el topico y el identificador del Dron 1."
        )

    def _pose(self) -> Pose | None:
        return self.dron_rx.fresh_pose(MOCAP_TIMEOUT_S)

    # -- Estado --------------------------------------------------------------

    @property
    def height_m(self) -> float | None:
        """Altura sobre el punto de despegue, o `None` si no hay mocap."""
        pose = self._pose()
        if pose is None:
            return None
        referencia = (
            self.pose_despegue.z if self.pose_despegue is not None
            else self._suelo_z
        )
        return pose.z - referencia if referencia is not None else pose.z

    # -- Maniobras -----------------------------------------------------------

    def _lanzar(self, trabajo, nombre: str) -> bool:
        with self.lock:
            if self.busy or self.emergency:
                return False
            self.busy = True

        def worker() -> None:
            try:
                trabajo()
            except Exception as error:
                print(f"ERROR durante el {nombre}: {error}")
            finally:
                with self.lock:
                    self.busy = False

        hilo = threading.Thread(target=worker, name=nombre, daemon=True)
        with self.lock:
            self._maniobra = hilo
        hilo.start()
        return True

    def request_takeoff(self) -> bool:
        return self._lanzar(self._despegar, "despegue")

    def request_land(self, reason: str = "gesto") -> bool:
        return self._lanzar(lambda: self._aterrizar(reason), "aterrizaje")

    def _despegar(self) -> None:
        with self.lock:
            if self.flying or self.cf is None:
                return
        pose = self._pose()
        if pose is None:
            print("No se despega: no hay pose fresca del mocap.")
            return

        print(f"Gesto DESPEGAR confirmado. Subiendo a {self.altura_hover_m:.2f} m.")
        with self.lock:
            self.pose_despegue = pose
            self.objetivo_z = pose.z + self.altura_hover_m
            self._comando = (0.0, 0.0, 0.0)
            self.motion_active = False
            self.ultima_orden = time.monotonic()
            self.flying = True
            self.estado = "despegando"

        # El lazo ya vuela hacia `objetivo_z`; aqui solo se espera a llegar
        # para que el panel no diga VOLANDO mientras todavia sube.
        limite = time.monotonic() + LIMITE_MANIOBRA_S
        while time.monotonic() < limite:
            if self.emergency or not self.flying:
                return
            altura = self.height_m
            if altura is not None and abs(altura - self.altura_hover_m) <= TOLERANCIA_DESPEGUE_M:
                break
            time.sleep(CONTROL_PERIOD_S)
        with self.lock:
            self.estado = "volando"
        print("Altura de hover alcanzada.")

    def _aterrizar(self, razon: str) -> None:
        """Pide el descenso y espera; **no manda setpoints**.

        El lazo de control es el unico que escribe en el commander. Si esta
        maniobra tambien enviara, los dos setpoints se pisarian a 20 Hz y el
        dron obedeceria al ultimo que llegase.
        """
        with self.lock:
            if not self.flying or self.cf is None:
                return
            self.estado = f"aterrizando ({razon})"
            self.motion_active = False
            self._aterrizando = True
            suelo = (
                self.pose_despegue.z if self.pose_despegue is not None
                else -math.inf
            )
        print(f"Aterrizando ({razon})...")

        limite = time.monotonic() + LIMITE_MANIOBRA_S
        try:
            while time.monotonic() < limite:
                if self.emergency:
                    return
                pose = self._pose()
                if pose is None or pose.z <= suelo + SUELO_M:
                    break
                time.sleep(CONTROL_PERIOD_S)
        finally:
            with self.lock:
                self.flying = False          # el lazo deja de enviar
                self._aterrizando = False
            self._apagar_motores()
            with self.lock:
                self.objetivo_z = None
                self.pose_despegue = None
                self._comando = (0.0, 0.0, 0.0)
                self.estado = "en tierra"
        print("Aterrizaje completado.")

    # -- Comandos ------------------------------------------------------------

    def set_velocity(self, vx: float, vy: float, vz: float) -> None:
        """Referencia de velocidad **en el marco de la sala**, en m/s.

        `vz` no se manda tal cual: mueve el *objetivo* de altura, y el lazo lo
        sostiene con un control proporcional. Asi, al soltar el gesto el dron
        se queda a la altura a la que llego en vez de quedarse sin referencia.
        """
        with self.lock:
            if not self.flying or self.busy or self.emergency:
                return
            self._comando = (vx, vy, vz)
            self.motion_active = any(abs(v) > 1e-6 for v in (vx, vy, vz))
            self.ultima_orden = time.monotonic()

    def hover(self) -> None:
        with self.lock:
            if self.flying and not self.busy:
                self._comando = (0.0, 0.0, 0.0)
                self.motion_active = False
            self.ultima_orden = time.monotonic()

    def emergency_stop(self) -> None:
        with self.lock:
            if self.cf is None:
                return
            self.emergency = True
            self.flying = False
            self._aterrizando = False
            self.motion_active = False
            self._comando = (0.0, 0.0, 0.0)
            self.estado = "EMERGENCIA"
        self._apagar_motores()

    # -- Lazo ----------------------------------------------------------------

    def _lazo_de_control(self) -> None:
        """Alimenta el EKF y sostiene el setpoint. Corre siempre.

        El `extpos` se manda tambien en tierra: es lo que hace converger al
        Kalman antes del despegue.
        """
        while not self._parar.wait(CONTROL_PERIOD_S):
            pose = self._pose()
            if pose is not None and self.cf is not None:
                try:
                    self.cf.extpos.send_extpos(pose.x, pose.y, pose.z)
                except Exception:
                    pass

            with self.lock:
                volando = self.flying and not self.emergency
                ocupado = self.busy
                aterrizando = self._aterrizando
                comando = self._comando
                silencio = time.monotonic() - self.ultima_orden
                objetivo = self.objetivo_z
                despegue = self.pose_despegue
            if not volando:
                continue

            if pose is None:
                print("Mocap perdido en vuelo: PARADA DE EMERGENCIA.")
                self.emergency_stop()
                continue

            if aterrizando:
                # Descenso a velocidad fija, sin objetivo de altura: el
                # objetivo tiene un piso (MIN_HEIGHT_M) que impediria bajar.
                self._enviar(0.0, 0.0, -DESCENSO_M_S)
                continue

            # Watchdog de vision. La etapa 2 no se dispara durante una
            # maniobra, que ya sabe lo que hace.
            if silencio >= VISION_LOST_LAND_S and not ocupado:
                print(f"Sin ordenes de la camara durante {silencio:.1f} s: "
                      f"aterrizando.")
                self.request_land("watchdog de vision")
                continue
            if silencio >= VISION_DEADMAN_S or ocupado:
                # Etapa 1, y tambien durante el despegue: solo control de
                # altura, sin desplazamiento horizontal.
                comando = (0.0, 0.0, 0.0)

            vx, vy, vz_pedido = comando
            objetivo = self._nuevo_objetivo(objetivo, despegue, vz_pedido)
            vx, vy = self._recortar_por_radio(pose, despegue, vx, vy)
            vz = 0.0
            if objetivo is not None:
                vz = clamp(VERTICAL_KP * (objetivo - pose.z),
                           -MAX_VERTICAL_SPEED_M_S, MAX_VERTICAL_SPEED_M_S)
            with self.lock:
                self.objetivo_z = objetivo
            self._enviar(vx, vy, vz)

    def _nuevo_objetivo(self, objetivo, despegue, vz_pedido: float):
        """Integra la peticion vertical dentro de la ventana de altura."""
        if objetivo is None or despegue is None:
            return objetivo
        objetivo = objetivo + vz_pedido * CONTROL_PERIOD_S
        return clamp(objetivo, despegue.z + MIN_HEIGHT_M,
                     despegue.z + MAX_HEIGHT_M)

    def _recortar_por_radio(self, pose, despegue, vx: float, vy: float):
        """Anula la componente que se aleja mas alla del radio permitido.

        Se recorta solo lo que **sale**: dentro del limite no estorba, y en el
        limite el operador siempre puede volver hacia adentro.
        """
        if despegue is None:
            return vx, vy
        dx, dy = pose.x - despegue.x, pose.y - despegue.y
        if math.hypot(dx, dy) < self.radio_max_m:
            return vx, vy
        if dx * vx + dy * vy <= 0.0:
            return vx, vy
        with self.lock:
            self.estado = "limite horizontal alcanzado"
        return 0.0, 0.0

    def _enviar(self, vx: float, vy: float, vz: float) -> None:
        if self.cf is None:
            return
        try:
            self.cf.commander.send_velocity_world_setpoint(vx, vy, vz, 0.0)
        except Exception as error:
            print(f"No se pudo enviar el setpoint: {error}")

    def _apagar_motores(self) -> None:
        if self.cf is None:
            return
        error = stop_motors(self.cf, repeats=15, interval_s=0.03, zero_velocity_first=True)
        if error is not None:
            print(f"Error al apagar motores: {error}")

    # -- Cierre --------------------------------------------------------------

    def close(self) -> None:
        # El aterrizaje va PRIMERO y el lazo se para despues: el descenso lo
        # ejecuta el lazo, asi que pararlo antes dejaria el dron en el aire
        # esperando un setpoint que ya no llega.
        hilo = self._maniobra
        if hilo is not None and hilo.is_alive():
            hilo.join(timeout=LIMITE_MANIOBRA_S + 2.0)

        if self.flying and not self.emergency:
            try:
                self._aterrizar("cierre")
            except Exception as error:
                print(f"No se pudo completar el aterrizaje: {error}")

        self._parar.set()
        if self._lazo.is_alive():
            self._lazo.join(timeout=1.0)
        if not self.emergency:
            self._apagar_motores()

        self.dron_rx.stop()
        if self.link is not None:
            try:
                self.link.close_link()
            except Exception:
                pass
            self.link = None
            self.cf = None
