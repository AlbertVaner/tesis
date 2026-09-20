"""Reglas de vuelo del dron sobre el Robotat, sin radio ni broker."""

from __future__ import annotations

import math
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # controllers/shared

import dron_robotat as dr  # noqa: E402
from dron_robotat import (  # noqa: E402
    DronError, DronRobotat, DronSimulado, Estado, Opciones,
    anticipate, fence_velocity, goto_duration_s, plan_hold_segment, ramp_velocity,
    stable_origin, validate_step, validate_target, watchdog_reason, world_to_body, wrap_deg,
)
from mocap_feed import Frame  # noqa: E402


def opciones(**kw) -> Opciones:
    base = dict(uri="radio://sim/84/2M/E7E7E7E7E4", topic="mocap/drone3", nombre="Dron T")
    return Opciones(**(base | kw))


def frame(x, y, z, t=0.0, quat=None):
    return Frame(x, y, z, quat, None, t, None)


# -- Funciones puras -----------------------------------------------------------

class TestPaso:
    def test_paso_valido(self):
        m = validate_step(0.1, -0.05, 0.0, 20.0)
        assert (m.dx, m.dy, m.dz, m.dyaw) == (0.1, -0.05, 0.0, 20.0)

    @pytest.mark.parametrize("kw", [
        dict(dx=0.11), dict(dy=-0.2), dict(dz=0.101), dict(dyaw=21.0),
    ])
    def test_excede_limites(self, kw):
        args = dict(dx=0.0, dy=0.0, dz=0.0, dyaw=0.0) | kw
        with pytest.raises(DronError):
            validate_step(**args)

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), "x", None, True])
    def test_no_numerico(self, bad):
        with pytest.raises(DronError):
            validate_step(bad, 0, 0)

    def test_paso_nulo(self):
        with pytest.raises(DronError):
            validate_step(0, 0, 0, 0)

    def test_solo_giro_es_valido(self):
        assert validate_step(0, 0, 0, -20).dyaw == -20


class TestObjetivo:
    origen = (1.0, -1.0, 0.03)

    def test_dentro(self):
        validate_target((1.3, -0.7, 0.5), self.origen)

    def test_fuera_de_radio(self):
        with pytest.raises(DronError, match="del origen"):
            validate_target((1.5, -0.6, 0.5), self.origen)

    @pytest.mark.parametrize("z", [0.19, 1.11])
    def test_fuera_de_altura(self, z):
        with pytest.raises(DronError, match="altura"):
            validate_target((1.0, -1.0, z), self.origen)

    def test_radio_configurable(self):
        validate_target((1.8, -1.0, 0.5), self.origen, max_radius_m=1.0)


class TestDuracionYAnticipo:
    def test_duracion_minima(self):
        assert goto_duration_s(0.0) == 1.0
        assert goto_duration_s(0.05) == 1.0

    def test_velocidad_configurable(self):
        assert goto_duration_s(0.1, 0.0, 0.25) == 1.0
        assert goto_duration_s(0.5, 0.0, 0.25) == pytest.approx(2.0)

    def test_esperar_libre(self, monkeypatch):
        d = DronSimulado(opciones(), log=lambda _m: None)
        d.preflight()
        d.takeoff()
        assert not d.esperar_libre(timeout_s=0.1)
        monkeypatch.setattr(dr, "ahora", lambda: 1e9)
        assert d.esperar_libre(timeout_s=0.1)

    def test_duracion_proporcional(self):
        assert goto_duration_s(0.3) == pytest.approx(3.0)
        assert goto_duration_s(0.0, 40.0) == pytest.approx(2.0)
        assert goto_duration_s(0.3, 40.0) == pytest.approx(3.0)

    def test_anticipo(self):
        f = frame(1.0, 2.0, 3.0)
        assert anticipate(f, (1.0, 0.0, -1.0), 0.1) == pytest.approx((1.1, 2.0, 2.9))
        assert anticipate(f, (1.0, 0.0, -1.0), 0.0) == (1.0, 2.0, 3.0)
        assert anticipate(f, None, 0.1) == (1.0, 2.0, 3.0)

    def test_wrap(self):
        assert wrap_deg(190.0) == -170.0
        assert wrap_deg(-180.0) == -180.0
        assert wrap_deg(180.0) == -180.0


class TestOrigenEstable:
    def test_pocos_frames(self):
        assert stable_origin([frame(0, 0, 0)] * 5) is None

    def test_marker_en_movimiento(self):
        frames = [frame(0.01 * k, 0, 0) for k in range(20)]
        assert stable_origin(frames) is None

    def test_promedio(self):
        frames = [frame(1.0 + 0.001 * (k % 2), 2.0, 0.03) for k in range(20)]
        origin = stable_origin(frames)
        assert origin == pytest.approx((1.0005, 2.0, 0.03))


