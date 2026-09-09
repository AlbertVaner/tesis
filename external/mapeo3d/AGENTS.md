# Mapeo tridimensional con cámaras — contrato para agentes

Subsistema de la capa de **percepción 3D del operador** para la tesis *Control de drones basado en gestos mediante captura de movimiento en el ecosistema Robotat*.

Este repositorio produce **la pose 3D del cuerpo del operador**, triangulada desde varias cámaras IP fijas y expresada en el marco de coordenadas del Robotat. No vuela drones, no reconoce gestos y no decide comandos.

> Desde el 7 de septiembre de 2026 este código vive en `external/mapeo3d/` dentro del repositorio `tesis`. El repositorio original `mapeo_tridimensional_con_camaras` queda como histórico. Las rutas de este documento son relativas a `external/mapeo3d/`.

## Estado canónico

- Ejecutar los comandos desde `external/mapeo3d/`, la raíz de este subsistema, no desde la raíz de `tesis`. Los scripts de `apps/` y `tests/` resuelven `src/` respecto a su propia ubicación.
- Python en Windows/PowerShell, con el `.venv` de la raíz de `tesis`. El `requirements.txt` de la raíz es la lista principal de dependencias; el de esta carpeta sólo remite a él.
- `main` es la rama canónica. No crear ramas, commits ni instalar dependencias sin petición explícita.
- **El repositorio está en fase de andamiaje.** Casi todo lo que describe `docs/` es diseño previsto, no código existente. Cada documento marca explícitamente su estado con `[implementado]`, `[parcial]` o `[planeado]`. Un agente **no debe asumir que un módulo existe porque `docs/` lo describa**: verificar en el árbol de archivos antes de importarlo o referenciarlo.
- El mapa de documentación vive en [`docs/README.md`](docs/README.md).

## Qué hace y qué NO hace este repositorio

| Sí | No |
|---|---|
| Leer streams RTSP de varias cámaras IP | Volar, armar o comandar un Crazyflie |
| Calibrar intrínsecos y extrínsecos | Reconocer gestos o clasificar intenciones |
| Estimar landmarks 2D por cámara | Traducir movimiento a órdenes de vuelo |
| Triangular a 3D en el marco del Robotat | Hablar con `cflib` o con el enlace de radio |
| Filtrar, validar y registrar la pose 3D | Implementar límites de vuelo o paradas de emergencia |

Los controladores de `tesis` (`controllers/`) son el consumidor. **Este subsistema nunca importa `controllers/`, `web/` ni `gesture_detection/`, y ellos no importan `mapeo3d` hasta que el contrato de datos esté definido** (tarea T-002 del vault): se comunican por el contrato de datos descrito en [`docs/architecture.md`](docs/architecture.md).

## Distinción fundamental: dos sistemas de cámaras

Es el error conceptual más fácil de cometer en este proyecto y hay que tenerlo presente en cada archivo.

| Sistema | Qué observa | Protocolo | Dónde vive |
|---|---|---|---|
| **OptiTrack / MoCap** | **el dron** (marcadores retrorreflectivos IR) | MQTT, tópicos `mocap/...` | Robotat; consumido por `tesis` |
| **Cámaras IP** | **el operador** (persona, luz visible) | RTSP | **este repositorio** |

No se cruzan en el flujo de datos. Se encuentran en dos puntos, ambos deliberados:

1. **Calibración**: el MoCap aporta la verdad de terreno 3D que fija los extrínsecos de las cámaras IP en el marco del Robotat.
2. **Validación**: el MoCap sirve como referencia para medir el error de la triangulación markerless.

Fuera de esos dos usos, este repositorio no consulta al MoCap en tiempo de ejecución.

## Límites y ownership

| Raíz | Responsabilidad |
|---|---|
| `src/mapeo3d/capture/` | Clientes RTSP, buffers, marcas de tiempo de llegada, sincronización entre cámaras |
| `src/mapeo3d/calibration/` | Intrínsecos, extrínsecos, matrices de proyección, marco Robotat, integridad de calibración |
| `src/mapeo3d/pose/` | Estimación de landmarks 2D por cámara (MediaPipe u otro backend) |
| `src/mapeo3d/triangulation/` | DLT de N vistas, robustez, filtrado temporal, restricciones anatómicas |
| `src/mapeo3d/io/` | Serialización, registro en disco, publicación del contrato de salida |
| `apps/` | Scripts ejecutables: diagnóstico, calibración, captura de dataset, visor en vivo |
| `config/` | Configuración versionada sin secretos (`*.example.yaml`) |
| `docs/` | Documentación de arquitectura y operación, dirigida a agentes y a personas técnicas |
| `results/` | Datos, calibraciones producidas, gráficas y capturas. Generado, no fuente |
| `tests/` | Pruebas automatizadas |

## Criterio para ubicar archivos nuevos

Elegir por la **responsabilidad principal**, no por una palabra del nombre ni por el primer módulo que lo use.

