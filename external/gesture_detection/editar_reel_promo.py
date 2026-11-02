"""Reel promocional para Instagram (1080x1920): informal, rapido y vistoso.

Usa el mismo material que `editar_reel.py` (sesiones, esqueleto, vista 3D del
Robotat), pero montado como contenido de redes, segun las practicas habituales
de Reels: gancho en el primer segundo, 30-35 s, texto grande que se entiende
sin sonido y dentro de la zona segura (1080x1420 centrada: arriba y abajo los
tapa la interfaz de Instagram), cortes rapidos y una pregunta al final para que
comenten. La musica se pone en la app, con un audio en tendencia: los cortes
caen en multiplos de 0.5 s para que encajen con una cancion de ~120 BPM.

Efectos, todos con OpenCV y PIL:

* `vision`: el esqueleto 2D brillando sobre el operador y la imagen oscurecida
  ("asi te ve la IA");
* `montaje`: las seis camaras en rafaga, medio segundo cada una;
* `robotat`: la vista 3D a pantalla completa (drones, operador, camaras);
* acercamiento lento (punch-in) en cada plano, destello blanco entre planos,
  velocidad 1.5x o 2x en los tramos largos y texto que entra con un pequeno rebote.

Uso, desde la raiz del repositorio:

    python .\\external\\gesture_detection\\editar_reel_promo.py

Sale `results/captures/control_camara_dron1/reel_promo_instagram.mp4`.
"""

from __future__ import annotations

import argparse
import sys
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

MODULE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = MODULE_DIR.parents[1]
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from editar_reel import MIERCOLES, SABADO, Seguidor  # noqa: E402
from editar_video_resumen import FPS, RECORTE_ABAJO, RECORTE_ARRIBA, VERDE_ROTULO, pegar, preparar  # noqa: E402
from grabar_camaras_hd import buscar_ffmpeg  # noqa: E402
from renderizar_sesion_hd import FuenteHD, SalidaH264  # noqa: E402
from visualization.escena_robotat import Vista3D, cargar_config  # noqa: E402

ANCHO, ALTO = 1080, 1920
#: Zona que no tapa la interfaz de Instagram (centrada).
ZONA_ARRIBA, ZONA_ABAJO = 260, 1660
VERDE = (60, 110, 0)               # el verde del operador (RGB 0, 68, 50), un poco mas vivo para resaltar
NEON = (120, 255, 120)
CAPTURAS = PROJECT_DIR / "results" / "captures" / "control_camara_dron1"

#: Cada plano: sesion, desde, hasta (s de la sesion), velocidad, modo, textos.
#: `textos`: (inicio, fin, texto, estilo) en segundos del plano ya acelerado.
#: Estilos: "grande" (blanco con borde), "verde" (pastilla verde), "abajo" (mas pequeno, bajo).
GUION = [
    dict(ses=SABADO, desde=11.3, hasta=13.8, vel=1.0, modo="vision",
         textos=[(0.0, 2.5, "Controlo drones\nsolo con mi cuerpo", "grande")]),
    dict(ses=SABADO, desde=11.0, hasta=14.0, vel=1.0, modo="montaje",
         textos=[(0.0, 3.0, "6 cámaras me siguen", "verde")]),
    dict(ses=SABADO, desde=13.5, hasta=17.5, vel=1.0, modo="robotat",
         textos=[(0.0, 1.5, "Hago el señalero...", "grande"), (1.5, 4.0, "¡y despegan!", "verde")]),
    dict(ses=SABADO, desde=21.8, hasta=24.8, vel=1.0, modo="camara",
         textos=[(0.0, 3.0, "Les digo \"ven acá\"...", "grande")]),
    dict(ses=SABADO, desde=24.8, hasta=30.8, vel=1.5, modo="robotat",
         textos=[(0.0, 4.0, "...y me siguen", "verde")]),
    dict(ses=SABADO, desde=40.5, hasta=43.5, vel=1.0, modo="vision",
         textos=[(0.0, 3.0, "Un círculo...", "grande")]),
    dict(ses=SABADO, desde=44.0, hasta=50.0, vel=1.5, modo="robotat",
         textos=[(0.0, 4.0, "= orbitan a mi alrededor", "verde")]),
    dict(ses=MIERCOLES, desde=80.8, hasta=92.8, vel=2.0, modo="vision",
         textos=[(0.0, 1.5, "Arriba", "verde"), (1.5, 3.0, "Derecha", "verde"),
                 (3.0, 4.5, "Izquierda", "verde"), (4.5, 6.0, "Al frente", "verde")]),
    dict(ses=MIERCOLES, desde=95.0, hasta=98.0, vel=1.0, modo="camara",
         textos=[(0.0, 1.5, "¿Y si algo falla?", "grande"), (1.5, 3.0, "¡Paro!", "verde")]),
    dict(ses=SABADO, desde=71.0, hasta=75.0, vel=1.0, modo="robotat",
         textos=[(0.0, 4.0, "Y aterrizan solos", "grande")]),
]
CIERRE_S = 3.5