class TestWatchdog:
    def base(self, **kw):
        return Estado(**(dict(mocap_edad_s=0.05, error_ekf_mocap_m=0.02, bateria_v=3.5) | kw))

    def test_sano(self):
        assert watchdog_reason(self.base()) is None

    def test_telemetria_congelada_aterriza_y_no_corta(self):
        # Vuelo del 2026-09-18 a las 17:51: la telemetria del Dron 2 se congelo 7.8 s
        # con el dron volando bien. El error contra un EKF de hace 8 s llego a 0.152 m
        # y la vigilancia corto motores a 0.87 m de altura.
        accion, razon = watchdog_reason(self.base(ekf_edad_s=7.8, error_ekf_mocap_m=0.152))
        assert accion == "aterrizar" and "telemetria" in razon

    def test_con_telemetria_fresca_el_ekf_lejos_sigue_cortando(self):
        accion, _ = watchdog_reason(self.base(ekf_edad_s=0.05, error_ekf_mocap_m=0.2))
        assert accion == "cortar"

    def test_sin_telemetria_todavia_no_se_inventa_nada(self):
        assert watchdog_reason(self.base(ekf_edad_s=None)) is None

    def test_mocap_viejo_aterriza(self):
        assert watchdog_reason(self.base(mocap_edad_s=1.0))[0] == "aterrizar"
        assert watchdog_reason(self.base(mocap_edad_s=None))[0] == "aterrizar"

    def test_ekf_lejos_corta(self):
        accion, razon = watchdog_reason(self.base(error_ekf_mocap_m=0.2))
        assert accion == "cortar" and "EKF" in razon

    def test_bateria_baja_aterriza_y_critica_corta(self):
        accion, razon = watchdog_reason(self.base(bateria_v=2.95))
        assert accion == "aterrizar" and "bateria" in razon
        accion, razon = watchdog_reason(self.base(bateria_v=2.6))
        assert accion == "cortar" and "bateria" in razon
        assert watchdog_reason(self.base(bateria_v=None)) is None
        assert watchdog_reason(self.base(bateria_v=3.05)) is None


class TestTramoContinuo:
    def test_avanza_velocidad_por_periodo(self):
        target, yaw, dur = plan_hold_segment((1.0, 2.0, 0.5), 10.0, (1, 0, 0), 0, 0.25)
        assert target == pytest.approx((1.0 + 0.25 * dr.HOLD_PERIOD_S, 2.0, 0.5))
        assert yaw == 10.0 and dur == dr.HOLD_LOOKAHEAD_S

    def test_diagonal_no_es_mas_rapida(self):
        target, _, _ = plan_hold_segment((0, 0, 0.5), 0.0, (1, 1, 0), 0, 0.25)
        assert math.hypot(target[0], target[1]) == pytest.approx(0.25 * dr.HOLD_PERIOD_S)

    def test_giro(self):
        _, yaw, _ = plan_hold_segment((0, 0, 0.5), 179.0, (0, 0, 0), 1, 0.25)
        assert yaw == pytest.approx(wrap_deg(179.0 + dr.HOLD_YAW_SPEED_DPS * dr.HOLD_PERIOD_S))

    def test_nulo(self):
        with pytest.raises(DronError):
            plan_hold_segment((0, 0, 0.5), 0.0, (0, 0, 0), 0, 0.25)

    def test_simulado_encadena_sin_esperar(self, monkeypatch):
        d = DronSimulado(opciones(velocidad_mps=0.25), log=lambda _m: None)
        d.preflight()
        d.takeoff()
        with pytest.raises(DronError, match="despegue"):
            d.avanzar(1, 0, 0)
        monkeypatch.setattr(dr, "ahora", lambda: 1e9)
        d.avanzar(1, 0, 0)
        d.avanzar(1, 0, 0)  # solapa sin error
        assert d.estado().objetivo[0] == pytest.approx(2 * 0.25 * dr.HOLD_PERIOD_S)
        assert [o[0] for o in d.ordenes] == ["takeoff", "tramo", "tramo"]

    def test_hardware_manda_go_to_corto_y_respeta_geocerca(self, monkeypatch):
        d, cf = dron_hw(monkeypatch, velocidad_mps=0.25, radio_max_m=0.11)
        alimentar(d)
        d.takeoff()
        reloj = [1e9]
        monkeypatch.setattr(dr, "ahora", lambda: reloj[0])
        d.avanzar(1, 0, 0)
        args, kwargs = cf.high_level_commander.go_to.call_args
        assert args[0] == pytest.approx(0.25 * dr.HOLD_PERIOD_S) and args[4] == dr.HOLD_LOOKAHEAD_S
        reloj[0] += 0.2
        d.avanzar(1, 0, 0)
        reloj[0] += 0.2
        with pytest.raises(DronError, match="origen"):
            d.avanzar(1, 0, 0)
        assert cf.high_level_commander.go_to.call_count == 2

    def test_hardware_descarta_tramos_demasiado_juntos(self, monkeypatch):
        d, cf = dron_hw(monkeypatch, velocidad_mps=0.25)
        alimentar(d)
        d.takeoff()
        monkeypatch.setattr(dr, "ahora", lambda: 1e9)
        d.avanzar(1, 0, 0)
        d.avanzar(1, 0, 0)  # mismo instante: descartado
        assert cf.high_level_commander.go_to.call_count == 1

    def test_bateria_baja_solo_si_se_mantiene(self, monkeypatch):
        """Un pico de 2.99 V de una muestra no aterriza; medio segundo si."""
        d, cf = dron_hw(monkeypatch)
        alimentar(d)
        d.takeoff()
        reloj = [1e9]
        monkeypatch.setattr(dr, "ahora", lambda: reloj[0])
        monkeypatch.setattr(dr.threading, "Timer", lambda *a, **k: MagicMock())
        aterrizajes = []
        monkeypatch.setattr(d, "_aterrizar_sin_mocap", lambda razon: aterrizajes.append(razon))
        waits = iter([False] * 9 + [True])
        monkeypatch.setattr(d._stop, "wait", lambda _t: next(waits))
        monkeypatch.setattr(d, "_fila", lambda *a, **k: {})  # el CSV no consume el reloj

        contador = iter(range(1, 1000))

        def alimentar_ahora(vbat):
            # posicion con ruido: una pose identica 0.5 s contaria como congelada
            alimentar(d, x=0.0005 * next(contador), t=reloj[0])
            d._vbat = vbat

        # 2.99 aislado; despues 2.98-2.96 sostenidos: a la sexta muestra (0.5 s) aterriza
        secuencia = iter([2.99, 3.02, 3.02, 2.98, 2.97, 2.96, 2.96, 2.96, 2.96])
        original_estado = d.estado

        def estado():
            try:
                alimentar_ahora(next(secuencia))
            except StopIteration:
                pass
            reloj[0] += 0.1
            return original_estado()

        monkeypatch.setattr(d, "estado", estado)
        d._monitor_loop()
        assert aterrizajes == ["bateria 2.96 V en vuelo"]

    def test_sin_mocap_aterriza_en_vez_de_cortar(self, monkeypatch):
        d, cf = dron_hw(monkeypatch)
        alimentar(d)
        d.takeoff()
        monkeypatch.setattr(dr, "ahora", lambda: 1e9)  # mocap viejo
        monkeypatch.setattr(dr.threading, "Timer", lambda *a, **k: MagicMock())
        d._aterrizar_sin_mocap("prueba")
        cf.high_level_commander.land.assert_called_once()
        assert d.estado().modo == "ATERRIZAJE_SIN_MOCAP" and not d.estado().emergencia


