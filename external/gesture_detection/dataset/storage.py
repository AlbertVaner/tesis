"""Guardado y lectura de tomas de gestos.

Una **toma** es una repeticion de un gesto: lo que ocurre entre que el operador
arranca la grabacion y la para. Es la unidad del dataset y la unidad que DTW
compara.

Que se guarda, y por que las dos representaciones
-------------------------------------------------
Cada toma lleva `world` (`pose_world_landmarks`, metros, 3D) **y** `imagen`
(`pose_landmarks`, normalizados al encuadre, 2D). No es redundante: la pregunta
que el dataset tiene que responder es si el 2D basta, y para contestarla hace
falta el 2D **de verdad**, no una proyeccion del 3D.

Una proyeccion del 3D no sirve como linea base porque hereda el prior de
profundidad del modelo: es un 2D que ya sabe cosas que una camara sola no le
diria. Comparar contra eso favorece al 3D por construccion.

Orientacion
-----------
`orientacion_deg` es cuanto estaba girado el operador respecto de la camara.
Con una sola camara, girar al operador es exactamente equivalente a mover la
camara, y es la unica forma honesta de medir si una plantilla transfiere entre
las vistas del anillo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

VERSION = 1
N_LANDMARKS = 33


def _limpio(texto: str) -> str:
    """Un nombre utilizable como parte de un archivo."""
    t = re.sub(r"[^\w-]+", "_", texto.strip().lower(), flags=re.UNICODE)
    return t.strip("_") or "sin_nombre"


@dataclass(frozen=True)
class Toma:
    """Una repeticion de un gesto."""

    persona: str
    gesto: str
    numero: int
    orientacion_deg: float
    world: np.ndarray            #: `(T, 33, 3)` metros, centrado en la cadera
    imagen: np.ndarray           #: `(T, 33, 2)` normalizado al encuadre
    visibility: np.ndarray       #: `(T, 33)`
    timestamps: np.ndarray       #: `(T,)` segundos desde el inicio de la toma
    ruta: Path | None = None

    @property
    def n_frames(self) -> int:
        return len(self.timestamps)

    @property
    def duracion_s(self) -> float:
        if self.n_frames < 2:
            return 0.0
        return float(self.timestamps[-1] - self.timestamps[0])

    @property
    def fps(self) -> float:
        return (self.n_frames - 1) / self.duracion_s if self.duracion_s > 0 else 0.0

    @property
    def etiqueta(self) -> str:
        return f"{self.persona}/{self.gesto}#{self.numero}"

    def nombre_de_archivo(self) -> str:
        return (f"{_limpio(self.persona)}__{_limpio(self.gesto)}"
                f"__o{int(round(self.orientacion_deg)):03d}"
                f"__{self.numero:03d}.npz")


def carpeta_de_hoy(raiz: Path) -> Path:
    return raiz / "results" / "data" / "gestos" / datetime.now().strftime("%Y-%m-%d")


def guardar(carpeta: Path, toma: Toma) -> Path:
    """Escribe la toma y devuelve la ruta. No sobrescribe."""
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / toma.nombre_de_archivo()
    sufijo = 1
    while ruta.exists():
        ruta = carpeta / ruta.name.replace(".npz", f"_{sufijo}.npz")
        sufijo += 1
    np.savez_compressed(
        ruta,
        version=VERSION,
        persona=toma.persona,
        gesto=toma.gesto,
        numero=toma.numero,
        orientacion_deg=toma.orientacion_deg,
        world=np.asarray(toma.world, np.float32),
        imagen=np.asarray(toma.imagen, np.float32),
        visibility=np.asarray(toma.visibility, np.float32),
        timestamps=np.asarray(toma.timestamps, np.float64),
    )
    return ruta


def cargar(ruta: Path) -> Toma:
    d = np.load(ruta, allow_pickle=False)
    return Toma(
        persona=str(d["persona"]),
        gesto=str(d["gesto"]),
        numero=int(d["numero"]),
        orientacion_deg=float(d["orientacion_deg"]),
        world=d["world"].astype(np.float64),
        imagen=d["imagen"].astype(np.float64),
        visibility=d["visibility"].astype(np.float64),
        timestamps=d["timestamps"].astype(np.float64),
        ruta=Path(ruta),
    )


def cargar_todas(carpeta: Path, patron: str = "*.npz") -> list[Toma]:
    """Todas las tomas de una carpeta, en orden de nombre.

    Busca tambien en subcarpetas: el material de varios dias vive en carpetas
    por fecha, y evaluar sobre todo junto es lo normal.
    """
    carpeta = Path(carpeta)
    rutas = sorted(carpeta.rglob(patron)) if carpeta.is_dir() else []
    tomas = []
    for r in rutas:
        try:
            tomas.append(cargar(r))
        except Exception as error:
            print(f"AVISO: no se pudo leer {r.name}: {error}")
    return tomas


def resumen(tomas: list[Toma]) -> str:
    """Cuantas tomas hay de cada gesto, persona y orientacion."""
    if not tomas:
        return "sin tomas"
    por_gesto: dict[str, int] = {}
    por_persona: dict[str, int] = {}
    por_orientacion: dict[float, int] = {}
    for t in tomas:
        por_gesto[t.gesto] = por_gesto.get(t.gesto, 0) + 1
        por_persona[t.persona] = por_persona.get(t.persona, 0) + 1
        por_orientacion[t.orientacion_deg] = \
            por_orientacion.get(t.orientacion_deg, 0) + 1
    duracion = sum(t.duracion_s for t in tomas)
    lineas = [
        f"{len(tomas)} tomas, {duracion:.0f} s en total",
        "  gestos:       " + "  ".join(f"{g} {n}" for g, n in sorted(por_gesto.items())),
        "  personas:     " + "  ".join(f"{p} {n}" for p, n in sorted(por_persona.items())),
        "  orientacion:  " + "  ".join(f"{o:.0f} deg {n}"
                                       for o, n in sorted(por_orientacion.items())),
    ]
    return "\n".join(lineas)
