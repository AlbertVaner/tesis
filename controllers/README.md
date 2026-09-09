# Controladores

- `single_drone/buttons/`: panel de botones para un dron.
- `single_drone/camera/`: `control_camara_dron1.py`, control por cámara y gestos para un dron (manos 2D o cuerpo 3D, mocap high-level o Flow Deck).
- `two_drones/`: los dos backends de vuelo (`cruz_highlevel_backend.py`, `flowdeck_dual_backend.py`) y todo lo específico de dos drones: botones, cámara, multiprocesamiento, logs y análisis.
- `joystick/`: control mediante marker/mocap usado como joystick.
- `shared/`: utilidades comunes, sin lógica de vuelo propia.

Consulta `../docs/agents/architecture.md` para las dependencias entre categorías.
