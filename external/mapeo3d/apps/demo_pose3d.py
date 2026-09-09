"""Demostración en vivo del pipeline de pose 3D, con una sola cámara.

Pensada para **enseñarla**: una cámara, un comando, sin calibrar nada. La vista
3D gira sola para que se entienda de un vistazo que la reconstrucción es
volumétrica y no un esqueleto plano dibujado encima del vídeo.

Qué demuestra y qué no
----------------------
Demuestra las etapas que este repositorio implementa: **captura → landmarks 2D
→ pose 3D**. La franja inferior las muestra encendiéndose en vivo.

**No demuestra reconocimiento de gestos ni control de vuelo**, y la franja lo
dice explícitamente: esas dos etapas viven en el repositorio `tesis` y consumen
la salida de éste. Ver docs/architecture.md.

La profundidad de esta demo es la estimación **monocular** de MediaPipe, que
sale de un prior aprendido y no de geometría: con una sola cámara no hay otra
cosa. El panel de calidad muestra en todo momento cuánto se puede confiar en
ella, y ese número es la razón de ser del sistema de varias cámaras. Ver
docs/pose.md.

Controles
---------
    espacio   pausar / reanudar el giro
    flechas   girar y elevar la vista a mano
    + / -     acercar y alejar
    r         reiniciar la vista
    q / ESC   salir

Ejemplo
-------
    python apps/demo_pose3d.py
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import deque
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from mapeo3d.capture import CameraStream, load_config, mask_url  # noqa: E402
from mapeo3d.pose import (  # noqa: E402
    NOMBRES,
    PoseDetector,
    SUELO_M,
    a_escena,
    camara_orbital,
    dibujar_esqueleto_2d,
    dibujar_esqueleto_3d,
    dibujar_rejilla,
    pares_de_conexiones,
    pares_de_huesos,
)
from mapeo3d.triangulation import segment_length_stability  # noqa: E402

FONDO = (24, 24, 28)
TITULO = "Mapeo tridimensional — demostración"

# La vista arranca ligeramente de lado y elevada: de frente exacto la
# perspectiva no se aprecia y parece 2D, que es justo lo contrario de lo que
# se quiere enseñar.
AZIMUT_INICIAL = -70.0
ELEVACION_INICIAL = 16.0
DISTANCIA_INICIAL = 2.4
GRADOS_POR_SEGUNDO = 22.0

VENTANA_CALIDAD = 150

ETAPAS = [
    ("captura", True),
    ("landmarks 2D", True),
    ("pose 3D", True),
    ("gestos", False),
    ("vuelo", False),
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Demostración en vivo del pipeline de pose 3D.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--url", default="0",
                   help="Índice de webcam o URL. Por defecto: 0 (la del portátil).")
    p.add_argument("--camera", help="Cámara de la configuración, en vez de --url.")
    p.add_argument("--config", help="Ruta de configuración alternativa.")
    p.add_argument("--model", help="Ruta del .task de MediaPipe.")
    p.add_argument("--alto", type=int, default=560,
                   help="Alto de la ventana en píxeles. Por defecto: 560.")
    p.add_argument("--espejo", action="store_true", default=True,
                   help="Reflejar la imagen (por defecto sí: es lo natural "
                        "cuando uno se ve a sí mismo).")
    p.add_argument("--sin-espejo", dest="espejo", action="store_false")
    return p.parse_args()


def resolver_fuente(args) -> tuple[str | int, str]:
    if args.camera:
        cam = load_config(args.config).camera(args.camera)
        return cam.url(), cam.name
    return (int(args.url) if args.url.isdigit() else args.url), "webcam"


# ------------------------------------------------------------------ paneles


def _texto(img, txt, org, escala=0.5, color=(230, 230, 230), grosor=1):
    cv2.putText(img, txt, org, cv2.FONT_HERSHEY_SIMPLEX, escala, (0, 0, 0),
                grosor + 2, cv2.LINE_AA)
    cv2.putText(img, txt, org, cv2.FONT_HERSHEY_SIMPLEX, escala, color,
                grosor, cv2.LINE_AA)


def panel_pipeline(ancho: int, alto: int, activo: bool) -> np.ndarray:
    """Franja con las etapas del pipeline y dónde termina este repositorio."""
    panel = np.full((alto, ancho, 3), FONDO, np.uint8)
    n = len(ETAPAS)
    caja = ancho // n
    for i, (nombre, propio) in enumerate(ETAPAS):
        x0 = i * caja + 8
        x1 = (i + 1) * caja - 8
        if propio:
            color = (90, 200, 120) if activo else (70, 90, 75)
            relleno = -1 if activo else 1
        else:
            color = (90, 90, 110)
            relleno = 1
        cv2.rectangle(panel, (x0, 14), (x1, alto - 24), color, relleno,
                      cv2.LINE_AA)
        txt_color = (20, 20, 20) if (propio and activo) else (200, 200, 200)
        (w, _), _ = cv2.getTextSize(nombre, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.putText(panel, nombre, (x0 + (x1 - x0 - w) // 2, alto // 2 + 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, txt_color, 1, cv2.LINE_AA)
        if i < n - 1:
            cv2.arrowedLine(panel, (x1 + 1, alto // 2 - 5),
                            (x1 + 14, alto // 2 - 5), (120, 120, 120), 1,
                            cv2.LINE_AA, tipLength=0.4)

    corte = 3 * caja - 8
    cv2.line(panel, (corte, 6), (corte, alto - 16), (110, 110, 140), 1,
             cv2.LINE_AA)
    _texto(panel, "este repositorio", (12, alto - 8), 0.38, (140, 200, 155))
    _texto(panel, "repositorio tesis", (corte + 12, alto - 8), 0.38,
           (150, 150, 190))
    return panel


def panel_3d(lado: int, mundo, vis, conexiones, az, el, dist,
             sin_persona: bool) -> np.ndarray:
    panel = np.full((lado, lado, 3), FONDO, np.uint8)
    focal = lado * 0.9
    ojo, base = camara_orbital(az, el, dist)

    # La rejilla se apoya en el punto más bajo del cuerpo y no en una altura
    # fija: así el esqueleto se ve DE PIE sobre el suelo sea cual sea la
    # estatura, y no flotando por encima.
    suelo = SUELO_M
    if mundo is not None:
        z = a_escena(mundo)[:, 2]
        z = z[np.isfinite(z)]
        if z.size:
            suelo = float(z.min()) - 0.02
    dibujar_rejilla(panel, ojo, base, focal, altura_m=suelo)

    if mundo is not None:
        dibujar_esqueleto_3d(panel, mundo, vis, conexiones, NOMBRES,
                             ojo, base, focal)

    _texto(panel, "reconstruccion 3D", (12, 26), 0.52)
    _texto(panel, f"vista {az % 360:5.0f} deg", (12, lado - 16), 0.42,
           (150, 150, 150))
    if sin_persona:
        _texto(panel, "colocate frente a la camara",
               (12, lado // 2), 0.6, (90, 150, 240))
    return panel


def panel_datos(ancho: int, alto: int, fps: float, cv_pct: float | None,
                mundo, girando: bool) -> np.ndarray:
    panel = np.full((alto, ancho, 3), FONDO, np.uint8)
    y = 30
    _texto(panel, "en vivo", (14, y), 0.55, (200, 200, 200)); y += 30
    _texto(panel, f"{fps:4.1f} fps", (14, y), 0.5, (170, 200, 240)); y += 26

    if mundo is not None:
        alto_m = float(np.nanmax(mundo[:, 1]) - np.nanmin(mundo[:, 1]))
        prof_m = float(np.nanmax(mundo[:, 2]) - np.nanmin(mundo[:, 2]))
        _texto(panel, f"alto  {alto_m:.2f} m", (14, y), 0.5); y += 24
        _texto(panel, f"prof. {prof_m:.2f} m", (14, y), 0.5); y += 30
    else:
        y += 54

    _texto(panel, "calidad del 3D", (14, y), 0.5, (200, 200, 200)); y += 26
    if cv_pct is None:
        _texto(panel, "midiendo...", (14, y), 0.45, (150, 150, 150)); y += 24
    else:
        color = ((90, 220, 90) if cv_pct < 3 else
                 (60, 200, 230) if cv_pct < 8 else (90, 90, 240))
        _texto(panel, f"{cv_pct:.1f} %", (14, y), 0.62, color); y += 26
        _texto(panel, "variacion del largo", (14, y), 0.38, (150, 150, 150))
        y += 16
        _texto(panel, "de los huesos", (14, y), 0.38, (150, 150, 150)); y += 26

    _texto(panel, "un hueso rigido no", (14, y), 0.36, (140, 140, 140)); y += 15
    _texto(panel, "cambia de largo: todo", (14, y), 0.36, (140, 140, 140)); y += 15
    _texto(panel, "lo que varia es error", (14, y), 0.36, (140, 140, 140)); y += 26

    _texto(panel, "profundidad: estimada", (14, y), 0.36, (150, 150, 190)); y += 15
    _texto(panel, "por la red, no medida", (14, y), 0.36, (150, 150, 190)); y += 15
    _texto(panel, "-> por eso 6 camaras", (14, y), 0.36, (150, 150, 190))

    _texto(panel, "espacio: " + ("pausar giro" if girando else "reanudar"),
           (14, alto - 34), 0.38, (140, 140, 140))
    _texto(panel, "flechas: girar   q: salir", (14, alto - 16), 0.38,
           (140, 140, 140))
    return panel


# --------------------------------------------------------------------- main


def main() -> int:
    args = parse_args()
    fuente, nombre = resolver_fuente(args)
    conexiones = pares_de_conexiones()
    pares = pares_de_huesos()

    print(f"Conectando a [{nombre}] {mask_url(str(fuente))}")
    stream = CameraStream(fuente, name=nombre).start()
    t_inicio = time.perf_counter()
    while stream.read_latest() is None:
        if time.perf_counter() - t_inicio > 15.0:
            stream.stop()
            print("ERROR: no llegó ningún frame en 15 s.", file=sys.stderr)
            return 1
        time.sleep(0.05)

    try:
        detector = PoseDetector(args.model, camera=nombre)
    except FileNotFoundError as e:
        stream.stop()
        print(f"\n{e}", file=sys.stderr)
        return 1

    print("Listo. Colocate a 2-3 m para que se te vea el cuerpo entero.")
    print("espacio: pausar giro · flechas: girar · +/-: zoom · r: reiniciar · q: salir")

    alto = max(360, args.alto)
    franja = 52
    lado = alto - franja
    ancho_datos = 210

    az, el, dist = AZIMUT_INICIAL, ELEVACION_INICIAL, DISTANCIA_INICIAL
    girando = True
    ventana: deque = deque(maxlen=VENTANA_CALIDAD)
    cv_pct: float | None = None
    n_frames = 0
    n_det = 0
    t0 = time.perf_counter()
    t_prev = t0

    cv2.namedWindow(TITULO, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(TITULO, 2 * lado + ancho_datos, alto)
    try:
        while True:
            lectura = stream.read()
            if lectura is None:
                time.sleep(0.001)
                continue
            frame, ts = lectura
            if args.espejo:
                frame = cv2.flip(frame, 1)
            n_frames += 1

            lm = detector.detect(frame, ts)
            mundo = vis = None
            if lm is not None and lm.world is not None:
                n_det += 1
                mundo, vis = lm.world, lm.visibility
                m = mundo.copy()
                m[vis < 0.5] = np.nan
                ventana.append(m)
                if n_det % 10 == 0 and len(ventana) >= 20:
                    est = segment_length_stability(np.array(ventana), pares,
                                                   minimo_frames=10)
                    cv_pct = est.variacion_media * 100.0
                frame = dibujar_esqueleto_2d(frame, lm.to_pixels(), vis,
                                             conexiones)

            ahora = time.perf_counter()
            if girando:
                az += GRADOS_POR_SEGUNDO * (ahora - t_prev)
            t_prev = ahora
            fps = n_frames / max(ahora - t0, 1e-6)

            # Recorte central a cuadrado: un panel 16:9 se come la ventana y
            # deja la vista 3D —que es lo que hay que enseñar— de segunda.
            h, w = frame.shape[:2]
            if w > h:
                x0 = (w - h) // 2
                cuadro = frame[:, x0:x0 + h]
            else:
                cuadro = frame
            izq = cv2.resize(cuadro, (lado, lado), interpolation=cv2.INTER_AREA)
            _texto(izq, "camara + landmarks 2D", (12, 26), 0.52)

            centro = panel_3d(lado, mundo, vis, conexiones, az, el, dist,
                              sin_persona=mundo is None)
            der = panel_datos(ancho_datos, lado, fps, cv_pct, mundo, girando)

            fila = np.hstack([izq, centro, der])
            vista = np.vstack([fila, panel_pipeline(fila.shape[1], franja,
                                                    mundo is not None)])
            cv2.imshow(TITULO, vista)

            tecla = cv2.waitKey(1) & 0xFF
            if tecla in (ord("q"), 27):
                break
            if tecla == ord(" "):
                girando = not girando
            elif tecla == ord("r"):
                az, el, dist = (AZIMUT_INICIAL, ELEVACION_INICIAL,
                                DISTANCIA_INICIAL)
                girando = True
            elif tecla in (81, ord("a")):        # izquierda
                az -= 5.0; girando = False
            elif tecla in (83, ord("d")):        # derecha
                az += 5.0; girando = False
            elif tecla in (82, ord("w")):        # arriba
                el = min(80.0, el + 4.0); girando = False
            elif tecla in (84, ord("s")):        # abajo
                el = max(-80.0, el - 4.0); girando = False
            elif tecla in (ord("+"), ord("=")):
                dist = max(1.2, dist - 0.2)
            elif tecla in (ord("-"), ord("_")):
                dist = min(8.0, dist + 0.2)
    except KeyboardInterrupt:
        pass
    finally:
        detector.close()
        stream.stop()
        cv2.destroyAllWindows()

    print(f"\n{n_frames} frames, {n_det} con persona "
          f"({100 * n_det / max(n_frames, 1):.0f} %), "
          f"{n_frames / max(time.perf_counter() - t0, 1e-6):.1f} fps")
    if cv_pct is not None:
        print(f"Variación del largo de los huesos: {cv_pct:.1f} %")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
