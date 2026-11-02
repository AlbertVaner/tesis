"""Recomponer la interfaz de una sesion en 1080p, con la imagen del stream principal.

Durante la sesion el reconocedor trabaja en VGA, que es lo que lo hace fluido,
y la interfaz grabada en vivo se ve borrosa. Con `--grabar-hd`,
`control_camara_dron1.py` deja en la carpeta de la sesion:

* `camN_hd.mkv`: el stream principal de cada camara, cada cuadro marcado con
  la hora de pared a la que llego (`grabar_camaras_hd.py`);
* `render.jsonl`: lo que hizo el sistema, con el mismo reloj
  (`visualization/registro_render.py`): esqueleto de cada camara, camara
  activa, gesto, estado del dron y ordenes.

Este script junta las dos cosas: en cada instante pone la imagen HD de cada
camara con el esqueleto y el gesto que el sistema tenia **en vivo** en ese
instante. No vuelve a reconocer nada. Sale `sesion_hd.mp4` (H.264, 1920x1080)
en la misma carpeta y, con `--por-camara`, un `camN_hd_esqueleto.mp4` por
camara. Tambien deja un `camN_hd.mp4` sin dibujos que cualquier editor abre.

El desfase
----------
El stream principal llega mas tarde que el sub-stream (es mas pesado de
codificar y de mandar), asi que el cuadro HD de un instante tiene una hora de
llegada algo posterior a la del cuadro VGA sobre el que se calculo el
esqueleto. `--desfase auto` (por defecto) lo estima correlacionando el
movimiento de la imagen HD con el de los brazos del esqueleto; si la
estimacion no es fiable, usa 0 y lo avisa. Para afinarlo a mano:
`--desfase 0.35` (segundos; positivo = el HD va por detras), y `--desde 30
--hasta 40` para renderizar solo un trozo y mirarlo.

Uso, desde la raiz del repositorio:

    python .\\external\\gesture_detection\\renderizar_sesion_hd.py results\\captures\\control_camara_dron1\\<dia>\\sesion_HHMMSS
    python .\\external\\gesture_detection\\renderizar_sesion_hd.py <carpeta> --desde 30 --hasta 40 --desfase 0.3

El esqueleto se dibuja con coordenadas normalizadas al encuadre: vale si el
sub-stream y el principal ven el mismo campo (las Amcrest escalan, no
recortan). Si se viera desplazado de forma constante, es eso y no el desfase.
"""

from __future__ import annotations

import argparse
import bisect
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from grabar_camaras_hd import buscar_ffmpeg, remux  # noqa: E402
from visualization.registro_render import NOMBRE as REGISTRO, leer  # noqa: E402

ANCHO, ALTO = 1920, 1080
PRINCIPAL = (1440, 810)                 # camara activa, 16:9
ANCHO_PANEL = ANCHO - PRINCIPAL[0]
MINIATURA = (ANCHO_PANEL // 2, 135)

FONDO = (24, 22, 20)
BLANCO, GRIS = (235, 235, 235), (140, 140, 140)
VERDE, AMBAR, ROJO = (90, 210, 90), (40, 190, 250), (70, 70, 230)
HUESO, ARTICULACION = (0, 170, 255), (90, 230, 90)

#: Vocabulario de `recognition/vocabulario.py`, para la leyenda del panel.
LEYENDA = (
    ("MODO DINAMICO", "dinamico", ("senalero: despegar / aterrizar", "ven aca: seguir",
                                   "arco: pirueta", "circulo: orbitar")),
    ("MODO ESTATICO", "estatico", ("un brazo: arriba, abajo, adelante,", "atras, izquierda, derecha")),
    ("SIEMPRE", None, ("aplaudir: cambiar de modo", "X sobre la cabeza: paro")),
)

#: Una pose vieja no se dibuja: la camara dejo de ver a la persona.
POSE_VALIDA_S = 0.4
#: Landmarks de hombros, codos y munecas: los que mueven los gestos.
BRAZOS = (11, 12, 13, 14, 15, 16)


# ------------------------------------------------------------ marcas de tiempo


def marcas_de_tiempo(ffprobe: str, video: Path) -> np.ndarray:
    """Hora de pared de cada cuadro, en orden de presentacion."""
    salida = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time",
         "-of", "csv=p=0", str(video)], capture_output=True, text=True, check=True).stdout
    marcas = [float(x) for x in salida.split() if x.strip() not in ("", "N/A")]
    return reparar_marcas(np.array(marcas, dtype=float))


