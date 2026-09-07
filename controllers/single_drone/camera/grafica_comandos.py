"""Gráfica de tiempo contra comandos para los controladores por cámara.

Cada ejecución de `control_camara_flowdeck_dron1.py` (una mano) y de
`control_corporal_dron1.py` (cuerpo entero) deja una figura en

    results/graphs/<controlador>/<AAAA-MM-DD>/<sesion>_comandos.png  (y .pdf)

con el comando que el controlador atendió en cada instante, si estaba
confirmado, y el estado del dron de fondo (maniobrando, volando).

Es la figura que responde a «qué entendió el sistema y cuándo»: se ve la
latencia entre el gesto y su confirmación, los comandos que parpadean, y
cuánto tiempo se sostuvo cada orden. Es la misma figura para los dos
controladores a propósito, para que una sesión de mano y una de cuerpo se
puedan poner una junto a otra.

Uso desde un controlador:

    grafica = GraficaDeComandos("control_corporal_dron1")
    ...
    grafica.anotar(t_s, "ADELANTE", confirmado=True, estado="VOLANDO")
    ...
    grafica.guardar()          # en el `finally`, después de cerrar la radio

`guardar()` nunca lanza: una gráfica que falla no debe impedir que el
controlador termine de aterrizar y cerrar el enlace. Matplotlib se importa
dentro de `guardar()` para no retrasar el arranque de la cámara.
"""

from __future__ import annotations

import statistics
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

PROJECT_DIR = Path(__file__).resolve().parents[3]

#: Orden fijo de las filas, común a los dos controladores, para que dos
#: sesiones sean comparables a simple vista. Sólo se dibujan las que aparecen;
#: un comando fuera de esta lista se añade al final, no se pierde.
ORDEN_COMANDOS = (
    "SIN_DETECCION", "NO_GESTURE", "REPOSO",
    "ADELANTE", "ATRAS", "IZQUIERDA", "DERECHA", "ARRIBA", "ABAJO",
    "DESPEGAR", "ATERRIZAR", "STOP",
    "SEGUIR_MARKER", "DETENER_SEGUIMIENTO",
)

COLORES = {
    "SIN_DETECCION": "#b0b7bd",
    "NO_GESTURE": "#b0b7bd",
    "REPOSO": "#8c959b",
    "ADELANTE": "#2878b5",
    "ATRAS": "#6baed6",
    "IZQUIERDA": "#2d8a45",
    "DERECHA": "#74c476",
    "ARRIBA": "#8e44ad",
    "ABAJO": "#c39bd3",
    "DESPEGAR": "#e38a19",
    "ATERRIZAR": "#c83b32",
    "STOP": "#7f0000",
    "SEGUIR_MARKER": "#17a2b8",
    "DETENER_SEGUIMIENTO": "#5f6f7a",
}
COLOR_OTRO = "#4a4a4a"

#: Estados del dron que se sombrean de fondo: (color, alfa). Los demás
#: («EN TIERRA», «SIMULACION») quedan en blanco.
SOMBRA_ESTADO = {
    "MANIOBRANDO": ("#e38a19", 0.16),
    "VOLANDO": ("#2d8a45", 0.10),
}

#: Duración que se asigna a la última muestra cuando no hay con qué medirla.
DT_POR_DEFECTO_S = 1.0 / 30.0

#: Transparencia con que se pinta un comando que la visión todavía no
#: confirmó. Se ve, pero se distingue del que sí movió el dron.
ALFA_SIN_CONFIRMAR = 0.32


@dataclass(frozen=True)
class Muestra:
    t: float
    comando: str
    confirmado: bool
    estado: str


@dataclass(frozen=True)
class Tramo:
    comando: str
    confirmado: bool
    inicio: float
    fin: float

    @property
    def duracion(self) -> float:
        return self.fin - self.inicio


# ------------------------------------------------------------------ cálculo


