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

`--rtsp cam2`, `--rtsp cam3`... eligen otra camara del `.env` (`CAM2_HOST`,
`CAM3_HOST`...; lo que falte sale de `CAM_*`), con los mismos nombres que
usan `--multicamara` y el panel web. `cam1` es lo mismo que `env`.

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
                      archivo: Path | None = None, camara: str = "cam1") -> str:
    """Arma la URL RTSP de `camara` (`cam1` = `CAM_*`, `camN` = `CAMN_*`).

    `ValueError` si falta algo, sin mostrar ningun valor.
    """
    valores = leer_env(ARCHIVO_ENV if archivo is None else archivo)
    valores.update({k: v for k, v in (os.environ if entorno is None else entorno).items() if v})

    return _armar_url(valores, _prefijo(camara))


def _prefijo(camara: str) -> str:
    """`cam1` -> `CAM`, `cam3` -> `CAM3`. `ValueError` si no es `camN` con N de 1 a 6."""
    numero = camara.strip().lower().removeprefix("cam")
    if not numero.isdigit() or not 1 <= int(numero) <= MAX_CAMARAS:
        raise ValueError(f"camara desconocida: {camara!r} (cam1 a cam{MAX_CAMARAS}).")
    return "CAM" if int(numero) == 1 else f"CAM{int(numero)}"


def es_nombre_de_camara(valor: str) -> bool:
    """`True` para `cam1`...`cam6`, que `--rtsp` acepta igual que `env`."""
    try:
        _prefijo(valor)
    except ValueError:
        return False
    return valor.strip().lower().startswith("cam")


def _armar_url(valores: dict[str, str], prefijo: str) -> str:
    """URL de la camara `prefijo` (`CAM`, `CAM2`...). Lo que le falte lo toma de `CAM_*`."""
    def valor(clave: str) -> str:
        return valores.get(f"{prefijo}_{clave}") or valores.get(f"CAM_{clave}") or ""

    faltan = [] if valores.get(f"{prefijo}_HOST") else [f"{prefijo}_HOST"]
    if not valor("PASSWORD"):
        faltan.append("CAM_PASSWORD")
    if faltan:
        raise ValueError(
            f"faltan {', '.join(faltan)}. Definirlas en el entorno o en "
            f"{ARCHIVO_ENV.name} en la raiz del repositorio (ver .env.example)."
        )
    usuario = urllib.parse.quote(valor("USER") or "admin", safe="")
    clave = urllib.parse.quote(valor("PASSWORD"), safe="")
    puerto = valor("RTSP_PORT") or "554"
    subtype = valor("SUBTYPE") or "1"
    return (f"rtsp://{usuario}:{clave}@{valores[f'{prefijo}_HOST']}:{puerto}"
            f"/cam/realmonitor?channel=1&subtype={subtype}")


#: Camaras que se buscan en el entorno: `CAM_HOST` es la 1, `CAM2_HOST` la 2...
MAX_CAMARAS = 6


def camaras_desde_entorno(entorno: dict[str, str] | None = None,
                          archivo: Path | None = None) -> list[tuple[str, str]]:
    """`[(nombre, url)]` de cada camara con host definido, en orden.

    `cam1` es `CAM_HOST`; `camN` es `CAMN_HOST`. Usuario, clave, puerto y
    sub-stream de `camN` salen de `CAMN_*` y, si no estan, de `CAM_*`.
    """
    valores = leer_env(ARCHIVO_ENV if archivo is None else archivo)
    valores.update({k: v for k, v in (os.environ if entorno is None else entorno).items() if v})
    camaras = []
    for n in range(1, MAX_CAMARAS + 1):
        prefijo = "CAM" if n == 1 else f"CAM{n}"
        if valores.get(f"{prefijo}_HOST"):
            camaras.append((f"cam{n}", _armar_url(valores, prefijo)))
    if not camaras:
        raise ValueError(
            f"no hay ninguna camara: definir CAM_HOST, CAM2_HOST... en el entorno o en "
            f"{ARCHIVO_ENV.name} en la raiz del repositorio (ver .env.example)."
        )
    return camaras


def resolver_rtsp(valor: str) -> str:
    """Para `type=` de argparse: `env` y `camN` se resuelven, una URL se deja como esta."""
    nombre = valor.strip().lower()
    if nombre == DESDE_ENTORNO:
        nombre = "cam1"
    elif not es_nombre_de_camara(nombre):
        return valor
    try:
        return url_desde_entorno(camara=nombre)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


AYUDA_RTSP = ("URL RTSP de la camara IP; `env` o `cam1` para armarla con CAM_HOST, "
              "CAM_USER y CAM_PASSWORD del entorno o del .env de la raiz; `cam2`, "
              "`cam3`... con CAM2_HOST, CAM3_HOST...")


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
