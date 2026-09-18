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
- [ ] `EXTPOS_RATE_HZ` en `controllers/two_drones/drone_unit.py` sube a 60 Hz (o se elimina el throttle) y el comentario que lo justificaba se corrige — eliminado; se envía una vez por frame distinto
- [ ] `_on_mocap` parsea el cuaternión del Robotat y envía `send_extpose`; si el mensaje no trae rotación, cae a `send_extpos` y lo registra — parsea y registra siempre; `send_extpose` sólo con `--extpose` y rotación nivelada en el suelo (ver bitácora)
- [ ] El CSV de `dual_flight_logger.py` incluye `extpos_submitted`, `mqtt_accepted_msgs`, `stateEstimate.yaw` y el yaw del mocap — además `extpose_submitted`, `mqtt_duplicate_msgs`, `mocap_gap_max_s`, roll/pitch del mocap y `orientation_mode`
- [ ] `--dry-run` de `control_dos_drones_cruz_botones.py` y de `control_dron_individual_interfaz.py` arrancan sin error (`--help` en sesión no interactiva) — `--help` verificado en los cuatro lanzadores
- [ ] Tests de `controllers/two_drones/tests/` y `tests/integration/` pasan — 516 en verde, 20 nuevos en `test_extpos_feed.py`
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
- 2026-09-12 (claude): auditoría con MQTT crudo ([nota](../60-Analisis/2026-09-12%20Auditoría%20del%20controlador%20de%20dos%20drones.md)). El Robotat publica cada frame 3–5 veces (~86 msg/s, ~18 frames distintos/s) con huecos de 0.3 s en el 5 % de los casos; el límite de 20 Hz deja 7–13 Hz efectivos. Propuesta para el primer criterio: en vez de "60 Hz", enviar una vez por frame distinto (XYZ cambia > 0.5 mm) sin límite, y registrar en el CSV la tasa efectiva y el hueco máximo. Sin cambios de código todavía; estado sin tocar.
- 2026-09-12 (claude): implementado. `drone_unit.py`: sin límite de tasa, un envío por frame distinto (los duplicados del puente se cuentan en `mqtt_duplicate_msgs` y no van por radio ni refrescan la edad de la pose); `mocap_hz` cuenta frames distintos y `mocap_gap_max_s` el hueco máximo de 3 s; rotación parseada y registrada siempre; `decide_orientation()` en el preflight; segundo bloque de log con `stateEstimate.yaw` y batería. Decisión que se aparta del criterio: `send_extpose` **no va por defecto**, se activa con `--extpose` y sólo si la rotación es nivelada con el dron en el suelo, porque una convención de ejes distinta en el rigid body (Y arriba, o cuerpo definido girado) alimentaría al EKF una actitud falsa y eso es peor que la oscilación; la convención sigue sin verificarse con `marker_orientation_check.py`. Sin `--extpose`, el preflight aborta si el rumbo del Robotat supera `--rumbo-max-deg` (10; 0 desactiva), porque el EKF asume yaw 0. Con `--extpose`, la alineación exige yaw EKF–mocap dentro de 10° y el primer `go_to` parte del rumbo medido. Banderas en `dual_cli.py` (botones, multiproceso, panel individual y cámara dual); `control_camara_dron1.py` y el panel web construyen el backend sin ellas y quedan en sólo posición con la comprobación de rumbo por defecto. Validado: `compileall`, 516 tests, `--help`. **Pendientes del humano**: comprobar la convención de ejes y el vuelo de validación en el Robotat (hover 30 s, Z pico a pico < 0.1 m; `mocap_hz` ≈ 18 y `mocap_gap_max_s` en el CSV dicen si el puente sigue con huecos).
- 2026-09-12 (claude, tarde): en el Robotat el preflight bloqueó al Dron 1 con rumbo +97.7° y el humano confirmó que el rigid body está definido girado y no puede cambiarse. Añadidos `--rumbo-offset1/--rumbo-offset2` (yaw que publica el Robotat con la nariz a +X): `DroneUnit.yaw_offset_deg` gira cada cuaternión sobre el eje vertical del propio cuerpo (`rotate_quaternion_about_body_z`, multiplicación por la derecha) antes de comprobar el rumbo y de enviarlo con `--extpose`. El mensaje de bloqueo indica el valor a pasar y el preflight evalúa los dos drones antes de abortar. 4 pruebas nuevas; suite completa en verde. Pendiente: medir el offset del Dron 2 y el vuelo de validación.
- 2026-09-12 (claude, noche): corrección de rumbo. El rigid body bueno es el del Dron 2; el del Dron 1 lee ~95° con los drones en paralelo. Nuevo `--alinear-rumbo {drone1,drone2}`: en el preflight, con los dos drones en paralelo, el otro dron toma como offset la diferencia de rumbo con el de referencia (`align_yaw_offset`, `DroneUnit.set_yaw_offset`); `decide_orientation()` pasó de `wait_for_stable_origin` al backend para poder alinear antes de comprobar. 3 pruebas más. Sustituye a los `--rumbo-offset` manuales, que siguen disponibles.
- 2026-09-12 (claude, noche 2): con los drones en su posición de vuelo (paralelos) los markers publican 94.8° y 81.5°: miran a +Y del Robotat, y el catedrático confirma que esa es la colocación correcta. Se descarta obligar la nariz a +X. Nuevo **marco de vuelo por dron** (`DroneUnit.frame_yaw_deg`): el preflight toma el rumbo del marker como +X del EKF; extpos/extpose y `go_to` se rotan a ese marco y `stateEstimate` se desrota. `--rumbo-max-deg` eliminado. Decisión en `30-Decisiones/2026-09-12 Marco de vuelo por dron.md`. Columna `frame_yaw_deg` en el CSV. Pruebas actualizadas.
- 2026-09-12 (claude, cierre): **todo el código de hoy revertido a petición del humano**; `drone_unit.py`, `dual_flight_logger.py` y las pruebas vuelven al estado anterior, y en `cruz_highlevel_backend.py`, `dual_cli.py` y el panel se deshicieron sólo las ediciones de hoy (se conservan los cambios previos de giro y `--backend`). Queda documentado el diseño y las medidas en la nota de análisis, la decisión `2026-09-12 Marco de vuelo por dron` (estado: propuesta) y el README de la cruz. Se conserva `controllers/joystick/ver_markers.py`, que sólo lee MQTT. Estado de vuelta a `pendiente`; los criterios se desmarcan.
