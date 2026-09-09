# Estimación de landmarks 2D

Estado: `[parcial]` — `Landmarks2D`, el esqueleto, los pares de huesos,
`PoseDetector` sobre la Tasks API, el **marco corporal** (`canonical.py`),
los **eventos temporales** (`eventos.py`) y el dibujado están `[implementado]` en `src/mapeo3d/pose/`, junto con
`apps/check_pose3d.py`, `apps/demo_pose3d.py` y `apps/diagnose_camera.py`.
La selección de vista entre varias cámaras sigue `[planeado]`.

`pose/` **no sabe que existen varias cámaras**. Recibe una imagen y devuelve
landmarks 2D normalizados con su confianza. La agregación multivista es de
[triangulation.md](triangulation.md). Ver AGENTS.md, punto 3.

## «MediaPipe 3D» son dos cosas distintas

Es la confusión más cara de este proyecto, porque las dos se llaman igual y
responden preguntas diferentes.

| | `pose_world_landmarks` | triangular `pose_landmarks` |
|---|---|---|
| Origen | punto medio de las caderas | la cámara A, luego el marco Robotat |
| Unidades | metros | metros |
| De dónde sale la profundidad | **un prior aprendido** de la red | **geometría** de N vistas calibradas |
| Necesita calibración | no | sí |
| «el brazo está a 45°» | sí | sí |
| «la mano está en este punto de la sala» | **no, nunca** | sí |

La estimación monocular es 3D de verdad y es gratis, pero **no sabe dónde está
el sujeto en la sala**, que es justamente lo que da valor a este repositorio
(ver [architecture.md](architecture.md)). No sustituye a la triangulación.

Sí sirve como **término de comparación**: `PoseDetector` la devuelve en
`Landmarks2D.world` porque MediaPipe ya la calcula en la misma llamada y no
cuesta nada extra. Medir la estabilidad de longitud de huesos sobre las dos
—triangulación calibrada y estimación monocular— sobre la misma grabación es
una comparación directa, en las mismas unidades, que no necesita MoCap. Ver
[triangulation.md](triangulation.md).

## MediaPipe 1.0 eliminó `mp.solutions`

`[implementado]` — `src/mapeo3d/pose/detector.py` usa la **Tasks API**.

Es una ruptura y hay que tenerla presente al mover código entre repositorios:

| | `mediapipe` 0.10.x | `mediapipe` 1.0+ |
|---|---|---|
| `mp.solutions.pose.Pose(...)` | existe | **eliminado** |
| `PoseLandmarker` (Tasks) | existe | existe |
| Modelo | incluido en el paquete | **archivo `.task` aparte** |

El repositorio `tesis` corre 0.10.14 y su `external/gesture_detection/pose/detector.py`
usa `mp.solutions`; sus dos rutas de importación fallan con 1.0. Este
repositorio corre 1.0.1. **No portar ese archivo tal cual.**

La Tasks API además encaja mejor con seis cámaras: `RunningMode.VIDEO` mantiene
el tracking entre frames por instancia, y cada cámara tiene la suya.

### El modelo se descarga una vez

```powershell
mkdir models
curl -L -o models\pose_landmarker_lite.task https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task
```

Se busca, en orden: el argumento explícito, `MAPEO3D_POSE_MODEL`, y `models/`
en la raíz. `models/` no se versiona: es un binario descargado, no fuente.

## Costo: el cómputo no es el cuello de botella

`[implementado]` — medido, no estimado. Intel de 24 núcleos, frames de
1280×720, **un proceso por cámara**, Tasks API con `pose_landmarker_lite`:

| procesos | ms/frame | fps/cámara | fps agregados |
|---|---|---|---|
| 1 | 10.2 | 98.5 | 98.5 |
| 2 | 10.6 | 94.1 | 188.1 |
| 4 | 13.5 | 73.9 | 295.4 |
| **6** | **16.0** | **62.5** | **375.2** |

El escalado es casi lineal: de 1 a 6 procesos el costo por frame sólo sube un
57 %. **Seis cámaras a 30 fps caben con holgura.**

Para comparar, la API vieja (`mp.solutions`, mediapipe 0.10) daba 19.1 ms con
seis procesos en `lite` y 33.9 ms en `full` — o sea 52.3 y 29.5 fps por cámara.
La Tasks API es más rápida, y `full` seguiría cabiendo pero justo, sin margen
para decodificar seis H.264.

