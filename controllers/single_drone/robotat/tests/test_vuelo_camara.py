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


def _opc(**kw):
    return opciones_camara(uri=None, topic="mocap/drone4", nombre="Dron 2", dry_run=True, **kw)


def test_el_tope_de_velocidad_se_puede_subir_pero_tiene_techo():
    assert _opc().velocidad_mps == vc.VELOCIDAD_MAX_CAMARA_MPS
    assert _opc(velocidad_max_mps=0.45).velocidad_mps == 0.45
    # Un error de tecleo (5 en vez de 0.5) no llega al dron.
    assert _opc(velocidad_max_mps=5.0).velocidad_mps == vc.VELOCIDAD_TOPE_ABSOLUTO_MPS


def test_seguir_y_orbita_suben_con_el_tope_y_nunca_lo_pasan():
    f = VueloRobotat(_opc(velocidad_max_mps=0.45), dry_run=True, log=lambda _m: None,
                     velocidad_seguir_mps=0.45, velocidad_orbita_mps=0.90)
    assert f.velocidad_seguir_mps == 0.45
    assert f.velocidad_orbita_mps == 0.45


class TestMarkerPorEncimaDelTecho:
    """El operador lleva el marker en la mano, a 1.2-1.5 m; el dron no pasa de 0.90."""

    def _volando(self, monkeypatch):
        f = VueloRobotat(_opc(), dry_run=True, log=lambda _m: None, key="drone2")
        f.connect()
        f.request_takeoff()
        monkeypatch.setattr(dr, "ahora", lambda: 1e9)
        monkeypatch.setattr(vc, "ahora", lambda: 1e9)
        return f

    def test_la_banda_alcanzable(self):
        assert vc.altura_alcanzable(1.50, 0.0) == pytest.approx(0.90)
        assert vc.altura_alcanzable(0.05, 0.0) == pytest.approx(0.30)
        assert vc.altura_alcanzable(0.60, 0.0) == pytest.approx(0.60)
        assert vc.altura_alcanzable(1.50, 0.10) == pytest.approx(1.00)      # sobre el origen

    def test_seguir_no_gasta_la_velocidad_en_subir_contra_el_techo(self, monkeypatch):
        f = self._volando(monkeypatch)
        x, y, z = f.dron.estado().ekf
        techo = vc.altura_alcanzable(9.9, float(f.dron.estado().origen[2]))
        f.dron._pose = (x, y, techo)                      # ya esta en el techo del modo fluido
        seguidor = SeguidorFalso((x + 1.0, y, 1.50))      # ancla 1 m delante y 0.6 m por encima
        f.follow_marker(seguidor)
        vel = f.dron.ordenes[-1][1]
        assert vel[2] == pytest.approx(0.0, abs=1e-6)     # antes pedia +0.9 hacia arriba
        assert vel[0] == pytest.approx(vc.SEGUIR_VELOCIDAD_MPS)   # y el horizontal, entero


class TestLeyDeOrbita:
    """La orbita tiene que mantener el radio. Perseguir un punto 30 grados por
    delante lo dejaba en 0.37 m para un circulo de 0.50 (vuelo de las 18:05)."""

    def test_sobre_el_circulo_la_velocidad_es_tangente_y_antihoraria(self):
        vx, vy, vz = vc.velocidad_de_orbita((0.5, 0.0, 0.9), (0.0, 0.0, 0.9), 0.5, 0.2, 0.9)
        assert vx == pytest.approx(0.0) and vy == pytest.approx(0.2) and vz == pytest.approx(0.0)

    def test_dentro_del_circulo_empuja_hacia_fuera(self):
        vx, _vy, _vz = vc.velocidad_de_orbita((0.2, 0.0, 0.9), (0.0, 0.0, 0.9), 0.5, 0.2, 0.9)
        assert vx == pytest.approx(vc.ORBITA_KP_RADIO * 0.3)

    def test_fuera_empuja_hacia_dentro(self):
        vx, _vy, _vz = vc.velocidad_de_orbita((0.8, 0.0, 0.9), (0.0, 0.0, 0.9), 0.5, 0.2, 0.9)
        assert vx < 0.0

    def test_integrada_converge_al_radio_y_no_al_37_por_ciento(self):
        import math
        p, c = [0.15, 0.05], (0.0, 0.0, 0.9)                 # empieza casi en el centro
        for _ in range(1500):
            v = vc.velocidad_de_orbita((p[0], p[1], 0.9), c, 0.5, 0.25, 0.9)
            n = math.hypot(v[0], v[1]); k = min(1.0, 0.30 / n)
            p = [p[0] + v[0] * k * 0.02, p[1] + v[1] * k * 0.02]
        assert math.hypot(*p) == pytest.approx(0.5, abs=0.03)


