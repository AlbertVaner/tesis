"""Un Crazyflie sobre el Robotat: preflight, despegar, mover, aterrizar, parar.

Núcleo de vuelo **por dron**: una instancia por Crazyflie, sin UI ni cámara.
Vive en `controllers/shared/` porque lo consumen tres categorías: el panel y
el adaptador de cámara de `single_drone/robotat/`, el panel dual y el
adaptador `robotat_backend.py` de `two_drones/` (y con él la web). Decisión:
`Tesis/30-Decisiones/2026-09-17 Nucleo Robotat en shared.md`.

Diseño mínimo, escrito desde cero en septiembre de 2026 para un solo dron.
El firmware vuela (commander high-level: `takeoff`, `go_to`, `land`) y este
módulo se limita a:

1. alimentar el EKF con **cada frame distinto** del Robotat (`MocapFeed`),
   opcionalmente con la orientación (`--extpose`) y con anticipo de latencia;
2. fijar los parámetros del firmware que afectan al lazo (`locSrv.extPosStdDev`
   y cualquier `--param grupo.nombre=valor`) y dejarlos registrados;
3. validar cada orden (paso máximo, geocerca, alturas) y **no solapar** un
   `go_to` con el anterior;
4. vigilar en vuelo: mocap fresco, EKF cerca del mocap, batería; y cortar
   motores si algo falla;
5. registrar un CSV por sesión con mocap, EKF, objetivo, latencia y batería.

Las decisiones vienen de `Tesis/60-Analisis/2026-09-12 Auditoría del
controlador de dos drones.md` y `2026-09-12 Oscilación en el primer vuelo por
gestos.md`. Todo lo que no es hardware está en funciones puras para probarlo
sin dron.
"""

from __future__ import annotations

import json
import math
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

MODULE_DIR = Path(__file__).resolve().parent  # controllers/shared
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from crazyflie_link import configure_estimator, stop_motors  # noqa: E402
from csv_session import CsvSession  # noqa: E402
from mocap_feed import Frame, MocapFeed  # noqa: E402
from reloj import ahora  # noqa: E402
from robotat import MOCAP_TIMEOUT_S  # noqa: E402

# -- Límites de vuelo -------------------------------------------------------
# Los mismos que el backend de la cruz, para que el dron no haga nada que no
# hiciera antes. Cambiarlos requiere autorización (AGENTS.md, seguridad).

TAKEOFF_HEIGHT_M = 0.35
TAKEOFF_DURATION_S = 4.0
LAND_HEIGHT_M = 0.03
LAND_DURATION_S = 4.0
MAX_STEP_M = 0.10
MAX_YAW_STEP_DEG = 20.0
MAX_RADIUS_FROM_ORIGIN_M = 0.50
MIN_TARGET_Z_M = 0.20
MAX_TARGET_Z_M = 1.10
#: Velocidad de crucero de un `go_to`: la duración es distancia / velocidad,
#: con un mínimo. Un paso de 0.10 m dura 1 s en vez de los 3 s anteriores.
GOTO_SPEED_MPS = 0.10
GOTO_YAW_SPEED_DPS = 20.0
GOTO_MIN_DURATION_S = 1.0
#: Movimiento continuo (tecla mantenida): cada `HOLD_PERIOD_S` se manda un
#: `go_to` al objetivo avanzado `v · periodo`, con duración `HOLD_LOOKAHEAD_S`
#: para que el siguiente llegue antes de que el planificador frene. El
#: firmware planifica cada `go_to` desde el estado *planificado* (posición,
#: velocidad y aceleración del tramo en curso), así que encadenarlos da un
#: movimiento suave; al soltar la tecla el último tramo termina en reposo.
HOLD_PERIOD_S = 0.20
HOLD_LOOKAHEAD_S = 0.45
HOLD_YAW_SPEED_DPS = 30.0
#: Dos tramos continuos más juntos que esto se descartan (protección contra
#: un teclado que repite).
HOLD_MIN_INTERVAL_S = 0.08
#: Modo fluido: mientras hay tecla se envía al firmware el mismo setpoint que
#: usa `MotionCommander` con el Flow Deck (`send_hover_setpoint`): velocidad
#: horizontal en el marco del **cuerpo**, giro en grados/s y **altura
#: absoluta**, a `FLUID_RATE_HZ` y con rampa de `FLUID_ACCEL_MPS2`. La altura
#: se integra en Python (`z += vz·dt`) y el firmware la mantiene en lazo de
#: posición. En el primer vuelo (2026-09-16 15:47) se usó velocidad en los
#: tres ejes (`send_velocity_world_setpoint`) y el dron subía 0.13 m/s con
#: cualquier tecla: sin lazo de posición en Z, el sesgo de la velocidad
#: vertical del EKF (sólo posición externa, sin medida de velocidad) se
#: convierte en deriva. Al soltar, cuando la rampa llega a cero, se devuelve
#: el mando al commander high-level con un `go_to`, que mantiene el hover sin
#: depender del enlace. La geocerca horizontal anula la componente de
#: velocidad que la cruzaría en `FLUID_LOOKAHEAD_S`; la vertical acota la
#: altura integrada.
FLUID_RATE_HZ = 20.0
FLUID_ACCEL_MPS2 = 0.6
FLUID_YAW_RATE_DPS = 45.0
FLUID_LOOKAHEAD_S = 0.6
#: Fuera de la geocerca (el dron llega al borde con inercia o lo arrastra un
#: seguimiento), además de anular la velocidad hacia fuera se **empuja hacia
#: dentro** proporcionalmente a lo que sobresale, hasta `FENCE_PUSH_MAX_MPS`.
#: Sin esto el dron se quedaba en el borde sin volver (2026-09-17).
FENCE_PUSH_KP = 1.5
FENCE_PUSH_MAX_MPS = 0.30
#: Duración del `go_to` de entrega al high-level al terminar el movimiento.
FLUID_HOLD_DURATION_S = 1.0
#: La altura mandada en modo fluido no se adelanta más que esto a la estimada
#: **en el sentido del movimiento**. Con `zKp=1` el dron sigue la altura
#: integrada con ~0.25 m de retraso a 0.25 m/s (vuelo de las 17:18 del
#: 2026-09-16: hasta 0.27 m); sin correa, al soltar la tecla el dron seguía
#: subiendo hasta alcanzar un objetivo que ya iba muy por delante. La correa
#: sólo actúa mientras se pide subir o bajar: la primera versión arrastraba el
#: objetivo también cuando el dron se desviaba solo, y eso anulaba el lazo de
#: posición en Z (vuelo de las 17:46: altura a la deriva entre 0.1 y 1.2 m
#: durante el seguimiento del marker).
FLUID_Z_LEASH_M = 0.15
#: Márgenes de la altura fluida respecto a los límites de vuelo. El dron
#: llega al objetivo con retraso y se pasa `v/zKp` (0.25 m a 0.25 m/s):
#: el 2026-09-16 a las 17:25, con el objetivo en el techo de 1.10 m, subió a
#: 1.29 m. La altura integrada se detiene antes para que el dron no cruce
#: el límite físico; hacia abajo el margen es menor porque el suelo está
#: lejos del mínimo y la velocidad de bajada frena antes.
FLUID_Z_CEILING_MARGIN_M = 0.20
FLUID_Z_FLOOR_MARGIN_M = 0.10

# -- Vigilancia ---------------------------------------------------------------
MAX_EKF_MOCAP_ERROR_M = 0.15
MIN_BATTERY_V_TAKEOFF = 3.65
#: Por debajo de este valor en reposo el despegue se acepta pero se avisa:
#: el Dron 2 cae ~0.7 V al cargar los motores y llega justo al umbral de vuelo.
WARN_BATTERY_V_TAKEOFF = 3.9
#: Tensión bajo carga a partir de la cual se aterriza solo. El 2026-09-16 un
#: vuelo limpio (error EKF 1 cm, roll 0.5°) acabó cortado a 2.99 V desde
#: 0.38 m; aterrizar es mejor que dejar caer el dron. Tiene que mantenerse
#: `LOW_BATTERY_HOLD_S` para que un pico de corriente no dispare nada.
MIN_BATTERY_V_FLIGHT = 3.0
LOW_BATTERY_HOLD_S = 0.5
#: Por debajo de esto el dron se apaga solo: corte inmediato.
CRITICAL_BATTERY_V = 2.7
MONITOR_PERIOD_S = 0.10

# -- Preflight ----------------------------------------------------------------
PREFLIGHT_TIMEOUT_S = 15.0
PREFLIGHT_STABLE_S = 2.0
PREFLIGHT_MAX_SPREAD_M = 0.030
PREFLIGHT_MIN_FRAMES = 15
PREFLIGHT_MAX_GAP_S = 0.20
EKF_ALIGNMENT_M = 0.07
EKF_ALIGNMENT_HOLD_S = 1.0
EKF_ALIGNMENT_TIMEOUT_S = 12.0
#: Desviación estándar que el EKF asigna a la posición externa. El valor de
#: fábrica (0.01 m) hace que el filtro se fíe ciegamente de una medida que
#: llega con 60 a 120 ms de retraso. Se registra siempre y se cambia con
#: `--ext-pos-std`.
DEFAULT_EXT_POS_STD_M = 0.01

#: Empuje de hover medido en el último vuelo, por dron. `cache/` está fuera
#: del control de versiones. El empuje cambia con la batería y las hélices
#: (el 2026-09-16 el mismo Dron 2 dio 46 000 y, con otra batería, 39 500), y
#: un `thrustBase` 6 000 por encima del real vuelve a oscilar la altura.
THRUST_MEMORY_PATH = Path("./cache/dron_robotat_empuje.json")
#: Inclinación máxima del rigid body en el suelo para aceptar `--extpose`.
EXTPOSE_MAX_TILT_DEG = 10.0

