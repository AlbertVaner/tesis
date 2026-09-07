# Reconocimiento de gestos corporales con IA para control de Crazyflie

## 1. Objetivo

Explorar una nueva línea del trabajo de graduación para reemplazar el traje de captura de movimiento del operador por un sistema de reconocimiento de gestos corporales mediante visión por computadora e inteligencia artificial.

La propuesta conserva el sistema OptiTrack/MoCap para el posicionamiento del Crazyflie y utiliza las cámaras RGB Amcrest del Robotat para observar al usuario, reconocer gestos naturales (por ejemplo `FOLLOW_ME` o “síganme”) y convertirlos en comandos de alto nivel.

---

## 2. Arquitectura conceptual

```text
                  ROBOTAT

        ┌───────────────────────────┐
        │  Cámaras Amcrest RGB     │
        │ CAM1 CAM2 ... CAM6       │
        └─────────────┬─────────────┘
                      │
                     RTSP
                      │
                      ▼
             Procesamiento de video
                Python / OpenCV
                      │
                      ▼
              Estimación de pose
           MediaPipe u otro modelo
                      │
                      ▼
            Secuencia de landmarks
                      │
                      ▼
      Reconocedor temporal
       DTW / HMM como baseline
     LSTM / GRU en etapa posterior
                      │
                      ▼
          Clasificación de gesto
                      │
                      ▼
             Fusión multicámara
                      │
                      ▼
          Confirmación temporal
                      │
                      ▼
                    MQTT
                      │
                      ▼
        Supervisor/control Crazyflie
                      │
                 Crazyradio
                      │
                      ▼
                Crazyflie 2.1

OptiTrack → Motive → NatNet/MQTT → posición del Crazyflie
```

La IA no debe controlar motores directamente. Debe producir una intención de alto nivel y el supervisor del Crazyflie decide si puede ejecutarse de acuerdo con las reglas de seguridad existentes.

---

## 3. Infraestructura del Robotat que ya podemos aprovechar

### 3.1 Cámaras Amcrest

El trabajo de Sara Ximena Hernández Recinos documenta cámaras de la familia **Amcrest IP4M-1041** y su integración en el Robotat.

Características relevantes:

- resolución de hasta 4 MP;
- hasta 30 FPS;
- campo de visión aproximado de 90°;
- movimiento PTZ;
- compatibilidad con RTSP;
- compatibilidad con ONVIF;
- API HTTP;
- integración con Python;
- posibilidad de acceder directamente al stream de video.

Esto significa que no es necesario utilizar la aplicación propietaria de Amcrest para procesar las imágenes.

### 3.2 RTSP

El video puede obtenerse directamente desde las cámaras mediante RTSP.

Plantilla genérica:

```text
rtsp://<usuario>:<password>@<ip>:554/cam/realmonitor?channel=1&subtype=1
```

**No guardar credenciales reales en Git.**

El trabajo previo utilizó `subtype=1` para disminuir el ancho de banda y mejorar la fluidez cuando se visualizan varias cámaras. Para reconocimiento de gestos se debe comparar experimentalmente:

- `subtype=0`: mayor resolución;
- `subtype=1`: menor consumo y potencialmente menor latencia.

No se debe asumir que mayor resolución producirá el mejor sistema, porque también aumenta el costo de decodificación e inferencia.

### 3.3 Arquitectura previa de video

La infraestructura previa utilizó aproximadamente:

```text
Amcrest
   ↓ RTSP
Flask
   ↓ MJPEG
Frontend web
```

Para IA conviene un camino más directo:

```text
Amcrest
   ↓ RTSP
OpenCV
   ↓
Pose / Gesture AI
```

MJPEG puede seguir utilizándose para visualización web, pero no es necesario usarlo como fuente de la IA.

### 3.4 MQTT

Robotat ya utiliza Mosquitto/MQTT para distribuir información.

Separación recomendada:

```text
RTSP  → video
MQTT  → resultados, estados, eventos y comandos
```

No transmitir frames de video por MQTT.

Posibles topics futuros:

```text
vision/gesture/raw
vision/gesture/confirmed
vision/cameras/status
vision/cameras/primary
vision/model/status
```

Ejemplo conceptual de payload:

```json
{
  "source": "gesture_recognition",
  "gesture": "FOLLOW_ME",
  "confidence": 0.96,
  "primary_camera": 3,
  "confirmed": true,
  "timestamp": 0.0
}
```

El formato definitivo debe alinearse con el esquema de mensajes ya existente en Robotat.

---

## 4. Qué queremos reconocer

No se desea definir cada gesto mediante reglas manuales como:

```python
if wrist_y < shoulder_y:
    gesture = "UP"
```

ni mediante umbrales fijos de ángulos corporales.

