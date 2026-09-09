---
fecha: 2026-09-08
tipo: analisis
autor: claude
estado: propuesta
---
# Oscilación de los drones con el backend de mocap

Análisis de sólo lectura del código de `controllers/` y de las 17 sesiones CSV de `results/data/dos_drones/2026-09-05/`. Nada se ha cambiado todavía.

## El dato que cambia el problema

**La oscilación no es exclusiva de dos drones.** Aparece igual con un solo dron y en hover puro, sin ningún `go_to`:

| Sesión | Configuración | Medida |
|---|---|---|
| 112041 | Dron 1 solo, 47 s de hover | z pico a pico 0.43 m |
| 111530 | Dron 2 solo | XY pico a pico 0.40 m, roll σ 5.4° |
| 122248 | Dos drones, hover | XY pico a pico 0.33 m, pitch máximo 10.9° |
| 115449 | Seguimiento del marker | x pico a pico 0.87 m |

Frecuencia de la oscilación: 0.35 a 0.45 Hz. Amplitud: ±5 a 20 cm en XY, hasta ±20 cm en Z. El EKF sigue bien al mocap (error medio entre 0.014 y 0.05 m), así que el dron sabe dónde está; oscila porque la estimación llega tarde o irregular, o porque actúa en un marco girado. El camino de código con `--single` es idéntico al de dos drones salvo las comprobaciones de separación.

## Cómo funciona hoy el lazo

Cada dron tiene su Crazyradio y su cliente MQTT. Cada mensaje del Robotat se convierte a XYZ en metros y se reenvía al EKF con `send_extpos`, **sólo posición**, limitado a 20 Hz en `drone_unit.py:34,210-219`. El preflight fija `stabilizer.estimator=2`, activa el commander high-level y resetea el Kalman con valores por defecto; no toca `locSrv.*` ni yaw. Después sólo manda `takeoff`, `go_to` (siempre con yaw 0) y `land`. El seguimiento del marker 65 reenvía un `go_to` de 0.75 s cada 0.10 s.

## Causas probables

| Causa | Evidencia | Confianza | Corrección |
|---|---|---|---|
| **Extpos limitado a 20 Hz, igual a la tasa del Robotat (20 a 24 Hz)**. Se descarta cerca de uno de cada dos frames y el EKF recibe ~11 Hz irregulares. En Z no hay otro sensor. El comentario que justifica el límite habla de "radio compartida", pero cada dron tiene su radio | `drone_unit.py:31-34,212`; CSV: `mocap_hz` 20 a 24, intervalo ~45 ms por debajo de los 50 ms del throttle | Alta | Subir `EXTPOS_RATE_HZ` a 60 o quitar el throttle |
| **Yaw nunca se envía**. El EKF asume yaw 0 al reset y todos los `go_to` mandan yaw 0. Si la nariz no apunta a +X del Robotat, el controlador actúa en un marco girado y produce vaivén lento | `drone_unit.py:155-156,219` ignora `rotation`; `cruz_highlevel_backend.py:352,379,443` yaw 0.0; no hay chequeo de rumbo ni yaw en el CSV | Media-alta (sin yaw en el CSV no se puede confirmar) | Enviar `send_extpose` con el cuaternión del Robotat, o verificar rumbo en preflight |
| **`go_to` solapados**. El seguimiento manda `go_to` de 0.75 s cada 0.10 s, con paso calculado contra el objetivo anterior y sin zona muerta, así que persigue el ruido del marker. El joystick web manda `move` de 3 a 4 s cada 0.25 s. cflib advierte contra `go_to` solapados | `camera_marker_runtime.py:329,403-418`; `marker_follow.py:155-162`; `experiment_session.py:244-246,281`; sesión 113802: 193 GOTO en ráfagas de 0.25 s | Alta para seguimiento y joystick; no explica el hover | Zona muerta de 2 cm, periodo ≥ mitad de la duración, duración proporcional a la distancia |
| Latencia MQTT no acotada ni registrada | `drone_unit.py:166-182`; el campo existe pero no va al CSV | Baja | Registrar y rechazar frames con más de 80 ms |
| `locSrv.extPosStdDev` por defecto (0.01 m) con medidas retrasadas | `crazyflie_link.py:40-46` no lo fija | Baja | Probar 0.02 a 0.03 después de arreglar la tasa |

## Descartado con evidencia

- Ids cruzados, ejes o unidades: cada dron sigue sus propios objetivos en metros con Z arriba.
- Radio, MQTT o multiproceso compartidos: dos radios en canales distintos, un cliente MQTT por dron, y el extpos nunca pasa por el socket JSON.
- Pérdida de tracking: frecuencia mínima 10.6 Hz, edad máxima 0.28 s.
- Parámetros del EKF distintos por dron: idénticos y por defecto.
- Autorepeat de teclado: deshabilitado.

## Los tres cambios, en orden

1. **Alimentar el EKF con todos los frames** (`drone_unit.py`): `EXTPOS_RATE_HZ = 60.0`. Validar añadiendo `extpos_submitted` y `mqtt_accepted_msgs` al CSV: la razón debe pasar de ~0.5 a ~1.0, y en hover de 30 s la Z pico a pico debe bajar de 0.43 m a menos de 0.1 m.
2. **Orientación al EKF y chequeo de rumbo** (`drone_unit.py`, `_on_mocap`): parsear el cuaternión del Robotat con el mismo parser de `marker_mocap.py:342-368` y usar `send_extpose`. Antes de volar, confirmar la convención de ejes con `joystick/marker_orientation_check.py`. Alternativa mínima: en `wait_for_ekf_alignment` calcular el yaw del Robotat y abortar si supera 10°. Validar registrando `stateEstimate.yaw` y el yaw del mocap en el CSV: deben coincidir ±5°.
3. **Desacoplar el reapuntado del `go_to`**: `FOLLOW_COMMAND_PERIOD_S` de 0.10 a 0.50, zona muerta de 2 cm en `marker_follow.highlevel_delta`, `FOLLOW_GOTO_DURATION_S` a 1.0, y en `move()` duración `max(1.0, distancia/0.10)` rechazando un `move` mientras el anterior no termine. Validar en `--dry-run` contando `follow_move` y `move` por segundo (2 o menos), y en hardware comprobando en el CSV que no hay ráfagas de 0.25 s.

Además conviene añadir al analizador una métrica de oscilación (pico a pico y σ por eje en los holds, frecuencia por cruces por cero): hoy sólo mide sobrepaso vertical.

## Cómo se convierte en tareas

- T-003: cambios 1 y 2 (rate y yaw) con su instrumentación en el CSV. Requiere prueba en el Robotat con hélices puestas sólo tras validar en `--dry-run`. Asignado a Claude por tocar código de seguridad de vuelo.
- T-004: cambio 3 (go_to solapados) y métrica de oscilación en el analizador. Asignado a Codex: el cambio es acotado y se valida en simulación.
