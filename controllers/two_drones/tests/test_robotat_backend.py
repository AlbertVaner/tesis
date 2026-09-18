"""Adaptador del controlador nuevo a la interfaz de la cruz, sin hardware."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import robotat_backend as rcb  # noqa: E402
from cruz_highlevel_backend import BridgeError  # noqa: E402
from cruz_highlevel_protocol import Command  # noqa: E402
from flowdeck_cruz_backend import build_backend  # noqa: E402
import dron_robotat as dr  # noqa: E402


def args(**kw):
    base = dict(backend="robotat", dry_run=True, single=None, uri1=None, uri2=None,
                topic1=None, topic2=None, ganancias="robotat", param=None, velocidad=0.25, radio_max=1.0)
    return argparse.Namespace(**(base | kw))


def backend_listo(monkeypatch, **kw):
    b = build_backend(args(**kw))
    mensajes = []
    b.connect(lambda ok, ev, msg, snap: mensajes.append((ok, ev, msg)))
    # el simulado arranca los dos en el mismo punto: separarlos
    if "drone2" in b.drones:
        d2 = b.drones["drone2"]
        d2._pose = (0.0, 0.9, 0.05); d2._estado.origen = d2._pose; d2._estado.objetivo = d2._pose
    return b, mensajes


def test_build_backend_elige_robotat():
    b = build_backend(args())
    assert isinstance(b, rcb.RobotatCruzBackend)
    assert b.active_keys == ("drone1", "drone2")
    assert build_backend(args(single="drone2")).active_keys == ("drone2",)


def test_opciones_desde_args_param_y_topicos():
    o = rcb.opciones_desde_args(args(param=["posCtlPid.thrustBase=40000"], topic2="mocap/otro"), "drone2")
    assert o.topic == "mocap/otro" and o.nombre == "Dron 2"
    assert o.parametros["posCtlPid.thrustBase"] == "40000" and o.thrust_base_explicito
    assert o.parametros["velCtlPid.vzKi"] == "8" and o.velocidad_mps == 0.25 and o.radio_max_m == 1.0


def test_flujo_de_la_cruz(monkeypatch):
    b, mensajes = backend_listo(monkeypatch)
    assert b.ready and mensajes[-1][1] == "ready"
    snap = b.snapshot()
    assert snap["mode"].startswith("robotat") and snap["drone1"]["enabled"] and snap["separation_m"] == pytest.approx(0.9)
    with pytest.raises(BridgeError, match="despega"):
        b.move(Command("move", "drone1", 0.1, 0, 0))
    b.takeoff(Command("takeoff", "both"))
    assert all(b.snapshot()[k]["airborne"] for k in ("drone1", "drone2"))
    with pytest.raises(BridgeError, match="en vuelo"):
        b.takeoff(Command("takeoff", "drone1"))
    monkeypatch.setattr(dr, "ahora", lambda: 1e9)
    monkeypatch.setattr(rcb, "ahora", lambda: 1e9)
    b.move(Command("move", "drone1", 0.1, 0, 0))
    assert b.drones["drone1"].estado().modo == "FLUIDO"
    assert b.drones["drone2"].estado().modo != "FLUIDO"
    assert b.drones["drone1"].ordenes[-1][0] == "velocidad"
    b._frenar("drone1")
    assert b.drones["drone1"].estado().modo == "VUELO"
    b.land(Command("land", "both"))
    assert not any(b.snapshot()[k]["airborne"] for k in ("drone1", "drone2"))
    b.close()


def test_pulso_se_detiene_solo(monkeypatch):
    b, _ = backend_listo(monkeypatch)
    monkeypatch.setattr(rcb, "PULSO_S", 0.05)
    b.takeoff(Command("takeoff", "drone2"))
    monkeypatch.setattr(dr, "ahora", lambda: 1e9)
    b.move(Command("move", "drone2", 0, 0.1, 0, 20))
    assert b.drones["drone2"].estado().modo == "FLUIDO"
    time.sleep(0.25)
    assert b.drones["drone2"].estado().modo == "VUELO"
    b.close()


def test_follow_move_velocidad_proporcional(monkeypatch):
    b, _ = backend_listo(monkeypatch)
    b.takeoff(Command("takeoff", "drone1"))
    monkeypatch.setattr(dr, "ahora", lambda: 1e9)
    b.follow_move(Command("follow_move", "drone1", 0.025, 0, 0))
    vel = b.drones["drone1"].ordenes[-1][1]
    assert vel[0] == pytest.approx(0.25)  # 0.025 m cada 0.10 s, dentro del tope
    b.follow_move(Command("follow_move", "drone1", 0, 0, 0))
    assert b.drones["drone1"].estado().modo == "VUELO"
    b.close()


def test_emergencia_y_snapshot(monkeypatch):
    b, _ = backend_listo(monkeypatch)
    b.takeoff(Command("takeoff", "both"))
    b.emergency("prueba")
    snap = b.snapshot()
    assert snap["emergency"] and not snap["ready"] and snap["emergency_reason"] == "prueba"
    with pytest.raises(BridgeError, match="emergencia"):
        b.takeoff(Command("takeoff", "drone1"))
    b.close()


def test_conexion_rechaza_drones_juntos(monkeypatch):
    b = build_backend(args())
    d2 = b.drones["drone2"]
    d2._pose = (0.0, 0.1, 0.05)  # a 10 cm del Dron 1
    with pytest.raises(BridgeError, match="separacion"):
        b.connect(lambda *a: None)
