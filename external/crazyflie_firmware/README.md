# Flow Deck conectado durante pruebas Robotat

## Qué está preparado y qué falta

Python selecciona la realimentación antes de reiniciar y alinear el EKF:

- Robotat: `motion.disable=1` y `range.disable=1`, con respuesta del firmware.
- Control con Flow Deck: ambos en `0`; el firmware estándar admite el flujo óptico y ya incorpora ToF sin interruptor.
- Sin Flow Deck/Z-ranger detectado: no se escriben esos parámetros.

`motion.disable` ya existe en Bitcraze y excluye el flujo óptico. **No excluye
la distancia al suelo (ToF)**. El parche adjunto añade `range.disable` al
firmware. Es un parámetro propio de este proyecto; no se debe suponer que
existe en un firmware estándar. La tabla local de parámetros observada en
septiembre de 2026 no lo contiene; esa tabla no identifica la versión exacta
instalada ni sustituye consultar el firmware real.

Si hay Flow Deck/Z-ranger y falta un interruptor o su confirmación, Python
bloquea el preflight. No existe una opción para continuar con exclusión parcial.
No se cambian ganancias, URI, tópicos ni umbrales EKF/MoCap.

## Parche de firmware

Archivo: `patches/0001-range-disable-for-robotat.patch`.
Base verificada: Bitcraze `crazyflie-firmware`, etiqueta `2026.04`,
`src/modules/src/range.c`. SHA-256 del archivo base:
`04cf1b3bb9628482b9db2e376f4795e76bbeda55d1d6913c4df275b95f428ded`.

El parche deja de encolar ToF descendente cuando `range.disable=1`, tanto
para Flow Deck v1 como v2, porque ambos usan
`rangeEnqueueDownRangeInEstimator`. Mantiene `range.zrange` disponible en logs.
El valor inicial es `0` y no se guarda persistentemente: reiniciar el dron
restablece el comportamiento original. No desactiva la IMU ni la posición
externa, y no anula los autotests de arranque del deck.

Se comprobó la aplicación del parche sobre el archivo oficial. **No se ha
compilado un firmware completo, instalado una herramienta de compilación ni
flasheado un dron.** Hace falta conocer modelo y versión instalados antes de
elegir una base para los drones reales. La etiqueta usada para verificar el
parche no constituye una recomendación de actualizar a esa versión.

Cuando se disponga del checkout compatible de firmware, revisar desde su raíz:

```powershell
git apply --check C:/Users/avand/Documents/GitHub/tesis/external/crazyflie_firmware/patches/0001-range-disable-for-robotat.patch
```

Aplicar, compilar y cargar el firmware son pasos pendientes; el comando de
arriba solo comprueba el parche. Para otra versión hay que revisar el código
y repetir la comprobación. No cambiar cachés de cflib para inventar parámetros.

## Alcance de Python y validación

La implementación común está en `controllers/shared/flowdeck_feedback.py`.
La consumen el preflight high-level, `DroneUnit.configure()` (incluye la
interfaz individual y la dual low-level), el joystick Robotat y la preparación
del vuelo con Flow Deck (hover, panel y cámara). Los modos `--dry-run` no
instancian hardware y no escriben estos parámetros.

El controlador de Flow Deck vuelve a habilitar las mediciones antes de su
reset; no hay que retirar físicamente el deck al cambiar de modo. Para usar
software ajeno que no seleccione el modo, reiniciar antes el dron.

Pruebas locales sin cámara, MQTT, radio ni motores:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests/integration -p test_flowdeck_feedback.py -v
```

Una vez instalado el firmware compatible, la comprobación física pendiente
es PREFLIGHT con el deck colocado: confirmar ambos parámetros en `1`, MoCap
reciente y alineación EKF. El primer ensayo no requiere despegar. Si el deck
falla sus autotests al encender, estos interruptores no reparan ese problema;
se debe revisar la consola de arranque.

## Fuentes y ubicación

- [Flujo óptico, parámetro motion.disable](https://github.com/bitcraze/crazyflie-firmware/blob/master/src/deck/drivers/src/flowdeck_v1v2.c).
- [ToF descendente, base del parche](https://github.com/bitcraze/crazyflie-firmware/blob/2026.04/src/modules/src/range.c).
- [Driver Z-ranger v2](https://github.com/bitcraze/crazyflie-firmware/blob/master/src/deck/drivers/src/zranger2.c).
- [Guía oficial de compilación](https://www.bitcraze.io/documentation/repository/crazyflie-firmware/master/building-and-flashing/build/).

El parche vive en `external/crazyflie_firmware/` porque adapta código de
firmware externo, independiente del número de drones y de la interfaz. La
selección desde Python vive en `controllers/shared/` por sus consumidores en
control dual, joystick y Flow Deck individual.
