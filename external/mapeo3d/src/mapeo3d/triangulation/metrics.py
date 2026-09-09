"""Medidas de calidad de una reconstrucción 3D, sin verdad de terreno.

El problema que resuelve este módulo: **cómo saber si la triangulación es
buena cuando no hay nada con qué compararla**. El residual de reproyección no
alcanza —un error de escala reproyecta perfectamente— y el MoCap sólo está
disponible en sesiones de validación preparadas.

La respuesta es la misma idea que `grid_spacing()` en `dlt.py`, que mide la
casilla reconstruida de un tablero de dimensión conocida. Aquí se aplica a un
cuerpo: **el antebrazo mide lo mismo en todos los frames de una sesión**. No
hace falta saber cuánto mide; basta con que no cambie. La desviación de su
longitud reconstruida a lo largo del tiempo es una medida directa de la calidad
del 3D, y se obtiene de una persona moviéndose libremente, sin marcadores, sin
objeto de referencia y sin MoCap.

Sirve igual para lo que hay que comparar en la tesis: la misma medida sobre la
triangulación calibrada y sobre `pose_world_landmarks` de MediaPipe dice cuál
de las dos es más estable, en las mismas unidades y sobre la misma grabación.

Este módulo **no conoce MediaPipe ni nombres de articulaciones**: recibe pares
de índices. La traducción de `("left_elbow", "left_wrist")` a `(13, 15)` la hace
`pose.pares_de_huesos()`. Ver AGENTS.md, reglas de dependencias.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def segment_lengths(puntos3d: np.ndarray, pares: np.ndarray) -> np.ndarray:
    """Longitud de cada segmento en un instante.

    Args:
        puntos3d: `(K, 3)`. Los landmarks no reconstruidos son `NaN`.
        pares: `(M, 2)` índices de los extremos de cada segmento.

    Returns:
        `(M,)` en las mismas unidades que `puntos3d`; `NaN` donde falte un
        extremo.
    """
    X = np.asarray(puntos3d, dtype=np.float64).reshape(-1, 3)
    p = np.asarray(pares, dtype=int).reshape(-1, 2)
    return np.linalg.norm(X[p[:, 0]] - X[p[:, 1]], axis=1)


@dataclass
class EstabilidadSegmentos:
    """Cuánto varía la longitud reconstruida de cada segmento en una sesión."""

    media: np.ndarray          # (M,) longitud media
    desviacion: np.ndarray     # (M,) desviación estándar
    n: np.ndarray              # (M,) frames en los que se pudo medir
    n_frames: int

    @property
    def variacion(self) -> np.ndarray:
        """Coeficiente de variación por segmento: `desviacion / media`.

        Es la cifra comparable entre segmentos y entre métodos, porque un
        muslo y un antebrazo no tienen por qué tener la misma desviación
        absoluta para estar igual de bien medidos.
        """
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(self.media > 0, self.desviacion / self.media, np.nan)

    @property
    def variacion_media(self) -> float:
        """Un solo número para comparar dos reconstrucciones."""
        v = self.variacion
        v = v[np.isfinite(v)]
        return float(np.mean(v)) if v.size else float("nan")

    def resumen(self, nombres: list[str] | None = None) -> str:
        lineas = [
            f"Estabilidad de segmentos sobre {self.n_frames} frames "
            f"(variación media {self.variacion_media * 100:.2f} %)",
        ]
        for i, (m, d, c, v) in enumerate(
            zip(self.media, self.desviacion, self.n, self.variacion)
        ):
            etiqueta = nombres[i] if nombres and i < len(nombres) else f"seg {i}"
            if not np.isfinite(m):
                lineas.append(f"  {etiqueta:<28} sin datos")
                continue
            lineas.append(
                f"  {etiqueta:<28} {m * 1000:7.1f} mm  +-{d * 1000:6.1f}  "
                f"({v * 100:5.2f} %)  n={int(c)}"
            )
        return "\n".join(lineas)


def segment_length_stability(
    secuencia: np.ndarray,
    pares: np.ndarray,
    *,
    minimo_frames: int = 5,
) -> EstabilidadSegmentos:
    """Estabilidad de las longitudes a lo largo de una secuencia.

    Args:
        secuencia: `(T, K, 3)`, un frame por instante. `NaN` donde no se
            reconstruyó.
        pares: `(M, 2)` índices.
        minimo_frames: por debajo de esto un segmento se reporta sin datos, en
            lugar de con una desviación calculada sobre dos muestras.
    """
    S = np.asarray(secuencia, dtype=np.float64)
    if S.ndim != 3 or S.shape[2] != 3:
        raise ValueError(f"secuencia debe ser (T, K, 3); es {S.shape}.")
    p = np.asarray(pares, dtype=int).reshape(-1, 2)

    L = np.array([segment_lengths(f, p) for f in S])  # (T, M)
    validos = np.isfinite(L)
    n = validos.sum(axis=0)

    media = np.full(len(p), np.nan)
    desv = np.full(len(p), np.nan)
    for j in range(len(p)):
        if n[j] >= minimo_frames:
            col = L[validos[:, j], j]
            media[j] = float(col.mean())
            desv[j] = float(col.std())

    return EstabilidadSegmentos(media, desv, n, len(S))
