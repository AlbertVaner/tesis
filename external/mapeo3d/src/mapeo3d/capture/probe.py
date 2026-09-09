"""Sondeo RTSP de bajo nivel, para saber POR QUÉ no conecta una cámara.

`cv2.VideoCapture` devuelve `False` y ya está. No distingue «la IP no existe»
de «el puerto está cerrado», de «la contraseña está mal», de «la ruta RTSP de
ese modelo es otra» — y las cuatro se arreglan de forma distinta. Este módulo
habla RTSP directamente y devuelve el código de estado real.

Cómo se lee un sondeo
---------------------
| Síntoma | Qué significa |
|---|---|
| El puerto 554 no abre | IP equivocada, cámara apagada, u otra subred |
| Abre pero no responde a `OPTIONS` | Hay algo escuchando, pero no es RTSP |
| `401` sin credenciales, `200` con ellas | **Todo bien** |
| `401` también con credenciales | Usuario o contraseña incorrectos |
| `404` con credenciales correctas | La ruta de ese modelo es otra |

La distinción entre 401 y 404 es la que más tiempo ahorra: significa que el
problema está en la cuenta y no en el modelo, o al revés.

Este módulo sólo abre sockets TCP y envía peticiones de lectura. No emite
comandos PTZ ni cambia ninguna configuración de la cámara.
"""

from __future__ import annotations

import hashlib
import re
import socket
from dataclasses import dataclass, field

from .urls import RTSP_PATHS, mask_url

PUERTO_RTSP = 554
TIMEOUT_S = 2.0

_ESTADO = re.compile(r"^RTSP/1\.0 (\d{3}) ?(.*)$")
_CABECERA = re.compile(r"^([\w-]+):\s*(.*)$")
_PARAMETRO = re.compile(r'(\w+)="([^"]*)"')


def puerto_abierto(host: str, puerto: int = PUERTO_RTSP,
                   timeout: float = TIMEOUT_S) -> bool:
    """¿Hay algo escuchando? Es la primera pregunta y la más barata."""
    try:
        with socket.create_connection((host, puerto), timeout=timeout):
            return True
    except OSError:
        return False


def _digest(usuario: str, clave: str, metodo: str, uri: str,
            parametros: dict) -> str:
    """Respuesta Digest MD5 (RFC 2617), que es la que usan Amcrest y Dahua.

    Sin `qop`, que es el caso de las cámaras IP: la respuesta es
    `MD5(HA1:nonce:HA2)`.
    """
    def md5(s: str) -> str:
        return hashlib.md5(s.encode("utf-8")).hexdigest()

    realm = parametros.get("realm", "")
    nonce = parametros.get("nonce", "")
    ha1 = md5(f"{usuario}:{realm}:{clave}")
    ha2 = md5(f"{metodo}:{uri}")
    return md5(f"{ha1}:{nonce}:{ha2}")


def cabecera_autorizacion(usuario: str, clave: str, metodo: str, uri: str,
                          www_authenticate: str) -> str | None:
    """Construye el `Authorization` que corresponda al reto recibido."""
    reto = www_authenticate.strip()
    if reto.lower().startswith("digest"):
        p = dict(_PARAMETRO.findall(reto))
        resp = _digest(usuario, clave, metodo, uri, p)
        partes = [
            f'username="{usuario}"',
            f'realm="{p.get("realm", "")}"',
            f'nonce="{p.get("nonce", "")}"',
            f'uri="{uri}"',
            f'response="{resp}"',
        ]
        return "Digest " + ", ".join(partes)
    if reto.lower().startswith("basic"):
        import base64
        cred = base64.b64encode(f"{usuario}:{clave}".encode()).decode()
        return f"Basic {cred}"
    return None


