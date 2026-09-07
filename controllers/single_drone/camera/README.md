# Control del Dron 1 por cámara

Un solo controlador, `control_camara_dron1.py`, con dos cosas elegibles:

| Argumento | Opciones | Qué cambia |
|---|---|---|
| `--reconocedor` | `cuerpo` *(por defecto)*, `manos` | Vocabulario 3D de cuerpo entero (MediaPipe Pose) o gestos de una mano en 2D (MediaPipe Hands) |
| `--backend` | `mocap` *(por defecto)*, `flowdeck` | Backend high-level de la cruz sobre el Robotat o `FlowDroneController` con Flow deck v2 |

El resto es el mismo código para las cuatro combinaciones: bucle de cámara,
STOP sostenido, seguimiento del marker 65, panel, CSV por frame y gráfica de
tiempo contra comandos. El lanzador de conveniencia `control_dron_camara.py`
en la raíz apunta aquí.

| | `--reconocedor manos` | `--reconocedor cuerpo` |
|---|---|---|
| Entrada | una mano, MediaPipe Hands | cuerpo entero, MediaPipe Pose |
| Marco | píxeles de la imagen | marco del cuerpo, en unidades de torso |
| Comandos | 6 direcciones + despegue/aterrizaje | 6 direcciones + despegue/aterrizaje/stop |
| ADELANTE / ATRAS | no existen | sí |
| Depende del ángulo del operador | sí | no |
| STOP sostenido para emergencia | 0.6 s (puño) | 2 s (manos juntas) |

Los dos reconocedores aceptan además dos gestos de mano que no pertenecen al
vocabulario: enseñar únicamente el dedo medio activa el seguimiento
tridimensional del marker Robotat 65; el símbolo de rock (índice y meñique) lo
detiene y deja el dron en hover. Con mocap el seguimiento son pasos
`follow_move` validados por la cruz; con Flow deck, una velocidad relativa
limitada a 0.10 m/s. Si se pierde el marker o la pose del dron, el
seguimiento se cancela y queda hover.

El reconocedor corporal es el que se está validando para el Robotat: el
objetivo es un anillo de seis cámaras IP alrededor del operador, y ahí el
marco del cuerpo deja de ser una comodidad y pasa a ser obligatorio.

## Vocabulario 3D

Los ejes son los **del operador**: `+X` a su izquierda, `+Y` arriba, `+Z` hacia
donde mira.

| Gesto | Cómo se hace | Orden al dron |
|---|---|---|
| `ADELANTE` | un brazo al frente, horizontal | `vx = +1` |
| `ATRAS` | un brazo abajo y hacia atrás | `vx = -1` |
| `IZQUIERDA` | brazo **izquierdo** abierto a tu izquierda | `vy = +1` |
| `DERECHA` | brazo **derecho** abierto a tu derecha | `vy = -1` |
| `ARRIBA` | un brazo arriba, ligeramente al frente | `vz = +1` |
| `ABAJO` | un brazo abajo y al frente, a 45° | `vz = -1` |
| `DESPEGAR` | las dos manos por encima de los hombros | despegue |
| `ATERRIZAR` | los dos brazos en cruz, horizontales | aterrizaje |
| `STOP` | las dos manos **juntas** delante del pecho | hover; sostenido 2 s, emergencia |

Señala **cualquiera de los dos brazos**: el que se aleje más de la vertical.
El otro tiene que quedarse colgando, y eso es lo único que separa `ARRIBA` de
`DESPEGAR` y `DERECHA` de `ATERRIZAR`.

Tres detalles que no son arbitrarios, y los tres salieron de medir:

- **Cada lateral se hace con su brazo.** Con el brazo derecho fijo, `IZQUIERDA`
  obligaba a cruzar el pecho estirado, que el hombro no da: en una sesión real
  de 368 s el mejor intento se quedó a 19° del objetivo y sólo 3 frames de 79
  entraron en el cono de 22°.
- **`ABAJO` no es el brazo colgando**, porque eso es la postura de reposo. Va
  abajo y al frente, a 45°, y ése es el único que **no** está medido sino
  fijado: medido daba 25° de la vertical, que lo deja a 24° del brazo
  colgando y haría descender el dron solo. Si cuesta, hay que exagerarlo.