#: Ganancias del lazo de posición y velocidad del firmware por juego. Las de
#: fábrica (Crazyflie 2.1, posCtlPid/velCtlPid) oscilan con la posición externa
#: retrasada ~100 ms del Robotat; con la mitad en XY el hover del 2026-09-16
#: bajó de 0.69 m a 0.13 m pico a pico. `mitad` aplica lo mismo en Z.
GANANCIAS: dict[str, dict[str, str]] = {
    "fabrica": {},
    "mitad-xy": {
        "posCtlPid.xKp": "1.0", "posCtlPid.yKp": "1.0",
        "velCtlPid.vxKp": "12", "velCtlPid.vyKp": "12",
        "posCtlPid.xVelMax": "0.5", "posCtlPid.yVelMax": "0.5",
    },
    "mitad": {
        "posCtlPid.xKp": "1.0", "posCtlPid.yKp": "1.0", "posCtlPid.zKp": "1.0",
        "velCtlPid.vxKp": "12", "velCtlPid.vyKp": "12", "velCtlPid.vzKp": "12",
        "posCtlPid.xVelMax": "0.5", "posCtlPid.yVelMax": "0.5", "posCtlPid.zVelMax": "0.5",
    },
    # Juego validado el 2026-09-16 con el Dron 2 (hover de 45 s: sigma x/y/z
    # 0.027/0.041/0.032 m, roll 0.5 grados, despegue en 0.8 s con 4 cm de
    # sobrepaso): `mitad` + integrador vertical suave, empuje base igual al
    # empuje de hover medido (46 000 con la bateria a 4.0-4.2 V) y menos
    # confianza en la posicion externa retrasada. Si `LANDED` recomienda otro
    # thrustBase, pasarlo con `--param`, que manda sobre el preajuste.
    "robotat": {
        "posCtlPid.xKp": "1.0", "posCtlPid.yKp": "1.0", "posCtlPid.zKp": "1.0",
        "velCtlPid.vxKp": "12", "velCtlPid.vyKp": "12", "velCtlPid.vzKp": "12",
        "posCtlPid.xVelMax": "0.5", "posCtlPid.yVelMax": "0.5", "posCtlPid.zVelMax": "0.5",
        "velCtlPid.vzKi": "8", "posCtlPid.thrustBase": "46000",
        "locSrv.extPosStdDev": "0.0300",
    },
}


CSV_COLUMNS = [
    "t_s", "evento", "detalle", "modo",
    "mocap_x", "mocap_y", "mocap_z", "mocap_yaw_deg", "mocap_edad_s",
    "mocap_frames_hz", "mocap_hueco_max_s", "mocap_congelado", "mqtt_latencia_s", "extpos_enviados",
    "ekf_x", "ekf_y", "ekf_z", "ekf_yaw_deg", "error_ekf_mocap_m",
    "ekf_vx", "ekf_vy", "ekf_vz", "mocap_vx", "mocap_vy", "mocap_vz", "empuje_cmd",
    "objetivo_x", "objetivo_y", "objetivo_z", "objetivo_yaw_deg",
    "roll_deg", "pitch_deg", "bateria_v",
]


class DronError(RuntimeError):
    """Orden rechazada por estado o seguridad. No es una avería."""


def wrap_deg(deg: float) -> float:
    """Ángulo equivalente en [-180, 180)."""
    return (deg + 180.0) % 360.0 - 180.0


def parametros_firmware(items) -> dict[str, str]:
    """`--param grupo.nombre=valor`, repetible, como diccionario ordenado."""
    params: dict[str, str] = {}
    for item in items or ():
        nombre, sep, valor = str(item).partition("=")
        if not sep or not nombre.strip() or not valor.strip():
            raise SystemExit(f"--param espera grupo.nombre=valor, no {item!r}")
        params[nombre.strip()] = valor.strip()
    return params


@dataclass
class Move:
    """Un paso relativo validado. Se construye con `validate_step`."""

    dx: float = 0.0
    dy: float = 0.0
    dz: float = 0.0
    dyaw: float = 0.0

    def is_zero(self) -> bool:
        return all(abs(v) <= 1e-9 for v in (self.dx, self.dy, self.dz, self.dyaw))


def validate_step(dx: float, dy: float, dz: float, dyaw: float = 0.0) -> Move:
    """Aplica los límites de un paso; lanza `DronError` si se exceden."""
    values = {"dx": dx, "dy": dy, "dz": dz, "dyaw": dyaw}
    for name, raw in values.items():
        if isinstance(raw, bool):
            raise DronError(f"{name} debe ser numerico")
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise DronError(f"{name} debe ser numerico") from exc
        if not math.isfinite(value):
            raise DronError(f"{name} debe ser finito")
        values[name] = value
    for name in ("dx", "dy", "dz"):
        if abs(values[name]) > MAX_STEP_M + 1e-9:
            raise DronError(f"{name}={values[name]:+.3f} m excede el paso maximo de {MAX_STEP_M:.2f} m")
    if abs(values["dyaw"]) > MAX_YAW_STEP_DEG + 1e-9:
        raise DronError(f"dyaw={values['dyaw']:+.1f} excede el giro maximo de {MAX_YAW_STEP_DEG:.0f} grados")
    move = Move(**values)
    if move.is_zero():
        raise DronError("el paso no mueve ni gira")
    return move


def validate_target(
    target: tuple[float, float, float],
    origin: tuple[float, float, float],
    *,
    max_radius_m: float = MAX_RADIUS_FROM_ORIGIN_M,
    min_z_m: float = MIN_TARGET_Z_M,
    max_z_m: float = MAX_TARGET_Z_M,
) -> None:
    """Geocerca horizontal alrededor del origen y rango vertical absoluto."""
    if not all(math.isfinite(v) for v in target):
        raise DronError("objetivo no finito")
    radius = math.hypot(target[0] - origin[0], target[1] - origin[1])
    if radius > max_radius_m + 1e-9:
        raise DronError(f"objetivo a {radius:.2f} m del origen; maximo {max_radius_m:.2f} m")
    if not min_z_m <= target[2] <= max_z_m:
        raise DronError(f"altura {target[2]:.2f} m fuera de [{min_z_m:.2f}, {max_z_m:.2f}] m")


def goto_duration_s(distance_m: float, yaw_deg: float = 0.0, speed_mps: float = GOTO_SPEED_MPS) -> float:
    """Duración de un `go_to` proporcional a lo que hay que recorrer."""
    by_distance = abs(distance_m) / max(speed_mps, 1e-3)
    by_yaw = abs(yaw_deg) / GOTO_YAW_SPEED_DPS
    return max(GOTO_MIN_DURATION_S, by_distance, by_yaw)


def centro_geocerca(opciones: "Opciones", origen: tuple[float, float, float]) -> tuple[float, float, float]:
    """Centro de la geocerca: el fijado en las opciones o, si no hay, el origen del despegue."""
    if opciones.centro_geocerca is None:
        return origen
    return (float(opciones.centro_geocerca[0]), float(opciones.centro_geocerca[1]), origen[2])


def anticipate(frame: Frame, velocity: tuple[float, float, float] | None, lead_s: float) -> tuple[float, float, float]:
    """Posición extrapolada `p + v·τ` para compensar la latencia del mocap."""
    if lead_s <= 0.0 or velocity is None:
        return frame.xyz()
    return tuple(p + v * lead_s for p, v in zip(frame.xyz(), velocity))




def ramp_velocity(actual: float, deseada: float, dt: float, accel: float = FLUID_ACCEL_MPS2) -> float:
    """Acerca `actual` a `deseada` sin superar `accel · dt` por paso."""
    delta = deseada - actual
    limite = accel * dt
    if abs(delta) <= limite:
        return deseada
    return actual + math.copysign(limite, delta)


def world_to_body(vx: float, vy: float, yaw_deg: float) -> tuple[float, float]:
    """Velocidad horizontal del marco del mundo al del cuerpo (x nariz, y izquierda)."""
    yaw = math.radians(yaw_deg)
    c, s = math.cos(yaw), math.sin(yaw)
    return c * vx + s * vy, -s * vx + c * vy


def fence_velocity(
    pose: tuple[float, float, float],
    vel: tuple[float, float, float],
    origen: tuple[float, float, float],
    *,
    max_radius_m: float = MAX_RADIUS_FROM_ORIGIN_M,
    min_z_m: float = MIN_TARGET_Z_M,
    max_z_m: float = MAX_TARGET_Z_M,
    lookahead_s: float = FLUID_LOOKAHEAD_S,
) -> tuple[float, float, float]:
    """Quita de `vel` lo que sacaría a `pose` de la geocerca.

    Horizontal: si la posición prevista en `lookahead_s` queda fuera del radio
    y la velocidad tiene componente hacia fuera, se resta **sólo la componente
    radial** (el dron resbala por el borde) y se añade un empuje hacia dentro
    proporcional a lo que sobresale. (La primera versión anulaba la velocidad
    entera y, con el dron ya fuera del círculo por la inercia, A y D dejaban
    de responder: vuelo del 2026-09-16 a las 15:52.) Vertical: igual con los
    límites de altura.
    """
    vx, vy, vz = vel
    px, py, pz = (p + v * lookahead_s for p, v in zip(pose, vel))
    rx, ry = px - origen[0], py - origen[1]
    dist = math.hypot(rx, ry)
    if dist > max_radius_m and dist > 1e-9:
        ux, uy = rx / dist, ry / dist
        radial = vx * ux + vy * uy
        if radial > 0.0:
            vx -= radial * ux
            vy -= radial * uy
        empuje = min(FENCE_PUSH_MAX_MPS, FENCE_PUSH_KP * (dist - max_radius_m))
        vx -= empuje * ux
        vy -= empuje * uy
    if pz > max_z_m:
        vz = min(vz, 0.0) - min(FENCE_PUSH_MAX_MPS, FENCE_PUSH_KP * (pz - max_z_m))
    elif pz < min_z_m:
        vz = max(vz, 0.0) + min(FENCE_PUSH_MAX_MPS, FENCE_PUSH_KP * (min_z_m - pz))
    return vx, vy, vz