La idea es que un modelo aprenda los patrones espaciales y temporales asociados a cada gesto.

Ejemplo:

```text
Video
  ↓
Pose estimation
  ↓
Secuencia del movimiento corporal
  ↓
Modelo entrenado
  ↓
FOLLOW_ME  0.94
STOP       0.03
NO_GESTURE 0.03
```

---

## 5. Gestos estáticos y dinámicos

### Gestos estáticos

Ejemplo: `STOP`.

Una sola postura puede contener suficiente información, aunque se utilizará una ventana temporal o persistencia para aumentar robustez y reducir falsos positivos.

### Gestos dinámicos

Ejemplo: `FOLLOW_ME`.

Su significado depende de cómo se mueve la mano a través del tiempo. Por tanto, un frame aislado puede ser ambiguo.

El sistema debe procesar una secuencia:

```text
frame t-29
frame t-28
...
frame t
```

A partir del paper de Ibañez et al. sobre reconocimiento de gestos corporales, se incorporan como primeros métodos temporales de referencia:

- **Dynamic Time Warping (DTW)**;
- **Hidden Markov Models (HMM)**.

El paper evaluó DTW, Procrustes Analysis, Markov Chain y HMM sobre 7 gestos dinámicos. DTW y HMM alcanzaron las mejores precisiones reportadas: aproximadamente **99.1 %** y **98.9 %**, respectivamente, bajo su esquema de validación.

DTW resulta especialmente interesante para `FOLLOW_ME` porque permite comparar secuencias ejecutadas a diferentes velocidades mediante alineación temporal.

Después de establecer estos baselines, se evaluarán modelos más modernos:

- LSTM;
- GRU;
- Temporal Convolutional Network (TCN);
- Transformers temporales en una etapa posterior.

---

## 6. Enfoque recomendado: comenzar simple y luego aumentar complejidad

El paper revisado cambia el orden recomendado de experimentación.

En lugar de comenzar directamente con una red recurrente, se propone construir primero un baseline sencillo e interpretable.

### Baseline 1 — MediaPipe + DTW

```text
Webcam / Amcrest
       ↓
     OpenCV
       ↓
 MediaPipe Pose
       ↓
 Landmarks corporales
       ↓
 Centrado + normalización
       ↓
 Secuencia temporal
       ↓
       DTW
       ↓
 Clasificación de gesto
```

Ventajas:

- necesita pocos datos;
- no requiere entrenamiento pesado;
- tolera diferencias de velocidad entre ejecuciones;
- es fácil de depurar;
- puede ejecutarse en CPU;
- ofrece un baseline académico claro.

### Baseline 2 — MediaPipe + HMM

```text
Pose
 ↓
landmarks normalizados
 ↓
transformación/secuencia
 ↓
HMM
 ↓
gesto
```

HMM también mostró un desempeño alto en el paper revisado y permite modelar transiciones temporales de forma probabilística.

### Modelo posterior — LSTM / GRU

Una vez medidos los baselines:

```text
Webcam / Amcrest
       ↓
     OpenCV
       ↓
 MediaPipe Pose
       ↓
 Landmarks corporales
       ↓
 Normalización
       ↓
 Ventana temporal
       ↓
    LSTM / GRU
       ↓
 Clasificación
```

La comparación entre métodos permitirá responder si una red neuronal más compleja aporta una mejora suficiente frente a DTW/HMM en:

- precisión;
- generalización;
- latencia;
- cantidad de datos requerida;
- complejidad computacional.

Frente a entrenar directamente sobre imágenes RGB, mantener landmarks como representación principal sigue teniendo ventajas:

- requiere menos datos;
- requiere menos cómputo;
- reduce dependencia del fondo;
- reduce dependencia de la ropa;
- facilita la generalización entre usuarios;
- facilita procesamiento multicámara;
- simplifica entrenamiento y depuración;
- permite datasets de landmarks relativamente pequeños.

Aun así, se recomienda guardar también el video original para poder probar otros extractores o modelos en el futuro sin volver a grabar el dataset.

---

## 7. Normalización para diferentes complexiones

El modelo no debe depender de la altura, ancho de hombros o longitud de brazos del usuario.

El paper de Ibañez et al. aplica dos transformaciones antes del reconocimiento:

1. **centrado**;
2. **normalización de escala**.

En su implementación con Kinect, el centrado consiste en trasladar la secuencia al origen usando el centroide de la trayectoria 3D del torso. Después, las posiciones se escalan utilizando una distancia corporal relativa a cada persona, específicamente la distancia entre cuello y torso.

Pipeline conceptual para nuestro sistema:

```text
landmarks originales
        ↓
centrar respecto al torso/cadera
        ↓
normalizar escala corporal
        ↓
landmarks normalizados
```

