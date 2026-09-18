---
fecha: 2026-09-12
tipo: analisis
autor: claude
estado: propuesta
---
# Auditoría del controlador de dos drones: por qué oscilan

Revisión de sólo lectura. No se cambió código ni se conectó hardware.

Se leyó el backend de mocap (`cruz_highlevel_backend.py`, `drone_unit.py`), el de
Flow Deck (`flowdeck_dual_backend.py`, `flowdeck_cruz_backend.py`), el teclado,
los controladores por cámara y las partes de cflib 0.1.28 que intervienen
(`MotionCommander`, driver de radio). Se analizaron 17 sesiones CSV del 5 de
septiembre (backend high-level con mocap), 6 sesiones del panel individual
anterior (22 y 29 de agosto, 5 de septiembre), 3 grabaciones MQTT crudas del
Robotat (26 de agosto) y las 5 capturas del panel dual del 9 de septiembre.

Complementa el [análisis del 8 de septiembre](2026-09-08%20Oscilación%20con%20dos%20drones.md);
lo confirma en lo esencial y corrige la estimación de la tasa real de posición.

## 1. El punto de partida no se sostiene con los datos que hay

La premisa "por separado vuelan bien, así que es el hardware" sólo es cierta si
"por separado" significa el panel individual **anterior** (lazo low-level en
Python, eliminado en la refactorización) o el Flow Deck. Con el backend actual,
un dron solo oscila igual que dos.

Ventanas de 5 s con objetivo fijo (sin despegue, sin seguimiento), error respecto
al objetivo en XY y dispersión de roll/pitch:

| Sesiones | Controlador | σ XY (m) | σ inclinación (°) |
|---|---|---|---|
| Panel individual, ago 22–29 y sep 5 09:25 (6 sesiones) | lazo low-level en Python sobre mocap | 0.02 – 0.07 | 0.4 – 1.5 |
| Un dron con `--single`, sep 5 (5 sesiones) | high-level `go_to` del firmware | 0.05 – 0.16 | 2.0 – 6.2 |
| Dos drones, sep 5 (2 sesiones con hold) | high-level `go_to` del firmware | 0.05 – 0.10 | 1.7 – 3.8 |

Frecuencia dominante en todas las sesiones high-level: **0.38 – 0.43 Hz en X, Y y Z
a la vez**, con uno o dos drones. Una oscilación de la misma frecuencia en los
tres ejes y en los dos drones por separado apunta al lazo de estimación y
control, no a una interacción entre los drones.

Las capturas del 9 de septiembre son del panel dual en **modo Flow Deck con un
solo dron habilitado** (`--single`); no hay CSV de esos vuelos porque el backend
de Flow Deck no registra nada. Lo que se sabe del Flow Deck con dos drones a la
vez está en la sección 4.

## 2. Lo que sí se descarta con evidencia (sesiones dual del 5 de septiembre)

| Hipótesis "de hardware" | Medida | Conclusión |
|---|---|---|
| Las dos Crazyradio se interfieren | Edad de la telemetría EKF (log a 20 Hz) p95 = 47–62 ms, máximo 0.19 s en las 4 sesiones dual; igual que con un dron | Los dos enlaces estuvieron sanos. No se pierden paquetes de forma apreciable |
| El proceso se atasca con dos drones (GIL, Tk) | Intervalo del logger p95 = 0.11 s, máximo 0.125 s, igual con uno o dos | No hay atascos |
| Marcadores cruzados o pérdida de tracking | Error EKF–mocap medio 0.03–0.05 m, máximo 0.17 m en dual; cada dron sigue su objetivo | Descartado |
| Acoplamiento aerodinámico | Con objetivo fijo, n = 8 ventanas: la inclinación **no** crece al acercarse (r = +0.6, signo contrario al esperado). En ventanas dinámicas sí crece (5.3° a 0.5–0.8 m frente a 2.2° a más de 1.1 m), pero esas ventanas son las de seguimiento del marker, donde los drones persiguen un objetivo móvil | Sin evidencia a ≥ 0.5 m de separación lateral. No se puede excluir por debajo de 0.4 m ni con un dron encima del otro |
| Baterías | En vuelo 3.0–3.5 V en todas las sesiones, mínimos hasta 2.9 V; correlación con la inclinación 0.27 | Bajas en **todos** los grupos, también en los tranquilos: no explican la diferencia, pero reducen el margen de empuje. Ver mejora E |

