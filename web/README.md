# Panel web de experimentos Robotat

Desde la raíz del repositorio, con las dependencias existentes del proyecto:

```powershell
.\.venv\Scripts\python.exe .\web\server.py --dry-run
```

Abrir http://127.0.0.1:8765. La simulación es el modo predeterminado y no abre
radios, MQTT ni cámara. No requiere npm ni dependencias web adicionales.

## Configurar y operar

1. Elegir nombre, entorno y dron 1, dron 2 o ambos.
2. Seleccionar botones, gestos de manos o joystick con marker.
3. Elegir registro CSV y generación automática de gráficas. Las casillas de
   resultados definen las gráficas automáticas al guardar la configuración.
4. Ejecutar preflight. Guarda la configuración visible y conecta únicamente
   los drones elegidos. No despega. La configuración queda fija hasta finalizar.
5. Para manos o joystick, activar la entrada. Para el joystick, establecer cero
   con el marker nivelado; después despegar mediante los botones.
6. Aterrizar o finalizar la sesión. Finalizar cierra la entrada, aterriza si
   corresponde, cierra conexiones y genera las gráficas seleccionadas.

### Manos

Una mano: seleccionar izquierda o derecha; controla todos los drones incluidos
en la sesión. Dos manos: asignar cada mano a dron 1, dron 2, ambos o sin asignar.
Se puede controlar un mismo dron con ambas manos. Órdenes idénticas no duplican
el movimiento; órdenes contradictorias bloquean la actualización. Un puño
asignado a un dron en vuelo solicita emergencia para la sesión completa.

En Robotat real, enseñar únicamente el dedo medio activa el seguimiento
tridimensional del marker 65 para el destino de esa mano. El símbolo de rock —índice
y meñique extendidos, con el pulgar abierto o cerrado— lo detiene y deja hover.
Cada dron mantiene una separación de 0.45 m respecto al marker y sigue X, Y y Z.
El seguimiento se limita a 0.10 m/s, usa pasos de 0.025 m y una esfera de
exclusión de 0.30 m entre drones. Los demás gestos de movimiento se ignoran
mientras sigue al marker, pero el puño mantiene prioridad de emergencia. La
pérdida de una pose cancela el seguimiento; el recorrido del marker no está
limitado respecto al origen. La lista de ensayo muestra ambos gestos, pero la simulación no abre
MQTT y por eso no mueve una pose ficticia del marker.

La cámara conserva el detector, filtrado y confirmación temporal existentes.
La vista Cámara muestra las manos anotadas. En simulación se eligen gestos
mediante listas, sin abrir la cámara. Las órdenes tienen pausa de 1.25 s por dron.

### Joystick con marker

Introducir el ID publicado en Robotat y elegir el destino: dron 1, dron 2 o ambos,
siempre dentro de la selección de la sesión. El adaptador filtra `mocap/all` por
ese ID y reutiliza los signos y zonas muertas del controlador de marker vigente.
Cambiar el ID requiere finalizar la sesión. Reiniciar la entrada exige otro cero.

El panel compone esta entrada con el backend high-level: actualiza objetivos
cada 250 ms, con incrementos XY de hasta 3 cm y Z de hasta 8 cm, sujetos a los
límites existentes del backend; requiere validación física antes de su uso experimental.
Con ambos drones, el desplazamiento se aplica a ambos conservando la diferencia
entre sus objetivos. Bajar el marker más de 10 cm respecto al cero durante 0.5 s
solicita aterrizaje. En simulación, los controles de ensayo envían una actualización
por pulsación; el aterrizaje se ensaya mediante el botón Aterrizar.

### Parada y pérdida de entrada

