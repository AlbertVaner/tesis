# Control del Dron 1 por cámara

Hay dos controladores, y la diferencia no es de estilo:

| | `control_camara_flowdeck_dron1.py` | `control_corporal_dron1.py` |
|---|---|---|
| Entrada | una mano, MediaPipe Hands | cuerpo entero, MediaPipe Pose |
| Marco | píxeles de la imagen | marco del cuerpo, en unidades de torso |
| Comandos | 6 direcciones + despegue/aterrizaje | 6 direcciones + despegue/aterrizaje/stop |
| ADELANTE / ATRAS | no existen | sí |
| Depende del ángulo del operador | sí | no |

Los dos controladores aceptan además dos gestos de mano que no pertenecen al
vocabulario corporal: enseñar únicamente el dedo medio activa el seguimiento
tridimensional del marker Robotat 65; el símbolo de rock (índice y meñique, con el
pulgar abierto o cerrado) lo detiene y deja el dron en hover. Al activarse se
define una separación de 0.45 m entre dron y marker, de modo que el dron sigue
sus desplazamientos en X, Y y Z. El movimiento se limita a 0.10 m/s y no aplica
la geocerca respecto al origen. Si se pierde el marker o la pose del dron, el
seguimiento se cancela y queda hover.

El lanzador de conveniencia `control_dron_camara.py` apunta ahora a
`control_corporal_dron1.py`. Sin `--volar` sólo abre la cámara; el seguimiento
real se habilita junto con el resto del vuelo mediante `--volar`.

El segundo es el que se está validando para el Robotat: el objetivo es un
anillo de seis cámaras IP alrededor del operador, y ahí el marco del cuerpo
deja de ser una comodidad y pasa a ser obligatorio. Sin canonicalizar, la
misma pose vista por dos cámaras adyacentes produce números que difieren un
62 %; canonicalizada, un 0 %.

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

`control_camara_flowdeck_dron1.py`, el de manos, **sí** infiere sobre la imagen
volteada. Sus umbrales se ajustaron así, de modo que se dejó como estaba.

## Uso

Para **sólo ver si los gestos se detectan**, sin nada de vuelo, el programa es otro y vive en el subsistema de visión:

```powershell
python .\external\gesture_detection\probar_gestos_3d.py
```

Ése no importa `cflib` ni conoce el Crazyflie, y muestra por qué un gesto no sale. Los de abajo son los que sí hablan con el dron.

```powershell
# leer el vocabulario en la webcam, sin dron y sin radio
python .\controllers\single_drone\camera\control_corporal_dron1.py

# recorrido guiado por los nueve gestos, con tasa de acierto y latencia
python .\controllers\single_drone\camera\control_corporal_dron1.py --practica

# conectar el Dron 1 y ejecutar los comandos
python .\controllers\single_drone\camera\control_corporal_dron1.py --volar

# volando con el mocap, mirando hacia el eje +Y de la sala
python .\controllers\single_drone\camera\control_corporal_dron1.py --volar --rumbo 90

# con Flow deck en vez del mocap
python .\controllers\single_drone\camera\control_corporal_dron1.py --volar --flowdeck
```

### Dos backends de vuelo, y el de mocap es el que manda

Por defecto vuela con el **mocap del Robotat**. `--flowdeck` cambia al otro.

| | Mocap del Robotat *(por defecto)* | `--flowdeck` |
|---|---|---|
| Posición | absoluta, por MQTT + `extpos` | integrada desde el despegue |
| Geofence | sí, radio real | imposible |
| Pérdida de tracking | detectable, corta | invisible |
| `commander.enHighLevel` | 0 | 1 |
| Cómo vuela | `send_velocity_world_setpoint` en un lazo propio | `MotionCommander` |

No son dos variantes de lo mismo: son configuraciones de firmware
**mutuamente excluyentes**. `MotionCommander` *es* el commander de alto nivel,
así que la ruta de mocap lo apaga y hay que volar en un lazo propio, porque el
setpoint de velocidad caduca. Eso vive en
[mocap_flight.py](mocap_flight.py), que expone la misma interfaz de diez
miembros que `CameraFlight`; el reconocimiento, el panel y el CSV no cambian.

