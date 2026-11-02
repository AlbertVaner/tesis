# Subsistemas externos

Código que funciona sin conocer al Crazyflie. Los controladores de `controllers/`
consumen sus resultados; ellos no importan nada de los controladores ni de la web.

| Carpeta | Contenido |
|---|---|
| [`gesture_detection/`](gesture_detection/README.md) | Cámara (webcam o IP por RTSP), pose y manos con MediaPipe, vocabulario de gestos estáticos (reglas 3D) y dinámicos (DTW), selección entre seis cámaras, seguimiento PTZ del operador, grabación y render HD de sesiones |
| [`mapeo3d/`](mapeo3d/README.md) | Percepción 3D multicámara: captura RTSP, calibración, landmarks 2D y triangulación al marco del Robotat. Se ejecuta desde su carpeta |
| [`crazyflie_firmware/`](crazyflie_firmware/README.md) | Parche del firmware (`range.disable`) para ignorar el Flow deck mientras vuela con el Robotat, y cómo aplicarlo |
