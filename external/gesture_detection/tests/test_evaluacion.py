r"""Como se mide el reconocedor: metricas por clase y validacion anidada.

Sin camara, sin MediaPipe y sin dataset. Se construyen matrices de distancias
a mano para comprobar lo que decide si una cifra es publicable o no:

* que la precision y la exhaustividad separen lo que la exactitud junta;
* que la F1 de una clase minoritaria no se salve porque la mayoritaria acierte;
* que el umbral de la validacion anidada se mida **sin** la persona evaluada,
  que es lo unico que evita reportar una cifra optimista;
* que rechazar sea una salida del sistema y aparezca en la matriz.

Uso, desde la raiz del repositorio:

    .\.venv\Scripts\python.exe -m pytest -q .\external\gesture_detection\tests\test_evaluacion.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

TESTS_DIR = Path(__file__).resolve().parent
GESTURE_DIR = TESTS_DIR.parent
if str(GESTURE_DIR) not in sys.path:
    sys.path.insert(0, str(GESTURE_DIR))

from recognition.evaluacion import (  # noqa: E402
    RECHAZADO,
    formato_matriz,
    formato_metricas,
    guardar_csv,
    loso,
    loso_anidado,
    macro_f1,
    matriz_confusion,
    metricas_por_clase,
    umbrales_por_clase,
)


def por_estilo(etiquetas: list[str], personas: list[str]) -> np.ndarray:
    """Distancias de un dataset donde pesa mas el estilo de cada persona que el
    gesto: dos tomas de la misma persona se parecen aunque sean gestos
    distintos, y entre personas el vecino mas cercano es del gesto equivocado.
    """
    n = len(etiquetas)
    D = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            mismo_gesto = etiquetas[i] == etiquetas[j]
            if personas[i] == personas[j]:
                D[i, j] = 0.1 if mismo_gesto else 0.3
            else:
                D[i, j] = 0.8 if mismo_gesto else 0.5
    return D


# --------------------------------------------------------------- metricas


def test_la_exactitud_esconde_lo_que_la_f1_dice() -> None:
    """Nueve tomas de una clase y una de otra: ignorar la minoritaria da 90 %
    de exactitud y F1 cero en la clase que importa."""
    reales = ["comun"] * 9 + ["raro"]
    predichas = ["comun"] * 10
    m = {x["clase"]: x for x in metricas_por_clase(reales, predichas)}
    assert m["raro"]["f1"] == 0.0 and m["comun"]["exhaustividad"] == 1.0, \
        f"la clase minoritaria ignorada tiene F1 0: {m['raro']['f1']:.2f}"
    assert macro_f1(list(m.values())) < 0.6, \
        f"la macro-F1 no premia ignorar la minoritaria: {macro_f1(list(m.values())):.2f}"


def test_precision_y_exhaustividad_no_son_lo_mismo() -> None:
    """Un clasificador que dispara de mas: recuerda todo y acierta poco."""
    reales = ["gesto", "otro", "otro", "otro"]
    predichas = ["gesto", "gesto", "gesto", "otro"]
    m = {x["clase"]: x for x in metricas_por_clase(reales, predichas)}
    assert m["gesto"]["exhaustividad"] == 1.0 and m["gesto"]["precision"] < 0.4, \
        (f"exhaustividad {m['gesto']['exhaustividad']:.2f} contra precision "
         f"{m['gesto']['precision']:.2f}")


def test_no_emitir_nada_es_una_salida_de_la_matriz() -> None:
    clases, conteos = matriz_confusion(["a", None], [None, None])
    assert RECHAZADO in clases and conteos["a"][RECHAZADO] == 1, \
        f"el rechazo aparece como clase: {clases}"


def test_una_clase_nunca_predicha_no_rompe_la_precision() -> None:
    m = {x["clase"]: x for x in metricas_por_clase(["a", "b"], ["a", "a"])}
    assert not np.isfinite(m["b"]["precision"]) and m["b"]["f1"] == 0.0, \
        "sin predicciones de una clase la precision es indefinida, no cero"


# ------------------------------------------------------------------ LOSO


def test_loso_no_se_apoya_en_la_propia_persona() -> None:
    """La diferencia entre medir repetibilidad y medir generalizacion.

    Sobre un dataset donde pesa el estilo de cada persona, dejar fuera solo la
    propia toma da el 100 % —cada toma tiene de vecina otra suya— y dejar
    fuera a la persona entera da 0 %. La primera cifra no dice nada sobre
    alguien que no aporto plantillas.
    """
    etiquetas = ["a", "a", "b", "b"] * 2
    personas = ["p1"] * 4 + ["p2"] * 4
    D = por_estilo(etiquetas, personas)

    propia_toma = sum(
        etiquetas[min((j for j in range(len(D)) if j != i),
                      key=lambda k: D[i, k])] == etiquetas[i]
        for i in range(len(D))) / len(D)
    assert propia_toma == 1.0, \
        f"dejando fuera solo la propia toma, sale perfecto: {propia_toma:.2f}"

    r = loso(D, etiquetas, personas)
    assert r["exactitud"] == 0.0, (
        "dejando fuera a la persona, parecerse a uno mismo no ayuda: "
        f"exactitud {r['exactitud']:.2f}")


def test_el_umbral_anidado_no_ve_a_la_persona_evaluada() -> None:
    """El umbral de cada pliegue sale solo de las demas personas."""
    etiquetas = ["a", "a", "b", "b", "a", "a", "b", "b"]
    personas = ["p1"] * 4 + ["p2"] * 4
    n = len(etiquetas)
    D = np.full((n, n), 0.9)
    for i in range(n):
        for j in range(n):
            if i != j and etiquetas[i] == etiquetas[j]:
                D[i, j] = 0.2
        D[i, i] = 0.0
    r = loso_anidado(D, etiquetas, personas)
    assert set(r["umbrales"]) == {"p1", "p2"}, \
        f"un umbral por persona: {sorted(r['umbrales'])}"
    assert r["exactitud"] == 1.0 and r["evaluadas"] == n, \
        f"con clases separadas acierta todo: {r['exactitud']:.2f}"


def test_la_validacion_anidada_no_supera_a_la_normal() -> None:
    """La cifra honesta no puede salir mejor que la que eligio su propio
    umbral: si sale, el anidado no esta dejando fuera lo que dice."""
    rng = np.random.default_rng(0)
    etiquetas = [g for g in ("a", "b", "c") for _ in range(6)]
    personas = [f"p{k % 3}" for k in range(len(etiquetas))]
    n = len(etiquetas)
    D = rng.uniform(0.4, 1.0, (n, n))
    D = (D + D.T) / 2
    for i in range(n):
        D[i, i] = 0.0
        for j in range(n):
            if i != j and etiquetas[i] == etiquetas[j]:
                D[i, j] = D[j, i] = rng.uniform(0.1, 0.5)
    normal = loso(D, etiquetas, personas)
    anidado = loso_anidado(D, etiquetas, personas)
    assert anidado["exactitud"] <= normal["exactitud"] + 1e-9, (
        f"la cifra honesta no supera a la optimista: anidada "
        f"{anidado['exactitud']:.2f} contra {normal['exactitud']:.2f}")


def test_la_clase_de_rechazo_se_lee_como_no_emitir_nada() -> None:
    """Leer material ajeno y pasarse del umbral son la misma salida: silencio."""
    etiquetas = ["a", "a", "otro", "otro", "a", "a", "otro", "otro"]
    personas = ["p1"] * 4 + ["p2"] * 4
    n = len(etiquetas)
    D = np.full((n, n), 0.9)
    for i in range(n):
        for j in range(n):
            if i != j and etiquetas[i] == etiquetas[j]:
                D[i, j] = 0.2
        D[i, i] = 0.0
    r = loso_anidado(D, etiquetas, personas, rechazo="otro")
    ajenas = [k for k in range(n) if etiquetas[k] == "otro"]
    assert all(r["predichas"][k] is None for k in ajenas), \
        "una toma ajena bien clasificada no emite comando"
    assert all(r["reales"][k] is None for k in ajenas), \
        "lo correcto para una toma ajena es no emitir nada"
    assert "otro" not in {x["clase"] for x in
                          metricas_por_clase(r["reales"], r["predichas"])}, \
        "el rechazo no se lista como un comando mas"


def test_cada_gesto_recibe_el_umbral_que_su_material_pide() -> None:
    """Un gesto estable y uno variable no aguantan el mismo numero.

    `estable` se lee siempre cerca; `variable` acierta lejos. Un umbral unico
    tendria que elegir entre cortar al variable o dejar pasar basura al
    estable; dos umbrales no tienen que elegir.
    """
    dist =    [0.1, 0.1, 0.1, 0.9, 0.9, 0.9, 0.6, 0.6, 0.6, 1.4, 1.4, 1.4]
    leidas =  ["estable"] * 6 + ["variable"] * 6
    ciertas = ["estable"] * 3 + ["x", "y", "z"] + ["variable"] * 3 + ["x", "y", "z"]
    u = umbrales_por_clase(dist, leidas, ciertas, respaldo=0.5)
    assert u["estable"] < u["variable"], \
        f"el gesto variable pide mas margen: {u['estable']:.2f} vs {u['variable']:.2f}"
    assert 0.1 < u["estable"] < 0.9 and 0.6 < u["variable"] < 1.4, \
        f"cada umbral cae entre sus dos poblaciones: {u}"


def test_sin_material_suficiente_se_usa_el_umbral_global() -> None:
    """Un umbral sacado de dos distancias es ruido; mejor el global."""
    u = umbrales_por_clase([0.2, 0.8], ["a", "a"], ["a", "b"], respaldo=0.5)
    assert u["a"] == 0.5, f"cae al global: {u['a']}"


def test_el_umbral_por_gesto_tampoco_ve_a_la_persona_evaluada() -> None:
    """La cifra por gesto sigue siendo honesta: los umbrales de cada pliegue
    se miden dentro del pliegue, uno por persona y por gesto."""
    etiquetas = ["a", "a", "b", "b"] * 3
    personas = [f"p{k // 4}" for k in range(len(etiquetas))]
    n = len(etiquetas)
    D = np.full((n, n), 0.9)
    for i in range(n):
        for j in range(n):
            if i != j and etiquetas[i] == etiquetas[j]:
                D[i, j] = 0.2
        D[i, i] = 0.0
    r = loso_anidado(D, etiquetas, personas, por_clase=True)
    assert set(r["umbrales_clase"]) == {"p0", "p1", "p2"}, \
        f"un juego de umbrales por persona: {sorted(r['umbrales_clase'])}"
    assert r["exactitud"] == 1.0, f"acierta todo: {r['exactitud']:.2f}"


def test_sin_por_clase_no_hay_umbrales_por_gesto() -> None:
    D = np.full((4, 4), 0.5)
    r = loso_anidado(D, ["a", "b", "a", "b"], ["p1", "p1", "p2", "p2"])
    assert r["umbrales_clase"] == {}, \
        "el umbral por gesto no se calcula si no se pide"


def test_una_sola_persona_no_se_puede_evaluar() -> None:
    """Sin una segunda persona no hay banco ajeno, y no hay nada que medir."""
    D = np.zeros((3, 3))
    r = loso_anidado(D, ["a", "a", "a"], ["p1"] * 3)
    assert r["evaluadas"] == 0 and r["exactitud"] == 0.0, \
        f"con una persona no se evalua nada: {r['evaluadas']} tomas"


# --------------------------------------------------------------- reporte


def test_el_reporte_queda_en_disco(tmp_path: Path) -> None:
    reales = ["a", "b", None]
    predichas = ["a", "a", None]
    rutas = guardar_csv(tmp_path, reales, predichas, extra={"acierto": 0.667})
    assert all(r.exists() for r in rutas) and len(rutas) == 3, \
        f"tres archivos: {[r.name for r in rutas]}"
    texto = (tmp_path / "matriz_confusion.csv").read_text(encoding="utf-8")
    assert RECHAZADO in texto, "el rechazo entra en el CSV"


def test_las_tablas_se_imprimen_alineadas() -> None:
    reales = ["a", "b", None]
    predichas = ["a", "a", None]
    lineas = formato_matriz(reales, predichas).splitlines()
    assert len({len(x) for x in lineas}) == 1, \
        "todas las filas de la matriz miden lo mismo"
    assert "macro-F1" in formato_metricas(metricas_por_clase(reales, predichas))


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
