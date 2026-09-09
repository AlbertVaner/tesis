# Captura RTSP y sincronización

Estado: `[implementado]` — `src/mapeo3d/capture/` implementa lectura, descarte,
reconexión, estadísticas y **sincronización multicámara**.

## Responsabilidad

Entregar, para cada cámara, un flujo de frames con **marca de tiempo de llegada** y sin acumular retraso. Nada más. `capture/` no sabe qué es una persona.

## El problema real no es leer el stream, es no acumular latencia

Un cliente RTSP ingenuo con OpenCV (`cv2.VideoCapture(url)` y `read()` en el bucle principal) parece funcionar y va acumulando retraso: el decodificador mantiene una cola y cada `read()` devuelve el frame más viejo, no el más reciente. En un lazo de control eso se traduce en un retraso creciente que nadie sospecha porque la imagen se ve bien.

Reglas para evitarlo:

1. **Un hilo por cámara**, dedicado exclusivamente a leer y descartar.
2. El hilo guarda **solo el último frame** en una variable protegida. Si llega uno nuevo antes de que el consumidor tome el anterior, el anterior se pierde. Es lo correcto: un frame viejo no sirve.
3. El consumidor nunca bloquea al lector.
4. Reducir el buffer del decodificador en origen. Con FFmpeg: `rtsp_transport=tcp`, `fflags=nobuffer`, `flags=low_delay`, `buffer_size` mínimo. Con OpenCV, `CAP_PROP_BUFFERSIZE=1` (no siempre lo respeta el backend, por eso el hilo descartador es obligatorio y no opcional).
5. **Reconexión automática.** Un stream RTSP de cámara de consumo se cae. El cliente debe reconectar solo y registrar la interrupción, no morirse.

## Marca de tiempo

La marca de tiempo de un frame es **el instante en que llegó al PC de captura**, tomada con un reloj monotónico, en el hilo lector, inmediatamente después de decodificar.

No se usa el reloj interno de la cámara ni el timestamp del OSD. Las cámaras IP de consumo no tienen sincronización por hardware y sus relojes derivan.

### El reloj es `perf_counter`, no `monotonic`

No es un detalle de estilo. En Windows **`time.monotonic()` avanza a saltos de
15.6 ms**, y la tolerancia de emparejamiento entre cámaras es de 17 ms: la
rejilla del reloj sería casi tan gruesa como la decisión que hay que tomar con
ella, y el emparejamiento por vecino más cercano dejaría de significar nada.

Medido en la máquina de desarrollo (Windows 11):

| reloj | resolución declarada | salto mínimo real |
|---|---|---|
| `time.monotonic()` | 15.625 ms | **15.0 ms** |
| `time.perf_counter()` | 0.0001 ms | **0.0001 ms** |

`perf_counter` es igual de monotónico (`get_clock_info().monotonic == True`) y
no ajustable. Todo `capture/` lo usa a través de `_ahora()`. **No mezclar los
dos relojes**: restar un `time.monotonic()` de una marca de frame da basura.

Esto introduce un error: el tiempo de llegada incluye exposición, codificación, red y decodificación, que no son idénticos entre cámaras. Pero ese sesgo es **aproximadamente constante por cámara**, así que se puede medir una vez y compensar. El jitter, que es lo que no se puede compensar, es pequeño con las cámaras cableadas.

## Sincronización entre cámaras

`[implementado]` en `src/mapeo3d/capture/sync.py`: `MultiCameraSync`.

Estrategia: **emparejamiento por vecino más cercano en tiempo**, con ventana de tolerancia.

- La referencia `t_ref` es el instante más reciente que **todas las cámaras al día ya cubrieron** — el mínimo de sus frames más nuevos. Así el vecino más cercano se busca hacia los dos lados en lugar de quedar sesgado al pasado. Cuesta hasta un periodo de frame de latencia.
- De cada cámara se toma el frame cuya marca esté más cerca de `t_ref`.
- Si la diferencia supera la tolerancia, esa vista **no participa**. Es preferible triangular con 4 vistas buenas que con 6 donde 2 están desfasadas.
- Una cámara **rezagada** —más de `espera_maxima_s` por detrás— deja de fijar la referencia. Sin eso, una sola cámara caída detendría a las otras cinco.

