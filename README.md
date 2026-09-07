# Control de drones Crazyflie

Repositorio de tesis para volar uno o dos Crazyflies con el Robotat (captura de
movimiento) o con Flow Deck, mandándolos por botones, teclado, cámara y gestos,
un marker usado como joystick o un panel web local.

Hay exactamente **dos backends de vuelo**, y todo controlador usa uno de los dos:

| Backend | Posicionamiento | Cómo vuela | Archivo |
|---|---|---|---|
| High-level de la cruz | mocap del Robotat por MQTT + `extpos` | `takeoff`, `go_to`, `land` del commander high-level del firmware | `controllers/two_drones/cruz_highlevel_backend.py` |
| Flow Deck | Flow deck v2, sin referencia externa | `MotionCommander` con velocidad | `controllers/two_drones/flowdeck_dual_backend.py` |

No existe ningún lazo de velocidad propio sobre el mocap: el low-level se
eliminó en septiembre de 2026. Ver [docs/agents/refactor_2026-09.md](docs/agents/refactor_2026-09.md).

## Estructura

| Ruta | Contenido |
|---|---|
| `controllers/single_drone/buttons/` | Panel de botones para un dron: la interfaz de la cruz con un solo dron habilitado |
| `controllers/single_drone/camera/` | `control_camara_dron1.py`: un solo controlador por cámara, con reconocedor (`cuerpo` 3D o `manos` 2D) y backend (`mocap` o `flowdeck`) elegibles |
| `controllers/single_drone/flowdeck/` | Hover y panel de teclado para un dron con Flow Deck |
| `controllers/two_drones/` | Los dos backends, el estado del dron sobre el Robotat (`drone_unit.py`), botones, cámara, multiproceso, telemetría y análisis de dos drones |
| `controllers/joystick/` | Marker Robotat como joystick (`marker_input.py`) y seguimiento del marker 65 (`marker_follow.py`) |
| `controllers/shared/` | Radios, identidad del Robotat, configuración del EKF, teclado Tk, CSV de sesión y captura de GUI |
| `external/gesture_detection/` | Visión: vocabulario 3D de cuerpo entero, gestos de mano 2D, banco de pruebas y grabación de gestos |
| `web/` | Servidor y frontend del panel web, que manda al backend high-level |
| `results/data/` | CSV y logs generados por nuevas corridas (ignorado por Git) |
| `results/graphs/` | Gráficas y capturas versionadas |
| `results/artifacts/` | Presentaciones y otros artefactos generados |
| `docs/` | Documentación para agentes, plan de gestos y registro de cambios |
| `thesis/` | Fuentes LaTeX y recursos del trabajo escrito |

## Preparación

En PowerShell, desde la raíz:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Ejecuta siempre los programas con `.\.venv\Scripts\python.exe`: `cflib` está
instalada en ese entorno.

## Ejecución

```powershell
# Leer el vocabulario corporal con la webcam, sin dron ni radio
python .\control_dron_camara.py

# Recorrido guiado por los nueve gestos, con acierto y latencia (sin dron)
python .\external\gesture_detection\probar_gestos_3d.py --practica

# Volar el Dron 1 por gestos corporales sobre el backend high-level (simulado)
python .\control_dron_camara.py --volar --dry-run

# Lo mismo con hardware, mirando hacia +Y del Robotat
python .\control_dron_camara.py --volar --rumbo 90

# Gestos de una mano en 2D sobre Flow Deck
python .\control_dron_camara.py --reconocedor manos --backend flowdeck --volar

# Botones: dos drones (simulado) y un solo dron
python .\controllers\two_drones\control_dos_drones_cruz_botones.py --dry-run
python .\controllers\single_drone\buttons\control_dron_individual_interfaz.py --drone 1

# Cámara con dos manos para dos drones, backend en otro proceso
python .\control_dos_drones_camara.py --dry-run

# Panel web local
python .\web\server.py
```

Antes de un vuelo real, confirma URI/radio, espacio libre, baterías, sistema de
posicionamiento y mecanismo de parada. Usa `--dry-run` cuando el controlador lo
ofrezca: simula el backend high-level sin radio ni mocap.

## Validación sin hardware

```powershell
python -m compileall controllers external web control_dron_camara.py control_dos_drones_camara.py
python .\controllers\single_drone\camera\tests\test_control_camara.py
python .\controllers\single_drone\camera\tests\test_highlevel_flight.py
python .\controllers\single_drone\camera\tests\test_camera_flight_safety.py
python .\tests\integration\test_flowdeck_feedback.py
python .\tests\integration\test_web_panel.py
```

Cada carpeta con `tests/` tiene sus propios scripts; ninguno abre cámara, radio ni motores.

La guía de la cruz está en [controllers/two_drones/README_CONTROL_CRUZ_PYTHON.md](controllers/two_drones/README_CONTROL_CRUZ_PYTHON.md)
y la del controlador por cámara en [controllers/single_drone/camera/README.md](controllers/single_drone/camera/README.md).
Para contribuir o trabajar con agentes, consulta [AGENTS.md](AGENTS.md).
