"""El vocabulario completo sobre un backend falso. Sin camara, sin radio.

Recorre la secuencia que el dron real tiene que soportar con
`--reconocedor vocabulario`: en el suelo solo el senalero despega, ven_aca
sigue al marker, el aplauso cambia de modo y deja hover, los estaticos solo
mueven en modo estatico y en el aire, arco y circulo todavia no vuelan, y la
X sobre la cabeza aterriza, bloquea y, sostenida, corta motores.

Las observaciones de vision (deteccion dinamica, evento estatico, pose para
el paro) se inyectan directamente; MediaPipe no participa.

Uso, desde la raiz del repositorio:

    .\\.venv\\Scripts\\python.exe -m pytest -q .\\controllers\\single_drone\\camera\\tests\\test_control_vocabulario.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

TESTS_DIR = Path(__file__).resolve().parent
CAMERA_DIR = TESTS_DIR.parent
if str(CAMERA_DIR) not in sys.path:
    sys.path.insert(0, str(CAMERA_DIR))

import control_camara_dron1 as ctrl  # noqa: E402
from contracts import Gesture, GestureEvent, VelocityIntent  # noqa: E402
from pose.normalize import (  # noqa: E402
    LEFT_ELBOW,
    LEFT_SHOULDER,
    LEFT_WRIST,
    N_LANDMARKS,
    RIGHT_ELBOW,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
)
from recognition.dinamicos import BancoDinamico, Deteccion  # noqa: E402
from recognition.paro_estatico import NOSE  # noqa: E402
from recognition.vocabulario import DINAMICO, ESTATICO, HOVER  # noqa: E402

SPEED = (0.18, 0.10)


class FakeFlight:
    """Doble del backend: registra ordenes y lleva `flying` como lo haria el real."""

    def __init__(self) -> None:
        self.flying = False
        self.busy = False
        self.height_m = None
        self.llamadas: list[str] = []
        self.velocidades: list[tuple[float, float, float]] = []

    def request_takeoff(self) -> bool:
        self.llamadas.append("takeoff")
        self.flying = True
        return True

    def request_land(self, razon: str = "") -> bool:
        self.llamadas.append(f"land:{razon}")
        self.flying = False
        return True

    def set_velocity(self, vx, vy, vz) -> None:
        self.llamadas.append("set_velocity")
        self.velocidades.append((vx, vy, vz))

    def hover(self) -> None:
        self.llamadas.append("hover")

    def emergency_stop(self) -> None:
        self.llamadas.append("emergency")


class FakeFollow:
    """Receptor del marker 65: activa, desactiva y da una velocidad fija."""

    def __init__(self) -> None:
        self.activos: set[str] = set()

    def active(self, key) -> bool:
        return key in self.activos

    def activate(self, keys) -> None:
        self.activos.update(keys)

    def deactivate(self, keys) -> None:
        self.activos.difference_update(keys)

    def world_velocity(self, _key):
        return (0.05, 0.0, 0.0)

    def body_velocity(self, _key):
        return (0.05, 0.0, 0.0)


def deteccion(gesto: str, t: float) -> Deteccion:
    return Deteccion(gesto, 0.30, 0.10, t - 2.0, t)


def evento(gesto: Gesture, confirmado: bool = True) -> GestureEvent:
    return GestureEvent(
        gesture=gesto, confidence=1.0, confirmed=confirmado, engaged=True,
        velocity=ctrl.VELOCIDADES.get(gesto, VelocityIntent()) if confirmado else VelocityIntent(),
        timestamp=0.0,
    )


def pose_x_sobre_la_cabeza() -> np.ndarray:
    """Munecas por encima de la nariz, cruzadas y juntas. Unidades de torso."""
    pose = np.zeros((N_LANDMARKS, 3))
    pose[NOSE] = (0.0, 1.30, 0.0)
    pose[RIGHT_SHOULDER], pose[LEFT_SHOULDER] = (-0.2, 1.0, 0.0), (0.2, 1.0, 0.0)
    pose[RIGHT_ELBOW], pose[LEFT_ELBOW] = (-0.1, 1.3, 0.0), (0.1, 1.3, 0.0)
    pose[RIGHT_WRIST], pose[LEFT_WRIST] = (0.2, 1.5, 0.0), (-0.2, 1.5, 0.0)
    return pose


@pytest.fixture
def rec() -> ctrl.ReconocedorVocabulario:
    banco = BancoDinamico(gestos=[], plantillas=[], umbral=1.0)
    return ctrl.ReconocedorVocabulario(0, banco=banco, detector=object())


def paso(rec, flight, t, *, det=None, ev=None, pose=None, follow=None, rumbo=0.0):
    """Un frame: observaciones inyectadas y decision sobre el backend falso."""
    rec.observar(pose, None, t)
    if det is not None:
        rec.deteccion = det
    if ev is not None:
        rec.evento_estatico = ev
    return rec.aplicar(
        flight, t=t, speed_xy=SPEED[0], speed_z=SPEED[1], rumbo_deg=rumbo,
        rotar=ctrl.al_marco_del_mundo, marker_follow=follow, marker_body_frame=False)


# ------------------------------------------------------------ dinamicos


def test_en_el_suelo_solo_el_senalero_despega(rec) -> None:
    flight = FakeFlight()
    paso(rec, flight, 1.0, det=deteccion("ven_aca", 1.0))
    assert "takeoff" not in flight.llamadas and rec.comportamiento == HOVER
    assert any("ignorado" in texto for texto, _ in rec.novedades)

    paso(rec, flight, 2.0, det=deteccion("senalero", 2.0))
    assert flight.llamadas.count("takeoff") == 1 and flight.flying
    assert ("senalero -> DESPEGAR", True) in rec.novedades


def test_ven_aca_sigue_al_marker_y_el_aplauso_lo_suelta(rec) -> None:
    flight, follow = FakeFlight(), FakeFollow()
    paso(rec, flight, 1.0, det=deteccion("senalero", 1.0), follow=follow)
    aviso, emergencia = paso(rec, flight, 2.0, det=deteccion("ven_aca", 2.0), follow=follow)
    assert not emergencia and "MARKER 65" in aviso
    assert follow.active("drone1") and flight.velocidades[-1] == (0.05, 0.0, 0.0)

    # Sigue solo, frame tras frame, sin nuevos gestos.
    n = len(flight.velocidades)
    paso(rec, flight, 2.1, follow=follow)
    assert len(flight.velocidades) == n + 1

    # El aplauso cambia de modo, deja hover y suelta el marker.
    paso(rec, flight, 3.0, det=deteccion("aplaudir", 3.0), follow=follow)
    assert rec.modo == ESTATICO and rec.comportamiento == HOVER
    assert not follow.active("drone1") and flight.flying
    n = len(flight.velocidades)
    paso(rec, flight, 3.1, follow=follow)
    assert len(flight.velocidades) == n, "en modo estatico ya no sigue"


def test_senalero_ignorado_en_modo_estatico_y_aterriza_en_dinamico(rec) -> None:
    flight = FakeFlight()
    paso(rec, flight, 1.0, det=deteccion("senalero", 1.0))
    paso(rec, flight, 2.0, det=deteccion("aplaudir", 2.0))
    paso(rec, flight, 3.0, det=deteccion("senalero", 3.0))
    assert flight.flying and not any(c.startswith("land") for c in flight.llamadas)
    paso(rec, flight, 4.0, det=deteccion("aplaudir", 4.0))
    paso(rec, flight, 5.0, det=deteccion("senalero", 5.0))
    assert not flight.flying and "land:gesto senalero" in flight.llamadas


def test_arco_sin_backend_que_sepa_la_pirueta_deja_hover_y_lo_dice(rec) -> None:
    flight = FakeFlight()
    paso(rec, flight, 1.0, det=deteccion("senalero", 1.0))
    aviso, _ = paso(rec, flight, 2.0, det=deteccion("arco", 2.0))
    assert "necesita --backend robotat" in aviso
    assert rec.comportamiento == "hover" and flight.llamadas[-1] == "hover"


def test_arco_hace_la_pirueta_y_al_terminar_vuelve_a_hover(rec) -> None:
    flight = FakeFlight()
    pasos = iter([False, False, True])
    flight.pirueta = lambda: next(pasos)
    paso(rec, flight, 1.0, det=deteccion("senalero", 1.0))
    aviso, _ = paso(rec, flight, 2.0, det=deteccion("arco", 2.0))
    assert rec.comportamiento == "PIRUETA" and "PIRUETA" in aviso
    paso(rec, flight, 2.1)
    aviso, _ = paso(rec, flight, 2.2)
    assert aviso == "PIRUETA terminada" and rec.comportamiento == "hover"


def test_la_x_frena_la_pirueta(rec) -> None:
    flight = FakeFlight()
    flight.pirueta = lambda: False
    paso(rec, flight, 1.0, det=deteccion("senalero", 1.0))
    paso(rec, flight, 2.0, det=deteccion("arco", 2.0))
    x = pose_x_sobre_la_cabeza()
    paso(rec, flight, 3.0, pose=x)
    aviso, _ = paso(rec, flight, 3.0 + ctrl.PARO_FRENA_S + 0.05, pose=x)
    assert "FRENADO" in aviso and rec.comportamiento == "hover"


def test_circulo_orbita_solo_con_backend_que_sepa(rec) -> None:
    """Sin `orbit_marker` en el backend (cruz, Flow Deck) la orbita avisa y deja hover."""
    class Seguidor:
        def marker_position(self):
            return (0.0, 0.0, 0.8)

        def active(self, key):
            return False

        def deactivate(self, keys=None):
            pass

    flight = FakeFlight()
    paso(rec, flight, 1.0, det=deteccion("senalero", 1.0))
    aviso, _ = paso(rec, flight, 2.0, det=deteccion("circulo", 2.0), follow=Seguidor())
    assert "NO ORBITA" in aviso and "robotat" in aviso
    assert rec.comportamiento == "hover" and flight.llamadas[-1] == "hover"


def test_circulo_orbita_y_aplaudir_sale(rec) -> None:
    class FlightOrbita(FakeFlight):
        def __init__(self):
            super().__init__()
            self.orbitas = 0

        def orbit_marker(self, marker_follow):
            self.orbitas += 1
            self.llamadas.append("orbit_marker")

    class Seguidor:
        def marker_position(self):
            return (0.0, 0.0, 0.8)

        def active(self, key):
            return False

        def deactivate(self, keys=None):
            pass

    flight = FlightOrbita()
    paso(rec, flight, 1.0, det=deteccion("senalero", 1.0))
    aviso, _ = paso(rec, flight, 2.0, det=deteccion("circulo", 2.0), follow=Seguidor())
    assert rec.comportamiento == "ORBITAR" and "ORBITANDO" in aviso and flight.orbitas == 1
    paso(rec, flight, 2.5, follow=Seguidor())
    assert flight.orbitas == 2  # sigue orbitando sin gesto nuevo
    aviso, _ = paso(rec, flight, 3.0, det=deteccion("aplaudir", 3.0), follow=Seguidor())
    assert rec.comportamiento == "hover" and flight.llamadas[-1] == "hover" and flight.orbitas == 2


# ------------------------------------------------------------- estaticos


def test_los_estaticos_solo_mueven_en_modo_estatico_y_en_el_aire(rec) -> None:
    flight = FakeFlight()
    adelante = evento(Gesture.ADELANTE)

    paso(rec, flight, 1.0, ev=adelante)                      # dinamico, en el suelo
    assert "set_velocity" not in flight.llamadas
    paso(rec, flight, 2.0, det=deteccion("senalero", 2.0))
    paso(rec, flight, 3.0, ev=adelante)                      # dinamico, en el aire
    assert "set_velocity" not in flight.llamadas and rec.modo == DINAMICO

    paso(rec, flight, 4.0, det=deteccion("aplaudir", 4.0))
    paso(rec, flight, 5.0, ev=adelante, rumbo=90.0)          # estatico, en el aire
    vx, vy, vz = flight.velocidades[-1]
    assert abs(vx) < 1e-6 and abs(vy - SPEED[0]) < 1e-6 and vz == 0.0, "ADELANTE girado 90 deg"
    assert rec.comportamiento == "MANUAL"

    paso(rec, flight, 5.1, ev=evento(Gesture.ADELANTE, confirmado=False))
    assert flight.llamadas[-1] == "hover", "sin direccion confirmada, hover"

    flight.request_land("prueba")
    paso(rec, flight, 6.0, ev=adelante)                      # estatico, en el suelo
    assert flight.llamadas[-1] == "hover" and rec.comportamiento == HOVER


def test_los_gestos_de_estado_estaticos_no_salen_del_reconocedor(rec, monkeypatch) -> None:
    despegar = evento(Gesture.DESPEGAR)
    monkeypatch.setattr(rec.estatico, "update", lambda *_a, **_k: despegar)
    salida = rec.observar(None, None, 1.0)
    assert salida.gesture is Gesture.NO_GESTURE and not salida.confirmed
    assert salida.velocity == VelocityIntent()


# ------------------------------------------------------------------ paro


def test_el_paro_aterriza_bloquea_y_al_soltar_arranca_en_dinamico(rec) -> None:
    flight, follow = FakeFlight(), FakeFollow()
    x = pose_x_sobre_la_cabeza()
    paso(rec, flight, 0.0, det=deteccion("senalero", 0.0), follow=follow)
    paso(rec, flight, 0.5, det=deteccion("aplaudir", 0.5), follow=follow)
    assert flight.flying and rec.modo == ESTATICO

    # La X se sostiene 1 s: aterriza y bloquea.
    for t in (1.0, 1.5, 2.0):
        aviso, emergencia = paso(rec, flight, t, pose=x, follow=follow)
    assert not emergencia and not flight.flying
    assert "land:PARO por gesto" in flight.llamadas and "PARO" in aviso
    assert rec.maquina.paro_activo and rec.modo == DINAMICO

    # Con el paro activo nada se atiende, ni siquiera el senalero.
    paso(rec, flight, 2.2, pose=x, det=deteccion("senalero", 2.2), follow=follow)
    assert flight.llamadas.count("takeoff") == 1

    # Se sueltan los brazos: el paro se libera y el movimiento de bajar los
    # brazos se descarta durante un segundo.
    paso(rec, flight, 2.6, follow=follow)
    assert not rec.maquina.paro_activo
    paso(rec, flight, 3.0, det=deteccion("senalero", 3.0), follow=follow)
    assert flight.llamadas.count("takeoff") == 1
    assert any("movimiento del paro" in texto for texto, _ in rec.novedades)

    # Pasado ese segundo, el vocabulario vuelve a escuchar, en modo dinamico.
    paso(rec, flight, 4.0, det=deteccion("senalero", 4.0), follow=follow)
    assert flight.llamadas.count("takeoff") == 2 and flight.flying


def test_el_paro_sostenido_pide_emergencia(rec) -> None:
    flight = FakeFlight()
    x = pose_x_sobre_la_cabeza()
    paso(rec, flight, 0.0, det=deteccion("senalero", 0.0))
    # La X empieza en 1.0 s: aterriza a los 1.0 s sostenida (2.0 s) y corta
    # motores a los 3.0 s sostenida (4.0 s), ni un frame antes.
    emergencias = [paso(rec, flight, t, pose=x)[1] for t in (1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0)]
    assert emergencias[:-1] == [False] * 6
    assert emergencias[-1] is True, "sostenida confirmacion + 2 s"
    assert "land:PARO por gesto" in flight.llamadas


def test_un_aterrizaje_ajeno_olvida_el_comportamiento(rec) -> None:
    flight, follow = FakeFlight(), FakeFollow()
    paso(rec, flight, 1.0, det=deteccion("senalero", 1.0), follow=follow)
    paso(rec, flight, 2.0, det=deteccion("ven_aca", 2.0), follow=follow)
    assert rec.comportamiento == "SEGUIR" and follow.active("drone1")

    flight.flying = False                  # el watchdog del backend aterrizo
    aviso, _ = paso(rec, flight, 3.0, follow=follow)
    assert rec.comportamiento == HOVER and not follow.active("drone1")
    assert aviso is None and "set_velocity" not in flight.llamadas[-1:]


# ------------------------------------------------------------- PTZ


class FakeControl:
    def __init__(self) -> None:
        self.ordenes = []

    def pedir(self, orden) -> None:
        if orden is not None:
            self.ordenes.append(orden)


class _Landmark:
    def __init__(self, x: float, y: float) -> None:
        self.x, self.y, self.z, self.visibility = x, y, 0.0, 1.0


def landmarks_en(x: float, y: float) -> list:
    """Los 33 landmarks 2D apilados en un punto: el torso queda justo ahi."""
    return [_Landmark(x, y) for _ in range(N_LANDMARKS)]


def test_la_camara_sigue_y_el_frame_girando_es_hueco(rec) -> None:
    control = FakeControl()
    rec.activar_seguimiento(control, ctrl.AjustesPTZ())

    # Persona a la derecha: arranca el pan y ese frame no sirve para clasificar.
    assert rec._seguir_camara(landmarks_en(0.95, 0.5), 0.0) is True
    assert control.ordenes[-1].codigo == "Right"
    assert rec.estado_camara == "siguiendo Right"

    # Centrada: para, y pasado el enfriamiento el frame vuelve a valer.
    rec._seguir_camara(landmarks_en(0.5, 0.5), 1.0)
    assert control.ordenes[-1].es_parada
    assert rec._seguir_camara(landmarks_en(0.5, 0.5), 5.0) is False
    assert rec.estado_camara == "centrada"

    # Con un gesto en curso la camara se queda quieta, salvo error critico.
    rec.dinamico.en_segmento = True
    n = len(control.ordenes)
    assert rec._seguir_camara(landmarks_en(0.75, 0.5), 6.0) is False
    assert len(control.ordenes) == n and rec.estado_camara == "quieta (gesto en curso)"


def test_sin_seguimiento_no_hay_huecos(rec) -> None:
    assert rec._seguir_camara(landmarks_en(0.95, 0.5), 0.0) is False
    assert rec.estado_camara == ""


# ------------------------------------------------------------- registro


def test_el_registro_lleva_modo_y_comportamiento(rec) -> None:
    assert "modo" in ctrl.Registro.CAMPOS and "comportamiento" in ctrl.Registro.CAMPOS
    assert rec.modo == DINAMICO and rec.comportamiento == HOVER


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))


def test_circulo_parecido_a_aplaudir_se_ignora(rec) -> None:
    from types import SimpleNamespace

    class FlightOrbita(FakeFlight):
        def orbit_marker(self, marker_follow):
            self.llamadas.append("orbit_marker")

    class Seguidor:
        def marker_position(self):
            return (0.0, 0.0, 0.8)

        def active(self, key):
            return False

        def deactivate(self, keys=None):
            pass

    flight = FlightOrbita()
    paso(rec, flight, 1.0, det=deteccion("senalero", 1.0))
    det = deteccion("circulo", 2.0)
    det = SimpleNamespace(**{**det.__dict__, "distancias": {"circulo": det.distancia, "aplaudir": det.distancia * 1.05}})
    paso(rec, flight, 2.0, det=det, follow=Seguidor())
    assert rec.comportamiento == "hover"
    assert any("parecido a aplaudir" in n[0] for n in rec.novedades)
    det = deteccion("circulo", 3.0)
    det = SimpleNamespace(**{**det.__dict__, "distancias": {"circulo": det.distancia, "aplaudir": det.distancia * 1.6}})
    paso(rec, flight, 3.0, det=det, follow=Seguidor())
    assert rec.comportamiento == "ORBITAR" and flight.llamadas[-1] == "orbit_marker"


# --------------------------------------------- parar sin depender del aplauso
#
# Sesion de las 18:50 del 2026-09-18: el dron siguio al operador 59 s. Los
# aplausos se rechazaban ("demasiado largo", "pose perdida") porque caminaba y
# la camara se movia, y con la camara girando **tampoco el paro veia la pose**.


def test_la_x_frena_antes_de_aterrizar(rec) -> None:
    flight, follow = FakeFlight(), FakeFollow()
    x = pose_x_sobre_la_cabeza()
    paso(rec, flight, 0.0, det=deteccion("senalero", 0.0), follow=follow)
    paso(rec, flight, 1.0, det=deteccion("ven_aca", 1.0), follow=follow)
    assert rec.maquina.comportamiento == "SEGUIR" and follow.active("drone1")

    paso(rec, flight, 2.0, pose=x, follow=follow)                 # empieza la X
    aviso, emergencia = paso(rec, flight, 2.0 + ctrl.PARO_FRENA_S + 0.05, pose=x, follow=follow)
    assert "FRENADO" in aviso and not emergencia
    assert rec.maquina.comportamiento == "hover" and not follow.active("drone1")
    assert flight.flying and "land:PARO por gesto" not in flight.llamadas    # frena, no aterriza

    # Bajando los brazos ahi, el dron se queda en hover y sigue obedeciendo.
    paso(rec, flight, 2.6, follow=follow)
    assert flight.flying and not rec.maquina.paro_activo


def test_la_x_mantenida_sigue_aterrizando(rec) -> None:
    flight, follow = FakeFlight(), FakeFollow()
    x = pose_x_sobre_la_cabeza()
    paso(rec, flight, 0.0, det=deteccion("senalero", 0.0), follow=follow)
    for t in (1.0, 1.4, 1.8, 2.2):
        paso(rec, flight, t, pose=x, follow=follow)
    assert not flight.flying and "land:PARO por gesto" in flight.llamadas


def test_el_paro_ve_la_pose_aunque_la_camara_este_girando(rec) -> None:
    # Los canales que clasifican movimiento se quedan sin frame (pose=None);
    # el paro recibe la pose real por `pose_paro`.
    x = pose_x_sobre_la_cabeza()
    rec.observar(None, None, 0.0, pose_paro=x)
    rec.observar(None, None, 0.5, pose_paro=x)
    assert rec.regla.cumple and rec.regla.sostenido_s == pytest.approx(0.5)


def test_la_camara_no_gira_mientras_se_hace_la_x(rec) -> None:
    control = FakeControl()
    rec.activar_seguimiento(control, ctrl.AjustesPTZ())
    rec.observar(None, None, 0.0, pose_paro=pose_x_sobre_la_cabeza())
    assert rec._seguir_camara(landmarks_en(0.75, 0.5), 0.1) is False
    assert control.ordenes == []


def test_la_cola_de_un_gesto_no_cambia_de_comportamiento(rec) -> None:
    # 18:47: `circulo` y, 2.6 s despues, un `ven_aca` que el operador no hizo.
    flight, follow = FakeFlight(), FakeFollow()
    flight.orbit_marker = lambda _f: None
    paso(rec, flight, 0.0, det=deteccion("senalero", 0.0), follow=follow)
    paso(rec, flight, 5.0, det=deteccion("circulo", 5.0), follow=follow)
    paso(rec, flight, 7.6, det=deteccion("ven_aca", 7.6), follow=follow)
    assert rec.maquina.comportamiento == "ORBITAR"
    assert any("del gesto anterior" in texto for texto, _ in rec.novedades)
    # Pasado el antirrebote, el mismo gesto si cambia.
    paso(rec, flight, 5.0 + ctrl.REBOTE_COMPORTAMIENTO_S + 0.5,
         det=deteccion("ven_aca", 9.6), follow=follow)
    assert rec.maquina.comportamiento == "SEGUIR"


def test_los_radios_no_pueden_quedar_dentro_de_la_zona_del_marker(capsys) -> None:
    from types import SimpleNamespace
    args = SimpleNamespace(exclusion_marker=0.60, radio_seguir=0.45, radio_orbita=0.80)
    ctrl.radios_coherentes(args)
    assert args.radio_seguir == pytest.approx(0.75) and args.radio_orbita == 0.80
    assert "radio-seguir" in capsys.readouterr().out
