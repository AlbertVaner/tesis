---
estado: pendiente
agente: claude
repo: tesis
prioridad: alta
creada: 2026-09-08
---
## Objetivo
Que el estimador del dron reciba todos los frames del Robotat y conozca su orientación, para eliminar la oscilación de 0.35 a 0.45 Hz que aparece en hover con uno o dos drones.

## Criterio de aceptación
- [ ] `EXTPOS_RATE_HZ` en `controllers/two_drones/drone_unit.py` sube a 60 Hz (o se elimina el throttle) y el comentario que lo justificaba se corrige
- [ ] `_on_mocap` parsea el cuaternión del Robotat y envía `send_extpose`; si el mensaje no trae rotación, cae a `send_extpos` y lo registra
- [ ] El CSV de `dual_flight_logger.py` incluye `extpos_submitted`, `mqtt_accepted_msgs`, `stateEstimate.yaw` y el yaw del mocap
- [ ] `--dry-run` de `control_dos_drones_cruz_botones.py` y de `control_dron_individual_interfaz.py` arrancan sin error (`--help` en sesión no interactiva)
- [ ] Tests de `controllers/two_drones/tests/` y `tests/integration/` pasan
- [ ] Antes de volar con hélices: comprobar la convención de ejes con `controllers/joystick/marker_orientation_check.py`
- [ ] Vuelo de validación en el Robotat: en hover de 30 s, Z pico a pico por debajo de 0.1 m y yaw EKF vs mocap dentro de ±5°

## Contexto
- [Análisis de la oscilación](../60-Analisis/2026-09-08%20Oscilación%20con%20dos%20drones.md)
- `controllers/two_drones/drone_unit.py:31-34,155-156,210-219`
- `controllers/shared/crazyflie_link.py:27-48`
- `controllers/joystick/marker_mocap.py:342-368` (parser del cuaternión ya escrito)
- `AGENTS.md`, sección "Seguridad de hardware": no volar sin autorización explícita

## Bitácora
- 2026-09-08 (humano): creada a partir del análisis de la oscilación.