def reparar_marcas(marcas: np.ndarray) -> np.ndarray:
    """Las marcas que no son hora de pared, con la hora de su vecino.

    Con las Amcrest, el primer keyframe sale con marca 0: ffmpeg lo recibe
    antes de empezar a marcar con el reloj. Sigue siendo un cuadro que
    OpenCV decodifica, asi que no se puede quitar sin descuadrar el indice:
    se le da la hora del siguiente valido.
    """
    marcas = marcas.copy()
    validas = np.flatnonzero(marcas >= 1e9)
    if len(validas) == 0:
        return np.sort(marcas)
    for i in np.flatnonzero(marcas < 1e9):
        siguiente = validas[validas > i]
        marcas[i] = marcas[siguiente[0]] if len(siguiente) else marcas[validas[-1]]
    return np.sort(marcas)


class FuenteHD:
    """Un video HD leido en orden, avanzando hasta la hora que se pida."""

    def __init__(self, ruta: Path, marcas: np.ndarray) -> None:
        self.ruta = ruta
        self.marcas = marcas
        self.captura = cv2.VideoCapture(str(ruta))
        self.indice = -1                # cuadro que hay en `frame`
        self.frame = None

    def en(self, t: float):
        """El ultimo cuadro llegado antes de `t`, o `None` si aun no hay."""
        while self.indice + 1 < len(self.marcas) and self.marcas[self.indice + 1] <= t:
            ok, frame = self.captura.read()
            if not ok:
                self.marcas = self.marcas[:self.indice + 1]
                break
            self.indice += 1
            self.frame = frame
        return self.frame

    def cerrar(self) -> None:
        self.captura.release()


# ------------------------------------------------------------------- desfase


def _senal_imagen(ruta: Path, marcas: np.ndarray, t0: float, t1: float):
    """Energia de movimiento de la imagen entre `t0` y `t1`: `(tiempos, valores)`."""
    captura = cv2.VideoCapture(str(ruta))
    tiempos, valores, anterior = [], [], None
    for t in marcas:
        if t > t1:
            break
        ok = captura.grab()
        if not ok:
            break
        if t < t0:
            continue
        ok, frame = captura.retrieve()
        if not ok:
            break
        gris = cv2.cvtColor(cv2.resize(frame, (160, 90)), cv2.COLOR_BGR2GRAY).astype(np.float32)
        if anterior is not None:
            tiempos.append(t)
            valores.append(float(np.mean(np.abs(gris - anterior))))
        anterior = gris
    captura.release()
    return np.array(tiempos), np.array(valores)


def _senal_pose(poses: list[dict], t0: float, t1: float):
    """Velocidad de los brazos del esqueleto entre `t0` y `t1`: `(tiempos, valores)`."""
    tiempos, valores, anterior = [], [], None
    for p in poses:
        if not t0 <= p["t"] <= t1 or not p.get("lm"):
            anterior = None
            continue
        lm = np.array(p["lm"], dtype=float)
        if anterior is not None and p["t"] > anterior[0]:
            visibles = [i for i in BRAZOS if lm[i, 2] > 0.5 and anterior[1][i, 2] > 0.5]
            if visibles:
                d = np.linalg.norm(lm[visibles, :2] - anterior[1][visibles, :2], axis=1).mean()
                tiempos.append(p["t"])
                valores.append(d / (p["t"] - anterior[0]))
        anterior = (p["t"], lm)
    return np.array(tiempos), np.array(valores)


def correlacionar(t_img, v_img, t_pose, v_pose, *, paso=0.05, minimo=-0.5, maximo=1.5):
    """`(desfase, correlacion)` que mejor alinea la imagen con la pose.

    Desfase positivo: la imagen HD llega despues que la pose.
    """
    if len(t_img) < 20 or len(t_pose) < 20:
        return 0.0, 0.0
    inicio = max(t_img[0], t_pose[0]) - minimo
    fin = min(t_img[-1], t_pose[-1]) - maximo
    if fin - inicio < 5.0:
        return 0.0, 0.0
    rejilla = np.arange(inicio, fin, paso)

    def norm(x):
        return (x - x.mean()) / (x.std() + 1e-9)

    pose = norm(np.interp(rejilla, t_pose, v_pose))
    mejor = (0.0, -1.0)
    for desfase in np.arange(minimo, maximo + 1e-9, paso):
        img = norm(np.interp(rejilla + desfase, t_img, v_img))
        c = float(np.mean(img * pose))
        if c > mejor[1]:
            mejor = (round(float(desfase), 3), c)
    return mejor


