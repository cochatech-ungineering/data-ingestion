from pathlib import Path
from uuid import UUID, uuid4

import polars as pl

from app.schemas.contracts import (
    IngestionStats,
    QrIngestionCompletedEvent,
    QrPaymentTransaction,
    QrStatusValidationReport,
    QrTransactionsBatchEvent,
)
from app.services.cleaners._dates import parse_qr_datetime
from app.services.validators import validate_qr_completed_status

QR_COLUMN_MAP = {
    "Número de cotización": "quote_number",
    "Fecha de creación": "created_at_raw",
    "Estado": "status",
    "Creado por": "user_alias",
    "Número de Cuenta": "account_number",
    "Monto intercambio": "amount_usdt",
    "Monto Pagado": "amount_bob",
    "Precio": "exchange_rate",
    "Comisión": "commission_usdt",
    "Transacción Id": "transaction_id",
    "Tipo de servicio": "service_code",
}

KEEP_COLUMNS = list(QR_COLUMN_MAP.keys())

_AMOUNT_COLUMNS = ("amount_bob", "amount_usdt", "exchange_rate", "commission_usdt")


def _normalize_amount_columns(df: pl.DataFrame) -> pl.DataFrame:
    expressions = []
    for column in _AMOUNT_COLUMNS:
        if column in df.columns:
            expressions.append(
                pl.col(column)
                .cast(pl.Utf8)
                .str.replace_all(",", "")
                .cast(pl.Float64)
                .alias(column)
            )
    return df.with_columns(expressions) if expressions else df


def _read_qr_csv(source: Path | str) -> pl.DataFrame:
    return pl.read_csv(
        source,
        infer_schema_length=10_000,
        null_values=["", "NA", "N/A"],
    )


def _transform(df: pl.DataFrame) -> pl.DataFrame:
    missing = [col for col in KEEP_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"Columnas requeridas ausentes en CSV QR: {missing}")

    cleaned = (
        df.select(KEEP_COLUMNS)
        .rename(QR_COLUMN_MAP)
        .filter(pl.col("service_code") == "S-001")
        .pipe(_normalize_amount_columns)
        .with_columns(
            pl.col("quote_number").cast(pl.Int64),
            pl.col("account_number").cast(pl.Utf8),
            pl.col("transaction_id").cast(pl.Utf8),
            pl.col("user_alias").str.strip_chars(),
        )
        .filter(pl.col("amount_bob") > 0)
        .filter(pl.col("amount_usdt") >= 0)
        .filter(pl.col("exchange_rate") > 0)
        .unique(subset=["transaction_id"], keep="first")
        .sort("created_at_raw")
    )
    return cleaned


def _to_transactions(df: pl.DataFrame) -> list[QrPaymentTransaction]:
    transactions: list[QrPaymentTransaction] = []
    for row in df.iter_rows(named=True):
        transactions.append(
            QrPaymentTransaction(
                quote_number=row["quote_number"],
                transaction_id=row["transaction_id"],
                user_alias=row["user_alias"],
                account_number=row["account_number"],
                status="completed",
                amount_bob=row["amount_bob"],
                amount_usdt=row["amount_usdt"],
                exchange_rate=row["exchange_rate"],
                commission_usdt=row["commission_usdt"],
                created_at=parse_qr_datetime(row["created_at_raw"]),
                service_code="S-001",
            )
        )
    return transactions


def _build_stats(transactions: list[QrPaymentTransaction]) -> IngestionStats:
    if not transactions:
        return IngestionStats(
            total_records=0,
            total_amount_bob=0.0,
            total_amount_usdt=0.0,
            unique_users=0,
        )

    created_dates = [tx.created_at for tx in transactions]
    return IngestionStats(
        total_records=len(transactions),
        total_amount_bob=round(sum(tx.amount_bob for tx in transactions), 2),
        total_amount_usdt=round(sum(tx.amount_usdt for tx in transactions), 4),
        unique_users=len({tx.user_alias for tx in transactions}),
        period_start=min(created_dates),
        period_end=max(created_dates),
    )


def clean_qr_payments(
    source: Path | str,
    *,
    report_id: UUID | None = None,
    source_file: str | None = None,
    chunk_size: int = 500,
    strict_status: bool = True,
) -> tuple[
    list[QrPaymentTransaction],
    IngestionStats,
    list[QrTransactionsBatchEvent],
    QrIngestionCompletedEvent,
    QrStatusValidationReport,
]:
    path = Path(source)
    report_id = report_id or uuid4()
    source_file = source_file or path.name

    raw = _read_qr_csv(path)
    status_validated, validation = validate_qr_completed_status(raw, strict=strict_status)
    transformed = _transform(status_validated)
    transactions = _to_transactions(transformed)
    stats = _build_stats(transactions)

    batches: list[QrTransactionsBatchEvent] = []
    if transactions:
        batch_count = (len(transactions) + chunk_size - 1) // chunk_size
        for index in range(batch_count):
            start = index * chunk_size
            end = start + chunk_size
            batches.append(
                QrTransactionsBatchEvent(
                    report_id=report_id,
                    source_file=source_file,
                    batch_index=index,
                    batch_count=batch_count,
                    transactions=transactions[start:end],
                )
            )

    completed = QrIngestionCompletedEvent(
        report_id=report_id,
        source_file=source_file,
        stats=stats,
        published_batches=len(batches),
    )
    return transactions, stats, batches, completed, validation
