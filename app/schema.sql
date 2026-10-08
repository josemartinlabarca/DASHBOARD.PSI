CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    rol TEXT NOT NULL CHECK (rol IN ('paciente', 'profesional')),
    creado_en TEXT NOT NULL
);

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
    CHECK (inicio GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]'),
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
