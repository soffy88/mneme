-- Phase 1.5: add substrate pinning support
ALTER TABLE substrate ADD COLUMN IF NOT EXISTS is_pinned BOOL DEFAULT FALSE;
ALTER TABLE substrate ADD COLUMN IF NOT EXISTS pinned_at TIMESTAMP NULL;

CREATE INDEX IF NOT EXISTS idx_substrate_pinned ON substrate(is_pinned, pinned_at DESC)
