# Detección de gestos por cámara

## Objetivo del proyecto

Este subsistema contiene la visión del proyecto, y funciona sin importar controladores de Crazyflie. El **vocabulario 3D de cuerpo entero** ya clasifica y produce comandos a través de `contracts.py`; `probar_gestos_3d.py` es la vista previa con clasificación, y el detector manual de manos se conserva como prototipo anterior.

Todos los comandos se ejecutan desde la raíz del repositorio.

## Vocabulario 3D de cuerpo entero

Es la línea principal del proyecto. Reconoce nueve gestos sobre
`pose_world_landmarks`, canonicalizados al marco del cuerpo, y los entrega como
`GestureEvent`. El vocabulario y sus umbrales están en un solo archivo.

```text
contracts.py                        Gesture, VelocityIntent, GestureEvent
pose/normalize.py                   marco corporal y escala del operador
recognition/body_3d_rules.py        el vocabulario, sus umbrales y las reglas
tests/test_body_3d_rules.py         comprobación sin cámara ni dron
```

Dos reglas del contrato que conviene no romper: la visión **nunca** produce
m/s —produce intención normalizada, y el controlador la escala— y
`confirmed=False` significa «no ejecutar».

### Probar los gestos sin dron

```powershell
python .\external\gesture_detection\probar_gestos_3d.py
python .\external\gesture_detection\probar_gestos_3d.py --video grabacion.mp4
```

No importa controladores ni `cflib`. Además de mostrar el gesto, muestra **por qué no** sale: cada condición con su valor actual, su umbral y si cumple. Cuando un gesto no aparece, la línea en rojo dice cuál es el problema. El CSV guarda todas las medidas por frame, así que un umbral se puede reajustar sin volver a grabar.

Con `--practica` guía al operador por los nueve gestos en orden aleatorio y mide acierto y latencia; `--semilla` fija el orden. El consumidor con dron es `controllers/single_drone/camera/control_camara_dron1.py`; la tabla de gestos y cómo se hacen está en el README de esa carpeta.

```powershell
python -m pytest -q external\gesture_detection\tests\test_body_3d_rules.py
```

## Gestos dinámicos: aplausos y secuencias

El vocabulario de arriba lee **posturas**. Un aplauso o una celebración no son
una postura: son un recorrido. Eso vive en otras dos piezas.

```text
recognition/dinamicos.py        segmentación por movimiento y banco de plantillas
recognition/dtw.py              distancia DTW y umbral por separación
recognition/vocabulario.py      máquina de modos: qué gesto vale en qué modo, sin dron
tests/test_dtw.py               comprobación sin cámara
```

La ventana se define en **segundos y número de muestras**, no en frames: 1.5 s
en 24 muestras. Una ventana de «los últimos 45 frames» dura 1.5 s a 30 fps y
3.0 s a 15 fps, que son gestos distintos.

### Qué da sobre material real

Diez aplausos de una grabación de 60 s, evaluados *leave-one-out* — cada
aplauso como plantilla, probado contra los otros nueve y contra 80 ventanas sin
aplauso:

| | mediana | |
|---|---|---|
| aplauso contra aplauso | **0.276** | p90 0.490 |
| aplauso contra lo demás | **0.957** | p10 0.550 |

Un factor 3.5 de separación. Con el umbral óptimo (0.322) la exactitud es
96.5 %, con 0.6 % de falsas alarmas.

Y la propiedad que se buscaba, con plantillas construidas a 30 fps y probadas
sobre el mismo material decimado a 15:

| | aplausos reconocidos |
|---|---|
| fase 0 | 9/10 |
| fase 1 | 10/10 |

### Lo que hace falta antes de usarlo en vuelo

Un **dataset**: varias repeticiones de cada gesto, grabadas con las cámaras
finales. DTW no necesita entrenamiento —una repetición ya es plantilla— pero el
umbral sale de medir sobre repeticiones reales y sobre material donde el gesto
*no* ocurre. Sin las dos mitades, un umbral es una opinión;
`umbral_por_separacion()` calcula el que mejor las separa y devuelve la
exactitud, que es lo que dice si el gesto se separa de verdad.

### Probar el vocabulario completo: `probar_vocabulario.py`

Junta todo lo que la visión produce en una sola ventana y le pone delante un
**dron simulado** con estado (modo de control, en el aire, comportamiento,
velocidad), para ver si el vocabulario funciona como secuencia y no sólo
gesto a gesto.

