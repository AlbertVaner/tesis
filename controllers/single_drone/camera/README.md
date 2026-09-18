# Control del Dron 1 por cámara

Un solo controlador, `control_camara_dron1.py`, con dos cosas elegibles:

| Argumento | Opciones | Qué cambia |
|---|---|---|
| `--reconocedor` | `cuerpo` *(por defecto)*, `manos`, `vocabulario` | Vocabulario 3D estático de cuerpo entero (MediaPipe Pose), gestos de una mano en 2D (MediaPipe Hands), o el vocabulario completo: dinámicos por DTW + estáticos + paro, con dos modos excluyentes (ver abajo) |
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

## Vocabulario completo: `--reconocedor vocabulario`

Es el bucle de `external/gesture_detection/probar_vocabulario.py` con el dron
real en vez del simulado: gestos dinámicos por DTW (`recognition/dinamicos.py`
con el banco `models/plantillas_vocabulario.npz`), los seis estáticos de
dirección de arriba y el paro de `recognition/paro_estatico.py`. Qué gesto
vale en qué modo lo decide `recognition/vocabulario.py` (`MaquinaDeModos`);
este archivo sólo traduce cada decisión a una orden del backend.

Arranca en **modo dinámico**; `aplaudir` cambia de modo en las dos direcciones
y deja el dron en hover: es también la forma de **salir** del seguimiento
(`ven_aca`) y de la órbita (`circulo`). El modo y lo que hace el dron se
muestran en grande, a la derecha bajo el panel. Los dos canales no conviven porque, medido en vivo, un
brazo abajo y al frente es por donde pasan los brazos al empezar y terminar
cualquier gesto dinámico.

| Modo | Gesto | Orden al dron |
|---|---|---|
| dinámico | `senalero` | despegue en el suelo, aterrizaje en el aire |
| dinámico | `ven_aca` | seguimiento del marker 65, como el gesto de mano |
| dinámico | `circulo` | **órbita** alrededor del marker 65: círculo de `--radio-orbita` (0.50 m) a la altura del marker, antihorario, con el objetivo 30° por delante del dron; sólo con `--backend robotat`. Un `circulo` cuya distancia DTW quede a menos del 20 % de la de `aplaudir` se ignora |
| dinámico | `arco` | **todavía sin vuelo**: hover y aviso (T-005, paso 2) |
| estático | `ARRIBA` … `DERECHA` | velocidad mientras se sostiene, sólo en el aire |
| ambos | `aplaudir` | cambia de modo; hover |
| siempre | X sobre la cabeza | 1 s: aterriza y bloquea hasta soltar; sostenida 3 s: corte de motores |

Los `DESPEGAR`, `ATERRIZAR` y `STOP` estáticos no actúan en este modo: los
sustituyen el senalero y la X, igual que en el probador. `ESC` sigue cortando
motores.

Dos cosas que conviene saber antes de volar con él:

- **Quién dice si el dron está en el aire es el backend, no la máquina.** Un
  despegue rechazado o un aterrizaje del watchdog no la desincronizan: el
  siguiente senalero vuelve a decidir con el estado real.
- **`aplaudir` se lee 3 de cada 4 veces** con su umbral propio (ver el análisis
  del reconocedor DTW en el vault). Si en vivo cuesta cambiar de modo, la
  palanca es subir sólo ese umbral en el banco, no `--banco` con umbral único.

```powershell
# leer el vocabulario completo en la webcam, sin dron
python .\controllers\single_drone\camera\control_camara_dron1.py --reconocedor vocabulario

# simulado, sin radio ni mocap
python .\controllers\single_drone\camera\control_camara_dron1.py --reconocedor vocabulario --volar --dry-run

# otra postura de paro, o más segundos para confirmarlo
python .\controllers\single_drone\camera\control_camara_dron1.py --reconocedor vocabulario --paro pecho --confirmacion 1.5
```

El CSV por frame lleva dos columnas más, `modo` y `comportamiento`, y la
gráfica marca cada gesto dinámico que se ejecutó (`senalero -> DESPEGAR`).

### Volar el Dron 2 con el mismo controlador

`--dron 2` cambia lo que distingue a un aparato del otro: el enlace de radio
(`DRONE_2_LINK` de `controllers/shared/radios.py`), el tópico mocap
(`mocap/drone4`) y la clave `drone2` en el backend de la cruz, así que su CSV
nombra al dron correcto. Sirve para separar hardware de software: si con el
Dron 2 la batería no se hunde o la oscilación cambia, el problema está en el
aparato. `--topico-dron` sigue mandando si hace falta otro tópico.

