"""Esquema de teclado común de los paneles Tkinter.

Dron 1: W/A/S/D adelante/izquierda/atrás/derecha, Espacio sube, Shift baja.
Dron 2: flechas, Re Pág sube, Av Pág baja.

`DualStepKeysMixin`: cada pulsación pide **un paso** (botones high-level).
Sin autorepeat: la tecla debe soltarse antes de repetir. El mixin no conoce
pasos ni velocidades: entrega direcciones unitarias y el panel las escala con
sus propias constantes. (`HeldKeysMixin`, la velocidad sostenida de los paneles
Flow Deck, se eliminó con esos paneles en septiembre de 2026.)
"""

from __future__ import annotations

import tkinter as tk

DUAL_KEYSYMS = (
    "w", "a", "s", "d", "space", "Shift_L", "Shift_R",
    "Up", "Down", "Left", "Right", "Prior", "Next",
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

    def _bind_flight_keys(self, *, emergency=None, close=None) -> None:
        if not hasattr(self, "pressed_keys"):
            self.pressed_keys = set()
        disable_button_keyboard_focus(self)
        for key in DUAL_KEYSYMS:
            self.bind_all(f"<KeyPress-{key}>", self._key_press)
            self.bind_all(f"<KeyRelease-{key}>", self._key_release)
        self.bind_all("<FocusOut>", lambda _event: self.pressed_keys.clear())
        self.bind_all("<ButtonRelease-1>", lambda _event: self.focus_set(), add="+")
        if emergency is not None:
            self.bind_all("<KeyPress-q>", lambda _event: emergency())
            self.bind_all("<KeyPress-Q>", lambda _event: emergency())
        if close is not None:
            self.bind_all("<Control-c>", lambda _event: close())

    def _keys_enabled(self) -> bool:
        return True

    def _key_step(self, slot: int, ux: int, uy: int, uz: int) -> None:
        raise NotImplementedError

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

    def _key_release(self, event: tk.Event) -> str:
        self.pressed_keys.discard(normalize_key(event.keysym))
        return "break"

