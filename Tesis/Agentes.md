# Agentes: quién hace qué

Repartir por **tipo de tarea**, no por archivo. Nunca dos agentes sobre el mismo repositorio al mismo tiempo.

| Agente | Le va bien | Evitar |
|---|---|---|
| **Claude Code** | Diseño y arquitectura, refactors que cruzan módulos, depuración difícil, revisar lo que hicieron los otros, mantener el grafo (`graphify`) | Tareas mecánicas largas que un agente más barato puede hacer |
| **Codex** | Tareas acotadas y bien especificadas: una función con sus tests, un script de `apps/`, adaptar rutas, limpiar código | Decisiones de diseño sin contexto previo |
| **Gemini** | Leer papers largos, resumir bibliografía, borradores de capítulos en `40-Redaccion`, comparar tu texto con la literatura | Tocar código de vuelo o hardware |

## Cómo abrirlos

Siempre desde la raíz del repositorio `tesis`, para que lean `AGENTS.md`:

```powershell
cd C:\Users\avand\Documents\GitHub\tesis
claude          # lee CLAUDE.md, que importa AGENTS.md
codex           # lee AGENTS.md
gemini          # lee GEMINI.md, que remite a AGENTS.md
```

Los tres pueden escribir en `Tesis/` porque está dentro del repositorio: no hace falta dar permisos extra.

## Protocolo que siguen los tres

Está escrito en la sección "Protocolo del vault" de `AGENTS.md`. En resumen:

1. Leer la tarea completa antes de tocar código.
2. Cumplir el criterio de aceptación, no interpretarlo.
3. Al terminar: `estado: revisar`, línea en la bitácora de la tarea y línea en la nota del día.
4. Nunca marcar `hecha`: eso lo decide el humano tras revisar.
5. Si la tarea es ambigua, escribir la duda en la tarea y parar.
