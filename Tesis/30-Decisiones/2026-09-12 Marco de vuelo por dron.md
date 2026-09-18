---
fecha: 2026-09-12
tipo: decision
estado: propuesta
autor: humano (catedrático) e implementación de claude
---
# Marco de vuelo por dron: los drones se colocan como indica el laboratorio

## Estado

Implementada y **revertida el mismo día** a petición del humano. Queda como diseño documentado y medido; no está en el código.

## Contexto

El EKF del Crazyflie asume, al reiniciarse, que la nariz del dron apunta a +X
del marco en que recibe las posiciones externas. El backend de mocap enviaba
las posiciones del Robotat tal cual y `go_to` con yaw 0, así que daba por
hecho que la nariz apuntaba a +X del Robotat. Nadie lo comprobaba.

Medido el 12 de septiembre con [ver_markers.py](../../controllers/joystick/ver_markers.py):
con los drones en su posición de vuelo, en paralelo, los markers publican
rumbos de 94.8° (Dron 1) y 81.5° (Dron 2). Es decir, miran a **+Y** del
Robotat. El controlador de posición corregía en un marco girado un cuarto de
vuelta, que produce una oscilación circular lenta con la misma frecuencia en X
e Y: la de los CSV del 5 de septiembre.

El catedrático indica que **esa colocación es la correcta** y que no se deben
transferir ejes ni alinear los drones con +X.

## Decisión

El código se adapta a la colocación, no al revés. Cada `DroneUnit` tiene un
**marco de vuelo** (`frame_yaw_deg`): el rumbo que publica su marker (menos el
offset del rigid body, si lo hay) con el dron quieto en el suelo, fijado en el
preflight y sin cambios en vuelo. En ese marco la nariz es +X y el yaw 0.

- Lo que va por radio se rota al marco de vuelo: posiciones y orientación al
  EKF (`send_extpos`/`send_extpose`) y objetivos de `go_to`.
- Lo que vuelve del EKF (`stateEstimate.x/y/yaw`) se desrota al Robotat.
- Geocerca, separación mínima, watchdog, panel, seguimiento del marker y CSV
  siguen en coordenadas del Robotat. Las distancias no dependen del marco.
- La comprobación de rumbo que abortaba el preflight (`--rumbo-max-deg`) se
  elimina: ya no hay un rumbo "correcto".
- Se conservan `--rumbo-offset1/2` y `--alinear-rumbo` para el caso de un
  rigid body cuyo eje X no coincida con la nariz del dron.

## Consecuencias

- Las teclas y botones del panel siguen significando ejes del Robotat
  (adelante = +X del Robotat), como antes. Lo que cambia es que ahora el dron
  ejecuta ese movimiento en la dirección correcta.
- El rigid body del Dron 2 publica roll de −84°: su rumbo (eje X proyectado)
  sirve, su actitud no. `--extpose` queda descartado para él mientras no se
  redefina.
- Si en el futuro se cambia la colocación de vuelo, no hay que tocar nada: el
  marco se mide en cada preflight.
- Registrado en `frame_yaw_deg` del CSV para que cada sesión sea auditable.

## Enlaces

- [Auditoría del controlador de dos drones](../60-Analisis/2026-09-12%20Auditoría%20del%20controlador%20de%20dos%20drones.md)
- [T-003](../10-Tareas/T-003%20Extpos%20a%2060%20Hz%20y%20yaw%20al%20EKF.md)
- `controllers/two_drones/drone_unit.py`, `controllers/two_drones/cruz_highlevel_backend.py`
