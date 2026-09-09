# Mapeo tridimensional con cámaras

Sistema de percepción 3D del operador para la tesis *Control de drones basado en gestos mediante captura de movimiento en el ecosistema Robotat*.

Varias cámaras IP observan a la persona desde ángulos distintos. El sistema estima su esqueleto en cada imagen, combina esas vistas por triangulación, y produce **la posición 3D de las articulaciones en el mismo sistema de coordenadas en el que vuela el dron**.

Eso es lo que permite que el dron y la persona se entiendan en el espacio: no sólo "el brazo está inclinado", sino "la mano está en este punto del laboratorio, a esta distancia del dron".

## Qué hace y qué no

**Hace:** leer las cámaras, calibrarlas, detectar el cuerpo en 2D, triangular a 3D, filtrar y publicar el resultado.

**No hace:** reconocer gestos, decidir comandos, ni volar. Eso vive en `controllers/` del repositorio `tesis`, del que este subsistema forma parte desde septiembre de 2026 (carpeta `external/mapeo3d/`).

Este subsistema y los controladores no comparten código: se comunican por un contrato de datos. Todos los comandos de este README se ejecutan desde `external/mapeo3d/`.

## Estado

En construcción, pero ya no es sólo andamiaje. Están implementados:

| Etapa | Estado |
|---|---|
| **Captura** | lectura RTSP sin latencia acumulada, reconexión, estadísticas y sincronización multicámara con compensación de sesgo |
| **Calibración** | intrínsecos, tablero, campo de visión, extrínsecos estéreo y detección de que una cámara se movió durante la sesión |
| **Pose 2D** | MediaPipe Pose sobre la Tasks API, una instancia por cámara |
| **Triangulación** | DLT de N vistas, ponderación por confianza, rechazo de vistas que alucinan y validación por longitud de huesos |

Falta el anclaje de los extrínsecos al marco del Robotat, el filtrado temporal,
la publicación del contrato de salida, y las apps que compongan todo eso.

El siguiente entregable es el **anclaje al marco del Robotat contra un blanco
que el MoCap rastree**: con seis cámaras en anillo el estéreo por tablero no
escala, porque dos cámaras opuestas nunca ven la misma cara del tablero. Ver
[`docs/calibration.md`](docs/calibration.md).

## Hardware

| | Estado |
|---|---|
| **TP-Link Tapo C210** | en uso para las pruebas actuales |
| **Amcrest IP4M-1041B** (×6) | objetivo; disponibles en la Universidad |

Las Amcrest son mejores para el sistema final: dan 30 fps en lugar de 15, tienen puerto Ethernet y permiten configurar el encoder. Los detalles y las restricciones de montaje están en [`docs/hardware.md`](docs/hardware.md).

## Instalación

Se usa el entorno virtual de la raíz del repositorio `tesis`; este subsistema no tiene `.venv` propio. Desde la raíz de `tesis`:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

El `requirements.txt` de esta carpeta sólo remite al de la raíz. Las pruebas se corren desde la raíz con `python -m pytest -q external\mapeo3d\tests` o desde esta carpeta con `python -m pytest -q tests`.

## Configuración de las cámaras

Copiar la plantilla y rellenarla con los datos reales:

```powershell
copy config\cameras.example.yaml config\cameras.local.yaml
```

`config\cameras.local.yaml` **no se versiona**, porque contiene el usuario y la contraseña de las cámaras.

Antes de conectar por primera vez, en la app o interfaz web de cada cámara:

1. **Apagar la visión nocturna** y forzar modo día. Los infrarrojos de las cámaras interfieren con el sistema OptiTrack del Robotat, y viceversa.
2. **Desactivar patrulla y seguimiento automático de movimiento.** Si una cámara se mueve, la calibración deja de ser válida sin que nada lo indique.
3. **Fijar la IP** (o reservarla en el router), o las direcciones RTSP van a cambiar solas.
4. En las Amcrest, además: **desactivar la radio Wi-Fi** una vez cableadas, y fijar la exposición manualmente.

## Uso

### Ver el sistema funcionando

