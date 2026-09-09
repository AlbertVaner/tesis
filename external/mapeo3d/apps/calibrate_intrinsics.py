"""Calibra los intrínsecos de una cámara con un tablero de ajedrez.

Además de la matriz de cámara y la distorsión, devuelve el **campo de visión
real** derivado del ajuste, que es el número que decide a qué distancia hay que
poner la cámara para que una persona quepa entera. Sustituye a medirlo con
cinta métrica.

Los intrínsecos son propiedad del lente: sobreviven a mover la cámara y sólo se
invalidan si cambia la resolución del stream. Se calibran una vez.

Ejemplos
--------
En vivo, capturando automáticamente cuando el tablero se detecta::

    python apps/calibrate_intrinsics.py --camera cam1

Con un tablero distinto del de por defecto (9x6 esquinas, casilla de 25 mm)::

    python apps/calibrate_intrinsics.py --camera cam1 --cols 7 --rows 5 --square-mm 30

Desde una carpeta de fotos ya tomadas::

    python apps/calibrate_intrinsics.py --images results\\calibration\\fotos_cam1 --name cam1

Cómo tomar buenas vistas
------------------------
Unas 20, y que sean **distintas entre sí**:

- El tablero cerca y lejos.
- En las cuatro esquinas del cuadro y en el centro, no siempre en medio.
- Inclinado en varias direcciones, no siempre de frente. Las vistas frontales
  no informan sobre la focal, y una calibración hecha sólo con ellas estima
  mal el zoom.
- Rígido y plano: pegado a un cartón, no sostenido a pulso doblándose.
- Bien iluminado y sin movimiento: si la imagen sale movida, las esquinas
  salen sesgadas y el ajuste hereda el sesgo.

La app avisa de la cobertura del cuadro conforme captura.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from mapeo3d.calibration import (  # noqa: E402
    EXTENT_MINIMO,
    EXTENT_OBJETIVO,
    ChessboardSpec,
    calibrate,
    cargar_puntos,
    corner_centroid,
    corner_extent,
    corner_movement,
    corner_span,
    diagnosticar,
    draw_corners,
    escribir_reporte,
    find_corners,
    find_corners_preview,
    guardar_puntos,
)
from mapeo3d.capture import CameraStream, load_config, mask_url  # noqa: E402

EXTENSIONES = (".jpg", ".jpeg", ".png", ".bmp")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Calibra los intrínsecos de una cámara.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    fuente = p.add_mutually_exclusive_group(required=True)
    fuente.add_argument("--camera", help="Cámara definida en la configuración.")
    fuente.add_argument("--url", help="URL o índice de dispositivo.")
    fuente.add_argument(
        "--images", help="Carpeta con imágenes ya tomadas, en lugar de capturar."
    )
    fuente.add_argument(
        "--from-points",
        help="Recalibrar desde un .npz de esquinas ya capturadas. Evita repetir "
             "la sesión de capturas si algo falló después.",
    )

    p.add_argument("--name", help="Nombre para etiquetar el resultado.")
    p.add_argument("--config", help="Ruta de configuración alternativa.")

    p.add_argument("--cols", type=int, default=9,
                   help="Esquinas interiores a lo ancho. Por defecto: 9.")
    p.add_argument("--rows", type=int, default=6,
                   help="Esquinas interiores a lo alto. Por defecto: 6.")
    p.add_argument("--square-mm", type=float, default=25.0,
                   help="Lado de casilla en mm, MEDIDO sobre el papel impreso.")

    p.add_argument("--target", type=int, default=20,
                   help="Vistas a capturar. Por defecto: 20.")
    p.add_argument("--cooldown", type=float, default=1.5,
                   help="Segundos mínimos entre capturas. Por defecto: 1.5.")
    p.add_argument("--max-movement", type=float, default=2.0,
                   help="Movimiento máximo del tablero entre frames, en píxeles, "
                        "para capturar automáticamente. Evita guardar frames "
                        "movidos, que es lo que dispara el RMS. 0 desactiva la "
                        "comprobación. Por defecto: 2.0.")
    p.add_argument("--min-extent", type=float, default=EXTENT_MINIMO,
                   help="Fracción mínima del ancho de la imagen que debe ocupar "
                        "el tablero para capturar automáticamente. Es LA variable "
                        f"que determina la calidad. Por defecto: {EXTENT_MINIMO}. "
                        "ESPACIO fuerza la captura igualmente.")
    p.add_argument("--display-width", type=int, default=960,
                   help="Ancho de la ventana. Sólo afecta a la vista.")
    p.add_argument("--detect-width", type=int, default=960,
                   help="Ancho al que se reduce la imagen para BUSCAR el tablero "
                        "en vivo. Al capturar se vuelve a detectar a resolución "
                        "completa. Bajarlo si la vista va lenta. Por defecto: 960.")
    p.add_argument("--detect-every", type=int, default=1,
                   help="Buscar el tablero 1 de cada N frames. Subirlo si la "
                        "vista sigue lenta. Por defecto: 1.")
    p.add_argument("--out", help="Carpeta de salida. Por defecto: results/calibration/<fecha>.")
    p.add_argument("--save-frames", action="store_true",
                   help="Guardar también las imágenes usadas.")
    return p.parse_args()


def resolver_fuente(args: argparse.Namespace) -> tuple[str | int, str]:
    if args.url is not None:
        fuente: str | int = int(args.url) if args.url.isdigit() else args.url
        return fuente, args.name or "url"
    cfg = load_config(args.config)
    cam = cfg.camera(args.camera)
    return cam.url("main"), args.name or cam.name


def _es_vista_nueva(
    centro: tuple[float, float],
    area: float,
    anteriores: list[tuple[tuple[float, float], float]],
    tamano: tuple[int, int],
) -> bool:
    """Rechaza vistas casi idénticas a otra ya capturada.

    Veinte fotos del tablero en el mismo sitio no son veinte vistas: son una,
    repetida. El ajuste queda mal condicionado y el RMS engaña.
    """
    umbral_px = 0.08 * max(tamano)
    for (cx, cy), a in anteriores:
        cerca = np.hypot(centro[0] - cx, centro[1] - cy) < umbral_px
        mismo_tamano = abs(area - a) < 0.15 * max(a, 1e-6)
        if cerca and mismo_tamano:
            return False
    return True


def capturar_en_vivo(
    args: argparse.Namespace, spec: ChessboardSpec
) -> tuple[list[np.ndarray], tuple[int, int], list[np.ndarray]]:
    fuente, nombre = resolver_fuente(args)
    print(f"Conectando a [{nombre}] {mask_url(str(fuente))}")
    print(f"Patrón: {spec.describe()}")

    stream = CameraStream(fuente, name=nombre).start()
    inicio = time.monotonic()
    while stream.read_latest() is None:
        if time.monotonic() - inicio > 15.0:
            stream.stop()
            raise SystemExit("ERROR: no llegó ningún frame en 15 s.")
        time.sleep(0.1)

    tamano = stream.resolucion or (0, 0)
    print(f"Conectado. Resolución {tamano[0]}×{tamano[1]}.")
    print("ESPACIO fuerza una captura · 'q' o ESC termina · 'd' descarta la última")
    print(
        f"El tablero debe ocupar al menos el {args.min_extent * 100:.0f} % del "
        f"ancho del cuadro (objetivo {EXTENT_OBJETIVO * 100:.0f} %). Si sale "
        f"«MUY LEJOS», acercarlo: es lo que más determina la calidad."
    )
    if args.max_movement > 0:
        print(
            f"Sólo captura con el tablero quieto (movimiento < "
            f"{args.max_movement:.1f} px entre frames). Colocarlo, soltarlo, "
            f"esperar a que diga «LISTO»."
        )

    escala = 1.0
    ventana = f"calibrate_intrinsics — {nombre}"
    cv2.namedWindow(ventana, cv2.WINDOW_NORMAL)
    if args.display_width > 0 and tamano[0] > args.display_width:
        escala = args.display_width / tamano[0]
        cv2.resizeWindow(
            ventana, args.display_width, int(round(tamano[1] * escala))
        )

    puntos: list[np.ndarray] = []
    frames: list[np.ndarray] = []
    meta: list[tuple[tuple[float, float], float]] = []
    ultima = 0.0
    n_frame = 0
    esquinas_prev: np.ndarray | None = None
    esquinas_antes: np.ndarray | None = None
    movimiento = float("inf")
    ms_deteccion = 0.0

    try:
        while len(puntos) < args.target:
            resultado = stream.read()
            if resultado is None:
                time.sleep(0.001)
                continue
            frame, _ts = resultado
            n_frame += 1

            # Detección BARATA para la vista: sobre la imagen reducida y sin
            # el detector exhaustivo. Buscar el tablero a resolución completa
            # en cada frame es lo que hace que la vista vaya a tirones.
            if n_frame % max(1, args.detect_every) == 0:
                t_det = time.perf_counter()
                anterior = esquinas_prev
                esquinas_prev = find_corners_preview(frame, spec, args.detect_width)
                ms_deteccion = (time.perf_counter() - t_det) * 1000.0

                # Cuánto se movió el tablero desde la detección anterior. Un
                # frame movido no es una vista algo peor: es la observación de
                # un tablero deformado por el movimiento, y contamina el ajuste
                # entero. Mejor esperar a que quede quieto que descartarlo
                # después.
                movimiento = corner_movement(anterior, esquinas_prev)

            esquinas = esquinas_prev
            vista = frame if esquinas is None else draw_corners(frame, spec, esquinas)

            forzar = False
            if escala < 1.0:
                vista = cv2.resize(vista, None, fx=escala, fy=escala,
                                   interpolation=cv2.INTER_AREA)

            listo = esquinas is not None
            ahora = time.monotonic()
            nueva = False
            extent = 0.0
            bastante_grande = False
            if listo:
                centro = corner_centroid(esquinas)
                area = corner_span(esquinas, tamano)
                extent = corner_extent(esquinas, tamano)
                bastante_grande = extent >= args.min_extent
                nueva = _es_vista_nueva(centro, area, meta, tamano)

            quieto = args.max_movement <= 0 or movimiento <= args.max_movement

            if not listo:
                estado = "sin tablero"
            elif not bastante_grande:
                estado = "MUY LEJOS: acercalo"
            elif not nueva:
                estado = "repetida: movelo"
            elif not quieto:
                estado = "EN MOVIMIENTO: espera"
            else:
                estado = "LISTO"

            color = (
                (0, 255, 0) if (listo and nueva and bastante_grande and quieto)
                else (0, 200, 255) if listo
                else (0, 0, 255)
            )
            mov = "-" if movimiento == float("inf") else f"{movimiento:.1f}"
            texto = [
                f"{len(puntos)}/{args.target} vistas   {estado}",
                f"tablero: {extent * 100:3.0f}% del ancho "
                f"(objetivo {EXTENT_OBJETIVO * 100:.0f}%, minimo "
                f"{args.min_extent * 100:.0f}%)",
                f"movimiento: {mov} px (max {args.max_movement:.1f})",
                f"deteccion: {ms_deteccion:.0f} ms   ESPACIO fuerza · q termina",
            ]
            for i, linea in enumerate(texto):
                y = 30 + i * 28
                cv2.putText(vista, linea, (12, y), cv2.FONT_HERSHEY_SIMPLEX,
                            0.7, (0, 0, 0), 4, cv2.LINE_AA)
                cv2.putText(vista, linea, (12, y), cv2.FONT_HERSHEY_SIMPLEX,
                            0.7, color, 1, cv2.LINE_AA)
            cv2.imshow(ventana, vista)

            tecla = cv2.waitKey(1) & 0xFF
            if tecla in (ord("q"), 27):
                break
            if tecla == ord(" "):
                forzar = True
            if tecla == ord("d") and puntos:
                puntos.pop(); meta.pop()
                if frames:
                    frames.pop()
                print(f"  descartada; quedan {len(puntos)}")

            if listo and (
                forzar
                or (nueva and bastante_grande and quieto
                    and ahora - ultima >= args.cooldown)
            ):
                # Precisión: se re-detecta sobre el frame COMPLETO y con
                # refinamiento subpíxel. Las esquinas de la vista previa vienen
                # de una imagen reducida y no valen para calibrar.
                exactas = find_corners(frame, spec)
                if exactas is None:
                    print("  (la detección precisa falló en ese frame; se salta)")
                else:
                    puntos.append(exactas)
                    meta.append(
                        (corner_centroid(exactas), corner_span(exactas, tamano))
                    )
                    if args.save_frames:
                        frames.append(frame.copy())
                    ultima = ahora
                    print(f"  vista {len(puntos)}/{args.target} capturada")
    finally:
        stream.stop()
        cv2.destroyAllWindows()

    return puntos, tamano, frames


def cargar_de_carpeta(
    carpeta: Path, spec: ChessboardSpec
) -> tuple[list[np.ndarray], tuple[int, int], list[np.ndarray]]:
    archivos = sorted(
        p for p in carpeta.iterdir() if p.suffix.lower() in EXTENSIONES
    )
    if not archivos:
        raise SystemExit(f"No hay imágenes en {carpeta}")

    puntos: list[np.ndarray] = []
    tamano: tuple[int, int] | None = None
    for archivo in archivos:
        imagen = cv2.imread(str(archivo))
        if imagen is None:
            print(f"  {archivo.name}: ilegible, se salta")
            continue
        alto, ancho = imagen.shape[:2]
        if tamano is None:
            tamano = (ancho, alto)
        elif (ancho, alto) != tamano:
            # Mezclar resoluciones invalida el ajuste: los intrínsecos son
            # específicos de la resolución.
            print(f"  {archivo.name}: resolución distinta ({ancho}×{alto}), se salta")
            continue

        esquinas = find_corners(imagen, spec)
        if esquinas is None:
            print(f"  {archivo.name}: sin tablero")
            continue
        puntos.append(esquinas)
        print(f"  {archivo.name}: OK")

    if tamano is None:
        raise SystemExit("Ninguna imagen legible.")
    return puntos, tamano, []


def main() -> int:
    args = parse_args()
    spec = ChessboardSpec(cols=args.cols, rows=args.rows, square_mm=args.square_mm)

    salida = (
        Path(args.out) if args.out
        else Path("results/calibration") / date.today().isoformat()
    )
    frames: list = []

    if args.from_points:
        puntos, spec, tamano, nombre = cargar_puntos(args.from_points)
        nombre = args.name or nombre
        print(f"Recalibrando desde {args.from_points}")
        print(f"Patrón: {spec.describe()}")
    elif args.images:
        nombre = args.name or Path(args.images).name
        print(f"Leyendo imágenes de {args.images}")
        print(f"Patrón: {spec.describe()}")
        puntos, tamano, frames = cargar_de_carpeta(Path(args.images), spec)
    else:
        _fuente, nombre = resolver_fuente(args)
        puntos, tamano, frames = capturar_en_vivo(args, spec)

    print(f"\n{len(puntos)} vistas válidas.")

    # Persistir las esquinas ANTES de calibrar. Capturarlas cuesta diez minutos
    # de trabajo manual; calibrar cuesta segundos. Si algo falla después, se
    # recalibra con --from-points en lugar de repetir la sesión entera.
    ruta_puntos = None
    if puntos and not args.from_points:
        try:
            # Con la hora en el nombre, una corrida nueva no pisa a la
            # anterior: si la de ayer salió mejor, sigue estando.
            sello = datetime.now().strftime("%H%M%S")
            ruta_puntos = guardar_puntos(
                puntos, spec, tamano, nombre,
                salida / f"puntos_{nombre}_{sello}.npz",
            )
            print(f"Esquinas guardadas en {ruta_puntos}")
        except Exception as e:  # noqa: BLE001 - nunca debe impedir continuar
            print(f"AVISO: no se pudieron guardar las esquinas ({e})",
                  file=sys.stderr)

    if len(puntos) < 5:
        print("Insuficientes para calibrar. Hacen falta al menos 5, "
              "y lo recomendable son 20.", file=sys.stderr)
        return 1

    print("Calibrando…")
    try:
        intr = calibrate(puntos, spec, tamano, camera=nombre)
    except Exception as e:  # noqa: BLE001
        print(f"\nERROR al calibrar: {e}", file=sys.stderr)
        if ruta_puntos:
            print(f"Las {len(puntos)} vistas están a salvo en {ruta_puntos}.\n"
                  f"Reintentar con: python apps/calibrate_intrinsics.py "
                  f"--from-points {ruta_puntos}", file=sys.stderr)
        return 1
    print(intr.resumen())

    if intr.n_descartadas:
        print(
            f"  Se descartaron {intr.n_descartadas} vistas atípicas de "
            f"{len(puntos)}: su error de reproyección estaba muy por encima de "
            f"la mediana, señal de frames movidos."
        )
    hallazgos = diagnosticar(puntos, tamano, intr.rms, intr.residual_coherence)
    if not intr.calidad_aceptable or len(hallazgos) > 1 or "Sin problemas" not in hallazgos[0]:
        print("\n--- Diagnóstico ---")
        for i, h in enumerate(hallazgos, 1):
            print(f"  {i}. {h}")

    cx, cy = float(intr.K[0, 2]), float(intr.K[1, 2])
    if (abs(cx - tamano[0] / 2) / tamano[0] > 0.10
            or abs(cy - tamano[1] / 2) / tamano[1] > 0.10):
        print(
            f"  * El centro óptico salió en ({cx:.0f}, {cy:.0f}) y debería estar "
            f"cerca de ({tamano[0] // 2}, {tamano[1] // 2}). Señal de ajuste mal "
            f"condicionado."
        )
    if abs(intr.fx - intr.fy) / max(intr.fx, intr.fy) > 0.02:
        print(
            f"  * fx={intr.fx:.0f} y fy={intr.fy:.0f} difieren un "
            f"{abs(intr.fx - intr.fy) / max(intr.fx, intr.fy) * 100:.1f} %; con "
            f"píxeles cuadrados deberían coincidir."
        )

    ruta_yaml = intr.save(salida / f"intrinsics_{nombre}.yaml")
    try:
        ruta_md = escribir_reporte(
            intr, salida / f"report_{nombre}.md", puntos_imagen=puntos
        )
    except Exception as e:  # noqa: BLE001 - el YAML ya está guardado
        print(f"AVISO: no se pudo escribir el informe ({e})", file=sys.stderr)
        ruta_md = None

    if args.save_frames and frames:
        carpeta = salida / f"frames_{nombre}"
        carpeta.mkdir(parents=True, exist_ok=True)
        for i, f in enumerate(frames):
            cv2.imwrite(str(carpeta / f"{i:03d}.png"), f)
        print(f"Imágenes guardadas en {carpeta}")

    print(f"\nGuardado:\n  {ruta_yaml}")
    if ruta_md:
        print(f"  {ruta_md}")
    if ruta_puntos:
        print(f"  {ruta_puntos}")
    print("\n--- Campo de visión medido por el ajuste ---")
    print(f"  Horizontal: {intr.fov_h_deg:.1f}°")
    print(f"  Vertical:   {intr.fov_v_deg:.1f}°")
    print(f"  Cobertura vertical: {intr.cobertura_vertical_por_metro:.3f} · d")
    print("\n  Distancia mínima para cuerpo entero:")
    for alto, etiqueta in ((1.80, "de pie          "), (2.20, "brazos en alto  ")):
        d098 = intr.distancia_minima(alto, 0.98)
        d110 = intr.distancia_minima(alto, 1.10)
        print(f"    {etiqueta} cámara a 0.98 m: {d098:.2f} m | a 1.10 m: {d110:.2f} m")

    return 0 if intr.calidad_aceptable else 2


if __name__ == "__main__":
    raise SystemExit(main())
