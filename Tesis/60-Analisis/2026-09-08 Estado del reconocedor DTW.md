---
fecha: 2026-09-08
tipo: analisis
autor: claude
estado: revisar
---
# Estado del reconocedor DTW: validación y qué falta

Qué se hizo hoy: se añadió a la validación lo que faltaba para que las cifras se
puedan defender en el documento —**validación anidada por sujeto** y **precisión,
exhaustividad y F1 por clase**— y se volvieron a construir los dos bancos con el
material que hay. Todo lo de abajo es medido, no estimado.

## La cifra

**El reconocedor dinámico acierta el 77.6 % sobre una persona que no aportó
plantillas, con macro-F1 0.77.** Es el vocabulario de cinco gestos
(`senalero`, `aplaudir`, `ven_aca`, `arco`, `circulo`) más una clase de rechazo,
sobre 263 tomas de 5 sujetos.

El número que se venía reportando era 79.5 %. La diferencia no es un error: el
79.5 % se calcula con un umbral que se eligió mirando esas mismas distancias, y
el 77.6 % con un umbral que nunca vio a la persona evaluada. **La fuga costaba
1.9 puntos**, menos de lo que se temía, pero ahora está separada y se puede
citar sin nota al pie.

| | LOSO simple | LOSO anidado | macro-F1 |
|---|---|---|---|
| Vocabulario de 5 gestos (263 tomas, 5 sujetos) | 79.5 % | **77.6 %** | 0.77 |
| Banco de 3 gestos reetiquetado (102 tomas, 10 sujetos) | 83.3 % | **81.4 %** | 0.82 |

Azar: 17 % y 25 % respectivamente.

## Matriz de confusión, vocabulario de cinco gestos

Validación anidada, con umbral y rechazo. `(rechazado)` es "el sistema no emite
ningún comando", que es la salida correcta para un movimiento ajeno.

| real \ leído | (rechazado) | aplaudir | arco | circulo | senalero | ven_aca |
|---|---|---|---|---|---|---|
| **(rechazado)** | **24** | 5 | 2 | 6 | 2 | 2 |
| **aplaudir** | 2 | **41** | 1 | 0 | 1 | 0 |
| **arco** | 12 | 5 | **24** | 0 | 1 | 1 |
| **circulo** | 3 | 0 | 0 | **40** | 1 | 2 |
| **senalero** | 0 | 3 | 0 | 0 | **41** | 0 |
| **ven_aca** | 1 | 9 | 0 | 0 | 0 | **34** |

| clase | soporte | precisión | exhaustividad | F1 |
|---|---|---|---|---|
| senalero | 44 | 0.89 | 0.93 | **0.91** |
| circulo | 46 | 0.87 | 0.87 | **0.87** |
| ven_aca | 44 | 0.87 | 0.77 | **0.82** |
| aplaudir | 45 | 0.65 | 0.91 | **0.76** |
| arco | 43 | 0.89 | 0.56 | **0.69** |
| (rechazado) | 41 | 0.57 | 0.59 | **0.58** |

Tres cosas que la exactitud sola no decía:

1. **`arco` se pierde por el umbral, no por confusión.** Tiene precisión 0.89
   —cuando lo lee, acierta— pero exhaustividad 0.56: **12 de 43 tomas se
   rechazan** por pasarse del umbral. Es el gesto más variable entre personas y
   el umbral global lo castiga.
2. **`aplaudir` es el sumidero.** Precisión 0.65: se lleva 9 `ven_aca`, 5 `arco`
   y 5 movimientos ajenos. Cualquier trayectoria de las dos manos hacia el pecho
   se le parece. Ya estaba documentado en `probar_vocabulario.py`; ahora tiene
   número por clase.
3. **El rechazo es la mitad de bueno que el reconocimiento.** F1 0.58 contra
   0.76-0.91 del vocabulario: 17 de 41 movimientos ajenos se leen como un
   comando de vuelo. Es la limitación real del sistema y no la esconde ninguna
   media.

## Umbral por gesto (implementado y activado)

`construir_plantillas.py --umbral-por-clase` mide un umbral para cada gesto en
vez de uno solo. La población de cada gesto son las distancias con las que **se
lee ese gesto**: acertando son los positivos, equivocándose son los negativos.
Es justo lo que el umbral tiene que separar cuando el reconocedor propone ese
gesto. Los dos números se reportan siempre, así que la elección se hace con
datos.

Umbrales medidos sobre el vocabulario de cinco gestos, con el global en 0.708:

| gesto | umbral propio |
|---|---|
| aplaudir | **0.373** |
| ven_aca | 0.475 |
| circulo | 0.511 |
| senalero | 0.701 |
| arco | 0.716 |

**Mi predicción de ayer era la equivocada.** Dije que `arco` era el que sufría
el umbral global: su umbral propio resulta ser 0.716, prácticamente el global.
`arco` no pierde tomas por el umbral, las pierde porque de verdad cae lejos de
toda plantilla, y eso sólo lo arregla más material. El que sí estaba mal medido
es **`aplaudir`, que necesita la mitad del umbral global** — y es exactamente el
gesto sumidero que se tragaba a los demás.

