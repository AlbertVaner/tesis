"""Detecta aplaudir, ven aca y arco en vivo. Sin dron y sin radio.

Uso, desde la raiz del repositorio:

    python .\\external\\gesture_detection\\construir_plantillas.py
    python .\\external\\gesture_detection\\detectar_gestos_3d.py

Como funciona
-------------
No clasifica cada frame. **Espera a que el gesto termine**: detecta cuando las
munecas empiezan a moverse, sigue el recorrido, y cuando se detienen compara la
trayectoria completa contra las plantillas grabadas.

Eso significa que el gesto se reconoce **al terminarlo**, no mientras se hace.
Para un aplauso son unos 2.4 s. Es inherente a reconocer trayectorias.

Que esperar
-----------
Medido sobre 102 tomas de 10 personas, dejando fuera a cada persona:

    los tres gestos, bien clasificados      69 / 72
    movimientos ajenos rechazados           16 / 30

Ese segundo numero es la limitacion real. Lo que se cuela es el gesto de
senalar la mano, que comparte con el aplauso el mismo recorrido de brazos; la
diferencia esta en los dedos y la pose no los ve. **No es un detector de "hay
gesto o no": es un clasificador con rechazo parcial.**

Teclas: `q` salir, `r` reiniciar, `d` detalle de distancias.

Cuando da falsos positivos
--------------------------
Casi siempre son `aplaudir`, porque es el gesto al que se parece cualquier
movimiento de las dos manos hacia el pecho. Ningun umbral lo arregla: medido,
los aplausos reales quedan a distancia 0.259 y las confusiones a 0.286, y se
solapan. Probado tambien exigir margen (cuesta 22 de 72 gestos buenos) y votar
entre varias plantillas (empeora: 13 fugas pasan a 19).

Lo que si lo arregla es material: la clase de rechazo del banco son dos gestos
concretos, y en vivo lo que se cuela es movimiento cualquiera. Con
`--guardar-segmentos`, cada deteccion queda grabada; se borran las correctas y
el resto se suma a la clase de rechazo con `construir_plantillas.py
--rechazo-extra`. El detector aprende a rechazar de sus propios errores.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

MODULE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = MODULE_DIR.parents[1]
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from dataset.storage import Toma, guardar  # noqa: E402
from pose.detector import PoseDetector  # noqa: E402
from pose.normalize import (  # noqa: E402
    N_LANDMARKS,
    body_frame,
    landmarks_to_array,
)
from recognition.dinamicos import (  # noqa: E402
    ENTRADA_RAPIDEZ,
    BancoDinamico,
    ReconocedorDinamico,
)
from utils import calculate_fps  # noqa: E402
from visualization.pose_overlay import draw_pose  # noqa: E402

VENTANA = "Gestos dinamicos 3D"
FONDO = (22, 22, 26)
BLANCO = (238, 238, 242)
GRIS = (150, 150, 155)
VERDE = (120, 220, 140)
ROJO = (90, 90, 240)
AMBAR = (80, 200, 255)

#: Segundos que el gesto reconocido se queda en pantalla.
MOSTRAR_S = 2.0


def _texto(img, txt, fila, color=BLANCO, escala=0.58, grosor=1) -> None:
    cv2.putText(img, txt, (14, 32 + fila * 30), cv2.FONT_HERSHEY_SIMPLEX,
                escala, (0, 0, 0), grosor + 2, cv2.LINE_AA)
    cv2.putText(img, txt, (14, 32 + fila * 30), cv2.FONT_HERSHEY_SIMPLEX,
                escala, color, grosor, cv2.LINE_AA)


def dibujar(frame, *, rec, ultima, fps, escala_m, contador, detalle, t) -> None:
    alto = frame.shape[0]
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (frame.shape[1], 170), FONDO, -1)
    cv2.addWeighted(overlay, 0.74, frame, 0.26, 0, frame)

    torso = f"{escala_m * 100:.0f} cm" if np.isfinite(escala_m) else "s/d"
    _texto(frame, f"fps {fps:4.1f}   torso {torso}   "
                  f"plantillas {len(rec.banco.plantillas)}", 0, GRIS, 0.5)

    if rec.en_segmento:
        _texto(frame, f"GRABANDO GESTO   {rec.segmento_s:4.1f} s", 1, ROJO,
               0.85, 2)
        cv2.circle(frame, (frame.shape[1] - 40, 40), 14, (60, 60, 240), -1)
    else:
        barra = min(rec.rapidez / ENTRADA_RAPIDEZ, 1.0)
        _texto(frame, "esperando movimiento", 1, GRIS, 0.7)
        cv2.rectangle(frame, (14, 62), (14 + int(200 * barra), 70), AMBAR, -1)
        cv2.rectangle(frame, (14, 62), (214, 70), GRIS, 1)

    if ultima is not None and t - ultima.t_fin < MOSTRAR_S:
        if ultima.gesto:
            _texto(frame, ultima.gesto.upper(), 2, VERDE, 1.0, 2)
            _texto(frame, f"distancia {ultima.distancia:.2f}   "
                          f"margen {ultima.margen:.2f}   "
                          f"{ultima.duracion_s:.1f} s", 3, GRIS, 0.5)
        else:
            _texto(frame, "no reconocido", 2, AMBAR, 0.75)
            _texto(frame, ultima.motivo or
                   f"lo mas cercano a {ultima.distancia:.2f}", 3, GRIS, 0.5)
        if detalle and ultima.distancias:
            for i, (g, d) in enumerate(sorted(ultima.distancias.items(),
                                              key=lambda x: x[1])):
                _texto(frame, f"   {g:<14} {d:.3f}", 4 + i, GRIS, 0.48)

    fila = " ".join(f"{g} {n}" for g, n in contador.most_common())
    cv2.putText(frame, fila or "sin detecciones todavia",
                (14, alto - 40), cv2.FONT_HERSHEY_SIMPLEX, 0.55, BLANCO, 1,
                cv2.LINE_AA)
    cv2.putText(frame, "q salir   r reiniciar   d detalle",
                (14, alto - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.5, GRIS, 1,
                cv2.LINE_AA)


def bucle(camara, banco, registro, segmentos=None, persona="vivo") -> Counter:
    captura = cv2.VideoCapture(camara)
    if not captura.isOpened():
        raise RuntimeError(f"No se pudo abrir la camara {camara}.")
    detector = PoseDetector()
    rec = ReconocedorDinamico(banco)
    contador: Counter = Counter()
    anterior = 0.0
    detalle = True
    escalas: list[float] = []
    t0 = time.monotonic()
    # Historial crudo, para poder guardar el segmento tal como se grabo.
    crudos: list[tuple[float, np.ndarray, np.ndarray, np.ndarray]] = []
    guardados = 0

    cv2.namedWindow(VENTANA, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(VENTANA, 1024, 768)
    print("Ponte a cuerpo entero. El gesto se reconoce al terminarlo.\n")

    try:
        while True:
            ok, crudo = captura.read()
            if not ok:
                raise RuntimeError("La camara dejo de entregar imagenes.")
            # Sin voltear: la imagen en espejo intercambia las etiquetas
            # anatomicas de MediaPipe.
            lm2d, mundo_lm = detector.process_full(crudo)
            fps, anterior = calculate_fps(anterior)
            t = time.monotonic()

            pose = None
            mundo, vis = landmarks_to_array(mundo_lm)
            if mundo.size:
                marco = body_frame(mundo, vis)
                if marco is not None and marco.valid:
                    escalas.append(marco.torso_length_m)
                    escala = float(np.median(escalas[-900:]))
                    pose = marco.apply(mundo) / escala

            if mundo.size and lm2d is not None:
                P2 = np.array([[l.x, l.y] for l in lm2d], dtype=np.float64)
            else:
                P2 = np.full((N_LANDMARKS, 2), np.nan)
                mundo = np.full((N_LANDMARKS, 3), np.nan)
                vis = np.zeros(N_LANDMARKS)
            crudos.append((t, mundo.copy(), P2, vis.copy()))
            if len(crudos) > 900:
                crudos.pop(0)

            det = rec.actualizar(pose, t)
            if det is not None:
                etiqueta = det.gesto or "no reconocido"
                contador[etiqueta] += 1
                print(f"[{t - t0:6.2f} s] {etiqueta:<16} "
                      f"d={det.distancia:.3f} margen={det.margen:.3f} "
                      f"{det.duracion_s:.1f} s"
                      + (f"   {det.motivo}" if det.motivo else ""))
                if segmentos is not None and not det.motivo:
                    tramo = [c for c in crudos
                             if det.t_inicio - 0.2 <= c[0] <= det.t_fin]
                    if len(tramo) >= 8:
                        guardados += 1
                        guardar(segmentos, Toma(
                            persona=persona,
                            gesto=f"leido_{det.gesto or 'nada'}",
                            numero=guardados,
                            orientacion_deg=0.0,
                            world=np.stack([c[1] for c in tramo]),
                            imagen=np.stack([c[2] for c in tramo]),
                            visibility=np.stack([c[3] for c in tramo]),
                            timestamps=np.array([c[0] - tramo[0][0]
                                                 for c in tramo]),
                        ))
                if registro is not None:
                    registro.writerow([
                        f"{t - t0:.3f}", det.gesto or "", f"{det.distancia:.4f}",
                        f"{det.margen:.4f}", f"{det.duracion_s:.2f}",
                        det.motivo,
                        ";".join(f"{g}={d:.4f}"
                                 for g, d in sorted(det.distancias.items())),
                    ])

            dibujado = cv2.flip(crudo, 1)
            if lm2d is not None:
                espejo = crudo.copy()
                draw_pose(espejo, lm2d, detector.connections)
                dibujado = cv2.flip(espejo, 1)
            dibujar(dibujado, rec=rec, ultima=rec.ultima, fps=fps,
                    escala_m=float(np.median(escalas)) if escalas else float("nan"),
                    contador=contador, detalle=detalle, t=t)
            cv2.imshow(VENTANA, dibujado)

            tecla = cv2.waitKey(1) & 0xFF
            if tecla == ord("q"):
                break
            if tecla == ord("r"):
                rec.reset()
            if tecla == ord("d"):
                detalle = not detalle
            if cv2.getWindowProperty(VENTANA, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        captura.release()
        detector.close()
        cv2.destroyAllWindows()
    return contador


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detecta gestos dinamicos en vivo, sin dron")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--banco", help="por defecto models/plantillas_dinamicas.npz")
    parser.add_argument("--umbral", type=float,
                        help="sobreescribe el umbral medido del banco")
    parser.add_argument("--guardar-segmentos", action="store_true",
                        help="guarda cada segmento clasificado como una toma. "
                             "Sirve para convertir los falsos positivos en "
                             "material de rechazo")
    parser.add_argument("--persona", default="vivo",
                        help="nombre con el que se guardan los segmentos")
    parser.add_argument("--sin-csv", action="store_true")
    args = parser.parse_args()

    ruta = Path(args.banco) if args.banco \
        else PROJECT_DIR / "models" / "plantillas_dinamicas.npz"
    if not ruta.exists():
        print(f"No hay banco de plantillas en {ruta}.")
        print(r"Construilo con: python .\external\gesture_detection\construir_plantillas.py")
        return 1
    banco = BancoDinamico.cargar(ruta)
    if args.umbral is not None:
        banco.umbral = args.umbral

    print(f"Banco: {ruta.name}")
    print(f"  {banco.nota}")
    print(f"  gestos: {', '.join(banco.clases)}"
          + ("   (+ clase de rechazo)" if banco.tiene_rechazo else
             "   SIN clase de rechazo: aceptara cualquier movimiento"))
    print(f"  umbral {banco.umbral:.3f}   "
          f"rasgos {banco.plantillas[0].shape[1]}\n")

    archivo = registro = None
    if not args.sin_csv:
        carpeta = (PROJECT_DIR / "results" / "data" / "gestos_dinamicos"
                   / datetime.now().strftime("%Y-%m-%d"))
        carpeta.mkdir(parents=True, exist_ok=True)
        destino = carpeta / f"sesion_{datetime.now():%H%M%S}.csv"
        archivo = destino.open("w", newline="", encoding="utf-8")
        registro = csv.writer(archivo)
        registro.writerow(["t_s", "gesto", "distancia", "margen", "duracion_s",
                           "motivo", "distancias"])

    segmentos = None
    if args.guardar_segmentos:
        segmentos = (PROJECT_DIR / "results" / "data" / "gestos_dinamicos"
                     / datetime.now().strftime("%Y-%m-%d") / "segmentos")
        print(f"Los segmentos se guardan en {segmentos}")
        print("Despues: borra los que SI eran ese gesto. Lo que quede es")
        print("material de rechazo, y se pasa a construir_plantillas.py con")
        print("--rechazo-extra.")
        print()

    try:
        contador = bucle(args.camera, banco, registro, segmentos, args.persona)
        print("\nDetecciones:")
        for g, n in contador.most_common():
            print(f"  {g:<16} {n}")
        if not contador:
            print("  ninguna")
        if archivo is not None:
            print(f"\nRegistro: {destino}")
        return 0
    except KeyboardInterrupt:
        print("Interrupcion solicitada.")
        return 130
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    finally:
        if archivo is not None:
            archivo.close()


if __name__ == "__main__":
    raise SystemExit(main())
