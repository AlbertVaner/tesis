# Estado del proyecto

Actualizar cuando cambie algo grande. Los detalles finos están en el código y en `AGENTS.md`.

## Objetivo de la tesis
Control de drones Crazyflie por gestos, con captura de movimiento del operador en el ecosistema Robotat. Meta final: seis cámaras IP para gestos de cuerpo completo en 3D.

## Subsistemas

| Subsistema | Dónde | Estado |
|---|---|---|
| Vuelo con mocap (backend high-level) | `controllers/two_drones/cruz_highlevel_backend.py` | Funciona; es el backend por defecto para todo control nuevo |
| Vuelo con Flow Deck | `controllers/two_drones/flowdeck_dual_backend.py` | Funciona; sólo se usa desde `control_camara_dron1.py --backend flowdeck` (los paneles y el hover dedicados se borraron el 2026-09-08) |
| Control por cámara de un dron | `controllers/single_drone/camera/control_camara_dron1.py` | Funciona con manos 2D o cuerpo 3D |
| Reconocimiento de gestos | `external/gesture_detection/` | Vocabulario 3D y gestos 2D; en evolución |
| Percepción 3D multicámara | `external/mapeo3d/` | Captura, calibración y triangulación estéreo implementadas; prueba con dos cámaras hecha; seis cámaras pendiente |
| Panel web | `web/` | Funciona |
| Documento de tesis | `thesis/` | LaTeX, en redacción |

## Próximos hitos
1. Revisar T-001 (entornos ya unificados) y las tareas T-003 y T-004 de la oscilación.
2. Contrato de datos mapeo3d a controladores (T-002).
3. Calibrar y montar más cámaras.
