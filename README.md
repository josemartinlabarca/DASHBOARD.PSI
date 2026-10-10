# Agenda Psi — agendamiento de sesiones con psicólogo

Proyecto de práctica para aprender a trabajar con múltiples agentes de IA.
Aplicación web liviana donde un **profesional** publica horas disponibles y los
**pacientes** las reservan.

## Qué hace (resumen)

- Registro e inicio de sesión (roles: `paciente`, `profesional`).
- El profesional agrega y elimina horas disponibles.
- El paciente ve las horas libres, reserva una y la cancela con al menos 24 horas de anticipación (lista «Mis reservas» en su panel). Reservar exige **más de** 24 horas: a las 24 horas exactas ya no se puede reservar, pero sí cancelar (regla 7 de `SPEC.md`, D-029).
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

`init-db` es **aditivo** (D-006, ampliado por D-050): crea lo que falta (tablas, índices y la
columna `usuarios.sesion_version`), anota la versión del esquema en `PRAGMA user_version` y
**nunca borra ni reescribe datos ni reconstruye una tabla existente**. Todo ocurre en una sola
transacción: si algo falla, la base queda como estaba. Tras actualizar el código, ejecútalo
una vez más sobre tu `agenda.db`:

```bash
flask --app app init-db
```

Con una base antigua imprime qué hizo («Base de datos actualizada: se agregó la columna
usuarios.sesion_version; se creó la tabla intentos_acceso…») y no pierde usuarios, horas ni
notificaciones. Lo que **no** puede hacer:

- **Tablas de un esquema anterior sin sus restricciones nuevas** (por ejemplo antes de T-02c,
  T-02f o T-02g: `ON DELETE SET NULL` en `notificaciones.hora_id`, el formato de `horas.inicio`).
  Agregar una restricción a una tabla existente exige reconstruirla, y eso no se hace sin que
  lo decidas tú. `init-db` lo **avisa** por la salida de error («Aviso: La tabla … se creó con un
  esquema anterior…») y la base sigue funcionando, sin esas protecciones. Si no necesitas los datos,
  bórrala y vuelve a crearla (esto sí borra todo):

  ```bash
  rm agenda.db                     # en Windows: del agenda.db
  flask --app app init-db
  ```

- **Dos o más profesionales** (base anterior a T-08d): la versión actual admite uno solo y la base
  lo impide con el índice `un_solo_profesional`. `init-db` **se detiene sin cambiar nada** y explica
  cómo decidir qué cuenta conservar; no borra ninguna.
- **Una base de una versión más nueva** (`user_version` mayor que el de esta versión): avisa y no
  cambia su número.

Mientras no ejecutes `init-db` tras una actualización, el login y el registro sobre una base
antigua responden una página «503» en español que pide avisar a quien administra el sistema (el
log lleva el detalle y la orden a ejecutar), no un 500 con traza.

### Base ocupada

Si otro proceso retiene el bloqueo de escritura de SQLite más de 5 segundos, reservar, cancelar,
agregar u eliminar una hora, marcar notificaciones como leídas, el login y el registro responden
«El sistema está ocupado en este momento. Espera unos segundos e inténtalo de nuevo.» con código
503 y la cabecera `Retry-After: 5`, y piden reintentar (el formulario de «Agregar hora» conserva lo
escrito). `send-reminders` termina con un mensaje parecido, sin traza y con código 1 (el cron reintenta en la
siguiente ejecución). `create-professional` con la base ocupada sigue mostrando la traza de SQLite
(no se cambió; es un comando manual que se repite).

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
> usar la clave pública (D-049; D-047 solo avisaba). La clave de desarrollo se usa
> únicamente con `flask` ejecutando uno de sus comandos (`run` o un comando de mantenimiento:
> `init-db`, `create-professional`, `send-reminders`, que no sirven peticiones) o en las pruebas;
> un script propio, aunque use Click, **no** cuenta (D-050). Con una `SECRET_KEY` propia
> solo avisa en el log (el host no se conoce ahí). **Un script propio o un servidor WSGI que herede
> `FLASK_DEBUG` y no defina `SECRET_KEY` ahora falla al crear la app** («Me niego a servir…»):
> define `SECRET_KEY` o quita `FLASK_DEBUG` del entorno de ese proceso.

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

### Recordatorios (`send-reminders`) y `outbox.log`

```bash
flask --app app send-reminders
```

Debe ver la **misma `DATABASE`** que el servidor. Si el archivo no existe, la carpeta no existe,
la ruta es una carpeta, el archivo no es SQLite o no tiene las tablas, imprime un mensaje claro
en español, termina con código 1, **no muestra traza y no crea un `.db` vacío** (T-10 R-01);
lo mismo con la base ocupada. `create-professional` tampoco crea una base inexistente.

Los avisos (confirmaciones, recordatorios, cancelaciones) se añaden a `outbox.log`, un archivo de
texto que sustituye al correo real y contiene **nombres y correos**:

- **Permisos:** se crea con modo `0600` (carpeta `0700` si la app la crea), menos lo que quite el
  `umask`. Un archivo que ya existe con permisos más amplios **no se cambia** (puede ser a
  propósito) y el log avisa una vez por proceso; ciérralo con `chmod 600 outbox.log`. En Windows
  los modos POSIX no se aplican ni se avisa: protege la carpeta con los permisos del sistema.
- **Ubicación:** `OUTBOX_PATH` (por defecto `outbox.log` en la carpeta de la base de datos). Una ruta
  **relativa** se resuelve respecto al directorio de trabajo del proceso: el servidor y el cron
  pueden escribir en archivos distintos; usa una ruta absoluta. Los **enlaces simbólicos se
  siguen**: si `OUTBOX_PATH` apunta a un enlace, se escribe en su destino.
- **Crecimiento y rotación:** el archivo y la tabla `notificaciones` **crecen sin límite**
  (no hay borrado automático; ver D-051, pendiente del humano). El archivo se abre en cada
  escritura, así que se puede rotar renombrándolo o moviéndolo (`mv outbox.log outbox.log.1`; la
  siguiente escritura crea uno nuevo con modo `0600`). Con `logrotate` usa el modo por defecto
  (renombrar y crear), **no** `copytruncate`.

### Horas libres del paciente

`/paciente/horas` muestra las horas libres que se pueden reservar y empiezan dentro de los próximos
**60 días**, como máximo las **100** primeras (D-044). Si el tope recorta la lista, un aviso lo dice:
«Mostramos las próximas 100 horas; hay más disponibles más adelante.»

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
