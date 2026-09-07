"""Vocabulario 3D: reglas geométricas sobre la pose en el marco del cuerpo.

Es la conversión directa del detector corporal 2D de `gesture_detector.py`, con
dos diferencias que sólo la profundidad permite:

* **ADELANTE y ATRAS existen.** En 2D se proyectan sobre el mismo píxel que
  REPOSO, y por eso el vocabulario de dos dimensiones nunca los tuvo.
* **Los criterios no dependen del ángulo del operador.** El criterio 2D
  `right_arm_extended` mide en píxeles de imagen: al girarse el sujeto, el
  ancho de hombros se encoge y las distancias con él. Medido sobre la misma
  pose vista desde distintos ángulos, el criterio 3D en unidades de torso se
  mantiene plano mientras el 2D se degrada.

Diseño: dos canales
-------------------
Obaid et al. (2016) documentan la colisión que aparece al meter navegación y
comandos de estado en el mismo clasificador: *subir* y *despegar* producen el
mismo gesto candidato. Aquí se separan por el numero de manos, que es la
desambiguacion que ellos mismos proponen:

* **Un brazo extendido = navegacion.** La direccion del brazo dice hacia donde.
  Senala cualquiera de los dos, el que quede mas lejos de la vertical; el otro
  se queda colgando.
* **Las dos manos = estado.** DESPEGAR, ATERRIZAR, STOP.

Unidades
--------
Todo se mide en **unidades de torso** sobre la pose ya canonicalizada
(`pose/normalize.py`), con los ejes del cuerpo: `+X` a la izquierda del sujeto,
`+Y` arriba, `+Z` hacia donde mira. Asi los umbrales valen igual para una
persona de 1.60 m y para una de 1.90 m.

El ruido de referencia es **0.044 unidades de torso por eje y landmark**,
medido sobre grabaciones reales. Cada umbral de este modulo lleva anotado a
cuantas sigmas queda de la postura nominal del gesto.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from contracts import (
    GESTOS_DE_ESTADO,
    Gesture,
    GestureEvent,
    VelocityIntent,
)
from pose.normalize import (
    LEFT_SHOULDER,
    LEFT_WRIST,
    MIN_CONDITION,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
    ScaleEstimator,
    body_frame,
    landmarks_to_array,
    normalize,
)

#: Ruido de deteccion por eje y landmark, en unidades de torso. Medido.
RUIDO_U = 0.044


# --------------------------------------------------------------- direcciones

#: Hacia donde apunta el brazo extendido en cada comando de navegacion, en el
#: marco del cuerpo. Senala cualquiera de los dos: ver `brazo_que_senala`. Es
#: la tabla que define el vocabulario; para cambiarlo se edita aqui y en ningun
#: otro sitio.
#:
#: ATRAS no es `[0, 0, -1]`. Apuntar recto hacia atras con el brazo estirado
#: pide unos 90 grados de extension del hombro y la articulacion da unos 50-60.
#: Va abajo-y-atras.
#:
#: Estuvo primero a 60 grados de la vertical y era **demasiado**: en una sesion
#: real de 368 s, de 23 frames en que ATRAS fue la direccion mas cercana el
#: mejor se quedo a 30 grados, con el cono en 22, y no se confirmo ni una vez.
#: Ahora esta a 53 grados. Sigue siendo la direccion mas exigente del
#: vocabulario y el limite inferior es duro: por debajo de 44 el cono chocaria
#: con el del brazo colgando.
#: Las direcciones estan **medidas**, no supuestas. Sobre 1461 frames de una
#: sesion real con el brazo estirado y el otro quieto, la mediana de lo que
#: hace el operador se desvia bastante de los ejes ideales:
#:
#:     gesto        medido               ideal          desvio
#:     ARRIBA       [0, +0.92, +0.40]    [0, +1, 0]     23 deg
#:     DERECHA      [-0.93, 0, +0.37]    [-1, 0, 0]     22 deg
#:     IZQUIERDA    [+0.96, 0, +0.29]    [+1, 0, 0]     17 deg
#:     ADELANTE     [0, -0.09, +1.00]    [0, 0, +1]      5 deg
#:
#: El patron es el mismo en todos: **el brazo se va hacia adelante**. El hombro
#: no trabaja en el plano frontal, y levantar o abrir el brazo lo lleva al
#: frente. Con los ejes ideales, ARRIBA quedaba a 26 grados de mediana con el
#: cono en 22 y practicamente no se reconocia: 1 frame en 120 s de vuelo.
#:
#: Recentrar sube el reconocimiento de 823 a 1101 frames sobre esa sesion
#: (ARRIBA 89 -> 143, DERECHA 194 -> 380).
#:
#: Dos NO se mueven, y por motivos distintos:
#:
#: * **ABAJO** esta fijado por geometria, no por comodidad. Medido daba 25 deg
#:   de la vertical, que lo deja a 24 del brazo colgando: el dron descenderia
#:   solo. Tiene que quedarse a 45. Si cuesta hacerlo, hay que exagerarlo, no
#:   bajar el umbral.
#: * **ADELANTE** se desvia solo 5 deg, y moverlo esos 5 estrecharia el par
#:   ABAJO/ADELANTE de 45 a 40, por debajo de los dos conos juntos.
#:
#: IZQUIERDA y DERECHA se simetrizan entre si: son el mismo gesto con el otro
#: brazo, y no hay razon para que difieran.
DIRECCIONES: dict[Gesture, tuple[float, float, float]] = {
    Gesture.ARRIBA: (0.0, 0.92, 0.40),
    Gesture.ABAJO: (0.0, -0.7, 0.7),
    Gesture.ADELANTE: (0.0, 0.0, 1.0),
    Gesture.ATRAS: (0.0, -0.6, -0.8),
    Gesture.IZQUIERDA: (0.944, 0.0, 0.33),
    Gesture.DERECHA: (-0.944, 0.0, 0.33),
}

#: Comando de velocidad de cada gesto, normalizado, en ejes del dron
#: (`vx` adelante, `vy` izquierda, `vz` arriba).
#:
#: **No se deriva del vector del brazo.** ABAJO apunta abajo-y-al-frente
#: porque abajo-a-secas es la postura de reposo; su significado, sin embargo,
#: es descender y nada mas. El gesto se reconoce por su direccion y se ejecuta
#: por su significado.
VELOCIDADES: dict[Gesture, VelocityIntent] = {
    Gesture.ADELANTE: VelocityIntent(vx=1.0),
    Gesture.ATRAS: VelocityIntent(vx=-1.0),
    Gesture.IZQUIERDA: VelocityIntent(vy=1.0),
    Gesture.DERECHA: VelocityIntent(vy=-1.0),
    Gesture.ARRIBA: VelocityIntent(vz=1.0),
    Gesture.ABAJO: VelocityIntent(vz=-1.0),
}


# ------------------------------------------------------------------ umbrales

#: Semiangulo del cono de aceptacion de una direccion, en grados.
#:
#: El par mas cercano del vocabulario es ABAJO/ADELANTE, separado 45 grados, asi
#: que el cono no puede pasar de 22.5 sin que se solapen. Con el brazo a 1.05
#: unidades de torso del hombro, el ruido angular es atan(0.044*raiz(2)/1.05) =
#: 3.4 grados, de modo que 22 grados son 6.5 sigma.
CONO_DEG = 22.0

#: El mejor candidato tiene que ganarle al segundo por este margen. Evita que
#: un brazo puesto justo en la frontera ABAJO/ADELANTE parpadee entre los dos.
MARGEN_DEG = 6.0

#: Cono alrededor de la vertical hacia abajo dentro del cual el brazo que
#: senala se considera colgando, y por tanto no senala nada. Queda pegado al
#: cono de ABAJO sin solaparse: entre los dos no hay ningun gesto.
CONO_REPOSO_DEG = 22.0

#: Cono equivalente para el brazo que NO senala. Es mucho mas ancho a
#: proposito: su unico trabajo es separar los gestos de una mano de los de dos,
#: y el brazo quieto de un operador real oscila bastante. El gesto de dos manos
#: mas cercano a la vertical es ATERRIZAR, con el brazo a 83 grados, asi que
#: 45 no se come ninguno. Con 22 fallaba: el brazo colgando nominal ya esta a
#: 9 grados de la vertical y el ruido de deteccion lo saca del cono.
CONO_BRAZO_QUIETO_DEG = 45.0

#: Distancia minima muneca-hombro para considerar el brazo extendido, en
#: unidades de torso. Medido: un brazo estirado da 0.95-1.10.
EXTENSION_MIN = 0.85

# --------------------------------------------------------------- ATRAS
#
# ATRAS es la unica direccion que pide extension del hombro, y el hombro no la
# da sola: al echar el brazo atras se abre hacia el costado y el codo se dobla.
# No es una opinion, esta medido sobre una sesion real de 2952 frames.
#
#   los 88 frames en que ATRAS fue la direccion mas cercana:
#     direccion mediana   [-0.64, -0.46, -0.61]   <- 0.64 de apertura lateral
#     extension mediana    0.70                   <- el codo doblado
#     pasan EXTENSION_MIN  2 de 88
#
#   con el brazo estirado, en 1976 frames, dir_z no bajo nunca de -0.38
#
# De ahi las dos excepciones de abajo. Las demas direcciones se hacen con el
# brazo recto y en el plano que uno quiera, y no necesitan ninguna.

#: Extension minima para ATRAS. Mas baja porque el codo se dobla; sigue muy por
#: encima del 0.40 de un brazo recogido contra el pecho.
ATRAS_EXTENSION_MIN = 0.60

#: ATRAS se compara **solo en el plano sagital** `(Y, Z)`, ignorando la
#: apertura lateral. Es lo que hace falta: en el plano sagital el gesto medido
#: cae a 0.4 grados del objetivo, y en 3D se quedaba a 38 por culpa de una
#: apertura que es anatomicamente obligatoria.
#:
#: La proyeccion es degenerada para un brazo que apunta de lado —su componente
#: sagital es ruido puro— asi que ATRAS solo compite cuando esa componente
#: llega a este minimo. DERECHA e IZQUIERDA valen 0 y quedan fuera.
ATRAS_SAGITAL_MINIMO = 0.50

#: DESPEGAR: las dos munecas por encima de los hombros. Nominal ~1.0 u sobre el
#: hombro, umbral 0.25 -> 12 sigma.
DESPEGAR_ALTURA = 0.25

#: ATERRIZAR (brazos en cruz): separacion lateral minima muneca-hombro y
#: desnivel maximo. Nominal 1.04 u de separacion -> 5.5 sigma sobre 0.70.
#:
#: El desnivel es generoso porque nadie sostiene una cruz horizontal a 4 cm:
#: el brazo cae. Lo que hay que evitar es confundirla con DESPEGAR, y eso ya
#: esta resuelto por el orden de comprobacion, que mira DESPEGAR primero.
CRUZ_LATERAL = 0.70
CRUZ_DESNIVEL = 0.55

#: STOP (manos juntas al frente): las munecas cerca entre si y por delante del
#: cuerpo. Es el gesto que el detector 2D confunde con una mano delante y otra
#: detras del pecho, porque en la imagen caen en el mismo pixel.
STOP_SEPARACION = 0.60
STOP_FRENTE = 0.50

#: Tiempo que hay que sostener un gesto para que se confirme. En segundos y no
#: en frames a proposito: asi el detector se comporta igual a 15 que a 30 fps.
#: Los comandos de estado piden mas porque no se pueden deshacer.
CONFIRMACION_NAVEGACION_S = 0.20
CONFIRMACION_ESTADO_S = 0.80

#: Visibilidad media minima de los landmarks clave para aceptar el frame.
CALIDAD_MINIMA = 0.55

_CLAVE = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_WRIST, RIGHT_WRIST)


def _unitarias() -> dict[Gesture, np.ndarray]:
    return {
        g: np.asarray(d, dtype=np.float64) / np.linalg.norm(d)
        for g, d in DIRECCIONES.items()
    }


DIRECCIONES_U = _unitarias()
_ABAJO_VERTICAL = np.array([0.0, -1.0, 0.0])


def extension_minima(gesto: Gesture) -> float:
    """Extension exigida al brazo para ese gesto, en unidades de torso."""
    return ATRAS_EXTENSION_MIN if gesto is Gesture.ATRAS else EXTENSION_MIN


def _angulo_sagital(a: np.ndarray, b: np.ndarray) -> float | None:
    """Angulo entre dos direcciones ignorando la componente lateral.

    Devuelve `None` si la proyeccion sagital de `a` es tan corta que su
    direccion no significa nada.
    """
    pa, pb = a[1:], b[1:]
    na = float(np.linalg.norm(pa))
    nb = float(np.linalg.norm(pb))
    if na < ATRAS_SAGITAL_MINIMO or nb < 1e-9:
        return None
    return float(np.degrees(np.arccos(
        np.clip(float(pa @ pb) / (na * nb), -1.0, 1.0))))


def angulos_a_direcciones(d: np.ndarray) -> list[tuple[float, Gesture]]:
    """Distancia angular de un brazo a cada direccion, de menor a mayor.

    ATRAS usa la metrica sagital y puede no aparecer; el resto usan el angulo
    en 3D.
    """
    salida: list[tuple[float, Gesture]] = []
    for g, u in DIRECCIONES_U.items():
        if g is Gesture.ATRAS:
            ang = _angulo_sagital(d, u)
            if ang is None:
                continue
        else:
            ang = _angulo_deg(d, u)
        salida.append((ang, g))
    return sorted(salida, key=lambda p: p[0])


def separaciones_del_vocabulario() -> list[tuple[Gesture, Gesture, float]]:
    """Angulo entre cada par de direcciones, de menor a mayor.

    Es la comprobacion que dice si el vocabulario es reconocible: si algun par
    baja de `2 * CONO_DEG`, los dos conos se solapan y hay ambiguedad.
    """
    items = list(DIRECCIONES_U.items())
    pares = []
    for i, (ga, da) in enumerate(items):
        for gb, db in items[i + 1:]:
            ang = np.degrees(np.arccos(np.clip(float(da @ db), -1.0, 1.0)))
            pares.append((ga, gb, float(ang)))
    return sorted(pares, key=lambda p: p[2])


# ------------------------------------------------------------------- rasgos


@dataclass
class Rasgos:
    """Lo que el clasificador mira, en unidades de torso y marco del cuerpo."""

    pose: np.ndarray            #: (K, 3) canonicalizada y normalizada
    condicion: float            #: calidad del marco corporal
    calidad: float              #: visibilidad media de los landmarks clave
    escala_m: float             #: largo de torso de la sesion

    @property
    def brazo_der(self) -> np.ndarray:
        return self.pose[RIGHT_WRIST] - self.pose[RIGHT_SHOULDER]

    @property
    def brazo_izq(self) -> np.ndarray:
        return self.pose[LEFT_WRIST] - self.pose[LEFT_SHOULDER]


def _direccion(v: np.ndarray) -> tuple[np.ndarray, float]:
    n = float(np.linalg.norm(v))
    if n < 1e-9:
        return np.zeros(3), 0.0
    return v / n, n


def _angulo_deg(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.degrees(np.arccos(np.clip(float(a @ b), -1.0, 1.0))))


def _en_reposo(brazo: np.ndarray, cono_deg: float) -> bool:
    """Brazo colgando al costado, dentro de `cono_deg` de la vertical."""
    d, largo = _direccion(brazo)
    if largo < 1e-6:
        return True
    return _angulo_deg(d, _ABAJO_VERTICAL) <= cono_deg


@dataclass
class BrazoActivo:
    """El brazo que senala, elegido entre los dos."""

    lado: str                   #: "der" o "izq"
    direccion: np.ndarray       #: unitaria, en el marco del cuerpo
    largo: float                #: muneca-hombro, en unidades de torso
    angulo_vertical: float      #: separacion de la vertical hacia abajo
    angulo_del_otro: float      #: lo mismo para el brazo que se queda parado


def brazo_que_senala(r: "Rasgos") -> BrazoActivo:
    """Cual de los dos brazos senala: el que mas se separa de la vertical.

    Antes senalaba siempre el derecho y el izquierdo tenia que estar parado.
    Eso hacia IZQUIERDA casi imposible: cruzar el pecho con el brazo derecho
    **estirado** pide una aduccion que el hombro no da. Medido sobre una sesion
    real de 368 s, el mejor intento se quedo a 19 grados del objetivo y solo 3
    frames de 79 cayeron dentro del cono de 22.

    Con cualquiera de los dos brazos, cada direccion se hace con el brazo que
    le queda cerca y ninguna cruza el cuerpo.

    Elegir por *distancia a la vertical* y no por un umbral evita un problema
    de frontera: ABAJO cae justo a 45 grados, que es el limite de "parado".
    """
    dd, largo_d = _direccion(r.brazo_der)
    di, largo_i = _direccion(r.brazo_izq)
    ang_d = _angulo_deg(dd, _ABAJO_VERTICAL) if largo_d > 1e-6 else 0.0
    ang_i = _angulo_deg(di, _ABAJO_VERTICAL) if largo_i > 1e-6 else 0.0
    if ang_d >= ang_i:
        return BrazoActivo("der", dd, largo_d, ang_d, ang_i)
    return BrazoActivo("izq", di, largo_i, ang_i, ang_d)


# -------------------------------------------------------------- clasificador


def clasificar(r: Rasgos) -> tuple[Gesture, float, dict[str, float]]:
    """Gesto crudo del frame, su confianza en `[0, 1]` y las puntuaciones.

    El orden importa: los gestos de dos manos se comprueban antes que los de
    navegacion, porque un brazo levantado forma parte de DESPEGAR y no debe
    leerse como ARRIBA mientras el otro tambien lo esta.
    """
    scores: dict[str, float] = {}
    if r.calidad < CALIDAD_MINIMA:
        return Gesture.NO_GESTURE, 0.0, scores

    P = r.pose
    md, mi = P[RIGHT_WRIST], P[LEFT_WRIST]
    hd, hi = P[RIGHT_SHOULDER], P[LEFT_SHOULDER]

    # --- canal de eventos: las dos manos ---------------------------------
    alto_d = md[1] - hd[1]
    alto_i = mi[1] - hi[1]
    if alto_d > DESPEGAR_ALTURA and alto_i > DESPEGAR_ALTURA:
        holgura = min(alto_d, alto_i) - DESPEGAR_ALTURA
        scores[Gesture.DESPEGAR.value] = _confianza(holgura, 0.50)
        return Gesture.DESPEGAR, scores[Gesture.DESPEGAR.value], scores

    lat_d = hd[0] - md[0]          # positivo si la mano derecha sale al costado
    lat_i = mi[0] - hi[0]
    if (
        lat_d > CRUZ_LATERAL
        and lat_i > CRUZ_LATERAL
        and abs(alto_d) < CRUZ_DESNIVEL
        and abs(alto_i) < CRUZ_DESNIVEL
    ):
        holgura = min(lat_d, lat_i) - CRUZ_LATERAL
        scores[Gesture.ATERRIZAR.value] = _confianza(holgura, 0.35)
        return Gesture.ATERRIZAR, scores[Gesture.ATERRIZAR.value], scores

    separacion = float(np.linalg.norm(md - mi))
    frente = min(md[2], mi[2])
    if separacion < STOP_SEPARACION and frente > STOP_FRENTE:
        holgura = min(STOP_SEPARACION - separacion, frente - STOP_FRENTE)
        scores[Gesture.STOP.value] = _confianza(holgura, 0.30)
        return Gesture.STOP, scores[Gesture.STOP.value], scores

    # --- canal continuo: un brazo senala ---------------------------------
    # Senala uno cualquiera de los dos; el otro tiene que estar parado al
    # costado. Es lo que separa ARRIBA de DESPEGAR y DERECHA de ATERRIZAR sin
    # mirar nada mas.
    brazo = brazo_que_senala(r)
    if brazo.angulo_del_otro > CONO_BRAZO_QUIETO_DEG:
        return Gesture.NO_GESTURE, 0.0, scores      # los dos brazos activos
    if brazo.angulo_vertical <= CONO_REPOSO_DEG:
        return Gesture.NO_GESTURE, 0.0, scores      # los dos brazos colgando

    angulos = angulos_a_direcciones(brazo.direccion)
    for ang, g in angulos:
        scores[g.value] = round(ang, 1)
    if len(angulos) < 2:
        return Gesture.NO_GESTURE, 0.0, scores
    mejor_ang, mejor = angulos[0]
    segundo_ang = angulos[1][0]
    if mejor_ang > CONO_DEG or (segundo_ang - mejor_ang) < MARGEN_DEG:
        return Gesture.NO_GESTURE, 0.0, scores

    # La extension se mira DESPUES de saber que direccion es, porque ATRAS
    # exige menos: el codo se dobla al echar el brazo atras y no hay forma de
    # evitarlo.
    if brazo.largo < extension_minima(mejor):
        return Gesture.NO_GESTURE, 0.0, scores

    return mejor, _confianza(CONO_DEG - mejor_ang, CONO_DEG), scores


def _confianza(holgura: float, escala: float) -> float:
    """Holgura sobre el umbral, saturada en 1. No es una probabilidad."""
    if escala <= 0:
        return 0.0
    return float(np.clip(holgura / escala, 0.0, 1.0))


# ------------------------------------------------------------- diagnostico


@dataclass
class Medida:
    """Una condicion del vocabulario, con su valor actual y su umbral."""

    etiqueta: str
    valor: float
    umbral: float
    sentido: str                #: ">=" si el valor debe superar el umbral
    unidad: str = "u"

    @property
    def cumple(self) -> bool:
        return (
            self.valor >= self.umbral
            if self.sentido == ">="
            else self.valor <= self.umbral
        )

    @property
    def holgura(self) -> float:
        """Cuanto sobra (positivo) o cuanto falta (negativo)."""
        return (
            self.valor - self.umbral
            if self.sentido == ">="
            else self.umbral - self.valor
        )

    def __str__(self) -> str:
        return (f"{self.etiqueta} {self.valor:.2f} {self.sentido} "
                f"{self.umbral:.2f} {self.unidad}")


def diagnostico(r: Rasgos) -> dict[str, list[Medida]]:
    """Todas las condiciones del vocabulario evaluadas sobre un frame.

    `clasificar` responde *que* gesto hay; esto responde **por que no hay
    otro**, que es lo que hace falta para afinar un umbral o para entender por
    que un operador no consigue producir un gesto. Es diagnostico: no decide
    nada y no lo consume el controlador.
    """
    P = r.pose
    md, mi = P[RIGHT_WRIST], P[LEFT_WRIST]
    hd, hi = P[RIGHT_SHOULDER], P[LEFT_SHOULDER]
    alto_d, alto_i = md[1] - hd[1], mi[1] - hi[1]

    brazo = brazo_que_senala(r)
    angulos = angulos_a_direcciones(brazo.direccion)
    direcciones = [
        Medida(g.value, ang, CONO_DEG, "<=", "deg") for ang, g in angulos
    ]
    otro = "izq" if brazo.lado == "der" else "der"
    # El umbral de extension depende de la direccion candidata, asi que el
    # panel tiene que mostrar el que se le va a aplicar y no el generico.
    exigida = extension_minima(angulos[0][1]) if angulos else EXTENSION_MIN

    return {
        "encuadre": [
            Medida("visibilidad", r.calidad, CALIDAD_MINIMA, ">=", ""),
            Medida("marco corporal", r.condicion, MIN_CONDITION, ">=", ""),
        ],
        "brazo_activo": [
            Medida(f"extension ({brazo.lado})", brazo.largo, exigida, ">="),
            Medida("fuera del reposo", brazo.angulo_vertical,
                   CONO_REPOSO_DEG, ">=", "deg"),
        ],
        "brazo_parado": [
            Medida(f"al costado ({otro})", brazo.angulo_del_otro,
                   CONO_BRAZO_QUIETO_DEG, "<=", "deg"),
        ],
        "direcciones": direcciones,
        "dos_manos": [
            Medida("DESPEGAR alto der", alto_d, DESPEGAR_ALTURA, ">="),
            Medida("DESPEGAR alto izq", alto_i, DESPEGAR_ALTURA, ">="),
            Medida("ATERRIZAR lat der", hd[0] - md[0], CRUZ_LATERAL, ">="),
            Medida("ATERRIZAR lat izq", mi[0] - hi[0], CRUZ_LATERAL, ">="),
            Medida("STOP separacion", float(np.linalg.norm(md - mi)),
                   STOP_SEPARACION, "<="),
            Medida("STOP al frente", float(min(md[2], mi[2])),
                   STOP_FRENTE, ">="),
        ],
    }


# ------------------------------------------------------------ reconocedor


class Body3DRecognizer:
    """Convierte landmarks de MediaPipe en `GestureEvent` confirmados.

    Mantiene dos estados propios: la escala corporal del operador, que se
    estima durante los primeros segundos, y la persistencia temporal del gesto
    actual. Sin persistencia, un frame malo entre dos buenos produce una orden
    de vuelo espuria.
    """

    def __init__(self, source: str = "webcam") -> None:
        self.source = source
        self.scale = ScaleEstimator()
        self._candidato = Gesture.NO_GESTURE
        self._desde = 0.0
        self._confirmado = Gesture.NO_GESTURE
        self._ya_emitido = False
        #: Rasgos del ultimo `update`, o `None` si el frame no era utilizable.
        #: Los expone para que un diagnostico no tenga que volver a
        #: canonicalizar: repetir la llamada anadiria una segunda observacion
        #: de escala por frame, que sesgaria el calentamiento.
        self.ultimos_rasgos: Rasgos | None = None

    def reset(self) -> None:
        self._candidato = Gesture.NO_GESTURE
        self._confirmado = Gesture.NO_GESTURE
        self._desde = 0.0
        self._ya_emitido = False
        self.ultimos_rasgos = None

    @property
    def listo(self) -> bool:
        """La escala corporal ya es estable."""
        return self.scale.ready

    def rasgos(self, world_landmarks) -> Rasgos | None:
        """Pose canonicalizada y normalizada, o `None` si no es utilizable."""
        world, visibility = landmarks_to_array(world_landmarks)
        if world.shape[0] == 0:
            return None
        frame = body_frame(world, visibility)
        self.scale.observe(frame)
        if frame is None or not frame.valid:
            return None
        escala = self.scale.scale_m
        if not np.isfinite(escala) or escala <= 1e-6:
            return None
        pose = normalize(frame.apply(world), escala)

        # Sin los cuatro landmarks que mira el clasificador no hay frame.
        #
        # No es defensa preventiva: un `NaN` **inventa un gesto**. Toda
        # comparacion con `NaN` es falsa, asi que las guardas de extension y de
        # reposo se saltan solas, los seis angulos salen `NaN`, y el gesto que
        # queda primero en la lista se declara ganador con el cono vacio. Sobre
        # una grabacion real esto producia ARRIBA con la muneca derecha
        # ausente. Es preferible no dar dato a dar uno plausible y falso.
        if not np.all(np.isfinite(pose[list(_CLAVE)])):
            return None

        calidad = float(np.mean(visibility[list(_CLAVE)]))
        return Rasgos(pose, frame.condition, calidad, escala)

    def update(self, world_landmarks, ahora: float | None = None) -> GestureEvent:
        ahora = time.monotonic() if ahora is None else ahora
        r = self.rasgos(world_landmarks)
        self.ultimos_rasgos = r
        if r is None:
            return self._emitir(Gesture.NO_GESTURE, 0.0, ahora, {}, 0.0, False)

        crudo, confianza, scores = clasificar(r)
        enganchado = r.calidad >= CALIDAD_MINIMA
        return self._emitir(crudo, confianza, ahora, scores, r.calidad, enganchado)

    def _emitir(
        self,
        crudo: Gesture,
        confianza: float,
        ahora: float,
        scores: dict,
        calidad: float,
        enganchado: bool,
    ) -> GestureEvent:
        if crudo is not self._candidato:
            self._candidato = crudo
            self._desde = ahora
            self._ya_emitido = False

        de_estado = crudo in GESTOS_DE_ESTADO
        espera = CONFIRMACION_ESTADO_S if de_estado else CONFIRMACION_NAVEGACION_S
        sostenido = ahora - self._desde
        if sostenido >= espera:
            self._confirmado = crudo

        confirmado = self._confirmado is crudo and crudo is not Gesture.NO_GESTURE

        # Un gesto de estado se confirma UNA vez por gesto. Sostener DESPEGAR
        # medio segundo mas no debe pedir un segundo despegue; sostener
        # ADELANTE si debe seguir produciendo referencia de velocidad.
        if confirmado and de_estado:
            if self._ya_emitido:
                confirmado = False
            else:
                self._ya_emitido = True

        velocidad = (
            VELOCIDADES.get(crudo, VelocityIntent())
            if self._confirmado is crudo
            else VelocityIntent()
        )
        scores = dict(scores)
        scores["sostenido_s"] = round(sostenido, 3)
        scores["falta_s"] = round(max(espera - sostenido, 0.0), 3)

        return GestureEvent(
            gesture=crudo,
            confidence=confianza,
            confirmed=confirmado,
            engaged=enganchado,
            velocity=velocidad,
            timestamp=ahora,
            source=self.source,
            scores=scores,
            landmark_quality=calidad,
        )
