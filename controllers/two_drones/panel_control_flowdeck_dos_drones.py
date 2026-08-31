"""Panel de teclado para dos Crazyflies con Flow deck, sin Robotat."""

from __future__ import annotations

import argparse
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

import cflib.crtp
from cflib.drivers.crazyradio import get_serials


PROJECT_DIR = Path(__file__).resolve().parents[2]
SHARED_DIR = PROJECT_DIR / "controllers" / "shared"
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))

from flowdeck_dual_backend import FlowDroneConfig, FlowDroneController
from gui_pdf_capture import auto_save_gui_pdf, install_gui_pdf_capture


KNOWN_RADIOS = ("2B1D933FCC", "9DD2507072")
DRONE_LINKS = ((84, "E7E7E7E7E4"), (90, "E7E7E7E7E5"))
SPEED_XY = 0.20
SPEED_Z = 0.12
KEY_DEADMAN_S = 0.80


def resolve_uris(uri1: str | None, uri2: str | None) -> tuple[str, str]:
    if uri1 and uri2:
        return uri1, uri2
    radios = [str(serial).upper() for serial in get_serials()]
    preferred = [serial for serial in KNOWN_RADIOS if serial in radios]
    if len(preferred) < 2:
        preferred.extend(serial for serial in radios if serial not in preferred)
    if len(preferred) < 2:
        raise RuntimeError("El control simultáneo necesita dos Crazyradio conectadas.")
    channel1, address1 = DRONE_LINKS[0]
    channel2, address2 = DRONE_LINKS[1]
    return (
        uri1 or f"radio://{preferred[0]}/{channel1}/2M/{address1}",
        uri2 or f"radio://{preferred[1]}/{channel2}/2M/{address2}",
    )


