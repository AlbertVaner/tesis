# Comandos para probar los programas

Esta guía reúne los comandos principales de prueba del repositorio. Todos los
comandos, excepto los de `external/mapeo3d`, se ejecutan desde la raíz de
`tesis` en PowerShell.

> **Seguridad:** empieza por las pruebas automáticas y por `--dry-run`. No uses
> los comandos marcados como **HARDWARE REAL** sin confirmar baterías, URI,
> radios, posicionamiento, espacio libre y parada de emergencia.

## 1. Preparar el entorno

Si `.venv` todavía no existe:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
```

En los comandos siguientes se llama directamente al Python del entorno, por lo
que no es necesario activarlo.

## 2. Validación completa sin hardware

Estas son las dos comprobaciones generales que deben pasar antes de abrir una
interfaz o una cámara:

```powershell
.\.venv\Scripts\python.exe -m compileall controllers external web control_dron_camara.py control_dos_drones_camara.py
.\.venv\Scripts\python.exe -m pytest -q
```

Para probar sólo un subsistema:

```powershell
# Control de un dron por cámara
.\.venv\Scripts\python.exe -m pytest -q .\controllers\single_drone\camera\tests

# Control de dos drones
.\.venv\Scripts\python.exe -m pytest -q .\controllers\two_drones\tests

# Joystick con marker
.\.venv\Scripts\python.exe -m pytest -q .\controllers\joystick\tests

# Detección de gestos
.\.venv\Scripts\python.exe -m pytest -q .\external\gesture_detection\tests

# Panel web e integraciones
.\.venv\Scripts\python.exe -m pytest -q .\tests\integration

# Percepción 3D multicámara
.\.venv\Scripts\python.exe -m pytest -q .\external\mapeo3d\tests
```

## 3. Comprobar lanzadores y argumentos

`--help` comprueba que los imports y argumentos cargan sin abrir ventanas,
cámaras, MQTT ni radios:

```powershell
.\.venv\Scripts\python.exe .\control_dron_camara.py --help
.\.venv\Scripts\python.exe .\control_dos_drones_camara.py --help
.\.venv\Scripts\python.exe .\controllers\single_drone\buttons\control_dron_individual_interfaz.py --help
.\.venv\Scripts\python.exe .\controllers\two_drones\control_dos_drones_cruz_botones.py --help
.\.venv\Scripts\python.exe .\web\server.py --help
.\.venv\Scripts\python.exe .\external\gesture_detection\probar_gestos_3d.py --help
.\.venv\Scripts\python.exe .\external\gesture_detection\probar_vocabulario.py --help
.\.venv\Scripts\python.exe .\external\gesture_detection\grabar_vocabulario.py --help
.\.venv\Scripts\python.exe .\external\gesture_detection\construir_plantillas.py --help
.\.venv\Scripts\python.exe .\external\gesture_detection\seguir_persona.py --help
.\.venv\Scripts\python.exe .\controllers\single_drone\hover_flowdeck.py --help
.\.venv\Scripts\python.exe .\controllers\two_drones\diagnostico_flowdeck_dos_drones.py --help
```

## 4. Probar interfaces en simulación

Estos comandos no arman motores. Los programas con interfaz gráfica se quedan
abiertos hasta que cierres la ventana.

```powershell
# Botones para dos drones simulados
.\.venv\Scripts\python.exe .\controllers\two_drones\control_dos_drones_cruz_botones.py --dry-run

# Botones para un solo dron simulado
.\.venv\Scripts\python.exe .\controllers\single_drone\buttons\control_dron_individual_interfaz.py --drone 1 --dry-run

# Variante de dos procesos, sin radio ni Robotat
.\.venv\Scripts\python.exe .\controllers\two_drones\control_dos_drones_cruz_multiprocessing.py --dry-run

# Panel de dos drones habilitando sólo uno
.\.venv\Scripts\python.exe .\controllers\two_drones\control_dos_drones_cruz_botones.py --single drone1 --dry-run

# Panel web simulado; abrir después http://127.0.0.1:8765
.\.venv\Scripts\python.exe .\web\server.py --dry-run
```

En el panel web, `--dry-run` es también el modo predeterminado.

`--dry-run` sólo existe con `--backend mocap`, que es el predeterminado.
`--backend flowdeck` no tiene simulador de deck: siempre conecta radio y va en
la sección 8.

Teclado de los paneles de botones, común a uno y dos drones:

| tecla | dron 1 | dron 2 |
|---|---|---|
| mover | W/A/S/D | flechas |
| subir y bajar | Espacio y Shift | Re Pág y Av Pág |
| girar | Q y E | Inicio y Fin |
| despegar o aterrizar | Enter | Enter |
| **paro de emergencia** | **R** | **R** |

El paro estuvo en `Q` hasta septiembre de 2026. No confundir la `R` de los
paneles con la `q` de las ventanas de cámara, que sólo cierra la ventana.

## 5. Probar cámara y gestos sin vuelo real

Los siguientes comandos abren la webcam, pero no conectan un Crazyflie:

```powershell
# Reconocimiento corporal 3D con explicación de cada regla
.\.venv\Scripts\python.exe .\external\gesture_detection\probar_gestos_3d.py

