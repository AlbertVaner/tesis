"""Reloj para medir intervalos y edades. Una sola fuente para todos.

**No usar `time.monotonic()` para esto.** En Windows su resolución es de
15.62 ms, casi igual al periodo del MoCap del Robotat (~16 ms a 60 Hz). Medido
el 2026-09-12 sobre el flujo real:

    mensajes reales                              61.4 Hz
    con time.monotonic(): 69 % de los intervalos salen exactamente 0,
      el filtro `0 < interval` los descarta, y la media de los que
      sobreviven da                              18.9 Hz   (tres veces menos)
    con time.perf_counter()                      61.5 Hz   (correcto)

El síntoma es traicionero: no falla nada, simplemente la telemetría miente. La
columna `mocap_hz` de todos los logs anteriores a esa fecha está mal por un
factor de ~3, y con ella las velocidades derivadas por diferencias.

`perf_counter` es igual de monótono y tiene 0.1 us de resolución.

Por qué vive en `shared/`
-------------------------
Lo consumen dos categorías distintas: `two_drones/` (edad de la pose, ritmo de
extpos, registro) y `joystick/` (`marker_mocap.Pose.age_s`, que arrastra el
mismo defecto). Y sobre todo: **quien guarda una marca de tiempo y quien la
compara tienen que usar el mismo reloj.** `perf_counter` y `monotonic` tienen
épocas distintas, así que mezclarlos no da un error, da edades absurdas —del
orden de 84 000 s— que pasan los umbrales sin que nadie se entere.
"""

from __future__ import annotations

import time

#: Instante actual, en segundos, para intervalos y edades.
ahora = time.perf_counter

#: Resolución del reloj, en segundos. Útil para avisar en diagnósticos.
RESOLUCION_S = time.get_clock_info("perf_counter").resolution

__all__ = ["ahora", "RESOLUCION_S"]
