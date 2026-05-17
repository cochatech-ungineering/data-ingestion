from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from app.schemas.contracts import FileType, QrStatusValidationReport
from app.services.ingest import ingest_qr_file, ingest_transfers_file
from app.services.validators import QrStatusValidationError

router = APIRouter(prefix="/api/v1/ingest", tags=["ingest"])

DATA_DIR = Path(__file__).resolve().parents[3] / "data"

QR_SAMPLE = DATA_DIR / "Reportes Banexcoin Bolivia Hackaton 2026.xlsx - Pago QR.csv"
TRANSFERS_SAMPLE = DATA_DIR / "Reportes Banexcoin Bolivia Hackaton 2026.xlsx - Transfers.csv"


async def _save_upload(upload: UploadFile) -> Path:
    suffix = Path(upload.filename or "upload.csv").suffix or ".csv"
    with NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await upload.read()
        if not content:
            raise HTTPException(status_code=400, detail="El archivo está vacío.")
        tmp.write(content)
        return Path(tmp.name)


def _validation_error_response(exc: QrStatusValidationError) -> HTTPException:
    report: QrStatusValidationReport = exc.report
    return HTTPException(
        status_code=422,
        detail={
            "message": str(exc),
            "validation": report.model_dump(),
        },
    )


@router.post("/qr-payments", summary="Ingerir reporte CSV de pagos QR")
async def ingest_qr_payments(
    file: UploadFile = File(..., description="CSV mensual de pagos QR"),
    publish: bool = Query(True, description="Publicar eventos en RabbitMQ"),
    strict_status: bool = Query(
        True,
        description="Rechazar el archivo si existe alguna fila con estado distinto de Completed",
    ),
):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Se espera un archivo .csv")

    tmp_path = await _save_upload(file)
    try:
        return await ingest_qr_file(
            tmp_path,
            source_file=file.filename,
            publish=publish,
            strict_status=strict_status,
        )
    except QrStatusValidationError as exc:
        raise _validation_error_response(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)


@router.post("/transfers", summary="Ingerir reporte CSV de transferencias USDT")
async def ingest_transfers(
    file: UploadFile = File(..., description="CSV de transferencias internas"),
    publish: bool = Query(True, description="Publicar eventos en RabbitMQ"),
):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Se espera un archivo .csv")

    tmp_path = await _save_upload(file)
    try:
        return await ingest_transfers_file(tmp_path, source_file=file.filename, publish=publish)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)


@router.post("/demo", summary="Procesar los CSV de ejemplo en /data")
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
