-- =========================
-- Base existente (idempotente)
-- =========================
CREATE TABLE IF NOT EXISTS alerts(
  id          BIGSERIAL PRIMARY KEY,
  fingerprint TEXT,
  alertname   TEXT,
  labels      JSONB,
  starts_at   TIMESTAMPTZ,
  status      TEXT,
  created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS alerts_fingerprint_idx ON alerts (fingerprint);

CREATE TABLE IF NOT EXISTS decisions(
  id             BIGSERIAL PRIMARY KEY,
  alert_id       BIGINT REFERENCES alerts(id),
  path           TEXT,                 -- 'history' | 'kb' | 'semantic' | 'fallback'
  rule_id        TEXT,                 -- p.ej. 'kb:123' o 'previous'
  context        JSONB,
  recommendation JSONB,
  latency_ms     INT,
  created_at     TIMESTAMPTZ DEFAULT now()
);

-- Extensiones de decisions para nueva estrategia (idempotente)
ALTER TABLE decisions ADD COLUMN IF NOT EXISTS kb_id      BIGINT;
ALTER TABLE decisions ADD COLUMN IF NOT EXISTS confidence NUMERIC(5,2);
ALTER TABLE decisions ADD COLUMN IF NOT EXISTS reason     TEXT;
ALTER TABLE decisions ADD COLUMN IF NOT EXISTS ai_request_id TEXT;

-- Feedback (igual que tenías)
CREATE TABLE IF NOT EXISTS feedback(
  id          BIGSERIAL PRIMARY KEY,
  decision_id BIGINT REFERENCES decisions(id),
  vote        BOOLEAN,
  notes       TEXT,
  created_at  TIMESTAMPTZ DEFAULT now()
);

-- AI usage metrics (idempotente)
CREATE TABLE IF NOT EXISTS ai_usage(
  id                BIGSERIAL PRIMARY KEY,
  decision_id       BIGINT REFERENCES decisions(id),
  alert_id          BIGINT REFERENCES alerts(id),
  request_id        TEXT,
  provider          TEXT,
  model             TEXT,
  input_tokens      INT,
  output_tokens     INT,
  estimated_cost_usd NUMERIC(12,6),
  latency_ms        INT,
  created_at        TIMESTAMPTZ DEFAULT now()
);

-- =========================
-- Catálogo de conocimiento (KB)
-- =========================
CREATE TABLE IF NOT EXISTS kb_items (
  id          BIGSERIAL PRIMARY KEY,
  title       TEXT NOT NULL,
  description TEXT,
  severity    TEXT CHECK (severity IN ('low','medium','high','critical')) DEFAULT 'medium',
  tags        TEXT[] DEFAULT '{}',
  enabled     BOOLEAN NOT NULL DEFAULT TRUE,
  version     INTEGER NOT NULL DEFAULT 1,
  checks      JSONB NOT NULL DEFAULT '[]',     -- lista de comandos/chequeos sugeridos
  fixes       JSONB NOT NULL DEFAULT '[]',     -- lista de acciones sugeridas
  created_by  TEXT,
  updated_by  TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS kb_matchers (
  id        BIGSERIAL PRIMARY KEY,
  kb_id     BIGINT NOT NULL REFERENCES kb_items(id) ON DELETE CASCADE,
  kind      TEXT   NOT NULL CHECK (kind IN ('alertname','namespace','label','regex')),
  field     TEXT,         -- para kind='label' => nombre de la label
  operator  TEXT   NOT NULL CHECK (operator IN ('eq','contains','regex')),
  value     TEXT   NOT NULL
);

-- Trigger para updated_at en kb_items
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER
LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END$$;

DROP TRIGGER IF EXISTS kb_items_set_updated_at ON kb_items;
CREATE TRIGGER kb_items_set_updated_at
BEFORE UPDATE ON kb_items
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- =========================
-- Índices recomendados
-- =========================
CREATE INDEX IF NOT EXISTS alerts_alertname_idx        ON alerts (alertname);
CREATE INDEX IF NOT EXISTS alerts_ns_idx               ON alerts ((labels->>'namespace'));
CREATE INDEX IF NOT EXISTS decisions_alert_id_idx      ON decisions (alert_id);
CREATE INDEX IF NOT EXISTS kb_items_enabled_idx        ON kb_items (enabled) WHERE enabled = TRUE;
CREATE INDEX IF NOT EXISTS kb_matchers_kb_idx          ON kb_matchers (kb_id);

-- (Opcional futuro)
-- CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- para ILIKE/regex más rápido
-- CREATE EXTENSION IF NOT EXISTS vector;    -- para similitud semántica (pgvector)
