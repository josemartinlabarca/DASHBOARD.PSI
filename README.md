# Agenda Psi — agendamiento de sesiones con psicólogo

Proyecto de práctica para aprender a trabajar con múltiples agentes de IA.
Aplicación web liviana donde un **profesional** publica horas disponibles y los
**pacientes** las reservan.

## Qué hace (resumen)

- Registro e inicio de sesión (roles: `paciente`, `profesional`).
- El profesional agrega y elimina horas disponibles.
- El paciente ve las horas libres y reserva una.
- Dashboard para cada rol (próximas sesiones, historial).
- Notificaciones de confirmación y recordatorio de hora.

El detalle está en `SPEC.md`.

## Stack (liviano a propósito)

- Python 3.11+ con **Flask**
- **SQLite** (un solo archivo, sin servidor)
- Plantillas **Jinja2** + CSS simple (sin frameworks de frontend)
- **pytest** para pruebas

## Cómo ejecutarlo

```bash
python -m venv .venv
source .venv/bin/activate        # en Windows: .venv\Scripts\activate
pip install -r requirements.txt
flask --app app init-db          # crea la base de datos
flask --app app run --debug      # http://127.0.0.1:5000
pytest                           # corre las pruebas
```

> Estos comandos se vuelven reales a medida que los agentes completan las
> tareas de `TASKS.md`. Si algo no existe todavía, mira `PROGRESS.md`.

## Mapa de documentación

| Archivo | Contenido |
|---|---|
| `SPEC.md` | Qué se construye y qué significa "terminado" |
| `ARCHITECTURE.md` | Estructura, módulos y modelo de datos |
| `DECISIONS.md` | Decisiones técnicas y su porqué |
| `CLAUDE.md` | Reglas para los agentes (convenciones, comandos, límites) |
| `TASKS.md` | Lista de tareas con estado y criterio de término |
| `PROGRESS.md` | Bitácora de lo hecho, fallos y siguiente paso |
| `LOOP.md` | Cómo correr el loop de agentes y sus barandas |

## Aviso

Es un proyecto de aprendizaje. No guarda datos clínicos reales ni debe usarse
en producción sin una revisión de seguridad y privacidad.