# -- Simulado ------------------------------------------------------------------

class TestSimulado:
    def dron(self, **kw):
        return DronSimulado(opciones(**kw), log=lambda _m: None)

    def test_flujo_completo(self, monkeypatch):
        d = self.dron()
        with pytest.raises(DronError, match="PREFLIGHT"):
            d.takeoff()
        d.preflight()
        assert d.estado().listo
        with pytest.raises(DronError, match="despega"):
            d.move(0.1, 0, 0)
        d.takeoff()
        e = d.estado()
        assert e.en_vuelo and e.objetivo[2] == pytest.approx(0.40)
        with pytest.raises(DronError, match="en curso"):
            d.move(0.1, 0, 0)
        monkeypatch.setattr(dr, "ahora", lambda: 1e9)
        d.move(0.1, 0, 0, 20)
        e = d.estado()
        assert e.objetivo[0] == pytest.approx(0.1) and e.objetivo_yaw_deg == 20
        d.land()
        assert not d.estado().en_vuelo
        assert [o[0] for o in d.ordenes] == ["takeoff", "go_to", "land"]

    def test_geocerca(self, monkeypatch):
        d = self.dron(radio_max_m=0.15)
        d.preflight()
        d.takeoff()
        reloj = [1e9]
        monkeypatch.setattr(dr, "ahora", lambda: reloj[0])
        d.move(0.1, 0, 0)
        reloj[0] += 10.0
        with pytest.raises(DronError, match="origen"):
            d.move(0.1, 0, 0)

    def test_emergencia_enclava(self):
        d = self.dron()
        d.preflight()
        d.takeoff()
        d.emergency("prueba")
        e = d.estado()
        assert e.emergencia and not e.en_vuelo and not e.listo
        with pytest.raises(DronError, match="emergencia"):
            d.preflight()


# -- Hardware con cflib simulado -----------------------------------------------

class FakeCf:
    def __init__(self):
        self.extpos = MagicMock()
        self.high_level_commander = MagicMock()
        self.commander = MagicMock()
        self.param = MagicMock()


def dron_hw(monkeypatch, **kw) -> tuple[DronRobotat, FakeCf]:
    d = DronRobotat(opciones(**kw), log=lambda _m: None)
    cf = FakeCf()
    d._cf = cf
    d._estado.listo = True
    d._estado.origen = (0.0, 0.0, 0.03)
    d._estado.objetivo = (0.0, 0.0, 0.03)
    d._vbat = 3.9
    monkeypatch.setattr(dr, "stop_motors", lambda *a, **k: None)
    return d, cf


def alimentar(d: DronRobotat, x=0.0, y=0.0, z=0.03, t=None):
    """Mete un frame de mocap y una estimacion EKF coincidentes."""
    t = dr.ahora() if t is None else t
    d.feed.push(Frame(x, y, z, None, None, t, None))
    d._on_ekf(0, {"stateEstimate.x": x, "stateEstimate.y": y, "stateEstimate.z": z,
                  "stateEstimate.yaw": 95.0, "controller.cmd_thrust": 41000.0}, None)
    d._on_attitude(0, {"stabilizer.roll": 0.0, "stabilizer.pitch": 0.0, "pm.vbat": 3.9,
                       "stateEstimate.vx": 0.0, "stateEstimate.vy": 0.0, "stateEstimate.vz": -0.12}, None)


