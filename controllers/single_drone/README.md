# Control de un dron

- `buttons/`: panel de botones para un dron; es la interfaz high-level de la cruz con un solo dron habilitado.
- `robotat/`: `control_dron_robotat.py`, controlador **desde cero** para un dron con
  mocap (septiembre de 2026): extpos por frame distinto, `--ext-pos-std`, `--param`,
  `--anticipo-s`, órdenes sin solapar y CSV propio. Ver [robotat/README.md](robotat/README.md).
- `camera/`: `control_camara_dron1.py`, control mediante cámara y gestos con
  reconocedor (`manos` 2D, `cuerpo` 3D estático o `vocabulario` completo con
  dinámicos por DTW) y backend (`mocap` o `flowdeck`) elegibles. Ver
  [camera/README.md](camera/README.md).

`buttons/` y `camera/` vuelan con mocap a través del backend high-level de `two_drones/cruz_highlevel_backend.py`; el Flow deck usa `two_drones/flowdeck_dual_backend.py`. `robotat/` es independiente de ambos y está en evaluación.
