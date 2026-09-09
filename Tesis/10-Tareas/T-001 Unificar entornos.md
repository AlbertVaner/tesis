---
estado: revisar
agente: codex
repo: tesis
prioridad: alta
creada: 2026-09-07
---
## Objetivo
Un solo entorno virtual `.venv` en la raíz de `tesis` con el que corran tanto los controladores como `external/mapeo3d`.

## Criterio de aceptación
- [x] `requirements.txt` de la raíz incluye las dependencias de `external/mapeo3d/requirements.txt` sin duplicados ni conflictos de versión
- [x] Desde `external/mapeo3d/`, con el `.venv` de `tesis`: `python -m pytest tests -q` pasa (hoy pasan 217 pruebas con el `.venv` antiguo)
- [x] Las validaciones de `AGENTS.md` siguen pasando
- [x] `external/mapeo3d/README.md` explica que se usa el `.venv` de la raíz

## Contexto
- `AGENTS.md` (raíz) y `external/mapeo3d/AGENTS.md`
- `requirements.txt` (raíz) y `external/mapeo3d/requirements.txt`
- Hoy los tests de `mapeo3d` sólo pasan con el `.venv` del repositorio antiguo `mapeo_tridimensional_con_camaras`
- No instalar dependencias sin avisar: proponer el `pip install` y esperar confirmación

## Bitácora
- 2026-09-07 (humano): creada al fusionar `mapeo3d` dentro de `tesis`.
- 2026-09-08 (claude): el `.venv` de tesis ya tenía todas las dependencias de mapeo3d; 217 tests pasan con él. `requirements.txt` raíz pasa a `opencv-contrib-python` y añade `pytest`; el de mapeo3d remite al raíz. README y AGENTS de mapeo3d actualizados. Falta que el humano haga `pip install -r requirements.txt` si quiere alinear versiones; nada se instaló salvo pytest.
