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
esas dos poblaciones.

Eso responde la pregunta que importa —cuanto se parece el gesto de alguien que
no aporto plantillas— y no la que sale gratis, que es cuanto se parece una toma
a las de su propio dueno.

...y la cifra que se reporta tampoco
------------------------------------
Ese umbral se eligio maximizando la separacion sobre las mismas distancias que
despues se imprimen. Publicar esa exactitud seria tomar una decision sobre el
material de prueba: sale optimista por construccion.

Por eso se reporta ademas una **validacion anidada**: para cada persona que se
deja fuera, el umbral se vuelve a medir dejando fuera a otra persona *dentro
del resto*, de modo que el umbral nunca vio a quien se evalua. Es la unica
cifra defendible, y es la que va en la nota del banco.

Ademas de la exactitud se sacan **precision, exhaustividad y F1 por clase**.
Con material desbalanceado —222 gestos del vocabulario contra 41 movimientos
ajenos— la exactitud global esconde que rechazar funciona la mitad de bien que
reconocer; la F1 de la clase de rechazo, no. Todo queda en CSV bajo
`results/data/validacion_dtw/<fecha>/`.

Un umbral por gesto, no uno solo
--------------------------------
Cada gesto lleva su propio umbral, medido sobre las distancias con las que **se
lee ese gesto**: acertando son los positivos, equivocandose son los negativos.
Es exactamente lo que el umbral tiene que separar cuando el reconocedor propone
ese gesto. Los gestos sin material suficiente a los dos lados se quedan con el
global.

Por que asi y no con un numero unico: `aplaudir` necesita 0.373 y el global es
0.708. Con el global, `aplaudir` acepta cualquier trayectoria de las dos manos
hacia el pecho y se traga los `ven_aca` y los movimientos ajenos que pasan
cerca; con el suyo, deja de hacerlo. Medido, los comandos inventados a partir
de un movimiento ajeno bajan de 17 a 10 de 41 en el vocabulario de cinco gestos
y de 14 a 6 de 30 en el de tres.

