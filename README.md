# Agenda Psi — agendamiento de sesiones con psicólogo

Proyecto de práctica para aprender a trabajar con múltiples agentes de IA.
Aplicación web liviana donde un **profesional** publica horas disponibles y los
**pacientes** las reservan.

## Qué hace (resumen)

- Registro e inicio de sesión (roles: `paciente`, `profesional`).
- El profesional agrega y elimina horas disponibles.
- El paciente ve las horas libres, reserva una y la cancela con al menos 24 horas de anticipación (lista «Mis reservas» en su panel).
- Dashboard para cada rol (próximas sesiones, historial).
- Notificaciones de confirmación, recordatorio y cancelación (en la base y en un archivo de log que simula el correo).

El detalle está en `SPEC.md`. Las reglas de negocio están resumidas más abajo.

## Stack (liviano a propósito)

- **Python 3.13 recomendado** (3.11+ como mínimo; ver «Versión de Python») con **Flask**
- **SQLite** (un solo archivo, sin servidor ni servicios externos)
- Plantillas **Jinja2** + CSS simple (sin JavaScript ni frameworks de frontend)
- **pytest** para pruebas

## Instalación y primer uso

```bash
python3 -m venv .venv
source .venv/bin/activate        # en Windows: .venv\Scripts\activate
pip install -r requirements.txt
flask --app app init-db          # crea la base de datos (agenda.db)
flask --app app create-professional --email profesional@ejemplo.cl --nombre "Nombre Apellido"
flask --app app run --debug      # http://127.0.0.1:5000  (solo en tu máquina; ver la advertencia de --debug)
python3 -m pytest                # corre las pruebas (unos 45 s)
```

`create-professional` pide la contraseña (mínimo 8 caracteres) y la repite. Luego entra en
`/login` con ese correo; los pacientes se registran solos en `/registro`. **Registrarse no inicia
sesión:** al crear la cuenta te lleva al inicio con el aviso «Tu cuenta fue creada correctamente.»
y luego debes entrar en `/login`. Para servir sin
`--debug` hay que definir `SECRET_KEY` (siguiente sección).

## Variables de entorno

| Variable | Por defecto | Qué hace |
|---|---|---|
| `SECRET_KEY` | (ninguna) | Clave con la que Flask firma sesiones y tokens CSRF. **Obligatoria para servir** fuera de `--debug` (ver abajo). |
| `DATABASE` | `agenda.db` en la carpeta del proyecto | Ruta del archivo SQLite. Usa una ruta **absoluta**: una relativa depende del directorio de trabajo de cada proceso. |
| `OUTBOX_PATH` | `outbox.log` junto a la base de datos | Archivo donde se anotan los avisos (ver «Notificaciones y `outbox.log`»). |
| `SESSION_COOKIE_SECURE` | desactivada | Con HTTPS, `1` hace que la cookie de sesión solo viaje cifrada (ver «Despliegue»). |
| `TRUSTED_PROXY_COUNT` | `0` | Cantidad de proxies propios delante de la app (ver «Despliegue»). |
| `FLASK_DEBUG` | (sin definir) | Lo lee Flask: es el modo debug. **Solo para tu máquina** (ver la advertencia). |

El servidor web, el cron de `send-reminders` y los comandos de mantenimiento deben ver los
**mismos** `DATABASE` y `OUTBOX_PATH`. Las pruebas ignoran todas estas variables: crean sus
propias bases en una carpeta temporal.

### `SECRET_KEY`

Si alguien conoce la clave, puede falsificar sesiones y tokens CSRF: debe ser larga, aleatoria
y no subirse al repositorio. Genera una así y defínela antes de servir:

```bash
export SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
flask --app app run
```

En Windows (PowerShell):

```powershell
$env:SECRET_KEY = python -c "import secrets; print(secrets.token_hex(32))"
flask --app app run
```

