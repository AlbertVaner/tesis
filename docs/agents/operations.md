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

## Comprobaciones seguras

- `python -m compileall ...` valida sintaxis sin ejecutar los controladores.
- `--dry-run` valida únicamente los entrypoints que implementan esa opción.
- No asumir que una importación es inocua si un módulo contiene inicialización en nivel superior; inspeccionarlo antes.

## Vuelo real

Un vuelo exige confirmación humana de radio/URI, baterías, zona despejada, posicionamiento, límites y parada de emergencia. No automatizar una prueba física como validación ordinaria de software.

## Datos locales

Entornos virtuales, caches `cflib`, CSV, logs y temporales permanecen fuera de Git. No eliminar resultados locales existentes durante limpiezas del repositorio.