```powershell
python .\external\gesture_detection\probar_vocabulario.py
python .\external\gesture_detection\probar_vocabulario.py --paro pecho --margen 0.05
python .\external\gesture_detection\probar_vocabulario.py --estado-estatico
python .\external\gesture_detection\probar_vocabulario.py --solo-dinamicos   # solo el canal DTW, banco plantillas_dinamicas.npz
```

La lógica de qué gesto vale en qué modo vive en `recognition/vocabulario.py`
(`MaquinaDeModos`): el `Simulador` del probador y el controlador real
(`controllers/single_drone/camera/control_camara_dron1.py --reconocedor
vocabulario`) usan la misma. La máquina no lleva la cuenta de si el dron está
en el aire: se lo dice el simulador o el backend en cada decisión, para que un
despegue rechazado no los desincronice.

**Dos modos excluyentes, y el aplauso conmuta.** Probado en vivo con todo
activo a la vez, los estáticos y los dinámicos se pisan, y ABAJO es el peor
caso: un brazo abajo y al frente es por donde pasan los brazos al empezar y
terminar cualquier gesto dinámico. Por eso los canales no conviven:

| modo | gestos activos | qué hace el simulador |
|---|---|---|
| **dinámico** (al arrancar) | senalero | despega en el suelo, aterriza en el aire |
| | ven_aca, arco, circulo | SEGUIR / ALEJARSE / ORBITAR, sólo en el aire |
| **estático** | ARRIBA, ABAJO, ADELANTE, ATRAS, IZQUIERDA, DERECHA | velocidad manual mientras se sostiene, sólo en el aire |
| ambos | aplaudir | cambia de modo y deja el dron en hover |
| ambos | X sobre la cabeza, 1 s | paro: aterriza, vuelve a modo dinámico |

El aplauso es el único gesto dinámico que se escucha en modo estático. Los
DESPEGAR / ATERRIZAR / STOP estáticos de `body_3d_rules` quedan desactivados
por defecto, porque el senalero y la X los sustituyen; `--estado-estatico` los
activa dentro del modo estático para compararlos. Todo lo que llega en el modo
que no le corresponde se muestra como "ignorado" con el motivo.

El paro vive en `recognition/paro_estatico.py`. La X va **sobre la cabeza** y no
sobre el pecho porque la del pecho es, medida, la postura casual de cruzarse de
brazos: mismas alturas y misma distancia al hombro contrario, con 5 cm de
margen. La de la cabeza no se sostuvo más de 0.2 s en ninguna de las 300 tomas
del dataset. `--paro pecho` conserva la otra para compararlas en vivo.

**Por qué el segmentador cierra relativo al pico.** En la primera sesión en
vivo el aplauso fallaba una de cada tres veces, y los segmentos guardados con
`--guardar-segmentos` dijeron por qué: la rapidez de las muñecas con las manos
ya quietas rondaba 0.5-0.9 torsos/s, por encima del umbral absoluto de cierre
de 0.35, así que el segmento no cerraba nunca y se tiraba entero como
"demasiado largo". Además el reconocedor en vivo tomaba el **máximo** de los
dos últimos frames en vez de la media móvil que usan las plantillas. Ahora la
rapidez se promedia igual en los dos sitios, el cierre y el recorte de quietud
exigen bajar del 15 % del pico del propio gesto, y sobre los 24 segmentos de
esa sesión los aplausos reconocidos pasan de 9 a 13 y los "demasiado largo" de
6 a 2, que son dos tramos de movimiento continuo. Con el banco reconstruido con
el mismo recorte, el dataset dejando fuera a cada persona sube de 76.8 % a
79.5 % y el aplauso de 36 a 41 de 45.

**Qué número se puede publicar.** El umbral que guarda el banco se elige
maximizando la separación sobre las mismas distancias que se reportan, así que
esa exactitud sale optimista. `construir_plantillas.py` imprime además una
**validación anidada**: el umbral se vuelve a medir dentro de cada pliegue,
dejando fuera a otra persona, de modo que nunca ve a quien se evalúa. Sobre el
vocabulario de cinco gestos la diferencia va de 79.5 % a **77.6 %**, con
macro-F1 0.77. Junto a la exactitud salen precisión, exhaustividad y F1 por
clase —la exactitud sola esconde que rechazar funciona la mitad de bien que
reconocer— y las tablas se guardan en CSV bajo
`results/data/validacion_dtw/<fecha>/`. El código compartido de evaluación vive
en `recognition/evaluacion.py`.

