"""Verifica las protecciones del control por camara sin radio ni motores.

No abre la camara, no conecta el Crazyflie y no enciende motores: sustituye
MotionCommander y el enlace por dobles de prueba, y comprueba unicamente la
logica de seguridad del controlador.

Uso, desde la raiz del repositorio:

    .\\.venv\\Scripts\\python.exe .\\controllers\\single_drone\\camera\\tests\\test_camera_flight_safety.py
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
CAMERA_DIR = TESTS_DIR.parent
if str(CAMERA_DIR) not in sys.path:
    sys.path.insert(0, str(CAMERA_DIR))

import control_camara_flowdeck_dron1 as ctrl  # noqa: E402


TAKEOFF_SECONDS = 1.5


class FakeCommander:
    """Doble de MotionCommander: registra llamadas y simula bloqueo."""

    def __init__(self, *_args, **_kwargs) -> None:
        self.calls: list[str] = []
        self.velocities: list[tuple[float, float, float]] = []

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


def build_flight(*, flying: bool = False) -> ctrl.CameraFlight:
    flight = ctrl.CameraFlight("radio://fake")
    flight.cf = FakeCf()
    if flying:
        flight.commander = FakeCommander()
        flight.flying = True
    return flight


# ---------------------------------------------------------------- S1: altura
def test_limite_de_altura() -> None:
    flight = build_flight(flying=True)
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
    flight.height_m, flight.height_time = ctrl.MAX_HEIGHT_M + 0.05, time.monotonic()
    check("S1 sobre el techo: ascenso bloqueado", flight._limit_vertical(+0.10) == 0.0)
    check("S1 sobre el techo: descenso permitido", flight._limit_vertical(-0.10) == -0.10)

    # Por debajo del piso: se corta el descenso.
    flight.height_m, flight.height_time = ctrl.MIN_HEIGHT_M - 0.05, time.monotonic()
    check("S1 bajo el piso: descenso bloqueado", flight._limit_vertical(-0.10) == 0.0)
    check("S1 bajo el piso: ascenso permitido", flight._limit_vertical(+0.10) == +0.10)

    # Lectura vieja: se trata como desconocida.
    flight.height_m = 0.50
    flight.height_time = time.monotonic() - (ctrl.HEIGHT_STALE_S + 0.2)
    check("S1 altura vieja: ascenso bloqueado", flight._limit_vertical(+0.10) == 0.0)

    # El limite se aplica de verdad en set_velocity, no solo en el helper.
    flight.height_m, flight.height_time = ctrl.MAX_HEIGHT_M + 0.05, time.monotonic()
    flight.set_velocity(0.0, 0.0, +0.10)
    enviado = flight.commander.velocities[-1]
    check("S1 set_velocity aplica el techo", enviado == (0.0, 0.0, 0.0), f"envio {enviado}")


# ------------------------------------------------------ S3: despegue sin bloqueo
def test_despegue_no_bloquea() -> None:
    original = ctrl.MotionCommander
    original_arm = ctrl.arm_if_supported
    ctrl.MotionCommander = FakeCommander
    ctrl.arm_if_supported = lambda _cf: None
    try:
        flight = build_flight()
        inicio = time.monotonic()
        aceptado = flight.request_takeoff()
        retorno = time.monotonic() - inicio

        check("S3 request_takeoff aceptado", aceptado)
        check(
            "S3 request_takeoff no bloquea el bucle",
            retorno < 0.20,
            f"retorno en {retorno * 1000:.0f} ms (take_off tarda {TAKEOFF_SECONDS} s)",
        )
        check("S3 marca busy durante la maniobra", flight.busy)

        # Un segundo despegue no debe encolarse.
        check("S3 no acepta despegue duplicado", flight.request_takeoff() is False)

        # Y el watchdog no queda bloqueado esperando el lock.
        adquirido = flight.lock.acquire(timeout=0.5)
        if adquirido:
            flight.lock.release()
        check("S3 el lock queda libre durante take_off", adquirido)

        flight.operation_thread.join(timeout=TAKEOFF_SECONDS + 2.0)
        check("S3 termina volando", flight.flying and not flight.busy)
    finally:
        ctrl.MotionCommander = original
        ctrl.arm_if_supported = original_arm


# --------------------------------------------------- S2: watchdog en dos etapas
def test_watchdog_dos_etapas() -> None:
    original_arm = ctrl.arm_if_supported
    ctrl.arm_if_supported = lambda _cf: None
    try:
        flight = build_flight(flying=True)
        flight.height_m, flight.height_time = 0.50, time.monotonic()
        flight.watchdog.start()
        try:
            # Etapa 1: silencio corto -> se detiene el movimiento.
            flight.set_velocity(0.10, 0.0, 0.0)
            check("S2 hay movimiento activo", flight.motion_active)
            with flight.lock:
                flight.last_vision_command = time.monotonic() - (ctrl.VISION_DEADMAN_S + 0.1)
            time.sleep(0.30)
            check("S2 etapa 1 detiene el movimiento", not flight.motion_active)
            check("S2 etapa 1 no aterriza todavia", flight.flying)

            # El watchdog debe poder volver a disparar: antes se desactivaba.
            flight.set_velocity(0.10, 0.0, 0.0)
            with flight.lock:
                flight.last_vision_command = time.monotonic() - (ctrl.VISION_DEADMAN_S + 0.1)
            time.sleep(0.30)
            check("S2 el watchdog vuelve a disparar", not flight.motion_active)

            # Etapa 2: silencio largo -> aterriza.
            with flight.lock:
                flight.last_vision_command = time.monotonic() - (ctrl.VISION_LOST_LAND_S + 0.1)
            plazo = time.monotonic() + 4.0
            while time.monotonic() < plazo and flight.flying:
                time.sleep(0.05)
            check("S2 etapa 2 aterriza", not flight.flying)
        finally:
            flight.watchdog_stop.set()
            flight.watchdog.join(timeout=1.0)
    finally:
        ctrl.arm_if_supported = original_arm


def main() -> int:
    print("Prueba de protecciones del control por camara")
    print("Sin radio, sin camara y sin motores.\n")
    print(f"  techo={ctrl.MAX_HEIGHT_M} m  piso={ctrl.MIN_HEIGHT_M} m")
    print(f"  deadman={ctrl.VISION_DEADMAN_S} s  aterrizaje={ctrl.VISION_LOST_LAND_S} s\n")

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