`--param grupo.nombre=valor`, repetible, fija parámetros del firmware justo
después de conectar (EKF, controlador de posición) y los imprime en el
preflight; viven en RAM y se pierden al reiniciar el dron. Ver la nota de
análisis de la oscilación del 2026-09-12 en el vault para la receta.

### Cámara IP y seguimiento PTZ

`--rtsp` sustituye la webcam por la cámara IP, con el mismo lector en hilo de
`external/gesture_detection/video_source.py` (sólo el último frame, sin
acumular latencia). Con `--seguir`, y sólo con `--reconocedor vocabulario`, la
cámara sigue al operador con su pan/tilt exactamente como en
`probar_vocabulario.py --seguir`: no gira mientras hay un gesto en curso salvo
que la persona se salga del cuadro, y los frames tomados girando se marcan como
huecos en vez de alimentar al reconocedor. Los mandos son los mismos:
`--zona-muerta`, `--zona-muerta-tilt`, `--centro-y`, `--velocidad-max`,
`--sin-tilt`, `--ptz-dry-run`. El PTZ se conecta antes que la radio: si la
cámara no responde, el programa sale sin armar nada.

```powershell
# vocabulario completo con la cámara IP siguiéndote, dron simulado
python .\controllers\single_drone\camera\control_camara_dron1.py --reconocedor vocabulario --rtsp "rtsp://usuario:clave@IP:554/cam/realmonitor?channel=1&subtype=1" --seguir --centro-y 0.6 --volar --dry-run
```

Sin `--rtsp`, `--seguir` no tiene host al que hablar y el programa lo dice.
Usar siempre `subtype=1` (el sub-stream): a 704x480 sin audio la cámara
responde en 200–350 ms en vez de ~800 ms con el stream principal, y MediaPipe
no gana nada con más resolución. El sub-stream se deja configurado una vez con
`external/gesture_detection/configurar_camara.py --aplicar`; el porqué y la
medida están en el README de `gesture_detection`, sección "Latencia". Ojo con
los fps: el banco se validó a 30 y 15, y el panel los muestra.

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
| Gestos dinámicos (DTW) y banco de plantillas | `external/gesture_detection/recognition/dinamicos.py` |
| Máquina de modos del vocabulario completo | `external/gesture_detection/recognition/vocabulario.py` |
| Paro por postura sostenida | `external/gesture_detection/recognition/paro_estatico.py` |
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
python -m pytest -q external\gesture_detection\tests\test_body_3d_rules.py
python -m pytest -q controllers\single_drone\camera\tests\test_control_camara.py
python -m pytest -q controllers\single_drone\camera\tests\test_highlevel_flight.py
python -m pytest -q controllers\single_drone\camera\tests\test_camera_flight_safety.py
python -m pytest -q controllers\single_drone\camera\tests\test_grafica_comandos.py
python -m pytest -q controllers\single_drone\camera\tests\test_control_vocabulario.py
```

Ninguna abre cámara, radio ni motores. La primera valida la geometría del
vocabulario; la segunda, la traducción de gesto a orden, el signo de la
corrección de rumbo y que las etiquetas de mano entren por el contrato; la
tercera, la traducción a pasos del backend high-level, su geocerca y el
watchdog de visión; la cuarta, el techo de altura y el watchdog del backend
Flow deck; la quinta, que la gráfica de comandos cuente bien los tramos y se
guarde en su carpeta; la sexta recorre el vocabulario completo sobre un
backend falso: senalero, seguimiento, cambio de modo, estáticos, paro y corte
de motores. Que un operador real consiga producir los gestos es otra cosa, y
para eso están `probar_gestos_3d.py --practica` y `probar_vocabulario.py`.

## Backend `robotat` (septiembre de 2026)

`--backend robotat` vuela con el controlador nuevo de un dron
(`controllers/single_drone/robotat/`, ver su README): la intención de velocidad
de los gestos se manda en modo fluido (paquete `hover` del firmware, como el
Flow Deck) en vez de pasos `go_to`, con las ganancias validadas el 16 de
septiembre (`--ganancias robotat`) y el empuje de hover medido en el último
vuelo. El seguimiento del marker 65 (dedo medio) persigue el ancla a la altura del marker con tope `--velocidad-seguir` (0.30 m/s). Sin órdenes de la cámara durante 0.4 s el dron frena; a los 2 s aterriza.

```powershell
# sin hardware
.\.venv\Scripts\python.exe .\controllers\single_drone\camera\control_camara_dron1.py --reconocedor vocabulario --backend robotat --dry-run --volar
# Dron 2 en el Robotat
.\.venv\Scripts\python.exe .\controllers\single_drone\camera\control_camara_dron1.py --reconocedor vocabulario --backend robotat --dron 2 --radio-max 1.0 --volar
```
