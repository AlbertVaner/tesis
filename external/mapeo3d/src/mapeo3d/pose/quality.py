"""Calidad del estimador 2D: ruido en reposo y encuadre.

Dos medidas que deciden dónde montar una cámara, y que hay que tomar **antes**
de fijarla porque esa decisión es difícil de deshacer. Ver docs/operations.md.

Este módulo no sabe que existen varias cámaras ni qué es RTSP: recibe
secuencias de landmarks de una cámara. Ver AGENTS.md, punto 3.

Por qué el jitter en reposo es la medida correcta
-------------------------------------------------
Con el sujeto **quieto**, cualquier movimiento que reporte el estimador es
error suyo. Eso convierte «esta cámara se ve mejor» en un número en píxeles, y
es el número que entra directamente en el presupuesto de error de la
triangulación: el ruido de detección 2D es lo que se propaga a la
reconstrucción 3D.

Se mide a varias distancias porque no escala de forma obvia: al alejarse, el
cuerpo ocupa menos píxeles y el estimador empeora, pero además cada píxel vale
más milímetros. Las dos cosas van en la misma dirección y el resultado hay que
medirlo, no deducirlo.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .landmarks import INDICE, NOMBRES

# Landmarks que más importan para gestos: son los extremos, los que más se
# mueven y los que peor estima cualquier modelo de pose.
CLAVE = ("left_wrist", "right_wrist", "left_ankle", "right_ankle",
         "left_elbow", "right_elbow")

# Margen respecto del borde del cuadro, en fracción del ancho/alto. Un landmark
# más cerca del borde que esto se considera en riesgo de salirse: MediaPipe
# extrapola fuera del cuadro y esos valores no son fiables.
MARGEN = 0.02


@dataclass
class Jitter:
    """Ruido de posición con el sujeto quieto, por landmark."""

    desviacion_px: np.ndarray      # (K,) desviación típica del radio, en px
    n: np.ndarray                  # (K,) muestras usadas
    distancia_m: float = 0.0

    def de(self, nombre: str) -> float:
        return float(self.desviacion_px[INDICE[nombre]])

    @property
    def mediana_clave_px(self) -> float:
        """Un solo número para comparar cámaras entre sí."""
        v = [self.de(n) for n in CLAVE if self.n[INDICE[n]] > 10]
        return float(np.median(v)) if v else float("nan")

    def milimetros(self, fx_px: float, distancia_m: float | None = None) -> float:
        """Convierte el jitter mediano a milímetros sobre el sujeto.

        Un píxel a distancia `d` con focal `fx` abarca `d / fx` metros. Es la
        cifra que se compara con el error que se puede tolerar en un gesto.
        """
        d = self.distancia_m if distancia_m is None else distancia_m
        if fx_px <= 0 or d <= 0:
            return float("nan")
        return self.mediana_clave_px * (d / fx_px) * 1000.0

    def resumen(self) -> str:
        lineas = [
            f"Jitter en reposo a {self.distancia_m:.1f} m "
            f"(mediana de los landmarks clave: {self.mediana_clave_px:.2f} px)"
        ]
        for nombre in CLAVE:
            i = INDICE[nombre]
            if self.n[i] <= 10:
                lineas.append(f"  {nombre:<14} sin datos suficientes")
            else:
                lineas.append(f"  {nombre:<14} {self.desviacion_px[i]:6.2f} px"
                              f"   (n={int(self.n[i])})")
        return "\n".join(lineas)


def jitter_en_reposo(
    secuencia_px: np.ndarray,
    visibilidad: np.ndarray | None = None,
    *,
    distancia_m: float = 0.0,
    min_visibilidad: float = 0.5,
) -> Jitter:
    """Ruido de posición de cada landmark con el sujeto quieto.

    Args:
        secuencia_px: `(T, K, 2)` en píxeles.
        visibilidad: `(T, K)` opcional; por debajo de `min_visibilidad` el
            frame no cuenta para ese landmark.
        distancia_m: a qué distancia se tomó, sólo para etiquetar.

    Returns:
        `Jitter` con la desviación típica del **radio** respecto de la posición
        media, por landmark. Se usa el radio y no cada eje por separado porque
        lo que importa es cuánto se mueve el punto, no en qué dirección.
    """
    S = np.asarray(secuencia_px, dtype=np.float64)
    if S.ndim != 3 or S.shape[2] != 2:
        raise ValueError(f"secuencia_px debe ser (T, K, 2); es {S.shape}.")
    k = S.shape[1]

    ok = np.all(np.isfinite(S), axis=2)
    if visibilidad is not None:
        ok &= np.asarray(visibilidad, dtype=np.float64) >= min_visibilidad

    desv = np.full(k, np.nan)
    n = np.zeros(k, dtype=int)
    for j in range(k):
        pts = S[ok[:, j], j, :]
        n[j] = len(pts)
        if len(pts) > 10:
            radio = np.linalg.norm(pts - pts.mean(axis=0), axis=1)
            desv[j] = float(radio.std())
    return Jitter(desv, n, distancia_m)


@dataclass
class Encuadre:
    """Si el cuerpo cabe entero en el cuadro, y con cuánto margen."""

    fraccion_completa: float       # frames con TODO el cuerpo dentro
    fraccion_con_brazos: float     # ídem, contando muñecas por encima de hombros
    landmarks_problematicos: list[str]
    n_frames: int

    @property
    def cabe(self) -> bool:
        return self.fraccion_completa >= 0.95

    def resumen(self) -> str:
        estado = "OK" if self.cabe else "NO CABE"
        lineas = [
            f"Encuadre: {estado} — cuerpo completo en el "
            f"{self.fraccion_completa * 100:.0f} % de {self.n_frames} frames",
        ]
        if self.fraccion_con_brazos > 0:
            lineas.append(f"  con los brazos en alto: "
                          f"{self.fraccion_con_brazos * 100:.0f} %")
        if self.landmarks_problematicos:
            lineas.append("  se salen del cuadro: "
                          + ", ".join(self.landmarks_problematicos[:6]))
        return "\n".join(lineas)


def evaluar_encuadre(
    secuencia_norm: np.ndarray,
    *,
    margen: float = MARGEN,
) -> Encuadre:
    """Cuántos frames tienen el cuerpo entero dentro del cuadro.

    Args:
        secuencia_norm: `(T, K, 2)` **normalizado** a `[0, 1]`, tal como sale
            de `Landmarks2D.xy`. Se usa normalizado porque la pregunta es sobre
            el cuadro, no sobre píxeles concretos.

    Es la comprobación que decide la distancia de montaje. MediaPipe extrapola
    landmarks fuera del cuadro sin avisar, así que un cuerpo que «se ve
    completo» en la ventana puede estar produciendo tobillos inventados.
    """
    S = np.asarray(secuencia_norm, dtype=np.float64)
    if S.ndim != 3 or S.shape[2] != 2:
        raise ValueError(f"secuencia_norm debe ser (T, K, 2); es {S.shape}.")

    dentro = np.all((S >= margen) & (S <= 1.0 - margen), axis=2)
    dentro &= np.all(np.isfinite(S), axis=2)
    completo = dentro.all(axis=1)

    # "Brazos en alto": las dos muñecas por encima de los hombros. En
    # coordenadas de imagen, más arriba es MENOR y, así que se compara al revés.
    iw = [INDICE["left_wrist"], INDICE["right_wrist"]]
    ish = [INDICE["left_shoulder"], INDICE["right_shoulder"]]
    arriba = np.all(S[:, iw, 1] < S[:, ish, 1].min(axis=1, keepdims=True), axis=1)
    con_brazos = (completo & arriba).sum() / max(arriba.sum(), 1) if arriba.any() else 0.0

    fuera = (~dentro).mean(axis=0)
    problematicos = [NOMBRES[i] for i in np.argsort(-fuera) if fuera[i] > 0.05]

    return Encuadre(
        fraccion_completa=float(completo.mean()),
        fraccion_con_brazos=float(con_brazos),
        landmarks_problematicos=problematicos,
        n_frames=len(S),
    )
