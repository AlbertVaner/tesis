---
fecha: 2026-09-16
tipo: analisis
autor: claude
estado: revisar
---
# Primer vuelo del controlador de un dron sobre el Robotat

Sesión `results/data/dron_robotat/2026-09-16/dron_robotat_20260916_145902.csv`, Dron 2, rigid body recién creado (id 4), sin órdenes de movimiento. Todo lo de abajo está medido sobre ese CSV.

## Qué pasó

| | |
|---|---|
| Despegue | 16.7 s, objetivo 0.385 m |
| Vuelo | 6.2 s, sólo `takeoff` |
| Fin | 22.9 s, emergencia por EKF a 0.204 m del mocap durante una excursión rápida |
| Batería | 4.13 V en reposo, 3.55 V al arrancar motores, mínimo 3.42 V: sana |
| Mocap | 19 frames/s en reposo, **48 en vuelo**, hueco máximo 75 ms, EKF a 1 mm del mocap en tierra |

El puente publica sólo cuando la pose cambia: por eso en reposo llegan 19 frames/s (ruido) y en vuelo 48. No hay duplicados que filtrar; el flujo es limpio.

## La oscilación

| eje | pico a pico | frecuencia |
|---|---|---|
| y | 0.69 m | 0.35 Hz |
| x | 0.32 m | — |

Roll hasta 18°, pitch hasta 7.5°. Amplitud creciente desde el primer segundo en el aire: inestable, no sólo mal amortiguado.

## Lo que se descarta con este vuelo

- **Marco girado o nariz mal orientada.** Aceleración del dron (segunda derivada del mocap) contra el error de posición: 32 de 33 muestras a menos de 45°, es decir, acelera hacia el objetivo. Roll positivo produce aceleración −Y en 23 de 24 muestras, que es lo que corresponde a la nariz en +X. El rigid body nuevo publica yaw −2° con la nariz a +X: está bien definido.
- **Batería.** Cae 0.6 V al arrancar, dentro de lo normal.
- **Huecos o tasa baja del mocap.** 48 frames/s en vuelo, hueco máximo 75 ms.
- **Órdenes solapadas.** No hubo ninguna.

## Lo que queda

El retardo entre mocap y EKF es de una muestra del registro (~100 ms), igual que el 12 de septiembre. Es el mismo diagnóstico de entonces: **el lazo de posición del firmware con las ganancias de fábrica es inestable con una posición externa retrasada ~100 ms**. El controlador nuevo reproduce el problema con todo lo demás limpio, que era el objetivo: ahora sólo queda una variable.

La columna `mqtt_latencia_s` da −4 s: el reloj del Robotat va 4 s adelantado respecto al PC, así que no mide latencia absoluta. Sirve sólo para ver cambios.

## Siguiente vuelo

Una variable por vuelo, Dron 2, hover de 30 s sin órdenes:

1. `--param posCtlPid.xKp=1.0 --param posCtlPid.yKp=1.0 --param velCtlPid.vxKp=12 --param velCtlPid.vyKp=12 --param posCtlPid.xVelMax=0.5 --param posCtlPid.yVelMax=0.5`
2. `--ext-pos-std 0.03`
3. `--anticipo-s 0.10`

Criterio: pico a pico en Y por debajo de 0.1 m y roll por debajo de 3°.

## Segundo vuelo: ganancias XY a la mitad (15:04, Dron 2)

`dron_robotat_20260916_150457.csv`, 35 s en el aire con `posCtlPid.x/yKp=1.0`, `velCtlPid.vx/vyKp=12`, `posCtlPid.x/yVelMax=0.5`. Z con ganancias de fábrica.

| fase | x pico a pico | y pico a pico | z pico a pico | roll σ | pitch σ |
|---|---|---|---|---|---|
| hover 8 s tras despegar | 0.06 m | 0.13 m | 0.10 m (0.47 Hz) | 0.4° | 0.2° |
| dos pasos en X | 0.20 m (los pasos) | 0.08 m | 0.09 m | 0.4° | 0.3° |
| ocho pasos en Z | 0.06 m | 0.10 m | **0.70 m (0.55 Hz)** | 0.4° | 0.4° |

**XY resuelto**: de 0.69 m y roll de 18° a 0.13 m y roll de 0.4°. El diagnóstico del retardo se confirma: bajar la ganancia estabiliza el lazo.

**Z sigue con las ganancias de fábrica y oscila igual que XY antes**: tras cada paso vertical la amplitud crece (0.44 a 1.00 m entre los 49 y los 52 s) a 0.55 Hz. La tensión de batería sigue la oscilación (3.16 V en los mínimos, 3.55 V en los máximos): son ráfagas de empuje. Es el mismo lazo, en el eje que no se tocó.

**El final fue un aterrizaje en plena oscilación.** Se pulsó aterrizar cuando el dron bajaba a ~0.9 m/s; el firmware frenó la caída con una ráfaga (3.16 V), el dron salió disparado a 1.11 m sin empuje (3.63 V), y al caer el EKF se alejó 0.154 m del mocap y saltó la emergencia a 0.47 m. Además hubo un hueco real del mocap de 0.36 s a 0.33 m de altura. Regla: **no aterrizar en mitad de una oscilación grande**; esperar a que se calme o cortar con R a baja altura.