## 3. La causa: cómo llega la posición al EKF

### 3.1 El Robotat no publica a 20 Hz limpios

Las tres grabaciones MQTT crudas (`results/data/dos_drones/mqtt_robotat_raw_20260826_*.csv`)
muestran, por tópico:

| Grabación | Mensajes/s | Frames distintos por ráfaga | Intervalo entre ráfagas p50 / p95 / máx | Huecos > 120 ms |
|---|---|---|---|---|
| 12:03 | 86 | 1–2 (ráfagas de ~5 mensajes) | 53 / **319** / 1058 ms | 17.5 % |
| 12:05 | 86 | 1 (ráfagas de ~3) | 31 / 64 / 175 ms | 0.5 % |
| 12:08 | 86 | 1–2 (ráfagas de ~5) | 57 / **308** / 709 ms | 16.9 % |

Es decir: el puente Node-RED publica **cada frame 3 a 5 veces** (mismo XYZ, 0.1 mm
de diferencia dentro de la ráfaga), a ~18 frames distintos por segundo, y en dos
de tres grabaciones **uno de cada seis intervalos supera 120 ms**, con huecos de
0.3 s frecuentes y de hasta 1 s. La grabación de las 12:05 fue limpia, así que la
calidad del stream cambia de una sesión a otra: la del Robotat no es una
constante, es algo que hay que medir antes de cada vuelo.

`DroneUnit.mocap_hz` reporta "20–23 Hz" porque descarta los intervalos de 0 ms
(`drone_unit.py:194`): mide el ritmo de las ráfagas, no cuántos frames útiles
llegan ni cuánto duran los huecos. El indicador del panel engaña.

### 3.2 El límite de 20 Hz convierte eso en 7–13 Hz irregulares

`EXTPOS_RATE_HZ = 20` (`drone_unit.py:34`) sólo deja pasar un mensaje si han
pasado ≥ 50 ms desde el anterior. Simulado sobre las llegadas reales:

| Grabación | Frames al EKF | Intervalo p50 / p95 / máx |
|---|---|---|
| 12:03 | **7.1 Hz** | 88 / 399 / 1043 ms |
| 12:05 | 13.0 Hz | 75 / 106 / 194 ms |
| 12:08 | **8.0 Hz** | 87 / 347 / 729 ms |

Con ráfagas cada ~53 ms, la regla de "≥ 50 ms" rechaza ráfagas enteras cuando
llegan con 45 ms de jitter y el EKF se queda 90–100 ms sin medida de forma
sistemática, y 0.3–0.4 s en el 5 % de los casos. El comentario que justifica el
límite ("radio compartida") no aplica: cada dron tiene su Crazyradio.

Subir el límite a 60 Hz **no basta**: pasaría los duplicados (3–5 paquetes
idénticos seguidos por radio) y no rellena los huecos del Robotat. Lo correcto es
**enviar una vez por frame distinto, inmediatamente**, y arreglar el puente.

### 3.3 Por qué el backend actual lo sufre y el anterior no

- El `go_to` del commander high-level se ejecuta entero en el firmware: el
  controlador de posición PID actúa sobre `stateEstimate`, y esa estimación
  sólo se corrige cuando llega un extpos. Entre correcciones, la posición se
  integra de la IMU y la velocidad estimada se degrada; con huecos de 100–400 ms
  el controlador corrige tarde y de más. Eso da exactamente una oscilación lenta
  (0.4 Hz) con 3–6° de inclinación.
- El lazo anterior cerraba la posición **en Python, sobre el último frame del
  mocap**, y mandaba velocidades pequeñas al firmware. Tolera huecos porque su
  ganancia era baja y no dependía de la posición del EKF. Por eso volaba tranquilo
  con el mismo Robotat y las mismas radios.
- La orientación nunca se envía (sólo `send_extpos`). El EKF asume yaw 0 al
  reiniciar; si la nariz no apunta a +X del Robotat, el controlador actúa en un
  marco girado. Con dos drones esto importa el doble: se colocan a mano y nada
  comprueba que ambos miren en la misma dirección.
