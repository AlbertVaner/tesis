"""Cliente PTZ para camaras Amcrest / Dahua sobre su API HTTP CGI.

Solo depende de la biblioteca estandar: la autenticacion es Digest MD5, que
`urllib` sabe hacer y que es la que piden estas camaras.

Endpoints usados::

    /cgi-bin/ptz.cgi?action=getStatus&channel=1
    /cgi-bin/ptz.cgi?action=getCurrentProtocolCaps&channel=1
    /cgi-bin/ptz.cgi?action=start&channel=1&code=Left&arg1=0&arg2=<vel>&arg3=0
    /cgi-bin/ptz.cgi?action=stop&channel=1&code=Left&arg1=0&arg2=0&arg3=0
    /cgi-bin/ptz.cgi?action=start&channel=1&code=PositionABS&arg1=<pan>&arg2=<tilt>&arg3=<zoom>
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

import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Iterable

TIEMPO_ESPERA_S = 5.0

#: Codigos aceptados por `mover`. `stop` no es un codigo, es una accion.
CODIGOS = ("Left", "Right", "Up", "Down")


#: Clave de la rotacion de imagen: 0 sin rotar, 1 = 90 grados horario,
#: 2 = 270 horario (90 antihorario). Comprobado el 2026-09-18 con la IP4M-1041B
#: montada de lado: con 2, lo que estaba a la izquierda del cuadro pasa abajo.
CLAVE_ROTACION = "VideoInOptions[0].Rotate90"
#: Volteos del sensor. Medido el 2026-09-18: `Flip` voltea el sensor en
#: vertical y `Mirror` en horizontal, y los dos se aplican **antes** que
#: `Rotate90` (con la imagen rotada 270, `Flip` se veia como un espejo
#: izquierda-derecha y `Mirror` como un volteo arriba-abajo). Girar la imagen
#: 180 grados, para una camara montada boca abajo, es `Flip` + `Mirror`.
CLAVE_FLIP = "VideoInOptions[0].Flip"
CLAVE_MIRROR = "VideoInOptions[0].Mirror"

#: Que codigo pedirle al motor para mover el encuadre hacia un lado **del
#: cuadro que se ve en pantalla**, segun la rotacion de imagen. La rotacion
#: gira la imagen, no los motores: con la camara montada de lado, el motor de
#: pan desplaza la escena en vertical y el de tilt en horizontal. Sin esta
#: tabla el seguidor corrige un error horizontal con el pan, la persona no se
#: centra nunca y el motor sigue hasta el tope.
#:
#: Derivacion para 2 (imagen girada 90 antihorario: x_pantalla = y_sensor,
#: y_pantalla = 1 - x_sensor): derecha del cuadro = abajo del sensor = Down;
#: abajo del cuadro = izquierda del sensor = Left. Para 1 es la inversa.
MOTOR_SEGUN_ROTACION: dict[int, dict[str, str]] = {
    0: {"Left": "Left", "Right": "Right", "Up": "Up", "Down": "Down"},
    1: {"Left": "Down", "Right": "Up", "Up": "Left", "Down": "Right"},
    2: {"Left": "Up", "Right": "Down", "Up": "Right", "Down": "Left"},
}


def pan_fisico(pan_leido: float) -> float:
    """Angulo del pan contado desde su tope mecanico, en grados.

    La lectura de `getStatus` no empieza en el tope: `fisico = 180 - leido`, que
    es ademas lo que espera `PositionABS`. Medido el 2026-09-18: con la lectura
    en 180 (fisico 0) el motor no gira mas hacia ese lado, ni a velocidad 3, y
    hacia el otro si. El recorrido declarado es de 1 a 354 grados fisicos, asi
    que el centro del recorrido es la lectura ~3, no 180. Devuelve un valor
    entre -3 y 357 para que el sector muerto quede pegado al tope de abajo.
    """
    fisico = (180.0 - float(pan_leido)) % 360.0
    return fisico - 360.0 if fisico > 357.0 else fisico


def pan_para_posicion_abs(pan_leido: float) -> float:
    """Pan que hay que pedirle a `PositionABS` para que `getStatus` lea `pan_leido`."""
    return round((180.0 - float(pan_leido)) % 360.0, 1)


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
        self._rotacion: int | None = None   # se lee de la camara al primer uso
        self._flip = False
        self._mirror = False

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

    def rotacion_imagen(self) -> int:
        """Rotacion de imagen configurada en la camara (0, 1 o 2). Se cachea.

        Ver `MOTOR_SEGUN_ROTACION`. Un valor desconocido se trata como 0.
        """
        if self._rotacion is None:
            opciones = self.leer_configuracion("VideoInOptions")
            valor = opciones.get(CLAVE_ROTACION, "0")
            self._flip = opciones.get(CLAVE_FLIP, "false").lower() == "true"
            self._mirror = opciones.get(CLAVE_MIRROR, "false").lower() == "true"
            try:
                rotacion = int(valor)
            except ValueError:
                rotacion = 0
            self._rotacion = rotacion if rotacion in MOTOR_SEGUN_ROTACION else 0
            if self._rotacion:
                self.log(f"[ptz] imagen rotada (Rotate90={self._rotacion}): los ejes del "
                         "cuadro se cruzan con los motores de pan y tilt.")
            if self._flip or self._mirror:
                self.log(f"[ptz] imagen volteada (Flip={self._flip}, Mirror={self._mirror}): "
                         "el firmware ya invierte los motores; no se corrige nada aqui.")
        return self._rotacion

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

    def limites_tilt(self) -> tuple[float, float] | None:
        """`(minimo, maximo)` del tilt en grados, o `None` si la camara no lo dice.

        En la IP4M-1041B son -4 y 79: el tilt recorre unos 83 grados, frente a
        los 354 del pan. Con la camara montada de lado ese es el recorrido
        **horizontal** del seguimiento, y uno de sus extremos es un tope
        mecanico a medio metro del centro del encuadre. Ver `ControlPTZ.tope`.
        """
        caps = self.capacidades()
        try:
            return (float(caps["caps.PtzMotionRange.VerticalAngle[0]"]),
                    float(caps["caps.PtzMotionRange.VerticalAngle[1]"]))
        except (KeyError, ValueError):
            return None

    def codigo_motor(self, codigo: str) -> str:
        """Codigo del motor que mueve el encuadre hacia `codigo` en pantalla.

        Solo se deshace la **rotacion** (`MOTOR_SEGUN_ROTACION`). Los volteos
        `Flip` y `Mirror` **no se tocan: el firmware ya invierte el sentido de
        los motores** cuando estan activos, para que las flechas de su web
        sigan siendo intuitivas con la camara colgada del techo.

        Medido el 2026-09-18 con la camara boca abajo (`Flip` + `Mirror`,
        `Rotate90=0`), por correlacion de fase entre dos capturas: un pulso de
        `Left` desplazo la escena +106 px (la vista fue a la izquierda del
        cuadro) y uno de `Up` la desplazo +55 px hacia abajo (la vista subio).
        O sea, identidad. Invertirlos aqui ademas hacia girar la camara al
        reves en los dos ejes.
        """
        return MOTOR_SEGUN_ROTACION[self.rotacion_imagen()][codigo]

    def limites_pan(self) -> tuple[float, float] | None:
        """`(minimo, maximo)` del pan en grados fisicos (ver `pan_fisico`)."""
        caps = self.capacidades()
        try:
            return (float(caps["caps.PtzMotionRange.HorizontalAngle[0]"]),
                    float(caps["caps.PtzMotionRange.HorizontalAngle[1]"]))
        except (KeyError, ValueError):
            return None

    def sentido_pan(self, motor: str) -> int:
        """+1 si `motor` aumenta el pan fisico, -1 si lo baja, 0 si es tilt.

        Medido: sin voltear, `Right` aumenta el fisico (lectura de 0 a 298.9);
        con la imagen volteada el firmware lo invierte y es `Left` el que lo
        aumenta (lectura de 180 a 166.9) y `Right` el que choca con el tope.
        """
        if motor not in ("Left", "Right"):
            return 0
        sentido = 1 if motor == "Right" else -1
        self.rotacion_imagen()               # carga tambien los volteos
        return -sentido if self._mirror else sentido

    def sentido_tilt(self, motor: str) -> int:
        """+1 si `motor` aumenta la lectura del tilt, -1 si la baja, 0 si es pan.

        Con `Flip` activo el firmware invierte `Up` y `Down`: medido, un pulso
        de `Up` llevo la lectura de 2.0 a -6.3. Lo usa `ControlPTZ` para saber
        contra que tope empuja una orden.
        """
        if motor not in ("Up", "Down"):
            return 0
        sentido = 1 if motor == "Up" else -1
        self.rotacion_imagen()               # carga tambien los volteos
        return -sentido if self._flip else sentido

    # ---------------------------------------------------------- movimiento

    def ir_a(self, pan: float, tilt: float, zoom: float = 1.0) -> None:
        """Posicion absoluta, en los grados que devuelve `posicion()`.

        `PositionABS` y `getStatus` **no usan la misma convencion de pan**.
        Medido el 2026-09-18 en la IP4M-1041B: pedir 180 deja la lectura en 0,
        pedir 170 la deja en 9.9. O sea `leido = 180 - pedido` (modulo 360).
        Aqui se convierte, para que `ir_a(p, t)` deje `posicion()` en `(p, t)`.
        Sin la conversion, "ir al frente" (pan 180) mandaba la camara a mirar
        hacia atras. El tilt si coincide, con un par de grados de error.
        """
        self._pedir({
            "action": "start", "channel": self.canal, "code": "PositionABS",
            "arg1": pan_para_posicion_abs(pan), "arg2": round(float(tilt), 1),
            "arg3": zoom,
        })

    def mirar_al_frente(self, frente: tuple[float, float] | None, *,
                        timeout_s: float = 12.0, tolerancia: float = 3.0,
                        dormir=time.sleep) -> bool:
        """Lleva la camara a `frente = (pan, tilt)` y espera a que llegue.

        Devuelve `True` si llego (o si no habia nada que hacer). No lanza: que
        la camara no llegue al frente no debe impedir arrancar, solo avisarse.
        La posicion que reporta la camara tiene un par de grados de error, de
        ahi la tolerancia; el pan se compara modulo 360.
        """
        if frente is None:
            return True
        pan, tilt = frente
        self.log(f"[ptz] mirando al frente: pan {pan:.1f}  tilt {tilt:.1f}")
        try:
            self.ir_a(pan, tilt)
            if self.dry_run:
                return True
            for _ in range(max(1, int(timeout_s / 0.5))):
                dormir(0.5)
                pos = self.posicion()
                if pos is None:
                    continue
                d_pan = abs((pos[0] - pan + 180.0) % 360.0 - 180.0)
                if d_pan <= tolerancia and abs(pos[1] - tilt) <= tolerancia:
                    return True
        except ErrorPTZ as exc:
            self.log(f"[ptz] no se pudo ir al frente: {exc}")
            return False
        self.log("[ptz] la camara no llego al frente a tiempo; se sigue desde donde este.")
        return False

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

        El seguidor razona sobre el cuadro que se ve, asi que aqui el codigo se
        traduce al motor que de verdad mueve ese eje segun la rotacion de
        imagen. `mover` no traduce: recibe codigos de motor (`medir_ptz.py`).
        """
        if orden is None:
            return
        if orden.codigo == "stop":
            self.parar()
        else:
            self.mover(self.codigo_motor(orden.codigo), orden.velocidad)

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