La consecuencia de diseño es que el cuello de botella de un sistema de seis no
es la inferencia sino la **decodificación de los seis streams H.264**, que va
en el mismo proceso que la cámara. Por eso la topología es un proceso por
cámara y no un pool de inferencia.

Estas cifras se midieron con una figura sintética; con una persona real el
costo del modelo de landmarks es el mismo, porque la entrada a la red tiene
tamaño fijo.

## Lo que Pose ve y lo que no

33 landmarks. En la mano sólo hay cuatro —muñeca, meñique, índice y pulgar— y
**no dan la configuración de los dedos**. Eso decide qué gestos son posibles:

| Gesto | ¿Con Pose? |
|---|---|
| Brazos arriba, inclinación del torso, postura estática | sí |
| Aplaudir | sí, por proximidad de muñecas — pero ver abajo |
| Secuencia dinámica (celebración, baile) | sí, con ventana temporal |
| Forma de mano (dedos concretos) | **no** — hace falta MediaPipe Hands |

**Aplaudir parecía un problema de frame rate. No lo era: era el detector.**
El contacto dura 50–100 ms, que a 15 fps es un frame, así que buscar el
*instante* del contacto pierde eventos. Pero buscar el **episodio** —las manos
se acercan, se juntan, se separan— abarca 400–600 ms y sobrevive a cualquier
tasa razonable. Ver «Eventos» más abajo, donde está medido.

Correr Holistic (Pose + dos manos + cara) en las seis cámaras no cabe en el
presupuesto de cómputo. La combinación viable es **Pose en las seis y Hands
sólo en una o dos vistas**, las que mejor vean las manos en ese instante.

## Interfaz implementada

```
Landmarks2D(xy, visibility, presence, image_size, timestamp, world, camera)
    .to_pixels()   -> (K, 2) en píxeles, para triangular
    .confianza()   -> (K,) peso para el DLT ponderado
    .n             -> número de landmarks
    lm["left_wrist"] -> posición normalizada por nombre

PoseDetector(model_path=None, *, camera, min_deteccion, min_presencia,
             min_tracking, con_world)
    .detect(frame_bgr, timestamp_s) -> Landmarks2D | None
    .close()                          también gestor de contexto

NOMBRES, INDICE, N_LANDMARKS, HUESOS, pares_de_huesos()
```

`confianza()` devuelve `visibility` a secas: MediaPipe la define como la
probabilidad de que el landmark **no esté ocluido**, que es exactamente el
criterio por el que una vista debe pesar más o menos en el DLT.

`presence` responde otra pregunta —si el landmark está dentro del cuadro— y
**no vale siempre 1**: se ha observado entre 0.06 y 0.91 en una misma
detección. Se expone para filtrar, pero no se multiplica por `visibility`: son
preguntas distintas, y el producto penalizaría dos veces al mismo landmark
contra el umbral absoluto `PESO_MINIMO` de `triangulation.robust`.

`pose/detector.py` importa MediaPipe **de forma perezosa**, así que
`pose.landmarks` y las pruebas funcionan en una máquina sin MediaPipe
instalado.

### Un detalle que rompe la cámara entera si se ignora

`RunningMode.VIDEO` exige marcas de tiempo en milisegundos **estrictamente
crecientes**. A 30 fps los frames distan 33 ms y no hay problema, pero al
redondear a entero dos frames cercanos pueden caer en el mismo milisegundo, y
MediaPipe lanza una excepción que mata el proceso de esa cámara. `PoseDetector`
lleva un contador propio y fuerza el avance.

## Coordenadas: normalizadas dentro, píxeles al salir

`Landmarks2D.xy` guarda `[0, 1]` —`x/ancho`, `y/alto`— porque es lo que
devuelve el backend y porque así el resultado no depende de la resolución a la
que se procesó. `to_pixels()` hace la conversión en un solo sitio.

Entre `to_pixels()` y triangular va **siempre**
`CameraIntrinsics.undistort_points()`. Es la precondición de
[triangulation.md](triangulation.md) y no falla de forma visible: el residual
sigue bajo y lo que sale sesgado es la escala.

## Medir la pose 3D monocular: `apps/check_pose3d.py`

`[implementado]`. Es el **nivel 0** del sistema: 3D métrico del cuerpo con una
cámara y cero calibración. Sirve para responder rápido si un vocabulario de
gestos es separable en 3D, antes de invertir en montar y calibrar seis cámaras.

