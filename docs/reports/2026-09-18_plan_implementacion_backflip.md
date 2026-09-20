# Solución propuesta para implementar un backflip en el Crazyflie

**Fecha:** 18 de septiembre de 2026  
**Estado:** diseño basado en literatura y revisión del repositorio; sin pruebas de hardware.

## Decisión recomendada

Implementar una **trayectoria de una vuelta de 0.9 s y un controlador geométrico en el firmware del Crazyflie 2.1**, usando el Robotat para fijar la posición antes del giro, registrar el movimiento y recuperar la posición después. No ejecutar el lazo acrobático desde Python.

Esta arquitectura resuelve el principal problema observado en la simulación anterior: el controlador híbrido sencillo completó el giro nominal, pero sólo alcanzó 64.3% de éxito bajo incertidumbre. Antal, Péni y Tóth probaron el controlador geométrico en un Crazyflie 2.1 real y obtuvieron 10 ejecuciones iguales en 10 intentos. El mismo trabajo advierte que la secuencia puramente feedforward pierde estabilidad con errores pequeños en el estado inicial.

## Por qué el controlador actual no basta

`controllers/shared/dron_robotat.py` usa el commander high-level para despegar, ir a una posición y aterrizar, y `send_hover_setpoint` a 20 Hz para movimiento fluido. Esos modos mantienen el dron aproximadamente nivelado y no describen una rotación completa.

El backflip exige:

- control de actitud y velocidad angular a 500 Hz;
- referencias continuas en `SO(3)` o cuaterniones, sin singularidad en 180°;
- empuje y torque cercanos a los límites físicos;
- transición determinista entre seguimiento normal, trayectoria acrobática y recuperación;
- continuidad aun cuando el enlace de radio tenga retrasos o pierda un paquete.

El firmware oficial ejecuta el lazo de velocidad angular a 500 Hz. El puerto de setpoints permite referencias de estado completo, pero mandar la maniobra desde el PC seguiría introduciendo radio, Windows y Python en el camino crítico. El paper que consiguió el backflip real también amplió el firmware y dejó el PC para gestión y registro.

## Solución técnica

### 1. Identificar la plataforma real

Antes de reutilizar parámetros hay que registrar para cada dron:

- modelo: Crazyflie 2.1 con motores brushed o Crazyflie 2.1 Brushless;
- masa total con batería, marcadores y decks;
- geometría y momento de inercia alrededor de pitch;
- empuje máximo y curva empuje/PWM con batería cargada y descargada;
- centro de masa, hélices y sentido de giro;
- frecuencia y latencia reales del Robotat.

El modelo MATLAB anterior usa el Brushless de 44 g. El paper de Antal usa el Crazyflie 2.1 convencional de 28 g, `Jyy = 1.4e-5 kg m²`, longitud motor a motor de 92 mm y empuje colectivo máximo de 0.64 N. Los parámetros no son intercambiables.

### 2. Generar la trayectoria fuera de línea

Partir de `scripts/flip_traj_design.m` del repositorio abierto de los autores y eliminar su dependencia opcional de MOSEK usando `quadprog`, que el propio paper contempla. La referencia publicada usa:

- duración: 0.9 s;
- periodo: 2 ms, equivalente a 500 Hz;
- rotación completa alrededor de pitch;
- empuje colectivo `0 <= F <= 0.64 N`;
- límites relativos del planificador: `x` entre -0.15 y 0 m y `z` entre 0 y 0.30 m;
- ganancias publicadas: `kr = 4.5`, `kv = 0.3`, `kR = 0.2`, `kOmega = 0.002`.

La salida debe convertirse en una tabla fija con tiempo, posición, velocidad, aceleración, cuaternión y velocidad angular. Esa tabla se genera en MATLAB y se compila dentro de la aplicación de firmware; no se calcula durante el vuelo.

### 3. Ejecutar el control en el Crazyflie

Crear una aplicación de firmware fuera del árbol principal o un controlador seleccionable que contenga:

1. `IDLE`: control normal y espera.
2. `ARMED`: acepta la maniobra sólo si posición, actitud, batería y Robotat están dentro de tolerancias.
3. `TRACK_FLIP`: reproduce la tabla a 500 Hz con control geométrico de actitud y fuerza.
4. `RECOVER`: vuelve al controlador de posición cuando el cuaternión está cerca de nivel y la velocidad angular es pequeña.
5. `ABORT`: corta la referencia acrobática y aplica la recuperación disponible; cerca del suelo, aplica el procedimiento de emergencia definido para el ensayo.

El disparo puede llegar desde Python como un parámetro o paquete de una sola vez. Después del disparo, el firmware termina la maniobra de forma autónoma.

### 4. Usar correctamente el Robotat

Durante la vuelta, la actitud rápida debe provenir del giróscopo y del estimador interno. El Robotat se usa para:

- comprobar que el dron comenzó nivelado y en el centro de la zona;
- aportar posición y orientación externas antes y después del giro;
- medir la trayectoria real con independencia del estimador;
- decidir si la recuperación terminó dentro de la geocerca.

No conviene cerrar el torque de pitch desde la posición Robotat: su retraso observado de 60–120 ms es demasiado grande frente a una maniobra de 0.9 s. Además, durante una rotación rápida pueden existir pérdidas o ambigüedades de orientación del rigid body.

