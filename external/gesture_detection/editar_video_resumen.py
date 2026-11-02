"""Video resumen de una sesion: el operador en HD, los gestos rotulados y el esqueleto aparte.

Parte de lo mismo que `renderizar_sesion_hd.py` (los `camN_hd.mkv` con la hora
de llegada de cada cuadro y el `render.jsonl` de la sesion), pero en vez de la
interfaz de trabajo monta un video para presentar:

* la imagen HD **limpia** de la camara activa a pantalla completa, sin nada
  dibujado encima del operador;
* cuando el operador se mueve y cambia la camara activa, un **fundido** de
  `TRANSICION_S` entre las dos. Los planos de menos de `PLANO_MIN_S` se
  absorben en el anterior, para que no haya cortes nerviosos;
* abajo a la derecha, un cuadro con el **esqueleto** que el sistema detecto en
  esa camara, reencuadrado sobre el cuerpo;
* un rotulo formal (tercio inferior) con cada gesto reconocido y la orden que
  produjo, el modo arriba a la derecha y la camara arriba a la izquierda;
* una portada con el titulo y un fundido de entrada y de salida.

No reconoce nada otra vez: rotula lo que el sistema hizo en vivo. Los gestos
estaticos que llegan en modo dinamico no producen orden, y asi se rotulan.

Uso, desde la raiz del repositorio:

    python .\\external\\gesture_detection\\editar_video_resumen.py results\\captures\\control_camara_dron1\\2026-10-28\\sesion_120609
    python .\\external\\gesture_detection\\editar_video_resumen.py <carpeta> --desde 10 --hasta 30 --sin-portada
    python .\\external\\gesture_detection\\editar_video_resumen.py <sesion 1> <sesion 2>   # una tras otra

Sale `<carpeta>/resumen_gestos.mp4` (1920x1080, 30 fps, H.264).
"""

from __future__ import annotations

import argparse
import bisect
import json
import re
import sys
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

MODULE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = MODULE_DIR.parents[1]
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from grabar_camaras_hd import buscar_ffmpeg  # noqa: E402
from reconstruir_cuerpo import cargar as cargar_cuerpo  # noqa: E402
from renderizar_sesion_hd import (  # noqa: E402
    POSE_VALIDA_S, FuenteHD, SalidaH264, _ffprobe, estimar_desfase, marcas_de_tiempo,
)
from visualization.escena_robotat import (  # noqa: E402
    COLORES_DRON, MARKER, Serie, Vista3D, cargar_config, cuerpo_desde_marker, icono_ip, icono_optitrack,
    drones_de_la_sesion, eventos_de_drones, marker_de_la_sesion, tramos_con_drones,
)
from visualization.registro_render import NOMBRE as REGISTRO, leer  # noqa: E402

ANCHO, ALTO = 1920, 1080
FPS = 30.0
TRANSICION_S = 0.8
PLANO_MIN_S = 2.0
ROTULO_S = 3.4
#: El sistema confirma un gesto dinamico al **terminar** el movimiento. El
#: rotulo se adelanta al inicio del movimiento (velocidad de las munecas en el
#: esqueleto), entre estos limites, y se queda `TRAS_GESTO_S` despues.
ANTES_MIN_S, ANTES_MAX_S = 1.0, 4.0
TRAS_GESTO_S = 2.2
#: Velocidad de munecas, en anchos de imagen por segundo, que cuenta como movimiento.
MOVIMIENTO_MIN = 0.12
APARECER_S = 0.35
PORTADA_S = 5.0
FUNDIDO_S = 0.8

TITULO = "Control de drones basado en gestos mediante\ncaptura de movimiento en el ecosistema Robotat"

# Colores en BGR, sobrios: blanco, gris y un solo acento, verde.
BLANCO = (245, 245, 245)
GRIS = (175, 175, 175)
ACENTO = (80, 125, 0)
#: Fondo de los rotulos emergentes.
VERDE_ROTULO = (50, 68, 0)          # RGB (0, 68, 50), el que eligio el operador
FONDO_PANEL = (24, 22, 20)
TEXTO_LEYENDA = (205, 205, 205)
#: Columna derecha: ancho de los dos recuadros y alto de cada uno.
ANCHO_CUADRO = 360
ALTO_3D = 300
ALTO_ESQUELETO = 210
#: Las Amcrest imprimen fecha y hora arriba a la derecha e "IPC" abajo a la
#: izquierda. Se recortan estas fracciones arriba y abajo, lo proporcional a
#: los lados, y se vuelve a ampliar.
RECORTE_ARRIBA, RECORTE_ABAJO = 0.09, 0.04
#: Dentro del recuadro 3D: franja del titulo y de la leyenda (dos filas).
ARRIBA_3D, LEYENDA_3D = 30, 48

