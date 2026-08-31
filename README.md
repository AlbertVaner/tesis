# Control de drones Crazyflie

Repositorio de tesis para experimentar con uno o dos Crazyflies mediante control high-level y low-level, Flow Deck, cámara, gestos, joystick, marker/mocap y una interfaz web local.

## Estructura

| Ruta | Contenido |
|---|---|
| `controllers/single_drone/buttons/` | Panel de botones para un dron |
| `controllers/single_drone/camera/` | Control de un dron mediante cámara y gestos |
| `controllers/single_drone/flowdeck/` | Hover y panel de teclado para un dron con Flow Deck |
| `controllers/two_drones/` | Todo el control de dos drones: botones, cámara, Flow Deck, backends, telemetría y análisis |
| `controllers/joystick/` | Control mediante joystick-marker y mocap |
| `controllers/shared/` | Utilidades compartidas por varios controladores |
| `external/gesture_detection/` | Detección de manos y gestos con cámara |
| `web/` | Servidor y frontend del panel web |
| `results/data/` | CSV y logs generados por nuevas corridas (ignorado por Git) |
| `results/graphs/` | Gráficas y capturas históricas versionadas |
| `results/artifacts/` | Presentaciones y otros artefactos generados |
| `docs/` | Guías e índice técnico para agentes |
| `thesis/` | Fuentes LaTeX y recursos del trabajo escrito |
| `archive/legacy/` | Código histórico; no usar como base para código nuevo |

## Preparación

En PowerShell, desde la raíz:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Algunos experimentos de gestos tienen dependencias adicionales en `external/gesture_detection/requirements.txt`.

## Ejecución

Ejemplos representativos:

```powershell
# Simulación de la cruz con dos drones, sin conectar hardware
python .\controllers\two_drones\control_dos_drones_cruz_botones.py --dry-run

# Control por cámara y multiprocesamiento
python .\control_dos_drones_camara.py --dry-run

# Panel web local
python .\web\server.py
```

Antes de un vuelo real, confirma URI/radio, espacio libre, baterías, sistema de posicionamiento y mecanismo de parada. Usa `--dry-run` cuando el controlador lo ofrezca.

La guía detallada de la cruz está en [controllers/two_drones/README_CONTROL_CRUZ_PYTHON.md](controllers/two_drones/README_CONTROL_CRUZ_PYTHON.md). Para contribuir o trabajar con agentes, consulta [AGENTS.md](AGENTS.md).
