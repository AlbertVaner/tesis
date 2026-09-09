"""Verifica que una cámara se puede leer, y mide los fps que realmente llegan.

Es la primera app que hay que correr con una cámara nueva. Responde tres
preguntas antes de invertir tiempo en calibrar nada:

  1. ¿Se conecta?
  2. ¿A qué resolución y a cuántos fps *reales*, no declarados?
  3. ¿Se ve bien encuadrado el cuerpo completo desde donde está la cámara?

Ejemplos
--------
Con una cámara definida en config/cameras.local.yaml::

    python apps/check_stream.py --camera cam1

Con una URL directa (cámara del teléfono, webcam, o una IP suelta)::

    python apps/check_stream.py --url rtsp://usuario:clave@192.168.1.50:554/stream1
    python apps/check_stream.py --url http://192.168.1.60:8080/video
    python apps/check_stream.py --url 0            # webcam local

Sin ventana, sólo medición, 60 segundos::

    python apps/check_stream.py --camera cam1 --duration 60 --no-display

Guardar un frame a resolución completa, sin overlay, para analizarlo aparte::

    python apps/check_stream.py --camera cam1 --save-frame
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, datetime
from pathlib import Path

# El repositorio usa layout src/. Esto permite ejecutar las apps sin instalar
# el paquete, que es lo cómodo mientras se desarrolla.
RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

import cv2  # noqa: E402

from mapeo3d.capture import CameraStream, load_config, mask_url  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Verifica una cámara y mide sus fps reales.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    fuente = p.add_mutually_exclusive_group(required=True)
    fuente.add_argument(
        "--camera",
        help="Nombre de una cámara definida en la configuración.",
    )
    fuente.add_argument(
        "--url",
        help="URL o índice de dispositivo. Se salta la configuración.",
    )
    p.add_argument("--config", help="Ruta de configuración alternativa.")
    p.add_argument(
        "--stream",
        choices=("main", "sub"),
        default="main",
        help="Stream principal o secundario. Por defecto: main.",
    )
    p.add_argument(
        "--duration",
        type=float,
        default=30.0,
        help="Segundos de medición. Por defecto: 30.",
    )
    p.add_argument(
        "--no-display",
        action="store_true",
        help="No abrir ventana de vídeo; sólo medir.",
    )
    p.add_argument(
        "--display-width",
        type=int,
        default=960,
        help=(
            "Ancho máximo de la ventana, en píxeles. Sólo afecta a lo que se "
            "MUESTRA: el frame se procesa siempre a resolución completa. "
            "0 = sin reescalar. Por defecto: 960."
        ),
    )
    p.add_argument(
        "--save-frame",
        nargs="?",
        const="",
        metavar="RUTA",
        help=(
            "Guardar un frame y salir. Sin RUTA usa "
            "results/captures/<fecha>/<camara>_<hora>.jpg. Se guarda a "
            "RESOLUCIÓN COMPLETA y SIN overlay: es el frame tal como lo "
            "recibe el pipeline, que es lo que hay que analizar. Una foto de "
            "la pantalla no sirve para eso."
        ),
    )
    p.add_argument(
        "--warmup",
        type=float,
        default=3.0,
        help=(
            "Segundos de espera antes de guardar con --save-frame. Da tiempo "
            "a que la exposición automática se estabilice y a colocarse "
            "delante de la cámara. Por defecto: 3."
        ),
    )
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args()


def guardar_frame(stream, nombre: str, destino: str) -> int:
    """Escribe un frame a disco, a resolución completa y sin overlay."""
    ruta = Path(destino) if destino else (
        RAIZ / "results" / "captures" / date.today().isoformat()
        / f"{nombre}_{datetime.now().strftime('%H%M%S')}.jpg"
    )
    ruta.parent.mkdir(parents=True, exist_ok=True)

    resultado = stream.read_latest()
    if resultado is None:
        print("ERROR: no hay ningún frame que guardar.", file=sys.stderr)
        return 1
    frame, _ts = resultado
    if not cv2.imwrite(str(ruta), frame):
        print(f"ERROR: no se pudo escribir {ruta}", file=sys.stderr)
        return 1

    alto, ancho = frame.shape[:2]
    print(f"Frame guardado: {ruta}")
    print(f"  {ancho}x{alto}, {ruta.stat().st_size / 1024:.0f} kB")
    return 0


def resolver_fuente(args: argparse.Namespace) -> tuple[str | int, str, float]:
    """Devuelve (fuente, nombre, fps_esperados)."""
    if args.url is not None:
        # Un argumento puramente numérico es un índice de webcam local.
        fuente: str | int = int(args.url) if args.url.isdigit() else args.url
        return fuente, "url", 0.0

    cfg = load_config(args.config)
    cam = cfg.camera(args.camera)
    return cam.url(args.stream), cam.name, float(cfg.capture.target_fps)


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    fuente, nombre, fps_esperados = resolver_fuente(args)
    mostrado = mask_url(str(fuente))
    print(f"Conectando a [{nombre}] {mostrado}")

    stream = CameraStream(fuente, name=nombre)
    stream.start()

    # Esperar el primer frame antes de empezar a medir, para no contar el
    # tiempo de negociación RTSP como si fueran frames perdidos.
    inicio_espera = time.monotonic()
    while stream.read_latest() is None:
        if time.monotonic() - inicio_espera > 15.0:
            print("ERROR: no llegó ningún frame en 15 s.", file=sys.stderr)
            print(
                "Revisar: IP correcta, cuenta de cámara creada, puerto 554 "
                "accesible, y que el PC esté en la misma red.",
                file=sys.stderr,
            )
            stream.stop()
            return 1
        time.sleep(0.1)

    print(f"Conectado. Resolución: {stream.resolucion}, "
          f"fps declarados: {stream.fps_declarados:.1f}")

    if args.save_frame is not None:
        if args.warmup > 0:
            print(f"Esperando {args.warmup:.0f} s (exposición automática)…")
            time.sleep(args.warmup)
        try:
            return guardar_frame(stream, nombre, args.save_frame)
        finally:
            stream.stop()
    if not args.no_display:
        print("Ventana abierta. Pulsa 'q' o ESC para terminar antes de tiempo.")

    # Reiniciar estadísticas para no contar el arranque.
    stream.stats.frames_recibidos = 0
    stream.stats.primer_frame_t = None
    stream.stats.ultimo_frame_t = None

    t0 = time.monotonic()
    ventana = f"check_stream — {nombre}"
    escala = 1.0
    if not args.no_display:
        # WINDOW_NORMAL permite que el usuario redimensione y evita que una
        # ventana mayor que la pantalla se vea recortada, que es lo que
        # produce la falsa impresión de que la cámara tiene zoom.
        cv2.namedWindow(ventana, cv2.WINDOW_NORMAL)
        if args.display_width > 0 and stream.resolucion:
            ancho_original = stream.resolucion[0]
            if ancho_original > args.display_width:
                escala = args.display_width / ancho_original
            alto_ventana = int(round(stream.resolucion[1] * escala))
            cv2.resizeWindow(
                ventana, int(round(ancho_original * escala)), alto_ventana
            )
        if escala < 1.0:
            print(
                f"Vista reducida al {escala * 100:.0f}% para que quepa en "
                "pantalla. El procesamiento usa la resolución completa."
            )
    try:
        while time.monotonic() - t0 < args.duration:
            resultado = stream.read()
            if resultado is None:
                time.sleep(0.001)
                continue

            if not args.no_display:
                frame, _ts = resultado
                if escala < 1.0:
                    # Sólo la vista. El frame original no se toca.
                    frame = cv2.resize(
                        frame, None, fx=escala, fy=escala,
                        interpolation=cv2.INTER_AREA,
                    )
                transcurrido = time.monotonic() - t0
                vista = f"  vista {escala * 100:.0f}%" if escala < 1.0 else ""
                overlay = [
                    f"{nombre}  {stream.resolucion}{vista}",
                    f"fps recibidos: {stream.stats.fps_recibidos:5.2f}",
                    f"t: {transcurrido:5.1f}/{args.duration:.0f} s",
                ]
                for i, linea in enumerate(overlay):
                    y = 30 + i * 28
                    cv2.putText(frame, linea, (12, y), cv2.FONT_HERSHEY_SIMPLEX,
                                0.7, (0, 0, 0), 4, cv2.LINE_AA)
                    cv2.putText(frame, linea, (12, y), cv2.FONT_HERSHEY_SIMPLEX,
                                0.7, (0, 255, 0), 1, cv2.LINE_AA)
                cv2.imshow(ventana, frame)
                if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                    break
    except KeyboardInterrupt:
        pass
    finally:
        stream.stop()
        if not args.no_display:
            cv2.destroyAllWindows()

    print()
    print("--- Resultado ---")
    print(f"Cámara:            {nombre}")
    print(f"Resolución:        {stream.resolucion}")
    print(f"fps declarados:    {stream.fps_declarados:.2f}")
    print(f"fps recibidos:     {stream.stats.fps_recibidos:.2f}")
    print(stream.stats.resumen())

    # La comprobación que importa: docs/capture.md exige verificar los fps
    # reales, porque la exposición automática puede bajarlos en silencio.
    referencia = fps_esperados or stream.fps_declarados
    if referencia > 0:
        recibidos = stream.stats.fps_recibidos
        desviacion = abs(recibidos - referencia) / referencia
        print(f"Esperados:         {referencia:.2f}")
        if desviacion > 0.10:
            print(
                f"AVISO: los fps recibidos se desvían un {desviacion * 100:.0f}% "
                "de lo esperado (umbral 10%). Causas probables: luz insuficiente "
                "con exposición automática, red saturada, o CPU al límite.\n"
                "Ver docs/capture.md, 'Verificación obligatoria del frame rate'."
            )
            return 2
        print("fps dentro de tolerancia.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