class TestHardware:
    def test_extpos_por_frame_distinto(self, monkeypatch):
        d, cf = dron_hw(monkeypatch)
        d.feed.push(frame(0.0, 0.0, 0.0, 0.00))
        d.feed.push(frame(0.0, 0.0, 0.0, 0.001))  # duplicado del puente
        d.feed.push(frame(0.0, 0.0, 0.1, 0.05))
        assert cf.extpos.send_extpos.call_count == 2
        assert d.estado().extpos_enviados == 2
        cf.extpos.send_extpose.assert_not_called()

    def test_extpose_solo_con_bandera_y_rotacion(self, monkeypatch):
        d, cf = dron_hw(monkeypatch, extpose=True)
        d.feed.push(frame(0.0, 0.0, 0.0, 0.0, quat=(0, 0, 0, 1)))
        cf.extpos.send_extpose.assert_called_once_with(0.0, 0.0, 0.0, 0, 0, 0, 1)
        d.feed.push(frame(0.0, 0.0, 0.1, 0.05))  # sin rotacion: cae a extpos
        cf.extpos.send_extpos.assert_called_once_with(0.0, 0.0, 0.1)

    def test_anticipo_extrapola(self, monkeypatch):
        d, cf = dron_hw(monkeypatch, anticipo_s=0.1)
        d.feed.push(frame(0.0, 0.0, 0.0, 0.00))
        d.feed.push(frame(0.05, 0.0, 0.0, 0.05))  # 1 m/s en x
        x, y, z = cf.extpos.send_extpos.call_args.args
        assert x == pytest.approx(0.15) and y == 0.0 and z == 0.0

    def test_takeoff_manda_altura_absoluta_y_yaw_del_ekf(self, monkeypatch):
        d, cf = dron_hw(monkeypatch)
        alimentar(d, 1.0, 2.0, 0.03)
        d.takeoff()
        cf.high_level_commander.takeoff.assert_called_once_with(pytest.approx(0.38), dr.TAKEOFF_DURATION_S)
        e = d.estado()
        assert e.en_vuelo and e.objetivo == pytest.approx((1.0, 2.0, 0.38))
        assert e.objetivo_yaw_deg == pytest.approx(95.0)

    def test_takeoff_rechaza_bateria_baja(self, monkeypatch):
        d, cf = dron_hw(monkeypatch)
        alimentar(d)
        d._vbat = 3.5
        with pytest.raises(DronError, match="bateria"):
            d.takeoff()
        cf.high_level_commander.takeoff.assert_not_called()

    def test_takeoff_rechaza_mocap_viejo(self, monkeypatch):
        d, cf = dron_hw(monkeypatch)
        alimentar(d, t=dr.ahora() - 5.0)
        with pytest.raises(DronError, match="fresco"):
            d.takeoff()

    def test_move_no_solapa_y_manda_yaw_absoluto(self, monkeypatch):
        d, cf = dron_hw(monkeypatch)
        alimentar(d)
        d.takeoff()
        with pytest.raises(DronError, match="en curso"):
            d.move(0.1, 0, 0)
        cf.high_level_commander.go_to.assert_not_called()
        monkeypatch.setattr(dr, "ahora", lambda: 1e9)
        d.move(0.1, 0.0, 0.0, -20.0)
        args, kwargs = cf.high_level_commander.go_to.call_args
        assert args[:3] == pytest.approx((0.1, 0.0, 0.38))
        assert args[3] == pytest.approx(math.radians(75.0))
        assert args[4] == pytest.approx(1.0)
        assert kwargs == {"relative": False}
        with pytest.raises(DronError, match="en curso"):
            d.move(0.1, 0, 0)

    def test_fallo_de_radio_en_go_to_corta_motores(self, monkeypatch):
        d, cf = dron_hw(monkeypatch)
        alimentar(d)
        d.takeoff()
        monkeypatch.setattr(dr, "ahora", lambda: 1e9)
        cf.high_level_commander.go_to.side_effect = OSError("radio")
        with pytest.raises(DronError, match="go_to"):
            d.move(0.1, 0, 0)
        assert d.estado().emergencia
        cf.high_level_commander.stop.assert_called()

    def test_land_y_landed_apagan_motores(self, monkeypatch):
        d, cf = dron_hw(monkeypatch)
        alimentar(d)
        d.takeoff()
        timers = []
        monkeypatch.setattr(dr.threading, "Timer", lambda s, fn, **k: timers.append((s, fn)) or MagicMock())
        d.land()
        cf.high_level_commander.land.assert_called_once_with(dr.LAND_HEIGHT_M, dr.LAND_DURATION_S)
        assert d.estado().en_vuelo
        timers[0][1]()
        assert not d.estado().en_vuelo
        cf.high_level_commander.stop.assert_called_once()

    def test_emergencia_es_idempotente(self, monkeypatch):
        d, cf = dron_hw(monkeypatch)
        d.emergency("uno")
        d.emergency("dos")
        assert d.estado().razon_emergencia == "uno"
        cf.high_level_commander.stop.assert_called_once()
        with pytest.raises(DronError, match="emergencia"):
            d.takeoff()

    def test_parametros_con_error_no_frenan_al_resto(self, monkeypatch):
        d, cf = dron_hw(monkeypatch, parametros={"malo.x": "1", "posCtlPid.xKp": "1.0"}, ext_pos_std_m=0.03)
        monkeypatch.setattr(dr, "configure_estimator", lambda *a, **k: None)
        fake_log = MagicMock()
        monkeypatch.setitem(sys.modules, "cflib", MagicMock())
        monkeypatch.setitem(sys.modules, "cflib.crazyflie", MagicMock())
        monkeypatch.setitem(sys.modules, "cflib.crazyflie.log", MagicMock(LogConfig=fake_log))
        cf.log = MagicMock()

        def set_value(name, value):
            if name == "malo.x":
                raise KeyError(name)
        cf.param.set_value.side_effect = set_value
        d._configure_firmware()
        assert d.estado().parametros == {"locSrv.extPosStdDev": "0.0300", "posCtlPid.xKp": "1.0"}
        assert fake_log.return_value.start.call_count == 2
        # ningun bloque supera los 26 bytes del firmware (floats de 4 bytes)
        for call in fake_log.call_args_list:
            assert call.kwargs["name"] in ("PosRobotat", "ActRobotat")
        assert fake_log.return_value.add_variable.call_count == 11

    def test_fila_csv_tiene_todas_las_columnas(self, monkeypatch):
        d, _ = dron_hw(monkeypatch)
        alimentar(d)
        fila = d._fila("PRUEBA", "x")
        assert set(fila) == set(dr.CSV_COLUMNS)
        assert fila["mocap_x"] == 0.0 and fila["ekf_yaw_deg"] == 95.0
        assert fila["ekf_vz"] == -0.12 and fila["mocap_vz"] == ""  # un solo frame: sin velocidad mocap
        assert fila["empuje_cmd"] == 41000


