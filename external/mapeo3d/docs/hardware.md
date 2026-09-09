# Hardware, red y montaje

Estado: `[implementado]` como documentación de hechos verificados. El código que la consume es `[planeado]`.

## Situación actual

- **En uso ahora:** TP-Link Tapo C210.
- **Objetivo:** 6 × Amcrest IP4M-1041B, disponibles en la Universidad pero sin acceso en este momento.

El código debe funcionar con ambas y no asumir un modelo. Toda diferencia entre modelos vive en `config/`, no en el código.

## Comparación

| | Tapo C210 | Amcrest IP4M-1041B |
|---|---|---|
| Sensor | 1/2.8" | 1/3" |
| Resolución | 2304×1296 (2K) | 2688×1520 (4MP) |
| **Frame rate** | **15 fps, no configurable** | **30 fps a resolución completa** |
| Lente | f = 3.83 mm, F/2.4 | ~90° declarado |
| **FOV** | **≈ 66° H, 40° V (MEDIDO)** | ≈ 79° H, 46° V (calculado, sin medir) |
| Compresión | H.264 | H.264 y MJPEG |
| Encoder configurable | no | **sí** (resolución, fps, bitrate, I-frame, exposición) |
| Red | Wi-Fi 2.4 GHz únicamente | **Ethernet RJ-45 10/100** + Wi-Fi 2.4 GHz |
| IR nocturno | 850 nm, ~9 m | ~10 m (longitud de onda no publicada; asumir 850 nm) |
| Pan/tilt | motorizado 360°/114° | motorizado |
| RTSP | `rtsp://usr:pwd@ip:554/stream1` (`/stream2` sub) | `rtsp://usr:pwd@ip:554/cam/realmonitor?channel=1&subtype=0` (`subtype=1` sub) |

**Advertencia sobre la hoja de datos de Tapo:** el "360° horizontal / 114° vertical" que aparece en la fila de *field of view* es el **rango del motor**, no el campo de visión del lente. El FOV real es el medido más abajo.

**No mezclar modelos** en una misma sesión de triangulación si se puede evitar: frame rates distintos complican la sincronización sin aportar nada.

## Encuadre: el cálculo que condiciona el montaje

La cobertura vertical a distancia `d` es `2 · d · tan(FOV_v / 2)`.

### FOV de la Tapo C210 — MEDIDO (2026-09-02)

Medición: cámara horizontal a **0.98 m** de altura, sujeto a **2.22 m**, borde
inferior del cuadro a **0.17 m** del suelo. De ahí, `tan(α) = (0.98 − 0.17)/2.22`:

| | Estimado antes | **Medido** |
|---|---|---|
| FOV vertical | 43° | **40.1°** |
| FOV horizontal (derivado, 16:9) | 70° | **65.9°** |
| Cobertura vertical | 0.79 · d | **0.730 · d** |
| Focal equivalente | 1645 px | **1776 px** |

El estimado a partir de la focal y el tamaño nominal del sensor se quedó un 7 %
corto. La diferencia sugiere un sensor algo menor que el 1/2.8" nominal o un
recorte del área activa. **Usar siempre el valor medido.**

El FOV de la **Amcrest sigue sin medir**: sus números son estimaciones del mismo
tipo que fallaron aquí, y hay que repetir esta medición en cuanto haya acceso.

### Distancia mínima para que la persona quepa entera

| Objetivo | Cámara a 0.98 m | Cámara a 1.10 m |
|---|---|---|
| De pie, sin levantar brazos (1.80 m) | d ≥ 2.69 m | d ≥ 3.01 m |
| Con brazos en alto (2.20 m) | d ≥ 3.34 m | **d ≥ 3.01 m** |

La altura óptima es la mitad del alto a cubrir: con 1.10 m se minimiza la
distancia necesaria para el caso exigente.

### Consecuencia para el Robotat: montar en las ESQUINAS

Con el operador en el centro de una planta de 4 × 5 m, la distancia de montaje
depende mucho de dónde se ponga la cámara, y eso decide si la persona cabe:

| Posición | Distancia al centro | Cobertura vertical | Cuerpo entero | Brazos en alto |
|---|---|---|---|---|
| **Esquina** | **3.20 m** | **2.34 m** | **sí** | **sí** |
| Medio del lado corto | 2.50 m | 1.82 m | no | no |
| Medio del lado largo | 2.00 m | 1.46 m | no | no |

(Con la cámara horizontal a 1.10 m de altura y el FOV medido de la Tapo.)

**Las esquinas resuelven el problema de encuadre y las posiciones intermedias no.**
Desde una esquina el cuadro abarca de −0.07 m a 2.27 m: entra el cuerpo completo
con los brazos levantados. Es la diferencia entre que el sistema funcione y que no.

