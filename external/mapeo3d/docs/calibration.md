# Calibración y marco de coordenadas

Estado: `[parcial]` — intrínsecos, detección de tablero, campo de visión y
**extrínsecos estéreo** `[implementado]`. El anclaje al marco del Robotat con el
Crazyflie y la integridad ArUco siguen `[planeado]`.

`calibration/` es **la única dueña de las matrices de proyección**. Ningún otro módulo las construye ni asume un orden de cámaras.

## Las dos mitades del problema

| | Qué es | Cada cuánto | Cómo se obtiene |
|---|---|---|---|
| **Intrínsecos** | matriz `K` y coeficientes de distorsión, por cámara | una vez por cámara, si no cambia el lente | tablero de ajedrez o ChArUco |
| **Extrínsecos** | rotación `R` y traslación `t` de cada cámara respecto al marco Robotat | cada vez que una cámara se mueve | ver abajo |

La matriz de proyección de cada cámara es `P = K · [R | t]`, y es lo único que consume [triangulation.md](triangulation.md).

## Intrínsecos

`[implementado]` en `src/mapeo3d/calibration/`, app `apps/calibrate_intrinsics.py`.

Procedimiento estándar de OpenCV: tablero de ajedrez, ~20 capturas cubriendo todo el cuadro y varias inclinaciones, `cv2.calibrateCamera`.

**El ajuste devuelve el campo de visión real**, derivado de `fx` y `fy`, que sustituye a medirlo con cinta métrica:

```
fov_h = 2·atan(ancho / (2·fx))       fov_v = 2·atan(alto / (2·fy))
```

`CameraIntrinsics.distancia_minima(alto, altura_camara)` responde directamente a la pregunta que condiciona el montaje: a qué distancia hay que poner la cámara para que una persona quepa entera.

### Detección en dos pasadas

Buscar el tablero a 2304×1296 con el detector exhaustivo cuesta **más de 5 segundos por frame**: la vista en vivo se vuelve inusable. Por eso la detección va en dos pasadas:

| Pasada | Cuándo | Cómo | Coste |
|---|---|---|---|
| Vista previa | cada frame | imagen reducida a 960 px, sin subpíxel | ~16 ms |
| Exacta | sólo al capturar | frame completo, detector clásico + `cornerSubPix` | ~18 ms |

El detector clásico va primero porque con refinamiento subpíxel da la misma
precisión que el «sector based» exhaustivo y cuesta **300 veces menos**. El SB
exhaustivo queda como respaldo para cuando el clásico falla (imagen movida, mal
iluminada); ahí sí cuesta segundos, pero sólo se paga cuando hace falta.

La vista previa sólo sirve para saber si el tablero está en cuadro y dónde: sitúa las esquinas con ~1 px de error, suficiente para dibujar el overlay y para decidir si la vista es nueva. **Las esquinas que se guardan para calibrar son siempre las de la pasada exacta**, sobre el frame a resolución completa.

Si la vista sigue lenta: `--detect-width 640` o `--detect-every 2`.

### Las capturas se guardan antes de calibrar

Capturar 20 vistas cuesta diez minutos de trabajo manual; calibrar cuesta
segundos. Por eso la app escribe `puntos_<camara>.npz` con las esquinas **antes**
de calibrar, y cualquier fallo posterior se reintenta con:

```
python apps/calibrate_intrinsics.py --from-points results/calibration/<fecha>/puntos_cam1.npz
```

Esto se añadió después de que un fallo en el cálculo del error por vista
tirara 20 capturas ya tomadas. La lección general: **lo que cuesta trabajo
humano se persiste en cuanto existe**, no al final del proceso.

**Advertencias que la app aplica sola:**

- Rechaza vistas casi idénticas a otra ya capturada. Veinte fotos del tablero en el mismo sitio no son veinte vistas: son una repetida, y el ajuste queda mal condicionado con un RMS engañosamente bueno.
- Exige al menos 5 vistas y recomienda 20.
- Avisa si el RMS supera 0.5 px.
- Al leer de una carpeta, descarta imágenes de resolución distinta: los intrínsecos son específicos de la resolución.

### El tablero: generarlo, no descargarlo

`[implementado]` en `apps/make_chessboard.py`.

**La impresora casi nunca respeta la escala del PDF**, porque el diálogo de impresión aplica «ajustar a la página» por defecto. Un error de escala del 3 % se propaga a **todo** lo métrico del sistema —posiciones, distancias, separaciones— y no da ningún síntoma: simplemente todo sale consistentemente mal.