def leer_empuje_memoria(nombre: str, path: Path | None = None) -> float | None:
    """Empuje de hover guardado del último vuelo de `nombre`, o None."""
    path = THRUST_MEMORY_PATH if path is None else path
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        valor = float(data[nombre]["thrust_base"])
        return valor if math.isfinite(valor) and 20000.0 <= valor <= 60000.0 else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def guardar_empuje_memoria(nombre: str, thrust_base: float, path: Path | None = None) -> None:
    path = THRUST_MEMORY_PATH if path is None else path
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data[nombre] = {"thrust_base": round(thrust_base), "guardado": time.strftime("%Y-%m-%d %H:%M:%S")}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


def stable_origin(frames: list[Frame], max_spread_m: float = PREFLIGHT_MAX_SPREAD_M) -> tuple[float, float, float] | None:
    """Promedio de una ventana de frames si el marker estuvo quieto."""
    if len(frames) < PREFLIGHT_MIN_FRAMES:
        return None
    xs, ys, zs = zip(*(f.xyz() for f in frames))
    spread = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
    if spread > max_spread_m:
        return None
    return (sum(xs) / len(xs), sum(ys) / len(ys), sum(zs) / len(zs))


@dataclass
class Estado:
    """Lo que el panel necesita mostrar. Copia inmutable por consulta."""

    modo: str = "SIN_CONECTAR"
    detalle: str = "Ejecuta PREFLIGHT. Los motores permanecen apagados."
    listo: bool = False
    en_vuelo: bool = False
    emergencia: bool = False
    razon_emergencia: str | None = None
    mocap: tuple[float, float, float] | None = None
    mocap_yaw_deg: float | None = None
    mocap_edad_s: float | None = None
    mocap_frames_hz: float | None = None
    mocap_hueco_max_s: float | None = None
    #: La pose del Robotat lleva más de `FROZEN_AFTER_S` sin cambiar.
    mocap_congelado: bool = False
    mqtt_latencia_s: float | None = None
    extpos_enviados: int = 0
    ekf: tuple[float, float, float] | None = None
    ekf_yaw_deg: float | None = None
    error_ekf_mocap_m: float | None = None
    #: Velocidad que estima el EKF (`stateEstimate.vx/vy/vz`) y la derivada
    #: del mocap. Su diferencia en Z es el sesgo que hace oscilar la altura.
    ekf_vel: tuple[float, float, float] | None = None
    mocap_vel: tuple[float, float, float] | None = None
    #: Empuje que manda el controlador (`controller.cmd_thrust`, 0..65535).
    #: Su media en hover es el `posCtlPid.thrustBase` correcto para este dron.
    empuje_cmd: float | None = None
    origen: tuple[float, float, float] | None = None
    objetivo: tuple[float, float, float] | None = None
    objetivo_yaw_deg: float = 0.0
    roll_deg: float | None = None
    pitch_deg: float | None = None
    bateria_v: float | None = None
    ocupado_hasta_s: float = 0.0
    #: Hasta cuándo dura el despegue o el aterrizaje en curso. Los tramos
    #: continuos no se aceptan mientras tanto; los pasos esperan.
    maniobra_hasta_s: float = 0.0
    csv: str | None = None
    parametros: dict[str, str] = field(default_factory=dict)


@dataclass
class Opciones:
    """Ajustes elegidos en la línea de órdenes."""

    uri: str
    topic: str
    nombre: str = "Dron 1"
    extpose: bool = False
    anticipo_s: float = 0.0
    ext_pos_std_m: float = DEFAULT_EXT_POS_STD_M
    parametros: dict[str, str] = field(default_factory=dict)
    altura_m: float = TAKEOFF_HEIGHT_M
    radio_max_m: float = MAX_RADIUS_FROM_ORIGIN_M
    #: Velocidad de crucero de los `go_to`. 0.10 m/s es conservador; el
    #: 2026-09-16 con ganancias a la mitad cada paso tardaba ~2 s.
    velocidad_mps: float = GOTO_SPEED_MPS
    #: True si `--param posCtlPid.thrustBase=...` vino en la línea de órdenes:
    #: entonces no se sustituye por el medido en el último vuelo.
    thrust_base_explicito: bool = False
    #: Centro (x, y) de la geocerca horizontal en el marco del Robotat. Por
    #: defecto (None) es el punto de despegue, que para un vuelo a mano está
    #: bien; para seguir u orbitar un marker que se mueve por toda el área hay
    #: que centrarla en el área misma (`--centro-geocerca 0 -0.4`, por
    #: ejemplo): el 2026-09-17 el dron alcanzó el borde del círculo de 1 m
    #: alrededor de donde despegó y dejó de perseguir al marker.
    centro_geocerca: tuple[float, float] | None = None


