# Triangulación y filtrado

Estado: `[parcial]` — el DLT de N vistas, el error de reproyección, el ángulo
entre rayos y la comprobación métrica de rejilla están `[implementado]` en
`dlt.py`; **las tres capas de robustez** en `robust.py`; y la **estabilidad de
longitud de segmentos** en `metrics.py`. El filtrado temporal sigue
`[planeado]`.

Este módulo no sabe qué es RTSP ni qué es MediaPipe. Recibe landmarks 2D con matrices de proyección y devuelve puntos 3D con su residual. **Debe poder probarse íntegramente con datos sintéticos, sin cámaras.**

## Precondición: los puntos entran rectificados

`P_i = K_i[R_i|T_i]` describe una cámara **estenopeica ideal**. Los landmarks
que salen de un detector, no: llevan la distorsión del objetivo. Entre detectar
y triangular hay siempre un paso de `CameraIntrinsics.undistort_points()`.

Es una precondición fácil de saltarse porque **no falla de forma visible**: el
residual de reproyección puede seguir siendo bajo y los puntos 3D parecen
razonables. Lo que sale mal es la escala, de forma sistemática. Con las Tapo
C210 (k1 ≈ −0.42) se midió un **−6.3 %** en la casilla reconstruida, que
desaparece al rectificar (+0.09 %). Ver `docs/calibration.md`.

Este módulo **no rectifica por su cuenta**: no conoce los intrínsecos, sólo las
matrices de proyección. La responsabilidad es de quien llama.

## El método: DLT de N vistas

Para un punto 3D `X` visto por la cámara `i` con matriz de proyección `P_i` en la posición de imagen `(u_i, v_i)`, cada vista aporta dos ecuaciones lineales:

```
u_i · (P_i fila 3) − (P_i fila 1) = 0
v_i · (P_i fila 3) − (P_i fila 2) = 0
```

Se apilan las filas de todas las vistas en una matriz `A` de tamaño `(2N, 4)` y se resuelve `A·X = 0` por SVD: `X` es el vector singular derecho asociado al valor singular más pequeño, deshomogeneizado.

La consecuencia práctica es importante: **el DLT es N-vistas por naturaleza**. Pasar de 2 a 6 cámaras es apilar más filas, no cambiar de algoritmo. No hace falta triangular por pares y promediar.

## Robustez: lo que hay que añadir encima

`[implementado]` en `robust.py`: `triangulate_robust()` para un punto,
`triangulate_landmarks()` para un esqueleto entero.

El DLT desnudo trata todas las vistas por igual, y no todas merecen lo mismo. Tres capas, en orden:

### 1. Ponderación por confianza

Cada landmark viene con una confianza del estimador 2D. Multiplicar las dos filas de esa vista por su peso antes del SVD. Una vista donde el estimador apenas ve el codo debe influir poco, no igual.

### 2. Rechazo de vistas discrepantes

Un estimador 2D no falla suavemente: **alucina**. Confunde el codo izquierdo con el derecho, o coloca una muñeca en un objeto del fondo, y lo reporta con confianza alta. Una sola vista así arrastra el punto 3D varios centímetros.

Estrategia: RANSAC sobre subconjuntos de vistas. Se triangula con subconjuntos mínimos, se calcula el error de reproyección en todas las vistas, y se conserva el consenso mayor. Con 6 cámaras hay margen de sobra para descartar 1-2 vistas malas.

Alternativa más barata y también válida: triangular con todas, calcular el residual por vista, eliminar la peor si supera un umbral, y repetir mientras queden al menos 2 vistas. Es lo que hace `Pose2Sim` y funciona bien.

**Es la que está implementada**, con `UMBRAL_VISTA_PX = 12`. Con seis cámaras
sobra margen y evita el costo de RANSAC en el lazo de tiempo real.