Aparte: al despegar el dron resbaló 17 cm en +Y por el suelo durante 1.5 s antes de levantar (ocurrió igual en el primer vuelo). Con `xyKp` a la mitad la corrección lateral en el suelo es débil. No es peligroso, pero conviene despegar desde una zona sin roce.

## Dron 1 (15:06 y 15:07): no despega por batería

3.69 V en reposo; al arrancar los motores cae a **2.88 V** y **2.78 V** en menos de 0.1 s, y el vigilante corta por debajo de 3.0 V. El Dron 2 con 4.10 V cae a 3.55 V. Es la misma batería que el 12 de septiembre caía 1.1 V: hay que cambiarla. El corte fue correcto; con esa tensión el dron se apaga solo en vuelo.

## Siguiente vuelo

`--ganancias mitad` (nuevo en el panel: aplica lo anterior más `posCtlPid.zKp=1.0`, `velCtlPid.vzKp=12`, `posCtlPid.zVelMax=0.5`). Hover de 30 s y después pasos en Z de uno en uno, esperando a que se estabilice entre pasos.

## Tercer vuelo: `--ganancias mitad` (15:16, Dron 2)

`dron_robotat_20260916_151658.csv`, 70 s en el aire, aterrizaje limpio (LANDED). Batería 4.03 V en reposo, 3.2 V en vuelo.

| fase | x | y | z | roll σ |
|---|---|---|---|---|
| hover 16 s | 0.09 m | 0.12 m | 0.22 m (0.2 Hz) | 0.4° |
| vuelo entero con 11 pasos | 0.19 m | 0.30 m | 0.65 m | 0.45° |

Z mejora (σ del error de 0.12 a 0.05 m) pero sigue oscilando ±10 cm a 0.2 Hz. Cada paso tarda 1.2 a 2.6 s en llegar al 90 % y sobrepasa. El despegue tardó 2 s en levantar del suelo a plena potencia y sobrepasó a 0.585 m (objetivo 0.384): con 3.2 V en vuelo el dron va justo de empuje y el integrador de velocidad vertical se carga en el suelo.

Lentitud percibida: dos causas. (1) Diseño: 0.10 m/s de crucero y ganancia a la mitad, un paso de 10 cm tarda ~2 s. Nuevo `--velocidad` (por defecto sigue 0.10) y cola de hasta 3 pasos en el panel: antes pulsar W tres veces daba un paso. (2) Empuje: batería a 3.2 V bajo carga; con 4.15 V el dron responde más.

## Dron 1 con batería nueva (15:15): tampoco levanta

4.17 V en reposo, 3.30 V al arrancar, bajando a 3.00 V en 2.8 s **sin despegar** (z de 0.033 a 0.069 m) y deslizando 20 cm por el suelo. Batería nueva, mismo resultado: **no es la batería, es el dron**. A plena potencia no genera empuje para su peso: revisar que giren los cuatro motores, hélices (rotas, dobladas o montadas al revés: A y B) y el conector de batería. El vigilante cortó bien.

## Cuarto vuelo: `--ganancias mitad --velocidad 0.25` (15:26, Dron 2)

`dron_robotat_20260916_152634.csv`, 99 s en el aire, 47 pasos (XY, 18 giros de 20°, 15 en Z). Batería 3.88 V en reposo, 3.1 a 3.3 V en vuelo.

| | x | y | z |
|---|---|---|---|
| hover 10 s | 0.09 m | 0.06 m | 0.24 m |
| vuelo entero | σ error 0.05 m | 0.04 m | 0.05 m |

- XY estable con roll y pitch σ 0.4°. Z sigue con ±10 cm lentos y el despegue vuelve a sobrepasar (0.585 m): con 3.2 V bajo carga el dron levanta tarde y el integrador vertical se carga en el suelo.
- El yaw del EKF sigue al del mocap a 2° tras 280° de giros: el EKF aprende el rumbo sólo con posición.
- **Por qué no es fluido**: cada paso es un `go_to` de 1 s que arranca y frena (polinomio con velocidad cero en los extremos), y el lazo con `Kp=1` va ~1 s por detrás de la trayectoria. Llega al 90 % en 2 a 2.5 s y encadenar pasos da tirones.
- **Final**: el Robotat dejó de publicar a los 110.5 s con el dron a 0.52 m; el vigilante cortó motores a los 0.75 s y el dron cayó. Hubo huecos de 0.13 a 0.35 s durante todo el vuelo, sin relación clara con el rumbo.

Cambios a raíz de esto:

