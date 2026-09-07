"""Prueba del vocabulario 3D. Sin dron, sin radio y sin cflib.

No importa controladores ni sabe que existe un Crazyflie: es vision pura. Sirve
para dos cosas distintas.

**Ver que se detecta.** El panel muestra el gesto crudo, si esta confirmado y
cuantas veces se ha confirmado cada uno en la sesion.

**Ver por que NO se detecta**, que es lo que de verdad cuesta averiguar. Cada
condicion del vocabulario aparece con su valor actual, su umbral y si cumple.
Cuando un gesto no sale, la linea en rojo dice exactamente cual es el problema:
el brazo no esta bastante extendido, el otro brazo no esta quieto, las manos no
estan bastante al frente. Sin eso, afinar un umbral es adivinar.

Uso, desde la raiz del repositorio:

    python .\\external\\gesture_detection\\probar_gestos_3d.py
    python .\\external\\gesture_detection\\probar_gestos_3d.py --camera 1
    python .\\external\\gesture_detection\\probar_gestos_3d.py --video grabacion.mp4

Teclas: `q` salir, `r` reiniciar el reconocedor, `d` ocultar o mostrar el
detalle, `espacio` pausar.

Cada sesion deja un CSV con **todas** las medidas por frame, no solo el gesto.
Es el material para reajustar un umbral despues, sin tener que volver a grabar.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

MODULE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = MODULE_DIR.parents[1]
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from contracts import Gesture  # noqa: E402
from pose.detector import PoseDetector  # noqa: E402
from recognition.body_3d_rules import (  # noqa: E402
    CONO_DEG,
    Body3DRecognizer,
    brazo_que_senala,
    diagnostico,
    separaciones_del_vocabulario,
)
from utils import calculate_fps  # noqa: E402
from visualization.pose_overlay import draw_pose  # noqa: E402

VENTANA = "Vocabulario 3D - prueba sin dron"
ALTO_VIDEO = 720
ANCHO_PANEL = 400

#: Banda inferior reservada para la fila de teclas.
PIE_ALTO = 34

FONDO = (24, 24, 28)
BLANCO = (238, 238, 242)
GRIS = (150, 150, 155)
VERDE = (120, 220, 140)
ROJO = (90, 90, 240)
AMBAR = (80, 200, 255)

#: Como se hace cada gesto. Es lo que se le dice al operador cuando falla.
INSTRUCCIONES = {
    Gesture.ARRIBA: "un brazo recto hacia arriba",
    Gesture.ABAJO: "un brazo abajo y al frente, a 45 grados",
    Gesture.ADELANTE: "un brazo al frente, horizontal",
    Gesture.ATRAS: "un brazo abajo y hacia atras",
    Gesture.IZQUIERDA: "brazo IZQUIERDO extendido a tu izquierda",
    Gesture.DERECHA: "brazo DERECHO extendido a tu derecha",
    Gesture.DESPEGAR: "las dos manos sobre los hombros",
    Gesture.ATERRIZAR: "los dos brazos en cruz",
    Gesture.STOP: "las dos manos JUNTAS delante del pecho",
}


# ----------------------------------------------------------------- registro


class Registro:
    """Todas las medidas por frame, no solo el gesto.

    Guardar unicamente la etiqueta obliga a volver a grabar cada vez que se
    quiere mover un umbral. Guardando las medidas, el reajuste es offline.
    """

    #: `dir_x/y/z` es la direccion del brazo que senala, en el marco del
    #: cuerpo. Es la columna que permite **mover una direccion del vocabulario
    #: con datos** en vez de a ojo: basta promediar los frames en que el
    #: operador intentaba un gesto para saber adonde llega su hombro de verdad.
    CAMPOS = (
        "t", "fps", "gesto", "confirmado", "confianza", "escala_m",
        "visibilidad", "condicion",
        "lado", "extension", "vertical_activo", "vertical_parado",
        "dir_x", "dir_y", "dir_z",
        "mejor_direccion", "mejor_angulo",
        "alto_der", "alto_izq", "lat_der", "lat_izq",
        "stop_separacion", "stop_frente",
    )

    def __init__(self, activo: bool = True) -> None:
        self.ruta: Path | None = None
        self._archivo = None
        self._writer = None
        if not activo:
            return
        carpeta = (
            PROJECT_DIR / "results" / "data" / "gesture_detection"
            / datetime.now().strftime("%Y-%m-%d")
        )
        carpeta.mkdir(parents=True, exist_ok=True)
        self.ruta = carpeta / f"vocabulario_3d_{datetime.now():%H%M%S}.csv"
        self._archivo = self.ruta.open("w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._archivo)
        self._writer.writerow(self.CAMPOS)

    def anotar(self, t, fps, evento, escala_m, diag, brazo) -> None:
        if self._writer is None:
            return
        if diag is None or brazo is None:
            self._writer.writerow(
                [f"{t:.3f}", f"{fps:.1f}", evento.gesture.value, 0, "0.000",
                 f"{escala_m:.4f}"] + [""] * (len(self.CAMPOS) - 6)
            )
            return
        mejor = diag["direcciones"][0]
        fila = [
            f"{t:.3f}", f"{fps:.1f}", evento.gesture.value,
            int(evento.confirmed), f"{evento.confidence:.3f}",
            f"{escala_m:.4f}",
            f"{diag['encuadre'][0].valor:.3f}",
            f"{diag['encuadre'][1].valor:.3f}",
            brazo.lado, f"{brazo.largo:.3f}",
            f"{brazo.angulo_vertical:.1f}", f"{brazo.angulo_del_otro:.1f}",
            f"{brazo.direccion[0]:.4f}", f"{brazo.direccion[1]:.4f}",
            f"{brazo.direccion[2]:.4f}",
            mejor.etiqueta, f"{mejor.valor:.1f}",
        ]
        fila += [f"{m.valor:.3f}" for m in diag["dos_manos"]]
        self._writer.writerow(fila)

    def cerrar(self) -> None:
        if self._archivo is not None:
            self._archivo.close()
            self._archivo = None


# -------------------------------------------------------------------- panel


class Lineas:
    """Escribe el panel de arriba abajo sin llevar la cuenta de las filas."""

    def __init__(self, panel) -> None:
        self.panel = panel
        self.y = 34

    def salto(self, px: int = 10) -> None:
        self.y += px

    def texto(self, txt, color=BLANCO, escala=0.46, grosor=1) -> None:
        cv2.putText(self.panel, txt, (16, self.y), cv2.FONT_HERSHEY_SIMPLEX,
                    escala, color, grosor, cv2.LINE_AA)
        self.y += int(26 * max(escala / 0.46, 1.0))

    def titulo(self, txt) -> None:
        self.salto(6)
        self.texto(txt, GRIS, 0.42)

    def medida(self, m, resaltar=False) -> None:
        color = VERDE if m.cumple else ROJO
        if resaltar and m.cumple:
            color = AMBAR
        marca = "OK" if m.cumple else "--"
        cv2.putText(self.panel, f"  {m.etiqueta[:19]:<19}",
                    (16, self.y), cv2.FONT_HERSHEY_SIMPLEX, 0.42, BLANCO, 1,
                    cv2.LINE_AA)
        signo = ">" if m.sentido == ">=" else "<"
        cv2.putText(self.panel,
                    f"{m.valor:6.2f} {signo} {m.umbral:5.2f}  {marca}",
                    (200, self.y), cv2.FONT_HERSHEY_SIMPLEX, 0.42, color, 1,
                    cv2.LINE_AA)
        self.y += 22


def dibujar_panel(evento, diag, *, fps, escala_m, contador, detalle, pausado):
    panel = np.full((ALTO_VIDEO, ANCHO_PANEL, 3), FONDO, np.uint8)
    L = Lineas(panel)

    L.texto("VOCABULARIO 3D - SIN DRON", GRIS, 0.44)
    torso = f"{escala_m * 100:.0f} cm" if np.isfinite(escala_m) else "s/d"
    L.texto(f"fps {fps:4.1f}    torso {torso}"
            f"{'    PAUSA' if pausado else ''}", GRIS, 0.42)
    L.salto(8)

    if diag is None:
        L.texto("SIN MARCO CORPORAL", ROJO, 0.62, 2)
        L.texto("ponte de frente y a cuerpo entero", GRIS, 0.42)
    else:
        color = VERDE if evento.confirmed else (
            GRIS if evento.gesture is Gesture.NO_GESTURE else AMBAR)
        L.texto(evento.gesture.value, color, 0.72, 2)
        if evento.gesture is Gesture.NO_GESTURE:
            peor = _que_falta(diag)
            L.texto(f"lo mas cerca: {peor}", GRIS, 0.42)
        else:
            falta = evento.scores.get("falta_s", 0.0)
            L.texto(
                "confirmado" if evento.confirmed and falta <= 0
                else f"sostener {falta:.1f} s mas", GRIS, 0.42)

    if diag is not None and detalle:
        L.titulo("ENCUADRE")
        for m in diag["encuadre"]:
            L.medida(m)
        L.titulo(f"BRAZO QUE SENALA   (cono {CONO_DEG:.0f} deg)")
        for m in diag["brazo_activo"]:
            L.medida(m)
        # Solo las cuatro direcciones mas cercanas. Las dos ultimas quedan
        # siempre a 100 grados o mas: ocupan sitio y no dicen nada.
        for i, m in enumerate(diag["direcciones"][:4]):
            L.medida(m, resaltar=(i == 0))
        L.titulo("EL OTRO BRAZO")
        for m in diag["brazo_parado"]:
            L.medida(m)
        L.titulo("DOS MANOS")
        for m in diag["dos_manos"]:
            L.medida(m)

    # El pie tiene su banda reservada: con el detalle abierto la tabla llega
    # casi al borde, y los contadores se montaban encima de las teclas.
    sitio = (ALTO_VIDEO - PIE_ALTO - L.y) // 22
    if sitio >= 2:
        L.titulo("CONFIRMADOS EN LA SESION")
        lineas = _contador_compacto(contador, sitio - 1)
        for linea in lineas:
            L.texto(f"  {linea}", BLANCO if contador else GRIS, 0.42)

    cv2.putText(panel, "q salir   r reiniciar   d detalle   espacio pausa",
                (16, ALTO_VIDEO - 16), cv2.FONT_HERSHEY_SIMPLEX, 0.38, GRIS, 1,
                cv2.LINE_AA)
    return panel


def _contador_compacto(contador: Counter, max_lineas: int) -> list[str]:
    """Los contadores en las lineas que quepan, sin desbordar el panel."""
    if not contador:
        return ["todavia ninguno"]
    piezas = [f"{g} {n}" for g, n in contador.most_common()]
    lineas: list[str] = []
    actual = ""
    for pieza in piezas:
        candidato = f"{actual}   {pieza}" if actual else pieza
        if len(candidato) > 30 and actual:
            lineas.append(actual)
            actual = pieza
        else:
            actual = candidato
    lineas.append(actual)
    if len(lineas) > max_lineas:
        lineas = lineas[:max_lineas]
        lineas[-1] = lineas[-1][:24] + " ..."
    return lineas


def _que_falta(diag) -> str:
    """El gesto mas cercano y la condicion que le falta.

    Con NO_GESTURE en pantalla lo util no es saber que no hay gesto, sino cual
    estuvo a punto y por que se quedo fuera. Se decide primero que estaba
    intentando el operador: si el brazo izquierdo no esta quieto, iba a por un
    gesto de dos manos, y decirle que extienda mas el derecho no ayuda.
    """
    for m in diag["encuadre"]:
        if not m.cumple:
            return f"{m.etiqueta} {m.valor:.2f}, hace falta {m.umbral:.2f}"

    if not diag["brazo_parado"][0].cumple:
        return _falta_dos_manos(diag)

    for m in diag["brazo_activo"]:
        if not m.cumple:
            return f"{m.etiqueta} {m.valor:.2f}, hace falta {m.umbral:.2f}"

    mejor, segundo = diag["direcciones"][0], diag["direcciones"][1]
    if not mejor.cumple:
        return f"{mejor.etiqueta} a {mejor.valor:.0f} deg, cono {CONO_DEG:.0f}"
    return (f"{mejor.etiqueta} y {segundo.etiqueta} demasiado juntos "
            f"({mejor.valor:.0f} y {segundo.valor:.0f} deg)")


def _falta_dos_manos(diag) -> str:
    """De los tres gestos de dos manos, el que menos lejos se quedo."""
    porgesto: dict[str, list] = {}
    for m in diag["dos_manos"]:
        porgesto.setdefault(m.etiqueta.split()[0], []).append(m)
    candidatos = [
        (min(m.holgura for m in medidas), nombre,
         min(medidas, key=lambda m: m.holgura))
        for nombre, medidas in porgesto.items()
    ]
    holgura, nombre, peor = max(candidatos)
    if holgura >= 0:
        return f"{nombre} listo"
    return (f"{nombre}: {peor.etiqueta.split(maxsplit=1)[1]} "
            f"{peor.valor:.2f}, hace falta {peor.umbral:.2f}")


# -------------------------------------------------------------------- bucle


def bucle(fuente, *, espejo: bool, registro: Registro) -> Counter:
    captura = cv2.VideoCapture(fuente)
    if not captura.isOpened():
        raise RuntimeError(f"No se pudo abrir {fuente!r}.")

    reconocedor = Body3DRecognizer()
    detector = PoseDetector()
    contador: Counter = Counter()
    anterior = 0.0
    ultimo_confirmado: Gesture | None = None
    detalle = True
    pausado = False
    frame = None
    evento = reconocedor.update(None)
    diag = None
    brazo = None
    fps = 0.0
    t0 = time.monotonic()

    cv2.namedWindow(VENTANA, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(VENTANA, 1280, 720)

    try:
        while True:
            if not pausado or frame is None:
                ok, crudo = captura.read()
                if not ok:
                    break
                alto, ancho = crudo.shape[:2]
                frame = cv2.resize(
                    crudo, (int(ancho * ALTO_VIDEO / alto), ALTO_VIDEO))
                # La inferencia va sobre la imagen SIN voltear. Volteada,
                # MediaPipe intercambia las etiquetas anatomicas: llama
                # "izquierda" a lo que ve a la derecha del encuadre. Comprobado
                # sobre la misma foto con y sin espejo. El espejo se aplica
                # despues, solo para mostrar.
                landmarks, mundo = detector.process_full(frame)
                fps, anterior = calculate_fps(anterior)
                evento = reconocedor.update(mundo)
                rasgos = reconocedor.ultimos_rasgos
                diag = None if rasgos is None else diagnostico(rasgos)
                brazo = None if rasgos is None else brazo_que_senala(rasgos)
                draw_pose(frame, landmarks, detector.connections)

                if evento.confirmed and evento.gesture is not ultimo_confirmado:
                    contador[evento.gesture.value] += 1
                    print(f"[{time.monotonic() - t0:6.2f} s] "
                          f"{evento.gesture.value}")
                if evento.confirmed:
                    ultimo_confirmado = evento.gesture
                elif evento.gesture is Gesture.NO_GESTURE:
                    ultimo_confirmado = None

                registro.anotar(time.monotonic() - t0, fps, evento,
                                reconocedor.scale.scale_m, diag, brazo)

            panel = dibujar_panel(evento, diag, fps=fps,
                                  escala_m=reconocedor.scale.scale_m,
                                  contador=contador, detalle=detalle,
                                  pausado=pausado)
            mostrado = cv2.flip(frame, 1) if espejo else frame
            cv2.imshow(VENTANA, np.hstack([mostrado, panel]))

            tecla = cv2.waitKey(1) & 0xFF
            if tecla == ord("q"):
                break
            if tecla == ord("r"):
                reconocedor.reset()
                ultimo_confirmado = None
            if tecla == ord("d"):
                detalle = not detalle
            if tecla == ord(" "):
                pausado = not pausado
            if cv2.getWindowProperty(VENTANA, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        captura.release()
        detector.close()
        cv2.destroyAllWindows()
    return contador


# --------------------------------------------------------------------- main


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prueba del vocabulario 3D sin dron")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--video", help="archivo de video en vez de la webcam")
    parser.add_argument("--sin-espejo", action="store_true",
                        help="no invertir la imagen (ponlo con --video)")
    parser.add_argument("--sin-csv", action="store_true")
    args = parser.parse_args()

    peor = separaciones_del_vocabulario()[0]
    print(f"{len(INSTRUCCIONES)} gestos, cono de {CONO_DEG:.0f} deg. "
          f"Par mas cercano: {peor[0].value}/{peor[1].value} a {peor[2]:.0f} deg.")
    for gesto, como in INSTRUCCIONES.items():
        print(f"  {gesto.value:<10} {como}")
    print("\nEste programa no conecta ningun dron.\n")

    registro = Registro(activo=not args.sin_csv)
    try:
        contador = bucle(
            args.video if args.video else args.camera,
            espejo=not args.sin_espejo and not args.video,
            registro=registro,
        )
        print("\nGestos confirmados en la sesion:")
        if not contador:
            print("  ninguno")
        for gesto, n in contador.most_common():
            print(f"  {gesto:<12} {n}")
        faltan = [g.value for g in INSTRUCCIONES if g.value not in contador]
        if faltan:
            print(f"\nNo salieron: {', '.join(faltan)}")
        if registro.ruta is not None:
            print(f"\nMedidas por frame: {registro.ruta}")
        return 0
    except KeyboardInterrupt:
        print("Interrupcion solicitada.")
        return 130
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    finally:
        registro.cerrar()


if __name__ == "__main__":
    raise SystemExit(main())
