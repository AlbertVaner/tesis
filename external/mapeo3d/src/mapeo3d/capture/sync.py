"""Emparejamiento temporal de varias cámaras sin sincronización por hardware.

Las cámaras IP no comparten reloj ni disparo. Este módulo junta, de entre los
frames que van llegando, los que corresponden **aproximadamente al mismo
instante**, y deja fuera los que no. No sabe qué es una persona: entrega frames
con marca de tiempo, igual que el resto de `capture/`.

Por qué hace falta aquí y no hizo falta al calibrar
---------------------------------------------------
En la calibración estéreo el desfase daba igual porque **el tablero estaba
quieto**: si no se mueve, no importa que una cámara lo vea 30 ms después que la
otra. Ese argumento **no se traslada al operador**, que sí se mueve. Un desfase
`dt` sobre un punto que va a velocidad `v` mete un error de posición del orden
de `v · dt`: con la muñeca a 2 m/s, 33 ms son 6.7 cm. Ver docs/capture.md.

La estrategia
-------------
Emparejamiento por **vecino más cercano en el tiempo**, con ventana de
tolerancia:

- Se elige como referencia el instante `t_ref` más reciente para el que **todas
  las cámaras al día ya tienen algún frame igual o posterior**. Así el vecino
  más cercano puede buscarse hacia los dos lados y no queda sesgado al pasado.
  Cuesta hasta un periodo de frame de latencia, y a cambio el emparejamiento es
  simétrico.
- De cada cámara se toma el frame cuya marca esté más cerca de `t_ref`.
- Si la diferencia supera la tolerancia, **esa vista no participa**. Es
  preferible triangular con 4 vistas buenas que con 6 donde 2 están desfasadas.
- Una cámara que dejó de entregar frames no bloquea al resto: se la declara
  rezagada y el conjunto sale con las demás.

Lo que este módulo NO puede detectar
------------------------------------
**Un sesgo constante por cámara pasa desapercibido, y hay que compensarlo
aparte.** Con dos cámaras a la misma tasa y periodo `T`, la distancia al vecino
más cercano es `min(d mod T, T - d mod T)`, que **nunca supera `T/2`** por
grande que sea el sesgo real `d`. A 30 fps, `T/2` = 16.7 ms, justo por debajo
de la tolerancia por defecto. Medido:

    sesgo real   5 ms  ->  vecino más cercano a   5.0 ms   entra
    sesgo real  40 ms  ->  vecino más cercano a   6.7 ms   entra
    sesgo real 120 ms  ->  vecino más cercano a  13.3 ms   entra
    sesgo real 500 ms  ->  vecino más cercano a   0.0 ms   entra

Una cámara medio segundo atrasada se empareja con desfase aparente **cero**.
Por eso `sesgos` no es un extra: el retardo de exposición, codificación, red y
decodificación difiere entre modelos y es aproximadamente constante, así que se
mide una vez —con un evento visible por todas, un flash o una palmada— y se
resta aquí. Ver docs/capture.md.

Dos consecuencias más de la misma cuenta:

- La tolerancia **no sirve para rechazar cámaras desfasadas**: sirve para
  rechazar las **paradas o que van a otra tasa**. Es su trabajo real.
- Queda un error irreducible de hasta `T/2` sin sincronización por hardware.
  A 30 fps son ±16.7 ms, que con la muñeca a 2 m/s son **±3.3 cm**. Es el suelo
  de exactitud del sistema para puntos en movimiento rápido.

Por qué el buffer vive aquí y no en `CameraStream`
--------------------------------------------------
`CameraStream` guarda **sólo el último frame** a propósito: entregar frames
viejos es peor que perderlos, y ese contrato es el que evita que se acumule
latencia. Pero el vecino más cercano a `t_ref` puede ser el frame *anterior* al
último. La historia corta que eso necesita se guarda aquí, sin tocar la
garantía de latencia de `CameraStream`.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

# Frames de historia por cámara. A 30 fps son ~0.4 s, de sobra para buscar el
# vecino más cercano dentro de una tolerancia de decenas de milisegundos.
HISTORIA = 12

# Medio periodo de frame a 30 fps. Coincide con `capture.sync_tolerance_s`.
TOLERANCIA_S = 0.017

# Una cámara cuyo frame más nuevo esté más atrasado que esto respecto del más
# nuevo de todas se considera rezagada: no fija la referencia ni frena al resto.
ESPERA_MAXIMA_S = 0.25


@dataclass
class VistaSincronizada:
    """Un frame de una cámara, ya emparejado."""

    camera: str
    frame: object
    timestamp: float
    desfase_s: float
    timestamp_llegada: float = 0.0

    @property
    def desfase_ms(self) -> float:
        return self.desfase_s * 1000.0


@dataclass
class ConjuntoSincronizado:
    """Los frames de un mismo instante, con lo que quedó fuera y por qué."""

    t_ref: float
    vistas: dict[str, VistaSincronizada]
    descartadas: dict[str, float] = field(default_factory=dict)

    @property
    def n_vistas(self) -> int:
        return len(self.vistas)

    @property
    def desfase_max_s(self) -> float:
        if not self.vistas:
            return 0.0
        return max(abs(v.desfase_s) for v in self.vistas.values())

    def frames(self) -> dict[str, object]:
        """`{nombre: frame}` para quien sólo quiera las imágenes."""
        return {n: v.frame for n, v in self.vistas.items()}

    def __contains__(self, camera: str) -> bool:
        return camera in self.vistas

    def __getitem__(self, camera: str) -> VistaSincronizada:
        return self.vistas[camera]


@dataclass
class SyncStats:
    """Salud del emparejamiento a lo largo de una sesión.

    No es depuración: con seis cámaras, saber **cuál** se queda fuera y cuántas
    veces es lo que distingue un problema de red de una cámara mal configurada.
    Una que participe mucho menos que el resto casi siempre está entregando a
    menos fps de los que declara. Ver docs/capture.md.
    """

    conjuntos: int = 0
    conjuntos_descartados: int = 0
    participaciones: dict[str, int] = field(default_factory=dict)
    descartes: dict[str, int] = field(default_factory=dict)
    desfases_ms: deque = field(default_factory=lambda: deque(maxlen=2000))

    def registrar(self, conjunto: "ConjuntoSincronizado") -> None:
        self.conjuntos += 1
        for nombre, vista in conjunto.vistas.items():
            self.participaciones[nombre] = self.participaciones.get(nombre, 0) + 1
            self.desfases_ms.append(abs(vista.desfase_ms))
        for nombre in conjunto.descartadas:
            self.descartes[nombre] = self.descartes.get(nombre, 0) + 1

    @property
    def desfase_mediano_ms(self) -> float:
        if not self.desfases_ms:
            return 0.0
        datos = sorted(self.desfases_ms)
        return datos[len(datos) // 2]

    @property
    def desfase_max_ms(self) -> float:
        return max(self.desfases_ms) if self.desfases_ms else 0.0

    def resumen(self) -> str:
        lineas = [
            f"{self.conjuntos} conjuntos emparejados "
            f"({self.conjuntos_descartados} descartados por falta de vistas), "
            f"desfase mediano {self.desfase_mediano_ms:.1f} ms, "
            f"máximo {self.desfase_max_ms:.1f} ms",
        ]
        for nombre in sorted(set(self.participaciones) | set(self.descartes)):
            si = self.participaciones.get(nombre, 0)
            no = self.descartes.get(nombre, 0)
            pct = 100.0 * si / self.conjuntos if self.conjuntos else 0.0
            lineas.append(
                f"  {nombre:<10} participó en {si} ({pct:.0f} %), "
                f"fuera de tolerancia {no}"
            )
        return "\n".join(lineas)


class MultiCameraSync:
    """Empareja los frames de varias cámaras por cercanía temporal.

    Acepta cualquier objeto con `.name` y `.read() -> (frame, timestamp) | None`;
    en producción eso es `CameraStream`, y en las pruebas un doble sin cámaras.

    Uso::

        sync = MultiCameraSync(streams, tolerancia_s=0.017)
        while True:
            conjunto = sync.next(timeout_s=0.1)
            if conjunto is None:
                continue
            for nombre, vista in conjunto.vistas.items():
                ...
        print(sync.stats.resumen())

    Args:
        streams: uno por cámara.
        tolerancia_s: desfase máximo respecto de `t_ref` para participar.
        min_vistas: por debajo de esto el conjunto se descarta entero.
        historia: frames guardados por cámara.
        espera_maxima_s: atraso a partir del cual una cámara se declara
            rezagada y deja de frenar al resto.
        sesgos: `{nombre: segundos}` de retardo constante a **restar** de la
            marca de llegada de esa cámara. Sin esto, un sesgo constante se
            empareja con desfase aparente cero; ver el encabezado del módulo.
    """

    def __init__(
        self,
        streams,
        *,
        tolerancia_s: float = TOLERANCIA_S,
        min_vistas: int = 2,
        historia: int = HISTORIA,
        espera_maxima_s: float = ESPERA_MAXIMA_S,
        sesgos: dict[str, float] | None = None,
    ) -> None:
        self.streams = list(streams)
        if not self.streams:
            raise ValueError("MultiCameraSync necesita al menos un stream.")
        nombres = [s.name for s in self.streams]
        if len(set(nombres)) != len(nombres):
            raise ValueError(f"Nombres de cámara duplicados: {nombres}")

        desconocidas = set(sesgos or {}) - set(nombres)
        if desconocidas:
            raise ValueError(
                f"sesgos nombra cámaras que no están en streams: "
                f"{sorted(desconocidas)}"
            )
        self.sesgos = {n: float((sesgos or {}).get(n, 0.0)) for n in nombres}
        self.tolerancia_s = tolerancia_s
        self.min_vistas = min_vistas
        self.espera_maxima_s = espera_maxima_s
        self.stats = SyncStats()
        self._buffers: dict[str, deque] = {
            s.name: deque(maxlen=historia) for s in self.streams
        }
        self._ultimo_t_ref = float("-inf")

    # ------------------------------------------------------------- interno

    def _sondear(self) -> int:
        """Toma el frame nuevo de cada stream, si lo hay.

        **Una lectura por stream y por vuelta, no más.** `CameraStream` no
        mantiene cola: `read()` devuelve el frame más reciente y `None` si no
        hay ninguno nuevo, así que insistir no traería nada. Y si el consumidor
        se atrasa, el descarte ya ocurrió en el hilo lector, donde corresponde:
        un frame viejo no sirve para control. Vaciar aquí una cola inexistente
        sólo serviría para saltarse instantes en silencio.
        """
        nuevos = 0
        for s in self.streams:
            r = s.read()
            if r is not None:
                llegada = float(r[1])
                # Se guarda ya corregido: todo lo que sigue razona sobre el
                # instante de captura estimado, no sobre el de llegada.
                self._buffers[s.name].append(
                    (r[0], llegada - self.sesgos[s.name], llegada)
                )
                nuevos += 1
        return nuevos

    def _referencia(self) -> float | None:
        """Instante más reciente que todas las cámaras al día ya cubrieron."""
        ultimos = [b[-1][1] for b in self._buffers.values() if b]
        if not ultimos:
            return None
        mas_nuevo = max(ultimos)
        # Las rezagadas no fijan la referencia: una cámara caída no puede
        # detener el emparejamiento de las otras cinco.
        al_dia = [t for t in ultimos if mas_nuevo - t <= self.espera_maxima_s]
        return min(al_dia) if al_dia else None

    def _emparejar(self, t_ref: float) -> ConjuntoSincronizado:
        vistas: dict[str, VistaSincronizada] = {}
        descartadas: dict[str, float] = {}
        for nombre, buffer in self._buffers.items():
            if not buffer:
                continue
            frame, t, llegada = min(buffer, key=lambda f: abs(f[1] - t_ref))
            desfase = t - t_ref
            if abs(desfase) <= self.tolerancia_s:
                vistas[nombre] = VistaSincronizada(
                    nombre, frame, t, desfase, llegada
                )
            else:
                descartadas[nombre] = desfase
        return ConjuntoSincronizado(t_ref, vistas, descartadas)

    # -------------------------------------------------------------- lectura

    def next(self, timeout_s: float = 0.0) -> ConjuntoSincronizado | None:
        """Devuelve el siguiente conjunto emparejado, o `None` si no hay.

        Con `timeout_s > 0` espera hasta ese tiempo a que se pueda formar uno.
        Nunca bloquea a los hilos lectores.
        """
        limite = time.perf_counter() + max(timeout_s, 0.0)
        while True:
            self._sondear()
            t_ref = self._referencia()
            if t_ref is not None and t_ref > self._ultimo_t_ref:
                # Se avanza siempre, incluso si el conjunto se descarta: si no,
                # el mismo instante se reevaluaría en bucle.
                self._ultimo_t_ref = t_ref
                conjunto = self._emparejar(t_ref)
                if conjunto.n_vistas >= self.min_vistas:
                    self.stats.registrar(conjunto)
                    return conjunto
                self.stats.conjuntos_descartados += 1
            if time.perf_counter() >= limite:
                return None
            time.sleep(0.001)

    def __iter__(self):
        """Itera conjuntos indefinidamente; para en cuanto deje de haberlos."""
        while True:
            conjunto = self.next(timeout_s=1.0)
            if conjunto is None:
                return
            yield conjunto