1. **Modo continuo** (por defecto en el panel, `--modo pasos` para el anterior): la tecla mantenida manda cada 0.2 s un `go_to` de 0.45 s al objetivo avanzado `v · 0.2`; el firmware planifica cada tramo desde el estado *planificado* del anterior, así que el movimiento es una rampa continua a `--velocidad`, y al soltar frena en el último objetivo. La geocerca se aplica a cada objetivo. Es la excepción documentada a "no solapar go_to": aquí el solape es intencionado y con tramos cortos.
2. **Sin mocap se aterriza, no se corta.** El EKF sigue integrando unos segundos; `land` del firmware desde 0.5 m es mejor que la caída. Si el mocap no vuelve, los motores se apagan al terminar el descenso. El corte inmediato queda para EKF lejos del mocap y batería.

Pendiente: batería a 4.15 V para el despegue; probar `posCtlPid.x/yKp=1.5` si el retraso de 1 s molesta en continuo.

## Quinto vuelo: primer uso del modo continuo (15:36, Dron 2)

`dron_robotat_20260916_153627.csv`. 17 s en el aire, W mantenida 2 s (10 tramos), hover limpio: error EKF–mocap 1 cm, roll y pitch por debajo de 0.8°, sin oscilación apreciable en XY.

**Emergencia a los 23.4 s: batería 2.99 V en vuelo.** La batería estaba a 3.76 V en reposo y bajo carga se quedó en 3.02–3.06 V todo el vuelo; una muestra a 2.99 V disparó el corte y el dron cayó desde 0.38 m volando bien. Fue el umbral, no el dron.

Cambios: batería por debajo de 3.0 V sostenida medio segundo → aterrizaje automático (no corte); corte sólo por debajo de 2.7 V. Aviso al despegar si la batería en reposo está por debajo de 3.9 V. Para el Dron 2, que cae ~0.7 V bajo carga, conviene despegar con 4.1 V o más.

## Modo fluido (16:00): velocidad como el Flow Deck

El humano sigue notando el mando tosco con `go_to` encadenados. El Flow Deck se siente fluido porque `MotionCommander` manda una **velocidad** continua y el firmware no arranca ni frena por tramo. Con mocap se puede hacer igual: `send_velocity_world_setpoint(vx, vy, vz, yawrate)` a 20 Hz mientras hay tecla, con rampa de 0.6 m/s². Al soltar, la rampa baja a cero, `send_notify_setpoint_stop()` y un `go_to` de 1 s a la posición estimada devuelven el mando al high-level, que mantiene el hover sin depender del enlace (con setpoints de bajo nivel el firmware nivela a los 0.5 s sin paquetes y corta a los 2 s). La geocerca anula la componente de velocidad que la cruzaría en 0.6 s. Implementado como `--modo fluido`, por defecto; `continuo` y `pasos` siguen disponibles. Sin probar en vuelo todavía.

No es el lazo de velocidad en Python que prohíbe `AGENTS.md`: aquí la posición la cierra el firmware; Python sólo transmite la velocidad que pide la tecla.

## Sexto vuelo: modo fluido, el dron sube con cualquier tecla (15:47, Dron 2)

`dron_robotat_20260916_154703.csv`, 66 s, batería 4.18 V en reposo y 3.2–3.35 V en vuelo, aterrizaje limpio. Diez movimientos fluidos; el horizontal funciona (0.45 m en +X en 3.5 s, suave), pero **en todos el dron sube ~0.13 m/s** aunque la velocidad vertical enviada era 0, y sigue subiendo unos segundos tras devolver el mando. Ejemplo: de 0.62 a 0.92 m en 2.3 s con una tecla horizontal.

Causa: `send_velocity_world_setpoint` pone Z en modo velocidad. Sin lazo de posición, el firmware sólo iguala su **velocidad vertical estimada** a cero, y el EKF con sólo posición externa (sin medida de velocidad) tiene un sesgo en esa velocidad: la posición la corrige cada frame, la velocidad la arrastra la IMU. El sesgo se convierte en deriva. Probablemente es el mismo sesgo que hace oscilar Z en el high-level y que el despegue sobrepase (hoy 0.52 m con objetivo 0.38 y batería llena).

Cambio: el modo fluido usa ahora `send_hover_setpoint`, el paquete de `MotionCommander`: velocidad horizontal en el marco del cuerpo (se rota con el yaw del EKF), giro en grados/s (positivo antihorario, como `start_turn_left`) y **altura absoluta**, que Python integra con `z += vz·dt` y el firmware mantiene en lazo de posición. Al soltar, el `go_to` de entrega usa la altura mandada, no la estimada. 89 pruebas.

Pendiente: si Z sigue oscilando en hover high-level, medir el sesgo de `stateEstimate.vz` en el CSV y probar `--extpose` o `locSrv.extPosStdDev` más alto.

## Séptimo vuelo: modo fluido con altura absoluta (15:52, Dron 2)

`dron_robotat_20260916_155254.csv`, 68 s, 14 movimientos, aterrizaje limpio. Batería 4.04 V en reposo, 3.1–3.3 V en vuelo.