En desarrollo con `flask --app app run --debug` y en las pruebas **no hace falta**: se usa un
valor de desarrollo inseguro (ver la advertencia siguiente). Los comandos de mantenimiento
(`init-db`, `create-professional`, `send-reminders`) tampoco la necesitan. Fuera de debug, si
falta `SECRET_KEY` (o solo tiene espacios), la app **no atiende ninguna petición**: cada una
responde error 500 y el log indica qué falta. Con `flask run` (o un servidor WSGI) sin clave, el
log muestra además un aviso al arrancar.

### Advertencia: `--debug` y `FLASK_DEBUG` son solo para tu máquina

El modo debug ofrece un depurador interactivo que permite **ejecutar código en el servidor** a
quien llegue a él. Además, **si no defines `SECRET_KEY`**, en debug se usa una clave pública fija
(está en el código) con la que cualquiera podría falsificar sesiones y tokens CSRF, incluida la
sesión del profesional; con una `SECRET_KEY` propia esa parte no aplica, pero el depurador sí.

Qué hace la aplicación para evitarlo (D-043, D-047, D-049, D-050):

- `flask run` **se niega a arrancar** con debug (o con `--debugger`) si el host no es local
  (`127.0.0.1`, `localhost`, `::1`): `flask run --host 0.0.0.0 --debug` o
  `FLASK_DEBUG=1 flask run --host 0.0.0.0` terminan con un mensaje y sin abrir el puerto.
- **Fuera de `flask run`** (gunicorn, uWSGI, un script propio) con debug activo y **sin
  `SECRET_KEY`** la aplicación **no se crea**: falla con «Me niego a servir…» en vez de usar la
  clave pública. Con una `SECRET_KEY` propia solo avisa en el log, porque ahí el host no se
  conoce. Un script propio, aunque use Click, cuenta como «fuera de `flask run`». Si heredas
  `FLASK_DEBUG` en un servicio, define `SECRET_KEY` o quita `FLASK_DEBUG` de ese proceso.
- La clave de desarrollo solo se usa cuando el programa `flask` ejecuta `run` o un comando de
  mantenimiento (`init-db`, `create-professional`, `send-reminders`, que no sirven peticiones), o
  en las pruebas.
- Cómo se lee `FLASK_DEBUG` (medido): bajo `flask run`, Click lo trata como booleano (`0`, `false`,
  `no` y `off` lo apagan; un valor que no es booleano, como `banana`, da error). Fuera de
  `flask run`, Flask solo trata `0`, `false` y `no` como falso: **`off` cuenta como verdadero**.

## Cuenta del profesional

```bash
flask --app app create-professional --email profesional@ejemplo.cl --nombre "Nombre Apellido"
```

El comando pide la contraseña en pantalla **sin mostrarla** y la repite para confirmar. No existe
una opción `--password`: así la contraseña no queda en la lista de procesos ni en el historial del
intérprete. Límite: solo queda oculta cuando la terminal es interactiva. Si alimentas la entrada
estándar con una tubería (`printf 'clave\nclave\n' | flask ...`), Python (`getpass`, no Click) no
puede controlar el eco y avisa «Can not control echo on the terminal» y «Warning: Password input
may be echoed.» (el eco no se pudo ocultar); además la contraseña queda escrita en esa línea del
intérprete. Hazlo solo en pruebas.

- **Comprueba la base antes de pedir la contraseña:** si `DATABASE` apunta a un archivo que no
  existe, a una carpeta, a algo que no es SQLite, a una base sin tablas, de solo lectura o
  bloqueada por otro proceso, lo dice (en español, con código 1 y sin traza) **antes** de que la
  escribas. Nunca crea un `.db` vacío.
- En esta versión solo puede haber **un** profesional: si ya existe uno, se niega, muestra «Ya
  existe un profesional; en esta versión solo puede haber uno.» y termina con código 1 (la base
  también lo impide con un índice único, D-023). Si dos ejecuciones coinciden, una crea la cuenta
  y la otra recibe ese mensaje.

## Reglas de negocio

