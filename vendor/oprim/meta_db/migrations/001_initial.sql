-- Stratum initial schema migration
-- Creates substrate, derivative, concept, note, and changefeed_local tables.
-- Note: DuckDB 1.5 does not support CASCADE/SET NULL on FK constraints.

CREATE TABLE IF NOT EXISTS substrate (
    id          TEXT PRIMARY KEY,
    ulid        TEXT UNIQUE NOT NULL,
    title       TEXT,
    mime        TEXT,
    source_path TEXT,
    file_hash   TEXT,
    byte_size   INTEGER,
    page_count  INTEGER,
    parser      TEXT,
    language    TEXT,
    has_cjk     BOOLEAN DEFAULT FALSE,
    is_scanned  BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    meta_json   TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_substrate_ulid ON substrate (ulid);
CREATE INDEX IF NOT EXISTS idx_substrate_file_hash ON substrate (file_hash);
CREATE INDEX IF NOT EXISTS idx_substrate_created_at ON substrate (created_at);

CREATE TABLE IF NOT EXISTS derivative (
    id            TEXT PRIMARY KEY,
    substrate_id  TEXT NOT NULL,
    kind          TEXT NOT NULL,
    seq           INTEGER DEFAULT 0,
    content       TEXT,
    embedding_id  TEXT,
    embedding_dim INTEGER,
    meta_json     TEXT DEFAULT '{}',
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_derivative_substrate_id ON derivative (substrate_id);
CREATE INDEX IF NOT EXISTS idx_derivative_kind ON derivative (kind);

CREATE TABLE IF NOT EXISTS concept (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    aliases     TEXT,
    description TEXT,
    wikilink    TEXT UNIQUE,
    source_ids  TEXT DEFAULT '[]',
    meta_json   TEXT DEFAULT '{}',
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_concept_wikilink ON concept (wikilink);

CREATE TABLE IF NOT EXISTS note (
    id           TEXT PRIMARY KEY,
    title        TEXT,
    content      TEXT,
    wikilinks    TEXT DEFAULT '[]',
    substrate_id TEXT,
    meta_json    TEXT DEFAULT '{}',
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_note_substrate_id ON note (substrate_id);

CREATE TABLE IF NOT EXISTS changefeed_local (
    seq         BIGINT PRIMARY KEY,
    table_name  TEXT NOT NULL,
    row_id      TEXT NOT NULL,
    op          TEXT NOT NULL,
    payload     TEXT,
    ts          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE SEQUENCE IF NOT EXISTS changefeed_seq START 1;