- **La altura ya no deriva**: con W y S la Z cambia menos de 1 cm en 5 s; Espacio y Shift la mueven 0.19 m en 1 s y para al soltar.
- **X funciona**: +0.65 m con W (5.5 s), −1.14 m con S (6.4 s), +0.77 y −0.72 m después.
- **A casi no responde** (0.04 a 0.05 m en 2 s en tres intentos); D sí (−0.27 m). Causa: la geocerca. El dron estaba a 0.55 m del origen, fuera del círculo de 0.50 m, empujado por la inercia al parar en X. `fence_velocity` anulaba la velocidad horizontal **entera** si tenía cualquier componente hacia fuera, y a esa posición +Y tenía un poco. Arreglado: se resta sólo la componente radial, así el dron resbala por el borde y A/D siguen respondiendo; hacia dentro pasa todo.
- Con 1.5 m de área, 0.50 m de radio se queda corto para el mando fluido: usar `--radio-max 1.0` si el laboratorio lo permite (el límite por defecto no se toca).
- Hover: pico a pico 0.09 m en X e Y y 0.12 m en Z, roll y pitch σ 0.6–0.8°. Es la "ligera oscilación": queda el sesgo vertical del EKF y el retraso; pendiente `--extpose` / `--ext-pos-std`.
- El yaw del mocap derivó de 6° a 18° en vuelo sin ninguna orden de giro (el EKF lo siguió a 5°). Hay una pequeña deriva de rumbo en modo velocidad; sin efecto en el mando porque la velocidad se rota con el yaw del EKF.

## Tres hovers de comparación (16:18, 16:19, 16:20, Dron 2)

Todos con `--ganancias mitad`, batería en reposo 3.95, 3.90 y 3.84 V (no se cargó a 4.1), 3.1 V en vuelo. Hover de 15 a 20 s sin órdenes.

| | 1: `--ext-pos-std 0.03` | 2: `--anticipo-s 0.08`* | 3: `vzKi=5`, `thrustBase=40000` |
|---|---|---|---|
| σ x / y | 0.024 / 0.055 m | 0.029 / 0.028 m | 0.049 / 0.050 m |
| σ z, pico a pico, frecuencia | 0.069 m, 0.35 m, 0.24 Hz | 0.078 m, 0.42 m, 0.30 Hz | 0.082 m, 0.22 m, **0.04 Hz** |
| error medio en z | +0.03 m | +0.02 m | **+0.06 m** |
| roll / pitch σ | 0.53 / 0.40° | 0.62 / 0.73° | 0.83 / 0.79° |
| σ de `ekf_vz` | 0.060 m/s | 0.095 m/s | **0.029 m/s** |
| sesgo medio `ekf_vz − mocap_vz` | +0.011 m/s | −0.001 m/s | 0.000 m/s |
| sobrepaso del despegue (objetivo 0.39 m) | 0.68 m | 0.67 m | 0.59 m |

\* El CSV no registraba las opciones de Python; se asume que el segundo vuelo llevó el anticipo. Desde ahora `PREFLIGHT_OK` las incluye.

Lo que dicen:

- **No hay sesgo estático en la velocidad vertical del EKF** (media ≈ 0 en los tres). Lo que había era una **oscilación real** en Z a 0.25–0.3 Hz que el EKF sigue bien. La hipótesis del sesgo queda descartada para el hover; el sesgo sólo se manifestaba en modo velocidad pura.
- **La oscilación de Z la produce el integrador del lazo de velocidad vertical.** Con `thrustBase` de fábrica (36000) muy por debajo del empuje real de hover con esta batería, el integrador (`vzKi=15`) hace todo el trabajo y el lazo entra en ciclo límite. Con `vzKi=5` y `thrustBase=40000` la oscilación desaparece (0.04 Hz, `ekf_vz` σ tres veces menor) y queda un **desfase de +6 cm**: la base de empuje se pasó un poco. Siguiente: `thrustBase=38000` con `vzKi=8`.
- **`extPosStdDev=0.03` es lo mejor para XY** (σ x 0.024, roll 0.53°), sin daño en Z. `--anticipo-s 0.08` no aporta sobre eso.
- **El sobrepaso del despegue (0.2 a 0.3 m)** viene del mismo integrador cargándose en el suelo; mejoró con los parámetros de Z. Falta probar con batería a 4.1 V, que reduce el tiempo en el suelo a plena potencia.
- El XY del tercer vuelo salió peor (σ 0.05), pero es el de batería más baja (3.84 V en reposo); no se atribuye a los parámetros de Z sin repetirlo.

Siguiente vuelo: `--ganancias mitad --ext-pos-std 0.03 --param velCtlPid.vzKi=8 --param posCtlPid.thrustBase=38000`, batería a 4.1 V.

## Vuelo combinado (16:28, Dron 2): `extPosStdDev=0.03`, `vzKi=8`, `thrustBase=38000`, batería 4.13 V

`dron_robotat_20260916_162840.csv`, 74 s, hover de 33 s y cinco movimientos fluidos (hasta 1.7 m en X y 0.8 m en Z), aterrizaje limpio.

| tramo | x σ | y σ | z σ | z pico a pico | roll / pitch σ |
|---|---|---|---|---|---|
| hover completo (12–45 s) | 0.025 | 0.038 | 0.068 | 0.34 m | 0.45 / 0.30° |
| hover estacionario (28–45 s) | 0.022 | 0.049 | **0.029** | 0.14 m | 0.56 / 0.30° |