class TestFluido:
    def test_rampa(self):
        assert ramp_velocity(0.0, 0.25, 0.05, accel=0.6) == pytest.approx(0.03)
        assert ramp_velocity(0.24, 0.25, 0.05, accel=0.6) == 0.25
        assert ramp_velocity(0.25, 0.0, 0.05, accel=0.6) == pytest.approx(0.22)

    def test_geocerca_anula_hacia_fuera(self):
        origen = (0.0, 0.0, 0.03)
        # a 0.45 m del origen yendo hacia fuera a 0.25 m/s: en 0.6 s saldría 0.10 m:
        # se anula la salida y se empuja 0.15 m/s hacia dentro
        assert fence_velocity((0.45, 0.0, 0.5), (0.25, 0.0, 0.0), origen)[:2] == pytest.approx((-0.15, 0.0))
        # misma posición volviendo hacia el origen: se permite
        assert fence_velocity((0.45, 0.0, 0.5), (-0.25, 0.0, 0.0), origen)[0] == -0.25
        # techo y suelo: se anula la salida y se empuja de vuelta
        assert fence_velocity((0.0, 0.0, 1.05), (0.0, 0.0, 0.25), origen)[2] < 0.0
        assert fence_velocity((0.0, 0.0, 0.25), (0.0, 0.0, -0.25), origen)[2] > 0.0
        assert fence_velocity((0.0, 0.0, 0.5), (0.0, 0.0, -0.25), origen)[2] == -0.25

    def test_geocerca_deja_resbalar_por_el_borde(self):
        """Fuera del círculo por inercia, una tecla tangencial sigue moviendo."""
        origen = (0.0, 0.0, 0.03)
        # en el borde, velocidad tangencial: pasa casi entera (la prevision
        # en 0.6 s queda un poco fuera y se quita esa pizca radial)
        vx, vy, _ = fence_velocity((0.5, 0.0, 0.5), (0.0, 0.25, 0.0), origen)
        assert vy > 0.2 and vx <= 0.0
        # fuera (0.55, 0.20) con velocidad mixta: queda la parte tangencial, sin componente radial
        vx, vy, _ = fence_velocity((0.55, 0.20, 0.5), (0.10, 0.25, 0.0), origen)
        px, py = 0.55 + 0.10 * 0.6, 0.20 + 0.25 * 0.6
        radial = (vx * px + vy * py) / math.hypot(px, py)
        assert radial < 0.0  # ahora empuja hacia dentro
        assert math.hypot(vx, vy) > 0.15
        # fuera y volviendo: sin cambios
        assert fence_velocity((0.6, 0.0, 0.5), (-0.25, 0.0, 0.0), origen)[:2] == pytest.approx((-0.25, 0.0))

    def test_simulado_velocidad_y_freno(self, monkeypatch):
        d = DronSimulado(opciones(velocidad_mps=0.25), log=lambda _m: None)
        d.preflight()
        d.takeoff()
        with pytest.raises(DronError, match="despegue"):
            d.fijar_velocidad(1, 0, 0)
        monkeypatch.setattr(dr, "ahora", lambda: 1e9)
        d.fijar_velocidad(1, 0, 0)
        assert d.estado().modo == "FLUIDO"
        assert d.estado().objetivo[0] == pytest.approx(0.25 * dr.FLUID_LOOKAHEAD_S)
        d.fijar_velocidad(0, 0, 0)
        assert d.estado().modo == "VUELO"

    def test_mundo_a_cuerpo(self):
        assert world_to_body(0.25, 0.0, 0.0) == pytest.approx((0.25, 0.0))
        assert world_to_body(0.25, 0.0, 90.0) == pytest.approx((0.0, -0.25))
        assert world_to_body(0.0, 0.25, 90.0) == pytest.approx((0.25, 0.0))

    def test_hardware_envia_hover_con_rampa_y_entrega(self, monkeypatch):
        d, cf = dron_hw(monkeypatch, velocidad_mps=0.25)
        alimentar(d, z=0.5)
        d.takeoff()
        monkeypatch.setattr(dr, "ahora", lambda: 1e9)
        monkeypatch.setattr(dr.threading, "Thread", lambda *a, **k: MagicMock())  # sin hilo real
        d.fijar_velocidad(1, 0, 0)
        assert d.estado().modo == "FLUIDO"
        assert d._fluido_tick(0.05)
        vbx, vby, yawrate, z = cf.commander.send_hover_setpoint.call_args.args
        # el EKF dice yaw 95°: +X del mundo es casi -Y del cuerpo
        assert math.hypot(vbx, vby) == pytest.approx(0.03) and vby < 0
        assert yawrate == 0.0 and z == pytest.approx(0.5)  # altura absoluta, sin deriva
        for _ in range(20):
            d._fluido_tick(0.05)
        vbx, vby, _, z = cf.commander.send_hover_setpoint.call_args.args
        assert math.hypot(vbx, vby) == pytest.approx(0.25) and z == pytest.approx(0.5)
        cf.commander.send_velocity_world_setpoint.assert_not_called()
        # soltar: rampa a cero y entrega al high-level con go_to a la estimación
        d.fijar_velocidad(0, 0, 0)
        while d._fluido_tick(0.05):
            pass
        cf.commander.send_notify_setpoint_stop.assert_called_once()
        args, _ = cf.high_level_commander.go_to.call_args
        assert args[:3] == pytest.approx((0.0, 0.0, 0.5))
        assert args[4] == dr.FLUID_HOLD_DURATION_S
        assert d.estado().modo == "VUELO" and not d.estado().emergencia

    def test_subir_integra_la_altura_y_gira_a_la_izquierda(self, monkeypatch):
        d, cf = dron_hw(monkeypatch, velocidad_mps=0.25)
        alimentar(d, z=0.5)
        d.takeoff()
        monkeypatch.setattr(dr, "ahora", lambda: 1e9)
        monkeypatch.setattr(dr.threading, "Thread", lambda *a, **k: MagicMock())
        d.fijar_velocidad(0, 0, 1, 1)  # subir y girar a la izquierda
        for _ in range(40):
            d._fluido_tick(0.05)
        vbx, vby, yawrate, z = cf.commander.send_hover_setpoint.call_args.args
        assert (vbx, vby) == (0.0, 0.0)
        assert yawrate == pytest.approx(dr.FLUID_YAW_RATE_DPS)  # +1 antihorario, como turn_left
        assert 0.5 < z <= 0.5 + dr.FLUID_Z_LEASH_M  # la correa frena la integracion
        # techo: la altura integrada se queda un margen por debajo del maximo
        alimentar(d, z=0.85)
        for _ in range(200):
            d._fluido_tick(0.05)
        assert cf.commander.send_hover_setpoint.call_args.args[3] == pytest.approx(
            dr.MAX_TARGET_Z_M - dr.FLUID_Z_CEILING_MARGIN_M)

    def test_hardware_geocerca_en_vuelo(self, monkeypatch):
        d, cf = dron_hw(monkeypatch, velocidad_mps=0.25, radio_max_m=0.2)
        alimentar(d, x=0.19, y=0.0, z=0.5)
        d.takeoff()
        monkeypatch.setattr(dr, "ahora", lambda: 1e9)
        monkeypatch.setattr(dr.threading, "Thread", lambda *a, **k: MagicMock())
        d.fijar_velocidad(1, 0, 0)
        d._fluido_tick(0.05)
        vbx, vby, _, _ = cf.commander.send_hover_setpoint.call_args.args
        # la salida se anula; solo queda un empuje pequeno hacia dentro
        assert math.hypot(vbx, vby) < 0.05

    def test_land_detiene_el_fluido(self, monkeypatch):
        d, cf = dron_hw(monkeypatch, velocidad_mps=0.25)
        alimentar(d)
        d.takeoff()
        monkeypatch.setattr(dr, "ahora", lambda: 1e9)
        monkeypatch.setattr(dr.threading, "Thread", lambda *a, **k: MagicMock())
        monkeypatch.setattr(dr.threading, "Timer", lambda *a, **k: MagicMock())
        d.fijar_velocidad(1, 0, 0)
        d.land()
        cf.commander.send_notify_setpoint_stop.assert_called()
        cf.high_level_commander.land.assert_called_once()
        assert not d._fluido_activo


