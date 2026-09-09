---
fecha: 2026-09-08
tipo: analisis
autor: claude
estado: en_ejecucion
---
# Opciones para bajar líneas de código

> **Actualización 2026-09-08.** Aplicado tras las decisiones del autor: borrados los controles Flow Deck (1.181 líneas) y su cascada en `tk_keys.py` (85), `detectar_gestos_3d.py` fusionado en `probar_vocabulario.py --solo-dinamicos` (327), funciones muertas de `pose_overlay.py` (69), y once tests pasados a pytest (unas 260 netas). Docstrings de mapeo3d conservadas. Quedan pendientes los puntos 2, 3, 4 y 5 de abajo.

Análisis de sólo lectura hecho con tres agentes sobre `external/gesture_detection`, `external/mapeo3d` y `controllers/two_drones`, más una revisión global. Ninguna línea se ha cambiado todavía. Cada hallazgo trae `archivo:línea` para verificarlo antes de tocar nada.

## Resumen

| Carpeta | Líneas hoy | Ahorro sin cambiar comportamiento | Ahorro extra que exige decisión |
|---|---|---|---|
| `external/mapeo3d` | ~10.9k | ~370 | ~100 recortando docstrings de apps |
| `external/gesture_detection` | ~6.1k | ~280 | ~300 fusionando `detectar_gestos_3d.py` en `probar_vocabulario.py` |
| `controllers/two_drones` | ~4.6k | ~330 a 400 | ~545 borrando dos archivos sin consumidor y la figura low-level |
| `controllers/single_drone` y tests | ~2.6k | ~270 pasando los runners propios a pytest | ~315 si el panel Flow Deck individual se funde con el dual |
| **Total** | ~23k a 27k según se cuente | **~1.300 (5 %)** | **~1.500 más (10 % acumulado)** |

Conclusión honesta: la duplicación real es moderada. El repositorio ya pasó por un recorte fuerte en septiembre. Lo que más baja líneas es **borrar lo que nadie usa** (necesita tu confirmación) y **fundir los dos backends de la cruz**. Lo demás son utilidades pequeñas que mejoran mantenimiento más que volumen.

## Los seis refactors con mejor relación ahorro/riesgo

0. **Tests a pytest** (~270 líneas, riesgo bajo). Once archivos de test tienen su propio `main()` con lista de pruebas e impresión OK/FALLA (`external/gesture_detection/tests/test_body_3d_rules.py:405-449`, `test_dinamicos.py:296-336`, `controllers/single_drone/camera/tests/test_control_camara.py:235-274`, `test_highlevel_flight.py:71-168`, entre otros). Un `conftest.py` en la raíz que inserte las carpetas en `sys.path` y un `tests/fakes.py` con `FakeFlight` y `FakeFollower` (hoy copiados entre tests) permiten borrar todos los runners. Cambia la forma de validar que describe `AGENTS.md`; hay que actualizarlo en la misma tarea.

1. **Borrar código sin consumidor en `two_drones`** (~545 líneas, riesgo bajo, exige confirmación).
   - `controllers/two_drones/panel_control_flowdeck_dos_drones.py` (242 líneas): cero imports, cero menciones en README, docs o lanzadores.
   - `controllers/two_drones/control_camara_flowdeck_dos_drones.py` (257): sólo lo nombra la prosa de `docs/agents/gesture_pipeline.md:60`.
   - Figura y columnas de "comandos low-level" en `analizar_sesion_dos_drones.py:138-167,281-283`, `dual_flight_logger.py:23,73-80` y `drone_unit.py:118`: `DroneUnit.command` nunca se asigna.
   - `diagnostico_flowdeck_dos_drones.py` no tiene consumidor pero parece herramienta manual: **no borrar sin preguntar**.
   - En `external/gesture_detection/visualization/pose_overlay.py:40-99`, `key_landmark_visibilities` y `draw_status_panel` no tienen ningún import en el repo (60 líneas).
   - `detectar_gestos_3d.py` (327 líneas) está superado por `probar_vocabulario.py`: mismo canal dinámico, CSV y segmentos. Borrarlo es la alternativa a fusionarlo.
   - `controllers/single_drone/flowdeck/panel_control_flowdeck_dron1.py` (315) y `controllers/two_drones/diagnostico_flowdeck_dos_drones.py` (208): un segundo barrido confirma cero referencias en todo el repo (ni README, ni docs, ni imports). Siguen siendo posibles herramientas de laboratorio lanzadas a mano: confirmar.
   - Si se borran los dos paneles Flow Deck, en `controllers/shared/tk_keys.py` quedan huérfanos `HeldKeysMixin`, `held_axes` y `SINGLE_KEYSYMS` (78 líneas más); `DualStepKeysMixin` sigue vivo.
   - `controllers/shared/flowdeck_flight.py:20` re-exporta `stop_motors` con un `# noqa: F401` que tapa que nadie lo usa.
   - Dudosos: `hover_flowdeck_dron1.py` (159, "script puro" según el refactor), `reetiquetar_gestos.py` (164, sin referencias pero produce la carpeta que `construir_plantillas.py` lee), `instalar_windows.{bat,ps1}` y `README_ACTUALIZACION_GESTOS_MANO.md`.

