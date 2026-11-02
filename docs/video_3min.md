# Vídeo de presentación (3 min): guion y plan de grabación

Borrador para grabar y editar el vídeo del proyecto. Los tiempos suman 3:00 a
un ritmo de narración de unas 130 palabras por minuto. La narración está
escrita para leerse en voz alta; cambiarla con libertad.

## 1. Qué grabar

Todo sale de **una sola sesión** del controlador por cámara con las seis
cámaras, el vocabulario completo y el **dron simulado** (`--volar --dry-run`:
no abre radio ni mocap, pero la máquina de modos cree que el dron despega y
aterriza, así que el panel muestra cada orden ejecutada). Desde la raíz:

```powershell
python .\controllers\single_drone\camera\control_camara_dron1.py --multicamara --reconocedor vocabulario --backend robotat --volar --dry-run --grabar-video --grabar-hd
```

y, al terminar, **recomponer la interfaz en HD** con la carpeta que imprime al
cerrar:

```powershell
python .\external\gesture_detection\renderizar_sesion_hd.py results\captures\control_camara_dron1\<día>\sesion_HHMMSS --por-camara
```

Resultado en `results/captures/control_camara_dron1/<día>/`:

| archivo | qué es | para qué en la edición |
|---|---|---|
| `sesion_HHMMSS/sesion_hd.mp4` | **la interfaz en 1080p**: cámara activa en HD con el esqueleto, las seis en miniatura, gesto, órdenes, estado del dron y leyenda del vocabulario | plano principal de la demo |
| `sesion_HHMMSS/camN_hd_esqueleto.mp4` | cada cámara en 1080p con el esqueleto (con `--por-camara`) | mosaico 3×2, cortes de ángulo |
| `sesion_HHMMSS/camN_hd.mp4` | cada cámara en alta resolución, sin dibujos | intro, cierre, planos "bonitos" |
| `sesion_HHMMSS.mp4` | la interfaz tal como se vio en vivo (VGA) | respaldo |

### Cómo se consigue HD sin perder fluidez

Las cámaras siguen en VGA (`CAM_SUBTYPE=1`) para que el reconocimiento vaya
fluido. Las Amcrest sirven **dos streams a la vez**, y `--grabar-hd`:

1. graba el stream principal de cada cámara con ffmpeg **sin decodificarlo ni
   recodificarlo** (casi nada de CPU; sí unos 4-8 Mbit/s de red por cámara),
   marcando cada cuadro con la hora a la que llegó (`camN_hd.mkv`);
2. guarda, con el mismo reloj, lo que hizo el sistema en vivo: el esqueleto de
   cada cámara, la cámara activa, el gesto, el estado del dron y cada orden
   (`render.jsonl`).

`renderizar_sesion_hd.py` junta las dos cosas después: **no reconoce nada otra
vez**, dibuja sobre la imagen HD exactamente lo que el sistema hizo en vivo.
Tarda varios minutos por cada minuto de sesión (decodifica seis vídeos HD).

**El desfase.** El stream HD llega algo más tarde que el VGA, así que el
renderizador lo estima solo (correlaciona el movimiento de la imagen con el de
los brazos) e imprime el valor. Si el esqueleto se ve adelantado o atrasado
respecto al cuerpo, probar a mano con un trozo corto y luego renderizar todo:

```powershell
python .\external\gesture_detection\renderizar_sesion_hd.py <carpeta> --desde 30 --hasta 40 --desfase 0.3
```

Si el esqueleto queda desplazado siempre igual (no adelantado ni atrasado,
sino corrido de sitio), el stream principal y el VGA no tienen el mismo
encuadre: avisar, eso no se arregla con el desfase.

Necesita ffmpeg (ya instalado con `winget install Gyan.FFmpeg`). Para grabar
sólo las cámaras en HD, sin reconocedor: `python .\external\gesture_detection\grabar_camaras_hd.py`.

Además, en `results/data/` queda el CSV de la sesión con el instante de cada
gesto, útil como índice para encontrar cada gesto al editar.

Teclas durante la grabación: `1`-`6` fijan una cámara (para forzar un plano),
`0` vuelve a la elección automática, `espacio` pausa el seguimiento PTZ, `q`
termina y cierra los vídeos. **Cerrar siempre con `q`**: matar el proceso deja
los vídeos sin cerrar.

Si el equipo no da abasto, quitar `--grabar-video` (el HD casi no cuesta CPU:
el trabajo pesado se hace después, al renderizar), o usar `--sin-ptz` si las
cámaras ya encuadran el área.

### Antes de grabar

