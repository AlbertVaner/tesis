# Control de un dron

- `buttons/`: interfaz individual de botones con mocap.
- `camera/`: control mediante cámara y gestos, en 2D por mano y en 3D
  por cuerpo entero. Ver [camera/README.md](camera/README.md).
- `flowdeck/`: hover y panel de teclado con Flow Deck.

El panel de botones reutiliza protecciones y tipos del controlador dual para evitar duplicar lógica de seguridad.