La envolvente de vuelo —altura, radio, velocidades, timeout de mocap— **no se
redefine**: se importa de `controllers/joystick/control_with_marker.py`, que es
donde se ajustó volando.

Antes de la primera sesión hay que confirmar el tópico MQTT del Dron 1. Por
defecto es `mocap/drone3`, que es el que usa el control por marker; si el Dron 1
publica en otro, `--topico-dron`, y `--id-dron` si el tópico lleva varios
cuerpos.

### El rumbo no es opcional

Los gestos están en **tu** marco: `ADELANTE` es hacia donde mirás vos. El dron
no obedece en ese marco, y adónde hay que girarlo depende del backend:

- **Con mocap**, las órdenes van en el marco de la **sala**. El rumbo del dron
  da igual —eso sí lo resuelve el mocap— pero aparece el otro: `--rumbo` es
  hacia dónde mirás vos, en grados antihorarios desde el eje `+X` del Robotat.
- **Con `--flowdeck`**, van en el marco del **dron**: `--rumbo` es cuánto está
  girada su nariz hacia tu izquierda.

En los dos casos un `--rumbo` equivocado manda el dron de lado. Si el operador
llega a llevar un marcador encima, ese ángulo sale del mocap y deja de teclearse.

Sin `--volar` no se importa `cflib`, no se abre la radio y no se arma nada, así
que el banco de pruebas corre en cualquier máquina con webcam.

Teclas: `q` salir, `ESC` parada de emergencia, `r` reiniciar el reconocedor,
`n` saltar el gesto actual en modo práctica.

Cada sesión deja un CSV por frame en
`results/data/control_corporal_dron1/<AAAA-MM-DD>/` y una **gráfica de tiempo
contra comandos** en `results/graphs/control_corporal_dron1/<AAAA-MM-DD>/`
(`<sesion>_comandos.png` y `.pdf`, con la misma etiqueta que el CSV). El
controlador de manos guarda la suya en
`results/graphs/control_camara_flowdeck_dron1/<AAAA-MM-DD>/`.

La figura se genera al cerrar —también tras una emergencia o un error— y
muestra qué comando atendió el controlador en cada instante, si estaba
confirmado, el estado del dron de fondo y cuánto tiempo se sostuvo cada
orden. Es la misma figura para los dos controladores, para poder comparar
una sesión de mano con una de cuerpo. `--sin-grafica` la desactiva.

## Dónde está cada cosa

El reconocimiento **no** vive aquí. Este archivo sólo compone cámara, pose,
reconocedor, panel y vuelo.

| Pieza | Ubicación |
|---|---|
| Vocabulario, umbrales y reglas | `external/gesture_detection/recognition/body_3d_rules.py` |
| Marco corporal y escala | `external/gesture_detection/pose/normalize.py` |
| Contrato `GestureEvent` | `external/gesture_detection/contracts.py` |
| Vuelo con mocap *(por defecto)* | `mocap_flight.py` (`MocapFlight`) |
| Vuelo con Flow deck | `control_camara_flowdeck_dron1.py` (`CameraFlight`) |
| Gráfica tiempo vs comandos | `grafica_comandos.py` (`GraficaDeComandos`) |
| Envolvente de vuelo | `controllers/joystick/control_with_marker.py` |

`control_corporal_dron1.py` reutiliza `CameraFlight` en lugar de duplicarlo:
techo de altura, registro de `stateEstimate.z` y watchdog de visión en dos
etapas ya están probados ahí.

## Pruebas

```powershell
python .\external\gesture_detection\tests\test_body_3d_rules.py
python .\controllers\single_drone\camera\tests\test_camera_flight_safety.py
python .\controllers\single_drone\camera\tests\test_control_corporal.py
python .\controllers\single_drone\camera\tests\test_mocap_flight.py
python .\controllers\single_drone\camera\tests\test_grafica_comandos.py
```

Ninguna abre cámara, radio ni motores. La primera valida la geometría del
vocabulario; la segunda, las protecciones de vuelo; la tercera, la
traducción de gesto a orden y el signo de la corrección de rumbo; la cuarta,
el geofence, la ventana de altura y la pérdida de tracking del backend de mocap;
la quinta, que la gráfica de comandos cuente bien los tramos y se guarde en su
carpeta. Que un operador real
consiga producir los gestos es otra cosa, y para eso está `--practica`.
