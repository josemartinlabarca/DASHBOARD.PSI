# TASKS

Estados: `PENDIENTE` · `EN CURSO` · `HECHA` · `BLOQUEADA`

Cada tarea tiene un **criterio de término** verificable. Un agente solo marca
`HECHA` cuando ese criterio se cumple y `pytest` pasa.

---

## Fase 1 — Base

### T-01 — Esqueleto del proyecto
- **Estado:** HECHA
- **Depende de:** —
- **Qué:** Si no existe, `git init` con `.gitignore` (venv, `*.db`, `outbox.log`, `__pycache__`). Crear `app/` con fábrica Flask, `requirements.txt`, `tests/conftest.py` con app de prueba y base temporal.
- **Término:** `pytest` corre (aunque sea con una prueba trivial) y `flask --app app run` levanta una página de inicio.

### T-02 — Base de datos
- **Estado:** PENDIENTE
- **Depende de:** T-01
- **Qué:** `schema.sql` según `ARCHITECTURE.md`, `db.py` y comando `init-db`.
- **Término:** Prueba que crea la base y verifica que existen las 3 tablas con sus restricciones.

## Fase 2 — Usuarios

### T-03 — Registro de pacientes
- **Estado:** PENDIENTE
- **Depende de:** T-02
- **Qué:** Ruta `/registro` con formulario, validación y hash de contraseña. Correo único.
- **Término:** Pruebas: registro válido, correo duplicado rechazado, contraseña guardada con hash.

### T-04 — Login, logout y control de rol
- **Estado:** PENDIENTE
- **Depende de:** T-03
- **Qué:** `/login`, `/logout`, decoradores `solo_paciente` y `solo_profesional`, comando `create-professional`.
- **Término:** Pruebas: login correcto/incorrecto, paciente no accede a `/profesional` (US-3).

## Fase 3 — Horas

### T-05 — Profesional agrega y elimina horas
- **Estado:** PENDIENTE
- **Depende de:** T-04
- **Qué:** Formulario y rutas de US-4 y US-5 con reglas 2, 3 y 4.
- **Término:** Pruebas: crear hora válida, rechazar pasado, rechazar solape, no eliminar reservada.

### T-06 — Paciente ve horas libres
- **Estado:** PENDIENTE
- **Depende de:** T-05
- **Qué:** `/paciente/horas` con horas libres futuras ordenadas (US-7).
- **Término:** Prueba: solo aparecen horas libres y futuras.

### T-07 — Reservar hora
- **Estado:** PENDIENTE
- **Depende de:** T-06
- **Qué:** `POST /horas/<id>/reservar` con UPDATE atómico (D-003) y reglas 1 y 5.
- **Término:** Pruebas: reserva exitosa; segunda reserva de la misma hora falla; paciente no puede tener dos a la misma hora.

### T-08 — Cancelar reserva
- **Estado:** PENDIENTE
- **Depende de:** T-07
- **Qué:** `POST /horas/<id>/cancelar` con anticipación mínima de 24 h (US-9); la hora vuelve a `libre`.
- **Término:** Pruebas: cancelar con >24 h funciona, con <24 h se rechaza, la hora queda libre.

## Fase 4 — Notificaciones

### T-09 — Notificaciones de confirmación y cancelación
- **Estado:** PENDIENTE
- **Depende de:** T-08
- **Qué:** `notificaciones.py`; crear registros y escribir `outbox.log` al reservar y cancelar (US-11, US-13).
- **Término:** Pruebas: se crean notificaciones para ambas partes y aparece la línea en el log.

### T-10 — Recordatorios 24 h antes
- **Estado:** PENDIENTE
- **Depende de:** T-09
- **Qué:** Comando `send-reminders` (US-12); no repite recordatorios (`recordatorio_enviado`).
- **Término:** Pruebas con hora a <24 h: envía una sola vez aunque se ejecute dos veces.

## Fase 5 — Interfaz

### T-11 — Dashboard del paciente
- **Estado:** PENDIENTE
- **Depende de:** T-09
- **Qué:** `/paciente` con próxima sesión, historial y campana de notificaciones (US-10).
- **Término:** Prueba de contenido por rol; revisión visual en navegador.

### T-12 — Dashboard del profesional
- **Estado:** PENDIENTE
- **Depende de:** T-09
- **Qué:** `/profesional` con agenda, horas libres y notificaciones (US-6).
- **Término:** Prueba de contenido por rol; revisión visual en navegador.

### T-13 — Estilo y plantilla base amigable
- **Estado:** PENDIENTE
- **Depende de:** T-11, T-12
- **Qué:** `style.css` con tonos calmados, diseño responsivo, mensajes de error claros.
- **Término:** Revisión en pantalla de escritorio y de celular; sin texto ilegible.

## Fase 6 — Cierre

### T-14 — Recorrido de punta a punta y revisión final
- **Estado:** PENDIENTE
- **Depende de:** T-13
- **Qué:** Verificador ejecuta el recorrido completo de `SPEC.md` §9; Revisor contrasta código contra SPEC.
- **Término:** Todas las casillas de "Definición de terminado" marcadas; hallazgos en `REVIEW.md` resueltos.

---

## Tareas que pueden correr en paralelo (en ramas separadas)

- T-11 y T-12 (después de T-09).
- Dentro de la Fase 3 no: son secuenciales porque comparten `horas`.