Por ejemplo:

```text
p_rel = p - centro_del_cuerpo
p_norm = p_rel / escala_del_cuerpo
```

MediaPipe no entrega exactamente el mismo `stick model` que Kinect, por lo que debemos adaptar la escala corporal. Candidatos:

- distancia entre hombros;
- longitud aproximada del torso;
- distancia entre centro de hombros y centro de caderas;
- combinación robusta de varias distancias.

La mejor opción debe determinarse experimentalmente.

Objetivo: que dos personas de contexturas diferentes produzcan representaciones similares al ejecutar el mismo gesto.

---

## 8. Generalización entre personas

Entrenar solo con una persona puede provocar sobreajuste.

El modelo podría aprender:

```text
“cómo hace una persona específica FOLLOW_ME”
```

cuando queremos aprender:

```text
“qué patrón representa FOLLOW_ME”
```

El paper revisado utilizó **4 personas con diferentes contexturas físicas y diferentes posiciones frente al Kinect**, lo cual respalda la necesidad de variabilidad entre usuarios.

Sin embargo, su evaluación utilizó **cross-validation aleatoria de 10 iteraciones** sobre las muestras. Esto evalúa muestras no vistas, pero no garantiza que la persona de prueba sea completamente desconocida para el modelo.

Para nuestra tesis se propone una evaluación más estricta por sujeto:

```text
Sujetos 1–4 → entrenamiento
Sujeto 5    → prueba
```

El sujeto de prueba no debe aparecer durante el entrenamiento.

Posteriormente se puede utilizar:

- hold-out por sujeto;
- Leave-One-Subject-Out (LOSO);
- validación cruzada por sujetos.

Esta métrica puede convertirse en un resultado importante de la tesis porque responde directamente a la pregunta:

> ¿Puede una persona con diferente complexión utilizar el sistema aunque nunca haya participado en el entrenamiento?

---

## 9. Dataset inicial

Primera versión con solo tres clases:

```text
FOLLOW_ME
STOP
NO_GESTURE
```

El paper revisado utilizó:

- 7 gestos;
- 4 personas;
- 20 repeticiones por persona y gesto;
- 80 muestras totales por gesto.

También evaluó datasets de 20, 40, 60 y 80 muestras por gesto. Reportó que aumentar la cantidad de ejemplos mejora la precisión, pero la mejora se desacelera a partir de aproximadamente **40 muestras por gesto** en varias de las técnicas evaluadas.

Esto sugiere que para validar rápidamente el enfoque no es necesario comenzar con miles de ejemplos.

### Recolección inicial propuesta

Por persona:

```text
FOLLOW_ME    30
STOP         30
NO_GESTURE   60
```

Total:

```text
120 secuencias / persona
```

Con cinco personas:

```text
600 secuencias
```

Estas cantidades son para una primera evaluación con separación por sujeto.

Para un experimento rápido de DTW se puede comenzar incluso con:

```text
20–40 muestras por gesto
```

y posteriormente ampliar el dataset.

---

## 10. Importancia de NO_GESTURE

`NO_GESTURE` es fundamental porque los falsos positivos pueden provocar movimientos no deseados del dron.

Debe contener ejemplos como:

- persona quieta;
- hablando;
- moviendo casualmente una mano;
- cruzando brazos;
- acomodando el cabello;
- mirando el teléfono;
- señalando algo;
- caminando ligeramente;
- movimientos no definidos como comandos.

No basta con maximizar accuracy; será especialmente importante minimizar falsos positivos.

---

## 11. Cómo guardar el dataset

Guardar por muestra:

1. video original;
2. landmarks procesados;
3. metadata.

Estructura propuesta:

```text
dataset/
├── subject_001/
│   ├── follow_me/
│   │   ├── sample_001.mp4
│   │   ├── sample_001.npy
│   │   ├── sample_002.mp4
│   │   └── sample_002.npy
│   ├── stop/
│   └── no_gesture/
├── subject_002/
└── ...
```

Metadata de ejemplo:

```json
{
  "subject": "subject_001",
  "gesture": "FOLLOW_ME",
  "camera": "laptop",
  "fps": 30,
  "frames": 30,
  "timestamp": "...",
  "notes": ""
}
```

Evitar nombres reales de participantes cuando no sean necesarios.

---

## 12. Data augmentation

Posibles transformaciones sobre landmarks:

- ruido pequeño;
- escalado pequeño;
- rotaciones pequeñas;
- variaciones temporales;
- pérdida ocasional de frames;
- variaciones de velocidad;
- mirror izquierda/derecha cuando el significado del gesto lo permita.

No toda transformación es válida para todas las clases. Debe verificarse que el augmentation no cambie el significado del gesto.

---

## 13. Persistencia temporal

