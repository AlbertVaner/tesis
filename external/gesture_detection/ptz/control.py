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

from .cliente import ErrorPTZ

PERIODO_POSICION_S = 2.0


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
