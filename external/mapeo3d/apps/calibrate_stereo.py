"""Calibra la posición relativa entre dos cámaras (extrínsecos estéreo).

Es el paso que falta para poder triangular: los intrínsecos dicen cómo cada
cámara ve, los extrínsecos dicen dónde está una respecto de la otra.

Los intrínsecos se dan por buenos y no se reestiman. Hay que calibrarlos antes
con `apps/calibrate_intrinsics.py`.

Cómo funciona la captura
------------------------
El tablero tiene que verse **en las dos cámaras a la vez**. La app sólo guarda
un par cuando:

- las dos detectan el tablero completo,
- las dos lo ven bastante grande,
- **está quieto** — y eso es lo que hace irrelevante que las cámaras no estén
  sincronizadas por hardware: si el tablero no se mueve, da igual que una vea
  el frame 30 ms después que la otra,
- y la vista es distinta de las ya capturadas.

Colocar el tablero en el solape de las dos cámaras, soltarlo, esperar a que
diga «LISTO», moverlo a otra posición, repetir.

Ejemplos
--------
    python apps/calibrate_stereo.py --cameras cam1 cam2 \\
        --intrinsics results/calibration/2026-09-02 --square-mm 24

Recalibrar desde pares ya capturados::

    python apps/calibrate_stereo.py --from-points results/.../pares_cam1_cam2_1830.npz \\
        --intrinsics results/calibration/2026-09-02
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
    EXTENT_MINIMO_ESTEREO,
    EXTENT_OBJETIVO,
    MINIMO_PARES,
    UMBRAL_COHERENCIA_PX,
    CameraIntrinsics,
    ChessboardSpec,
    ParesIncoherentes,
    analizar_coherencia,
    calibrate_stereo,
    corner_centroid,
    corner_extent,
    corner_movement,
    draw_corners,
    find_corners,
    find_corners_preview,
)
from mapeo3d.capture import CameraStream, load_config, mask_url  # noqa: E402
from mapeo3d.triangulation import (  # noqa: E402
    grid_spacing,
    triangulate_many,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Calibra los extrínsecos entre dos cámaras.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--cameras", nargs=2, metavar=("A", "B"),
                   help="Nombres de las dos cámaras en la configuración.")
    p.add_argument("--from-points",
                   help="Recalibrar desde un .npz de pares ya capturados.")
    p.add_argument("--intrinsics", required=True,
                   help="Carpeta con intrinsics_<camara>.yaml de ambas.")
    p.add_argument("--config", help="Ruta de configuración alternativa.")

    p.add_argument("--cols", type=int, default=9)
    p.add_argument("--rows", type=int, default=6)
    p.add_argument("--square-mm", type=float, default=24.0,
                   help="Lado de casilla en mm, MEDIDO sobre el papel.")

    p.add_argument("--target", type=int, default=18,
                   help="Pares a capturar. Por defecto: 18.")
    p.add_argument("--cooldown", type=float, default=1.0)
    p.add_argument("--max-movement", type=float, default=2.0,
                   help="Movimiento máximo entre frames, en px. 0 desactiva.")
    p.add_argument("--min-extent", type=float, default=EXTENT_MINIMO_ESTEREO,
                   help="Fracción mínima del ancho que debe ocupar el tablero "
                        "en AMBAS cámaras. Mucho más baja que en intrínsecos: "
                        "aquí los intrínsecos van fijos y sólo se estiman 6 "
                        f"parámetros. Por defecto: {EXTENT_MINIMO_ESTEREO}.")
    p.add_argument("--max-sync-ms", type=float, default=60.0,
                   help="Desfase máximo tolerado entre los frames de las dos "
                        "cámaras, en ms. Con el tablero quieto importa poco.")
    p.add_argument("--display-width", type=int, default=640,
                   help="Ancho de cada panel de la ventana.")
    p.add_argument("--detect-width", type=int, default=800)
    p.add_argument("--solo-pares", nargs="+", type=int, metavar="I",
                   help="Usar sólo estos índices de par (con --from-points).")
    p.add_argument("--forzar", action="store_true",
                   help="Calibrar aunque los pares describan geometrías "
                        "incompatibles. El resultado no significa nada; sólo "
                        "sirve para inspeccionar.")
    p.add_argument("--out", help="Carpeta de salida.")
    return p.parse_args()


def cargar_intrinsecos(carpeta: Path, nombres: tuple[str, str]):
    salida = []
    for n in nombres:
        ruta = carpeta / f"intrinsics_{n}.yaml"
        if not ruta.exists():
            raise SystemExit(
                f"No existe {ruta}.\nCalibrar primero los intrínsecos:\n"
                f"  python apps/calibrate_intrinsics.py --camera {n}"
            )
        intr = CameraIntrinsics.load(ruta)
        print(f"  {intr.resumen()}")
        if not intr.calidad_aceptable:
            print(f"    AVISO: los intrínsecos de {n} tienen RMS "
                  f"{intr.rms:.2f} px; los extrínsecos heredan ese error.")
        salida.append(intr)
    return salida[0], salida[1]


def _es_par_nuevo(centro, area, anteriores, tamano) -> bool:
    umbral = 0.08 * max(tamano)
    for (cx, cy), a in anteriores:
        if (np.hypot(centro[0] - cx, centro[1] - cy) < umbral
                and abs(area - a) < 0.15 * max(a, 1e-6)):
            return False
    return True


def capturar_pares(args, spec, nombres, intr_a, intr_b):
    cfg = load_config(args.config)
    cams = [cfg.camera(n) for n in nombres]
    for c in cams:
        print(f"Conectando a [{c.name}] {mask_url(c.url())}")
    streams = [CameraStream(c.url(), name=c.name).start() for c in cams]

    inicio = time.monotonic()
    while any(s.read_latest() is None for s in streams):
        if time.monotonic() - inicio > 20.0:
            for s in streams:
                s.stop()
            raise SystemExit("ERROR: alguna cámara no entregó frames en 20 s.")
        time.sleep(0.1)

    tamano = streams[0].resolucion or (0, 0)
    if streams[1].resolucion != tamano:
        for s in streams:
            s.stop()
        raise SystemExit(
            f"Las cámaras tienen resoluciones distintas: {tamano} y "
            f"{streams[1].resolucion}. Los intrínsecos son específicos de la "
            f"resolución."
        )
    print(f"Conectadas. Resolución {tamano[0]}×{tamano[1]}.")
    print(f"El tablero debe verse en LAS DOS a la vez, quieto, y ocupar al "
          f"menos el {args.min_extent * 100:.0f} % del ancho en ambas.")
    print("ESPACIO fuerza · 'd' descarta el último · 'q' termina")

    ventana = f"calibrate_stereo — {nombres[0]} | {nombres[1]}"
    cv2.namedWindow(ventana, cv2.WINDOW_NORMAL)
    escala = min(1.0, args.display_width / max(tamano[0], 1))
    cv2.resizeWindow(ventana, int(2 * tamano[0] * escala),
                     int(tamano[1] * escala))

    pares_a: list[np.ndarray] = []
    pares_b: list[np.ndarray] = []
    meta: list = []
    aviso_movimiento = ""
    prev = [None, None]
    ultima = 0.0
    desfases: list[float] = []

    try:
        while len(pares_a) < args.target:
            lecturas = [s.read() for s in streams]
            if any(r is None for r in lecturas):
                time.sleep(0.001)
                continue
            frames = [r[0] for r in lecturas]
            tiempos = [r[1] for r in lecturas]
            desfase_ms = abs(tiempos[0] - tiempos[1]) * 1000.0

            det = []
            movs = []
            for i, f in enumerate(frames):
                anterior = prev[i]
                e = find_corners_preview(f, spec, args.detect_width)
                prev[i] = e
                det.append(e)
                movs.append(corner_movement(anterior, e))

            listo = all(e is not None for e in det)
            quieto = args.max_movement <= 0 or max(movs) <= args.max_movement
            sincro = desfase_ms <= args.max_sync_ms
            exts = [corner_extent(e, tamano) if e is not None else 0.0 for e in det]
            grande = min(exts) >= args.min_extent
            nuevo = False
            if listo:
                nuevo = _es_par_nuevo(
                    corner_centroid(det[0]),
                    corner_extent(det[0], tamano), meta, tamano,
                )

            if not listo:
                cual = " y ".join(n for n, e in zip(nombres, det) if e is None)
                estado = f"sin tablero en {cual}"
            elif not grande:
                estado = "MUY LEJOS: acercalo"
            elif not quieto:
                estado = "EN MOVIMIENTO: espera"
            elif not sincro:
                estado = f"desfase {desfase_ms:.0f} ms"
            elif not nuevo:
                estado = "repetido: movelo"
            else:
                estado = "LISTO"

            paneles = []
            for f, e in zip(frames, det):
                v = f if e is None else draw_corners(f, spec, e)
                paneles.append(cv2.resize(v, None, fx=escala, fy=escala,
                                          interpolation=cv2.INTER_AREA))
            vista = np.hstack(paneles)
            color = ((0, 255, 0) if estado == "LISTO"
                     else (0, 200, 255) if listo else (0, 0, 255))
            lineas_hud = [
                f"{len(pares_a)}/{args.target} pares   {estado}",
                f"tam: {exts[0]*100:.0f}% / {exts[1]*100:.0f}% "
                f"(min {args.min_extent*100:.0f}%)   desfase {desfase_ms:.0f} ms",
            ]
            if aviso_movimiento:
                lineas_hud.append(aviso_movimiento)
            for i, linea in enumerate(lineas_hud):
                y = 26 + i * 26
                c = (0, 0, 255) if i == 2 else color
                cv2.putText(vista, linea, (10, y), cv2.FONT_HERSHEY_SIMPLEX,
                            0.6, (0, 0, 0), 4, cv2.LINE_AA)
                cv2.putText(vista, linea, (10, y), cv2.FONT_HERSHEY_SIMPLEX,
                            0.6, c, 1, cv2.LINE_AA)
            cv2.imshow(ventana, vista)

            tecla = cv2.waitKey(1) & 0xFF
            forzar = tecla == ord(" ")
            if tecla in (ord("q"), 27):
                break
            if tecla == ord("d") and pares_a:
                pares_a.pop(); pares_b.pop(); meta.pop()
                print(f"  descartado; quedan {len(pares_a)}")

            ahora = time.monotonic()
            if listo and (forzar or (
                    nuevo and grande and quieto and sincro
                    and ahora - ultima >= args.cooldown)):
                # Detección exacta a resolución completa en ambas.
                ea = find_corners(frames[0], spec)
                eb = find_corners(frames[1], spec)
                if ea is None or eb is None:
                    print("  (la detección precisa falló en una de las dos)")
                else:
                    pares_a.append(ea)
                    pares_b.append(eb)
                    meta.append((corner_centroid(ea),
                                 corner_extent(ea, tamano)))
                    desfases.append(desfase_ms)
                    ultima = ahora
                    print(f"  par {len(pares_a)}/{args.target} capturado "
                          f"(desfase {desfase_ms:.0f} ms)")
                    # Comprobar en el momento que todos los pares siguen
                    # describiendo la misma geometría. Detectarlo aquí, y no al
                    # final, es la diferencia entre mover la cámara de vuelta y
                    # repetir la sesión entera.
                    if len(pares_a) >= 8:
                        coh = analizar_coherencia(pares_a, pares_b,
                                                  intr_a, intr_b, spec)
                        if coh.hay_movimiento:
                            aviso_movimiento = (
                                f"!! UNA CAMARA SE MOVIO en el par "
                                f"{coh.movimiento_en} -- parar y revisar")
                            print(f"\n  {aviso_movimiento}")
                            print("  Los pares anteriores y posteriores al "
                                  f"{coh.movimiento_en} son incompatibles.")
                            print("  Detené con 'q', fijá las cámaras y "
                                  "empezá de nuevo.\n")
    finally:
        for s in streams:
            s.stop()
        cv2.destroyAllWindows()

    if desfases:
        print(f"\nDesfase entre cámaras: mediana {np.median(desfases):.0f} ms, "
              f"máximo {max(desfases):.0f} ms")
    return pares_a, pares_b, tamano


def guardar_pares(pa, pb, spec, tamano, nombres, ruta: Path) -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        ruta,
        a=np.stack([np.asarray(p, np.float32).reshape(-1, 1, 2) for p in pa]),
        b=np.stack([np.asarray(p, np.float32).reshape(-1, 1, 2) for p in pb]),
        cols=spec.cols, rows=spec.rows, square_mm=spec.square_mm,
        image_size=np.array(tamano, np.int32),
        cam_a=nombres[0], cam_b=nombres[1],
    )
    return ruta


def cargar_pares(ruta):
    d = np.load(Path(ruta), allow_pickle=False)
    spec = ChessboardSpec(int(d["cols"]), int(d["rows"]), float(d["square_mm"]))
    tam = tuple(int(v) for v in d["image_size"])
    nombres = (str(d["cam_a"]), str(d["cam_b"]))
    return list(d["a"]), list(d["b"]), spec, (tam[0], tam[1]), nombres


def validar_escala(ext, pa, pb, spec) -> tuple[float, float, float]:
    """Triangula los tableros y mide la casilla reconstruida.

    Es la única comprobación **absoluta** de la cadena entera: un error de
    escala reproyecta perfectamente y no aparece en ningún residual, pero sí
    en el tamaño de la casilla.

    Los puntos se **rectifican antes de triangular**. Las matrices de
    proyección describen cámaras estenopeicas ideales; usar las esquinas tal
    como se detectaron mete la distorsión del objetivo directamente en la
    reconstrucción, y con las Tapo eso son unos 6 puntos porcentuales de error
    de escala que parecen un problema del montaje y no lo son.
    """
    Pa, Pb = ext.projection_matrices()
    ia, ib = ext.intrinsics_a, ext.intrinsics_b
    medias, angulos = [], []
    for a, b in zip(pa, pb):
        pts = np.stack([ia.undistort_points(a), ib.undistort_points(b)])
        X = triangulate_many(np.stack([Pa, Pb]), pts)
        m, _ = grid_spacing(X, spec.cols, spec.rows)
        if np.isfinite(m):
            medias.append(m * 1000.0)          # metros -> mm
            angulos.append(ext.angulo_triangulacion_deg(np.nanmean(X, axis=0)))
    if not medias:
        return float("nan"), float("nan"), float("nan")
    return float(np.mean(medias)), float(np.std(medias)), float(np.mean(angulos))


def main() -> int:
    args = parse_args()
    carpeta_intr = Path(args.intrinsics)

    if args.from_points:
        pa, pb, spec, tamano, nombres = cargar_pares(args.from_points)
        print(f"Recalibrando desde {args.from_points}")
        print(f"Patrón: {spec.describe()}")
        print("Intrínsecos:")
        intr_a, intr_b = cargar_intrinsecos(carpeta_intr, nombres)
        ruta_pares = None
    else:
        if not args.cameras:
            print("Hace falta --cameras A B o --from-points.", file=sys.stderr)
            return 1
        nombres = tuple(args.cameras)
        spec = ChessboardSpec(args.cols, args.rows, args.square_mm)
        print(f"Patrón: {spec.describe()}")
        print("Intrínsecos:")
        intr_a, intr_b = cargar_intrinsecos(carpeta_intr, nombres)
        pa, pb, tamano = capturar_pares(args, spec, nombres, intr_a, intr_b)
        ruta_pares = None

    if args.solo_pares:
        try:
            pa = [pa[i] for i in args.solo_pares]
            pb = [pb[i] for i in args.solo_pares]
        except IndexError:
            print(f"--solo-pares fuera de rango: hay {len(pa)} pares "
                  f"(índices 0 a {len(pa) - 1}).", file=sys.stderr)
            return 1
        print(f"Usando sólo los pares "
              f"{', '.join(str(i) for i in args.solo_pares)}.")

    print(f"\n{len(pa)} pares válidos.")

    salida = (Path(args.out) if args.out
              else Path("results/calibration") / date.today().isoformat())
    if pa and not args.from_points:
        sello = datetime.now().strftime("%H%M%S")
        ruta_pares = guardar_pares(
            pa, pb, spec, tamano, nombres,
            salida / f"pares_{nombres[0]}_{nombres[1]}_{sello}.npz",
        )
        print(f"Pares guardados en {ruta_pares}")

    if len(pa) < 8:
        print("Insuficientes para calibrar; hacen falta al menos 8.",
              file=sys.stderr)
        return 1

    print("Calibrando extrínsecos…")
    try:
        ext = calibrate_stereo(pa, pb, intr_a, intr_b, spec,
                               exigir_coherencia=not args.forzar)
    except ParesIncoherentes as e:
        print(f"\n{e}", file=sys.stderr)
        origen = ruta_pares or args.from_points
        if origen:
            print(f"\nLos pares están guardados en {origen}.", file=sys.stderr)
            grupo = e.coherencia.bloques[0]
            if len(grupo) >= MINIMO_PARES:
                print("Para calibrar sólo con el primer grupo (si sabés que "
                      "las cámaras siguen en esa posición):\n"
                      f"  python apps/calibrate_stereo.py --from-points {origen} "
                      f"--intrinsics {carpeta_intr} "
                      f"--solo-pares {' '.join(str(i) for i in grupo)}",
                      file=sys.stderr)
            else:
                print(f"El grupo más grande tiene {len(grupo)} pares y hacen "
                      f"falta {MINIMO_PARES}: no alcanza ni para rescatar la "
                      "primera mitad de la sesión.", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"\nERROR al calibrar: {e}", file=sys.stderr)
        if ruta_pares:
            print(f"Los pares están a salvo en {ruta_pares}.", file=sys.stderr)
        return 1

    print(ext.resumen())
    if ext.coherencia is not None:
        print(f"  Coherencia entre pares: {ext.coherencia.resumen()}")
    if ext.n_descartados:
        print(f"  Se descartaron {ext.n_descartados} pares atípicos.")

    ruta_yaml = ext.save(salida / f"extrinsics_{nombres[0]}_{nombres[1]}.yaml")

    # --- comprobación métrica absoluta ---
    med, desv, ang = validar_escala(ext, pa, pb, spec)
    print("\n--- Verificación métrica (triangulando los tableros) ---")
    print(f"  casilla reconstruida: {med:.2f} mm ± {desv:.2f}")
    print(f"  casilla real:         {spec.square_mm:.2f} mm")
    if np.isfinite(med) and spec.square_mm > 0:
        err = (med - spec.square_mm) / spec.square_mm * 100.0
        print(f"  error de escala:      {err:+.2f} %")
        if abs(err) > 2.0:
            print("  AVISO: más de un 2 % de error de escala. Revisar que "
                  "--square-mm coincida con el tablero impreso.")
    print(f"  ángulo de triangulación medio: {ang:.1f}°  "
          f"(zona útil 20°-160°)")

    print(f"\n  línea base: {ext.baseline_m * 100:.1f} cm")
    print(f"\nGuardado:\n  {ruta_yaml}")
    if ruta_pares:
        print(f"  {ruta_pares}")

    return 0 if ext.calidad_aceptable else 2


if __name__ == "__main__":
    raise SystemExit(main())
