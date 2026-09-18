---
fecha: 2026-09-12
tipo: analisis
autor: claude
estado: revisar
---
# Oscilación en el primer vuelo por gestos (Dron 1, vocabulario completo)

Sesión `results/data/dos_drones/2026-09-12/python_highlevel_cruz_20260912_104357.csv` (backend) y `results/data/control_camara_dron1/2026-09-12/sesion_104353.csv` (cámara). Gráficas en `results/graphs/dos_drones/2026-09-12/python_highlevel_cruz_20260912_104357/`. Todo lo de abajo es medido sobre esos CSV.

## Qué pasó

| | |
|---|---|
| Despegue (senalero) | 76.3 s, a 0.38 m |
| Vuelo | 21.0 s, todo en `TAKEOFF_HIGHLEVEL`: hover puro del commander high-level |
| Órdenes de la cámara | **ninguna**. Modo dinámico todo el vuelo, ningún `move`, ningún seguimiento |
| Fin | 97.4 s, `EMERGENCIA_HIGHLEVEL`: EKF-MoCap = 0.158 m > 0.15 m |
| Cámara | 30.6 fps mediana, seguimiento PTZ activo |

**La oscilación es del hover del firmware, no del controlador por gestos.** El nuevo código no mandó ni una orden de movimiento durante el vuelo.

## La oscilación

| eje | σ (mocap − objetivo) | pico a pico | frecuencia |
|---|---|---|---|
| x | 0.137 m | 0.71 m | 0.43 Hz |
| y | 0.158 m | 0.66 m | 0.38 Hz |
| z | 0.180 m | 0.70 m | 0.33 Hz |

Inclinación: roll σ 5.6°, pitch σ 4.5°, picos de 12°. Velocidad vertical hasta 0.68 m/s subiendo y 0.88 m/s bajando. Es la misma firma de 0.4 Hz de la [auditoría](2026-09-12%20Auditor%C3%ADa%20del%20controlador%20de%20dos%20drones.md), hoy más amplia.

## Qué dicen los datos sobre las causas

**1. El dron corrige hacia donde debe: no hay marco girado.** Ángulo entre la aceleración del dron (segunda derivada del mocap) y el error de posición: 115 de 117 muestras entre 150° y 180°, es decir, acelera hacia la referencia. Un EKF con yaw 90° equivocado habría dado ~90°. La hipótesis de T-003 ("los drones miran a +Y y el EKF asume yaw 0") **no explica esta oscilación**; el EKF con extpos observa el yaw en cuanto el dron se mueve.

**2. El EKF va detrás del mocap.** Correlación cruzada entre `mocap_*` y `ekf_*`: retardo de +60 ms en x, +100 ms en y, +20 ms en z. El vector (EKF − mocap) apunta contra la velocidad en 113 de 131 muestras: es retardo, no ruido. A 0.9 m/s, 100 ms son 0.09 m, y por eso el umbral de 0.15 m de la emergencia se alcanza en una excursión rápida: **la emergencia fue consecuencia de la oscilación, no su causa**.

**3. La batería estaba agotada.** 3.89 V en reposo, 3.57 V al despegar, 2.82 a 3.08 V en vuelo, nivel 0 %. La tensión adelantada 1.5 s correlaciona −0.87 con la altura: cada ráfaga de empuje hunde la tensión y el dron sube tarde y de más. El eje z estuvo limitado por potencia. La regla E de la auditoría pide ≥ 3.7 V en reposo antes de despegar; hoy no se cumplió.

**4. El mocap llegó limpio.** 21 Hz, intervalo mediana 47 ms, máximo 51 ms, antigüedad máxima 63 ms. Sin huecos. Las 46 corridas high-level registradas desde agosto muestran lo mismo: intervalo máximo ≤ 0.06 s en todas menos dos (0.11 s). **Los huecos de 0.3 s de la auditoría no aparecen en los CSV del backend**; si existen, están antes del punto donde el backend mide.

