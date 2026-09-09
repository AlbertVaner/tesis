# Tesis: control de drones por gestos

Este vault es el tablero de trabajo de la tesis. Aquí viven las tareas, la bitácora, las decisiones y la redacción. El código vive fuera del vault, en el resto del repositorio `tesis`.

## Mapa

| Carpeta | Para qué |
|---|---|
| `00-Inbox` | Ideas sueltas. Se vacía cada semana: cada nota se convierte en tarea, decisión o se borra |
| `10-Tareas` | Una nota por tarea. El frontmatter alimenta el [Tablero](Tablero.md) |
| `20-Bitacora` | Una nota por día. Los agentes anotan aquí lo que hicieron |
| `30-Decisiones` | Decisiones de diseño que no se vuelven a discutir |
| `40-Redaccion` | Borradores de capítulos y notas de escritura |
| `50-Referencias` | Papers y notas de lectura |
| `60-Analisis` | Informes de análisis hechos por agentes (código, vuelo, datos). Son propuestas, no decisiones |
| `_plantillas` | Plantillas: `Ctrl+P` y "Templates: Insert template" |
| `_adjuntos` | Imágenes y archivos pegados en notas |

## Flujo de trabajo con agentes

1. Crear una tarea en `10-Tareas` con la plantilla `Tarea`. Nombrarla `T-### Título corto`.
2. Rellenar objetivo, criterio de aceptación y el agente asignado.
3. Abrir el agente en la raíz del repositorio `tesis` y pedirle:

```
Lee Tesis/10-Tareas/T-001 Unificar entornos.md y ejecútala. Al terminar, cambia el estado, escribe en su Bitácora lo que hiciste y añade una línea en Tesis/20-Bitacora/<fecha>.md.
```

4. Revisar en el [Tablero](Tablero.md). Si está bien, pasar `estado` a `hecha`.

Regla de oro: **un agente por repositorio a la vez**. Dos agentes editando los mismos archivos producen conflictos.

Quién hace qué: ver [Agentes](Agentes.md).

## Puesta en marcha (una sola vez)

1. Ajustes > Plugins de la comunidad > desactivar "Modo restringido".
2. Explorar > buscar **Dataview** > instalar y activar. Sin él, el Tablero muestra el código de las consultas en vez de las tablas.
3. Opcional: **Kanban** si prefieres arrastrar tarjetas.
4. Abrir [Tablero](Tablero.md) y comprobar que aparece la tarea T-001.

Ya viene configurado: enlaces en formato Markdown estándar, adjuntos en `_adjuntos`, plantillas en `_plantillas`, nota diaria en `20-Bitacora`.

## Estado del proyecto

- **Empieza aquí si no conoces el proyecto:** [Contexto del proyecto](Contexto%20del%20proyecto.md)
- [Estado y plan](40-Redaccion/Estado%20del%20proyecto.md)
- Decisiones: ver `30-Decisiones`
- Grafo del código: `graphify-out/graph.html` en la raíz del repositorio