```powershell
python apps\check_pose3d.py --url 0
python apps\check_pose3d.py --camera cam1 --record --duration 60
python apps\check_pose3d.py --url 0 --no-display --duration 30
```

La ventana muestra la cámara con el esqueleto 2D encima y, al lado, tres
proyecciones ortográficas de los landmarks 3D —frontal, perfil y planta— más
las métricas en vivo.

**La escala de las vistas 3D es fija** (±1 m). Es deliberado: una vista que se
autoescala hace imposible juzgar a ojo si el esqueleto está temblando, que es
justo lo que se viene a mirar.

### Qué mide y por qué esa medida

La **variación de la longitud de los huesos**: la desviación estándar de la
longitud reconstruida dividida por su media, promediada sobre los doce
segmentos de `HUESOS`. Un hueso rígido no puede cambiar de largo, así que todo
lo que varía es error del estimador. No necesita MoCap, ni marcadores, ni
calibración, ni verdad de terreno de ningún tipo.

Es **la misma medida** que `triangulation.metrics` aplica a la triangulación
calibrada, así que los dos números son directamente comparables sobre la misma
grabación. Ésa es la comparación que dice cuánto aporta calibrar, y es un
resultado que se puede reportar en la tesis.

Lectura orientativa del número:

| variación media | lectura |
|---|---|
| < 3 % | muy estable para ser monocular |
| 3–8 % | utilizable para gestos de forma amplia (brazos arriba, torso) |
| > 8 % | sirve para poses muy distintas entre sí, no para gestos parecidos |

Un landmark por debajo de `--min-visibilidad` se marca `NaN` y no cuenta: mete
ruido en las longitudes sin aportar información.

### Medido sobre una persona real

`[implementado]` — dos sesiones de 60 s con una Tapo C210, sujeto a unos 2-3 m.
Es la referencia contra la que comparar la triangulación calibrada.

| | sesión 1 | sesión 2 |
|---|---|---|
| completa | 13.87 % | 10.44 % |
| **bien encuadrado** | **7.90 %** | **9.05 %** |
| mal encuadrado (parcialmente fuera) | 15.55 % | 10.86 % |

**El encuadre domina el resultado.** En la primera sesión los 25 s iniciales
tenían al sujeto parcialmente fuera de cuadro: 35 % de landmarks descartados y
un ancho de hombros de 209 ± 54 mm. A partir del segundo 25, con el cuerpo
entero dentro: 7 % descartados y 332 ± 16 mm. Es el mismo sujeto, la misma
cámara y el mismo modelo; sólo cambia el encuadre.

Con la persona bien encuadrada, **la estimación monocular queda en torno al
8-9 %**, es decir justo en el límite de lo utilizable.

### El error es sistemático, no ruido: filtrar no lo arregla

Un filtro de mediana de 5 frames elimina sólo el **5-6 %** de la variación.
Eso descarta la explicación cómoda: no es temblor entre frames, es **sesgo
dependiente de la pose**. El modelo se equivoca de forma consistente durante
decenas de frames seguidos, y ningún filtro temporal —One Euro, Kalman, lo que
sea— lo va a corregir. Ver [triangulation.md](triangulation.md).

### El error se duplica al girarse de lado

Agrupando los frames por lo ancho que se ve el torso, que es una medida de
cuánto está el sujeto de frente:

| orientación | sesión 1 | sesión 2 |
|---|---|---|
| de perfil | 14.95 % | 12.82 % |
| intermedio | 10.01 % | 6.76 % |
| de frente | 7.44 % | 7.58 % |

Es exactamente el fallo esperado del prior de profundidad: cuando el cuerpo se
extiende a lo largo del eje óptico, la red tiene que adivinar justo lo que no
puede medir.

**Es el argumento empírico a favor de las seis cámaras**: en anillo, siempre
hay alguna que te ve de frente.

### No normalizar por el ancho de hombros

La literatura de gestos (Ibañez et al.) centra y escala por medida corporal
antes de clasificar, y el ancho de hombros es la elección natural. **Con
`pose_world_landmarks` es la peor posible**, porque es justo la medida más
inestable: es la que se acorta cuando el sujeto gira.

| se normaliza por | sesión 1 | sesión 2 |
|---|---|---|
| nada | 13.87 % | 10.44 % |
| **ancho de hombros** | **21.89 %** | **15.41 %** |
| largo de torso (hombro-cadera) | 11.93 % | 10.13 % |

