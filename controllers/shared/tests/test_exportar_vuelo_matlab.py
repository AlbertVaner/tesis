r"""Exportacion de un vuelo a .mat: drones en la misma linea de tiempo, gestos y marker 65.

Uso, desde la raiz del repositorio::

    .\.venv\Scripts\python.exe -m pytest -q .\controllers\shared\tests\test_exportar_vuelo_matlab.py
"""

from __future__ import annotations

import csv
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

SHARED_DIR = Path(__file__).resolve().parents[1]
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))

import dron_robotat as dr  # noqa: E402
import exportar_vuelo_matlab as ex  # noqa: E402

INICIO = datetime(2026, 10, 28, 15, 0, 0).timestamp()


def _csv_dron(carpeta: Path, nombre: str, arranque_s: float, x: float, *, con_t_unix=True, hueco=None):
    """Un dron que arranca `arranque_s` despues de INICIO y sube en x a 1 m/s."""
    marca = datetime.fromtimestamp(INICIO + int(arranque_s)).strftime("%Y%m%d_%H%M%S")
    ruta = carpeta / f"dron_robotat_{nombre}_{marca}.csv"
    columnas = dr.CSV_COLUMNS if con_t_unix else [c for c in dr.CSV_COLUMNS if c != "t_unix"]
    with ruta.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columnas)
        w.writeheader()
        w.writerow({c: "" for c in columnas} | {"t_s": 0.0, "evento": "DESPEGUE", "modo": "LISTO"}
                   | ({"t_unix": INICIO + arranque_s} if con_t_unix else {}))
        for i in range(1, 101):
            t = i * 0.1
            fila = {c: "" for c in columnas} | {"t_s": t, "modo": "VUELO", "mocap_x": x + t,
                                                "mocap_y": 0.0, "mocap_z": 0.5, "mocap_yaw_deg": 90.0}
            if hueco and hueco[0] <= t <= hueco[1]:
                fila |= {"mocap_x": "", "mocap_y": "", "mocap_z": ""}
            if con_t_unix:
                fila["t_unix"] = INICIO + arranque_s + t
            w.writerow(fila)
    return ruta


def _csv_gestos(carpeta: Path) -> Path:
    ruta = carpeta / "sesion_150001.csv"
    with ruta.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["t_s", "t_unix", "gesto", "confirmado", "modo", "comportamiento", "estado",
                    "marker_x", "marker_y", "marker_z", "novedad"])
        for i in range(60):
            t = 1.0 + i * 0.1
            w.writerow([t, INICIO + t, "ARRIBA" if i > 20 else "NO_GESTURE", int(i > 25), "estatico",
                        "SEGUIR" if i > 40 else "hover", "VOLANDO", 2.0, 1.0, 1.5,
                        "ven_aca -> SEGUIR" if i == 40 else ""])
    return ruta


def test_tres_drones_quedan_en_la_misma_linea_de_tiempo(tmp_path):
    rutas = [_csv_dron(tmp_path, "Dron1", 0, 0.0), _csv_dron(tmp_path, "Dron2", 5, 10.0),
             _csv_dron(tmp_path, "Dron3", 14, 20.0)]
    _csv_dron(tmp_path, "Dron1", 300, 0.0)                     # otra sesion: no se junta
    assert ex.drones_de_la_sesion(rutas[1]) == rutas
    drones = [ex.leer_dron(p, []) for p in rutas]
    vuelo = ex.construir(drones, None)
    r = vuelo["rejilla"]
    assert r["pos"].shape[1:] == (3, 3)
    # El Dron 2 arranco 5 s despues en x=10: en el mismo instante va 5 m por delante.
    # A los 9 s el Dron 3 (arranca a los 14 s) aun no tiene datos.
    i = np.argmin(np.abs(r["t"] - 9.0))
    assert r["pos"][i, 0, 1] - r["pos"][i, 0, 0] == pytest.approx(5.0, abs=0.05)
    assert np.isnan(r["pos"][i, 0, 2])


def test_sin_t_unix_usa_la_hora_del_nombre_y_avisa(tmp_path):
    avisos: list[str] = []
    d = ex.leer_dron(_csv_dron(tmp_path, "Dron1", 3, 0.0, con_t_unix=False), avisos)
    assert d["t_unix"][0] == pytest.approx(INICIO + 3.1)
    assert avisos and "1 s" in avisos[0]


def test_un_hueco_de_mocap_largo_no_se_inventa(tmp_path):
    d = ex.leer_dron(_csv_dron(tmp_path, "Dron1", 0, 0.0, hueco=(3.0, 5.0)), [])
    r = ex.construir([d], None)["rejilla"]
    t = r["t"]
    assert np.isnan(r["pos"][np.argmin(np.abs(t - 4.0)), 0, 0])
    assert np.isfinite(r["pos"][np.argmin(np.abs(t - 6.0)), 0, 0])


def test_gestos_marker_65_y_ordenes_en_la_rejilla(tmp_path):
    dia = tmp_path / "gestos" / "2026-10-28"
    dia.mkdir(parents=True)
    d = ex.leer_dron(_csv_dron(tmp_path, "Dron1", 0, 0.0), [])
    g = ex.leer_gestos(_csv_gestos(dia), [])
    r = ex.construir([d], g)["rejilla"]
    t = r["t"]

    def en(s):
        return np.argmin(np.abs(t - s))

    assert list(r["marker"][en(4.0)]) == pytest.approx([2.0, 1.0, 1.5])
    assert r["gesto"][en(3.3)] == "ARRIBA?"                     # visto, aun sin confirmar
    assert r["gesto"][en(4.0)] == "ARRIBA"
    assert r["comportamiento"][en(5.5)] == "SEGUIR"
    assert r["orden"][en(5.5)] == "ven_aca -> SEGUIR"
    assert r["orden"][en(5.0 + ex.ORDEN_VISIBLE_S + 0.5)] == ""


def test_el_mat_se_lee_con_scipy(tmp_path):
    scipy_io = pytest.importorskip("scipy.io")
    d = ex.leer_dron(_csv_dron(tmp_path, "Dron1", 0, 0.0), [])
    ruta = ex.guardar(ex.construir([d], None), tmp_path / "vuelo.mat")
    vuelo = scipy_io.loadmat(ruta, simplify_cells=True)["vuelo"]
    assert vuelo["rejilla"]["nombres"] == "Dron1"
    assert len(vuelo["rejilla"]["t"]) == len(vuelo["rejilla"]["gesto"])
    assert "DESPEGUE" in vuelo["drones"]["Dron1"]["eventos"]["evento"]
