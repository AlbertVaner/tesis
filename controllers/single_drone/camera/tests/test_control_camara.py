"""Verifica la traduccion de gesto a orden de vuelo. Sin radio ni motores.

Lo unico que se comprueba aqui es lo que puede mandar el dron en la direccion
equivocada:

* que un gesto **no confirmado** no mueva nada;
* que STOP y los gestos de estado dejen el dron en hover, no en movimiento;
* que la correccion de rumbo tenga el signo correcto;
* que las etiquetas del detector de mano entren por el mismo contrato que
  el vocabulario corporal.

Uso, desde la raiz del repositorio:

    .\\.venv\\Scripts\\python.exe -m pytest -q .\\controllers\\single_drone\\camera\\tests\\test_control_camara.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
CAMERA_DIR = TESTS_DIR.parent
if str(CAMERA_DIR) not in sys.path:
    sys.path.insert(0, str(CAMERA_DIR))

import control_camara_dron1 as ctrl  # noqa: E402
from contracts import Gesture, GestureEvent, VelocityIntent  # noqa: E402

TOL = 1e-6


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


class FakeFollow:
    def __init__(self, activo: bool) -> None:
        self.activo = activo

    def active(self, _key) -> bool:
        return self.activo


def evento(gesto, velocidad, confirmado=True) -> GestureEvent:
    return GestureEvent(
        gesture=gesto, confidence=1.0, confirmed=confirmado, engaged=True,
        velocity=velocidad, timestamp=0.0,
    )


# ------------------------------------------------------------- rumbo


def test_sin_rumbo_no_se_toca_nada() -> None:
    vx, vy = ctrl.al_marco_del_dron(1.0, 0.0, 0.0)
    assert abs(vx - 1.0) < TOL and abs(vy) < TOL, \
        f"rumbo 0 deja la orden igual: ({vx:.2f}, {vy:.2f})"


def test_el_signo_del_rumbo_es_el_correcto() -> None:
    """La nariz del dron 90 grados a TU izquierda: tu ADELANTE queda, visto
    desde el dron, 90 grados a su derecha (`vy` negativo)."""
    vx, vy = ctrl.al_marco_del_dron(1.0, 0.0, 90.0)
    assert abs(vx) < TOL and abs(vy + 1.0) < TOL, \
        f"nariz 90 deg a la izquierda -> el dron va a su derecha: ({vx:.2f}, {vy:.2f})"

    vx, vy = ctrl.al_marco_del_dron(1.0, 0.0, -90.0)
    assert abs(vx) < TOL and abs(vy - 1.0) < TOL, \
        f"nariz 90 deg a la derecha -> el dron va a su izquierda: ({vx:.2f}, {vy:.2f})"

    vx, vy = ctrl.al_marco_del_dron(1.0, 0.0, 180.0)
    assert abs(vx + 1.0) < TOL and abs(vy) < TOL, \
        f"nariz al reves -> el dron va hacia atras: ({vx:.2f}, {vy:.2f})"


def test_el_rumbo_conserva_la_magnitud() -> None:
    peor = 0.0
    for grados in range(0, 360, 15):
        vx, vy = ctrl.al_marco_del_dron(0.6, -0.8, float(grados))
        peor = max(peor, abs((vx * vx + vy * vy) ** 0.5 - 1.0))
    assert peor < 1e-9, f"el rumbo no cambia la rapidez: error {peor:.2e}"


def test_el_marco_del_mundo_tiene_el_signo_correcto() -> None:
    """Con mocap las ordenes van en el marco de la SALA y `rumbo` es hacia
    donde mira el operador, en grados antihorarios desde +X del Robotat."""
    vx, vy = ctrl.al_marco_del_mundo(1.0, 0.0, 0.0)
    assert abs(vx - 1.0) < TOL and abs(vy) < TOL, \
        f"mirando a +X, ADELANTE va a +X: ({vx:.2f}, {vy:.2f})"

    vx, vy = ctrl.al_marco_del_mundo(1.0, 0.0, 90.0)
    assert abs(vx) < TOL and abs(vy - 1.0) < TOL, \
        f"mirando a +Y, ADELANTE va a +Y: ({vx:.2f}, {vy:.2f})"

    vx, vy = ctrl.al_marco_del_mundo(0.0, 1.0, 0.0)
    assert abs(vx) < TOL and abs(vy - 1.0) < TOL, \
        f"mirando a +X, tu IZQUIERDA es +Y: ({vx:.2f}, {vy:.2f})"

    vx, vy = ctrl.al_marco_del_mundo(0.0, 1.0, 90.0)
    assert abs(vx + 1.0) < TOL and abs(vy) < TOL, \
        f"mirando a +Y, tu IZQUIERDA es -X: ({vx:.2f}, {vy:.2f})"


def test_los_dos_marcos_giran_en_sentidos_opuestos() -> None:
    a = ctrl.al_marco_del_dron(1.0, 0.0, 45.0)
    b = ctrl.al_marco_del_mundo(1.0, 0.0, 45.0)
    assert abs(a[1] - b[1]) > 1.0, f"marco del dron y del mundo no coinciden: {a} vs {b}"


# ------------------------------------------------------- gesto -> orden


def test_lo_no_confirmado_no_mueve() -> None:
    """`confirmed=False` significa «no ejecutar». Es la regla del contrato."""
    f = FakeFlight()
    ctrl._aplicar(f, evento(Gesture.ADELANTE, VelocityIntent(vx=1.0), False),
                  0.18, 0.10)
    assert f.velocidades == [] and f.llamadas == ["hover"], \
        f"un gesto sin confirmar no mueve: {f.llamadas}"


def test_la_navegacion_escala_a_metros_por_segundo() -> None:
    f = FakeFlight()
    ctrl._aplicar(f, evento(Gesture.ADELANTE, VelocityIntent(vx=1.0)),
                  0.18, 0.10)
    assert f.velocidades == [(0.18, 0.0, 0.0)], \
        f"ADELANTE manda vx en m/s: {f.velocidades}"

    f = FakeFlight()
    ctrl._aplicar(f, evento(Gesture.ARRIBA, VelocityIntent(vz=1.0)),
                  0.18, 0.10)
    assert f.velocidades == [(0.0, 0.0, 0.10)], \
        f"ARRIBA usa la velocidad vertical, no la horizontal: {f.velocidades}"


def test_stop_deja_el_dron_quieto() -> None:
    f = FakeFlight()
    ctrl._aplicar(f, evento(Gesture.STOP, VelocityIntent()), 0.18, 0.10)
    assert f.llamadas == ["hover"] and not f.velocidades, \
        f"STOP deja hover y no velocidad: {f.llamadas}"


def test_en_tierra_solo_se_atiende_el_despegue() -> None:
    f = FakeFlight(flying=False)
    ctrl._aplicar(f, evento(Gesture.ADELANTE, VelocityIntent(vx=1.0)),
                  0.18, 0.10)
    assert f.llamadas == [], f"en tierra un gesto de navegacion no hace nada: {f.llamadas}"

    f = FakeFlight(flying=False)
    ctrl._aplicar(f, evento(Gesture.DESPEGAR, VelocityIntent()), 0.18, 0.10)
    assert f.llamadas == ["takeoff"], f"en tierra DESPEGAR despega: {f.llamadas}"


def test_volando_aterrizar_aterriza() -> None:
    f = FakeFlight()
    ctrl._aplicar(f, evento(Gesture.ATERRIZAR, VelocityIntent()), 0.18, 0.10)
    assert f.llamadas == ["land"], f"volando ATERRIZAR aterriza: {f.llamadas}"


def test_el_rumbo_llega_hasta_la_orden() -> None:
    f = FakeFlight()
    ctrl._aplicar(f, evento(Gesture.ADELANTE, VelocityIntent(vx=1.0)),
                  0.18, 0.10, rumbo_deg=90.0)
    vx, vy, _ = f.velocidades[0]
    assert abs(vx) < 1e-9 and abs(vy + 0.18) < 1e-9, \
        f"el rumbo se aplica a la orden real: {f.velocidades}"


# ------------------------------------------------------ manos -> contrato


def test_las_etiquetas_de_mano_entran_por_el_contrato() -> None:
    e = ctrl.evento_de_mano("ADELANTE")
    assert e.gesture is Gesture.ADELANTE and e.confirmed and e.velocity.vx == 1.0, \
        f"ADELANTE de mano = ADELANTE confirmado con vx=+1: {e}"
    e = ctrl.evento_de_mano("ABAJO")
    assert e.velocity.vz == -1.0 and e.velocity.quieto is False, "ABAJO de mano baja"
    for etiqueta in ("REPOSO", "SIN_DETECCION", "SEGUIR_MARKER", "DETENER_SEGUIMIENTO"):
        e = ctrl.evento_de_mano(etiqueta)
        assert e.gesture is Gesture.NO_GESTURE and not e.confirmed and e.velocity.quieto, \
            f"{etiqueta} de mano no es una orden"
    e = ctrl.evento_de_mano("STOP")
    assert e.gesture is Gesture.STOP and e.confirmed, "STOP de mano es STOP"

    f = FakeFlight()
    ctrl._aplicar(f, ctrl.evento_de_mano("REPOSO"), 0.18, 0.10)
    assert f.llamadas == ["hover"], f"REPOSO volando = hover: {f.llamadas}"
    f = FakeFlight()
    ctrl._aplicar(f, ctrl.evento_de_mano("DERECHA"), 0.18, 0.10)
    assert f.velocidades == [(0.0, -0.18, 0.0)], \
        f"DERECHA de mano manda vy negativo: {f.velocidades}"


def test_la_grafica_cuenta_lo_que_el_dron_hizo() -> None:
    f = FakeFlight()
    comando, ok = ctrl._comando_ejecutado(evento(Gesture.ADELANTE, VelocityIntent(vx=1.0)), "REPOSO", f, FakeFollow(True))
    assert comando == "SEGUIR_MARKER" and ok, \
        f"con seguimiento activo la grafica registra SEGUIR_MARKER: {comando}"
    comando, ok = ctrl._comando_ejecutado(evento(Gesture.STOP, VelocityIntent(), False), "SEGUIR_MARKER", f, FakeFollow(True))
    assert comando == "STOP" and not ok, f"STOP manda sobre todo lo demas: {comando}"
    comando, ok = ctrl._comando_ejecutado(evento(Gesture.ARRIBA, VelocityIntent(vz=1.0)), "REPOSO", f, FakeFollow(False))
    assert comando == "ARRIBA" and ok, f"sin seguimiento la grafica registra el gesto: {comando}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
