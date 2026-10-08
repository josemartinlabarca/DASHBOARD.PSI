CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    rol TEXT NOT NULL CHECK (rol IN ('paciente', 'profesional')),
    creado_en TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS horas (
    id INTEGER PRIMARY KEY,
    profesional_id INTEGER NOT NULL REFERENCES usuarios (id),
    inicio TEXT NOT NULL,
    duracion_min INTEGER NOT NULL DEFAULT 50,
    estado TEXT NOT NULL DEFAULT 'libre' CHECK (estado IN ('libre', 'reservada')),
    paciente_id INTEGER REFERENCES usuarios (id),
    reservada_en TEXT,
    recordatorio_enviado INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS notificaciones (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios (id),
    tipo TEXT NOT NULL,
    mensaje TEXT NOT NULL,
    hora_id INTEGER REFERENCES horas (id),
    leida INTEGER NOT NULL DEFAULT 0,
    creada_en TEXT NOT NULL
);
