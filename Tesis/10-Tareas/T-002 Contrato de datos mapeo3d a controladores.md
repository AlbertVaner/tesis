---
estado: pendiente
agente: claude
repo: tesis
prioridad: media
creada: 2026-09-07
---
## Objetivo
Definir cómo `external/mapeo3d` entrega la pose 3D a `controllers/single_drone/camera/` ahora que viven en el mismo repositorio: módulo compartido, archivo, o MQTT.

## Criterio de aceptación
- [ ] Una nota en `30-Decisiones` con la opción elegida y por qué
- [ ] `external/mapeo3d/docs/architecture.md` y `docs/agents/architecture.md` actualizados con el mismo contrato
- [ ] Sin código nuevo todavía: es una tarea de diseño

## Contexto
- `external/mapeo3d/docs/architecture.md` (contrato de salida previsto)
- `docs/agents/gesture_pipeline.md` (contrato `GestureEvent`)
- `controllers/single_drone/camera/control_camara_dron1.py` (consumidor)
- Objetivo final: seis cámaras para gestos 3D; el estéreo de dos cámaras fue sólo la prueba previa

## Bitácora
- 2026-09-07 (humano): creada.