Una sola predicción no debe activar un comando.

Ejemplo:

```text
Predicción 1 → FOLLOW_ME 0.93
Predicción 2 → FOLLOW_ME 0.95
Predicción 3 → FOLLOW_ME 0.96
Predicción 4 → FOLLOW_ME 0.94
Predicción 5 → FOLLOW_ME 0.97
                  ↓
           GESTO CONFIRMADO
```

Si las predicciones son inconsistentes:

```text
FOLLOW_ME
NO_GESTURE
NO_GESTURE
FOLLOW_ME
NO_GESTURE
```

no se ejecuta nada.

El protocolo de Luis Furlán incluye antecedentes de sistemas de visión que usan persistencia y confirmación temporal para reducir falsas alarmas. Ese principio es directamente aplicable al control seguro de drones.

---

## 14. Fusión multicámara

El sistema final utilizará hasta seis cámaras.

Cada una puede producir una predicción independiente:

```text
CAM1 → P(FOLLOW_ME)
CAM2 → P(FOLLOW_ME)
...
CAM6 → P(FOLLOW_ME)
```

Para la primera versión multicámara se propone **fusión de decisiones**, no reconstrucción 3D completa.

---

## 15. Cámara principal basada en rostro

Hipótesis inicial: la cámara que observa el rostro con mayor calidad debe recibir mayor peso, porque probablemente tiene una vista favorable del torso y los brazos.

Sin embargo, el rostro no debe ser el único criterio: una cámara puede ver perfectamente la cara y tener una mano ocluida.

Score conceptual:

```text
Score_i =
    α * face_confidence
  + β * face_frontality
  + γ * pose_visibility
  + δ * body_image_quality
```

Los pesos `α, β, γ, δ` todavía no están definidos y deberán ajustarse experimentalmente.

---

## 16. Peso por articulación

Versión avanzada:

```text
CAM3
rostro        excelente
hombro        excelente
codo          bueno
mano derecha  ocluida

CAM4
rostro        lateral
hombro        bueno
codo          excelente
mano derecha  excelente
```

Posible estrategia:

```text
torso        → mayor peso CAM3
mano derecha → mayor peso CAM4
```

Esto puede aumentar robustez ante oclusiones.

---

## 17. Fusión de probabilidades

Enfoque inicial:

```text
P_final(G) = Σ(w_i * P_i(G)) / Σ(w_i)
```

Donde:

- `P_i(G)` es la probabilidad del gesto G estimada por la cámara i;
- `w_i` es el peso/confianza asignado a esa cámara.

Después:

```text
if P_final(G) > threshold:
    candidato = G
else:
    candidato = NO_GESTURE
```

Posteriormente se aplica persistencia temporal.

---

## 18. Seguridad

Las primeras pruebas no deben controlar directamente un Crazyflie.

Orden recomendado:

```text
1. gesto → texto en pantalla
2. gesto → log
3. gesto → MQTT sin dron
4. gesto → simulación
5. gesto → pruebas físicas sin vuelo
6. gesto → vuelo controlado
```

Regla principal ante incertidumbre:

```text
NO enviar nueva referencia de movimiento
```

Nunca:

```text
“no estoy seguro del gesto” → ejecutar movimiento
```

---

## 19. Relación con el controlador Crazyflie existente

```text
Gesture Recognition
       ↓
"FOLLOW_ME"
       ↓
Supervisor / State Machine
       ↓
validaciones de seguridad
       ↓
generación de referencia
       ↓
Crazyflie
```

La IA genera una intención de alto nivel. El supervisor conserva la responsabilidad de validar límites de área, estado del dron, disponibilidad de posicionamiento y condiciones de emergencia.

---

## 20. Lo aportado por el protocolo de Luis Furlán

El protocolo de 2026 sobre detección de objetos peligrosos y comportamiento sospechoso aporta antecedentes muy cercanos al problema:

- aprendizaje automático sobre video;
- análisis de comportamiento;
- integración de información espacial y temporal;
- CNN + LSTM;
- estimación de pose;
- representaciones esqueléticas;
- datasets;
- data augmentation;
- balance de clases;
- persistencia temporal;
- métricas de clasificación;
- evaluación de latencia;
- pruebas en tiempo real.

Esto refuerza la viabilidad del enfoque **pose estimation + modelo temporal**.

---

## 21. Aporte del paper “Evaluación de técnicas de Machine Learning para el reconocimiento de gestos corporales”

Rodrigo Ibañez, Álvaro Soria, Alfredo Teyseyre y Marcelo Campo evaluaron cuatro técnicas de Machine Learning para reconocimiento de gestos corporales utilizando esqueletos 3D obtenidos con Microsoft Kinect.

### Dataset utilizado

