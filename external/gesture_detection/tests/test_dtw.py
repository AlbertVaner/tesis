"""Gestos dinamicos: ventana deslizante y comparacion por DTW.

Sin camara y sin MediaPipe. Lo que se verifica es lo que hace util a un
clasificador de secuencias:

* que la ventana sea la misma trayectoria a 15 y a 30 fps;
* que una ventana incompleta o con huecos devuelva `None` en vez de inventar;
* que DTW absorba un cambio de ritmo pero no confunda gestos distintos;
* que la banda impida el alineamiento patologico que hace pasar cualquier cosa.

Los numeros sobre material real —aplausos de una grabacion de 60 s— estan en
el README del subsistema; aqui se comprueba la mecanica.

Uso, desde la raiz del repositorio:

    .\\.venv\\Scripts\\python.exe .\\external\\gesture_detection\\tests\\test_dtw.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

TESTS_DIR = Path(__file__).resolve().parent
GESTURE_DIR = TESTS_DIR.parent
if str(GESTURE_DIR) not in sys.path:
    sys.path.insert(0, str(GESTURE_DIR))

from features.sequence_buffer import (  # noqa: E402
    DURACION_S,
    MUESTRAS,
    SequenceBuffer,
)
from recognition.dtw import (  # noqa: E402
    DTWRecognizer,
    Plantilla,
    dtw_distancia,
    umbral_por_separacion,
)

LM = (0, 1)                      # dos landmarks: 6 rasgos
results: list[tuple[str, bool, str]] = []


def anotar(nombre: str, ok: bool, detalle: str = "") -> None:
    results.append((nombre, bool(ok), detalle))


def trayectoria(fps: float, duracion_s: float = 3.0, fase: float = 0.0,
                ritmo: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """Un movimiento continuo de dos landmarks, muestreado a `fps`."""
    t = np.arange(0.0, duracion_s, 1.0 / fps)
    w = 2 * np.pi * 0.7 * ritmo
    P = np.zeros((len(t), 3, 3))
    P[:, 0] = np.stack([0.3 * np.sin(w * t + fase),
                        0.2 * np.cos(w * t + fase),
                        np.zeros(len(t))], axis=1)
    P[:, 1] = -P[:, 0]
    return P, t


def llenar(buf: SequenceBuffer, P, t) -> None:
    for k in range(len(t)):
        buf.push(P[k], float(t[k]))


# ------------------------------------------------------------ la ventana


def test_la_ventana_no_depende_del_frame_rate() -> None:
    """Es la razon de remuestrear. Una ventana de N frames dura el doble a la
    mitad de fps: seria otro gesto."""
    a = SequenceBuffer(LM)
    b = SequenceBuffer(LM)
    llenar(a, *trayectoria(30.0))
    llenar(b, *trayectoria(15.0))
    # Se pide el MISMO instante final en las dos: si se deja el ultimo frame
    # de cada una, terminan 33 ms distintas y la comparacion mide eso.
    va, vb = a.ventana(t_fin=2.90), b.ventana(t_fin=2.90)
    ok = va is not None and vb is not None
    error = float(np.abs(va.datos - vb.datos).max()) if ok else float("inf")
    anotar("la ventana es la misma a 15 y a 30 fps", ok and error < 0.01,
           f"diferencia maxima {error:.4f}")


def test_la_ventana_tiene_la_forma_pedida() -> None:
    buf = SequenceBuffer(LM)
    llenar(buf, *trayectoria(30.0))
    v = buf.ventana()
    anotar("forma de la ventana",
           v is not None and v.datos.shape == (MUESTRAS, len(LM) * 3),
           f"{None if v is None else v.datos.shape}")
    anotar("duracion de la ventana",
           v is not None and abs(v.duracion_s - DURACION_S) < 1e-9,
           f"{None if v is None else round(v.duracion_s, 3)}")


def test_la_ventana_admite_rasgos_2d() -> None:
    """La linea base 2D tiene que poder correrse con el mismo codigo.

    Comparar 3D contra 2D es parte de lo que la tesis tiene que responder, y no
    sirve si cada uno usa una implementacion distinta de la ventana.
    """
    P, t = trayectoria(30.0)
    buf = SequenceBuffer(LM, coordenadas=2)
    for k in range(len(t)):
        buf.push(P[k, :, :2], float(t[k]))
    v = buf.ventana()
    anotar("ventana con rasgos 2D",
           v is not None and v.datos.shape == (MUESTRAS, len(LM) * 2),
           f"{None if v is None else v.datos.shape}")

    try:
        SequenceBuffer(LM, coordenadas=4)
    except ValueError:
        anotar("solo se admiten 2 o 3 coordenadas", True, "")
    else:
        anotar("solo se admiten 2 o 3 coordenadas", False, "acepto 4")


def test_sin_material_suficiente_no_hay_ventana() -> None:
    buf = SequenceBuffer(LM)
    llenar(buf, *trayectoria(30.0, duracion_s=DURACION_S * 0.5))
    anotar("media ventana no es una ventana", buf.ventana() is None, "")


def test_un_hueco_largo_invalida_la_ventana() -> None:
    """Media ventana interpolada se compararia con las plantillas como si
    fuera buena. Es peor que no dar dato."""
    P, t = trayectoria(30.0)
    buf = SequenceBuffer(LM)
    for k in range(len(t)):
        dentro = t[k] > t[-1] - DURACION_S
        perdido = dentro and (t[-1] - t[k]) < DURACION_S * 0.6
        buf.push(None if perdido else P[k], float(t[k]))
    anotar("un hueco grande invalida la ventana", buf.ventana() is None, "")


def test_un_hueco_corto_se_tolera() -> None:
    P, t = trayectoria(30.0)
    buf = SequenceBuffer(LM)
    for k in range(len(t)):
        perdido = 0.30 < (t[-1] - t[k]) < 0.40      # 100 ms
        buf.push(None if perdido else P[k], float(t[k]))
    anotar("un hueco corto no invalida la ventana",
           buf.ventana() is not None, "")


def test_el_reset_vacia_el_buffer() -> None:
    buf = SequenceBuffer(LM)
    llenar(buf, *trayectoria(30.0))
    buf.reset()
    anotar("reset deja el buffer sin ventana", buf.ventana() is None, "")


# ------------------------------------------------------------------- DTW


def test_una_trayectoria_consigo_misma_da_cero() -> None:
    P, t = trayectoria(30.0)
    buf = SequenceBuffer(LM)
    llenar(buf, P, t)
    v = buf.ventana().datos
    anotar("distancia consigo misma", dtw_distancia(v, v) < 1e-9,
           f"{dtw_distancia(v, v):.2e}")


def test_dtw_absorbe_un_cambio_de_ritmo() -> None:
    """La misma persona hace el mismo gesto un 20-30 % mas rapido entre
    repeticiones. Comparar muestra a muestra lo penalizaria como otro gesto."""
    a = SequenceBuffer(LM)
    b = SequenceBuffer(LM)
    llenar(a, *trayectoria(30.0, ritmo=1.0))
    llenar(b, *trayectoria(30.0, ritmo=1.2))
    va, vb = a.ventana().datos, b.ventana().datos
    d_dtw = dtw_distancia(va, vb)
    d_directa = float(np.linalg.norm(va - vb, axis=1).mean())
    anotar("DTW penaliza el cambio de ritmo menos que la comparacion directa",
           d_dtw < d_directa, f"DTW {d_dtw:.3f} vs directa {d_directa:.3f}")


def test_dos_gestos_distintos_quedan_lejos() -> None:
    a = SequenceBuffer(LM)
    b = SequenceBuffer(LM)
    llenar(a, *trayectoria(30.0))
    P, t = trayectoria(30.0)
    P[:, 0, 2] = 0.8                        # el mismo dibujo, otra profundidad
    P[:, 1, 2] = -0.8
    llenar(b, P, t)
    va, vb = a.ventana().datos, b.ventana().datos
    anotar("dos trayectorias distintas quedan lejos",
           dtw_distancia(va, vb) > 0.5, f"{dtw_distancia(va, vb):.3f}")


def test_la_banda_impide_el_alineamiento_patologico() -> None:
    """Sin banda, DTW alinea un pulso con cualquier cosa y devuelve una
    distancia pequeña que no significa nada."""
    # Dos escalones en extremos opuestos de la ventana: el mismo dibujo, pero
    # separados en el tiempo mas de lo que un cambio de ritmo explica.
    temprano = np.zeros((MUESTRAS, 6))
    temprano[2:] = 1.0
    tardio = np.zeros((MUESTRAS, 6))
    tardio[MUESTRAS - 2:] = 1.0
    con = dtw_distancia(temprano, tardio, banda=0.25)
    sin = dtw_distancia(temprano, tardio, banda=1.0)
    anotar("la banda impide alinear cosas separadas en el tiempo", con > sin,
           f"banda 0.25 -> {con:.3f}, sin banda -> {sin:.3f}")


def test_dtw_rechaza_formas_incompatibles() -> None:
    try:
        dtw_distancia(np.zeros((10, 6)), np.zeros((10, 4)))
    except ValueError:
        anotar("dimensiones incompatibles fallan", True, "")
    else:
        anotar("dimensiones incompatibles fallan", False, "no fallo")


# ------------------------------------------------------------ reconocedor


def _ventana(**kw) -> np.ndarray:
    buf = SequenceBuffer(LM)
    llenar(buf, *trayectoria(30.0, **kw))
    return buf.ventana().datos


def test_el_reconocedor_encuentra_su_plantilla() -> None:
    rec = DTWRecognizer()
    rec.agregar(Plantilla("aplauso", _ventana(), umbral=0.3))
    r = rec.comparar(_ventana(ritmo=1.1))
    anotar("reconoce una repeticion del mismo gesto",
           r.hay_gesto and r.nombre == "aplauso", f"{r.nombre} d={r.distancia:.3f}")


def test_el_umbral_rechaza_lo_que_no_se_parece() -> None:
    rec = DTWRecognizer()
    rec.agregar(Plantilla("aplauso", _ventana(), umbral=0.05))
    r = rec.comparar(_ventana(fase=np.pi))
    anotar("por encima del umbral no hay gesto", not r.hay_gesto,
           f"d={r.distancia:.3f}")


def test_sin_plantillas_no_hay_gesto() -> None:
    r = DTWRecognizer().comparar(_ventana())
    anotar("sin plantillas no hay gesto", not r.hay_gesto, "")


def test_el_margen_evita_el_parpadeo_entre_gestos_parecidos() -> None:
    rec = DTWRecognizer(margen_minimo=1.0)
    rec.agregar(Plantilla("a", _ventana(), umbral=10.0))
    rec.agregar(Plantilla("b", _ventana(ritmo=1.02), umbral=10.0))
    r = rec.comparar(_ventana(ritmo=1.01))
    anotar("dos gestos casi iguales no se eligen al azar", not r.hay_gesto,
           f"margen {r.margen:.3f}")


def test_varias_plantillas_por_gesto() -> None:
    rec = DTWRecognizer()
    for ritmo in (0.9, 1.0, 1.1):
        rec.agregar(Plantilla("aplauso", _ventana(ritmo=ritmo), umbral=0.3))
    anotar("el banco agrupa por nombre de gesto",
           rec.gestos == ["aplauso"], f"{rec.gestos}")


def test_plantillas_de_distinta_dimension_fallan() -> None:
    rec = DTWRecognizer()
    rec.agregar(Plantilla("a", np.zeros((MUESTRAS, 6))))
    try:
        rec.agregar(Plantilla("b", np.zeros((MUESTRAS, 9))))
    except ValueError:
        anotar("no se mezclan plantillas de distinta dimension", True, "")
    else:
        anotar("no se mezclan plantillas de distinta dimension", False, "")


# --------------------------------------------------------------- umbral


def test_el_umbral_sale_de_las_dos_mitades() -> None:
    u, exactitud = umbral_por_separacion([0.1, 0.2, 0.15], [0.8, 0.9, 0.75])
    anotar("umbral entre los dos grupos", 0.2 < u < 0.75 and exactitud == 1.0,
           f"u={u:.3f} exactitud={exactitud:.2f}")


def test_sin_negativos_no_hay_umbral() -> None:
    u, exactitud = umbral_por_separacion([0.1, 0.2], [])
    anotar("sin material negativo no se inventa un umbral",
           not np.isfinite(u) and exactitud == 0.0, f"u={u}")


def test_grupos_solapados_lo_dicen_en_la_exactitud() -> None:
    u, exactitud = umbral_por_separacion([0.1, 0.9], [0.2, 0.8])
    anotar("si no separan, la exactitud lo dice", exactitud < 0.8,
           f"exactitud {exactitud:.2f}")


def main() -> int:
    print("Gestos dinamicos: ventana deslizante y DTW")
    print("Sin camara, sin MediaPipe y sin dron.\n")
    print(f"  ventana {DURACION_S} s en {MUESTRAS} muestras\n")

    for prueba in (
        test_la_ventana_no_depende_del_frame_rate,
        test_la_ventana_tiene_la_forma_pedida,
        test_la_ventana_admite_rasgos_2d,
        test_sin_material_suficiente_no_hay_ventana,
        test_un_hueco_largo_invalida_la_ventana,
        test_un_hueco_corto_se_tolera,
        test_el_reset_vacia_el_buffer,
        test_una_trayectoria_consigo_misma_da_cero,
        test_dtw_absorbe_un_cambio_de_ritmo,
        test_dos_gestos_distintos_quedan_lejos,
        test_la_banda_impide_el_alineamiento_patologico,
        test_dtw_rechaza_formas_incompatibles,
        test_el_reconocedor_encuentra_su_plantilla,
        test_el_umbral_rechaza_lo_que_no_se_parece,
        test_sin_plantillas_no_hay_gesto,
        test_el_margen_evita_el_parpadeo_entre_gestos_parecidos,
        test_varias_plantillas_por_gesto,
        test_plantillas_de_distinta_dimension_fallan,
        test_el_umbral_sale_de_las_dos_mitades,
        test_sin_negativos_no_hay_umbral,
        test_grupos_solapados_lo_dicen_en_la_exactitud,
    ):
        prueba()

    ancho = max(len(nombre) for nombre, _, _ in results)
    fallos = 0
    for nombre, ok, detalle in results:
        marca = "OK  " if ok else "FALLA"
        extra = f"   {detalle}" if detalle else ""
        print(f"  [{marca}] {nombre.ljust(ancho)}{extra}")
        fallos += not ok

    print()
    if fallos:
        print(f"{fallos} de {len(results)} comprobaciones fallaron.")
        return 1
    print(f"Las {len(results)} comprobaciones pasaron.")
    print("Esto valida la mecanica. Que un gesto real se separe de lo demas "
          "depende del dataset.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
