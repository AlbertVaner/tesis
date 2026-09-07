# Utilidades compartidas

Código reutilizable sin lógica de vuelo propia.

- `gui_pdf_capture.py`: captura de interfaces gráficas a PDF.
- `flowdeck_feedback.py`: selecciona y confirma las mediciones del Flow Deck
  que recibe el estimador. Lo consumen control dual, joystick Robotat y Flow
  Deck individual; no depende de UI, MQTT, cflib ni de un número de drones.
  Ver [requisito de firmware y validación](../../external/crazyflie_firmware/README.md).