def agrupar(muestras: list[Muestra],
            clave: Callable[[Muestra], object]) -> list[tuple[object, float, float]]:
    """Tramos consecutivos con la misma `clave(muestra)`: `(valor, inicio, fin)`.

    Cada muestra cubre hasta la siguiente. La última no tiene siguiente y se
    le da el intervalo mediano de la sesión: así un comando de un solo frame
    al final no dura cero ni se inventa medio segundo.
    """
    if not muestras:
        return []
    ts = [m.t for m in muestras]
    if len(ts) > 1:
        dt = statistics.median(b - a for a, b in zip(ts, ts[1:])) or DT_POR_DEFECTO_S
    else:
        dt = DT_POR_DEFECTO_S
    fines = ts[1:] + [ts[-1] + dt]

    grupos: list[list] = []
    for muestra, fin in zip(muestras, fines):
        valor = clave(muestra)
        if grupos and grupos[-1][0] == valor:
            grupos[-1][2] = fin
        else:
            grupos.append([valor, muestra.t, fin])
    return [(valor, inicio, fin) for valor, inicio, fin in grupos]


def tramos_de_comando(muestras: list[Muestra]) -> list[Tramo]:
    """Un tramo por cada racha de `(comando, confirmado)` iguales."""
    return [
        Tramo(comando, confirmado, inicio, fin)
        for (comando, confirmado), inicio, fin
        in agrupar(muestras, lambda m: (m.comando, m.confirmado))
    ]


def tiempo_por_comando(muestras: list[Muestra]) -> dict[str, float]:
    """Segundos totales que se sostuvo cada comando, confirmado o no."""
    total: dict[str, float] = {}
    for tramo in tramos_de_comando(muestras):
        total[tramo.comando] = total.get(tramo.comando, 0.0) + tramo.duracion
    return total


def orden_de_filas(comandos: set[str]) -> list[str]:
    """Los comandos presentes, en el orden fijo; los desconocidos al final."""
    conocidos = [c for c in ORDEN_COMANDOS if c in comandos]
    otros = sorted(c for c in comandos if c not in ORDEN_COMANDOS)
    return conocidos + otros


def _color(comando: str) -> str:
    return COLORES.get(comando, COLOR_OTRO)


# ------------------------------------------------------------------- figura


def _figura(controlador: str, sesion: str, muestras: list[Muestra],
            eventos: list[tuple[float, str]]):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.patches import Patch

    # La primera fila del vocabulario va arriba: en el eje Y eso es el índice
    # más alto, de ahí la lista invertida.
    filas = list(reversed(orden_de_filas({m.comando for m in muestras})))
    indice = {comando: i for i, comando in enumerate(filas)}
    tramos = tramos_de_comando(muestras)
    totales = tiempo_por_comando(muestras)
    t0 = muestras[0].t
    t1 = max(tramo.fin for tramo in tramos)
    duracion = max(t1 - t0, 1e-3)

    fig = Figure(figsize=(13, max(3.8, 1.8 + 0.42 * len(filas))),
                 layout="constrained")
    FigureCanvasAgg(fig)
    ax = fig.subplots()

    # Estado del dron de fondo.
    estados_vistos: list[str] = []
    for estado, inicio, fin in agrupar(muestras, lambda m: m.estado):
        if estado in SOMBRA_ESTADO:
            color, alfa = SOMBRA_ESTADO[estado]
            ax.axvspan(inicio, fin, color=color, alpha=alfa, linewidth=0)
            if estado not in estados_vistos:
                estados_vistos.append(estado)

    # Comandos, un carril por fila.
    for tramo in tramos:
        y = indice[tramo.comando]
        ax.broken_barh(
            [(tramo.inicio, tramo.duracion)], (y - 0.36, 0.72),
            color=_color(tramo.comando),
            alpha=1.0 if tramo.confirmado else ALFA_SIN_CONFIRMAR,
            linewidth=0,
        )

    # Tiempo total sostenido, a la derecha de cada carril.
    for comando, y in indice.items():
        ax.text(t1 + 0.012 * duracion, y, f"{totales.get(comando, 0.0):.1f} s",
                va="center", ha="left", fontsize=8, color="#555555")

    # Eventos puntuales: emergencias y similares.
    for t, nombre in eventos:
        ax.axvline(t, color="#1f2933", linestyle="--", alpha=0.6)
        # A la izquierda de la línea, para no pisar la columna de duraciones
        # cuando el evento cae al final de la sesión, que es lo habitual.
        ax.text(t, len(filas) - 0.45, f"{nombre} ", rotation=90,
                va="top", ha="right", fontsize=8, color="#1f2933")

    ax.set_yticks(range(len(filas)), filas)
    ax.set_ylim(-0.6, len(filas) - 0.4)
    ax.set_xlim(t0 - 0.01 * duracion, t1 + 0.11 * duracion)
    ax.set_xlabel("Tiempo de sesión [s]")
    ax.grid(axis="x", alpha=0.25)
    ax.set_title(
        f"{controlador} · {sesion} · {datetime.now():%Y-%m-%d}\n"
        f"Comandos atendidos por el controlador en el tiempo "
        f"({duracion:.0f} s, {len(muestras)} frames)",
        fontsize=11,
    )

    leyenda = [
        Patch(facecolor=SOMBRA_ESTADO[e][0], alpha=min(1.0, 3 * SOMBRA_ESTADO[e][1]),
              label=f"dron {e.lower()}")
        for e in estados_vistos
    ]
    if any(not tramo.confirmado for tramo in tramos):
        leyenda.append(Patch(facecolor=COLOR_OTRO, label="comando confirmado"))
        leyenda.append(Patch(facecolor=COLOR_OTRO, alpha=ALFA_SIN_CONFIRMAR,
                             label="gesto sin confirmar"))
    if leyenda:
        ax.legend(handles=leyenda, loc="upper left", bbox_to_anchor=(1.01, 1.0),
                  fontsize=8, frameon=False)
    return fig


