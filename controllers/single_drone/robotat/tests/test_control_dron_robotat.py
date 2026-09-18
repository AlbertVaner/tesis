"""Línea de órdenes del panel: sin abrir Tk, radios ni broker."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import control_dron_robotat as panel  # noqa: E402


def args(*extra: str):
    return panel.build_parser().parse_args(["--dry-run", *extra])


def test_parametros_firmware():
    assert panel.parametros_firmware(["a.b=1", " c.d = 2 "]) == {"a.b": "1", "c.d": "2"}
    assert panel.parametros_firmware(None) == {}
    with pytest.raises(SystemExit):
        panel.parametros_firmware(["sinigual"])


def test_opciones_dron_1_por_defecto():
    o = panel.opciones_desde_args(args())
    assert o.topic == "mocap/drone3" and o.nombre == "Dron 1"
    assert o.uri.endswith("/84/2M/E7E7E7E7E4")
    assert o.ext_pos_std_m == panel.DEFAULT_EXT_POS_STD_M and o.anticipo_s == 0.0
    assert not o.extpose and o.parametros == {}


def test_opciones_dron_2_con_ajustes():
    o = panel.opciones_desde_args(args("--dron", "2", "--ext-pos-std", "0.03", "--anticipo-s", "0.08",
                                       "--extpose", "--param", "posCtlPid.xKp=1.0", "--altura", "0.5",
                                       "--radio-max", "0.8", "--topic", "mocap/otro"))
    assert o.topic == "mocap/otro" and o.nombre == "Dron 2"
    assert o.uri.endswith("/90/2M/E7E7E7E7E5")
    assert (o.ext_pos_std_m, o.anticipo_s, o.extpose) == (0.03, 0.08, True)
    assert o.parametros == {"posCtlPid.xKp": "1.0"}
    assert (o.altura_m, o.radio_max_m) == (0.5, 0.8)


@pytest.mark.parametrize("extra", [
    ("--anticipo-s", "0.5"), ("--ext-pos-std", "0"), ("--altura", "1.5"),
])
def test_rangos_rechazados(extra):
    with pytest.raises(SystemExit):
        panel.opciones_desde_args(args(*extra))


def test_uri_explicita_manda():
    o = panel.opciones_desde_args(args("--uri", "radio://0/80/2M/E7E7E7E7E7"))
    assert o.uri == "radio://0/80/2M/E7E7E7E7E7"


def test_ganancias_mitad_y_param_manda():
    o = panel.opciones_desde_args(args("--ganancias", "mitad", "--param", "posCtlPid.zKp=1.5"))
    assert o.parametros["posCtlPid.xKp"] == "1.0"
    assert o.parametros["velCtlPid.vzKp"] == "12"
    assert o.parametros["posCtlPid.zKp"] == "1.5"
    assert len(o.parametros) == 9


def test_ganancias_fabrica_no_toca_nada():
    assert panel.opciones_desde_args(args()).parametros == {}
    assert "posCtlPid.zKp" not in panel.opciones_desde_args(args("--ganancias", "mitad-xy")).parametros


def test_velocidad():
    assert panel.opciones_desde_args(args()).velocidad_mps == panel.GOTO_SPEED_MPS
    assert panel.opciones_desde_args(args("--velocidad", "0.25")).velocidad_mps == 0.25
    with pytest.raises(SystemExit):
        panel.opciones_desde_args(args("--velocidad", "1.0"))


def test_modo():
    assert panel.build_parser().parse_args(["--dry-run"]).modo == "fluido"
    assert panel.build_parser().parse_args(["--dry-run", "--modo", "pasos"]).modo == "pasos"


def test_ganancias_robotat():
    o = panel.opciones_desde_args(args("--ganancias", "robotat"))
    assert o.parametros["posCtlPid.thrustBase"] == "46000"
    assert o.parametros["velCtlPid.vzKi"] == "8"
    assert o.parametros["locSrv.extPosStdDev"] == "0.0300"
    o = panel.opciones_desde_args(args("--ganancias", "robotat", "--param", "posCtlPid.thrustBase=47000"))
    assert o.parametros["posCtlPid.thrustBase"] == "47000"
