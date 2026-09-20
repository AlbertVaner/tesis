r"""Panel de teclado para los dos Crazyflies sobre el Robotat, con el controlador nuevo.

Dos instancias independientes de `DronRobotat` (`controllers/shared`), cada
una con su Crazyradio, su rigid body y su CSV, y un supervisor de separación
que aterriza a los dos si se acercan a menos de `SEPARACION_MIN_M`. Sirve
para probar los dos drones con el mismo mando fluido que ya voló con uno.

    .\.venv\Scripts\python.exe .\controllers\two_drones\control_dos_drones_robotat.py --dry-run
    .\.venv\Scripts\python.exe .\controllers\two_drones\control_dos_drones_robotat.py --ganancias robotat --velocidad 0.25 --radio-max 1.0

Teclado (esquema de `shared/tk_keys.py`): Dron 1 con W/A/S/D, Espacio/Shift y
Q/E; Dron 2 con flechas, Re Pág/Av Pág e Inicio/Fin. Mantener la tecla mueve;
soltarla frena. Enter despega o aterriza los dos; **R corta motores de los dos**.

El núcleo por dron (`DronRobotat`) vive en `controllers/shared/`.
"""

from __future__ import annotations

import argparse
import math
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

from dron_robotat import (  # noqa: E402
    DEFAULT_EXT_POS_STD_M, GANANCIAS, GOTO_SPEED_MPS, MAX_RADIUS_FROM_ORIGIN_M, TAKEOFF_HEIGHT_M,
    DronError, DronRobotat, DronSimulado, Opciones, parametros_firmware,
)
from radios import DRONE_1_LINK, DRONE_2_LINK, KNOWN_RADIOS, make_uri, select_radio  # noqa: E402
from robotat_backend import SupervisorSeparacion, separacion  # noqa: E402
from reloj import ahora  # noqa: E402
from robotat import DRONE_1_TOPIC, DRONE_2_TOPIC  # noqa: E402
from tk_keys import (  # noqa: E402
    AYUDA_TECLADO_DUAL, KEY_DIRECTIONS, KEY_ROTATIONS, DualStepKeysMixin, normalize_key,
)

from robotat_backend import SEPARACION_INICIAL_M, SEPARACION_MIN_M  # noqa: E402
HOLD_TICK_MS = 200
REFRESH_MS = 150
CLAVES = ("drone1", "drone2")
#: Botones de dirección por dron: texto y tecla equivalente. Actúan mientras
#: se mantiene pulsado el ratón, igual que la tecla. Sirven de alternativa si
#: el teclado no entrega las flechas o Re Pág/Av Pág (portátiles con Fn).
BOTONES_DIRECCION = {
    "drone1": (("Adelante", "w"), ("Atrás", "s"), ("Izquierda", "a"), ("Derecha", "d"),
               ("Subir", "space"), ("Bajar", "shift"), ("Giro izq", "q"), ("Giro der", "e")),
    "drone2": (("Adelante", "up"), ("Atrás", "down"), ("Izquierda", "left"), ("Derecha", "right"),
               ("Subir", "pageup"), ("Bajar", "pagedown"), ("Giro izq", "home"), ("Giro der", "end")),
}


