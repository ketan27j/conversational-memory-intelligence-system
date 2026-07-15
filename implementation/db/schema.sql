-- Schema for the Conversational Memory Intelligence System.
-- Source of truth for field choices: design/data_model.md
-- Source of truth for the isolation approach: design/ADR-004-separation-inside-the-database.md

CREATE EXTENSION IF NOT EXISTS vector;

-- ── memory ──────────────────────────────────────────────────────────────────
CREATE TABLE memory (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID NOT NULL,
    type             TEXT NOT NULL CHECK (type IN ('event', 'fact', 'preference', 'working')),
    content          TEXT NOT NULL,
    embedding        vector(1536),
    content_tsv      TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    importance       SMALLINT NOT NULL CHECK (importance BETWEEN 1 AND 10),
    confidence       REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    source_turn_id   UUID,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_accessed_at TIMESTAMPTZ,
    access_count     INTEGER NOT NULL DEFAULT 0,
    weight           REAL NOT NULL DEFAULT 1.0,
    status           TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived', 'deleted')),
    superseded_by    UUID REFERENCES memory(id)
);

CREATE INDEX idx_memory_tenant_id ON memory (tenant_id);
CREATE INDEX idx_memory_embedding ON memory USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_memory_content_tsv ON memory USING gin (content_tsv);

ALTER TABLE memory ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory FORCE ROW LEVEL SECURITY;

-- INV-1 (context-graph.json): no query, however written, can return another
-- tenant's rows. The session variable is set once per connection/request from
-- the verified auth token — never from a client-supplied field.
CREATE POLICY tenant_isolation ON memory
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

-- ── memory_entity ────────────────────────────────────────────────────────────
CREATE TABLE memory_entity (
    memory_id  UUID NOT NULL REFERENCES memory(id) ON DELETE CASCADE,
    tenant_id  UUID NOT NULL,
    entity     TEXT NOT NULL,
    PRIMARY KEY (memory_id, entity)
);

CREATE INDEX idx_memory_entity_tenant_id ON memory_entity (tenant_id);
CREATE INDEX idx_memory_entity_entity ON memory_entity (entity);

ALTER TABLE memory_entity ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_entity FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON memory_entity
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

-- ── conversation_turn ────────────────────────────────────────────────────────
CREATE TABLE conversation_turn (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id  UUID NOT NULL,
    session_id UUID NOT NULL,
    role       TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    text       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_conversation_turn_tenant_id ON conversation_turn (tenant_id);
CREATE INDEX idx_conversation_turn_session_id ON conversation_turn (session_id);

ALTER TABLE conversation_turn ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_turn FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON conversation_turn
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

-- ── audit_log ────────────────────────────────────────────────────────────────
-- Append-only: no UPDATE/DELETE grants issued to the application role (see M0 tests).
CREATE TABLE audit_log (
    id         BIGSERIAL PRIMARY KEY,
    tenant_id  UUID NOT NULL,
    actor      TEXT NOT NULL,
    action     TEXT NOT NULL CHECK (action IN ('stored', 'rejected', 'retrieved', 'replaced', 'archived', 'deleted', 'blocked_secret')),
    memory_id  UUID,
    detail     TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_audit_log_tenant_id ON audit_log (tenant_id);

ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON audit_log
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

-- ── application role ─────────────────────────────────────────────────────────
-- The app connects as a non-superuser role. RLS is not bypassed by superusers
-- or table owners unless BYPASSRLS is granted — this role never gets it.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cmis_app') THEN
        CREATE ROLE cmis_app LOGIN PASSWORD 'cmis_app_dev_only' NOBYPASSRLS;
    END IF;
END
$$;

GRANT CONNECT ON DATABASE cmis TO cmis_app;
GRANT USAGE ON SCHEMA public TO cmis_app;
GRANT SELECT, INSERT, UPDATE ON memory, memory_entity, conversation_turn TO cmis_app;
GRANT SELECT, INSERT ON audit_log TO cmis_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO cmis_app;
