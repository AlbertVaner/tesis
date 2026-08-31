# Vision Campu - Control de gestos por cámara web

## Objetivo del proyecto

Este proyecto es una prueba de concepto para reconocer gestos corporales con cámara web y generar comandos simulados para controlar un dron Crazyflie 2.1. En esta etapa no se conecta al dron real y solo se muestra el comando en pantalla y se guardan registros.

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

## Cómo probar la cámara y el detector

Ejecuta:

```powershell
python .\external\gesture_detection\main_hands.py
```

Si la cámara no abre, cambia `CAMERA_INDEX` en `external/gesture_detection/config.py`.

## Gestos reconocidos

- `DESPEGUE`: ambas manos arriba de los hombros.
- `SUBIR`: mano derecha arriba del hombro derecho.
- `BAJAR`: mano izquierda arriba del hombro izquierdo.
- `DERECHA`: brazo derecho extendido hacia la derecha.
- `IZQUIERDA`: brazo izquierdo extendido hacia la izquierda.
- `STOP`: muñecas cerca entre sí.
- `ATERRIZAJE`: ambas manos debajo de la cadera.
- `REPOSO`: postura neutra.
- `SIN_DETECCION`: no se detecta pose.

## Qué hace el CSV

El archivo `results/data/gesture_detection/<YYYY-MM-DD>/gestos_mano_detectados.csv` guarda un registro de cada frame con:

- timestamp
- command_raw
- command_filtered
- posiciones normalizadas de muñecas y hombros

Sirve para análisis posterior y validación de detección.

## Qué hacer si MediaPipe falla

- Asegúrate de que el entorno virtual tenga `mediapipe` instalado.
- Verifica que usas `py -3.11` y un Python 3.11 compatible.
- Prueba ejecutar `python -c "import mediapipe; print(mediapipe.__version__)"`.

## Nota de seguridad

Esta etapa es solo simulación. No se conecta al dron real, no se envían comandos a motores ni a hardware.
