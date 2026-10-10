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

- Python 3.11+ con **Flask** (se probó con Python 3.13; ver «Versión de Python» más abajo)
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

**Actualizar una base creada antes de T-14a (límite de intentos, D-045):** la
tabla nueva `intentos_acceso` **no exige borrar nada**. Basta volver a ejecutar
`flask --app app init-db`: como solo crea lo que falta, agrega la tabla y su
índice y deja intactos los usuarios, horas y notificaciones. Sin ese paso, el
login y el registro responden 500 (`no such table: intentos_acceso`). Las demás
tablas siguen necesitando el borrado de arriba si son anteriores a T-02c, T-02f,
T-02g o T-08d.

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

> **Advertencia:** `--debug` y `FLASK_DEBUG` son **solo para tu máquina**. En debug
> la clave es un valor público fijo (está en el código), así que cualquiera podría
> falsificar sesiones y tokens CSRF; además el modo debug expone un depurador
> interactivo. Por eso `flask run` **se niega a arrancar** con debug (o con
> `--debugger`) si el host no es local (`127.0.0.1`, `localhost`, `::1`): por ejemplo
> `flask run --host 0.0.0.0 --debug` o `FLASK_DEBUG=1 flask run --host 0.0.0.0` terminan
> con un mensaje y sin abrir el puerto (D-043). Matices medidos: bajo `flask run`,
> Click lee `FLASK_DEBUG` como booleano (`0`, `false`, `no` y `off` lo apagan; un
> valor que no es booleano, como `banana`, da error); en cambio, con gunicorn u otro
> servidor, `Flask` solo trata `0`, `false` y `no` como falso y **`off` cuenta como
> verdadero**. Por eso, **fuera de `flask run` (gunicorn, uWSGI...) con debug activo y
> sin `SECRET_KEY` la aplicación no se crea**: falla con «Me niego a servir…» en vez de
> usar la clave pública (D-047, ampliación de la ronda 2). Con una `SECRET_KEY` propia
> solo avisa en el log (el host no se conoce ahí). Los comandos de mantenimiento
> (`init-db`, `create-professional`, `send-reminders`) siguen funcionando sin
> `SECRET_KEY`, incluso con `FLASK_DEBUG` definida.

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

En esta versión solo puede haber **un** profesional: si ya existe uno,
`create-professional` se niega a crear un segundo, muestra el mensaje «Ya existe
un profesional; en esta versión solo puede haber uno.» y termina con código 1
(la base de datos también lo impide con un índice único; D-023). Si dos
ejecuciones coinciden, una crea la cuenta y la otra recibe ese mensaje.

### Cookie de sesión y variables de despliegue

La cookie de sesión es `HttpOnly` y `SameSite=Lax`. Con HTTPS, actívale `Secure`
(D-042):

| Variable | Valores | Efecto |
|---|---|---|
| `SESSION_COOKIE_SECURE` | `1`, `true`, `yes`, `on`, `si`, `sí` activan; `0`, `false`, `no`, `off` o vacía desactivan (sin importar mayúsculas) | La cookie solo viaja por HTTPS. Otro valor (`maybe`, `2`...) **aborta el arranque** con un mensaje: no se interpreta en silencio como falso. |
| `TRUSTED_PROXY_COUNT` | entero 0 a 10 (por defecto `0`) | Cuántos proxies **propios** hay delante de la app. Con `1`, la dirección del cliente es la última de `X-Forwarded-For`; lo que el cliente antepone no cuenta. Con `0` la cabecera se ignora. |

Desactivada por defecto para poder probar en `http://localhost`. Si se sirve la app
(`flask run` sin debug, gunicorn...) sin ella, el log avisa al arrancar. Si la app está
detrás de un proxy, **configura `TRUSTED_PROXY_COUNT`**. Consecuencia de no hacerlo: la
aplicación ignora `X-Forwarded-For`/`X-Real-IP` y el límite de intentos (abajo) ve a todos
los clientes como la dirección del proxy, así que **20 intentos fallidos de cualquiera
bloquean el acceso de todos, incluido el profesional con su contraseña correcta, durante
15 minutos**, y un atacante lo sostiene con 20 peticiones cada 15 minutos. Si llegan esas
cabeceras sin la variable, el log lo avisa una vez por proceso. Al revés, un valor mayor
que los proxies reales deja a un cliente falsificar su dirección: usa exactamente la
cantidad de proxies propios (el proxy debe sobrescribir `X-Forwarded-For`, no solo añadirle).

### Límite de intentos de login y registro

Para frenar la fuerza bruta y el costo de CPU del hash, los intentos se cuentan en la
tabla `intentos_acceso` de la misma base de datos (funciona con varios procesos). Ventana
de **15 minutos**: login, **5 fallos** por dirección y correo, **20** por dirección (con
cualquier correo) y **30** por correo (desde cualquier dirección); registro, **10** por
dirección. Al superarlo la respuesta es 429 con «Demasiados intentos… espera N minutos»,
igual para un correo que existe y uno que no, y sin probar ninguna contraseña. Un login
correcto no cuenta. El detalle, y el riesgo de que alguien bloquee a un tercero, están en
`DECISIONS.md` (D-045). Para levantar un bloqueo antes de tiempo (solo el administrador):
`DELETE FROM intentos_acceso;` en la base.

### Versión de Python

El proyecto pide Python 3.11+, pero se probó con **3.13** (Unicode 15.1). La política de
caracteres del correo juzga cada letra por la versión de Unicode de Python: con una
versión más antigua, un correo con una letra añadida después podría rechazarse al iniciar
sesión. Si la app se sirve con un Python con Unicode anterior al 15.1, el log avisa. Mantén
la misma versión (o una más nueva) que la que creó las cuentas.

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
