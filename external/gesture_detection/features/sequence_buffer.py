"""Ventana deslizante de movimiento, remuestreada a paso fijo.

Es la pieza que convierte una pose por frame en algo que un clasificador de
secuencias puede comparar: una trayectoria de duracion conocida y con un numero
fijo de muestras.

Por que remuestrear y no guardar frames
---------------------------------------
Una ventana de "los ultimos 45 frames" dura 1.5 s a 30 fps y 3.0 s a 15 fps.
Son gestos distintos. Una ventana de "los ultimos 1.5 s, en 24 muestras" es la
misma trayectoria en las dos, y ademas absorbe el jitter de las camaras IP, que
no entregan a intervalo constante.

Es la misma leccion que en la deteccion de episodios: **el tiempo se mide en
segundos, no en frames**. Medido alli, buscar el instante perdia el 42 % de los
eventos al bajar de 30 a 15 fps; buscar la trayectoria conservaba el 90 %.

Que entra aqui
--------------
Poses ya canonicalizadas y normalizadas por torso (`pose/normalize.py`). Sin
eso, la misma trayectoria vista desde dos camaras del anillo da dos matrices
distintas —medido, hasta un 62 % de diferencia entre camaras adyacentes— y
ninguna plantilla transfiere.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

#: Duracion de la ventana. 1.5 s cubre un aplauso completo (0.4-0.6 s) con
#: margen y sigue siendo corto para un gesto de celebracion.
DURACION_S = 1.5

#: Muestras por ventana. 24 en 1.5 s son 16 Hz efectivos, por encima del
#: contenido util del movimiento del brazo medido.
MUESTRAS = 24

#: Fraccion maxima de la ventana que puede venir de frames sin pose.
HUECO_MAXIMO = 0.30


@dataclass(frozen=True)
class Ventana:
    """Trayectoria lista para comparar."""

    datos: np.ndarray            #: `(muestras, D)` remuestreada
    t_inicio: float
    t_fin: float

    @property
    def duracion_s(self) -> float:
        return self.t_fin - self.t_inicio


class SequenceBuffer:
    """Acumula rasgos por frame y entrega ventanas de duracion fija.

    Args:
        landmarks: indices cuyas coordenadas forman el vector de rasgos. Para
            un aplauso bastan las dos munecas; para un gesto de celebracion
            conviene anadir codos.
        duracion_s: largo de la ventana.
        muestras: puntos a los que se remuestrea.
        coordenadas: cuantas por landmark. 3 para el marco corporal; 2 para
            comparar contra una linea base en el plano de la imagen, que es la
            comparacion que la tesis necesita poder hacer.
    """

    def __init__(
        self,
        landmarks: tuple[int, ...],
        *,
        duracion_s: float = DURACION_S,
        muestras: int = MUESTRAS,
        hueco_maximo: float = HUECO_MAXIMO,
        coordenadas: int = 3,
    ) -> None:
        if muestras < 2:
            raise ValueError("hacen falta al menos 2 muestras por ventana")
        if coordenadas not in (2, 3):
            raise ValueError(f"coordenadas debe ser 2 o 3; es {coordenadas}")
        self.landmarks = tuple(landmarks)
        self.coordenadas = int(coordenadas)
        self.duracion_s = float(duracion_s)
        self.muestras = int(muestras)
        self.hueco_maximo = float(hueco_maximo)
        # Holgado: a 60 fps una ventana de 1.5 s son 90 frames.
        self._t: deque[float] = deque(maxlen=1024)
        self._x: deque[np.ndarray] = deque(maxlen=1024)

    @property
    def dimension(self) -> int:
        return len(self.landmarks) * self.coordenadas

    def reset(self) -> None:
        self._t.clear()
        self._x.clear()

    def push(self, pose: np.ndarray | None, t: float) -> None:
        """Anade un frame. `pose` es `(K, 3)` canonicalizada, o `None`.

        Un frame sin pose se guarda como hueco, no se descarta: si se
        descartara, una perdida larga se veria como un salto instantaneo y la
        trayectoria saldria falseada.
        """
        if pose is None:
            v = np.full(self.dimension, np.nan)
        else:
            P = np.asarray(pose, dtype=np.float64)
            v = P[list(self.landmarks)].ravel().astype(np.float64)
            if v.size != self.dimension:
                raise ValueError(
                    f"la pose no tiene los landmarks pedidos; "
                    f"se esperaban {self.dimension} valores y hay {v.size}."
                )
        self._t.append(float(t))
        self._x.append(v)

    def ventana(self, t_fin: float | None = None) -> Ventana | None:
        """Ventana remuestreada que termina en `t_fin`, o `None`.

        Devuelve `None` mientras no haya material para la ventana entera o si
        la pose se perdio durante mas de `hueco_maximo` de ella. Una ventana
        medio inventada es peor que ninguna: el clasificador la compararia con
        las plantillas como si fuera buena.
        """
        if len(self._t) < 2:
            return None
        t = np.fromiter(self._t, dtype=np.float64)
        fin = t[-1] if t_fin is None else float(t_fin)
        inicio = fin - self.duracion_s
        if t[0] > inicio:
            return None                      # todavia no hay ventana completa

        X = np.stack(self._x)
        validos = np.all(np.isfinite(X), axis=1)
        dentro = (t >= inicio) & (t <= fin)
        if not dentro.any():
            return None
        if 1.0 - validos[dentro].mean() > self.hueco_maximo:
            return None

        tv, Xv = t[validos], X[validos]
        if len(tv) < 2 or tv[0] > inicio or tv[-1] < fin - 1e-9:
            return None

        rejilla = np.linspace(inicio, fin, self.muestras)
        datos = np.empty((self.muestras, X.shape[1]), dtype=np.float64)
        for j in range(X.shape[1]):
            datos[:, j] = np.interp(rejilla, tv, Xv[:, j])
        return Ventana(datos, inicio, fin)


def ventana_de_secuencia(
    secuencia: np.ndarray,
    tiempos: np.ndarray,
    landmarks: tuple[int, ...],
    *,
    duracion_s: float = DURACION_S,
    muestras: int = MUESTRAS,
    hueco_maximo: float = HUECO_MAXIMO,
    coordenadas: int = 3,
) -> Ventana | None:
    """Atajo offline: una ventana a partir de una grabacion entera.

    Sirve para construir plantillas desde material ya grabado sin repetir el
    bucle de `push`.
    """
    buf = SequenceBuffer(landmarks, duracion_s=duracion_s, muestras=muestras,
                         hueco_maximo=hueco_maximo, coordenadas=coordenadas)
    S = np.asarray(secuencia, dtype=np.float64)
    T = np.asarray(tiempos, dtype=np.float64)
    if len(S) != len(T):
        raise ValueError(f"secuencia y tiempos no coinciden: {len(S)} y {len(T)}")
    for k in range(len(S)):
        fila = S[k]
        buf.push(None if not np.all(np.isfinite(fila)) else fila, T[k])
    return buf.ventana()