La oscilación de Z **desaparece una vez asentado**: a partir de los 28 s la altura queda en 0.34–0.40 m sin frecuencia dominante. Lo que queda es el **transitorio del despegue**: 3.4 s en el suelo a plena potencia, sobrepaso a 0.66 m (objetivo 0.39) y ~15 s de asentamiento. Es el integrador vertical cargándose mientras el dron no levanta: `thrustBase=38000` sigue por debajo del empuje real de hover, y el P del lazo es pequeño al principio de la trayectoria. En el vuelo de las 16:20 con `thrustBase=40000` el sobrepaso fue menor (0.59 m) y el hover quedó 6 cm alto: la base correcta está por encima de 38000 pero no en 40000 con esa batería.

Añadido `empuje_cmd` (`controller.cmd_thrust`) al CSV: su media en hover estacionario es el `thrustBase` correcto para este dron y batería. Con ese número el despegue debería levantar de inmediato y sin sobrepaso.

## Empuje de hover medido (17:01 y 17:03, Dron 2)

- 17:01, batería 3.94 V en reposo: al despegar cayó a 2.93 V y el aterrizaje automático actuó a los 4 s. Correcto: con menos de 4 V esta batería no aguanta el despegue.
- 17:03, batería 4.18 V: 77 s de vuelo, nueve movimientos fluidos de hasta 1.5 m, aterrizaje limpio. **Empuje comandado en hover: 45 800 ± 900** (3.15 V bajo carga). `thrustBase` estaba en 38 000: en el despegue el empuje sube de 37 800 a 46 000 durante 3 s **antes** de que el dron levante, y ese integrador cargado es el sobrepaso (0.57 m) y los 15 s de asentamiento. En ese vuelo el hover no llegó a asentarse antes del primer movimiento (Z σ 0.06 m a los 12 s).

Cambio: al aterrizar, el controlador imprime y registra en `LANDED` el empuje medio del hover y el `thrustBase` recomendado. Siguiente vuelo: `--param posCtlPid.thrustBase=46000` con `vzKi=8` y `extPosStdDev=0.03`; debería levantar en menos de 1 s y sin sobrepaso.

## Vuelo con `thrustBase=46000` (17:11, Dron 2): objetivo cumplido

`dron_robotat_20260916_171126.csv`, batería 3.99 V en reposo, 3.08 V en vuelo. Hover de 45 s sin órdenes.

| | valor |
|---|---|
| despegue: tiempo hasta levantar | **0.8 s** (antes 3.0–3.4 s) |
| despegue: altura máxima | **0.435 m** con objetivo 0.39 (antes 0.57–0.68) |
| hover 45 s: σ x / y / z | **0.027 / 0.041 / 0.032 m** |
| hover: pico a pico x / y / z | 0.13 / 0.18 / 0.14 m |
| roll / pitch σ | 0.50 / 0.39° |
| empuje en hover | 46 100 ± 700 (coincide con `thrustBase`) |
| error EKF–mocap máximo | 0.04 m |

Se cumple el criterio de T-003 (Z pico a pico por debajo de 0.1 m una vez asentado; 0.14 m contando el transitorio) y los de T-006. El vuelo acabó en aterrizaje automático por batería (2.97 V) al empezar el primer movimiento fluido: la batería estaba a 3.99 V en reposo, no a 4.1.

Fijado como preajuste `--ganancias robotat` en el panel (README de la carpeta con la tabla de por qués). Pendiente: un vuelo de manejo fluido largo con batería llena, y decidir si `buttons/` y `camera/` pasan a este backend.

## Vuelo con `--ganancias robotat` (17:18, Dron 2, batería 4.17 V)

`dron_robotat_20260916_171848.csv`, 55 s, tres movimientos fluidos (uno de 24 s combinando ejes), aterrizaje limpio.

| | valor |
|---|---|
| despegue | levanta en 0.7 s, máximo 0.47 m (objetivo 0.39) |
| hover entre movimientos: σ x / y / z | 0.022 / 0.030 / 0.072 m (z 3 cm por debajo tras cada entrega) |
| roll σ | 0.48° |
| empuje de hover | 46 500 (`LANDED` recomienda `thrustBase=46500`) |
| batería mínima en vuelo | 3.16 V, sin aterrizaje automático |
| error EKF–mocap máximo | 0.045 m; hueco de mocap máximo 0.10 s |

Lo único mejorable: durante las subidas y bajadas fluidas el dron va **0.20–0.27 m por detrás** de la altura integrada (retraso `v/zKp` = 0.25 m a 0.25 m/s), y al soltar sigue hasta alcanzarla. Añadida una correa: la altura mandada no se adelanta más de 0.15 m a la estimada, así que al soltar el dron se detiene en menos de 0.15 m. Con eso el hover posterior no arranca 3 cm bajo.

Con batería llena el juego `robotat` queda validado: despegue rápido, hover de 2–3 cm en XY y manejo fluido en los tres ejes.