Qué cambia, medido:

| vocabulario de 5 gestos | acierto | macro-F1 | comandos inventados | gestos perdidos |
|---|---|---|---|---|
| umbral único (0.708) | 77.6 % | 0.77 | 17/41 | 18/222 |
| umbral por gesto | 77.6 % | **0.78** | **10/41** | 37/222 |

| banco de 3 gestos | acierto | macro-F1 | comandos inventados | gestos perdidos |
|---|---|---|---|---|
| umbral único (0.839) | 81.4 % | 0.82 | 14/30 | 4/72 |
| umbral por gesto | **82.4 %** | **0.83** | **6/30** | 11/72 |

En el banco de tres gestos gana en todo. En el de cinco **la exactitud es
idéntica y lo que cambia es el reparto de errores**: se inventan 7 comandos
menos y se pierden 19 gestos buenos más. Por clase, `aplaudir` sube de precisión
0.65 a 0.80 y `ven_aca` de 0.87 a 1.00; lo que baja es la exhaustividad de
`aplaudir`, de 0.91 a 0.78.

**Activado por defecto** (decisión del autor, 2026-09-08). El argumento que
gana es de seguridad: un gesto perdido se repite, un despegue inventado no se
deshace. Los dos bancos de `models/` están reconstruidos con umbrales por
gesto, `probar_vocabulario.py` los imprime al arrancar, y `--umbral-unico`
—en `construir_plantillas.py`— o `--umbral X` —en vivo— vuelven al número único
para comparar. Las dos cifras se siguen reportando en cada corrida.

Lo que hay que vigilar en la próxima sesión de vuelo: **`aplaudir` es el gesto
que conmuta entre modo dinámico y estático**, y pasa de leerse 9 de cada 10
veces a 3 de cada 4. Si en vivo cuesta cambiar de modo, la salida no es volver
al umbral único —perdería el rechazo— sino subir sólo el de `aplaudir`, que
ahora es un número editable e independiente.

| banco | umbral por gesto guardado |
|---|---|
| `plantillas_vocabulario.npz` | aplaudir 0.373, ven_aca 0.475, circulo 0.511, senalero 0.701, arco 0.716 (global 0.708) |
| `plantillas_dinamicas.npz` | aplaudir 0.295, ven_aca 0.756; arco se queda con el global 0.839 |

## Lo que se probó y no funcionó

**Añadir más material de rechazo genérico empeora el sistema.** Hay `saludar`
(45 tomas) y `reposo` (10) grabados y sin usar; parecía la mejora obvia. Medido:

| | anidado | macro-F1 | F1 de `ven_aca` | ajenos colados |
|---|---|---|---|---|
| rechazo = `otro` (41 tomas) | **77.6 %** | 0.77 | 0.82 | 17/41 |
| rechazo = `otro,saludar,reposo` (96) | 69.5 % | 0.71 | **0.57** | 42/96 |

La causa se ve en la matriz: `saludar` es un brazo que se levanta y oscila, es
decir, casi un `ven_aca`. Meterlo en la clase de rechazo enseña al detector a
rechazar `ven_aca`. **El material de rechazo tiene que ser el que el sistema
confunde de verdad, no cualquier movimiento ajeno.** La vía correcta ya existe:
`probar_vocabulario.py --guardar-segmentos` graba los falsos positivos reales y
`construir_plantillas.py --rechazo-extra` los suma.

## 3D contra 2D

Sobre las 102 tomas reetiquetadas, cinco clases sin rechazo:

| | exactitud 1-NN | separación | LOSO por sujeto | macro-F1 |
|---|---|---|---|---|
| 3D canonicalizado | 73.5 % | 1.34x | 82 % | 0.68 |
| 2D del plano de imagen | 65.7 % | 1.15x | 73 % | 0.60 |

El 3D separa mejor incluso de frente. Dos comprobaciones sanas: la plantilla de
un desconocido cuesta sólo 1.05x más que la propia (2D: 1.11x), y el sistema
identifica a la persona por su gesto sólo el 19 % de las veces contra un 12 % de
azar —es decir, **casi no está aprendiendo el estilo de cada quien**, que era el
riesgo—.

La tabla de transferencia entre orientaciones que imprime el script **no se
puede usar**: toma como base las tomas de −90°, y sólo hay 3. Habría que fijar la
base en 0° (38 tomas).

## Qué cambió en el código