**Con seis cámaras esta capa deja de ser opcional.** Con las cámaras en anillo,
en todo momento la mitad ve al operador **de espaldas**; MediaPipe sigue
devolviendo landmarks desde atrás, con izquierda y derecha intercambiadas y sin
que la confianza lo refleje. Sin rechazo, las muñecas saltan de un lado al otro
del cuerpo.

### 3. Umbral de aceptación

Un landmark triangulado con residual alto o con menos de 2 vistas **no se reporta como válido**: se marca `NaN` con confianza 0. Es mejor que el consumidor sepa que no hay dato a que reciba un número inventado.

## El residual es parte de la salida, no un detalle de depuración

Cada landmark del `PoseFrame3D` lleva su error de reproyección en píxeles y el número de vistas que contribuyeron. Sin eso, el consumidor no puede distinguir un codo bien medido de uno reconstruido a duras penas desde dos vistas casi colineales, y un sistema de control que no puede hacer esa distinción no es seguro.

## Geometría: por qué el ángulo importa más que el número de cámaras

La incertidumbre de la triangulación no depende de cuántas cámaras hay, sino del **ángulo entre los rayos**. Dos cámaras que ven al sujeto casi desde la misma dirección dan una elipse de error muy alargada en profundidad, por muy separadas que estén físicamente.

- El ángulo útil entre pares de vistas está alrededor de **60-90°** visto desde el operador.
- **Los extremos son igual de malos.** Cerca de 0° los rayos son casi paralelos; cerca de 180° son casi opuestos, es decir, colineales. En ambos casos la intersección queda indeterminada a lo largo de la línea de visión. Un par de cámaras en esquinas opuestas de la sala, con el operador en el centro, cae exactamente en el segundo caso.
- Con el operador en el centro y las cámaras en las esquinas de la sala de 4 × 5 m, los pares adyacentes dan 77° y 103° —zona óptima— y los pares diagonales dan 180°, inservibles. Ver [hardware.md](hardware.md).
- **La selección de vistas debe descartar los pares casi colineales**, no sólo los de ángulo pequeño. Un criterio simple: exigir que el ángulo entre rayos esté entre 20° y 160°.
- `angulo_util_deg()` lo resume en un número: la calidad de un par es
  `min(t, 180 - t)`, y la del conjunto es la del **mejor** par, porque basta una
  pareja bien condicionada para fijar la profundidad. Así, 60° y 120° puntúan
  igual, que es lo correcto.
- **La altura de montaje rescata al par opuesto.** Dos cámaras enfrentadas sólo
  son exactamente colineales si están a la altura del punto observado. Con un
  anillo de 2.5 m de radio y las cámaras a 1.6 m, el par opuesto da 18° de
  calidad sobre el pecho —por debajo del mínimo— pero 27° sobre la cadera.
  Subirlas aleja al par opuesto de la degeneración. Medido en
  `tests/test_robust.py`.
- Al elegir qué vistas usar en tiempo real, si hay que reducir por costo de CPU, **elegir por diversidad angular**, no por confianza ni por orden.

## Validar sin verdad de terreno: longitud de huesos

`[implementado]` en `metrics.py`: `segment_lengths()` y
`segment_length_stability()`.

El problema: cómo saber si la reconstrucción es buena cuando no hay con qué
compararla. El residual no alcanza —un error de escala reproyecta
perfectamente— y el MoCap sólo está en sesiones preparadas.

Es la misma idea que `grid_spacing()` aplicada a un cuerpo: **el antebrazo mide
lo mismo en todos los frames de una sesión**. No hace falta saber cuánto mide;
basta con que no cambie. La desviación de su longitud reconstruida a lo largo
del tiempo es una medida directa de la calidad del 3D, y sale de una persona
moviéndose libremente, sin marcadores, sin objeto de referencia y sin MoCap.

Se reporta el **coeficiente de variación** por segmento, `desviación / media`,
porque un muslo y un antebrazo no tienen por qué tener la misma desviación
absoluta para estar igual de bien medidos. `variacion_media` condensa la sesión
en un número comparable.