#: Gesto dinamico (y el paro) -> (categoria, nombre, accion por orden).
DINAMICOS = {
    "senalero": ("GESTO DINÁMICO", "Señalero", {"DESPEGAR": "Despegar", "ATERRIZAR": "Aterrizar"}),
    "ven_aca": ("GESTO DINÁMICO", "Ven acá", {"SEGUIR": "Seguir al operador"}),
    "circulo": ("GESTO DINÁMICO", "Círculo", {"ORBITAR": "Orbitar alrededor del operador"}),
    "arco": ("GESTO DINÁMICO", "Arco", {"PIRUETA": "Pirueta"}),
    "aplaudir": ("CAMBIO DE MODO", "Aplauso", {"MODO ESTATICO": "Pasa a modo estático",
                                               "MODO DINAMICO": "Pasa a modo dinámico"}),
    "X sobre la cabeza": ("SEGURIDAD", "Brazos en X sobre la cabeza", {"PARO": "Paro de emergencia"}),
}

#: Gesto estatico -> (nombre, accion en modo estatico).
ESTATICOS = {
    "ARRIBA": ("Brazo arriba", "Ascender"),
    "ABAJO": ("Brazo abajo", "Descender"),
    "ADELANTE": ("Brazo al frente", "Avanzar hacia donde mira el operador"),
    "ATRAS": ("Brazo atrás", "Retroceder"),
    "IZQUIERDA": ("Brazo a la izquierda", "Desplazarse a la izquierda"),
    "DERECHA": ("Brazo a la derecha", "Desplazarse a la derecha"),
}


# -------------------------------------------------------------------- texto


def _fuente(negrita: bool, tamano: int) -> ImageFont.FreeTypeFont:
    carpeta = Path("C:/Windows/Fonts")
    nombres = ("segoeuib.ttf", "arialbd.ttf") if negrita else ("segoeui.ttf", "arial.ttf")
    for nombre in nombres:
        if (carpeta / nombre).is_file():
            return ImageFont.truetype(str(carpeta / nombre), tamano)
    return ImageFont.load_default(size=tamano)


@lru_cache(maxsize=256)
def texto_rgba(texto: str, tamano: int, color=BLANCO, negrita=False, interlineado=1.25,
               centrado=False) -> np.ndarray:
    """El texto renderizado (BGRA), recortado a su tamano; `centrado` centra cada linea. Cacheado."""
    fuente = _fuente(negrita, tamano)
    lineas = texto.split("\n")
    alto_linea = int(tamano * interlineado)
    ancho = max(int(fuente.getlength(l)) for l in lineas) + 4
    img = Image.new("RGBA", (ancho, alto_linea * len(lineas) + 4), (0, 0, 0, 0))
    dibujo = ImageDraw.Draw(img)
    rgb = (color[2], color[1], color[0])
    for i, linea in enumerate(lineas):
        x = (ancho - int(fuente.getlength(linea))) // 2 if centrado else 2
        dibujo.text((x, i * alto_linea), linea, font=fuente, fill=rgb + (255,))
    rgba = np.array(img)
    return rgba[:, :, [2, 1, 0, 3]]


def pegar(lienzo, bgra: np.ndarray, x: int, y: int, opacidad: float = 1.0) -> None:
    """Mezcla `bgra` en `lienzo` con su alfa por `opacidad`, recortando a los bordes."""
    h, w = bgra.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(lienzo.shape[1], x + w), min(lienzo.shape[0], y + h)
    if x0 >= x1 or y0 >= y1 or opacidad <= 0:
        return
    parche = bgra[y0 - y:y1 - y, x0 - x:x1 - x]
    a = parche[:, :, 3:4].astype(np.float32) / 255.0 * opacidad
    zona = lienzo[y0:y1, x0:x1].astype(np.float32)
    lienzo[y0:y1, x0:x1] = (zona * (1 - a) + parche[:, :, :3].astype(np.float32) * a).astype(np.uint8)


def rectangulo(lienzo, x0, y0, x1, y1, color, opacidad: float) -> None:
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(lienzo.shape[1], x1), min(lienzo.shape[0], y1)
    if x0 >= x1 or y0 >= y1 or opacidad <= 0:
        return
    zona = lienzo[y0:y1, x0:x1].astype(np.float32)
    lienzo[y0:y1, x0:x1] = (zona * (1 - opacidad) + np.array(color, np.float32) * opacidad).astype(np.uint8)


# ------------------------------------------------------------------ planos


def planos(estados: list[dict], camaras: list[str], minimo_s: float = PLANO_MIN_S) -> list[tuple[float, str]]:
    """`[(inicio, camara)]`: la camara activa sin planos de menos de `minimo_s`.

    Un plano corto se queda en la camara anterior: el operador cruzando entre
    dos camaras no debe producir tres fundidos seguidos.
    """
    tramos: list[list] = []
    for e in estados:
        cam = e.get("activa")
        if cam not in camaras:
            continue
        if tramos and tramos[-1][1] == cam:
            continue
        tramos.append([e["t"], cam])
    if not tramos:
        return [(estados[0]["t"] if estados else 0.0, camaras[0])]
    fin = estados[-1]["t"]
    limpios: list[list] = []
    for i, (t, cam) in enumerate(tramos):
        siguiente = tramos[i + 1][0] if i + 1 < len(tramos) else fin
        if limpios and siguiente - t < minimo_s:
            continue                            # se absorbe en el plano anterior
        if limpios and limpios[-1][1] == cam:
            continue
        limpios.append([t, cam])
    return [(t, cam) for t, cam in limpios]


