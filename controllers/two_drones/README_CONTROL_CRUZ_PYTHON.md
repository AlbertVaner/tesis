# Control high-level por botones — Python

Es el único backend de vuelo con mocap del repositorio. Sigue el principio del
trabajo de Cruz (`takeoff`, `go_to`, `land` del controlador high-level del
firmware Crazyflie) y toda la adaptación funciona en Python: interfaz, Robotat,
telemetría, seguridad y cflib. Botones, cámara, panel web y controlador corporal
mandan sobre él.

## 1. Probar la ventana sin hardware

```powershell
python .\controllers\two_drones\control_dos_drones_cruz_botones.py --dry-run
```

La variante recomendada con interfaz y hardware en procesos separados usa:

```powershell
python .\controllers\two_drones\control_dos_drones_cruz_multiprocessing.py --dry-run
```

En este modo no se importa cflib, no se abre ninguna Crazyradio y ningún botón
puede activar motores. Ejecuta `PREFLIGHT`, despega, mueve y aterriza los drones
simulados para comprobar la interfaz.

La entrada `python .\control_dos_drones_camara.py --dry-run` utiliza el mismo
backend simulado, pero abre la cámara para reconocer gestos. Un mensaje
`TAKEOFF` en ese modo solo cambia el estado simulado; no prueba la conexión
con los drones. En cámara, `q` aterriza y sale; Ctrl+C solicita emergencia y
cierra (código de salida 130). Si ambos procesos reciben Ctrl+C, el cliente
tolera que el backend ya haya cerrado y avisa cuando no recibe confirmación.

En todos los controles por cámara, enseñar únicamente el dedo medio activa el
seguimiento tridimensional del marker Robotat 65 para el dron asignado a esa mano. El
símbolo de rock (índice y meñique, con pulgar opcional) lo detiene y conserva el
último objetivo como hover. Con una mano asignada a `both`, ambos drones siguen
el mismo desplazamiento y conservan su formación inicial. Cada dron mantiene
0.45 m respecto al marker en X, Y y Z, con velocidad máxima de 0.10 m/s, pasos
high-level de hasta 2.5 cm y transiciones de 0.75 s. No se limita el recorrido
respecto al origen. Una esfera de exclusión evita que los drones se acerquen a
menos de 0.30 m. El seguimiento se cancela si una pose caduca. El puño mantiene
prioridad de emergencia aunque el seguimiento esté activo.

Regresión del cierre, sin abrir cámara, interfaz ni radios:

```powershell
python -m unittest discover -s controllers/two_drones/tests -v
```

### Diagnosticar un fallo de alineación EKF–MoCap

Si el preflight agota la espera de alineación, muestra en consola y en el
error las posiciones MoCap/EKF, su antigüedad, URI, tópico, parámetros en
cache y contadores de llamadas a `send_extpos`. Estos contadores son
acumulados por instancia: una llamada sin excepción no confirma recepción
en el firmware. Los errores de envío quedan disponibles aunque luego se
recupere la comunicación. El diagnóstico no solicita lecturas adicionales
ni cambia parámetros, tiempos de espera o el umbral de 0.07 m.

Una estimación `(0, 0, 0)` con muestras recientes y MoCap distinto de cero
requiere revisar el estimador, la inicialización del dron y la recepción de
posición externa. La antigüedad permite distinguir ese caso de una
telemetría que dejó de actualizarse. Para confirmar el origen, conservar
el diagnóstico completo y la salida de la consola del firmware; no basta
el mensaje genérico de alineación.

## 2. Preflight real sin motores

Para Robotat con el Flow Deck conectado, el preflight ahora exige confirmar
`motion.disable=1` y `range.disable=1` antes del reset del EKF. Esto excluye
flujo óptico y ToF; el segundo parámetro requiere el
[parche de firmware del proyecto](../../external/crazyflie_firmware/README.md).
Si el firmware no lo ofrece, el preflight se bloquea con un error específico.
Sin deck detectado se conserva la operación con MoCap. Esta selección también
aplica a todos los consumidores del backend, que comparten `DroneUnit`. Los modos dedicados a Flow Deck reactivan ambas mediciones.

