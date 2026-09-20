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
| dinámico | `arco` | **pirueta**: espiral hacia abajo y subida por el eje; al terminar vuelve a hover. Sólo con `--backend robotat` |
| estático | `ARRIBA` … `DERECHA` | velocidad mientras se sostiene, sólo en el aire |
| ambos | `aplaudir` | cambia de modo; hover |
| siempre | X sobre la cabeza | **0.35 s: frena** (deja de seguir u orbitar y queda en hover; bajando los brazos ahí, sigue volando); 1 s: aterriza y bloquea hasta soltar; sostenida 3 s: corte de motores |

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

### La pirueta del gesto `arco`

Es la maniobra de la [demo de Bitcraze en IROS 2018](https://www.bitcraze.io/2018/10/the-iros-2018-demo/):
**una espiral hacia abajo y la vuelta hacia arriba por el eje central**. Ellos
la suben al firmware como trayectoria polinómica y suavizan altura y radio con
senos para que no haya tirones; aquí la forma y los senos son los mismos, pero
se vuela como la órbita: Python manda velocidades en modo fluido y la posición
la cierra el firmware. Así pasa por la geocerca, por la zona de exclusión del
marker y por la repulsión entre drones, como todo lo demás. `arco` era
ALEJARSE, que nunca llegó a tener implementación de vuelo.

| | Un dron | Dos drones (`--dron ambos`) |
|---|---|---|
| Eje | Donde estaba el dron al hacer el gesto | El punto medio entre los dos |
| Radio | Se abre de 0 a 0.40 m y se cierra otra vez sobre el eje | Casi constante, entre 0.45 y 0.70 m: es una **doble hélice en oposición** |
| Vueltas | 2 | 1.5 |
| Altura | De donde esté (máx. 0.90 m) a 0.35 m, y vuelta arriba | Igual |
| Subida | Vertical por el eje | Cada uno en vertical desde donde terminó |
| Duración | ~25 s con el tope de 0.30 m/s | ~25-30 s |

La duración sale del tope de velocidad: el tramo más rápido se recorre al 80 %
de `--velocidad-tope`. El punto que persigue el dron **le espera** si se queda
más de 25 cm atrás, la lección de la órbita. Con dos drones el avance es común:
si uno se retrasa el otro le espera y la oposición no se rompe. Se interrumpe
con la X sobre la cabeza (frena a los 0.35 s) o con cualquier otro gesto que
cambie de comportamiento. Al terminar, el dron queda en hover.

Necesita sitio: un círculo de 0.40 m alrededor del dron (0.70 m alrededor del
punto medio, con dos) dentro de la geocerca, y 0.90 m de altura libre.

### Parar sin depender del aplauso, y la mano del operador

**La X frena antes de aterrizar.** El aplauso es un gesto dinámico: se reconoce
al terminar y falla si el operador camina o la cámara se mueve. En la sesión de
las 18:50 del 2026-09-18 el dron siguió al operador **59 s** con todos los
aplausos rechazados ("demasiado largo", "pose perdida"). La X sobre la cabeza
tiene ahora una primera etapa a los 0.35 s que **frena**: cancela seguir u
orbitar y deja el dron en hover. Bajando los brazos ahí, sigue volando.

**El paro ve siempre la imagen.** Con la cámara girando, los frames no valen
para clasificar movimiento y se descartaban para los tres canales, también el
del paro. Caminando, con la cámara siguiendo al operador casi sin parar, la X
no podía sostenerse y no disparaba nunca. Ahora el paro recibe todos los
frames, y la cámara se queda quieta mientras se hace la X.

**Antirrebote.** La cola de un gesto se leía como otro (un `ven_aca` 2.6 s
después del `circulo`): entre dos comportamientos continuos distintos tienen
que pasar 4 s.

**Zona de exclusión del marker.** El marker 65 va en la mano del operador.
`--exclusion-marker` (0.60 m) es un radio al que **ninguna orden** puede
acercar el dron, tampoco las direcciones de los gestos estáticos: dentro, se
anula la parte de la velocidad que acerca y se empuja hacia fuera.
`--radio-seguir` (0.80 m, era 0.45) y `--radio-orbita` (0.80 m, era 0.50) no
pueden quedar por debajo de la zona más 15 cm. Una órbita de 0.80 m necesita
sitio: con `--radio-max 1.0` el marker tiene que estar a menos de 20 cm del
centro de la geocerca; para orbitar con holgura, `--radio-max 1.4` o más.

### Volar los dos drones a la vez: `--dron ambos`

El mismo controlador y el mismo vocabulario, con los dos Crazyflies en
formación. Necesita `--backend robotat` y dos Crazyradio.

```powershell
# ensayo sin hardware
python .\controllers\single_drone\camera\control_camara_dron1.py --reconocedor vocabulario --backend robotat --dron ambos --radio-max 1.0 --rtsp env --seguir --volar --dry-run
# vuelo real: el mismo comando sin --dry-run
```

| Gesto | Con dos drones |
|---|---|
| Señalero, paro | Despegan, aterrizan o cortan motores **los dos** |
| Direcciones (modo estático) | La misma velocidad a los dos: se mueven en paralelo |
| `ven_aca` (seguir) | Cada uno a su ancla, repartidas a ±70° de la dirección media: quedan a 0.85 m entre sí en vez de a 15 cm |
| `circulo` (orbitar) | Los dos en el mismo círculo, **en oposición**; la velocidad de cada uno se regula con el desfase hasta llevarlo a 180° |

**Geocerca común.** Cada dron tiene su cerca centrada en su propio despegue, y
con dos eso los aprieta uno contra otro (a 1.54 m entre sí y radio 1.0 la zona
común medía 0.46 m). En formación hay **una sola cerca**: centro en el punto
medio de los dos despegues, o el de `--centro-geocerca`, y radio `--radio-max`.
Si algún dron queda a menos de 30 cm del borde **no despega** y dice qué hacer:
acercar los drones o subir `--radio-max`. Con `--radio-max 1.0`, colocarlos a
1.4 m o menos entre sí. La órbita (radio mínimo 0.60 m con dos drones) tiene
que caber dentro: el marker, a menos de 40 cm del centro de la cerca.

Seguridad propia de la formación: por debajo de 80 cm entre sí cada dron es
empujado en sentido opuesto al otro, y la orden original se atenúa hasta
anularse a 55 cm (repulsión, en todas las órdenes); no despega con los drones a menos de 50 cm;
un supervisor aterriza a los dos si se acercan a menos de 30 cm; y si uno deja
de volar por su cuenta (batería, geocerca, vigilante de visión), el otro
aterriza también. Cada dron deja su propio CSV y sus gráficas.

La coordinación vive en `controllers/two_drones/formacion_camara.py`
(`VueloFormacion`); este controlador sólo construye los dos vuelos y los
envuelve. Decisión y alternativas en
`Tesis/30-Decisiones/2026-09-18 Dos drones en formacion con el controlador de gestos de uno.md`.

### Grabar la interfaz en vídeo: `--grabar-video`

Guarda en MP4 lo que se ve en la ventana (cámara, esqueleto y panel) en
`results/captures/control_camara_dron1/<día>/sesion_HHMMSS.mp4`, con el mismo
nombre que el CSV de la sesión. Va **a velocidad real**: el bucle de visión no
tiene una tasa fija (22-30 fps, y se para segundos cuando la cámara da la
vuelta), así que cada cuadro se repite o se descarta para seguir al reloj, y el
vídeo dura lo que duró la sesión y casa con el CSV. Sólo graba esa ventana, no
el resto del escritorio. Los MP4 no se versionan.

### Cámara IP y seguimiento PTZ

`--rtsp` sustituye la webcam por la cámara IP, con el mismo lector en hilo de
`external/gesture_detection/video_source.py` (sólo el último frame, sin
acumular latencia). Con `--seguir`, y sólo con `--reconocedor vocabulario`, la
cámara sigue al operador con su pan/tilt exactamente como en
`probar_vocabulario.py --seguir`: no gira mientras hay un gesto en curso salvo
que la persona se salga del cuadro, y los frames tomados girando se marcan como
huecos en vez de alimentar al reconocedor. Los mandos son los mismos:
`--zona-muerta`, `--zona-muerta-tilt`, `--encuadre`, `--centro-y`, `--velocidad-max`,
`--sin-tilt`, `--ptz-dry-run`. El PTZ se conecta antes que la radio: si la
cámara no responde, el programa sale sin armar nada.

```powershell
# vocabulario completo con la cámara IP siguiéndote, dron simulado
python .\controllers\single_drone\camera\control_camara_dron1.py --reconocedor vocabulario --rtsp "rtsp://usuario:clave@IP:554/cam/realmonitor?channel=1&subtype=1" --seguir --volar --dry-run
```

`--rtsp env` arma la URL con `CAM_HOST`, `CAM_USER` y `CAM_PASSWORD` del entorno o
del `.env` de la raíz (ver `.env.example`), para no escribir la clave en el comando:

```powershell
python .\controllers\single_drone\camera\control_camara_dron1.py --reconocedor vocabulario --backend robotat --rtsp env --seguir --volar --dry-run
```

La cámara empieza donde esté; `--frente PAN TILT` (o `--frente` a secas, con el
guardado en el `.env`) la lleva antes a una posición. Si el pan choca con su
tope, **da la vuelta por el otro lado: ~5 s sin imagen y sin gestos, tampoco el
de paro**. En esos segundos la emergencia es la tecla ESC. El panel lo avisa.

En vertical, `--encuadre cuerpo` (por defecto) lleva el pecho al centro de la
cámara sin cortar cabeza ni pies; `pecho` y `torso` son las alternativas. Ya no
hace falta `--centro-y 0.6`: ese truco compensaba que antes se centraba el
ombligo. Detalle en el README de `gesture_detection`, sección "Ajustes".

Sin `--rtsp`, `--seguir` no tiene host al que hablar y el programa lo dice.
Usar siempre `subtype=1` (el sub-stream): a 640x480 sin audio la cámara
responde en 200–350 ms en vez de ~800 ms con el stream principal, y MediaPipe
no gana nada con más resolución. El sub-stream se deja configurado una vez con
`external/gesture_detection/configurar_camara.py --aplicar`; el porqué y la
medida están en el README de `gesture_detection`, sección "Latencia". Ojo con
los fps: el banco se validó a 30 y 15, y el panel los muestra.

Desde el 2026-09-18 la cámara está montada de lado y la imagen se endereza en
la propia cámara (`configurar_camara.py --rotar 270 --aplicar`), así que el
cuadro llega en vertical. El controlador lo escala a 720 px de alto y lo
completa con una banda oscura hasta 960 px de ancho para que el panel de texto
quepa; la inferencia se hace sobre el cuadro original. Con `--seguir`, el
cliente PTZ cruza los ejes solo según la rotación de la cámara. Ver "Cámara
montada de lado" en el README de `gesture_detection`.

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