- [ ] Las seis cámaras responden y **ninguna tiene espejo** (Flip sin Mirror):
      la imagen espejada invierte IZQUIERDA/DERECHA y rompe los gestos.
- [ ] Probar 30 s sin grabar, con el mismo comando sin `--grabar-*`, y mirar que
      las seis miniaturas tengan imagen y fps.
- [ ] Ropa que contraste con el fondo; brazos libres.
- [ ] Tomas de vuelo real con los Crazyflie: se graban aparte, con el
      operador presente y la autorización de siempre (no forman parte de esta
      sesión simulada). Un móvil en trípode basta.

### Orden de gestos en la sesión (unos 4 min de material bruto)

Hacer cada gesto **dos veces**, con 3 s quieto (brazos abajo) entre uno y otro,
para tener donde cortar. El vocabulario arranca en modo dinámico.

| # | gesto | cómo se hace | qué hace (con el dron simulado) |
|---|---|---|---|
| 1 | señalero | dos brazos arriba, oscilar los antebrazos 3-4 veces, codos altos | DESPEGAR (en el suelo) |
| 2 | ven acá | llamar con una mano a la altura del pecho, 3 veces | SEGUIR el marker 65 (el que lleva el operador) |
| 3 | arco | subir los dos brazos por los lados hasta arriba, despacio | PIRUETA |
| 4 | círculo | una mano, todo el brazo, círculo grande al frente, 2 vueltas | ORBITAR alrededor del marker 65 |
| 5 | aplaudir | 3-4 aplausos a la altura del pecho | pasa a MODO ESTÁTICO, hover |
| 6 | ARRIBA | un brazo estirado hacia arriba, sostenido 2 s | sube mientras se sostiene |
| 7 | ABAJO | un brazo estirado abajo y al frente | baja |
| 8 | ADELANTE | un brazo estirado al frente | avanza (hacia donde mira el operador) |
| 9 | ATRAS | un brazo estirado hacia atrás | retrocede |
| 10 | IZQUIERDA | un brazo estirado a la izquierda | izquierda |
| 11 | DERECHA | un brazo estirado a la derecha | derecha |
| 12 | aplaudir | igual que el 5 | vuelve a MODO DINÁMICO |
| 13 | señalero | igual que el 1 | ATERRIZAR (en el aire) |
| 14 | señalero + X | despegar otra vez y cruzar los brazos en X **sobre la cabeza**, 1 s | PARO: aterriza y bloquea hasta soltar |
| 15 | multicámara | caminar despacio alrededor del área, girándose | la cámara activa cambia a la que mejor ve la cara |

Opcional, para "todos los gestos": los **gestos de mano 2D** del modo
anterior (DESPEGAR, ATERRIZAR, STOP, direcciones, SEGUIR_MARKER…) se graban
con una webcam cercana:

```powershell
python .\controllers\single_drone\camera\control_camara_dron1.py --reconocedor manos --grabar-video
```

Y si hay tiempo, la **formación de dos drones** con el mismo vocabulario,
también simulada:

```powershell
python .\controllers\single_drone\camera\control_camara_dron1.py --multicamara --reconocedor vocabulario --backend robotat --dron ambos --volar --dry-run --grabar-video --grabar-hd
```

### Montaje formal de una sesión

`external/gesture_detection/editar_video_resumen.py <carpeta de la sesión>`
monta `resumen_gestos.mp4`: portada con el título, la cámara activa en HD sin
nada encima del operador, fundidos al cambiar de cámara, un cuadro abajo a la
derecha con el esqueleto y un rótulo con cada gesto y su orden. `--desde` y
`--hasta` (segundos de la sesión) recortan; `--sin-portada` la quita.

Encima del esqueleto va una **vista 3D del Robotat** con los drones (del CSV de
cada dron), el marker 65 y una figura del operador reconstruida a partir de él
(del CSV de la sesión por cámara), más las cámaras OptiTrack e IP. Las
posiciones de las cámaras y del área están en
`external/gesture_detection/visualization/escena_robotat.json` y son
**aproximadas** (no hay medidas); corregirlas ahí cuando se midan.
`--sin-escena` la quita.

**Tu esqueleto en 3D.** `external/gesture_detection/reconstruir_cuerpo.py <carpeta de la sesión>`
deja `cuerpo3d.npz`: el esqueleto 3D de MediaPipe sobre el vídeo HD de la cámara
activa, girado según el poste de esa cámara (`escena_robotat.json`) y colocado
con la muñeca sobre el marker 65. Si existe, la vista 3D del vídeo y la
animación de MATLAB (`exportar_vuelo_matlab.py` lo incluye en el `.mat`)
dibujan ese esqueleto en vez de la figura esquemática. Es una cámara a la vez,
no una triangulación.

