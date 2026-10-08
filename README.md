# Agenda Psi — agendamiento de sesiones con psicólogo

Proyecto de práctica para aprender a trabajar con múltiples agentes de IA.
Aplicación web liviana donde un **profesional** publica horas disponibles y los
**pacientes** las reservan.

## Qué hace (resumen)

- Registro e inicio de sesión (roles: `paciente`, `profesional`).
- El profesional agrega y elimina horas disponibles.
- El paciente ve las horas libres, reserva una y la cancela con al menos 24 horas de anticipación (lista «Mis reservas» en su panel).
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

### Cambios de esquema y `agenda.db` existente

`init-db` solo crea las tablas que faltan (`CREATE TABLE IF NOT EXISTS`, D-006):
**no modifica tablas ya existentes**. Si ya tienes un `agenda.db` creado con un
esquema anterior (por ejemplo, antes de T-02c, T-02f o T-02g, que agregaron restricciones: `ON DELETE SET NULL` en `notificaciones.hora_id` y el formato de `horas.inicio`, incluido el rechazo del carácter nulo), seguirá
funcionando pero **sin las restricciones nuevas**. Mientras sea una base de
práctica, bórrala y vuelve a ejecutar `init-db`:

```bash
rm agenda.db                     # en Windows: del agenda.db
flask --app app init-db
```

Esto borra todos sus datos; no lo hagas con datos que quieras conservar.

**Importante tras T-08d (D-022 y D-023):** la tabla `usuarios` ganó la columna
`sesion_version` (cierre de sesión que invalida las cookies copiadas) y el índice
único `un_solo_profesional` (la base impide un segundo profesional). Un
`agenda.db` anterior **no tiene la columna**: la aplicación fallaría al iniciar
sesión con `no such column: sesion_version`. Bórralo y ejecuta `init-db` de nuevo
como se indica arriba. Hoy `init-db` no avisa si detecta un esquema antiguo (eso
queda para T-14).

### Variable `SECRET_KEY`

`SECRET_KEY` es la clave secreta con la que Flask firma las sesiones y los
tokens CSRF. Si alguien la conoce, puede falsificarlos, así que debe ser larga,
aleatoria y no subirse al repositorio. Genera una así y defínela antes de
iniciar la app:

```bash
export SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
flask --app app run
```

En Windows (PowerShell):

```powershell
$env:SECRET_KEY = python -c "import secrets; print(secrets.token_hex(32))"
flask --app app run
```

En desarrollo con `flask --app app run --debug` y en las pruebas **no hace
falta**: se usa un valor de desarrollo inseguro. Los comandos de mantenimiento
(`flask --app app init-db`) tampoco la necesitan. Fuera de debug, si falta
`SECRET_KEY` (o solo tiene espacios), la app **no atiende ninguna petición**:
cada una responde error 500 y el log indica qué falta. Con `flask run` (o un
servidor WSGI) sin clave, el log muestra además un aviso al arrancar; `init-db`
y `create-professional` no lo muestran.

> **Advertencia:** no actives `FLASK_DEBUG` (ni `--debug`) en un entorno
> expuesto. En debug la clave es un valor público fijo (está en el código), así
> que cualquiera podría falsificar sesiones y tokens CSRF; además el modo debug
> expone un depurador interactivo.

### Crear la cuenta del profesional

```bash
flask --app app create-professional --email profesional@ejemplo.cl --nombre "Nombre Apellido"
```

El comando pide la contraseña en pantalla **sin mostrarla** y la repite para
confirmar. No existe una opción `--password`: así la contraseña no queda en la
lista de procesos ni en el historial del intérprete de comandos. Límite: solo
queda oculta cuando la terminal es interactiva. Si alimentas la entrada
estándar con una tubería (`printf 'clave\nclave\n' | flask ...`), la
contraseña queda escrita en esa línea (y en el historial del intérprete) y Click
avisa "Password input may be echoed"; hazlo solo en pruebas. Después inicia
sesión en `/login`.

### Cookie de sesión

La cookie de sesión es `HttpOnly` y `SameSite=Lax`. No lleva `Secure` porque
eso exige HTTPS; se activará con `SESSION_COOKIE_SECURE=True` al desplegar
(tarea T-14).

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
