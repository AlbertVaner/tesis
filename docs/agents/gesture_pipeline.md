# Pipeline de gestos por visión: diseño

Documento de arquitectura para cerrar la pieza que falta del proyecto:

```text
movimiento corporal → clasificación robusta → comando de vuelo → Crazyflie → validación experimental
```

Reconcilia `plan_reconocimiento_gestos_robotat_actualizado.md` con la estructura y las reglas ya establecidas en `AGENTS.md`. No introduce una estructura paralela: reubica lo que el plan propone dentro de las raíces canónicas actuales.

---

## 0. Dos sistemas de cámaras que no deben mezclarse

Es la distinción más importante del proyecto y conviene fijarla antes de cualquier otra cosa, porque atraviesa el código, la tesis y las gráficas.

| | **MoCap / OptiTrack** | **Cámaras IP de visión** |
|---|---|---|
| Qué observa | El **dron** (y marcadores) | El **operador** |
| Qué produce | Posición y orientación métricas | Landmarks corporales 2D/3D relativos |
| Transporte | MQTT, tópicos `mocap/...` | RTSP |
| Estado | En operación | Adquiridas, **pendientes de instalar** |
| Consumidor | `cf.extpos.send_extpos()`, supervisor | `pose/detector.py` → reconocedor |

Nunca se cruzan: el dron no se posiciona con las cámaras de visión, y el operador no se rastrea con marcadores MoCap —salvo en la línea base del joystick-marker, que es precisamente el control que el cuerpo va a sustituir.

Los dos flujos se encuentran en un único punto, el supervisor:

```text
 cámaras IP ──RTSP──► pose ──► reconocedor ──► GestureEvent ─┐
                                                             ├─► SUPERVISOR ──► Crazyflie
 OptiTrack ──MQTT──► pose del dron ──────────────────────────┘
```

El supervisor es el único módulo que conoce ambos. Es también el único que puede decidir si un gesto es ejecutable, porque para eso necesita saber dónde está el dron.

---

## 1. Diagnóstico del estado actual

### 1.1 Lo que ya funciona

| Pieza | Ubicación | Estado |
|---|---|---|
| Captura de webcam desacoplada | `external/gesture_detection/capture/webcam.py` | Lista, con selección automática de índice |
| Inferencia de pose | `external/gesture_detection/pose/detector.py` | Lista, devuelve landmarks sin clasificar |
| Tracking de manos | `external/gesture_detection/hand_tracker.py` | Listo, con lateralidad y confianza |
| Visualización y métricas | `external/gesture_detection/visualization/` | Lista (FPS, visibilidad, ángulos de dedos) |
| Vista previa corporal | `external/gesture_detection/pose_preview.py` | Corre, **no clasifica** |
| Reglas de mano | `external/gesture_detection/hand_gesture_detector.py` | Clasifica 9 comandos, vuela hoy |
| Vuelo por gestos de mano | `controllers/single_drone/camera/control_camara_flowdeck_dron1.py` | Vuela con Flow Deck, con watchdog y parada de emergencia |
| Referencia de control continuo | `controllers/joystick/control_with_marker.py` | Zona muerta, rampa, límites de altura/radio, aterrizaje por pérdida de señal |

La base de captura, visualización, telemetría y seguridad está resuelta. El problema no es de infraestructura.

### 1.2 Los cuatro problemas reales

**P1 — No existe un contrato entre visión y control.**
`control_camara_flowdeck_dron1.py` importa `HandGestureDetector` directamente y traduce gestos a velocidades en línea, dentro de `gesture_velocity()` y de `camera_loop()`. El clasificador y el mapeo a velocidad están soldados al bucle de la cámara.

El acoplamiento es más amplio de lo que parece: **hay cuatro consumidores directos de `HandGestureDetector`**, cada uno con su propio mapeo a comandos.