Los doce segmentos usados están en `pose.HUESOS` — sólo tramos entre
articulaciones separadas por hueso, nada que cruce cabeza, manos o pies, donde
los landmarks son estimaciones de superficie y su separación cambia con la
pose. `triangulation/` no conoce esos nombres: recibe pares de índices desde
`pose.pares_de_huesos()`.

**Es la medida con la que comparar la triangulación calibrada contra
`pose_world_landmarks` de MediaPipe** sobre la misma grabación. Ver
[pose.md](pose.md).

## Filtrado temporal

`[planeado]`

**Antes de invertir aquí, conviene saber contra qué error se está peleando.**
Medido sobre `pose_world_landmarks` con una persona real, un filtro de mediana
de 5 frames elimina sólo el **5-6 %** de la variación de longitud de huesos: el
error de la estimación monocular es sesgo dependiente de la pose, no temblor
entre frames, y el filtrado no lo toca. Ver [pose.md](pose.md).

Eso no invalida el filtrado —la triangulación tiene otras fuentes de error, y
la suavidad importa para el control— pero sí dice que **no es la palanca
grande**. La palanca grande es la geometría: más vistas y mejor ángulo.

Después de triangular, antes de publicar:

- **Filtro de una euro (One Euro)** por landmark. Es el estándar práctico para señales interactivas: poco retraso en movimiento rápido y buena suavidad en reposo, con dos parámetros interpretables. Preferible a un Butterworth de fase cero, que necesita la señal completa y por tanto no sirve en línea.
- **Restricción de longitud de huesos.** Los segmentos del cuerpo tienen longitud constante. Estimarla en los primeros segundos de una sesión y usarla después como regularizador es una de las mejoras más baratas y efectivas disponibles.
- **Rechazo de saltos.** Un landmark que se desplaza más de lo físicamente posible entre frames consecutivos es un error de asociación, no un movimiento. Descartarlo y mantener el anterior con confianza degradada.

Todo el filtrado debe poder desactivarse por configuración: para el capítulo experimental hace falta poder reportar el error **sin** filtrar, que es la medida honesta de la calidad de la triangulación.

## Validación

Tres niveles, de menor a mayor costo:

1. **Sintético, sin cámaras.** Se define un punto 3D conocido, se proyecta con matrices sintéticas, se añade ruido gaussiano a las proyecciones, y se comprueba que la reconstrucción vuelve al punto original dentro de la tolerancia esperada. **Es prueba obligatoria y debe correr en CI.**
2. **Error de reproyección en operación.** El residual medio sobre una sesión real, por landmark. No requiere verdad de terreno y detecta degradación de calibración.
3. **Contra el MoCap.** Poner marcadores retrorreflectivos en muñecas y tobillos **únicamente durante la sesión de validación**, no en operación, y comparar la triangulación markerless contra el OptiTrack como verdad de terreno. Es la medida que se reporta en la tesis.

Para el nivel 3, la referencia metodológica es Nakano et al. (2020), *Evaluation of 3D Markerless Motion Capture Accuracy Using OpenPose With Multiple Video Cameras*: 5 cámaras, DLT, validado contra MoCap marcado, con ~47 % de errores bajo 20 mm y 80 % bajo 30 mm. Reportar los resultados en el mismo formato permite comparación directa con literatura publicada.

## Referencia de implementación

- `TemugeB/bodypose3d` — MediaPipe + DLT/SVD con dos cámaras, en tiempo real sobre CPU. Es el punto de partida más directo; hay que generalizarlo a N vistas y añadirle las tres capas de robustez de arriba.
- `Pose2Sim` — pipeline maduro, **no en tiempo real**. Su implementación de triangulación ponderada con exclusión progresiva de cámaras es buena referencia de diseño, y sirve como vara de medir offline sobre las mismas grabaciones.
- `aniposelib` — calibración y triangulación con ajuste de haces, usable de forma independiente.
