# Tablero de tareas

Se arma solo desde el frontmatter de `10-Tareas`. Necesita el plugin **Dataview** (ver [Inicio](Inicio.md)).

## En progreso

```dataview
TABLE WITHOUT ID file.link AS Tarea, agente, repo, prioridad, creada
FROM "10-Tareas"
WHERE estado = "en_progreso"
SORT prioridad ASC, creada ASC
```

## Por revisar

```dataview
TABLE WITHOUT ID file.link AS Tarea, agente, repo, creada
FROM "10-Tareas"
WHERE estado = "revisar"
SORT creada ASC
```

## Pendientes

```dataview
TABLE WITHOUT ID file.link AS Tarea, agente, repo, prioridad, creada
FROM "10-Tareas"
WHERE estado = "pendiente"
SORT prioridad ASC, creada ASC
```

## Hechas (últimas 20)

```dataview
TABLE WITHOUT ID file.link AS Tarea, agente, repo, creada
FROM "10-Tareas"
WHERE estado = "hecha"
SORT creada DESC
LIMIT 20
```

## Por agente

```dataview
TABLE WITHOUT ID agente AS Agente, length(rows) AS Tareas, rows.file.link AS Lista
FROM "10-Tareas"
WHERE estado != "hecha"
GROUP BY agente
```
