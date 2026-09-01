# Tesis Crazyflie — contrato para agentes

## Estado canónico

- Ejecutar los comandos desde la raíz del repositorio, salvo que una guía indique lo contrario.
- El proyecto usa Python en Windows/PowerShell. `requirements.txt` es la lista principal de dependencias; `external/gesture_detection/requirements.txt` añade dependencias del subsistema de gestos.
- `main` es la rama observada como canónica. No crear ramas, commits ni instalar dependencias sin petición explícita.
- El mapa técnico ampliado vive en `docs/agents/README.md`.

## Límites y ownership

| Raíz | Responsabilidad |
|---|---|
| `controllers/single_drone/buttons/` | UI de botones para un Crazyflie |
| `controllers/single_drone/camera/` | Cámara y gestos para un Crazyflie |
| `controllers/single_drone/flowdeck/` | Hover y teclado para un Crazyflie con Flow Deck |
| `controllers/two_drones/` | Runtime de dos Crazyflies: backends, protocolos, telemetría y análisis |
| `controllers/joystick/` | Marker/mocap usado como joystick y control asociado |
| `controllers/shared/` | Utilidades reutilizadas entre categorías de control |
| `external/gesture_detection/` | Visión, tracking de manos y clasificación de gestos |
| `web/` | Servidor HTTP y recursos estáticos del panel |
| `results/` | Datos, gráficas, capturas y artefactos de ejecución |
| `docs/` | Documentación operativa y para agentes |
| `thesis/` | Documento académico y sus recursos; no es código de runtime |
| `archive/legacy/` | Compatibilidad histórica; evitar ampliarla |

Los controladores de un dron pueden reutilizar primitivas conservadoras de `two_drones/`; esa dependencia debe permanecer explícita. No mover backends duales fuera de `two_drones/` aunque también sean reutilizados por una interfaz individual.

## Criterio para crear y ubicar archivos nuevos

Elegir la ubicación por la responsabilidad principal del archivo, no por una palabra de su nombre ni por el primer módulo que lo utilice. Aplicar este orden:

1. **Determinar el tipo de artefacto.** El código ejecutable pertenece a `controllers/`, `external/` o `web/`; los resultados generados a `results/`; la documentación a `docs/`; y el material académico a `thesis/`.
2. **Si es un controlador, decidir primero el alcance.** Todo archivo cuyo comportamiento, estado o coordinación requiera simultáneamente dos Crazyflies va en `controllers/two_drones/`, aunque reciba órdenes de cámara, botones o joystick.
3. **Para un solo dron, elegir por interfaz principal.** Botones van en `controllers/single_drone/buttons/`; cámara o gestos en `controllers/single_drone/camera/`; y vuelo apoyado en Flow Deck o teclado asociado en `controllers/single_drone/flowdeck/`.
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
- **Compatibilidad histórica:** no crear archivos nuevos en `archive/legacy/`. Si una compatibilidad es imprescindible, implementar la fuente canónica en la carpeta vigente y dejar en legacy únicamente un adaptador mínimo.
- **Secretos y entorno local:** `.env`, entornos virtuales, caches y credenciales no definen arquitectura y no deben versionarse. Documentar variables necesarias en `.env.example` sin valores sensibles.

Antes de crear un archivo, buscar implementaciones equivalentes y comprobar imports, lanzadores, documentación y `.gitignore`. Después de crearlo o moverlo, actualizar todas las rutas afectadas y ejecutar una validación estática proporcional al cambio. Si dos ubicaciones siguen siendo razonables, elegir la que reduzca dependencias hacia afuera y registrar la decisión en la documentación del subsistema.

## Reglas de dependencias

- Los lanzadores y la web pueden componer controladores y módulos externos.
- `external/gesture_detection/` no debe importar controladores ni la web.
- Los controladores no deben importar la web.
- Guardar nuevas corridas en `results/data/<controlador>/` y gráficas en `results/graphs/<controlador_o_sesion>/`.
- No añadir datos generados, caches de radio, secretos ni entornos virtuales al control de versiones.
- Hay imports basados en `sys.path` porque los scripts se ejecutan directamente. Verificar ejecución directa antes de convertir carpetas en paquetes.

## Seguridad de hardware

- No conectar, despegar, armar, enviar comandos de radio ni abrir una prueba de vuelo salvo autorización explícita.
- Preferir `--dry-run` para validaciones. Compilar o importar estáticamente no equivale a validar un vuelo.
- No cambiar URI, límites de velocidad/altura, ganancias, tópicos mocap ni calibraciones de seguridad sin explicarlo y obtener autorización cuando afecte hardware real.
- Nunca registrar credenciales o datos sensibles. Los caches de `cflib` son estado local y deben permanecer ignorados.

## Validación

Desde la raíz:

```powershell
python -m compileall controllers external web control_dron_camara.py control_dos_drones_camara.py
python .\controllers\two_drones\control_dos_drones_cruz_botones.py --dry-run
```

La segunda orden sólo aplica si sus dependencias ya están instaladas. No ejecutar interfaces, cámara o hardware como parte de una tarea documental.

## Flujo Git

- Preservar cambios locales existentes y no reescribir archivos ajenos a la tarea.
- Usar ramas `codex/<scope>` si el usuario pide crear una rama.
- Mantener commits pequeños y convencionales si el usuario pide commits.
- No usar `archive/legacy/` como fuente canónica para nuevas funciones, aunque la web y un lanzador todavía lo consultan por compatibilidad.

## Índice canónico

- [Mapa de documentación](docs/agents/README.md)
- [Arquitectura y dependencias](docs/agents/architecture.md)
- [Ejecución, resultados y seguridad](docs/agents/operations.md)
- [Guía de comandos Crazyflie](docs/Guia_comandos_controladores_Crazyflie.docx)
- [Control de cruz en Python](controllers/two_drones/README_CONTROL_CRUZ_PYTHON.md)
- [Control mediante marker](controllers/joystick/README.md)
- [Detección de gestos](external/gesture_detection/README.md)

Verificar siempre rutas, argumentos y comportamiento en el código actual. La documentación describe el estado observado, pero no sustituye al código.