# Práctica guiada de los nueve gestos
.\.venv\Scripts\python.exe .\external\gesture_detection\probar_gestos_3d.py --practica --semilla 7

# Vocabulario completo con dron simulado
.\.venv\Scripts\python.exe .\external\gesture_detection\probar_vocabulario.py

# Control de un dron: sólo reconoce y muestra comandos; no vuela sin --volar
.\.venv\Scripts\python.exe .\control_dron_camara.py

# Reconoce gestos y ejercita el backend mocap simulado
.\.venv\Scripts\python.exe .\control_dron_camara.py --volar --dry-run

# Cámara de dos drones con backend simulado
.\.venv\Scripts\python.exe .\control_dos_drones_camara.py --dry-run
```

También se puede usar un video en vez de la webcam:

```powershell
.\.venv\Scripts\python.exe .\external\gesture_detection\probar_gestos_3d.py --video .\ruta\video.mp4 --sin-espejo
.\.venv\Scripts\python.exe .\external\gesture_detection\probar_vocabulario.py --video .\ruta\video.mp4 --sin-espejo
```

O una cámara IP por RTSP; el lector fuerza TCP y lee en un hilo aparte para
no acumular latencia. Sustituir la URL por la de la cámara y no dejarla escrita
con usuario y contraseña en archivos versionados:

```powershell
# Una vez por cámara: sub-stream 640x480 @ 30 fps sin audio (latencia 200-350 ms en vez de ~800). Sin --aplicar sólo muestra.
.\.venv\Scripts\python.exe .\external\gesture_detection\configurar_camara.py --rtsp "rtsp://USUARIO:CLAVE@IP:554/cam/realmonitor?channel=1&subtype=1" --aplicar
.\.venv\Scripts\python.exe .\external\gesture_detection\probar_gestos_3d.py --rtsp "rtsp://USUARIO:CLAVE@IP:554/cam/realmonitor?channel=1&subtype=1"
.\.venv\Scripts\python.exe .\external\gesture_detection\probar_vocabulario.py --rtsp "rtsp://USUARIO:CLAVE@IP:554/cam/realmonitor?channel=1&subtype=1"
```

En las ventanas de cámara, normalmente `q` sale, `r` reinicia el reconocedor y
`Esc` solicita una parada de emergencia cuando el controlador la admite.

### 5.1 Grabar y construir el vocabulario de gestos

Los tres pasos, en orden. Ninguno conecta un Crazyflie:

```powershell
# 1. Grabar a una persona nueva: 54 tomas guiadas, 10-15 min,
#    en results\data\gestos\<fecha de hoy>
.\.venv\Scripts\python.exe .\external\gesture_detection\grabar_vocabulario.py --persona nombre
.\.venv\Scripts\python.exe .\external\gesture_detection\grabar_vocabulario.py --solo senalero,circulo
.\.venv\Scripts\python.exe .\external\gesture_detection\grabar_vocabulario.py --sin-negativos

# 2. Construir el banco DTW en models\plantillas_vocabulario.npz y validar
#    dejando fuera a cada persona; CSV en results\data\validacion_dtw\<fecha>
.\.venv\Scripts\python.exe .\external\gesture_detection\construir_plantillas.py

# 3. Probar en vivo el banco recién construido, guardando los segmentos
.\.venv\Scripts\python.exe .\external\gesture_detection\probar_vocabulario.py --guardar-segmentos --persona nombre
```

Sin argumentos, `construir_plantillas.py` usa las sesiones que enumera
`CARPETAS_VOCABULARIO` en su cabecera. Al grabar otro día hay que añadir esa
fecha ahí; no apuntar a `results\data\gestos` entera, porque las sesiones del
5 y 6 de septiembre traen etiquetas viejas. Los detalles están en el
[README de gestos](../external/gesture_detection/README.md).

### 5.2 Seguimiento PTZ de la persona con la cámara IP

`seguir_persona.py` cierra el lazo entre la pose 2D y el pan/tilt de la cámara
Amcrest. Con `--dry-run` valida el lazo entero e imprime lo que enviaría sin
mover los motores:

```powershell
.\.venv\Scripts\python.exe .\external\gesture_detection\seguir_persona.py --rtsp "rtsp://USUARIO:CLAVE@IP:554/cam/realmonitor?channel=1&subtype=1" --dry-run
```

Sin `--dry-run` la cámara se mueve de verdad. Eso invalida cualquier
calibración extrínseca previa de `external/mapeo3d` sin síntoma visible; ver
`external/gesture_detection/ptz/cliente.py`. Teclas: `q` sale y `espacio`
pausa el seguimiento sin cerrar.

## 6. Probar lectura del Robotat sin conectar drones

Estos programas sólo leen MQTT. No conectan radio ni mandan órdenes de vuelo:

```powershell
# Ver los dos rigid bodies a la vez: posicion, roll/pitch/yaw, Hz y diferencia de rumbo
.\.venv\Scripts\python.exe .\controllers\joystick\ver_markers.py


