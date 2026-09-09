"""Graba el vocabulario final de gestos, persona por persona. Sin dron.

Es `grabar_gestos.py --guiado` con el guion del vocabulario que va a volar.
El bucle de camara, el encuadre y el formato de las tomas son los mismos;
aqui solo vive **que** se graba, **cuantas veces** y **que se le dice** al
operador en cada toma.

Uso, desde la raiz del repositorio:

    python .\\external\\gesture_detection\\grabar_vocabulario.py
    python .\\external\\gesture_detection\\grabar_vocabulario.py --persona ana
    python .\\external\\gesture_detection\\grabar_vocabulario.py --solo senalero,circulo
    python .\\external\\gesture_detection\\grabar_vocabulario.py --sin-negativos

`--solo` sirve para alguien que ya grabo los tres gestos viejos y solo debe
aportar los nuevos. `--sin-negativos` salta reposo, paro y rechazo, para una
segunda tanda de alguien que ya los grabo.

Que hay en el guion y por que
-----------------------------
**Cinco gestos dinamicos**, los que van al banco de DTW. Cada uno tiene una
firma distinta en munecas y codos, que es todo lo que mira el reconocedor:

    senalero   dos manos, arriba, oscilan       despegar / aterrizar
    aplaudir   dos manos, convergen al pecho    habilitar / inhabilitar
    ven_aca    una mano, frontal, hacia el cuerpo   seguir al marker
    arco       dos manos, subida lateral, lenta  alejarse del marker
    circulo    una mano, todo el brazo, circular orbitar el marker

Saludar se probo y se quito: es "una mano que oscila", igual que ven_aca, y
la unica diferencia era la altura, que cada persona elige distinta (medido
el 2026-09-07 sobre 5 personas: 18 de 57 saludos leidos como ven_aca).

**Una postura estatica**, `paro`: brazos cruzados en X sobre el pecho. No va
al banco de DTW —se reconoce por regla— pero **si hace falta grabarla**: los
umbrales de la regla salen de medir muñecas y codos en esa postura, no de
adivinarlos.

**Reposo**: la persona parada sin hacer nada, y en especial cruzandose de
brazos como le salga. Es lo que mide la tasa de falsos paros de emergencia,
que es el numero mas importante de todo el dataset: cruzarse de brazos es la
postura mas comun de alguien esperando.

**Rechazo** (`otro`): movimientos que NO son ninguno de los gestos pero se
les parecen. Sin ellos el banco no puede decir "esto no es nada", y medido,
los movimientos ajenos caen mas cerca que los aciertos. Las tomas dificiles
apuntan a las firmas del vocabulario nuevo: saludar a alguien (se parece al
senalero), estirarse (al arco), rascarse la cabeza con el brazo (al circulo).

Se agrupa por angulo y no por gesto: girarse es lo lento, y uno se coloca una
vez y hace todo desde ahi. El perfil (90) va porque es donde se rompe el 2D
y donde se sabra si el 3D aguanta.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = MODULE_DIR.parents[1]
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from dataset.storage import carpeta_de_hoy  # noqa: E402

#: Gestos dinamicos del vocabulario, en el orden en que se graban.
GESTOS = ("senalero", "aplaudir", "ven_aca", "arco", "circulo")

#: Postura estatica. Se graba sostenida, una vez por angulo.
PARO = "paro"

#: Angulos respecto de la camara y repeticiones de cada gesto dinamico en
#: cada uno. 0 y +-45 cubren lo que ven dos camaras adyacentes del anillo;
#: 90 es el caso limite.
ANGULOS = ((0.0, 2), (45.0, 2), (-45.0, 2), (90.0, 2))

#: Tomas de reposo y en que angulo. Largas: 30 s cada una.
REPOSO = ((0.0, 1), (45.0, 1))

#: Tomas de rechazo, todas de frente. Las primeras son las dificiles.
OTRO_QUE = (
    "saluda a alguien fuera de camara con una mano, a media altura",
    "estirate: los dos brazos arriba y bajalos despacio",
    "rascate la cabeza y peinate con una mano",
    "cruzate de brazos relajado, a la altura del vientre, y descruzate",
    "gesticula con las dos manos como explicando algo",
    "acomodate la camisa o el cuello",
    "mira el telefono y guardalo",
    "camina un par de pasos y volve",
)

#: Instruccion en pantalla para cada gesto. Corta, porque cabe en una linea.
COMO = {
    "senalero": "SENALERO: dos brazos arriba, oscila los antebrazos 3-4 veces, codos altos",
    "aplaudir": "APLAUDIR: aplaudi 3-4 veces a la altura del pecho",
    "ven_aca": "VEN ACA: llama con UNA mano a la altura del pecho, 3 veces",
    "arco": "ARCO: sube los dos brazos por los lados hasta arriba, despacio, sin repetir",
    "circulo": "CIRCULO: UNA mano, todo el brazo, un circulo grande frente a vos, 2 vueltas",
    "paro": "PARO: brazos cruzados en X por ENCIMA de la cabeza. NO pares hasta que el contador pase de 6 s",
    "reposo": "REPOSO 30 s: espera parado, movete, cruzate de brazos si te sale",
}


def construir_guion(gestos=GESTOS, angulos=ANGULOS, reposo=REPOSO,
                    otro=len(OTRO_QUE), con_paro=True):
    """`[(gesto, orientacion, numero)]` con la sesion completa de una persona."""
    pasos, cuenta = [], {}

    def paso(gesto, angulo):
        clave = (gesto, angulo)
        cuenta[clave] = cuenta.get(clave, 0) + 1
        pasos.append((gesto, angulo, cuenta[clave]))

    for angulo, repeticiones in angulos:
        for gesto in gestos:
            for _ in range(repeticiones):
                paso(gesto, angulo)
        if con_paro:
            paso(PARO, angulo)
    for angulo, repeticiones in reposo:
        for _ in range(repeticiones):
            paso("reposo", angulo)
    for _ in range(otro):
        paso("otro", 0.0)
    return pasos


def instruccion(gesto: str, numero: int) -> str:
    """Que se le dice al operador en cada toma."""
    if gesto == "otro":
        return f"NO es un gesto: {OTRO_QUE[(numero - 1) % len(OTRO_QUE)]}"
    return COMO.get(gesto, gesto)


def duracion_estimada_min(guion) -> float:
    """Minutos aproximados de una sesion, para avisar antes de empezar."""
    por_toma = {"reposo": 35.0, "paro": 8.0, "otro": 10.0}
    segundos = sum(por_toma.get(g, 8.0) for g, _, _ in guion)
    giros = len({a for _, a, _ in guion}) * 20.0
    return (segundos + giros) / 60.0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Graba el vocabulario final de gestos, guiado")
    parser.add_argument("--persona", help="salta la pregunta del nombre")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--solo", help="gestos dinamicos a grabar, separados "
                                        "por coma; por defecto los cinco")
    parser.add_argument("--repeticiones", type=int,
                        help="repeticiones por gesto y angulo; por defecto 2")
    parser.add_argument("--sin-negativos", action="store_true",
                        help="salta reposo, paro y rechazo")
    parser.add_argument("--carpeta", help="destino; por defecto results/data/gestos")
    args = parser.parse_args()

    gestos = tuple(g.strip() for g in args.solo.split(",")) if args.solo else GESTOS
    desconocidos = [g for g in gestos if g not in GESTOS]
    if desconocidos:
        parser.error(f"gestos desconocidos: {desconocidos}; validos: {GESTOS}")
    angulos = (tuple((a, args.repeticiones) for a, _ in ANGULOS)
               if args.repeticiones else ANGULOS)
    guion = construir_guion(
        gestos=gestos, angulos=angulos,
        reposo=() if args.sin_negativos else REPOSO,
        otro=0 if args.sin_negativos else len(OTRO_QUE),
        con_paro=not args.sin_negativos,
    )

    # Se importa aqui y no arriba: trae OpenCV y MediaPipe, y `--help` y las
    # pruebas del guion no los necesitan.
    from grabar_gestos import bucle, preguntar  # noqa: E402

    persona, _ = preguntar(argparse.Namespace(persona=args.persona, numero=1))
    carpeta = Path(args.carpeta) if args.carpeta else carpeta_de_hoy(PROJECT_DIR)

    print(f"\nPersona: {persona}   {len(guion)} tomas, "
          f"unos {duracion_estimada_min(guion):.0f} min")
    print("  ENTER graba y para; el gesto y el angulo los pone el programa.")
    print("  b repite la toma anterior si salio mal.   q sale.")
    print("  El angulo es cuanto estas girado respecto de la camara: "
          "+45 a tu derecha, -45 a tu izquierda, 90 de perfil.\n")

    try:
        n = bucle(camara=args.camera, persona=persona, gesto=guion[0][0],
                  numero=1, orientacion=guion[0][1], carpeta=carpeta,
                  guion=guion, instruccion=instruccion)
        print(f"\n{n} tomas guardadas en {carpeta}")
        if n:
            print("Siguiente paso, cuando haya al menos tres personas:")
            print(r"  python .\external\gesture_detection\construir_plantillas.py "
                  r"--carpeta results\data\gestos "
                  r"--gestos senalero,aplaudir,ven_aca,arco,circulo "
                  r"--negativos otro,senalar_mano,six_seven")
        return 0
    except KeyboardInterrupt:
        print("Interrupcion solicitada.")
        return 130
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