def estimar_desfase(fuentes: dict, poses: dict, t0: float, duracion: float = 90.0) -> float | None:
    """Desfase HD - pose sobre la camara con mas esqueletos. `None` si no es fiable."""
    candidatas = sorted(fuentes, key=lambda n: -sum(1 for p in poses.get(n, ()) if p.get("lm")))
    for nombre in candidatas[:2]:
        ruta, marcas = fuentes[nombre]
        senal_img = _senal_imagen(ruta, marcas, t0, t0 + duracion)
        senal_pose = _senal_pose(poses.get(nombre, []), t0, t0 + duracion)
        desfase, c = correlacionar(*senal_img, *senal_pose)
        print(f"  desfase estimado en {nombre}: {desfase:+.2f} s (correlacion {c:.2f})")
        if c >= 0.3:
            return desfase
    return None


# -------------------------------------------------------------------- dibujo


def texto(img, txt, xy, color=BLANCO, escala=0.7, grosor=2) -> None:
    """Texto con contorno oscuro, legible sobre cualquier imagen."""
    cv2.putText(img, txt, xy, cv2.FONT_HERSHEY_SIMPLEX, escala, (0, 0, 0), grosor + 3, cv2.LINE_AA)
    cv2.putText(img, txt, xy, cv2.FONT_HERSHEY_SIMPLEX, escala, color, grosor, cv2.LINE_AA)


def encajar(frame, ancho: int, alto: int):
    """`(celda, (x, y, w, h))`: el frame sin deformar dentro de `ancho` x `alto`."""
    celda = np.full((alto, ancho, 3), FONDO, np.uint8)
    if frame is None:
        return celda, None
    fa, fw = frame.shape[:2]
    escala = min(ancho / fw, alto / fa)
    w, h = max(1, int(fw * escala)), max(1, int(fa * escala))
    x, y = (ancho - w) // 2, (alto - h) // 2
    celda[y:y + h, x:x + w] = cv2.resize(frame, (w, h), interpolation=cv2.INTER_AREA)
    return celda, (x, y, w, h)


def dibujar_esqueleto(img, caja, lm, conexiones, grosor: int) -> None:
    if caja is None or not lm:
        return
    x0, y0, w, h = caja

    def punto(i):
        return int(x0 + lm[i][0] * w), int(y0 + lm[i][1] * h)

    for a, b in conexiones:
        if lm[a][2] > 0.1 and lm[b][2] > 0.1:
            cv2.line(img, punto(a), punto(b), HUESO, grosor, cv2.LINE_AA)
    for i, p in enumerate(lm):
        if p[2] > 0.1:
            cv2.circle(img, punto(i), grosor + 1, ARTICULACION, -1, cv2.LINE_AA)


def ultimo(lista: list[dict], tiempos: list[float], t: float) -> dict | None:
    i = bisect.bisect_right(tiempos, t) - 1
    return lista[i] if i >= 0 else None


