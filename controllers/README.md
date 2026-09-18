# Controladores

- `single_drone/buttons/`: panel de botones para un dron, con `--backend {mocap,flowdeck}`.
- `single_drone/hover_flowdeck.py`: hover de un dron sólo con Flow deck, para probar el hardware antes de volar en serio.
- `single_drone/camera/`: `control_camara_dron1.py`, control por cámara y gestos para un dron (manos 2D, cuerpo 3D estático, o el vocabulario completo con dinámicos por DTW; mocap high-level o Flow Deck).
- `two_drones/`: los dos backends de vuelo (`cruz_highlevel_backend.py`, `flowdeck_dual_backend.py`) y todo lo específico de dos drones: botones, cámara, multiprocesamiento, logs y análisis.
- `joystick/`: control mediante marker/mocap usado como joystick.
- `shared/`: utilidades comunes, sin lógica de vuelo propia.


## Teclado de los paneles

Común a los paneles de botones, de uno y de dos drones. Vive en un solo sitio,
`shared/tk_keys.py`.

| tecla | dron 1 | dron 2 |
|---|---|---|
| mover | W/A/S/D | flechas |
| subir y bajar | Espacio y Shift | Re Pág y Av Pág |
| girar | Q y E | Inicio y Fin |
| despegar o aterrizar | Enter | Enter |
| **paro de emergencia** | **R** | **R** |

Enter decide por el estado real del dron, no por un contador de pulsaciones:
despega lo que está en el suelo y aterriza lo que está en vuelo. Con los dos
drones seleccionados y uno en cada estado no hace nada, y lo dice en el registro.

El paro estuvo en `Q` hasta septiembre de 2026 y se movió a `R` al asignar
`Q` y `E` al giro. `R` no tenía uso y queda lejos de las teclas de vuelo.

## Elegir cómo vuela: `--backend`

Los paneles de botones y los controladores por cámara aceptan
`--backend {mocap,flowdeck}`. No hay programas distintos por deck.

| | `mocap` (por defecto) | `flowdeck` |
|---|---|---|
| posición | absoluta, del Robotat | ninguna, sólo flujo óptico |
| geocerca y separación mínima | sí | **no** |
| `--dry-run` | sí | no existe, no hay simulador de deck |
| seguir el marker | sí | no |
| límites de altura y hombre muerto | sí | sí |

Con Flow deck, un paso de movimiento es un pulso de velocidad que se detiene
solo, no un punto al que ir. Con dos drones a la vez **nadie impide que se
acerquen**: el panel lo avisa al conectar.

Consulta `../docs/agents/architecture.md` para las dependencias entre categorías.