| Consumidor | Línea |
|---|---|
| `controllers/single_drone/camera/control_camara_flowdeck_dron1.py` | 32 |
| `web/server.py` | 45 |
| `archive/legacy/Integration/control_gestos_basico.py` | 45 |
| `external/gesture_detection/main_hands.py` | 13 |

Pasar de manos a cuerpo hoy significa tocar los cuatro. Con `GestureEvent` significa tocar uno.

**P2 — Hay tres líneas de gestos que no se hablan.**

- `hand_gesture_detector.py` (reglas sobre 21 landmarks de mano) — **en producción**, cuatro consumidores.
- `gesture_detector.py` (reglas sobre pose corporal: `DESPEGUE`, `ATERRIZAJE`, `SUBIR`, `BAJAR`, `IZQUIERDA`, `DERECHA`, `STOP`) — **huérfano**: ningún módulo lo importa.
- `pose_preview.py` + `pose/detector.py` (cuerpo + manos, moderno y bien separado) — **sin clasificación**.

Verificado con `grep -rn "gesture_detector\|GestureDetector\|pose_tracker\|PoseTracker\|logger_csv" --include=*.py .`: `GestureDetector`, `PoseTracker` y `logger_csv.py` no tienen ningún consumidor. `pose_tracker.py` se documenta en el README del subsistema como adaptador de compatibilidad, pero no hay nada que compatibilizar.

Además los vocabularios no coinciden: el de mano usa `DESPEGAR`/`ATERRIZAR`, el corporal usa `DESPEGUE`/`ATERRIZAJE`.

**P2b — El lanzador documentado de cámara apunta a `archive/legacy/`.**
`control_dron_camara.py`, listado en el README como entrada de conveniencia, inserta `archive/legacy/Integration/` en `sys.path` e importa `control_gestos_lowlevel_companero`. La ruta que un usuario nuevo ejecuta primero **no** es `controllers/single_drone/camera/`, que es la raíz canónica según `AGENTS.md`.

**P3 — No hay dataset ni normalización, que es exactamente lo que el plan necesita.**
El plan pide DTW/HMM/LSTM sobre landmarks centrados y normalizados. Hoy no existe ni el módulo de normalización, ni el buffer de ventana temporal, ni el recolector de muestras.

**P4 — La estructura sugerida por el plan contradice `AGENTS.md`.**
El plan (§24) propone un repositorio `gesture-control/` con `src/capture`, `src/pose`, `src/recognition`. `AGENTS.md` ya asigna esa responsabilidad a `external/gesture_detection/`. **`AGENTS.md` gana; el plan aporta el contenido, no las rutas.**

---

## 2. El objetivo final es cuerpo completo; las manos son línea base

Decisión explícita: el control por gestos de mano fue una vía experimental que funcionó bien y validó el ciclo completo percepción → interpretación → vuelo, pero **el sistema final de la tesis es control corporal**. Las manos no se promueven a canal permanente de eventos.

Eso les deja tres papeles, todos valiosos:

1. **Prototipo funcional** que ya vuela y que sirve de red de seguridad mientras el corporal madura.
2. **Punto de comparación experimental** en la validación (§8): manos vs. marker vs. cuerpo.
3. **Modo alternativo** disponible en el código, no en el sistema propuesto.

Consecuencia arquitectónica: `hand_gesture_detector.py` se envuelve en `recognition/legacy_hand_rules.py` para que hable `GestureEvent` como todos los demás, y ahí se queda. El sistema final corre **solo Pose**, lo que además evita duplicar la inferencia por stream cuando haya varias cámaras.

---

## 3. Decisión central: separar el canal continuo del canal de eventos

Los papers de `Referencias/` apuntan en direcciones distintas, y esa tensión hay que resolverla de forma explícita.

