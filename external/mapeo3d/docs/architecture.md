# Arquitectura y contrato de salida

Estado global: `[planeado]`.

## Propósito

Convertir varios streams de vídeo 2D del operador en **una pose corporal 3D métrica, expresada en el marco de coordenadas del Robotat**, con marca de tiempo y medida de confianza.

Todo lo que ocurre después de eso —reconocer un gesto, decidir un comando, volar— pertenece al repositorio `tesis`.

## Flujo de datos

```
Cámara IP 1 ─┐
Cámara IP 2 ─┤                                                  ┌─→ results/  (registro)
     ...     ├─→ capture ─→ pose ─→ triangulation ─→ io ────────┤
Cámara IP N ─┘   (frames    (landmarks  (puntos 3D   (contrato)  └─→ repo `tesis`
                  + tiempo)  2D + conf.)  en marco
                                          Robotat)
                             ▲
                             │
                       calibration
                   (matrices de proyección)
```

Cada etapa tiene una frontera estricta, definida en [`AGENTS.md`](../AGENTS.md#criterio-para-ubicar-archivos-nuevos):

| Etapa | Entrada | Salida | No sabe nada de |
|---|---|---|---|
| `capture` | URLs RTSP | frames + marca de tiempo de llegada | personas, landmarks |
| `pose` | una imagen | landmarks 2D normalizados + confianza | que existan varias cámaras |
| `calibration` | capturas de calibración | matrices de proyección por cámara | el contenido de las imágenes en operación |
| `triangulation` | landmarks 2D de N vistas + matrices | puntos 3D + residual de reproyección | RTSP, MediaPipe |
| `io` | puntos 3D | registro en disco y publicación | cómo se calcularon |

La consecuencia práctica es que **`triangulation` debe poder probarse sin cámaras**: se le dan proyecciones sintéticas de un punto conocido y se comprueba que lo reconstruye. Esa prueba es obligatoria.

## Marco de coordenadas

Hay un solo marco de coordenadas de salida: **el del Robotat**, el mismo en el que el MoCap reporta la posición del dron.

Esta decisión es la que da valor al sistema. Si el operador y el dron viven en el mismo marco métrico, dejan de ser posibles sólo los comandos de velocidad a ciegas y pasan a ser posibles los comandos referenciados espacialmente: mantener una separación mínima, acudir a la posición del operador, o volar hacia un punto señalado.

Cómo se consigue está en [calibration.md](calibration.md). En resumen: se pasea por el volumen un blanco que el MoCap rastrea con marcadores pasivos y que a la vez es detectable en luz visible por las cámaras IP. El Crazyflie por sí solo no sirve de blanco: sus marcadores son retrorreflectivos, brillan en infrarrojo y no en luz visible, y encender los IR de las cámaras cegaría al OptiTrack justo cuando se lo necesita como verdad de terreno.

## Contrato de salida

`[planeado]`

La unidad de salida es un **`PoseFrame3D`**: una pose corporal completa en un instante.

Campos previstos:

| Campo | Tipo | Notas |
|---|---|---|
| `timestamp` | float | segundos, reloj del PC de captura, monotónico |
| `frame_id` | int | contador incremental |
| `landmarks` | array `(K, 3)` | metros, marco Robotat; `NaN` donde no se pudo triangular |
| `confidence` | array `(K,)` | `[0, 1]` por landmark |
| `residual` | array `(K,)` | error de reproyección en píxeles, por landmark |
| `n_views` | array `(K,)` | cuántas cámaras contribuyeron a cada landmark |
| `source_frames` | dict | marca de tiempo por cámara, para auditar la sincronización |

`residual` y `n_views` no son opcionales: son lo que permite al consumidor decidir si confía en un landmark. Una pose sin medida de calidad no es utilizable para control.

### Cómo lo consume `tesis`

Dos vías previstas, en este orden de preferencia:

1. **MQTT.** El Robotat ya usa MQTT y `tesis` ya tiene cliente. Publicar `PoseFrame3D` serializado en un tópico propio (por ejemplo `vision/pose3d`) mantiene los dos repositorios completamente desacoplados y permite que el consumidor esté en otra máquina.
2. **Archivo, para trabajo offline.** Registro en `results/data/<sesion>/` para afinar umbrales y reproducir sesiones sin volar.

**No se contempla importar este paquete desde `tesis`.** Los dos repositorios se despliegan y evolucionan por separado; el contrato es de datos, no de código.

## Decisiones de diseño y por qué

### Por qué un paquete y no scripts sueltos

El repositorio `tesis` usa scripts de ejecución directa con manipulación de `sys.path`, por razones históricas. Este repositorio arranca limpio, así que usa un paquete en `src/mapeo3d/` con lanzadores en `apps/`. Eso hace que la triangulación sea importable y testeable, que es el requisito que más va a pesar.

### Por qué la triangulación no depende del backend de pose

MediaPipe es la elección inicial por costo y por continuidad con lo que ya existe en `tesis`, pero no es necesariamente la definitiva: RTMPose es más preciso y es lo que usan los pipelines maduros del área. `pose/` expone una interfaz de "imagen → landmarks 2D con confianza" y `triangulation/` consume sólo eso, de modo que cambiar de backend sea un cambio local.

### Por qué el DLT y no algo más sofisticado

La triangulación lineal por DLT resuelto con SVD es **N-vistas por naturaleza**: se apilan dos filas por cámara en la matriz del sistema y se resuelve. Pasar de 2 a 6 cámaras es añadir filas, no cambiar de método. Lo que sí hay que añadir encima es robustez —pesos por confianza y rechazo de vistas discrepantes— y eso está en [triangulation.md](triangulation.md).

### Por qué las marcas de tiempo son de llegada y no de la cámara

Las cámaras disponibles no tienen sincronización por hardware. Los relojes internos de cámaras IP de consumo no son fiables al nivel que importa aquí. La marca de tiempo de llegada al PC de captura, con las cámaras cableadas por Ethernet, tiene jitter de pocos milisegundos, que a 30 fps es sub-frame. Ver [capture.md](capture.md).

## Relación con el repositorio `tesis`

| | `mapeo tridimensional con camaras` | `tesis` |
|---|---|---|
| Observa | al operador | al dron |
| Sensor | cámaras IP (luz visible, RTSP) | OptiTrack (IR, MQTT) |
| Produce | pose 3D del cuerpo | vuelo, telemetría, análisis |
| Depende de `cflib` | no | sí |
| Contiene lógica de seguridad de vuelo | no | sí |

La frontera es deliberada. Este repositorio puede fallar, reiniciarse o quedarse sin cámaras y el supervisor de `tesis` debe seguir siendo capaz de mantener el dron seguro — ese es su trabajo, no el nuestro.
