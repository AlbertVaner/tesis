"""Verifica la traduccion de gesto a orden de vuelo. Sin radio ni motores.

Lo unico que se comprueba aqui es lo que puede mandar el dron en la direccion
equivocada:

* que un gesto **no confirmado** no mueva nada;
* que STOP y los gestos de estado dejen el dron en hover, no en movimiento;
* que la correccion de rumbo tenga el signo correcto.

Ese ultimo punto no es un detalle: el gesto esta en el marco del operador y
`MotionCommander` manda en el del dron. Un signo cambiado convierte ADELANTE en
un desplazamiento lateral, y con Flow deck no hay referencia externa que lo
corrija sola.

Uso, desde la raiz del repositorio:

    .\\.venv\\Scripts\\python.exe .\\controllers\\single_drone\\camera\\tests\\test_control_corporal.py
"""

from __future__ import annotations

import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
CAMERA_DIR = TESTS_DIR.parent
if str(CAMERA_DIR) not in sys.path:
    sys.path.insert(0, str(CAMERA_DIR))

import control_corporal_dron1 as ctrl  # noqa: E402
from contracts import Gesture, GestureEvent, VelocityIntent  # noqa: E402

TOL = 1e-6
results: list[tuple[str, bool, str]] = []


def anotar(nombre: str, ok: bool, detalle: str = "") -> None:
    results.append((nombre, bool(ok), detalle))


class FakeFlight:
    """Doble del backend de vuelo: registra ordenes, no toca hardware."""

    def __init__(self, flying: bool = True) -> None:
        self.flying = flying
        self.busy = False
        self.height_m = 0.5
        self.velocidades: list[tuple[float, float, float]] = []
        self.llamadas: list[str] = []

    def set_velocity(self, vx, vy, vz) -> None:
        self.velocidades.append((vx, vy, vz))
        self.llamadas.append("set_velocity")

    def hover(self) -> None:
        self.llamadas.append("hover")

    def request_takeoff(self) -> bool:
        self.llamadas.append("takeoff")
        return True

    def request_land(self, _razon="") -> bool:
        self.llamadas.append("land")
        return True


def evento(gesto, velocidad, confirmado=True) -> GestureEvent:
    return GestureEvent(
        gesture=gesto, confidence=1.0, confirmed=confirmado, engaged=True,
        velocity=velocidad, timestamp=0.0,
    )


# ------------------------------------------------------------- rumbo


def test_sin_rumbo_no_se_toca_nada() -> None:
    vx, vy = ctrl.al_marco_del_dron(1.0, 0.0, 0.0)
    anotar("rumbo 0 deja la orden igual",
           abs(vx - 1.0) < TOL and abs(vy) < TOL, f"({vx:.2f}, {vy:.2f})")


def test_el_signo_del_rumbo_es_el_correcto() -> None:
    """La nariz del dron 90 grados a TU izquierda.

    Tu ADELANTE queda, visto desde el dron, 90 grados a su derecha: `vy`
    negativo. Si el signo estuviera cambiado se iria justo al otro lado.
    """
    vx, vy = ctrl.al_marco_del_dron(1.0, 0.0, 90.0)
    anotar("nariz 90 deg a la izquierda -> el dron va a su derecha",
           abs(vx) < TOL and abs(vy + 1.0) < TOL, f"({vx:.2f}, {vy:.2f})")

    vx, vy = ctrl.al_marco_del_dron(1.0, 0.0, -90.0)
    anotar("nariz 90 deg a la derecha -> el dron va a su izquierda",
           abs(vx) < TOL and abs(vy - 1.0) < TOL, f"({vx:.2f}, {vy:.2f})")

    vx, vy = ctrl.al_marco_del_dron(1.0, 0.0, 180.0)
    anotar("nariz al reves -> el dron va hacia atras",
           abs(vx + 1.0) < TOL and abs(vy) < TOL, f"({vx:.2f}, {vy:.2f})")


def test_el_rumbo_conserva_la_magnitud() -> None:
    peor = 0.0
    for grados in range(0, 360, 15):
        vx, vy = ctrl.al_marco_del_dron(0.6, -0.8, float(grados))
        peor = max(peor, abs((vx * vx + vy * vy) ** 0.5 - 1.0))
    anotar("el rumbo no cambia la rapidez", peor < 1e-9, f"error {peor:.2e}")


# ------------------------------------------------------- gesto -> orden


def test_el_marco_del_mundo_tiene_el_signo_correcto() -> None:
    """Con mocap las ordenes van en el marco de la SALA.

    `rumbo` pasa a ser hacia donde mira el operador, en grados antihorarios
    desde el eje +X del Robotat. El rumbo del dron deja de importar.
    """
    vx, vy = ctrl.al_marco_del_mundo(1.0, 0.0, 0.0)
    anotar("mirando a +X, ADELANTE va a +X",
           abs(vx - 1.0) < TOL and abs(vy) < TOL, f"({vx:.2f}, {vy:.2f})")

    vx, vy = ctrl.al_marco_del_mundo(1.0, 0.0, 90.0)
    anotar("mirando a +Y, ADELANTE va a +Y",
           abs(vx) < TOL and abs(vy - 1.0) < TOL, f"({vx:.2f}, {vy:.2f})")

    vx, vy = ctrl.al_marco_del_mundo(0.0, 1.0, 0.0)
    anotar("mirando a +X, tu IZQUIERDA es +Y",
           abs(vx) < TOL and abs(vy - 1.0) < TOL, f"({vx:.2f}, {vy:.2f})")

    vx, vy = ctrl.al_marco_del_mundo(0.0, 1.0, 90.0)
    anotar("mirando a +Y, tu IZQUIERDA es -X",
           abs(vx + 1.0) < TOL and abs(vy) < TOL, f"({vx:.2f}, {vy:.2f})")