Los ángulos de triangulación entre esquinas, vistos desde el centro, también son
buenos: **77.3°** entre esquinas del lado corto y **102.7°** entre las del lado
largo, ambos dentro o cerca del rango ideal de 60-90°.

**Excepción importante:** las esquinas **opuestas** (A-C, B-D) quedan a 180°, es
decir, sus rayos son colineales y la triangulación con ese par es **degenerada**.
Nunca depender sólo de un par de esquinas opuestas; con tres o más vistas el
problema desaparece.

Plan de montaje que se desprende: **cuatro cámaras en las esquinas** para cuerpo
completo y triangulación, y las dos restantes en los lados si se quieren vistas
más cercanas para detalle de manos, sabiendo que ésas no verán el cuerpo entero.

Pendiente antes de fijar: **medir el FOV real de las Amcrest**, que puede cambiar
estos números igual que cambió los de la Tapo.

## Cuando una cámara no conecta

`[implementado]` — `apps/check_connection.py`.

`check_stream.py` sólo puede decir «no llegó ningún frame»: OpenCV no distingue
una IP equivocada de una contraseña mal puesta o de una ruta RTSP que no existe
en ese modelo, y las tres se arreglan de forma distinta. `check_connection.py`
habla RTSP directamente y devuelve el código de estado real.

```powershell
python apps/check_connection.py --camera cam3
python apps/check_connection.py --host 192.168.1.108 --user admin --password CLAVE
python apps/check_connection.py --scan
```

Cómo se lee el resultado:

| Síntoma | Causa | Arreglo |
|---|---|---|
| El puerto 554 no abre | IP equivocada, cámara apagada, u **otra subred** | Ver abajo |
| Abre pero no responde RTSP | Hay otro dispositivo con ese puerto | Confirmar la IP |
| `401` también con credenciales | Usuario o contraseña incorrectos | Ver abajo |
| `404` con credenciales correctas | El `model` declarado no es el de la cámara | Corregir `model` |
| `401` sin credenciales y `200` con ellas | Todo bien | — |

La distinción entre **401 y 404** es la que más tiempo ahorra: dice si el
problema está en la cuenta o en el modelo, que es lo que uno no puede adivinar
mirando una pantalla en negro.

### Estrenar una Amcrest: los tres tropiezos

1. **Hay que activarla antes.** Una Amcrest recién sacada de la caja **no tiene
   contraseña de administrador y no levanta el servicio RTSP**. Primero se crea
   la contraseña por su interfaz web o por la app; hasta entonces el puerto 554
   ni siquiera abre, y parece un problema de red cuando no lo es.

2. **La contraseña RTSP no es la de la app.** Es la del usuario `admin` del
   dispositivo, la que se creó al activarlo. La cuenta de la app Amcrest View es
   otra cosa. En las Tapo pasa lo mismo con la «cuenta de cámara» frente a la
   cuenta TP-Link.

3. **La subred.** Es el fallo más frecuente y el menos obvio. Una cámara nueva
   pide DHCP a la red donde esté enchufada, que **no tiene por qué ser la misma
   del PC**. Si el PC está en una red institucional (`10.x.x.x`) y la cámara en
   un router de laboratorio (`192.168.x.x`), no se ven aunque los dos cables
   salgan de la misma pared.

   Para encontrar la IP, en orden de menos a más intrusivo:

   - La tabla DHCP del router, o el *Amcrest IP Config Tool*, que las descubre
     por difusión sin escanear nada.
   - Conectar la cámara y el PC a un switch o router aislado, donde la subred es
     conocida.
   - `--scan`, que prueba el puerto 554 en los 254 hosts de la subred local.

   **En una red universitaria, `--scan` puede parecer un escaneo de puertos y
   disparar alertas de seguridad.** Usarlo sólo en una red propia o con permiso.

### Fijar la IP en cuanto conecte

En cuanto la cámara responda, **fijar su IP** (o reservarla por MAC en el
router). Si cambia, las direcciones RTSP dejan de valer, y con los extrínsecos
ya calibrados eso significa repetir una sesión de calibración por una razón
puramente administrativa.

## Los cuatro problemas del laboratorio

### 1. Pan/tilt motorizado — riesgo número uno

