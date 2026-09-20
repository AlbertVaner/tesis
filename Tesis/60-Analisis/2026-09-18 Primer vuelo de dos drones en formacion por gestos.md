---
fecha: 2026-09-18
tipo: analisis
---
# Primer vuelo de dos drones en formación por gestos

Sesión de las 17:33 (`results/data/dron_robotat/2026-09-18/dron_robotat_Dron1_20260918_173331.csv`, `..._Dron2_20260918_173336.csv`, cámara `control_camara_dron1/2026-09-18/sesion_173326.csv`). `control_camara_dron1.py --dron ambos`, 110 s en el aire. Hover σ 3-5 cm por eje en los dos.

## Lo que funcionó
- Despegue de los dos, `ven_aca` (seguir) 37 s con las anclas a 0.63 m entre sí, modo estático, `circulo` (orbitar).
- Reconocimiento estático tras la recalibración de la tarde: ADELANTE 2.1 s, ABAJO 1.1 s, ARRIBA 3.9 s e IZQUIERDA 3.3 s confirmados y sostenidos.

## Fallo 1 — el vuelo lo terminó el supervisor de separación
Orbitando, los drones llegaron a **0.29 m** (t=123 s) y `SupervisorSeparacion` aterrizó a los dos. Entraron a la órbita a 52° uno del otro; la regulación por desfase cerraba unos 8°/s; y el operador movió el marker 1.3 m en 3 s (de x=+1.25 a x=−0.04), con lo que los dos quedaron del mismo lado del círculo y sus objetivos coincidieron: (0.72, 0.29) y (0.72, 0.31).

Cambios en `two_drones/formacion_camara.py`: **repulsión directa** entre drones (por debajo de 0.60 m horizontales se empuja a cada uno en sentido opuesto al otro y se atenúa la orden original hasta anularla a 0.40 m; se instala en cada `VueloRobotat` por `modificar_velocidad` y actúa también en seguir y en las direcciones), y regulación de desfase más fuerte (escala mínima 0.55→0.35, ganancia 0.25→0.50). Simulado en lazo cerrado con el marker saltando 1.3 m en 3 s: la separación no baja de 0.35 m. El supervisor sigue siendo la última red.

## Fallo 2 — el error en Z se comía la velocidad horizontal
El marker va en la mano del operador, a 1.2-1.5 m; el modo fluido no pasa de 0.90 m. El error vertical no se anulaba nunca: 0.4-0.6 m, que con Kp 1.5 son 0.6-0.9 m/s hacia arriba. Como la velocidad total se acota a 0.30 m/s, con `uz=+0.9, uy=−0.5` quedaban **0.14 m/s en horizontal**. Es la causa de que seguir y orbitar salieran lentos y poco marcados, también en los vuelos de un dron de esa tarde. `vuelo_camara.altura_alcanzable` recorta la altura del objetivo a la banda que el modo fluido puede mantener.

## Fallo 3 — las direcciones estáticas salieron al revés
Se voló con `--rumbo 0` (se asume que el operador mira a +X). De las anclas del seguimiento se deduce dónde estaba: marker en (1.16, −0.15) y drones hacia (−0.91, +0.42) desde él, o sea el operador miraba a **~155° desde +X**, casi −X. Con rumbo 0, ADELANTE movió los drones a +X (**hacia el operador**, x de 0.68 a 0.75 y de 0.77 a 0.96) e IZQUIERDA a +Y, que era su derecha. Hay que volar con `--rumbo 180` desde esa posición.

## Pendiente
- DERECHA no se confirmó en vuelo (tres parpadeos de 2-4 frames entre t=76 y 82 s) aunque en las grabaciones guiadas salía al 94 %. El CSV del controlador no guarda las medidas del brazo, así que no se puede saber por qué. Sospecha: el operador llevaba el marker en esa mano.
- Batería: 3.36 V bajo carga al despegar y 3.07-3.10 V de mínimo, a décimas del aterrizaje automático. Con dos drones, el que se agota aterriza también al otro.

## Segundo vuelo en formación, 17:51

67 s en el aire con `--rumbo` corregido. **Los seis gestos estáticos funcionaron**: ARRIBA 3.2 s, DERECHA 4.8 s, IZQUIERDA (a trozos de 0.3-1.9 s, sigue siendo la más floja), ADELANTE 6.1 s. Terminó con el **Dron 2 cayendo con los motores cortados** desde 0.87 m al empezar el seguimiento.

