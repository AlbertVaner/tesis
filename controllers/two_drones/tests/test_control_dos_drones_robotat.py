"""Panel de dos drones sobre el controlador nuevo: opciones y supervisor, sin Tk."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import control_dos_drones_robotat as dual  # noqa: E402
from dron_robotat import DronSimulado  # noqa: E402


def args(*extra):
    return dual.build_parser().parse_args(["--dry-run", *extra])


def test_opciones_dual_por_defecto():
    o = dual.opciones_dual(args())
    assert set(o) == {"drone1", "drone2"}
    assert o["drone1"].topic == "mocap/drone3" and o["drone2"].topic == "mocap/drone4"
    assert o["drone1"].uri != o["drone2"].uri
    assert o["drone2"].parametros["posCtlPid.thrustBase"] == "46000"
    assert not o["drone2"].thrust_base_explicito


def test_param_explicito_para_los_dos():
    o = dual.opciones_dual(args("--param", "posCtlPid.thrustBase=40000", "--topic2", "mocap/otro"))
    assert o["drone1"].parametros["posCtlPid.thrustBase"] == "40000" and o["drone1"].thrust_base_explicito
    assert o["drone2"].topic == "mocap/otro"


def _drones(monkeypatch):
    o = dual.opciones_dual(args())
    drones = {c: DronSimulado(o[c], log=lambda _m: None) for c in dual.CLAVES}
    for d in drones.values():
        d.preflight()
    # el simulado empieza en (0, 0, 0.05): separar al segundo antes de despegar
    drones["drone2"]._pose = (0.0, 0.9, 0.05)
    drones["drone2"]._estado.origen = drones["drone2"]._pose
    drones["drone2"]._estado.objetivo = drones["drone2"]._pose
    return drones


def test_supervisor_aterriza_si_se_acercan(monkeypatch):
    drones = _drones(monkeypatch)
    sup = dual.SupervisorSeparacion(drones, log=lambda _m: None)
    for d in drones.values():
        d.takeoff()
    assert sup.comprobar() == pytest.approx(0.9)
    assert all(d.estado().en_vuelo for d in drones.values())
    # el dron 2 se acerca a 0.2 m
    drones["drone2"]._pose = (0.0, 0.2, 0.4)
    assert sup.comprobar() == pytest.approx(0.2)
    assert sup.disparado
    assert not any(d.estado().en_vuelo for d in drones.values())


def test_supervisor_no_actua_con_uno_solo(monkeypatch):
    drones = _drones(monkeypatch)
    sup = dual.SupervisorSeparacion(drones, log=lambda _m: None)
    drones["drone1"].takeoff()
    drones["drone2"]._pose = (0.0, 0.1, 0.05)
    sup.comprobar()
    assert drones["drone1"].estado().en_vuelo and not sup.disparado


def test_botones_de_direccion_cubren_las_dos_columnas():
    for clave, botones in dual.BOTONES_DIRECCION.items():
        slot = dual.CLAVES.index(clave)
        assert len(botones) == 8
        for _texto, tecla in botones:
            assert dual.PanelDosRobotat._slot_de(tecla) == slot, (clave, tecla)
