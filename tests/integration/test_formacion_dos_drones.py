"""Formacion de dos drones con el `VueloRobotat` real, simulado. Sin radio ni mocap.

Integra dos categorias (`single_drone/robotat` y `two_drones`), por eso vive en
`tests/integration/`. Comprueba lo que los dobles de prueba no pueden: que la
interfaz que `VueloFormacion` supone es la que `VueloRobotat` ofrece de verdad,
y que el controlador por camara la construye con `--dron ambos`.

Uso, desde la raiz del repositorio::

    .\\.venv\\Scripts\\python.exe -m pytest -q .\\tests\\integration\\test_formacion_dos_drones.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

RAIZ = Path(__file__).resolve().parents[2]
for carpeta in ("controllers/shared", "controllers/two_drones", "controllers/single_drone/robotat",
                "controllers/single_drone/camera", "controllers/joystick",
                "external/gesture_detection"):
    ruta = str(RAIZ / carpeta)
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

import dron_robotat as dr  # noqa: E402
import vuelo_camara as vc  # noqa: E402
from formacion_camara import VueloFormacion  # noqa: E402
from vuelo_camara import VueloRobotat, opciones_camara  # noqa: E402


class Seguidor:
    """Lo que `VueloRobotat` y `VueloFormacion` usan de `CameraMarkerFollower`."""

    RADIO = 0.45

    def __init__(self, marker) -> None:
        self.marker = tuple(marker)
        self.offsets: dict[str, tuple[float, float, float]] = {}

    def marker_position(self): return self.marker
    def active(self, clave): return clave in self.offsets

    def activate(self, claves, posiciones=None, *, level=False):
        for c in claves:
            dx, dy = posiciones[c][0] - self.marker[0], posiciones[c][1] - self.marker[1]
            n = math.hypot(dx, dy)
            self.offsets[c] = (dx * self.RADIO / n, dy * self.RADIO / n, 0.0)

    def desired(self, clave):
        return tuple(m + o for m, o in zip(self.marker, self.offsets[clave]))

    def deactivate(self, claves=None):
        for c in (claves or list(self.offsets)):
            self.offsets.pop(c, None)


@pytest.fixture
def formacion(monkeypatch):
    vuelos = {}
    for clave, nombre in (("drone1", "Dron 1"), ("drone2", "Dron 2")):
        opciones = opciones_camara(uri=None, topic=f"mocap/{clave}", nombre=nombre, dry_run=True,
                                   radio_max_m=1.0)
        vuelos[clave] = VueloRobotat(opciones, dry_run=True, log=lambda _m: None, key=clave)
    f = VueloFormacion(vuelos, log=lambda _m: None, vigilar_separacion=False)
    f.connect()
    yield f, monkeypatch
    f.close()


def _en_el_aire(f, monkeypatch) -> None:
    assert f.request_takeoff() is True
    monkeypatch.setattr(dr, "ahora", lambda: 1e9)          # el despegue ya termino
    monkeypatch.setattr(vc, "ahora", lambda: 1e9)
    assert f.flying and not f.busy


def test_los_simulados_arrancan_separados_y_despegan_los_dos(formacion):
    f, monkeypatch = formacion
    assert f.separacion_m() == pytest.approx(0.9)
    _en_el_aire(f, monkeypatch)
    assert all(v.flying for v in f.vuelos.values())


def test_un_gesto_de_direccion_mueve_a_los_dos_igual(formacion):
    f, monkeypatch = formacion
    _en_el_aire(f, monkeypatch)
    f.set_velocity(0.18, 0.0, 0.0)
    ultimas = [v.dron.ordenes[-1] for v in f.vuelos.values()]
    assert ultimas[0][0] == ultimas[1][0] == "velocidad" or ultimas[0] == ultimas[1]


def test_seguir_deja_las_anclas_separadas(formacion):
    f, monkeypatch = formacion
    _en_el_aire(f, monkeypatch)
    seguidor = Seguidor((2.0, 0.45, 0.5))                 # los dos drones al oeste del marker
    f.follow_marker(seguidor)
    a, b = seguidor.desired("drone1"), seguidor.desired("drone2")
    assert math.dist(a, b) > 0.60


def test_orbitar_acepta_la_escala_de_velocidad(formacion):
    f, monkeypatch = formacion
    _en_el_aire(f, monkeypatch)
    f.orbit_marker(Seguidor((0.0, 0.45, 0.5)))            # no lanza: la firma coincide


def test_el_controlador_construye_la_formacion_con_dron_ambos(monkeypatch):
    import control_camara_dron1 as ctrl

    args = SimpleNamespace(dron="ambos", backend="robotat", dry_run=True, ganancias="robotat",
                           param=None, radio_max=1.0, centro_geocerca=None, velocidad_tope=0.30,
                           velocidad_seguir=0.30, radio_orbita=0.50, velocidad_orbita=0.20,
                           topico_dron=None)
    monkeypatch.setattr(ctrl, "parametros_firmware", lambda _a: {})
    flight = ctrl.crear_vuelo(args)
    try:
        assert isinstance(flight, VueloFormacion) and set(flight.vuelos) == {"drone1", "drone2"}
        assert ctrl.datos_del_dron(args)[0] == "drone1"
    finally:
        flight.close()


def test_la_formacion_solo_existe_sobre_el_nucleo_robotat():
    import control_camara_dron1 as ctrl

    with pytest.raises(SystemExit):
        ctrl.crear_formacion(SimpleNamespace(dron="ambos", backend="mocap"))


def test_la_pirueta_en_formacion_es_una_doble_helice_en_oposicion(formacion):
    """Dos drones simulados que obedecen la velocidad: bajan girando en oposicion,
    nunca se acercan y acaban arriba, cada uno donde termino su helice."""
    f, monkeypatch = formacion
    _en_el_aire(f, monkeypatch)
    origen_z = {c: float(v.dron.estado().origen[2]) for c, v in f.vuelos.items()}
    for c, v in f.vuelos.items():
        x, y, _ = v.dron._pose
        v.dron._pose = (x, y, origen_z[c] + 0.85)
    reloj = [0.0]
    sep_min, z_min, terminada = 9.9, 9.9, False
    for _ in range(4000):
        antes = {c: len(v.dron.ordenes) for c, v in f.vuelos.items()}
        terminada = f.pirueta(reloj=lambda: reloj[0])
        if terminada:
            break
        for c, v in f.vuelos.items():
            if len(v.dron.ordenes) > antes[c]:
                vel = v.dron.ordenes[-1][1]
                p = v.dron._pose
                v.dron._pose = (p[0] + vel[0] * 0.05, p[1] + vel[1] * 0.05, p[2] + vel[2] * 0.05)
        reloj[0] += 0.05
        a, b = (v.dron._pose for v in f.vuelos.values())
        sep_min = min(sep_min, math.hypot(a[0] - b[0], a[1] - b[1]))
        z_min = min(z_min, a[2], b[2])
    assert terminada
    assert sep_min > 0.80, f"llegaron a {sep_min:.2f} m"
    assert z_min == pytest.approx(min(origen_z.values()) + vc.ESPIRAL_Z_BAJA_M, abs=0.08)
