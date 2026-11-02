"""Que camara manda. Con histeresis, porque saltar tambien es un fallo.

Si la camara activa cambiara en cuanto otra la supera por una centesima, el
operador veria la imagen parpadear entre dos camaras con la cara a 45 grados
de ambas, y un gesto a medio sostener se partiria entre dos reconocedores.
Tres reglas:

1. **Margen y tiempo.** Otra camara solo toma el mando si supera a la activa
   por `margen` durante `sostener_s` seguidos.
2. **No durante un gesto.** Mientras la activa esta viendo un gesto (aunque
   no confirmado), no se cambia por preferencia: el gesto termina donde
   empezo.
3. **Perdida.** Si la activa deja de ver la cara (puntaje bajo `minimo`)
   durante `perdida_s`, se pasa a la mejor que haya, gesto o no. Una camara
   que no ve a nadie no puede terminar ningun gesto.

`fijar()` deja una camara elegida a mano y apaga el cambio automatico.
"""

from __future__ import annotations

import time


class SelectorCamara:
    def __init__(self, *, margen: float = 0.15, sostener_s: float = 0.6,
                 perdida_s: float = 1.0, minimo: float = 0.2) -> None:
        self.margen = margen
        self.sostener_s = sostener_s
        self.perdida_s = perdida_s
        self.minimo = minimo
        self.activa: str | None = None
        self.fija: str | None = None
        self._retador: str | None = None
        self._retador_desde = 0.0
        self._perdida_desde: float | None = None

    def fijar(self, nombre: str | None) -> None:
        """Elige camara a mano, o `None` para volver al modo automatico."""
        self.fija = nombre
        if nombre is not None:
            self.activa = nombre
        self._retador = None
        self._perdida_desde = None

    def actualizar(self, puntajes: dict[str, float], *, en_gesto: bool = False,
                   ahora: float | None = None) -> str | None:
        """Nombre de la camara activa tras ver los `puntajes` de este instante."""
        ahora = time.monotonic() if ahora is None else ahora
        if self.fija is not None:
            return self.fija
        if not puntajes:
            return self.activa

        mejor = max(puntajes, key=puntajes.get)
        if self.activa is None or self.activa not in puntajes:
            if puntajes[mejor] >= self.minimo:
                self._cambiar(mejor)
            return self.activa

        actual = puntajes[self.activa]

        # 3. perdida: la activa ya no ve la cara.
        if actual < self.minimo:
            if self._perdida_desde is None:
                self._perdida_desde = ahora
            if (ahora - self._perdida_desde >= self.perdida_s
                    and mejor != self.activa and puntajes[mejor] >= self.minimo):
                self._cambiar(mejor)
            return self.activa
        self._perdida_desde = None

        # 1 y 2. otra la supera claramente y no hay gesto en curso.
        if mejor == self.activa or puntajes[mejor] < actual + self.margen or en_gesto:
            self._retador = None
            return self.activa
        if mejor != self._retador:
            self._retador = mejor
            self._retador_desde = ahora
        elif ahora - self._retador_desde >= self.sostener_s:
            self._cambiar(mejor)
        return self.activa

    def _cambiar(self, nombre: str) -> None:
        self.activa = nombre
        self._retador = None
        self._perdida_desde = None
