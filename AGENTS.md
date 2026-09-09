# Tesis Crazyflie — contrato para agentes

## Estado canónico

- Ejecutar los comandos desde la raíz del repositorio, salvo que una guía indique lo contrario.
- El proyecto usa Python en Windows/PowerShell. `requirements.txt` es la lista principal de dependencias; `external/gesture_detection/requirements.txt` añade dependencias del subsistema de gestos.
- `main` es la rama observada como canónica. No crear ramas, commits ni instalar dependencias sin petición explícita.
- El mapa técnico ampliado vive en `docs/agents/README.md`.
- `external/mapeo3d/` tiene contrato propio en `external/mapeo3d/AGENTS.md`; sus comandos se ejecutan desde esa carpeta.
- El vault de Obsidian `Tesis/` es el tablero de tareas compartido entre humano y agentes. Ver la sección "Protocolo del vault".

## Límites y ownership

| Raíz | Responsabilidad |
|---|---|
| `controllers/single_drone/buttons/` | UI de botones para un Crazyflie |
| `controllers/single_drone/camera/` | `control_camara_dron1.py`: cámara y gestos para un Crazyflie, con reconocedor (manos 2D / cuerpo 3D) y backend (mocap / Flow Deck) elegibles; `highlevel_flight.py` lo conecta al backend de la cruz |
| `controllers/two_drones/` | Los dos backends de vuelo (`cruz_highlevel_backend.py` con mocap, `flowdeck_dual_backend.py` con Flow Deck), `drone_unit.py`, protocolos, telemetría y análisis |
| `controllers/joystick/` | Lectura del marker Robotat: joystick (`marker_input.py`), seguimiento del marker 65 (`marker_follow.py`) y receptor MQTT |
| `controllers/shared/` | Utilidades reutilizadas entre categorías de control |
| `external/gesture_detection/` | Visión, tracking de manos y clasificación de gestos |
| `external/mapeo3d/` | Percepción 3D del operador con varias cámaras IP: captura RTSP, calibración, landmarks 2D y triangulación al marco del Robotat. Contrato propio en `external/mapeo3d/AGENTS.md` |
| `web/` | Servidor HTTP y recursos estáticos del panel |
| `results/` | Datos, gráficas, capturas y artefactos de ejecución |
| `docs/` | Documentación operativa y para agentes |
| `thesis/` | Documento académico y sus recursos; no es código de runtime |
| `Tesis/` | Vault de Obsidian: tareas, bitácora, decisiones y redacción. No es código |

Los controladores de un dron pueden reutilizar primitivas conservadoras de `two_drones/`; esa dependencia debe permanecer explícita. No mover backends duales fuera de `two_drones/` aunque también sean reutilizados por una interfaz individual.

## Estado del código (septiembre de 2026)

- **Dos backends de vuelo y ninguno más.** Con mocap, todo pasa por el commander high-level del firmware a través de `controllers/two_drones/cruz_highlevel_backend.py` (`HardwareBackend`, `SimulatedBackend` para `--dry-run`). Con Flow Deck, por `controllers/two_drones/flowdeck_dual_backend.py` (`FlowDroneController`, uno por dron). El lazo de velocidad low-level sobre el mocap se eliminó; **no reintroducirlo**. Un control nuevo manda `Command` al backend de la cruz o usa `single_drone/camera/highlevel_flight.py`.
- **Un controlador por cámara para un dron**: `controllers/single_drone/camera/control_camara_dron1.py`, con `--reconocedor {cuerpo,manos}` y `--backend {mocap,flowdeck}`. El banco de pruebas y la práctica guiada sin dron viven en `external/gesture_detection/probar_gestos_3d.py`.
- **`controllers/shared/`** concentra radios, identidad del Robotat, configuración del EKF y corte de motores, preparación con Flow Deck, teclado Tk y CSV de sesión. `two_drones/` no importa nada de `single_drone/`.
- Historia y motivación de esta forma del repositorio: [docs/agents/refactor_2026-09.md](docs/agents/refactor_2026-09.md).

## Criterio para crear y ubicar archivos nuevos

Elegir la ubicación por la responsabilidad principal del archivo, no por una palabra de su nombre ni por el primer módulo que lo utilice. Aplicar este orden:

1. **Determinar el tipo de artefacto.** El código ejecutable pertenece a `controllers/`, `external/` o `web/`; los resultados generados a `results/`; la documentación a `docs/`; y el material académico a `thesis/`.
2. **Si es un controlador, decidir primero el alcance.** Todo archivo cuyo comportamiento, estado o coordinación requiera simultáneamente dos Crazyflies va en `controllers/two_drones/`, aunque reciba órdenes de cámara, botones o joystick.
3. **Para un solo dron, elegir por interfaz principal.** Botones van en `controllers/single_drone/buttons/` y cámara o gestos en `controllers/single_drone/camera/`. El Flow Deck no tiene controladores propios desde septiembre de 2026: se elige con `--backend flowdeck` en el controlador por cámara.
4. **Separar joystick de la implementación de vuelo.** La lectura, traducción y adaptación de marker, mocap o joystick va en `controllers/joystick/`. Si dirige dos drones, la coordinación y ejecución de vuelo permanecen en `controllers/two_drones/` y consumen la entrada del joystick mediante una interfaz explícita.
5. **Usar `controllers/shared/` sólo para reutilización real.** Un módulo puede ir allí cuando tenga al menos dos consumidores de categorías distintas, no dependa de UI, cámara, joystick, web ni de un número concreto de drones, y represente una abstracción estable. No crear utilidades genéricas anticipadamente para un único consumidor.
6. **Mantener visión independiente en `external/gesture_detection/`.** El procesamiento de imagen, tracking y clasificación que pueda funcionar sin conocer Crazyflie va allí. La conversión de sus resultados en órdenes de vuelo pertenece al controlador que los consume.
7. **Mantener la web en `web/`.** Rutas HTTP, servidor, recursos estáticos y adaptadores de presentación web van allí. La lógica de vuelo no debe trasladarse a la web: ésta llama contratos públicos de los controladores.

Para archivos que combinen responsabilidades, conservar un punto de composición pequeño en la categoría que inicia la ejecución y extraer cada responsabilidad a su carpeta propietaria. No duplicar implementaciones entre categorías ni crear dependencias circulares para evitar esa separación.

### Casos auxiliares

- **Lanzadores:** colocar el lanzador junto al controlador principal. Sólo conservar en la raíz un wrapper pequeño requerido por compatibilidad o como entrada documentada; no añadir nuevos scripts de negocio en la raíz.
- **Pruebas:** crear `tests/` dentro de la categoría propietaria para pruebas específicas. Las pruebas que integren varias categorías van en `tests/integration/` en la raíz.
- **Configuración:** mantener junto al subsistema que la consume. Una configuración transversal y no secreta puede ir en `config/` en la raíz cuando existan al menos dos consumidores independientes.
- **Resultados:** usar `results/data/<controlador>/<AAAA-MM-DD>/` para logs y datos, `results/graphs/<controlador>/<AAAA-MM-DD>/` para gráficas y `results/captures/<controlador>/<AAAA-MM-DD>/` para capturas. Los archivos generados no son código fuente.
- **Documentación:** instrucciones específicas viven junto al subsistema cuando son necesarias para usarlo; documentación transversal, arquitectura y operación viven en `docs/`.
- **Compatibilidad histórica:** el código anterior a la reorganización se eliminó (queda en el historial de git). No recrear carpetas `archive/` ni adaptadores de compatibilidad; implementar la fuente canónica en la carpeta vigente.
- **Secretos y entorno local:** `.env`, entornos virtuales, caches y credenciales no definen arquitectura y no deben versionarse. Documentar variables necesarias en `.env.example` sin valores sensibles.

Antes de crear un archivo, buscar implementaciones equivalentes y comprobar imports, lanzadores, documentación y `.gitignore`. Después de crearlo o moverlo, actualizar todas las rutas afectadas y ejecutar una validación estática proporcional al cambio. Si dos ubicaciones siguen siendo razonables, elegir la que reduzca dependencias hacia afuera y registrar la decisión en la documentación del subsistema.

## Reglas de dependencias

- Los lanzadores y la web pueden componer controladores y módulos externos.
- `external/gesture_detection/` no debe importar controladores ni la web.
- `external/mapeo3d/` no importa `cflib`, controladores, web ni `gesture_detection`; se comunica con ellos por el contrato de datos de `external/mapeo3d/docs/architecture.md`.
- Los controladores no deben importar la web.
- Guardar nuevas corridas en `results/data/<controlador>/` y gráficas en `results/graphs/<controlador_o_sesion>/`.
- No añadir datos generados, caches de radio, secretos ni entornos virtuales al control de versiones. Todos los controladores escriben el cache de `cflib` bajo `./cache/<nombre>/` (ignorado).
- Hay imports basados en `sys.path` porque los scripts se ejecutan directamente. Verificar ejecución directa antes de convertir carpetas en paquetes.

## Seguridad de hardware

