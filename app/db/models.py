from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.contracts import FileType, IngestionJobStatus, IngestionStats
from app.schemas.job import RETRYABLE_STATUSES, TERMINAL_STATUSES

__all__ = [
    "DuplicateIngestionError",
    "IngestionJob",
    "IngestionJobStatus",
    "RETRYABLE_STATUSES",
    "TERMINAL_STATUSES",
]


class IngestionJob(BaseModel):
    id: UUID
    content_hash: str
    file_type: FileType
    original_filename: str
    media_type: str
    minio_bucket: str
    minio_object_key: str
    status: IngestionJobStatus
    error_message: str | None = None
    error_stage: IngestionJobStatus | None = None
    retry_count: int = 0
    events_published: int | None = None
    stats: IngestionStats | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class DuplicateIngestionError(Exception):
    def __init__(self, existing: IngestionJob) -> None:
        self.existing = existing
        super().__init__(f"Ingesta duplicada (hash={existing.content_hash})")