- **Obaid et al. (2016)**, elicitación con 25 participantes: los usuarios eligen gestos **dinámicos** (89 %) y deícticos. Pero detectan una colisión importante: *subir* y *despegar* producen el mismo gesto candidato (`Two Hands Move Up`), igual que *bajar* y *aterrizar*. Proponen desambiguar por duración del stroke o por una mano vs. dos manos.
- **Gio, Brisco y Vuletic (2021)**, implementación real sobre Kinect: **posturas estáticas continuas** con ángulos y dos umbrales (zona muerta y saturación), amplitud → velocidad por regresión lineal. Error de velocidad < 2 %, latencia ≈ 1,3 s atribuida al SDK del Tello. Los comandos de evento los sacan del canal de navegación y los ponen en un menú que se abre levantando el brazo izquierdo.
- **Ibañez et al. (2014)**: DTW 99,1 % y HMM 98,9 % sobre 7 gestos dinámicos, con centrado y normalización por escala corporal previos. Su validación cruzada es aleatoria por muestra, no por sujeto.

La lectura conjunta es clara: **la navegación quiere ser continua, y los comandos de estado quieren ser eventos discretos**. Meterlos en el mismo clasificador es lo que produce la colisión que reporta Obaid.

### Diseño adoptado

```text
                       ┌─────────────────────────────────┐
   landmarks  ────────►│  CANAL CONTINUO                 │
   normalizados        │  ángulos torso/brazos           │──► vx, vy, vz
                       │  zona muerta + rampa            │    (intención normalizada)
                       └─────────────────────────────────┘
                                    │
                       ┌─────────────────────────────────┐
   ventana de     ────►│  CANAL DE EVENTOS               │
   N frames            │  DTW sobre secuencia corporal   │──► DESPEGAR, ATERRIZAR,
                       │  + persistencia temporal        │    STOP, FOLLOW_ME
                       └─────────────────────────────────┘
                                    │
                       ┌─────────────────────────────────┐
                       │  GATE DE ENGAGEMENT             │
                       │  sin postura de activación,     │
                       │  todo es NO_GESTURE             │
                       └─────────────────────────────────┘
```

**Por qué el gate de engagement no es opcional.** Ni Obaid ni Gio lo resuelven de frente, y es el mecanismo que impide que un movimiento casual del operador —hablando, señalando, acomodándose el pelo— genere una referencia de vuelo. Cumple la función de `NO_GESTURE` del plan (§10) pero actuando *antes* del clasificador: más barato y más auditable. La postura neutra de reposo es la de Gio: de pie, brazos a los lados.

**Ventaja para la tesis.** El canal continuo reutiliza literalmente `tilt_to_speed()` de `controllers/joystick/control_with_marker.py` (zona muerta 12°, saturación 28°, rampa lineal). Eso convierte el joystick-marker ya validado en la **línea base cuantitativa** del control corporal: mismo dron, mismo controlador de bajo nivel, mismas gráficas, sólo cambia la fuente de la inclinación. Comparación lista para escribir.

---

## 4. El contrato: `contracts.py`

Es la pieza que resuelve P1 y P2, y la primera que debe escribirse.

```python
# external/gesture_detection/contracts.py
from dataclasses import dataclass, field
from enum import Enum


class Gesture(str, Enum):
    """Vocabulario único. Nadie define comandos fuera de aquí."""
    NO_GESTURE = "NO_GESTURE"
    DESPEGAR   = "DESPEGAR"
    ATERRIZAR  = "ATERRIZAR"
    STOP       = "STOP"
    FOLLOW_ME  = "FOLLOW_ME"


@dataclass(frozen=True)
class VelocityIntent:
    """Canal continuo. Unidades normalizadas [-1, 1]; el supervisor escala."""
    vx: float = 0.0
    vy: float = 0.0
    vz: float = 0.0


@dataclass(frozen=True)
class GestureEvent:
    """Salida única del subsistema de visión."""
    gesture: Gesture
    confidence: float
    confirmed: bool                  # pasó persistencia temporal
    engaged: bool                    # el operador está en modo control
    velocity: VelocityIntent
    timestamp: float                 # time.monotonic() de la captura
    source: str = "webcam"           # "webcam" | "ipcam_1" | ...
    scores: dict = field(default_factory=dict)   # probabilidades por clase
    landmark_quality: float = 0.0    # visibilidad media de landmarks clave
```

