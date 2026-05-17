from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


SCHEMA_VERSION = "1.0.0"


class FileType(str, Enum):
    QR_PAYMENTS = "qr_payments"
    TRANSFERS = "transfers"


class IngestionJobStatus(str, Enum):
    RECEIVED = "received"
    STORED = "stored"
    CONVERTING = "converting"
    PROCESSING = "processing"
    PUBLISHING = "publishing"
    COMPLETED = "completed"
    FAILED = "failed"


class QrPaymentTransaction(BaseModel):
    quote_number: int
    transaction_id: str
    user_alias: str
    account_number: str
    status: Literal["completed"]
    amount_bob: float = Field(ge=0)
    amount_usdt: float = Field(ge=0)
    exchange_rate: float = Field(gt=0)
    commission_usdt: float = Field(ge=0)
    created_at: datetime
    service_code: Literal["S-001"] = "S-001"


class TransferTransaction(BaseModel):
    transfer_number: int
    amount_usdt: float = Field(gt=0)
    sender_account_number: str
    sender_alias: str
    receiver_account_number: str
    receiver_alias: str
    product_symbol: Literal["USDT"] = "USDT"
    created_at: datetime
    service_code: Literal["S-005"] = "S-005"


class QrStatusValidationReport(BaseModel):
    total_rows: int
    completed_rows: int
    excluded_rows: int
    status_breakdown: dict[str, int]
    required_status: Literal["Completed"] = "Completed"
    passed: bool


class IngestionStats(BaseModel):
    total_records: int
    total_amount_bob: float | None = None
    total_amount_usdt: float | None = None
    unique_users: int
    period_start: datetime | None = None
    period_end: datetime | None = None


class QrTransactionsBatchEvent(BaseModel):
    schema_version: str = SCHEMA_VERSION
    event_type: Literal["qr_transactions_batch"] = "qr_transactions_batch"
    report_id: UUID
    source_file: str
    batch_index: int
    batch_count: int
    transactions: list[QrPaymentTransaction]


class QrIngestionCompletedEvent(BaseModel):
    schema_version: str = SCHEMA_VERSION
    event_type: Literal["qr_ingestion_completed"] = "qr_ingestion_completed"
    report_id: UUID
    source_file: str
    file_type: Literal[FileType.QR_PAYMENTS] = FileType.QR_PAYMENTS
    stats: IngestionStats
    published_batches: int


class TransfersIngestionCompletedEvent(BaseModel):
    schema_version: str = SCHEMA_VERSION
    event_type: Literal["transfers_ingestion_completed"] = "transfers_ingestion_completed"
    report_id: UUID
    source_file: str
    file_type: Literal[FileType.TRANSFERS] = FileType.TRANSFERS
    stats: IngestionStats
    transfers: list[TransferTransaction]


class IngestionResponse(BaseModel):
    report_id: UUID
    job_status: IngestionJobStatus | None = None
    file_type: FileType
    source_file: str
    validation: QrStatusValidationReport | None = None
    stats: IngestionStats
    events_published: int
    events_archive_dir: str | None = None
    sample_transactions: list[dict] | None = None