**Un umbral por gesto, no uno solo.** Cada gesto lleva su propio umbral, medido
sobre las distancias con las que se lee ese gesto. `aplaudir` necesita 0.373 y
el global es 0.708: con el global se traga los `ven_aca` y los movimientos
ajenos que pasan cerca, con el suyo deja de hacerlo. Los comandos inventados a
partir de un movimiento ajeno bajan de 17 a 10 de 41 en el vocabulario de cinco
gestos y de 14 a 6 de 30 en el de tres; lo que se paga es que `aplaudir` se lee
0.78 de las veces en vez de 0.91. Las dos cifras se reportan en cada corrida y
`--umbral-unico` vuelve al comportamiento anterior. Los bancos guardados antes
de este cambio siguen cargando: sin umbrales por gesto usan el global.

### Flujo completo: grabar, construir el banco, probar

Los tres pasos, en orden, con el dataset actual. Todo desde la raíz de `tesis`
y con su `.venv` activado (si el `python` activo es el de `mapeo3d`, MediaPipe
1.0 no trae `mp.solutions` y el detector lo dice; usar
`.\.venv\Scripts\python.exe` en lugar de `python`).

**1. Grabar a una persona nueva.** Una sesión son 54 tomas, unos 10-15 min.
La carpeta de destino es `results\data\gestos\<fecha de hoy>`.

```powershell
python .\external\gesture_detection\grabar_vocabulario.py --persona nombre
```

**2. Construir el banco con DTW.** Sin argumentos ya construye el vocabulario
vigente: los cinco gestos, `otro` como clase de rechazo y las sesiones que
enumera `CARPETAS_VOCABULARIO`, y lo guarda en `models\plantillas_vocabulario.npz`.

```powershell
python .\external\gesture_detection\construir_plantillas.py
```

**Al grabar otro día hay que añadir esa fecha a `CARPETAS_VOCABULARIO`**, en la
cabecera de `construir_plantillas.py`. No vale apuntar a `results\data\gestos`
entera: las sesiones del 5 y 6 de septiembre traen etiquetas viejas (`aplauso`,
y un `arco` que era tensar una flecha) y contaminarían el banco. Para elegir
las carpetas a mano, sin tocar el archivo:

```powershell
python .\external\gesture_detection\construir_plantillas.py --carpeta results\data\gestos\2026-09-07 results\data\gestos\2026-09-08 --gestos senalero,aplaudir,ven_aca,arco,circulo --negativos otro --salida models\plantillas_vocabulario.npz
```