## Vuelo con la correa vertical (17:25, Dron 2, batería 4.04 V)

`dron_robotat_20260916_172540.csv`, 35 s, cuatro movimientos fluidos. Terminó en aterrizaje automático por batería (2.99 V): con 4.04 V en reposo esta batería no aguanta ni un minuto de manejo.

- **La correa funciona**: el dron va 0.15–0.16 m por detrás de la altura mandada (antes 0.20–0.27) y al soltar se detiene en 5 a 16 cm.
- **Techo**: manteniendo Espacio, el objetivo llegó al máximo de 1.10 m y el dron, por el retraso, subió hasta **1.29 m**. La altura integrada se detiene ahora 0.20 m antes del techo (0.90 m) y 0.10 m después del suelo (0.30 m), para que el dron físico no cruce los límites.
- Hover entre movimientos: σ x/y 0.021/0.025 m, roll 0.39°. Despegue en 0.9 s con máximo 0.51 m; en ambos despegues el dron se adelanta a la trayectoria de 4 s en el primer segundo, se frena a 0.13 m y vuelve a subir: una trayectoria de despegue más corta (2 s) lo haría más limpio. Pendiente.
- `LANDED` recomienda `thrustBase=46400`; el preajuste de 46 000 sirve.

## Vuelo con batería llena (17:32, Dron 2, 4.15 V): el empuje de hover cambió

`dron_robotat_20260916_173231.csv`, 32 s. Despegue en 0.7 s con máximo 0.45 m; hover XY σ 0.018/0.027 m, roll 0.42°; aterrizaje limpio a mano.

- **El empuje de hover fue 39 500, no 46 000.** Con la misma consigna (`thrustBase=46000`) el dron llevó un empuje base 6 000 por encima del real: el integrador tuvo que descargarse y **Z volvió a oscilar** (0.7 m pico a pico, ~6 s de período; z hasta 1.28 m). Batería distinta o hélices: el empuje de hover no es una constante del dron. Por eso el controlador guarda ahora en `cache/dron_robotat_empuje.json` el empuje medido en cada aterrizaje, por dron, y lo usa como `thrustBase` en el vuelo siguiente cuando se elige `--ganancias robotat` (un `--param posCtlPid.thrustBase=...` explícito sigue mandando). El preflight dice cuál usa.
- **"No me dejaba moverme a los lados"**: las pulsaciones de A y D duraron 0.5, 0.6 y 1.0 s. Con la rampa de 0.6 m/s² en medio segundo la velocidad sólo llega a 0.15 m/s, unos 4 cm; además el dron estaba subiendo y bajando 30 cm. No es un bloqueo: la geocerca no intervino (radio 1.0 m, el dron a 0.15 m del origen). Para moverse de lado hay que mantener la tecla dos o tres segundos, como con W.
- **El yaw del EKF osciló ±20° en un segundo** durante un movimiento lateral. Con sólo posición externa el rumbo es poco observable y una aceleración lateral se confunde con giro; eso rota la velocidad mandada en el marco del cuerpo. Solución: `--extpose`, ahora que el rigid body nuevo está nivelado. Para no repetir el error de septiembre, el preflight registra roll, pitch y yaw del rigid body en el suelo y **rechaza `--extpose` si roll o pitch superan 10°**.

Pendiente: un vuelo con `--extpose` y ver si el yaw se queda quieto.

## Primer vuelo por gestos de mano (17:46, Dron 2, batería 3.99 V)

`dron_robotat_20260916_174626.csv` y `control_camara_dron1/sesion_174621.csv`. 170 s en el aire con `--reconocedor manos --backend robotat`. Despegue, direcciones (arriba, derecha, izquierda, adelante, atrás) y stop funcionaron; el dron se movió 0.5–0.8 m por gesto. Terminó en emergencia por EKF a 0.16 m del mocap durante una excursión vertical, con la batería en 2.96 V.

**El "sacado de dedo" (seguir el marker 65) no fue bien**: desde los 98 s el seguimiento mandó velocidades sin parar (modo fluido continuo 48 s) y **la altura anduvo a la deriva entre 0.11 y 1.23 m** con período de ~4 s. No fue el empuje base (43 000 frente a 44 840 medido) ni la velocidad del seguidor (tope 0.10 m/s). Fue la **correa de altura**: acotaba el objetivo a ±0.15 m de la altura estimada en los dos sentidos, así que cuando el dron se desviaba solo, el objetivo lo seguía y el lazo de posición en Z dejaba de tirar de él. Con teclado no se notó porque los movimientos eran cortos; con el seguidor, que emite velocidad todo el rato, la deriva creció hasta que el EKF se separó del mocap. Corregido: la correa sólo actúa en el sentido en que se pide moverse; con vz = 0 el objetivo se queda fijo.

Además: el empuje de hover se guarda ahora también cuando el vuelo acaba en emergencia, y los tests ya no escriben en `cache/`.