class DualKeyboardPanel(tk.Tk):
    def __init__(self, uri1: str, uri2: str) -> None:
        super().__init__()
        self.title("Dos drones · Flow deck · Control de teclado")
        self.geometry("940x760")
        self.resizable(False, False)
        self.closing = False
        self.close_deadline = 0.0
        self.pressed: set[str] = set()
        self.last_key_event = time.monotonic()
        self.states = [tk.StringVar(value="DESCONECTADO"), tk.StringVar(value="DESCONECTADO")]
        self.details = [tk.StringVar(value=uri1), tk.StringVar(value=uri2)]
        self.velocity = [tk.StringVar(value="vx=0.00 vy=0.00 vz=0.00") for _ in range(2)]
        self.controllers = [
            FlowDroneController(
                FlowDroneConfig("Dron 1", uri1),
                lambda state, message: self._controller_update(0, state, message),
            ),
            FlowDroneController(
                FlowDroneConfig("Dron 2", uri2),
                lambda state, message: self._controller_update(1, state, message),
            ),
        ]
        self._build()
        install_gui_pdf_capture(self, "gui_flowdeck_dos_drones")
        self._bind_keys()
        self.protocol("WM_DELETE_WINDOW", self.close_panel)
        self.after(50, self._keyboard_watchdog)

    def _build(self) -> None:
        ttk.Label(
            self, text="CONTROL DUAL CON FLOW DECK", font=("Segoe UI", 20, "bold")
        ).pack(pady=(18, 3))
        ttk.Label(self, text="Sin Robotat · cada dron utiliza una Crazyradio independiente").pack()

        cards = ttk.Frame(self)
        cards.pack(fill="x", padx=20, pady=15)
        for index in range(2):
            card = ttk.LabelFrame(cards, text=f" Dron {index + 1} ", padding=10)
            card.grid(row=0, column=index, padx=7, sticky="nsew")
            cards.columnconfigure(index, weight=1)
            ttk.Label(card, textvariable=self.states[index], font=("Segoe UI", 13, "bold")).pack()
            ttk.Label(card, textvariable=self.details[index], wraplength=400).pack(pady=5)
            ttk.Label(card, textvariable=self.velocity[index], font=("Consolas", 10)).pack()
            buttons = ttk.Frame(card)
            buttons.pack(pady=(8, 0))
            ttk.Button(
                buttons,
                text="DESPEGAR",
                takefocus=False,
                command=lambda i=index: self.takeoff((i,)),
            ).grid(row=0, column=0, padx=3)
            ttk.Button(
                buttons,
                text="ATERRIZAR",
                takefocus=False,
                command=lambda i=index: self.land((i,)),
            ).grid(row=0, column=1, padx=3)
            tk.Button(
                buttons,
                text="EMERGENCIA",
                bg="#b72f2a",
                fg="white",
                takefocus=False,
                command=lambda i=index: self.controllers[i].emergency_stop(),
            ).grid(row=0, column=2, padx=3)

        actions = ttk.Frame(self)
        actions.pack(pady=3)
        ttk.Button(actions, text="CONECTAR AMBOS", takefocus=False, command=self.connect_both).grid(
            row=0, column=0, padx=5
        )
        ttk.Button(
            actions, text="DESPEGAR AMBOS", takefocus=False, command=lambda: self.takeoff((0, 1))
        ).grid(row=0, column=1, padx=5)
        ttk.Button(
            actions, text="ATERRIZAR AMBOS", takefocus=False, command=lambda: self.land((0, 1))
        ).grid(row=0, column=2, padx=5)
        tk.Button(
            actions,
            text="EMERGENCIA AMBOS (Q)",
            bg="#941f1c",
            fg="white",
            takefocus=False,
            command=self.emergency_both,
        ).grid(row=0, column=3, padx=5)

        controls = ttk.Frame(self)
        controls.pack(fill="x", padx=20, pady=18)
        descriptions = (
            (
                "DRON 1",
                "W / S    Adelante / Atrás\nA / D    Izquierda / Derecha\nEspacio  Subir\nShift    Bajar",
            ),
            (
                "DRON 2",
                "↑ / ↓       Adelante / Atrás\n← / →       Izquierda / Derecha\nPage Up     Subir\nPage Down   Bajar",
            ),
        )
        for index, (title, body) in enumerate(descriptions):
            box = ttk.LabelFrame(controls, text=f" {title} ", padding=15)
            box.grid(row=0, column=index, padx=10, sticky="nsew")
            controls.columnconfigure(index, weight=1)
            ttk.Label(box, text=body, font=("Consolas", 12), justify="left").pack()

        ttk.Label(
            self,
            text=(
                "Puedes mover ambos simultáneamente manteniendo teclas de los dos grupos.\n"
                "Al soltar una tecla o perder el foco, ese dron vuelve a hover."
            ),
            justify="center",
        ).pack(pady=8)
        tk.Label(
            self,
            text="Q corta inmediatamente los motores de AMBOS drones.",
            fg="#a3221e",
            font=("Segoe UI", 11, "bold"),
        ).pack(pady=10)

    def _bind_keys(self) -> None:
        keys = ("w", "a", "s", "d", "space", "Shift_L", "Shift_R", "Up", "Down", "Left", "Right", "Prior", "Next")
        for key in keys:
            self.bind(f"<KeyPress-{key}>", self._key_press)
            self.bind(f"<KeyRelease-{key}>", self._key_release)
        self.bind("<KeyPress-q>", lambda _event: self.emergency_both())
        self.bind("<Control-c>", lambda _event: self.close_panel())
        self.bind("<FocusOut>", self._focus_lost)

    @staticmethod
    def _normal(keysym: str) -> str:
        aliases = {"Shift_L": "shift", "Shift_R": "shift", "Prior": "pageup", "Next": "pagedown"}
        return aliases.get(keysym, keysym.lower())

    def _key_press(self, event: tk.Event) -> str:
        self.last_key_event = time.monotonic()
        self.pressed.add(self._normal(event.keysym))
        self._send_velocities()
        return "break"

    def _key_release(self, event: tk.Event) -> str:
        self.last_key_event = time.monotonic()
        self.pressed.discard(self._normal(event.keysym))
        self._send_velocities()
        return "break"

    def _focus_lost(self, _event: tk.Event) -> None:
        if self.pressed:
            self.pressed.clear()
            self._send_velocities()

    def _requested(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        d1 = (
            SPEED_XY * (("w" in self.pressed) - ("s" in self.pressed)),
            SPEED_XY * (("a" in self.pressed) - ("d" in self.pressed)),
            SPEED_Z * (("space" in self.pressed) - ("shift" in self.pressed)),
        )
        d2 = (
            SPEED_XY * (("up" in self.pressed) - ("down" in self.pressed)),
            SPEED_XY * (("left" in self.pressed) - ("right" in self.pressed)),
            SPEED_Z * (("pageup" in self.pressed) - ("pagedown" in self.pressed)),
        )
        return d1, d2

    def _send_velocities(self) -> None:
        for index, values in enumerate(self._requested()):
            self.velocity[index].set(f"vx={values[0]:+.2f} vy={values[1]:+.2f} vz={values[2]:+.2f}")
            self.controllers[index].velocity(*values)

    def _keyboard_watchdog(self) -> None:
        if self.closing:
            return
        if self.pressed and time.monotonic() - self.last_key_event > KEY_DEADMAN_S:
            self.pressed.clear()
            self._send_velocities()
        self.after(50, self._keyboard_watchdog)

    def _controller_update(self, index: int, state: str, message: str) -> None:
        if not self.closing:
            self.after(0, self.states[index].set, state)
            self.after(0, self.details[index].set, message)

    def connect_both(self) -> None:
        for controller in self.controllers:
            controller.connect()

    def takeoff(self, indices: tuple[int, ...]) -> None:
        unavailable = [
            self.controllers[index].config.name
            for index in indices
            if not self.controllers[index].ready
        ]
        if unavailable:
            messagebox.showwarning(
                "Despegue bloqueado",
                "No están listos: " + ", ".join(unavailable) + ". Revisa su Flow deck.",
            )
            return
        if not messagebox.askokcancel("Confirmar despegue", "Despeja el área. ¿Continuar?"):
            return
        for index in indices:
            self.controllers[index].takeoff()

    def land(self, indices: tuple[int, ...]) -> None:
        self.pressed.clear()
        self._send_velocities()
        for index in indices:
            self.controllers[index].land()

    def emergency_both(self) -> None:
        for controller in self.controllers:
            controller.emergency_stop()

    def close_panel(self) -> None:
        if self.closing:
            return
        auto_save_gui_pdf(self)
        self.closing = True
        self.pressed.clear()
        for index, controller in enumerate(self.controllers):
            self.states[index].set("CERRANDO")
            controller.close()
        self.close_deadline = time.monotonic() + 10.0
        self.after(100, self._finish_close)

    def _finish_close(self) -> None:
        alive = any(c.thread is not None and c.thread.is_alive() for c in self.controllers)
        if not alive or time.monotonic() >= self.close_deadline:
            self.destroy()
        else:
            self.after(100, self._finish_close)


def main() -> int:
    parser = argparse.ArgumentParser(description="Panel dual con Flow deck")
    parser.add_argument("--uri1")
    parser.add_argument("--uri2")
    args = parser.parse_args()
    try:
        cflib.crtp.init_drivers(enable_debug_driver=False)
        uri1, uri2 = resolve_uris(args.uri1, args.uri2)
    except Exception as error:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("No se puede iniciar", str(error))
        root.destroy()
        return 1
    DualKeyboardPanel(uri1, uri2).mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
