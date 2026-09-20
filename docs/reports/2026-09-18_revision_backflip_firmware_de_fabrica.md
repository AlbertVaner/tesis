# Revisión del plan de backflip y alternativa con el firmware de fábrica

**Fecha:** 18 de septiembre de 2026
**Estado:** revisión documental y simulación; no se conectó ni se voló ningún dron.
**Revisa:** [plan de implementación](2026-09-18_plan_implementacion_backflip.md) y [simulación en MATLAB](2026-09-18_simulacion_backflip_matlab.md).

## Qué está bien en los reportes de Codex

- El diagnóstico central es correcto: `send_hover_setpoint` y el commander high-level mantienen el dron nivelado y no pueden describir una vuelta; y cerrar el giro desde Python sobre el mocap (60–120 ms) no es viable.
- La referencia es la adecuada: Antal, Péni y Tóth lo lograron en un Crazyflie 2.1 de escobillas, 10 de 10 con control geométrico **dentro del firmware**, y advierten que el feedforward puro es sensible al estado inicial.
- El plan reconoce que el modelo de MATLAB (Brushless, 44 g) no es intercambiable con el dron real.

## Qué falla o falta

1. **La simulación de MATLAB no describe los drones del laboratorio.** Usa el Brushless de 44 g (1.1 N de empuje), arranca a 2.5 m y recorre 2.1 m en vertical. Los drones son Crazyflie 2.1 de escobillas con marcadores. Sus CSV no sirven para dimensionar nada en el Robotat.
2. **El margen de empuje real es menor que el del paper.** Del empuje de hover recordado (`cache/dron_robotat_empuje.json`) y la curva PWM→empuje de Bitcraze:

   | Dron | hover (de 65535) | masa equivalente | aceleración máxima |
   |---|---:|---:|---:|
   | Dron 1 | 45700 | ≈ 38 g | ≈ 16 m/s² (1.65 g) |
   | Dron 2 | 41400 | ≈ 33 g | ≈ 18.5 m/s² (1.9 g) |
   | CF 2.1 del paper | — | 28 g | ≈ 23 m/s² (2.3 g) |

   La maniobra publicada pide 17.8 m/s² en el impulso y en la recuperación. El Dron 2 llega justo con batería llena; el Dron 1 no llega. La trayectoria de 0.9 s del paper no se puede copiar: hay que regenerarla con el empuje real, y saldrá más alta y más larga.
3. **El plan salta directamente a firmware propio sin evaluar lo que ya trae el de fábrica.** El TOC cacheado de los drones muestra `flightmode.stabModeRoll/Pitch/Yaw`, `pid_rate.*`, `supervisor.tmblChckEn` y los controladores Mellinger y Lee. Con `stabModePitch = 0` (rate), `send_setpoint` entrega una **velocidad angular** al lazo de 500 Hz del firmware, sin límite ni escalado (`crtp_commander_rpyt.c`). El PC sólo manda tres órdenes; el lazo rápido no pasa por la radio.
4. **No menciona la detección de vuelco.** El supervisor corta motores con `acc.z < 0.5 g` sostenido 1 s o invertido 100 ms. Un giro de ~0.4 s con empuje positivo no debería dispararla, pero hay que fijar `supervisor.tmblChckEn=0` sólo durante la maniobra y restaurarlo al terminar.
5. **No menciona la singularidad de Euler del PID de fábrica.** Al pasar por 90° de pitch, roll y yaw de Euler saltan 180°. Durante el giro, roll debe ir también en modo rate y `pid_attitude.yaw_kp/yaw_ki` a 0, o el lazo de actitud pelea contra el giro. Un giro de **roll** no tiene este problema (roll de Euler es continuo en ±180°); es la razón por la que casi todos los flips vistos en Crazyflie son laterales.
6. **El espacio.** La geocerca actual admite objetivos de 0.20 a 1.10 m. Ninguna variante cabe ahí (ver abajo).

## Alternativa: tres órdenes sobre el firmware de fábrica

| Fase | Orden desde Python | Quién cierra el lazo |
|---|---|---|
| IMPULSO | `send_setpoint(0, 0, 0, máx)` en modo rate | lazo rate del firmware, 500 Hz |
| GIRO | `send_setpoint(0, ±Q, 0, bajo)` | lazo rate del firmware, 500 Hz |
| RECUPERA | `send_hover_setpoint(0, 0, 0, z)` al ver ≥ 270° acumulados (giroscopio integrado, vía log) | PID de actitud, velocidad y altura del firmware, con el Robotat alimentando el EKF |