Resumen de `SPEC.md` §4 (cada una tiene pruebas):

1. Una hora solo puede estar reservada por **un** paciente, ni siquiera con dos clics simultáneos.
2. No se pueden crear horas en el pasado.
3. Las horas del profesional no pueden solaparse entre sí.
4. No se puede eliminar una hora ya reservada: primero debe cancelarse.
5. Un paciente no puede tener dos reservas a la misma hora.
6. Las contraseñas se guardan con hash, nunca en texto plano.
7. **Solo se puede reservar si faltan MÁS de 24 horas** para el inicio, medido en instantes
   absolutos (no en hora de pared); a las 24 horas exactas ya no se puede reservar. **Cancelar sí
   se permite con 24 horas exactas**, de modo que toda reserva aceptada puede cancelarse en el
   momento de hacerla (D-029). La lista de horas libres solo ofrece las que cumplen esta regla.
8. La regla 5 es de **solape de intervalos**: dos reservas de un mismo paciente no pueden cruzarse
   aunque no empiecen a la misma hora; dos horas contiguas (una termina cuando empieza la otra) no
   se cruzan.

Las fechas se muestran y se guardan en hora de Chile (`America/Santiago`); la aplicación decide
con instantes absolutos, no con la zona del equipo.

### Horas libres del paciente

`/paciente/horas` muestra las horas libres reservables que empiezan dentro de los próximos
**60 días**, como máximo las **100** primeras (D-044). Si el tope recorta la lista, un aviso lo
dice: «Mostramos las próximas 100 horas; hay más disponibles más adelante.» Si la ventana de 60
días oculta horas posteriores sin llegar al tope, no hay aviso (propuesta pendiente: D-051 C).

## Notificaciones, recordatorios y `outbox.log`

Cada reserva, recordatorio y cancelación se guarda en la tabla `notificaciones` (campana del
panel) y se añade como una línea a `outbox.log`, un archivo de texto que sustituye al correo real
y contiene **nombres y correos**:

- **Permisos:** se crea con modo `0600`, y **todas las carpetas que la app cree** en la ruta con
  `0700`, menos lo que quite el `umask`. Un archivo que ya existe con permisos más amplios **no se
  cambia** (puede ser a propósito) y el log avisa una vez por proceso; ciérralo con
  `chmod 600 outbox.log`. En Windows los modos POSIX no se aplican: protege la carpeta con los
  permisos del sistema.
- **Ubicación:** `OUTBOX_PATH`. Una ruta **relativa** se resuelve respecto al directorio de trabajo
  del proceso (el servidor y el cron pueden escribir en archivos distintos): usa una ruta
  absoluta. Los **enlaces simbólicos se siguen**. Si es un FIFO sin lector, la escritura falla
  enseguida (queda en el log de la app) en vez de bloquear la petición.
- **Si no se puede escribir** (disco lleno, sin permiso), la reserva igual se confirma: el error
  queda en el log de la aplicación y la fila de `notificaciones` es la fuente de verdad.
- **Crecimiento y rotación:** el archivo y la tabla `notificaciones` **crecen sin límite** (no hay
  borrado automático; propuesta pendiente: D-051). El archivo se abre en cada escritura, así que se
  puede rotar renombrándolo (`mv outbox.log outbox.log.1`; la siguiente escritura crea uno nuevo
  con modo `0600`). Con `logrotate` usa el modo por defecto (renombrar y crear), **no**
  `copytruncate`.

### Recordatorios con cron (`send-reminders`)

```bash
flask --app app send-reminders
```

Genera el recordatorio de cada reserva cuyo inicio está a **24 horas o menos** (y todavía no
empezó), una sola vez por reserva, y escribe `Recordatorios enviados: N.`. Está pensado para
ejecutarse **periódicamente con un período menor de 24 horas** (lo normal: cada 15 minutos o
cada hora): una reserva se recuerda en la primera ejecución en que le faltan 24 horas o menos, y
con un período de 24 horas o más habría sesiones que se reservan, se reservan y se pasan sin aviso.
Con el período de ejemplo, el aviso llega hasta 15 minutos tarde.

