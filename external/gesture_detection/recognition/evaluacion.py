"""Como se mide un reconocedor por plantillas, y por que de esta forma.

Un banco de plantillas no se entrena: no hay pesos que ajustar ni curvas de
perdida que mirar. Lo unico que se elige mirando datos es **el umbral**, y ahi
esta el riesgo. Si el umbral se elige sobre las mismas distancias que despues
se reportan, la cifra publicada es optimista: es la misma fuga de datos que
tomar decisiones de diseno sobre el conjunto de prueba.

Este modulo separa las dos preguntas:

* `loso` responde *que gesto leeria el sistema*, dejando fuera a la persona.
* `loso_anidado` responde *cuanto acierta con un umbral que nunca vio a esa
  persona*: dentro de cada pliegue vuelve a dejar fuera a otra persona para
  medir el umbral. Es la unica cifra defendible.

Y separa la exactitud de las metricas que sobreviven al desbalance. Con 72
gestos del vocabulario y 30 movimientos ajenos, la exactitud global esconde
que el rechazo es la mitad de bueno que el reconocimiento; la precision, la
exhaustividad y la F1 por clase no lo esconden.

Un umbral o varios
------------------
`umbrales_por_clase` mide uno por gesto. Un solo numero obliga a todos al mismo
compromiso y no lo tienen: medido sobre el vocabulario de cinco gestos, el
umbral que `aplaudir` necesita es 0.373 y el global es 0.708. Con el global,
`aplaudir` se traga los `ven_aca` y los movimientos ajenos que pasan cerca; con
el suyo, deja de hacerlo. Lo que se paga es exhaustividad: el mismo gesto se
lee menos veces. Los dos numeros se reportan para poder elegir con datos.

Convenio de etiquetas
---------------------
`None` como prediccion significa **no se emite ningun comando**: o la
distancia paso del umbral, o el vecino mas cercano era material de rechazo.
`None` como etiqueta real significa que la toma era un movimiento ajeno y lo
correcto era no emitir nada. En las tablas eso se imprime como `RECHAZADO`.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

import numpy as np

from recognition.dtw import dtw_distancia, umbral_por_separacion

#: Como se muestra "ningun comando" en las tablas.
RECHAZADO = "(rechazado)"


def _nombre(etiqueta: str | None) -> str:
    return RECHAZADO if etiqueta is None else etiqueta


def matriz_de_distancias(rasgos: list[np.ndarray]) -> np.ndarray:
    """Distancias DTW de todos contra todos, `(n, n)` y simetrica."""
    n = len(rasgos)
    D = np.full((n, n), np.inf)
    for i in range(n):
        D[i, i] = 0.0
        for j in range(i + 1, n):
            D[i, j] = D[j, i] = dtw_distancia(rasgos[i], rasgos[j])
    return D


def loso(D: np.ndarray, etiquetas: list[str], personas: list[str]) -> dict:
    """1-NN dejando fuera a la persona, sin umbral.

    Mide lo que el clasificador *elegiria* entre las clases del banco. No dice
    nada sobre rechazar, porque sin umbral siempre hay un vecino mas cercano.

    Returns:
        `predichas`, `distancias` a ese vecino, `exactitud`, y esas mismas
        distancias separadas en `aciertos` y `fallos`.
    """
    n = len(etiquetas)
    predichas: list[str | None] = []
    distancias: list[float] = []
    aciertos: list[float] = []
    fallos: list[float] = []
    ok = 0
    for i in range(n):
        banco = [k for k in range(n) if personas[k] != personas[i]]
        if not banco:
            predichas.append(None)
            distancias.append(float("inf"))
            continue
        j = min(banco, key=lambda k: D[i, k])
        predichas.append(etiquetas[j])
        distancias.append(float(D[i, j]))
        if etiquetas[j] == etiquetas[i]:
            aciertos.append(float(D[i, j]))
            ok += 1
        else:
            fallos.append(float(D[i, j]))
    return {
        "predichas": predichas,
        "distancias": distancias,
        "exactitud": ok / n if n else 0.0,
        "aciertos": aciertos,
        "fallos": fallos,
    }


#: Cuantas distancias hacen falta a cada lado para fiarse de un umbral propio.
#: Con menos, el umbral sale de dos o tres numeros y es ruido: mejor el global.
MINIMO_POR_CLASE = 3


def umbrales_por_clase(distancias, predichas, reales, respaldo: float,
                       minimo: int = MINIMO_POR_CLASE) -> dict[str, float]:
    """Un umbral para cada gesto, medido sobre las veces que se lee ese gesto.

    Un umbral unico obliga a todos los gestos al mismo compromiso, y no lo
    tienen: `senalero` es casi el mismo movimiento en todo el mundo y `arco`
    cambia mucho de una persona a otra. El global se pone donde menos dana en
    promedio, y ahi ya es demasiado estrecho para el gesto variable y demasiado
    ancho para el estable.

    La poblacion de cada clase es la que decide su umbral: las distancias con
    las que **se leyo ese gesto** —acertando, que son los positivos, y
    equivocandose, que son los negativos—. Es exactamente lo que el umbral
    tiene que separar cuando el reconocedor propone ese gesto.

    Args:
        respaldo: umbral global, que se usa para las clases sin material
            suficiente a los dos lados.
    """
    umbrales: dict[str, float] = {}
    for c in sorted(set(predichas) - {None}):
        pos = [d for d, p, r in zip(distancias, predichas, reales)
               if p == c and r == c]
        neg = [d for d, p, r in zip(distancias, predichas, reales)
               if p == c and r != c]
        if len(pos) < minimo or len(neg) < minimo:
            umbrales[c] = float(respaldo)
            continue
        u, _ = umbral_por_separacion(pos, neg)
        umbrales[c] = float(u) if np.isfinite(u) else float(
            np.percentile(pos, 90))
    return umbrales


def loso_anidado(D: np.ndarray, etiquetas: list[str], personas: list[str],
                 rechazo: str | None = None, por_clase: bool = False) -> dict:
    """Exactitud con un umbral que **nunca vio** a la persona evaluada.

    Para cada persona que se deja fuera, el umbral se mide repitiendo el
    dejar-fuera-a-uno *dentro* del resto. Asi el umbral y la cifra que se
    reporta no salen del mismo material.

    Args:
        rechazo: nombre de la clase de material ajeno, si el banco la tiene.
            Leerla equivale a no emitir comando, igual que pasarse del umbral;
            y una toma de esa clase se acierta no emitiendo nada.
        por_clase: mide un umbral para cada gesto en vez de uno solo. Los
            umbrales tambien salen de dentro del pliegue, asi que la cifra
            sigue siendo honesta.

    Returns:
        `umbrales` (uno por persona), `umbrales_clase` (por persona y gesto, si
        `por_clase`), `predichas` y `reales` ya con `None` donde corresponde no
        emitir nada, y la `exactitud` honesta.
    """
    n = len(etiquetas)
    quienes = sorted(set(personas))
    umbrales: dict[str, float] = {}
    umbrales_clase: dict[str, dict[str, float]] = {}
    predichas: list[str | None] = [None] * n
    reales: list[str | None] = [None if e == rechazo else e for e in etiquetas]
    evaluadas, ok = 0, 0

    for quien in quienes:
        prueba = [i for i in range(n) if personas[i] == quien]
        dentro = [i for i in range(n) if personas[i] != quien]
        if not prueba or not dentro:
            continue

        # Umbral medido dentro del pliegue, dejando fuera a otra persona.
        dist: list[float] = []
        leidas: list[str] = []
        ciertas: list[str] = []
        for i in dentro:
            banco = [k for k in dentro if personas[k] != personas[i]]
            if not banco:
                continue
            j = min(banco, key=lambda k: D[i, k])
            dist.append(float(D[i, j]))
            leidas.append(etiquetas[j])
            ciertas.append(etiquetas[i])
        buenas = [d for d, p, r in zip(dist, leidas, ciertas) if p == r]
        malas = [d for d, p, r in zip(dist, leidas, ciertas) if p != r]
        umbral, _ = umbral_por_separacion(buenas, malas)
        if not np.isfinite(umbral):
            # Sin fallos dentro del pliegue no hay separacion que medir; el
            # p90 de los aciertos es el sustituto que ya usa el banco.
            umbral = float(np.percentile(buenas, 90)) if buenas else float("inf")
        umbrales[quien] = float(umbral)
        propios = (umbrales_por_clase(dist, leidas, ciertas, umbral)
                   if por_clase else {})
        if por_clase:
            umbrales_clase[quien] = propios

        for i in prueba:
            j = min(dentro, key=lambda k: D[i, k])
            leido = etiquetas[j]
            if D[i, j] > propios.get(leido, umbral) or leido == rechazo:
                leido = None
            predichas[i] = leido
            evaluadas += 1
            ok += leido == reales[i]

    return {
        "umbrales": umbrales,
        "umbrales_clase": umbrales_clase,
        "predichas": predichas,
        "reales": reales,
        "exactitud": ok / evaluadas if evaluadas else 0.0,
        "evaluadas": evaluadas,
    }


def matriz_confusion(reales, predichas) -> tuple[list[str], dict]:
    """`(clases, conteos)` con `conteos[real][leido]`.

    Las clases incluyen `RECHAZADO` si aparece en cualquiera de los dos lados:
    no emitir nada es una salida del sistema y tiene que verse en la tabla.
    """
    nombres_r = [_nombre(e) for e in reales]
    nombres_p = [_nombre(e) for e in predichas]
    clases = sorted(set(nombres_r) | set(nombres_p))
    conteos: dict = defaultdict(lambda: defaultdict(int))
    for real, leido in zip(nombres_r, nombres_p):
        conteos[real][leido] += 1
    return clases, conteos


def metricas_por_clase(reales, predichas) -> list[dict]:
    """Precision, exhaustividad, F1 y soporte de cada clase.

    Por que no basta la exactitud: con material desbalanceado —muchos gestos
    del vocabulario y pocos ajenos, o al reves— un clasificador que ignore la
    clase pequena sigue sacando una exactitud alta. La F1 de esa clase, no.
    """
    clases, conteos = matriz_confusion(reales, predichas)
    filas = []
    for c in clases:
        tp = conteos[c][c]
        fp = sum(conteos[a][c] for a in clases if a != c)
        fn = sum(conteos[c][b] for b in clases if b != c)
        soporte = tp + fn
        precision = tp / (tp + fp) if tp + fp else float("nan")
        exhaustividad = tp / soporte if soporte else float("nan")
        suma = precision + exhaustividad
        f1 = (2 * precision * exhaustividad / suma
              if np.isfinite(suma) and suma > 0 else 0.0)
        filas.append({
            "clase": c, "soporte": soporte, "tp": tp, "fp": fp, "fn": fn,
            "precision": precision, "exhaustividad": exhaustividad, "f1": f1,
        })
    return filas


def macro_f1(metricas: list[dict]) -> float:
    """F1 promediada por clase: la que no premia ignorar a la minoritaria."""
    if not metricas:
        return 0.0
    return float(np.mean([m["f1"] for m in metricas]))


def formato_matriz(reales, predichas, sangria: str = "    ") -> str:
    clases, conteos = matriz_confusion(reales, predichas)
    ancho = max(max(len(c) for c in clases) + 2, 14)
    lineas = [sangria + "real \\ leido".ljust(ancho)
              + "".join(c.rjust(ancho) for c in clases)]
    for real in clases:
        lineas.append(sangria + real.ljust(ancho)
                      + "".join(str(conteos[real][b]).rjust(ancho)
                                for b in clases))
    return "\n".join(lineas)


def formato_metricas(metricas: list[dict], sangria: str = "    ") -> str:
    ancho = max(max(len(m["clase"]) for m in metricas) + 2, 14)
    lineas = [sangria + "clase".ljust(ancho)
              + "".join(c.rjust(10) for c in
                        ("soporte", "precision", "exhaust.", "F1"))]
    for m in metricas:
        lineas.append(sangria + m["clase"].ljust(ancho)
                      + f"{m['soporte']:10d}{m['precision']:10.2f}"
                      + f"{m['exhaustividad']:10.2f}{m['f1']:10.2f}")
    lineas.append(sangria + "macro-F1".ljust(ancho) + " " * 30
                  + f"{macro_f1(metricas):10.2f}")
    return "\n".join(lineas)


def guardar_csv(carpeta: Path, reales, predichas,
                extra: dict | None = None) -> list[Path]:
    """Escribe matriz de confusion y metricas por clase; devuelve las rutas.

    Se guardan porque una tabla impresa en una consola no entra en un capitulo
    ni se compara con la corrida de la semana siguiente.
    """
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    clases, conteos = matriz_confusion(reales, predichas)
    rutas = []

    ruta = carpeta / "matriz_confusion.csv"
    with ruta.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["real \\ leido"] + clases)
        for real in clases:
            w.writerow([real] + [conteos[real][b] for b in clases])
    rutas.append(ruta)

    ruta = carpeta / "metricas_por_clase.csv"
    campos = ["clase", "soporte", "tp", "fp", "fn",
              "precision", "exhaustividad", "f1"]
    with ruta.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        for m in metricas_por_clase(reales, predichas):
            w.writerow({k: (f"{m[k]:.4f}" if isinstance(m[k], float) else m[k])
                        for k in campos})
    rutas.append(ruta)

    if extra:
        ruta = carpeta / "resumen.csv"
        with ruta.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["clave", "valor"])
            for k, v in extra.items():
                w.writerow([k, f"{v:.4f}" if isinstance(v, float) else v])
        rutas.append(ruta)
    return rutas
