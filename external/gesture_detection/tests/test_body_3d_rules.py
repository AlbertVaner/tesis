"""Comprueba el vocabulario 3D sin camara, sin dron y sin MediaPipe.

Construye poses sinteticas en el propio marco del cuerpo y las pasa por el
reconocedor. Lo que se verifica es lo que puede romper el vocabulario:

* que la postura nominal de cada gesto se clasifique como ese gesto;
* que el reposo NO produzca ningun comando;
* que los nueve conos de aceptacion no se solapen;
* que el ruido real de deteccion (0.044 u de torso) no cambie la respuesta;
* que un gesto de estado sostenido se confirme UNA vez y no noventa;
* que un landmark ausente no invente un gesto.

Uso, desde la raiz del repositorio:

    .\\.venv\\Scripts\\python.exe .\\external\\gesture_detection\\tests\\test_body_3d_rules.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

TESTS_DIR = Path(__file__).resolve().parent
GESTURE_DIR = TESTS_DIR.parent
if str(GESTURE_DIR) not in sys.path:
    sys.path.insert(0, str(GESTURE_DIR))

from contracts import Gesture  # noqa: E402
from pose.normalize import (  # noqa: E402
    LEFT_HIP,
    LEFT_SHOULDER,
    LEFT_WRIST,
    N_LANDMARKS,
    RIGHT_HIP,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
)
from recognition.body_3d_rules import (  # noqa: E402
    CONO_DEG,
    DIRECCIONES,
    RUIDO_U,
    Body3DRecognizer,
    separaciones_del_vocabulario,
)

TORSO_M = 0.50
BRAZO_M = 1.05 * TORSO_M
FPS = 30.0

#: Brazos colgando al costado. Es la postura por defecto del operador, y la
#: unica que el sistema ve la mayor parte del tiempo.
REPOSO_DER = (-0.15, -1.0, 0.05)
REPOSO_IZQ = (0.15, -1.0, 0.05)

#: Posturas de los tres gestos de dos manos, en direccion hombro -> muneca.
#: STOP lleva las manos a la LINEA MEDIA: los brazos cruzan hacia adentro. Si
#: salieran paralelos al frente las manos quedarian separadas un ancho de
#: hombros, que no es "manos juntas".
DOS_MANOS = {
    Gesture.DESPEGAR: ((-0.30, 1.0, 0.0), (0.30, 1.0, 0.0), 1.0),
    Gesture.ATERRIZAR: ((-1.0, -0.12, 0.0), (1.0, -0.12, 0.0), 1.0),
    Gesture.STOP: ((0.43, -0.40, 0.80), (-0.43, -0.40, 0.80), 0.98),
}

results: list[tuple[str, bool, str]] = []


def anotar(nombre: str, ok: bool, detalle: str = "") -> None:
    results.append((nombre, bool(ok), detalle))


class FakeLandmark:
    """Lo minimo que `landmarks_to_array` necesita de MediaPipe."""

    def __init__(self, punto, visibilidad: float = 0.95) -> None:
        self.x, self.y, self.z = (float(c) for c in punto)
        self.visibility = visibilidad


def _torso() -> np.ndarray:
    P = np.zeros((N_LANDMARKS, 3))
    P[LEFT_HIP] = (0.13, 0.0, 0.0)
    P[RIGHT_HIP] = (-0.13, 0.0, 0.0)
    P[LEFT_SHOULDER] = (0.19, TORSO_M, 0.0)
    P[RIGHT_SHOULDER] = (-0.19, TORSO_M, 0.0)
    return P


def _brazo(P, lado: str, direccion, largo: float = 1.0) -> np.ndarray:
    d = np.asarray(direccion, dtype=np.float64)
    d = d / np.linalg.norm(d)
    hombro = LEFT_SHOULDER if lado == "left" else RIGHT_SHOULDER
    muneca = LEFT_WRIST if lado == "left" else RIGHT_WRIST
    P[muneca] = P[hombro] + d * BRAZO_M * largo
    return P


def pose(gesto, ruido: float = 0.0, semilla: int = 0, lado: str = "right"):
    """Postura nominal de un gesto, opcionalmente con ruido de deteccion."""
    P = _torso()
    if gesto in DIRECCIONES:
        P = _brazo(P, lado, DIRECCIONES[gesto])
        P = _brazo(P, "left" if lado == "right" else "right",
                   REPOSO_IZQ if lado == "right" else REPOSO_DER)
    elif gesto in DOS_MANOS:
        der, izq, largo = DOS_MANOS[gesto]
        P = _brazo(P, "right", der, largo)
        P = _brazo(P, "left", izq, largo)
    else:                                       # reposo
        P = _brazo(P, "right", REPOSO_DER)
        P = _brazo(P, "left", REPOSO_IZQ)
    if ruido:
        # El ruido esta medido en unidades de torso; aqui se trabaja en metros.
        rng = np.random.default_rng(semilla)
        P = P + rng.normal(0.0, ruido * TORSO_M, P.shape)
    return [FakeLandmark(p) for p in P]


def sostener(landmarks, segundos: float = 2.0):
    """Pasa la misma pose durante `segundos`.

    Devuelve `(ultimo_evento, veces_confirmado)`. Hacen falta los dos porque
    los gestos de estado se confirman una sola vez y despues siguen leyendose
    con `confirmed=False`: mirar solo el ultimo frame los daria por fallados.
    """
    rec = Body3DRecognizer()
    evento = None
    confirmaciones = 0
    for i in range(int(segundos * FPS)):
        evento = rec.update(landmarks, ahora=i / FPS)
        confirmaciones += evento.confirmed
    return evento, confirmaciones


TODOS = list(DIRECCIONES) + list(DOS_MANOS)


# ------------------------------------------------------------------ pruebas


def test_cada_gesto_se_reconoce() -> None:
    for gesto in TODOS:
        evento, confirmaciones = sostener(pose(gesto))
        anotar(
            f"{gesto.value} se reconoce",
            evento.gesture is gesto and confirmaciones >= 1,
            f"leido {evento.gesture.value}, conf {evento.confidence:.2f}",
        )


def test_el_reposo_no_manda_nada() -> None:
    """De pie y relajado el operador NO debe estar pilotando.

    Es el fallo mas caro posible: el brazo colgando queda a 43 grados de
    ABAJO, y si el ruido cruzara esa distancia el dron descenderia solo. Se
    prueba con ruido y con muchas semillas justamente por eso.
    """
    evento, _ = sostener(pose(None))
    anotar(
        "el reposo no produce comando",
        evento.gesture is Gesture.NO_GESTURE and evento.velocity.quieto,
        f"leido {evento.gesture.value}",
    )

    limpios = 0
    leidos: set[str] = set()
    for s in range(50):
        ev, _ = sostener(pose(None, ruido=RUIDO_U, semilla=s))
        if ev.gesture is Gesture.NO_GESTURE:
            limpios += 1
        else:
            leidos.add(ev.gesture.value)
    anotar(
        "el reposo con ruido tampoco",
        limpios == 50,
        f"{limpios}/50 limpios"
        + (f", se colo {sorted(leidos)}" if leidos else ""),
    )


def test_senala_cualquiera_de_los_dos_brazos() -> None:
    """Cada direccion tiene que salir con el brazo derecho y con el izquierdo.

    Con el brazo fijo, IZQUIERDA obligaba a cruzar el pecho con el brazo
    estirado y era practicamente imposible: en una sesion real de 368 s solo
    3 frames de 79 entraron en el cono. Senalando con el brazo que queda cerca,
    ninguna direccion cruza el cuerpo.
    """
    for gesto in DIRECCIONES:
        for lado in ("right", "left"):
            evento, confirmaciones = sostener(pose(gesto, lado=lado))
            anotar(
                f"{gesto.value} con brazo {lado}",
                evento.gesture is gesto and confirmaciones >= 1,
                f"leido {evento.gesture.value}",
            )


#: Postura de ATRAS **medida** sobre una sesion real de 2952 frames: el brazo
#: se abre 0.64 hacia el costado y el codo se dobla hasta 0.70 de extension.
#: Con la definicion isotropica y `EXTENSION_MIN` no se reconocia ni un frame.
ATRAS_REAL = (-0.64, -0.46, -0.61)
ATRAS_REAL_EXTENSION = 0.70


def test_atras_tal_como_sale_de_verdad() -> None:
    """ATRAS con la postura medida, no con la ideal.

    Es la unica direccion que pide extension del hombro, y el hombro no la da
    sola: el brazo se abre al costado y el codo se dobla. Ninguna de las dos
    cosas es corregible pidiendoselo al operador.
    """
    for lado, signo in (("right", 1.0), ("left", -1.0)):
        P = _torso()
        d = (ATRAS_REAL[0] * signo, ATRAS_REAL[1], ATRAS_REAL[2])
        P = _brazo(P, lado, d, ATRAS_REAL_EXTENSION / 1.05)
        P = _brazo(P, "left" if lado == "right" else "right",
                   REPOSO_IZQ if lado == "right" else REPOSO_DER)
        evento, confirmaciones = sostener([FakeLandmark(p) for p in P])
        anotar(
            f"ATRAS real con brazo {lado}",
            evento.gesture is Gesture.ATRAS and confirmaciones >= 1,
            f"leido {evento.gesture.value}",
        )


def test_un_brazo_apenas_atrasado_no_es_ATRAS() -> None:
    """ATRAS pide menos extension que las demas, asi que hay que comprobar que
    no se cuela un brazo simplemente colgando un poco hacia atras: seria el
    dron retrocediendo solo."""
    for grados in (5, 10, 15, 20):
        rad = np.radians(grados)
        P = _torso()
        P = _brazo(P, "right", (-0.15, -np.cos(rad), -np.sin(rad)))
        P = _brazo(P, "left", REPOSO_IZQ)
        evento, _ = sostener([FakeLandmark(p) for p in P])
        anotar(
            f"brazo colgando {grados} deg atras no es ATRAS",
            evento.gesture is Gesture.NO_GESTURE,
            f"leido {evento.gesture.value}",
        )


def test_apuntar_de_lado_no_activa_la_metrica_sagital() -> None:
    """La proyeccion sagital de un brazo horizontal es ruido puro.

    Por eso ATRAS solo compite cuando la componente sagital llega al minimo:
    si no, DERECHA e IZQUIERDA podrian leerse como ATRAS segun el ruido.
    """
    for gesto in (Gesture.DERECHA, Gesture.IZQUIERDA):
        for s in range(15):
            evento, _ = sostener(pose(gesto, ruido=RUIDO_U, semilla=s))
            if evento.gesture is Gesture.ATRAS:
                anotar(f"{gesto.value} nunca se lee como ATRAS", False,
                       f"semilla {s}")
                break
        else:
            anotar(f"{gesto.value} nunca se lee como ATRAS", True, "")


def test_ninguna_direccion_roza_el_brazo_colgando() -> None:
    """El brazo colgando no puede caer dentro de ningun cono.

    Es la comprobacion que impide mover una direccion "para que salga mas
    facil" y acabar con el dron obedeciendo a un operador quieto. ABAJO es el
    que marca el limite: medido, el operador lo hace a 25 deg de la vertical,
    que estaria a 24 del brazo colgando. Por eso se queda en 45 aunque cueste.
    """
    import numpy as np

    from recognition.body_3d_rules import CONO_REPOSO_DEG, DIRECCIONES_U

    for lado, r in (("der", REPOSO_DER), ("izq", REPOSO_IZQ)):
        d = np.asarray(r, float)
        d = d / np.linalg.norm(d)
        cerca, gesto = min(
            (float(np.degrees(np.arccos(np.clip(float(d @ u), -1, 1)))), g.value)
            for g, u in DIRECCIONES_U.items()
        )
        # El cono de reposo se comprueba ANTES que la direccion, asi que basta
        # con que ninguna direccion quede dentro de el.
        anotar(
            f"reposo {lado} fuera de todos los conos",
            cerca > CONO_REPOSO_DEG + CONO_DEG - 2.0,
            f"lo mas cercano es {gesto} a {cerca:.0f} deg",
        )


def test_ninguna_direccion_es_alcanzable_solo_en_teoria() -> None:
    """Cada direccion tiene que salir con la postura MEDIDA del operador.

    Las medianas vienen de 1461 frames de una sesion real. Con los ejes
    ideales, ARRIBA se reconocia 1 frame en 120 s de vuelo.
    """
    medidas = {
        Gesture.ARRIBA: (0.13, 0.90, 0.39),
        Gesture.ADELANTE: (0.0, -0.09, 1.00),
        Gesture.IZQUIERDA: (0.96, 0.0, 0.29),
        Gesture.DERECHA: (-0.93, -0.06, 0.37),
    }
    for gesto, direccion in medidas.items():
        P = _torso()
        P = _brazo(P, "right", direccion)
        P = _brazo(P, "left", REPOSO_IZQ)
        evento, confirmaciones = sostener([FakeLandmark(p) for p in P])
        anotar(
            f"{gesto.value} con la postura medida",
            evento.gesture is gesto and confirmaciones >= 1,
            f"leido {evento.gesture.value}",
        )


def test_los_conos_no_se_solapan() -> None:
    a, b, ang = separaciones_del_vocabulario()[0]
    anotar(
        "los conos de direccion no se solapan",
        ang > 2 * CONO_DEG,
        f"el par mas cercano es {a.value}/{b.value} a {ang:.0f} deg, "
        f"cono {2 * CONO_DEG:.0f} deg",
    )


def test_aguanta_el_ruido_de_deteccion() -> None:
    """Con el ruido real medido, la respuesta no debe cambiar.

    0.044 u de torso por eje y landmark es lo que da MediaPipe monocular en
    condiciones buenas. Si el vocabulario no lo aguanta, no sirve.

    El modelo es **mas duro que la realidad**: aqui el ruido es independiente
    en cada landmark, y en la practica el error de MediaPipe esta correlacionado
    a lo largo del cuerpo. Perturbar las caderas de forma independiente gira el
    marco corporal entero, que es el termino que domina.
    """
    for gesto in TODOS:
        aciertos = sum(
            sostener(pose(gesto, ruido=RUIDO_U, semilla=s))[0].gesture is gesto
            for s in range(20)
        )
        anotar(
            f"{gesto.value} aguanta el ruido",
            aciertos == 20,
            f"{aciertos}/20 repeticiones",
        )


def test_un_gesto_de_estado_se_confirma_una_vez() -> None:
    """Sostener DESPEGAR tres segundos es un despegue, no noventa."""
    rec = Body3DRecognizer()
    landmarks = pose(Gesture.DESPEGAR)
    veces = sum(
        rec.update(landmarks, ahora=i / FPS).confirmed
        for i in range(int(3 * FPS))
    )
    anotar("DESPEGAR se confirma una sola vez", veces == 1, f"{veces} veces")


def test_la_navegacion_es_continua() -> None:
    """ADELANTE sostenido tiene que seguir dando referencia de velocidad."""
    rec = Body3DRecognizer()
    landmarks = pose(Gesture.ADELANTE)
    total = int(3 * FPS)
    con_velocidad = sum(
        not rec.update(landmarks, ahora=i / FPS).velocity.quieto
        for i in range(total)
    )
    anotar(
        "ADELANTE mantiene la referencia",
        con_velocidad > 0.85 * total,
        f"{con_velocidad}/{total} frames",
    )


def test_sin_pose_no_hay_comando() -> None:
    evento = Body3DRecognizer().update(None, ahora=0.0)
    anotar(
        "sin pose no hay comando",
        evento.gesture is Gesture.NO_GESTURE and not evento.engaged,
        "",
    )


def test_un_landmark_ausente_no_inventa_un_gesto() -> None:
    """Una muneca `NaN` producia ARRIBA sobre una grabacion real.

    Toda comparacion con `NaN` es falsa, de modo que las guardas de extension
    y de reposo se saltaban solas y los seis angulos salian `NaN`: el primero
    de la lista ganaba con el cono vacio. Un dato plausible y falso es peor
    que no tener dato.
    """
    for indice, nombre in ((RIGHT_WRIST, "muneca der"),
                           (LEFT_WRIST, "muneca izq"),
                           (RIGHT_SHOULDER, "hombro der")):
        landmarks = pose(Gesture.ARRIBA)
        landmarks[indice].x = float("nan")
        evento, _ = sostener(landmarks)
        anotar(
            f"{nombre} ausente no inventa gesto",
            evento.gesture is Gesture.NO_GESTURE and evento.velocity.quieto,
            f"leido {evento.gesture.value}",
        )


def main() -> int:
    print("Vocabulario 3D: comprobacion sin camara y sin dron\n")
    print(f"  cono de aceptacion {CONO_DEG:.0f} deg")
    print(f"  ruido de referencia {RUIDO_U} u de torso")
    peor = separaciones_del_vocabulario()[0]
    print(f"  par mas cercano: {peor[0].value}/{peor[1].value} "
          f"a {peor[2]:.0f} deg\n")

    for prueba in (
        test_cada_gesto_se_reconoce,
        test_el_reposo_no_manda_nada,
        test_senala_cualquiera_de_los_dos_brazos,
        test_atras_tal_como_sale_de_verdad,
        test_un_brazo_apenas_atrasado_no_es_ATRAS,
        test_apuntar_de_lado_no_activa_la_metrica_sagital,
        test_ninguna_direccion_roza_el_brazo_colgando,
        test_ninguna_direccion_es_alcanzable_solo_en_teoria,
        test_los_conos_no_se_solapan,
        test_aguanta_el_ruido_de_deteccion,
        test_un_gesto_de_estado_se_confirma_una_vez,
        test_la_navegacion_es_continua,
        test_sin_pose_no_hay_comando,
        test_un_landmark_ausente_no_inventa_un_gesto,
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
    print("Esto valida la geometria del vocabulario, no que un operador real "
          "consiga producirlo: para eso esta --practica.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