Ejemplo de `crontab -e` (cada 15 minutos; ajusta las rutas):

```cron
MAILTO=admin@ejemplo.cl
*/15 * * * * cd /srv/agenda-psi && DATABASE=/var/lib/agenda/agenda.db OUTBOX_PATH=/var/log/agenda/outbox.log .venv/bin/flask --app app send-reminders >> /var/log/agenda/recordatorios.log
```

- Debe ver los **mismos `DATABASE` y `OUTBOX_PATH` que el servidor web** (rutas absolutas); si no,
  avisará sobre otra base. No necesita `SECRET_KEY`.
- **Código de salida:** 0 si terminó (aunque no hubiera nada que enviar); **1** si falló, con un
  mensaje en español y sin traza en la salida de error. Falla (y no crea un `.db` vacío) si el
  archivo no existe, la carpeta no existe, la ruta es una carpeta, el archivo no es SQLite o no
  tiene las tablas. Con la base bloqueada más de 5 segundos no cambia nada y termina con 1; la
  siguiente ejecución del cron lo reintenta. Con `MAILTO`, cron te envía por correo la salida de
  una ejecución fallida (el ejemplo manda solo la salida normal al archivo; los errores salen por la
  salida de error y llegan por correo).
- Es seguro ejecutar varias a la vez: nunca duplica un recordatorio.

## Despliegue detrás de HTTPS y un proxy

La aplicación no habla HTTPS por sí sola: se sirve con un servidor WSGI detrás de un proxy inverso
(nginx, Caddy…) que termina el HTTPS. Ejemplo con gunicorn (no forma parte de `requirements.txt`;
instálalo aparte con `pip install gunicorn`):

```bash
export SECRET_KEY=...            # obligatoria
export DATABASE=/var/lib/agenda/agenda.db
export OUTBOX_PATH=/var/log/agenda/outbox.log
export SESSION_COOKIE_SECURE=1   # solo con HTTPS
export TRUSTED_PROXY_COUNT=1     # un proxy propio delante
gunicorn --bind 127.0.0.1:8000 'app:create_app()'
```

El proxy debe pasar `X-Forwarded-For`; por ejemplo, en nginx: `proxy_set_header X-Forwarded-For
$proxy_add_x_forwarded_for;` y `proxy_pass http://127.0.0.1:8000;`. (El ejemplo de nginx no se
ejecutó en el desarrollo de este proyecto; el de gunicorn sí.)

| Variable | Valores | Efecto |
|---|---|---|
| `SESSION_COOKIE_SECURE` | `1`, `true`, `yes`, `on`, `si`, `sí` activan; `0`, `false`, `no`, `off` o vacía desactivan (sin importar mayúsculas) | La cookie solo viaja por HTTPS. Otro valor (`maybe`, `2`…) **aborta el arranque** con un mensaje: no se interpreta en silencio como falso. |
| `TRUSTED_PROXY_COUNT` | entero 0 a 10 (por defecto `0`) | Cuántos proxies **propios** hay delante. Con `1`, la dirección del cliente es la última de `X-Forwarded-For` (la que añade tu proxy); lo que el cliente antepone no cuenta. Con `0` la cabecera se ignora. |

La cookie de sesión es siempre `HttpOnly` y `SameSite=Lax`. `SESSION_COOKIE_SECURE` está
desactivada por defecto para poder probar en `http://localhost`; si se sirve la app sin ella, el
log avisa al arrancar. Con HTTPS, actívala: sin `Secure`, una página servida por HTTP puede
filtrar la cookie.

