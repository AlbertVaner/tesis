"""Construye el banco de plantillas dinamicas desde las tomas grabadas.

Uso, desde la raiz del repositorio:

    python .\\external\\gesture_detection\\construir_plantillas.py
    python .\\external\\gesture_detection\\construir_plantillas.py ^
        --gestos aplaudir,ven_aca,arco --salida models\\plantillas.npz

El umbral no se pone a ojo
--------------------------
Se mide con **validacion dejando fuera a cada persona**: para cada sujeto, se
clasifican sus tomas contra las plantillas de los demas, y se guardan las
distancias de los aciertos y de los fallos. El umbral es el que mejor separa
esas dos poblaciones, y se reporta la exactitud que consigue.

Eso responde la pregunta que importa —cuanto se parece el gesto de alguien que
no aporto plantillas— y no la que sale gratis, que es cuanto se parece una toma
a las de su propio dueno.

Rechazar lo que no es ninguno de los tres
-----------------------------------------
Un umbral que solo separa un gesto de otro acepta cualquier cosa que el
segmentador le pase. Para rechazar hace falta material **negativo**: gestos que
no estan en el vocabulario. `--negativos` toma los que hay grabados y mide el
umbral que separa "es uno de los tres" de "es otro movimiento".

Lo que sigue faltando es material de **reposo**: alguien de pie moviendose sin
hacer ningun gesto. En vivo eso lo cubre en parte la segmentacion por
movimiento, que solo clasifica lo que empieza y termina como un gesto, pero el
umbral seguira siendo optimista hasta que se grabe.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

MODULE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = MODULE_DIR.parents[1]
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from dataset.storage import Toma, cargar_todas  # noqa: E402
from pose.normalize import body_frame, yaw_camara  # noqa: E402
from recognition.dinamicos import (  # noqa: E402
    GESTO_RECHAZO,
    MUESTRAS,
    BancoDinamico,
    rasgos_de_secuencia,
    recortar_quietud,
)
from recognition.dtw import dtw_distancia, umbral_por_separacion  # noqa: E402

GESTOS_POR_DEFECTO = "aplaudir,ven_aca,arco"


def canonicalizar(toma: Toma):
    """`(poses, tiempos)` en el marco del cuerpo, normalizado por torso."""
    P, ts, torsos = [], [], []
    for k in range(len(toma.world)):
        m = body_frame(toma.world[k], toma.visibility[k])
        if m is None or not m.valid:
            continue
        torsos.append(m.torso_length_m)
        P.append(m.apply(toma.world[k]))
        ts.append(toma.timestamps[k])
    if len(P) < 6:
        return None
    escala = float(np.median(torsos))
    if not np.isfinite(escala) or escala < 1e-6:
        return None
    return np.stack(P) / escala, np.array(ts)


def ventana(toma: Toma, muestras: int, con_diferencia: bool):
    r = canonicalizar(toma)
    if r is None:
        return None
    P, ts = recortar_quietud(*r)
    return rasgos_de_secuencia(P, ts, muestras=muestras,
                               con_diferencia=con_diferencia)


def medir_umbral(ventanas, gestos, personas):
    """Deja fuera a cada persona y separa las distancias de acierto y de fallo."""
    n = len(ventanas)
    D = np.full((n, n), np.inf)
    for i in range(n):
        for j in range(i + 1, n):
            D[i, j] = D[j, i] = dtw_distancia(ventanas[i], ventanas[j])

    aciertos, fallos, ok = [], [], 0
    conf = defaultdict(lambda: defaultdict(int))
    for i in range(n):
        banco = [k for k in range(n) if personas[k] != personas[i]]
        if not banco:
            continue
        j = min(banco, key=lambda k: D[i, k])
        conf[gestos[i]][gestos[j]] += 1
        if gestos[j] == gestos[i]:
            aciertos.append(D[i, j])
            ok += 1
        else:
            fallos.append(D[i, j])
    umbral, exactitud = umbral_por_separacion(aciertos, fallos)
    return umbral, exactitud, ok / max(n, 1), aciertos, fallos, conf


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Construye el banco de plantillas dinamicas")
    parser.add_argument("--carpeta",
                        help="por defecto results/data/gestos_reetiquetado")
    parser.add_argument("--gestos", default=GESTOS_POR_DEFECTO)
    parser.add_argument("--salida", help="por defecto models/plantillas_dinamicas.npz")
    parser.add_argument("--muestras", type=int, default=MUESTRAS)
    parser.add_argument("--con-diferencia", action="store_true",
                        help="anade la diferencia entre munecas; hace falta "
                             "para gestos de manos alternadas")
    parser.add_argument("--negativos", default="senalar_mano,six_seven",
                        help="gestos que NO estan en el vocabulario, usados "
                             "para medir el rechazo. Vacio los desactiva")
    parser.add_argument("--rechazo-extra",
                        help="carpeta con segmentos guardados en vivo que "
                             "resultaron ser falsos positivos; se suman a la "
                             "clase de rechazo")
    parser.add_argument("--sin-rechazo", action="store_true",
                        help="no mete los negativos en el banco; el detector "
                             "queda de conjunto cerrado y acepta cualquier cosa")
    parser.add_argument("--solo-frontales", action="store_true",
                        help="usa solo tomas de frente como plantillas")
    args = parser.parse_args()

    carpeta = Path(args.carpeta) if args.carpeta \
        else PROJECT_DIR / "results" / "data" / "gestos_reetiquetado"
    quiere = [g.strip() for g in args.gestos.split(",") if g.strip()]
    fuera = [g.strip() for g in args.negativos.split(",") if g.strip()]
    todas = cargar_todas(carpeta)
    tomas = [t for t in todas if t.gesto in quiere]
    if not args.sin_rechazo:
        # Los gestos ajenos entran al banco como una clase propia. Es lo que
        # permite decir "esto no es ninguno" en vez de forzar el mas parecido.
        tomas += [t for t in todas if t.gesto in fuera]
        if args.rechazo_extra:
            extra = cargar_todas(Path(args.rechazo_extra))
            for t in extra:
                fuera.append(t.gesto)
            tomas += extra
            print(f"  + {len(extra)} segmentos de rechazo de "
                  f"{args.rechazo_extra}")
    if not tomas:
        print(f"No hay tomas de {quiere} en {carpeta}.")
        return 1

    ventanas, gestos, personas, angulos = [], [], [], []
    descartadas = 0
    for t in tomas:
        yaw = abs(yaw_camara(t.world))
        if args.solo_frontales and yaw >= 20:
            continue
        v = ventana(t, args.muestras, args.con_diferencia)
        if v is None:
            descartadas += 1
            continue
        ventanas.append(v)
        gestos.append(GESTO_RECHAZO if t.gesto in fuera else t.gesto)
        personas.append(t.persona)
        angulos.append(yaw)

    print(f"Material: {carpeta}")
    print(f"  {len(ventanas)} plantillas de {len(set(personas))} personas"
          + (f"   ({descartadas} descartadas sin pose suficiente)" if descartadas else ""))
    for g in sorted(set(gestos)):
        n = sum(1 for x in gestos if x == g)
        print(f"    {g:<12} {n:3d}")
    print(f"  angulos: mediana {np.median(angulos):.0f} deg, "
          f"maximo {max(angulos):.0f} deg")
    print(f"  rasgos por muestra: {ventanas[0].shape[1]}"
          f"   muestras por plantilla: {args.muestras}")

    umbral, exactitud, acierto, aciertos, fallos, conf = medir_umbral(
        ventanas, gestos, personas)
    print(f"\nValidacion dejando fuera a cada persona:")
    print(f"  acierto            {100 * acierto:5.1f} %   (azar "
          f"{100 / len(set(gestos)):.0f} %)")
    print(f"  distancia acierto  mediana {np.median(aciertos):.3f}   "
          f"p90 {np.percentile(aciertos, 90):.3f}")
    if fallos:
        print(f"  distancia fallo    mediana {np.median(fallos):.3f}   "
              f"p10 {np.percentile(fallos, 10):.3f}")
    print(f"  umbral medido      {umbral:.3f}   separa el "
          f"{100 * exactitud:.0f} % de los casos")

    clases = sorted(set(gestos))
    print("\n  real \\ leido " + "".join(f"{c[:10]:>12}" for c in clases))
    for a in clases:
        print(f"  {a:<12} " + "".join(f"{conf[a][b]:12d}" for b in clases))

    if not np.isfinite(umbral):
        print("\nSin fallos no se puede medir un umbral: se usa el p90 de los "
              "aciertos.")
        umbral = float(np.percentile(aciertos, 90))

    if not args.sin_rechazo and GESTO_RECHAZO in gestos:
        ajenos = [i for i, g in enumerate(gestos) if g == GESTO_RECHAZO]
        propios = [i for i, g in enumerate(gestos) if g != GESTO_RECHAZO]
        colados = sum(conf[GESTO_RECHAZO][c] for c in clases
                      if c != GESTO_RECHAZO)
        print(f"\n  Rechazo ({len(ajenos)} tomas ajenas en el banco):")
        print(f"    ajenos leidos como un comando: {colados}/{len(ajenos)}")
        perdidos = sum(conf[a][GESTO_RECHAZO] for a in clases
                       if a != GESTO_RECHAZO)
        print(f"    gestos del vocabulario rechazados: {perdidos}/{len(propios)}")
        print("    lo que se cuela es el gesto que comparte trayectoria con")
        print("    aplaudir; eso no se arregla con mas plantillas.")

    banco = BancoDinamico(
        gestos=gestos, plantillas=ventanas, umbral=float(umbral), margen=0.0,
        con_diferencia=args.con_diferencia, muestras=args.muestras,
        nota=f"{len(ventanas)} tomas, {len(set(personas))} personas, "
             f"acierto {100 * acierto:.0f} % dejando fuera a cada persona",
    )
    salida = Path(args.salida) if args.salida \
        else PROJECT_DIR / "models" / "plantillas_dinamicas.npz"
    banco.guardar(salida)
    print(f"\nBanco guardado en {salida}")
    print("Para usarlo en vivo:")
    print(r"  python .\external\gesture_detection\detectar_gestos_3d.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
