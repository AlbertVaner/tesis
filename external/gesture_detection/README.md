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

El consumidor con dron es `controllers/single_drone/camera/control_corporal_dron1.py`; la tabla de gestos y cómo se hacen está en el README de esa carpeta.

```powershell
python .\external\gesture_detection\tests\test_body_3d_rules.py
```

## Gestos dinámicos: aplausos y secuencias

El vocabulario de arriba lee **posturas**. Un aplauso o una celebración no son
una postura: son un recorrido. Eso vive en otras dos piezas.

```text
recognition/dinamicos.py        segmentación por movimiento y banco de plantillas
recognition/dtw.py              distancia DTW y umbral por separación
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
