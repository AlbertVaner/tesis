---
estado: revisar
agente: claude
repo: tesis
prioridad: alta
creada: 2026-09-12
---
## Objetivo
Que `controllers/single_drone/camera/control_camara_dron1.py` vuele un Crazyflie con el vocabulario completo: gestos dinámicos por DTW (senalero, aplaudir, ven_aca, arco, circulo) y estáticos por reglas (ARRIBA, ABAJO, ADELANTE, ATRAS, IZQUIERDA, DERECHA), con los dos modos excluyentes, el aplauso como conmutador y la X sobre la cabeza como paro. Primero sin cámara, después en `--dry-run`, y por último en vuelo autorizado.

## Criterio de aceptación

### Paso 1: cablear, sin cámara ni hardware
- [x] La máquina de modos que hoy vive en `Simulador` (`external/gesture_detection/probar_vocabulario.py`) pasa a `external/gesture_detection/recognition/vocabulario.py` como lógica pura: sin `cv2`, sin dron, sin saber qué es un Crazyflie. Decide qué gesto vale en qué modo y emite acciones abstractas. `probar_vocabulario.py` la reutiliza y `tests/test_probar_vocabulario.py` sigue en verde.
- [x] `control_camara_dron1.py --reconocedor vocabulario` combina banco DTW (`models/plantillas_vocabulario.npz`), estáticos de `body_3d_rules` y regla de paro de `paro_estatico`, y traduce las acciones a `HighLevelFlight` o `FlowDroneController`:
  - senalero: despegue en el suelo, aterrizaje en el aire
  - aplaudir: cambia de modo y deja hover
  - ven_aca: seguimiento del marker 65 (`follow_marker` o velocidad relativa, como ya hace el gesto de mano)
  - estáticos: `set_velocity` sólo en modo estático y en el aire; sin dirección confirmada, hover
  - X sobre la cabeza 1 s: aterriza y bloquea todo hasta soltar; X sostenida 3 s: corte de motores
  - arco y circulo: hover y aviso en pantalla, sin implementación de vuelo todavía (paso 2)
- [x] Pruebas nuevas en `controllers/single_drone/camera/tests/` con un backend falso que recorren esa secuencia sin cámara. `python -m pytest -q` en verde desde la raíz. `python controllers\single_drone\camera\control_camara_dron1.py --help` funciona.

### Paso 2: medir y completar comportamientos
- [ ] Falsos disparos en reposo: una sesión de al menos 5 min de pie, hablando y caminando, con `probar_vocabulario.py --guardar-segmentos`. Comandos inventados por minuto, por gesto, anotados en `60-Analisis`. Si senalero se inventa más de una vez cada 5 min, hay que exigir confirmación (por ejemplo repetirlo) antes de despegar.
- [ ] ALEJARSE como pasos `move` en dirección contraria al marker 65, usando la posición que ya entrega `marker_follow`. ORBITAR se implementa en el backend o queda documentado como pendiente con la razón.

### Paso 3: volar
- [ ] `--reconocedor vocabulario --volar --dry-run` recorre la secuencia completa con `SimulatedBackend`, con CSV y gráfica en `results/{data,graphs}/control_camara_dron1/`.
- [ ] Vuelo real sólo con autorización explícita del humano, con la webcam o una cámara a 15 fps o más: senalero, aplaudir, X, estáticos y ven_aca. Sesión registrada y una línea en `20-Bitacora`.

## Contexto
- [Estado del reconocedor DTW](../60-Analisis/2026-09-08%20Estado%20del%20reconocedor%20DTW.md): 77.1 % de acierto dejando fuera al sujeto (`results/data/validacion_dtw/2026-09-09/`), rechazo con F1 0.56, aplaudir se lee 3 de cada 4 veces con su umbral propio. Si en vivo cuesta conmutar, subir sólo el umbral de aplaudir.
- `external/gesture_detection/README.md`, secciones "Gestos dinámicos" y "Probar el vocabulario completo": la máquina de modos y por qué los canales no conviven.
- `external/gesture_detection/probar_vocabulario.py`: `Simulador` y el orden de prioridad del bucle (seguimiento PTZ, paro, dinámico, estáticos).
- `controllers/single_drone/camera/control_camara_dron1.py`: `_aplicar`, `_seguir_marker`, el bucle y sus prioridades (STOP, marker, seguimiento, vocabulario).
- `controllers/single_drone/camera/highlevel_flight.py`: interfaz común de los dos backends.
- `external/gesture_detection/contracts.py`: la visión nunca produce m/s y `confirmed=False` no ejecuta.
- Regla 6 de `AGENTS.md`: la lógica que decide qué gesto vale cuándo es visión; convertirla en órdenes de vuelo es del controlador.
- Seguridad de hardware de `AGENTS.md`: nada de vuelo real sin autorización; `--dry-run` primero.
- Riesgo de cámara IP: con RTSP se midió un consumidor a 6.4 fps y el banco se validó a 30 y 15 fps. Para volar, webcam o 15 fps garantizados.

