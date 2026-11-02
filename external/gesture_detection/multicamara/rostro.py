"""Cuanto se ve el rostro del operador en una camara.

Se calcula con los landmarks de MediaPipe Pose que ya hay, sin un segundo
modelo de cara: nariz, ojos y orejas bastan para saber si la persona mira a
la camara. Tres factores, todos en `[0, 1]`:

- **frontal**: la nariz cae en medio de las dos orejas. De perfil se va hacia
  una de ellas; de espaldas las orejas se cruzan (la izquierda de la persona
  queda a la izquierda de la imagen) y el factor vale 0.
- **visibilidad**: la media de lo que MediaPipe dice ver de nariz y ojos.
- **tamano**: la distancia entre orejas respecto al alto del cuadro. Mas
  cerca, mas pixeles de cara. Satura en `TAMANO_PLENO` para que una camara
  pegada al operador no gane solo por cercania.

El puntaje es `frontal * visibilidad * (0.5 + 0.5 * tamano)`: la orientacion
manda y el tamano solo desempata.

Los landmarks van **sin espejo**: con la imagen volteada se intercambian las
etiquetas izquierda/derecha y el criterio de espaldas se invierte.
"""

from __future__ import annotations

from dataclasses import dataclass

NARIZ = 0
OJO_IZQ = 2
OJO_DER = 5
OREJA_IZQ = 7
OREJA_DER = 8

#: Distancia entre orejas, en fraccion del alto del cuadro, a partir de la cual
#: la cara ya se ve lo bastante grande.
TAMANO_PLENO = 0.06


@dataclass(frozen=True)
class Rostro:
    puntaje: float
    frontal: float
    visibilidad: float
    tamano: float


SIN_ROSTRO = Rostro(0.0, 0.0, 0.0, 0.0)


def _acotar(x: float) -> float:
    return min(1.0, max(0.0, x))


def puntaje_rostro(landmarks, ancho: int, alto: int) -> Rostro:
    """`Rostro` a partir de `pose_landmarks` normalizados, o `SIN_ROSTRO`."""
    if landmarks is None:
        return SIN_ROSTRO
    nariz = landmarks[NARIZ]
    oreja_izq, oreja_der = landmarks[OREJA_IZQ], landmarks[OREJA_DER]

    # En pixeles: x e y vienen normalizados a lados distintos del cuadro.
    x_izq, x_der = oreja_izq.x * ancho, oreja_der.x * ancho
    envergadura = x_izq - x_der          # > 0 de frente, < 0 de espaldas
    if envergadura <= 1.0:
        return SIN_ROSTRO
    medio = 0.5 * (x_izq + x_der)
    desvio = abs(nariz.x * ancho - medio) / (0.5 * envergadura)
    frontal = _acotar(1.0 - desvio)

    visibilidad = _acotar(
        (nariz.visibility + landmarks[OJO_IZQ].visibility + landmarks[OJO_DER].visibility) / 3.0
    )
    orejas_px = ((x_izq - x_der) ** 2 + ((oreja_izq.y - oreja_der.y) * alto) ** 2) ** 0.5
    tamano = _acotar(orejas_px / (TAMANO_PLENO * alto))

    puntaje = frontal * visibilidad * (0.5 + 0.5 * tamano)
    return Rostro(puntaje, frontal, visibilidad, tamano)


def caja_rostro(landmarks, ancho: int, alto: int) -> tuple[int, int, int, int] | None:
    """Recuadro `(x0, y0, x1, y1)` en pixeles alrededor de la cabeza, para dibujar.

    Centrado en la nariz, con el ancho de las orejas mas un margen. De
    espaldas o de perfil cerrado no hay cara que enmarcar y devuelve `None`.
    """
    if landmarks is None:
        return None
    nariz = landmarks[NARIZ]
    x_izq, x_der = landmarks[OREJA_IZQ].x * ancho, landmarks[OREJA_DER].x * ancho
    envergadura = x_izq - x_der
    if envergadura <= 1.0 or nariz.visibility < 0.3:
        return None
    cx, cy = nariz.x * ancho, nariz.y * alto
    medio_ancho = 0.7 * envergadura
    return (int(cx - medio_ancho), int(cy - 1.1 * medio_ancho),
            int(cx + medio_ancho), int(cy + 0.9 * medio_ancho))
