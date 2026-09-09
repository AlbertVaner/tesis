"""Paro de emergencia: una postura sostenida, evaluada frame a frame.

Es el unico comando que **no puede** ir por DTW: una trayectoria se reconoce
cuando termina, 2 a 4 s despues de empezar, y una emergencia no espera. Aqui
cada frame se comprueba una condicion geometrica sobre la pose canonicalizada
(marco del cuerpo, unidades de torso) y el paro se dispara cuando la condicion
se sostiene `CONFIRMACION_S` seguidos.

Dos posturas, y por que la que va por defecto es la de la cabeza
-----------------------------------------------------------------
**`cabeza`: brazos cruzados en X por encima de la cabeza.** Es la senal de
"alto" de los senaleros de aviacion. Medido sobre 300 tomas de 5 personas
(2026-09-07), con todo el vocabulario, reposo y movimientos de rechazo, la
condicion "las dos munecas por encima de la nariz y cruzadas" no se sostuvo
mas de **0.2 s** en ninguna toma. Con 1.0 s de confirmacion no hay falsos
positivos en el material que existe. La postura en si no se ha grabado
todavia: los umbrales son geometricos y el probador en vivo es donde se miden.

**`pecho`: brazos cruzados en X sobre el pecho, munecas en los hombros
contrarios.** Se grabo (21 tomas) y se descarto como opcion principal porque
es, geometricamente, la postura de cruzarse de brazos esperando: las munecas
quedan a 0.42-0.84 torsos de altura en reposo y a 0.60-0.99 en la X, y a la
misma distancia del hombro contrario. La mejor regla separa por una decima de
torso, unos 5 cm. Se conserva para poder compararla en vivo.

Unidades: torso = 1.0. El hombro queda a ~1.0 de altura sobre la cadera, la
nariz a 1.30 (mediana medida, p10-p90 1.26-1.34). `+X` es la izquierda del
sujeto, asi que la muneca derecha cruzada tiene X mayor que la izquierda.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from pose.normalize import (
    LEFT_ELBOW,
    LEFT_SHOULDER,
    LEFT_WRIST,
    RIGHT_ELBOW,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
)

NOSE = 0

#: Segundos que la postura debe sostenerse antes de disparar. Menos que los
#: 2 s del STOP de `body_3d_rules` porque es emergencia; mas que un cruce
#: casual de brazos, que en el material de reposo no pasa de 0.2 s en la
#: postura de la cabeza.
CONFIRMACION_S = {"cabeza": 1.0, "pecho": 1.5}

#: Huecos de pose mas cortos que esto no rompen la racha. Perder la pose un
#: par de frames es frecuente y no significa que el operador bajo los brazos.
HUECO_MAXIMO_S = 0.25

#: Tras soltar la postura, tiempo antes de poder volver a disparar.
REARME_S = 0.5


@dataclass
class Medida:
    """Una condicion de la postura, con su valor actual y su umbral."""

    etiqueta: str
    valor: float
    umbral: float
    sentido: str            #: ">=" si el valor debe superar el umbral
    unidad: str = "u"

    @property
    def cumple(self) -> bool:
        if not np.isfinite(self.valor):
            return False
        return (self.valor >= self.umbral if self.sentido == ">="
                else self.valor <= self.umbral)

    @property
    def holgura(self) -> float:
        return (self.valor - self.umbral if self.sentido == ">="
                else self.umbral - self.valor)


def medidas_cabeza(pose: np.ndarray) -> list[Medida]:
    """X sobre la cabeza: munecas por encima de la nariz y cruzadas."""
    rw, lw, nz = pose[RIGHT_WRIST], pose[LEFT_WRIST], pose[NOSE]
    return [
        # Las dos munecas por encima de la nariz. Las orejas quedan 0.05 mas
        # arriba; la nariz es el landmark mas estable de la cara.
        Medida("munecas sobre nariz", float(min(rw[1], lw[1]) - nz[1]), 0.0, ">="),
        # Cruce: la muneca derecha queda a la izquierda de la izquierda. 0.10
        # es dos veces el ruido por eje (0.044); en el senalero, que oscila
        # con los brazos arriba, el cruce no llega a sostenerse 0.2 s.
        Medida("cruce munecas", float(rw[0] - lw[0]), 0.10, ">="),
        # En una X las munecas se tocan o casi. Descarta brazos abiertos en V.
        Medida("separacion munecas", float(np.linalg.norm(rw - lw)), 0.60, "<="),
    ]


def medidas_pecho(pose: np.ndarray) -> list[Medida]:
    """X sobre el pecho. Umbrales medidos el 2026-09-07; margen escaso."""
    rw, lw = pose[RIGHT_WRIST], pose[LEFT_WRIST]
    rs, ls = pose[RIGHT_SHOULDER], pose[LEFT_SHOULDER]
    re, le = pose[RIGHT_ELBOW], pose[LEFT_ELBOW]
    d_op = max(np.linalg.norm(rw - ls), np.linalg.norm(lw - rs))
    return [
        Medida("muneca-hombro contr.", float(d_op), 0.80, "<="),
        Medida("altura munecas", float(min(rw[1], lw[1])), 0.70, ">="),
        Medida("altura codos", float(min(re[1], le[1])), 0.45, ">="),
    ]


POSTURAS = {"cabeza": medidas_cabeza, "pecho": medidas_pecho}

INSTRUCCION = {
    "cabeza": "brazos cruzados en X por ENCIMA de la cabeza",
    "pecho": "brazos en X sobre el pecho, munecas en los hombros contrarios",
}


class ReglaParo:
    """Evalua la postura frame a frame y dispara al sostenerse."""

    def __init__(self, postura: str = "cabeza",
                 confirmacion_s: float | None = None) -> None:
        if postura not in POSTURAS:
            raise ValueError(f"postura {postura!r}; validas: {list(POSTURAS)}")
        self.postura = postura
        self.confirmacion_s = (CONFIRMACION_S[postura] if confirmacion_s is None
                               else float(confirmacion_s))
        self._medir = POSTURAS[postura]
        self.medidas: list[Medida] = []
        self.cumple = False         #: la postura se cumple en este frame
        self.activo = False         #: confirmada y todavia sostenida
        self._t_inicio: float | None = None
        self._t_ultimo_ok: float | None = None
        self._t_liberado = -np.inf

    def reset(self) -> None:
        self.medidas = []
        self.cumple = self.activo = False
        self._t_inicio = self._t_ultimo_ok = None

    @property
    def sostenido_s(self) -> float:
        if self._t_inicio is None or self._t_ultimo_ok is None:
            return 0.0
        return self._t_ultimo_ok - self._t_inicio

    @property
    def falta_s(self) -> float:
        return max(self.confirmacion_s - self.sostenido_s, 0.0)

    def actualizar(self, pose: np.ndarray | None, t: float) -> bool:
        """Alimenta un frame. Devuelve `True` solo en el frame que dispara.

        `pose` es `(33, 3)` canonicalizada y normalizada por torso, o `None`.
        """
        if pose is None or not np.all(np.isfinite(
                np.asarray(pose)[[NOSE, LEFT_WRIST, RIGHT_WRIST,
                                  LEFT_SHOULDER, RIGHT_SHOULDER,
                                  LEFT_ELBOW, RIGHT_ELBOW]])):
            self.cumple = False
            self._hueco(t)
            return False

        self.medidas = self._medir(np.asarray(pose, dtype=np.float64))
        self.cumple = all(m.cumple for m in self.medidas)
        if not self.cumple:
            self._hueco(t)
            return False

        if self._t_inicio is None:
            if t - self._t_liberado < REARME_S:
                return False
            self._t_inicio = t
        self._t_ultimo_ok = t
        if not self.activo and self.sostenido_s >= self.confirmacion_s:
            self.activo = True
            return True
        return False

    def _hueco(self, t: float) -> None:
        """Un frame sin postura: tolera un hueco corto, si no, suelta."""
        if self._t_inicio is None:
            return
        if self._t_ultimo_ok is not None and t - self._t_ultimo_ok <= HUECO_MAXIMO_S:
            return
        if self.activo:
            self._t_liberado = t
        self.activo = False
        self._t_inicio = self._t_ultimo_ok = None
