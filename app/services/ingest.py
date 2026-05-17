from collections.abc import Awaitable, Callable
from pathlib import Path
from uuid import UUID

from app.core.config import settings
from app.schemas.contracts import (
    FileType,
    IngestionResponse,
    TransfersIngestionCompletedEvent,
)
from app.services.cleaners import clean_qr_payments, clean_transfers
from app.services.publisher import preview_model, publisher


async def ingest_qr_file(
    source: Path,
    *,
    source_file: str | None = None,
    report_id: UUID | None = None,
    publish: bool = True,
    strict_status: bool = True,
    on_publishing: Callable[[], Awaitable[None]] | None = None,
) -> IngestionResponse:
    transactions, stats, batches, completed, validation = clean_qr_payments(
        source,
        report_id=report_id,
        source_file=source_file or source.name,
        chunk_size=settings.event_chunk_size,
        strict_status=strict_status,
    )

    events_published = 0
    archive_dir: str | None = None
    if publish and settings.publish_events:
        if on_publishing is not None:
            await on_publishing()
        for batch in batches:
            await publisher.publish("qr.transactions.batch", batch)
            events_published += 1
        await publisher.publish("qr.ingestion.completed", completed)
        events_published += 1
        if settings.archive_published_events:
            archive_dir = str(Path(settings.events_output_dir) / str(completed.report_id))

    sample = [preview_model(tx) for tx in transactions[:3]] if transactions else None
    return IngestionResponse(
        report_id=completed.report_id,
        job_status=None,
        file_type=FileType.QR_PAYMENTS,
        source_file=completed.source_file,
        validation=validation,
        stats=stats,
        events_published=events_published,
        events_archive_dir=archive_dir,
        sample_transactions=sample,
    )


async def ingest_transfers_file(
    source: Path,
    *,
    source_file: str | None = None,
    report_id: UUID | None = None,
    publish: bool = True,
    on_publishing: Callable[[], Awaitable[None]] | None = None,
) -> IngestionResponse:
    transfers, stats, report_id = clean_transfers(source, report_id=report_id)
    completed = TransfersIngestionCompletedEvent(
        report_id=report_id,
        source_file=source_file or source.name,
        stats=stats,
        transfers=transfers,
    )

    events_published = 0
    archive_dir: str | None = None
    if publish and settings.publish_events:
        if on_publishing is not None:
            await on_publishing()
        await publisher.publish("transfers.ingestion.completed", completed)
        events_published = 1
        if settings.archive_published_events:
            archive_dir = str(Path(settings.events_output_dir) / str(report_id))

    sample = [preview_model(tx) for tx in transfers[:3]] if transfers else None
    return IngestionResponse(
        report_id=report_id,
        job_status=None,
        file_type=FileType.TRANSFERS,
        source_file=completed.source_file,
        stats=stats,
        events_published=events_published,
        events_archive_dir=archive_dir,
        sample_transactions=sample,
    )
