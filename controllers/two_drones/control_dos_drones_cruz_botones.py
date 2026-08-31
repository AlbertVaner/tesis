r"""Interfaz Python por botones para comparar control high-level en dos drones.

La estrategia replica el principio usado por Cruz con Crazyswarm2: el firmware
recibe ``takeoff``, ``go_to`` y ``land`` y mantiene el objetivo. Robotat sigue
alimentando el EKF por posición externa y todas las protecciones viven en el
backend Python.

Primera prueba, sin hardware:
    python .\controllers\two_drones\control_dos_drones_cruz_botones.py --dry-run

Prueba real (PREFLIGHT no enciende motores):
    python .\controllers\two_drones\control_dos_drones_cruz_botones.py
"""

from __future__ import annotations

import argparse
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Callable


MODULE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = MODULE_DIR.parents[1]
SHARED_DIR = PROJECT_DIR / "controllers" / "shared"
for directory in (MODULE_DIR, SHARED_DIR):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from cruz_highlevel_backend import (
    DEFAULT_TOPIC_1,
    DEFAULT_TOPIC_2,
    DEFAULT_URI_1,
    DEFAULT_URI_2,
    HardwareBackend,
    SimulatedBackend,
)
from cruz_highlevel_protocol import Command
from gui_pdf_capture import auto_save_gui_pdf, install_gui_pdf_capture


STEP_XY_M = 0.10
STEP_Z_M = 0.08
REFRESH_MS = 150