### 5. Integración en este repositorio

Ubicación propuesta:

```text
controllers/single_drone/backflip/
    generar_trayectoria_backflip.m
    simular_backflip.m
    ejecutar_backflip.py
    README.md
    tests/

firmware/backflip_app/       # sólo si se decide versionar aquí la app fuera de árbol
```

`ejecutar_backflip.py` debe reutilizar `MocapFeed`, preflight, batería, CSV y parada de `controllers/shared/`, pero mantener una interfaz separada de `DronRobotat`. La maniobra no debe añadirse como otro movimiento de `send_hover_setpoint`.

Campos adicionales del CSV:

- fase de la maniobra;
- cuaternión y velocidad angular medida/deseada;
- empuje y torques deseados;
- saturación por motor;
- edad del Robotat;
- razón exacta de aborto o recuperación.

## Compuertas de validación

### Etapa A: modelo identificado

- La masa y geometría corresponden al dron real.
- La curva de empuje predice hover y empuje máximo dentro de 5%.
- La simulación reproduce vuelos normales registrados antes de probar el giro.

### Etapa B: simulación

- 1000/1000 corridas sin contacto con el suelo dentro de la incertidumbre medida.
- Error final de actitud menor que 10°.
- Velocidad angular final menor que 60°/s.
- Ningún motor permanece saturado más tiempo que el previsto por la trayectoria.
- La trayectoria completa cabe en la zona disponible con margen adicional.

### Etapa C: firmware sin hélices

- La máquina de estados avanza con el tiempo correcto.
- La tabla produce referencias continuas.
- El watchdog, aborto y retorno al controlador normal funcionan.
- El firmware registra la trayectoria a 500 Hz o en una frecuencia suficiente para reconstruirla.

### Etapa D: banco de empuje

- Verificar asignación y signo del torque de pitch.
- Confirmar empuje máximo con batería en los extremos permitidos.
- Confirmar que ningún comando supera los límites del motor o ESC.

### Etapa E: vuelo protegido

Requiere una zona cerrada, red o jaula, suelo amortiguado, distancia suficiente en todas las direcciones, un operador dedicado al corte y repuestos. Primero se validan impulso y recuperación por separado; la vuelta completa se habilita cuando ambas etapas coinciden con la simulación.

## Espacio de vuelo

El controlador geométrico publicado planifica sólo 0.30 m de desplazamiento vertical relativo y 0.15 m horizontal en simulación. En hardware, el feedforward mostró aproximadamente cuatro veces el desplazamiento horizontal simulado y 23% más desplazamiento vertical. Por ello, el margen de la arena debe basarse en ensayos y Monte Carlo, no sólo en los límites nominales.

La geocerca actual del repositorio permite alturas objetivo de 0.20 a 1.10 m. No debe ampliarse para acomodar el modelo Brushless anterior. Primero se debe regenerar y validar una trayectoria para el Crazyflie real; luego se calcula una altura inicial que mantenga toda la envolvente dentro de la zona física y del rango medible por el Robotat.

## Implementación mínima frente a implementación robusta

| Alternativa | Trabajo | Robustez observada | Recomendación |
|---|---:|---:|---|
| Cinco fases feedforward | Bajo | Sensible al estado inicial y parámetros | Sólo referencia y banco |
| PID de velocidad angular desde Python | Medio | Dependiente del enlace y 20–100 Hz | Descartar |
| Setpoints de estado completo por radio | Medio | Lazo interno rápido, referencia dependiente del radio | Útil para simulación/HIL |
| Control geométrico dentro del firmware | Alto | 10/10 en el paper | Implementación inicial recomendada |
| Geométrico robusto con GP/LUT | Muy alto | Mejor con masa y dinámica alteradas | Segunda fase |

## Qué falta para comenzar

1. Confirmar el modelo exacto del Crazyflie y sus accesorios.
2. Medir masa total y obtener firmware exacto instalado.
3. Definir las dimensiones libres de la zona Robotat.
4. Elegir si la aplicación de firmware se mantiene como repositorio externo o dentro de `firmware/backflip_app/`.
5. Crear una tarea del vault con criterios de aceptación; el protocolo del repositorio exige una tarea antes de modificar controladores.

## Referencias

- P. Antal, T. Péni y R. Tóth, *Backflipping with Miniature Quadcopters by Gaussian Process Based Control and Planning*. [Paper](https://arxiv.org/abs/2209.14652) · [Código](https://github.com/AIMotionLab-SZTAKI/crazyflie_backflipping)
- A. Gräfe et al., *How to Model Your Crazyflie Brushless*. [Paper](https://arxiv.org/abs/2603.05944)
- Bitcraze, documentación de [controladores del firmware](https://www.bitcraze.io/documentation/repository/crazyflie-firmware/master/functional-areas/sensor-to-control/controllers/), [setpoints genéricos](https://www.bitcraze.io/documentation/repository/crazyflie-firmware/master/functional-areas/crtp/crtp_generic_setpoint/) y [commander framework](https://www.bitcraze.io/documentation/repository/crazyflie-firmware/master/functional-areas/sensor-to-control/commanders_setpoints/).
