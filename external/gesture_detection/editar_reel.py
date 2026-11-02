"""Reel con lo mas relevante de las sesiones: vertical para redes, horizontal para una TV.

Reutiliza el montaje de `editar_video_resumen.py` (sesiones, planos de camara,
rotulos, esqueleto 3D y vista del Robotat) y lo compone en dos formatos con el
mismo contenido:

* `vertical` (1080x1920), para redes: la camara arriba y el Robotat abajo;
* `horizontal` (1920x1080), para una pantalla del laboratorio: la camara a la
  izquierda y el Robotat a la derecha.

En los dos, la camara activa va **recortada siguiendo al operador** (el centro
de la cadera en el esqueleto 2D), sin la fecha que imprime la camara. El panel
muestra el Robotat en 3D con los drones, el marker y el esqueleto del operador
si la sesion tiene vuelo real; si el dron era simulado, el esqueleto en grande.
El gesto reconocido va en una pastilla y, solo si volaron drones de verdad,
tambien la accion en verde.

Los tramos se eligen a mano en `TRAMOS` (sesion, desde, hasta, en segundos de
la sesion) y se encadenan con un fundido corto.

Uso, desde la raiz del repositorio:

    python .\\external\\gesture_detection\\editar_reel.py --formato vertical
    python .\\external\\gesture_detection\\editar_reel.py --formato horizontal

Sale `results/captures/control_camara_dron1/reel_gestos_<formato>.mp4`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

MODULE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = MODULE_DIR.parents[1]
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from editar_video_resumen import (  # noqa: E402
    ACENTO, BLANCO, FONDO_PANEL, FPS, GRIS, RECORTE_ABAJO, RECORTE_ARRIBA, VERDE_ROTULO,
    cuadro_esqueleto, pegar, preparar, rectangulo, rotulo_en, texto_rgba,
)
from grabar_camaras_hd import buscar_ffmpeg  # noqa: E402
from renderizar_sesion_hd import FuenteHD, SalidaH264  # noqa: E402
from visualization.escena_robotat import Vista3D, cargar_config  # noqa: E402

#: Por formato: lienzo y rectangulos `(x, y, ancho, alto)` de la camara y del panel del Robotat.
FORMATOS = {
    "vertical": {"lienzo": (1080, 1920), "camara": (0, 0, 1080, 1150), "panel": (0, 1154, 1080, 766)},
    "horizontal": {"lienzo": (1920, 1080), "camara": (0, 0, 1150, 1080), "panel": (1154, 0, 766, 1080)},
}
FUNDIDO_S = 0.35
PORTADA_S = 2.6

CAPTURAS = PROJECT_DIR / "results" / "captures" / "control_camara_dron1"
MIERCOLES = CAPTURAS / "2026-10-28" / "sesion_120609"     # dron simulado
SABADO = CAPTURAS / "2026-10-31" / "sesion_110018"        # Dron 1 y Dron 2 volando
ARCO = CAPTURAS / "2026-10-28" / "sesion_114330"          # el arco, reconocido (dron simulado en el suelo)

#: (sesion, desde, hasta[, camara fija]) en segundos de la sesion: lo mas relevante, en orden.
TRAMOS = [
    (SABADO, 11.0, 20.0),       # senalero -> despegan los dos
    (SABADO, 21.8, 30.0),       # ven aca -> te siguen
    (SABADO, 41.0, 50.0),       # circulo -> orbitan
    (SABADO, 62.5, 69.5),       # caminando con los drones detras
    (MIERCOLES, 80.5, 93.0),    # gestos del brazo
    (ARCO, 4.5, 10.5, "cam6"),  # arco, de frente en cam6
    (MIERCOLES, 25.3, 29.6),    # aplauso: cambio de modo
    (MIERCOLES, 94.8, 98.6),    # brazos en X: paro
    (SABADO, 70.5, 76.0),       # senalero -> aterrizan
]
PORTADA = "Control de drones\ncon gestos del cuerpo"


class Seguidor:
    """Centro horizontal del recorte: la cadera del operador, suavizada."""

    def __init__(self) -> None:
        self.x = 0.5

    def actualizar(self, lm) -> float:
        if lm:
            p = np.array(lm)
            if p[[23, 24], 2].min() > 0.4:
                self.x = 0.85 * self.x + 0.15 * float(p[[23, 24], 0].mean())
        return self.x


def recortar(frame, centro_x: float, ancho: int, alto: int):
    """La franja del frame alrededor de `centro_x` con la proporcion `ancho`:`alto`, sin la fecha ni el "IPC"."""
    if frame is None:
        return np.full((alto, ancho, 3), FONDO_PANEL, np.uint8)
    h, w = frame.shape[:2]
    y0, y1 = int(h * RECORTE_ARRIBA), int(h * (1 - RECORTE_ABAJO))
    cw = min(w, int((y1 - y0) * ancho / alto))
    x0 = int(np.clip(centro_x * w - cw / 2, 0, w - cw))
    return cv2.resize(frame[y0:y1, x0:x0 + cw], (ancho, alto), interpolation=cv2.INTER_AREA)


def pastilla(lienzo, texto: str, tamano: int, y: int, fondo, opacidad: float, x_centro: int) -> None:
    """Texto centrado en `x_centro` dentro de una pastilla de color."""
    t = texto_rgba(texto, tamano, BLANCO, negrita=True)
    w, h = t.shape[1] + 56, t.shape[0] + 26
    x = x_centro - w // 2
    rectangulo(lienzo, x, y, x + w, y + h, fondo, 0.9 * opacidad)
    pegar(lienzo, t, x + 28, y + 10, opacidad)


def componer(montaje, t: float, frames: dict, seguidor: Seguidor, vista: Vista3D,
             formato: dict) -> np.ndarray:
    ancho, alto = formato["lienzo"]
    cx, cy, cw, ch = formato["camara"]
    px, py, pw, ph = formato["panel"]
    lienzo = np.full((alto, ancho, 3), FONDO_PANEL, np.uint8)
    cam, anterior, peso = montaje.plano(t)
    centro = seguidor.actualizar(montaje.pose(cam, t))
    imagen = recortar(frames.get(cam), centro, cw, ch)
    if anterior is not None:
        suave = peso * peso * (3 - 2 * peso)
        imagen = cv2.addWeighted(recortar(frames.get(anterior), centro, cw, ch), 1 - suave, imagen, suave, 0)
    lienzo[cy:cy + ch, cx:cx + cw] = imagen
    if px == 0:      # panel debajo: linea horizontal; panel al lado: vertical
        cv2.line(lienzo, (0, py - 2), (ancho, py - 2), ACENTO, 4)
    else:
        cv2.line(lienzo, (px - 2, 0), (px - 2, alto), ACENTO, 4)

    escena = montaje.escena
    con_drones = escena is not None and bool(escena.drones)
    if con_drones:
        drones, marker, cuerpo = escena.estado(t)
        lienzo[py:py + ph, px:px + pw] = vista.dibujar(
            t, drones=drones, marker=marker, cuerpo=cuerpo, camara_activa=cam,
            t_vista=t - montaje.t_estados[0], esqueleto=escena.esqueleto_en(t))
        pegar(lienzo, texto_rgba("Robotat · drones y operador en 3D", 26, GRIS), px + 32, py + 22)
    else:
        lado = min(pw - 120, ph - 140)
        cuerpo = cuadro_esqueleto(montaje.pose(cam, t), montaje.conexiones, lado, lado)
        pegar(lienzo, cuerpo, px + (pw - lado) // 2, py + 80 + (ph - 80 - lado) // 2)
        pegar(lienzo, texto_rgba("Esqueleto detectado", 26, GRIS), px + 32, py + 22)

    # El gesto y, si hubo vuelo real, la accion en grande, abajo en la camara.
    rotulo, opacidad = rotulo_en(montaje.rotulos, t)
    if rotulo is not None:
        _, _, _, nombre, accion = rotulo
        centro_x, base = cx + cw // 2, cy + ch
        if con_drones and accion:
            pastilla(lienzo, accion, 52, base - 190, VERDE_ROTULO, opacidad, centro_x)
            pastilla(lienzo, nombre, 30, base - 260, (40, 40, 40), opacidad * 0.9, centro_x)
        else:
            pastilla(lienzo, nombre, 52, base - 150, VERDE_ROTULO, opacidad, centro_x)
    return lienzo


def portada(t: float, formato: dict) -> np.ndarray:
    ancho, alto = formato["lienzo"]
    lienzo = np.full((alto, ancho, 3), (16, 14, 12), np.uint8)
    o = min(1.0, t / 0.5, (PORTADA_S - t) / 0.5)
    tit = texto_rgba(PORTADA, 84, BLANCO, negrita=True, interlineado=1.2, centrado=True)
    y = alto // 2 - tit.shape[0] // 2 - 20
    pegar(lienzo, tit, (ancho - tit.shape[1]) // 2, y, o)
    cv2.line(lienzo, (ancho // 2 - 90, y + tit.shape[0] + 36), (ancho // 2 + 90, y + tit.shape[0] + 36),
             tuple(int(c * o) for c in ACENTO), 5, cv2.LINE_AA)
    return lienzo


def main() -> int:
    parser = argparse.ArgumentParser(description="Reel con lo mas relevante de las sesiones.")
    parser.add_argument("--formato", choices=sorted(FORMATOS), default="vertical",
                        help="vertical (redes, 1080x1920) u horizontal (TV, 1920x1080)")
    parser.add_argument("--desfase", type=float, default=-0.10)
    parser.add_argument("--salida", type=Path)
    args = parser.parse_args()
    formato = FORMATOS[args.formato]
    ruta = args.salida or CAPTURAS / f"reel_gestos_{args.formato}.mp4"

    ffmpeg = buscar_ffmpeg()
    opciones = SimpleNamespace(sin_escena=False, desfase=str(args.desfase))
    sesiones = {}
    for carpeta, *_ in TRAMOS:
        if carpeta not in sesiones:
            sesiones[carpeta] = preparar(carpeta, opciones, ffmpeg)
            if sesiones[carpeta] is None:
                return 1
    _, _, pw, ph = formato["panel"]
    vista = Vista3D(cargar_config(), pw, ph, distancia_m=9.0 if pw > ph else 10.5,
                    elevacion_deg=36.0, giro_deg_por_s=1.5)
    salida = SalidaH264(ffmpeg, ruta, FPS, tamano=formato["lienzo"])
    try:
        for k in range(int(PORTADA_S * FPS)):
            salida.escribir(portada(k / FPS, formato))
        for carpeta, desde, hasta, *fija in TRAMOS:
            montaje, videos, _, _, desfase = sesiones[carpeta]
            montaje.camara_fija = fija[0] if fija else None
            t0 = montaje.t_estados[0]
            fuentes = {n: FuenteHD(r, m) for n, (r, m) in videos.items()}
            seguidor = Seguidor()
            n = int((hasta - desde) * FPS)
            print(f"{carpeta.name} {desde:.0f}-{hasta:.0f} s", flush=True)
            try:
                for k in range(n):
                    t = t0 + desde + k / FPS
                    frames = {nombre: f.en(t + desfase) for nombre, f in fuentes.items()}
                    cuadro = componer(montaje, t, frames, seguidor, vista, formato)
                    nivel = min(1.0, k / (FUNDIDO_S * FPS), (n - 1 - k) / (FUNDIDO_S * FPS))
                    if nivel < 1.0:
                        cuadro = (cuadro.astype(np.float32) * max(0.0, nivel)).astype(np.uint8)
                    salida.escribir(cuadro)
            finally:
                for f in fuentes.values():
                    f.cerrar()
    finally:
        salida.cerrar()
    print(f"Reel: {salida.ruta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