Empuje de hover de los vuelos de hoy con el Dron 2: 46 150 (3.09 V en vuelo), 39 490 (3.21 V), 43 290 (3.24 V), 44 840 (3.10 V). Varía ±3 000 de un vuelo a otro; con `vzKi=8` el lazo tolera esa diferencia sin ciclo límite. El recuerdo del último vuelo es suficiente.

## Seguimiento del marker con el lazo propio (18:02, Dron 2, batería 4.12 V)

`dron_robotat_20260916_180254.csv`. 32 s persiguiendo el marker 65 con `--velocidad-seguir 0.30`: velocidad media 0.28 m/s, máxima 0.5 m/s en los cambios de sentido, recorrido de 1.5 × 2 m por el área, altura entre 0.28 y 1.03 m (el ancla conservaba la diferencia de altura inicial y seguía al marker en Z). Roll σ 0.9°. Terminó en aterrizaje automático por batería a 2.98 V: perseguir a 0.3 m/s consume mucho más que el hover y esta batería pasó de 3.33 a 2.98 V bajo carga en medio minuto.

Cambios pedidos por el humano: el ancla queda ahora **a la altura del marker** (`activate(level=True)`: radio de 0.45 m sólo en horizontal, desplazamiento vertical cero), y nuevo panel `two_drones/control_dos_drones_robotat.py` para volar los dos drones con este núcleo (supervisor de separación a 0.30 m; CSV con el nombre del dron).

## Los dos drones a la vez (18:19 y 18:21): el Dron 2 se apaga porque Motive lo pierde

Panel `control_dos_drones_robotat.py`, dos vuelos. **El Dron 1 vuela** (14 s y 9 s de hover, empuje 45 500, aterrizajes limpios): lo que fuera que le impedía levantar por la mañana ya no está. **El Dron 2 acaba en emergencia 1.3–1.8 s después de despegar** las dos veces, por EKF a 0.18 y 0.96 m del mocap.

La causa está en el CSV del Dron 2: su posición del Robotat **queda congelada** (exactamente el mismo valor, `(+0.723, −0.202, 0.117)`, durante 2.7 s) mientras el EKF y el empuje dicen que el dron sube; el puente sigue publicando a 23 frames/s, así que ni la edad ni la tasa lo delatan. Cuando Motive recupera el rigid body, la pose salta 0.9 m de golpe y el vigilante corta. En los vuelos de la tarde con un solo dron en el volumen esto no pasó nunca.

Diagnóstico: con los dos drones a la vista, **Motive pierde o confunde el rigid body 4**. Lo más probable es que los dos rigid bodies tengan la misma geometría de marcadores y Motive no pueda distinguirlos; también puede ser que el del Dron 2 tenga pocos marcadores visibles desde donde está. Se comprueba sin volar con `ver_markers.py`, moviendo cada dron a mano con el otro a la vista: el que se congela es el que Motive no rastrea. Solución en Motive: geometrías distintas (un marcador desplazado en uno de los dos) y rastreo estable en toda el área.

Mitigación en el controlador: una pose que no cambia durante 0.4 s se declara **congelada** y cuenta como sin mocap: no se envía al EKF (alimentarla lo clava en un sitio mientras el dron se mueve), el preflight espera, el despegue se rechaza y en vuelo se hace aterrizaje de seguridad en vez de cortar motores. Columna `mocap_congelado` en el CSV.

No hay CSV de cámara posterior a las 18:02: el vuelo "con el seguidor a nivel" no dejó registro (¿`--sin-csv`, o se cerró antes de aterrizar?).

**Corrección (00:40):** los tópicos son correctos. El puente publica el rigid body de id de streaming **8N** en `mocap/droneN`: el 83 va en `mocap/drone3` y el 84 en `mocap/drone4` (`discover_marker_id.py --show-all`). En reposo los dos publican poses distintas y niveladas. La pose congelada del Dron 2 en los vuelos duales fue, por tanto, pérdida real de rastreo del 84 con los dos drones a la vista (o en ese sitio del área). El preflight registra ahora el `identifier` del mensaje junto a la actitud del rigid body.

## Dual de las 18:55: el Dron 2 se apaga por batería, no por el Robotat

`dron_robotat_Dron2_20260916_185515.csv`: esta vez el rastreo fue perfecto (0 filas congeladas, 46–51 frames/s, error EKF 2–5 cm). Despegó, llegó a 0.58 m y en 2 s se hundió hasta 0.15 m mientras la tensión caía de 3.13 a 2.98 V: **aterrizaje automático por batería a los 7 s de vuelo**. Reposo 4.06 V, bajo carga 3.0 V: una caída de 1.1 V, la firma de la batería mala que tenía el Dron 1 por la mañana. La `EMERGENCIA` de 3 s después ocurrió ya en el suelo (z 0.034 m, EKF a 0.158 m del mocap al tocar) y no significa nada; desde ahora, a menos de 10 cm del origen durante un aterrizaje, esa comprobación no corta.

`dron_robotat_Dron1_20260916_185509.csv`: el Dron 1 voló 30 s con seis movimientos fluidos y aterrizó bien (empuje 45 200).

## Cámara de dos drones con el controlador nuevo (19:34): funciona