def opciones_dual(args: argparse.Namespace) -> dict[str, Opciones]:
    """Una `Opciones` por dron; cada uno con su Crazyradio y su rigid body."""
    parametros = GANANCIAS[args.ganancias] | parametros_firmware(args.param)
    explicito = "posCtlPid.thrustBase" in parametros_firmware(args.param)
    if args.dry_run:
        uris = {"drone1": f"radio://sim/{DRONE_1_LINK[0]}/2M/{DRONE_1_LINK[2]}",
                "drone2": f"radio://sim/{DRONE_2_LINK[0]}/2M/{DRONE_2_LINK[2]}"}
    else:
        radio1 = select_radio(args.radio1, index=0)
        radio2 = select_radio(args.radio2, index=1)
        if radio1 == radio2:
            raise RuntimeError("los dos drones necesitan dos Crazyradio distintas")
        uris = {"drone1": args.uri1 or make_uri(radio1, DRONE_1_LINK),
                "drone2": args.uri2 or make_uri(radio2, DRONE_2_LINK)}
    topics = {"drone1": args.topic1 or DRONE_1_TOPIC, "drone2": args.topic2 or DRONE_2_TOPIC}
    nombres = {"drone1": "Dron 1", "drone2": "Dron 2"}
    return {
        clave: Opciones(
            uri=uris[clave], topic=topics[clave], nombre=nombres[clave],
            ext_pos_std_m=args.ext_pos_std, parametros=dict(parametros), altura_m=args.altura,
            radio_max_m=args.radio_max, velocidad_mps=args.velocidad, thrust_base_explicito=explicito,
            centro_geocerca=None if args.centro_geocerca is None else tuple(args.centro_geocerca),
        )
        for clave in CLAVES
    }


