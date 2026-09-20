"""Aplicar ordenes PTZ sin bloquear el bucle de vision.

Por que existe este modulo
--------------------------
Una peticion HTTP a la camara tarda **~300 ms de mediana** (medido sobre la
Amcrest del laboratorio por Wi-Fi, con picos de 437 ms). `urllib` no reutiliza
la conexion y la autenticacion Digest cuesta un desafio 401 extra por
peticion, asi que no hay forma barata de bajarlo.

Hacer esa peticion dentro del bucle de vision congela la deteccion durante
ese tiempo, y lo hace **en el peor momento posible**: justo cuando el motor
esta girando. La camara se mueve a ciegas, y cuando el bucle vuelve, la
imagen que lee ya no corresponde a la decision que origino el movimiento. El
resultado se ve como pasarse de largo y corregir a tirones, que es
exactamente el sintoma que se quiere evitar.

Con el hilo aparte, el bucle de vision nunca espera: deja la orden y sigue
detectando a su ritmo.

Solo se guarda la ULTIMA orden, no una cola
-------------------------------------------
Lo que importa es como tiene que quedar el motor, no la historia de ordenes.
Si mientras el hilo esta ocupado llegan `Right` y luego `stop`, aplicar solo
`stop` es correcto: el motor acaba donde debe. Encolarlas seria acumular
retraso, que es el problema que este modulo resuelve.
"""

from __future__ import annotations

import threading
import time

from .cliente import ErrorPTZ, pan_fisico, pan_para_posicion_abs

PERIODO_POSICION_S = 2.0

#: Grados de margen para dar por alcanzado un tope. La posicion que reporta la
#: camara no es exacta: en el tope inferior de la IP4M-1041B se leyo -6.3 con
#: un limite declarado de -4.
HOLGURA_TOPE_GRADOS = 1.5

# Dar la vuelta por el otro lado
# ------------------------------
# El pan recorre 353 grados, no 360: hay un sector muerto de unos 7 grados junto
# a su tope. Si ese tope cae hacia donde esta la persona (la camara recien
# encendida descansa pegada a el, y no siempre se puede girar la base), hacia
# un lado no hay recorrido. Pero ese lado **si se alcanza girando casi una
# vuelta entera por el otro**. Medido el 2026-09-18: 197 grados en 5.0 s.
#
# Mientras gira, la imagen no sirve: son varios segundos sin ver a la persona,
# **y por tanto sin ver sus gestos, tampoco el de paro**. Por eso no se hace a
# la primera: tienen que llegar varias ordenes seguidas contra el tope, o sea,
# la persona sigue fuera de la zona muerta despues de mas de un segundo.

#: Ordenes seguidas contra el mismo tope del pan antes de dar la vuelta.
BLOQUEOS_PARA_DAR_LA_VUELTA = 2
#: Cuanto se pasa del sector muerto al salir por el otro lado, en grados. La
#: persona estaba descentrada hacia ahi; con ~30 queda dentro del cuadro y el
#: seguimiento normal termina de centrarla.
SALTO_TRAS_LA_VUELTA_GRADOS = 30.0
ESPERA_VUELTA_S = 15.0