Por eso el generador imprime, junto al tablero, una **regla de verificación de 100 mm**. Se mide después de imprimir; si no da 100 mm exactos, la impresión está escalada.

Elección de tamaño:

| Papel | Casilla | Tablero | Distancia de calibración |
|---|---|---|---|
| Carta | 24 mm | 240 × 168 mm | 0.6 – 1.0 m |
| Oficio | 24 mm | 240 × 168 mm | 0.6 – 1.0 m |
| A4 | 23 mm | 230 × 161 mm | 0.6 – 1.0 m |
| **Doble carta** | **33 mm** | **330 × 231 mm** | **1.0 – 1.4 m** |
| A3 | 35 mm | 350 × 245 mm | 1.0 – 1.5 m |

Todos salen en horizontal: es la orientación que aprovecha el papel con un
patrón de 10×7 casillas. El generador la elige solo.

**Los intrínsecos no dependen de la distancia**, así que se calibra de cerca —donde el tablero llena buena parte del cuadro— aunque la cámara vaya a operar a 3 m. Calibrar con el tablero pequeño y lejano da esquinas mal localizadas y una calibración pobre.

El patrón por defecto es 9×6 esquinas interiores. Que las dos dimensiones sean distintas y una par y otra impar no es casualidad: elimina la ambigüedad de orientación de 180°.

Dos advertencias que importan con estas cámaras:

- **Capturar a resolución completa**, aunque en operación se use 720p. Los intrínsecos escalan de forma conocida; la nitidez no se recupera.
- Las cámaras IP tienen lentes de ángulo amplio con distorsión apreciable en los bordes. **Rectificar antes de cualquier uso geométrico.** Si no se rectifica, la homografía y la triangulación absorben la distorsión como error y el residual sube sin explicación aparente.

Se guarda en `results/calibration/<AAAA-MM-DD>/intrinsics_<camara>.yaml` junto con el error de reproyección del ajuste. Un error medio por encima de ~0.5 px indica una calibración pobre; repetirla.

## Extrínsecos estéreo (entre dos cámaras)

`[implementado]` en `src/mapeo3d/calibration/extrinsics.py`, app `apps/calibrate_stereo.py`.

Da la pose de la cámara B respecto de la A: es lo que falta para triangular.
Los intrínsecos **se fijan** (`CALIB_FIX_INTRINSIC`): ya están medidos con más
vistas y mejor condicionadas de las que aporta una sesión estéreo, y dejarlos
libres sólo añade parámetros que el dato no determina.

**La sincronización deja de ser un problema.** Las cámaras IP no están
sincronizadas por hardware, y observar el mismo instante desde dos vistas
normalmente lo exigiría. Pero la captura exige que el tablero esté **quieto**, y
con el tablero quieto da igual que una cámara vea el frame 30 ms después que la
otra. La misma puerta de quietud que evita los frames movidos resuelve de paso
la sincronización.

### El tablero puede verse mucho más pequeño que en intrínsecos

Es contraintuitivo pero está medido. En intrínsecos el tamaño manda porque se
está estimando la focal, y para eso el tablero tiene que subtender un ángulo
grande: el mínimo es el 20 % del ancho. **En estéreo los intrínsecos van fijos y
sólo se estiman 6 parámetros** (R y T) a partir de ~1000 correspondencias
repartidas en 18 pares. El sistema está enormemente sobredeterminado.

Error de escala reconstruida, medido en simulación con ruido de detección
conservador (0.5 px):

| Tamaño del tablero | Lado en px | Error de escala |
|---|---|---|
| 3.0 % | 69 | +6.96 % — inservible |
| 3.7 % | 86 | +3.17 % — malo |
| 4.5 % | 103 | +1.67 % — límite |
| **6.3 %** | **146** | **+0.34 % — bien** |
| 8.8 % | 203 | +0.17 % |
| 12.9 % | 297 | +0.09 % |

El codo está sobre el 6 %. `EXTENT_MINIMO_ESTEREO` se fija en **8 %** para dejar
margen — menos de la mitad del umbral de intrínsecos.

Y el detector encuentra el tablero hasta el 4 % del ancho (92 px), así que el
límite lo pone la precisión, no la detección.

### Se comprueba que las cámaras no se movieron durante la sesión

`[implementado]` — `analizar_coherencia()` en `extrinsics.py`.

