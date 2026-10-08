# LOOP — cómo correr agentes sobre este proyecto

Aprende en este orden. No saltes etapas.

## Etapa 1 — Una tarea, un agente, tú mirando

Prompt para el **Implementador**:

```
Lee CLAUDE.md y sigue sus instrucciones de lectura.
Toma la primera tarea PENDIENTE de TASKS.md cuyas dependencias estén HECHAS.
Márcala EN CURSO, impleméntala con sus pruebas, verifica con pytest,
márcala HECHA, agrega la entrada en PROGRESS.md y haz commit.
Haz solo esa tarea y detente.
```

Después **tú** revisas el diff y la bitácora. Haz esto con T-01 y T-02.

## Etapa 2 — Generador / Crítico

Después de que el Implementador termina una tarea, lanza un agente distinto, con contexto limpio:

Prompt para el **Revisor**:

```
Lee CLAUDE.md, SPEC.md y ARCHITECTURE.md.
Revisa el último commit (git show HEAD) contra el criterio de término
de la tarea y las reglas de negocio de SPEC.md §4.
No modifiques código. Escribe en REVIEW.md una lista de hallazgos
con severidad (alta/media/baja) y el archivo y línea afectados.
Si no hay hallazgos altos, escribe "APROBADO".
```

Si hay hallazgos altos, el Implementador los corrige en una vuelta nueva y se repite. **Máximo 3 rondas** por tarea; si no se resuelve, se detiene y avisa al humano.

## Etapa 3 — Loop automático sobre TASKS.md

El mismo prompt de la Etapa 1, repetido. Cada vuelta empieza sin memoria; el estado vive en `TASKS.md` y `PROGRESS.md`.

Condiciones de **término**:
- Todas las tareas están `HECHA`, o
- Una tarea queda `BLOQUEADA`, o
- Se alcanza el límite de vueltas.

### Barandas obligatorias

| Baranda | Valor sugerido |
|---|---|
| Máximo de vueltas por ejecución | 5 |
| Pruebas deben pasar antes de marcar HECHA | siempre |
| Commit al final de cada tarea | siempre |
| Rama de trabajo | `agentes/loop` (nunca `main`) |
| Acciones destructivas | prohibidas (ver CLAUDE.md) |
| Revisión humana | al final de cada fase de `TASKS.md` |

## Etapa 4 — Paralelo

Solo cuando la Etapa 3 funcione bien. Ejemplo: T-11 y T-12 a la vez.

- Un `git worktree` (o rama) por agente: `git worktree add ../psi-t11 -b agentes/t11`
- Cada agente toca solo los archivos de su tarea.
- Un humano (o el Orquestador) integra las ramas y resuelve conflictos.

## Cómo saber que el loop está sano

- `PROGRESS.md` crece con entradas claras.
- Los commits son pequeños y uno por tarea.
- `pytest` pasa en cada commit.
- No aparecen dependencias ni archivos que nadie pidió.

Señales de alarma: tareas marcadas HECHA sin pruebas, cambios en `SPEC.md`,
el mismo error repetido en varias vueltas, commits enormes.