Imprime la validación dejando fuera a cada persona (matriz de confusión,
precisión y exhaustividad por gesto, umbral por gesto) y deja los CSV en
`results\data\validacion_dtw\<fecha>\`. Con 8 personas y 427 tomas
(2026-09-08): acierto 79.4 %, anidado 78.9 %, macro-F1 0.79.

**3. Probar en vivo**, con el banco recién construido:

```powershell
python .\external\gesture_detection\probar_vocabulario.py
python .\external\gesture_detection\probar_vocabulario.py --guardar-segmentos --persona nombre
```

**Pruebas sin cámara** del paro, del simulador y del guion de grabación:

```powershell
python -m pytest -q external\gesture_detection\tests
```

### Explicar los gestos: `visualization/esquema_gestos_dinamicos.py`

Los gestos de mano tenían su lámina (`visualization/esquema_gestos_mano.m`, en
MATLAB). Los dinámicos necesitan otra cosa, porque **no son una postura sino un
recorrido**: una figura quieta no distingue `aplaudir` de tener las manos en el
pecho. Este script dibuja el recorrido, y en Python porque lee las tomas
grabadas con los mismos cargadores que el reconocedor.

```powershell
python .\external\gesture_detection\visualization\esquema_gestos_dinamicos.py
python .\external\gesture_detection\visualization\esquema_gestos_dinamicos.py --animar
python .\external\gesture_detection\visualization\esquema_gestos_dinamicos.py --gestos aplaudir,circulo --animar
```

Deja en `results\graphs\gestos_dinamicos\<hoy>\` una lámina en PNG a 300 ppp y
en PDF vectorial, y con `--animar` un **GIF por gesto**: el esqueleto moviéndose
a su velocidad real, con la estela de las muñecas detrás. El GIF es lo que hay
que enseñarle a quien va a hacer el gesto por primera vez; la lámina es lo que
va al documento.

Tres decisiones que conviene no deshacer:

| | por qué |
|---|---|
| Las coordenadas salen de las **tomas grabadas**, no de dibujos | la lámina enseña lo que hicieron las ocho personas, no lo que uno cree que hacen. De cada gesto se toma el **medoide** por DTW entre las tomas frontales: la que menos dista de las demás de su clase |
| **De frente y de perfil** | `ven_aca` va hacia el cuerpo, o sea en profundidad; sólo de frente parece que no se mueve |
| **Una sola escala en toda la lámina** | si cada celda se ajustase a su gesto, un `ven_aca` de 20 cm y un `arco` de brazos abiertos saldrían del mismo tamaño, y la amplitud es justo una de las cosas que separa un gesto de otro |

La ventana del dibujo se calcula sólo con los landmarks que se pintan. Con los
33 de MediaPipe llegaría hasta los tobillos, a 2.4 torsos por debajo de la
cadera, y el cuerpo saldría a un tercio de su tamaño; la prueba
`tests/test_esquema_gestos_dinamicos.py` lo fija.

### Grabar el vocabulario final: `grabar_vocabulario.py`

Es el grabador de arriba con el guion del vocabulario que va a volar. Pone
solo el gesto, el ángulo y el número de toma; el operador sólo pulsa ENTER.

```powershell
python .\external\gesture_detection\grabar_vocabulario.py
python .\external\gesture_detection\grabar_vocabulario.py --solo senalero,circulo
python .\external\gesture_detection\grabar_vocabulario.py --sin-negativos
```

Una sesión son 54 tomas, unos 10-15 minutos por persona:

| qué | cuántas | para qué |
|---|---|---|
| `senalero`, `aplaudir`, `ven_aca`, `arco`, `circulo` | 2 × 4 ángulos (0, ±45, 90) | plantillas de DTW |
| `paro` (X sobre el pecho, sostenida) | 1 por ángulo | umbrales de la regla estática |
| `reposo` (30 s parado, cruzándose de brazos) | 2 | tasa de falsos paros de emergencia |
| `otro` (saludar, estirarse, rascarse…) | 8 | clase de rechazo del banco |

Hacen falta **al menos cuatro personas**, y mejor seis: el umbral se mide
dejando fuera a cada persona, así que con tres, cada medida se apoya en sólo
dos. Que haya estaturas y lateralidades distintas importa más que el número.

```powershell
python -m pytest -q external\gesture_detection\tests\test_grabar_vocabulario.py
```

### Grabar el dataset y decidir con datos

Los números de arriba salen de una grabación hecha para otra cosa. Para
decidirlo bien hace falta material grabado a propósito:

```powershell
python .\external\gesture_detection\grabar_gestos.py
python .\external\gesture_detection\grabar_gestos.py --gesto reposo
python .\external\gesture_detection\comparar_2d_3d.py
```

`grabar_gestos.py` pregunta nombre y número de toma, abre la cámara para que te
encuadres, y graba entre un ENTER y el siguiente. El panel avisa si el cuerpo no
se ve completo o si las manos rozan el borde superior, que es lo que pasa al
levantar el brazo.

Todo se hace en una sola sesión: `g` cambia de gesto y `o` de orientación sin
salir del programa. **Cada toma tiene que ser un solo ángulo y un solo gesto**
—si te girás a mitad de toma, la etiqueta miente— pero las tomas van una
detrás de otra. El número de toma se lleva por combinación de gesto y ángulo,
así que cambiar de una a otra no pisa la numeración.

Cada toma guarda **las dos representaciones**: `pose_world_landmarks` (3D) y
`pose_landmarks` (2D de imagen). No es redundante — una proyección del 3D
hereda el prior de profundidad del modelo, así que no sirve como línea base 2D:
favorecería al 3D por construcción.

Qué hace falta para que el material sirva:

| | por qué |
|---|---|
| **Al menos dos gestos** | sin material negativo cualquier umbral da 100 % |
| **Cinco repeticiones o más de cada uno** | una plantilla sola no cubre la variación entre repeticiones |
| **El mismo gesto girado** (`--orientacion 30`, `60`, `90`) | con una cámara, girar al operador equivale a mover la cámara: es la única forma honesta de medir si una plantilla transfiere entre las vistas del anillo |

`comparar_2d_3d.py` evalúa 1-NN con DTW **dejando fuera la propia toma**, y
reporta exactitud, matriz de confusión y separación —la distancia mediana entre
gestos distintos dividida por la del mismo gesto—. Las dos cosas importan: una
exactitud del 100 % con separación 1.1x se cae con la primera persona nueva.

### ¿Y en 2D?

El mismo experimento con rasgos del plano de imagen —las mismas cuatro
articulaciones en `(x, y)`, centradas en las caderas y normalizadas por el ancho
de hombros—. La medida es la separación entre «aplauso contra aplauso» y
«aplauso contra lo demás»:

| | 0° | 30° | 60° | 90° |
|---|---|---|---|---|
| 3D canonicalizado | 3.4x | 3.4x | 3.4x | 3.4x |
| 2D, plantillas hechas de frente | 3.3x | 1.7x | 1.3x | 0.2x |
| 2D, **plantillas por cámara** | 3.3x | 3.5x | 3.6x | 1.6x |

Dos conclusiones, y la primera es buena noticia:

1. **En 2D funciona, si cada cámara guarda sus propias plantillas.** Hasta 60° la
   separación iguala a la del 3D. Una trayectoria completa aguanta el cambio de
   punto de vista mucho mejor que un umbral escalar: el detector de episodios en
   2D se caía a 8/10 recalibrando, y aquí no se cae.
2. **Lo que cuesta es el dataset.** Las plantillas no transfieren entre cámaras:
   con plantillas frontales, a 60° la separación baja a 1.3x y no detecta nada.
   Seis cámaras significan grabar cada gesto seis veces. Con 3D es un solo juego.

De perfil (90°) se rompe igual: el normalizador es el ancho de hombros y tiende
a cero.

La fila de 3D es idealizada. Este experimento rota los landmarks 3D para simular
otras cámaras, así que la canonicalización sale invariante **por construcción**.
No mide la debilidad real del 3D monocular, que es que la profundidad estimada
se degrada desde vistas oblicuas. Eso sólo lo dirá material grabado con las seis
cámaras.

## Usar una cámara IP en vez de la webcam

`probar_vocabulario.py` y `probar_gestos_3d.py` aceptan `--rtsp` con la URL de
una cámara IP:

```powershell
.\.venv\Scripts\python.exe .\external\gesture_detection\probar_vocabulario.py `
    --rtsp "rtsp://usuario:clave@192.168.1.50:554/cam/realmonitor?channel=1&subtype=1"
```

