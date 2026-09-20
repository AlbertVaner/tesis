"""URL RTSP de la camara IP a partir del entorno, para no escribir la clave.

Por que hace falta
------------------
Las URLs RTSP llevan usuario y clave en claro. Escritas en la linea de
comandos quedan en el historial de PowerShell, en capturas de pantalla y en
cualquier registro que copie el comando. Ademas la IP de la camara cambia por
DHCP, y habia que corregirla en cada comando.

Los lanzadores aceptan `--rtsp env` y la URL se arma aqui con::

    CAM_HOST        IP o nombre de la camara              (obligatoria)
    CAM_PASSWORD    clave de la cuenta del dispositivo    (obligatoria)
    CAM_USER        usuario                               (por defecto: admin)
    CAM_SUBTYPE     0 stream principal, 1 sub-stream      (por defecto: 1)
    CAM_RTSP_PORT   puerto RTSP                           (por defecto: 554)
    CAM_FRENTE_PAN  pan de "mirar al frente", en grados   (por defecto: 180)
    CAM_FRENTE_TILT tilt de "mirar al frente", en grados  (por defecto: 0)

Se leen del entorno del proceso y, si no estan, del archivo `.env` de la raiz
del repositorio, que **no se versiona** (`.env.example` documenta las claves).
El entorno real manda sobre el archivo. `CAM_USER` y `CAM_PASSWORD` son los
mismos nombres que ya lee `external/mapeo3d` como credenciales globales.

Una URL `rtsp://...` literal sigue funcionando igual que antes.

Solo biblioteca estandar, sin `cv2`: tambien lo usan `medir_ptz.py` y
`configurar_camara.py`, que no abren video.
"""

from __future__ import annotations

import argparse
import os
import urllib.parse
from pathlib import Path

#: Valor de `--rtsp` que pide armar la URL desde el entorno.
DESDE_ENTORNO = "env"

ARCHIVO_ENV = Path(__file__).resolve().parents[2] / ".env"


def leer_env(ruta: Path) -> dict[str, str]:
    """`CLAVE=valor` por linea. Ignora vacias y comentarios; quita comillas."""
    datos: dict[str, str] = {}
    if not ruta.is_file():
        return datos
    for linea in ruta.read_text(encoding="utf-8-sig").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, _, valor = linea.partition("=")
        valor = valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
            valor = valor[1:-1]
        datos[clave.strip()] = valor
    return datos


def url_desde_entorno(entorno: dict[str, str] | None = None,
                      archivo: Path | None = None) -> str:
    """Arma la URL RTSP. `ValueError` si falta algo, sin mostrar ningun valor."""
    valores = leer_env(ARCHIVO_ENV if archivo is None else archivo)
    valores.update({k: v for k, v in (os.environ if entorno is None else entorno).items() if v})

    faltan = [c for c in ("CAM_HOST", "CAM_PASSWORD") if not valores.get(c)]
    if faltan:
        raise ValueError(
            f"faltan {', '.join(faltan)}. Definirlas en el entorno o en "
            f"{ARCHIVO_ENV.name} en la raiz del repositorio (ver .env.example)."
        )
    usuario = urllib.parse.quote(valores.get("CAM_USER") or "admin", safe="")
    clave = urllib.parse.quote(valores["CAM_PASSWORD"], safe="")
    puerto = valores.get("CAM_RTSP_PORT") or "554"
    subtype = valores.get("CAM_SUBTYPE") or "1"
    return (f"rtsp://{usuario}:{clave}@{valores['CAM_HOST']}:{puerto}"
            f"/cam/realmonitor?channel=1&subtype={subtype}")


def resolver_rtsp(valor: str) -> str:
    """Para `type=` de argparse: `env` se resuelve, una URL se deja como esta."""
    if valor.strip().lower() != DESDE_ENTORNO:
        return valor
    try:
        return url_desde_entorno()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


AYUDA_RTSP = ("URL RTSP de la camara IP, o `env` para armarla con CAM_HOST, "
              "CAM_USER y CAM_PASSWORD del entorno o del .env de la raiz.")


# ------------------------------------------------------------------ frente
#
# Con `--frente`, la camara va a una posicion conocida antes de buscar a nadie.
# Desde la tarde del 2026-09-18 **no es el comportamiento por defecto**: sin
# `--frente` la camara empieza donde este, que es lo que el operador pidio.
#
# En la IP4M-1041B del laboratorio el frente es **pan 180**, no pan 0: montada
# de lado, el pan gira alrededor de un eje horizontal, asi que pan 0 es la
# misma linea de vision pero hacia atras y con la imagen boca abajo
# (comprobado el 2026-09-18 con una captura en pan 0).

FRENTE_POR_DEFECTO = (180.0, 0.0)


def frente_desde_entorno(entorno: dict[str, str] | None = None,
                         archivo: Path | None = None) -> tuple[float, float]:
    """`(pan, tilt)` de mirar al frente, del entorno o del `.env`."""
    valores = leer_env(ARCHIVO_ENV if archivo is None else archivo)
    valores.update({k: v for k, v in (os.environ if entorno is None else entorno).items() if v})
    frente = []
    for clave, defecto in zip(("CAM_FRENTE_PAN", "CAM_FRENTE_TILT"), FRENTE_POR_DEFECTO):
        try:
            frente.append(float(valores.get(clave) or defecto))
        except ValueError:
            raise ValueError(f"{clave} tiene que ser un numero de grados.") from None
    return frente[0], frente[1]


def agregar_frente(parser: argparse.ArgumentParser) -> None:
    """Anade `--frente PAN TILT` y `--sin-frente` a un lanzador con PTZ."""
    parser.add_argument("--frente", type=float, nargs="*", metavar="GRADOS",
                        help="Antes de buscar a la persona, llevar la camara a una posicion: "
                             "`--frente PAN TILT`, o `--frente` a secas para la guardada en "
                             "CAM_FRENTE_PAN y CAM_FRENTE_TILT. Sin esta opcion la camara "
                             "no se mueve al arrancar.")


def frente_de(args) -> tuple[float, float] | None:
    """El frente pedido con `--frente`, o `None` si no se pidio (no mover)."""
    if args.frente is None:
        return None
    if len(args.frente) == 2:
        return float(args.frente[0]), float(args.frente[1])
    if not args.frente:
        return frente_desde_entorno()
    raise SystemExit("--frente va solo o con dos numeros: PAN TILT.")


def guardar_frente(pan: float, tilt: float, archivo: Path | None = None) -> Path:
    """Escribe `CAM_FRENTE_PAN` y `CAM_FRENTE_TILT` en el `.env`, sin tocar lo demas.

    El frente se define **a ojo**: se apunta la camara adonde se quiere y se
    guarda la posicion que ella reporta. Los grados por si solos no dicen
    adonde mira: dependen de como este montada.
    """
    ruta = ARCHIVO_ENV if archivo is None else archivo
    nuevos = {"CAM_FRENTE_PAN": f"{pan:.1f}", "CAM_FRENTE_TILT": f"{tilt:.1f}"}
    lineas = ruta.read_text(encoding="utf-8-sig").splitlines() if ruta.is_file() else []
    salida = []
    for linea in lineas:
        clave = linea.partition("=")[0].strip()
        if clave in nuevos:
            salida.append(f"{clave}={nuevos.pop(clave)}")
        else:
            salida.append(linea)
    for clave, valor in nuevos.items():
        salida.append(f"{clave}={valor}")
    ruta.write_text("\n".join(salida) + "\n", encoding="utf-8")
    return ruta
