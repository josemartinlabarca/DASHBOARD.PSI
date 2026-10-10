CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    rol TEXT NOT NULL CHECK (rol IN ('paciente', 'profesional')),
    creado_en TEXT NOT NULL,
    sesion_version INTEGER NOT NULL DEFAULT 0
);

-- Un solo profesional en v1 (D-004, D-023): la base impide un segundo. El índice es
-- parcial: los pacientes (rol 'paciente') no entran en él y pueden ser muchos.
CREATE UNIQUE INDEX IF NOT EXISTS un_solo_profesional ON usuarios (rol) WHERE rol = 'profesional';

CREATE TABLE IF NOT EXISTS horas (
    id INTEGER PRIMARY KEY,
    profesional_id INTEGER NOT NULL REFERENCES usuarios (id),
    inicio TEXT NOT NULL,
    duracion_min INTEGER NOT NULL DEFAULT 50 CHECK (duracion_min > 0),
    estado TEXT NOT NULL DEFAULT 'libre' CHECK (estado IN ('libre', 'reservada')),
    paciente_id INTEGER REFERENCES usuarios (id),
    reservada_en TEXT,
    recordatorio_enviado INTEGER NOT NULL DEFAULT 0 CHECK (recordatorio_enviado IN (0, 1)),
    CHECK (
        (estado = 'libre' AND paciente_id IS NULL AND reservada_en IS NULL)
        OR (estado = 'reservada' AND paciente_id IS NOT NULL AND reservada_en IS NOT NULL)
    ),
    CHECK (inicio GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]' AND instr(inicio, char(0)) = 0),
    UNIQUE (profesional_id, inicio)
);

CREATE TABLE IF NOT EXISTS notificaciones (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios (id),
    tipo TEXT NOT NULL CHECK (tipo IN ('confirmacion', 'recordatorio', 'cancelacion')),
    mensaje TEXT NOT NULL,
    hora_id INTEGER REFERENCES horas (id) ON DELETE SET NULL,
    leida INTEGER NOT NULL DEFAULT 0 CHECK (leida IN (0, 1)),
    creada_en TEXT NOT NULL
);

-- Límite de intentos de login y registro (D-041, D-045). Una fila por intento; `ambito`
-- dice qué se cuenta: la dirección ('ip'), la dirección con el correo ('par') o el correo
-- ('correo'). `instante` son segundos desde 1970 (UTC). Las filas vencidas se borran al
-- anotar un intento nuevo. Una base creada antes de esta tabla la recibe con `init-db`
-- (CREATE TABLE IF NOT EXISTS no toca las demás tablas ni borra datos).
CREATE TABLE IF NOT EXISTS intentos_acceso (
    id INTEGER PRIMARY KEY,
    accion TEXT NOT NULL CHECK (accion IN ('login', 'registro')),
    ambito TEXT NOT NULL CHECK (ambito IN ('ip', 'par', 'correo')),
    clave TEXT NOT NULL CHECK (typeof(clave) = 'text' AND length(clave) > 0),
    instante INTEGER NOT NULL CHECK (typeof(instante) = 'integer' AND instante > 0)
);

CREATE INDEX IF NOT EXISTS intentos_acceso_clave ON intentos_acceso (accion, ambito, clave, instante);

-- Borrado de filas vencidas y reubicación de marcas futuras por `instante` (T-14b, D-050). Sin
-- este índice cada intento recorría toda la tabla dentro del bloqueo de escritura.
CREATE INDEX IF NOT EXISTS intentos_acceso_instante ON intentos_acceso (instante);
