# Operación, resultados y validación

Estado: `[parcial]` — `make_chessboard.py`, `check_connection.py`, `check_stream.py`, `calibrate_intrinsics.py`, `calibrate_stereo.py`, `check_pose3d.py`, `demo_pose3d.py` y `diagnose_camera.py` existen; el resto está `[planeado]`.
Este documento define qué se va a construir y en qué orden.

## Aplicaciones previstas

Todas viven en `apps/`, componen módulos de `src/mapeo3d/` y no contienen algoritmos.

| App | Qué hace | Prioridad |
|---|---|---|
| `make_chessboard.py` `[implementado]` | Genera el tablero de calibración a escala exacta, con regla de verificación | **0 — hecha** |
| `check_connection.py` `[implementado]` | Diagnostica por qué no conecta una cámara: distingue puerto cerrado, credenciales mal y ruta RTSP mal | **0 — hecha** |
| `check_stream.py` `[implementado]` | Conecta con una cámara, la muestra, mide los fps reales frente a los esperados y guarda un frame con `--save-frame` | **0 — hecha** |
| `check_pose3d.py` `[implementado]` | Pose 3D monocular con una cámara; mide su calidad por constancia de longitud de huesos | **0 — hecha** |
| `demo_pose3d.py` `[implementado]` | Demostración en vivo del pipeline 3D con una cámara y vista que gira; para enseñar el sistema | **0 — hecha** |
| `diagnose_camera.py` `[implementado]` | Mide fps reales, latencia extremo a extremo, jitter de landmarks, encuadre y FOV | **0 — hecha** |
| `calibrate_intrinsics.py` `[implementado]` | Captura de tablero, `cv2.calibrateCamera` y **campo de visión real** por cámara | **0 — hecha** |
| `calibrate_stereo.py` `[implementado]` | Extrínsecos entre dos cámaras + verificación métrica triangulando el tablero | **0 — hecha** |
| `calibrate_extrinsics.py` | Correspondencias LED↔MoCap para anclar al marco del Robotat | 3 |
| `check_calibration.py` | Verifica el marcador ArUco de integridad; corre antes de cada sesión | 3 |
| `record_session.py` | Graba streams sincronizados a disco para trabajo offline | 4 |
| `live_pose3d.py` | Pipeline completo en vivo con visor 3D y publicación del contrato | 5 |

### `diagnose_camera.py`: por qué iba primera, y cómo se usa

Casi todo lo que dice [hardware.md](hardware.md) sobre encuadre, frame rate y latencia está **calculado, no medido**. Y la decisión de dónde fijar las cámaras es la única difícil de deshacer. Medir antes de fijar cuesta medio día; equivocarse cuesta desmontar seis cámaras.

Lo que reporta, en un solo informe:

- **fps realmente recibidos** frente a los configurados, con el jitter del intervalo entre frames.
- **Latencia extremo a extremo**, haciendo destellar la pantalla contra la cámara y buscando el escalón de brillo en el stream.
- **Jitter de landmarks** — cuánto se mueve cada articulación con el sujeto quieto.
- **Encuadre**: si el cuerpo completo cabe, y si cabe con los brazos en alto.
- **FOV real**, derivado de los intrínsecos. Sustituye a medirlo con un objeto de tamaño conocido: sale del propio ajuste y es más fiable.

Ese informe es a la vez criterio de montaje y material para el capítulo experimental.

`[implementado]`. Escribe el informe en `results/diagnostics/<AAAA-MM-DD>/`.

```powershell
# Completo, con el sujeto a 3 m
python apps/diagnose_camera.py --camera cam3 --distancia 3.0 --intrinsics results/calibration/2026-09-02

# Sólo frame rate y latencia, sin sujeto
python apps/diagnose_camera.py --camera cam3 --sin-pose
```

Notas de uso:

- La medida de **latencia** hace destellar una ventana en la pantalla: hay que
  **apuntar la cámara al monitor**. Se salta con `--sin-latencia`.
- La medida de **jitter** exige que el sujeto esté **quieto**: con el sujeto
  parado, todo lo que se mueve es error del estimador. Da 5 s para colocarse.