Varias sesiones en un solo vídeo: pasar las carpetas en orden; `--hasta`
acepta un segundo de corte por sesión (`--hasta 99 77`).

### Vuelo de los drones animado en MATLAB

Si en la grabación los drones se ven pequeños, el mismo vuelo se puede contar
con una animación 3D: drones, estelas, marker 65, gesto y orden en curso. Tras
volar (con hardware, autorizado y presente el operador):

```powershell
python .\controllers\shared\exportar_vuelo_matlab.py
```

y en MATLAB, con la ruta que imprime: `addpath('controllers/shared');
animar_vuelo_robotat('results/data/dron_robotat/<día>/vuelo_<HHMMSS>.mat')`.
Detalle en `controllers/single_drone/robotat/README.md`, "Animar un vuelo en
MATLAB".

## 2. Guion

| tiempo | imagen | narración |
|---|---|---|
| **0:00-0:15** gancho | Vuelo real: el operador hace el señalero y el Crazyflie despega. Corte a mosaico 3×2 de las seis cámaras limpias. | «Sin control remoto, sin teclado. Solo con el cuerpo. Esto es lo que construimos.» |
| **0:15-0:40** problema | Plano general del Robotat con los drones en el suelo. | «Controlar un dron normalmente exige un mando y entrenamiento. Nuestra pregunta fue: ¿puede una persona dirigir uno o varios drones con gestos naturales, desde cualquier punto de la sala, sin llevar nada encima?» |
| **0:40-1:05** montaje | Mosaico de las seis cámaras con esqueleto; inserto de un Crazyflie y del mocap. | «Usamos drones Crazyflie dentro del Robotat, cuyo sistema de captura de movimiento le dice a cada dron dónde está; la posición la controla el propio firmware. Alrededor, seis cámaras IP que siguen al operador moviendo su pan y tilt. En cada una, MediaPipe estima el esqueleto en 3D.» |
| **1:05-1:20** multicámara | Interfaz: el operador camina y la miniatura activa cambia (gesto 15). | «Las seis cámaras miran a la vez, pero manda la que mejor ve la cara del operador. Si te giras, el control pasa a otra cámara sin que lo notes.» |
| **1:20-1:50** modo dinámico | Gestos 1-4, interfaz + corte a la cámara de frente. Rótulo con el nombre de cada gesto. | «El vocabulario tiene dos modos. En el dinámico, los gestos son movimientos: el señalero despega y aterriza, "ven acá" hace que el dron siga el marcador que llevas, el arco dispara una pirueta y el círculo lo pone a orbitar a tu alrededor. Se reconocen comparando la trayectoria de los brazos con plantillas grabadas.» |
| **1:50-2:15** modo estático | Gesto 5 (aplauso), luego 6-11 en cortes rápidos de 2 s, rótulo con la flecha. | «Un aplauso cambia al modo estático: ahora el brazo es un joystick. Arriba, abajo, adelante, atrás, izquierda y derecha, siempre desde el punto de vista del operador, no del dron.» |
| **2:15-2:30** seguridad | Gesto 14: la X sobre la cabeza, rótulo "PARO". | «Y siempre, en cualquier modo, los brazos en X sobre la cabeza son el paro de emergencia: el dron aterriza y no obedece nada más hasta que bajas los brazos.» |
| **2:30-2:45** resultados | Vuelo real o formación de dos drones; capturas de las gráficas de `results/graphs/dron_robotat/`. | «Con el mismo vocabulario volamos uno o dos drones en formación, y cada sesión deja registros y gráficas para medir el seguimiento.» |
| **2:45-3:00** cierre | Mosaico limpio con el operador haciendo el señalero; título y nombres. | «Gestos naturales, varias cámaras y un firmware que cierra el lazo: un paso hacia drones que se dirigen como se dirige a una persona.» |

### Consejos de edición

- `sesion_hd.mp4` y los `camN_hd_esqueleto.mp4` salen del mismo reloj: empiezan
  y terminan a la vez, se alinean al inicio sin más.
- Para el mosaico 3×2, usar los `camN_hd.mp4` limpios en la intro y los de esqueleto en la
  explicación técnica: el contraste cuenta solo lo que hace el sistema.
- Rotular el nombre de cada gesto en el momento en que la interfaz lo muestra
  en verde (confirmado), no cuando empieza el movimiento.