- 7 gestos:
  - Círculo;
  - Estiramiento;
  - Nadar;
  - Smash;
  - Punch;
  - Swipe izquierda;
  - Swipe derecha.
- 4 participantes con diferentes contexturas físicas.
- 20 repeticiones por gesto y persona.
- 80 muestras por gesto.

### Técnicas evaluadas

| Técnica | Precisión reportada |
|---|---:|
| Dynamic Time Warping (DTW) | 99.1 % |
| Hidden Markov Models (HMM) | 98.9 % |
| Markov Chain | 96.96 % |
| Procrustes Analysis | 81.25 % |

### Aportes aplicables al proyecto

1. **Evitar reglas manuales para gestos complejos.**  
   Los autores destacan que los enfoques basados en reglas tienen poca flexibilidad frente a diferencias de ejecución y contextura física.

2. **Trabajar con una representación esquelética.**  
   Kinect genera una secuencia temporal de `stick models`; en nuestro caso MediaPipe cumplirá un rol equivalente al producir landmarks.

3. **Centrar y normalizar antes de clasificar.**  
   Esto reduce el efecto de la posición del usuario y de sus dimensiones corporales.

4. **Comparar trayectorias temporales.**  
   DTW puede alinear secuencias que representan el mismo gesto aunque se ejecuten a distintas velocidades.

5. **No usar necesariamente todo el cuerpo.**  
   Dependiendo del gesto se pueden utilizar solo las articulaciones relevantes. Por ejemplo, `FOLLOW_ME` podría depender principalmente de hombro, codo, muñeca y mano.

6. **La cantidad de datos presenta rendimientos decrecientes.**  
   En el paper, el aumento de muestras mejora la precisión, pero la ganancia adicional disminuye al superar aproximadamente 40 ejemplos por gesto para varias técnicas.

### Limitación metodológica importante

El paper divide las muestras aleatoriamente en 10 grupos para cross-validation. Eso significa que entrenamiento y prueba pueden contener muestras de las mismas personas.

Nuestra evaluación será más estricta:

```text
entrenamiento → sujetos conocidos
prueba         → sujeto completamente desconocido
```

Esto permitirá medir generalización real entre usuarios.

---

## 22. Primer prototipo con webcam

Antes de usar Robotat se desarrollará un prototipo con la webcam de la laptop.

```text
Laptop webcam
      ↓
    OpenCV
      ↓
 MediaPipe Pose
      ↓
landmarks normalizados
      ↓
modelo temporal
      ↓
FOLLOW_ME / STOP / NO_GESTURE
```

Esto permite validar el pipeline sin depender todavía de:

- Robotat;
- Amcrest;
- red interna;
- Crazyflie;
- Crazyradio;
- Motive.

---

## 23. Plan de desarrollo

### Fase 0 — entorno

- [ ] Crear repositorio/proyecto.
- [ ] Crear entorno virtual Python.
- [ ] Instalar OpenCV.
- [ ] Instalar MediaPipe.
- [ ] Instalar NumPy.
- [ ] Instalar pandas.
- [ ] Instalar scikit-learn.
- [ ] Elegir TensorFlow/Keras o PyTorch.
- [ ] Crear `.gitignore`.
- [ ] Crear `.env.example`.
- [ ] No subir credenciales RTSP al repositorio.

### Fase 1 — webcam + pose

- [ ] Detectar webcam.
- [ ] Mostrar video.
- [ ] Ejecutar pose estimation.
- [ ] Dibujar landmarks.
- [ ] Mostrar FPS.
- [ ] Medir latencia aproximada.
- [ ] Registrar visibility/confidence de hombros, codos y muñecas.
- [ ] Confirmar funcionamiento desde cintura hacia arriba.

### Fase 2 — recolector de datos

- [ ] Definir `FOLLOW_ME`.
- [ ] Definir `STOP`.
- [ ] Definir `NO_GESTURE`.
- [ ] Crear selector de sujeto.
- [ ] Crear selector de gesto.
- [ ] Cuenta regresiva 3-2-1.
- [ ] Capturar ventana temporal.
- [ ] Guardar `.mp4`.
- [ ] Guardar `.npy`.
- [ ] Guardar metadata.
- [ ] Mostrar cantidad de muestras recolectadas.

### Fase 3 — preprocesamiento

- [ ] Centrar landmarks.
- [ ] Normalizar escala.
- [ ] Tratar landmarks faltantes.
- [ ] Crear secuencias de longitud fija.
- [ ] Separar train/validation/test por sujeto.
- [ ] Verificar balance de clases.

### Fase 4 — baselines y modelos

