# Control high-level por botones — Python

Esta prueba compara el lazo externo low-level usado anteriormente contra el
controlador high-level del firmware Crazyflie. Sigue el principio del trabajo
de Cruz (`takeoff`, `go_to`, `land`), pero toda esta adaptación funciona en
Python: interfaz, Robotat, telemetría, seguridad y cflib.

## 1. Probar la ventana sin hardware

```powershell
python .\controllers\two_drones\control_dos_drones_cruz_botones.py --dry-run
```

La variante recomendada con interfaz y hardware en procesos separados usa:

```powershell
python .\controllers\two_drones\control_dos_drones_cruz_multiprocessing.py --dry-run
```

En este modo no se importa cflib, no se abre ninguna Crazyradio y ningún botón
puede activar motores. Ejecuta `PREFLIGHT`, despega, mueve y aterriza los drones
simulados para comprobar la interfaz.

La entrada `python .\control_dos_drones_camara.py --dry-run` utiliza el mismo
backend simulado, pero abre la cámara para reconocer gestos. Un mensaje
`TAKEOFF` en ese modo solo cambia el estado simulado; no prueba la conexión
con los drones. En cámara, `q` aterriza y sale; Ctrl+C solicita emergencia y
cierra (código de salida 130). Si ambos procesos reciben Ctrl+C, el cliente
tolera que el backend ya haya cerrado y avisa cuando no recibe confirmación.

En todos los controles por cámara, enseñar únicamente el dedo medio activa el
seguimiento tridimensional del marker Robotat 65 para el dron asignado a esa mano. El
símbolo de rock (índice y meñique, con pulgar opcional) lo detiene y conserva el
último objetivo como hover. Con una mano asignada a `both`, ambos drones siguen
el mismo desplazamiento y conservan su formación inicial. Cada dron mantiene
0.45 m respecto al marker en X, Y y Z, con velocidad máxima de 0.10 m/s, pasos
high-level de hasta 2.5 cm y transiciones de 0.75 s. No se limita el recorrido
respecto al origen. Una esfera de exclusión evita que los drones se acerquen a
menos de 0.30 m. El seguimiento se cancela si una pose caduca. El puño mantiene
prioridad de emergencia aunque el seguimiento esté activo.

Regresión del cierre, sin abrir cámara, interfaz ni radios:

```powershell
python -m unittest discover -s controllers/two_drones/tests -v
```

### Diagnosticar un fallo de alineación EKF–MoCap

Si el preflight agota la espera de alineación, muestra en consola y en el
error las posiciones MoCap/EKF, su antigüedad, URI, tópico, parámetros en
cache y contadores de llamadas a `send_extpos`. Estos contadores son
acumulados por instancia: una llamada sin excepción no confirma recepción
en el firmware. Los errores de envío quedan disponibles aunque luego se
recupere la comunicación. El diagnóstico no solicita lecturas adicionales
ni cambia parámetros, tiempos de espera o el umbral de 0.07 m.

Una estimación `(0, 0, 0)` con muestras recientes y MoCap distinto de cero
requiere revisar el estimador, la inicialización del dron y la recepción de
posición externa. La antigüedad permite distinguir ese caso de una
telemetría que dejó de actualizarse. Para confirmar el origen, conservar
el diagnóstico completo y la salida de la consola del firmware; no basta
el mensaje genérico de alineación.

## 2. Preflight real sin motores

Para Robotat con el Flow Deck conectado, el preflight ahora exige confirmar
`motion.disable=1` y `range.disable=1` antes del reset del EKF. Esto excluye
flujo óptico y ToF; el segundo parámetro requiere el
[parche de firmware del proyecto](../../external/crazyflie_firmware/README.md).
Si el firmware no lo ofrece, el preflight se bloquea con un error específico.
Sin deck detectado se conserva la operación con MoCap. Esta selección también
aplica a la cámara high-level, botones low-level y la interfaz individual que
reutiliza `DroneUnit`. Los modos dedicados a Flow Deck reactivan ambas mediciones.

```powershell
python .\controllers\two_drones\control_dos_drones_cruz_botones.py
```

Para la prueba real multiproceso:

```powershell
python .\controllers\two_drones\control_dos_drones_cruz_multiprocessing.py
```

## Modo de un solo dron

Para probar únicamente el Dron 1 con el mismo control de Cruz:

```powershell
python .\controllers\two_drones\control_dos_drones_cruz_multiprocessing.py --single drone1
```

Para probar únicamente el Dron 2:

```powershell
python .\controllers\two_drones\control_dos_drones_cruz_multiprocessing.py --single drone2
```

Puede combinarse con `--dry-run`. En modo de un dron solo se abre su
Crazyradio y su tópico Robotat; el otro dron aparece deshabilitado y no se
aplica la verificación de separación.

Pulsa únicamente `PREFLIGHT (SIN MOTORES)`. Para habilitar el despegue debe
comprobar:

- marcadores estables en `mocap/drone3` y `mocap/drone4`;
- dos Crazyradio diferentes, resueltas por serial;
- separación inicial mínima de 0.30 m;
- alineación EKF–MoCap;
- telemetría de batería disponible únicamente para registro y visualización;

## 3. Primera comparación de hover

1. Despeja el área y mantén visible el botón rojo.
2. Completa el preflight.
3. Pulsa `DESPEGAR AMBOS`: ascienden 0.35 m en 5 s.
4. No envíes movimientos durante 10–15 s.
5. Pulsa `ATERRIZAR AMBOS`.

La sesión real genera
`results/data/dos_drones/<YYYY-MM-DD>/python_highlevel_cruz_*.csv`.
Al cerrar el programa genera automáticamente figuras PDF dentro de
`results/graphs/dos_drones/<YYYY-MM-DD>/python_highlevel_cruz_*`. Incluye altura, trayectoria XY, error de
control, error EKF-MoCap, calidad MoCap, batería, actitud y separación cuando
participan dos drones. El voltaje solo se registra y grafica: no bloquea el
preflight, el despegue ni activa una emergencia.

El watchdog detiene ambos motores ante pérdida de Robotat, error EKF–MoCap
mayor de 0.15 m o separación física menor de 0.30 m. La tecla
`Q` y el botón rojo también activan la emergencia.

La interfaz continúa mostrando el voltaje y porcentaje reportados, pero estos
valores son únicamente informativos.