def test_resumen_empuje_recomienda_thrust_base(monkeypatch, tmp_path):
    d, cf = dron_hw(monkeypatch)
    monkeypatch.setattr(dr, "THRUST_MEMORY_PATH", tmp_path / "empuje.json")
    assert d.resumen_empuje() == ""
    d._empuje_hover = [45800.0] * 30
    texto = d.resumen_empuje()
    assert "45800" in texto and "thrustBase=45800" in texto


def test_despegue_pasa_a_vuelo_cuando_termina(monkeypatch):
    d, cf = dron_hw(monkeypatch)
    alimentar(d)
    d.takeoff()
    assert d.estado().modo == "DESPEGUE"
    monkeypatch.setattr(dr, "ahora", lambda: 1e9)
    monkeypatch.setattr(d, "_fila", lambda *a, **k: {})
    waits = iter([False, True])
    monkeypatch.setattr(d._stop, "wait", lambda _t: next(waits))
    d._monitor_loop()
    assert d.estado().modo == "VUELO"


def test_correa_no_arrastra_el_objetivo_si_el_dron_se_desvia(monkeypatch):
    """Con vz = 0 el objetivo se queda: el lazo de posición debe traer al dron."""
    d, cf = dron_hw(monkeypatch, velocidad_mps=0.25)
    alimentar(d, z=0.5)
    d.takeoff()
    monkeypatch.setattr(dr, "ahora", lambda: 1e9)
    monkeypatch.setattr(dr.threading, "Thread", lambda *a, **k: MagicMock())
    d.fijar_velocidad(1, 0, 0)  # movimiento horizontal, altura fija en 0.5
    d._fluido_tick(0.05)
    alimentar(d, z=0.9)  # el dron sube solo 0.4 m
    d._fluido_tick(0.05)
    assert cf.commander.send_hover_setpoint.call_args.args[3] == pytest.approx(0.5)
    alimentar(d, z=0.1)  # y baja solo
    d._fluido_tick(0.05)
    assert cf.commander.send_hover_setpoint.call_args.args[3] == pytest.approx(0.5)