- Los `go_to` se solapan: el gesto repite cada 1.25 s un `go_to` de 3 s
  (`control_dos_drones_camara_multiprocessing.py:51`, igual en el de un
  dron); el seguimiento manda uno de 0.75 s cada 0.10 s. Cada `go_to` replanifica
  desde la estimación actual, que ya va con retraso: alimenta la oscilación.

## 4. Lo que sí cambia con dos drones

Ordenado por lo que más probablemente explica que "con dos se vea peor":

1. **Dos oscilaciones de ±20 cm con separación mínima de 0.30 m.** Con los drones
   a 0.5–0.8 m (seguimiento en formación a 0.45 m del marker), la oscilación de
   cada uno basta para acercarlos a menos de 0.30 m y disparar el watchdog
   (`EMERGENCY_SEPARATION_M`), o para bloquear movimientos. Lo que se ve es un
   sistema que "se descontrola"; la causa sigue siendo la sección 3.
2. **Orientación inicial distinta.** Cada dron parte con yaw 0 asumido. Un dron
   colocado girado respecto al otro vuela en un marco girado; el error crece con
   el ángulo. No se comprueba en el preflight.
3. **Aerodinámica** sólo si están a menos de ~0.4 m o uno sobre otro. Los datos a
   ≥ 0.5 m no muestran efecto, pero la formación permite acercarse más.
4. **Paro de emergencia secuencial.** `HardwareBackend.emergency()` corta el
   dron 1 (10 repeticiones × 20 ms) y sólo después el dron 2: el segundo sigue
   volando 0.2 s más. `stop_motors(*cfs)` ya intercala repeticiones si se le
   pasan los dos `cf`; no se usa así.
5. **Radios y Wi-Fi.** Sin evidencia de interferencia el 5 de septiembre. Sigue
   pendiente apagar la radio Wi-Fi de la Amcrest (bitácora del 11) y separar
   físicamente las dos Crazyradio PA; es barato y elimina la duda.
6. **Batería del segundo dron.** En las sesiones dual, el dron 2 voló 0.15–0.2 V
   por debajo del dron 1 (3.28 frente a 3.46 V).

## 5. Flow Deck con dos drones: no hay datos, pero sí riesgos conocidos

- `FlowCruzBackend.snapshot()` devuelve `log_path: None`: **no se registra nada**.
  Lo primero es instrumentar; sin CSV no se puede distinguir hardware de software.
- `MotionCommander` envía el setpoint de hover **cada 0.2 s** (5 Hz,
  `_SetPointThread.UPDATE_PERIOD`). El firmware pasa a modo "estabilizar"
  (nivela y deja de mantener posición) a los 0.5 s sin setpoint y corta a los 2 s.
  Basta perder dos o tres paquetes seguidos para que el dron se nivele, derive y
  luego dé un tirón al recuperar. Con dos Crazyradio PA pegadas en el mismo hub,
  la pérdida en ráfaga es más probable. Es la única vía verosímil por la que "dos
  radios" produzcan oscilación, y sólo en Flow Deck: el backend de mocap manda
  `go_to` una vez y el firmware sigue solo.
- Cada dron sostiene su posición por flujo óptico sobre su propio trozo de suelo.
  Con dos drones cerca, la sombra del otro moviéndose sobre ese trozo es flujo
  aparente; y con poca textura o luz uno de los dos puede quedar en peor sitio.
  Los ToF a 940 nm sólo se estorban con las huellas en el suelo solapadas
  (menos de ~20 cm a 0.35 m de altura).
- `take_off()` y `land()` bloquean el hilo dueño de la radio
  (`flowdeck_dual_backend.py:_serve`): la tecla R no se atiende hasta que el
  despegue termina. Con dos drones despegando a la vez son varios segundos sin
  paro. No causa oscilación, pero conviene arreglarlo antes de seguir probando.

Prueba que separa las hipótesis, sin cambiar código: volar en hover con
`--backend flowdeck` (1) dron 1 solo, (2) dron 2 solo, (3) los dos a 1.5 m,
(4) los dos a 0.5 m, (5) los dos a 1.5 m con las Crazyradio separadas 50 cm por
cable USB. Si (3) ya oscila y (5) no, son las radios; si sólo (4), es suelo,
sombra o aire; si (1) o (2) oscilan solos, no es cosa de dos drones.

