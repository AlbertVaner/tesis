"""Maquina de modos del vocabulario: que gesto vale en que modo. Sin dron.

Es la logica que antes vivia dentro del `Simulador` de `probar_vocabulario.py`
y que el controlador real necesita igual. Aqui no hay camara, ni `cv2`, ni
Crazyflie: entra el nombre de un gesto y si el dron esta en el aire, y sale
una `Decision` con la accion abstracta que corresponde, o `ignorado` con el
motivo. Convertir esa accion en una orden de vuelo es trabajo del controlador
que la consume (regla 6 de `AGENTS.md`).

Dos modos excluyentes, y el aplauso conmuta
-------------------------------------------
Probado en vivo con todo activo a la vez, los estaticos y los dinamicos se
pisan: un brazo abajo y al frente es por donde pasan los brazos al empezar y
terminar cualquier gesto dinamico. Por eso:

    MODO DINAMICO (al arrancar)    senalero, ven_aca, arco, circulo
    MODO ESTATICO                  ARRIBA, ABAJO, ADELANTE, ATRAS, IZQUIERDA, DERECHA

`aplaudir` cambia de modo en las dos direcciones, es el unico gesto dinamico
que se escucha en modo estatico, y cambiar de modo deja al dron en hover.

El paro (una postura sostenida) manda sobre los dos modos y bloquea todo hasta
que se suelta; al soltarse, el vocabulario arranca otra vez en modo dinamico.

Quien lleva la cuenta de `en_aire`
----------------------------------
La maquina **no** sabe si el dron esta en el aire: se lo dicen en cada
decision. En el probador lo lleva el simulador; en el controlador lo dice el
backend de vuelo, que es el unico que sabe de verdad si despego o si un
watchdog lo aterrizo. Si la maquina lo llevara por su cuenta, un despegue
rechazado por el backend dejaria a los dos en desacuerdo.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

DINAMICO, ESTATICO = "dinamico", "estatico"

#: Comportamiento continuo que pide cada gesto dinamico de navegacion.
MODOS_DINAMICOS = {"ven_aca": "SEGUIR", "arco": "ALEJARSE", "circulo": "ORBITAR"}

#: Gesto dinamico que conmuta de modo y gesto que alterna despegue/aterrizaje.
CONMUTADOR = "aplaudir"
SENALERO = "senalero"

#: Gestos de estado del canal estatico (`body_3d_rules`), por nombre.
ESTADO_ESTATICO = ("DESPEGAR", "ATERRIZAR", "STOP")

#: Comportamientos del dron que la maquina puede pedir.
HOVER = "hover"
MANUAL = "MANUAL"
IGNORADO = "ignorado"

#: Acciones puntuales, para que el controlador no compare cadenas sueltas.
DESPEGAR, ATERRIZAR, PARO = "DESPEGAR", "ATERRIZAR", "PARO"


class Decision(NamedTuple):
    """Lo que la maquina decidio para un gesto.

    `motivo` va vacio cuando la accion se ejecuta; si no, dice por que se
    ignoro. Es una tupla para que `accion, motivo = decision` funcione.
    """

    accion: str
    motivo: str = ""

    @property
    def ejecutar(self) -> bool:
        return self.accion != IGNORADO


@dataclass
class MaquinaDeModos:
    """Estado del vocabulario: modo, comportamiento pedido y paro."""

    control: str = DINAMICO
    comportamiento: str = HOVER     #: hover, SEGUIR, ALEJARSE, ORBITAR, MANUAL
    paro_activo: bool = False

    def reset(self) -> None:
        self.control = DINAMICO
        self.comportamiento = HOVER
        self.paro_activo = False

    def hover(self) -> None:
        """Olvida cualquier comportamiento en curso."""
        self.comportamiento = HOVER

    # ---- eventos

    def gesto(self, nombre: str, *, en_aire: bool) -> Decision:
        """Un gesto dinamico o de estado terminado."""
        if self.paro_activo:
            return Decision(IGNORADO, "paro activo")
        if nombre == CONMUTADOR:
            self.control = ESTATICO if self.control == DINAMICO else DINAMICO
            self.hover()
            return Decision(f"MODO {self.control.upper()}")
        if nombre == SENALERO or nombre in MODOS_DINAMICOS:
            if self.control != DINAMICO:
                return Decision(IGNORADO, "modo estatico (aplaudir para cambiar)")
            if nombre == SENALERO:
                self.hover()
                return Decision(ATERRIZAR if en_aire else DESPEGAR)
            if not en_aire:
                return Decision(IGNORADO, "en el suelo (senalero primero)")
            self.comportamiento = MODOS_DINAMICOS[nombre]
            return Decision(self.comportamiento)
        if nombre in ESTADO_ESTATICO:
            if self.control != ESTATICO:
                return Decision(IGNORADO, "modo dinamico (aplaudir para cambiar)")
            if nombre == DESPEGAR:
                if en_aire:
                    return Decision(IGNORADO, "ya en el aire")
                self.hover()
                return Decision(DESPEGAR)
            if nombre == ATERRIZAR:
                if not en_aire:
                    return Decision(IGNORADO, "ya en el suelo")
                self.hover()
                return Decision(ATERRIZAR)
            self.hover()
            return Decision("HOVER")
        return Decision(IGNORADO, f"gesto sin comando: {nombre}")

    def navegar(self, nombre: str, *, en_aire: bool) -> Decision:
        """Canal continuo: una direccion confirmada, cada frame."""
        if self.paro_activo:
            return Decision(IGNORADO, "paro activo")
        if self.control != ESTATICO:
            return Decision(IGNORADO, "modo dinamico (aplaudir para cambiar)")
        if not en_aire:
            return Decision(IGNORADO, "en el suelo")
        self.comportamiento = MANUAL
        return Decision(MANUAL)

    def soltar_navegacion(self) -> bool:
        """Sin direccion confirmada. `True` si habia navegacion manual en curso."""
        return self.comportamiento == MANUAL

    def paro(self) -> Decision:
        """Bloquea todo y vuelve a modo dinamico. Siempre se ejecuta."""
        self.paro_activo = True
        self.control = DINAMICO
        self.hover()
        return Decision(PARO)

    def soltar_paro(self) -> None:
        self.paro_activo = False