- **Las direcciones están medidas, no supuestas.** El hombro no trabaja en
  el plano frontal: levantar o abrir el brazo lo lleva hacia adelante. Con
  los ejes ideales, `ARRIBA` se reconocía 1 frame en 120 s de vuelo.
  Recentrando sobre 1461 frames reales, el reconocimiento sube de 823 a
  1101 frames (`ARRIBA` 89 → 143, `DERECHA` 194 → 380).
- **`ATRAS` tiene dos excepciones, y las dos salieron de medir.** Al echar el
  brazo atrás el hombro no da la extensión solo: el brazo **se abre al
  costado** y el **codo se dobla**. Sobre 2952 frames de una sesión real, los
  88 en que se intentó dieron dirección mediana `[-0.64, -0.46, -0.61]` y
  extensión 0.70, y sólo 2 pasaban el umbral general de 0.85. Por eso `ATRAS`
  se compara **sólo en el plano sagital**, ignorando la apertura lateral, y
  pide menos extensión. Con eso pasó de 0 a 89 frames reconocidos en esa misma
  sesión, sin un solo falso positivo.

`STOP` y aplaudir son la misma postura. Los distingue el tiempo: `STOP` pide
0.8 s sostenidos. Sobre una grabación real de 60 s con palmadas, el gesto se
insinuó en el 7.6 % de los frames y se confirmó 3 veces.

### El espejo va después de la inferencia

La imagen se voltea para mostrarla, nunca antes de MediaPipe. Volteada,
MediaPipe intercambia las etiquetas anatómicas —llama «izquierda» a lo que ve a
la derecha del encuadre— y con ellas se invierte el eje `X` del marco corporal,
así que `IZQUIERDA` y `DERECHA` salen cambiadas y los gestos de un brazo dejan
de detectarse. Comprobado sobre la misma foto con y sin espejo.

El reconocedor de manos (`--reconocedor manos`) **sí** infiere sobre la imagen
volteada. Sus umbrales se ajustaron así, de modo que se dejó como estaba.

## Uso

Para **sólo ver si los gestos se detectan**, o para medir acierto y latencia
con la práctica guiada, el programa es otro y vive en el subsistema de visión:

```powershell
python .\external\gesture_detection\probar_gestos_3d.py
python .\external\gesture_detection\probar_gestos_3d.py --practica --semilla 7
```

Ése no importa `cflib` ni conoce el Crazyflie, y muestra por qué un gesto no
sale. Los de abajo son los que sí hablan con el dron.

```powershell
# leer el vocabulario en la webcam, sin dron y sin radio
python .\controllers\single_drone\camera\control_camara_dron1.py

# volar sobre el backend high-level, simulado (sin radio ni mocap)
python .\controllers\single_drone\camera\control_camara_dron1.py --volar --dry-run

# conectar el Dron 1 por mocap y ejecutar los comandos
python .\controllers\single_drone\camera\control_camara_dron1.py --volar

# volando con el mocap, mirando hacia el eje +Y de la sala
python .\controllers\single_drone\camera\control_camara_dron1.py --volar --rumbo 90

# gestos de una mano sobre Flow deck
python .\controllers\single_drone\camera\control_camara_dron1.py --reconocedor manos --backend flowdeck --volar
```

### Los dos backends

| | `--backend mocap` *(por defecto)* | `--backend flowdeck` |
|---|---|---|
| Posición | absoluta, por MQTT + `extpos` | integrada desde el despegue |
| Geofence | sí, radio real | imposible |
| Pérdida de tracking | detectable, corta | invisible |
| Cómo vuela | pasos `go_to` del backend high-level de la cruz | `MotionCommander` con velocidad |
| Simulación | `--dry-run` | no |

Con mocap, [highlevel_flight.py](highlevel_flight.py) envuelve el backend de
`controllers/two_drones/cruz_highlevel_backend.py` en modo de un dron: cada
gesto de dirección se convierte en un paso de 0.10 m (0.08 m en Z) como máximo
cada 1.25 s, y el backend valida geocerca, ventana de altura, mocap fresco,
alineación EKF y separación. Sin órdenes de la cámara durante 2 s aterriza.
Con Flow deck se usa el `FlowDroneController` de `two_drones/flowdeck_dual_backend.py`
con techo de altura y watchdog de visión en dos etapas.