2. **Fundir `SimulatedBackend` y `HardwareBackend`** en `cruz_highlevel_backend.py` (~70 a 90 líneas, riesgo medio). `_selected` y `_require_ready` son idénticos carácter a carácter; `_validate_target`, `move`, `follow_move`, `takeoff`, `land`, `emergency`, `snapshot` y `close` sólo difieren en cómo leen el estado (dict vs `DroneUnit` con lock). Propuesta: clase base `_CruzBackend` con un `UnitDriver` inyectado (`DictDriver` para simulación, `CflibDriver` para hardware). Aviso: `tests/test_camera_marker_runtime.py:38-39` depende de que `units[k]` sea un dict.
   Después, fundir `move` y `follow_move` en un `_step(cmd, geofence, duration_s, mode, status)` (~40 líneas más, riesgo medio-alto porque cambia la ruta del seguimiento del marker 65; conservar las dos rutas de comprobación de separación).

3. **Utilidades compartidas en `external/gesture_detection`** (~280 líneas, riesgo bajo), en este orden:
   - `visualization/colores.py` y `visualization/hud.py` (paleta byte-idéntica en 4 archivos; banda semitransparente, texto contorneado, pie de teclas).
   - `cli.py` con `añadir_camara`, `añadir_banco`, `añadir_csv`, `añadir_segmentos`, `cargar_banco` y `ejecutar(fn)` (el epílogo de `main()` es idéntico en cinco scripts).
   - `dataset/sesion_csv.py` y `dataset/segmentos.py` (`guardar_segmento` y el historial crudo están duplicados en `probar_vocabulario.py:406-457` y `detectar_gestos_3d.py:181-214`).
   - `visualization/panel.py` con la clase `Lineas` (dos copias casi iguales).
   - `camera_loop.py` con el bucle de cámara común a cinco scripts (el más grande y el más delicado, al final).

4. **Utilidades compartidas en `external/mapeo3d`** (~370 líneas, riesgo bajo):
   - `tests/conftest.py` y `pyproject.toml` con `pythonpath = ["src"]`: elimina 12 copias de `sys.path.insert` en tests y unifica `K()`, `render_tablero()`, `vistas_sinteticas()`.
   - `src/mapeo3d/cli/fuente.py` (`resolver_fuente`, `abrir_stream` con timeout): reescrito cinco y seis veces en `apps/`.
   - `src/mapeo3d/io/rutas.py` (`ruta_resultado`, `guardar_yaml`, `cargar_yaml`): el paquete `io/` está declarado en `AGENTS.md` y no existe.
   - Mover `_proyectar`, `_panel_3d` y `_panel_texto` de `apps/check_pose3d.py:114-179` a `pose/draw.py` (el propio `draw.py:4` pide que no se copie dibujo entre apps).
   - `calibration/board.py: vista_repetida()` y `calibration/_robustez.py: rechazar_atipicos()` (duplicados entre intrínsecos y extrínsecos).

5. **Paneles Tk y telemetría cflib en `controllers`** (~130 líneas, riesgo bajo): `SafeClosePanelMixin` y `run_panel()` en `shared/`, `shared/cf_logging.py` con `start_log`/`stop_log` (el patrón `LogConfig` se repite en `drone_unit.py`, `flowdeck_dual_backend.py` y dos más), y `SessionRecording(CsvSession)`.

## Lo que NO es código muerto

- `external/mapeo3d/src/mapeo3d/{capture/sync,pose/canonical,pose/eventos,triangulation/robust}.py` (2.184 líneas con sus tests) no tienen app que los consuma, pero son la etapa multivista planeada. La acción es escribir la app que los use, no borrarlos.
- `reetiquetar_gestos.py` no tiene referencias, pero produce la carpeta `results/data/gestos_reetiquetado` que `construir_plantillas.py:139` lee por defecto. Está sin documentar, no muerto.
- `JsonLineServer` en `cruz_highlevel_backend.py:660-780` tiene un consumidor real. Sólo hay que corregir el docstring que anuncia una CLI inexistente.

## Decisiones que necesito de ti

1. ¿Borro `panel_control_flowdeck_dos_drones.py` y `control_camara_flowdeck_dos_drones.py`?
2. ¿Fusiono `detectar_gestos_3d.py` dentro de `probar_vocabulario.py` con un flag `--solo-dinamicos`?
3. ¿Recorto las docstrings de `external/mapeo3d/apps/*.py` (267 líneas que duplican `docs/`)? Son la mejor documentación del subsistema; yo las dejaría.
4. ¿Se puede probar en el Robotat sin hélices tras fundir `move`/`follow_move`? Sin esa prueba no lo haría.
5. ¿Paso todos los tests a pytest con un `conftest.py` raíz? Implica cambiar la sección "Validación" de `AGENTS.md`.
6. ¿Conservas el panel y el hover de Flow Deck para un dron (`controllers/single_drone/flowdeck/`)? Nadie los referencia, pero el panel individual y el dual son casi gemelos y podrían ser uno solo parametrizado.

## Cómo se convertiría en tareas

Cada refactor de arriba cabe en una tarea del vault para Codex (los de riesgo bajo) o Claude (los dos backends). Validación mínima en todos: `python -m compileall`, los tests de la carpeta, `--help` de cada lanzador, y para `mapeo3d` `python -m pytest tests -q` desde su carpeta.
