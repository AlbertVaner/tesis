# Control del Crazyflie con marker ROBOTAT

Primero ejecuta `marker_orientation_check.py`. No conecta al dron y permite confirmar que MQTT publica posición y cuaternión, además de identificar los signos de roll y pitch.

```powershell
.\.venv\Scripts\python.exe .\controllers\joystick\marker_orientation_check.py --marker-topic mocap/all --marker-id 64
```

El marker joystick de este proyecto es el rigid body ID `64`, publicado dentro del tópico compartido `mocap/all`. El programa filtra el campo `identifier` para ignorar todos los otros objetos.

Si conoce la ID del rigid body pero no su tópico, descúbralo sin conectar el dron. Para el marker ID 64:

```powershell
.\.venv\Scripts\python.exe .\controllers\joystick\discover_marker_id.py --id 64 --show-all
```

El control de vuelo está en `control_with_marker.py`:

```powershell
.\.venv\Scripts\python.exe .\controllers\joystick\control_with_marker.py --marker-topic mocap/all --marker-id 64
```

Sus protecciones son: marker y dron con MoCap reciente, cero obligatorio, zona muerta angular grande (±12°), límite de velocidad/altura, aterrizaje al bajar el marker más de 10 cm y paro de emergencia.

`marker_follow.py` implementa una función distinta para los controladores de
cámara: el marker Robotat ID 65 actúa como referencia tridimensional. El gesto
de dedo medio activa el seguimiento en X, Y y Z a 0.45 m del marker; el símbolo
de rock lo cancela. La velocidad se limita a 0.10 m/s, cada paso high-level a
0.025 m y cada transición dura 0.75 s. El marker puede recorrer el volumen de
Robotat sin una geocerca respecto al origen. Una pose con más de 0.75 s cancela
el seguimiento. Con dos drones, una esfera de exclusión impide que sus centros
se acerquen a menos de 0.30 m.

La configuración Robotat excluye las mediciones de flujo óptico y ToF del
Flow Deck antes de reiniciar el EKF. Con el deck conectado requiere el
[parche de firmware](../../external/crazyflie_firmware/README.md) que añade
`range.disable`; sin esa capacidad confirmada se bloquea la preparación.

## Evidencia para la presentación

Cada vez que se presiona **ESTABLECER CERO**, el programa crea un CSV en `datos_marker/`. El archivo registra, a 20 Hz, la pose del marker ID 64, la pose del dron, la altura objetivo, las velocidades enviadas y el comando interpretado (`NEUTRO`, `ADELANTE`, `DERECHA`, `SUBIR`, etc.). Al aterrizar se cierra automáticamente.

Al terminar la sesión, las figuras PDF se generan automáticamente. También
puede regenerarlas manualmente con:

```powershell
.\.venv\Scripts\python.exe .\controllers\joystick\analyze_marker_session.py
```

Se creará una carpeta `results/graphs/marker/<YYYY-MM-DD>/sesion_marker_...` con:

- `01_timeline_comandos.pdf`: línea de tiempo de los comandos interpretados.
- `02_movimiento_joystick.pdf`: roll, pitch y desplazamiento vertical en el tiempo.
- `03_comandos_velocidad.pdf`: VX, VY y VZ realmente enviados al dron.
- `04_trayectoria_xy.pdf`: trayectoria horizontal coloreada por comando.
- `resumen.txt`: duración, tiempo por comando y eventos de la prueba.

> Ejecuta los programas del proyecto siempre con `.\.venv\Scripts\python.exe`, no con `python`, porque la librería `cflib` está instalada en ese entorno virtual.
