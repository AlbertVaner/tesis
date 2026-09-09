---
estado: pendiente
agente: codex
repo: tesis
prioridad: media
creada: 2026-09-08
---
## Objetivo
Que el seguimiento del marker y el joystick web no manden `go_to` solapados, y que el analizador de sesiones mida la oscilación.

## Criterio de aceptación
- [ ] `controllers/two_drones/camera_marker_runtime.py`: `FOLLOW_COMMAND_PERIOD_S` pasa de 0.10 a 0.50
- [ ] `controllers/joystick/marker_follow.py`: `highlevel_delta` aplica una zona muerta `FOLLOW_DEADZONE_M = 0.02` por eje
- [ ] `controllers/two_drones/cruz_highlevel_backend.py`: `FOLLOW_GOTO_DURATION_S` pasa a 1.0; `move()` usa duración `max(1.0, distancia / 0.10)` y rechaza con `BridgeError` un `move` mientras el anterior no haya terminado (`unit.goto_until`)
- [ ] `controllers/two_drones/experiment_session.py`: el paso del joystick web se llama como máximo una vez por segundo
- [ ] `analizar_sesion_dos_drones.py` añade pico a pico y desviación por eje durante los holds, y frecuencia por cruces por cero
- [ ] Test en `controllers/two_drones/tests/` con `SimulatedBackend` que cuenta `follow_move` y `move` por segundo: 2 o menos
- [ ] Tests existentes de la carpeta y `tests/integration/` pasan; `--help` de los lanzadores afectados funciona

## Contexto
- [Análisis de la oscilación](../60-Analisis/2026-09-08%20Oscilación%20con%20dos%20drones.md), sección "Los tres cambios", punto 3
- `camera_marker_runtime.py:329,403-418`, `marker_follow.py:155-162`, `experiment_session.py:244-246,281`, `cruz_highlevel_backend.py:42-44,375`
- Regla de `AGENTS.md`: no reintroducir lazos low-level; todo sigue pasando por `go_to`
- No tocar hardware: validar sólo en simulación

## Bitácora
- 2026-09-08 (humano): creada a partir del análisis de la oscilación.