**Detrás de un proxy hay que configurar `TRUSTED_PROXY_COUNT`.** Si no, la aplicación ignora
`X-Forwarded-For` y el límite de intentos (siguiente sección) ve a todos los clientes como la
dirección del proxy: **20 intentos fallidos de cualquiera bloquean el acceso de todos, incluido
el profesional con su contraseña correcta, durante 15 minutos**, y un atacante lo sostiene con 20
peticiones cada 15 minutos. Si llegan `X-Forwarded-For` o `X-Real-IP` sin la variable, el log lo
avisa una vez por proceso. Al revés, un valor **mayor** que los proxies reales deja a un cliente
falsificar su dirección: usa exactamente la cantidad de proxies propios. Aviso sobre otras
cabeceras: **la aplicación solo lee `X-Forwarded-For`**. Ni `Forwarded` ni `X-Real-IP` se usan
(medido: con `TRUSTED_PROXY_COUNT=1` y solo `X-Real-IP` o `Forwarded`, la dirección sigue siendo la
del proxy), y el aviso del log no mira `Forwarded`. Si tu proxy solo manda una de ellas,
configúralo para que envíe `X-Forwarded-For`.

### Límite de intentos de login y registro

Para frenar la fuerza bruta y el costo de CPU del hash, los intentos se cuentan en la tabla
`intentos_acceso` de la misma base (funciona con varios procesos). Ventana de **15 minutos**:
login, **5 fallos** por dirección y correo, **20** por dirección (con cualquier correo) y **30**
por correo (desde cualquier dirección); registro, **10** por dirección. Al superarlo la respuesta
es 429 con «Demasiados intentos… espera N minutos», igual para un correo que existe y uno que no, y
sin probar ninguna contraseña. Un login correcto no cuenta. El detalle y el riesgo de que alguien
bloquee a un tercero están en `DECISIONS.md` (D-045). Para levantar un bloqueo antes de tiempo
(solo el administrador): `DELETE FROM intentos_acceso;` en la base.

### Base ocupada

Si otro proceso retiene el bloqueo de escritura de SQLite más de 5 segundos, reservar, cancelar,
agregar u eliminar una hora, marcar notificaciones como leídas, el login y el registro responden
«El sistema está ocupado en este momento. Espera unos segundos e inténtalo de nuevo.» con código
503 y la cabecera `Retry-After: 5`, y piden reintentar (el formulario de «Agregar hora» conserva lo
escrito). `send-reminders`, `init-db` y `create-professional` terminan con un mensaje parecido, sin
traza y con código 1.

## Actualizar o reparar una base existente

`init-db` es **aditivo** (D-006, ampliado por D-050): crea lo que falta (tablas, índices y la
columna `usuarios.sesion_version`), anota la versión del esquema en `PRAGMA user_version` y
**nunca borra ni reescribe datos ni reconstruye una tabla existente**. Todo ocurre en una sola
transacción y las decisiones se toman dentro de ella (dos `init-db` simultáneos no se pisan): si
algo falla, la base queda como estaba. Tras actualizar el código, ejecútalo una vez más sobre tu
`agenda.db`:

```bash
flask --app app init-db
```

Con una base antigua imprime qué hizo («Base de datos actualizada: se agregó la columna
usuarios.sesion_version; se creó la tabla intentos_acceso…») y no pierde usuarios, horas ni
notificaciones. Mientras no lo ejecutes, el login y el registro sobre una base antigua responden
una página «503» en español que pide avisar a quien administra el sistema (el log lleva el
detalle), no un 500 con traza.

Si el archivo no sirve, `init-db` lo dice en español, termina con código 1, **sin traza** y sin
tocar nada: no es SQLite, está dañado, es una carpeta, la carpeta no existe, es de solo lectura o
está bloqueado por otro proceso.

Lo que `init-db` **no** puede hacer:

- **Dos o más profesionales** (base anterior a T-08d): la versión actual admite uno solo. `init-db`
  **se detiene sin cambiar nada** y explica cómo decidir qué cuenta conservar; no borra ninguna.
- **Una base de una versión más nueva** (`user_version` mayor que el de esta versión): imprime
  «Base de datos sin cambios.» y un aviso, y **no cambia nada**: ni su número ni sus tablas ni sus
  índices.
