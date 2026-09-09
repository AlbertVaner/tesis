"""Mide la calidad de la pose 3D **monocular** de MediaPipe (`pose_world_landmarks`).

Es el nivel 0 del sistema: 3D métrico del cuerpo con **una sola cámara y cero
calibración**. Sirve para responder rápido si un vocabulario de gestos es
separable en 3D, antes de invertir en montar y calibrar seis cámaras.

Qué es y qué no es
------------------
`pose_world_landmarks` da metros con origen en el punto medio de las caderas.
Es 3D de verdad, pero **la profundidad sale de un prior aprendido, no de
geometría**: no sabe dónde está el sujeto en la sala y no sustituye a la
triangulación. Ver docs/pose.md.

Su debilidad es específica y esta app la hace visible: los movimientos **a lo
largo del eje óptico** —empujar la mano hacia la cámara— son los que peor
estima, y el resultado parpadea entre frames.

Cómo se mide sin verdad de terreno
----------------------------------
Por la **constancia de la longitud de los huesos**. Un antebrazo mide lo mismo
en todos los frames pase lo que pase; la desviación de su longitud reconstruida
es una medida directa de la calidad del 3D, y no necesita MoCap, ni marcadores,
ni calibración. Es la misma medida que se aplicará después a la triangulación,
así que los dos números son comparables. Ver docs/triangulation.md.

Ejemplos
--------
Con la webcam del portátil::

    python apps/check_pose3d.py --url 0

Con una cámara de la configuración, grabando para analizar después::

    python apps/check_pose3d.py --camera cam1 --record --duration 60

Sólo medir, sin ventana::

    python apps/check_pose3d.py --url 0 --no-display --duration 30
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import deque
from datetime import date, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from mapeo3d.capture import CameraStream, load_config, mask_url  # noqa: E402
from mapeo3d.pose import (  # noqa: E402
    HUESOS,
    NOMBRES,
    PoseDetector,
    dibujar_esqueleto_2d,
    pares_de_conexiones,
    pares_de_huesos,
)
from mapeo3d.triangulation import segment_length_stability  # noqa: E402

# Media altura del cuadro 3D, en metros. **Fijo a propósito**: una vista que
# se autoescala hace imposible juzgar a ojo si el esqueleto está temblando,
# que es justo lo que se viene a mirar.
RANGO_M = 1.0

# Frames sobre los que se calcula la estabilidad en vivo. A 30 fps son 5 s:
# suficiente para que la cifra sea estable y corto para que reaccione.
VENTANA = 150


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Mide la calidad de la pose 3D monocular de MediaPipe.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    fuente = p.add_mutually_exclusive_group(required=True)
    fuente.add_argument("--camera", help="Cámara definida en la configuración.")
    fuente.add_argument("--url", help="URL o índice de dispositivo.")

    p.add_argument("--config", help="Ruta de configuración alternativa.")
    p.add_argument("--model", help="Ruta del .task de MediaPipe.")
    p.add_argument("--duration", type=float, default=0.0,
                   help="Segundos a medir. 0 = hasta pulsar 'q'.")
    p.add_argument("--record", action="store_true",
                   help="Guardar la sesión en results/data/pose3d/<fecha>/.")
    p.add_argument("--out", help="Ruta del .npz de salida.")
    p.add_argument("--min-visibilidad", type=float, default=0.5,
                   help="Por debajo de esto el landmark no cuenta para las "
                        "métricas. Por defecto: 0.5.")
    p.add_argument("--no-display", action="store_true",
                   help="No abrir ventana; sólo medir.")
    p.add_argument("--display-width", type=int, default=640,
                   help="Ancho del panel de cámara. Por defecto: 640.")
    return p.parse_args()


def resolver_fuente(args) -> tuple[str | int, str]:
    if args.url is not None:
        return (int(args.url) if args.url.isdigit() else args.url), "url"
    cfg = load_config(args.config)
    cam = cfg.camera(args.camera)
    return cam.url(), cam.name


# ------------------------------------------------------------------ dibujo


def _proyectar(puntos: np.ndarray, eje_h: int, eje_v: int, lado: int,
               invertir_v: bool = False) -> np.ndarray:
    """Proyección ortográfica de los puntos 3D a píxeles de un panel."""
    h = puntos[:, eje_h]
    v = puntos[:, eje_v]
    if invertir_v:
        v = -v
    cx = cy = lado / 2.0
    escala = (lado / 2.0) / RANGO_M
    return np.stack([cx + h * escala, cy + v * escala], axis=1)


def _panel_3d(mundo: np.ndarray, vis: np.ndarray, conexiones: np.ndarray,
              lado: int, titulo: str, eje_h: int, eje_v: int,
              etiqueta_h: str, etiqueta_v: str,
              invertir_v: bool = False) -> np.ndarray:
    panel = np.full((lado, lado, 3), 28, np.uint8)
    # Ejes de referencia por el origen, que son las caderas.
    cv2.line(panel, (lado // 2, 0), (lado // 2, lado), (55, 55, 55), 1)
    cv2.line(panel, (0, lado // 2), (lado, lado // 2), (55, 55, 55), 1)

    if mundo is not None:
        pts = _proyectar(mundo, eje_h, eje_v, lado, invertir_v)
        for a, b in conexiones:
            if vis[a] < 0.3 or vis[b] < 0.3:
                continue
            pa = tuple(np.round(pts[a]).astype(int))
            pb = tuple(np.round(pts[b]).astype(int))
            cv2.line(panel, pa, pb, (90, 200, 120), 2, cv2.LINE_AA)
        for i, p in enumerate(pts):
            if vis[i] < 0.3:
                continue
            c = (60, 220, 255) if vis[i] > 0.7 else (60, 130, 180)
            cv2.circle(panel, tuple(np.round(p).astype(int)), 3, c, -1,
                       cv2.LINE_AA)

    cv2.putText(panel, titulo, (8, lado - 9), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                (200, 200, 200), 1, cv2.LINE_AA)
    cv2.putText(panel, etiqueta_h, (lado - 20, lado // 2 - 6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (120, 120, 120), 1, cv2.LINE_AA)
    cv2.putText(panel, etiqueta_v, (lado // 2 + 6, 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (120, 120, 120), 1, cv2.LINE_AA)
    return panel


def _corto(nombre: str) -> str:
    """`left_shoulder` -> `L.shoulder`, para que quepa en el panel."""
    return nombre.replace("left_", "L.").replace("right_", "R.")


def _panel_texto(lineas: list[tuple], lado: int) -> np.ndarray:
    """Panel de texto. Cada línea es `(texto, color)` o `(texto, color, escala)`."""
    panel = np.full((lado, lado, 3), 28, np.uint8)
    y = 24
    for entrada in lineas:
        texto, color = entrada[0], entrada[1]
        escala = entrada[2] if len(entrada) > 2 else 0.45
        # Encoger sólo lo que no cabe, en vez de recortarlo en silencio.
        (ancho, _), _ = cv2.getTextSize(texto, cv2.FONT_HERSHEY_SIMPLEX,
                                        escala, 1)
        if ancho > lado - 18:
            escala *= (lado - 18) / ancho
        cv2.putText(panel, texto, (9, y), cv2.FONT_HERSHEY_SIMPLEX, escala,
                    color, 1, cv2.LINE_AA)
        y += 22
    return panel


# ----------------------------------------------------------------- métricas


def estabilidad(buffer: deque, pares: np.ndarray):
    """Estabilidad de huesos sobre la ventana, o None si no hay bastante."""
    if len(buffer) < 20:
        return None
    return segment_length_stability(np.array(buffer), pares, minimo_frames=10)


def informe_final(mundos: list, pares: np.ndarray, huesos, n_frames: int,
                  n_detectados: int, fps: float) -> None:
    print()
    print("--- Resultado ---")
    print(f"Frames procesados:  {n_frames}")
    tasa = 100.0 * n_detectados / max(n_frames, 1)
    print(f"Con persona:        {n_detectados} ({tasa:.0f} %)")
    print(f"fps de proceso:     {fps:.1f}")

    if len(mundos) < 20:
        print("\nMuy pocas detecciones para medir estabilidad.")
        return

    est = segment_length_stability(np.array(mundos), pares, minimo_frames=10)
    print()
    print(est.resumen([f"{a}-{b}" for a, b in huesos]))

    cv_ = est.variacion_media * 100.0
    print()
    print("La variación es la desviación de la longitud del hueso dividida por")
    print("su media. Es la medida de calidad del 3D: un hueso rígido no puede")
    print("cambiar de largo, así que todo lo que varía es error.")
    print()
    if cv_ < 3.0:
        print(f"  {cv_:.1f} % — muy estable para ser monocular.")
    elif cv_ < 8.0:
        print(f"  {cv_:.1f} % — utilizable para gestos de forma amplia "
              "(brazos arriba, torso).")
    else:
        print(f"  {cv_:.1f} % — inestable. Sirve para poses muy distintas "
              "entre sí, no para\n  distinguir gestos parecidos.")
    print()
    print("Comparar este número con el de la triangulación calibrada sobre la")
    print("misma grabación es la medida honesta de cuánto aporta calibrar.")


def guardar(mundos, viss, tiempos, nombre, destino) -> Path:
    ruta = Path(destino) if destino else (
        RAIZ / "results" / "data" / "pose3d" / date.today().isoformat()
        / f"{nombre}_{datetime.now().strftime('%H%M%S')}.npz"
    )
    ruta.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        ruta,
        world=np.array(mundos, np.float32),
        visibility=np.array(viss, np.float32),
        timestamps=np.array(tiempos, np.float64),
        nombres=np.array(NOMBRES),
        fuente="pose_world_landmarks",
    )
    return ruta


# --------------------------------------------------------------------- main


def main() -> int:
    args = parse_args()
    fuente, nombre = resolver_fuente(args)
    conexiones = pares_de_conexiones()
    pares = pares_de_huesos()

    print(f"Conectando a [{nombre}] {mask_url(str(fuente))}")
    stream = CameraStream(fuente, name=nombre).start()
    inicio = time.perf_counter()
    while stream.read_latest() is None:
        if time.perf_counter() - inicio > 15.0:
            stream.stop()
            print("ERROR: no llegó ningún frame en 15 s.", file=sys.stderr)
            return 1
        time.sleep(0.05)
    print(f"Conectado. Resolución {stream.resolucion}.")

    try:
        detector = PoseDetector(args.model, camera=nombre)
    except FileNotFoundError as e:
        stream.stop()
        print(f"\n{e}", file=sys.stderr)
        return 1
    print(f"Modelo: {detector.model_path.name}")
    if not args.no_display:
        print("Ventana abierta. 'q' o ESC para terminar.")

    mundos: list[np.ndarray] = []
    viss: list[np.ndarray] = []
    tiempos: list[float] = []
    ventana_mundo: deque = deque(maxlen=VENTANA)

    n_frames = 0
    n_detectados = 0
    t0 = time.perf_counter()
    est = None
    titulo = f"check_pose3d — {nombre}"
    if not args.no_display:
        cv2.namedWindow(titulo, cv2.WINDOW_NORMAL)

    try:
        while True:
            if args.duration > 0 and time.perf_counter() - t0 > args.duration:
                break
            lectura = stream.read()
            if lectura is None:
                time.sleep(0.001)
                continue
            frame, ts = lectura
            n_frames += 1

            lm = detector.detect(frame, ts)
            mundo = vis = pix = None
            if lm is not None and lm.world is not None:
                n_detectados += 1
                mundo, vis, pix = lm.world, lm.visibility, lm.to_pixels()
                # Un landmark poco visible mete ruido en las longitudes; se
                # marca NaN para que la métrica lo ignore en lugar de contarlo.
                mundo_metrica = mundo.copy()
                mundo_metrica[vis < args.min_visibilidad] = np.nan
                ventana_mundo.append(mundo_metrica)
                if args.record:
                    mundos.append(mundo_metrica)
                    viss.append(vis)
                    tiempos.append(ts)
                elif len(mundos) < 100000:
                    mundos.append(mundo_metrica)
                if n_detectados % 10 == 0:
                    est = estabilidad(ventana_mundo, pares)

            if args.no_display:
                continue

            escala = min(1.0, args.display_width / max(frame.shape[1], 1))
            izq = frame if pix is None else dibujar_esqueleto_2d(
                frame, pix, vis, conexiones)
            izq = cv2.resize(izq, None, fx=escala, fy=escala,
                             interpolation=cv2.INTER_AREA)
            alto = izq.shape[0]
            lado = alto // 2

            # MediaPipe: x a la derecha, y hacia ABAJO, z crece alejándose de
            # la cámara. Por eso la vista superior invierte z: así "arriba" en
            # el panel es "lejos", que es como se lee un plano de planta.
            frontal = _panel_3d(mundo, vis, conexiones, lado, "frontal",
                                0, 1, "x", "y")
            perfil = _panel_3d(mundo, vis, conexiones, lado, "perfil",
                               2, 1, "z", "y")
            planta = _panel_3d(mundo, vis, conexiones, lado,
                               "planta · arriba = lejos",
                               0, 2, "x", "z", invertir_v=True)

            transcurrido = time.perf_counter() - t0
            fps = n_frames / max(transcurrido, 1e-6)
            tasa = 100.0 * n_detectados / max(n_frames, 1)
            lineas = [
                (f"{fps:5.1f} fps", (200, 200, 200)),
                (f"deteccion {tasa:3.0f} %",
                 (90, 220, 90) if tasa > 80 else (60, 160, 230)),
                ("", (0, 0, 0)),
            ]
            if est is not None:
                cv_ = est.variacion_media * 100.0
                color = ((90, 220, 90) if cv_ < 3 else
                         (60, 200, 230) if cv_ < 8 else (80, 80, 240))
                lineas.append((f"variacion huesos {cv_:.1f} %", color))
                lineas.append((f"(ventana de {len(ventana_mundo)} frames)",
                               (140, 140, 140)))
                peor = int(np.nanargmax(np.where(
                    np.isfinite(est.variacion), est.variacion, -1)))
                lineas.append(("peor hueso:", (140, 140, 140), 0.40))
                lineas.append(("-".join(_corto(n) for n in HUESOS[peor]),
                               (140, 140, 140), 0.40))
            else:
                lineas.append(("midiendo...", (140, 140, 140)))
            if mundo is None:
                lineas.append(("SIN PERSONA", (80, 80, 240)))

            der = np.vstack([np.hstack([frontal, perfil]),
                             np.hstack([planta, _panel_texto(lineas, lado)])])
            if der.shape[0] != izq.shape[0]:
                der = cv2.resize(der, (izq.shape[0], izq.shape[0]))
            cv2.imshow(titulo, np.hstack([izq, der]))
            if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                break
    except KeyboardInterrupt:
        pass
    finally:
        detector.close()
        stream.stop()
        if not args.no_display:
            cv2.destroyAllWindows()

    fps = n_frames / max(time.perf_counter() - t0, 1e-6)
    informe_final(mundos, pares, HUESOS, n_frames, n_detectados, fps)
    print(f"\nCámara: {stream.stats.resumen()}")

    if args.record and mundos:
        ruta = guardar(mundos, viss, tiempos, nombre, args.out)
        print(f"\nSesión guardada en {ruta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