- El **FOV** sale de los intrínsecos, no de medir con cinta: pasar
  `--intrinsics` si ya están hechos.
- Una corrida por distancia (2, 3, 4 m), y luego se comparan los informes.
  `--nota` etiqueta cada uno.

**Cómo se interpreta el jitter.** Es el ruido de detección 2D en píxeles, y es
justo lo que se propaga a la triangulación: la simulación de
[calibration.md](calibration.md) usa 0.5 px como «ruido conservador». Si una
cámara da mucho más que eso con el sujeto quieto, el problema está antes de la
geometría. Con intrínsecos y distancia, el informe lo traduce a milímetros
sobre el sujeto, que es la cifra comparable con lo que un gesto tolera.

## Resultados

```
results/
├── calibration/<AAAA-MM-DD>/    intrínsecos, extrínsecos, proyección, report.md
├── data/<sesion>/               grabaciones, poses 3D, estadísticas de captura
├── graphs/<sesion>/             gráficas generadas
└── diagnostics/<AAAA-MM-DD>/    informes de diagnóstico de cámara
```

Nada de `results/` se versiona. Toda sesión guarda, junto a los datos:

- la calibración vigente que se usó (copia, no referencia);
- las estadísticas de captura (fps recibidos, reconexiones, frames descartados por sincronización);
- la configuración efectiva de cada cámara.

Sin eso, una sesión no es reproducible y no puede citarse en la tesis.

## Configuración

`config/cameras.example.yaml` es la plantilla versionada. La configuración real, **con credenciales**, va en un archivo local ignorado por git.

Las URLs RTSP llevan usuario y contraseña: nunca deben aparecer en logs, mensajes de error ni nombres de archivo. Al mostrar una URL, enmascarar las credenciales.

## Validación

Tres niveles, con costos muy distintos. Un cambio se valida al nivel que le corresponde, no al más barato.

### Nivel 1 — Sin cámaras, en CI

```powershell
python -m compileall src apps
python -m pytest tests -q
```

Cubre tres cosas:

1. **Los módulos**, con datos sintéticos: punto 3D conocido → proyecciones con ruido → reconstrucción dentro de tolerancia. Obligatorio para cualquier cambio en `triangulation/` o `calibration/`.
2. **El arranque de cada app** (`tests/test_apps.py`), ejecutando `--help`. Ejercita los imports de módulo y `parse_args()`.
3. **La ruta de captura completa**, contra un vídeo sintético con la GUI neutralizada.

Los puntos 2 y 3 existen porque dos fallos seguidos vivieron en el código de las apps y ninguna prueba de biblioteca los vio: un `import` que faltaba y sólo reventaba al arrancar, y un cálculo que sólo se ejecutaba después de veinte capturas manuales.

**Regla: después de tocar una app, ejecutarla.** Que el módulo compile no dice nada sobre si la app arranca.

### Nivel 2 — Con cámaras, sin verdad de terreno

- Error de reproyección medio por landmark sobre una sesión real.
- Verificación del marcador ArUco de integridad.
- fps recibidos frente a esperados.

Detecta degradación de calibración y problemas de captura sin necesidad del MoCap.

### Nivel 3 — Contra el MoCap

Marcadores retrorreflectivos en muñecas y tobillos **sólo durante la sesión de validación**, nunca en operación, y comparación de la triangulación markerless contra el OptiTrack como verdad de terreno.

Es la medida que se reporta en la tesis. Formato de reporte: percentiles de error en milímetros, siguiendo a Nakano et al. (2020) para que sea comparable con literatura publicada.

## Lo que NO se hace desde este repositorio

- No se vuela, arma ni comanda ningún Crazyflie.
- No se emiten comandos PTZ a las cámaras.
- No se modifica la calibración de Motive.
- No se instalan dependencias ni se crean ramas sin petición explícita.

Si una tarea parece requerir alguna de esas cosas, es señal de que pertenece al repositorio `tesis` o de que hace falta pedirle algo al usuario, no de que haya que hacerla aquí.
