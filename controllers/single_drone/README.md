# Control de un dron

- `buttons/`: panel de botones para un dron; es la interfaz high-level de la cruz con un solo dron habilitado.
- `camera/`: `control_camara_dron1.py`, control mediante cámara y gestos con
  reconocedor (`manos` 2D o `cuerpo` 3D) y backend (`mocap` o `flowdeck`)
  elegibles. Ver [camera/README.md](camera/README.md).

Todo el vuelo con mocap pasa por el backend high-level de `two_drones/cruz_highlevel_backend.py`; el Flow deck usa `two_drones/flowdeck_dual_backend.py`.
