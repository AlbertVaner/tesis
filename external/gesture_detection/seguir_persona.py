"""La camara sigue a la persona: MediaPipe decide, el motor obedece.

Cierra el lazo entre la pose 2D y el pan/tilt de una camara Amcrest. La
persona se mueve por el area del Robotat, el detector dice donde esta dentro
del cuadro, y la camara gira hasta volver a centrarla.

Uso, desde la raiz del repositorio::

    # Sin mover motores: valida el lazo entero e imprime lo que enviaria.
    .\\.venv\\Scripts\\python.exe .\\external\\gesture_detection\\seguir_persona.py ^
        --rtsp "rtsp://usuario:clave@IP:554/cam/realmonitor?channel=1&subtype=1" --dry-run

    # De verdad.
    .\\.venv\\Scripts\\python.exe .\\external\\gesture_detection\\seguir_persona.py ^
        --rtsp "rtsp://usuario:clave@IP:554/cam/realmonitor?channel=1&subtype=1"

Teclas: `q` salir, `espacio` pausar el seguimiento sin cerrar.

AVISO: mover la camara invalida cualquier calibracion extrinseca previa, sin
sintoma visible. Ver el docstring de `ptz/cliente.py`.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from pose.detector import PoseDetector  # noqa: E402
from pose.normalize import landmarks_to_array  # noqa: E402
from ptz import (  # noqa: E402
    Ajustes,
    CamaraPTZ,
    ControlPTZ,
    ErrorPTZ,
    Seguidor,
    centro_torso,
    resumen_capacidades,
)
from utils import calculate_fps  # noqa: E402
from video_source import abrir, enmascarar  # noqa: E402
from visualization.pose_overlay import draw_pose  # noqa: E402

VENTANA = "Seguimiento de persona - camara PTZ"
ALTO_VIDEO = 720

VERDE = (120, 240, 140)
AMBAR = (80, 200, 250)
ROJO = (90, 90, 240)
GRIS = (170, 170, 170)
BLANCO = (245, 245, 245)


def dibujar(frame, *, centro, orden, activo, ajustes, fps, pausado, posicion):
    """Overlay con la banda muerta y el estado del lazo."""
    alto, ancho = frame.shape[:2]
    medio = ancho // 2

    # Banda de arranque (fuera de aqui, la camara se mueve) y de parada.
    for fraccion, color in ((ajustes.arrancar_en, AMBAR), (ajustes.parar_en, VERDE)):
        for signo in (-1, 1):
            x = int(medio + signo * fraccion * ancho)
            cv2.line(frame, (x, 0), (x, alto), color, 1, cv2.LINE_AA)
    cv2.line(frame, (medio, 0), (medio, alto), GRIS, 1, cv2.LINE_AA)

    if centro is not None:
        cx, cy = int(centro[0] * ancho), int(centro[1] * alto)
        cv2.circle(frame, (cx, cy), 9, VERDE, 2, cv2.LINE_AA)
        cv2.line(frame, (medio, cy), (cx, cy), VERDE, 2, cv2.LINE_AA)

    estado = "PAUSADO" if pausado else (f"MOVIENDO {activo}" if activo else "centrada")
    color = GRIS if pausado else (AMBAR if activo else VERDE)
    lineas = [
        (estado, color),
        (f"fps {fps:4.1f}", BLANCO),
    ]
    if centro is None:
        lineas.insert(1, ("sin persona en cuadro", ROJO))
    else:
        lineas.insert(1, (f"error x {centro[0] - 0.5:+.3f}", BLANCO))
    if posicion is not None:
        lineas.append((f"pan {posicion[0]:.1f}  tilt {posicion[1]:.1f}", GRIS))
    if orden is not None:
        detalle = "parar" if orden.es_parada else f"{orden.codigo} v{orden.velocidad}"
        lineas.append((f"-> {detalle}", AMBAR))

    y = 30
    for texto, c in lineas:
        cv2.putText(frame, texto, (16, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, c, 2,
                    cv2.LINE_AA)
        y += 28
    cv2.putText(frame, "q salir   espacio pausa", (16, alto - 16),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, GRIS, 1, cv2.LINE_AA)
    return frame


def bucle(fuente, control: ControlPTZ, ajustes: Ajustes, *, mostrar: bool) -> int:
    captura = abrir(fuente)
    if not captura.isOpened():
        raise RuntimeError(f"No se pudo abrir {enmascarar(fuente)!r}.")

    detector = PoseDetector()
    seguidor = Seguidor(ajustes)
    anterior = 0.0
    fps = 0.0
    pausado = False

    if mostrar:
        cv2.namedWindow(VENTANA, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(VENTANA, 1280, 720)

    try:
        while True:
            ok, crudo = captura.read()
            if not ok:
                print("Se corto el video.")
                break
            alto, ancho = crudo.shape[:2]
            frame = cv2.resize(crudo, (int(ancho * ALTO_VIDEO / alto), ALTO_VIDEO))

            lm2d, _ = detector.process_full(frame)
            puntos, visibilidad = landmarks_to_array(lm2d)
            centro = (
                centro_torso(puntos, visibilidad,
                             visibilidad_min=ajustes.visibilidad_min)
                if puntos.size else None
            )

            ahora = time.monotonic()
            orden = None
            if not pausado:
                # `pedir` no bloquea: la peticion HTTP, que cuesta ~300 ms, la
                # hace el hilo de ControlPTZ. Hacerla aqui congelaba la
                # deteccion justo mientras el motor giraba.
                orden = seguidor.decidir(centro, ahora)
                control.pedir(orden)

            fps, anterior = calculate_fps(anterior)

            if mostrar:
                if lm2d is not None:
                    draw_pose(frame, lm2d, detector.connections)
                dibujar(frame, centro=centro, orden=orden, activo=seguidor.activo,
                        ajustes=ajustes, fps=fps, pausado=pausado,
                        posicion=control.posicion)
                cv2.imshow(VENTANA, frame)
                tecla = cv2.waitKey(1) & 0xFF
                if tecla == ord("q"):
                    break
                if tecla == ord(" "):
                    pausado = not pausado
                    if pausado:
                        control.pedir(seguidor.detener(ahora))
    finally:
        # Nunca dejar el motor girando: ControlPTZ.cerrar() lo confirma al
        # salir del `with` de main().
        control.pedir(seguidor.detener())
        captura.release()
        detector.close()
        if mostrar:
            cv2.destroyAllWindows()
    return control.enviadas


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--rtsp", required=True, help="URL RTSP de la camara.")
    p.add_argument("--host", help="IP para el PTZ, si difiere de la del RTSP.")
    p.add_argument("--user", help="Usuario para el PTZ, si difiere del RTSP.")
    p.add_argument("--password", help="Clave para el PTZ, si difiere del RTSP.")
    p.add_argument("--dry-run", action="store_true",
                   help="No mueve los motores: imprime lo que enviaria.")
    p.add_argument("--sin-ventana", action="store_true",
                   help="No abrir ventana; util para medir sin interfaz.")
    p.add_argument("--sin-tilt", action="store_true",
                   help="Seguir solo en horizontal.")
    p.add_argument("--velocidad-min", type=int, default=Ajustes.velocidad_min,
                   help="Velocidad con la persona apenas descentrada. "
                        f"Por defecto: {Ajustes.velocidad_min}.")
    p.add_argument("--velocidad-max", type=int, default=Ajustes.velocidad_max,
                   help="Velocidad con la persona en el borde del cuadro. "
                        f"Por defecto: {Ajustes.velocidad_max}.")
    p.add_argument("--pulso", type=float, default=Ajustes.pulso_s,
                   help="Duracion de cada paso, en segundos. 0 = movimiento "
                        f"continuo. Por defecto: {Ajustes.pulso_s}.")
    p.add_argument("--asentamiento", type=float, default=Ajustes.enfriamiento_s,
                   help="Espera MINIMA entre pasos. La real la decide la "
                        "confirmacion visual. Por defecto: "
                        f"{Ajustes.enfriamiento_s}.")
    p.add_argument("--cambio-minimo", type=float, default=Ajustes.cambio_minimo,
                   help="Cuanto tiene que moverse la persona en el cuadro para "
                        "dar por visto el paso anterior. Subirlo hace el "
                        f"seguimiento mas prudente. Por defecto: {Ajustes.cambio_minimo}.")
    p.add_argument("--espera-max", type=float, default=Ajustes.espera_max_s,
                   help="Tope de la espera por confirmacion, en segundos. "
                        f"Por defecto: {Ajustes.espera_max_s}.")
    p.add_argument("--zona-muerta", type=float, default=Ajustes.arrancar_en,
                   help="Fraccion del ancho que puede descentrarse antes de "
                        f"mover. Por defecto: {Ajustes.arrancar_en}.")
    p.add_argument("--zona-muerta-tilt", type=float,
                   help="Fraccion de la altura que puede subir o bajar el torso "
                        "antes de inclinar. Por defecto, igual que --zona-muerta.")
    p.add_argument("--centro-y", type=float, default=Ajustes.objetivo_y,
                   help="Donde dejar el torso en vertical (0 arriba, 1 abajo). "
                        "Mas de 0.5 deja aire sobre la cabeza. Por defecto: "
                        f"{Ajustes.objetivo_y}.")
    args = p.parse_args()

    zona_tilt = args.zona_muerta if args.zona_muerta_tilt is None else args.zona_muerta_tilt
    ajustes = Ajustes(
        arrancar_en=args.zona_muerta,
        parar_en=min(Ajustes.parar_en, args.zona_muerta * 0.6),
        arrancar_en_tilt=zona_tilt,
        parar_en_tilt=min(Ajustes.parar_en_tilt, zona_tilt * 0.6),
        objetivo_y=args.centro_y,
        velocidad_min=args.velocidad_min,
        velocidad_max=args.velocidad_max,
        pulso_s=args.pulso,
        enfriamiento_s=args.asentamiento,
        cambio_minimo=args.cambio_minimo,
        espera_max_s=args.espera_max,
        seguir_tilt=not args.sin_tilt,
    )

    if args.host:
        camara = CamaraPTZ(args.host, args.user or "admin", args.password or "",
                           dry_run=args.dry_run)
    else:
        camara = CamaraPTZ.desde_rtsp(args.rtsp, dry_run=args.dry_run)

    print(f"Camara PTZ: {camara.host}" + ("   [DRY-RUN, no mueve nada]"
                                          if args.dry_run else ""))
    try:
        caps = camara.capacidades()
        if caps:
            print("  " + resumen_capacidades(caps))
        pos = camara.posicion()
        if pos:
            print(f"  posicion inicial: pan {pos[0]:.1f}  tilt {pos[1]:.1f}")
            print("  ANOTALA: es la referencia para volver si hace falta.")
        try:
            tipo, serie = camara.identidad()
            print(f"  {tipo}  serie {serie}")
        except ErrorPTZ:
            pass          # informativo: que no impida arrancar
    except ErrorPTZ as exc:
        print(f"  no se pudo consultar la camara: {exc}")
        return 1

    print(f"Video: {enmascarar(args.rtsp)}")
    print(f"Zona muerta {ajustes.arrancar_en:.2f}  parada {ajustes.parar_en:.2f}"
          f"  velocidad {ajustes.velocidad_min}-{ajustes.velocidad_max}"
          f"  paso {ajustes.pulso_s:.2f}s"          f"  espera {ajustes.enfriamiento_s:.2f}s"
          f"  tilt {'si' if ajustes.seguir_tilt else 'no'}\n")

    with camara, ControlPTZ(camara) as control:
        enviadas = bucle(args.rtsp, control, ajustes,
                         mostrar=not args.sin_ventana)
    print(f"\n{enviadas} ordenes enviadas al motor.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