El torso es el segmento más estable de los doce (3.8 % y 4.9 % en la sesión 2),
y es el divisor correcto.

Además, conviene **calcular la escala una vez por sesión y no por frame**. El
coeficiente de variación es invariante a escala, así que un divisor constante
no cambia nada de la estabilidad pero sí hace comparables a dos sujetos; un
divisor por frame sólo puede añadir su propio ruido. Comprobado: normalizar por
la mediana del torso de la sesión deja la variación exactamente igual que sin
normalizar.

### Otras dos cosas que aparecieron

- **Asimetría izquierda/derecha del 3 al 10 %.** El mismo brazo mide distinto
  según el lado. Es sesgo sistemático por lado, no ruido.
- **La cámara es el cuello de botella, no MediaPipe.** Intervalo mediano entre
  frames: 66.5 ms, o sea 15 fps, que es lo que da la Tapo C210. La inferencia
  tarda 10 ms. Ver el apartado de aplaudir más arriba: a 15 fps el contacto de
  una palmada dura 1 frame y no se detecta de forma fiable.

### La debilidad que esta app hace visible

La profundidad de `pose_world_landmarks` sale de un prior aprendido, así que
los movimientos **a lo largo del eje óptico** —empujar la mano hacia la
cámara— son justo los que peor estima. En la vista de planta se ve
directamente: el esqueleto se aplana y parpadea en profundidad mientras que en
la vista frontal parece perfecto.

Con `--record` la sesión queda en `results/data/pose3d/<fecha>/` como `.npz`
con `world`, `visibility` y `timestamps`, para analizarla después o compararla
contra la triangulación.

## Marco corporal: la pose vista desde el cuerpo

`[implementado]` en `src/mapeo3d/pose/canonical.py`.

`pose_world_landmarks` viene en un marco **alineado con la cámara**. La misma
pose vista desde dos cámaras separadas un ángulo produce dos juegos de números
distintos, girados justamente ese ángulo. Medido sobre una grabación real,
simulando la segunda cámara del anillo:

| ángulo entre cámaras | sin canonicalizar | canonicalizado |
|---|---|---|
| 10° | 10.8 % | 0.00 % |
| **60°** (adyacentes en un anillo de 6) | **62.0 %** | **0.00 %** |
| 120° | 107.4 % | 0.00 % |

Un 62 % es del orden del movimiento entero: **conmutar de cámara a mitad de un
gesto corrompería cualquier ventana temporal de clasificación**. Sobre datos
reales la invariancia sale exacta hasta el épsilon de máquina (3.3e-16 m).

### Qué hace

Ejes a partir del propio cuerpo: origen en el centro de las caderas, `X` de
cadera derecha a izquierda, `Y` hacia los hombros, `Z` el producto vectorial.
`Y` se ortogonaliza contra `X` porque caderas y columna no son perpendiculares
exactas, y suponerlo metería una inclinación falsa.

Se usa la **lateralidad anatómica** que ya trae MediaPipe (su «left» es la
izquierda del sujeto, no la de la imagen): es lo que hace que el resultado no
dependa de desde dónde se mire. La canonicalización **no** vuelve simétrica la
pose — si lo hiciera, «brazo derecho arriba» y «brazo izquierdo arriba» serían
el mismo gesto.

### Hace falta con una cámara o con seis

No es una pieza de la idea de seleccionar vista: es el paso previo a cualquier
clasificador, y la literatura lo da por hecho (Ibañez et al. centran y
normalizan por escala corporal antes de clasificar). Con una sola cámara ya
sirve, porque vuelve comparables a dos sujetos de estatura distinta.

### La condición del marco es una puerta, no un ranking

El marco se construye con cuatro landmarks. Si el sujeto está de perfil el
ancho de caderas se desploma, la dirección de `X` pasa a ser ruido, y la pose
sale girada un ángulo arbitrario. **Canonicalizar no arregla una vista mala:
puede empeorarla.**

`MarcoCorporal.condicion` es el ancho de caderas relativo al torso; de frente
ronda 0.41-0.43. Medido sobre dos sesiones:

| umbral | frames que pasan | error de los que pasan | de los que NO |
|---|---|---|---|
| 0.10 | 99.8 % | 13.4 % | 33.9 % |
| **0.18** | **97.9 %** | **13.0 %** | **30.4 %** |
| 0.30 | 77.8 % | 10.2 % | 24.7 % |

