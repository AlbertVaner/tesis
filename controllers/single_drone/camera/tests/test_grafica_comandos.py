"""Gráfica de tiempo contra comandos: que cuente la verdad de la sesión.

Sin cámara, sin radio y sin ventana. Lo que se comprueba:

* que los frames consecutivos con el mismo comando formen un solo tramo y
  que un cambio lo corte donde toca;
* que un comando sin confirmar no se funda con el mismo comando confirmado;
* que las filas sigan el orden fijo del vocabulario;
* que la figura se guarde en `results/graphs/<controlador>/<fecha>/` y que
  sin muestras no se cree nada.

Uso, desde la raíz del repositorio:

    .\\.venv\\Scripts\\python.exe -m pytest -q .\\controllers\\single_drone\\camera\\tests\\test_grafica_comandos.py
"""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
CAMERA_DIR = TESTS_DIR.parent
if str(CAMERA_DIR) not in sys.path:
    sys.path.insert(0, str(CAMERA_DIR))

import grafica_comandos as gc  # noqa: E402

TOL = 1e-9


def muestras(secuencia, dt=0.1, estado="VOLANDO") -> list[gc.Muestra]:
    """`secuencia`: lista de `(comando, confirmado)`, una por frame."""
    return [gc.Muestra(i * dt, c, conf, estado)
            for i, (c, conf) in enumerate(secuencia)]


# ------------------------------------------------------------------- tramos


def test_los_frames_consecutivos_se_funden_en_un_tramo() -> None:
    ms = muestras([("REPOSO", True)] * 3 + [("ADELANTE", True)] * 5
                  + [("REPOSO", True)] * 2)
    tr = gc.tramos_de_comando(ms)
    assert len(tr) == 3, f"tres rachas dan tres tramos: {len(tr)}"
    assert abs(tr[1].inicio - 0.3) < TOL and abs(tr[1].fin - 0.8) < TOL, \
        f"ADELANTE empieza en 0.3 s y termina en 0.8 s: {tr[1].inicio:.2f}-{tr[1].fin:.2f}"
    assert abs(tr[2].fin - 1.0) < TOL, \
        f"el ultimo tramo dura hasta t_final + intervalo mediano: fin {tr[2].fin:.3f}"


def test_confirmado_y_sin_confirmar_no_se_mezclan() -> None:
    ms = muestras([("ADELANTE", False)] * 4 + [("ADELANTE", True)] * 4)
    tr = gc.tramos_de_comando(ms)
    assert len(tr) == 2 and not tr[0].confirmado and tr[1].confirmado, (
        "el mismo comando se parte al confirmarse: "
        f"{[(t.confirmado, round(t.duracion, 2)) for t in tr]}"
    )


def test_una_sola_muestra_dura_un_frame() -> None:
    tr = gc.tramos_de_comando(muestras([("STOP", True)]))
    assert len(tr) == 1 and abs(tr[0].duracion - gc.DT_POR_DEFECTO_S) < TOL, \
        "una muestra sola dura DT_POR_DEFECTO_S"


def test_sin_muestras_no_hay_tramos() -> None:
    assert gc.tramos_de_comando([]) == [], "sin muestras no hay tramos"


def test_el_tiempo_por_comando_suma_sus_tramos() -> None:
    ms = muestras([("A", True)] * 2 + [("B", True)] * 3 + [("A", True)] * 5)
    total = gc.tiempo_por_comando(ms)
    assert abs(total["A"] - 0.7) < TOL, f"A suma sus dos rachas: {total}"
    assert abs(total["B"] - 0.3) < TOL, f"B suma la suya: {total}"


def test_las_filas_siguen_el_orden_del_vocabulario() -> None:
    filas = gc.orden_de_filas({"STOP", "ADELANTE", "RARO", "NO_GESTURE"})
    assert filas == ["NO_GESTURE", "ADELANTE", "STOP", "RARO"], \
        f"orden fijo y lo desconocido al final: {filas}"


# ------------------------------------------------------------------ guardado


def test_sin_muestras_no_se_guarda_nada() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        g = gc.GraficaDeComandos("prueba", sesion="sesion_x", raiz=tmp)
        ruta = g.guardar()
        assert ruta is None and not (Path(tmp) / "results").exists(), \
            "sin muestras devuelve None y no crea carpetas"


def test_inactiva_no_registra_ni_guarda() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        g = gc.GraficaDeComandos("prueba", raiz=tmp, activo=False)
        g.anotar(0.0, "STOP")
        g.evento(0.0, "x")
        assert g.muestras == [] and g.eventos == [] and g.guardar() is None, \
            "--sin-grafica: nada registrado, nada guardado"


def test_la_figura_se_guarda_en_su_carpeta() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        g = gc.GraficaDeComandos("control_prueba", sesion="sesion_000000",
                                 raiz=tmp)
        for i in range(60):
            comando = "ADELANTE" if 15 <= i < 35 else "NO_GESTURE"
            estado = "EN TIERRA" if i < 5 else "MANIOBRANDO" if i < 12 else "VOLANDO"
            g.anotar(i * 0.05, comando, confirmado=i >= 20, estado=estado)
        g.evento(2.4, "EMERGENCIA (prueba)")
        ruta = g.guardar()

        esperada = (Path(tmp) / "results" / "graphs" / "control_prueba"
                    / datetime.now().strftime("%Y-%m-%d"))
        assert ruta is not None and ruta.parent == esperada, \
            f"se guarda en results/graphs/<controlador>/<fecha>/: {ruta}"
        assert ruta is not None and ruta.name == "sesion_000000_comandos.png", \
            "el archivo lleva la etiqueta de sesion"
        assert ruta is not None and ruta.with_suffix(".pdf").exists(), \
            "tambien en PDF"
        assert ruta is not None and ruta.stat().st_size > 5_000, \
            f"el PNG tiene contenido: {ruta.stat().st_size if ruta else 0} bytes"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
