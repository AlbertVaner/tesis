"""`VueloFormacion`: dos vuelos con la interfaz de uno. Sin radio ni mocap.

Los vuelos son falsos y se tratan por su interfaz, igual que en produccion:
`formacion_camara.py` no importa nada de `single_drone/`. La integracion con el
`VueloRobotat` real esta en `tests/integration/test_formacion_dos_drones.py`.

Uso, desde la raiz del repositorio::

    .\\.venv\\Scripts\\python.exe -m pytest -q .\\controllers\\two_drones\\tests\\test_formacion_camara.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

MODULE_DIR = Path(__file__).resolve().parents[1]
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import formacion_camara as fc  # noqa: E402
from formacion_camara import (  # noqa: E402
    SeguidorFormacion,
    VueloFormacion,
    escalas_de_orbita,
    posiciones_de_anclaje,
    velocidad_con_repulsion,
)


class DronFalso:
    def __init__(self, pose) -> None:
        self.pose = tuple(pose)
        self.en_vuelo = False
        self.aterrizajes = 0

    def estado(self):
        return SimpleNamespace(mocap=self.pose, ekf=self.pose, origen=self.pose,
                               en_vuelo=self.en_vuelo, emergencia=False)

    def land(self) -> None:
        self.aterrizajes += 1
        self.en_vuelo = False


class VueloFalso:
    def __init__(self, pose, *, despega: bool = True) -> None:
        self.dron = DronFalso(pose)
        self.despega = despega
        self.emergency = False
        self.busy = False
        self.ordenes: list[tuple] = []
        self.opciones = SimpleNamespace(velocidad_mps=0.30, radio_max_m=1.0, centro_geocerca=None)
        self.velocidad_seguir_mps = 0.30
        self.velocidad_orbita_mps = 0.20
        self.radio_orbita_m = 0.50

    @property
    def flying(self) -> bool:
        return self.dron.en_vuelo and not self.emergency

    height_m = 0.5

    def connect(self): self.ordenes.append(("connect",))
    def wait_ready(self): pass
    def join(self, timeout=None): pass
    def close(self): self.ordenes.append(("close",))
    def set_params(self, params): return dict(params or {})

    def request_takeoff(self) -> bool:
        if not self.despega:
            return False
        self.dron.en_vuelo = True
        self.ordenes.append(("takeoff",))
        return True

    def request_land(self, reason="gesto") -> bool:
        self.dron.en_vuelo = False
        self.ordenes.append(("land", reason))
        return True

    def emergency_stop(self) -> None:
        self.emergency = True
        self.ordenes.append(("emergency",))

    def set_velocity(self, vx, vy, vz): self.ordenes.append(("vel", vx, vy, vz))
    def hover(self): self.ordenes.append(("hover",))
    def follow_marker(self, seguidor): self.ordenes.append(("follow",))

    def orbit_marker(self, seguidor, *, escala_velocidad=1.0):
        self.ordenes.append(("orbit", round(escala_velocidad, 3)))


class SeguidorFalso:
    def __init__(self, marker=(0.0, 0.0, 0.5)) -> None:
        self.marker = marker
        self.activos: dict[str, tuple] = {}
        self.level = None

    def marker_position(self): return self.marker
    def active(self, clave): return clave in self.activos

    def activate(self, claves, posiciones=None, *, level=False):
        self.level = level
        for c in claves:
            self.activos[c] = tuple(posiciones[c])

    def deactivate(self, claves=None):
        for c in (claves or list(self.activos)):
            self.activos.pop(c, None)


def formacion(pose1=(0.0, 0.0, 0.0), pose2=(0.0, 0.9, 0.0), **kw2):
    v1, v2 = VueloFalso(pose1), VueloFalso(pose2, **kw2)
    f = VueloFormacion({"drone1": v1, "drone2": v2}, log=lambda _m: None,
                       vigilar_separacion=False)
    return f, v1, v2


# ------------------------------------------------------------------ ordenes


def test_despegan_y_aterrizan_los_dos():
    f, v1, v2 = formacion()
    assert f.request_takeoff() is True
    assert f.flying and v1.flying and v2.flying
    assert f.request_land() is True
    assert not f.alguno_volando


def test_no_se_despega_con_los_drones_pegados():
    f, v1, v2 = formacion(pose2=(0.0, 0.3, 0.0))          # 30 cm: menos de los 50 exigidos
    assert f.request_takeoff() is False
    assert ("takeoff",) not in v1.ordenes and ("takeoff",) not in v2.ordenes


def test_si_uno_no_despega_el_otro_vuelve_al_suelo():
    f, v1, v2 = formacion(despega=False)
    assert f.request_takeoff() is False
    assert not v1.flying and v1.ordenes[-1][0] == "land"


def test_la_misma_velocidad_a_los_dos():
    f, v1, v2 = formacion()
    f.request_takeoff()
    f.set_velocity(0.18, 0.0, 0.0)
    assert v1.ordenes[-1] == v2.ordenes[-1] == ("vel", 0.18, 0.0, 0.0)


def test_en_el_suelo_no_se_manda_velocidad():
    f, v1, v2 = formacion()
    f.set_velocity(0.18, 0.0, 0.0)
    assert all(o[0] != "vel" for o in v1.ordenes + v2.ordenes)


def test_si_uno_cae_solo_el_otro_aterriza():
    f, v1, v2 = formacion()
    f.request_takeoff()
    v2.dron.en_vuelo = False                              # bateria, geocerca, watchdog...
    f.set_velocity(0.18, 0.0, 0.0)
    assert not v1.flying and v1.ordenes[-2][0] == "land"
    assert all(o[0] != "vel" for o in v1.ordenes)


def test_la_emergencia_corta_a_los_dos_aunque_uno_falle():
    f, v1, v2 = formacion()
    v1.emergency_stop = lambda: (_ for _ in ()).throw(RuntimeError("radio caida"))
    f.emergency_stop()
    assert v2.emergency and f.emergency


# ---------------------------------------------------------------- seguimiento


def test_las_anclas_se_separan_aunque_los_drones_esten_del_mismo_lado():
    # Los dos al este del marker, a 1.5 m y separados 0.5 m: sin formacion sus
    # anclas (radio 0.45) quedarian a 15 cm una de otra.
    marker = (0.0, 0.0, 0.5)
    poses = {"drone1": (1.5, 0.25, 0.5), "drone2": (1.5, -0.25, 0.5)}
    ficticias = posiciones_de_anclaje(marker, poses)
    angulos = {c: math.degrees(math.atan2(p[1], p[0])) for c, p in ficticias.items()}
    medio = fc.MEDIO_ANGULO_SEGUIR_DEG
    assert angulos["drone1"] == pytest.approx(medio) and angulos["drone2"] == pytest.approx(-medio)
    # Con el radio de seguimiento real las anclas quedan fuera de la zona de repulsion.
    cuerda = 2 * 0.45 * math.sin(math.radians(medio))
    assert cuerda > fc.DISTANCIA_REPULSION_M


def test_cada_dron_se_queda_en_su_lado():
    marker = (0.0, 0.0, 0.5)
    poses = {"drone1": (1.5, -0.25, 0.5), "drone2": (1.5, 0.25, 0.5)}      # al reves que antes
    ficticias = posiciones_de_anclaje(marker, poses)
    assert ficticias["drone1"][1] < 0 < ficticias["drone2"][1]


def test_uno_a_cada_lado_del_marker_se_deja_como_esta():
    poses = {"drone1": (1.0, 0.0, 0.5), "drone2": (-1.0, 0.0, 0.5)}
    assert posiciones_de_anclaje((0.0, 0.0, 0.5), poses) == poses


def test_seguir_ancla_a_los_dos_a_la_altura_del_marker_y_una_sola_vez():
    f, v1, v2 = formacion(pose1=(1.5, 0.25, 0.5), pose2=(1.5, -0.25, 0.5))
    f.request_takeoff()
    seguidor = SeguidorFalso()
    f.follow_marker(seguidor)
    anclas = dict(seguidor.activos)
    f.follow_marker(seguidor)
    assert set(seguidor.activos) == {"drone1", "drone2"} and seguidor.level is True
    assert seguidor.activos == anclas                      # no se re-ancla en cada frame
    assert v1.ordenes[-1] == v2.ordenes[-1] == ("follow",)


def test_el_controlador_ve_un_solo_seguidor():
    seguidor = SeguidorFalso()
    seguidor.activate(("drone1", "drone2"), {"drone1": (1, 0, 0), "drone2": (0, 1, 0)})
    proxy = SeguidorFormacion(seguidor, ("drone1", "drone2"))
    assert proxy.active("drone1")
    proxy.deactivate(("drone1",))                          # el controlador solo conoce una clave
    assert seguidor.activos == {} and not proxy.active("drone1")
    assert proxy.marker_position() == seguidor.marker       # lo demas se delega


# --------------------------------------------------------------------- orbita


def test_en_oposicion_los_dos_van_igual():
    a, b = escalas_de_orbita(math.pi, 0.0)
    assert a == b == pytest.approx(fc.ESCALA_BASE)


def test_si_van_juntos_el_de_delante_acelera_y_el_de_atras_frena():
    a, b = escalas_de_orbita(math.radians(20.0), 0.0)      # A solo 20 grados por delante
    assert a > fc.ESCALA_BASE > b
    assert fc.ESCALA_MIN <= b and a <= fc.ESCALA_MAX


def test_el_desfase_converge_a_180_grados():
    # Integra la fase de cada dron con su escala: tiene que acabar en oposicion.
    fa, fb = math.radians(20.0), 0.0
    omega = 0.30 / 0.50                                   # tope / radio, rad/s
    for _ in range(3000):
        ea, eb = escalas_de_orbita(fa, fb)
        fa += ea * omega * 0.02
        fb += eb * omega * 0.02
    desfase = math.degrees((fa - fb) % (2 * math.pi))
    assert desfase == pytest.approx(180.0, abs=3.0)


def test_orbitar_reparte_la_velocidad_segun_el_desfase():
    # Separados 0.6 m (se puede despegar) pero a solo 33 grados uno del otro sobre el circulo.
    f, v1, v2 = formacion(pose1=(1.0, 0.3, 0.5), pose2=(1.0, -0.3, 0.5))
    f.request_takeoff()
    f.orbit_marker(SeguidorFalso())
    assert v1.ordenes[-1][0] == v2.ordenes[-1][0] == "orbit"
    assert v1.ordenes[-1][1] > v2.ordenes[-1][1]           # drone1 va por delante: acelera


def test_hace_falta_mas_de_un_vuelo():
    with pytest.raises(ValueError):
        VueloFormacion({"drone1": VueloFalso((0, 0, 0))})


def test_mientras_despegan_los_vigilantes_de_cada_dron_siguen_oyendo():
    # Cada vuelo aterriza solo tras 2 s sin ordenes. Durante el despegue la
    # formacion no manda movimiento, pero tiene que seguir hablandoles.
    f, v1, v2 = formacion()
    f.request_takeoff()
    v1.busy = v2.busy = True
    for orden in (lambda: f.follow_marker(SeguidorFalso()), lambda: f.orbit_marker(SeguidorFalso()),
                  lambda: f.set_velocity(0.1, 0.0, 0.0)):
        v1.ordenes.clear(); v2.ordenes.clear()
        orden()
        assert v1.ordenes == v2.ordenes == [("hover",)]


# ------------------------------------------------------------------ repulsion
#
# Vuelo del 2026-09-18 a las 17:33: orbitando, los dos drones llegaron a 0.29 m
# y los aterrizo el supervisor. El operador habia movido el marker 1.3 m en 3 s
# y los dos quedaron del mismo lado del circulo.


def test_lejos_no_se_toca_la_orden():
    vel = (0.2, -0.1, 0.05)
    assert velocidad_con_repulsion(vel, (0.0, 0.0, 0.9), (1.0, 0.0, 0.9)) == vel


def test_cerca_se_anula_lo_que_acerca_y_se_empuja_hacia_fuera():
    # El otro esta 0.45 m al este y la orden es ir hacia el este.
    vx, vy, vz = velocidad_con_repulsion((0.30, 0.0, 0.0), (0.0, 0.0, 0.9), (0.45, 0.0, 0.9))
    assert vx < 0.0 and vy == pytest.approx(0.0) and vz == 0.0


def test_lo_que_no_acerca_se_conserva_en_parte():
    # La orden es ir al norte con el otro al este: el norte sobrevive, atenuado.
    vx, vy, _ = velocidad_con_repulsion((0.0, 0.30, 0.0), (0.0, 0.0, 0.9), (0.70, 0.0, 0.9))
    assert 0.0 < vy < 0.30 and vx < 0.0


def test_por_debajo_de_la_distancia_dura_solo_queda_el_empuje():
    vx, vy, _ = velocidad_con_repulsion((0.0, 0.30, 0.0), (0.0, 0.0, 0.9), (0.50, 0.0, 0.9))
    assert vy == pytest.approx(0.0) and vx == pytest.approx(-fc.REPULSION_MAX_MPS)


def test_superpuestos_no_divide_por_cero():
    vx, vy, _ = velocidad_con_repulsion((0.0, 0.0, 0.0), (0.2, 0.2, 0.9), (0.2, 0.2, 0.9))
    assert math.hypot(vx, vy) == pytest.approx(fc.REPULSION_MAX_MPS)


def test_la_formacion_instala_la_repulsion_en_cada_vuelo():
    f, v1, v2 = formacion(pose1=(0.0, 0.0, 0.9), pose2=(0.45, 0.0, 0.9))
    vx, _vy, _vz = v1.modificar_velocidad((0.30, 0.0, 0.0))
    wx, _wy, _wz = v2.modificar_velocidad((-0.30, 0.0, 0.0))
    assert vx < 0.0 < wx and f.repulsiones == 2


def _simular_orbita(centro_en, *, segundos=40.0, dt=0.05, tope=0.30, radio=0.60):
    """Dos drones puntuales con la ley de orbita de `VueloRobotat` y la formacion."""
    p = {"a": [0.80, 0.30], "b": [0.80, -0.30]}            # del mismo lado, a 0.6 m
    minimo, t = 9.9, 0.0
    while t < segundos:
        c = centro_en(t)
        fases = {k: math.atan2(p[k][1] - c[1], p[k][0] - c[0]) for k in p}
        escalas = dict(zip("ab", escalas_de_orbita(fases["a"], fases["b"])))
        nuevas = {}
        for k, otro in (("a", "b"), ("b", "a")):
            dx, dy = p[k][0] - c[0], p[k][1] - c[1]
            r = math.hypot(dx, dy) or 1e-6
            ux, uy = dx / r, dy / r
            vt, vr = tope * escalas[k], 1.5 * (radio - r)      # la ley de `velocidad_de_orbita`
            vel = [vr * ux - vt * uy, vr * uy + vt * ux, 0.0]
            n = math.hypot(vel[0], vel[1])
            if n > vt:
                vel = [vel[0] * vt / n, vel[1] * vt / n, 0.0]
            vel = velocidad_con_repulsion(tuple(vel), (*p[k], 0.9), (*p[otro], 0.9))
            n = math.hypot(vel[0], vel[1])
            v = min(n, tope)
            nuevas[k] = [p[k][0] + vel[0] / n * v * dt, p[k][1] + vel[1] / n * v * dt] if n > 1e-9 else p[k]
        p = nuevas
        minimo = min(minimo, math.dist(p["a"], p["b"]))
        t += dt
    desfase = math.degrees((math.atan2(p["a"][1] - c[1], p["a"][0] - c[0])
                            - math.atan2(p["b"][1] - c[1], p["b"][0] - c[0])) % (2 * math.pi))
    return minimo, desfase


def test_orbitando_un_centro_quieto_acaban_en_oposicion_sin_acercarse():
    minimo, desfase = _simular_orbita(lambda _t: (0.0, 0.0))
    assert minimo >= 0.55
    assert desfase == pytest.approx(180.0, abs=15.0)


def test_si_el_operador_mueve_el_marker_un_metro_no_se_juntan():
    # Lo del vuelo real: el centro salta 1.3 m en 3 s, de un lado de los drones al otro.
    def centro(t):
        return (1.25 - 1.30 * min(1.0, max(0.0, (t - 5.0) / 3.0)), -0.20 + 0.25 * min(1.0, t / 8.0))
    minimo, _ = _simular_orbita(centro)
    assert minimo > 0.35, f"llegaron a {minimo:.2f} m"


# ------------------------------------------------------------- geocerca comun
#
# Vuelo del 2026-09-18 a las 18:05: despegaron a 1.54 m uno del otro con radio
# 1.0 m **cada uno alrededor de su propio despegue**. La zona comun era una lente
# de 0.46 m y cada cerca empujaba a su dron hacia el otro: llegaron a 0.28 m.


def test_la_formacion_pone_una_sola_geocerca_en_el_punto_medio():
    f, v1, v2 = formacion(pose1=(0.0, -0.5, 0.0), pose2=(0.0, 0.5, 0.0))
    f.connect()
    assert v1.opciones.centro_geocerca == v2.opciones.centro_geocerca == (0.0, 0.0)
    assert f.geocerca_estrecha is None and f.request_takeoff() is True


def test_un_centro_pedido_por_el_operador_se_respeta():
    f, v1, v2 = formacion(pose1=(0.0, -0.5, 0.0), pose2=(0.0, 0.5, 0.0))
    v2.opciones.centro_geocerca = (0.2, 0.1)
    f.connect()
    assert v1.opciones.centro_geocerca == (0.2, 0.1)


def test_con_los_drones_lejos_para_el_radio_no_se_despega_y_se_dice_que_hacer():
    # Lo del vuelo real: 1.54 m entre los dos y radio 1.0.
    f, v1, v2 = formacion(pose1=(0.01, -0.83, 0.0), pose2=(0.06, 0.71, 0.0))
    f.connect()
    assert f.geocerca_estrecha is not None and "--radio-max 1.4" in f.geocerca_estrecha
    assert f.request_takeoff() is False
    assert ("takeoff",) not in v1.ordenes + v2.ordenes


def test_la_orbita_de_dos_drones_no_baja_de_su_radio_minimo():
    f, v1, v2 = formacion()
    assert v1.radio_orbita_m == v2.radio_orbita_m == fc.RADIO_ORBITA_MIN_M


def test_el_motivo_de_no_despegar_cabe_en_el_panel_y_dice_que_hacer():
    # Sesion de las 18:40: drones a 1.95 m, radio 1.0. El operador hizo el gesto
    # dos veces y en la ventana no salia por que no despegaban.
    f, _v1, _v2 = formacion(pose1=(0.59, -0.93, 0.0), pose2=(0.50, 1.01, 0.0))
    f.connect()
    assert f.aviso.startswith("NO DESPEGA") and len(f.aviso) <= 100
    assert "1.9 m" in f.aviso and "1.4 m" in f.aviso and "--radio-max 1.6" in f.aviso


def test_bien_colocados_no_hay_aviso():
    f, _v1, _v2 = formacion(pose1=(0.0, -0.5, 0.0), pose2=(0.0, 0.5, 0.0))
    f.connect()
    assert f.aviso is None


def test_demasiado_juntos_tambien_se_avisa_en_el_panel():
    f, _v1, _v2 = formacion(pose2=(0.0, 0.3, 0.0))
    assert f.request_takeoff() is False and "separarlos" in f.aviso
