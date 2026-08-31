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

## 2. Preflight real sin motores

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
- separación inicial mínima de 0.70 m;
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
mayor de 0.15 m o separación física menor de 0.50 m. La tecla
`Q` y el botón rojo también activan la emergencia.

La interfaz continúa mostrando el voltaje y porcentaje reportados, pero estos
valores son únicamente informativos.
