"""Graba tomas de gestos con la camara. Sin dron y sin clasificar nada.

Pregunta el nombre y el numero de toma, abre la camara para que te encuadres, y
graba entre un ENTER y el siguiente. Cada toma es **una repeticion** del gesto.

Uso, desde la raiz del repositorio:

    python .\\external\\gesture_detection\\grabar_gestos.py
    python .\\external\\gesture_detection\\grabar_gestos.py --gesto reposo
    python .\\external\\gesture_detection\\grabar_gestos.py --orientacion 45

Como se usa
-----------
1. Escribe tu nombre y el numero de la primera toma en la consola.
2. Se abre la camara. Encuadrate: el panel dice si el cuerpo se ve completo.
3. ENTER empieza a grabar, ENTER vuelve a pararla y guarda.
4. El numero sube solo, asi que se pueden encadenar repeticiones. `q` sale.

Que hay que grabar para que el dataset sirva
--------------------------------------------
**Al menos dos gestos distintos.** Con uno solo no hay nada que separar: la
evaluacion mide si un aplauso se distingue de lo que *no* es un aplauso, y sin
material negativo cualquier umbral da 100 %.

**Varias repeticiones de cada uno**, cinco o mas. DTW no entrena, pero una sola
plantilla no cubre la variacion entre repeticiones.

**Y si se puede, el mismo gesto girado.** Con una sola camara, girar al operador
es exactamente equivalente a mover la camara: es la unica forma honesta de medir
si una plantilla transfiere entre las vistas del anillo. Se graban tomas con
`--orientacion 0`, `30`, `60` y `90`.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

MODULE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = MODULE_DIR.parents[1]
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from dataset.storage import Toma, carpeta_de_hoy, guardar  # noqa: E402
from pose.detector import PoseDetector  # noqa: E402
from pose.normalize import (  # noqa: E402
    LEFT_HIP,
    LEFT_SHOULDER,
    LEFT_WRIST,
    N_LANDMARKS,
    RIGHT_HIP,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
    body_frame,
    landmarks_to_array,
)
from utils import calculate_fps  # noqa: E402
from visualization.pose_overlay import draw_pose  # noqa: E402

VENTANA = "Grabar gestos"
ENTER = (13, 10)

#: Orientaciones que recorre la tecla `o`. Con una sola camara, girar al
#: operador equivale a mover la camara.
ORIENTACIONES = (0.0, 30.0, 60.0, 90.0)

#: Gestos que recorre la tecla `g`. El segundo existe para que haya material
#: negativo: sin el, la evaluacion no mide nada.
GESTOS = ("aplauso", "reposo")

#: Guion del modo guiado: la sesion completa de una persona, en el orden en que
#: conviene grabarla. Se agrupa por ANGULO y no por gesto porque girarse es lo
#: lento: uno se coloca una vez y hace los tres gestos desde ahi.
#:
#: Dos repeticiones de cada combinacion. Con una sola, como en la primera
#: tanda, una toma rara no se distingue de un gesto raro.
GUION_GESTOS = ("aplaudir", "ven_aca", "arco")

#: Angulos y cuantas repeticiones en cada uno. El perfil lleva mas porque es la
#: banda que decide si una plantilla transfiere entre camaras del anillo, y es
#: la unica de la que casi no hay material: 3 tomas en todo el dataset.
GUION_ANGULOS = ((0.0, 2), (45.0, 2), (-45.0, 2), (90.0, 3))

#: Tomas de movimiento que NO es ninguno de los gestos. Son las que permiten al
#: detector decir "esto no es ninguno".
#:
#: Sin ellas no hay forma de rechazar: DTW se queda con la plantilla mas
#: cercana, y si el banco solo tiene los gestos buenos, alguno gana siempre.
#: Medido: con un banco de solo los tres, los movimientos ajenos caian a
#: distancia mediana 0.299, MAS CERCA que los aciertos reales (0.315). No es
#: que estuvieran lejos y se colaran por un umbral flojo.
#:
#: Las que valen son las que **casi** parecen un gesto. Un falso positivo no es
#: un movimiento raro y lejano: es un casi-acierto. Por eso las primeras piden
#: movimientos con las dos manos cerca del pecho, que es donde se solapan.
GUION_OTRO = 8

#: Que se pide en cada toma de rechazo, en orden. Las primeras son las
#: dificiles a proposito.
GUION_OTRO_QUE = (
    "cruzate de brazos y descruzate",
    "acomodate la camisa o el cuello",
    "frotate las manos como si tuvieras frio",
    "gesticula con las dos manos como explicando algo",
    "mira el telefono y guardalo",
    "camina un par de pasos y volve",
    "rascate la cabeza, estirate",
    "girate, mira para atras y volve",
)

FONDO = (22, 22, 26)
BLANCO = (238, 238, 242)
GRIS = (150, 150, 155)
VERDE = (120, 220, 140)
ROJO = (90, 90, 240)
AMBAR = (80, 200, 255)

#: Visibilidad minima de los landmarks clave para dar el encuadre por bueno.
VISIBILIDAD_OK = 0.70

#: Margen del borde de la imagen, en fraccion. Un landmark mas cerca del borde
#: que esto se considera en riesgo de salirse: con el brazo levantado es lo que
#: mas suele pasar.
MARGEN = 0.03

CLAVE = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_WRIST, RIGHT_WRIST,
         LEFT_HIP, RIGHT_HIP)


def encuadre(lm2d, mundo, vis) -> tuple[bool, str]:
    """Dice si la toma va a servir, y si no, por que.

    Avisar antes es barato; descubrir que media sesion no vale, no.
    """
    if lm2d is None or mundo is None:
        return False, "no se detecta a nadie"
    marco = body_frame(mundo, vis)
    if marco is None:
        return False, "faltan caderas u hombros"
    if not marco.valid:
        return False, "de perfil: el marco corporal no es fiable"
    media = float(np.mean(vis[list(CLAVE)]))
    if media < VISIBILIDAD_OK:
        return False, f"visibilidad baja ({media:.2f})"
    P = np.array([[l.x, l.y] for l in lm2d], dtype=np.float64)
    fuera = [i for i in CLAVE
             if not (MARGEN < P[i][0] < 1 - MARGEN and MARGEN < P[i][1] < 1 - MARGEN)]
    if fuera:
        return False, "alguna articulacion se sale del encuadre"
    # Las munecas son las que se salen al levantar el brazo.
    munecas = [P[LEFT_WRIST][1], P[RIGHT_WRIST][1]]
    if min(munecas) < 0.10:
        return True, "cuidado: las manos rozan el borde superior"
    return True, "encuadre correcto"


def _texto(img, txt, fila, color=BLANCO, escala=0.6, grosor=1) -> None:
    cv2.putText(img, txt, (14, 32 + fila * 30), cv2.FONT_HERSHEY_SIMPLEX,
                escala, (0, 0, 0), grosor + 2, cv2.LINE_AA)
    cv2.putText(img, txt, (14, 32 + fila * 30), cv2.FONT_HERSHEY_SIMPLEX,
                escala, color, grosor, cv2.LINE_AA)


def dibujar(frame, *, persona, gesto, numero, orientacion, grabando, n_frames,
            duracion, fps, ok, motivo, guardadas, guion=None, paso=0,
            como="") -> None:
    alto = frame.shape[0]
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (frame.shape[1], 150), FONDO, -1)
    cv2.addWeighted(overlay, 0.72, frame, 0.28, 0, frame)

    if guion is not None:
        _texto(frame, f"{persona}   paso {paso + 1}/{len(guion)}   "
                      f"{gesto}   {orientacion:+.0f} deg   toma {numero}",
               0, AMBAR, 0.6)
    else:
        _texto(frame, f"{persona}   [g] {gesto}   [o] {orientacion:.0f} deg   "
                      f"toma {numero}", 0, AMBAR, 0.6)
    if grabando:
        _texto(frame, f"GRABANDO   {duracion:4.1f} s   {n_frames} frames",
               1, ROJO, 0.85, 2)
        cv2.circle(frame, (frame.shape[1] - 40, 40), 14, (60, 60, 240), -1)
    else:
        _texto(frame, "LISTO   ENTER para grabar", 1, VERDE, 0.85, 2)
    _texto(frame, motivo, 2, VERDE if ok else AMBAR, 0.55)
    if como:
        _texto(frame, como, 3, BLANCO, 0.52)
    _texto(frame, f"fps {fps:.1f}   tomas guardadas {guardadas}",
           4 if como else 3, GRIS, 0.5)
    cv2.putText(frame,
                ("ENTER grabar/parar    b repetir la anterior    q salir"
                 if guion is not None else
                 "ENTER grabar/parar    g gesto    o orientacion    q salir"),
                (14, alto - 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, GRIS, 1,
                cv2.LINE_AA)


def construir_guion(gestos=GUION_GESTOS, angulos=GUION_ANGULOS,
                    otro=GUION_OTRO):
    """`[(gesto, orientacion, numero)]` con la sesion completa de una persona."""
    pasos, cuenta = [], {}
    for angulo, repeticiones in angulos:
        for gesto in gestos:
            for _ in range(repeticiones):
                clave = (gesto, angulo)
                cuenta[clave] = cuenta.get(clave, 0) + 1
                pasos.append((gesto, angulo, cuenta[clave]))
    for k in range(otro):
        pasos.append(("otro", 0.0, k + 1))
    return pasos


#: Que se le dice al operador en cada paso. Sale en pantalla.
COMO = {
    "aplaudir": "aplaudi varias veces, a la altura del pecho",
    "ven_aca": "llama con UNA mano, como diciendo veni",
    "arco": "arma un arco: un brazo estira y el otro tira",
    "otro": "movimiento que NO es ninguno de los tres",
}


def como_hacerlo(gesto: str, numero: int) -> str:
    """Instruccion en pantalla. Las de rechazo cambian en cada toma."""
    if gesto == "otro":
        i = (numero - 1) % len(GUION_OTRO_QUE)
        return f"NO es un gesto: {GUION_OTRO_QUE[i]}"
    return COMO.get(gesto, "")


def preguntar(args) -> tuple[str, int]:
    persona = args.persona or input("Nombre de la persona: ").strip()
    while not persona:
        persona = input("Nombre de la persona: ").strip()
    if args.numero is not None:
        return persona, args.numero
    crudo = input("Numero de la primera toma [1]: ").strip()
    try:
        return persona, int(crudo) if crudo else 1
    except ValueError:
        print("No es un numero; se empieza en 1.")
        return persona, 1


def bucle(*, camara, persona, gesto, numero, orientacion, carpeta,
          gestos=GESTOS, orientaciones=ORIENTACIONES, guion=None,
          instruccion=None) -> int:
    """Graba tomas hasta que se pulse `q`.

    `instruccion(gesto, numero)` es el texto que se muestra al operador. Por
    defecto es el de este vocabulario; otros guiones (`grabar_vocabulario.py`)
    pasan el suyo sin tocar el bucle.

    El numero de toma se lleva **por combinacion de gesto y orientacion**: al
    cambiar de una a otra con `g` u `o`, la numeracion de cada una sigue donde
    se quedo en vez de pisarse.
    """
    captura = cv2.VideoCapture(camara)
    if not captura.isOpened():
        raise RuntimeError(f"No se pudo abrir la camara {camara}.")
    detector = PoseDetector()

    lista_gestos = list(dict.fromkeys([gesto, *gestos]))
    lista_orient = list(dict.fromkeys([orientacion, *orientaciones]))
    i_gesto, i_orient = 0, 0
    # Solo la combinacion con la que se arranca empieza en el numero que pidio
    # el operador; las demas empiezan en 1.
    clave_inicial = (gesto, orientacion)
    numero_inicial = numero
    numeros: dict[tuple[str, float], int] = {}

    grabando = False
    guardadas = 0
    paso = 0
    anterior = 0.0
    mundo_buf: list[np.ndarray] = []
    imagen_buf: list[np.ndarray] = []
    vis_buf: list[np.ndarray] = []
    t_buf: list[float] = []
    t0 = 0.0

    cv2.namedWindow(VENTANA, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(VENTANA, 1024, 768)
    print(f"\nGuardando en {carpeta}")
    print("Ponte a cuerpo entero. ENTER empieza y para la grabacion, q sale.\n")

    try:
        while True:
            ok_lectura, crudo = captura.read()
            if not ok_lectura:
                raise RuntimeError("La camara dejo de entregar imagenes.")
            # La inferencia va sobre la imagen SIN voltear: volteada, MediaPipe
            # intercambia las etiquetas anatomicas.
            lm2d, mundo_lm = detector.process_full(crudo)
            fps, anterior = calculate_fps(anterior)

            mundo, vis = landmarks_to_array(mundo_lm)
            ok, motivo = encuadre(lm2d, mundo if mundo.size else None,
                                  vis if vis.size else None)

            if grabando:
                if lm2d is None or mundo.size == 0:
                    P2 = np.full((N_LANDMARKS, 2), np.nan)
                    P3 = np.full((N_LANDMARKS, 3), np.nan)
                    Vv = np.zeros(N_LANDMARKS)
                else:
                    P2 = np.array([[l.x, l.y] for l in lm2d], dtype=np.float64)
                    P3, Vv = mundo, vis
                mundo_buf.append(P3)
                imagen_buf.append(P2)
                vis_buf.append(Vv)
                t_buf.append(time.perf_counter() - t0)

            if guion is not None:
                if paso >= len(guion):
                    print("Guion terminado.")
                    break
                gesto, orientacion, numero = guion[paso]
            else:
                gesto = lista_gestos[i_gesto]
                orientacion = lista_orient[i_orient]
                clave = (gesto, orientacion)
                if clave not in numeros:
                    numeros[clave] = (numero_inicial if clave == clave_inicial
                                      else 1)
                numero = numeros[clave]

            dibujado = crudo.copy()
            draw_pose(dibujado, lm2d, detector.connections)
            dibujado = cv2.flip(dibujado, 1)          # espejo solo para mostrar
            dibujar(dibujado, persona=persona, gesto=gesto, numero=numero,
                    orientacion=orientacion, grabando=grabando,
                    n_frames=len(t_buf),
                    duracion=(t_buf[-1] if t_buf else 0.0), fps=fps, ok=ok,
                    motivo=motivo, guardadas=guardadas, guion=guion, paso=paso,
                    como=(instruccion or como_hacerlo)(gesto, numero))
            cv2.imshow(VENTANA, dibujado)

            tecla = cv2.waitKey(1) & 0xFF
            if tecla == ord("q"):
                break
            if guion is not None and tecla == ord("b") and not grabando:
                paso = max(paso - 1, 0)          # repetir la toma anterior
                continue
            if tecla == ord("g") and not grabando:
                i_gesto = (i_gesto + 1) % len(lista_gestos)
                continue
            if tecla == ord("o") and not grabando:
                i_orient = (i_orient + 1) % len(lista_orient)
                continue
            if tecla in ENTER:
                if not grabando:
                    mundo_buf, imagen_buf, vis_buf, t_buf = [], [], [], []
                    t0 = time.perf_counter()
                    grabando = True
                    print(f"[{gesto} {orientacion:.0f} deg #{numero}] "
                          f"grabando...")
                else:
                    grabando = False
                    if len(t_buf) < 5:
                        print(f"[toma {numero}] descartada: solo "
                              f"{len(t_buf)} frames.")
                        continue
                    toma = Toma(
                        persona=persona, gesto=gesto, numero=numero,
                        orientacion_deg=orientacion,
                        world=np.stack(mundo_buf), imagen=np.stack(imagen_buf),
                        visibility=np.stack(vis_buf),
                        timestamps=np.array(t_buf),
                    )
                    ruta = guardar(carpeta, toma)
                    guardadas += 1
                    print(f"[{gesto} {orientacion:.0f} deg #{numero}] "
                          f"{ruta.name}   {toma.n_frames} frames, "
                          f"{toma.duracion_s:.1f} s, {toma.fps:.1f} fps")
                    if guion is not None:
                        paso += 1
                    else:
                        numeros[(gesto, orientacion)] = numero + 1
            if cv2.getWindowProperty(VENTANA, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        captura.release()
        detector.close()
        cv2.destroyAllWindows()
    return guardadas


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Graba tomas de gestos para el dataset")
    parser.add_argument("--persona", help="salta la pregunta del nombre")
    parser.add_argument("--numero", type=int, help="salta la pregunta del numero")
    parser.add_argument("--gesto", default="aplauso",
                        help="etiqueta del gesto que se va a grabar")
    parser.add_argument("--orientacion", type=float, default=0.0,
                        help="grados que estas girado respecto de la camara")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--guiado", action="store_true",
                        help="recorre la sesion completa en orden y pone las "
                             "etiquetas solo. Es la forma recomendada")
    parser.add_argument("--carpeta", help="destino; por defecto results/data/gestos")
    args = parser.parse_args()

    persona, numero = preguntar(args)
    carpeta = Path(args.carpeta) if args.carpeta else carpeta_de_hoy(PROJECT_DIR)

    print(f"\nPersona: {persona}   gesto: {args.gesto}   "
          f"orientacion: {args.orientacion:.0f} deg   desde la toma {numero}")
    if args.gesto == "aplauso":
        print("Recorda grabar tambien al menos un gesto distinto "
              "(--gesto reposo, por ejemplo):")
        print("sin material negativo la evaluacion no mide nada.")

    guion = construir_guion() if args.guiado else None
    if guion is not None:
        print(f"Modo guiado: {len(guion)} tomas.")
        print("  ENTER graba y para; el gesto y el angulo los pone el programa.")
        print("  b repite la toma anterior si sale mal.")

    try:
        n = bucle(camara=args.camera, persona=persona, gesto=args.gesto,
                  numero=numero, orientacion=args.orientacion, carpeta=carpeta,
                  guion=guion)
        print(f"\n{n} tomas guardadas en {carpeta}")
        if n:
            print("Para compararlas en 2D y en 3D:")
            print(r"  python .\external\gesture_detection\comparar_2d_3d.py")
        return 0
    except KeyboardInterrupt:
        print("Interrupcion solicitada.")
        return 130
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
