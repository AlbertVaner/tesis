# Graph Report - tesis  (2026-09-08)

## Corpus Check
- 186 files · ~171,712 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 2615 nodes · 5161 edges · 143 communities (120 shown, 20 thin omitted)
- Extraction: 89% EXTRACTED · 11% INFERRED · 0% AMBIGUOUS · INFERRED: 548 edges (avg confidence: 0.87)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `c338c7d1`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- MultiCameraSync
- test_dinamicos.py
- Gesture
- CsvSession
- test_canonical.py
- AGENTS.md: contrato canónico para agentes
- HighLevelButtonsApp
- Command
- calibration/__init__.py
- test_diagnostico.py
- detectar_episodios
- test_probe.py
- VelocityIntent
- test_body_3d_rules.py
- project
- grafica_comandos.py
- ReglaParo
- ProcessBackend
- external/mapeo3d/
- Body3DRecognizer
- ExperimentSession
- grabar_gestos.py
- CameraIntrinsics
- capture/__init__.py
- probar_vocabulario.py
- probar_gestos_3d.py
- test_extrinsics.py
- control_camara_dron1.py
- test_robust.py
- FlowDroneController
- SessionTests
- CameraStream
- fake_cf
- body_3d_rules.py
- test_apps.py
- dtw_distancia
- Jitter
- CameraMarkerFollower
- cruz_highlevel_backend.py
- StereoExtrinsics
- test_draw.py
- flowdeck_flight.py
- check_pose3d.py
- test_dataset.py
- HighlevelCameraMarkerRuntime
- Arquitectura actual (docs/agents/architecture.md)
- Pose
- HighLevelFlight
- dinamicos.py
- segment_length_stability
- ChessboardSpec
- test_calibration.py
- app.js
- comparar_2d_3d.py
- extrinsics.py
- HandGestureDetector
- demo_pose3d.py
- test_grafica_comandos.py
- diagnose_camera.py
- Landmarks2D
- load_config
- SimulatedBackend
- hand_tracker.py
- DroneUnit
- Handler
- gui_pdf_capture.py
- test_camera_flight_safety.py
- DualStepKeysMixin
- construir_plantillas.py
- Anclaje al marco Robotat con blanco rastreado por el MoCap
- EstimadorDeEscala
- Pipeline de gestos por vision: diseno (docs/agents/gesture_pipeline.md)
- test_highlevel_flight.py
- BancoDinamico
- flowdeck_dual_backend.py
- capturar_en_vivo
- mapeo3d/pose/__init__.py
- server.py
- GraficaDeComandos
- MarkerFollowTests
- MocapReceiver
- Panel web UVG Drone Lab (index.html)
- Practica
- ProcessBackendCloseTests
- hand_gesture_detector.py
- PoseDetector
- control_camara_dron1.py (controlador único por cámara)
- Oscilación de los drones con el backend de mocap
- flowdeck_feedback.py
- datetime
- Toma
- calibrate_stereo.py
- check_connection.py
- control_dos_drones_cruz_camara_multiprocessing.py
- angle_delta_deg
- HandTracker
- Backend high-level de la cruz (cruz_highlevel_backend.py)
- SessionRecording
- Reconocedor cuerpo 3D (MediaPipe Pose)
- Estado del reconocedor DTW: validación y qué falta
- sin_hardware
- test_grabar_vocabulario.py
- FollowGestureTests
- SessionConfig
- DLT de N vistas
- normalize.py
- StreamStats
- marker_mocap.py
- conftest.py
- Redes Neuronales Profundas: Detalles de Entrenamiento
- Lineas
- triangulation/__init__.py
- AlignmentDiagnosticTests
- --dry-run: backend high-level simulado sin radio ni mocap
- FakeCommander
- _P
- Opciones para bajar líneas de código
- Comandos para probar los programas
- discover_marker_id.py
- Receiver
- Medida
- 7.1. Para Tareas de Regresión
- dataset/__init__.py
- gesture_detection/pose/__init__.py
- recognition/__init__.py
- visualization/__init__.py
- mapeo3d/__init__.py
- shared/tk_keys.py (DualStepKeysMixin, HeldKeysMixin)
- Telefono como camara IP para pruebas
- Funcionamiento externo (external/README.md)
- Stack científico (numpy, pandas, scipy, scikit-learn)
- por_estilo
- 1. Motivación: ¿Por qué Deep Learning?
- 2.2. Capacidad de Partición: Redes Superficiales vs. Redes Profundas
- 8. Técnicas de Regularización
- InterruptTests
- 12. Implementación Práctica de un Perceptrón en Frameworks Modernos
- 3. Dinámica de Entrenamiento y Optimización
- 4. Métricas de Evaluación y Matriz de Confusión
- 10. Heurísticas Fundamentales de Entrenamiento

## God Nodes (most connected - your core abstractions)
1. `Command` - 58 edges
2. `Gesture` - 46 edges
3. `HardwareBackend` - 42 edges
4. `Pipeline de gestos por vision: diseno (docs/agents/gesture_pipeline.md)` - 36 edges
5. `ExperimentSession` - 35 edges
6. `CameraIntrinsics` - 35 edges
7. `SimulatedBackend` - 34 edges
8. `MultiCameraSync` - 33 edges
9. `CameraStream` - 31 edges
10. `VelocityIntent` - 29 edges

## Surprising Connections (you probably didn't know these)
- `Yaw nunca enviado al EKF` --references--> `configure_estimator()`  [EXTRACTED]
  Tesis/60-Analisis/2026-09-08 Oscilación con dos drones.md → controllers/shared/crazyflie_link.py
- `--dry-run: SimulatedBackend, validacion sin radio ni mocap` --conceptually_related_to--> `SimulatedBackend`  [EXTRACTED]
  docs/agents/operations.md → controllers/two_drones/cruz_highlevel_backend.py
- `SimulatedBackend` --implements--> `Dry-run (simulación sin hardware)`  [EXTRACTED]
  controllers/two_drones/cruz_highlevel_backend.py → Tesis/Contexto del proyecto.md
- `Arquitectura actual (docs/agents/architecture.md)` --references--> `SimulatedBackend`  [EXTRACTED]
  docs/agents/architecture.md → controllers/two_drones/cruz_highlevel_backend.py
- `control_camara_dron1.py (controlador unico por camara)` --conceptually_related_to--> `HardwareBackend`  [EXTRACTED]
  docs/agents/architecture.md → controllers/two_drones/cruz_highlevel_backend.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **GestureEvent/Recognizer unifica reconocedores intercambiables** — external_gesture_detection_contracts_gestureevent, external_gesture_detection_recognition_base_recognizer, external_gesture_detection_recognition_body_3d_rules, external_gesture_detection_recognition_legacy_hand_rules_module [EXTRACTED 0.95]