Las comillas son necesarias: el `?` y el `&` de la ruta Amcrest los interpreta
el shell si van sueltos.

**No usar `--video` con una URL RTSP.** Funciona, pero mal, y las dos razones no
se ven venir:

1. **OpenCV negocia UDP por defecto** para RTSP. Sobre Wi-Fi eso significa
   paquetes perdidos sin retransmisión: la imagen se pixela y los macrobloques
   dañados se arrastran hasta el siguiente I-frame. `--rtsp` fuerza TCP.
2. **La lectura síncrona acumula latencia sin límite.** Con una webcam el driver
   descarta los frames viejos; por RTSP se encolan. Si el bucle de visión va más
   lento que la cámara —y con MediaPipe siempre va más lento— el retraso crece
   hasta hacer inútil cualquier prueba en vivo. `--rtsp` lee en un hilo aparte y
   conserva **sólo el último frame**.

Medido contra una Amcrest a 30 fps con el consumidor a 6.4 fps: se descarta el
**78 %** de los frames por frescura. Con lectura síncrona esos frames se
encolarían, o sea ~5 s de retraso acumulados en 6 s de uso.

El lector vive en [`video_source.py`](video_source.py). Duplica a propósito lo
que `external/mapeo3d` ya resuelve en `capture/stream.py`; el motivo está en el
docstring y en la decisión del vault del 2026-09-09.

### Latencia: dónde se van los 800 ms y cómo bajarlos

Medido el 2026-09-17 con la IP4M-1041B por cable: **~800 ms** entre el gesto y
su imagen, con el lector de arriba ya en marcha. No es la red ni MediaPipe
(13 ms). Se reparte en tres sitios, y los tres tienen arreglo:

| Dónde | Cuánto | Arreglo |
|---|---|---|
| Decodificador H.264 de FFmpeg con un hilo por núcleo: entrega cada frame `hilos − 1` frames tarde | ~230 ms en un PC de 8 núcleos | `video_source.py` abre con **un solo hilo** (`CAP_PROP_N_THREADS=1`). Automático. |
| Audio en el stream: FFmpeg intercala audio y vídeo y espera al más lento | 100–200 ms | Desactivar el audio en la cámara. Lo hace `configurar_camara.py`. |
| Encoder del stream principal a 720p | 300–500 ms | Usar el **sub-stream** (`subtype=1`) a 704x480, 30 fps, H.264 CBR. Lo deja así `configurar_camara.py`. |

```powershell
# Muestra la configuración actual del encoder y lo que cambiaría. No toca nada.
.\.venv\Scripts\python.exe .\external\gesture_detection\configurar_camara.py `
    --rtsp "rtsp://usuario:clave@IP:554/cam/realmonitor?channel=1&subtype=1"

# Aplica: sub-stream 704x480 @ 30 fps H.264 CBR 1024 kbps GOP 30, audio fuera en los dos streams.
.\.venv\Scripts\python.exe .\external\gesture_detection\configurar_camara.py `
    --rtsp "rtsp://usuario:clave@IP:554/cam/realmonitor?channel=1&subtype=1" --aplicar
```