Antes de la primera sesión con mocap hay que confirmar el tópico MQTT del
Dron 1. Por defecto es `mocap/drone3`; si el Dron 1 publica en otro,
`--topico-dron`.

### El rumbo no es opcional

Los gestos están en **tu** marco: `ADELANTE` es hacia donde mirás vos. El dron
no obedece en ese marco, y adónde hay que girarlo depende del backend:

- **Con mocap**, las órdenes van en el marco de la **sala**. El rumbo del dron
  da igual, pero aparece el otro: `--rumbo` es hacia dónde mirás vos, en grados
  antihorarios desde el eje `+X` del Robotat.
- **Con Flow deck**, van en el marco del **dron**: `--rumbo` es cuánto está
  girada su nariz hacia tu izquierda.

En los dos casos un `--rumbo` equivocado manda el dron de lado.

Sin `--volar` no se importa `cflib`, no se abre la radio y no se arma nada, así
que la lectura de gestos corre en cualquier máquina con webcam.

Teclas: `q` salir, `ESC` parada de emergencia, `r` reiniciar el reconocedor.

Cada sesión deja un CSV por frame en
`results/data/control_camara_dron1/<AAAA-MM-DD>/<sesion>.csv` y una gráfica de
tiempo contra comandos en `results/graphs/control_camara_dron1/<AAAA-MM-DD>/`
(`<sesion>_comandos.png` y `.pdf`, con la misma etiqueta que el CSV). La figura
se genera al cerrar, también tras una emergencia, y muestra qué comando
atendió el controlador en cada instante, si estaba confirmado y el estado del
dron de fondo. Es la misma figura para los dos reconocedores, para poder
comparar una sesión de mano con una de cuerpo. `--sin-grafica` la desactiva y
`--sin-csv` desactiva el CSV.

## Dónde está cada cosa

Este archivo sólo compone cámara, reconocedor, panel y vuelo.

| Pieza | Ubicación |
|---|---|
| Vocabulario 3D, umbrales y reglas | `external/gesture_detection/recognition/body_3d_rules.py` |
| Gestos de mano 2D | `external/gesture_detection/hand_gesture_detector.py` |
| Marco corporal y escala | `external/gesture_detection/pose/normalize.py` |
| Contrato `GestureEvent` | `external/gesture_detection/contracts.py` |
| Práctica guiada y diagnóstico sin dron | `external/gesture_detection/probar_gestos_3d.py` |
| Vuelo con mocap | `highlevel_flight.py` sobre `controllers/two_drones/cruz_highlevel_backend.py` |
| Vuelo con Flow deck | `controllers/two_drones/flowdeck_dual_backend.py` (`FlowDroneController`) |
| Seguimiento del marker 65 | `controllers/joystick/marker_follow.py` |
| Gráfica tiempo vs comandos | `grafica_comandos.py` (`GraficaDeComandos`) |

## Pruebas

```powershell
python .\external\gesture_detection\tests\test_body_3d_rules.py
python .\controllers\single_drone\camera\tests\test_control_camara.py
python .\controllers\single_drone\camera\tests\test_highlevel_flight.py
python .\controllers\single_drone\camera\tests\test_camera_flight_safety.py
python .\controllers\single_drone\camera\tests\test_grafica_comandos.py
```

Ninguna abre cámara, radio ni motores. La primera valida la geometría del
vocabulario; la segunda, la traducción de gesto a orden, el signo de la
corrección de rumbo y que las etiquetas de mano entren por el contrato; la
tercera, la traducción a pasos del backend high-level, su geocerca y el
watchdog de visión; la cuarta, el techo de altura y el watchdog del backend
Flow deck; la quinta, que la gráfica de comandos cuente bien los tramos y se
guarde en su carpeta. Que un operador real consiga producir los gestos es otra
cosa, y para eso está `probar_gestos_3d.py --practica`.