def test_altura_fluida_con_correa(monkeypatch):
    """La altura mandada no se adelanta más de la correa a la estimada."""
    d, cf = dron_hw(monkeypatch, velocidad_mps=0.25)
    alimentar(d, z=0.5)
    d.takeoff()
    monkeypatch.setattr(dr, "ahora", lambda: 1e9)
    monkeypatch.setattr(dr.threading, "Thread", lambda *a, **k: MagicMock())
    d.fijar_velocidad(0, 0, 1)
    for _ in range(60):  # 3 s subiendo con el EKF clavado en 0.5
        d._fluido_tick(0.05)
    z = cf.commander.send_hover_setpoint.call_args.args[3]
    assert z == pytest.approx(0.5 + dr.FLUID_Z_LEASH_M)


def test_altura_fluida_no_baja_del_suelo_mas_margen(monkeypatch):
    d, cf = dron_hw(monkeypatch, velocidad_mps=0.25)
    alimentar(d, z=0.35)
    d.takeoff()
    monkeypatch.setattr(dr, "ahora", lambda: 1e9)
    monkeypatch.setattr(dr.threading, "Thread", lambda *a, **k: MagicMock())
    d.fijar_velocidad(0, 0, -1)
    for _ in range(200):
        d._fluido_tick(0.05)
    assert cf.commander.send_hover_setpoint.call_args.args[3] == pytest.approx(
        dr.MIN_TARGET_Z_M + dr.FLUID_Z_FLOOR_MARGIN_M)


class TestMemoriaEmpuje:
    def test_guardar_y_leer(self, tmp_path):
        path = tmp_path / "empuje.json"
        assert dr.leer_empuje_memoria("Dron 2", path) is None
        dr.guardar_empuje_memoria("Dron 2", 39500.0, path)
        assert dr.leer_empuje_memoria("Dron 2", path) == 39500.0
        assert dr.leer_empuje_memoria("Dron 1", path) is None
        dr.guardar_empuje_memoria("Dron 1", 46000.0, path)
        assert dr.leer_empuje_memoria("Dron 2", path) == 39500.0

    def test_valor_absurdo_se_ignora(self, tmp_path):
        path = tmp_path / "empuje.json"
        path.write_text('{"Dron 2": {"thrust_base": 5}}', encoding="utf-8")
        assert dr.leer_empuje_memoria("Dron 2", path) is None
        path.write_text("basura", encoding="utf-8")
        assert dr.leer_empuje_memoria("Dron 2", path) is None

    def _configurar(self, monkeypatch, tmp_path, **kw):
        d, cf = dron_hw(monkeypatch, **kw)
        monkeypatch.setattr(dr, "THRUST_MEMORY_PATH", tmp_path / "empuje.json")
        monkeypatch.setattr(dr, "configure_estimator", lambda *a, **k: None)
        monkeypatch.setitem(sys.modules, "cflib", MagicMock())
        monkeypatch.setitem(sys.modules, "cflib.crazyflie", MagicMock())
        monkeypatch.setitem(sys.modules, "cflib.crazyflie.log", MagicMock(LogConfig=MagicMock()))
        cf.log = MagicMock()
        return d, cf

    def test_memoria_sustituye_al_preajuste(self, monkeypatch, tmp_path):
        d, cf = self._configurar(monkeypatch, tmp_path, nombre="Dron 2",
                                 parametros={"posCtlPid.thrustBase": "46000"})
        dr.guardar_empuje_memoria("Dron 2", 39500.0, tmp_path / "empuje.json")
        d._configure_firmware()
        assert d.estado().parametros["posCtlPid.thrustBase"] == "39500"

    def test_param_explicito_manda(self, monkeypatch, tmp_path):
        d, cf = self._configurar(monkeypatch, tmp_path, nombre="Dron 2",
                                 parametros={"posCtlPid.thrustBase": "47000"}, thrust_base_explicito=True)
        dr.guardar_empuje_memoria("Dron 2", 39500.0, tmp_path / "empuje.json")
        d._configure_firmware()
        assert d.estado().parametros["posCtlPid.thrustBase"] == "47000"

    def test_sin_thrust_base_en_parametros_no_toca_nada(self, monkeypatch, tmp_path):
        d, cf = self._configurar(monkeypatch, tmp_path, nombre="Dron 2")
        dr.guardar_empuje_memoria("Dron 2", 39500.0, tmp_path / "empuje.json")
        d._configure_firmware()
        assert "posCtlPid.thrustBase" not in d.estado().parametros

    def test_resumen_guarda(self, monkeypatch, tmp_path):
        d, cf = dron_hw(monkeypatch, nombre="Dron 2")
        monkeypatch.setattr(dr, "THRUST_MEMORY_PATH", tmp_path / "empuje.json")
        d._empuje_hover = [39474.0] * 30
        d.resumen_empuje()
        assert dr.leer_empuje_memoria("Dron 2", tmp_path / "empuje.json") == 39500.0