Cualquier movimiento del motor invalida los extrínsecos **sin síntoma visible**. Ver [calibration.md](calibration.md#integridad-de-la-calibración-el-riesgo-número-uno) para la mitigación en dos capas: desactivar patrulla y seguimiento, y marcador ArUco de integridad al arranque.

Ningún módulo de este repositorio debe emitir comandos PTZ.

### 2. Infrarrojo contra el OptiTrack

Las cámaras IP llevan iluminadores IR de 850 nm; las OptiTrack trabajan en esa misma banda. La interferencia va en las dos direcciones: los IR de las cámaras IP meten ruido y marcadores falsos en Motive, y el estrobo de las OptiTrack satura una cámara IP que entre en modo noche.

**Obligatorio:** apagar la visión nocturna y forzar modo día permanente (deshabilitar el conmutador automático del filtro IR-cut) en todas las cámaras IP, y garantizar luz ambiente suficiente.

### 3. Wi-Fi de 2.4 GHz contra el Crazyradio

El enlace del Crazyflie usa la misma banda. Seis cámaras transmitiendo vídeo por Wi-Fi pueden degradarlo.

- Con las **Amcrest**: cablear las seis por Ethernet **y desactivar la radio Wi-Fi en la configuración de cada cámara** — no basta con enchufar el cable, o se quedan asociadas al AP ocupando la banda.
- Con las **Tapo**: no hay Ethernet. Medir la tasa de paquetes perdidos del Crazyflie con las cámaras encendidas y apagadas antes de dar por buena cualquier sesión de vuelo.

### 4. Exposición automática que baja el frame rate

Con la visión nocturna apagada (obligatorio, punto 2) y sensores de píxel pequeño, la exposición automática en luz escasa hace una de dos cosas: subir la ganancia, metiendo ruido que se traduce en jitter de landmarks; o **bajar el frame rate por su cuenta**. Lo segundo es traicionero: se cree tener 30 fps y llegan 15.

Mitigación: fijar exposición y obturador manualmente donde el modelo lo permita (las Amcrest sí), garantizar luz ambiente, y **verificar siempre los fps realmente recibidos** contando frames. Ver [capture.md](capture.md#verificación-obligatoria-del-frame-rate).

## Red (cuando lleguen las Amcrest)

- Switch con **uplink gigabit** al PC de captura; los puertos de cámara a 100 Mbps bastan. Preferible switch o VLAN dedicado, y segunda NIC en el PC.
- **Ancho de banda:** H.264 a 4MP y 30 fps ronda 4-8 Mbps por cámara, o sea 24-48 Mbps entre seis. Cómodo. **MJPEG a resolución completa son 80-150 Mbps por cámara y satura un puerto de 100Base-T** — descartado; si se quiere MJPEG por el marcado temporal frame a frame, sólo a resolución reducida.
- **No es PoE.** Cada cámara necesita alimentación DC en su punto de montaje. Seis tomas de corriente en altura, a considerar en la logística.
- **IP fija o reserva DHCP** por cámara, o las URLs RTSP cambian solas.
- NTP en la LAN para las seis.

## Montaje

Las 6 cámaras IP irán en las mismas posiciones perimetrales que las OptiTrack, **un poco más abajo**.

**Ventaja:** ven el mismo volumen que el MoCap, así que la calibración contra un blanco rastreado por el MoCap funciona directamente y deja todo en el marco del Robotat.

**Restricciones:**

- **Altura.** Las posiciones OptiTrack están optimizadas para ver el dron, no al operador, y los estimadores de pose se degradan con vistas muy picadas. Regla: `altura_cámara ≤ 1.2 + d · tan(25°)`. Con el operador en el centro y `d ≈ 2-2.5 m`, eso son **1.5-1.8 m**.
- **Riesgo mecánico.** Manipular los soportes puede mover una OptiTrack e invalidar la calibración de Motive. Usar herrajes independientes y **re-verificar la calibración del MoCap después del montaje**.
- **Irreversibilidad.** La colocación definitiva es la única decisión difícil de deshacer. Montar con abrazaderas ajustables, correr el diagnóstico, y sólo entonces fijar.

## Geometría del laboratorio

- Volumen neto del Robotat: **4 × 5 × 3 m** (confirmado por el usuario, 2026-09-02).
- El cubo interior de la figura de referencia **no es el laboratorio: es la zona de
  seguridad de vuelo del dron**, de 1.5 m de altura. (La figura rotula su planta
  como 2 × 2 m en la etiqueta interna y 3 × 3 m en el título; inconsistencia menor
  sin resolver, no bloquea el montaje.)
- Los 3 m de altura útil dan margen de sobra para montar a la altura que conviene
  a la estimación de pose (~1.1-1.8 m), que es mucho más baja que el techo.
- **El operador se ubica en el centro.** Las seis cámaras ya apuntan ahí, así que la cobertura y los ángulos de triangulación son casi óptimos sin mover nada.

**Advertencia de seguridad que no pertenece a este repositorio pero hay que registrar:** con el operador en el centro y un cubo de vuelo de 1.5 m de altura —menor que la estatura de una persona—, operador y dron comparten espacio. La zona de exclusión alrededor del operador es responsabilidad del supervisor en el repositorio `tesis`. Este repositorio le da la posición del operador; no impone límites de vuelo.

## Fuentes

- Hoja de datos oficial Tapo C210 (TP-Link).
- Página de producto y especificaciones técnicas Amcrest IP4M-1041B; puerto Ethernet RJ-45 10/100Base-T confirmado por el usuario.
- Formatos de URL RTSP de Amcrest: iSpyConnect.
