-- Tabla de seguimiento de ingestas (estado + referencia a MinIO)
CREATE TABLE IF NOT EXISTS ingestion_jobs (
    id UUID PRIMARY KEY,
    content_hash CHAR(64) NOT NULL UNIQUE,
    file_type VARCHAR(32) NOT NULL,
    original_filename TEXT NOT NULL,
    media_type VARCHAR(128) NOT NULL,
    minio_bucket TEXT NOT NULL,
    minio_object_key TEXT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'received',
    error_message TEXT,
    error_stage VARCHAR(32),
    retry_count INTEGER NOT NULL DEFAULT 0,
    events_published INTEGER,
    stats JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_status ON ingestion_jobs (status);
CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_file_type ON ingestion_jobs (file_type);
CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_created_at ON ingestion_jobs (created_at DESC);