### El buffer vive en el sincronizador, no en `CameraStream`

`CameraStream` guarda sólo el último frame a propósito, y ese contrato es lo que evita que se acumule latencia. Pero el vecino más cercano a `t_ref` puede ser el frame **anterior** al último, así que hace falta una historia corta. Se guarda en `MultiCameraSync` (12 frames por cámara, ~0.4 s a 30 fps) sin tocar la garantía de `CameraStream`.

Por la misma razón, `MultiCameraSync` hace **una sola lectura por cámara y vuelta**: `CameraStream` no tiene cola, así que insistir no traería nada, y vaciar una cola inexistente sólo serviría para saltarse instantes en silencio.

### Lo que la tolerancia NO puede detectar

**Un sesgo constante por cámara pasa completamente desapercibido.** Con dos cámaras a la misma tasa y periodo `T`, la distancia al vecino más cercano es `min(d mod T, T − d mod T)`, que **nunca supera `T/2`** por grande que sea el sesgo real `d`. Medido a 30 fps (`T/2` = 16.7 ms, justo por debajo de la tolerancia de 17 ms):

| sesgo real | vecino más cercano | ¿entra? |
|---|---|---|
| 5 ms | 5.0 ms | sí |
| 40 ms | 6.7 ms | sí |
| 120 ms | 13.3 ms | sí |
| **500 ms** | **0.0 ms** | **sí** |

Una cámara medio segundo atrasada se empareja informando desfase **cero**. Tres consecuencias:

1. **La tolerancia sirve para rechazar cámaras paradas o que van a otra tasa**, no para rechazar desfases. Ése es su trabajo real.
2. El sesgo hay que **medirlo aparte y declararlo**: `MultiCameraSync(..., sesgos={"cam2": 0.040})` lo resta de la marca de llegada. La marca cruda queda en `VistaSincronizada.timestamp_llegada` para poder auditar.
3. Queda un error **irreducible** de hasta `T/2` sin sincronización por hardware: a 30 fps son ±16.7 ms, que con la muñeca a 2 m/s son **±3.3 cm**. Es el suelo de exactitud del sistema para puntos rápidos, y hay que reportarlo como tal.

Cómo medir el sesgo: un evento visible por todas las cámaras a la vez —un flash, una palmada, un LED conmutado— y comparar en qué frame aparece en cada una. `[planeado]` como app.

### Cuánto error introduce el desfase

Un desfase `Δt` entre dos vistas de un punto que se mueve a velocidad `v` produce un error de posición del orden de `v · Δt`:

| Escenario | Δt | v muñeca | Error |
|---|---|---|---|
| Wi-Fi, 15 fps | ~33 ms | 2 m/s | ~6.7 cm |
| Ethernet, 30 fps | ~5 ms | 2 m/s | ~1 cm |

Por eso el cableado importa tanto: no es comodidad, es exactitud. Ver [hardware.md](hardware.md).

## Frecuencia y resolución

Configurar el stream principal a **1280×720 a 30 fps**, no a resolución completa.

El razonamiento: el backend de pose reescala la imagen a unos 256×256 internamente, así que los megapíxeles adicionales no compran calidad de landmarks — sólo cuestan decodificación y ancho de banda, y la decodificación es el cuello de botella cuando hay seis streams.

La resolución completa se reserva para las capturas de calibración, donde cada píxel sí importa.

## Verificación obligatoria del frame rate

**Nunca confiar en los fps que declara la configuración de la cámara.** Con la visión nocturna apagada —que es obligatorio, ver [hardware.md](hardware.md)— la exposición automática puede bajar el frame rate por su cuenta en luz escasa. El síntoma es invisible: la imagen se ve bien y se reciben la mitad de los frames.

Toda sesión debe registrar los **fps realmente recibidos**, contando frames en el hilo lector, y compararlos con los esperados. Una discrepancia mayor al 10 % invalida la sesión.

## Credenciales

Las URLs RTSP llevan usuario y contraseña. **Nunca deben aparecer en logs, mensajes de error, nombres de archivo ni en el repositorio.** Se leen de un archivo local ignorado por git o de variables de entorno. Al registrar o mostrar una URL, enmascarar las credenciales.

