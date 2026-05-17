from pathlib import Path
from uuid import UUID, uuid4

import polars as pl

from app.schemas.contracts import IngestionStats, TransferTransaction
from app.services.cleaners._dates import parse_transfer_date

TRANSFER_COLUMN_MAP = {
    "createdAt": "created_at_raw",
    "transferNumber": "transfer_number",
    "amount": "amount_usdt",
    "senderAccount.accountNumber": "sender_account_number",
    "senderAccount.alias": "sender_alias",
    "receiverAccount.accountNumber": "receiver_account_number",
    "receiverAccount.alias": "receiver_alias",
    "product.symbol": "product_symbol",
    "Tipo de servicio": "service_code",
}

KEEP_COLUMNS = list(TRANSFER_COLUMN_MAP.keys())


def _read_transfers_csv(source: Path | str) -> pl.DataFrame:
    return pl.read_csv(source, infer_schema_length=5_000)


def _transform(df: pl.DataFrame) -> pl.DataFrame:
    missing = [col for col in KEEP_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"Columnas requeridas ausentes en CSV de transferencias: {missing}")

    return (
        df.select(KEEP_COLUMNS)
        .rename(TRANSFER_COLUMN_MAP)
        .filter(pl.col("service_code") == "S-005")
        .filter(pl.col("product_symbol") == "USDT")
        .with_columns(
            pl.col("transfer_number").cast(pl.Int64),
            pl.col("amount_usdt").cast(pl.Float64),
            pl.col("sender_account_number").cast(pl.Utf8),
            pl.col("receiver_account_number").cast(pl.Utf8),
            pl.col("sender_alias").str.strip_chars(),
            pl.col("receiver_alias").str.strip_chars(),
        )
        .filter(pl.col("amount_usdt") > 0)
        .unique(subset=["transfer_number"], keep="first")
        .sort("created_at_raw")
    )


def clean_transfers(
    source: Path | str,
    *,
    report_id: UUID | None = None,
) -> tuple[list[TransferTransaction], IngestionStats, UUID]:
    path = Path(source)
    report_id = report_id or uuid4()

    transformed = _transform(_read_transfers_csv(path))
    transfers: list[TransferTransaction] = []
    for row in transformed.iter_rows(named=True):
        transfers.append(
            TransferTransaction(
                transfer_number=row["transfer_number"],
                amount_usdt=row["amount_usdt"],
                sender_account_number=row["sender_account_number"],
                sender_alias=row["sender_alias"],
                receiver_account_number=row["receiver_account_number"],
                receiver_alias=row["receiver_alias"],
                created_at=parse_transfer_date(row["created_at_raw"]),
            )
        )

    if not transfers:
        stats = IngestionStats(total_records=0, unique_users=0, total_amount_usdt=0.0)
    else:
        participants = {t.sender_alias for t in transfers} | {t.receiver_alias for t in transfers}
        created_dates = [t.created_at for t in transfers]
        stats = IngestionStats(
            total_records=len(transfers),
            total_amount_usdt=round(sum(t.amount_usdt for t in transfers), 4),
            unique_users=len(participants),
            period_start=min(created_dates),
            period_end=max(created_dates),
        )

    return transfers, stats, report_id