```powershell
python .\controllers\two_drones\control_dos_drones_cruz_botones.py
```

Para la prueba real multiproceso:

```powershell
python .\controllers\two_drones\control_dos_drones_cruz_multiprocessing.py
```

### Qué recibe el EKF del Robotat (hallazgos del 12 de septiembre de 2026)

**El código de esta sección se implementó y se revirtió el mismo día por
decisión del humano; el backend vuelve a comportarse como antes.** Queda aquí
lo que se midió, para no perderlo:

- El puente Node-RED publica **cada frame varias veces** (en agosto, 3 a 5
  copias, ~86 mensajes/s y ~18 frames distintos/s con huecos de 0.3 s; el 12
  de septiembre, 40 Hz limpios). `drone_unit.py` limita el envío de extpos a
  20 Hz y su `mocap_hz` mide ráfagas, no frames distintos: con ráfagas, el EKF
  recibe 7–13 Hz irregulares.
- Con los drones en su posición de vuelo (en paralelo, la que indica el
  catedrático) los markers publican rumbos de ~95° y ~82°: **los drones miran
  a +Y del Robotat**, mientras el EKF asume la nariz en +X al reiniciarse y
  `go_to` manda yaw 0. El controlador corrige en un marco girado un cuarto de
  vuelta, que produce una oscilación circular lenta en X e Y con la misma
  frecuencia en ambos ejes.
- El rigid body del Dron 2 publica roll de −84°: sus ejes no son los del dron.
  Su rumbo (eje X proyectado) sirve; su actitud no.
- Para verlo en vivo, sin conectar drones:
  `controllers/joystick/ver_markers.py`.

El diseño que se probó (frames distintos sin límite de tasa, marco de vuelo
por dron, offset de rigid body) está en
`Tesis/60-Analisis/2026-09-12 Auditoría del controlador de dos drones.md` y en
`Tesis/30-Decisiones/2026-09-12 Marco de vuelo por dron.md`.

## Modo de un solo dron

Para probar únicamente el Dron 1 con el mismo control de Cruz:

```powershell
python .\controllers\two_drones\control_dos_drones_cruz_multiprocessing.py --single drone1
```

Para probar únicamente el Dron 2:

```powershell
python .\controllers\two_drones\control_dos_drones_cruz_multiprocessing.py --single drone2
```

Puede combinarse con `--dry-run`. En modo de un dron solo se abre su
Crazyradio y su tópico Robotat; el otro dron aparece deshabilitado y no se
aplica la verificación de separación.

Pulsa únicamente `PREFLIGHT (SIN MOTORES)`. Para habilitar el despegue debe
comprobar:

- marcadores estables en `mocap/drone3` y `mocap/drone4`;
- dos Crazyradio diferentes, resueltas por serial;
- separación inicial mínima de 0.30 m;
- alineación EKF–MoCap;
- telemetría de batería disponible únicamente para registro y visualización;

## 3. Primera comparación de hover

1. Despeja el área y mantén visible el botón rojo.
2. Completa el preflight.
3. Pulsa `DESPEGAR AMBOS`: ascienden 0.35 m en 5 s.
4. No envíes movimientos durante 10–15 s.
5. Pulsa `ATERRIZAR AMBOS`.

La sesión real genera
`results/data/dos_drones/<YYYY-MM-DD>/python_highlevel_cruz_*.csv`.
Al cerrar el programa genera automáticamente figuras PDF dentro de
`results/graphs/dos_drones/<YYYY-MM-DD>/python_highlevel_cruz_*`. Incluye altura, trayectoria XY, error de
control, error EKF-MoCap, calidad MoCap, batería, actitud y separación cuando
participan dos drones. El voltaje solo se registra y grafica: no bloquea el
preflight, el despegue ni activa una emergencia.

El watchdog detiene ambos motores ante pérdida de Robotat, error EKF–MoCap
mayor de 0.15 m o separación física menor de 0.30 m. La tecla
`R` y el botón rojo también activan la emergencia. **El paro estaba en `Q`
hasta septiembre de 2026**; se movió al asignar `Q` y `E` al giro.