# ----------------------------------------------------------------- rotulos


def rotulos(estados: list[dict], eventos: list[dict], inicio_movimiento=None) -> list[tuple]:
    """`[(inicio, fin, categoria, nombre, accion)]` de lo que el sistema reconocio y ordeno.

    `inicio_movimiento(t)` da cuando empezo el movimiento que se confirmo en
    `t`; sin ella, el rotulo empieza `ANTES_MIN_S` antes.
    """
    salida = []
    for e in eventos:
        # Reconocido pero ignorado ("arco ignorado: en el suelo"): se dice el
        # gesto, sin accion, porque no la hubo.
        ignorado = re.match(r"(\w+) ignorado:", e["texto"])
        if ignorado and ignorado.group(1) in DINAMICOS:
            categoria, nombre, _ = DINAMICOS[ignorado.group(1)]
            t = e["t"]
            inicio = inicio_movimiento(t) if inicio_movimiento is not None else t - ANTES_MIN_S
            salida.append((inicio, t + TRAS_GESTO_S, categoria, nombre, ""))
            continue
        m = re.match(r"(.+?) -> (.+)$", e["texto"])
        if not m:
            continue
        gesto, orden = m.group(1).strip(), m.group(2).strip()
        if gesto in DINAMICOS:
            categoria, nombre, acciones = DINAMICOS[gesto]
            t = e["t"]
            if gesto == "X sobre la cabeza" or inicio_movimiento is None:
                inicio = t - ANTES_MIN_S            # el paro es una postura: se confirma al segundo
            else:
                inicio = inicio_movimiento(t)
            salida.append((inicio, t + TRAS_GESTO_S, categoria, nombre,
                           acciones.get(orden, orden.capitalize())))
    previo, ultimo = None, {}
    for e in estados:
        g = e.get("gesto")
        confirmado = bool(e.get("confirmado"))
        if confirmado and g in ESTATICOS and g != previo:
            nombre, accion = ESTATICOS[g]
            t = e["t"]
            if t - ultimo.get(g, -1e9) > 6.0:      # la misma direccion repetida, una vez
                # Tambien en modo dinamico, donde la direccion se reconoce pero
                # no mueve el dron. ABAJO en modo dinamico no: es por donde pasan
                # los brazos en reposo y al caminar.
                if e.get("modo") == "estatico" or g != "ABAJO":
                    salida.append((t - 0.5, t + ROTULO_S, "GESTO ESTÁTICO", nombre, accion))
                ultimo[g] = t
        previo = g if confirmado else (None if g == "NO_GESTURE" else previo)
    # Un brazo que pasa por arriba al dibujar un circulo no es el gesto ARRIBA:
    # los estaticos que caen dentro de un gesto dinamico no se rotulan.
    dinamicos = [(r[0], r[1]) for r in salida if r[2] != "GESTO ESTÁTICO"]
    salida = [r for r in salida
              if r[2] != "GESTO ESTÁTICO" or not any(a - 2.0 <= r[0] + 0.5 <= b for a, b in dinamicos)]
    salida.sort()
    # Un estatico encima de otro estatico: el segundo sustituye al primero.
    limpios = []
    for r in salida:
        if limpios and r[0] - limpios[-1][0] < 1.2 and r[2] == limpios[-1][2] == "GESTO ESTÁTICO":
            limpios[-1] = r
            continue
        limpios.append(r)
    return limpios


def rotulo_en(lista, t: float):
    """`(rotulo, opacidad)` del rotulo visible en `t`, o `(None, 0)`.

    Si dos se solapan, el siguiente corta al anterior.
    """
    i = bisect.bisect_right([r[0] for r in lista], t) - 1
    if i < 0:
        return None, 0.0
    r = lista[i]
    fin = r[1]
    if i + 1 < len(lista):
        fin = min(fin, lista[i + 1][0])
    if t > fin:
        return None, 0.0
    opacidad = min(1.0, (t - r[0]) / APARECER_S, (fin - t) / APARECER_S)
    return r, max(0.0, opacidad)


# ---------------------------------------------------------------- esqueleto