# -------------------------------------------------------------------- texto


def _fuente(tamano: int) -> ImageFont.FreeTypeFont:
    for nombre in ("seguibl.ttf", "segoeuib.ttf", "arialbd.ttf"):
        ruta = Path("C:/Windows/Fonts") / nombre
        if ruta.is_file():
            return ImageFont.truetype(str(ruta), tamano)
    return ImageFont.load_default(size=tamano)


@lru_cache(maxsize=128)
def texto_borde(texto: str, tamano: int, color=(255, 255, 255), fondo=None) -> np.ndarray:
    """Texto centrado (BGRA) con borde negro grueso, o sobre una pastilla de color `fondo` (BGR)."""
    fuente = _fuente(tamano)
    lineas = texto.split("\n")
    borde = max(3, tamano // 12)
    alto_linea = int(tamano * 1.18)
    ancho = max(int(fuente.getlength(l)) for l in lineas) + 2 * borde + 8
    pad_x, pad_y = (44, 22) if fondo else (0, 0)
    img = Image.new("RGBA", (ancho + 2 * pad_x, alto_linea * len(lineas) + 2 * borde + 2 * pad_y + 8),
                    (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if fondo:
        d.rounded_rectangle([0, 0, img.width - 1, img.height - 1], radius=28,
                            fill=(fondo[2], fondo[1], fondo[0], 235))
    rgb = (color[2], color[1], color[0], 255)
    for i, linea in enumerate(lineas):
        x = pad_x + (ancho - int(fuente.getlength(linea))) // 2
        y = pad_y + borde + i * alto_linea
        d.text((x, y), linea, font=fuente, fill=rgb,
               stroke_width=0 if fondo else borde, stroke_fill=(0, 0, 0, 255))
    return np.array(img)[:, :, [2, 1, 0, 3]]


def poner_texto(lienzo, texto: str, estilo: str, edad: float, resta: float) -> None:
    """Texto con un rebote al entrar y un fundido al salir, dentro de la zona segura."""
    tamano = {"grande": 96, "verde": 84, "abajo": 60}[estilo]
    img = texto_borde(texto, tamano, fondo=VERDE if estilo == "verde" else None)
    entrada = min(1.0, edad / 0.18)
    escala = 0.6 + 0.4 * entrada + 0.08 * np.sin(np.pi * entrada)      # pequeno rebote
    opacidad = min(1.0, edad / 0.12, resta / 0.15)
    if escala != 1.0:
        img = cv2.resize(img, (max(1, int(img.shape[1] * escala)), max(1, int(img.shape[0] * escala))))
    y_centro = {"grande": 560, "verde": 1260, "abajo": 1480}[estilo]
    pegar(lienzo, img, (ANCHO - img.shape[1]) // 2, y_centro - img.shape[0] // 2, max(0.0, opacidad))


# ----------------------------------------------------------------- imagenes


def recorte(frame, centro_x: float, zoom: float):
    """`(imagen 1080x1920, caja)` del frame alrededor de `centro_x`, con `zoom` >= 1."""
    h, w = frame.shape[:2]
    y0, y1 = int(h * RECORTE_ARRIBA), int(h * (1 - RECORTE_ABAJO))
    alto = (y1 - y0) / zoom
    ancho = min(w, alto * ANCHO / ALTO)
    cy = (y0 + y1) / 2
    x0 = float(np.clip(centro_x * w - ancho / 2, 0, w - ancho))
    caja = (x0, cy - alto / 2, ancho, alto)
    xa, ya = int(caja[0]), int(caja[1])
    img = frame[ya:ya + int(alto), xa:xa + int(ancho)]
    return cv2.resize(img, (ANCHO, ALTO), interpolation=cv2.INTER_LINEAR), caja, (w, h)


def realzar(img):
    """Un poco mas de contraste y saturacion: se ve menos 'camara de vigilancia'."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * 1.25, 0, 255)
    img = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    return cv2.convertScaleAbs(img, alpha=1.12, beta=-12)


def esqueleto_neon(img, lm, conexiones, caja, tamano_frame) -> np.ndarray:
    """La imagen oscurecida con el esqueleto 2D brillando encima."""
    if not lm:
        return img
    x0, y0, cw, ch = caja
    w, h = tamano_frame
    p = np.array(lm)

    def punto(i):
        return (int((p[i, 0] * w - x0) / cw * ANCHO), int((p[i, 1] * h - y0) / ch * ALTO))

    capa = np.zeros_like(img)
    for a, b in conexiones:
        if a >= 11 and b >= 11 and p[a, 2] > 0.4 and p[b, 2] > 0.4:
            cv2.line(capa, punto(a), punto(b), NEON, 10, cv2.LINE_AA)
    for i in range(11, len(p)):
        if p[i, 2] > 0.4:
            cv2.circle(capa, punto(i), 12, (255, 255, 255), -1, cv2.LINE_AA)
    brillo = cv2.GaussianBlur(capa, (0, 0), 18)
    oscuro = (img.astype(np.float32) * 0.45).astype(np.uint8)
    return cv2.add(cv2.add(oscuro, brillo), capa)


def cierre(t: float) -> np.ndarray:
    lienzo = np.full((ALTO, ANCHO, 3), (18, 16, 14), np.uint8)
    o = min(1.0, t / 0.3)
    pegar(lienzo, texto_borde("Mi tesis", 70, (200, 200, 200)), (ANCHO - texto_borde("Mi tesis", 70).shape[1]) // 2,
          620, o)
    tit = texto_borde("Control de drones\ncon gestos del cuerpo", 92)
    pegar(lienzo, tit, (ANCHO - tit.shape[1]) // 2, 740, o)
    if t > 1.0:
        pregunta = texto_borde("¿Qué gesto le pondrías?", 66, fondo=VERDE)
        pegar(lienzo, pregunta, (ANCHO - pregunta.shape[1]) // 2, 1180, min(1.0, (t - 1.0) / 0.3))
    return lienzo


# ------------------------------------------------------------------- montaje


def renderizar_plano(plano, sesion, vista, salida, ultimo_cuadro):
    montaje, videos, _, _, desfase = sesion
    t0 = montaje.t_estados[0]
    fuentes = {n: FuenteHD(r, m) for n, (r, m) in videos.items()}
    camaras = sorted(fuentes)
    seguidor = Seguidor()
    duracion = (plano["hasta"] - plano["desde"]) / plano["vel"]
    n = int(round(duracion * FPS))
    cuadro = ultimo_cuadro
    try:
        for k in range(n):
            ts = k / FPS                                     # tiempo del plano ya acelerado
            t = t0 + plano["desde"] + ts * plano["vel"]
            frames = {nombre: f.en(t + desfase) for nombre, f in fuentes.items()}
            cam = montaje.plano(t)[0]
            if plano["modo"] == "montaje":
                cam = camaras[min(len(camaras) - 1, int(ts / 0.5))]
            zoom = 1.0 + 0.10 * ts / max(duracion, 1e-6)    # acercamiento lento
            frame = frames.get(cam)
            if plano["modo"] == "robotat" and montaje.escena is not None:
                e = montaje.escena
                drones, marker, cuerpo = e.estado(t)
                # La camara virtual mira al centro de la accion (operador y drones), no al del area.
                puntos = [d[1][0] for d in drones if d[1] is not None]
                if marker is not None:
                    puntos.append(marker[0])
                if puntos:
                    objetivo = np.mean(puntos, axis=0) * np.array([1, 1, 0]) + np.array([0, 0, 0.8])
                    vista.centro = objetivo if k == 0 else 0.92 * vista.centro + 0.08 * objetivo
                cuadro = vista.dibujar(t, drones=drones, marker=marker, cuerpo=cuerpo, camara_activa=cam,
                                       t_vista=ts, esqueleto=e.esqueleto_en(t))
                # La camara del operador en una esquina, para no perder la persona.
                if frame is not None:
                    mini, _, _ = recorte(frame, seguidor.actualizar(montaje.pose(cam, t)), 1.0)
                    mini = cv2.resize(mini, (300, 534))
                    cv2.rectangle(mini, (0, 0), (299, 533), (255, 255, 255), 6)
                    cuadro[ZONA_ARRIBA + 40:ZONA_ARRIBA + 574, ANCHO - 340:ANCHO - 40] = mini
            elif frame is not None:
                img, caja, tam = recorte(frame, seguidor.actualizar(montaje.pose(cam, t)), zoom)
                img = realzar(img)
                if plano["modo"] == "vision":
                    img = esqueleto_neon(img, montaje.pose(cam, t), montaje.conexiones, caja, tam)
                cuadro = img
            if plano["modo"] == "montaje":
                etiqueta = texto_borde(cam.replace("cam", "Cámara "), 46)
                pegar(cuadro, etiqueta, 60, ZONA_ARRIBA + 30)
            cuadro = cuadro.copy()
            for ini, fin, texto, estilo in plano["textos"]:
                if ini <= ts < fin:
                    poner_texto(cuadro, texto, estilo, ts - ini, fin - ts)
            # Destello blanco al empezar cada plano (y cada camara del montaje).
            destello = max(0.0, 1.0 - (ts % 0.5 if plano["modo"] == "montaje" else ts) / 0.12)
            if destello > 0:
                cuadro = cv2.addWeighted(cuadro, 1 - 0.6 * destello, np.full_like(cuadro, 255), 0.6 * destello, 0)
            salida.escribir(cuadro)
    finally:
        for f in fuentes.values():
            f.cerrar()
    return cuadro


def main() -> int:
    parser = argparse.ArgumentParser(description="Reel promocional para Instagram, vertical e informal.")
    parser.add_argument("--desfase", type=float, default=-0.10)
    parser.add_argument("--salida", type=Path, default=CAPTURAS / "reel_promo_instagram.mp4")
    args = parser.parse_args()
    ffmpeg = buscar_ffmpeg()
    opciones = SimpleNamespace(sin_escena=False, desfase=str(args.desfase))
    sesiones = {}
    for plano in GUION:
        if plano["ses"] not in sesiones:
            sesiones[plano["ses"]] = preparar(plano["ses"], opciones, ffmpeg)
            if sesiones[plano["ses"]] is None:
                return 1
    vista = Vista3D(cargar_config(), ANCHO, ALTO, distancia_m=7.0, elevacion_deg=32.0, giro_deg_por_s=8.0)
    salida = SalidaH264(ffmpeg, args.salida, FPS, tamano=(ANCHO, ALTO))
    cuadro = np.zeros((ALTO, ANCHO, 3), np.uint8)
    try:
        for plano in GUION:
            print(f"{plano['ses'].name} {plano['desde']:.1f}-{plano['hasta']:.1f} s ({plano['modo']})", flush=True)
            cuadro = renderizar_plano(plano, sesiones[plano["ses"]], vista, salida, cuadro)
        for k in range(int(CIERRE_S * FPS)):
            salida.escribir(cierre(k / FPS))
    finally:
        salida.cerrar()
    print(f"Reel: {salida.ruta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