**Reglas que impone:**

1. El vocabulario vive en `Gesture` y en ningún otro sitio. Las reglas de mano y las corporales conservan sus constantes internas pero se exponen traducidas. Resuelve `DESPEGAR`/`DESPEGUE` sin romper el código en uso.
2. La visión **nunca** produce m/s. Produce intención normalizada. Los límites físicos (`SPEED_XY_M_S`, `MAX_HEIGHT_M`, `MAX_RADIUS_M`) son del supervisor, que es quien conoce el dron y el espacio.
3. `confirmed=False` significa "no ejecutar". Sirve para pintar en pantalla y para el CSV, nunca para mover el dron.
4. Serializable a JSON para MQTT sin una segunda definición del formato.

### Interfaz de los reconocedores

```python
# external/gesture_detection/recognition/base.py
class Recognizer(Protocol):
    def update(self, sample: PoseSample) -> GestureEvent: ...
    def reset(self) -> None: ...
```

`dtw.py`, `hmm.py`, `sequence_nn.py`, `continuous_pose.py`, `legacy_body_rules.py` y `legacy_hand_rules.py` quedan intercambiables. El experimento A del plan se reduce a instanciar una clase distinta sobre el mismo dataset y el mismo bucle de evaluación.

---

## 5. Estructura propuesta

Todo lo nuevo cabe en las raíces que `AGENTS.md` ya define.

```text
external/gesture_detection/
├── contracts.py                 ← NUEVO. La pieza clave (§4)
├── config.py                      existente; se separa por subsistema (§7.1)
│
├── capture/
│   ├── webcam.py                  existente
│   ├── rtsp_camera.py           ← NUEVO. Cámaras IP, con reconexión
│   └── camera_manager.py        ← NUEVO. Multicámara
│
├── pose/
│   ├── detector.py                existente
│   └── normalize.py             ← NUEVO. Centrado + escala + orientación
│
├── features/
│   └── sequence_buffer.py       ← NUEVO. Ventana deslizante de N frames
│
├── dataset/
│   ├── collector.py             ← NUEVO. Grabador con cuenta regresiva
│   ├── storage.py               ← NUEVO. .mp4 + .npy + metadata
│   └── loader.py                ← NUEVO. Splits por sujeto (LOSO)
│
├── recognition/
│   ├── base.py                  ← NUEVO. Interfaz común
│   ├── continuous_pose.py       ← NUEVO. Canal continuo por ángulos
│   ├── dtw.py                   ← NUEVO. Canal de eventos, baseline
│   ├── hmm.py                   ← NUEVO. Segundo baseline
│   ├── sequence_nn.py           ← NUEVO. LSTM/GRU, etapa posterior
│   ├── legacy_body_rules.py     ← NUEVO. Rescata gesture_detector.py
│   └── legacy_hand_rules.py     ← NUEVO. Envuelve hand_gesture_detector.py
│
├── runtime/
│   ├── pipeline.py              ← NUEVO. Compone captura→pose→norm→reconoce
│   ├── engagement.py            ← NUEVO. Gate de activación
│   ├── temporal_filter.py       ← NUEVO. Persistencia y confirmación
│   ├── operator_tracking.py     ← NUEVO. Selección de persona y pérdida (§6.2)
│   └── fusion.py                ← NUEVO. Fusión multicámara
│
├── transport/
│   └── mqtt_publisher.py        ← NUEVO. Publica GestureEvent
│
└── apps/
    ├── pose_preview.py            se mueve aquí desde la raíz del subsistema
    ├── camera_survey.py         ← NUEVO. Mide FPS/latencia/cobertura (§6.1)
    ├── collect_dataset.py       ← NUEVO
    └── live_infer.py            ← NUEVO. Inferencia en vivo sin dron
```

