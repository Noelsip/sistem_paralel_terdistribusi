CREATE TABLE IF NOT EXISTS processed_events (
    seq         BIGSERIAL PRIMARY KEY,     -- monotonic counter (Bab 5: ordering)
    topic       TEXT        NOT NULL,
    event_id    TEXT        NOT NULL,
    event_ts    TIMESTAMPTZ NOT NULL,      -- timestamp dari event (ISO8601)
    source      TEXT        NOT NULL,
    payload     JSONB       NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_topic_event UNIQUE (topic, event_id)
);

CREATE INDEX IF NOT EXISTS idx_processed_topic ON processed_events (topic);
CREATE INDEX IF NOT EXISTS idx_processed_topic_seq ON processed_events (topic, seq);

CREATE TABLE IF NOT EXISTS aggregator_stats (
    metric TEXT PRIMARY KEY,
    value  BIGINT NOT NULL DEFAULT 0
);

INSERT INTO aggregator_stats (metric, value) VALUES
    ('received', 0),
    ('unique_processed', 0),
    ('duplicate_dropped', 0)
ON CONFLICT (metric) DO NOTHING;


CREATE TABLE IF NOT EXISTS audit_log (
    id         BIGSERIAL PRIMARY KEY,
    topic      TEXT NOT NULL,
    event_id   TEXT NOT NULL,
    action     TEXT NOT NULL,             -- 'processed' | 'duplicate'
    worker     TEXT,
    logged_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_event ON audit_log (topic, event_id);
