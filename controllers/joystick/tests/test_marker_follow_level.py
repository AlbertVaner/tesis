"""Ancla del seguidor a la altura del marker (`activate(level=True)`)."""

from __future__ import annotations

import math
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import marker_follow as mf  # noqa: E402


class ReceptorFalso:
    def __init__(self, pose):
        self.pose = pose
        self.error = None

    def snapshot(self):
        return self.pose

    def start(self):
        pass

    def stop(self):
        pass


def pose(x, y, z):
    return SimpleNamespace(x=x, y=y, z=z, age_s=0.0)


def seguidor(marker):
    return mf.CameraMarkerFollower(receiver_factory=lambda *a, **k: ReceptorFalso(marker))


def test_ancla_nivelada_ignora_la_altura_del_dron():
    s = seguidor(pose(0.0, 0.0, 1.0))
    s.activate(("drone2",), {"drone2": (0.3, 0.4, 0.4)}, level=True)  # dron 0.6 m mas bajo
    ox, oy, oz = s.offsets["drone2"]
    assert oz == 0.0
    assert math.hypot(ox, oy) == pytest.approx(mf.FOLLOW_RADIUS_M)
    assert (ox, oy) == pytest.approx((0.3 * mf.FOLLOW_RADIUS_M / 0.5, 0.4 * mf.FOLLOW_RADIUS_M / 0.5))
    assert s.desired("drone2")[2] == pytest.approx(1.0)


def test_ancla_nivelada_con_dron_encima_del_marker():
    s = seguidor(pose(1.0, 1.0, 0.5))
    s.activate(("drone2",), {"drone2": (1.0, 1.0, 1.2)}, level=True)
    assert s.offsets["drone2"] == (mf.FOLLOW_RADIUS_M, 0.0, 0.0)


def test_ancla_tridimensional_sigue_igual():
    s = seguidor(pose(0.0, 0.0, 1.0))
    s.activate(("drone2",), {"drone2": (0.0, 0.0, 0.4)})
    assert s.offsets["drone2"] == pytest.approx((0.0, 0.0, -mf.FOLLOW_RADIUS_M))


def test_marker_position():
    s = seguidor(pose(0.3, -0.2, 0.9))
    assert s.marker_position() == (0.3, -0.2, 0.9)
    viejo = pose(0.0, 0.0, 0.0)
    viejo.age_s = 5.0
    with pytest.raises(mf.FollowUnavailable):
        seguidor(viejo).marker_position()


def test_el_radio_de_seguimiento_se_puede_ampliar():
    s = mf.CameraMarkerFollower(receiver_factory=lambda *a, **k: ReceptorFalso(pose(0.0, 0.0, 1.0)),
                                follow_radius_m=0.80)
    s.activate(("drone2",), {"drone2": (0.3, 0.4, 0.4)}, level=True)
    ox, oy, _ = s.offsets["drone2"]
    assert math.hypot(ox, oy) == pytest.approx(0.80)
