"""Politica de seguimiento: donde esta la persona -> hacia donde y cuan rapido.

Este modulo **no habla con la camara ni con MediaPipe**. Recibe el centro de
la persona en coordenadas normalizadas de la imagen y decide una orden. Todo
lo que hay aqui se prueba sin hardware, que es la unica forma de ajustar el
comportamiento sin gastar motores.

Por que control por velocidad y no por posicion absoluta
--------------------------------------------------------
Convertir "la persona esta a 0.3 del borde" en "gira 12 grados" exige conocer
el campo de vision horizontal, y el de la Amcrest **sigue sin medir** (ver
`external/mapeo3d/docs/hardware.md`). Con arrancar/parar no hace falta: se
mueve mientras este descentrada y se para cuando vuelve al medio. El lazo
cerrado absorbe el error de escala.

Por que la velocidad es proporcional
------------------------------------
Con velocidad fija el movimiento es de todo o nada: arranca a tope y frena en
seco, y se ve como un tiron. Aqui la velocidad crece con el error, asi que una
persona que se descentra un poco provoca una correccion lenta y una que cruza
el area provoca una rapida. Cerca del centro la camara ya va al minimo, que es
lo que hace que el final del movimiento no se note.

Por que se mueve a pulsos y no de forma continua
-----------------------------------------------
Entre lo que el detector ve y lo que el motor hace hay **tiempo muerto**: la
imagen llega con el retraso de RTSP mas el de MediaPipe, y la orden de parada
tarda otros ~300 ms en llegar a la camara. En total, medio segundo largo en el
que la camara gira sin que nadie la este mirando.

Un lazo continuo con ese tiempo muerto **siempre se pasa de largo**: cuando se
decide parar, ya se recorrio `velocidad x tiempo_muerto` de mas. Subir o bajar
la ganancia no lo arregla; es una propiedad del retraso, no del ajuste.

La solucion es no realimentar en continuo: mover un paso corto acotado,
parar, esperar a que la imagen refleje el movimiento, y volver a decidir. Cada
paso es lo bastante pequeno para que ni con todo el sobrepaso se cruce el
objetivo, y varios pasos seguidos cubren un error grande.

Por eso `enfriamiento_s` no es un capricho: tiene que ser **mayor que la
latencia de vision**. Si se reevalua antes, se decide sobre una imagen anterior
al movimiento y se manda otro paso que sobra. Ese era el origen del sobrepaso.

Con `pulso_s = 0` se vuelve al movimiento continuo, con `pulso_max_s` como
unica red de seguridad.

El paso minimo real lo fija la red, no el temporizador
------------------------------------------------------
`ControlPTZ` serializa las peticiones: primero llega `start` y despues `stop`,
y cada una cuesta ~300 ms. El motor gira **desde que llega una hasta que llega
la otra**, asi que bajar `pulso_s` por debajo de esa latencia no hace el paso
mas corto. Para pasos mas pequenos hay que bajar la **velocidad**, que si
cambia cuanto se recorre en ese tiempo.

Esperar a ver el paso, no a que pase un tiempo
----------------------------------------------
El temporizador fijo obliga a adivinar la latencia de vision, y adivinarla de
menos es exactamente lo que produce la oscilacion: se manda un paso nuevo sobre
una imagen que todavia no refleja el anterior.

En vez de eso se espera a **observar** el movimiento. Al parar se guarda donde
estaba la persona; no se manda otro paso hasta que su posicion en el cuadro
cambie al menos `cambio_minimo`. Eso se adapta solo a la latencia real, sea la
que sea, sin tener que medirla.

`espera_max_s` es la valvula de escape: si la persona camina justo al ritmo al
que gira la camara, el error no cambia nunca y sin ese tope el seguidor se
quedaria clavado. `enfriamiento_s` sigue existiendo como minimo, para no
encadenar peticiones HTTP mas rapido de lo que la camara las atiende.

Por que hay histeresis
----------------------
Mover la camara mueve a la persona dentro del cuadro: es un lazo de
realimentacion y, con un solo umbral, oscila. Por eso hay dos:

* `arrancar_en`: cuanto se tiene que descentrar para empezar a moverse;
* `parar_en`, mas pequeno: cuanto tiene que acercarse al centro para parar.

Entre los dos hay una banda donde no se hace nada, que es lo que impide el
caceo. El `enfriamiento_s` anade la misma idea en el tiempo.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Indices de MediaPipe Pose para el torso. El centro del torso es mucho mas
# estable que el del esqueleto completo: no lo arrastran ni los pies ni las
# manos cuando la persona gesticula, que es justo lo que va a estar haciendo.
HOMBROS_Y_CADERAS = (11, 12, 23, 24)

#: Codigos PTZ de Dahua/Amcrest.
IZQUIERDA, DERECHA, ARRIBA, ABAJO = "Left", "Right", "Up", "Down"
PARAR = "stop"


@dataclass(frozen=True)
class Orden:
    """Lo que hay que pedirle al motor. `codigo == PARAR` es detenerse."""

    codigo: str
    velocidad: int = 0

    @property
    def es_parada(self) -> bool:
        return self.codigo == PARAR


@dataclass(frozen=True)
class Ajustes:
    """Parametros del lazo. Los de fabrica son deliberadamente suaves."""

    arrancar_en: float = 0.16
    parar_en: float = 0.10
    #: El tilt arranca con mas holgura que el pan: una persona que camina se
    #: descentra sobre todo en horizontal, y el torso apenas sube o baja en
    #: el cuadro salvo que se acerque. Los lanzadores lo igualan al pan por
    #: defecto (`--zona-muerta-tilt`).
    arrancar_en_tilt: float = 0.20
    parar_en_tilt: float = 0.08
    #: Donde se quiere el centro del torso en vertical, como fraccion de la
    #: altura del cuadro (0 arriba, 1 abajo). 0.5 lo centra; mas de 0.5 lo
    #: baja y deja aire por encima de la cabeza para las manos levantadas
    #: (senalero, X del paro).
    objetivo_y: float = 0.5

    #: Velocidad con el error justo en el umbral de arranque.
    velocidad_min: int = 1
    #: Velocidad con la persona en el borde del cuadro.
    velocidad_max: int = 2
    #: Error (fraccion del ancho) al que ya se pide `velocidad_max`.
    error_saturacion: float = 0.42

    #: Duracion de cada paso. Es el mecanismo de parada normal. Con 0 el
    #: movimiento es continuo hasta `parar_en`. Bajarlo por debajo de la
    #: latencia HTTP (~0.3 s) no acorta el paso: ver el docstring.
    pulso_s: float = 0.12
    #: Red de seguridad: si la deteccion se pierde justo despues de arrancar,
    #: el motor no se queda girando.
    pulso_max_s: float = 2.0
    #: Espera MINIMA entre pasos, para no encadenar peticiones HTTP mas rapido
    #: de lo que la camara las atiende. La espera real la decide la
    #: confirmacion visual de abajo.
    enfriamiento_s: float = 0.30
    #: Cuanto tiene que moverse la persona en el cuadro para dar por observado
    #: el paso anterior. Por debajo de esto es ruido de deteccion.
    cambio_minimo: float = 0.02
    #: Tope de la espera por confirmacion. Sin el, una persona que camina al
    #: ritmo de la camara dejaria el error constante y el seguidor clavado.
    espera_max_s: float = 1.20

    #: Error a partir del cual el encuadre gana al gesto. Un gesto que se sale
    #: del cuadro no se puede clasificar de todas formas.
    error_critico: float = 0.28
    #: Cuanto puede un segmento retener la camara. Medido sobre 655 tomas del
    #: dataset, un gesto real dura 3.5 s de mediana; mas alla de esto lo que
    #: hay abierto es locomocion, no un gesto.
    bloqueo_max_s: float = 4.0
    #: Sin deteccion durante este tiempo, se para y no se persigue nada.
    paciencia_s: float = 1.0
    seguir_tilt: bool = True
    #: Confianza minima de un landmark para contarlo en el centro del torso.
    visibilidad_min: float = 0.5


def centro_torso(
    puntos: np.ndarray, visibilidad: np.ndarray, *, visibilidad_min: float = 0.5
) -> tuple[float, float] | None:
    """Centro `(x, y)` normalizado del torso, o `None` si no se ve.

    `puntos` son los landmarks 2D de MediaPipe normalizados a la imagen.
    Se promedian hombros y caderas visibles; con menos de dos no hay torso
    fiable y se prefiere no mover la camara a moverla mal.
    """
    if puntos is None or len(puntos) <= max(HOMBROS_Y_CADERAS):
        return None
    indices = [
        i for i in HOMBROS_Y_CADERAS
        if i < len(visibilidad) and visibilidad[i] >= visibilidad_min
    ]
    if len(indices) < 2:
        return None
    seleccion = puntos[indices]
    return float(np.mean(seleccion[:, 0])), float(np.mean(seleccion[:, 1]))


def velocidad_para(error: float, umbral: float, ajustes: Ajustes) -> int:
    """Velocidad PTZ para un error dado, entre `velocidad_min` y `_max`.

    Justo en el umbral de arranque devuelve el minimo; a partir de
    `error_saturacion` devuelve el maximo. En medio interpola linealmente.
    """
    exceso = max(0.0, abs(error) - umbral)
    tramo = max(1e-6, ajustes.error_saturacion - umbral)
    fraccion = min(1.0, exceso / tramo)
    rango = ajustes.velocidad_max - ajustes.velocidad_min
    return int(round(ajustes.velocidad_min + fraccion * rango))


def decidir_con_gesto(
    seguidor: "Seguidor",
    centro: tuple[float, float] | None,
    ahora: float,
    *,
    gesto_en_curso: bool,
) -> "Orden | None":
    """Envoltorio de `Seguidor.decidir_con_gesto`, por comodidad de llamada."""
    return seguidor.decidir_con_gesto(centro, ahora, gesto_en_curso=gesto_en_curso)


class Seguidor:
    """Maquina de estados del lazo de seguimiento.

    Uso::

        seg = Seguidor()
        orden = seg.decidir(centro, ahora)   # Orden | None

    `None` significa "no cambies nada". Solo se emite una orden cuando el
    estado del motor tiene que cambiar, asi que el llamante puede mandarla a
    la camara tal cual sin filtrar repeticiones.
    """

    def __init__(self, ajustes: Ajustes | None = None) -> None:
        self.ajustes = ajustes or Ajustes()
        self.activo: str | None = None
        self._t_inicio = 0.0
        self._t_fin = float("-inf")
        self._t_vista = float("-inf")
        # Donde estaba la persona cuando se paro el ultimo paso, y sobre que
        # eje fue. Sirven para saber si ese paso ya se ve en la imagen.
        self._centro_al_parar: tuple[float, float] | None = None
        self._eje_al_parar = 0
        self._t_bloqueo: float | None = None   # desde cuando manda el gesto

    # ------------------------------------------------------------- decision

    def decidir(self, centro: tuple[float, float] | None, ahora: float) -> Orden | None:
        a = self.ajustes

        if centro is None:
            # Se perdio la persona. Se para, pero sin buscarla: una camara que
            # sale a barrer el laboratorio sola es peor que una quieta.
            if self.activo is not None and ahora - self._t_vista >= a.paciencia_s:
                return self._parar(ahora)
            if self.activo is not None and ahora - self._t_inicio >= a.pulso_max_s:
                return self._parar(ahora)
            return None

        self._t_vista = ahora
        error_x = centro[0] - 0.5
        error_y = centro[1] - a.objetivo_y

        if self.activo is not None:
            if ahora - self._t_inicio >= self._limite_paso():
                return self._parar(ahora, centro)
            horizontal = self.activo in (IZQUIERDA, DERECHA)
            error = error_x if horizontal else error_y
            umbral = a.parar_en if horizontal else a.parar_en_tilt
            if abs(error) <= umbral:
                return self._parar(ahora, centro)
            return None

        espera = ahora - self._t_fin
        if espera < a.enfriamiento_s:
            return None
        if self._centro_al_parar is not None:
            movido = abs(centro[self._eje_al_parar]
                         - self._centro_al_parar[self._eje_al_parar])
            if movido < a.cambio_minimo and espera < a.espera_max_s:
                # El paso anterior todavia no se ve. Encadenar otro aqui es
                # justo lo que produce la oscilacion.
                return None
            self._centro_al_parar = None

        # El pan manda: una persona que camina se descentra sobre todo en
        # horizontal, y corregir las dos cosas a la vez marea la imagen.
        if abs(error_x) > a.arrancar_en:
            codigo = DERECHA if error_x > 0 else IZQUIERDA
            return self._arrancar(codigo, error_x, a.arrancar_en, ahora)
        if a.seguir_tilt and abs(error_y) > a.arrancar_en_tilt:
            codigo = ABAJO if error_y > 0 else ARRIBA
            return self._arrancar(codigo, error_y, a.arrancar_en_tilt, ahora)
        return None

    def _limite_paso(self) -> float:
        """Cuanto puede durar un movimiento seguido, en segundos."""
        a = self.ajustes
        if a.pulso_s <= 0:
            return a.pulso_max_s
        return min(a.pulso_s, a.pulso_max_s)

    # -------------------------------------------------------------- estado

    def _arrancar(self, codigo: str, error: float, umbral: float, ahora: float) -> Orden:
        self.activo = codigo
        self._t_inicio = ahora
        self._centro_al_parar = None
        return Orden(codigo, velocidad_para(error, umbral, self.ajustes))

    def _parar(self, ahora: float, centro: tuple[float, float] | None = None) -> Orden:
        # Se guarda el eje del movimiento que termina: el paso solo se puede
        # dar por visto mirando la coordenada que ese paso movia.
        self._eje_al_parar = 0 if self.activo in (IZQUIERDA, DERECHA) else 1
        self._centro_al_parar = centro
        self.activo = None
        self._t_fin = ahora
        return Orden(PARAR)

    def decidir_con_gesto(
        self,
        centro: tuple[float, float] | None,
        ahora: float,
        *,
        gesto_en_curso: bool,
    ) -> Orden | None:
        """Politica cuando la camara ademas reconoce gestos.

        **El gesto tiene prioridad, pero no absoluta.** Girar durante un gesto
        lo contamina —motion blur en los landmarks, y movimiento aparente en
        las manos, que es justo lo que el reconocedor usa— asi que por defecto
        la camara se queda quieta mientras haya un segmento abierto.

        Pero `en_segmento` no significa "esta haciendo un gesto": significa
        "se esta moviendo". Caminar abre segmento, y caminar es exactamente
        cuando hace falta seguir. Medido contra la camara del laboratorio, la
        prioridad absoluta bloqueaba **10 de cada 11** correcciones y dejaba el
        seguimiento inservible.

        De ahi dos escapes:

        * `error_critico`: si la persona esta a punto de salirse del cuadro, el
          encuadre gana. Un gesto que no se ve no se puede clasificar, asi que
          protegerlo a costa de perder a la persona no protege nada.
        * `bloqueo_max_s`: un segmento no puede retener la camara mas que
          cualquier gesto real. Sobre 655 tomas del dataset la mediana es 3.5 s;
          lo que dure mas es locomocion.
        """
        a = self.ajustes
        if not gesto_en_curso:
            self._t_bloqueo = None
            return self.decidir(centro, ahora)

        if self._t_bloqueo is None:
            self._t_bloqueo = ahora

        critico = centro is not None and abs(centro[0] - 0.5) >= a.error_critico
        agotado = ahora - self._t_bloqueo >= a.bloqueo_max_s
        if critico or agotado:
            return self.decidir(centro, ahora)
        return self.detener(ahora)

    def en_movimiento(self, ahora: float) -> bool:
        """True si el motor gira o todavia esta frenando.

        Los frames tomados en esa ventana llevan motion blur y sus landmarks
        no sirven para clasificar un gesto. La ventana incluye el enfriamiento
        a proposito: la orden de parada tarda ~300 ms en llegar, asi que el
        motor sigue girando un rato despues de que la politica decida pararlo.
        """
        if self.activo is not None:
            return True
        return ahora - self._t_fin < self.ajustes.enfriamiento_s

    def detener(self, ahora: float = 0.0) -> Orden | None:
        """Orden de parada incondicional, para el cierre del programa."""
        if self.activo is None:
            return None
        return self._parar(ahora)
