"""Initialiserer Postgres-skjema for NAV Archive V2.1."""
import os, sys
sys.path.insert(0, ".")
from config.config_loader import CONFIG

POSTGRES_URL = os.environ.get("POSTGRES_URL", CONFIG["postgres"]["url"])

SQL = """
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

DO $$ BEGIN
    CREATE TYPE job_state AS ENUM (
        'UPLOADED', 'QUEUED', 'PREPROCESSING', 'OCR_PROCESSING',
        'NLP_PROCESSING', 'VALIDATION', 'ROUTING', 'DONE', 'FAILED'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS jobs (
    job_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    idempotency_key TEXT UNIQUE NOT NULL,
    state           job_state NOT NULL DEFAULT 'UPLOADED',
    current_stage   TEXT,
    file_path       TEXT NOT NULL,
    file_name       TEXT NOT NULL,
    priority        INT DEFAULT 1,
    attempt_count   INT DEFAULT 0,
    max_retries     INT DEFAULT 3,
    last_error      TEXT,
    locked_by       TEXT,
    lock_expiry     TIMESTAMP,
    -- Flersidige dokumenter: én jobb per side, gruppert på dokument_id
    dokument_id     UUID,
    side_nummer     INT DEFAULT 0,
    antall_sider    INT DEFAULT 1,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW(),
    completed_at    TIMESTAMP
);

-- Idempotente migreringer for eksisterende databaser
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS dokument_id  UUID;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS side_nummer  INT DEFAULT 0;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS antall_sider INT DEFAULT 1;
CREATE INDEX IF NOT EXISTS jobs_dokument_id_idx ON jobs (dokument_id);

CREATE TABLE IF NOT EXISTS results (
    job_id              UUID PRIMARY KEY REFERENCES jobs(job_id),
    preprocess_result   JSONB,
    ocr_result          JSONB,
    nlp_result          JSONB,
    validation_result   JSONB,
    routing_decision    TEXT CHECK (routing_decision IN ('APPROVED', 'REVIEW', 'REJECTED')),
    label_studio_project INT,
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          BIGSERIAL PRIMARY KEY,
    job_id      UUID REFERENCES jobs(job_id),
    event_type  TEXT NOT NULL,
    from_state  TEXT,
    to_state    TEXT,
    worker_id   TEXT,
    details     JSONB,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS dead_letter_queue (
    id               BIGSERIAL PRIMARY KEY,
    job_id           UUID REFERENCES jobs(job_id),
    stage            TEXT NOT NULL,
    error_type       TEXT NOT NULL,
    error_message    TEXT,
    payload_snapshot JSONB,
    retry_count      INT,
    created_at       TIMESTAMP DEFAULT NOW(),
    resolved_at      TIMESTAMP,
    resolved_by      TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_state      ON jobs(state);
-- idx_jobs_idempotency fjernet (F2-9): idempotency_key har allerede UNIQUE →
-- implisitt indeks. Duplikat koster kun skrive-overhead.
CREATE INDEX IF NOT EXISTS idx_jobs_lock_expiry ON jobs(lock_expiry) WHERE locked_by IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_audit_job        ON audit_log(job_id);
CREATE INDEX IF NOT EXISTS idx_audit_time       ON audit_log(created_at);
CREATE INDEX IF NOT EXISTS idx_dlq_job          ON dead_letter_queue(job_id);

-- F2-6: reconciliation-spørringer full-scanner uten disse ved 60M rader.
-- ettersend_label_studio filtrerer på audit_log.event_type og
-- results.routing_decision; ghost/tapt-deteksjon på jobs(state,updated_at).
CREATE INDEX IF NOT EXISTS idx_audit_event      ON audit_log(event_type, id);
CREATE INDEX IF NOT EXISTS idx_jobs_state_upd    ON jobs(state, updated_at);
CREATE INDEX IF NOT EXISTS idx_results_beslutning ON results(routing_decision)
    WHERE routing_decision IN ('REVIEW', 'REJECTED');

-- F1-5/F2-9: deklarativ garanti mot duplikate sider i et dokument.
CREATE UNIQUE INDEX IF NOT EXISTS unik_dokument_side
    ON jobs(dokument_id, side_nummer) WHERE dokument_id IS NOT NULL;
"""

def init_db():
    import psycopg2
    print(f"Kobler til: {POSTGRES_URL.split('@')[-1]}")
    conn = psycopg2.connect(POSTGRES_URL)
    cur = conn.cursor()
    cur.execute(SQL)
    conn.commit()
    cur.close()
    conn.close()
    print("Tabeller opprettet: jobs, results, audit_log, dead_letter_queue")

if __name__ == "__main__":
    init_db()