## Lo que dice la comparación entre sesiones

Métricas en el aire de las 46 corridas (`python_highlevel_cruz_*`, agosto y septiembre):

- **Frecuencia 0.37 a 0.44 Hz en todas**, un dron o dos, Dron 1 o Dron 2.
- **σ XY entre 0.05 y 0.25 m** sin relación clara con la batería: con mínimo de 3.38 V también salen 0.14 m. La batería agrava (hoy 0.21 m con 2.82 V) pero no crea la oscilación.
- **Retardo EKF de 0 a 100 ms** en todas.
- Hoy la corrida fue **sin ninguna orden desde Python**: la oscilación vive en el lazo firmware + extpos.

Descartado con estos datos: marco girado (punto 1), huecos del mocap (punto 4), órdenes solapadas de Python (no hubo), acoplamiento entre drones (un dron solo).

Queda una causa compatible con todo: **el lazo de posición del firmware alimentado con una posición externa retrasada** (Robotat → MQTT → Python → radio; lo medible desde aquí son 60 a 100 ms, el tramo Robotat → PC no se ve en el CSV) con los pesos y ganancias por defecto (`locSrv.extPosStdDev` no se fija; `posCtlPid` de fábrica). Un retardo así en un lazo de posición produce justamente una oscilación lenta y sostenida a frecuencia constante, independiente de la batería y del número de drones.

## Segunda prueba (10:56): batería "cargada", misma caída

`python_highlevel_cruz_20260912_105621.csv`. Hover de 11.4 s, emergencia otra vez por EKF-MoCap = 0.158 m. Sin órdenes de la cámara (el aplauso llegó después del corte).

| | primera (10:43) | segunda (10:56) |
|---|---|---|
| batería en reposo | 3.89 V | **4.14 V** |
| batería nada más despegar | 3.07 V | **3.02 V** |
| mínimo en vuelo | 2.82 V | 2.91 V |
| σ x / y / z | 0.137 / 0.158 / 0.180 m | **0.047** / 0.131 / 0.158 m |
| pico a pico x / y / z | 0.71 / 0.66 / 0.70 m | 0.19 / 0.53 / 0.44 m |
| frecuencia x / y / z | 0.43 / 0.38 / 0.33 Hz | 0.35 / 0.44 / 0.18 Hz |
| roll σ / pitch σ | 5.6° / 4.5° | 4.6° / **1.6°** |
| retardo EKF x / y | +60 / +100 ms | +80 / +120 ms |
| mocap | 21 Hz, máx 51 ms | 21 Hz, máx 60 ms |

Dos cosas nuevas:

- **La batería cae 1.1 V al encender motores, salga de 3.89 o de 4.14 V.** Una batería sana del Crazyflie cae 0.3 a 0.4 V en hover. Una caída así es resistencia interna (batería vieja o dañada) o un consumo anormal (hélices o motores). No se arregla con software y limita el empuje: el eje z sigue con 0.44 m pico a pico y ahora a 0.18 Hz, la respuesta de un dron que no tiene margen para subir.
- **Con x quieto, la oscilación se concentra en y y en roll.** x bajó a σ 0.047 m con pitch σ 1.6°; y sigue en 0.13 m a 0.44 Hz con roll σ 4.6°. Sigue corrigiendo hacia la referencia (28 de 30 muestras). El retardo del EKF es mayor en y (120 ms) que en x (80 ms) en las dos pruebas.

## Tercera y cuarta prueba (11:26 Dron 1, 11:39 Dron 2): la batería queda descartada

