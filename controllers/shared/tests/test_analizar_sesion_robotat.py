"""El analizador produce las gráficas PDF y el resumen a partir de un CSV real o sintético."""

from __future__ import annotations

import csv
import math
import sys

import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # controllers/shared

import analizar_sesion_robotat as an  # noqa: E402
import dron_robotat as dr  # noqa: E402


def csv_sintetico(path: Path) -> Path:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=dr.CSV_COLUMNS)
        writer.writeheader()
        base = {c: "" for c in dr.CSV_COLUMNS}
        writer.writerow(base | {"t_s": 0.0, "evento": "PREFLIGHT_OK", "detalle": "posCtlPid.thrustBase=46000; radio_max_m=1.0", "modo": "PREFLIGHT"})
        writer.writerow(base | {"t_s": 1.0, "evento": "TAKEOFF", "detalle": "z=0.38", "modo": "DESPEGUE", "objetivo_z": 0.38})
        writer.writerow(base | {"t_s": 8.0, "evento": "VEL", "detalle": "ux=+1.00 uy=+0.00 uz=+0.00 uyaw=+0.0 v=0.25", "modo": "FLUIDO"})
        writer.writerow(base | {"t_s": 11.0, "evento": "VEL", "detalle": "ux=+0.00 uy=+0.00 uz=+0.00 uyaw=+0.0 v=0.25", "modo": "FLUIDO"})
        writer.writerow(base | {"t_s": 14.0, "evento": "GO_TO", "detalle": "dx=+0.00 dy=-0.10 dz=+0.00 dyaw=+0 dur=1.0", "modo": "GO_TO"})
        for k in range(200):
            t = 1.0 + 0.1 * k
            z = min(0.38 + 0.05 * math.sin(k / 5), 0.38 + 0.4 * k / 30)
            writer.writerow(base | {
                "t_s": round(t, 2), "modo": "DESPEGUE" if t < 5 else "VUELO",
                "mocap_x": 0.01 * math.sin(k / 7), "mocap_y": 0.01 * math.cos(k / 9), "mocap_z": round(z, 4),
                "ekf_x": 0.0, "ekf_y": 0.0, "ekf_z": round(z - 0.01, 4), "error_ekf_mocap_m": 0.012,
                "objetivo_x": 0.0, "objetivo_y": 0.0, "objetivo_z": 0.38, "objetivo_yaw_deg": 0.0,
                "mocap_frames_hz": 20.0, "mocap_hueco_max_s": 0.06, "mocap_congelado": 0,
                "roll_deg": 0.3, "pitch_deg": -0.2, "bateria_v": round(3.3 - 0.001 * k, 3),
                "empuje_cmd": 45800, "ekf_vx": 0.0, "ekf_vy": 0.0, "ekf_vz": 0.01, "mocap_vz": 0.0,
                "extpos_enviados": k, "ekf_yaw_deg": 1.0, "mocap_yaw_deg": 2.0,
            })
        writer.writerow(base | {"t_s": 21.5, "evento": "LAND", "modo": "ATERRIZAJE"})
        writer.writerow(base | {"t_s": 26.0, "evento": "LANDED", "detalle": "empuje medio en hover 45800", "modo": "EN_TIERRA"})
    return path


def test_genera_pdfs_y_resumen(tmp_path, monkeypatch):
    monkeypatch.setattr(an, "GRAPH_DIR", tmp_path / "graphs")
    fuente = csv_sintetico(tmp_path / "dron_robotat_Dron2_20260916_120000.csv")
    salida = an.analyze_session(fuente)
    assert salida == tmp_path / "graphs" / "2026-09-16" / fuente.stem
    pdfs = sorted(p.name for p in salida.glob("*.pdf"))
    assert pdfs == ["01_altura.pdf", "02_trayectoria_xy.pdf", "03_error_ekf_y_mocap.pdf",
                    "04_bateria_empuje.pdf", "05_velocidades.pdf", "06_actitud.pdf",
                    "07_comandos_y_vuelo.pdf", "08_vuelo_3d.pdf"]
    assert all(p.stat().st_size > 1000 for p in salida.glob("*.pdf"))
    resumen = (salida / "00_resumen.txt").read_text(encoding="utf-8")
    assert "Hover σ x (m)" in resumen and "Empuje medio en hover: 45800" in resumen
    assert "Final: LANDED" in resumen


