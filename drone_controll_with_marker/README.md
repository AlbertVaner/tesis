# Control del Crazyflie con marker ROBOTAT

Primero ejecuta `marker_orientation_check.py`. No conecta al dron y permite confirmar que MQTT publica posición y cuaternión, además de identificar los signos de roll y pitch.

```powershell
.\.venv\Scripts\python.exe .\drone_controll_with_marker\marker_orientation_check.py --marker-topic mocap/all --marker-id 64
```

El marker joystick de este proyecto es el rigid body ID `64`, publicado dentro del tópico compartido `mocap/all`. El programa filtra el campo `identifier` para ignorar todos los otros objetos.

Si conoce la ID del rigid body pero no su tópico, descúbralo sin conectar el dron. Para el marker ID 64:

```powershell
.\.venv\Scripts\python.exe .\drone_controll_with_marker\discover_marker_id.py --id 64 --show-all
```

El control de vuelo está en `control_with_marker.py`:

```powershell
.\.venv\Scripts\python.exe .\drone_controll_with_marker\control_with_marker.py --marker-topic mocap/all --marker-id 64
```

Sus protecciones son: marker y dron con MoCap reciente, cero obligatorio, zona muerta angular grande (±12°), límite de velocidad/altura, aterrizaje al bajar el marker más de 10 cm y paro de emergencia.

## Evidencia para la presentación

Cada vez que se presiona **ESTABLECER CERO**, el programa crea un CSV en `datos_marker/`. El archivo registra, a 20 Hz, la pose del marker ID 64, la pose del dron, la altura objetivo, las velocidades enviadas y el comando interpretado (`NEUTRO`, `ADELANTE`, `DERECHA`, `SUBIR`, etc.). Al aterrizar se cierra automáticamente.

Después de una prueba, genere las figuras con:

```powershell
.\.venv\Scripts\python.exe .\drone_controll_with_marker\analyze_marker_session.py
```

Se creará una carpeta `analisis_...` junto al CSV con:

- `01_timeline_comandos.png`: línea de tiempo de los movimientos detectados.
- `02_marker_respuesta_dron.png`: inclinación/altura del marker, objetivo y respuesta del dron.
- `03_trayectoria_xy.png`: trayectoria horizontal coloreada por comando.
- `resumen.txt`: duración, tiempo por comando y eventos de la prueba.

> Ejecuta los programas del proyecto siempre con `.\.venv\Scripts\python.exe`, no con `python`, porque la librería `cflib` está instalada en ese entorno virtual.
