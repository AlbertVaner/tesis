"""Panel de control tipo videojuego para el Dron 1 con Flow deck v2.

Controles (la ventana debe tener el foco):
    W/S: adelante/atras       A/D: izquierda/derecha
    Espacio: subir            Shift: bajar
    Q: corte inmediato de motores

No usa Robotat ni posicion externa.
"""

from __future__ import annotations

import argparse
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

import cflib.crtp
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie
from cflib.positioning.motion_commander import MotionCommander


PROJECT_DIR = Path(__file__).resolve().parents[3]
SHARED_DIR = PROJECT_DIR / "controllers" / "shared"
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))

from hover_flowdeck_dron1 import (
    DEFAULT_HEIGHT_M,
    arm_if_supported,
    emergency_stop_motion_commander,
    require_flow_deck,
    reset_and_wait_for_estimator,
    select_uri,
)
from gui_pdf_capture import auto_save_gui_pdf, install_gui_pdf_capture


SPEED_XY_M_S = 0.25
SPEED_Z_M_S = 0.12
KEY_DEADMAN_S = 0.8


class FlowDeckPanel(tk.Tk):
    def __init__(self, uri: str) -> None:
        super().__init__()
        self.uri = uri
        self.title("Dron 1 · Control con Flow deck")
        self.geometry("760x700")
        self.resizable(False, False)

        self.commands: queue.Queue[tuple[str, object | None]] = queue.Queue()
        self.stop_worker = threading.Event()
        self.emergency_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.pressed: set[str] = set()
        self.last_key_event = time.monotonic()
        self.connected = False
        self.flying = False
        self.busy = False
        self.closing = False
        self.close_deadline = 0.0

        self.status = tk.StringVar(value="Conecta y valida el Dron 1. Los motores permanecen apagados.")
        self.flight_state = tk.StringVar(value="DESCONECTADO")
        self.velocity = tk.StringVar(value="vx=+0.00  vy=+0.00  vz=+0.00 m/s")
        self.key_state = tk.StringVar(value="Ninguna tecla activa")

        self._build()
        install_gui_pdf_capture(self, "gui_flowdeck_dron1")
        self._bind_keys()
        self.protocol("WM_DELETE_WINDOW", self.close_panel)
        self.after(100, self._refresh_focus)

    def _build(self) -> None:
        style = ttk.Style(self)
        style.configure("Title.TLabel", font=("Segoe UI", 19, "bold"))
        style.configure("State.TLabel", font=("Segoe UI", 13, "bold"))

        ttk.Label(self, text="CONTROL DEL DRON 1 · FLOW DECK", style="Title.TLabel").pack(
            pady=(18, 3)
        )
        ttk.Label(
            self,
            text="Control relativo sin Robotat · La ventana debe permanecer seleccionada",
        ).pack()

        config = ttk.LabelFrame(self, text=" Configuración ", padding=10)
        config.pack(fill="x", padx=24, pady=14)
        ttk.Label(config, text=f"Radio: {self.uri}").pack(anchor="w")
        ttk.Label(config, text="Dron: canal 84 · dirección E7E7E7E7E4").pack(anchor="w")

        actions = ttk.Frame(self)
        actions.pack(pady=5)
        ttk.Button(
            actions, text="CONECTAR Y VALIDAR", command=self.connect_drone, takefocus=False
        ).grid(
            row=0, column=0, padx=5
        )
        ttk.Button(actions, text="DESPEGAR", command=self.takeoff, takefocus=False).grid(
            row=0, column=1, padx=5
        )
        ttk.Button(actions, text="ATERRIZAR", command=self.land, takefocus=False).grid(
            row=0, column=2, padx=5
        )
        tk.Button(
            actions,
            text="EMERGENCIA (Q)",
            bg="#b72f2a",
            fg="white",
            activebackground="#8e211e",
            activeforeground="white",
            command=self.emergency,
            takefocus=False,
        ).grid(row=0, column=3, padx=5)

        ttk.Label(self, textvariable=self.flight_state, style="State.TLabel").pack(pady=(15, 5))

        keyboard = ttk.LabelFrame(self, text=" Controles de movimiento ", padding=12)
        keyboard.pack(padx=24, pady=5)
        self.key_labels: dict[str, tk.Label] = {}

        self._key(keyboard, "W", "W\nADELANTE", 0, 1)
        self._key(keyboard, "A", "A\nIZQUIERDA", 1, 0)
        self._key(keyboard, "S", "S\nATRÁS", 1, 1)
        self._key(keyboard, "D", "D\nDERECHA", 1, 2)
        self._key(keyboard, "SPACE", "ESPACIO\nSUBIR", 0, 3, width=14)
        self._key(keyboard, "SHIFT", "SHIFT\nBAJAR", 1, 3, width=14)

        info = ttk.LabelFrame(self, text=" Comando en vivo ", padding=12)
        info.pack(fill="x", padx=24, pady=18)
        ttk.Label(info, textvariable=self.velocity, font=("Consolas", 12)).pack(anchor="w")
        ttk.Label(info, textvariable=self.key_state).pack(anchor="w", pady=(5, 0))

        ttk.Label(
            self,
            text=(
                f"Velocidad horizontal: {SPEED_XY_M_S:.2f} m/s · "
                f"vertical: {SPEED_Z_M_S:.2f} m/s\n"
                "Al soltar las teclas el dron vuelve a hover."
            ),
            justify="center",
        ).pack()

        tk.Label(
            self,
            text="Q CORTA LOS MOTORES: el dron caerá. Úsala solo en una emergencia.",
            fg="#a3221e",
            font=("Segoe UI", 10, "bold"),
        ).pack(pady=(15, 7))
        ttk.Label(
            self,
            textvariable=self.status,
            wraplength=700,
            justify="center",
        ).pack(padx=20, pady=8)

    def _key(
        self, parent: ttk.LabelFrame, name: str, text: str, row: int, column: int, width: int = 12
    ) -> None:
        label = tk.Label(
            parent,
            text=text,
            width=width,
            height=3,
            relief="raised",
            bg="#e7ece9",
            font=("Segoe UI", 10, "bold"),
        )
        label.grid(row=row, column=column, padx=7, pady=7)
        self.key_labels[name] = label

    def _bind_keys(self) -> None:
        for key in ("w", "a", "s", "d"):
            self.bind(f"<KeyPress-{key}>", self._key_press)
            self.bind(f"<KeyRelease-{key}>", self._key_release)
        self.bind("<KeyPress-space>", self._key_press)
        self.bind("<KeyRelease-space>", self._key_release)
        self.bind("<KeyPress-Shift_L>", self._key_press)
        self.bind("<KeyRelease-Shift_L>", self._key_release)
        self.bind("<KeyPress-Shift_R>", self._key_press)
        self.bind("<KeyRelease-Shift_R>", self._key_release)
        self.bind("<KeyPress-q>", lambda _event: self.emergency())
        self.bind("<Control-c>", lambda _event: self.close_panel())
        self.bind("<FocusOut>", self._focus_lost)

    @staticmethod
    def _normalize_key(keysym: str) -> str | None:
        key = keysym.lower()
        if key in {"w", "a", "s", "d"}:
            return key
        if key == "space":
            return "space"
        if key in {"shift_l", "shift_r"}:
            return "shift"
        return None

    def _key_press(self, event: tk.Event) -> str:
        key = self._normalize_key(event.keysym)
        self.last_key_event = time.monotonic()
        if key is not None:
            if key not in self.pressed:
                self.pressed.add(key)
            # Los KeyPress repetidos funcionan como señal de vida al dron.
            self._send_velocity()
        # Evita que Espacio active accidentalmente un botón de Tkinter.
        return "break"

    def _key_release(self, event: tk.Event) -> str:
        key = self._normalize_key(event.keysym)
        self.last_key_event = time.monotonic()
        if key is not None and key in self.pressed:
            self.pressed.discard(key)
            self._send_velocity()
        return "break"

    def _focus_lost(self, _event: tk.Event) -> None:
        if self.pressed:
            self.pressed.clear()
            self._send_velocity()

    def _desired_velocity(self) -> tuple[float, float, float]:
        vx = SPEED_XY_M_S * (("w" in self.pressed) - ("s" in self.pressed))
        vy = SPEED_XY_M_S * (("a" in self.pressed) - ("d" in self.pressed))
        vz = SPEED_Z_M_S * (("space" in self.pressed) - ("shift" in self.pressed))
        return vx, vy, vz

    def _send_velocity(self) -> None:
        vx, vy, vz = self._desired_velocity()
        self.velocity.set(f"vx={vx:+.2f}  vy={vy:+.2f}  vz={vz:+.2f} m/s")
        active = ", ".join(sorted(key.upper() for key in self.pressed))
        self.key_state.set(f"Teclas activas: {active}" if active else "Ninguna tecla activa")
        for name, label in self.key_labels.items():
            lookup = {"SPACE": "space", "SHIFT": "shift"}.get(name, name.lower())
            label.configure(bg="#80c978" if lookup in self.pressed else "#e7ece9")
        if self.flying:
            self.commands.put(("velocity", (vx, vy, vz)))

    def connect_drone(self) -> None:
        if self.connected or self.busy:
            return
        self.busy = True
        self.status.set("Conectando, comprobando Flow deck y estabilizando Kalman...")
        self.flight_state.set("VALIDANDO")
        # El cierre normal espera este hilo; daemon evita dejar Python colgado si
        # un driver USB deja de responder durante la desconexion.
        self.worker = threading.Thread(target=self._flight_worker, daemon=True)
        self.worker.start()

    def takeoff(self) -> None:
        if not self.connected or self.busy or self.flying:
            messagebox.showwarning("Despegue bloqueado", "Primero conecta y valida el dron.")
            return
        if not messagebox.askokcancel(
            "Confirmar despegue",
            "Despeja el área y aléjate de las hélices.\n\n¿Despegar a 35 cm?",
        ):
            return
        self.busy = True
        self.commands.put(("takeoff", None))
        self.status.set("Despegando...")

    def land(self) -> None:
        if not self.flying:
            return
        self.pressed.clear()
        self._send_velocity()
        self.busy = True
        self.commands.put(("land", None))
        self.status.set("Aterrizando...")

    def emergency(self) -> None:
        if self.emergency_event.is_set():
            return
        self.emergency_event.set()
        self.pressed.clear()
        self._send_velocity()
        self.flight_state.set("EMERGENCIA")
        self.status.set("PARADA DE EMERGENCIA: cortando motores...")

    def _ui(self, callback, *args) -> None:
        if not self.closing:
            self.after(0, callback, *args)

    def _set_ready(self) -> None:
        self.connected = True
        self.busy = False
        self.flight_state.set("LISTO · MOTORES APAGADOS")
        self.status.set("Flow deck detectado y estimador estable. Ya puedes despegar.")

    def _set_flying(self, value: bool) -> None:
        self.flying = value
        self.busy = False
        self.flight_state.set("VOLANDO · CONTROL WASD" if value else "EN TIERRA")
        self.status.set(
            "Mantén una tecla para moverte; suéltala para hover."
            if value
            else "Aterrizaje completado."
        )

    def _set_error(self, text: str) -> None:
        self.connected = False
        self.flying = False
        self.busy = False
        self.flight_state.set("ERROR")
        self.status.set(text)

    def _flight_worker(self) -> None:
        commander: MotionCommander | None = None
        emergency = False
        motion_active = False
        last_motion_command = time.monotonic()
        try:
            with SyncCrazyflie(self.uri, cf=Crazyflie(rw_cache="./cache_flowdeck_panel")) as scf:
                require_flow_deck(scf.cf)
                reset_and_wait_for_estimator(scf.cf)
                self._ui(self._set_ready)

                while not self.stop_worker.is_set():
                    if self.emergency_event.is_set():
                        emergency = True
                        emergency_stop_motion_commander(commander, scf.cf)
                        commander = None
                        self._ui(self._set_error, "Motores detenidos por Q. Revisa el dron antes de reconectar.")
                        break
                    try:
                        command, payload = self.commands.get(timeout=0.05)
                    except queue.Empty:
                        if (
                            commander is not None
                            and motion_active
                            and time.monotonic() - last_motion_command > KEY_DEADMAN_S
                        ):
                            commander.stop()
                            motion_active = False
                        continue

                    if command == "takeoff":
                        arm_if_supported(scf.cf)
                        commander = MotionCommander(scf, default_height=DEFAULT_HEIGHT_M)
                        commander.take_off()
                        commander.stop()
                        self._ui(self._set_flying, True)
                    elif command == "velocity" and commander is not None:
                        vx, vy, vz = payload  # type: ignore[misc]
                        commander.start_linear_motion(vx, vy, vz)
                        motion_active = any(abs(value) > 1e-6 for value in (vx, vy, vz))
                        last_motion_command = time.monotonic()
                    elif command == "land" and commander is not None:
                        commander.stop()
                        motion_active = False
                        commander.land()
                        commander = None
                        self._ui(self._set_flying, False)
                    elif command == "close":
                        if commander is not None:
                            commander.stop()
                            motion_active = False
                            commander.land()
                            commander = None
                        break
        except Exception as error:
            self._ui(self._set_error, f"Operación bloqueada: {error}")
        finally:
            if commander is not None and not emergency:
                try:
                    commander.stop()
                    commander.land()
                except Exception:
                    pass

    def _refresh_focus(self) -> None:
        if self.closing:
            return
        # Si se pierde un KeyRelease, nunca conserva una velocidad para siempre.
        if self.pressed and time.monotonic() - self.last_key_event > KEY_DEADMAN_S:
            self.pressed.clear()
            self._send_velocity()
            self.status.set("Protección de teclado: movimiento detenido; vuelve a pulsar la tecla.")
        self.after(50, self._refresh_focus)

    def close_panel(self) -> None:
        if self.closing:
            return
        auto_save_gui_pdf(self)
        self.closing = True
        self.pressed.clear()
        self.velocity.set("vx=+0.00  vy=+0.00  vz=+0.00 m/s")
        self.key_state.set("Cerrando control...")
        self.flight_state.set("CERRANDO")
        self.status.set("Deteniendo movimiento, aterrizando y cerrando la radio...")
        self.commands.put(("close", None))
        self.close_deadline = time.monotonic() + 8.0
        self.after(100, self._finish_close)

    def _finish_close(self) -> None:
        """Cierra la ventana cuando acaba la radio, sin bloquear Tkinter."""
        worker_done = self.worker is None or not self.worker.is_alive()
        if worker_done or time.monotonic() >= self.close_deadline:
            self.stop_worker.set()
            self.destroy()
            return
        self.after(100, self._finish_close)


def main() -> int:
    parser = argparse.ArgumentParser(description="Panel WASD del Dron 1 con Flow deck")
    parser.add_argument("--radio", help="serial de la Crazyradio que se desea utilizar")
    parser.add_argument("--uri", help="URI completa; tiene prioridad sobre --radio")
    args = parser.parse_args()

    try:
        cflib.crtp.init_drivers(enable_debug_driver=False)
        uri = select_uri(args.uri, args.radio)
    except Exception as error:
        messagebox.showerror("No se puede iniciar", str(error))
        return 1

    FlowDeckPanel(uri).mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
