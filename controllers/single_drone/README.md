# Control de un dron

- `buttons/`: panel de botones para un dron; es la interfaz high-level de la cruz con un solo dron habilitado.
- `camera/`: control mediante cámara y gestos, en 2D por mano y en 3D
  por cuerpo entero. Ver [camera/README.md](camera/README.md).
- `flowdeck/`: hover y panel de teclado con Flow Deck.

Todo el vuelo con mocap pasa por el backend high-level de `two_drones/cruz_highlevel_backend.py`; el Flow deck usa `two_drones/flowdeck_dual_backend.py`.