Lo más rápido para entender qué hace todo esto, o para enseñárselo a alguien:

```powershell
python apps/demo_pose3d.py
```

Usa la cámara del portátil, no necesita calibración ni configuración. Muestra
la cámara con el esqueleto encima, la **reconstrucción 3D girando** y la
calidad de la reconstrucción en vivo, con una franja abajo que marca hasta
dónde llega este repositorio.


### Si una cámara no conecta

```powershell
python apps/check_connection.py --camera cam1
```

Dice **por qué** falla: si el puerto no abre, si las credenciales están mal, o
si la ruta RTSP del modelo declarado no es la de esa cámara. OpenCV no
distingue esos tres casos y los tres se arreglan de forma distinta.

Con una Amcrest nueva, lo más probable es que falte **activarla** (crear la
contraseña de administrador; hasta entonces no levanta RTSP) o que **esté en
otra subred** que el PC. Ver [`docs/hardware.md`](docs/hardware.md).

### Verificar una cámara

Lo primero con cualquier cámara nueva: comprobar que se conecta y medir a cuántos
cuadros por segundo llega de verdad.

```powershell
python apps\check_stream.py --camera cam1
```

O con una dirección directa, sin pasar por la configuración:

```powershell
python apps\check_stream.py --url rtsp://usuario:clave@192.168.1.50:554/stream1
python apps\check_stream.py --url 0        # webcam del portátil
```

Abre una ventana con el vídeo y los fps en pantalla, y al terminar imprime un
resumen. Si los fps recibidos se desvían más de un 10 % de lo esperado, avisa: es
la señal de que la exposición automática está bajando el frame rate por falta de
luz, y es un problema que de otro modo pasa desapercibido.

Con `--no-display` mide sin abrir ventana, útil por escritorio remoto.

Para guardar un frame tal como lo recibe el pipeline —resolución completa, sin
overlay— y poder analizarlo aparte:

```powershell
python apps\check_stream.py --camera cam1 --save-frame
```

Queda en `results\captures\<fecha>\`. Espera unos segundos antes de capturar
para que la exposición automática se estabilice (`--warmup`). Una foto de la
pantalla no sirve para esto: pierde resolución y añade el moiré del monitor.

### Preparar el tablero de calibración

```powershell
python apps\make_chessboard.py
```

Genera `results\tablero.pdf` en A4, con casillas de 23 mm. Para A3 y casillas
más grandes, útil si vas a calibrar a más distancia:

```powershell
python apps\make_chessboard.py --square-mm 35 --paper A3
```

**Imprimilo al 100 %, sin «ajustar a la página».** El PDF trae una regla de
100 mm al pie: medila con una regla de verdad después de imprimir. Si no da
100 mm, la impresión salió escalada y hay que repetirla — un error de escala se
propaga a todas las medidas del sistema sin dar ningún síntoma.

**Pegalo a algo rígido y plano** — foam board, MDF, un portapapeles, un vidrio —
y **apoyalo en un soporte** en lugar de sostenerlo a mano. Las dos cosas por la
misma razón: el ajuste supone que el tablero es plano y está quieto, y una hoja
sostenida a pulso no es ni lo uno ni lo otro.

Si el informe dice que el error es sistemático, repetí con `--save-frames` y
mirá las imágenes: se ve a simple vista si está combado o movido.

### Calibrar una cámara

```powershell
python apps\calibrate_intrinsics.py --camera cam1 --square-mm 23
```

**Poné el tablero cerca**: tiene que ocupar al menos un 20 % del ancho de la
imagen, e idealmente un 30 %. Con el tablero de carta eso es estar a unos
**0.6 m** de la cámara. Es lo que más determina la calidad de la calibración, y
calibrar desde lejos es el error más caro. La ventana te muestra el porcentaje
en vivo y no captura si estás demasiado lejos.

**Colocá el tablero, soltalo, y esperá a que diga «LISTO».** La app sólo
captura con el tablero quieto: un frame movido contamina el ajuste entero, y
basta con que 4 de 20 lo estén para que el error se triplique.

Captura sola cuando detecta el tablero, y rechaza vistas repetidas para que las
20 capturas sean realmente distintas. Si la vista va lenta, `--detect-width 640`
o `--detect-every 2`. Movelo por todo el cuadro: cerca y lejos,
en las esquinas, inclinado en varias direcciones.

Al terminar guarda la calibración y un informe en
`results\calibration\<fecha>\`, y te dice el **campo de visión real** de la
cámara y a qué distancia tenés que ponerla para que una persona quepa entera.

Si ya tenés fotos tomadas:

```powershell
python apps\calibrate_intrinsics.py --images ruta\a\las\fotos --name cam1
```

### Calibrar la posición entre las dos cámaras

Con los intrínsecos de ambas ya hechos:

```powershell
python apps\calibrate_stereo.py --cameras cam1 cam2 ^
    --intrinsics results\calibration\2026-09-02 --square-mm 24