Lo que se paga es exhaustividad: `aplaudir` se lee 0.78 de las veces en vez de
0.91. Es el reparto que el uso pide —un gesto perdido se repite, un despegue
inventado no se deshace— y el que decidio el autor. `--umbral-unico` vuelve al
comportamiento anterior; las dos cifras se siguen reportando en cada corrida
para poder compararlas.

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
from datetime import date
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
from recognition.dtw import umbral_por_separacion  # noqa: E402
from recognition.evaluacion import (  # noqa: E402
    formato_matriz,
    formato_metricas,
    guardar_csv,
    loso,
    loso_anidado,
    macro_f1,
    matriz_de_distancias,
    metricas_por_clase,
    umbrales_por_clase,
)

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
    """Deja fuera a cada persona y separa las distancias de acierto y de fallo.

    El umbral que sale de aqui es el que se guarda en el banco —hay que
    guardar alguno, y este es el mejor que el material permite— pero **no** es
    una cifra que se pueda reportar: se eligio maximizando la separacion sobre
    las mismas distancias que se imprimen debajo. La cifra defendible la da
    `loso_anidado`, que mide el umbral sin mirar a la persona evaluada.

    Returns:
        `(D, resultado_loso, umbral, separacion)`.
    """
    D = matriz_de_distancias(ventanas)
    r = loso(D, gestos, personas)
    umbral, separacion = umbral_por_separacion(r["aciertos"], r["fallos"])
    return D, r, umbral, separacion


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Construye el banco de plantillas dinamicas")
    parser.add_argument("--carpeta", nargs="+",
                        help="una o varias carpetas de tomas; se cargan todas "
                             "juntas. Por defecto results/data/gestos_reetiquetado")
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
    parser.add_argument("--umbral-unico", action="store_true",
                        help="un solo umbral para todos los gestos, en vez "
                             "del umbral por gesto que se usa por defecto")
    parser.add_argument("--reporte",
                        help="carpeta para la matriz de confusion y las "
                             "metricas en CSV; por defecto "
                             "results/data/validacion_dtw/<fecha>")
    args = parser.parse_args()

    # Varias carpetas porque el dataset se graba por sesion, una carpeta por
    # fecha, y no todas las fechas valen: las primeras traen etiquetas viejas
    # (`aplauso`, el `arco` de tensar una flecha). Se eligen las que son.
    carpetas = ([Path(c) for c in args.carpeta] if args.carpeta
                else [PROJECT_DIR / "results" / "data" / "gestos_reetiquetado"])
    carpeta = ", ".join(str(c) for c in carpetas)
    quiere = [g.strip() for g in args.gestos.split(",") if g.strip()]
    fuera = [g.strip() for g in args.negativos.split(",") if g.strip()]
    todas = [t for c in carpetas for t in cargar_todas(c)]
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

    D, res, umbral, separacion = medir_umbral(ventanas, gestos, personas)
    aciertos, fallos = res["aciertos"], res["fallos"]
    print(f"\nValidacion dejando fuera a cada persona:")
    print(f"  acierto            {100 * res['exactitud']:5.1f} %   (azar "
          f"{100 / len(set(gestos)):.0f} %)")
    print(f"  distancia acierto  mediana {np.median(aciertos):.3f}   "
          f"p90 {np.percentile(aciertos, 90):.3f}")
    if fallos:
        print(f"  distancia fallo    mediana {np.median(fallos):.3f}   "
              f"p10 {np.percentile(fallos, 10):.3f}")
    print(f"  umbral medido      {umbral:.3f}   separa el "
          f"{100 * separacion:.0f} % de los casos")
    print("  (ese umbral se eligio sobre estas mismas distancias; la cifra "
          "honesta esta abajo)")

    print("\n  Matriz de confusion, 1-NN sin umbral:")
    print(formato_matriz(gestos, res["predichas"], sangria="  "))
    print("\n  Por clase:")
    print(formato_metricas(metricas_por_clase(gestos, res["predichas"]),
                           sangria="  "))

    if not np.isfinite(umbral):
        print("\nSin fallos no se puede medir un umbral: se usa el p90 de los "
              "aciertos.")
        umbral = float(np.percentile(aciertos, 90))

    # La cifra que se puede publicar: el umbral se mide dentro del pliegue,
    # sin haber visto a la persona que se evalua.
    rechazo = GESTO_RECHAZO if GESTO_RECHAZO in gestos else None
    unico = loso_anidado(D, gestos, personas, rechazo=rechazo)
    porgesto = loso_anidado(D, gestos, personas, rechazo=rechazo,
                            por_clase=True)
    print("\nValidacion anidada (umbral medido sin ver a la persona evaluada):")
    print(f"  {'':<18}{'acierto':>10}{'macro-F1':>10}")
    for nombre, r in (("umbral unico", unico), ("umbral por gesto", porgesto)):
        m = metricas_por_clase(r["reales"], r["predichas"])
        print(f"  {nombre:<18}{100 * r['exactitud']:9.1f} %{macro_f1(m):10.2f}")

    anidado = unico if args.umbral_unico else porgesto
    metricas = metricas_por_clase(anidado["reales"], anidado["predichas"])
    us = np.array(list(unico["umbrales"].values()), dtype=float)
    print(f"  sobre {unico['evaluadas']} tomas; se reporta el "
          f"{'umbral unico' if args.umbral_unico else 'umbral por gesto'}")
    print(f"  umbral unico por pliegue: mediana {np.median(us):.3f}   "
          f"rango {us.min():.3f} a {us.max():.3f}")

    # Umbrales que se guardan en el banco, medidos sobre todo el material.
    propios = umbrales_por_clase(res["distancias"], res["predichas"], gestos,
                                 umbral)
    print(f"\n  Umbral de cada gesto (el global es {umbral:.3f})"
          + ("   NO se guardan: --umbral-unico" if args.umbral_unico else "")
          + ":")
    for g in sorted(propios):
        marca = "  (global)" if propios[g] == umbral else ""
        print(f"    {g:<14}{propios[g]:7.3f}{marca}")

    print("\n  Matriz de confusion, con umbral y rechazo:")
    print(formato_matriz(anidado["reales"], anidado["predichas"], sangria="  "))
    print("\n  Por clase:")
    print(formato_metricas(metricas, sangria="  "))

    if not args.sin_rechazo and GESTO_RECHAZO in gestos:
        ajenos = sum(1 for g in gestos if g == GESTO_RECHAZO)
        del_vocabulario = len(gestos) - ajenos
        colados = sum(1 for r, p in zip(anidado["reales"], anidado["predichas"])
                      if r is None and p is not None)
        perdidos = sum(1 for r, p in zip(anidado["reales"], anidado["predichas"])
                       if r is not None and p is None)
        print(f"\n  Rechazo ({ajenos} tomas ajenas en el banco):")
        print(f"    ajenos leidos como un comando: {colados}/{ajenos}")
        print(f"    gestos del vocabulario rechazados: "
              f"{perdidos}/{del_vocabulario}")
        print("    lo que se cuela es el gesto que comparte trayectoria con")
        print("    aplaudir; eso no se arregla con mas plantillas.")

    reporte = Path(args.reporte) if args.reporte else (
        PROJECT_DIR / "results" / "data" / "validacion_dtw"
        / date.today().isoformat())
    rutas = guardar_csv(reporte, anidado["reales"], anidado["predichas"], extra={
        "tomas": len(ventanas),
        "personas": len(set(personas)),
        "acierto_loso": res["exactitud"],
        "acierto_loso_anidado": anidado["exactitud"],
        "macro_f1_anidado": macro_f1(metricas),
        "umbral_guardado": float(umbral),
        "umbral_anidado_mediana": float(np.median(us)),
        "umbral_anidado_min": float(us.min()),
        "umbral_anidado_max": float(us.max()),
        "acierto_umbral_por_gesto": porgesto["exactitud"],
        "macro_f1_umbral_por_gesto": macro_f1(
            metricas_por_clase(porgesto["reales"], porgesto["predichas"])),
    })
    print("\nReporte:")
    for r in rutas:
        print(f"  {r}")

    banco = BancoDinamico(
        gestos=gestos, plantillas=ventanas, umbral=float(umbral),
        umbrales={} if args.umbral_unico else propios, margen=0.0,
        con_diferencia=args.con_diferencia, muestras=args.muestras,
        nota=f"{len(ventanas)} tomas, {len(set(personas))} personas, "
             f"acierto {100 * anidado['exactitud']:.0f} % con validacion "
             f"anidada por persona, umbral "
             f"{'unico' if args.umbral_unico else 'por gesto'}",
    )
    salida = Path(args.salida) if args.salida \
        else PROJECT_DIR / "models" / "plantillas_dinamicas.npz"
    banco.guardar(salida)
    print(f"\nBanco guardado en {salida}")
    print("Para usarlo en vivo:")
    print(r"  python .\external\gesture_detection\probar_vocabulario.py --solo-dinamicos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