Sólo escribe las claves que difieren, porque reescribir la tabla `Encode`
reinicia el encoder y corta el stream a quien lo esté leyendo. El stream
principal queda como estaba, salvo el audio. Para MediaPipe la resolución del
sub-stream sobra: reescala internamente a ~256 px.

Con los tres arreglos, estas cámaras quedan en **200–350 ms**. Menos de ~150 ms
no es posible por RTSP con un Amcrest: el encoder pone ese suelo. Para medirlo,
apuntar la cámara al monitor y, desde `external/mapeo3d`:

```powershell
python apps\diagnose_camera.py --url "rtsp://usuario:clave@IP:554/cam/realmonitor?channel=1&subtype=1" --sin-pose --segundos-fps 10
```

## Gestos con la cámara siguiéndote: `probar_vocabulario.py --seguir`

Reconocimiento de gestos y seguimiento PTZ en el mismo bucle. La cámara te
mantiene encuadrado mientras te movés por el área, y el vocabulario completo
sigue funcionando igual.

```powershell
.\.venv\Scripts\python.exe .\external\gesture_detection\probar_vocabulario.py `
    --rtsp "rtsp://usuario:clave@IP:554/cam/realmonitor?channel=1&subtype=1" --seguir
```

`--seguir` necesita `--rtsp`: el host y las credenciales del PTZ salen de esa
misma URL, para que el vídeo y el control no puedan apuntar a cámaras distintas.
Con `--ptz-dry-run` decide pero no mueve los motores.

### El gesto manda sobre el encuadre

Es la regla que hace que esto funcione, y no es obvia: **mientras hay un gesto
en curso, la cámara no se mueve.**

Girar durante un gesto lo contamina por dos vías a la vez. El motion blur
ensucia los landmarks, y el propio giro añade movimiento aparente a las manos
que el reconocedor no distingue del movimiento real —y los gestos dinámicos se
clasifican justamente por la trayectoria de las manos. Encuadrar bien no sirve
de nada si a cambio se pierde lo que se quería leer.

Así que `rec.en_segmento` tiene prioridad... **pero no absoluta**, y ésa fue la
lección medida contra la cámara.

`en_segmento` no significa "está haciendo un gesto": significa "se está
moviendo". **Caminar abre segmento**, y caminar es exactamente cuando hace falta
seguir. Con prioridad absoluta, medido sobre 20 s reales, el segmento estaba
abierto el 85 % del tiempo y se bloqueaban **10 de cada 11** correcciones: el
seguimiento quedaba inservible.

De ahí dos escapes, ambos con el valor sacado de datos:

- **`error_critico` (0.28).** Si la persona está a punto de salirse del cuadro,
  el encuadre gana. Un gesto que no se ve no se puede clasificar igualmente, así
  que protegerlo a costa de perder a la persona no protege nada.
- **`bloqueo_max_s` (4.0 s).** Un segmento no puede retener la cámara más que
  cualquier gesto real. Sobre 655 tomas del dataset la mediana de un gesto es
  3.5 s; lo que dure más es locomoción. (El propio reconocedor descarta
  segmentos de más de 7 s.)

La regla vive en `Seguidor.decidir_con_gesto()`, separada del bucle para poder
probarla sin cámara.

**Además, los frames tomados con la cámara girando se marcan como huecos** en
vez de alimentarlos al reconocedor. Unos landmarks borrosos inventan segmentos
que no existen; un hueco es lo honesto, y el reconocedor ya sabe manejarlos. La
ventana incluye el enfriamiento, porque la orden de parada tarda ~300 ms en
llegar y el motor sigue girando después de decidirla.

El overlay muestra el estado de la cámara: `centrada`, `siguiendo Right` o
`quieta (gesto en curso)`.

### Ajustes

Los mismos que `seguir_persona.py`, con los más útiles expuestos:
`--zona-muerta`, `--zona-muerta-tilt`, `--centro-y`, `--velocidad-max`,
`--sin-tilt`.

**El tilt sigue por defecto**, pero con una zona muerta propia: el pan manda
(una persona que camina se descentra sobre todo en horizontal) y el tilt sólo
arranca cuando el pan ya está centrado. Desde el 2026-09-12 los lanzadores
igualan la zona muerta del tilt a la del pan (`--zona-muerta`, 0.16); la de
fábrica del módulo, 0.20, casi nunca se alcanzaba de pie a 3 m y por eso
parecía que sólo seguía en horizontal. Para verlo inclinar sin caminar,
`--zona-muerta-tilt 0.08`. `--centro-y 0.6` deja el torso por debajo del centro
y aire por encima de la cabeza para las manos levantadas (senalero, X del paro).

Si notás que pierde gestos, subí `--zona-muerta`: la cámara se moverá menos y
habrá menos frames descartados. Si notás que te sales del cuadro, bajala.

## Seguir al operador con una cámara PTZ: `seguir_persona.py`

Cierra el lazo entre la pose 2D y el pan/tilt de una cámara Amcrest: la persona
se mueve, MediaPipe dice dónde está dentro del cuadro, y la cámara gira hasta
volver a centrarla.

```powershell
# Sin mover motores: valida el lazo entero e imprime lo que enviaría.
.\.venv\Scripts\python.exe .\external\gesture_detection\seguir_persona.py `
    --rtsp "rtsp://usuario:clave@IP:554/cam/realmonitor?channel=1&subtype=1" --dry-run

# De verdad.
.\.venv\Scripts\python.exe .\external\gesture_detection\seguir_persona.py `
    --rtsp "rtsp://usuario:clave@IP:554/cam/realmonitor?channel=1&subtype=1"
