# Control de un dron

- `buttons/`: panel de botones para un dron; es la interfaz high-level de la cruz con un solo dron habilitado.
- `robotat/`: `control_dron_robotat.py`, controlador **desde cero** para un dron con
  mocap (septiembre de 2026): extpos por frame distinto, `--ext-pos-std`, `--param`,
  `--anticipo-s`, órdenes sin solapar y CSV propio. Ver [robotat/README.md](robotat/README.md).
- `camera/`: `control_camara_dron1.py`, control mediante cámara y gestos con
  reconocedor (`manos` 2D, `cuerpo` 3D estático o `vocabulario` completo con
  dinámicos por DTW) y backend (`robotat`, `mocap` o `flowdeck`) elegibles; con
  `--multicamara` usa las seis cámaras IP del `.env` y con `--dron ambos` vuela
  dos drones en formación. Ver [camera/README.md](camera/README.md).
- `hover_flowdeck.py`: prueba de hardware (hover con Flow deck), no un controlador.

`buttons/` y `camera/` eligen cómo vuelan con `--backend`: `robotat` usa el núcleo
`shared/dron_robotat.py` (recomendado desde el 16 de septiembre de 2026), `mocap`
el backend high-level de `two_drones/cruz_highlevel_backend.py` y `flowdeck`
`two_drones/flowdeck_dual_backend.py`.