1. **Separar por etapa del pipeline.** El flujo es `capture → pose → triangulation`, con `calibration` como entrada transversal y `io` como salida. Un archivo pertenece a la etapa cuyo estado y vocabulario manipula.
2. **`capture/` no sabe qué es una persona.** Entrega frames con marca de tiempo. Si un módulo necesita saber de landmarks, no va en `capture/`.
3. **`pose/` no sabe que hay varias cámaras.** Procesa una imagen y devuelve landmarks 2D normalizados con su confianza. La agregación multivista es de `triangulation/`.
4. **`triangulation/` no sabe de RTSP ni de MediaPipe.** Recibe landmarks 2D con matrices de proyección; devuelve puntos 3D. Debe poder probarse con datos sintéticos sin cámaras.
5. **`calibration/` es la única dueña de las matrices.** Ningún otro módulo construye una matriz de proyección por su cuenta ni asume un orden de cámaras.
5b. **Los puntos se rectifican antes de triangular.** `K[R|T]` describe una cámara estenopeica ideal; los landmarks detectados llevan la distorsión del objetivo. Entre detectar y triangular va siempre `CameraIntrinsics.undistort_points()`. Saltárselo no produce ningún error visible —el residual sigue bajo— pero sesga la escala reconstruida varios puntos porcentuales. `triangulation/` no rectifica: no conoce los intrínsecos. Es responsabilidad de quien llama.
6. **Los ejecutables van en `apps/`.** Un archivo con `if __name__ == "__main__"` y parsing de argumentos es una aplicación, no una biblioteca. Las apps componen; no contienen algoritmos.
7. **Nada de lógica de vuelo, en ninguna carpeta.** Si un archivo necesita conocer velocidades, altura, URI de radio o límites de seguridad del dron, pertenece a `controllers/` del repositorio `tesis`.

Para archivos que combinen responsabilidades, dejar un punto de composición pequeño en `apps/` y extraer cada responsabilidad a su módulo propietario.

### Casos auxiliares

- **Configuración:** `config/` con sufijo `.example` para lo versionado. Las IP, usuarios y contraseñas de las cámaras **son secretos operativos**: van en un archivo local ignorado o en variables de entorno, nunca en el repositorio.
- **Resultados:** `results/calibration/<AAAA-MM-DD>/`, `results/data/<sesion>/`, `results/graphs/<sesion>/`. Los archivos generados no son código fuente y no se versionan.
- **Pruebas:** `tests/` en la raíz, con datos sintéticos. La triangulación y la calibración deben tener pruebas que no requieran cámaras.
- **Documentación:** transversal en `docs/`. Instrucciones específicas de un módulo pueden vivir junto a él si son imprescindibles para usarlo.

Antes de crear un archivo, buscar implementaciones equivalentes y comprobar imports y `.gitignore`. Después de crearlo o moverlo, actualizar las rutas afectadas y **actualizar el documento de `docs/` correspondiente en el mismo cambio**, incluida la marca de estado.

## Reglas de dependencias

- `apps/` puede importar cualquier módulo de `src/mapeo3d/`.
- `triangulation/` puede importar `calibration/`. No al revés.
- `pose/` no importa `capture/`, `triangulation/` ni `calibration/`.
- `capture/` no importa ningún otro módulo del paquete.
- Ningún módulo de `src/mapeo3d/` importa nada de `apps/`.
- **Este subsistema no importa `cflib`, ni `controllers/`, ni ninguna biblioteca de control de vuelo.**
- No añadir datos generados, calibraciones producidas, credenciales de cámara ni entornos virtuales al control de versiones.

## Seguridad

Este repositorio no toca hardware de vuelo, pero sí toca dos cosas frágiles:

- **La calibración del OptiTrack.** No manipular soportes, ni pedir al usuario que lo haga, sin advertir que puede invalidar la calibración de Motive.
- **La orientación de las cámaras IP.** Las cámaras actuales son pan/tilt motorizadas: **cualquier movimiento del motor invalida los extrínsecos sin ningún síntoma visible**. Ningún módulo de este repositorio debe emitir comandos PTZ. Ver [`docs/hardware.md`](docs/hardware.md).
- Nunca registrar credenciales de cámara en logs, mensajes de error ni nombres de archivo.

## Validación

Desde la raíz:

```powershell
python -m compileall src apps
python -m pytest tests -q
```

Las pruebas de `triangulation/` y `calibration/` deben pasar **sin cámaras conectadas**, usando datos sintéticos. Una tarea que no pueda validarse sin hardware debe decirlo explícitamente en lugar de darse por terminada.

Compilar o importar no equivale a validar: un cambio en triangulación se valida con error de reproyección sobre datos conocidos, no con que el script arranque.

## Flujo Git

- Preservar cambios locales existentes y no reescribir archivos ajenos a la tarea.
- Commits pequeños y convencionales, sólo si el usuario los pide.
- No versionar `results/`, `config/*.local.*`, ni `.venv/`.

## Índice canónico

- [Mapa de documentación](docs/README.md)
- [Arquitectura y contrato de salida](docs/architecture.md)
- [Captura RTSP y sincronización](docs/capture.md)
- [Landmarks 2D y MediaPipe](docs/pose.md)
- [Calibración y marco de coordenadas](docs/calibration.md)
- [Triangulación y filtrado](docs/triangulation.md)
- [Hardware, red y montaje](docs/hardware.md)
- [Operación, resultados y validación](docs/operations.md)

Verificar siempre rutas, argumentos y comportamiento contra el código actual. La documentación describe el estado previsto y el observado, pero no sustituye al código.
