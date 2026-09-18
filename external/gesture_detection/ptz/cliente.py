"""Cliente PTZ para camaras Amcrest / Dahua sobre su API HTTP CGI.

Solo depende de la biblioteca estandar: la autenticacion es Digest MD5, que
`urllib` sabe hacer y que es la que piden estas camaras.

Endpoints usados::

    /cgi-bin/ptz.cgi?action=getStatus&channel=1
    /cgi-bin/ptz.cgi?action=getCurrentProtocolCaps&channel=1
    /cgi-bin/ptz.cgi?action=start&channel=1&code=Left&arg1=0&arg2=<vel>&arg3=0
    /cgi-bin/ptz.cgi?action=stop&channel=1&code=Left&arg1=0&arg2=0&arg3=0
    /cgi-bin/configManager.cgi?action=getConfig&name=Encode
    /cgi-bin/configManager.cgi?action=setConfig&<clave>=<valor>&...

AVISO IMPORTANTE
----------------
Mover una camara **invalida cualquier calibracion extrinseca previa, sin
sintoma visible**. Este cliente existe porque el proyecto decidio (septiembre
de 2026) posponer la calibracion y priorizar el seguimiento del operador con
una sola camara. Si en el futuro se retoma la triangulacion, este modulo NO
debe usarse sobre las camaras que triangulan. Ver
`external/mapeo3d/docs/calibration.md`.

Las credenciales nunca deben aparecer en logs ni en mensajes de error: usar
`enmascarar()` de `video_source` antes de mostrar cualquier URL.
"""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from typing import Iterable

TIEMPO_ESPERA_S = 5.0

#: Codigos aceptados por `mover`. `stop` no es un codigo, es una accion.
CODIGOS = ("Left", "Right", "Up", "Down")


class ErrorPTZ(RuntimeError):
    """La camara no acepto la peticion PTZ."""


def describir_error(exc: BaseException, ruta: str, host: str) -> str:
    """Convierte la excepcion en algo que diga que hay que arreglar.

    Los tres fallos habituales se arreglan de forma distinta y desde fuera se
    parecen: la camara no esta en esa IP, las credenciales no son las del
    dispositivo, o el endpoint no existe. Un `URLError` pelado no distingue
    ninguno, y es justo lo que uno ve en pantalla.

    La ruta no lleva credenciales —van en la cabecera Digest, no en la URL—
    asi que se puede mostrar entera.
    """
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 401:
            return (f"401 en {host}: usuario o contrasena incorrectos. Es la "
                    "cuenta 'admin' del dispositivo, la que se creo al "
                    "activarlo, no la de la app Amcrest View.")
        if exc.code == 404:
            return (f"404 en {host}{ruta}: la camara responde pero no tiene ese "
                    "endpoint. Lo normal es que no sea una Amcrest/Dahua.")
        return f"HTTP {exc.code} en {host}{ruta}"
    if isinstance(exc, urllib.error.URLError):
        return (f"{host} no responde por HTTP (el TCP puede abrir y el servidor "
                f"no contestar igualmente). Comprobar que la IP sigue siendo esa: "
                f"una camara que pasa de Wi-Fi a cable cambia de IP porque la "
                f"interfaz cableada tiene otra MAC. Detalle: {exc.reason}")
    return f"{type(exc).__name__} en {host}{ruta}"


def _parsear_respuesta(texto: str) -> dict[str, str]:
    """`clave=valor` por linea -> diccionario.

    Una linea sin `=` (la camara contesta `OK` o `Error` a `setConfig`) se
    guarda como clave con valor vacio, para poder comprobarla.
    """
    datos: dict[str, str] = {}
    for linea in texto.splitlines():
        linea = linea.strip()
        if not linea:
            continue
        clave, _, valor = linea.partition("=")
        datos[clave.strip()] = valor.strip()
    return datos


