"""`MocapFeed` sin broker: parseo, duplicados, velocidad y estadísticas."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # controllers/shared

import mocap_feed  # noqa: E402
from mocap_feed import Frame, MocapFeed, parse_message, quaternion_yaw_deg  # noqa: E402


def mensaje(x: float, y: float, z: float, *, yaw_deg: float | None = 0.0, ts: str | None = None) -> bytes:
    pose: dict = {"position": {"x": x, "y": y, "z": z}}
    if yaw_deg is not None:
        half = math.radians(yaw_deg) / 2.0
        pose["rotation"] = {"x": 0.0, "y": 0.0, "z": math.sin(half), "w": math.cos(half)}
    data = {"payload": {"pose": pose}}
    if ts is not None:
        data["ts"] = ts
    return json.dumps(data).encode("utf-8")


def frame(x: float, y: float, z: float, t: float) -> Frame:
    return Frame(x, y, z, None, None, t, None)


class TestParse:
    def test_posicion_y_rumbo(self):
        f = parse_message(mensaje(0.1, -0.2, 0.3, yaw_deg=95.0), 10.0)
        assert f.xyz() == pytest.approx((0.1, -0.2, 0.3))
        assert f.yaw_deg == pytest.approx(95.0, abs=1e-6)
        assert f.quat is not None
        assert f.received_at == 10.0

    def test_sin_rotacion(self):
        f = parse_message(mensaje(0.0, 0.0, 0.0, yaw_deg=None), 1.0)
        assert f.quat is None and f.yaw_deg is None

    def test_formato_pld_y_orientation_con_q(self):
        raw = {"pld": {"pose": {"position": {"x": 1, "y": 2, "z": 3},
                                "orientation": {"qx": 0, "qy": 0, "qz": 0, "qw": 1}}}}
        f = parse_message(raw, 0.0)
        assert f.xyz() == (1.0, 2.0, 3.0)
        assert f.yaw_deg == pytest.approx(0.0)

    def test_latencia_desde_ts(self):
        f = parse_message(mensaje(0, 0, 0, ts="2000-01-01T00:00:00Z"), 0.0)
        assert f.source_latency_s is not None and f.source_latency_s > 1e8

    @pytest.mark.parametrize("raw", [b"[]", b"{}", b'{"payload": {"pose": {"position": {"x": "nan", "y": 0, "z": 0}}}}'])
    def test_mensajes_invalidos(self, raw):
        with pytest.raises((KeyError, ValueError, TypeError)):
            parse_message(raw, 0.0)

    def test_yaw_de_cuaternion(self):
        assert quaternion_yaw_deg(0, 0, 0, 1) == pytest.approx(0.0)
        assert quaternion_yaw_deg(0, 0, 1, 0) == pytest.approx(180.0)
        with pytest.raises(ValueError):
            quaternion_yaw_deg(0, 0, 0, 0)


class TestDuplicados:
    def test_rafaga_del_puente_cuenta_una_vez(self):
        recibidos: list[Frame] = []
        feed = MocapFeed("mocap/drone3", recibidos.append)
        assert feed.push(frame(0.0, 0.0, 0.0, 0.000))
        # tres copias con 0.1 mm de diferencia, 1 ms despues
        for k in range(1, 4):
            assert not feed.push(frame(0.0001 * k * 0.5, 0.0, 0.0, 0.001 * k))
        assert feed.push(frame(0.0002, 0.0, 0.0, 0.050))
        assert feed.frames == 2 and feed.duplicates == 3
        assert len(recibidos) == 2

    def test_dron_quieto_no_pierde_frames(self):
        """Con ruido de decimas de milimetro a 20 Hz todos los frames pasan."""
        feed = MocapFeed("t")
        for k in range(40):
            assert feed.push(frame(0.0001 * (k % 2), 0.0, 0.0, 0.05 * k))
        assert feed.frames == 40 and feed.duplicates == 0

    def test_salto_grande_en_la_misma_rafaga_es_nuevo(self):
        feed = MocapFeed("t")
        feed.push(frame(0.0, 0.0, 0.0, 0.0))
        assert feed.push(frame(0.01, 0.0, 0.0, 0.001))

    def test_callback_fuera_del_lock(self):
        feed = MocapFeed("t")
        feed.on_frame = lambda f: feed.stats()  # tomaria el lock: no debe bloquear
        assert feed.push(frame(0.0, 0.0, 0.0, 0.0))


class TestVelocidadYEstadisticas:
    def test_velocidad_filtrada(self):
        feed = MocapFeed("t")
        feed.push(frame(0.0, 0.0, 0.0, 0.00))
        feed.push(frame(0.05, 0.0, 0.0, 0.05))  # 1 m/s
        assert feed.velocity == pytest.approx((1.0, 0.0, 0.0))
        feed.push(frame(0.10, 0.0, 0.0, 0.10))
        assert feed.velocity == pytest.approx((1.0, 0.0, 0.0))

    def test_velocidad_nula_tras_hueco(self):
        feed = MocapFeed("t")
        feed.push(frame(0.0, 0.0, 0.0, 0.0))
        feed.push(frame(0.05, 0.0, 0.0, 0.05))
        feed.push(frame(0.10, 0.0, 0.0, 1.00))
        assert feed.velocity is None

    def test_frames_hz_y_hueco(self, monkeypatch):
        feed = MocapFeed("t")
        t = 0.0
        for k in range(10):
            t = k * 0.05
            feed.push(frame(0.01 * k, 0.0, 0.0, t))
        t = 0.45 + 0.30  # un hueco de 300 ms
        feed.push(frame(0.5, 0.0, 0.0, t))
        monkeypatch.setattr(mocap_feed, "ahora", lambda: t)
        stats = feed.stats(window_s=3.0)
        assert stats["frames"] == 11
        assert stats["hueco_max_s"] == pytest.approx(0.30)
        assert stats["frames_hz"] == pytest.approx(10 / 0.75)

    def test_fresh_y_edad(self, monkeypatch):
        feed = MocapFeed("t")
        assert feed.fresh() is None and feed.age_s() is None
        feed.push(frame(0.0, 0.0, 0.0, 100.0))
        monkeypatch.setattr(mocap_feed, "ahora", lambda: 100.2)
        assert feed.fresh() is not None
        monkeypatch.setattr(mocap_feed, "ahora", lambda: 101.0)
        assert feed.fresh() is None
        assert feed.age_s() == pytest.approx(1.0)


def test_roll_pitch_del_cuaternion():
    f = parse_message(mensaje(0, 0, 0, yaw_deg=30.0), 0.0)
    assert (f.roll_deg, f.pitch_deg) == pytest.approx((0.0, 0.0), abs=1e-6)
    assert f.yaw_deg == pytest.approx(30.0, abs=1e-6)
    # roll de 90 grados: (sin 45, 0, 0, cos 45)
    raw = {"payload": {"pose": {"position": {"x": 0, "y": 0, "z": 0},
                                "rotation": {"x": math.sin(math.pi / 4), "y": 0, "z": 0, "w": math.cos(math.pi / 4)}}}}
    f = parse_message(raw, 0.0)
    assert f.roll_deg == pytest.approx(90.0, abs=1e-6)


class TestCongelado:
    def test_pose_repetida_se_declara_congelada(self, monkeypatch):
        feed = MocapFeed("t")
        for k in range(25):  # 1 s con la misma posicion exacta
            feed.push(frame(0.723, -0.202, 0.117, 0.04 * k))
        assert feed.frozen()
        monkeypatch.setattr(mocap_feed, "ahora", lambda: 1.0)
        assert feed.fresh() is None
        assert feed.stats()["congelado"] is True

    def test_ruido_normal_no_es_congelado(self, monkeypatch):
        feed = MocapFeed("t")
        for k in range(20):
            feed.push(frame(0.723 + 0.0002 * (k % 3), -0.202, 0.117, 0.04 * k))
        assert not feed.frozen()
        monkeypatch.setattr(mocap_feed, "ahora", lambda: 0.8)
        assert feed.fresh() is not None

    def test_se_descongela_al_cambiar(self):
        feed = MocapFeed("t")
        for k in range(25):
            feed.push(frame(0.5, 0.5, 0.1, 0.04 * k))
        assert feed.frozen()
        feed.push(frame(0.9, -0.3, 0.4, 1.04))
        assert not feed.frozen()


def test_identificador_del_rigid_body():
    raw = {"identifier": "84", "payload": {"pose": {"position": {"x": 0, "y": 0, "z": 0}}}}
    assert parse_message(raw, 0.0).identifier == "84"
    raw = {"pid": 84, "pld": {"pose": {"position": {"x": 0, "y": 0, "z": 0}}}}
    assert parse_message(raw, 0.0).identifier == "84"
    assert parse_message(mensaje(0, 0, 0), 0.0).identifier is None