## Bitácora
- 2026-09-12 (claude): creada a partir de la conversación sobre si las pruebas con DTW alcanzan para volar. Arranca el paso 1.
- 2026-09-12 (claude): **paso 1 hecho.** Nuevo `external/gesture_detection/recognition/vocabulario.py` (`MaquinaDeModos`, `Decision`): la máquina no lleva `en_aire`, se lo dice quien decide, así un despegue rechazado por el backend no la desincroniza. `Simulador` del probador ahora la envuelve; sus 8 pruebas siguen igual. `control_camara_dron1.py --reconocedor vocabulario` (`ReconocedorVocabulario`, con `observar()` para la visión y `aplicar()` para la decisión, separados para probarlos sin cámara): senalero despega/aterriza, ven_aca sigue al marker 65 y lo suelta al cambiar de modo, aplaudir conmuta + hover, estáticos sólo en modo estático y en el aire, X 1 s aterriza y bloquea, X 3 s pide corte de motores, arco/circulo hover con aviso. `--banco`, `--paro`, `--confirmacion`; CSV con `modo` y `comportamiento`; la gráfica marca cada gesto dinámico ejecutado. Pruebas: `tests/test_vocabulario.py` (7) y `camera/tests/test_control_vocabulario.py` (10). Validado: `compileall` limpio, `python -m pytest -q` 533 en verde, `--help` del controlador, del wrapper y del probador. Sin cámara ni hardware. Quedan pasos 2 y 3: el 2 necesita una sesión en vivo del humano (falsos disparos en reposo) y el 3, autorización de vuelo. Pasa a `revisar` por eso.
- 2026-09-12 (claude): **preparación del paso 3.** El usuario confirmó que `probar_vocabulario.py --seguir` funciona con la cámara real y pidió probar con el Dron 1. El controlador ahora acepta `--rtsp` (lector en hilo de `video_source.py`) y `--seguir` con los mismos mandos PTZ del probador (`--zona-muerta`, `--zona-muerta-tilt`, `--centro-y`, `--velocidad-max`, `--sin-tilt`, `--ptz-dry-run`); sólo con `--reconocedor vocabulario`, porque el seguimiento necesita saber si hay un segmento abierto y los frames tomados girando se marcan como huecos. El PTZ se conecta antes que la radio. Dos pruebas más (`_seguir_camara`); 53 en la carpeta camera, `compileall` y `--help` limpios. Sin hardware: el `--dry-run` y el vuelo los corre el humano.
- 2026-09-12 (humano + claude): **paso 3, primer vuelo.** Dry-run OK. Vuelo real con mocap: el senalero despegó a 0.38 m, la cámara siguió al operador, CSV y gráfica en `results/`. A los 21 s el backend cortó por EKF-MoCap = 0.158 m. Oscilación de 0.4 Hz y 0.7 m pico a pico en hover puro, sin ninguna orden de la cámara: no es del controlador. Análisis en [60-Analisis](../60-Analisis/2026-09-12%20Oscilaci%C3%B3n%20en%20el%20primer%20vuelo%20por%20gestos.md): batería agotada (2.82 V en vuelo) y EKF 60–100 ms detrás del mocap; marco girado y huecos del mocap descartados con datos. Faltan aplaudir, estáticos y ven_aca en vuelo: repetir con batería ≥ 3.9 V.
- 2026-09-12 (humano + claude): vuelos 3 y 4. Con `--dron 2` (nuevo) el Dron 2 despegó por senalero, **aplaudir cambió a modo estático y ABAJO produjo un `go_to`**: primera vez que el vocabulario completo actúa sobre un dron real. Emergencia del backend a los 16 s por la misma oscilación de 0.4 Hz, que el Dron 2 con batería sana reproduce igual: no es del controlador ni de la batería. Queda ven_aca en vuelo. La oscilación se trata aparte (nota en 60-Analisis); mientras no baje, cada vuelo termina en emergencia antes de poder probar más gestos.
- 2026-09-18 (humano + claude): **paso 3, el vocabulario completo en vuelo, con uno y con dos drones**, sobre el núcleo Robotat y con la cámara IP colgada del techo siguiendo al operador. Sesiones en `results/data/control_camara_dron1/2026-09-18/` y `results/data/dron_robotat/2026-09-18/`; vídeo de la interfaz en `results/captures/control_camara_dron1/2026-09-18/sesion_180534.mp4`. Volaron por gestos: senalero (despegue y aterrizaje), aplaudir, los seis estáticos, `ven_aca` (hasta 59 s de seguimiento) y `circulo` (órbita). La X se rehízo: frena a 0.35 s, aterriza a 1 s, corta a 3 s, y ve la imagen aunque la cámara gire. Detalle del día en [la bitácora](../20-Bitacora/2026-09-18.md) y en los análisis [de los estáticos](../60-Analisis/2026-09-18%20Gestos%20estaticos%20con%20la%20camara%20IP%20en%20el%20techo.md) y [de los vuelos en formación](../60-Analisis/2026-09-18%20Primer%20vuelo%20de%20dos%20drones%20en%20formacion%20por%20gestos.md). **Dos cosas para que decida el humano, por eso no marco casillas:** (1) el criterio del paso 2 pide ALEJARSE para `arco`, y a petición del operador `arco` es ahora la **pirueta** de la demo de Bitcraze (espiral y subida por el eje); ORBITAR sí está implementado en el backend `robotat`. (2) El paso 3 pedía webcam o 15 fps garantizados: se voló con la cámara IP a 23-33 fps, y dos drones a la vez, que la tarea no contemplaba (decisión en `30-Decisiones/2026-09-18 Dos drones en formacion...`). Sigue sin hacerse la sesión de falsos disparos en reposo del paso 2; hoy hubo un `ven_aca` fantasma. Pendiente de validar en vuelo: pirueta, zona de exclusión del marker, geocerca común y repulsión.