class TestZonaDelMarker:
    """Ninguna orden acerca el dron a la mano del operador."""

    def test_fuera_de_la_zona_no_se_toca(self):
        vel = (0.2, 0.0, 0.0)
        assert vc.fuera_del_marker(vel, (2.0, 0.0, 0.9), (0.0, 0.0, 1.3), 0.6) == vel

    def test_dentro_se_anula_lo_que_acerca_y_se_empuja_hacia_fuera(self):
        vx, vy, vz = vc.fuera_del_marker((-0.30, 0.10, 0.05), (0.4, 0.0, 0.9), (0.0, 0.0, 1.3), 0.6)
        assert vx == pytest.approx(vc.EXCLUSION_MARKER_KP * 0.2)       # solo el empuje, hacia +x
        assert vy == pytest.approx(0.10) and vz == 0.05                # lo tangencial y Z se respetan

    def test_sin_radio_no_hay_zona(self):
        vel = (-0.3, 0.0, 0.0)
        assert vc.fuera_del_marker(vel, (0.1, 0.0, 0.9), (0.0, 0.0, 1.3), 0.0) == vel

    def test_un_gesto_de_direccion_tampoco_mete_al_dron_en_la_zona(self, monkeypatch):
        f = VueloRobotat(_opc(), dry_run=True, log=lambda _m: None, key="drone2")
        f.connect(); f.request_takeoff()
        monkeypatch.setattr(dr, "ahora", lambda: 1e9); monkeypatch.setattr(vc, "ahora", lambda: 1e9)
        x, y, z = f.dron.estado().ekf
        f.vigilar_marker(SeguidorFalso((x + 0.4, y, 1.3)), 0.6)        # el marker, 40 cm delante
        f.set_velocity(0.18, 0.0, 0.0)                                 # ADELANTE, hacia el marker
        vel = f.dron.ordenes[-1][1]
        assert vel[0] < 0.0                                            # se aleja en vez de acercarse


class TestPirueta:
    """La maniobra de la demo de Bitcraze en IROS 2018: espiral hacia abajo y
    subida por el eje central."""

    def _plan(self, **kw):
        return vc.plan_espiral((1.0, 2.0, 0.90), 0.0, 0.30, **kw)

    def test_empieza_y_termina_en_el_mismo_sitio(self):
        plan = self._plan()
        assert vc.punto_espiral(plan, 0.0) == pytest.approx((1.0, 2.0, 0.90))
        assert vc.punto_espiral(plan, 2.0) == pytest.approx((1.0, 2.0, 0.90))

    def test_abajo_esta_en_el_eje_y_en_medio_en_el_radio_maximo(self):
        import math
        plan = self._plan()
        x, y, z = vc.punto_espiral(plan, 1.0)
        assert (x, y) == pytest.approx((1.0, 2.0)) and z == pytest.approx(0.35)
        x, y, _ = vc.punto_espiral(plan, 0.5)
        assert math.hypot(x - 1.0, y - 2.0) == pytest.approx(vc.ESPIRAL_RADIO_M)

    def test_la_subida_es_vertical_por_el_eje(self):
        plan = self._plan()
        for s in (1.2, 1.5, 1.8):
            x, y, _ = vc.punto_espiral(plan, s)
            assert (x, y) == pytest.approx((1.0, 2.0))

    def test_no_hay_saltos_de_posicion_entre_tramos(self):
        import math
        plan = self._plan()
        pasos = [vc.punto_espiral(plan, i / 400.0) for i in range(801)]
        assert max(math.dist(a, b) for a, b in zip(pasos, pasos[1:])) < 0.02

    def test_el_tramo_mas_rapido_respeta_el_tope(self):
        import math
        plan = self._plan()
        dt = plan.t_bajada_s / 2000.0
        v = max(math.dist(vc.punto_espiral(plan, i / 2000.0), vc.punto_espiral(plan, (i + 1) / 2000.0)) / dt
                for i in range(2000))
        assert v <= 0.30

    def test_si_el_dron_se_retrasa_el_punto_le_espera(self):
        plan = self._plan()
        assert vc.avance_espiral(plan, 0.3, 0.05, retraso_m=0.40) == 0.3
        assert vc.avance_espiral(plan, 0.3, 0.05, retraso_m=0.05) > 0.3

    def test_en_formacion_el_radio_casi_no_cambia_y_no_pasa_por_el_eje(self):
        import math
        plan = vc.plan_espiral((0.5, 0.0, 0.9), 0.0, 0.30, centro=(0.0, 0.0), radio_m=0.55, vueltas=1.5)
        radios = [math.hypot(*vc.punto_espiral(plan, i / 100.0)[:2]) for i in range(201)]
        assert min(radios) >= 0.49 and max(radios) <= 0.56

    def test_vuelo_simulado_completo(self, monkeypatch):
        """El dron simulado obedece la velocidad que se le manda: la pirueta baja a
        0.35 m abriendo la espiral, vuelve al eje y acaba arriba, donde empezo."""
        import math
        f = VueloRobotat(_opc(), dry_run=True, log=lambda _m: None, key="drone2")
        f.connect()
        f.request_takeoff()
        reloj = [1e6]
        monkeypatch.setattr(dr, "ahora", lambda: reloj[0])
        monkeypatch.setattr(vc, "ahora", lambda: reloj[0])
        x0, y0, _ = f.dron.estado().ekf
        origen_z = float(f.dron.estado().origen[2])
        f.dron._pose = (x0, y0, origen_z + 0.85)
        z_min, r_max, terminada = 9.9, 0.0, False
        for _ in range(3000):                           # hasta 150 s simulados
            n_antes = len(f.dron.ordenes)
            terminada = f.pirueta()
            if terminada:
                break
            if len(f.dron.ordenes) > n_antes:
                vel = f.dron.ordenes[-1][1]
                p = f.dron._pose
                f.dron._pose = (p[0] + vel[0] * 0.05, p[1] + vel[1] * 0.05, p[2] + vel[2] * 0.05)
            reloj[0] += 0.05
            p = f.dron._pose
            z_min = min(z_min, p[2])
            r_max = max(r_max, math.hypot(p[0] - x0, p[1] - y0))
        assert terminada
        assert z_min == pytest.approx(origen_z + vc.ESPIRAL_Z_BAJA_M, abs=0.06)
        assert r_max == pytest.approx(vc.ESPIRAL_RADIO_M, abs=0.08)
        p = f.dron._pose
        assert math.hypot(p[0] - x0, p[1] - y0) < 0.12
        assert p[2] == pytest.approx(origen_z + 0.85, abs=0.10)
