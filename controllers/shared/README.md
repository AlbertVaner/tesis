# Utilidades compartidas

Código reutilizable sin lógica de vuelo propia. Cada módulo tiene al menos dos
consumidores de categorías distintas y no depende de UI, cámara ni de un
número concreto de drones.

- `robotat.py`: broker MQTT, tópicos de los drones y del marker, y edad máxima
  de una pose. Única fuente de esos valores en el repositorio.
- `radios.py`: seriales de las Crazyradio, canal/dirección de cada Crazyflie y
  las tres formas de elegir antena (`select_uri`, `resolve_dual_uris`,
  `resolve_serial_uris`).
- `crazyflie_link.py`: `configure_estimator` (EKF con posición externa, low o
  high-level), `reset_kalman`, `arm_if_supported` y `stop_motors` (corte
  repetido, intercalado si son varios drones).
- `flowdeck_flight.py`: validación del Flow deck, espera de convergencia del
  Kalman y parada de emergencia con `MotionCommander`.
- `flowdeck_feedback.py`: selecciona y confirma las mediciones del Flow Deck
  que recibe el estimador. Ver [requisito de firmware y validación](../../external/crazyflie_firmware/README.md).
- `tk_keys.py`: esquema de teclado de los paneles Tkinter (`DualStepKeysMixin`,
  un paso por pulsación, sin autorepeat).
- `csv_session.py`: base de los registros CSV por sesión (carpeta por día,
  reloj relativo, gráficas al cerrar).
- `mocap_feed.py`: suscriptor MQTT de un rigid body del Robotat; entrega cada
  frame distinto, detecta poses congeladas (rastreo perdido) y mide frames/s,
  huecos y latencia. Sin cflib.
- `dron_robotat.py`: **núcleo de vuelo por dron** sobre el Robotat
  (`DronRobotat`, `DronSimulado`): preflight, despegue, pasos, modo fluido por
  velocidad, aterrizaje, vigilancia (mocap, EKF, batería), preajustes de
  ganancias (`GANANCIAS`), memoria del empuje de hover y CSV con gráficas.
  Consumido por `single_drone/robotat/` (panel y cámara) y por
  `two_drones/robotat_backend.py` (todas las interfaces de la cruz con
  `--backend robotat`). Ver `controllers/single_drone/robotat/README.md`.
- `analizar_sesion_robotat.py`: gráficas PDF y resumen de cada sesión de
  `dron_robotat` en `results/graphs/dron_robotat/` (altura, trayectoria,
  EKF y mocap, batería, velocidades, actitud, línea de tiempo de órdenes y
  gestos, vuelo 3D, y los dos drones juntos cuando vuelan a la vez).
- `gui_pdf_capture.py`: captura de interfaces gráficas a PDF.

Todos los controladores escriben el cache de `cflib` bajo `./cache/<nombre>/`.
