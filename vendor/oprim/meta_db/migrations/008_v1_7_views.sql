-- Phase 13: Views (检索视角) table
CREATE TABLE IF NOT EXISTS views (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    default_filter TEXT,            -- JSON: {"medium": [...], "domain": [...], "time_range": "..."}
    default_llm TEXT,               -- JSON: {"provider": "...", "model": "..."}
    default_system_prompt TEXT,
    icon TEXT,
    is_default BOOLEAN DEFAULT FALSE,
    is_builtin BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_views_user_default
    ON views(user_id, is_default DESC);

CREATE INDEX IF NOT EXISTS idx_views_user_name
    ON views(user_id, name)
