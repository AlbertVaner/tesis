"""Compara, con motores apagados, los parametros de control de dos Crazyflies.

Uso:
    .\.venv\Scripts\python.exe .\drone_control\comparar_parametros_drones.py

El programa solo lee parametros: no inicia MoCap, no arma motores ni envia
setpoints. Guarda un JSON dentro de datos_dos_drones/, carpeta que Git ignora.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import cflib.crtp
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie

from prueba_estabilidad_dos_drones_lowlevel import DEFAULT_URI_1, DEFAULT_URI_2


# Los grupos que afectan directamente los lazos de posicion, actitud y tasa.
CONTROL_GROUPS = {
    "stabilizer",
    "posCtlPid",
    "pid_attitude",
    "pid_rate",
    "ctrlAtt",
    "ctrlINDI",
    "ctrlLee",
    "ctrlMel",
    "flightmode",
}


def wait_for_parameters(cf: Crazyflie, timeout_s: float = 12.0) -> None:
    deadline = time.monotonic() + timeout_s
    while not cf.param.is_updated:
        if time.monotonic() >= deadline:
            raise TimeoutError("La tabla de parametros no termino de descargarse")
        time.sleep(0.1)


def read_control_parameters(uri: str, label: str) -> dict[str, object]:
    print(f"Conectando {label}: {uri}")
    cf = Crazyflie(rw_cache=f"./cache_{label.replace(' ', '_')}")
    with SyncCrazyflie(uri, cf=cf):
        wait_for_parameters(cf)
        names = sorted(
            f"{group}.{name}"
            for group, entries in cf.param.toc.toc.items()
            if group in CONTROL_GROUPS
            for name in entries
        )
        values: dict[str, object] = {}
        for name in names:
            try:
                value = cf.param.get_value(name)
                # cflib puede devolver los valores como texto aun cuando el
                # parametro sea float. Convertir primero a float evita que
                # valores como "0.5" se marquen falsamente como no leidos.
                if isinstance(value, str):
                    numeric = float(value)
                    values[name] = int(numeric) if numeric.is_integer() else numeric
                elif isinstance(value, float):
                    values[name] = value
                else:
                    values[name] = int(value)
            except (KeyError, TypeError, ValueError) as exc:
                values[name] = f"NO_LEIDO: {exc}"
        print(f"  {len(values)} parametros leidos.")
        return {"uri": uri, "parameters": values}


def print_differences(first: dict[str, object], second: dict[str, object]) -> list[dict[str, object]]:
    a = first["parameters"]
    b = second["parameters"]
    assert isinstance(a, dict) and isinstance(b, dict)
    differences: list[dict[str, object]] = []
    for name in sorted(set(a) | set(b)):
        left, right = a.get(name, "NO_EXISTE"), b.get(name, "NO_EXISTE")
        if left != right:
            differences.append({"parameter": name, "dron_1": left, "dron_2": right})
    print("\nDiferencias encontradas:")
    if not differences:
        print("  Ninguna. Los parametros de control leidos son identicos.")
    else:
        for item in differences:
            print(f"  {item['parameter']}: Dron 1={item['dron_1']} | Dron 2={item['dron_2']}")
    return differences


def main() -> None:
    parser = argparse.ArgumentParser(description="Comparacion segura de PID/configuracion Crazyflie")
    parser.add_argument("--uri1", default=DEFAULT_URI_1)
    parser.add_argument("--uri2", default=DEFAULT_URI_2)
    args = parser.parse_args()

    print("COMPARACION DE PARAMETROS — MOTORES DESACTIVADOS")
    print("Cierra CFclient y cualquier otro script que use la Crazyradio.\n")
    cflib.crtp.init_drivers(enable_debug_driver=False)
    first = read_control_parameters(args.uri1, "Dron 1")
    second = read_control_parameters(args.uri2, "Dron 2")
    differences = print_differences(first, second)

    output_dir = Path(__file__).with_name("datos_dos_drones")
    output_dir.mkdir(exist_ok=True)
    path = output_dir / f"comparacion_parametros_{datetime.now():%Y%m%d_%H%M%S}.json"
    path.write_text(
        json.dumps(
            {"dron_1": first, "dron_2": second, "differences": differences},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\nResultado guardado: {path}")


if __name__ == "__main__":
    main()
