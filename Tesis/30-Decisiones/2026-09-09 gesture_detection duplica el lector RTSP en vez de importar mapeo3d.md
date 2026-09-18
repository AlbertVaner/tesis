---
fecha: 2026-09-09
estado: vigente
afecta: gesture_detection, mapeo3d
---
## Decisión
`external/gesture_detection/video_source.py` implementa su propio lector RTSP —hilo lector, sólo el último frame, transporte TCP forzado— en vez de reutilizar `CameraStream` de `external/mapeo3d/src/mapeo3d/capture/stream.py`, que resuelve exactamente lo mismo. Son unas 40 líneas duplicadas **a propósito**.

## Contexto

Al añadir `--rtsp` a `probar_vocabulario.py` y `probar_gestos_3d.py` hacía falta un lector RTSP que no acumulara latencia. `mapeo3d` ya tiene uno maduro, con reconexión y estadísticas.

Pero `external/mapeo3d/AGENTS.md` dice, literalmente, que los demás subsistemas **no importan `mapeo3d` hasta que el contrato de datos esté definido**, y ese contrato es la tarea T-002, que sigue en estado `pendiente`. Importarlo habría violado el contrato en vigor.

La alternativa era adelantar T-002 sobre la marcha, en medio de una sesión de puesta en marcha de hardware. Se prefirió no hacerlo: T-002 es explícitamente una tarea de diseño sin código, y resolverla de pasada para desbloquear un import habría sido decidirla mal.

## Consecuencias

- La duplicación queda **documentada en el docstring de `video_source.py`**, con el motivo y la referencia a T-002, para que un lector futuro no la interprete como un descuido.
- La implementación de `gesture_detection` es deliberadamente más simple que `CameraStream`: no tiene reconexión automática ni estadísticas, porque los probadores son sesiones interactivas cortas y no las necesitan.
- **Al cerrar T-002, esto es el primer candidato a unificar.** Conviene revisarlo en esa tarea antes de que la duplicación se asiente.
- El sentido de la dependencia importa: `mapeo3d` no importa `gesture_detection` en ningún caso, y eso no cambia.
