"""Detección de episodios en una señal derivada de la pose.

El problema que resuelve, medido sobre una grabación real de 60 s a 30 fps con
palmadas y gestos rápidos:

    método                            30 fps   15 fps   se conserva
    mínimos locales (instante)          48       28        58 %
    episodios (trayectoria)             11       10-11    91-100 %

Buscar el **instante** del contacto pierde el 42 % de los eventos al bajar a
15 fps, porque el contacto dura 50-100 ms y a 15 fps eso es un frame. Buscar el
**episodio** —la señal baja del umbral, alcanza un mínimo, y vuelve a subir—
abarca 400-600 ms y sobrevive a cualquier tasa razonable.

La conclusión práctica es que el frame rate no era el límite: lo era el
detector. Ver docs/pose.md.

Qué hay aquí y qué no
---------------------
Aquí está la **primitiva temporal**: dada una señal escalar en el tiempo,
encontrar sus episodios. Y los constructores de señales genéricos —distancia
entre dos landmarks, rapidez de uno— que no nombran ningún gesto.

**La traducción de un episodio a un comando de vuelo no está aquí.** Eso es
clasificación de intención y vive en el repositorio `tesis`. Ver AGENTS.md.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# La salida se exige más alta que la entrada para no contar dos veces un
# episodio cuya señal tiembla alrededor del umbral. Es histéresis: sin ella,
# un solo evento con ruido produce una ráfaga de detecciones.
FACTOR_SALIDA = 1.35

# Duración mínima de un episodio, en segundos. Se expresa en tiempo y no en
# frames a propósito: así el detector se comporta igual a 15 que a 30 fps,
# que es justamente la propiedad que se busca.
MIN_DURACION_S = 0.10

# Huecos más largos que esto cierran el episodio. Por debajo se toleran: la
# pose se pierde durante décimas de segundo con bastante frecuencia, y partir
# un episodio por eso produciría dos detecciones donde hubo una.
HUECO_MAXIMO_S = 0.25


@dataclass
class Episodio:
    """Un tramo en que la señal se mantuvo por debajo del umbral."""

    inicio: int
    fin: int
    pico: int
    valor_pico: float
    t_inicio: float
    t_pico: float
    duracion_s: float

    @property
    def n_frames(self) -> int:
        return self.fin - self.inicio + 1


def detectar_episodios(
    senal: np.ndarray,
    tiempos: np.ndarray | None = None,
    *,
    umbral: float,
    factor_salida: float = FACTOR_SALIDA,
    min_duracion_s: float = MIN_DURACION_S,
    hueco_maximo_s: float = HUECO_MAXIMO_S,
    fps: float = 30.0,
) -> list[Episodio]:
    """Episodios en que `senal` baja de `umbral` y vuelve a subir.

    Args:
        senal: `(T,)`. Los `NaN` se tratan como huecos, no como valores.
        tiempos: `(T,)` en segundos. Si falta, se derivan de `fps`.
        umbral: la señal entra en episodio por debajo de este valor.
        factor_salida: sale cuando supera `umbral * factor_salida`.
        min_duracion_s: episodios más cortos se descartan por ruido.
        hueco_maximo_s: huecos de datos más largos cierran el episodio.

    Returns:
        Lista de `Episodio` en orden temporal.

    El umbral de salida es mayor que el de entrada **a propósito**. Con un solo
    umbral, una señal que roza el límite genera decenas de episodios donde hubo
    uno; es el mismo motivo por el que un termostato tiene banda muerta.
    """
    s = np.asarray(senal, dtype=np.float64).ravel()
    if tiempos is None:
        t = np.arange(len(s), dtype=np.float64) / max(fps, 1e-9)
    else:
        t = np.asarray(tiempos, dtype=np.float64).ravel()
        if len(t) != len(s):
            raise ValueError(
                f"senal y tiempos deben tener el mismo largo; "
                f"son {len(s)} y {len(t)}."
            )
    if len(s) == 0:
        return []

    salida_umbral = umbral * factor_salida
    episodios: list[Episodio] = []

    dentro = False
    i0 = pico = 0
    v_pico = np.inf
    t_ultimo_dato = t[0]

    def cerrar(i_fin: int) -> None:
        nonlocal dentro
        dentro = False
        dur = float(t[i_fin] - t[i0])
        if dur >= min_duracion_s:
            episodios.append(Episodio(i0, i_fin, pico, float(v_pico),
                                      float(t[i0]), float(t[pico]), dur))

    for i, v in enumerate(s):
        if not np.isfinite(v):
            # Hueco: sólo cierra el episodio si dura demasiado.
            if dentro and t[i] - t_ultimo_dato > hueco_maximo_s:
                cerrar(max(i - 1, i0))
            continue
        t_ultimo_dato = t[i]

        if not dentro:
            if v < umbral:
                dentro = True
                i0 = pico = i
                v_pico = v
        else:
            if v < v_pico:
                v_pico, pico = v, i
            if v > salida_umbral:
                cerrar(i - 1 if i > i0 else i0)

    if dentro:
        cerrar(len(s) - 1)
    return episodios


# ------------------------------------------------------------------ señales


def distancia(secuencia: np.ndarray, a: int, b: int) -> np.ndarray:
    """`(T,)` distancia entre dos landmarks a lo largo del tiempo."""
    S = np.asarray(secuencia, dtype=np.float64)
    if S.ndim != 3 or S.shape[2] != 3:
        raise ValueError(f"secuencia debe ser (T, K, 3); es {S.shape}.")
    return np.linalg.norm(S[:, a] - S[:, b], axis=1)


def rapidez(secuencia: np.ndarray, i: int,
            tiempos: np.ndarray | None = None,
            fps: float = 30.0) -> np.ndarray:
    """`(T,)` rapidez de un landmark. El primer valor es `NaN`.

    Se divide por el intervalo real entre frames y no por `1/fps` nominal:
    con cámaras IP el intervalo tiene jitter, y usar el nominal mete un error
    proporcional a ese jitter en cada muestra.
    """
    S = np.asarray(secuencia, dtype=np.float64)
    p = S[:, i]
    if tiempos is None:
        dt = np.full(len(p) - 1, 1.0 / max(fps, 1e-9))
    else:
        dt = np.diff(np.asarray(tiempos, dtype=np.float64))
    v = np.full(len(p), np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        v[1:] = np.linalg.norm(np.diff(p, axis=0), axis=1) / dt
    return v


def umbral_por_percentil(senal: np.ndarray, percentil: float = 12.0) -> float:
    """Umbral adaptado a la sesión, en lugar de una constante absoluta.

    Una distancia entre muñecas de 12 cm significa cosas distintas en personas
    de tamaños distintos y en unidades distintas. Tomar un percentil bajo de la
    propia señal la ancla a lo que ese sujeto hizo de verdad.
    """
    s = np.asarray(senal, dtype=np.float64)
    s = s[np.isfinite(s)]
    return float(np.percentile(s, percentil)) if s.size else float("nan")
