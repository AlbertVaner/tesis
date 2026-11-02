"""`--multicamara --reconocedor vocabulario`: el vocabulario completo sobre la camara activa.

Sin camaras ni dron. Lo que puede fallar en silencio: un frame procesado dos
veces (el DTW ve un gesto el doble de lento y el paro se dispara dos veces),
un gesto que se parte entre dos camaras, un gesto que la camara nueva ya tenia
confirmado y que se ejecuta solo por cambiar de camara, y una camara que gira
en mitad de un gesto dinamico.

Uso, desde la raiz del repositorio::

    .\\.venv\\Scripts\\python.exe -m pytest -q .\\controllers\\single_drone\\camera\\tests\\test_vocabulario_multicamara.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

MODULE_DIR = Path(__file__).resolve().parents[1]
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import control_camara_dron1 as ctrl  # noqa: E402
from contracts import Gesture, GestureEvent, VelocityIntent  # noqa: E402
from multicamara.rostro import SIN_ROSTRO  # noqa: E402
from multicamara.sistema import Estado  # noqa: E402
from recognition.dinamicos import BancoDinamico  # noqa: E402


def _evento(gesto: Gesture, confirmado: bool) -> GestureEvent:
    return GestureEvent(gesto, 1.0, confirmado, True, VelocityIntent(vz=1.0), 0.0)


class _Sistema:
    """Lo que el reconocedor le pide a `SistemaMulticamara`."""

    def __init__(self) -> None:
        self.activa: str | None = "cam1"
        self.estados: dict[str, Estado] = {}
        self.alto_cabecera = 0
        self.avisos: list[bool] = []
        self.reiniciado = 0
        self.cerrado = 0

    def poner(self, nombre: str, seq: int) -> None:
        self.estados[nombre] = Estado(None, _evento(Gesture.NO_GESTURE, False), SIN_ROSTRO,
                                      0.0, True, seq, t=float(seq))

    def gesto_en_curso(self, en_curso: bool) -> None:
        self.avisos.append(en_curso)

    def reiniciar(self) -> None:
        self.reiniciado += 1

    def cerrar(self) -> None:
        self.cerrado += 1


@pytest.fixture
def armado(monkeypatch):
    """Reconocedor con `procesar_landmarks` falso que cuenta y devuelve lo pedido."""
    sistema = _Sistema()
    banco = BancoDinamico(gestos=[], plantillas=[], umbral=1.0)
    rec = ctrl.ReconocedorVocabularioMulticamara(sistema, banco=banco)
    llamadas: list[tuple] = []
    siguiente = {"evento": _evento(Gesture.NO_GESTURE, False)}

    def falso(mundo, t, *, girando):
        llamadas.append((t, girando))
        rec.novedades = []
        rec.evento_estatico = siguiente["evento"]
        return siguiente["evento"]

    monkeypatch.setattr(rec, "procesar_landmarks", falso)
    return SimpleNamespace(rec=rec, sistema=sistema, llamadas=llamadas, siguiente=siguiente)


def test_cada_frame_de_la_activa_se_procesa_una_sola_vez(armado):
    armado.sistema.poner("cam1", seq=1)
    armado.rec.procesar("vista")
    armado.rec.paro_disparado = True          # lo que dejo el frame anterior
    armado.rec.procesar("vista")              # mismo seq: el bucle desperto por otra camara
    assert len(armado.llamadas) == 1
    assert armado.rec.paro_disparado is False
    armado.sistema.poner("cam1", seq=2)
    armado.rec.procesar("vista")
    assert len(armado.llamadas) == 2


def test_los_frames_tomados_girando_llegan_marcados(armado):
    armado.sistema.poner("cam1", seq=1)
    armado.sistema.estados["cam1"] = Estado(None, _evento(Gesture.NO_GESTURE, False), SIN_ROSTRO,
                                            0.0, True, 1, t=1.0, moviendo=True)
    armado.rec.procesar("vista")
    assert armado.llamadas == [(1.0, True)]


def test_la_vista_combinada_se_devuelve_tal_cual(armado):
    armado.sistema.poner("cam1", seq=1)
    vista, _, mano = armado.rec.procesar("vista")
    assert vista == "vista" and mano == ""


def test_cambiar_de_camara_reinicia_dinamico_y_estatico_pero_no_el_modo(armado, monkeypatch):
    reinicios = []
    monkeypatch.setattr(armado.rec.dinamico, "reset", lambda: reinicios.append("dinamico"))
    monkeypatch.setattr(armado.rec.estatico, "reset", lambda: reinicios.append("estatico"))
    armado.sistema.poner("cam1", seq=1)
    armado.rec.procesar("vista")
    modo = armado.rec.modo
    reinicios.clear()

    armado.sistema.activa = "cam2"
    armado.sistema.poner("cam2", seq=1)
    armado.rec.procesar("vista")
    assert reinicios == ["dinamico", "estatico"]
    assert armado.rec.modo == modo
    assert ("camara activa: cam2", True) in armado.rec.novedades


def test_lo_confirmado_en_la_camara_nueva_no_navega_hasta_soltarlo(armado):
    armado.sistema.poner("cam1", seq=1)
    armado.rec.procesar("vista")

    armado.sistema.activa = "cam2"
    armado.siguiente["evento"] = _evento(Gesture.ARRIBA, True)
    armado.sistema.poner("cam2", seq=1)
    _, evento, _ = armado.rec.procesar("vista")
    assert evento.gesture is Gesture.ARRIBA and evento.confirmed is False
    assert armado.rec.evento_estatico.confirmed is False     # es lo que lee `aplicar`

    armado.siguiente["evento"] = _evento(Gesture.NO_GESTURE, False)
    armado.sistema.poner("cam2", seq=2)
    armado.rec.procesar("vista")
    armado.siguiente["evento"] = _evento(Gesture.ARRIBA, True)
    armado.sistema.poner("cam2", seq=3)
    _, evento, _ = armado.rec.procesar("vista")
    assert evento.confirmed is True


def test_un_gesto_dinamico_en_curso_congela_la_camara_activa(armado, monkeypatch):
    armado.sistema.poner("cam1", seq=1)
    monkeypatch.setattr(type(armado.rec), "gesto_en_curso", property(lambda self: True))
    armado.rec.procesar("vista")
    assert armado.sistema.avisos[-1] is True


def test_sin_nadie_a_la_vista_el_tiempo_sigue_corriendo(armado):
    armado.sistema.activa = None
    armado.rec.procesar("vista")
    armado.rec.procesar("vista")
    assert len(armado.llamadas) == 2 and all(not g for _, g in armado.llamadas)


def test_cerrar_para_las_camaras(armado):
    armado.rec.close()
    assert armado.sistema.cerrado == 1


def test_crear_reconocedor_elige_la_clase_segun_el_reconocedor(armado):
    sistema = ctrl.SistemaMulticamara([])
    banco = BancoDinamico(gestos=[], plantillas=[], umbral=1.0)
    args = SimpleNamespace(reconocedor="vocabulario", paro="cabeza", confirmacion=None, camera=0)
    assert isinstance(ctrl.crear_reconocedor(args, banco, sistema),
                      ctrl.ReconocedorVocabularioMulticamara)
    args.reconocedor = "cuerpo"
    assert isinstance(ctrl.crear_reconocedor(args, None, sistema), ctrl.ReconocedorMulticamara)


# ------------------------------------------------- --multicamara y --dron


def _args_multicamara(**cambios):
    base = dict(multicamara=True, reconocedor="vocabulario", rtsp=None, seguir=False,
                dron="1", sin_ptz=True, ptz_dry_run=True, camera=0)
    return SimpleNamespace(**(base | cambios))


def test_multicamara_acepta_la_formacion_de_dos_drones(monkeypatch):
    """`--dron ambos` ya no se rechaza: las seis camaras gobiernan la formacion."""
    abiertas = []
    monkeypatch.setattr(ctrl, "camaras_desde_entorno",
                        lambda: [(f"cam{n}", f"rtsp://u:c@10.0.0.{n}/x") for n in range(1, 7)])
    monkeypatch.setattr(ctrl, "SistemaMulticamara",
                        lambda camaras, **kw: abiertas.append((camaras, kw)) or "sistema")
    assert ctrl.fuente_de_video(_args_multicamara(dron=ctrl.AMBOS)) == "sistema"
    camaras, kw = abiertas[0]
    assert [n for n, _ in camaras] == [f"cam{n}" for n in range(1, 7)]
    assert kw == {"ptz": False, "dry_run": True}


@pytest.mark.parametrize("cambio", [
    {"reconocedor": "manos"}, {"rtsp": "cam1"}, {"seguir": True},
])
def test_multicamara_sigue_rechazando_lo_incompatible(cambio):
    with pytest.raises(SystemExit, match="--multicamara"):
        ctrl.fuente_de_video(_args_multicamara(dron=ctrl.AMBOS, **cambio))