def test_registro_genera_graficas_al_cerrar(tmp_path, monkeypatch):
    monkeypatch.setattr(an, "GRAPH_DIR", tmp_path / "graphs")
    import csv_session
    monkeypatch.setattr(csv_session, "RESULTS_DIR", tmp_path / "results")
    registro = dr.RegistroRobotat(dr.CSV_COLUMNS, folder_name="dron_robotat", filename_prefix="prueba")
    registro.sincrono = True  # en la prueba se generan aqui mismo
    path = registro.start("prueba_20260916_000000")
    fila = {c: "" for c in dr.CSV_COLUMNS}
    for k in range(30):
        registro.write(fila | {"t_s": 0.1 * k, "modo": "VUELO", "mocap_x": 0, "mocap_y": 0, "mocap_z": 0.4,
                               "objetivo_x": 0, "objetivo_y": 0, "objetivo_z": 0.4, "bateria_v": 3.5})
    registro.stop(generate_graphs=True)
    assert registro.analysis_path is not None and (registro.analysis_path / "01_altura.pdf").exists()


def test_ordenes_de_la_linea_de_tiempo():
    eventos = [
        {"t_s": 1.0, "evento": "TAKEOFF", "detalle": "z=0.38"},
        {"t_s": 8.0, "evento": "VEL", "detalle": "ux=+1.00 uy=+0.00 uz=+0.00 uyaw=+0.0 v=0.25"},
        {"t_s": 11.0, "evento": "VEL", "detalle": "ux=+0.00 uy=+0.00 uz=+0.00 uyaw=+0.0 v=0.25"},
        {"t_s": 14.0, "evento": "GO_TO", "detalle": "dx=+0.00 dy=-0.10 dz=+0.08 dyaw=+20 dur=1.0"},
        {"t_s": 20.0, "evento": "LAND", "detalle": ""},
    ]
    lista = an.ordenes(eventos, 30.0)
    assert lista[0] == (1.0, 5.0, "despegue")
    assert lista[1] == (8.0, 11.0, "+X")
    assert lista[2] == (14.0, 20.0, "−Y ↑ giro ⟲")
    assert lista[3] == (20.0, 24.0, "aterrizar")


def test_vuelo_dual_empareja_sesiones(tmp_path, monkeypatch):
    monkeypatch.setattr(an, "GRAPH_DIR", tmp_path / "graphs")
    a = csv_sintetico(tmp_path / "dron_robotat_Dron1_20260916_193417.csv")
    b = csv_sintetico(tmp_path / "dron_robotat_Dron2_20260916_193423.csv")
    assert an.sesion_hermana(a) == b and an.sesion_hermana(b) == a
    an.analyze_session(a)
    dual = tmp_path / "graphs" / "2026-09-16" / "vuelo_dual_20260916_193417" / "trayectorias_y_separacion.pdf"
    assert dual.exists() and dual.stat().st_size > 1000


def test_ordenes_por_desplazamiento_sin_evento_vel():
    muestras = [{"t_s": 0.1 * k, "mocap_x": 0.0, "mocap_y": -0.02 * k, "mocap_z": 0.4} for k in range(60)]
    eventos = [{"t_s": 1.0, "evento": "FLUIDO_INICIO", "detalle": "v=0.25"},
               {"t_s": 5.0, "evento": "FLUIDO_FIN", "detalle": ""}]
    assert an.ordenes(eventos, 6.0, muestras) == [(1.0, 5.0, "−Y")]


def test_ventana_de_vuelo():
    muestras = [{"t_s": 0.1 * k} for k in range(3000)]
    eventos = [{"t_s": 30.0, "evento": "TAKEOFF"}, {"t_s": 90.0, "evento": "LANDED"}]
    assert an.ventana_de_vuelo(muestras, eventos) == (25.0, 95.0)
    assert an.ventana_de_vuelo(muestras, [])[1] == pytest.approx(299.9)
