# Un Crazyflie sobre el Robotat, desde cero

Controlador nuevo (16 de septiembre de 2026) para **un** dron con **mocap**,
escrito porque el backend de la cruz oscila a 0.4 Hz en hover con uno o dos
drones (ver los análisis del 8 y del 12 de septiembre en `Tesis/60-Analisis/`).
Conserva las órdenes de siempre y cambia sólo lo que esos análisis señalan.

```powershell
# sin hardware
.\.venv\Scripts\python.exe .\controllers\single_drone\robotat\control_dron_robotat.py --dry-run
# Dron 1 (PREFLIGHT no enciende motores)
.\.venv\Scripts\python.exe .\controllers\single_drone\robotat\control_dron_robotat.py --dron 1
```

Teclado: W/A/S/D mueven, Espacio y Shift suben y bajan, Q y E giran, Enter
despega o aterriza, **R corta motores**. Tres modos de mando:

| `--modo` | Qué manda al firmware | Cuándo |
|---|---|---|
| `fluido` (defecto) | Mientras hay tecla, el paquete `hover` de `MotionCommander` a 20 Hz: velocidad horizontal en el marco del cuerpo con rampa de 0.6 m/s², giro en °/s y **altura absoluta** integrada en Python (Z en modo velocidad hacía subir el dron por el sesgo de vz del EKF). Al soltar, frena y devuelve el mando al high-level con un `go_to` | Manejo a mano |
| `continuo` | `go_to` de 0.45 s cada 0.2 s encadenados; el firmware planifica cada uno desde el anterior | Si el fluido diera problemas de enlace |
| `pasos` | Un `go_to` de 10 cm (8 cm en Z) o 20° por pulsación, nunca solapados | Órdenes discretas (gestos) |

En los tres, la velocidad es `--velocidad` y la geocerca se aplica a cada
objetivo; en `fluido`, anulando la componente de velocidad que la cruzaría en
0.6 s. En `fluido` el enlace de radio importa: sin setpoints el firmware
nivela a los 0.5 s y corta a los 2 s, por eso al terminar cada movimiento se
vuelve siempre al high-level, que no depende del enlace.

## Archivos

Para los dos drones a la vez con este mismo núcleo: `controllers/two_drones/control_dos_drones_robotat.py` (teclado dual) y, para **todas** las interfaces de la cruz (botones, cámara de dos drones, web), `--backend robotat` vía `controllers/two_drones/robotat_backend.py`.

| Archivo | Qué hace |
|---|---|
| `../../shared/mocap_feed.py` | Suscriptor MQTT de un rigid body. Descarta los duplicados del puente, entrega cada frame distinto una vez, detecta poses congeladas, mide frames/s, hueco máximo, latencia de origen y velocidad. Sin cflib. |
| `../../shared/dron_robotat.py` | `DronRobotat`: preflight, `takeoff`, `move(dx, dy, dz, dyaw)`, `fijar_velocidad`, `land`, `emergency`, `estado()`, vigilancia y CSV. `DronSimulado` con la misma interfaz para `--dry-run`. Las reglas (paso, geocerca, duración, watchdog) son funciones puras. **Desde el 17 de septiembre vive en `controllers/shared/`** porque lo consumen tres categorías. |
| `control_dron_robotat.py` | Panel Tk y línea de órdenes. |
| `../../shared/analizar_sesion_robotat.py` | Gráficas **PDF** y resumen de cada sesión en `results/graphs/dron_robotat/<día>/<sesión>/`; se genera solo al cerrar. |
| `vuelo_camara.py` | `VueloRobotat`: el dron con la interfaz que espera `camera/control_camara_dron1.py` (`--backend robotat`). Velocidad de los gestos en modo fluido; seguimiento del marker 65 a la altura del marker, con Kp 1.5 y tope `--velocidad-seguir` (0.30 m/s); deadman de 0.4 s y aterrizaje a los 2 s sin órdenes. |
| `tests/` | 114 pruebas sin radio ni broker. |

## Qué cambia respecto al backend de la cruz