El botón rojo o Escape solicitan emergencia sin esperar la cola de operaciones.
La emergencia queda enclavada; finalizar y repetir preflight para otra sesión.
Detener entrada deja de emitir órdenes y mantiene el objetivo de vuelo actual.
Si el panel deja de enviar heartbeat por más de 5 s mientras hay vuelo, se
solicita aterrizaje. La cámara sin respuesta por más de 2 s y la pérdida sostenida
del marker (pose de más de 0.75 s, seguida de 1 s de espera) también solicitan
aterrizaje. Si la orden de aterrizaje por fallo de entrada falla, se solicita
emergencia. La ausencia de manos en una cámara que sigue entregando imágenes
mantiene el objetivo; no se interpreta como fallo de cámara.

## Hardware real

```powershell
.\.venv\Scripts\python.exe .\web\server.py --hardware
```

Esta opción habilita Robotat real en la lista, pero conserva Simulación por
defecto. Sólo un preflight seleccionado como real abre hardware. No usar otro
controlador simultáneamente sobre las mismas radios. Las URI, tópicos de drones,
ganancias y límites proceden del backend canónico; no se modifican desde esta UI.

Con Flow Deck conectado se conserva la exclusión de flujo óptico y ToF de
`controllers/shared/flowdeck_feedback.py`. Firmware sin `range.disable` bloquea
preflight cuando el deck lo requiere. La adaptación de firmware está descrita en
`external/crazyflie_firmware/README.md`; este panel no compila ni flashea firmware.
La validación automatizada del panel sólo cubre simulación, no vuelo real.

El servidor escucha únicamente en esta computadora por defecto. La opción
`--host 0.0.0.0` existe para una red de laboratorio confiable; no hay autenticación
de usuarios ni TLS y no se debe exponer directamente a Internet. El token de
control y la comprobación de origen previenen solicitudes cruzadas de otras webs.

## Archivos y significado de las mediciones

- Configuración y CSV: `results/data/panel_web/AAAA-MM-DD/<sesión>/`.
- Gráficas: `results/graphs/panel_web/AAAA-MM-DD/<sesión>/<exportación>/`.
- PNG y PDF disponibles en Resultados; exportaciones sucesivas no sobrescriben.
- Desactivar CSV omite la telemetría persistida del panel. Se conserva `sesion.json`
  y los datos en memoria permiten exportar gráficas durante esa ejecución.
- Los logs propios del backend real siguen su política existente, independiente
  de la casilla CSV del panel. No se desactivan registros de vuelo del controlador.

El CSV registra posición MoCap XYZ, objetivo XYZ, error EKF, batería, antigüedad
MoCap/EKF y eventos de órdenes/gestos. `processing_ms` mide procesamiento dentro
del programa; `mocap_age_ms` y `ekf_age_ms`, edad de la última muestra al leerla.
`source_latency_ms` sólo existe si el publicador incluye una marca de tiempo
compatible y depende de la sincronización de relojes. Ninguna es latencia de
radio ni tiempo de respuesta física. El tiempo mostrado como respuesta del panel
mide HTTP desde el navegador y se muestra por separado. Valores no disponibles
quedan vacíos; la simulación se identifica en configuración y títulos de gráficas.

## Arquitectura y comprobación sin hardware

`web/server.py` expone HTTP y archivos estáticos. La coordinación vive en
`controllers/two_drones/experiment_session.py`; configuración, manos y registro
pertenecen a esa categoría porque admiten coordinación dual. `marker_input.py`
permanece en `controllers/joystick/`. La web no importa controladores legacy.
Las pruebas HTTP, entrada y resultados cruzan categorías y por eso viven en
`tests/integration/test_web_panel.py`.

```powershell
.\.venv\Scripts\python.exe -m compileall -q controllers external web control_dron_camara.py control_dos_drones_camara.py
.\.venv\Scripts\python.exe -m unittest discover -s tests/integration -p test_web_panel.py -v
```

Las pruebas usan servidor efímero y directorios temporales. Verifican selección,
asignaciones, rechazo de conflictos, cero de marker, emergencia, heartbeat,
protección de solicitudes y descargas CSV/PNG/PDF. No abren UI, cámara, MQTT ni radio.