class RegistroRobotat(CsvSession):
    """CSV de sesión que al cerrarse genera las gráficas PDF y el resumen.

    Las gráficas se generan en un proceso aparte que sobrevive al cierre: el
    backend de la cámara dual corre en un proceso hijo que el padre termina a
    los 12 s de pedirle cerrar, y el 2026-09-16 (19:34) las dos sesiones se
    quedaron sin gráficas por eso. Con `sincrono=True` se generan aquí mismo
    (pruebas y uso a mano).
    """

    sincrono = False

    def _analyze(self, path: Path) -> Path | None:
        from analizar_sesion_robotat import analyze_session, session_output_dir

        if self.sincrono:
            return analyze_session(path)
        import subprocess

        script = MODULE_DIR / "analizar_sesion_robotat.py"
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        subprocess.Popen(
            [sys.executable, str(script), str(path)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=flags, close_fds=True,
        )
        print(f"Graficas PDF en curso (proceso aparte): {session_output_dir(path)}")
        return session_output_dir(path)


class DronRobotat:
    """Un Crazyflie real. Sólo esta clase toca la Crazyradio."""

    def __init__(self, opciones: Opciones, *, log: Callable[[str], None] = print) -> None:
        self.opciones = opciones
        self.log = log
        self.feed = MocapFeed(opciones.topic, self._on_frame)
        self.csv = RegistroRobotat(CSV_COLUMNS, folder_name="dron_robotat", filename_prefix="dron_robotat")
        self._lock = threading.RLock()
        self._cf: Any = None
        self._stack: Any = None
        self._estado = Estado()
        self._ekf: Frame | None = None
        self._ekf_yaw_deg: float | None = None
        self._ekf_vel: tuple[float, float, float] | None = None
        self._empuje_cmd: float | None = None
        #: Empuje comandado durante el hover high-level (sin maniobras): su
        #: media es el `posCtlPid.thrustBase` que evita el arranque lento y el
        #: sobrepaso del despegue con esta batería.
        self._empuje_hover: list[float] = []
        self._roll = self._pitch = self._vbat = None
        self._extpos_enviados = 0
        self._ultimo_tramo_s = -1.0
        self._ultimo_vel_evento_s = -1e9
        self._bateria_baja_desde_s: float | None = None
        # Modo fluido: velocidad deseada (vx, vy, vz, yawrate), la enviada
        # (con rampa) y el hilo que la transmite.
        self._fluido_cmd = (0.0, 0.0, 0.0, 0.0)
        self._fluido_vel = [0.0, 0.0, 0.0, 0.0]
        self._fluido_z: float | None = None
        self._fluido_activo = False
        self._fluido_thread: threading.Thread | None = None
        self._log_configs: list[Any] = []
        self._stop = threading.Event()
        self._monitor: threading.Thread | None = None
        self._cerrando = False

    # -- Estado --------------------------------------------------------------

    def estado(self) -> Estado:
        with self._lock:
            e = self._estado
            frame = self.feed.frame
            stats = self.feed.stats()
            ekf = self._ekf
            e.mocap = None if frame is None else frame.xyz()
            e.mocap_yaw_deg = None if frame is None else frame.yaw_deg
            e.mocap_edad_s = self.feed.age_s()
            e.mocap_frames_hz = stats["frames_hz"]
            e.mocap_hueco_max_s = stats["hueco_max_s"]
            e.mocap_congelado = bool(stats["congelado"])
            e.mqtt_latencia_s = stats["latencia_s"]
            e.extpos_enviados = self._extpos_enviados
            e.ekf = None if ekf is None else ekf.xyz()
            e.ekf_yaw_deg = self._ekf_yaw_deg
            e.ekf_vel = self._ekf_vel
            e.mocap_vel = self.feed.velocity
            e.empuje_cmd = self._empuje_cmd
            e.error_ekf_mocap_m = (
                None if frame is None or ekf is None else math.dist(frame.xyz(), ekf.xyz())
            )
            e.roll_deg, e.pitch_deg, e.bateria_v = self._roll, self._pitch, self._vbat
            e.csv = None if self.csv.path is None else str(self.csv.path)
            return Estado(**vars(e))

    def _set(self, modo: str | None = None, detalle: str | None = None) -> None:
        with self._lock:
            if modo is not None:
                self._estado.modo = modo
            if detalle is not None:
                self._estado.detalle = detalle
        if detalle:
            self.log(f"[{self.opciones.nombre}] {detalle}")

    def _evento(self, evento: str, detalle: str = "") -> None:
        self.csv.write(self._fila(evento, detalle), flush=True)

    def _fila(self, evento: str = "", detalle: str = "") -> dict:
        e = self.estado()

        def xyz(v):
            return ("", "", "") if v is None else tuple(round(c, 4) for c in v)

        mx, my, mz = xyz(e.mocap)
        kx, ky, kz = xyz(e.ekf)
        ox, oy, oz = xyz(e.objetivo)
        kvx, kvy, kvz = xyz(e.ekf_vel)
        mvx, mvy, mvz = xyz(e.mocap_vel)
        return {
            "t_s": self.csv.elapsed_s(), "evento": evento, "detalle": detalle, "modo": e.modo,
            "mocap_x": mx, "mocap_y": my, "mocap_z": mz,
            "mocap_yaw_deg": "" if e.mocap_yaw_deg is None else round(e.mocap_yaw_deg, 2),
            "mocap_edad_s": "" if e.mocap_edad_s is None else round(e.mocap_edad_s, 4),
            "mocap_frames_hz": "" if e.mocap_frames_hz is None else round(e.mocap_frames_hz, 2),
            "mocap_hueco_max_s": "" if e.mocap_hueco_max_s is None else round(e.mocap_hueco_max_s, 4),
            "mocap_congelado": int(e.mocap_congelado),
            "mqtt_latencia_s": "" if e.mqtt_latencia_s is None else round(e.mqtt_latencia_s, 4),
            "extpos_enviados": e.extpos_enviados,
            "ekf_x": kx, "ekf_y": ky, "ekf_z": kz,
            "ekf_yaw_deg": "" if e.ekf_yaw_deg is None else round(e.ekf_yaw_deg, 2),
            "error_ekf_mocap_m": "" if e.error_ekf_mocap_m is None else round(e.error_ekf_mocap_m, 4),
            "ekf_vx": kvx, "ekf_vy": kvy, "ekf_vz": kvz,
            "empuje_cmd": "" if e.empuje_cmd is None else round(e.empuje_cmd, 0),
            "mocap_vx": mvx, "mocap_vy": mvy, "mocap_vz": mvz,
            "objetivo_x": ox, "objetivo_y": oy, "objetivo_z": oz,
            "objetivo_yaw_deg": round(e.objetivo_yaw_deg, 2),
            "roll_deg": "" if e.roll_deg is None else round(e.roll_deg, 2),
            "pitch_deg": "" if e.pitch_deg is None else round(e.pitch_deg, 2),
            "bateria_v": "" if e.bateria_v is None else round(e.bateria_v, 3),
        }

    # -- Mocap → EKF ---------------------------------------------------------

    def _on_frame(self, frame: Frame) -> None:
        """Se llama en el hilo MQTT con cada frame distinto; reenvía al EKF."""
        with self._lock:
            cf = self._cf
            velocity = self.feed.velocity
        if cf is None or self.feed.frozen():
            # Una pose repetida no es una medida: alimentarla al EKF lo clava
            # en un sitio mientras el dron se mueve.
            return
        x, y, z = anticipate(frame, velocity, self.opciones.anticipo_s)
        try:
            if self.opciones.extpose and frame.quat is not None:
                cf.extpos.send_extpose(x, y, z, *frame.quat)
            else:
                cf.extpos.send_extpos(x, y, z)
        except Exception as exc:
            self.log(f"extpos fallo: {exc}")
            return
        with self._lock:
            self._extpos_enviados += 1

    def _on_ekf(self, _timestamp, data, _logconf) -> None:
        """Bloque de posición del EKF (`stateEstimate.x/y/z/yaw`)."""
        try:
            estimate = Frame(
                float(data["stateEstimate.x"]), float(data["stateEstimate.y"]),
                float(data["stateEstimate.z"]), None, None, ahora(), None,
            )
            yaw = float(data["stateEstimate.yaw"])
        except (KeyError, TypeError, ValueError):
            return
        empuje = None
        try:
            empuje = float(data["controller.cmd_thrust"])
        except (KeyError, TypeError, ValueError):
            pass
        with self._lock:
            self._ekf = estimate
            self._ekf_yaw_deg = yaw
            if empuje is not None:
                self._empuje_cmd = empuje

    def _on_attitude(self, _timestamp, data, _logconf) -> None:
        """Bloque de actitud, batería y velocidad estimada."""
        try:
            roll = float(data["stabilizer.roll"])
            pitch = float(data["stabilizer.pitch"])
            vbat = float(data["pm.vbat"])
        except (KeyError, TypeError, ValueError):
            return
        vel: tuple[float, float, float] | None = None
        try:
            vel = (float(data["stateEstimate.vx"]), float(data["stateEstimate.vy"]), float(data["stateEstimate.vz"]))
        except (KeyError, TypeError, ValueError):
            pass
        with self._lock:
            self._roll, self._pitch, self._vbat = roll, pitch, vbat
            if vel is not None:
                self._ekf_vel = vel

    # -- Preflight -----------------------------------------------------------

    def preflight(self, progreso: Callable[[str], None] | None = None) -> None:
        """Mocap estable → radio → estimador → parámetros → EKF alineado → CSV."""
        avisar = progreso or (lambda _m: None)
        with self._lock:
            if self._estado.emergencia:
                raise DronError("emergencia enclavada; reinicia el programa")
            if self._estado.listo:
                return
        try:
            avisar("Esperando frames estables del Robotat...")
            self._set("PREFLIGHT", f"Escuchando {self.opciones.topic}")
            self.feed.start()
            origin = self._wait_stable_origin()
            with self._lock:
                self._estado.origen = origin
                self._estado.objetivo = origin
            self._comprobar_orientacion()
            stats = self.feed.stats()
            hz = stats["frames_hz"] or 0.0
            gap_ms = (stats["hueco_max_s"] or 0.0) * 1000.0
            self._set(None, f"Origen ({origin[0]:+.3f}, {origin[1]:+.3f}, {origin[2]:+.3f}) m; "
                            f"{hz:.1f} frames/s, hueco max {gap_ms:.0f} ms")

            avisar("Abriendo enlace de radio; motores apagados...")
            self._open_link()

            avisar("Configurando estimador y parametros del firmware...")
            self._configure_firmware()

            avisar("Esperando que el EKF coincida con el mocap...")
            self._wait_ekf_alignment()

            # El nombre del dron en el archivo: dos drones a la vez no deben
            # pisarse el CSV por arrancar en el mismo segundo.
            path = self.csv.start(f"dron_robotat_{self.opciones.nombre.replace(' ', '')}_{time.strftime('%Y%m%d_%H%M%S')}")
            # Parámetros del firmware y opciones de Python juntos: sin esto no
            # se puede saber después qué anticipo o desviación usó un vuelo.
            o = self.opciones
            detalle = "; ".join(f"{k}={v}" for k, v in self.estado().parametros.items())
            detalle += (f"; anticipo_s={o.anticipo_s}; extpose={o.extpose}; "
                        f"velocidad_mps={o.velocidad_mps}; radio_max_m={o.radio_max_m}; altura_m={o.altura_m}; "
                        f"centro_geocerca={'origen' if o.centro_geocerca is None else f'{o.centro_geocerca[0]:.2f},{o.centro_geocerca[1]:.2f}'}")
            self._evento("PREFLIGHT_OK", detalle)
            with self._lock:
                self._estado.listo = True
            self._set("LISTO", f"Preflight correcto. CSV: {path}")
            self._start_monitor()
        except Exception:
            self._close_link()
            raise

    def _comprobar_orientacion(self) -> None:
        """Registra la actitud del rigid body en el suelo; con `--extpose`
        exige que esté nivelado, o el EKF recibiría una actitud falsa."""
        frame = self.feed.fresh()
        if frame is None or frame.roll_deg is None or frame.pitch_deg is None or frame.yaw_deg is None:
            if self.opciones.extpose:
                raise DronError("--extpose requiere que el Robotat publique la rotacion del rigid body")
            self._set(None, "El mensaje del Robotat no trae rotacion; solo posicion al EKF")
            return
        self._set(None, f"Rigid body en el suelo (id {frame.identifier or '?'} en {self.opciones.topic}): "
                        f"roll {frame.roll_deg:+.1f}, pitch {frame.pitch_deg:+.1f}, yaw {frame.yaw_deg:+.1f} deg")
        if self.opciones.extpose and max(abs(frame.roll_deg), abs(frame.pitch_deg)) > EXTPOSE_MAX_TILT_DEG:
            raise DronError(
                f"--extpose rechazado: el rigid body no esta nivelado (roll {frame.roll_deg:+.1f}, "
                f"pitch {frame.pitch_deg:+.1f}; maximo {EXTPOSE_MAX_TILT_DEG:.0f} deg). "
                "Redefinirlo en Motive con el dron plano y la nariz a +X"
            )

    def _wait_stable_origin(self) -> tuple[float, float, float]:
        deadline = ahora() + PREFLIGHT_TIMEOUT_S
        best: float | None = None
        ultimo_aviso = -1e9
        while ahora() < deadline:
            frames = self.feed.stable_window(PREFLIGHT_STABLE_S)
            origin = stable_origin(frames)
            if origin is not None and self.feed.frozen():
                # Un aviso cada 5 s, con el valor y el tiempo que lleva igual.
                if ahora() - ultimo_aviso >= 5.0:
                    ultimo_aviso = ahora()
                    f = self.feed.frame
                    fijo = "" if f is None else f" en ({f.x:+.3f}, {f.y:+.3f}, {f.z:+.3f})"
                    desde = 0.0 if self.feed.last_change_at is None or f is None else f.received_at - self.feed.last_change_at
                    self._set(None, f"Pose del Robotat congelada{fijo} desde hace {desde:.0f} s: Motive no "
                                    f"rastrea este rigid body (id {'?' if f is None else f.identifier}). "
                                    "Comprueba en Motive que el cuerpo aparece rastreado y que sus "
                                    "marcadores se ven; esperando")
                time.sleep(0.5)
                continue
            if origin is not None:
                gap = self.feed.stats(PREFLIGHT_STABLE_S)["hueco_max_s"]
                if gap is not None and gap > PREFLIGHT_MAX_GAP_S:
                    self._set(None, f"Hueco de {gap*1000:.0f} ms en el mocap; esperando un flujo limpio")
                    time.sleep(0.5)
                    continue
                return origin
            if len(frames) >= PREFLIGHT_MIN_FRAMES:
                xs, ys, zs = zip(*(f.xyz() for f in frames))
                spread = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
                best = spread if best is None else min(best, spread)
            time.sleep(0.05)
        stats = self.feed.stats()
        if self.feed.frozen():
            raise DronError(
                f"la pose de {self.opciones.topic} lleva congelada todo el preflight: Motive no rastrea "
                "este rigid body. Revisa en Motive que aparezca rastreado (marcadores visibles, dentro del "
                "area) o muevelo con la mano y mira si cambia en ver_markers.py"
            )
        detalle = "sin frames suficientes" if best is None else f"mejor dispersion={best:.3f} m"
        raise DronError(
            f"el marker no estuvo quieto {PREFLIGHT_STABLE_S:.0f} s en {self.opciones.topic} "
            f"({detalle}; mensajes={stats['mqtt_msgs']}, frames={stats['frames']}, "
            f"invalidos={stats['mqtt_invalidos']})"
        )

    def _open_link(self) -> None:
        import cflib.crtp as crtp
        from cflib.crazyflie import Crazyflie
        from cflib.crazyflie.syncCrazyflie import SyncCrazyflie
        from contextlib import ExitStack
        from radios import resolve_serial_uris

        uri = resolve_serial_uris({"dron": self.opciones.uri}, names={"dron": self.opciones.nombre}, log=self.log)["dron"]
        crtp.init_drivers(enable_debug_driver=False)
        stack = ExitStack()
        cache = f"./cache/{self.opciones.nombre.replace(' ', '_')}_robotat"
        link = stack.enter_context(SyncCrazyflie(uri, cf=Crazyflie(rw_cache=cache)))
        with self._lock:
            self._stack = stack
            self._cf = link.cf
        self._set(None, f"Radio abierta: {uri}")

    def _configure_firmware(self) -> None:
        from cflib.crazyflie.log import LogConfig

        cf = self._cf
        configure_estimator(cf, high_level=True, settle_before_reset_s=0.5, settle_after_reset_s=0.5)
        aplicados: dict[str, str] = {}
        parametros = {"locSrv.extPosStdDev": f"{self.opciones.ext_pos_std_m:.4f}"} | self.opciones.parametros
        # thrustBase: el medido en el último vuelo de este dron manda sobre el
        # del preajuste; un `--param` explícito manda sobre los dos.
        memoria = leer_empuje_memoria(self.opciones.nombre)
        if memoria is not None and "posCtlPid.thrustBase" in parametros and not self.opciones.thrust_base_explicito:
            parametros["posCtlPid.thrustBase"] = f"{memoria:.0f}"
            self.log(f"thrustBase del ultimo vuelo: {memoria:.0f} (sustituye al del preajuste)")
        for name, value in parametros.items():
            try:
                cf.param.set_value(name, str(value))
                aplicados[name] = str(value)
            except Exception as exc:
                # Un nombre mal escrito no debe dejar el dron a medio configurar
                # sin aviso: se registra y se sigue con los demás.
                self.log(f"[param] {name}={value} NO aplicado: {exc}")
        with self._lock:
            self._estado.parametros = aplicados
        self._set(None, "Parametros: " + (", ".join(f"{k}={v}" for k, v in aplicados.items()) or "ninguno"))

        # Un bloque de log del firmware admite 26 bytes: once floats no
        # caben ("log configuration is too large"). Dos bloques de 20 y 24.
        blocks = (
            ("PosRobotat", 50, ("stateEstimate.x", "stateEstimate.y", "stateEstimate.z", "stateEstimate.yaw",
                                "controller.cmd_thrust"), self._on_ekf),
            ("ActRobotat", 100, ("stabilizer.roll", "stabilizer.pitch", "pm.vbat",
                                 "stateEstimate.vx", "stateEstimate.vy", "stateEstimate.vz"), self._on_attitude),
        )
        configs = []
        for name, period_ms, variables, callback in blocks:
            config = LogConfig(name=name, period_in_ms=period_ms)
            for variable in variables:
                config.add_variable(variable, "float")
            cf.log.add_config(config)
            config.data_received_cb.add_callback(callback)
            config.start()
            configs.append(config)
        self._log_configs = configs

    def _wait_ekf_alignment(self) -> None:
        deadline = ahora() + EKF_ALIGNMENT_TIMEOUT_S
        since: float | None = None
        while ahora() < deadline:
            e = self.estado()
            error = e.error_ekf_mocap_m
            if error is not None and e.mocap_edad_s is not None and e.mocap_edad_s < MOCAP_TIMEOUT_S:
                if error <= EKF_ALIGNMENT_M:
                    since = since or ahora()
                    if ahora() - since >= EKF_ALIGNMENT_HOLD_S:
                        self._set(None, f"EKF alineado: error {error:.3f} m; yaw EKF {e.ekf_yaw_deg:+.1f} deg, "
                                        f"yaw mocap {'n/d' if e.mocap_yaw_deg is None else f'{e.mocap_yaw_deg:+.1f} deg'}")
                        return
                else:
                    since = None
            time.sleep(0.05)
        e = self.estado()
        raise DronError(
            f"EKF y mocap no se alinearon en {EKF_ALIGNMENT_TIMEOUT_S:.0f} s "
            f"(error={e.error_ekf_mocap_m}, extpos enviados={e.extpos_enviados}, "
            f"mocap={e.mocap}, ekf={e.ekf})"
        )

    # -- Órdenes ---------------------------------------------------------------

    def _require_ready(self) -> None:
        with self._lock:
            if self._estado.emergencia:
                raise DronError("emergencia enclavada; reinicia el programa")
            if not self._estado.listo:
                raise DronError("ejecuta PREFLIGHT antes")

    def _require_free(self) -> None:
        with self._lock:
            remaining = self._estado.ocupado_hasta_s - ahora()
        if remaining > 0:
            raise DronError(f"orden anterior en curso; faltan {remaining:.1f} s")

    def esperar_libre(self, timeout_s: float = 6.0) -> bool:
        """Espera a que termine la orden en curso. False si no terminó a tiempo."""
        deadline = ahora() + timeout_s
        while ahora() < deadline:
            with self._lock:
                remaining = self._estado.ocupado_hasta_s - ahora()
            if remaining <= 0:
                return True
            time.sleep(min(remaining, 0.05))
        return False

    def takeoff(self) -> None:
        self._require_ready()
        self._require_free()
        e = self.estado()
        if e.en_vuelo:
            raise DronError("ya esta en vuelo")
        frame = self.feed.fresh()
        if frame is None:
            raise DronError("mocap no fresco")
        if e.bateria_v is not None and e.bateria_v < MIN_BATTERY_V_TAKEOFF:
            raise DronError(f"bateria {e.bateria_v:.2f} V; se requieren {MIN_BATTERY_V_TAKEOFF:.2f} V en reposo")
        if e.bateria_v is not None and e.bateria_v < WARN_BATTERY_V_TAKEOFF:
            self.log(f"AVISO: bateria {e.bateria_v:.2f} V en reposo; bajo carga quedara cerca de "
                     f"{MIN_BATTERY_V_FLIGHT:.1f} V y el vuelo puede acabar en aterrizaje automatico")
        if e.error_ekf_mocap_m is not None and e.error_ekf_mocap_m > EKF_ALIGNMENT_M:
            raise DronError(f"EKF a {e.error_ekf_mocap_m:.3f} m del mocap; no despega")
        target_z = min(frame.z + self.opciones.altura_m, MAX_TARGET_Z_M)
        # El firmware sube sin girar. Partir del rumbo que el EKF ya estima
        # evita que el primer go_to mande un giro espurio hacia yaw 0.
        yaw = 0.0 if e.ekf_yaw_deg is None else wrap_deg(e.ekf_yaw_deg)
        with self._lock:
            self._estado.objetivo = (frame.x, frame.y, target_z)
            self._estado.objetivo_yaw_deg = yaw
            self._estado.en_vuelo = True
            self._estado.ocupado_hasta_s = ahora() + TAKEOFF_DURATION_S
            self._estado.maniobra_hasta_s = ahora() + TAKEOFF_DURATION_S
        self._set("DESPEGUE", f"Despegando a {target_z:.2f} m (yaw {yaw:+.0f} deg)")
        try:
            self._cf.high_level_commander.takeoff(target_z, TAKEOFF_DURATION_S)
        except Exception as exc:
            self.emergency(f"fallo enviando takeoff: {exc}")
            raise DronError(f"fallo enviando takeoff: {exc}") from exc
        self._evento("TAKEOFF", f"z={target_z:.3f}")

    def move(self, dx: float, dy: float, dz: float, dyaw: float = 0.0) -> None:
        """Un paso relativo al objetivo actual. Rechazado si el anterior sigue en curso."""
        self._require_ready()
        step = validate_step(dx, dy, dz, dyaw)
        e = self.estado()
        if not e.en_vuelo or e.objetivo is None or e.origen is None:
            raise DronError("despega antes de mover")
        self._require_free()
        target = (e.objetivo[0] + step.dx, e.objetivo[1] + step.dy, e.objetivo[2] + step.dz)
        validate_target(target, centro_geocerca(self.opciones, e.origen), max_radius_m=self.opciones.radio_max_m)
        yaw = wrap_deg(e.objetivo_yaw_deg + step.dyaw)
        duration = goto_duration_s(math.dist(target, e.objetivo), step.dyaw, self.opciones.velocidad_mps)
        with self._lock:
            self._estado.objetivo = target
            self._estado.objetivo_yaw_deg = yaw
            self._estado.ocupado_hasta_s = ahora() + duration
        self._set("GO_TO", f"Objetivo ({target[0]:+.2f}, {target[1]:+.2f}, {target[2]:+.2f}) m, "
                           f"yaw {yaw:+.0f} deg, {duration:.1f} s")
        try:
            self._cf.high_level_commander.go_to(*target, math.radians(yaw), duration, relative=False)
        except Exception as exc:
            self.emergency(f"fallo enviando go_to: {exc}")
            raise DronError(f"fallo enviando go_to: {exc}") from exc
        self._evento("GO_TO", f"dx={step.dx:+.2f} dy={step.dy:+.2f} dz={step.dz:+.2f} dyaw={step.dyaw:+.0f} dur={duration:.1f}")

    def avanzar(self, ux: float, uy: float, uz: float, uyaw: float = 0.0) -> None:
        """Un tramo de movimiento continuo en la dirección (ux, uy, uz, uyaw).

        A diferencia de `move`, puede solapar el tramo anterior: es lo que
        hace fluido el movimiento con la tecla mantenida. La geocerca y los
        límites de altura se aplican igual al objetivo planificado.
        """
        self._require_ready()
        e = self.estado()
        if not e.en_vuelo or e.objetivo is None or e.origen is None:
            raise DronError("despega antes de mover")
        if e.maniobra_hasta_s > ahora():
            raise DronError("despegue o aterrizaje en curso")
        target, yaw, duration = plan_hold_segment(
            e.objetivo, e.objetivo_yaw_deg, (ux, uy, uz), uyaw, self.opciones.velocidad_mps
        )
        validate_target(target, e.origen, max_radius_m=self.opciones.radio_max_m)
        with self._lock:
            if ahora() - self._ultimo_tramo_s < HOLD_MIN_INTERVAL_S:
                return
            self._ultimo_tramo_s = ahora()
            self._estado.objetivo = target
            self._estado.objetivo_yaw_deg = yaw
            self._estado.ocupado_hasta_s = ahora() + duration
            self._estado.modo = "CONTINUO"
            self._estado.detalle = f"Movimiento continuo hacia ({target[0]:+.2f}, {target[1]:+.2f}, {target[2]:+.2f}) m"
        try:
            self._cf.high_level_commander.go_to(*target, math.radians(yaw), duration, relative=False)
        except Exception as exc:
            self.emergency(f"fallo enviando tramo continuo: {exc}")
            raise DronError(f"fallo enviando tramo continuo: {exc}") from exc
        self._evento("TRAMO", f"u=({ux:+.1f},{uy:+.1f},{uz:+.1f}) uyaw={uyaw:+.0f} dur={duration:.2f}")

    # -- Modo fluido: velocidad mientras hay tecla -----------------------------

    def fijar_velocidad(self, ux: float, uy: float, uz: float, uyaw: float = 0.0,
                        *, velocidad_mps: float | None = None) -> None:
        """Velocidad deseada: dirección (ux, uy, uz) a `velocidad_mps` (por
        defecto la de las opciones, que además es el tope). (0, 0, 0, 0) frena
        y devuelve el mando al high-level cuando la rampa llega a cero."""
        self._require_ready()
        e = self.estado()
        if not e.en_vuelo or e.origen is None:
            raise DronError("despega antes de mover")
        if e.maniobra_hasta_s > ahora():
            raise DronError("despegue o aterrizaje en curso")
        norm = math.sqrt(ux * ux + uy * uy + uz * uz)
        tope = self.opciones.velocidad_mps
        v = tope if velocidad_mps is None else max(0.0, min(float(velocidad_mps), tope))
        cmd = (
            (ux / norm * v, uy / norm * v, uz / norm * v) if norm > 1e-9 else (0.0, 0.0, 0.0)
        ) + (max(-1.0, min(1.0, uyaw)) * FLUID_YAW_RATE_DPS,)
        with self._lock:
            cambio = cmd != self._fluido_cmd
            self._fluido_cmd = cmd
            activo = self._fluido_activo
        parada = all(abs(c) <= 1e-9 for c in cmd)
        if cambio and (activo or not parada):
            # Direccion pedida, para la linea de tiempo de comandos. El
            # seguimiento cambia la orden a 30 Hz: como mucho dos por segundo,
            # salvo arranques y paradas, que se registran siempre.
            t = ahora()
            if parada or not activo or t - self._ultimo_vel_evento_s >= 0.5:
                self._ultimo_vel_evento_s = t
                self._evento("VEL", f"ux={ux:+.2f} uy={uy:+.2f} uz={uz:+.2f} uyaw={uyaw:+.1f} v={v:.2f}")
        with self._lock:
            if self._fluido_activo:
                return
            if all(abs(c) <= 1e-9 for c in cmd):
                return
            # La altura de partida es la estimada: el firmware la mantiene en
            # lazo de posición mientras Python la desplaza con vz.
            z0 = self._ekf.z if self._ekf is not None else e.objetivo[2]
            self._fluido_z = min(max(z0, MIN_TARGET_Z_M), MAX_TARGET_Z_M)
            self._fluido_activo = True
            self._estado.modo = "FLUIDO"
            self._estado.detalle = "Movimiento fluido (velocidad)"
        self._evento("FLUIDO_INICIO", f"v={self.opciones.velocidad_mps:.2f} m/s")
        self._fluido_thread = threading.Thread(target=self._fluido_loop, name="FluidoRobotat", daemon=True)
        self._fluido_thread.start()

    def _fluido_loop(self) -> None:
        periodo = 1.0 / FLUID_RATE_HZ
        try:
            while not self._stop.is_set():
                if not self._fluido_tick(periodo):
                    return
                time.sleep(periodo)
        except Exception as exc:
            self.emergency(f"fallo en el modo fluido: {exc}")
        finally:
            with self._lock:
                self._fluido_activo = False

    def _fluido_tick(self, dt: float) -> bool:
        """Un envío de velocidad. Devuelve False cuando ya devolvió el mando."""
        with self._lock:
            cf = self._cf
            cmd = self._fluido_cmd
            vel = self._fluido_vel
            e = self._estado
            activo = self._fluido_activo and e.en_vuelo and not e.emergencia
            ekf = self._ekf
            yaw_deg = self._ekf_yaw_deg
            origen = e.origen
            z_obj = self._fluido_z
        if cf is None or not activo or z_obj is None:
            return False
        for i in range(3):
            vel[i] = ramp_velocity(vel[i], cmd[i], dt)
        vel[3] = cmd[3]
        frame = self.feed.fresh()
        pose = ekf.xyz() if ekf is not None else (frame.xyz() if frame is not None else None)
        if pose is not None and origen is not None:
            vx, vy, _ = fence_velocity(pose, tuple(vel[:3]), centro_geocerca(self.opciones, origen),
                                       max_radius_m=self.opciones.radio_max_m)
            vel[0], vel[1] = vx, vy
        z_obj = min(max(z_obj + vel[2] * dt, MIN_TARGET_Z_M + FLUID_Z_FLOOR_MARGIN_M),
                    MAX_TARGET_Z_M - FLUID_Z_CEILING_MARGIN_M)
        if ekf is not None:
            if vel[2] > 1e-6:
                z_obj = min(z_obj, ekf.z + FLUID_Z_LEASH_M)
            elif vel[2] < -1e-6:
                z_obj = max(z_obj, ekf.z - FLUID_Z_LEASH_M)
        if all(abs(v) <= 1e-6 for v in vel) and all(abs(c) <= 1e-9 for c in cmd):
            with self._lock:
                self._fluido_z = z_obj
            self._fluido_entregar(pose)
            return False
        vbx, vby = world_to_body(vel[0], vel[1], 0.0 if yaw_deg is None else yaw_deg)
        # Signo del giro como `MotionCommander.start_turn_left(rate)`: positivo
        # es antihorario, igual que nuestro +1.
        cf.commander.send_hover_setpoint(vbx, vby, vel[3], z_obj)
        with self._lock:
            self._fluido_z = z_obj
            if pose is not None:
                self._estado.objetivo = (pose[0], pose[1], z_obj)
            if yaw_deg is not None:
                self._estado.objetivo_yaw_deg = wrap_deg(yaw_deg)
        return True

    def _fluido_entregar(self, pose: tuple[float, float, float] | None) -> None:
        """Rampa en cero: el high-level recupera el mando con un `go_to` corto
        a la posición estimada. Sin él el firmware cortaría motores a los 2 s
        sin setpoints."""
        with self._lock:
            cf = self._cf
            ekf = self._ekf
            yaw = 0.0 if self._ekf_yaw_deg is None else wrap_deg(self._ekf_yaw_deg)
            z_obj = self._fluido_z
            self._fluido_activo = False
            self._fluido_vel = [0.0, 0.0, 0.0, 0.0]
        hold = ekf.xyz() if ekf is not None else pose
        if hold is None:
            self.emergency("modo fluido sin posicion para entregar el mando")
            return
        # XY donde se detuvo; Z la altura mandada, no la estimada, para no
        # heredar el error que el lazo aún estaba corrigiendo.
        z_hold = hold[2] if z_obj is None else z_obj
        hold = (hold[0], hold[1], min(max(z_hold, MIN_TARGET_Z_M), MAX_TARGET_Z_M))
        try:
            cf.commander.send_notify_setpoint_stop()
            cf.high_level_commander.go_to(*hold, math.radians(yaw), FLUID_HOLD_DURATION_S, relative=False)
        except Exception as exc:
            self.emergency(f"fallo devolviendo el mando al high-level: {exc}")
            return
        with self._lock:
            self._estado.objetivo = hold
            self._estado.objetivo_yaw_deg = yaw
            self._estado.ocupado_hasta_s = ahora() + FLUID_HOLD_DURATION_S
            self._estado.modo = "VUELO"
            self._estado.detalle = f"Hover high-level en ({hold[0]:+.2f}, {hold[1]:+.2f}, {hold[2]:+.2f}) m"
        self._evento("FLUIDO_FIN", f"hold=({hold[0]:.3f},{hold[1]:.3f},{hold[2]:.3f})")

    def _detener_fluido(self) -> None:
        """Corta el hilo de velocidad y devuelve el mando antes de otra orden."""
        with self._lock:
            activo = self._fluido_activo
            self._fluido_cmd = (0.0, 0.0, 0.0, 0.0)
            self._fluido_activo = False
        thread = self._fluido_thread
        if activo and thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        if activo:
            try:
                self._cf.commander.send_notify_setpoint_stop()
            except Exception:
                pass

    def land(self) -> None:
        self._detener_fluido()
        with self._lock:
            cf = self._cf
            if cf is None or not self._estado.en_vuelo:
                return
            objetivo = self._estado.objetivo or (0.0, 0.0, LAND_HEIGHT_M)
            self._estado.objetivo = (objetivo[0], objetivo[1], LAND_HEIGHT_M)
            self._estado.ocupado_hasta_s = ahora() + LAND_DURATION_S + 0.5
            self._estado.maniobra_hasta_s = ahora() + LAND_DURATION_S + 0.5
        self._set("ATERRIZAJE", "Aterrizando")
        try:
            cf.high_level_commander.land(LAND_HEIGHT_M, LAND_DURATION_S)
        except Exception as exc:
            self.emergency(f"fallo enviando land: {exc}")
            raise DronError(f"fallo enviando land: {exc}") from exc
        self._evento("LAND", "")
        threading.Timer(LAND_DURATION_S + 0.5, self._landed).start()

    def _landed(self) -> None:
        with self._lock:
            cf = self._cf
            if self._estado.emergencia or not self._estado.en_vuelo:
                return
            self._estado.en_vuelo = False
        # Sin `stop()` el commander high-level deja los motores girando al
        # ralentí sobre el suelo. Apagarlos deja el dron listo para otro vuelo.
        if cf is not None:
            try:
                cf.high_level_commander.stop()
            except Exception:
                pass
        self._set("EN_TIERRA", "Aterrizado; motores apagados")
        self._evento("LANDED", self.resumen_empuje())

    def resumen_empuje(self) -> str:
        """Empuje medio del hover y el `thrustBase` que conviene la próxima vez."""
        muestras = self._empuje_hover
        if len(muestras) < 20:
            return ""
        media = sum(muestras) / len(muestras)
        guardar_empuje_memoria(self.opciones.nombre, round(media, -2))
        texto = (f"empuje medio en hover {media:.0f} (n={len(muestras)}); guardado: el proximo vuelo "
                 f"con --ganancias robotat usara thrustBase={round(media, -2):.0f}")
        self.log(texto)
        return texto

    def emergency(self, reason: str = "orden manual") -> None:
        """Corta motores. Enclava: después sólo queda cerrar el programa."""
        with self._lock:
            if self._estado.emergencia:
                return
            self._estado.emergencia = True
            self._estado.razon_emergencia = reason
            self._estado.listo = False
            self._estado.en_vuelo = False
            self._fluido_activo = False
            cf = self._cf
        self._set("EMERGENCIA", f"EMERGENCIA: {reason}")
        self._evento("EMERGENCIA", reason)
        self.resumen_empuje()
        if cf is None:
            return
        try:
            cf.high_level_commander.stop()
        except Exception:
            pass
        stop_motors(cf, repeats=10, interval_s=0.02)

    # -- Vigilancia y cierre ---------------------------------------------------

    def _start_monitor(self) -> None:
        self._stop.clear()
        self._monitor = threading.Thread(target=self._monitor_loop, name="MonitorRobotat", daemon=True)
        self._monitor.start()

    def _monitor_loop(self) -> None:
        while not self._stop.wait(MONITOR_PERIOD_S):
            self.csv.write(self._fila())
            e = self.estado()
            if not e.en_vuelo or e.emergencia:
                continue
            if e.modo == "DESPEGUE" and e.maniobra_hasta_s <= ahora():
                # El despegue terminó: hover high-level normal.
                self._set("VUELO", "Hover high-level")
                continue
            if e.modo == "VUELO" and e.maniobra_hasta_s <= ahora() and e.empuje_cmd:
                self._empuje_hover.append(e.empuje_cmd)
            decision = watchdog_reason(e)
            if decision is not None and decision[0] == "aterrizar" and "bateria" in decision[1]:
                # Un pico de corriente hunde la tension una decima de segundo;
                # solo cuenta si se mantiene.
                self._bateria_baja_desde_s = self._bateria_baja_desde_s or ahora()
                if ahora() - self._bateria_baja_desde_s < LOW_BATTERY_HOLD_S:
                    continue
            elif decision is None or "bateria" not in decision[1]:
                self._bateria_baja_desde_s = None
            if decision is None:
                continue
            accion, razon = decision
            self.log(f"WATCHDOG: {razon}")
            if accion == "aterrizar" and e.modo != "ATERRIZAJE_SIN_MOCAP":
                self._aterrizar_sin_mocap(razon)
                continue
            if accion == "cortar":
                # Aterrizando a ras de suelo el EKF puede separarse del mocap
                # al tocar; cortar ahi no protege nada y deja la sesion
                # enclavada. El aterrizaje termina y apaga motores solo.
                if (e.modo in ("ATERRIZAJE", "ATERRIZAJE_SIN_MOCAP") and "EKF" in razon
                        and e.mocap is not None and e.origen is not None
                        and e.mocap[2] - e.origen[2] < 0.10):
                    continue
                self.emergency(razon)
                return

    def _aterrizar_sin_mocap(self, razon: str) -> None:
        """Aterrizaje de seguridad: sin mocap o con batería baja.

        Sin posición externa el EKF sigue integrando unos segundos, y con la
        batería en 3 V el dron aún vuela: pedir `land` al firmware es más
        seguro que dejar caer el dron. Los motores se apagan al terminar."""
        self._detener_fluido()
        with self._lock:
            cf = self._cf
            self._estado.ocupado_hasta_s = ahora() + LAND_DURATION_S + 0.5
            self._estado.maniobra_hasta_s = ahora() + LAND_DURATION_S + 0.5
        self._set("ATERRIZAJE_SIN_MOCAP", f"Aterrizaje de seguridad: {razon}")
        self._evento("LAND_SEGURIDAD", razon)
        try:
            cf.high_level_commander.land(LAND_HEIGHT_M, LAND_DURATION_S)
        except Exception as exc:
            self.emergency(f"fallo enviando land de seguridad: {exc}")
            return
        threading.Timer(LAND_DURATION_S + 0.5, self._landed).start()

    def close(self) -> None:
        if self._cerrando:
            return
        self._cerrando = True
        try:
            e = self.estado()
            if e.en_vuelo and not e.emergencia:
                self.land()
                time.sleep(LAND_DURATION_S + 0.7)
        finally:
            self._stop.set()
            self._close_link()

    def _close_link(self) -> None:
        self.feed.stop()
        with self._lock:
            self._cf = None
            stack, self._stack = self._stack, None
            log_configs, self._log_configs = self._log_configs, []
            self._estado.listo = False
        for log_config in log_configs:
            try:
                log_config.stop()
            except Exception:
                pass
        if stack is not None:
            try:
                stack.close()
            except Exception:
                pass
        # Gráficas PDF y resumen de la sesión, siempre que hubo muestras.
        self.csv.stop(generate_graphs=True)


def plan_hold_segment(
    objetivo: tuple[float, float, float],
    yaw_deg: float,
    direccion: tuple[float, float, float],
    uyaw: float,
    velocidad_mps: float,
) -> tuple[tuple[float, float, float], float, float]:
    """Objetivo, yaw y duración del siguiente tramo continuo.

    La dirección se normaliza (dos teclas a la vez no van más rápido) y el
    objetivo avanza `velocidad · HOLD_PERIOD_S`; el yaw, `HOLD_YAW_SPEED_DPS ·
    HOLD_PERIOD_S` por unidad de `uyaw`.
    """
    norm = math.sqrt(sum(c * c for c in direccion))
    if norm > 1e-9:
        paso = velocidad_mps * HOLD_PERIOD_S
        target = tuple(o + c / norm * paso for o, c in zip(objetivo, direccion))
    else:
        target = tuple(objetivo)
    yaw = wrap_deg(yaw_deg + max(-1.0, min(1.0, uyaw)) * HOLD_YAW_SPEED_DPS * HOLD_PERIOD_S)
    if norm <= 1e-9 and abs(uyaw) <= 1e-9:
        raise DronError("el tramo no mueve ni gira")
    return target, yaw, HOLD_LOOKAHEAD_S


def watchdog_reason(e: Estado) -> tuple[str, str] | None:
    """Qué hacer en vuelo: ("aterrizar" | "cortar", motivo), o None si todo va bien.

    Sin mocap el EKF aguanta unos segundos: se pide aterrizar. Con el EKF
    lejos del mocap o la batería agotada no hay dónde aterrizar: se corta.
    """
    if e.mocap_edad_s is None or e.mocap_edad_s > MOCAP_TIMEOUT_S:
        return "aterrizar", "el Robotat dejo de actualizar"
    if e.mocap_congelado:
        return "aterrizar", "pose del Robotat congelada (rastreo perdido)"
    if e.error_ekf_mocap_m is not None and e.error_ekf_mocap_m > MAX_EKF_MOCAP_ERROR_M:
        return "cortar", f"EKF a {e.error_ekf_mocap_m:.3f} m del mocap (max {MAX_EKF_MOCAP_ERROR_M:.2f})"
    if e.bateria_v is not None and 0.0 < e.bateria_v < CRITICAL_BATTERY_V:
        return "cortar", f"bateria {e.bateria_v:.2f} V en vuelo"
    if e.bateria_v is not None and 0.0 < e.bateria_v < MIN_BATTERY_V_FLIGHT:
        return "aterrizar", f"bateria {e.bateria_v:.2f} V en vuelo"
    return None


class DronSimulado:
    """Misma interfaz que `DronRobotat`, sin radio ni broker. Para `--dry-run`."""

    def __init__(self, opciones: Opciones, *, log: Callable[[str], None] = print) -> None:
        self.opciones = opciones
        self.log = log
        self._lock = threading.RLock()
        self._estado = Estado(detalle="Simulacion. Ejecuta PREFLIGHT.")
        # Dos simulados no arrancan en el mismo punto: el Dron 2 a 0.9 m en Y,
        # como en el backend simulado de la cruz, para que pase la separacion.
        self._pose = (0.0, 0.9 if opciones.nombre.strip().endswith("2") else 0.0, 0.05)
        self._yaw = 0.0
        self._estado.bateria_v = 4.05
        self.ordenes: list[tuple] = []

    def estado(self) -> Estado:
        with self._lock:
            e = self._estado
            e.mocap = self._pose
            e.mocap_yaw_deg = self._yaw
            e.mocap_edad_s = 0.0 if e.listo or e.en_vuelo else None
            e.ekf = self._pose
            e.ekf_yaw_deg = self._yaw
            e.error_ekf_mocap_m = 0.0
            e.mocap_frames_hz = 20.0
            e.mocap_hueco_max_s = 0.05
            e.parametros = {"locSrv.extPosStdDev": f"{self.opciones.ext_pos_std_m:.4f}"} | dict(self.opciones.parametros)
            return Estado(**vars(e))

    def _set(self, modo: str, detalle: str) -> None:
        with self._lock:
            self._estado.modo, self._estado.detalle = modo, detalle
        self.log(f"[{self.opciones.nombre}] {detalle}")

    def preflight(self, progreso: Callable[[str], None] | None = None) -> None:
        with self._lock:
            if self._estado.emergencia:
                raise DronError("emergencia enclavada; reinicia el programa")
        if progreso:
            progreso("Simulando Robotat, radio y EKF...")
        time.sleep(0.1)
        with self._lock:
            self._estado.origen = self._pose
            self._estado.objetivo = self._pose
            self._estado.listo = True
        self._set("LISTO", "Preflight simulado correcto")

    def _require(self) -> None:
        with self._lock:
            if self._estado.emergencia:
                raise DronError("emergencia enclavada; reinicia el programa")
            if not self._estado.listo:
                raise DronError("ejecuta PREFLIGHT antes")
            remaining = self._estado.ocupado_hasta_s - ahora()
        if remaining > 0:
            raise DronError(f"orden anterior en curso; faltan {remaining:.1f} s")

    def esperar_libre(self, timeout_s: float = 6.0) -> bool:
        """Espera a que termine la orden en curso. False si no terminó a tiempo."""
        deadline = ahora() + timeout_s
        while ahora() < deadline:
            with self._lock:
                remaining = self._estado.ocupado_hasta_s - ahora()
            if remaining <= 0:
                return True
            time.sleep(min(remaining, 0.05))
        return False

    def takeoff(self) -> None:
        self._require()
        with self._lock:
            if self._estado.en_vuelo:
                raise DronError("ya esta en vuelo")
            z = min(self._pose[2] + self.opciones.altura_m, MAX_TARGET_Z_M)
            self._pose = (self._pose[0], self._pose[1], z)
            self._estado.objetivo = self._pose
            self._estado.objetivo_yaw_deg = self._yaw
            self._estado.en_vuelo = True
            self._estado.ocupado_hasta_s = ahora() + TAKEOFF_DURATION_S
            self._estado.maniobra_hasta_s = ahora() + TAKEOFF_DURATION_S
        self.ordenes.append(("takeoff", z))
        self._set("DESPEGUE", f"Despegue simulado a {z:.2f} m")

    def move(self, dx: float, dy: float, dz: float, dyaw: float = 0.0) -> None:
        step = validate_step(dx, dy, dz, dyaw)
        self._require()
        with self._lock:
            if not self._estado.en_vuelo:
                raise DronError("despega antes de mover")
            objetivo = self._estado.objetivo
            target = (objetivo[0] + step.dx, objetivo[1] + step.dy, objetivo[2] + step.dz)
            validate_target(target, centro_geocerca(self.opciones, self._estado.origen), max_radius_m=self.opciones.radio_max_m)
            duration = goto_duration_s(math.dist(target, objetivo), step.dyaw, self.opciones.velocidad_mps)
            self._yaw = wrap_deg(self._yaw + step.dyaw)
            self._pose = target
            self._estado.objetivo = target
            self._estado.objetivo_yaw_deg = self._yaw
            self._estado.ocupado_hasta_s = ahora() + duration
        self.ordenes.append(("go_to", target, self._yaw, duration))
        self._set("GO_TO", f"Objetivo simulado ({target[0]:+.2f}, {target[1]:+.2f}, {target[2]:+.2f}) m, "
                           f"yaw {self._yaw:+.0f} deg, {duration:.1f} s")

    def avanzar(self, ux: float, uy: float, uz: float, uyaw: float = 0.0) -> None:
        with self._lock:
            if self._estado.emergencia:
                raise DronError("emergencia enclavada; reinicia el programa")
            if not self._estado.listo:
                raise DronError("ejecuta PREFLIGHT antes")
            if not self._estado.en_vuelo:
                raise DronError("despega antes de mover")
            if self._estado.maniobra_hasta_s > ahora():
                raise DronError("despegue o aterrizaje en curso")
            target, yaw, duration = plan_hold_segment(
                self._estado.objetivo, self._yaw, (ux, uy, uz), uyaw, self.opciones.velocidad_mps
            )
            validate_target(target, self._estado.origen, max_radius_m=self.opciones.radio_max_m)
            self._yaw = yaw
            self._pose = target
            self._estado.objetivo = target
            self._estado.objetivo_yaw_deg = yaw
            self._estado.ocupado_hasta_s = ahora() + duration
            self._estado.modo = "CONTINUO"
        self.ordenes.append(("tramo", target, yaw, duration))

    def fijar_velocidad(self, ux: float, uy: float, uz: float, uyaw: float = 0.0,
                        *, velocidad_mps: float | None = None) -> None:
        """Simulación: la pose avanza un paso de `FLUID_LOOKAHEAD_S` por llamada."""
        with self._lock:
            if self._estado.emergencia:
                raise DronError("emergencia enclavada; reinicia el programa")
            if not self._estado.listo:
                raise DronError("ejecuta PREFLIGHT antes")
            if not self._estado.en_vuelo:
                raise DronError("despega antes de mover")
            if self._estado.maniobra_hasta_s > ahora():
                raise DronError("despegue o aterrizaje en curso")
            norm = math.sqrt(ux * ux + uy * uy + uz * uz)
            tope = self.opciones.velocidad_mps
            v = tope if velocidad_mps is None else max(0.0, min(float(velocidad_mps), tope))
            vel = (ux / norm * v, uy / norm * v, uz / norm * v) if norm > 1e-9 else (0.0, 0.0, 0.0)
            vel = fence_velocity(self._pose, vel, centro_geocerca(self.opciones, self._estado.origen),
                                 max_radius_m=self.opciones.radio_max_m)
            dt = FLUID_LOOKAHEAD_S
            self._pose = tuple(p + c * dt for p, c in zip(self._pose, vel))
            self._yaw = wrap_deg(self._yaw + max(-1.0, min(1.0, uyaw)) * FLUID_YAW_RATE_DPS * dt)
            self._estado.objetivo = self._pose
            self._estado.objetivo_yaw_deg = self._yaw
            self._estado.modo = "FLUIDO" if any(abs(c) > 1e-9 for c in vel) or abs(uyaw) > 1e-9 else "VUELO"
        self.ordenes.append(("velocidad", vel, uyaw))

    def land(self) -> None:
        with self._lock:
            if not self._estado.en_vuelo:
                return
            origen = self._estado.origen
            self._pose = (self._pose[0], self._pose[1], origen[2])
            self._estado.objetivo = self._pose
            self._estado.en_vuelo = False
        self.ordenes.append(("land",))
        self._set("EN_TIERRA", "Aterrizado (simulado)")

    def emergency(self, reason: str = "orden manual") -> None:
        with self._lock:
            self._estado.emergencia = True
            self._estado.razon_emergencia = reason
            self._estado.listo = False
            self._estado.en_vuelo = False
        self.ordenes.append(("emergency", reason))
        self._set("EMERGENCIA", f"EMERGENCIA (simulada): {reason}")

    def close(self) -> None:
        with self._lock:
            self._estado.listo = False


__all__ = [
    "DronError", "DronRobotat", "DronSimulado", "Estado", "GANANCIAS", "Move", "Opciones",
    "RegistroRobotat", "parametros_firmware",
    "anticipate", "centro_geocerca", "fence_velocity", "goto_duration_s", "guardar_empuje_memoria", "leer_empuje_memoria",
    "plan_hold_segment", "ramp_velocity", "stable_origin", "validate_step", "world_to_body",
    "CRITICAL_BATTERY_V", "LOW_BATTERY_HOLD_S", "MIN_BATTERY_V_FLIGHT",
    "validate_target", "watchdog_reason", "wrap_deg",
]
