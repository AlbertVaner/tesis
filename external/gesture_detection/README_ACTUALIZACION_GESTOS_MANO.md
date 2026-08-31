# Actualización: vocabulario final de gestos de mano

Copia estos archivos en tu carpeta del proyecto y reemplaza los existentes:

```text
config.py
hand_tracker.py
hand_gesture_detector.py
logger_hand_csv.py
main_hands.py
```

Luego corre:

```powershell
python .\external\gesture_detection\main_hands.py
```

## Gestos implementados

| Comando | Gesto |
|---|---|
| DESPEGAR | índice + medio extendidos, mano hacia arriba |
| ATERRIZAR | índice + medio extendidos, mano hacia abajo |
| STOP | puño cerrado |
| DERECHA | pulgar extendido hacia la derecha |
| IZQUIERDA | meñique extendido, mano hacia arriba |
| ARRIBA | índice extendido, mano hacia arriba |
| ABAJO | índice extendido, mano hacia abajo |
| ADELANTE | índice + anular extendidos, mano hacia arriba |
| ATRAS | índice + anular extendidos, mano hacia abajo |

## Seguridad

Por defecto, `DESPEGAR` y `ATERRIZAR` requieren sostener el gesto durante 1 segundo:

```python
ENABLE_CRITICAL_HOLD = True
CRITICAL_HOLD_SECONDS = 1.0
```

Esto está en `config.py`.

## Debug en pantalla

El panel muestra:

```text
T = pulgar
I = índice
M = medio
A = anular
m = meñique
```

Si un dedo aparece como `1`, el sistema lo considera extendido.
Si aparece como `0`, lo considera cerrado.

## Nota

Este sistema sigue en modo simulación. No se conecta al Crazyflie.
