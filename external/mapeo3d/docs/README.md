# Mapa de documentación

Documentación técnica del repositorio **mapeo tridimensional con cámaras**. Dirigida a agentes de IA y a personas que vayan a modificar el código. Para instalar y correr el proyecto, ver el [README de usuario](../README.md).

## Convención de estado

Cada sección de estos documentos lleva una marca:

| Marca | Significado |
|---|---|
| `[implementado]` | El código existe y hace lo descrito |
| `[parcial]` | Existe algo, pero no todo lo descrito |
| `[planeado]` | Diseño acordado, sin código todavía |

**Un agente no debe importar ni referenciar un módulo marcado `[planeado]`.** Verificar siempre contra el árbol de archivos.

Al implementar algo, actualizar su marca en el mismo cambio.

## Documentos

| Documento | Qué cubre | Leerlo antes de |
|---|---|---|
| [architecture.md](architecture.md) | Capas, flujo de datos, contrato de salida hacia `tesis` | Crear cualquier módulo nuevo |
| [capture.md](capture.md) | Clientes RTSP, latencia, marcas de tiempo, sincronización | Tocar `src/mapeo3d/capture/` |
| [calibration.md](calibration.md) | Intrínsecos, extrínsecos, marco Robotat, integridad | Tocar `src/mapeo3d/calibration/` o calibrar en el laboratorio |
| [pose.md](pose.md) | Landmarks 2D, MediaPipe, costo con seis cámaras, qué gestos son posibles | Tocar `src/mapeo3d/pose/` o elegir vocabulario de gestos |
| [triangulation.md](triangulation.md) | DLT de N vistas, robustez, filtrado, validación numérica | Tocar `src/mapeo3d/triangulation/` |
| [hardware.md](hardware.md) | Cámaras, red, montaje, interferencias | Configurar cámaras o proponer montaje |
| [operations.md](operations.md) | Cómo correr cada app, dónde caen los resultados, cómo validar | Ejecutar o añadir una app |

## Orden de lectura recomendado

Para un agente que entra por primera vez:

1. [`AGENTS.md`](../AGENTS.md) — el contrato y los límites.
2. [architecture.md](architecture.md) — qué produce el sistema y para quién.
3. El documento de la etapa que se va a tocar.

No hace falta leerlos todos. Sí hace falta leer `AGENTS.md` y `architecture.md`.

## Estado global del repositorio

`[parcial]`.

| Etapa | Estado |
|---|---|
| `capture/` | `[implementado]` — lectura, descarte, reconexión, estadísticas, configuración y sincronización multicámara con compensación de sesgo |
| `calibration/` | `[parcial]` — intrínsecos, tablero, FOV, extrínsecos estéreo y detección de cámara movida durante la calibración implementados; marco Robotat e integridad ArUco entre sesiones pendientes |
| `pose/` | `[parcial]` — `Landmarks2D`, esqueleto, huesos, `PoseDetector` sobre la Tasks API, marco corporal, eventos temporales, calidad y dibujado implementados; selección de vista entre cámaras pendiente |
| `triangulation/` | `[parcial]` — DLT de N vistas, reproyección, ángulo entre rayos, las tres capas de robustez y la estabilidad de longitud de segmentos implementadas; filtrado temporal pendiente |
| `io/` | `[planeado]` |

Apps existentes (`[implementado]`): `apps/make_chessboard.py`, `apps/check_connection.py`, `apps/check_stream.py`, `apps/calibrate_intrinsics.py`, `apps/calibrate_stereo.py`, `apps/check_pose3d.py`, `apps/demo_pose3d.py`, `apps/diagnose_camera.py`.

Pruebas: `tests/test_capture.py`, `tests/test_calibration.py`, `tests/test_extrinsics.py`, `tests/test_triangulation.py`, `tests/test_robust.py`, `tests/test_sync.py`, `tests/test_diagnostico.py`, `tests/test_probe.py`, `tests/test_draw.py`, `tests/test_canonical.py`, `tests/test_eventos.py` (módulos) y `tests/test_apps.py` (arranque de las apps y ruta de captura completa). Todas corren sin cámaras, sin pantalla y sin MediaPipe instalado.

El siguiente entregable es el **anclaje de extrínsecos al marco del Robotat contra un blanco rastreado por el MoCap**. Con seis cámaras en anillo el estéreo por tablero no escala: dos cámaras opuestas nunca ven la misma cara del tablero, y encadenar pares acumula error sin dar un marco común. Un blanco que el MoCap sitúa en 3D da a cada cámara su pose absoluta directamente, sin encadenar con ninguna otra. **El Crazyflie por sí solo no sirve**: sus marcadores son retrorreflectivos y no se ven en luz visible. Ver [calibration.md](calibration.md).
