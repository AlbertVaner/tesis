# Detección de gestos por cámara

## Objetivo del proyecto

Este subsistema contiene prototipos de visión que funcionan sin importar controladores de Crazyflie. El modo corporal nuevo combina MediaPipe Pose y MediaPipe Hands; todavía no clasifica gestos ni genera comandos. El detector manual de manos se conserva como prototipo anterior.

Todos los comandos se ejecutan desde la raíz del repositorio.

## Instalación en Windows CMD

1. Abre `cmd` en la raíz del repositorio.
2. Ejecuta:

```bat
py -3.11 -m venv .venv
.\.venv\Scripts\activate.bat
python -m pip install --upgrade pip setuptools wheel
pip install -r .\external\gesture_detection\requirements.txt
```

## Instalación en Windows PowerShell

1. Abre PowerShell en la raíz del repositorio.
2. Ejecuta:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
pip install -r .\external\gesture_detection\requirements.txt
```

## Vista previa corporal nueva

Desde la raíz del repositorio:

```powershell
python .\external\gesture_detection\pose_preview.py
```

El programa:

- busca automáticamente una webcam entre los índices 0 y 5;
- captura video con OpenCV;
- estima la pose con MediaPipe;
- dibuja el esqueleto;
- detecta hasta dos manos y dibuja sus 21 landmarks;
- muestra FPS suavizado;
- muestra la visibilidad de hombros, codos y muñecas;
- muestra confianza de lateralidad, dirección y ángulos de los dedos;
- termina al presionar `Q`.

Para seleccionar una cámara específica:

```powershell
python .\external\gesture_detection\pose_preview.py --camera 1
```

Para ampliar el rango de búsqueda o desactivar la imagen en espejo:

```powershell
python .\external\gesture_detection\pose_preview.py --max-camera-index 8 --no-mirror
```

La visibilidad mostrada pertenece a cada landmark corporal. MediaPipe Pose no entrega una única confianza global de pose, por lo que el panel presenta el promedio de los seis landmarks principales únicamente como diagnóstico visual.

Para cada mano se presentan tres ángulos por dedo, en el orden proximal/medio/distal. Un valor cercano a 180 grados representa una articulación aproximadamente extendida; valores menores indican mayor flexión. `T`, `I`, `M`, `A` y `m` representan pulgar, índice, medio, anular y meñique. La confianza junto a `Left` o `Right` corresponde a la clasificación de lateralidad de MediaPipe, no a una confianza global de toda la mano.

Los ángulos usan las coordenadas 3D relativas estimadas por una webcam RGB. Son apropiados para comparar posturas y construir el dataset, pero no equivalen a grados anatómicos calibrados.

### Organización del modo corporal

```text
pose_preview.py              composición y ciclo de ejecución
capture/webcam.py            selección y lectura de webcam
pose/detector.py             inferencia de MediaPipe Pose
visualization/pose_overlay.py dibujo y métricas en pantalla
visualization/hand_metrics.py cálculo y panel de ángulos de dedos
```

`pose_tracker.py` conserva la interfaz anterior como adaptador, pero reutiliza la implementación nueva para evitar dos detectores corporales distintos.

## Detector manual de manos (modo anterior)

Ejecuta:

```powershell
python .\external\gesture_detection\main_hands.py
```

Si la cámara no abre, cambia `CAMERA_INDEX` en `external/gesture_detection/config.py`. Esta configuración corresponde solamente al modo anterior; `pose_preview.py` usa detección automática o el argumento `--camera`.

## Gestos reconocidos por el modo anterior

- `DESPEGAR`: índice y medio extendidos, con la mano hacia arriba.
- `ATERRIZAR`: índice y medio extendidos, con la mano hacia abajo.
- `STOP`: puño cerrado.
- `DERECHA`: pulgar extendido y los demás dedos cerrados.
- `IZQUIERDA`: meñique extendido, con la mano hacia arriba.
- `ARRIBA` y `ABAJO`: índice extendido y orientación correspondiente.
- `ADELANTE`: pulgar e índice extendidos.
- `ATRAS`: pulgar y meñique extendidos.
- `REPOSO` y `SIN_DETECCION`: estados sin comando activo.

## CSV del modo anterior

El archivo `results/data/gesture_detection/<YYYY-MM-DD>/gestos_mano_detectados.csv` guarda un registro de cada frame con:

- timestamp
- command_raw
- command_filtered
- orientación y estado extendido de cada dedo
- posiciones normalizadas de la muñeca y las puntas de los dedos

Sirve para análisis posterior y validación de detección.

## Qué hacer si MediaPipe falla

- Asegúrate de que el entorno virtual tenga `mediapipe` instalado.
- Verifica que usas `py -3.11` y un Python 3.11 compatible.
- Prueba ejecutar `python -c "import mediapipe; print(mediapipe.__version__)"`.

## Nota de seguridad

Esta etapa es solo simulación. No se conecta al dron real, no se envían comandos a motores ni a hardware.