## 6. Mejoras, en orden

**A. Alimentar el EKF con cada frame distinto, sin duplicados ni límite**
(`drone_unit.py`; amplía T-003):
- Quitar `EXTPOS_RATE_HZ`. Enviar cuando el XYZ difiera del último enviado
  (> 0.5 mm) o hayan pasado más de 100 ms; así los duplicados del puente no van
  por radio y ningún frame útil se pierde. Esperado: ~18 Hz regulares en vez de
  7–13 irregulares.
- Enviar `send_extpose` con el cuaternión del Robotat (parser ya escrito en
  `marker_mocap.py:342-368`) y fijar `locSrv.extPosStdDev` / `extQuatStdDev`
  explícitamente en el preflight.
- Registrar en el CSV `extpos_submitted`, la tasa efectiva de frames distintos,
  el hueco máximo del último segundo y `stateEstimate.yaw` frente al yaw del mocap.
- Corregir `mocap_hz`: contar frames distintos por segundo y exponer el hueco
  máximo; el panel debe avisar en rojo si el hueco supera 120 ms.

**B. Arreglar el puente del Robotat, no sólo compensarlo en Python.**
Los duplicados y los huecos de 0.3 s nacen en Node-RED/MQTT, no en el dron.
Revisar el flujo que publica `mocap/drone3` y `mocap/drone4` (publicar una vez
por frame, QoS 0, sin buffers) y añadir al preflight una medición de 5 s del
stream que rechace el vuelo si el p95 del intervalo supera 120 ms. El recorder
crudo ya existe; conviene correrlo antes de cada sesión.

**C. No solapar `go_to`** (T-004, y extenderla a los gestos): cooldown del gesto
≥ duración del `go_to`, o duración proporcional a la distancia y rechazo mientras
el anterior no termine. Sólo después de A tiene sentido tocar ganancias del
firmware (`posCtlPid.*`); hoy se estarían ajustando contra una estimación mala.

**D. Preflight de rumbo**: calcular el yaw del Robotat de cada dron y abortar si
difiere de 0 (o entre drones) más de 10°, con
`controllers/joystick/marker_orientation_check.py` para fijar la convención.

**E. Reglas de operación con dos drones mientras persista la oscilación**:
separación mínima y de formación ≥ 0.60 m, misma orientación al colocarlos,
baterías ≥ 3.7 V en reposo antes de despegar (añadir aviso en el panel por
debajo de 3.6 V en vuelo), Crazyradio PA separadas ≥ 30 cm con alargadores USB,
Amcrest sin Wi-Fi.

**F. Paro de emergencia intercalado**: `stop_motors(cf1, cf2, repeats=10,
interval_s=0.02)` en `HardwareBackend.emergency()`; comprobar `emergency_event`
dentro de los despegues y aterrizajes del `FlowDroneController` (o hacerlos no
bloqueantes).

**G. Instrumentar el backend de Flow Deck**: CSV por dron con `stateEstimate.x/y/z`,
`kalman.varPX/PY/PZ`, `range.zrange`, `motion.deltaX/deltaY`, batería y calidad
de enlace (`cf.link_statistics.link_quality_updated`, disponible en cflib
0.1.28). Registrar también la calidad de enlace en el CSV de mocap: es la medida
directa de la hipótesis de las radios. Subir el periodo del hilo de setpoints a
50–100 ms para que el watchdog del firmware necesite 5–10 paquetes perdidos, no
dos.

**H. Métrica de oscilación en el analizador** (ya en T-004): pico a pico y σ por
eje en holds, frecuencia por cruces por cero, y ahora también tasa efectiva de
extpos y hueco máximo.

## 7. Qué se espera después de A y B

En hover de 30 s con un dron: σ XY por debajo de 0.04 m e inclinación por debajo
de 1.5°, es decir, lo que ya daba el panel anterior. Si con eso un dron solo
queda bien y dos siguen oscilando, entonces sí queda un problema de dos drones, y
la prueba de la sección 5 y la calidad de enlace registrada dirán cuál.