# Descubrir el rigid body del joystick
.\.venv\Scripts\python.exe .\controllers\joystick\discover_marker_id.py --id 64 --show-all

# Revisar posición, cuaternión y signos de roll/pitch
.\.venv\Scripts\python.exe .\controllers\joystick\marker_orientation_check.py --marker-topic mocap/all --marker-id 64
```

## 7. Probar `external/mapeo3d`

Por el contrato propio de este subsistema, sus aplicaciones se ejecutan desde
su carpeta:

```powershell
Set-Location .\external\mapeo3d

# Sintaxis y pruebas sin cámaras
..\..\.venv\Scripts\python.exe -m compileall src apps
..\..\.venv\Scripts\python.exe -m pytest tests -q

# Demostración con la webcam del portátil
..\..\.venv\Scripts\python.exe .\apps\demo_pose3d.py

# Comprobar una webcam y medir sus FPS
..\..\.venv\Scripts\python.exe .\apps\check_stream.py --url 0

Set-Location ..\..
```

Para una cámara IP ya configurada en
`external/mapeo3d/config/cameras.local.yaml`:

```powershell
Set-Location .\external\mapeo3d
..\..\.venv\Scripts\python.exe .\apps\check_connection.py --camera cam1
..\..\.venv\Scripts\python.exe .\apps\check_stream.py --camera cam1
Set-Location ..\..
```

No escribas una URL RTSP con usuario y contraseña en archivos versionados ni
en capturas de consola.

## 8. HARDWARE REAL: ejecutar sólo con autorización y preflight

Los siguientes comandos sí pueden conectar radios y habilitar vuelo. No forman
parte de la validación automática.

### Flow deck, en orden

```powershell
# 1. Diagnóstico de los dos decks: conecta radio y nunca arma motores.
#    Levantar y mover cada dron con la mano sobre suelo con textura.
.\.venv\Scripts\python.exe .\controllers\two_drones\diagnostico_flowdeck_dos_drones.py
.\.venv\Scripts\python.exe .\controllers\two_drones\diagnostico_flowdeck_dos_drones.py --radio1 SERIAL1 --radio2 SERIAL2 --tiempo 6

# 2. Hover mínimo de un dron sólo con el deck: despega, mantiene y aterriza.
#    R corta motores en el acto; Ctrl+C aterriza de forma normal.
.\.venv\Scripts\python.exe .\controllers\single_drone\hover_flowdeck.py --drone 1
.\.venv\Scripts\python.exe .\controllers\single_drone\hover_flowdeck.py --drone 2 --altura 0.4 --tiempo 8

# 3. Paneles de botones con Flow deck: sin --dry-run, sin geocerca
#    ni separación mínima entre drones
.\.venv\Scripts\python.exe .\controllers\single_drone\buttons\control_dron_individual_interfaz.py --drone 1 --backend flowdeck
.\.venv\Scripts\python.exe .\controllers\two_drones\control_dos_drones_cruz_botones.py --backend flowdeck

# 4. Dos drones por cámara con Flow deck
.\.venv\Scripts\python.exe .\control_dos_drones_camara.py --backend flowdeck
```

### Mocap y cámara

```powershell
# Un dron por cámara y mocap
.\.venv\Scripts\python.exe .\control_dron_camara.py --volar --rumbo 90

# Un dron por gestos de mano y Flow Deck
.\.venv\Scripts\python.exe .\control_dron_camara.py --reconocedor manos --backend flowdeck --volar

# Botones para dos drones con mocap
.\.venv\Scripts\python.exe .\controllers\two_drones\control_dos_drones_cruz_botones.py

# Botones para un solo dron con mocap
.\.venv\Scripts\python.exe .\controllers\single_drone\buttons\control_dron_individual_interfaz.py --drone 1

# Panel web habilitado para seleccionar hardware real
.\.venv\Scripts\python.exe .\web\server.py --hardware
```

Antes de despegar:

1. Confirmar las URI y Crazyradio asignadas a cada dron.
2. Confirmar baterías, hélices, zona despejada y mecanismo de parada.
3. Con mocap, confirmar tópicos, pose fresca, ejes y alineación EKF–Robotat.
4. Con Flow Deck, confirmar que el deck está instalado y que el suelo tiene
   textura e iluminación suficientes.
5. Ejecutar primero el preflight sin pulsar despegue.

## Referencias detalladas

- [Control de un dron por cámara](../controllers/single_drone/camera/README.md)
- [Control high-level de dos drones](../controllers/two_drones/README_CONTROL_CRUZ_PYTHON.md)
- [Joystick con marker](../controllers/joystick/README.md)
- [Panel web](../web/README.md)
- [Detección de gestos](../external/gesture_detection/README.md)
- [Percepción 3D multicámara](../external/mapeo3d/README.md)
