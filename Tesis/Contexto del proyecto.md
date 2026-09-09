# Contexto del proyecto

Documento de entrada para cualquier persona o agente que abra este vault sin conocer el proyecto. Explica qué es la tesis, qué se está construyendo, con qué hardware, cómo está organizado el código, qué decisiones ya se tomaron y qué falta. Los detalles finos viven en `AGENTS.md`, en `docs/` y en el código; este documento es el mapa.

Última revisión: 2026-09-08.

## 1. Qué es el proyecto

Trabajo de graduación de Albert Vandercam (Universidad del Valle de Guatemala) titulado **Control de drones basado en gestos mediante captura de movimiento en el ecosistema Robotat**.

En una frase: una persona mueve el cuerpo o las manos delante de unas cámaras, el sistema reconoce el gesto y uno o dos drones Crazyflie 2.1 obedecen dentro de un laboratorio con captura de movimiento (el Robotat).

### Objetivos del documento de tesis

- **General.** Desarrollar e implementar un sistema de control para drones Crazyflie 2.1 basado en gestos detectados por captura de movimiento dentro del ecosistema Robotat.
- **Específicos.**
  1. Validar el control punto a punto de un Crazyflie 2.1 usando la captura de movimiento del Robotat.
  2. Diseñar rutinas en Python que obtengan información de captura de movimiento para detectar gestos.
  3. Implementar un control intuitivo basado en movimientos corporales, pensado para entornos educativos.

### Un cambio de rumbo importante

El plan original detectaba gestos con un **traje de captura de movimiento**. Se cambió a **visión por computadora**: cámaras normales que observan al operador y estiman su esqueleto con MediaPipe. El objetivo 2 sigue siendo el mismo, pero la fuente de datos ya no es el traje sino las cámaras. Cuando un texto viejo hable del traje, léase "cámaras de visión".

### Meta final

Instalar **seis cámaras IP** justo debajo de las seis cámaras infrarrojas del OptiTrack que ya están montadas en el Robotat, y reconocer con ellas gestos corporales **dinámicos y en 3D** (aplaudir, poses, secuencias de brazos) en tiempo real para mandar comandos a los Crazyflies. El par estéreo de dos cámaras que ya se probó es un banco de pruebas, no la geometría definitiva.

## 2. El entorno físico

| Elemento | Qué es | Papel en el proyecto |
|---|---|---|
| **Robotat** | Laboratorio de robótica de la UVG con captura de movimiento OptiTrack | Escenario de vuelo y fuente de posición de los drones |
| **OptiTrack / mocap** | Seis cámaras infrarrojas que ven marcadores reflectivos | Publica por MQTT la posición y orientación de cada dron (tópicos `mocap/...`) |
| **Crazyflie 2.1** | Nanodron de Bitcraze, ~30 g, radio Crazyradio | El dron que se controla. Hay dos, con marcadores del Robotat |
| **Flow Deck v2** | Placa óptica que mide velocidad y altura sin referencia externa | Alternativa para volar fuera del Robotat; no da posición absoluta ni rumbo |
| **Cámaras IP** | Cámaras de red con stream RTSP (pan/tilt motorizadas) | Observan al operador. Dos ya probadas en estéreo; seis previstas |
| **Marker 65** | Un marcador del Robotat sin dron | Sirve de joystick y de objetivo a seguir; es el control que los gestos van a sustituir |

### Dos sistemas de cámaras que no se mezclan

Es la confusión más fácil de cometer y atraviesa código, tesis y gráficas.

| | OptiTrack / mocap | Cámaras IP de visión |
|---|---|---|
| Observa | **al dron** (marcadores infrarrojos) | **al operador** (persona, luz visible) |
| Produce | posición y orientación métricas | landmarks corporales 2D o 3D |
| Transporte | MQTT | RTSP |
| Consumidor | el estimador del dron (`extpos`) y las validaciones de seguridad | el reconocedor de gestos |

Se encuentran en un único punto: el **supervisor** que decide si un gesto se convierte en orden de vuelo, porque necesita saber dónde está el dron. La única otra intersección es la calibración: el mocap da la verdad de terreno para colocar las cámaras IP en el marco del Robotat.

## 3. Cómo está organizado el código

Todo vive en un solo repositorio, `tesis`, desde el 7 de septiembre de 2026. Antes la percepción 3D era un repositorio aparte (`mapeo_tridimensional_con_camaras`); hoy es la carpeta `external/mapeo3d/`.