class ControlPTZ:
    """Puente no bloqueante entre la politica y la camara.

    Uso::

        with ControlPTZ(camara) as control:
            control.pedir(seguidor.decidir(centro, ahora))   # no bloquea
            ...
            control.posicion        # ultima conocida, refrescada en el hilo
    """

    def __init__(
        self,
        camara,
        *,
        periodo_posicion_s: float = PERIODO_POSICION_S,
        iniciar: bool = True,
    ) -> None:
        self.camara = camara
        self.periodo_posicion_s = periodo_posicion_s
        self.posicion: tuple[float, float, float] | None = None
        self.errores = 0
        self.enviadas = 0
        #: Lado del cuadro ("Left", "Right", "Up", "Down") hacia el que no se
        #: puede seguir porque el motor de tilt esta en su tope. `None` si no
        #: hay ninguno. Es para mostrarlo: desde la imagen, una camara en el
        #: tope es identica a una que no obedece.
        self.tope: str | None = None
        self.limites_tilt: tuple[float, float] | None = None
        self.limites_pan: tuple[float, float] | None = None
        #: `True` mientras la camara da la vuelta por el otro lado. Los frames
        #: de ese rato no valen para reconocer nada.
        self.dando_la_vuelta = False
        self.vueltas = 0
        self.dar_la_vuelta = True
        self._bloqueo_pan = 0                 # -1 tope bajo, +1 tope alto, 0 ninguno
        self._bloqueos_seguidos = 0
        self._codigo_bloqueado: str | None = None
        self._limites_leidos = False

        self._deseado = None
        self._aplicado = None
        self._t_posicion = float("-inf")
        self._lock = threading.Lock()
        self._hay_trabajo = threading.Event()
        self._parar = threading.Event()
        self._hilo: threading.Thread | None = None
        if iniciar:
            self.iniciar()

    # ---------------------------------------------------------------- ciclo

    def iniciar(self) -> "ControlPTZ":
        if self._hilo is None:
            self._hilo = threading.Thread(
                target=self._bucle, name="ControlPTZ", daemon=True
            )
            self._hilo.start()
        return self

    def _bucle(self) -> None:
        while not self._parar.is_set():
            self._ciclo(time.monotonic())
            # Espera corta: la posicion hay que refrescarla aunque no lleguen
            # ordenes, asi que no se puede bloquear indefinidamente.
            self._hay_trabajo.wait(0.05)
            self._hay_trabajo.clear()

    def _ciclo(self, ahora: float) -> None:
        """Una pasada del hilo. Separada para poder probarla sin hilos."""
        with self._lock:
            deseado, self._deseado = self._deseado, None

        if deseado is not None and deseado != self._aplicado:
            try:
                if self._contra_el_tope(deseado):
                    # Empujar contra el tope no mueve nada y gasta el motor.
                    self.tope = deseado.codigo
                    self._aplicado = deseado
                    self._contar_bloqueo(deseado.codigo)
                else:
                    if getattr(deseado, "codigo", "stop") != "stop":
                        self.tope = None
                        self._bloqueos_seguidos = 0
                        self._codigo_bloqueado = None
                    self.camara.aplicar(deseado)
                    self._aplicado = deseado
                    self.enviadas += 1
            except ErrorPTZ:
                self.errores += 1

        if ahora - self._t_posicion >= self.periodo_posicion_s:
            self._t_posicion = ahora
            try:
                self.posicion = self.camara.posicion()
            except ErrorPTZ:
                self.posicion = None

    def _contra_el_tope(self, orden) -> bool:
        """`True` si `orden` empuja un motor mas alla de su recorrido.

        El tilt recorre unos 83 grados y el pan 353: los dos tienen topes y los
        dos se alcanzan de verdad. Usa la ultima posicion conocida, que se
        refresca cada `periodo_posicion_s`.
        """
        codigo = getattr(orden, "codigo", "stop")
        traducir = getattr(self.camara, "codigo_motor", None)
        if codigo == "stop" or traducir is None:
            return False
        if not self._limites_leidos:
            self._limites_leidos = True
            leer = getattr(self.camara, "limites_tilt", None)
            self.limites_tilt = leer() if leer is not None else None
            leer = getattr(self.camara, "limites_pan", None)
            self.limites_pan = leer() if leer is not None else None
        if self.posicion is None:
            return False
        motor = traducir(codigo)
        self._bloqueo_pan = 0

        # Pan. Da casi la vuelta entera, pero no entera: tiene un tope, y si
        # el frente cae encima la camara solo puede seguir hacia un lado.
        sentido_pan_de = getattr(self.camara, "sentido_pan", None)
        if self.limites_pan is not None and sentido_pan_de is not None:
            sentido = sentido_pan_de(motor)
            fisico = pan_fisico(self.posicion[0])
            if sentido < 0 and fisico <= self.limites_pan[0] + HOLGURA_TOPE_GRADOS:
                self._bloqueo_pan = -1
                return True
            if sentido > 0 and fisico >= self.limites_pan[1] - HOLGURA_TOPE_GRADOS:
                self._bloqueo_pan = 1
                return True

        if self.limites_tilt is None:
            return False
        # Hacia donde mueve `motor` la lectura del tilt. Con la imagen
        # volteada el firmware invierte Up y Down, y la camara lo sabe.
        sentido_de = getattr(self.camara, "sentido_tilt", None)
        if sentido_de is not None:
            sentido = sentido_de(motor)
        else:
            sentido = {"Up": 1, "Down": -1}.get(motor, 0)
        tilt = self.posicion[1]
        minimo, maximo = self.limites_tilt
        if sentido < 0:
            return tilt <= minimo + HOLGURA_TOPE_GRADOS
        if sentido > 0:
            return tilt >= maximo - HOLGURA_TOPE_GRADOS
        return False

    def _contar_bloqueo(self, codigo: str) -> None:
        """Cuenta ordenes seguidas contra el tope del pan y, si toca, da la vuelta."""
        if self._bloqueo_pan == 0 or not self.dar_la_vuelta:
            return
        if codigo == self._codigo_bloqueado:
            self._bloqueos_seguidos += 1
        else:
            self._codigo_bloqueado = codigo
            self._bloqueos_seguidos = 1
        if self._bloqueos_seguidos >= BLOQUEOS_PARA_DAR_LA_VUELTA:
            self._dar_la_vuelta(self._bloqueo_pan)

    def _dar_la_vuelta(self, tope: int, dormir=time.sleep) -> None:
        """Lleva el pan al otro extremo de su recorrido, pasado el sector muerto."""
        ir_a = getattr(self.camara, "ir_a", None)
        if ir_a is None or self.posicion is None or self.limites_pan is None:
            return
        minimo, maximo = self.limites_pan
        fisico = (maximo - SALTO_TRAS_LA_VUELTA_GRADOS if tope < 0
                  else minimo + SALTO_TRAS_LA_VUELTA_GRADOS)
        pan = pan_para_posicion_abs(fisico)       # la conversion es simetrica
        tilt = self.posicion[1]
        self.dando_la_vuelta = True
        try:
            ir_a(pan, tilt)
            self.vueltas += 1
            if not getattr(self.camara, "dry_run", False):
                for _ in range(int(ESPERA_VUELTA_S / 0.4)):
                    dormir(0.4)
                    pos = self.camara.posicion()
                    if pos is not None:
                        self.posicion = pos
                        if abs((pos[0] - pan + 180.0) % 360.0 - 180.0) <= 3.0:
                            break
        finally:
            self.dando_la_vuelta = False
            self.tope = None
            self._bloqueos_seguidos = 0
            self._codigo_bloqueado = None
            with self._lock:
                self._deseado = None              # lo decidido durante el giro no vale
            self._aplicado = None

    # --------------------------------------------------------------- envio

    def pedir(self, orden) -> None:
        """Registra la orden y vuelve de inmediato. `None` no hace nada."""
        if orden is None:
            return
        with self._lock:
            self._deseado = orden
        self._hay_trabajo.set()

    # -------------------------------------------------------------- cierre

    def cerrar(self) -> None:
        """Para el hilo y garantiza que el motor queda detenido."""
        self._parar.set()
        self._hay_trabajo.set()
        if self._hilo is not None:
            self._hilo.join(timeout=3.0)
            self._hilo = None
        try:
            self.camara.parar()
        except ErrorPTZ:
            pass

    def __enter__(self) -> "ControlPTZ":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.cerrar()