def _parsear(respuesta: str) -> tuple[int, str, dict[str, str]]:
    lineas = respuesta.split("\r\n")
    m = _ESTADO.match(lineas[0]) if lineas else None
    if not m:
        return 0, "respuesta no es RTSP", {}
    cabeceras: dict[str, str] = {}
    for ln in lineas[1:]:
        if not ln:
            break
        c = _CABECERA.match(ln)
        if c:
            cabeceras[c.group(1).lower()] = c.group(2)
    return int(m.group(1)), m.group(2), cabeceras


def describe(host: str, ruta: str, usuario: str = "", clave: str = "",
             puerto: int = PUERTO_RTSP,
             timeout: float = TIMEOUT_S) -> tuple[int, str, dict[str, str]]:
    """Envía `DESCRIBE` y devuelve `(estado, motivo, cabeceras)`.

    Si la cámara responde `401`, reintenta una vez con la cabecera
    `Authorization` que pida el reto. `0` significa que no hubo respuesta RTSP.
    """
    uri = f"rtsp://{host}:{puerto}{ruta}"

    def peticion(autorizacion: str | None, cseq: int) -> str:
        lineas = [
            f"DESCRIBE {uri} RTSP/1.0",
            f"CSeq: {cseq}",
            "User-Agent: mapeo3d-probe",
            "Accept: application/sdp",
        ]
        if autorizacion:
            lineas.append(f"Authorization: {autorizacion}")
        return "\r\n".join(lineas) + "\r\n\r\n"

    try:
        with socket.create_connection((host, puerto), timeout=timeout) as s:
            s.settimeout(timeout)
            s.sendall(peticion(None, 1).encode())
            datos = s.recv(4096).decode("utf-8", "replace")
            estado, motivo, cab = _parsear(datos)

            if estado == 401 and usuario:
                reto = cab.get("www-authenticate", "")
                auth = cabecera_autorizacion(usuario, clave, "DESCRIBE", uri, reto)
                if auth:
                    s.sendall(peticion(auth, 2).encode())
                    datos = s.recv(4096).decode("utf-8", "replace")
                    estado, motivo, cab2 = _parsear(datos)
                    cab.update(cab2)
            return estado, motivo, cab
    except socket.timeout:
        return 0, "sin respuesta (timeout)", {}
    except OSError as e:
        return 0, f"no se pudo conectar: {e}", {}


@dataclass
class Sondeo:
    """Diagnóstico de una cámara: qué funciona y qué no."""

    host: str
    puerto: int = PUERTO_RTSP
    abierto: bool = False
    rtsp: bool = False
    autenticado: bool = False
    rutas_ok: list[str] = field(default_factory=list)
    rutas_probadas: list[tuple[str, int, str]] = field(default_factory=list)
    servidor: str = ""

    @property
    def conecta(self) -> bool:
        return bool(self.rutas_ok)

    def diagnostico(self) -> str:
        if not self.abierto:
            return (
                f"El puerto {self.puerto} de {self.host} no abre.\n"
                "  - Comprobar que la IP es la correcta (probar --scan).\n"
                "  - Comprobar que la cámara está encendida y en la MISMA subred.\n"
                "  - En las Amcrest recién sacadas de la caja hay que ACTIVARLAS\n"
                "    primero por la interfaz web o la app: sin contraseña de\n"
                "    administrador creada, el servicio RTSP no se levanta."
            )
        if not self.rtsp:
            return (f"Algo escucha en {self.host}:{self.puerto}, pero no responde "
                    "RTSP. ¿Es otro dispositivo con ese puerto abierto?")
        if not self.autenticado:
            return (
                "La cámara responde RTSP pero **rechaza las credenciales** (401).\n"
                "  - En Amcrest el usuario suele ser 'admin' y la contraseña es la\n"
                "    que se creó al activarla, NO la de la cuenta de la app.\n"
                "  - En Tapo hace falta crear una 'cuenta de cámara' aparte, que es\n"
                "    distinta de la cuenta TP-Link.\n"
                "  - Si la contraseña lleva caracteres raros, comprobar que llega\n"
                "    entera: en el YAML entrecomillarla."
            )
        if not self.rutas_ok:
            return (
                "Credenciales correctas, pero **ninguna ruta RTSP conocida existe**\n"
                "(404). El modelo declarado no coincide con la cámara real.\n"
                "  - Revisar 'model' en la configuración.\n"
                "  - Buscar la ruta en la interfaz web de la cámara."
            )
        return f"Conecta correctamente por {self.rutas_ok[0]}"

    def resumen(self) -> str:
        L = [f"[{self.host}:{self.puerto}]"]
        L.append(f"  puerto abierto: {'sí' if self.abierto else 'NO'}")
        if self.abierto:
            L.append(f"  responde RTSP:  {'sí' if self.rtsp else 'NO'}"
                     + (f"   servidor: {self.servidor}" if self.servidor else ""))
            L.append(f"  credenciales:   {'OK' if self.autenticado else 'RECHAZADAS'}")
        for ruta, estado, motivo in self.rutas_probadas:
            marca = "OK " if estado == 200 else f"{estado:3d}"
            L.append(f"    {marca}  {ruta}   {motivo}")
        return "\n".join(L)


