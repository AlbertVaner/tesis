"""Corrige las etiquetas de un lote de tomas ya grabadas. No toca el original.

Si una sesion se grabo sin cambiar el gesto ni la orientacion con `g` y `o`,
todas las tomas quedan con la misma etiqueta aunque el material sea correcto.
Este programa reconstruye las etiquetas sin regrabar nada.

Uso, desde la raiz del repositorio:

    python .\\external\\gesture_detection\\reetiquetar_gestos.py --revisar
    python .\\external\\gesture_detection\\reetiquetar_gestos.py ^
        --gestos aplauso,saludo,circulo,arriba

De donde sale cada etiqueta
---------------------------
**La orientacion se MIDE**, no se supone: `yaw_camara()` la saca del eje de
hombros y caderas en coordenadas de camara. Es mas fiable que el numero que se
teclea, porque nadie se gira exactamente 45 grados.

**El gesto sale del orden de grabacion**: si se grabo cada gesto seguido, en
bloques de `--por-gesto` tomas, la posicion en la secuencia dice cual es. Eso
viene del protocolo y no de los datos, asi que usarlo despues para evaluar no
es circular.

`--revisar` no escribe nada: muestra lo que haria. Conviene mirarlo antes,
porque si el orden de grabacion no fue el que se supone, las etiquetas
saldrian mal y todo lo que venga despues heredaria el error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = MODULE_DIR.parents[1]
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from dataset.storage import Toma, cargar_todas, guardar, resumen  # noqa: E402
from pose.normalize import yaw_camara  # noqa: E402


def banda_de_angulo(grados: float, cortes: tuple[float, ...]) -> float:
    """Redondea el angulo medido a la referencia mas cercana."""
    return min(cortes, key=lambda c: abs(abs(grados) - c)) * (1 if grados >= 0 else -1)


def reetiquetar(toma: Toma, gestos: list[str], por_gesto: int,
                cortes: tuple[float, ...],
                posicion: int | None = None) -> tuple[Toma, float]:
    """`posicion` es el lugar de la toma dentro de su persona, ya descartadas
    las que sobran. Usar el numero de archivo corre todos los bloques que
    siguen a una toma de mas."""
    medido = yaw_camara(toma.world)
    k = toma.numero - 1 if posicion is None else posicion
    indice = k // por_gesto
    gesto = gestos[indice] if 0 <= indice < len(gestos) else f"extra{indice + 1}"
    numero = k % por_gesto + 1
    nueva = Toma(
        persona=toma.persona,
        gesto=gesto,
        numero=numero,
        orientacion_deg=round(banda_de_angulo(medido, cortes), 1),
        world=toma.world,
        imagen=toma.imagen,
        visibility=toma.visibility,
        timestamps=toma.timestamps,
    )
    return nueva, medido


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reetiqueta tomas grabadas sin cambiar el material")
    parser.add_argument("--carpeta", help="origen; por defecto results/data/gestos")
    parser.add_argument("--destino", help="por defecto <origen>_reetiquetado")
    parser.add_argument("--gestos", default="",
                        help="nombres separados por coma, en el orden en que se grabaron")
    parser.add_argument("--por-gesto", type=int, default=3,
                        help="tomas seguidas de cada gesto (por defecto 3, una por angulo)")
    parser.add_argument("--angulos", default="0,45,90",
                        help="orientaciones de referencia a las que redondear")
    parser.add_argument("--personas", default="",
                        help="solo estas personas, separadas por coma. Sirve "
                             "cuando distintos grupos grabaron gestos distintos: "
                             "se corre una vez por grupo sobre la misma carpeta")
    parser.add_argument("--saltar", default="",
                        help="tomas a descartar, como Persona:numero separados "
                             "por coma. Una toma de mas corre todos los bloques "
                             "siguientes")
    parser.add_argument("--revisar", action="store_true",
                        help="no escribe: muestra lo que haria")
    args = parser.parse_args()

    origen = Path(args.carpeta) if args.carpeta \
        else PROJECT_DIR / "results" / "data" / "gestos"
    tomas = cargar_todas(origen)
    if not tomas:
        print(f"No hay tomas en {origen}.")
        return 1

    quienes = {p.strip().lower() for p in args.personas.split(",") if p.strip()}
    if quienes:
        tomas = [t for t in tomas if t.persona.lower() in quienes]
        if not tomas:
            print(f"Ninguna toma de {sorted(quienes)} en {origen}.")
            return 1
    saltar = set()
    for item in args.saltar.split(","):
        if ":" in item:
            quien, num = item.split(":", 1)
            saltar.add((quien.strip().lower(), int(num)))
    if saltar:
        antes = len(tomas)
        tomas = [t for t in tomas
                 if (t.persona.lower(), t.numero) not in saltar]
        print(f"Descartadas {antes - len(tomas)} tomas por --saltar")

    gestos = [g.strip() for g in args.gestos.split(",") if g.strip()]
    cortes = tuple(float(a) for a in args.angulos.split(","))
    if not gestos and not args.revisar:
        print("Falta --gestos con los nombres en el orden de grabacion.")
        print("Corre primero --revisar para comprobar que el orden cuadra.")
        return 1
    if not gestos:
        gestos = [f"gesto{i + 1}" for i in range(8)]

    print(f"Origen: {origen}")
    print(resumen(tomas))
    print(f"\nBloques de {args.por_gesto} tomas por gesto; "
          f"angulos de referencia {cortes}\n")

    print(f"{'toma original':<34} {'medido':>8} {'->':^4} "
          f"{'gesto':<12} {'orientacion':>11} {'#':>3}")
    nuevas = []
    posiciones: dict[str, int] = {}
    for toma in sorted(tomas, key=lambda t: (t.persona, t.numero)):
        pos = posiciones.get(toma.persona, 0)
        posiciones[toma.persona] = pos + 1
        nueva, medido = reetiquetar(toma, gestos, args.por_gesto, cortes, pos)
        nuevas.append(nueva)
        print(f"{toma.ruta.name:<34} {medido:+7.1f}° {'->':^4} "
              f"{nueva.gesto:<12} {nueva.orientacion_deg:+10.1f}° "
              f"{nueva.numero:3d}")

    if args.revisar:
        print("\n--revisar: no se escribio nada.")
        print("Comproba que los bloques cuadran con el orden real de grabacion.")
        return 0

    destino = Path(args.destino) if args.destino \
        else origen.parent / f"{origen.name}_reetiquetado"
    for nueva in nuevas:
        guardar(destino, nueva)
    print(f"\n{len(nuevas)} tomas escritas en {destino}")
    print("El material original queda intacto.")
    print(resumen(nuevas))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
