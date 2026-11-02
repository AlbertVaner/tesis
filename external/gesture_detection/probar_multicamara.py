"""Varias camaras, un operador: manda la que mejor le ve la cara. Sin dron.

Prototipo del montaje de seis camaras del Robotat. Cada camara corre en su
propio hilo con su detector de pose y su reconocedor del vocabulario 3D, asi
que todas estan siempre calientes y el cambio de camara es instantaneo. Un
`SelectorCamara` elige la **activa** con el puntaje de rostro de cada una
(`multicamara/rostro.py`), y solo los gestos confirmados de la activa se
emiten como comandos. La activa es tambien la que se ve en grande; las demas
aparecen en miniatura con su puntaje. Con camaras PTZ, cada una ademas
mueve su pan/tilt para seguir a la persona (`--sin-ptz` lo apaga, `--dry-run`
solo imprime lo que mandaria).

No importa controladores ni sabe que existe un Crazyflie: los comandos se
imprimen y quedan en el CSV. Conectarlos a un dron es trabajo del controlador
que consuma `GestureEvent` (ver `contracts.py`).

Uso, desde la raiz del repositorio:

    python .\\external\\gesture_detection\\probar_multicamara.py
    python .\\external\\gesture_detection\\probar_multicamara.py --fuente 0 --fuente video.mp4

Sin `--fuente` usa todas las camaras del `.env`: `CAM_HOST` es cam1,
`CAM2_HOST` cam2, y asi hasta `CAM6_HOST` (ver `.env.example`).

Teclas: `q` salir, `r` reiniciar los reconocedores, `1`-`6` fijar esa camara,
`0` volver a la eleccion automatica, `espacio` pausar el seguimiento PTZ.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2

MODULE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = MODULE_DIR.parents[1]
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from camara_env import camaras_desde_entorno  # noqa: E402
from contracts import GESTOS_DE_ESTADO, Gesture, GestureEvent  # noqa: E402
from multicamara.sistema import (  # noqa: E402
    AMBAR, BLANCO, GRIS, VERDE, SistemaMulticamara, _texto,
)
from video_source import enmascarar  # noqa: E402
from visualization.ventana import mostrar  # noqa: E402

VENTANA = "Multicamara - prueba sin dron"
CABECERA_ALTO = 200

# ----------------------------------------------------------------- comandos


class Comandos:
    """Convierte los eventos de la camara activa en comandos, una vez cada uno.

    Igual que `probar_gestos_3d.py`: un gesto confirmado se emite al
    confirmarse y no se repite mientras se sostiene. Al cambiar de camara **no**
    se emite lo que la nueva ya tuviera confirmado: hace falta pasar por
    NO_GESTURE. Asi un DESPEGAR sostenido no se ejecuta dos veces por verse
    desde dos camaras.
    """

    def __init__(self) -> None:
        self.ultimo: Gesture | None = None
        self.camara: str | None = None
        self.historial: list[tuple[float, str, Gesture]] = []

    def actualizar(self, t: float, camara: str | None, evento: GestureEvent) -> Gesture | None:
        if camara != self.camara:
            self.camara = camara
            self.ultimo = evento.gesture if evento.confirmed else None
            return None
        emitido = None
        if evento.confirmed and evento.gesture is not self.ultimo:
            emitido = evento.gesture
            self.historial.append((t, camara, emitido))
        if evento.confirmed:
            self.ultimo = evento.gesture
        elif evento.gesture is Gesture.NO_GESTURE:
            self.ultimo = None
        return emitido


# ----------------------------------------------------------------- registro


class Registro:
    """Por instante: camara activa, puntaje de cada una, gesto y comando."""

    def __init__(self, nombres: list[str], activo: bool = True) -> None:
        self.ruta: Path | None = None
        self._archivo = None
        self._writer = None
        if not activo:
            return
        carpeta = (PROJECT_DIR / "results" / "data" / "gesture_detection"
                   / datetime.now().strftime("%Y-%m-%d"))
        carpeta.mkdir(parents=True, exist_ok=True)
        self.ruta = carpeta / f"multicamara_{datetime.now():%H%M%S}.csv"
        self._archivo = self.ruta.open("w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._archivo)
        self._writer.writerow(["t", "activa", "fija", "gesto", "confirmado", "comando"]
                              + [f"rostro_{n}" for n in nombres])

    def anotar(self, t, activa, fija, evento, comando, puntajes: list[str]) -> None:
        if self._writer is not None:
            self._writer.writerow([f"{t:.3f}", activa or "", int(fija), evento.gesture.value,
                                   int(evento.confirmed), comando.value if comando else ""]
                                  + puntajes)

    def cerrar(self) -> None:
        if self._archivo is not None:
            self._archivo.close()
            self._archivo = None


# -------------------------------------------------------------------- dibujo


def cabecera(sistema: SistemaMulticamara, comandos: Comandos):
    """Lo que va encima de las miniaturas: activa, gesto y ultimos comandos."""
    def dibujar(panel) -> None:
        _texto(panel, "MULTICAMARA - SIN DRON", (16, 30), GRIS, 0.44)
        fija = sistema.selector.fija
        modo = f"fija ({fija})" if fija else "automatica"
        _texto(panel, f"activa: {sistema.activa or '-'}   eleccion {modo}", (16, 58), BLANCO, 0.5)
        if not sistema.siguiendo:
            _texto(panel, "SEGUIMIENTO EN PAUSA", (16, 80), AMBAR, 0.42)
        evento = sistema.evento_activo()
        if evento.gesture is Gesture.NO_GESTURE:
            _texto(panel, "sin gesto", (16, 112), GRIS, 0.72, 2)
        else:
            _texto(panel, evento.gesture.value, (16, 112),
                   VERDE if evento.confirmed else AMBAR, 0.72, 2)
        if comandos.historial:
            _, cam, g = comandos.historial[-1]
            color = AMBAR if g in GESTOS_DE_ESTADO else BLANCO
            _texto(panel, f"ultimo comando: {g.value} ({cam})", (16, 142), color, 0.5)
            previos = "  ".join(x.value for _, _, x in comandos.historial[-5:-1][::-1])
            _texto(panel, previos[:48], (16, 164), GRIS, 0.4)
        _texto(panel, "q salir  r reiniciar  1-6 fijar  0 auto  espacio PTZ", (16, 190), GRIS, 0.4)
    return dibujar


# --------------------------------------------------------------------- bucle


def bucle(sistema: SistemaMulticamara, registro: Registro) -> Comandos:
    comandos = Comandos()
    t0 = time.monotonic()
    sistema.iniciar()
    cv2.namedWindow(VENTANA, cv2.WINDOW_NORMAL)
    try:
        while True:
            anterior = sistema.activa
            activa = sistema.actualizar()
            t = time.monotonic() - t0
            if activa != anterior:
                print(f"[{t:6.2f} s] camara activa: {activa}", flush=True)

            if activa is not None:
                evento = sistema.estados[activa].evento
                comando = comandos.actualizar(t, activa, evento)
                if comando is not None:
                    print(f"[{t:6.2f} s] COMANDO {comando.value} ({activa})", flush=True)
                registro.anotar(t, activa, sistema.selector.fija is not None, evento, comando,
                                [f"{sistema.estados[c.nombre].rostro.puntaje:.3f}"
                                 for c in sistema.camaras])

            mostrar(VENTANA, sistema.componer(cabecera(sistema, comandos), CABECERA_ALTO))

            tecla = cv2.waitKey(15) & 0xFF
            if tecla == ord("q"):
                break
            if tecla == ord("r"):
                sistema.reiniciar()
            if tecla == ord("0"):
                sistema.fijar(None)
            if tecla == ord(" "):
                sistema.alternar_seguimiento()
            if ord("1") <= tecla <= ord("9"):
                sistema.fijar(f"cam{tecla - ord('0')}")
            if cv2.getWindowProperty(VENTANA, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        sistema.cerrar()
        cv2.destroyAllWindows()
    return comandos


# ---------------------------------------------------------------------- main


def _fuente(valor: str):
    return int(valor) if valor.isdigit() else valor


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Varias camaras; manda la que mejor ve la cara del operador. Sin dron.")
    parser.add_argument("--fuente", action="append", type=_fuente, metavar="FUENTE",
                        help="webcam (indice), archivo o URL rtsp://. Repetible; "
                             "la primera es cam1. Sin esta opcion: las camaras del .env.")
    parser.add_argument("--sin-ptz", action="store_true",
                        help="no mover las camaras; solo mirar")
    parser.add_argument("--dry-run", action="store_true",
                        help="no mueve los motores: imprime lo que mandaria")
    parser.add_argument("--sin-csv", action="store_true")
    args = parser.parse_args()

    try:
        if args.fuente:
            fuentes = [(f"cam{i}", f) for i, f in enumerate(args.fuente, start=1)]
        else:
            fuentes = camaras_desde_entorno()
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print("Este programa no conecta ningun dron.")
    for nombre, fuente in fuentes:
        print(f"  {nombre}: {enmascarar(fuente)}")
    print()

    sistema = SistemaMulticamara(fuentes, ptz=not args.sin_ptz, dry_run=args.dry_run)
    registro = Registro([n for n, _ in fuentes], activo=not args.sin_csv)
    try:
        comandos = bucle(sistema, registro)
        print("\nComandos emitidos:")
        if not comandos.historial:
            print("  ninguno")
        for t, cam, g in comandos.historial:
            print(f"  {t:7.2f} s  {g.value:<10} {cam}")
        if registro.ruta is not None:
            print(f"\nRegistro: {registro.ruta}")
        return 0
    except KeyboardInterrupt:
        print("Interrupcion solicitada.")
        return 130
    finally:
        registro.cerrar()


if __name__ == "__main__":
    raise SystemExit(main())
