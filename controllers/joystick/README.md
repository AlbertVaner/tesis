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

El vuelo con el marker joystick se hace desde el panel web (`web/server.py`):
`marker_input.py` lee el marker y produce una intención de velocidad, y la
sesión (`two_drones/experiment_session.py`) la convierte en pasos del backend
high-level de la cruz. `marker_input.py` conserva la zona muerta angular
(±12°), la rampa hasta 28°, la zona muerta vertical y el aterrizaje al bajar el
marker más de 10 cm durante 0.5 s. Ver [web/README.md](../../web/README.md).

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

El CSV y las gráficas de cada sesión con el marker los genera la sesión web
(`two_drones/session_recording.py`) en `results/data/` y `results/graphs/`.

> Ejecuta los programas del proyecto siempre con `.\.venv\Scripts\python.exe`, no con `python`, porque la librería `cflib` está instalada en ese entorno virtual.