class TestOrientacion:
    def test_extpose_rechaza_cuerpo_inclinado(self, monkeypatch):
        d, cf = dron_hw(monkeypatch, extpose=True)
        d.feed.push(Frame(0, 0, 0.03, (0.5, 0, 0, 0.866), 0.0, dr.ahora(), None, -60.0, 0.0))
        with pytest.raises(DronError, match="nivelado"):
            d._comprobar_orientacion()

    def test_extpose_acepta_cuerpo_plano(self, monkeypatch):
        d, cf = dron_hw(monkeypatch, extpose=True)
        d.feed.push(Frame(0, 0, 0.03, (0, 0, 0, 1), -2.0, dr.ahora(), None, 1.0, -0.5))
        d._comprobar_orientacion()

    def test_extpose_sin_rotacion(self, monkeypatch):
        d, cf = dron_hw(monkeypatch, extpose=True)
        d.feed.push(Frame(0, 0, 0.03, None, None, dr.ahora(), None))
        with pytest.raises(DronError, match="rotacion"):
            d._comprobar_orientacion()

    def test_sin_extpose_solo_registra(self, monkeypatch):
        d, cf = dron_hw(monkeypatch)
        d.feed.push(Frame(0, 0, 0.03, (0.5, 0, 0, 0.866), 0.0, dr.ahora(), None, -60.0, 0.0))
        d._comprobar_orientacion()


def test_pose_congelada_no_va_al_ekf_y_aterriza(monkeypatch):
    d, cf = dron_hw(monkeypatch)
    for k in range(25):
        d.feed.push(Frame(0.7, -0.2, 0.1, None, None, 0.04 * k, None))
    # las primeras copias si se enviaron; al congelarse deja de enviar
    enviados = cf.extpos.send_extpos.call_count
    d.feed.push(Frame(0.7, -0.2, 0.1, None, None, 1.04, None))
    assert cf.extpos.send_extpos.call_count == enviados
    monkeypatch.setattr(dr, "ahora", lambda: 1.05)
    e = d.estado()
    assert e.mocap_congelado
    assert watchdog_reason(Estado(mocap_edad_s=0.01, mocap_congelado=True, error_ekf_mocap_m=0.0, bateria_v=3.5)) == (
        "aterrizar", "pose del Robotat congelada (rastreo perdido)")
    with pytest.raises(DronError, match="fresco"):
        d.takeoff()


def test_ekf_lejos_a_ras_de_suelo_durante_aterrizaje_no_corta(monkeypatch):
    d, cf = dron_hw(monkeypatch)
    alimentar(d, z=0.05)
    d.takeoff()
    monkeypatch.setattr(dr, "ahora", lambda: 1e9)
    monkeypatch.setattr(dr.threading, "Timer", lambda *a, **k: MagicMock())
    d.land()
    monkeypatch.setattr(d, "_fila", lambda *a, **k: {})
    # EKF 0.2 m lejos, pero el dron esta a 2 cm del origen (0.03): no se corta
    d._on_ekf(0, {"stateEstimate.x": 0.2, "stateEstimate.y": 0.0, "stateEstimate.z": 0.05,
                  "stateEstimate.yaw": 0.0}, None)
    d.feed.push(Frame(0.0, 0.0, 0.05, None, None, 1e9, None))
    waits = iter([False, True])
    monkeypatch.setattr(d._stop, "wait", lambda _t: next(waits))
    d._monitor_loop()
    assert not d.estado().emergencia


def test_geocerca_centrada_en_el_robotat(monkeypatch):
    """Con centro fijo, el despegue lejos del centro no limita el vuelo al rededor del despegue."""
    d = DronSimulado(opciones(radio_max_m=1.0, centro_geocerca=(0.0, 0.0)), log=lambda _m: None)
    d._pose = (0.9, 0.0, 0.05)  # despega a 0.9 m del centro
    d.preflight()
    d.takeoff()
    monkeypatch.setattr(dr, "ahora", lambda: 1e9)
    d.fijar_velocidad(-1, 0, 0)  # hacia el centro: pasa
    assert d.ordenes[-1][1][0] < 0
    d._pose = (-0.95, 0.0, 0.4)
    d.fijar_velocidad(-1, 0, 0)  # hacia fuera del circulo de 1 m alrededor de (0,0): se anula y empuja de vuelta
    assert d.ordenes[-1][1][0] >= 0.0
    assert dr.centro_geocerca(d.opciones, (5.0, 5.0, 0.03)) == (0.0, 0.0, 0.03)
    assert dr.centro_geocerca(opciones(), (5.0, 5.0, 0.03)) == (5.0, 5.0, 0.03)


def test_geocerca_empuja_de_vuelta_cuando_ya_esta_fuera():
    origen = (0.0, 0.0, 0.03)
    # quieto a 0.8 m del origen con radio 0.5: 0.3 m fuera -> empuje 0.30 (tope)
    vx, vy, _ = fence_velocity((0.8, 0.0, 0.5), (0.0, 0.0, 0.0), origen)
    assert (vx, vy) == pytest.approx((-dr.FENCE_PUSH_MAX_MPS, 0.0))
    # un poco fuera: empuje proporcional
    vx, _, _ = fence_velocity((0.0, 0.0, 0.5), (0.0, 0.0, 0.0), origen, max_radius_m=0.0 + 1e-9)
    assert vx <= 0.0
    vx, vy, _ = fence_velocity((0.0, 0.56, 0.5), (0.0, 0.0, 0.0), origen)
    assert vy == pytest.approx(-dr.FENCE_PUSH_KP * 0.06)