Es el fallo más caro de esta etapa y hay que detectarlo explícitamente, porque
**no se distingue de «datos ruidosos» mirando el RMS**.

Cada par del tablero determina, por sí solo, la pose relativa completa entre
las dos cámaras: basta resolver PnP en cada una y componer. Si las cámaras no
se movieron, los 18 pares dan la misma respuesta. Si una se reapunta a mitad de
sesión, los pares de antes y los de después describen geometrías distintas, y
`stereoCalibrate` intenta ajustar **una** pose rígida a **dos** configuraciones:
sale un RMS enorme sin ninguna pista de la causa.

Cómo se detecta: se toma la pose de cada par como hipótesis, se **reajusta
sobre sus propios inliers** —la pose de un solo par no siempre es fiable, PnP
sobre un patrón plano tiene una ambigüedad de dos soluciones que se agrava
cuando el tablero se ve casi de frente— y se cuenta cuántos pares encajan por
debajo de `UMBRAL_COHERENCIA_PX`. El grupo mayor es el consenso. Si los que
quedan fuera forman **otro** grupo grande y los dos están **separados en el
tiempo**, no es ruido disperso: es un cambio de configuración.

El umbral está medido en simulación con distorsión e intrínsecos realistas,
contando sesiones marcadas como «una cámara se movió»:

| | ruido 0.5 px | 1 px | 2 px |
|---|---|---|---|
| cámaras quietas | 0/8 | 0/5 | 0/5 |
| movida 28° | 8/8 | 5/5 | — |
| movida 10° | 8/8 | — | 3/5 |
| movida 5° | — | — | 3/5 |

Ningún falso positivo. A 3 px un grupo real se fragmenta y el movimiento pasa
desapercibido; a **5 px** los grupos salen enteros. Movimientos por debajo de
lo que se detecta aquí aportan menos error que el propio ruido de detección.

Cuando se detecta, `calibrate_stereo()` **lanza `ParesIncoherentes` y no
calibra**. No es prudencia excesiva: no hay una pose que describa los dos
grupos, y además no se sabe en cuál de las dos configuraciones están las
cámaras ahora. Lo correcto es fijarlas y repetir. Con `--solo-pares` se puede
rescatar un grupo si se sabe que las cámaras siguen en esa posición.

La app además corre la comprobación **durante la captura**, a partir del octavo
par, y avisa en pantalla en cuanto la geometría cambia. Detectarlo en el momento
es la diferencia entre volver a colocar la cámara y repetir la sesión entera.

### Rectificar antes de triangular no es opcional

Las matrices de proyección `K[R|T]` describen cámaras **estenopeicas ideales**.
Las esquinas detectadas no lo son: llevan la distorsión del objetivo. Triangular
las coordenadas tal como salen del detector mete esa distorsión directamente en
la reconstrucción.

Lo traicionero es que **no rompe nada visible**: el residual de reproyección
puede seguir siendo bajo, porque `stereoCalibrate` sí modela la distorsión. Lo
que sale sesgado es la escala. Medido sobre una sesión real con Tapo C210
(k1 ≈ −0.42):

| | casilla reconstruida | error |
|---|---|---|
| sin rectificar | 22.49 mm ± 0.95 | **−6.3 %** |
| rectificando | 24.02 mm ± 0.14 | +0.09 % |

Un −6 % de escala se confunde fácilmente con un problema del montaje o del
tablero impreso, y no lo es. `CameraIntrinsics.undistort_points()` es el paso
que falta, y todo consumidor de `triangulation/` tiene que aplicarlo.

### La comprobación que sí prueba que está bien

**Triangular el tablero y medir la casilla reconstruida.** Si el tablero mide
24 mm y la reconstrucción da 24 mm, la cadena entera —intrínsecos, extrínsecos y
escala— es correcta.

Esto importa porque **un error de escala reproyecta perfectamente**: el RMS no
lo detecta. Es la única verificación absoluta disponible sin instrumentación
externa. La app la hace sola y avisa si el error pasa del 2 %.

Verificado en simulación con pose conocida: línea base real 1.500 m recuperada
como 1.5003 m, ángulo real 30.0° recuperado como 30.01°, y casilla de 24.00 mm
reconstruida como 24.019 mm (+0.08 %).

## Extrínsecos en el marco del Robotat: un blanco que el MoCap rastrea

Esta es la parte específica de este laboratorio y la que hace que todo encaje.