- **Consumidores del backend high-level de la cruz** — controllers_two_drones_readme_control_cruz_python_cruz_highlevel_backend, controllers_single_drone_camera_readme_highlevel_flight, controllers_two_drones_control_dos_drones_cruz_botones, controllers_two_drones_control_dos_drones_cruz_multiprocessing, controllers_two_drones_readme_control_cruz_python_control_dos_drones_camara, web_readme_experiment_session, web_static_index_direction_pad [EXTRACTED 1.00]
- **Decisiones ya tomadas (no se rediscuten sin evidencia nueva)** — tesis_contexto_del_proyecto_decision_vision_en_lugar_de_traje, tesis_contexto_del_proyecto_decision_mocap_por_defecto, tesis_contexto_del_proyecto_decision_sin_low_level, tesis_contexto_del_proyecto_decision_un_solo_controlador_por_camara, tesis_contexto_del_proyecto_decision_un_solo_repositorio, tesis_contexto_del_proyecto_seis_camaras_en_anillo [EXTRACTED 1.00]
- **Mitigacion del riesgo pan/tilt en tres capas** — external_mapeo3d_agents_prohibicion_ptz, external_mapeo3d_docs_calibration_coherencia_entre_pares, external_mapeo3d_config_cameras_example_integrity_check_aruco, external_mapeo3d_docs_calibration_integridad_de_calibracion [EXTRACTED 1.00]
- **Pipeline cámara ─ landmarks ─ reglas ─ GestureEvent ─ supervisor ─ backend** — tesis_contexto_del_proyecto_camaras_ip, tesis_contexto_del_proyecto_landmarks, tesis_contexto_del_proyecto_gestureevent, tesis_contexto_del_proyecto_supervisor, controllers_two_drones_cruz_highlevel_backend [EXTRACTED 1.00]
- **Plan de reducción de líneas por carpeta** — tesis_60_analisis_2026_09_08_optimizacion_del_codigo_tests_a_pytest, tesis_60_analisis_2026_09_08_optimizacion_del_codigo_codigo_sin_consumidor, tesis_60_analisis_2026_09_08_optimizacion_del_codigo_fundir_backends, tesis_60_analisis_2026_09_08_optimizacion_del_codigo_utilidades_gesture_detection, tesis_60_analisis_2026_09_08_optimizacion_del_codigo_utilidades_mapeo3d [EXTRACTED 1.00]
- **Módulos de controllers/shared/ (reutilización real sin lógica de vuelo)** — controllers_shared_readme_robotat, controllers_shared_readme_radios, controllers_shared_readme_crazyflie_link, controllers_shared_flowdeck_flight, controllers_shared_flowdeck_feedback, controllers_shared_readme_tk_keys, controllers_shared_csv_session, controllers_shared_gui_pdf_capture, controllers_shared_readme_reuse_criterion [EXTRACTED 1.00]
- **Equipo de tres agentes (Claude, Codex, Gemini) y sus archivos de instrucciones** — tesis_agentes_claude_code, tesis_agentes_codex, tesis_agentes_gemini, claude_instrucciones_claude, gemini_instrucciones_gemini, agents_contrato_para_agentes [EXTRACTED 1.00]
- **Arquitectura de dos backends de vuelo y sus consumidores** — agents_dos_backends_de_vuelo, agents_cruz_highlevel_backend, agents_flowdeck_dual_backend, agents_highlevel_flight, agents_control_camara_dron1, readme_web_panel [EXTRACTED 1.00]
- **Flujo de tareas del vault: plantilla, tarea, tablero, bitácora, protocolo** — agents_protocolo_del_vault, tesis__plantillas_tarea, tesis_tablero, tesis_tablero_frontmatter_de_tarea, tesis_10_tareas_t_001_unificar_entornos, tesis_10_tareas_t_002_contrato_de_datos_mapeo3d_a_controladores, tesis_20_bitacora_2026_09_07 [EXTRACTED 1.00]
- **Vuelo con mocap: MQTT ─ extpos ─ EKF ─ commander high-level** — tesis_contexto_del_proyecto_optitrack_mocap, tesis_contexto_del_proyecto_mqtt, tesis_contexto_del_proyecto_extpos, tesis_contexto_del_proyecto_ekf_kalman, tesis_contexto_del_proyecto_commander_high_level, controllers_two_drones_cruz_highlevel_backend [EXTRACTED 1.00]
- **Los dos backends de vuelo y sus consumidores** — controllers_two_drones_cruz_highlevel_backend_hardwarebackend, controllers_two_drones_flowdeck_dual_backend_flowdronecontroller, controllers_single_drone_camera_control_camara_dron1_module, controllers_two_drones_experiment_session [INFERRED 0.80]
- **Causas probables de la oscilación con mocap** — tesis_60_analisis_2026_09_08_oscilacion_con_dos_drones_extpos_limitado_20_hz, tesis_60_analisis_2026_09_08_oscilacion_con_dos_drones_yaw_no_enviado, tesis_60_analisis_2026_09_08_oscilacion_con_dos_drones_go_to_solapados, tesis_60_analisis_2026_09_08_oscilacion_con_dos_drones_oscilacion_0_4_hz [INFERRED 0.85]
- **Cadena metrica: tablero a escala, rectificacion y verificacion por casilla reconstruida** — external_mapeo3d_readme_tablero_calibracion_regla_100mm, external_mapeo3d_docs_calibration_rectificar_antes_de_triangular, external_mapeo3d_readme_verificacion_metrica_casilla_reconstruida, external_mapeo3d_docs_calibration_extrinsecos_estereo [INFERRED 0.85]
- **Frontera mapeo3d ↔ tesis por contrato de datos PoseFrame3D** — external_mapeo3d_agents_contrato_para_agentes, external_mapeo3d_docs_architecture_poseframe3d, external_mapeo3d_config_cameras_example_output_mqtt_vision_pose3d, controllers_single_drone_camera_control_camara_dron1 [INFERRED 0.85]
- **Tension entre papers que motiva la separacion canal continuo/eventos** — paper_gio_2021, paper_obaid_2016, paper_ibanez_2014, concept_canal_continuo_canal_eventos [INFERRED 0.85]
- **Seguimiento del marker 65 en todos los controles por cámara** — controllers_joystick_readme_marker_follow, controllers_joystick_readme_marker_65_follow_protocol, controllers_single_drone_camera_readme_control_camara_dron1, controllers_two_drones_readme_control_cruz_python_control_dos_drones_camara, web_readme_hands_control, web_static_index_session_form [INFERRED 0.95]

## Communities (143 total, 20 thin omitted)

### Community 0 - "MultiCameraSync"
Cohesion: 0.05
Nodes (53): Extrinsecos estereo (intrinsecos fijos, tablero al 8 %), Sesgo constante por camara invisible a la tolerancia, ConjuntoSincronizado, MultiCameraSync, Emparejamiento temporal de varias cámaras sin sincronización por hardware. Las…, Los frames de un mismo instante, con lo que quedó fuera y por qué., `{nombre: frame}` para quien sólo quiera las imágenes., Salud del emparejamiento a lo largo de una sesión. No es depuración: con seis… (+45 more)

### Community 1 - "test_dinamicos.py"
Cohesion: 0.17
Nodes (25): Segmenta el movimiento en vivo y clasifica cada segmento., ReconocedorDinamico, banco_de_prueba(), Reconocedor de gestos dinamicos. Sin camara, sin MediaPipe y sin dron. Se…, Pasa una trayectoria cuadro a cuadro y devuelve las detecciones., De pie sin moverse no puede salir ningun gesto., Un aplauso se detiene un instante en cada palmada. Si eso cerrara el segmento,…, El hallazgo que motivo la clase de rechazo: un banco de solo gestos buenos no… (+17 more)

### Community 2 - "Gesture"
Cohesion: 0.10
Nodes (23): evento(), FakeFlight, FakeFollow, Verifica la traduccion de gesto a orden de vuelo. Sin radio ni motores. Lo…, Con mocap las ordenes van en el marco de la SALA y `rumbo` es hacia donde mira…, `confirmed=False` significa «no ejecutar». Es la regla del contrato., Doble del backend de vuelo: registra ordenes, no toca hardware., La nariz del dron 90 grados a TU izquierda: tu ADELANTE queda, visto desde el… (+15 more)

### Community 3 - "CsvSession"
Cohesion: 0.09
Nodes (17): CsvSession, Path, Abre `<prefijo>_<marca>.csv`, o `<filename>.csv` si se da un nombre., Escribe una fila si la sesión está activa; devuelve si se escribió., Genera las gráficas de `path`; devuelve la carpeta creada o `None`., analyze_session(), main(), number() (+9 more)

### Community 4 - "test_canonical.py"
Cohesion: 0.08
Nodes (52): Comparacion 2D vs 3D canonicalizado por angulo, Marco corporal (canonicalizacion), canonicalizar(), canonicalizar_secuencia(), escala_de_sesion(), marco_corporal(), normalizar(), ndarray (+44 more)

### Community 5 - "AGENTS.md: contrato canónico para agentes"
Cohesion: 0.10
Nodes (51): AGENTS.md, AGENTS.md: contrato canónico para agentes, control_camara_dron1.py: controlador único por cámara, controllers/shared: utilidades reutilizadas, Criterio para crear y ubicar archivos nuevos, cruz_highlevel_backend.py (HardwareBackend / SimulatedBackend), Dos backends de vuelo y ninguno más, flowdeck_dual_backend.py (FlowDroneController) (+43 more)