Lo que cae por debajo del umbral es **catastrófico, no mediocre**: un error del
30 %, tres veces la media. Pero rechaza muy poco, así que sirve de **puerta de
validez y no de criterio de calidad**. Para ordenar vistas, la `visibility` del
modelo predice el error mucho mejor (rho = −0.75 frente a −0.28 de esta
medida). `CONDICION_MINIMA` se fija en 0.18: conserva el 98 % del material y
descarta sólo lo roto.

Cuando el marco no es utilizable, `canonicalizar()` devuelve `None` y
`canonicalizar_secuencia()` deja `NaN`. Es el mismo contrato que
`triangulation.robust`: mejor que el consumidor sepa que no hay dato a que
reciba un número inventado.

### La escala se calcula una vez por sesión

`escala_de_sesion()` para material grabado, `EstimadorDeEscala` para vivo, con
calentamiento y mediana acumulada.

Una escala por frame sólo puede añadir su propio ruido: el coeficiente de
variación es invariante a escala, así que un divisor constante no cambia la
estabilidad pero sí hace comparables a dos sujetos. Ya estaba medido —
normalizar por el ancho de hombros de cada frame empeoraba la variación de
10.4 % a 15.4 %— y las dos sesiones lo confirman entre sí:

| | sesión 1 | sesión 2 | diferencia |
|---|---|---|---|
| largo de torso | 491 mm | 496 mm | **1 %** |
| ancho de hombros | 281 mm | 318 mm | 13 % |

Mismo sujeto, dos sesiones: el torso se repite al 1 % y los hombros varían un
13 %. Es la confirmación entre sesiones de que **el torso es la referencia de
escala y los hombros no**.

### Interfaz

```
marco_corporal(mundo, visibilidad=None)   -> MarcoCorporal | None
    .origen, .rotacion, .ancho_caderas_m, .largo_torso_m
    .condicion, .valido, .aplicar(puntos)

canonicalizar(mundo, visibilidad=None)         -> (K,3) | None
canonicalizar_secuencia(secuencia, vis=None)   -> (T,K,3), NaN si no hay marco
escala_de_sesion(secuencia, vis=None)          -> metros
normalizar(canonico, escala_m)                 -> adimensional
rasgos_de_sesion(secuencia, vis=None)          -> ((T,K,3), escala_m)

EstimadorDeEscala(calentamiento=45)
    .observar(marco) / .listo / .escala_m / .n
```

`rasgos_de_sesion()` es lo que consumiría un clasificador de gestos — que vive
en el repositorio `tesis`, no aquí.

## Eventos: detectar trayectorias, no instantes

`[implementado]` en `src/mapeo3d/pose/eventos.py`.

Medido sobre una grabación real de 60 s a 30 fps con palmadas y gestos rápidos,
decimándola después a 15 fps:

| método | 30 fps | 15 fps | se conserva |
|---|---|---|---|
| mínimos locales (**instante**) | 48 | 28 | 58 % |
| **episodios (trayectoria)** | **10** | **9–10** | **90 %** |

Dos lecturas, y las dos importan:

1. **El método ingenuo sobrecuenta.** 48 detecciones donde hubo 10
   acercamientos: con la señal temblando, un solo evento sostenido produce
   varios mínimos locales.
2. **Y además pierde el 42 % al bajar a 15 fps**, porque el instante del
   contacto dura un frame. El episodio dura 0.2–1.7 s y no se pierde.

La conclusión es que **el frame rate no era el límite: lo era el detector.**
Esto cambia una decisión de proyecto — el vocabulario dinámico no hay que
condicionarlo a conseguir 30 fps.

### Cómo se consigue esa robustez

- **Histéresis.** Se entra en episodio por debajo de `umbral` y se sale por
  encima de `umbral × 1.35`. Con un solo umbral, una señal que roza el límite
  genera decenas de episodios donde hubo uno; es la banda muerta de un
  termostato.
- **Duración mínima en segundos, no en frames.** Es lo que hace que el
  detector se comporte igual a 15 que a 30 fps.
- **Tolerancia a huecos.** La pose se pierde durante décimas de segundo con
  frecuencia; un hueco de menos de 0.25 s no parte el episodio.
