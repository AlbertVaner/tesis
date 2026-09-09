"""Marco corporal: la pose vista desde el cuerpo y no desde la cámara.

`pose_world_landmarks` viene en un marco **alineado con la cámara**: `x` a la
derecha, `y` abajo, `z` alejándose de *esa* cámara. La consecuencia es que la
misma pose, vista desde dos cámaras separadas un ángulo, produce dos juegos de
números distintos — girados justamente ese ángulo.

Medido sobre una grabación real, simulando una segunda cámara del anillo:

    ángulo entre cámaras    sin canonicalizar    canonicalizado
           10°                    10.8 %             0.00 %
           60° (adyacentes)       62.0 %             0.00 %
          120°                   107.4 %             0.00 %

Un 62 % es del orden del movimiento entero: cambiar de cámara a mitad de un
gesto corrompería cualquier ventana temporal de clasificación. Canonicalizar lo
elimina.

Qué hace
--------
Construye ejes a partir del **propio cuerpo**: origen en el centro de las
caderas, `X` de cadera derecha a izquierda, `Y` hacia los hombros, `Z` el
producto vectorial. Lo que queda depende de la pose y no del punto de vista ni
de la estatura.

Hace falta con una cámara o con seis
------------------------------------
No es una pieza de la idea de «elegir la mejor cámara»: es el paso previo a
cualquier clasificador de gestos, y la literatura lo da por hecho (Ibañez et
al. centran y normalizan por escala corporal antes de clasificar). Con una sola
cámara ya sirve, porque vuelve comparables a dos sujetos de estatura distinta.

Lo que NO arregla
-----------------
**Canonicalizar no mejora una vista mala; puede empeorarla.** El marco se
construye a partir de cuatro landmarks, y si el sujeto está de perfil el ancho
de caderas se desploma: la dirección de `X` pasa a ser ruido y toda la pose
queda girada un ángulo arbitrario. Por eso `MarcoCorporal` expone su
`condicion` y su `valido`, y por eso un marco mal condicionado es exactamente
una vista que no conviene elegir.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

from .landmarks import INDICE

# Landmarks que definen el marco. Si cualquiera falta o no se ve, no hay marco.
CADERA_IZQ = INDICE["left_hip"]
CADERA_DER = INDICE["right_hip"]
HOMBRO_IZQ = INDICE["left_shoulder"]
HOMBRO_DER = INDICE["right_shoulder"]

# Ancho de caderas dividido por largo de torso. Por debajo de esto la dirección
# lateral está mal determinada y el marco gira de forma arbitraria.
#
# Fijado sobre dos grabaciones reales de 60 s. De frente la condición ronda
# 0.41-0.43 de mediana. Lo que hay por debajo del umbral es catastrófico, no
# mediocre:
#
#     umbral   frames que pasan   error de los que pasan   de los que NO
#      0.10        99.8 %               13.4 %                 33.9 %
#      0.18        97.9 %               13.0 %                 30.4 %
#      0.30        77.8 %               10.2 %                 24.7 %
#
# **Es una puerta de validez, no un criterio de calidad.** Rechaza poco (un
# 1-2 %) y lo que rechaza tiene un error del 30 %, tres veces la media: son
# frames en los que el marco está roto y la pose sale girada al azar. Pero no
# distingue una vista buena de una regular, y no hay que usarlo para eso: para
# ordenar vistas, la `visibility` del modelo predice el error mucho mejor
# (rho = -0.75 frente a -0.28 de esta medida). Ver docs/pose.md.
#
# Se toma 0.18 porque conserva el 98 % del material y descarta sólo lo roto.
CONDICION_MINIMA = 0.18

# Frames que acumula el estimador de escala antes de dar un valor. A 15-30 fps
# son 2-4 s: suficiente para una mediana estable sin hacer esperar.
CALENTAMIENTO = 45


@dataclass
class MarcoCorporal:
    """Sistema de referencia anclado al cuerpo, en el instante de un frame."""

    origen: np.ndarray          # (3,) centro de las caderas
    rotacion: np.ndarray        # (3,3) filas: X lateral, Y vertical, Z frontal
    ancho_caderas_m: float
    largo_torso_m: float

    @property
    def condicion(self) -> float:
        """Cuán bien determinado está el eje lateral, en `[0, ~0.6]`.

        Es el ancho de caderas relativo al torso. De frente ronda 0.35-0.40;
        de perfil se desploma, y con él la fiabilidad de todo el marco.
        """
        if self.largo_torso_m <= 1e-6:
            return 0.0
        return self.ancho_caderas_m / self.largo_torso_m

    @property
    def valido(self) -> bool:
        return self.condicion >= CONDICION_MINIMA

    def aplicar(self, puntos: np.ndarray) -> np.ndarray:
        """Lleva puntos del marco de la cámara al marco del cuerpo."""
        P = np.asarray(puntos, dtype=np.float64).reshape(-1, 3)
        return (P - self.origen) @ self.rotacion.T


def marco_corporal(
    mundo: np.ndarray,
    visibilidad: np.ndarray | None = None,
    *,
    min_visibilidad: float = 0.5,
) -> MarcoCorporal | None:
    """Construye el marco del cuerpo, o `None` si no se puede.

    Args:
        mundo: `(K, 3)` en metros, tal como los da `pose_world_landmarks`.
        visibilidad: `(K,)` opcional. Si alguno de los cuatro landmarks que
            definen el marco está por debajo del umbral, **no hay marco**: uno
            malo no degrada la pose, la gira entera.

    Devolver `None` es parte del contrato. Un marco inventado a partir de una
    cadera que el modelo no ve produce una pose plausible y equivocada, que es
    peor que no tener dato.
    """
    P = np.asarray(mundo, dtype=np.float64).reshape(-1, 3)
    idx = (CADERA_IZQ, CADERA_DER, HOMBRO_IZQ, HOMBRO_DER)
    if P.shape[0] <= max(idx) or not np.all(np.isfinite(P[list(idx)])):
        return None
    if visibilidad is not None:
        v = np.asarray(visibilidad, dtype=np.float64).ravel()
        if v.size <= max(idx) or np.min(v[list(idx)]) < min_visibilidad:
            return None

    ci, cd = P[CADERA_IZQ], P[CADERA_DER]
    hi, hd = P[HOMBRO_IZQ], P[HOMBRO_DER]

    origen = (ci + cd) / 2.0
    hombros = (hi + hd) / 2.0

    # X: lateral, de la cadera DERECHA a la IZQUIERDA del sujeto. Se usa la
    # lateralidad anatómica que ya trae MediaPipe, no la de la imagen: es lo
    # que hace que el resultado no dependa de desde dónde se mire.
    x = ci - cd
    ancho = float(np.linalg.norm(x))
    if ancho < 1e-6:
        return None
    x = x / ancho

    # Y: hacia los hombros, ortogonalizado contra X. Caderas y columna no son
    # perpendiculares exactas, y suponerlo metería una inclinación falsa.
    y = hombros - origen
    torso = float(np.linalg.norm(y))
    y = y - np.dot(y, x) * x
    ny = float(np.linalg.norm(y))
    if ny < 1e-6 or torso < 1e-6:
        return None
    y = y / ny

    z = np.cross(x, y)
    return MarcoCorporal(origen, np.stack([x, y, z]), ancho, torso)


def canonicalizar(
    mundo: np.ndarray,
    visibilidad: np.ndarray | None = None,
    *,
    exigir_valido: bool = True,
    min_visibilidad: float = 0.5,
) -> np.ndarray | None:
    """Pose en el marco del cuerpo, o `None` si el marco no es utilizable.

    Con `exigir_valido=False` devuelve la pose aunque el marco esté mal
    condicionado. Sirve para inspeccionar, no para alimentar un clasificador.
    """
    marco = marco_corporal(mundo, visibilidad, min_visibilidad=min_visibilidad)
    if marco is None or (exigir_valido and not marco.valido):
        return None
    return marco.aplicar(mundo)


def canonicalizar_secuencia(
    secuencia: np.ndarray,
    visibilidad: np.ndarray | None = None,
    **opciones,
) -> np.ndarray:
    """`(T, K, 3)` canonicalizado. `NaN` en los frames sin marco utilizable."""
    S = np.asarray(secuencia, dtype=np.float64)
    if S.ndim != 3 or S.shape[2] != 3:
        raise ValueError(f"secuencia debe ser (T, K, 3); es {S.shape}.")
    salida = np.full_like(S, np.nan)
    for t in range(len(S)):
        v = None if visibilidad is None else np.asarray(visibilidad)[t]
        c = canonicalizar(S[t], v, **opciones)
        if c is not None:
            salida[t] = c
    return salida


# ----------------------------------------------------------------- escala


def escala_de_sesion(secuencia: np.ndarray,
                     visibilidad: np.ndarray | None = None,
                     *, min_visibilidad: float = 0.5) -> float:
    """Largo de torso mediano de una sesión, en metros.

    **Una escala por sesión, no una por frame.** El coeficiente de variación es
    invariante a escala, así que un divisor constante no cambia nada de la
    estabilidad pero sí hace comparables a dos sujetos; un divisor por frame
    sólo puede añadir su propio ruido. Medido: normalizar por el ancho de
    hombros de cada frame empeoraba la variación de 10.4 % a 15.4 %. Ver
    docs/pose.md.
    """
    S = np.asarray(secuencia, dtype=np.float64)
    largos = []
    for t in range(len(S)):
        v = None if visibilidad is None else np.asarray(visibilidad)[t]
        m = marco_corporal(S[t], v, min_visibilidad=min_visibilidad)
        if m is not None and m.valido:
            largos.append(m.largo_torso_m)
    return float(np.median(largos)) if largos else float("nan")


class EstimadorDeEscala:
    """Escala corporal en vivo: mediana acumulada con calentamiento.

    En una sesión grabada la escala se calcula de una vez sobre todo el
    material. En vivo no se puede, y usar el largo del frame actual reintroduce
    justo el ruido que se quería evitar. Este estimador acumula, y una vez
    caliente devuelve una mediana que ya casi no se mueve.
    """

    def __init__(self, calentamiento: int = CALENTAMIENTO,
                 memoria: int = 900) -> None:
        self.calentamiento = calentamiento
        self._largos: deque[float] = deque(maxlen=memoria)

    def observar(self, marco: MarcoCorporal | None) -> None:
        if marco is not None and marco.valido:
            self._largos.append(marco.largo_torso_m)

    @property
    def listo(self) -> bool:
        return len(self._largos) >= self.calentamiento

    @property
    def escala_m(self) -> float:
        if not self._largos:
            return float("nan")
        return float(np.median(self._largos))

    @property
    def n(self) -> int:
        return len(self._largos)


def normalizar(canonico: np.ndarray, escala_m: float) -> np.ndarray:
    """Divide por la escala corporal. Deja la pose adimensional."""
    if not np.isfinite(escala_m) or escala_m <= 1e-6:
        return np.full_like(np.asarray(canonico, dtype=np.float64), np.nan)
    return np.asarray(canonico, dtype=np.float64) / escala_m


def rasgos_de_sesion(
    secuencia: np.ndarray,
    visibilidad: np.ndarray | None = None,
    **opciones,
) -> tuple[np.ndarray, float]:
    """Atajo para trabajo offline: canonicaliza y normaliza una sesión entera.

    Returns:
        `(rasgos, escala_m)` con `rasgos` de forma `(T, K, 3)`, adimensional y
        con `NaN` donde no hubo marco utilizable. Es lo que consume un
        clasificador de gestos — que vive en el repositorio `tesis`, no aquí.
    """
    escala = escala_de_sesion(secuencia, visibilidad, **opciones)
    canon = canonicalizar_secuencia(secuencia, visibilidad, **opciones)
    return normalizar(canon, escala), escala
