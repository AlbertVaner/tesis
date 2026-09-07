"""Reconocimiento de gestos dinamicos por comparacion con plantillas (DTW).

Es el canal de **eventos** del diseno: mientras el canal continuo lee la
postura instantanea —un brazo señala una direccion—, este lee una trayectoria
completa. Un aplauso o una celebracion no son una postura; son un recorrido.

Por que DTW y no otra cosa
--------------------------
Ibañez et al. (2014) reportan 99.1 % con DTW y 98.9 % con HMM sobre 7 gestos
dinamicos, con centrado y normalizacion por escala corporal previos —que es
exactamente lo que hace `pose/normalize.py`—. DTW no necesita entrenamiento:
una sola repeticion ya es plantilla. Para un vocabulario que todavia se esta
decidiendo, eso importa mas que el ultimo punto de exactitud.

La deformacion temporal no es un adorno: la misma persona hace el mismo gesto
un 20-30 % mas rapido o mas lento entre repeticiones, y comparar muestra a
muestra penaliza eso como si fuera un gesto distinto.

Que NO resuelve
---------------
DTW da una distancia, no una probabilidad. El umbral de aceptacion sale de
medir: se calcula sobre repeticiones reales del gesto y sobre material donde el
gesto **no** ocurre. Sin las dos mitades, un umbral es una opinion.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

#: Radio de la banda de Sakoe-Chiba, en fraccion del largo de la ventana.
#:
#: Limita cuanto se puede estirar el tiempo. Sin banda, DTW encuentra siempre
#: un camino: puede alinear un gesto de 0.2 s con uno de 1.4 s y devolver una
#: distancia pequeña que no significa nada. 0.25 permite un 25 % de diferencia
#: de ritmo, que cubre la variacion entre repeticiones de una misma persona.
BANDA = 0.25

#: Distancia por encima de la cual una ventana no se parece a la plantilla.
#: Es un valor de arranque: el que vale sale de medir sobre repeticiones
#: reales. Ver `umbral_por_separacion`.
UMBRAL = 0.35


def dtw_distancia(a: np.ndarray, b: np.ndarray, banda: float = BANDA) -> float:
    """Distancia DTW entre dos trayectorias `(N, D)` y `(M, D)`.

    Se normaliza por el largo del camino para que ventanas de distinto numero
    de muestras sean comparables.
    """
    A = np.asarray(a, dtype=np.float64)
    B = np.asarray(b, dtype=np.float64)
    if A.ndim != 2 or B.ndim != 2 or A.shape[1] != B.shape[1]:
        raise ValueError(
            f"las trayectorias deben ser (N, D) con la misma D; "
            f"son {A.shape} y {B.shape}."
        )
    n, m = len(A), len(B)
    if n == 0 or m == 0:
        return float("inf")

    radio = max(int(round(banda * max(n, m))), abs(n - m)) + 1
    coste = np.full((n + 1, m + 1), np.inf)
    pasos = np.zeros((n + 1, m + 1), dtype=np.int32)
    coste[0, 0] = 0.0

    for i in range(1, n + 1):
        j0 = max(1, i - radio)
        j1 = min(m, i + radio)
        d = np.linalg.norm(B[j0 - 1:j1] - A[i - 1], axis=1)
        for k, j in enumerate(range(j0, j1 + 1)):
            mejor = min(
                (coste[i - 1, j], pasos[i - 1, j]),
                (coste[i, j - 1], pasos[i, j - 1]),
                (coste[i - 1, j - 1], pasos[i - 1, j - 1]),
                key=lambda p: p[0],
            )
            coste[i, j] = mejor[0] + d[k]
            pasos[i, j] = mejor[1] + 1

    if not np.isfinite(coste[n, m]) or pasos[n, m] == 0:
        return float("inf")
    return float(coste[n, m] / pasos[n, m])


@dataclass
class Plantilla:
    """Una repeticion de referencia de un gesto."""

    nombre: str
    trayectoria: np.ndarray      #: `(muestras, D)`
    umbral: float = UMBRAL

    def distancia(self, ventana: np.ndarray, banda: float = BANDA) -> float:
        return dtw_distancia(self.trayectoria, ventana, banda)


@dataclass
class Coincidencia:
    """Lo que devuelve el reconocedor para una ventana."""

    nombre: str | None
    distancia: float
    margen: float                #: cuanto le gana al segundo mejor gesto
    distancias: dict = field(default_factory=dict)

    @property
    def hay_gesto(self) -> bool:
        return self.nombre is not None


class DTWRecognizer:
    """Compara una ventana contra las plantillas guardadas.

    Varias plantillas por gesto son la regla, no la excepcion: cubren la
    variacion entre repeticiones mucho mejor que promediarlas, que produce una
    trayectoria que nadie hace.
    """

    def __init__(self, *, banda: float = BANDA, margen_minimo: float = 0.0):
        self.banda = banda
        self.margen_minimo = margen_minimo
        self.plantillas: list[Plantilla] = []

    def agregar(self, plantilla: Plantilla) -> None:
        if self.plantillas:
            esperado = self.plantillas[0].trayectoria.shape[1]
            if plantilla.trayectoria.shape[1] != esperado:
                raise ValueError(
                    f"la plantilla tiene {plantilla.trayectoria.shape[1]} "
                    f"rasgos y las demas {esperado}."
                )
        self.plantillas.append(plantilla)

    @property
    def gestos(self) -> list[str]:
        return sorted({p.nombre for p in self.plantillas})

    def comparar(self, ventana: np.ndarray) -> Coincidencia:
        """Gesto mas parecido a `ventana`, o ninguno.

        Se exige dos cosas: que la mejor plantilla este por debajo de su propio
        umbral, y que le gane al mejor gesto **distinto** por `margen_minimo`.
        Sin lo segundo, dos gestos parecidos alternan segun el ruido.
        """
        if not self.plantillas:
            return Coincidencia(None, float("inf"), 0.0, {})

        por_gesto: dict[str, float] = {}
        mejor: tuple[float, Plantilla] | None = None
        for p in self.plantillas:
            d = p.distancia(ventana, self.banda)
            if d < por_gesto.get(p.nombre, np.inf):
                por_gesto[p.nombre] = d
            if mejor is None or d < mejor[0]:
                mejor = (d, p)

        assert mejor is not None
        distancia, plantilla = mejor
        otros = [d for g, d in por_gesto.items() if g != plantilla.nombre]
        margen = (min(otros) - distancia) if otros else float("inf")

        if distancia > plantilla.umbral or margen < self.margen_minimo:
            return Coincidencia(None, distancia, margen, por_gesto)
        return Coincidencia(plantilla.nombre, distancia, margen, por_gesto)


def umbral_por_separacion(
    positivos: list[float], negativos: list[float]
) -> tuple[float, float]:
    """Umbral que mejor separa repeticiones del gesto de material sin el.

    Returns:
        `(umbral, exactitud)`. La exactitud es la fraccion de las dos listas
        clasificada correctamente con ese umbral.

    Es lo que evita fijar un numero a ojo: hacen falta las dos mitades, y si no
    se separan bien la exactitud lo dice.
    """
    pos = np.asarray([d for d in positivos if np.isfinite(d)], dtype=np.float64)
    neg = np.asarray([d for d in negativos if np.isfinite(d)], dtype=np.float64)
    if pos.size == 0 or neg.size == 0:
        return float("nan"), 0.0

    candidatos = np.unique(np.concatenate([pos, neg]))
    medios = (candidatos[:-1] + candidatos[1:]) / 2.0
    if medios.size == 0:
        medios = candidatos
    aciertos = [
        ((pos <= u).sum() + (neg > u).sum()) / (pos.size + neg.size)
        for u in medios
    ]
    k = int(np.argmax(aciertos))
    return float(medios[k]), float(aciertos[k])