| Archivo | Qué |
|---|---|
| `external/gesture_detection/recognition/evaluacion.py` | **Nuevo.** `loso`, `loso_anidado`, `metricas_por_clase`, `matriz_confusion`, `guardar_csv`. Es la fuente única: la matriz de confusión estaba duplicada en dos scripts |
| `external/gesture_detection/construir_plantillas.py` | Usa el módulo; imprime las dos validaciones, las métricas por clase y guarda CSV. `--reporte` elige la carpeta |
| `external/gesture_detection/comparar_2d_3d.py` | Usa el módulo; imprime métricas por clase; la matriz de distancias se calcula **una vez** en lugar de tres |
| `external/gesture_detection/tests/test_evaluacion.py` | **Nuevo.** 11 pruebas, entre ellas que la cifra anidada nunca supere a la optimista |
| `external/gesture_detection/recognition/dinamicos.py` | `BancoDinamico.umbrales`: umbral propio por gesto, con respaldo al global. Se guarda en el `.npz` y **los bancos viejos siguen cargando** |
| `external/gesture_detection/probar_vocabulario.py` | Imprime los umbrales por gesto; `--umbral X` ahora los sustituye de verdad |
| `external/gesture_detection/README.md` | Documenta qué número se puede publicar y el umbral por gesto |

Validación: `python -m pytest -q` → **392 pruebas en verde**.

Los CSV quedan en `results/data/validacion_dtw/2026-09-08/`: la carpeta raíz es
el banco de tres gestos, `vocabulario_5/` el de cinco y
`vocabulario_5_mas_negativos/` el experimento que falló. Las carpetas raíz y
`vocabulario_5/` llevan ya el umbral por gesto; `umbral_unico/` y
`vocabulario_5_umbral_unico/` guardan la variante anterior como referencia.

Reproducir:

```powershell
python .\external\gesture_detection\construir_plantillas.py --carpeta results\data\gestos --gestos senalero,aplaudir,ven_aca,arco,circulo --negativos otro --salida models\plantillas_vocabulario.npz
python .\external\gesture_detection\comparar_2d_3d.py --carpeta results\data\gestos_reetiquetado
```

## Sugerencias, por lo que mueve la cifra

1. **Grabar dos o tres sujetos más.** Es lo único que va a mover el 77.6 % de
   verdad. El banco del vocabulario descansa en **5 personas** (Adrian, Brayan,
   Campos, Jeremías, Samuel); el propio README pide mínimo cuatro y
   recomienda seis. Se nota en el umbral: **varía entre 0.546 y 0.732 según qué
   persona se deje fuera**, un 33 % de dispersión. Con más sujetos se estabiliza
   y las tres cifras suben a la vez. La sesión ya está guionizada en
   `grabar_vocabulario.py` (54 tomas, 10-15 min por persona).
2. ~~Umbral por clase~~ **hecho y activado por defecto** (sección de arriba).
   Queda comprobar en vuelo que `aplaudir` sigue siendo usable para conmutar de
   modo; si no, se sube su umbral solo.
3. **Alimentar el rechazo con los errores propios, no con gestos ajenos.**
   Una sesión con `--guardar-segmentos`, borrar los segmentos correctos y pasar
   el resto por `--rechazo-extra`. El experimento de arriba dice que la
   alternativa —más material ajeno genérico— hace daño.
4. **Reservar uno o dos sujetos como test intocado.** Hoy la validación anidada
   ya es honesta para el umbral, pero cualquier decisión futura de diseño
   (rasgos, número de muestras, banda de Sakoe-Chiba) se seguirá tomando sobre
   todo el material. Con 7-8 sujetos se puede permitir apartar uno.
5. **Medir la tasa de falsos disparos en reposo.** Hay 10 tomas de `reposo` y no
   entran en ninguna métrica. La pregunta que falta responder no es "¿confunde
   dos gestos?" sino "¿cuántos comandos inventa por minuto alguien de pie
   hablando?". Eso lo filtra el segmentador por movimiento, y el segmentador no
   está medido sobre material real.
6. **Arreglar la base de la tabla de transferencia** (`comparar_2d_3d.py:271`):
   fijarla en 0° en vez de en la orientación mínima.
7. **Higiene de nombres de sujeto.** `Alan`/`Alan2`, `Keu`/`keu2`, `kUrt`. Se
   midió por si rompía el LOSO: **no cambia ninguna cifra** (0.0 puntos), porque
   los duplicados sólo aparecen en clases de rechazo. Es orden, no un problema.

## Para el documento

El capítulo de validación ya tiene con qué escribirse: partición por sujeto
(LOSO) con la justificación de por qué no aplica el split 70/20/10 —DTW no
entrena parámetros—, validación anidada como defensa contra la fuga de datos,
matriz de confusión y métricas por clase, y el par sesgo/varianza con lectura
concreta: sesgo alto = banda de Sakoe-Chiba estrecha o umbral bajo (`arco`
perdiendo 12 tomas es exactamente eso), varianza alta = umbral permisivo (17 de
41 ajenos colándose es exactamente eso). Ibañez et al. reportan 99.1 % con
validación cruzada **aleatoria por muestra**; la comparación honesta con este
77.6 % exige decir esa diferencia.

## Enlaces

- [Pipeline de gestos por visión](../../docs/agents/gesture_pipeline.md)
- [Detección de gestos: README](../../external/gesture_detection/README.md)
- [Teoría: redes profundas y métricas](../00-Inbox/Redes_Neuronales_Profundas_Detalles_de_Entrenamiento.md)
