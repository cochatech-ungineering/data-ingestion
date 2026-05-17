from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from app.db.models import DuplicateIngestionError
from app.schemas.contracts import FileType, IngestionJobStatus, QrStatusValidationReport
from app.schemas.job import DuplicateIngestionResponse, job_to_response
from app.services.file_converter import ALLOWED_EXTENSIONS, validate_upload_filename
from app.services.ingest import ingest_qr_file, ingest_transfers_file
from app.services.pipeline import IngestionPipeline
from app.services.validators import QrStatusValidationError

router = APIRouter(prefix="/api/v1/ingest", tags=["ingest"])

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
QR_SAMPLE = DATA_DIR / "Reportes Banexcoin Bolivia Hackaton 2026.xlsx - Pago QR.csv"
TRANSFERS_SAMPLE = DATA_DIR / "Reportes Banexcoin Bolivia Hackaton 2026.xlsx - Transfers.csv"

_pipeline = IngestionPipeline()


def _validation_error_response(exc: QrStatusValidationError) -> HTTPException:
    report: QrStatusValidationReport = exc.report
    return HTTPException(
        status_code=422,
        detail={
            "message": str(exc),
            "validation": report.model_dump(mode="json"),
        },
    )


def _duplicate_response(exc: DuplicateIngestionError) -> HTTPException:
    job = exc.existing
    retry_url = f"/api/v1/ingest/jobs/{job.id}/retry"
    if job.status == IngestionJobStatus.FAILED:
        message = (
            "Archivo ya ingerido. El job anterior falló; "
            f"reintenta con POST {retry_url} o vuelve a subir el mismo archivo."
        )
    else:
        message = "Archivo ya ingerido (contenido duplicado)."

    body = DuplicateIngestionResponse(
        message=message,
        existing_job=job_to_response(job),
        retry_url=retry_url if job.status == IngestionJobStatus.FAILED else None,
    )
    return HTTPException(status_code=409, detail=body.model_dump(mode="json"))


async def _read_upload(upload: UploadFile) -> tuple[bytes, str]:
    if not upload.filename:
        raise HTTPException(status_code=400, detail="Nombre de archivo requerido.")
    try:
        validate_upload_filename(upload.filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    content = await upload.read()
    if not content:
        raise HTTPException(status_code=400, detail="El archivo está vacío.")
    return content, upload.filename


@router.post("/qr-payments", summary="Ingerir reporte de pagos QR")
async def ingest_qr_payments(
    file: UploadFile = File(..., description="CSV, XLS, XLSX, JSON o TXT de pagos QR"),
    publish: bool = Query(True, description="Publicar eventos en SNS"),
    strict_status: bool = Query(
        True,
        description="Rechazar el archivo si existe alguna fila con estado distinto de Completed",
    ),
):
    content, filename = await _read_upload(file)
    try:
        return await _pipeline.ingest_upload(
            data=content,
            filename=filename,
            file_type=FileType.QR_PAYMENTS,
            publish=publish,
            strict_status=strict_status,
        )
    except DuplicateIngestionError as exc:
        raise _duplicate_response(exc) from exc
    except QrStatusValidationError as exc:
        raise _validation_error_response(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/transfers", summary="Ingerir reporte de transferencias USDT")
async def ingest_transfers(
    file: UploadFile = File(
        ...,
        description="CSV, XLS, XLSX, JSON o TXT de transferencias internas",
    ),
    publish: bool = Query(True, description="Publicar eventos en SNS"),
):
    content, filename = await _read_upload(file)
    try:
        return await _pipeline.ingest_upload(
            data=content,
            filename=filename,
            file_type=FileType.TRANSFERS,
            publish=publish,
        )
    except DuplicateIngestionError as exc:
        raise _duplicate_response(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/demo", summary="Procesar los CSV de ejemplo en /data (sin MinIO)")
async def ingest_demo_data(
    file_type: FileType = Query(FileType.QR_PAYMENTS),
    publish: bool = Query(True),
    strict_status: bool = Query(True),
):
    if file_type == FileType.QR_PAYMENTS:
        if not QR_SAMPLE.exists():
            raise HTTPException(status_code=404, detail=f"No se encontró {QR_SAMPLE.name}")
        try:
            return await ingest_qr_file(QR_SAMPLE, publish=publish, strict_status=strict_status)
        except QrStatusValidationError as exc:
            raise _validation_error_response(exc) from exc

    if not TRANSFERS_SAMPLE.exists():
        raise HTTPException(status_code=404, detail=f"No se encontró {TRANSFERS_SAMPLE.name}")
    return await ingest_transfers_file(TRANSFERS_SAMPLE, publish=publish)


@router.get("/formats", summary="Extensiones de archivo aceptadas")
def supported_formats():
    return {"extensions": sorted(ALLOWED_EXTENSIONS)}