El problema habitual de la calibración extrínseca multicámara es conseguir correspondencias 3D↔2D fiables y bien repartidas por el volumen. En este laboratorio la mitad está resuelta de fábrica: **el MoCap del Robotat conoce la posición 3D de cualquier cuerpo rígido con marcadores con precisión milimétrica**, y la publica por MQTT como posición más cuaternión.

### Lo que hace falta, y por qué el Crazyflie solo no basta

Un blanco de calibración tiene que cumplir **tres** condiciones a la vez:

1. Su posición 3D es conocida en el marco del Robotat.
2. Es detectable **con precisión subpíxel** en cada cámara IP.
3. La asociación entre lo detectado y el punto 3D es inequívoca.

El Crazyflie cumple la 1 —lleva marcadores pasivos y el MoCap lo rastrea— pero **no la 2**. Sus marcadores son retrorreflectivos: brillan en infrarrojo, iluminados por los estrobos del OptiTrack, y en luz visible son bolitas grises sin nada que las distinga del fondo. Sus LEDs propios son indicadores de estado, no una baliza: pocos milímetros, poca potencia, y a 3 m no dan un blob fiable ni un centroide preciso.

Las cámaras IP **sí** verían los marcadores retrorreflectivos en modo nocturno, porque un retrorreflector devuelve la luz hacia su fuente y el iluminador IR de la cámara está justo al lado del sensor. Pero eso exige encender los IR de las seis cámaras, que es precisamente lo que ciega al OptiTrack — y el OptiTrack es la verdad de terreno que se necesita **al mismo tiempo**. No es una opción.

Conclusión: hay que **añadir al blanco algo visible en luz normal**, solidario con los marcadores pasivos.

### Opción recomendada: bola de color en el centroide de un clúster de marcadores

Una varilla rígida con tres o cuatro marcadores pasivos repartidos **simétricamente alrededor de una bola de color saturado** (naranja o verde, mate, tipo pelota de ping-pong).

- El MoCap la rastrea como cuerpo rígido; con los marcadores simétricos, el pivote por defecto cae en el centroide, **que es el centro de la bola**. La posición que llega por MQTT es directamente la del blanco visible, sin desfase que medir.
- Las cámaras la detectan por umbral en HSV más circularidad, que en luz normal es robusto y barato.
- Se pasea por el volumen a distintas alturas durante un minuto y salen cientos de correspondencias 3D↔2D por cámara.

Es el procedimiento original con la baliza cambiada, y **no necesita volar, ni penumbra, ni tocar los IR**.

Procedimiento:

1. Pasear la varilla por todo el volumen de trabajo, despacio y a distintas alturas.
2. Registrar simultáneamente la posición 3D del MoCap y los frames de todas las cámaras, emparejados por `MultiCameraSync`.
3. Detectar la bola en cada cámara y descartar frames ambiguos (más de un candidato, o candidato en el borde).
4. `cv2.solvePnPRansac` por cámara para la pose inicial, y después un ajuste de haces conjunto que refine todas a la vez.

El resultado son extrínsecos **directamente en el marco de coordenadas del Robotat**: operador y dron en el mismo sistema. Y cada cámara se calibra **por su cuenta**, sin necesidad de compartir campo de visión con ninguna otra — que es la propiedad que hace que esto escale a seis y el tablero no.

### Opción de más precisión: tablero ChArUco rastreado como cuerpo rígido

Marcadores pasivos pegados a un tablero **ChArUco** rígido. Cada observación da la pose completa de 6 grados de libertad en lugar de un punto, así que bastan decenas de observaciones en vez de cientos de puntos, y la orientación queda mucho mejor determinada.

ChArUco y no tablero de ajedrez clásico por una razón que importa con seis cámaras: **tolera oclusión y visibilidad parcial**. El detector clásico es todo o nada, y en una sala grande el tablero casi nunca se ve entero desde las seis.

El precio es un paso más: hay que conocer la transformación entre el cuerpo rígido que define Motive y el origen del patrón impreso. No hace falta medirla a mano — es el problema clásico *robot-world/hand-eye*, y `cv2.calibrateRobotWorldHandEye` (métodos `LI` o `SHAH`) lo resuelve junto con la pose de la cámara a partir de los mismos datos. Hay que tener cuidado con el convenio de marcos: la configuración es *cámara fija, blanco en movimiento*, que es la dual de la habitual.

