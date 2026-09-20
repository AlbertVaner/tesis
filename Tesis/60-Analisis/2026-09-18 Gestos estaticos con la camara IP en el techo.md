---
fecha: 2026-09-18
tipo: analisis
---
# Gestos estáticos con la cámara IP en el techo

## Síntoma

En los dos vuelos del 2026-09-18 (`results/data/control_camara_dron1/2026-09-18/`), en modo estático el 92 % y el 98 % de los frames fueron `NO_GESTURE`. Sólo `ARRIBA` llegó a confirmarse. `ABAJO` y `ADELANTE` parpadeaban 1-5 frames con confianza 0.1-0.3, y `DERECHA`, `IZQUIERDA` y `ATRAS` no aparecieron. La calidad de landmarks era 0.98: no era visibilidad. En modo dinámico, sin hacer gestos estáticos, el registro marcaba `ABAJO` en el 7 % y el 14 % de los frames.

## Datos

Dos grabaciones guiadas con `probar_gestos_3d.py --rtsp env --practica`, 620 frames, cámara Amcrest colgada del techo a unos 5 m, sub-stream 640x480 (persona de ~180 px de alto): `results/data/gesture_detection/2026-09-18/vocabulario_3d_170237.csv` y `..._170314.csv`. El CSV no guarda qué gesto se pedía; la intención se etiquetó por tramos leyendo la línea de tiempo, descartando el primer segundo de cada gesto.

Lo que ve el clasificador, por gesto (mediana):

| Gesto | Dirección del brazo | Ángulo al nominal | Extensión |
|---|---|---|---|
| Reposo | (0.06, −0.94, 0.30) | 19-25° de la vertical | 1.0 |
| DERECHA | (−0.90, −0.25, 0.29) | 14-24° | **0.75-0.84** |
| IZQUIERDA | (0.76, −0.21, 0.55) | 25° (p90 37°) | 0.82 |
| ADELANTE | (−0.21, −0.16, 0.96) | 15° (p90 29°) | 0.89 |
| ARRIBA | (−0.12, 0.93, 0.34) | 8-20° | 0.88 |
| ABAJO | (0.17, −0.73, 0.66) | 10° | 1.04 |
| ATRAS | (−0.40, −0.36, −0.85) | 14-19° sagital | 0.74-0.94 |

## Causas

1. **`EXTENSION_MIN = 0.85` rechazaba los laterales.** De lejos y desde arriba un brazo lateral estirado se mide a 0.75-0.84 unidades de torso. DERECHA caía a 14° del objetivo y se rechazaba sólo por esto.
2. **El cono de 22° es estrecho para un brazo real visto así.** El brazo no sale horizontal: cae unos 15° y el modelo lo adelanta.
3. **El reposo rozaba el cono de reposo (22°)** y se leía como ABAJO.

Descartado con una simulación: no es un sesgo de profundidad corregible restando un desplazamiento en Z. Las direcciones nominales ya lo incluyen (ARRIBA es (0, 0.92, 0.40)), y restarlo bajaba ARRIBA del 100 % al 0 %. Tampoco es la resolución: el stream principal a 1280x720 da las mismas medidas.

## Cambio

`recognition/body_3d_rules.py`: `EXTENSION_MIN` 0.85 → 0.70; `CONO_AMPLIO_DEG = 30` para ARRIBA, ADELANTE, IZQUIERDA y DERECHA (ABAJO y ATRAS siguen en 22); `CONO_REPOSO_DEG` 22 → 27.

Por qué es seguro: todos los pares de direcciones salvo ABAJO/ADELANTE están a 66° o más, así que 30+30 no solapa. ABAJO/ADELANTE (45°) lo sigue guardando `MARGEN_DEG`: barriendo el brazo de uno a otro se lee ABAJO, luego nada, luego ADELANTE, nunca un salto (hay prueba). El cono de reposo y el de ABAJO se solapan 4° a propósito y lo resuelve el orden: el reposo se comprueba primero. El ABAJO real se midió a 36-43° de la vertical.

## Resultado sobre las grabaciones (re-simulado, por frame)

| | Antes | Después |
|---|---|---|
| DERECHA | 0 % | 94 % |
| IZQUIERDA | 0 % | 66 % |
| ADELANTE | 47 % | 59 % → con cono 30: mejora en los tramos caídos |
| ARRIBA, ABAJO, ATRAS | 100 / 95 / 100 % | igual |
| Reposo leído como ABAJO | 7 de 67 | 4 de 67 |

Con la confirmación de 0.20 s, sobre las grabaciones enteras: antes se confirmaban ARRIBA, ADELANTE, ABAJO y ATRAS; después además DERECHA e IZQUIERDA en las dos, sin ningún gesto equivocado, y desaparece un ABAJO falso en reposo.

## Pendiente

- **No validado en vivo.** Todo sale de re-simular dos grabaciones de un solo operador.
- IZQUIERDA sigue siendo la más floja: el brazo izquierdo sale más adelantado (z 0.55) que el derecho (0.29). Falta saber si es el operador, su orientación respecto a la cámara o el modelo.
- Los gestos de dos manos (DESPEGAR, STOP) se leen bien en crudo pero parpadean y les cuesta sostener los 0.8 s de confirmación. No se tocaron.
- `probar_gestos_3d.py` debería guardar en el CSV qué gesto está pidiendo la práctica, para no etiquetar a mano.