Causa: la **telemetría del Dron 2 se congeló 7.8 s** (desde t=72.5 s dejaron de cambiar a la vez EKF, actitud, batería y empuje). El dron volaba bien: mantenía el hover con ±10 cm de deriva y seguía recibiendo posición externa. La vigilancia comparó el mocap vivo con un EKF de hacía 8 s; el "error" creció con la deriva normal, 0.098 → 0.152 m, cruzó el umbral de 0.15 y **cortó motores** por una divergencia que no existía. Al caer el Dron 2, la formación aterrizó el Dron 1, como está diseñado.

No fue la velocidad recuperada con el arreglo de Z: el corte llegó 0.3 s después de empezar a seguir, con el dron casi quieto. En el Dron 1, con hasta 0.6 m/s, el error EKF-mocap no pasó de 0.02 m.

Las congelaciones de telemetría son frecuentes con dos radios: 16-39 s en tres sesiones de esa tarde que no llegaron a despegar, y ninguna mayor de 0.3 s en los vuelos de un solo dron mientras volaba.

Cambio en `controllers/shared/dron_robotat.py`: `Estado.ekf_edad_s` y `TELEMETRIA_TIMEOUT_S = 1.0`. Con la telemetría vieja el error EKF-mocap **no se evalúa**, y si no vuelve en 1 s se **aterriza** en vez de cortar. Con telemetría fresca, un EKF a más de 0.15 m sigue cortando motores. Pendiente: averiguar por qué se congela (saturación del enlace de bajada con dos Crazyradio, o interferencia).

Además: `CONFIRMACION_ABAJO_S = 0.45` (antes 0.20). Bajar el brazo desde cualquier gesto barre el cono de ABAJO; hubo cinco ABAJO de 0.0-0.3 s, uno justo al acabar el ADELANTE, y cada uno fue un tirón hacia abajo.

## Tercer vuelo en formación, 18:05 — el vocabulario completo

147 s en el aire: señalero, `circulo` (8 s), estáticos, `ven_aca` (32 s), estáticos y un segundo `circulo`. Sin congelaciones de telemetría (máx. 0.1 s), error EKF-mocap máx. 0.08 m, velocidad horizontal hasta 0.5-0.8 m/s con el arreglo de Z. Vídeo de la interfaz: `results/captures/control_camara_dron1/2026-09-18/sesion_180534.mp4` (54 MB).

Terminó otra vez con los drones a **0.28 m** en la segunda órbita y el supervisor aterrizando a los dos. Esta vez la causa se pudo aislar reproduciendo la lógica sobre las posiciones reales:

1. **La oposición funcionaba**: desfase entre 180° y 200° durante toda la órbita.
2. **El radio no**: los drones orbitaban a 0.15-0.30 m del centro en vez de a 0.50. Perseguir un punto 30° por delante sobre el círculo tiene su equilibrio en `R·cos30° − 0.067` = 0.37 m, porque la cuerda apunta hacia dentro.
3. **Y sobre todo, las geocercas.** Cada `DronRobotat` tiene la suya centrada en su propio despegue. Despegaron en (0.01, −0.83) y (0.06, +0.71), a 1.54 m, con radio 1.0: la zona común era una lente de **0.46 m de ancho**. En los últimos 3 s el Dron 1 estaba a 1.05 m de su origen y el Dron 2 a 0.97-1.04 del suyo: cada cerca le quitaba a su dron la componente hacia fuera y lo empujaba hacia dentro, o sea **hacia el otro**. La cerca se aplica en el núcleo, después de la repulsión, y ganaba: las órdenes decían separarse (+y para uno, −y para el otro) y las velocidades reales eran las contrarias. Es muy probable que fuera también la causa del primer acercamiento, a las 17:33.

Cambios:
- `formacion_camara.py`: **geocerca común** tras el preflight (centro en el punto medio de los dos despegues, o el de `--centro-geocerca`), y despegue rechazado con instrucciones si algún dron queda a menos de 0.30 m del borde. Repulsión desde 0.80 m (dura a 0.55), anclas del seguimiento a ±70° (0.85 m), radio mínimo de órbita 0.60 m.
- `vuelo_camara.py`: `velocidad_de_orbita`, ley polar (tangencial más corrección radial) que sí mantiene el radio; y la escala de velocidad de la formación ya no frena la repulsión.

Batería: despegaron con 3.24 V bajo carga (no se habían cambiado) y el Dron 2 bajó a 2.96 V, por debajo del umbral de aterrizaje de 3.0.
