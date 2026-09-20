"""Mostrar un lienzo en una ventana de OpenCV sin deformarlo.

En Windows, una ventana `WINDOW_NORMAL` **estira** la imagen hasta llenar su
tamano, sin respetar la proporcion. Con un tamano fijo apaisado (1280x720) eso
no se notaba mientras todas las fuentes eran apaisadas. Desde el 2026-09-18 la
camara IP del laboratorio esta montada de lado y entrega el cuadro en vertical
(480x640 el sub-stream): en una ventana apaisada la persona salia aplastada.

`mostrar` ajusta la ventana a la proporcion del lienzo la primera vez, y otra
vez solo si el lienzo cambia de forma, asi que si el usuario la redimensiona a
mano se respeta.
"""

from __future__ import annotations

import cv2

#: Alto maximo de la ventana, en pixeles de pantalla.
ALTO_MAXIMO = 900

_formas: dict[str, tuple[int, int]] = {}


def tamano_ventana(ancho: int, alto: int, alto_maximo: int = ALTO_MAXIMO) -> tuple[int, int]:
    """`(ancho, alto)` de ventana con la proporcion del lienzo, sin pasar del maximo."""
    escala = min(1.0, alto_maximo / alto)
    return max(1, round(ancho * escala)), max(1, round(alto * escala))


def mostrar(nombre: str, lienzo) -> None:
    """`cv2.imshow` que mantiene la proporcion. La ventana debe existir ya."""
    alto, ancho = lienzo.shape[:2]
    if _formas.get(nombre) != (ancho, alto):
        _formas[nombre] = (ancho, alto)
        cv2.resizeWindow(nombre, *tamano_ventana(ancho, alto))
    cv2.imshow(nombre, lienzo)