def sondear(host: str, usuario: str = "", clave: str = "",
            puerto: int = PUERTO_RTSP, modelos: list[str] | None = None,
            timeout: float = TIMEOUT_S) -> Sondeo:
    """Sondea una cámara probando las rutas RTSP de los modelos conocidos.

    Se prueban **todos** los modelos y no sólo el declarado: el fallo más
    frecuente al estrenar una cámara es tener el modelo mal puesto en la
    configuración, y probarlos todos lo detecta en la misma pasada.
    """
    s = Sondeo(host=host, puerto=puerto)
    s.abierto = puerto_abierto(host, puerto, timeout)
    if not s.abierto:
        return s

    candidatas: list[str] = []
    for modelo in (modelos or list(RTSP_PATHS)):
        for stream in ("main", "sub"):
            ruta = RTSP_PATHS.get(modelo, {}).get(stream)
            if ruta and ruta not in candidatas:
                candidatas.append(ruta)

    for ruta in candidatas:
        estado, motivo, cab = describe(host, ruta, usuario, clave, puerto, timeout)
        if estado:
            s.rtsp = True
        if cab.get("server"):
            s.servidor = cab["server"]
        if estado not in (0, 401):
            s.autenticado = True
        if estado == 200:
            s.rutas_ok.append(ruta)
        s.rutas_probadas.append((ruta, estado, motivo))
    return s


def escanear(prefijo: str, puerto: int = PUERTO_RTSP, timeout: float = 0.35,
             hilos: int = 64) -> list[str]:
    """Busca hosts con el puerto RTSP abierto en una subred `/24`.

    Args:
        prefijo: los tres primeros octetos, p. ej. `"192.168.1"`.

    Sólo intenta abrir un socket TCP y cerrarlo: no envía datos ni cambia nada.
    """
    from concurrent.futures import ThreadPoolExecutor

    hosts = [f"{prefijo}.{i}" for i in range(1, 255)]
    with ThreadPoolExecutor(max_workers=hilos) as ex:
        abiertos = list(ex.map(lambda h: puerto_abierto(h, puerto, timeout), hosts))
    return [h for h, ok in zip(hosts, abiertos) if ok]


def prefijo_local() -> str | None:
    """Los tres primeros octetos de la IP local, para escanear su subred."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            # No envía nada: sólo fuerza al SO a elegir la interfaz de salida.
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        return ip.rsplit(".", 1)[0]
    except OSError:
        return None


__all__ = [
    "PUERTO_RTSP",
    "Sondeo",
    "cabecera_autorizacion",
    "describe",
    "escanear",
    "mask_url",
    "prefijo_local",
    "puerto_abierto",
    "sondear",
]