```text
controllers/shared/
├── gesture_supervisor.py        ← NUEVO. GestureEvent → comando validado
└── gesture_mqtt_subscriber.py   ← NUEVO. Recibe GestureEvent por MQTT

controllers/single_drone/camera/
├── control_camara_flowdeck_dron1.py   se refactoriza para usar el supervisor
└── control_corporal_dron1.py    ← NUEVO. Entrypoint del modo corporal
```

**Justificación según `AGENTS.md` §"Criterio para crear y ubicar archivos nuevos":**

- Todo lo de visión va en `external/gesture_detection/` porque funciona sin conocer el Crazyflie (regla 6).
- `gesture_supervisor.py` va en `controllers/shared/` porque tendrá al menos dos consumidores de categorías distintas —`single_drone/camera/` y `two_drones/`— no depende de UI ni de cámara, y es una abstracción estable (regla 5). Si al implementarlo hay un solo consumidor real, empieza en `single_drone/camera/` y se promueve después.
- `apps/` mantiene los entrypoints junto al subsistema, sin scripts nuevos en la raíz.
- Dirección de dependencias respetada: `external/` nunca importa `controllers/`.

---

## 6. Lo que decide la instalación de las cámaras

Las cámaras IP ya están adquiridas y en las instalaciones, pendientes de montar. **La colocación es la única decisión irreversible del proyecto a corto plazo**: una vez fijadas al techo o a la pared, cambiarlas cuesta mucho más que cambiar cualquier línea de código. Por eso merece más análisis del que sugiere su apariencia de tarea logística.

### 6.1 Criterios de colocación, orientados a estimación de pose

MediaPipe Pose se degrada con vistas muy laterales o muy picadas: los landmarks de brazos se solapan con el torso y la `visibility` cae. Criterios concretos:

- **Cobertura angular.** Que para cualquier orientación del operador exista al menos una cámara dentro de ±30–45° de su plano frontal. Con cámaras repartidas alrededor de la zona de operación, seis a ~60° de separación cumplen esto por construcción; cuatro a 90° dejan huecos que hay que compensar con la fusión.
- **Altura y picado.** Suficiente para evitar oclusión por muebles u otras personas, pero con un ángulo de picado moderado: un picado fuerte acorta los brazos en la imagen y arruina los ángulos hombro-codo-muñeca, que son justo la señal del canal continuo.
- **Encuadre.** El plan (Fase 1) pide confirmar funcionamiento "de cintura hacia arriba". Si el vocabulario final incluye inclinación del torso o pasos, hace falta cuerpo completo, lo que cambia la distancia y el campo de visión necesarios. **Definir el vocabulario antes de fijar el encuadre**, o se fija un encuadre que no sirve.
- **Iluminación y fondo.** Evitar contraluz y ventanas en el fondo. Es la causa más común de pérdida de landmarks y no se arregla en software.
- **Zona de operación marcada.** Si el operador tiene una zona definida, la geometría cámara-persona queda acotada y la normalización es mucho más fácil. Es un compromiso contra la naturalidad; conviene decidirlo conscientemente y no por omisión.

`apps/camera_survey.py` existe para convertir esto en medidas y no en opiniones: FPS real, latencia, `visibility` media de hombros/codos/muñecas por posición y orientación del operador, y mapa de puntos ciegos. **Correrlo con las cámaras en posición provisional antes de fijarlas.**

### 6.2 Seguimiento del operador: probablemente más simple de lo que parece

La hoja de ruta menciona sincronizar observaciones, identificar a la misma persona entre cámaras, mantener una referencia corporal coherente y detectar pérdida de seguimiento. Re-identificación de personas entre cámaras es un problema difícil de verdad — pero sólo si hay varias personas.