def test_los_dos_marcos_giran_en_sentidos_opuestos() -> None:
    """No son la misma funcion con otro nombre, y confundirlas manda el dron
    justo al lado contrario: una lleva del operador al dron, la otra del
    operador al mundo."""
    a = ctrl.al_marco_del_dron(1.0, 0.0, 45.0)
    b = ctrl.al_marco_del_mundo(1.0, 0.0, 45.0)
    anotar("marco del dron y del mundo no coinciden",
           abs(a[1] - b[1]) > 1.0, f"{a} vs {b}")


def test_lo_no_confirmado_no_mueve() -> None:
    """`confirmed=False` significa «no ejecutar». Es la regla del contrato."""
    f = FakeFlight()
    ctrl._aplicar(f, evento(Gesture.ADELANTE, VelocityIntent(), False),
                  0.18, 0.10)
    anotar("un gesto sin confirmar no mueve", f.velocidades == [],
           f"{f.llamadas}")


def test_la_navegacion_escala_a_metros_por_segundo() -> None:
    f = FakeFlight()
    ctrl._aplicar(f, evento(Gesture.ADELANTE, VelocityIntent(vx=1.0)),
                  0.18, 0.10)
    anotar("ADELANTE manda vx en m/s",
           f.velocidades == [(0.18, 0.0, 0.0)], f"{f.velocidades}")

    f = FakeFlight()
    ctrl._aplicar(f, evento(Gesture.ARRIBA, VelocityIntent(vz=1.0)),
                  0.18, 0.10)
    anotar("ARRIBA usa la velocidad vertical, no la horizontal",
           f.velocidades == [(0.0, 0.0, 0.10)], f"{f.velocidades}")


def test_stop_deja_el_dron_quieto() -> None:
    f = FakeFlight()
    ctrl._aplicar(f, evento(Gesture.STOP, VelocityIntent()), 0.18, 0.10)
    anotar("STOP deja hover y no velocidad",
           f.llamadas == ["hover"] and not f.velocidades, f"{f.llamadas}")


def test_en_tierra_solo_se_atiende_el_despegue() -> None:
    f = FakeFlight(flying=False)
    ctrl._aplicar(f, evento(Gesture.ADELANTE, VelocityIntent(vx=1.0)),
                  0.18, 0.10)
    anotar("en tierra un gesto de navegacion no hace nada",
           f.llamadas == [], f"{f.llamadas}")

    f = FakeFlight(flying=False)
    ctrl._aplicar(f, evento(Gesture.DESPEGAR, VelocityIntent()), 0.18, 0.10)
    anotar("en tierra DESPEGAR despega", f.llamadas == ["takeoff"],
           f"{f.llamadas}")


def test_volando_aterrizar_aterriza() -> None:
    f = FakeFlight()
    ctrl._aplicar(f, evento(Gesture.ATERRIZAR, VelocityIntent()), 0.18, 0.10)
    anotar("volando ATERRIZAR aterriza", f.llamadas == ["land"],
           f"{f.llamadas}")


def test_el_rumbo_llega_hasta_la_orden() -> None:
    """De poco sirve la rotacion si el controlador no la aplica."""
    f = FakeFlight()
    ctrl._aplicar(f, evento(Gesture.ADELANTE, VelocityIntent(vx=1.0)),
                  0.18, 0.10, rumbo_deg=90.0)
    vx, vy, _ = f.velocidades[0]
    anotar("el rumbo se aplica a la orden real",
           abs(vx) < 1e-9 and abs(vy + 0.18) < 1e-9, f"{f.velocidades}")


def main() -> int:
    print("Gesto -> orden de vuelo del Dron 1")
    print("Sin radio, sin camara y sin motores.\n")

    for prueba in (
        test_sin_rumbo_no_se_toca_nada,
        test_el_signo_del_rumbo_es_el_correcto,
        test_el_rumbo_conserva_la_magnitud,
        test_el_marco_del_mundo_tiene_el_signo_correcto,
        test_los_dos_marcos_giran_en_sentidos_opuestos,
        test_lo_no_confirmado_no_mueve,
        test_la_navegacion_escala_a_metros_por_segundo,
        test_stop_deja_el_dron_quieto,
        test_en_tierra_solo_se_atiende_el_despegue,
        test_volando_aterrizar_aterriza,
        test_el_rumbo_llega_hasta_la_orden,
    ):
        prueba()

    ancho = max(len(nombre) for nombre, _, _ in results)
    fallos = 0
    for nombre, ok, detalle in results:
        marca = "OK  " if ok else "FALLA"
        extra = f"   {detalle}" if detalle else ""
        print(f"  [{marca}] {nombre.ljust(ancho)}{extra}")
        fallos += not ok

    print()
    if fallos:
        print(f"{fallos} de {len(results)} comprobaciones fallaron. NO VOLAR.")
        return 1
    print(f"Las {len(results)} comprobaciones pasaron.")
    print("Esto valida la traduccion, no el vuelo. Primera prueba sin helices.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
