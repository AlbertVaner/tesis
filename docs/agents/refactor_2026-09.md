# Refactorización de septiembre de 2026

Entre el 6 y el 7 de septiembre de 2026 el repositorio pasó de ~21 900 a
~14 500 líneas de Python sin perder funcionalidad de vuelo. Este documento
registra qué se eliminó, qué se fusionó y por qué, para que nadie vuelva a
buscar código que ya no existe.

## Decisiones

1. **Un solo backend con mocap: el high-level de la cruz.** Todo el vuelo con
   el Robotat pasa por `controllers/two_drones/cruz_highlevel_backend.py`, que
   sólo manda `takeoff`, `go_to`, `land` y `stop` al commander high-level del
   firmware. El lazo externo de velocidad (`send_velocity_world_setpoint` con
   un P propio) se eliminó por completo.
2. **Un solo backend con Flow Deck**: `controllers/two_drones/flowdeck_dual_backend.py`,
   para uno o dos drones.
3. **Un solo controlador por cámara para un dron**, con el reconocedor y el
   backend como argumentos.
4. Lo que se repetía en varios archivos vive una vez en `controllers/shared/`.

## Paso 1 — código muerto y limpieza

- Borrado `archive/legacy/` (2 300 líneas que nadie importaba y que ni siquiera
  arrancaban).
- Borrados los huérfanos de `external/gesture_detection/`: el detector corporal
  2D (`gesture_detector.py`), `pose_tracker.py`, `logger_csv.py`, `pose_preview.py`
  con `capture/` y `visualization/hand_metrics.py`, y la rama `features/sequence_buffer.py`
  + `DTWRecognizer`, que sólo usaba su propio test. Su sucesor es
  `recognition/body_3d_rules.py` y `recognition/dinamicos.py`.
- Borrado `docs/build_command_guide.py`; el `.docx` que generaba se conserva como
  documento histórico. El plan de gestos pasó de la raíz a `docs/plan_reconocimiento_gestos_robotat.md`.
- El cache de `cflib` se escribe bajo `./cache/<nombre>/` (ignorado); antes había
  once carpetas `cache*/` en la raíz, cinco de ellas versionadas.

## Paso 2 — utilidades compartidas

Nuevos módulos en `controllers/shared/`: `robotat.py` (broker, tópicos,
timeout del mocap), `radios.py` (seriales, enlaces, URIs, selección de antena),
`crazyflie_link.py` (`configure_estimator`, `reset_kalman`, `arm_if_supported`,
`stop_motors`), `flowdeck_flight.py` (validación del deck, espera del Kalman,
parada con `MotionCommander`), `tk_keys.py` (mixins de teclado) y `csv_session.py`
(base de los registros CSV). En `two_drones/`, `dual_cli.py` unifica los
argumentos `--uri1/--uri2/--topic1/--topic2`. `hover_flowdeck_dron1.py` quedó como
script puro y `two_drones/` dejó de importar de `single_drone/`.

## Paso 3 — fin del low-level y Flow Deck único

- `DroneUnit` salió de `prueba_estabilidad_dos_drones_lowlevel.py` a
  `two_drones/drone_unit.py`, sin el lazo P ni las constantes de control.
- Borrados `prueba_estabilidad_dos_drones_lowlevel.py`, `control_dos_drones_botones_lowlevel.py`,
  `single_drone/camera/mocap_flight.py`, `joystick/control_with_marker.py`
  (`MarkerFlightApp`), `joystick/flight_logger.py` y `joystick/analyze_marker_session.py`.
- `single_drone/buttons/control_dron_individual_interfaz.py` es un envoltorio
  que abre la interfaz de la cruz con `--single`.
- `single_drone/camera/highlevel_flight.py` envuelve el backend de la cruz con
  la interfaz que usan los controladores por cámara: cada gesto de dirección
  es un paso `go_to` de 0.10 m (0.08 m en Z) como máximo cada 1.25 s; el
  seguimiento del marker 65 son pasos `follow_move`; sin órdenes de la cámara
  durante 2 s aterriza.
- `FlowDroneController` absorbió el techo de altura y el aterrizaje por
  silencio que tenía el controlador de cámara; ambos son opcionales en
  `FlowDroneConfig`, así que los paneles de teclado no cambiaron.
- `joystick/marker_input.py` es autónomo y el joystick vuela desde el panel web.

## Paso 4 — un controlador por cámara

`control_camara_flowdeck_dron1.py` (manos, Flow Deck) y `control_corporal_dron1.py`
(cuerpo, mocap o Flow Deck) se fusionaron en `control_camara_dron1.py`:

- `--reconocedor cuerpo|manos` elige la visión. El detector de mano entra por el
  mismo contrato `GestureEvent` que el vocabulario corporal (`evento_de_mano`).
- `--backend mocap|flowdeck` elige el vuelo; `--volar --dry-run` simula el mocap.
- STOP sostenido, seguimiento del marker 65, panel, CSV y gráfica de comandos
  son el mismo código para las cuatro combinaciones.
- La práctica guiada (`--practica`) pasó a `external/gesture_detection/probar_gestos_3d.py`,
  que no necesita dron.
- Los resultados van a `results/{data,graphs}/control_camara_dron1/`.

## Cómo validar

```powershell
python -m compileall controllers external web control_dron_camara.py control_dos_drones_camara.py
python .\controllers\single_drone\camera\tests\test_control_camara.py
python .\controllers\single_drone\camera\tests\test_highlevel_flight.py
python .\controllers\single_drone\camera\tests\test_camera_flight_safety.py
python .\controllers\two_drones\tests\test_ekf_alignment_diagnostic.py
python .\tests\integration\test_flowdeck_feedback.py
python .\tests\integration\test_web_panel.py
```

Ningún test abre cámara, radio ni motores. El cambio de modo de vuelo del
controlador corporal (de velocidad continua a pasos `go_to`) exige una primera
prueba en el Robotat sin hélices y con `--dry-run` antes.

## Pendiente

- Fundir `SimulatedBackend` y `HardwareBackend` en una clase base y unificar
  `move` con `follow_move`.
- Pasar los tests con runner propio a `unittest` con dobles comunes.
- `main_hands.py` y el `.docx` de comandos siguen por decisión explícita.
