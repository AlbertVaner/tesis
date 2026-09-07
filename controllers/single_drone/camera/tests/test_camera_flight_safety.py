"""Protecciones del backend Flow deck que usa el control por camara.

Sin radio, sin camara y sin motores: `MotionCommander` y el armado se
sustituyen por dobles y el hilo del controlador atiende un `cf` falso.

* S1 techo y piso de altura, aplicados de verdad en `set_velocity`;
* S3 el despegue no bloquea el bucle de la camara;
* S2 watchdog en dos etapas: silencio corto detiene, silencio largo aterriza.

Uso, desde la raiz del repositorio:

    .\\.venv\\Scripts\\python.exe .\\controllers\\single_drone\\camera\\tests\\test_camera_flight_safety.py
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

CAMERA_DIR = Path(__file__).resolve().parents[1]
TWO_DRONES_DIR = CAMERA_DIR.parents[1] / "two_drones"
for directory in (CAMERA_DIR, TWO_DRONES_DIR):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import flowdeck_dual_backend as backend  # noqa: E402
from control_camara_flowdeck_dron1 import (  # noqa: E402
    VISION_DEADMAN_S,
    VISION_LOST_LAND_S,
    flowdeck_controller,
)


TAKEOFF_SECONDS = 1.5


class FakeCommander:
    """Doble de MotionCommander: registra llamadas y simula bloqueo."""

    instances: list["FakeCommander"] = []

    def __init__(self, *_args, **_kwargs) -> None:
        self.calls: list[str] = []
        self.velocities: list[tuple[float, float, float]] = []
        FakeCommander.instances.append(self)

    def take_off(self, *_a, **_k) -> None:
        self.calls.append("take_off")
        time.sleep(TAKEOFF_SECONDS)

    def land(self, *_a, **_k) -> None:
        self.calls.append("land")
        time.sleep(0.2)

    def stop(self) -> None:
        self.calls.append("stop")

    def start_linear_motion(self, vx: float, vy: float, vz: float) -> None:
        self.velocities.append((vx, vy, vz))


class FakeCf:
    pass


results: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    results.append((name, bool(condition), detail))


def wait_until(predicate, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def build_served() -> tuple[backend.FlowDroneController, threading.Thread]:
    """Controlador listo, con su hilo atendiendo la cola sobre un cf falso."""
    controller = flowdeck_controller("radio://fake")
    controller.ready = True
    thread = threading.Thread(target=controller._serve, args=(FakeCf(),), daemon=True)
    thread.start()
    return controller, thread


def takeoff_and_wait(controller: backend.FlowDroneController) -> FakeCommander:
    controller.request_takeoff()
    wait_until(lambda: controller.flying, TAKEOFF_SECONDS + 2.0)
    return FakeCommander.instances[-1]


# ---------------------------------------------------------------- S1: altura
def test_limite_de_altura() -> None:
    flight = flowdeck_controller("radio://fake")
    techo, piso = flight.config.max_height_m, flight.config.min_height_m
    now = time.monotonic()

    # Sin lectura de altura: no se permite subir.
    flight.height_m = None
    check("S1 sin altura: ascenso bloqueado", flight._limit_vertical(+0.10) == 0.0)
    check("S1 sin altura: descenso permitido", flight._limit_vertical(-0.10) == -0.10)

    # Lectura fresca y dentro de rango: pasa sin tocar.
    flight.height_m, flight.height_time = 0.50, now
    check("S1 en rango: sube", flight._limit_vertical(+0.10) == +0.10)
    check("S1 en rango: baja", flight._limit_vertical(-0.10) == -0.10)

    # Por encima del techo: se corta el ascenso, se conserva el descenso.
    flight.height_m, flight.height_time = techo + 0.05, time.monotonic()
    check("S1 sobre el techo: ascenso bloqueado", flight._limit_vertical(+0.10) == 0.0)
    check("S1 sobre el techo: descenso permitido", flight._limit_vertical(-0.10) == -0.10)

    # Por debajo del piso: se corta el descenso.
    flight.height_m, flight.height_time = piso - 0.05, time.monotonic()
    check("S1 bajo el piso: descenso bloqueado", flight._limit_vertical(-0.10) == 0.0)
    check("S1 bajo el piso: ascenso permitido", flight._limit_vertical(+0.10) == +0.10)

    # Lectura vieja: se trata como desconocida.
    flight.height_m = 0.50
    flight.height_time = time.monotonic() - (backend.HEIGHT_STALE_S + 0.2)
    check("S1 altura vieja: ascenso bloqueado", flight._limit_vertical(+0.10) == 0.0)

    # Sin techo configurado (paneles de teclado) no se toca la orden.
    panel = backend.FlowDroneController(backend.FlowDroneConfig("Panel", "radio://fake"))
    check("S1 sin techo configurado: pasa tal cual", panel._limit_vertical(+0.10) == +0.10)

    # El limite se aplica de verdad en set_velocity, no solo en el helper.
    controller, thread = build_served()
    try:
        commander = takeoff_and_wait(controller)
        controller.height_m, controller.height_time = techo + 0.05, time.monotonic()
        controller.set_velocity(0.0, 0.0, +0.10)
        wait_until(lambda: bool(commander.velocities), 1.0)
        enviado = commander.velocities[-1] if commander.velocities else None
        check("S1 set_velocity aplica el techo", enviado == (0.0, 0.0, 0.0), f"envio {enviado}")
    finally:
        controller.close()
        thread.join(timeout=2.0)


# ------------------------------------------------------ S3: despegue sin bloqueo
def test_despegue_no_bloquea() -> None:
    controller, thread = build_served()
    try:
        inicio = time.monotonic()
        aceptado = controller.request_takeoff()
        retorno = time.monotonic() - inicio

        check("S3 request_takeoff aceptado", aceptado)
        check(
            "S3 request_takeoff no bloquea el bucle",
            retorno < 0.20,
            f"retorno en {retorno * 1000:.0f} ms (take_off tarda {TAKEOFF_SECONDS} s)",
        )
        check("S3 marca busy durante la maniobra", controller.busy)

        # Un segundo despegue no debe encolarse.
        check("S3 no acepta despegue duplicado", controller.request_takeoff() is False)

        # Y las interfaces no quedan bloqueadas esperando el lock.
        adquirido = controller.lock.acquire(timeout=0.5)
        if adquirido:
            controller.lock.release()
        check("S3 el lock queda libre durante take_off", adquirido)

        wait_until(lambda: controller.flying, TAKEOFF_SECONDS + 2.0)
        check("S3 termina volando", controller.flying and not controller.busy)
    finally:
        controller.close()
        thread.join(timeout=2.0)


# --------------------------------------------------- S2: watchdog en dos etapas
def test_watchdog_dos_etapas() -> None:
    controller, thread = build_served()
    try:
        commander = takeoff_and_wait(controller)
        controller.height_m, controller.height_time = 0.50, time.monotonic()

        # Etapa 1: silencio corto -> se detiene el movimiento.
        controller.set_velocity(0.10, 0.0, 0.0)
        wait_until(lambda: controller.motion_active, 1.0)
        check("S2 hay movimiento activo", controller.motion_active)
        with controller.lock:
            controller._last_command = time.monotonic() - (VISION_DEADMAN_S + 0.1)
        time.sleep(0.30)
        check("S2 etapa 1 detiene el movimiento", not controller.motion_active and "stop" in commander.calls)
        check("S2 etapa 1 no aterriza todavia", controller.flying)

        # El watchdog debe poder volver a disparar.
        controller.set_velocity(0.10, 0.0, 0.0)
        wait_until(lambda: controller.motion_active, 1.0)
        with controller.lock:
            controller._last_command = time.monotonic() - (VISION_DEADMAN_S + 0.1)
        time.sleep(0.30)
        check("S2 el watchdog vuelve a disparar", not controller.motion_active)

        # Etapa 2: silencio largo -> aterriza.
        with controller.lock:
            controller._last_command = time.monotonic() - (VISION_LOST_LAND_S + 0.1)
        aterrizo = wait_until(lambda: not controller.flying, 4.0)
        check("S2 etapa 2 aterriza", aterrizo and "land" in commander.calls)
    finally:
        controller.close()
        thread.join(timeout=2.0)


def main() -> int:
    print("Prueba de protecciones del control por camara con Flow deck")
    print("Sin radio, sin camara y sin motores.\n")
    print(f"  techo={backend.MAX_HEIGHT_M} m  piso={backend.MIN_HEIGHT_M} m")
    print(f"  deadman={VISION_DEADMAN_S} s  aterrizaje={VISION_LOST_LAND_S} s\n")

    backend.MotionCommander = FakeCommander
    backend.arm_if_supported = lambda _cf: None
    for prueba in (test_limite_de_altura, test_despegue_no_bloquea, test_watchdog_dos_etapas):
        prueba()

    ancho = max(len(nombre) for nombre, _, _ in results)
    fallos = 0
    for nombre, ok, detalle in results:
        marca = "OK  " if ok else "FALLA"
        extra = f"   {detalle}" if detalle else ""
        print(f"  [{marca}] {nombre.ljust(ancho)}{extra}")
        if not ok:
            fallos += 1

    total = len(results)
    print()
    if fallos:
        print(f"{fallos} de {total} comprobaciones fallaron. NO VOLAR.")
        return 1
    print(f"Las {total} comprobaciones pasaron.")
    print("Esto valida la logica, no el vuelo. Sigue haciendo la prueba sin helices.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