Si durante la operación **hay un único operador en la zona**, el problema se reduce a "elegir la detección de mayor calidad por cámara", que es trivial. Merece la pena decidir esto explícitamente:

- **Un solo operador en la zona**: `operator_tracking.py` selecciona por área o por `visibility` media y no necesita re-ID. Recomendado para la tesis.
- **Varias personas presentes** (observadores, compañeros de laboratorio): hace falta al menos un criterio de desambiguación —proximidad al centro de la zona marcada, o continuidad temporal— antes de pensar en re-ID.

La sincronización tiene el mismo tratamiento: para **fusión de decisiones** basta con marcas de tiempo y una ventana de tolerancia; sólo la reconstrucción 3D exigiría sincronía estricta, y el plan (§14) ya descarta la reconstrucción 3D en la primera versión.

La pérdida de seguimiento sí es crítica y ya tiene precedente en el código: `control_with_marker.py` mantiene hover al perder el marker y aterriza tras `MARKER_LOSS_LAND_S`. El supervisor debe replicar exactamente esa política cuando se pierde el cuerpo del operador.

### 6.3 El dataset se graba con las cámaras finales

Consecuencia directa de §0: como las cámaras de visión son un sistema nuevo y dedicado, el dataset debe grabarse con ellas. Grabarlo con webcam y migrar después introduce un cambio de dominio —ángulo, distancia, resolución, iluminación— que el plan ya anticipa como pérdida de accuracy (Fase 6) y que obligaría a re-grabar.

La webcam conserva un papel acotado y útil: **depurar código**, no entrenar. Tres a cinco muestras de juguete bastan para verificar que el recolector guarda bien, que la normalización no rompe y que DTW corre. El dataset que se reporta en la tesis se graba una sola vez, con las cámaras instaladas.

---

## 7. Deuda a saldar en el camino

### 7.1 `config.py` mezcla tres subsistemas

Contiene parámetros de mano (`FINGER_EXTENSION_MARGIN`, `THUMB_HORIZONTAL_MARGIN`), de cuerpo (`HAND_UP_MARGIN`, `ARM_EXTENDED_FACTOR`), de cámara y de CSV, más un alias de compatibilidad (`CSV_PATH = BODY_CSV_PATH`). Al añadir DTW, ventanas temporales y N cámaras se vuelve inmanejable.

Propuesta: `config/hands.py`, `config/body.py`, `config/cameras.py`, `config/runtime.py`, dejando `config.py` como re-exportador para no romper los imports actuales.

### 7.2 Tres módulos huérfanos

`gesture_detector.py`, `pose_tracker.py` y `logger_csv.py` no tienen consumidores.

- `gesture_detector.py`: convertirlo en `recognition/legacy_body_rules.py`. Da un punto de comparación gratis y responde a "¿realmente hacía falta ML?", que es lo que el plan quiere justificar (§21, aporte 1).
- `pose_tracker.py`: eliminarlo o dejarlo, pero corregir el README, que lo presenta como adaptador de algo que nadie llama.
- `logger_csv.py`: su sucesor natural es `dataset/storage.py`.

### 7.3 `control_dron_camara.py` apunta a legacy

Repuntarlo a `controllers/single_drone/camera/` al hacer la refactorización del contrato.

### 7.4 Imports relativos al subsistema

`pose_preview.py` usa `from capture.webcam import ...`, lo que obliga a ejecutarlo con el subsistema en `sys.path`. Al mover a `apps/` hay que decidir entre convertir `gesture_detection` en paquete o mantener la inserción explícita. `AGENTS.md` advierte: verificar la ejecución directa antes de convertir carpetas en paquetes.

---

## 8. Orden de implementación: dos vías en paralelo

La instalación de cámaras tiene dependencia externa; el software no debería esperarla. Las dos vías avanzan a la vez y confluyen en el dataset.

### Vía A — software, sin bloqueo (se depura con webcam)