class CamaraPTZ:
    """Control pan/tilt de una camara Amcrest por HTTP.

    Con `dry_run=True` se registran las ordenes de movimiento en vez de
    enviarlas, pero las consultas de lectura si se hacen: sin ellas no se
    puede comprobar que la camara responde.
    """

    def __init__(
        self,
        host: str,
        usuario: str,
        clave: str,
        *,
        canal: int = 1,
        timeout: float = TIEMPO_ESPERA_S,
        dry_run: bool = False,
        log=print,
    ) -> None:
        self.host = host
        self.canal = canal
        self.timeout = timeout
        self.dry_run = dry_run
        self.log = log
        self._ultimo_codigo: str | None = None

        gestor = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        gestor.add_password(None, f"http://{host}/", usuario, clave)
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPDigestAuthHandler(gestor),
            urllib.request.HTTPBasicAuthHandler(gestor),
        )

    # ------------------------------------------------------------ fabricas

    @classmethod
    def desde_rtsp(cls, url: str, **kwargs) -> "CamaraPTZ":
        """Construye el cliente a partir de la URL RTSP de la misma camara.

        Evita repetir host y credenciales en dos sitios, que es una fuente
        clasica de que el video vaya a una camara y el PTZ a otra.
        """
        partes = urllib.parse.urlsplit(url)
        if not partes.hostname:
            raise ValueError("La URL RTSP no tiene host.")
        return cls(
            partes.hostname,
            urllib.parse.unquote(partes.username or ""),
            urllib.parse.unquote(partes.password or ""),
            **kwargs,
        )

    # ------------------------------------------------------------ peticion

    def _pedir(self, params: dict[str, str | int]) -> dict[str, str]:
        return self._pedir_en("/cgi-bin/ptz.cgi", params)

    def _pedir_en(self, cgi: str, params: dict[str, str | int]) -> dict[str, str]:
        consulta = urllib.parse.urlencode(params)
        ruta = f"{cgi}?{consulta}"
        # El dry-run silencia solo lo que mueve el motor. Las consultas de
        # lectura se hacen igual: no tienen efecto y sin ellas no se puede
        # validar que la camara responde.
        if self.dry_run and params.get("action") in ("start", "stop", "setConfig"):
            self.log(f"[dry-run] {ruta}")
            return {}
        try:
            respuesta = self._opener.open(
                f"http://{self.host}{ruta}", timeout=self.timeout
            )
            return _parsear_respuesta(respuesta.read().decode(errors="replace"))
        except Exception as exc:  # noqa: BLE001 - se reenvia sin credenciales
            raise ErrorPTZ(describir_error(exc, ruta, self.host)) from None

    # ------------------------------------------------------------- lectura

    def estado(self) -> dict[str, str]:
        """Posicion y estado del motor. No mueve nada."""
        return self._pedir({"action": "getStatus", "channel": self.canal})

    def posicion(self) -> tuple[float, float, float] | None:
        """`(pan, tilt, zoom)` o `None` si la camara no la reporta."""
        datos = self.estado()
        try:
            return (
                float(datos["status.Postion[0]"]),
                float(datos["status.Postion[1]"]),
                float(datos["status.Postion[2]"]),
            )
        except (KeyError, ValueError):
            return None

    def identidad(self) -> tuple[str, str]:
        """`(modelo, numero de serie)` de la camara.

        El serie es lo unico que distingue de verdad un dispositivo de otro.
        Una camara con Ethernet y Wi-Fi activos a la vez aparece **dos veces en
        la red**, con dos IP y dos MAC, y desde fuera parece dos camaras. Si dos
        IP devuelven el mismo serie, es una sola: hay que apagarle una interfaz.
        """
        datos = self._pedir_en("/cgi-bin/magicBox.cgi",
                               {"action": "getSystemInfo"})
        tipo = datos.get("deviceType", "")
        if not tipo:
            tipo = self._pedir_en(
                "/cgi-bin/magicBox.cgi", {"action": "getDeviceType"}
            ).get("type", "?")
        serie = datos.get("serialNumber") or self._pedir_en(
            "/cgi-bin/magicBox.cgi", {"action": "getSerialNo"}
        ).get("sn", "?")
        return tipo or "?", serie

    def capacidades(self) -> dict[str, str]:
        return self._pedir(
            {"action": "getCurrentProtocolCaps", "channel": self.canal}
        )

    # -------------------------------------------------------- configuracion

    def leer_configuracion(self, nombre: str) -> dict[str, str]:
        """Tabla de configuracion `nombre` (`Encode`, `VideoInOptions`...).

        Las claves vienen con el prefijo `table.`, que aqui se quita para que
        sean las mismas que acepta `escribir_configuracion`.
        """
        datos = self._pedir_en("/cgi-bin/configManager.cgi",
                               {"action": "getConfig", "name": nombre})
        return {k.removeprefix("table."): v for k, v in datos.items()}

    def escribir_configuracion(self, cambios: dict[str, str | int | bool]) -> None:
        """`setConfig` con las claves tal como las devuelve `leer_configuracion`.

        Los booleanos se mandan como `true`/`false`, que es lo que espera la
        camara. Con `dry_run` se registra y no se envia. La camara contesta
        `OK` o `Error`; cualquier otra cosa se trata como fallo.
        """
        params: dict[str, str | int] = {"action": "setConfig"}
        for clave, valor in cambios.items():
            if isinstance(valor, bool):
                valor = "true" if valor else "false"
            params[clave] = valor
        respuesta = self._pedir_en("/cgi-bin/configManager.cgi", params)
        if self.dry_run:
            return
        if "OK" not in respuesta:
            raise ErrorPTZ(f"la camara no acepto la configuracion: {respuesta or 'sin respuesta'}")

    # ---------------------------------------------------------- movimiento

    def mover(self, codigo: str, velocidad: int = 3) -> None:
        if codigo not in CODIGOS:
            raise ValueError(f"Codigo PTZ desconocido: {codigo!r}. Validos: {CODIGOS}")
        self._pedir({
            "action": "start", "channel": self.canal, "code": codigo,
            "arg1": 0, "arg2": int(velocidad), "arg3": 0,
        })
        self._ultimo_codigo = codigo

    def parar(self, codigo: str | None = None) -> None:
        """Detiene el movimiento en curso.

        La API pide el mismo `code` con el que se arranco, asi que el cliente
        recuerda el ultimo. Llamar sin nada pendiente no hace nada.
        """
        codigo = codigo or self._ultimo_codigo
        if codigo is None:
            return
        self._pedir({
            "action": "stop", "channel": self.canal, "code": codigo,
            "arg1": 0, "arg2": 0, "arg3": 0,
        })
        self._ultimo_codigo = None

    def aplicar(self, orden) -> None:
        """Traduce la salida de `Seguidor.decidir` en una peticion.

        Acepta cualquier objeto con `codigo` y `velocidad`, para no acoplar el
        transporte a la politica de seguimiento.
        """
        if orden is None:
            return
        if orden.codigo == "stop":
            self.parar()
        else:
            self.mover(orden.codigo, orden.velocidad)

    # ------------------------------------------------------------- cierre

    def __enter__(self) -> "CamaraPTZ":
        return self

    def __exit__(self, *_exc: object) -> None:
        # Pase lo que pase, el motor no se queda girando.
        try:
            self.parar()
        except ErrorPTZ:
            pass


def resumen_capacidades(caps: dict[str, str], claves: Iterable[str] = ()) -> str:
    claves = tuple(claves) or ("caps.Pan", "caps.Zoom", "caps.MoveAbsolutely",
                               "caps.Preset", "caps.PresetMax")
    return "  ".join(f"{c.removeprefix('caps.')}={caps.get(c, '?')}" for c in claves)
