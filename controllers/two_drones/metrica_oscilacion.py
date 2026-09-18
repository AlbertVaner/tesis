"""Metrica de oscilacion de una sesion de vuelo. Sin hardware.

Mirar la trayectoria en una grafica dice si oscila, pero no **cuanto**, y sin
un numero no se pueden comparar dos corridas ni saber si un cambio mejoro algo.
Esto reduce una sesion a cuatro cifras:

* `rms_error_m`: distancia horizontal cuadratica media al objetivo. Es la cifra
  de rendimiento: cuanto se desvia el dron de donde se le pidio estar.
* `amplitud_m`: semi pico-a-pico del error. Cuanto se va en el peor momento.
* `frecuencia_hz`: a que ritmo oscila, por cruces por la media.
* `reversiones`: cuantas veces cambia de sentido. Distingue una oscilacion
  sostenida de una excursion aislada.

Las dos primeras bajan si el control mejora; la tercera caracteriza el modo y
deberia moverse poco mientras la causa sea la misma.

Se mide **solo con el dron en el aire**: el suelo no oscila y meter esas
muestras diluye el numero.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class Oscilacion:
    """Resumen numerico de una sesion."""

    muestras: int
    duracion_s: float
    rms_error_m: float
    amplitud_m: float
    frecuencia_hz: float
    reversiones: int

    def __str__(self) -> str:
        return (f"rms {self.rms_error_m:.3f} m   amplitud {self.amplitud_m:.3f} m   "
                f"{self.frecuencia_hz:.2f} Hz   {self.reversiones} reversiones   "
                f"({self.muestras} muestras, {self.duracion_s:.1f} s)")


def _tiempos_de_cruce(t_s: Sequence[float], valores: Sequence[float]) -> list[float]:
    """Instantes en que la senal cruza su propia media."""
    if len(valores) < 2:
        return []
    media = sum(valores) / len(valores)
    cruces = []
    for (ta, a), (tb, b) in zip(zip(t_s, valores), zip(t_s[1:], valores[1:])):
        if (a - media > 0) != (b - media > 0):
            # Interpolacion lineal: el cruce rara vez cae en una muestra.
            salto = (b - media) - (a - media)
            frac = 0.0 if salto == 0 else (media - a) / (b - a) if b != a else 0.0
            cruces.append(ta + max(0.0, min(1.0, frac)) * (tb - ta))
    return cruces


def _frecuencia(t_s: Sequence[float], valores: Sequence[float]) -> tuple[float, int]:
    """`(frecuencia_hz, numero_de_cruces)` por espaciado entre cruces.

    Contar cruces y dividir por la duracion total sesga el resultado cuando la
    grabacion no cubre un numero entero de ciclos: con 2.5 ciclos aparece un
    cruce de mas y la frecuencia sale un 20 % alta. Medir entre el primer y el
    ultimo cruce elimina esos bordes.
    """
    cruces = _tiempos_de_cruce(t_s, valores)
    if len(cruces) < 2:
        return 0.0, len(cruces)
    tramo = cruces[-1] - cruces[0]
    if tramo <= 0:
        return 0.0, len(cruces)
    return (len(cruces) - 1) / (2.0 * tramo), len(cruces)


def medir_oscilacion(
    t_s: Sequence[float],
    error_x: Sequence[float],
    error_y: Sequence[float],
) -> Oscilacion | None:
    """Resume el error horizontal respecto del objetivo.

    `error_x`/`error_y` son posicion menos objetivo, en metros. Devuelve `None`
    si no hay muestras suficientes para decir nada.
    """
    n = min(len(t_s), len(error_x), len(error_y))
    if n < 4:
        return None
    t_s, error_x, error_y = list(t_s[:n]), list(error_x[:n]), list(error_y[:n])
    duracion = t_s[-1] - t_s[0]
    if duracion <= 0:
        return None

    distancias = [math.hypot(x, y) for x, y in zip(error_x, error_y)]
    rms = math.sqrt(sum(d * d for d in distancias) / n)
    amplitud = (max(distancias) - min(distancias)) / 2.0

    # La frecuencia se toma del eje que mas se mueve: el otro suele ser ruido.
    span_x = max(error_x) - min(error_x)
    span_y = max(error_y) - min(error_y)
    dominante = error_x if span_x >= span_y else error_y
    frecuencia, cruces = _frecuencia(t_s, dominante)

    return Oscilacion(
        muestras=n,
        duracion_s=duracion,
        rms_error_m=rms,
        amplitud_m=amplitud,
        frecuencia_hz=frecuencia,
        reversiones=cruces,
    )


def medir_desde_filas(filas, *, solo_en_vuelo: bool = True) -> Oscilacion | None:
    """`medir_oscilacion` sobre las filas de un CSV de sesion.

    Espera las columnas `t_s`, `mocap_x_m`, `mocap_y_m`, `target_x_m`,
    `target_y_m` y `airborne`.
    """
    t_s, ex, ey = [], [], []
    for fila in filas:
        if fila.get("kind") == "event":
            continue
        if solo_en_vuelo and str(fila.get("airborne")) != "True":
            continue
        try:
            x, y = float(fila["mocap_x_m"]), float(fila["mocap_y_m"])
            tx, ty = float(fila["target_x_m"]), float(fila["target_y_m"])
            t_s.append(float(fila["t_s"]))
        except (KeyError, TypeError, ValueError):
            continue
        ex.append(x - tx)
        ey.append(y - ty)
    return medir_oscilacion(t_s, ex, ey)