- [ ] Implementar DTW sobre secuencias normalizadas.
- [ ] Seleccionar trayectoria/referencia por gesto.
- [ ] Definir umbral de aceptación para DTW.
- [ ] Evaluar DTW.
- [ ] Implementar HMM.
- [ ] Evaluar HMM.
- [ ] Implementar LSTM.
- [ ] Implementar GRU.
- [ ] Comparar DTW vs HMM vs LSTM vs GRU.
- [ ] Medir tiempo de entrenamiento.
- [ ] Medir tiempo de inferencia.
- [ ] Guardar modelos/referencias y configuración.
- [ ] Generar matrices de confusión.
- [ ] Calcular Accuracy.
- [ ] Calcular Precision.
- [ ] Calcular Recall.
- [ ] Calcular F1-score.
- [ ] Calcular False Positive Rate.

### Fase 5 — inferencia en vivo

- [ ] Webcam en tiempo real.
- [ ] Buffer de N frames.
- [ ] Normalización.
- [ ] Inferencia.
- [ ] Mostrar probabilidades.
- [ ] Mostrar gesto detectado.
- [ ] Implementar `confidence_threshold`.
- [ ] Implementar persistencia temporal.
- [ ] Registrar eventos.

### Fase 6 — primera Amcrest

- [ ] Confirmar IP de cámara.
- [ ] Confirmar RTSP.
- [ ] Abrir RTSP con OpenCV.
- [ ] Medir FPS.
- [ ] Medir latencia.
- [ ] Comparar `subtype=0` y `subtype=1`.
- [ ] Ejecutar pose estimation.
- [ ] Ejecutar modelo entrenado inicialmente con webcam.
- [ ] Evaluar pérdida de accuracy por cambio de cámara.

### Fase 7 — multicámara

- [ ] Conectar 2 cámaras.
- [ ] Ejecutar procesamiento paralelo.
- [ ] Crear `CameraManager`.
- [ ] Obtener score de cada cámara.
- [ ] Detectar cámara frontal.
- [ ] Seleccionar cámara principal.
- [ ] Fusionar probabilidades.
- [ ] Evaluar oclusiones.
- [ ] Escalar 2 → 4 → 6 cámaras.

### Fase 8 — Robotat/MQTT

- [ ] Definir topics.
- [ ] Adaptar payload al estándar Robotat.
- [ ] Publicar gesto raw.
- [ ] Publicar gesto confirmado.
- [ ] Registrar timestamp.
- [ ] Crear subscriber de prueba.
- [ ] Medir latencia end-to-end.

### Fase 9 — integración Crazyflie

- [ ] Máquina de estados.
- [ ] Validaciones de seguridad.
- [ ] Mapear gesto → acción de alto nivel.
- [ ] Prueba sin vuelo.
- [ ] Prueba en simulación.
- [ ] Prueba física controlada.
- [ ] Medir comandos incorrectos.
- [ ] Evaluar respuesta completa.

---

## 24. Estructura inicial sugerida del repositorio

```text
gesture-control/
├── README.md
├── requirements.txt
├── .gitignore
├── .env.example
│
├── config/
│   ├── gestures.yaml
│   └── cameras.example.yaml
│
├── data/
│   └── .gitkeep
│
├── models/
│   └── .gitkeep
│
├── src/
│   ├── capture/
│   │   ├── webcam.py
│   │   ├── rtsp_camera.py
│   │   └── camera_manager.py
│   ├── pose/
│   │   ├── detector.py
│   │   └── normalize.py
│   ├── dataset/
│   │   ├── collector.py
│   │   ├── preprocess.py
│   │   └── loader.py
│   ├── recognition/
│   │   ├── dtw.py
│   │   ├── hmm.py
│   │   ├── lstm.py
│   │   ├── gru.py
│   │   └── evaluate.py
│   ├── inference/
│   │   ├── realtime.py
│   │   ├── temporal_filter.py
│   │   └── fusion.py
│   ├── mqtt/
│   │   ├── publisher.py
│   │   └── subscriber.py
│   └── app.py
│
├── tests/
│
└── docs/
    ├── architecture.md
    ├── dataset_protocol.md
    └── experiments.md
```

No es necesario crear toda la estructura de una vez. Puede crecer progresivamente.

---

## 25. Dependencias iniciales tentativas

```text
opencv-python
mediapipe
numpy
pandas
scikit-learn
matplotlib
paho-mqtt
python-dotenv
```

Para los primeros baselines pueden evaluarse:

```text
dtaidistance
hmmlearn
```

También es válido implementar DTW manualmente para mantener el baseline transparente y reducir dependencias.

Para redes neuronales elegir inicialmente **uno**:

```text
tensorflow
```

o:

```text
torch
```

No instalar ambos frameworks sin necesidad en el primer prototipo.

---

## 26. Métricas importantes

Clasificación:

```text
Accuracy
Precision
Recall
F1-score
Confusion Matrix
False Positive Rate
```

