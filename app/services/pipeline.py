import hashlib
import logging
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID, uuid4

from app.db.models import DuplicateIngestionError, IngestionJob
from app.schemas.contracts import IngestionJobStatus
from app.schemas.job import RETRYABLE_STATUSES
from app.db.repository import IngestionJobRepository
from app.schemas.contracts import FileType, IngestionResponse
from app.services.file_converter import materialize_as_csv, media_type_for_extension, validate_upload_filename
from app.services.ingest import ingest_qr_file, ingest_transfers_file
from app.services.validators import QrStatusValidationError
from app.storage.minio_storage import raw_file_storage

logger = logging.getLogger(__name__)


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class IngestionPipeline:
    def __init__(self, repository: IngestionJobRepository | None = None) -> None:
        self._repo = repository or IngestionJobRepository()

    async def ingest_upload(
        self,
        *,
        data: bytes,
        filename: str,
        file_type: FileType,
        publish: bool = True,
        strict_status: bool = True,
    ) -> IngestionResponse:
        if not data:
            raise ValueError("El archivo está vacío.")

        suffix = validate_upload_filename(filename)
        digest = content_hash(data)

        existing = await self._repo.get_by_content_hash(digest)
        if existing is not None:
            if existing.status in RETRYABLE_STATUSES:
                logger.info(
                    "Archivo duplicado con job en failed; reintento automático %s (sin republicar en SNS)",
                    existing.id,
                )
                return await self.retry_job(
                    existing.id,
                    publish=False,
                    strict_status=strict_status,
                )
            raise DuplicateIngestionError(existing)

        job_id = uuid4()
        object_key = raw_file_storage.build_object_key(
            job_id=job_id,
            file_type=file_type,
            original_filename=filename,
        )

        job = await self._repo.create_received(
            job_id=job_id,
            content_hash=digest,
            file_type=file_type,
            original_filename=filename,
            media_type=media_type_for_extension(suffix),
            minio_bucket=raw_file_storage.bucket,
            minio_object_key=object_key,
        )

        try:
            raw_file_storage.upload_bytes(
                object_key=object_key,
                data=data,
                content_type=job.media_type,
            )
            job = await self._repo.update_status(job.id, IngestionJobStatus.STORED)
            return await self._process_stored_job(
                job,
                publish=publish,
                strict_status=strict_status,
            )
        except DuplicateIngestionError:
            raise
        except Exception as exc:
            logger.exception("Error en ingesta %s", job.id)
            await self._repo.mark_failed(
                job.id,
                error_message=str(exc),
                error_stage=job.status,
            )
            raise

    async def retry_job(
        self,
        job_id: UUID,
        *,
        publish: bool = True,
        strict_status: bool = True,
    ) -> IngestionResponse:
        job = await self._repo.get_by_id(job_id)
        if job is None:
            raise ValueError(f"Job {job_id} no encontrado")
        if job.status not in RETRYABLE_STATUSES:
            raise ValueError(
                f"Solo se puede reintentar jobs en estado failed (actual: {job.status.value})"
            )

        job = await self._repo.increment_retry(job_id)
        return await self._process_stored_job(job, publish=publish, strict_status=strict_status)

    async def _process_stored_job(
        self,
        job: IngestionJob,
        *,
        publish: bool,
        strict_status: bool,
    ) -> IngestionResponse:
        raw_path: Path | None = None
        csv_path: Path | None = None
        delete_csv = False
        current_stage = IngestionJobStatus.STORED

        try:
            suffix = Path(job.original_filename).suffix or ".bin"
            with NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                raw_path = Path(tmp.name)
            raw_file_storage.download_to_path(object_key=job.minio_object_key, destination=raw_path)

            current_stage = IngestionJobStatus.CONVERTING
            job = await self._repo.update_status(job.id, current_stage)
            csv_path, delete_csv = materialize_as_csv(raw_path)

            current_stage = IngestionJobStatus.PROCESSING
            job = await self._repo.update_status(job.id, current_stage)

            async def on_publishing() -> None:
                nonlocal job, current_stage
                current_stage = IngestionJobStatus.PUBLISHING
                job = await self._repo.update_status(job.id, current_stage)

            if job.file_type == FileType.QR_PAYMENTS:
                result = await ingest_qr_file(
                    csv_path,
                    source_file=job.original_filename,
                    report_id=job.id,
                    publish=publish,
                    strict_status=strict_status,
                    on_publishing=on_publishing,
                )
            else:
                result = await ingest_transfers_file(
                    csv_path,
                    source_file=job.original_filename,
                    report_id=job.id,
                    publish=publish,
                    on_publishing=on_publishing,
                )

            await self._repo.update_status(
                job.id,
                IngestionJobStatus.COMPLETED,
                events_published=result.events_published,
                stats=result.stats,
                clear_error=True,
            )
            return result.model_copy(update={"job_status": IngestionJobStatus.COMPLETED})
        except QrStatusValidationError:
            await self._repo.mark_failed(
                job.id,
                error_message="Validación de estados QR fallida",
                error_stage=current_stage,
            )
            raise
        except Exception as exc:
            await self._repo.mark_failed(
                job.id,
                error_message=str(exc),
                error_stage=current_stage,
            )
            raise
        finally:
            if raw_path is not None:
                raw_path.unlink(missing_ok=True)
            if delete_csv and csv_path is not None:
                csv_path.unlink(missing_ok=True)