### Opción sin nada que sostener: marcadores ArUco fijos, medidos una vez

Tags ArUco impresos y pegados en puntos fijos de la sala, a distintas alturas y profundidades. Se miden sus esquinas **una sola vez** con un marcador del MoCap, y a partir de ahí cada cámara resuelve PnP contra los tags que vea.

Ventaja específica: **son los mismos tags que pide la comprobación de integridad entre sesiones** descrita más abajo. Se montan una vez y sirven para las dos cosas.

Desventaja: el levantamiento inicial es manual y es donde entra el error; y hay que asegurarse de que cada cámara vea tags suficientes y bien repartidos en profundidad.

### Si se quiere el procedimiento original

Existe el *LED-ring deck* de Bitcraze, un anillo RGB direccionable y genuinamente brillante. Con él montado, el Crazyflie sí cumple la condición 2 y el plan de volar la baliza por el volumen funciona tal cual. Es la única vía que aprovecha que el blanco vuele solo.

### Herramientas externas

`Caliscope` (GUI) y `aniposelib` (biblioteca, con ajuste de haces y tableros ChArUco) resuelven la calibración multicámara genérica y pueden usarse para obtener una primera calibración válida. `Pose2Sim` acepta calibraciones importadas de varios formatos. Ninguna de ellas conoce el marco del Robotat, así que el paso 5 de arriba —o una transformación rígida posterior medida contra puntos MoCap conocidos— sigue siendo necesario.

## Homografía del suelo: para qué sirve y para qué no

Una homografía mapea **plano a plano**, y sólo es válida para puntos que están físicamente sobre el plano calibrado.

- **Sirve** para obtener la posición (X, Y) del operador en el suelo a partir del **punto de contacto con el suelo** (punto medio entre tobillos, o mejor talones). Ese punto sí está en el plano.
- **No sirve** aplicada al centroide de la persona ni a la cadera. Esos puntos no están en el plano, y la homografía los proyecta a donde el rayo cámara→punto corta el suelo, que está mucho más lejos:

  ```
  d_aparente = d_real · h_cámara / (h_cámara − h_punto)
  ```

  Con cámara a 2.5 m, cadera a 1.0 m y persona a 4 m: da 6.67 m. Error sistemático de 2.7 m, dependiente de la estatura. **No es un sesgo a calibrar: es el método aplicado fuera de su dominio.**

Con triangulación multicámara la homografía deja de ser necesaria para la posición. Se conserva como comprobación cruzada barata y como respaldo si queda una sola cámara operativa.

## Integridad de la calibración: el riesgo número uno

Las cámaras actuales son **pan/tilt motorizadas**. Cualquier movimiento del motor —desde la app, por un modo patrulla, por seguimiento automático de movimiento, o por el re-centrado que algunas hacen al reiniciar— **invalida los extrínsecos sin producir ningún síntoma visible**. La imagen se ve perfecta y la triangulación devuelve números plausibles y equivocados.

Mitigación obligatoria, en dos capas:

1. **Preventiva.** Desactivar patrulla y seguimiento de movimiento en todas las cámaras. Ningún módulo de este repositorio debe emitir comandos PTZ.
2. **Detectiva durante la calibración.** `[implementado]` — la comprobación de coherencia entre pares descrita más arriba. Cubre el caso de que una cámara se mueva mientras se calibra, que es cuando más fácil es que ocurra y cuando el síntoma es más confuso.
3. **Detectiva entre sesiones.** Un **marcador ArUco fijo** pegado en un punto estático dentro del campo de visión de cada cámara. Al arrancar cualquier sesión, se detecta el marcador y se compara su posición observada con la esperada según la calibración vigente. Si se desvía más de unos pocos píxeles, **la sesión se detiene con un error claro** en lugar de producir datos malos.

Esta comprobación debe implementarse temprano, no al final. Es más barato que descubrir a mitad de la tesis que un mes de datos está sesgado.

## Artefactos

```
results/calibration/<AAAA-MM-DD>/
├── intrinsics_<camara>.yaml     K, distorsión, error de reproyección
├── extrinsics.yaml              R, t por cámara, en marco Robotat
├── projection.yaml              P por cámara (derivado, para consumo directo)
├── aruco_reference.yaml         posición esperada del marcador de integridad
└── report.md                    residuales, número de puntos, fecha, quién
```

`report.md` no es opcional. Una calibración sin su residual documentado no es utilizable como referencia y no puede citarse en la tesis.
