# Tesis Crazyflie — contrato para agentes

## Estado canónico

- Ejecutar los comandos desde la raíz del repositorio, salvo que una guía indique lo contrario.
- El proyecto usa Python en Windows/PowerShell. `requirements.txt` es la lista principal de dependencias; `external/gesture_detection/requirements.txt` añade dependencias del subsistema de gestos.
- `main` es la rama observada como canónica. No crear ramas, commits ni instalar dependencias sin petición explícita.
- El mapa técnico ampliado vive en `docs/agents/README.md`.

## Límites y ownership

| Raíz | Responsabilidad |
|---|---|
| `controllers/crazyflie/` | Control de vuelo, UI local, backends, protocolos, telemetría y análisis de Crazyflie |
| `controllers/joystick/` | Marker/mocap y control asociado |
| `external/gesture_detection/` | Visión, tracking de manos y clasificación de gestos |
| `web/` | Servidor HTTP y recursos estáticos del panel |
| `results/` | Datos, gráficas, capturas y artefactos de ejecución |
| `docs/` | Documentación operativa y para agentes |
| `thesis/` | Documento académico y sus recursos; no es código de runtime |
| `archive/legacy/` | Compatibilidad histórica; evitar ampliarla |

No dividir archivos entre `backend`, `multiprocessing`, `flow deck` o `joystick` sólo por nombre: hoy esos conceptos están acoplados dentro de controladores ejecutables. Primero aislar imports y contratos, luego moverlos en un refactor verificable.

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