Simulada en `thesis/simulations/backflip/simular_backflip_cf21_modo_rate.py` con el PID de rate de fábrica (250/500/2.5), recorte de empuje, motores de escobillas con retardo asimétrico, latencia de radio de 10–40 ms y edad del log de 15–45 ms. Monte Carlo de 500 corridas (inercia ±20 %, batería 85–100 %, inclinación inicial ±4°):

| Dron | éxito | sube (p95) | cae bajo el inicio (p95 / peor) | retrocede en x (p95) |
|---|---:|---:|---:|---:|
| Dron 1 (38 g) | 81.6 % | 1.11 m | 0.60 / 1.51 m | 1.13 m |
| Dron 2 (33 g) | 97.2 % | 0.79 m | 0.42 / 1.02 m | 1.11 m |
| CF 2.1 sin marcadores (25 g) | 100 % | 0.49 m | 0.36 / 0.71 m | 1.52 m |

Lectura: la rotación sale casi siempre (el lazo de 500 Hz es del firmware); lo que falla es la **altura**, igual que en el Monte Carlo de Codex. El peso decide: con el Dron 2 es plausible, con el Dron 1 no. Hace falta arrancar a ≥ 1.2 m con ~1 m libre encima y ~1.5 m libres detrás, es decir, ampliar geocerca y techo sólo para la maniobra.

Límites de esta simulación: plana, sin aerodinámica ni estimador; la masa sale de una curva genérica, no de una balanza; las constantes de tiempo de los motores son supuestas. No autoriza un vuelo.

## Recomendación

1. **No empezar por firmware propio.** Validar primero la vía de tres órdenes, que no exige toolchain ni flasheo y reutiliza `DronRobotat`. Si la repetibilidad medida no alcanza, entonces sí el controlador geométrico a bordo del plan de Codex, con la trayectoria regenerada para la masa real.
2. **Usar el Dron 2, aligerado si se puede, y batería recién cargada** (rechazar la maniobra por debajo de ~3.9 V en vuelo).
3. **Empezar por el flip de roll**, que evita la singularidad de Euler; el backflip de pitch después, con yaw_kp a 0 durante el giro.
4. **Integración con el gesto:** `arco` hoy produce `ALEJARSE`, que está en `SIN_VUELO` (`control_camara_dron1.py`). El punto de enganche es ese: `arco` → `VueloRobotat.request_flip()` → `DronRobotat.voltereta()`. La maniobra vive en el núcleo (`controllers/shared/dron_robotat.py`) porque necesita su hilo de mando y su cerrojo; sólo con `--backend robotat`, sólo con un dron, y sólo con un `--permitir-voltereta` explícito.
5. **Compuertas antes de volar:** (a) sin hélices: desbloqueo de empuje (`thrustLocked` exige un paquete con empuje 0 antes), signo del rate de pitch, restauración de parámetros y del tumble check; (b) con hélices y atado o con red: sólo IMPULSO + RECUPERA; (c) giro completo sobre suelo acolchado.

## Fuentes

- Antal, Péni y Tóth, [Backflipping with Miniature Quadcopters…](https://arxiv.org/abs/2209.14652) y su [código](https://github.com/AIMotionLab-SZTAKI/crazyflie_backflipping).
- Firmware de Bitcraze: [`crtp_commander_rpyt.c`](https://github.com/bitcraze/crazyflie-firmware/blob/master/src/modules/src/crtp_commander_rpyt.c), [`controller_pid.c`](https://github.com/bitcraze/crazyflie-firmware/blob/master/src/modules/src/controller/controller_pid.c), [`supervisor.c`](https://github.com/bitcraze/crazyflie-firmware/blob/master/src/modules/src/supervisor.c), [`platform_defaults_cf2.h`](https://github.com/bitcraze/crazyflie-firmware/blob/master/src/platform/interface/platform_defaults_cf2.h).
- Foro de Bitcraze: [rate setpoints desde Python](https://forum.bitcraze.io/viewtopic.php?t=4583).
