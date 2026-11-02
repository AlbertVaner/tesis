"""Grabar el stream principal (alta resolucion) de cada camara IP, sin decodificar.

El reconocimiento de gestos lee el **sub-stream** VGA (`CAM_SUBTYPE=1`) porque
decodificar seis streams de 4 MP le quitaria a MediaPipe la CPU que necesita y
subiria la latencia. Para un video de presentacion, en cambio, se quiere la
imagen buena. Las Amcrest sirven los dos streams a la vez, asi que aqui se pide
el **principal** (`subtype=0`) y ffmpeg lo copia al disco tal como llega
(`-c copy`): no decodifica ni recodifica, cuesta casi nada de CPU y el archivo
tiene la resolucion y el codec de la camara.

No dibuja el esqueleto: eso solo existe en la imagen VGA que procesa el
reconocedor (`--grabar-camaras` de `control_camara_dron1.py`).

Necesita `ffmpeg` en el PATH (o el paquete `imageio-ffmpeg`). En Windows:
`winget install Gyan.FFmpeg`, y abrir una terminal nueva.

Uso, desde la raiz del repositorio:

    python .\\external\\gesture_detection\\grabar_camaras_hd.py
    python .\\external\\gesture_detection\\grabar_camaras_hd.py --camaras cam1,cam3

Enter (o Ctrl+C) para terminar: cada ffmpeg recibe `q` y cierra su archivo.
Los archivos van a `results/captures/camaras_hd/<dia>/<HHMMSS>/camN_hd.mkv`.

Por que MKV y con la hora del reloj
-----------------------------------
Cada paquete se marca con la **hora de pared a la que llego**
(`-use_wallclock_as_timestamps 1`) y se conserva tal cual (`-copyts`): el
cuadro de las 17:03:21.480 lleva ese instante como marca de tiempo. Es lo que
permite a `renderizar_sesion_hd.py` poner sobre cada cuadro el esqueleto y el
gesto que el sistema tenia en ese mismo instante (`visualization/registro_render.py`
guarda las poses con el mismo reloj). MP4 no admite marcas que empiezan en
1.8e9 s; Matroska si.

**El MKV no es para verlo.** Su primer keyframe llega con marca 0 y los demas
con la hora de pared, y un reproductor que ve ese salto de 1.8e9 s reproduce
a saltos o acelerado. Al cerrar, cada camara se remuxa ademas a `camN_hd.mp4`
(copia, sin recodificar, empezando en cero): ese es el que se abre y se edita.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = MODULE_DIR.parents[1]
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from camara_env import camaras_desde_entorno  # noqa: E402
from video_source import enmascarar  # noqa: E402

#: Cuanto se espera a que un ffmpeg cierre su archivo tras pedirselo.
CIERRE_S = 10.0

_SUBTYPE = re.compile(r"subtype=\d+")


def stream_principal(url: str) -> str:
    """La misma camara con `subtype=0`: el stream de alta resolucion."""
    if _SUBTYPE.search(url):
        return _SUBTYPE.sub("subtype=0", url)
    separador = "&" if "?" in url else "?"
    return f"{url}{separador}subtype=0"


def buscar_ffmpeg() -> str | None:
    """Ruta de ffmpeg: el del PATH o el que trae `imageio-ffmpeg`."""
    ruta = shutil.which("ffmpeg")
    if ruta:
        return ruta
    # Recien instalado con winget, una terminal abierta antes no lo tiene en el PATH.
    winget = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet"
    for candidato in [winget / "Links" / "ffmpeg.exe",
                      *sorted(winget.glob("Packages/Gyan.FFmpeg*/*/bin/ffmpeg.exe"))]:
        if candidato.is_file():
            return str(candidato)
    try:
        import imageio_ffmpeg
    except ImportError:
        return None
    return imageio_ffmpeg.get_ffmpeg_exe()


def comando_ffmpeg(ffmpeg: str, url: str, salida: Path) -> list[str]:
    """Copia el video de `url` a `salida` sin recodificar, por TCP y sin audio,
    con la hora de llegada de cada paquete como marca de tiempo."""
    return [ffmpeg, "-hide_banner", "-nostats", "-loglevel", "error",
            "-rtsp_transport", "tcp", "-use_wallclock_as_timestamps", "1", "-i", url,
            "-map", "0:v:0", "-c", "copy", "-an", "-copyts",
            "-y", str(salida)]


class GrabadorRTSP:
    """Un proceso ffmpeg por camara. `iniciar()` al empezar y `cerrar()` al terminar."""

    def __init__(self, camaras: list[tuple[str, str]], carpeta: Path,
                 ffmpeg: str | None = None) -> None:
        self.ffmpeg = ffmpeg or buscar_ffmpeg()
        if self.ffmpeg is None:
            raise RuntimeError("no se encuentra ffmpeg: instalarlo con "
                               "`winget install Gyan.FFmpeg` y abrir una terminal nueva.")
        self.carpeta = Path(carpeta)
        self.camaras = [(n, stream_principal(u)) for n, u in camaras]
        self.procesos: dict[str, subprocess.Popen] = {}
        #: `camN_hd.mp4` reproducibles, tras `cerrar()`.
        self.mp4: list[Path] = []

    def ruta(self, nombre: str) -> Path:
        return self.carpeta / f"{nombre}_hd.mkv"

    def iniciar(self) -> "GrabadorRTSP":
        self.carpeta.mkdir(parents=True, exist_ok=True)
        for nombre, url in self.camaras:
            self.procesos[nombre] = subprocess.Popen(
                comando_ffmpeg(self.ffmpeg, url, self.ruta(nombre)),
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        return self

    def caidas(self) -> list[str]:
        """Camaras cuyo ffmpeg ya termino (no conecto o se corto)."""
        return [n for n, p in self.procesos.items() if p.poll() is not None]

    def cerrar(self) -> dict[str, str]:
        """Pide a cada ffmpeg que termine. `{camara: problema}`; vacio si todo fue bien."""
        problemas: dict[str, str] = {}
        for proceso in self.procesos.values():
            if proceso.poll() is None:
                try:
                    proceso.stdin.write(b"q")
                    proceso.stdin.flush()
                except OSError:
                    pass
        for nombre, proceso in self.procesos.items():
            try:
                _, error = proceso.communicate(timeout=CIERRE_S)
            except subprocess.TimeoutExpired:
                proceso.kill()
                _, error = proceso.communicate()
                problemas[nombre] = "no cerro a tiempo: el archivo puede estar incompleto"
                continue
            texto = enmascarar(error.decode("utf-8", "replace")).strip()
            if proceso.returncode not in (0, 255) or not self.ruta(nombre).is_file():
                problemas[nombre] = texto.splitlines()[-1] if texto else f"codigo {proceso.returncode}"
        self.procesos.clear()
        self.mp4 = []
        for ruta in self.rutas:
            try:
                self.mp4.append(remux(self.ffmpeg, ruta))
            except subprocess.CalledProcessError:
                problemas[ruta.stem] = "no se pudo pasar a MP4 (el MKV sigue valiendo para el render)"
        return problemas

    @property
    def rutas(self) -> list[Path]:
        return [self.ruta(n) for n, _ in self.camaras if self.ruta(n).is_file()]


def remux(ffmpeg: str, mkv: Path) -> Path:
    """`camN_hd.mp4` sin recodificar y empezando en cero, para cualquier reproductor."""
    mp4 = Path(mkv).with_suffix(".mp4")
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(mkv),
                    "-c", "copy", "-movflags", "+faststart", str(mp4)], check=True)
    return mp4


def carpeta_de_sesion(controlador: str = "camaras_hd", sesion: str | None = None) -> Path:
    sesion = sesion or datetime.now().strftime("%H%M%S")
    return (PROJECT_DIR / "results" / "captures" / controlador
            / datetime.now().strftime("%Y-%m-%d") / sesion)


def informar(grabador: GrabadorRTSP, problemas: dict[str, str]) -> None:
    for ruta in grabador.mp4:
        print(f"Video HD: {ruta}")
    if grabador.rutas:
        print(f"  (los .mkv de {grabador.carpeta} son para renderizar_sesion_hd.py, no para verlos)")
    for nombre, problema in problemas.items():
        print(f"  {nombre}: {problema}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Graba el stream principal de cada camara IP del .env, sin recodificar.")
    parser.add_argument("--camaras", help="lista separada por comas (cam1,cam3); por defecto todas")
    args = parser.parse_args()

    try:
        camaras = camaras_desde_entorno()
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    if args.camaras:
        pedidas = {c.strip().lower() for c in args.camaras.split(",")}
        camaras = [(n, u) for n, u in camaras if n in pedidas]
        if not camaras:
            print("ERROR: ninguna de esas camaras esta en el .env.", file=sys.stderr)
            return 1

    try:
        grabador = GrabadorRTSP(camaras, carpeta_de_sesion())
    except RuntimeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    for nombre, url in grabador.camaras:
        print(f"  {nombre}: {enmascarar(url)}")
    grabador.iniciar()
    print(f"Grabando en {grabador.carpeta}. Enter para terminar.")
    try:
        input()
    except (KeyboardInterrupt, EOFError):
        pass
    informar(grabador, grabador.cerrar())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
