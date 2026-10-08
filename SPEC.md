# SPEC — Agenda Psi

## 1. Objetivo

Permitir que pacientes reserven sesiones con un psicólogo a partir de horas
que el profesional publica, con una interfaz web simple y amigable.

## 2. Usuarios y roles

| Rol | Puede |
|---|---|
| **Paciente** | Registrarse, iniciar sesión, ver horas libres, reservar, cancelar su reserva, ver su historial |
| **Profesional** (admin) | Iniciar sesión, agregar/eliminar horas disponibles, ver sus sesiones, ver datos básicos del paciente que reservó |

Hay un único profesional en la versión 1 (se crea con un comando `create-professional`).
Los pacientes se registran solos.

## 3. Historias de usuario

**Autenticación**
- US-1: Como paciente me registro con nombre, correo y contraseña.
- US-2: Como usuario inicio y cierro sesión.
- US-3: Cada rol ve solo sus propias pantallas (un paciente no accede al panel profesional).

**Profesional**
- US-4: Agrego una hora disponible indicando fecha, hora de inicio y duración (por defecto 50 min).
- US-5: Elimino una hora disponible que aún no esté reservada.
- US-6: Veo mi dashboard: próximas sesiones, horas libres y sesiones pasadas.

**Paciente**
- US-7: Veo la lista de horas libres futuras, ordenadas por fecha.
- US-8: Reservo una hora libre (que empiece en más de 24 horas) y recibo confirmación.
- US-9: Cancelo mi reserva con al menos 24 horas de anticipación; la hora vuelve a quedar libre.
- US-10: Veo mi dashboard: próxima sesión, historial.

**Notificaciones**
- US-11: Al reservar, el paciente y el profesional reciben una notificación de confirmación.
- US-12: 24 horas antes de la sesión el paciente recibe un recordatorio.
- US-13: Al cancelar, ambas partes son notificadas.

## 4. Reglas de negocio

1. Una hora solo puede estar reservada por **un** paciente (sin doble reserva, ni siquiera con dos clics simultáneos).
2. No se pueden crear horas en el pasado.
3. Las horas del profesional no pueden solaparse entre sí.
4. No se puede eliminar una hora ya reservada (primero debe cancelarse).
5. Un paciente no puede tener dos reservas a la misma hora.
6. Las contraseñas se guardan con hash, nunca en texto plano.
7. Solo se puede reservar una hora si faltan **más de 24 horas** para su inicio (medido en instantes absolutos, no en hora de pared); a las 24 h exactas ya no se puede reservar. Cancelar (US-9) sí se permite con 24 h exactas, de modo que toda reserva aceptada puede cancelarse en el momento de hacerla. La lista de horas libres solo ofrece las que cumplen esta regla (D-029).
8. La regla 5 se entiende como **solape de intervalos**: un paciente no puede tener dos reservas cuyos intervalos [inicio, inicio + duración) se crucen, aunque no empiecen a la misma hora; dos horas contiguas (una termina cuando empieza la otra) no se cruzan (D-029).

## 5. Notificaciones (alcance v1)

- Se guardan en la tabla `notificaciones` y se muestran en el dashboard (campana con contador).
- Además se escriben en un archivo de log simulando el envío de correo (`outbox.log`).
- El recordatorio se genera con un comando `flask --app app send-reminders` pensado para ejecutarse periódicamente.
- Fuera de alcance v1: correo o SMS reales.

## 6. Pantallas

1. Inicio / login
2. Registro
3. Dashboard paciente (próxima sesión, botón "Reservar hora", historial, notificaciones)
4. Lista de horas libres + confirmar reserva
5. Dashboard profesional (agenda, horas libres, notificaciones)
6. Formulario para agregar horas

Diseño: limpio, tonos calmados, texto legible, funciona bien en celular.

## 7. Requisitos no funcionales

- Instalación en menos de 5 minutos, sin servicios externos.
- Todo el estado en un único archivo SQLite.
- Cobertura de pruebas en las reglas de negocio de la sección 4.
- Formularios protegidos contra CSRF; consultas SQL parametrizadas.

## 8. Fuera de alcance (v1)

Pagos, videollamadas, múltiples profesionales, fichas clínicas, recuperación de contraseña, correo real.

## 9. Definición de "terminado" (v1)

- [ ] Todas las historias US-1 a US-13 funcionan.
- [ ] Las reglas de negocio 1–6 tienen al menos una prueba cada una.
- [ ] `pytest` pasa completo.
- [ ] Un recorrido manual funciona de punta a punta: registro → reserva → confirmación → recordatorio → cancelación.
- [ ] README permite instalar y ejecutar desde cero.
