import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

import asyncpg

from app.db.connection import get_pool
from app.db.models import DuplicateIngestionError, IngestionJob
from app.schemas.contracts import IngestionJobStatus
from app.schemas.contracts import FileType, IngestionStats


def _parse_stats(raw: object | None) -> IngestionStats | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        return IngestionStats.model_validate_json(raw)
    return IngestionStats.model_validate(raw)


def _row_to_job(row: asyncpg.Record) -> IngestionJob:
    stats = _parse_stats(row["stats"])
    error_stage = row["error_stage"]
    return IngestionJob(
        id=row["id"],
        content_hash=row["content_hash"],
        file_type=FileType(row["file_type"]),
        original_filename=row["original_filename"],
        media_type=row["media_type"],
        minio_bucket=row["minio_bucket"],
        minio_object_key=row["minio_object_key"],
        status=IngestionJobStatus(row["status"]),
        error_message=row["error_message"],
        error_stage=IngestionJobStatus(error_stage) if error_stage else None,
        retry_count=row["retry_count"],
        events_published=row["events_published"],
        stats=stats,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_at=row["completed_at"],
    )


class IngestionJobRepository:
    async def get_by_id(self, job_id: UUID) -> IngestionJob | None:
        pool = get_pool()
        row = await pool.fetchrow("SELECT * FROM ingestion_jobs WHERE id = $1", job_id)
        return _row_to_job(row) if row else None

    async def get_by_content_hash(self, content_hash: str) -> IngestionJob | None:
        pool = get_pool()
        row = await pool.fetchrow(
            "SELECT * FROM ingestion_jobs WHERE content_hash = $1",
            content_hash,
        )
        return _row_to_job(row) if row else None

    async def create_received(
        self,
        *,
        content_hash: str,
        file_type: FileType,
        original_filename: str,
        media_type: str,
        minio_bucket: str,
        minio_object_key: str,
        job_id: UUID | None = None,
    ) -> IngestionJob:
        pool = get_pool()
        job_id = job_id or uuid4()
        now = datetime.now(timezone.utc)
        try:
            row = await pool.fetchrow(
                """
                INSERT INTO ingestion_jobs (
                    id, content_hash, file_type, original_filename, media_type,
                    minio_bucket, minio_object_key, status, created_at, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $9)
                RETURNING *
                """,
                job_id,
                content_hash,
                file_type.value,
                original_filename,
                media_type,
                minio_bucket,
                minio_object_key,
                IngestionJobStatus.RECEIVED.value,
                now,
            )
        except asyncpg.UniqueViolationError:
            existing = await self.get_by_content_hash(content_hash)
            if existing is None:
                raise
            raise DuplicateIngestionError(existing) from None
        return _row_to_job(row)

    async def update_status(
        self,
        job_id: UUID,
        status: IngestionJobStatus,
        *,
        error_message: str | None = None,
        error_stage: IngestionJobStatus | None = None,
        events_published: int | None = None,
        stats: IngestionStats | None = None,
        clear_error: bool = False,
    ) -> IngestionJob:
        pool = get_pool()
        now = datetime.now(timezone.utc)
        completed_at = now if status == IngestionJobStatus.COMPLETED else None
        stats_json = stats.model_dump_json() if stats else None

        row = await pool.fetchrow(
            """
            UPDATE ingestion_jobs
            SET status = $2,
                error_message = CASE WHEN $9 THEN NULL ELSE COALESCE($3, error_message) END,
                error_stage = CASE WHEN $9 THEN NULL ELSE COALESCE($4, error_stage) END,
                events_published = COALESCE($5, events_published),
                stats = COALESCE($6::jsonb, stats),
                updated_at = $7,
                completed_at = COALESCE($8, completed_at)
            WHERE id = $1
            RETURNING *
            """,
            job_id,
            status.value,
            error_message,
            error_stage.value if error_stage else None,
            events_published,
            stats_json,
            now,
            completed_at,
            clear_error,
        )
        if row is None:
            raise ValueError(f"Job {job_id} no encontrado")
        return _row_to_job(row)

    async def mark_failed(
        self,
        job_id: UUID,
        *,
        error_message: str,
        error_stage: IngestionJobStatus,
    ) -> IngestionJob:
        return await self.update_status(
            job_id,
            IngestionJobStatus.FAILED,
            error_message=error_message,
            error_stage=error_stage,
        )

    async def increment_retry(self, job_id: UUID) -> IngestionJob:
        pool = get_pool()
        now = datetime.now(timezone.utc)
        row = await pool.fetchrow(
            """
            UPDATE ingestion_jobs
            SET retry_count = retry_count + 1,
                status = $2,
                error_message = NULL,
                error_stage = NULL,
                completed_at = NULL,
                updated_at = $3
            WHERE id = $1
            RETURNING *
            """,
            job_id,
            IngestionJobStatus.STORED.value,
            now,
        )
        if row is None:
            raise ValueError(f"Job {job_id} no encontrado")
        return _row_to_job(row)