| Carpeta | Qué contiene |
|---|---|
| `controllers/two_drones/` | Los **dos backends de vuelo** y todo lo que coordina dos drones a la vez: botones, cámara, telemetría, análisis de sesiones |
| `controllers/single_drone/camera/` | `control_camara_dron1.py`: el único controlador por cámara para un dron. Elige reconocedor (`cuerpo` 3D o `manos` 2D) y backend (`mocap` o `flowdeck`) |
| `controllers/single_drone/buttons/` | Panel de botones para un dron |
| `controllers/joystick/` | El marker 65 como joystick y como objetivo a seguir; receptor MQTT |
| `controllers/shared/` | Radios, identidad del Robotat, configuración del estimador, teclado Tk, CSV de sesión |
| `external/gesture_detection/` | Visión: tracking de manos, vocabulario 3D de cuerpo, banco de pruebas y grabación de gestos. No sabe nada de drones |
| `external/mapeo3d/` | Percepción 3D multicámara: captura RTSP, calibración, landmarks 2D por cámara, triangulación al marco del Robotat. Tampoco sabe nada de drones |
| `web/` | Panel web local que manda al backend de mocap |
| `results/` | Datos, gráficas y capturas generadas (no es código) |
| `docs/` | Documentación para agentes y personas técnicas |
| `thesis/` | El documento LaTeX de la tesis |
| `Tesis/` | Este vault de Obsidian |

Reglas de dependencia: lanzadores y web llaman a controladores; controladores llaman a backends; `single_drone` puede usar `two_drones`, nunca al revés; `gesture_detection` y `mapeo3d` no importan nada de control de vuelo.

## 4. Cómo vuela un dron

Hay exactamente **dos formas de volar**, y todo controlador usa una de las dos.

1. **Con mocap (la forma por defecto).** El Robotat publica la posición del dron por MQTT; el código la reenvía al dron como posición externa (`extpos`) y el filtro de Kalman del firmware la fusiona con la IMU. El código entonces sólo manda órdenes de alto nivel al firmware: `takeoff`, `go_to`, `land`, `stop`. Vive en `controllers/two_drones/cruz_highlevel_backend.py`. Valida geocerca, ventana de altura, separación entre drones, frescura del mocap y error del estimador. Tiene un `SimulatedBackend` para probar sin hardware con `--dry-run`.
2. **Con Flow Deck.** Sin referencia externa, el dron vuela por velocidad con `MotionCommander`. Vive en `controllers/two_drones/flowdeck_dual_backend.py`. Tiene techo, piso y "deadman": si no llegan órdenes, se detiene y aterriza.

**No existe ningún lazo de velocidad propio sobre el mocap.** Existió, se llamaba low-level, y se eliminó en septiembre de 2026 porque duplicaba lo que el firmware ya hace bien. No hay que reintroducirlo.

## 5. Cómo se reconoce un gesto

```text
cámara(s) ──► landmarks del cuerpo o la mano ──► reglas de clasificación ──► GestureEvent ──► supervisor ──► backend de vuelo
```

- **Manos en 2D** (`hand_gesture_detector.py`): una cámara, MediaPipe Hands, nueve comandos. Es lo que vuela hoy con más horas de prueba.
- **Cuerpo en 3D** (`recognition/body_3d_rules.py`): MediaPipe Pose con coordenadas 3D relativas, vocabulario de gestos de cuerpo entero, gestos estáticos y dinámicos con plantillas. Tiene banco de pruebas y práctica guiada sin dron.
- **Multicámara** (`external/mapeo3d/`): varias cámaras IP calibradas triangulan las articulaciones a coordenadas reales del laboratorio. Es el paso que permite gestos 3D robustos y saber "dónde está la mano respecto al dron". Captura, calibración y triangulación estéreo ya funcionan; falta el anclaje al marco del Robotat con seis cámaras y el contrato de datos hacia los controladores.

## 6. Estado del proyecto

| Pieza | Estado |
|---|---|
| Vuelo punto a punto con mocap, uno y dos drones | Funciona. Es la base del objetivo 1 |
| Vuelo con Flow Deck | Funciona |
| Botones, teclado, panel web, joystick con marker | Funcionan |
| Gestos de mano 2D volando un dron | Funciona |
| Gestos de cuerpo 3D volando un dron | Funciona con una cámara; vocabulario en evolución |
| Percepción multicámara | Estéreo de dos cámaras calibrado y probado; seis cámaras pendientes de instalar |
| Contrato de datos mapeo3d a controladores | Pendiente (tarea T-002) |
| Documento de tesis | Plantilla LaTeX con objetivos; capítulos por redactar |

### Problemas abiertos