- **Tablas de un esquema anterior sin sus restricciones nuevas** (por ejemplo antes de T-02c o
  T-02g: los `CHECK`, el formato de `horas.inicio`). Agregar una restricción a una tabla existente
  exige reconstruirla, y eso no se hace sin que lo decidas tú. `init-db` lo **avisa** por la salida
  de error («Aviso: La tabla … se creó con un esquema anterior…») y la base sigue funcionando sin
  esas protecciones.

### Bases creadas por versiones antiguas: eliminar una hora que tuvo avisos

Las bases creadas con los esquemas de los commits `748f18e` y `cd9f209` (las primeras ~48 horas
del proyecto, antes de D-016) tienen la clave foránea `notificaciones.hora_id` **sin
`ON DELETE SET NULL`**. Eso **no es inocuo**: reservar, cancelar y todo lo demás funciona, pero
**el profesional no puede eliminar una hora que alguna vez tuvo avisos** (el caso normal «se reservó,
se canceló, ahora la quiero borrar»). `init-db` lo detecta (`PRAGMA foreign_key_list`) **cada vez
que se ejecuta**, aunque la versión del esquema ya esté anotada, y muestra:

> Aviso: La tabla notificaciones es de un esquema anterior a D-016: su clave foránea hora_id no
> tiene ON DELETE SET NULL. Consecuencia: el profesional NO podrá eliminar una hora que alguna vez
> tuvo avisos… 

El servidor lo repite en su log al arrancar. Si el profesional intenta eliminar esa hora, ve el
mensaje «No se pudo eliminar esta hora porque ya tuvo avisos y la base de datos es de una versión
antigua que no lo permite. No se cambió nada…» (código 302 al panel, no un 500) y el log de la
aplicación lleva el detalle. **Ningún dato cambia ni se pierde.**

Cómo corregirlo (en este orden; nada de esto lo hace la aplicación por ti):

1. Detén el servidor y guarda una copia del archivo: `cp agenda.db agenda.db.respaldo`.
2. **Si es una base de práctica y no necesitas sus datos**, bórrala y vuelve a crearla (esto sí
   borra todo: usuarios, horas y avisos):

   ```bash
   rm agenda.db                     # en Windows: del agenda.db
   flask --app app init-db
   flask --app app create-professional --email profesional@ejemplo.cl --nombre "Nombre Apellido"
   ```

3. **Si necesitas los datos**, déjala como está: todo funciona salvo eliminar horas que tuvieron
   avisos (cancela y deja la hora libre, que sigue ofreciéndose). Reconstruir la tabla
   `notificaciones` conservando los datos es una decisión pendiente del humano (propuesta en
   D-052).

## Pruebas

```bash
python3 -m pytest
```

Unas 2 250 pruebas, ~45 segundos. Son herméticas: ignoran `SECRET_KEY`, `DATABASE`,
`OUTBOX_PATH`, `SESSION_COOKIE_SECURE`, `TRUSTED_PROXY_COUNT` y `FLASK_DEBUG`, y no dejan
`agenda.db` ni `outbox.log` en el proyecto. Las bases temporales van a `/dev/shm` si hay sitio
(`AGENDA_PSI_TMPFS=0` lo evita).

### Versión de Python

Se prueba con **Python 3.13** (Unicode 15.1) y ese es el recomendado. La política de caracteres
del correo juzga cada letra por la versión de Unicode de Python: con una versión más antigua, un
correo con una letra añadida después podría rechazarse al iniciar sesión aunque la cuenta exista.
Si la app se sirve con Unicode anterior al 15.1, el log avisa. Mantén la misma versión (o una más
nueva) que la que creó las cuentas.

