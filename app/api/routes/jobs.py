from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from app.db.repository import IngestionJobRepository
from app.schemas.job import IngestionJobResponse, job_to_response
from app.services.pipeline import IngestionPipeline
from app.services.validators import QrStatusValidationError

router = APIRouter(prefix="/api/v1/ingest/jobs", tags=["ingestion-jobs"])

_repo = IngestionJobRepository()
_pipeline = IngestionPipeline(_repo)


@router.get("/{job_id}", response_model=IngestionJobResponse, summary="Estado de una ingesta")
async def get_job(job_id: UUID):
    job = await _repo.get_by_id(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    return job_to_response(job)


@router.post("/{job_id}/retry", summary="Reintentar ingesta fallida desde S3")
async def retry_job(
    job_id: UUID,
    publish: bool = Query(True, description="Publicar eventos en SNS"),
    strict_status: bool = Query(
        True,
        description="Rechazar el archivo QR si existe alguna fila con estado distinto de Completed",
    ),
):
    try:
        return await _pipeline.retry_job(
            job_id,
            publish=publish,
            strict_status=strict_status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except QrStatusValidationError as exc:
        from app.api.routes.ingest import _validation_error_response

        raise _validation_error_response(exc) from exc