| Antes (`two_drones/cruz_highlevel_backend.py`) | Aquí | Por qué |
|---|---|---|
| Extpos limitado a 20 Hz: con las ráfagas del puente llegaban 7–13 Hz irregulares al EKF | Un envío por **frame distinto**, sin límite; los duplicados no van por radio | Auditoría del 12/09, mejora A |
| `locSrv.extPosStdDev` de fábrica (0.01 m) | Se fija siempre y se registra; `--ext-pos-std 0.03` para probar | Oscilación del 12/09, prueba 3 |
| Sin forma de tocar el firmware | `--param grupo.nombre=valor`, repetible; lo aplicado va al CSV | Oscilación del 12/09, prueba 0 |
| Latencia del mocap no compensada ni medida | `--anticipo-s 0.08` extrapola `p + v·τ` antes de enviar; la latencia MQTT va al CSV | Oscilación del 12/09, prueba 4 |
| `go_to` de 3 s que se solapan (gestos cada 1.25 s) | Pasos: duración `distancia / --velocidad` (mínimo 1 s) y cola en el panel, nunca solapados. Modo continuo: `go_to` de 0.45 s cada 0.2 s, solapados **a propósito** (el firmware planifica desde el estado planificado) | T-004 y vuelo del 16/09 |
| Sin mocap: corte de motores | Sin mocap: `land` del firmware; corte sólo si el EKF se aleja del mocap o la batería cae | Caída del 16/09 |
| Primer `go_to` con yaw 0 absoluto | El objetivo de yaw parte de `stateEstimate.yaw` al despegar; no hay giro espurio | Marco de vuelo, 12/09 |
| Sin comprobación de batería | Despegue rechazado por debajo de 3.65 V en reposo; corte por debajo de 3.0 V en vuelo | Oscilación del 12/09, regla E |
| Tras `land` los motores siguen al ralentí | `stop()` medio segundo después de aterrizar | — |
| Sin hueco máximo ni latencia en el CSV | `mocap_frames_hz`, `mocap_hueco_max_s`, `mqtt_latencia_s`, `extpos_enviados`, `ekf_yaw_deg`, `mocap_yaw_deg`, `ekf_vx/vy/vz` y `mocap_vx/vy/vz` (sesgo de velocidad del EKF) | Auditoría, mejora H |

Lo que **no** cambia: límites de vuelo (paso 0.10 m, giro 20°, geocerca
0.50 m, Z entre 0.20 y 1.10 m), vigilancia de mocap fresco y de EKF a menos de
0.15 m del mocap, y el corte de motores enclavado.

## Juego validado y cómo se llegó a él

```powershell
.\.venv\Scripts\python.exe .\controllers\single_drone\robotat\control_dron_robotat.py --dron 2 --ganancias robotat --velocidad 0.25 --radio-max 1.0
```

`--ganancias robotat` (Dron 2, 16 de septiembre de 2026, hover de 45 s: σ x/y/z
de 0.027/0.041/0.032 m, roll 0.5°, despegue en 0.8 s con 4 cm de sobrepaso):

| Parámetro | Fábrica | Aquí | Por qué |
|---|---|---|---|
| `posCtlPid.x/y/zKp`, `velCtlPid.vx/vy/vzKp`, `VelMax` | 2.0 / 25 / 1.0 | 1.0 / 12 / 0.5 | Con la posición externa 60–100 ms tarde el lazo de fábrica oscila a 0.4 Hz; a la mitad es estable |
| `velCtlPid.vzKi` | 15 | 8 | El integrador vertical entraba en ciclo límite (Z ±20 cm a 0.3 Hz) |
| `posCtlPid.thrustBase` | 36000 | 46000 | Es el empuje de hover medido (`empuje_cmd`); con 36000 el dron pasaba 3 s en el suelo cargando el integrador y sobrepasaba 0.27 m |
| `locSrv.extPosStdDev` | 0.01 | 0.03 | Menos confianza en una medida retrasada: mejor XY y roll |

`thrustBase` depende del dron y de la batería. Al aterrizar, `LANDED` imprime
el empuje medio del hover y el valor recomendado; si difiere, pasarlo con
`--param posCtlPid.thrustBase=...`, que manda sobre el preajuste. Batería a
4.1 V o más: por debajo de 4.0 V en reposo el Dron 2 cae por debajo de 3.0 V
en el primer movimiento y el controlador aterriza solo.

Pruebas que no aportaron: `--anticipo-s 0.08` (sin mejora sobre `extPosStdDev`).

`--extpose` envía además el cuaternión del rigid body. **No usarlo** con el
Dron 2 mientras su rigid body publique roll de −84°: alimentaría al EKF una
actitud falsa. Sirve para el Dron 1 sólo si se comprueba antes que los ejes
del rigid body coinciden con los del dron.

## Resultados

Cada sesión escribe `results/data/dron_robotat/<AAAA-MM-DD>/dron_robotat_<dron>_<marca>.csv`
con una fila cada 100 ms y una por evento (`PREFLIGHT_OK`, `TAKEOFF`, `GO_TO`,
`FLUIDO_INICIO`, `LAND`, `LANDED`, `EMERGENCIA`), y al cerrar genera en
`results/graphs/dron_robotat/<AAAA-MM-DD>/<sesión>/` ocho gráficas PDF (altura,
trayectoria, error EKF y mocap, batería y empuje, velocidades, actitud, **línea
de tiempo de gestos y órdenes sobre el vuelo**, **vuelo en 3D** con las
órdenes marcadas) y un `00_resumen.txt` con las cifras clave. Si hubo un
segundo dron arrancado a menos de un minuto, además
`vuelo_dual_<marca>/trayectorias_y_separacion.pdf` con los dos y su separación.
El evento `VEL` del CSV guarda la dirección pedida en cada cambio de velocidad. A mano: `controllers/shared/analizar_sesion_robotat.py [csv|--todas]`. El criterio de T-003 (hover de 30 s con Z pico a
pico por debajo de 0.1 m) se alcanzó el 16 de septiembre con `--ganancias robotat`.
