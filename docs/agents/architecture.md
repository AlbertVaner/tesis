# Arquitectura actual

## Flujo principal

```text
web/ o lanzadores
        |
        +---- controllers/single_drone/{buttons,camera,flowdeck}/
        +---- controllers/two_drones/
        +---- controllers/joystick/
                         |
                         +---- controllers/shared/
                         +---- external/gesture_detection/
                         +---- cflib, cámara, MQTT/mocap
                         v
                 results/data/ y results/graphs/
```

`controllers/two_drones/` mantiene juntos los entrypoints duales, backend high/low-level, protocolo multiproceso, Flow Deck, logging y análisis. Así, todo lo relacionado con dos Crazyflies tiene una sola raíz operativa.

`controllers/single_drone/` se divide por interfaz: botones, cámara y Flow Deck. El panel individual reutiliza tipos y protecciones de `two_drones/`; no duplicar esa lógica.

`controllers/joystick/` y las interfaces gráficas reutilizan `controllers/shared/gui_pdf_capture.py`. `web/server.py` todavía carga partes de `archive/legacy/` por compatibilidad.

## Dirección permitida

- UI/lanzadores -> controladores -> integraciones externas.
- Controladores -> resultados.
- Web -> controladores.
- Nunca: detección gestual -> controladores, controladores -> web, runtime -> tesis.

Los archivos `control_dron_camara.py` y `control_dos_drones_camara.py` se conservan en la raíz como lanzadores de conveniencia.