def cuadro_esqueleto(lm, conexiones, ancho: int, alto: int, aspecto: float = 16 / 9):
    """El esqueleto reencuadrado sobre el cuerpo, en un BGRA de `ancho` x `alto`."""
    img = np.zeros((alto, ancho, 4), np.uint8)
    if not lm:
        return img
    p = np.array(lm, dtype=float)
    vis = p[:, 2] > 0.4
    if vis.sum() < 6:
        return img
    xy = np.stack([p[:, 0] * aspecto, p[:, 1]], axis=1)   # proporciones reales de la escena
    caja = xy[vis]
    (x0, y0), (x1, y1) = caja.min(axis=0), caja.max(axis=0)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    lado = max(x1 - x0, (y1 - y0) * ancho / alto) * 1.25 + 1e-6
    escala = ancho / lado

    def punto(i):
        return (int(ancho / 2 + (xy[i, 0] - cx) * escala), int(alto / 2 + (xy[i, 1] - cy) * escala))

    capa = np.zeros((alto, ancho, 3), np.uint8)
    for a, b in conexiones:
        if a >= 11 and b >= 11 and vis[a] and vis[b]:
            cv2.line(capa, punto(a), punto(b), BLANCO, 3, cv2.LINE_AA)
    for i in range(11, len(p)):
        if vis[i]:
            cv2.circle(capa, punto(i), 4, ACENTO, -1, cv2.LINE_AA)
    if vis[0] and vis[11] and vis[12]:
        radio = max(6, int(np.linalg.norm(xy[11] - xy[12]) * escala * 0.32))
        cv2.circle(capa, punto(0), radio, BLANCO, 2, cv2.LINE_AA)
        hombros = ((punto(11)[0] + punto(12)[0]) // 2, (punto(11)[1] + punto(12)[1]) // 2)
        cv2.line(capa, hombros, (punto(0)[0], punto(0)[1] + radio), BLANCO, 3, cv2.LINE_AA)
    img[:, :, :3] = capa
    img[:, :, 3] = (capa.max(axis=2) > 0).astype(np.uint8) * 255
    return img


# ------------------------------------------------------------------- montaje


class Escena:
    """Lo que necesita la vista 3D: drones, marker 65 y cuerpo del operador.

    `tramos`: cuando la vista 3D pasa a pantalla completa. En las camaras los
    Crazyflie son unos pocos pixeles (las PTZ encuadran al operador), asi que al
    despegar y al empezar a seguir se ensena el Robotat y la camara pasa al
    recuadro.
    """

    def __init__(self, vista: Vista3D, drones: list[Serie], marker: Serie | None,
                 tramos: list[tuple[float, float]] = (), vista_grande: Vista3D | None = None,
                 esqueleto=None) -> None:
        self.vista = vista
        self.vista_grande = vista_grande
        self.drones = drones
        self.marker = marker
        self.cuerpo = cuerpo_desde_marker(marker) if marker is not None else None
        self.tramos = list(tramos)
        #: `(t_unix, lm, vis, conexiones)` de `reconstruir_cuerpo.py`, o `None`.
        self.esqueleto = esqueleto

    def peso_grande(self, t: float) -> float:
        """0 en la camara, 1 en la vista 3D grande, con fundido de `TRANSICION_S`."""
        for a, b in self.tramos:
            if a - TRANSICION_S < t < b + TRANSICION_S:
                p = min(1.0, (t - (a - TRANSICION_S)) / TRANSICION_S, ((b + TRANSICION_S) - t) / TRANSICION_S)
                p = max(0.0, p)
                return p * p * (3 - 2 * p)
        return 0.0

    def estado(self, t: float):
        drones = [(s.nombre, s.en(t), s.estela(t)) for s in self.drones]
        marker = self.marker.en(t) if self.marker is not None else None
        cuerpo = self.cuerpo.en(t) if self.cuerpo is not None and marker is not None else None
        return drones, marker, cuerpo

    def esqueleto_en(self, t: float):
        """`(lm, vis, conexiones)` reconstruido mas cercano a `t`, si hay uno a menos de 0.3 s."""
        if self.esqueleto is None:
            return None
        ts, lm, vis, conexiones = self.esqueleto
        i = int(np.clip(np.searchsorted(ts, t), 1, len(ts) - 1))
        i = i if abs(ts[i] - t) < abs(ts[i - 1] - t) else i - 1
        return (lm[i], vis[i], conexiones) if abs(ts[i] - t) < 0.3 else None


class Montaje:
    def __init__(self, inicio, poses, estados, eventos, escena: Escena | None = None) -> None:
        self.escena = escena
        self.camaras = inicio.get("camaras") or sorted(poses)
        self.conexiones = [tuple(c) for c in inicio.get("conexiones", [])]
        self.poses = poses
        self.t_poses = {n: [p["t"] for p in ps] for n, ps in poses.items()}
        self.estados = estados
        self.t_estados = [e["t"] for e in estados]
        self.planos = planos(estados, self.camaras)
        self.t_planos = [t for t, _ in self.planos]
        self.rotulos = rotulos(estados, eventos, self.inicio_movimiento)

    def _dibujar_escena(self, lienzo, t: float, x: int, y: int, w: int, h: int,
                        camara=None, peso_camara: float = 0.0) -> None:
        """Recuadro del Robotat. Con `peso_camara` > 0 muestra (fundida) la `camara` en su lugar."""
        e = self.escena
        rectangulo(lienzo, x, y, x + w, y + h, FONDO_PANEL, 0.82)
        cv2.rectangle(lienzo, (x, y), (x + w - 1, y + h - 1), (90, 90, 90), 1, cv2.LINE_AA)
        titulo = "Cámara del operador" if peso_camara > 0.5 else "Robotat · posiciones del mocap"
        pegar(lienzo, texto_rgba(titulo, 17, GRIS), x + 12, y + 8)
        zona_alto = h - ARRIBA_3D - LEYENDA_3D
        zona = (w - 2, zona_alto)
        img = np.zeros((zona_alto, w - 2, 3), np.uint8)
        if peso_camara < 1.0:
            drones, marker, cuerpo = e.estado(t)
            img = cv2.resize(e.vista.dibujar(t, drones=drones, marker=marker, cuerpo=cuerpo,
                                             camara_activa=self.plano(t)[0], t_vista=t - self.t_estados[0],
                                             esqueleto=e.esqueleto_en(t)),
                             zona)
        if peso_camara > 0.0 and camara is not None:
            img = cv2.addWeighted(img, 1 - peso_camara, _encajar_en(camara, zona), peso_camara, 0)
        lienzo[y + ARRIBA_3D:y + ARRIBA_3D + zona_alto, x + 1:x + w - 1] = img
        if peso_camara <= 0.5:
            self._leyenda(lienzo, x + 12, y + h - LEYENDA_3D + 4, 15)

    def _leyenda(self, lienzo, x: int, y: int, tamano: int) -> None:
        """Dos filas: lo que se mueve arriba y las camaras abajo, con los mismos iconos de la vista."""
        e = self.escena

        def item(lx, ly, dibujar, texto):
            dibujar(lx + 7, ly + tamano // 2 + 1)
            etiqueta = texto_rgba(texto, tamano, TEXTO_LEYENDA)
            pegar(lienzo, etiqueta, lx + 18, ly)
            return lx + 30 + etiqueta.shape[1]

        def punto(color):
            return lambda cx, cy: cv2.circle(lienzo, (cx, cy), 5, color, -1, cv2.LINE_AA)

        lx = x
        for k, s in enumerate(e.drones):
            lx = item(lx, y, punto(COLORES_DRON[k % len(COLORES_DRON)]), s.nombre.replace("Dron", "Dron "))
        if e.marker is not None:
            item(lx, y, punto(MARKER), "Operador (marker)")
        y += int(tamano * 1.4)
        lx = item(x, y, lambda cx, cy: icono_optitrack(lienzo, (cx, cy)), "Cámaras OptiTrack")
        item(lx, y, lambda cx, cy: icono_ip(lienzo, (cx, cy + 3)), "Cámaras IP")

    def _vista_grande(self, t: float) -> np.ndarray:
        """El Robotat a pantalla completa, con titulo y leyenda arriba a la izquierda."""
        e = self.escena
        drones, marker, cuerpo = e.estado(t)
        img = e.vista_grande.dibujar(t, drones=drones, marker=marker, cuerpo=cuerpo,
                                     camara_activa=self.plano(t)[0], t_vista=t - self.t_estados[0],
                                     esqueleto=e.esqueleto_en(t))
        titulo = texto_rgba("Robotat · posiciones del mocap", 30, BLANCO, negrita=True)
        rectangulo(img, 32, 30, 32 + 560, 30 + 130, FONDO_PANEL, 0.7)
        pegar(img, titulo, 52, 42)
        self._leyenda(img, 52, 42 + titulo.shape[0] + 12, 22)
        return img

    def inicio_movimiento(self, t: float) -> float:
        """Hacia atras desde `t`, cuando empezaron a moverse las munecas en la camara del plano."""
        cam = self.plano(t)[0]
        ps = self.poses.get(cam, [])
        i = bisect.bisect_right(self.t_poses.get(cam, []), t) - 1
        inicio, quieto_desde = t - ANTES_MIN_S, None
        while i > 0 and t - ps[i]["t"] <= ANTES_MAX_S:
            a, b = ps[i - 1], ps[i]
            dt = b["t"] - a["t"]
            if a.get("lm") and b.get("lm") and dt > 0:
                v = max(np.hypot(b["lm"][k][0] - a["lm"][k][0], b["lm"][k][1] - a["lm"][k][1]) / dt
                        for k in (15, 16))
                if v >= MOVIMIENTO_MIN:
                    inicio, quieto_desde = a["t"], None
                elif quieto_desde is None:
                    quieto_desde = b["t"]
                elif quieto_desde - a["t"] > 0.4:
                    break                       # 0.4 s quieto: ahi empezo el gesto
            i -= 1
        return min(inicio, t - ANTES_MIN_S)

    def pose(self, camara: str, t: float):
        ps = self.poses.get(camara, [])
        i = bisect.bisect_right(self.t_poses.get(camara, []), t) - 1
        if i < 0 or t - ps[i]["t"] > POSE_VALIDA_S:
            return None
        return ps[i].get("lm")

    def estado(self, t: float) -> dict:
        i = bisect.bisect_right(self.t_estados, t) - 1
        return self.estados[i] if i >= 0 else {}

    def plano(self, t: float) -> tuple[str, str | None, float]:
        """`(camara, camara anterior o None, peso de la actual)` en `t`."""
        if getattr(self, "camara_fija", None):
            return self.camara_fija, None, 1.0
        i = max(0, bisect.bisect_right(self.t_planos, t) - 1)
        inicio, cam = self.planos[i]
        if i > 0 and t - inicio < TRANSICION_S:
            return cam, self.planos[i - 1][1], (t - inicio) / TRANSICION_S
        return cam, None, 1.0

    def componer(self, t: float, frames: dict) -> np.ndarray:
        cam, anterior, peso = self.plano(t)
        lienzo = _imagen(frames.get(cam))
        if anterior is not None:
            suave = peso * peso * (3 - 2 * peso)        # smoothstep: entra y sale despacio
            lienzo = cv2.addWeighted(_imagen(frames.get(anterior)), 1 - suave, lienzo, suave, 0)
        else:
            suave = 1.0

        # Al despegar y al empezar a seguir: el Robotat en grande y la camara
        # en el recuadro, con un fundido entre las dos.
        grande = 0.0
        if self.escena is not None and self.escena.vista_grande is not None:
            grande = self.escena.peso_grande(t)
        camara = lienzo
        if grande > 0.0:
            lienzo = cv2.addWeighted(camara, 1 - grande, self._vista_grande(t), grande, 0)

        # Columna derecha, abajo: el Robotat en 3D y, debajo, el esqueleto.
        bw, bh = ANCHO_CUADRO, ALTO_ESQUELETO
        bx, by = ANCHO - 40 - bw, ALTO - 40 - bh
        if self.escena is not None:
            self._dibujar_escena(lienzo, t, bx, by - 12 - ALTO_3D, bw, ALTO_3D,
                                 camara=camara, peso_camara=grande)
        rectangulo(lienzo, bx, by, bx + bw, by + bh, FONDO_PANEL, 0.8)
        cv2.rectangle(lienzo, (bx, by), (bx + bw - 1, by + bh - 1), (90, 90, 90), 1, cv2.LINE_AA)
        pegar(lienzo, texto_rgba("Esqueleto detectado", 17, GRIS), bx + 12, by + 8)
        # El gesto que se esta reconociendo, sobre el esqueleto: encima del
        # recuadro si hay sitio; si arriba esta la vista 3D, dentro, arriba a la derecha.
        rotulo, opacidad = rotulo_en(self.rotulos, t)
        if rotulo is not None:
            nombre = texto_rgba(rotulo[3], 24 if self.escena is None else 18, BLANCO, negrita=True)
            if self.escena is None:
                x0, y1 = bx, by - 10
                y0 = y1 - nombre.shape[0] - 18
                rectangulo(lienzo, x0, y0, x0 + nombre.shape[1] + 32, y1, VERDE_ROTULO, 0.9 * opacidad)
                pegar(lienzo, nombre, x0 + 16, y0 + 8, opacidad)
            else:
                x0 = bx + bw - nombre.shape[1] - 26
                rectangulo(lienzo, x0, by + 6, bx + bw - 6, by + 10 + nombre.shape[0], VERDE_ROTULO, 0.9 * opacidad)
                pegar(lienzo, nombre, x0 + 10, by + 7, opacidad)
        cuerpo = cuadro_esqueleto(self.pose(cam, t), self.conexiones, bw - 20, bh - 40)
        pegar(lienzo, cuerpo, bx + 10, by + 34, suave)
        if anterior is not None:
            previo = cuadro_esqueleto(self.pose(anterior, t), self.conexiones, bw - 20, bh - 40)
            pegar(lienzo, previo, bx + 10, by + 34, 1 - suave)

        # Abajo a la izquierda: la accion, en un rotulo verde. Solo si volaron
        # drones de verdad: con el dron simulado se dice el gesto, no lo que hizo.
        con_drones = self.escena is not None and bool(self.escena.drones)
        if rotulo is not None and con_drones and rotulo[4]:
            accion = texto_rgba(rotulo[4], 46, BLANCO, negrita=True)
            ancho, alto = accion.shape[1] + 64, accion.shape[0] + 34
            x0, y1 = 48, ALTO - 48
            y0 = y1 - alto
            desliza = int((1 - opacidad) * 24)
            rectangulo(lienzo, x0 - desliza, y0, x0 + ancho - desliza, y1, VERDE_ROTULO, 0.9 * opacidad)
            rectangulo(lienzo, x0 - desliza, y0, x0 + 6 - desliza, y1, ACENTO, opacidad)
            pegar(lienzo, accion, x0 + 32 - desliza, y0 + 14, opacidad)
        return lienzo


def _encajar_en(img, tamano: tuple[int, int]) -> np.ndarray:
    """`img` dentro de `tamano` (ancho, alto) sin deformar, con bandas."""
    ancho, alto = tamano
    celda = np.full((alto, ancho, 3), FONDO_PANEL, np.uint8)
    h, w = img.shape[:2]
    e = min(ancho / w, alto / h)
    nw, nh = max(1, int(w * e)), max(1, int(h * e))
    x, y = (ancho - nw) // 2, (alto - nh) // 2
    celda[y:y + nh, x:x + nw] = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
    return celda


def _imagen(frame):
    if frame is None:
        return np.full((ALTO, ANCHO, 3), FONDO_PANEL, np.uint8)
    # Sin la fecha y la hora que imprime la camara arriba a la derecha: se
    # recorta la franja de arriba y lo proporcional a los lados, centrado.
    alto, ancho = frame.shape[:2]
    y0, y1 = int(alto * RECORTE_ARRIBA), int(alto * (1 - RECORTE_ABAJO))
    nuevo_ancho = int(ancho * (y1 - y0) / alto)
    x0 = (ancho - nuevo_ancho) // 2
    frame = frame[y0:y1, x0:x0 + nuevo_ancho]
    return cv2.resize(frame, (ANCHO, ALTO), interpolation=cv2.INTER_AREA)


def portada(t: float, duracion: float = PORTADA_S) -> np.ndarray:
    lienzo = np.full((ALTO, ANCHO, 3), (16, 14, 12), np.uint8)
    opacidad = min(1.0, t / FUNDIDO_S, (duracion - t) / FUNDIDO_S)
    tit = texto_rgba(TITULO, 58, BLANCO, negrita=True, interlineado=1.3, centrado=True)
    y = ALTO // 2 - tit.shape[0] // 2 - 14
    pegar(lienzo, tit, (ANCHO - tit.shape[1]) // 2, y, opacidad)
    cv2.line(lienzo, (ANCHO // 2 - 80, y + tit.shape[0] + 28), (ANCHO // 2 + 80, y + tit.shape[0] + 28),
             tuple(int(c * opacidad) for c in ACENTO), 3, cv2.LINE_AA)
    return lienzo


def preparar(carpeta: Path, args, ffmpeg: str, desde: float | None = None, hasta: float | None = None,
             camara: str | None = None):
    """`(montaje, videos, t_ini, t_fin, desfase)` de una sesion, o `None` si no se puede."""
    inicio, poses, estados, eventos = leer(carpeta / REGISTRO)
    if not estados:
        print(f"ERROR: {carpeta.name}: el registro no tiene estados.", file=sys.stderr)
        return None
    t0, t1 = estados[0]["t"], estados[-1]["t"]
    escena = None
    if not args.sin_escena:
        dia, sesion = carpeta.resolve().parent.name, carpeta.resolve().name
        drones = drones_de_la_sesion(dia, t0, t1)
        marker = marker_de_la_sesion(PROJECT_DIR / "results" / "data" / "control_camara_dron1" / dia / f"{sesion}.csv")
        if drones or marker is not None:
            config = cargar_config()
            tramos = tramos_con_drones(eventos_de_drones(dia, t0, t1)) if drones else []
            escena = Escena(Vista3D(config, ANCHO_CUADRO - 2, ALTO_3D - ARRIBA_3D - LEYENDA_3D, giro_deg_por_s=0.6),
                            drones, marker, tramos,
                            Vista3D(config, ANCHO, ALTO, distancia_m=10.5, elevacion_deg=34.0, giro_deg_por_s=0.6),
                            cargar_cuerpo(carpeta))
            print(f"{carpeta.name}: vista 3D con " + ", ".join(s.nombre for s in drones)
                  + (", marker 65" if marker is not None else ", sin marker 65")
                  + ("; Robotat en grande en " + ", ".join(f"{a - t0:.0f}-{b - t0:.0f} s" for a, b in tramos)
                     if tramos else ""))
    montaje = Montaje(inicio, poses, estados, eventos, escena)
    # Gestos que el sistema no reconocio pero se quieren rotular, anotados a
    # mano en `<sesion>/gestos_anotados.json`: [{"desde": s, "hasta": s, "gesto": "Arco"}]
    anotados = carpeta / "gestos_anotados.json"
    if anotados.is_file():
        for g in json.loads(anotados.read_text(encoding="utf-8")):
            montaje.rotulos.append((t0 + g["desde"], t0 + g["hasta"], "ANOTADO A MANO", g["gesto"], ""))
        montaje.rotulos.sort()
        print(f"{carpeta.name}: {anotados.name} con " + ", ".join(g["gesto"] for g in json.loads(anotados.read_text(encoding="utf-8"))))
    # Una camara fija para toda la sesion: cuando la activa no es la que mejor
    # ensena el gesto (p. ej. la mesa de la laptop delante del operador).
    montaje.camara_fija = camara if camara and camara != "auto" else None
    videos = {}
    for nombre in montaje.camaras:
        mkv = carpeta / f"{nombre}_hd.mkv"
        if mkv.is_file():
            marcas = marcas_de_tiempo(_ffprobe(ffmpeg), mkv)
            if len(marcas) and marcas[0] >= 1e9:
                videos[nombre] = (mkv, marcas)
    if not videos:
        print(f"ERROR: {carpeta.name}: no hay videos HD con hora de pared.", file=sys.stderr)
        return None
    # Por defecto, desde un poco antes de que alguna camara tome el mando.
    primera = next((e["t"] for e in estados if e.get("activa")), t0)
    t_ini = t0 + desde if desde is not None else max(t0, primera - 0.5)
    t_fin = min(t1, t0 + hasta) if hasta is not None else t1
    if args.desfase == "auto":
        desfase = estimar_desfase(videos, poses, t0)
        desfase = 0.0 if desfase is None else desfase
    else:
        desfase = float(args.desfase)
    print(f"{carpeta.name}: desfase HD-esqueleto {desfase:+.2f} s")
    print("  planos: " + ", ".join(f"{t - t0:.1f}s {c}" for t, c in montaje.planos))
    for t, fin, _cat, nombre, accion in montaje.rotulos:
        print(f"  {t - t0:6.1f}-{fin - t0:5.1f} s  {nombre}: {accion}")
    return montaje, videos, t_ini, t_fin, desfase


def escribir_sesion(salida, montaje, videos, t_ini, t_fin, desfase) -> None:
    """Los cuadros de una sesion, con fundido desde negro al entrar y a negro al salir."""
    fuentes = {n: FuenteHD(ruta, marcas) for n, (ruta, marcas) in videos.items()}
    try:
        n = int((t_fin - t_ini) * FPS)
        for k in range(n):
            t = t_ini + k / FPS
            frames = {nombre: f.en(t + desfase) for nombre, f in fuentes.items()}
            cuadro = montaje.componer(t, frames)
            nivel = min(1.0, k / (FUNDIDO_S * FPS), (n - 1 - k) / (FUNDIDO_S * FPS))
            if nivel < 1.0:
                cuadro = (cuadro.astype(np.float32) * max(0.0, nivel)).astype(np.uint8)
            salida.escribir(cuadro)
            if k % int(FPS * 15) == 0:
                print(f"  {k / FPS:5.0f} s de {n / FPS:.0f} s", flush=True)
    finally:
        for f in fuentes.values():
            f.cerrar()


def main() -> int:
    parser = argparse.ArgumentParser(description="Video resumen formal de una o varias sesiones grabadas con --grabar-hd.")
    parser.add_argument("carpetas", type=Path, nargs="+",
                        help="carpeta de cada sesion; con varias, se encadenan en ese orden tras una sola portada")
    parser.add_argument("--desfase", default="auto", help="segundos, o `auto`")
    parser.add_argument("--desde", type=float, nargs="+", default=None,
                        help="segundo de cada sesion donde empezar: uno para todas o uno por sesion")
    parser.add_argument("--hasta", type=float, nargs="+", default=None,
                        help="segundo de cada sesion donde acabar (p. ej. antes de ir a cortar la grabacion)")
    parser.add_argument("--camara", nargs="+", default=None,
                        help="camara fija por sesion (cam1...cam6) o `auto` (la activa, por defecto)")
    parser.add_argument("--sin-portada", action="store_true")
    parser.add_argument("--sin-escena", action="store_true",
                        help="sin la vista 3D del Robotat (drones, operador y camaras)")
    parser.add_argument("--salida", type=Path,
                        help="por defecto <carpeta>/resumen_gestos.mp4, o resumen_unido.mp4 junto a la primera")
    args = parser.parse_args()
    for opcion in ("desde", "hasta", "camara"):
        valores = getattr(args, opcion)
        if valores is not None and len(valores) not in (1, len(args.carpetas)):
            parser.error(f"--{opcion}: un valor para todas las sesiones o uno por sesion")

    ffmpeg = buscar_ffmpeg()
    if ffmpeg is None:
        print("ERROR: no se encuentra ffmpeg.", file=sys.stderr)
        return 1
    def de_la_sesion(valores, i):
        return None if valores is None else valores[i if len(valores) > 1 else 0]

    sesiones = [preparar(c, args, ffmpeg, de_la_sesion(args.desde, i), de_la_sesion(args.hasta, i),
                         de_la_sesion(args.camara, i))
                for i, c in enumerate(args.carpetas)]
    if any(s is None for s in sesiones):
        return 1
    if args.salida:
        ruta = args.salida
    elif len(args.carpetas) == 1:
        ruta = args.carpetas[0] / "resumen_gestos.mp4"
    else:
        ruta = args.carpetas[0].parent.parent / "resumen_unido.mp4"
    salida = SalidaH264(ffmpeg, ruta, FPS)
    try:
        if not args.sin_portada:
            for k in range(int(PORTADA_S * FPS)):
                salida.escribir(portada(k / FPS))
        for carpeta, sesion in zip(args.carpetas, sesiones):
            print(f"Escribiendo {carpeta.name}")
            escribir_sesion(salida, *sesion)
    finally:
        salida.cerrar()
    print(f"Video: {salida.ruta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
