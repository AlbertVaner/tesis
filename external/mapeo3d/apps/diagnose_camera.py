"""Diagnóstico completo de una cámara, antes de decidir dónde montarla.

Casi todo lo que dice docs/hardware.md sobre encuadre, frame rate y latencia
está **calculado, no medido**. Y fijar seis cámaras es la decisión más difícil
de deshacer del proyecto. Esta app convierte esas estimaciones en medidas.

Qué mide
--------
1. **fps realmente recibidos** frente a los esperados, con el jitter del
   intervalo entre frames. Nunca confiar en los fps declarados: la exposición
   automática los baja en silencio cuando falta luz.
2. **Latencia extremo a extremo**, haciendo destellar la pantalla contra la
   cámara. Es invisible en la imagen y es lo que decide si un gesto sirve para
   pilotar.
3. **Jitter de landmarks en reposo**: con el sujeto quieto, todo lo que se
   mueve es error del estimador. Convierte «se ve mejor» en un número.
4. **Encuadre**: si el cuerpo entero cabe, y si cabe con los brazos en alto.
   MediaPipe extrapola landmarks fuera del cuadro sin avisar.
5. **Campo de visión real**, si ya hay intrínsecos de esa cámara.

Escribe un informe en `results/diagnostics/<fecha>/`. Ese informe es a la vez
criterio de montaje y material para el capítulo experimental.

Ejemplos
--------
Todo seguido, con el sujeto a 3 m::

    python apps/diagnose_camera.py --camera cam3 --distancia 3.0

Sólo frame rate y latencia, sin sujeto::

    python apps/diagnose_camera.py --camera cam3 --sin-pose

Repetir a varias distancias: una corrida por distancia, y luego comparar los
informes. `--nota` sirve para etiquetar cada una.
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

from mapeo3d.calibration import CameraIntrinsics  # noqa: E402
from mapeo3d.capture import (  # noqa: E402
    CameraStream,
    Latencia,
    brillo,
    detectar_flanco,
    load_config,
    mask_url,
)
from mapeo3d.pose import (  # noqa: E402
    PoseDetector,
    evaluar_encuadre,
    jitter_en_reposo,
)

VENTANA_DESTELLO = "diagnose_camera — DESTELLO (apuntá la cámara aquí)"

# Cada cuánto se refresca la línea de progreso.
PERIODO_AVISO_S = 0.25
_ultimo_aviso = 0.0


def _toca_avisar() -> bool:
    """True como mucho 4 veces por segundo."""
    global _ultimo_aviso
    ahora = time.perf_counter()
    if ahora - _ultimo_aviso < PERIODO_AVISO_S:
        return False
    _ultimo_aviso = ahora
    return True


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Mide fps, latencia, jitter y encuadre de una cámara.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    fuente = p.add_mutually_exclusive_group(required=True)
    fuente.add_argument("--camera", help="Cámara definida en la configuración.")
    fuente.add_argument("--url", help="URL o índice de dispositivo.")

    p.add_argument("--config", help="Ruta de configuración alternativa.")
    p.add_argument("--model", help="Ruta del .task de MediaPipe.")
    p.add_argument("--intrinsics",
                   help="Carpeta con intrinsics_<camara>.yaml, para el FOV.")
    p.add_argument("--distancia", type=float, default=0.0,
                   help="Distancia del sujeto a la cámara, en metros. Sólo "
                        "etiqueta el informe y convierte el jitter a mm.")
    p.add_argument("--nota", default="", help="Texto libre para el informe.")

    p.add_argument("--segundos-fps", type=float, default=60.0,
                   help="Duración de la medida de frame rate. Por defecto: 60.")
    p.add_argument("--segundos-pose", type=float, default=20.0,
                   help="Duración de la medida de jitter, con el sujeto "
                        "QUIETO. Por defecto: 20.")
    p.add_argument("--destellos", type=int, default=12,
                   help="Destellos para la latencia. Por defecto: 12.")

    p.add_argument("--sin-latencia", action="store_true",
                   help="Saltar la medida de latencia (necesita apuntar la "
                        "cámara a la pantalla).")
    p.add_argument("--sin-pose", action="store_true",
                   help="Saltar jitter y encuadre (no hace falta sujeto).")
    p.add_argument("--out", help="Ruta del informe .md.")
    return p.parse_args()


def resolver_fuente(args) -> tuple[str | int, str, float]:
    if args.url is not None:
        f: str | int = int(args.url) if args.url.isdigit() else args.url
        return f, "url", 0.0
    cfg = load_config(args.config)
    cam = cfg.camera(args.camera)
    return cam.url(), cam.name, float(cfg.capture.target_fps)


# ------------------------------------------------------------------ medidas


def medir_frame_rate(stream: CameraStream, segundos: float) -> dict:
    """fps reales e intervalo entre frames. La medida que nunca hay que creer
    de la hoja de datos."""
    print(f"\n[1/4] Frame rate — {segundos:.0f} s…")
    stream.stats.frames_recibidos = 0
    stream.stats.primer_frame_t = None
    stream.stats.ultimo_frame_t = None

    tiempos: list[float] = []
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < segundos:
        r = stream.read()
        if r is None:
            time.sleep(0.001)
            continue
        tiempos.append(r[1])
        # Refrescar 4 veces por segundo y no una vez por frame: a 30 fps son
        # 1800 líneas en un log redirigido, que tapan todo lo demás.
        if _toca_avisar():
            print(f"\r  {time.perf_counter() - t0:5.1f}/{segundos:.0f} s   "
                  f"{stream.stats.fps_recibidos:5.2f} fps", end="", flush=True)
    print(f"\r  {segundos:5.1f}/{segundos:.0f} s   "
          f"{stream.stats.fps_recibidos:5.2f} fps")

    dt = np.diff(tiempos) if len(tiempos) > 2 else np.array([np.nan])
    return {
        "n": len(tiempos),
        "fps": stream.stats.fps_recibidos,
        "fps_declarados": stream.fps_declarados,
        "intervalo_mediano_ms": float(np.median(dt)) * 1000.0,
        "intervalo_p95_ms": float(np.percentile(dt, 95)) * 1000.0,
        "jitter_ms": float(np.std(dt)) * 1000.0,
        "reconexiones": stream.stats.reconexiones,
        "lecturas_fallidas": stream.stats.lecturas_fallidas,
    }


def medir_latencia(stream: CameraStream, destellos: int) -> Latencia:
    """Destella la pantalla y busca el escalón de brillo en el stream."""
    print(f"\n[2/4] Latencia — {destellos} destellos.")
    print("  APUNTÁ LA CÁMARA A LA PANTALLA. Empieza en 3 s…")
    cv2.namedWindow(VENTANA_DESTELLO, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(VENTANA_DESTELLO, 900, 620)
    negro = np.zeros((620, 900, 3), np.uint8)
    blanco = np.full((620, 900, 3), 255, np.uint8)
    cv2.imshow(VENTANA_DESTELLO, negro)
    cv2.waitKey(3000)

    res = Latencia(intentos=destellos)
    try:
        for k in range(destellos):
            # Reposo: se recoge la línea base de brillo con la pantalla negra.
            cv2.imshow(VENTANA_DESTELLO, negro)
            cv2.waitKey(1)
            t: list[float] = []
            b: list[float] = []
            fin = time.perf_counter() + 0.6
            while time.perf_counter() < fin:
                r = stream.read()
                if r is not None:
                    t.append(r[1]); b.append(brillo(r[0]))
                else:
                    time.sleep(0.001)

            cv2.imshow(VENTANA_DESTELLO, blanco)
            cv2.waitKey(1)
            t_destello = time.perf_counter()

            fin = t_destello + 1.2
            while time.perf_counter() < fin:
                r = stream.read()
                if r is not None:
                    t.append(r[1]); b.append(brillo(r[0]))
                else:
                    time.sleep(0.001)

            lat = detectar_flanco(np.array(t), np.array(b), t_destello)
            if lat is not None:
                res.muestras_s.append(lat)
            print(f"\r  destello {k + 1}/{destellos}   "
                  + (f"{lat * 1000:6.0f} ms" if lat else "  no detectado"),
                  end="")
        print()
    finally:
        cv2.destroyWindow(VENTANA_DESTELLO)
    return res


def medir_pose(stream: CameraStream, detector: PoseDetector, segundos: float,
               distancia: float) -> dict | None:
    """Jitter en reposo y encuadre. El sujeto tiene que estar QUIETO."""
    print(f"\n[3/4] Jitter y encuadre — {segundos:.0f} s.")
    print("  COLOCATE EN CUADRO Y QUEDATE QUIETO. Empieza en 5 s…")
    time.sleep(5.0)

    pix: list[np.ndarray] = []
    norm: list[np.ndarray] = []
    vis: list[np.ndarray] = []
    n_frames = 0
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < segundos:
        r = stream.read()
        if r is None:
            time.sleep(0.001)
            continue
        n_frames += 1
        lm = detector.detect(r[0], r[1])
        if lm is not None:
            pix.append(lm.to_pixels()); norm.append(lm.xy); vis.append(lm.visibility)
        if _toca_avisar():
            print(f"\r  {time.perf_counter() - t0:5.1f}/{segundos:.0f} s   "
                  f"{len(pix)} detecciones", end="", flush=True)
    print(f"\r  {segundos:5.1f}/{segundos:.0f} s   {len(pix)} detecciones")

    if len(pix) < 20:
        print("  Muy pocas detecciones; se omite esta sección.")
        return None

    j = jitter_en_reposo(np.array(pix), np.array(vis), distancia_m=distancia)
    e = evaluar_encuadre(np.array(norm))
    return {"jitter": j, "encuadre": e, "n_frames": n_frames,
            "n_detecciones": len(pix)}


# ------------------------------------------------------------------ informe


def escribir_informe(ruta: Path, nombre: str, args, tam, fr, lat, pose,
                     intr: CameraIntrinsics | None) -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    L: list[str] = [
        f"# Diagnóstico de cámara — {nombre}",
        "",
        f"- Fecha: {datetime.now().isoformat(timespec='seconds')}",
        f"- Resolución: {tam[0]}×{tam[1]}",
        f"- Distancia del sujeto: "
        + (f"{args.distancia:.2f} m" if args.distancia else "no indicada"),
    ]
    if args.nota:
        L.append(f"- Nota: {args.nota}")
    L += ["", "## Frame rate", ""]

    esperados = fr["fps_esperados"]
    L += [
        f"- **fps recibidos: {fr['fps']:.2f}**",
        f"- fps declarados por el stream: {fr['fps_declarados']:.2f}",
        f"- fps esperados por configuración: {esperados:.2f}"
        if esperados else "- fps esperados: no configurado",
        f"- Intervalo entre frames: mediana {fr['intervalo_mediano_ms']:.1f} ms, "
        f"p95 {fr['intervalo_p95_ms']:.1f} ms, jitter {fr['jitter_ms']:.1f} ms",
        f"- Reconexiones: {fr['reconexiones']} · lecturas fallidas: "
        f"{fr['lecturas_fallidas']}",
        "",
    ]
    ref = esperados or fr["fps_declarados"]
    if ref > 0:
        desv = abs(fr["fps"] - ref) / ref
        if desv > 0.10:
            L += [f"> **AVISO**: los fps recibidos se desvían un "
                  f"{desv * 100:.0f} % de los esperados (umbral 10 %). Causas "
                  f"probables: luz insuficiente con exposición automática, red "
                  f"saturada, o CPU al límite. Ver docs/capture.md.", ""]
        else:
            L += ["Frame rate dentro de tolerancia.", ""]

    L += ["## Latencia extremo a extremo", ""]
    if lat is None:
        L += ["No medida (`--sin-latencia`).", ""]
    else:
        L += [f"- {lat.resumen()}", "",
              "Incluye exposición, codificación, red y decodificación, más el "
              "retardo del monitor (5-15 ms). No incluye pintar el resultado: "
              "es el retardo que sufre el lazo de percepción.", ""]

    L += ["## Jitter de landmarks en reposo", ""]
    if pose is None:
        L += ["No medido.", ""]
    else:
        j = pose["jitter"]
        L += [f"- **Mediana de los landmarks clave: {j.mediana_clave_px:.2f} px**"]
        if intr is not None and args.distancia > 0:
            esc = intr.fx * (tam[0] / intr.image_size[0])
            L.append(f"- Equivale a **{j.milimetros(esc, args.distancia):.1f} mm** "
                     f"sobre el sujeto a {args.distancia:.1f} m")
        L += ["", "```", j.resumen(), "```", "",
              "Con el sujeto quieto, todo lo que se mueve es error del "
              "estimador. Es el ruido que se propaga a la triangulación.", "",
              "## Encuadre", "", "```", pose["encuadre"].resumen(), "```", ""]
        if not pose["encuadre"].cabe:
            L += ["> **AVISO**: el cuerpo no cabe entero de forma consistente. "
                  "MediaPipe extrapola los landmarks que se salen del cuadro "
                  "sin avisar, y esos valores no son fiables. Alejar la cámara "
                  "o bajarla.", ""]

    L += ["## Campo de visión", ""]
    if intr is None:
        L += ["Sin intrínsecos para esta cámara. Calibrarla con:", "",
              f"    python apps/calibrate_intrinsics.py --camera {nombre}", "",
              "El FOV sale del ajuste, no hace falta medirlo con cinta.", ""]
    else:
        L += [f"- Horizontal: **{intr.fov_h_deg:.1f}°** · vertical: "
              f"**{intr.fov_v_deg:.1f}°**",
              f"- Cobertura vertical: {intr.cobertura_vertical_por_metro:.3f} · d",
              "",
              "Distancia mínima para que la persona quepa entera:", "",
              "| Objetivo | Cámara a 0.98 m | Cámara a 1.10 m |",
              "|---|---|---|",
              f"| De pie (1.80 m) | {intr.distancia_minima(1.80, 0.98):.2f} m | "
              f"{intr.distancia_minima(1.80, 1.10):.2f} m |",
              f"| Brazos en alto (2.20 m) | {intr.distancia_minima(2.20, 0.98):.2f} m | "
              f"{intr.distancia_minima(2.20, 1.10):.2f} m |", ""]

    ruta.write_text("\n".join(L), encoding="utf-8")
    return ruta


# --------------------------------------------------------------------- main


def main() -> int:
    args = parse_args()
    fuente, nombre, fps_esperados = resolver_fuente(args)

    intr = None
    if args.intrinsics:
        ruta_i = Path(args.intrinsics) / f"intrinsics_{nombre}.yaml"
        if ruta_i.exists():
            intr = CameraIntrinsics.load(ruta_i)
            print(f"Intrínsecos: {intr.resumen()}")
        else:
            print(f"AVISO: no existe {ruta_i}; el informe irá sin FOV.")

    print(f"Conectando a [{nombre}] {mask_url(str(fuente))}")
    stream = CameraStream(fuente, name=nombre).start()
    inicio = time.perf_counter()
    while stream.read_latest() is None:
        if time.perf_counter() - inicio > 15.0:
            stream.stop()
            print("ERROR: no llegó ningún frame en 15 s.", file=sys.stderr)
            return 1
        time.sleep(0.05)
    tam = stream.resolucion or (0, 0)
    print(f"Conectado. Resolución {tam[0]}×{tam[1]}, "
          f"fps declarados {stream.fps_declarados:.1f}.")

    detector = None
    if not args.sin_pose:
        try:
            detector = PoseDetector(args.model, camera=nombre)
        except FileNotFoundError as e:
            stream.stop()
            print(f"\n{e}", file=sys.stderr)
            return 1

    lat = pose = None
    try:
        fr = medir_frame_rate(stream, args.segundos_fps)
        fr["fps_esperados"] = fps_esperados
        if not args.sin_latencia:
            lat = medir_latencia(stream, args.destellos)
        if detector is not None:
            pose = medir_pose(stream, detector, args.segundos_pose,
                              args.distancia)
    except KeyboardInterrupt:
        print("\nInterrumpido; se escribe el informe con lo medido.")
        fr = locals().get("fr") or {
            "n": 0, "fps": 0.0, "fps_declarados": stream.fps_declarados,
            "fps_esperados": fps_esperados, "intervalo_mediano_ms": float("nan"),
            "intervalo_p95_ms": float("nan"), "jitter_ms": float("nan"),
            "reconexiones": 0, "lecturas_fallidas": 0,
        }
    finally:
        if detector is not None:
            detector.close()
        stream.stop()
        cv2.destroyAllWindows()

    print("\n[4/4] Informe.")
    destino = Path(args.out) if args.out else (
        RAIZ / "results" / "diagnostics" / date.today().isoformat()
        / f"{nombre}_{datetime.now().strftime('%H%M%S')}.md"
    )
    ruta = escribir_informe(destino, nombre, args, tam, fr, lat, pose, intr)

    print()
    print(f"  fps recibidos: {fr['fps']:.2f}"
          + (f" (esperados {fps_esperados:.0f})" if fps_esperados else ""))
    if lat is not None:
        print(f"  {lat.resumen()}")
    if pose is not None:
        print(f"  jitter en reposo: {pose['jitter'].mediana_clave_px:.2f} px")
        print(f"  {pose['encuadre'].resumen().splitlines()[0]}")
    print(f"\nInforme: {ruta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