- **Oscilación con el backend de mocap.** Se creía exclusiva de dos drones, pero las sesiones grabadas muestran la misma oscilación de 0.35 a 0.45 Hz con un solo dron y en hover. Causas probables: posición externa limitada a 20 Hz (se pierde la mitad de los frames del Robotat), yaw que nunca se envía al estimador, y `go_to` solapados en el seguimiento del marker. Análisis en [60-Analisis](60-Analisis/2026-09-08%20Oscilación%20con%20dos%20drones.md); tareas T-003 y T-004.
- **Tamaño del código.** Unas 23 mil líneas de Python. Ya se recortó de 21.9k a 14.5k en la parte de control en septiembre de 2026; con la fusión de mapeo3d volvió a subir. Hay duplicación entre scripts de visión y entre apps de calibración. El 8 de septiembre se borraron los controles Flow Deck sin consumidor, se fusionó el detector dinámico suelto y los tests pasaron a pytest; quedan las utilidades compartidas y la fusión de los dos backends de la cruz. Análisis y plan en [60-Analisis](60-Analisis/2026-09-08%20Optimización%20del%20código.md).
- **Entornos.** Resuelto el 8 de septiembre: el `.venv` de la raíz cubre también `mapeo3d` y `requirements.txt` está unificado (T-001, pendiente de revisión).
- **Redacción.** El documento LaTeX está casi vacío más allá de los objetivos.

## 7. Decisiones ya tomadas

No se vuelven a discutir salvo que aparezca evidencia nueva. Cada una tiene o tendrá su nota en `30-Decisiones`.

1. **Visión por computadora en lugar de traje de captura** para detectar gestos.
2. **Mocap por defecto** para todo control nuevo; Flow Deck sólo cuando se pida.
3. **Todo el vuelo con mocap pasa por el commander high-level del firmware.** Sin lazos low-level propios.
4. **Un solo controlador por cámara** para un dron, con reconocedor y backend elegibles.
5. **Un solo repositorio** (`tesis`) con `mapeo3d` como subsistema en `external/`.
6. **Seis cámaras en anillo** como geometría objetivo; el estéreo fue una prueba.

## 8. Cómo trabajamos

El trabajo se reparte entre el autor y tres agentes de IA (Claude Code, Codex y Gemini) usando este vault como tablero. Cada tarea es una nota en `10-Tareas` con objetivo, criterio de aceptación y agente asignado; el agente la ejecuta desde la raíz del repositorio y reporta en la propia tarea y en `20-Bitacora`. El protocolo completo está en `AGENTS.md` y el reparto en [Agentes](Agentes.md); el punto de partida es [Inicio](Inicio.md).

Además hay un grafo de conocimiento del código (`graphify-out/graph.html` en la raíz) que los agentes consultan antes de buscar a mano.

## 9. Glosario

- **Robotat**: laboratorio de robótica de la UVG con captura de movimiento.
- **Mocap / OptiTrack**: sistema de cámaras infrarrojas que localiza marcadores reflectivos con precisión milimétrica.
- **extpos**: posición externa que se envía al dron para que su estimador la use.
- **EKF / Kalman**: filtro del firmware que fusiona IMU y posición externa para estimar dónde está el dron.
- **Commander high-level**: módulo del firmware que ejecuta trayectorias (`takeoff`, `go_to`, `land`) por sí solo.
- **Flow Deck**: sensor óptico de flujo y altura para volar sin mocap.
- **Geocerca**: volumen permitido de vuelo; fuera de él el dron aterriza.
- **Landmarks**: puntos del esqueleto (muñeca, codo, hombro...) que devuelve MediaPipe.
- **Triangulación / DLT**: cálculo de un punto 3D a partir de su proyección en varias cámaras calibradas.
- **Intrínsecos / extrínsecos**: parámetros internos de una cámara (lente) y su posición y orientación en el mundo.
- **RTSP**: protocolo con el que las cámaras IP entregan vídeo.
- **GestureEvent**: el contrato de datos entre el reconocedor de gestos y el supervisor de vuelo.
- **Dry-run**: ejecución simulada sin hardware.

## 10. Cronología breve

- **2026-08**: plantilla LaTeX, primeros controladores con Flow Deck, gestos de mano 2D.
- **2026-09-01 a 04**: repositorio de percepción 3D; calibración estéreo de dos cámaras; primeras poses 3D.
- **2026-09-05**: decisión de volar contra el mocap por defecto.
- **2026-09-06 a 07**: recorte del repositorio de control (pasos 1 a 4 del plan); un solo controlador por cámara; sin low-level.
- **2026-09-07**: fusión de repositorios, vault de Obsidian, protocolo de agentes, grafo del proyecto.
