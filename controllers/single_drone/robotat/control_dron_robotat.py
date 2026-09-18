r"""Panel de teclado para un Crazyflie sobre el Robotat.

Controlador nuevo, de un solo dron y sólo con mocap. Las órdenes son las de
siempre: PREFLIGHT, despegar, pasos de 10 cm y giros de 20 grados, aterrizar
y EMERGENCIA. Lo que cambia respecto al backend de la cruz está descrito en
`README.md` de esta carpeta.

Sin hardware:
    .\.venv\Scripts\python.exe .\controllers\single_drone\robotat\control_dron_robotat.py --dry-run

Con el Dron 1 (PREFLIGHT no enciende motores):
    .\.venv\Scripts\python.exe .\controllers\single_drone\robotat\control_dron_robotat.py --dron 1

Juego validado con el Dron 2 (2026-09-16) y velocidad de manejo:
    ... --dron 2 --ganancias robotat --velocidad 0.25 --radio-max 1.0

Otras pruebas, sin recompilar el firmware:
    ... --dron 2 --ganancias mitad --anticipo-s 0.08
    ... --dron 2 --ganancias robotat --param posCtlPid.thrustBase=47000   (manda sobre el preajuste)

Teclado: W/A/S/D mueven, Espacio y Shift suben y bajan, Q y E giran, Enter
despega o aterriza y **R corta motores**. Por defecto (`--modo fluido`) la
tecla mantenida manda una velocidad al firmware, igual que el Flow Deck, y al
soltarla el dron frena y vuelve al hover high-level; `--modo continuo`
encadena go_to cortos y `--modo pasos` da un paso de 10 cm por pulsación.
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
SHARED_DIR = MODULE_DIR.parents[1] / "shared"
for directory in (MODULE_DIR, SHARED_DIR):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from dron_robotat import (  # noqa: E402
    DEFAULT_EXT_POS_STD_M, GANANCIAS, GOTO_SPEED_MPS, MAX_RADIUS_FROM_ORIGIN_M, MAX_YAW_STEP_DEG,
    TAKEOFF_HEIGHT_M, DronError, DronRobotat, DronSimulado, Opciones, parametros_firmware,
)
from radios import DRONE_1_LINK, DRONE_2_LINK, select_uri  # noqa: E402
from robotat import DRONE_1_TOPIC, DRONE_2_TOPIC  # noqa: E402
from dron_robotat import HOLD_PERIOD_S  # noqa: E402
from tk_keys import (  # noqa: E402
    AYUDA_TECLADO_SIMPLE, KEY_DIRECTIONS, KEY_ROTATIONS, DualStepKeysMixin, normalize_key,
)

STEP_XY_M = 0.10
STEP_Z_M = 0.08
STEP_YAW_DEG = MAX_YAW_STEP_DEG
REFRESH_MS = 150
#: Pasos que pueden quedar en cola mientras el dron ejecuta el anterior. Cada
#: pulsación es un paso; sin cola, pulsar W tres veces daba un solo paso.
MAX_PASOS_EN_COLA = 3


def opciones_desde_args(args: argparse.Namespace) -> Opciones:
    """Traduce la línea de órdenes; no abre radios ni broker."""
    link = DRONE_1_LINK if args.dron == "1" else DRONE_2_LINK
    topic = args.topic or (DRONE_1_TOPIC if args.dron == "1" else DRONE_2_TOPIC)
    if args.dry_run:
        uri = args.uri or f"radio://sim/{link[0]}/{link[1]}/{link[2]}"
    else:
        uri = select_uri(args.uri, args.radio, link)
    if args.anticipo_s < 0.0 or args.anticipo_s > 0.3:
        raise SystemExit("--anticipo-s debe estar entre 0 y 0.3 s")
    if not 0.001 <= args.ext_pos_std <= 0.5:
        raise SystemExit("--ext-pos-std debe estar entre 0.001 y 0.5 m")
    if not 0.2 <= args.altura <= 1.0:
        raise SystemExit("--altura debe estar entre 0.2 y 1.0 m")
    if not 0.05 <= args.velocidad <= 0.5:
        raise SystemExit("--velocidad debe estar entre 0.05 y 0.5 m/s")
    return Opciones(
        uri=uri, topic=topic, nombre=f"Dron {args.dron}",
        extpose=args.extpose, anticipo_s=args.anticipo_s, ext_pos_std_m=args.ext_pos_std,
        parametros=GANANCIAS[args.ganancias] | parametros_firmware(args.param), altura_m=args.altura,
        radio_max_m=args.radio_max, velocidad_mps=args.velocidad,
        thrust_base_explicito="posCtlPid.thrustBase" in parametros_firmware(args.param),
        centro_geocerca=None if args.centro_geocerca is None else tuple(args.centro_geocerca),
    )


class PanelRobotat(DualStepKeysMixin, tk.Tk):
    """Ventana con botones y teclado. Las órdenes corren en un hilo aparte."""

    def __init__(self, dron: Any, *, dry_run: bool, modo: str = "continuo") -> None:
        super().__init__()
        self.dron = dron
        self.dry_run = dry_run
        #: "fluido": la tecla mantenida manda velocidad, como el Flow Deck;
        #: "continuo": go_to cortos encadenados; "pasos": un paso por pulsación.
        self.modo = modo
        self._held: set[str] = set()
        self._hold_tick_pending = False
        self.title(f"{dron.opciones.nombre} sobre el Robotat" + (" (simulado)" if dry_run else ""))
        self.geometry("720x560")
        self.minsize(640, 500)
        self.protocol("WM_DELETE_WINDOW", self.close_window)

        self._queue: queue.Queue[tuple[str, Callable[[], None]]] = queue.Queue()
        self._busy = False
        self._worker = threading.Thread(target=self._run_orders, name="OrdenesPanel", daemon=True)
        self._worker.start()

        self.summary = tk.StringVar(value=dron.estado().detalle)
        self.telemetry = tk.StringVar(value="")
        self._build()
        self._bind_flight_keys(emergency=self.emergency, close=self.close_window, takeoff_land=self.takeoff_or_land)
        self.after(REFRESH_MS, self._refresh)

    # -- Construcción ----------------------------------------------------------

    def _build(self) -> None:
        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)

        top = ttk.Frame(root)
        top.pack(fill="x")
        ttk.Button(top, text="PREFLIGHT", command=self.preflight).pack(side="left", padx=4)
        ttk.Button(top, text="Despegar", command=self.takeoff).pack(side="left", padx=4)
        ttk.Button(top, text="Aterrizar", command=self.land).pack(side="left", padx=4)
        stop = tk.Button(top, text="EMERGENCIA (R)", command=self.emergency, bg="#b00020", fg="white", font=("Segoe UI", 11, "bold"))
        stop.pack(side="right", padx=4)

        ttk.Label(root, textvariable=self.summary, wraplength=680, font=("Segoe UI", 10, "bold")).pack(fill="x", pady=(10, 4))

        pad = ttk.Frame(root)
        pad.pack(pady=8)
        moves = {
            (0, 1): ("Adelante +X (W)", (STEP_XY_M, 0, 0, 0)),
            (1, 0): ("Izquierda +Y (A)", (0, STEP_XY_M, 0, 0)),
            (1, 2): ("Derecha -Y (D)", (0, -STEP_XY_M, 0, 0)),
            (2, 1): ("Atrás -X (S)", (-STEP_XY_M, 0, 0, 0)),
            (0, 3): ("Subir (Espacio)", (0, 0, STEP_Z_M, 0)),
            (2, 3): ("Bajar (Shift)", (0, 0, -STEP_Z_M, 0)),
            (0, 0): ("Giro izq. (Q)", (0, 0, 0, STEP_YAW_DEG)),
            (0, 2): ("Giro der. (E)", (0, 0, 0, -STEP_YAW_DEG)),
        }
        for (row, col), (text, step) in moves.items():
            ttk.Button(pad, text=text, width=18, command=lambda s=step: self.step(*s)).grid(row=row, column=col, padx=3, pady=3)

        ttk.Label(root, textvariable=self.telemetry, font=("Consolas", 10), justify="left").pack(fill="x", pady=(8, 4))
        ayuda = AYUDA_TECLADO_SIMPLE + {
            "fluido": "\nModo fluido: mantén la tecla para moverte a velocidad constante; suéltala para frenar.",
            "continuo": "\nModo continuo: mantén la tecla para moverte; suéltala para frenar.",
            "pasos": "\nModo pasos: cada pulsación es un paso de 10 cm.",
        }[self.modo]
        ttk.Label(root, text=ayuda, foreground="#555").pack(fill="x", pady=(4, 0))

        self.log_box = tk.Text(root, height=8, state="disabled", font=("Consolas", 9))
        self.log_box.pack(fill="both", expand=True, pady=(6, 0))
        self.focus_set()

    # -- Órdenes ---------------------------------------------------------------

    def _run_orders(self) -> None:
        while True:
            name, action = self._queue.get()
            self._busy = True
            try:
                action()
            except DronError as exc:
                self.after(0, self._log, f"{name}: rechazada: {exc}")
            except Exception as exc:
                self.after(0, self._log, f"{name}: fallo: {exc}")
            finally:
                self._busy = False

    def _enqueue(self, name: str, action: Callable[[], None], *, cola: bool = False) -> None:
        if cola:
            if self._queue.qsize() >= MAX_PASOS_EN_COLA:
                self._log(f"{name}: cola llena ({MAX_PASOS_EN_COLA} pasos pendientes)")
                return
        elif self._busy or not self._queue.empty():
            self._log(f"{name}: espera, hay una orden en curso")
            return
        self._queue.put((name, action))

    def _keys_enabled(self) -> bool:
        # Los pasos se encolan; la cola decide si caben.
        return True

    def _key_step(self, slot: int, ux: int, uy: int, uz: int) -> None:
        if slot == 0:
            self.step(ux * STEP_XY_M, uy * STEP_XY_M, uz * STEP_Z_M, 0.0)

    def _key_rotate(self, slot: int, uyaw: int) -> None:
        if slot == 0:
            self.step(0.0, 0.0, 0.0, uyaw * STEP_YAW_DEG)

    # -- Modo continuo: tecla mantenida -----------------------------------------

    def _key_press(self, event: tk.Event) -> str:
        if self.modo == "pasos":
            return super()._key_press(event)
        key = normalize_key(event.keysym)
        if key in KEY_DIRECTIONS or key in KEY_ROTATIONS:
            if key not in self._held:
                self._held.add(key)
                self._schedule_hold_tick(inmediato=True)
        return "break"

    def _key_release(self, event: tk.Event) -> str:
        if self.modo == "pasos":
            return super()._key_release(event)
        self._held.discard(normalize_key(event.keysym))
        if self.modo == "fluido" and not self._held:
            # Soltar la última tecla frena: velocidad cero y entrega al high-level.
            self._queue.put(("Fluido", lambda: self.dron.fijar_velocidad(0, 0, 0, 0)))
        return "break"

    def _direccion_teclas(self) -> tuple[int, int, int, int]:
        ux = uy = uz = uyaw = 0
        for key in self._held:
            direction = KEY_DIRECTIONS.get(key)
            if direction is not None and direction[0] == 0:
                ux += direction[1]; uy += direction[2]; uz += direction[3]
            rotation = KEY_ROTATIONS.get(key)
            if rotation is not None and rotation[0] == 0:
                uyaw += rotation[1]
        return ux, uy, uz, uyaw

    def _fluid_update(self) -> None:
        ux, uy, uz, uyaw = self._direccion_teclas()
        if self._queue.empty():
            self._queue.put(("Fluido", lambda: self.dron.fijar_velocidad(ux, uy, uz, uyaw)))

    def _schedule_hold_tick(self, *, inmediato: bool = False) -> None:
        if self._hold_tick_pending:
            return
        self._hold_tick_pending = True
        self.after(0 if inmediato else int(HOLD_PERIOD_S * 1000), self._hold_tick)

    def _hold_tick(self) -> None:
        self._hold_tick_pending = False
        if not self._held:
            return
        if self.modo == "fluido":
            self._fluid_update()
            self._schedule_hold_tick()
            return
        ux = uy = uz = uyaw = 0
        for key in self._held:
            direction = KEY_DIRECTIONS.get(key)
            if direction is not None and direction[0] == 0:
                ux += direction[1]; uy += direction[2]; uz += direction[3]
            rotation = KEY_ROTATIONS.get(key)
            if rotation is not None and rotation[0] == 0:
                uyaw += rotation[1]
        if (ux or uy or uz or uyaw) and not self._busy and self._queue.empty():
            self._queue.put(("Continuo", lambda: self.dron.avanzar(ux, uy, uz, uyaw)))
        self._schedule_hold_tick()

    def preflight(self) -> None:
        def run() -> None:
            self.dron.preflight(lambda m: self.after(0, self._log, m))
        self._enqueue("PREFLIGHT", run)

    def takeoff(self) -> None:
        if not self.dry_run and not messagebox.askyesno("Despegar", "¿Despegar? Los motores se encienden."):
            return
        self._enqueue("Despegar", self.dron.takeoff)

    def land(self) -> None:
        self._enqueue("Aterrizar", self.dron.land)

    def takeoff_or_land(self) -> None:
        if self.dron.estado().en_vuelo:
            self.land()
        else:
            self.takeoff()

    def step(self, dx: float, dy: float, dz: float, dyaw: float) -> None:
        def run() -> None:
            # Un paso espera a que acabe el anterior en vez de rechazarse:
            # el dron sigue sin recibir go_to solapados.
            if not self.dron.esperar_libre():
                raise DronError("la orden anterior no termino")
            self.dron.move(dx, dy, dz, dyaw)
        self._enqueue("Paso", run, cola=True)

    def emergency(self) -> None:
        # Nunca por la cola: tiene que ejecutarse aunque haya una orden en curso.
        threading.Thread(target=self.dron.emergency, args=("boton o tecla R",), daemon=True).start()

    def close_window(self) -> None:
        if self.dron.estado().en_vuelo and not self.dry_run:
            if not messagebox.askyesno("Cerrar", "El dron esta en vuelo. ¿Aterrizar y cerrar?"):
                return
        threading.Thread(target=self._close_and_quit, daemon=True).start()

    def _close_and_quit(self) -> None:
        try:
            self.dron.close()
        finally:
            self.after(0, self.destroy)

    # -- Refresco --------------------------------------------------------------

    def _log(self, text: str) -> None:
        print(text, flush=True)
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _refresh(self) -> None:
        e = self.dron.estado()
        self.summary.set(f"[{e.modo}] {e.detalle}")

        def fmt(v, spec=".3f", unit=""):
            return "  n/d" if v is None else f"{v:{spec}}{unit}"

        def xyz(v):
            return "n/d" if v is None else ", ".join(f"{c:+.3f}" for c in v)

        lines = [
            f"mocap  ({xyz(e.mocap)}) m  yaw {fmt(e.mocap_yaw_deg, '+.1f', ' deg')}  edad {fmt(e.mocap_edad_s, '.3f', ' s')}",
            f"EKF    ({xyz(e.ekf)}) m  yaw {fmt(e.ekf_yaw_deg, '+.1f', ' deg')}  error {fmt(e.error_ekf_mocap_m, '.3f', ' m')}",
            f"objetivo ({xyz(e.objetivo)}) m  yaw {e.objetivo_yaw_deg:+.0f} deg",
            f"frames {fmt(e.mocap_frames_hz, '.1f', ' Hz')}  hueco max {fmt(e.mocap_hueco_max_s, '.3f', ' s')}  "
            f"latencia {fmt(e.mqtt_latencia_s, '.3f', ' s')}  extpos {e.extpos_enviados}",
            f"bateria {fmt(e.bateria_v, '.2f', ' V')}  roll {fmt(e.roll_deg, '+.1f')}  pitch {fmt(e.pitch_deg, '+.1f')}",
        ]
        self.telemetry.set("\n".join(lines))
        self.after(REFRESH_MS, self._refresh)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Control de un Crazyflie sobre el Robotat, desde cero")
    parser.add_argument("--dron", choices=("1", "2"), default="1", help="Crazyflie y rigid body a usar")
    parser.add_argument("--uri", help="URI cflib explicita; por defecto la radio conocida del dron elegido")
    parser.add_argument("--radio", help="serial de la Crazyradio a usar")
    parser.add_argument("--topic", help="topico MQTT del rigid body; por defecto el del dron elegido")
    parser.add_argument("--dry-run", action="store_true", help="simula Robotat y radio; nunca activa motores")
    parser.add_argument("--altura", type=float, default=TAKEOFF_HEIGHT_M, help=f"altura de despegue sobre el suelo, m (defecto {TAKEOFF_HEIGHT_M})")
    parser.add_argument("--radio-max", type=float, default=MAX_RADIUS_FROM_ORIGIN_M, help=f"geocerca horizontal desde el origen, m (defecto {MAX_RADIUS_FROM_ORIGIN_M})")
    parser.add_argument("--modo", choices=("fluido", "continuo", "pasos"), default="fluido",
                        help="fluido: la tecla mantenida manda velocidad al firmware, como el Flow Deck "
                             "(defecto). continuo: go_to cortos encadenados. pasos: un paso de 10 cm "
                             "por pulsacion")
    parser.add_argument("--velocidad", type=float, default=GOTO_SPEED_MPS,
                        help=f"velocidad de crucero de cada paso, m/s (defecto {GOTO_SPEED_MPS}; "
                             "un paso de 10 cm dura 10 cm / velocidad, minimo 1 s)")
    parser.add_argument("--centro-geocerca", type=float, nargs=2, metavar=("X", "Y"), default=None,
                        help="centro de la geocerca en el marco del Robotat, m; por defecto el punto de despegue")
    parser.add_argument("--ext-pos-std", type=float, default=DEFAULT_EXT_POS_STD_M,
                        help=f"locSrv.extPosStdDev: cuanto se fia el EKF del mocap, m (fabrica {DEFAULT_EXT_POS_STD_M})")
    parser.add_argument("--anticipo-s", type=float, default=0.0,
                        help="extrapola el mocap con su velocidad este tiempo antes de enviarlo al EKF, s (0 = no)")
    parser.add_argument("--extpose", action="store_true",
                        help="envia tambien el cuaternion del rigid body al EKF (solo si sus ejes coinciden con el dron)")
    parser.add_argument("--ganancias", choices=tuple(GANANCIAS), default="fabrica",
                        help="juego de ganancias del firmware: robotat (validado el 2026-09-16 con el "
                             "Dron 2: mitad + vzKi=8, thrustBase=46000, extPosStdDev=0.03), mitad, "
                             "mitad-xy o fabrica")
    parser.add_argument("--param", action="append", metavar="GRUPO.NOMBRE=VALOR",
                        help="parametro del firmware a fijar tras conectar; repetible y "
                             "tiene prioridad sobre --ganancias")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        opciones = opciones_desde_args(args)
    except RuntimeError as exc:
        print(f"No se pudo preparar el dron: {exc}", file=sys.stderr)
        return 2
    dron = DronSimulado(opciones) if args.dry_run else DronRobotat(opciones)
    print(f"{opciones.nombre}: uri={opciones.uri} topic={opciones.topic} "
          f"extPosStdDev={opciones.ext_pos_std_m} anticipo={opciones.anticipo_s}s extpose={opciones.extpose}")
    PanelRobotat(dron, dry_run=args.dry_run, modo=args.modo).mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
