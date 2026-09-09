---
fecha: 2026-09-07
estado: vigente
afecta: tesis, mapeo3d
---
## Decisión
El código de percepción 3D con cámaras IP deja de ser un repositorio aparte y vive en `external/mapeo3d/` dentro de `tesis`. Un solo repositorio de trabajo, un solo vault.

## Contexto
Había dos repositorios que se comunicaban sólo por un contrato de datos. Con tres agentes y un vault, mantener dos raíces duplicaba instrucciones, entornos y grafos. El repositorio `mapeo_tridimensional_con_camaras` queda intacto como histórico y no se borra.

## Consecuencias
- `external/mapeo3d/` conserva su estructura interna (`src/`, `apps/`, `docs/`, `tests/`) y sus comandos se ejecutan desde esa carpeta.
- Sigue sin importar `cflib` ni controladores; la regla de aislamiento se mantiene dentro del mismo repositorio.
- Queda pendiente unificar entornos (T-001) y definir el contrato de datos entre ambos (T-002).
- El grafo `graphify` cubre ahora todo el repositorio; `.graphifyignore` excluye resultados, modelos y el estado de Obsidian.
