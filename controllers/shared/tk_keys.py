"""Esquema de teclado común de los paneles Tkinter.

Dron 1: W/A/S/D adelante/izquierda/atrás/derecha, Espacio sube, Shift baja,
Q y E giran a izquierda y derecha.
Dron 2: flechas, Re Pág sube, Av Pág baja, Inicio y Fin giran.
Comunes: Enter despega o aterriza según el dron esté en el suelo o en el aire,
y **R corta motores**.

El paro estaba en Q hasta septiembre de 2026. Se movió a R al asignar Q y E al
giro: R no tenía uso y queda lejos de las teclas de vuelo, así que no se pulsa
por error mientras se maneja con la izquierda sobre W/A/S/D.

`DualStepKeysMixin`: cada pulsación pide **un paso** (botones high-level).
Sin autorepeat: la tecla debe soltarse antes de repetir. El mixin no conoce
pasos, velocidades ni ángulos: entrega direcciones unitarias y el panel las
escala con sus propias constantes. (`HeldKeysMixin`, la velocidad sostenida de
los paneles Flow Deck, se eliminó con esos paneles en septiembre de 2026.)
"""

from __future__ import annotations

import tkinter as tk

DUAL_KEYSYMS = (
    "w", "a", "s", "d", "space", "Shift_L", "Shift_R",
    "q", "e", "Q", "E",
    "Up", "Down", "Left", "Right", "Prior", "Next",
    "Home", "End",
)

_ALIASES = {"Shift_L": "shift", "Shift_R": "shift", "Prior": "pageup", "Next": "pagedown"}

#: tecla normalizada -> (dron 0/1, ux, uy, uz) con u en {-1, 0, 1}.
KEY_DIRECTIONS: dict[str, tuple[int, int, int, int]] = {
    "w": (0, 1, 0, 0), "s": (0, -1, 0, 0),
    "a": (0, 0, 1, 0), "d": (0, 0, -1, 0),
    "space": (0, 0, 0, 1), "shift": (0, 0, 0, -1),
    "up": (1, 1, 0, 0), "down": (1, -1, 0, 0),
    "left": (1, 0, 1, 0), "right": (1, 0, -1, 0),
    "pageup": (1, 0, 0, 1), "pagedown": (1, 0, 0, -1),
}

#: tecla normalizada -> (dron 0/1, giro) con giro en {-1, +1}.
#:
#: El signo sigue la convención del marco del Robotat y del firmware: **+1 es
#: antihorario visto desde arriba**, que es girar a la izquierda del operador.
KEY_ROTATIONS: dict[str, tuple[int, int]] = {
    "q": (0, 1), "e": (0, -1),
    "home": (1, 1), "end": (1, -1),
}

#: Teclas que no mueven: se atienden con su propia acción.
EMERGENCY_KEYSYMS = ("r", "R")
TAKEOFF_LAND_KEYSYMS = ("Return", "KP_Enter")

#: Resumen para pintar en los paneles. Un solo sitio que actualizar.
AYUDA_TECLADO_DUAL = (
    "D1: WASD + Espacio/Shift + Q/E giro\n"
    "D2: flechas + RePág/AvPág + Inicio/Fin giro\n"
    "ENTER = despegar o aterrizar    R = EMERGENCIA"
)
AYUDA_TECLADO_SIMPLE = (
    "WASD mover    Espacio/Shift subir y bajar    Q/E giro\n"
    "ENTER = despegar o aterrizar    R = EMERGENCIA"
)


def normalize_key(keysym: str) -> str:
    return _ALIASES.get(keysym, keysym.lower())



def disable_button_keyboard_focus(widget: tk.Misc) -> None:
    """Reserva Espacio para el dron, no para los botones de Tkinter."""
    for child in widget.winfo_children():
        try:
            child.configure(takefocus=False)
        except tk.TclError:
            pass
        disable_button_keyboard_focus(child)


class DualStepKeysMixin:
    """Un paso por pulsación. El panel implementa `_key_step` y `_keys_enabled`."""

    pressed_keys: set[str]

    def _bind_flight_keys(self, *, emergency=None, close=None,
                          takeoff_land=None) -> None:
        if not hasattr(self, "pressed_keys"):
            self.pressed_keys = set()
        disable_button_keyboard_focus(self)
        for key in DUAL_KEYSYMS:
            self.bind_all(f"<KeyPress-{key}>", self._key_press)
            self.bind_all(f"<KeyRelease-{key}>", self._key_release)
        self.bind_all("<FocusOut>", lambda _event: self.pressed_keys.clear())
        self.bind_all("<ButtonRelease-1>", lambda _event: self.focus_set(), add="+")
        if emergency is not None:
            # El paro NO pasa por `_keys_enabled`: tiene que funcionar aunque
            # el panel esté ocupado en otra orden. Es el único que no espera.
            for key in EMERGENCY_KEYSYMS:
                self.bind_all(f"<KeyPress-{key}>", lambda _event: emergency())
        if takeoff_land is not None:
            for key in TAKEOFF_LAND_KEYSYMS:
                self.bind_all(f"<KeyPress-{key}>", self._make_step_action(takeoff_land))
        if close is not None:
            self.bind_all("<Control-c>", lambda _event: close())

    def _make_step_action(self, accion):
        """Envuelve una acción de una pulsación con la guarda del panel."""
        def manejar(_event: tk.Event) -> str:
            if self._keys_enabled():
                accion()
            return "break"
        return manejar

    def _keys_enabled(self) -> bool:
        return True

    def _key_step(self, slot: int, ux: int, uy: int, uz: int) -> None:
        raise NotImplementedError

    def _key_rotate(self, slot: int, uyaw: int) -> None:
        """Un paso de giro. Los paneles sin yaw no lo implementan."""

    def _key_press(self, event: tk.Event) -> str:
        key = normalize_key(event.keysym)
        if key in self.pressed_keys:
            return "break"
        self.pressed_keys.add(key)
        if not self._keys_enabled():
            return "break"
        direction = KEY_DIRECTIONS.get(key)
        if direction is not None:
            self._key_step(*direction)
            return "break"
        rotation = KEY_ROTATIONS.get(key)
        if rotation is not None:
            self._key_rotate(*rotation)
        return "break"

    def _key_release(self, event: tk.Event) -> str:
        self.pressed_keys.discard(normalize_key(event.keysym))
        return "break"

