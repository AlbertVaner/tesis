"""Deja el encoder de la camara Amcrest listo para vision en tiempo real.

Por que hace falta
------------------
Con el lector de `video_source.py` (TCP, ultimo frame, un hilo de decodificacion)
la latencia que queda la pone el **encoder de la camara**, y eso no se arregla
desde el PC. En la IP4M-1041B el stream principal a 720p lleva 300-500 ms de
retraso interno; el sub-stream a 640x480 sin audio lo baja a la mitad, y para
MediaPipe la resolucion no importa: reescala a ~256 px.

Lo que ajusta, solo en el **sub-stream** (`subtype=1`):

- 640x480 a 30 fps, H.264, CBR, 1024 kbps, un I-frame por segundo (GOP 30).
  La IP4M-1041B **no admite 704x480** en el sub-stream (HTTP 400).
- Audio desactivado, tambien en el stream principal: FFmpeg intercala audio y
  video y espera al mas lento de los dos.

El stream principal (`subtype=0`) queda como estaba, salvo el audio.

Con `--rotar {0,90,180,270}` fija ademas la orientacion de la imagen segun el
montaje: 90 y 270 para una camara de lado (dejan los streams en vertical),
**180 para una camara boca abajo** (`Flip` + `Mirror`, imagen apaisada) y 0
para una derecha. El seguimiento PTZ lee la orientacion de la camara y adapta
los ejes y el sentido de los motores solo: ver `ptz/cliente.py`.

Uso, desde la raiz del repositorio::

    # Muestra la configuracion actual y lo que cambiaria. No toca nada.
    .\\.venv\\Scripts\\python.exe .\\external\\gesture_detection\\configurar_camara.py ^
        --rtsp "rtsp://usuario:clave@IP:554/cam/realmonitor?channel=1&subtype=1"

    # Aplica los cambios.
    .\\.venv\\Scripts\\python.exe .\\external\\gesture_detection\\configurar_camara.py ^
        --rtsp "rtsp://usuario:clave@IP:554/cam/realmonitor?channel=1&subtype=1" --aplicar

Despues, usar `subtype=1` en todas las URLs `--rtsp`. La latencia real se mide
con `external/mapeo3d/apps/diagnose_camera.py --url ... --sin-pose` apuntando
la camara al monitor.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from camara_env import AYUDA_RTSP, resolver_rtsp  # noqa: E402
from ptz import CamaraPTZ, ErrorPTZ  # noqa: E402
from ptz.cliente import CLAVE_FLIP, CLAVE_MIRROR, CLAVE_ROTACION  # noqa: E402

#: Grados en sentido horario -> `(Rotate90, Flip, Mirror)`. 180 no es un valor
#: de `Rotate90`: son los dos volteos del sensor a la vez.
ROTACIONES = {0: (0, False, False), 90: (1, False, False),
              180: (0, True, True), 270: (2, False, False)}

PRINCIPAL = "Encode[0].MainFormat[0]"
SUB = "Encode[0].ExtraFormat[0]"

CAMPOS_VIDEO = ("resolution", "FPS", "GOP", "Compression", "BitRateControl", "BitRate")


@dataclass(frozen=True)
class Ajustes:
    """Encoder del sub-stream. Los valores por defecto son los validados."""

    resolucion: str = "640x480"
    fps: int = 30
    gop: int = 30
    bitrate_kbps: int = 1024
    codec: str = "H.264"
    #: Grados de rotacion de imagen (0, 90, 270) o `None` para no tocarla.
    rotar: int | None = None

    def deseado(self) -> dict[str, str | int | bool]:
        rotacion = {}
        if self.rotar is not None:
            rotate90, flip, mirror = ROTACIONES[self.rotar]
            rotacion = {CLAVE_ROTACION: rotate90, CLAVE_FLIP: flip, CLAVE_MIRROR: mirror}
        return rotacion | {
            f"{SUB}.VideoEnable": True,
            f"{SUB}.Video.resolution": self.resolucion,
            f"{SUB}.Video.FPS": self.fps,
            f"{SUB}.Video.GOP": self.gop,
            f"{SUB}.Video.Compression": self.codec,
            f"{SUB}.Video.BitRateControl": "CBR",
            f"{SUB}.Video.BitRate": self.bitrate_kbps,
            f"{SUB}.AudioEnable": False,
            f"{PRINCIPAL}.AudioEnable": False,
        }


def _como_texto(valor: str | int | bool) -> str:
    if isinstance(valor, bool):
        return "true" if valor else "false"
    return str(valor)


def plan_cambios(actual: dict[str, str], ajustes: Ajustes) -> dict[str, str | int | bool]:
    """Solo las claves cuyo valor en la camara difiere del deseado.

    Mandar la tabla entera reinicia el encoder aunque no cambie nada, y con
    ello corta el stream a quien lo este leyendo. Comparar como texto es
    suficiente: la camara devuelve todo como texto.
    """
    return {
        clave: valor
        for clave, valor in ajustes.deseado().items()
        if actual.get(clave, "").lower() != _como_texto(valor).lower()
    }


def resumen_stream(actual: dict[str, str], prefijo: str) -> str:
    """Una linea legible con lo que importa de un stream."""
    v = {campo: actual.get(f"{prefijo}.Video.{campo}", "?") for campo in CAMPOS_VIDEO}
    audio = actual.get(f"{prefijo}.AudioEnable", "?")
    return (f"{v['resolution']} {v['FPS']} fps  {v['Compression']}  "
            f"{v['BitRateControl']} {v['BitRate']} kbps  GOP {v['GOP']}  audio={audio}")


def leer_todo(camara: CamaraPTZ) -> dict[str, str]:
    """Encoder y opciones de imagen en un solo diccionario; las claves no chocan."""
    return camara.leer_configuracion("Encode") | camara.leer_configuracion("VideoInOptions")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--rtsp", type=resolver_rtsp, help=AYUDA_RTSP)
    p.add_argument("--host")
    p.add_argument("--user", default="admin")
    p.add_argument("--password")
    p.add_argument("--resolucion", default=Ajustes.resolucion)
    p.add_argument("--fps", type=int, default=Ajustes.fps)
    p.add_argument("--gop", type=int, default=Ajustes.gop)
    p.add_argument("--bitrate", type=int, default=Ajustes.bitrate_kbps, help="kbps")
    p.add_argument("--rotar", type=int, choices=sorted(ROTACIONES), default=None,
                   help="Orientacion de la imagen en grados horarios segun el montaje: "
                        "90 o 270 de lado, 180 boca abajo, 0 derecha. Sin esto no se toca.")
    p.add_argument("--aplicar", action="store_true",
                   help="Escribe la configuracion. Sin esto solo la muestra.")
    args = p.parse_args()

    if args.rtsp:
        camara = CamaraPTZ.desde_rtsp(args.rtsp)
    elif args.host:
        camara = CamaraPTZ(args.host, args.user, args.password or "")
    else:
        p.error("hace falta --rtsp o --host")

    ajustes = Ajustes(args.resolucion, args.fps, args.gop, args.bitrate, rotar=args.rotar)
    print(f"Camara: {camara.host}")
    try:
        modelo, serie = camara.identidad()
        print(f"  {modelo}  serie {serie}")
        actual = leer_todo(camara)
    except ErrorPTZ as exc:
        print(f"  no responde: {exc}")
        return 1

    print(f"  orientacion de imagen: Rotate90={actual.get(CLAVE_ROTACION, '?')}"
          f"  Flip={actual.get(CLAVE_FLIP, '?')}  Mirror={actual.get(CLAVE_MIRROR, '?')}")
    print(f"  principal (subtype=0): {resumen_stream(actual, PRINCIPAL)}")
    print(f"  sub       (subtype=1): {resumen_stream(actual, SUB)}")

    cambios = plan_cambios(actual, ajustes)
    if not cambios:
        print("Ya esta como se quiere. Nada que cambiar.")
        return 0

    print("Cambios:")
    for clave, valor in cambios.items():
        print(f"  {clave}: {actual.get(clave, '(sin valor)')} -> {_como_texto(valor)}")
    if not args.aplicar:
        print("No se ha tocado nada. Repetir con --aplicar para escribirlos.")
        return 0

    # Una clave por peticion. Medido el 2026-09-18: con un solo valor que la
    # camara no admite (704x480) contesto OK al lote entero y **no aplico
    # ninguna** de las claves de `Encode`, ni las validas.
    for clave, valor in cambios.items():
        try:
            camara.escribir_configuracion({clave: valor})
        except ErrorPTZ:
            print(f"  la camara rechaza {clave} = {_como_texto(valor)}")
    despues = leer_todo(camara)
    pendientes = plan_cambios(despues, ajustes)
    print(f"  sub ahora: {resumen_stream(despues, SUB)}")
    if pendientes:
        print("  sin aplicar: " + ", ".join(pendientes))
        print("  Para ver que valores admite: web de la camara, "
              "Setup > Camera > Video > Sub Stream.")
        return 1
    print("Listo. Usar subtype=1 en las URLs --rtsp; el encoder se reinicia y "
          "un stream abierto puede reconectar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