Formatos por modelo en [hardware.md](hardware.md).

## Usar el teléfono como cámara

Para pruebas tempranas, un teléfono con una app de cámara IP (IP Webcam, DroidCam
y similares) expone un stream MJPEG o RTSP por la red local y **se conecta igual
que cualquier otra cámara**: es una URL más.

Sirve perfectamente para desarrollar el pipeline y para tener una segunda vista
con la que empezar a triangular sin esperar al hardware definitivo. No sirve para
producir datos de la tesis: los intrínsecos cambian si el teléfono se mueve o si
la app reajusta el zoom, y no hay forma de fijarlo de manera reproducible.

## Interfaz implementada

`[implementado]` en `src/mapeo3d/capture/stream.py`:

```
CameraStream(url, name, *, reconnect_after_s, open_timeout_ms, prefer_tcp)
    .start() / .stop()          arranque y parada del hilo lector
    .read()        -> (frame, timestamp) o None si no hay frame NUEVO
    .read_latest() -> (frame, timestamp) aunque ya se haya leído (sólo para vista)
    .stats         -> StreamStats: fps_recibidos, descartados, reconexiones
    .resolucion, .fps_declarados, .conectado
```

Admite una URL RTSP, una URL HTTP/MJPEG o un índice entero de webcam local.
Sirve también como gestor de contexto (`with CameraStream(...) as s:`).

`stats` no es un extra de depuración: es la fuente de la verificación de frame
rate descrita arriba y debe registrarse en cada sesión.

`[implementado]` en `src/mapeo3d/capture/urls.py`: `build_rtsp_url()` arma la URL
por modelo y `mask_url()` la enmascara para poder registrarla.

`[implementado]` en `src/mapeo3d/capture/config.py`: `load_config()` lee
`config/cameras.local.yaml`.

**Credenciales por cámara.** En las Tapo la "cuenta de cámara" se crea por
dispositivo, así que lo normal es que cada cámara tenga usuario y contraseña
distintos. La precedencia, de mayor a menor, es:

1. `CAM_<NOMBRE>_USER` / `CAM_<NOMBRE>_PASSWORD` del entorno.
2. `user` / `password` dentro de la entrada de esa cámara en el YAML.
3. `CAM_USER` / `CAM_PASSWORD` del entorno.
4. Bloque `credentials` global del YAML.

Una cámara sin credenciales resolubles hace fallar la carga con un mensaje que
nombra las cuatro vías. Es preferible fallar al arrancar que descubrirlo como
un timeout de conexión.

`[implementado]` en `src/mapeo3d/capture/sync.py`:

```
MultiCameraSync(streams, *, tolerancia_s, min_vistas, historia,
                espera_maxima_s, sesgos)
    .next(timeout_s) -> ConjuntoSincronizado | None
    .stats           -> SyncStats
    iterable: for conjunto in sync: ...

ConjuntoSincronizado
    .t_ref, .vistas {nombre: VistaSincronizada}, .descartadas {nombre: desfase}
    .n_vistas, .desfase_max_s, .frames()
    conjunto["cam1"], "cam1" in conjunto

VistaSincronizada
    .camera, .frame, .timestamp, .desfase_s/.desfase_ms, .timestamp_llegada
```

Acepta cualquier objeto con `.name` y `.read()`, así que se prueba entero sin
cámaras: `tests/test_sync.py` reproduce jitter de red, una cámara a la mitad de
fps, una que se cae a mitad de sesión y el sesgo constante.

`SyncStats` **no es depuración**: con seis cámaras, saber cuál se queda fuera y
cuántas veces es lo que distingue un problema de red de una cámara mal
configurada. Una que participe mucho menos que el resto casi siempre está
entregando a menos fps de los que declara.

**Costo de una cámara caída:** el emparejamiento se detiene `espera_maxima_s`
(0.25 s por defecto, ~7 conjuntos a 30 fps) mientras se decide que está caída,
y después continúa con las demás. Bajarlo acorta la pausa y hace el sistema más
nervioso ante un hipo pasajero.