# ------------------------------------------------------------------ registro


class GraficaDeComandos:
    """Acumula `(t, comando)` durante la sesión y guarda la figura al cerrar.

    Args:
        controlador: nombre de la carpeta bajo `results/graphs/`. Conviene que
            sea el nombre del script, igual que hace el CSV.
        sesion: etiqueta del archivo; si falta, `sesion_HHMMSS`. Pasar la misma
            que al CSV para que los dos se emparejen a simple vista.
        raiz: raíz del repositorio. Sólo las pruebas la cambian.
        activo: con `False` no registra ni guarda nada (`--sin-grafica`).
    """

    def __init__(self, controlador: str, *, sesion: str | None = None,
                 raiz: Path | str = PROJECT_DIR, activo: bool = True) -> None:
        ahora = datetime.now()
        self.controlador = controlador
        self.sesion = sesion or ahora.strftime("sesion_%H%M%S")
        self.activo = activo
        self.carpeta = (
            Path(raiz) / "results" / "graphs" / controlador
            / ahora.strftime("%Y-%m-%d")
        )
        self.muestras: list[Muestra] = []
        self.eventos: list[tuple[float, str]] = []
        self.ruta: Path | None = None
        self._lock = threading.Lock()

    def anotar(self, t: float, comando: str, *, confirmado: bool = True,
               estado: str = "") -> None:
        """Una muestra por frame: qué comando se atendió y en qué estado."""
        if not self.activo:
            return
        with self._lock:
            self.muestras.append(
                Muestra(float(t), str(comando), bool(confirmado), str(estado))
            )

    def evento(self, t: float, nombre: str) -> None:
        """Marca vertical con etiqueta: emergencias, aterrizajes forzados."""
        if not self.activo:
            return
        with self._lock:
            self.eventos.append((float(t), str(nombre)))

    def guardar(self) -> Path | None:
        """Escribe PNG y PDF. Devuelve la ruta del PNG, o `None` si no hubo
        nada que graficar o falló. Nunca lanza."""
        if not self.activo:
            return None
        with self._lock:
            muestras = list(self.muestras)
            eventos = list(self.eventos)
        if not muestras:
            print("Gráfica de comandos: sin muestras, no se guarda.")
            return None
        try:
            self.carpeta.mkdir(parents=True, exist_ok=True)
            base = self.carpeta / f"{self.sesion}_comandos"
            fig = _figura(self.controlador, self.sesion, muestras, eventos)
            fig.savefig(base.with_suffix(".png"), dpi=150)
            fig.savefig(base.with_suffix(".pdf"))
            self.ruta = base.with_suffix(".png")
            print(f"Gráfica de comandos: {self.ruta}")
            return self.ruta
        except Exception as error:  # noqa: BLE001 - el cierre no debe romperse
            print(f"No se pudo guardar la gráfica de comandos: {error}")
            return None