- **Umbral por percentil de la propia sesión.** Una distancia de 12 cm
  significa cosas distintas en personas de tamaños distintos.

Robustez frente al ajuste del umbral, sobre la misma grabación:

| percentil | umbral | 30 fps | 15 fps |
|---|---|---|---|
| 8 | 11 cm | 8 | 8 |
| 12 | 12 cm | 10 | 9 |
| 15 | 13 cm | 10 | 10 |
| 20 | 16 cm | 8 | 8 |

El número de eventos varía con el umbral, pero **el acuerdo entre 30 y 15 fps
se mantiene entre el 89 % y el 100 %** en todo el rango. La propiedad no
depende de afinar el umbral.

### Lo que hay aquí y lo que no

Aquí está la **primitiva temporal** —dada una señal escalar, encontrar sus
episodios— y los constructores de señales genéricos: distancia entre dos
landmarks, rapidez de uno.

**La traducción de un episodio a un comando de vuelo no está aquí.** Eso es
clasificación de intención y vive en el repositorio `tesis`. Ver AGENTS.md.

```
detectar_episodios(senal, tiempos, *, umbral, factor_salida,
                   min_duracion_s, hueco_maximo_s) -> list[Episodio]
    Episodio: .inicio .fin .pico .valor_pico .t_inicio .t_pico
              .duracion_s .n_frames

distancia(secuencia, a, b)          -> (T,)
rapidez(secuencia, i, tiempos)      -> (T,)   usa el intervalo REAL, no 1/fps
umbral_por_percentil(senal, p=12)   -> float
```

## Enseñar el sistema: `apps/demo_pose3d.py`

`[implementado]`. Una cámara, un comando, sin calibrar nada:

```powershell
python apps/demo_pose3d.py
```

Tres paneles: cámara con los landmarks 2D encima, **reconstrucción 3D en
perspectiva que gira sola**, y métricas en vivo. Abajo, una franja con las
etapas del pipeline y una línea vertical que marca **dónde termina este
repositorio y empieza `tesis`**.

Controles: `espacio` pausa el giro, las flechas giran a mano, `+`/`-` acercan,
`r` reinicia, `q` sale.

### Por qué perspectiva girando y no las tres vistas ortográficas

`check_pose3d.py` usa frontal, perfil y planta porque son lo mejor para
**medir**: no deforman y se leen como un plano. Pero cada panel por separado
parece 2D, y a quien lo ve por primera vez no le comunica que la reconstrucción
sea volumétrica.

Una vista en perspectiva que gira, con rejilla de suelo, sí: el movimiento
relativo entre las partes es lo que deja ver el volumen. Las dos coexisten
porque sirven para cosas distintas. El dibujado está compartido en
`src/mapeo3d/pose/draw.py`.

Dos detalles que hacen que se lea bien y que son fáciles de omitir:

- **Los huesos se pintan de atrás hacia adelante.** Sin ordenar por
  profundidad, un brazo que pasa por detrás del torso se dibuja encima y la
  pose se lee al revés.
- **La rejilla se apoya en el punto más bajo del cuerpo**, no en una altura
  fija: así el esqueleto se ve de pie sobre el suelo sea cual sea la estatura,
  en vez de flotando.

Izquierda y derecha van en colores distintos a propósito: es lo que permite ver
a simple vista si el modelo intercambió los lados, que es su fallo típico
cuando el sujeto está de espaldas.

### Lo que la demo NO demuestra

Las etapas de **gestos** y **vuelo** aparecen en la franja apagadas y marcadas
como del repositorio `tesis`. La demo enseña `captura → landmarks 2D → pose 3D`,
que es lo que este repositorio implementa.

Y la profundidad que se ve girar es la estimación **monocular**: sale de un
prior aprendido, no de geometría. El panel de calidad muestra la variación del
largo de los huesos en todo momento, que con una sola cámara ronda el 8-9 % con
buen encuadre. Ese número es precisamente el argumento del sistema de varias
cámaras, así que conviene enseñarlo y no esconderlo.

## Pendiente

`[planeado]`

- App de captura y visualización en vivo con N cámaras.
- Selección de vistas por **diversidad angular** cuando haya que reducir por
  costo de CPU — no por confianza ni por orden. Ver
  [triangulation.md](triangulation.md).
- Normalización y ventana temporal para el reconocedor. Eso vive en `tesis`,
  no aquí: este repositorio publica pose 3D, no gestos.
