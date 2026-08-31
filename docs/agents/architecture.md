# Arquitectura actual

## Flujo principal

```text
web/ o lanzadores
        |
        v
controllers/crazyflie/ <---- controllers/joystick/
        |
        +---- external/gesture_detection/
        |
        +---- cflib, cámara, MQTT/mocap
        |
        v
results/data/ y results/graphs/
```

`controllers/crazyflie/` sigue siendo un módulo cohesionado por imports locales. Contiene entrypoints, backend high/low-level, protocolo multiproceso, Flow Deck, joystick/UI, logging y análisis. Separarlo físicamente en subcarpetas ahora rompería la ejecución directa; debe hacerse como un refactor posterior, incorporando paquetes e imports explícitos.

`controllers/joystick/` reutiliza la captura PDF de Crazyflie. `web/server.py` todavía carga partes de `archive/legacy/` por compatibilidad. Ambas son dependencias conocidas que conviene retirar gradualmente.

## Dirección permitida

- UI/lanzadores -> controladores -> integraciones externas.
- Controladores -> resultados.
- Web -> controladores.
- Nunca: detección gestual -> controladores, controladores -> web, runtime -> tesis.

Los archivos `control_dron_camara.py` y `control_dos_drones_camara.py` se conservan en la raíz como lanzadores de conveniencia.