### Community 6 - "HighLevelButtonsApp"
Cohesion: 0.15
Nodes (6): Traduce `radio://<serial>/...` a `radio://<indice USB>/...`. Las URIs que ya…, resolve_serial_uris(), HighLevelButtonsApp, Any, Mueve un objetivo concreto; se usa por botones y por teclado dual., LabelFrame

### Community 7 - "Command"
Cohesion: 0.16
Nodes (9): BridgeError, HardwareBackend, RuntimeError, Movimiento del seguidor sin geocerca de origen ni límites de altura., Backend cflib persistente; solo esta clase toca las Crazyradio., Sigue al marker sin geocerca de origen ni límites absolutos de XYZ., Operacion rechazada por estado o seguridad., Command (+1 more)

### Community 8 - "calibration/__init__.py"
Cohesion: 0.11
Nodes (33): capturar_pares(), corner_centroid(), corner_extent(), corner_movement(), corner_span(), draw_corners(), find_corners(), find_corners_preview() (+25 more)

### Community 9 - "test_diagnostico.py"
Cohesion: 0.06
Nodes (45): brillo(), detectar_flanco(), Latencia, ndarray, Latencia extremo a extremo de una cámara, medida con destellos. El número que…, Brillo medio de un frame, submuestreado para que sea barato. Se toma un décimo…, Resultado de una campaña de medidas de latencia., Latencia en segundos entre el destello y el primer frame iluminado. Args:… (+37 more)

### Community 10 - "detectar_episodios"
Cohesion: 0.08
Nodes (39): detectar_episodios(), distancia(), Episodio, ndarray, rapidez(), Detección de episodios en una señal derivada de la pose. El problema que…, `(T,)` distancia entre dos landmarks a lo largo del tiempo., `(T,)` rapidez de un landmark. El primer valor es `NaN`. Se divide por el… (+31 more)

### Community 11 - "test_probe.py"
Cohesion: 0.07
Nodes (34): cabecera_autorizacion(), describe(), _digest(), _parsear(), puerto_abierto(), Sondeo RTSP de bajo nivel, para saber POR QUÉ no conecta una cámara.…, Envía `DESCRIBE` y devuelve `(estado, motivo, cabeceras)`. Si la cámara…, Diagnóstico de una cámara: qué funciona y qué no. (+26 more)

### Community 12 - "VelocityIntent"
Cohesion: 0.14
Nodes (16): Canal continuo, en el marco del cuerpo del operador. Unidades normalizadas…, VelocityIntent, Un dron imaginario que responde al vocabulario como lo haria el real., Gesto dinamico o de estado. `(accion, motivo)`; motivo vacio si se ejecuto., Canal continuo. Se llama cada frame con la direccion confirmada., Sin direccion confirmada, la velocidad manual vuelve a cero., Simulador, Supervisor simulado del probador de vocabulario. Sin camara. Verifica la… (+8 more)

