---
fecha: 2026-09-09
estado: vigente
afecta: tesis, mapeo3d, gesture_detection
---
## Decisión
Se pospone la calibración de las cámaras y, por tanto, la triangulación multivista. La percepción del operador pasa a ser **monocular**, con una sola cámara Amcrest que **sigue a la persona moviendo su pan/tilt**. El seguimiento se implementa en `external/gesture_detection/ptz/`.

## Contexto

El profesor pidió que la cámara siga al operador cuando se mueve por el área del Robotat. Esa petición es incompatible con la triangulación tal como está diseñada: triangular exige extrínsecos fijos, y `R` y `T` **son** la orientación y posición físicas de la cámara. Cualquier giro del motor los invalida, y según `external/mapeo3d/docs/calibration.md` lo hace **sin ningún síntoma visible**: la imagen se ve perfecta y la triangulación devuelve números plausibles y equivocados.

Se plantearon cuatro salidas:

1. **Seguimiento digital** — cámara fija, recorte que sigue a la persona en software. Preserva los extrínsecos porque pasar de coordenadas del recorte al frame completo es una suma exacta, no una estimación mecánica.
2. **Separar roles** — las cámaras que triangulan quedan fijas y otra distinta hace el seguimiento sin participar en la triangulación.
3. **Recalcular `R` desde los ángulos del motor** — descartada: la API no publica la resolución del encoder, el eje de giro no pasa por el centro óptico (así que `T` también cambia), hay backlash, y no hay forma de asociar una posición reportada a un frame concreto. Con el operador a 3 m, un error angular de 0.6° ya iguala el suelo de exactitud de ±3.3 cm por sincronización.
4. **Posponer la calibración** — la elegida.

El autor decidió que la calibración queda descartada por el momento. Sin extrínsecos que invalidar, la objeción desaparece y el seguimiento físico es viable de inmediato.

La decisión es coherente con el código existente: `probar_vocabulario.py` ya trabaja con los *world landmarks* monoculares de MediaPipe, no con puntos triangulados, así que el reconocimiento de gestos no pierde nada por esta vía.

## Consecuencias

- **La regla "ningún módulo debe emitir comandos PTZ" sigue vigente dentro de `external/mapeo3d/`** y no se relaja: ese subsistema es el de triangulación. Lo que cambia es que el seguimiento PTZ existe, y vive fuera, en `external/gesture_detection/ptz/`.
- **Si se retoma la triangulación, la cámara que sigue no puede ser una de las que triangulan.** La opción 2 de arriba es el camino de vuelta, y `docs/hardware.md` ya contempla cámaras adicionales para vistas cercanas.
- Un preset PTZ **no** rescata una cámara movida: la repetibilidad mecánica no es de nivel sub-píxel. Volver a un preset deja la cámara *cerca*, no *calibrada*. Si se recalibra, hay que recalibrar de verdad.
- Consultar la posición PTZ **por lectura** (`ptz.cgi?action=getStatus`) no mueve nada y queda permitido. Registrar la posición al calibrar y compararla al arrancar sería un detector de movimiento complementario al marcador ArUco de `integrity_check`, más barato porque no necesita el marcador en cuadro.
- El seguimiento usa **control por velocidad**, no por posición absoluta, porque el FOV horizontal de la Amcrest sigue sin medir. Si se mide, se puede cambiar sin tocar el resto.
- Medición que condiciona el diseño y conviene conservar: **una petición HTTP a la cámara cuesta ~304 ms de mediana**. Eso obliga a sacar el I/O del bucle de visión y a mover por pasos acotados en vez de en continuo. Ver `external/gesture_detection/ptz/seguidor.py` y `ptz/control.py`, donde el razonamiento está escrito.

## Pendiente

- Confirmar con el profesor el alcance real: si el operador se queda en el centro del Robotat, la cobertura desde una esquina puede bastar y el seguimiento estaría resolviendo un problema inexistente.
- Medir la repetibilidad de los presets (llevar a una posición, mover, volver, medir el desplazamiento en píxeles). Es la medición que decidiría con un número si la vía de presets sería viable el día que se retome la calibración. Hacerla **ahora**, mientras no hay calibración que perder, sale gratis.
