---
fecha: 2026-09-17
estado: vigente
afecta: tesis
---
## Decisión
El núcleo de vuelo por dron sobre el Robotat (`dron_robotat.py`, `mocap_feed.py` y `analizar_sesion_robotat.py`) pasa de `controllers/single_drone/robotat/` a `controllers/shared/`, y `AGENTS.md` describe tres formas de volar elegibles con `--backend {robotat,mocap,flowdeck}`, con `robotat` como la recomendada.

## Contexto
El controlador nuevo se escribió el 16 de septiembre para un solo dron y ese mismo día pasó a usarse desde el panel de un dron, la cámara de un dron, el panel dual y, por `two_drones/robotat_backend.py`, desde todas las interfaces de la cruz. Eso dejó dos incumplimientos del contrato: `two_drones/` importaba de `single_drone/` y `AGENTS.md` decía que sólo había dos backends. Opciones: (a) mover el núcleo a `two_drones/` (la dirección de dependencia que el repositorio ya admite, pero no es un controlador de dos drones), (b) moverlo a `shared/` (tres consumidores de categorías distintas, sin UI, sin número fijo de drones: cumple el criterio de `shared/`), (c) mantener la excepción. Se elige (b).

## Consecuencias
- `controllers/shared/` contiene el núcleo y sus pruebas (`shared/tests/`); `single_drone/robotat/` conserva el panel, el adaptador de cámara y sus pruebas.
- `two_drones/` vuelve a no importar nada de `single_drone/`. `parametros_firmware` vive en `dron_robotat.py`.
- `AGENTS.md` actualizado: tabla de ownership, estado del código, criterio de ubicación e índice. El backend de mocap de la cruz se conserva como referencia; no se elimina.
- Los CSV siguen en `results/data/dron_robotat/` y las gráficas PDF en `results/graphs/dron_robotat/`.
- Las notas de análisis anteriores citan las rutas antiguas; se dejan como registro histórico.
