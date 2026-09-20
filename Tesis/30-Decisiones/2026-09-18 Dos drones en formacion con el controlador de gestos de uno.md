---
fecha: 2026-09-18
estado: vigente
afecta: tesis
---
## Decisión
Los dos Crazyflies se vuelan con el vocabulario de gestos de cuerpo usando **el mismo controlador de un dron** (`controllers/single_drone/camera/control_camara_dron1.py --dron ambos`). La coordinación entre los dos vive en `controllers/two_drones/formacion_camara.py` (`VueloFormacion`), que ofrece la interfaz de vuelo de un dron sobre dos. Los dos hacen lo mismo, en formación.

## Contexto
El controlador de dos drones que existía (`control_dos_drones_camara_multiprocessing.py`) usa gestos de **mano** y una webcam cercana: desde la cámara IP del techo, a 5 m, una mano ocupa unos 15 px y no se puede leer. El operador pidió volar los dos con los gestos dinámicos y el controlador ya validado con uno.

Opciones consideradas:

1. Portar el vocabulario de cuerpo al controlador multiproceso de dos drones. Duplica el bucle de cámara, el reconocedor, el seguimiento PTZ y el registro, que ya están probados en el de uno.
2. Mover el bucle y el reconocedor a `shared/` para que lo importen los dos. Es la salida limpia a largo plazo, pero es una refactorización grande a mitad de la campaña de vuelos.
3. **(Elegida)** Un adaptador de formación en `two_drones/` con la interfaz que el controlador ya espera, compuesto desde el controlador.

Sobre las reglas de `AGENTS.md`: la coordinación de dos Crazyflies está en `two_drones/` (regla 2) y `formacion_camara.py` **no importa nada de `single_drone/`**: recibe los vuelos ya construidos y los trata por su interfaz. El controlador de un dron importa de `two_drones/`, que es la dirección permitida y ya tenía precedente (`highlevel_flight.py` sobre el backend de la cruz). El archivo del controlador no *requiere* dos drones: `--dron ambos` es una opción.

Qué significa cada orden con dos drones se decidió así: despegar, aterrizar, paro y emergencia, los dos; direcciones, la misma velocidad a los dos; seguir el marker, anclas repartidas a ±50° de la dirección media para que queden a 0.69 m y no a 15 cm; orbitar, los dos en el mismo círculo **en oposición**, regulando la velocidad de cada uno según el desfase.

## Consecuencias
- `--dron` acepta `1`, `2` o `ambos`; `ambos` exige `--backend robotat` y dos Crazyradio.
- `VueloRobotat.orbit_marker` acepta `escala_velocidad`.
- Seguridad: `SupervisorSeparacion` aterriza a los dos por debajo de 30 cm; no se despega a menos de 50 cm; si uno deja de volar, el otro aterriza.
- Pendiente: validación en vuelo. Si se adopta como forma estable de volar dos drones, reconsiderar la opción 2.