| # | Entregable | Verificación | Vuelo |
|---|---|---|---|
| A1 | `contracts.py` | `compileall`; import desde ambos lados | no |
| A2 | `pose/normalize.py` + `features/sequence_buffer.py` | Dos personas de contextura distinta producen secuencias con distancia pequeña | no |
| A3 | `recognition/base.py` + `legacy_hand_rules.py`; migrar los 4 consumidores y repuntar `control_dron_camara.py` | El controlador de cámara y el panel web se comportan igual, ahora vía `GestureEvent` | sí, regresión |
| A4 | `recognition/continuous_pose.py` + `runtime/engagement.py` | `apps/live_infer.py` muestra vx/vy/vz en pantalla, sin dron | no |
| A5 | `controllers/shared/gesture_supervisor.py` | Pruebas unitarias de rechazo: evento viejo, no confirmado, fuera de límites, cuerpo perdido | no |
| A6 | `dataset/storage.py` + `apps/collect_dataset.py` | Grabar 3–5 muestras de juguete con webcam y revisar el `.npy` | no |

### Vía B — cámaras, con dependencia externa

| # | Entregable | Verificación |
|---|---|---|
| B1 | Definir el vocabulario corporal preliminar | Determina encuadre: medio cuerpo vs. cuerpo completo |
| B2 | `capture/rtsp_camera.py` contra **una** cámara en posición provisional | Stream estable, reconexión ante corte |
| B3 | `apps/camera_survey.py` | FPS, latencia, `visibility` por posición/orientación, puntos ciegos |
| B4 | Colocación definitiva y montaje | Cobertura angular medida, no estimada |
| B5 | `capture/camera_manager.py` + `runtime/operator_tracking.py` | N streams sin caída de FPS; operador seguido de forma continua |

### Confluencia

| # | Entregable | Verificación | Vuelo |
|---|---|---|---|
| C1 | Dataset multi-sujeto con las cámaras instaladas | Balance de clases; metadatos completos | no |
| C2 | `recognition/dtw.py` + `runtime/temporal_filter.py` | Matriz de confusión; evaluación LOSO | no |
| C3 | `runtime/fusion.py` | Accuracy con 1 vs. 2 vs. N cámaras | no |
| C4 | `control_corporal_dron1.py --dry-run` | Simulación completa, luego vuelo autorizado | sí |
| C5 | `hmm.py`, `sequence_nn.py`, comparación | Experimento A del plan | no |
| C6 | `transport/mqtt_publisher.py` + suscriptor | Latencia extremo a extremo | sí |

A1–A3 desbloquean todo lo demás y no tocan hardware. A3 es el que hay que hacer con cuidado: refactoriza código que hoy vuela, y su criterio de éxito es que el comportamiento en vuelo no cambie en absoluto. **B1 debería resolverse pronto**, porque de él depende el encuadre y el encuadre depende del montaje.

---

## 9. Qué medir, y contra qué

La validación experimental compara cuatro cosas, según la hoja de ruta:

| Comparación | Por qué importa | Estado |
|---|---|---|
| Control por marker (joystick físico) | Línea base de captura de movimiento, ya validada | sí: `analyze_marker_session.py` ya emite timeline de comandos, movimiento del joystick, velocidades y trayectoria XY |
| Control por gestos de mano | Prototipo experimental que ya vuela | parcial: falta instrumentación equivalente |
| Control por movimientos corporales | El sistema propuesto | falta |
| Métodos de reconocimiento corporal entre sí | Reglas vs. DTW vs. HMM vs. LSTM/GRU | falta |

Métricas por comparación: precisión, latencia, error de trayectoria, comandos falsos y facilidad de uso.

Dos mediciones que ningún trabajo de `Referencias/` reporta y que por eso son las más valiosas:

- **Falsos positivos por minuto con el operador en reposo.** Se mide pidiendo al sujeto que se comporte con naturalidad durante N minutos sin intención de controlar, y contando cuántos comandos habría emitido el sistema. Sin vuelo, sin dataset grande, y ataca de frente el problema de seguridad. Se mide con y sin gate de engagement para cuantificar qué aporta.
- **Generalización a sujeto no visto (LOSO).** Corrige explícitamente la limitación metodológica de Ibañez et al., que hace validación cruzada aleatoria por muestra y no por sujeto.

Para "facilidad de uso" conviene un instrumento estándar —NASA-TLX o SUS—, porque ni Gio ni Obaid los aplican y hace la comparación defendible. Gio mide tiempos de tarea con 4 sujetos y reporta que los gestos son ~27 % más lentos que el mando para un experto, pero similares para novatos: ese es el resultado a replicar y contrastar, porque la motivación del proyecto es justamente reducir la curva de aprendizaje.

---

## 10. Decisiones tomadas

1. Dos sistemas de cámaras separados: MoCap para el dron, cámaras IP para el operador. No se cruzan.
2. La estructura de `AGENTS.md` prevalece sobre la del plan §24.
3. El sistema final es **corporal**. Las manos quedan como prototipo y línea base experimental, no como canal permanente.
4. Navegación por canal continuo (ángulos + zona muerta), comandos de estado por canal de eventos (DTW). No un único clasificador para todo.
5. Gate de engagement obligatorio antes de cualquier comando.
6. La visión emite intención normalizada; el supervisor aplica límites físicos.
7. `GestureEvent` es la única frontera entre `external/gesture_detection/` y `controllers/`, en proceso y por MQTT.
8. El dataset se graba con las cámaras IP instaladas. La webcam sólo depura código.
9. El joystick-marker se conserva como línea base experimental.

## 11. Preguntas abiertas

- **¿Cuál es el vocabulario corporal?** Bloquea el encuadre de las cámaras (B1). Es lo más urgente.
- **¿Medio cuerpo o cuerpo completo?** Si el vocabulario incluye inclinación de torso o pasos, cambia la distancia y el campo de visión de cada cámara.
- **¿Cuál es el gesto de engagement?** Candidatos: brazo izquierdo vertical (menú de Gio), ambas manos al frente, o mantener una postura 1 s.
- **¿`FOLLOW_ME` es seguimiento espacial continuo o una maniobra predefinida?** Cambia si es evento o estado persistente, y afecta al supervisor.
- **¿Un solo operador en la zona, o varias personas presentes?** Decide si hace falta re-identificación (§6.2).
- **¿Zona de operación marcada o movimiento libre?** Compromiso entre naturalidad y robustez de la normalización.
- **¿Longitud de la ventana temporal?** Los tiempos de stroke de Obaid (1,45–2,9 s) sugieren 2–3 s; hay que medirlo con el dataset propio.
- **¿Los dos Crazyflies entran en el alcance formal?** El supervisor se diseña para no impedirlo, pero el vocabulario cambia si hay que seleccionar dron.

---

## Referencias

- Gio, N., Brisco, R., Vuletic, T. (2021). *Control of a Drone with Body Gestures*. ICED21, Gothenburg. DOI: 10.1017/pds.2021.76
- Obaid, M., Kistler, F., Kasparavičiūtė, G., Yantaç, A. E., Fjeld, M. (2016). *How would you gesture navigate a drone? A user-centered approach to control a drone*. AcademicMindtrek '16, Tampere. DOI: 10.1145/2994310.2994348
- Ibañez, R., Soria, Á., Teyseyre, A., Campo, M. (2014). *Evaluación de técnicas de Machine Learning para el reconocimiento de gestos corporales*. ASAI 2014.
- Hernández Recinos, S. X. (2025). Infraestructura de software para conexión remota con el laboratorio Robotat. UVG. — cámaras IP, RTSP, MQTT.
- Schwendener Morales, C. A. (2025). Evaluación de sensores de posicionamiento para el Crazyflie 2.1. UVG. — Motive, NatNet, MoCap.
