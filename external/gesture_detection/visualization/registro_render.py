"""Lo que hizo el sistema en vivo, para volver a dibujarlo despues en alta resolucion.

El reconocedor trabaja sobre el sub-stream VGA, que es lo que lo hace fluido,
y por eso la interfaz grabada en vivo se ve borrosa. Este registro guarda, con
la **hora del reloj del sistema** (`time.time()`), todo lo necesario para
recomponer esa interfaz sobre el stream principal grabado aparte
(`grabar_camaras_hd.py`, que marca cada cuadro con su hora de llegada):

* `pose`: los landmarks 2D de cada camara en cada frame procesado, normalizados
  al encuadre. Como el sub-stream y el principal ven el mismo encuadre, valen
  para dibujar el esqueleto sobre la imagen grande.
* `estado`: en cada vuelta del bucle, camara activa, gesto, si esta confirmado
  y lo que el panel ensena (estado del dron, modo, comportamiento).
* `evento`: las novedades del reconocedor (ordenes ejecutadas o ignoradas).

No se reconoce nada otra vez al renderizar: se dibuja lo que paso.
`renderizar_sesion_hd.py` lee este archivo. Formato: JSON por linea.
"""

from __future__ import annotations

import json
from pathlib import Path

NOMBRE = "render.jsonl"


def _lm(landmarks) -> list | None:
    if landmarks is None:
        return None
    return [[round(p.x, 4), round(p.y, 4), round(p.visibility, 2)] for p in landmarks]


class RegistroRender:
    """`anotar_poses(estados)` y `anotar_estado(...)` en cada vuelta; `cerrar()` al salir."""

    def __init__(self, carpeta: Path, camaras: list[str], conexiones) -> None:
        self.ruta = Path(carpeta) / NOMBRE
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self._archivo = self.ruta.open("w", encoding="utf-8")
        self._seq: dict[str, int] = {}
        self._escribir({"tipo": "inicio", "camaras": list(camaras),
                        "conexiones": sorted([int(a), int(b)] for a, b in conexiones)})

    def _escribir(self, registro: dict) -> None:
        if self._archivo is not None:
            self._archivo.write(json.dumps(registro, separators=(",", ":")) + "\n")

    def anotar_poses(self, estados: dict) -> None:
        """Una linea por cada frame nuevo de cada camara (`Estado` de `multicamara`)."""
        for nombre, estado in estados.items():
            if estado.seq == self._seq.get(nombre) or not estado.t_captura:
                continue
            self._seq[nombre] = estado.seq
            self._escribir({"tipo": "pose", "cam": nombre, "t": round(estado.t_captura, 3),
                            "senal": bool(estado.senal), "lm": _lm(estado.landmarks)})

    def anotar_estado(self, t: float, **campos) -> None:
        self._escribir({"tipo": "estado", "t": round(t, 3), **campos})

    def anotar_evento(self, t: float, texto: str, ejecutado: bool) -> None:
        self._escribir({"tipo": "evento", "t": round(t, 3), "texto": texto,
                        "ejecutado": bool(ejecutado)})

    def cerrar(self) -> None:
        if self._archivo is not None:
            self._archivo.close()
            self._archivo = None


def leer(ruta: Path) -> tuple[dict, dict[str, list], list[dict], list[dict]]:
    """`(inicio, poses por camara, estados, eventos)`, cada lista ordenada por `t`."""
    inicio: dict = {}
    poses: dict[str, list] = {}
    estados: list[dict] = []
    eventos: list[dict] = []
    with Path(ruta).open(encoding="utf-8") as archivo:
        for linea in archivo:
            linea = linea.strip()
            if not linea:
                continue
            try:
                r = json.loads(linea)
            except json.JSONDecodeError:
                continue            # ultima linea a medias si el proceso murio
            tipo = r.get("tipo")
            if tipo == "inicio":
                inicio = r
            elif tipo == "pose":
                poses.setdefault(r["cam"], []).append(r)
            elif tipo == "estado":
                estados.append(r)
            elif tipo == "evento":
                eventos.append(r)
    for lista in (*poses.values(), estados, eventos):
        lista.sort(key=lambda r: r["t"])
    return inicio, poses, estados, eventos
