"""Panel de tres drones sobre el controlador nuevo: opciones, teclas y supervisor, sin Tk."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import control_tres_drones_robotat as triple  # noqa: E402
from dron_robotat import DronSimulado  # noqa: E402
from robotat_backend import SupervisorSeparacion, separacion  # noqa: E402
from tk_keys import DUAL_KEYSYMS, EMERGENCY_KEYSYMS, normalize_key  # noqa: E402


def args(*extra):
    return triple.build_parser().parse_args(["--dry-run", *extra])


def test_opciones_triple_en_dry_run():
    o = triple.opciones_triple(args())
    assert tuple(o) == triple.CLAVES
    assert o["drone3"].nombre == "Dron 3"
    assert len({x.uri for x in o.values()}) == 3 and len({x.topic for x in o.values()}) == 3
    assert o["drone3"].parametros == o["drone1"].parametros
    assert o["drone3"].parametros is not o["drone1"].parametros


def test_los_ajustes_comunes_llegan_al_dron_3():
    o = triple.opciones_triple(args("--velocidad", "0.25", "--radio-max", "0.8", "--centro-geocerca", "0", "-0.4",
                                    "--param", "posCtlPid.thrustBase=40000"))
    d3 = o["drone3"]
    assert d3.velocidad_mps == 0.25 and d3.radio_max_m == 0.8 and d3.centro_geocerca == (0.0, -0.4)
    assert d3.parametros["posCtlPid.thrustBase"] == "40000" and d3.thrust_base_explicito


def test_con_hardware_el_dron_3_exige_uri_y_topico():
    """Se rechaza antes de consultar las Crazyradio: nada inventado llega a una radio."""
    parser = triple.build_parser()
    for extra in ([], ["--uri3", "radio://0/90/2M/E7E7E7E7E6"], ["--topic3", "mocap/drone5"]):
        with pytest.raises(RuntimeError, match="--uri3"):
            triple.opciones_triple(parser.parse_args(extra))


def test_topico_repetido_se_rechaza():
    with pytest.raises(RuntimeError, match="mismo rigid body"):
        triple.opciones_triple(args("--topic3", "mocap/drone4"))


def test_antena_compartida_avisa_y_mismo_enlace_se_rechaza(monkeypatch):
    import control_dos_drones_robotat as dual

    radios = ["2B1D933FCC", "9DD2507072"]
    monkeypatch.setattr(dual, "select_radio", lambda pedido, *, index=0: radios[index])
    parser = triple.build_parser()
    avisos: list[str] = []
    o = triple.opciones_triple(
        parser.parse_args(["--uri3", "radio://9DD2507072/90/2M/E7E7E7E7E6", "--topic3", "mocap/drone5"]),
        log=avisos.append)
    assert o["drone3"].uri.endswith("E7E7E7E7E6")
    assert avisos == ["Dron 3 comparte la Crazyradio 9DD2507072 con Dron 2"]

    avisos.clear()
    triple.opciones_triple(
        parser.parse_args(["--uri3", "radio://2B1D933FCC/80/2M/E7E7E7E7E6", "--topic3", "mocap/drone5"]),
        log=avisos.append)
    assert len(avisos) == 1 and "Dron 1" in avisos[0] and "canales distintos" in avisos[0]

    with pytest.raises(RuntimeError, match="mismo Crazyflie"):
        triple.opciones_triple(
            parser.parse_args(["--uri3", "radio://2B1D933FCC/90/2M/e7e7e7e7e5", "--topic3", "mocap/drone5"]),
            log=avisos.append)


def test_teclas_del_dron_3_no_pisan_las_demas():
    teclas3 = set(triple.KEY_DIRECTIONS_3) | set(triple.KEY_ROTATIONS_3)
    ocupadas = {normalize_key(k) for k in (*DUAL_KEYSYMS, *EMERGENCY_KEYSYMS)}
    assert not teclas3 & ocupadas
    assert {normalize_key(k) for k in triple.KEYSYMS_3} == teclas3
    assert all(v[0] == 2 for v in (*triple.KEY_DIRECTIONS_3.values(), *triple.KEY_ROTATIONS_3.values()))


def test_botones_de_direccion_cubren_las_tres_columnas():
    assert tuple(triple.PanelTresRobotat.BOTONES) == triple.CLAVES
    for clave, botones in triple.PanelTresRobotat.BOTONES.items():
        assert len(botones) == 8
        for _texto, tecla in botones:
            assert triple.PanelTresRobotat._slot_de(tecla) == triple.CLAVES.index(clave), (clave, tecla)


def _drones():
    o = triple.opciones_triple(args())
    drones = {c: DronSimulado(o[c], log=lambda _m: None) for c in triple.CLAVES}
    for d in drones.values():
        d.preflight()
    return drones


def test_los_simulados_arrancan_separados():
    drones = _drones()
    assert [d.estado().mocap[1] for d in drones.values()] == pytest.approx([0.0, 0.9, 1.8])
    assert separacion({c: d.estado() for c, d in drones.items()}) == pytest.approx(0.9)


def test_supervisor_vigila_los_tres_pares():
    drones = _drones()
    sup = SupervisorSeparacion(drones, log=lambda _m: None)
    for d in drones.values():
        d.takeoff()
    assert sup.comprobar() == pytest.approx(0.9) and not sup.disparado
    # el dron 3 se acerca al 2; el 1 sigue lejos de ambos
    altura = drones["drone2"].estado().mocap[2]
    drones["drone3"]._pose = (0.0, 1.1, altura)
    assert sup.comprobar() == pytest.approx(0.2)
    assert sup.disparado
    assert not any(d.estado().en_vuelo for d in drones.values())


def test_supervisor_ignora_a_un_dron_posado():
    drones = _drones()
    sup = SupervisorSeparacion(drones, log=lambda _m: None)
    drones["drone1"].takeoff()
    drones["drone2"].takeoff()
    drones["drone3"]._pose = (0.0, 0.1, 0.05)  # posado junto al dron 1
    sup.comprobar()
    assert not sup.disparado
    assert drones["drone1"].estado().en_vuelo and drones["drone2"].estado().en_vuelo


def test_un_dron_sin_pose_no_apaga_la_vigilancia():
    drones = _drones()
    estados = {c: d.estado() for c, d in drones.items()}
    estados["drone3"].mocap = None
    assert separacion(estados) == pytest.approx(0.9)
    estados["drone2"].mocap = None
    assert separacion(estados) is None