```

`q` sale (y para el motor), `espacio` pausa el seguimiento. El overlay dibuja la
zona muerta, el error horizontal, el estado del motor y los fps.

### Aviso antes de usarlo

**Mover la cámara invalida cualquier calibración extrínseca previa, sin síntoma
visible.** Este código existe porque el proyecto pospuso la calibración
(decisión del 2026-09-09 en el vault). Si se retoma la triangulación, no usarlo
sobre una cámara que triangule.

### Las tres piezas

| Módulo | Responsabilidad |
|---|---|
| [`ptz/seguidor.py`](ptz/seguidor.py) | La política: dónde está la persona → hacia dónde y cuán rápido. Pura, sin red ni MediaPipe |
| [`ptz/cliente.py`](ptz/cliente.py) | HTTP CGI de Dahua/Amcrest con Digest, sólo stdlib |
| [`ptz/control.py`](ptz/control.py) | Aplica las órdenes en un hilo aparte |

La política está separada del transporte para poder ajustarla **sin gastar
motores**: todo `ptz/seguidor.py` se prueba con datos sintéticos.

### Por qué el diseño es así

Tres decisiones que parecen arbitrarias y no lo son. Están medidas.

**Velocidad, no posición absoluta.** Convertir "está a 0.3 del borde" en "gira
12 grados" exige el FOV horizontal, y el de la Amcrest sigue sin medir. Con
arrancar/parar no hace falta: el lazo cerrado absorbe el error de escala.

**El I/O va en un hilo aparte.** Una petición HTTP a la cámara cuesta **~304 ms
de mediana** (máximo medido: 437). Hacerla dentro del bucle de visión congelaba
la detección justo mientras el motor giraba: la cámara se movía a ciegas y al
volver leía una imagen que ya no correspondía a la decisión que la originó.

**Se mueve a pasos, no en continuo.** Entre lo que el detector ve y lo que el
motor hace hay medio segundo de tiempo muerto: latencia de RTSP más los ~300 ms
del comando. Un lazo continuo con ese retraso **siempre se pasa de largo**, y no
es cuestión de ganancia: cuando se decide parar, ya se recorrió
`velocidad × tiempo_muerto` de más. Por eso cada corrección es un paso acotado.

(MediaPipe **no** entra en ese presupuesto: medido sobre un frame real cuesta
13 ms, unos 75 fps. La latencia de visión es decodificación RTSP, y bajar la
resolución de proceso no la mejora.)

**Se espera a ver el paso, no a que pase un tiempo.** Un temporizador fijo
obliga a adivinar la latencia de visión, y adivinarla de menos es exactamente lo
que produce la oscilación. En vez de eso, al parar se guarda dónde estaba la
persona y **no se manda otro paso hasta que su posición en el cuadro cambie**
al menos `--cambio-minimo`. Eso se adapta solo a la latencia real, sin medirla.
`--espera-max` es la válvula de escape para cuando la persona camina justo al
ritmo de la cámara y el error no cambia nunca.

### El paso mínimo lo fija la red, no el temporizador

`ControlPTZ` serializa las peticiones: primero llega `start`, después `stop`, y
cada una cuesta ~300 ms. El motor gira **desde que llega una hasta que llega la
otra**, así que bajar `--pulso` por debajo de esa latencia no acorta el paso.
Para pasos más pequeños hay que bajar la **velocidad**.

En simulación con las latencias medidas, el lazo es estable por debajo de unos
**140 °/s** a velocidad 1, y la espera por confirmación sube ese umbral a ~180.
Por encima de eso un solo paso recorre más que toda la zona muerta y **ninguna
política basada en tiempo lo arregla**: haría falta posicionamiento absoluto,
que la cámara sí soporta (`caps.MoveAbsolutely=true`) pero que exige conocer el
FOV horizontal, todavía sin medir.

### Ajustes

| Síntoma | Mando |
|---|---|
| Se pasa del objetivo | `--velocidad-max 1` (pasos más cortos de verdad) |
| Sigue oscilando | `--cambio-minimo 0.04` (más prudente antes de encadenar) |
| Reacciona a cualquier movimiento | `--zona-muerta 0.25` |
| Tarda en alcanzarte | `--velocidad-max 3` o `--espera-max 0.6` |
| El tilt marea | `--sin-tilt`, o `--zona-muerta-tilt 0.25` |
| No inclina nunca | `--zona-muerta-tilt 0.08` |
| Corta las manos levantadas | `--centro-y 0.6` (el torso más abajo, aire arriba) |
| Movimiento continuo (comportamiento anterior) | `--pulso 0` |

El mando principal es **la velocidad**, no la duración del paso.

## Medir la cámara: `medir_ptz.py`

Cuánto recorre un paso depende de la velocidad angular del motor, que no está
publicada en ninguna hoja de datos. Este script la mide, y de paso mide la
repetibilidad yendo y volviendo el mismo paso:

```powershell
.\.venv\Scripts\python.exe .\external\gesture_detection\medir_ptz.py `
    --rtsp "rtsp://usuario:clave@IP:554/cam/realmonitor?channel=1&subtype=1" --confirmar
```