La interfaz continúa mostrando el voltaje y porcentaje reportados, pero estos
valores son únicamente informativos.


## Dos drones con el controlador nuevo (septiembre de 2026)

`control_dos_drones_robotat.py` vuela los dos Crazyflies con dos instancias del
núcleo `controllers/shared/dron_robotat.py` (mando fluido por velocidad,
ganancias `robotat`, CSV por dron) y un supervisor que aterriza a los dos si se
acercan a menos de 0.30 m. Es independiente del backend de la cruz.

```powershell
.\.venv\Scripts\python.exe .\controllers\two_drones\control_dos_drones_robotat.py --dry-run
.\.venv\Scripts\python.exe .\controllers\two_drones\control_dos_drones_robotat.py --velocidad 0.25 --radio-max 1.0
```

### Tres drones (en preparación, 18 de septiembre de 2026)

`control_tres_drones_robotat.py` es el mismo panel con una tercera columna:
hereda de `PanelDosRobotat`, que ahora saca sus columnas de las claves de
`drones`, y sólo añade las teclas del Dron 3 (I/J/K/L, Y sube, H baja, U/O
giran). `SupervisorSeparacion` y `separacion()` trabajan con cualquier número
de drones: vigilan todos los pares, sólo cuentan los pares con los dos en el
aire, y un dron sin pose no apaga la vigilancia de los demás.

```powershell
.\.venv\Scripts\python.exe .\controllers\two_drones\control_tres_drones_robotat.py --dry-run
.\.venv\Scripts\python.exe .\controllers\two_drones\control_tres_drones_robotat.py --uri3 radio://<serial>/<canal>/2M/<direccion> --topic3 mocap/<rigid body> --velocidad 0.25 --radio-max 1.0
```

* **El Dron 3 no tiene identidad por defecto.** Sin `--dry-run` hay que dar
  `--uri3` y `--topic3`; el programa se niega antes de consultar las radios.
  Cuando se conozcan su dirección y su rigid body, pasan a `shared/radios.py`
  y `shared/robotat.py` como los de los otros dos.
* **Dos Crazyradio para tres drones.** El Dron 3 comparte antena con el dron
  cuyo serial lleve su URI (el programa lo avisa al arrancar). cflib lo admite
  en un mismo proceso, pero los dos drones se reparten el ancho de banda de
  esa radio, y con canales distintos la radio cambia de canal en cada paquete:
  conviene que compartan canal con direcciones distintas. **Sin validar con
  hardware**: lo primero que hay que medir es si el `extpos` de los dos drones
  de la antena compartida mantiene su cadencia (columna `extpos` del panel y
  huecos en el CSV) antes de despegar los tres.
* Vive en `two_drones/` porque es la carpeta de la coordinación de varios
  Crazyflies y reutiliza el panel y el supervisor de ahí; no se crea una
  carpeta nueva para un solo archivo.

### `--backend robotat` en las interfaces de la cruz

`robotat_backend.py` presenta uno o dos `DronRobotat` con la interfaz del
backend de la cruz, así que el panel de botones, el control por cámara de dos
drones y el panel individual aceptan `--backend robotat` (con `--ganancias`,
`--velocidad`, `--radio-max` y `--param`). Un `move` es un pulso de velocidad
fluida de 0.45 s que se prolonga si llega otro; `follow_move` es velocidad
proporcional al desplazamiento pedido. Cada dron guarda su CSV y sus gráficas
PDF en `results/.../dron_robotat/`.

```powershell
.\.venv\Scripts\python.exe .\controllers\two_drones\control_dos_drones_camara_multiprocessing.py --backend robotat --dry-run
.\.venv\Scripts\python.exe .\controllers\two_drones\control_dos_drones_camara_multiprocessing.py --backend robotat --velocidad 0.25 --radio-max 1.0
.\.venv\Scripts\python.exe .\controllers\two_drones\control_dos_drones_cruz_botones.py --backend robotat --velocidad 0.25 --radio-max 1.0
```
