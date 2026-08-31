r"""Diagnóstico sin motores del Flow deck v2 en los dos Crazyflies.

Durante cada prueba, levanta y mueve suavemente el dron con la mano sobre una
superficie con textura. El programa verifica detección, distancia al suelo y
actividad del sensor de flujo óptico. Nunca arma ni enciende motores.

Uso:
    .\.venv\Scripts\python.exe .\controllers\two_drones\diagnostico_flowdeck_dos_drones.py
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from dataclasses import dataclass

import cflib.crtp
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.log import LogConfig
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie
from cflib.crazyflie.syncLogger import SyncLogger
from cflib.drivers.crazyradio import get_serials


KNOWN_RADIOS = ("2B1D933FCC", "9DD2507072")
DRONE_1_LINK = (84, "2M", "E7E7E7E7E4")
DRONE_2_LINK = (90, "2M", "E7E7E7E7E5")
DEFAULT_SAMPLE_S = 6.0


@dataclass(frozen=True)
class DroneTest:
    name: str
    uri: str


@dataclass
class TestResult:
    name: str
    connected: bool = False
    deck_detected: bool = False
    range_samples: int = 0
    range_min_mm: float | None = None
    range_max_mm: float | None = None
    flow_samples: int = 0
    flow_nonzero: int = 0
    error: str | None = None

    @property
    def range_change_mm(self) -> float | None:
        if self.range_min_mm is None or self.range_max_mm is None:
            return None
        return self.range_max_mm - self.range_min_mm


def detected_radios() -> list[str]:
    return [str(serial).upper() for serial in get_serials()]


def choose_radios(requested_1: str | None, requested_2: str | None) -> tuple[str, str]:
    radios = detected_radios()
    if not radios:
        raise RuntimeError("No se detectó ninguna Crazyradio conectada por USB.")

    def validate(requested: str | None, fallback_index: int) -> str:
        if requested:
            serial = requested.upper()
            if serial not in radios:
                raise RuntimeError(
                    f"La antena {serial} no está conectada. Detectadas: {', '.join(radios)}"
                )
            return serial
        preferred = [serial for serial in KNOWN_RADIOS if serial in radios]
        if fallback_index < len(preferred):
            return preferred[fallback_index]
        # Como las pruebas son secuenciales, una misma antena sirve para ambos.
        return radios[0]

    selected = validate(requested_1, 0), validate(requested_2, 1)
    return selected


def make_uri(serial: str, link: tuple[int, str, str]) -> str:
    channel, rate, address = link
    return f"radio://{serial}/{channel}/{rate}/{address}"


def read_deck_parameter(cf: Crazyflie) -> bool:
    try:
        value = cf.param.get_value("deck.bcFlow2")
    except Exception as error:
        raise RuntimeError(f"no se pudo leer deck.bcFlow2: {error}") from error
    if value is None:
        raise RuntimeError("el firmware no contiene el parámetro deck.bcFlow2")
    return int(value) == 1


def collect_sensor_data(
    scf: SyncCrazyflie, duration_s: float
) -> tuple[list[float], list[tuple[float, float]]]:
    """Lee ToF y flujo óptico desde la tabla de logs del firmware."""
    config = LogConfig(name="FlowDeckDiagnostic", period_in_ms=100)
    config.add_variable("range.zrange")
    config.add_variable("motion.deltaX")
    config.add_variable("motion.deltaY")

    ranges: list[float] = []
    flow: list[tuple[float, float]] = []
    deadline = time.monotonic() + duration_s
    with SyncLogger(scf, config) as logger:
        for _, data, _ in logger:
            ranges.append(float(data["range.zrange"]))
            flow.append(
                (float(data["motion.deltaX"]), float(data["motion.deltaY"]))
            )
            if time.monotonic() >= deadline:
                break
    return ranges, flow


def test_drone(drone: DroneTest, duration_s: float) -> TestResult:
    result = TestResult(name=drone.name)
    print(f"\n{'=' * 62}")
    print(f"{drone.name}: {drone.uri}")
    print("Conectando únicamente para diagnóstico; los motores no se arman.")
    try:
        with SyncCrazyflie(
            drone.uri,
            cf=Crazyflie(rw_cache=f"./cache_diagnostico_{drone.name.lower().replace(' ', '_')}"),
        ) as scf:
            result.connected = True
            result.deck_detected = read_deck_parameter(scf.cf)
            print(f"deck.bcFlow2 = {1 if result.deck_detected else 0}")
            if not result.deck_detected:
                result.error = "Flow deck no detectado por el firmware"
                return result

            print("Flow deck reconocido.")
            print(
                f"Durante {duration_s:.1f} s, levanta el dron y muévelo suavemente "
                "hacia los lados sobre un suelo con textura."
            )
            answer = input("Presiona ENTER para comenzar o escribe Q para omitir: ").strip()
            if answer.lower() == "q":
                return result

            ranges, flow = collect_sensor_data(scf, duration_s)
            result.range_samples = len(ranges)
            result.flow_samples = len(flow)
            if ranges:
                result.range_min_mm = min(ranges)
                result.range_max_mm = max(ranges)
            result.flow_nonzero = sum(
                1 for dx, dy in flow if abs(dx) > 0.0 or abs(dy) > 0.0
            )

            if ranges:
                print(
                    f"ToF: {len(ranges)} muestras | mínimo={min(ranges):.0f} mm | "
                    f"máximo={max(ranges):.0f} mm | promedio={statistics.mean(ranges):.0f} mm"
                )
            print(
                f"Flujo óptico: {result.flow_nonzero}/{result.flow_samples} "
                "muestras detectaron movimiento."
            )
    except Exception as error:
        result.error = str(error)
    return result


def status_text(result: TestResult) -> str:
    if result.error:
        return f"FALLÓ — {result.error}"
    if not result.connected:
        return "FALLÓ — sin conexión"
    if not result.deck_detected:
        return "FALLÓ — deck.bcFlow2=0"
    if result.range_samples == 0 and result.flow_samples == 0:
        return "RECONOCIDO — prueba de sensores omitida"

    range_ok = result.range_change_mm is not None and result.range_change_mm >= 20.0
    flow_ok = result.flow_nonzero > 0
    if range_ok and flow_ok:
        return "CORRECTO — identificación, altura y flujo respondieron"
    if not range_ok and not flow_ok:
        return "INCONCLUSO — no se observó cambio de altura ni movimiento"
    if not range_ok:
        return "REVISAR — el ToF no mostró un cambio de altura suficiente"
    return "REVISAR — el sensor óptico no reportó movimiento"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verifica sin motores el Flow deck en los dos drones"
    )
    parser.add_argument("--radio1", help="serial de antena para el Dron 1")
    parser.add_argument("--radio2", help="serial de antena para el Dron 2")
    parser.add_argument(
        "--tiempo", type=float, default=DEFAULT_SAMPLE_S, help="segundos de muestreo por dron"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.tiempo <= 0:
        print("ERROR: --tiempo debe ser mayor que cero.", file=sys.stderr)
        return 2

    try:
        cflib.crtp.init_drivers(enable_debug_driver=False)
        radio_1, radio_2 = choose_radios(args.radio1, args.radio2)
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print("DIAGNÓSTICO DE FLOW DECK — MOTORES DESACTIVADOS")
    print(f"Crazyradio detectadas: {', '.join(detected_radios())}")
    tests = (
        DroneTest("Dron 1", make_uri(radio_1, DRONE_1_LINK)),
        DroneTest("Dron 2", make_uri(radio_2, DRONE_2_LINK)),
    )
    final_results = [test_drone(drone, args.tiempo) for drone in tests]

    print(f"\n{'=' * 62}")
    print("RESUMEN")
    for result in final_results:
        print(f"{result.name}: {status_text(result)}")
    return 0 if all(result.deck_detected and not result.error for result in final_results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