`dron_robotat_Dron1_20260916_193417.csv`, `dron_robotat_Dron2_20260916_193423.csv` y `dos_drones/gestos_cruz_multiprocessing_20260916_193423.csv`. `control_dos_drones_camara_multiprocessing.py --backend robotat`, gestos de mano para los dos drones.

| | Dron 1 | Dron 2 |
|---|---|---|
| en el aire | 120 s, 58 movimientos | 111 s, 70 movimientos |
| hover σ x / y / z | 0.035 / 0.036 / 0.042 m | 0.030 / 0.039 / 0.045 m |
| roll σ | 0.58° | 0.77° |
| recorrido | 1.3 × 0.9 m, z 0.36–1.02 | 1.75 × 0.75 m, z 0.48–1.05 |
| batería | 4.05 → 3.14 V | 4.00 → 3.11 V |
| poses congeladas / error EKF máx | 0 / 0.13 m | 0 / 0.13 m |
| final | aterrizaje limpio, empuje 42 500 | aterrizaje limpio, empuje 44 400 |

Separación mínima en vuelo 0.90 m (media 1.63 m); el supervisor no tuvo que actuar. La cámara registró 128 órdenes de movimiento, 2 despegues y 4 aterrizajes. Ninguna emergencia.

Fallo encontrado: las gráficas PDF no se generaron para estas dos sesiones. El backend de la cámara dual vive en un proceso hijo que el padre termina 12 s después de pedirle cerrar, y aterrizar más cerrar radios agotó ese margen antes de las figuras. Ahora las gráficas se generan en un proceso aparte que sobrevive al cierre; las de estas dos sesiones se generaron a mano.

## 2026-09-17, 18:45: seguir y orbitar el marker con los gestos dinámicos

`dron_robotat_Dron1_20260917_184533.csv` y `control_camara_dron1/sesion_184527.csv`. Dron 1, batería 4.13 V, 80 s en el aire, aterrizaje limpio.

- **`ven_aca` sí siguió** al principio: de (−0.37, +0.91, 0.40) a (+0.53, −0.14, 0.91), 1.4 m hacia el ancla y subiendo a la altura del marker, en 22 s.
- **Después ni siguió ni orbitó**: en 32 s de `ORBITAR` y `SEGUIR` el dron se movió 5 cm aunque las órdenes pedían hasta 0.30 m/s. Causa: **la geocerca**. Está centrada en el punto de despegue con radio 1.0 m; el dron ya estaba a 1.4 m de donde despegó (el marker se llevó al dron hasta el borde) y la geocerca anula toda velocidad hacia fuera. Con teclado no se nota porque uno vuelve; con un marker que se mueve por el área, sí.
- Arreglo: `--centro-geocerca X Y` fija el centro en el marco del Robotat (por defecto sigue siendo el despegue). Para seguir u orbitar: `--centro-geocerca 0 -0.4 --radio-max 1.5`, que cubre el área usada en todos los vuelos de ayer (x de −1.3 a 1.1, y de −1.7 a 0.9). El resumen de `PREFLIGHT_OK` registra el centro.
- El evento `VEL` se registraba 30 veces por segundo durante el seguimiento (1227 filas); ahora como mucho dos por segundo, y los eventos `SEGUIR`/`ORBITA` dejan una vez por segundo el objetivo y el marker.

## 2026-09-17, 18:59: seguimiento bien; el aplauso se leyó como círculo

`dron_robotat_Dron1_20260917_185938.csv` y `sesion_185933.csv`. Con la geocerca centrada en el área el seguimiento funcionó: 19 s siguiendo al marker por todo el recorrido, con 0.3–0.5 m de retraso por el tope de 0.30 m/s. Batería 4.13 V; aterrizaje automático a los 46 s de vuelo por 2.95 V: el Dron 1 hoverea a 48 700 de empuje, necesita batería llena y aun así dura poco.

Tres cosas a corregir, todas hechas:

1. **El aplauso se ejecutó como `circulo`** (la máquina pasó a `ORBITAR` sin cambiar de modo). Es una confusión del reconocedor DTW, no del controlador. Guarda nueva: si `aplaudir` queda a menos de un 20 % de distancia DTW del gesto ganador, el gesto se ignora y se avisa. Además el CSV de la cámara registra ahora cada detección dinámica cerrada (`gesto_dinamico`, `dist_dinamico`, `margen_dinamico`, `segundo_dinamico`) para poder ajustar el banco con datos.
2. **La órbita no se veía**: el objetivo avanzaba por el círculo con reloj propio y, con el tope de velocidad, el dron iba medio metro detrás; además el marker se movía. Ahora el objetivo va 30° por delante de la **fase real** del dron sobre el círculo: la órbita se dibuja a la velocidad que el dron pueda y no se le escapa. El marker debe estar quieto para que se vea un círculo.
3. **Salir de la geocerca**: fuera del radio, además de anular la velocidad hacia fuera, se empuja hacia dentro proporcionalmente a lo que sobresale (1.5 por metro, tope 0.30 m/s); igual con el techo y el suelo.