Sistema en tiempo real:

```text
FPS
latencia de captura
latencia de pose
latencia de inferencia
latencia de fusión
latencia MQTT
latencia total gesto → evento
```

Multicámara:

```text
accuracy con 1 cámara
accuracy con 2 cámaras
accuracy con 4 cámaras
accuracy con 6 cámaras
```

Generalización:

```text
accuracy usuario conocido
accuracy usuario no visto
```

---

## 27. Experimentos potenciales de tesis

### Experimento A

¿Puede un método temporal reconocer gestos corporales dinámicos utilizando landmarks?

Comparar:

```text
DTW
vs
HMM
vs
LSTM
vs
GRU
```

Evaluar no solo precisión, sino también:

```text
latencia
tiempo de entrenamiento
cantidad de muestras requerida
complejidad computacional
```

### Experimento B

¿Qué tan bien generaliza el modelo a personas no utilizadas en entrenamiento?

```text
train subjects ≠ test subject
```

### Experimento C

¿Mejora el desempeño al usar múltiples cámaras?

```text
1 vs 2 vs 4 vs 6 cámaras
```

### Experimento D

¿La selección ponderada de cámaras reduce fallos por oclusión?

```text
una cámara fija
vs
cámara con mejor rostro
vs
fusión rostro + visibilidad
```

### Experimento E

¿Cuál es la latencia completa?

```text
gesto físico
→ captura
→ pose
→ IA
→ confirmación
→ MQTT
→ controlador
```

---

## 28. Hipótesis de arquitectura final

```text
6 Amcrest
   ↓
RTSP
   ↓
procesamiento paralelo
   ↓
Pose Estimation
   ↓
landmarks normalizados
   ↓
reconocedor temporal por cámara
DTW / HMM / LSTM / GRU
   ↓
scores / probabilidades
   ↓
fusión ponderada
   ↓
persistencia temporal
   ↓
gesture event
   ↓
MQTT
   ↓
supervisor Crazyflie
```

Mientras:

```text
OptiTrack
   ↓
Motive
   ↓
NatNet/MQTT
   ↓
posición del Crazyflie
```

---

## 29. Decisiones actuales

1. El Crazyflie seguirá usando MoCap para posicionamiento.
2. Las cámaras Amcrest observarán al operador.
3. Los gestos serán aprendidos por IA, no definidos principalmente por reglas manuales.
4. Los gestos dinámicos necesitan información temporal.
5. El primer baseline será pose estimation + DTW; después se evaluarán HMM, LSTM y GRU.
6. Se empezará con la webcam de la laptop.
7. Primeras clases: `FOLLOW_ME`, `STOP`, `NO_GESTURE`.
8. El dataset guardará video + landmarks.
9. La división del dataset debe realizarse por sujeto.
10. Se probará generalización con personas nunca vistas por el modelo.
11. En multicámara, la cámara que mejor vea el rostro tendrá mayor importancia, pero no será el único criterio.
12. La visibilidad de landmarks también influirá en el peso.
13. Inicialmente se hará fusión de decisiones, no reconstrucción 3D.
14. RTSP transportará video.
15. MQTT transportará eventos/resultados.
16. Las predicciones deben confirmarse temporalmente.
17. La IA producirá intenciones de alto nivel, no comandos directos de motores.
18. Ante baja confianza no se generará movimiento.

---

## 30. Preguntas abiertas

- ¿MediaPipe Pose será suficientemente robusto con las Amcrest?
- ¿Será necesario MediaPipe Holistic para gestos con dedos/manos?
- ¿Qué resolución ofrece el mejor balance latencia/accuracy?
- ¿Cuántos FPS reales se obtendrán procesando seis streams?
- ¿Qué hardware ejecutará finalmente el modelo?
- ¿TensorFlow o PyTorch?
- ¿DTW, HMM, LSTM o GRU ofrece el mejor balance entre precisión, generalización y latencia?
- ¿Vale la pena una TCN después de establecer los baselines?
- ¿Cuál será la longitud óptima de la ventana temporal?
- ¿Cómo manejar landmarks ausentes?
- ¿Cómo definir el score de cámara?
- ¿Cómo estimar frontalidad del rostro?
- ¿Qué threshold minimiza falsos positivos sin perder demasiados gestos reales?
- ¿Cuántas confirmaciones temporales se necesitan?
- ¿Cuántas personas deben formar el dataset final?
- ¿Qué gestos finales se utilizarán?
- ¿Cómo mapear `FOLLOW_ME` cuando existan múltiples drones?
- ¿`FOLLOW_ME` significará seguir espacialmente al usuario o ejecutar una maniobra predefinida?
- ¿Será necesaria sincronización estricta entre cámaras para fusión de decisiones?
- ¿Se añadirá reconstrucción 3D en una etapa posterior?

