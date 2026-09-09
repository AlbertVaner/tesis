# Operación, resultados y seguridad

## Resultados

Las nuevas sesiones deben usar:

```text
results/
  data/<controlador>/<YYYY-MM-DD>/...  # CSV y logs, ignorados
  graphs/<controlador_o_sesion>/...    # PDF/PNG de análisis
  artifacts/...                        # entregables generados
```

Los controladores crean `results/data/<controlador>/<YYYY-MM-DD>/`; los analizadores replican controlador y día bajo `results/graphs/`. Las gráficas históricas existentes se mantienen versionadas.

El controlador por cámara de un dron (`control_camara_dron1.py`) escribe un CSV por frame en `results/data/control_camara_dron1/<YYYY-MM-DD>/<sesion>.csv` y, al cerrar, la gráfica de tiempo contra comandos en `results/graphs/control_camara_dron1/<YYYY-MM-DD>/<sesion>_comandos.{png,pdf}`; ver `grafica_comandos.py`. El backend high-level guarda su propio CSV y sus PDF en `results/{data,graphs}/dos_drones/`.

## Comprobaciones seguras

- `python -m compileall ...` valida sintaxis sin ejecutar los controladores.
- `python -m pytest -q` desde la raíz ejecuta todas las pruebas del repositorio (ver `pytest.ini` y `conftest.py`).
- `--dry-run` valida únicamente los entrypoints que implementan esa opción: sustituye el backend high-level por `SimulatedBackend`, sin radio ni mocap. El backend Flow Deck no tiene simulación.
- `--help` de cada lanzador comprueba imports y argumentos sin abrir cámara, radio ni ventanas.
- Los scripts de `tests/` de cada carpeta corren sin hardware; `tests/integration/` cubre la selección de realimentación del deck y el panel web.
- No asumir que una importación es inocua si un módulo contiene inicialización en nivel superior; inspeccionarlo antes.

## Vuelo real

Un vuelo exige confirmación humana de radio/URI, baterías, zona despejada, posicionamiento, límites y parada de emergencia. No automatizar una prueba física como validación ordinaria de software.

## Datos locales

Entornos virtuales, caches `cflib`, CSV, logs y temporales permanecen fuera de Git. No eliminar resultados locales existentes durante limpiezas del repositorio.