- No conectar, despegar, armar, enviar comandos de radio ni abrir una prueba de vuelo salvo autorización explícita.
- Preferir `--dry-run` para validaciones. Compilar o importar estáticamente no equivale a validar un vuelo.
- No cambiar URI, límites de velocidad/altura, ganancias, tópicos mocap ni calibraciones de seguridad sin explicarlo y obtener autorización cuando afecte hardware real.
- Nunca registrar credenciales o datos sensibles. Los caches de `cflib` son estado local y deben permanecer ignorados.

## Validación

Desde la raíz, con el `.venv` del repositorio:

```powershell
python -m compileall controllers external web control_dron_camara.py control_dos_drones_camara.py
python -m pytest -q
```

`pytest.ini` y `conftest.py` en la raíz recogen todas las pruebas (`controllers/**/tests`, `tests/integration`, `external/gesture_detection/tests` y `external/mapeo3d/tests`) con un solo comando; `conftest.py` pone las carpetas de los scripts en `sys.path`. Para una sola carpeta o archivo: `python -m pytest -q external\gesture_detection\tests` o `python -m pytest -q ruta\al\test_x.py`. Desde septiembre de 2026 ningún test lleva runner propio; los nuevos se escriben como funciones `test_*` con `assert` o como `unittest.TestCase`.

Los `--dry-run` de las interfaces Tk abren ventanas y bloquean una sesión no interactiva; `--help` de cada lanzador comprueba imports y argumentos sin abrir nada. No ejecutar interfaces, cámara o hardware como parte de una tarea documental.
## Flujo Git

- Preservar cambios locales existentes y no reescribir archivos ajenos a la tarea.
- Usar ramas `codex/<scope>` si el usuario pide crear una rama.
- Mantener commits pequeños y convencionales si el usuario pide commits.

## Protocolo del vault (Obsidian)

El vault `Tesis/` es el tablero compartido. Claude, Codex y Gemini siguen el mismo protocolo:

1. **Antes de tocar código, leer la tarea completa** en `Tesis/10-Tareas/T-### <título>.md`: objetivo, criterio de aceptación y contexto. Leer también los archivos que la tarea enlaza.
2. **Cumplir el criterio de aceptación tal como está escrito.** Si es ambiguo o imposible, escribir la duda en la sección `Bitácora` de la tarea, dejar `estado: pendiente` y parar.
3. **Al empezar**, cambiar `estado: en_progreso` en el frontmatter.
4. **Al terminar**, cambiar `estado: revisar` (nunca `hecha`: eso lo decide el humano), añadir una línea `- AAAA-MM-DD (<agente>): <qué se hizo, qué se validó>` en la `Bitácora` de la tarea, y una línea en `Tesis/20-Bitacora/AAAA-MM-DD.md` bajo `## Agentes` (crear la nota copiando `Tesis/_plantillas/Bitacora.md` si no existe).
5. **Decisiones de diseño** que afecten a más de un subsistema se registran en `Tesis/30-Decisiones/` con la plantilla `Decision.md`, además de en la documentación del subsistema.
6. **No tocar** `Tesis/.obsidian/`, ni crear notas fuera de las carpetas numeradas o `_plantillas`. Los enlaces se escriben en Markdown estándar `[texto](ruta relativa)`, no en `[[wikilinks]]`.
7. Una tarea por agente a la vez. No editar archivos que otra tarea `en_progreso` declare en su contexto.

## Índice canónico

- [Mapa de documentación](docs/agents/README.md)
- [Arquitectura y dependencias](docs/agents/architecture.md)
- [Ejecución, resultados y seguridad](docs/agents/operations.md)
- [Pipeline de gestos por visión](docs/agents/gesture_pipeline.md)
- [Refactorización de septiembre de 2026](docs/agents/refactor_2026-09.md)
- [Guía de comandos Crazyflie](docs/Guia_comandos_controladores_Crazyflie.docx) (documento histórico; los comandos vigentes están en los README de cada categoría)
- [Plan de reconocimiento de gestos](docs/plan_reconocimiento_gestos_robotat.md)
- [Control de cruz en Python](controllers/two_drones/README_CONTROL_CRUZ_PYTHON.md)
- [Control mediante marker](controllers/joystick/README.md)
- [Detección de gestos](external/gesture_detection/README.md)
- [Percepción 3D multicámara](external/mapeo3d/AGENTS.md) y su [mapa de documentación](external/mapeo3d/docs/README.md)
- [Vault de Obsidian: inicio](Tesis/Inicio.md), [tablero](Tesis/Tablero.md) y [reparto entre agentes](Tesis/Agentes.md)

Verificar siempre rutas, argumentos y comportamiento en el código actual. La documentación describe el estado observado, pero no sustituye al código.