class HighLevelButtonsApp(tk.Tk):
    def __init__(self, backend: Any, *, dry_run: bool) -> None:
        super().__init__()
        self.backend = backend
        self.dry_run = dry_run
        self.title("Dos Crazyflies — Python high-level")
        self.geometry("960x720")
        self.minsize(900, 660)
        self.protocol("WM_DELETE_WINDOW", self.close_window)
        self.bind_all("<KeyPress-q>", lambda _event: self.emergency())
        self.bind_all("<KeyPress-Q>", lambda _event: self.emergency())

        self.selected = tk.StringVar(value="drone1")
        self.summary = tk.StringVar(value="Ejecuta PREFLIGHT. Los motores permanecen apagados.")
        self.mode_text = tk.StringVar(value="MODO SIMULADO" if dry_run else "MODO HARDWARE")
        self.event_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.action_lock = threading.Lock()
        self.pressed_keys: set[str] = set()
        self.busy = False
        self.closing = False
        self.latest_snapshot = backend.snapshot()
        enabled_keys = [key for key in ("drone1", "drone2") if self.latest_snapshot[key].get("enabled", True)]
        if len(enabled_keys) == 1:
            self.selected.set(enabled_keys[0])
        self.move_buttons: list[ttk.Button] = []
        self._build()
        install_gui_pdf_capture(self, "gui_control_cruz_dos_drones")
        self._disable_button_keyboard_focus(self)
        self._bind_flight_keys()
        self.focus_set()
        if len(enabled_keys) == 1:
            self.takeoff_both_button.configure(text="2  DESPEGAR DRON ACTIVO")
            self.land_both_button.configure(text="ATERRIZAR DRON ACTIVO")
        self.after(REFRESH_MS, self.refresh)

    def _bind_flight_keys(self) -> None:
        """Añade el esquema dual del panel Flow deck sin repetir por autorepeat."""
        keys = ("w", "a", "s", "d", "space", "Shift_L", "Shift_R", "Up", "Down", "Left", "Right", "Prior", "Next")
        for key in keys:
            self.bind_all(f"<KeyPress-{key}>", self._key_press)
            self.bind_all(f"<KeyRelease-{key}>", self._key_release)
        self.bind_all("<FocusOut>", lambda _event: self.pressed_keys.clear())
        self.bind_all("<ButtonRelease-1>", lambda _event: self.focus_set(), add="+")

    def _disable_button_keyboard_focus(self, widget: tk.Misc) -> None:
        """Evita que Espacio active un botón en lugar de controlar altura."""
        for child in widget.winfo_children():
            try:
                child.configure(takefocus=False)
            except tk.TclError:
                pass
            self._disable_button_keyboard_focus(child)

    @staticmethod
    def _normalize_key(keysym: str) -> str:
        aliases = {"Shift_L": "shift", "Shift_R": "shift", "Prior": "pageup", "Next": "pagedown"}
        return aliases.get(keysym, keysym.lower())

    def _key_press(self, event: tk.Event) -> str:
        key = self._normalize_key(event.keysym)
        if key in self.pressed_keys:
            return "break"
        self.pressed_keys.add(key)
        if self.busy:
            return "break"
        mapping = {
            "w": ("drone1", STEP_XY_M, 0.0, 0.0),
            "s": ("drone1", -STEP_XY_M, 0.0, 0.0),
            "a": ("drone1", 0.0, STEP_XY_M, 0.0),
            "d": ("drone1", 0.0, -STEP_XY_M, 0.0),
            "space": ("drone1", 0.0, 0.0, STEP_Z_M),
            "shift": ("drone1", 0.0, 0.0, -STEP_Z_M),
            "up": ("drone2", STEP_XY_M, 0.0, 0.0),
            "down": ("drone2", -STEP_XY_M, 0.0, 0.0),
            "left": ("drone2", 0.0, STEP_XY_M, 0.0),
            "right": ("drone2", 0.0, -STEP_XY_M, 0.0),
            "pageup": ("drone2", 0.0, 0.0, STEP_Z_M),
            "pagedown": ("drone2", 0.0, 0.0, -STEP_Z_M),
        }
        command = mapping.get(key)
        if command is not None:
            self.move_target(*command)
        return "break"

    def _key_release(self, event: tk.Event) -> str:
        self.pressed_keys.discard(self._normalize_key(event.keysym))
        return "break"

    def _build(self) -> None:
        style = ttk.Style(self)
        style.configure("Title.TLabel", font=("Segoe UI", 19, "bold"))
        style.configure("Subtitle.TLabel", font=("Segoe UI", 10))
        style.configure("Card.TLabelframe", padding=10)
        style.configure("Danger.TButton", font=("Segoe UI", 10, "bold"))

        root = ttk.Frame(self, padding=14)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)

        heading = ttk.Frame(root)
        heading.grid(row=0, column=0, sticky="ew")
        heading.columnconfigure(0, weight=1)
        ttk.Label(heading, text="CONTROL HIGH-LEVEL DE DOS CRAZYFLIES", style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            heading,
            text="Comparación Python: takeoff / go_to / land del firmware + extpos de Robotat",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="w")
        mode = tk.Label(
            heading,
            textvariable=self.mode_text,
            bg="#174d2a" if not self.dry_run else "#5c4b15",
            fg="white",
            padx=12,
            pady=7,
            font=("Segoe UI", 10, "bold"),
        )
        mode.grid(row=0, column=1, rowspan=2, padx=(10, 0))

        safety = ttk.Frame(root, padding=(0, 14, 0, 8))
        safety.grid(row=1, column=0, sticky="ew")
        for column in range(4):
            safety.columnconfigure(column, weight=1)
        self.preflight_button = ttk.Button(safety, text="1  PREFLIGHT (SIN MOTORES)", command=self.preflight)
        self.preflight_button.grid(row=0, column=0, padx=4, sticky="ew")
        self.takeoff_both_button = tk.Button(
            safety,
            text="2  DESPEGAR AMBOS",
            command=lambda: self.takeoff("both"),
            bg="#2f8a3a",
            fg="white",
            activebackground="#246e2e",
            font=("Segoe UI", 10, "bold"),
            state="disabled",
        )
        self.takeoff_both_button.grid(row=0, column=1, padx=4, sticky="ew")
        self.land_both_button = ttk.Button(
            safety, text="ATERRIZAR AMBOS", command=lambda: self.land("both"), state="disabled"
        )
        self.land_both_button.grid(row=0, column=2, padx=4, sticky="ew")
        self.emergency_button = tk.Button(
            safety,
            text="EMERGENCIA — MOTORES OFF",
            command=self.emergency,
            bg="#b31e1e",
            fg="white",
            activebackground="#8f1717",
            font=("Segoe UI", 10, "bold"),
        )
        self.emergency_button.grid(row=0, column=3, padx=4, sticky="ew")

        cards = ttk.Frame(root)
        cards.grid(row=2, column=0, sticky="nsew")
        cards.columnconfigure(0, weight=1)
        cards.columnconfigure(1, weight=1)
        root.rowconfigure(2, weight=1)
        self.unit_labels: dict[str, dict[str, tk.StringVar]] = {}
        self.unit_buttons: dict[str, dict[str, ttk.Button]] = {}
        for column, key in enumerate(("drone1", "drone2")):
            name = "Dron 1" if key == "drone1" else "Dron 2"
            card = ttk.LabelFrame(cards, text=f" {name} ", style="Card.TLabelframe")
            card.grid(row=0, column=column, padx=6, pady=4, sticky="nsew")
            card.columnconfigure(0, weight=1)
            values = {
                "status": tk.StringVar(value="Sin preflight"),
                "pose": tk.StringVar(value="Posición: —"),
                "target": tk.StringVar(value="Objetivo: —"),
                "battery": tk.StringVar(value="Batería: —"),
                "mocap": tk.StringVar(value="MoCap: —"),
                "ekf": tk.StringVar(value="EKF–MoCap: —"),
            }
            self.unit_labels[key] = values
            ttk.Radiobutton(card, text="Controlar este dron", variable=self.selected, value=key).grid(
                row=0, column=0, sticky="w", pady=(0, 7)
            )
            ttk.Label(card, textvariable=values["status"], font=("Segoe UI", 10, "bold"), wraplength=390).grid(
                row=1, column=0, sticky="w"
            )
            for row, field in enumerate(("pose", "target", "battery", "mocap", "ekf"), start=2):
                ttk.Label(card, textvariable=values[field]).grid(row=row, column=0, sticky="w", pady=1)
            buttons = ttk.Frame(card)
            buttons.grid(row=7, column=0, sticky="ew", pady=(10, 0))
            buttons.columnconfigure((0, 1), weight=1)
            takeoff = ttk.Button(
                buttons, text="DESPEGAR", command=lambda selected=key: self.takeoff(selected), state="disabled"
            )
            takeoff.grid(row=0, column=0, padx=(0, 3), sticky="ew")
            land = ttk.Button(
                buttons, text="ATERRIZAR", command=lambda selected=key: self.land(selected), state="disabled"
            )
            land.grid(row=0, column=1, padx=(3, 0), sticky="ew")
            self.unit_buttons[key] = {"takeoff": takeoff, "land": land}

        movement = ttk.LabelFrame(root, text=" Movimiento del dron seleccionado — XY: 10 cm; Z: 8 cm ", padding=8)
        movement.grid(row=3, column=0, sticky="ew", pady=(10, 4))
        for column in range(6):
            movement.columnconfigure(column, weight=1)
        self._move_button(movement, "↑ ADELANTE", 0, 1, STEP_XY_M, 0.0, 0.0)
        self._move_button(movement, "← IZQUIERDA", 1, 0, 0.0, STEP_XY_M, 0.0)
        self._move_button(movement, "DERECHA →", 1, 2, 0.0, -STEP_XY_M, 0.0)
        self._move_button(movement, "↓ ATRÁS", 2, 1, -STEP_XY_M, 0.0, 0.0)
        self._move_button(movement, "SUBIR", 0, 3, 0.0, 0.0, STEP_Z_M)
        self._move_button(movement, "BAJAR", 2, 3, 0.0, 0.0, -STEP_Z_M)
        both_selector = ttk.Radiobutton(
            movement, text="Controlar ambos", variable=self.selected, value="both"
        )
        both_selector.grid(row=1, column=4, padx=10, sticky="w")
        if len([key for key in ("drone1", "drone2") if self.latest_snapshot[key].get("enabled", True)]) < 2:
            both_selector.configure(state="disabled")
        ttk.Label(
            movement,
            text="D1: WASD + Espacio/Shift\nD2: flechas + PageUp/PageDown\nQ = EMERGENCIA",
            justify="left",
        ).grid(row=0, column=5, rowspan=3, padx=12, sticky="w")

        ttk.Label(root, textvariable=self.summary, anchor="center", wraplength=900).grid(
            row=4, column=0, sticky="ew", pady=(7, 4)
        )
        log_frame = ttk.LabelFrame(root, text=" Eventos ", padding=5)
        log_frame.grid(row=5, column=0, sticky="ew")
        self.log_list = tk.Listbox(log_frame, height=6, font=("Consolas", 9))
        self.log_list.pack(fill="both", expand=True)
        self.log("Interfaz iniciada. PREFLIGHT no activa motores.")

    def _move_button(
        self, parent: ttk.LabelFrame, text: str, row: int, column: int, dx: float, dy: float, dz: float
    ) -> None:
        button = ttk.Button(
            parent,
            text=text,
            command=lambda: self.move(dx, dy, dz),
            state="disabled",
        )
        button.grid(row=row, column=column, padx=4, pady=3, sticky="ew")
        self.move_buttons.append(button)

    def emit(self, ok: bool, event: str, message: str, snapshot: dict[str, Any] | None) -> None:
        self.event_queue.put(("event", (ok, event, message, snapshot)))

    def run_action(self, description: str, operation: Callable[[], None]) -> None:
        if self.busy:
            messagebox.showinfo("Operación en curso", "Espera a que termine la operación actual.")
            return
        self.busy = True
        self.log(f"→ {description}")
        self._update_buttons()

        def worker() -> None:
            try:
                with self.action_lock:
                    operation()
                self.event_queue.put(("done", (True, description)))
            except Exception as exc:
                self.event_queue.put(("done", (False, str(exc))))

        threading.Thread(target=worker, name=f"GUI-{description}", daemon=True).start()

    def preflight(self) -> None:
        self.run_action("PREFLIGHT", lambda: self.backend.connect(self.emit))

    def takeoff(self, target: str) -> None:
        self.run_action(f"TAKEOFF {target}", lambda: self.backend.takeoff(Command("takeoff", target)))

    def move(self, dx: float, dy: float, dz: float) -> None:
        self.move_target(self.selected.get(), dx, dy, dz)

    def move_target(self, target: str, dx: float, dy: float, dz: float) -> None:
        """Mueve un objetivo concreto; se usa por botones y por teclado dual."""
        self.run_action(
            f"GO_TO {target}: dx={dx:+.2f}, dy={dy:+.2f}, dz={dz:+.2f}",
            lambda: self.backend.move(Command("move", target, dx, dy, dz)),
        )

    def land(self, target: str) -> None:
        self.run_action(f"LAND {target}", lambda: self.backend.land(Command("land", target)))

    def emergency(self) -> None:
        if self.latest_snapshot.get("emergency"):
            return
        self.log("→ EMERGENCIA")

        def worker() -> None:
            self.backend.emergency()
            self.event_queue.put(("done", (True, "EMERGENCIA enviada")))

        threading.Thread(target=worker, name="GUI-Emergency", daemon=True).start()

    def refresh(self) -> None:
        if self.closing:
            return
        while True:
            try:
                kind, payload = self.event_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "event":
                ok, event, message, snapshot = payload
                if event != "status":
                    self.log(f"{'✓' if ok else '✗'} {message}")
                if snapshot is not None:
                    self.latest_snapshot = snapshot
            elif kind == "done":
                ok, message = payload
                self.busy = False
                self.log(f"{'✓' if ok else '✗'} {message}")
                if not ok:
                    messagebox.showwarning("Comando bloqueado", message)
        try:
            self.latest_snapshot = self.backend.snapshot()
            self._render_snapshot(self.latest_snapshot)
        except Exception as exc:
            self.summary.set(f"Error leyendo backend: {exc}")
        self.after(REFRESH_MS, self.refresh)

    def _render_snapshot(self, snapshot: dict[str, Any]) -> None:
        for key in ("drone1", "drone2"):
            unit = snapshot[key]
            values = self.unit_labels[key]
            values["status"].set(str(unit["status"]))
            values["pose"].set(f"Posición: {self._vector(unit.get('pose'))}")
            values["target"].set(f"Objetivo: {self._vector(unit.get('target'))}")
            voltage = self._number(unit.get("battery_v"), " V", 2)
            level = "—" if unit.get("battery_level_pct") is None else f"{unit['battery_level_pct']}%"
            values["battery"].set(f"Batería: {voltage} · {level}")
            values["mocap"].set(f"MoCap: {self._number(unit.get('mocap_age_s'), ' s', 3)}")
            values["ekf"].set(f"EKF–MoCap: {self._number(unit.get('ekf_mocap_error_m'), ' m', 3)}")
        separation = self._number(snapshot.get("separation_m"), " m", 2)
        if snapshot["emergency"]:
            reason = snapshot.get("emergency_reason") or "motivo no informado"
            self.summary.set(f"EMERGENCIA: {reason} — reinicia el programa.")
        elif snapshot["ready"]:
            self.summary.set(f"PREFLIGHT correcto · separación {separation} · high-level listo")
        elif self.busy:
            self.summary.set("Operación en curso; observa los eventos y no despejes el área.")
        else:
            self.summary.set("Sin preflight: motores apagados.")
        self._update_buttons()

    def _update_buttons(self) -> None:
        snapshot = self.latest_snapshot
        ready = bool(snapshot.get("ready")) and not bool(snapshot.get("emergency"))
        airborne = {key: bool(snapshot[key].get("airborne")) for key in ("drone1", "drone2")}
        enabled = {key: bool(snapshot[key].get("enabled", True)) for key in ("drone1", "drone2")}
        any_airborne = any(airborne.values())
        self.preflight_button.configure(
            state="normal" if not self.busy and not ready and not snapshot.get("emergency") else "disabled"
        )
        self.takeoff_both_button.configure(
            state="normal" if ready and not any_airborne and not self.busy else "disabled"
        )
        self.land_both_button.configure(
            state="normal" if any_airborne and not self.busy and not snapshot.get("emergency") else "disabled"
        )
        for key in ("drone1", "drone2"):
            self.unit_buttons[key]["takeoff"].configure(
                state="normal" if enabled[key] and ready and not airborne[key] and not self.busy else "disabled"
            )
            self.unit_buttons[key]["land"].configure(
                state="normal" if enabled[key] and airborne[key] and not self.busy else "disabled"
            )
        selected = self.selected.get()
        selected_airborne = (
            all(airborne[key] for key in ("drone1", "drone2") if enabled[key])
            if selected == "both"
            else airborne.get(selected, False)
        )
        for button in self.move_buttons:
            button.configure(state="normal" if ready and selected_airborne and not self.busy else "disabled")

    def log(self, message: str) -> None:
        self.log_list.insert("end", message)
        if self.log_list.size() > 100:
            self.log_list.delete(0)
        self.log_list.see("end")

    def close_window(self) -> None:
        if self.closing:
            return
        snapshot = self.backend.snapshot()
        airborne = bool(snapshot["drone1"]["airborne"] or snapshot["drone2"]["airborne"])
        if airborne:
            choice = messagebox.askyesnocancel(
                "Cierre seguro",
                "Hay drones en vuelo.\n\nSí: aterrizar y cerrar.\nNo: emergencia y cerrar.\nCancelar: volver.",
                icon="warning",
            )
            if choice is None:
                return
            if choice is False:
                self.backend.emergency()
        auto_save_gui_pdf(self)
        self.closing = True
        self.summary.set("Cerrando backend de forma segura...")
        self._disable_all()

        def worker() -> None:
            try:
                with self.action_lock:
                    self.backend.close()
            finally:
                self.after(0, self.destroy)

        threading.Thread(target=worker, name="GUI-Close", daemon=True).start()

    def _disable_all(self) -> None:
        for button in (
            self.preflight_button,
            self.takeoff_both_button,
            self.land_both_button,
            *self.move_buttons,
            *(item for buttons in self.unit_buttons.values() for item in buttons.values()),
        ):
            button.configure(state="disabled")

    @staticmethod
    def _vector(value: Any) -> str:
        if value is None:
            return "—"
        return f"({value[0]:+.2f}, {value[1]:+.2f}, {value[2]:+.2f}) m"

    @staticmethod
    def _number(value: Any, suffix: str, digits: int) -> str:
        if value is None:
            return "—"
        return f"{value:.{digits}f}{suffix}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Control Python por botones, high-level, para dos Crazyflies")
    parser.add_argument("--uri1", default=DEFAULT_URI_1)
    parser.add_argument("--uri2", default=DEFAULT_URI_2)
    parser.add_argument("--topic1", default=DEFAULT_TOPIC_1)
    parser.add_argument("--topic2", default=DEFAULT_TOPIC_2)
    parser.add_argument("--single", choices=("drone1", "drone2"), help="habilita solamente un dron")
    parser.add_argument("--dry-run", action="store_true", help="simula Robotat y radios; nunca activa motores")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        backend = SimulatedBackend(args.single) if args.dry_run else HardwareBackend(args)
    except Exception as exc:
        print(f"No se pudo iniciar el backend: {exc}", file=sys.stderr)
        return 2
    app = HighLevelButtonsApp(backend, dry_run=args.dry_run)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
