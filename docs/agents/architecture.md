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

`controllers/shared/` concentra lo que antes se repetía en cada controlador: identidad del Robotat (`robotat.py`), radios y URIs (`radios.py`), configuración del estimador y corte de motores (`crazyflie_link.py`), preparación con Flow deck (`flowdeck_flight.py`), teclado Tk (`tk_keys.py`) y registros CSV (`csv_session.py`). `two_drones/` ya no importa nada de `single_drone/`; la dependencia va sólo de `single_drone/` hacia `two_drones/` y de ambos hacia `shared/`. `controllers/joystick/` y las interfaces gráficas reutilizan `controllers/shared/gui_pdf_capture.py`. `web/server.py` compone `controllers/two_drones/experiment_session.py` y sirve el panel local. La sesión reutiliza el backend high-level para uno o dos drones, `hand_commands.py` para órdenes gestuales y `controllers/joystick/marker_input.py` para leer el joystick. Registro y exportación pertenecen a `session_recording.py`. Consulta `web/README.md` para operación y validación.

`controllers/shared/flowdeck_feedback.py` selecciona realimentación de flujo
óptico/ToF para consumidores de control dual, joystick y Flow Deck individual.
La adaptación externa de firmware necesaria para excluir ToF vive en
`external/crazyflie_firmware/`; no contiene un binario compilado ni flasheado.

`controllers/joystick/marker_follow.py` es la fuente común del seguimiento
tridimensional del marker 65 a 0.45 m. Sólo recibe y transforma poses; los
consumidores de cámara conservan la propiedad de la orden de vuelo. En
high-level, el adaptador dual `camera_marker_runtime.py` convierte el objetivo
en pasos protegidos y aplica una separación mínima de 0.30 m entre drones. Los
controladores Flow Deck convierten la corrección del marco Robotat al marco del
dron antes de pedir velocidad.

## Dirección permitida

- UI/lanzadores -> controladores -> integraciones externas.
- Controladores -> resultados.
- Web -> controladores.
- Nunca: detección gestual -> controladores, controladores -> web, runtime -> tesis.

Los archivos `control_dron_camara.py` y `control_dos_drones_camara.py` se conservan en la raíz como lanzadores de conveniencia.
