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
- `gui_pdf_capture.py`: captura de interfaces gráficas a PDF.

Todos los controladores escriben el cache de `cflib` bajo `./cache/<nombre>/`.