class Escena:
    """Todo lo registrado, indexado por tiempo, y el dibujo de un instante."""

    def __init__(self, inicio, poses, estados, eventos) -> None:
        self.camaras = inicio.get("camaras") or sorted(poses)
        self.conexiones = inicio.get("conexiones", [])
        self.poses = poses
        self.t_poses = {n: [p["t"] for p in ps] for n, ps in poses.items()}
        self.estados = estados
        self.t_estados = [e["t"] for e in estados]
        self.eventos = eventos
        self.t_eventos = [e["t"] for e in eventos]

    def pose(self, camara: str, t: float):
        p = ultimo(self.poses.get(camara, []), self.t_poses.get(camara, []), t)
        if p is None or t - p["t"] > POSE_VALIDA_S:
            return None
        return p.get("lm")

    def estado(self, t: float) -> dict:
        return ultimo(self.estados, self.t_estados, t) or {}

    def eventos_hasta(self, t: float, n: int = 4) -> list[dict]:
        i = bisect.bisect_right(self.t_eventos, t)
        return self.eventos[max(0, i - n):i]

    def componer(self, t: float, frames: dict, fija: str | None = None):
        lienzo = np.full((ALTO, ANCHO, 3), FONDO, np.uint8)
        estado = self.estado(t)
        activa = fija or estado.get("activa") or (self.camaras[0] if self.camaras else None)

        # Camara activa en grande.
        celda, caja = encajar(frames.get(activa), *PRINCIPAL)
        dibujar_esqueleto(celda, caja, self.pose(activa, t), self.conexiones, 4)
        if caja is None:
            texto(celda, "sin imagen", (PRINCIPAL[0] // 2 - 90, PRINCIPAL[1] // 2), GRIS, 1.0)
        texto(celda, (activa or "-").upper(), (24, 44), VERDE, 1.0)
        lienzo[:PRINCIPAL[1], :PRINCIPAL[0]] = celda

        self._barra_gesto(lienzo, estado, t)
        self._panel(lienzo, estado, frames, activa, t)
        return lienzo

    def _barra_gesto(self, lienzo, estado: dict, t: float) -> None:
        y0 = PRINCIPAL[1]
        gesto = estado.get("gesto") or "NO_GESTURE"
        if gesto == "NO_GESTURE":
            texto(lienzo, "sin gesto", (32, y0 + 90), GRIS, 1.6, 3)
        else:
            color = VERDE if estado.get("confirmado") else AMBAR
            texto(lienzo, gesto, (32, y0 + 90), color, 1.8, 4)
            if not estado.get("confirmado"):
                texto(lienzo, "confirmando...", (34, y0 + 128), AMBAR, 0.7)
        y = y0 + 170
        for e in reversed(self.eventos_hasta(t)):
            edad = t - e["t"]
            color = (VERDE if e.get("ejecutado") else GRIS) if edad < 6 else GRIS
            texto(lienzo, e["texto"][:70], (32, y), color, 0.75 if edad < 6 else 0.6)
            y += 30
            if y > ALTO - 10:
                break

    def _panel(self, lienzo, estado: dict, frames: dict, activa, t: float) -> None:
        x0 = PRINCIPAL[0]
        texto(lienzo, "CONTROL POR GESTOS", (x0 + 20, 40), BLANCO, 0.8)
        lineas = [
            ("dron", estado.get("estado") or "-", BLANCO),
            ("modo", (estado.get("modo") or "-").upper(), BLANCO),
            ("hace", estado.get("comportamiento") or estado.get("seguimiento") or "-", BLANCO),
        ]
        if estado.get("paro"):
            lineas.append(("", "PARO ACTIVO", ROJO))
        y = 80
        for etiqueta, valor, color in lineas:
            texto(lienzo, etiqueta, (x0 + 20, y), GRIS, 0.6, 1)
            texto(lienzo, str(valor)[:22], (x0 + 100, y), color, 0.7)
            y += 34
        y = 230
        mw, mh = MINIATURA
        for i, nombre in enumerate(self.camaras):
            fila, col = divmod(i, 2)
            x, yy = x0 + col * mw, y + fila * mh
            if yy + mh > ALTO:
                break
            celda, caja = encajar(frames.get(nombre), mw, mh)
            dibujar_esqueleto(celda, caja, self.pose(nombre, t), self.conexiones, 1)
            es_activa = nombre == activa
            cv2.rectangle(celda, (0, 0), (mw - 1, mh - 1), VERDE if es_activa else (60, 60, 60),
                          4 if es_activa else 1)
            texto(celda, nombre, (8, 22), VERDE if es_activa else BLANCO, 0.55, 1)
            lienzo[yy:yy + mh, x:x + mw] = celda
        filas = -(-len(self.camaras) // 2)
        self._leyenda(lienzo, x0 + 20, y + filas * mh + 40, estado.get("modo"))

    @staticmethod
    def _leyenda(lienzo, x: int, y: int, modo) -> None:
        """El vocabulario, con el modo en curso resaltado: para quien ve el video."""
        for titulo, clave, lineas in LEYENDA:
            activo = modo == clave if clave else True
            texto(lienzo, titulo, (x, y), VERDE if activo and clave else GRIS, 0.6, 2 if activo else 1)
            y += 28
            for linea in lineas:
                texto(lienzo, linea, (x + 12, y), BLANCO if activo else GRIS, 0.5, 1)
                y += 24
            y += 10
            if y > ALTO - 20:
                return


# -------------------------------------------------------------------- salida


class SalidaH264:
    """Cuadros BGR a un MP4 H.264 por la tuberia de ffmpeg: mucha mejor calidad que mp4v."""

    def __init__(self, ffmpeg: str, ruta: Path, fps: float, tamano=(ANCHO, ALTO)) -> None:
        self.ruta = ruta
        self.tamano = tamano
        self.proceso = subprocess.Popen(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
             "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{tamano[0]}x{tamano[1]}",
             "-r", f"{fps:g}", "-i", "-",
             "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
             "-movflags", "+faststart", str(ruta)],
            stdin=subprocess.PIPE)

    def escribir(self, frame) -> None:
        if frame.shape[1::-1] != self.tamano:
            frame = cv2.resize(frame, self.tamano)
        self.proceso.stdin.write(np.ascontiguousarray(frame).tobytes())

    def cerrar(self) -> None:
        self.proceso.stdin.close()
        self.proceso.wait()


def _ffprobe(ffmpeg: str) -> str:
    candidato = Path(ffmpeg).with_name("ffprobe" + Path(ffmpeg).suffix)
    return str(candidato) if candidato.is_file() else "ffprobe"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recompone en 1080p la interfaz de una sesion grabada con --grabar-hd.")
    parser.add_argument("carpeta", type=Path, help="carpeta de la sesion (render.jsonl y camN_hd.mkv)")
    parser.add_argument("--desfase", default="auto",
                        help="segundos que el HD va por detras de la pose, o `auto` (por defecto)")
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--desde", type=float, default=0.0, help="segundo de la sesion donde empezar")
    parser.add_argument("--hasta", type=float, default=None, help="segundo de la sesion donde acabar")
    parser.add_argument("--camara", help="dejar fija esta camara en grande (cam1...)")
    parser.add_argument("--por-camara", action="store_true",
                        help="ademas, un camN_hd_esqueleto.mp4 por camara (lento)")
    parser.add_argument("--sin-remux", action="store_true", help="no dejar los camN_hd.mp4 limpios")
    parser.add_argument("--salida", type=Path, help="por defecto <carpeta>/sesion_hd.mp4")
    args = parser.parse_args()

    ffmpeg = buscar_ffmpeg()
    if ffmpeg is None:
        print("ERROR: no se encuentra ffmpeg (winget install Gyan.FFmpeg).", file=sys.stderr)
        return 1
    ffprobe = _ffprobe(ffmpeg)
    registro = args.carpeta / REGISTRO
    if not registro.is_file():
        print(f"ERROR: no hay {registro}. Se graba con --grabar-hd.", file=sys.stderr)
        return 1
    inicio, poses, estados, eventos = leer(registro)
    if not estados:
        print("ERROR: el registro no tiene ningun estado.", file=sys.stderr)
        return 1
    escena = Escena(inicio, poses, estados, eventos)

    videos = {}
    for nombre in escena.camaras:
        mkv = args.carpeta / f"{nombre}_hd.mkv"
        if not mkv.is_file():
            print(f"  {nombre}: no hay {mkv.name}; saldra sin imagen")
            continue
        marcas = marcas_de_tiempo(ffprobe, mkv)
        if len(marcas) == 0 or marcas[0] < 1e9:
            print(f"  {nombre}: {mkv.name} no tiene la hora de pared en sus marcas; se omite")
            continue
        videos[nombre] = (mkv, marcas)
    if not videos:
        print("ERROR: ningun video HD utilizable.", file=sys.stderr)
        return 1

    t_sesion = escena.t_estados[0]
    t_ini = t_sesion + args.desde
    t_fin = escena.t_estados[-1] if args.hasta is None else t_sesion + args.hasta

    if args.desfase == "auto":
        print("Estimando el desfase entre el HD y el esqueleto...")
        desfase = estimar_desfase(videos, poses, t_sesion)
        if desfase is None:
            desfase = 0.0
            print("  no es fiable: uso 0. Si el esqueleto va adelantado o atrasado, "
                  "repetir con --desfase (p. ej. 0.3) sobre un trozo corto.")
    else:
        desfase = float(args.desfase)
    print(f"Desfase: {desfase:+.2f} s")

    fuentes = {n: FuenteHD(ruta, marcas) for n, (ruta, marcas) in videos.items()}
    salida = SalidaH264(ffmpeg, args.salida or args.carpeta / "sesion_hd.mp4", args.fps)
    por_camara = ({n: SalidaH264(ffmpeg, args.carpeta / f"{n}_hd_esqueleto.mp4", args.fps)
                   for n in fuentes} if args.por_camara else {})
    n_cuadros = max(0, int((t_fin - t_ini) * args.fps))
    try:
        for k in range(n_cuadros):
            t = t_ini + k / args.fps
            frames = {n: f.en(t + desfase) for n, f in fuentes.items()}
            salida.escribir(escena.componer(t, frames, args.camara))
            for nombre, s in por_camara.items():
                celda, caja = encajar(frames.get(nombre), ANCHO, ALTO)
                dibujar_esqueleto(celda, caja, escena.pose(nombre, t), escena.conexiones, 4)
                s.escribir(celda)
            if k % int(args.fps * 10) == 0:
                print(f"  {k / args.fps:6.0f} s de {n_cuadros / args.fps:.0f} s", flush=True)
    finally:
        salida.cerrar()
        for s in por_camara.values():
            s.cerrar()
        for f in fuentes.values():
            f.cerrar()
    print(f"Interfaz HD: {salida.ruta}")
    for s in por_camara.values():
        print(f"Camara con esqueleto: {s.ruta}")
    if not args.sin_remux:
        for ruta, _ in videos.values():
            print(f"Camara limpia: {remux(ffmpeg, ruta)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
