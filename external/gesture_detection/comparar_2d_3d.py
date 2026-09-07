"""Compara 3D contra 2D sobre las tomas grabadas. Sin camara y sin dron.

Responde la pregunta que motiva todo el proyecto: **para reconocer un gesto
dinamico, hace falta la profundidad?**

Uso, desde la raiz del repositorio:

    python .\\external\\gesture_detection\\comparar_2d_3d.py
    python .\\external\\gesture_detection\\comparar_2d_3d.py --carpeta results\\data\\gestos\\2026-09-05

Como se mide
------------
**1-NN con DTW, dejando fuera la toma que se evalua.** Cada toma se clasifica
por la plantilla mas parecida de entre todas las demas. Una toma nunca se
compara consigo misma, que es la trampa que hace que cualquier metodo parezca
perfecto.

Se reportan dos cosas distintas y las dos importan:

* **Exactitud**: cuantas tomas se clasifican bien. Es lo que se siente al usarlo.
* **Separacion**: la distancia mediana entre tomas de gestos distintos dividida
  por la de tomas del mismo gesto. Es lo que dice cuanto margen hay: una
  exactitud del 100 % con separacion 1.1x se cae con la primera persona nueva.

Las dos representaciones
------------------------
* **3D**: `pose_world_landmarks` canonicalizados al marco del cuerpo y
  normalizados por el largo del torso.
* **2D**: `pose_landmarks` del plano de imagen, centrados en las caderas y
  normalizados por el ancho de hombros. Es el 2D **de verdad**, no una
  proyeccion del 3D: una proyeccion heredaria el prior de profundidad del
  modelo y favoreceria al 3D por construccion.

Transferencia entre vistas
--------------------------
Si el material tiene tomas con varias orientaciones, se mide ademas si una
plantilla grabada de frente sirve para reconocer el mismo gesto girado. Es la
pregunta que decide si con seis camaras hacen falta seis juegos de plantillas o
uno solo.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

MODULE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = MODULE_DIR.parents[1]
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from dataset.storage import Toma, cargar_todas, resumen  # noqa: E402
from pose.normalize import (  # noqa: E402
    LEFT_ELBOW,
    LEFT_HIP,
    LEFT_SHOULDER,
    LEFT_WRIST,
    RIGHT_ELBOW,
    RIGHT_HIP,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
    body_frame,
)
from recognition.dtw import dtw_distancia  # noqa: E402

#: Articulaciones que forman el vector de rasgos. Munecas y codos bastan para
#: un aplauso y para la mayoria de gestos de brazos.
ARTICULACIONES = (RIGHT_WRIST, LEFT_WRIST, RIGHT_ELBOW, LEFT_ELBOW)

#: Todas las tomas se llevan a esta tasa antes de comparar. No cambia la
#: duracion —eso es informacion del gesto— pero hace comparables tomas
#: grabadas a fps distintos.
HZ = 30.0

#: Fraccion minima de frames con pose para que una toma cuente.
COBERTURA_MINIMA = 0.60


def _remuestrear(X: np.ndarray, t: np.ndarray, hz: float = HZ) -> np.ndarray | None:
    """Lleva `(T, D)` a una rejilla uniforme, interpolando los huecos."""
    valido = np.all(np.isfinite(X), axis=1)
    if valido.mean() < COBERTURA_MINIMA or valido.sum() < 4:
        return None
    tv, Xv = t[valido], X[valido]
    n = max(int(round((tv[-1] - tv[0]) * hz)) + 1, 4)
    rejilla = np.linspace(tv[0], tv[-1], n)
    return np.stack([np.interp(rejilla, tv, Xv[:, j])
                     for j in range(X.shape[1])], axis=1)


def rasgos_3d(toma: Toma) -> np.ndarray | None:
    """Marco corporal, normalizado por torso. `(N, 12)`."""
    W, V = toma.world, toma.visibility
    salida = np.full((len(W), len(ARTICULACIONES), 3), np.nan)
    torsos = []
    for k in range(len(W)):
        marco = body_frame(W[k], V[k])
        if marco is None or not marco.valid:
            continue
        torsos.append(marco.torso_length_m)
        salida[k] = marco.apply(W[k])[list(ARTICULACIONES)]
    if not torsos:
        return None
    escala = float(np.median(torsos))
    if not np.isfinite(escala) or escala < 1e-6:
        return None
    X = (salida / escala).reshape(len(W), -1)
    return _remuestrear(X, toma.timestamps)


def rasgos_2d(toma: Toma) -> np.ndarray | None:
    """Plano de imagen, centrado en caderas y normalizado por hombros. `(N, 8)`.

    Es lo que puede hacer un pipeline 2D: no hay torso metrico ni marco
    corporal, asi que el unico normalizador disponible es el ancho de hombros
    en la imagen. De perfil tiende a cero, y ahi esta su limite.
    """
    P = toma.imagen
    cad = (P[:, LEFT_HIP] + P[:, RIGHT_HIP]) / 2.0
    ancho = np.linalg.norm(P[:, LEFT_SHOULDER] - P[:, RIGHT_SHOULDER], axis=1)

    # Una escala por toma, no una por frame. Dividir frame a frame parece mas
    # fino y es peor: el ancho de hombros estimado se desploma en frames
    # sueltos —medido, hasta 100 veces por debajo de la mediana de su propia
    # toma— y ahi los rasgos explotan. Ademas seria una comparacion tramposa:
    # `rasgos_3d` usa la mediana del torso de la toma, y el 2D tiene que
    # jugar con la misma regla.
    escala = float(np.nanmedian(ancho[np.isfinite(ancho) & (ancho > 1e-6)]))
    if not np.isfinite(escala) or escala < 1e-6:
        return None
    with np.errstate(invalid="ignore", divide="ignore"):
        Q = (P[:, list(ARTICULACIONES)] - cad[:, None, :]) / escala
    Q[~np.isfinite(Q)] = np.nan
    return _remuestrear(Q.reshape(len(P), -1), toma.timestamps)


def matriz_de_distancias(rasgos: list[np.ndarray]) -> np.ndarray:
    n = len(rasgos)
    D = np.full((n, n), np.inf)
    for i in range(n):
        D[i, i] = 0.0
        for j in range(i + 1, n):
            d = dtw_distancia(rasgos[i], rasgos[j])
            D[i, j] = D[j, i] = d
    return D


def evaluar(D: np.ndarray, etiquetas: list[str]) -> dict:
    """1-NN dejando fuera la propia toma."""
    n = len(etiquetas)
    predichas, aciertos = [], 0
    for i in range(n):
        otros = [j for j in range(n) if j != i]
        if not otros:
            predichas.append(None)
            continue
        j = min(otros, key=lambda k: D[i, k])
        predichas.append(etiquetas[j])
        aciertos += etiquetas[j] == etiquetas[i]

    mismo, distinto = [], []
    for i in range(n):
        for j in range(i + 1, n):
            (mismo if etiquetas[i] == etiquetas[j] else distinto).append(D[i, j])
    m = float(np.median(mismo)) if mismo else float("nan")
    x = float(np.median(distinto)) if distinto else float("nan")
    return {
        "exactitud": aciertos / n if n else 0.0,
        "d_mismo": m,
        "d_distinto": x,
        "separacion": x / m if m and np.isfinite(m) and m > 0 else float("nan"),
        "predichas": predichas,
    }


def confusion(etiquetas: list[str], predichas: list[str | None]) -> str:
    clases = sorted(set(etiquetas))
    ancho = max(len(c) for c in clases) + 2
    lineas = ["    " + "real \\ leido".ljust(ancho)
              + "".join(c.rjust(ancho) for c in clases)]
    for real in clases:
        fila = [sum(1 for e, p in zip(etiquetas, predichas)
                    if e == real and p == leido) for leido in clases]
        lineas.append("    " + real.ljust(ancho)
                      + "".join(str(v).rjust(ancho) for v in fila))
    return "\n".join(lineas)


def entre_personas(tomas, rasgos, semilla: int = 0) -> str:
    """Sirve la plantilla de una persona para otra?

    Se puede medir **con una sola clase de gesto**, que es lo que suele haber
    primero. Compara, para cada toma, la distancia a la plantilla mas cercana
    de su propia persona contra la mas cercana de las demas.

    Los dos bancos se igualan en tamano por sorteo. Sin eso el banco ajeno
    gana siempre: el minimo sobre 36 tomas es menor que sobre 11 aunque las
    plantillas sean identicas en calidad, y la conclusion saldria al reves.
    """
    personas = sorted({t.persona for t in tomas})
    if len(personas) < 2:
        return ""
    rng = np.random.default_rng(semilla)
    n = len(rasgos)
    D = matriz_de_distancias(rasgos)
    quien = [t.persona for t in tomas]

    lineas = [f"    {'persona':>10} {'banco propio':>13} {'banco ajeno':>12} "
              f"{'penalizacion':>13}"]
    penas = []
    for p_ in personas:
        propios = [i for i in range(n) if quien[i] == p_]
        ajenos = [i for i in range(n) if quien[i] != p_]
        k = len(propios) - 1
        if k < 1 or len(ajenos) < k:
            continue
        d_pro, d_aje = [], []
        for i in propios:
            d_pro.append(min(D[i, m] for m in propios if m != i))
            d_aje.append(float(np.median([
                min(D[i, m] for m in rng.choice(ajenos, k, replace=False))
                for _ in range(40)])))
        razon = float(np.median(d_aje) / np.median(d_pro))
        penas.append(razon)
        lineas.append(f"    {p_:>10} {np.median(d_pro):13.3f} "
                      f"{np.median(d_aje):12.3f} {razon:12.2f}x")
    if penas:
        lineas.append(f"    {'MEDIA':>10} {'':13} {'':12} "
                      f"{float(np.mean(penas)):12.2f}x")
        lineas.append("")
        lineas.append("    1.0x = la plantilla de un desconocido sirve igual "
                      "que la propia.")

    # Identificar a la persona por su gesto es justo lo que NO se quiere.
    aciertos = sum(
        quien[min((k for k in range(n) if k != i), key=lambda k: D[i, k])] == quien[i]
        for i in range(n)
    )
    mayor = max(quien.count(p_) for p_ in personas)
    lineas.append(f"    identifica a la persona por su gesto: "
                  f"{100 * aciertos / n:.0f} %  (azar {100 * mayor / n:.0f} %)")

    tri = np.triu(np.ones((n, n), bool), 1)
    d = D[tri]
    d = d[np.isfinite(d)]
    if d.size:
        lineas.append(f"    cola de la distribucion p90/p50: "
                      f"{np.percentile(d, 90) / np.median(d):.1f}x  "
                      f"(adimensional, comparable entre 3D y 2D)")
    return "\n".join(lineas)


def por_sujeto(tomas, rasgos, etiquetas) -> str:
    """Leave-one-subject-out: plantillas de unas personas, prueba en otra.

    Es la evaluacion que dice si el sistema **generaliza**. La de leave-one-out
    por toma no lo dice: con varias repeticiones de la misma persona, cada toma
    tiene de vecina otra suya, y eso mide repetibilidad, no generalizacion.

    Ibañez et al. reportan 99.1 % con validacion cruzada aleatoria por muestra,
    no por sujeto. Es una diferencia importante al comparar cifras.
    """
    personas = sorted({t.persona for t in tomas})
    if len(personas) < 2:
        return ""
    lineas = [f"    {'fuera':>14} {'tomas':>6} {'exactitud':>10}"]
    total, aciertos_total = 0, 0
    for quien in personas:
        prueba = [i for i, t in enumerate(tomas) if t.persona == quien]
        banco = [i for i, t in enumerate(tomas) if t.persona != quien]
        if not banco or not prueba:
            continue
        aciertos = 0
        for i in prueba:
            j = min(banco, key=lambda k: dtw_distancia(rasgos[i], rasgos[k]))
            aciertos += etiquetas[j] == etiquetas[i]
        total += len(prueba)
        aciertos_total += aciertos
        lineas.append(f"    {quien:>14} {len(prueba):6d} "
                      f"{100 * aciertos / len(prueba):9.0f}%")
    if total:
        lineas.append(f"    {'GLOBAL':>14} {total:6d} "
                      f"{100 * aciertos_total / total:9.0f}%")
    return "\n".join(lineas)


def transferencia(tomas, rasgos, etiquetas) -> str:
    """Plantillas de una orientacion, probadas en las demas."""
    orientaciones = sorted({t.orientacion_deg for t in tomas})
    if len(orientaciones) < 2:
        return ""
    base = orientaciones[0]
    idx_base = [i for i, t in enumerate(tomas) if t.orientacion_deg == base]
    lineas = [f"    plantillas de {base:.0f} deg ({len(idx_base)} tomas)",
              f"    {'orientacion':>12} {'tomas':>6} {'exactitud':>10}"]
    for o in orientaciones:
        idx = [i for i, t in enumerate(tomas) if t.orientacion_deg == o]
        aciertos = 0
        for i in idx:
            cand = [j for j in idx_base if j != i]
            if not cand:
                continue
            j = min(cand, key=lambda k: dtw_distancia(rasgos[i], rasgos[k]))
            aciertos += etiquetas[j] == etiquetas[i]
        lineas.append(f"    {o:11.0f}° {len(idx):6d} "
                      f"{100 * aciertos / max(len(idx), 1):9.0f}%")
    return "\n".join(lineas)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compara 3D y 2D sobre las tomas grabadas")
    parser.add_argument("--carpeta", help="por defecto results/data/gestos")
    args = parser.parse_args()

    carpeta = Path(args.carpeta) if args.carpeta \
        else PROJECT_DIR / "results" / "data" / "gestos"
    tomas = cargar_todas(carpeta)
    if not tomas:
        print(f"No hay tomas en {carpeta}.")
        print(r"Grabalas con: python .\external\gesture_detection\grabar_gestos.py")
        return 1

    print(f"Material en {carpeta}")
    print(resumen(tomas))
    personas = sorted({t.persona for t in tomas})
    if len(personas) < 2:
        print("\n  AVISO: una sola persona. La exactitud que sale mide "
              "repetibilidad,")
        print("  no generalizacion. Para lo segundo hacen falta al menos tres.")

    gestos = sorted({t.gesto for t in tomas})
    una_clase = len(gestos) < 2
    if una_clase:
        print(f"\n  Solo hay un gesto ({gestos[0]}): no se puede medir separacion "
              f"entre gestos.")
        print("  Se mide lo que si se puede con una clase: si una plantilla "
              "sirve entre personas.")
        print(r"  Para el resto: python .\external\gesture_detection\grabar_gestos.py --gesto reposo")

    print()
    resultados = {}
    for nombre, hacer in (("3D", rasgos_3d), ("2D", rasgos_2d)):
        pares = [(t, hacer(t)) for t in tomas]
        usables = [(t, r) for t, r in pares if r is not None]
        if len(usables) < 3:
            print(f"{nombre}: solo {len(usables)} tomas utilizables, no alcanza.")
            continue
        if len(usables) < len(pares):
            print(f"{nombre}: se descartan {len(pares) - len(usables)} tomas "
                  f"sin pose suficiente.")
        sub_tomas = [t for t, _ in usables]
        rasgos = [r for _, r in usables]
        etiquetas = [t.gesto for t in sub_tomas]
        print(f"=== {nombre} ({rasgos[0].shape[1]} rasgos por muestra, "
              f"{len(sub_tomas)} tomas)")
        ep = entre_personas(sub_tomas, rasgos)
        if ep:
            print("    plantillas entre personas:")
            print(ep)
            print()
        if una_clase:
            continue
        r = evaluar(matriz_de_distancias(rasgos), etiquetas)
        resultados[nombre] = (r, sub_tomas, rasgos, etiquetas)

        print(f"    exactitud 1-NN      {100 * r['exactitud']:5.1f} %  "
              f"sobre {len(sub_tomas)} tomas")
        print(f"    d mismo gesto       {r['d_mismo']:.3f}")
        print(f"    d gestos distintos  {r['d_distinto']:.3f}")
        print(f"    separacion          {r['separacion']:.2f}x")
        print(confusion(etiquetas, r["predichas"]))
        ps = por_sujeto(sub_tomas, rasgos, etiquetas)
        if ps:
            print("    generalizacion entre personas (leave-one-subject-out):")
            print(ps)
        t = transferencia(sub_tomas, rasgos, etiquetas)
        if t:
            print("    transferencia entre orientaciones:")
            print(t)
        print()

    if len(resultados) == 2:
        (a, *_), (b, *_) = resultados["3D"], resultados["2D"]
        print("=== Veredicto")
        print(f"    {'':<14} {'3D':>8} {'2D':>8}")
        print(f"    {'exactitud':<14} {100*a['exactitud']:7.1f}% "
              f"{100*b['exactitud']:7.1f}%")
        print(f"    {'separacion':<14} {a['separacion']:7.2f}x "
              f"{b['separacion']:7.2f}x")
        if not np.isfinite(a["separacion"]) or not np.isfinite(b["separacion"]):
            pass
        elif b["separacion"] >= a["separacion"] * 0.9:
            print("\n    Con una sola camara de frente, el 2D no se queda atras.")
            print("    Lo que el 3D compra no es exactitud aqui, es que la misma")
            print("    plantilla sirva desde cualquier camara del anillo. Eso solo")
            print("    lo mide material con varias orientaciones.")
        else:
            print("\n    El 3D separa mejor incluso de frente.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
