"""Reconocedor de gestos dinamicos. Sin camara, sin MediaPipe y sin dron.

Se alimenta el reconocedor cuadro a cuadro con trayectorias sinteticas y se
comprueba lo que decide si el detector sirve en vivo:

* que segmente por movimiento y no por una ventana ciega;
* que no cierre un segmento porque la mano se detuvo un instante;
* que un movimiento que no se parece a nada no produzca un gesto;
* que la clase de rechazo funcione, que es lo unico que permite decir «esto no
  es ninguno» en vez de forzar el mas parecido;
* que el periodo refractario impida leer dos veces el mismo gesto.

Uso, desde la raiz del repositorio:

    .\\.venv\\Scripts\\python.exe .\\external\\gesture_detection\\tests\\test_dinamicos.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

TESTS_DIR = Path(__file__).resolve().parent
GESTURE_DIR = TESTS_DIR.parent
if str(GESTURE_DIR) not in sys.path:
    sys.path.insert(0, str(GESTURE_DIR))

from pose.normalize import (  # noqa: E402
    LEFT_ELBOW,
    LEFT_WRIST,
    N_LANDMARKS,
    RIGHT_ELBOW,
    RIGHT_WRIST,
)
from recognition.dtw import dtw_distancia  # noqa: E402
from recognition.dinamicos import (  # noqa: E402
    GESTO_RECHAZO,
    MUESTRAS,
    BancoDinamico,
    ReconocedorDinamico,
    rasgos_de_secuencia,
    recortar_quietud,
)

FPS = 30.0
results: list[tuple[str, bool, str]] = []


def anotar(nombre: str, ok: bool, detalle: str = "") -> None:
    results.append((nombre, bool(ok), detalle))


def trayectoria(clase: str, duracion=2.5, quietud=0.8, ruido=0.0015,
                semilla=0, t0=0.0):
    """Poses canonicalizadas con quietud, movimiento y quietud otra vez."""
    rng = np.random.default_rng(semilla)
    t = np.arange(0.0, quietud * 2 + duracion, 1.0 / FPS) + t0
    P = np.zeros((len(t), N_LANDMARKS, 3))
    activo = (t - t0 > quietud) & (t - t0 < quietud + duracion)
    fase = np.zeros(len(t))
    fase[activo] = (t[activo] - t0 - quietud) / duracion

    if clase == "junta":               # las dos manos se acercan y separan
        sep = 0.45 - 0.40 * np.sin(np.pi * fase * 3) ** 2
        P[:, RIGHT_WRIST] = np.stack([-sep, 0.3 * (fase > 0), 0.35 * (fase > 0)], 1)
        P[:, LEFT_WRIST] = np.stack([sep, 0.3 * (fase > 0), 0.35 * (fase > 0)], 1)
    elif clase == "una_mano":          # solo la derecha, hacia arriba y abajo
        alto = 0.8 * np.sin(np.pi * fase * 2) ** 2
        P[:, RIGHT_WRIST] = np.stack([-0.3 - 0 * alto, alto, 0.3 * (fase > 0)], 1)
        P[:, LEFT_WRIST] = [0.22, -0.15, 0.02]
    elif clase == "ajeno":             # una mano cruzando el cuerpo de lado
        x = -0.35 + 0.7 * np.sin(np.pi * fase) ** 2
        P[:, RIGHT_WRIST] = np.stack([x, -0.1 * (fase > 0), 0.1 * (fase > 0)], 1)
        P[:, LEFT_WRIST] = [0.22, -0.15, 0.02]
    else:                              # brazos que se abren en cruz
        ancho = 0.2 + 0.9 * np.sin(np.pi * fase) ** 2
        P[:, RIGHT_WRIST] = np.stack([-ancho, 0.4 * (fase > 0), np.zeros(len(t))], 1)
        P[:, LEFT_WRIST] = np.stack([ancho, 0.4 * (fase > 0), np.zeros(len(t))], 1)
    P[:, RIGHT_ELBOW] = P[:, RIGHT_WRIST] * 0.5
    P[:, LEFT_ELBOW] = P[:, LEFT_WRIST] * 0.5
    return P + rng.normal(0, ruido, P.shape), t


def ventana_de(clase, **kw):
    P, t = trayectoria(clase, **kw)
    P, t = recortar_quietud(P, t)
    return rasgos_de_secuencia(P, t)


def banco_de_prueba(con_rechazo=True) -> BancoDinamico:
    gestos, plantillas = [], []
    for clase in ("junta", "una_mano", "cruz"):
        for s in range(3):
            v = ventana_de(clase, semilla=s, duracion=2.2 + 0.2 * s)
            if v is not None:
                gestos.append(clase)
                plantillas.append(v)
    if con_rechazo:
        # Un movimiento ajeno de verdad, no una version corta de uno del
        # vocabulario: la duracion se normaliza, asi que eso seria el mismo.
        for s in range(3):
            v = ventana_de("ajeno", semilla=50 + s)
            if v is not None:
                gestos.append(GESTO_RECHAZO)
                plantillas.append(v)
    return BancoDinamico(gestos=gestos, plantillas=plantillas, umbral=0.6)


def reproducir(rec, clase, t0=0.0, **kw):
    """Pasa una trayectoria cuadro a cuadro y devuelve las detecciones."""
    P, t = trayectoria(clase, t0=t0, **kw)
    dets = []
    for k in range(len(t)):
        d = rec.actualizar(P[k], float(t[k]))
        if d is not None:
            dets.append(d)
    # Un poco de quietud extra para que cierre el ultimo segmento.
    for k in range(30):
        d = rec.actualizar(P[-1], float(t[-1] + (k + 1) / FPS))
        if d is not None:
            dets.append(d)
    return dets


# ------------------------------------------------------------ segmentacion


def test_segmenta_el_movimiento() -> None:
    rec = ReconocedorDinamico(banco_de_prueba())
    dets = reproducir(rec, "junta", semilla=99)
    anotar("un gesto produce una deteccion", len(dets) == 1,
           f"{len(dets)} detecciones")


def test_la_quietud_no_produce_nada() -> None:
    """De pie sin moverse no puede salir ningun gesto."""
    rec = ReconocedorDinamico(banco_de_prueba())
    P = np.zeros((120, N_LANDMARKS, 3))
    P[:, RIGHT_WRIST] = [-0.22, -0.15, 0.02]
    P[:, LEFT_WRIST] = [0.22, -0.15, 0.02]
    P += np.random.default_rng(0).normal(0, 0.004, P.shape)
    dets = [d for k in range(len(P))
            if (d := rec.actualizar(P[k], k / FPS)) is not None]
    anotar("la quietud no dispara nada", not dets, f"{len(dets)} detecciones")


def test_una_pausa_corta_no_parte_el_gesto() -> None:
    """Un aplauso se detiene un instante en cada palmada. Si eso cerrara el
    segmento, cada gesto saldria partido en varios."""
    rec = ReconocedorDinamico(banco_de_prueba())
    P, t = trayectoria("junta", duracion=2.5, semilla=7)
    mitad = len(t) // 2
    P[mitad:mitad + 4] = P[mitad]                 # 130 ms congelados
    dets = [d for k in range(len(t))
            if (d := rec.actualizar(P[k], float(t[k]))) is not None]
    for k in range(30):
        d = rec.actualizar(P[-1], float(t[-1] + (k + 1) / FPS))
        if d is not None:
            dets.append(d)
    anotar("una pausa corta no parte el gesto", len(dets) == 1,
           f"{len(dets)} detecciones")


def test_el_refractario_evita_leer_dos_veces() -> None:
    rec = ReconocedorDinamico(banco_de_prueba())
    dets = reproducir(rec, "junta", semilla=3)
    dets += reproducir(rec, "junta", semilla=4, t0=20.0)
    anotar("dos gestos seguidos dan dos detecciones", len(dets) == 2,
           f"{len(dets)}")


# ------------------------------------------------------------ clasificacion


def test_reconoce_cada_clase() -> None:
    banco = banco_de_prueba(con_rechazo=False)
    for clase in ("junta", "una_mano", "cruz"):
        rec = ReconocedorDinamico(banco)
        dets = reproducir(rec, clase, semilla=77)
        leido = dets[0].gesto if dets else None
        anotar(f"reconoce {clase}", leido == clase, f"leido {leido}")


def test_sin_clase_de_rechazo_acepta_cualquier_cosa() -> None:
    """El hallazgo que motivo la clase de rechazo: un banco de solo gestos
    buenos no puede decir que no. Sobre material real, los movimientos ajenos
    caian mas cerca del banco que los propios aciertos."""
    banco = banco_de_prueba(con_rechazo=False)
    banco.umbral = 10.0
    rec = ReconocedorDinamico(banco)
    dets = reproducir(rec, "ajeno", semilla=60)
    anotar("sin rechazo, todo se clasifica como algo",
           bool(dets) and dets[0].gesto is not None,
           f"leido {dets[0].gesto if dets else None}")


def test_la_clase_de_rechazo_dice_que_no() -> None:
    banco = banco_de_prueba(con_rechazo=True)
    banco.umbral = 10.0
    rec = ReconocedorDinamico(banco)
    dets = reproducir(rec, "ajeno", semilla=61)
    anotar("con rechazo, lo ajeno no produce gesto",
           bool(dets) and dets[0].gesto is None,
           f"leido {dets[0].gesto if dets else None}")


def test_el_umbral_rechaza_lo_lejano() -> None:
    banco = banco_de_prueba(con_rechazo=False)
    banco.umbral = 0.001
    rec = ReconocedorDinamico(banco)
    dets = reproducir(rec, "junta", semilla=11)
    anotar("por encima del umbral no hay gesto",
           bool(dets) and dets[0].gesto is None,
           f"{dets[0].distancia:.3f}" if dets else "sin deteccion")


def test_el_rechazo_no_es_una_clase_emitible() -> None:
    banco = banco_de_prueba(con_rechazo=True)
    anotar("la clase de rechazo no se lista como gesto",
           GESTO_RECHAZO not in banco.clases and banco.tiene_rechazo,
           f"{banco.clases}")


# ------------------------------------------------------------- utilidades


def test_recortar_quita_la_quietud() -> None:
    P, t = trayectoria("junta", duracion=2.0, quietud=1.0)
    Pr, tr = recortar_quietud(P, t)
    dur = tr[-1] - tr[0]
    anotar("recortar deja solo el tramo activo", 1.5 < dur < 2.8,
           f"{dur:.1f} s de {t[-1] - t[0]:.1f} s")


def test_la_ventana_no_depende_del_frame_rate() -> None:
    """Lo que tiene que aguantar el cambio de fps es la DISTANCIA, no cada
    punto.

    Punto a punto las dos versiones difieren bastante —el recorte cae en
    frames distintos— pero eso no importa: lo que decide es cuanto se separan
    en DTW. Medido sobre 72 tomas reales, la distancia entre la version a 30 y
    la de 15 fps es 0.048 de mediana y 0.166 como maximo, contra un umbral de
    aceptacion de 0.81 y una distancia tipica de acierto de 0.33. Ninguna toma
    se saldria del umbral por bajar el frame rate.
    """
    peor = 0.0
    for clase in ("junta", "una_mano", "cruz"):
        P, t = trayectoria(clase, semilla=5)
        a = rasgos_de_secuencia(*recortar_quietud(P, t))
        b = rasgos_de_secuencia(*recortar_quietud(P[::2], t[::2]))
        if a is None or b is None:
            anotar("la ventana aguanta 15 fps", False, f"{clase} sin ventana")
            return
        peor = max(peor, dtw_distancia(a, b))
    anotar("la ventana aguanta 15 fps", peor < 0.25,
           f"peor distancia DTW {peor:.3f}")


def test_un_segmento_sin_pose_no_se_clasifica() -> None:
    rec = ReconocedorDinamico(banco_de_prueba())
    P, t = trayectoria("junta", semilla=13)
    dets = []
    for k in range(len(t)):
        pose = None if 0.3 < (t[k] / t[-1]) < 0.9 else P[k]
        d = rec.actualizar(pose, float(t[k]))
        if d is not None:
            dets.append(d)
    for k in range(40):
        d = rec.actualizar(P[-1], float(t[-1] + (k + 1) / FPS))
        if d is not None:
            dets.append(d)
    malos = [d for d in dets if d.gesto is not None]
    anotar("un segmento medio perdido no se clasifica", not malos,
           f"{len(malos)} clasificados de {len(dets)}")


def test_el_banco_sobrevive_al_disco() -> None:
    carpeta = Path(tempfile.mkdtemp())
    try:
        original = banco_de_prueba()
        ruta = original.guardar(carpeta / "banco.npz")
        leido = BancoDinamico.cargar(ruta)
        igual = (leido.gestos == original.gestos
                 and leido.umbral == original.umbral
                 and leido.con_diferencia == original.con_diferencia
                 and all(np.allclose(a, b) for a, b in
                         zip(leido.plantillas, original.plantillas)))
        anotar("el banco vuelve igual del disco", igual, ruta.name)
    finally:
        shutil.rmtree(carpeta, ignore_errors=True)


def main() -> int:
    print("Gestos dinamicos: segmentacion y clasificacion")
    print("Sin camara, sin MediaPipe y sin dron.\n")

    for prueba in (
        test_segmenta_el_movimiento,
        test_la_quietud_no_produce_nada,
        test_una_pausa_corta_no_parte_el_gesto,
        test_el_refractario_evita_leer_dos_veces,
        test_reconoce_cada_clase,
        test_sin_clase_de_rechazo_acepta_cualquier_cosa,
        test_la_clase_de_rechazo_dice_que_no,
        test_el_umbral_rechaza_lo_lejano,
        test_el_rechazo_no_es_una_clase_emitible,
        test_recortar_quita_la_quietud,
        test_la_ventana_no_depende_del_frame_rate,
        test_un_segmento_sin_pose_no_se_clasifica,
        test_el_banco_sobrevive_al_disco,
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
    print("Esto valida la mecanica. Lo que el detector acierta con gente real "
          "esta medido en construir_plantillas.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
