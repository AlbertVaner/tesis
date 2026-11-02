"""`resolve_dual_uris` con otro segundo dron: el Dron 3 en la antena del Dron 2."""

from __future__ import annotations

import radios


def test_el_segundo_enlace_se_puede_elegir(monkeypatch):
    monkeypatch.setattr(radios, "connected_radios", lambda: ["9DD2507072", "2B1D933FCC"])
    assert radios.resolve_dual_uris(None, None) == (
        "radio://2B1D933FCC/84/2M/E7E7E7E7E4", "radio://9DD2507072/90/2M/E7E7E7E7E5")
    assert radios.resolve_dual_uris(None, None, link2=radios.DRONE_3_LINK) == (
        "radio://2B1D933FCC/84/2M/E7E7E7E7E4", "radio://9DD2507072/90/2M/E7E7E7E7E6")


def test_sin_el_dron_1_el_dron_3_toma_su_antena(monkeypatch):
    monkeypatch.setattr(radios, "connected_radios", lambda: ["9DD2507072", "2B1D933FCC"])
    assert radios.resolve_dual_uris(None, None, link1=radios.DRONE_3_LINK,
                                    link2=radios.DRONE_2_LINK) == (
        "radio://2B1D933FCC/90/2M/E7E7E7E7E6", "radio://9DD2507072/90/2M/E7E7E7E7E5")


def test_sin_seriales_y_con_dos_antenas_usa_los_indices(monkeypatch):

    import cflib.drivers.crazyradio as cr

    def falla():
        raise ValueError("The device has no langid")

    monkeypatch.setattr(radios, "connected_radios", falla)
    monkeypatch.setattr(cr, "_find_devices", lambda: iter([object(), object()]))
    assert radios.resolve_dual_uris(None, None, link2=radios.DRONE_3_LINK) == (
        "radio://0/84/2M/E7E7E7E7E4", "radio://1/90/2M/E7E7E7E7E6")

    monkeypatch.setattr(cr, "_find_devices", lambda: iter([object()]))
    import pytest
    with pytest.raises(ValueError, match="langid"):
        radios.resolve_dual_uris(None, None)
