# CLAUDE.md — reglas para los agentes

Lee este archivo completo antes de hacer cualquier cosa. Luego lee, en este orden:
`SPEC.md` → `ARCHITECTURE.md` → `TASKS.md` → `PROGRESS.md`.

## Proyecto

Agenda Psi: app Flask + SQLite para reservar sesiones con un psicólogo.
Idioma de la interfaz y de los mensajes al usuario: **español de Chile**.
Idioma del código (nombres de funciones y variables): se mantiene el de
`ARCHITECTURE.md` (español para el dominio: `horas`, `paciente`, etc.).

## Comandos

```bash
pip install -r requirements.txt
flask --app app init-db
flask --app app run --debug
pytest
```

Una tarea no está terminada si `pytest` no pasa.

## Convenciones

- Python 3.11+, funciones cortas, nombres claros.
- SQL siempre parametrizado (`?`), nunca concatenado.
- Contraseñas con `werkzeug.security` (hash), nunca en texto plano.
- Formularios con token CSRF.
- Fechas en ISO 8601, zona horaria de Chile.
- Una dependencia nueva requiere una entrada en `DECISIONS.md`.
- Mensajes de commit en español, formato: `T-XX: descripción corta`.

## Reglas de trabajo

1. Trabaja en **una sola tarea** de `TASKS.md` por vuelta.
2. Toma solo tareas con estado `PENDIENTE` cuyas dependencias estén `HECHA`.
3. Cumple el **criterio de término** de la tarea; no añadas funciones extra.
4. Escribe o actualiza pruebas junto con el código.
5. Al terminar: marca la tarea como `HECHA` en `TASKS.md`, agrega una entrada en
   `PROGRESS.md` y haz un commit.
6. Si dos documentos se contradicen o falta información, **no inventes**:
   anota la duda en `PROGRESS.md` bajo "Bloqueos" y detén la vuelta.
7. No edites `SPEC.md` ni `ARCHITECTURE.md` sin que la tarea lo pida; propón el
   cambio en `DECISIONS.md`.

## Qué NO tocar

- `SPEC.md` y `ARCHITECTURE.md` (solo el humano o una tarea explícita).
- Archivos fuera de la carpeta del proyecto.
- No ejecutar comandos destructivos (`rm -rf`, borrar la base de datos de datos
  que no sean de prueba, `git push --force`).

## Roles de agente

Cuando se te asigne un rol, actúa solo dentro de él:

| Rol | Hace | No hace |
|---|---|---|
| **Implementador** | Toma una tarea, escribe código y pruebas | Aprobar su propio trabajo |
| **Revisor** | Lee el diff, busca errores contra `SPEC.md`, escribe hallazgos en `REVIEW.md` | Modificar código |
| **Verificador** | Corre `pytest` y el recorrido manual, reporta resultados | Corregir fallos |
| **Orquestador** | Mantiene `TASKS.md`, decide el orden y reparte tareas | Escribir código de la app |

## Formato de entrada en PROGRESS.md

```
### [fecha hora] T-XX — título — rol
- Qué se hizo:
- Cómo se verificó:
- Problemas / dudas:
- Siguiente paso sugerido:
```