```

El tablero tiene que verse **en las dos cámaras a la vez** y estar quieto.
Acá no hace falta que se vea grande: con el 8 % del ancho basta, frente al 20 %
que exigen los intrínsecos. Son problemas distintos — allá se estima la focal,
acá sólo la posición relativa, y eso se determina con muchísimo menos.
Colocalo en la zona que ambas ven, soltalo, esperá a que diga «LISTO», movelo a
otra posición, repetí unas 18 veces.

**No toques las cámaras durante la sesión** — ni desde la app del teléfono.
Si una se mueve a mitad de captura, los pares de antes y los de después
describen geometrías distintas y no hay calibración posible. La app lo detecta
sola: avisa en pantalla en cuanto ocurre, y al terminar se niega a calibrar
diciendo en qué par cambió la geometría, en lugar de devolver un número malo
con pinta de bueno.

Al terminar te dice la distancia entre las cámaras y, lo más importante,
**triangula los tableros y mide la casilla reconstruida**: si el tablero es de
24 mm y la reconstrucción da 24 mm, toda la cadena está bien. Es la única
comprobación absoluta que hay — un error de escala no aparece en ningún otro
número.

Si sabés que las cámaras no se movieron y querés recalibrar desde unos pares
concretos ya guardados:

```powershell
python apps\calibrate_stereo.py --from-points results\...\pares_cam1_cam2_005118.npz ^
    --intrinsics results\calibration\2026-09-02 --solo-pares 0 2 3 4 5 8
```

### Resto del flujo

Las demás aplicaciones todavía no existen. Se documentan en
[`docs/operations.md`](docs/operations.md) conforme se implementen.

El orden de trabajo previsto es:

1. Diagnosticar cada cámara — fps, latencia, campo de visión, ruido.
2. Calibrar los parámetros internos de cada cámara con un tablero.
3. Calibrar la posición de las cámaras usando el Crazyflie como referencia, ya que el sistema de captura de movimiento conoce su posición exacta.
4. Verificar la calibración antes de cada sesión.
5. Grabar sesiones y correr el pipeline completo.

## Documentación

La documentación técnica está en [`docs/`](docs/README.md). Está escrita tanto para personas como para agentes de IA que trabajen sobre el código.

- [Arquitectura y contrato de salida](docs/architecture.md)
- [Captura RTSP y sincronización](docs/capture.md)
- [Calibración y marco de coordenadas](docs/calibration.md)
- [Triangulación y filtrado](docs/triangulation.md)
- [Hardware, red y montaje](docs/hardware.md)
- [Operación, resultados y validación](docs/operations.md)

Si vas a modificar el código —o a pedirle a un agente que lo haga— empieza por [`AGENTS.md`](AGENTS.md).

## Advertencias

**Las cámaras son pan/tilt motorizadas.** Si una se mueve, aunque sea desde la app del teléfono, la calibración queda inválida y el sistema sigue produciendo números que parecen correctos y no lo son. Por eso hay una verificación de integridad que corre antes de cada sesión, y por eso conviene no tocarlas.

**Este sistema no es responsable de la seguridad del vuelo.** No impone límites de velocidad, altura ni separación. Esos límites viven en el supervisor del repositorio `tesis`, y deben seguir funcionando aunque este sistema se caiga o se quede sin cámaras.