class PanelDosRobotat(DualStepKeysMixin, tk.Tk):
    """Ventana con una columna de botones por dron y el teclado dual, en modo fluido.

    Las columnas salen de las claves de `drones`; el panel de tres drones
    (`control_tres_drones_robotat.py`) hereda de éste y sólo cambia los
    atributos de clase: teclas, botones, ayuda y tamaño.
    """

    TITULO = "Dos Crazyflies sobre el Robotat"
    GEOMETRIA = ("980x640", 900, 560)
    TODOS = "ambos"
    KEY_DIRECTIONS = KEY_DIRECTIONS
    KEY_ROTATIONS = KEY_ROTATIONS
    #: Teclas que `_bind_flight_keys` no enlaza (las del tercer dron).
    KEYSYMS_EXTRA: tuple[str, ...] = ()
    BOTONES = BOTONES_DIRECCION
    AYUDA = AYUDA_TECLADO_DUAL

    def __init__(self, drones: dict[str, Any], *, dry_run: bool) -> None:
        super().__init__()
        self.drones = drones
        self.claves = tuple(drones)
        CLAVES = self.claves
        self.dry_run = dry_run
        self.title(self.TITULO + (" (simulado)" if dry_run else ""))
        self.geometry(self.GEOMETRIA[0])
        self.minsize(*self.GEOMETRIA[1:])
        self.protocol("WM_DELETE_WINDOW", self.close_window)
        self.supervisor = SupervisorSeparacion(drones, log=lambda m: self.after(0, self._log, m))
        self._queues = {c: queue.Queue() for c in CLAVES}
        self._busy = {c: False for c in CLAVES}
        for c in CLAVES:
            threading.Thread(target=self._run_orders, args=(c,), name=f"Ordenes-{c}", daemon=True).start()
        self._held: set[str] = set()
        self._hold_tick_pending = False
        self.summary = {c: tk.StringVar(value=drones[c].estado().detalle) for c in CLAVES}
        self.telemetry = {c: tk.StringVar(value="") for c in CLAVES}
        self.separacion_var = tk.StringVar(value="separación: n/d")
        self._build()
        self._bind_flight_keys(emergency=self.emergency, close=self.close_window, takeoff_land=self.takeoff_or_land)
        for key in self.KEYSYMS_EXTRA:
            self.bind_all(f"<KeyPress-{key}>", self._key_press)
            self.bind_all(f"<KeyRelease-{key}>", self._key_release)
        self.after(REFRESH_MS, self._refresh)

    # -- Construcción ----------------------------------------------------------

    def _build(self) -> None:
        CLAVES = self.claves
        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)
        top = ttk.Frame(root)
        top.pack(fill="x")
        ttk.Button(top, text=f"PREFLIGHT {self.TODOS}", command=lambda: self.preflight(CLAVES)).pack(side="left", padx=4)
        ttk.Button(top, text=f"Despegar {self.TODOS}", command=lambda: self.takeoff(CLAVES)).pack(side="left", padx=4)
        ttk.Button(top, text=f"Aterrizar {self.TODOS}", command=lambda: self.land(CLAVES)).pack(side="left", padx=4)
        ttk.Label(top, textvariable=self.separacion_var, font=("Consolas", 10)).pack(side="left", padx=16)
        tk.Button(top, text="EMERGENCIA (R)", command=self.emergency, bg="#b00020", fg="white",
                  font=("Segoe UI", 11, "bold")).pack(side="right", padx=4)

        columnas = ttk.Frame(root)
        columnas.pack(fill="x", pady=8)
        for i, c in enumerate(CLAVES):
            col = ttk.LabelFrame(columnas, text=self.drones[c].opciones.nombre, padding=8)
            col.grid(row=0, column=i, padx=6, sticky="nsew")
            columnas.columnconfigure(i, weight=1)
            fila = ttk.Frame(col)
            fila.pack(fill="x")
            ttk.Button(fila, text="PREFLIGHT", command=lambda c=c: self.preflight((c,))).pack(side="left", padx=2)
            ttk.Button(fila, text="Despegar", command=lambda c=c: self.takeoff((c,))).pack(side="left", padx=2)
            ttk.Button(fila, text="Aterrizar", command=lambda c=c: self.land((c,))).pack(side="left", padx=2)
            ttk.Label(col, textvariable=self.summary[c], wraplength=840 // len(CLAVES), font=("Segoe UI", 9, "bold")).pack(fill="x", pady=(6, 2))
            ttk.Label(col, textvariable=self.telemetry[c], font=("Consolas", 9), justify="left").pack(fill="x")
            pad = ttk.Frame(col)
            pad.pack(pady=(6, 0))
            for k, (texto, tecla) in enumerate(self.BOTONES[c]):
                boton = ttk.Button(pad, text=texto, width=10)
                boton.grid(row=k // 4, column=k % 4, padx=2, pady=2)
                boton.bind("<ButtonPress-1>", lambda _e, t=tecla: self._pulsar(t))
                boton.bind("<ButtonRelease-1>", lambda _e, t=tecla: self._soltar(t))

        ttk.Label(root, text=self.AYUDA + "\nMantén la tecla para moverte; suéltala para frenar.",
                  foreground="#555").pack(fill="x", pady=(4, 0))
        self.log_box = tk.Text(root, height=8, state="disabled", font=("Consolas", 9))
        self.log_box.pack(fill="both", expand=True, pady=(6, 0))
        self.focus_set()

    # -- Órdenes ---------------------------------------------------------------

    def _run_orders(self, clave: str) -> None:
        while True:
            name, action = self._queues[clave].get()
            self._busy[clave] = True
            try:
                action()
            except DronError as exc:
                self.after(0, self._log, f"{clave} {name}: rechazada: {exc}")
            except Exception as exc:
                self.after(0, self._log, f"{clave} {name}: fallo: {exc}")
            finally:
                self._busy[clave] = False

    def _enqueue(self, clave: str, name: str, action: Callable[[], None]) -> None:
        if self._busy[clave] or not self._queues[clave].empty():
            self._log(f"{clave} {name}: espera, hay una orden en curso")
            return
        self._queues[clave].put((name, action))

    def preflight(self, claves) -> None:
        CLAVES = self.claves
        if len(claves) > 1 and not self.dry_run:
            # Todos en el suelo y separados antes de abrir radios.
            def ambos() -> None:
                for c in CLAVES:
                    self.drones[c].preflight(lambda m, c=c: self.after(0, self._log, f"{c}: {m}"))
                dist = separacion({c: self.drones[c].estado() for c in CLAVES})
                if dist is not None and dist < SEPARACION_INICIAL_M:
                    raise DronError(f"separacion inicial {dist:.2f} m; se requieren {SEPARACION_INICIAL_M:.2f} m")
                self.supervisor.start()
            self._enqueue(CLAVES[0], "PREFLIGHT", ambos)
            return
        for c in claves:
            self._enqueue(c, "PREFLIGHT", lambda c=c: self.drones[c].preflight(
                lambda m, c=c: self.after(0, self._log, f"{c}: {m}")))
        if not self.supervisor._thread.is_alive():
            self.supervisor.start()

    def takeoff(self, claves) -> None:
        if not self.dry_run and not messagebox.askyesno("Despegar", "¿Despegar? Los motores se encienden."):
            return
        for c in claves:
            self._enqueue(c, "Despegar", self.drones[c].takeoff)

    def land(self, claves) -> None:
        for c in claves:
            self._enqueue(c, "Aterrizar", self.drones[c].land)

    def takeoff_or_land(self) -> None:
        if any(self.drones[c].estado().en_vuelo for c in self.claves):
            self.land(self.claves)
        else:
            self.takeoff(self.claves)

    def emergency(self) -> None:
        for c in self.claves:
            threading.Thread(target=self.drones[c].emergency, args=("boton o tecla R",), daemon=True).start()

    # -- Teclado: tecla mantenida = velocidad ---------------------------------

    def _key_press(self, event: tk.Event) -> str:
        self._pulsar(normalize_key(event.keysym))
        return "break"

    def _key_release(self, event: tk.Event) -> str:
        self._soltar(normalize_key(event.keysym))
        return "break"

    @classmethod
    def _slot_de(cls, key: str) -> int | None:
        return (cls.KEY_DIRECTIONS.get(key) or cls.KEY_ROTATIONS.get(key) or (None,))[0]

    def _pulsar(self, key: str) -> None:
        """Tecla o botón de dirección pulsado: empieza a mover ese dron."""
        slot = self._slot_de(key)
        if slot is None or key in self._held:
            return
        self._held.add(key)
        self._log(f"{self.claves[slot]} <- {key}")
        self._schedule_hold_tick(inmediato=True)

    def _soltar(self, key: str) -> None:
        """Tecla o botón soltado: si ese dron no tiene otra tecla, frena."""
        slot = self._slot_de(key)
        self._held.discard(key)
        if slot is None or any(self._slot_de(k) == slot for k in self._held):
            return
        c = self.claves[slot]
        self._queues[c].put(("Frenar", lambda c=c: self.drones[c].fijar_velocidad(0, 0, 0, 0)))

    def _direcciones(self) -> dict[str, tuple[int, int, int, int]]:
        CLAVES = self.claves
        acumulado = {c: [0, 0, 0, 0] for c in CLAVES}
        for key in self._held:
            direction = self.KEY_DIRECTIONS.get(key)
            if direction is not None:
                slot, ux, uy, uz = direction
                a = acumulado[CLAVES[slot]]
                a[0] += ux; a[1] += uy; a[2] += uz
            rotation = self.KEY_ROTATIONS.get(key)
            if rotation is not None:
                acumulado[CLAVES[rotation[0]]][3] += rotation[1]
        return {c: tuple(v) for c, v in acumulado.items()}

    def _schedule_hold_tick(self, *, inmediato: bool = False) -> None:
        if self._hold_tick_pending:
            return
        self._hold_tick_pending = True
        self.after(0 if inmediato else HOLD_TICK_MS, self._hold_tick)

    def _hold_tick(self) -> None:
        self._hold_tick_pending = False
        if not self._held:
            return
        for c, (ux, uy, uz, uyaw) in self._direcciones().items():
            if (ux or uy or uz or uyaw) and not self._busy[c] and self._queues[c].empty():
                self._queues[c].put(("Fluido", lambda c=c, a=(ux, uy, uz, uyaw): self.drones[c].fijar_velocidad(*a)))
        self._schedule_hold_tick()

    # -- Cierre y refresco -----------------------------------------------------

    def close_window(self) -> None:
        if any(self.drones[c].estado().en_vuelo for c in self.claves) and not self.dry_run:
            if not messagebox.askyesno("Cerrar", "Hay un dron en vuelo. ¿Aterrizar y cerrar?"):
                return
        threading.Thread(target=self._close_and_quit, daemon=True).start()

    def _close_and_quit(self) -> None:
        self.supervisor.stop()
        try:
            hilos = [threading.Thread(target=self.drones[c].close, daemon=True) for c in self.claves]
            for h in hilos:
                h.start()
            for h in hilos:
                h.join(timeout=12.0)
        finally:
            self.after(0, self.destroy)

    def _log(self, text: str) -> None:
        print(text, flush=True)
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _refresh(self) -> None:
        estados = {}
        # Con tres columnas la línea de poses no cabe: mocap y EKF van aparte.
        corte = "\n" if len(self.claves) > 2 else "  "
        for c in self.claves:
            e = self.drones[c].estado()
            estados[c] = e
            self.summary[c].set(f"[{e.modo}] {e.detalle}")

            def fmt(v, spec=".3f", unit=""):
                return "  n/d" if v is None else f"{v:{spec}}{unit}"

            def xyz(v):
                return "n/d" if v is None else ", ".join(f"{k:+.2f}" for k in v)

            self.telemetry[c].set(
                f"mocap ({xyz(e.mocap)}){corte}EKF ({xyz(e.ekf)})  err {fmt(e.error_ekf_mocap_m, '.3f', ' m')}\n"
                f"objetivo ({xyz(e.objetivo)})  yaw {e.objetivo_yaw_deg:+.0f}  bat {fmt(e.bateria_v, '.2f', ' V')}\n"
                f"frames {fmt(e.mocap_frames_hz, '.1f', ' Hz')}  hueco {fmt(e.mocap_hueco_max_s, '.2f', ' s')}  "
                f"extpos {e.extpos_enviados}"
            )
        dist = separacion(estados)
        self.separacion_var.set("separación: n/d" if dist is None else f"separación: {dist:.2f} m")
        self.after(REFRESH_MS, self._refresh)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dos Crazyflies sobre el Robotat con el controlador nuevo")
    parser.add_argument("--dry-run", action="store_true", help="simula Robotat y radios; nunca activa motores")
    parser.add_argument("--uri1", help=f"URI del Dron 1; por defecto la radio {KNOWN_RADIOS[0]}")
    parser.add_argument("--uri2", help=f"URI del Dron 2; por defecto la radio {KNOWN_RADIOS[1]}")
    parser.add_argument("--radio1", help="serial de la Crazyradio del Dron 1")
    parser.add_argument("--radio2", help="serial de la Crazyradio del Dron 2")
    parser.add_argument("--topic1", help=f"topico del Dron 1 (defecto {DRONE_1_TOPIC})")
    parser.add_argument("--topic2", help=f"topico del Dron 2 (defecto {DRONE_2_TOPIC})")
    parser.add_argument("--ganancias", choices=tuple(GANANCIAS), default="robotat")
    parser.add_argument("--param", action="append", metavar="GRUPO.NOMBRE=VALOR",
                        help="parametro del firmware para los dos drones; manda sobre --ganancias")
    parser.add_argument("--ext-pos-std", type=float, default=DEFAULT_EXT_POS_STD_M)
    parser.add_argument("--altura", type=float, default=TAKEOFF_HEIGHT_M)
    parser.add_argument("--radio-max", type=float, default=MAX_RADIUS_FROM_ORIGIN_M)
    parser.add_argument("--velocidad", type=float, default=GOTO_SPEED_MPS,
                        help="velocidad del mando fluido, m/s (defecto 0.10; probado 0.25)")
    parser.add_argument("--centro-geocerca", type=float, nargs=2, metavar=("X", "Y"), default=None,
                        help="centro de la geocerca en el marco del Robotat; por defecto el despegue de cada dron")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 0.05 <= args.velocidad <= 0.5:
        raise SystemExit("--velocidad debe estar entre 0.05 y 0.5 m/s")
    try:
        opciones = opciones_dual(args)
    except RuntimeError as exc:
        print(f"No se pudo preparar los drones: {exc}", file=sys.stderr)
        return 2
    drones = {
        c: (DronSimulado(o) if args.dry_run else DronRobotat(o)) for c, o in opciones.items()
    }
    for c, o in opciones.items():
        print(f"{o.nombre}: uri={o.uri} topic={o.topic}")
    PanelDosRobotat(drones, dry_run=args.dry_run).mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