Medido en entornos nuevos (`python3.11 -m venv` / `python3.12 -m venv` + `pip install -r
requirements.txt`): la suite completa pasa en 3.11, 3.12 y 3.13 (2 249 pruebas, 1 saltada: la de
una base de solo lectura por permisos, que no corre como `root`). Que pase no cambia la
recomendación: la política de caracteres del correo (Unicode) se probó con 3.13; en 3.11 y 3.12
una letra añadida en Unicode 15.1 (por ejemplo `U+2EBF0`, de 3.13) se rechaza en el registro, así
que no mezcles versiones sobre una misma base de cuentas.

### Windows

Sin ejecutar nada en Windows (no hay un equipo de ese tipo en el desarrollo), esto es lo que el
código y las pruebas dicen:

- Las instrucciones de este README usan `source .venv/bin/activate`, `rm` y `cp`; en Windows usa
  `.venv\Scripts\activate`, `del` y `copy`, y PowerShell para `SECRET_KEY` (arriba). Las
  tareas programadas de Windows sustituyen al cron.
- **Pruebas que se saltan:** Windows no tiene `time.tzset`, así que no se puede cambiar la zona
  horaria del proceso. Las 7 pruebas que piden la fixture `zona_sistema` (21 casos: cada una
  repetida con el sistema en UTC, Tokio y Santiago) se **saltan**, y la fixture que fija la zona
  del sistema en UTC en cada prueba no hace nada. Esas pruebas comprueban que los bordes de las 24
  horas (reservar, cancelar, recordatorios, horas libres) no dependen de la zona del equipo
  (la aplicación decide con `zoneinfo` e instantes absolutos). **Qué cubre y qué no:** en Windows
  el resto de la suite sí corre, pero con la zona del equipo; esa independencia de la zona del
  sistema **solo se comprueba en Linux/macOS**. Si tu equipo Windows está en la zona de Chile, un
  error que mezclara la hora de pared con la del sistema pasaría desapercibido ahí.
- **Permisos:** los modos `0600`/`0700` del `outbox.log` son de POSIX; en Windows no se aplican
  (rigen las ACL) y las pruebas de permisos, de FIFO y las que usan `fork` se saltan.
- No se ha probado la instalación ni el servidor en Windows.

## Recorrido de prueba (de punta a punta)

Con la base creada y la cuenta del profesional (arriba), servidor en marcha:

1. Registra un paciente en `/registro` (no inicia sesión: luego entra en `/login` con ese correo).
2. Entra como profesional (`/login`) y agrega una hora **a más de 24 horas** en el futuro
   («Agregar hora»); agrega otra más lejana.
3. Entra como paciente, abre «Reservar hora», reserva la primera: aparece la confirmación y la
   campana del panel suma un aviso; el profesional ve la reserva y su aviso.
4. **Recordatorio:** el recordatorio solo existe cuando faltan 24 horas o menos y reservar exige
   más de 24, así que para probarlo acerca la hora por SQL y ejecuta el comando:

   ```bash
   python3 - <<'EOF'
   import sqlite3
   from datetime import datetime, timedelta
   from zoneinfo import ZoneInfo
   # el inicio de la primera reserva pasa a dentro de 12 horas (hora de pared de Chile, sin zona)
   inicio = (datetime.now(ZoneInfo("America/Santiago")) + timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:00")
   con = sqlite3.connect("agenda.db")   # o la ruta de tu DATABASE
   con.execute(
       "UPDATE horas SET inicio = ? WHERE id = (SELECT MIN(id) FROM horas WHERE estado = 'reservada')",
       (inicio,),
   )
   con.commit()
   EOF
   flask --app app send-reminders      # «Recordatorios enviados: 1.»
   ```

   El paciente ve el recordatorio en su campana
   y en `outbox.log`.
5. **Cancelación:** con una reserva a más de 24 horas (o a 24 exactas), el paciente la cancela desde
   «Mis reservas»; la hora vuelve a quedar libre y ambos reciben el aviso.

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

Es un proyecto de aprendizaje. No guarda datos clínicos reales ni debe usarse en producción sin
una revisión de seguridad y privacidad.
