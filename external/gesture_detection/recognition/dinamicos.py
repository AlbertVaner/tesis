"""Reconocedor de gestos dinamicos en vivo, por segmentacion y DTW.

A diferencia del vocabulario de posturas (`body_3d_rules.py`), que lee cada
frame por separado, aqui un gesto es un **recorrido**: aplaudir, llamar con la
mano, armar un arco. Se reconoce comparando la trayectoria completa contra
plantillas grabadas.

Como decide cuando empezar y cuando terminar
--------------------------------------------
No usa una ventana deslizante a ciegas. **Segmenta por movimiento**: cuando la
rapidez de las munecas sube del umbral empieza un segmento, y cuando vuelve a
bajar y se queda abajo, lo cierra y lo clasifica.

Eso importa por dos razones. Los tres gestos duran cosas muy distintas —2.2 s
aplaudir, 2.9 ven aca, 4.2 arco, medido— y ninguna ventana fija les sirve a los
tres. Y las plantillas se construyen recortando la quietud de los extremos, asi
que el segmento vivo tiene que recortarse igual o no serian comparables.

El precio es la latencia: el gesto se reconoce **cuando termina**, no mientras
ocurre. Para aplaudir son ~2.4 s desde que se empieza. Es inherente a reconocer
trayectorias, no un defecto de la implementacion.

Duracion normalizada
--------------------
Cada segmento se lleva a `MUESTRAS` puntos, lo que borra su duracion absoluta:
un aplauso lento y uno rapido se comparan igual. Medido sobre 72 tomas de 8
personas, normalizar la duracion y recortar la quietud no cuesta exactitud
(89 % contra 90 % conservando la duracion real).

Que reconoce, y con que evidencia
---------------------------------
Con plantillas de **otras personas** y sin calibrar por individuo:

    de frente (<20 deg)      100 %
    girado hasta 70 deg       85 %

Medido sobre `aplaudir`, `ven_aca` y `arco`. Otros dos gestos probados
—`senalar_mano` y `six_seven`— fallan cerca del 50 % porque comparten con el
aplauso el mismo movimiento dominante: las dos manos subiendo al pecho. Un
cuarto gesto tiene que evitar esa firma.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from pose.normalize import LEFT_ELBOW, LEFT_WRIST, RIGHT_ELBOW, RIGHT_WRIST
from recognition.dtw import dtw_distancia

#: Etiqueta de la clase que agrupa lo que NO es del vocabulario. Un banco que
#: solo contiene los gestos buenos no puede rechazar nada: cualquier movimiento
#: cae sobre la plantilla menos lejana. Medido, los gestos ajenos quedaban a
#: distancia mediana 0.299 del banco, mas cerca que los propios aciertos
#: (0.315), asi que ningun umbral los separaba. Metiendolos como clase propia,
#: el 53 % se rechaza y el vocabulario apenas pierde 2 de 72.
GESTO_RECHAZO = "otro"

#: Articulaciones del vector de rasgos, en el marco del cuerpo.
ARTICULACIONES = (RIGHT_WRIST, LEFT_WRIST, RIGHT_ELBOW, LEFT_ELBOW)

#: Puntos a los que se lleva cada segmento. 24 y 32 dan lo mismo; 24 es la
#: mitad de coste en DTW.
MUESTRAS = 24

# --- umbrales de rapidez ---------------------------------------------------
#
# En unidades de torso por segundo. Son tres cosas distintas y conviene no
# confundirlas.
#
# El **jitter de deteccion** con el sujeto quieto ronda 0.16 y llega a picos de
# 0.3 en frames sueltos. Cualquier umbral cerca de ahi se dispara solo, y por
# eso la rapidez se promedia sobre `SUAVIZADO` antes de compararla.
#
# ADVERTENCIA: estos dos primeros **no estan validados**. El material grabado
# no tiene a nadie quieto sin hacer nada, asi que la tasa de falsos arranques
# no se pudo medir; se eligieron con margen sobre el jitter. `detectar_gestos_3d`
# muestra la rapidez en pantalla para poder ajustarlos en el sitio.
ENTRADA_RAPIDEZ = 0.60
SALIDA_RAPIDEZ = 0.35

#: Recorte de la quietud en los extremos. Este SI esta medido: con 72 tomas de
#: 8 personas, el acierto va de 94 % a 97 % entre 0.20 y 0.80, con el maximo
#: aqui. Es plano, o sea que la eleccion no es critica.
RECORTE_RAPIDEZ = 0.45

#: Frames sobre los que se promedia la rapidez antes de compararla con un
#: umbral. A 30 fps son 100 ms. Sin promediar, un unico frame ruidoso decide.
SUAVIZADO = 3

#: Tiempo por debajo del umbral de salida antes de cerrar el segmento.
CIERRE_S = 0.30

#: Un segmento fuera de estos limites no es ninguno de los gestos. Los medidos
#: van de 2.2 a 5.2 s de mediana; el rango deja margen a los dos lados.
MIN_DURACION_S = 1.0
MAX_DURACION_S = 7.0

#: Fraccion minima del segmento con marco corporal utilizable.
COBERTURA_MINIMA = 0.70

#: Tras reconocer, no se vuelve a reconocer hasta pasado esto. Sin ello, la
#: cola de un gesto y el principio del siguiente se leen como un tercero.
REFRACTARIO_S = 1.0


def rasgos_de_secuencia(
    poses: np.ndarray,
    tiempos: np.ndarray,
    *,
    muestras: int = MUESTRAS,
    con_diferencia: bool = False,
) -> np.ndarray | None:
    """`(N, D)` desde poses canonicalizadas `(T, K, 3)` normalizadas por torso.

    `con_diferencia` anade el vector muneca derecha menos izquierda. No hace
    falta para los tres gestos base, pero es lo que rescata parcialmente un
    gesto de manos alternadas, donde el movimiento comun domina la distancia y
    la informacion esta en la diferencia. Se guarda en el banco para que el
    reconocedor use la misma receta con la que se construyeron las plantillas.
    """
    P = np.asarray(poses, dtype=np.float64)
    t = np.asarray(tiempos, dtype=np.float64)
    if P.ndim != 3 or len(P) != len(t) or len(P) < 4:
        return None
    S = P[:, list(ARTICULACIONES)]
    valido = np.all(np.isfinite(S.reshape(len(S), -1)), axis=1)
    if valido.mean() < COBERTURA_MINIMA or valido.sum() < 4:
        return None
    S, t = S[valido], t[valido]
    if t[-1] - t[0] <= 1e-6:
        return None

    X = S.reshape(len(S), -1)
    if con_diferencia:
        X = np.concatenate([X, S[:, 0] - S[:, 1]], axis=1)
    rejilla = np.linspace(t[0], t[-1], muestras)
    return np.stack([np.interp(rejilla, t, X[:, j])
                     for j in range(X.shape[1])], axis=1)


def rapidez_munecas(poses: np.ndarray, tiempos: np.ndarray) -> np.ndarray:
    """`(T,)` rapidez de las dos munecas juntas. El primer valor es `NaN`."""
    P = np.asarray(poses, dtype=np.float64)
    t = np.asarray(tiempos, dtype=np.float64)
    munecas = P[:, [RIGHT_WRIST, LEFT_WRIST]].reshape(len(P), -1)
    v = np.full(len(P), np.nan)
    dt = np.diff(t)
    with np.errstate(invalid="ignore", divide="ignore"):
        v[1:] = np.linalg.norm(np.diff(munecas, axis=0), axis=1) / dt
    return v


def recortar_quietud(poses, tiempos, umbral: float = RECORTE_RAPIDEZ):
    """Quita la quietud de los extremos. Devuelve `(poses, tiempos)`.

    Las tomas grabadas traen medio segundo o mas de inmovilidad antes y despues
    del gesto. Si la plantilla la conserva y el segmento vivo no, DTW compara
    cosas de distinta forma.
    """
    P = np.asarray(poses, dtype=np.float64)
    t = np.asarray(tiempos, dtype=np.float64)
    v = np.nan_to_num(rapidez_munecas(P, t))
    # Suavizado antes de umbralizar. Sin el, un solo frame ruidoso al principio
    # marca el arranque del movimiento y el recorte no recorta nada: basta que
    # el ruido de deteccion pase el umbral una vez en toda la quietud.
    if len(v) >= SUAVIZADO:
        nucleo = np.ones(SUAVIZADO) / SUAVIZADO
        v = np.convolve(v, nucleo, mode="same")
    activos = np.where(v > umbral)[0]
    if activos.size < 3:
        return P, t
    a = max(activos[0] - 1, 0)
    b = min(activos[-1] + 2, len(P))
    return P[a:b], t[a:b]


# ------------------------------------------------------------------- banco


@dataclass
class BancoDinamico:
    """Plantillas y umbral de aceptacion, medidos sobre material real."""

    gestos: list[str]                 #: etiqueta de cada plantilla
    plantillas: list[np.ndarray]      #: cada una `(MUESTRAS, D)`
    umbral: float                     #: distancia maxima aceptada
    margen: float = 0.0               #: ventaja minima sobre el segundo gesto
    con_diferencia: bool = False
    muestras: int = MUESTRAS
    nota: str = ""

    @property
    def clases(self) -> list[str]:
        """Gestos que el banco puede emitir. `GESTO_RECHAZO` no es uno."""
        return sorted(set(self.gestos) - {GESTO_RECHAZO})

    @property
    def tiene_rechazo(self) -> bool:
        return GESTO_RECHAZO in self.gestos

    def clasificar(self, ventana: np.ndarray) -> tuple[str | None, float, float, dict]:
        """`(gesto, distancia, margen, distancias por gesto)`.

        `gesto` es `None` si la mejor plantilla queda por encima del umbral o
        si no le saca al segundo gesto el margen exigido.
        """
        if not self.plantillas:
            return None, float("inf"), 0.0, {}
        por_gesto: dict[str, float] = {}
        for etiqueta, p in zip(self.gestos, self.plantillas):
            d = dtw_distancia(p, ventana)
            if d < por_gesto.get(etiqueta, np.inf):
                por_gesto[etiqueta] = d
        mejor = min(por_gesto, key=por_gesto.get)
        distancia = por_gesto[mejor]
        otros = [d for g, d in por_gesto.items() if g != mejor]
        margen = (min(otros) - distancia) if otros else float("inf")
        if distancia > self.umbral or margen < self.margen:
            return None, distancia, margen, por_gesto
        if mejor == GESTO_RECHAZO:
            return None, distancia, margen, por_gesto
        return mejor, distancia, margen, por_gesto

    def guardar(self, ruta: Path) -> Path:
        ruta = Path(ruta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            ruta,
            gestos=np.array(self.gestos),
            plantillas=np.stack(self.plantillas),
            umbral=self.umbral,
            margen=self.margen,
            con_diferencia=self.con_diferencia,
            muestras=self.muestras,
            nota=self.nota,
        )
        return ruta

    @classmethod
    def cargar(cls, ruta: Path) -> "BancoDinamico":
        d = np.load(ruta, allow_pickle=False)
        return cls(
            gestos=[str(g) for g in d["gestos"]],
            plantillas=[np.asarray(p, dtype=np.float64) for p in d["plantillas"]],
            umbral=float(d["umbral"]),
            margen=float(d["margen"]),
            con_diferencia=bool(d["con_diferencia"]),
            muestras=int(d["muestras"]),
            nota=str(d["nota"]),
        )


# ------------------------------------------------------------- reconocedor


@dataclass
class Deteccion:
    """Un gesto reconocido, o un segmento rechazado."""

    gesto: str | None
    distancia: float
    margen: float
    t_inicio: float
    t_fin: float
    motivo: str = ""
    distancias: dict = field(default_factory=dict)

    @property
    def duracion_s(self) -> float:
        return self.t_fin - self.t_inicio


class ReconocedorDinamico:
    """Segmenta el movimiento en vivo y clasifica cada segmento."""

    def __init__(self, banco: BancoDinamico, *, memoria_s: float = 12.0) -> None:
        self.banco = banco
        self.memoria_s = memoria_s
        self._t: deque[float] = deque()
        self._p: deque[np.ndarray] = deque()
        self.en_segmento = False
        self.t_inicio = 0.0
        self._t_bajo: float | None = None
        self._hasta = 0.0                 # fin del periodo refractario
        self.ultima: Deteccion | None = None
        self.rapidez = 0.0
        self._huecos = 0
        self._frames = 0

    def reset(self) -> None:
        self._t.clear()
        self._p.clear()
        self.en_segmento = False
        self._t_bajo = None
        self.ultima = None
        self._huecos = 0
        self._frames = 0

    @property
    def segmento_s(self) -> float:
        if not self.en_segmento or not self._t:
            return 0.0
        return self._t[-1] - self.t_inicio

    def actualizar(self, pose: np.ndarray | None, t: float | None = None) -> Deteccion | None:
        """Alimenta un frame. Devuelve una `Deteccion` al cerrar un segmento.

        `pose` es `(K, 3)` canonicalizada y normalizada por torso, o `None` si
        el frame no era utilizable.
        """
        t = time.monotonic() if t is None else float(t)
        K = max(ARTICULACIONES) + 1
        fila = (np.full((K, 3), np.nan) if pose is None
                else np.asarray(pose, dtype=np.float64)[:K])
        self._t.append(t)
        self._p.append(fila)
        while self._t and t - self._t[0] > self.memoria_s:
            self._t.popleft()
            self._p.popleft()
        if len(self._t) < 3:
            return None

        # Un frame sin pose no es un frame lento: es un frame sin dato. Si se
        # tratara como lento, perder la pose a mitad de gesto lo partiria en
        # dos y la primera mitad se clasificaria como si estuviera completa.
        hay_pose = bool(np.all(np.isfinite(fila[list(ARTICULACIONES)])))
        if self.en_segmento:
            self._frames += 1
            self._huecos += not hay_pose
        if hay_pose:
            P = np.stack(list(self._p)[-3:])
            tt = np.array(list(self._t)[-3:])
            v = rapidez_munecas(P, tt)[1:]
            v = v[np.isfinite(v)]
            if v.size:
                self.rapidez = float(v.max())
        elif self.en_segmento:
            return None                    # sin dato no se decide nada

        if not self.en_segmento:
            if t >= self._hasta and self.rapidez > ENTRADA_RAPIDEZ:
                self.en_segmento = True
                self.t_inicio = t
                self._t_bajo = None
                self._huecos = self._frames = 0
            return None

        if self.rapidez > SALIDA_RAPIDEZ:
            self._t_bajo = None
            if t - self.t_inicio > MAX_DURACION_S:
                return self._cerrar(t, "demasiado largo")
            return None

        if self._t_bajo is None:
            self._t_bajo = t
        elif t - self._t_bajo >= CIERRE_S:
            return self._cerrar(t, "")
        return None

    def _cerrar(self, t: float, motivo: str) -> Deteccion:
        inicio, self.en_segmento, self._t_bajo = self.t_inicio, False, None
        self._hasta = t + REFRACTARIO_S

        tiempos = np.array(self._t)
        m = (tiempos >= inicio - 0.1) & (tiempos <= t)
        det = Deteccion(None, float("inf"), 0.0, inicio, t, motivo)
        if motivo or m.sum() < 4:
            self.ultima = det
            return det

        cobertura = 1.0 - self._huecos / max(self._frames, 1)
        if cobertura < COBERTURA_MINIMA:
            det.motivo = f"pose perdida en el {100 * (1 - cobertura):.0f} % del gesto"
            self.ultima = det
            return det

        poses = np.stack(self._p)[m]
        tt = tiempos[m]
        poses, tt = recortar_quietud(poses, tt)
        dur = float(tt[-1] - tt[0]) if len(tt) > 1 else 0.0
        if not (MIN_DURACION_S <= dur <= MAX_DURACION_S):
            det.motivo = f"duracion {dur:.1f} s fuera de rango"
            self.ultima = det
            return det

        ventana = rasgos_de_secuencia(
            poses, tt, muestras=self.banco.muestras,
            con_diferencia=self.banco.con_diferencia)
        if ventana is None:
            det.motivo = "pose insuficiente en el segmento"
            self.ultima = det
            return det

        gesto, d, margen, todas = self.banco.clasificar(ventana)
        det = Deteccion(gesto, d, margen, inicio, t,
                        "" if gesto else "no se parece a ninguna plantilla",
                        todas)
        self.ultima = det
        return det
