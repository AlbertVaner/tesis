"""`VueloRobotat`: la interfaz que espera el controlador por cámara, sin hardware."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import dron_robotat as dr  # noqa: E402
import vuelo_camara as vc  # noqa: E402
from vuelo_camara import VueloRobotat, opciones_camara  # noqa: E402


def vuelo(**kw) -> VueloRobotat:
    o = opciones_camara(uri=None, topic="mocap/drone4", nombre="Dron 2", dry_run=True, **kw)
    return VueloRobotat(o, dry_run=True, log=lambda _m: None)


class TestOpciones:
    def test_preajuste_y_param(self):
        o = opciones_camara(uri="radio://0/90/2M/E7E7E7E7E5", topic="mocap/drone4", nombre="Dron 2",
                            parametros={"posCtlPid.thrustBase": "39500"})
        assert o.parametros["velCtlPid.vzKi"] == "8"
        assert o.parametros["posCtlPid.thrustBase"] == "39500" and o.thrust_base_explicito
        assert o.velocidad_mps == vc.VELOCIDAD_MAX_CAMARA_MPS

    def test_sin_uri_real_falla(self):
        with pytest.raises(ValueError, match="URI"):
            opciones_camara(uri=None, topic="t", nombre="Dron 2")

    def test_ganancias_desconocidas(self):
        with pytest.raises(ValueError):
            opciones_camara(uri=None, topic="t", nombre="Dron 2", ganancias="x", dry_run=True)


class TestInterfaz:
    def test_flujo_completo(self, monkeypatch):
        f = vuelo()
        assert not f.flying and f.height_m is None
        f.connect()
        assert f.set_params({"posCtlPid.thrustBase": "46000"})["posCtlPid.thrustBase"] == "46000"
        assert f.height_m == pytest.approx(0.0)
        assert f.request_takeoff()
        assert f.flying and f.busy
        assert not f.request_takeoff()  # ya en vuelo
        f.set_velocity(0.18, 0.0, 0.0)  # ocupado: se ignora sin error
        monkeypatch.setattr(dr, "ahora", lambda: 1e9)
        monkeypatch.setattr(vc, "ahora", lambda: 1e9)
        assert not f.busy
        f.set_velocity(0.18, 0.0, 0.0)
        e = f.dron.estado()
        assert e.modo == "FLUIDO" and e.objetivo[0] > 0
        assert f.dron.ordenes[-1][0] == "velocidad"
        # la magnitud pedida se respeta (0.18 m/s), no el tope
        vel = f.dron.ordenes[-1][1]
        assert abs(vel[0]) == pytest.approx(0.18)
        f.hover()
        assert f.dron.estado().modo == "VUELO"
        assert f.request_land("prueba")
        assert not f.flying
        f.close()

    def test_velocidad_por_encima_del_tope_se_acota(self, monkeypatch):
        f = vuelo()
        f.connect()
        f.request_takeoff()
        monkeypatch.setattr(dr, "ahora", lambda: 1e9)
        monkeypatch.setattr(vc, "ahora", lambda: 1e9)
        f.set_velocity(1.0, 0.0, 0.0)
        assert abs(f.dron.ordenes[-1][1][0]) == pytest.approx(vc.VELOCIDAD_MAX_CAMARA_MPS)

    def test_emergencia(self):
        f = vuelo()
        f.connect()
        f.request_takeoff()
        f.emergency_stop()
        assert f.emergency and not f.flying and f.dron.estado().emergencia
        assert not f.request_takeoff()

    def test_deadman_frena_y_luego_aterriza(self, monkeypatch):
        f = vuelo()
        f.connect()
        f.request_takeoff()
        reloj = [1e9]
        monkeypatch.setattr(dr, "ahora", lambda: reloj[0])
        monkeypatch.setattr(vc, "ahora", lambda: reloj[0])
        f.set_velocity(0.0, 0.18, 0.0)
        assert f.dron.estado().modo == "FLUIDO"
        # una pasada del vigilante con 0.5 s de silencio: frena
        reloj[0] += 0.5
        waits = iter([False, True])
        monkeypatch.setattr(f._watchdog_stop, "wait", lambda _t: next(waits))
        f._watchdog_loop()
        assert f.dron.estado().modo == "VUELO" and f.flying
        # 2.5 s de silencio: aterriza
        reloj[0] += 2.5
        waits = iter([False, True])
        f._watchdog_loop()
        assert not f.flying


class SeguidorFalso:
    """Imita `CameraMarkerFollower`: ancla fija y objetivo configurable."""

    def __init__(self, objetivo):
        self.objetivo = objetivo
        self.activos = {}

    def active(self, key):
        return key in self.activos

    def activate(self, keys, positions=None, *, level=False):
        self.level = level
        for key in keys:
            self.activos[key] = positions[key]

    def desired(self, key):
        assert key in self.activos
        return self.objetivo

    def marker_position(self):
        return self.objetivo


class TestSeguirMarker:
    def _volando(self, monkeypatch, **kw):
        f = VueloRobotat(opciones_camara(uri=None, topic="t", nombre="Dron 2", dry_run=True),
                         dry_run=True, log=lambda _m: None, key="drone2", **kw)
        f.connect()
        f.request_takeoff()
        monkeypatch.setattr(dr, "ahora", lambda: 1e9)
        monkeypatch.setattr(vc, "ahora", lambda: 1e9)
        return f

    def test_persigue_con_kp_y_tope(self, monkeypatch):
        f = self._volando(monkeypatch)
        pose = f.dron.estado().ekf
        seguidor = SeguidorFalso((pose[0] + 1.0, pose[1], pose[2]))  # 1 m delante
        f.follow_marker(seguidor)
        assert seguidor.active("drone2") and seguidor.level  # ancla a la altura del marker
        vel = f.dron.ordenes[-1][1]
        assert vel[0] == pytest.approx(vc.SEGUIR_VELOCIDAD_MPS)  # Kp*1.0 = 1.5 -> tope 0.30
        assert vel[1] == 0.0 and vel[2] == 0.0

    def test_cerca_del_ancla_se_frena(self, monkeypatch):
        f = self._volando(monkeypatch)
        pose = f.dron.estado().ekf
        seguidor = SeguidorFalso((pose[0] + 0.02, pose[1] - 0.01, pose[2]))
        f.follow_marker(seguidor)
        assert f.dron.ordenes[-1][0] == "takeoff"  # dentro de la zona muerta: sin velocidad

    def test_error_medio_da_velocidad_proporcional(self, monkeypatch):
        f = self._volando(monkeypatch, velocidad_seguir_mps=0.30)
        pose = f.dron.estado().ekf
        seguidor = SeguidorFalso((pose[0], pose[1] + 0.10, pose[2]))
        f.follow_marker(seguidor)
        vel = f.dron.ordenes[-1][1]
        assert vel[1] == pytest.approx(vc.SEGUIR_KP * 0.10)

    def test_velocidad_de_seguimiento_acotada_por_las_opciones(self, monkeypatch):
        f = self._volando(monkeypatch, velocidad_seguir_mps=5.0)
        assert f.velocidad_seguir_mps == vc.VELOCIDAD_MAX_CAMARA_MPS


class TestOrbita:
    def test_plan_orbita(self):
        objetivo, tangente = vc.plan_orbita((1.0, 2.0, 0.8), 0.5, 0.0, 0.2)
        assert objetivo == pytest.approx((1.5, 2.0, 0.8))
        assert tangente == pytest.approx((0.0, 0.2, 0.0))
        objetivo, tangente = vc.plan_orbita((0.0, 0.0, 0.5), 0.5, math.pi / 2, 0.2)
        assert objetivo == pytest.approx((0.0, 0.5, 0.5))
        assert tangente == pytest.approx((-0.2, 0.0, 0.0))

    def _volando(self, monkeypatch, **kw):
        f = VueloRobotat(opciones_camara(uri=None, topic="t", nombre="Dron 2", dry_run=True),
                         dry_run=True, log=lambda _m: None, key="drone2", **kw)
        f.connect()
        f.request_takeoff()
        reloj = [1e9]
        monkeypatch.setattr(dr, "ahora", lambda: reloj[0])
        monkeypatch.setattr(vc, "ahora", lambda: reloj[0])
        return f, reloj

    def test_empieza_donde_esta_y_avanza_antihorario(self, monkeypatch):
        f, reloj = self._volando(monkeypatch, radio_orbita_m=0.5, velocidad_orbita_mps=0.2)
        pose = f.dron.estado().ekf
        marker = (pose[0] - 0.5, pose[1], 0.9)  # el dron esta en theta = 0, medio metro a +X
        seguidor = SeguidorFalso(marker)
        f.orbit_marker(seguidor)
        # el objetivo va ORBITA_ANTICIPO_DEG por delante de la fase del dron (0)
        assert f._orbita[0] == pytest.approx(math.radians(vc.ORBITA_ANTICIPO_DEG))
        vel = f.dron.ordenes[-1][1]
        assert vel[1] > 0.0 and abs(vel[0]) < vel[1]  # antihorario: hacia +Y
        assert vel[2] > 0    # sube hacia la altura del marker (0.9 > 0.4)
        # el simulado se movio hacia +Y: la fase crece y el objetivo sigue por delante
        reloj[0] += 0.25
        f.orbit_marker(seguidor)
        assert f._orbita[0] > math.radians(vc.ORBITA_ANTICIPO_DEG)

    def test_hover_termina_la_orbita(self, monkeypatch):
        f, reloj = self._volando(monkeypatch)
        seguidor = SeguidorFalso((0.5, 0.5, 0.6))
        f.orbit_marker(seguidor)
        assert f._orbita is not None
        f.hover()
        assert f._orbita is None and f.dron.estado().modo == "VUELO"

    def test_radio_y_velocidad_configurables(self):
        f = VueloRobotat(opciones_camara(uri=None, topic="t", nombre="Dron 2", dry_run=True),
                         dry_run=True, log=lambda _m: None, radio_orbita_m=0.05, velocidad_orbita_mps=5.0)
        assert f.radio_orbita_m == 0.05 and f.velocidad_orbita_mps == vc.VELOCIDAD_MAX_CAMARA_MPS


def test_opciones_camara_centro_geocerca():
    o = opciones_camara(uri=None, topic="t", nombre="Dron 2", dry_run=True, centro_geocerca=(0.0, -0.4))
    assert o.centro_geocerca == (0.0, -0.4)
    assert opciones_camara(uri=None, topic="t", nombre="Dron 2", dry_run=True).centro_geocerca is None