### Community 13 - "test_body_3d_rules.py"
Cohesion: 0.10
Nodes (36): Angulo entre cada par de direcciones, de menor a mayor. Es la comprobacion que…, separaciones_del_vocabulario(), _brazo(), FakeLandmark, pose(), ndarray, Comprueba el vocabulario 3D sin camara, sin dron y sin MediaPipe. Construye…, Pasa la misma pose durante `segundos`. Devuelve `(ultimo_evento,… (+28 more)

### Community 14 - "project"
Cohesion: 0.10
Nodes (33): angulo_utilizable(), grid_spacing(), project(), ndarray, Triangulación lineal de N vistas por DLT. Este módulo no sabe qué es RTSP ni…, Proyecta puntos 3D con una matriz `(3, 4)`. Devuelve `(K, 2)`., Error de reproyección en píxeles, por punto: `(K,)`. Es lo que permite al…, Ángulo entre los rayos de dos cámaras hacia un punto, en grados. Es lo que… (+25 more)

### Community 15 - "grafica_comandos.py"
Cohesion: 0.25
Nodes (13): agrupar(), _color(), _figura(), Muestra, orden_de_filas(), Gráfica de tiempo contra comandos para los controladores por cámara. Cada…, Tramos consecutivos con la misma `clave(muestra)`: `(valor, inicio, fin)`. Cada…, Un tramo por cada racha de `(comando, confirmado)` iguales. (+5 more)

### Community 16 - "ReglaParo"
Cohesion: 0.10
Nodes (30): Paro de emergencia: X sobre la cabeza, Medida, medidas_cabeza(), medidas_pecho(), ndarray, Paro de emergencia: una postura sostenida, evaluada frame a frame. Es el unico…, X sobre el pecho. Umbrales medidos el 2026-09-07; margen escaso., Evalua la postura frame a frame y dispara al sostenerse. (+22 more)

### Community 17 - "ProcessBackend"
Cohesion: 0.23
Nodes (4): ProcessBackend, Any, Adaptador de la GUI al backend propietario del hardware., Process

### Community 18 - "external/mapeo3d/"
Cohesion: 0.07
Nodes (36): controllers/joystick/, controllers/shared/, controllers/single_drone/ (buttons, flowdeck), controllers/two_drones/, external/gesture_detection/, external/mapeo3d/, Albert Vandercam, Cámaras IP (RTSP, pan/tilt) (+28 more)

### Community 19 - "Body3DRecognizer"
Cohesion: 0.07
Nodes (18): Gate de engagement obligatorio antes de cualquier comando, evento_de_mano(), _gesto_de_mano(), Vocabulario 3D de cuerpo entero, mas los dos gestos de mano del marker., Traduce la etiqueta del detector de mano al contrato `GestureEvent`. El…, Gestos de una mano en 2D. Prototipo anterior al vocabulario corporal., ReconocedorCuerpo, ReconocedorManos (+10 more)

### Community 21 - "grabar_gestos.py"
Cohesion: 0.13
Nodes (23): carpeta_de_hoy(), Guardado y lectura de tomas de gestos. Una **toma** es una repeticion de un…, bucle(), como_hacerlo(), construir_guion(), dibujar(), encuadre(), main() (+15 more)

### Community 22 - "CameraIntrinsics"
Cohesion: 0.09
Nodes (18): CameraIntrinsics, escribir_reporte(), Path, Resultado de una calibración intrínseca., Escribe el `report.md` que exige docs/calibration.md. Una calibración sin su…, Campo de visión horizontal, derivado del ajuste. Sustituye a la medición con…, Metros de alto que abarca el cuadro por cada metro de distancia. Es el número…, Distancia mínima para que un objeto de ese alto quepa entero. Supone la cámara… (+10 more)

### Community 23 - "capture/__init__.py"
Cohesion: 0.10
Nodes (23): CameraConfig, CaptureConfig, Config, ConfigNotFound, find_config(), FileNotFoundError, Path, Carga de la configuración de cámaras. La configuración real vive en… (+15 more)

### Community 24 - "probar_vocabulario.py"
Cohesion: 0.15
Nodes (13): bucle(), dibujar_panel(), _direccion_mas_cercana(), Lineas, main(), _panel_dinamicos(), _panel_estado(), _panel_estaticos() (+5 more)

### Community 25 - "probar_gestos_3d.py"
Cohesion: 0.12
Nodes (20): bucle(), _contador_compacto(), dibujar_panel(), _falta_dos_manos(), main(), Counter, _que_falta(), Prueba del vocabulario 3D. Sin dron, sin radio y sin cflib. No importa… (+12 more)

### Community 26 - "test_extrinsics.py"
Cohesion: 0.10
Nodes (26): calibrate_stereo(), Estima la pose de la cámara B respecto de la A. Los intrínsecos se fijan…, extrinsecos(), intrinsecos(), pares(), pose_real(), fixture, Pruebas de la calibración estéreo, sin cámaras. Se simulan dos cámaras con una… (+18 more)

### Community 27 - "control_camara_dron1.py"
Cohesion: 0.10
Nodes (25): Lanzador canónico del control de un Crazyflie por cámara y gestos., al_marco_del_dron(), al_marco_del_mundo(), _altura(), _aplicar(), bucle(), _comando_ejecutado(), crear_vuelo() (+17 more)

### Community 28 - "test_robust.py"
Cohesion: 0.15
Nodes (26): _angulo(), anillo(), _K(), proyectar(), ndarray, Triangulación robusta de N vistas, con datos sintéticos y sin cámaras. El…, Rayos colineales: la intersección queda indeterminada., 0.5 px de ruido de detección sobre seis vistas a 2.5 m. (+18 more)

### Community 29 - "FlowDroneController"
Cohesion: 0.10
Nodes (9): FlowDroneController, Crazyflie, Bloquea hasta que termina el preflight; lanza `RuntimeError` si falló., Registra stateEstimate.z para poder limitar la altura en vuelo., Bloquea ascenso sobre el techo y descenso bajo el piso., Atiende la cola hasta `close` o emergencia. Devuelve si hubo emergencia., Deadman y aterrizaje por silencio; corre en el hilo dueño de la radio., Un hilo es dueño exclusivo de una Crazyradio y un Crazyflie. (+1 more)

### Community 31 - "CameraStream"
Cohesion: 0.09
Nodes (16): Marcas de tiempo de llegada, no de camara, Captura sin acumular latencia (hilo lector, solo ultimo frame), Reloj perf_counter, no monotonic, Sincronizacion por vecino mas cercano con tolerancia, _ahora(), CameraStream, Devuelve `(frame, timestamp)` si hay uno nuevo, o `None`. El timestamp es de…, Como `read()`, pero devuelve el último frame aunque ya se haya leído. Útil para… (+8 more)

### Community 32 - "fake_cf"
Cohesion: 0.12
Nodes (5): ControllerIntegrationTests, fake_cf(), FakeParam, FeedbackTests, Seleccion Robotat/Flow Deck con firmware falso; sin MQTT, camara ni radio.

### Community 33 - "body_3d_rules.py"
Cohesion: 0.14
Nodes (21): _angulo_deg(), _angulo_sagital(), angulos_a_direcciones(), BrazoActivo, clasificar(), _confianza(), _direccion(), _en_reposo() (+13 more)

### Community 34 - "test_apps.py"
Cohesion: 0.07
Nodes (36): app_calibracion(), app_pose3d(), _args(), _fourcc(), _mundo_sintetico(), _placa_tablero(), fixture, Namespace (+28 more)

### Community 35 - "dtw_distancia"
Cohesion: 0.15
Nodes (21): dtw_distancia(), ndarray, Reconocimiento de gestos dinamicos por comparacion con plantillas (DTW). Es el…, Distancia DTW entre dos trayectorias `(N, D)` y `(M, D)`. Se normaliza por el…, Umbral que mejor separa repeticiones del gesto de material sin el. Returns:…, umbral_por_separacion(), ndarray, r"""Comparacion de trayectorias por DTW y calculo del umbral. Sin camara y sin… (+13 more)

### Community 36 - "Jitter"
Cohesion: 0.17
Nodes (7): Encuadre, Jitter, Calidad del estimador 2D: ruido en reposo y encuadre. Dos medidas que deciden…, Si el cuerpo cabe entero en el cuadro, y con cuánto margen., Ruido de posición con el sujeto quieto, por landmark., Un solo número para comparar cámaras entre sí., Convierte el jitter mediano a milímetros sobre el sujeto. Un píxel a distancia…

### Community 37 - "CameraMarkerFollower"
Cohesion: 0.14
Nodes (10): CameraMarkerFollower, FollowUnavailable, _fresh(), RuntimeError, Seguimiento relativo de un marker Robotat para controladores de cámara. Este…, Velocidad para un backend `send_velocity_world_setpoint`., Velocidad para MotionCommander, expresada en el marco del dron., No se puede iniciar o conservar un seguimiento seguro. (+2 more)

### Community 38 - "cruz_highlevel_backend.py"
Cohesion: 0.11
Nodes (20): JsonLineServer, socket, r"""Backend Python/cflib para dos Crazyflies con control high-level. Este…, decode_command(), encode_response(), ProtocolError, Any, ValueError (+12 more)

### Community 39 - "StereoExtrinsics"
Cohesion: 0.09
Nodes (14): _errores_por_par(), ndarray, Path, Pose de la cámara B respecto de la A., Distancia entre los dos centros ópticos, en metros., Ángulo entre los ejes ópticos de las dos cámaras. No es el ángulo de…, Matrices `(3, 4)` de las dos cámaras, con origen en la cámara A. Es lo único…, Ángulo entre rayos hacia un punto, visto desde las dos cámaras. (+6 more)

### Community 40 - "test_draw.py"
Cohesion: 0.13
Nodes (25): camara_orbital(), Base de una cámara que orbita el origen mirándolo. Returns: `(ojo, base)` con…, pares_de_conexiones(), `CONEXIONES` como índices `(M, 2)`, para dibujar., test_el_esqueleto_2d_no_modifica_el_frame_original(), test_un_panel_3d_sin_persona_no_revienta(), _esqueleto(), Dibujado 3D: cambio de marco, cámara orbital y proyección en perspectiva. Es… (+17 more)

### Community 41 - "flowdeck_flight.py"
Cohesion: 0.12
Nodes (21): arm_if_supported(), configure_estimator(), Operaciones sobre un enlace Crazyflie que todos los controladores repiten.…, Pulso de `kalman.resetEstimation`., Prepara el Crazyflie para volar con posición externa del Robotat. Excluye la…, Arma explícitamente en cflib reciente; conserva compatibilidad antigua., Corta los motores de uno o varios Crazyflie repitiendo el stop setpoint. Se…, reset_kalman() (+13 more)

### Community 42 - "check_pose3d.py"
Cohesion: 0.14
Nodes (19): deque, _corto(), estabilidad(), guardar(), informe_final(), main(), _panel_3d(), _panel_texto() (+11 more)

### Community 43 - "test_dataset.py"
Cohesion: 0.17
Nodes (21): cargar(), cargar_todas(), guardar(), Path, Todas las tomas de una carpeta, en orden de nombre. Busca tambien en…, Escribe la toma y devuelve la ruta. No sobrescribe., _rasgos(), Dataset de gestos y comparacion 3D/2D. Sin camara y sin MediaPipe. Se… (+13 more)

### Community 44 - "HighlevelCameraMarkerRuntime"
Cohesion: 0.08
Nodes (9): HighlevelCameraMarkerRuntime, Adaptador del seguimiento de marker al backend high-level de cámara., Convierte objetivos del marker en pasos validados del backend., Cancela objetivos sin esperar al cierre del receptor MQTT., selected_keys(), Backend, Follower, Adaptación high-level del seguimiento, sin radio ni MQTT. (+1 more)

### Community 45 - "Arquitectura actual (docs/agents/architecture.md)"
Cohesion: 0.13
Nodes (21): Reduccion de ~21900 a ~14500 lineas sin perder funcionalidad de vuelo, controllers/joystick/marker_follow.py (seguimiento marker 65), Adaptador headless del marker joystick; no abre radios ni controla drones. Lee…, connected_radios(), make_uri(), Identidad de las Crazyradio y de los Crazyflie del laboratorio. Concentra…, URI cflib para una antena (serial o índice USB) y un enlace., Seriales de las Crazyradio conectadas por USB, en mayúsculas. (+13 more)

### Community 46 - "Pose"
Cohesion: 0.14
Nodes (5): MarkerInput, Pose, Ultima pose si tiene menos de `timeout_s`; si no, `None`., MarkerInputTests, Traduccion de marker con receptor falso: sin conexion MQTT ni radio.

### Community 47 - "HighLevelFlight"
Cohesion: 0.15
Nodes (5): HighLevelFlight, Altura sobre el origen del preflight, o `None` sin pose., Convierte la intención de velocidad en un paso `go_to` acotado., Un paso de seguimiento del marker 65 como `follow_move` validado., Un dron de la cruz visto como el backend de un controlador por cámara.

### Community 48 - "dinamicos.py"
Cohesion: 0.12
Nodes (17): Segmentador cierra relativo al pico, Dataset del vocabulario (54 tomas por persona), Gestos dinamicos por DTW (aplausos y secuencias), Deteccion, rapidez_munecas(), rasgos_de_secuencia(), Reconocedor de gestos dinamicos en vivo, por segmentacion y DTW. A diferencia…, `(N, D)` desde poses canonicalizadas `(T, K, 3)` normalizadas por torso.… (+9 more)

### Community 49 - "segment_length_stability"
Cohesion: 0.11
Nodes (18): Variacion de longitud de huesos como metrica sin verdad de terreno, Filtrado temporal (One Euro, longitud de huesos, rechazo de saltos), HUESOS / pares_de_huesos(), EstabilidadSegmentos, ndarray, Medidas de calidad de una reconstrucción 3D, sin verdad de terreno. El problema…, Estabilidad de las longitudes a lo largo de una secuencia. Args: secuencia:…, Longitud de cada segmento en un instante. Args: puntos3d: `(K, 3)`. Los… (+10 more)

### Community 50 - "ChessboardSpec"
Cohesion: 0.12
Nodes (14): ChessboardSpec, Tablero de ajedrez para calibración. Args: cols: esquinas interiores a lo ancho…, Coordenadas 3D de las esquinas en el marco del tablero, en metros. El tablero…, cargar_puntos(), _coherencia(), _errores_por_vista(), guardar_puntos(), ndarray (+6 more)

### Community 51 - "test_calibration.py"
Cohesion: 0.11
Nodes (33): calibrate(), diagnosticar(), Ajusta los intrínsecos a partir de las esquinas detectadas. Args:…, Explica POR QUÉ una calibración salió como salió. Un RMS alto no dice qué hacer…, intrinsecos(), K_real(), fixture, ndarray (+25 more)

### Community 52 - "app.js"
Cohesion: 0.18
Nodes (19): action(), command(), config(), directions, drawTrajectory(), field(), fillConfig(), fmt() (+11 more)

### Community 53 - "comparar_2d_3d.py"
Cohesion: 0.16
Nodes (19): entre_personas(), evaluar(), main(), por_sujeto(), ndarray, rasgos_2d(), rasgos_3d(), Compara 3D contra 2D sobre las tomas grabadas. Sin camara y sin dron. Responde… (+11 more)

### Community 54 - "extrinsics.py"
Cohesion: 0.12
Nodes (15): analizar_coherencia(), Coherencia, ParesIncoherentes, pose_relativa_de_un_par(), _poses_tablero(), RuntimeError, Calibración extrínseca entre dos cámaras (estéreo). Da la posición y…, Los pares no describen una sola geometría: una cámara se movió. (+7 more)

### Community 55 - "HandGestureDetector"
Cohesion: 0.18
Nodes (8): HandGestureDetector, Detector de gestos de mano basado en MediaPipe Hands. Vocabulario implementado:…, Escala aproximada de la mano. Se usa la distancia muñeca -> MCP del dedo medio., Determina dedos extendidos usando distancias desde la muñeca. Esto es más…, Pulgar extendido: - punta más lejos de la muñeca que la articulación IP/MCP - y…, Estima si la mano apunta hacia arriba o hacia abajo. Se usa el promedio de las…, Confirma DESPEGAR y ATERRIZAR solo si se sostienen durante cierto tiempo. Esto…, Suavizado por mayoría para evitar parpadeos por detecciones aisladas.

### Community 56 - "demo_pose3d.py"
Cohesion: 0.17
Nodes (16): main(), panel_3d(), panel_datos(), panel_pipeline(), parse_args(), Namespace, ndarray, Demostración en vivo del pipeline de pose 3D, con una sola cámara. Pensada para… (+8 more)

### Community 57 - "test_grafica_comandos.py"
Cohesion: 0.21
Nodes (7): muestras(), Gráfica de tiempo contra comandos: que cuente la verdad de la sesión. Sin…, `secuencia`: lista de `(comando, confirmado)`, una por frame., test_confirmado_y_sin_confirmar_no_se_mezclan(), test_el_tiempo_por_comando_suma_sus_tramos(), test_los_frames_consecutivos_se_funden_en_un_tramo(), test_una_sola_muestra_dura_un_frame()

### Community 58 - "diagnose_camera.py"
Cohesion: 0.19
Nodes (16): escribir_informe(), main(), medir_frame_rate(), medir_latencia(), medir_pose(), parse_args(), Namespace, Path (+8 more)

### Community 59 - "Landmarks2D"
Cohesion: 0.07
Nodes (24): visibility como peso del DLT, presence aparte, ModeloNoEncontrado, _o_cero(), FileNotFoundError, ndarray, Path, Estimación de landmarks 2D con MediaPipe Pose (Tasks API). Una instancia por…, Devuelve los landmarks de un frame, o `None` si no hay persona. Args:… (+16 more)

### Community 60 - "load_config"
Cohesion: 0.14
Nodes (24): load_config(), Carga y valida la configuración de cámaras., build_rtsp_url(), Devuelve la URL RTSP para una cámara. Args: model: clave de RTSP_PATHS, p. ej.…, _escribir_config(), _fourcc(), fixture, Path (+16 more)

### Community 61 - "SimulatedBackend"
Cohesion: 0.12
Nodes (8): --dry-run: SimulatedBackend, validacion sin radio ni mocap, grafica_comandos.py (grafica tiempo vs comandos), Any, Backend determinista para verificar la interfaz sin radios ni motores., SimulatedBackend, Operacion, resultados y seguridad (docs/agents/operations.md), Fundir SimulatedBackend y HardwareBackend, Dry-run (simulación sin hardware)

### Community 62 - "hand_tracker.py"
Cohesion: 0.40
Nodes (3): config.py mezcla tres subsistemas (deuda tecnica), Actualizacion: vocabulario final de gestos de mano, requirements.txt de external/gesture_detection

### Community 63 - "DroneUnit"
Cohesion: 0.17
Nodes (6): DroneUnit, Crazyflie, Prepara el EKF para posición externa con el commander high-level activo., Promedia una ventana de MoCap inmovil para reducir el salto inicial., Describe el ultimo estado recibido sin consultar ni configurar hardware., Estado y recepción MoCap de un Crazyflie.

### Community 64 - "Handler"
Cohesion: 0.39
Nodes (3): BaseHTTPRequestHandler, finite_json(), Handler

### Community 65 - "gui_pdf_capture.py"
Cohesion: 0.21
Nodes (10): auto_save_gui_pdf(), install_gui_pdf_capture(), _physical_window_bbox(), Any, Path, Captura reutilizable de ventanas Tkinter en PDF., Obtiene el rectángulo físico de Windows, incluyendo escala DPI., Añade botón, Ctrl+P y método ``save_gui_pdf`` a una ventana Tk. (+2 more)

### Community 66 - "test_camera_flight_safety.py"
Cohesion: 0.31
Nodes (12): flowdeck_controller(), Backend Flow deck del Dron 1 con techo de altura y watchdog de vision., build_served(), FakeCf, Protecciones del backend Flow deck que usa el control por camara. Sin radio,…, Controlador listo, con su hilo atendiendo la cola sobre un cf falso., takeoff_and_wait(), test_despegue_no_bloquea() (+4 more)

### Community 67 - "DualStepKeysMixin"
Cohesion: 0.23
Nodes (7): disable_button_keyboard_focus(), DualStepKeysMixin, normalize_key(), Reserva Espacio para el dron, no para los botones de Tkinter., Un paso por pulsación. El panel implementa `_key_step` y `_keys_enabled`., Event, Misc

### Community 68 - "construir_plantillas.py"
Cohesion: 0.08
Nodes (51): main(), medir_umbral(), Construye el banco de plantillas dinamicas desde las tomas grabadas. Uso, desde…, Deja fuera a cada persona y separa las distancias de acierto y de fallo. El…, formato_matriz(), formato_metricas(), guardar_csv(), loso() (+43 more)

### Community 69 - "Anclaje al marco Robotat con blanco rastreado por el MoCap"
Cohesion: 0.05
Nodes (54): AGENTS.md — contrato para agentes de mapeo3d, Distincion: OptiTrack/MoCap vs camaras IP, Pipeline capture → pose → triangulation → io, Prohibicion de comandos PTZ, guardar_frame(), main(), parse_args(), Namespace (+46 more)

### Community 70 - "EstimadorDeEscala"
Cohesion: 0.13
Nodes (8): Ibanez et al. (normalizacion corporal antes de clasificar), Escala por largo de torso, no por ancho de hombros, EstimadorDeEscala, MarcoCorporal, Lleva puntos del marco de la cámara al marco del cuerpo., Escala corporal en vivo: mediana acumulada con calentamiento. En una sesión…, Sistema de referencia anclado al cuerpo, en el instante de un frame., Cuán bien determinado está el eje lateral, en `[0, ~0.6]`. Es el ancho de…

### Community 71 - "Pipeline de gestos por vision: diseno (docs/agents/gesture_pipeline.md)"
Cohesion: 0.12
Nodes (25): Separacion canal continuo (navegacion) / canal de eventos (comandos de estado), Dos sistemas de camaras separados: MoCap (dron) vs camaras IP (operador), Baseline 1: MediaPipe + DTW, Baseline 2: MediaPipe + HMM, Leave-One-Subject-Out (LOSO) / validacion estricta por sujeto, Modelo posterior: LSTM/GRU sobre landmarks normalizados, Fusion multicamara de decisiones (no reconstruccion 3D), Normalizacion de landmarks: centrado + escala corporal (+17 more)

### Community 72 - "test_highlevel_flight.py"
Cohesion: 0.11
Nodes (16): FakeFollower, pose(), fixture, MonkeyPatch, El controlador corporal sobre el backend high-level, con el backend simulado.…, Doble de CameraMarkerFollower: un marker fijo 2 cm delante del dron., Maniobras instantaneas y sin periodo entre pasos, como en el runner original., Un HighLevelFlight simulado ya conectado (en tierra) y su bitacora. (+8 more)

### Community 73 - "BancoDinamico"
Cohesion: 0.16
Nodes (8): BancoDinamico, ndarray, Path, Plantillas y umbral de aceptacion, medidos sobre material real., Gestos que el banco puede emitir. `GESTO_RECHAZO` no es uno., Umbral que se le exige a `gesto`: el suyo si lo tiene, si no el global., `(gesto, distancia, margen, distancias por gesto)`. `gesto` es `None` si la…, test_el_banco_sobrevive_al_disco()

### Community 74 - "flowdeck_dual_backend.py"
Cohesion: 0.29
Nodes (5): FlowDroneConfig, Backend Flow deck: un hilo por Crazyflie, para uno o dos drones. Lo usan el…, StateCallback, Deadman (Flow Deck: sin órdenes, se detiene y aterriza), MotionCommander (vuelo por velocidad)

### Community 75 - "capturar_en_vivo"
Cohesion: 0.21
Nodes (15): capturar_en_vivo(), cargar_de_carpeta(), _es_vista_nueva(), main(), parse_args(), Namespace, ndarray, Path (+7 more)

### Community 76 - "mapeo3d/pose/__init__.py"
Cohesion: 0.20
Nodes (16): a_escena(), _color_de(), dibujar_esqueleto_2d(), dibujar_esqueleto_3d(), dibujar_rejilla(), proyectar(), ndarray, Dibujado de esqueletos: overlay 2D y vista 3D en perspectiva. Es presentación,… (+8 more)

### Community 77 - "server.py"
Cohesion: 0.20
Nodes (6): HttpTests, Integracion HTTP y sesiones: todo simulado, sin radios, MQTT ni camara., ThreadingHTTPServer, main(), PanelServer, Panel HTTP de experimentos. La logica de vuelo pertenece a controllers/.

### Community 78 - "GraficaDeComandos"
Cohesion: 0.22
Nodes (6): GraficaDeComandos, Path, Acumula `(t, comando)` durante la sesión y guarda la figura al cerrar. Args:…, Una muestra por frame: qué comando se atendió y en qué estado., Marca vertical con etiqueta: emergencias, aterrizajes forzados., Escribe PNG y PDF. Devuelve la ruta del PNG, o `None` si no hubo nada que…

### Community 79 - "MarkerFollowTests"
Cohesion: 0.22
Nodes (5): Convierte una velocidad del marco Robotat al marco del Crazyflie., world_to_body(), MarkerFollowTests, pose(), Seguimiento relativo del marker, sin MQTT ni drones.

### Community 80 - "MocapReceiver"
Cohesion: 0.22
Nodes (5): MocapReceiver, Suscriptor MQTT seguro para una sola pose de ROBOTAT., main(), OrientationChecker, Comprobador visual del marker ROBOTAT. No conecta ni arma el dron.

### Community 81 - "Panel web UVG Drone Lab (index.html)"
Cohesion: 0.21
Nodes (13): Marker joystick: rigid body 64 en mocap/all, marker_input.py (marker 64 como joystick), Criterio de reutilización real en shared/, shared/robotat.py (broker MQTT y tópicos), paho-mqtt (MQTT / MoCap), Control por gestos de manos en el panel web, Joystick con marker en el panel web, Vista de cámara con manos anotadas (#camera-feed) (+5 more)

### Community 84 - "hand_gesture_detector.py"
Cohesion: 0.26
Nodes (6): HandGestureLogger, main(), put_hand_panel(), calculate_fps(), distance_2d(), Gestos de manos en 2D (nueve comandos)

### Community 85 - "PoseDetector"
Cohesion: 0.18
Nodes (4): PoseDetector, Adaptador pequeño de MediaPipe Pose para video en tiempo real., Convierte frames BGR en landmarks sin aplicar clasificación., Devuelve `(landmarks, world_landmarks)`, o `(None, None)`. `pose_landmarks`…

### Community 86 - "control_camara_dron1.py (controlador único por cámara)"
Cohesion: 0.27
Nodes (12): Protocolo de seguimiento del marker Robotat 65, marker_follow.py (seguimiento del marker 65), Categorías de controladores, --backend flowdeck (FlowDroneController de flowdeck_dual_backend.py), control_camara_dron1.py (controlador único por cámara), CSV por frame y gráfica tiempo vs comandos por sesión, grafica_comandos.py (GraficaDeComandos), El rumbo (--rumbo) no es opcional (+4 more)

### Community 87 - "Oscilación de los drones con el backend de mocap"
Cohesion: 0.31
Nodes (13): highlevel_delta, T-003 Extpos a 60 Hz y yaw al EKF, T-004 Go_to sin solapamiento y métrica de oscilación, Bitácora 2026-09-08, Hipótesis descartadas con evidencia, Extpos limitado a 20 Hz, locSrv.extPosStdDev por defecto, Go_to solapados en el seguimiento del marker (+5 more)

### Community 88 - "flowdeck_feedback.py"
Cohesion: 0.18
Nodes (12): Exclusión de flujo óptico y ToF en Robotat, Seleccion de mediciones del Flow Deck; sin dependencia de UI o de radios., Espera respuesta del firmware; no confunde set_value con confirmacion., _set_confirmed(), shared/radios.py (select_uri, resolve_dual_uris, resolve_serial_uris), DroneUnit (drone_unit.py), Diagnóstico de fallo de alineación EKF–MoCap, Preflight sin motores (+4 more)

### Community 89 - "datetime"
Cohesion: 0.21
Nodes (8): Base de los registros CSV de sesión: archivo por corrida, reloj y análisis.…, mqtt_timestamp_is_older(), parse_mqtt_timestamp(), Pose, Estado de un Crazyflie sobre el Robotat: pose MQTT, extpos, telemetría EKF y…, Convierte timestamps Robotat ISO-8601 o Unix a UTC., Indica un retroceso real; timestamps repetidos siguen siendo válidos., datetime

### Community 90 - "Toma"
Cohesion: 0.18
Nodes (7): canonicalizar(), `(poses, tiempos)` en el marco del cuerpo, normalizado por torso., ventana(), _limpio(), Un nombre utilizable como parte de un archivo., Una repeticion de un gesto., Toma

### Community 91 - "calibrate_stereo.py"
Cohesion: 0.29
Nodes (11): cargar_intrinsecos(), cargar_pares(), _es_par_nuevo(), guardar_pares(), main(), parse_args(), Namespace, Path (+3 more)

### Community 92 - "check_connection.py"
Cohesion: 0.23
Nodes (11): _credenciales(), informar(), main(), modo_scan(), parse_args(), Namespace, Diagnostica por qué no conecta una cámara IP. `check_stream.py` dice «no llegó…, escanear() (+3 more)

### Community 93 - "control_dos_drones_cruz_camara_multiprocessing.py"
Cohesion: 0.09
Nodes (30): ArgumentParser, Lanzador del control Cruz multiproceso de dos drones por cámara., main(), Panel de botones para un solo Crazyflie: la interfaz de la cruz en modo de un…, main(), parse_args(), Namespace, r"""Interfaz Python por botones para comparar control high-level en dos drones.… (+22 more)

### Community 94 - "angle_delta_deg"
Cohesion: 0.40
Nodes (4): angle_delta_deg(), Diferencia angular en [-180, 180], segura al cruzar ±180°., Zona muerta amplia y rampa suave desde 12° hasta 28°., tilt_to_speed()

### Community 95 - "HandTracker"
Cohesion: 0.13
Nodes (7): HandsSource, Fuente de manos para sesiones duales; la coordinacion recibe gestos filtrados., HandTracker, Encapsula MediaPipe Hands. Devuelve: - frame anotado - landmarks de la primera…, Devuelve todas las manos detectadas, conservando su handedness., Devuelve landmarks, lateralidad y confianza de todas las manos., Compatibilidad: devuelve solo la primera mano como antes.

### Community 96 - "Backend high-level de la cruz (cruz_highlevel_backend.py)"
Cohesion: 0.29
Nodes (10): shared/crazyflie_link.py (configure_estimator, reset_kalman, arm_if_supported, stop_motors), highlevel_flight.py (adaptador de un dron sobre el backend de la cruz), Backend high-level de la cruz (cruz_highlevel_backend.py), Resultados de sesión dos_drones (CSV y figuras PDF), Watchdog de seguridad del backend de la cruz, cflib (Crazyflie / Bitcraze), Por qué la coordinación del panel vive en two_drones/, controllers/two_drones/experiment_session.py (coordinación del panel) (+2 more)

### Community 97 - "SessionRecording"
Cohesion: 0.22
Nodes (4): Registro y graficas de sesiones; mide tiempos del software, no de la radio., SessionRecording, Significado de las mediciones del CSV del panel, Exportación de gráficas y descargas (#export, #downloads)

### Community 98 - "Reconocedor cuerpo 3D (MediaPipe Pose)"
Cohesion: 0.25
Nodes (9): El espejo va después de la inferencia, Contrato GestureEvent (external/gesture_detection/contracts.py), external/gesture_detection/probar_gestos_3d.py (práctica guiada sin dron), Reconocedor cuerpo 3D (MediaPipe Pose), Reconocedor manos 2D (MediaPipe Hands), Objetivo: anillo de seis cámaras IP alrededor del operador, STOP sostenido como parada de emergencia, Vocabulario 3D de gestos corporales (9 gestos) (+1 more)

### Community 99 - "Estado del reconocedor DTW: validación y qué falta"
Cohesion: 0.17
Nodes (10): 3D contra 2D, Enlaces, Estado del reconocedor DTW: validación y qué falta, La cifra, Lo que se probó y no funcionó, Matriz de confusión, vocabulario de cinco gestos, Para el documento, Qué cambió en el código (+2 more)

### Community 100 - "sin_hardware"
Cohesion: 0.50
Nodes (4): fixture, MonkeyPatch, Sustituye MotionCommander y el armado por dobles durante cada prueba., sin_hardware()

### Community 101 - "test_grabar_vocabulario.py"
Cohesion: 0.22
Nodes (3): Guion del vocabulario final. Sin camara y sin MediaPipe. Verifica lo que cuesta…, Girarse es lo lento: un angulo no debe volver a aparecer despues., test_agrupado_por_angulo()

### Community 102 - "FollowGestureTests"
Cohesion: 0.31
Nodes (3): DummyLandmarks, FollowGestureTests, Clasificación de los dos gestos de seguimiento, sin cámara.

### Community 104 - "DLT de N vistas"
Cohesion: 0.29
Nodes (8): Herramientas externas: Caliscope, aniposelib, Pose2Sim, Homografia del suelo: dominio de validez, Rectificar puntos antes de triangular (undistort_points), Nakano et al. (2020) Evaluation of 3D Markerless Motion Capture Accuracy Using OpenPose, DLT de N vistas, Referencias: TemugeB/bodypose3d, Pose2Sim, aniposelib, Tres capas de robustez sobre el DLT, Verificacion metrica: triangular el tablero y medir la casilla

### Community 105 - "normalize.py"
Cohesion: 0.10
Nodes (21): Cuantas tomas hay de cada gesto, persona y orientacion., resumen(), BodyFrame, landmarks_to_array(), normalize(), ndarray, Marco corporal: la pose vista desde el cuerpo y no desde la cámara.…, Hacia donde mira el cuerpo respecto de la camara, en grados.… (+13 more)

### Community 106 - "StreamStats"
Cohesion: 0.25
Nodes (4): Estadísticas de una cámara durante una sesión. No son un extra de depuración:…, fps medios realmente recibidos, no los declarados por la cámara., StreamStats, _UltimoFrame

### Community 107 - "marker_mocap.py"
Cohesion: 0.38
Nodes (6): _component(), parse_robotat_pose(), quaternion_to_euler_deg(), Recepción y conversión de poses ROBOTAT publicadas por MQTT., Convierte el cuaternión ROS/ROBOTAT (x, y, z, w) a roll, pitch, yaw., Acepta los formatos ``mocap/all`` y ``mocap/allv2`` de ROBOTAT.

### Community 109 - "Redes Neuronales Profundas: Detalles de Entrenamiento"
Cohesion: 0.20
Nodes (10): 11. El "Zoológico" de Arquitecturas Neuronales, 13. Resumen Sintético de Conceptos Clave, 14. Bibliografía, 5. Partición de Datos: Train, Validation y Test Split, 6. Diagnóstico del Modelo: El Dilema Sesgo-Varianza (*Bias-Variance Tradeoff*), 9.1. SGD con Momentum, 9.2. Adam (*Adaptive Moment Estimation*), 9. Optimizadores Modernos (+2 more)

### Community 111 - "triangulation/__init__.py"
Cohesion: 0.16
Nodes (18): camera_center(), Centro óptico de una cámara a partir de su matriz `(3, 4)`., Triangulación: de landmarks 2D de N vistas a puntos 3D. Este subpaquete no sabe…, angulo_util_deg(), Punto3D, ndarray, Triangulación robusta de N vistas: ponderación, rechazo y aceptación. El DLT…, Triangula un punto descartando las vistas que no encajan. Args: proyecciones:… (+10 more)

### Community 113 - "--dry-run: backend high-level simulado sin radio ni mocap"
Cohesion: 0.33
Nodes (6): Seguridad de hardware, --backend mocap (posición absoluta, geofence, dry-run), control_dos_drones_camara.py (dos manos, dos drones), --dry-run: backend high-level simulado sin radio ni mocap, Servidor local sin TLS: token de control y comprobación de origen, web/server.py (HTTP y estáticos del panel)

### Community 116 - "_P"
Cohesion: 0.33
Nodes (6): _P(), par_estereo(), fixture, ndarray, Matriz de proyección de una cámara con rotación R y centro C., Dos cámaras separadas 1.5 m, la segunda girada 30° hacia el centro.

### Community 117 - "Opciones para bajar líneas de código"
Cohesion: 0.33
Nodes (7): Andamiaje multivista sin app consumidora, Código sin consumidor en two_drones, Decisiones pendientes del autor sobre borrados, Opciones para bajar líneas de código, Tests a pytest con conftest raíz, Utilidades compartidas en gesture_detection, Utilidades compartidas en mapeo3d

### Community 118 - "Comandos para probar los programas"
Cohesion: 0.13
Nodes (15): AGENTS.md (contrato raiz del repositorio), controllers/joystick/README.md, controllers/two_drones/README_CONTROL_CRUZ_PYTHON.md, Mapa de documentacion para agentes (docs/agents/README.md), 1. Preparar el entorno, 2. Validación completa sin hardware, 3. Comprobar lanzadores y argumentos, 4. Probar interfaces en simulación (+7 more)

### Community 119 - "discover_marker_id.py"
Cohesion: 0.40
Nodes (3): contains_id(), Descubre el tópico MQTT que corresponde a una ID de rigid body ROBOTAT. No abre…, Busca la ID tanto como número como texto dentro del JSON recibido.

### Community 121 - "Medida"
Cohesion: 0.33
Nodes (3): Medida, Una condicion del vocabulario, con su valor actual y su umbral., Cuanto sobra (positivo) o cuanto falta (negativo).

### Community 122 - "7.1. Para Tareas de Regresión"
Cohesion: 0.33
Nodes (6): 7.1. Para Tareas de Regresión, 7.2. Para Tareas de Clasificación, 7. Funciones de Pérdida Comunes (*Loss Functions*), Entropía Cruzada Binaria (*Binary Cross-Entropy* / *Log Loss*), Error Absoluto Medio (MAE / Pérdida $\mathcal{L}_1$), Error Cuadrático Medio (MSE / Pérdida $\mathcal{L}_2$)

### Community 134 - "por_estilo"
Cohesion: 0.40
Nodes (5): por_estilo(), ndarray, La diferencia entre medir repetibilidad y medir generalizacion. Sobre un…, Distancias de un dataset donde pesa mas el estilo de cada persona que el gesto:…, test_loso_no_se_apoya_en_la_propia_persona()

### Community 135 - "1. Motivación: ¿Por qué Deep Learning?"
Cohesion: 0.40
Nodes (5): 1.1. Del Teorema de Aproximación Universal a las Redes Profundas, 1.2. Deep Learning vs. Machine Learning Tradicional, 1.3. Escalamiento: Rendimiento vs. Volumen de Datos, 1.4. Criterios de Selección: ¿Cuándo usar Deep Learning?, 1. Motivación: ¿Por qué Deep Learning?

### Community 136 - "2.2. Capacidad de Partición: Redes Superficiales vs. Redes Profundas"
Cohesion: 0.40
Nodes (5): 2.1. Funciones Lineales a Trozos con Activación ReLU, 2.2. Capacidad de Partición: Redes Superficiales vs. Redes Profundas, 2. Fundamentos de Expresividad en Redes Profundas, Red Profunda ($K$ capas ocultas, $D$ neuronas por capa en 1D), Red Superficial (1 capa oculta, $D$ neuronas en 1D)

### Community 137 - "8. Técnicas de Regularización"
Cohesion: 0.40
Nodes (5): 8.1. Formulación Matemática con Multiplicadores de Lagrange, 8.2. Regularización $\mathcal{L}_2$ (*Weight Decay* / Norma de Frobenius), 8.3. Regularización $\mathcal{L}_1$ y el Fenómeno de Esparcidad (*Sparsity*), 8.4. Geometría de las Normas ($\ell_p$), 8. Técnicas de Regularización

### Community 139 - "12. Implementación Práctica de un Perceptrón en Frameworks Modernos"
Cohesion: 0.50
Nodes (4): 12.1. MATLAB, 12.2. TensorFlow + Keras (Python), 12.3. PyTorch (Python), 12. Implementación Práctica de un Perceptrón en Frameworks Modernos

### Community 140 - "3. Dinámica de Entrenamiento y Optimización"
Cohesion: 0.50
Nodes (4): 3.1. Mini-Batches y Épocas (*Epochs*), 3.2. Descenso de Gradiente Estocástico por Mini-Batches (*Mini-Batch SGD*), 3. Dinámica de Entrenamiento y Optimización, Comparativa entre regímenes de gradiente:

### Community 141 - "4. Métricas de Evaluación y Matriz de Confusión"
Cohesion: 0.50
Nodes (4): 4.1. Métricas de Clasificación, 4.2. La Matriz de Confusión, 4.3. Métricas de Regresión, 4. Métricas de Evaluación y Matriz de Confusión

### Community 142 - "10. Heurísticas Fundamentales de Entrenamiento"
Cohesion: 0.67
Nodes (3): 10.1. Parada Temprana (*Early Stopping*), 10.2. Dropout, 10. Heurísticas Fundamentales de Entrenamiento

## Ambiguous Edges - Review These
- `body_3d_rules.py` → `rasgos_de_sesion()`  [AMBIGUOUS]
  external/mapeo3d/docs/pose.md · relation: shares_data_with
- `Robotat: captura de movimiento por MQTT + extpos` → `Contrato de entrega de pose 3D (módulo compartido, archivo o MQTT)`  [AMBIGUOUS]
  Tesis/10-Tareas/T-002 Contrato de datos mapeo3d a controladores.md · relation: conceptually_related_to

## Knowledge Gaps
- **89 isolated node(s):** `DummyLandmarks`, `form`, `names`, `directions`, `gestures` (+84 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 1014 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **20 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `body_3d_rules.py` and `rasgos_de_sesion()`?**
  _Edge tagged AMBIGUOUS (relation: shares_data_with) - confidence is low._
- **What is the exact relationship between `Robotat: captura de movimiento por MQTT + extpos` and `Contrato de entrega de pose 3D (módulo compartido, archivo o MQTT)`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **Why does `Pipeline de gestos por vision: diseno (docs/agents/gesture_pipeline.md)` connect `Pipeline de gestos por vision: diseno (docs/agents/gesture_pipeline.md)` to `body_3d_rules.py`, `Gesture`, `Estado del reconocedor DTW: validación y qué falta`, `AGENTS.md: contrato canónico para agentes`, `VelocityIntent`, `Arquitectura actual (docs/agents/architecture.md)`, `Body3DRecognizer`, `hand_gesture_detector.py`, `PoseDetector`, `Comandos para probar los programas`, `probar_gestos_3d.py`, `hand_tracker.py`?**
  _High betweenness centrality (0.069) - this node is a cross-community bridge._
- **Why does `Gesture` connect `Gesture` to `body_3d_rules.py`, `Pipeline de gestos por vision: diseno (docs/agents/gesture_pipeline.md)`, `test_body_3d_rules.py`, `Practica`, `Body3DRecognizer`, `probar_vocabulario.py`, `probar_gestos_3d.py`, `control_camara_dron1.py`?**
  _High betweenness centrality (0.058) - this node is a cross-community bridge._
- **Why does `Refactorizacion de septiembre de 2026 (docs/agents/refactor_2026-09.md)` connect `Arquitectura actual (docs/agents/architecture.md)` to `body_3d_rules.py`, `AGENTS.md: contrato canónico para agentes`, `Command`, `flowdeck_flight.py`, `Comandos para probar los programas`, `datetime`, `FlowDroneController`, `probar_gestos_3d.py`, `DroneUnit`?**
  _High betweenness centrality (0.056) - this node is a cross-community bridge._
- **Are the 16 inferred relationships involving `Command` (e.g. with `HighLevelFlight` and `HighlevelCameraMarkerRuntime`) actually correct?**
  _`Command` has 16 INFERRED edges - model-reasoned connections that need verification._
- **Are the 34 inferred relationships involving `Gesture` (e.g. with `_aplicar()` and `bucle()`) actually correct?**
  _`Gesture` has 34 INFERRED edges - model-reasoned connections that need verification._