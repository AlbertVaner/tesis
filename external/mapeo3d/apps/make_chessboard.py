"""Genera un tablero de ajedrez para calibración, a escala exacta, en PDF.

El problema que resuelve: casi ningún PDF de tablero descargado de internet se
imprime a la escala que dice, porque el diálogo de impresión aplica "ajustar a
la página" por defecto. Un error de escala del 3 % se propaga a **todo** lo
métrico del sistema — posiciones, distancias, separaciones — y no da ningún
síntoma salvo que todo salga consistentemente mal.

Por eso este generador imprime, junto al tablero:

- Una **regla de verificación de 100 mm** con marcas cada 10 mm.
- La cota del lado de casilla.
- Las dimensiones del tablero completo.

Después de imprimir, se mide la regla. Si no da 100 mm exactos, la impresión
está escalada: hay que reimprimir al 100 % o, si no hay más remedio, medir el
lado real de una casilla y pasarlo con `--square-mm` a la calibración.

Ejemplos
--------
Por defecto (9×6 esquinas interiores, casilla de 23 mm, A4 horizontal)::

    python apps/make_chessboard.py

Más grande, para calibrar a más distancia (A3)::

    python apps/make_chessboard.py --square-mm 35 --paper A3

Nomenclatura
------------
Un tablero de 10×7 **casillas** tiene 9×6 **esquinas interiores**. Lo que se
declara aquí, y lo que espera la calibración, son las esquinas interiores.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

MM_POR_PULGADA = 25.4

# Tamaños de papel en mm, orientación vertical.
# Se incluyen los nombres usados en Latinoamérica además de los ISO.
PAPELES = {
    "A4": (210.0, 297.0),
    "A3": (297.0, 420.0),
    "CARTA": (215.9, 279.4),        # Letter, 8.5 x 11 in
    "LETTER": (215.9, 279.4),
    "OFICIO": (215.9, 330.0),       # 8.5 x 13 in, el habitual en Guatemala
    "LEGAL": (215.9, 355.6),        # 8.5 x 14 in
    "DOBLE_CARTA": (279.4, 431.8),  # Tabloid / Ledger, 11 x 17 in
    "TABLOID": (279.4, 431.8),
}

MARGEN_MM = 12.0  # margen imprimible seguro
REGLA_MM = 100.0
ALTO_PIE_MM = 20.0  # espacio para la regla y las cotas


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Genera un tablero de ajedrez a escala exacta.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--cols", type=int, default=9,
                   help="Esquinas interiores a lo ancho. Por defecto: 9.")
    p.add_argument("--rows", type=int, default=6,
                   help="Esquinas interiores a lo alto. Por defecto: 6.")
    p.add_argument("--square-mm", type=float, default=23.0,
                   help="Lado de casilla en mm. Por defecto: 23, el mayor que "
                        "entra en A4 con el patrón por defecto.")
    p.add_argument("--paper", choices=sorted(PAPELES), default="A4",
                   help="Tamaño de papel. Por defecto: A4.")
    p.add_argument("--landscape", action="store_true",
                   help="Forzar orientación horizontal. Por defecto se elige "
                        "la que haga caber el tablero.")
    p.add_argument("--portrait", action="store_true",
                   help="Forzar orientación vertical.")
    p.add_argument("-o", "--out", default="results/tablero.pdf",
                   help="Archivo de salida (.pdf o .png).")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    casillas_x = args.cols + 1
    casillas_y = args.rows + 1
    ancho_tablero = casillas_x * args.square_mm
    alto_tablero = casillas_y * args.square_mm

    base_w, base_h = PAPELES[args.paper]

    def util(w: float, h: float) -> tuple[float, float]:
        return w - 2 * MARGEN_MM, h - 2 * MARGEN_MM - ALTO_PIE_MM

    def cabe(w: float, h: float) -> bool:
        uw, uh = util(w, h)
        return ancho_tablero <= uw and alto_tablero <= uh

    # Orientación: la forzada, o la que haga caber el tablero.
    if args.landscape and args.portrait:
        print("ERROR: --landscape y --portrait son incompatibles.", file=sys.stderr)
        return 1
    if args.landscape:
        papel_w, papel_h = base_h, base_w
    elif args.portrait:
        papel_w, papel_h = base_w, base_h
    elif cabe(base_w, base_h):
        papel_w, papel_h = base_w, base_h
    else:
        papel_w, papel_h = base_h, base_w  # se intenta girado

    horizontal = papel_w > papel_h
    disponible_w, disponible_h = util(papel_w, papel_h)

    if not cabe(papel_w, papel_h):
        max_v = min(util(base_w, base_h)[0] / casillas_x,
                    util(base_w, base_h)[1] / casillas_y)
        max_h = min(util(base_h, base_w)[0] / casillas_x,
                    util(base_h, base_w)[1] / casillas_y)
        print(
            f"ERROR: el tablero mide {ancho_tablero:.0f}x{alto_tablero:.0f} mm y no "
            f"cabe en {args.paper} en ninguna orientación "
            f"({disponible_w:.0f}x{disponible_h:.0f} mm útiles).\n"
            f"Opciones: --square-mm {max(max_v, max_h):.1f} o menos, "
            f"un patrón con menos casillas, o --paper A3.",
            file=sys.stderr,
        )
        return 1

    fig = plt.figure(
        figsize=(papel_w / MM_POR_PULGADA, papel_h / MM_POR_PULGADA), dpi=300
    )
    # Ejes en milímetros reales sobre la hoja: 1 unidad = 1 mm.
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, papel_w)
    ax.set_ylim(0, papel_h)
    ax.set_aspect("equal")
    ax.axis("off")

    # Tablero centrado horizontalmente, apoyado sobre el pie.
    x0 = (papel_w - ancho_tablero) / 2.0
    y0 = papel_h - MARGEN_MM - alto_tablero

    for fila in range(casillas_y):
        for col in range(casillas_x):
            if (fila + col) % 2 == 0:
                continue  # casilla blanca: el papel ya lo es
            ax.add_patch(
                Rectangle(
                    (x0 + col * args.square_mm,
                     y0 + fila * args.square_mm),
                    args.square_mm,
                    args.square_mm,
                    facecolor="black",
                    edgecolor="none",
                )
            )

    # --- Regla de verificación de escala ---
    ry = MARGEN_MM + 12.0
    rx = (papel_w - REGLA_MM) / 2.0
    ax.plot([rx, rx + REGLA_MM], [ry, ry], color="black", linewidth=1.0)
    for i in range(11):
        x = rx + i * 10.0
        alto_marca = 4.0 if i % 5 == 0 else 2.5
        ax.plot([x, x], [ry, ry + alto_marca], color="black", linewidth=1.0)
    ax.text(
        papel_w / 2.0, ry + 6.0,
        f"VERIFICAR ESCALA: esta regla debe medir exactamente {REGLA_MM:.0f} mm",
        ha="center", va="bottom", fontsize=7, family="DejaVu Sans",
    )
    ax.text(
        papel_w / 2.0, ry - 4.5,
        "Si no mide 100 mm, la impresión está escalada: reimprimir al 100 % "
        "(sin «ajustar a la página»).",
        ha="center", va="top", fontsize=6, family="DejaVu Sans",
    )

    # --- Cotas del tablero ---
    ax.text(
        papel_w / 2.0, ry - 10.0,
        f"{args.cols}x{args.rows} esquinas interiores  ·  "
        f"{casillas_x}x{casillas_y} casillas  ·  "
        f"casilla {args.square_mm:.1f} mm  ·  "
        f"tablero {ancho_tablero:.0f}x{alto_tablero:.0f} mm",
        ha="center", va="top", fontsize=7, family="DejaVu Sans",
    )
    ax.text(
        papel_w / 2.0, ry - 15.5,
        f"python apps/calibrate_intrinsics.py --camera cam1 "
        f"--cols {args.cols} --rows {args.rows} --square-mm {args.square_mm:g}",
        ha="center", va="top", fontsize=6, family="DejaVu Sans", color="0.35",
    )

    salida = Path(args.out)
    salida.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(salida, format=salida.suffix.lstrip(".") or "pdf")
    plt.close(fig)

    print(f"Generado: {salida}")
    print(f"  Papel:    {args.paper} {'horizontal' if horizontal else 'vertical'} "
          f"({papel_w:.0f}x{papel_h:.0f} mm)")
    print(f"  Patrón:   {args.cols}x{args.rows} esquinas interiores "
          f"({casillas_x}x{casillas_y} casillas)")
    print(f"  Casilla:  {args.square_mm:.1f} mm")
    print(f"  Tablero:  {ancho_tablero:.0f}x{alto_tablero:.0f} mm")
    print()
    print("Al imprimir: escala 100 %, SIN «ajustar a la página».")
    print("Después: medir la regla del pie. Si no da 100 mm, reimprimir.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
