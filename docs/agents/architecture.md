# Arquitectura actual

## Flujo principal

```text
lanzadores raíz, paneles Tk, web/
        |
        +---- controllers/single_drone/{buttons,camera}/
        +---- controllers/two_drones/  (entrypoints duales)
        +---- controllers/joystick/    (marker como joystick, marker 65)
                         |
                         v
         los dos backends de vuelo, en controllers/two_drones/
           cruz_highlevel_backend.py   (mocap Robotat, commander high-level)
           flowdeck_dual_backend.py    (Flow Deck, MotionCommander)
                         |
                         +---- controllers/shared/         (radios, Robotat, EKF, teclado, CSV)
                         +---- external/gesture_detection/ (visión, sin Crazyflie)
                         +---- cflib, cámara, MQTT/mocap
                         v
                 results/data/ y results/graphs/
```

## Los dos backends

**Mocap: `controllers/two_drones/cruz_highlevel_backend.py`.** `HardwareBackend`
abre las radios, espera un origen Robotat estable, configura el EKF con posición
externa (`shared/crazyflie_link.configure_estimator`), alinea EKF y mocap y
después sólo manda `takeoff`, `go_to`, `land` y `stop` al commander high-level
del firmware. Valida geocerca, ventana de altura, separación entre drones, mocap
fresco y error EKF. `SimulatedBackend` reproduce la misma interfaz sin hardware
para `--dry-run`. El estado de cada dron (pose MQTT, `extpos`, telemetría EKF,
preflight) vive en `drone_unit.py`. Consumidores: botones dual e individual,
cámara de la cruz (`control_dos_drones_cruz_camara_multiprocessing.py`), el panel
web (`experiment_session.py`) y el controlador por cámara de un dron a través de
`single_drone/camera/highlevel_flight.py`, que convierte la intención de
velocidad de la visión en pasos `go_to` acotados.

**Flow Deck: `controllers/two_drones/flowdeck_dual_backend.py`.** Un
`FlowDroneController` por dron, con un hilo dueño de la radio y del
`MotionCommander`. Opcionalmente registra la altura para imponer techo y piso,
detiene el movimiento sin órdenes frescas (deadman) y aterriza por silencio.
Consumidor: el controlador por cámara de un dron con `--backend flowdeck`. Los
paneles y el hover dedicados al Flow Deck se eliminaron en septiembre de 2026.

No existe ningún otro lazo de vuelo. El low-level sobre mocap se eliminó en
septiembre de 2026; ver `refactor_2026-09.md`.

## Un dron

`controllers/single_drone/` se divide por interfaz. `buttons/` es la interfaz
de la cruz con un solo dron habilitado. `camera/control_camara_dron1.py` es el
único controlador por cámara: reconocedor `cuerpo` (vocabulario 3D) o `manos`
(2D), backend `mocap` o `flowdeck`; comparte bucle, panel, CSV, gráfica de
comandos, STOP sostenido y seguimiento del marker 65.

## Compartido

`controllers/shared/` concentra lo que antes se repetía: identidad del Robotat
(`robotat.py`), radios y URIs (`radios.py`), configuración del estimador y corte
de motores (`crazyflie_link.py`), preparación con Flow deck (`flowdeck_flight.py`),
selección de realimentación del deck (`flowdeck_feedback.py`, que exige el
[parche de firmware](../../external/crazyflie_firmware/README.md)), teclado Tk
(`tk_keys.py`), registros CSV (`csv_session.py`) y captura de GUI a PDF.

`controllers/joystick/marker_follow.py` es la fuente común del seguimiento
tridimensional del marker 65 a 0.45 m; sólo recibe y transforma poses. En
high-level, `two_drones/camera_marker_runtime.py` convierte el objetivo en pasos
`follow_move` protegidos. `marker_input.py` traduce la inclinación del marker
joystick a una intención de velocidad que consume el panel web.

`web/server.py` compone `two_drones/experiment_session.py`, que manda al backend
high-level; registro y exportación pertenecen a `session_recording.py`.

## Dirección permitida

- Lanzadores, paneles y web -> controladores -> backends -> cflib, MQTT, cámara.
- `single_drone/` puede importar de `two_drones/`; nunca al revés.
- Todo puede importar de `shared/` y de `external/gesture_detection/`.
- Nunca: detección gestual -> controladores, controladores -> web, runtime -> tesis.

`control_dron_camara.py` y `control_dos_drones_camara.py` se conservan en la raíz
como lanzadores de conveniencia.