---

## 31. Primer objetivo para Codex

No entrenar todavía el modelo completo.

Primero construir:

```text
Webcam
  ↓
OpenCV
  ↓
MediaPipe
  ↓
visualización de pose
  ↓
FPS + confidence
```

Luego construir el recolector de dataset.

### Prompt sugerido para Codex

```text
Estamos desarrollando un sistema de reconocimiento de gestos corporales
para controlar drones Crazyflie. El primer prototipo usará la webcam de
una laptop.

Quiero crear una aplicación en Python que:

1. Detecte automáticamente la webcam.
2. Capture video con OpenCV.
3. Ejecute MediaPipe Pose en tiempo real.
4. Dibuje el esqueleto sobre la imagen.
5. Muestre FPS.
6. Muestre la visibilidad/confianza de los landmarks principales:
   hombros, codos y muñecas.
7. Permita salir con la tecla Q.
8. Separe claramente captura, detección de pose y visualización en
   funciones o clases para reutilizarlo después con cámaras RTSP.
9. No implemente todavía clasificación de gestos.
10. Entregue el código completo y un requirements.txt.

Usar Python 3.11 cuando las dependencias seleccionadas sean compatibles.
```

Después del primer programa, el siguiente objetivo será crear un recolector de datos que guarde video, landmarks y metadata por sujeto y gesto.

Luego se implementará el primer reconocedor funcional:

```text
MediaPipe → centrado/normalización → DTW → gesto
```

antes de introducir LSTM/GRU.

---

## 32. Fuentes principales

### Infraestructura Robotat y cámaras Amcrest

Sara Ximena Hernández Recinos. **Diseño e implementación de infraestructura de software para la conexión remota sincrónica con el laboratorio Robotat de la Universidad del Valle de Guatemala.** Trabajo de graduación, UVG, 2025.

Secciones relevantes:

- cámaras Amcrest;
- RTSP;
- API HTTP;
- control PTZ;
- acceso a video en tiempo real;
- Flask/MJPEG;
- MQTT/Mosquitto;
- arquitectura de red Robotat.

### Visión por computadora y reconocimiento temporal

Luis David Furlán Monterroso. **Diseño e implementación de un sistema de detección de objetos peligrosos y comportamiento sospechoso usando visión por computadora.** Protocolo de trabajo de graduación, UVG, 2026.

Aspectos relevantes:

- comportamiento en video;
- CNN-LSTM;
- pose estimation;
- representaciones esqueléticas;
- datasets;
- data augmentation;
- persistencia temporal;
- métricas;
- latencia.

### Reconocimiento de gestos corporales con Machine Learning

Rodrigo Ibañez, Álvaro Soria, Alfredo Teyseyre y Marcelo Campo. **Evaluación de técnicas de Machine Learning para el reconocimiento de gestos corporales.** 15th Argentine Symposium on Artificial Intelligence (ASAI), 2014.

Aspectos relevantes:

- comparación de DTW, Procrustes Analysis, Markov Chain y HMM;
- reconocimiento basado en trayectorias de articulaciones;
- centrado y normalización de esqueletos;
- tolerancia a diferentes contexturas físicas;
- DTW como método de alineación temporal;
- evaluación con 7 gestos y 80 muestras por gesto;
- precisión reportada de 99.1 % para DTW y 98.9 % para HMM;
- observación de rendimientos decrecientes al aumentar el dataset por encima de aproximadamente 40 muestras por gesto;
- limitación: cross-validation aleatoria por muestras, no separación estricta por sujeto.

### Crazyflie / MoCap / MQTT

César Adrian Schwendener Morales. **Desarrollo de herramientas de software para la evaluación de sensores de posicionamiento en el control individual y seguro del cuadricóptero Crazyflie 2.1.** Trabajo de graduación, UVG, 2025.

Aspectos relevantes:

- Robotat;
- Motive;
- NatNet;
- MQTT;
- formato de mensajes;
- MoCap como fuente de posicionamiento del Crazyflie.

---

## 33. Seguridad del repositorio

Nunca guardar en Git:

```text
contraseñas
credenciales RTSP
tokens
archivos .env
certificados privados
```

Utilizar:

```text
.env
.env.example
cameras.example.yaml
```

y agregar secretos a `.gitignore`.

---

## 34. Resumen de una línea

> Desarrollar un sistema de visión multicámara que utilice estimación de pose y reconocimiento temporal —iniciando con DTW/HMM y comparándolo posteriormente con LSTM/GRU— para reconocer gestos corporales naturales, fusionar las observaciones de seis cámaras Amcrest y convertir gestos confirmados en comandos seguros de alto nivel para drones Crazyflie dentro del Robotat.
