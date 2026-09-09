"""Latencia extremo a extremo de una cámara, medida con destellos.

El número que interesa para control no es el frame rate sino **cuánto tarda un
suceso del mundo en llegar a memoria**: exposición, codificación, red y
decodificación. Es invisible en la imagen —se ve perfecta— y es lo que decide
si un gesto se puede usar para pilotar.

El método
---------
Se hace destellar la pantalla apuntando a la cámara y se busca el escalón de
brillo en los frames que llegan. La diferencia entre el instante en que se pintó
el destello y la marca de llegada del primer frame iluminado es la latencia.

Qué incluye y qué no
--------------------
Incluye el retardo del monitor (unos 5-15 ms) y el tiempo hasta que el frame
está decodificado en memoria. **No** es «glass-to-glass»: no incluye pintar el
resultado en pantalla. Es exactamente el retardo que sufre el lazo de
percepción, que es lo que se quiere acotar.

El retardo del monitor se puede descontar si se conoce, pero conviene no
hacerlo: deja la cifra como cota superior, que es el lado seguro.

Este módulo no abre cámaras ni ventanas: recibe series de tiempo y devuelve
números. Se prueba sin hardware.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# Cuántas desviaciones típicas por encima del brillo de reposo cuenta como
# destello. 5 sigma es holgado: el escalón de un monitor en blanco es enorme
# comparado con el ruido del sensor.
UMBRAL_SIGMA = 5.0

# Un solo frame brillante puede ser un artefacto de compresión. Se exige que el
# siguiente también lo esté, salvo que sea el último de la serie.
CONFIRMAR_SIGUIENTE = True


@dataclass
class Latencia:
    """Resultado de una campaña de medidas de latencia."""

    muestras_s: list[float] = field(default_factory=list)
    intentos: int = 0

    @property
    def n(self) -> int:
        return len(self.muestras_s)

    @property
    def mediana_ms(self) -> float:
        return float(np.median(self.muestras_s)) * 1000.0 if self.muestras_s else float("nan")

    @property
    def p95_ms(self) -> float:
        return float(np.percentile(self.muestras_s, 95)) * 1000.0 if self.muestras_s else float("nan")

    @property
    def min_ms(self) -> float:
        return min(self.muestras_s) * 1000.0 if self.muestras_s else float("nan")

    def resumen(self) -> str:
        if not self.muestras_s:
            return (f"Latencia: sin medidas válidas de {self.intentos} intentos "
                    "(¿la cámara apunta a la pantalla?)")
        return (f"Latencia extremo a extremo: mediana {self.mediana_ms:.0f} ms, "
                f"mínimo {self.min_ms:.0f} ms, p95 {self.p95_ms:.0f} ms "
                f"({self.n}/{self.intentos} destellos detectados)")


def detectar_flanco(
    tiempos: np.ndarray,
    brillos: np.ndarray,
    t_destello: float,
    *,
    umbral_sigma: float = UMBRAL_SIGMA,
    confirmar: bool = CONFIRMAR_SIGUIENTE,
) -> float | None:
    """Latencia en segundos entre el destello y el primer frame iluminado.

    Args:
        tiempos: `(N,)` marcas de llegada de los frames, monotónicas.
        brillos: `(N,)` brillo medio de cada frame.
        t_destello: instante en que se pintó el destello, mismo reloj.

    Returns:
        Segundos, o `None` si no se distingue ningún escalón. Devolver `None` es
        parte del contrato: una medida dudosa contamina la mediana, y con
        destellos sobran las muestras.
    """
    t = np.asarray(tiempos, dtype=np.float64)
    b = np.asarray(brillos, dtype=np.float64)
    if t.shape != b.shape or t.size < 4:
        return None

    antes = b[t < t_destello]
    despues_idx = np.flatnonzero(t >= t_destello)
    if antes.size < 3 or despues_idx.size < 1:
        return None

    base, ruido = float(antes.mean()), float(antes.std())
    # Un sensor sin ruido daría sigma 0 y cualquier variación pasaría el
    # umbral; se pone un suelo para no disparar con nada.
    umbral = base + umbral_sigma * max(ruido, 1.0)

    for pos, i in enumerate(despues_idx):
        if b[i] <= umbral:
            continue
        if confirmar and pos + 1 < despues_idx.size:
            if b[despues_idx[pos + 1]] <= umbral:
                continue      # destello de un solo frame: artefacto
        return float(t[i] - t_destello)
    return None


def brillo(frame) -> float:
    """Brillo medio de un frame, submuestreado para que sea barato.

    Se toma un décimo de las filas y columnas: con un destello a pantalla
    completa sobra, y evita recorrer 2.7 MP por frame en el lazo de medida.
    """
    a = np.asarray(frame)
    if a.ndim == 3:
        a = a[..., 0]
    return float(a[::10, ::10].mean())