**Mueve los motores**, por eso exige `--confirmar`: sin ese argumento explica lo
que haría y sale.

Dice en qué régimen está la cámara (estable / límite / rápido) y por tanto si
los ajustes por defecto sirven. El residuo al ir y volver es la repetibilidad
del motor, que es el número que decidiría si la vía de los presets serviría para
recuperar una calibración el día que se retome.

## Instalación en Windows CMD

1. Abre `cmd` en la raíz del repositorio.
2. Ejecuta:

```bat
py -3.11 -m venv .venv
.\.venv\Scripts\activate.bat
python -m pip install --upgrade pip setuptools wheel
pip install -r .\external\gesture_detection\requirements.txt
```

## Instalación en Windows PowerShell

1. Abre PowerShell en la raíz del repositorio.
2. Ejecuta:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
pip install -r .\external\gesture_detection\requirements.txt
```

## Detector manual de manos (modo anterior)

Ejecuta:

```powershell
python .\external\gesture_detection\main_hands.py
```

Si la cámara no abre, cambia `CAMERA_INDEX` en `external/gesture_detection/config.py`. Los scripts 3D usan el argumento `--camera`.

## Gestos reconocidos por el modo anterior

- `DESPEGAR`: índice y medio extendidos, con la mano hacia arriba.
- `ATERRIZAR`: índice y medio extendidos, con la mano hacia abajo.
- `STOP`: puño cerrado.
- `DERECHA`: pulgar extendido y los demás dedos cerrados.
- `IZQUIERDA`: meñique extendido, con la mano hacia arriba.
- `ARRIBA` y `ABAJO`: índice extendido y orientación correspondiente.
- `ADELANTE`: pulgar e índice extendidos.
- `ATRAS`: pulgar y meñique extendidos.
- `SEGUIR_MARKER`: únicamente el dedo medio extendido.
- `DETENER_SEGUIMIENTO`: símbolo de rock, con índice y meñique extendidos; el
  pulgar puede estar abierto o cerrado.
- `REPOSO` y `SIN_DETECCION`: estados sin comando activo.

## CSV del modo anterior

El archivo `results/data/gesture_detection/<YYYY-MM-DD>/gestos_mano_detectados.csv` guarda un registro de cada frame con:

- timestamp
- command_raw
- command_filtered
- orientación y estado extendido de cada dedo
- posiciones normalizadas de la muñeca y las puntas de los dedos

Sirve para análisis posterior y validación de detección.

## Qué hacer si MediaPipe falla

- Asegúrate de que el entorno virtual tenga `mediapipe` instalado.
- Verifica que usas `py -3.11` y un Python 3.11 compatible.
- Prueba ejecutar `python -c "import mediapipe; print(mediapipe.__version__)"`.

## Nota de seguridad

Esta etapa es solo simulación. No se conecta al dron real, no se envían comandos a motores ni a hardware.
