from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel

from app.schemas.contracts import FileType, IngestionJobStatus, IngestionStats

if TYPE_CHECKING:
    from app.db.models import IngestionJob

RETRYABLE_STATUSES = frozenset({IngestionJobStatus.FAILED})
TERMINAL_STATUSES = frozenset({IngestionJobStatus.COMPLETED, IngestionJobStatus.FAILED})


class IngestionJobResponse(BaseModel):
    id: UUID
    status: IngestionJobStatus
    file_type: FileType
    original_filename: str
    content_hash: str
    minio_bucket: str
    minio_object_key: str
    retry_count: int
    error_message: str | None = None
    error_stage: IngestionJobStatus | None = None
    events_published: int | None = None
    stats: IngestionStats | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class DuplicateIngestionResponse(BaseModel):
    message: str = "Archivo ya ingerido (contenido duplicado)"
    existing_job: IngestionJobResponse
    retry_url: str | None = None


def job_to_response(job: "IngestionJob") -> IngestionJobResponse:
    return IngestionJobResponse(
        id=job.id,
        status=job.status,
        file_type=job.file_type,
        original_filename=job.original_filename,
        content_hash=job.content_hash,
        minio_bucket=job.minio_bucket,
        minio_object_key=job.minio_object_key,
        retry_count=job.retry_count,
        error_message=job.error_message,
        error_stage=job.error_stage,
        events_published=job.events_published,
        stats=job.stats,
        created_at=job.created_at,
        updated_at=job.updated_at,
        completed_at=job.completed_at,
    )