| | Dron 1, 11:26 | **Dron 2, 11:39** |
|---|---|---|
| batería reposo → 2 s tras despegar → mínimo | 4.11 → 3.01 → 2.82 V | **4.12 → 3.50 → 3.35 V** |
| vuelo | 8.9 s, hover | 15.8 s, hover + un `go_to` (aplaudir → ABAJO) |
| σ x / y / z | 0.106 / 0.160 / 0.172 m | 0.132 / 0.167 / 0.146 m |
| pico a pico x / y / z | 0.47 / 0.64 / 0.49 m | 0.65 / 0.76 / 0.52 m |
| frecuencia x / y | 0.34 / 0.34 Hz | 0.38 / 0.38 Hz |
| roll σ / pitch σ | 5.5° / 3.8° | 6.1° / 4.6° |
| retardo EKF x / y | +60 / +100 ms | +80 / +80 ms |
| fin | emergencia 0.154 m | emergencia 0.184 m |

**El Dron 2, con batería sana, oscila exactamente igual.** Con eso la batería
sale de la lista de causas de la oscilación en x e y, y también en z: el Dron 2
tuvo 0.52 m pico a pico en z con 3.4 V bajo carga. La batería del Dron 1 sigue
estando mal (cae 1.1 V las tres veces; el Dron 2 cae 0.6 V) y hay que cambiarla,
pero no es lo que hace oscilar.

De paso, el vuelo del Dron 2 fue el primero con el vocabulario completo
actuando: aplaudir cambió a modo estático y ABAJO produjo un `go_to` a 0.30 m.
La emergencia llegó 8 s después, durante una excursión de 0.42 m en y.

Lo que queda en pie, cuatro vuelos, dos aparatos, dos baterías, mocap limpio
las cuatro veces y ninguna orden de Python en tres de ellas: **el lazo de
posición del firmware, alimentado por extpos a 20 Hz con 60 a 120 ms de
retardo, es inestable con los pesos y ganancias de fábrica.** Es lo único común.

## Qué probar, en orden

El controlador ya tiene `--param grupo.nombre=valor` (repetible), que fija
parámetros del firmware tras conectar y los imprime en el preflight. Viven en
RAM: al reiniciar el dron vuelven los de fábrica. Un nombre inexistente se
avisa y no frena a los demás. Con el Dron 2, que tiene la batería buena.

0. **Bajar ganancias y velocidad máxima del lazo de posición.** Un lazo
   inestable por retardo se estabiliza bajando la ganancia; el tope de
   velocidad limita además la excursión que dispara la emergencia. Es la
   primera prueba porque es la que tiene el efecto más seguro.
   `posCtlPid.xKp=1.0 yKp=1.0`, `velCtlPid.vxKp=12 vyKp=12`,
   `posCtlPid.xVelMax=0.5 yVelMax=0.5`.


1. **Cambiar la batería del Dron 1.** Ya no es un experimento sino mantenimiento: cae 1.1 V al encender motores en tres vuelos seguidos y se apagó sola entre el segundo y el tercero.
2. **Medir la latencia completa** Robotat → EKF: marca de tiempo del Robotat en el mensaje MQTT contra la recepción, y el retardo EKF de este análisis. Es el número que falta para decidir.
3. **Un hover con `locSrv.extPosStdDev` en 0.03 y luego 0.05** (hoy es el 0.01 de fábrica). Menos confianza en una medida retrasada suaviza el lazo; si σ XY baja y la frecuencia cambia, la causa es la del punto anterior.
4. Si 0 y 3 no bastan, **compensar el retardo antes de enviarlo**: extrapolar la posición del mocap con su velocidad (`p + v · τ`, τ ≈ 0.1 s) en `drone_unit.py` antes de `send_extpos`. Es lo que ataca la causa en vez del síntoma, y cae dentro de T-003, que ya toca ese envío.
5. Añadir al `analizar_sesion_dos_drones.py` el retardo EKF-mocap por correlación cruzada y el ángulo aceleración-error, que son los dos números que hoy hubo que calcular a mano (extiende la mejora H).

## Para T-005

El vuelo cumple el criterio del paso 3 en lo que toca al controlador: senalero despegó, la cámara siguió al operador, el CSV y la gráfica están, y la emergencia del backend cortó bien. Lo que no se pudo probar es aplaudir, los estáticos y ven_aca, porque la emergencia llegó a los 21 s. Se repite con batería cargada.
